"""The merged 3D map's controls, driven with real input in a real browser.

The merged view is the default 3D map, and its controls are most of what a reader does
with it. They went untested because the view loads MapLibre and deck.gl from a CDN and
this suite has no network — and two regressions shipped: a shift-drag that flung the map
two hundred kilometres (the pivot was clamped into an element with no height, so every
grab went to the horizon), and a track that vanished when airspace was switched on (the
translucent boxes wrote depth and hid everything inside them). The canvas view's controls
earned their tests the same way.

The libraries come from a local cache (`tests/vendor.py`) served from localhost, so the
no-network rule holds, and so does the terrain: the server makes terrarium tiles of a
ridged landscape on request (`_ground`), so every turn, tilt and pan below grabs ground on
a slope, hundreds of metres up — where a pivot taken from the wrong height shows. Imagery
is not fetched. In software GL the terrain makes a frame take 1-3 s (October 2026) — more
the wider the map and the steeper the view, so the window is narrow and the tilts gentle —
and every input event below waits for a frame, which is where these tests' minutes go. So
nothing here sleeps and hopes: each wait is for the thing it waits for (`_still`, `_frame`,
`Browser.wait`), checked in the page as it happens. Input goes in through the DevTools
protocol — mouse with modifiers, keys, wheel, touch — because a synthetic DOM event is
not what MapLibre's handlers see from a reader.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import http.server
import inspect
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
import zlib
from pathlib import Path

import numpy as np
import pytest

from parainsights_map import map3d, render_map, view3d
from tests import vendor
from tests.browser import CHROME, _scene

websocket = pytest.importorskip("websocket")

pytestmark = [
    pytest.mark.skipif(CHROME is None, reason="no Chrome"),
    pytest.mark.skipif(vendor.folder() is None,
                       reason="MapLibre and deck.gl not cached: python -m tests.vendor"),
]

_FLAGS = [
    # Just over the 900 px breakpoint, so the desktop layout: the map is 21:9 of the width,
    # and over terrain software GL takes 4.8 s a frame at 1200 px wide.
    "--headless", "--no-sandbox", "--window-size=920,800", "--enable-unsafe-swiftshader",
    "--use-gl=angle", "--use-angle=swiftshader", "--remote-allow-origins=*",
    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
    # A headless window counts as hidden, and Chrome then stops serving animation frames
    # whenever nothing on the page asks to be repainted — which stalls every camera loop
    # these tests drive.
    "--disable-renderer-backgrounding", "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
]


def _scene_with_time() -> dict:
    """The GL tests' ridged scene, with a time on every fix (replay and follow need it)
    and its one airspace zone covering the whole track."""
    scene = _scene(airspace=True)
    track = scene["track"]
    track["t"] = [i * 30 for i in range(len(track["lon"]))]
    ring = scene["airspaces"][0]
    ring["lon"] = [13.9, 14.4, 14.4, 13.9]
    ring["lat"] = [48.9, 48.9, 49.3, 49.3]
    ring["c"] = 6000
    # A second kind, floored high, for the airspace menu's kinds and floor.
    scene["airspaces"].append({"k": "restricted", "n": "R TEST  (3000 m – 4000 m)", "f": 3000,
                               "c": 4000, "lon": [14.0, 14.3, 14.3, 14.0],
                               "lat": [49.0, 49.0, 49.2, 49.2]})
    scene["airspaceColours"]["restricted"] = "#b91c1c"
    scene["airspaceClasses"] = [["base", "Controlled"], ["restricted", "Restricted"],
                                ["gliding", "Gliding"]]
    scene["tiles"] = dict(view3d.TILE_SOURCES)
    return scene


def _ground(lon, lat):
    """The scene's ridges (`tests.browser._terrain`), carried on past its quarter degree:
    200 m to 1 400 m, a crest every 9 km east to west. Numbers or numpy arrays."""
    return 800 + 600 * np.sin(4 * np.pi * (lon - 14) / 0.25) * np.cos(3 * np.pi * (lat - 49) / 0.25)


# Made once and kept: a run asks for a few hundred tiles, every worker and every run the
# same ones. Named by a hash of the code that draws them, so a change redraws them.
_DEM_CACHE = vendor.FOLDER.parent / "dem" / hashlib.sha1(
    (inspect.getsource(_ground) + "terrarium-256").encode()).hexdigest()[:12]


def _dem_tile(z: int, x: int, y: int) -> bytes:
    """A terrarium PNG of `_ground` for tile z/x/y: height + 32 768 m in red·256 + green +
    blue/256, as the AWS tiles the map asks for are."""
    path = _DEM_CACHE / f"{z}-{x}-{y}.png"
    if path.is_file():
        return path.read_bytes()
    size, n = 256, 2 ** z
    middle = (np.arange(size) + 0.5) / size
    lon = (x + middle) / n * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + middle) / n))))
    v = _ground(lon[None, :], lat[:, None]) + 32768
    whole = v.astype(np.int64)
    rgb = np.stack([whole >> 8, whole & 255, ((v - whole) * 256).astype(np.int64)], axis=-1)
    rows = np.concatenate([np.zeros((size, 1), np.uint8),
                           rgb.astype(np.uint8).reshape(size, size * 3)], axis=1)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows.tobytes())) + chunk(b"IEND", b""))
    _DEM_CACHE.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.part")    # workers share the folder
    temporary.write_bytes(png)
    temporary.replace(path)
    return png


def _page() -> str:
    scene = _scene_with_time()
    loader = (render_map.SCRIPT
              .replace(render_map.MAPLIBRE, "/vendor")
              .replace(render_map.DECK, "/vendor/deck.min.js")
              .replace(f"'{render_map.TERRARIUM}'", "location.origin + '/dem/{z}/{x}/{y}.png'"))
    assert "/dem/" in loader
    return (
        '<!doctype html><meta charset="utf-8"><title>merged</title>'
        f"<style>{view3d.STYLE}{render_map.STYLE}{map3d.STYLE}</style>"
        '<div class="wrap"><div class="renderer-host">'
        + view3d.panel(scene, "t") + "</div></div>"
        + f"<script>{view3d.SCRIPT}\n{loader}\n{map3d.SCRIPT}</script>"
        "<script>window.__errors = [];"
        "addEventListener('error', function (e) { __errors.push(String(e.message)); });"
        "var host = document.querySelector('.renderer-host');"
        "initView3dWhenReady(host, null).then(function (handle) {"
        "  window.__handle = handle; window.__openMap(host); });</script>"
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Every map on the page asked to repaint: the probe page has one, a report one a flight.
_REPAINT = ("Object.values(window.__mergedAll || {}).forEach(function (e) {"
            " if (e && e.map) e.map.triggerRepaint(); }); 1")


class Browser:
    """One Chrome over the DevTools protocol, the page served from a temporary folder."""

    def __init__(self, folder: Path):
        handler = functools.partial(_Quiet, directory=str(folder))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        port = _free_port()
        self.profile = tempfile.mkdtemp()
        self.chrome = subprocess.Popen(
            [CHROME, *_FLAGS, f"--remote-debugging-port={port}",
             f"--user-data-dir={self.profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tabs = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except OSError:
                time.sleep(0.2)
        page = [t for t in tabs if t["type"] == "page"][0]
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=120)
        self.n = 0
        self.call("Page.navigate",
                  url=f"http://127.0.0.1:{self.server.server_address[1]}/page.html")

    def call(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.n:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result")

    def js(self, expression):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True,
                           awaitPromise=True)
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return result["result"].get("value")

    def wait(self, expression, timeout=90.0):
        """Until `expression` holds, checked in the page every 20 ms, so the answer comes on
        the frame it starts to hold — polled from here it was a round trip and a quarter
        second's sleep a look. Each look asks the maps for a repaint: headless Chrome
        serves animation frames only while something is being repainted, and a repaint
        runs every pending frame callback — the follow camera's included."""
        held = self.js(f"""new Promise(done => {{ var end = Date.now() + {timeout * 1000};
          (function look() {{ var ok; try {{ ok = !!({expression}); }} catch (e) {{ ok = false; }}
            if (ok || Date.now() > end) return done(ok);
            {_REPAINT}; setTimeout(look, 20); }})(); }})""")
        if not held:
            raise TimeoutError(expression)

    def frame(self):
        """Until the page has painted a frame — the maps on it asked to, so one comes."""
        self.js(f"new Promise(done => {{ {_REPAINT}; requestAnimationFrame(() => requestAnimationFrame(done)); }})")

    def mouse(self, kind, x, y, *, modifiers=0, buttons=0, clicks=1, button="left"):
        self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, modifiers=modifiers,
                  button=button if kind != "mouseMoved" or buttons else "none",
                  buttons=buttons, clickCount=clicks)

    def drag(self, start, end, *, modifiers=0, steps=10):
        x0, y0 = start
        x1, y1 = end
        self.mouse("mouseMoved", x0, y0, modifiers=modifiers)
        self.mouse("mousePressed", x0, y0, modifiers=modifiers, buttons=1)
        for i in range(1, steps + 1):
            self.mouse("mouseMoved", x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps,
                       modifiers=modifiers, buttons=1)
            time.sleep(0.03)
        self.mouse("mouseReleased", x1, y1, modifiers=modifiers)

    def click(self, x, y, clicks=1):
        self.mouse("mouseMoved", x, y)
        for n in range(1, clicks + 1):
            self.mouse("mousePressed", x, y, buttons=1, clicks=n)
            self.mouse("mouseReleased", x, y, clicks=n)

    def key(self, key, code=None, keycode=0):
        for kind in ("keyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", type=kind, key=key, code=code or key,
                      windowsVirtualKeyCode=keycode)

    def screenshot(self) -> bytes:
        return base64.b64decode(self.call("Page.captureScreenshot", format="png")["data"])

    def close(self):
        self.chrome.kill()
        self.server.shutdown()
        shutil.rmtree(self.profile, ignore_errors=True)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/dem/"):
            return super().do_GET()
        z, x, y = (int(part) for part in self.path[5:].removesuffix(".png").split("/"))
        body = _dem_tile(z, x, y)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionError:         # a tile the map stopped wanting, or Chrome closed
            pass

    def log_message(self, *args):
        pass


ENTRY = "window.__mergedAll && window.__mergedAll['view3d-t']"
MAP = f"({ENTRY}).map"


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    folder = tmp_path_factory.mktemp("merged")
    (folder / "page.html").write_text(_page(), encoding="utf-8")
    shutil.copytree(vendor.folder(), folder / "vendor")
    b = Browser(folder)
    try:
        b.wait(f"!!({ENTRY}) && ({MAP}).isStyleLoaded !== undefined")
        # Not `loaded()`: the place names' source is fetched from the network and never
        # loads, so that never holds. The ground's tiles, every tile asked for, and a still
        # camera do — and a first test that drove a map still settling read a NaN bearing.
        b.wait(f"(m => m.isSourceLoaded('dem') && m.areTilesLoaded() && !m.isMoving())({MAP})")
        _still(b)
        b.js("document.querySelector('.ml-map').scrollIntoView({block: 'center'}); 1")
        _frame(b)
        yield b
    finally:
        b.close()


def _box(browser):
    return browser.js(f"(() => {{ var r = ({MAP}).getCanvas().getBoundingClientRect();"
                      " return [r.left, r.top, r.width, r.height]; })()")


def _frame(browser):
    """Until the map has drawn a frame from where it is now."""
    browser.js(f"new Promise(r => {{ ({MAP}).once('render', () => r(1)); ({MAP}).triggerRepaint(); }})")


def _still(browser, timeout=60.0):
    """Until the camera has stopped — the same over two frames, no easing, nothing frozen
    for a drag — and every tile it asks for is in. Where a test used to sleep for a
    while and hope, this is what it was waiting for."""
    held = browser.js(f"""new Promise(done => {{ var m = {MAP}, end = Date.now() + {timeout * 1000}, was = null;
      function look() {{
        var c = m.transform.getCameraPosition(), now = JSON.stringify([c.lngLat.lng.toFixed(7),
          c.lngLat.lat.toFixed(7), c.altitude.toFixed(1), m.getBearing().toFixed(2), m.getPitch().toFixed(2)]);
        if ((now === was && !m.isMoving() && !m._elevationFreeze && m.areTilesLoaded()) || Date.now() > end)
          return done(now === was);
        was = now; m.once('render', look); m.triggerRepaint(); }}
      m.once('render', look); m.triggerRepaint(); }})""")
    if not held:
        raise TimeoutError("the camera did not come to rest")


def _reset(browser, ground=False, **camera):
    # 50°, not steeper: in software GL a frame over terrain takes 1.2 s looking straight
    # down, 1.8 s at 60° and 3.3 s at 70°, and every input event waits for one.
    view = {"center": [14.1, 49.1], "zoom": 10, "pitch": 50, "bearing": 0, **camera}
    browser.js(f"({ENTRY}).setFollow && ({ENTRY}).setFollow(false); ({MAP}).jumpTo({json.dumps(view)}); 1")
    if ground:
        # A test that reads the ground off the screen waits for the tiles and a frame
        # drawn from there: over terrain, `unproject` reads the ground from the last
        # frame's depth, and a test that grabbed a point a moment after the jump took one
        # from the view before — 800 m off, on a slope.
        _still(browser)
    else:
        _frame(browser)


def test_the_map_opens(browser):
    """The panel's map is mounted over it, and nothing threw on the way."""
    assert browser.js("!!document.querySelector('.renderer-host .merged-view:not([hidden])')")
    assert browser.js("window.__errors") == []


@pytest.mark.parametrize("grab, move", [
    ((0.5, 0.5), (80, 0)),              # a turn, on the crest in the middle
    ((0.65, 0.6), (60, 40)),            # a turn and a tilt down to 30°, on its flank
    ((0.4, 0.35), (-30, -20)),          # a tilt up to 60° and a turn back, further down
])
def test_a_shift_drag_turns_and_tilts_about_the_ground_grabbed(browser, grab, move):
    """The ground under the pointer stays under it while the view turns and tilts — here
    ground on a ridge, hundreds of metres up, so a pivot taken at the wrong height shows.
    The pivot was clamped into the canvas *container*, which has no height, so it went to
    y = 0 — the horizon at a 60° tilt — and an 80 px turn moved the map from Krupka to
    Leipzig."""
    _reset(browser, ground=True)
    left, top, width, height = _box(browser)
    x, y = width * grab[0], height * grab[1]
    ground = browser.js(f"({MAP}).unproject([{x}, {y}]).toArray()")
    drawn = browser.js(f"(m => m.terrain.getElevationForLngLatZoom(new maplibregl.LngLat(...{json.dumps(ground)}),"
                       f" m.transform.tileZoom))({MAP})")
    assert drawn == pytest.approx(_ground(*ground), abs=40), "grabbed on the ridge, at its height"
    # Five moves: each waits for a frame, and the pivot is put back after every one.
    browser.drag((left + x, top + y), (left + x + move[0], top + y + move[1]), modifiers=8, steps=5)
    # Until the camera's height is handed back to MapLibre and it rests: the ground that
    # hand-off settles on is where the tilted-up view jumped.
    _still(browser)
    bearing, pitch = browser.js(f"[({MAP}).getBearing(), ({MAP}).getPitch()]")
    where = browser.js(f"(() => {{ var p = ({MAP}).project({json.dumps(ground)}); return [p.x, p.y]; }})()")
    assert bearing == pytest.approx(move[0] * 0.8, abs=1), "the drag turned the view"
    assert pitch == pytest.approx(50 - move[1] * 0.5, abs=1), "and tilted it"
    assert math.hypot(where[0] - x, where[1] - y) < 4, (ground, where, (x, y))


def test_a_plain_drag_pans_and_does_not_turn(browser):
    _reset(browser)
    left, top, width, height = _box(browser)
    browser.drag((left + width / 2, top + height / 2), (left + width / 2 + 120, top + height / 2), steps=5)
    _still(browser)
    assert abs(browser.js(f"({MAP}).getBearing()")) < 0.5
    centre = browser.js(f"({MAP}).getCenter().toArray()")
    assert centre[0] < 14.1 - 0.01, "dragging right moves the map right: the centre goes west"


def test_the_airspace_hides_nothing(browser):
    """Translucent boxes must not write depth: one drawn before the track hid every part
    of the flight inside it, which over Krupka was nearly all of it."""
    _reset(browser)
    browser.js("document.querySelector('.merged-view [data-m3=airspace]').click(); 1")
    browser.wait(f"({ENTRY}).layers().some(d => d.id === 'airspace')")
    layers = {d["id"]: d["parameters"] for d in browser.js(f"({ENTRY}).layers()")}
    browser.js("document.querySelector('.merged-view [data-m3=airspace]').click(); 1")
    assert "airspace" in layers
    for name in ("airspace", "airspace-edges", "airspace-corners"):
        assert layers[name] and layers[name].get("depthWriteEnabled") is False, name
    assert any(name.startswith("track") for name in layers), layers


def test_the_airspace_menu_filters_by_kind_and_floor(browser):
    """The ▾ beside Airspaces: a row per kind with how many this map draws (a kind with
    none is offered greyed), a floor, and Reset. Choosing a filter turns the airspace on,
    and Escape closes the menu."""
    _reset(browser)
    q = "document.querySelector('.merged-view %s')"
    shown = f"({ENTRY}).airspaceShown()"
    rows = """[...document.querySelectorAll('.merged-view .m3-asp-kinds label')].map(r =>
      [r.querySelector('span').textContent, r.querySelector('b').textContent,
       r.querySelector('input').disabled, r.querySelector('input').checked])"""
    assert browser.js((q % ".m3-airspace-menu") + ".hidden") is True
    browser.js((q % "[data-m3=airspace-menu]") + ".click(); 1")
    assert browser.js((q % ".m3-airspace-menu") + ".hidden") is False
    assert browser.js(rows) == [["Controlled", "1", False, True], ["Restricted", "1", False, True],
                                ["Gliding", "0", True, True]]
    assert browser.js(shown) == 0, "the airspace starts off on a flight's map"

    # Untick a kind: the airspace comes on, without it.
    browser.js((q % ".m3-asp-kinds label:nth-child(2) input") + ".click(); 1")
    assert browser.js(f"({ENTRY}).state().airspace") is True
    assert browser.js(shown) == 1
    # The floor: the restricted zone is back, then dropped by a floor under its 3 000 m.
    browser.js((q % ".m3-asp-kinds label:nth-child(2) input") + ".click(); 1")
    assert browser.js(shown) == 2
    assert browser.js((q % ".m3-asp-floor input") + ".max") == "3000"
    assert browser.js((q % ".m3-asp-floor-out") + ".textContent") == "every floor"
    browser.js(f"(() => {{ var s = {q % '.m3-asp-floor input'}; s.value = 2950;"
               " s.dispatchEvent(new Event('input')); })(); 1")
    assert browser.js(shown) == 1
    assert browser.js((q % ".m3-asp-floor-out") + ".textContent") == "2950 m"
    assert browser.js((q % ".m3-asp-count") + ".textContent") == "1 shown"
    # Reset: everything again.
    browser.js((q % ".m3-asp-reset") + ".click(); 1")
    assert browser.js(shown) == 2
    assert browser.js((q % ".m3-asp-floor-out") + ".textContent") == "every floor"
    # Escape closes it; the switch's own button turns the airspace back off.
    browser.js((q % ".m3-asp-reset") + ".focus(); 1")
    browser.key("Escape", keycode=27)
    assert browser.js((q % ".m3-airspace-menu") + ".hidden") is True
    browser.js((q % "[data-m3=airspace]") + ".click(); 1")
    assert browser.js(shown) == 0


def test_showing_one_zone_sets_the_menu_for_it(browser):
    """The report's Airspace section shows a zone on the map (`focusAirspace`): the
    airspace on, only that zone's kind, nothing floored above it — through the menu, so
    the menu says so and Reset undoes it."""
    _reset(browser)
    q = "document.querySelector('.merged-view %s')"
    rows = """[...document.querySelectorAll('.merged-view .m3-asp-kinds label')].map(r =>
      [r.querySelector('span').textContent, r.querySelector('input').checked])"""
    zone = "__handle.built.scene.airspaces.find(z => z.k === 'restricted')"
    assert browser.js(f"({ENTRY}).focusAirspace({zone}, [14.15, 49.1])") is True
    assert browser.js(f"({ENTRY}).state().airspace") is True
    assert browser.js(f"({ENTRY}).airspaceShown()") == 1
    assert dict(browser.js(rows))["Restricted"] is True
    assert dict(browser.js(rows))["Controlled"] is False
    assert browser.js((q % ".m3-asp-floor-out") + ".textContent") == "3000 m"
    browser.js((q % ".m3-asp-reset") + ".click(); 1")
    assert browser.js(f"({ENTRY}).airspaceShown()") == 2
    browser.js((q % "[data-m3=airspace]") + ".click(); 1")
    assert browser.js(f"({ENTRY}).airspaceShown()") == 0


def test_the_airspace_split_button_is_one_rounded_group(browser):
    """The switch and its ▾ are one control: square where they meet, rounded at both
    outer ends, and the row keeps the same gap as every other button pair."""
    radii = browser.js("""(() => {
      var a = getComputedStyle(document.querySelector('.merged-view [data-m3=airspace]'));
      var c = getComputedStyle(document.querySelector('.merged-view [data-m3=airspace-menu]'));
      return [a.borderTopLeftRadius, a.borderTopRightRadius, c.borderTopLeftRadius, c.borderTopRightRadius,
              c.borderBottomRightRadius];
    })()""")
    assert radii == ["10px", "0px", "0px", "10px", "10px"]
    gaps = browser.js("""(() => {
      var kids = [...document.querySelector('.merged-view .m3-corner-row').children]
        .map(e => e.getBoundingClientRect());
      return kids.slice(1).map((r, i) => Math.round(r.left - kids[i].right));
    })()""")
    assert gaps and len(set(gaps)) == 1, gaps


def test_a_sun_handed_in_lights_the_ground_and_turns_the_rose(browser):
    """`setSun` and `setWind`, the planner's takeoff time: the map takes a `TV.sun` table,
    lights the hillshade from its azimuth and says the time on the rose in the page's
    clock, and the wind with where it blows."""
    _reset(browser)
    az = [100 + i for i in range(144)]          # a degree every ten minutes, from 100°
    table = {"track": {"step": 10, "az": az, "el": [30] * 144}, "offset": 60, "at": 600}
    browser.js(f"({ENTRY}).setSun({json.dumps(table)}); 1")
    browser.wait(f"({MAP}).getPaintProperty('hillshade-over', 'hillshade-illumination-direction') === 160")
    text = browser.js("document.querySelector('.merged-view .m3-rose-text').textContent")
    assert text.startswith("Sun 11:00"), text
    assert browser.js("!document.querySelector('.merged-view .m3-rose').hidden") is True
    browser.js(f"({ENTRY}).setWind({{ms: 5, from: 225, cardinal: 'SW', at: 'at 1500 m'}}); 1")
    text = browser.js("document.querySelector('.merged-view .m3-rose-text').textContent")
    assert text.endswith("Wind 5.0 m/s from SW at 1500 m"), text
    browser.js(f"({ENTRY}).setWind(null); 1")
    text = browser.js("document.querySelector('.merged-view .m3-rose-text').textContent")
    assert "Wind" not in text, text


def test_a_tilt_or_turn_is_not_a_click(browser):
    """The planner drops a turnpoint on a click (`onClick`). A shift-drag that turns or
    tilts the map ends in a mouseup MapLibre may call a click, and that dropped a point
    wherever the tilt let go; only a plain press that stayed put counts."""
    _reset(browser)
    browser.js(f"window.__clicks = []; ({ENTRY}).onClick(function (at) {{ __clicks.push(at); }}); 1")
    x, y, w, h = _box(browser)
    cx, cy = x + w / 2, y + h / 2
    # A click comes with the mouseup it follows, inside the input call, so a frame after
    # each is long enough for one to have landed.
    browser.drag((cx, cy), (cx + 60, cy + 40), modifiers=8, steps=5)    # shift: turn and tilt
    _frame(browser)
    browser.mouse("mousePressed", cx, cy, modifiers=8, buttons=1)   # shift-click in place
    browser.mouse("mouseReleased", cx, cy, modifiers=8)
    _frame(browser)
    after_tilt = browser.js("__clicks.length")
    browser.click(cx, cy)
    _frame(browser)
    after_click = browser.js("__clicks.length")
    _reset(browser)
    assert after_tilt == 0, "a tilt or a modified press dropped a point"
    assert after_click == 1, "a plain click did not"


def test_the_measure_tool_adds_up_the_legs_on_the_sphere(browser):
    """Clicks are points, the readout is the total and the last leg, and a click while
    measuring is not also a turnpoint or anything else."""
    _reset(browser, ground=True, pitch=0)
    left, top, width, height = _box(browser)
    browser.js("document.querySelector('.merged-view [data-m3=measure]').click(); 1")
    spots = [(0.3, 0.5), (0.6, 0.5), (0.6, 0.3)]
    points = []
    for fx, fy in spots:
        browser.click(left + width * fx, top + height * fy)
        points.append(browser.js(f"({MAP}).unproject([{width * fx}, {height * fy}]).toArray()"))
    text = browser.js("document.querySelector('.merged-view .m3-measure').textContent")

    def sphere(a, b):
        la1, la2 = math.radians(a[1]), math.radians(b[1])
        h = (math.sin((la2 - la1) / 2) ** 2
             + math.cos(la1) * math.cos(la2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2)
        return 2 * 6371000 * math.asin(math.sqrt(h))

    total = sphere(points[0], points[1]) + sphere(points[1], points[2])
    shown = float(text.split(" km")[0])
    assert shown == pytest.approx(total / 1000, abs=0.06), text  # 0.1 km shown over 10 km
    assert "last leg" in text
    browser.key("Backspace", "Backspace", 8)
    after = browser.js("document.querySelector('.merged-view .m3-measure').textContent")
    assert float(after.split(" km")[0]) == pytest.approx(sphere(points[0], points[1]) / 1000, abs=0.06)
    browser.key("Escape", "Escape", 27)
    assert browser.js("document.querySelector('.merged-view .m3-measure').hidden")


def _follow(browser):
    browser.js("""(() => { var v = document.querySelector('.merged-view');
      if (v.querySelector('.m3-replay').hidden) v.querySelector('[data-m3=replay]').click();
      var play = v.querySelector('[data-m3=play]');
      if (play.classList.contains('is-on')) play.click();
      (%s).setTime(1800); (%s).setFollow(true); return 1; })()""" % (ENTRY, ENTRY))
    browser.wait(f"Math.abs(({MAP}).getZoom() - 12.5) < 0.05", timeout=30)


def test_follow_survives_zooming_and_turning_and_ends_on_a_drag(browser):
    """Zoom, the arrows and a click adjust the follow camera; only a drag hands it back."""
    _reset(browser)
    _follow(browser)
    left, top, width, height = _box(browser)
    x, y = left + width / 2, top + height / 2
    following = f"({ENTRY}).following()"

    browser.call("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=-300)
    browser.wait(f"({MAP}).getZoom() > 12.9", timeout=10)
    assert browser.js(following), "the wheel zooms the follow camera"

    zoom = browser.js(f"({MAP}).getZoom()")
    browser.click(x, y, clicks=2)
    browser.wait(f"({MAP}).getZoom() > {zoom + 0.8}", timeout=20)
    assert browser.js(following), "a double-click zooms, it does not end following"

    browser.js("document.querySelector('.merged-view .ml-map').focus(); 1")
    before = browser.js(f"({MAP}).getPitch()")
    browser.key("ArrowUp", "ArrowUp", 38)
    browser.key("ArrowRight", "ArrowRight", 39)
    # The pilot's way round: → turns the view 15° left of the course, ↑ tilts it down.
    offset = f"(({MAP}).getBearing() - ({ENTRY}).courseAt(1800) + 540) % 360 - 180"
    browser.wait(f"({MAP}).getPitch() < {before - 9} && Math.abs({offset} + 15) < 1", timeout=20)
    assert browser.js(following), "the arrows turn and tilt the follow camera"

    browser.drag((x, y), (x + 60, y + 20), steps=5)
    _frame(browser)
    assert not browser.js(following), "a drag hands the camera back"


def test_two_fingers_tilt_and_turn_the_follow_camera(browser):
    """A phone has no arrows: moving two fingers tilts the follow camera, a twist turns it
    off the direction of flight, and neither ends following. Taken as a pinch alone, a
    two-finger drag did nothing at all. Tilted down, not up: under the follow camera a
    frame at 80° took 6-10 s an event, and at 40° a fraction of that."""
    _reset(browser)
    _follow(browser)
    left, top, width, height = _box(browser)
    x, y = left + width / 2, top + height / 2
    browser.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=2)
    try:
        def touch(kind, points):
            browser.call("Input.dispatchTouchEvent", type=kind,
                         touchPoints=[{"x": px, "y": py, "id": i} for i, (px, py) in enumerate(points)])

        before = browser.js(f"({ENTRY}).followCamera()")
        touch("touchStart", [(x - 60, y), (x + 60, y)])
        # Four moves a gesture: each waits for a frame, and a frame is about a second here.
        for k in range(1, 5):                          # both fingers 40 px down
            touch("touchMove", [(x - 60, y + 10 * k), (x + 60, y + 10 * k)])
            time.sleep(0.03)
        touch("touchEnd", [])
        after = browser.js(f"({ENTRY}).followCamera()")
        assert after["pitch"] == pytest.approx(max(0, before["pitch"] - 20), abs=2)
        assert after["zoom"] == pytest.approx(before["zoom"], abs=0.05), "not a pinch"

        touch("touchStart", [(x - 60, y), (x + 60, y)])
        for k in range(1, 5):                          # a twist, 30° clockwise on screen
            a = math.radians(30 * k / 4)
            touch("touchMove", [(x - 60 * math.cos(a), y - 60 * math.sin(a)),
                                (x + 60 * math.cos(a), y + 60 * math.sin(a))])
            time.sleep(0.03)
        touch("touchEnd", [])
        turned = browser.js(f"({ENTRY}).followCamera()")
        assert turned["turn"] == pytest.approx(after["turn"] - 30, abs=2)  # the ground follows the fingers
        assert browser.js(f"({ENTRY}).following()")
    finally:
        browser.call("Emulation.setTouchEmulationEnabled", enabled=False)


def test_handing_the_follow_camera_back_leaves_it_where_it_was(browser):
    _reset(browser)
    _follow(browser)
    # Not until it rests: the follow camera never quite does. Two frames into following.
    _frame(browser)
    _frame(browser)
    camera = ("(() => { var p = (%s).transform.getCameraPosition();"
              " return [p.lngLat.lng, p.lngLat.lat, p.altitude]; })()" % MAP)
    before = browser.js(camera)
    browser.js(f"({ENTRY}).setFollow(false); 1")
    _frame(browser)
    _frame(browser)
    after = browser.js(camera)
    assert after[0] == pytest.approx(before[0], abs=2e-4)
    assert after[1] == pytest.approx(before[1], abs=2e-4)
    assert after[2] == pytest.approx(before[2], rel=0.05)


def test_compared_flights_are_drawn_on_one_clock_and_far_ones_are_listed(browser):
    """The flights marked for comparison are drawn on each other's maps. Flown the same
    day, the replay shows each where it was at the same moment; one far away is listed,
    not drawn, rather than stretching the view across a continent."""
    _reset(browser)
    browser.js(f"""(() => {{
      var tr = __handle.built.scene.track, start = __handle.built.scene.start || 1700000000;
      var near = {{ lon: tr.lon.map(x => x + 0.01), lat: tr.lat.slice(), alt: tr.alt.slice(), t: tr.t.slice() }};
      var far = {{ lon: tr.lon.map(x => x + 20), lat: tr.lat.slice(), alt: tr.alt.slice(), t: tr.t.slice() }};
      __handle.built.scene.start = start;
      ({ENTRY}).setOthers({{ own: {{ name: 'THIS', colour: '#e0893a' }}, others: [
        {{ name: 'NEAR', colour: '#3aa8d0', track: near, start: start + 600 }},
        {{ name: 'FAR', colour: '#c9483c', track: far, start: start }}] }});
      return 1; }})()""")
    browser.wait(f"({ENTRY}).layers().some(d => d.id.startsWith('other-'))")
    ids = [d["id"] for d in browser.js(f"({ENTRY}).layers()")]
    legend = browser.js("document.querySelector('.merged-view .m3-others').textContent")
    assert "other-0" in ids and "other-1" not in ids, ids
    assert "NEAR" in legend and "FAR · too far to show" in legend
    titles = browser.js("Array.from(document.querySelectorAll('.merged-view .m3-others li')).map(li => li.title)")
    assert any(t.startswith("Same day") for t in titles), titles      # one clock
    # All flights are equal on the map: NEAR launched 10 min later, so it lands 10 min
    # later too, and the replay runs until it does — not just to this flight's landing.
    own_end = browser.js("__handle.built.scene.track.t.slice(-1)[0]")
    assert browser.js("+document.querySelector('.merged-view .m3-to').max") == own_end + 600
    assert browser.js("+document.querySelector('.merged-view .m3-from').min") == 0
    # The replay at 30 min: NEAR launched 10 min later, so it is 20 min into its flight.
    browser.js("""(() => { var v = document.querySelector('.merged-view');
      if (v.querySelector('.m3-replay').hidden) v.querySelector('[data-m3=replay]').click();
      var play = v.querySelector('[data-m3=play]'); if (play.classList.contains('is-on')) play.click();
      (%s).setTime(1800); return 1; })()""" % ENTRY)
    browser.wait(f"({ENTRY}).layers().some(d => d.id === 'other-now-0')", timeout=10)
    ids = [d["id"] for d in browser.js(f"({ENTRY}).layers()")]
    assert "other-now-0" in ids, ids
    # The height at "now", top right: this flight's with its climb, then each compared one.
    now = browser.js("document.querySelector('.merged-view .m3-now').innerText").splitlines()
    # Each glider's height and climb, the compared one's as well as this one's.
    assert len(now) == 2 and all(" m · " in line and line.endswith("m/s") for line in now), now
    browser.js(f"({ENTRY}).setOthers(null); 1")
    assert browser.js("document.querySelector('.merged-view .m3-others').hidden")


def test_follow_keeps_every_compared_glider_in_the_picture(browser):
    """Comparing, the follow camera frames the whole group at the shared "now": a glider
    11 km to the side stays on screen, the view pulled back from 12.5 to hold it."""
    _reset(browser)
    browser.js(f"""(() => {{
      var tr = __handle.built.scene.track, start = __handle.built.scene.start || 1700000000;
      __handle.built.scene.start = start;
      var beside = {{ lon: tr.lon.map(x => x + 0.15), lat: tr.lat.slice(), alt: tr.alt.slice(), t: tr.t.slice() }};
      window.__beside = beside;
      ({ENTRY}).setOthers({{ own: {{ name: 'THIS', colour: '#e0893a' }},
                             others: [{{ name: 'BESIDE', colour: '#3aa8d0', track: beside, start: start }}] }});
      return 1; }})()""")
    browser.js("""(() => { var v = document.querySelector('.merged-view');
      if (v.querySelector('.m3-replay').hidden) v.querySelector('[data-m3=replay]').click();
      var play = v.querySelector('[data-m3=play]'); if (play.classList.contains('is-on')) play.click();
      (%s).setTime(1800); (%s).setFollow(true); return 1; })()""" % (ENTRY, ENTRY))
    browser.wait(f"({MAP}).getZoom() < 12.3 && ({ENTRY}).following()", timeout=30)
    # Where each glider is drawn — at its altitude, not on the ground under it — and how
    # far down the map is clear: above the replay bar, the buttons and the legend over
    # its bottom, which on a phone cover a third of the map.
    seen = f"""(() => {{
      var m = {MAP}, tr = __handle.built.scene.track, i = tr.t.indexOf(1800);
      function at(lon, lat, alt) {{
        return m.transform.coordinatePoint(maplibregl.MercatorCoordinate.fromLngLat([lon, lat]), alt);
      }}
      var top = m.getContainer().getBoundingClientRect().top, bar = document.querySelector('.merged-view .m3-bottom');
      return {{ spots: [at(tr.lon[i], tr.lat[i], tr.alt[i]), at(__beside.lon[i], __beside.lat[i], __beside.alt[i])]
                  .map(p => [p.x, p.y]),
               width: m.getCanvas().clientWidth,
               clear: bar && !bar.hidden ? bar.getBoundingClientRect().top - top : m.getCanvas().clientHeight }}; }})()"""
    # The camera eases to frame them and never quite rests, so: until both are in view.
    try:
        browser.wait(f"(s => s.spots.every(([x, y]) => 0 < x && x < s.width && 0 < y && y < s.clear))({seen})",
                     timeout=30)
    except TimeoutError:
        pass                                    # the assert below says where they were
    view = browser.js(seen)
    spots, width, clear = view["spots"], view["width"], view["clear"]
    for x, y in spots:
        assert 0 < x < width and 0 < y < clear, (spots, width, clear)
    browser.js(f"({ENTRY}).setFollow(false); ({ENTRY}).setOthers(null); 1")


def test_no_errors_along_the_way(browser):
    assert browser.js("window.__errors") == []




def _one_finger(browser):
    """A touch function for one finger, its events stamped 50 ms apart: a software-GL
    frame takes a second or more here and every event waits for one, which turned each
    tap into a long press. `gap()` starts a new gesture rather than a third tap."""
    clock = [time.time()]

    def touch(kind, points=()):
        clock[0] += 0.05
        browser.call("Input.dispatchTouchEvent", type=kind, timestamp=clock[0],
                     touchPoints=[{"x": px, "y": py, "id": 0} for px, py in points])

    def gap():
        clock[0] += 1

    return touch, gap


def _double_tap_and_slide(browser, zoom, settle):
    left, top, width, height = _box(browser)
    x, y = left + width / 2, top + height / 2
    browser.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=2)
    try:
        touch, gap = _one_finger(browser)
        before = zoom()
        for _ in range(2):
            touch("touchStart", [(x, y)])
            touch("touchEnd")
        settle(before + 1)
        assert zoom() == pytest.approx(before + 1, abs=0.05), "a double tap zooms in a level"
        gap()
        before = zoom()
        touch("touchStart", [(x, y)])
        touch("touchEnd")
        touch("touchStart", [(x, y)])
        for k in range(1, 5):                      # slid 128 px up: out a level
            touch("touchMove", [(x, y - 32 * k)])
        touch("touchEnd")
        settle(before - 1)
        assert zoom() == pytest.approx(before - 1, abs=0.1), "a tap then a slide up zooms out"
        gap()
        before = zoom()
        touch("touchStart", [(x, y)])
        touch("touchEnd")
        touch("touchStart", [(x, y)])
        for k in range(1, 3):                      # and 64 px down: in half a level
            touch("touchMove", [(x, y + 32 * k)])
        touch("touchEnd")
        settle(before + 0.5)
        assert zoom() == pytest.approx(before + 0.5, abs=0.1), "and down zooms in"
    finally:
        browser.call("Emulation.setTouchEmulationEnabled", enabled=False)


def test_a_double_tap_zooms_in_and_a_tap_then_slide_zooms(browser):
    """On a phone, Google Maps' one-finger zoom: a double tap zooms in a level, and a tap
    then a finger held down and slid zooms — up out, down in. MapLibre's own gestures."""
    _reset(browser, pitch=0)
    _double_tap_and_slide(
        browser, lambda: browser.js(f"({MAP}).getZoom()"),
        lambda want: browser.wait(f"!({MAP}).isMoving() && Math.abs(({MAP}).getZoom() - {want}) < 0.1", timeout=30))


def test_the_follow_camera_takes_a_double_tap_and_a_tap_then_slide(browser):
    """Following, the same two gestures zoom the follow camera, and neither ends it: the
    slide is a zoom, not the drag that hands the camera back."""
    _reset(browser)
    _follow(browser)
    cam = f"({ENTRY}).followCamera().zoom"
    _double_tap_and_slide(browser, lambda: browser.js(cam), lambda want: None)
    assert browser.js(f"({ENTRY}).following()")


def test_a_row_of_the_compared_legend_hides_and_shows_its_flight(browser):
    """Comparing, a press on a flight's row in the legend hides that flight on the map, and
    a second shows it again; this flight's own row too. A flight too far to draw has no
    switch."""
    _reset(browser)
    browser.js(f"""(() => {{
      var tr = __handle.built.scene.track, start = __handle.built.scene.start || 1700000000;
      var near = {{ lon: tr.lon.map(x => x + 0.01), lat: tr.lat.slice(), alt: tr.alt.slice(), t: tr.t.slice() }};
      var far = {{ lon: tr.lon.map(x => x + 20), lat: tr.lat.slice(), alt: tr.alt.slice(), t: tr.t.slice() }};
      __handle.built.scene.start = start;
      ({ENTRY}).setOthers({{ own: {{ name: 'THIS', colour: '#e0893a' }}, others: [
        {{ name: 'NEAR', colour: '#3aa8d0', track: near, start: start }},
        {{ name: 'FAR', colour: '#c9483c', track: far, start: start }}] }});
      return 1; }})()""")
    ids = f"({ENTRY}).layers().map(d => d.id)"
    browser.wait(f"{ids}.includes('other-0')")
    row = "document.querySelector('.merged-view .m3-others li[data-flight=\"%s\"]')"
    assert browser.js("document.querySelectorAll('.merged-view .m3-others li[data-flight]').length") == 2
    browser.js(f"{row % 'NEAR'}.click(); 1")
    assert "other-0" not in browser.js(ids)
    assert browser.js(f"{row % 'NEAR'}.getAttribute('aria-pressed')") == "false"
    browser.js(f"{row % 'NEAR'}.click(); 1")
    assert "other-0" in browser.js(ids)
    own = "document.querySelector('.merged-view .m3-others li.is-own')"
    assert "track" in browser.js(ids)
    browser.js(f"{own}.click(); 1")
    assert "track" not in browser.js(ids) and "climbs" not in browser.js(ids)
    assert browser.js(f"{own}.classList.contains('is-off')")
    browser.js(f"{own}.click(); 1")
    assert "track" in browser.js(ids)
    browser.js(f"({ENTRY}).setOthers(null); 1")


def test_a_double_tap_is_a_zoom_and_not_two_taps(browser):
    """A tap reaches the page (the planner's "Above this point", a turnpoint) only once it
    is clear it was not the first of a double tap, which is the zoom alone. Driven with
    synthetic events: real taps here are a second or more apart, every event waiting
    for a software-GL frame."""
    _reset(browser)
    taps = browser.js(f"""new Promise(done => {{
      var m = {MAP}, canvas = m.getCanvas(), r = canvas.getBoundingClientRect();
      var x = r.left + r.width / 2, y = r.top + r.height / 2, got = [], t0 = performance.now() + 10000;
      if (!window.__tapLog) {{ window.__tapLog = []; ({ENTRY}).onClick(at => __tapLog.push(at)); }}
      __tapLog.length = 0;
      function tap(t) {{
        canvas.dispatchEvent(new PointerEvent('pointerdown', {{ pointerType: 'touch', clientX: x, clientY: y,
                                                               bubbles: true, isPrimary: true }}));
        m.fire('click', {{ lngLat: m.getCenter(), point: {{ x: r.width / 2, y: r.height / 2 }},
                          originalEvent: {{ timeStamp: t, clientX: x, clientY: y, pointerType: 'touch' }} }});
      }}
      tap(t0); tap(t0 + 200);                       // a double tap: nothing
      setTimeout(() => {{ got.push(__tapLog.length); tap(t0 + 5000);   // a tap: one, after a wait
        got.push(__tapLog.length);
        setTimeout(() => {{ got.push(__tapLog.length); done(got); }}, 500); }}, 500);
    }})""")
    assert taps == [0, 0, 1], taps

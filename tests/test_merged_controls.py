"""The merged 3D map's controls, driven with real input in a real browser.

The merged view is the default 3D map, and its controls are most of what a reader does
with it. They went untested because the view loads MapLibre and deck.gl from a CDN and
this suite has no network — and two regressions shipped: a shift-drag that flung the map
two hundred kilometres (the pivot was clamped into an element with no height, so every
grab went to the horizon), and a track that vanished when airspace was switched on (the
translucent boxes wrote depth and hid everything inside them). The canvas view's controls
earned their tests the same way.

The libraries come from a local cache (`tests/vendor.py`) served from localhost, so the
no-network rule holds; imagery and terrain are not fetched, and the map runs flat over a
plain background, which is all a control test needs. Input goes in through the DevTools
protocol — mouse with modifiers, keys, wheel, touch — because a synthetic DOM event is
not what MapLibre's handlers see from a reader.
"""

from __future__ import annotations

import base64
import functools
import http.server
import json
import math
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from parainsights_map import map3d, render_map, view3d, view3d_gl
from tests import vendor
from tests.test_view3d_gl import CHROME, _scene

websocket = pytest.importorskip("websocket")

pytestmark = [
    pytest.mark.skipif(CHROME is None, reason="no Chrome"),
    pytest.mark.skipif(vendor.folder() is None,
                       reason="MapLibre and deck.gl not cached: python -m tests.vendor"),
]

_FLAGS = [
    "--headless", "--no-sandbox", "--window-size=1200,900", "--enable-unsafe-swiftshader",
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
    scene = _scene(airspace=True, basemap=False)
    track = scene["track"]
    track["t"] = [i * 30 for i in range(len(track["lon"]))]
    ring = scene["airspaces"][0]
    ring["lon"] = [13.9, 14.4, 14.4, 13.9]
    ring["lat"] = [48.9, 48.9, 49.3, 49.3]
    ring["c"] = 6000
    scene["tiles"] = dict(view3d.TILE_SOURCES)
    return scene


def _page() -> str:
    scene = _scene_with_time()
    switch = (render_map.SWITCH_SCRIPT
              .replace(render_map.MAPLIBRE, "/vendor")
              .replace(render_map.DECK, "/vendor/deck.min.js"))
    return (
        '<!doctype html><meta charset="utf-8"><title>merged</title>'
        f"<style>{view3d.STYLE}{view3d_gl.STYLE}{render_map.SWITCH_STYLE}{map3d.STYLE}</style>"
        '<div class="wrap"><div class="renderer-host" data-renderer-default="merged">'
        + render_map.switch_html() + view3d.panel(scene, "t") + "</div></div>"
        + f"<script>{view3d.SCRIPT}\n{view3d_gl.SCRIPT}\n{switch}\n{map3d.SCRIPT}</script>"
        "<script>window.__errors = [];"
        "addEventListener('error', function (e) { __errors.push(String(e.message)); });"
        "var host = document.querySelector('.renderer-host');"
        "initView3dWhenReady(host, null).then(function (handle) {"
        "  window.__handle = handle; window.__openDefaultRenderer(host); });</script>"
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
        """Until `expression` holds. Each poll asks MapLibre for a repaint: headless Chrome
        serves animation frames only while something is being repainted, and a repaint
        runs every pending frame callback — the follow camera's included."""
        end = time.time() + timeout
        while time.time() < end:
            if self.js(expression):
                return
            self.js(f"window.__mergedAll && ({MAP}).triggerRepaint(); 1")
            time.sleep(0.25)
        raise TimeoutError(expression)

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
        b.wait(f"({MAP}).loaded() || true")
        time.sleep(1.5)
        b.js("document.querySelector('.ml-map').scrollIntoView({block: 'center'}); 1")
        time.sleep(0.5)
        yield b
    finally:
        b.close()


def _box(browser):
    return browser.js(f"(() => {{ var r = ({MAP}).getCanvas().getBoundingClientRect();"
                      " return [r.left, r.top, r.width, r.height]; })()")


def _reset(browser, **camera):
    view = {"center": [14.1, 49.1], "zoom": 10, "pitch": 60, "bearing": 0, **camera}
    browser.js(f"({ENTRY}).setFollow && ({ENTRY}).setFollow(false); ({MAP}).jumpTo({json.dumps(view)}); 1")
    time.sleep(0.3)


def test_the_merged_map_is_what_opens(browser):
    """Merged is the default 3D view; the canvas is only what is left without MapLibre."""
    on = browser.js("document.querySelector('[data-renderer].is-on').dataset.renderer")
    assert on == "merged"
    assert browser.js("window.__errors") == []


@pytest.mark.parametrize("grab", [(0.5, 0.5), (0.65, 0.6), (0.4, 0.35)])
def test_a_shift_drag_turns_about_the_ground_grabbed(browser, grab):
    """The ground under the pointer stays under it while the view turns. The pivot was
    clamped into the canvas *container*, which has no height, so it went to y = 0 — the
    horizon at a 60° tilt — and an 80 px turn moved the map from Krupka to Leipzig."""
    _reset(browser)
    left, top, width, height = _box(browser)
    x, y = width * grab[0], height * grab[1]
    ground = browser.js(f"({MAP}).unproject([{x}, {y}]).toArray()")
    browser.drag((left + x, top + y), (left + x + 80, top + y), modifiers=8)
    time.sleep(0.4)
    bearing = browser.js(f"({MAP}).getBearing()")
    where = browser.js(f"(() => {{ var p = ({MAP}).project({json.dumps(ground)}); return [p.x, p.y]; }})()")
    assert abs(bearing) > 30, "the drag turned the view"
    assert math.hypot(where[0] - x, where[1] - y) < 4, (ground, where, (x, y))


def test_a_plain_drag_pans_and_does_not_turn(browser):
    _reset(browser)
    left, top, width, height = _box(browser)
    browser.drag((left + width / 2, top + height / 2), (left + width / 2 + 120, top + height / 2))
    time.sleep(0.6)
    assert abs(browser.js(f"({MAP}).getBearing()")) < 0.5
    centre = browser.js(f"({MAP}).getCenter().toArray()")
    assert centre[0] < 14.1 - 0.01, "dragging right moves the map right: the centre goes west"


def test_the_airspace_hides_nothing(browser):
    """Translucent boxes must not write depth: one drawn before the track hid every part
    of the flight inside it, which over Krupka was nearly all of it."""
    _reset(browser)
    browser.js("document.querySelector('.merged-view [data-m3=airspace]').click(); 1")
    time.sleep(0.5)
    layers = {d["id"]: d["parameters"] for d in browser.js(f"({ENTRY}).layers()")}
    browser.js("document.querySelector('.merged-view [data-m3=airspace]').click(); 1")
    assert "airspace" in layers
    for name in ("airspace", "airspace-edges", "airspace-corners"):
        assert layers[name] and layers[name].get("depthWriteEnabled") is False, name
    assert any(name.startswith("track") for name in layers), layers


def test_the_measure_tool_adds_up_the_legs_on_the_sphere(browser):
    """Clicks are points, the readout is the total and the last leg, and a click while
    measuring is not also a turnpoint or anything else."""
    _reset(browser, pitch=0)
    left, top, width, height = _box(browser)
    browser.js("document.querySelector('.merged-view [data-m3=measure]').click(); 1")
    spots = [(0.3, 0.5), (0.6, 0.5), (0.6, 0.3)]
    points = []
    for fx, fy in spots:
        browser.click(left + width * fx, top + height * fy)
        time.sleep(0.4)
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
    assert float(after.split(" km")[0]) == pytest.approx(sphere(points[0], points[1]) / 1000, abs=0.02)
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

    browser.drag((x, y), (x + 60, y + 20))
    time.sleep(0.5)
    assert not browser.js(following), "a drag hands the camera back"


def test_two_fingers_tilt_and_turn_the_follow_camera(browser):
    """A phone has no arrows: moving two fingers up tilts the follow camera, a twist turns
    it off the direction of flight, and neither ends following. Taken as a pinch alone,
    a two-finger drag did nothing at all."""
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
        for k in range(1, 9):                          # both fingers 40 px up
            touch("touchMove", [(x - 60, y - 5 * k), (x + 60, y - 5 * k)])
            time.sleep(0.03)
        touch("touchEnd", [])
        after = browser.js(f"({ENTRY}).followCamera()")
        assert after["pitch"] == pytest.approx(min(85, before["pitch"] + 20), abs=2)
        assert after["zoom"] == pytest.approx(before["zoom"], abs=0.05), "not a pinch"

        touch("touchStart", [(x - 60, y), (x + 60, y)])
        for k in range(1, 9):                          # a twist, 30° clockwise on screen
            a = math.radians(30 * k / 8)
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
    time.sleep(1)
    camera = ("(() => { var p = (%s).transform.getCameraPosition();"
              " return [p.lngLat.lng, p.lngLat.lat, p.altitude]; })()" % MAP)
    before = browser.js(camera)
    browser.js(f"({ENTRY}).setFollow(false); 1")
    time.sleep(0.5)
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
    time.sleep(0.5)
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
    time.sleep(0.5)
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
    11 km to the side stays on screen, the view pulled back from 12.5 to hold it.

    Both tracks fly at ground level here: this map has no terrain (no network), and
    without terrain MapLibre keeps its orbit at 0 m, so a glider 1-2 km up would sit
    nearer the camera than the plane it orbits — which the real map, always over
    terrain, avoids by orbiting at the gliders' height."""
    _reset(browser)
    browser.js(f"""(() => {{
      var tr = __handle.built.scene.track, start = __handle.built.scene.start || 1700000000;
      window.__altBefore = tr.alt.slice();
      for (var k = 0; k < tr.alt.length; k++) tr.alt[k] = 10;
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
    time.sleep(2)
    left, top, width, height = _box(browser)
    spots = browser.js(f"""(() => {{
      var m = {MAP}, tr = __handle.built.scene.track, i = tr.t.indexOf(1800);
      // Where each glider is drawn: at its altitude, not on the ground under it.
      function at(lon, lat, alt) {{
        return m.transform.coordinatePoint(maplibregl.MercatorCoordinate.fromLngLat([lon, lat]), alt);
      }}
      return [at(tr.lon[i], tr.lat[i], tr.alt[i]), at(__beside.lon[i], __beside.lat[i], __beside.alt[i])]
        .map(p => [p.x, p.y]); }})()""")
    # Not just on the canvas: above the replay bar, the buttons and the legend over its
    # bottom, which on a phone cover a third of the map.
    clear = browser.js(f"""(() => {{ var top = ({MAP}).getContainer().getBoundingClientRect().top;
      return Math.min.apply(null, ['.m3-bottom'].map(s => document.querySelector('.merged-view ' + s))
        .filter(el => el && !el.hidden).map(el => el.getBoundingClientRect().top - top)); }})()""")
    for x, y in spots:
        assert 0 < x < width and 0 < y < clear, (spots, width, clear)
    browser.js(f"""({ENTRY}).setFollow(false); ({ENTRY}).setOthers(null);
      var tr = __handle.built.scene.track; __altBefore.forEach((a, k) => tr.alt[k] = a); 1""")


def test_no_errors_along_the_way(browser):
    assert browser.js("window.__errors") == []

"""The terrain a page fetches for itself is the terrain the build would have carried.

`terrain.remote()` ships a box and a grid, and `view3d`'s `loadTerrain` fetches the tiles
and samples them in the browser. It is the same grid built in two languages, so this
serves one set of synthetic terrarium tiles to both — Python's `terrain.fetch` and the
page's `loadTerrain` — and compares every node. No network: the tiles are made here and
served from localhost, with one of them missing so the hole-filling is compared too.
"""

import functools
import http.server
import io
import json
import math
import re
import subprocess
import threading

import numpy as np
import pytest

from tests.test_view3d_gl import CHROME, CHROME_FLAGS, needs_chrome
from parainsights_map import terrain, view3d

BOX = (13.6, 14.9, 49.1, 50.2)          # west, east, south, north
COLS, MAX_NODES = 90, 5000


def _elevation(lat, lon):
    """Relief with fractions in it, including exact halves, so rounding is compared."""
    return (400 + 350 * math.sin(lat * 7.1) * math.cos(lon * 5.3)
            + (int(lat * 1000 + lon * 1000) % 4) * 0.5 + 0.25 * (int(lon * 3000) % 2))


def _tile_png(zoom, x, y):
    from PIL import Image

    n = 2 ** zoom
    pixels = np.zeros((256, 256, 3), dtype=np.uint8)
    for r in range(256):
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + (r + 0.5) / 256) / n))))
        for c in range(256):
            lon = (x + (c + 0.5) / 256) / n * 360 - 180
            value = _elevation(lat, lon) + 32768
            whole = int(value)
            pixels[r, c] = (whole // 256, whole % 256, int(round((value - whole) * 256)) % 256)
    out = io.BytesIO()
    Image.fromarray(pixels, "RGB").save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def tile_server(tmp_path):
    zoom = terrain._choose_zoom(*BOX)
    x0, y0 = (int(v) for v in terrain._tile_indices(BOX[3], BOX[0], zoom))
    x1, y1 = (int(v) for v in terrain._tile_indices(BOX[2], BOX[1], zoom))
    missing = (x1, y1)                   # a corner tile never arrives
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            if (x, y) == missing:
                continue
            folder = tmp_path / "tiles" / str(zoom) / str(x)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{y}.png").write_bytes(_tile_png(zoom, x, y))

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp_path))
    handler.log_message = lambda *args: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield tmp_path, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


@needs_chrome
def test_the_page_builds_the_grid_the_build_would_have(tile_server, monkeypatch):
    root, base = tile_server
    url = base + "/tiles/{z}/{x}/{y}.png"
    monkeypatch.setattr(terrain, "TILE_URL", url)
    monkeypatch.setattr(terrain, "CACHE", root / "cache")

    carried = terrain.fetch(*BOX, cols=COLS, max_points=MAX_NODES).to_dict()
    remote = terrain.remote(*BOX, cols=COLS, max_points=MAX_NODES)
    assert remote["remote"]["url"] == url
    assert "z" not in remote, "the remote descriptor carries the heights after all"

    page = f"""<!doctype html><meta charset="utf-8">
<script>{view3d.SCRIPT}</script>
<pre id="out"></pre>
<script>
loadTerrain({json.dumps(remote)}).then(function (dem) {{
  document.getElementById('out').textContent = JSON.stringify(
    {{ rows: dem.rows, cols: dem.cols, min: dem.min, max: dem.max, z: dem.z }});
}}, function (error) {{
  document.getElementById('out').textContent = JSON.stringify({{ error: String(error) }});
}});
</script>"""
    (root / "page.html").write_text(page, encoding="utf-8")
    out = subprocess.run([CHROME, *CHROME_FLAGS, base + "/page.html"],
                         capture_output=True, text=True, timeout=180).stdout
    found = re.search(r'<pre id="out">(.*?)</pre>', out, re.S)
    assert found and found.group(1), out[-2000:]
    fetched = json.loads(found.group(1))
    assert "error" not in fetched, fetched

    assert (fetched["rows"], fetched["cols"]) == (carried["rows"], carried["cols"])
    assert (fetched["min"], fetched["max"]) == (carried["min"], carried["max"])
    differ = [i for i, (a, b) in enumerate(zip(fetched["z"], carried["z"])) if a != b]
    assert not differ, (f"{len(differ)} of {len(carried['z'])} nodes differ, first at "
                        f"{differ[0]}: page {fetched['z'][differ[0]]}, "
                        f"build {carried['z'][differ[0]]}")


def test_the_remote_descriptor_is_the_grid_fetch_would_build():
    """Same rows, columns and zoom as `fetch` — the page is handed the build's plan."""
    remote = terrain.remote(5.5, 20.5, 45.0, 51.3, cols=560, max_points=120000)
    assert remote["rows"] * remote["cols"] <= 120000
    assert (remote["rows"], remote["cols"]) == terrain._grid(5.5, 20.5, 45.0, 51.3,
                                                             560, 120000)
    assert remote["remote"]["zoom"] == terrain._choose_zoom(5.5, 20.5, 45.0, 51.3)


# ---- finer ground on zoom ---------------------------------------------------------------
#
# The whole path, with a real fetch: a tile server that answers any tile from a known
# function, a scene whose base grid is *not* that function, a wheel zoom, and the view
# left still. Afterwards the ground under the zoomed view has to be the function's.

def _known(lat, lon):
    return 900 + 400 * np.sin(lat * 311.0) * np.cos(lon * 207.0)


def _tile_on_the_fly(zoom, x, y):
    from PIL import Image

    n = 2 ** zoom
    rows = (y + (np.arange(256) + 0.5) / 256) / n
    cols = (x + (np.arange(256) + 0.5) / 256) / n
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * rows))))[:, None]
    lon = (cols * 360 - 180)[None, :]
    value = _known(lat, lon) + 32768
    whole = np.floor(value).astype(np.int64)
    rgb = np.stack([whole // 256, whole % 256,
                    np.round((value - whole) * 256).astype(np.int64) % 256], axis=-1)
    out = io.BytesIO()
    Image.fromarray(rgb.astype(np.uint8), "RGB").save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def any_tile():
    served = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            z, x, y = (int(part) for part in self.path.strip("/").removesuffix(".png")
                       .split("/")[-3:])
            served.append((z, x, y))
            body = _tile_on_the_fly(z, x, y)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/{{z}}/{{x}}/{{y}}.png", served
    finally:
        server.shutdown()


_ZOOM_AND_WAIT = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
var canvas = document.querySelector('canvas.view3d');
h.view.pitch = 0.9; h.view.yaw = 0; h.view.panX = 0; h.view.panY = 0; h.view.zoom = 1;
h.redraw();
var box = canvas.getBoundingClientRect();
for (var i = 0; i < 30; i++) canvas.dispatchEvent(new WheelEvent('wheel', {
  deltaY: -100, clientX: box.left + box.width / 2, clientY: box.top + box.height * 0.55,
  bubbles: true, cancelable: true }));
return new Promise(function (resolve) {
  setTimeout(function () {
    var state = h.terrainState();
    var samples = [];
    if (state) {
      for (var i = 1; i < 6; i++) for (var j = 1; j < 6; j++) {
        var lon = state.west + (state.east - state.west) * i / 6;
        var lat = state.south + (state.north - state.south) * j / 6;
        samples.push([lat, lon, h.groundAt(lon, lat)]);
      }
    }
    resolve({ state: state, samples: samples, gl: h.gl() });
  }, 4000);
});
"""


@needs_chrome
def test_zooming_in_fetches_finer_ground_and_stands_on_it(any_tile):
    from tests.test_view3d_gl import _probe, _scene, _terrain

    url, served = any_tile
    dem = {**_terrain(), "remote": {"url": url}}
    answer = _probe(_scene(terrain=dem, basemap=False), _ZOOM_AND_WAIT)
    assert served, "zooming in fetched no terrain at all"
    assert answer["state"], "tiles were served but no patch was put down"
    assert answer["gl"]["patchCells"] > 0
    worst = max(abs(ground - _known(lat, lon)) for lat, lon, ground in answer["samples"])
    # Nearest-pixel sampling and bilinear reading between nodes: a few metres on a
    # function this smooth. The base grid underneath is a different function entirely,
    # so reading it instead would miss by hundreds.
    assert worst < 15, f"the ground under the zoomed view is {worst:.0f} m off the tiles'"


_HOLD_WHERE_ZOOMED = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
var canvas = document.querySelector('canvas.view3d');
h.view.pitch = 0.7; h.view.yaw = 0.3; h.view.vertical = 3;
h.view.panX = 0; h.view.panY = 0; h.view.zoom = 1;
h.redraw();
var box = canvas.getBoundingClientRect();
var x = Math.round(box.left + box.width * 0.4), y = Math.round(box.top + box.height * 0.5);
for (var i = 0; i < 30; i++) canvas.dispatchEvent(new WheelEvent('wheel', {
  deltaY: -100, clientX: x, clientY: y, bubbles: true, cancelable: true }));
h.redraw();
// The ground under the cursor on the base grid, before any patch has been fetched.
var at = h.groundLonLat(x, y);
function screenOf() {
  var m = h.toMetres(at[0], at[1]);
  var p = h.worldProject(m[0], m[1], h.groundAt(at[0], at[1]));
  return [box.left + p[0] / canvas.width * box.width,
          box.top + p[1] / canvas.height * box.height];
}
var before = screenOf();
return new Promise(function (resolve) {
  setTimeout(function () {
    var after = screenOf();
    resolve({ patch: h.terrainState(), before: Math.hypot(before[0] - x, before[1] - y),
              after: Math.hypot(after[0] - x, after[1] - y) });
  }, 4000);
});
"""


@needs_chrome
def test_the_ground_zoomed_on_stays_put_when_finer_ground_lands(any_tile):
    """A patch changes the ground's height and so where it is on screen: over the
    Dolomites the ground under the cursor sat up to 39 px away from it once the patches
    had landed, the map jumping a moment after the reader stopped zooming. The fixture's
    base grid and the tile server's ground are different functions, so the jump here is
    large unless the view holds the point it was zoomed on."""
    from tests.test_view3d_gl import _probe, _scene, _terrain

    url, _ = any_tile
    dem = {**_terrain(), "remote": {"url": url}}
    answer = _probe(_scene(terrain=dem, basemap=False), _HOLD_WHERE_ZOOMED)
    assert answer["patch"], "no patch landed, so nothing was tested"
    assert answer["before"] < 0.5
    assert answer["after"] < 1.0, (
        f"the ground zoomed on moved {answer['after']:.1f} px when the finer ground landed")

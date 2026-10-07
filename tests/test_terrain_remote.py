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

from tests.browser import CHROME, CHROME_FLAGS, needs_chrome
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

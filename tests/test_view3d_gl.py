"""The WebGL heightfield, measured in a real browser. No network: the DEM is synthetic
and the basemap is generated, so nothing here reaches a host.

Why a browser at all. Every claim this backend makes is a claim about what a GPU does
with a matrix — that nothing folds, that the far terrain is not clipped away, that the
imagery lands on the ground rather than beside it. None of that is visible from Python,
and the canvas renderer it replaces had three separate artefacts that a green Python
suite never saw. So the tests drive Chrome and read numbers back out of the page.

The probe writes its answer into an element and the DOM is dumped, because Chrome cannot
be asked for the value of an expression. Timing is deliberately not asserted here:
under --virtual-time-budget the clock does not advance during synchronous work, so every
duration comes back zero. The measured frame costs are in docs/plan.md.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tracklog_viewer import render_kmz, view3d, view3d_gl

CHROME = shutil.which("google-chrome") or shutil.which("chromium")
needs_chrome = pytest.mark.skipif(CHROME is None, reason="needs headless Chrome")

# swiftshader, so this runs the same on a machine with no GPU — including CI. It is a
# software rasteriser, which makes the timing pessimistic and the geometry identical.
CHROME_FLAGS = [
    "--headless", "--disable-gpu", "--no-sandbox", "--window-size=1280,900",
    "--virtual-time-budget=20000", "--enable-unsafe-swiftshader",
    "--use-gl=angle", "--use-angle=swiftshader", "--dump-dom",
]


def _terrain(cols: int = 81, rows: int = 81) -> dict:
    """A ridged DEM, steep enough that the 2D renderer folds cells on it.

    A gentle grid would pass every test below on both renderers and prove nothing: cells
    fold where a slope is steeper than the pitch angle, so the fixture has to have some.
    """
    z = []
    for r in range(rows):
        for c in range(cols):
            ridge = math.sin(4 * math.pi * c / cols) * math.cos(3 * math.pi * r / rows)
            z.append(round(800 + 600 * ridge))
    return {
        "west": 14.0, "east": 14.25, "south": 49.0, "north": 49.25,
        "cols": cols, "rows": rows, "min": min(z), "max": max(z), "z": z,
    }


def _basemap() -> dict:
    """A real image, generated rather than typed. A hand-written base64 constant is
    unverifiable and the one in this repo's history was a corrupt PNG."""
    size = 16
    pixels = [
        [
            ((x * 16) % 256, (y * 16) % 256, ((x + y) * 8) % 256, 255)
            for x in range(size)
        ]
        for y in range(size)
    ]
    import base64

    uri = "data:image/png;base64," + base64.b64encode(
        render_kmz._png(pixels)
    ).decode("ascii")
    # Deliberately larger than the DEM's box, the way a tile mosaic always is: the UVs
    # have to be built from the image's box, not the terrain's, or the imagery lands
    # offset from the ground it belongs to.
    return {
        "west": 13.9, "east": 14.35, "south": 48.9, "north": 49.35,
        "uri": uri, "zoom": 12, "width": size, "height": size,
        "attribution": "Test imagery",
    }


def _scene(*, terrain: dict | None = None, basemap: bool = True) -> dict:
    dem = terrain or _terrain()
    track = {"lon": [], "lat": [], "alt": [], "c": []}
    for i in range(120):
        track["lon"].append(round(14.02 + i * 0.0015, 5))
        track["lat"].append(round(49.05 + math.sin(i / 15) * 0.02, 5))
        track["alt"].append(dem["max"] + 200 + i * 5)
        track["c"].append(i % 6)
    return {
        "terrain": dem,
        "trackTop": max(track["alt"]),
        "track": track,
        "climbs": [{"label": "1", "lon": 14.1, "lat": 49.1,
                    "alt": dem["max"] + 400, "tow": False}],
        "palette": [[20, 40, 60], [60, 90, 120], [120, 150, 60],
                    [200, 160, 40], [230, 110, 50], [240, 60, 40]],
        "basemaps": {"satellite": _basemap()} if basemap else {},
        "tiles": None,
        "landing": {"lon": 14.2, "lat": 49.2, "alt": dem["min"]},
    }


_HARNESS = """
<pre id="probe-out"></pre>
<script>%s
%s
window.__handle = initView3d(document.querySelector('.view3d-panel'), null);
</script>
<script>
window.addEventListener('load', function () {
  // setTimeout, never a chained requestAnimationFrame: rAF hangs outright under
  // --virtual-time-budget, and the delay lets the embedded basemap decode.
  setTimeout(function () {
    var answer;
    try { answer = (function () { %s })(); }
    catch (error) { answer = { error: String((error && error.stack) || error) }; }
    Promise.resolve(answer).then(function (value) {
      document.getElementById('probe-out').textContent = JSON.stringify(value);
    });
  }, 1200);
});
</script>
"""


def _probe(scene: dict, body: str, *, gl: bool = True) -> dict:
    """Render a panel carrying `scene`, run `body` in it, and return what it answered."""
    script = view3d_gl.SCRIPT
    if not gl:
        # Make the registration falsy rather than dropping it, so the page under test is
        # otherwise byte-identical. This is the no-WebGL path itself.
        script = script.replace(
            "window.__view3dBackend = function (host) {",
            "window.__view3dBackend = null && function (host) {")
        assert "null && function (host)" in script
    page = (
        '<!doctype html><meta charset="utf-8"><title>probe</title>'
        f"<style>{view3d.STYLE}{view3d_gl.STYLE}</style>"
        f'<div class="wrap">{view3d.panel(scene, "t")}</div>'
        + _HARNESS % (view3d.SCRIPT, script, body)
    )
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "probe.html"
        target.write_text(page, encoding="utf-8")
        result = subprocess.run(
            [CHROME, *CHROME_FLAGS, target.as_uri()],
            capture_output=True, text=True, timeout=180,
        )
    match = re.search(r'<pre id="probe-out">(.*?)</pre>', result.stdout, re.S)
    assert match and match.group(1).strip(), (
        "the probe produced nothing:\n" + result.stderr[-2000:])
    text = match.group(1)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                         ("&amp;", "&")):
        text = text.replace(entity, char)
    answer = json.loads(text)
    assert "error" not in answer, answer.get("error")
    return answer


# Every camera the sweep visits: shallow pitches are where cells fold, high zooms are
# where the fold is large enough to see.
_SWEEP = """
var h = window.__handle;
var dem = JSON.parse(document.querySelector('.view3d-data').textContent).terrain;
var out = { backend: h.gl() ? h.gl().version : 'canvas2d', info: h.gl(),
            cameras: 0, folded: 0, foldedCameras: 0, cells: 0,
            worstPixels: 0, depthMin: 1e9, depthMax: -1e9 };
var corners = [];
[[dem.west, dem.north], [dem.east, dem.north],
 [dem.west, dem.south], [dem.east, dem.south]].forEach(function (corner) {
  var m = h.toMetres(corner[0], corner[1]);
  [dem.min, dem.max, (dem.min + dem.max) / 2].forEach(function (z) {
    corners.push([m[0], m[1], z]);
  });
});
[0.18, 0.25, 0.35, 0.46, 0.7, 1.0, 1.45].forEach(function (pitch) {
  [1, 2, 4, 7, 12].forEach(function (zoom) {
    [-0.42, 0.6, 2.1].forEach(function (yaw) {
      h.view.pitch = pitch; h.view.zoom = zoom; h.view.yaw = yaw;
      h.redraw();
      out.cameras++;
      var stats = h.stats();
      out.cells = stats.cells;
      out.folded += stats.folded;
      if (stats.folded > 0) out.foldedCameras++;
      if (!h.gl()) return;
      corners.forEach(function (point) {
        var a = h.worldProject(point[0], point[1], point[2]);
        var b = h.glScreenOf(point[0], point[1], point[2]);
        var off = Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]));
        if (off > out.worstPixels) out.worstPixels = off;
        var depth = h.glDepthOf(point[0], point[1], point[2]);
        if (depth < out.depthMin) out.depthMin = depth;
        if (depth > out.depthMax) out.depthMax = depth;
      });
    });
  });
});
return out;
"""


_MESH = """
var h = window.__handle;
h.setInteracting(false);
h.redraw();
var settled = h.stats().cells;
h.setInteracting(true);
h.redraw();
var dragging = h.stats().cells;
h.setInteracting(false);
return { cells: settled, dragging: dragging, grid: h.grid() };
"""


@pytest.fixture(scope="module")
def swept():
    """One browser run, many assertions: launching Chrome is the expensive part."""
    return _probe(_scene(), _SWEEP)


@pytest.fixture(scope="module")
def swept_canvas():
    return _probe(_scene(), _SWEEP, gl=False)


@needs_chrome
class TestBackendMounts:
    def test_it_takes_and_reports_a_depth_buffer(self, swept):
        """The whole argument for this module is that a depth buffer is available where
        an external script is not."""
        assert swept["info"]["active"] is True
        assert swept["info"]["version"] in ("webgl", "webgl2")
        assert swept["info"]["depthBits"] >= 16

    def test_it_draws_every_cell_of_the_grid_it_was_given(self, swept):
        assert swept["cells"] == 80 * 80

    def test_the_basemap_reaches_the_texture(self, swept):
        assert swept["info"]["textured"] is True

    def test_a_real_sized_dem_is_drawn_whole_rather_than_budgeted(self):
        """The 2D renderer caps its mesh at FINE_BUDGET cells because each one costs a
        drawImage, so on a real 26 000-node DEM it draws a quarter of the grid the
        report actually carries. One draw call has no such budget.

        Measured on the 161×161 grid a single-flight report embeds, which is where the
        cap bites — the smaller fixture the sweep uses falls under it and would show no
        difference at all."""
        full = _terrain(161, 161)
        mesh = _probe(_scene(terrain=full), _MESH)
        budgeted = _probe(_scene(terrain=full), _MESH, gl=False)
        assert mesh["cells"] == 160 * 160
        assert budgeted["cells"] < mesh["cells"] / 3
        # The coarse-while-dragging swap exists only because the fine mesh is too slow
        # to run on a gesture. With one draw call there is nothing to trade.
        assert mesh["dragging"] == mesh["cells"]
        assert budgeted["dragging"] < budgeted["cells"]


@needs_chrome
class TestNothingFolds:
    def test_the_canvas_renderer_folds_on_this_terrain(self, swept_canvas):
        """The control. Without this the test below would pass on a fixture too gentle
        to fold anything, and would be measuring nothing at all."""
        assert swept_canvas["foldedCameras"] > 0, (
            "the fixture is too gentle to fold a cell — it cannot show the fix")

    def test_the_gl_renderer_folds_at_no_camera(self, swept):
        """A fold is an artefact of painter's order. Under a depth buffer there is no
        such thing: only triangles, resolved per pixel."""
        assert swept["cameras"] == 105
        assert swept["folded"] == 0
        assert swept["foldedCameras"] == 0


@needs_chrome
class TestTheCameraIsTheSameCamera:
    def test_the_matrix_agrees_with_project_to_a_hundredth_of_a_pixel(self, swept):
        """The track, the climb markers and the cursor are drawn in 2D with project(),
        over a heightfield drawn from the matrix. If the two disagree the track floats
        off the ground, and every gesture — which anchors through groundUnder() and
        holdGround() — anchors to the wrong place."""
        assert swept["worstPixels"] < 0.01

    def test_the_terrain_stays_inside_the_clip_range(self, swept):
        """Depth is normalised against the terrain's own box. Overflow clips the far
        ground away silently, which looks like the DEM simply ending."""
        assert -1.0 < swept["depthMin"]
        assert swept["depthMax"] < 1.0


_PAINTED = """
var h = window.__handle;
h.redraw();
var canvas = document.querySelector('canvas.view3d-gl');
if (!canvas) return { error: 'no GL canvas in the panel' };
// preserveDrawingBuffer is on, so the buffer survives the draw call and can be read.
var off = document.createElement('canvas');
off.width = 160; off.height = 90;
var ctx = off.getContext('2d');
ctx.drawImage(canvas, 0, 0, 160, 90);
var pixels = ctx.getImageData(0, 0, 160, 90).data;
var opaque = 0, shades = {};
for (var i = 0; i < pixels.length; i += 4) {
  if (pixels[i + 3] > 200) {
    opaque++;
    shades[(pixels[i] >> 4) + ',' + (pixels[i + 1] >> 4) + ',' + (pixels[i + 2] >> 4)] = 1;
  }
}
return { fraction: opaque / (160 * 90), shades: Object.keys(shades).length,
         size: [canvas.width, canvas.height] };
"""


@needs_chrome
class TestItActuallyDraws:
    def test_the_heightfield_covers_the_canvas_in_more_than_one_colour(self):
        """"Look at the output" is a habit in this repo because the validator checks
        colour and not layout. A backing store full of one flat colour is what a
        silently failing shader produces, and it passes every numeric test above."""
        painted = _probe(_scene(), _PAINTED)
        assert painted["size"][0] > 0 and painted["size"][1] > 0
        assert painted["fraction"] > 0.2, "the terrain barely covered the canvas"
        assert painted["shades"] > 8, "the terrain came out a single flat colour"

    def test_bare_relief_draws_without_any_imagery(self):
        """The basemap button cycles to bare terrain, and a document may carry no
        imagery at all. Then the colour comes from the vertex attribute instead."""
        painted = _probe(_scene(basemap=False), _PAINTED)
        assert painted["fraction"] > 0.2
        assert painted["shades"] > 8


_FLAT = """
var h = window.__handle;
h.redraw();
var dem = JSON.parse(document.querySelector('.view3d-data').textContent).terrain;
var a = h.toMetres(dem.west, dem.north), b = h.toMetres(dem.east, dem.south);
return {
  info: h.gl(),
  folded: h.stats().folded,
  depth: [h.glDepthOf(a[0], a[1], dem.min), h.glDepthOf(b[0], b[1], dem.min)],
  agreement: (function () {
    var p = h.worldProject(a[0], a[1], dem.min), q = h.glScreenOf(a[0], a[1], dem.min);
    return Math.max(Math.abs(p[0] - q[0]), Math.abs(p[1] - q[1]));
  })()
};
"""


@needs_chrome
def test_a_flat_plane_still_resolves():
    """An uploaded track gets no DEM — a published page cannot fetch one — so its ground
    is one plane and dem.min === dem.max. Every vertex then shares an elevation, and the
    depth range has to come out of x and y alone or the normalisation divides by nothing.
    """
    plane = {"west": 14.0, "east": 14.25, "south": 49.0, "north": 49.25,
             "cols": 61, "rows": 25, "min": 480, "max": 480, "z": [480] * (61 * 25)}
    flat = _probe(_scene(terrain=plane, basemap=False), _FLAT)
    assert flat["info"]["active"] is True
    assert flat["folded"] == 0
    assert flat["agreement"] < 0.01
    near, far = sorted(flat["depth"])
    assert near < far, "a plane must still have a near and a far edge"
    assert -1.0 < near and far < 1.0


_LOST = """
var h = window.__handle;
h.redraw();
var before = h.gl();
var canvas = document.querySelector('canvas.view3d-gl');
var lose = canvas.getContext('webgl2') || canvas.getContext('webgl');
lose.getExtension('WEBGL_lose_context').loseContext();
// The event is delivered in a later task, so the check has to wait for one.
return new Promise(function (resolve) {
  setTimeout(function () {
    h.redraw();
    var stats = h.stats();
    resolve({
      wasActive: !!(before && before.active),
      nowActive: !!h.gl(),
      glCanvasGone: !document.querySelector('canvas.view3d-gl'),
      classGone: !document.querySelector('.view3d-panel').classList.contains('has-gl'),
      cells: stats.cells
    });
  }, 300);
});
"""


@needs_chrome
def test_losing_the_context_hands_the_terrain_back_to_the_canvas():
    """Context loss is real — a background tab, a driver reset, or simply more panels in
    one document than the browser's ~16 contexts. A blank panel is a worse outcome than
    a slower one, so the loss is not fought: the 2D renderer takes the heightfield back,
    and it needs nothing from the backend to do it."""
    lost = _probe(_scene(), _LOST)
    assert lost["wasActive"] is True
    assert lost["nowActive"] is False
    assert lost["glCanvasGone"] is True
    assert lost["classGone"] is True, (
        "the 2D canvas stays transparent while has-gl is set, so a stale class leaves "
        "the panel showing nothing but sky")
    assert lost["cells"] > 0, "the canvas renderer did not resume drawing terrain"


_DISPOSE = """
var h = window.__handle;
h.redraw();
var had = !!h.gl();
h.dispose();
return { had: had, active: !!h.gl(),
         canvasGone: !document.querySelector('canvas.view3d-gl') };
"""


@needs_chrome
def test_disposing_a_removed_flight_gives_the_context_back():
    """Flights accumulate and any of them can be removed. A page gets about sixteen
    WebGL contexts, so a document that leaked one per panel would run out and quietly
    serve every flight the 2D renderer instead."""
    gone = _probe(_scene(), _DISPOSE)
    assert gone["had"] is True
    assert gone["active"] is False
    assert gone["canvasGone"] is True


class TestWiring:
    """Python-level, so these run everywhere — including without a browser."""

    def test_the_module_offers_the_same_surface_as_view3d(self):
        """The payload, the markup and the controls are unchanged: this replaces how the
        heightfield is drawn, not what is in the document."""
        for name in ("data", "panel", "cursor_track", "TILE_SOURCES"):
            assert getattr(view3d_gl, name) is getattr(view3d, name)

    def test_the_report_carries_both_renderers(self):
        """The canvas path is the fallback, so it has to still be in the document — and
        the backend has to register before anything calls initView3d."""
        from tracklog_viewer import render_html

        page = render_html._page("t", ["<article></article>"])
        assert view3d_gl.STYLE in page
        assert page.index(view3d.SCRIPT) < page.index(view3d_gl.SCRIPT), (
            "the backend reads initView3d's host object, so view3d.SCRIPT comes first")
        assert "initView3d" in page

    def test_the_canvas_renderer_is_still_whole(self):
        """`view3d.py` is the fallback and a live one — it is what runs after a context
        loss, not only on a browser with no WebGL. Deleting its drape would make that
        path a blank panel."""
        assert "function drawTerrain(" in view3d.SCRIPT
        assert "function fillHull(" in view3d.SCRIPT
        assert "function texturedTriangle(" in view3d.SCRIPT

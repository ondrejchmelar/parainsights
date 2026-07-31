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


def _png(rgba) -> bytes:
    """PNG out of a numpy RGBA array. `render_kmz._png` takes lists of tuples, which is
    fine for a 16 px icon and far too slow for the 1024 px texture the sharpness test
    needs."""
    import struct
    import zlib

    height, width, _ = rgba.shape
    raw = b"".join(b"\x00" + row.tobytes() for row in rgba)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def _basemap(size: int = 256) -> dict:
    """A real image, generated rather than typed. A hand-written base64 constant is
    unverifiable and the one in this repo's history was a corrupt PNG.

    `size` is what makes the sharpness test able to fail. Mip levels above zero are only
    selected where the texture is *minified*, so a small image stretched over the whole
    heightfield is magnified everywhere and mipmapping cannot blur anything — a 256 px
    fixture let the mipmapped renderer pass. The detail is a fine checker, which carries
    the most high-frequency energy per byte and compresses to almost nothing.
    """
    import numpy as np

    y, x = np.mgrid[0:size, 0:size]
    checker = ((x >> 1) + (y >> 1)) & 1
    coarse = (((x >> 5) * 37 + (y >> 5) * 53) % 256).astype(np.uint8)
    rgba = np.empty((size, size, 4), dtype=np.uint8)
    rgba[..., 0] = np.where(checker, 235, 40)
    rgba[..., 1] = np.where(checker, 210, 70) // 2 + coarse // 2
    rgba[..., 2] = np.where(checker, 60, 200)
    rgba[..., 3] = 255

    import base64

    uri = "data:image/png;base64," + base64.b64encode(_png(rgba)).decode("ascii")
    # Deliberately larger than the DEM's box, the way a tile mosaic always is: the UVs
    # have to be built from the image's box, not the terrain's, or the imagery lands
    # offset from the ground it belongs to.
    return {
        "west": 13.9, "east": 14.35, "south": 48.9, "north": 49.35,
        "uri": uri, "zoom": 12, "width": size, "height": size,
        "attribution": "Test imagery",
    }


def _scene(*, terrain: dict | None = None, basemap: bool = True,
           basemap_size: int = 256, sun: dict | None = None,
           wind: dict | None = None, cursor: dict | None = None) -> dict:
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
        "basemaps": {"satellite": _basemap(basemap_size)} if basemap else {},
        "tiles": None,
        "landing": {"lon": 14.2, "lat": 49.2, "alt": dem["min"]},
        # Absent unless a test asks for them: a panel with no date has no sun and an
        # uploaded track may have no wind estimate, and neither may draw anything then.
        **({"sun": sun} if sun else {}),
        **({"wind": wind} if wind else {}),
        # Not part of the payload: the cursor track is initView3d's second argument, and
        # `_probe` lifts it out of here and hands it over as one.
        **({"__cursor": cursor} if cursor else {}),
    }


_HARNESS = """
<pre id="probe-out"></pre>
<script>%s
%s
window.__handle = initView3d(document.querySelector('.view3d-panel'),
                            window.__cursorTrack || null);
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


def _probe(scene: dict, body: str, *, gl: bool = True, page_extra: str = "",
           doctype: bool = True, device_scale: float | None = None) -> dict:
    """Render a panel carrying `scene`, run `body` in it, and return what it answered.

    `page_extra` is markup appended after the panel. The real report is several screens
    tall, so the document has a scrollbar from the first layout — which is a fact the
    full-bleed panel is sized against, and a short probe page does not have one.

    `doctype=False` renders the page in quirks mode, which the report itself did until
    the full-screen bug was traced to it. It is kept as a switch because the panel is
    embeddable and cannot control the document it lands in.

    `device_scale` drives the device pixel ratio. The backing store is the box times that
    ratio, so anything that converts between CSS and canvas pixels is only half tested at
    a ratio of 1 — which is how a rotation gesture came to turn twice as far on a retina
    screen as on the machine it was tuned on.
    """
    script = view3d_gl.SCRIPT
    if not gl:
        # Make the registration falsy rather than dropping it, so the page under test is
        # otherwise byte-identical. This is the no-WebGL path itself.
        script = script.replace(
            "window.__view3dBackend = function (host) {",
            "window.__view3dBackend = null && function (host) {")
        assert "null && function (host)" in script
    cursor = dict(scene).pop("__cursor", None)
    scene = {k: v for k, v in scene.items() if k != "__cursor"}
    page = (
        ('<!doctype html>' if doctype else '')
        + '<meta charset="utf-8"><title>probe</title>'
        f"<style>{view3d.STYLE}{view3d_gl.STYLE}</style>"
        f'<div class="wrap">{view3d.panel(scene, "t")}</div>'
        + (f"<script>window.__cursorTrack = {json.dumps(cursor)};</script>" if cursor else "")
        + page_extra
        + _HARNESS % (view3d.SCRIPT, script, body)
    )
    flags = list(CHROME_FLAGS)
    if device_scale is not None:
        flags.append(f"--force-device-scale-factor={device_scale}")
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "probe.html"
        target.write_text(page, encoding="utf-8")
        result = subprocess.run(
            [CHROME, *flags, target.as_uri()],
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


# Detail actually reaching the screen, measured the way a focus metric is: the variance
# of the Laplacian over the composited panel. Both renderers are asked for the same
# scene at the same camera, so the number is comparable between them.
_SHARPNESS = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
h.view.zoom = 4;
h.view.pitch = 0.20;
h.redraw();
var panel = document.querySelector('.view3d-panel');
var gl = panel.querySelector('canvas.view3d-gl');
var flat = panel.querySelector('canvas.view3d');
var W = 480, H = 200;
var off = document.createElement('canvas');
off.width = W; off.height = H;
var ctx = off.getContext('2d');
// Composite in paint order: the heightfield, then the 2D overlay over it. With no
// backend the first is absent and the second carries the terrain itself.
if (gl) ctx.drawImage(gl, 0, 0, W, H);
ctx.drawImage(flat, 0, 0, W, H);
var px = ctx.getImageData(0, 0, W, H).data;
var grey = new Float64Array(W * H);
for (var i = 0; i < W * H; i++) {
  grey[i] = 0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2];
}
var sum = 0, sumSq = 0, n = 0;
for (var y = 1; y < H - 1; y++) {
  for (var x = 1; x < W - 1; x++) {
    var k = y * W + x;
    var lap = grey[k - 1] + grey[k + 1] + grey[k - W] + grey[k + W] - 4 * grey[k];
    sum += lap; sumSq += lap * lap; n++;
  }
}
var mean = sum / n;
return { detail: sumSq / n - mean * mean, backend: h.gl() ? h.gl().version : 'canvas2d',
         minFilter: h.gl() ? h.gl().minFilter : null,
         anisotropy: h.gl() ? h.gl().anisotropy : null };
"""


@needs_chrome
def test_the_terrain_is_no_blurrier_than_the_renderer_it_replaces():
    """A regression test for a real one, and an honest note about what it can prove.

    Mipmapping the draped texture looked obviously correct and cost more than half the
    detail on screen. Terrain is viewed from a grazing angle, and mip level is chosen
    from the longest texture derivative — so at low pitch an isotropic lookup blurs by
    the elongated axis in both directions and discards the short one, which is where the
    detail is. It arrived as two complaints with one cause: the imagery went soft, and
    the terrain went *flat*, because shadedTexture() bakes the hillshade into the very
    texture being blurred away.

    Laplacian variance of the rendered panel at zoom 4 / pitch 0.20, GL against the
    canvas renderer it replaces, on the Blatná flight — a real DEM and a real basemap:

        mipmapped, isotropic         44%
        mipmapped, 16x anisotropic   64%
        no mipmaps (what ships)      98%

    **This test does not reproduce that.** On the synthetic fixture the same three
    configurations measure 94%, 92% and 103%: the effect needs the particular ratio
    between texture resolution and projected ground scale that a real DEM and a stitched
    basemap have, and raising the fixture's texture to 1024 px did not manufacture it.
    So the assertion below is a floor against gross blurring, not proof of that fix. The
    filter check is the specific guard, and it is read back out of the texture rather
    than reported from a literal.
    """
    scene = _scene(basemap_size=1024)
    gl = _probe(scene, _SHARPNESS)
    flat = _probe(scene, _SHARPNESS, gl=False)
    assert flat["detail"] > 0, "the canvas renderer drew nothing to compare against"
    assert gl["detail"] >= 0.85 * flat["detail"], (
        "the WebGL terrain came out blurrier than the 2D drape it replaces: "
        f"{gl['detail']:.1f} against {flat['detail']:.1f}")
    LINEAR = 9729
    assert gl["minFilter"] == LINEAR, (
        "the draped texture is filtered LINEAR with no mipmaps on purpose — the "
        "docstring above has what mipmapping cost last time it was tried, measured on a "
        "real report rather than on this fixture")


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

    def test_the_report_declares_a_doctype(self):
        """Without one the page is in quirks mode, where `documentElement.clientHeight`
        is the height of the whole document — which is what the maximised 3D canvas was
        sized from, giving a 4 316 px canvas inside an 813 px panel."""
        from tracklog_viewer import render_html

        page = render_html._page("t", ["<article></article>"])
        assert page.lstrip().lower().startswith("<!doctype html>")

    def test_the_maximised_canvas_is_sized_from_its_panel(self):
        """Not from a global that means something different in quirks mode. The browser
        test in test_view3d_fullscreen.py measures the consequence; this is the cause,
        and it is cheap enough to check without a browser."""
        assert "panel.clientWidth" in view3d.SCRIPT
        assert "document.documentElement.clientWidth + 'px'" not in view3d.SCRIPT

    def test_the_canvas_renderer_is_still_whole(self):
        """`view3d.py` is the fallback and a live one — it is what runs after a context
        loss, not only on a browser with no WebGL. Deleting its drape would make that
        path a blank panel."""
        assert "function drawTerrain(" in view3d.SCRIPT
        assert "function fillHull(" in view3d.SCRIPT
        assert "function texturedTriangle(" in view3d.SCRIPT

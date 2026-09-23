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
           wind: dict | None = None, cursor: dict | None = None,
           tiles: bool = False, airspace: bool = False) -> dict:
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
        # One of each, so a test can turn the two label switches on independently and see
        # that each drew only its own.
        "phases": [
            {"kind": "climb", "text": "+2.1 m/s · +480 m",
             "lon": [14.04, 14.06], "lat": [49.06, 49.08],
             "alt": [dem["max"] + 220, dem["max"] + 700]},
            {"kind": "glide", "text": "8.4:1 · 12.0 km",
             "lon": [14.06, 14.14], "lat": [49.08, 49.12],
             "alt": [dem["max"] + 700, dem["max"] + 260]},
        ],
        "palette": [[20, 40, 60], [60, 90, 120], [120, 150, 60],
                    [200, 160, 40], [230, 110, 50], [240, 60, 40]],
        "basemaps": {"satellite": _basemap(basemap_size)} if basemap else {},
        # Templates only, and nothing fetches them: the embedded image above is what the
        # panel drapes. They are here so the *detail* planner has a source to reason
        # about, which is the half of that feature a test can reach without a network.
        "tiles": view3d.TILE_SOURCES if tiles else None,
        "landing": {"lon": 14.2, "lat": 49.2, "alt": dem["min"]},
        # Absent unless a test asks for them: a panel with no date has no sun and an
        # uploaded track may have no wind estimate, and neither may draw anything then.
        **({"sun": sun} if sun else {}),
        **({"wind": wind} if wind else {}),
        # One zone over the flight, behind the switch a flight map offers — the shape
        # the viewer sees, which is not the shape the airspace map sees: there the layer
        # is the subject, is on, and has no button.
        **({
            "airspaces": [{
                "k": "base", "n": "TMA TEST  (GND – FL 95)", "f": 0, "g": True,
                "c": 2896,
                "lon": [14.05, 14.20, 14.20, 14.05],
                "lat": [49.05, 49.05, 49.20, 49.20],
            }],
            "airspaceColours": {"base": "#c2410c"},
            "airspaceToggle": True,
        } if airspace else {}),
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
           doctype: bool = True, device_scale: float | None = None,
           window: tuple[int, int] | None = None) -> dict:
    """Render a panel carrying `scene`, run `body` in it, and return what it answered.

    `page_extra` is markup appended after the panel. The real report is several screens
    tall, so the document has a scrollbar from the first layout — which is a fact the
    full-bleed panel is sized against, and a short probe page does not have one.

    `window` replaces the default 1280 x 900 viewport. It has to be the real window and
    not a narrowed wrapper: the panel is full-bleed to `100vw` and its own layout rules
    are media queries, so a phone layout only exists at a phone-sized viewport.

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
    if window is not None:
        flags = [f for f in flags if not f.startswith("--window-size=")]
        flags.append(f"--window-size={window[0]},{window[1]}")
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


# The optional phase labels. Whether they *draw* is not visible from Python, and the
# canvas that matters is the 2D overlay — the GL canvas behind it carries the heightfield
# and nothing else, so sampling that one shows no change however well the labels work.
_LABELS = """
var h = window.__handle;
var panel = document.querySelector('.view3d-panel');
var overlay = panel.querySelector('canvas.view3d');
function shot() {
  h.redraw();
  var s = document.createElement('canvas');
  s.width = 96; s.height = 96;
  s.getContext('2d').drawImage(overlay, 0, 0, 96, 96);
  return s.toDataURL();
}
var btns = panel.querySelectorAll('[data-view3d-act="labels-toggle"]');
var out = { buttons: btns.length };
out.pressedAtRest = [].map.call(btns, function (b) {
  return b.getAttribute('aria-pressed');
}).join(',');

var bare = shot();
btns[0].click();
var climbs = shot();
btns[1].click();
var both = shot();
btns[0].click();
btns[1].click();
var off = shot();

out.climbsDrew = climbs !== bare;
out.glidesDrew = both !== climbs;
out.turningBothOffRestoresIt = off === bare;
return out;
"""


@needs_chrome
def test_phase_labels_are_off_until_asked_for_and_draw_when_they_are():
    """Two independent switches, both starting off.

    A label per climb *and* per glide over a long flight is more ink than terrain, so
    neither is on by default and neither implies the other. Turning both off again has to
    put the view back exactly as it was, which is what catches a label drawn into some
    state the toggle does not own.
    """
    from tests.test_view3d_sun import CURSOR

    answer = _probe(_scene(basemap=False, cursor=CURSOR), _LABELS)
    assert answer["buttons"] == 2
    assert answer["pressedAtRest"] == "false,false", "a label switch started on"
    assert answer["climbsDrew"] is True, "the climb labels drew nothing"
    assert answer["glidesDrew"] is True, "the glide labels drew nothing"
    assert answer["turningBothOffRestoresIt"] is True


# ---- the detail mosaic ---------------------------------------------------------------
#
# Zooming in used to magnify the base mosaic's own pixels: the view got closer and the
# ground got blurrier, which is the opposite of what zooming is for. A second, sharper
# mosaic is now stitched over whatever is on screen once the camera settles. The fetch
# needs a tile server; the two things that can be wrong here do not.

_DETAIL_PLAN = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
function plan(zoom) {
  h.view.zoom = zoom; h.view.pitch = 0.9; h.view.yaw = 0;
  h.view.panX = 0; h.view.panY = 0;
  h.redraw();
  var p = h.detailPlan();
  return p ? { zoom: p.zoom, tiles: p.tiles,
               width: Number((p.box.east - p.box.west).toFixed(4)) } : null;
}
var out = { rest: plan(1), near: plan(8), nearer: plan(24) };
// Having fetched it, the same camera must not ask again.
h.view.zoom = 8; h.redraw();
var again = h.detailPlan();
h.setDetail(document.querySelector('canvas.view3d'), again.box, again.zoom);
h.view.zoom = 8; h.redraw();
out.repeat = h.detailPlan();
out.state = h.detailState();
return out;
"""


_VISIBLE = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
var canvas = document.querySelector('canvas.view3d');
h.view.vertical = 5; h.view.pitch = 1.32; h.view.yaw = 0.4;
h.view.zoom = 16; h.view.panX = 0; h.view.panY = 0;
h.redraw();
var seen = h.visibleBox();
var dem = %s;
var outside = [], inside = 0;
for (var r = 0; r < dem.rows; r++) for (var c = 0; c < dem.cols; c++) {
  var lon = dem.west + (dem.east - dem.west) * c / (dem.cols - 1);
  var lat = dem.north + (dem.south - dem.north) * r / (dem.rows - 1);
  var m = h.toMetres(lon, lat);
  var p = h.worldProject(m[0], m[1], dem.z[r * dem.cols + c]);
  if (p[0] < 0 || p[0] > canvas.width || p[1] < 0 || p[1] > canvas.height) continue;
  inside++;
  // One grid cell: the box is taken from four corners, and ground between them can
  // stand a little higher than the ground under them.
  var slack = (dem.east - dem.west) / (dem.cols - 1);
  if (lon < seen.west - slack || lon > seen.east + slack
      || lat < seen.south - slack || lat > seen.north + slack) outside.push([lon, lat]);
}
return { onScreen: inside, missed: outside.length, first: outside[0] || null };
"""


@needs_chrome
def test_the_visible_box_is_the_ground_on_screen_not_the_datum():
    """The detail imagery is fetched for `visibleBox`, and it took the canvas corners on
    the flat plane at `dem.min`. On raised, exaggerated ground the real surface stands
    above that plane and projects higher up the screen, so the box slid away from what
    was on screen — on the planner, the lower third of a fully zoomed view stayed
    blurred. Checked from the other end: every terrain node the camera actually draws on
    the canvas has to be inside the box."""
    dem = _terrain()
    answer = _probe(_scene(terrain=dem, tiles=True), _VISIBLE % json.dumps(dem))
    assert answer["onScreen"] > 10, "the camera shows too little ground to test anything"
    assert answer["missed"] == 0, (
        f"{answer['missed']} of {answer['onScreen']} on-screen nodes are outside the "
        f"visible box, first at {answer['first']}")


@needs_chrome
def test_zooming_in_asks_for_a_sharper_mosaic_and_only_once():
    """Three claims. The finer the zoom, the smaller the box on screen and the higher the
    tile zoom that box can afford — so zooming in buys sharpness rather than magnifying
    the pixels it already had. And once a patch has been fetched, sitting still at the
    same camera must not ask for it again: the alternative is a page that fetches tiles
    forever.

    The resting view asks for one too, and that is correct here rather than a miss: this
    fixture's basemap is *embedded*, so no mosaic has been stitched, and an embedded
    image is the coarsest thing this view ever drapes. Against a stitched base the same
    camera asks for nothing, because `mosaicZoom` is then the zoom that base reached and
    a plan has to beat it by `DETAIL_STEP`.
    """
    answer = _probe(_scene(tiles=True), _DETAIL_PLAN)
    assert answer["near"] and answer["nearer"], "zooming in asked for nothing"
    assert answer["near"]["zoom"] > answer["rest"]["zoom"], (
        "zooming in from rest did not buy a finer tile zoom")
    assert answer["nearer"]["zoom"] > answer["near"]["zoom"], (
        "zooming further in did not buy a finer tile zoom")
    assert answer["nearer"]["width"] < answer["near"]["width"], (
        "the box asked for did not shrink as the view zoomed in")
    assert answer["near"]["tiles"] <= 48, "a detail fetch blew the tile budget"
    assert answer["repeat"] is None, "the same camera asked for the same patch twice"
    assert answer["state"]["zoom"] == answer["near"]["zoom"]


_DETAIL_PIXELS = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
var panel = document.querySelector('.view3d-panel');
var gl = panel.querySelector('canvas.view3d-gl');
if (!gl) return { skipped: true };

h.view.zoom = 8; h.view.pitch = 0.9; h.view.yaw = 0;
h.view.panX = 0; h.view.panY = 0;
h.redraw();

function centre() {
  var off = document.createElement('canvas');
  off.width = 60; off.height = 60;
  var ctx = off.getContext('2d');
  ctx.drawImage(gl, gl.width / 2 - 30, gl.height / 2 - 30, 60, 60, 0, 0, 60, 60);
  var px = ctx.getImageData(0, 0, 60, 60).data;
  var r = 0, g = 0, b = 0;
  for (var i = 0; i < 60 * 60; i++) { r += px[i * 4]; g += px[i * 4 + 1]; b += px[i * 4 + 2]; }
  return [Math.round(r / 3600), Math.round(g / 3600), Math.round(b / 3600)];
}

var before = centre();

// A flat magenta patch over the middle of the terrain, standing in for a stitch that
// cannot happen offline. Nothing in the fixture's imagery is this colour, so if it
// appears on screen it came through the detail sampler and nowhere else.
var patch = document.createElement('canvas');
patch.width = patch.height = 64;
var pctx = patch.getContext('2d');
pctx.fillStyle = '#ff00ff';
pctx.fillRect(0, 0, 64, 64);
var dem = JSON.parse(document.querySelector('.view3d-data').textContent).terrain;
var midLon = (dem.west + dem.east) / 2, midLat = (dem.south + dem.north) / 2;
var w = (dem.east - dem.west) * 0.2, hgt = (dem.north - dem.south) * 0.2;
h.setDetail(patch, { west: midLon - w, east: midLon + w,
                     south: midLat - hgt, north: midLat + hgt }, 15);
h.redraw();
var after = centre();

h.setDetail(null);
h.redraw();
return { before: before, after: after, cleared: centre() };
"""


@needs_chrome
def test_the_detail_patch_reaches_the_pixels_and_only_where_it_covers():
    """The shader claim, measured rather than reasoned: a fragment inside the detail box
    samples the detail texture, and one outside it carries on sampling the base. A patch
    in a colour the fixture's imagery does not contain is the only way to tell the two
    apart in a screenshot.

    Also that removing the patch puts the base back — the detail belongs to a camera and
    to a style, and a stale one left on screen would be imagery of somewhere else.
    """
    answer = _probe(_scene(tiles=True), _DETAIL_PIXELS)
    if answer.get("skipped"):
        pytest.skip("no WebGL backend in this browser")
    before, after, cleared = answer["before"], answer["after"], answer["cleared"]
    assert after[0] > 180 and after[2] > 180 and after[1] < 90, (
        f"the detail patch did not reach the middle of the view: {after}")
    assert before[1] > after[1], "the base imagery was already magenta"
    assert abs(cleared[1] - before[1]) < 25, (
        f"clearing the patch did not put the base image back: {cleared} vs {before}")


# ---------------------------------------------------------------- the airspace switch
#
# The layer is the airspace tool's, and this is the viewer's half of it: a flight map
# carries the airspace over its own ground behind a button, off until asked. Three claims
# that can only be made in a browser — that nothing is drawn or pointable until the button
# is pressed, that pressing it draws and names the zone, and that the same widget with no
# button on it keeps drawing the layer it exists for.

_TOGGLE = """
var h = window.__handle;
var panel = document.querySelector('.view3d-panel');
var button = panel.querySelector('[data-view3d-act="airspace-toggle"]');
var canvas = document.querySelector('canvas.view3d');
h.view.yaw = 0; h.view.pitch = 0.7; h.redraw();
// The middle of the test zone, in client pixels.
function overZone() {
  var m = h.toMetres(14.125, 49.125);
  var p = h.worldProject(m[0], m[1], h.groundAt(14.125, 49.125));
  var box = canvas.getBoundingClientRect();
  return { x: box.left + p[0] / canvas.width * box.width,
           y: box.top + p[1] / canvas.height * box.height };
}
function hover(at) {
  canvas.dispatchEvent(new PointerEvent('pointermove', {
    clientX: at.x, clientY: at.y, bubbles: true, pointerType: 'mouse', buttons: 0 }));
}
function label() {
  var tip = panel.querySelector('.view3d-asp');
  return tip && !tip.hidden ? tip.textContent : null;
}
"""


@needs_chrome
def test_the_flight_map_hides_the_airspace_until_it_is_asked_for():
    """The flight is the subject and the airspace is context, so the layer starts off —
    the same call the phase labels make. Off has to mean *off*: not drawn, and not
    answering the pointer either, or a reader would be naming zones they cannot see."""
    answer = _probe(_scene(airspace=True), _TOGGLE + """
    var at = overZone();
    hover(at);
    return { hasButton: !!button, pressed: button.getAttribute('aria-pressed'),
             found: !!h.airspaceAt(at.x, at.y), label: label() };
    """)
    assert answer["hasButton"], "a flight map with airspace in it carries no switch"
    assert answer["pressed"] == "false"
    assert not answer["found"], "the hidden layer still answered the pointer"
    assert answer["label"] is None


@needs_chrome
def test_pressing_it_draws_the_airspace_and_names_it_on_hover():
    """A translucent shape with no name says something is there and not what, and the
    flight report has none of the airspace page's legend, slider or tooltip around it."""
    answer = _probe(_scene(airspace=True), _TOGGLE + """
    button.click();
    // `draw` schedules an animation frame and this probe returns before one arrives —
    // on the page that is 16 ms and nobody sees it, in here it is the whole answer.
    h.redraw();
    var at = overZone();
    hover(at);
    var named = label();
    button.click();
    h.redraw();
    hover(at);
    return { pressed: button.getAttribute('aria-pressed'), named: named,
             after: label(), found: !!h.airspaceAt(at.x, at.y) };
    """)
    assert answer["named"] and answer["named"].startswith("TMA TEST"), answer
    assert "FL 95" in answer["named"], "the limits left the label"
    assert answer["pressed"] == "false", "the second press did not turn it back off"
    assert answer["after"] is None, "the label outlived the layer"
    assert not answer["found"]


@needs_chrome
def test_a_map_whose_subject_is_the_airspace_keeps_no_switch():
    """The airspace map hands the same widget the same rings without `airspaceToggle`,
    and there the layer is simply on. `a` must do nothing there — bound blindly it would
    turn the whole map off with nothing on screen saying it had."""
    scene = _scene(airspace=True)
    del scene["airspaceToggle"]
    answer = _probe(scene, _TOGGLE + """
    var at = overZone();
    canvas.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    h.redraw();
    return { hasButton: !!button, found: !!h.airspaceAt(at.x, at.y), label: label() };
    """)
    assert not answer["hasButton"], "the airspace map grew a redundant switch"
    assert answer["found"], "pressing 'a' turned the airspace map's own layer off"
    assert answer["label"] is None, "the widget's label fought the page's own tooltip"


_DETAIL_LADDER = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
var canvas = document.querySelector('canvas.view3d');
h.view.pitch = 0.9; h.view.yaw = 0; h.view.panX = 0; h.view.panY = 0;
var ladder = [];
[1, 2, 4, 8, 12, 16, 20, 28, 40].forEach(function (zoom) {
  h.view.zoom = zoom; h.redraw();
  var plan = h.detailPlan();
  // Apply what was planned, the way a completed fetch would, so the next step is judged
  // against what the reader can actually see.
  if (plan) h.setDetail(canvas, plan.box, plan.zoom);
  h.redraw();
  var state = h.detailState();
  ladder.push({ view: zoom, have: state && state.zoom ? state.zoom : 0 });
});
return ladder;
"""


@needs_chrome
def test_zooming_in_keeps_buying_sharpness():
    """It stopped buying any, over the range a reader actually works in.

    Halving the visible box buys exactly one tile level inside a fixed tile budget, so a
    `DETAIL_STEP` of two levels meant a **4x zoom of no improvement**. Measured on this
    fixture: a fetch at tile zoom 15 around view zoom 8, then nothing through 12, 16, 20
    and 28 — three and a half times closer, and the ground only getting blurrier — and
    the next fetch at 40, the ceiling. That is what "the tiles stopped updating with
    zoom" is, and it was a threshold rather than a fault.

    What this holds is the shape rather than the constants: sharpness never goes
    backwards, it improves several times across the range, and no plateau swallows a
    3x zoom.
    """
    ladder = _probe(_scene(tiles=True), _DETAIL_LADDER)
    have = [step["have"] for step in ladder]
    assert have == sorted(have), f"the detail got coarser as the view got closer: {have}"
    assert len(set(have)) >= 4, (
        f"only {len(set(have))} sharpness levels across a 40x zoom range: {ladder}")

    # The widest stretch of view zoom that bought nothing.
    worst, run_start = 1.0, ladder[0]
    for step in ladder[1:]:
        if step["have"] == run_start["have"]:
            worst = max(worst, step["view"] / run_start["view"])
        else:
            run_start = step
    assert worst <= 3.0, (
        f"the reader zooms {worst:.1f}x with no improvement at all: {ladder}")


# ---- the detail terrain ----------------------------------------------------------------
#
# The same idea as the detail imagery, for the ground: zoomed in and still, the view asks
# for a finer grid over what is on screen and draws it as a patch. Planning and drawing
# are checked here without a network; `test_terrain_remote.py` fetches a real one.

def _remote(dem):
    return {**dem, "remote": {"url": "http://127.0.0.1:9/{z}/{x}/{y}.png"}}


_TERRAIN_PLAN = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
function plan(zoom) {
  h.view.zoom = zoom; h.view.pitch = 0.9; h.view.yaw = 0;
  h.view.panX = 0; h.view.panY = 0;
  h.redraw();
  var p = h.terrainPlan();
  return p ? { spacing: p.spacing, tiles: p.tiles, zoom: p.remote.zoom,
               rows: p.rows, cols: p.cols } : null;
}
return { rest: plan(1), near: plan(8), nearer: plan(24) };
"""


@needs_chrome
def test_zooming_in_plans_finer_ground_and_resting_does_not():
    dem = _terrain()
    base_m = (dem["east"] - dem["west"]) * 111320 * math.cos(math.radians(49.125)) \
        / (dem["cols"] - 1)
    answer = _probe(_scene(terrain=_remote(dem), basemap=False), _TERRAIN_PLAN)
    assert answer["rest"] is None, "the resting view asked for ground it already has"
    for key in ("near", "nearer"):
        plan = answer[key]
        assert plan, f"zoomed in ({key}) and asked for no finer ground"
        assert plan["spacing"] <= base_m * 0.4, plan
        assert plan["tiles"] <= 16, "a terrain patch blew the tile budget"
        assert plan["rows"] * plan["cols"] <= 170 * 170
    assert answer["nearer"]["spacing"] < answer["near"]["spacing"]
    assert answer["nearer"]["zoom"] >= answer["near"]["zoom"]

    without = _probe(_scene(terrain=dem, basemap=False), _TERRAIN_PLAN)
    assert without["near"] is None, "a terrain with no tile source planned a fetch"


_TERRAIN_PATCH = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
var canvas = document.querySelector('canvas.view3d');
h.view.zoom = 6; h.view.pitch = 0.7; h.view.yaw = 0.3; h.view.vertical = 2;
h.view.panX = 0; h.view.panY = 0;
h.redraw();
var before = h.groundAt(14.125, 49.125);
// A patch whose ground is unmistakably not the base grid's: a flat 2 500 m table.
var rows = 41, cols = 41, z = [];
for (var i = 0; i < rows * cols; i++) z.push(2500);
h.setTerrainDetail({ west: 14.1, east: 14.15, south: 49.1, north: 49.15,
                     rows: rows, cols: cols, z: z, min: 2500, max: 2500, spacing: 90 });
var box = canvas.getBoundingClientRect();
var m = h.toMetres(14.125, 49.125);
var p = h.worldProject(m[0], m[1], h.groundAt(14.125, 49.125));
var sx = box.left + p[0] / canvas.width * box.width;
var sy = box.top + p[1] / canvas.height * box.height;
var picked = h.groundLonLat(sx, sy);
return { before: before, inside: h.groundAt(14.125, 49.125),
         outside: h.groundAt(14.2, 49.2),
         pickErr: Math.hypot((picked[0] - 14.125) * 73000, (picked[1] - 49.125) * 111000),
         state: h.terrainState(), gl: h.gl() };
"""


@needs_chrome
def test_a_terrain_patch_is_the_ground_where_it_lies():
    """Inside the patch, the ground is the patch's: `groundAt`, and so every pick and
    every turnpoint height, reads it — and the renderer has it in its buffers. Outside,
    nothing changed."""
    dem = _terrain()
    answer = _probe(_scene(terrain=_remote(dem), basemap=False), _TERRAIN_PATCH)
    assert answer["inside"] == pytest.approx(2500)
    assert answer["before"] != pytest.approx(2500)
    # The base fixture's own height at 14.2, 49.2, bilinear on its grid.
    assert 200 <= answer["outside"] <= 1400
    assert answer["state"]["rows"] == 41
    assert answer["pickErr"] < 5, (
        f"a pick on the patch landed {answer['pickErr']:.0f} m from the point it was aimed at")
    assert answer["gl"], "no WebGL backend, so there is nothing to draw a patch with"
    assert answer["gl"]["patchCells"] == 40 * 40, answer["gl"]


_PATCH_SHADING = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
return new Promise(function (resolve) {
  setTimeout(function () {
    function grab() {
      var image = h.shadedBasemap();
      var copy = document.createElement('canvas');
      copy.width = image.width; copy.height = image.height;
      var cx = copy.getContext('2d');
      cx.drawImage(image, 0, 0);
      return { data: cx.getImageData(0, 0, copy.width, copy.height).data,
               w: copy.width, h: copy.height };
    }
    // The fixture image covers 13.9-14.35 E, 48.9-49.35 N.
    function pixel(shot, lon, lat) {
      var x = Math.floor((lon - 13.9) / 0.45 * shot.w);
      var y = Math.floor((49.35 - lat) / 0.45 * shot.h);
      var k = (y * shot.w + x) * 4;
      return [shot.data[k], shot.data[k + 1], shot.data[k + 2]];
    }
    var before = grab();
    // Steep east-west ridges every 300 m, where the base grid is smooth at this scale.
    var rows = 81, cols = 81, z = [];
    for (var r = 0; r < rows; r++) for (var c = 0; c < cols; c++) {
      z.push(800 + 250 * Math.sin(r / 4));
    }
    h.setTerrainDetail({ west: 14.1, east: 14.15, south: 49.1, north: 49.15,
                         rows: rows, cols: cols, z: z, min: 550, max: 1050, spacing: 70 });
    var after = grab();
    var inside = 0, outside = 0;
    for (var i = 0; i < 40; i++) {
      var a = pixel(before, 14.105 + i * 0.001, 49.105 + i * 0.001);
      var b = pixel(after, 14.105 + i * 0.001, 49.105 + i * 0.001);
      inside += Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) + Math.abs(a[2] - b[2]);
      var c = pixel(before, 14.2, 49.0 + i * 0.002), d = pixel(after, 14.2, 49.0 + i * 0.002);
      outside += Math.abs(c[0] - d[0]) + Math.abs(c[1] - d[1]) + Math.abs(c[2] - d[2]);
    }
    resolve({ inside: inside, outside: outside });
  }, 800);
});
"""


@needs_chrome
def test_finer_ground_reshades_the_imagery_where_it_lies():
    """The hillshade is baked into the draped image from the base grid. When finer
    ground lands, the light on the image has to come from it — otherwise the new ridges
    stand up in the geometry wearing the old ridges' shadows. Outside the patch the
    image is left exactly as it was."""
    answer = _probe(_scene(terrain=_remote(_terrain())), _PATCH_SHADING)
    assert answer["inside"] > 200, "the finer ground left the image's shading unchanged"
    assert answer["outside"] == 0, "shading changed outside the patch"


_SHADED_WITHOUT_SUN = """
var h = window.__view3dAll[Object.keys(window.__view3dAll)[0]];
return new Promise(function (resolve) {
  setTimeout(function () {
    var data = JSON.parse(document.querySelector('.view3d-data').textContent);
    var raw = new Image();
    raw.onload = function () {
      function pixels(image) {
        var c = document.createElement('canvas');
        c.width = 256; c.height = 256;
        var x = c.getContext('2d');
        x.drawImage(image, 0, 0, 256, 256);
        return x.getImageData(0, 0, 256, 256).data;
      }
      var a = pixels(raw), b = pixels(h.shadedBasemap()), diff = 0;
      for (var i = 0; i < a.length; i += 4) diff += Math.abs(a[i] - b[i]);
      resolve({ diff: diff / (a.length / 4) });
    };
    raw.src = data.basemaps.satellite.uri;
  }, 800);
});
"""


@needs_chrome
def test_the_imagery_is_hillshaded_without_a_sun_track():
    """The lit range was measured before the light was declared, so on a page with no
    sun track — the airspace map, the planner — every slope was NaN and the draped image
    went out with no hillshade at all. The report hid it by relighting from its sun."""
    answer = _probe(_scene(), _SHADED_WITHOUT_SUN)
    assert answer["diff"] > 2, "the draped image is the raw imagery: nothing was shaded"

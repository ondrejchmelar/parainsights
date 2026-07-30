"""An interactive 3D view that survives a content-security policy.

`render_map.py` gives the better 3D map — real basemap, real tiles, deck.gl — but it
needs the network at view time, so it cannot be embedded in a published page. This
renders the same idea with nothing but a canvas and about a hundred lines of
JavaScript: the DEM is fetched once at build time and travels inside the document.

The heightfield is drawn back-to-front by walking the grid from the farthest corner,
which is exact for a regular grid seen from outside it — no depth sort, no z-buffer.
"""

from __future__ import annotations

import json

import numpy as np

from .analysis import Analysis, Phase
from .charts import decimate
from .render_map import RAMP_RGB, climb_rgb

TRACK_TOLERANCE = 4.0  # metres of horizontal detail kept in the 3D track


def _colour_index(value: float) -> int:
    """Index into the shared climb ramp.

    An index costs three characters in the payload where an [r,g,b] triple costs
    fifteen, and a long flight has thousands of points.
    """
    for index, (threshold, _) in enumerate(RAMP_RGB):
        if value < threshold:
            return index
    return len(RAMP_RGB) - 1


def data(analysis: Analysis, terrain, *, tolerance: float | None = None,
         basemap=None) -> dict:
    """Terrain grid, track and climbs, in the compact form the renderer wants."""
    flight = analysis.flight
    series = analysis.series
    altitude = flight.alt_gps if np.any(flight.alt_gps) else series.alt

    tolerance = TRACK_TOLERANCE if tolerance is None else tolerance
    keep = np.union1d(
        decimate(series.x, series.y, tolerance),
        decimate(series.t, series.alt, tolerance * 0.75),
    )
    track = {
        # 4 decimals is ~11 m — below what a pixel represents at these zooms.
        "lon": [round(float(flight.lon[i]), 4) for i in keep],
        "lat": [round(float(flight.lat[i]), 4) for i in keep],
        "alt": [int(altitude[i]) for i in keep],
        "c": [_colour_index(float(series.climb[i])) for i in keep],
    }

    climbs = []
    number = 0
    for segment in analysis.segments:
        if segment.phase not in (Phase.THERMAL, Phase.TOW):
            continue
        middle = (segment.start + segment.stop) // 2
        if segment.phase is Phase.TOW:
            label = "T"
        else:
            number += 1
            label = str(number)
        climbs.append(
            {
                "label": label,
                "lon": round(float(flight.lon[middle]), 5),
                "lat": round(float(flight.lat[middle]), 5),
                "alt": int(altitude[middle]),
                "tow": segment.phase is Phase.TOW,
            }
        )

    # Cursor positions for the shared hover, at the same sample indices the charts use.
    return {
        "terrain": terrain.to_dict(),
        "trackTop": int(max(track["alt"])) if track["alt"] else 0,
        "track": track,
        "climbs": climbs,
        "palette": [list(colour) for _, colour in RAMP_RGB],
        "basemap": basemap.to_dict() if basemap is not None else None,
        "landing": {
            "lon": round(float(flight.lon[-1]), 5),
            "lat": round(float(flight.lat[-1]), 5),
            "alt": int(altitude[-1]),
        },
    }


def cursor_track(analysis: Analysis, sample) -> dict:
    """Positions for the hover cursor, aligned with the chart sample indices."""
    flight = analysis.flight
    altitude = flight.alt_gps if np.any(flight.alt_gps) else analysis.series.alt
    return {
        "lon": [round(float(flight.lon[i]), 5) for i in sample],
        "lat": [round(float(flight.lat[i]), 5) for i in sample],
        "alt": [int(altitude[i]) for i in sample],
    }


def panel(payload: dict, uid: str) -> str:
    """The canvas, its controls, and the embedded data."""
    return f"""
    <div class="panel view3d-panel">
      <canvas class="view3d" id="view3d-{uid}" width="1080" height="620"
              aria-label="Interactive three-dimensional view of the flight over terrain">
      </canvas>
      <div class="view3d-controls">
        <button type="button" data-view3d-act="rotate-left" title="Rotate left">&#8630;</button>
        <button type="button" data-view3d-act="rotate-right" title="Rotate right">&#8631;</button>
        <button type="button" data-view3d-act="tilt-up" title="Tilt up">&#8593;</button>
        <button type="button" data-view3d-act="tilt-down" title="Tilt down">&#8595;</button>
        <button type="button" data-view3d-act="zoom-in" title="Zoom in">+</button>
        <button type="button" data-view3d-act="zoom-out" title="Zoom out">&minus;</button>
        <button type="button" data-view3d-act="basemap" class="is-on"
                title="Show map with place names">Map</button>
        <button type="button" data-view3d-act="exaggerate" title="Vertical exaggeration">
          &#215;1 height</button>
        <button type="button" data-view3d-act="reset">Reset view</button>
      </div>
      <script type="application/json" class="view3d-data">{json.dumps(payload)}</script>
    </div>"""


STYLE = """
.view3d-panel { position: relative; padding: 0; overflow: hidden; }
canvas.view3d { display: block; width: 100%; height: auto; cursor: grab;
  background: linear-gradient(180deg, var(--panel-2) 0%, var(--panel) 62%); touch-action: none; }
canvas.view3d.is-dragging { cursor: grabbing; }
.view3d-controls { position: absolute; right: 10px; bottom: 10px; display: flex; gap: 5px;
  flex-wrap: wrap; }
.view3d-controls button {
  font: inherit;
  font-size: 11.5px;
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 4px 9px;
  border: 1px solid var(--rule-strong);
  border-radius: 2px;
  background: var(--panel);
  color: var(--ink-2);
  cursor: pointer;
}
.view3d-controls button:hover { color: var(--ink); background: var(--panel-2); }
.view3d-controls button.is-on { background: var(--climb); border-color: var(--climb);
  color: var(--paper); }
"""


SCRIPT = """
function initView3d(root, cursorTrack) {
  var canvas = root.querySelector('canvas.view3d');
  var payload = root.querySelector('.view3d-data');
  if (!canvas || !payload) return null;
  var scene = JSON.parse(payload.textContent);
  var dem = scene.terrain;
  var ctx = canvas.getContext('2d');
  var W = canvas.width, H = canvas.height;

  // Local metric frame about the DEM centre, so rotation is about the middle of
  // the terrain rather than the corner of a bounding box.
  var lat0 = (dem.north + dem.south) / 2;
  var lon0 = (dem.east + dem.west) / 2;
  var mPerDegLat = 110540;
  var mPerDegLon = 111320 * Math.cos(lat0 * Math.PI / 180);
  function toMetres(lon, lat) {
    return [(lon - lon0) * mPerDegLon, (lat - lat0) * mPerDegLat];
  }

  var spanX = (dem.east - dem.west) * mPerDegLon;
  var spanY = (dem.north - dem.south) * mPerDegLat;

  // True scale by default: the whole point of putting the flight over a DEM is that
  // heights can be compared with the ground, and an exaggerated vertical breaks that.
  // The ×2 button is there for when the relief needs help.
  var baseVertical = 1;
  // panX/panY are screen-space offsets applied after the fit, which is what lets the
  // view be dragged off centre — the fit alone always recentres, so without these the
  // camera was welded to the middle of the flight.
  var view = { yaw: -0.42, pitch: 0.46, zoom: 1, vertical: baseVertical, map: true,
               panX: 0, panY: 0 };

  // The basemap carries the place names, which is the whole reason it is here: a
  // hillshade shows the shape of a ridge but never tells you which village it is above.
  var basemap = null;
  var cellColour = null;      // one averaged map colour per texture cell
  var cellCols = 0, cellRows = 0;

  function texStep() {
    // Texturing costs a drawImage per cell, so drape on a coarser mesh than shading.
    return {
      c: Math.max(Math.round(cols / 70), 1),
      r: Math.max(Math.round(rows / 26), 1)
    };
  }

  // A per-cell average of the map, taken once by letting the browser downscale the
  // image. It is painted under each textured cell so the small gaps where a non-planar
  // cell disagrees with its affine fit show ground colour rather than sky.
  function sampleCellColours() {
    try {
      var steps = texStep();
      cellCols = Math.max(Math.round(cols / steps.c), 1);
      cellRows = Math.max(Math.round(rows / steps.r), 1);
      var off = document.createElement('canvas');
      off.width = cellCols;
      off.height = cellRows;
      var octx = off.getContext('2d');
      octx.drawImage(basemap, 0, 0, cellCols, cellRows);
      cellColour = octx.getImageData(0, 0, cellCols, cellRows).data;
    } catch (e) {
      cellColour = null;
    }
  }

  if (scene.basemap) {
    basemap = new Image();
    basemap.onload = function () { sampleCellColours(); draw(); };
    basemap.src = scene.basemap.uri;
  }

  function world(x, y, z) {
    var cy = Math.cos(view.yaw), sy = Math.sin(view.yaw);
    var wx = x * cy - y * sy;
    var wy = x * sy + y * cy;
    var wz = (z - dem.min) * view.vertical;
    var cp = Math.cos(view.pitch), sp = Math.sin(view.pitch);
    // Screen y grows downward, so the northward axis has to be negated: without it
    // the far side of the terrain lands at the bottom of the canvas, which is the
    // same picture as looking from the north — east and west come out swapped.
    return [wx, -wy * sp - wz * cp, wy];
  }

  // Fit is recomputed per frame because yaw and pitch change the outline. It is
  // deliberately computed at ×1 regardless of the current exaggeration: fitting the
  // exaggerated outline zooms out by exactly the factor the user just asked for, which
  // is why the ×2 button appeared to do nothing at all.
  var fit = { scale: 1, dx: 0, dy: 0 };
  function refit() {
    var wanted = view.vertical;
    view.vertical = 1;
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    function consider(p) {
      if (p[0] < minX) minX = p[0];
      if (p[0] > maxX) maxX = p[0];
      if (p[1] < minY) minY = p[1];
      if (p[1] > maxY) maxY = p[1];
    }
    // Sampling the grid is enough for bounds and keeps this cheap.
    for (var r = 0; r < rows; r += 3) {
      for (var c = 0; c < cols; c += 6) {
        var i = r * cols + c;
        consider(world(nodeX[i], nodeY[i], dem.z[i]));
      }
    }
    var t = scene.track;
    for (var k = 0; k < t.lon.length; k += 7) {
      var m = toMetres(t.lon[k], t.lat[k]);
      consider(world(m[0], m[1], t.alt[k]));
    }
    var scale = Math.min(W * 0.95 / Math.max(maxX - minX, 1), H * 0.9 / Math.max(maxY - minY, 1));
    view.vertical = wanted;
    fit.scale = scale * view.zoom;
    fit.dx = W / 2 - (minX + maxX) / 2 * fit.scale;
    // Keep the *ground* centred rather than the whole scene: as the exaggeration grows
    // the flight should climb up the canvas, not push the terrain off the bottom.
    fit.dy = H * 0.66 - (minY + maxY) / 2 * fit.scale;
  }

  function project(x, y, z) {
    var w = world(x, y, z);
    return [fit.dx + w[0] * fit.scale + view.panX, fit.dy + w[1] * fit.scale + view.panY];
  }

  // Grid node positions in metres, computed once; only the projection changes.
  var cols = dem.cols, rows = dem.rows;
  var nodeX = new Float64Array(rows * cols);
  var nodeY = new Float64Array(rows * cols);
  for (var r = 0; r < rows; r++) {
    var lat = dem.north - (dem.north - dem.south) * r / (rows - 1);
    for (var c = 0; c < cols; c++) {
      var lon = dem.west + (dem.east - dem.west) * c / (cols - 1);
      var m = toMetres(lon, lat);
      nodeX[r * cols + c] = m[0];
      nodeY[r * cols + c] = m[1];
    }
  }

  function shadeFactor(r, c) {
    var i = r * cols + c;
    var here = dem.z[i];
    var right = dem.z[i + (c + 1 < cols ? 1 : 0)];
    var below = dem.z[i + (r + 1 < rows ? cols : 0)];
    var cellX = spanX / (cols - 1), cellY = spanY / (rows - 1);
    var dzdx = (right - here) / cellX, dzdy = (below - here) / cellY;
    var nx = -dzdx, ny = -dzdy, nz = 1;
    var len = Math.sqrt(nx * nx + ny * ny + nz * nz);
    var light = (nx * -0.55 + ny * 0.55 + nz * 0.63) / len;
    return Math.max(0.25, Math.min(1.15, 0.55 + light * 0.65));
  }

  function shade(r, c) {
    // Slope shading from the two in-grid gradients, lit from the north-west.
    var i = r * cols + c;
    var here = dem.z[i];
    var right = dem.z[i + (c + 1 < cols ? 1 : 0)];
    var below = dem.z[i + (r + 1 < rows ? cols : 0)];
    var cellX = spanX / (cols - 1), cellY = spanY / (rows - 1);
    var dzdx = (right - here) / cellX, dzdy = (below - here) / cellY;
    var nx = -dzdx, ny = -dzdy, nz = 1;
    var len = Math.sqrt(nx * nx + ny * ny + nz * nz);
    var light = (nx * -0.55 + ny * 0.55 + nz * 0.63) / len;
    var lit = Math.max(0.25, Math.min(1.15, 0.55 + light * 0.65));
    // Elevation tint: low ground greener, high ground paler and greyer.
    var t = Math.min(1, Math.max(0, (here - dem.min) / Math.max(dem.max - dem.min, 1)));
    var rr = (120 + t * 95) * lit;
    var gg = (135 + t * 80) * lit;
    var bb = (105 + t * 95) * lit;
    return 'rgb(' + (rr | 0) + ',' + (gg | 0) + ',' + (bb | 0) + ')';
  }

  // The map has to follow the relief, not lie flat under it: at these vertical
  // exaggerations a flat floor and an exaggerated mesh separate visibly. Drawing it in
  // north-south bands, each affine-fitted to that band's mean ground height, keeps the
  // names readable and the geometry honest for a dozen drawImage calls a frame.
  var STRIPS = 10;
  // Banding exists to follow relief. Where there is little relief it only buys seams,
  // so flat ground gets one exact affine fit at the mean elevation instead.
  var BAND_THRESHOLD = 500;  // metres of terrain range

  // Ground elevation anywhere in the box, bilinear on the DEM grid. Everything that
  // belongs on the ground — the track's shadow, the cursor's drop line — needs this:
  // drawing it on a flat plane at the minimum elevation makes it slide against the
  // terrain as the view rotates, because it is simply not where the ground is.
  function groundAt(lon, lat) {
    var gx = (lon - dem.west) / (dem.east - dem.west) * (cols - 1);
    var gy = (dem.north - lat) / (dem.north - dem.south) * (rows - 1);
    gx = Math.max(0, Math.min(cols - 1, gx));
    gy = Math.max(0, Math.min(rows - 1, gy));
    var x0 = Math.floor(gx), y0 = Math.floor(gy);
    var x1 = Math.min(x0 + 1, cols - 1), y1 = Math.min(y0 + 1, rows - 1);
    var fx = gx - x0, fy = gy - y0;
    var top = dem.z[y0 * cols + x0] * (1 - fx) + dem.z[y0 * cols + x1] * fx;
    var bottom = dem.z[y1 * cols + x0] * (1 - fx) + dem.z[y1 * cols + x1] * fx;
    return top * (1 - fy) + bottom * fy;
  }

  // Source rectangle in basemap pixels for a grid cell, so the map can be drawn cell
  // by cell and therefore sits *on* the surface rather than under it.
  function sourceRect(r, c, rStep, cStep) {
    var bm = scene.basemap;
    var iw = basemap.naturalWidth, ih = basemap.naturalHeight;
    var lonW = dem.west + (dem.east - dem.west) * c / (cols - 1);
    var lonE = dem.west + (dem.east - dem.west) * Math.min(c + cStep, cols - 1) / (cols - 1);
    var latN = dem.north - (dem.north - dem.south) * r / (rows - 1);
    var latS = dem.north - (dem.north - dem.south) * Math.min(r + rStep, rows - 1) / (rows - 1);
    var sx = (lonW - bm.west) / (bm.east - bm.west) * iw;
    var ex = (lonE - bm.west) / (bm.east - bm.west) * iw;
    var sy = (bm.north - latN) / (bm.north - bm.south) * ih;
    var ey = (bm.north - latS) / (bm.north - bm.south) * ih;
    return [sx, sy, Math.max(ex - sx, 0.5), Math.max(ey - sy, 0.5)];
  }

  function drawTerrain(withMap) {
    // Paint far to near. Depth is the rotated northward coordinate
    // wy = x·sin(yaw) + y·cos(yaw); x grows with column and y *falls* with row, so
    // the sign of each contribution gives the iteration direction directly.
    var cy = Math.cos(view.yaw), sy = Math.sin(view.yaw);
    var colsFirst = sy > 0 ? -1 : 1;   // decreasing wy along columns
    var rowsFirst = cy > 0 ? 1 : -1;   // dwy/drow = -cos(yaw)
    var steps = texStep();
    var cStep = withMap ? steps.c : 1;
    var rStep = withMap ? steps.r : 1;
    var rStart = rowsFirst > 0 ? 0 : rows - 1 - rStep;
    var cStart = colsFirst > 0 ? 0 : cols - 1 - cStep;

    for (var r = rStart; r >= 0 && r <= rows - 1 - rStep; r += rowsFirst * rStep) {
      for (var c = cStart; c >= 0 && c <= cols - 1 - cStep; c += colsFirst * cStep) {
        var i00 = r * cols + c;
        var i01 = i00 + cStep;
        var i10 = i00 + cols * rStep;
        var i11 = i10 + cStep;
        var p00 = project(nodeX[i00], nodeY[i00], dem.z[i00]);
        var p01 = project(nodeX[i01], nodeY[i01], dem.z[i01]);
        var p11 = project(nodeX[i11], nodeY[i11], dem.z[i11]);
        var p10 = project(nodeX[i10], nodeY[i10], dem.z[i10]);

        if (withMap) {
          var lit0 = shadeFactor(r, c);
          if (cellColour) {
            // Opaque base in the cell's average colour, on the true four corners.
            var ci = (Math.min(Math.floor(r / rStep), cellRows - 1) * cellCols +
                      Math.min(Math.floor(c / cStep), cellCols - 1)) * 4;
            ctx.beginPath();
            ctx.moveTo(p00[0], p00[1]);
            ctx.lineTo(p01[0], p01[1]);
            ctx.lineTo(p11[0], p11[1]);
            ctx.lineTo(p10[0], p10[1]);
            ctx.closePath();
            ctx.fillStyle = 'rgb(' + cellColour[ci] + ',' + cellColour[ci + 1] + ',' +
              cellColour[ci + 2] + ')';
            ctx.strokeStyle = ctx.fillStyle;
            ctx.lineWidth = 1;
            ctx.fill();
            ctx.stroke();
          }
          var rect = sourceRect(r, c, rStep, cStep);
          // Map the cell's own slice of the image onto the cell's parallelogram. No
          // clip and no save/restore: the drawn area *is* the cell, and a small
          // overdraw closes the hairline seams between neighbours.
          ctx.setTransform(
            p01[0] - p00[0], p01[1] - p00[1],
            p10[0] - p00[0], p10[1] - p00[1],
            p00[0], p00[1]
          );
          ctx.drawImage(basemap, rect[0], rect[1], rect[2], rect[3], 0, 0, 1.12, 1.12);
          // Relief on top, so the place names stay readable underneath.
          var strength = Math.min(Math.abs(lit0 - 0.86) * 0.5, 0.24);
          ctx.fillStyle = (lit0 >= 0.86 ? 'rgba(255,255,255,' : 'rgba(24,30,38,') +
            strength.toFixed(3) + ')';
          ctx.fillRect(0, 0, 1.12, 1.12);
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          continue;
        }

        ctx.beginPath();
        ctx.moveTo(p00[0], p00[1]);
        ctx.lineTo(p01[0], p01[1]);
        ctx.lineTo(p11[0], p11[1]);
        ctx.lineTo(p10[0], p10[1]);
        ctx.closePath();
        ctx.fillStyle = shade(r, c);
        // Stroke with the same colour: hairline gaps between quads otherwise show
        // the sky through the mesh.
        ctx.strokeStyle = ctx.fillStyle;
        ctx.lineWidth = 1;
        ctx.fill();
        ctx.stroke();
      }
    }
  }

  function drawTrack() {
    var t = scene.track;
    var n = t.lon.length;
    var pts = new Array(n);
    for (var i = 0; i < n; i++) {
      var m = toMetres(t.lon[i], t.lat[i]);
      pts[i] = project(m[0], m[1], t.alt[i]);
    }
    // Shadow drawn on the ground surface itself, so it stays under the track at every
    // angle instead of sliding about on a flat plane.
    ctx.strokeStyle = 'rgba(20,24,28,0.34)';
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    for (var j = 0; j < n; j++) {
      var mg = toMetres(t.lon[j], t.lat[j]);
      var g = project(mg[0], mg[1], groundAt(t.lon[j], t.lat[j]));
      if (j === 0) ctx.moveTo(g[0], g[1]); else ctx.lineTo(g[0], g[1]);
    }
    ctx.stroke();

    ctx.lineWidth = 2.6;
    ctx.lineCap = 'round';
    for (var k = 1; k < n; k++) {
      var col = scene.palette[t.c[k]];
      ctx.strokeStyle = 'rgb(' + col[0] + ',' + col[1] + ',' + col[2] + ')';
      ctx.beginPath();
      ctx.moveTo(pts[k - 1][0], pts[k - 1][1]);
      ctx.lineTo(pts[k][0], pts[k][1]);
      ctx.stroke();
    }

    scene.climbs.forEach(function (climb) {
      var m = toMetres(climb.lon, climb.lat);
      var p = project(m[0], m[1], climb.alt);
      ctx.beginPath();
      ctx.arc(p[0], p[1], 8.5, 0, Math.PI * 2);
      ctx.fillStyle = climb.tow ? 'rgba(27,175,122,0.92)' : 'rgba(235,104,52,0.92)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.85)';
      ctx.lineWidth = 1.4;
      ctx.stroke();
      ctx.fillStyle = '#fff';
      ctx.font = '600 11px ui-sans-serif, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(climb.label, p[0], p[1] + 0.5);
    });
  }

  var cursorIndex = null;
  function drawCursor() {
    if (cursorIndex === null || !cursorTrack) return;
    var i = Math.min(cursorIndex, cursorTrack.lon.length - 1);
    var m = toMetres(cursorTrack.lon[i], cursorTrack.lat[i]);
    var p = project(m[0], m[1], cursorTrack.alt[i]);
    var g = project(m[0], m[1], groundAt(cursorTrack.lon[i], cursorTrack.lat[i]));
    ctx.strokeStyle = 'rgba(255,255,255,0.7)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(p[0], p[1]);
    ctx.lineTo(g[0], g[1]);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(p[0], p[1], 5.5, 0, Math.PI * 2);
    ctx.fillStyle = '#fff';
    ctx.fill();
    ctx.strokeStyle = '#14171c';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  var pending = false;
  function draw() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () {
      pending = false;
      ctx.clearRect(0, 0, W, H);
      refit();
      var mapped = view.map && basemap && basemap.complete && basemap.naturalWidth > 0;
      drawTerrain(mapped);
      drawTrack();
      drawCursor();
    });
  }

  // Input model borrowed from Google Earth, because that is what pilots already know:
  //   left-drag            pan
  //   right-drag, or ctrl/shift/alt + left-drag, or middle-drag   rotate and tilt
  //   wheel                zoom towards the pointer
  //   one finger           pan
  //   two fingers          pinch to zoom, twist to rotate
  var pointers = new Map();
  var gesture = null;   // 'pan' | 'orbit'
  var pinch = null;

  function points() { return Array.from(pointers.values()); }

  function twoFingerState() {
    var p = points();
    return {
      distance: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y),
      angle: Math.atan2(p[1].y - p[0].y, p[1].x - p[0].x),
      cx: (p[0].x + p[1].x) / 2,
      cy: (p[0].y + p[1].y) / 2
    };
  }

  function orbitModifier(event) {
    return event.button === 2 || event.button === 1 ||
           event.ctrlKey || event.shiftKey || event.altKey || event.metaKey;
  }

  // Keep the point under the cursor fixed while zooming, the way every map does.
  function zoomAt(factor, clientX, clientY) {
    var box = canvas.getBoundingClientRect();
    var vb = canvas.viewBox ? null : null;
    var sx = (clientX - box.left) / box.width * W;
    var sy = (clientY - box.top) / box.height * H;
    var before = view.zoom;
    view.zoom = Math.max(0.3, Math.min(12, view.zoom * factor));
    var ratio = view.zoom / before;
    // The fit scales with zoom, so anchoring means moving the pan by the same ratio
    // about the cursor.
    view.panX = sx - (sx - view.panX) * ratio;
    view.panY = sy - (sy - view.panY) * ratio;
  }

  canvas.addEventListener('contextmenu', function (event) { event.preventDefault(); });

  canvas.addEventListener('pointerdown', function (event) {
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 2) {
      gesture = 'pinch';
      pinch = twoFingerState();
    } else if (pointers.size === 1) {
      gesture = orbitModifier(event) ? 'orbit' : 'pan';
    }
    canvas.classList.add('is-dragging');
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener('pointermove', function (event) {
    var previous = pointers.get(event.pointerId);
    if (!previous) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    var box = canvas.getBoundingClientRect();
    var toCanvas = W / box.width;   // CSS pixels to canvas units

    if (pointers.size >= 2) {
      var now = twoFingerState();
      if (pinch) {
        if (pinch.distance > 0 && now.distance > 0) {
          zoomAt(now.distance / pinch.distance, now.cx, now.cy);
        }
        // Twist rotates, which is the gesture Earth uses for heading on touch.
        view.yaw += (now.angle - pinch.angle) * 0.9;
        view.panX += (now.cx - pinch.cx) * toCanvas;
        view.panY += (now.cy - pinch.cy) * toCanvas;
      }
      pinch = now;
      draw();
      return;
    }

    var dx = (event.clientX - previous.x) * toCanvas;
    var dy = (event.clientY - previous.y) * toCanvas;
    if (gesture === 'orbit') {
      view.yaw += dx * 0.005;
      view.pitch = Math.max(0.06, Math.min(1.45, view.pitch - dy * 0.004));
    } else {
      view.panX += dx;
      view.panY += dy;
    }
    draw();
  });

  function endPointer(event) {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!pointers.size) { gesture = null; canvas.classList.remove('is-dragging'); }
  }
  canvas.addEventListener('pointerup', endPointer);
  canvas.addEventListener('pointercancel', endPointer);
  canvas.addEventListener('pointerleave', endPointer);

  canvas.addEventListener('wheel', function (event) {
    event.preventDefault();
    zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX, event.clientY);
    draw();
  }, { passive: false });

  function box() {
    var r = canvas.getBoundingClientRect();
    return { cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
  }

  root.querySelectorAll('[data-view3d-act]').forEach(function (button) {
    button.addEventListener('click', function () {
      var act = button.dataset.view3dAct;
      if (act === 'rotate-left') view.yaw -= 0.35;
      else if (act === 'rotate-right') view.yaw += 0.35;
      else if (act === 'tilt-up') view.pitch = Math.min(1.45, view.pitch + 0.15);
      else if (act === 'tilt-down') view.pitch = Math.max(0.06, view.pitch - 0.15);
      else if (act === 'zoom-in') zoomAt(1.25, box().cx, box().cy);
      else if (act === 'zoom-out') zoomAt(1 / 1.25, box().cx, box().cy);
      else if (act === 'exaggerate') {
        // True scale is the default because it is the only setting you can read height
        // above ground from. But a 90 km flight through 2 km of air is 2 % of its own
        // width, so the multiples are here for when the shape of the climbs matters
        // more than their absolute height.
        var ladder = [1, 2, 4];
        var at = ladder.indexOf(view.vertical);
        var next = ladder[(at + 1) % ladder.length];
        view.vertical = next;
        button.classList.toggle('is-on', next !== 1);
        button.innerHTML = '&#215;' + next + ' height';
      } else if (act === 'basemap') {
        view.map = !view.map;
        button.classList.toggle('is-on', view.map);
      } else if (act === 'reset') {
        view.yaw = -0.42; view.pitch = 0.46; view.zoom = 1; view.vertical = baseVertical;
        view.panX = 0; view.panY = 0;
        view.map = true;
        root.querySelectorAll('[data-view3d-act="basemap"]').forEach(function (b) {
          b.classList.add('is-on');
        });
        root.querySelectorAll('[data-view3d-act="exaggerate"]').forEach(function (b) {
          b.classList.remove('is-on');
          b.innerHTML = '&#215;1 height';
        });
      }
      draw();
    });
  });

  draw();
  var handle = {
    setCursor: function (index) { cursorIndex = index; draw(); },
    clearCursor: function () { cursorIndex = null; draw(); },
    // Exposed for tests: driving the camera from a headless browser is the only way to
    // check that a gesture does what it claims.
    view: view
  };
  window.__view3d = handle;
  return handle;
}
"""

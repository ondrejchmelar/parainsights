/* What the sun was doing to the ground: `tracklog_viewer/insolation.py`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * Slope and aspect from the DEM's gradient, the sun's incidence on each face, and the
 * ridge-or-thermal call per climb — which needs three things to agree (a steep face, the
 * climb staying on it, and a track that beats rather than circles) and is not vetoed by
 * the wind. Nothing here claims a cause.
 */
(function (TV) {
  'use strict';
  var np = TV.np, geo = TV.geo, sun = TV.sun, T = TV.terrain, M = TV.metrics, R = np.pyRound;

  var NEIGHBOURHOOD = 1200.0, MIN_SLOPE = 5.0;
  var RIDGE_CLEARANCE = 250.0, RIDGE_SLOPE = 12.0, RIDGE_TURN_RATE = 0.5, RIDGE_TOLERANCE = 60.0;

  // np.gradient over a 2D grid: (d/drow, d/dcol), central inside, one-sided at the edges.
  function grad2(grid) {
    var rows = grid.rows, cols = grid.cols, dr = new Float64Array(rows * cols), dc = new Float64Array(rows * cols);
    var z = function (r, c) { return T.cell(grid, r, c); };
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var k = r * cols + c;
        dr[k] = r === 0 ? z(1, c) - z(0, c) : r === rows - 1 ? z(r, c) - z(r - 1, c) : (z(r + 1, c) - z(r - 1, c)) / 2.0;
        dc[k] = c === 0 ? z(r, 1) - z(r, 0) : c === cols - 1 ? z(r, c) - z(r, c - 1) : (z(r, c + 1) - z(r, c - 1)) / 2.0;
      }
    }
    return { dr: dr, dc: dc };
  }

  // Ground slope in metres per metre, east and north (row 0 is north, so negated).
  function gradients(grid) {
    var rows = grid.rows, cols = grid.cols;
    if (grid.__grad) return grid.__grad;
    if (rows < 2 || cols < 2) return { gx: new Float64Array(rows * cols), gy: new Float64Array(rows * cols) };
    var midLat = (grid.north + grid.south) / 2.0;
    var dy = geo.R * ((grid.north - grid.south) * np.DEG) / (rows - 1);
    var dx = geo.R * ((grid.east - grid.west) * np.DEG) * Math.cos(midLat * np.DEG) / (cols - 1);
    var g = grad2(grid), gx = new Float64Array(rows * cols), gy = new Float64Array(rows * cols);
    for (var k = 0; k < rows * cols; k++) {
      gx[k] = g.dc[k] / Math.max(dx, 1e-6);
      gy[k] = -g.dr[k] / Math.max(dy, 1e-6);
    }
    Object.defineProperty(grid, '__grad', { value: { gx: gx, gy: gy }, enumerable: false });
    return grid.__grad;
  }

  function sunVector(p) {
    var az = p.azimuth * np.DEG, el = p.elevation * np.DEG;
    return [Math.cos(el) * Math.sin(az), Math.cos(el) * Math.cos(az), Math.sin(el)];
  }

  // Relative insolation of every cell, 0..1, for one solar position.
  function litGrid(grid, position) {
    var g = gradients(grid), s = sunVector(position), n = grid.rows * grid.cols, out = new Float64Array(n);
    if (position.elevation <= 0) return out;
    for (var k = 0; k < n; k++) {
      var norm = Math.sqrt(g.gx[k] * g.gx[k] + g.gy[k] * g.gy[k] + 1.0);
      out[k] = np.clip((-g.gx[k] * s[0] - g.gy[k] * s[1] + s[2]) / norm, 0.0, 1.0);
    }
    return out;
  }

  function faceAt(grid, position, lat, lon) {
    var rows = grid.rows, cols = grid.cols;
    if (rows < 3 || cols < 3) return null;
    if (!(grid.south <= lat && lat <= grid.north && grid.west <= lon && lon <= grid.east)) return null;
    var g = gradients(grid);
    var row = (grid.north - lat) / (grid.north - grid.south) * (rows - 1);
    var col = (lon - grid.west) / (grid.east - grid.west) * (cols - 1);
    var r = Math.min(Math.max(R(row), 0), rows - 1), c = Math.min(Math.max(R(col), 0), cols - 1);
    var k = r * cols + c;
    var slope = Math.atan(Math.hypot(g.gx[k], g.gy[k])) * np.RAD;
    var aspect = np.mod(Math.atan2(-g.gx[k], -g.gy[k]) * np.RAD, 360.0);
    var lit = litGrid(grid, position), here = lit[k];
    var spanLat = (grid.north - grid.south) / Math.max(rows - 1, 1);
    var spanLon = (grid.east - grid.west) / Math.max(cols - 1, 1);
    var perRow = geo.R * (spanLat * np.DEG), perCol = geo.R * (spanLon * np.DEG) * Math.cos(lat * np.DEG);
    var dr = Math.max(Math.trunc(NEIGHBOURHOOD / Math.max(perRow, 1.0)), 1);
    var dc = Math.max(Math.trunc(NEIGHBOURHOOD / Math.max(perCol, 1.0)), 1);
    // np.mean over a 2D patch: each row summed pairwise, the rows added in order.
    var total = 0, count = 0;
    for (var pr = Math.max(r - dr, 0); pr < Math.min(r + dr + 1, rows); pr++) {
      var line = [];
      for (var pc = Math.max(c - dc, 0); pc < Math.min(c + dc + 1, cols); pc++) line.push(lit[pr * cols + pc]);
      total += np.sum(line);
      count += line.length;
    }
    var around = count ? total / count : 0.0;
    return { slope: R(slope, 1), aspect: R(aspect), cardinal: geo.cardinal(aspect), insolation: R(here, 2),
             relative: around > 0.01 ? R(here / around, 2) : 1.0, sun_elevation: R(position.elevation, 1) };
  }

  function triggers(analysis, grid, limit) {
    if (!grid) return [];
    var found = [], th = M.thermals(analysis);
    for (var i = 0; i < th.length; i++) {
      var seg = th[i];
      if (!seg.centre) continue;
      var position = sun.position(analysis.flight.time[seg.start], seg.centre[0], seg.centre[1]);
      var face = faceAt(grid, position, seg.centre[0], seg.centre[1]);
      if (!face || face.slope < MIN_SLOPE) continue;
      found.push({ climb: i + 1, at: seg.start_time, face: face });
      if (limit && found.length >= limit) break;
    }
    return found;
  }

  function groundClearance(analysis, grid, seg) {
    var f = analysis.flight, start = seg.start, stop = Math.max(seg.stop, seg.start + 1);
    var alt = f.alt_gps.some(function (v) { return v !== 0; }) ? f.alt_gps : analysis.series.alt;
    var diffs = [];
    for (var i = start; i < Math.min(stop, f.lat.length); i++) diffs.push(alt[i] - T.at(grid, f.lat[i], f.lon[i]));
    return diffs.length ? np.median(diffs) : null;
  }

  function offsetOf(aspect, direction) { return Math.abs(np.mod(aspect - direction + 540, 360) - 180); }

  // Keyed by climb number, as the Python dict is.
  function sources(analysis, grid) {
    var wind = analysis.wind, found = {};
    M.thermals(analysis).forEach(function (seg, i) {
      var number = i + 1, at = seg.start_time;
      var fallback = { climb: number, at: at, label: 'thermal', confident: false, clearance: null,
                       slope: null, turn_rate: null, offset: null };
      if (!grid || !seg.centre) { found[number] = fallback; return; }
      var face = faceAt(grid, sun.position(analysis.flight.time[seg.start], seg.centre[0], seg.centre[1]),
                        seg.centre[0], seg.centre[1]);
      var clearance = groundClearance(analysis, grid, seg);
      if (!face || clearance === null) { found[number] = fallback; return; }
      var minutes = Math.max(seg.duration / 60.0, 1 / 60.0);
      var turnRate = (seg.turns || 0.0) / minutes;
      var ridge = face.slope >= RIDGE_SLOPE && clearance <= RIDGE_CLEARANCE && turnRate <= RIDGE_TURN_RATE;
      var against = seg.wind || wind;
      var offset = against ? offsetOf(face.aspect, against.direction) : null;
      found[number] = { climb: number, at: at, label: ridge ? 'ridge' : 'thermal', confident: true,
                        clearance: R(clearance), slope: face.slope, turn_rate: R(turnRate, 2),
                        offset: offset === null ? null : R(offset) };
    });
    return found;
  }

  function windward(analysis, grid, tolerance) {
    tolerance = tolerance === undefined ? 60.0 : tolerance;
    if (!grid || !analysis.wind) return null;
    var found = triggers(analysis, grid);
    if (!found.length) return null;
    var offsets = found.map(function (t) { return offsetOf(t.face.aspect, analysis.wind.direction); });
    return { windward: offsets.filter(function (o) { return o <= tolerance; }).length, total: offsets.length,
             mean_offset: R(np.mean(offsets)) };
  }

  TV.insolation = { MIN_SLOPE: MIN_SLOPE, RIDGE_CLEARANCE: RIDGE_CLEARANCE, RIDGE_SLOPE: RIDGE_SLOPE,
                    RIDGE_TURN_RATE: RIDGE_TURN_RATE, RIDGE_TOLERANCE: RIDGE_TOLERANCE,
                    faceAt: faceAt, litGrid: litGrid, sunVector: sunVector, triggers: triggers, sources: sources, windward: windward };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

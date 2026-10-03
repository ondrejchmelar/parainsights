/* The air-mass frame: `tracklog_viewer/airmass.py`, ported.
 *
 * The flight as the glider flew it rather than as the day carried it: a wind field from
 * the climbs that measured the air, interpolated in time and height, and the glide
 * ratio, circle wander and polar measured through the air with it. Every consumer refuses
 * on an untrusted field — a "corrected" number from a weak wind is an uncorrected number
 * wearing a hat.
 */
(function (TV) {
  'use strict';
  var np = TV.np, A = TV.analysis, M = TV.metrics, R = np.pyRound;
  var C = A.constants;

  var TIME_SCALE = 2400.0, HEIGHT_SCALE = 600.0, MIN_CONFIDENCE = 0.5, MIN_SOUNDINGS = 2;
  var MIN_GLIDE_SECONDS = 60.0;

  function trusted(field) { return field.confidence >= MIN_CONFIDENCE && field.soundings.length >= MIN_SOUNDINGS; }

  // Inverse-distance weighting in (time, height); see WindField.at.
  function windAt(field, t, altitude) {
    if (!field.soundings.length) return field.fallback || [0.0, 0.0];
    var weights = 0, vx = 0, vy = 0;
    field.soundings.forEach(function (s) {
      var dt = (t - s.t) / TIME_SCALE, dz = (altitude - s.altitude) / HEIGHT_SCALE;
      var weight = s.confidence / (dt * dt + dz * dz + 0.05);
      weights += weight; vx += weight * s.vx; vy += weight * s.vy;
    });
    if (weights <= 0) return field.fallback || [0.0, 0.0];
    return [vx / weights, vy / weights];
  }

  // Where the air is *going*: Wind.direction is where it comes from.
  function vector(speed, direction) {
    var towards = np.mod(direction + 180.0, 360.0) * np.DEG;
    return [speed * Math.sin(towards), speed * Math.cos(towards)];
  }

  // `weather.windAt(altitude)` → [speed m/s, direction from], optional: the model as a
  // fallback for a flight that sounded nothing itself.
  function field(a, weather) {
    var coarse = A.sampleInterval(a.series) > C.TURN_RESOLUTION_LIMIT, soundings = [];
    a.segments.forEach(function (seg) {
      if (seg.phase !== 'thermal' || !seg.wind) return;
      var circled = (seg.turns || 0) >= 2 && (seg.turn_direction === 'left' || seg.turn_direction === 'right');
      if (!(coarse ? seg.duration >= 120 : circled)) return;
      var v = vector(seg.wind.speed, seg.wind.direction);
      soundings.push({ t: a.series.t[seg.start], altitude: (seg.start_altitude + seg.finish_altitude) / 2.0,
                       vx: v[0], vy: v[1], confidence: seg.wind.confidence });
    });
    var fallback = null;
    if (weather && typeof weather.windAt === 'function') {
      var modelled = weather.windAt(np.median(a.series.alt));
      if (modelled) fallback = vector(modelled[0], modelled[1]);
    }
    if (!soundings.length) {
      return { soundings: [], confidence: fallback === null ? 0.0 : 0.4,
               source: fallback ? 'model' : 'none', fallback: fallback };
    }
    return { soundings: soundings, confidence: np.mean(soundings.map(function (s) { return s.confidence; })),
             source: fallback ? 'mixed' : 'measured', fallback: fallback };
  }

  function airVelocity(a, wind) {
    var s = a.series, n = s.t.length;
    var step = np.gradient(s.t), gx = np.gradient(s.x), gy = np.gradient(s.y);
    var vx = new Array(n), vy = new Array(n);
    for (var i = 0; i < n; i++) {
      var d = step[i] === 0 ? NaN : step[i];
      var w = windAt(wind, s.t[i], s.alt[i]);
      var ax = gx[i] / d - w[0], ay = gy[i] / d - w[1];
      vx[i] = ax !== ax ? 0 : ax;
      vy[i] = ay !== ay ? 0 : ay;
    }
    return { vx: vx, vy: vy };
  }

  function airspeed(a, wind) {
    var v = airVelocity(a, wind);
    return v.vx.map(function (x, i) { return 3.6 * Math.hypot(x, v.vy[i]); });
  }

  function longGlides(a) {
    return M.glides(a).filter(function (s) { return s.duration >= MIN_GLIDE_SECONDS; });
  }
  function insideMask(a) {
    var mask = new Array(a.series.t.length).fill(false);
    longGlides(a).forEach(function (s) { for (var i = s.start; i < s.stop; i++) mask[i] = true; });
    return mask;
  }

  function glidePerformance(a, wind) {
    if (!trusted(wind)) return null;
    var s = a.series, v = airVelocity(a, wind), air = [], ground = [];
    M.glides(a).forEach(function (seg) {
      if (seg.duration < MIN_GLIDE_SECONDS) return;
      var drop = s.alt[seg.start] - s.alt[seg.stop - 1];
      if (drop <= 0) return;
      var step = np.diff(s.t.slice(seg.start, seg.stop));
      if (!step.length) return;
      var pieces = [];
      for (var k = 0; k < step.length; k++) {
        var i = seg.start + k;
        pieces.push(Math.hypot(v.vx[i], v.vy[i]) * step[k]);
      }
      air.push(np.sum(pieces) / drop);
      if (seg.average_ld) ground.push(seg.average_ld);
    });
    if (air.length < 2) return null;
    var speeds = airspeed(a, wind), mask = insideMask(a);
    var inside = speeds.filter(function (_, i) { return mask[i]; });
    return {
      air_ld: R(np.median(air), 1), ground_ld: ground.length ? R(np.median(ground), 1) : 0.0,
      median_airspeed: inside.length ? R(np.median(inside), 1) : 0.0,
      glides: air.length, confidence: R(wind.confidence, 2)
    };
  }

  function circleWander(a, wind) {
    if (!trusted(wind)) return null;
    if (A.sampleInterval(a.series) > C.TURN_RESOLUTION_LIMIT) return null;
    var s = a.series, v = airVelocity(a, wind), step = np.gradient(s.t);
    var ax = np.cumsum(v.vx.map(function (x, i) { return x * step[i]; }));
    var ay = np.cumsum(v.vy.map(function (y, i) { return y * step[i]; }));
    var moves = [];
    M.thermals(a).forEach(function (seg) {
      var runs = A.monotoneRuns(s.heading.slice(seg.start, seg.stop)).filter(function (r) { return Math.abs(r[2]) >= 360.0; });
      var centres = [];
      runs.forEach(function (r) {
        var lo = seg.start + r[0], hi = seg.start + r[1];
        if (hi - lo < 3) return;
        centres.push([np.mean(ax.slice(lo, hi)), np.mean(ay.slice(lo, hi))]);
      });
      for (var k = 0; k + 1 < centres.length; k++) {
        moves.push(Math.hypot(centres[k + 1][0] - centres[k][0], centres[k + 1][1] - centres[k][1]));
      }
    });
    if (moves.length < 3) return null;
    return { median: R(np.median(moves)), worst: R(np.max(moves)),
             climbs: M.thermals(a).filter(function (seg) { return seg.turns; }).length };
  }

  function polar(a, wind, bins, minimum) {
    bins = bins || 6;
    minimum = minimum || 20;
    if (!trusted(wind)) return null;
    var s = a.series, speeds = airspeed(a, wind), mask = insideMask(a);
    if (mask.filter(Boolean).length < minimum * 2) return null;
    var v = speeds.filter(function (_, i) { return mask[i]; });
    var w = s.climb.filter(function (_, i) { return mask[i]; });
    var low = np.percentile(v, 5), high = np.percentile(v, 95);
    if (high - low < 5.0) return null;
    var edges = np.linspace(low, high, bins + 1), centres = [], sinks = [], counts = [];
    for (var b = 0; b < bins; b++) {
      var band = v.map(function (x) { return x >= edges[b] && (b < bins - 1 ? x < edges[b + 1] : x <= edges[b + 1]); });
      var count = band.filter(Boolean).length;
      if (count < minimum) continue;
      centres.push(R((edges[b] + edges[b + 1]) / 2, 1));
      sinks.push(R(np.median(w.filter(function (_, i) { return band[i]; })), 2));
      counts.push(count);
    }
    if (centres.length < 2) return null;
    var monotone = true;
    for (var k = 0; k + 1 < sinks.length; k++) if (!(sinks[k + 1] <= sinks[k] + 0.1)) monotone = false;
    var ratios = [];
    centres.forEach(function (speed, i) { if (sinks[i] < 0) ratios.push([speed, speed / 3.6 / -sinks[i]]); });
    var best = ratios.length && monotone ? M.firstMax(ratios, function (p) { return p[1]; }) : null;
    return { speeds: centres, sink: sinks, counts: counts,
             best_glide: best ? [R(best[0], 1), R(best[1], 1)] : null,
             confidence: R(wind.confidence, 2), monotone: monotone };
  }

  TV.airmass = { MIN_CONFIDENCE: MIN_CONFIDENCE, field: field, trusted: trusted, windAt: windAt,
                 airVelocity: airVelocity, airspeed: airspeed, glidePerformance: glidePerformance,
                 circleWander: circleWander, polar: polar };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

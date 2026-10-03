/* Flight analysis: `tracklog_viewer/analysis.py`, ported.
 *
 * Phases, per-thermal and per-glide statistics, wind, the time budget and the "other"
 * decomposition — the same rules with the same constants, and an output shaped exactly
 * like `Analysis.to_dict()` so the two can be compared field for field
 * (`tracklog_viewer/js_parity.py`). The reasoning behind each rule lives in the Python
 * docstrings and is not repeated here; where the two would read differently, the
 * comment says why.
 */
(function (TV) {
  'use strict';
  var np = TV.np, geo = TV.geo, igc = TV.igc, flightMod = TV.flight;
  var R = np.pyRound;

  var C = {
    GLIDE_PROGRESS: 0.9, MIN_THERMAL_SECONDS: 60, MIN_THERMAL_GAIN: 50.0,
    MIN_GLIDE_SECONDS: 120, MIN_DIVE_SECONDS: 30, MIN_DIVE_LOSS: 100.0,
    MAX_DIVE_CLIMB: -2.0, CONDENSE_THERMAL: 60, CONDENSE_GLIDE: 60, CONDENSE_DIVE: 30,
    TURNING_THRESHOLD: 3.0, THERMAL_SLOW_KMH: 10.0, TURN_ONSET_SECONDS: 5.0,
    TURN_RESOLUTION_LIMIT: 5.0, REVERSAL_HYSTERESIS: 60.0, TOW_START_SECONDS: 120,
    TOW_MIN_CLIMB: 1.0, TOW_MAX_TURNS_PER_MINUTE: 1.5, TOW_RESOLUTION_LIMIT: 15.0
  };

  // Half-open [start, stop) ranges where mask is true.
  function runs(mask) {
    var out = [], start = -1;
    for (var i = 0; i < mask.length; i++) {
      if (mask[i] && start < 0) start = i;
      else if (!mask[i] && start >= 0) { out.push([start, i]); start = -1; }
    }
    if (start >= 0) out.push([start, mask.length]);
    return out;
  }

  function condense(rs, t, gap) {
    if (!rs.length) return [];
    var merged = [[rs[0][0], rs[0][1]]];
    for (var k = 1; k < rs.length; k++) {
      var last = merged[merged.length - 1];
      if (t[rs[k][0]] - t[last[1] - 1] <= gap) last[1] = rs[k][1];
      else merged.push([rs[k][0], rs[k][1]]);
    }
    return merged;
  }

  function sustained(mask, need) {
    var out = new Array(mask.length).fill(false);
    runs(mask).forEach(function (r) {
      if (r[1] - r[0] >= need) for (var i = r[0]; i < r[1]; i++) out[i] = true;
    });
    return out;
  }

  function sampleInterval(series) {
    return series.t.length < 2 ? 0 : np.median(np.diff(series.t));
  }

  function classify(series) {
    var n = series.t.length, t = series.t, i;
    var phases = new Array(n).fill('unknown');
    // Python: max(int(round(5.0 / max(interval, 1e-6))), 1); round is half-to-even.
    var onset = Math.max(Math.trunc(R(C.TURN_ONSET_SECONDS / Math.max(sampleInterval(series), 1e-6))), 1);
    var circling = sustained(series.turn_rate.map(function (r) { return Math.abs(r) > C.TURNING_THRESHOLD; }), onset);

    var glide = series.progress.map(function (p, k) { return p >= C.GLIDE_PROGRESS && series.climb[k] <= 0; });
    condense(runs(glide), t, C.CONDENSE_GLIDE).forEach(function (r) {
      for (i = r[0]; i < r[1]; i++) phases[i] = 'glide';
    });

    var dive = series.progress.map(function (p, k) { return p < C.GLIDE_PROGRESS && series.climb[k] < 1.0; });
    condense(runs(dive), t, C.CONDENSE_DIVE).forEach(function (r) {
      if (series.alt[r[1] - 1] - series.alt[r[0]] < -C.MIN_DIVE_LOSS) {
        for (i = r[0]; i < r[1]; i++) phases[i] = 'dive';
      }
    });

    var thermal = series.climb.map(function (c, k) {
      return c > 0 && (series.progress[k] < C.GLIDE_PROGRESS || series.speed[k] < C.THERMAL_SLOW_KMH || circling[k]);
    });
    condense(runs(thermal), t, C.CONDENSE_THERMAL).forEach(function (r) {
      var start = r[0], stop = r[1], first = -1, last = -1;
      for (i = start; i < stop; i++) if (circling[i]) { if (first < 0) first = i; last = i; }
      if (first >= 0) { start = first; stop = last + 1; }
      for (i = start; i < stop; i++) phases[i] = 'thermal';
    });
    return phases;
  }

  function estimateWind(series, start, stop) {
    if (stop - start < 20) return null;
    var t = series.t.slice(start, stop), x = series.x.slice(start, stop), y = series.y.slice(start, stop);
    var span = t[t.length - 1] - t[0];
    if (span < 30) return null;
    var fx = np.linefit(t, x), fy = np.linefit(t, y);
    var speed = Math.hypot(fx.slope, fy.slope);
    if (speed < 0.1) return { speed: 0.0, direction: 0.0, cardinal: 'calm', confidence: 1.0 };
    var towards = np.mod(Math.atan2(fx.slope, fy.slope) * np.RAD, 360);
    var direction = np.mod(towards + 180, 360);
    var drift = speed * span;
    var scatter = t.length ? Math.sqrt((fx.residuals + fy.residuals) / t.length) : 0;
    var confidence = drift ? np.clip(drift / (drift + 2 * scatter), 0, 1) : 0;
    return { speed: speed, direction: direction, cardinal: geo.cardinal(direction), confidence: confidence };
  }

  // Prominence pruning of altitude extremes; see `analysis.salient`.
  function salient(values, threshold) {
    if (values.length < 3) return values.map(function (_, i) { return i; });
    var marks = [0];
    for (var i = 1; i < values.length - 1; i++) {
      if ((values[i] - values[i - 1]) * (values[i + 1] - values[i]) < 0) marks.push(i);
    }
    marks.push(values.length - 1);
    while (marks.length > 2) {
      var smallest = 0, best = Infinity;
      for (var k = 0; k < marks.length - 1; k++) {
        var swing = Math.abs(values[marks[k + 1]] - values[marks[k]]);
        if (swing < best) { best = swing; smallest = k; }
      }
      if (best >= threshold) break;
      var drop = (smallest > 0 && smallest < marks.length - 1) ? smallest : smallest + 1;
      if (drop === 0 || drop === marks.length - 1) drop = smallest === 0 ? smallest + 1 : smallest;
      marks.splice(drop, 1);
    }
    return marks;
  }

  function monotoneRuns(heading, hysteresis) {
    hysteresis = hysteresis === undefined ? C.REVERSAL_HYSTERESIS : hysteresis;
    if (heading.length < 2) return [];
    var pivots = [[0, heading[0]]], direction = 0;
    for (var i = 1; i < heading.length; i++) {
      var value = heading[i], step = value - pivots[pivots.length - 1][1];
      if (direction && step * direction > 0) pivots[pivots.length - 1] = [i, value];
      else if (Math.abs(step) >= hysteresis) { direction = step > 0 ? 1 : -1; pivots.push([i, value]); }
    }
    var out = [];
    for (var k = 0; k + 1 < pivots.length; k++) {
      out.push([pivots[k][0], pivots[k + 1][0], pivots[k + 1][1] - pivots[k][1]]);
    }
    return out;
  }

  function revolutions(heading) {
    return monotoneRuns(heading).filter(function (r) { return Math.abs(r[2]) >= 360.0; });
  }

  function turnStats(series, start, stop) {
    var heading = series.heading.slice(start, stop), rate = series.turn_rate.slice(start, stop);
    var t = series.t.slice(start, stop);
    if (heading.length < 2) return {};
    var net = heading[heading.length - 1] - heading[0];
    var swept = np.sum(np.diff(heading).map(Math.abs)) / 360.0;
    var circles = revolutions(heading);
    // Python's built-in sum() here: left to right, starting from 0.
    var turns = 0;
    circles.forEach(function (r) { turns += Math.abs(r[2]); });
    turns /= 360.0;

    var turning = rate.map(function (r) { return Math.abs(r) > C.TURNING_THRESHOLD; });
    var signs = [];
    rate.forEach(function (r, k) { if (turning[k]) signs.push(r > 0 ? 1 : (r < 0 ? -1 : 0)); });
    var direction = null, reversals = 0;
    if (signs.length) {
      var right = np.mean(signs.map(function (s) { return s > 0 ? 1 : 0; }));
      direction = right > 0.8 ? 'right' : (right < 0.2 ? 'left' : 'mixed');
      for (var k = 1; k < signs.length; k++) if (signs[k] !== signs[k - 1]) reversals++;
    }
    var steps = np.diff(t), circling = 0;
    circles.forEach(function (r) {
      var picked = [];
      for (var j = r[0]; j < r[1]; j++) if (turning[j]) picked.push(steps[j]);
      circling += np.sum(picked);
    });
    var circleSeconds = (turns >= 0.5 && circling) ? circling / turns : null;
    var radius = null;
    if (circleSeconds) {
      var speeds = [];
      for (var q = start; q < stop; q++) if (turning[q - start]) speeds.push(series.speed[q]);
      var turningSpeed = speeds.length ? np.mean(speeds) / 3.6 : null;
      if (turningSpeed) radius = turningSpeed * circleSeconds / (2 * Math.PI);
    }
    return {
      turns: R(turns, 1), swept_turns: R(swept, 1), turn_direction: direction,
      reversals: reversals, circle_seconds: circleSeconds ? R(circleSeconds, 1) : null,
      circle_radius: radius ? R(radius) : null, net_rotation: net
    };
  }

  function segment(flight, series, phase, start, stop) {
    var last = stop - 1, alt = series.alt;
    var duration = Math.trunc(series.t[last] - series.t[start]);
    var dz = alt[last] - alt[start];
    var steps = np.diff(alt.slice(start, stop)), stepT = np.diff(series.t.slice(start, stop));
    var peak = steps.map(function (s, k) { return s / (stepT[k] === 0 ? NaN : stepT[k]); });
    var straight = geo.distance(flight.lat[start], flight.lon[start], flight.lat[last], flight.lon[last]);
    var windowClimb = series.climb.slice(start, stop);
    var maxClimb = np.max(windowClimb);
    var zone = flight.timezone;
    var seg = {
      phase: phase, start: start, stop: stop,
      start_time: igc.clock(flight.time[start], zone),
      finish_time: igc.clock(flight.time[last], zone),
      duration: duration,
      altitude_change: R(dz),
      start_altitude: R(alt[start]),
      finish_altitude: R(alt[last]),
      distance: R(straight),
      average_speed: duration ? R(3.6 * straight / duration, 1) : 0.0,
      average_climb: duration ? R(dz / duration, 2) : 0.0,
      maximum_climb: R(maxClimb, 1),
      peak_climb: peak.length ? R(np.nanmax(peak), 1) : 0.0,
      maximum_descent: R(np.min(windowClimb), 1),
      accumulated_gain: R(np.sum(steps.filter(function (s) { return s > 0; }))),
      accumulated_loss: R(np.sum(steps.filter(function (s) { return s < 0; }))),
      efficiency: null, average_ld: null, turns: null, swept_turns: null,
      turn_direction: null, reversals: null, circle_seconds: null, circle_radius: null,
      wind: null,
      centre: [R(np.mean(flight.lat.slice(start, stop)), 6), R(np.mean(flight.lon.slice(start, stop)), 6)]
    };
    if (phase === 'thermal') {
      if (duration && maxClimb > 0) seg.efficiency = R(100.0 * dz / (duration * maxClimb));
      seg.wind = estimateWind(series, start, stop);
      if (sampleInterval(series) <= C.TURN_RESOLUTION_LIMIT) {
        var stats = turnStats(series, start, stop);
        Object.keys(stats).forEach(function (key) { if (key in seg) seg[key] = stats[key]; });
      }
    } else if (phase === 'glide' || phase === 'dive') {
      seg.average_ld = dz < 0 ? R(-straight / dz, 1) : null;
    }
    return seg;
  }

  function launchClimb(flight, series) {
    var rs = condense(runs(series.climb.map(function (c) { return c > C.TOW_MIN_CLIMB; })), series.t, C.CONDENSE_THERMAL);
    for (var k = 0; k < rs.length; k++) {
      var stop = rs[k][1];
      if (series.t[rs[k][0]] > C.TOW_START_SECONDS) break;
      var start = 0;
      var duration = series.t[stop - 1] - series.t[start];
      var gain = series.alt[stop - 1] - series.alt[start];
      if (duration < C.MIN_THERMAL_SECONDS || gain <= C.MIN_THERMAL_GAIN) return null;
      return segment(flight, series, 'thermal', start, stop);
    }
    return null;
  }

  function reclassifyTow(series, segments) {
    if (sampleInterval(series) > C.TOW_RESOLUTION_LIMIT) return;
    for (var k = 0; k < segments.length; k++) {
      var seg = segments[k];
      if (series.t[seg.start] > C.TOW_START_SECONDS) return;
      if (seg.phase !== 'thermal') continue;
      if (seg.average_climb < C.TOW_MIN_CLIMB) continue;
      if (seg.swept_turns === null) {
        if (np.mean(series.progress.slice(seg.start, seg.stop)) < 0.55) continue;
      } else {
        var minutes = seg.duration / 60 || 1;
        if (seg.swept_turns / minutes > C.TOW_MAX_TURNS_PER_MINUTE) continue;
      }
      seg.phase = 'tow';
      seg.efficiency = null;
      seg.wind = null;
      return;
    }
  }

  function summary(flight, series) {
    var alt = series.alt, steps = np.diff(alt), zone = flight.timezone, n = alt.length;
    var runningMin = [], low = Infinity, i;
    for (i = 0; i < n; i++) { low = Math.min(low, alt[i]); runningMin.push(low); }
    var fromTakeoff = flight.lat.map(function (lat, k) {
      return geo.distance(flight.lat[0], flight.lon[0], lat, flight.lon[k]);
    });
    var offset = igc.baroOffset(flight);
    return {
      pilot: flight.headers.pilot, glider: flight.headers.glider_type, site: flight.headers.site,
      date: igc.isoDate(flight.time[0], zone),
      takeoff_time: igc.clock(flight.time[0], zone),
      landing_time: igc.clock(flight.time[n - 1], zone),
      timezone: flight.timezone_source,
      duration: Math.trunc(series.t[n - 1]),
      fixes: n,
      sample_interval: R(sampleInterval(series), 1),
      altitude_source: igc.hasBaro(flight) ? 'baro' : 'gps',
      baro_offset: offset !== null ? R(offset) : null,
      takeoff_altitude: R(alt[0]), landing_altitude: R(alt[n - 1]),
      max_altitude: R(np.max(alt)), min_altitude: R(np.min(alt)),
      total_gain: R(np.sum(steps.filter(function (s) { return s > 0; }))),
      max_gain: R(np.max(alt.map(function (a, k) { return a - runningMin[k]; }))),
      max_climb: R(np.max(series.climb), 1), max_sink: R(np.min(series.climb), 1),
      max_speed: R(np.max(series.speed), 1),
      track_distance: R(series.s[n - 1]),
      straight_distance: R(geo.distance(flight.lat[0], flight.lon[0], flight.lat[n - 1], flight.lon[n - 1])),
      max_distance_from_takeoff: R(np.max(fromTakeoff))
    };
  }

  function decomposeOther(series, segments) {
    var steps = np.diff(series.t);
    if (!steps.length) return { seconds: 0, straight_sink: 0, scratching: 0, rising: 0, net_altitude: 0, mean_climb: 0.0 };
    var covered = new Array(steps.length).fill(false);
    segments.forEach(function (s) {
      for (var i = s.start; i < Math.max(s.stop - 1, s.start); i++) covered[i] = true;
    });
    var dalt = np.diff(series.alt);
    var free = [], straightSink = [], scratch = [], up = [], net = [];
    for (var i = 0; i < steps.length; i++) {
      if (covered[i]) continue;
      free.push(steps[i]);
      net.push(dalt[i]);
      if (series.climb[i] > 0) up.push(steps[i]);
      else if (series.progress[i] >= C.GLIDE_PROGRESS) straightSink.push(steps[i]);
      else scratch.push(steps[i]);
    }
    var seconds = np.sum(free), total = np.sum(net);
    return {
      seconds: Math.trunc(R(seconds)), straight_sink: Math.trunc(R(np.sum(straightSink))),
      scratching: Math.trunc(R(np.sum(scratch))), rising: Math.trunc(R(np.sum(up))),
      net_altitude: R(total), mean_climb: seconds ? R(total / seconds, 2) : 0.0
    };
  }

  function climbHistogram(series, phases) {
    var values = series.climb.filter(function (_, k) { return phases[k] === 'thermal'; });
    if (!values.length) return {};
    var edges = [];
    for (var k = 0; k < 17; k++) edges.push(-2.0 + k * 0.5);
    return { edges: edges, counts: np.histogram(values, edges),
             seconds_per_count: [np.median(np.diff(series.t))] };
  }

  // OtherSlice.fractions(): divided by the slice's own seconds, not by the parts' sum.
  function otherFractions(other) {
    var t = other.seconds || 1;
    return { straight_sink: other.straight_sink / t, scratching: other.scratching / t,
             rising: other.rising / t };
  }

  function fractions(obj, keys) {
    var total = 0;
    keys.forEach(function (k) { total += obj[k]; });
    total = total || 1;
    var out = {};
    keys.forEach(function (k) { out[k] = obj[k] / total; });
    return out;
  }

  function analyse(flight, options) {
    options = options || {};
    var series = flightMod.derive(flight, options.window);
    var phases = classify(series);
    var segments = [];
    [['thermal', C.MIN_THERMAL_SECONDS, function (dz) { return dz > C.MIN_THERMAL_GAIN; }],
     ['glide', C.MIN_GLIDE_SECONDS, function () { return true; }],
     ['dive', C.MIN_DIVE_SECONDS, function (dz, dt) { return dz / dt < C.MAX_DIVE_CLIMB; }]
    ].forEach(function (rule) {
      runs(phases.map(function (p) { return p === rule[0]; })).forEach(function (r) {
        var duration = series.t[r[1] - 1] - series.t[r[0]];
        var dz = series.alt[r[1] - 1] - series.alt[r[0]];
        if (duration >= rule[1] && rule[2](dz, Math.max(duration, 1))) {
          segments.push(segment(flight, series, rule[0], r[0], r[1]));
        }
      });
    });
    segments.sort(function (a, b) { return a.start - b.start; });

    var candidate = launchClimb(flight, series), overlapped = [];
    if (candidate) {
      overlapped = segments.filter(function (s) { return s.start < candidate.stop && candidate.start < s.stop; });
      segments.push(candidate);
      segments.sort(function (a, b) { return a.start - b.start; });
    }
    reclassifyTow(series, segments);
    if (candidate) {
      var drop = candidate.phase === 'tow' ? overlapped : [candidate];
      segments = segments.filter(function (s) { return drop.indexOf(s) < 0; });
    }

    var accounted = { thermal: 0, glide: 0, dive: 0, tow: 0 };
    segments.forEach(function (s) { accounted[s.phase] += s.duration; });
    var total = Math.trunc(series.t[series.t.length - 1]);
    var budget = {
      thermalling: accounted.thermal, gliding: accounted.glide, diving: accounted.dive,
      towing: accounted.tow,
      other: Math.max(total - (accounted.thermal + accounted.glide + accounted.dive + accounted.tow), 0)
    };

    var coarse = sampleInterval(series) > C.TURN_RESOLUTION_LIMIT;
    var winds = segments.filter(function (s) {
      if (s.phase !== 'thermal' || !s.wind) return false;
      return coarse ? s.duration >= 120
                    : ((s.turns || 0) >= 2 && (s.turn_direction === 'left' || s.turn_direction === 'right'));
    });
    var overall = null;
    if (winds.length) {
      var weights = winds.map(function (s) { return s.wind.confidence * s.duration; });
      var wsum = np.sum(weights);
      if (wsum > 0) {
        var vx = [], vy = [];
        winds.forEach(function (s, k) {
          vx.push(s.wind.speed * Math.sin(s.wind.direction * np.DEG) * weights[k]);
          vy.push(s.wind.speed * Math.cos(s.wind.direction * np.DEG) * weights[k]);
        });
        // numpy sums an (n, 2) array along axis 0 row by row, not pairwise.
        var sx = 0, sy = 0;
        for (var k = 0; k < vx.length; k++) { sx += vx[k]; sy += vy[k]; }
        var mx = sx / wsum, my = sy / wsum;
        var speed = Math.hypot(mx, my);
        var direction = np.mod(Math.atan2(mx, my) * np.RAD, 360);
        overall = { speed: speed, direction: direction, cardinal: geo.cardinal(direction),
                    confidence: np.mean(weights) / np.max(weights) };
      }
    }

    var other = decomposeOther(series, segments);
    return {
      flight: flight, series: series, phases: phases,
      summary: summary(flight, series),
      budget: Object.assign({}, budget, { fractions: fractions(budget, ['thermalling', 'gliding', 'diving', 'towing', 'other']) }),
      other: Object.assign({}, other, { fractions: otherFractions(other) }),
      wind: overall,
      climb_histogram: climbHistogram(series, phases),
      segments: segments
    };
  }

  // The same shape as Python's `Analysis.to_dict()`, and nothing else.
  function toDict(a) {
    return { summary: a.summary, budget: a.budget, other: a.other, wind: a.wind,
             climb_histogram: a.climb_histogram, segments: a.segments };
  }

  TV.analysis = { constants: C, runs: runs, condense: condense, classify: classify,
                  salient: salient, sampleInterval: sampleInterval, analyse: analyse,
                  toDict: toDict, monotoneRuns: monotoneRuns };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

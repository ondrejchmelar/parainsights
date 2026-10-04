/* Tier-1 measurements over an analysis: `tracklog_viewer/metrics.py`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * Every function returns null where the data cannot support the measurement, never a
 * plausible number, and none of them decides whether a number is worth printing — that
 * is the debrief's job. Shapes are those of the Python dataclasses' `asdict`.
 */
(function (TV) {
  'use strict';
  var np = TV.np, A = TV.analysis, R = np.pyRound;
  var C = A.constants;

  var MIN_CLIMB_FOR_CENTRING = 120.0, CENTRING_WINDOW = 60.0;

  function thermals(a) { return a.segments.filter(function (s) { return s.phase === 'thermal'; }); }
  function glides(a) { return a.segments.filter(function (s) { return s.phase === 'glide'; }); }
  function gaps(a) { return np.diff(a.series.t); }

  // Python's sum() and max()/min() with a key: left to right, the first extreme wins.
  function pySum(values) { var s = 0; values.forEach(function (v) { s += v; }); return s; }
  function firstMax(items, key) {
    var best = items[0];
    items.forEach(function (it) { if (key(it) > key(best)) best = it; });
    return best;
  }

  function airborneWindow(clearance, margin) {
    if (clearance === null || clearance === undefined) return null;
    margin = margin === undefined ? 100.0 : margin;
    var first = -1, last = -1;
    for (var i = 0; i < clearance.length; i++) if (clearance[i] > margin) { if (first < 0) first = i; last = i; }
    if (first < 0 || first === last) return null;
    var low = first, high = last + 1;
    return high - low >= 2 ? [low, high] : null;
  }

  function climbSelection(a) {
    var th = thermals(a).filter(function (s) { return s.duration > 0; });
    if (th.length < 3) return null;
    var best = Math.max.apply(null, th.map(function (s) { return s.average_climb; }));
    if (best <= 0) return null;
    var threshold = best / 2;
    var weak = th.filter(function (s) { return s.average_climb < threshold; });
    return {
      weak_seconds: pySum(weak.map(function (s) { return s.duration; })),
      total_seconds: pySum(th.map(function (s) { return s.duration; })),
      threshold: R(threshold, 2), best: R(best, 2), weak_climbs: weak.length
    };
  }

  function workingBand(a) {
    var n = a.series.t.length, steps = gaps(a);
    var mask = new Array(n).fill(false);
    thermals(a).forEach(function (s) { for (var i = s.start; i < s.stop; i++) mask[i] = true; });
    mask = mask.slice(0, n - 1);
    if (!steps.length || !mask.some(Boolean)) return null;
    var alt = a.series.alt.slice(0, n - 1).filter(function (_, k) { return mask[k]; });
    var low = np.min(alt), high = np.max(alt);
    if (high - low < 100.0) return null;
    var edges = np.linspace(low, high, 4);
    var dz = np.diff(a.series.alt).filter(function (_, k) { return mask[k]; });
    var weights = steps.filter(function (_, k) { return mask[k]; });
    var climbs = [], seconds = [];
    for (var b = 0; b < 3; b++) {
      var lo = edges[b], hi = edges[b + 1];
      var band = alt.map(function (v) { return v >= lo && (b === 2 ? v <= hi : v < hi); });
      var held = np.sum(weights.filter(function (_, k) { return band[k]; }));
      climbs.push(held ? R(np.sum(dz.filter(function (_, k) { return band[k]; })) / held, 2) : 0.0);
      seconds.push(Math.trunc(R(held)));
    }
    return { edges: edges.map(function (e) { return R(e); }), climbs: climbs, seconds: seconds };
  }
  function argmax(values) { var k = 0; values.forEach(function (v, i) { if (v > values[k]) k = i; }); return k; }
  function argmin(values) { var k = 0; values.forEach(function (v, i) { if (v < values[k]) k = i; }); return k; }

  function centring(a) {
    if (A.sampleInterval(a.series) > C.TURN_RESOLUTION_LIMIT) return null;
    var s = a.series, firstGain = 0, firstTime = 0, restGain = 0, restTime = 0, counted = 0;
    thermals(a).forEach(function (seg) {
      if (seg.duration < MIN_CLIMB_FOR_CENTRING) return;
      var t = s.t.slice(seg.start, seg.stop), alt = s.alt.slice(seg.start, seg.stop);
      var split = t[0] + CENTRING_WINDOW;
      var edge = np.interp([split], t, alt)[0];
      firstGain += edge - alt[0];
      firstTime += CENTRING_WINDOW;
      restGain += alt[alt.length - 1] - edge;
      restTime += t[t.length - 1] - split;
      counted += 1;
    });
    if (counted < 3 || firstTime <= 0 || restTime <= 0) return null;
    var first = firstGain / firstTime, rest = restGain / restTime;
    if (rest <= 0) return null;
    var cost = firstTime - (firstGain > 0 ? firstGain / rest : 0.0);
    return { ratio: R(first / rest, 2), first: R(first, 2), rest: R(rest, 2), climbs: counted,
             cost_seconds: Math.trunc(R(Math.max(cost, 0.0))) };
  }

  function climbGaps(a) {
    var th = thermals(a).slice().sort(function (x, y) { return x.start - y.start; });
    if (th.length < 3) return null;
    var s = a.series, list = [];
    for (var k = 0; k + 1 < th.length; k++) {
      var before = th[k], after = th[k + 1];
      var seconds = s.t[after.start] - s.t[before.stop - 1];
      if (seconds <= 0) continue;
      list.push([seconds, s.alt[after.start] - s.alt[before.stop - 1], before.finish_time, before.stop - 1]);
    }
    if (list.length < 2) return null;
    var longest = firstMax(list, function (g) { return g[0]; });
    return {
      median: Math.trunc(R(np.median(list.map(function (g) { return g[0]; })))),
      longest: Math.trunc(R(longest[0])), longest_at: longest[2],
      longest_loss: R(longest[1]), longest_index: longest[3]
    };
  }

  function concentration(a, top) {
    top = top || 3;
    var gains = thermals(a).filter(function (s) { return s.altitude_change > 0; })
      .map(function (s) { return s.altitude_change; })
      .sort(function (x, y) { return y - x; });
    if (gains.length <= top) return null;
    var total = pySum(gains);
    if (total <= 0) return null;
    return { share: R(pySum(gains.slice(0, top)) / total, 2), top: top, total_gain: R(total),
             climbs: gains.length };
  }

  function dayEnvelope(a) {
    var th = thermals(a).filter(function (s) { return s.duration > 0; });
    if (th.length < 4) return null;
    var hours = th.map(function (s) { return a.series.t[s.start] / 3600.0; });
    var climbs = th.map(function (s) { return s.average_climb; });
    var span = hours[hours.length - 1] - hours[0];
    if (span < 1.0) return null;
    var fit = np.weightedLinefit(hours, climbs, th.map(function (s) { return s.duration; }));
    return { slope: R(fit.slope, 2), first: R(fit.slope * hours[0] + fit.intercept, 2),
             last: R(fit.slope * hours[hours.length - 1] + fit.intercept, 2), climbs: th.length,
             hours: R(span, 1) };
  }

  // `weather` carries `cloudbase` and/or `thermal_top`, as numbers or functions.
  function ceilingUse(a, weather) {
    if (!weather) return null;
    var ceiling = null, source = '';
    ['cloudbase', 'thermal_top'].some(function (name) {
      var value = weather[name];
      if (typeof value === 'function') value = value();
      if (value) { ceiling = value; source = name; return true; }
      return false;
    });
    if (!ceiling || ceiling <= 0) return null;
    var reached = a.summary.max_altitude;
    return { reached: R(reached), ceiling: R(ceiling), fraction: R(reached / ceiling, 2), source: source };
  }

  TV.metrics = {
    thermals: thermals, glides: glides, pySum: pySum,
    firstMax: firstMax, argmax: argmax, argmin: argmin,
    airborneWindow: airborneWindow, climbSelection: climbSelection, workingBand: workingBand,
    centring: centring, climbGaps: climbGaps, concentration: concentration, dayEnvelope: dayEnvelope,
    ceilingUse: ceilingUse
  };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

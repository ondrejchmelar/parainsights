/* The debrief — a verdict, and findings ranked by what they cost:
 * `tracklog_viewer/debrief.py`, ported.
 *
 * Same rules: a finding is a measurement and a link, never an imperative; every finding
 * carries a cost in minutes or metres; nothing fires on data that cannot support it; and
 * a missing input removes the finding rather than leaving an empty card. The sentences
 * are the Python's word for word, formatted by `np.fmt`, which reproduces Python's
 * format specs, so the same flight reads the same in both.
 */
(function (TV) {
  'use strict';
  var np = TV.np, M = TV.metrics, igc = TV.igc, geo = TV.geo, xc = TV.xc;
  var fmt = np.fmt, R = np.pyRound;

  var THRESHOLDS = {
    weak_climb_share: 0.65, gap_over_median: 3.25, gap_minimum_seconds: 300,
    centring_ratio: 0.75, best_climb_left_metres: 100.0, other_lossy_share: 0.18,
    low_clearance: 100.0, ground_margin: 100.0, band_share: 0.20, band_ratio: 0.75,
    ceiling_used: 0.85, near_close: 0.35, minimum_share: 0.02, cards: 5
  };

  // A no-break space, as Python's `_num` uses: "2 024 m" must not wrap across a line.
  function num(v) { return fmt(v, 0, { thousands: '\u00a0' }); }

  function costLabel(cost) { return cost.unit === 'min' ? fmt(cost.value, 0) + ' min' : num(cost.value) + ' m'; }
  function minutes(seconds, a) {
    var airtime = a.summary.duration || 1;
    return { value: R(seconds / 60.0), unit: 'min', share: Math.min(seconds / airtime, 1.0) };
  }
  function metres(value, a) {
    var gained = a.summary.total_gain || 1;
    return { value: R(value), unit: 'm', share: Math.min(Math.abs(value) / gained, 1.0) };
  }

  function finding(f) {
    return { id: f.id, title: f.title, sentence: f.sentence, cost: f.cost,
             at: f.at === undefined ? null : f.at, cursor: f.cursor === undefined ? null : f.cursor,
             confidence: f.confidence === undefined ? 1.0 : f.confidence, evidence: f.evidence || {} };
  }

  function bestClimbLeft(a) {
    var th = M.thermals(a).slice().sort(function (x, y) { return x.start - y.start; });
    if (th.length < 3) return null;
    var best = M.firstMax(th, function (s) { return s.average_climb; });
    if (best.average_climb <= 0) return null;
    var ceiling = Math.max.apply(null, th.map(function (s) { return s.finish_altitude; }));
    var under = ceiling - best.finish_altitude;
    if (under < THRESHOLDS.best_climb_left_metres) return null;
    var index = th.indexOf(best);
    if (index + 1 >= th.length) return null;
    var following = th[index + 1], s = a.series;
    var gap = s.t[following.start] - s.t[best.stop - 1];
    if (gap <= 0) return null;
    return finding({
      id: 'best-climb-left',
      title: "You left the day's best climb " + fmt(under, 0) + ' m below the height you later reached',
      sentence: 'Climb ' + (index + 1) + ' was running at ' + fmt(best.average_climb, 2, { plus: true }) +
        ' m/s when you left it at ' + num(best.finish_altitude) + ' m. Later in the flight you were at ' +
        num(ceiling) + ' m. The next climb took ' + fmt(gap / 60, 0) + ' min to find and gave ' +
        fmt(following.average_climb, 2, { plus: true }) + ' m/s.',
      cost: minutes(gap, a), at: best.finish_time, cursor: best.stop - 1,
      evidence: { climb: index + 1, average_climb: best.average_climb, finish_altitude: best.finish_altitude,
                  ceiling: ceiling, next_climb: following.average_climb, gap_seconds: Math.trunc(gap) }
    });
  }

  function expensiveGap(a) {
    var g = M.climbGaps(a);
    if (!g || g.longest < THRESHOLDS.gap_minimum_seconds) return null;
    if (g.longest < g.median * THRESHOLDS.gap_over_median) return null;
    return finding({
      id: 'expensive-gap',
      title: 'Your longest search for a climb ran ' + fmt(g.longest / 60, 0) + ' min',
      sentence: 'It began at ' + g.longest_at + ' and cost ' + num(Math.abs(g.longest_loss)) +
        ' m of height before you found the next one. Most gaps that day were about ' +
        fmt(g.median / 60, 0) + ' min.',
      cost: minutes(g.longest - g.median, a), at: g.longest_at, cursor: g.longest_index,
      evidence: { longest_seconds: g.longest, median_seconds: g.median, loss: g.longest_loss }
    });
  }

  function lowPoint(a, clearance) {
    if (!clearance || clearance.length !== a.series.t.length) return null;
    if (!clearance.some(function (v) { return isFinite(v); })) return null;
    var w = M.airborneWindow(clearance, THRESHOLDS.ground_margin);
    if (!w) return null;
    var lo = w[0], hi = w[1], index = -1, lowest = Infinity, inside = [];
    for (var i = lo; i < hi; i++) {
      var v = clearance[i];
      if (v !== v) continue;
      inside.push(v);
      if (v < lowest) { lowest = v; index = i; }
    }
    var median = np.median(inside);
    if (lowest > THRESHOLDS.low_clearance || lowest < 0) return null;
    var when = igc.clock(a.flight.time[index], a.flight.timezone);
    return finding({
      id: 'low-point',
      title: 'You came within ' + fmt(lowest, 0) + ' m of the ground',
      sentence: 'That was at ' + when + '. For most of the flight you had about ' + num(median) +
        ' m underneath you. Launch and landing are left out of this, or they would win every time.',
      cost: metres(Math.max(median - lowest, 0.0), a), at: when, cursor: index,
      evidence: { lowest: R(lowest), median: R(median), from: lo, to: hi }
    });
  }

  function climbSelection(a) {
    var sel = M.climbSelection(a);
    if (!sel) return null;
    var fraction = sel.total_seconds ? sel.weak_seconds / sel.total_seconds : 0.0;
    if (fraction < THRESHOLDS.weak_climb_share) return null;
    var weak = M.thermals(a).filter(function (s) { return s.average_climb < sel.threshold; });
    var worst = weak.length ? M.firstMax(weak, function (s) { return s.duration; }) : null;
    return finding({
      id: 'climb-selection',
      title: 'You spent ' + fmt(sel.weak_seconds / 60, 0) + ' of your ' + fmt(sel.total_seconds / 60, 0) +
        " min circling in the day's weaker climbs",
      sentence: sel.weak_climbs + ' of your climbs averaged under ' + fmt(sel.threshold, 2, { plus: true }) +
        ' m/s, on a day whose best gave ' + fmt(sel.best, 2, { plus: true }) + '.',
      cost: minutes(sel.weak_seconds, a), at: worst ? worst.start_time : null, cursor: worst ? worst.start : null,
      evidence: { weak_seconds: sel.weak_seconds, total_seconds: sel.total_seconds,
                  threshold: sel.threshold, best: sel.best }
    });
  }

  function centring(a) {
    var c = M.centring(a);
    if (!c || c.ratio > THRESHOLDS.centring_ratio || c.cost_seconds < 60) return null;
    return finding({
      id: 'centring',
      title: 'Your first minute in a climb was worth ' + fmt(c.ratio, 0, { percent: true }) + ' of the rest of it',
      sentence: 'Across ' + c.climbs + ' climbs the opening minute averaged ' + fmt(c.first, 2, { plus: true }) +
        ' m/s against ' + fmt(c.rest, 2, { plus: true }) + ' once you had settled in. That is roughly ' +
        fmt(c.cost_seconds / 60, 0) + ' min of extra circling at the rate those same climbs went on to give.',
      cost: minutes(c.cost_seconds, a),
      evidence: { ratio: c.ratio, first: c.first, rest: c.rest, climbs: c.climbs }
    });
  }

  function workingBand(a) {
    var band = M.workingBand(a);
    if (!band) return null;
    var total = M.pySum(band.seconds) || 1;
    if (Math.min.apply(null, band.seconds) / total < THRESHOLDS.band_share) return null;
    var strongest = Math.max.apply(null, band.climbs);
    if (!strongest || band.climbs[2] / strongest > THRESHOLDS.band_ratio) return null;
    var best = M.argmax(band.climbs), worst = M.argmin(band.climbs);
    var height = band.edges[3] - band.edges[2];
    return finding({
      id: 'working-band',
      title: 'The lift was best ' + (best === 0 ? 'down low' : best === 1 ? 'in the middle of the band' : 'up high'),
      sentence: 'Split into thirds between ' + num(band.edges[0]) + ' m and ' + num(band.edges[3]) +
        ' m, your climbs averaged ' + fmt(band.climbs[0], 2, { plus: true }) + ', ' +
        fmt(band.climbs[1], 2, { plus: true }) + ' and ' + fmt(band.climbs[2], 2, { plus: true }) +
        ' m/s, over ' + fmt(band.seconds[0] / 60, 0) + ', ' + fmt(band.seconds[1] / 60, 0) + ' and ' +
        fmt(band.seconds[2] / 60, 0) + ' minutes of circling. The top ' + num(height) + ' m gave ' +
        fmt(band.climbs[2], 2, { plus: true }) + '.',
      cost: minutes(band.seconds[worst], a),
      evidence: { edges: band.edges.slice(), climbs: band.climbs.slice(), seconds: band.seconds.slice() }
    });
  }

  function ceilingUsed(a, weather) {
    var use = M.ceilingUse(a, weather);
    if (!use || use.fraction >= THRESHOLDS.ceiling_used) return null;
    return finding({
      id: 'ceiling-used',
      title: 'You used ' + fmt(use.fraction, 0, { percent: true }) + ' of the height the day was offering',
      sentence: 'Your highest point was ' + num(use.reached) + ' m against a modelled ' +
        use.source.replace(/_/g, ' ') + ' of ' + num(use.ceiling) + ' m, so ' +
        num(use.ceiling - use.reached) + ' m of the column went unused.',
      cost: metres(use.ceiling - use.reached, a),
      evidence: { reached: use.reached, ceiling: use.ceiling, fraction: use.fraction, source: use.source }
    });
  }

  function otherSlice(a) {
    var o = a.other;
    if (!o || o.seconds < 300) return null;
    var lossy = o.straight_sink + o.scratching;
    if (lossy < 300 || lossy / Math.max(a.summary.duration, 1) < THRESHOLDS.other_lossy_share) return null;
    var net = o.net_altitude;
    return finding({
      id: 'other-slice',
      title: fmt(o.seconds / 60, 0) + ' min counted as neither a climb nor a glide, and you ' +
        (net > 0 ? 'gained' : 'lost') + ' ' + num(Math.abs(net)) + ' m in it',
      sentence: fmt(o.straight_sink / 60, 0) + ' min of that was straight sink, which is what a glide costs; ' +
        fmt(o.scratching / 60, 0) + ' min was turning without climbing; and ' + fmt(o.rising / 60, 0) +
        ' min was rising air that no phase counted. Over the whole stretch it worked out at ' +
        fmt(o.mean_climb, 2, { plus: true }) + ' m/s.',
      cost: minutes(lossy, a),
      evidence: { seconds: o.seconds, straight_sink: o.straight_sink, scratching: o.scratching,
                  rising: o.rising, net_altitude: o.net_altitude }
    });
  }

  function closeThatWasnt(a, route) {
    if (!route || route.closed) return null;
    if (route.kind !== 'fai_triangle' && route.kind !== 'flat_triangle') return null;
    var points = route.points || [];
    if (points.length < 3) return null;
    var sides = xc.sides(route);
    if (!sides.length) return null;
    var gap = geo.distance(points[0].lat, points[0].lon, points[points.length - 1].lat, points[points.length - 1].lon);
    var perimeter = M.pySum(sides);
    if (perimeter <= 0 || gap / perimeter > THRESHOLDS.near_close) return null;
    var category = xc.classify(sides), multiplier = xc.MULTIPLIER[category] || 1.0;
    return finding({
      id: 'near-close',
      title: 'You finished ' + fmt(gap / 1000, 1) + ' km from closing the triangle',
      sentence: 'The route came back to within ' + fmt(gap / 1000, 1) + ' km of where it started, on a ' +
        fmt(perimeter / 1000, 1) + ' km perimeter. Closed, it would have scored as a ' +
        (category === 'fai' ? 'an FAI' : 'a flat') + ' triangle, at ×' + fmt(multiplier, 1) + ' instead of ×1.0.',
      cost: metres(gap, a),
      evidence: { gap: R(gap), perimeter: R(perimeter), category: category, multiplier: multiplier }
    });
  }

  function escapeHtml(value) {
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function planDeparture(a, flightPlan) {
    if (!flightPlan || !TV.plan) return null;
    var f = TV.plan.adherence(a, flightPlan);
    if (!f || f.departed_index === null) return null;
    var height = a.series.alt[f.departed_index];
    var remaining = f.departed_distance ? ' — ' + fmt(f.departed_distance / 1000, 0) + ' km short of the planned goal' : '';
    var caveat = f.reconstructed ? ' This plan carries no timestamp, so it is recorded as reconstructed intent.' : '';
    return finding({
      id: 'plan-departure',
      title: 'The track left the planned line at ' + f.departed_at + remaining,
      sentence: 'The first sustained departure beyond ' + fmt(TV.plan.DEPARTURE_METRES / 1000, 0) +
        ' km from the plan was at ' + f.departed_at + ', from ' + num(height) +
        ' m. Median distance from the planned line over the flight was ' + num(f.median_off) + ' m.' + caveat,
      cost: metres(f.departed_distance || f.max_off, a), at: f.departed_at, cursor: f.departed_index,
      confidence: f.reconstructed ? 0.6 : 1.0,
      evidence: { median_off: f.median_off, max_off: f.max_off, reconstructed: f.reconstructed }
    });
  }

  function planTurnpoints(a, flightPlan) {
    if (!flightPlan || !TV.plan) return null;
    var m = TV.plan.turnpoints(a, flightPlan);
    if (!m || m.reached >= m.total) return null;
    var missed = m.total - m.reached;
    return finding({
      id: 'plan-turnpoints',
      title: m.reached + ' of ' + m.total + ' planned turnpoints were reached',
      sentence: m.first_missed ? 'The first not reached was ' + escapeHtml(m.first_missed) + '.'
                               : missed + ' planned turnpoints were not reached.',
      cost: { value: missed, unit: 'm', share: Math.min(missed / Math.max(m.total, 1), 1.0) },
      confidence: m.reconstructed ? 0.6 : 1.0,
      evidence: { reached: m.reached, total: m.total, first_missed: m.first_missed }
    });
  }

  function verdict(a, route, weather) {
    var summary = a.summary, th = M.thermals(a);
    if (!summary.duration) return null;
    var totalMinutes = Math.floor(summary.duration / 60);
    var hours = Math.floor(totalMinutes / 60), mins = totalMinutes % 60;
    var shape = hours ? hours + ' h ' + (mins < 10 ? '0' : '') + mins + ' m' : mins + ' m';
    var kind = 'flight';
    if (route && route.distance) {
      var category = xc.shape(route);
      kind = (category === 'fai' || category === 'flat')
        ? (category === 'fai' ? 'FAI' : category) + ' triangle' : 'cross-country flight';
    }
    var parts = ['A ' + shape + ' ' + kind + '.'];
    var env = M.dayEnvelope(a);
    if (env && env.slope < -0.05) {
      parts.push('The day decayed ' + fmt(Math.abs(env.slope), 2) + ' m/s per hour, from ' +
                 fmt(env.first, 2, { plus: true }) + ' to ' + fmt(env.last, 2, { plus: true }) + '.');
    } else if (env && env.slope > 0.05) {
      parts.push('The day built ' + fmt(env.slope, 2) + ' m/s per hour, from ' +
                 fmt(env.first, 2, { plus: true }) + ' to ' + fmt(env.last, 2, { plus: true }) + '.');
    }
    var share = M.concentration(a);
    if (share && share.share >= 0.6) {
      parts.push(fmt(share.share, 0, { percent: true }) + ' of the height came from ' + share.top + ' of ' +
                 share.climbs + ' climbs.');
    }
    var headline = [];
    if (route && route.distance) {
      headline.push({ value: fmt(route.distance / 1000, 2) + ' km', label: 'scored', key: 'scored_km' });
    }
    if (th.length) {
      var mean = np.mean(th.map(function (s) { return s.average_climb; }));
      headline.push({ value: fmt(mean, 2, { plus: true }) + ' m/s', label: 'mean of ' + th.length + ' climbs',
                      key: 'mean_climb' });
    }
    var use = M.ceilingUse(a, weather);
    if (use) headline.push({ value: fmt(use.fraction, 0, { percent: true }), label: 'of cloudbase', key: 'ceiling_used' });
    else headline.push({ value: num(summary.max_altitude) + ' m', label: 'highest' });
    return { sentence: parts.join(' '), headline: headline };
  }

  // `options`: route, weather, clearance, flightPlan, limit — each optional; absent, the
  // findings resting on it do not exist and the input is named in `suppressed`.
  function build(a, options) {
    options = options || {};
    var route = options.route || null, weather = options.weather || null;
    var clearance = options.clearance || null, flightPlan = options.flightPlan || null;
    var builders = [
      function () { return bestClimbLeft(a); },
      function () { return expensiveGap(a); },
      function () { return lowPoint(a, clearance); },
      function () { return climbSelection(a); },
      function () { return centring(a); },
      function () { return workingBand(a); },
      function () { return ceilingUsed(a, weather); },
      function () { return otherSlice(a); },
      function () { return closeThatWasnt(a, route); },
      function () { return planDeparture(a, flightPlan); },
      function () { return planTurnpoints(a, flightPlan); }
    ];
    var found = [];
    builders.forEach(function (b) {
      var f = b();
      if (f && f.cost.share >= THRESHOLDS.minimum_share) found.push(f);
    });
    // Python's sort is stable, and so is Array.prototype.sort.
    found.sort(function (x, y) { return y.cost.share - x.cost.share; });
    var cards = options.limit !== undefined && options.limit !== null ? options.limit : THRESHOLDS.cards;
    var suppressed = [];
    if (!clearance) suppressed.push('terrain');
    if (!weather) suppressed.push('meteo');
    if (!route) suppressed.push('route');
    var th = M.thermals(a);
    if (th.length && th.some(function (s) { return s.turns === null; })) suppressed.push('sampling');
    if (!flightPlan) suppressed.push('plan');
    return { verdict: verdict(a, route, weather), findings: found.slice(0, cards), suppressed: suppressed };
  }

  // Python's Debrief.to_dict(): each cost carries its label, and the thresholds ride along.
  function toDict(d) {
    return {
      verdict: d.verdict,
      findings: d.findings.map(function (f) {
        return Object.assign({}, f, { cost: Object.assign({}, f.cost, { label: costLabel(f.cost) }) });
      }),
      suppressed: d.suppressed, thresholds: THRESHOLDS
    };
  }

  TV.debrief = { THRESHOLDS: THRESHOLDS, build: build, toDict: toDict, costLabel: costLabel, num: num };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

/* Cross-country distance and triangles: `tracklog_viewer/xc.py`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * Free distance through up to three turnpoints by dynamic programming over a sampled
 * track, and the best-*scoring* closed triangle by XContest's rules: perimeter times the
 * category multiplier, so a shorter FAI triangle (x1.4) routinely beats a longer flat one
 * (x1.2). `best()` is the choice `cli.py` makes between the two.
 */
(function (TV) {
  'use strict';
  var np = TV.np, geo = TV.geo, igc = TV.igc;

  var MAX_SAMPLES = 400;
  var FAI_MIN_SIDE = 0.28;
  var MAX_CLOSING = 0.20;
  var MULTIPLIER = { open: 1.0, flat: 1.2, fai: 1.4 };
  var TRIANGLE_SAMPLES = 260;

  function classify(sides) {
    var perimeter = sides.reduce(function (a, b) { return a + b; }, 0);
    if (sides.length !== 3 || perimeter <= 0) return 'open';
    return Math.min.apply(null, sides) / perimeter >= FAI_MIN_SIDE ? 'fai' : 'flat';
  }

  function sides(route) {
    if (route.points.length < 5) return [];
    var c = route.points.slice(1, 4), out = [];
    for (var i = 0; i < 3; i++) {
      var a = c[i], b = c[(i + 1) % 3];
      out.push(geo.distance(a.lat, a.lon, b.lat, b.lon));
    }
    return out;
  }

  function shape(route) {
    return (route.kind === 'fai_triangle' || route.kind === 'flat_triangle') ? classify(sides(route)) : 'open';
  }

  function score(route) { return route.distance / 1000.0 * (MULTIPLIER[shape(route)] || 1.0); }

  // np.linspace(0, stop, num): start + i * step, with the last value exactly `stop`.
  function linspace(stop, num) {
    var out = [], step = num > 1 ? stop / (num - 1) : 0;
    for (var i = 0; i < num; i++) out.push(i * step);
    if (num > 1) out[num - 1] = stop;
    return out;
  }

  // np.searchsorted(a, v) (side='left'): the first index with a[i] >= v.
  function searchsorted(a, v) {
    var lo = 0, hi = a.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (a[mid] < v) lo = mid + 1; else hi = mid; }
    return lo;
  }

  function unique(values) {
    var seen = {}, out = [];
    values.forEach(function (v) { if (!seen[v]) { seen[v] = true; out.push(v); } });
    return out.sort(function (a, b) { return a - b; });
  }

  // A shape-preserving subsample: spread by distance flown, endpoints kept.
  function sample(lat, lon, limit) {
    limit = limit || MAX_SAMPLES;
    var n = lat.length, i;
    if (n <= limit) { var all = []; for (i = 0; i < n; i++) all.push(i); return all; }
    var s = geo.cumulativeDistance(lat, lon);
    var idx = linspace(s[n - 1], limit).map(function (t) {
      return Math.min(Math.max(searchsorted(s, t), 0), n - 1);
    });
    return unique([0].concat(idx, [n - 1]));
  }

  function distanceMatrix(slat, slon) {
    var n = slat.length, m = [];
    for (var i = 0; i < n; i++) {
      var row = new Float64Array(n);
      for (var j = 0; j < n; j++) row[j] = geo.distance(slat[i], slon[i], slat[j], slon[j]);
      m.push(row);
    }
    return m;
  }

  function turnpoint(index, lat, lon, times) {
    return { index: index, lat: lat[index], lon: lon[index], time: times ? times[index] : null };
  }

  function optimise(lat, lon, times, turnpoints) {
    turnpoints = turnpoints === undefined ? 3 : turnpoints;
    var smp = sample(lat, lon);
    var slat = smp.map(function (k) { return lat[k]; }), slon = smp.map(function (k) { return lon[k]; });
    var n = smp.length, legs = turnpoints + 1, matrix = distanceMatrix(slat, slon);
    var best = new Float64Array(n), cameFrom = [];
    for (var leg = 0; leg < legs; leg++) {
      var choice = new Int32Array(n), next = new Float64Array(n);
      for (var to = 0; to < n; to++) {
        // np.triu keeps i <= j, and the lower triangle with the diagonal is -inf: legs
        // run forwards. argmax takes the first maximum, so ties go to the earliest.
        var arg = 0, top = -Infinity;
        for (var from = 0; from < to; from++) {
          var v = best[from] + matrix[from][to];
          if (v > top) { top = v; arg = from; }
        }
        choice[to] = arg;
        next[to] = top === -Infinity ? 0 : top;
      }
      cameFrom.push(choice);
      best = next;
    }
    var end = 0;
    for (var e = 1; e < n; e++) if (best[e] > best[end]) end = e;
    var total = best[end], chain = [end];
    for (var l = legs - 1; l >= 0; l--) chain.push(cameFrom[l][chain[chain.length - 1]]);
    chain.reverse();
    // The sample is ~1 fix in every 50 on a long flight, so a turnpoint it picks is up to
    // half a spacing from the fix that is really furthest out: 380 m short of XContest on
    // a 40 km flight, 200 m on 71 km. So, as `triangle` does, each point slides over the
    // full-resolution fixes around it — between its neighbours, never past them — while a
    // slide still adds distance. Two spacings either way: the sampled optimum is in the
    // right basin, and the fix it missed is next to it.
    var picks = chain.map(function (i) { return smp[i]; });
    var spacing = Math.max(Math.trunc(lat.length / Math.max(n, 1)), 1) * 2;
    function span(a, b) { return geo.distance(lat[a], lon[a], lat[b], lon[b]); }
    for (var pass = 0; pass < 5; pass++) {
      var moved = false;
      for (var slot = 0; slot < picks.length; slot++) {
        var before = slot > 0 ? picks[slot - 1] : -1, after = slot + 1 < picks.length ? picks[slot + 1] : -1;
        var low = Math.max(picks[slot] - spacing, before < 0 ? 0 : before);
        var high = Math.min(picks[slot] + spacing, after < 0 ? lat.length - 1 : after);
        var value = function (w) {
          return (before < 0 ? 0 : span(before, w)) + (after < 0 ? 0 : span(w, after));
        };
        var spot = picks[slot], spotValue = value(spot);
        for (var w = low; w <= high; w++) {
          var v = value(w);
          if (v > spotValue + 1e-6) { spotValue = v; spot = w; }
        }
        if (spot !== picks[slot]) { picks[slot] = spot; moved = true; }
      }
      if (!moved) break;
    }
    var points = picks.map(function (k) { return turnpoint(k, lat, lon, times); });
    var legDistances = [];
    for (var p = 0; p + 1 < points.length; p++) {
      legDistances.push(geo.distance(points[p].lat, points[p].lon, points[p + 1].lat, points[p + 1].lon));
    }
    var closing = geo.distance(points[0].lat, points[0].lon, points[points.length - 1].lat, points[points.length - 1].lon);
    total = legDistances.reduce(function (sum, d) { return sum + d; }, 0);
    return { kind: 'free_' + turnpoints + 'tp', distance: total, points: points, legs: legDistances,
             closed: total > 0 && closing / total < 0.2 };
  }

  // closing[i][k]: the shortest gap between a sample at or before i and one at or after k.
  function closingMatrix(matrix) {
    var n = matrix.length, c = matrix.map(function (row) { return Float64Array.from(row); });
    for (var i = 1; i < n; i++) for (var j = 0; j < n; j++) c[i][j] = Math.min(c[i][j], c[i - 1][j]);
    for (var k = n - 2; k >= 0; k--) for (var r = 0; r < n; r++) c[r][k] = Math.min(c[r][k], c[r][k + 1]);
    return c;
  }

  function triangle(lat, lon, times, samples) {
    var smp = sample(lat, lon, samples || TRIANGLE_SAMPLES);
    var slat = smp.map(function (k) { return lat[k]; }), slon = smp.map(function (k) { return lon[k]; });
    var n = smp.length;
    if (n < 3) return null;
    var matrix = distanceMatrix(slat, slon), closing = closingMatrix(matrix);
    var bestScore = 0.0, best = null;
    for (var i = 0; i < n - 2; i++) {
      for (var j = i + 1; j < n - 1; j++) {
        var sideA = matrix[i][j], arg = 0, top = -Infinity, argPerimeter = 0, argFai = false;
        for (var k = j + 1; k < n; k++) {
          var sideB = matrix[j][k], sideC = matrix[k][i];
          var perimeter = sideA + sideB + sideC;
          var openEnough = closing[i][k] <= MAX_CLOSING * perimeter;
          var shortest = Math.min(Math.min(sideA, sideB), sideC);
          var fai = shortest >= FAI_MIN_SIDE * perimeter;
          var sc = openEnough ? perimeter * (fai ? MULTIPLIER.fai : MULTIPLIER.flat) : 0.0;
          if (sc > top) { top = sc; arg = k; argPerimeter = perimeter; argFai = fai; }
        }
        if (top > bestScore) { bestScore = top; best = [i, j, arg, argPerimeter, argFai]; }
      }
    }
    if (!best) return null;

    var perimeterBest = best[3], isFai = best[4];
    // Slide each corner over the full-resolution fixes within half a sample spacing.
    var spacing = Math.max(Math.trunc(lat.length / Math.max(n, 1)), 1);
    var picks = [smp[best[0]], smp[best[1]], smp[best[2]]];
    for (var pass = 0; pass < 3; pass++) {
      var moved = false;
      for (var slot = 0; slot < 3; slot++) {
        var low = Math.max(picks[slot] - spacing, slot === 0 ? 0 : picks[slot - 1] + 1);
        var high = Math.min(picks[slot] + spacing, slot === 2 ? lat.length - 1 : picks[slot + 1] - 1);
        if (high <= low) continue;
        var o0 = picks[(slot + 1) % 3], o1 = picks[(slot + 2) % 3];
        var side3 = geo.distance(lat[o0], lon[o0], lat[o1], lon[o1]);
        var spot = 0, spotValue = -Infinity;
        for (var w = low; w <= high; w++) {
          var s1 = geo.distance(lat[w], lon[w], lat[o0], lon[o0]);
          var s2 = geo.distance(lat[w], lon[w], lat[o1], lon[o1]);
          var candidate = s1 + s2 + side3;
          var allowed = isFai ? Math.min(Math.min(s1, s2), side3) >= FAI_MIN_SIDE * candidate : true;
          var value = allowed ? candidate : 0.0;
          if (value > spotValue) { spotValue = value; spot = w; }
        }
        if (spotValue > perimeterBest + 1.0) { perimeterBest = spotValue; picks[slot] = spot; moved = true; }
      }
      if (!moved) break;
    }
    var corners = picks.map(function (c) { return turnpoint(c, lat, lon, times); });
    var sideList = [];
    for (var q = 0; q < 3; q++) {
      var a = corners[q], b = corners[(q + 1) % 3];
      sideList.push(geo.distance(a.lat, a.lon, b.lat, b.lon));
    }
    return { kind: isFai ? 'fai_triangle' : 'flat_triangle', distance: perimeterBest,
             points: [corners[0]].concat(corners, [corners[0]]), legs: sideList, closed: true };
  }

  // The route the report shows: the triangle when it outscores the open distance.
  function best(flight) {
    var times = flight.time.map(function (t) { return igc.clock(t, flight.timezone); });
    var free = optimise(flight.lat, flight.lon, times);
    var closed = triangle(flight.lat, flight.lon, times);
    return (closed && score(closed) > free.distance / 1000.0) ? closed : free;
  }

  TV.xc = { MULTIPLIER: MULTIPLIER, FAI_MIN_SIDE: FAI_MIN_SIDE, MAX_CLOSING: MAX_CLOSING, MAX_SAMPLES: MAX_SAMPLES,
            classify: classify, sides: sides, shape: shape, score: score, sample: sample,
            optimise: optimise, triangle: triangle, best: best };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

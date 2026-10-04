/* The handful of numpy behaviours the flight analysis depends on, reproduced exactly.
 *
 * Not a numpy: only what `igc.py`, `flight.py` and `analysis.py` call, each written to
 * give the *same bits* as numpy where that is achievable — the same interpolation
 * formula, the same pairwise summation order, Python's round-half-to-even. It was held to
 * the Python field for field on 63 real tracklogs before the Python was retired, and a
 * rounded field that disagrees in its last digit is a difference a reader can see, so
 * "close enough" is not the target where exact is cheap.
 *
 * Every function takes and returns plain arrays (or Float64Arrays); none mutates its
 * input.
 */
(function (TV) {
  'use strict';

  var DEG = Math.PI / 180;      // numpy's deg2rad multiplies by pi / 180
  var RAD = 180 / Math.PI;      // and rad2deg by 180 / pi

  // numpy's pairwise summation (`pairwise_sum` in numpy/core/src/umath/loops_utils.h):
  // blocks of eight accumulated in parallel, halves recursed above 128. Sequential
  // addition differs from it in the last bits, and a total that is then rounded to the
  // metre can land on the other side of .5.
  function pairwise(a, start, n) {
    var i, res;
    if (n < 8) {
      res = 0;
      for (i = 0; i < n; i++) res += a[start + i];
      return res;
    }
    if (n <= 128) {
      var r0 = a[start], r1 = a[start + 1], r2 = a[start + 2], r3 = a[start + 3];
      var r4 = a[start + 4], r5 = a[start + 5], r6 = a[start + 6], r7 = a[start + 7];
      var end = n - (n % 8);
      for (i = 8; i < end; i += 8) {
        r0 += a[start + i]; r1 += a[start + i + 1]; r2 += a[start + i + 2];
        r3 += a[start + i + 3]; r4 += a[start + i + 4]; r5 += a[start + i + 5];
        r6 += a[start + i + 6]; r7 += a[start + i + 7];
      }
      res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7));
      for (; i < n; i++) res += a[start + i];
      return res;
    }
    var n2 = Math.floor(n / 2);
    n2 -= n2 % 8;
    return pairwise(a, start, n2) + pairwise(a, start + n2, n - n2);
  }

  function sum(a) { return a.length ? pairwise(a, 0, a.length) : 0; }
  function mean(a) { return a.length ? sum(a) / a.length : NaN; }

  function median(a) {
    var n = a.length;
    if (!n) return NaN;
    var s = Array.prototype.slice.call(a).sort(function (x, y) { return x - y; });
    var h = n >> 1;
    // numpy takes the mean of the two middle values, as a sum and a division.
    return n % 2 ? s[h] : (s[h - 1] + s[h]) / 2;
  }

  function max(a) { var m = -Infinity; for (var i = 0; i < a.length; i++) if (a[i] > m) m = a[i]; return m; }
  function min(a) { var m = Infinity; for (var i = 0; i < a.length; i++) if (a[i] < m) m = a[i]; return m; }
  // nanmax: NaN is skipped, and all-NaN is NaN.
  function nanmax(a) {
    var m = -Infinity, seen = false;
    for (var i = 0; i < a.length; i++) if (a[i] === a[i]) { seen = true; if (a[i] > m) m = a[i]; }
    return seen ? m : NaN;
  }

  function diff(a) {
    var out = new Array(Math.max(a.length - 1, 0));
    for (var i = 1; i < a.length; i++) out[i - 1] = a[i] - a[i - 1];
    return out;
  }

  function cumsum(a) {
    var out = new Array(a.length), s = 0;
    for (var i = 0; i < a.length; i++) { s += a[i]; out[i] = s; }
    return out;
  }

  function clip(x, lo, hi) { return x < lo ? lo : (x > hi ? hi : x); }

  // np.mod: C fmod, then moved into the divisor's sign (numpy's npy_divmod).
  function mod(a, b) {
    var m = a % b;
    if (m !== 0 && ((b < 0) !== (m < 0))) m += b;
    return m;
  }

  // np.interp, as numpy's arr_interp computes it: clamp outside, exact at the last
  // point, and `slope * (x - xp[j]) + fp[j]` inside with j from a binary search.
  function interp(x, xp, fp) {
    var n = xp.length, out = new Array(x.length);
    var left = fp[0], right = fp[n - 1];
    for (var k = 0; k < x.length; k++) {
      var v = x[k];
      if (v !== v) { out[k] = v; continue; }
      if (v > xp[n - 1]) { out[k] = right; continue; }
      if (v < xp[0]) { out[k] = left; continue; }
      if (v === xp[n - 1]) { out[k] = right; continue; }
      var lo = 0, hi = n - 1;
      while (hi - lo > 1) {
        var mid = (lo + hi) >> 1;
        if (xp[mid] <= v) lo = mid; else hi = mid;
      }
      var j = lo;
      if (v === xp[j]) { out[k] = fp[j]; continue; }
      var slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j]);
      var r = slope * (v - xp[j]) + fp[j];
      if (r !== r) r = slope * (v - xp[j + 1]) + fp[j + 1];
      out[k] = r;
    }
    return out;
  }

  // np.unwrap with the default discontinuity of pi, on radians.
  function unwrap(p) {
    var n = p.length, out = new Array(n);
    if (!n) return out;
    out[0] = p[0];
    var correction = 0;
    for (var i = 1; i < n; i++) {
      var dd = p[i] - p[i - 1];
      var ddmod = mod(dd + Math.PI, 2 * Math.PI) - Math.PI;
      if (ddmod === -Math.PI && dd > 0) ddmod = Math.PI;
      var fix = ddmod - dd;
      if (Math.abs(dd) < Math.PI) fix = 0;
      correction += fix;
      out[i] = p[i] + correction;
    }
    return out;
  }

  // Least squares line, as np.polyfit(t, x, 1, full=True): slope, intercept and the sum
  // of squared residuals. numpy solves it by SVD; the closed form agrees to ~1e-15.
  function linefit(t, x) {
    var n = t.length, mt = mean(t), mx = mean(x), sxy = 0, sxx = 0, i;
    for (i = 0; i < n; i++) { sxy += (t[i] - mt) * (x[i] - mx); sxx += (t[i] - mt) * (t[i] - mt); }
    var slope = sxx ? sxy / sxx : 0, intercept = mx - slope * mt, rss = 0;
    for (i = 0; i < n; i++) { var e = x[i] - (slope * t[i] + intercept); rss += e * e; }
    return { slope: slope, intercept: intercept, residuals: rss };
  }

  // np.histogram with explicit edges: [e_i, e_{i+1}) except the last bin, which also
  // takes values equal to its right edge; anything outside is not counted.
  function histogram(values, edges) {
    var bins = edges.length - 1, counts = new Array(bins).fill(0);
    for (var k = 0; k < values.length; k++) {
      var v = values[k];
      if (!(v >= edges[0] && v <= edges[bins])) continue;
      if (v === edges[bins]) { counts[bins - 1]++; continue; }
      var lo = 0, hi = bins;
      while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (edges[mid] <= v) lo = mid; else hi = mid; }
      counts[lo]++;
    }
    return counts;
  }

  // Python's round(): correctly rounded on the *exact* binary value, ties to even.
  // Scaling first (x * 10) is the trap: 23 / 20 is 1.14999999999999991 in binary and
  // Python rounds it to 1.1, but 1.15 * 10 rounds to exactly 11.5 and then to 12.
  // `toFixed` rounds the exact value too, and differs only on a true tie, where it goes
  // away from zero — and a true tie shows as ...5000 in a longer expansion.
  function pyRound(x, digits) {
    if (x !== x || x === Infinity || x === -Infinity) return x;
    digits = digits || 0;
    var a = Math.abs(x), out;
    var frac = (a.toFixed(Math.min(digits + 30, 100)).split('.')[1]) || '';
    if (frac[digits] === '5' && /^0*$/.test(frac.slice(digits + 1))) {
      // A tie: keep the even neighbour.
      var down = Number(a.toFixed(digits + 1).slice(0, -1));
      var step = Math.pow(10, -digits);
      var last = Math.round(down / step) % 2;
      out = last ? Number((down + step).toFixed(digits)) : down;
    } else {
      out = Number(a.toFixed(digits));
    }
    if (x < 0) out = -out;
    return out === 0 ? 0 : out;   // never -0, which JSON prints as 0 and Python as -0.0
  }

  // Python's format(x, '.Nf') and friends, for the sentences the debrief writes: rounded
  // half-to-even on the exact value like `round`, and — unlike `round` — the sign is
  // kept when the result is zero: f"{-0.004:.2f}" is "-0.00" in Python. `plus` is the
  // '+' flag; `percent` is the '%' type, which multiplies by 100 first.
  function fmt(x, digits, options) {
    options = options || {};
    if (options.percent) x = x * 100;
    var negative = x < 0 || Object.is(x, -0);
    var body = Math.abs(pyRound(x, digits)).toFixed(digits);
    var sign = negative ? '-' : (options.plus ? '+' : '');
    var out = sign + body;
    if (options.thousands) {
      var parts = body.split('.');
      parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, options.thousands);
      out = sign + parts.join('.');
    }
    return out + (options.percent ? '%' : '');
  }

  // Weighted least squares line, as np.polyfit(x, y, 1, w=w): numpy weights the
  // *residuals* by w, so the squared error is weighted by w².
  function weightedLinefit(x, y, w) {
    var W = w.map(function (v) { return v * v; }), sw = 0, sx = 0, sy = 0, i;
    for (i = 0; i < x.length; i++) { sw += W[i]; sx += W[i] * x[i]; sy += W[i] * y[i]; }
    var mx = sx / sw, my = sy / sw, sxy = 0, sxx = 0;
    for (i = 0; i < x.length; i++) { sxy += W[i] * (x[i] - mx) * (y[i] - my); sxx += W[i] * (x[i] - mx) * (x[i] - mx); }
    var slope = sxx ? sxy / sxx : 0;
    return { slope: slope, intercept: my - slope * mx };
  }

  // np.linspace(start, stop, num), endpoint included.
  function linspace(start, stop, num) {
    var out = [], step = num > 1 ? (stop - start) / (num - 1) : 0;
    for (var i = 0; i < num; i++) out.push(i * step + start);
    if (num > 1) out[num - 1] = stop;
    return out;
  }

  // np.gradient(f) at unit spacing: central differences inside, one-sided at the ends.
  function gradient(f) {
    var n = f.length, out = new Array(n);
    if (n < 2) return f.map(function () { return 0; });
    out[0] = f[1] - f[0];
    out[n - 1] = f[n - 1] - f[n - 2];
    for (var i = 1; i < n - 1; i++) out[i] = (f[i + 1] - f[i - 1]) / 2.0;
    return out;
  }

  // np.percentile(a, q), 'linear': the virtual index q/100 * (n - 1), and numpy's _lerp,
  // which interpolates from the upper neighbour once the fraction reaches 0.5.
  function percentile(a, q) {
    var s = Array.prototype.slice.call(a).sort(function (x, y) { return x - y; });
    var n = s.length;
    if (!n) return NaN;
    var virtual = (q / 100) * (n - 1);
    var below = Math.floor(virtual), above = Math.min(below + 1, n - 1);
    below = Math.min(Math.max(below, 0), n - 1);
    var t = virtual - Math.floor(virtual);
    var lo = s[below], hi = s[above], d = hi - lo;
    return t >= 0.5 ? hi - d * (1 - t) : lo + d * t;
  }

  TV.np = {
    gradient: gradient, percentile: percentile,
    DEG: DEG, RAD: RAD, sum: sum, mean: mean, median: median, max: max, min: min,
    nanmax: nanmax, diff: diff, cumsum: cumsum, clip: clip, mod: mod, interp: interp,
    unwrap: unwrap, linefit: linefit, weightedLinefit: weightedLinefit, histogram: histogram,
    linspace: linspace, pyRound: pyRound, fmt: fmt
  };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

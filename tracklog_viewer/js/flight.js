/* Derived series: `tracklog_viewer/flight.py`, ported.
 *
 * Every series is computed over a sliding time window with interpolated edges rather
 * than snapped to the nearest fix: loggers are not reliably 1 Hz, and snapping makes the
 * window length follow the sample rate and quietly biases climb rates.
 */
(function (TV) {
  'use strict';
  var np = TV.np, geo = TV.geo, igc = TV.igc;

  var G = 9.80665;
  var WINDOW = 20.0;           // seconds; the de facto standard averaging period
  var TURN_SMOOTHING = 5.0;    // seconds

  // East/north metres about the first fix: equirectangular, centimetres off over a
  // cross-country flight, and it makes drift fitting ordinary linear algebra.
  function localFrame(lat, lon) {
    var lat0 = lat[0], lon0 = lon[0], k = Math.cos(lat0 * np.DEG);
    return {
      x: lon.map(function (v) { return (v - lon0) * np.DEG * geo.R * k; }),
      y: lat.map(function (v) { return (v - lat0) * np.DEG * geo.R; })
    };
  }

  function windowEdges(t, window) {
    var half = window / 2, a = t[0], b = t[t.length - 1];
    var t0 = t.map(function (v) { return np.clip(v - half, a, b); });
    var t1 = t.map(function (v) { return np.clip(v + half, a, b); });
    // Where clipping shortened one side, shift the other to keep the full length.
    for (var i = 0; i < t.length; i++) {
      if (t1[i] - t0[i] < window) {
        t0[i] = np.clip(t1[i] - window, a, b);
        t1[i] = np.clip(t0[i] + window, a, b);
      }
    }
    return { t0: t0, t1: t1 };
  }

  function derive(flight, window) {
    window = window || WINDOW;
    var n = flight.time.length, i;
    var t = flight.time.map(function (v) { return v - flight.time[0]; });
    var alt = igc.altitude(flight).slice();
    var frame = localFrame(flight.lat, flight.lon), x = frame.x, y = frame.y;
    var s = geo.cumulativeDistance(flight.lat, flight.lon);

    // Total energy altitude: trading speed for height should not read as a climb.
    var stepT = np.diff(t), stepS = np.diff(s), stepV = [];
    for (i = 0; i < stepT.length; i++) stepV.push(stepS[i] / (stepT[i] === 0 ? NaN : stepT[i]));
    var v = stepV.length ? [stepV[0]].concat(stepV) : t.map(function () { return 0; });
    v = v.map(function (w) {
      if (w !== w) return 0;
      if (w === Infinity) return Number.MAX_VALUE;
      if (w === -Infinity) return -Number.MAX_VALUE;
      return w;
    });
    var teAlt = alt.map(function (a, k) { return a + v[k] * v[k] / (2 * G); });

    var edges = windowEdges(t, window), t0 = edges.t0, t1 = edges.t1;
    var span = t0.map(function (a, k) { return Math.max(t1[k] - a, 1e-9); });
    function at(times, values) { return np.interp(times, t, values); }

    var s0 = at(t0, s), s1 = at(t1, s);
    var x0 = at(t0, x), x1 = at(t1, x), y0 = at(t0, y), y1 = at(t1, y);
    var a0 = at(t0, alt), a1 = at(t1, alt), e0 = at(t0, teAlt), e1 = at(t1, teAlt);
    var speed = [], climb = [], teClimb = [], progress = [];
    for (i = 0; i < n; i++) {
      var flown = s1[i] - s0[i];
      var straight = Math.hypot(x1[i] - x0[i], y1[i] - y0[i]);
      speed.push(3.6 * flown / span[i]);
      climb.push((a1[i] - a0[i]) / span[i]);
      teClimb.push((e1[i] - e0[i]) / span[i]);
      // 1.0 flying straight, ~0 circling; meaningless when barely moving.
      progress.push(flown > 1.0 ? np.clip(straight / Math.max(flown, 1e-9), 0, 1) : 0);
    }
    var turning = turningOf(t, x, y);
    return { t: t, s: s, alt: alt, speed: speed, climb: climb, te_climb: teClimb,
             progress: progress, heading: turning.heading, turn_rate: turning.rate, x: x, y: y };
  }

  // Unwrapped course and turn rate. Unwrapping is what makes turns countable: heading
  // change over a thermal divided by 360 is the number of circles flown.
  function turningOf(t, x, y) {
    var n = t.length, dx = np.diff(x), dy = np.diff(y), i;
    var raw = dx.map(function (d, k) { return Math.atan2(d, dy[k]) * np.RAD; });
    var course = raw.length ? [raw[0]].concat(raw) : t.map(function () { return 0; });
    // Where the glider barely moved the course is noise: hold the previous value.
    var held = new Array(n), best = 0;
    for (i = 0; i < n; i++) {
      var moved = i === 0 || Math.hypot(dx[i - 1], dy[i - 1]) > 0.5;
      var candidate = moved ? i : 0;
      if (candidate > best) best = candidate;
      held[i] = course[best];
    }
    var heading = np.unwrap(held.map(function (c) { return c * np.DEG; }))
      .map(function (r) { return r * np.RAD; });
    var ahead = np.interp(t.map(function (v) { return v + TURN_SMOOTHING / 2; }), t, heading);
    var behind = np.interp(t.map(function (v) { return v - TURN_SMOOTHING / 2; }), t, heading);
    return { heading: heading,
             rate: ahead.map(function (a, k) { return (a - behind[k]) / TURN_SMOOTHING; }) };
  }

  TV.flight = { G: G, WINDOW: WINDOW, TURN_SMOOTHING: TURN_SMOOTHING, derive: derive,
                localFrame: localFrame };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

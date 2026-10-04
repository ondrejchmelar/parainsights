/* The pilot's intent: `tracklog_viewer/plan.py`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * A plan from the tracklog's own C records (three turnpoints at least), or from the
 * sidecar JSON a pre-flight run writes; then where the flight left the planned line,
 * which turnpoints it reached in order, and planned against scored distance. Every
 * comparison goes through `describes`, which refuses a plan whose median cross-track
 * error is past 10 km — a task left loaded from another day is not this flight's plan.
 */
(function (TV) {
  'use strict';
  var np = TV.np, geo = TV.geo, igc = TV.igc, R = np.pyRound;

  var DEPARTURE_METRES = 3000.0, DEPARTURE_SECONDS = 240.0, STALE_MEDIAN_METRES = 10000.0;
  var DEFAULT_RADIUS = 400.0;

  function make(fields) {
    return Object.assign({ made_at: null, turnpoints: [], radii: [], goal_distance: null,
                           planned_start: null, planned_turn: null, planned_finish: null,
                           min_clearance: null, notes: null, source: 'none' }, fields);
  }
  function reconstructed(plan) { return plan.made_at === null || plan.made_at === undefined; }
  function declared(plan) { return plan.turnpoints.length >= 2; }
  function radius(plan, i) { return i < plan.radii.length && plan.radii[i] ? plan.radii[i] : DEFAULT_RADIUS; }
  function toDict(plan) { return Object.assign({}, plan, { reconstructed: reconstructed(plan) }); }

  function fromFlight(flight) {
    var task = flight.task || [];
    if (task.length < 3) return null;
    return make({ turnpoints: task.slice(), source: 'task' });
  }

  // A sidecar plan, already parsed from JSON.
  function fromJson(payload) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
    var points = (payload.turnpoints || []).filter(function (p) {
      return p && typeof p === 'object' && 'lat' in p && 'lon' in p;
    }).map(function (p) { return { name: String(p.name === undefined ? '' : p.name), lat: +p.lat, lon: +p.lon }; });
    var get = function (k) { return payload[k] === undefined ? null : payload[k]; };
    return make({ made_at: get('made_at'), turnpoints: points,
                  radii: (payload.radii || []).filter(function (r) { return r !== null; }).map(Number),
                  goal_distance: get('goal_distance'), planned_start: get('planned_start'),
                  planned_turn: get('planned_turn'), planned_finish: get('planned_finish'),
                  min_clearance: get('min_clearance'), notes: get('notes'), source: 'sidecar' });
  }

  function legDistance(points) {
    var s = 0;
    for (var i = 0; i + 1 < points.length; i++) s += geo.distance(points[i].lat, points[i].lon, points[i + 1].lat, points[i + 1].lon);
    return s;
  }

  // Distance from the planned line, per fix, projecting onto each leg in a flat frame.
  function crossTrack(plan, lat, lon) {
    var best = lat.map(function () { return Infinity; });
    for (var k = 0; k + 1 < plan.turnpoints.length; k++) {
      var a = plan.turnpoints[k], b = plan.turnpoints[k + 1];
      var mid = ((a.lat + b.lat) / 2.0) * np.DEG, cm = Math.cos(mid);
      var ax = a.lon * cm, ay = a.lat, bx = b.lon * cm, by = b.lat;
      var dx = bx - ax, dy = by - ay, length = dx * dx + dy * dy;
      for (var i = 0; i < lat.length; i++) {
        var px = lon[i] * cm, py = lat[i];
        var t = length === 0 ? 0 : np.clip(((px - ax) * dx + (py - ay) * dy) / length, 0.0, 1.0);
        var nx = ax + t * dx, ny = ay + t * dy;
        var d = geo.distance(py, px / cm, ny, nx / cm);
        if (d < best[i]) best[i] = d;
      }
    }
    return best;
  }

  function describes(analysis, plan) {
    if (!plan || !declared(plan)) return false;
    var off = crossTrack(plan, analysis.flight.lat, analysis.flight.lon);
    if (!off.some(function (v) { return isFinite(v); })) return false;
    return np.median(off) <= STALE_MEDIAN_METRES;
  }

  function adherence(analysis, plan) {
    if (!describes(analysis, plan)) return null;
    var f = analysis.flight, off = crossTrack(plan, f.lat, f.lon), t = analysis.series.t;
    var departed = null, start = null;
    for (var i = 0; i < off.length; i++) {
      var away = off[i] > DEPARTURE_METRES;
      if (away && start === null) start = i;
      else if (!away) start = null;
      else if (start !== null && t[i] - t[start] >= DEPARTURE_SECONDS) { departed = start; break; }
    }
    var remaining = null;
    if (departed !== null && plan.goal_distance) remaining = Math.max(plan.goal_distance - analysis.series.s[departed], 0.0);
    return { median_off: R(np.median(off)), max_off: R(np.max(off)),
             departed_at: departed !== null ? igc.clock(f.time[departed], f.timezone) : null,
             departed_index: departed, departed_distance: remaining ? R(remaining) : null,
             reconstructed: reconstructed(plan) };
  }

  function turnpoints(analysis, plan) {
    if (!describes(analysis, plan)) return null;
    var f = analysis.flight, times = [], firstMissed = null, cursor = 0;
    plan.turnpoints.forEach(function (point, index) {
      var r = radius(plan, index), hit = -1;
      for (var i = cursor; i < f.lat.length; i++) {
        if (geo.distance(point.lat, point.lon, f.lat[i], f.lon[i]) <= r) { hit = i; break; }
      }
      if (hit >= 0) { times.push(igc.clock(f.time[hit], f.timezone)); cursor = hit; }
      else {
        times.push(null);
        if (firstMissed === null) firstMissed = point.name || 'turnpoint ' + (index + 1);
      }
    });
    return { reached: times.filter(Boolean).length, total: plan.turnpoints.length,
             first_missed: firstMissed, times: times, reconstructed: reconstructed(plan) };
  }

  function budget(analysis, plan, route) {
    if (!plan || !describes(analysis, plan)) return null;
    var planned = plan.goal_distance || (declared(plan) ? legDistance(plan.turnpoints) : null);
    if (!planned || !route || !route.distance) return null;
    return { planned_km: R(planned / 1000.0, 1), scored_km: R(route.distance / 1000.0, 2),
             short_km: R((planned - route.distance) / 1000.0, 1), reconstructed: reconstructed(plan) };
  }

  TV.plan = { DEPARTURE_METRES: DEPARTURE_METRES, DEPARTURE_SECONDS: DEPARTURE_SECONDS,
              STALE_MEDIAN_METRES: STALE_MEDIAN_METRES, fromFlight: fromFlight, fromJson: fromJson,
              toDict: toDict, describes: describes, adherence: adherence, turnpoints: turnpoints,
              budget: budget, crossTrack: crossTrack, reconstructed: reconstructed, declared: declared };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

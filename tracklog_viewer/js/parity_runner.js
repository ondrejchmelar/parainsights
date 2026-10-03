/* Node side of the parity harness (`tracklog_viewer/js_parity.py`).
 *
 * Reads a JSON list of {path, positionZone} on stdin, runs the JavaScript analysis over
 * each file exactly as the page will, and writes the `toDict()` results as a JSON list.
 * `positionZone` is Python's timezonefinder answer, passed through so the comparison
 * isolates the one source the page cannot reproduce yet.
 */
'use strict';
var fs = require('fs');
var path = require('path');
global.TV = {};
['np', 'geo', 'igc', 'flight', 'analysis', 'xc', 'metrics', 'debrief', 'sun', 'airmass', 'terrain', 'insolation', 'plan', 'kml'].forEach(function (name) {
  require(path.join(__dirname, name + '.js'));
});

var zlib = require('zlib');
var input = JSON.parse(fs.readFileSync(0, 'utf8'));

function parse(job) {
  var options = { positionZone: job.positionZone ? function () { return job.positionZone; } : null,
                  inflateRaw: function (bytes) { return Promise.resolve(new Uint8Array(zlib.inflateRawSync(bytes))); } };
  if (/\.(kml|kmz)$/i.test(job.path)) {
    return TV.kml.parseBytes(new Uint8Array(fs.readFileSync(job.path)), path.basename(job.path), options);
  }
  return Promise.resolve(TV.igc.parse(fs.readFileSync(job.path, 'utf8'), options));
}

function run(job, flight) {
  try {
    var analysis = TV.analysis.analyse(flight);
    var parsed = { fixes: flight.time.length, warnings: flight.warnings, dropped: flight.dropped,
                   logger_type: flight.headers.logger_type, timezone_source: flight.timezone_source };
    var result = TV.analysis.toDict(analysis);
    result.parsed = parsed;
    var route = TV.xc.best(flight);
    result.route = Object.assign({}, route, { shape: TV.xc.shape(route), score: TV.xc.score(route) });
    // The same synthetic ground and cloudbase the Python side uses (see js_parity.py), so
    // the findings that need terrain or weather are exercised without a network.
    var low = Math.min.apply(null, analysis.series.alt);
    var clearance = analysis.series.alt.map(function (v) { return v - (low - 60); });
    var weather = { cloudbase: analysis.summary.max_altitude + 400 };
    var M = TV.metrics;
    result.metrics = {
      straight_air: M.straightAir(analysis), cross_country_speed: M.crossCountrySpeed(analysis, route),
      glide_ratio_median: M.glideRatioMedian(analysis), climb_selection: M.climbSelection(analysis),
      working_band: M.workingBand(analysis), centring: M.centring(analysis), climb_gaps: M.climbGaps(analysis),
      concentration: M.concentration(analysis), day_envelope: M.dayEnvelope(analysis),
      detour: M.detour(analysis, route), lowest_save: M.lowestSave(analysis, clearance),
      ceiling_use: M.ceilingUse(analysis, weather), airborne_window: M.airborneWindow(clearance)
    };
    result.debrief = TV.debrief.toDict(TV.debrief.build(analysis, { route: route }));
    result.debrief_full = TV.debrief.toDict(TV.debrief.build(analysis, { route: route, weather: weather, clearance: clearance }));
    var plan = TV.plan.fromFlight(flight);
    result.plan = plan && {
      plan: TV.plan.toDict(plan), describes: TV.plan.describes(analysis, plan),
      adherence: TV.plan.adherence(analysis, plan), turnpoints: TV.plan.turnpoints(analysis, plan),
      budget: TV.plan.budget(analysis, plan, route),
      debrief: TV.debrief.toDict(TV.debrief.build(analysis, { route: route, flightPlan: plan }))
    };
    result.sun = TV.sun.forFlight(flight);
    if (job.terrain) {
      var grid = job.terrain, I = TV.insolation;
      var agl = TV.terrain.clearance(grid, analysis);
      result.insolation = {
        clearance: agl.filter(function (_, i) { return i % 37 === 0; }),
        triggers: I.triggers(analysis, grid), sources: I.sources(analysis, grid),
        windward: I.windward(analysis, grid)
      };
    }
    var AM = TV.airmass;
    [['airmass', null], ['airmass_model', { windAt: function () { return [5.0, 270.0]; } }]].forEach(function (pair) {
      var wind = AM.field(analysis, pair[1]);
      result[pair[0]] = { field: wind, glide: AM.glidePerformance(analysis, wind),
                          wander: AM.circleWander(analysis, wind), polar: AM.polar(analysis, wind) };
    });
    return { ok: true, result: result };
  } catch (error) {
    return { ok: false, error: String(error && error.stack || error) };
  }
}

var out = [];
input.reduce(function (chain, job) {
  return chain.then(function () {
    return parse(job).then(function (flight) { out.push(run(job, flight)); },
                           function (error) { out.push({ ok: false, error: String(error && error.stack || error) }); });
  });
}, Promise.resolve()).then(function () { process.stdout.write(JSON.stringify(out)); });

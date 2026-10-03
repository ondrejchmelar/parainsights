/* Node side of `js_parity.py --report`: renders each flight's article with report.js. */
'use strict';
var fs = require('fs'), path = require('path'), zlib = require('zlib');
global.TV = {};
['np', 'geo', 'igc', 'flight', 'analysis', 'xc', 'metrics', 'debrief', 'sun', 'airmass', 'terrain',
 'insolation', 'plan', 'kml', 'certification', 'meteo', 'charts', 'scene', 'report'].forEach(function (name) {
  require(path.join(__dirname, name + '.js'));
});
var input = JSON.parse(fs.readFileSync(0, 'utf8'));

function parse(job) {
  var options = { positionZone: job.positionZone ? function () { return job.positionZone; } : null,
                  inflateRaw: function (b) { return Promise.resolve(new Uint8Array(zlib.inflateRawSync(b))); } };
  if (/\.(kml|kmz)$/i.test(job.path)) return TV.kml.parseBytes(new Uint8Array(fs.readFileSync(job.path)), path.basename(job.path), options);
  return Promise.resolve(TV.igc.parse(fs.readFileSync(job.path, 'utf8'), options));
}

var out = [];
input.jobs.reduce(function (chain, job) {
  return chain.then(function () {
    return parse(job).then(function (flight) {
      try {
        var analysis = TV.analysis.analyse(flight);
        var meteo = job.meteo ? TV.meteo.parse(job.meteo, job.when, job.now) : null;
        var html = TV.report.flightBody(analysis, {
          meteo: meteo, route: TV.xc.best(flight), terrain: job.terrain, sceneTerrain: job.sceneTerrain,
          uid: 'f0', flightPlan: TV.plan.fromFlight(flight), certificationTable: input.certification, now: job.now
        });
        out.push({ ok: true, html: html });
      } catch (error) { out.push({ ok: false, error: String(error && error.stack || error) }); }
    }, function (error) { out.push({ ok: false, error: String(error && error.stack || error) }); });
  });
}, Promise.resolve()).then(function () { process.stdout.write(JSON.stringify(out)); });

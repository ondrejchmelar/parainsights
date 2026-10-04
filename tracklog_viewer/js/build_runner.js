/* Node side of `js_build.py`: the report's own flights, through the same code an uploaded
 * track goes through in the page. Reads one JSON request on stdin, writes JSON on stdout.
 *
 * `inspect` reads each file and says what the CLI should fetch for it — the ground box
 * (`TV.terrain.remoteFor`) and the weather request (`TV.meteo.request`) — and the date and
 * site a sidecar plan is filed under. `render` writes the articles with `TV.upload.compose`
 * from what was fetched. Nothing here touches the network. */
'use strict';
var fs = require('fs'), path = require('path'), zlib = require('zlib');
global.TV = {};
// The take-off timezone the way the page finds it: tz-lookup, not timezonefinder.
global.tzlookup = require(path.join(__dirname, 'vendor', 'tz-lookup.js'));
['np', 'geo', 'igc', 'flight', 'analysis', 'xc', 'metrics', 'debrief', 'sun', 'airmass', 'terrain',
 'insolation', 'plan', 'kml', 'certification', 'meteo', 'charts', 'scene', 'report', 'upload'].forEach(function (name) {
  require(path.join(__dirname, name + '.js'));
});
var input = JSON.parse(fs.readFileSync(0, 'utf8'));
var inflate = { inflateRaw: function (b) { return Promise.resolve(new Uint8Array(zlib.inflateRawSync(b))); } };

function parse(job) {
  return TV.upload.readBytes(new Uint8Array(fs.readFileSync(job.path)), job.name, inflate);
}

function failed(error) { return { ok: false, error: String(error && error.message || error),
                                   stack: String(error && error.stack || error) }; }

var steps = {
  inspect: function (job, flight) {
    var middle = TV.meteo.middleOf(flight), summary = TV.igc;
    var annotate = { pilot: flight.headers.pilot, site: flight.headers.site };
    var fields = (job.label || '').split('|');
    if (fields[0] && fields[0].trim()) annotate.pilot = fields[0].trim();
    if (fields[1] && fields[1].trim()) annotate.site = fields[1].trim();
    return {
      ok: true, ground: TV.terrain.remoteFor(flight),
      meteo: { url: TV.meteo.request(middle.lat, middle.lon, middle.when, input.now), when: middle.when },
      date: summary.isoDate(flight.time[0], flight.timezone), site: annotate.site || null,
      pilot: annotate.pilot || null, warnings: flight.warnings.slice(0, 5), dropped: flight.dropped
    };
  },
  render: function (job, flight) {
    var meteo = job.meteo ? TV.meteo.parse(job.meteo, job.when, input.now) : null;
    var made = TV.upload.compose(flight, job.name, {
      terrain: job.terrain, sceneTerrain: job.sceneTerrain, meteo: meteo,
      certificationTable: input.certification, now: input.now
    }, job.options);
    made.ok = true;
    return made;
  }
};

var out = [];
input.jobs.reduce(function (chain, job) {
  return chain.then(function () {
    return parse(job).then(function (flight) {
      try { out.push(steps[input.mode](job, flight)); } catch (error) { out.push(failed(error)); }
    }, function (error) { out.push(failed(error)); });
  });
}, Promise.resolve()).then(function () { process.stdout.write(JSON.stringify(out)); });

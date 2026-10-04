/* Node side of `js_build.py`: the report's own flights, rendered at build time by the same
 * `TV.upload.compose` an uploaded track goes through in the page. Reads one JSON job list
 * on stdin and writes the articles on stdout. The inputs are what the CLI fetched — the
 * ground with its heights, Open-Meteo's answer unparsed, the glider table — so nothing
 * here touches the network. */
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
  var bytes = new Uint8Array(fs.readFileSync(job.path));
  var head = Buffer.from(bytes.subarray(0, 2000)).toString('utf8');
  if (/\.(kml|kmz)$/i.test(job.name) || (bytes[0] === 0x50 && bytes[1] === 0x4b) || /<kml/i.test(head)) {
    return TV.kml.parseBytes(bytes, job.name, inflate);
  }
  return Promise.resolve(TV.igc.parse(Buffer.from(bytes).toString('utf8')));
}

var out = [];
input.jobs.reduce(function (chain, job) {
  return chain.then(function () {
    return parse(job).then(function (flight) {
      try {
        var meteo = job.meteo ? TV.meteo.parse(job.meteo, job.when, input.now) : null;
        var made = TV.upload.compose(flight, job.name, {
          terrain: job.terrain, sceneTerrain: job.sceneTerrain, meteo: meteo,
          certificationTable: input.certification, now: input.now
        }, job.options);
        made.ok = true;
        out.push(made);
      } catch (error) { out.push({ ok: false, error: String(error && error.stack || error) }); }
    }, function (error) { out.push({ ok: false, error: String(error && error.stack || error) }); });
  });
}, Promise.resolve()).then(function () { process.stdout.write(JSON.stringify(out)); });

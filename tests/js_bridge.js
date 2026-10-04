/* The test suite's way into `tracklog_viewer/js/`: one JSON request on stdin —
 * { code, inputs } — run as the body of an async function with `TV`, `input`, `load`
 * and `fs` in scope, and its return value as JSON on stdout. Numbers JSON cannot carry
 * (NaN, ±Infinity) travel as {"$num": "NaN"} and come back as floats in Python. */
'use strict';
var fs = require('fs'), path = require('path'), zlib = require('zlib');
var JS = path.join(__dirname, '..', 'tracklog_viewer', 'js');
global.TV = {};
global.tzlookup = require(path.join(JS, 'vendor', 'tz-lookup.js'));
['np', 'geo', 'igc', 'flight', 'analysis', 'xc', 'metrics', 'debrief', 'sun', 'airmass', 'terrain',
 'insolation', 'plan', 'kml', 'certification', 'meteo', 'charts', 'scene', 'report', 'upload'].forEach(function (name) {
  require(path.join(JS, name + '.js'));
});
var inflate = { inflateRaw: function (b) { return Promise.resolve(new Uint8Array(zlib.inflateRawSync(b))); } };

// A file to a flight, through the page's own dispatch (`TV.upload.readBytes`).
function load(file, options) {
  return TV.upload.readBytes(new Uint8Array(fs.readFileSync(file)), path.basename(file),
                             Object.assign({}, inflate, options || {}));
}

var request = JSON.parse(fs.readFileSync(0, 'utf8'));
var AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
var body = new AsyncFunction('TV', 'input', 'load', 'fs', request.code);
body(TV, request.inputs, load, fs).then(function (value) {
  process.stdout.write(JSON.stringify({ ok: true, value: value === undefined ? null : value },
    function (key, x) { return typeof x === 'number' && !isFinite(x) ? { $num: String(x) } : x; }));
}, function (error) {
  process.stdout.write(JSON.stringify({ ok: false, error: String(error && error.stack || error),
                                        message: String(error && error.message || error) }));
});

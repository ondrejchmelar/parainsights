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
['np', 'geo', 'igc', 'flight', 'analysis'].forEach(function (name) {
  require(path.join(__dirname, name + '.js'));
});

var input = JSON.parse(fs.readFileSync(0, 'utf8'));
var out = input.map(function (job) {
  try {
    var text = fs.readFileSync(job.path, 'utf8');
    var flight = TV.igc.parse(text, {
      positionZone: job.positionZone ? function () { return job.positionZone; } : null
    });
    return { ok: true, result: TV.analysis.toDict(TV.analysis.analyse(flight)) };
  } catch (error) {
    return { ok: false, error: String(error && error.stack || error) };
  }
});
process.stdout.write(JSON.stringify(out));

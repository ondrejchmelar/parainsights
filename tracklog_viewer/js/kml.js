/* A flight out of KML or KMZ: `tracklog_viewer/kml.py`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * `gx:Track` first (alternating <when> and <gx:coord>), then timed placemarks — the
 * shapes XContest and igc2kmz write. A KML records one altitude and never says which
 * datum, so it is treated as GPS, and there is no pressure altitude at all.
 *
 * The XML and the ZIP are read here rather than by the browser: `DOMParser` does not
 * exist in Node, where the build and the tests run this, and the reading
 * the analysis needs — element names, their first text, document order — is small. KMZ
 * decompression is the one thing borrowed: `options.inflateRaw(bytes) → Promise<bytes>`,
 * which defaults to the browser's `DecompressionStream('deflate-raw')`.
 */
(function (TV) {
  'use strict';
  var np = TV.np, igc = TV.igc;

  function NoTrackError(message) { var e = new Error(message); e.name = 'NoTrackError'; return e; }

  // ---- XML ---------------------------------------------------------------------------
  var ENTITIES = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" };
  function decode(text) {
    return text.replace(/&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);/g, function (all, code) {
      if (code[0] === '#') {
        var n = code[1] === 'x' || code[1] === 'X' ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
        return String.fromCodePoint(n);
      }
      return ENTITIES[code] !== undefined ? ENTITIES[code] : all;
    });
  }
  var TOKEN = /<!--[\s\S]*?-->|<!\[CDATA\[([\s\S]*?)\]\]>|<\?[\s\S]*?\?>|<!DOCTYPE[^>]*>|<\/([^\s>]+)\s*>|<([^\s>\/!?]+)((?:\s+[^\s=>\/]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*(\/?)>|([^<]+)|(<)/g;

  // Elements as { name (local), text (before the first child), children }.
  function parseXml(text) {
    var root = null, stack = [], m;
    TOKEN.lastIndex = 0;
    function addText(value) {
      var top = stack[stack.length - 1];
      if (top && !top.children.length) top.text += value;
    }
    while ((m = TOKEN.exec(text))) {
      if (m[7]) throw new Error('stray < at ' + m.index);
      if (m[1] !== undefined) { addText(m[1]); continue; }
      if (m[6] !== undefined) { addText(decode(m[6])); continue; }
      if (m[2] !== undefined) {
        var closing = m[2].split(':').pop(), open = stack.pop();
        if (!open || open.name !== closing) throw new Error('mismatched </' + m[2] + '>');
        continue;
      }
      if (m[3] !== undefined) {
        var element = { name: m[3].split(':').pop(), text: '', children: [] };
        if (stack.length) stack[stack.length - 1].children.push(element);
        else if (root) throw new Error('more than one root element');
        else root = element;
        if (!m[5]) stack.push(element);
      }
    }
    if (!root || stack.length) throw new Error('unclosed element');
    return root;
  }
  // Document order, the element itself first — ElementTree's iter().
  function iter(element, out) {
    out = out || [];
    out.push(element);
    element.children.forEach(function (c) { iter(c, out); });
    return out;
  }
  function textOf(element) { return element.text.trim(); }

  // ---- ZIP ---------------------------------------------------------------------------
  function u16(b, o) { return b[o] | (b[o + 1] << 8); }
  function u32(b, o) { return (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16)) + b[o + 3] * 16777216; }
  function defaultInflate(bytes) {
    var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Response(stream).arrayBuffer().then(function (buffer) { return new Uint8Array(buffer); });
  }
  // The first .kml in the archive's own order, as Google Earth and the Python both take.
  function kmlFromZip(bytes, inflateRaw) {
    var end = -1;
    for (var i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
      if (u32(bytes, i) === 0x06054b50) { end = i; break; }
    }
    if (end < 0) return Promise.reject(NoTrackError('not a readable KMZ archive'));
    var count = u16(bytes, end + 10), at = u32(bytes, end + 16), entry = null;
    for (var k = 0; k < count; k++) {
      if (u32(bytes, at) !== 0x02014b50) break;
      var nameLength = u16(bytes, at + 28), extra = u16(bytes, at + 30), comment = u16(bytes, at + 32);
      var name = new TextDecoder('utf-8').decode(bytes.subarray(at + 46, at + 46 + nameLength));
      if (/\.kml$/i.test(name)) {
        entry = { method: u16(bytes, at + 10), size: u32(bytes, at + 20), offset: u32(bytes, at + 42) };
        break;
      }
      at += 46 + nameLength + extra + comment;
    }
    if (!entry) return Promise.reject(NoTrackError('KMZ contains no .kml document'));
    var local = entry.offset, start = local + 30 + u16(bytes, local + 26) + u16(bytes, local + 28);
    var data = bytes.subarray(start, start + entry.size);
    var body = entry.method === 0 ? Promise.resolve(data) : (inflateRaw || defaultInflate)(data);
    return body.then(function (raw) { return new TextDecoder('utf-8').decode(raw); });
  }

  // ---- the track ---------------------------------------------------------------------
  // KML timestamps are ISO 8601, usually with a Z, sometimes with an offset; whole
  // seconds, as numpy's datetime64[s] truncates them.
  var WHEN_RE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?)?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$/;
  function parseWhen(value) {
    var m = WHEN_RE.exec(value.trim());
    if (!m) return null;
    var seconds = Date.UTC(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0)) / 1000;
    if (m[8] && m[8] !== 'Z') {
      var sign = m[8][0] === '-' ? -1 : 1, digits = m[8].slice(1).replace(':', '');
      seconds -= sign * (parseInt(digits.slice(0, 2), 10) * 3600 + parseInt(digits.slice(2) || '0', 10) * 60);
    }
    return seconds;
  }

  var COORD_RE = /(-?\d+(?:\.\d+)?)[,\s]+(-?\d+(?:\.\d+)?)(?:[,\s]+(-?\d+(?:\.\d+)?))?/;

  function fromGxTrack(root) {
    var fixes = [];
    iter(root).forEach(function (element) {
      if (element.name !== 'Track') return;
      var whens = [], coords = [];
      element.children.forEach(function (child) {
        if (child.name === 'when') whens.push(parseWhen(textOf(child)));
        else if (child.name === 'coord') {
          var parts = textOf(child).split(/\s+/).filter(Boolean);
          if (parts.length >= 2) coords.push([parseFloat(parts[0]), parseFloat(parts[1]), parts.length > 2 ? parseFloat(parts[2]) : 0.0]);
        }
      });
      for (var i = 0; i < Math.min(whens.length, coords.length); i++) {
        if (whens[i] !== null) fixes.push([whens[i], coords[i][1], coords[i][0], coords[i][2]]);
      }
    });
    return fixes;
  }

  function fromTimedPlacemarks(root) {
    var fixes = [];
    iter(root).forEach(function (element) {
      if (element.name !== 'Placemark') return;
      var when = null, position = null;
      iter(element).forEach(function (node) {
        if ((node.name === 'when' || node.name === 'begin') && when === null) when = parseWhen(textOf(node));
        else if (node.name === 'coordinates' && position === null) {
          var m = COORD_RE.exec(textOf(node));
          if (m) position = [parseFloat(m[1]), parseFloat(m[2]), m[3] ? parseFloat(m[3]) : 0.0];
        }
      });
      if (when !== null && position !== null) fixes.push([when, position[1], position[0], position[2]]);
    });
    return fixes;
  }

  // `name` is the file's name, for the fallback title and the warning; `options` as
  // igc.parse (positionZone, filterFixes).
  function parseText(document, name, options) {
    options = options || {};
    var root;
    try { root = parseXml(document); } catch (error) { throw NoTrackError(name + ': not parseable XML (' + error.message + ')'); }
    var fixes = fromGxTrack(root), source = 'gx:Track';
    if (!fixes.length) { fixes = fromTimedPlacemarks(root); source = 'timed placemarks'; }
    if (fixes.length < 2) {
      throw NoTrackError(name + ': no timed positions found. A KML holding only a LineString has no ' +
                         'timestamps, so climb rates and phases cannot be derived — use the IGC.');
    }
    fixes.sort(function (a, b) { return a[0] - b[0]; });
    var times = fixes.map(function (f) { return f[0]; });
    var alt = fixes.map(function (f) { return f[3]; });
    var title = null;
    iter(root).some(function (node) { if (node.name === 'name' && textOf(node)) { title = textOf(node); return true; } return false; });
    var stem = name.replace(/^.*[\\/]/, '').replace(/\.[^.]*$/, '');
    var d0 = new Date(times[0] * 1000);
    var headers = { manufacturer: 'KML', logger_id: null,
                    date: { year: d0.getUTCFullYear(), month: d0.getUTCMonth() + 1, day: d0.getUTCDate() },
                    flight_of_day: null, pilot: null, glider_type: null, glider_id: null, site: null,
                    logger_type: (title || stem) + ' (' + source + ')', firmware: null,
                    competition_class: null, pressure_sensor: null, raw: {} };
    var suffix = (/\.([^.\\/]*)$/.exec(name) || [, ''])[1].toUpperCase();
    var interval = times.length < 2 ? 0.0 : np.median(np.diff(times));
    var flight = {
      headers: headers, time: times, lat: fixes.map(function (f) { return f[1]; }),
      lon: fixes.map(function (f) { return f[2]; }), alt_baro: alt.map(function () { return 0; }),
      alt_gps: alt, validity: alt.map(function () { return true; }), extensions: {},
      timezone: null, timezone_source: null, task: [],
      warnings: ['read from ' + suffix + ' via ' + source + ': ' + fixes.length + ' points at ~' +
                 np.fmt(interval, 0) + ' s, no pressure altitude'],
      dropped: {}
    };
    var byPosition = options.positionZone || igc.defaultZone;
    if (byPosition) {
      var zone = byPosition(flight.lat[0], flight.lon[0]);
      if (zone) { flight.timezone = { iana: zone }; flight.timezone_source = 'position (' + zone + ')'; }
    }
    return options.filterFixes === false ? flight : igc.filterBadFixes(flight);
  }

  // Raw KML or a KMZ archive, as bytes; resolves to a flight.
  function parseBytes(bytes, name, options) {
    options = options || {};
    var isZip = bytes[0] === 0x50 && bytes[1] === 0x4b;
    var document = isZip ? kmlFromZip(bytes, options.inflateRaw)
                         : Promise.resolve(new TextDecoder('utf-8').decode(bytes));
    return document.then(function (text) { return parseText(text, name, options); });
  }

  TV.kml = { parseXml: parseXml, parseText: parseText, parseBytes: parseBytes, parseWhen: parseWhen,
             NoTrackError: NoTrackError };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

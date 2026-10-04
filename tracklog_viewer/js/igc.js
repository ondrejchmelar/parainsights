/* IGC tracklog parsing: `tracklog_viewer/igc.py`, ported.
 *
 * Every logger quirk lives here. Times are UTC epoch seconds; the timezone is resolved
 * once and carried as `{ iana: name }` or `{ offsetHours: h }` (or null for UTC), which
 * `localParts` turns into a clock reading the way Python's `astimezone` does.
 *
 * The zone from the take-off position is Python's `timezonefinder` there and tz-lookup
 * here (`defaultZone`). `options.positionZone(lat, lon)` overrides it — the parity
 * harness passes Python's own answer, so the comparison is of the analysis rather than
 * of two boundary datasets.
 */
(function (TV) {
  'use strict';
  var np = TV.np, geo = TV.geo;

  var B_RE = /^B(\d{2})(\d{2})(\d{2})(\d{2})(\d{5})([NS])(\d{3})(\d{5})([EW])([AV])(-\d{4}|\d{5})(-\d{4}|\d{5})/;
  var HFDTE_RE = /^H.DTE(?:DATE:)?(\d\d)(\d\d)(\d\d)(?:,(\d\d))?\s*$/;
  var H_RE = /^H([\s\S])([0-9A-Z]{3})([^:]*)(?::([\s\S]*))?$/;
  var I_RE = /^I(\d{2})([\s\S]*)$/;
  var I_FIELD_RE = /(\d{2})(\d{2})([A-Z]{3})/g;
  var C_TASK_RE = /^C(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{6}|-{6})(\d{2})(\d{2})(.*)$/;
  var C_TP_RE = /^C(\d{2})(\d{5})([NS])(\d{3})(\d{5})([EW])(.*)$/;
  var LXCT_DEVICE_RE = /^L(?:XCT)?DEVICE\s?(.*)$/;
  var TZ_OFFSET_RE = /([-+]?\d+(?:\.\d+)?)\s*$/;
  var NOT_SET_RE = /^\s*(not\s+set|n\/?a|\?|-+)?\s*$/i;
  var DIGITS_RE = /^[0-9]+$/;

  var FILTER_MAX_GROUND_SPEED = 100.0;   // m/s

  function clean(value) {
    if (value === null || value === undefined) return null;
    value = value.trim();
    return NOT_SET_RE.test(value) ? null : value;
  }

  // ---- clock ------------------------------------------------------------------------
  var formatters = {};
  function zoneExists(name) {
    try { new Intl.DateTimeFormat('en-GB', { timeZone: name }); return true; }
    catch (error) { return false; }
  }
  function utcParts(seconds) {
    var d = new Date(seconds * 1000);
    return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate(),
             hour: d.getUTCHours(), minute: d.getUTCMinutes(), second: d.getUTCSeconds() };
  }
  // The wall clock at `seconds` (UTC epoch) in `zone`.
  function localParts(seconds, zone) {
    if (!zone) return utcParts(seconds);
    if (zone.offsetHours !== undefined) return utcParts(seconds + zone.offsetHours * 3600);
    var f = formatters[zone.iana] || (formatters[zone.iana] = new Intl.DateTimeFormat('en-GB', {
      timeZone: zone.iana, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    }));
    var out = {};
    f.formatToParts(new Date(seconds * 1000)).forEach(function (p) {
      if (p.type !== 'literal') out[p.type] = parseInt(p.value, 10);
    });
    return out;
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function clock(seconds, zone) {
    var p = localParts(seconds, zone);
    return pad(p.hour) + ':' + pad(p.minute) + ':' + pad(p.second);
  }
  function isoDate(seconds, zone) {
    var p = localParts(seconds, zone);
    return p.year + '-' + pad(p.month) + '-' + pad(p.day);
  }

  // ---- records ----------------------------------------------------------------------
  function parseIRecord(line) {
    var m = I_RE.exec(line);
    if (!m) return {};
    var fields = {}, f;
    I_FIELD_RE.lastIndex = 0;
    while ((f = I_FIELD_RE.exec(m[2]))) fields[f[3]] = [parseInt(f[1], 10) - 1, parseInt(f[2], 10)];
    return fields;
  }

  var SETTERS = { PLT: 'pilot', GTY: 'glider_type', GID: 'glider_id', SIT: 'site',
                  FTY: 'logger_type', RFW: 'firmware', CCL: 'competition_class',
                  PRS: 'pressure_sensor' };

  function parseHeader(line, headers) {
    var d = HFDTE_RE.exec(line);
    if (d) {
      var year = parseInt(d[3], 10);
      year += year < 80 ? 2000 : 1900;
      var month = parseInt(d[2], 10), day = parseInt(d[1], 10);
      var stamp = Date.UTC(year, month - 1, day);
      var back = new Date(stamp);
      if (month < 1 || month > 12 || back.getUTCDate() !== day || back.getUTCMonth() !== month - 1) {
        throw new Error('invalid date in ' + JSON.stringify(line));
      }
      headers.date = { year: year, month: month, day: day };
      if (d[4] !== undefined) headers.flight_of_day = parseInt(d[4], 10);
      return;
    }
    var m = H_RE.exec(line);
    if (!m) throw new Error('unparseable H record ' + JSON.stringify(line));
    var code = m[2];
    var value = m[4] !== undefined ? m[4] : m[3];
    headers.raw[code] = (value || '').trim();
    if (SETTERS[code]) headers[SETTERS[code]] = clean(value);
  }

  // XCTrack's base64 device JSON, split over L records. Python decodes with
  // validate=False, which skips anything outside the alphabet and tolerates excess
  // padding; `atob` does neither, so this does it by hand.
  function base64Bytes(text) {
    var alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
    var data = text.split('=')[0].replace(/[^A-Za-z0-9+/]/g, '');
    if (data.length % 4 === 1) throw new Error('bad base64');
    var bytes = [], buffer = 0, bits = 0;
    for (var i = 0; i < data.length; i++) {
      buffer = (buffer << 6) | alphabet.indexOf(data[i]);
      bits += 6;
      if (bits >= 8) { bits -= 8; bytes.push((buffer >> bits) & 0xff); }
    }
    return new Uint8Array(bytes);
  }
  function zoneFromLRecords(lines) {
    var chunks = [];
    lines.forEach(function (line) { var m = LXCT_DEVICE_RE.exec(line); if (m) chunks.push(m[1]); });
    if (!chunks.length) return null;
    try {
      var json = JSON.parse(new TextDecoder('utf-8').decode(base64Bytes(chunks.join(''))));
      var name = json.os.timezone;
      if (typeof name !== 'string' || !zoneExists(name)) return null;
      return { zone: { iana: name }, source: 'LXCTDEVICE (' + name + ')' };
    } catch (error) {
      return null;
    }
  }
  function formatG(x) { return String(Math.abs(x)); }
  function zoneFromHeader(headers) {
    var raw = headers.raw.TZN;
    if (!raw) return null;
    var m = TZ_OFFSET_RE.exec(raw);
    if (!m) return null;
    var hours = parseFloat(m[1]);
    return { zone: { offsetHours: hours },
             source: 'HFTZN (' + (hours < 0 || Object.is(hours, -0) ? '-' : '+') + formatG(hours) + ')' };
  }

  // The zone at a take-off when the file does not say: tz-lookup (js/vendor), where the
  // page has loaded it. It gives the same clock as Python's timezonefinder at all 136
  // sample take-offs, and the same zone name at 131 — the rest name a neighbour with the
  // same offset (Europe/Bratislava for Europe/Prague).
  function defaultZone(lat, lon) {
    var lookup = typeof tzlookup === 'function' ? tzlookup : null;
    if (!lookup) return null;
    try { return lookup(lat, lon); } catch (error) { return null; }
  }

  function parse(text, options) {
    options = options || {};
    var filterFixes = options.filterFixes !== false;
    var lines = text.split(/\r\n|\r|\n/);
    var headers = { manufacturer: null, logger_id: null, date: null, flight_of_day: null,
                    pilot: null, glider_type: null, glider_id: null, site: null,
                    logger_type: null, firmware: null, competition_class: null,
                    pressure_sensor: null, raw: {} };
    var extensionFields = {}, lRecords = [], task = [], warnings = [];
    var times = [], lats = [], lons = [], baros = [], gpss = [], valids = [], rawExt = {};
    var date = null, previousSeconds = null, dayOffset = 0;
    // The I record's columns, held as a list rather than walked as an object on every B
    // record: a five-hour file is 40 000 of them, and the per-fix closures were most of
    // the parse.
    var extCodes = [], extRanges = [], ladRange = null, lodRange = null;

    for (var n = 0; n < lines.length; n++) {
      var line = lines[n].trimEnd();
      if (!line) continue;
      var record = line[0];
      if (record === 'A') {
        headers.manufacturer = line.slice(1, 4) || null;
        headers.logger_id = line.slice(4).trim() || null;
      } else if (record === 'H') {
        try { parseHeader(line, headers); } catch (error) { warnings.push(error.message); }
        // Python resets its working date on *every* H record once one is known, which
        // also undoes any midnight rollover counted so far; so does this.
        if (headers.date) { date = headers.date; dayOffset = 0; }
      } else if (record === 'I') {
        extensionFields = parseIRecord(line);
        rawExt = {};
        extCodes = Object.keys(extensionFields);
        extRanges = extCodes.map(function (code) { rawExt[code] = []; return extensionFields[code]; });
        ladRange = extensionFields.LAD || null;
        lodRange = extensionFields.LOD || null;
      } else if (record === 'L') {
        lRecords.push(line);
      } else if (record === 'C') {
        if (C_TASK_RE.test(line)) continue;
        var c = C_TP_RE.exec(line);
        if (c) {
          var tlat = parseInt(c[1], 10) + parseInt(c[2], 10) / 60000;
          if (c[3] === 'S') tlat = -tlat;
          var tlon = parseInt(c[4], 10) + parseInt(c[5], 10) / 60000;
          if (c[6] === 'W') tlon = -tlon;
          if (tlat || tlon) task.push({ name: c[7].trim(), lat: tlat, lon: tlon });
        }
      } else if (record === 'B') {
        var b = B_RE.exec(line);
        if (!b) { warnings.push('unparseable B record ' + JSON.stringify(line)); continue; }
        if (!date) {
          warnings.push('B record before HFDTE; assuming 1970-01-01');
          date = { year: 1970, month: 1, day: 1 };
          headers.date = date;
        }
        var hh = parseInt(b[1], 10), mm = parseInt(b[2], 10), ss = parseInt(b[3], 10);
        var timeOfDay = hh * 3600 + mm * 60 + ss;
        if (previousSeconds !== null && timeOfDay < previousSeconds - 43200) dayOffset += 1;
        previousSeconds = timeOfDay;

        var lat = parseInt(b[4], 10) + parseInt(b[5], 10) / 60000;
        var lon = parseInt(b[7], 10) + parseInt(b[8], 10) / 60000;
        if (ladRange) {
          var ladDigits = line.slice(ladRange[0], ladRange[1]);
          if (DIGITS_RE.test(ladDigits)) lat += parseInt(ladDigits, 10) / (60000 * Math.pow(10, ladDigits.length));
        }
        if (lodRange) {
          var lodDigits = line.slice(lodRange[0], lodRange[1]);
          if (DIGITS_RE.test(lodDigits)) lon += parseInt(lodDigits, 10) / (60000 * Math.pow(10, lodDigits.length));
        }
        if (b[6] === 'S') lat = -lat;
        if (b[9] === 'W') lon = -lon;

        if (hh > 23 || mm > 59 || ss > 59) {
          warnings.push('impossible time in ' + JSON.stringify(line));
          previousSeconds = null;
          continue;
        }
        times.push(Date.UTC(date.year, date.month - 1, date.day + dayOffset, hh, mm, ss) / 1000);
        lats.push(lat);
        lons.push(lon);
        valids.push(b[10] === 'A');
        baros.push(parseInt(b[11], 10));
        gpss.push(parseInt(b[12], 10));
        for (var e = 0; e < extCodes.length; e++) {
          var extDigits = line.slice(extRanges[e][0], extRanges[e][1]);
          rawExt[extCodes[e]].push(DIGITS_RE.test(extDigits) ? parseInt(extDigits, 10) : null);
        }
      }
    }
    if (!times.length) throw new Error('no valid B records');

    var extensions = {};
    Object.keys(rawExt).forEach(function (code) {
      if (code === 'LAD' || code === 'LOD') return;
      if (!rawExt[code].some(function (v) { return v; })) return;
      extensions[code] = rawExt[code].map(function (v) { return v === null ? NaN : v; });
    });

    var flight = { headers: headers, time: times, lat: lats, lon: lons, alt_baro: baros,
                   alt_gps: gpss, validity: valids, extensions: extensions, timezone: null,
                   timezone_source: null, task: task, warnings: warnings, dropped: {} };

    var resolved = zoneFromLRecords(lRecords) || zoneFromHeader(headers);
    var byPosition = options.positionZone || defaultZone;
    if (!resolved) {
      var name = byPosition(lats[0], lons[0]);
      if (name && zoneExists(name)) resolved = { zone: { iana: name }, source: 'position (' + name + ')' };
    }
    if (resolved) { flight.timezone = resolved.zone; flight.timezone_source = resolved.source; }
    return filterFixes ? filterBadFixes(flight) : flight;
  }

  // ---- flight helpers ----------------------------------------------------------------
  function hasBaro(flight) { return flight.alt_baro.some(function (v) { return v !== 0; }); }
  function altitude(flight) { return hasBaro(flight) ? flight.alt_baro : flight.alt_gps; }
  function baroOffset(flight) {
    if (!hasBaro(flight)) return null;
    return np.median(flight.alt_gps.map(function (g, i) { return g - flight.alt_baro[i]; }));
  }

  // A sample more than `threshold` metres off the median of its five neighbours is
  // receiver noise at 1 Hz: repaired to that median, not dropped.
  function despikeAltitude(alt, window, threshold) {
    window = window || 5;
    threshold = threshold === undefined ? 30.0 : threshold;
    if (alt.length < window) return { alt: alt, count: 0 };
    var half = window >> 1, n = alt.length, out = alt.slice(), count = 0;
    for (var i = 0; i < n; i++) {
      var w = [];
      for (var k = i - half; k <= i + half; k++) w.push(alt[Math.min(Math.max(k, 0), n - 1)]);
      var m = np.median(w);
      if (Math.abs(alt[i] - m) > threshold) { out[i] = m; count++; }
    }
    return { alt: count ? out : alt, count: count };
  }

  function filterBadFixes(flight) {
    var n = flight.time.length, keep = new Array(n).fill(false), dropped = {};
    function bump(key, by) { dropped[key] = (dropped[key] || 0) + (by === undefined ? 1 : by); }
    keep[0] = true;
    var last = 0;
    for (var i = 1; i < n; i++) {
      var gap = flight.time[i] - flight.time[last];
      if (gap <= 0) { bump('duplicate or backwards timestamp'); continue; }
      var ground = geo.distance(flight.lat[last], flight.lon[last], flight.lat[i], flight.lon[i]);
      if (ground / gap > FILTER_MAX_GROUND_SPEED) { bump('implausible ground speed'); continue; }
      keep[i] = true;
      last = i;
    }
    function pick(a) { return a.filter(function (_, j) { return keep[j]; }); }
    var gps = despikeAltitude(pick(flight.alt_gps));
    if (gps.count) bump('GPS altitude spikes repaired', gps.count);
    var baro = pick(flight.alt_baro);
    if (hasBaro(flight)) {
      var b = despikeAltitude(baro);
      baro = b.alt;
      if (b.count) bump('baro altitude spikes repaired', b.count);
    }
    if (!Object.keys(dropped).length) return flight;
    var extensions = {};
    Object.keys(flight.extensions).forEach(function (code) { extensions[code] = pick(flight.extensions[code]); });
    return { headers: flight.headers, time: pick(flight.time), lat: pick(flight.lat),
             lon: pick(flight.lon), alt_baro: baro, alt_gps: gps.alt,
             validity: pick(flight.validity), extensions: extensions, timezone: flight.timezone,
             timezone_source: flight.timezone_source, task: flight.task,
             warnings: flight.warnings, dropped: dropped };
  }

  TV.igc = { parse: parse, defaultZone: defaultZone, filterBadFixes: filterBadFixes, despikeAltitude: despikeAltitude,
             hasBaro: hasBaro, altitude: altitude, baroOffset: baroOffset,
             localParts: localParts, clock: clock, isoDate: isoDate };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

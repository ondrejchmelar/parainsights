/* One flight's article, from masthead to footer — for an uploaded track in the page, and
 * for the report's own flights at build time (`js_build.py`), through `TV.upload.compose`.
 * Ported from `render_html._flight_body` and its helpers, and held to the same markup,
 * sentences and numbers until the Python was retired (it is in git at `ada5e5b`).
 * Where the article reads the clock (the weather archive's reach), `now` is a parameter.
 *
 * `options`: meteo (TV.meteo.parse), route (TV.xc), terrain (a grid with `z`, for the
 * clearance and the faces), sceneTerrain (what the 3D payload carries; the grid itself
 * by default), uid, hidden, flightPlan, airspace, certificationTable, now (epoch seconds).
 */
(function (TV) {
  'use strict';
  var np = TV.np, geo = TV.geo, igc = TV.igc, A = TV.analysis, M = TV.metrics, Ch = TV.charts, Met = TV.meteo;
  var fmt = np.fmt, R = np.pyRound, esc = Ch.escape;

  var SHAPE_LABEL = { fai: 'FAI triangle', flat: 'flat triangle', open: 'free distance, 3 turnpoints' };
  var RECENT_DAYS = 60;

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function duration(seconds) {
    seconds = Math.trunc(seconds);
    var hours = Math.floor(seconds / 3600), rest = seconds % 3600, minutes = Math.floor(rest / 60), secs = rest % 60;
    return hours ? hours + ' h ' + pad(minutes) + ' m' : minutes + ' m ' + pad(secs) + ' s';
  }
  function shortDuration(seconds) {
    seconds = Math.trunc(seconds);
    return Math.floor(seconds / 60) + ':' + pad(seconds % 60);
  }
  function spaced(value) { return fmt(value, 0, { thousands: ' ' }); }
  // str() of a Python float: an integral value keeps its ".0".
  function pyFloat(value) { return Number.isInteger(value) ? value.toFixed(1) : String(value); }
  // The climb rate through one climb, every fix, to a tenth of a m/s: what the row's
  // sparkline is drawn from in the page (`charts_client.SCRIPT`, `sparks`). The data, not
  // the drawing — the bars are bucketed and coloured where they are shown.
  function sparkSeries(series, start, stop) {
    return series.climb.slice(start, stop).map(function (v) { return String(Math.round(v * 10) / 10); }).join(',');
  }
  function thermals(a) { return a.segments.filter(function (s) { return s.phase === 'thermal'; }); }
  function glides(a) { return a.segments.filter(function (s) { return s.phase === 'glide'; }); }

  function sampleIndices(a) {
    var total = a.series.t.length, step = Math.max(Math.floor(total / 900), 1), out = [];
    for (var i = 0; i < total; i += step) out.push(i);
    return out;
  }

  // `clearance` (per fix, `TV.terrain.clearance`) adds the height above the ground where
  // the report has an elevation model.
  function cursorData(a, clearance) {
    var s = a.series, f = a.flight, indices = sampleIndices(a), phaseOf = {};
    a.segments.forEach(function (seg) { for (var i = seg.start; i < seg.stop; i++) phaseOf[i] = seg; });
    var floor = Math.floor(np.min(s.alt) / 250) * 250, ceiling = Math.ceil(np.max(s.alt) / 250) * 250;
    var top = 16, plotH = 300 - top - 34;
    function screenY(v) { return top + plotH * (1 - (v - floor) / Math.max(ceiling - floor, 1)); }
    var gpsAlt = f.alt_gps.some(function (v) { return v !== 0; }) ? f.alt_gps : s.alt;
    return {
      t: indices.map(function (i) { return s.t[i]; }),
      y: indices.map(function (i) { return R(screenY(s.alt[i]), 1); }),
      alt: indices.map(function (i) { return Math.trunc(s.alt[i]); }),
      climb: indices.map(function (i) { return R(s.climb[i], 2); }),
      speed: indices.map(function (i) { return Math.trunc(s.speed[i]); }),
      clock: indices.map(function (i) { return igc.clock(f.time[i], f.timezone); }),
      phase: indices.map(function (i) { return phaseOf[i] ? phaseOf[i].phase : 'cruise'; }),
      segment: indices.map(function (i) { return phaseOf[i] ? phaseOf[i].start : null; }),
      agl: clearance ? indices.map(function (i) { return Math.round(clearance[i]); }) : null,
      cursor3d: {
        lon: indices.map(function (i) { return R(f.lon[i], 5); }),
        lat: indices.map(function (i) { return R(f.lat[i], 5); }),
        alt: indices.map(function (i) { return Math.trunc(gpsAlt[i]); }),
        min: indices.map(function (i) { var d = new Date(f.time[i] * 1000); return d.getUTCHours() * 60 + d.getUTCMinutes(); })
      }
    };
  }

  function rowCursor(sample, fix) { return sample && sample.length ? ' data-cursor="' + Ch.samplePosition(sample, fix) + '"' : ''; }

  // The ⓘ, the same markup as `parainsights_common.info`: a circled i straight after the
  // label it explains, its text in a bubble (`prefs.js` shows it). `text` is HTML.
  function info(text, label) {
    if (!text) return '';
    return '<span class="info-wrap"><button type="button" class="info" aria-expanded="false" aria-label="' +
      esc(label || 'More about this') + '">i</button><span class="info-pop" role="note">' + text + '</span></span>';
  }
  function cap(text) { return text ? text.charAt(0).toUpperCase() + text.slice(1) : text; }

  // One of the key numbers: the value, its label and, in grey under it, this flight's
  // detail. What the number *means* is the same on every flight, so it is in the flight's
  // "Sources and method" fold, not here (October 2026). `key` names it for the
  // comparison, which writes into the `.verdict-delta` slot.
  function figure(label, value, unit, detail, key) {
    return '<div class="fig"' + (key ? ' data-key="' + key + '"' : '') + '><span class="v">' + value +
      (unit ? '<small>' + unit + '</small>' : '') + '</span><span class="k">' + label + '</span>' +
      (detail ? '<span class="d">' + detail + '</span>' : '') + (key ? '<span class="verdict-delta" hidden></span>' : '') + '</div>';
  }

  // One ⓘ for a whole section: a term per line, each a sentence at most. Only the
  // definitions that hold on every flight go here; what is particular to this flight is
  // printed, not hidden.
  function glossary(terms) {
    return '<dl class="gloss">' + terms.filter(Boolean).map(function (t) { return '<dt>' + t[0] + '</dt><dd>' + t[1] + '</dd>'; }).join('') + '</dl>';
  }

  function stat(key, value, unit, sub) {
    var unitHtml = unit ? '<small>' + unit + '</small>' : '', subHtml = sub ? '<span class="sub">' + sub + '</span>' : '';
    return '<div class="stat"><span class="key">' + key + '</span><span class="stat-value">' + value + unitHtml + '</span>' + subHtml + '</div>';
  }

  function sourceTitle(source) {
    return [fmt(source.clearance, 0) + ' m above the ground',
            source.slope !== null ? fmt(source.slope, 0) + '° slope' : '',
            source.turn_rate !== null ? fmt(source.turn_rate, 1) + ' circles a minute' : '',
            source.offset !== null ? 'face ' + fmt(source.offset, 0) + '° off the wind' : ''].filter(Boolean).join(', ');
  }

  function clearanceNote(clearance) {
    var w = M.airborneWindow(clearance);
    if (!w) return '';
    var inside = clearance.slice(w[0], w[1]), median = np.median(inside), low = np.min(inside);
    if (low < 0) {
      return 'Median height over the ground directly beneath you was ' + fmt(median, 0) + '&nbsp;m &mdash; the launch and the landing are left out, or both would win by being on the ground.';
    }
    return 'Lowest height over the ground directly beneath you was ' + fmt(low, 0) + '&nbsp;m, median ' + fmt(median, 0) +
      '&nbsp;m &mdash; the launch and the landing are left out, or both would win by being on the ground.';
  }

  // The same facts as `clearanceNote` and `triggerNote`, as the debrief's context cards:
  // the number large, what it counts beside it, this flight's detail under it.
  function contextFacts(a, clearance, terrain) {
    var out = [], w = clearance ? M.airborneWindow(clearance) : null;
    if (w) {
      var inside = clearance.slice(w[0], w[1]), median = np.median(inside), low = np.min(inside);
      out.push({ value: fmt(median, 0) + '&nbsp;m', label: 'Median height over the ground directly beneath you',
                 detail: (low >= 0 ? 'Lowest ' + fmt(low, 0) + '&nbsp;m. ' : '') + 'Launch and landing left out.' });
    }
    if (!terrain) return out;
    var found = TV.insolation.triggers(a, terrain);
    if (found.length >= 3) {
      var lit = found.filter(function (t) { return t.face.relative > 1.05; }).length;
      var detail = '', hm = function (t) { return String(t).slice(0, 5); };
      var half = Math.floor(found.length / 2);
      if (half >= 2) {
        var early = found.slice(0, half), late = found.slice(found.length - half);
        var first = meanAspect(early.map(function (t) { return t.face.aspect; }));
        var second = meanAspect(late.map(function (t) { return t.face.aspect; }));
        var swing = np.mod(second - first + 540, 360) - 180;
        detail += Math.abs(swing) >= 30
          ? 'From ' + geo.cardinal(first) + '-facing (' + hm(early[0].at) + '&ndash;' + hm(early[early.length - 1].at) + ') to ' +
            geo.cardinal(second) + '-facing (' + hm(late[0].at) + '&ndash;' + hm(late[late.length - 1].at) + ').'
          : cap(geo.cardinal(first)) + '-facing from ' + hm(early[0].at) + ' to ' + hm(late[late.length - 1].at) + '.';
      }
      out.push({ value: lit + ' of ' + found.length, label: 'Climbs began over ground catching more sun than the slopes around it', detail: detail });
    }
    var breeze = TV.insolation.windward(a, terrain);
    if (breeze && breeze.total) {
      out.push({ value: breeze.windward + ' of ' + breeze.total, label: 'Climbs faced within 60&#176; of the measured wind — where ridge lift would be' });
    }
    return out;
  }

  function meanAspect(aspects) {
    var east = 0, north = 0;
    aspects.forEach(function (d) { east += Math.sin(d * np.DEG); });
    aspects.forEach(function (d) { north += Math.cos(d * np.DEG); });
    return np.mod(Math.atan2(east, north) * np.RAD, 360.0);
  }

  function triggerNote(a, terrain) {
    if (!terrain) return '';
    var found = TV.insolation.triggers(a, terrain);
    if (found.length < 3) return '';
    var lit = found.filter(function (t) { return t.face.relative > 1.05; }).length;
    var note = ' Of ' + found.length + ' climbs that started over sloping ground, ' + lit +
      ' began over ground catching more sun than the slopes around it.';
    var half = Math.floor(found.length / 2);
    if (half >= 2) {
      var early = found.slice(0, half), late = found.slice(found.length - half);
      var first = meanAspect(early.map(function (t) { return t.face.aspect; }));
      var second = meanAspect(late.map(function (t) { return t.face.aspect; }));
      var swing = np.mod(second - first + 540, 360) - 180;
      if (Math.abs(swing) >= 30) {
        note += ' The faces swung ' + (swing > 0 ? 'clockwise' : 'anticlockwise') + ' through the day, from ' +
          geo.cardinal(first) + '-facing early on (' + early[0].at + '&ndash;' + early[early.length - 1].at + ') to ' +
          geo.cardinal(second) + '-facing later (' + late[0].at + '&ndash;' + late[late.length - 1].at + ')' +
          (swing > 0 ? ', which is the sun going round' : '') + '.';
      } else {
        note += ' They stayed on ' + geo.cardinal(first) + '-facing ground from ' + early[0].at + ' to ' +
          late[late.length - 1].at + ' rather than following the sun round.';
      }
    }
    var breeze = TV.insolation.windward(a, terrain);
    if (breeze && breeze.total) {
      note += ' ' + breeze.windward + ' of ' + breeze.total + ' faced within 60&#176; of the measured wind, which is where ridge lift would be.';
    }
    return note;
  }

  function ceilingTile(a, meteo, peakTime, offset) {
    var summary = a.summary, use = M.ceilingUse(a, meteo && Met.weather(meteo));
    if (!use) {
      return ['max altitude', spaced(summary.max_altitude), ' m',
              'at ' + peakTime + (offset ? ' · ' + spaced(summary.max_altitude + offset) + ' m GPS' : '')];
    }
    return ['ceiling used', fmt(use.fraction, 0, { percent: true }), '',
            (spaced(use.reached) + ' m of a modelled ' + spaced(use.ceiling) + ' m ' + M.CEILING_NAMES[use.source]).replace(/,/g, ' '),
            use.source === 'cloudbase' ? 'Of cloudbase' : 'Of thermal top'];
  }

  function thermalRows(a, sample, sources) {
    var rows = [], number = 0, th = thermals(a);
    var bestClimb = th.length ? Math.max.apply(null, th.map(function (s) { return s.average_climb; })) : 1.0;
    a.segments.forEach(function (seg) {
      if (seg.phase !== 'thermal' && seg.phase !== 'tow') return;
      var label, tag;
      if (seg.phase === 'tow') { label = 'T'; tag = '<span class="tag tag-tow">Tow</span>'; }
      else { number += 1; label = String(number); tag = ''; }
      var source = sources && seg.phase === 'thermal' ? sources[number] : null;
      var sourceHtml = source && source.confident
        ? '<span class="tag tag-' + source.label + '" title="' + sourceTitle(source) + '">' + cap(source.label) + '</span>'
        : "<span class='dir'>—</span>";
      var width = 46 * Math.max(seg.average_climb, 0) / Math.max(bestClimb, 0.1);
      var turns = seg.turns !== null ? fmt(seg.turns, 1) : '—';
      var perTurn = seg.turns && seg.turns >= 0.5 ? fmt(seg.altitude_change / seg.turns, 0) : '—';
      var direction = seg.turn_direction ? "<span class='dir'>" + seg.turn_direction + '</span>' : "<span class='dir'>—</span>";
      var reversals = seg.reversals !== null ? String(seg.reversals) : '—';
      var circle = seg.circle_seconds ? fmt(seg.circle_seconds, 0) : '—';
      var radius = seg.circle_radius ? fmt(seg.circle_radius, 0) : '—';
      var efficiency = seg.efficiency !== null ? fmt(seg.efficiency, 0) + '%' : '—';
      rows.push('<tr data-segment="' + seg.start + '"' + rowCursor(sample, seg.start) + (seg.phase === 'tow' ? ' class=is-tow' : '') + '>' +
        '<td>' + label + ' ' + tag + '</td><td>' + seg.start_time + '</td><td>' + shortDuration(seg.duration) + '</td>' +
        '<td>' + fmt(seg.altitude_change, 0, { plus: true }) + '</td><td>' + fmt(seg.finish_altitude, 0) + '</td>' +
        '<td><span class="bar-cell">' + fmt(seg.average_climb, 2, { plus: true }) + '<span class="bar" style="width:' +
        fmt(width, 0) + 'px"></span></span></td><td>' + efficiency + '</td><td>' + sourceHtml + '</td>' +
        '<td class="circling-detail">' + turns + '</td><td class="circling-detail">' + perTurn + '</td>' +
        '<td class="circling-detail">' + direction + '</td><td class="circling-detail">' + reversals + '</td>' +
        '<td class="circling-detail">' + circle + '</td><td class="circling-detail">' + radius + '</td>' +
        '<td class="spark-cell" data-climb="' + sparkSeries(a.series, seg.start, seg.stop) + '"></td></tr>');
    });
    return rows.join('');
  }

  // Most glides are short hops between thermals; the longest few are the ones a pilot
  // looks for. Those stay in flight order and the rest are folded behind "Show all".
  var GLIDES_SHOWN = 8;
  function glideRows(a, sample) {
    var gl = glides(a);
    var best = gl.length ? Math.max.apply(null, gl.map(function (s) { return s.average_ld || 0; })) : 1.0;
    var longest = gl.slice().sort(function (x, y) { return y.distance - x.distance; }).slice(0, GLIDES_SHOWN);
    return gl.map(function (seg, i) {
      var ld = seg.average_ld ? fmt(seg.average_ld, 1) : '—';
      var extra = gl.length > GLIDES_SHOWN && longest.indexOf(seg) < 0;
      return '<tr data-segment="' + seg.start + '"' + rowCursor(sample, seg.start) + (extra ? ' class="is-extra"' : '') + '><td>' + (i + 1) + '</td>' +
        '<td>' + seg.start_time + '</td><td>' + shortDuration(seg.duration) + '</td><td>' + fmt(seg.distance / 1000, 1) + '</td>' +
        '<td><span class="bar-cell">' + ld + Ch.ldBar(seg.average_ld, best) + '</span></td><td>' + fmt(seg.average_speed, 0) + '</td></tr>';
    }).join('');
  }

  var SHEAR_NOTICEABLE = 1.0;  // m/s, as render_html.SHEAR_NOTICEABLE

  function windShearNote(a) {
    var sounded = thermals(a).filter(function (s) { return s.wind && s.turns && s.turns >= 2; })
      .map(function (s) { return [(s.start_altitude + s.finish_altitude) / 2, s.wind]; });
    if (sounded.length < 3) return 'Too few circled climbs to see a trend with height.';
    sounded.sort(function (x, y) { return x[0] - y[0]; });
    var half = Math.floor(sounded.length / 2);
    var lower = sounded.slice(0, half), upper = sounded.slice(sounded.length - half);
    var low = 0, high = 0;
    lower.forEach(function (p) { low += p[1].speed; });
    upper.forEach(function (p) { high += p[1].speed; });
    low /= lower.length; high /= upper.length;
    var change = high - low;
    if (Math.abs(change) < SHEAR_NOTICEABLE) {
      return 'About ' + fmt(low, 1) + ' m/s throughout, with no useful shear between the low climbs and the high ones.';
    }
    return fmt(low, 1) + ' m/s in the lower climbs against ' + fmt(high, 1) + ' m/s in the higher ones — ' +
      fmt(Math.abs(change), 1) + ' m/s ' + (change > 0 ? 'stronger' : 'lighter') + ' with height.';
  }

  function histogramVerdict(a) {
    var data = a.climb_histogram;
    if (!data || !data.counts || !data.counts.some(Boolean)) return 'No time circling';
    var edges = data.edges, counts = data.counts;
    var interval = data.seconds_per_count ? data.seconds_per_count[0] : 1.0;
    var total = 0;
    counts.forEach(function (c) { total += c; });
    total = total || 1;
    var modeIndex = 0;
    counts.forEach(function (c, i) { if (c > counts[modeIndex]) modeIndex = i; });
    var mode = (edges[modeIndex] + edges[modeIndex + 1]) / 2, sink = 0, best = null;
    counts.forEach(function (c, i) { if (edges[i] < 0) sink += c; });
    counts.forEach(function (c, i) { if (c * interval > 20 && (best === null || edges[i + 1] > best)) best = edges[i + 1]; });
    if (best === null) best = mode;
    return 'Mostly ' + fmt(mode, 1, { plus: true }) + ' m/s, best sustained about ' + fmt(best, 0, { plus: true }) + ' m/s, ' +
      fmt(sink / total * 100, 0) + '% of the circling in sink';
  }

  // The air section's one ⓘ: what its numbers are. Where they came from is in the fold.
  var AIR_TERMS = [['Cloudbase', 'Surface air lifted until its dew-point spread closes.'],
                   ['Thermal top', 'Where the dry adiabat from the surface meets the profile.'],
                   ['Boundary layer', 'The model\'s mixing height.']];

  // The flight's last fold: where this flight's data came from, then how the numbers
  // above are worked out — one line each, the same on every flight (October 2026; these
  // were two dozen ⓘ).
  function sourcesFold(rows) {
    return '\n  <details class="flight-sources">\n    <summary>Sources and method</summary>\n    <table>' +
      rows.filter(Boolean).map(function (r) { return '<tr' + (r[2] ? ' class="method"' : '') + '><th scope="row">' + r[0] + '</th><td>' + r[1] + '</td></tr>'; }).join('') +
      '</table>\n  </details>\n';
  }

  function airFetchSection(a) {
    var f = a.flight, middle = Math.floor(f.lat.length / 2);
    return '\n  <section class="air-fetch" data-air-lat="' + fmt(f.lat[middle], 3) + '"\n' +
      '           data-air-lon="' + fmt(f.lon[middle], 3) + '" data-air-epoch="' + Math.trunc(f.time[middle]) + '"\n' +
      '           data-air-top="' + fmt(a.summary.max_altitude, 0) + '">\n' +
      '    <h2>The air that day' + info(glossary(AIR_TERMS), 'About the air') +
      '</h2>\n    <div class="figs air air-stats"></div>\n  </section>';
  }

  function capNote(meteo) {
    var top = Met.thermalTop(meteo);
    if (!top || !meteo.levels.length) return '';
    var above = meteo.levels.filter(function (l) { return l.height >= top; }).sort(function (x, y) { return x.height - y.height; });
    if (above.length < 2 || above[above.length - 1].height - above[0].height < 400) return '';
    var lastLevel = above[above.length - 1], second = above[1];
    var span = Math.abs(second.height - top - 1000.0) < Math.abs(lastLevel.height - top - 1000.0) ? second : lastLevel;
    var rise = span.height - above[0].height;
    if (rise < 400) return '';
    var lapse = (above[0].temperature - span.temperature) / rise * 1000.0;
    if (lapse < 6.0) {
      return ' Above it, ' + fmt(lapse, 1) + '&nbsp;K/km: a stable lid.';
    }
    return ' Above it, ' + fmt(lapse, 1) + '&nbsp;K/km: no lid.';
  }

  function meteoProfile(a, meteo, uid, rows) {
    if (meteo.levels.length < 2) {
      return '<p class="note">No sounding: the archive keeps profiles for about ' + RECENT_DAYS + ' days.</p>';
    }
    return '<div class="two">\n      <div class="chart">\n        <h3>Sounding</h3>\n' +
      '        <div class="panel">' + Ch.sounding(meteo, a, uid) + '</div>\n' +
      '        <ul class="legend legend-row"><li><i style="background:var(--climb)"></i>Temperature</li>' +
      '<li><i style="background:var(--sink)"></i>Dew point</li><li><i style="background:var(--neutral)"></i>Dry adiabat from the surface</li></ul>\n      </div>\n' +
      '      <div class="chart">\n        <h3>Wind against the model</h3>\n' +
      '        <div class="panel">\n          <div class="table-scroll">\n            <table>\n' +
      '              <thead><tr><th>Climb</th><th>Start</th><th>Height m</th><th>m/s</th><th>From</th>' +
      '<th>Model m/s</th><th>Model from</th><th>&Delta; dir</th></tr></thead>\n' +
      '              <tbody>' + rows.join('') + '</tbody>\n            </table>\n          </div>\n        </div>\n      </div>\n    </div>';
  }

  function meteoSection(a, meteo, uid) {
    if (!meteo) return '';
    var summary = a.summary, offset = summary.baro_offset || 0, flightTop = summary.max_altitude + offset;
    var spread = meteo.surface_temperature - meteo.surface_dew_point;
    var cloudbase = Met.cloudbase(meteo), thermalTop = Met.thermalTop(meteo), blTop = Met.boundaryLayerTop(meteo);
    var figs = [figure('Surface', fmt(meteo.surface_temperature, 0) + ' °C', '', 'Dew point ' + fmt(meteo.surface_dew_point, 0) + ' °C'),
                figure('Cloudbase', spaced(cloudbase), ' m', '')];
    if (thermalTop) figs.push(figure('Thermal top', spaced(thermalTop), ' m', ''));
    if (blTop) figs.push(figure('Boundary layer', spaced(blTop), ' m', ''));
    if (meteo.cape !== null) {
      figs.push(figure('CAPE', fmt(meteo.cape, 0), ' J/kg', meteo.cloud_cover_low !== null ? 'Low cloud ' + fmt(meteo.cloud_cover_low, 0) + '%' : ''));
    }
    var rows = [];
    thermals(a).forEach(function (seg, i) {
      if (!seg.wind || !seg.turns || seg.turns < 2) return;
      var height = (seg.start_altitude + seg.finish_altitude) / 2 + offset, model = Met.windAt(meteo, height);
      if (!model) return;
      var delta = Math.abs(np.mod(seg.wind.direction - model[1] + 180, 360) - 180);
      rows.push('<tr data-segment="' + seg.start + '"><td>' + (i + 1) + '</td><td>' + seg.start_time + '</td><td>' + fmt(height, 0) + '</td>' +
        '<td>' + fmt(seg.wind.speed, 1) + '</td><td>' + fmt(seg.wind.direction, 0) + '°</td><td>' + fmt(model[0], 1) + '</td><td>' +
        fmt(model[1], 0) + '°</td><td>' + fmt(delta, 0) + '°</td></tr>');
    });
    var ceilingNote = '';
    if (thermalTop) {
      var difference = flightTop - thermalTop;
      var verdict = difference > 0 ? fmt(Math.abs(difference), 0) + ' m above' : fmt(Math.abs(difference), 0) + ' m below';
      ceilingNote = '<p class="note">You topped out ' + verdict + ' the thermal top.' + capNote(meteo) + '</p>';
    }
    return '\n  <section>\n    <h2>The air that day' + info(glossary(AIR_TERMS.concat([
        ['Sounding', 'Shaded: the heights you flew.'], ['Wind against the model', 'Climb drift against the model at the same height.']])), 'About the air') + '</h2>\n' +
      '    <div class="figs air">' + figs.join('') + '</div>\n    ' + ceilingNote + '\n    ' + meteoProfile(a, meteo, uid, rows) + '\n  </section>';
  }

  function meteoReason(a, now) {
    var flown = Math.floor(a.flight.time[0] / 86400), age = Math.floor(now / 86400) - flown;
    if (age > RECENT_DAYS) return 'no sounding archived after ' + RECENT_DAYS + ' days';
    return 'no sounding fetched';
  }

  function debriefCards(result, uid, sample, facts, reason, figs) {
    var found = result && result.findings.length;
    if (!found && !(figs && figs.length)) return '';
    var cards = (found ? result.findings : []).map(function (finding) {
      var footer = finding.at ? '<span class="finding-when">' + esc(finding.at) + '</span>' : '', link = '';
      if (finding.cursor !== null && sample && sample.length) {
        link = '<button type="button" class="lnk finding-link" data-finding-cursor="' + Ch.samplePosition(sample, finding.cursor) +
          '">Show on the map <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 10h12M12 6l4 4-4 4"/></svg></button>';
      }
      return '<article class="finding" data-finding="' + esc(finding.id) + '"><p class="finding-cost"><span class="badge accent">Costs ' +
        esc(TV.debrief.costLabel(finding.cost)) + '</span></p><h3>' + esc(finding.title) + '</h3><p class="finding-body">' + esc(finding.sentence) +
        '</p><p class="finding-foot">' + footer + link + '</p></article>';
    });
    var reasons = { terrain: 'ground clearance (no elevation model)',
                    meteo: 'the ceiling (' + (reason || 'no sounding') + ')',
                    route: 'the route (none scored)', sampling: 'circling (track too coarse)' };
    var missing = (result ? result.suppressed : []).filter(function (k) { return k in reasons; }).map(function (k) { return reasons[k]; });
    var ctx = facts.length ? '<div class="context debrief-context">' + facts.map(function (f) {
      return '<div class="card"><b>' + f.value + '</b><span>' + f.label + (f.detail ? '<small>' + f.detail + '</small>' : '') + '</span></div>';
    }).join('') + '</div>' : '';
    var note = missing.length ? '<p class="note debrief-note">Not checked: ' + esc(missing.join('; ')) + '.</p>' : '';
    // The flight's other figures first, then what cost it.
    var more = figs && figs.length ? '    <div class="figs debrief-figs">' + figs.join('') + '</div>\n' : '';
    return '\n  <section id="debrief-' + uid + '">\n    <h2>Debrief</h2>\n' + more +
      (cards.length ? '    <div class="findings">' + cards.join('') + '</div>\n    ' : '    ') + ctx + '\n    ' + note + '\n  </section>';
  }

  var ARROW = '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';

  // The article, in the order a pilot reads a flight (the redesign, October 2026): the
  // title and the key numbers; the map with the side view under it; the debrief; climbs
  // and glides; how the air was used; the air that day. Every explanation sits behind an
  // ⓘ beside what it explains — the long "How to read this" section is gone, its
  // paragraphs distributed to their numbers.
  function flightBody(a, options) {
    options = options || {};
    var meteo = options.meteo || null, route = options.route || null, terrain = options.terrain || null;
    var uid = options.uid || 'f0', now = options.now === undefined ? Date.now() / 1000 : options.now;
    var weather = meteo ? Met.weather(meteo) : null;
    var summary = a.summary, f = a.flight, th = thermals(a), budget = a.budget;
    var tow = a.segments.filter(function (s) { return s.phase === 'tow'; })[0] || null;

    var gain = 0, held = 0, totalTurns = 0;
    th.forEach(function (s) { gain += s.altitude_change; held += s.duration; totalTurns += s.turns || 0; });
    var climbRate = th.length ? gain / held : 0.0;

    var wing = TV.certification && options.certificationTable ? TV.certification.lookup(summary.glider || '', options.certificationTable) : null;
    var chip = wing ? '<span class="cert">' + esc(wing.label) + '</span>' : '';

    var peakIndex = 0;
    a.series.alt.forEach(function (v, i) { if (v > a.series.alt[peakIndex]) peakIndex = i; });
    var peakTime = igc.clock(f.time[peakIndex], f.timezone).slice(0, 5);
    var offset = summary.baro_offset || 0;
    var coarse = summary.sample_interval > A.constants.TURN_RESOLUTION_LIMIT;
    var sample = sampleIndices(a), planH = Ch.planHeight(a);
    var withWind = th.filter(function (s) { return s.wind; }).length;
    var routeShape = route ? TV.xc.shape(route) : null;

    var altitude = summary.altitude_source === 'baro'
      ? 'barometric (ISA, ' + spaced(summary.baro_offset) + ' m below GPS)'
      : 'GPS only, so heights and climb rates are noisier';
    var sampling = spaced(summary.fixes) + ' fixes, one every ' + fmt(summary.duration / summary.fixes, 1) + ' s · altitude ' + altitude +
      ' · ' + esc(summary.timezone || 'UTC') + (coarse ? ' · too coarse to resolve circles: turn columns left blank' : '');

    var ceiling = ceilingTile(a, meteo, peakTime, offset);
    var perf = null, field = TV.airmass.field(a, weather);
    perf = TV.airmass.glidePerformance(a, field);
    var curve = perf ? TV.airmass.polar(a, field) : null;
    // Four key numbers over the map (2 × 2 on a phone): how far, how long, how well it
    // climbed, the wind. The rest of the flight's figures open the debrief (October 2026).
    var figs = [
      figure('Scored', route ? fmt(route.distance / 1000, 2) : '—', ' km',
             route ? cap(SHAPE_LABEL[routeShape] || 'open distance') + ' · ' + fmt(summary.track_distance / 1000, 0) + ' km flown' : 'No scored route', 'scored_km'),
      figure('Airtime', duration(summary.duration), '', String(summary.takeoff_time).slice(0, 5) + ' – ' + String(summary.landing_time).slice(0, 5)),
      figure('Mean climb', fmt(climbRate, 2, { plus: true }), ' m/s', th.length + ' climbs' + (!coarse ? ', ' + fmt(totalTurns, 0) + ' turns' : ''), 'mean_climb'),
      // Where it came from in the label, as a forecast says it.
      figure(a.wind ? 'Wind from ' + a.wind.cardinal : 'Wind', a.wind ? fmt(a.wind.speed, 1) : '—', ' m/s',
        a.wind ? 'Drift of ' + withWind + ' climbs' : 'Too few circled climbs')
    ];
    var moreFigs = [
      figure('Height gained', spaced(summary.total_gain), ' m', 'Best climb ' + spaced(summary.max_gain) + ' m'),
      ceiling[0] === 'ceiling used'
        ? figure(ceiling[4], ceiling[1].replace('%', ''), '%', cap(ceiling[3]), 'ceiling_used')
        : figure('Highest', ceiling[1], ' m', cap(ceiling[3]))
    ];
    if (perf) {
      moreFigs.push(figure('Wing’s glide', fmt(perf.air_ld, 1) + '&thinsp;:&thinsp;1', '',
        'At ' + fmt(perf.median_airspeed, 0) + ' km/h · ' + fmt(perf.ground_ld, 1) + ':1 over the ground' +
        (curve && curve.best_glide && curve.monotone ? ' · best ' + fmt(curve.best_glide[1], 1) + ':1 at ' + fmt(curve.best_glide[0], 0) + ' km/h' : '')));
    }
    if (tow) {
      moreFigs.push(figure('Off tow at', spaced(tow.finish_altitude), ' m',
        fmt(tow.altitude_change, 0, { plus: true }) + ' m in ' + shortDuration(tow.duration) + ' · not counted as a climb'));
    }

    // The side view, altitude against the time of day: its legend on a bar under the
    // chart, so the chart sits right under the map, inside the map's block
    // (`.flight-map`), so both go full screen with the map.
    var sideBar = '      <div class="side-bar">\n' +
      '        <ul class="legend legend-row"><li>&minus;4 m/s <span class="grad"></span> +4 m/s</li>' +
      '<li><i style="background:var(--climb);opacity:.5"></i>Climbing</li><li><i style="background:var(--sink);opacity:.5"></i>Gliding</li>' +
      (tow ? '<li><i style="background:var(--tow);opacity:.5"></i>Tow</li>' : '') + '</ul>\n      </div>\n';
    var sideChart = '\n    <div class="panel hero side-view">\n' +
      '      <div class="profile chart-host" data-chart="profile"\n           style="aspect-ratio:' + Ch.PROFILE.width + '/' + Ch.PROFILE.height + '">\n' +
      '        <p class="chart-missing">The side view is drawn in this page. It needs JavaScript.</p>\n      </div>\n' + sideBar + '    </div>\n';

    var mapSection, clearance = null, valley = null, topView = '';
    if (terrain) {
      var payload = TV.scene.data(a, options.sceneTerrain || terrain, { airspaceRemote: options.airspaceRemote });
      clearance = TV.terrain.clearance(terrain, a);
      valley = TV.terrain.valleyClearance(terrain, a);
      mapSection = '\n  <section class="map-section">\n    <div class="flight-map">\n    <div class="renderer-host">\n    ' +
        TV.scene.panel(payload, uid) + '\n    </div>' + sideChart + '    </div>\n  </section>';
    } else {
      // No ground to draw on: the side view alone, and the top view below the tables,
      // which a 3D map looking straight down replaces where there is one.
      mapSection = '\n  <section class="map-section">\n    <div class="flight-map">' + sideChart + '    </div>\n  </section>';
      topView = '\n  <section>\n    <h2>Top view</h2>\n' +
        '    <div class="seg toggle" role="group" aria-label="What the climb circles show">' +
        '<button type="button" class="toggle-button is-on" data-circles="gain" aria-pressed="true">Size: height gained</button>' +
        '<button type="button" class="toggle-button" data-circles="rate" aria-pressed="false">Size: climb rate</button></div>\n' +
        '    <div class="panel hero">\n      <div class="chart-host" data-chart="plan"\n           style="aspect-ratio:' + Ch.PLAN.width + '/' + planH + '">\n' +
        '        <p class="chart-missing">The top view is drawn in this page. It needs JavaScript.</p>\n      </div>\n    </div>\n  </section>\n';
    }

    var windChart = Ch.windProfile(a, meteo, uid), histogram = Ch.climbHistogram(a);
    var metSection = meteo ? meteoSection(a, meteo, uid) : airFetchSection(a);

    var result = TV.debrief.build(a, { route: route, weather: weather, clearance: clearance, valley: valley, flightPlan: options.flightPlan || null });
    var sources = TV.insolation.sources(a, terrain);
    var debriefSection = debriefCards(result, uid, sample, contextFacts(a, clearance, terrain), meteo ? '' : meteoReason(a, now), moreFigs);
    var use = M.ceilingUse(a, weather);
    var compare = [['scored-km', route ? pyFloat(R(route.distance / 1000.0, 2)) : null],
                   ['mean-climb', th.length ? pyFloat(R(climbRate, 2)) : null],
                   ['ceiling-used', use ? pyFloat(use.fraction) : null]]
      .filter(function (c) { return c[1] !== null; }).map(function (c) { return ' data-compare-' + c[0] + '="' + c[1] + '"'; }).join('');
    var compareName = esc([summary.date, summary.site].filter(Boolean).join(' · '));
    // What tells compared flights apart is chosen among them (`compareLabels`, page): the
    // pilot, the day, the launch time.
    var compareWho = ' data-compare-pilot="' + esc(summary.pilot || '') + '" data-compare-date="' + esc(summary.date || '') +
      '" data-compare-time="' + esc(String(summary.takeoff_time || '').slice(0, 5)) + '"';
    var glideCount = glides(a).length;

    var budgetLegend = Ch.budgetParts(a).filter(function (p) { return p.fraction > 0; }).map(function (p) {
      return '<li><i style="background:' + p.colour + '"></i>' + p.label + ' ' + (p.seconds >= 60 ? shortDurationWords(p.seconds) : fmt(p.fraction * 100, 0) + '%') + '</li>';
    }).join('');
    var sparkLegend = '<ul class="legend legend-row spark-legend"><li>Over time:</li><li><i style="background:var(--sink-1)"></i>Sinking</li>' +
      '<li><i style="background:var(--neutral)"></i>Around zero</li><li><i style="background:var(--climb-1)"></i>Climbing</li>' +
      '<li><i style="background:var(--climb-2)"></i>Climbing hard</li></ul>';
    var ldLegend = '<ul class="legend legend-row"><li>Glide over the ground:</li>' +
      ['under 5', '5–7', '7–9', '9–12', 'over 12'].map(function (t, i) { return '<li><i style="background:var(--ld-' + (i + 1) + ')"></i>' + t + '</li>'; }).join('') + '</ul>';

    // The page's title while this flight is the one shown (`flightTabs.show`, page/report.js).
    var pageTitle = summary.date + ' · ' + (summary.site || 'flight') + ' — flight review';
    return '<article class="flight" data-flight-report="' + uid + '"' + compare + ' data-compare-name="' + compareName + '"' + compareWho +
      ' data-title="' + esc(pageTitle) + '"' + (options.hidden ? ' hidden' : '') + '>\n' +
      '  <header class="masthead">\n    <h1>' + esc(summary.site || 'Flight') + ' <span>' + esc(summary.date) + '</span></h1>\n' +
      '    <p class="who"><b>' + esc(summary.pilot || '—') + '</b> · ' + esc(summary.glider || '—') + chip + '</p>\n  </header>\n' +
      '  <div class="figs keys">' + figs.join('') + '</div>\n' + mapSection + '\n' + debriefSection + '\n\n' +
      '  <section>\n    <h2>Climbs' + info(glossary([
        ['Climb', 'The circling, not the run-in. Click a row to find it on the map.'],
        ['Core', 'Best 20&nbsp;s of the climb against its average.'],
        ['Lift', 'Ridge: slope over ' + fmt(TV.insolation.RIDGE_SLOPE, 0) + '°, facing the wind, within ' + fmt(TV.insolation.RIDGE_CLEARANCE, 0) +
                 '&nbsp;m of it, not circling. Thermal otherwise.'],
        ['Rev', 'Times the turn changed direction.'],
        ['Over time', 'Climb rate from entry (left) to exit.']]), 'About the climbs') + '</h2>\n' +
      '    <div class="panel">\n      <div class="table-scroll">\n        <table class="table-climbs">\n          <thead><tr>\n' +
      '            <th>#</th><th>Start</th><th>Time</th><th>Gain m</th><th>Top m</th>\n            <th>Avg m/s</th>' +
      '<th>Core</th><th>Lift</th>\n' +
      '            <th class="circling-detail">Turns</th><th class="circling-detail">m/turn</th>\n            <th class="circling-detail">Dir</th><th class="circling-detail">Rev</th>\n' +
      '            <th class="circling-detail">s/turn</th>\n            <th class="circling-detail">Radius m</th>\n            <th class="spark-head">Over time</th>\n          </tr></thead>\n' +
      '          <tbody>' + thermalRows(a, sample, sources) + '</tbody>\n        </table>\n      </div>\n    </div>\n' + sparkLegend + '\n' +
      '    <button type="button" class="btn more toggle-button" data-detail="circling" aria-pressed="false">Circling detail</button>\n  </section>\n\n' +
      '  <section>\n    <h2>Glides</h2>\n' +
      '    <div class="panel">\n      <div class="table-scroll">\n        <table class="table-glides">\n          <thead><tr><th>#</th><th>Start</th><th>Time</th><th>km</th>\n' +
      '            <th>Glide</th><th>km/h</th></tr></thead>\n          <tbody>' + glideRows(a, sample) + '</tbody>\n        </table>\n      </div>\n    </div>\n    ' + ldLegend + '\n' +
      (glideCount > GLIDES_SHOWN ? '    <button type="button" class="btn more" data-show-all="glides" aria-expanded="false">Show all ' + glideCount + ' glides</button>\n' : '') +
      '  </section>\n\n' +
      '  <section>\n    <h2>How the air was used' + info(glossary([
        ['Time', 'Climbing, gliding, and the rest: transitions too short to call.'],
        ['Lift you sat in', 'Time circling by climb rate, in 0.5&nbsp;m/s bins.'],
        ['Wind by height', 'One point per climb, from its drift; the tail points downwind.' + (meteo ? ' Grey: the model.' : '')]]),
        'About these charts') + '</h2>\n' +
      '    <div class="chart">\n      <h3>Time</h3>\n' +
      '      <div class="panel budget">' + Ch.budgetBar(a, 1040) + '</div>\n      <ul class="legend legend-row">' + budgetLegend + '</ul>\n    </div>\n' +
      '    <div class="two">\n      <div class="chart">\n        <h3>Lift you sat in</h3>\n' +
      '        <p class="sub">' + histogramVerdict(a) + '</p>\n' +
      '        <div class="panel">' + (histogram || '<p class="note">No thermalling time to summarise.</p>') + '</div>\n      </div>\n' +
      '      <div class="chart">\n        <h3>Wind by height</h3>\n' +
      '        <p class="sub">' + windShearNote(a) + '</p>\n' +
      '        <div class="panel">' + (windChart || '<p class="note">Not enough circled climbs to sound the wind.</p>') + '</div>\n' +
      '        <ul class="legend legend-row"><li><i style="background:var(--sink)"></i>Measured from circle drift</li>' +
      (meteo ? '<li><i style="background:var(--neutral)"></i>Model profile for the day</li>' : '') + '</ul>\n      </div>\n    </div>\n  </section>\n\n' +
      topView + metSection + '\n' + sourcesFold([
        ['Track', sampling],
        ['Weather', (meteo ? esc(meteo.source) + ', valid ' + esc(meteo.valid_at) : 'Open-Meteo, live') +
                    ', at the middle of the course line. A model: ceilings ±100&nbsp;m.'],
        wing ? ['Wing class', esc(wing.name + ' — ' + wing.certificate + ', ' + wing.source + (wing.note ? ' (' + wing.note + ')' : ''))] : null,
        ['Scored', 'XContest rules: free distance, flat or FAI triangle.', true],
        ['Mean climb', 'Height gained circling ÷ time circling.', true],
        ['Wind', 'The drift while circling; climbs of two or more turns one way.', true],
        perf ? ['Wing’s glide', 'Median glide through the air, the wind taken out (' + field.soundings.length + ' climbs, ' +
                fmt(perf.confidence, 0, { percent: true }) + ' confidence).', true] : null,
        ['Ceiling used', 'Your top against the lower of the model cloudbase and thermal top.', true],
        ['Lift', 'Convergence is not a label: one track cannot tell it from ridge lift.', true]]) +
      '  <script type="application/json" class="cursor-data">' + JSON.stringify(cursorData(a, clearance)) + '</script>\n' +
      '  <script type="application/json" class="chart-data">' + JSON.stringify(Ch.payload(a, meteo, route, sample, planH)) + '</script>\n</article>\n';
  }

  function shortDurationWords(seconds) {
    seconds = Math.trunc(seconds);
    var hours = Math.floor(seconds / 3600), minutes = Math.round((seconds % 3600) / 60);
    return hours ? hours + ' h ' + pad(minutes) : minutes + ' min';
  }

  TV.report = { flightBody: flightBody, cursorData: cursorData, sampleIndices: sampleIndices, duration: duration,
                shortDuration: shortDuration,
                // The pieces of the article a test asks about one at a time.
                parts: { windShearNote: windShearNote, clearanceNote: clearanceNote, triggerNote: triggerNote } };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

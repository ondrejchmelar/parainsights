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

  // One of the key numbers under the title: the value, its label and an ⓘ with the
  // detail that used to be a grey sub-line. `key` names it for the comparison, which
  // writes into the `.verdict-delta` slot.
  function figure(label, value, unit, detail, key) {
    return '<div class="fig"' + (key ? ' data-key="' + key + '"' : '') + '><span class="v">' + value +
      (unit ? '<small>' + unit + '</small>' : '') + '</span><span class="k">' + label + info(detail, 'About ' + label.toLowerCase()) +
      '</span>' + (key ? '<span class="verdict-delta" hidden></span>' : '') + '</div>';
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
  // the number large, what it counts beside it, the reasoning behind an ⓘ.
  function contextFacts(a, clearance, terrain) {
    var out = [], w = clearance ? M.airborneWindow(clearance) : null;
    if (w) {
      var inside = clearance.slice(w[0], w[1]), median = np.median(inside), low = np.min(inside);
      out.push({ value: fmt(median, 0) + '&nbsp;m', label: 'Median height over the ground directly beneath you',
                 detail: (low >= 0 ? 'Lowest ' + fmt(low, 0) + '&nbsp;m. ' : '') +
                         'The launch and the landing are left out, or both would win by being on the ground.' });
    }
    if (!terrain) return out;
    var found = TV.insolation.triggers(a, terrain);
    if (found.length >= 3) {
      var lit = found.filter(function (t) { return t.face.relative > 1.05; }).length;
      var detail = 'Of the ' + found.length + ' climbs that started over sloping ground.';
      var half = Math.floor(found.length / 2);
      if (half >= 2) {
        var early = found.slice(0, half), late = found.slice(found.length - half);
        var first = meanAspect(early.map(function (t) { return t.face.aspect; }));
        var second = meanAspect(late.map(function (t) { return t.face.aspect; }));
        var swing = np.mod(second - first + 540, 360) - 180;
        detail += Math.abs(swing) >= 30
          ? ' The faces swung ' + (swing > 0 ? 'clockwise' : 'anticlockwise') + ' through the day, from ' + geo.cardinal(first) +
            '-facing (' + early[0].at + '&ndash;' + early[early.length - 1].at + ') to ' + geo.cardinal(second) + '-facing (' +
            late[0].at + '&ndash;' + late[late.length - 1].at + ')' + (swing > 0 ? ', which is the sun going round' : '') + '.'
          : ' They stayed on ' + geo.cardinal(first) + '-facing ground from ' + early[0].at + ' to ' + late[late.length - 1].at +
            ' rather than following the sun round.';
      }
      out.push({ value: lit + ' of ' + found.length, label: 'Climbs began over ground catching more sun than the slopes around it', detail: detail });
    }
    var breeze = TV.insolation.windward(a, terrain);
    if (breeze && breeze.total) {
      out.push({ value: breeze.windward + ' of ' + breeze.total, label: 'Climbs faced within 60&#176; of the measured wind — where ridge lift would be',
                 detail: 'A climb is called ridge only when the slope, the wind and your distance from it all agree; see the Lift column.' });
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
            (spaced(use.reached) + ' m of a modelled ' + spaced(use.ceiling) + ' m ' + use.source.replace(/_/g, ' ')).replace(/,/g, ' ')];
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

  function airFetchSection(a) {
    var f = a.flight, middle = Math.floor(f.lat.length / 2);
    return '\n  <section class="air-fetch" data-air-lat="' + fmt(f.lat[middle], 3) + '"\n' +
      '           data-air-lon="' + fmt(f.lon[middle], 3) + '" data-air-epoch="' + Math.trunc(f.time[middle]) + '"\n' +
      '           data-air-top="' + fmt(a.summary.max_altitude, 0) + '">\n' +
      '    <h2>The air that day' + info('Open-Meteo, fetched when you open this page, for the middle of the course line: a model, not a measurement. Treat the ceilings as ±100&nbsp;m.') +
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
      return ' Above that the profile cools ' + fmt(lapse, 1) + '&nbsp;K/km against the dry adiabat\'s 9.8 — a stable layer, which is what a day that caps out feels like from the harness.';
    }
    return ' Above that it still cools ' + fmt(lapse, 1) + '&nbsp;K/km, so nothing in the profile was holding the day down.';
  }

  function meteoProfile(a, meteo, uid, rows) {
    if (meteo.levels.length < 2) {
      return '<p class="note">No sounding for this date' + info('The reanalysis archive serves surface fields for any past day but returns nothing on pressure levels, so the sounding and the wind comparison are missing here. Flights from the last two months get the full profile.') + '</p>';
    }
    return '<div class="two">\n      <div class="chart">\n        <h3>Sounding' +
      info('Where the dry adiabat crosses the temperature curve is as high as a surface thermal can get without help. The shaded band is the altitude you actually used.') + '</h3>\n' +
      '        <div class="panel">' + Ch.sounding(meteo, a, uid) + '</div>\n' +
      '        <ul class="legend legend-row"><li><i style="background:var(--climb)"></i>Temperature</li>' +
      '<li><i style="background:var(--sink)"></i>Dew point</li><li><i style="background:var(--neutral)"></i>Dry adiabat from the surface</li></ul>\n      </div>\n' +
      '      <div class="chart">\n        <h3>Wind against the model' +
      info('Wind from circle drift against the model at the same height. Agreement here is the strongest evidence that the drift method works — nothing in the flight data knows about the model, and nothing in the model knows about the flight.') + '</h3>\n' +
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
    var figs = [figure('Surface', fmt(meteo.surface_temperature, 0) + ' °C', '', 'Dew point ' + fmt(meteo.surface_dew_point, 0) + ' °C, a spread of ' + fmt(spread, 0) + ' K.'),
                figure('Cloudbase', spaced(cloudbase), ' m', 'The surface air lifted until its ' + fmt(spread, 0) + ' K spread closes.')];
    if (thermalTop) figs.push(figure('Thermal top', spaced(thermalTop), ' m', 'Where the dry adiabat from the surface meets the profile.'));
    if (blTop) figs.push(figure('Boundary layer', spaced(blTop), ' m', 'As high as the day\'s heating reaches.'));
    if (meteo.cape !== null) {
      figs.push(figure('CAPE', fmt(meteo.cape, 0), ' J/kg', meteo.cloud_cover_low !== null ? 'Low cloud ' + fmt(meteo.cloud_cover_low, 0) + '%.' : 'Instability.'));
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
      ceilingNote = '<p class="note">The sounding puts the dry thermal top at ' + spaced(thermalTop) + '&nbsp;m and you topped out ' + verdict +
        ' it.' + capNote(meteo) + '</p>';
    }
    return '\n  <section>\n    <h2>The air that day' +
      info(esc(meteo.source) + ' over the middle of the course line, valid ' + esc(meteo.valid_at) + ', fetched once and embedded. ' +
           'A model\'s analysis, not a radiosonde ascent: treat the ceilings as ±100&nbsp;m and the winds as indicative.') + '</h2>\n' +
      '    <div class="figs air">' + figs.join('') + '</div>\n    ' + ceilingNote + '\n    ' + meteoProfile(a, meteo, uid, rows) + '\n  </section>';
  }

  function otherNote(a) {
    var o = a.other;
    if (!o || !o.seconds) return '';
    function minutes(s) { return s >= 30 ? fmt(s / 60, 0) + ' min' : 'under a minute'; }
    var net = o.net_altitude;
    return ' That last part is ' + minutes(o.straight_sink) + ' of straight sink, ' + minutes(o.scratching) +
      ' turning without climbing and ' + minutes(o.rising) + ' of rising air no phase claimed — a net ' + Math.abs(net) + ' m ' +
      (net > 0 ? 'gained' : 'lost') + ' over the whole of it.';
  }

  function meteoReason(a, now) {
    var flown = Math.floor(a.flight.time[0] / 86400), age = Math.floor(now / 86400) - flown;
    if (age > RECENT_DAYS) {
      return 'this flight is ' + Math.floor(age / 30) + ' months old and the weather archive keeps a vertical profile for about ' +
        RECENT_DAYS + ' days, so the day\'s sounding can no longer be fetched';
    }
    return "the day's sounding was not fetched when this report was built";
  }

  function debriefCards(result, uid, sample, facts, reason) {
    if (!result || !result.findings.length) return '';
    var cards = result.findings.map(function (finding) {
      var footer = finding.at ? '<span class="finding-when">' + esc(finding.at) + '</span>' : '', link = '';
      if (finding.cursor !== null && sample && sample.length) {
        link = '<button type="button" class="lnk finding-link" data-finding-cursor="' + Ch.samplePosition(sample, finding.cursor) +
          '">Show on the map <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 10h12M12 6l4 4-4 4"/></svg></button>';
      }
      return '<article class="finding" data-finding="' + esc(finding.id) + '"><p class="finding-cost"><span class="badge accent">Costs ' +
        esc(TV.debrief.costLabel(finding.cost)) + '</span></p><h3>' + esc(finding.title) + '</h3><p class="finding-body">' + esc(finding.sentence) +
        '</p><p class="finding-foot">' + footer + link + '</p></article>';
    });
    var reasons = { terrain: 'ground clearance needs an elevation model, which this report has none of',
                    meteo: reason || "the day's sounding is not in this report",
                    route: 'the route findings need a scored route', sampling: 'this track is too coarse to count circles' };
    var missing = result.suppressed.filter(function (k) { return k in reasons; }).map(function (k) { return reasons[k]; });
    var ctx = facts.length ? '<div class="context debrief-context">' + facts.map(function (f) {
      return '<div class="card"><b>' + f.value + '</b><span>' + f.label + info(f.detail) + '</span></div>';
    }).join('') + '</div>' : '';
    var note = missing.length ? '<p class="note debrief-note">Some findings are not computed here' +
      info(esc(cap(missing.join('; '))) + '.') + '</p>' : '';
    return '\n  <section id="debrief-' + uid + '">\n    <h2>Debrief</h2>\n' +
      '    <div class="findings">' + cards.join('') + '</div>\n    ' + ctx + '\n    ' + note + '\n  </section>';
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
    var chip = wing ? '<span class="cert">' + esc(wing.label) + '</span>' +
      info(esc(wing.name + ' — ' + wing.certificate + ', ' + wing.source + (wing.note ? ' (' + wing.note + ')' : '')) +
           ". The certifier's class, looked up on the wing's name; a header names the wing but not its size. It describes the wing's behaviour in a test, and says nothing about this flight.",
           'About the class') : '';

    var peakIndex = 0;
    a.series.alt.forEach(function (v, i) { if (v > a.series.alt[peakIndex]) peakIndex = i; });
    var peakTime = igc.clock(f.time[peakIndex], f.timezone).slice(0, 5);
    var offset = summary.baro_offset || 0;
    var coarse = summary.sample_interval > A.constants.TURN_RESOLUTION_LIMIT;
    var sample = sampleIndices(a), planH = Ch.planHeight(a);
    var withWind = th.filter(function (s) { return s.wind; }).length;
    var routeShape = route ? TV.xc.shape(route) : null;

    var altitude = summary.altitude_source === 'baro'
      ? 'Altitude is barometric: climb rates come from the smooth baro trace. It reads ISA pressure altitude, ' +
        String(summary.baro_offset) + ' m below GPS on the day — absolute heights are indicative, height changes are solid.'
      : 'Altitude is GPS: this recorder has no pressure sensor, so heights and climb rates are noisier than they look.';
    var sampling = summary.fixes.toLocaleString('en-US') + ' fixes at ' + fmt(summary.duration / summary.fixes, 1) + ' s, timezone ' +
      esc(summary.timezone || 'UTC') + '.' + (coarse ? ' A fix every ' + fmt(summary.sample_interval, 0) +
      ' s is too coarse to resolve a circle: turns, circle radius and peak climb are left blank, and distance flown reads low.' : '');

    var ceiling = ceilingTile(a, meteo, peakTime, offset);
    var perf = null, field = TV.airmass.field(a, weather);
    perf = TV.airmass.glidePerformance(a, field);
    var curve = perf ? TV.airmass.polar(a, field) : null;
    var figs = [
      figure('Scored', route ? fmt(route.distance / 1000, 2) : '—', ' km',
             route ? cap(SHAPE_LABEL[routeShape] || 'open distance') + ', ' + fmt(summary.track_distance / 1000, 0) + ' km flown, ' +
                     fmt(summary.straight_distance / 1000, 0) + ' km straight.' : 'No scored route.', 'scored_km'),
      figure('Airtime', duration(summary.duration), '', summary.takeoff_time + ' – ' + summary.landing_time + '. ' + sampling),
      figure('Mean climb', fmt(climbRate, 2, { plus: true }), ' m/s', th.length + ' climbs' + (!coarse ? ', ' + fmt(totalTurns, 0) + ' turns' : '') +
             '. Height gained while circling, over the time spent circling.', 'mean_climb'),
      figure('Height gained', spaced(summary.total_gain), ' m', 'Best single climb ' + fmt(summary.max_gain, 0) + ' m. ' + altitude),
      ceiling[0] === 'ceiling used'
        ? figure('Of cloudbase', ceiling[1].replace('%', ''), '%', cap(ceiling[3]) + '.', 'ceiling_used')
        : figure('Highest', ceiling[1], ' m', cap(ceiling[3]) + '.')
    ];
    if (perf) {
      figs.push(figure('Wing’s glide', fmt(perf.air_ld, 1) + '&thinsp;:&thinsp;1', '',
        'The median glide through the air at ' + fmt(perf.median_airspeed, 0) + ' km/h, the wind taken out; ' + fmt(perf.ground_ld, 1) +
        ':1 over the ground. The wind is the one sounded from ' + field.soundings.length + ' circled climbs, which this flight supports to about ' +
        fmt(perf.confidence, 0, { percent: true }) + '.' +
        (curve && curve.best_glide && curve.monotone ? ' Your best glides came at about ' + fmt(curve.best_glide[0], 0) + ' km/h, where the wing returned ' +
         fmt(curve.best_glide[1], 1) + ':1.' : '')));
    }
    figs.push(figure('Wind', a.wind ? fmt(a.wind.speed, 1) : '—', ' m/s',
      a.wind ? 'From ' + a.wind.cardinal + ', averaged over ' + withWind + ' climbs. Inferred, not measured: while circling the glider\'s own airspeed averages out and the track drifts with the air. Climbs flown fewer than two full turns, or in both directions, are left out.' : 'Too few circled climbs to sound the wind.'));
    if (tow) {
      figs.push(figure('Off tow at', spaced(tow.finish_altitude), ' m',
        fmt(tow.altitude_change, 0, { plus: true }) + ' m in ' + shortDuration(tow.duration) + ' at ' + fmt(tow.average_climb, 2, { plus: true }) +
        ' m/s, flown almost straight' + (tow.swept_turns !== null ? ' (' + fmt(tow.swept_turns, 1) + ' turns of heading)' : '') +
        '. Kept out of the thermal statistics and the wind estimate.'));
    }

    // The side view: its axis switch and legend on a bar above the chart, inside the
    // map's block (`.flight-map`), so both go full screen with the map.
    var sideBar = '      <div class="side-bar">\n' +
      '        <div class="seg toggle" role="group" aria-label="Ground axis for the side view">' +
      '<button type="button" class="toggle-button is-on" data-profile="flown" aria-pressed="true">Distance</button>' +
      '<button type="button" class="toggle-button" data-profile="from_start" aria-pressed="false">From launch</button>' +
      '<button type="button" class="toggle-button" data-profile="time" aria-pressed="false">Time</button></div>\n' +
      '        <ul class="legend legend-row"><li>Sink <span class="grad"></span> Climb' +
      info('The trace is coloured by climb rate, from &minus;4 m/s to +4 m/s; the bands behind it are the phases. Distance is distance flown, always increasing, so a climb draws as a near-vertical step.') + '</li>' +
      '<li><i style="background:var(--climb);opacity:.5"></i>Climbing</li><li><i style="background:var(--sink);opacity:.5"></i>Gliding</li>' +
      (tow ? '<li><i style="background:var(--tow);opacity:.5"></i>Tow</li>' : '') + '</ul>\n      </div>\n';
    var sideChart = '\n    <div class="panel hero side-view">\n' + sideBar +
      '      <div class="profile chart-host" data-chart="profile" data-mode="flown"\n           style="aspect-ratio:' + Ch.PROFILE.width + '/' + Ch.PROFILE.height + '">\n' +
      '        <p class="chart-missing">The side view is drawn in this page. It needs JavaScript.</p>\n      </div>\n    </div>\n';

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
      topView = '\n  <section>\n    <h2>Top view' + info('The course line over the ground' + (route ? '; the thin straight legs are the scored route.' : '.')) + '</h2>\n' +
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
    var debriefSection = debriefCards(result, uid, sample, contextFacts(a, clearance, terrain), meteo ? '' : meteoReason(a, now));
    var use = M.ceilingUse(a, weather);
    var compare = [['scored-km', route ? pyFloat(R(route.distance / 1000.0, 2)) : null],
                   ['mean-climb', th.length ? pyFloat(R(climbRate, 2)) : null],
                   ['ceiling-used', use ? pyFloat(use.fraction) : null]]
      .filter(function (c) { return c[1] !== null; }).map(function (c) { return ' data-compare-' + c[0] + '="' + c[1] + '"'; }).join('');
    var compareName = esc([summary.date, summary.site].filter(Boolean).join(' · '));
    var glideCount = glides(a).length;
    var otherFraction = budget.fractions.other;

    var budgetLegend = Ch.budgetParts(a).filter(function (p) { return p.fraction > 0; }).map(function (p) {
      return '<li><i style="background:' + p.colour + '"></i>' + p.label + ' ' + (p.seconds >= 60 ? shortDurationWords(p.seconds) : fmt(p.fraction * 100, 0) + '%') + '</li>';
    }).join('');
    var sparkLegend = '<ul class="legend legend-row spark-legend"><li>Over time:</li><li><i style="background:var(--sink-1)"></i>Sinking</li>' +
      '<li><i style="background:var(--neutral)"></i>Around zero</li><li><i style="background:var(--climb-1)"></i>Climbing</li>' +
      '<li><i style="background:var(--climb-2)"></i>Climbing hard</li></ul>';
    var ldLegend = 'Glide ratio over the ground, so it carries the wind as well as the wing; the wing\'s own is the key number above. Bar colours: ' +
      ['under 5', '5–7', '7–9', '9–12', 'over 12'].map(function (t, i) { return '<span class="sw" style="background:var(--ld-' + (i + 1) + ')"></span>' + t; }).join(', ') + '.';

    return '<article class="flight" data-flight-report="' + uid + '"' + compare + ' data-compare-name="' + compareName + '"' + (options.hidden ? ' hidden' : '') + '>\n' +
      '  <header class="masthead">\n    <h1>' + esc(summary.site || 'Flight') + ' <span>' + esc(summary.date) + '</span></h1>\n' +
      '    <p class="who"><b>' + esc(summary.pilot || '—') + '</b> · ' + esc(summary.glider || '—') + chip + '</p>\n  </header>\n' +
      '  <div class="figs keys">' + figs.join('') + '</div>\n' + mapSection + '\n' + debriefSection + '\n\n' +
      '  <section>\n    <h2>Climbs' + info('A climb is the circling, not the run-in to it, which is neither a climb nor a glide. Click a row to see where it began on the map.' +
        (coarse ? ' This track is sampled every ' + fmt(summary.sample_interval, 0) + ' s, too coarse to resolve a circle, so the turn columns are blank.' : '')) + '</h2>\n' +
      '    <div class="panel">\n      <div class="table-scroll">\n        <table class="table-climbs">\n          <thead><tr>\n' +
      '            <th>#</th><th>Start</th><th>Time</th><th>Gain m</th><th>Top m</th>\n            <th>Avg m/s</th>' +
      '<th>Core' + info('Mean climb over the best 20&nbsp;s of the same climb, against the whole climb: the closest single number to “did you stay in the core”.') + '</th>' +
      '<th>Lift' + info('Ridge only when three things agree: the ground steeper than ' + fmt(TV.insolation.RIDGE_SLOPE, 0) + '°, the wind running into it, and you within ' +
        fmt(TV.insolation.RIDGE_CLEARANCE, 0) + '&nbsp;m of the slope, beating along it rather than closing circles. Thermal otherwise; a dash means there was nothing to check it against. Convergence is deliberately not a label: its honest signature is a climb drifting differently from the air around it, and one tracklog cannot tell that from a ridge climb holding station or a badly sounded wind.') + '</th>\n' +
      '            <th class="circling-detail">Turns</th><th class="circling-detail">m/turn</th>\n            <th class="circling-detail">Dir</th><th class="circling-detail">Rev' +
      info('Reversals: the times the turn changed direction mid-climb. With the radius it says how tidily the climb was flown.') + '</th>\n' +
      '            <th class="circling-detail">s/turn</th>\n            <th class="circling-detail">Radius m</th>\n            <th class="spark-head">Over time' +
      info('Climb rate through the climb, entry on the left: where the core was, and whether you left while it was still working.') + '</th>\n          </tr></thead>\n' +
      '          <tbody>' + thermalRows(a, sample, sources) + '</tbody>\n        </table>\n      </div>\n    </div>\n' + sparkLegend + '\n' +
      '    <button type="button" class="btn more toggle-button" data-detail="circling" aria-pressed="false">Circling detail</button>\n  </section>\n\n' +
      '  <section>\n    <h2>Glides' + info(ldLegend + (glideCount > GLIDES_SHOWN ? ' The ' + GLIDES_SHOWN + ' longest of ' + glideCount + ' are shown.' : '')) + '</h2>\n' +
      '    <div class="panel">\n      <div class="table-scroll">\n        <table class="table-glides">\n          <thead><tr><th>#</th><th>Start</th><th>Time</th><th>km</th>\n' +
      '            <th>Glide</th><th>km/h</th></tr></thead>\n          <tbody>' + glideRows(a, sample) + '</tbody>\n        </table>\n      </div>\n    </div>\n' +
      (glideCount > GLIDES_SHOWN ? '    <button type="button" class="btn more" data-show-all="glides" aria-expanded="false">Show all ' + glideCount + ' glides</button>\n' : '') +
      '  </section>\n\n' +
      '  <section>\n    <h2>How the air was used</h2>\n' +
      '    <div class="chart">\n      <h3>Time' + info(duration(budget.thermalling) + ' climbing across ' + th.length + ' thermals, ' + duration(budget.gliding) + ' gliding, and ' +
        duration(budget.other) + ' that was neither.' + otherNote(a) + ' The climbs and glides account for ' + fmt((1 - otherFraction) * 100, 0) +
        '% of airtime; the rest is transitions too short or too ambiguous to call, which is honest rather than tidy.') + '</h3>\n' +
      '      <div class="panel budget">' + Ch.budgetBar(a, 1040) + '</div>\n      <ul class="legend legend-row">' + budgetLegend + '</ul>\n    </div>\n' +
      '    <div class="two">\n      <div class="chart">\n        <h3>Lift you sat in' +
      info('Every second spent circling, sorted into half-metre climb-rate buckets. The tallest bar is the climb rate you spent the most time in — not the best one you found. Bars left of zero are time spent turning in sink; the right-hand tail is the cores.') + '</h3>\n' +
      '        <p class="sub">' + histogramVerdict(a) + '</p>\n' +
      '        <div class="panel">' + (histogram || '<p class="note">No thermalling time to summarise.</p>') + '</div>\n      </div>\n' +
      '      <div class="chart">\n        <h3>Wind by height' +
      info('One point per climb, from circle drift, numbered as in the climbs table and so in the order flown; the first and last carry their clock time, and hovering any point gives the rest. Height is where the climb was worked; the tail points downwind.' +
           (meteo ? ' The model profile for the day is drawn behind them as a check.' : ' The day\'s forecast profile would be drawn behind these as a check on them, but ' + meteoReason(a, now) + '.'), 'About the wind chart') + '</h3>\n' +
      '        <p class="sub">' + windShearNote(a) + '</p>\n' +
      '        <div class="panel">' + (windChart || '<p class="note">Not enough circled climbs to sound the wind.</p>') + '</div>\n' +
      '        <ul class="legend legend-row"><li><i style="background:var(--sink)"></i>Measured from circle drift</li>' +
      (meteo ? '<li><i style="background:var(--neutral)"></i>Model profile for the day</li>' : '') + '</ul>\n      </div>\n    </div>\n  </section>\n\n' +
      topView + metSection + '\n' +
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

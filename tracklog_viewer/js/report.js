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
      if (seg.phase === 'tow') { label = 'T'; tag = '<span class="tag tag-tow">tow</span>'; }
      else { number += 1; label = String(number); tag = ''; }
      var source = sources && seg.phase === 'thermal' ? sources[number] : null;
      var sourceHtml = source && source.confident
        ? '<span class="tag tag-' + source.label + '" title="' + sourceTitle(source) + '">' + source.label + '</span>'
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

  function glideRows(a, sample) {
    var gl = glides(a);
    var best = gl.length ? Math.max.apply(null, gl.map(function (s) { return s.average_ld || 0; })) : 1.0;
    return gl.map(function (seg, i) {
      var ld = seg.average_ld ? fmt(seg.average_ld, 1) : '—';
      return '<tr data-segment="' + seg.start + '"' + rowCursor(sample, seg.start) + '><td>' + (i + 1) + '</td>' +
        '<td>' + seg.start_time + '</td><td>' + shortDuration(seg.duration) + '</td><td>' + fmt(seg.distance / 1000, 1) + '</td>' +
        '<td><span class="bar-cell">' + ld + Ch.ldBar(seg.average_ld, best) + '</span></td><td>' + fmt(seg.average_speed, 0) + '</td></tr>';
    }).join('');
  }

  var SHEAR_NOTICEABLE = 1.0;  // m/s, as render_html.SHEAR_NOTICEABLE

  function windShearNote(a) {
    var sounded = thermals(a).filter(function (s) { return s.wind && s.turns && s.turns >= 2; })
      .map(function (s) { return [(s.start_altitude + s.finish_altitude) / 2, s.wind]; });
    if (sounded.length < 3) return 'too few circled climbs to see a trend with height.';
    sounded.sort(function (x, y) { return x[0] - y[0]; });
    var half = Math.floor(sounded.length / 2);
    var lower = sounded.slice(0, half), upper = sounded.slice(sounded.length - half);
    var low = 0, high = 0;
    lower.forEach(function (p) { low += p[1].speed; });
    upper.forEach(function (p) { high += p[1].speed; });
    low /= lower.length; high /= upper.length;
    var change = high - low;
    if (Math.abs(change) < SHEAR_NOTICEABLE) {
      return 'about ' + fmt(low, 1) + ' m/s throughout, with no useful shear between the low climbs and the high ones.';
    }
    return fmt(low, 1) + ' m/s in the lower climbs against ' + fmt(high, 1) + ' m/s in the higher ones — ' +
      fmt(Math.abs(change), 1) + ' m/s ' + (change > 0 ? 'stronger' : 'lighter') + ' with height.';
  }

  function histogramVerdict(a) {
    var data = a.climb_histogram;
    if (!data || !data.counts || !data.counts.some(Boolean)) return 'no time circling';
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
    return 'mostly ' + fmt(mode, 1, { plus: true }) + ' m/s, best sustained about ' + fmt(best, 0, { plus: true }) + ' m/s, ' +
      fmt(sink / total * 100, 0) + '% of the circling in sink';
  }

  function airFetchSection(a) {
    var f = a.flight, middle = Math.floor(f.lat.length / 2);
    return '\n  <section class="air-fetch" data-air-lat="' + fmt(f.lat[middle], 3) + '"\n' +
      '           data-air-lon="' + fmt(f.lon[middle], 3) + '" data-air-epoch="' + Math.trunc(f.time[middle]) + '"\n' +
      '           data-air-top="' + fmt(a.summary.max_altitude, 0) + '">\n' +
      '    <div class="section-head"><h2>The air that day</h2></div>\n    <div class="stats air-stats"></div>\n  </section>';
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
      return '<p class="caption" style="margin-top:16px">No vertical profile is available for this date: the reanalysis archive serves surface fields for any past day but returns nothing on pressure levels, so the sounding and the wind comparison are missing here. Flights from the last two months get the full profile.</p>';
    }
    return '<div class="grid-2" style="margin-top:22px">\n      <div>\n' +
      '        <div class="panel" style="padding:14px 16px 6px">' + Ch.sounding(meteo, a, uid) + '</div>\n' +
      '        <ul class="legend">\n          <li><span class="swatch" style="background:var(--climb)"></span>temperature</li>\n' +
      '          <li><span class="swatch" style="background:var(--sink)"></span>dew point</li>\n' +
      '          <li><span class="swatch" style="background:var(--neutral)"></span>dry adiabat from the\n            surface</li>\n        </ul>\n' +
      '        <p class="caption">Where the dry adiabat crosses the temperature curve is as high as a\n          surface thermal can get without help. The shaded band is the altitude you actually\n          used.</p>\n      </div>\n' +
      '      <div>\n        <div class="panel" style="padding:14px 16px 4px">\n          <div class="table-scroll">\n            <table>\n' +
      '              <thead><tr><th>climb</th><th>start</th><th>height m</th><th>m/s</th><th>from</th>\n' +
      '                <th>model m/s</th><th>model from</th><th>&Delta; dir</th></tr></thead>\n' +
      '              <tbody>' + rows.join('') + '</tbody>\n            </table>\n          </div>\n        </div>\n' +
      '        <p class="caption">Wind from circle drift against the model at the same height. Agreement\n          here is the strongest evidence that the drift method works — nothing in the flight data\n          knows about the model, and nothing in the model knows about the flight.</p>\n      </div>\n    </div>';
  }

  function meteoSection(a, meteo, uid) {
    if (!meteo) return '';
    var summary = a.summary, offset = summary.baro_offset || 0, flightTop = summary.max_altitude + offset;
    var spread = meteo.surface_temperature - meteo.surface_dew_point;
    var cloudbase = Met.cloudbase(meteo), thermalTop = Met.thermalTop(meteo), blTop = Met.boundaryLayerTop(meteo);
    var chips = [['surface', fmt(meteo.surface_temperature, 0) + ' °C', 'dew ' + fmt(meteo.surface_dew_point, 0) + ' °C · spread ' + fmt(spread, 0) + ' K'],
                 ['cloudbase', spaced(cloudbase) + ' m', fmt(spread, 0) + ' K spread, lifted until it closes']];
    if (thermalTop) chips.push(['thermal top', spaced(thermalTop) + ' m', 'dry adiabat meets the profile']);
    if (blTop) chips.push(['boundary layer', spaced(blTop) + ' m', "as high as the day's heating reaches"]);
    if (meteo.cape !== null) {
      chips.push(['cape', fmt(meteo.cape, 0) + ' J/kg', meteo.cloud_cover_low !== null ? 'low cloud ' + fmt(meteo.cloud_cover_low, 0) + '%' : 'instability']);
    }
    var chipHtml = chips.map(function (c) {
      return '<div class="stat"><span class="key">' + c[0] + '</span><span class="stat-value">' + c[1] + '</span><span class="sub">' + c[2] + '</span></div>';
    }).join('');
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
      ceilingNote = '<p>The sounding puts the dry thermal top at ' + spaced(thermalTop) + '&nbsp;m and you topped out ' + verdict +
        ' it.' + capNote(meteo) + '</p>';
    }
    return '\n  <section>\n    <div class="section-head">\n      <h2>The air that day</h2>\n' +
      '      <p>' + esc(meteo.source) + ' over the middle of the course line, valid ' + esc(meteo.valid_at) + '.\n' +
      '         Fetched once and embedded — the report makes no requests when you open it.</p>\n    </div>\n' +
      '    <div class="stats">' + chipHtml + '</div>\n    ' + meteoProfile(a, meteo, uid, rows) + '\n' +
      '    <div class="notes" style="margin-top:20px">\n      ' + ceilingNote + '\n' +
      '      <p><strong>Model, not measurement.</strong> This is a model\'s analysis for a point near the\n' +
      '        course line, not a radiosonde ascent. Treat the ceilings as ±100&nbsp;m and the winds as\n        indicative.</p>\n    </div>\n  </section>';
  }

  function verdictStrip(result) {
    if (!result || !result.verdict) return '';
    var v = result.verdict;
    var numbers = v.headline.map(function (item) {
      return '<div class="verdict-figure" data-key="' + esc(item.key || '') + '"><span class="verdict-value">' + esc(item.value) +
        '</span><span class="verdict-label">' + esc(item.label) + '</span><span class="verdict-delta" hidden></span></div>';
    }).join('');
    return '\n  <div class="verdict">\n    <p class="verdict-line">' + esc(v.sentence) + '</p>\n    <div class="verdict-figures">' + numbers + '</div>\n  </div>';
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

  function debriefCards(result, uid, sample, context, reason) {
    if (!result || !result.findings.length) return '';
    var cards = result.findings.map(function (finding) {
      var footer = finding.at ? '<span class="finding-when">' + esc(finding.at) + '</span>' : '', link = '';
      if (finding.cursor !== null && sample && sample.length) {
        link = '<button type="button" class="finding-link" data-finding-cursor="' + Ch.samplePosition(sample, finding.cursor) + '">show me &rarr;</button>';
      }
      return '<article class="finding" data-finding="' + esc(finding.id) + '"><p class="finding-cost"><span class="finding-dot"></span>cost ' +
        esc(TV.debrief.costLabel(finding.cost)) + '</p><h3>' + esc(finding.title) + '</h3><p class="finding-body">' + esc(finding.sentence) +
        '</p><p class="finding-foot">' + footer + link + '</p></article>';
    });
    var reasons = { terrain: 'ground clearance needs an elevation model, which this report has none of',
                    meteo: reason || "the day's sounding is not in this report",
                    route: 'the route findings need a scored route', sampling: 'this track is too coarse to count circles' };
    var missing = result.suppressed.filter(function (k) { return k in reasons; }).map(function (k) { return reasons[k]; });
    var ctx = context.trim() ? '<p class="caption debrief-context">' + context.trim() + '</p>' : '';
    var note = missing.length ? '<p class="caption debrief-note">Some findings are not computed here: ' + esc(missing.join('; ')) + '.</p>' : '';
    return '\n  <section id="debrief-' + uid + '">\n    <div class="section-head">\n      <h2>Debrief</h2>\n' +
      '      <p>The measurements this flight supports, ranked by what they cost. Each one is a\n         number and where to find it — never advice: the tool cannot see the sky, the\n         gaggle, the airspace or the plan, and you were there.</p>\n    </div>\n' +
      '    <div class="findings">' + cards.join('') + '</div>\n    ' + ctx + '\n    ' + note + '\n  </section>';
  }

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
    var chip = wing ? '<span class="cert" title="' + esc(wing.name + ' — ' + wing.certificate + ', ' + wing.source + (wing.note ? ' (' + wing.note + ')' : '')) + '">' + esc(wing.label) + '</span>' : '';
    var identity = [['pilot', summary.pilot || '—', ''], ['glider', summary.glider || '—', chip], ['site', summary.site || '—', '']]
      .map(function (r) { return '<div><span class="key">' + r[0] + '</span><span class="val">' + esc(r[1]) + r[2] + '</span></div>'; }).join('');

    var peakIndex = 0;
    a.series.alt.forEach(function (v, i) { if (v > a.series.alt[peakIndex]) peakIndex = i; });
    var peakTime = igc.clock(f.time[peakIndex], f.timezone).slice(0, 5);
    var offset = summary.baro_offset || 0;
    var coarse = summary.sample_interval > A.constants.TURN_RESOLUTION_LIMIT;
    var sample = sampleIndices(a), planH = Ch.planHeight(a);
    var withWind = th.filter(function (s) { return s.wind; }).length;
    var routeShape = route ? TV.xc.shape(route) : null;
    var tiles = [
      stat('airtime', duration(summary.duration), '', summary.takeoff_time + ' – ' + summary.landing_time),
      stat('xc distance', route ? fmt(route.distance / 1000, 2) : '—', ' km',
           route ? (SHAPE_LABEL[routeShape] || 'open distance') + ' · ' + fmt(summary.track_distance / 1000, 0) + ' km flown, ' +
                   fmt(summary.straight_distance / 1000, 0) + ' km straight' : ''),
      stat('height gained', spaced(summary.total_gain), ' m', 'best single climb ' + fmt(summary.max_gain, 0) + ' m'),
      stat('mean climb', fmt(climbRate, 2, { plus: true }), ' m/s', th.length + ' climbs' + (!coarse ? ' · ' + fmt(totalTurns, 0) + ' turns' : '')),
      stat.apply(null, ceilingTile(a, meteo, peakTime, offset)),
      stat('wind', a.wind ? fmt(a.wind.speed, 1) : '—', ' m/s',
           a.wind ? 'from ' + a.wind.cardinal + ' · averaged over ' + withWind + ' climbs' : '')
    ];
    if (tow) {
      tiles.push(stat('off tow at', spaced(tow.finish_altitude), ' m',
                      fmt(tow.altitude_change, 0, { plus: true }) + ' m in ' + shortDuration(tow.duration) + ' of tow'));
    }
    var ramp = Ch.CLIMB_RAMP.map(function (r) { return '<span style="background:' + r[1] + '"></span>'; }).join('');
    var towNote = '';
    if (tow) {
      towNote = '<p><strong>Launch classified as a tow.</strong> The first climb — ' + shortDuration(tow.duration) + ', ' +
        fmt(tow.altitude_change, 0, { plus: true }) + ' m at ' + fmt(tow.average_climb, 2, { plus: true }) + ' m/s, released at ' +
        fmt(tow.finish_altitude, 0) + ' m — starts with the flight, climbs steadily and was flown almost straight (' +
        (tow.swept_turns !== null ? fmt(tow.swept_turns, 1) + ' turns of heading' : 'nearly straight') + '). It is kept out of the thermal statistics and out of the wind estimate, where a straight climb would have measured the glider\'s own track rather than the air.</p>';
    }
    // The side view: the chart, then its axis buttons and legend under it. With a 3D map
    // it sits in the map's own block (`.flight-map`), joined to it and going full screen
    // with it, where the buttons and the legend are not shown.
    var sideChart = '\n    <div class="panel hero side-view">\n' +
      '      <div class="profile chart-host" data-chart="profile" data-mode="flown"\n           style="aspect-ratio:' + Ch.PROFILE.width + '/' + Ch.PROFILE.height + '">\n' +
      '        <p class="chart-missing">The side view is drawn in this page, from the same\n          numbers the hover cursor reads. It needs JavaScript; everything above it does\n          not.</p>\n      </div>\n    </div>\n';
    var sideControls = '    <div class="side-controls">\n' +
      '    <div class="toggle" role="group" aria-label="Ground axis for the side view">\n' +
      '      <button type="button" class="toggle-button is-on" data-profile="flown" aria-pressed="true">\n        distance flown</button>\n' +
      '      <button type="button" class="toggle-button" data-profile="from_start" aria-pressed="false">\n        from launch</button>\n' +
      '      <button type="button" class="toggle-button" data-profile="time" aria-pressed="false">\n        time</button>\n    </div>\n' +
      '    <ul class="legend">\n      <li class="ramp">' + ramp + '</li>\n      <li>trace colour: sink &minus;4 m/s → climb +4 m/s</li>\n' +
      '      <li><span class="swatch" style="background:var(--tow);opacity:.5"></span>tow</li>\n' +
      '      <li><span class="swatch" style="background:var(--climb);opacity:.5"></span>climbing</li>\n' +
      '      <li><span class="swatch" style="background:var(--sink);opacity:.5"></span>gliding</li>\n    </ul>\n    </div>';
    var sideView = sideChart + sideControls;

    var view3dSection, clearance = null, valley = null;
    if (terrain) {
      var payload = TV.scene.data(a, options.sceneTerrain || terrain, { airspaceRemote: options.airspaceRemote });
      clearance = TV.terrain.clearance(terrain, a);
      valley = TV.terrain.valleyClearance(terrain, a);
      view3dSection = '\n  <section>\n    <div class="section-head">\n      <h2>The flight over the ground</h2>\n' +
        '      <p>Hovering a moment in the side view marks the same moment on the map above, and in\n         the top view below. Click to keep it there while you look; click again, or press\n' +
        '         <kbd>Esc</kbd>, to let go. A row in the climbs or glides table does the same for\n         where that phase began.' +
        (payload.airspaceRemote ? " <strong>Airspace</strong> draws the zones this flight came within 5 km and 200 m (height) of, as the boxes they are, floor to ceiling — hover one for its name and limits. Zones that bind nobody (danger and firing areas, sport and alert areas, gliding sectors) are left out, and so are those active only by NOTAM: NOTAMs are not fetched, so one activated during the flight is missing too. Airspace &copy; <a href=\"https://www.openaip.net\" rel=\"noreferrer\">openAIP</a>, CC BY-NC 4.0, refreshed monthly; in Czechia the traffic circuits are this site's own, from ŘLP publications." : '') +
        '</p>\n    </div>\n    <div class="flight-map">\n    <div class="renderer-host">\n    ' +
        TV.scene.panel(payload, uid) +
        '\n    </div>' + sideChart + '    </div>\n' + sideControls + '\n  </section>';
    } else {
      view3dSection = '\n  <section>\n    <div class="section-head">\n      <h2>The flight from the side</h2>\n' +
        '      <p>Hovering a moment marks the same moment in the top view below. Click to keep it\n         there while you look; click again, or press <kbd>Esc</kbd>, to let go.</p>\n    </div>\n' +
        sideView + '\n  </section>';
    }

    var windChart = Ch.windProfile(a, meteo, uid), histogram = Ch.climbHistogram(a);
    var metSection = meteo ? meteoSection(a, meteo, uid) : airFetchSection(a);

    var airNote = '', field = TV.airmass.field(a, weather), perf = TV.airmass.glidePerformance(a, field);
    if (perf) {
      var curve = TV.airmass.polar(a, field);
      var bestNote = curve && curve.best_glide ? ' Your best glides came at about ' + fmt(curve.best_glide[0], 0) +
        ' km/h through the air, where the wing returned ' + fmt(curve.best_glide[1], 1) + ':1.' : '';
      if (curve && !curve.monotone) {
        bestNote = ' No best-glide speed is given: over these glides the measured sink does not rise steadily with airspeed, which a wing\'s does, so the curve is describing the air they were flown in as much as the glider. One flight is not a polar.';
      }
      airNote = " Taking the wind out of it, the wing's own median glide was <strong>" + fmt(perf.air_ld, 1) + ':1</strong> at ' +
        fmt(perf.median_airspeed, 0) + ' km/h through the air, against ' + fmt(perf.ground_ld, 1) +
        ':1 measured over the ground. The wind subtracted is the one sounded from ' + field.soundings.length +
        ' circled climbs, which this flight supports to about ' + fmt(perf.confidence, 0, { percent: true }) + '.' + bestNote;
    }

    var result = TV.debrief.build(a, { route: route, weather: weather, clearance: clearance, valley: valley, flightPlan: options.flightPlan || null });
    var sources = TV.insolation.sources(a, terrain);
    var debriefSection = debriefCards(result, uid, sample, clearanceNote(clearance) + ' ' + triggerNote(a, terrain),
                                      meteo ? '' : meteoReason(a, now));
    var use = M.ceilingUse(a, weather);
    var compare = [['scored-km', route ? pyFloat(R(route.distance / 1000.0, 2)) : null],
                   ['mean-climb', th.length ? pyFloat(R(climbRate, 2)) : null],
                   ['ceiling-used', use ? pyFloat(use.fraction) : null]]
      .filter(function (c) { return c[1] !== null; }).map(function (c) { return ' data-compare-' + c[0] + '="' + c[1] + '"'; }).join('');
    var compareName = esc([summary.date, summary.site].filter(Boolean).join(' · '));
    var glideCount = glides(a).length;
    var otherFraction = budget.fractions.other;

    return '<article class="flight" data-flight-report="' + uid + '"' + compare + ' data-compare-name="' + compareName + '"' + (options.hidden ? ' hidden' : '') + '>\n' +
      '  <header class="masthead">\n    <div>\n      <p class="eyebrow">tracklog viewer</p>\n' +
      '      <h1>' + esc(summary.site || 'Flight') + ' <span>' + esc(summary.date) + '</span></h1>\n    </div>\n' +
      '    <div class="identity">' + identity + '</div>\n  </header>\n' + verdictStrip(result) + '\n\n' + view3dSection + '\n\n' +
      '  <section>\n    <div class="section-head">\n      <h2>Top view</h2>\n      <p>The same flight seen from above, on the same cursor as the side view.</p>\n    </div>\n' +
      '    <div class="panel hero">\n      <div class="chart-head">\n        <p class="chart-title">The course line over the ground.' +
      (route ? ' Thin straight legs are the scored free-distance route.' : '') + '</p>\n' +
      '        <div class="toggle toggle-small" role="group" aria-label="What the climb circles show">\n' +
      '          <button type="button" class="toggle-button is-on" data-circles="gain"\n                  aria-pressed="true">size = height gained</button>\n' +
      '          <button type="button" class="toggle-button" data-circles="rate"\n                  aria-pressed="false">size = climb rate</button>\n        </div>\n      </div>\n' +
      '      <div class="chart-host" data-chart="plan"\n           style="aspect-ratio:' + Ch.PLAN.width + '/' + planH + '">\n' +
      '        <p class="chart-missing">The top view is drawn in this page. It needs\n          JavaScript.</p>\n      </div>\n    </div>\n  </section>\n' +
      debriefSection + '\n\n  <section>\n    <div class="stats">' + tiles.join('') + '</div>\n  </section>\n\n' +
      '  <section>\n    <div class="section-head">\n      <h2>Where the time went</h2>\n' +
      '      <p>' + duration(budget.thermalling) + ' climbing across ' + th.length + ' thermals,\n        ' + duration(budget.gliding) +
      ' gliding, and ' + duration(budget.other) + ' that was\n        neither.' + otherNote(a) + '</p>\n    </div>\n' +
      '    <div class="panel" style="padding:18px 20px 12px">\n      ' + Ch.budgetBar(a, 1040) + '\n    </div>\n  </section>\n\n' +
      '  <section class="grid-2">\n    <div>\n      <div class="section-head"><h2>Wind, sounded by thermal</h2></div>\n' +
      '      <div class="panel" style="padding:14px 16px 6px">' + (windChart || '<p class="caption">Not enough circled climbs to sound the wind.</p>') + '</div>\n' +
      '      <ul class="legend">\n        <li><span class="swatch" style="background:var(--sink)"></span>measured from circle drift</li>\n        ' +
      (meteo ? '<li><span class="swatch" style="background:var(--neutral)"></span>model profile for the day</li>' : '') + '\n      </ul>\n' +
      '      <p class="caption">One point per climb, numbered as in the table below and therefore in the\n        order flown — the first and last carry their clock time, and hovering any point gives the\n' +
      '        rest. Height is where the climb was worked; the tail points downwind. Reading it bottom to\n        top: ' + windShearNote(a) +
      (meteo ? '' : " The day's forecast profile would be drawn behind these as a check on them, but " + meteoReason(a, now) + '.') + '</p>\n    </div>\n' +
      '    <div>\n      <div class="section-head">\n        <h2>How strong was the lift you sat in?</h2>\n      </div>\n' +
      '      <div class="panel" style="padding:14px 16px 6px">' + (histogram || '<p class="caption">No thermalling time to summarise.</p>') + '</div>\n' +
      '      <p class="caption">Every second spent circling, sorted into half-metre climb-rate buckets.\n        The tallest bar is the climb rate you spent the most time in — not the best one you found.\n' +
      '        Bars left of zero are time spent turning in <em>sink</em>. The right-hand tail is the\n        cores. This day reads as ' + histogramVerdict(a) + '.</p>\n    </div>\n  </section>\n\n' +
      '  <section>\n    <div class="section-head">\n      <h2>Climbs</h2>\n' +
      '      <p><strong>Eff</strong> is mean climb over the best 20&nbsp;s of the same climb — the\n         closest single number to &ldquo;did you stay in the core&rdquo;. <strong>Rev</strong>\n' +
      '         counts reversals: the times the turn changed direction mid-climb, so a thermal\n         circled one way throughout reads zero. With <strong>radius</strong> it says how\n' +
      '         tidily the climb was flown. <strong>Lift</strong> reads\n         <em>ridge</em> only when three things agree — a steep face, the wind running into\n' +
      '         it, and you within ' + fmt(TV.insolation.RIDGE_CLEARANCE, 0) + '&nbsp;m of the slope — and\n         <em>thermal</em> otherwise; a dash means there was nothing to check it\n         against.' +
      (coarse ? ' This track is sampled every ' + fmt(summary.sample_interval, 0) + ' s, which is too coarse to resolve a circle, so the turn columns are blank.' : '') + '</p>\n    </div>\n' +
      '    <div class="toggle toggle-small" role="group" aria-label="Circling detail columns">\n' +
      '      <button type="button" class="toggle-button" data-detail="circling" aria-pressed="false">\n        &#8853; circling detail</button>\n    </div>\n' +
      '    <div class="panel" style="padding:14px 16px 4px">\n      <div class="table-scroll">\n        <table class="table-climbs">\n          <thead><tr>\n' +
      '            <th>#</th><th>start</th><th>time</th><th>gain m</th><th>top m</th>\n            <th>avg m/s</th><th>eff</th><th>lift</th>\n' +
      '            <th class="circling-detail">turns</th><th class="circling-detail">m/turn</th>\n            <th class="circling-detail">dir</th><th class="circling-detail">rev</th>\n' +
      '            <th class="circling-detail">s/turn</th>\n            <th class="circling-detail">radius m</th>\n            <th>over time &rarr;</th>\n          </tr></thead>\n' +
      '          <tbody>' + thermalRows(a, sample, sources) + '</tbody>\n        </table>\n      </div>\n    </div>\n  </section>\n\n' +
      '  <section>\n    <div class="section-head">\n      <h2>Glides</h2>\n      <p>Glide ratio in this table is over the ground, so it carries whatever the wind was\n         doing as well as the wing.' +
      airNote + '</p>\n    </div>\n    <ul class="legend" style="margin:0 0 12px">\n      <li class="legend-title">glide ratio:</li>\n' +
      '      <li><span class="swatch" style="background:var(--ld-1)"></span>under 5</li>\n      <li><span class="swatch" style="background:var(--ld-2)"></span>5–7</li>\n' +
      '      <li><span class="swatch" style="background:var(--ld-3)"></span>7–9</li>\n      <li><span class="swatch" style="background:var(--ld-4)"></span>9–12</li>\n' +
      '      <li><span class="swatch" style="background:var(--ld-5)"></span>over 12</li>\n    </ul>\n' +
      '    <div class="panel" style="padding:14px 16px 4px">\n      <div class="table-scroll">\n        <table>\n          <thead><tr><th>#</th><th>start</th><th>time</th><th>km</th>\n' +
      '            <th>glide</th><th>km/h</th></tr></thead>\n          <tbody>' + glideRows(a, sample) + '</tbody>\n        </table>\n      </div>\n    </div>\n  </section>\n\n' +
      metSection + '\n\n  <section>\n    <div class="section-head"><h2>How to read this, and what to distrust</h2></div>\n    <div class="notes">\n      ' + towNote + '\n' +
      '      <p><strong>Altitude is ' + (summary.altitude_source === 'baro' ? 'barometric' : 'GPS') + '.</strong>\n        ' +
      (summary.altitude_source === 'baro'
        ? 'This recorder has a pressure sensor, so climb rates come from the smooth baro trace. It reads ISA pressure altitude, sitting ' +
          String(summary.baro_offset) + ' m below the GPS altitude on the day — absolute heights are indicative, height changes are solid.'
        : 'This recorder has no pressure sensor, so both altitude and climb come from GPS and are noisier than they look.') + '</p>\n      ' +
      (coarse ? '<p><strong>Coarse sampling.</strong> This track has a fix every ' + fmt(summary.sample_interval, 0) + ' s. A thermal circle takes about 20 s, so turn counting, circle radius and peak climb rate cannot be recovered — they are left blank rather than guessed, and distance flown reads low because the sampling cuts the corners off every turn. Analyse the IGC instead of a KML where you have it.</p>' : '') + '\n' +
      '      <p><strong>A climb is the circling, not the run-in to it.</strong> A climb is time\n        spent turning in lift and a glide is time spent going somewhere without it. The\n' +
      '        straight run into a thermal is neither, and lands in the unclassified time\n        below.</p>\n' +
      "      <p><strong>Wind is inferred, not measured.</strong> While circling, the glider's own\n        airspeed averages out and the track drifts with the air. Climbs flown fewer than two\n" +
      '        full turns, or in both directions, are excluded — they measure the pilot, not the\n        wind. On a track sampled too coarsely to count turns at all, a climb of two minutes\n' +
      "        or more is used instead: the drift is still the air's, and there is nothing better.</p>\n" +
      '      <p><strong>"Ridge" is three measurements agreeing, and "thermal" is everything\n        else.</strong> A climb is called ridge when the ground under it was steeper than\n' +
      '        ' + fmt(TV.insolation.RIDGE_SLOPE, 0) + '°, the glider stayed within\n        ' + fmt(TV.insolation.RIDGE_CLEARANCE, 0) + ' m of it, and the track beat along the slope\n' +
      '        rather than closing circles — hover a label to see all three for that climb.\n        Convergence is deliberately not a label: its honest signature is a climb drifting\n' +
      '        differently from the air around it, and one tracklog cannot tell that from a ridge\n        climb holding station or a badly sounded wind. Without terrain there is nothing to\n' +
      '        check and the column shows a dash rather than guessing.</p>\n      ' +
      (wing ? "<p><strong>The class beside the glider is the certifier's, not ours.</strong> It is " + esc(wing.label) + ' according to ' + esc(wing.source) +
              ", under " + esc(wing.certificate) + "; hover the chip for the reference. A class is looked up on the wing's name, and a header names the wing but not its size, so where a model's sizes are certified differently the chip shows the class most of them carry" +
              (wing.note ? ' — here ' + esc(wing.note.replace(/^most sizes; /, '')) : '') + ". LTF and EN are never translated into each other. Certification describes the wing's behaviour in a test, and says nothing about this flight.</p>" : '') + '\n' +
      '      <p>The ' + glideCount + ' glides and ' + th.length + ' climbs account for\n        ' + fmt((1 - otherFraction) * 100, 0) +
      '% of airtime. The rest is transitions too\n        short or too ambiguous to call, which is honest rather than tidy.</p>\n    </div>\n  </section>\n\n' +
      '  <footer>\n    <span>' + summary.fixes.toLocaleString('en-US') + ' fixes at ' + fmt(summary.duration / summary.fixes, 1) +
      ' s · timezone from\n      ' + esc(summary.timezone || 'UTC') + '</span>\n    <span>tracklog viewer · your track is analysed in this page and never uploaded</span>\n  </footer>\n' +
      '  <script type="application/json" class="cursor-data">' + JSON.stringify(cursorData(a, clearance)) + '</script>\n' +
      '  <script type="application/json" class="chart-data">' + JSON.stringify(Ch.payload(a, meteo, route, sample, planH)) + '</script>\n</article>\n';
  }

  TV.report = { flightBody: flightBody, cursorData: cursorData, sampleIndices: sampleIndices, duration: duration,
                shortDuration: shortDuration,
                // The pieces of the article a test asks about one at a time.
                parts: { windShearNote: windShearNote, clearanceNote: clearanceNote, triggerNote: triggerNote } };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

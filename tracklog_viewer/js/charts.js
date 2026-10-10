/* The report's built charts: `tracklog_viewer/charts.py` (the ones the article bakes in)
 * and `charts_client.payload`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * The output was the Python's SVG, element for element and attribute for attribute, so
 * the page's CSS, the linked cursor and the tooltips went on working across the port.
 * The side and top views are not here: those are drawn in the page (`page/charts.js`),
 * and this only builds the payload they draw from.
 *
 * `meteo` throughout is the object `TV.meteo.parse` returns.
 */
(function (TV) {
  'use strict';
  var np = TV.np, igc = TV.igc, Met = TV.meteo, fmt = np.fmt;

  var CLIMB_RAMP = [
    [-4.0, 'var(--sink-3)'], [-2.0, 'var(--sink-2)'], [-0.7, 'var(--sink-1)'], [0.7, 'var(--neutral)'],
    [2.0, 'var(--climb-1)'], [4.0, 'var(--climb-2)'], [Infinity, 'var(--climb-3)']
  ];
  var WIND_SPEED_STEP = 1, WIND_ALT_STEP = 250, WIND_MODEL_BAND = 400;
  var LD_STEPS = [[5.0, 'var(--ld-1)'], [7.0, 'var(--ld-2)'], [9.0, 'var(--ld-3)'], [12.0, 'var(--ld-4)'],
                  [Infinity, 'var(--ld-5)']];
  var PROFILE = { width: 1080, height: 420, left: 56, right: 20, top: 20, bottom: 46 };
  var PLAN = { width: 1080, pad: 26 };

  function f1(x) { return fmt(x, 1); }
  function escape(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function climbColor(value) {
    for (var i = 0; i < CLIMB_RAMP.length; i++) if (value < CLIMB_RAMP[i][0]) return CLIMB_RAMP[i][1];
    return CLIMB_RAMP[CLIMB_RAMP.length - 1][1];
  }
  function ldColor(value) {
    if (value === null || value === undefined) return 'var(--neutral)';
    for (var i = 0; i < LD_STEPS.length; i++) if (value < LD_STEPS[i][0]) return LD_STEPS[i][1];
    return LD_STEPS[LD_STEPS.length - 1][1];
  }
  function range(start, stop, step) { var out = []; for (var v = start; v < stop; v += step) out.push(v); return out; }
  function thermals(a) { return a.segments.filter(function (s) { return s.phase === 'thermal'; }); }

  function withHeadroom(ceiling, dataMax, meteo) {
    if (!meteo) return ceiling;
    [Met.boundaryLayerTop(meteo), Met.cloudbase(meteo)].forEach(function (value) {
      if (value !== null && value !== undefined && ceiling < value && value <= dataMax + 1000) {
        ceiling = Math.ceil(value / 100) * 100;
      }
    });
    return ceiling;
  }

  function planHeight(a, width, floor, ceiling) {
    width = width || 1080; floor = floor || 260; ceiling = ceiling || 620;
    var s = a.series;
    var spanX = Math.max(np.max(s.x) - np.min(s.x), 1.0), spanY = Math.max(np.max(s.y) - np.min(s.y), 1.0);
    return Math.trunc(Math.min(Math.max(np.pyRound(width * spanY / spanX) + 70, floor), ceiling));
  }

  // The time bar's parts, in its order: key, colour, label, fraction and seconds. The
  // article's legend under the bar reads the same list, so every segment is named even
  // where the bar has no room for a label.
  function budgetParts(a) {
    var fractions = Object.assign({}, a.budget.fractions), seconds = {
      towing: a.budget.towing, thermalling: a.budget.thermalling, gliding: a.budget.gliding, other: a.budget.other };
    var order = [['towing', 'var(--tow)', 'Tow'], ['thermalling', 'var(--climb)', 'Climbing'],
                 ['gliding', 'var(--sink)', 'Gliding']];
    var slice = a.other, total = a.budget.thermalling + a.budget.gliding + a.budget.diving + a.budget.towing + a.budget.other || 1;
    if (slice && slice.seconds) {
      var split = { other_sink: slice.straight_sink / total, other_scratch: slice.scratching / total,
                    other_rising: slice.rising / total };
      var keys = ['other_sink', 'other_scratch', 'other_rising'], biggest = keys[0];
      keys.forEach(function (k) { if (split[k] > split[biggest]) biggest = k; });
      split[biggest] += fractions.other - (split.other_sink + split.other_scratch + split.other_rising);
      Object.assign(fractions, split);
      seconds.other_sink = slice.straight_sink; seconds.other_scratch = slice.scratching; seconds.other_rising = slice.rising;
      order = order.concat([['other_sink', 'var(--neutral)', 'Sinking straight'], ['other_scratch', 'var(--shadow-ink)', 'Turning, no climb'],
                            ['other_rising', 'var(--climb-1)', 'Drifting up']]);
    } else {
      order.push(['other', 'var(--neutral)', 'Other']);
    }
    return order.map(function (o) {
      return { key: o[0], colour: o[1], label: o[2], fraction: fractions[o[0]] || 0, seconds: seconds[o[0]] || 0 };
    });
  }

  function budgetBar(a, width, height) {
    width = width || 460; height = height || 58;
    var fractions = {}, order = budgetParts(a).map(function (p) {
      fractions[p.key] = p.fraction; return [p.key, p.colour, p.label]; });
    var gap = 2, barH = 26, parts = [], labels = [], x = 0.0;
    var totalGaps = gap * (order.filter(function (o) { return fractions[o[0]] > 0; }).length - 1);
    var usable = width - totalGaps;
    order.forEach(function (o) {
      var fraction = fractions[o[0]];
      if (fraction <= 0) return;
      var w = usable * fraction;
      parts.push('<rect x="' + f1(x) + '" y="0" width="' + f1(w) + '" height="' + barH + '" rx="3" fill="' + o[1] + '" />');
      if (fraction > 0.06) {
        var labelX = Math.min(Math.max(x + w / 2, 26.0), width - 26.0);
        labels.push('<text x="' + f1(labelX) + '" y="' + (barH + 18) + '" class="budget-label">' + o[2] + ' ' +
                    fmt(fraction * 100, 0) + '%</text>');
      }
      x += w + gap;
    });
    return '<svg viewBox="0 0 ' + width + ' ' + height + '" class="chart chart-budget" role="img" ' +
      'aria-label="Share of airtime spent climbing, gliding and under tow">' + parts.join('') + labels.join('') + '</svg>';
  }

  function windProfile(a, meteo, uid, width, height) {
    width = width || 620; height = height || 350; uid = uid || '';
    var th = thermals(a).filter(function (s) { return s.wind && s.turns && s.turns >= 2; });
    if (!th.length) return '';
    var left = 52, right = 58, top = 22, bottom = 42, plotW = width - left - right, plotH = height - top - bottom;
    var speeds = th.map(function (s) { return s.wind.speed; });
    var altitudes = th.map(function (s) { return (s.start_altitude + s.finish_altitude) / 2; });
    var modelLevels = [];
    if (meteo) {
      var lo = Math.min.apply(null, altitudes), hi = Math.max.apply(null, altitudes);
      modelLevels = meteo.levels.filter(function (l) { return lo - WIND_MODEL_BAND <= l.height && l.height <= hi + WIND_MODEL_BAND; });
    }
    var speedMax = Math.max(Math.ceil(Math.max.apply(null, speeds.concat(modelLevels.map(function (l) { return l.wind_speed; })))
                                      / WIND_SPEED_STEP) * WIND_SPEED_STEP, 4 * WIND_SPEED_STEP);
    var heights = altitudes.concat(modelLevels.map(function (l) { return l.height; }));
    var altMin = Math.floor(Math.min.apply(null, heights) / WIND_ALT_STEP) * WIND_ALT_STEP;
    var altMax = Math.ceil(Math.max.apply(null, heights) / WIND_ALT_STEP) * WIND_ALT_STEP;
    function sx(v) { return left + plotW * v / speedMax; }
    function sy(v) { return top + plotH * (1 - (v - altMin) / Math.max(altMax - altMin, 1)); }
    var grid = [], labels = [];
    range(0, Math.trunc(speedMax) + 1, WIND_SPEED_STEP).forEach(function (v) {
      var x = sx(v);
      grid.push('<line x1="' + f1(x) + '" y1="' + top + '" x2="' + f1(x) + '" y2="' + (top + plotH) + '" />');
      labels.push('<text x="' + f1(x) + '" y="' + (top + plotH + 17) + '" class="axis-label axis-x">' + v + '</text>');
    });
    range(Math.trunc(altMin), Math.trunc(altMax) + 1, WIND_ALT_STEP).forEach(function (v) {
      var y = sy(v);
      labels.push('<text x="' + (left - 9) + '" y="' + f1(y + 3.5) + '" class="axis-label axis-y">' + v + '</text>');
      grid.push('<line x1="' + left + '" y1="' + f1(y) + '" x2="' + (width - right) + '" y2="' + f1(y) + '" />');
    });
    var model = '<g class="model"></g>';
    if (modelLevels.length >= 2) {
      var path = modelLevels.map(function (l) { return f1(sx(l.wind_speed)) + ',' + f1(sy(l.height)); }).join(' ');
      var dots = modelLevels.map(function (l) {
        return '<circle cx="' + f1(sx(l.wind_speed)) + '" cy="' + f1(sy(l.height)) + '" r="2.5" class="model-dot"><title>model ' +
          f1(l.wind_speed) + ' m/s from ' + fmt(l.wind_direction, 0) + '° at ' + fmt(l.height, 0) + ' m (' + l.pressure + ' hPa)</title></circle>';
      }).join('');
      model = '<g class="model"><polyline points="' + path + '" />' + dots + '</g>';
    }
    var numbers = {};
    thermals(a).forEach(function (s, i) { numbers[s.start] = i + 1; });
    var points = th.map(function (seg, position) {
      var speed = speeds[position], altitude = altitudes[position];
      var x = sx(speed), y = sy(altitude), angle = np.mod(seg.wind.direction + 180, 360) * np.DEG;
      var ux = Math.sin(angle), uy = -Math.cos(angle);
      var startX = x + ux * 9, startY = y + uy * 9, dx = ux * 26, dy = uy * 26, timeLabel = '';
      if (position === 0 || position === th.length - 1) {
        var anchor = x > left + plotW * 0.6 ? 'end' : 'start', offset = anchor === 'end' ? -16 : 16;
        timeLabel = '<text x="' + f1(x + offset) + '" y="' + f1(y + 3.5) + '" class="wind-time" text-anchor="' + anchor + '">' +
          escape(seg.start_time.slice(0, 5)) + '</text>';
      }
      var n = numbers[seg.start] === undefined ? '' : numbers[seg.start];
      return '<g class="wind-point" data-segment="' + seg.start + '" data-speed="' + fmt(speed, 2) + '" data-alt="' +
        fmt(altitude, 0) + '" data-dir="' + fmt(seg.wind.direction, 0) + '">' +
        '<line x1="' + f1(startX) + '" y1="' + f1(startY) + '" x2="' + f1(x + dx) + '" y2="' + f1(y + dy) +
        '" class="wind-arrow" marker-end="url(#arrow' + uid + ')" />' +
        '<circle cx="' + f1(x) + '" cy="' + f1(y) + '" r="9" class="wind-dot" />' +
        '<text x="' + f1(x) + '" y="' + f1(y) + '" class="wind-number">' + n + '</text>' + timeLabel +
        '<title>climb ' + n + ' at ' + escape(seg.start_time) + ' — ' + f1(speed) + ' m/s from ' +
        escape(seg.wind.cardinal) + ' at ' + fmt(altitude, 0) + ' m</title></g>';
    });
    var frame = JSON.stringify({ left: left, right: right, top: top, bottom: bottom, width: width, height: height,
                                 plotW: plotW, plotH: plotH, speedMax: speedMax, altMin: altMin, altMax: altMax,
                                 speedStep: WIND_SPEED_STEP, altStep: WIND_ALT_STEP, band: WIND_MODEL_BAND,
                                 hasModel: modelLevels.length >= 2 });
    return '<svg viewBox="0 0 ' + width + ' ' + height + '" class="chart chart-wind" role="img"\n' +
      "     data-wind-frame='" + frame + "'\n" +
      '     aria-label="Wind speed measured in each thermal against altitude, with the model\n' +
      '     wind profile for comparison">\n  <defs>\n' +
      '    <marker id="arrow' + uid + '" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="5" markerHeight="5"\n' +
      '            orient="auto"><path d="M0,1 L7,4 L0,7 z" fill="var(--sink)" /></marker>\n  </defs>\n' +
      '  <g class="grid">' + grid.join('') + '</g>\n  ' + model + '\n  <g class="axes">' + labels.join('') + '\n' +
      '    <text x="' + f1(left + plotW / 2) + '" y="' + (height - 5) + '" class="axis-title">Wind, m/s</text>\n' +
      '    <text x="12" y="' + f1(top + plotH / 2) + '" class="axis-title"\n' +
      '          transform="rotate(-90 12 ' + f1(top + plotH / 2) + ')">Altitude, m</text>\n  </g>\n  ' +
      points.join('') + '\n</svg>';
  }

  function sounding(meteo, a, uid, width, height) {
    width = width || 620; height = height || 350; uid = uid || '';
    if (!meteo || !meteo.levels.length) return '';
    var left = 52, right = 20, top = 22, bottom = 42, plotW = width - left - right, plotH = height - top - bottom;
    var summary = a.summary, offset = summary.baro_offset || 0;
    var flightTop = summary.max_altitude + offset, flightBottom = summary.min_altitude + offset;
    var cloudbase = Met.cloudbase(meteo);
    var altMax = Math.ceil(Math.max(flightTop + 300, cloudbase + 200) / 500) * 500;
    var altMin = Math.floor(Math.min(flightBottom, meteo.elevation) / 500) * 500;
    var inside = meteo.levels.filter(function (l) { return altMin <= l.height && l.height <= altMax; });
    if (inside.length < 2) return '';
    var below = meteo.levels.filter(function (l) { return l.height < altMin; });
    var above = meteo.levels.filter(function (l) { return l.height > altMax; });
    var levels = (below.length ? [below[below.length - 1]] : []).concat(inside, above.length ? [above[0]] : []);
    var temps = inside.map(function (l) { return l.temperature; }).concat(inside.map(function (l) { return l.dew_point; }));
    var tMin = Math.floor(Math.min.apply(null, temps.concat([meteo.surface_dew_point])) / 5) * 5;
    var tMax = Math.ceil(Math.max.apply(null, temps.concat([meteo.surface_temperature])) / 5) * 5;
    function sx(v) { return left + plotW * (v - tMin) / Math.max(tMax - tMin, 1); }
    function sy(v) { return top + plotH * (1 - (v - altMin) / Math.max(altMax - altMin, 1)); }
    var grid = [], labels = [];
    range(Math.trunc(tMin), Math.trunc(tMax) + 1, 5).forEach(function (v) {
      var x = sx(v);
      grid.push('<line x1="' + f1(x) + '" y1="' + top + '" x2="' + f1(x) + '" y2="' + (top + plotH) + '" />');
      labels.push('<text x="' + f1(x) + '" y="' + (top + plotH + 17) + '" class="axis-label axis-x">' + v + '</text>');
    });
    range(Math.trunc(altMin), Math.trunc(altMax) + 1, 500).forEach(function (v) {
      var y = sy(v);
      grid.push('<line x1="' + left + '" y1="' + f1(y) + '" x2="' + (width - right) + '" y2="' + f1(y) + '" />');
      labels.push('<text x="' + (left - 9) + '" y="' + f1(y + 3.5) + '" class="axis-label axis-y">' + v + '</text>');
    });
    var environment = levels.map(function (l) { return f1(sx(l.temperature)) + ',' + f1(sy(l.height)); }).join(' ');
    var dewpoint = levels.map(function (l) { return f1(sx(l.dew_point)) + ',' + f1(sy(l.height)); }).join(' ');
    var adiabat = [], altitude = meteo.elevation;
    while (altitude <= altMax) {
      var temperature = meteo.surface_temperature - 9.8 / 1000 * (altitude - meteo.elevation);
      adiabat.push(f1(sx(temperature)) + ',' + f1(sy(altitude)));
      altitude += 100;
    }
    var band = '<rect class="flight-band" x="' + left + '" y="' + f1(sy(flightTop)) + '" width="' + plotW + '" height="' +
      f1(Math.max(sy(flightBottom) - sy(flightTop), 1)) + '" />' +
      '<text x="' + (left + 6) + '" y="' + f1(sy(flightBottom) - 6) + '" class="reference-label band-label">Flown ' +
      fmt(flightBottom, 0) + '–' + fmt(flightTop, 0) + ' m</text>';
    var candidates = [[Met.thermalTop(meteo), 'Thermal top', 'thermal-top'], [cloudbase, 'Cloudbase', 'cloudbase'],
                      [Met.boundaryLayerTop(meteo), 'Boundary layer', 'bl-top']].filter(function (c) {
      return c[0] !== null && c[0] !== undefined && altMin <= c[0] && c[0] <= altMax;
    });
    var references = candidates.map(function (c, index) {
      var y = sy(c[0]);
      var anchor = index % 2 ? 'x="' + (left + 6) + '" class="reference-label band-label"'
                             : 'x="' + (width - right - 4) + '" class="reference-label"';
      return '<line class="reference ' + c[2] + '" x1="' + left + '" y1="' + f1(y) + '" x2="' + (width - right) + '" y2="' + f1(y) + '" />' +
        '<text ' + anchor + ' y="' + f1(y - 5) + '">' + c[1] + ' ' + fmt(c[0], 0) + ' m</text>';
    });
    return '<svg viewBox="0 0 ' + width + ' ' + height + '" class="chart chart-sounding" role="img"\n' +
      '     aria-label="Model temperature and dew point profile for the day of the flight, with the\n' +
      '     altitude band actually flown">\n  <defs>\n    <clipPath id="clip' + uid + '">\n' +
      '      <rect x="' + left + '" y="' + top + '" width="' + plotW + '" height="' + plotH + '" />\n    </clipPath>\n  </defs>\n' +
      '  <g class="grid">' + grid.join('') + '</g>\n  ' + band + '\n  <g class="references">' + references.join('') + '</g>\n' +
      '  <g clip-path="url(#clip' + uid + ')">\n    <polyline class="adiabat" points="' + adiabat.join(' ') + '" />\n' +
      '    <polyline class="dewpoint" points="' + dewpoint + '" />\n    <polyline class="environment" points="' + environment + '" />\n  </g>\n' +
      '  <g class="axes">' + labels.join('') + '\n' +
      '    <text x="' + f1(left + plotW / 2) + '" y="' + (height - 5) + '" class="axis-title">Temperature, °C</text>\n' +
      '    <text x="12" y="' + f1(top + plotH / 2) + '" class="axis-title"\n' +
      '          transform="rotate(-90 12 ' + f1(top + plotH / 2) + ')">Altitude, m</text>\n  </g>\n</svg>';
  }

  function climbHistogram(a, width, height) {
    width = width || 460; height = height || 260;
    var data = a.climb_histogram;
    if (!data || !data.edges) return '';
    var edges = data.edges, interval = data.seconds_per_count ? data.seconds_per_count[0] : 1.0;
    var seconds = data.counts.map(function (c) { return c * interval; });
    if (!seconds.some(Boolean)) return '';
    var left = 46, right = 16, top = 18, bottom = 40, plotW = width - left - right, plotH = height - top - bottom;
    var peak = Math.max.apply(null, seconds), gap = 2, barW = plotW / seconds.length - gap;
    var bars = [], labels = [];
    seconds.forEach(function (value, index) {
      var x = left + index * (barW + gap), h = plotH * value / peak, centre = (edges[index] + edges[index + 1]) / 2;
      bars.push('<rect x="' + f1(x) + '" y="' + f1(top + plotH - h) + '" width="' + f1(barW) + '" height="' + f1(h) +
                '" rx="2" fill="' + climbColor(centre) + '"><title>' + fmt(edges[index], 1, { plus: true }) + ' to ' +
                fmt(edges[index + 1], 1, { plus: true }) + ' m/s — ' + f1(value / 60) + ' min</title></rect>');
      if (Math.abs(np.mod(centre, 2)) < 0.3) {
        var tick = edges[index] ? fmt(edges[index], 0, { plus: true }) : '0';
        labels.push('<text x="' + f1(x + barW / 2) + '" y="' + (top + plotH + 17) + '" class="axis-label axis-x">' + tick + '</text>');
      }
    });
    var best = 0;
    seconds.forEach(function (v, i) { if (v > seconds[best]) best = i; });
    var bestX = left + best * (barW + gap) + barW / 2, bestH = plotH * seconds[best] / peak;
    var annotation = '<text x="' + f1(bestX) + '" y="' + f1(top + plotH - bestH - 8) + '" class="point-label">' +
      fmt(seconds[best] / 60, 0) + ' min</text>';
    return '<svg viewBox="0 0 ' + width + ' ' + height + '" class="chart chart-hist" role="img"\n' +
      '     aria-label="Minutes spent at each climb rate while thermalling">\n' +
      '  <line class="axis" x1="' + left + '" y1="' + (top + plotH) + '" x2="' + (width - right) + '" y2="' + (top + plotH) + '" />\n' +
      '  ' + bars.join('') + annotation + '\n  <g class="axes">' + labels.join('') + '\n' +
      '    <text x="' + f1(left + plotW / 2) + '" y="' + (height - 6) + '" class="axis-title">Climb rate, m/s\n' +
      '      (20 s average)</text>\n  </g>\n</svg>';
  }

  function ldBar(value, best, width, height) {
    width = width || 54; height = height || 8;
    if (value === null || value === undefined) return '';
    var fraction = Math.max(Math.min(value / Math.max(best, 1e-9), 1.0), 0.02);
    return '<svg class="ldbar" viewBox="0 0 ' + width + ' ' + height + '" width="' + width + '" height="' + height + '" ' +
      'role="img" aria-label="glide ratio ' + f1(value) + ' to 1">' +
      '<rect x="0" y="0" width="' + width + '" height="' + height + '" rx="1" fill="var(--rule)" />' +
      '<rect x="0" y="0" width="' + f1(width * fraction) + '" height="' + height + '" rx="1" fill="' + ldColor(value) + '" /></svg>';
  }

  // ---- charts_client.payload ----------------------------------------------------------
  function searchsorted(a, v) {
    var lo = 0, hi = a.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (a[mid] < v) lo = mid + 1; else hi = mid; }
    return lo;
  }
  function samplePosition(sample, fix) {
    var found = searchsorted(sample, fix);
    if (found >= sample.length) return sample.length - 1;
    if (found && Math.abs(sample[found - 1] - fix) <= Math.abs(sample[found] - fix)) return found - 1;
    return found;
  }
  function clockTicks(a) {
    var s = a.series, f = a.flight, quarter = 900;
    var takeoff = igc.localParts(f.time[0], f.timezone), span = s.t[s.t.length - 1];
    var first = np.mod(-takeoff.minute, 15) * 60 - takeoff.second;
    var tick = first > 0 ? first : first + quarter, out = [];
    while (tick <= span) {
      var index = searchsorted(s.t, tick);
      out.push([np.pyRound(tick, 1), igc.clock(f.time[index], f.timezone).slice(0, 5)]);
      tick += quarter;
    }
    return out;
  }
  function payload(a, meteo, route, sample, planH) {
    var s = a.series, f = a.flight;
    var bands = a.segments.map(function (seg) {
      return [samplePosition(sample, seg.start), samplePosition(sample, seg.stop - 1), seg.phase, seg.start];
    });
    var marks = [], number = 0;
    a.segments.forEach(function (seg) {
      if (seg.phase !== 'thermal' && seg.phase !== 'tow') return;
      var tow = seg.phase === 'tow';
      if (!tow) number += 1;
      marks.push({ at: samplePosition(sample, Math.floor((seg.start + seg.stop) / 2)), label: tow ? 'T' : String(number),
                   tow: tow, segment: seg.start, gain: np.pyRound(seg.altitude_change, 1),
                   rate: np.pyRound(seg.average_climb, 2) });
    });
    var references = [];
    if (meteo) {
      [[Met.boundaryLayerTop(meteo), 'Boundary layer top'], [Met.cloudbase(meteo), 'Cloudbase']].forEach(function (r) {
        if (r[0] !== null && r[0] !== undefined) references.push([np.pyRound(r[0]), r[1]]);
      });
    }
    var legs = route && route.points && route.points.length >= 2 ? route.points.map(function (p) { return p.index; }) : [];
    var ramp = CLIMB_RAMP.map(function (r) { return [r[0] === Infinity ? null : r[0], r[1]]; });
    var altMax = np.max(s.alt);
    return {
      profile: Object.assign({}, PROFILE), plan: Object.assign({}, PLAN, { height: planH }), ramp: ramp,
      x: sample.map(function (i) { return Math.trunc(s.x[i]); }), y: sample.map(function (i) { return Math.trunc(s.y[i]); }),
      bands: bands, marks: marks, references: references,
      route: legs.map(function (i) { return samplePosition(sample, i); }),
      clockTicks: clockTicks(a),
      floor: Math.trunc(Math.floor(np.min(s.alt) / 100) * 100),
      ceiling: Math.trunc(withHeadroom(Math.ceil(altMax / 100) * 100, altMax, meteo))
    };
  }

  TV.charts = { CLIMB_RAMP: CLIMB_RAMP, PROFILE: PROFILE, PLAN: PLAN, escape: escape, climbColor: climbColor,
                WIND_SPEED_STEP: WIND_SPEED_STEP, WIND_ALT_STEP: WIND_ALT_STEP, WIND_MODEL_BAND: WIND_MODEL_BAND,
                ldColor: ldColor, planHeight: planHeight, budgetBar: budgetBar, budgetParts: budgetParts, windProfile: windProfile,
                sounding: sounding, climbHistogram: climbHistogram, ldBar: ldBar, payload: payload, samplePosition: samplePosition };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

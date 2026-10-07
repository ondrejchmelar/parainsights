// The side view and the top view, built here rather than shipped as SVG.
//
// The output is the same DOM `charts.py` writes — same elements in the same order, same
// classes, same data attributes — because everything that reads these charts was written
// against that DOM: the linked cursor, the tooltip, the band highlight, the debrief's
// "show me", the theme's `var()` fills. This file is a second *renderer*, deliberately
// not a second *design*.
(function () {
  var SVGNS = 'http://www.w3.org/2000/svg';

  function make(tag, attributes, text) {
    var node = document.createElementNS(SVGNS, tag);
    if (attributes) {
      Object.keys(attributes).forEach(function (key) {
        if (attributes[key] !== null && attributes[key] !== undefined) {
          node.setAttribute(key, attributes[key]);
        }
      });
    }
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function climbColour(ramp, value) {
    for (var i = 0; i < ramp.length; i++) {
      if (ramp[i][0] === null || value < ramp[i][0]) return ramp[i][1];
    }
    return ramp[ramp.length - 1][1];
  }

  // One polyline per run of one colour, exactly as `_polyline_by_climb` does it: a track
  // of a thousand two-point segments is a thousand DOM nodes, and this is a handful.
  function trackPaths(group, ramp, climb, px, py) {
    if (px.length < 2) return;
    var current = climbColour(ramp, climb[0]);
    var run = [px[0].toFixed(1) + ',' + py[0].toFixed(1)];
    for (var i = 1; i < px.length; i++) {
      var colour = climbColour(ramp, climb[i]);
      run.push(px[i].toFixed(1) + ',' + py[i].toFixed(1));
      if (colour !== current) {
        group.appendChild(make('polyline', { points: run.join(' '), stroke: current }));
        run = [px[i].toFixed(1) + ',' + py[i].toFixed(1)];
        current = colour;
      }
    }
    if (run.length > 1) {
      group.appendChild(make('polyline', { points: run.join(' '), stroke: current }));
    }
  }

  // The hit area carries the projected sample coordinates, which is what the cursor code
  // reads. Python put them in `data-px`/`data-py` and so does this: the alternative is
  // the browser recomputing a projection it would then have to keep in step.
  function cursorLayer(svg, px, py, frame, mode) {
    var cursor = make('g', { 'class': 'cursor' });
    if (mode === 'x') {
      cursor.appendChild(make('line', { 'class': 'crosshair', x1: frame.left,
        x2: frame.left, y1: frame.top, y2: frame.top + frame.plotH }));
    }
    cursor.appendChild(make('circle', { 'class': 'cursor-dot', cx: frame.left,
      cy: frame.top, r: 4.5 }));
    svg.appendChild(cursor);
    svg.appendChild(make('rect', {
      'class': 'hit', x: mode === 'x' ? frame.left : 0, y: mode === 'x' ? frame.top : 0,
      width: mode === 'x' ? frame.plotW : frame.width,
      height: mode === 'x' ? frame.plotH : frame.height,
      'data-mode': mode,
      'data-px': px.map(function (v) { return v.toFixed(1); }).join(','),
      'data-py': py.map(function (v) { return v.toFixed(1); }).join(',')
    }));
  }

  // ---- the side view -------------------------------------------------------------
  // A compared flight's trace on this chart's ground axis, from its 3D scene's track:
  // distance flown or from its launch on the sphere, or time — on this flight's clock when
  // flown the same day (as the 3D replay), from its own launch otherwise. Thinned to
  // about 1 500 points: it is a line to compare against, not one to read fixes off.
  function comparedTrace(o, own, mode) {
    var tr = o.track, n = tr.lon.length, step = Math.max(Math.ceil(n / 1500), 1);
    var R = 6371000, rad = Math.PI / 180, flown = 0, xs = [], ys = [];
    function metres(i, j) {
      var dLat = (tr.lat[j] - tr.lat[i]) * rad, dLon = (tr.lon[j] - tr.lon[i]) * rad;
      var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(tr.lat[i] * rad) *
              Math.cos(tr.lat[j] * rad) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
      return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
    }
    var offset = own && own.start && o.start && Math.abs(o.start - own.start) < 12 * 3600
      ? o.start - own.start : 0;
    var last = 0;
    for (var i = 0; i < n; i += step) {
      if (mode === 'flown') { flown += metres(last, i); last = i; }
      xs.push(mode === 'time' ? (tr.t ? tr.t[i] : i) + offset
              : mode === 'from_start' ? metres(0, i) : flown);
      ys.push(tr.alt[i]);
    }
    return { x: xs, y: ys, colour: o.colour };
  }

  // `aspect`: the host's width over its height, where its shape is not the chart's own —
  // full screen gives the side view a band a quarter of the screen tall, and drawn at its
  // usual proportions it shrank to a strip in the middle. The plot widens; text stays.
  function profile(data, cursor, mode, compared, aspect) {
    var box = data.profile;
    var left = box.left, right = box.right, top = box.top, bottom = box.bottom;
    var H = box.height, W = aspect ? Math.round(H * aspect) : box.width;
    var plotW = W - left - right, plotH = H - top - bottom;
    var along = mode === 'from_start' ? data.d : (mode === 'time' ? cursor.t : data.s);
    var alt = cursor.alt;
    var spanMax = Math.max(along[along.length - 1], 1), spanMin = 0;
    for (var i = 0; i < along.length; i++) spanMax = Math.max(spanMax, along[i]);
    var floor = data.floor, ceiling = data.ceiling;
    // Comparing: every compared flight on the same axes, which grow to hold them all.
    var traces = compared && compared.others ? compared.others.map(function (o) {
      return comparedTrace(o, compared.own, mode);
    }) : [];
    traces.forEach(function (t) {
      for (var k = 0; k < t.x.length; k++) {
        spanMax = Math.max(spanMax, t.x[k]); spanMin = Math.min(spanMin, t.x[k]);
        floor = Math.min(floor, Math.floor(t.y[k] / 250) * 250);
        ceiling = Math.max(ceiling, Math.ceil(t.y[k] / 250) * 250);
      }
    });

    function sx(value) { return left + plotW * (value - spanMin) / Math.max(spanMax - spanMin, 1); }
    function sy(value) {
      return top + plotH * (1 - (value - floor) / Math.max(ceiling - floor, 1));
    }
    var px = along.map(sx), py = alt.map(sy);
    var baseline = top + plotH;

    var svg = make('svg', {
      viewBox: '0 0 ' + W + ' ' + H, 'class': 'chart chart-profile', role: 'img',
      'aria-label': 'Altitude against ' + data.modes[mode][1]
        + ', coloured by climb rate, with climbs numbered'
    });

    var bands = make('g', { 'class': 'bands' });
    data.bands.forEach(function (band) {
      var x0 = sx(along[band[0]]), x1 = sx(along[band[1]]);
      bands.appendChild(make('rect', {
        'class': 'band band-' + band[2], 'data-segment': band[3],
        x: x0.toFixed(1), y: top, width: Math.max(x1 - x0, 1).toFixed(1), height: plotH
      }));
    });
    svg.appendChild(bands);

    var grid = make('g', { 'class': 'grid' });
    var labels = [];
    for (var level = Math.ceil(floor / 500) * 500; level <= ceiling; level += 500) {
      var y = sy(level);
      grid.appendChild(make('line', { x1: left, y1: y.toFixed(1), x2: W - right,
        y2: y.toFixed(1) }));
      labels.push(make('text', { x: left - 10, y: (y + 3.5).toFixed(1),
        'class': 'axis-label axis-y' }, String(level)));
    }
    svg.appendChild(grid);

    // The hairlines down to the axis. About 110 of them however long the flight is —
    // they are a texture that says "this is a profile", not a reading.
    var drops = make('g', { 'class': 'drops' });
    var step = Math.max(Math.round(along.length / 110), 1);
    for (var d = 0; d < along.length; d += step) {
      drops.appendChild(make('line', { x1: px[d].toFixed(1), y1: py[d].toFixed(1),
        x2: px[d].toFixed(1), y2: baseline }));
    }
    svg.appendChild(drops);

    var references = make('g', { 'class': 'references' });
    data.references.forEach(function (reference, index) {
      var value = reference[0];
      if (value <= floor || value >= ceiling) return;
      var ry = sy(value);
      references.appendChild(make('line', { 'class': 'reference', x1: left,
        y1: ry.toFixed(1), x2: W - right, y2: ry.toFixed(1) }));
      // Alternating ends: cloudbase and the boundary layer top are often within 100 m
      // of each other, and two labels at the same end overlap.
      var label = make('text', {
        x: index % 2 ? left + 6 : W - right - 4,
        y: (ry - 6).toFixed(1),
        'class': index % 2 ? 'reference-label band-label' : 'reference-label'
      }, reference[1] + ' ' + Math.round(value) + ' m');
      references.appendChild(label);
    });
    svg.appendChild(references);

    traces.forEach(function (t) {
      var d = '';
      for (var k = 0; k < t.x.length; k++) d += (k ? 'L' : 'M') + sx(t.x[k]).toFixed(1) + ' ' + sy(t.y[k]).toFixed(1);
      svg.appendChild(make('path', { 'class': 'compared-trace', d: d, fill: 'none', stroke: t.colour,
        'stroke-width': 1.6, 'stroke-linejoin': 'round', opacity: 0.9 }));
    });
    var track = make('g', { 'class': 'track' });
    if (traces.length && compared.own) {
      // This flight in its comparison colour, as on the map: one colour a flight.
      var own = '';
      for (var k2 = 0; k2 < px.length; k2++) own += (k2 ? 'L' : 'M') + px[k2].toFixed(1) + ' ' + py[k2].toFixed(1);
      track.appendChild(make('path', { d: own, fill: 'none', stroke: compared.own.colour,
        'stroke-width': 2.2, 'stroke-linejoin': 'round' }));
    } else {
      trackPaths(track, data.ramp, cursor.climb, px, py);
    }
    svg.appendChild(track);

    var ends = make('g', { 'class': 'endpoints' });
    ends.appendChild(make('circle', { cx: px[0].toFixed(1), cy: py[0].toFixed(1),
      r: 4.5, 'class': 'endpoint' }));
    var last = px.length - 1;
    ends.appendChild(make('circle', { cx: px[last].toFixed(1), cy: py[last].toFixed(1),
      r: 4.5, 'class': 'endpoint' }));
    ends.appendChild(make('text', { x: Math.min(px[last], W - right - 26).toFixed(1),
      y: (py[last] + 20).toFixed(1), 'class': 'endpoint-label' }, 'landing'));
    svg.appendChild(ends);

    var marks = make('g', { 'class': 'marks' });
    data.marks.forEach(function (mark) {
      var mx = sx(along[mark.at]), my = sy(alt[mark.at]);
      var group = make('g', { 'class': 'mark', 'data-segment': mark.segment });
      group.appendChild(make('circle', { cx: mx.toFixed(1), cy: my.toFixed(1), r: 9,
        fill: 'var(--panel)', stroke: mark.tow ? 'var(--tow)' : 'var(--climb)' }));
      group.appendChild(make('text', { x: mx.toFixed(1), y: (my + 3.4).toFixed(1),
        'class': 'mark-label' }, mark.label));
      marks.appendChild(group);
    });
    svg.appendChild(marks);

    cursorLayer(svg, px, py, { left: left, top: top, plotW: plotW, plotH: plotH,
                               width: W, height: H }, 'x');

    var axes = make('g', { 'class': 'axes' });
    axes.appendChild(make('line', { x1: left, y1: baseline, x2: W - right, y2: baseline }));
    if (mode === 'time') {
      // The clock is Python's: it knows the flight's own timezone, and this page does
      // not and must not guess.
      data.clockTicks.forEach(function (tick) {
        var x = sx(tick[0]);
        if (x > left + plotW + 0.5) return;
        axes.appendChild(make('line', { 'class': 'tick', x1: x.toFixed(1), y1: baseline,
          x2: x.toFixed(1), y2: baseline + 4 }));
        axes.appendChild(make('text', { x: x.toFixed(1), y: baseline + 17,
          'class': 'axis-label axis-x' }, tick[1]));
      });
    } else {
      var stepKm = Math.max(Math.round(spanMax / 1000 / 10), 1);
      if (stepKm > 7) stepKm = Math.round(stepKm / 5) * 5;
      for (var km = 0; km * 1000 <= spanMax; km += stepKm) {
        var tx = sx(km * 1000);
        axes.appendChild(make('line', { 'class': 'tick', x1: tx.toFixed(1), y1: baseline,
          x2: tx.toFixed(1), y2: baseline + 4 }));
        axes.appendChild(make('text', { x: tx.toFixed(1), y: baseline + 17,
          'class': 'axis-label axis-x' }, String(km)));
      }
    }
    labels.forEach(function (label) { axes.appendChild(label); });
    axes.appendChild(make('text', { x: (left + plotW / 2).toFixed(1), y: H - 8,
      'class': 'axis-title' }, data.modes[mode][0]));
    var side = make('text', { x: 14, y: (top + plotH / 2).toFixed(1),
      'class': 'axis-title',
      transform: 'rotate(-90 14 ' + (top + plotH / 2).toFixed(1) + ')' }, 'altitude m');
    axes.appendChild(side);
    svg.appendChild(axes);
    return svg;
  }

  // ---- the top view --------------------------------------------------------------
  function plan(data, cursor) {
    var box = data.plan;
    var W = box.width, H = box.height, pad = box.pad;
    var xs = data.x, ys = data.y;
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    var spanX = Math.max(maxX - minX, 1), spanY = Math.max(maxY - minY, 1);
    var scale = Math.min((W - 2 * pad) / spanX, (H - 2 * pad - 20) / spanY);
    var offX = ((W - 2 * pad) - spanX * scale) / 2;
    var offY = ((H - 2 * pad - 20) - spanY * scale) / 2;

    function px(value) { return pad + offX + (value - minX) * scale; }
    function py(value) { return H - pad - 16 - offY - (value - minY) * scale; }
    var sx = xs.map(px), sy = ys.map(py);

    var svg = make('svg', {
      viewBox: '0 0 ' + W + ' ' + H, 'class': 'chart chart-plan', role: 'img',
      'aria-label': 'Plan view of the course line, coloured by climb rate, with climbs '
        + 'marked and the scored free-distance route'
    });

    if (data.route && data.route.length >= 2) {
      var route = make('g', { 'class': 'xc-route' });
      for (var leg = 1; leg < data.route.length; leg++) {
        route.appendChild(make('line', {
          x1: sx[data.route[leg - 1]].toFixed(1), y1: sy[data.route[leg - 1]].toFixed(1),
          x2: sx[data.route[leg]].toFixed(1), y2: sy[data.route[leg]].toFixed(1) }));
      }
      data.route.forEach(function (at) {
        route.appendChild(make('rect', { x: (sx[at] - 3).toFixed(1),
          y: (sy[at] - 3).toFixed(1), width: 6, height: 6 }));
      });
      svg.appendChild(route);
    }

    var track = make('g', { 'class': 'track' });
    trackPaths(track, data.ramp, cursor.climb, sx, sy);
    svg.appendChild(track);

    var marks = make('g', { 'class': 'marks' });
    data.marks.forEach(function (mark) {
      var mx = sx[mark.at], my = sy[mark.at];
      var group = make('g', { 'class': 'mark', 'data-segment': mark.segment });
      if (mark.tow) {
        group.appendChild(make('circle', { cx: mx.toFixed(1), cy: my.toFixed(1), r: 6,
          fill: 'var(--panel)', stroke: 'var(--tow)' }));
      } else {
        // Two encodings of the same climb, one visible at a time: height gained finds
        // the big climbs and average rate finds the good ones, which are not the same
        // climbs — a long weak one can out-gain a short strong one.
        var colour = climbColour(data.ramp, mark.rate);
        var byGain = 3.5 + 6.0 * Math.min(mark.gain / 1200, 1);
        var byRate = 3.5 + 6.0 * Math.min(Math.max(mark.rate, 0) / 3, 1);
        group.appendChild(make('circle', { 'class': 'plan-thermal plan-by-gain',
          cx: mx.toFixed(1), cy: my.toFixed(1), r: byGain.toFixed(1), fill: colour }));
        group.appendChild(make('circle', { 'class': 'plan-thermal plan-by-rate',
          cx: mx.toFixed(1), cy: my.toFixed(1), r: byRate.toFixed(1), fill: colour }));
        group.appendChild(make('title', {}, 'climb ' + mark.label + ': '
          + (mark.gain > 0 ? '+' : '') + Math.round(mark.gain) + ' m at '
          + (mark.rate > 0 ? '+' : '') + mark.rate.toFixed(2) + ' m/s'));
      }
      marks.appendChild(group);
    });
    svg.appendChild(marks);

    svg.appendChild(make('circle', { cx: sx[0].toFixed(1), cy: sy[0].toFixed(1), r: 4,
      'class': 'endpoint' }));
    var last = sx.length - 1;
    svg.appendChild(make('circle', { cx: sx[last].toFixed(1), cy: sy[last].toFixed(1),
      r: 4, 'class': 'endpoint' }));

    var northX = W - pad + 4, northY = pad + 4;
    var compass = make('g', { 'class': 'compass' });
    compass.appendChild(make('line', { x1: northX, y1: northY + 22, x2: northX,
      y2: northY }));
    compass.appendChild(make('path', { d: 'M' + (northX - 3.5) + ',' + (northY + 5)
      + ' L' + northX + ',' + northY + ' L' + (northX + 3.5) + ',' + (northY + 5) }));
    compass.appendChild(make('text', { x: northX, y: northY + 34,
      'class': 'axis-label axis-x' }, 'N'));
    svg.appendChild(compass);

    var barKm = Math.max(Math.round(spanX / 1000 / 3), 1);
    var barPx = barKm * 1000 * scale;
    var barY = H - 10;
    var bar = make('g', { 'class': 'scalebar' });
    bar.appendChild(make('line', { x1: pad, y1: barY, x2: (pad + barPx).toFixed(1),
      y2: barY }));
    bar.appendChild(make('text', { x: (pad + barPx + 7).toFixed(1), y: barY + 3.5,
      'class': 'axis-label' }, barKm + ' km'));
    svg.appendChild(bar);

    cursorLayer(svg, sx, sy, { left: 0, top: 0, plotW: W, plotH: H, width: W, height: H },
                'xy');
    return svg;
  }

  // ---- drawing them into the page --------------------------------------------------
  //
  // Every flight article carries one payload and one host per chart. The side view is
  // redrawn on a mode change rather than three copies being hidden and shown, which is
  // the other two thirds of what the old document was spending its bytes on.
  function draw(article) {
    var holder = article.querySelector('.chart-data');
    var cursorNode = article.querySelector('.cursor-data');
    if (!holder || !cursorNode) return;
    var data, cursor;
    try {
      data = JSON.parse(holder.textContent);
      cursor = JSON.parse(cursorNode.textContent);
    } catch (error) {
      return;
    }
    article.__chartData = data;
    article.__cursorData = cursor;

    var side = article.querySelector('.chart-host[data-chart="profile"]');
    if (side) {
      var mode = side.dataset.mode || 'flown';
      side.textContent = '';
      side.appendChild(profile(data, cursor, mode, comparedFor(article), shapeOf(side)));
      watch(article, side);
    }
    var top = article.querySelector('.chart-host[data-chart="plan"]');
    if (top) {
      top.textContent = '';
      top.appendChild(plan(data, cursor));
    }
    sparks(article, data.ramp);
  }

  // ---- the climbs table's sparklines -----------------------------------------------
  //
  // One per climb: the climb rate from entry (left) to exit, in TREND_BARS bars, each the
  // mean over its slice, above the line climbing and below it sinking, on the climb ramp.
  // Drawn here from the row's own series (`data-climb`, every fix, written by
  // `js/report.js`) rather than shipped as SVG: 104 of them were 176 KB of the published
  // page. The page's cursor sample is too coarse to draw them from — one point every
  // 14-45 s on the showcase flights, against 22 bars across a climb of a few minutes.
  var TREND_CEILING = 4.0, TREND_BARS = 22, SPARK_W = 76, SPARK_H = 18;
  function spark(values, ramp) {
    var svg = make('svg', { 'class': 'spark', viewBox: '0 0 ' + SPARK_W + ' ' + SPARK_H,
      width: SPARK_W, height: SPARK_H, role: 'img',
      'aria-label': 'climb rate through the climb, entry on the left' });
    function sy(v) {
      var clipped = Math.max(Math.min(v, TREND_CEILING), -TREND_CEILING);
      return SPARK_H / 2 - clipped / TREND_CEILING * (SPARK_H / 2 - 1);
    }
    var buckets = Math.min(TREND_BARS, values.length);
    var gap = 0.8, barW = (SPARK_W - gap * (buckets - 1)) / buckets;
    for (var p = 0; p < buckets; p++) {
      var from = Math.trunc(p * values.length / buckets);
      var to = Math.max(Math.trunc((p + 1) * values.length / buckets), from + 1), sum = 0;
      for (var k = from; k < to; k++) sum += values[k];
      var value = sum / (to - from), y = sy(value), top = Math.min(y, SPARK_H / 2);
      svg.appendChild(make('rect', { x: (p * (barW + gap)).toFixed(2), y: top.toFixed(2),
        width: barW.toFixed(2), height: Math.max(Math.abs(SPARK_H / 2 - y), 0.7).toFixed(2),
        fill: climbColour(ramp, value) }));
    }
    svg.appendChild(make('line', { 'class': 'spark-zero', x1: 0, y1: SPARK_H / 2,
      x2: SPARK_W, y2: SPARK_H / 2 }));
    return svg;
  }
  function sparks(article, ramp) {
    article.querySelectorAll('td.spark-cell[data-climb]').forEach(function (cell) {
      var values = cell.dataset.climb.split(',').map(Number).filter(function (v) { return isFinite(v); });
      cell.textContent = '';
      if (values.length >= 3) cell.appendChild(spark(values, ramp));
    });
  }

  // The axis toggle stays where it was — in the report's own handler, with the button
  // states it already manages — and calls this. Two handlers on one button is how a
  // control ends up half-toggled: the classes say one thing and the chart another.
  //
  // It used to unhide one of three SVGs the document already carried. Redrawing one is a
  // few milliseconds and 380 KB.
  function redraw(article, mode) {
    var host = article.querySelector('.chart-host[data-chart="profile"]');
    if (!host || !article.__chartData) return;
    host.dataset.mode = mode;
    host.textContent = '';
    host.appendChild(profile(article.__chartData, article.__cursorData, mode, comparedFor(article),
                             shapeOf(host)));
    // The cursor binds to the SVG that was there when it ran, so the new one has to be
    // handed back to it. Without this the toggle produces a chart the cursor cannot
    // drive, which looks exactly like the cursor being broken.
    if (article.__relinkCharts) article.__relinkCharts();
  }

  // The host's own proportions where CSS has given it a box of its own (full screen: a
  // fixed height, `aspect-ratio: auto`); null where the chart's proportions are the box's.
  function shapeOf(host) {
    if (getComputedStyle(host).aspectRatio !== 'auto' || !host.clientHeight) return null;
    return host.clientWidth / host.clientHeight;
  }
  // Redrawn when the host changes shape — entering and leaving full screen.
  function watch(article, host) {
    if (host.__watched || !window.ResizeObserver) return;
    host.__watched = true;
    var last = null, timer = null;
    new ResizeObserver(function () {
      var shape = shapeOf(host), key = shape ? shape.toFixed(2) : 'own';
      if (key === last) return;
      last = key;
      clearTimeout(timer);
      timer = setTimeout(function () { redraw(article, host.dataset.mode || 'flown'); }, 60);
    }).observe(host);
  }

  // The flights compared with this one (`window.__compareFor`, `render_html`), or null.
  function comparedFor(article) {
    return window.__compareFor ? window.__compareFor(article.getAttribute('data-flight-report')) : null;
  }

  // Exposed so a flight added after this ran can be drawn the same way, and so a test
  // can force a redraw.
  window.__drawCharts = draw;
  window.__drawProfile = redraw;

  document.querySelectorAll('[data-flight-report]').forEach(draw);
})();

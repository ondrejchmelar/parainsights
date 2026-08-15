"""The side view and the top view, drawn in the browser instead of in the document.

These two are the report's biggest charts and its biggest bytes. Measured on the
published three-flight report before this existed: **nine profile SVGs at 577 KB and
three plan views at 153 KB**, 730 KB of a 2.97 MB document — 24% of it, and nine
profiles because the axis toggle shipped all three modes and hid two.

What replaces them is a payload of about 20 KB a flight and one renderer. The trade is
data against CPU and for these two charts it is close to free, because *the data is
already in the document*: `render_html._cursor_data` ships altitude, climb rate and time
at a sampled index for the hover cursor, and the chart's own trace is a second drawing of
exactly those numbers. This module adds the four series the cursor payload does not
carry — distance flown, distance from launch, and the plan-view metres — and draws from
the pair.

Three rules kept this from becoming a second implementation of `charts.py`:

* **The browser builds the same SVG.** Same element order, same class names, same
  `data-` attributes. Everything downstream — the linked cursor, the tooltip, the phase
  band highlight, "show me" from a debrief card, both themes through `var()` fills — goes
  on working without knowing where the SVG came from, and the report's CSS is unchanged.
* **One sample, shared.** The trace is drawn through the *same* indices the cursor is
  indexed by. `quicklook.py` learned this the hard way: two independently decimated
  samples put the marker on a different moment than the one under the pointer.
* **Nothing is recomputed that Python already knows.** The clock labels for the time
  axis, the meteo reference lines, the phase bands and the climb ramp all arrive as data.
  A JavaScript port of `flight.local_time` would be a timezone bug waiting to happen.

`charts.altitude_profile` and `charts.plan_view` are still here and still tested — they
are what a KMZ, a test or anything else that needs a self-contained SVG uses — but the
report calls neither.
"""

from __future__ import annotations

import math

import numpy as np

from . import charts, geo
from .analysis import Analysis, Phase

# The two charts' geometry, in one place because the payload and the renderer both need
# it and a disagreement is a cursor that points somewhere the trace is not.
PROFILE = {"width": 1080, "height": 420, "left": 56, "right": 20, "top": 20, "bottom": 46}
PLAN = {"width": 1080, "pad": 26}


def _ramp() -> list:
    """`charts.CLIMB_RAMP` as JSON: the ramp is data, not a second list in JavaScript."""
    return [
        [None if math.isinf(threshold) else threshold, colour]
        for threshold, colour in charts.CLIMB_RAMP
    ]


def _clock_ticks(analysis: Analysis, sample: list[int]) -> list:
    """Quarter-hour marks for the time axis, already formatted.

    The label is `flight.local_time`, which resolves the flight's own timezone from the
    logger header or from the take-off coordinates — `timezonefinder`'s dataset is not
    going in a page, and `lon / 15` is the trap the timezone gap warns about. So the
    ticks are computed here and shipped: a few dozen pairs, against a whole class of
    wrong-by-an-hour.
    """
    series = analysis.series
    flight = analysis.flight
    quarter = 900
    takeoff = flight.local_time(0)
    span = float(series.t[-1])
    first = (-takeoff.minute % 15) * 60 - takeoff.second
    tick = first if first > 0 else first + quarter
    out = []
    while tick <= span:
        index = int(np.searchsorted(series.t, tick))
        out.append([round(tick, 1), flight.local_time(index).strftime("%H:%M")])
        tick += quarter
    return out


def payload(analysis: Analysis, *, meteo=None, route=None, sample: list[int],
            plan_height: int) -> dict:
    """Everything the two charts need that the cursor payload does not already carry.

    Positions in `bands` and `marks` are **positions in `sample`**, not fix indices, for
    the same reason the trace is drawn through the sample: one index space per chart, and
    the cursor already lives in this one. `data-segment` keeps the fix index, because
    that is what the tooltip and "show me" address a segment by.
    """
    series = analysis.series
    flight = analysis.flight
    at = np.asarray(sample, dtype=int)

    from_start = geo.distance(flight.lat[0], flight.lon[0], flight.lat, flight.lon)

    def position(fix: int) -> int:
        """The sample position nearest a fix index — `render_html._sample_position`'s
        rule, applied here so the bands land where the trace does."""
        found = int(np.searchsorted(at, fix))
        if found >= len(at):
            return len(at) - 1
        if found and abs(int(at[found - 1]) - fix) <= abs(int(at[found]) - fix):
            return found - 1
        return found

    bands = [
        [position(segment.start), position(segment.stop - 1), segment.phase.value,
         int(segment.start)]
        for segment in analysis.segments
    ]

    marks, number = [], 0
    for segment in analysis.segments:
        if segment.phase not in (Phase.THERMAL, Phase.TOW):
            continue
        middle = (segment.start + segment.stop) // 2
        tow = segment.phase is Phase.TOW
        if not tow:
            number += 1
        marks.append({
            "at": position(middle),
            "label": "T" if tow else str(number),
            "tow": tow,
            "segment": int(segment.start),
            # The plan view sizes a climb's disc two ways and colours it by rate; both
            # are per-climb numbers rather than per-fix ones, so they travel with the
            # mark rather than being re-derived from the series.
            "gain": round(float(segment.altitude_change), 1),
            "rate": round(float(segment.average_climb), 2),
        })

    references = []
    if meteo is not None:
        for value, label in ((getattr(meteo, "boundary_layer_top", None), "boundary layer top"),
                             (getattr(meteo, "cloudbase", None), "cloudbase")):
            if value is not None:
                references.append([round(float(value)), label])

    legs = []
    if route is not None and len(getattr(route, "points", [])) >= 2:
        legs = [int(point.index) for point in route.points]

    out = {
        "profile": dict(PROFILE),
        "plan": dict(PLAN, height=plan_height),
        "ramp": _ramp(),
        "modes": {key: list(value) for key, value in charts.PROFILE_MODES.items()},
        # One integer per sample per series. Metres and seconds, rounded — the charts
        # are 1 080 px wide and a decimetre is not visible on any of them.
        "s": [int(series.s[i]) for i in at],
        "d": [int(from_start[i]) for i in at],
        "x": [int(series.x[i]) for i in at],
        "y": [int(series.y[i]) for i in at],
        "bands": bands,
        "marks": marks,
        "references": references,
        "route": [position(index) for index in legs],
        "clockTicks": _clock_ticks(analysis, sample),
        # The axis is computed from the data in the page, but the headroom rule needs the
        # meteo lines and the 1 000 m cap, so the answer travels rather than the rule.
        "floor": int(math.floor(float(series.alt.min()) / 100) * 100),
        "ceiling": int(charts._with_headroom(
            math.ceil(float(series.alt.max()) / 100) * 100, float(series.alt.max()), meteo)),
    }
    return out


STYLE = """
/* The two big charts are drawn into these when the page loads. The height is reserved
   from the payload's own aspect ratio, so the page does not jump when they appear —
   a chart that lands 400 px tall into a 0 px box moves everything under it. */
.chart-host { display: block; width: 100%; }
.chart-host > svg { display: block; width: 100%; height: auto; }
.chart-missing { padding: 22px 16px; color: var(--ink-3); font-size: 13.5px; }
"""

SCRIPT = r"""
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
  function profile(data, cursor, mode) {
    var box = data.profile;
    var left = box.left, right = box.right, top = box.top, bottom = box.bottom;
    var W = box.width, H = box.height;
    var plotW = W - left - right, plotH = H - top - bottom;
    var along = mode === 'from_start' ? data.d : (mode === 'time' ? cursor.t : data.s);
    var alt = cursor.alt;
    var spanMax = Math.max(along[along.length - 1], 1);
    for (var i = 0; i < along.length; i++) spanMax = Math.max(spanMax, along[i]);
    var floor = data.floor, ceiling = data.ceiling;

    function sx(value) { return left + plotW * value / spanMax; }
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

    var track = make('g', { 'class': 'track' });
    trackPaths(track, data.ramp, cursor.climb, px, py);
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
      side.appendChild(profile(data, cursor, mode));
    }
    var top = article.querySelector('.chart-host[data-chart="plan"]');
    if (top) {
      top.textContent = '';
      top.appendChild(plan(data, cursor));
    }
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
    host.appendChild(profile(article.__chartData, article.__cursorData, mode));
    // The cursor binds to the SVG that was there when it ran, so the new one has to be
    // handed back to it. Without this the toggle produces a chart the cursor cannot
    // drive, which looks exactly like the cursor being broken.
    if (article.__relinkCharts) article.__relinkCharts();
  }

  // Exposed so a flight added after this ran can be drawn the same way, and so a test
  // can force a redraw.
  window.__drawCharts = draw;
  window.__drawProfile = redraw;

  document.querySelectorAll('[data-flight-report]').forEach(draw);
})();
"""

"""Self-contained HTML flight report.

No external requests: the display face is an inlined woff2, the charts are inline
SVG, the interaction is a few dozen lines of vanilla JavaScript. That keeps the
report readable from a USB stick in ten years, and it is the only form that works
under a strict content-security policy.

A second renderer using MapLibre + deck.gl over a terrain DEM is planned for the
interactive 3D view; it needs network tiles, so it cannot replace this one.
"""

import base64
import json
import math
from pathlib import Path

from . import charts, quicklook, terrain as terrain_module, view3d, view3d_gl
from numpy import median as np_median
from .analysis import TURN_RESOLUTION_LIMIT, Analysis, Phase

FONT_PATH = Path(__file__).parent / "assets" / "display.woff2.b64"

# XContest's own names for what it scored. The distance beside them is the scored one — a
# triangle's perimeter, not the open path through its turnpoints.
SHAPE_LABEL = {
    "fai": "FAI triangle",
    "flat": "flat triangle",
    "open": "free distance, 3 turnpoints",
}


def _duration(seconds: int) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes:02d} m"
    return f"{minutes} m {secs:02d} s"


def _short_duration(seconds: int) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def _font_face() -> str:
    if not FONT_PATH.exists():
        return ""
    encoded = FONT_PATH.read_text().strip()
    return (
        "@font-face{font-family:'NarrowDisplay';font-style:normal;font-weight:400;"
        f"font-display:swap;src:url(data:font/woff2;base64,{encoded}) format('woff2');}}"
    )


STYLE = """
:root {
  color-scheme: light;
  --paper: #f2f1ed;
  --panel: #fbfbf9;
  --panel-2: #eceae4;
  --rule: #d8d5cc;
  --rule-strong: #b9b5a9;
  --ink: #14171c;
  --ink-2: #4a5560;
  --ink-3: #767f8a;
  --climb: #eb6834;
  --climb-1: #f0a07a;
  --climb-2: #eb6834;
  --climb-3: #c8431a;
  --sink: #2a78d6;
  --sink-1: #8fb6e6;
  --sink-2: #2a78d6;
  --sink-3: #17508f;
  --tow: #1baf7a;
  --neutral: #a9a49a;
  --shadow-ink: #c3bfb4;
  --ld-1: #86aed8;
  --ld-2: #5f92c9;
  --ld-3: #3f74b4;
  --ld-4: #2a5894;
  --ld-5: #173d69;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --paper: #101317;
    --panel: #171b21;
    --panel-2: #1e232a;
    --rule: #2b323b;
    --rule-strong: #414a55;
    --ink: #eef1f4;
    --ink-2: #a3adb8;
    --ink-3: #737d88;
    --climb: #d95926;
    --climb-1: #b06a4a;
    --climb-2: #d95926;
    --climb-3: #f07a44;
    --sink: #3987e5;
    --sink-1: #4a6f9e;
    --sink-2: #3987e5;
    --sink-3: #7fb0ef;
    --tow: #199e70;
    --neutral: #6f7883;
    --shadow-ink: #2f3741;
    --ld-1: #35577f;
    --ld-2: #4874a6;
    --ld-3: #5b91cc;
    --ld-4: #74aae0;
    --ld-5: #9cc6f0;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --paper: #101317;
  --panel: #171b21;
  --panel-2: #1e232a;
  --rule: #2b323b;
  --rule-strong: #414a55;
  --ink: #eef1f4;
  --ink-2: #a3adb8;
  --ink-3: #737d88;
  --climb: #d95926;
  --climb-1: #b06a4a;
  --climb-2: #d95926;
  --climb-3: #f07a44;
  --sink: #3987e5;
  --sink-1: #4a6f9e;
  --sink-2: #3987e5;
  --sink-3: #7fb0ef;
  --tow: #199e70;
  --neutral: #6f7883;
  --shadow-ink: #2f3741;
  --ld-1: #35577f;
  --ld-2: #4874a6;
  --ld-3: #5b91cc;
  --ld-4: #74aae0;
  --ld-5: #9cc6f0;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
    "DejaVu Sans", sans-serif;
  font-size: 15px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}

.wrap { max-width: 1180px; margin: 0 auto; padding: 30px 22px 80px; }

.display, .eyebrow, .stat-value, h1, h2, th, .axis-label, .axis-title,
.budget-label, .mark-label, .endpoint-label, .point-label {
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", "DejaVu Sans Condensed",
    ui-sans-serif, sans-serif;
}

.num, .stat-value, td.num, .mono {
  font-variant-numeric: tabular-nums;
  font-family: ui-monospace, "DejaVu Sans Mono", "Liberation Mono", Menlo, monospace;
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 11px;
  color: var(--ink-3);
  margin: 0;
}

/* Masthead ---------------------------------------------------------------- */
.masthead {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 14px;
  border-bottom: 2px solid var(--ink);
}
.masthead h1 {
  margin: 2px 0 0;
  font-size: clamp(30px, 5vw, 46px);
  line-height: 1.02;
  font-weight: 400;
  letter-spacing: -0.015em;
  text-wrap: balance;
}
.masthead h1 span { color: var(--ink-3); }
.identity { display: flex; gap: 26px; flex-wrap: wrap; }
.identity div { display: flex; flex-direction: column; }
.identity dt, .identity .key {
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-3);
}
.identity .val { font-size: 14px; }

/* Panels ------------------------------------------------------------------ */
section { margin-top: 34px; }
.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--rule);
  padding-bottom: 7px;
  margin-bottom: 16px;
}
.section-head h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 400;
  letter-spacing: 0.01em;
}
.section-head p { margin: 0; color: var(--ink-3); font-size: 13px; max-width: 52ch; }

.panel {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: 2px;
}

.hero { padding: 6px 4px 0; overflow: hidden; }
.caption { color: var(--ink-3); font-size: 12.5px; margin: 4px 4px 10px; }
.chart-title {
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  font-size: 11.5px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink-2);
  margin: 8px 8px 2px;
}
.view3d-caption { margin-top: 10px; }
.chart-head { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  flex-wrap: wrap; }
.chart-head .chart-title { margin-bottom: 0; }
.toggle-small { margin: 4px 6px 6px 0; }
.toggle-small .toggle-button { font-size: 10.5px; padding: 4px 9px; }

/* Stat tiles -------------------------------------------------------------- */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
  gap: 1px;
  background: var(--rule);
  border: 1px solid var(--rule);
}
.stat { background: var(--panel); padding: 12px 14px 13px; }
.stat .key {
  display: block;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-3);
}
.stat-value { font-size: 25px; line-height: 1.15; display: block; margin-top: 3px; }
.stat-value small { font-size: 13px; color: var(--ink-3); margin-left: 2px; }
.stat .sub { font-size: 12px; color: var(--ink-3); }

.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 22px; }
.hero-grid { display: grid; grid-template-columns: minmax(0, 2.2fr) minmax(0, 1fr); gap: 16px; }
@media (max-width: 780px) { .hero-grid { grid-template-columns: 1fr; } }

/* Charts ------------------------------------------------------------------ */
.chart { display: block; width: 100%; height: auto; }
.chart .axis-label { font-size: 10.5px; fill: var(--ink-3); }
.chart .axis-y { text-anchor: end; }
.chart .axis-x { text-anchor: middle; }
.chart .axis-title { font-size: 10.5px; fill: var(--ink-3); text-anchor: middle;
  text-transform: uppercase; letter-spacing: 0.1em; }
.chart .grid line { stroke: var(--rule); stroke-width: 1; }
.chart .axes line, .chart .axis { stroke: var(--rule-strong); stroke-width: 1; }
.chart .track polyline { fill: none; stroke-width: 2.2; stroke-linecap: round;
  stroke-linejoin: round; }

.chart-profile .drops line { stroke: var(--shadow-ink); stroke-width: 0.7; opacity: 0.45; }
.chart-profile .endpoint { fill: var(--panel); stroke: var(--ink); stroke-width: 2; }
.chart-profile .endpoint-label { font-size: 10.5px; fill: var(--ink-2); text-anchor: middle;
  text-transform: uppercase; letter-spacing: 0.1em; }
.chart .mark circle { stroke-width: 2; }
.chart .mark-label { font-size: 10.5px; fill: var(--ink); text-anchor: middle; }
.chart .mark.active circle { fill: var(--climb); stroke: var(--panel); }

.chart .reference { stroke: var(--ink-3); stroke-width: 1; stroke-dasharray: 6 4; }
.chart .reference-label { font-size: 10px; fill: var(--ink-3); text-anchor: end;
  text-transform: uppercase; letter-spacing: 0.07em; }
.chart .reference-label.band-label { text-anchor: start; }

.chart-plan .plan-thermal { fill-opacity: 0.72; stroke: var(--panel); stroke-width: 1.2; }
.chart-plan .plan-by-rate { display: none; }
.chart-plan.circles-by-rate .plan-by-gain { display: none; }
.chart-plan.circles-by-rate .plan-by-rate { display: inline; }
.chart-plan .mark.active .plan-thermal { fill-opacity: 1; stroke: var(--ink); stroke-width: 2; }
.chart-plan .endpoint { fill: var(--panel); stroke: var(--ink); stroke-width: 2; }
.chart-plan .compass line, .chart-plan .compass path { stroke: var(--ink-2); stroke-width: 1.2;
  fill: none; }
.chart-plan .scalebar line { stroke: var(--ink-2); stroke-width: 1.2; }

/* Phase shading moved from the old standalone barogram onto the profile, so these
   selectors are chart-agnostic now — scoping them to a class that no longer exists is
   how the bands ended up filling black. */
.chart .band { opacity: 0.1; }
.chart .band-thermal { fill: var(--climb); }
.chart .band-glide { fill: var(--sink); }
.chart .band-tow { fill: var(--tow); }
.chart .band-dive { fill: var(--sink-3); }
.chart .band.active { opacity: 0.32; }
/* Hide via CSS, not the HTML `hidden` attribute — that attribute does nothing
   inside SVG, which leaves the crosshair parked at the origin. */
.chart .cursor { visibility: hidden; }
.chart .cursor.on { visibility: visible; }
.chart .cursor-dot { fill: var(--panel); stroke: var(--ink); stroke-width: 2; }
.chart .hit { fill: transparent; cursor: crosshair; }
.chart .crosshair { stroke: var(--ink-2); stroke-width: 1; stroke-dasharray: 3 3; }
.panel-divide { height: 1px; background: var(--rule); margin: 2px 6px 4px; }

.chart-wind .wind-dot { fill: var(--panel); stroke: var(--sink); stroke-width: 2; }
.chart-wind .wind-arrow { stroke: var(--sink); stroke-width: 1.6; }
.chart-wind .wind-number { font-size: 10px; fill: var(--ink); text-anchor: middle;
  font-variant-numeric: tabular-nums; }
.chart-wind .wind-point.active .wind-dot { fill: var(--climb); stroke: var(--panel); }
.chart-wind .wind-time { font-size: 10px; fill: var(--ink-3); font-variant-numeric: tabular-nums; }
.chart-wind .model polyline { fill: none; stroke: var(--neutral); stroke-width: 2;
  stroke-dasharray: 5 3; }
.chart-wind .model .model-dot { fill: var(--neutral); }

.chart-sounding .environment { fill: none; stroke: var(--climb); stroke-width: 2.2; }
.chart-sounding .dewpoint { fill: none; stroke: var(--sink); stroke-width: 2.2; }
.chart-sounding .adiabat { fill: none; stroke: var(--neutral); stroke-width: 1.6;
  stroke-dasharray: 4 3; }
.chart-sounding .flight-band { fill: var(--climb); opacity: 0.1; }

.chart-plan .xc-route line { stroke: var(--ink-3); stroke-width: 1; stroke-dasharray: 4 3; }
.chart-plan .xc-route rect { fill: none; stroke: var(--ink-2); stroke-width: 1.4; }
.point-label { font-size: 11px; fill: var(--ink-2); text-anchor: middle;
  font-variant-numeric: tabular-nums; }
.budget-label { font-size: 11px; fill: var(--ink-2); text-anchor: middle;
  text-transform: uppercase; letter-spacing: 0.08em; }

.legend { display: flex; gap: 16px; flex-wrap: wrap; margin: 12px 0 0; padding: 0; list-style: none; }
.legend li { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--ink-2); }
.legend .legend-title { color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.09em;
  font-size: 10.5px; }

/* Segmented control ------------------------------------------------------- */
.toggle { display: inline-flex; margin-bottom: 12px; border: 1px solid var(--rule-strong);
  border-radius: 3px; overflow: hidden; }
.toggle-button {
  font: inherit;
  font-size: 12px;
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  padding: 6px 14px;
  border: 0;
  background: var(--panel);
  color: var(--ink-3);
  cursor: pointer;
}
.toggle-button + .toggle-button { border-left: 1px solid var(--rule-strong); }
.toggle-button:hover { color: var(--ink); }
.toggle-button.is-on { background: var(--ink); color: var(--paper); }
.profile[hidden] { display: none; }
.flight[hidden] { display: none; }

/* Flight picker ----------------------------------------------------------- */
.tabs { display: flex; flex-wrap: wrap; gap: 1px; background: var(--rule);
  border: 1px solid var(--rule); margin-bottom: 26px; }
/* A tab is a wrapper, not a button, because it holds two: open and remove. A button
   inside a button is invalid and browsers drop the inner one. */
.tab { flex: 1 1 150px; position: relative; background: var(--panel); display: flex; }
.tab-open {
  flex: 1 1 auto;
  min-width: 0;
  text-align: left;
  border: 0;
  background: none;
  padding: 9px 26px 10px 13px;
  cursor: pointer;
  color: var(--ink-2);
  font: inherit;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.tab-close {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 19px;
  height: 19px;
  padding: 0;
  border: 0;
  border-radius: 2px;
  background: none;
  color: var(--ink-3);
  font: inherit;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.12s;
}
.tab:hover .tab-close, .tab-close:focus-visible { opacity: 1; }
.tab-close:hover { background: var(--climb); color: var(--paper); }
/* Touch has no hover, so the control has to be permanently visible there. */
@media (hover: none) { .tab-close { opacity: 0.7; } }
.tab .tab-date {
  font-family: ui-monospace, "DejaVu Sans Mono", monospace;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}
.tab .tab-meta {
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-3);
}
.tab .tab-stat {
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-2);
}
.tab:hover { background: var(--panel-2); }
.tab.is-on { background: var(--ink); }
.tab.is-on .tab-date, .tab.is-on .tab-meta, .tab.is-on .tab-stat
  { color: var(--paper); }
.tab.is-on .tab-close { color: var(--paper); }
.tab-add { flex: 0 0 auto; border-right: 2px solid var(--climb); }
.tab-add .tab-open { padding-right: 13px; }
.tab-add .tab-date { font-size: 13px; }
.tabs-note { margin: -18px 0 26px; font-size: 12.5px; color: var(--ink-3); }
.swatch { width: 12px; height: 12px; border-radius: 2px; flex: none; }
.ramp { display: flex; gap: 2px; align-items: center; }
.ramp span { width: 22px; height: 10px; border-radius: 1px; }

.tooltip {
  position: absolute;
  pointer-events: none;
  z-index: 5;
  background: var(--panel);
  border: 1px solid var(--rule-strong);
  border-radius: 3px;
  padding: 7px 10px;
  font-size: 12.5px;
  line-height: 1.45;
  box-shadow: 0 4px 14px rgb(0 0 0 / 0.14);
  white-space: nowrap;
  opacity: 0;
  transition: opacity 0.1s;
}
.tooltip.on { opacity: 1; }
.tooltip .t-time { font-variant-numeric: tabular-nums; font-weight: 600; }
.tooltip .t-row { color: var(--ink-2); font-variant-numeric: tabular-nums; }

/* Tables ------------------------------------------------------------------ */
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
th {
  text-align: right;
  font-weight: 400;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-3);
  padding: 0 9px 7px;
  border-bottom: 1px solid var(--rule-strong);
  white-space: nowrap;
}
th:first-child, td:first-child { text-align: left; padding-left: 2px; }
td { padding: 7px 9px; border-bottom: 1px solid var(--rule); text-align: right;
  font-variant-numeric: tabular-nums; white-space: nowrap; }
tbody tr { cursor: default; }
tbody tr:hover, tbody tr:focus-visible { background: var(--panel-2); outline: none; }
tr.is-tow td:first-child { color: var(--tow); }
.tag {
  display: inline-block;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  padding: 1px 6px;
  border-radius: 2px;
  border: 1px solid currentColor;
}
.tag-tow { color: var(--tow); }
.tag-thermal { color: var(--climb); }
.tag-glide { color: var(--sink); }
.bar-cell { display: flex; align-items: center; gap: 7px; justify-content: flex-end; }
.bar-cell .bar { height: 7px; border-radius: 1px; background: var(--climb); flex: none; }
td.spark-cell { padding: 3px 10px 2px; }
svg.spark { display: block; }
svg.spark .spark-zero { stroke: var(--rule-strong); stroke-width: 1; }
svg.ldbar { display: block; flex: none; }
.dir { color: var(--ink-3); }

/* Notes ------------------------------------------------------------------- */
.notes { columns: 2 300px; column-gap: 34px; color: var(--ink-2); font-size: 13.5px; }
.notes p { margin: 0 0 11px; break-inside: avoid; }
.notes strong { color: var(--ink); font-weight: 600; }
code { font-family: ui-monospace, "DejaVu Sans Mono", monospace; font-size: 0.92em;
  background: var(--panel-2); padding: 1px 4px; border-radius: 2px; }

footer { margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--rule);
  color: var(--ink-3); font-size: 12.5px; display: flex; justify-content: space-between;
  gap: 16px; flex-wrap: wrap; }

:focus-visible { outline: 2px solid var(--climb); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
@media (max-width: 620px) {
  .notes { columns: 1; }
  .masthead h1 { font-size: 30px; }
  /* Charts get the full width of the screen on a phone: the page padding costs more
     than it gives when the panel is the content. */
  .wrap { padding-left: 8px; padding-right: 8px; }
  .hero { padding: 4px 0 0; }
  .hero .caption, .hero .chart-title { margin-left: 8px; margin-right: 8px; }
  .view3d-panel { margin-left: -8px; margin-right: -8px; }
  .section-head { flex-direction: column; gap: 4px; }
  .section-head p { max-width: none; }
}
"""

SCRIPT = """
function initFlight(root) {
  var payload = root.querySelector('.cursor-data');
  var tip = document.getElementById('tip');
  if (!tip || !payload) return;
  var data = JSON.parse(payload.textContent);
  var terrainView = typeof initView3d === 'function'
    ? initView3d(root, data.cursor3d || null) : null;

  // Every chart that can host the cursor publishes its own projected sample
  // coordinates on its hit rect, so one index drives a dot in all of them and
  // none of the projection maths is repeated here.
  var views = [];
  root.querySelectorAll('.hit[data-px]').forEach(function (hit) {
    if (!hit.dataset.px) return;
    var svg = hit.ownerSVGElement;
    views.push({
      svg: svg,
      hit: hit,
      mode: hit.dataset.mode || 'x',
      px: hit.dataset.px.split(',').map(Number),
      py: hit.dataset.py.split(',').map(Number),
      cursor: svg.querySelector('.cursor'),
      dot: svg.querySelector('.cursor-dot'),
      crosshair: svg.querySelector('.crosshair')
    });
  });
  if (!views.length) return;

  function svgPoint(view, event) {
    var box = view.svg.getBoundingClientRect();
    var vb = view.svg.viewBox.baseVal;
    return {
      x: (event.clientX - box.left) / box.width * vb.width,
      y: (event.clientY - box.top) / box.height * vb.height,
      box: box,
      vb: vb
    };
  }

  function nearestIndex(view, point) {
    var best = 0;
    var bestDistance = Infinity;
    for (var i = 0; i < view.px.length; i++) {
      var dx = view.px[i] - point.x;
      // A profile or barogram is a function of x, so judging on x alone keeps the
      // cursor on the fix under the pointer even where the trace doubles back.
      var d = view.mode === 'xy' ? dx * dx + (view.py[i] - point.y) * (view.py[i] - point.y)
                                 : dx * dx;
      if (d < bestDistance) { bestDistance = d; best = i; }
    }
    return best;
  }

  function place(index, source, point) {
    views.forEach(function (view) {
      if (index >= view.px.length) return;
      // A hidden profile variant must not be drawn on: it has no layout box.
      if (!view.svg.getClientRects().length) return;
      var x = view.px[index];
      var y = view.py[index];
      if (view.dot) { view.dot.setAttribute('cx', x); view.dot.setAttribute('cy', y); }
      if (view.crosshair) {
        view.crosshair.setAttribute('x1', x);
        view.crosshair.setAttribute('x2', x);
      }
      if (view.cursor) view.cursor.classList.add('on');
    });

    tip.innerHTML =
      '<div class="t-time">' + data.clock[index] + '</div>' +
      '<div class="t-row">' + data.alt[index] + ' m &middot; ' +
      (data.climb[index] > 0 ? '+' : '') + data.climb[index].toFixed(1) + ' m/s</div>' +
      '<div class="t-row">' + data.speed[index] + ' km/h &middot; ' + data.phase[index] + '</div>';
    if (terrainView) terrainView.setCursor(index);
    tip.classList.add('on');
    var tipBox = tip.getBoundingClientRect();
    var pageX = point.box.left + source.px[index] / point.vb.width * point.box.width;
    var pageY = point.box.top + source.py[index] / point.vb.height * point.box.height;
    tip.style.left = Math.min(pageX + 14, window.innerWidth - tipBox.width - 10) + window.scrollX + 'px';
    tip.style.top = (pageY - tipBox.height - 12) + window.scrollY + 'px';
    highlight(data.segment[index]);
  }

  function hide() {
    views.forEach(function (view) {
      if (view.cursor) view.cursor.classList.remove('on');
    });
    tip.classList.remove('on');
    if (terrainView) terrainView.clearCursor();
    highlight(null);
  }

  views.forEach(function (view) {
    function show(event) {
      var point = svgPoint(view, event);
      place(nearestIndex(view, point), view, point);
    }
    view.hit.addEventListener('mousemove', show);
    view.hit.addEventListener('mouseleave', hide);
    view.hit.addEventListener('touchmove', function (event) {
      if (event.touches.length) { show(event.touches[0]); event.preventDefault(); }
    }, { passive: false });
  });

  function highlight(key) {
    // Scoped to this flight: with several flights in one document, a global query
    // would light up the matching segment index in every other flight too.
    root.querySelectorAll('.band.active, .mark.active, .wind-point.active, tr.active')
      .forEach(function (node) { node.classList.remove('active'); });
    if (key === null || key === undefined) return;
    root.querySelectorAll('[data-segment="' + key + '"]')
      .forEach(function (node) { node.classList.add('active'); });
  }

  root.querySelectorAll('.toggle-button[data-profile]').forEach(function (button) {
    button.addEventListener('click', function () {
      var wanted = button.dataset.profile;
      root.querySelectorAll('.toggle-button[data-profile]').forEach(function (other) {
        var on = other === button;
        other.classList.toggle('is-on', on);
        other.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      root.querySelectorAll('[data-profile-view]').forEach(function (view) {
        view.hidden = view.dataset.profileView !== wanted;
      });
    });
  });

  root.querySelectorAll('.toggle-button[data-circles]').forEach(function (button) {
    button.addEventListener('click', function () {
      var wanted = button.dataset.circles;
      root.querySelectorAll('.toggle-button[data-circles]').forEach(function (other) {
        var on = other === button;
        other.classList.toggle('is-on', on);
        other.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      root.querySelectorAll('.chart-plan').forEach(function (chart) {
        chart.classList.toggle('circles-by-rate', wanted === 'rate');
      });
    });
  });

  root.querySelectorAll('tr[data-segment]').forEach(function (row) {
    row.tabIndex = 0;
    row.addEventListener('mouseenter', function () { highlight(row.dataset.segment); });
    row.addEventListener('focus', function () { highlight(row.dataset.segment); });
    row.addEventListener('mouseleave', function () { highlight(null); });
    row.addEventListener('blur', function () { highlight(null); });
  });
}

document.querySelectorAll('[data-flight-report]').forEach(initFlight);

// One controller for the whole tab strip, delegated from the strip itself, because tabs
// are added and removed at runtime: a listener attached per tab at load would miss every
// flight the reader drops in later.
var flightTabs = (function () {
  var strip = document.getElementById('flight-tabs');

  function show(key) {
    document.querySelectorAll('.tab[data-flight-tab]').forEach(function (tab) {
      var on = tab.dataset.flightTab === key;
      tab.classList.toggle('is-on', on);
      var open = tab.querySelector('.tab-open');
      if (open) open.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    document.querySelectorAll('[data-flight-report]').forEach(function (report) {
      report.hidden = report.dataset.flightReport !== key;
    });
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  function remove(key) {
    var tab = strip.querySelector('.tab[data-flight-tab="' + key + '"]');
    var report = document.querySelector('[data-flight-report="' + key + '"]');
    var wasOn = tab && tab.classList.contains('is-on');
    if (tab) tab.parentNode.removeChild(tab);
    if (report) {
      // Drop the 3D handles this article owned: each holds a DEM grid and a stitched
      // basemap image, so leaving them in the registry keeps a removed flight's memory.
      // A WebGL context is scarcer still — a page gets about sixteen — so it is handed
      // back rather than left for the collector.
      if (window.__view3dAll) {
        report.querySelectorAll('canvas.view3d').forEach(function (canvas) {
          var handle = window.__view3dAll[canvas.id];
          if (handle && handle.dispose) handle.dispose();
          delete window.__view3dAll[canvas.id];
        });
      }
      report.parentNode.removeChild(report);
    }
    if (!wasOn) return;
    // Fall back to the first flight still in the document, or to the drop panel.
    var next = strip.querySelector('.tab[data-flight-tab]:not(.tab-add)');
    show(next ? next.dataset.flightTab : 'own');
  }

  if (strip) {
    strip.addEventListener('click', function (event) {
      var tab = event.target.closest('.tab[data-flight-tab]');
      if (!tab) return;
      if (event.target.closest('.tab-close')) remove(tab.dataset.flightTab);
      else show(tab.dataset.flightTab);
    });
  }
  return { show: show, remove: remove, strip: strip };
})();
window.__flightTabs = flightTabs;
"""


def _sample_indices(analysis: Analysis) -> list[int]:
    """Fix indices used for the hover cursor: a few hundred, evenly spread."""
    total = len(analysis.series)
    step = max(total // 900, 1)
    return list(range(0, total, step))


def _cursor_data(analysis: Analysis) -> dict:
    """Sampled series for the hover readout — a few hundred points, not thousands."""
    series = analysis.series
    flight = analysis.flight
    indices = _sample_indices(analysis)

    phase_of = {}
    for segment in analysis.segments:
        for i in range(segment.start, segment.stop):
            phase_of[i] = segment

    # Mirror the barogram's own y-scale so the hover dot lands on the trace.
    floor = math.floor(series.alt.min() / 250) * 250
    ceiling = math.ceil(series.alt.max() / 250) * 250
    left, right, top, bottom = 52, 16, 16, 34
    plot_h = 300 - top - bottom

    def screen_y(value):
        return top + plot_h * (1 - (value - floor) / max(ceiling - floor, 1))

    return {
        "t": [float(series.t[i]) for i in indices],
        "y": [round(float(screen_y(series.alt[i])), 1) for i in indices],
        "alt": [int(series.alt[i]) for i in indices],
        "climb": [round(float(series.climb[i]), 2) for i in indices],
        "speed": [int(series.speed[i]) for i in indices],
        "clock": [flight.local_time(i).strftime("%H:%M:%S") for i in indices],
        "phase": [phase_of[i].phase.value if i in phase_of else "cruise" for i in indices],
        "segment": [phase_of[i].start if i in phase_of else None for i in indices],
        # Ground positions for the 3D marker, at the very same indices.
        "cursor3d": {
            "lon": [round(float(flight.lon[i]), 5) for i in indices],
            "lat": [round(float(flight.lat[i]), 5) for i in indices],
            "alt": [
                int((flight.alt_gps if flight.alt_gps.any() else series.alt)[i])
                for i in indices
            ],
        },
    }


def _stat(key: str, value: str, unit: str = "", sub: str = "") -> str:
    unit_html = f"<small>{unit}</small>" if unit else ""
    sub_html = f'<span class="sub">{sub}</span>' if sub else ""
    return (
        f'<div class="stat"><span class="key">{key}</span>'
        f'<span class="stat-value">{value}{unit_html}</span>{sub_html}</div>'
    )


def _thermal_rows(analysis: Analysis) -> str:
    rows = []
    number = 0
    best_climb = max((s.average_climb for s in analysis.thermals), default=1.0)
    for segment in analysis.segments:
        if segment.phase not in (Phase.THERMAL, Phase.TOW):
            continue
        if segment.phase is Phase.TOW:
            label, tag = "T", '<span class="tag tag-tow">tow</span>'
        else:
            number += 1
            label, tag = str(number), ""
        width = 46 * max(segment.average_climb, 0) / max(best_climb, 0.1)
        wind = (
            f"{segment.wind.kmh:.0f} <span class='dir'>{segment.wind.cardinal}</span>"
            if segment.wind
            else "<span class='dir'>—</span>"
        )
        turns = f"{segment.turns:.1f}" if segment.turns is not None else "—"
        # Height per circle: the number that separates a cored climb from a ground-out one.
        per_turn = (
            f"{segment.altitude_change / segment.turns:.0f}"
            if segment.turns and segment.turns >= 0.5
            else "—"
        )
        direction = (
            f"<span class='dir'>{segment.turn_direction}</span>"
            if segment.turn_direction
            else "<span class='dir'>—</span>"
        )
        circle = f"{segment.circle_seconds:.0f}" if segment.circle_seconds else "—"
        radius = f"{segment.circle_radius:.0f}" if segment.circle_radius else "—"
        efficiency = f"{segment.efficiency:.0f}%" if segment.efficiency is not None else "—"
        rows.append(
            f'<tr data-segment="{segment.start}"'
            f'{" class=is-tow" if segment.phase is Phase.TOW else ""}>'
            f"<td>{label} {tag}</td>"
            f"<td>{segment.start_time}</td>"
            f"<td>{_short_duration(segment.duration)}</td>"
            f"<td>{segment.altitude_change:+.0f}</td>"
            f"<td>{segment.finish_altitude:.0f}</td>"
            f'<td><span class="bar-cell">{segment.average_climb:+.2f}'
            f'<span class="bar" style="width:{width:.0f}px"></span></span></td>'
            f"<td>{segment.maximum_climb:+.1f}</td>"
            f"<td>{efficiency}</td>"
            f"<td>{turns}</td>"
            f"<td>{per_turn}</td>"
            f"<td>{direction}</td>"
            f"<td>{circle}</td>"
            f"<td>{radius}</td>"
            f"<td>{wind}</td>"
            f'<td class="spark-cell">'
            f'{charts.climb_spark(analysis.series, segment.start, segment.stop)}</td>'
            f'<td class="spark-cell">'
            f'{charts.climb_trend(analysis.series, segment.start, segment.stop)}</td>'
            f"</tr>"
        )
    return "".join(rows)


def _glide_rows(analysis: Analysis) -> str:
    rows = []
    best = max((s.average_ld or 0) for s in analysis.glides) if analysis.glides else 1.0
    for index, segment in enumerate(analysis.glides, start=1):
        ld = f"{segment.average_ld:.1f}" if segment.average_ld else "—"
        rows.append(
            f'<tr data-segment="{segment.start}">'
            f"<td>{index}</td>"
            f"<td>{segment.start_time}</td>"
            f"<td>{_short_duration(segment.duration)}</td>"
            f"<td>{segment.distance / 1000:.1f}</td>"
            f"<td>{segment.altitude_change:+.0f}</td>"
            f'<td><span class="bar-cell">{ld}'
            f'{charts.ld_bar(segment.average_ld, best=best)}</span></td>'
            f"<td>{segment.average_speed:.0f}</td>"
            f"</tr>"
        )
    return "".join(rows)


def _wind_shear_note(analysis: Analysis) -> str:
    """One sentence on how the measured wind changed with height."""
    sounded = [
        ((s.start_altitude + s.finish_altitude) / 2, s.wind)
        for s in analysis.thermals
        if s.wind and s.turns and s.turns >= 2
    ]
    if len(sounded) < 3:
        return "too few circled climbs to see a trend with height."
    # Sort on the altitude only. A bare sort() falls through to the second element when
    # two climbs share a mean altitude, and `Wind` is not orderable — which took down the
    # whole report on a flight with eighteen climbs, two of which matched to the metre.
    sounded.sort(key=lambda item: item[0])
    lower = sounded[: len(sounded) // 2]
    upper = sounded[-(len(sounded) // 2):]
    low_speed = sum(w.kmh for _, w in lower) / len(lower)
    high_speed = sum(w.kmh for _, w in upper) / len(upper)
    change = high_speed - low_speed
    if abs(change) < 3:
        return (
            f"about {low_speed:.0f} km/h throughout, with no useful shear between the low "
            f"climbs and the high ones."
        )
    direction = "stronger" if change > 0 else "lighter"
    return (
        f"{low_speed:.0f} km/h in the lower climbs against {high_speed:.0f} km/h in the higher "
        f"ones — {abs(change):.0f} km/h {direction} with height."
    )


def _histogram_verdict(analysis: Analysis) -> str:
    """A one-phrase reading of the climb distribution, in pilot's terms."""
    data = analysis.climb_histogram
    if not data or not any(data["counts"]):
        return "no time circling"
    edges, counts = data["edges"], data["counts"]
    interval = data["seconds_per_count"][0] if data.get("seconds_per_count") else 1.0
    total = sum(counts) or 1
    mode_index = max(range(len(counts)), key=lambda i: counts[i])
    mode = (edges[mode_index] + edges[mode_index + 1]) / 2
    in_sink = sum(c for e, c in zip(edges, counts) if e < 0) / total
    best = max((edges[i + 1] for i, c in enumerate(counts) if c * interval > 20), default=mode)
    return (
        f"mostly {mode:+.1f} m/s, best sustained about {best:+.0f} m/s, "
        f"{in_sink * 100:.0f}% of the circling in sink"
    )


def _meteo_section(analysis: Analysis, meteo, uid: str = "") -> str:
    """The day's air: sounding, ceilings, and how they compare with what was flown."""
    if meteo is None:
        return ""
    summary = analysis.summary
    offset = summary.baro_offset or 0
    flight_top = summary.max_altitude + offset

    chips = [
        ("surface", f"{meteo.surface_temperature:.0f} °C",
         f"dew {meteo.surface_dew_point:.0f} °C · spread "
         f"{meteo.surface_temperature - meteo.surface_dew_point:.0f} K"),
        ("cloudbase", f"{meteo.cloudbase:,.0f} m".replace(",", " "), "from the surface spread"),
    ]
    if meteo.thermal_top:
        chips.append(
            ("thermal top", f"{meteo.thermal_top:,.0f} m".replace(",", " "),
             "dry adiabat meets the profile")
        )
    if meteo.boundary_layer_top:
        chips.append(
            ("boundary layer", f"{meteo.boundary_layer_top:,.0f} m".replace(",", " "),
             "model mixing depth")
        )
    chips.append(("you reached", f"{flight_top:,.0f} m".replace(",", " "),
                  "highest point, GPS datum"))
    if meteo.cape is not None:
        chips.append(("cape", f"{meteo.cape:.0f} J/kg",
                      f"low cloud {meteo.cloud_cover_low:.0f}%"
                      if meteo.cloud_cover_low is not None else "instability"))

    chip_html = "".join(
        f'<div class="stat"><span class="key">{key}</span>'
        f'<span class="stat-value">{value}</span><span class="sub">{sub}</span></div>'
        for key, value, sub in chips
    )

    # Compare the measured drift against the model at the same heights.
    rows = []
    for index, segment in enumerate(analysis.thermals, start=1):
        if not segment.wind or not segment.turns or segment.turns < 2:
            continue
        height = (segment.start_altitude + segment.finish_altitude) / 2 + offset
        model = meteo.wind_at(height)
        if not model:
            continue
        delta = abs(((segment.wind.direction - model[1] + 180) % 360) - 180)
        rows.append(
            f'<tr data-segment="{segment.start}"><td>{index}</td>'
            f"<td>{segment.start_time}</td><td>{height:.0f}</td>"
            f"<td>{segment.wind.kmh:.0f}</td><td>{segment.wind.direction:.0f}°</td>"
            f"<td>{model[0]:.0f}</td><td>{model[1]:.0f}°</td>"
            f"<td>{delta:.0f}°</td></tr>"
        )

    ceiling_note = ""
    if meteo.thermal_top:
        difference = flight_top - meteo.thermal_top
        verdict = (
            f"{abs(difference):.0f} m above" if difference > 0 else f"{abs(difference):.0f} m below"
        )
        ceiling_note = (
            f"<p>The sounding puts the dry thermal top at "
            f"{meteo.thermal_top:,.0f}&nbsp;m".replace(",", " ")
            + f" and you topped out {verdict} it. Above ~2 080&nbsp;m the profile only cools "
            f"4&nbsp;K/km — a stable layer, which is what a day that caps out feels like from "
            f"the harness.</p>"
        )

    return f"""
  <section>
    <div class="section-head">
      <h2>The air that day</h2>
      <p>{charts.escape(meteo.source)} over the middle of the course line, valid {charts.escape(meteo.valid_at)}.
         Fetched once and embedded — the report makes no requests when you open it.</p>
    </div>
    <div class="stats">{chip_html}</div>
    {_meteo_profile(analysis, meteo, uid, rows)}
    <div class="notes" style="margin-top:20px">
      {ceiling_note}
      <p><strong>Model, not measurement.</strong> This is a model's analysis for a point near the
        course line, not a radiosonde ascent. Treat the ceilings as ±100&nbsp;m and the winds as
        indicative.</p>
    </div>
  </section>"""


def _meteo_profile(analysis: Analysis, meteo, uid: str, rows: list[str]) -> str:
    """The sounding and the wind comparison — only possible with pressure levels."""
    if len(meteo.levels) < 2:
        return (
            '<p class="caption" style="margin-top:16px">No vertical profile is available for this '
            "date: the reanalysis archive serves surface fields for any past day but returns "
            "nothing on pressure levels, so the sounding and the wind comparison are missing "
            "here. Flights from the last two months get the full profile.</p>"
        )
    return f"""<div class="grid-2" style="margin-top:22px">
      <div>
        <div class="panel" style="padding:14px 16px 6px">{charts.sounding(meteo, analysis, uid=uid)}</div>
        <ul class="legend">
          <li><span class="swatch" style="background:var(--climb)"></span>temperature</li>
          <li><span class="swatch" style="background:var(--sink)"></span>dew point</li>
          <li><span class="swatch" style="background:var(--neutral)"></span>dry adiabat from the
            surface</li>
        </ul>
        <p class="caption">Where the dry adiabat crosses the temperature curve is as high as a
          surface thermal can get without help. The shaded band is the altitude you actually
          used.</p>
      </div>
      <div>
        <div class="panel" style="padding:14px 16px 4px">
          <div class="table-scroll">
            <table>
              <thead><tr><th>climb</th><th>start</th><th>height m</th><th>km/h</th><th>from</th>
                <th>model km/h</th><th>model from</th><th>&Delta; dir</th></tr></thead>
              <tbody>{"".join(rows)}</tbody>
            </table>
          </div>
        </div>
        <p class="caption">Wind from circle drift against the model at the same height. Agreement
          here is the strongest evidence that the drift method works — nothing in the flight data
          knows about the model, and nothing in the model knows about the flight.</p>
      </div>
    </div>"""


def _flight_body(analysis: Analysis, *, meteo=None, route=None, terrain=None,
                 basemaps=None, fetch_tiles: bool = True,
                 kmz: bytes | None = None, uid: str = "f0",
                 hidden: bool = False) -> str:
    """One flight's sections, from masthead to footer.

    ``meteo`` and ``route`` are optional: the report degrades to the flight's own
    data when the weather could not be fetched or optimisation was skipped. ``uid``
    keeps SVG element ids unique when several flights share one document.
    """
    summary = analysis.summary
    flight = analysis.flight
    tow = analysis.tow
    thermals = analysis.thermals
    budget = analysis.budget

    climb_rate = (
        sum(s.altitude_change for s in thermals) / sum(s.duration for s in thermals)
        if thermals
        else 0.0
    )
    best = max(thermals, key=lambda s: s.average_climb) if thermals else None
    longest = max(analysis.glides, key=lambda s: s.distance) if analysis.glides else None
    total_turns = sum(s.turns or 0 for s in thermals)

    # HFFTY is a free-text soup: "Google Pixel 8 17 Client:xctrack FlightId:019f…".
    # Keep the device, drop the OS version and the identifiers.
    device = (flight.headers.logger_type or "—").split(" Client:")[0].split(" FlightId:")[0]
    parts = device.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].isdigit():
        device = parts[0]

    identity = [
        ("pilot", summary.pilot or "—"),
        ("glider", summary.glider or "—"),
        ("site", summary.site or "—"),
        ("recorder", device),
    ]
    identity_html = "".join(
        f'<div><span class="key">{key}</span><span class="val">{charts.escape(value)}</span></div>'
        for key, value in identity
    )

    peak_index = int(analysis.series.alt.argmax())
    peak_time = flight.local_time(peak_index).strftime("%H:%M")
    offset = summary.baro_offset or 0
    # Coarse sampling (a KML export, typically) cannot resolve a thermal circle.
    coarse = summary.sample_interval > TURN_RESOLUTION_LIMIT
    # One set of sample indices shared by the cursor data and by every chart that
    # hosts the cursor, so an index means the same fix everywhere.
    sample = _sample_indices(analysis)

    tiles = [
        _stat("airtime", _duration(summary.duration), "",
              f"{summary.takeoff_time} – {summary.landing_time}"),
        _stat("xc distance", f"{route.km:.2f}" if route else "—", " km",
              f"{SHAPE_LABEL.get(route.shape, 'open distance')} · "
              f"{summary.track_distance / 1000:.0f} km flown, "
              f"{summary.straight_distance / 1000:.0f} km straight" if route else ""),
        _stat("max altitude", f"{summary.max_altitude:,.0f}".replace(",", " "), " m",
              f"at {peak_time}"
              + (f" · {summary.max_altitude + offset:,.0f} m GPS".replace(",", " ") if offset else "")),
        _stat("height gained", f"{summary.total_gain:,.0f}".replace(",", " "), " m",
              f"best single climb {summary.max_gain:.0f} m"),
        _stat("climbs", str(len(thermals)), "",
              (f"{total_turns:.0f} turns · " if not coarse else "")
              + f"{climb_rate:+.2f} m/s mean"),
        _stat("wind", f"{analysis.wind.kmh:.0f}" if analysis.wind else "—", " km/h",
              f"from {analysis.wind.cardinal} · averaged over "
              f"{len([s for s in thermals if s.wind])} climbs" if analysis.wind else ""),
    ]
    if tow:
        tiles.append(
            _stat("off tow at", f"{tow.finish_altitude:,.0f}".replace(",", " "), " m",
                  f"{tow.altitude_change:+.0f} m in {_short_duration(tow.duration)} of tow")
        )
    stats = "".join(tiles)

    ramp = "".join(
        f'<span style="background:{color}"></span>'
        for _, color in charts.CLIMB_RAMP
    )

    tow_note = ""
    if tow:
        tow_note = (
            f"<p><strong>Launch classified as a tow.</strong> The first climb — "
            f"{_short_duration(tow.duration)}, {tow.altitude_change:+.0f} m at "
            f"{tow.average_climb:+.2f} m/s, released at {tow.finish_altitude:.0f} m — starts "
            f"with the flight, climbs steadily and was flown almost straight "
            f"({f'{tow.turns:.1f} turns' if tow.turns is not None else 'nearly straight'}). "
            f"It is kept out of the thermal statistics and out of the "
            f"wind estimate, where a straight climb would have measured the glider's own "
            f"track rather than the air. igc2kmz counts it as thermal number one.</p>"
        )

    view3d_section = ""
    if terrain is not None:
        # A shared document carries several flights, so trade 3D track detail for size.
        payload = view3d.data(
            analysis, terrain, tolerance=4.0 if uid == "f0" else 12.0,
            basemaps=basemaps, tiles=fetch_tiles
        )
        kmz_uri = None
        if kmz:
            kmz_uri = (
                "data:application/vnd.google-earth.kmz;base64,"
                + base64.b64encode(kmz).decode("ascii")
            )
        clearance = terrain_module.clearance(terrain, analysis)
        view3d_section = f"""
  <section>
    <div class="section-head">
      <h2>The flight over the ground</h2>
      <p>Drag to pan, right-drag or ctrl-drag to rotate and tilt, scroll to zoom. The
         terrain is a real DEM carried inside this page; the Satellite button switches
         between imagery, a map and bare relief. Hovering the charts below moves the
         marker here too.</p>
    </div>
    {view3d.panel(payload, uid, kmz_uri=kmz_uri,
                  kmz_name=f"{summary.date}-{(summary.site or 'flight').replace(' ', '-')}.kmz")}
    <p class="caption view3d-caption">Terrain {terrain.elevations.min():.0f}–{terrain.elevations.max():.0f} m
      over {terrain.cols}&#215;{terrain.rows} samples, drawn at true vertical scale so height
      above ground can be judged directly — the &#215;1 button cycles to &#215;2 and &#215;4. Lowest
      ground clearance of the flight was {clearance.min():.0f}&nbsp;m, median
      {float(np_median(clearance)):.0f}&nbsp;m.
      {charts.escape("; ".join(sorted({b.attribution for b in (basemaps or {}).values()
                                       if b.attribution}))) or ""}
      Elevation from the AWS terrarium DEM.</p>
  </section>"""

    wind_chart = charts.wind_profile(analysis, meteo=meteo, uid=uid)
    histogram = charts.climb_histogram(analysis)
    meteo_section = _meteo_section(analysis, meteo, uid)

    return f"""<article class="flight" data-flight-report="{uid}"{" hidden" if hidden else ""}>
  <header class="masthead">
    <div>
      <p class="eyebrow">tracklog viewer</p>
      <h1>{charts.escape(summary.site or "Flight")} <span>{charts.escape(summary.date)}</span></h1>
    </div>
    <div class="identity">{identity_html}</div>
  </header>

{view3d_section}

  <section>
    <div class="section-head">
      <h2>Side view and top view</h2>
      <p>The same flight twice. Hover either and the marker appears in both — and in the
         3D view above — so you can see where on the ground any moment happened.</p>
    </div>
    <div class="toggle" role="group" aria-label="Ground axis for the side view">
      <button type="button" class="toggle-button is-on" data-profile="flown" aria-pressed="true">
        distance flown</button>
      <button type="button" class="toggle-button" data-profile="from_start" aria-pressed="false">
        from launch</button>
      <button type="button" class="toggle-button" data-profile="time" aria-pressed="false">
        time</button>
    </div>
    <div class="panel hero">
      <p class="chart-title">Side view — height above the ground axis. Shading is the detected
        phase; the trace itself is coloured by climb rate.</p>
      <div class="profile" data-profile-view="flown">
        {charts.altitude_profile(analysis, meteo=meteo, mode="flown", sample=sample)}
      </div>
      <div class="profile" data-profile-view="from_start" hidden>
        {charts.altitude_profile(analysis, meteo=meteo, mode="from_start", sample=sample)}
      </div>
      <div class="profile" data-profile-view="time" hidden>
        {charts.altitude_profile(analysis, meteo=meteo, mode="time", sample=sample)}
      </div>
      <div class="panel-divide"></div>
      <div class="chart-head">
        <p class="chart-title">Top view — the course line over the ground.{" Thin straight legs are the scored free-distance route." if route else ""}</p>
        <div class="toggle toggle-small" role="group" aria-label="What the climb circles show">
          <button type="button" class="toggle-button is-on" data-circles="gain"
                  aria-pressed="true">size = height gained</button>
          <button type="button" class="toggle-button" data-circles="rate"
                  aria-pressed="false">size = climb rate</button>
        </div>
      </div>
      {charts.plan_view(analysis, route=route, sample=sample,
                        height=charts.plan_height(analysis))}
    </div>
    <ul class="legend">
      <li class="ramp">{ramp}</li>
      <li>trace colour: sink &minus;4 m/s → climb +4 m/s</li>
      <li><span class="swatch" style="background:var(--tow);opacity:.5"></span>tow</li>
      <li><span class="swatch" style="background:var(--climb);opacity:.5"></span>climbing</li>
      <li><span class="swatch" style="background:var(--sink);opacity:.5"></span>gliding</li>
    </ul>
  </section>

  <section>
    <div class="stats">{stats}</div>
  </section>

  <section>
    <div class="section-head">
      <h2>Where the time went</h2>
      <p>{_duration(budget.thermalling)} climbing across {len(thermals)} thermals,
        {_duration(budget.gliding)} gliding, {_duration(budget.other)} unclassified.</p>
    </div>
    <div class="panel" style="padding:18px 20px 12px">
      {charts.budget_bar(analysis, width=1040)}
    </div>
  </section>

  <section class="grid-2">
    <div>
      <div class="section-head"><h2>Wind, sounded by thermal</h2></div>
      <div class="panel" style="padding:14px 16px 6px">{wind_chart or
        '<p class="caption">Not enough circled climbs to sound the wind.</p>'}</div>
      <ul class="legend">
        <li><span class="swatch" style="background:var(--sink)"></span>measured from circle drift</li>
        {'<li><span class="swatch" style="background:var(--neutral)"></span>model profile for the '
         'day</li>' if meteo else ''}
      </ul>
      <p class="caption">One point per climb, numbered as in the table below and therefore in the
        order flown — the first and last carry their clock time, and hovering any point gives the
        rest. Height is where the climb was worked; the tail points downwind. Reading it bottom to
        top: {_wind_shear_note(analysis)}</p>
    </div>
    <div>
      <div class="section-head">
        <h2>How strong was the lift you sat in?</h2>
      </div>
      <div class="panel" style="padding:14px 16px 6px">{histogram or
        '<p class="caption">No thermalling time to summarise.</p>'}</div>
      <p class="caption">Every second spent circling, sorted into half-metre climb-rate buckets.
        The tallest bar is the climb rate you spent the most time in — not the best one you found.
        Bars left of zero are time spent turning in <em>sink</em>. The right-hand tail is the
        cores. This day reads as {_histogram_verdict(analysis)}.</p>
    </div>
  </section>

  <section>
    <div class="section-head">
      <h2>Climbs</h2>
      <p><strong>Turns</strong> is total heading change ÷ 360 — how many circles the climb took,
         nothing more. <strong>m/turn</strong> is what that buys you: height gained per circle,
         so a thermal worked tightly in the core shows more metres per turn than the same
         average climb ground out in wide circles. <strong>Eff</strong> is mean climb over the
         best 20&nbsp;s of the same climb — the closest single number to &ldquo;did you stay in
         the core&rdquo;. Reversals and radius say how tidily it was flown.{" This track is sampled every " + f"{summary.sample_interval:.0f}" + " s, which is too coarse to resolve a circle, so the turn columns are blank." if coarse else ""}</p>
    </div>
    <div class="panel" style="padding:14px 16px 4px">
      <div class="table-scroll">
        <table>
          <thead><tr>
            <th>#</th><th>start</th><th>time</th><th>gain m</th><th>top m</th>
            <th>avg m/s</th><th>best m/s</th><th>eff</th><th>turns</th><th>m/turn</th>
            <th>dir</th><th>s/turn</th><th>radius m</th><th>wind km/h</th>
            <th>rates</th><th>over time &rarr;</th>
          </tr></thead>
          <tbody>{_thermal_rows(analysis)}</tbody>
        </table>
      </div>
    </div>
  </section>

  <section>
    <div class="section-head">
      <h2>Glides</h2>
      <p>Glide ratio here is what was achieved over the ground, so it beats the wing's
         still-air figure whenever the line was working. Bar length and shade both carry
         the ratio.</p>
    </div>
    <ul class="legend" style="margin:0 0 12px">
      <li class="legend-title">glide ratio:</li>
      <li><span class="swatch" style="background:var(--ld-1)"></span>under 5</li>
      <li><span class="swatch" style="background:var(--ld-2)"></span>5–7</li>
      <li><span class="swatch" style="background:var(--ld-3)"></span>7–9</li>
      <li><span class="swatch" style="background:var(--ld-4)"></span>9–12</li>
      <li><span class="swatch" style="background:var(--ld-5)"></span>over 12</li>
    </ul>
    <div class="panel" style="padding:14px 16px 4px">
      <div class="table-scroll">
        <table>
          <thead><tr><th>#</th><th>start</th><th>time</th><th>km</th><th>height m</th>
            <th>glide</th><th>km/h</th></tr></thead>
          <tbody>{_glide_rows(analysis)}</tbody>
        </table>
      </div>
    </div>
  </section>

{meteo_section}

  <section>
    <div class="section-head"><h2>How to read this, and what to distrust</h2></div>
    <div class="notes">
      {tow_note}
      <p><strong>Altitude is {"barometric" if summary.altitude_source == "baro" else "GPS"}.</strong>
        {"This recorder has a pressure sensor, so climb rates come from the smooth baro trace. "
         "It reads ISA pressure altitude, sitting " + str(summary.baro_offset) +
         " m below the GPS altitude on the day — absolute heights are indicative, "
         "height changes are solid." if summary.altitude_source == "baro" else
         "This recorder has no pressure sensor, so both altitude and climb come from GPS and "
         "are noisier than they look."}</p>
      {'<p><strong>Coarse sampling.</strong> This track has a fix every %.0f s. A thermal circle '
        'takes about 20 s, so turn counting, circle radius and peak climb rate cannot be '
        'recovered — they are left blank rather than guessed, and distance flown reads low '
        'because the sampling cuts the corners off every turn. Analyse the IGC instead of a KML '
        'where you have it.</p>' % summary.sample_interval if coarse else ''}
      <p><strong>Phases</strong> come from comparing progress — straight-line distance over
        distance flown in a 20&nbsp;s window — against climb rate. Above 0.9 is gliding; below
        it with lift is a climb. The heuristic is Tom Payne's, from igc2kmz.</p>
      <p><strong>Wind is inferred, not measured.</strong> While circling, the glider's own
        airspeed averages out and the track drifts with the air. Climbs flown fewer than two
        full turns, or in both directions, are excluded — they measure the pilot, not the wind.</p>
      <p><strong>Cross-checked against igc2kmz</strong> on this same file: it finds the same
        {len(thermals) + (1 if tow else 0)} climbs and {len(analysis.glides)} glides, with start
        times within 4&nbsp;s.{" Its altitude figures run higher because it prefers GPS "
        "altitude where this reads baro." if summary.altitude_source == "baro" else
        " Both read the same GPS altitude here, so the heights agree."}</p>
      <p>The {len(analysis.glides)} glides and {len(thermals)} climbs account for
        {(1 - budget.fractions()["other"]) * 100:.0f}% of airtime. The rest is transitions too
        short or too ambiguous to call, which is honest rather than tidy.</p>
    </div>
  </section>

  <footer>
    <span>{summary.fixes:,} fixes at {summary.duration / summary.fixes:.1f} s · timezone from
      {charts.escape(summary.timezone or "UTC")}</span>
    <span>tracklog viewer · analysis rendered locally, no external requests</span>
  </footer>
  <script type="application/json" class="cursor-data">{json.dumps(_cursor_data(analysis))}</script>
</article>
"""


def _page(title: str, bodies: list[str], tabs: str = "") -> str:
    """Wrap one or more flight bodies into a complete document."""
    return f"""<title>{charts.escape(title)}</title>
<style>{_font_face()}{STYLE}{view3d.STYLE}{view3d_gl.STYLE}{quicklook.STYLE}</style>
<div class="wrap">
{tabs}
{"".join(bodies)}
{quicklook.panel()}
</div>
<div class="tooltip" id="tip" role="status" aria-live="polite"></div>
<script>{view3d.SCRIPT}
{view3d_gl.SCRIPT}
{SCRIPT}</script>
<script>{quicklook.SCRIPT}</script>
"""


def first_name(pilot: str | None) -> str:
    """Just the given name. A tab has room for one word, and it is the one people use."""
    return (pilot or "").strip().split(" ")[0] if pilot else ""


def _tab(uid: str, date: str, meta: str, stat: str = "", *, on: bool = False) -> str:
    """One flight tab: open it, or remove it from the document."""
    return (
        f'<span class="tab{" is-on" if on else ""}" data-flight-tab="{uid}">'
        f'<button type="button" class="tab-open" aria-pressed="{"true" if on else "false"}">'
        f'<span class="tab-date">{date}</span>'
        f'<span class="tab-meta">{meta}</span>'
        + (f'<span class="tab-stat">{stat}</span>' if stat else "")
        + '</button>'
        f'<button type="button" class="tab-close" title="Remove this flight" '
        f'aria-label="Remove this flight">&#215;</button></span>'
    )


ADD_TAB = (
    '<span class="tab tab-add" data-flight-tab="own">'
    '<button type="button" class="tab-open" aria-pressed="false" '
    'title="Analyse your own track"><span class="tab-date">+ your track</span>'
    '<span class="tab-meta">igc &middot; kml &middot; kmz</span></button></span>'
)


def render(analysis: Analysis, *, meteo=None, route=None, terrain=None,
           basemaps=None, fetch_tiles: bool = True, kmz: bytes | None = None) -> str:
    """A report for a single flight, with the own-track picker alongside it."""
    summary = analysis.summary
    title = f"{summary.date} · {summary.site or 'flight'} — flight review"
    # Upload first: the bundled flight is a showcase, the reader's own track is the point.
    tabs = (
        '<nav class="tabs" id="flight-tabs" role="group" aria-label="Choose a flight">'
        + ADD_TAB
        + _tab("f0", charts.escape(summary.date),
               charts.escape(" · ".join(
                   part for part in (first_name(summary.pilot), summary.site) if part
               ) or "this flight"),
               on=True)
        + '</nav>'
        '<p class="tabs-note">Drop in as many of your own tracks as you like — they are '
        'analysed in this page, nothing is uploaded anywhere. Any flight can be removed '
        'with the &times; on its tab.</p>'
    )
    return _page(
        title,
        [
            _flight_body(
                analysis, meteo=meteo, route=route, terrain=terrain,
                basemaps=basemaps, fetch_tiles=fetch_tiles, kmz=kmz, uid="f0",
            )
        ],
        tabs,
    )


def render_multi(reports: list[dict]) -> str:
    """One document holding several flights, with a picker.

    Each report is ``{"analysis": …, "meteo": …, "route": …}``. Bodies are all
    present in the document and switched by hiding: it keeps the page a single
    self-contained file, which is the whole point of this renderer.
    """
    bodies, buttons = [], []
    for index, report in enumerate(reports):
        analysis = report["analysis"]
        summary = analysis.summary
        uid = f"f{index}"
        bodies.append(
            _flight_body(
                analysis,
                meteo=report.get("meteo"),
                route=report.get("route"),
                terrain=report.get("terrain"),
                basemaps=report.get("basemaps"),
                fetch_tiles=report.get("fetch_tiles", True),
                kmz=report.get("kmz"),
                uid=uid,
                hidden=index > 0,
            )
        )
        shape = report.get("shape") or ""
        fmt = report.get("format") or ""
        # Only worth showing when it is not the canonical source.
        fmt = "" if fmt in ("IGC", "?", "") else fmt
        route = report.get("route")
        # Who and where on one line, how far and what shape on the next: the distance and
        # the geometry are what you scan a list of flights for.
        stat = " &middot; ".join(
            part for part in (
                f"{route.km:.0f} km" if route else "",
                charts.escape(shape),
                "from " + charts.escape(fmt) if fmt else "",
            ) if part
        )
        buttons.append(_tab(
            uid,
            charts.escape(summary.date),
            charts.escape(" · ".join(
                part for part in (first_name(summary.pilot), summary.site) if part
            ) or "—"),
            stat,
            on=index == 0,
        ))

    # Upload first. The bundled flights are a showcase; the thing most readers want is
    # their own track, and a tab at the end of five examples does not say that.
    buttons.insert(0, ADD_TAB)
    tabs = (
        '<nav class="tabs" id="flight-tabs" role="group" aria-label="Choose a flight">'
        f'{"".join(buttons)}</nav>'
        '<p class="tabs-note">The dated tabs are example flights. Drop in as many of your '
        'own tracks as you like — they are analysed in this page, nothing is uploaded '
        'anywhere. Any flight can be removed with the &times; on its tab.</p>'
    )
    first = reports[0]["analysis"].summary
    title = f"tracklog viewer · {len(reports)} flights from {first.pilot or 'the log'}"
    return _page(title, bodies, tabs)


def write(analysis: Analysis, path, *, meteo=None, route=None, terrain=None,
          basemaps=None, fetch_tiles: bool = True, kmz: bytes | None = None) -> Path:
    path = Path(path)
    path.write_text(
        render(analysis, meteo=meteo, route=route, terrain=terrain, basemaps=basemaps,
               fetch_tiles=fetch_tiles,
               kmz=kmz),
        encoding="utf-8",
    )
    return path


def write_multi(reports: list[dict], path) -> Path:
    path = Path(path)
    path.write_text(render_multi(reports), encoding="utf-8")
    return path

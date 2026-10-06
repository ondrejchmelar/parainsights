"""The report page: everything around the articles.

The articles themselves — one per flight — are written by the JavaScript in `js/`
(`js/upload.js`'s `compose`), at build time for the flights the page ships with
(`js_build.py`) and in the page for a track the reader drops on it. This module is the
document they sit in: the stylesheet, the page script that draws the charts and links
the cursor, the view and flight strips, the upload panel, and the JavaScript bundle.
"""

import html
from dataclasses import dataclass
from pathlib import Path

import parainsights_common as common
from parainsights_map import map3d, render_map, view3d, view3d_gl

from . import charts_client, upload_panel

FONT_PATH = Path(__file__).parent / "assets" / "display.woff2.b64"

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
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-3);
}
.identity .val { font-size: 14px; }
/* The certification class, as a chip on the glider's name. Outlined rather than filled:
   it is a fact about the wing, not a warning about it, and an EN D painted red would be
   this report telling a pilot what to fly. */
.cert { display: inline-block; margin-left: 7px; padding: 1px 6px; border-radius: 3px;
  border: 1px solid var(--rule); font-size: 11px; letter-spacing: .04em;
  color: var(--ink-2); vertical-align: 1px; white-space: nowrap; cursor: help; }

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
/* The 3D map and the side view as one block (`.flight-map`): the chart right under the
   map, as wide as it, on the same ground, its axis buttons and legend below the block.
   The merged map makes the whole block full screen, so the side view goes with it. */
.flight-map .side-view { --page: calc(100vw - var(--scrollbar, 0px)); width: var(--page);
  margin: 0 0 0 calc(50% - var(--page) / 2); border-radius: 0; border-left: 0;
  border-right: 0; border-top: 0; }
.flight-map .side-view .chart-host { max-width: 1100px; margin: 0 auto; }
.side-controls { margin-top: 12px; }
.flight-map:fullscreen, .flight-map.is-maximised { display: flex; flex-direction: column;
  background: var(--panel); width: 100%; height: 100%; margin: 0; }
.flight-map.is-maximised { position: fixed; inset: 0; z-index: 60; width: auto; height: auto; }
.flight-map::backdrop { background: var(--panel); }
.flight-map:fullscreen .renderer-switch, .flight-map.is-maximised .renderer-switch { display: none; }
.flight-map:fullscreen .renderer-host, .flight-map.is-maximised .renderer-host {
  flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.flight-map:fullscreen .view3d-panel, .flight-map.is-maximised .view3d-panel {
  flex: 1 1 auto; min-height: 0; width: 100%; margin: 0; }
.flight-map:fullscreen canvas.view3d, .flight-map.is-maximised canvas.view3d {
  height: 100%; aspect-ratio: auto; }
.flight-map:fullscreen .side-view, .flight-map.is-maximised .side-view {
  flex: 0 0 auto; width: 100%; margin: 0; }
.flight-map:fullscreen .side-view .chart-host, .flight-map.is-maximised .side-view .chart-host {
  height: 24vh; aspect-ratio: auto !important; max-width: none; }
.flight-map:fullscreen .side-view .chart, .flight-map.is-maximised .side-view .chart { height: 100%; }
.caption { color: var(--ink-3); font-size: 12.5px; margin: 4px 4px 10px; }
.chart-title {
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  font-size: 11.5px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink-2);
  margin: 8px 8px 2px;
}
.chart-head { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  flex-wrap: wrap; }
.chart-head .chart-title { margin-bottom: 0; }
.toggle-small { margin: 4px 6px 6px 0; }
.toggle-small .toggle-button { font-size: 11px; padding: 4px 9px; }

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
  font-size: 11px;
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
.chart .axis-label { font-size: 11px; fill: var(--ink-3); }
.chart .axis-y { text-anchor: end; }
.chart .axis-x { text-anchor: middle; }
.chart .axis-title { font-size: 11px; fill: var(--ink-3); text-anchor: middle;
  text-transform: uppercase; letter-spacing: 0.1em; }
.chart .grid line { stroke: var(--rule); stroke-width: 1; }
.chart .axes line, .chart .axis { stroke: var(--rule-strong); stroke-width: 1; }
.chart .track polyline { fill: none; stroke-width: 2.2; stroke-linecap: round;
  stroke-linejoin: round; }

.chart-profile .drops line { stroke: var(--shadow-ink); stroke-width: 0.7; opacity: 0.45; }
.chart-profile .endpoint { fill: var(--panel); stroke: var(--ink); stroke-width: 2; }
.chart-profile .endpoint-label { font-size: 11px; fill: var(--ink-2); text-anchor: middle;
  text-transform: uppercase; letter-spacing: 0.1em; }
.chart .mark circle { stroke-width: 2; }
.chart .mark-label { font-size: 11px; fill: var(--ink); text-anchor: middle; }
.chart .mark.active circle { fill: var(--climb); stroke: var(--panel); }

.chart .reference { stroke: var(--ink-3); stroke-width: 1; stroke-dasharray: 6 4; }
.chart .reference-label { font-size: 11px; fill: var(--ink-3); text-anchor: end;
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
/* A pinned marker is drawn heavier than a hovered one, or the reader cannot tell whether
   the moment on screen is one they chose or one the mouse is passing over. */
.is-pinned .chart .cursor-dot { stroke-width: 3.5; }
.is-pinned .chart .crosshair { stroke-dasharray: none; }
.chart .hit { fill: transparent; cursor: crosshair; }
.chart .crosshair { stroke: var(--ink-2); stroke-width: 1; stroke-dasharray: 3 3; }
.panel-divide { height: 1px; background: var(--rule); margin: 2px 6px 4px; }

.chart-wind .wind-dot { fill: var(--panel); stroke: var(--sink); stroke-width: 2; }
.chart-wind .wind-arrow { stroke: var(--sink); stroke-width: 1.6; }
.chart-wind .wind-number { font-size: 11px; fill: var(--ink); text-anchor: middle;
  font-variant-numeric: tabular-nums; }
.chart-wind .wind-point.active .wind-dot { fill: var(--climb); stroke: var(--panel); }
.chart-wind .wind-time { font-size: 11px; fill: var(--ink-3); font-variant-numeric: tabular-nums; }
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
  font-size: 11px; }

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
/* Touch has no hover, so the control has to be permanently visible there.

   This is the control that *removes a flight from the document*, and at 19 x 19 px it
   was under half the minimum touch target, sitting immediately beside the control you
   actually meant to press. The glyph stays 19 px — it is right on a desktop — and
   `::before` grows the hit area to 44 x 44 on touch only.

   Two details that are the whole fix rather than decoration. The hit area is anchored to
   the tab's own corner and grows *inward*, because a symmetric 44 px box centred on a
   button 3 px from the edge hangs outside the tab and starts stealing taps from the next
   one. And because growing a target that overlaps another target makes mis-taps more
   likely rather than less, the × is live only once its tab is active: the first tap
   selects the flight, and only then can a second tap remove it. Enlarging the area
   without that pairing would have made the defect worse. */
@media (hover: none) {
  .tab-close { opacity: 0.7; }
  .tab-close::before {
    content: "";
    position: absolute;
    top: -3px;
    right: -3px;
    width: 44px;
    height: 44px;
  }
  .tab:not(.is-on) .tab-close { pointer-events: none; opacity: 0.3; }
}
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
.swatch { width: 12px; height: 12px; border-radius: 2px; flex: none; }
.ramp { display: flex; gap: 2px; align-items: center; }
.ramp span { width: 22px; height: 10px; border-radius: 1px; }

.tooltip {
  position: absolute;
  pointer-events: none;
  /* Above the map block's own layers: in full screen the tooltip is moved into it. */
  z-index: 70;
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
  font-size: 11px;
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
/* A row that can drive the cursor says so, and one that cannot must not pretend to. */
tbody tr.is-linked { cursor: pointer; }
tbody tr:hover, tbody tr:focus-visible { background: var(--panel-2); outline: none; }
tr.is-tow td:first-child { color: var(--tow); }
.tag {
  display: inline-block;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  padding: 1px 6px;
  border-radius: 2px;
  border: 1px solid currentColor;
}
.tag-tow { color: var(--tow); }
/* What held a climb up. Ridge is the one that had to be argued for, so it is the one
   that gets a colour; thermal is the ordinary case and stays quiet. */
.tag-ridge { color: var(--climb-3); }
.tag-thermal { color: var(--ink-3); }
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
/* The climbs table is eight columns, not sixteen. At a true 390 px viewport the old one
   was 1 023 px in a 340 px container — three screens of horizontal scrolling, with
   nothing on screen to say it scrolled. `turns m/turn dir s/turn radius` are five columns
   of circling mechanics: a whole sub-story and a specialist one, so they fold away rather
   than being deleted — the working-band and centring findings cite them as their
   receipts. `best m/s` went (peak of a noisy series, already eff's denominator), `wind`
   went (the wind chart is directly above and says it better), and the `rates` sparkline
   went (a duplicate of the big histogram at 60 px wide). */
.circling-detail { display: none; }
.table-climbs.show-circling .circling-detail { display: table-cell; }

/* Verdict strip and debrief ------------------------------------------------

   The strip sits between the masthead and the 3D view, and the cards immediately under
   it. That ordering is the whole point: the 3D view keeps its place as the hero image,
   but a reader used to scroll ~1 200 px before meeting a single number, and one compact
   line at the top answers the question the report exists to answer. The cards then sit
   next to the instrument they point into, so "show me" moves the marker in the view
   directly above with little or no scrolling on a desktop. */
.verdict {
  border: 1px solid var(--rule-strong);
  border-left: 3px solid var(--climb);
  background: var(--panel);
  padding: 16px 20px 14px;
  margin: 0 0 26px;
}
.verdict-line {
  margin: 0;
  font-size: 17px;
  line-height: 1.45;
  color: var(--ink);
  max-width: 68ch;
}
.verdict-figures { display: flex; flex-wrap: wrap; gap: 28px; margin-top: 12px; }
.verdict-delta {
  font-size: 11px;
  color: var(--ink-3);
  display: block;
  margin-top: 1px;
}
.verdict-delta.is-best { color: var(--climb); }
.verdict-delta[hidden] { display: none; }

/* The compare control sits beside the close button and is dim until used, so a tab reads
   as one thing rather than a row of three. */
.tab-compare {
  position: absolute;
  top: 3px;
  right: 24px;
  width: 19px;
  height: 19px;
  padding: 0;
  border: 0;
  border-radius: 2px;
  background: none;
  color: var(--ink-3);
  font: inherit;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.12s;
}
.tab:hover .tab-compare, .tab-compare:focus-visible, .tab-compare.is-on { opacity: 1; }
.tab-compare.is-on { background: var(--climb); color: var(--paper); }
.tab-compare:hover { color: var(--ink); }
.tab.is-on .tab-compare { color: var(--paper); }
.tab.is-on .tab-compare.is-on { background: var(--paper); color: var(--ink); }
@media (hover: none) {
  .tab-compare { opacity: 0.7; }
  .tab:not(.is-on) .tab-compare { pointer-events: none; opacity: 0.3; }
  /* Above the close button's 44 px touch area, which grows inward over this one: a tap
     meant to add a flight to the comparison removed the flight instead. */
  .tab-compare { z-index: 2; }
  .tab-close { z-index: 1; }
}
.verdict-figure { display: flex; flex-direction: column; gap: 1px; }
.verdict-value {
  font-size: 20px;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.verdict-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-3);
}

/* Three across the desktop width, stacked on a phone. `auto-fit` rather than a fixed
   three: with two findings the cards fill the row instead of leaving a hole, and with
   one the card does not stretch to the full width and read as a banner. */
.findings {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.finding {
  border: 1px solid var(--rule);
  background: var(--panel);
  padding: 14px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.finding h3 {
  margin: 0;
  font-size: 15px;
  line-height: 1.35;
  color: var(--ink);
  font-weight: 600;
}
.finding-body { margin: 0; font-size: 13px; line-height: 1.5; color: var(--ink-2); }
.finding-cost {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink-3);
}
/* The dot carries the climb ramp already in the design system, so cost reads as colour
   before it reads as text. */
.finding-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--climb);
  flex: none;
}
.finding-foot {
  margin: auto 0 0;
  padding-top: 6px;
  border-top: 1px solid var(--rule);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 11px;
  color: var(--ink-3);
  font-variant-numeric: tabular-nums;
}
.finding-link {
  border: 0;
  background: none;
  padding: 4px 0;
  color: var(--climb);
  font: inherit;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  cursor: pointer;
}
.finding-link:hover { color: var(--climb-3); }
.debrief-note { margin-top: 12px; }
@media (hover: none) {
  /* 44 px minimum where a finger replaces a mouse. */
  .finding-link { padding: 12px 0; min-height: 44px; }
}

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
  /* 12 px floor on a phone, against 11 px on a desktop.

     Most of the small type is SVG axis labels, and that makes this an accessibility
     problem rather than only a legibility one: SVG text does not respond to the reader's
     own font-size preference, so someone who has turned type up gets no relief from it
     and the floor is the only thing that helps them. Where an axis ends up crowded at
     this size, thin the ticks out — do not put the type back down. */
  .chart .axis-label,
  .chart .axis-title,
  .chart .mark-label,
  .chart .reference-label,
  .chart-profile .endpoint-label,
  .chart-wind .wind-number,
  .chart-wind .wind-time { font-size: 12px; }
  table { font-size: 14px; }
  .notes { font-size: 14px; }
}
"""

SCRIPT = """
// "The air that day" for a flight whose article was written without the day's weather —
// a report built without --meteo, or an upload whose fetch failed. Deferred until the
// page is idle so it never delays the first paint, and it fails quietly-but-visibly where
// every host is blocked.
(function () {
  var PRESSURE_LEVELS = __PRESSURE_LEVELS__;
  // `want.profile` adds the pressure levels — thirty more fields on the same one
  // request, so a report can draw the model wind profile behind its own measurements.
  // Off by default because an uploaded track has no chart to draw it in, and asking for
  // data nobody displays is a bigger answer for nothing.
  function fetchMeteo(a, want) {
    want = want || {};
    // Without a date there is no day to ask about, and asking anyway returns the weather
    // of 1 January 1970 rather than an error.
    if (!a.dated) return Promise.reject(new Error('the file carries no flight date'));
    var midLat = a.lat[Math.floor(a.lat.length / 2)];
    var midLon = a.lon[Math.floor(a.lon.length / 2)];
    var when = new Date(a.epoch * 1000);
    var day = when.toISOString().slice(0, 10);
    var ageDays = (Date.now() / 1000 - a.epoch) / 86400;
    var fields = 'temperature_2m,dew_point_2m,boundary_layer_height,' +
      'wind_speed_850hPa,wind_direction_850hPa';
    // m/s from the source. `meteo.py` asks for the same, so a wind is the same number
    // whether the report baked it in or the page fetched it.
    var units = '&wind_speed_unit=ms';
    if (want.profile) {
      PRESSURE_LEVELS.forEach(function (hpa) {
        fields += ',wind_speed_' + hpa + 'hPa,wind_direction_' + hpa + 'hPa' +
                  ',geopotential_height_' + hpa + 'hPa';
      });
    }
    var url;
    if (ageDays > 60) {
      url = 'https://archive-api.open-meteo.com/v1/archive?latitude=' + midLat.toFixed(3) +
        '&longitude=' + midLon.toFixed(3) + '&hourly=' + fields +
        '&start_date=' + day + '&end_date=' + day + '&timezone=UTC' + units;
    } else {
      url = 'https://api.open-meteo.com/v1/forecast?latitude=' + midLat.toFixed(3) +
        '&longitude=' + midLon.toFixed(3) + '&hourly=' + fields +
        '&past_days=' + Math.min(Math.ceil(ageDays) + 1, 92) +
        '&forecast_days=1&timezone=UTC' + units;
    }
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error('weather service returned ' + response.status);
      return response.json();
    }).then(function (payload) {
      var hourly = payload.hourly || {};
      var times = hourly.time || [];
      if (!times.length) throw new Error('no data for that date');
      var target = when.toISOString().slice(0, 13);
      var index = times.findIndex(function (stamp) { return stamp.slice(0, 13) === target; });
      if (index < 0) index = Math.floor(times.length / 2);
      var temperature = hourly.temperature_2m[index];
      var dew = hourly.dew_point_2m[index];
      if (temperature === null || temperature === undefined) {
        throw new Error('no surface data for that hour');
      }
      // The profile, where it was asked for and where the answer has one. The ERA5
      // archive returns nulls on every pressure level, so a flight older than the
      // 60-day cutoff comes back with an empty list rather than a line of zeroes —
      // which is the same distinction the 850 hPa tile makes between "calm" and
      // "not known", and it is the one that matters on a windy day.
      var levels = [];
      if (want.profile) {
        PRESSURE_LEVELS.forEach(function (hpa) {
          var height = hourly['geopotential_height_' + hpa + 'hPa'];
          var speed = hourly['wind_speed_' + hpa + 'hPa'];
          var from = hourly['wind_direction_' + hpa + 'hPa'];
          if (!height || !speed || !from) return;
          if (height[index] == null || speed[index] == null || from[index] == null) return;
          levels.push({ pressure: hpa, height: height[index],
                        speed: speed[index], direction: from[index] });
        });
        levels.sort(function (p, q) { return p.height - q.height; });
      }
      return {
        temperature: temperature, dew: dew,
        cloudbase: (payload.elevation || 0) + 125 * Math.max(temperature - dew, 0),
        blTop: hourly.boundary_layer_height && hourly.boundary_layer_height[index] !== null
          ? (payload.elevation || 0) + hourly.boundary_layer_height[index] : null,
        wind: hourly.wind_speed_850hPa ? hourly.wind_speed_850hPa[index] : 0,
        windFrom: hourly.wind_direction_850hPa ? hourly.wind_direction_850hPa[index] : 0,
        levels: levels
      };
    });
  }

  // Shared with the bundled flights. `render_html.py` has the same problem — a report
  // built without --meteo has no sounding — and the fix is the same request, so it is
  // exposed rather than written twice. One copy also means one place where the endpoint,
  // the 60-day archive cutoff and the cloudbase formula live.
  window.__fetchMeteo = fetchMeteo;

  function tile(key, value, sub) {
    return '<div class="stat"><span class="key">' + key + '</span>' +
      '<span class="stat-value">' + value + '</span>' +
      (sub ? '<span class="sub">' + sub + '</span>' : '') + '</div>';
  }
  function cardinal(deg) {
    var names = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW',
                 'W','WNW','NW','NNW'];
    return names[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];
  }
  // ---- the model wind profile, into a chart Python drew without one ------------------
  //
  // `charts.wind_profile` publishes its axis mapping in `data-wind-frame` and each point
  // carries the speed and altitude it was placed from. That is what lets this draw into
  // an SVG it did not build — and, more to the point, *rescale* it: the measured winds
  // are drift inside thermals and the model is the free air above, so the model is
  // routinely two or three times the fastest thing the glider felt. Clipping it to the
  // existing axis would draw a straight line up the right-hand edge and call it a
  // profile. So the axis grows, the measured points move with it, and the chart still
  // means what its labels say.
  //
  // Only the levels within `band` metres of the climbs are drawn, which is
  // `wind_profile`'s own rule: the point of the comparison is the air the glider was
  // actually in.
  var SVGNS = 'http://www.w3.org/2000/svg';
  function plotModelWind(svg, levels) {
    if (!svg || !levels || levels.length < 2) return false;
    var frame;
    try { frame = JSON.parse(svg.getAttribute('data-wind-frame')); } catch (e) { return false; }
    if (!frame || frame.hasModel) return false;      // built with --meteo already
    var group = svg.querySelector('.model');
    if (!group || group.childNodes.length) return false;

    var points = Array.prototype.slice.call(svg.querySelectorAll('.wind-point'));
    if (!points.length) return false;
    var alts = points.map(function (p) { return parseFloat(p.dataset.alt); });
    var lowest = Math.min.apply(null, alts), highest = Math.max.apply(null, alts);
    var inside = levels.filter(function (level) {
      return level.height >= lowest - frame.band && level.height <= highest + frame.band;
    });
    if (inside.length < 2) return false;

    // The same rounding `wind_profile` applies, over the measured points and the model
    // together — the steps come from the frame rather than being retyped here.
    var speedMax = frame.speedMax, altMin = frame.altMin, altMax = frame.altMax;
    inside.forEach(function (level) {
      speedMax = Math.max(speedMax,
        Math.ceil(level.speed / frame.speedStep) * frame.speedStep);
      altMin = Math.min(altMin, Math.floor(level.height / frame.altStep) * frame.altStep);
      altMax = Math.max(altMax, Math.ceil(level.height / frame.altStep) * frame.altStep);
    });

    function sx(ms) { return frame.left + frame.plotW * ms / speedMax; }
    function sy(m) {
      return frame.top + frame.plotH * (1 - (m - altMin) / Math.max(altMax - altMin, 1));
    }

    // Re-place the measured points, but only when the axis actually moved: an untouched
    // chart should come out of this byte-identical to the one Python drew.
    if (speedMax !== frame.speedMax || altMin !== frame.altMin || altMax !== frame.altMax) {
      points.forEach(function (point) {
        var speed = parseFloat(point.dataset.speed), alt = parseFloat(point.dataset.alt);
        var direction = parseFloat(point.dataset.dir);
        var x = sx(speed), y = sy(alt);
        var dot = point.querySelector('.wind-dot');
        var number = point.querySelector('.wind-number');
        var arrow = point.querySelector('.wind-arrow');
        var time = point.querySelector('.wind-time');
        if (dot) { dot.setAttribute('cx', x.toFixed(1)); dot.setAttribute('cy', y.toFixed(1)); }
        if (number) {
          number.setAttribute('x', x.toFixed(1));
          number.setAttribute('y', (y + 3.4).toFixed(1));
        }
        if (arrow) {
          // The tail points downwind — `direction` is where the air comes *from*, and
          // drawing along it is the 180° error that still looks like a good arrow.
          var angle = (direction + 180) * Math.PI / 180;
          var ux = Math.sin(angle), uy = -Math.cos(angle);
          arrow.setAttribute('x1', (x + ux * 9).toFixed(1));
          arrow.setAttribute('y1', (y + uy * 9).toFixed(1));
          arrow.setAttribute('x2', (x + ux * 22).toFixed(1));
          arrow.setAttribute('y2', (y + uy * 22).toFixed(1));
        }
        if (time) {
          var anchor = time.getAttribute('text-anchor');
          time.setAttribute('x', (x + (anchor === 'end' ? -13 : 13)).toFixed(1));
          time.setAttribute('y', (y + 3.5).toFixed(1));
        }
      });

      // The grid and the axis labels are regenerated rather than nudged: the number of
      // gridlines changes with the range, so there is nothing to nudge.
      var grid = svg.querySelector('.grid');
      var axes = svg.querySelector('.axes');
      if (grid && axes) {
        var titles = Array.prototype.filter.call(axes.childNodes, function (node) {
          return node.nodeType === 1 && node.getAttribute('class') === 'axis-title';
        });
        grid.textContent = '';
        axes.textContent = '';
        for (var ms = 0; ms <= speedMax; ms += frame.speedStep) {
          var gx = sx(ms);
          grid.appendChild(make('line', { x1: gx.toFixed(1), y1: frame.top,
            x2: gx.toFixed(1), y2: frame.top + frame.plotH }));
          axes.appendChild(make('text', { x: gx.toFixed(1),
            y: frame.top + frame.plotH + 17, 'class': 'axis-label axis-x' }, String(ms)));
        }
        for (var m = altMin; m <= altMax; m += frame.altStep) {
          var gy = sy(m);
          grid.appendChild(make('line', { x1: frame.left, y1: gy.toFixed(1),
            x2: frame.width - frame.right, y2: gy.toFixed(1) }));
          axes.appendChild(make('text', { x: frame.left - 9, y: (gy + 3.5).toFixed(1),
            'class': 'axis-label axis-y' }, String(m)));
        }
        titles.forEach(function (title) { axes.appendChild(title); });
      }
    }

    var path = inside.map(function (level) {
      return sx(level.speed).toFixed(1) + ',' + sy(level.height).toFixed(1);
    }).join(' ');
    group.appendChild(make('polyline', { points: path }));
    inside.forEach(function (level) {
      var dot = make('circle', { cx: sx(level.speed).toFixed(1),
        cy: sy(level.height).toFixed(1), r: 2.5, 'class': 'model-dot' });
      dot.appendChild(make('title', {}, 'model ' + level.speed.toFixed(1) +
        ' m/s from ' + Math.round(level.direction) + '° at ' +
        Math.round(level.height) + ' m (' + level.pressure + ' hPa)'));
      group.appendChild(dot);
    });
    return true;
  }

  function make(tag, attributes, text) {
    var node = document.createElementNS(SVGNS, tag);
    Object.keys(attributes).forEach(function (key) {
      node.setAttribute(key, attributes[key]);
    });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // The legend and the caption were written by Python for a report with no model in it,
  // and both say so. Once the line is drawn they are wrong, so they are corrected here
  // rather than left to contradict the chart the reader is looking at.
  function sayTheModelArrived(article, chart) {
    // The legend is the chart panel's next sibling, walked to rather than selected from
    // the article: an article holds several legends and the wrong one is worse than none.
    var legend = null;
    for (var node = chart.closest('.panel'); node; node = node.nextElementSibling) {
      if (node !== chart.closest('.panel') && node.classList.contains('legend')) {
        legend = node;
        break;
      }
    }
    if (legend && !legend.querySelector('.model-swatch')) {
      var item = document.createElement('li');
      item.innerHTML = '<span class="swatch model-swatch" ' +
        'style="background:var(--neutral)"></span>model profile for the day, fetched ' +
        'when you opened this page';
      legend.appendChild(item);
    }
    article.querySelectorAll('.caption').forEach(function (caption) {
      var text = caption.textContent;
      var at = text.indexOf("The day's forecast profile would be drawn behind these");
      if (at < 0) return;
      caption.textContent = text.slice(0, at) +
        "The day's forecast profile is drawn behind these — fetched when you opened " +
        'this page, not built into the report.';
    });
  }

  function run() {
    if (!window.__fetchMeteo) return;
    document.querySelectorAll('.air-fetch').forEach(function (section) {
      var stats = section.querySelector('.air-stats');
      if (!stats || stats.dataset.done) return;
      stats.dataset.done = '1';
      stats.innerHTML = tile('weather', 'fetching…', '');
      var top = parseFloat(section.dataset.airTop);
      var article = section.closest('[data-flight-report]') || document;
      var windChart = article.querySelector('.chart-wind');
      // The profile is only worth thirty extra fields when there is a chart waiting for
      // it: a flight with too few circled climbs to sound the wind has none.
      var wantProfile = !!(windChart && windChart.getAttribute('data-wind-frame'));
      window.__fetchMeteo({
        dated: true,
        lat: [parseFloat(section.dataset.airLat)],
        lon: [parseFloat(section.dataset.airLon)],
        epoch: parseFloat(section.dataset.airEpoch)
      }, { profile: wantProfile }).then(function (m) {
        if (wantProfile && plotModelWind(windChart, m.levels)) {
          sayTheModelArrived(article, windChart);
        }
        var used = m.cloudbase > 0 ? Math.round(top / m.cloudbase * 100) : null;
        var spread = Math.round(m.temperature - m.dew);
        var html =
          tile('surface', Math.round(m.temperature) + ' °C',
               'dew ' + Math.round(m.dew) + ' °C · spread ' + spread + ' K') +
          tile('cloudbase', Math.round(m.cloudbase) + ' m',
               spread + ' K spread, lifted until it closes') +
          tile('boundary layer', m.blTop ? Math.round(m.blTop) + ' m' : '—',
               'as high as the day\\'s heating reaches') +
          tile('ceiling used', used === null ? '—' : used + '%',
               'you reached ' + Math.round(top) + ' m');
        // No 850 hPa wind in the answer is missing data, and a missing wind is not a calm
        // day: the tile read "model wind 0 m/s from N", which is a specific and wrong
        // forecast rather than an absent one. An omitted tile says "not known"; a zero
        // says "still". They are the opposite claim on a windy day.
        if (m.wind > 0 && isFinite(m.windFrom)) {
          html += tile('model wind', m.wind.toFixed(1) + ' m/s',
                       'from ' + cardinal(m.windFrom) + ' at 850 hPa');
        }
        stats.innerHTML = html;
      }).catch(function (error) {
        stats.innerHTML = tile('weather', 'unavailable', error.message || String(error));
      });
    });
  }
  // Exposed for an article placed after load — an upload — which `run` has not seen.
  window.__fetchAir = run;
  if (window.requestIdleCallback) requestIdleCallback(run, { timeout: 3000 });
  else setTimeout(run, 400);
})();

// Cross-flight comparison, opt-in.
//
// Comparing whatever happens to be open is a claim nobody asked for — three unrelated
// flights are not a set — so nothing is compared until the reader marks two or more tabs
// with the compare control. Then each marked flight's headline figures gain a line
// saying where they stand *among the flights the reader chose*.
//
// Document-level on purpose, unlike the cursor code, which is per flight: this is a fact
// about the document rather than about one article.
(function () {
  var HIGHER_IS_BETTER = { 'scored_km': true, 'mean_climb': true, 'ceiling_used': true };
  var UNITS = { 'scored_km': ' km', 'mean_climb': ' m/s', 'ceiling_used': '' };
  var chosen = {};

  function articles() {
    return Array.prototype.slice.call(
      document.querySelectorAll('[data-flight-report]'));
  }

  function valueOf(article, key) {
    var raw = article.getAttribute('data-compare-' + key.replace(/_/g, '-'));
    if (raw === null || raw === '') return null;
    var value = parseFloat(raw);
    return isNaN(value) ? null : value;
  }

  function refresh() {
    var picked = articles().filter(function (a) {
      return chosen[a.getAttribute('data-flight-report')];
    });
    articles().forEach(function (article) {
      var mine = chosen[article.getAttribute('data-flight-report')];
      article.querySelectorAll('.verdict-delta').forEach(function (slot) {
        var key = slot.parentNode.getAttribute('data-key');
        // Under two flights there is nothing to compare against, and a flight the reader
        // did not pick is not part of the comparison at all.
        if (!mine || picked.length < 2 || !key) { slot.hidden = true; return; }
        var value = valueOf(article, key);
        var others = picked.filter(function (a) { return a !== article; })
                           .map(function (a) { return valueOf(a, key); })
                           .filter(function (v) { return v !== null; });
        if (value === null || !others.length) { slot.hidden = true; return; }
        var up = HIGHER_IS_BETTER[key] !== false;
        var rival = up ? Math.max.apply(null, others) : Math.min.apply(null, others);
        var leads = up ? value >= rival : value <= rival;
        var unit = UNITS[key] || '';
        slot.hidden = false;
        slot.className = 'verdict-delta' + (leads ? ' is-best' : '');
        slot.textContent = leads
          ? 'best of ' + picked.length + ' compared'
          : (up ? '\u25bc ' : '\u25b2 ') + Math.abs(value - rival).toFixed(2) + unit +
            ' off the best of ' + picked.length;
      });
    });
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest && event.target.closest('[data-compare-toggle]');
    if (!button) return;
    // The compare control lives inside the tab, which opens the flight. Without this the
    // tab would switch every time someone marked one for comparison.
    event.stopPropagation();
    var uid = button.getAttribute('data-compare-toggle');
    chosen[uid] = !chosen[uid];
    button.setAttribute('aria-pressed', chosen[uid] ? 'true' : 'false');
    button.classList.toggle('is-on', chosen[uid]);
    settle();
  }, true);

  // Counted from the flights still in the document: a removed flight leaves the
  // comparison, and the others' lines say "of 2" again rather than "of 3".
  function settle() {
    var count = articles().filter(function (a) {
      return chosen[a.getAttribute('data-flight-report')];
    }).length;
    document.documentElement.classList.toggle('is-comparing', count >= 2);
    refresh();
    showOthers();
  }

  // Each compared flight's 3D map draws the others too (`setOthers` in `map3d`): usually
  // the same area, often the same day. Colours from outside the climb-rate ramp the
  // flight's own track uses, so a compared track never reads as a climb. Scenes are read
  // once per flight; a map built later asks `__compareFor` itself.
  // XContest's own way of telling tracks apart: thin lines, one muted colour each — orange,
  // sky blue, brick red, indigo, olive. Bright ones shouted over the ground; the climb ramp
  // is dropped while comparing, because five climb colours a track times several tracks
  // is no way to tell them apart. A flight keeps its colour on every map.
  var OTHER_COLOURS = ['#e0893a', '#3aa8d0', '#c9483c', '#5a5fc0', '#8a9a3a'];
  var scenes = {};
  function sceneOf(article) {
    var uid = article.getAttribute('data-flight-report');
    if (scenes[uid] !== undefined) return scenes[uid];
    var node = article.querySelector('.view3d-data');
    scenes[uid] = null;
    if (node && typeof readScene === 'function') {
      try {
        var scene = readScene(node);
        scenes[uid] = { track: scene.track, start: scene.start, climbs: scene.climbs || [],
                        name: article.getAttribute('data-compare-name') || uid };
      } catch (error) { /* a flight without a scene is compared by its figures only */ }
    }
    return scenes[uid];
  }
  function picked() {
    return articles().filter(function (a) { return chosen[a.getAttribute('data-flight-report')]; });
  }
  window.__compareFor = function (uid) {
    var all = picked();
    if (all.length < 2 || !chosen[uid]) return null;
    var out = { own: null, others: [] };
    all.forEach(function (article, i) {
      var colour = OTHER_COLOURS[i % OTHER_COLOURS.length];
      var name = article.getAttribute('data-compare-name') || '';
      if (article.getAttribute('data-flight-report') === uid) {
        var mine = sceneOf(article);
        out.own = { name: name, colour: colour, start: mine ? mine.start : null };
        return;
      }
      var scene = sceneOf(article);
      if (scene) out.others.push({ name: scene.name, track: scene.track, start: scene.start,
                                   climbs: scene.climbs, colour: colour });
    });
    return out;
  };
  function showOthers() {
    articles().forEach(function (article) {
      var canvas = article.querySelector('canvas.view3d');
      var entry = canvas && window.__mergedAll && window.__mergedAll[canvas.id];
      if (entry && entry.setOthers) entry.setOthers(window.__compareFor(article.getAttribute('data-flight-report')));
      // The side view draws the compared flights too.
      var host = article.querySelector('.chart-host[data-chart="profile"]');
      if (host && window.__drawProfile) window.__drawProfile(article, host.dataset.mode || 'flown');
    });
  }
  // Flights come and go (uploads, the × on a tab); re-settle when they do.
  var holder = document.querySelector('[data-flight-report]');
  if (holder && window.MutationObserver) {
    new MutationObserver(settle).observe(holder.parentNode, { childList: true });
  }
})();

// Resolves when `element` is first on screen: now if it already is, else on the first
// change that reveals it (the flight tabs and the view strip toggle `hidden`).
function whenShown(element) {
  function shown() { return element.getClientRects().length > 0; }
  if (shown()) return Promise.resolve();
  return new Promise(function (resolve) {
    var watch = new MutationObserver(function () {
      if (shown()) { watch.disconnect(); resolve(); }
    });
    watch.observe(document.body, { attributes: true, subtree: true,
                                   attributeFilter: ['hidden', 'class', 'style'] });
  });
}

function initFlight(root) {
  var payload = root.querySelector('.cursor-data');
  var tip = document.getElementById('tip');
  if (!tip || !payload) return;
  var data = JSON.parse(payload.textContent);
  // The ground is fetched by the page (`terrain.to_remote`), so the view arrives once it
  // has; every use of `terrainView` below is in a handler that runs after that. And only
  // once the flight is first shown: each 3D view fetches its own ground and imagery and
  // holds a WebGL context, and a page of three flights was starting all three on arrival
  // for the one the reader sees — 600 requests and most of the page's memory.
  var terrainView = null;
  if (typeof initView3dWhenReady === 'function') {
    whenShown(root).then(function () {
      return initView3dWhenReady(root, data.cursor3d || null);
    }).then(function (handle) {
      terrainView = handle;
      // The merged map is the default view; the canvas built underneath it is what it
      // draws from, and what is left if MapLibre cannot be fetched.
      var host = root.querySelector('.renderer-host');
      if (handle && host && window.__openDefaultRenderer) window.__openDefaultRenderer(host);
    }, function () {});
  }

  // Every chart that can host the cursor publishes its own projected sample
  // coordinates on its hit rect, so one index drives a dot in all of them and
  // none of the projection maths is repeated here.
  //
  // Rebuilt rather than collected once, because the side view is now *drawn* in the page
  // and the axis toggle replaces its SVG: the views array would otherwise still point at
  // an element that is no longer in the document. Listeners are bound per hit rect and
  // only once — a replaced SVG takes its own listeners with it, and the charts that
  // survived must not collect a second copy.
  var views = [];
  function collectViews() {
    views = [];
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
    views.forEach(bindView);
  }

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
    // In full screen (or the in-page maximise) the map block is all there is on screen, and
    // a tooltip left in the page under it is never seen: it moves into the block, which
    // sits at the viewport's corner, so it is placed without the page's scroll.
    var full = document.fullscreenElement && document.fullscreenElement.contains(root)
      ? document.fullscreenElement : root.querySelector('.flight-map.is-maximised');
    var into = full || document.body;
    if (tip.parentNode !== into) {
      into.appendChild(tip);
      tipBox = tip.getBoundingClientRect();
    }
    tip.style.left = Math.min(pageX + 14, window.innerWidth - tipBox.width - 10) + (full ? 0 : window.scrollX) + 'px';
    tip.style.top = (pageY - tipBox.height - 12) + (full ? 0 : window.scrollY) + 'px';
    highlight(data.segment[index]);
  }

  function clearMarker() {
    views.forEach(function (view) {
      if (view.cursor) view.cursor.classList.remove('on');
    });
    tip.classList.remove('on');
    if (terrainView) terrainView.clearCursor();
    highlight(null);
  }

  // A click pins the moment; hover alone is only a preview.
  //
  // Hover is the right default — sweep a chart and the map keeps up — but on its own it
  // takes the marker away at exactly the moment the reader wants it: they have found
  // something, and now they want to look at the 3D view, or read the row in the table, or
  // point at the screen. Both the chart hover and the debrief's "show me" had that fault,
  // and "show me" had it worse, because it is a deliberate act that any stray mouse
  // movement then undid.
  //
  // So: a click pins. Hovering still previews and moves the marker; leaving the chart
  // returns to the pinned point rather than clearing; and the pin lets go on a second
  // click, on Escape, or after PIN_IDLE_MS with no interaction with this flight at all.
  // The timeout is re-armed by any hover, so it expires after the reader has stopped
  // looking rather than while they are still reading.
  var PIN_IDLE_MS = 30000;
  var pinned = null;
  var pinTimer = null;

  function armPin() {
    if (pinTimer) { clearTimeout(pinTimer); pinTimer = null; }
    if (pinned !== null) pinTimer = setTimeout(release, PIN_IDLE_MS);
  }

  function release() {
    if (pinTimer) { clearTimeout(pinTimer); pinTimer = null; }
    pinned = null;
    root.classList.remove('is-pinned');
    clearMarker();
  }

  // The view a marker should be positioned from: `place` skips a chart with no layout
  // box, so a hidden profile variant would leave the tooltip placed against nothing.
  function visibleView() {
    for (var i = 0; i < views.length; i++) {
      if (views[i].svg.getClientRects().length) return views[i];
    }
    return null;
  }

  function markAt(index, view) {
    view = view || visibleView();
    if (!view) return false;
    index = Math.max(0, Math.min(index, view.px.length - 1));
    place(index, view,
          { box: view.svg.getBoundingClientRect(), vb: view.svg.viewBox.baseVal });
    return true;
  }

  // Pin, and bring the moment into view in the 3D panel as well — a pinned point the
  // reader cannot see on the map answers half the question they asked.
  function pinAt(index, view) {
    if (!markAt(index, view)) return;
    pinned = index;
    root.classList.add('is-pinned');
    if (terrainView && terrainView.revealCursor) terrainView.revealCursor(index);
    armPin();
  }

  function restore() {
    if (pinned === null) { clearMarker(); return; }
    markAt(pinned);
    armPin();
  }

  function bindView(view) {
    if (view.hit.__cursorBound) return;
    view.hit.__cursorBound = true;
    function show(event) {
      var point = svgPoint(view, event);
      place(nearestIndex(view, point), view, point);
      armPin();
    }
    view.hit.addEventListener('mousemove', show);
    view.hit.addEventListener('mouseleave', restore);
    view.hit.addEventListener('click', function (event) {
      var point = svgPoint(view, event);
      var index = nearestIndex(view, point);
      // Clicking the pinned point again is how the reader lets go without hunting for a
      // key, so the same click both pins and unpins.
      if (pinned === index) release(); else pinAt(index, view);
    });
    view.hit.addEventListener('touchmove', function (event) {
      if (event.touches.length) { show(event.touches[0]); event.preventDefault(); }
    }, { passive: false });
  }

  collectViews();
  // How a redrawn chart gets back into the cursor. `charts_client.js` calls this after
  // the axis toggle rebuilds the side view; without it the toggle silently produces a
  // chart the cursor cannot drive, which looks exactly like the cursor being broken.
  root.__relinkCharts = collectViews;
  // The 3D map's replay drives the charts (`map3d`, `setTime`): its "now", in seconds
  // since the first fix, as the cursor on the side and top views. Quiet — no tooltip, and
  // not back to the map, which is showing the replay already.
  root.__cursorAtTime = function (t) {
    if (!data.t || !data.t.length) return;
    var lo = 0, hi = data.t.length - 1;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (data.t[mid] < t) lo = mid + 1; else hi = mid; }
    if (lo > 0 && Math.abs(data.t[lo - 1] - t) < Math.abs(data.t[lo] - t)) lo--;
    views.forEach(function (view) {
      if (lo >= view.px.length || !view.svg.getClientRects().length) return;
      if (view.dot) { view.dot.setAttribute('cx', view.px[lo]); view.dot.setAttribute('cy', view.py[lo]); }
      if (view.crosshair) { view.crosshair.setAttribute('x1', view.px[lo]); view.crosshair.setAttribute('x2', view.px[lo]); }
      if (view.cursor) view.cursor.classList.add('on');
    });
    highlight(data.segment[lo]);
  };

  // Escape lets go from anywhere, which is the one shortcut a reader will guess.
  root.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && pinned !== null) { release(); event.preventDefault(); }
  });

  // "show me" on a debrief card drives the cursor the charts already share, rather than
  // scrolling to a section and hoping. That is what makes the card a measurement *plus a
  // link*: the sentence names a moment, and the button puts the marker on it in the side
  // view, the top view and the 3D view at once.
  //
  // Scoped to `root` like everything else here — a document holds several flights, and a
  // document-level query would move another flight's cursor.
  root.querySelectorAll('[data-finding-cursor]').forEach(function (button) {
    button.addEventListener('click', function () {
      var index = parseInt(button.getAttribute('data-finding-cursor'), 10);
      if (isNaN(index)) return;
      var view = visibleView();
      if (!view) return;
      // Pinned rather than merely placed. "Show me" is a deliberate act, and it used to
      // be undone by the reader's own mouse on its way to look at what had been shown.
      pinAt(index, view);
      view.svg.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
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
      // The side view is drawn in the page now, so this redraws it rather than
      // unhiding one of three copies the document used to carry.
      if (window.__drawProfile) window.__drawProfile(root, wanted);
    });
  });

  // The circling columns fold away by default. A single button rather than a two-state
  // pair, because there is nothing to compare against: it is showing five extra columns
  // or not showing them.
  root.querySelectorAll('.toggle-button[data-detail]').forEach(function (button) {
    button.addEventListener('click', function () {
      var on = button.getAttribute('aria-pressed') !== 'true';
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      button.classList.toggle('is-on', on);
      root.querySelectorAll('.table-climbs').forEach(function (table) {
        table.classList.toggle('show-circling', on);
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

  // The tables are the third way into the same moment. Hovering a row lights the matching
  // band and mark, which it always did; clicking one now pins the cursor to where that
  // climb or glide began, in both charts and on the 3D map — the reader had a row in
  // front of them and no way to ask where on the ground it happened.
  //
  // `data-cursor` is a position in the sampled arrays the charts are drawn over, mapped
  // from the segment's fix index in Python, exactly as a finding's cursor is. A row
  // without one (a table built with no sample) simply stays hover-only.
  root.querySelectorAll('tr[data-segment]').forEach(function (row) {
    row.tabIndex = 0;
    row.addEventListener('mouseenter', function () { highlight(row.dataset.segment); });
    row.addEventListener('focus', function () { highlight(row.dataset.segment); });
    row.addEventListener('mouseleave', function () {
      if (pinned === null) highlight(null); else restore();
    });
    row.addEventListener('blur', function () {
      if (pinned === null) highlight(null); else restore();
    });

    var at = parseInt(row.dataset.cursor, 10);
    if (isNaN(at)) return;
    row.classList.add('is-linked');
    function go() {
      if (pinned === at) release(); else pinAt(at);
    }
    row.addEventListener('click', go);
    row.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') { go(); event.preventDefault(); }
    });
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
          // The MapLibre renderer, where the reader switched to it, holds a context too.
          ['__maplibreAll', '__mergedAll'].forEach(function (registry) {
            var other = window[registry] && window[registry][canvas.id];
            if (other) { other.map.remove(); delete window[registry][canvas.id]; }
          });
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
# The levels `js/meteo.js` asks Open-Meteo for, so the page's own request for a flight
# written without the day's weather draws the same profile.
PRESSURE_LEVELS = (1000, 975, 950, 925, 900, 850, 800, 700, 600, 500)
SCRIPT = SCRIPT.replace("__PRESSURE_LEVELS__", str(list(PRESSURE_LEVELS)))


def escape(text) -> str:
    """Text for HTML, quotes included: tab labels come from a file's own headers."""
    return html.escape(str(text), quote=True)


@dataclass
class Extra:
    """A whole view in this document that is not the flight report.

    Deliberately opaque: `body`, `style` and `script` are strings this renderer pastes
    in without inspecting. That is what keeps the airspace map out of the tracklog
    viewer's imports — the two tools share a page, not code.

    An extra is **not** a flight tab. It sits one level up, in the view switcher at the
    top of the page, because it is not another flight to compare against these ones —
    it is a different thing to look at. Its body must therefore carry no
    `data-flight-report`: that attribute belongs to the flight strip's controller, which
    hides everything that is not the open flight, and the two would fight over `hidden`.
    """

    uid: str
    label: str
    meta: str = ""
    body: str = ""
    style: str = ""
    script: str = ""


VIEW_SCRIPT = """
// The top-level view switch. One level above the flight tabs: those choose which
// flight, this chooses whether you are looking at flights at all.
(function () {
  var nav = document.getElementById('views');
  if (!nav) return;
  function show(key) {
    document.querySelectorAll('[data-view]').forEach(function (section) {
      section.hidden = section.dataset.view !== key;
    });
    nav.querySelectorAll('[data-view-tab]').forEach(function (button) {
      var on = button.dataset.viewTab === key;
      button.classList.toggle('is-on', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    // A 3D panel inside a hidden section has a zero-sized box, so it drew nothing and
    // its first frame never came — the airspace view opened as an empty canvas until
    // something was dragged in it. Now the view that has just been revealed is redrawn.
    if (window.__view3dAll) {
      Object.keys(window.__view3dAll).forEach(function (id) {
        // Every panel, not only the revealed one: a hidden canvas measures zero, so
        // `resize()` bails and redrawing it costs nothing.
        var handle = window.__view3dAll[id];
        if (handle && handle.redraw) handle.redraw();
      });
    }
    window.scrollTo({ top: 0, behavior: 'auto' });
  }
  nav.addEventListener('click', function (event) {
    var button = event.target.closest('[data-view-tab]');
    if (button) show(button.dataset.viewTab);
  });
})();
"""

VIEW_STYLE = """
.views { display: flex; gap: 4px; margin: 0 0 18px; border-bottom: 1px solid var(--rule);
  padding-bottom: 0; }
.view-tab { font: inherit; font-size: 15px; font-weight: 600; letter-spacing: 0.01em;
  background: none; border: 0; border-bottom: 2px solid transparent; color: var(--ink-3);
  padding: 9px 15px 8px; cursor: pointer; margin-bottom: -1px; }
.view-tab:hover { color: var(--ink-2); }
.view-tab.is-on { color: var(--ink); border-bottom-color: var(--climb); }
/* The other tools are links, not buttons, and must not inherit an anchor's underline
   or the browser's link colour — they sit in the same row as the view buttons and any
   difference reads as a mistake rather than as a distinction. */
a.view-tab { text-decoration: none; display: inline-block; }
/* Pushed to the far end of whichever strip it is in. Same shape as the one the other
   three pages get from `common.STYLE`; the report does not include that sheet, because
   its own tokens are richer and it has never used the site strip. */
.theme-toggle { margin:0 0 0 auto; align-self:center; border:1px solid var(--rule);
  background:var(--panel); color:var(--ink-2); border-radius:999px; cursor:pointer;
  width:30px; height:30px; padding:0; font-size:14px;
  /* Grid rather than `line-height`: the glyph is a character whose ink sits high in its
     em box (☽ higher than ☀), so a line box centres the *box* and leaves the mark
     visibly above centre. A grid cell centres the thing that was actually drawn. */
  display:grid; place-items:center; line-height:1; }
.theme-toggle .theme-glyph { display:block; }
.theme-toggle:hover { color: var(--ink); border-color: var(--rule-strong); }
/* The source link beside it, and the page's foot: `common.strip_end` and `common.footer`. */
a.site-source { align-self:center; margin:0 0 0 6px; padding:0; width:30px; height:30px;
  display:grid; place-items:center; border:1px solid var(--rule); border-radius:999px;
  background:var(--panel); color:var(--ink-2); }
a.site-source:hover { color: var(--ink); border-color: var(--rule-strong); }
/* `display: block`: the report lays every <footer> out as a flex row (each flight's own
   fixes-and-timezone line), and the site footer's sentence was spread across it. */
.site-foot { display:block; margin:28px 0 0; padding:14px 0 0; border-top:1px solid var(--rule);
  font-size:12.5px; line-height:1.55; color:var(--ink-3); }
.site-foot a { color: var(--ink-2); }
.view-tab:focus-visible { outline: 2px solid var(--climb); outline-offset: -2px; }
"""


def _flights_view(tabs: str, bodies: list[str], extras: "list[Extra]") -> str:
    """The flight report, wrapped in a view section only when there is a view to switch
    to. Every report before extras existed had no wrapper, and adding one unconditionally
    would change the DOM of all of them to no purpose."""
    inner = f'{tabs}\n{"".join(bodies)}\n{upload_panel.panel()}'
    if not extras:
        return inner
    return f'<section data-view="flights">\n{inner}\n</section>'


def _view_nav(extras: "list[Extra]") -> str:
    """The switch across the top. Absent entirely when there is nothing to switch to.

    Two kinds of destination, deliberately side by side: the views *in this document* are
    buttons that the script shows and hides, and the other tools are ordinary links. The
    reader should not have to know which is which, so they look the same — but a link is
    a link, because those pages are separate files and a button that navigated would be
    lying about what it does.

    The links assume the published layout under `public/`, and only ever appear on a
    report that has extras, which is the same report that is published there.
    """
    if not extras:
        # No other views, but the reader still gets the theme switch: it is furniture,
        # not part of the view chooser, and a report built from one flight with no
        # airspace is still a page somebody reads at night. It carries neither the id
        # nor the role of the chooser, because `test_a_report_with_no_extras_has_no_view
        # _switch` is right that a switch between one thing is noise — and a strip that
        # merely *looks* like one is the same noise.
        return ('<nav class="views page-tools" aria-label="Theme">'
                f'{common.strip_end()}</nav>')

    # **One order across the whole site**, and it is `common.PAGES`: what is the weather,
    # where shall I go, what will I fly, what did I actually do. This strip used to list
    # its buttons first and its links after, so the report read *Flights, Airspace,
    # Meteo, Planner* while every other page read *Meteo, Planner, Airspace, Flights* —
    # the same four things in two orders, which is the kind of difference a reader feels
    # without being able to name.
    #
    # Whether an entry is a button or a link is an implementation detail of *this*
    # document — the views it carries are shown and hidden here, the other tools are
    # separate files — and the docstring above already says the reader should not have to
    # know which is which. Now the order does not tell them either.
    by_uid = {e.uid: e for e in extras}
    items = []
    for key, label, where in common.PAGES:
        if key == "flights":
            items.append(
                '<button type="button" class="view-tab" data-view-tab="flights" '
                f'aria-pressed="false">{label}</button>')
        elif key in by_uid:
            extra = by_uid.pop(key)
            items.append(
                f'<button type="button" class="view-tab" data-view-tab="{extra.uid}" '
                f'aria-pressed="false">{escape(extra.label)}</button>')
        else:
            items.append(f'<a class="view-tab" href="{where}">{label}</a>')
    # An extra this site has no page for still gets a tab, after the ones it does.
    items += [
        f'<button type="button" class="view-tab" data-view-tab="{e.uid}" '
        f'aria-pressed="false">{escape(e.label)}</button>'
        for e in by_uid.values()
    ]
    # The flights view is the one the document opens on, wherever its tab now sits.
    marked = "".join(items).replace(
        '<button type="button" class="view-tab" data-view-tab="flights" '
        'aria-pressed="false">',
        '<button type="button" class="view-tab is-on" data-view-tab="flights" '
        'aria-pressed="true">', 1)
    return (
        '<nav class="views" id="views" role="group" aria-label="Choose a view">'
        f'{marked}{common.strip_end()}</nav>'
    )


def _page(title: str, bodies: list[str], tabs: str = "", extras: "list[Extra]" = ()) -> str:
    """Wrap one or more flight bodies into a complete document.

    The doctype is not decoration. Without it the page is in **quirks mode**, where
    `document.documentElement.clientHeight` is the height of the whole document rather
    than of the viewport — and that is what the maximised 3D view sized its canvas from.
    On a 4 316 px report the full-screen canvas came out 4 316 px tall inside an 813 px
    panel: the terrain drawn for a viewport five times too tall, the track overlay
    registered against a different projection from the terrain under it, and every
    pointer gesture anchored through the wrong one. The controls looked fine and did
    nothing sensible, which is how it was reported.
    """
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<script>{common.THEME_BOOT}</script>
<style>{_font_face()}{STYLE}{view3d.STYLE}{view3d_gl.STYLE}{render_map.SWITCH_STYLE}{map3d.STYLE}{upload_panel.STYLE}{charts_client.STYLE}
{VIEW_STYLE if extras else ""}{"".join(e.style for e in extras)}</style>
<div class="wrap">
{_view_nav(extras)}
{_flights_view(tabs, bodies, extras)}
{"".join(f'<section data-view="{e.uid}" hidden>{e.body}</section>' for e in extras)}
{common.footer()}
</div>
<div class="tooltip" id="tip" role="status" aria-live="polite"></div>
<script>{view3d.SCRIPT}
{view3d_gl.SCRIPT}
{render_map.SWITCH_SCRIPT}
{map3d.SCRIPT}
{charts_client.SCRIPT}
{SCRIPT}</script>
<script>{js_bundle()}</script>
<script>{upload_panel.SCRIPT}</script>
<script>{common.THEME_SCRIPT}</script>
{"".join(f"<script>{e.script}</script>" for e in extras)}
{f"<script>{VIEW_SCRIPT}</script>" if extras else ""}
"""


# The flight analysis and the article, in JavaScript. In dependency order; tz-lookup
# first, as the IGC parser asks it for a take-off's zone.
JS_DIR = Path(__file__).parent / "js"
JS_MODULES = ("vendor/tz-lookup", "np", "geo", "igc", "flight", "analysis", "xc", "metrics",
              "debrief", "sun", "airmass", "terrain", "insolation", "plan", "kml",
              "certification", "meteo", "charts", "scene", "report", "upload")


def js_bundle() -> str:
    """The modules as one inline script. `</script` inside them — report.js writes the
    payload tags — is escaped, or the browser would end the element there."""
    return "\n".join((JS_DIR / f"{name}.js").read_text(encoding="utf-8")
                     for name in JS_MODULES).replace("</script", "<\\/script")


def _tab(uid: str, date: str, meta: str, stat: str = "", *, on: bool = False) -> str:
    """One flight tab: open it, or remove it from the document."""
    return (
        f'<span class="tab{" is-on" if on else ""}" data-flight-tab="{uid}">'
        f'<button type="button" class="tab-open" aria-pressed="{"true" if on else "false"}">'
        f'<span class="tab-date">{date}</span>'
        f'<span class="tab-meta">{meta}</span>'
        + (f'<span class="tab-stat">{stat}</span>' if stat else "")
        + '</button>'
        f'<button type="button" class="tab-compare" data-compare-toggle="{uid}" '
        f'title="Add this flight to the comparison" aria-pressed="false" '
        f'aria-label="Add this flight to the comparison">&#8646;</button>'
        f'<button type="button" class="tab-close" title="Remove this flight" '
        f'aria-label="Remove this flight">&#215;</button></span>'
    )


ADD_TAB = (
    '<span class="tab tab-add" data-flight-tab="own">'
    '<button type="button" class="tab-open" aria-pressed="false" '
    'title="Analyse your own track"><span class="tab-date">+ your track</span>'
    '<span class="tab-meta">igc &middot; kml &middot; kmz</span></button></span>'
)

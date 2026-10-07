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
from parainsights_map import map3d, render_map, view3d

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
.flight-map:fullscreen .renderer-host, .flight-map.is-maximised .renderer-host {
  flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.flight-map:fullscreen .view3d-panel, .flight-map.is-maximised .view3d-panel {
  flex: 1 1 auto; min-height: 0; width: 100%; margin: 0; }
.flight-map:fullscreen .view3d, .flight-map.is-maximised .view3d {
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

SCRIPT = (Path(__file__).parent / "page/report.js").read_text(encoding="utf-8")
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


VIEW_SCRIPT = (Path(__file__).parent / "page/view_tabs.js").read_text(encoding="utf-8")

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
<style>{_font_face()}{STYLE}{view3d.STYLE}{render_map.STYLE}{map3d.STYLE}{upload_panel.STYLE}{charts_client.STYLE}
{VIEW_STYLE if extras else ""}{"".join(e.style for e in extras)}</style>
<div class="wrap">
{_view_nav(extras)}
{_flights_view(tabs, bodies, extras)}
{"".join(f'<section data-view="{e.uid}" hidden>{e.body}</section>' for e in extras)}
{common.footer()}
</div>
<div class="tooltip" id="tip" role="status" aria-live="polite"></div>
<script>{view3d.SCRIPT}
{render_map.SCRIPT}
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

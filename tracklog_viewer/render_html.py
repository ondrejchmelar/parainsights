"""Self-contained HTML flight report.

No external requests: the display face is an inlined woff2, the charts are inline
SVG, the interaction is a few dozen lines of vanilla JavaScript. That keeps the
report readable from a USB stick in ten years, and it is the only form that works
under a strict content-security policy.

A second renderer using MapLibre + deck.gl over a terrain DEM is planned for the
interactive 3D view; it needs network tiles, so it cannot replace this one.
"""

import bisect
import base64
import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path

from . import (airmass, charts, debrief, geo, insolation, metrics, quicklook,
               terrain as terrain_module, view3d, view3d_gl)
from numpy import asarray as np_asarray, median as np_median
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
  font-size: 11px;
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
.verdict-rank {
  font-size: 11px;
  color: var(--ink-3);
  display: block;
  margin-top: 1px;
}
.verdict-rank.is-best { color: var(--climb); }
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
// "The air that day" for bundled flights built without --meteo.
//
// Uses quicklook's request, which has fetched this in the browser for uploaded tracks all
// along. Deferred until the page is idle so it never delays the first paint, and it fails
// quietly-but-visibly inside a published artifact, where every host is blocked.
(function () {
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
  function run() {
    if (!window.__fetchMeteo) return;
    document.querySelectorAll('.air-fetch').forEach(function (section) {
      var stats = section.querySelector('.air-stats');
      if (!stats || stats.dataset.done) return;
      stats.dataset.done = '1';
      stats.innerHTML = tile('weather', 'fetching…', '');
      var top = parseFloat(section.dataset.airTop);
      window.__fetchMeteo({
        dated: true,
        lat: [parseFloat(section.dataset.airLat)],
        lon: [parseFloat(section.dataset.airLon)],
        epoch: parseFloat(section.dataset.airEpoch)
      }).then(function (m) {
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
        // day: the tile read "model wind 0 km/h from N", which is a specific and wrong
        // forecast rather than an absent one. An omitted tile says "not known"; a zero
        // says "still". They are the opposite claim on a windy day.
        if (m.wind > 0 && isFinite(m.windFrom)) {
          html += tile('model wind', Math.round(m.wind) + ' km/h',
                       'from ' + cardinal(m.windFrom) + ' at 850 hPa');
        }
        stats.innerHTML = html;
      }).catch(function (error) {
        stats.innerHTML = tile('weather', 'unavailable', error.message || String(error));
      });
    });
  }
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
    var count = Object.keys(chosen).filter(function (k) { return chosen[k]; }).length;
    document.documentElement.classList.toggle('is-comparing', count >= 2);
    refresh();
  }, true);
})();

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

  views.forEach(function (view) {
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
  });

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
      root.querySelectorAll('[data-profile-view]').forEach(function (view) {
        view.hidden = view.dataset.profileView !== wanted;
      });
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
            # UTC minute per sample, which is what moves the sun with the hover. Carried
            # rather than interpolated from the flight's span: fixes are not evenly
            # spaced in time, and a KMZ from a scoring site is not evenly spaced at all.
            "min": [
                (lambda when: when.hour * 60 + when.minute)(
                    flight.time[i].astype("datetime64[s]").astype(object))
                for i in indices
            ],
        },
    }


def _sample_position(sample: list[int], fix: int) -> int:
    """The sampled position nearest a *fix* index.

    Charts are drawn over a few hundred sampled fixes and every cursor array is indexed by
    position in that sample, while a finding and a segment both point at a fix. Mapped
    here rather than in the page: the sample list is right here, and the alternative is
    shipping it a second time so JavaScript can repeat the same search.
    """
    position = bisect.bisect_left(sample, fix)
    if position >= len(sample):
        return len(sample) - 1
    if position and abs(sample[position - 1] - fix) <= abs(sample[position] - fix):
        return position - 1
    return position


def _row_cursor(sample: list[int] | None, fix: int) -> str:
    """`data-cursor` for a table row, so clicking it drives the linked cursor.

    Absent when the table was built without a sample, and the page treats a row with no
    attribute as hover-only rather than guessing a position.
    """
    if not sample:
        return ""
    return f' data-cursor="{_sample_position(sample, fix)}"'


def _stat(key: str, value: str, unit: str = "", sub: str = "") -> str:
    unit_html = f"<small>{unit}</small>" if unit else ""
    sub_html = f'<span class="sub">{sub}</span>' if sub else ""
    return (
        f'<div class="stat"><span class="key">{key}</span>'
        f'<span class="stat-value">{value}{unit_html}</span>{sub_html}</div>'
    )


def _source_title(source) -> str:
    """The three measurements behind a climb's label, for its tooltip.

    Every one of them is a number the reader can check against the row it sits in, which
    is the point: "ridge" on its own is an assertion, and "ridge, 32 m over a 18° slope,
    no complete circles" is the evidence for it. The wind offset joins only when there is
    a wind — a flight spent beating a ridge never circles, so it often has none, and
    `0° off the wind` would be a fabrication rather than a measurement.
    """
    parts = [
        f"{source.clearance:.0f} m above the ground",
        f"{source.slope:.0f}° slope" if source.slope is not None else "",
        f"{source.turn_rate:.1f} circles a minute" if source.turn_rate is not None else "",
        f"face {source.offset:.0f}° off the wind" if source.offset is not None else "",
    ]
    return ", ".join(part for part in parts if part)


def _clearance_note(clearance) -> str:
    """Ground clearance, with the launch and the landing left out of it.

    This read "lowest ground clearance of the flight was 2 m" on a flight whose lowest
    point actually flown was 441 m — the 2 m was the takeoff, 25 seconds in. Shares
    `metrics.airborne_window` with the debrief's low-point card, so the caption and the
    card cannot drift apart and quote different numbers for the same flight.
    """
    window = metrics.airborne_window(clearance)
    if window is None:
        return ""
    low, high = window
    # Coerced like `airborne_window` already does: callers reasonably hand this a list,
    # and `terrain.clearance()` returning an ndarray is a happy accident rather than a
    # contract this function should depend on.
    inside = np_asarray(clearance, dtype=float)[low:high]
    median = float(np_median(inside))
    if inside.min() < 0:
        # The DEM has put part of the track under the ground, so the *lowest* clearance is
        # not a number about this flight and is not quoted — the same refusal the
        # low-point card makes, for the same reason. Counting the offending fixes and
        # explaining the grid spacing was tried and read as a finding about the flight
        # rather than about the model. The median over hundreds of fixes survives a few
        # bad cells, so it stays.
        return (
            f"Median ground clearance in flight was {median:.0f}&nbsp;m &mdash; the launch "
            f"and the landing are left out, or both would win by being on the ground."
        )
    return (
        f"Lowest ground clearance in flight was {inside.min():.0f}&nbsp;m, median "
        f"{median:.0f}&nbsp;m &mdash; the launch and the landing are left out, or both "
        f"would win by being on the ground."
    )


def _trigger_note(analysis: Analysis, terrain) -> str:
    """Which faces the climbs started over, and whether they were the lit ones.

    Both halves of this are already in the page — the DEM, and the solar tables the 3D
    view re-lights from — so it costs nothing but the reading. It is a sentence beside the
    view rather than a debrief card because it carries no cost in metres or minutes, and
    because it is emphatically *not* a cause: a lit south-west face under a climb is a
    coincidence a pilot can weigh, not a reason the thermal existed.
    """
    if terrain is None:
        return ""
    found = insolation.triggers(analysis, terrain)
    if len(found) < 3:
        return ""

    # Counting aspects over the whole flight was the shallow version of this: "3 began
    # over ESE-facing slopes and 2 over E-facing" is a tally, and a tally of a quantity
    # that is *supposed* to change through the day tells the reader nothing. The sun moves,
    # so the question is whether the climbs moved with it — morning on the eastern faces,
    # afternoon on the western ones — which needs the flight split in time before the
    # aspects are averaged.
    lit = sum(1 for t in found if t.face.relative > 1.05)
    note = (
        f" Of {len(found)} climbs that started over sloping ground, {lit} began over "
        f"ground catching more sun than the slopes around it."
    )

    half = len(found) // 2
    if half >= 2:
        early, late = found[:half], found[-half:]
        first = _mean_aspect([t.face.aspect for t in early])
        second = _mean_aspect([t.face.aspect for t in late])
        swing = ((second - first + 540) % 360) - 180
        if abs(swing) >= 30:
            note += (
                f" The faces swung {'clockwise' if swing > 0 else 'anticlockwise'} through"
                f" the day, from {geo.cardinal(first)}-facing early on"
                f" ({early[0].at}&ndash;{early[-1].at}) to {geo.cardinal(second)}-facing"
                f" later ({late[0].at}&ndash;{late[-1].at})"
                f"{', which is the sun going round' if swing > 0 else ''}."
            )
        else:
            note += (
                f" They stayed on {geo.cardinal(first)}-facing ground from"
                f" {early[0].at} to {late[-1].at} rather than following the sun round."
            )

    breeze = insolation.windward(analysis, terrain)
    if breeze is not None and breeze.total:
        note += (
            f" {breeze.windward} of {breeze.total} faced within 60&#176; of the measured"
            f" wind, which is where ridge lift would be."
        )
    return note


def _mean_aspect(aspects: list[float]) -> float:
    """Mean compass bearing. Averaging 350 and 10 arithmetically gives 180, due south."""
    radians = [math.radians(a) for a in aspects]
    east = sum(math.sin(r) for r in radians)
    north = sum(math.cos(r) for r in radians)
    return math.degrees(math.atan2(east, north)) % 360.0


def _ceiling_tile(analysis: Analysis, meteo, peak_time: str, offset: float) -> tuple:
    """`ceiling used`, or the bare height when there is no model to compare against.

    3 774 / 3 954 = 95% is one number where the report used to print three: MAX ALTITUDE,
    YOU REACHED (the same figure, 2 000 px away, in a different stat row) and CLOUDBASE.
    """
    summary = analysis.summary
    use = metrics.ceiling_use(analysis, meteo)
    if use is None:
        return ("max altitude", f"{summary.max_altitude:,.0f}".replace(",", " "), " m",
                f"at {peak_time}"
                + (f" · {summary.max_altitude + offset:,.0f} m GPS".replace(",", " ")
                   if offset else ""))
    return ("ceiling used", f"{use.fraction:.0%}", "",
            f"{use.reached:,.0f} m of a modelled {use.ceiling:,.0f} m "
            f"{use.source.replace('_', ' ')}".replace(",", " "))


def _thermal_rows(analysis: Analysis, sample: list[int] | None = None,
                  sources: dict | None = None) -> str:
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
        # What appears to have been holding the climb up. A tow is a tow and never asks.
        # An unconfident classification prints nothing rather than the fallback label —
        # "thermal" because there was no terrain to check is not the same claim as
        # "thermal" because the ground under it was flat and out of the wind.
        source = sources.get(number) if sources and segment.phase is Phase.THERMAL else None
        source_html = (
            f'<span class="tag tag-{source.label}" title="{_source_title(source)}">'
            f"{source.label}</span>"
            if source is not None and source.confident
            else "<span class='dir'>—</span>"
        )
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
        # Reversals were measured and never shown, while the caption beside the table
        # named them as one of the two columns saying how tidily the climb was flown.
        # Zero is a real answer here — one direction throughout — so it prints as 0 and
        # only an unmeasurable climb gets the dash.
        reversals = f"{segment.reversals}" if segment.reversals is not None else "—"
        circle = f"{segment.circle_seconds:.0f}" if segment.circle_seconds else "—"
        radius = f"{segment.circle_radius:.0f}" if segment.circle_radius else "—"
        efficiency = f"{segment.efficiency:.0f}%" if segment.efficiency is not None else "—"
        rows.append(
            f'<tr data-segment="{segment.start}"{_row_cursor(sample, segment.start)}'
            f'{" class=is-tow" if segment.phase is Phase.TOW else ""}>'
            f"<td>{label} {tag}</td>"
            f"<td>{segment.start_time}</td>"
            f"<td>{_short_duration(segment.duration)}</td>"
            f"<td>{segment.altitude_change:+.0f}</td>"
            f"<td>{segment.finish_altitude:.0f}</td>"
            f'<td><span class="bar-cell">{segment.average_climb:+.2f}'
            f'<span class="bar" style="width:{width:.0f}px"></span></span></td>'
            f"<td>{efficiency}</td>"
            f"<td>{source_html}</td>"
            # Six columns of circling mechanics: a whole sub-story, and a specialist one.
            # Kept, because a finding cites radius as its receipt, but folded away.
            f'<td class="circling-detail">{turns}</td>'
            f'<td class="circling-detail">{per_turn}</td>'
            f'<td class="circling-detail">{direction}</td>'
            f'<td class="circling-detail">{reversals}</td>'
            f'<td class="circling-detail">{circle}</td>'
            f'<td class="circling-detail">{radius}</td>'
            f'<td class="spark-cell">'
            f'{charts.climb_trend(analysis.series, segment.start, segment.stop)}</td>'
            f"</tr>"
        )
    return "".join(rows)


def _glide_rows(analysis: Analysis, sample: list[int] | None = None) -> str:
    rows = []
    best = max((s.average_ld or 0) for s in analysis.glides) if analysis.glides else 1.0
    for index, segment in enumerate(analysis.glides, start=1):
        ld = f"{segment.average_ld:.1f}" if segment.average_ld else "—"
        rows.append(
            f'<tr data-segment="{segment.start}"{_row_cursor(sample, segment.start)}>'
            f"<td>{index}</td>"
            f"<td>{segment.start_time}</td>"
            f"<td>{_short_duration(segment.duration)}</td>"
            f"<td>{segment.distance / 1000:.1f}</td>"
            # `height m` dropped: it is km x glide, and the ratio is the point of the row.
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


def _sun_note(sun: dict | None) -> str:
    """Where the sun was over the flight, in one sentence under the 3D view.

    The slider answers "which slope was lit at four" by moving the light; this answers
    the questions that do not need a gesture — when the day started and ended, and where
    the sun stood at launch and at landing. Both read the same table, so they cannot say
    different things.
    """
    if not sun or not sun.get("track"):
        return ""

    def clock(minute: float | None) -> str:
        if minute is None:
            return "—"
        local = (round(minute) + sun["offset"]) % 1440
        return f"{local // 60:02d}:{local % 60:02d}"

    def at(minute: int) -> tuple[float, float]:
        track = sun["track"]
        index = min(int(round(minute / track["step"])), len(track["az"]) - 1)
        return track["az"][index], track["el"][index]

    def height(elevation: float) -> str:
        # A flight that lands at sunset reads "-0° up", which is both ugly and wrong by
        # the width of the sun's own disc. Say what it means instead.
        if elevation < -1:
            return "was already below the horizon"
        if elevation < 1:
            return "was sitting on the horizon"
        return f"stood {elevation:.0f}&#176; up"

    launch_az, launch_el = at(sun["launch"])
    landing_az, landing_el = at(sun["landing"])
    day = (
        f"The sun was up from {clock(sun['rise'])} to {clock(sun['set'])}"
        if sun.get("rise") is not None and sun.get("set") is not None
        else "The sun did not set that day"
    )
    return (
        f"{day}; at launch it {height(launch_el)} in the "
        f"{charts.escape(_cardinal(launch_az))}, and at landing it {height(landing_el)} in "
        f"the {charts.escape(_cardinal(landing_az))}. <strong>Hovering the charts below "
        f"re-lights the terrain</strong> for that moment of the flight, and the rose on "
        f"the view carries the sun and the wind as arrows that turn with it — which is "
        f"how to ask whether a face was still in the sun when you got there. It is the "
        f"real solar position, not a fixed north-west lamp."
    )


def _cardinal(azimuth: float) -> str:
    names = ["north", "north-north-east", "north-east", "east-north-east", "east",
             "east-south-east", "south-east", "south-south-east", "south",
             "south-south-west", "south-west", "west-south-west", "west",
             "west-north-west", "north-west", "north-north-west"]
    return names[round((azimuth % 360) / 22.5) % 16]


def _air_fetch_section(analysis: Analysis, uid: str) -> str:
    """"The air that day", fetched in the page when it was not baked in at build time.

    A report built without `--meteo` used to have no weather at all, which is why the
    published site lost the section the moment it was rebuilt anywhere the API was not
    reachable. But `quicklook.py` has fetched Open-Meteo in the browser for uploaded
    tracks all along, so the bundled flights can use the same request: the data is public,
    keyless and CORS-enabled, and the page already knows how to ask.

    No opt-in and no capability check, matching quicklook's own reasoning: inside a
    published artifact every host is blocked and the request simply fails, and saying
    "unavailable" with the reason is more use to a reader than an unticked box.
    """
    flight = analysis.flight
    middle = len(flight.lat) // 2
    when = flight.time[middle].astype("datetime64[s]").astype(int)
    return f"""
  <section class="air-fetch" data-air-lat="{float(flight.lat[middle]):.3f}"
           data-air-lon="{float(flight.lon[middle]):.3f}" data-air-epoch="{int(when)}"
           data-air-top="{analysis.summary.max_altitude:.0f}">
    <div class="section-head"><h2>The air that day</h2></div>
    <div class="stats air-stats"></div>
  </section>"""


def _cap_note(meteo) -> str:
    """What the profile does immediately above the thermal top, on *this* day.

    A dry adiabat cools at about 9.8 K/km, so a layer cooling much more slowly than that
    is what stops a thermal — the "cap" a pilot feels as a day that will not go higher.
    Measured over the first kilometre above the top; silent when the sounding does not
    reach far enough to say anything, which is the usual reason to have no opinion.
    """
    top = meteo.thermal_top
    if not top or not meteo.levels:
        return ""
    above = sorted(
        (level for level in meteo.levels if level.height >= top),
        key=lambda level: level.height,
    )
    if len(above) < 2 or above[-1].height - above[0].height < 400:
        return ""
    span = min(above[-1], above[1], key=lambda level: abs(level.height - top - 1000.0))
    rise = span.height - above[0].height
    if rise < 400:
        return ""
    lapse = (above[0].temperature - span.temperature) / rise * 1000.0
    if lapse < 6.0:
        return (
            f" Above that the profile cools {lapse:.1f}&nbsp;K/km against the dry "
            f"adiabat's 9.8 — a stable layer, which is what a day that caps out feels "
            f"like from the harness."
        )
    return (
        f" Above that it still cools {lapse:.1f}&nbsp;K/km, so nothing in the profile "
        f"was holding the day down."
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
        # The caption names the arithmetic, not a tile beside it. It read "from the surface
        # spread" — which is true, and points at a number the reader can only find by
        # reading the tile to its left and doing the subtraction themselves.
        ("cloudbase", f"{meteo.cloudbase:,.0f} m".replace(",", " "),
         f"{meteo.surface_temperature - meteo.surface_dew_point:.0f} K spread, lifted "
         f"until it closes"),
    ]
    if meteo.thermal_top:
        chips.append(
            ("thermal top", f"{meteo.thermal_top:,.0f} m".replace(",", " "),
             "dry adiabat meets the profile")
        )
    if meteo.boundary_layer_top:
        chips.append(
            # Not "model mixing depth", and not "how deep the model mixes the day's
            # thermals" either — both name the mechanism to a reader who wants the
            # consequence. What a pilot is looking at is a ceiling: the height the
            # surface heating reaches, above which the model has no thermals left.
            ("boundary layer", f"{meteo.boundary_layer_top:,.0f} m".replace(",", " "),
             "as high as the day's heating reaches")
        )
    # "you reached" is deliberately not a chip any more. It was the same number as the
    # MAX ALTITUDE stat tile, printed twice, 2 000 px apart, in two different stat rows.
    # The `ceiling used` tile above folds both into the one number that means something —
    # the fraction of the modelled column that was actually used — and the rest of the
    # sounding stays here, where it belongs.
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
        # The lapse rate above the thermal top, measured from this flight's own sounding.
        # It used to read "above ~2 080 m the profile only cools 4 K/km" on every report
        # ever produced — the reference flight's numbers, typed into the template, printed
        # as a fact about whatever day was being looked at.
        ceiling_note = (
            f"<p>The sounding puts the dry thermal top at "
            f"{meteo.thermal_top:,.0f}&nbsp;m".replace(",", " ")
            + f" and you topped out {verdict} it.{_cap_note(meteo)}</p>"
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


def _verdict_strip(result, analysis=None, archive=None, peers=None) -> str:
    """The flight in one line, above the map.

    A reader used to scroll ~1 200 px before meeting a single number. One compact line at
    the top answers the question the report exists to answer, and the evidence follows.

    Two comparisons can hang off the headline figures, and they are deliberately
    different in kind. The **archive** rank ("among your best of 12 flights") is about
    the pilot's history, is true regardless of what else is open, and so is baked in here.
    The **cross-flight** delta is not: comparing whatever happens to be in the document is
    a claim nobody asked for — three unrelated flights are not a set — so it is opt-in,
    computed in the page once two or more tabs have been added to the comparison. That is
    why the figures carry `data-key` and their values, and why nothing is written here.
    """
    if result is None or result.verdict is None:
        return ""
    verdict = result.verdict

    ranks = {}
    if analysis is not None and archive is not None and getattr(archive, "usable", False):
        thermals = analysis.thermals
        held = sum(s.duration for s in thermals)
        mean = sum(s.altitude_change for s in thermals) / held if held else None
        sentence = archive.rank_sentence(
            "mean_climb", round(mean, 2) if mean else None, "climb rate"
        )
        if sentence:
            ranks["mean_climb"] = (
                f'<span class="verdict-rank">{charts.escape(sentence)}</span>'
            )

    numbers = "".join(
        f'<div class="verdict-figure" data-key="{charts.escape(item.get("key", ""))}">'
        f'<span class="verdict-value">{charts.escape(item["value"])}</span>'
        f'<span class="verdict-label">{charts.escape(item["label"])}</span>'
        f'{ranks.get(item.get("key"), "")}'
        f'<span class="verdict-delta" hidden></span>'
        f"</div>"
        for item in verdict.headline
    )
    return f"""
  <div class="verdict">
    <p class="verdict-line">{charts.escape(verdict.sentence)}</p>
    <div class="verdict-figures">{numbers}</div>
  </div>"""


def _other_note(analysis: Analysis) -> str:
    """The unclassified slice, split into the three things it is actually made of.

    "40 min unclassified" names a gap in the analysis rather than anything the flight
    did. The three parts are the flight: sink flown straight is what a glide costs,
    turning without climbing is a thermal that did not work, and rising air outside any
    phase is mostly the run-in the climb rule deliberately trims off — which is why the
    slice is often *profitable* and must never be summed up as a loss.
    """
    slice_ = analysis.other
    if slice_ is None or not slice_.seconds:
        return ""
    net = slice_.net_altitude
    # Minutes, not "0 m 07 s". These three are always the small numbers on the page, and
    # `_duration`'s seconds field makes a seven-second sliver look like a measurement.
    def minutes(seconds: int) -> str:
        return f"{seconds / 60:.0f} min" if seconds >= 30 else "under a minute"

    return (
        f" That last part is {minutes(slice_.straight_sink)} of straight sink, "
        f"{minutes(slice_.scratching)} turning without climbing and "
        f"{minutes(slice_.rising)} of rising air no phase claimed — a net "
        f"{abs(net)} m {'gained' if net > 0 else 'lost'} over the whole of it."
    )


def _meteo_reason(analysis: Analysis) -> str:
    """Why this flight has no sounding, in terms of the flight rather than the build.

    Open-Meteo's operational archive keeps pressure levels for roughly `RECENT_DAYS`; the
    ERA5 reanalysis behind it answers older dates with surface fields and nulls on every
    level. So for an old flight there is nothing to fetch and never will be, which is a
    different sentence from "this build did not ask for it" — and it is the answer to the
    question the old wording provoked, that the weather is downloaded for every flight.
    """
    from . import meteo as meteo_module

    try:
        flown = analysis.flight.time[0].astype("datetime64[D]").astype(object)
    except (AttributeError, IndexError, ValueError):
        return ""
    age = (dt.date.today() - flown).days
    if age > meteo_module.RECENT_DAYS:
        return (
            f"this flight is {age // 30} months old and the weather archive keeps a "
            f"vertical profile for about {meteo_module.RECENT_DAYS} days, so the day's "
            f"sounding can no longer be fetched"
        )
    return "the day's sounding was not fetched when this report was built"


def _debrief_cards(result, uid: str, sample: list[int], context: str = "",
                   meteo_reason: str = "") -> str:
    """The findings, immediately under the instrument they point into.

    Each card is a measurement plus a link, never an imperative — the phrasing is
    `debrief.py`'s job and is tested there. What this function must not do is add a verb:
    "show me" moves the existing linked cursor, it does not offer an opinion.

    The cost dot carries the climb ramp already in the design system, so cost reads as
    colour before it reads as text.
    """
    if result is None or not result.findings:
        return ""

    cards = []
    for finding in result.findings:
        footer = []
        if finding.at:
            footer.append(f'<span class="finding-when">{charts.escape(finding.at)}</span>')
        link = ""
        if finding.cursor is not None and sample:
            position = _sample_position(sample, finding.cursor)
            link = (
                f'<button type="button" class="finding-link" '
                f'data-finding-cursor="{position}">show me &rarr;</button>'
            )
        cards.append(
            f'<article class="finding" data-finding="{charts.escape(finding.id)}">'
            f'<p class="finding-cost"><span class="finding-dot"></span>'
            f'cost {charts.escape(finding.cost.label)}</p>'
            f'<h3>{charts.escape(finding.title)}</h3>'
            f'<p class="finding-body">{charts.escape(finding.sentence)}</p>'
            f'<p class="finding-foot">{"".join(footer)}{link}</p>'
            f"</article>"
        )

    # Why the list is short, when it is short. "Degrade, do not blank" cuts both ways: a
    # reader told why a card is missing is better served than one left wondering.
    #
    # These name what is absent, not the switch that would have fetched it. `--meteo` and
    # `--terrain` are arguments to a command the reader of a published page never ran and
    # cannot run, and quoting them invited exactly the right question — "isn't the weather
    # always downloaded?" — with no answer on the page. `meteo_reason` answers it, because
    # the commonest cause is not a missing flag at all: past about two months there is no
    # sounding to fetch.
    reasons = {
        "terrain": "ground clearance needs an elevation model, which this report has none of",
        "meteo": meteo_reason or "the day's sounding is not in this report",
        "route": "the route findings need a scored route",
        "sampling": "this track is too coarse to count circles",
    }
    missing = [reasons[key] for key in result.suppressed if key in reasons]
    context = f'<p class="caption debrief-context">{context.strip()}</p>' if context.strip() else ""
    note = (
        f'<p class="caption debrief-note">Some findings are not computed here: '
        f'{charts.escape("; ".join(missing))}.</p>'
        if missing
        else ""
    )

    return f"""
  <section id="debrief-{uid}">
    <div class="section-head">
      <h2>Debrief</h2>
      <p>The measurements this flight supports, ranked by what they cost. Each one is a
         number and where to find it — never advice: the tool cannot see the sky, the
         gaggle, the airspace or the plan, and you were there.</p>
    </div>
    <div class="findings">{"".join(cards)}</div>
    {context}
    {note}
  </section>"""


def _flight_body(analysis: Analysis, *, meteo=None, route=None, terrain=None,
                 basemaps=None, fetch_tiles: bool = True,
                 kmz: bytes | None = None, uid: str = "f0",
                 hidden: bool = False, archive=None, peers=None,
                 flight_plan=None) -> str:
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

    # No recorder chip: which phone logged the track answers no question a pilot asks,
    # and the one thing the logger does decide — baro or GPS altitude — is already said
    # in "How to read this", where it comes with its consequences.
    identity = [
        ("pilot", summary.pilot or "—"),
        ("glider", summary.glider or "—"),
        ("site", summary.site or "—"),
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
        _stat("height gained", f"{summary.total_gain:,.0f}".replace(",", " "), " m",
              f"best single climb {summary.max_gain:.0f} m"),
        # MEAN CLIMB replaces the CLIMBS count, which is now its sub-line: the rate is
        # the number that describes the day, and the count only qualifies it.
        _stat("mean climb", f"{climb_rate:+.2f}", " m/s",
              f"{len(thermals)} climbs"
              + (f" · {total_turns:.0f} turns" if not coarse else "")),
        # CEILING USED folds MAX ALTITUDE, YOU REACHED and CLOUDBASE into the one number
        # that means something, and kills the duplicate that was printed twice 2 000 px
        # apart. Without --meteo there is no ceiling to compare against, so the tile falls
        # back to the bare height rather than disappearing and leaving five tiles.
        _stat(*_ceiling_tile(analysis, meteo, peak_time, offset)),
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
            # Swept turns, not revolutions: a two-stage launch contains a deliberate 180
            # and completes no circle, so the revolution count is 0 and says nothing
            # about how straight it was.
            f"({f'{tow.swept_turns:.1f} turns of heading' if tow.swept_turns is not None else 'nearly straight'}). "
            f"It is kept out of the thermal statistics and out of the "
            f"wind estimate, where a straight climb would have measured the glider's own "
            f"track rather than the air.</p>"
        )

    view3d_section = ""
    clearance = None
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
    </div>
    {view3d.panel(payload, uid, kmz_uri=kmz_uri,
                  kmz_name=f"{summary.date}-{(summary.site or 'flight').replace(' ', '-')}.kmz")}

  </section>"""

    wind_chart = charts.wind_profile(analysis, meteo=meteo, uid=uid)
    histogram = charts.climb_histogram(analysis)
    meteo_section = (
        _meteo_section(analysis, meteo, uid) if meteo is not None
        else _air_fetch_section(analysis, uid)
    )

    # The air-mass frame. Deliberately *not* a debrief card: a wind-corrected glide ratio
    # is context, not a cost, and "every finding carries a cost in metres or minutes or it
    # does not ship" is the rule that stops the list becoming trivia. So it lands next to
    # the glides table it describes, and refuses itself when the wind cannot carry it —
    # which on both real flights measured in the plan it could not, at 0.36 and 0.39.
    air_note = ""
    wind_field = airmass.field(analysis, weather=meteo)
    performance = airmass.glide_performance(analysis, wind_field)
    if performance is not None:
        curve = airmass.polar(analysis, wind_field)
        best = (
            f" Your best glides came at about {curve.best_glide[0]:.0f} km/h through the"
            f" air, where the wing returned {curve.best_glide[1]:.1f}:1."
            if curve and curve.best_glide
            else ""
        )
        # A refusal the reader can see the reason for. Silence here would be indistinct
        # from having no curve at all, and the two mean different things.
        if curve and not curve.monotone:
            best = (
                " No best-glide speed is given: over these glides the measured sink does"
                " not rise steadily with airspeed, which a wing's does, so the curve is"
                " describing the air they were flown in as much as the glider. One"
                " flight is not a polar."
            )
        # One clause per idea, in the order a reader needs them: what the wing did, what
        # the ground said, and only then how the two were reconciled. The old sentence
        # opened on "through the air the median is 8.7:1 against 8.0:1 over the ground, at
        # a median 36 km/h airspeed \u2014 corrected with the wind measured by 9 circled climbs
        # (confidence 0.51)", which put the correction, its evidence and its uncertainty
        # into one trailing clause and asked the reader to hold all three.
        air_note = (
            f" Taking the wind out of it, the wing's own median glide was"
            f" <strong>{performance.air_ld:.1f}:1</strong> at"
            f" {performance.median_airspeed:.0f} km/h through the air, against"
            f" {performance.ground_ld:.1f}:1 measured over the ground. The wind subtracted"
            f" is the one sounded from {len(wind_field.soundings)} circled climbs, which"
            f" this flight supports to about"
            f" {performance.confidence:.0%}.{best}"
        )

    # The debrief is computed here and baked in: findings are sentences, and there is no
    # network at view time. `clearance` is None without `--terrain`, `meteo` is None
    # without `--meteo`, and the findings that rest on them simply do not exist.
    debrief_result = debrief.build(
        analysis, route=route, weather=meteo, clearance=clearance,
        flight_plan=flight_plan,
    )
    verdict_strip = _verdict_strip(debrief_result, analysis, archive, peers)
    climb_sources = insolation.sources(analysis, terrain)
    debrief_section = _debrief_cards(
        debrief_result, uid, sample,
        context=f"{_clearance_note(clearance)} {_trigger_note(analysis, terrain)}",
        meteo_reason=_meteo_reason(analysis) if meteo is None else "",
    )

    compare_values = {
        "scored_km": round(route.distance / 1000.0, 2) if route else None,
        "mean_climb": round(climb_rate, 2) if thermals else None,
        "ceiling_used": (lambda u: u.fraction if u else None)(
            metrics.ceiling_use(analysis, meteo)
        ),
    }
    compare_attrs = "".join(
        f' data-compare-{key.replace("_", "-")}="{value}"'
        for key, value in compare_values.items()
        if value is not None
    )
    compare_name = charts.escape(
        " · ".join(part for part in (summary.date, summary.site) if part)
    )

    return f"""<article class="flight" data-flight-report="{uid}"{compare_attrs} data-compare-name="{compare_name}"{" hidden" if hidden else ""}>
  <header class="masthead">
    <div>
      <p class="eyebrow">tracklog viewer</p>
      <h1>{charts.escape(summary.site or "Flight")} <span>{charts.escape(summary.date)}</span></h1>
    </div>
    <div class="identity">{identity_html}</div>
  </header>
{verdict_strip}

{view3d_section}

  <section>
    <div class="section-head">
      <h2>Side view and top view</h2>
      <p>Hovering a moment in one chart marks the same moment in the other and in the 3D
         view above, so a point on the climb trace can be found on the ground. Click to
         keep it there while you look; click again, or press <kbd>Esc</kbd>, to let go. A
         row in the climbs or glides table below does the same for where that phase
         began.</p>
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
{debrief_section}

  <section>
    <div class="stats">{stats}</div>
  </section>

  <section>
    <div class="section-head">
      <h2>Where the time went</h2>
      <p>{_duration(budget.thermalling)} climbing across {len(thermals)} thermals,
        {_duration(budget.gliding)} gliding, and {_duration(budget.other)} that was
        neither.{_other_note(analysis)}</p>
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
        top: {_wind_shear_note(analysis)}{
        " The day's forecast profile would be drawn behind these as a check on them, but "
        + _meteo_reason(analysis) + "." if meteo is None else ""}</p>
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
      <p><strong>Eff</strong> is mean climb over the best 20&nbsp;s of the same climb — the
         closest single number to &ldquo;did you stay in the core&rdquo;. <strong>Rev</strong>
         counts reversals: the times the turn changed direction mid-climb, so a thermal
         circled one way throughout reads zero. With <strong>radius</strong> it says how
         tidily the climb was flown. <strong>Lift</strong> reads
         <em>ridge</em> only when three things agree — a steep face, the wind running into
         it, and you within {insolation.RIDGE_CLEARANCE:.0f}&nbsp;m of the slope — and
         <em>thermal</em> otherwise; a dash means there was nothing to check it
         against.{" This track is sampled every " + f"{summary.sample_interval:.0f}" + " s, which is too coarse to resolve a circle, so the turn columns are blank." if coarse else ""}</p>
    </div>
    <div class="toggle toggle-small" role="group" aria-label="Circling detail columns">
      <button type="button" class="toggle-button" data-detail="circling" aria-pressed="false">
        &#8853; circling detail</button>
    </div>
    <div class="panel" style="padding:14px 16px 4px">
      <div class="table-scroll">
        <table class="table-climbs">
          <thead><tr>
            <th>#</th><th>start</th><th>time</th><th>gain m</th><th>top m</th>
            <th>avg m/s</th><th>eff</th><th>lift</th>
            <th class="circling-detail">turns</th><th class="circling-detail">m/turn</th>
            <th class="circling-detail">dir</th><th class="circling-detail">rev</th>
            <th class="circling-detail">s/turn</th>
            <th class="circling-detail">radius m</th>
            <th>over time &rarr;</th>
          </tr></thead>
          <tbody>{_thermal_rows(analysis, sample, climb_sources)}</tbody>
        </table>
      </div>
    </div>
  </section>

  <section>
    <div class="section-head">
      <h2>Glides</h2>
      <p>Glide ratio in this table is over the ground, so it carries whatever the wind was
         doing as well as the wing.{air_note}</p>
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
          <thead><tr><th>#</th><th>start</th><th>time</th><th>km</th>
            <th>glide</th><th>km/h</th></tr></thead>
          <tbody>{_glide_rows(analysis, sample)}</tbody>
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
      <p><strong>A climb is the circling, not the run-in to it.</strong> A climb is time
        spent turning in lift and a glide is time spent going somewhere without it. The
        straight run into a thermal is neither, and lands in the unclassified time
        below.</p>
      <p><strong>Wind is inferred, not measured.</strong> While circling, the glider's own
        airspeed averages out and the track drifts with the air. Climbs flown fewer than two
        full turns, or in both directions, are excluded — they measure the pilot, not the
        wind. On a track sampled too coarsely to count turns at all, a climb of two minutes
        or more is used instead: the drift is still the air's, and there is nothing better.</p>
      <p><strong>"Ridge" is three measurements agreeing, and "thermal" is everything
        else.</strong> A climb is called ridge when the ground under it was steeper than
        {insolation.RIDGE_SLOPE:.0f}°, the glider stayed within
        {insolation.RIDGE_CLEARANCE:.0f} m of it, and the track beat along the slope
        rather than closing circles — hover a label to see all three for that climb.
        Convergence is deliberately not a label: its honest signature is a climb drifting
        differently from the air around it, and one tracklog cannot tell that from a ridge
        climb holding station or a badly sounded wind. Without terrain there is nothing to
        check and the column shows a dash rather than guessing.</p>
      <p>The {len(analysis.glides)} glides and {len(thermals)} climbs account for
        {(1 - budget.fractions()["other"]) * 100:.0f}% of airtime. The rest is transitions too
        short or too ambiguous to call, which is honest rather than tidy.</p>
    </div>
  </section>

  <footer>
    <span>{summary.fixes:,} fixes at {summary.duration / summary.fixes:.1f} s · timezone from
      {charts.escape(summary.timezone or "UTC")}</span>
    <span>tracklog viewer · your track is analysed in this page and never uploaded</span>
  </footer>
  <script type="application/json" class="cursor-data">{json.dumps(_cursor_data(analysis))}</script>
</article>
"""


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
.view-tab:focus-visible { outline: 2px solid var(--climb); outline-offset: -2px; }
"""


def _flights_view(tabs: str, bodies: list[str], extras: "list[Extra]") -> str:
    """The flight report, wrapped in a view section only when there is a view to switch
    to. Every report before extras existed had no wrapper, and adding one unconditionally
    would change the DOM of all of them to no purpose."""
    inner = f'{tabs}\n{"".join(bodies)}\n{quicklook.panel()}'
    if not extras:
        return inner
    return f'<section data-view="flights">\n{inner}\n</section>'


def _view_nav(extras: "list[Extra]") -> str:
    """The switch across the top. Absent entirely when there is nothing to switch to."""
    if not extras:
        return ""
    buttons = [
        '<button type="button" class="view-tab is-on" data-view-tab="flights" '
        'aria-pressed="true">Flights</button>'
    ]
    buttons += [
        f'<button type="button" class="view-tab" data-view-tab="{e.uid}" '
        f'aria-pressed="false">{charts.escape(e.label)}</button>'
        for e in extras
    ]
    return (
        '<nav class="views" id="views" role="group" aria-label="Choose a view">'
        f'{"".join(buttons)}</nav>'
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
<title>{charts.escape(title)}</title>
<style>{_font_face()}{STYLE}{view3d.STYLE}{view3d_gl.STYLE}{quicklook.STYLE}
{VIEW_STYLE if extras else ""}{"".join(e.style for e in extras)}</style>
<div class="wrap">
{_view_nav(extras)}
{_flights_view(tabs, bodies, extras)}
{"".join(f'<section data-view="{e.uid}" hidden>{e.body}</section>' for e in extras)}
</div>
<div class="tooltip" id="tip" role="status" aria-live="polite"></div>
<script>{view3d.SCRIPT}
{view3d_gl.SCRIPT}
{SCRIPT}</script>
<script>{quicklook.SCRIPT}</script>
{"".join(f"<script>{e.script}</script>" for e in extras)}
{f"<script>{VIEW_SCRIPT}</script>" if extras else ""}
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


def render(analysis: Analysis, *, meteo=None, route=None, terrain=None,
           basemaps=None, fetch_tiles: bool = True, kmz: bytes | None = None,
           archive=None, flight_plan=None, extras: "list[Extra]" = ()) -> str:
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
    )
    return _page(
        title,
        [
            _flight_body(
                analysis, meteo=meteo, route=route, terrain=terrain,
                basemaps=basemaps, fetch_tiles=fetch_tiles, kmz=kmz, uid="f0",
                archive=archive, flight_plan=flight_plan,
            )
        ],
        tabs,
        extras,
    )


def render_multi(reports: list[dict], *, archive=None, extras: "list[Extra]" = ()) -> str:
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
                archive=archive,
                flight_plan=report.get("plan"),
                # Every other flight in this document, so each one can say where it
                # stands among them. The document held three flights and never once put
                # them side by side.
                peers=[r["analysis"] for j, r in enumerate(reports) if j != index],
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
    )
    first = reports[0]["analysis"].summary
    title = f"tracklog viewer · {len(reports)} flights from {first.pilot or 'the log'}"
    return _page(title, bodies, tabs, extras)


def write(analysis: Analysis, path, *, meteo=None, route=None, terrain=None,
          basemaps=None, fetch_tiles: bool = True, kmz: bytes | None = None,
          archive=None, flight_plan=None, extras: "list[Extra]" = ()) -> Path:
    path = Path(path)
    path.write_text(
        render(analysis, meteo=meteo, route=route, terrain=terrain, basemaps=basemaps,
               fetch_tiles=fetch_tiles,
               kmz=kmz, archive=archive, flight_plan=flight_plan, extras=extras),
        encoding="utf-8",
    )
    return path


def write_multi(reports: list[dict], path, *, archive=None, extras: "list[Extra]" = ()) -> Path:
    path = Path(path)
    path.write_text(
        render_multi(reports, archive=archive, extras=extras), encoding="utf-8"
    )
    return path

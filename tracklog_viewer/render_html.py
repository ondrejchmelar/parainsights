"""The report page: everything around the articles.

The articles themselves — one per flight — are written by the JavaScript in `js/`
(`js/upload.js`'s `compose`), at build time for the flights the page ships with
(`js_build.py`) and in the page for a track the reader drops on it. This module is the
document they sit in: the stylesheet, the page script that draws the charts and links
the cursor (`page/report.js`), the view and flight strips, the upload panel, and the
JavaScript bundle.
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


# The report's own sheet, after `common.TOKENS` and `common.STYLE` (the strip, the
# controls, the ⓘ). Rewritten for the redesign (October 2026); the reasoning behind each
# rule that survived is in the comments beside it and in git before that.
STYLE = common.TOKENS + common.STYLE + """
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); }
.wrap { max-width: 1180px; margin: 0 auto; padding: 0 28px 80px; }
.num, td.num, .mono { font-variant-numeric: tabular-nums; }
h1, h2, h3 { margin: 0; font-weight: 650; letter-spacing: -0.01em; }

/* Masthead and key numbers ------------------------------------------------- */
.masthead { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between;
  gap: 8px 20px; margin: 28px 0 18px; }
.masthead h1 { font-size: clamp(30px, 4.4vw, 40px); line-height: 1.1; text-wrap: balance; }
.masthead h1 span { color: var(--ink-2); font-weight: 400; }
.who { margin: 0; font-size: 17px; color: var(--ink-2); display: inline-flex; align-items: center; flex-wrap: wrap; }
.who b { color: var(--ink); font-weight: 600; margin-right: 0.3em; }
/* The certification class: outlined, a fact about the wing and not a warning about it. */
.cert { display: inline-block; margin-left: 8px; padding: 1px 10px; border-radius: 999px;
  border: 1.5px solid var(--edge); font-size: 15px; color: var(--ink-2); white-space: nowrap; }
.figs { display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); margin: 0 0 26px; }
.fig { padding: 16px 14px 14px 0; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.fig .v { font-size: 30px; font-weight: 650; line-height: 1.15; font-variant-numeric: tabular-nums; white-space: nowrap; }
.fig .v small { font-size: 17px; font-weight: 500; margin-left: 4px; color: var(--ink-2); }
.fig .k { font-size: 15.5px; color: var(--ink-2); display: inline-flex; align-items: center; }
.verdict-delta { font-size: 15px; color: var(--ink-2); display: block; margin-top: 2px; }
.verdict-delta.is-best { color: var(--accent); font-weight: 600; }
.verdict-delta[hidden] { display: none; }
.figs.air .v { font-size: 26px; }

/* Sections ------------------------------------------------------------------ */
section { margin-top: 46px; }
section > h2 { font-size: 24px; display: flex; align-items: center; margin-bottom: 14px; }
.chart h3 { font-size: 19px; display: flex; align-items: center; margin: 0 0 4px; }
.chart .sub { margin: 0 0 10px; color: var(--ink-2); font-size: 16px; }
.chart { margin-bottom: 24px; }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 26px; }
.panel { background: var(--panel); border: 1px solid var(--rule); border-radius: 14px; padding: 14px 16px 8px; }
.panel.budget { padding: 18px 20px 10px; }
p.note, p.caption { margin: 12px 0 0; color: var(--ink-2); font-size: 16px; display: block; }
.chart-missing { color: var(--ink-2); font-size: 15px; padding: 16px; margin: 0; }
.more { margin-top: 14px; }

/* The map and the side view, one full-width block (`.flight-map`). The merged map makes
   the whole block full screen, so the side view goes with it. */
.map-section { margin-top: 0; }
.flight-map { --page: calc(100vw - var(--scrollbar, 0px)); width: var(--page); margin-left: calc(50% - var(--page) / 2); }
.flight-map .side-view { border-radius: 0; border: 0; border-bottom: 1px solid var(--rule); padding: 0; background: var(--panel); }
.flight-map .side-view .chart-host { max-width: 1100px; margin: 0 auto; }
.side-bar { max-width: 1100px; margin: 0 auto; padding: 12px 20px 4px; display: flex; flex-wrap: wrap;
  align-items: center; justify-content: space-between; gap: 8px 16px; }
.side-bar .legend-row { margin: 0; }
.flight-map:fullscreen, .flight-map.is-maximised { display: flex; flex-direction: column;
  background: var(--panel); width: 100%; height: 100%; margin: 0; }
.flight-map.is-maximised { position: fixed; inset: 0; z-index: 60; width: auto; height: auto; }
.flight-map::backdrop { background: var(--panel); }
.flight-map:fullscreen .renderer-host, .flight-map.is-maximised .renderer-host {
  flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.flight-map:fullscreen .view3d-panel, .flight-map.is-maximised .view3d-panel {
  flex: 1 1 auto; min-height: 0; width: 100%; margin: 0; }
.flight-map:fullscreen .view3d, .flight-map.is-maximised .view3d { height: 100%; aspect-ratio: auto; }
.flight-map:fullscreen .side-view, .flight-map.is-maximised .side-view { flex: 0 0 auto; width: 100%; margin: 0; }
.flight-map:fullscreen .side-bar, .flight-map.is-maximised .side-bar { display: none; }
.flight-map:fullscreen .side-view .chart-host, .flight-map.is-maximised .side-view .chart-host {
  height: 24vh; aspect-ratio: auto !important; max-width: none; }
.flight-map:fullscreen .side-view .chart, .flight-map.is-maximised .side-view .chart { height: 100%; }
.hero { overflow: hidden; }

/* Charts: the page's type, at least 15 px, sentence case. ------------------- */
.chart { display: block; width: 100%; height: auto; }
svg.chart { overflow: visible; }
.chart .axis-label, .chart .axis-title, .chart .reference-label, .chart .mark-label,
.chart .endpoint-label, .chart-wind .wind-number, .chart-wind .wind-time, .point-label, .budget-label {
  font-family: "Noto Sans", ui-sans-serif, system-ui, sans-serif; font-size: 15px; fill: var(--ink-2);
  text-transform: none; letter-spacing: 0; font-variant-numeric: tabular-nums; }
.chart .axis-y { text-anchor: end; }
.chart .axis-x { text-anchor: middle; }
.chart .axis-title { text-anchor: middle; }
.chart .grid line { stroke: var(--rule); stroke-width: 1; }
.chart .axes line, .chart .axis { stroke: var(--edge); stroke-width: 1; }
.chart .track polyline { fill: none; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.chart-profile .drops line { stroke: var(--shadow-ink); stroke-width: 0.7; opacity: 0.45; }
.chart-profile .endpoint { fill: var(--panel); stroke: var(--ink); stroke-width: 2; }
.chart-profile .endpoint-label { text-anchor: middle; }
.chart .mark circle { stroke-width: 2; }
/* The numbers in the climbs' circles: smaller than the rest of the chart's type, so two
   digits fit inside, and centred on the font's middle rather than nudged by hand. The
   side view's and the wind chart's circles come out the same size on screen: about
   7.5 px across the radius, 11 px numbers (the wind chart is drawn at 620 wide and
   shown at about 0.83 of that on a desktop, 0.58 on a phone — see the phone rules). */
.chart .mark-label { fill: var(--ink); text-anchor: middle; dominant-baseline: central; font-size: 11px; }
.chart .mark.active circle { fill: var(--climb); stroke: var(--panel); }
.chart .reference { stroke: var(--ink-2); stroke-width: 1; stroke-dasharray: 6 4; }
.chart .reference-label { text-anchor: end; }
.chart .reference-label.band-label { text-anchor: start; }
.chart-plan .plan-thermal { fill-opacity: 0.72; stroke: var(--panel); stroke-width: 1.2; }
.chart-plan .plan-by-rate { display: none; }
.chart-plan.circles-by-rate .plan-by-gain { display: none; }
.chart-plan.circles-by-rate .plan-by-rate { display: inline; }
.chart-plan .mark.active .plan-thermal { fill-opacity: 1; stroke: var(--ink); stroke-width: 2; }
.chart-plan .endpoint { fill: var(--panel); stroke: var(--ink); stroke-width: 2; }
.chart-plan .compass line, .chart-plan .compass path { stroke: var(--ink-2); stroke-width: 1.2; fill: none; }
.chart-plan .scalebar line { stroke: var(--ink-2); stroke-width: 1.2; }
.chart-plan .xc-route line { stroke: var(--ink-2); stroke-width: 1; stroke-dasharray: 4 3; }
.chart-plan .xc-route rect { fill: none; stroke: var(--ink-2); stroke-width: 1.4; }
/* Phase shading on the profile: chart-agnostic selectors (scoped to a class that no longer
   existed, the bands once filled black). */
.chart .band { opacity: 0.12; }
.chart .band-thermal { fill: var(--climb); }
.chart .band-glide { fill: var(--sink); }
.chart .band-tow { fill: var(--tow); }
.chart .band-dive { fill: var(--sink-3); }
.chart .band.active { opacity: 0.32; }
/* Hidden via CSS: the HTML `hidden` attribute does nothing inside SVG. */
.chart .cursor { visibility: hidden; }
.chart .cursor.on { visibility: visible; }
.chart .cursor-dot { fill: var(--panel); stroke: var(--ink); stroke-width: 2; }
/* A pinned marker is heavier than a hovered one. */
.is-pinned .chart .cursor-dot { stroke-width: 3.5; }
.is-pinned .chart .crosshair { stroke-dasharray: none; }
.chart .hit { fill: transparent; cursor: crosshair; }
.chart .crosshair { stroke: var(--ink-2); stroke-width: 1; stroke-dasharray: 3 3; }
.chart .replay-dim { fill: var(--panel); opacity: 0.7; pointer-events: none; }
.chart-wind .wind-dot { fill: var(--panel); stroke: var(--sink); stroke-width: 2; }
.chart-wind .wind-arrow { stroke: var(--sink); stroke-width: 1.6; }
.chart-wind .wind-number { fill: var(--ink); text-anchor: middle; dominant-baseline: central; font-size: 13px; }
.chart-wind .wind-point.active .wind-dot { fill: var(--climb); stroke: var(--panel); }
.chart-wind .model polyline { fill: none; stroke: var(--neutral); stroke-width: 2; stroke-dasharray: 5 3; }
.chart-wind .model .model-dot { fill: var(--neutral); }
.chart-sounding .environment { fill: none; stroke: var(--climb); stroke-width: 2.2; }
.chart-sounding .dewpoint { fill: none; stroke: var(--sink); stroke-width: 2.2; }
.chart-sounding .adiabat { fill: none; stroke: var(--neutral); stroke-width: 1.6; stroke-dasharray: 4 3; }
.chart-sounding .flight-band { fill: var(--climb); opacity: 0.1; }
.point-label { text-anchor: middle; }
.budget-label { text-anchor: middle; fill: var(--ink); }
.panel-divide { height: 1px; background: var(--rule); margin: 2px 6px 4px; }
.swatch { width: 12px; height: 12px; border-radius: 3px; flex: none; display: inline-block; }
.info-pop .sw { width: 12px; height: 10px; border-radius: 3px; display: inline-block; margin: 0 4px 0 2px; vertical-align: 0; }
.legend .legend-title { color: var(--ink-2); }

/* Flight tabs ------------------------------------------------------------------ */
.tabs { display: flex; flex-wrap: wrap; gap: 10px; margin: 22px 0 0; }
/* A tab is a wrapper, not a button, because it holds three: open, compare and remove. A
   button inside a button is invalid and browsers drop the inner one. */
.tab { flex: 0 1 auto; min-width: 230px; position: relative; display: flex; align-items: center;
  background: var(--panel); border: 1px solid var(--edge); border-radius: 14px; min-height: 64px; }
.tab-open { flex: 1 1 auto; min-width: 0; text-align: left; border: 0; background: none;
  padding: 10px 6px 10px 16px; cursor: pointer; color: var(--ink); font: inherit;
  display: flex; flex-direction: column; gap: 1px; border-radius: 14px; }
.tab .tab-date { font-size: 17px; font-weight: 650; color: var(--ink); }
.tab .tab-meta, .tab .tab-stat { font-size: 15px; color: var(--ink-2); }
.tab:hover { background: var(--panel-2); }
/* The open flight: the one accent ring on the page, on purpose. */
.tab.is-on { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
.tab-compare, .tab-close { position: relative; width: 44px; height: 44px; flex: none; padding: 0; border: 0;
  border-radius: 10px; background: none; color: var(--ink-2); cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; }
.tab-close { margin-right: 6px; }
.tab-compare:hover, .tab-close:hover { background: var(--panel-2); color: var(--ink); }
.tab-compare.is-on { background: var(--ink); color: var(--paper); }
.tab-compare svg, .tab-close svg { display: block; }
/* On touch, only the open tab's buttons are live: the first tap opens a flight, and only
   then can a second remove it or add it to the comparison. */
@media (hover: none) { .tab:not(.is-on) .tab-close, .tab:not(.is-on) .tab-compare { pointer-events: none; opacity: 0.45; } }
.tab-add { min-width: 0; flex: none; }
.tab-add .tab-open { flex-direction: row; align-items: center; gap: 8px; padding-right: 18px; font-weight: 600; }
.tab-add .tab-date { font-size: 16px; font-weight: 600; }
.tab-add .tab-meta { display: none; }
.ramp { display: flex; gap: 2px; align-items: center; }
.ramp span { width: 22px; height: 10px; border-radius: 2px; }

/* The ⓘ bubbles' colours, the page's inverted: in the panel's own colour it vanished into
   the dark chart under it, where its shadow does not show. */
.tooltip { position: absolute; pointer-events: none; z-index: 70; background: var(--pop-bg); color: var(--pop-ink);
  border: 1px solid var(--pop-bg); border-radius: 10px; padding: 8px 12px; font-size: 15px; line-height: 1.45;
  box-shadow: 0 6px 20px rgb(0 0 0 / 0.2); white-space: nowrap; opacity: 0; transition: opacity 0.1s; }
.tooltip.on { opacity: 1; }
.tooltip .t-time { font-variant-numeric: tabular-nums; font-weight: 600; }
.tooltip .t-row { color: color-mix(in srgb, var(--pop-ink) 78%, var(--pop-bg)); font-variant-numeric: tabular-nums; }

/* Tables -------------------------------------------------------------------------- */
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 16.5px; }
th { text-align: right; font-weight: 600; font-size: 15px; color: var(--ink-2); padding: 10px 12px;
  border-bottom: 1px solid var(--rule); white-space: nowrap; }
th:first-child, td:first-child { text-align: left; padding-left: 2px; }
td { padding: 10px 12px; border-bottom: 1px solid var(--rule); text-align: right;
  font-variant-numeric: tabular-nums; white-space: nowrap; }
tbody tr:last-child td { border-bottom: 0; }
td:first-child { color: var(--ink-2); }
tbody tr { cursor: default; }
/* A row that can drive the cursor says so, and one that cannot must not pretend to. */
tbody tr.is-linked { cursor: pointer; }
tbody tr:hover, tbody tr:focus-visible { background: var(--panel-2); outline: none; }
tr.is-tow td:first-child { color: var(--tow); }
th .info-wrap { vertical-align: 0; }
th.spark-head { text-align: left; }
.tag { display: inline-block; font-size: 15px; }
.tag-tow { color: var(--tow); font-weight: 600; }
/* What held a climb up. Ridge is the one that had to be argued for, so it gets a colour. */
.tag-ridge { color: var(--climb-3); font-weight: 600; }
.tag-thermal { color: var(--ink-2); }
.tag-glide { color: var(--sink); }
.bar-cell { display: flex; align-items: center; gap: 8px; justify-content: flex-end; }
.bar-cell .bar { height: 8px; border-radius: 4px; background: var(--climb); flex: none; }
td.spark-cell { padding: 3px 4px 2px 12px; text-align: left; }
svg.spark { display: block; }
svg.spark .spark-zero { stroke: var(--edge); stroke-width: 1; }
svg.ldbar { display: block; flex: none; }
.dir { color: var(--ink-2); }
/* The circling columns fold away: five columns of circling mechanics, a whole sub-story
   and a specialist one. The longest glides show; the rest unfold. */
.circling-detail { display: none; }
.table-climbs.show-circling .circling-detail { display: table-cell; }
.table-glides tr.is-extra { display: none; }
.table-glides.show-all tr.is-extra { display: table-row; }
code { font-family: ui-monospace, "DejaVu Sans Mono", monospace; font-size: 0.92em;
  background: var(--panel-2); padding: 1px 4px; border-radius: 4px; }

/* Debrief: the cards are the point of the page, ranked by what each cost. ---------- */
.findings { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.finding, .context .card { padding: 18px 20px; border: 1px solid var(--rule); border-radius: 14px;
  background: var(--panel); display: flex; flex-direction: column; gap: 8px; }
.finding h3 { font-size: 21px; line-height: 1.3; }
.finding-body { margin: 0; font-size: 17px; line-height: 1.5; }
.finding-cost { margin: 0; }
.finding-foot { margin: auto 0 0; display: flex; align-items: center; justify-content: space-between;
  gap: 10px; font-size: 15px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.finding-link { min-height: 44px; }
.context { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-top: 16px; }
.context .card { gap: 2px; }
.context b { font-size: 22px; font-weight: 650; }
.context span { color: var(--ink-2); font-size: 16px; }

/* Wanted by the page-fetched air figures while they load. */
.stat .key { color: var(--ink-2); }

@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
@media (max-width: 640px) {
  .wrap { padding: 0 14px 40px; }
  .masthead h1 { font-size: 30px; }
  .figs.keys { grid-template-columns: repeat(2, 1fr); }
  .fig { padding: 12px 8px 12px 0; }
  .fig .v { font-size: 26px; }
  .tabs { flex-wrap: nowrap; overflow-x: auto; margin-right: -14px; padding-right: 14px; }
  .tab { min-width: 220px; flex: none; }
  .tab-add { min-width: 0; }
  .side-bar { padding: 10px 14px 4px; }
  .panel { padding: 10px 10px 6px; }
  table { font-size: 15.5px; }
  th, td { padding: 10px 7px; }
  /* Charts drawn at half width are scaled to about two thirds on a phone; their type is
     set larger in their own units so it lands near 13 px. */
  .two .chart .axis-label, .two .chart .axis-title,
  .two .chart-wind .wind-time, .two .chart .reference-label { font-size: 19px; }
  .two .chart-wind .wind-dot { r: 13px; }
  .two .chart-wind .wind-number { font-size: 19px; }
  /* The side view is drawn at the phone's own size (`narrowOf` in page/charts.js), so its
     type is the desktop's 15 px; the host drops the desktop's 1080:420 box for it. */
  .flight-map .side-view .chart-host { aspect-ratio: auto !important; }
  /* Start, top, core and lift fold away; the sparkline stays — it is the most useful
     column on a phone. */
  .table-climbs tr > :nth-child(2), .table-climbs tr > :nth-child(5),
  .table-climbs tr > :nth-child(7), .table-climbs tr > :nth-child(8) { display: none; }
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
/* The view switch is the site strip (`common.STYLE`): its buttons look like its links. */
.site-nav > .view-tab:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
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
        return ('<nav class="site-nav views page-tools" aria-label="Theme">'
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
        '<nav class="site-nav views" id="views" role="group" aria-label="Choose a view">'
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
<style>{STYLE}{view3d.STYLE}{render_map.STYLE}{map3d.STYLE}{upload_panel.STYLE}{charts_client.STYLE}
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
    """One flight tab: open it, add it to the comparison, or remove it from the document."""
    return (
        f'<span class="tab{" is-on" if on else ""}" data-flight-tab="{uid}">'
        f'<button type="button" class="tab-open" aria-pressed="{"true" if on else "false"}">'
        f'<span class="tab-date">{date}</span>'
        f'<span class="tab-meta">{meta}</span>'
        + (f'<span class="tab-stat">{stat}</span>' if stat else "")
        + '</button>'
        f'<button type="button" class="tab-compare" data-compare-toggle="{uid}" '
        f'title="Add this flight to the comparison" aria-pressed="false" '
        f'aria-label="Add this flight to the comparison">{common.icon(common.ICONS["swap"])}</button>'
        f'<button type="button" class="tab-close" title="Remove this flight" '
        f'aria-label="Remove this flight">{common.icon(common.ICONS["close"])}</button></span>'
    )


ADD_TAB = (
    '<span class="tab tab-add" data-flight-tab="own">'
    '<button type="button" class="tab-open" aria-pressed="false" '
    f'title="Analyse your own track">{common.icon(common.ICONS["plus"])}<span class="tab-date">Your track</span>'
    '<span class="tab-meta">igc &middot; kml &middot; kmz</span></button></span>'
)

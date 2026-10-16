"""The meteo view: a day, ranked by site, with the sounding behind each verdict.

Three things a pilot asks before driving, in the order they are asked:

1. **Is it worth going anywhere today?** — the day strip, and the sounding.
2. **Where?** — the site list, ordered by how the forecast wind sits on each takeoff.
3. **When?** — the meteogram, hour by hour.

Everything here is drawn in the browser from numbers fetched at view time, which is the
one place in this repository that is deliberately not self-contained: a forecast built at
03:00 and published is wrong by lunchtime, and there is no build step between the reader
and the site. See `docs/meteo.md` for what that costs.

The charts are canvas rather than SVG: they are redrawn whenever the reader moves the
hour slider, and rebuilding a few hundred SVG nodes on every step of a range input is
what makes a page feel heavy.
"""

from __future__ import annotations

import json

import parainsights_common as common

from . import flymet as flymet_data
from . import sites as site_data
from .sources import distance_m
from pathlib import Path

# Past this the nearest station is not the same weather and saying so would be worse than
# saying nothing. flymet covers Czechia and the edge of its neighbours, so every takeoff
# north of the Alps has a station well inside this, and the ones in Italy and Slovenia
# have none at all — they get no meteogram rather than a Czech airfield's.
FLYMET_RANGE_KM = 60

# Open-Meteo, keyless and CORS-open. The pressure levels are `tracklog_viewer/js/meteo.js`'s,
# so a forecast profile and a flown profile are the same shape and can be read against
# each other without a conversion nobody would remember.
LEVELS = (1000, 975, 950, 925, 900, 850, 800, 700, 600, 500)
ENDPOINT = "https://api.open-meteo.com/v1/forecast"

# The synoptic situation behind the day: ČHMÚ's "Synoptická situace" — the pressure
# and the fronts over Central Europe, stepped through the coming days — the chart a pilot
# reads the fronts and the gradient off. Linked, not drawn: there is no forecast here to
# draw one from. (The pilot's pick, October 2026, over DWD's and the Met Office's.)
SYNOPTIC = "https://www.chmi.cz/predpoved-pocasi/synopticka-situace"
# Concentric isobars, four uneven rings bunched a little to one side, as a chart draws
# them round a low. On a 24 grid and drawn at 32 px, so they fill the 44 px button, with
# the line thinned to the weight the site's 20 px icons have (1.35 on 24 is 1.8 px).
# The pilot's pick, October 2026, out of a dozen tried — fronts closed up at this size.
SYNOPTIC_ICON = (
    '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M22.66 10.22C23.05 11.93 22.33 14.34 21.29 15.95C20.25 17.56 18.27 19.05 16.42 19.86C14.57 20.68 12.14 21.07 10.20 20.85C8.26 20.63 6.24 19.69 4.77 18.57C3.31 17.44 1.90 15.81 1.41 14.09C0.92 12.37 0.89 9.88 1.84 8.26C2.79 6.65 5.20 5.12 7.11 4.43C9.02 3.73 11.32 3.87 13.30 4.08C15.28 4.29 17.43 4.66 18.99 5.68C20.55 6.71 22.28 8.51 22.66 10.22z"/>'
    '<path d="M19.92 10.41C20.19 11.60 19.69 13.28 18.96 14.40C18.23 15.52 16.84 16.56 15.54 17.14C14.24 17.71 12.53 17.98 11.17 17.83C9.81 17.68 8.39 17.03 7.36 16.24C6.34 15.46 5.35 14.32 5.01 13.13C4.66 11.93 4.64 10.19 5.31 9.07C5.98 7.94 7.67 6.87 9.02 6.39C10.36 5.90 11.97 6.00 13.36 6.14C14.75 6.29 16.26 6.54 17.35 7.25C18.45 7.96 19.66 9.22 19.92 10.41z"/>'
    '<path d="M17.19 10.60C17.34 11.29 17.05 12.27 16.63 12.92C16.21 13.57 15.41 14.17 14.67 14.50C13.92 14.83 12.94 14.99 12.15 14.90C11.37 14.81 10.56 14.43 9.96 13.97C9.37 13.52 8.80 12.86 8.60 12.16C8.41 11.47 8.39 10.46 8.78 9.81C9.16 9.16 10.13 8.54 10.90 8.25C11.68 7.97 12.61 8.03 13.41 8.12C14.21 8.20 15.07 8.35 15.70 8.76C16.33 9.18 17.03 9.91 17.19 10.60z"/>'
    '<path d="M14.38 10.87C14.42 11.08 14.37 11.35 14.25 11.55C14.13 11.75 13.91 11.95 13.68 12.06C13.46 12.17 13.14 12.22 12.89 12.20C12.64 12.18 12.36 12.07 12.18 11.92C12.00 11.78 11.86 11.54 11.82 11.33C11.78 11.12 11.83 10.85 11.95 10.65C12.07 10.45 12.29 10.25 12.52 10.14C12.74 10.03 13.06 9.98 13.31 10.00C13.56 10.02 13.84 10.13 14.02 10.28C14.20 10.42 14.34 10.66 14.38 10.87z"/>'
    '</svg>')

# The lapse rate at or below which a layer is drawn as the lid on the day. Here because
# the caption has to state it and the caption is written in Python; the rule itself is in
# the script, and a test holds the two to the same number.
CAP_LAPSE = 2.0

# The dry adiabatic lapse rate, which is physics rather than a threshold — but the caption
# quotes it and the script constructs the parcel with it, so it is written once here and
# once in the script, and `tests/test_meteo_view.py` holds the two to the same number.
DRY_LAPSE = 9.8

# How many takeoffs can be compared at once. Three was the palette's limit — the slots
# that validate all-pairs in both themes — until the reader asked for more (October
# 2026). Six now: slots 4–6 (amber-brown, slate, olive) are told apart from the first three
# and from each other less surely by colour alone, which the page allows because no
# takeoff is ever told by colour alone: the table names every row, every line carries
# its label, and each column is headed by its name.
MAX_CHOSEN = 6

STYLE = """
/* The takeoff colours are `--series-1..6` in `common.TOKENS`: an identity palette of
   their own (violet, cyan, pink, then amber-brown, slate, olive), so a takeoff's dot is
   never the accent or a verdict's green. Six, the comparison's cap (`MAX_CHOSEN`);
   identity is never colour alone — the table names every row and every line carries
   its label. */
.meteo-article h1 { display: none; }
/* The day, the hour and the takeoffs apply to everything below, so they stay in view. */
.met-sticky { position: sticky; top: 0; z-index: 20; background: var(--paper);
  padding: 14px 0 12px; border-bottom: 1px solid var(--rule); margin: -18px 0 22px; }
.met-head { display:flex; flex-wrap:wrap; gap:12px 22px; align-items:center; margin: 0 0 14px; }
.met-day-row { display:flex; flex-wrap:wrap; align-items:center; gap:10px; min-width:0; }
.met-days { flex:none; min-height:44px; }   /* its buttons come from the script */
.met-hour { display:flex; align-items:center; gap:12px; font-size:16px; color:var(--ink-2);
  flex:1 1 300px; min-width:240px; }
.met-hour label { display:inline-flex; align-items:center; }
.met-hour .info-wrap { margin-left: 0.3em; }
.met-hour input { flex:1; min-width:120px; accent-color: var(--accent); height: 28px; }
.met-hour output { min-width:3.6em; font-size:19px; font-weight:650; color:var(--ink);
  font-variant-numeric:tabular-nums; }
/* What the page is fetching or could not: a notice floating at the foot of the screen,
   not a line in the header — appearing and going there it moved everything under it. */
.met-status { position:fixed; left:50%; bottom:16px; transform:translateX(-50%); z-index:50; margin:0;
  max-width:calc(100vw - 32px); width:max-content; padding:8px 16px; border-radius:999px;
  background:var(--pop-bg); color:var(--pop-ink); font-size:15px; box-shadow:var(--float-shadow); }
.met-status:empty { display:none; }
/* The column standing in for a takeoff while the forecast loads. */
.met-col-wait .met-col-tools { visibility:hidden; }
.met-col-wait .met-canvas { animation: met-wait 1.4s ease-in-out infinite alternate; }
@keyframes met-wait { from { opacity:.55; } to { opacity:1; } }
@media (prefers-reduced-motion: reduce) { .met-col-wait .met-canvas { animation:none; } }

/* The chosen takeoffs, as one switcher, then +; the list of every takeoff is behind +.
   Wider than its row the switcher scrolls, and an end with more takeoffs past it fades
   out under a ‹ or ›, so it reads as a strip to scroll rather than a cropped control. */
.met-chosen { display:flex; flex-wrap:nowrap; gap:10px; align-items:center; margin:0; }
.met-picks { position:relative; display:flex; min-width:0; flex:0 1 auto; }
.met-picks[hidden] { display:none; }
.met-picks .seg { position:relative; max-width:100%; overflow-x:auto; scrollbar-width:none;
  overscroll-behavior-x:contain; }
.met-picks .seg::-webkit-scrollbar { display:none; }
.met-picks .seg > button { flex:none; white-space:nowrap; display:inline-flex; align-items:center; gap:8px; padding:0 14px; }
.met-picks .dot { width:11px; height:11px; border-radius:50%; flex:none; }
.met-pick[draggable="true"] { cursor:pointer; }
.met-pick.is-dragged { opacity:.5; }
.met-more { position:absolute; top:1px; bottom:1px; z-index:2; width:46px; display:flex; align-items:center;
  font-size:21px; font-weight:600; color:var(--ink); pointer-events:none; opacity:0; transition:opacity .15s; }
.met-more-l { left:1px; padding-left:9px; border-radius:10px 0 0 10px;
  background:linear-gradient(to left, transparent, var(--panel) 65%); }
.met-more-r { right:1px; padding-right:9px; justify-content:flex-end; border-radius:0 10px 10px 0;
  background:linear-gradient(to right, transparent, var(--panel) 65%); }
.met-picks.more-l .met-more-l, .met-picks.more-r .met-more-r { opacity:1; }
.met-add { border-style:dashed; color:var(--ink-2); cursor: pointer; flex:none; }
.met-add:disabled { opacity: .5; cursor: default; }
.met-cap { display: none; }

/* The comparison: the page's answer, so its largest text. It is also the palette's
   table view, which is what lets the series colours rest on a label as well as a hue. */
.met-compare { width:100%; border-collapse:collapse; margin:0 0 30px; font-variant-numeric:tabular-nums; }
.met-compare th, .met-compare td { text-align:left; padding:14px; font-size:18px;
  border-bottom:1px solid var(--rule); white-space: nowrap; }
.met-compare thead th { font-size:15.5px; color:var(--ink-2); font-weight:600; padding: 10px 14px; }
.met-compare thead th .info-wrap { vertical-align: 0; }
.met-compare tbody tr { cursor:pointer; }
.met-compare tbody tr:hover { background:var(--panel-2); }
.met-compare tbody tr.is-focus { background:var(--panel); }
.met-compare .site { display:flex; align-items:center; gap:9px; font-weight:650; }
.met-compare .site .swatch { width:11px; height:11px; border-radius:50%; flex:none; }
.met-compare .best { font-weight:700; }
/* Verdicts: the word always, the colour beside it. */
.met-verdict::first-letter { text-transform: uppercase; }
.met-verdict { display:inline-block; align-items:center; padding:3px 11px; border-radius:999px;
  font-size:15px; font-weight:600; line-height:1.3; white-space:nowrap; }
.met-good { background:var(--good); color:var(--on-good); }
.met-fair { background:var(--warn); color:var(--on-warn); }
.met-poor { border:1.5px solid var(--edge); color:var(--ink-2); }
.met-none { border:1.5px dashed var(--edge); color:var(--ink-2); }

/* The picker, in a dialog: Escape closes it, the backdrop closes it, focus stays inside.
   One step off the page, with a shadow, so it reads as a surface in both themes. */
.met-modal { width:min(600px, 94vw); max-height:82vh; padding:0; border:1px solid var(--edge);
  border-radius:14px; background:var(--panel); color:var(--ink); box-shadow:0 18px 44px rgba(0,0,0,0.45); }
.met-modal::backdrop { background:rgba(0,0,0,0.55); }
.met-modal-head { display:flex; gap:10px; align-items:center; padding:14px 16px; border-bottom:1px solid var(--rule); }
.met-modal-head h2 { margin:0; font-size:19px; flex:none; }
.met-search { flex:1; font:inherit; font-size:16px; height:44px; padding:0 14px; border:1px solid var(--edge);
  border-radius:10px; background:var(--paper); color:var(--ink); min-width:0; }
.met-modal-foot { display:flex; justify-content:space-between; align-items:center; gap:10px;
  padding:12px 16px; border-top:1px solid var(--rule); font-size:15px; color:var(--ink-2); }
.met-list { max-height:56vh; overflow-y:auto; }
.met-site { display:grid; grid-template-columns: auto 1fr auto; gap:2px 12px; width:100%; text-align:left;
  border:0; border-bottom:1px solid var(--rule); border-radius:0; padding:12px 16px; background:transparent;
  cursor:pointer; color:var(--ink); font: inherit; }
.met-site:last-child { border-bottom:0; }
.met-site:hover { background:var(--panel-2); }
.met-site.is-on { background:var(--panel-2); }
.met-site .tick { grid-row:1 / span 2; align-self:center; width:18px; text-align:center; color:var(--ink-2); font-size:17px; }
.met-site.is-on .tick { color:var(--ink); }
.met-site-name { font-weight:600; font-size:16px; }
.met-site-note { grid-column:2; font-size:15px; color:var(--ink-2); font-variant-numeric:tabular-nums; }
.met-empty { padding:18px 16px; color:var(--ink-2); font-size:16px; }
.met-site .met-verdict { align-self:center; }

.met-panel { border:0; padding:0; }
.met-strip, .met-keys { display:none !important; }

/* Small multiples, one column per takeoff: a strip that scrolls sideways, as a phone's
   swipes, three columns to the row at most and two filling it when there are two. The
   canvases carry `width`/`height` and no CSS height, so a wider column makes a chart
   bigger rather than flatter. One takeoff puts its two charts side by side instead, so a
   lone takeoff's charts come out the size of a pair's. */
.met-columns { position:relative; display:flex; gap:22px; margin:0; overflow-x:auto; scroll-snap-type:x mandatory;
  overscroll-behavior-x:contain; scrollbar-width:thin; padding-bottom:6px; }
.met-columns:not(.is-single) .met-col { flex:0 0 calc((100% - 44px) / 3); scroll-snap-align:start; }
.met-columns.is-two .met-col { flex-basis:calc((100% - 22px) / 2); }
.met-columns.is-single { display:block; overflow:visible; padding-bottom:0; }
.met-col { min-width:0; }
.met-col .met-canvas + .met-canvas { margin-top:10px; }
.met-columns.is-single .met-col { display:grid; gap:0 22px; align-items:start;
  grid-template-columns: repeat(2, minmax(0, 1fr)); }
.met-columns.is-single .met-col-head, .met-columns.is-single .met-col-rose,
.met-columns.is-single .met-col-top, .met-columns.is-single .met-col-fly { grid-column:1 / -1; }
.met-columns.is-single .met-canvas + .met-canvas { margin-top:0; }
/* Side by side, the airgram takes the sounding's shape, so the two height scales read across. */
.met-columns.is-single .met-col-air { aspect-ratio: 380 / 300; }
.met-col-head { display:flex; align-items:baseline; gap:9px; font-size:21px; font-weight:650; margin:0 0 2px; }
.met-col-head i { width:11px; height:11px; border-radius:50%; flex:none; align-self:center; }
.met-col-head .name { background:none; border:0; padding:0; font:inherit; color:inherit; cursor:pointer; }
.met-col-head .dirs { font-weight:600; font-size:16px; color:var(--ink-2); min-width:0;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.met-col-head .dirs.is-marginal { font-weight:400; font-style:italic; }
/* The takeoff's ParaglidingEarth page, and its place in the order, at the head's end. */
.met-col-tools { margin-left:auto; display:inline-flex; align-items:center; gap:2px; align-self:center; }
.met-col-tools a, .met-col-move, .met-col-drop { width:34px; height:34px; border:0; background:none; padding:0;
  color:var(--ink-2); border-radius:50%; display:inline-flex; align-items:center; justify-content:center; cursor:pointer; }
.met-col-tools a:hover, .met-col-move:hover:not(:disabled), .met-col-drop:hover { color:var(--ink); background:var(--panel-2); }
.met-col-move:disabled { opacity:.3; cursor:default; }
.met-columns.is-single .met-col-move { display:none; }

.met-col-rose { font-size:15.5px; color:var(--ink-2); margin:0 0 10px; font-variant-numeric:tabular-nums; }
/* The number visible, the reason one tap away. */
.met-col-top { font-size:16.5px; color:var(--ink); margin:8px 0 14px; display:flex; align-items:center; }
.met-col-top[hidden] { display:none; }
.met-canvas { width:100%; display:block; background:var(--panel); border-radius:14px; }
/* A finger scrolls the page and swipes the columns over the charts as anywhere else; a
   tap reads a chart, and a press held then dragged scrubs it (`bindReader`). The sounding
   used to keep the vertical drag, and with the charts most of a phone's screen the page
   was hard to scroll. `manipulation` only drops the double-tap zoom, so a tap reads at
   once. */
.met-col-sounding, .met-col-air { touch-action: manipulation; -webkit-touch-callout: none;
  -webkit-user-select: none; user-select: none; }
/* The synoptic situation, a link off the page: the pressure chart for the days above. */
/* The synoptic chart, an icon by the days it is about. */
.met-synoptic { width:44px; padding:0; flex:none; }
/* flymet's meteogram for the airfield nearest this takeoff, under its own charts. */
.met-col-fly { margin: 0; }
.met-col-fly img { display:block; width:100%; border-radius:14px; background:#fff; }
.met-col-fly figcaption { display:flex; justify-content:space-between; align-items:center; gap:10px;
  font-size:15px; color:var(--ink-2); margin:6px 0 0; }
.met-col-fly figcaption a { color:var(--ink-2); }
.met-col-fly .lnk { color:var(--accent); }
.met-sources { margin:30px 0 0; }
.met-sources > summary { color:var(--accent); font-weight:600; cursor:pointer; min-height:44px; display:flex; align-items:center; }
.met-src { width:100%; border-collapse:collapse; margin:8px 0 0; font-size:15px; }
.met-src th { text-align:left; font-weight:600; color:var(--ink-2); border-bottom:1px solid var(--rule); padding:0 12px 6px 0; }
.met-src td { padding:8px 12px 8px 0; border-bottom:1px solid var(--rule); color:var(--ink-2); vertical-align:top; }
.met-src td:first-child { color:var(--ink); font-weight:600; white-space:nowrap; }
.met-src a { color:inherit; text-decoration:underline; text-underline-offset:2px; }
.met-terms { margin:16px 0 0; font-size:15px; color:var(--ink-2); }
.met-terms dt { color:var(--ink); }
/* On a phone each source is a block: what, then where from. */
@media (max-width: 640px) {
  .met-src thead { display:none; }
  .met-src, .met-src tbody, .met-src tr, .met-src td { display:block; }
  .met-src tr { padding:10px 0; border-bottom:1px solid var(--rule); }
  .met-src td { border:0; padding:2px 0; }
  .met-src td:last-child { font-size:14px; }
}
.met-legend { font-size:15px; color:var(--ink-2); margin:6px 0 0; }
.met-flymet { display:none !important; }

@media (max-width: 640px) {
  .met-sticky { margin: -18px -14px 18px; padding: 12px 14px 10px; }
  .met-head { gap: 10px; margin-bottom: 10px; }
  .met-hour { flex-basis: 100%; min-width: 0; }
  /* The days across the phone's width, the synoptic chart's icon at the end: tighter
     buttons so the four and the icon share a 360 px row, stretched on a wider one. */
  .met-day-row { flex: 1 1 100%; flex-wrap: nowrap; }
  .met-days { flex: 1 1 auto; display: flex; }
  .met-days > button { flex: 1 1 auto; padding: 0 10px; }
  /* The head on one line: the name gives way (…) before the height or the tools do. */
  .met-col-head { font-size:19px; gap:7px; }
  .met-col-head .name { flex:none; max-width:62%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .met-col-tools { flex:none; gap:0; }
  .met-col-tools a, .met-col-move, .met-col-drop { width:32px; height:32px; }
  /* The switcher across the row up to +, however few takeoffs: buttons grow to fill it
     and never shrink, so with many it still scrolls. */
  .met-picks { flex: 1 1 auto; }
  .met-picks .seg { flex: 1 1 auto; display: flex; }
  .met-picks .seg > button { flex: 1 0 auto; justify-content: center; }
  /* + alone on a phone: the switcher gets the room. */
  .met-add { padding:0; width:44px; justify-content:center; }
  .met-add span { display:none; }
  /* The table keeps takeoffs as rows: name and verdict, then wind, thermal top, cloudbase. */
  .met-compare, .met-compare thead, .met-compare tbody { display:block; }
  /* One takeoff: no comparison, and no empty header standing in for one. */
  .met-compare[hidden] { display:none; }
  .met-compare tr { display:grid; grid-template-columns: 1.35fr 1fr 1fr 1fr; align-items:center;
    column-gap:8px; border-bottom:1px solid var(--rule); padding:8px 0; }
  .met-compare th, .met-compare td { border:0; padding:2px 0; font-size:16px; }
  .met-compare thead th { font-size:15px; white-space:normal; }
  .met-compare thead th:nth-child(2), .met-compare .hide-narrow { display:none; }
  .met-compare tbody tr > :nth-child(1) { grid-column:1; grid-row:1; }
  .met-compare tbody tr > :nth-child(2) { grid-column:1; grid-row:2; }
  .met-compare tr > :nth-child(3) { grid-column:2; grid-row:1 / span 2; }
  .met-compare tr > :nth-child(4) { grid-column:3; grid-row:1 / span 2; }
  .met-compare tr > :nth-child(5) { grid-column:4; grid-row:1 / span 2; }
  .met-compare thead tr > :nth-child(1) { grid-row: 1 / span 2; }
  /* The swipe uses the screen's full width: a column at a time, edge to edge. */
  .met-columns:not(.is-single) { gap:14px; margin:0 -14px; padding:0 14px; scroll-padding:0 14px;
    scrollbar-width: none; }
  /* One column a swipe, however fast: a quick flick ran on two or three columns past. */
  .met-columns:not(.is-single) .met-col, .met-columns.is-two .met-col { flex:0 0 100%; scroll-snap-align:center;
    scroll-snap-stop:always; }
  .met-columns.is-single .met-col { display:block; }
  .met-columns.is-single .met-canvas + .met-canvas { margin-top:10px; }
}
"""



def nearest_stations(sites=None, stations=None) -> list[dict | None]:
    """The flymet station nearest each takeoff, one entry per site and in the same order.

    Paired here rather than in the page because neither list moves: takeoffs and airfields
    are both committed data, so this is arithmetic the build can do once instead of 159
    times in every reader's browser — and it is arithmetic a test can check without a
    browser at all.
    """
    sites = site_data.SITES if sites is None else sites
    stations = flymet_data.STATIONS if stations is None else stations
    out: list[dict | None] = []
    for site in sites:
        best, best_m = None, None
        for station in stations:
            metres = distance_m(site["lat"], site["lon"], station["lat"], station["lon"])
            if best_m is None or metres < best_m:
                best, best_m = station, metres
        if best is None or best_m > FLYMET_RANGE_KM * 1000:
            out.append(None)
            continue
        out.append({"slug": best["slug"], "name": best["name"],
                    "km": round(best_m / 1000, 1)})
    return out


def body(uid: str = "meteo") -> str:
    """The view's markup. Everything with a number in it is filled by the script."""
    payload = json.dumps({
        "sites": site_data.SITES,
        "octants": list(site_data.OCTANTS),
        "levels": list(LEVELS),
        "endpoint": ENDPOINT,
        "attribution": site_data.ATTRIBUTION,
        "fetched": site_data.FETCHED,
        # The flymet meteogram for the station nearest each takeoff: a second opinion,
        # from a model and a hand this page does not have. Only two days of it exist.
        "flymet": {
            "near": nearest_stations(),
            "today": flymet_data.TODAY,
            "tomorrow": flymet_data.TOMORROW,
            "index": flymet_data.SOURCE,
        },
    }, separators=(",", ":"))
    info = common.info
    return f"""<article class="flight meteo-article" id="{uid}-article">
  <!-- The day and the hour apply to everything below, so they stay in view. -->
  <div class="met-sticky">
  <div class="met-head">
    <div class="met-day-row">
      <div class="seg met-days" id="met-days" role="group" aria-label="Which day"></div>
      <a class="tool met-synoptic" href="{SYNOPTIC}" rel="noreferrer" target="_blank"
         title="Synoptic chart (ČHMÚ)" aria-label="Synoptic chart (ČHMÚ)">{SYNOPTIC_ICON}</a>
    </div>
    <div class="met-hour">
      <label for="met-hour-input">Hour</label><span class="info-wrap"><button type="button" class="info"
        aria-expanded="false" aria-label="About the forecast model">i</button><span class="info-pop"
        role="note" id="met-model">The forecast model for this hour.</span></span>
      <input type="range" id="met-hour-input" min="6" max="20" step="1" value="14"
             aria-describedby="met-hour-readout">
      <output id="met-hour-readout" for="met-hour-input">14:00</output>
    </div>
    <p class="met-status" id="met-status" role="status">Fetching the forecast…</p>
  </div>

  <div class="met-chosen" id="met-chosen">
    <button type="button" class="chip met-add" id="met-add">{common.icon(common.ICONS["plus"])}<span>Add takeoff</span></button>
  </div>
  </div>

  <table class="met-compare" id="met-compare" hidden
         aria-label="The chosen takeoffs at the chosen hour">
    <thead><tr>
      <th scope="col">Takeoff</th><th scope="col">Verdict</th>
      <th scope="col">Wind</th>
      <th scope="col">Thermal top</th><th scope="col">Cloudbase</th>
      <th scope="col" class="hide-narrow">Temp / dew</th>
      <th scope="col" class="hide-narrow">Lid</th>
      <th scope="col" class="hide-narrow">Ground</th>
    </tr></thead>
    <tbody></tbody>
  </table>

  <div class="met-panel" id="met-panel">
    <h3 id="met-name" hidden>The day, takeoff by takeoff</h3>
    <p class="met-sub" id="met-sub" hidden></p>
    <!-- The boundary layer of every takeoff on one chart. Each column draws its own now,
         side by side, which says the same; kept for the script, not shown. -->
    <div class="met-strip" id="met-strip" hidden>
      <canvas class="met-canvas" id="met-band" width="960" height="170"></canvas>
      <p class="met-keys" id="met-keys"></p>
    </div>
    <div class="met-columns" id="met-columns" data-sounding-hint="Shaded: a layer the
      thermals stop at — lapse under {CAP_LAPSE:.0f} °C/km, red where the air warms with
      height. Orange: the dry adiabat, {DRY_LAPSE:.1f} °C/km from the surface temperature;
      the ring is where a parcel stops. Point, or tap, to read every sounding at that
      height; press and hold to drag the reading."></div>
    <!-- flymet's meteograms now sit in each takeoff's column (`drawFlymet`). -->
    <details class="met-flymet" id="met-flymet" hidden>
      <summary id="met-flymet-summary"></summary>
      <div id="met-flymet-list"></div>
    </details>
  </div>

  <dialog class="met-modal" id="met-modal" aria-labelledby="met-modal-title">
    <div class="met-modal-head">
      <h2 id="met-modal-title">Takeoffs</h2>
      <input type="search" class="met-search" id="met-search" aria-label="Search takeoffs"
             placeholder="Search {len(site_data.SITES)} takeoffs, best of the day first">
      <button type="button" class="tool" id="met-close" aria-label="Close">{common.icon(common.ICONS["close"])}</button>
    </div>
    <div class="met-list" id="met-list"></div>
    <div class="met-modal-foot">
      <span id="met-count"></span>
      <button type="button" class="btn primary" id="met-done">Done</button>
    </div>
  </dialog>
  <!-- Where everything on the page comes from, folded at the foot as on the Planner
       (October 2026: it was an ⓘ behind "A forecast is not a decision"). -->
  <details class="met-sources"><summary>Sources and method</summary>
    <table class="met-src">
      <thead><tr><th>What</th><th>Source</th></tr></thead>
      <tbody>
        <tr><td>Forecast</td><td><a href="https://open-meteo.com/" rel="noreferrer">Open-Meteo</a>:
          DWD ICON-D2 (2&nbsp;km) as far as it reaches, ICON-EU (7&nbsp;km) after, and the
          boundary layer height from ECMWF IFS, which ICON does not publish</td></tr>
        <tr><td>Takeoffs</td><td>Chosen after <a href="https://gfs.pgweb.cz/" rel="noreferrer">gfs.pgweb.cz</a>'s
          essentials. {site_data.ATTRIBUTION}</td></tr>
        <tr><td>Airfield meteograms</td><td>{flymet_data.ATTRIBUTION}, from
          <a href="{flymet_data.SOURCE}" rel="noreferrer">flymet</a>: {len(flymet_data.STATIONS)}
          stations, each takeoff shown its nearest</td></tr>
      </tbody>
    </table>
    <!-- What the comparison's columns mean: two ⓘ in the table head until October 2026. -->
    <dl class="gloss met-terms">
      <dt>Verdict</dt><dd>Flyable when the wind blows up a slope this takeoff works in. Wind only.</dd>
      <dt>Lid</dt><dd>A stable layer below 4&nbsp;km: lapse under {CAP_LAPSE:.0f}&nbsp;°C/km; “inv” where it warms with height.</dd>
      <dt>Thermal top</dt><dd>Two estimates: ECMWF’s mixing height (dashed) and a dry parcel lifted from the 2&nbsp;m air (ring). The parcel is usually lower.</dd>
    </dl>
  </details>
  <script type="application/json" class="met-data">{payload}</script>
</article>"""


SCRIPT = (Path(__file__).parent / "js/meteo.js").read_text(encoding="utf-8")
# One number for the cap, in the page and in the prose that states it.
SCRIPT = SCRIPT.replace("__MAX_CHOSEN__", str(MAX_CHOSEN))

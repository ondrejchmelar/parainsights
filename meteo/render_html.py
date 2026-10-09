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
.met-hour { display:flex; align-items:center; gap:12px; font-size:16px; color:var(--ink-2);
  flex:1 1 300px; min-width:240px; }
.met-hour label { display:inline-flex; align-items:center; }
.met-hour .info-wrap { margin-left: 0.3em; }
.met-hour input { flex:1; min-width:120px; accent-color: var(--accent); height: 28px; }
.met-hour output { min-width:3.6em; font-size:19px; font-weight:650; color:var(--ink);
  font-variant-numeric:tabular-nums; }
.met-status { color:var(--ink-2); font-size:15px; margin:0; flex-basis:100%; }
.met-status:empty { display:none; }

/* The chosen takeoffs, as chips; the list of every takeoff is behind a button. */
.met-chosen { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:0; }
.met-chip { padding: 0 6px 0 16px; }
.met-chip.is-focus { border-color:var(--ink); }
.met-chip .swatch { width:11px; height:11px; border-radius:50%; flex:none; }
.met-chip-name { background:none; border:0; padding:0; font:inherit; color:inherit; cursor:pointer; height: 100%; }
.met-chip-drop { position: relative; width:32px; height:32px; border:0; background:none; padding:0;
  color:var(--ink-2); cursor:pointer; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; }
.met-chip-drop::after { content: ""; position: absolute; inset: -6px; }
.met-chip-drop:hover { color:var(--ink); background:var(--panel-2); }
.met-add { border-style:dashed; color:var(--ink-2); cursor: pointer; }
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

/* Small multiples, one column per takeoff, filling the row whatever the count. The
   canvases carry `width`/`height` and no CSS height, so a wider column makes a chart
   bigger rather than flatter. One takeoff puts its two charts side by side instead, so a
   lone takeoff's charts come out the size of a pair's. */
.met-columns { display:grid; gap:22px; margin:0; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.met-col { min-width:0; }
.met-col .met-canvas + .met-canvas { margin-top:10px; }
.met-columns.is-single .met-col { display:grid; gap:0 22px; align-items:start;
  grid-template-columns: repeat(2, minmax(0, 1fr)); }
.met-columns.is-single .met-col-head, .met-columns.is-single .met-col-rose,
.met-columns.is-single .met-col-top, .met-columns.is-single .met-col-fly { grid-column:1 / -1; }
.met-columns.is-single .met-canvas + .met-canvas { margin-top:0; }
/* Side by side, the airgram takes the sounding's shape, so the two height scales read across. */
.met-columns.is-single .met-col-air { aspect-ratio: 380 / 300; }
.met-columns.is-single .met-col-airout { grid-column:1; }
.met-col-airout { font-size:15px; color:var(--ink-2); margin:4px 0 0; min-height:1.5em; font-variant-numeric:tabular-nums; }
.met-col-head { display:flex; align-items:baseline; gap:9px; font-size:21px; font-weight:650; margin:0 0 2px; }
.met-col-head i { width:11px; height:11px; border-radius:50%; flex:none; align-self:center; }
.met-col-head .name { background:none; border:0; padding:0; font:inherit; color:inherit; cursor:pointer; }
.met-col-head .ground { font-weight:400; font-size:16px; color:var(--ink-2); font-variant-numeric:tabular-nums; }
.met-col-rose { font-size:15.5px; color:var(--ink-2); margin:0 0 10px; }
.met-col-rose a { color:var(--accent); font-weight:600; text-decoration:none; }
.met-col-rose a:hover { text-decoration:underline; }
/* The number visible, the reason one tap away. */
.met-col-top { font-size:16.5px; color:var(--ink); margin:8px 0 14px; display:flex; align-items:center; }
.met-col-top[hidden] { display:none; }
.met-col.is-focus .met-col-head .name { text-decoration:underline; text-underline-offset:4px; }
.met-canvas { width:100%; display:block; background:var(--panel); border-radius:14px; }
/* The sounding reads a height from a vertical drag, the gesture the page scrolls with;
   this hands it to the chart. The airgram above each one still scrolls the page. */
.met-col-sounding { touch-action: none; }
/* flymet's meteogram for the airfield nearest this takeoff, under its own charts. */
.met-col-fly { margin: 0; }
.met-col-fly img { display:block; width:100%; border-radius:14px; background:#fff; }
.met-col-fly figcaption { display:flex; justify-content:space-between; align-items:center; gap:10px;
  font-size:15px; color:var(--ink-2); margin:6px 0 0; }
.met-col-fly figcaption a { color:var(--ink-2); }
.met-col-fly .lnk { color:var(--accent); }
.met-links { margin:30px 0 0; font-size:16px; color:var(--ink-2); }
.met-legend { font-size:15px; color:var(--ink-2); margin:6px 0 0; }
.met-swipe { display:none; }
.met-flymet { display:none !important; }

@media (max-width: 640px) {
  .met-sticky { margin: -18px -14px 18px; padding: 12px 14px 10px; }
  .met-head { gap: 10px; margin-bottom: 10px; }
  .met-hour { flex-basis: 100%; min-width: 0; }
  .met-chosen { flex-wrap: nowrap; overflow-x: auto; margin-right: -14px; padding-right: 14px; }
  .met-chosen > * { flex: none; }
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
  /* One takeoff's charts at a time, side by side by a swipe. */
  .met-swipe { display:flex; justify-content:center; margin:0 0 14px; }
  .met-swipe .seg > button { padding:0 12px; }
  .met-columns:not(.is-single) { display:flex; overflow-x:auto; scroll-snap-type:x mandatory; gap:14px;
    margin:0 -14px; padding:0 14px; scrollbar-width: none; }
  .met-columns:not(.is-single) .met-col { flex:0 0 88%; scroll-snap-align:center; }
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
    <div class="seg met-days" id="met-days" role="group" aria-label="Which day"></div>
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
      <th scope="col">Takeoff</th><th scope="col">Verdict{info("Flyable when the forecast wind blows up a slope this takeoff works in. The verdict is about the wind only; the columns beside it say how high the day goes.")}</th>
      <th scope="col">Wind</th>
      <th scope="col">Thermal top</th><th scope="col">Cloudbase</th>
      <th scope="col" class="hide-narrow">Temp / dew</th>
      <th scope="col" class="hide-narrow">Lid{info("A stable layer that stops thermals — lapse under " + f"{CAP_LAPSE:.0f}" + " °C/km — if one sits below 4 km. “inv” where the air warms with height.")}</th>
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
    <!-- A phone shows one takeoff's charts at a time; this picks which, and a swipe does. -->
    <div class="met-swipe" id="met-swipe"></div>
    <div class="met-columns" id="met-columns" data-sounding-hint="Shaded: a layer the
      thermals stop at — lapse under {CAP_LAPSE:.0f} °C/km, red where the air warms with
      height. Orange: the dry adiabat, {DRY_LAPSE:.1f} °C/km from the surface temperature;
      the ring is where a parcel stops. Point or drag to read every sounding at that
      height."></div>
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
  <p class="met-links">A forecast is not a decision — check the airspace, the NOTAMs and the
    sky.{info(f"""Forecast from <a href="https://open-meteo.com/" rel="noreferrer">Open-Meteo</a>,
    fetched in this page: DWD ICON-D2 (2 km) for as far as it reaches, ICON-EU (7 km) after,
    and the boundary layer height from ECMWF IFS, which ICON does not publish. Takeoffs chosen
    after <a href="https://gfs.pgweb.cz/" rel="noreferrer">gfs.pgweb.cz</a>'s essentials.
    {site_data.ATTRIBUTION}, list taken {site_data.FETCHED}. {flymet_data.ATTRIBUTION}, loaded
    from <a href="{flymet_data.SOURCE}" rel="noreferrer">flymet</a> —
    {len(flymet_data.STATIONS)} stations, matched to the nearest takeoff.""", "Sources")}</p>
  <script type="application/json" class="met-data">{payload}</script>
</article>"""


SCRIPT = (Path(__file__).parent / "js/meteo.js").read_text(encoding="utf-8")
# One number for the cap, in the page and in the prose that states it.
SCRIPT = SCRIPT.replace("__MAX_CHOSEN__", str(MAX_CHOSEN))

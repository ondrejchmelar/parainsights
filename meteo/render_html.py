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

# How many takeoffs can be compared at once, and it is a number the *palette* chose.
# Slots 1–3 of the design system's categorical order validate all-pairs in both themes;
# the fourth slot is yellow, and yellow against this orange fails the normal-vision floor
# (ΔE 13.7 against a 15 floor). Re-stepping a documented palette is not allowed and no
# reordering fixes an all-pairs failure, so the honest cap is three — see the comment at
# the top of `STYLE`. It is also about the number of hills a pilot really chooses between
# on a Saturday morning, which is why it does not feel like a limitation.
MAX_CHOSEN = 3

STYLE = """
/* The three series colours, and the reason there are three of them.
   Slots 1–3 of the design system's categorical palette — the same blue, orange and aqua
   the report paints phases with — checked with the dataviz skill's `validate_palette.js`
   against this page's own panel colour in both themes: all-pairs CVD ΔE 9.2 light /
   9.4 dark, normal vision 24.0 / 20.9. **A fourth site is not a fourth colour.** The
   documented order puts yellow next, and yellow against this orange fails the
   normal-vision floor (ΔE 13.7) — no re-stepping is allowed and no ordering fixes an
   all-pairs failure, so the comparison caps at three and says so on screen.
   Light aqua and orange sit under 3:1 on the light panel, which the palette's relief
   rule permits only with direct labels or a table: this has both. */
:root { --series-1:#2a78d6; --series-2:#eb6834; --series-3:#1baf7a; }
@media (prefers-color-scheme: dark) {
  :root { --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70; }
}
.met-head { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center;
  margin: 0 0 12px; }
.met-days { display:inline-flex; border:1px solid var(--rule); border-radius:3px;
  overflow:hidden; }
.met-days button { border:0; border-right:1px solid var(--rule); border-radius:0;
  padding:5px 13px; background:var(--panel); }
.met-days button:last-child { border-right:0; }
.met-days button.is-on { background:var(--ink); color:var(--paper); }

/* The chosen takeoffs, as chips. This is what replaced a 159-row list holding the top
   left corner of the page: the list is now behind a button, and what stays on screen is
   the three or fewer places the reader actually asked about. */
.met-chosen { display:flex; flex-wrap:wrap; gap:8px; align-items:center;
  margin:0 0 14px; }
.met-chip { display:inline-flex; align-items:center; gap:8px; padding:5px 6px 5px 10px;
  border:1px solid var(--rule); border-radius:999px; background:var(--panel);
  font-size:13.5px; }
.met-chip.is-focus { border-color:var(--ink-3); background:var(--panel-2); }
.met-chip .swatch { width:10px; height:10px; border-radius:50%; flex:none; }
.met-chip-name { background:none; border:0; padding:0; font:inherit; color:inherit;
  cursor:pointer; }
.met-chip-drop { border:0; background:none; padding:0 5px; line-height:1;
  font-size:15px; color:var(--ink-3); cursor:pointer; border-radius:50%; }
.met-chip-drop:hover { color:var(--ink); background:var(--panel-2); }
.met-add { border-style:dashed; border-radius:999px; padding:6px 14px; }
.met-cap { font-size:12px; color:var(--ink-3); }

/* The comparison. It is also the palette's *table view*, which is what makes the two
   light-mode series that fall under 3:1 against the panel legitimate. */
.met-compare { width:100%; border-collapse:collapse; margin:0 0 16px;
  font-variant-numeric:tabular-nums; }
.met-compare th, .met-compare td { text-align:left; padding:7px 10px; font-size:13px;
  border-bottom:1px solid var(--rule); }
.met-compare thead th { font-size:11px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--ink-3); font-weight:600; }
.met-compare tbody tr { cursor:pointer; }
.met-compare tbody tr:hover { background:var(--panel); }
.met-compare tbody tr.is-focus { background:var(--panel-2); }
.met-compare .site { display:flex; align-items:center; gap:8px; font-weight:600; }
.met-compare .site .swatch { width:10px; height:10px; border-radius:50%; flex:none; }
.met-compare .best { font-weight:700; }
@media (max-width: 620px) {
  .met-compare .hide-narrow { display:none; }
  /* Side by side on a phone is two 290 px charts, which is smaller than either was
     before. A single takeoff stacks again below this width. */
  .met-columns.is-single .met-col { display:block; }
  .met-columns.is-single .met-canvas + .met-canvas { margin-top:8px; }
}

/* The picker, in a dialog: Escape closes it, the backdrop closes it, and focus stays
   inside it — all of which a hand-rolled overlay would have to reimplement worse. */
/* One step off the page rather than the same colour as it. `--paper` *is* the page, so
   in the dark theme the dialog and the document behind it were the same value and a 1 px
   rule was the whole of the separation — with a backdrop dim that has almost nothing to
   dim. A surface and a shadow do the work in both themes. */
.met-modal { width:min(560px, 94vw); max-height:82vh; padding:0; border:1px solid
  var(--rule); border-radius:6px; background:var(--panel); color:var(--ink);
  box-shadow:0 18px 44px rgba(0,0,0,0.45); }
.met-modal::backdrop { background:rgba(0,0,0,0.55); }
.met-modal-head { display:flex; gap:10px; align-items:center; padding:12px 14px;
  border-bottom:1px solid var(--rule); }
.met-modal-head h2 { margin:0; font-size:16px; flex:none; }
.met-search { flex:1; font:inherit; padding:6px 10px; border:1px solid var(--rule);
  border-radius:3px; background:var(--panel); color:var(--ink); min-width:0; }
.met-modal-foot { display:flex; justify-content:space-between; align-items:center;
  gap:10px; padding:10px 14px; border-top:1px solid var(--rule);
  font-size:12.5px; color:var(--ink-3); }
.met-list { max-height:56vh; overflow-y:auto; }
.met-site { display:grid; grid-template-columns: auto 1fr auto; gap:2px 10px;
  width:100%; text-align:left; border:0; border-bottom:1px solid var(--rule);
  border-radius:0; padding:8px 11px; background:transparent; cursor:pointer;
  color:var(--ink); }
.met-site:last-child { border-bottom:0; }
.met-site:hover { background:var(--paper); }
.met-site.is-on { background:var(--panel-2); }
.met-site .tick { grid-row:1 / span 2; align-self:center; width:16px; text-align:center;
  color:var(--ink-3); }
.met-site.is-on .tick { color:var(--ink); }
.met-site-name { font-weight:600; font-size:13.5px; }
.met-site-note { grid-column:2; font-size:11.5px; color:var(--ink-3);
  font-variant-numeric:tabular-nums; }
.met-empty { padding:18px 14px; color:var(--ink-3); font-size:13px; }
.met-verdict { align-self:center; font-size:11px;
  text-transform:uppercase; letter-spacing:.06em; padding:3px 7px; border-radius:3px;
  white-space:nowrap; }
.met-good { background:#15803d; color:#fff; }
.met-fair { background:#a16207; color:#fff; }
.met-poor { background:var(--panel-2); color:var(--ink-3); }
.met-none { background:transparent; color:var(--ink-3); border:1px dashed var(--rule); }
.met-panel { border:1px solid var(--rule); border-radius:4px; padding:14px 16px; }
.met-panel h3 { margin:0 0 2px; font-size:17px; }
.met-sub { margin:0 0 12px; color:var(--ink-3); font-size:12.5px; }
.met-strip { margin:16px 0 6px; }
.met-strip .chart-title { font-size:11px; text-transform:uppercase; letter-spacing:.07em;
  color:var(--ink-3); margin:0 0 4px; }

/* Small multiples, one column per takeoff, filling the row whatever the count. The
   columns used to be capped at 340 px, which is what three of them come to — so three
   filled the panel and one used a third of it, leaving two thirds of the row empty
   beside a chart the reader had asked to look at.

   The cap was there to stop a sounding being "stretched past its own aspect ratio",
   which would flatten the lapse rate it exists to show. Measured, that is not what
   stretching a column does: these canvases carry `width`/`height` attributes and no CSS
   height, so the box keeps its intrinsic 380:300 and a wider column makes the chart
   bigger rather than wider — 340x268 at three takeoffs, 525x413 at two, the same 1.27
   either way. What the cap was really protecting against is the *single* takeoff, where
   filling the row proportionally means an 839 px sounding under a 645 px meteogram, and
   the reader scrolls past one chart to reach the other.

   So one takeoff puts its two charts side by side instead. Both stay in shape, both grow,
   the row is full, and a lone takeoff's charts come out the same size as a pair's. */
.met-columns { display:grid; gap:16px; margin:14px 0 0;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); }
.met-col { min-width:0; }
.met-col .met-canvas + .met-canvas { margin-top:8px; }
.met-columns.is-single .met-col { display:grid; gap:0 16px; align-items:start;
  grid-template-columns: repeat(2, minmax(0, 1fr)); }
.met-columns.is-single .met-col-head,
.met-columns.is-single .met-col-rose,
.met-columns.is-single .met-col-top { grid-column:1 / -1; }
.met-columns.is-single .met-canvas + .met-canvas { margin-top:0; }
/* Side by side, the airgram takes the sounding's shape rather than its own shorter one.
   Both charts run 0–4 km up the y axis, so equal heights put the two height scales beside
   each other and the reader can read across — boundary layer on the left at the height
   the trace bends on the right. Stacked, they keep their own proportions, because there
   is nothing to read across to. */
.met-columns.is-single .met-col-air { aspect-ratio: 380 / 300; }
.met-columns.is-single .met-col-airout { grid-column:1; }
/* The airgram reads on a tap, not a drag, so it is left to scroll the page: with the
   sounding taking vertical drags for its own readout, it is the column's strip to scroll
   from on a phone. */
.met-col-airout { font-size:11.5px; color:var(--ink-3); margin:3px 0 0; min-height:1.5em;
  font-variant-numeric:tabular-nums; }
.met-col-head { display:flex; align-items:center; gap:7px; font-size:12.5px;
  font-weight:600; margin:0 0 5px; }
.met-col-head i { width:10px; height:10px; border-radius:50%; flex:none; }
.met-col-head .name { background:none; border:0; padding:0; font:inherit; color:inherit;
  cursor:pointer; }
.met-col-head .ground { font-weight:400; color:var(--ink-3);
  font-variant-numeric:tabular-nums; }
.met-col-rose { font-size:11.5px; color:var(--ink-3); margin:0 0 6px; }
/* Two answers to one question, and the reason there are two — folded, because the
   number is what a reader wants and the reason is for the one who asks. */
.met-col-top { font-size:12px; color:var(--ink-2); margin:4px 0 0; }
.met-col-top summary { cursor:pointer; }
.met-col-top summary .why { color:var(--ink-3); text-decoration:underline dotted; }
.met-col-top p { margin:4px 0 0; color:var(--ink-3); font-size:11.5px; max-width:60ch; }
.met-col-rose a { color:inherit; }
.met-col.is-focus .met-col-head .name { text-decoration:underline;
  text-underline-offset:3px; }
.met-canvas { width:100%; display:block; background:var(--panel); border-radius:3px; }
/* The sounding reads a *height* from a vertical drag, which is the same gesture the page
   scrolls with — so the browser scrolled the page and the chart read nothing. This hands
   the gesture to the chart, and it is the same `touch-action: none` the 3D view and the
   airspace map already use for theirs. The cost is real and bounded: a swipe that starts
   on a sounding no longer scrolls. The airgram directly above each one is untouched,
   so every column keeps a full-width strip to scroll from. */
.met-col-sounding { touch-action: none; }
/* The hour is in the head, above everything, because it applies to everything: the
   ranking, the comparison and both charts all answer "at what time". It used to sit
   under the sounding, where it read as a control for that one chart. */
.met-hour { display:flex; align-items:center; gap:9px; font-size:12.5px;
  color:var(--ink-2); flex:1 1 240px; min-width:200px; }
.met-hour input { flex:1; min-width:120px; }
.met-hour output { min-width:3.6em; font-variant-numeric:tabular-nums; }
.met-flymet { margin:16px 0 0; }
.met-flymet figure { margin:0 0 18px; }
.met-flymet figure:last-child { margin-bottom:0; }
.met-flymet figcaption { font-size:11.5px; color:var(--ink-3); margin:5px 0 0; }
.met-flymet .for { display:flex; align-items:center; gap:7px; font-size:12.5px;
  font-weight:600; color:var(--ink-2); margin:0 0 2px; }
.met-flymet .for i { width:10px; height:10px; border-radius:50%; flex:none; }
.met-flymet > summary { font-size:12.5px; color:var(--ink-2); cursor:pointer;
  padding:4px 0; }
/* Its own width, not the panel's: the meteogram is 1024 px of small type and axis
   labels, and stretched past that it is a blurred picture of a chart. */
.met-flymet img { display:block; width:100%; max-width:1024px; border-radius:3px;
  background:var(--panel); margin-top:6px; }
.met-flymet p { font-size:11.5px; color:var(--ink-3); margin:5px 0 0; }
.met-flymet a { color:inherit; }
.met-model { color:var(--ink-3); font-size:12.5px; margin:0; }
.met-model b { color:var(--ink-2); font-weight:600; }
.met-status { color:var(--ink-3); font-size:13px; margin:0; flex-basis:100%; }
.met-status:empty { display:none; }
.met-links { margin:14px 0 0; font-size:12.5px; color:var(--ink-3); }
.met-legend { font-size:11.5px; color:var(--ink-3); margin:6px 0 0; }
/* Identity is never colour alone: every series in the meteogram is named here as well
   as drawn, and the lines carry their own labels at the right-hand end. */
.met-keys { display:flex; flex-wrap:wrap; gap:4px 16px; margin:6px 0 0; font-size:11.5px;
  color:var(--ink-2); }
.met-keys span { display:inline-flex; align-items:center; gap:6px; }
.met-keys i { width:14px; height:0; border-top-width:2px; border-top-style:solid;
  display:inline-block; }
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
    return f"""<article class="flight meteo-article" id="{uid}-article">
  <h1>Meteo</h1>
  <div class="met-head">
    <div class="met-days" id="met-days" role="group" aria-label="Which day"></div>
    <div class="met-hour">
      <label for="met-hour-input">Hour</label>
      <input type="range" id="met-hour-input" min="6" max="20" step="1" value="14"
             aria-describedby="met-hour-readout">
      <output id="met-hour-readout" for="met-hour-input">14:00</output>
    </div>
    <p class="met-model" id="met-model"></p>
    <p class="met-status" id="met-status" role="status">Fetching the forecast…</p>
  </div>

  <div class="met-chosen" id="met-chosen">
    <button type="button" class="met-add" id="met-add">+ add a takeoff</button>
  </div>

  <table class="met-compare" id="met-compare" hidden
         aria-label="The chosen takeoffs at the chosen hour">
    <thead><tr>
      <th scope="col">takeoff</th><th scope="col">verdict</th><th scope="col">wind</th>
      <th scope="col">thermal top</th><th scope="col">cloudbase</th>
      <th scope="col" class="hide-narrow">temp / dew</th>
      <th scope="col" class="hide-narrow">lid</th>
      <th scope="col" class="hide-narrow">ground</th>
    </tr></thead>
    <tbody></tbody>
  </table>

  <div class="met-panel" id="met-panel">
    <h3 id="met-name">The day, takeoff by takeoff</h3>
    <p class="met-sub" id="met-sub"></p>
    <div class="met-strip" id="met-strip" hidden>
      <p class="chart-title">Boundary layer height</p>
      <canvas class="met-canvas" id="met-band" width="960" height="170"></canvas>
      <p class="met-keys" id="met-keys"></p>
    </div>

    <!-- What the prose under the charts used to say, kept where a reader who wants it
         finds it: on the sounding itself, as its tooltip. The labels on the charts carry
         the rest. -->
    <div class="met-columns" id="met-columns" data-sounding-hint="Shaded: a layer the
      thermals stop at — lapse under {CAP_LAPSE:.0f} °C/km, red where the air warms with
      height. Orange: the dry adiabat, {DRY_LAPSE:.1f} °C/km from the surface temperature;
      the ring is where a parcel stops. Point or drag to read every sounding at that
      height."></div>

    <!-- Foldable, and open by default. It is a second opinion worth having in front of
         the reader — but it is 700 px of someone else's chart under 300 px of ours, and
         a page whose own answer scrolls off the top to make room for it has its
         priorities the wrong way round. One per chosen takeoff, stacked, which is why
         folding it matters more now than it did with one. -->
    <details class="met-flymet" id="met-flymet" open hidden>
      <summary id="met-flymet-summary">flymet's own meteograms</summary>
      <div id="met-flymet-list"></div>
    </details>
  </div>

  <dialog class="met-modal" id="met-modal" aria-labelledby="met-modal-title">
    <div class="met-modal-head">
      <h2 id="met-modal-title">Takeoffs</h2>
      <input type="search" class="met-search" id="met-search" aria-label="Search takeoffs"
             placeholder="Search {len(site_data.SITES)} takeoffs, best of the day first">
      <button type="button" id="met-close" aria-label="Close">&times;</button>
    </div>
    <div class="met-list" id="met-list"></div>
    <div class="met-modal-foot">
      <span id="met-count"></span>
      <button type="button" id="met-done">Done</button>
    </div>
  </dialog>
  <p class="met-links">Forecast from <a href="https://open-meteo.com/"
    rel="noreferrer">Open-Meteo</a>, fetched in this page: DWD ICON-D2 (2 km) for as far
    as it reaches, ICON-EU (7 km) after, and the boundary layer height from ECMWF IFS,
    which ICON does not publish. Takeoffs chosen after
    <a href="https://gfs.pgweb.cz/" rel="noreferrer">gfs.pgweb.cz</a>'s essentials.
    {site_data.ATTRIBUTION}, list taken {site_data.FETCHED}.
    {flymet_data.ATTRIBUTION}, loaded from <a
    href="{flymet_data.SOURCE}" rel="noreferrer">flymet</a> when you open a takeoff —
    {len(flymet_data.STATIONS)} stations, matched to the nearest takeoff here.
    <strong>A forecast is not a decision.</strong> Check the airspace, the NOTAMs and the
    sky before you fly.</p>
  <script type="application/json" class="met-data">{payload}</script>
</article>"""


SCRIPT = (Path(__file__).parent / "js/meteo.js").read_text(encoding="utf-8")
# One number for the cap, in the page and in the prose that states it.
SCRIPT = SCRIPT.replace("__MAX_CHOSEN__", str(MAX_CHOSEN))

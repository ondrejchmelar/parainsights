# parainsights

Tools for paragliding. One repository, four tools, answering a question each:

| tool | the question | published at |
|---|---|---|
| **tracklog viewer** | how did that flight go? | `public/index.html` |
| **airspaces** | what is above me, and what does my instrument not know? | `public/airspace/` |
| **meteo** | is it worth driving anywhere today, and where? | `public/meteo/` |
| **planner** | what is that task worth, and what does it cross? | `public/airspace/`, on the airspace map |

```
parainsights/
├── CLAUDE.md              this file
├── pyproject.toml         one project, one venv, one test suite
├── tracklog_viewer/       IGC/KML/KMZ → the report page; the analysis is JavaScript (js/)
├── airspaces/             Czech airspace + the airfields nobody else carries → OpenAir, map
├── meteo/                 the day's sounding against pgweb's essential takeoffs
├── planner/               a task drawn on the airspace it crosses — a section of the airspace page
├── parainsights_common/   the one thing every page shares: the strip between the tools
├── parainsights_map/      the 3D map every page draws with: MapLibre + deck.gl, the scene, terrain
├── ci/                    the checks the pipeline runs that are not tests
├── tests/                 pytest, ~560 tests, no network; the JS through Node (tests/js.py)
└── docs/
    ├── formats.md            IGC and KML/KMZ format research, measured on real files
    ├── plan.md               tracklog viewer: scope, decisions and status
    ├── ux-review.md          the report's UX, measured; the debrief layer, planned
    ├── analysis-plan.md      what more the data can say, and what data would help
    ├── airspaces.md          airspaces: sources, decisions and status
    ├── meteo.md              meteo: why Open-Meteo and not Windy, and what it fetches
    ├── meteo-ux.md           the meteo page's UX, measured before and after the rework
    ├── planner.md            planner: the scoring rules and where they come from
    └── atz-datum-hlaseni.md  draft report to RLP of the datum error found in LKR315A
```

A fifth tool goes in as a sibling package (`parainsights/<tool_name>/`) sharing this
`pyproject.toml` and `tests/`, and adds itself to `parainsights_common.PAGES` so the
other three link to it.

**Where the "no shared code" rule applies, and where it does not.** `airspaces/geo.py`
exists alongside `tracklog_viewer/js/geo.js` rather than sharing it, because they are not
the same geodesy: the viewer works on the FAI sphere because that is what a scored
distance is measured on, and airspace is published against WGS84. That is the rule, and
it is about *geodesy and analysis*, where the tools genuinely disagree.

The 3D map is the exception that shows the edge of it. It is a **map widget** — hand it a
terrain grid, some imagery and a list of things to draw and it never asks what a flight
is — so the viewer and the Planner share it, as the package `parainsights_map` (the map,
the panel and scene it draws from, the library loader and the DEM fetcher), rather than
each carrying its own copy. Its flight code went to
`js/scene.js` first, which is what made it a move. Imports of it from `airspaces` are
lazy, so the OpenAir file still builds with the map absent. Likewise `planner`
reads its scoring constants out of `tracklog_viewer/js/xc.js` — a planner that scored a
task differently from the report that later measures the flight would be worse than no
planner.

## Getting set up

The environment is [uv](https://docs.astral.sh/uv/)'s. It installs the interpreter as well
as the packages, so there is nothing to line up by hand:

```bash
uv sync --extra dev          # creates .venv on the pinned Python, from uv.lock
uv run pytest -c pyproject.toml     # ~560 tests, a few minutes in parallel, no network
```

`-c pyproject.toml` matters when the repo sits inside another project — pytest otherwise
walks up and adopts the enclosing config. **Node is the other requirement**: the flight
analysis and the article are JavaScript, the report is built by running them in Node,
and the tests reach them through Node too (`tests/js.py`). Without Node those tests skip.

**The installed set is a fact, not a coincidence.** `uv.lock` is committed and CI runs
`uv sync --locked`, which fails rather than silently resolving something new — so an
upstream release cannot turn the pipeline red on its own, and when a bump is wanted it is
`uv lock --upgrade` and a commit you can point at. `.python-version` pins the interpreter;
uv refuses to build a venv that violates `requires-python`, which is what previously let a
3.11 venv sit under a `>=3.12` floor unnoticed.

Run it:

```bash
uv run python -m tracklog_viewer.cli FLIGHT.igc --html out.html
uv run python -m tracklog_viewer.cli FLIGHT.igc --meteo --terrain --html out.html
uv run python -m tracklog_viewer.cli a.igc b.kmz c.igc --html all.html   # flight picker

uv run python -m airspaces.cli --openair CZ_airfields.txt  # aerodrome zones + okruhy for XCTrack
uv run python -m airspaces.cli --html airspace.html     # the airspace map, in 3D
uv run python -m airspaces.cli --report                # what built, and what did not

uv run python -m meteo.cli --html meteo.html           # the day, against every takeoff
uv run python -m meteo.cli --refresh-sites             # re-fetch sources.CHOSEN's takeoffs
uv run python -m meteo.cli --refresh-flymet            # re-read flymet's station map

uv run python -m planner.cli --html plan.html          # only the redirect to ../airspace/
```

Only `--meteo`, `--terrain` and `--airspace` touch the network at build time. Everything
else in the viewer is offline. `meteo` and `airspaces` both need one at build time, and the meteo *page* needs
one at view time — it is the one artifact here that is deliberately not self-contained,
because a forecast built at 03:00 and published is wrong by lunchtime.

`airspaces` fetches from four public sources and caches them under
`~/.cache/parainsights/airspace`; `--refresh` re-fetches. Its tests use fixtures.

## airspaces, in one paragraph

A paraglider may fly inside a Czech ATZ but must keep out of the traffic circuit, and
**no ATZ is in the airspace XCTrack or XContest carries** — one of the 251 airspaces in
the Aeroklub base file is an ATZ, and only because it is a controlled aerodrome. So this
builds an overlay: 82 aerodrome zones as class `W` (XCTrack paints `W` green) and 205
traffic circuits as class `Q` (orange, silent) at 156 fields, drawn as 410 rectangles
because a circuit is two of them meeting on the runway — imported alongside the normal
airspace rather than replacing it. The page's own copy says *aerodrome zone* rather than
*ATZ*, because half of those 156 fields have no ATZ at all. Read `docs/airspaces.md`
before changing it; the four things most likely
to be re-litigated are that the writer emits only `AC AN AH AL AF V DP DC DB` because
XCTrack rejects `AG` and misreports a missing `AH` against the *next* airspace, that the
circuit is a hollow band on **both** sides of the runway because the glider circuit
mirrors the powered one, that the band carries a 60 m gap because OpenAir has no hole
and a self-touching ring fills differently under the two fill rules, and that the
published ATZ geometry is 117 m out and gets corrected. The okruh is **not** an XCTrack
obstacle and cannot be — obstacles are a curated per-country download with no Czech
coverage and no import path.

The map draws each airspace as the **box** it is, floor to ceiling, which is the whole
reason it is a 3D view: three zones with the same outline and
different limits are one red line on a flat map.

**The planner is a section of the airspace page**, not a page of its own (October 2026):
they were two tabs drawing the same airspace over the same ground. Its bar sits over the
map, its score and crossing list under it, and drawing is a mode (*Draw a task*), off by
default, because on a phone a tap on this map names the zone under the finger and one
gesture must not mean two things. The map is built once by `airspaces.render_html.
SCRIPT3D`, which publishes the handle as `window.__airspaceMap`; the planner's script
waits on it, and only the airspace script sets the airspace filter (class, floor, time) —
the planner listens to the time control only to re-mark its list. The ground is the
planner's wider box (`scene.PLAN_BOX`, Czechia and the Alps, 120 000 nodes) fetched by
the page (`scene.remote`), opening framed on Czechia (`view.focus`); in the report the
fetch waits until the view is first opened. A build can therefore no longer lose the
terrain, so `--require-terrain` is accepted and does nothing. `public/planner/` is a
redirect (`planner/cli.py`), and `common.PAGES` has three entries.

**The airspace and planner maps open at
×5 vertical**, and that is not a decoration: at true scale over 500 km of country a 300 m
traffic circuit projects to **0.3 px**, and 2.8 px even zoomed a long way in, so every box
is two coincident rings and the 3D view shows exactly what the flat one did. The
segmented control offers ×1, ×5 and ×15, the caption says which is on, and every label
carries the real limits. The *report* still opens at true scale, where it belongs: a
flight is kilometres of air over tens of kilometres of ground, and true scale is the
setting you can read height above ground from. `view3d.panel(verticals=…, vertical=…)`
is how a page says which it wants. Two things there are decisions and not
details — a limit carries its *datum* as well as its number, so anything AGL stays a
height and is resolved against the terrain in the renderer; and the 21 airspaces that run
to FL165 or higher are **capped at 4 000 m**, drawn with a dashed open lid and their real
ceiling in the label, because drawn true they hide everything a paraglider meets. See
"The boxes" in `docs/airspaces.md`.

**The maps' airspace is openAIP's, across Europe** (October 2026). openAIP (openaip.net)
is the community airspace database, CC BY-NC 4.0 — fine for this non-commercial site,
credited wherever it is drawn. Its API needs a key and a key in a page is anyone's, so
the pages never call it: `airspaces/openaip.py` fetches 45 European countries (the Alps,
Turkey) and writes one file each into `public/airspace/layers/` with an `index.json` of
their boxes — 6.5 MB, 1.2 MB gzipped, France and Italy the largest at ~840 KB.
`.github/workflows/airspace.yml` refetches on the 3rd of every month with the repository
secret `OPENAIP_API_KEY`, commits only files whose airspace changed (a new date on the
same data would be a megabyte of history a month), and starts the Pages deploy itself —
a push with the workflow's token starts no workflow. Locally the key is
`~/.config/parainsights/openaip-key` or `OPENAIP_API_KEY`, never the repository.
Each ring carries the published name, class and limits too (`nm ac lo hi`), so
`openaip.read` gives the objects back and the Planner page builds from the committed
Czech file with no key. Service boundaries (FIR, airways, sectors) and anything floored at
FL195 or above are not drawn (`openaip.TYPES`).
**Czechia is openAIP too, ATZs included; ours adds only the traffic circuits**
(`cz-circuits.json`, written by both command lines) — the pilot's call, to keep it
simple. Our corrected aerodrome zones stay in the OpenAir download for XCTrack, which
is what that file is for. The Aeroklub `CZ_low` file it replaced is gone from
`sources.py`.
**Every flight's map loads its airspace when opened**, bundled and uploaded alike
(`loadAirspace` in `view3d`, before the views are built): the index once, then only the
files whose box reaches the flight's ground, the rings that do, biggest first. A
refresh therefore reaches every flight without rebuilding the report, which CI cannot
do. The scene carries `airspaceRemote` (where the layers are; the report names it in
`<meta name="airspace-layers">` for uploads) and the switch starts disabled — "Loading
the airspace…" — then is enabled with the credit as its title, or says why not (Hunza:
"the layers cover Europe"). Fetching means **airspace needs the page served over
http(s)**; opened from `file://` the switch says it could not load.
**A flight's map draws only the airspace the flight had to do with** (`relevantAirspace`,
after the terrain is in, since a limit above ground needs the ground — the pilot's rule,
October 2026): zones the track came within 5 km of sideways and 200 m vertically (1 km at first: it kept zones floored far above the flight); not the
kinds that bind nobody (danger and firing areas, sport/aerobatic, alert, warning, gliding
sectors — protected areas and parks *are* binding and stay); and not zones openAIP marks
as active only by NOTAM (`nt`, 376 across Europe). NOTAMs are not fetched, for the
flight's time or now, so a zone activated during a flight is missing too, and the caption
says so. Over the Dolomites flight 2 of 11 loaded zones remain, over Krupka 28 of 138.
The Planner map still draws everything.

## A network is assumed

**This was not always true and the code still remembers it.** Everything here was built
to run inside a published artifact, behind a policy that blocks every external host — and
that one constraint is why there was an embedded DEM, an embedded basemap, locally
rendered charts, a canvas 3D view instead of a map library, and an inlined font.

That assumption is retired. The site is GitHub Pages, the reader has a connection, and
the trade was never close: a fetched mosaic is 10–20 m a pixel where an embedded one can
afford 45, the detail layer makes it sharper again as you zoom in, and the file is half
the size. So **imagery is fetched at view time** in all three page-writing tools, and
`--embed`, which baked it in, is gone: nothing used it. The planner fetches its
**terrain grid** at view time too (`terrain.remote`, loaded by `view3d`'s
`initView3dWhenReady`) — what ground heights are read from (airspace floors given above
the ground, which zones a flight came near); the map streams its own terrain.
`--online` is still accepted and does nothing, so an old command line still runs.

What is *not* retired, because it is still true and still worth keeping:

- the charts are rendered locally, because Google Image Charts died in 2019 and took
  every graph in igc2kmz's output with it;
- the font is inlined, because a font is one request for a document's whole appearance.

The 3D view was a canvas and a shader of its own for that reason; it is MapLibre and
deck.gl from unpkg now (October 2026), and the canvas renderer is gone (see "Only the
merged map" under Decisions). So three things *require* a network at view time rather
than merely preferring one: the meteo page has no numbers of its own, the imagery on
every 3D map is fetched, and so is the map itself.
Both say so on screen when the fetch fails rather than drawing an empty frame.

**The meteo page compares up to three takeoffs, and three is the palette's number.**
The list sits in a `<dialog>` — 15 takeoffs now, gfs.pgweb.cz's ESSENTIALS plus four in
the Alps (`meteo.sources.CHOSEN`); when it was all 159 Czech ones, on the page it was 571 px of layout and
**166 tab stops** before a keyboard user reached the forecast, which `docs/meteo-ux.md`
measures before and after. Wind is in **m/s** throughout, asked of Open-Meteo as
`wind_speed_unit=ms` so nothing converts anything, with the verdict gates converted
exactly from the old km/h pair. What stays on the page is a chip per chosen takeoff, a
comparison table at the chosen hour, a strip carrying every chosen takeoff's boundary
layer *and nothing else*, a column per takeoff holding its own meteogram and sounding,
and flymet's picture for each — the charts a
pilot actually argues over, which the one-site-at-a-time page could only answer one hill
at a time. The soundings are **small multiples with a shared probe height**: three
temperature traces and three dew points on one frame is six crossing lines, but pointing
at 1 500 m over one hill and reading 1 500 m over all three is the question itself.
flymet's is one picture per *station*, not per takeoff, because two hills often share
their nearest airfield. **The thermal top is drawn twice, on purpose.** The dashed line is
the model's convective boundary layer height — handed over, not read off the chart — and
beside it the sounding now draws the construction a pilot would do by hand: the dry adiabat
from the surface, stopping where it meets the temperature trace, with a ring on the
crossing. The model knows the day's heating, the wind's mixing and the entrainment at the
top, none of which one profile and a straight edge can see, so where the two disagree the
reader sees the disagreement rather than being handed a number. `parcelTop` returns nothing
where there is no crossing rather than a ring at an arbitrary height — including on a
profile that is stable to dry convection from the ground up, which is what a lapse rate
under 9.8 °C/km means and what the test fixture happens to be.
The columns fill the row at any count, and a single takeoff puts its two charts side by
side rather than stretching one into an 839 px sounding; both then carry the same 0–4 km
axis at the same height, so the reader can read across. The cap is
three because slots 1–3 of the categorical palette pass `validate_palette.js` all-pairs in
both themes and the documented fourth slot (yellow) fails the normal-vision floor against
this orange — so the page says *three at a time* rather than drawing a line nobody can
tell from another. Two light-mode series fall under 3:1 on the panel, so identity is
carried by direct labels, the legend *and* the table, which is the palette's relief rule
and is pinned by a browser test.

One image on the meteo page comes from a **third party at view time**: flymet's meteogram
for the airfield nearest the chosen takeoff. It is linked and not copied — the reader's
browser fetches it from flymet, flymet is named in the caption and the caption links back
— so nothing here republishes it. Over `https`, because the site is https and a browser
drops a mixed-content image without drawing anything or saying why.

Publishing is a build and a commit — the site is `public/`, handed to GitHub Pages by
`.github/workflows/pages.yml`. The repository moved from GitLab in October 2026; the
GitLab project is deprecated, and `.gitlab-ci.yml` now publishes only redirect stubs
(`ci/redirect.sh`) so the old address sends readers on to the same page here:

```bash
uv run python -m tracklog_viewer.cli FLIGHT.igc --terrain --meteo \
  --html public/index.html
git add public/index.html && git commit -m "Publish flight" && git push
```

Nothing server-side is involved — it is static files. Opened over `file://` the page
works except for what it fetches beside itself: the airspace layers.

## What the tool does

Reads a tracklog and answers a pilot's questions about the flight: how the climbs were
worked, what the wind was doing, how the glides went, what the air was like that day.

Test data: `~/Downloads/*.igc` (60 files: XCTrack, SkyBean SkyDrop, Flytec) with matching
igc2kmz KMZs. `~/bin/igc2kmz` is Tom Payne's original Python-2 tool — the ancestor of this
one, still runnable under `python2.7` as an oracle.

**The analysis is JavaScript, and only JavaScript** (October 2026). It was written in
Python first, ported to `tracklog_viewer/js/` and held to the Python field for field —
63 of 63 real IGC files, 75 of 75 KMZ, every article identical — and then the Python was
retired. It is in git at `ada5e5b`, docstrings and all, which is where to read the long
reasoning behind a rule when the comment in the JavaScript is short. What went with it,
because nothing in the page used it: the Google Earth KMZ export, the pilot's archive
(`--archive`), the threshold calibrator, `--json` and the standalone `--map` page.

## Architecture

One flight goes through one function, `TV.upload.compose` (`js/upload.js`): parse, analyse,
score the route, write the article. An uploaded track goes through it in the page; the
report's own flights go through it at build time in Node (`js_build.py`). The Python is the
build and the page around the articles.

| Module | Responsibility |
|---|---|
| `js/igc.js` | IGC parsing. **Every logger quirk lives here and nowhere else.** The take-off's timezone from `js/vendor/tz-lookup.js` |
| `js/kml.js` | Track out of KML/KMZ (`gx:Track`, timed placemarks), with its own small XML and ZIP readers |
| `js/np.js` | The numpy behaviours the analysis was written against, reproduced exactly |
| `js/geo.js` | FAI-sphere haversine distance, bearing, cardinals |
| `js/flight.js` | Derived series over a 20 s interpolated window |
| `js/analysis.js` | Phases, per-climb and per-glide stats, wind, time budget, the `other` decomposition |
| `js/metrics.js` | Tier-1 measurements: climb selection, working band, centring, gaps, concentration, day envelope, ceiling use |
| `js/debrief.js` | The verdict, the findings ranked by cost, and the one `THRESHOLDS` table |
| `js/certification.js` | The wing's LTF/EN class from its header; the answers are precomputed by `certification.py` into `gliders.json` |
| `js/airmass.js` | Wind field from the per-thermal soundings; corrected glides, the empirical polar |
| `js/insolation.js` | Slope, aspect and sun incidence from the DEM; ridge-or-thermal per climb |
| `js/plan.js` | The declared task or a sidecar plan, and what the flight did against it |
| `js/xc.js` | Free distance through ≤3 turnpoints, and the best-scoring triangle |
| `js/terrain.js` | Height above the ground on a DEM grid, and the grid an upload asks for |
| `js/meteo.js` | The Open-Meteo request and the reading of its answer |
| `js/sun.js` | Solar position (NOAA), and the day tabulated for the 3D view |
| `js/charts.js` | The SVG charts the article carries, and the payload for the two drawn in the page |
| `js/scene.js` | A flight's 3D scene and panel markup |
| `js/report.js` | One flight's article, masthead to footer |
| `js/upload.js` | `compose`, `readBytes` (the one file dispatch) and the upload flow in the page |
| `js/build_runner.js` | Node side of the build: `inspect` (what to fetch) and `render` |
| `cli.py` | The build: inputs, fetches, plan discovery, airspace, the page |
| `js_build.py` | Runs `build_runner.js` |
| `sources.py` | A file, a URL's download, or a refusal for an XContest page |
| `certification.py` | The register-matching rules and `gliders.py`, compiled to `gliders.json` |
| `render_html.py` | The page around the articles: stylesheet, page script, strips, bundle |
| `upload_panel.py` | The `+ your track` panel |
| `charts_client.py` | The side and top views, drawn in the browser from the article's payload |
| `parainsights_map/` | The 3D map (a package of its own): `map3d` (the map: MapLibre + deck.gl and its controls), `view3d` (the panel, the scene, ground and airspace loading, the handle the charts drive), `render_map` (the library loader, `__openMap`, context-loss revival), `terrain` (DEM grids) |

## Decisions, and the reasons behind them

The rules below name the functions they live in as they were named in Python
(`_revolutions`, `insolation.sources`, `xc.triangle()`); the JavaScript keeps the names,
in camelCase where the Python had underscores.

Read `docs/plan.md` for the full list. The ones most likely to be re-litigated:

- **Pressure and GPS altitude are separate series.** Baro is smooth and is used for
  vertical analysis; GPS is geometric and is used for display and anything compared
  with terrain. `Flight.baro_offset` reports the ISA discrepancy. Never mix them.
  **36 of the 60 sample files have no baro at all** — GPS-only is the common case.
- **Broken altitude is repaired, broken position is dropped.** igc2kmz drops a fix whose
  vertical speed exceeds 30 m/s; on GPS-only files that discards good horizontal track
  to fix a vertical glitch. A local-median despike costs 50 repairs where dropping cost
  122 fixes.
- **Fidelity over page weight and frames, everywhere a budget is chosen.** The report's
  flights are a showcase; an uploaded track is the product. So: the 3D track carries
  **every fix** (it was Douglas–Peucker at 4 m, 12 m in a shared document, plus 4-decimal
  rounding — five or six vertices per thermal circle, drawn as zigzags), at 5 decimals.
  The DEM grid is **120 000 nodes over up to 480 columns**, fetched from up to 64 tiles,
  and the showcase flights **fetch it at view time** (`Terrain.to_remote`) rather than
  embedding ~600 KB of heights each; the Python analysis still uses the heights it
  fetched. Zooming in fetches patches of up to 320 nodes across from 36 tiles, down to
  the DEM's ~25 m, and imagery from up to 96 tiles. Measure a perf problem before
  trading any of this back. (History: 2 600 nodes was 59×43 over an alpine box — every
  facet of the heightfield visible as a quadrilateral.)
- **XContest ranks by score, not distance, and that changes which route wins.** The
  multipliers are open 1.0, flat triangle 1.2, FAI triangle 1.4, so a *shorter* triangle
  routinely beats a longer one — and the open optimum. `xc.triangle()` maximises
  perimeter × multiplier over a 260-point sample with the closing rule applied, then slides
  each corner over the full-resolution fixes; `cli` picks it over `xc.optimise()` when it
  scores higher. On the three showcase flights this reproduces XContest to **within 10 m**
  (48.64/48.63, 201.40/201.40, 400.61/400.61). Maximising distance alone gave 53.5 km flat
  where XContest says 48.63 km FAI: wrong number *and* wrong category.
- **Only a route from `triangle()` may claim a category.** `optimise()`'s route often closes
  under the 20% rule, but its distance is the four-leg path start → tp1 → tp2 → tp3 →
  finish, not a perimeter. Crediting that a triangle multiplier compares two different
  quantities, and it beat the real triangle on every closed flight.
- **Triangles are flat or FAI, and nothing else** (`xc.classify`): FAI when every side is at
  least 28% of the triangle's perimeter. Do not add a degeneracy test on side ratios — a
  triangle flattened onto a line has a + b = c, so its shortest side can still be a quarter
  of the perimeter, and XContest scores a closed there-and-back as a flat triangle anyway.
- **Turn statistics are refused above 5 s sampling** (`TURN_RESOLUTION_LIMIT`). A circle
  takes ~20 s, so a 15 s KML aliases and produces a confident wrong number. **Tow
  detection is refused above 15 s** (`TOW_RESOLUTION_LIMIT`) for the same reason: a tow
  lasts 2–5 minutes, and at coarser spacing the whole launch is three points, `progress`
  reads as straight because every corner has been cut, and any brisk launch climb gets
  called a tow — an 83 s KMZ was reported as a winch launch releasing at 4574 m.
- **A KMZ from a scoring site is reduced to 500 points, and everything measured *along*
  the track comes out low.** Measured on the same three flights, KMZ against IGC:
  89.4 → 121.3 km flown and 6 588 → 8 968 m gained; 259 → 365 km and 15.7 → 24.7 km
  gained; 476 → 623 km and 24.9 → 44.9 km gained, GPS-only against real baro. Turn counts
  are unavailable in every one. Straight-line and XC distances survive, because those need
  only the corners. Both are still accepted — a KMZ is what a scoring site gives you — but
  the uploader marks IGC as preferred and a flight read above 5 s sampling carries a
  warning next to its numbers.
- **Wind comes from circle drift** and is only trusted from climbs actually circled in
  one direction for ≥2 turns. A tow drifts with the glider, not the air.
- **Wind is metres per second, everywhere it is shown, and everywhere it is stored.**
  `Wind.speed` always was m/s and `.kmh` was a display conversion applied in a dozen
  places; the report, the KMZ, the 3D overlay, the console, the wind chart's axis and the
  in-page analysis all print m/s now, and `js/meteo.js` asks Open-Meteo for
  `wind_speed_unit=ms` so the model arrives in it too. **Ground speed stays km/h** — a
  pilot says "35 km/h" of a glide and "5 m/s" of the wind, and the glide table's speed
  column is unchanged.
  This closed a real bug rather than only changing a label. `airmass.field` built its
  vectors from `Wind.speed` (m/s) and then mixed in `meteo.wind_at()` (km/h) as the
  fallback for a flight with no circled climb — a modelled wind **3.6× too strong**, and
  a corrected glide ratio to match, on exactly the flights that had nothing better. One
  unit at rest is what makes that unforgettable: there is no conversion left to forget.
- **A thermal is the circling, not the run-in to it — and "circling" means *sustained*
  turning.** Wind is a straight-line fit to the drift, so any straight flight inside the
  phase is measured as if it were moving air. Two faults, one cause, both from the old
  `climb > 1.0` clause calling straight flight a thermal: a climb whose first 30 s of 70
  was a straight westward run reported 18 km/h from the east, and a 242 s "thermal" that
  was really two climbs with a 90 s glide between them reported 22 km/h — on a day whose
  other climbs all read 1–5 km/h. Now a thermal needs `climb > 0` **and** one of
  `progress < 0.9`, `speed < 10 km/h`, or circling; the phase is then trimmed to the
  circling and the straight entry falls to the budget's "other". Crucially `circling` is
  cleaned by `_sustained()` first: raw `|turn_rate| > 3` fires on 1 Hz GPS heading noise
  every 20–45 s during a *glide*, and those specks kept the internal gaps short enough
  for `_condense` to bridge. On the Dolomites flight this takes every per-thermal wind
  into 0.7–9.7 km/h with no outliers, at the cost of 18 climbs becoming 13 — the ones
  dropped were 1–2 turn straight-ish bumps that were never really thermals.
- **A glide that doubles back is two glides** (October 2026). Its distance is start to
  finish in a straight line, fair for a glide that bends and nonsense for one that turns
  round: a rounded 180° inside a glide is short enough for the condensing to bridge, and
  out 1.5 km and back 1 km read as a 2.3:1 glide of 0.5 km. `splitAtTurns` cuts a glide at
  the fix furthest off the straight line when the legs either side of it differ by more
  than 90°, each leg at least 60 s, and judges each part again; the parts stand as glides
  whatever their length. A turn under 90° stays one glide — it costs at most 29% of the
  distance, and the reader asked for slight changes to be left alone.
- **A turn is a full revolution; how far the nose swung is a different number.**
  `turns` counts heading advancing through 360° in *one* direction (`_revolutions`), so a
  wingover — 180° out, 180° back — is no longer most of a turn, and a climb circled both
  ways contributes the circles from each rather than cancelling to nothing. Runs are cut
  only where the heading backs up by more than `REVERSAL_HYSTERESIS` (60°), because a
  smaller threshold chops one circle into pieces that never reach 360° and the climb
  reads as zero. Across the 50 sample flights this takes 9 175 counted turns to 8 122
  (−11.5%) and 513 wind-trusted climbs to 509. **The total heading swept is kept as
  `swept_turns`** and is what tow detection asks for, because "was it flown straight" is
  a question about heading change, not about circles closing: pointing that test at
  revolutions called three foot launches in the sample set a winch launch. Circle time
  comes from the seconds spent *turning inside the counted revolutions* — dividing the
  phase duration by the count charges the circles for the scratching between them — which
  put 86 of 691 climbs outside a 12–30 s circle where the old measure put 143 of 704.
- **Ridge lift is recognised by the manoeuvre, not by the wind.** `insolation.sources`
  needs three measurements to agree — the ground is steeper than 12°, the climb's median
  height above it is under 250 m, and it scored under half a complete circle per minute.
  The third does the work: a thermal is a thing you turn inside of and a ridge is a slope
  you fly along and come back, and across the six real flights on hand every thermal ran
  above 1.2 circles a minute while every ridge beat scored none. The separation is a
  different manoeuvre, not a tuned threshold.
  The rule it replaced asked instead whether the *wind* ran into the face, above 12 km/h
  and within 60° of its aspect, and found ridge lift on **no flight at all**. Two
  structural reasons, both worth keeping in mind before anyone reaches for the wind
  again. The wind estimate is derived from *circling drift* — so an evening spent beating
  a ridge produces no estimate whatsoever (`analysis.wind` is None on `021734`, and the
  per-climb figures that do exist read 1.6–3.2 km/h, one of them 116° off a face the
  glider was demonstrably working). The one test that could have recognised the flight
  was disabled by the very behaviour it was looking for. And on the cross-country flights
  the flight-level average sat *just* under 12 km/h while individual climbs ran three
  times it, so the gate was unreachable for a whole day at a time. The offset is still
  measured and still shown in the row's tooltip; it no longer vetoes.
  Clearance is the **median over the climb** rather than the altitude at its first fix:
  one fix is one sample of a disagreement between a 60 m DEM cell and a GPS altitude, and
  on `021734` every climb reported a *negative* start clearance with medians of 32–89 m.
  Current scores: 3/3 ridge on `021734`, 2/20 on `20210703XCTOND01` (both late afternoon,
  low on a 37°/14° south-west face with the wind within 59°), and 0 on the four thermal
  cross-countries — 5 climbs out of 138, which is a finding rather than a constant.
  "How to read this" states the rule and its three thresholds, and **interpolates them
  from the module** rather than typing them. A hand-written "12°" goes stale the moment
  `RIDGE_SLOPE` moves, in the one section of the report that exists to be exact about its
  own limits — `tests/test_insolation.py` holds both the values and that shape.
- **A tow can legitimately contain a 180.** The reference tow on `2020-07-12` is a
  *two-stage* launch — a pull, a 180° turn, then a second pull — which is why the climb
  sweeps 3.3 turns of heading (and completes **no** revolution) and why judging the launch
  on a turny fragment of itself gets it wrong. This is the case `TOW_MAX_TURNS_PER_MINUTE`
  has to survive: over the whole 138 s it reads 1.43 turns/min against the 1.5 limit, but
  over the circling fragment inside it, far more. Any change to tow detection has to keep
  a deliberate 180 (and a two-stage launch) on the tow side of the line.
- **A tow is built separately, over the whole launch climb, and replaces what it
  overlaps.** It is the one straight climb that *is* a phase, so it cannot come from the
  rule above — `_launch_climb()` constructs it from `climb > TOW_MIN_CLIMB` instead.
  Three details are load-bearing: it starts at the **first fix**, not where the climb
  first passes the threshold (on the reference flight that shortens the window enough to
  read 1.54 turns/min against a 1.5 limit and lose the tow); it deliberately **overlaps**
  the short turny thermal that the circling part of a tow produces, and removes it if the
  tow wins; and it carries **no straightness test** of its own, because that is
  `_reclassify_tow`'s job and a `progress` test breaks on any discontinuity in the track.
- **Tow is a fourth phase**, detected at the launch and excluded from thermal statistics
  and from the wind estimate.
- **The take-off's timezone comes from its position** when the file does not say (only
  XCTrack ≥0.9.12 records one; 47 of 61 test files need the lookup), through
  `js/vendor/tz-lookup.js` — the same clock timezonefinder gave at all 136 sample
  take-offs. Do not be tempted by `lon / 15`.
- **Haversine, not the law of cosines** — `acos` loses precision at the ~7 m separations
  between 1 Hz fixes, which is what every derived series is built from.
- **Charts are rendered locally.** igc2kmz's Google Image Charts URLs died in 2019, so
  every graph in its output is a broken image. Don't reintroduce a network dependency
  into a chart.
- **Satellite imagery is the default basemap**, composited from Esri World Imagery plus
  its `World_Boundaries_and_Places_Alternate` label layer — the same place names as
  `World_Boundaries_and_Places`, without the region and district borders it drew over the
  photo; only the national border stays. Esri's caches are one fused raster, so a layer
  cannot be switched off, and `Canvas/World_Dark_Gray_Reference` (no lines at all) draws
  its names faint grey with no halo. Both keyless. **That label raster stops at level 12**
  (`label_max_zoom`) and answers empty tiles past it, so every name vanished as the reader
  zoomed in. **The merged view draws place names as text instead**: OpenFreeMap's
  OpenStreetMap vector tiles and fonts (keyless, CORS-open), cities bold, villages from
  zoom 11, white on a dark halo, placed by MapLibre so they never collide, over the
  photograph only. A photograph tells a pilot
  what the ground under a climb was; a road map does not. Attribution to Esri/Maxar is
  required and is rendered on the map and in the caption.
- **Uploading your own track is the first tab, not the last.** The bundled flights are a
  showcase. The reader's own file is the product, so the `+ your track` tab leads and a
  note under the tabs says the analysis happens in the page.
- **Comparing is opt-in, per tab** (the ⇆ beside the ×), bundled and uploaded flights
  alike: each picked flight's headline figures say where they stand among the picked
  ones, recounted when a flight is added or removed. On touch the ×'s 44 px tap area grows
  inward over the ⇆, so the ⇆ sits above it (`z-index`): a tap meant to compare removed
  the flight, which is what "comparing does not work" was. Uploaded tabs had no ⇆ at
  all. `tests/test_compare.py` taps them in the touch layout. **Each compared flight's
  merged map draws the others** (`entry.setOthers`, fed by `window.__compareFor`, which a
  map built later asks itself): **one thin line in one muted colour per flight, this
  map's own flight included — the climb ramp is dropped while comparing**, XContest's way
  (orange, sky blue, brick red, indigo, olive; the first try's bright magenta and cyan over
  every track's five climb colours was unreadable), a flight keeping its colour on every
  map, with a legend, and the view framed on all of them. **Following, the camera frames
  the whole group** at the shared "now": it looks at the middle of the gliders' steady
  positions and pulls back just enough to hold them, never closer than the reader's zoom —
  a pinhole fit, because a glider nearer the camera is magnified and the look-ahead puts
  the middle below the screen's, then checked each frame against where the gliders are
  drawn (`fitBias`, the model being close rather than exact). **The gliders are placed in
  the part of the map nothing covers** (`freeHeight`: down to the replay bar, the buttons
  or the legend), 60% of the way down it: on a phone those cover the bottom third, and a
  fixed "a fifth below the middle" put the gliders under them. **In the map all compared
  flights are equal**: the replay spans the first start to the last landing (`spanStart`,
  `spanEnd`), and follow frames whichever gliders are in the air, this one only while it
  is; the figures stay relative to the selected flight. Compared tracks are drawn flat
  like the own one — billboarded they faced the camera and read thicker. The legend sits
  top left (this flight bold; how each is aligned in time is in its tooltip), MapLibre's (i)
  beside it in the same corner row (at the bottom left it never lined up with the bar).
  Every flight is drawn alike in the replay: its track, its climbs and a dot at "now" —
  this one too — and no white leading stretch while comparing; each flight is one colour
  everywhere (track, climb dots, the "now" dot, its line in the height readout, which
  carries every glider's climb rate). The replay opens at 1 min/s, from a camera button —
  the play triangle is only the play button inside it. The top-right text carries a dark
  halo several deep, so it holds over the pale relief as over the photograph. The relief view's shading
  comes from DEM level 12 at most (`shade` source): at 15 the whole-metre steps terraced
  gentle slopes into bands. The background under the imagery is dark green, under the bare
  relief the light one the shading was made for.
  **The side view is part of the map** (October 2026): the report wraps the 3D panel and
  the side view in one block (`.flight-map`), the chart right under the map, full width,
  no caption; its axis buttons and legend sit below the block. The merged map's full
  screen takes the whole block (the map flexes, the chart a quarter of the screen,
  redrawn to that band's proportions by a ResizeObserver in `charts_client`, `shapeOf`);
  the buttons and legend are not shown there. Comparing, the side view
  draws every compared flight's height on the same axes (`comparedTrace`: distance flown,
  from its launch, or time on the shared clock as in the replay), each in its colour and
  this flight's in its own, the axes widened to hold them all. Its tooltip gives height
  AMSL and above the ground (`cursor-data` `agl`, from `terrain.clearance`), climb, speed
  and phase. In full screen it is moved into the full-screen element, which is *inside*
  the article — the check once asked it the other way round, and the tooltip stayed in
  the page body, behind the full screen (`test_compare`).
  **The replay drives the charts**: its "now" moves the side and top views' cursor
  (`article.__cursorAtTime`, quiet: no tooltip, not echoed back to the map), and the map
  shows the height at "now" top right (`.m3-now`: this flight's with its climb, each
  compared glider's in its colour). Flown the same day (starts within 12 h,
  `scene.start` is the first fix in UTC seconds) the replay runs on one clock — a dot
  where each glider was at the same moment, its trail inside the same window; otherwise
  by time since launch, and the legend says so. A flight more than 150 km from this map's
  ground is listed as too far, not drawn: the merged map streams ground for anywhere, so
  that is the only guard needed.
- **Flights accumulate, and any of them can be removed.** An upload becomes a new article
  with its own uid (`up1`, `up2`…) and appends a tab; every tab (bundled ones included)
  carries a `×` that removes both. Consequences worth knowing: nothing inside an article
  may use a bare `id` — two flights would collide, so every id carries the uid — the
  tab strip is driven by **one delegated listener** on the strip rather than a listener per
  tab, because tabs appear at runtime, and removing an article must delete its entries from
  `window.__view3dAll` and `__mergedAll` and dispose of its map (`host.__map`): each
  holds a DEM grid, and the map a WebGL context, of which a page gets about sixteen.
- **A tab is a wrapper, not a button.** It contains an open button and a close button, and
  a button inside a button is invalid HTML that browsers silently unnest.
- **Full-bleed needs the scrollbar measured.** `100vw` includes the scrollbar, so a
  `100vw` panel hangs off the layout viewport and anything anchored to its right edge is
  clipped. JS sets `--scrollbar` and the panel is `calc(100vw - var(--scrollbar))`. Note
  that `scrollWidth` reports the ink extent even when clipping prevents scrolling — test
  by calling `scrollTo(300, 0)` and reading `scrollX` back.
- **The hillshade is the real sun, and the sun follows the chart cursor.** The light was
  a fixed north-west lamp, which is a direction the sun is never in anywhere in the
  northern hemisphere, so the shading answered nothing a pilot asks. `js/sun.js` is the NOAA
  solar position algorithm; the payload carries the flight day sampled every ten minutes
  — under 2 KB — and **hovering a chart lights the terrain as it was at that moment**,
  which is the question itself: was that face still in the sun when I got there. A slider
  was the first attempt and was the wrong instrument twice over — it offered hours the
  flight never saw, and it made the reader hunt for a moment the charts were already
  pointing at. The cursor track carries a UTC minute per sample for it; **leaving the
  chart holds the light where it was** rather than snapping back to mid-flight, which was
  a full re-light and a colour swing across the whole terrain triggered by the pointer
  merely leaving on its way somewhere else — and it undid the comparison the reader had
  just set up. Mid-flight is still where an untouched panel starts. A table rather than a
  JavaScript port on purpose:
  `quicklook.py` already duplicates thresholds that can drift, and 144 pairs of numbers
  cannot. The azimuth is **unwrapped** in the table, or interpolating across 360 sweeps
  the light the long way round the compass. The map re-lights MapLibre's hillshade
  (`sunTo`) only once the sun has moved a degree, while the rose reads the exact
  position and stays smooth. A sun below
  the horizon is held 3° up rather than drawing a black panel.
- **The sun and the wind are on the compass rose, which turns with the map.** Both are
  geographic bearings, so a rose that did not turn would agree with the ground at one
  heading and lie at every other. **The wind arrow points opposite `wind.from`** — the
  reported bearing is where the air comes from, the arrow shows where it is going, and
  drawing it along the bearing is the classic 180° error that still looks like a
  perfectly good arrow. **A click on the rose turns the map north**
  (`easeTo({bearing: 0})`), and is not also a turnpoint for the planner.
- **An uploaded track fetches its own DEM, and CORS is why it can.** `js/upload.js` asks
  for the box the CLI would (`TV.terrain.remoteFor`: 64 tiles, 120 000 nodes over up to
  480 columns) and the page's own `loadTerrain` fills it — mosaicking the terrarium tiles
  onto a canvas and decoding `R * 256 + G + B / 256 - 32768`, the formula in
  `terrain.py`. It works because the tiles carry `Access-Control-Allow-Origin: *`;
  without that the canvas is tainted, `getImageData` throws, and the upload goes on with
  no ground grid — no clearance finding, as a report built without `--terrain`, and the
  status line says so.
- **An uploaded track is wired exactly as a built report's flight is**, because it *is*
  one: the article comes from the same `compose`, and `TV.upload.place` runs
  `__drawCharts` and `initFlight` on it, which bind the linked cursor, the tables and the
  3D map. (The reduced `quicklook.py` needed its own `linkCharts`
  for this, and its canvas charts had no tooltip or band highlight; both are gone.)
- **Full screen is the real Fullscreen API, and the in-page maximise is its fallback.**
  It used to be the fallback only, because `requestFullscreen` fails two ways at once in
  an iframe without the permission — a synchronous throw with no user activation, and a
  rejection without the permission — and the button appeared to do nothing. That reasoning
  held for a published artifact and stopped holding when Pages became the primary home:
  served from a host the API is granted, and it is what a reader means by full screen. So
  the button asks for it, and falls back to `.is-maximised` on a throw, on a rejection,
  *and* on an implementation that returns undefined and quietly does nothing — the third
  needs a check after a tick, which no amount of promise handling would catch. It takes
  the flight's whole map block (`.flight-map`: the map and the side view), and the
  side-view tooltip moves into it (`test_compare`).
- **The keyboard follows the map; the pointer follows the hand.** Bare arrows pan and
  shift + arrows rotate and tilt, matching the pointer: holding shift turns a drag, and
  so it turns a key. Keys are bound to the map, never the document — a report holds
  several flights, and a document-level handler drives whichever map it finds first.
- **A click pins the linked cursor; hover is only a preview.** Hover is the right default
  — sweep a chart and the map keeps up — but on its own it takes the marker away at the
  moment the reader wants it, when they have found something and are turning to look at
  the 3D view or the table. So a click pins: hovering still previews, leaving a chart
  returns to the pinned point rather than clearing, and the pin lets go on a second click,
  on Escape, or after 30 s with no interaction, re-armed by any hover so it expires after
  the reader stops rather than while they are still reading. "Show me" pins too, for the
  same reason and worse — it is a deliberate act that any stray mouse movement undid. The
  climbs and glides tables are the third way in: rows carry `data-cursor`, a *sample*
  position mapped from the segment's fix index by `_sample_position`, the same mapping a
  finding's cursor uses. Pinning also calls `handle.revealCursor`, which pans the 3D view
  until the marker is inside a comfortable inset — pan only, because this projection has
  no behind-the-camera case and turning the view unasked throws away the orientation the
  reader had just built. It needs a pixel of slack: `panX += (padX - p)` does not land `p`
  back on `padX` exactly, and a strict comparison asks for another correction every call.
- **No finding may assert something the run did not check.** Three sentences broke this
  and are gone: a per-flight claim that igc2kmz had been run on *this* file and found the
  same climbs (printed for every flight, checked for none); a cap sentence quoting the
  reference flight's "above ~2 080 m the profile only cools 4 K/km" at every reader, now
  measured per day by `_cap_note`; and the underground low-point card, where a negative
  clearance is the DEM losing an argument with the GPS. That last one is the general rule:
  a card that has to explain why its own headline number is wrong is worse than no card,
  because the framing lands and the disclaimer does not. `insolation.sources` carries the
  same rule as a flag — `confident` is false where the label is a fallback rather than a
  finding, and the table prints a dash, since "thermal because there was nothing to check"
  is not the claim "thermal because the ground was flat".
- **Only the merged map** (October 2026). There were three 3D views behind a switch: the
  canvas (`view3d`, a heightfield of its own in 2D canvas or WebGL), plain MapLibre and
  the merged view, which took what each was better at and became the default. The other
  two are gone (in git history), and so is the switch. What is left of `view3d` is the
  data: the panel (`view3d.panel`, a sized box, the exaggerations offered as
  `data-verticals`/`data-vertical`, the scene as JSON), `readScene`, the ground grid
  (`loadTerrain`), the airspace (`loadAirspace`, `relevantAirspace`, `settleAirspace`,
  which leaves the switch's wording in `scene.airspaceWhy`) and the handle
  (`initView3d`): `built`, `groundAt`, the cursor members and the airspace filter, which
  only remember — the map wraps them, which is how a chart hover or a planner filter
  reaches it. `render_map` loads MapLibre and deck.gl from unpkg once per page and
  mounts the map (`window.__openMap(host)`) once the handle is ready. **Without a
  network there is no 3D map**, and it says so; the canvas was the offline fallback, and
  the site is read online. The suite has no network, so the map is driven from a local
  copy of the libraries (`tests/vendor.py`, `test_merged_controls`) and everything else
  from the handle alone. The map draws from the scene (`handle.built`), so it cannot show
  a different flight, and `scene.track` carries `t` (seconds since the first fix) for
  the replay.
  `map3d.py` keeps from MapLibre the whole planet, streamed tiles and the replay; and
  from the canvas the control bar and its keys, the sun and wind rose, the climb and
  glide labels, the airspace boxes and the imagery treatment. That last one is the
  canvas's hillshade *colours* — warm white (255, 252, 242) on sunlit slopes, dark blue
  (18, 26, 38) in shadow, lit from the sun's real azimuth and following the cursor —
  through MapLibre's `hillshade-highlight-color`/`-shadow-color`; its default black and
  white is what greyed the photograph. The DEM and the photograph are declared at
  `tileSize: 128` so MapLibre asks one zoom deeper (4x the tiles): at their natural size
  it picks a DEM ~4x coarser than the canvas's grid was and the relief reads flat. Two
  MapLibre facts the map honours: terrain is exaggerated **from sea level**, so
  anything drawn over it is `alt × vertical`; and deck.gl layers sharing a point fight
  for depth, so markers and labels draw with `depthCompare: 'always'`.
  **Esri's levels under 12 are a different, darker mosaic** (blue channel 26 against 59
  over the same Dolomites ground; levels 12-15 agree within 1%), so a map that ever shows
  them jumps colour as the zoom crosses the line. `TILE_SOURCES["satellite"]
  ["consistent_from"] = 12`, and the merged view builds tiles one and two levels under
  that from the level-12 tiles beneath them (a `m3tiles://` MapLibre protocol); only the
  far horizon, at three levels down and more, still uses the native tiles.
  The map's controls follow the canvas's: a left drag with shift, alt or meta
  turns and tilts as a right drag does (box zoom is off), labels are white with an
  outline over a coloured span, and the replay is one play button in the bar that opens
  a **from-to range** (two handles on one bar, full width) with play/pause and speed
  (10 s/s to 20 min/s) under it at the left. The track is drawn only between the handles
  — the left one hides the start of a flight that overlaps itself, the right one is the
  replay's "now" — by a `TripsLayer` per colour run with `trailLength = to − from` and no
  fade; climbs, phase labels and the landing follow the same window (each given the time
  of its nearest fix). Both handles at the ends is the whole track, a double click puts
  them there, and closing the replay does too. **Follow** (a button in the replay row,
  `c`) rides with the replay's "now", facing the *general* direction of flight, never the
  nose — turning with every thermal circle is unwatchable. The direction is the
  track smoothed out (`courseAt`): every 10 s, the bearing from 2.5 minutes before to 2.5
  after, which cancels the circles, *held* where under half the path over that window
  went anywhere — a climb drifting downwind would otherwise swing the view round and back —
  then averaged over ±2 minutes as vectors. The scored route's legs were tried first and
  were too coarse: an hour of flying in one fixed direction. The camera then eases to it in real time
  (0.7 s, and at most 90° a second), so a fast replay cannot snap it round. **The camera orbits the glider itself**:
  MapLibre orbits a point at the height of the terrain under its centre, and estimating
  where on the ground to look so a glider kilometres above lands mid-screen worked over
  Krupka and hunted over the Karakoram, where moving the centre onto a 7 km peak lifts the
  whole camera. So follow freezes the orbit height at the glider's altitude
  (`map._elevationFreeze` and `transform.elevation`, what MapLibre's own animations do —
  private, and 4.7.1 is pinned) and puts the glider below the middle with top padding;
  handing back re-anchors on the ground under the middle of the view and corrects the
  centre by however far the camera slid, so the view does not jump. Measuring the glider
  with `transform.coordinatePoint` was a dead end: it disagrees with where deck.gl draws
  it by ~190 px. While following, the wheel, a pinch, a double-click or double-tap and `+`/`−` zoom
  the follow camera — MapLibre's own zoom gestures would be stopped by its next frame,
  so these are taken from it — and only a drag (4 px of mouse, 8 px of one finger) ends
  following, not a press; and the arrows turn the view off the
  direction of flight (← →, 15°, kept as the flight turns) and tilt it (↑ ↓, 10°) without
  ending it — both the reverse of MapLibre's shifted arrows, at the reader's request: they
  move the camera round the glider (↑ lifts it, ← swings it left), not the view — and on a phone two fingers do the same: spread zooms, moving both up or down
  tilts (MapLibre's half a degree a pixel), a twist turns; a drag on the map, the rose or reset hands the camera back.
  **The offset and the course are eased apart**: the course follows the flight at its own
  rate (≤ 90°/s), the reader's offset settles in 0.15 s, and the offset is kept within
  ±180° (`wrapOffset`, moving the eased value by the same 360°). Eased as one bearing, a
  press during a turn was swallowed by the turn rate limit and the two fought; and an
  offset of 300° turned the long way round. Space plays and pauses anywhere in the view,
  and while the replay plays the screen is kept on (Wake Lock, re-taken when the page is
  shown again). With the replay open the side and top views' white cursor is not drawn
  on the map: the replay's own dot is "now" there, and the two read as one big dot. **The camera looks at the glider's mean
  position over ±45 s** (`steadyAt`), not the glider: locked to it the view swung round
  every thermal circle. Each step runs on an animation frame or, within 100 ms, a timer —
  a browser that stops serving frames to a page it thinks hidden froze the camera.
  **Measure** (ruler button, `d`): clicks are points, the readout the total and the last
  leg on the FAI sphere, Backspace and Esc; while measuring a click is nothing else.
  **deck.gl is interleaved** (`MapboxOverlay({interleaved: true})`), drawn in MapLibre's
  own pass against the terrain's depth: on a canvas of its own over the map, the track,
  the airspace walls and the route all showed through the mountains in front of them.
  Markers and labels keep `ON_TOP`. **Keys go to the follow camera from anywhere in the
  view** — the reader has just pressed the follow button, so that is where focus is.
  **The glider is held below the middle by looking ahead of it, never by padding**:
  MapLibre places the sky by the unpadded horizon, and with padding a band between the
  sky and the far terrain was drawn as nothing; and dropping the padding on hand-back
  shifted the whole picture down. The distance ahead is the pinhole solution
  `lift·C·m / (C·cos t + lift·sin t)` (C the camera-to-centre distance in pixels), since
  the glider is nearer the camera than the point looked at.
  **Missing tiles show a dark muted green** (`bg`, near the photograph's average) and
  fade in over 300 ms: the beige it was flashed against the dark ground every time the
  follow camera moved into tiles not yet fetched.
  **The airspace is glass** (`GLASS`, no depth write): drawn before the track and writing
  depth, the boxes hid every part of a flight inside them — over Krupka nearly all of it.
  **The shift-drag pivot is clamped into the canvas's box**, not the canvas container's,
  which has no height: every grab went to y = 0, the horizon, and an 80 px turn moved
  the map from Krupka to Leipzig. Climbs are dots, not
  numbers, and the track is the canvas's width (2.6 px over the device ratio, capped at
  2). **Ground and exaggeration are one cycling button each**, against the canvas's
  segmented groups, because the merged bar has to fit one row on a phone.
  **The hillshade is two layers with fixed paint** (light over imagery, strong on
  relief), switched by visibility too: changing one layer's paint between the two left
  tiles under the 3D terrain shaded the old way — white streaks down every slope after
  satellite, relief, satellite. Paint transitions are off for the same reason.
  **Basemaps switch by layer visibility, never `setStyle`**: every basemap is in the one
  style and hidden ones fetch nothing. Three quick `setStyle` calls left the map with no
  imagery and no terrain. And `setTerrain` waits for `style.load`, not `load` (which
  waits for every tile) and not `isStyleLoaded()` (false while any tile is in flight) —
  both lost an early x2 press and drew the track over ground still at x1.
  **A phone that locks or backgrounds the page takes its WebGL contexts and often never
  gives them back**: the map stays black while every button still answers. The map
  checks its canvases (`isContextLost`) when the page becomes visible again and
  1.5 s after MapLibre reports a loss, and rebuild themselves in place from a snapshot —
  camera, basemap, exaggeration, labels, airspace, the replay and its window
  (`window.__reviveMaps`, `api.lost/snapshot/dispose`). A rebuild takes its cursor
  wrappers back off the panel's handle, and builds the restored basemap and exaggeration
  into its first style: set over it before that style loads, MapLibre throws inside a
  promise and the rebuild silently never finishes. Not covered by a test; checked by
  hand with
  `WEBGL_lose_context`.
- **A declared task the flight did not fly is worse than no task at all.** A logger writes
  out whatever task happens to be loaded, so a `C` record is evidence of what was in
  XCTrack, not of what the pilot intended today. On `2021-07-06-XCT-ROP-01` the loaded
  task's turnpoints are **432 km** away, and comparing against it produced the loudest
  card on that flight's report — *"cost 33 525 m, the track left the planned line at
  13:31:08"*, median distance from the line **18 812 m**. Every plan comparison now goes
  through `plan.describes()`, which refuses a plan whose median cross-track error exceeds
  `STALE_MEDIAN_METRES`. The test is the **median**, not the closest approach: a flight
  that flew most of a task and then bailed sits near the line for most of its length, and
  that is the case the feature exists for. It knowingly does not catch
  `2020-08-16-XCT-ROP-01`, whose nearest real turnpoint is 29 km away but whose long
  first leg runs over the flying area — separating that from a genuine abandonment needs
  progress *along* the line, and two files is not enough to tune it on.
- **A polar that is not monotone is measuring the day, not the wing.** Sink must rise with
  airspeed; when it does not, the fastest bin wins the best-glide comparison by
  construction. On `2020-07-12` the report published *"your best glides came at about
  39 km/h, where the wing returned 10.3:1"* off a curve running 1.30 m/s down at 22.5 km/h
  and 1.05 at 38.8 — a pilot who flew fast in the good air, not a wing. `Polar.monotone`
  withholds `best_glide` and the report says why, rather than going silent: **18 of the 50
  sample flights** produce an inverted curve, so this is the common case on one flight and
  the strongest argument for calibrating against the archive.
- **XContest flight pages cannot be scraped.** The page is a JavaScript shell behind
  Cloudflare Turnstile with the IGC link only present for a signed-in session. We read
  the public title (pilot, date, scored distance) and tell the user to pass the file.
- **There is no XContest OAuth to integrate with, but there is an API-key programme.**
  Checked July 2026: no `.well-known` discovery document and no authorize endpoint on
  `www.xcontest.org`; `oauth.xcontest.org` resolves into the `xcontest.app` zone and
  answers only with Cloudflare's challenge (one path reached the origin and returned 522),
  so whatever backs the "log in with XContest" button on `startovne.online` is private to
  registered partners. What *is* documented and still live are two key-gated APIs
  (`?key=TEST` returns a structured `Invalid key` from both, not a challenge):
  `/api/gate/ticket/` + `/api/gate/request/` **submits** a flight, and `/api/js/?key=…`
  serves widgets including a `flight` detail view, locked to a registered website.
  Keys come from `info@xcontest.org`. Neither hands over an IGC file, and the Gate API
  authenticates the pilot with `sha1(md5(password)+…)` — asking a user for their XContest
  password is not something to build. Docs:
  `github.com/Iv/FlyHigh/tree/master/doc/xcontest.org`.

## Verification habits

The numbers are checkable, so check them:

- **Against igc2kmz** (`python2.7 ~/bin/igc2kmz/bin/igc2kmz.py -i F.igc -o out.kmz`):
  same 12 climbs and 11 glides on the reference flight, start times within 4 s.
- **Against XContest**: its page title carries the scored distance. On
  `20260728XCTOCH10.igc` it says 64.09 km and `js/xc.js` says 64.08 km.
- **Against the model**: the wind chart draws the model profile behind the measured
  per-thermal winds. Agreement there is evidence the drift method works, since neither
  source knows about the other.
- **Look at the output.** The validator checks colour, not layout. Render the HTML in
  headless Chrome and screenshot it; several real bugs (a 3012-unit `viewBox` from a
  shadowed variable, phase bands filling black after a CSS class was removed, a mirrored
  3D projection) were only visible that way. Measure the DOM when unsure rather than
  guessing:
  ```bash
  google-chrome --headless --disable-gpu --no-sandbox --window-size=1280,3000 \
    --screenshot=shot.png --virtual-time-budget=10000 page.html
  ```
  For WebGL add `--enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader`.
- **What needs a browser and not the map is probed from the DOM** (`tests/browser.py`,
  `_probe`): a panel over a synthetic DEM with the panel script alone, a snippet run
  against its handle, the answer written into an element and the DOM dumped — Chrome
  cannot be asked for the value of an expression. It skips when there is no Chrome and
  touches no network. **Timing is not asserted there**, because `--virtual-time-budget`
  does not advance the clock during synchronous work and every duration comes back zero.
- **The merged map is tested with real input** (`tests/test_merged_controls.py`): MapLibre
  and deck.gl, the pinned versions the page loads from its CDN, are cached once by
  `python -m tests.vendor` (a network step CI runs first) and served from localhost; the
  test drives Chrome over the DevTools protocol — mouse with modifiers, keys, wheel — and
  checks the shift-drag pivot, a plain pan, measuring, the glass airspace, follow and its
  hand-back. `PARAINSIGHTS_REQUIRE=…,maplibre` makes a missing cache an error, not a skip.
  It runs flat, without terrain (no network), so occlusion by ridges is not in it.
  Two headless facts it needs: Chrome counts the window as hidden unless told otherwise
  (`--disable-renderer-backgrounding`, `--disable-backgrounding-occluded-windows`), and
  even then serves animation frames only while something repaints, so its waits nudge
  `map.triggerRepaint()`.
- **No test reaches the internet, and that is enforced.** `tests/conftest.py` refuses
  any socket to a non-loopback address, and `CHROME_FLAGS` carries a resolver rule that
  resolves nothing but localhost. A page under test that points at a real tile server,
  CDN or image fails where it stands. The rule was found broken by the meteo page's
  flymet `<img>`, which every run fetched from flymet.cz; it is served locally now.
  `unshare -rn` runs anything without a network if you want to check by hand.
- **Why the suite takes minutes.** About 90 tests each launch a headless Chrome with
  software WebGL, and a few of them stall for 30-110 s on any given run (which ones changes
  run to run) — waiting, not computing: Chrome itself starts in ~1 s. The suite runs in
  parallel (`pytest-xdist`, `-n auto --dist loadfile` in `pyproject.toml`): 708 tests in
  5 min 46 s on four cores against 8 min 42 s serially. `-p no:xdist` or `-n 0` runs
  serially when a failure needs reading in order. One cost was not Chrome: `igc._timezone_from_position` built a fresh
  `TimezoneFinder` per parse, 1.6-1.9 s each; it is cached per process now.
- **Don't pipe a command whose exit code you care about** — `cmd | tail` reports tail's
  status, which once hid a `NameError` for two runs.

**One order across the site, and one theme switch.** `parainsights_common.PAGES` is the
order — meteo, planner, flights, which is the order a day happens in — and the
report's own view strip follows it too; it used to list its in-document views first and
its links after, so the report read *Flights, Airspace, Meteo, Planner* while every other
page read the other way round. Whether an entry is a button or a link is an
implementation detail of one document, and the reader should not be able to tell from the
order either.
The **theme toggle** lives in that strip on every page. `common.TOKENS` holds the colours
(three pages carried identical copies), `common.THEME_BOOT` applies the stored choice in
the `<head>` — after the first paint it is a white flash on a dark page, every time —
and `common.THEME_SCRIPT` flips `data-theme`, remembers it, and asks the canvases to
redraw (the meteo charts and the report's charts), because a canvas holds the tokens it
was painted with. Something worth keeping from the canvas 3D view's time: *a listener's
exception never reaches the `click()` that dispatched it*, so a redraw that throws leaves
a button that looks like it worked; a probe without a `window.onerror` collector cannot
see it. Two states, not three:
"follow the system" is a preference a reader has already expressed in their system.

## Design system

Charts follow the `dataviz` skill: climb rate is a diverging ramp (warm up, cool down,
grey midpoint), glide ratio a validated single-hue sequential ramp, phases a validated
categorical trio. Both light and dark themes are defined token-by-token, with
`prefers-color-scheme` **and** `data-theme` scopes so the viewer's toggle wins either
way. Palettes were checked with the skill's `validate_palette.js`; if you change one, run
it again — several candidate ramps failed on contrast or step spacing.

Reports carry their own charts as inline SVG and their own woff2, and fetch their
imagery. That is no longer the hard constraint it was — see "A network is assumed" — but
the charts stay local because a chart service that dies takes every graph with it, and
the font stays inlined because it is one request for a document's whole appearance.

## Wanted next

**Queued, in no particular order (October 2026), not started:**

- ~~**Planner and Airspace in one tab.**~~ **Done** — see "airspaces, in one paragraph".
- ~~**The planner on the merged 3D map**~~ **Done.** The airspace map sits in a
  `renderer-host` like a flight's. `map3d` learned what the page needs: a scene with
  rings and no `airspaceToggle` draws them always; it follows the handle's airspace
  filter (`setAirspaceFilter` is wrapped like the cursor calls, `handle.airspaceFilter()`
  gives the starting one); the exaggerations and the opening one are the panel's
  (×1/5/15 here); it opens on `view.focus` at the scene's pitch; and its entry in
  `__mergedAll` takes a route (`setRoute`) and reports clicks (`onClick`), announced to
  the panel as `merged-ready`. The planner's browser tests stand in for the map with
  those three members (`test_planner._MAP`).
  **FAI areas** (`faiArea`, on by default, merged map only — drawn by MapLibre as
  GeoJSON so they lie on the terrain, through `entry.setShapes`): xcplanner's convention
  (dkm/xcplanner `faiSector`), which pilots know — turnpoint 1 green, 2 blue, 3 red, each
  the area where *that* turnpoint can be with the other two where they are, on the side
  of the opposite leg it is on; with two turnpoints, the third's area on both sides. A
  closed course adds the yellow circle where the flight must finish. **The rules switch**
  — XContest world (20% closing, the report's) or ČPP, the Czech cup on XContest (5%
  closing; in the Central European zone flat ×1.8, FAI ×2.2, which is the zone assumed)
  — sets the closing test, the circle and the multipliers. Checked by
  hand over CDP with the network: merged at ×5 over Czechia, 745 boxes and 663 with the
  aerodrome zones unticked, three clicks a scored triangle.
- ~~**Only the merged map.**~~ **Done** (October 2026) — see "Only the merged map" under
  Decisions. The merged view's shift-drag turns about the ground grabbed: the
  modified-drag block in `map3d.py` unprojects the ground under the pointer (clamped
  into the middle half) and pans it back under the pointer after every step, in up to
  four passes because over terrain the centre's height moves with the pan — measured on
  the Col Rodella flight, a 64° turn and 15° tilt: **944 px** before, **0.6 px** after
  (`test_merged_controls`).
- ~~**An airgram on the meteo page**~~ **Done**: a third chart in each takeoff's column
  (`drawAir`), wind by hour (05-21, the meteogram's clock) and height (the same ceiling as
  both charts) from the profile already fetched — no new request. Speed is one hue over
  the panel (deepest at 15 m/s), direction an arrow pointing downwind every two hours and
  500 m, the boundary layer over it and the page's hour as a dashed line; the pointer
  reads the wind at the hour and height under it through `sampleProfile`, so the readout
  and the shading interpolate the same way (components, not angles). **The meteogram is
  folded into it**: cloud cover as grey over the wind, the ground, the boundary layer (on
  a halo, because the first takeoff's colour is blue over blue shading) and the
  cloudbase, both named at their evening end. Each column is the airgram and the sounding,
  side by side on one height scale for a single takeoff. The airgram reads on a tap and
  does not take vertical drags, so it is the column's strip to scroll the page from.
- **Every feature for an uploaded track, and JavaScript as the one runtime language for
  the viewer — done** (October 2026; Pyodide was considered and rejected). In four steps,
  each checked before the next: (1) the analysis ported to `js/` and held to the Python
  field for field by a parity harness — 63 of 63 IGC, 75 of 75 KMZ, the Open-Meteo reading
  on 106 cached answers, the glider classes over 35 739 register names; (2) the article
  ported (`report.js`, `charts.js`, `scene.js`), 63 of 63 identical, so an upload gets the
  showcase's article; (3) the showcase flights rendered by the same `compose` in Node at
  build time, identical with real ground and weather; (4) the Python analysis, the parity
  harness and `quicklook.py` deleted, and the Python test suite moved onto the JavaScript
  (`tests/js.py`). Two numbers worth knowing: the JavaScript takes 5-8 s on a long
  flight, which is why the report renders at build time rather than on arrival; and the
  timezone is tz-lookup, which gives timezonefinder's clock at all 136 sample take-offs.

Written up with a plan in `docs/plan.md`:

- ~~**Move some charts to the client.**~~ **Done, for the two that were worth it.** The
  side view and the top view are drawn in the page by `charts_client.py`; the document
  carries a payload instead of the SVG. Measured on a real 3 h 39 flight, the whole
  report goes **618 KB → 482 KB** — and on the published three-flight document it takes
  out nine profile SVGs (577 KB) and three plan views (153 KB), because the axis toggle
  used to ship all three modes and hide two.

  | | count | bytes | share of 2.97 MB |
  |---|---|---|---|
  | `chart` SVGs, side view (3 modes × 3 flights) | 9 | 577 KB | 19% |
  | `chart` SVGs, top view | 3 | 153 KB | 5% |
  | sparklines | 104 | 176 KB | 6% |
  | L/D bars | 119 | 16 KB | 1% |

  Three rules made it a renderer rather than a second design. **The browser builds the
  same SVG** — same elements in the same order, same classes, same `data-` attributes —
  so the linked cursor, the tooltip, the band highlight, "show me" and both themes go on
  working and the CSS is untouched; a browser test holds the DOM to that shape. **One sample, shared**: the trace is drawn through
  the very indices the cursor is indexed by, which is also why the payload is small —
  `_cursor_data` was already shipping altitude, climb and time at those indices, so the
  chart payload adds only distance flown, distance from launch and the plan-view metres.
  **Nothing is recomputed that the article already knows**: the clock labels for the time
  axis ship as data, worked out once in the flight's own timezone.
  Two consequences worth knowing. The axis toggle **redraws** instead of unhiding, so
  `initFlight` had to gain `root.__relinkCharts` — the cursor binds to the SVG that was
  there when it ran, and a replaced one is a chart the cursor cannot drive, which looks
  exactly like the cursor being broken. And the hosts reserve their height with
  `aspect-ratio`, because a chart landing 420 px tall into a 0 px box moves everything
  under it.

- ~~**The sparklines.**~~ **Done (October 2026), drawn in the page too.** The climbs
  table's "over time" column, one per climb: the climb rate from entry to exit in 22
  bars on the climb ramp. The article carries each climb's series as data
  (`data-climb`, every fix, to 0.1 m/s, written by `js/report.js`) and `charts_client`
  draws the bars. Not from the cursor sample, which is what the side view uses: it is a
  point every 14-45 s on the showcase flights, against 22 bars across a climb of a few
  minutes. On the published page the data is 122 KB where the drawings were about
  193 KB, 71 KB smaller in all.

Both `docs/ux-review.md` and `docs/analysis-plan.md` are now **implemented** — every phase
of each. What they describe is what the code does, so read them for the reasoning and this
section for what is left.

- **The debrief.** A verdict strip above the 3D view and 3–5 finding cards under it, ranked
  by cost measured against the flight's own budget. Three rules live in code, not in
  review: no finding is an imperative (a test greps for "should have"), every finding
  carries a cost in metres or minutes or it does not ship, and a finding whose data is
  missing returns `None` rather than an empty card. *Show me* drives the linked cursor.
- **The corrections.** The `other` slice is decomposed three ways and never published as a
  loss — on the reference flight it nets +385 m.
- **The air-mass frame, the DEM findings, the flight plan.** All landed (the archive did
  too, and went with the Python analysis);
  see the module table. Two of them are deliberately *not* debrief cards — a wind-corrected
  glide ratio and a lit slope are context, not costs — so they sit beside the sections they
  describe. That is the "no cost, no card" rule doing its job rather than being worked
  around.

Still wanted:

- ~~Calibrate `THRESHOLDS` against a real archive.~~ **Done** — see the known gaps below
  and `docs/analysis-plan.md`. Three thresholds that need a DEM, a sounding or a scored
  triangle per flight remain uncalibrated.
- ~~The glider's EN class, beside the glider name.~~ **Done**, from two registers,
  because neither is complete: the **DHV Geräteportal** (LTF *and* EN, back to the
  1980s, but its newest Ozone is a 2018 Buzz Z6 — Ozone stopped seeking a German
  approval) and **Air Turquoise**'s report list (the test house that runs most EN 926-2
  flight testing, so it has the current wings, but only the ones it tested). 6 240 rows
  in `gliders.py`, generated with `python -m tracklog_viewer.certification --refresh`,
  every one carrying the register and the reference it can be checked under. The page
  reads `gliders.json`, every answer precomputed from these rules by
  `certification.compact()`.
  **The matching is built to refuse — except across sizes.** `lookup` answers only when
  the maker and the model agree. A header names the wing and never its size, so where a
  model's sizes are certified differently it gives **the class most sizes carry**, a tie
  going to the class the M and L sizes share (October 2026, the pilot's call: it used to
  refuse, which left their UP Summit XC4 bare). The answer carries a `note` ("most
  sizes; EN C in S") that the chip's title and the report's paragraph print, so the
  reader is told which size it does not cover. A header that names a maker never falls
  through to another maker's wing of the same name (Sky and Edel both make an Apollo).
  There is no fuzzy match: "Rush 6" against "Rush 5" is one character and a whole class
  of wing. **`certification.SUPPLEMENT`** holds wings no public register lists, cited to
  what was read, and survives `--refresh`: the Summit XC4 is in neither register, and
  EAPR — the other house that issues LTF — closed its database, so its rows come from
  UP's manual and specification (S EN C, SM/M/L EN B).
  **LTF and EN are never translated into each other.** LTF 1-2 is *about* EN B and every
  pilot knows it, but "about" is not a certification, so a wing in the DHV register under
  1-2 and in Air Turquoise's under B resolves to the EN row, and an LTF-only wing prints
  "LTF 1-2". The *Klassenzusatz* — a class granted only with a particular harness —
  travels with the class, because dropping it silently widens someone else's approval.
- **Convergence as a third climb class.** `insolation.sources` labels ridge and thermal
  and deliberately stops there; the Python docstring at `ada5e5b` says why one tracklog
  cannot support the third.
- ~~The model wind profile behind the sounded wind, for a page built without
  `--meteo`.~~ **Done.** The wind chart (`js/charts.js`) publishes its axis mapping in
  `data-wind-frame` and each point carries the speed, altitude and direction it was
  placed from; `plotModelWind` in `render_html.SCRIPT` draws the profile the view-time
  fetch returned into the `<g class="model">` the article leaves empty. `__fetchMeteo` takes
  `{profile: true}` and adds the pressure levels to the same request — off by default,
  because an uploaded track has no chart to draw them in.
  **It is a rescale, not a plot, and that is the whole of it.** The measured winds are
  drift inside thermals and the model is the free air, so the model is routinely two or
  three times the fastest thing the glider felt: clipping it to the chart's existing
  axis draws a straight line up the right-hand edge and calls it a profile. So the axis
  grows and every measured point moves with it, which is what the point-level data
  attributes are for. An untouched chart is left byte-identical. The legend and the
  caption are rewritten too — the article wrote both for a report with no model in it, and a
  caption explaining the absence of a line the reader can see is worse than no caption.
  A flight older than the 60-day cutoff still gets nothing, because the ERA5 archive
  returns nulls on every pressure level, and the page leaves the chart and its caption
  alone rather than drawing an empty axis.

## Known gaps

- ~~`debrief.THRESHOLDS` is provisional and has never been calibrated.~~ **Calibrated on
  2026-08-15 against 63 IGC files** with a calibrator that ran on the Python analysis and
  went with it (`tracklog_viewer/calibrate.py` at `ada5e5b`); recalibrating means porting
  it to Node first. The rule the numbers now follow is
  *each threshold is the percentile of its own quantity that puts the card on no more
  than a third of flights*, and both the percentile and the measured rate sit in the
  comment beside every value. `docs/analysis-plan.md` has the before-and-after table.
  What it found: `other-slice` had **no gate at all** and fired on 94% of flights, and
  two thresholds sat *below their own median* — `gap_over_median` at 2.0 against a median
  2.82, so the "unusually long gap" was shorter than the typical longest gap. Three
  flights cannot show you that. Note that a percentile does not predict a card rate,
  because most findings carry a cost gate too, which is why the tool reports rates.
  **Three are still uncalibrated and are listed as such** rather than reported as fine:
  `low_clearance` and `ground_margin` want a DEM per flight, `ceiling_used` a sounding
  per flight (and ERA5 is surface-only past 60 days), `near_close` a scored triangle.
- **`public/index.html` is a committed build artifact — the report needs the IGC files
  and flight tracks stay out of this repository.** That is the trade, and it failed in a
  specific way: the renderer changed, nobody rebuilt, and the site sat weeks out of date
  behind a wall of green pipelines, because the deploy job only checked the file
  existed. Two things changed.
  **`ci/stale.sh` refuses to publish a report older than the code that renders it.** It
  asks whether the page’s last commit contains the last change to `tracklog_viewer`,
  `airspaces`, `parainsights_common` and `parainsights_map` — the report carries the
  Planner, the nav strip and the 3D map — and fails the pipeline when it does not. Ancestry
  rather than dates, because two commits in the same second compare equal. One file is
  excluded and the exclusion is checked rather than assumed: `airspaces/cli.py` is the
  *standalone* page's command line, and the report imports `airspaces.build`,
  `.openair`, `.render_html`, `.scene` and `.sources` — never `.cli`. It fired on a flag
  added to that file, which no report could contain. It cannot
  rebuild the page; it can refuse to publish one that does not match the code beside it.
  Run `sh ci/stale.sh` before committing a renderer change.
  **The other three pages are built in CI now**, every deploy. `meteo` needs nothing but
  its own committed data, so a failure there is a bug and fails the job. `airspace` and
  `planner` fetch from four public sources, and those are allowed to be down: the build
  is attempted, a failure prints a warning, and the committed page is published instead
  of nothing — refusing to publish a rebuilt *report* because someone else's CSV is
  unreachable is the wrong trade. `ci/download-link.sh` then checks the one link on the
  site that is not in the nav: the airspace page names its OpenAir file, the name carries
  the AIRAC date, and a half-finished rebuild leaves a button that 404s.
  **`--require-terrain` was what stopped a rebuild being a downgrade** — moot since the
  airspace map fetches its ground in the page (October 2026), kept as history. It existed
  because the first green deploy was one: the job could not build a DEM, `airspaces.cli`
  did what it is supposed to do for a person — fell back to the flat SVG map — and the
  job wrote that over the 3D page and reported success. The cause was worth the two
  deploys it took to find, and it was **not** the unreachable tile host everyone assumed:
  the tiles downloaded fine and `Pillow` was not installed, so not one of them could be
  decoded. `uv sync --extra terrain` in the deploy's `build` job, and `terrain.fetch(report=...)`
  so the next one says so out loud instead of shrugging. The flag
  turns the fallback into a refusal, and the refusal happens *before* anything is
  written, so the committed page and its sidecar both survive. Passing it is the
  pipeline's job; a person building offline still gets the flat map.
  Two things the first deploy taught, both in GitLab's job image (GitHub's runner has
  both, but a slim container would not): it has **no CA trust store**
  (`uv` bundles its own roots and Debian's mirror list is plain http, so everything works
  until the first `urllib` call, which then says `CERTIFICATE_VERIFY_FAILED`), and
  `--no-install-recommends` will not pull one in behind `git`. Install `ca-certificates`
  explicitly.
  The rebuild for the report is
  ```bash
  uv run python -m tracklog_viewer.cli \
    ~/Downloads/2018-09-28-XCT-OND-01.igc \
    ~/Downloads/2022-05-07-XCT-KVR-01.igc \
    ~/Downloads/flight-2026-06-16-04-46-04.igc \
    --terrain --meteo --airspace airspace/ \
    --label '' --label '' --label 'Antoine Girard|PK Hunza|OZONE Zeolite 2' \
    --html public/index.html
  ```
  — one `--label` per flight, in order, empty where the file already says it, and
  `--airspace` is where the OpenAir download sits *relative to the report*. Without
  `--terrain` the airspace view silently falls back to the flat SVG map. The current copy
  is 2.51 MB, down from 3.12 MB before the side and top views moved into the page.
- Historical weather is surface-only: the ERA5 archive returns nulls on every pressure
  level, so flights older than ~60 days get no sounding.
- ~~`quicklook.py` re-implements a subset of the analysis in JavaScript.~~ **Retired**
  (October 2026): an upload gets the full analysis from `js/`, checked against the Python
  field by field before the Python went. Two traps it found are kept in `js/igc.js`: B records
  carry only a time of day, so a file with no `HFDTE` is undated and its weather is
  refused rather than fetched for 1 January 1970; and XCTrack's `L`-record timezone blob
  drops its base64 padding, which `atob` refuses in the wrong *amount* where Python's
  `b64decode(validate=False)` ignores it — a blind `+ '=='` fails silently. The take-off
  timezone comes from `js/vendor/tz-lookup.js`; do not be tempted by `lon / 15`.

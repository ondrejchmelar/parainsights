# parainsights

Tools for paragliding. One repository, four tools, answering a question each:

| tool | the question | published at |
|---|---|---|
| **tracklog viewer** | how did that flight go? | `public/index.html` |
| **airspaces** | what is above me, and what does my instrument not know? | `public/airspace/` |
| **meteo** | is it worth driving anywhere today, and where? | `public/meteo/` |
| **planner** | what is that task worth, and what does it cross? | `public/planner/` |

```
parainsights/
├── CLAUDE.md              this file
├── pyproject.toml         one project, one venv, one test suite
├── tracklog_viewer/       IGC/KML/KMZ → analysis → HTML, KMZ, 3D map
├── airspaces/             Czech airspace + the airfields nobody else carries → OpenAir, map
├── meteo/                 the day's sounding against pgweb's essential takeoffs
├── planner/               a task drawn on the airspace it crosses
├── parainsights_common/   the one thing every page shares: the strip between the tools
├── ci/                    the checks the pipeline runs that are not tests
├── tests/                 pytest, 644 tests, no network
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
exists alongside `tracklog_viewer/geo.py` rather than importing it, because they are not
the same geodesy: the viewer works on the FAI sphere because that is what a scored
distance is measured on, and airspace is published against WGS84. That is the rule, and
it is about *geodesy and analysis*, where the tools genuinely disagree.

`view3d` is the exception that shows the edge of it. It is a **map widget** — hand it a
terrain grid, some imagery and a list of things to draw and it never asks what a flight
is — so `airspaces`, `meteo` and `planner` all use it rather than carrying a copy of
120 KB of JavaScript. The right end state is a third package holding it; what stops that
today is that `view3d.data()` and `cursor_track()` in the same module *are* flight code,
so it is a refactor rather than a move. Every such import is lazy, so no tool fails to
build because another is absent. Likewise `planner` reads its scoring constants from
`tracklog_viewer/xc.py` — a planner that scored a task differently from the report that
later measures the flight would be worse than no planner.

## Getting set up

The environment is [uv](https://docs.astral.sh/uv/)'s. It installs the interpreter as well
as the packages, so there is nothing to line up by hand:

```bash
uv sync --extra dev          # creates .venv on the pinned Python, from uv.lock
uv run pytest -c pyproject.toml     # 644 tests, ~6 min, no network
```

`-c pyproject.toml` matters when the repo sits inside another project — pytest otherwise
walks up and adopts the enclosing config.

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
uv run python -m tracklog_viewer.cli FLIGHT.igc --kmz flight.kmz         # Google Earth
uv run python -m tracklog_viewer.cli FLIGHT.igc --map map.html           # 3D map

uv run python -m airspaces.cli --openair CZ_airfields.txt  # aerodrome zones + okruhy for XCTrack
uv run python -m airspaces.cli --html airspace.html     # the airspace map, in 3D
uv run python -m airspaces.cli --report                # what built, and what did not

uv run python -m meteo.cli --html meteo.html           # the day, against every takeoff
uv run python -m meteo.cli --refresh-sites             # re-fetch sources.CHOSEN's takeoffs
uv run python -m meteo.cli --refresh-flymet            # re-read flymet's station map

uv run python -m planner.cli --html plan.html          # draw a task, score it
```

Only `--meteo` and `--terrain` touch the network. Everything else in the viewer is
offline. `meteo` and `planner` both need one at build time, and the meteo *page* needs
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
different limits are one red line on a flat map. **The airspace and planner maps open at
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

The same layer goes over **each flight's own 3D map** in the report, behind an `airspace`
switch that starts off — the flight is the subject there and the airspace is context, the
same call the phase labels make. Each flight gets only the zones reaching the box its
terrain was fetched for (`scene.layer`), so a flight in Pakistan carries no layer and no
button, and the report grows by the airspace it can actually draw. It needs `--airspace`
*and* `--terrain`.

## A network is assumed

**This was not always true and the code still remembers it.** Everything here was built
to run inside a published artifact, behind a policy that blocks every external host — and
that one constraint is why there is an embedded DEM, an embedded basemap, locally
rendered charts, a canvas 3D view instead of a map library, and an inlined font.

That assumption is retired. The site is GitLab Pages, the reader has a connection, and
the trade was never close: a fetched mosaic is 10–20 m a pixel where an embedded one can
afford 45, the detail layer makes it sharper again as you zoom in, and the file is half
the size. So **imagery is fetched at view time** in all three page-writing tools, and
`--embed`, which baked it in, is gone: nothing used it. The planner fetches its
**terrain** at view time too (`terrain.remote`, loaded by `view3d`'s
`initView3dWhenReady`). `--online` is still accepted and does nothing, so an old command
line still runs.

What is *not* retired, because it is still true and still worth keeping:

- the charts are rendered locally, because Google Image Charts died in 2019 and took
  every graph in igc2kmz's output with it;
- the font is inlined, because a font is one request for a document's whole appearance;
- the 3D view is a canvas and a shader rather than a map library, because that is what
  makes it embeddable in a report at all.

And two things now *require* a network at view time rather than merely preferring one:
the meteo page has no numbers of its own, and the imagery on every 3D map is fetched.
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

Publishing is a build and a commit — the site is `public/`, handed to GitLab Pages by
the `pages` job in `.gitlab-ci.yml`:

```bash
uv run python -m tracklog_viewer.cli FLIGHT.igc --terrain --meteo \
  --html public/index.html
git add public/index.html && git commit -m "Publish flight" && git push
```

Nothing server-side is involved — it is one static HTML file. The same file opened over
`file://` behaves identically.

## What the tool does

Reads a tracklog and answers a pilot's questions about the flight: how the climbs were
worked, what the wind was doing, how the glides went, what the air was like that day.

Test data: `~/Downloads/*.igc` (60 files: XCTrack, SkyBean SkyDrop, Flytec) with matching
igc2kmz KMZs. `~/bin/igc2kmz` is Tom Payne's original Python-2 tool — the ancestor of this
one, still runnable under `python2.7` as an oracle.

## Architecture

Analysis is one pass producing plain dataclasses; renderers consume only those. No
geometry in a renderer, no rendering in the analysis.

| Module | Responsibility |
|---|---|
| `igc.py` | IGC parsing. **Every logger quirk lives here and nowhere else.** |
| `kml.py` | Track out of KML/KMZ (`gx:Track`, timed placemarks) |
| `sources.py` | One entry point: file, URL, or XContest page → `Flight` |
| `geo.py` | FAI-sphere haversine distance, bearing, cardinals |
| `flight.py` | Derived series over a 20 s interpolated window |
| `analysis.py` | Phases, per-climb and per-glide stats, wind, time budget, the `other` decomposition |
| `metrics.py` | Tier-1 measurements over an `Analysis`: climb selection, working band, centring, gaps, concentration, day envelope, detour, lowest save |
| `debrief.py` | `Finding`, the ranking pass, and the one `THRESHOLDS` dict |
| `calibrate.py` | What those thresholds do to a real archive: firing rates and distributions |
| `certification.py` | The wing's LTF/EN class, matched against `gliders.py` — and refused when unsure |
| `airmass.py` | Wind field from the per-thermal soundings; corrected glides, circle wander, the empirical polar |
| `insolation.py` | Slope, aspect and sun incidence from the DEM and `sun.py`; ridge-or-thermal per climb |
| `baseline.py` | The pilot's archive: summary JSON per flight, percentiles behind `--archive` |
| `plan.py` | The declared task or a sidecar plan, and what the flight did against it |
| `xc.py` | Free distance through ≤3 turnpoints (own dynamic program) |
| `terrain.py` | DEM grid + height above terrain (AWS terrarium, keyless) |
| `basemap.py` | Satellite (Esri) or OSM tiles stitched to one embedded JPEG |
| `meteo.py` | The day's vertical profile (Open-Meteo) |
| `sun.py` | Solar position (NOAA), and the day tabulated for the 3D view |
| `charts.py` | All SVG charts, rendered locally |
| `charts_client.py` | The side and top views, drawn in the browser from the cursor's own payload |
| `view3d.py` | The 3D view: camera, gestures, tiles, track overlay — and a canvas 2D heightfield as the fallback |
| `view3d_gl.py` | WebGL heightfield, registered as a backend for `view3d.py` |
| `render_kmz.py` | Google Earth KMZ: LOD folders, balloons, animation, local charts |
| `render_map.py` | Richer 3D map (MapLibre + deck.gl); needs network at view time |
| `render_html.py` | The report; `quicklook.py` is its in-browser sibling |
| `quicklook.py` | Reduced analysis in JavaScript, for a track the reader supplies; its own DEM fetch and linked cursor |
| `cli.py` | Argument handling and orchestration |

## Decisions, and the reasons behind them

Read `docs/plan.md` for the full list. The ones most likely to be re-litigated:

- **Pressure and GPS altitude are separate series.** Baro is smooth and is used for
  vertical analysis; GPS is geometric and is used for display and anything compared
  with terrain. `Flight.baro_offset` reports the ISA discrepancy. Never mix them.
  **36 of the 60 sample files have no baro at all** — GPS-only is the common case.
- **Broken altitude is repaired, broken position is dropped.** igc2kmz drops a fix whose
  vertical speed exceeds 30 m/s; on GPS-only files that discards good horizontal track
  to fix a vertical glitch. A local-median despike costs 50 repairs where dropping cost
  122 fixes.
- **The DEM budget is 26 000 nodes** (17 000 per flight in a shared document). 2 600 was
  59×43 over an alpine box — every facet of the heightfield visible as a quadrilateral.
  A finer grid costs bytes, not frames, because the drape mesh is budgeted separately.
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
  in-page analysis all print m/s now, and `meteo.py` asks Open-Meteo for
  `wind_speed_unit=ms` so the model arrives in it too. **Ground speed stays km/h** — a
  pilot says "35 km/h" of a glide and "5 m/s" of the wind, and the glide table's speed
  column is unchanged.
  This closed a real bug rather than only changing a label. `airmass.field` built its
  vectors from `Wind.speed` (m/s) and then mixed in `meteo.wind_at()` (km/h) as the
  fallback for a flight with no circled climb — a modelled wind **3.6× too strong**, and
  a corrected glide ratio to match, on exactly the flights that had nothing better. One
  unit at rest is what makes that unforgettable: there is no conversion left to forget.
  The archive migrates on read (`baseline._in_metres_per_second`) rather than bumping
  `FORMAT`: the old key held the same measurement in another unit, and a format bump
  means "this file cannot be understood", which is not true of it.
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
- **`timezonefinder` is a hard dependency.** Only XCTrack ≥0.9.12 records a timezone;
  47 of 61 test files need the coordinate lookup.
- **Haversine, not the law of cosines** — `acos` loses precision at the ~7 m separations
  between 1 Hz fixes, which is what every derived series is built from.
- **Charts are rendered locally.** igc2kmz's Google Image Charts URLs died in 2019, so
  every graph in its output is a broken image. Don't reintroduce a network dependency
  into a chart.
- **KML colours are `aabbggrr`, and every colour in `render_kmz.py` goes through
  `kml_colour()`.** Writing `#eb6834` directly yields blue. That bug painted an entire
  track solid blue on Google Earth mobile, because the solid-colour folder drew last.
- **Assume a viewer may ignore `Region`, `visibility` and `radioFolder`, and make the
  fallback correct rather than removing the feature.** Google Earth mobile demonstrably
  ignores `visibility` (a folder marked hidden was what the user saw). Whether it honours
  `Region` was never established — the reported symptom was fully explained by the colour
  bug. So the three detail levels are ordered coarse → fine and the colourings within
  each end with climb: a viewer that honours `Region` draws one level, and one that
  ignores everything draws them all and the last painted is the right one.
- **Satellite imagery is the default basemap**, composited from Esri World Imagery plus
  its `World_Boundaries_and_Places` label layer — both keyless. A photograph tells a pilot
  what the ground under a climb was; a road map does not. Attribution to Esri/Maxar is
  required and is rendered on the map and in the caption.
- **Every basemap style the button offers is embedded**, unless `--online` says the page
  will have a network. Fetching tiles by default was tried and reverted: a published
  artifact cannot reach any host, so the toggle switched to nothing at all and the report
  had no imagery whatsoever. `tiles` carries templates only for styles that are *not*
  embedded. `--no-basemap` opts out of imagery entirely.
  When stitching from tiles, give each source layer **its own canvas** and composite in
  order at the end: the label layer is requested second and frequently answers first, so
  painting into a shared mosaic as tiles arrive makes z-order a race.
- **One tile level of improvement is worth a fetch; two is a 4x zoom of nothing.**
  Halving the visible box buys exactly one tile level inside a fixed tile budget, so
  `DETAIL_STEP = 2` meant the imagery stood still across a fourfold zoom. Measured on the
  fixture: a fetch at tile zoom 15 around view zoom 8, then nothing at 12, 16, 20 or 28 —
  the reader gets three and a half times closer and the ground only gets blurrier — and
  the next fetch at 40, the ceiling. That is what "the tiles stopped updating with zoom"
  was, and it was a threshold rather than a fault. At one level the ladder is 12, 13, 15,
  16, 17 and the worst plateau is 2.5x. The two things that keep this from being a
  fetching machine are untouched: `DETAIL_DELAY` of stillness, and a padded box so small
  pans ask for nothing.
- **The tile budget is what sets image quality, not the JPEG settings.** `MAX_TILES = 24`
  held every stitch to zoom 10 — about 80 m per pixel, which is why the draped imagery
  looked like a smear, and no `max_width` above the native 1280 px could help. 80 tiles
  reaches zoom 12 (~22 m/px) on a cross-country box; the runtime path allows 120 because
  it pays in requests rather than bytes. A single-flight report embeds both styles at
  zoom 12 (~550 KB); a multi-flight document pays that per flight, so it takes zoom 11.
- **The heightfield is WebGL; everything else about the 3D view is not.** `view3d_gl.py`
  registers a backend and `view3d.py` calls it in place of its per-cell drape. It is a
  seam, not a second viewer: one camera, one set of gestures, one tile stitcher, one set
  of probes. The backend *reads* `view` and `fit` by reference rather than owning a copy,
  which is what keeps `groundUnder()`/`holdGround()` inverting the same projection every
  gesture anchors through — measured agreement between the matrix and `project()` is
  1.1e-05 px. Consequences: the track, markers and cursor stay in 2D on the canvas that
  was already there (the GL canvas goes *behind* it, and the sky gradient moves with it);
  falling back is `renderer = null`; and `preserveDrawingBuffer` is on, without which a
  headless screenshot of the one view that most needs looking at comes back blank.
- **A depth buffer is the fix for folded cells, and the 2D path is still live.** One
  `drawElements` at 1.9 ms where the drape took 99 ms, drawing 25 600 cells against
  6 400 — and across a 105-camera sweep the 2D renderer folds cells at 27 of them and
  WebGL at none. But `drawTerrain`/`fillHull`/`texturedTriangle` are not dead code: they
  run on a browser without WebGL *and* after a `webglcontextlost`, so they are kept whole
  and there is a test that says so. The paragraph below is what that path still does.
- **The draped texture is filtered LINEAR, with no mipmaps.** Mipmapping the terrain
  looked obviously right and cost more than half the detail on screen: mip level comes
  from the *longest* texture derivative, and terrain is viewed at a grazing angle, so a
  low pitch blurs by the elongated axis in both directions. It reads as two faults with
  one cause — the imagery goes soft, and the terrain goes **flat**, because
  `shadedTexture()` bakes the hillshade into the texture being blurred away. Measured at
  zoom 4 / pitch 0.20 against the canvas renderer: 44% of its detail mipmapped, 64% with
  16× anisotropy, 98% with plain LINEAR. Anisotropy is queried and reported but not used.
  **Measure any change here on a real report** — the effect needs the ratio between
  texture resolution and projected ground scale that a real DEM and stitched basemap
  have, and it does not reproduce on synthetic test data.
- **A WebGL context is scarcer than memory.** A page gets about sixteen, and flights
  accumulate — so removing a flight calls `handle.dispose()`, which deletes the buffers
  and forces `WEBGL_lose_context`. Without it, adding and removing a few tracks exhausts
  the contexts and every panel silently drops to 2D. Context loss from any other cause
  falls back the same way rather than leaving a blank panel.
- **Painter's order has no depth buffer, so cells fold.** (The fallback path.) A cell whose projected quad turns
  inside out (a slope steeper than the pitch angle) cannot be drawn as a quad: textured
  affinely it smears into a wedge, filled as one path it renders as a bowtie — also a wedge
  — and skipped it leaves the sky showing, because nothing was painted behind it. It gets a
  flat hull fill, plus two *clipped, individually-affine triangles* when the camera is still
  (three points determine an affine map exactly, so a triangle is right even when the quad
  is not). 955 of 6 324 cells fold at the default camera and 1 834 zoomed in at low pitch,
  which is why this matters. Cells are also depth-sorted by `wy·cos p − wz·sin p` rather
  than walked by horizontal depth, which ignores height entirely.
- **The hillshade is baked into the texture, never drawn per cell.** Cells must overdraw
  their neighbours — a projected quad is not a parallelogram, so the affine texture fit
  leaves hairlines — and *any* semi-transparent tint drawn over that overdraw lands twice
  in the overlap. That is a dark lattice over the whole slab; matching the tint to a
  smaller extent gives every cell an untinted border, which is the same lattice again.
  The basemap raster and the DEM are both axis-aligned in lon/lat, so `shadedTexture()`
  composites the illumination into a copy of the image once, at grid resolution, and lets
  the browser interpolate it. Smoother, faster, and no artefact.
- **Overdrawing a texture cell means growing the source too.** Stretching the same slice
  over a 10% larger quad scales the imagery up inside each cell, so its content no longer
  lines up with its neighbour's and every boundary becomes a visible step. Grow the source
  rect and the destination by the same fraction about the same centre. This, not the
  shading, was the lattice that survived three attempts to fix it.
- **The drape mesh is a cell budget, and coarse while the camera moves.** (The fallback
  path — WebGL draws the whole grid every frame at the same cost either way.) Each cell
  costs a `drawImage`, so a mesh fine enough to hide its own quadrilaterals cannot run on
  every frame of a drag: `FINE_BUDGET` 5 200 cells settles in ~130 ms, `COARSE_BUDGET`
  1 800 keeps a drag near 45 fps, and a 180 ms timer after the last gesture swaps back.
- **Hillshade is stretched to the terrain's own lit range.** A fixed shading curve assumes
  alpine relief; over the 390–761 m of ground a Czech flight crosses, `lit` stays within a
  few hundredths of flat-ground illumination and the overlay does nothing, which is how a
  draped road map came out looking like a flat sheet. `litMid`/`litSpread` are measured
  once from the grid and the shading is normalised against them (and skipped entirely when
  the range is under 0.01, as on quicklook's flat plane).
- **The KMZ is written on demand, not embedded.** `--earth-link` puts it in the report as
  a data URI behind "Open in Earth" (~170 KB, first flight only); by default `--kmz`
  writes a file. The report is for reading; a copy of the same flight in a second format
  is dead weight in it.
- **Uploading your own track is the first tab, not the last.** The bundled flights are a
  showcase. The reader's own file is the product, so the `+ your track` tab leads and a
  note under the tabs says the analysis happens in the page.
- **Flights accumulate, and any of them can be removed.** An upload clones
  `<template id="ql-template">` into a new article with its own uid and appends a tab;
  every tab (bundled ones included) carries a `×` that removes both. Consequences worth
  knowing: nothing inside that template may use an `id` — two flights would collide — the
  tab strip is driven by **one delegated listener** on the strip rather than a listener per
  tab, because tabs appear at runtime, and removing an article must delete its entries from
  `window.__view3dAll`, each of which holds a DEM grid and a stitched image.
- **A tab is a wrapper, not a button.** It contains an open button and a close button, and
  a button inside a button is invalid HTML that browsers silently unnest.
- **Full-bleed needs the scrollbar measured.** `100vw` includes the scrollbar, so a
  `100vw` panel hangs off the layout viewport and anything anchored to its right edge is
  clipped. JS sets `--scrollbar` and the panel is `calc(100vw - var(--scrollbar))`. Note
  that `scrollWidth` reports the ink extent even when clipping prevents scrolling — test
  by calling `scrollTo(300, 0)` and reading `scrollX` back.
- **The hillshade is the real sun, and the sun follows the chart cursor.** The light was
  a fixed north-west lamp, which is a direction the sun is never in anywhere in the
  northern hemisphere, so the shading answered nothing a pilot asks. `sun.py` is the NOAA
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
  the light the long way round the compass. Re-lighting re-measures the lit range,
  re-bakes the draped texture and calls `renderer.relight()` to rebuild the vertex
  colours in WebGL — far too much for a mousemove, so it only fires once the sun has
  moved a degree, while the arrow reads the exact position and stays smooth. A sun below
  the horizon is held 3° up and labelled rather than drawing a black panel.
- **The sun and the wind are arrows on the canvas, not in the DOM.** Both are geographic
  bearings, so both have to turn with the view — a rose drawn in the DOM would agree with
  the terrain at one heading and lie at every other. They live in the corner of the 2D
  overlay and are drawn from `bearingToScreen`, which folds in the two conventions that
  cancel: `view.yaw` turns the world counter-clockwise and screen y grows downward.
  **The wind arrow points opposite `wind.from`** — the reported bearing is where the air
  comes from, the arrow shows where it is going, and drawing it along the bearing is the
  classic 180° error that still looks like a perfectly good arrow. `handle.rose()` exposes
  both angles so a test can fail on it instead of a screenshot not doing so.
- **An uploaded track fetches its own DEM, and CORS is why it can.** `quicklook.py`
  mosaics the terrarium tiles onto a canvas, reads the pixels back and decodes
  `R * 256 + G + B / 256 - 32768` — the same formula as `terrain.py`, written twice
  because there is no shared source between Python and the page. It works because the
  tiles carry `Access-Control-Allow-Origin: *`; without that the canvas is tainted and
  `getImageData` throws, which the code treats as *no DEM* rather than as an error, along
  with every other way a tile can fail. Budgets differ from the CLI's on purpose: 12 tiles
  rather than 20 (a reader waits through this one, and at ~320 m node spacing a zoom-10
  tile already over-samples the grid) and 16 000 nodes rather than 26 000 (that budget is
  bytes in a document; this grid is never serialised). Fetched **before** `initView3d`,
  because re-running it on a live panel binds a second set of pointer handlers and every
  gesture counts twice.
- **An uploaded track carries the same linked cursor a built report does.** It carried
  none: `initView3d` was handed a *null* cursor track, so the 3D map had nothing to
  follow, and the climb and glide rows had no position on them, so clicking one did
  nothing. "A lot of features don't work when I upload my own IGC" was mostly that one
  argument. `linkCharts` in `quicklook.py` now drives the side view, the top view and
  the map from one index, with the same behaviour as `render_html`: hover previews, a
  click *pins*, leaving a chart returns to the pin rather than clearing, and a pin uses
  `revealCursor` so the map pans until the marker is on screen.
  Two things do not carry over and are not oversights. The tooltip and the band
  highlight need the SVG charts; quicklook's are **canvas**, which is also why the
  charts are drawn once into an offscreen canvas and blitted — the cursor repaints on
  every pointer move, and re-running a five-hour track's segment loop at that rate is
  what makes a canvas chart feel heavy. And the decimated sample has to be built **once**
  and shared: `initView3d` indexes its cursor track by position in it while the charts
  and the table rows point at fixes, so two independently-computed samples put the
  marker on a different moment than the one under the pointer.
- **Full screen is the real Fullscreen API, and the in-page maximise is its fallback.**
  It used to be the fallback only, because `requestFullscreen` fails two ways at once in
  an iframe without the permission — a synchronous throw with no user activation, and a
  rejection without the permission — and the button appeared to do nothing. That reasoning
  held for a published artifact and stopped holding when Pages became the primary home:
  served from a host the API is granted, and it is what a reader means by full screen. So
  the button asks for it, and falls back to `.is-maximised` on a throw, on a rejection,
  *and* on an implementation that returns undefined and quietly does nothing — the third
  needs a check after a tick, which no amount of promise handling would catch. Everything
  downstream asks `panelIsFull()` and does not care which path won. A synthetic click is
  not a user activation, so a test can only reach the granted path by stubbing the API —
  which means the fallback is what a browser test exercises by default, and both are
  pinned in `tests/test_view3d_fullscreen.py`.
- **The report declares a doctype, and the full-screen canvas is measured from its
  panel.** These are one bug. Without a doctype the page is in **quirks mode**, where
  `document.documentElement.clientHeight` is the height of the whole *document* rather
  than of the viewport — and that is what `applyMaximisedSize()` sized the maximised
  canvas from. On a 4 316 px report, full screen produced a 4 316 px canvas inside an
  813 px panel: terrain drawn for a viewport five times too tall, the track overlay
  registered against a projection the GL canvas underneath did not share, and every
  gesture anchored through the wrong one. The controls stayed exactly where CSS put them
  and did nothing sensible, which is how it was reported. Both halves are fixed, and the
  second is the one that matters: the canvas is sized from `panel.clientWidth/Height` —
  the panel's padding box, which is the same box `inset: 0` gives the GL canvas — so no
  global can ever mean something different again. The panel is embeddable and does not
  own the document it lands in. `tests/test_view3d_fullscreen.py` runs the maximise
  probe in **both** modes for that reason; against the old code the quirks case reports
  a 3 021 px canvas in an 813 px panel.
- **The keyboard follows the map; the pointer follows the hand.** Bare arrows pan and
  shift + arrows rotate and tilt, matching the pointer, where it used to be the other way
  round — so holding shift turned a pan into a rotate on the mouse and a rotate into a pan
  on the keyboard, on the same panel. And `rotate-left` swings the ground *anticlockwise*,
  which is `view.yaw` **increasing** and the opposite sign to the orbit drag beside it.
  That looks like a bug in the source and is not: a drag is direct manipulation of a
  grabbed point, so pushing left spins the world clockwise, exactly as the twist gesture
  is deliberately opposite to the drag. A key grabs nothing, so it follows the map. Both
  are pinned by `tests/test_view3d_gestures.py`, which dispatches real `KeyboardEvent`s
  and measures where the ground ended up — reading the sign off the source is what got it
  wrong in the first place. Note that a shifted arrow moves `panX`/`panY` too, and that is
  not a pan: a turn anchors through `holdGround` so the ground under the middle of the
  view stays there, exactly as the orbit drag does.
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
- **Twist rotates the map, the orbit drag rotates the camera, and the two are opposite
  on purpose.** A twist is direct manipulation — the ground follows the fingers, so
  `view.yaw -= angleDelta(...)`. The minus is the whole point and it looks wrong: the
  finger angle is `atan2` in client coordinates where y grows *downward*, so a
  clockwise twist is a **positive** delta, while a positive `view.yaw` turns the scene
  **counter-clockwise**. Three sign conventions, two of which cancel; the gesture span
  the map backwards for its entire life because every test measured the magnitude of
  `dyaw` and never its sign. Dragging, by contrast, walks the camera (Google Earth's
  model, which pilots know), so the ground swings the other way — that is not a bug.
  Both senses are pinned by tests that dispatch real `PointerEvent`s.
- **A gesture anchors on the terrain it grabbed, not on the flat datum under it.**
  `world()` measures height from `dem.min`, so inverting the projection with `wz = 0`
  solves the *datum plane* — and the mountainside a reader puts the cursor on stands well
  above it, so the two are the same screen pixel and kilometres apart on the ground.
  Turning about the wrong one swings the view. Measured on the ridged fixture's 618 m of
  relief: the grabbed terrain slid **7.1 px on a 90 px orbit drag and 12.7 px on 180 px**,
  growing with the drag; an alpine flight carries several times that relief, which is why
  the report's map felt wrong to rotate while the airspace map — 1.4 km of relief across
  500 km of country — felt fine. `groundUnder` iterates onto the surface (three passes:
  datum guess, terrain height there, corrected northing; each pass corrects by the slope
  times the previous error) and returns the height *with* the point, so `holdGround`
  re-projects it where it is. The measurement to be careful with is the tautological one:
  asking whether the point the code chose to hold stayed put answers zero either way, so
  the test computes the surface point itself and measures *that*.
- **An orbit anchored at the edge of the canvas throws the view away, and the fix is
  where the pivot is allowed to be.** Turning about a point holds *that* point still and
  swings everything else around it by an amount proportional to its distance from the
  pivot — so grabbing near a corner puts the whole scene on a long lever. Measured on a
  30 px rotate: the middle of the view slides **2 px** anchored centrally and **45–88 px**
  anchored at the edges, which reads as the map jumping somewhere else. It is not a
  regression and never was one; it is what orbiting about a corner does. `pickAnchor`
  clamps the pivot into the middle half of the canvas (`ANCHOR_INSET`), which takes those
  same drags to 2 px and 21–50 px, and it is applied at **both** places an orbit can pick
  one — the `pointerdown` that normally wins, and the `pointermove` fallback for a gesture
  that arrived without one. The drag still follows the finger; only the point it turns
  about is kept off the lever's end.
- **A zoom with no pointer behind it anchors on the fit, not on the middle of the
  canvas.** The wheel anchors on the pointer and always did; the buttons and the `+`/`-`
  keys have no pointer, and they zoomed about `(W/2, H/2)` while `refit` centres the
  scene on `(W/2, 0.58H)` — the sky above a flight needs more room than the ground below
  it. Every point except that one pixel row therefore translated on each press, always
  the same way: **13 px per zoom-in on a 549 px canvas**, so five presses walked what the
  reader was looking at 60 px down the panel. It accumulates, which is why it reads as a
  fault rather than as a choice. `box()` returns the anchor's client position now, and
  `tests/test_view3d_gestures.py` holds a button zoom to a *pure magnification*: every
  point lands on `anchor + (before − anchor) × ratio`, measured at 1, 5 and 10 presses
  and at three world points, worst error 0 px. Predicting it that way needs no inverse
  projection, so the test measures the zoom rather than the probe — the first attempt
  measured `groundUnder`'s own 7 px of sampling error being magnified and looked like a
  drift that was not there.
- **Zoom anchoring is measured from the fit's anchor, not the canvas corner.** A point's
  screen position is `anchor + world·scale·zoom + pan`, and `refit()` puts the anchor at
  `(W/2, 0.58H)`. Dropping that term biases every zoom by `anchor·(ratio−1)`, which reads
  as the view diving towards the bottom-right on both wheel and pinch. Verified at three
  different cursor positions, error ≤ 0.1 px.
- **`handle.redraw()` paints synchronously; `draw()` schedules a frame.** Headless Chrome
  stops servicing `requestAnimationFrame` once the page goes idle, so a test that
  scheduled a frame and then measured the projection was reading numbers from *before* its
  own input. Every gesture measurement was wrong in the same invisible way — including one
  that "proved" the anchor was in the wrong place — until the test hook bypassed the
  scheduler. A chained rAF loop in probe code hangs outright under
  `--virtual-time-budget`; use `setTimeout` there.
- **The 3D canvas has no width/height attributes.** CSS sizes the box (`aspect-ratio`)
  and JS matches the backing store to it, capped at 2× pixel ratio; that is what lets the
  same code serve an inline panel and full screen.
- **`Region`/`Lod` saves drawing, not bytes.** All three levels are in the file either
  way; Earth just skips the ones whose on-screen size falls outside their pixel window
  (56 points when the flight is a thumbnail, 1 727 when it fills the window). Real
  streaming needs `NetworkLink`, which a self-contained KMZ cannot use.
- **A Document description is shown verbatim on mobile.** HTML tables go on a Placemark
  (`Flight summary`, at the launch point); the Document gets plain text.
- **Icons are generated, never hand-typed.** `_png()` writes them with `zlib` and
  `struct`. A hand-written base64 constant passed the PNG signature check, had a corrupt
  IDAT, and Earth drew a red X on every placemark.
- **The KMZ batches geometry, igc2kmz does not.** One `LineString` per colour run and
  three `Region`/`Lod` detail levels, against one placemark per fix: 125 KB and 2 534
  placemarks where igc2kmz produces 612 KB and 11 373 for the same flight (129 KB / 2 535
  with the three detail levels restored). Watch the
  integer division when sampling — floor division gave one animation placemark per fix
  on short flights, which is the very thing this avoids.
- **Test the KMZ against a real viewer.** Structure tests pass on files that look wrong
  in Earth: the colour inversion, the corrupt icon and the raw-HTML description all
  survived a green suite. There are now regression tests for each.
- **Two 3D views on purpose.** `render_map.py` is better but needs network at view time;
  `view3d.py` gives up the basemap library to be embeddable. Both share the climb ramp.
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
  `20260728XCTOCH10.igc` it says 64.09 km and `xc.py` says 64.08 km.
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
  For the 3D canvas add `--enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader`.
- **The 3D view is tested in a browser, because none of its claims are visible from
  Python.** `tests/test_view3d_gl.py` renders a panel over a synthetic DEM, runs a probe
  in it and reads the numbers back out of the DOM — Chrome cannot be asked for the value
  of an expression, so the probe writes into an element and the DOM is dumped. It skips
  when there is no Chrome, and it touches no network. Two habits from it:
  **the fixture is ridged on purpose** — a gentle DEM folds no cells and would let a
  do-nothing renderer pass, so there is a control test asserting the 2D path *does* fold
  on it; and **timing is not asserted there**, because `--virtual-time-budget` does not
  advance the clock during synchronous work and every duration comes back zero. Frame
  costs were measured over the DevTools protocol instead and written into `docs/plan.md`.
- **Don't pipe a command whose exit code you care about** — `cmd | tail` reports tail's
  status, which once hid a `NameError` for two runs.

**One order across the site, and one theme switch.** `parainsights_common.PAGES` is the
order — meteo, planner, airspace, flights, which is the order a day happens in — and the
report's own view strip follows it too; it used to list its in-document views first and
its links after, so the report read *Flights, Airspace, Meteo, Planner* while every other
page read the other way round. Whether an entry is a button or a link is an
implementation detail of one document, and the reader should not be able to tell from the
order either.
The **theme toggle** lives in that strip on every page. `common.TOKENS` holds the colours
(three pages carried identical copies), `common.THEME_BOOT` applies the stored choice in
the `<head>` — after the first paint it is a white flash on a dark page, every time —
and `common.THEME_SCRIPT` flips `data-theme`, remembers it, and asks the canvases to
redraw, because a canvas holds the tokens it was painted with. **`window.__view3dAll` is
an object keyed by canvas id, not an array** — `render_html` registers and deletes
handles by id so a removed flight takes its DEM and its stitched image with it — and an
`Array.forEach` on it throws. That throw taught something worth keeping: *a listener's
exception never reaches the `click()` that dispatched it*, so the button looked like it
worked, the theme changed, and only the 3D views quietly kept the old sky. A probe that
does not install a `window.onerror` collector cannot see it, and a report built with
`fetch_tiles=False` has no handles registered to fail on. Two states, not three:
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
  working and the CSS is untouched; a browser test compares the DOM element for element
  against `charts.altitude_profile`. **One sample, shared**: the trace is drawn through
  the very indices the cursor is indexed by, which is also why the payload is small —
  `_cursor_data` was already shipping altitude, climb and time at those indices, so the
  chart payload adds only distance flown, distance from launch and the plan-view metres.
  **Nothing is recomputed that Python already knows**: the clock labels for the time
  axis ship as data, because resolving the flight's timezone in a page is the trap the
  timezone gap warns about.
  Two consequences worth knowing. The axis toggle **redraws** instead of unhiding, so
  `initFlight` had to gain `root.__relinkCharts` — the cursor binds to the SVG that was
  there when it ran, and a replaced one is a chart the cursor cannot drive, which looks
  exactly like the cursor being broken. And the hosts reserve their height with
  `aspect-ratio`, because a chart landing 420 px tall into a 0 px box moves everything
  under it.
  `charts.altitude_profile` and `charts.plan_view` are still there, still tested, and
  are the reference the browser test measures against — but the report calls neither.

- **The sparklines are the remaining case, and they are the opposite one.** 104 little
  charts at 176 KB: each needs its own slice of the series, so a payload for them is not
  a payload the document already carries. Not attempted.

Both `docs/ux-review.md` and `docs/analysis-plan.md` are now **implemented** — every phase
of each. What they describe is what the code does, so read them for the reasoning and this
section for what is left.

- **The debrief.** A verdict strip above the 3D view and 3–5 finding cards under it, ranked
  by cost measured against the flight's own budget. Three rules live in code, not in
  review: no finding is an imperative (a test greps for "should have"), every finding
  carries a cost in metres or minutes or it does not ship, and a finding whose data is
  missing returns `None` rather than an empty card. *Show me* drives the linked cursor.
- **The corrections.** The `other` slice is decomposed three ways and never published as a
  loss — on the reference flight it nets +385 m. Dolphin flying is measured over all
  straight flight, cross-country speed over the scored route, glide ratio as a median.
- **The air-mass frame, the DEM findings, the archive, the flight plan.** All four landed;
  see the module table. Two of them are deliberately *not* debrief cards — a wind-corrected
  glide ratio and a lit slope are context, not costs — so they sit beside the sections they
  describe. That is the "no cost, no card" rule doing its job rather than being worked
  around.

Still wanted:

- ~~Calibrate `THRESHOLDS` against a real archive.~~ **Done** — see the known gaps below
  and `docs/analysis-plan.md`. Three thresholds that need a DEM, a sounding or a scored
  triangle per flight remain uncalibrated and are named as such by the tool.
- ~~The glider's EN class, beside the glider name.~~ **Done**, from two registers,
  because neither is complete: the **DHV Geräteportal** (LTF *and* EN, back to the
  1980s, but its newest Ozone is a 2018 Buzz Z6 — Ozone stopped seeking a German
  approval) and **Air Turquoise**'s report list (the test house that runs most EN 926-2
  flight testing, so it has the current wings, but only the ones it tested). 6 240 rows
  in `gliders.py`, generated with `python -m tracklog_viewer.certification --refresh`,
  every one carrying the register and the reference it can be checked under.
  **The matching is built to refuse.** `lookup` answers only when the maker and the
  model agree and *every certified size of that model carries the same class* — so
  Advance's Sigma 10, which is D in 21 and C above it, gets no chip at all rather than
  a class the pilot might not have been flying under. A header that names a maker never
  falls through to another maker's wing of the same name (Sky and Edel both make an
  Apollo). There is no fuzzy match: "Rush 6" against "Rush 5" is one character and a
  whole class of wing. On the 19 distinct wings in the sample archive it answers 13 and
  says nothing about 6 — two of those are genuinely not in either register, one is a
  logger writing `NKN`, and one is the Sigma 10 refusing on principle.
  **LTF and EN are never translated into each other.** LTF 1-2 is *about* EN B and every
  pilot knows it, but "about" is not a certification, so a wing in the DHV register under
  1-2 and in Air Turquoise's under B resolves to the EN row, and an LTF-only wing prints
  "LTF 1-2". The *Klassenzusatz* — a class granted only with a particular harness —
  travels with the class, because dropping it silently widens someone else's approval.
- **Convergence as a third climb class.** `insolation.sources` labels ridge and thermal
  and deliberately stops there; see its docstring for why one tracklog cannot support the
  third.
- ~~The model wind profile behind the sounded wind, for a page built without
  `--meteo`.~~ **Done.** `charts.wind_profile` publishes its axis mapping in
  `data-wind-frame` and each point carries the speed, altitude and direction it was
  placed from; `plotModelWind` in `render_html.SCRIPT` draws the profile the view-time
  fetch returned into the `<g class="model">` Python leaves empty. `__fetchMeteo` takes
  `{profile: true}` and adds the pressure levels to the same request — off by default,
  because an uploaded track has no chart to draw them in.
  **It is a rescale, not a plot, and that is the whole of it.** The measured winds are
  drift inside thermals and the model is the free air, so the model is routinely two or
  three times the fastest thing the glider felt: clipping it to the chart's existing
  axis draws a straight line up the right-hand edge and calls it a profile. So the axis
  grows and every measured point moves with it, which is what the point-level data
  attributes are for. An untouched chart is left byte-identical. The legend and the
  caption are rewritten too — Python wrote both for a report with no model in it, and a
  caption explaining the absence of a line the reader can see is worse than no caption.
  A flight older than the 60-day cutoff still gets nothing, because the ERA5 archive
  returns nulls on every pressure level, and the page leaves the chart and its caption
  alone rather than drawing an empty axis.

## Known gaps

- ~~`debrief.THRESHOLDS` is provisional and has never been calibrated.~~ **Calibrated on
  2026-08-15 against 63 IGC files**, and re-runnable:
  `uv run python -m tracklog_viewer.calibrate ~/Downloads` prints how often each finding
  fires and the distribution behind each threshold. The rule the numbers now follow is
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
  The tracklogs are still not in the repository — `*.igc` is gitignored — so the
  calibrator reads a directory you point it at and writes nothing.
- **`public/index.html` is a committed build artifact — the report needs the IGC files
  and flight tracks stay out of this repository.** That is the trade, and it failed in a
  specific way: the renderer changed, nobody rebuilt, and the site sat weeks out of date
  behind a wall of green pipelines, because the `pages` job only checked the file
  existed. Two things changed.
  **`ci/stale.sh` refuses to publish a report older than the code that renders it.** It
  asks whether the page’s last commit contains the last change to `tracklog_viewer`,
  `airspaces` and `parainsights_common` — the last two because the report carries the
  airspace layer and the nav strip — and fails the pipeline when it does not. Ancestry
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
  **`--require-terrain` is what stops a rebuild being a downgrade**, and it exists
  because the first green deploy was one: the job could not build a DEM, `airspaces.cli`
  did what it is supposed to do for a person — fell back to the flat SVG map — and the
  job wrote that over the 3D page and reported success. The cause was worth the two
  deploys it took to find, and it was **not** the unreachable tile host everyone assumed:
  the tiles downloaded fine and `Pillow` was not installed, so not one of them could be
  decoded. `uv sync --extra terrain` in the `pages` job, and `terrain.fetch(report=...)`
  so the next one says so out loud instead of shrugging. The flag
  turns the fallback into a refusal, and the refusal happens *before* anything is
  written, so the committed page and its sidecar both survive. Passing it is the
  pipeline's job; a person building offline still gets the flat map.
  Two things the first deploy taught, both in the job image: it has **no CA trust store**
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
- FAI/flat triangle scoring with multipliers is not implemented; `xc.py` does free
  distance only.
- Historical weather is surface-only: the ERA5 archive returns nulls on every pressure
  level, so flights older than ~60 days get no sounding.
- `quicklook.py` re-implements a subset of the analysis in JavaScript, but **it no longer
  keeps its own copy of the numbers.** `quicklook.constants()` emits one payload — the
  `analysis.py` constants, `flight.WINDOW` and `debrief.THRESHOLDS` — into the drop panel,
  and the script reads every threshold out of it. It hangs off the *panel* rather than a
  flight, so an upload into a report with no bundled flights still gets it, and it fails
  at load rather than falling back, because a page analysing a flight by rules of its own
  is the thing this gap is about. `tests/test_quicklook_analysis.py` moves
  `minThermalGain` in the payload alone and requires the page's answer to change; a page
  still holding a literal cannot pass it. One rule is knowingly *not* shared and is
  commented as such: the circling clause, because the page has no smoothed turn rate and
  `climb > 1` stands in for it.
  This is not hypothetical: the two had already drifted on *shape* rather than on a
  number. `analysis.py` condenses runs separated by less than `CONDENSE_THERMAL` before
  applying the minimum — a thermal briefly left and re-entered is one thermal — and the
  browser demanded one unbroken run instead. A climb gains height in surges, so an
  evening spent working a ridge printed "No climbs met the thresholds" in the page while
  the same file gave three climbs on the command line. `tests/test_quicklook_analysis.py`
  now uploads a surging climb and checks *both* implementations find it, which is the
  shape this gap wants: a fixture whose answer is asserted against Python, not a second
  copy of the rule.
  It also has to parse `HFDTE` itself: B records carry only a time of day, and treating
  that as an epoch put every uploaded IGC flight on 1 January 1970 — which the weather
  lookup then fetched the real 1970 weather for and presented as "the air that day".
  A file with no `HFDTE` is marked undated and the weather is refused rather than guessed.
- An uploaded track gets real terrain **where the page can fetch it**, and a flat plane
  where it cannot. `quicklook.py` fetches and decodes the terrarium DEM itself; inside a
  published artifact every host is blocked, the tiles fail, and the ground falls back to
  one plane at the flight's lowest point with the caption saying so. The clearance series
  now falls out of that grid: `addClearance` samples the ground under every fix
  (bilinear — nearest-node makes a glide's ground a staircase), the side view gains a
  ground fill and drops its floor to it, and one stat tile reports the lowest clearance
  over `metrics.airborne_window`'s window, using the same `ground_margin` from
  `THRESHOLDS` as the report's low-point card. **No DEM means no tile** rather than a
  clearance measured against the invented flat plane.
- Times in the quicklook tables now follow the flight's own clock, so an upload and a
  built report of the same file agree — they disagreed by the offset, 15:43 against
  17:43 on a Czech evening, which makes a reader distrust both. Two of the Python side's
  three sources are available in the browser: `HFTZN`, and the IANA name XCTrack hides
  in a base64 JSON blob split across dozens of `L` records, which `Intl` can use
  directly and which beats a fixed offset because it knows the day's daylight saving.
  **The third is not, and this is the remaining gap:** resolving a zone from the
  take-off coordinates needs `timezonefinder`'s dataset, which is not going in a page.
  That is the common case — XCTrack only started writing `os.timezone` in 0.9.12, and
  three of six sample files predate it — so those still read UTC. Honest, but wrong by
  an hour or two, and there is no browser API that fixes it. Do not be tempted by
  `lon / 15`.
  One trap worth keeping: the `L` chunking drops base64 padding, and `atob` throws on
  the wrong *amount* of it where Python's `b64decode(validate=False)` ignores the
  excess — so a blind `+ '=='` fails on any payload already a multiple of four. It
  fails *silently*, because the zone lookup catches everything and the table simply goes
  on printing UTC.

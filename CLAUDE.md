# parainsights

Tools for paragliding flight analysis. One repository, several tools; the first and
currently only one is the **tracklog viewer**.

```
parainsights/
├── CLAUDE.md              this file
├── pyproject.toml         one project, one venv, one test suite
├── tracklog_viewer/       the tool: IGC/KML/KMZ → analysis → HTML, KMZ, 3D map
├── tests/                 pytest, 181 tests, no network
└── docs/
    ├── formats.md         IGC and KML/KMZ format research, measured on real files
    └── plan.md            scope, decisions and status
```

A second tool goes in as a sibling package (`parainsights/<tool_name>/`) sharing this
`pyproject.toml` and `tests/`. If shared code appears, put it in `parainsights_common/`
rather than importing across tools.

## Getting set up

The environment is [uv](https://docs.astral.sh/uv/)'s. It installs the interpreter as well
as the packages, so there is nothing to line up by hand:

```bash
uv sync --extra dev          # creates .venv on the pinned Python, from uv.lock
uv run pytest -c pyproject.toml     # 181 tests, ~110 s, no network
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
```

Only `--meteo` and `--terrain` touch the network. Everything else is offline.

## Where the report is read, and what that costs

Three destinations, and the differences are not cosmetic:

| | published artifact | GitHub Pages / any host | local file |
|---|---|---|---|
| can fetch anything | **no** | yes | yes |
| imagery | must be embedded | fetched, sharp | fetched, sharp |
| terrain for an *uploaded* track | flat plane | real DEM possible | real DEM possible |
| weather for an uploaded track | fails, says so | works | works |
| report size (reference flight) | 1.1 MB | 0.5 MB | 0.5 MB |

A published artifact runs under a policy that blocks **every** external host, so anything
it shows has to be inside the file. That single constraint explains the embedded DEM, the
embedded imagery, the local charts, the canvas 3D view and the inlined font.

Build for a host instead with `--online`: nothing is baked in, the 3D view fetches tiles at
zoom 12–13 (10–20 m/px against the ~45 m/px an embedded image can afford), and the file is
half the size. **That is the primary home** — the site is GitLab Pages, published from
`public/` by the `pages` job in `.gitlab-ci.yml`:

```bash
uv run python -m tracklog_viewer.cli FLIGHT.igc --terrain --meteo --online \
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
| `analysis.py` | Phases, per-climb and per-glide stats, wind, time budget |
| `xc.py` | Free distance through ≤3 turnpoints (own dynamic program) |
| `terrain.py` | DEM grid + height above terrain (AWS terrarium, keyless) |
| `basemap.py` | Satellite (Esri) or OSM tiles stitched to one embedded JPEG |
| `meteo.py` | The day's vertical profile (Open-Meteo) |
| `charts.py` | All SVG charts, rendered locally |
| `view3d.py` | The 3D view: camera, gestures, tiles, track overlay — and a canvas 2D heightfield as the fallback |
| `view3d_gl.py` | WebGL heightfield, registered as a backend for `view3d.py` |
| `render_kmz.py` | Google Earth KMZ: LOD folders, balloons, animation, local charts |
| `render_map.py` | Richer 3D map (MapLibre + deck.gl); needs network at view time |
| `render_html.py` | The report; `quicklook.py` is its in-browser sibling |
| `quicklook.py` | Reduced analysis in JavaScript, for a track the reader supplies |
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

## Design system

Charts follow the `dataviz` skill: climb rate is a diverging ramp (warm up, cool down,
grey midpoint), glide ratio a validated single-hue sequential ramp, phases a validated
categorical trio. Both light and dark themes are defined token-by-token, with
`prefers-color-scheme` **and** `data-theme` scopes so the viewer's toggle wins either
way. Palettes were checked with the skill's `validate_palette.js`; if you change one, run
it again — several candidate ramps failed on contrast or step spacing.

Reports are self-contained: an inlined woff2, inline SVG, embedded DEM and basemap, and
no external requests at view time. That is a hard constraint, not a preference — a
published artifact runs under a policy that blocks every external host.

## Wanted next

Written up with a plan in `docs/plan.md`:

- **GitHub Pages, not a published artifact, as the primary home.** The artifact CSP is
  what forces embedded imagery, an embedded DEM and a flat plane for uploaded tracks, and
  it costs a real fullscreen too. On a host the report can fetch: `--online` already
  builds for that (zoom 12–13 imagery at 10–20 m/px against ~45, and half the file size),
  the terrarium DEM is CORS-open so an *uploaded* track could get real terrain, and
  Open-Meteo would work for it as well. Keep the embedded path — it is what makes the
  file work offline — but stop treating it as the default.
- **Move some charts to the client.** Inline SVG is **34% of the document** (1.16 MB of
  3.39 MB): 605 KB in 9 altitude profiles, 279 KB in 238 sparklines, 161 KB in 3 plan
  views. The trade is data against CPU, and for the profile it is close to free — the 3D
  payload *already* ships lon/lat/alt/climb per fix (338 KB), so the profile's polyline is
  a second encoding of data that is in the file twice. Sparklines are the opposite case:
  238 little charts would each need their own slice. Measure before moving anything.
- **The sun during the flight** — which slopes were lit and when they switched off. Cheap to
  compute and it answers questions a pilot actually has. Now cheaper than when it was
  written: with the heightfield in WebGL the illumination belongs in the fragment shader,
  which makes the time of day a slider rather than a rebuild. The hillshade still lights
  from the north-west, which is never where the sun is in the northern hemisphere.

## Known gaps

- FAI/flat triangle scoring with multipliers is not implemented; `xc.py` does free
  distance only.
- Historical weather is surface-only: the ERA5 archive returns nulls on every pressure
  level, so flights older than ~60 days get no sounding.
- `quicklook.py` duplicates a subset of the analysis in JavaScript. If the Python
  thresholds change, change them there too — there is no shared source for them.
  It also has to parse `HFDTE` itself: B records carry only a time of day, and treating
  that as an epoch put every uploaded IGC flight on 1 January 1970 — which the weather
  lookup then fetched the real 1970 weather for and presented as "the air that day".
  A file with no `HFDTE` is marked undated and the weather is refused rather than guessed.
- An uploaded track gets the same 3D view, but over a **flat plane**: the DEM is a tile
  fetch and a published page cannot make one. Imagery is attempted and arrives only when
  the page is opened somewhere with a network. Altitudes are the track's own, so the shape
  of the flight in the air is exact; height above ground is simply not available. Fetching
  and decoding the terrarium DEM in the browser would fix this for a hosted page — the
  tiles are CORS-open (`Access-Control-Allow-Origin: *`) — and is not written yet.
- Times in the quicklook tables are **UTC**. The Python side resolves a timezone from the
  logger headers or the coordinates; the browser version does not.

# tracklog viewer — plan

The first tool in the `parainsights` repository. See `../CLAUDE.md` for the repository
layout and the decisions a newcomer needs first.

Goal: IGC tracklog → (a) a KMZ for Google Earth, (b) a 3D browser view with a written
report. Both driven by one analysis pass. See `formats.md` for the format research.

## Architecture

```
tracklog_viewer/
├── igc.py          IGC → Fix arrays. All logger quirks live here and nowhere else.
├── flight.py       Flight model + derived series (numpy): speed, climb, TE-climb,
│                   progress, heading, turn rate, height above terrain
├── analysis.py     phases (thermal/glide/dive), per-thermal & per-glide stats,
│                   turns, wind, time budget, salient altitude points
├── sources.py      input dispatch: file, URL, or XContest page
├── kml.py          read a track out of KML/KMZ (gx:Track, timed placemarks)
├── xc.py           free-distance optimisation (own DP, no external binary)
├── meteo.py        the day's weather profile (opt-in, the only network feature)
├── terrain.py      DEM tile fetch + cache → ground elevation under the track  (todo)
├── charts.py       SVG charts, rendered locally (no external chart service)
├── render_kmz.py   KMZ writer: LOD folders, colour bands, balloons, animation  (todo)
├── render_html.py  self-contained SVG report — works offline and under a CSP
├── render_map.py   interactive 3D map (MapLibre + deck.gl + terrarium DEM)
├── cli.py          tracklog-viewer FLIGHT… [--html OUT] [--map OUT] [--json OUT] [--meteo]
└── tests/
```

The layer boundary that matters: `analysis.py` emits a plain serialisable result
(dataclasses → JSON). Both renderers consume only that. No geometry logic in the
renderers, no rendering concerns in the analysis.

Python 3.12, numpy for the series work. `lxml` or hand-rolled writer for KML —
hand-rolled is fine, the KML we emit is small and regular.

## v1 scope

Parity with igc2kmz, plus the insights it lacks. In order:

1. **Parser** — B/H/I/C/L records, both `HFDTE` syntaxes, midnight rollover, `LAD`/`LOD`
   precision extensions, validity flag, empty/junk headers, CRLF, UTF-8 headers.
   Timezone from `LXCTDEVICE` JSON (XCTrack) → `HFTZN` (SkyDrop) → coordinate lookup → UTC.
   Both altitudes kept separate; baro used for vertical analysis when present,
   GPS for display, with the ISA offset reported.
2. **Fix filter** — two classes of problem, handled differently. Broken time or
   position (non-increasing timestamp, ground speed > 100 m/s) ⇒ drop the fix.
   Broken *altitude* ⇒ keep the fix, repair the altitude against a local median.
   igc2kmz drops on vertical speed too, but 36 of 60 files are GPS-altitude-only and
   spiky, so that discards good horizontal track to fix a vertical glitch: on
   `2020-08-16-XCT-OND-01.igc` it costs 122 fixes where 50 altitude repairs suffice.
   Everything dropped or repaired is counted and reported, never silent.
3. **Derived series** over a ~20 s sliding window with interpolated edges:
   ground speed, climb, total-energy climb (`dz/dt + (v1²−v0²)/2g`), progress
   (straight-line ÷ flown distance), heading, turn rate.
4. **Phase detection** — the igc2kmz progress heuristic (>0.9 glide; <0.9 + climb
   thermal; <0.9 + sink dive), run-merging, and the same interest thresholds.
5. **Per-thermal stats** — igc2kmz's set (altitude gain, average/max/peak climb,
   efficiency = avg ÷ max climb, duration, start/finish altitude and time,
   accumulated gain/loss, drift direction) **plus**:
   - **number of turns** — integrate unwrapped heading change over the thermal,
     `turns = Σ|Δheading| / 360`; also turn direction (L/R), how many direction
     reversals, mean circle period and radius. Cheap once turn rate exists, and it is
     the number that tells you whether a climb was worked cleanly or scratched around.
   - **wind at thermal altitude** from circle drift: fit the drift of successive circle
     centres → speed and direction, per thermal → a wind profile for the flight.
6. **Per-glide stats** — distance, average L/D, average speed, height lost, plus
   headwind/tailwind component from the wind estimate above.
7. **Time budget** — % of airtime thermalling / gliding / diving, height gained per
   hour, climb-rate histogram.
8. **Height above terrain** from a DEM (`terrain.py`, cached tiles) — enables real
   terrain clearance and a sane ground profile under the altitude chart. igc2kmz has
   nothing here.
9. **KMZ renderer** — XContest's geometry hygiene (`Region`/`Lod` detail levels,
   batched `LineString`s per colour band, 5-decimal coordinates, sampled time points)
   carrying igc2kmz's content (colour-by-climb/altitude/speed/TE, shadow, animation,
   thermal/glide placemarks with `ExtendedData` balloons, altitude marks, local charts
   as `ScreenOverlay`).
10. **HTML report** — single file: MapLibre GL JS + deck.gl `PathLayer`/`TripsLayer`,
    3D terrain from the keyless AWS terrarium DEM, track drawn at true altitude and
    coloured by the same scales as the KMZ; below it the flight summary, thermal and
    glide tables, altitude/climb charts with a shared time cursor.

Deferred: FAI/flat triangle scoring with multipliers, photo placement, task/turnpoint
handling, multi-flight comparison.

## Weather

`meteo.py`, opt-in via `--meteo`, the only feature that touches the network. Cached under
`~/.cache/parainsights/`, and whatever is fetched gets embedded in the report, so the report
itself still makes no requests.

Two endpoints, because neither covers the whole range:

- **recent flights (≤ 60 days)** → the operational model with `past_days`. This is what
  makes reviewing *yesterday's* flight possible; the reanalysis lags by days.
- **older flights** → the ERA5 archive by date. It answers for any past day, but
  **returns nulls on every pressure level**, so an old flight gets surface fields only:
  cloudbase, CAPE, mixing depth, surface wind. The report then says the profile is
  unavailable for that date instead of showing an empty sounding.

Derived, because the raw levels are not what a pilot asks: cloudbase from the surface
spread (125 m/K), boundary layer top as an absolute altitude, and **thermal top** from
crossing a dry adiabat off the surface temperature against the model profile.

**Flymet is not usable for review.** `flymet.meteopress.cz/meteogram/<SITE>.png` serves
the current day's forecast image and has no archive: `TABOR_20260728.png`,
`20260728/TABOR.png` and `archiv/…` all return 404. Fetched on the morning of a flight
it would be useful for planning; the morning after it shows the wrong day.

The model wind profile is also drawn behind the measured per-thermal winds, which turns
the wind chart into a check on our own method. On the reference flight the two agree to
within a few km/h and mostly under 15° of direction — independent support for the
circle-drift estimate, since nothing in the flight data knows about the model.

## Decisions taken

- **3D in the browser: MapLibre GL JS + deck.gl, DEM from AWS terrarium**
  (`https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`,
  `encoding: 'terrarium'`) — no API key, works offline-ish via tile cache.
  Rejected CesiumJS: it can load our KMZ directly and does support `BalloonStyle` +
  `ExtendedData` substitution, but it ignores `Region`/`Lod` (so the LOD work buys
  nothing and long flights get slow) and its world terrain wants an ion token.
- **The HTML report reads the analysis JSON, not the KMZ.** One analysis, two
  renderers; the KMZ stays a pure output format.
- **Charts are rendered locally.** igc2kmz's Google Image Charts URLs have been dead
  since 2019 — every graph in the existing KMZs is a broken image.
- **No external optimiser binary.** If XC scoring lands, we implement it.
- **`timezonefinder` is a hard dependency, not optional.** It resolves 47 of the 61
  test files; without it most flights have no local time.
- **Haversine, not the spherical law of cosines.** igc2kmz uses `acos`, which loses
  precision at the ~7 m separations between consecutive 1 Hz fixes — exactly the
  distances every derived series is built from.

## Phases

Four, not three. `thermal`, `glide`, `dive` come from the progress heuristic; **`tow`**
is the launch climb, detected afterwards: it starts within 120 s of the first fix,
averages ≥ 1 m/s up, and is flown at under 1.5 turns per minute (a circled thermal runs
nearer three). It is excluded from the thermal statistics and from the wind estimate —
a straight climb drifts with the glider, not with the air, so leaving it in mislabels
both. On `20260728XCTOCH10.igc` this moves the flight wind from 11.6 km/h SE-contaminated
to 14.0 km/h from W, agreeing with all 11 circled climbs.

## The profile view: distance, not projection

The hero chart plots altitude against **distance flown**, with a toggle to **distance
from launch**. Both were arrived at by discarding something worse:

- An *oblique projection* of east/north/altitude looks like a 3D view but folds the
  trace back over itself on every return leg, which reads as a drawing bug rather than
  as information. Dropped.
- *Distance from launch* has the same folding problem on an out-and-return or a
  triangle — but there the folding is the point, since it stacks the outbound and
  homebound legs over the same ground so their heights can be compared. Kept as the
  non-default toggle.
- *Distance flown* only ever increases, so the axis can be labelled in kilometres and
  believed. Default.

The spatial picture belongs on the plan view, which also carries the scored XC legs.

## Inputs

`sources.load()` takes a path or a URL and returns a `Flight`:

- **`.igc`** — the canonical source. Full rate, both altitudes, real headers.
- **`.kmz` / `.kml`** — `kml.py`, reading `gx:Track` first, then timed placemarks
  (XContest's shape), and refusing a KML that holds only an untimed `LineString`.
- **URLs** to any of the above — downloaded and cached under `~/.cache/parainsights/`.
- **XContest flight pages** — recognised, and refused with an explanation. The page is
  a JavaScript shell behind Cloudflare Turnstile and the IGC link exists only for a
  signed-in session, so there is nothing to fetch without holding credentials. What we
  *can* read is the public title: pilot, date and XContest's own scored distance.

### A KML is not a substitute for the IGC

Measured on the same flight, IGC against XContest's KMZ of it:

| | IGC (1 Hz) | KMZ (14 s) |
|---|---|---|
| XC free distance | 64.08 km | 64.1 km |
| straight distance | 59.0 km | 59.0 km |
| distance flown | 89.4 km | 72.3 km |
| height gained | 5 943 m | 5 230 m |
| turns counted | 155 | **not resolvable** |

Distances between fixed points survive; anything that integrates along the track does
not, because 14 s sampling cuts the corner off every turn. **Turn counting is refused
outright above 5 s sampling** — a circle takes ~20 s, so the count aliases and comes
out low and confident. `TURN_RESOLUTION_LIMIT` enforces this, and the report says why
the columns are blank rather than printing a number that is wrong.

## Status

Done and tested (61 tests):

- `igc.py` — parser + fix cleanup. All 61 sample files parse, no failures, no warnings,
  timezone resolved 61/61.
- `geo.py` — FAI-sphere haversine distance, bearing, cardinals.
- `flight.py` — derived series over a 20 s interpolated window: speed, climb,
  total-energy climb, progress, unwrapped heading, turn rate.
- `analysis.py` — phases incl. tow, per-thermal stats with turn counting, wind from
  circle drift, per-glide L/D, time budget, climb histogram.
- `charts.py` — local SVG: altitude profile (two x-axis modes), plan view, barogram,
  budget bar, wind sounding, climb histogram, day sounding.
- `xc.py` — free distance through up to three turnpoints, by dynamic program over a
  distance-sampled track. Replaces igc2kmz's dependency on an external `olc2002` binary.
- `meteo.py` — the day's vertical profile, opt-in.
- `render_html.py` + `cli.py` — self-contained report, no external requests.

Validated against igc2kmz (python2, run as an oracle) on the reference flight: same 12
climbs, same 11 glides, start times within 4 s.

- `terrain.py` — ground elevation from the AWS terrarium DEM (keyless), cached, plus
  height-above-terrain per fix. Grids are budgeted by node count because they get
  embedded in the report.
- `basemap.py` — OpenStreetMap raster tiles stitched into one JPEG data URI, so the
  embedded 3D view can carry place names. A couple of dozen tiles per flight, cached,
  with a real User-Agent — a polite consumer of a donated service. **Attribution is
  mandatory** and the report carries it.
- `view3d.py` — **the 3D view that works inside a published page.** Canvas, no
  libraries, DEM embedded at build time. The heightfield is painted back-to-front from
  the farthest corner, which is exact for a regular grid seen from outside, so there is
  no depth sort and no z-buffer. Vertical exaggeration is adaptive — a 90 km flight
  through 2 km of air is 3 % of its own width and reads as flat at true scale — and the
  fit is recomputed per frame because yaw, pitch and exaggeration all change the outline.
- `render_map.py` — the richer interactive 3D map: MapLibre GL JS, deck.gl `PathLayer` and
  `TripsLayer`, terrain from the keyless AWS terrarium DEM, OSM basemap. **Cannot be an
  embedded artifact** — a strict CSP blocks the library and the tiles — so it is written
  as a standalone file to open in a browser. Two lessons paid for in debugging:
  `map.on('load')` may never fire when the style carries terrain, so the overlay is
  attached immediately instead; and `interleaved: false` avoids depending on the map's
  GL context being ready, at the cost of the track not being occluded by hills.
- `sources.py` + `kml.py` — input handling (see above).

Validated against igc2kmz (python2, run as an oracle) on the reference flight: same 12
climbs, same 11 glides, start times within 4 s. **The XC optimiser agrees with XContest
to 10 m** on that flight: ours 64.08 km, XContest's own page 64.09 km.

### Draping a map on a heightfield with canvas 2D

The map is clamped to the surface, cell by cell. Three attempts got there:

1. **One affine fit on a flat plane.** For a fixed altitude the projection is affine, so
   a single `setTransform` + `drawImage` maps the basemap exactly — but onto a *plane*.
   With the vertical exaggeration these views need, an exaggerated mesh and a flat floor
   separate visibly.
2. **North-south bands**, each fitted to its own mean ground height. Better, but
   neighbouring fits disagree at the joins and it stripes.
3. **Per mesh cell**, which is what ships. Each cell's own slice of the image is mapped
   onto the cell's parallelogram with `setTransform` + the nine-argument `drawImage` —
   no clip, no `save`/`restore`, one call per cell. A cell of a heightfield is not
   planar, so its fourth corner disagrees with the affine fit and hairline gaps open up;
   under each textured cell goes an opaque fill of that cell's **average** map colour,
   sampled once by letting the browser downscale the whole image to one pixel per cell.
   Gaps then show ground, not sky. Relief is a translucent lighten/darken pass on top,
   so the place names stay readable.

Everything that belongs *on* the ground — the track's shadow, the cursor's drop line —
is placed by bilinear sampling of the DEM at that position, not on the minimum-elevation
plane. On a plane it slides against the terrain as the view rotates, because it is
simply not where the ground is.

### The mirrored view

Screen y grows downward, so the northward axis has to be negated before it reaches the
screen. Without that the far edge of the terrain lands at the bottom of the canvas —
which is the same picture as looking from the north, and east and west come out
swapped. The terrain paint order follows from the same rotated coordinate
(`wy = x·sin(yaw) + y·cos(yaw)`): x grows with column and y *falls* with row, so the
sign of each contribution gives the iteration direction directly.

### 3D controls

Modelled on Google Earth, because that is what pilots already know:

| gesture | effect |
|---|---|
| left-drag | pan |
| right-drag, middle-drag, or ctrl/shift/alt + left-drag | rotate and tilt |
| wheel | zoom towards the pointer |
| one finger | pan |
| two fingers | pinch to zoom, twist to rotate |

Panning needed a screen-space offset (`view.panX/panY`) applied *after* the fit: the fit
recentres every frame, so without it the camera was welded to the middle of the flight.
Zoom anchors on the cursor by moving the pan by the same ratio about that point.

`initView3d` returns its `view` object on `window.__view3d` so a headless browser can
assert what a gesture did — a fingerprint of the canvas is too insensitive to trust, and
a mis-timed one had me chasing a control bug that did not exist.

### Touch

Two fingers mean pinch-zoom, one means rotate. A phone has no scroll wheel, so a
pointer-tracking map replaced the single-drag handler; without it the view could only be
rotated, never zoomed, on the device most likely to be used at a landing field.

### Two 3D views, on purpose

`render_map.py` is the better map — real basemap, real tiles, deck.gl, replay — but it
needs the network *when opened*, so a published page cannot contain it. `view3d.py` gives
up the basemap to gain exactly that: everything it needs is inside the document. Both
share the climb ramp so they read as one tool.

### One altitude chart, three ground axes

The barogram was deleted, not kept: altitude-against-time and altitude-against-distance
are the same quantity on near-identical axes, and two panels of it is one too many. The
side view now takes **distance flown** (default), **from launch**, or **time**, and it
inherited the barogram's phase shading, crosshair and meteo reference lines. Panel order
is 3D map first, then side view and top view together in one panel with titles, because
the map is the thing that orients you and the charts are what you read afterwards.

### True vertical scale in the 3D view

Terrain and flight share one vertical scale — they always did — but the scale itself is
now 1:1 with the horizontal, because height above ground is only readable if it is. The
cost is honest and unavoidable: a 90 km flight through 2 km of air is 2 % of its own
width, so the climbs are a few pixels tall. The height button cycles ×1 → ×2 → ×4 for
when the shape of the climbs matters more than their absolute height.

Map coverage was widened (0.12 → 0.35 of the flight's own extent) with the grid node
budget unchanged, so more context costs nothing to draw: each cell simply covers more
ground.

### The height multiplier, and why it did nothing

The ×N button was bound to a per-frame refit that measured the *exaggerated* outline —
so asking for ×2 zoomed the view out by exactly two, and the picture never changed. The
fit is now computed at ×1 regardless of the current setting, and the ground is held at
two thirds of the canvas rather than the whole scene being centred, so raising the
multiplier lifts the flight up the frame instead of pushing the terrain off the bottom.
The ladder is ×1 → ×2 → ×4 with the button reporting where it is.

### Reading your own track in the page

Reached by the **+** tab beside the example flights; loading a file replaces the view
rather than appending to the page.

`quicklook.py` — a deliberately reduced analysis that runs in the browser, because a
published page cannot call Python and cannot reach the network. It reads IGC, KML and
KMZ (the ZIP is inflated with the browser's own `DecompressionStream`, so no library),
derives climb and progress on the same 20 s window, splits phases with the same
thresholds, and draws a side view, a top view and a climbs table on canvas.

It now also does wind from circle drift, glides with L/D, the time budget, and free
distance through three turnpoints (a 220-point sample against the CLI's 400, so expect
a few tenths of a percent low: 59.8 km against 60.2 on the return flight). Weather is an
explicit opt-in checkbox that calls the same Open-Meteo endpoints — it works when the
page is opened locally and fails with a plain message in a published artifact, whose
policy blocks every external request. Terrain and basemap remain out of reach for an
uploaded flight, since both need tiles fetched at build time. Checked against the CLI on the same files: the 2021-07-03
IGC gives 130.6 km flown against 130.2 and 23 climbs against 22 (the browser version
skips the altitude despiking), and the XContest KMZ matches exactly — 72.3 km flown,
5 230 m gained, 12 climbs, turns correctly refused at 14 s sampling.

### Linked cursor

Every chart that can host the cursor publishes its own projected sample coordinates on
its hit rect (`data-px` / `data-py`), and one shared index drives a dot in all of them —
altitude profile, plan view, barogram and the 3D canvas. The projection maths stays in
the module that owns the chart; nothing is re-derived in JavaScript, which is how linked
cursors normally drift away from the thing they point at.

### What turn count does and does not say

Turns alone say how many circles a climb took, nothing about quality — the report used to
imply otherwise. Quality lives in **m/turn** (height per circle), **efficiency** (mean
climb ÷ best 20 s of the same climb), the reversal and radius columns, and a per-row
two per-row sparklines: **rates** (that climb's own distribution — one tall bar is a
steady climb, a wide spread is one that kept falling out of the core) and **over time**
(how the rate changed from entry to exit, on a *fixed* ±4 m/s scale so rows can be
compared; auto-scaling each row would make a weak climb look identical to a strong one). Glide ratio gets a
validated single-hue sequential ramp, double-encoded as bar length and shade.

### KMZ output

`render_kmz.py`. igc2kmz's content on XContest's geometry: colour by climb, altitude,
ground speed and total energy as a `radioFolder`; shadow on the ground and as a curtain;
climb and glide placemarks whose balloons pull statistics out of `ExtendedData`; the
scored XC route; altitude marks from `salient()`; time marks every five minutes; a
`TimeSpan` animation for the time slider; and a locally rendered barogram as a
`ScreenOverlay`.

Measured against igc2kmz on the reference flight: **125 KB / 2 534 placemarks against
612 KB / 11 373**. The savings come from three `Region`/`Lod` detail levels, one
`LineString` per colour run rather than per segment, five-decimal coordinates, and a
sampled animation.

`salient()` — the altitude-mark selector — is *not* a port of igc2kmz's recursive
largest-drop split. That port produced four marks for a flight with eleven climbs, so it
was replaced with prominence pruning: take the turning points, then drop the least
prominent until every remaining swing clears the threshold. Checkable by construction —
one hill gives three marks, and the count falls monotonically with the threshold.

Next: FAI and flat triangle scoring with multipliers, and thermal-by-thermal comparison
across a season.

## Validation

`~/Downloads` has 60 IGC files across XCTrack, SkyBean SkyDrop and Flytec, with
matching igc2kmz KMZs. `python2.7` is still installed, so old igc2kmz can be run as
an oracle: compare thermal/glide detection and per-thermal stats against it, and treat
differences as findings to explain rather than as failures.

Reference flight `20260728XCTOCH10.igc` (2026-07-28, Všechov, UP Summit XC4):
7 232 fixes, 1 Hz throughout, all valid, 10:53:32–12:54:03 UTC (2 h 00 m 31 s),
89.5 km flown, 59.0 km straight-line, baro 410–2102 m, GPS 491–2227 m.
Good smoke-test target: parser, phases and turn counting must all be sane on it.

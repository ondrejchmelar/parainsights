# tracklog viewer — plan

The first tool in the `parainsights` repository. See `../CLAUDE.md` for the repository
layout and the decisions a newcomer needs first.

Goal: IGC tracklog → (a) a KMZ for Google Earth, (b) a 3D browser view with a written
report. Both driven by one analysis pass. See `formats.md` for the format research.

## The map gets sharper as you zoom in

The base mosaic is stitched once over the whole terrain, so its resolution is whatever a
120-tile budget reaches across that box — about 20 m a pixel on a cross-country flight
and about **300 m a pixel over a whole country**. Zooming in magnified exactly those
pixels: the view got closer and the ground got blurrier, which is the opposite of what
zooming is for, and it was the one thing that made the airspace map feel like a picture
of a map rather than a map.

So once the camera settles, `detailPlan()` asks whether what is on screen is a small
enough part of the terrain that a finer tile zoom would fit in 48 tiles. If it is, a
second mosaic is stitched over just that box and handed to the renderer as a **detail
layer**: the fragment shader samples it where it covers and the base image everywhere
else, feathered over 3% of its width so the boundary between two zoom levels is not a
rectangle drawn across the ground. Measured on the published airspace map: base zoom 9,
detail zoom 11 after one press of the zoom button — place names and field boundaries
where there had been a smear.

Four decisions worth keeping:

- **The UV attribute became a geo attribute.** It used to be built against the *image's*
  box and rebuilt every time a mosaic finished; it is now the node's place in the DEM's
  own box, built once, with each image's box arriving as a `vec4` uniform. That is what
  makes two images at once cheap rather than a second vertex buffer.
- **The detail patch is shaded like the base.** `shadedTexture()` bakes the hillshade in,
  and an unshaded patch reads as a flat rectangle laid over hillshaded ground — the
  terrain looks *wrong*, not merely different, because relief is what carries its shape.
- **It fires on stillness, wants two zoom levels of improvement, and pads the box it asks
  for.** Without all three it is a tile-fetching machine: the padding is what makes a
  small pan ask for nothing.
- **A failed detail fetch changes nothing the reader can see.** It does not take over the
  spinner or the credit line, and the base image is still underneath. That is the whole
  reason it is a second fetch rather than a re-fetch.

**The 2D fallback does not have it.** `drawTerrain` drapes one image, and giving it two
means choosing per cell which image and which source rect. The fallback exists for a
browser without WebGL and for the seconds after a context loss; it is not where anyone
looks at terrain closely.

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
   - **number of turns** — full revolutions of the unwrapped heading (not `Σ|Δheading| /
     360`, which counts a wingover; see *What turn count does and does not say*); also
     turn direction (L/R), how many direction reversals, mean circle period and radius.
     Cheap once turn rate exists, and it is the number that tells you whether a climb was
     worked cleanly or scratched around.
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

Deferred: photo placement, task/turnpoint handling, multi-flight comparison. XContest's
scoring multipliers are **done** — see *Matching XContest* below.

### WebGL for the 3D view

**Done.** `view3d_gl.py`. The heightfield is one `drawElements` against a 24-bit depth
buffer, and the fold artefacts are gone rather than mitigated.

**Why it was the answer.** The artefacts were cells whose projected quad turns inside out,
and they existed because canvas 2D has no depth buffer — painter's order was the only tool
available and no per-cell treatment is correct (the four that were tried, and how each
failed, are under *Wedges on a zoomed-in view*). A depth buffer removes the problem instead
of mitigating it: there stops being such a thing as a folded cell, only triangles that
resolve per pixel.

**Why it was allowed.** WebGL needs no external script — shaders are strings in the document
— so it works under the content-security policy that rules out MapLibre and deck.gl. That
policy is the single constraint behind every decision in `view3d.py`, and it does not apply
here. Confirmed in the browser: `webgl2`, `depthBits=24`, `MAX_TEXTURE_SIZE=8192`.

**It is a backend, not a second viewer.** The plan called for a parallel module exporting
its own `data()`/`panel()`/`SCRIPT`. Built that way it would have duplicated ~1 100 lines of
JavaScript — the gestures, the tile stitcher, the basemap cycling, the maximise logic, every
probe — for the sake of one function. So `view3d.py` gained a seam instead: it builds a host
object and calls `window.__view3dBackend`, and with nothing registered the per-cell 2D drape
runs exactly as before. Three things fall out of that which the parallel design would have
had to earn:

- **The camera is not reimplemented, it is read.** `view` and `fit` are held by reference and
  the matrix is derived from them each frame, so `groundUnder()`/`holdGround()` keep
  inverting the same projection every gesture anchors through. Step 3 of the original plan
  asked for bit-compatibility here; this makes it identity. Measured: the matrix and
  `project()` agree to **1.1 × 10⁻⁵ px** on a real DEM and 9.5 × 10⁻⁷ px on a flat plane.
- **The track overlay was already there.** The canvas in the markup keeps the track, the
  climb markers and the cursor in 2D and keeps every pointer handler; the GL canvas is
  inserted *behind* it and the sky gradient moves with it. No second canvas to build, and
  `initFlight`'s chart linking never learns any of this happened.
- **Falling back is one line.** `renderer = null` and the 2D drape resumes — which is what
  runs after a `webglcontextlost`, not only on a browser without WebGL.

**What it bought, measured on the Blatná flight (161×161 DEM), Chrome under swiftshader —
so a real GPU is faster still.** `redraw()` is synchronous, so these are frames and not
scheduled callbacks:

| camera | canvas 2D | WebGL |
|---|---|---|
| default (zoom 1, pitch 0.46) | 99 ms, 6 400 cells | **1.9 ms, 25 600 cells** |
| zoom 4, pitch 0.20, settled | 33 ms | **3.0 ms** |
| zoom 4, pitch 0.20, dragging | 8.8 ms (coarse mesh) | **3.0 ms** |

Two things in that table matter as much as the numbers. The GL column draws **four times as
many cells** — the whole DEM the report already carries, where the 2D renderer spends its
`FINE_BUDGET` on a quarter of it. And the settled and dragging rows are the same, which
retires `FINE_BUDGET`/`COARSE_BUDGET`/`moving()` as a concept: there is nothing left to
trade.

**Artefacts, swept rather than spot-checked.** 105 cameras (7 pitches × 5 zooms × 3 yaws).
On the Blatná flight the 2D renderer folds cells at 27 of them, 395 in total; on the ridged
test fixture, 16 432. WebGL folds at **none of the 105**, on either. `stats().folded` is
still the probe — it now answers from the backend, and its answer is structurally zero.

**Also fixed on the way past.** Bare relief is shaded per *vertex* and interpolated by the
rasteriser, so the facets the 2D version showed on a coarse mesh are gone for free.

**The draped texture is filtered LINEAR, with no mipmaps, and that was a correction.**
Mipmapping looked obviously right and shipped in the first version, where it cost more than
half the detail on screen. Terrain is looked at from a grazing angle and mip level is chosen
from the *longest* texture derivative, so at low pitch an isotropic lookup blurs by the
elongated axis in both directions and throws away the short one, which is where the detail
is. It arrived as two complaints with a single cause — the imagery went soft, and the
terrain went **flat**, because `shadedTexture()` bakes the hillshade into the very texture
being blurred away. Laplacian variance of the panel at zoom 4 / pitch 0.20, against the
canvas renderer:

| filtering | detail vs canvas 2D | near ground |
|---|---|---|
| mipmapped, isotropic | 44% | 37% |
| mipmapped, 16× anisotropic | 64% | 62% |
| **no mipmaps (ships)** | **98%** | **101%** |

Anisotropy recovers only about half of it on a software rasteriser, so it is queried and
reported but not used. LINEAR is exactly what the 2D path does, which is the useful
property: this renderer cannot come out blurrier than the one it replaces. The lesson is
narrower than "don't mipmap" — it is that a filtering change here has to be *measured on a
real report*, because the effect needs the ratio between texture resolution and projected
ground scale that a real DEM and a stitched basemap have. It does not reproduce on synthetic
test data, which is why `tests/test_view3d_gl.py` guards it by reading the texture's
`TEXTURE_MIN_FILTER` back out of the context rather than by a sharpness threshold, and says
so.

**What was watched out for, and what it cost.** `preserveDrawingBuffer` is on: it is off by
default, and a screenshot taken outside the draw call then comes back blank — which would
have made "render it and look at it" impossible for the one view that most needs it. Context
loss is handled by falling back rather than by fighting it. And a page gets only about
sixteen WebGL contexts while flights *accumulate*, so removing a flight calls
`handle.dispose()` and hands its context back; without that, adding and removing a few
flights would silently downgrade the whole document to 2D.

**Not retired, deliberately.** `drawTerrain`, `fillHull`, `texturedTriangle`, `convex` and
the depth sort all stay in `view3d.py`. They are no longer the common path but they are a
live one — after a context loss they are what the reader gets — and there is a test that
says so.


### The sun during the flight

**Done.** `sun.py` — the NOAA solar position algorithm — plus a slider in the 3D view that
re-lights the terrain from any time of day. The hillshade was a fixed north-west lamp,
which is a direction the sun is never in anywhere in the northern hemisphere, so it
answered none of the questions a pilot actually has:

- **which slopes were being lit**, and when they switched off. The east faces work first
  and die by mid-afternoon; the classic mistake is arriving at a west face an hour before
  it starts working. Dragging the slider is the answer, and the caption under the view
  states sunrise, sunset, and where the sun stood at launch and at landing.
- **whether a climb was thermic or convergence**: a good climb on a slope that had been in
  shadow for two hours is not sun-driven.
- **how much of the day was left**, against the flight's own clock.

**The day travels as a table, not as an algorithm.** 144 samples of azimuth and elevation,
one every ten minutes, under 2 KB. Porting the solar position into JavaScript would put a
second implementation in the document, and `quicklook.py` is the standing lesson in what
that costs — every threshold duplicated there is a thing that can drift. A table cannot
drift. The page interpolates linearly between samples, which is why `day_track` **unwraps**
the azimuth: interpolating across a wrap at 360 sweeps the light the long way round the
compass, and on a slider that reads as the sun bolting backwards through the whole sky.

**The sun follows the chart cursor, and there is no time control.** Hovering the altitude
trace at 14:40 lights the terrain as it was at 14:40 — the question and the instrument are
the same gesture. A slider was built first and was wrong twice over: it offered hours the
flight never saw, and it made the reader hunt for a moment the charts were already
pointing at. The cursor track carries a UTC minute per sample for this (carried, not
interpolated from the flight's span — fixes are not evenly spaced in time, and a KMZ from
a scoring site is not evenly spaced at all). Leaving the charts returns the light to
mid-flight, which is what the view opens on: the light the day was actually worked in.

**Re-lighting is not free, and a hover fires far more often than a drag.** Moving the sun
re-measures `litMid`/`litSpread` against the new light, re-bakes the draped texture on the
host side, and calls `renderer.relight()` so the WebGL backend rebuilds its vertex colours
through `bufferSubData` — a pass or two over the grid plus one over the texture, which is
nothing once and far too much per mousemove. So the shading only rebuilds once the sun has
moved a degree of azimuth (about four minutes of a summer afternoon, and a third of the
width of the sun's own disc). The **arrow** reads the exact interpolated position every
frame, so it tracks the cursor smoothly while the shading catches up in steps nobody can
see.

**The arrows are drawn on the canvas.** A rose in the corner carries the sun and the wind,
and both turn with the view — they are geographic bearings, so a widget in the DOM would
agree with the terrain at one heading and lie at every other. `bearingToScreen` folds in
the two conventions that cancel (a positive `view.yaw` turns the world counter-clockwise;
screen y grows downward). The wind arrow points **opposite** `wind.from`: the reported
bearing is where the air comes from, the arrow shows where it is going, and drawing it
along the bearing is the classic 180° error — which still looks like a perfectly good
arrow, so `handle.rose()` exposes both angles and the test fails on the number instead. Below the horizon the sun is held 3° up
and the label says "sun down" — there is no night mode, because a black panel answers
nothing.

Two omissions, both deliberate: no atmospheric refraction (half a degree at the horizon,
nothing above 10°, and this is a geometric question), and no topographic horizon — the sun
"rises" when it clears the sea horizon, not when it clears the ridge to your east. A real
answer to the second would march the DEM along the bearing, and the view already draws the
terrain's own shadows.

Validated against a second algorithm rather than against itself: `tests/test_sun.py`
carries the Astronomical Almanac's low-precision solar position, which goes through right
ascension and sidereal time where `sun.py` goes through the equation of time, and the two
agree within half a degree at five places from Prague to Sydney. The geometry is pinned
separately — equinox noon at 90° minus your latitude, the solstices a tilt either side,
the sun in the eastern half of the sky before noon, a polar day with no sunrise at all.

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

## Units: m/s for wind, km/h for speed

Wind is metres per second in every place it is displayed or stored, which is what a pilot
says out loud; ground speed and cross-country speed stay km/h, which is also what a pilot
says out loud. The measurements recorded elsewhere in this document predate the change
and are left in the unit they were taken in — they are notes on what was measured, not
labels on a screen.

`Wind.speed` was always m/s; the conversions were at the edges, and one of them was
missing: `airmass.field` mixed `meteo.wind_at()` in km/h into a field built in m/s, so a
flight with no circled climb got a modelled wind 3.6× too strong. `meteo.py` now asks
Open-Meteo for `wind_speed_unit=ms` and there is no conversion left anywhere to forget.

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

**Both are drawn in the browser now** (`charts_client.py`), from a payload rather than as
SVG in the document — the three axis modes used to ship as three SVGs with two of them
hidden, which was 577 KB of the published report on its own. The renderer builds the same
DOM `charts.py` builds, element for element, because the linked cursor, the tooltip, the
band highlight and "show me" were all written against it; a browser test compares the two.
The payload is small because the hover cursor was already carrying altitude, climb and
time at the very indices the trace is drawn through — see the module docstring for the
three rules that keep this a second *renderer* rather than a second *design*.

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

### Why there is no "paste an XContest link" button

Checked July 2026, hoping the "log in with XContest" button on `startovne.online` meant a
public OAuth provider. It does not appear to be one:

| probe | result |
|---|---|
| `www.xcontest.org/.well-known/openid-configuration` | 404 |
| `www.xcontest.org/.well-known/oauth-authorization-server`, `/oauth/authorize`, `/api/oauth/token` | 404 |
| `auth.`, `api.`, `oauth.xcontest.org` | only `oauth.` resolves |
| `oauth.xcontest.org/*` | Cloudflare 403 challenge, for the **`xcontest.app`** zone |
| `oauth.xcontest.org/.well-known/openid-configuration` | Cloudflare **522** — a real origin, timed out |
| `api.xcontest.app/*` | Cloudflare 403; `/.well-known/*` answers `Error: Forbidden path` from the origin |

So an auth service exists in the newer `xcontest.app` zone, but it is unadvertised and
reachable only as a registered partner. What *is* documented — and still answers in 2026,
with a structured `{"error":{"message":"Invalid key 'TEST'"}}` rather than a challenge — is
an **API key + shared secret** programme, keys from `info@xcontest.org`
([docs](https://github.com/Iv/FlyHigh/tree/master/doc/xcontest.org)):

- `GET /api/gate/ticket/?key=&hash=` then `POST /api/gate/request/?flight` — **submits** a
  flight. Pilot auth is `sha1(md5(password)+ticket+key+secret)`, i.e. the user hands us
  their XContest password. Not something to build, and it uploads rather than downloads.
- `GET /api/js/?key=` — a JS widget library with `flights`, `flight`, `pilots`, `pilot`
  and `ranking` services, locked to the website the key was issued for. It renders
  XContest's own flight-detail view; it does not hand over the tracklog.

Neither route yields an IGC file, so the tracklog still has to come from the pilot. The
cheap version of "get it from a link" is the two clicks the pilot already has: signed in
on their own flight page, **Download IGC**, then drop the file on the report. If the link
path is ever worth building, the action is an email to `info@xcontest.org` asking for a
key and whether the OAuth service is open to third parties — not more probing.

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

Done and tested (217 tests):

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

**That agreement no longer holds, on purpose.** igc2kmz shares the heuristic *and* its
flaw — a straight climb counts as a thermal — so agreeing with it meant reproducing the
wind outliers it produces. Requiring sustained circling takes the Dolomites flight from
18 climbs to 13 and every per-thermal wind into 1–10 km/h. The dropped climbs were
1–2 turn straight-ish bumps. See *Wind outliers from thermals that start too soon*.

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
climbs, same 11 glides, start times within 4 s.

**That agreement no longer holds, on purpose.** igc2kmz shares the heuristic *and* its
flaw — a straight climb counts as a thermal — so agreeing with it meant reproducing the
wind outliers it produces. Requiring sustained circling takes the Dolomites flight from
18 climbs to 13 and every per-thermal wind into 1–10 km/h. The dropped climbs were
1–2 turn straight-ish bumps. See *Wind outliers from thermals that start too soon*. **The XC optimiser agrees with XContest
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

### The 3D panel

Full-bleed (exactly the layout viewport, scrollbar measured in JS), 21:9 on a desktop and
4:3 below 900 px, with a fullscreen toggle that re-measures the canvas backing store.
Satellite imagery from Esri with its label layer composited on top, because a photograph
answers "what was under that climb" and a road map does not. An **Open in Earth** link
carries the KMZ as a data URI, so the Google Earth file is inside the report.

The fit overfills slightly (1.08 × width): the bounds are of a *rotated* rectangle, whose
bounding box is wider than the rectangle, so an exact fit leaves visible margins on every
side.

### 3D controls

Modelled on Google Earth, because that is what pilots already know:

| gesture | effect |
|---|---|
| left-drag | pan |
| right-drag, middle-drag, or ctrl/shift/alt + left-drag | rotate and tilt |
| wheel | zoom towards the pointer |
| one finger | pan |
| two fingers | pinch to zoom, twist to rotate, drag up/down to tilt |

Every rotation anchors on a **ground-plane point**, not on the middle of the flight. At
z = dem.min the height term drops out of the projection and it inverts in closed form, so
`groundUnder()` gives the world position under a finger and `holdGround()` moves the pan to
put it back after yaw or pitch has changed. Without it the fit recentres every frame and the
whole view swings around the scene's centre — "twist is centred on the wrong position", and
"the centre shifts at higher angles" for tilt. Verified across a gesture: the anchored point
moves **0 px** for both.

Two exceptions the measurements forced:

- **A two-finger drag must not pan.** The vertical travel *is* the tilt gesture, so panning
  with it drags the ground out from under the anchor by exactly the distance the fingers
  moved — 30 px of drift on a 30 px drag.
- **The pan spent crossing the deadzone has to be given back.** Until the gesture is
  classified it is treated as a pan; when it turns out to be a tilt, that pan is undone, or
  the view has already slid by the width of the deadzone. 14 px, then 0.

Tilt was also hard to trigger, because rotate was tested first and half a degree of twist
claimed the gesture before 26 px of travel could accumulate. Both thresholds are now
compared as *fractions of their own deadzone* and the further-along one wins, at 6° and
13 px.

The two-finger gestures are the only rotation controls a phone has, and for a while there
were none — twist-to-rotate had been removed because an imprecise pinch spun the camera,
which left the buttons as the only way to turn the view. Both are back behind a deadzone
that must be *broken* before either engages, and only one engages per gesture: 8° of twist
or 26 px of vertical travel. Verified by driving synthetic touch events — a straight pinch
gives `dyaw=0.00 dpitch=0.00 zoom=2.60`, a 40° twist gives `dyaw=0.57` with no zoom, and a
80 px two-finger drag gives `dpitch=0.22` with no yaw.

**And it turned the wrong way for all of that.** Every check above measured the *size* of
`dyaw`, never its sign against the direction the fingers actually went — so a twist that
tracked one-for-one, broke its deadzone correctly and anchored on the right ground point
still span the map backwards, and did so for as long as the gesture has existed. It reads
as correct in the source (`view.yaw += angleDelta(...)`), which is the trap: the finger
angle is `atan2` in client coordinates where y grows *downward*, so a twist the reader
sees as clockwise is a **positive** delta, while a positive `view.yaw` turns the scene
**counter-clockwise** on screen. Three sign conventions, two of which cancel. It is now
`-=`, and the test dispatches real `PointerEvent`s and asserts which way the ground went
— with the old sign a 45° clockwise twist moved the scene +0.445 rad, the wrong way.

Note that the **orbit drag is deliberately the opposite sense** and was left alone: drag
right walks the *camera* right, so the ground swings left, which is Google Earth's model
and what pilots already know. A twist is the reader turning the map; a drag is the reader
walking around it. Both directions are now pinned by a test so that correcting one is
never quietly applied to the other.

Panning needed a screen-space offset (`view.panX/panY`) applied *after* the fit: the fit
recentres every frame, so without it the camera was welded to the middle of the flight.

Zoom anchors on the cursor by moving the pan about that point — measured **from the fit's
anchor**, `(W/2, 0.58H)`, not from the canvas corner. Dropping that term biases every zoom
by `anchor·(ratio−1)`, which is why the view appeared to dive towards the bottom-right on
both wheel and pinch. Verified at three cursor positions: the point under the cursor stays
put to within 0.1 px.

Measuring any of this needs `handle.redraw()`, which paints **synchronously**. `draw()`
defers to `requestAnimationFrame`, and headless Chrome stops servicing rAF once the page
goes idle — so a probe that dispatched a wheel event and then read the projection was
reading it from before its own input. That produced a confident, entirely wrong measurement
of where the anchor was, and sent me looking for a bug in code that was already fixed. A
chained rAF loop in probe code hangs outright under `--virtual-time-budget`; use
`setTimeout`.

`initView3d` returns its `view` object on `window.__view3d` so a headless browser can
assert what a gesture did — a fingerprint of the canvas is too insensitive to trust, and
a mis-timed one had me chasing a control bug that did not exist.

### Touch

Two fingers mean pinch-zoom, one means pan. A phone has no scroll wheel, so a
pointer-tracking map replaced the single-drag handler; without it the view could only be
rotated, never zoomed, on the device most likely to be used at a landing field.

Pinch took two goes to get right. The first version panned by the centroid *and* let
`zoomAt` anchor on the same point, so every pinch double-counted the offset and the view
shot away sideways; it also mapped the angle between the fingers onto yaw, so any
imprecise pinch spun the camera. Now the pan follows the centroid, `zoomAt` handles the
scale about that point, and there is no twist. Measured from a headless browser driving
synthetic touch events: `pinch 1.00->2.00 yaw=-0.42`, the yaw unchanged from its start.

### Full screen: the API, with the in-page maximise behind it

The expand button calls `requestFullscreen` and maximises the panel *in the page* (a
fixed-position class) only when that fails. It was the other way round for as long as a
published artifact was the primary destination: inside an iframe without the fullscreen
permission the API fails two ways at once — it throws synchronously without a user
activation and rejects without the permission — and the button visibly did nothing. On a
host that permission is granted, and real full screen is what a reader means by the word:
the browser chrome goes with it, and the OS knows the window is presenting.

There is a third failure the promise does not describe: an implementation that returns
`undefined` and quietly does nothing. So the fallback is armed from a `catch`, from a
rejected promise, *and* from a check 120 ms later that asks whether the panel actually
became the fullscreen element. Everything downstream — sizing, the redraw ladder, the
Escape key — asks `panelIsFull()`, which is true for either path, so there is one state
machine rather than two.

Escape is deliberately not intercepted in real full screen: the browser already exits on
it, and taking the key would only race. The in-page path has nobody else to do it, so
there it is handled.

Testing this needed a stub. `requestFullscreen` requires a user activation and a
synthetic `click()` is not one, so a browser test reaches the *fallback* for free and can
only reach the granted path by standing in for the browser — recording the request,
reporting the panel as `document.fullscreenElement`, and firing `fullscreenchange`. Both
paths are pinned, along with leaving full screen again and not stranding the in-page
class on the way out.

The canvas then needed explicit pixel sizing: a percentage height does not resolve to
anything the backing store can match until layout settles, so the first redraw came out at
the old size. `applyMaximisedSize()` writes px, and a redraw ladder at 0/80/200/500 ms
catches whatever the browser settles late. Verified:
`maximised box=1185x713 backing=1185x713 match=true | restored box=1185x508 backing=1185x508`.

**Which pixels, though — the bug that made the controls useless.** Those px came from
`document.documentElement.clientWidth/clientHeight`, which is the viewport in standards
mode and the *whole document* in quirks mode. The report had no doctype, so it was in
quirks mode, and maximising a 4 316 px report gave a 4 316 px canvas inside an 813 px
panel. What that looks like from the reader's chair: the terrain is drawn for a viewport
five times too tall, so the visible strip is a fragment of a picture composed somewhere
off-screen; the track overlay and the GL heightfield disagree, because the GL canvas is
sized by `inset: 0` and got the panel's real height; and the controls sit exactly where
CSS puts them and appear to do nothing, because the projection every gesture and every
button anchors through belongs to a canvas five times the size of the one on screen.

Measured on the real report, before and after:

| | panel | 2D canvas | GL canvas | GL backing store |
|---|---|---|---|---|
| before | 1265×813 | 1265×**4316** | 1265×811 | 1265×**4316** |
| after | 1265×813 | 1265×811 | 1265×811 | 1265×811 |

Two fixes, and the second is the durable one. The report now emits `<!doctype html>` —
it should have all along; quirks mode was never intended and nothing else in the layout
had noticed. And the canvas is sized from **`panel.clientWidth/clientHeight`**: the
panel is `position: fixed; inset: 0` when maximised, so its own padding box *is* the
space to fill, and it is the identical box the GL canvas resolves `inset: 0` against.
Two measurements that cannot disagree, against two globals that did. The panel is
embeddable and does not own the document it lands in, so it must not depend on the mode
that document is parsed in.

`tests/test_view3d_fullscreen.py` maximises the panel in a browser and measures the
result in **both** modes — including `document.elementFromPoint` at each control's own
centre, which is the question a click actually asks. Against the old code the quirks case
fails at 3 021 px of canvas in an 813 px panel; the standards case passes, which is
exactly why a single-mode test would have been worthless.

### Image quality is set by the tile budget

`MAX_TILES = 24` capped every stitch at zoom 10 — 81 m per pixel on the reference box —
and no JPEG setting could recover detail that was never fetched: `max_width=1600` on a
1280 px native canvas did nothing at all. The budget is what matters:

| zoom | tiles | canvas | resolution |
|---|---|---|---|
| 10 | 10 | 1280×512 | 81 m/px |
| 11 | 27 | 2304×768 | 45 m/px |
| 12 | 72 | 4608×1024 | 22 m/px |

A single-flight report embeds both styles at zoom 12 downscaled to 2400 px (~550 KB per
flight, report 1.1 MB); a multi-flight document pays that once per flight and takes zoom 11
instead. `--online` embeds nothing and lets the page fetch up to 120 tiles at view time —
zoom 12–13, and a 0.5 MB file — which is the right build for GitHub Pages or a local file
and the wrong one for a published artifact.

### Reverted: tiles at view time

The section below describes fetching tiles when the page is opened. **It was reverted one
round later**, because it makes the toggle useless in the only place the report is actually
read: a published artifact blocks every host, so satellite fetched nothing, map fetched
nothing, and the button cycled between three states that all showed bare hillshade. Both
styles are embedded again (~340 KB per flight at 1600 px / q62, against 300 KB for the
single style before), and `tiles` now carries templates only for styles that are *not*
embedded — which is nothing, in a document built by the CLI, and both styles for the
uploaded-track view, which has no build step to bake anything into.

The lesson is not about tiles. It is that "smaller report" and "the feature works where the
report is read" were in conflict, and the size won a round it should have lost.

### Tiles at view time, and a three-state basemap button

The basemap used to be a JPEG stitched at build time and embedded — about 300 KB, at a
zoom fixed when the report was written. Now the payload carries tile templates and the
page stitches its own mosaic, so the button can cycle **satellite → map → bare terrain**
and each style is fetched once and cached in the page. `--embed-basemap` still bakes an
image for a genuinely offline report, and in that case the payload carries *no* templates:
a page holding both would try to fetch, fail under an artifact's CSP, and throw away the
picture it already had.

Two things this cost:

- **Compositing is not a race you can win by luck.** Satellite is two layers — imagery
  plus a transparent label overlay — and painting each tile into a shared mosaic as it
  arrives makes the z-order depend on arrival order. The label layer is requested second
  and frequently answers first, and then the imagery buries it. Each layer gets its own
  canvas, composited in declaration order at the end.
- **The button has to name what is on screen**, not what comes next. With three states a
  fixed "Map" label says nothing about where you are, so it reads Satellite / Map /
  Basemap. Verified by clicking it in a headless browser:
  `initial btn="Satellite" style=satellite painted=true | click1 btn="Map" style=map
  painted=true | click2 btn="Basemap" on=false | click3 btn="Satellite" cached=[satellite,map]`.

### The lattice of squares, and three wrong theories about it

The draped basemap showed a regular grid of dark lines over the whole slab, visible even
where the ground is flat. Three plausible causes, all wrong:

1. *The overdraw band is tinted twice.* Cells are drawn 12% oversized to cover the hairline
   the affine texture fit leaves — and the relief tint was drawn over the same 12%, so the
   overlap did receive two tints. Cutting the image to 4% while the tint stayed at 1.0
   moved the artefact rather than removing it: every cell then had an untinted border.
2. *The shading is sampled at one node per cell.* Averaging the four corners smoothed the
   values but changed nothing on screen.
3. *The tint itself.* Removing it entirely left the lattice exactly as it was — which is
   what finally ruled the shading out.

The cause was the overdraw itself. Stretching the *same* source slice over a 10% larger
quad scales the imagery up inside each cell, so the content no longer lines up with its
neighbour's and every boundary is a step. Growing the source rect by the same fraction
about the same centre keeps the texture's scale, covers the seams, and the lattice is gone.

The shading moved anyway, because it belongs in the texture: `shadedTexture()` composites
the illumination into a copy of the basemap once, at grid resolution, and the browser
interpolates it up. Smooth instead of faceted, one draw instead of one per cell per frame,
and it made room for a finer mesh.

### Matching XContest, and why distance alone cannot

Our numbers were consistently high: 53.5 km against 48.63, 204.8 against 201.40, 410.9
against 400.61. Two separate mistakes, both about *what quantity* is being reported.

The first: for a closed course XContest scores the **triangle's perimeter**, not the open
path through its turnpoints. `optimise()` returns start → tp1 → tp2 → tp3 → finish, which
includes the legs to and from the loop and is therefore longer.

The second, and the interesting one: **XContest maximises score, not distance.** The
multipliers are 1.0 open, 1.2 flat triangle, 1.4 FAI, so a shorter FAI triangle beats a
longer flat one — 48.6 × 1.4 = 68.1 against 51.0 × 1.2 = 61.2. Searching for the longest
triangle found the flat one and got both the number and the category wrong.

`xc.triangle()` therefore maximises perimeter × multiplier: an O(n²) sweep with the third
corner vectorised, over a 260-point distance-sample, with the closing rule enforced from a
precomputed `closing[i, k]` (the shortest gap between any sample at or before *i* and any at
or after *k* — a loop need not start where the flight did). That lands ~0.6% low, which is
the sample spacing, so each corner then slides over the *full-resolution* fixes in a window
of half a spacing, keeping the category fixed. Result, against XContest:

| flight | ours | XContest |
|---|---|---|
| Col Rodella 2018-09-28 | 48.64 km FAI | 48.63 km FAI |
| Krupka 2022-05-07 | 201.40 km FAI | 201.40 km FAI |
| Hunza 2026-06-16 | 400.61 km FAI | 400.61 km FAI |

Two things to keep straight. Only a route from `triangle()` may claim a category: the open
optimum frequently closes under the 20% rule, and crediting it a triangle multiplier let it
beat the real triangle every time, because its distance is not a perimeter. And the
open-distance path is still what an *open* flight scores — the reference flight is 64.08 km
against XContest's 64.09, unchanged.

### Wedges on a zoomed-in view

Folded cells, and the reason there is no clean fix: this is painter's order with no depth
buffer. A cell whose projected quad turns inside out — any slope steeper than the pitch
angle — has no correct quad rendering. Textured affinely it smears into a wedge; filled as
one path canvas draws it as a bowtie, which is also a wedge; filled as two triangles the
pair overlaps and leaves slivers showing older paint, which is a third wedge; skipped, the
sky shows through because painter's order means nothing was drawn behind it.

Measured before guessing further: **955 of 6 324 cells fold at the default camera, 1 834 at
zoom 7 and pitch 0.30, and only 37 at pitch 0.9.** Folding is a low-pitch phenomenon and
scales with zoom, which is why it only ever showed up zoomed in.

What is there now: a flat fill over the cell's convex hull, plus — when the camera is still
— two individually-affine textured triangles, each clipped to its own outline. Three points
determine an affine map exactly, so a triangle is correct even when the quad is not. The
minimum pitch is also raised from 0.06 to 0.18 rad, because three degrees of tilt is not a
view of anything and folds everywhere. Cells are additionally sorted by true camera depth
(`wy·cos p − wz·sin p`) instead of horizontal depth, which ignored height entirely; that is
correct but changed nothing visible, and it is worth knowing it was not the cause.

Some artefacts remain at extreme zoom and shallow pitch. A depth buffer is the real answer
and canvas 2D does not have one — so the terrain moved to WebGL, where it does. See *WebGL
for the 3D view*. Everything described above is still in `view3d.py` and still runs: it is
the fallback for a browser without WebGL and for a lost context, which is why the fold
handling was fixed rather than left broken before the depth buffer arrived.

### Terrain resolution, and paying for it in the right currency

2 600 DEM nodes was 59×43 over an alpine box: 850 m per node, and every facet of the
heightfield visible. The budget is 26 000 now (17 000 per flight when several share a
document), which is ~270 m per node.

Bytes and frames are separate costs and were being conflated. The grid costs bytes — it is
a flat list of integers in the document. The *drape mesh* costs frames, one `drawImage` per
cell, and is now budgeted in cells rather than derived from the grid: `FINE_BUDGET` 5 200
settles in ~130 ms, `COARSE_BUDGET` 1 800 keeps a drag near 45 fps, and the fine mesh
returns 180 ms after the last gesture. Measured with `__view3d.setInteracting()` and
`redraw()` in a headless browser, on the Dolomites flight at 188×138 nodes.

Both budgets are now a property of the **fallback** only. The WebGL backend draws every cell
of the grid in one call at the same cost whether the camera is moving or not, so on that
path the grid is the only budget there is — and it could go well past 26 000 nodes before
frames, rather than bytes, became the reason not to.

### Shading gentle terrain

The relief overlay on a draped basemap assumed alpine ground. `lit` on flat ground works
out to 0.96, and over the 390–761 m the reference flight crosses it never leaves a band a
few hundredths wide, so an overlay keyed to a fixed 0.86 midpoint painted a nearly uniform
wash. On satellite imagery that goes unnoticed — a photograph carries its own light — but a
road map is flat fill, and it came out looking like a sheet of paper.

Now `litMid` and `litSpread` are measured once over the grid and the shading is normalised
against them, so relief reads at whatever scale the ground actually has, with the overlay
skipped when the range is under 0.01 (a genuinely flat plane, as in the uploaded-track
view, must not have noise amplified into hills). Measured along a strip across the slab,
low-pass contrast on the bare hillshade went from sd 8.11 / span 35 to sd 9.85 / span 43.

Worth being honest about the limit: this terrain really is 2 % relief at true vertical
scale, and no shading makes it a mountain. That is what the ×2/×4 button is for.

### Several tracks at once, and removing any of them

The upload path used to overwrite one fixed article. Now each loaded flight is a clone of
`<template id="ql-template">` with its own uid, inserted before the drop panel's article so
reading order matches tab order, and every tab — bundled examples included — carries a `×`
that removes the article and the tab together.

Three things this forced:

- **No ids inside the template.** Everything is addressed by class and scoped to the
  article, because two flights would otherwise share `#ql-side`, `#ql-stats` and the rest.
- **One delegated listener on the tab strip**, not one per tab. Tabs appear at runtime, and
  listeners attached at load would miss every flight dropped in later. `render_html` owns
  the controller and `quicklook` asks it to switch or add; the previous arrangement had two
  independent copies of the switching logic, which is exactly how they got out of step.
- **Removing an article must drop its 3D handles** from `window.__view3dAll`. Each holds a
  DEM grid and a stitched basemap image, so a registry entry keeps a deleted flight's
  memory alive.

A tab is a `<span>` wrapper holding two buttons. A `<button>` inside a `<button>` is invalid
and browsers silently unnest it.

### The date an IGC file does not obviously have

B records carry a time of day and nothing else; the date is in `HFDTE`, in either of two
syntaxes. The browser parser was building fixes as `seconds since midnight` and calling that
an epoch, which put every uploaded flight on 1 January 1970. Nothing looked wrong until the
weather stopped being opt-in — at which point the page cheerfully fetched the *real* ERA5
weather for 1 January 1970 at the flight's coordinates and captioned it "the air that day".
A plausible wrong answer from a working request, which is the kind of bug a checkbox was
hiding. Fixes now carry absolute epochs, as the ones read out of a KML always did, and a
file with no `HFDTE` is marked undated so the weather is refused instead of guessed.

### A 3D view for an uploaded track

The same `initView3d`, and — where the page can reach a host — the same terrain as a built
report. `quicklook.py` fetches the terrarium tiles itself, mosaics them onto a canvas,
reads the pixels back and decodes `R * 256 + G + B / 256 - 32768`. That is allowed because
the tiles are CORS-open (`Access-Control-Allow-Origin: *`), which is the difference between
"reachable" and "readable": without those headers the canvas is tainted and `getImageData`
throws, and the code treats that as no DEM rather than as an error.

Three numbers differ from the CLI's on purpose. **Twelve tiles**, not twenty: this is a
fetch a reader waits through and a request against a donated service, and it is enough —
at the node spacing this grid ends up with (~320 m on a cross-country box) a zoom-10 tile
already over-samples it, so the extra tiles would buy detail the mesh cannot hold. **16 000
nodes**, not 26 000, and for the opposite reason to the CLI's: that budget is bytes in a
document, this one is never serialised, so the only cost is the mesh. **A 9 s timeout**,
after which it settles with whatever arrived — a CSP refusal fires `onerror` immediately
and never gets there, but a slow phone on a mountain must not be left staring at a spinner.

Measured against `terrain.py` on the same flight and the same box: the browser builds
139×115 nodes spanning −22 to 1449 m at zoom 10, where Python builds 139×114 spanning −3
to 1456 m at zoom 11. The spread is the deliberate tile budget, not a decode difference.

Where no host can be reached — a published artifact, which is blocked from every one — the
ground falls back to what it always was: one flat plane of 61 × 25 nodes at 30 m below the
flight's lowest point, with the caption saying which it is. The altitudes are the track's
own either way, so the *flight* is exact and rotatable, which is most of what the view is
for. Imagery follows the same rule and the credit says so.

The DEM is fetched **before** `initView3d`, not swapped in after it. There is no API for
replacing the grid under a running view, and re-running `initView3d` would bind a second
set of pointer handlers to the same canvas — every gesture counted twice. Inventing a
swap-in path to save a second of waiting is the worse trade; the caption reads
"Fetching terrain…" meanwhile.

Tested without a network: `tests/test_quicklook_terrain.py` rewrites the tile URL to a
data URI carrying a tile it encodes itself, with two known elevations in it, and asserts
both come back to the metre — plus the flat-plane fallback when every tile fails.

The panel is rebuilt from its original markup on every upload rather than re-initialised:
`initView3d` attaches its own listeners, and a second set on the same canvas would move
the camera twice per drag.

### What travels in the report, and what does not

The KMZ is no longer embedded. `--earth-link` puts it back as a data URI behind "Open in
Earth"; by default `--kmz` writes a file. Same reasoning for the basemap: the report is
for reading, and a second copy of the same flight in another format is dead weight in it.
Together these took the reference report from 0.8 MB to 0.46 MB.

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

Reached by the **+ your track** tab, which now comes *first*, ahead of the example
flights, with a note under the tabs saying the analysis happens in the page and nothing is
uploaded. The bundled flights are a showcase; the reader's own file is the product.
Loading a file replaces the view rather than appending to the page.

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

A turn is a **full revolution**: the heading advancing through 360° in one direction.
Summing |Δheading| and dividing by 360 — what this used to do — counts anything that
swings the nose, so a wingover scores most of a turn without a circle ever being flown,
and it is 11.5% of the turns counted across the 50 sample flights. Taking the *net*
rotation instead (what `quicklook.py` did) has the opposite fault: a climb circled six
times right and six times left cancels to zero. `_revolutions` splits the unwrapped
heading into runs of one direction, cutting a run only where the heading backs up by more
than 60°, and counts the runs that reach a full circle. The hysteresis is what makes it
usable on real data: 1 Hz GPS heading jitters, and a pilot holding a circle wanders more
than a few degrees, so a tight threshold chops one circle into pieces that never reach
360° and a good climb reads as zero turns.

The total swept heading is still computed, as `swept_turns`, because **tow detection
needs it**. "Was the launch flown straight" is a question about how far the nose moved,
not about circles closing; pointing `TOW_MAX_TURNS_PER_MINUTE` at revolutions labelled
three foot launches in the sample set as winch launches, and the reference two-stage tow
completes no revolution at all (it sweeps 3.3 turns of heading over 138 s, 1.43/min
against the 1.5 limit).

Circle time follows the same reasoning: it is the time spent *turning inside the counted
revolutions*, divided by the count. Dividing the whole phase duration by the count
charges the circles for every second of scratching straight between them, which reads as
one slow wide turn — 143 of 704 climbs landed outside a 12–30 s circle that way, against
86 of 691 now.

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

Measured against igc2kmz on the reference flight: **129 KB / 2 535 placemarks against
612 KB / 11 373**. The savings come from one `LineString` per colour run rather than per
segment, five-decimal coordinates, and a sampled animation — *not* from `Region`/`Lod`,
which costs bytes (three copies of the track) to save drawing work. Levels are 56 / 575 /
1 727 points, switched at 16, 320 and 1 400 on-screen pixels.

### What Google Earth mobile taught us

The first version passed every structural test and looked wrong on a phone. Four faults,
all of them things a KML validator cannot see:

- **Colours were byte-reversed.** KML is `aabbggrr`; `#eb6834` written directly is blue.
  The solid-colour folder drew last, so the entire track appeared solid blue. Every
  colour now goes through `kml_colour()` from familiar rrggbb.
- **The icon was a corrupt PNG.** Hand-typed base64 that passed the signature check and
  failed on the IDAT checksum: Earth drew a red X on every placemark. Icons are now
  generated with `zlib` and `struct`, and a test decodes each one.
- **`visibility` is ignored on mobile.** A folder marked hidden was exactly what was on
  screen. The fix is ordering rather than removal: the colourings end with climb, so a
  viewer that draws them all paints the right one last. Whether mobile also ignores
  `Region` was never established — that was an assumption, and the detail levels are back
  (coarse → fine, same fallback argument).
- **A Document description is printed verbatim**, markup included. The HTML table moved
  to a `Flight summary` placemark; the Document keeps a plain-text line.

Labels are also off on the climb and glide icons: eleven names at once overlapped into an
unreadable mat, and the name is already the balloon's heading.

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

### Wind outliers from thermals that start too soon

Reported from the wind sounding: two climbs on the Dolomites flight stood out at 22 and
18 km/h on a day whose others all read 1–5. Both were real, and they had one cause.

Measured first. Thermal 17 was 70 s long and its **first 30 s were dead straight** —
progress 0.99, no turn rate, tracking 270 m west while climbing 1.5 m/s. Wind is a
straight-line fit to the drift of a *circling* glider, so that westward run went into the
fit as if it were moving air: 17.9 km/h "from the east". Thermal 9 was worse and
different: 242 s containing **90 seconds of straight glide** between two separate climbs,
866 m of easting, reported as 22.4 km/h.

The shared cause was the `climb > 1.0` clause in the thermal mask, which asks nothing
about whether the glider is turning. It labels a straight run through a lift band a
thermal outright, and it fires on scattered single samples during a glide, which
`CONDENSE_THERMAL` then bridges into one enormous segment spanning the glide.

Three changes, and the third is the one that was not obvious:

1. **A thermal is climbing *and* not going straight**: `climb > 0` and one of
   `progress < 0.9`, `speed < 10 km/h`, or circling. The bare `climb > 1.0` is gone.
2. **A glide ends when the climb begins** (`climb <= 0`), not when progress finally
   breaks, and the straight climb between the two is left unclassified — the time budget
   already accounts for that as "other".
3. **"Circling" has to mean sustained turning.** Raw `|turn_rate| > 3°/s` fires on 1 Hz
   GPS heading noise every 20–45 s *while flying straight*, and those specks kept the
   internal gaps under the 60 s condense threshold, so thermal 9 stayed welded together
   even after 1 and 2. `_sustained()` drops any run shorter than `TURN_ONSET_SECONDS`
   before the mask is used. This was the fix that actually landed it.

Result on that flight: every per-thermal wind between **0.7 and 9.7 km/h**, no outliers,
every thermal 55–97% turning. 18 climbs become 13; the five dropped had 0.9–3.9 turns and
were straight-ish bumps rather than thermals. Across the showcase: Krupka 44→39 climbs,
Hunza 57→52. XC distances are untouched — they do not depend on phases.

**The tow had to move.** A tow is the one straight climb that *is* a phase, so removing
straight climbs from the thermal mask removed the segment `_reclassify_tow` relabels, and
tow detection vanished. It is now built directly by `_launch_climb()` and three details
are load-bearing, each found by a failing test rather than by design:

- It starts at the **first fix**, not where the climb first passes `TOW_MIN_CLIMB`.
  Starting late shortens the window and inflates turns per minute — on the reference
  flight to 1.54 against a limit of 1.5, losing the tow by a hair.
- It **overlaps** deliberately. A tow is rarely flown perfectly straight; the reference
  one contains 2.8 turns, whose circling part is detected as a short turny thermal.
  Judged on that fragment the launch is a thermal at 2.8 turns/min; judged over the whole
  113 s climb it is a tow. If the tow wins, the fragments inside it are dropped.
- It carries **no straightness test** of its own. That is `_reclassify_tow`'s judgement,
  made on turns per minute, which is the better measure — and a `progress` test here
  breaks on any discontinuity in the track, because the 20 s window straddles it.

The reference tow reads `138 s, +390 m, release 870 m`, exactly as before.

And it is a **two-stage launch** — a pull, a 180° turn, then a second pull — confirmed by
the pilot. That is the source of its 2.9 turns and the reason the overlap rule matters
rather than being a convenience: the 180 in the middle is detected as a short turny
thermal, and a tow that contains a deliberate reversal must still read as a tow. Over the
whole 138 s it is 1.26 turns/min against a 1.5 limit; over the 60 s fragment, 2.8. Any
future change to tow detection has to keep a two-stage launch on the tow side of that.

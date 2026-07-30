# parainsights

Tools for paragliding flight analysis. One repository, several tools; the first and
currently only one is the **tracklog viewer**.

```
parainsights/
├── CLAUDE.md              this file
├── pyproject.toml         one project, one venv, one test suite
├── tracklog_viewer/       the tool: IGC/KML/KMZ → analysis → HTML, KMZ, 3D map
├── tests/                 pytest, 113 tests, no network
└── docs/
    ├── formats.md         IGC and KML/KMZ format research, measured on real files
    └── plan.md            scope, decisions and status
```

A second tool goes in as a sibling package (`parainsights/<tool_name>/`) sharing this
`pyproject.toml` and `tests/`. If shared code appears, put it in `parainsights_common/`
rather than importing across tools.

## Getting set up

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -c pyproject.toml        # 113 tests, ~60 s, no network
```

`-c pyproject.toml` matters when the repo sits inside another project — pytest otherwise
walks up and adopts the enclosing config.

Run it:

```bash
.venv/bin/python -m tracklog_viewer.cli FLIGHT.igc --html out.html
.venv/bin/python -m tracklog_viewer.cli FLIGHT.igc --meteo --terrain --html out.html
.venv/bin/python -m tracklog_viewer.cli a.igc b.kmz c.igc --html all.html   # flight picker
.venv/bin/python -m tracklog_viewer.cli FLIGHT.igc --kmz flight.kmz         # Google Earth
.venv/bin/python -m tracklog_viewer.cli FLIGHT.igc --map map.html           # 3D map
```

Only `--meteo` and `--terrain` touch the network. Everything else is offline.

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
| `basemap.py` | OSM tiles stitched to one embedded JPEG |
| `meteo.py` | The day's vertical profile (Open-Meteo) |
| `charts.py` | All SVG charts, rendered locally |
| `view3d.py` | Canvas 3D view that works inside a published page |
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
- **Turn statistics are refused above 5 s sampling** (`TURN_RESOLUTION_LIMIT`). A circle
  takes ~20 s, so a 15 s KML aliases and produces a confident wrong number.
- **Wind comes from circle drift** and is only trusted from climbs actually circled in
  one direction for ≥2 turns. A tow drifts with the glider, not the air.
- **Tow is a fourth phase**, detected at the launch and excluded from thermal statistics
  and from the wind estimate.
- **`timezonefinder` is a hard dependency.** Only XCTrack ≥0.9.12 records a timezone;
  47 of 61 test files need the coordinate lookup.
- **Haversine, not the law of cosines** — `acos` loses precision at the ~7 m separations
  between 1 Hz fixes, which is what every derived series is built from.
- **Charts are rendered locally.** igc2kmz's Google Image Charts URLs died in 2019, so
  every graph in its output is a broken image. Don't reintroduce a network dependency
  into a chart.
- **The KMZ batches geometry, igc2kmz does not.** One `LineString` per colour run and
  three `Region`/`Lod` detail levels, against one placemark per fix: 125 KB and 2 534
  placemarks where igc2kmz produces 612 KB and 11 373 for the same flight. Watch the
  integer division when sampling — floor division gave one animation placemark per fix
  on short flights, which is the very thing this avoids.
- **Two 3D views on purpose.** `render_map.py` is better but needs network at view time;
  `view3d.py` gives up the basemap library to be embeddable. Both share the climb ramp.
- **XContest flight pages cannot be scraped.** The page is a JavaScript shell behind
  Cloudflare Turnstile with the IGC link only present for a signed-in session. We read
  the public title (pilot, date, scored distance) and tell the user to pass the file.

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

## Known gaps

- FAI/flat triangle scoring with multipliers is not implemented; `xc.py` does free
  distance only.
- Historical weather is surface-only: the ERA5 archive returns nulls on every pressure
  level, so flights older than ~60 days get no sounding.
- `quicklook.py` duplicates a subset of the analysis in JavaScript. If the Python
  thresholds change, change them there too — there is no shared source for them.

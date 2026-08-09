# airspaces — plan, decisions and status

The second tool in `parainsights`. See `../CLAUDE.md` for the repository layout.

Two goals, both met:

1. **A simple way to get Czech ATZ into XCTrack.** One OpenAir file, imported alongside
   the airspace XCTrack already downloads.
2. **Airspace in the browser.** A map tab in the published artifact, showing the base
   airspace and the ATZ together.

A third, later: the same data feeding flight planning.

## Why this tool exists at all

An unpowered paraglider is permitted inside a Czech ATZ, but must stay clear of the
traffic circuit. Neither XCTrack nor XContest carries the ATZ — they appear only when a
specific activity (parachuting, for instance) is activated. Of the 251 airspaces in the
Aeroklub base file, exactly one is an ATZ (LKCS, and only because it is a controlled
aerodrome). So the pilot flies past 82 aerodromes that the instrument does not know
about.

## Architecture

```
airspaces/
├── geo.py          WGS84 local-plane geodesy: circle fit, Douglas-Peucker, offsets
├── sources.py      the four public sources, and the cache
├── openair.py      OpenAir reader (tolerant) and writer (strict — see below)
├── atz.py          UAS zone GeoJSON → circles and clipped polygons, datum correction
├── aerodromes.py   VFR manual prose + OurAirports runways → reference data
├── circuits.py     the okruh box
├── basemap.py      embedded Czech border and city list, for the map backdrop
├── build.py        assembles the overlay from all of it
├── render_html.py  the map: inline SVG, class filter, floor filter, pan/zoom
└── cli.py          airspaces [--openair FILE] [--html FILE] [--report]
```

`build.Overlay` is the boundary: everything upstream produces it, both renderers
consume only it. Same split as the tracklog viewer's `Analysis`.

## Running it

```bash
.venv/bin/python -m airspaces.cli --openair CZ_ATZ.txt      # for XCTrack
.venv/bin/python -m airspaces.cli --html airspace.html      # the map
.venv/bin/python -m airspaces.cli --report                  # what built, what did not
```

Every source is cached under `~/.cache/parainsights/airspace`; `--refresh` re-fetches.
The tests never touch the network — fixtures live in `tests/data`.

Getting the file into XCTrack: Preferences → Airspaces and obstacles → FILES →
IMPORT OPENAIR FILES, or copy it into the `XCTrack/Airspaces` folder and tick it in the
same screen. **Keep the normal airspace loaded too** — this file is an addition, not a
replacement.

## Sources

| what | where | why this one |
|---|---|---|
| ATZ geometry | `aim.rlp.cz/data/uas/{AIRAC}/actual/LKR315A.json` | the only machine-readable publication of Czech ATZ; the AIP gives them as prose |
| base airspace | `airspace.aeroklub.cz/docs/public/CZ_low_*.txt` | Jan Zahradka for Aeroklub ČR, free to use |
| circuit altitude, ARP, circuit prose | `aim.rlp.cz/vfrmanual/actual/{icao}_text_en.html` | official, and the header line is fixed-format |
| runway thresholds | OurAirports `runways.csv` | public domain, and the VFR manual has no thresholds |

**The base airspace is Aeroklub's, not xcontest's.** The goal was "the same data as
airspace.xcontest.org". That site's own about page says it builds from soaringweb.org,
and soaringweb's Czech page is Aeroklub's file republished — so Aeroklub *is* the
upstream. Going to the origin gets a file that is current rather than an AIRAC cycle
stale (26-04-01 against soaringweb's 25-08-07), and it avoids xcontest's export
endpoint, which needs an account.

**RLP publishes on AIRAC, Aeroklub does not.** AIRAC is 28 days from 2024-01-25 —
checked against two real publications. Aeroklub's `26-04-01` is on no AIRAC date at all,
so its filename is read from the directory listing instead of computed.

## Decisions, and the reasons behind them

- **The writer emits only `AC AN AH AL AF V DP DC DB`.** Two failures, both observed in
  XCTrack: `AG` is rejected outright as *"Unsupported command"* — and Aeroklub's own
  file uses it 204 times — and an `AC` block missing `AN`/`AH`/`AL` fails not on itself
  but on the *following* `AC`, reported as *"Duplicate AC record"*. The error message
  names the wrong airspace, so the writer refuses to emit an incomplete block rather
  than trusting the caller. There is a test for each.

- **Colour comes only from the class**, so the class is the only lever: `Q` is orange
  with no alert, `W` is green with an alert, everything else is red. ATZ are `W` (green,
  as asked; the alert is right anyway — you should be on the frequency), circuit boxes
  are `Q` (orange, silent, because they sit inside an ATZ that has already alerted).

- **67 of the 82 ATZ are refitted as circles.** They are published as polygons of up to
  3 549 vertices, and the fit recovers a radius of 5 500.3 m ± 0.23 m — the published
  5.5 km, exactly. `V X=` plus `DC` is eight lines against three and a half thousand and
  is *more* accurate, because it drops the polygonal approximation rather than
  resampling it. The 15 that are clipped by an overlying CTR or TMA stay polygons,
  Douglas-Peucker at 50 m, which takes them from ~9 000 vertices to about 500 points.

- **5 500 m, not 3 NM.** 3 NM is 5 556 m — 56 m too big. The fit says 5.5 km flat.
  `DC` is in nautical miles regardless, so the file carries `DC 2.97`.

- **WGS84, not the FAI sphere** — hence `airspaces/geo.py` rather than reusing
  `tracklog_viewer/geo.py`. A 6 371 km sphere is 0.3% out in the east-west scale at
  50 N, which reads the 5 500 m radius as 5 490 m. The whole argument for replacing a
  polygon with a circle is that the circle is exact, so the geodesy has to be too.

- **The published ATZ geometry is 117 m out, and is corrected.** The fitted centres sit
  a mean 116.9 m from the aerodrome reference points on a mean bearing of 226°
  (sd 15°) — systematic, not scatter. Two independent sources agree with each other and
  not with it: RLP's own VFR manual and OurAirports are 7.3 m apart, and both are ~110 m
  from the zone centre. The signature is an S-JTSK → WGS84 conversion without the
  transformation grid. Circles are therefore re-centred on the published reference point
  and clipped polygons shifted by the mean measured across all the circles. `--raw`
  reproduces the publication unchanged. Written up for RLP in `atz-datum-hlaseni.md`.

  The correction refuses to act on fewer than five circular samples — below that an
  offset cannot be called systematic, and shifting real geometry on noise is worse than
  leaving a known small error alone.

- **The okruh is not an XCTrack obstacle, because it cannot be.** Obstacles would be the
  natural fit — they are the layer with proximity warnings and altitude labels — but
  they are a curated per-country download from airspace.xcontest.org covering Austria,
  France, Germany, Italy, Slovenia and Switzerland, with no Czech data and no import
  path. The Obstacles tab in XCTrack selects countries; it has no file picker, and
  `xcontest-public/xctrack-public#855`, asking for user obstacle files, has been open
  since April 2022. The one place obstacle GeoJSON can be uploaded is xcontest's export
  dialog, which targets XCTracer vario firmware, not the Android app. An obstacle in
  that model is also a *line with an altitude* — a power line, a cable car — which a
  volume of circling traffic is not. So the okruh stays OpenAir.

- **It is a band following the circuit path, not a filled box.** 300 m wide, 1 200 m
  abeam the runway, turning 2 000 m beyond each threshold, hollow in the middle. A
  filled box is 12 km² per runway, most of it corners where nothing ever flies; the band
  is 4.4 km², 37% of it, and reads like the circuit it represents. The proportions are
  the ordinary shape of a light-aircraft circuit, not a published figure, and the name
  and the file header both say so.

- **The band has a 60 m gap in one short end.** OpenAir has no hole primitive. Closing
  the ring through a zero-width slit produces a polygon that touches itself, and the two
  common fill rules then disagree: even-odd gives the hollow centre, nonzero winding
  fills it in — so whether the middle of the airfield alerts would depend on the reader.
  A real gap makes the ring a *simple* polygon, where both rules agree by definition.
  There is a test that walks every pair of edges to keep it that way.

- **Both sides of the runway, always.** The published handedness would allow a band half
  the size, but at a Czech aeroclub field the glider circuit is the mirror of the
  powered one — LKBE publishes `RWY 06, 09L/R - left hand` and then `gliders RWY 06,
  09L/R - right`. A one-sided band would be wrong at exactly the fields with the most
  traffic. It also means no geometry depends on parsing prose, which cannot be made
  reliable: 67 of 82 aerodromes state a direction and 15 state none. What the AIP does
  say goes in the airspace name, where XCTrack shows it.

- **Runway geometry comes from thresholds, not from the reference point.** The VFR
  manual gives magnetic runway directions and no thresholds; a box built from a
  reference point plus a magnetic heading is displaced by however far the reference
  point sits from the runway, which at a two-strip field is hundreds of metres.
  OurAirports has both thresholds for 137 of 140 Czech runways.

- **Altitudes are written in feet.** The VFR manual publishes both units and feet is
  what every OpenAir parser handles; the name carries the metric value too, because
  that is what a Czech pilot's instrument is set to.

- **`4000 MSL` is 4 000 feet, not 4 000 metres.** The base file uses that form 18 times.
  Testing for an "M" anywhere in the string reads it as metres — a 2 800 m error that
  put half the base airspace in the wrong filter band. Datum words are stripped before
  the unit is looked for.

- **The floor slider is sized from the data and starts at the top.** `CZ_low` stops at
  FL95, so its highest floor is 2 286 m; a slider running to 10 000 m spends three
  quarters of its travel doing nothing. It does *not* default to a filtered view: 328 of
  the 447 airspaces have a ground floor, so the filter answers "what is above me at
  1 500 m" rather than decluttering, and opening on a view that silently hides airspace
  is the wrong default for this of all things. (An earlier version did default to
  2 500 m, on the strength of the `4000 MSL` bug making the base file look like it
  reached 4 000 m. Once that was fixed the filter turned out to hide nothing at all.)

- **Circular ATZ carry their outline as well as their radius.** `records()` writes the
  circle whenever a radius is set and ignores the points, so keeping both costs nothing
  in the file — and without them the renderer draws 67 empty paths, which is exactly
  what the first version of the map did.

- **Airspaces are drawn big-and-high first, small-and-low last.** Otherwise a TMA covers
  every ATZ under it and the layer a paraglider cares about is the one that cannot be
  clicked.

- **No tile layer on the map.** Same constraint as the rest of the repository: a
  published artifact reaches no external host, so the backdrop is an embedded Natural
  Earth border simplified to 900 m, plus twelve city labels. Equirectangular projection
  with longitude scaled by cos(lat) at the country's centre — under a pixel of shape
  error at these sizes, and it keeps pan and zoom to a scale and an offset.

## Status

Done: both goals. 82 ATZ and 114 circuit boxes, 47 KB of OpenAir; the map renders all
447 airspaces with class and floor filters. 43 tests, no network.

The map is currently written as a standalone page by `--html`. The article it emits is
already shaped as `<article data-flight-report="airspace">`, which is what the tracklog
report's existing tab strip switches on, so dropping it in as a tab there is a matter of
adding the tab and the article to `tracklog_viewer/render_html.py` — deliberately left
until the report and the map are wanted in one file.

## Wanted next

- **Fold the map into the flight report as a tab**, and draw the flight's own track over
  it. The article and the tab-strip contract already match.
- **Airspace against the track**: which zones a flight entered, how close it came, and
  at what height — the natural bridge to `tracklog_viewer/analysis.py`.
- **Activation state.** Dropzones and restricted areas are only live sometimes; the AUP
  and NOTAM feeds say when. Everything here is drawn as if always active.
- **The 15 aerodromes with no published circuit direction** could be filled in by hand
  from the ADC charts, which are images and so not parseable.

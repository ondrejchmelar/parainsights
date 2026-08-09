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
aerodrome). So the pilot flies past 156 aerodromes and airstrips that the instrument
does not know about.

## Architecture

```
airspaces/
├── geo.py          WGS84 local-plane geodesy: circle fit, Douglas-Peucker, offsets
├── sources.py      the four public sources, and the cache
├── openair.py      OpenAir reader (tolerant) and writer (strict — see below)
├── atz.py          UAS zone GeoJSON → circles and clipped polygons, datum correction
├── aerodromes.py   VFR manual prose + OurAirports runways → reference data
├── circuits.py     the okruh band
├── basemap.py      embedded Czech border and city list, for the map backdrop
├── build.py        assembles the overlay from all of it
├── render_html.py  the map: inline SVG, class filter, floor filter, pan/zoom
└── cli.py          airspaces [--openair FILE] [--html FILE] [--report]
```

`build.Overlay` is the boundary: everything upstream produces it, both renderers
consume only it. Same split as the tracklog viewer's `Analysis`.

## Running it

```bash
uv run python -m airspaces.cli --openair CZ_ATZ.txt      # for XCTrack
uv run python -m airspaces.cli --html airspace.html      # the map
uv run python -m airspaces.cli --report                  # what built, what did not
```

`--html` writes **two** files: the page, and the OpenAir file next to it that the page's
download button links to. Publish them together or the button is dead.

The published copy lives at `public/airspace/`, deployed by the `pages` job in
`.gitlab-ci.yml` along with the rest of the site. `public/index.html` is the tracklog
viewer's report and must not be overwritten — the airspace map is a sibling, not the
front page:

```bash
uv run python -m airspaces.cli --html public/airspace/index.html
```

The same map is also a **view in the report**, reached by the switch at the very top of
the page. The tracklog viewer's `--airspace` builds it, and its argument is where the
download sits relative to the report:

```bash
uv run python -m tracklog_viewer.cli FLIGHT.igc [...] --terrain --meteo --online \
  --airspace airspace/ --html public/index.html
```

Every source is cached under `~/.cache/parainsights/airspace`; `--refresh` re-fetches.
The tests never touch the network — fixtures live in `tests/data`.

Getting the file into XCTrack: Preferences → Airspaces and obstacles → FILES →
IMPORT OPENAIR FILES, or copy it into the `XCTrack/Airspaces` folder and tick it in the
same screen. **Keep the normal airspace loaded too** — this file is an addition, not a
replacement.

## The two kinds of field, in the AIP's own words

Both are "airfields" loosely, and the AIP distinguishes them — publication A is the first
kind and B the second:

| | LKTA, publication A | LKCAST, publication B |
|---|---|---|
| Czech | **veřejné vnitrostátní letiště** | **neveřejná plocha SLZ** |
| English | **public domestic aerodrome** | **private SLZ field** |
| short | *letiště* — aerodrome | *plocha SLZ* — SLZ field |
| ident | 4-letter ICAO, `LKTA` | 6-letter, `LKCAST` |
| ATZ radius | 5 500 m | ~965 m |

*SLZ* is **sportovní létající zařízení**, sport flying device — the Czech category for
ultralights, and by extension the strips they fly from. This module uses "aerodrome" and
"SLZ field" throughout, which is what the manual's own English does.

## Sources

| what | where | why this one |
|---|---|---|
| ATZ geometry | `aim.rlp.cz/data/uas/{AIRAC}/actual/LKR315{A,B,C,D}.json` | the only machine-readable publication of Czech ATZ; the AIP gives them as prose |
| base airspace | `airspace.aeroklub.cz/docs/public/CZ_low_*.txt` | Jan Zahradka for Aeroklub ČR, free to use |
| circuit altitude, ARP, runway table, circuit prose | `aim.rlp.cz/vfrmanual/actual/{ident}_text_en.html` | official, header line is fixed-format, and SLZ fields have a page under their six-letter ident |
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

- **There are four zone publications, not one, and nothing indexes them.** `LKR315A` is
  82 ATZ at ICAO aerodromes; `LKR315B` is 74 SLZ/ultralight fields; `C` is 222 heliports
  and `D` 195 landing sites. They were found by asking for the next letter. A and B are
  the default — aerodromes with circuit traffic; C and D are mostly hospital pads and add
  417 small circles, so they are behind `--publications A,B,C,D`. **Missing B is what
  made Částkovice (`LKCAST`) absent**, and it is 74 airfields, not an edge case.

- **Only publication A prefixes the ICAO with a zone number.** A uses `905LKBA`; B uses
  `LKCAST`, C `HELLKUHIII`, D `PISLK011II`, and none of those is an ICAO code. Slicing
  `ident[3:]` unconditionally turns `LKCAST` into `AST`. `split_ident` matches the
  numbered form explicitly and leaves everything else whole.

- **The published ATZ geometry is 117 m out, and is corrected — but only publication A
  is wrong.** A's fitted centres sit a mean 116.9 m from the aerodrome reference points
  on a mean bearing of 226° (sd 15°) — systematic, not scatter. Two independent sources
  agree with each other and not with it: RLP's own VFR manual and OurAirports are 7.3 m
  apart, and both are ~110 m from the zone centre. The signature is an S-JTSK → WGS84
  conversion without the transformation grid. **Publication B, same organisation and same
  effective date, is right to 5 m** — which is why the offset is measured *per
  publication* and never across them: averaging a real error with clean data would move
  both. `--raw` reproduces the publications unchanged. Written up for RLP in
  `atz-datum-hlaseni.md`, where B's cleanliness is the strongest evidence that the fault
  is in one pipeline rather than in the zone data as a whole.

  The correction refuses to act on fewer than five circular samples — below that an
  offset cannot be called systematic, and shifting real geometry on noise is worse than
  leaving a known small error alone.

- **An SLZ strip has no ATZ, so it gets only an okruh.** Publication B's circles are
  *UAS geographical zones* — dronview labels one `SLZ LKCAST`, and the VFR manual calls
  the place a *neveřejná plocha SLZ*, not an aerodrome. Emitting them as green `ATZ`
  invented 74 aerodrome traffic zones that do not exist, and made the circuit look wrong
  for sitting outside one. What a paraglider needs at an SLZ strip is the traffic
  circuit; the zone is a drone rule. Off by default, `--slz-zones` puts them back, named
  `SLZ` rather than `ATZ`.

  Worth knowing if you compare against dronview: its drawn disc looks about twice the
  radius of the polygon in `LKR315B`, which measures 976 m over 73 vertices spanning
  962–988 m. Vlásenice (1 938 m from the reference point) and Hejlovský rybník
  (1 864 m) both sit outside that 976 m circle but appear inside dronview's. Not
  resolved; the published polygon is what this uses.

- **SLZ fields have a VFR manual page too, and therefore an okruh.** Under their own
  six-letter ident: `lkcast_text_en.html`. All 74 of publication B's have one, with a
  reference point and a runway table. None publishes a circuit altitude, so theirs is
  the 1 000 ft AGL default; none has surveyed thresholds either — OurAirports has them
  for 2 of the 35 Czech fields it lists — so the runway is reconstructed from the
  reference point, the manual's magnetic heading and its length. **Everything
  reconstructed is marked `est` in the airspace name.**

  The magnetic heading in an SLZ runway table is the designator times ten, so it is
  rounded to 10° before `DECLINATION` (5.5°, varying 4.5–6.5° across the country) is
  added. The residual is dominated by that rounding, not by the constant.

  Do not read a circuit altitude out of the prose: the only page that appears to state
  one says *"do not overfly surrounding villages in lower height than 1000 ft AGL"*,
  which is a noise-abatement minimum and not the circuit at all.

  **The 1 000 ft AGL default was checked and holds.** The VOC chart writes the circuit
  altitude beside the circuit at fields whose text page omits it — the number is an
  altitude, not a length, which subtracting the elevation across five fields settles:

  | field | elevation | on the chart | AGL | = metres |
  |---|---|---|---|---|
  | LKBORE Borek | 557 ft | 1 377 ft | 820 ft | 420 m |
  | LKBOLE Boleradice | 650 ft | 1 800 ft | 1 150 ft | 549 m |
  | LKBRTO Brťov | 1 610 ft | 2 624 ft | 1 014 ft | 800 m |
  | LKBREZ Březí Falcon | 1 680 ft | 2 700 ft | 1 020 ft | 823 m |
  | LKCAST Částkovice | 1 925 ft | 2 887 ft | 962 ft | 880 m |

  Mean 993 ft AGL over elevations spanning 557–1 925 ft, and the metric values are round
  (420 m, 800 m, 880 m) — Czech AIP practice, as at LKTA's published *2460 ft / 750 m*.
  A length would not track elevation like that. LKTA's own chart carries no such label,
  because its text page already publishes one.

  So the estimate is good to about ±150 ft. Reading the exact figure would mean OCR on a
  JPEG, which is why it is still an estimate and still marked `est`.

- **The band's dimensions were measured off the AIP's own charts, and do *not* scale
  with the runway.** The VOC chart at `.../ad/{ident}_voc.jpg` draws the published
  circuit, and the ATZ ring on it is a known 5 500 m radius, which gives the scale to a
  few metres. Measured:

  | field | runway | published circuit |
  |---|---|---|
  | LKCAST | 500 m | 3 316 × 2 832 m |
  | LKTA | 1 100 + 850 m | 4 672 × 4 161 m (both circuits together) |

  A 500 m SLZ strip therefore flies a circuit nearly the size of a 1 100 m aerodrome's:
  the size is set by how an aeroplane turns, not by how long the tarmac is. 1 300 m
  abeam and 1 400 m beyond puts the band within +9%/+2% of LKCAST's published figure.

  An earlier version scaled these with runway length, on the reasoning that a 2.4 km
  band around a 976 m ATZ "looked disproportionate". It was the reasoning that was
  wrong, not the band: **at an SLZ field the published circuit really is about 1.5× the
  ATZ diameter** and legitimately extends outside it. Scaling made those bands less than
  half the published size, which is the dangerous direction to be wrong in.

- **Names come from the VFR heading, position is the fallback.** `LK[A-Z]{2}` matched
  `LKCA` and then failed on the `S`, so all 74 B fields were unnamed; the ident is two
  to four letters after `LK`. The heading's second word is only sometimes part of the
  name — *Česká Lípa* yes, *Částkovice ARP:* no — so trailing service words and anything
  ending in a colon are stripped. Where the heading still yields nothing, the nearest
  listed Czech airfield within 2 km supplies it, which is also how C and D would be
  named, having no page at all.

- **The map label is hover on a mouse and tap-to-pin on a touchscreen.** A touchscreen
  fires `pointerover` on touch-down and `pointerout` on touch-up, so a hover-driven label
  appeared and vanished inside a single tap — which is exactly what it did on a phone.
  On touch it is now pinned by a tap, dismissed by tapping elsewhere, and drawn *above*
  the finger, because a label under the fingertip cannot be read.

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

- **It is a band following the circuit path, not a filled box — and there are two per
  runway, one each side, abutting along the runway itself.** That is how the AIP draws
  them: at LKCAST the two published rectangles meet on the runway line, each about
  2 950 m long and 1 300 m wide, together filling a 2 661 m span across.

  An earlier version drew a *single* ring at ±1 300 m with a hole in the middle. At an
  SLZ field, whose ATZ is only ~976 m in radius, the entire ATZ fell inside that hole —
  so the okruh appeared as a rectangle floating around the green circle, touching none
  of it, and nothing was marked over the field, the approach or the climb-out. That is
  the ground where an aeroplane is lowest and least able to avoid anybody. With two
  rectangles the shared leg runs down the runway and crosses the ATZ, as it should.

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

- **Airspaces are drawn strictly biggest-area first, ignoring class.** SVG has no
  z-index — paint order *is* hit order, so whatever is drawn last both covers and
  captures the pointer. Ordering by class put every ATZ above the dropzone inside it,
  and Tábor's dropzone could not be clicked through its own ATZ. Smallest on top means
  the most specific thing under the cursor is the one you get.

- **No tile layer on the map.** Same constraint as the rest of the repository: a
  published artifact reaches no external host, so the backdrop is an embedded Natural
  Earth border simplified to 900 m, plus twelve city labels. Equirectangular projection
  with longitude scaled by cos(lat) at the country's centre — under a pixel of shape
  error at these sizes, and it keeps pan and zoom to a scale and an offset.

- **The OpenAir download is a real file, not a data URI.** This is the one page in the
  repository that needs a sibling published with it, and it was a data URI first for
  exactly that reason. A plain file wins anyway: it keeps its name when a phone saves it,
  it can be linked to or `curl`'d on its own, and the page sheds 79 KB of base64 that
  most readers never click. Nothing the map *renders* fetches anything, so the offline
  guarantee that matters is intact.

- **The download button says what the file is not.** "Download for XCTrack" invites the
  reading that this replaces your airspace, which would delete every CTR and TMA from the
  instrument. It now reads *"Download ATZ + okruhy only"*, with the panel stating that
  nothing red or amber on the map is in the file and that it loads alongside the usual
  airspace.

- **The download carries a currency warning, and so does the file.** Airspace has an
  effective date and this is a snapshot: an AIRAC cycle is 28 days, a NOTAM is same-day,
  and nothing downstream can detect that the file has gone stale. So both the panel and
  the OpenAir header name the two effective dates the reader would check against, say it
  is informative only and not a navigation source, note that the okruh outlines are not
  published boundaries at all, and put the responsibility where it actually sits. In the
  file it is a banner, because a text file gets opened long after the page that offered
  it was closed.

- **In the report, the airspace map is a top-level view, not another flight tab.** The
  flight strip chooses *which flight*; this chooses *whether you are looking at flights
  at all*, which is a level up. It is the switch across the very top of the page.
  Consequences: the article carries no `data-flight-report` — that attribute belongs to
  the flight strip's controller, which hides everything that is not the open flight, and
  the two fought over `hidden` when it did — and the `<section data-view>` wrapper is
  emitted only when there is a second view, so reports without one keep the DOM they
  always had.

- **The viewer does not import the airspace package.** `render_html.Extra` is opaque:
  a uid, a label, and `body`/`style`/`script` strings pasted in unexamined. The
  composition happens in `tracklog_viewer/cli.py` behind `--airspace`, which imports
  `airspaces` lazily — so the viewer still works with the package absent or the network
  down. The two tools share a page, not code.

## Status

Done: both goals. 156 ATZ (82 aerodromes, 74 SLZ fields) and 205 circuit bands, 117 KB
of OpenAir; the map renders all 612 airspaces with class and floor filters, and offers
the OpenAir file for download. Published at `public/airspace/` and as a view in the
report. 66 tests, no network.

The map ships two ways: as a standalone page (`airspaces.cli --html`) and as a top-level
view in the tracklog report (`tracklog_viewer.cli --airspace`). Both are published.

## Wanted next

- **Draw the flight's own track over the airspace map.** The view is in the report now,
  but the two do not yet know about each other.
- **Airspace against the track**: which zones a flight entered, how close it came, and
  at what height — the natural bridge to `tracklog_viewer/analysis.py`.
- **Activation state.** Dropzones and restricted areas are only live sometimes; the AUP
  and NOTAM feeds say when. Everything here is drawn as if always active.
- **The 15 aerodromes with no published circuit direction** could be filled in by hand
  from the ADC charts, which are images and so not parseable.

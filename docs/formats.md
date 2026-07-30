# IGC and KML/KMZ — reference notes

Research notes taken from the IGC spec, the sample files in `~/Downloads` (60 IGC + 72 KMZ),
and `~/bin/igc2kmz` (twpayne, GPLv3, Python 2).

## 1. IGC file format

Plain ASCII (CRLF), one record per line, first character = record type.
Only `A`, `H`, `B` matter for basic parsing; `I`, `C`, `L` matter in practice.

| Rec | Meaning | Notes |
|-----|---------|-------|
| `A` | Manufacturer + logger serial, first line | `AXCT…` = XCTrack, `AXSB…` = SkyBean SkyDrop, `AXFH…` = Flytec/Flymaster |
| `H` | Header (`H` + source `F`/`O`/`P` + 3-letter code) | see below |
| `I` | Declares extra fields appended to every B record | byte ranges, 1-based inclusive |
| `B` | Fix (the actual tracklog) | see below |
| `C` | Declared task / turnpoints | two shapes (C1 = task header, C2 = turnpoint) |
| `E` | Timestamped event (e.g. marker press) | |
| `L` | Free-text log line | XCTrack dumps base64 device JSON here |
| `G` | Digital signature | ignore for analysis |

### B record

```
B 100525 4629836N 01145078E A 00000 02391 27
  ^time  ^lat     ^lon      ^ ^pressure ^gps  ^I-extensions
         DDMMmmm  DDDMMmmm  validity    alt
```

- time `HHMMSS`, **UTC**, no date → date comes from `HFDTE`
- lat `DDMMmmm` + `N`/`S`; lon `DDDMMmmm` + `E`/`W` → degrees + minutes/60000
- validity `A` = 3D fix, `V` = 2D/invalid
- **two altitudes**: pressure altitude (ISA, from baro) and GPS altitude, both 5 digits,
  may be `-0123` for negative. Either can be all-zero when the logger lacks that sensor.
- rollover past midnight: time goes backwards → increment the date (igc2kmz does this)

### Which altitude to use

igc2kmz picks GPS altitude if *any* fix has a non-zero value, else pressure altitude
(`igc.py:track()`). For climb-rate analysis pressure altitude is actually the better
source (less noise, no GPS vertical wander) when a baro sensor is present — worth
revisiting rather than copying. Sample files tell you what's available:
`HFPRSPRESSALTSENSOR:Measurement specialties,MS5611` = real baro.

### I record extensions

```
I 02 36 36 LAD 37 37 LOD
  ^n  ^start ^end ^code
```

Seen in the samples:
- `I023636LAD3737LOD` (47 files, XCTrack + SkyDrop) — lat/lon decimal places,
  extra digit of precision: `lat += LAD/6000000`
- `I053638FXA3941VXA4244GSP4547CCO4850HDT` (2 files) — fix accuracy, vertical speed,
  ground speed, course, heading

Other codes exist in the wild: `SIU` (satellites), `TAS`, `ENL` (engine noise), `RPM`, `TDS` (tenths of a second).

### Headers seen in the samples

`HFDTE` is the only one you must have. Two syntaxes, both present in `~/Downloads`:

```
HFDTE290523                 # old: DDMMYY
HFDTEDATE:280918,01         # new: DDMMYY,flight-number-of-day
```

Others worth reading: `HFPLTPILOTINCHARGE`, `HFGTYGLIDERTYPE`, `HFGIDGLIDERID`,
`HFFTYFRTYPE` (logger model), `HOSITSite`, `HFTZNTIMEZONE` (SkyDrop writes `+2.0`,
XCTrack does not → timezone usually has to be inferred or passed in),
`HFDTMGPSDATUM` (always WGS-84 in practice).

Values are frequently empty or junk (`HFPLTPILOTINCHARGE:` with nothing,
`HOSITSite:?`). igc2kmz has a `NOT_SET_RE` for `not set` / `n/a` — needed.

### Timezone: XCTrack hides it in the L records

XCTrack writes no `HFTZN`, but its `LXCTDEVICE` lines are a base64-chunked JSON blob
(concatenate the payloads, then decode) which contains:

```json
{"app":{"name":"XCTrack","versionName":"0.9.12.6"},
 "device":{"model":"Pixel 8", …},
 "os":{"sdk":37,"timezone":"Europe/Prague","type":"Android","version":"17"}}
```

So for XCTrack we can get the **IANA timezone** and convert UTC to correct local time
(including DST) instead of asking the user for `-z`.

**But only new XCTrack writes it.** Measured across the 61 files: the `os` key exists
only in 0.9.12.6 (the 2026 file). Versions 0.8.1 through 0.9.7.6 emit a device JSON
with `capabilities`/`device`/`xctrack` and **no timezone at all**. Resolution order and
what it actually yields on the corpus:

| Source | Files |
|--------|-------|
| `LXCTDEVICE` JSON `os.timezone` (XCTrack ≥ 0.9.12) | 1 |
| `HFTZN` header (SkyBean SkyDrop `+2.0`, Flytec `2`) | 13 |
| lookup from take-off coordinates (`timezonefinder`) | 47 |
| UTC fallback | 0 |

The coordinate lookup is not a nicety, it carries 77 % of the corpus — and it gets
foreign flights right: `2018-09-28-XCT-OND-01.igc` (`HOSITSite:Col Rodella`) resolves
to `Europe/Rome`, not the local `Europe/Prague`.

### Pressure vs GPS altitude offset

**Most files have no baro at all: 36 of the 60 in `~/Downloads`** — phone-based XCTrack
on hardware without a pressure sensor writes `00000` for pressure altitude throughout.
So the common case is GPS-altitude-only, and any climb-rate work has to survive GPS
vertical noise rather than assuming a clean baro trace. `HFPRSPRESSALTSENSOR` in the
header tells you which case you are in before you look at the data.

In `20260728XCTOCH10.igc` both are present: baro 410–2102 m, GPS 491–2227 m. Pressure
altitude is ISA-referenced (`HFALPALTPRESSURE:ISA`), so it is offset by whatever QNH
was — here ~80 m low at launch, ~125 m at altitude. Consequences:

- never mix the two series in one calculation
- baro is the better source for climb rate (smooth, 1 Hz, no vertical GPS wander)
- for *displayed* altitude, either use GPS or offset-correct baro against the GPS
  altitude at launch / a known launch elevation

### Gotchas confirmed in these samples

- 21 of 60 files are the same logger; 11 SkyDrop files have **empty pilot and glider**
- duplicate/backwards timestamps and 1 Hz stationary runs before take-off
- CRLF line endings; non-ASCII in headers (`Ondřej`) — files are not pure ASCII,
  decode as UTF-8 with fallback
- `01-1111.IGC` vs `01-1111(1).IGC` etc. are byte-identical duplicate downloads

## 2. KMZ / KML

KMZ = plain ZIP. The main document must be a `.kml` at the archive root; Google Earth
takes the first `.kml` it finds. Both flavors appear in the samples:

- igc2kmz: `doc.kml` + `images/pixel.png` + `images/paraglider.png`
- XContest: single `<name>.igc.kml`, no assets

Sizes are large because there is one Placemark per fix: `2018-09-28-XCT-OND-01.kmz`
is 1.1 MB zipped / **8.8 MB** of KML, 20 274 Placemarks, 13 157 `TimeSpan`s.
Any recreation should decimate (Douglas–Peucker) rather than emit every point.

### XContest's KMZ is the better structural model

`1785243312.27_6a68a6b042862.igc.kmz` (same 2 h flight as `20260728XCTOCH10.igc`) is
176 KB zipped / 1.1 MB KML with only 1 300 Placemarks — 8× leaner than igc2kmz, because:

- **`Region` + `Lod` level-of-detail switching.** Three sibling folders hold the same
  track at increasing detail (`track - simplest` / `simpler` / `detailed, colored by
  height`), each wrapped in a `<Region>` with a shared `<LatLonAltBox>` and
  `<Lod><minLodPixels>` of 16 / 256 / 1280 (`maxLodPixels` `-1` = no upper limit on the
  last one). Google Earth loads only the detail level matching the on-screen size.
- coordinates are batched into few long `<LineString>`s (one per colour band) instead of
  one Placemark per segment
- coordinates are rounded to 5 decimals (~1 m) — plenty, and it halves the file
- time points are sampled every ~15 s, not every fix, and use `TimeStamp`/`when`
  rather than `TimeSpan`

Folder set: ground projection (`clampToGround` + `tessellate`), extrusion to ground
(`extrude` + `absolute`), the three LOD tracks, and `time points` (`visibility 0`).
Colour bands are 45 pre-declared `<Style id="level-N">` line styles.

Downside: it is *only* a track viewer — no thermal/glide analysis, no stats, no balloons.
The combination we want is XContest's geometry hygiene with igc2kmz's analysis content.

### KML elements that actually get used

- `Folder` nesting + `<ListStyle><listItemType>` `radioFolder` (mutually exclusive
  track colorings) / `checkHideChildren` (collapse the thousands of children)
- `Placemark` → `LineString` (track segments) or `Point` (marks)
- `<altitudeMode>absolute</altitudeMode>` for the flown track;
  `clampToGround` + `<extrude>` for the shadow
- `<coordinates>lon,lat,ele</coordinates>` — **lon first**, ele in metres
- `TimeSpan`/`begin`/`end` (ISO 8601) drives the Google Earth time slider = animation
- `ExtendedData` + `<Data name="…"><value>` for per-feature stats, rendered through
  a `BalloonStyle` `<text>` template using `$[name]`, `$[description]`, `$[key]`
- `ScreenOverlay` for the graphs and colour scales
- colours are KML `aabbggrr` (**not** rrggbb)

Example thermal Placemark `ExtendedData` keys from the sample output:
`altitude_change, average_climb, maximum_climb, peak_climb, efficiency, distance,
average_ld, average_speed, maximum_descent, peak_descent, start_altitude,
finish_altitude, start_time, finish_time, duration, accumulated_altitude_gain,
accumulated_altitude_loss, drift_direction`.

## 3. What igc2kmz does (functionality to recreate)

`~/bin/igc2kmz`, ~4000 lines of **Python 2** (`print` statements, `raise X, y`,
`xrange`, `__builtin__`) — it will not run on python3 as-is. `python2.7` is still
installed here, so it can be used as an oracle for comparison output.

Output KML tree per flight:

```
<flight>.igc
├── Track            radioFolder: colored by climb / altitude / climb+energy / ground speed / time / solid
├── Shadow           normal / extrude / solid
├── Animation        paraglider icon driven by TimeSpan
├── Altitude marks   salient high/low points
├── Altitude graph   ScreenOverlay chart
├── Thermals         one Placemark per detected thermal + ExtendedData stats
├── Glides
├── Dives
└── Time marks       every 5 min (plus coarser hierarchy)
```

Flight summary table (`make_description`): pilot, glider, glider ID, take-off and
landing time, duration, take-off/max/min/landing altitude, total altitude gain,
maximum altitude gain, max climb, max sink, max speed, optional flight URL.

### Algorithms worth keeping (all documented in `HACKING.md`)

1. **Point filter** (`track.py:filter`) — drop fixes with non-increasing time,
   ground speed > 100 m/s, or vertical speed outside ±30 m/s.
2. **Windowed derivatives** — speed, climb, total-energy climb and *progress* over a
   sliding ~20 s window, interpolating the window edges rather than snapping to fixes.
3. **Progress heuristic for phase detection** — `progress = straight-line distance /
   distance flown` over the window. `> 0.9` ⇒ glide; `< 0.9` with climb ⇒ thermal;
   `< 0.9` with sink ⇒ dive. Then `condense()` merges runs separated by short gaps
   and thresholds discard uninteresting features (thermal ≥ 60 s and ≥ 50 m gain,
   glide ≥ 120 s, dive ≥ 30 s and < −2 m/s losing > 100 m).
4. **Thermal efficiency** = average climb / max 20 s climb. >80 % rare, >70 % very
   good, <50 % broken thermal or poor technique.
5. **Salient point selection** (`util.py:salient`) — recursive largest-drop/largest-climb
   split so only interesting altitude extremes get labelled. O(N log N) typical.
6. **Total energy compensation** — `dz/dt + (v1²−v0²)/2g`, removes the climb you get
   from trading speed for height.
7. **Spherical geometry** on an FAI sphere, R = 6 371 000 m — bearing, distance,
   halfway, interpolate, project. Fine for flight-scale distances; note FAI-sanctioned
   XC distance also uses the sphere, so this is the *correct* choice, not a shortcut.
8. **Wind drift** per thermal — direction from the entry→exit bearing of each thermal.
   `TODO` file admits the algorithm is weak.
9. **Incremental Douglas–Peucker** for chart and track decimation.

XC optimisation is **not** in igc2kmz: it shells out to the external `olc2002`
optimiser and reads a GPX with `<rte>` + league/distance/multiplier/score extensions
(`xc.py`). If we want XC scoring we implement it ourselves.

### What is broken / dated in igc2kmz

- Python 2 only.
- All graphs and colour scales are **Google Image Charts URLs**
  (`http://chart.apis.google.com/chart?…`) — that API was shut down in 2019, so every
  graph and scale in the existing sample KMZs renders as a dead image. Any recreation
  must generate charts locally (embedded PNG/SVG in the KMZ).
- `http://` links throughout, `pygooglechart` vendored in `third_party/`.
- The Google Elevation API notes in `~/bin/igc2kmlWrapper.sh` need an API key now;
  free DEM alternatives (SRTM/Copernicus tiles) are the sane replacement for
  ground-elevation lookups.
- One Placemark per fix → 8 MB KML for a 4 h flight.

## 4. Sample data on this machine

- `~/Downloads/*.igc`, `*.IGC` — 60 files: XCTrack (majority), SkyBean SkyDrop, Flytec.
  Good spread: 39 KB … 1.3 MB, some with baro, some without, some with empty headers.
- matching `*.kmz` — igc2kmz output for most of them (via `~/bin/igc2kmz/convert_all.sh`),
  plus one XContest-generated KMZ for format comparison.
- `~/bin/igc2kmz/examples/` and `test/` — upstream fixtures.

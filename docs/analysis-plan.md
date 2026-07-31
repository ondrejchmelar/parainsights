# Flight analysis — what more the data can say

Written 2026-07-31. Nothing here is implemented. Every number below was measured in this
worktree against `~/Downloads/*.igc` with the current `analysis.py`, on three flights that
between them cover the range the tool sees: an alpine triangle (`2018-09-28`, Col Rodella,
3 h 39 m, 13 climbs), a flatland day (`2020-08-16`, 2 h 38 m, 13 climbs) and a short tow
flight (`2020-07-12`, 1 h 34 m, 6 climbs). Probe scripts are throwaway; the numbers are
reproducible from the modules as they stand.

## Where this sits next to the UX review

`docs/ux-review.md` diagnoses the report — an instrument panel with no judgement in it —
and specifies the **debrief**: a verdict strip, 3–5 ranked finding cards, and the rule that
**a finding is a measurement plus a link, never an imperative**, and must carry a cost in
metres or minutes. Its eight findings are deliberately cheap: all eight are *framing* of
fields `Analysis` already carries.

This document is the layer underneath. It asks a different question — **what is in the
tracklog that we are not yet measuring at all** — and answers it in three tiers by what it
costs: existing dataclasses, new computation over existing series, new data. It inherits
every rule from the UX review, and adds one:

> **A metric that fires on most flights is not a finding, it is a constant.** Thresholds
> come from the distribution over the archive, not from a round number that sounds right.

## What the tracklogs actually support

Measured over the 50 IGC files, before proposing anything that assumes more:

| | Measured | Consequence |
|---|---|---|
| I-record extensions | **49 of 50 carry `LAD`/`LOD` only** — latitude and longitude decimals. One Flytec file carries `FXA SIU VAT ACZ VXA`. | **There is no airspeed anywhere in the sample.** Every "through the air" number has to come from the wind estimate, and inherits its confidence. |
| baro | 36 of 60 files have none | Vertical analysis on GPS altitude for most flights; anything comparing to a pressure level is already caveated |
| sampling | 1 Hz on XCTrack; a scoring-site KMZ is 500 points | `TURN_RESOLUTION_LIMIT` 5 s and `TOW_RESOLUTION_LIMIT` 15 s already gate the turn work; every new circling metric inherits the same gate |
| wind | drift only, and **the flight-level estimate is weak**: confidence 0.39 on Rodella, 0.36 on 2020-08-16 | A single flight wind is not good enough to correct a glide with. Per-thermal winds are (0.7–9.7 km/h, no outliers, after the `_sustained` fix) — so air-mass work must interpolate those, in time *and* height, and degrade where they are missing |

That last row is the load-bearing one for tier 2. It was tempting to write "correct every
glide to the air mass with `Analysis.wind`" until the confidence numbers came out at 0.36.

## Four corrections, from measuring rather than assuming

**1. `other` is not where the losses are.** The UX review says "That is 40 minutes, and it
is the only slice with no explanation. Losses live exactly there." Half right — it is
unexplained, and it is worth explaining, but on the reference flight it is **profitable**:

| | Rodella 2018-09-28 | Flatland 2020-08-16 | Tow day 2020-07-12 |
|---|---|---|---|
| `other` | 39.3 min, 17% | 39.2 min, 24% | 39.1 min, **41%** |
| mean climb inside it | **+0.16 m/s** | −0.54 m/s | −0.05 m/s |
| samples rising | 56% | 29% | 37% |
| net height over the slice | **+385 m** | −1 274 m | −115 m |
| straight sink | 8.2 min (20%) | 10.7 min (27%) | 3.8 min (9%) |
| scratching / slow sink | 7.0 min (17%) | 16.1 min (41%) | 10.8 min (27%) |
| rising, uncounted | **24.1 min (61%)** | 12.3 min (31%) | 24.5 min (62%) |

The slice is bimodal, and it is mostly the *thermal rule working as designed*: the straight
run-in to a climb and the sustained-circling trim both push rising straight flight out of
the thermal phase and into `other`. So the finding is not "you lost 40 minutes" — it is a
**three-way decomposition** with a different story per part: straight sink is the price of
the glide, scratching is the price of being low, and rising-uncounted is mostly ridge and
street flying that the phase model has no name for. Publishing the undifferentiated slice
as a loss would be the first confidently wrong sentence in the report.

**2. Dolphin flying cannot be measured inside the glide phase.** Share of glide time in
rising air: **8%** on Rodella, **5%** on 2020-08-16 — implausibly low for two good XC days,
and for the same reason as above: the good bits were reclassified out. Measured over *all
straight flight* (glides + `other`), Rodella's rising portions are worth **+299 m inside
glides and +385 m outside them**. Any "how much of your straight flight was in lift"
metric must be defined over straight flight, not over `Phase.GLIDING`.

**3. Achieved cross-country speed must use the scored route.**
`summary.straight_distance` is take-off to landing, which on a triangle is nearly zero:
it reads **0.5 km/h** on Rodella, a flight that scored 48.64 km FAI. Speed findings take
`Route.distance` and refuse when there is no route.

**4. `BEST` glide ratio is noise, and this is measurable.** Rodella's best glide reads
**116.2** — a "glide" that crossed lift. The UX review cuts the column on redundancy
grounds; the stronger argument is that it is not a measurement of the wing. Any L/D-based
finding uses a wind-corrected median over glides longer than 60 s (below), never a maximum.

## Tier 1 — new insight from dataclasses that already exist

Nine candidates, each measured on the three flights so the shape of the distribution is
visible before a threshold is argued about. The cost column is what the finding would
print; the rule is that a finding with no cost does not ship.

| Metric | Rodella | Flatland | Tow day | What the finding says |
|---|---|---|---|---|
| **Climb selection**: thermalling time in climbs under half the day's best | 32% (28.2 min) | **58% (43.9 min)** | 56% (15.5 min) | "43.9 min of your 75 min circling was in climbs under +1.00, on a day that offered +1.99" |
| **Climb rate by altitude third** | 0.78 / **1.36** / 0.85 | 1.06 / 0.96 / **1.26** | 1.05 / 1.05 / 1.02 | The working band, measured: on Rodella the top 588 m gave 0.85 for 24 min of circling; the middle gave 1.36 |
| **Centring index**: mean climb over the first 60 s ÷ the rest | 0.86 | **0.48** | 0.99 | "Your first minute in a climb averaged half of what the rest of it gave, over 12 climbs" — cost is the difference in minutes |
| **Gap between climbs** | median 432 s, max 1 340 s at 13:22 | median 332 s, max 866 s | median 186 s, max 1 245 s | The expensive gap (UX finding 2), with the day's own median as the comparison rather than a constant |
| **Concentration of gain**: share from the best three climbs | 45% | 50% | **73%** | How much of the flight rested on how few climbs — a fragility measure, and it frames the gap finding |
| **Day envelope**: climb rate regressed on hour of flight | −0.04 m/s/h (1.05 → 0.61) | **−0.17 m/s/h** (1.99 → 1.15) | — | "The day was decaying at 0.17 m/s per hour by the time you turned for home" — this is what makes a late turnpoint decision legible |
| **Detour ratio**: track distance ÷ scored distance | 121.3 / 48.64 = **2.49×** | — | — | Both numbers are already on the page and neither is framed as a cost |
| **`other` decomposition** | see above | | | Three named parts, replacing one unexplained slice |
| **Lowest save**: height before a climb over +300 m | +1 214 m from 2 051 m | +887 m from **558 m** | — | The number pilots retell. **Must be AGL** — 2 051 m on Rodella is a ridge top, not a save — so it needs `--terrain`, and is refused without it |

Everything in that table is a pass over `list[Segment]` and `Series`. No new inputs, no
network, no payload growth: findings are sentences, and a sentence costs a hundred bytes
against the 1.10 MB of inline SVG the report already carries.

**Two that look computable and are not.** Per-thermal drift relative to the course line
(UX finding 5) needs a course line, which only exists when `xc.py` returns a route — fine,
but it must be suppressed on a local flight rather than measured against take-off. And
"climbs abandoned early" needs a notion of what the climb would have given had it
continued, which the data cannot supply; the honest version is finding 1's phrasing —
*left at 3 656 m, 118 m under the day's best* — which states two measurements and no
counterfactual.

## Tier 2 — new computation over the series we already have

Ordered by evidence-per-line-of-code.

### The air-mass frame

Subtract the interpolated wind from the track and everything downstream is about the
glider rather than about the day. Measured with the (weak) flight-level wind, the
correction is already visible and it goes both ways:

| | ground L/D | air L/D | median airspeed |
|---|---|---|---|
| Rodella (3 km/h S) | 8.0 | 7.9 | 35 km/h |
| Flatland (8 km/h SSE) | 6.3 | **7.0** | 33 km/h |

An 11% correction on the flatland day from an 8 km/h wind is exactly the size of error that
makes a glide-quality finding wrong. Build it properly: interpolate the **per-thermal**
winds over time and height (they are the trustworthy ones), fall back to the model profile
from `meteo.wind_at()` where there is no measured climb nearby, and carry the confidence
through so a finding can refuse itself. This belongs in a new `airmass.py` beside
`flight.py` — a derived series, not a renderer concern.

What it unlocks, in order: wind-corrected glide ratio; **circle-centre wander** (the centre
of each revolution in the air frame — centring quality separated from drift, which is the
thing `circle_radius` cannot tell you); the drift-corrected core position, which is what
makes "you were circling 40 m downwind of it" sayable; and an **empirical polar**.

### An empirical polar, and why it beats a published one

Fit sink against airspeed over straight glides, binned, robust median per bin. One flight
gives a few points; the archive gives a curve per wing. It is better evidence than a
manufacturer polar because it is *this* glider with *this* pilot at *this* loading, and it
costs no new data. It is also the input every speed-to-fly statement needs, so it gates
that whole family of findings — including the honest refusal when the fit is too sparse.

### Speed decomposition, and the MacCready comparison

The classic XC identity: achieved speed is a function of mean *achieved* climb, glide ratio
over the ground, and the fraction of time doing neither. All three are now measurable
(the third being the `other` decomposition). Then the comparison that matters — what the
day's own climbs and the flight's own polar would have given at the MacCready setting the
pilot actually flew, against what they gave. Stated as two measurements, not as advice:
*"you stopped for climbs averaging +1.05; the day's best third averaged +1.43; at your
measured glide, taking only those would have been X km/h against your Y."*

Note the trap: the two are not independent, because taking only the best third means
gliding further and possibly landing. The finding must say so in the card, or it is the
blind coach again.

### Per-revolution climb

`_revolutions()` already returns the runs. Emitting a climb rate per revolution turns each
thermal into a short series and answers "how long to centre" directly (revolutions until
80% of the climb's best circle) instead of via the 60 s proxy used in tier 1. Gated at
`TURN_RESOLUTION_LIMIT` like everything else that counts circles.

### Insolation from the DEM, which we already have on the page

`sun.py` tabulates the day's solar position every ten minutes; `terrain.py` holds the
elevation grid. Slope and aspect are a gradient of that grid, and the cosine of the angle
between the surface normal and the sun vector is the relative insolation of every cell at
every moment. Two findings fall straight out, and neither needs a byte of new data:

- **The trigger**: which face was lit, and how strongly, at the minute each climb started —
  and how that face compares to the ones nearby. This is the question a pilot asks about a
  new site all day long.
- **The windward face**: aspect against the measured wind gives ridge-lift potential, which
  is a candidate explanation for the "rising, uncounted" 24 min that correction 1 uncovered.

The 3D view already re-lights the terrain from the same tables, so the machinery to *show*
this exists; what is missing is reading a number out of it.

### Reachability over the DEM

At the lowest point of the flight, how much ground was inside a glide cone at the measured
L/D — and where was the nearest of it. A safety finding that is honest about what it does
not know (it sees terrain, not fields, roads, wires or wind), so it reports **reachable
ground**, never "landable". Refused without `--terrain`.

### Model verification, accumulated

Achieved thermal top against `meteo.thermal_top()` and `boundary_layer_top`, per flight,
kept across the archive. Two payoffs: a per-flight statement (*"you topped at 95% of the
modelled cloudbase; across your 50 flights the median is 78%"*) and, over time, a
calibration of how well the model describes the pilot's sites — which is the same
independence argument that makes the wind chart's model-versus-measured overlay
persuasive.

## Tier 3 — data that would extend the analysis

| Source | What it buys | Keyless? | Cost / risk |
|---|---|---|---|
| **The pilot's own archive** (60 files, already on disk) | Percentiles for every tier-1 metric: "your weakest climb selection in 12 flights", per-site baselines, seasonal progression. **The single biggest win available**, and the thing that turns thresholds from opinions into observations | offline | Needs a cached summary (a few KB of JSON per flight, no tracklogs — `*.igc` is gitignored) and a `--archive DIR` flag. Cold-start problem: one flight, no context |
| **Open-Meteo fields not currently requested** — `shortwave_radiation`, `lifted_index`, `convective_inhibition`, `wind_gusts_10m`, `surface_pressure`, `freezing_level_height`, `cloud_cover`, `precipitation`, soil temperature/moisture | Same endpoint, same call, no new dependency — the cheapest data on this list. Radiation is the missing explanation for *why the day switched off*, which the −0.17 m/s/h envelope currently states without cause. `surface_pressure` gives the day's QNH, which validates `baro_offset` directly instead of inferring it. CIN/LI describe the morning delay and the cap | yes | Widens the hourly request; archive coverage still surface-only beyond 60 days (existing known gap) |
| **Landcover** (ESA WorldCover, CORINE) | Surface under each climb — "four of your six climbs triggered over ploughed ground" | WorldCover is public on S3 | Heavy rasters, licence check needed, and probably a lookup at a handful of points rather than a grid. Verify before promising |
| **Airspace** (openAIP, national AIP) | "You were 120 m under the TMA floor for 4 minutes" — high value, high stakes | key required, redistribution terms | Do not bake a copy into the repo or the report. Also: being *right* here matters more than anywhere else in the tool, and stale airspace is worse than none |
| **Site databases** (paraglidingearth and similar) | Names the launch and the LZ instead of a lat/lon; site-typical flight for comparison | to be verified | Small, offline-cacheable. Do not let it invent a site name it is not sure of |
| **Ground stations** (Holfuy and similar) | Launch wind reality-check against the model. `flymet` is already noted in `meteo.py` as forecast-only, so it cannot serve this | to be verified | Sparse coverage; only useful near known sites |
| **Other pilots, same day** | The strongest possible context: did everyone find 1.0 m/s, or just you | — | XContest cannot be scraped (documented, with reasons). The honest version is the files your friends send you, which the multi-flight document already accepts on the command line — so this is a *framing* feature, not a scraping one |
| **Published glider polar** | Speed-to-fly against the book | pilot types it in | The empirical polar is better evidence and free; a book polar is a nice-to-have cross-check, not a dependency |
| **IGC extensions when present** (`VAT`, `ACZ`, `SIU`, `FXA`) | TE vario, load factor, satellite count and fix accuracy — the last two are a *data-quality gate* rather than an insight | in the file | One file in fifty. Read it if it is there, never require it |

## What not to compute

An explicit list, because the debrief spends trust that "How to read this, and what to
distrust" earned:

- **No imperatives.** Inherited rule, restated because tier 2's speed-to-fly work is where
  it will be hardest to keep.
- **No circling metric above 5 s sampling**, no tow reasoning above 15 s. The centring
  index, per-revolution climb and circle-centre wander are all gated.
- **No air-mass correction on a low-confidence wind.** Measured: the flight-level estimate
  is 0.36–0.39 on both real flights. Use per-thermal winds, and refuse the finding rather
  than publishing a corrected number that is really an uncorrected one.
- **No AGL finding without `--terrain`**, and no ceiling finding without `--meteo`.
  Absent, the finding does not exist — not an empty card.
- **No landability claim.** Terrain is not a field.
- **No counterfactual that requires knowing what the abandoned climb would have done.**

## Where the code goes

The architecture rule holds: analysis is a pass producing plain dataclasses, renderers
consume only those.

- **`airmass.py`** — wind-corrected series and the polar fit. Derived data, beside
  `flight.py`. Nothing here knows about HTML.
- **`debrief.py`** — `Finding` dataclass (id, title, sentence, cost, evidence fields, a
  cursor index to link to, a confidence), a ranking pass, and one `THRESHOLDS` dict. Pure
  function of `Analysis` plus optional `meteo` / `terrain` / `route`.
- **`baseline.py`** — archive summaries and percentiles behind `--archive DIR`, cached as
  JSON, offline.
- **Thresholds ship as data.** `THRESHOLDS` is serialised into the page so `quicklook.py`
  reads the same numbers instead of holding a second copy. That is a direct hit on the
  documented known gap — *"if the Python thresholds change, change them there too; there is
  no shared source"* — and it is cheap enough to be worth doing on the first finding
  rather than the tenth.

## Validation

The repo's habit is that numbers are checkable, so:

- **Measure every tier-1 metric across all 50 files and report the distribution**, not the
  showcase three. A metric whose finding would fire on more than a third of flights has its
  threshold set wrong (or is not a finding).
- **The air-mass work checks against the model.** Correcting a glide with the measured wind
  and with `meteo.wind_at()` should agree within the wind's own uncertainty; where they
  disagree systematically, one of them is wrong and the flight can say which.
- **The polar checks against the wing's published curve** where the pilot supplies one, and
  against itself across flights — a polar that moves between two flights of the same glider
  is measuring the wind estimate, not the wing.
- **The `other` decomposition checks by reconstruction**: the three parts must sum to the
  slice, and the slice plus the phases must sum to airtime.
- **No network in tests.** Archive baselines are fixtures of summary JSON; tracklogs stay
  out of the repository.

## Phasing

**Phase A — decompose `other`, and the four corrections.** Cheapest, and it fixes a wrong
sentence before it is written. Three named parts, the dolphin metric defined over straight
flight, XC speed on the scored route, glide ratio as a corrected median.

**Phase B — tier 1 findings, with thresholds from the archive.** Climb selection, working
band, centring index, gap, concentration, day envelope, detour. This is what feeds the UX
review's debrief cards, and it is where the product changes. `THRESHOLDS` ships as data
here, so quicklook stops drifting.

**Phase C — `airmass.py`.** Per-thermal wind interpolation, corrected glides, circle-centre
wander, the empirical polar. Everything speed-to-fly waits on this, and rightly.

**Phase D — the DEM findings.** Insolation and aspect at each trigger, windward faces,
reachable ground at the low point. All from data already in the report.

**Phase E — the archive.** `--archive`, percentiles on every tile and finding, model
verification accumulated over flights. This is the one that makes the tool answer *"was
that a good flight for you"* rather than *"was that a good flight"*.

Phases A and B are a session's work each and need nothing new. C is the one with real
uncertainty in it — the wind field is the weakest input in the tool, and it is worth
finding that out on glides before building speed-to-fly on top of it.

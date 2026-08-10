# meteo — plan, decisions and status

The third tool in `parainsights`. See `../CLAUDE.md` for the repository layout.

One goal: **before the drive, decide whether it is worth driving.** A day's sounding, its
cloud cover, its wind and its temperatures, for the Czech sites people actually fly, on
one page — the question flymet's meteograms and pgweb's GFS charts answer, put next to
the site list rather than next to a model.

## Why Open-Meteo and not Windy

Windy was checked first, because it is what everybody already has on their phone and its
map is better than anything here will be. It cannot be the source:

| | Windy Point Forecast | Windy Map Forecast | Open-Meteo |
|---|---|---|---|
| free tier | 500 requests/day | 500 sessions/day | no key at all |
| what the free tier returns | **"randomly shuffled and slightly modified data"** | GFS only, 3 layers | the real forecast |
| free tier in production | **not permitted** — "development purpose only" | **not permitted** | permitted, non-commercial |
| paid | €990/year | €990/year (+€1 000 for ECMWF) | — |
| pressure levels | yes, surface to 150 hPa | n/a | yes, 1000 to 500 hPa here |

The free Windy tier is not a smaller version of the paid one — it deliberately returns
*wrong numbers*, and its terms forbid shipping it. A forecast page whose numbers are
"slightly modified" is worse than no page. €990 a year for a tool nobody pays for is not
a trade this project can make, so Windy is out as a data source. Checked August 2026:
`api.windy.com/point-forecast/pricing`, `api.windy.com/map-forecast/pricing`.

Open-Meteo is already a dependency (`tracklog_viewer/meteo.py` fetches the day's profile
for a flown flight) and gives the same pressure levels with no key. What is left on the
table is Windy's *map*, which is genuinely better than a static chart; an embed is a
possible future layer, and it would be the free Map Forecast tier, which is dev-only —
so that too would have to be paid for or done without.

Flymet (`flymet.meteopress.cz`) stays as a **link, not a fetch**. Its meteograms are
images generated per site with no documented API and no licence to redistribute them,
and `tracklog_viewer/meteo.py` already records that they carry no archive endpoint. A
pilot who wants the flymet reading should get flymet's own page.

## The forecast is fetched in the page, not baked into it

Every other artifact in this repository is self-contained, and this one deliberately is
not. The reason is that a forecast has a shelf life of hours: a page built at 03:00 and
published is wrong by lunchtime, and there is no build step between the reader and the
site. So the page ships the *site list* and the charts' code, and asks Open-Meteo for the
numbers when it is opened. Open-Meteo sends `Access-Control-Allow-Origin: *`, which is
what makes this possible at all — the same property `quicklook.py` relies on for terrain.

Consequences, all of them accepted: the page is useless offline, it says so rather than
drawing an empty chart, and it cannot be a view inside a published artifact that blocks
every host.

## The site list is committed data, not a fetch

ParaglidingEarth publishes a documented per-country GeoJSON API, and its records carry
the one thing a weather service cannot know: **which wind directions each takeoff works
in**, on its own 0/1/2 scale. That is what turns a forecast into an answer — 20 km/h from
the north-west is a good day at one hill and unflyable at the next one along — and it is
the whole reason the list comes from there rather than from a list of place names.

159 Czech takeoffs, 138 of them with a rose. The 21 without one are **left unjudged**
rather than guessed at, and the page says so: inventing a direction for a hill nobody
recorded is the one error this page must not make.

`meteo.cli --refresh-sites` rewrites `meteo/sites.py`, provenance and fetch date first.
Takeoffs do not move, so the file is committed and the build needs no network.

## Two requests, and why not one or a hundred and sixty

Every site's *surface* forecast comes in one multi-coordinate call — Open-Meteo accepts
comma-separated coordinates and answers with an array, so 159 takeoffs cost one round
trip and about half a megabyte, which is what the ranking needs. The **pressure levels
are fetched for one site only, when that site is opened**: asking for the profile of
every takeoff up front would be tens of megabytes to answer a question about one hill.

## Status

Started, and the page works end to end: the day strip, the ranked site list with a
verdict per takeoff, the sounding, the meteogram and the day's figures. Published at
`public/meteo/`.

Wanted next:

- **The verdict rule needs a browser test.** `tests/test_meteo_view.py` keeps a second
  copy of it in Python and pins the two thresholds; it cannot fail on a change to the
  rule's *shape*. Driving the real function with `fetch` stubbed is the fix, the way
  `tests/test_view3d_gestures.py` drives the real gestures.
- **A map, instead of a scrolling list.** The airspace view is already the widget for it,
  and a takeoff is a point with a colour.
- **A wind-direction arrow per site**, rather than the compass point in text.
- **The site's own airspace.** Both halves exist in this repository and neither knows
  about the other yet: a takeoff sits under something, and it would be worth saying what.

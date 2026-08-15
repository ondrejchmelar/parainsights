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

Flymet (`flymet.meteopress.cz`) is now shown as well, and it is worth being precise about
what that means. Its meteograms are images generated per station with no documented API,
no archive endpoint (`tracklog_viewer/meteo.py` already records that) and no licence to
redistribute them — so **nothing here copies, caches or rebuilds one**. The page carries a
URL; the reader's own browser fetches the picture from flymet, with flymet named in the
caption and the caption a link back to its own page. That is the same relationship as the
Open-Meteo call beside it, and the opposite of republishing.

It earns its place because it is not another view of the same numbers: a different model,
run by somebody else, drawn in the form Czech glider pilots already read — cloud, rain,
stability with the convective cloud height, and wind by height, all against the hour.
Where it disagrees with the charts above, that disagreement is the most useful thing on
the page.

Two consequences the page has to state rather than hide. **Only two days exist** —
`/meteogram/` is today and `/meteogram2/` is tomorrow — so the third and fourth day of the
strip show no picture rather than yesterday's under today's heading. And the station is
the *nearest airfield*, not the takeoff: the caption gives its name and how far away it
is, because 12 km down the valley is a fair proxy for the day and a poor one for the hill.

### Where the stations are, given flymet never says

The one derived dataset in this repository. flymet publishes its 186 stations as an HTML
image map over an 800x600 picture of the country: the only statement anywhere of where a
station *is* is the pixel its circle sits on. So `sources.flymet_frame` solves the map's
projection — a full six-parameter affine, since nothing published says which projection it
is or whether it is square to north — from twelve stations whose real position is known
from OurAirports, and puts every station's pixel through it.

It is checked rather than trusted, in three places. The refresh **refuses to write** if the
worst anchor comes out more than a kilometre from where it belongs, which is what a
redrawn map would look like and would otherwise pass silently. The committed file keeps
the pixels, so a test re-solves the fit and re-places all 186. And the anchors are
airfields rather than towns, because matching flymet's names against a gazetteer put
Černovice u Tábora on Brno-Černovice, 170 pixels away — the error this construction exists
to avoid.

Measured: worst anchor 239 m against a map scale of 664 m a pixel, and Mnichovo Hradiště —
picked because it is the station the whole feature was asked for — lands 150 m from the
real airfield. Every Czech takeoff has a station within 21 km, median 9 km.

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
Takeoffs do not move, so the file is committed and the build needs no network. The flymet
station list is the same shape — `--refresh-flymet` rewrites `meteo/flymet.py` — and the
two are paired at build time by `render_html.nearest_stations`, because neither list moves
and 159 × 186 distances are arithmetic no reader's browser should be asked to repeat.

## Two requests, and why not one or a hundred and sixty

Every site's *surface* forecast comes in one multi-coordinate call — Open-Meteo accepts
comma-separated coordinates and answers with an array, so 159 takeoffs cost one round
trip and about half a megabyte, which is what the ranking needs. The **pressure levels
are fetched per chosen takeoff, when it is chosen** — at most three, since that is the
comparison's cap: asking for the profile of every takeoff up front would be tens of
megabytes to answer a question about three hills.

## Three takeoffs, compared

The page's question is *is it worth driving anywhere, and where*, and the second half of
it needs more than one hill on screen. Up to three are chosen at a time — the cap is the
categorical palette's, not a whim, see below — each with a chip, a row in the comparison
table and its own boundary-layer line on the shared meteogram. The takeoff being *looked
at* keeps the sounding, the figures and flymet's picture; the others are there to be
compared against it.

**Why three.** Slots 1–3 of the design system's categorical order pass every check in the
dataviz skill's `validate_palette.js` on the all-pairs list in both themes; the documented
fourth slot is yellow, and yellow against this orange fails the normal-vision floor at
ΔE 13.7. A documented palette may not be re-stepped and no ordering fixes an all-pairs
failure, so a fourth line would be one nobody could tell from the third. The page says so
rather than evicting a takeoff the reader chose. Because two of the three light-mode
series sit under 3:1 against the panel, identity is also carried by a label at the end of
each line, by the legend, and by the table — the palette's relief rule, and a browser test
holds it.

The full list lives in a `<dialog>` rather than on the page. `docs/meteo-ux.md` measures
what that was costing: 571 px of the layout, and 166 tab stops before a keyboard user
reached the forecast.

## What the sounding says

The chart is two lines against a scale, and two things a pilot wants from it are not
lines. Both are drawn now, and both are marked as what they are.

**The cloudbase** is the surface spread at 125 m a degree — a rule of thumb, drawn dotted
and printed in the figures under the chart, with the model's own cloud cover on the
meteogram beside it so the two can disagree in front of the reader.

**The capping layer — the *zadržná vrstva*** — is shaded. A parcel rising dry cools at
9.8 °C/km, so it keeps going while the air around it cools faster than that and stops
where the air cools slowly, not at all, or warms with height. The threshold drawn is
2 °C/km: well below the 6-9 of a working day, above the noise of two levels 220 m apart,
and named in the caption because it is a judgement and not a measurement. An inversion —
air that warms with height — is shaded red and labelled as one; only the lowest band is
named, because it is the one a thermal meets first. The honest limitation is stated on the
page: this is read *between the model's pressure levels* and is no finer than they are, so
a 100 m morning inversion inside one of those gaps cannot be seen here at all.

**The pointer reads it off.** Hover — or drag a finger up it on a touchscreen — and the
chart names the height, the height above the site, the temperature, the dew point, the
spread and the wind there. The wind is the reason it exists: it is the number that decides
where the day is flyable and the only one on this chart that is not drawn at all. Values
between levels are interpolated along the same line the chart draws, and the wind as *u/v
components* — 350° and 010° averaged as numbers give 180, due south, which is the one
wrong answer a pilot would act on.

## Status

Started, and the page works end to end: the day strip, one hour slider over everything,
the takeoff picker behind a dialog, up to three chosen takeoffs compared in a table and on
one meteogram, and for the one being looked at the sounding with its cloudbase, capping
layer and hover readout, the day's figures and flymet's own meteogram for the nearest
airfield. The choice is remembered between visits. Published at `public/meteo/`.

Wanted next:

- **The verdict rule still keeps a second copy in Python.** `tests/test_meteo_view.py`
  pins the two thresholds but cannot fail on a change to the rule's *shape*. The harness
  that fixes it now exists — the sounding tests drive the real page with `fetch` answering
  from a built profile — so this is exposing `verdict` on `window.__meteo` and one test,
  rather than the piece of work it used to be.
- **A map, instead of a list.** The airspace view is already the widget for it, and a
  takeoff is a point with a colour. The list is behind a dialog now, which takes the
  pressure off this — but a map is still the right way to pick a hill, and it would answer
  "what else is near the one I am looking at", which no list does.
- **A wind-direction arrow per site**, rather than the compass point in text.
- **The site's own airspace.** Both halves exist in this repository and neither knows
  about the other yet: a takeoff sits under something, and it would be worth saying what.

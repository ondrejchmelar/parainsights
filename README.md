# parainsights

Tools for paragliding, published at **<https://ondrejchmelar.github.io/parainsights/>**.

| page | the question |
|---|---|
| [Meteo](https://ondrejchmelar.github.io/parainsights/meteo/) | is it worth driving anywhere today, and where? |
| [Planner](https://ondrejchmelar.github.io/parainsights/airspace/) | what is above me, what is that task worth, and what does it cross? |
| [Flights](https://ondrejchmelar.github.io/parainsights/) | how did that flight go? |

**Meteo** compares up to three takeoffs at once: a table at the chosen hour, the boundary
layer, and for each takeoff an airgram (wind by hour and height, cloud, cloudbase) beside
its sounding. The forecast is Open-Meteo's, fetched when the page is opened.

**Planner** is the airspace over Czechia and the Alps as the 3D boxes it really is, floor
to ceiling, with a task planner on the same map: drop turnpoints, see the distance and
score as XContest would count them, the area where the third turnpoint makes an FAI
triangle, and every zone the route crosses. The traffic circuits of Czech airfields are
drawn by this project — no published airspace carries them — and are also offered as an
OpenAir file to load into XCTrack alongside your usual airspace.

**Flights** analyses a tracklog — IGC, or KML/KMZ from a scoring site — entirely in the
browser: climbs and glides, wind from circle drift, the scored XContest route, the wing's
EN class, the weather that day, and a debrief that ranks what cost the most. Upload your
own track with *+ your track*; nothing leaves your machine. Each flight has a 3D map with
a replay that can follow the glider, the airspace over it, and a distance tool.

## Data, and credit

- Airspace © [openAIP](https://www.openaip.net), CC BY-NC 4.0 — 45 European countries,
  refreshed monthly by a GitHub Action (`.github/workflows/airspace.yml`)
- Czech traffic circuits and aerodrome zones: this project, from ŘLP ČR publications
- Imagery © Esri, Maxar, Earthstar Geographics; place names from
  [OpenFreeMap](https://openfreemap.org), © OpenMapTiles, © OpenStreetMap contributors
- Terrain: AWS Open Data Terrain Tiles
- Weather: [Open-Meteo](https://open-meteo.com); meteograms linked from flymet.cz
- Glider classes: the DHV Geräteportal and Air Turquoise's report list

The site is static files on GitHub Pages; nothing runs on a server. It is
non-commercial, as the openAIP licence requires.

## Working on it

Needs [uv](https://docs.astral.sh/uv/) and Node; Chrome for the browser tests.

```bash
uv sync --extra dev
uv run python -m tests.vendor          # once: MapLibre and deck.gl for the 3D map tests
uv run pytest -c pyproject.toml
```

**Publishing.** The Flights page (`public/flights/index.html`; the site's root redirects there) is built locally — it needs the
tracklogs, which stay out of the repository — and committed. The Pages workflow
(`.github/workflows/pages.yml`) runs the tests, refuses to publish a Flights page older
than the code that renders it (`ci/stale.sh`), builds the Meteo and Planner pages itself,
and deploys. Uploaded tracks need no build: they are analysed in the reader's browser.

Layout, decisions, the build commands and why things are the way they are:
[CLAUDE.md](CLAUDE.md).

"""The meteo view. No network: the site list is committed data and the forecast is
fetched by the page, so what is testable here is the data and the markup around it.

The one judgement the page makes — whether the wind suits a takeoff — is tested in the
browser with `fetch` stubbed, because it is JavaScript and because getting it wrong is
the only way this page can actively mislead somebody. So is everything the sounding says
about the air, and for the same reason.
"""

import base64
import contextlib
import datetime as dt
import http.server
import json
import re
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest

from meteo import cli, render_html, sites, sources
from tests.browser import CHROME, CHROME_FLAGS, needs_chrome


class TestTheSiteList:
    def test_every_site_is_in_the_country_it_claims(self):
        """A stray coordinate would put a takeoff in the sea and rank it anyway."""
        boxes = {  # (south, north, west, east), loose
            "CZ": (48.5, 51.1, 12.0, 18.9), "SK": (47.7, 49.7, 16.8, 22.6),
            "DE": (47.2, 55.1, 5.8, 15.1), "IT": (36.6, 47.1, 6.6, 18.6),
            "SI": (45.4, 46.9, 13.3, 16.7), "AT": (46.3, 49.1, 9.4, 17.2),
            "CH": (45.8, 47.9, 5.9, 10.6), "FR": (41.3, 51.2, -5.2, 9.6),
            "PL": (49.0, 54.9, 14.1, 24.2),
        }
        for site in sites.SITES:
            south, north, west, east = boxes[site["country"]]
            assert south < site["lat"] < north, site
            assert west < site["lon"] < east, site

    def test_every_takeoff_is_in_a_region_and_every_region_points_at_one(self):
        """The picker reaches a takeoff only through a region, so one in none is a
        takeoff nobody can choose, and an index past the end is a broken row."""
        reached = set()
        for country in sites.COUNTRIES:
            assert country["regions"], country["code"]
            for region in country["regions"]:
                assert region["sites"], (country["code"], region["name"])
                for index in region["sites"]:
                    assert 0 <= index < len(sites.SITES)
                    reached.add(index)
        assert reached == set(range(len(sites.SITES)))

    def test_countries_are_alphabetical_and_essentials_lead(self):
        """The pilot's calls (October 2026): countries by name, and each country's
        essentials, where pgweb has them, first and named for the country."""
        names = [country["name"] for country in sites.COUNTRIES]
        assert names == sorted(names)
        by_code = {country["code"]: country for country in sites.COUNTRIES}
        assert by_code["CZ"]["regions"][0]["name"] == "Essentials Czechia"
        assert by_code["SK"]["regions"][0]["name"] == "Essentials Slovakia"

    def test_every_hand_move_names_a_takeoff_that_exists(self):
        """`sources.MOVES` puts takeoffs in regions by name; a typo, or pgweb renaming
        one, would leave it wherever the nearest point puts it, silently."""
        for code, moves in sources.MOVES.items():
            listed = {sites.SITES[i]["name"] for country in sites.COUNTRIES
                      if country["code"] == code for region in country["regions"]
                      for i in region["sites"]}
            for region, names in moves.items():
                assert region in [r for r, _, _ in sources.REGIONS[code]], (code, region)
                for name in names:
                    assert name in listed, (code, name)

    def test_pgweb_is_read_into_groups_and_one_takeoff_listed_twice_is_one(self):
        html = ('<script>WeatherApp.init([{"name":"**ESSENTIALS**","x":0,"y":0},'
                '{"name":"Ran\\u00e1","x":13.77,"y":50.406},'
                '{"name":"*****St\\u0159edoho\\u0159\\u00ed & Kru\\u0161n\\u00e9*****","x":0,"y":0},'
                '{"name":"Ran\\u00e1","x":13.7702,"y":50.4061},'
                '{"name":"*****RAKOUSKO*****","x":0,"y":0},'
                '{"name":"Gerlitzen [AT], 1911 m","x":13.91,"y":46.69}], {});</script>')
        groups = sources.read_pgweb(html)
        assert [g for g, _ in groups] == ["ESSENTIALS", "Středohoří & Krušné", "RAKOUSKO"]
        assert groups[2][1][0] == {"name": "Gerlitzen", "country": "AT", "alt": 1911,
                                   "lat": 46.69, "lon": 13.91}
        built, countries = sources.build(groups)
        assert [s["name"] for s in built] == ["Raná", "Gerlitzen"]
        regions = {c["code"]: [(r["name"], r["sites"]) for r in c["regions"]] for c in countries}
        assert regions["CZ"] == [("Essentials Czechia", [0]), ("Středohoří & Krušné hory", [0])]
        assert regions["AT"] == [("East Tyrol & Carinthia", [1])]

    def test_a_rose_comes_from_the_paraglidingearth_takeoff_within_a_kilometre(self):
        built = [{"name": "Raná", "country": "CZ", "lat": 50.406, "lon": 13.77, "alt": None,
                  "landing": None, "tow": False, "winds": [], "id": 0},
                 {"name": "Nowhere", "country": "CZ", "lat": 49.0, "lon": 15.0, "alt": 400,
                  "landing": None, "tow": False, "winds": [], "id": 0}]
        records = {"CZ": [{"name": "Raná - J", "lat": 50.4075, "lon": 13.7715, "alt": 426,
                           "landing": 293, "tow": False, "winds": [2, 0, 0, 2, 2, 0, 0, 2],
                           "id": 10099}]}
        assert sources.pair(built, records) == 1
        assert built[0]["winds"] == [2, 0, 0, 2, 2, 0, 0, 2] and built[0]["id"] == 10099
        assert (built[0]["lat"], built[0]["alt"]) == (50.4075, 426)
        assert built[0]["name"] == "Raná", "pgweb's name is the one a pilot searches for"
        assert built[1]["winds"] == [], "nothing within a kilometre: unjudged, not guessed"

    def test_a_wind_rose_is_eight_octants_or_nothing(self):
        """`winds` is indexed by octant, so a short list would read the wrong direction
        rather than fail. Empty is the deliberate 'unknown', and it is common: not every
        takeoff has one recorded."""
        for site in sites.SITES:
            assert len(site["winds"]) in (0, 8), site
            assert set(site["winds"]) <= {0, 1, 2}, site
        assert any(not site["winds"] for site in sites.SITES), (
            "the unknown case has vanished from the fixture, so nothing tests it")

    def test_the_list_says_where_it_came_from_and_when(self):
        """Committed data with no provenance is data nobody can tell is stale."""
        assert "pgweb" in sites.SOURCE.lower()
        assert "paraglidingearth" in sites.ATTRIBUTION.lower()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", sites.FETCHED)
        assert sites.ATTRIBUTION

    def test_north_is_first_and_it_goes_clockwise(self):
        assert sites.OCTANTS == ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


class TestTheFlymetStations:
    """The one list here that is derived rather than published. flymet states where a
    station is only by where it draws it on an 800x600 picture of the country, so these
    check the derivation rather than take it on trust."""

    def test_every_station_landed_somewhere_real(self):
        from meteo import flymet

        assert len(flymet.STATIONS) > 150
        for station in flymet.STATIONS:
            assert 47.8 < station["lat"] < 51.6, station
            assert 11.5 < station["lon"] < 19.6, station
            assert station["slug"] and station["name"], station
            assert re.fullmatch(r"[A-Z0-9._-]+", station["slug"]), station

    def test_the_pixels_still_give_back_the_coordinates(self):
        """The committed `lat`/`lon` are the committed `x`/`y` through the affine, and
        nothing else. Re-solving it from the anchors and re-placing every station is what
        makes that checkable instead of a claim in a docstring — a hand-edited coordinate,
        or a fit quietly changed, shows up here."""
        from meteo import flymet, sources

        pixels = {s["slug"]: (s["x"], s["y"]) for s in flymet.STATIONS}
        place, worst, scale = sources.flymet_frame(pixels)
        assert worst == pytest.approx(flymet.RESIDUAL_M, abs=1)
        assert scale == pytest.approx(flymet.METRES_PER_PIXEL, abs=1)
        for station in flymet.STATIONS:
            lat, lon = place(station["x"], station["y"])
            # The file rounds to four places, which is 11 m of latitude.
            assert (lat, lon) == pytest.approx((station["lat"], station["lon"]), abs=1e-4)

    def test_the_fit_is_well_inside_what_picking_a_station_needs(self):
        """A kilometre of error would still pick the right airfield; the point of the
        limit is to catch a redrawn map, which would move every station at once and
        otherwise look exactly like a page that works."""
        from meteo import flymet, sources

        assert flymet.RESIDUAL_M < sources.FLYMET_TOLERANCE_M
        assert flymet.RESIDUAL_M < flymet.METRES_PER_PIXEL, (
            "the worst anchor is more than a pixel out: the projection is not affine")

    def test_the_list_says_where_it_came_from_and_when(self):
        from meteo import flymet

        assert "flymet" in flymet.SOURCE
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", flymet.FETCHED)
        assert "FLYMET" in flymet.ATTRIBUTION

    def test_the_images_are_fetched_over_https(self):
        """Not a detail. The site is served over https, and a browser drops an http image
        on an https page without drawing anything or saying why — so the picture would
        simply never appear, and only for the readers who use the published site."""
        from meteo import flymet

        assert flymet.TODAY.startswith("https://")
        assert flymet.TOMORROW.startswith("https://")
        assert "{slug}" in flymet.TODAY and "{slug}" in flymet.TOMORROW
        assert "meteogram2" in flymet.TOMORROW, "tomorrow's meteograms are the /2 set"


class TestPairingATakeoffWithAStation:
    def test_the_nearest_station_wins(self):
        near = {"slug": "NEAR", "name": "Near", "lat": 50.0, "lon": 15.0, "x": 0, "y": 0}
        far = {"slug": "FAR", "name": "Far", "lat": 50.5, "lon": 15.0, "x": 0, "y": 0}
        site = {"name": "Hill", "lat": 50.05, "lon": 15.0, "alt": 500, "winds": [], "id": 1}
        found = render_html.nearest_stations([site], [near, far])[0]
        assert found["slug"] == "NEAR"
        assert found["km"] == pytest.approx(5.6, abs=0.3)

    def test_a_takeoff_with_nothing_near_it_gets_nothing(self):
        """Silence beats a meteogram for an airfield 200 km away, which would be a
        different day's weather under this takeoff's name."""
        station = {"slug": "FAR", "name": "Far", "lat": 48.0, "lon": 15.0,
                   "x": 0, "y": 0}
        site = {"name": "Hill", "lat": 50.5, "lon": 15.0, "alt": 500, "winds": [], "id": 1}
        assert render_html.nearest_stations([site], [station]) == [None]

    def test_every_takeoff_north_of_the_alps_has_a_station_near_it(self):
        """flymet covers Czechia and the border: every takeoff there gets a meteogram,
        and the Alpine ones get none rather than a Czech airfield's."""
        found = render_html.nearest_stations()
        assert len(found) == len(render_html.SITES)
        north = [entry for site, entry in zip(render_html.SITES, found)
                 if site["country"] in ("CZ", "SK", "DE")]
        assert all(north), "a takeoff north of the Alps was left without a station"
        worst = max(entry["km"] for entry in north)
        assert worst < 30, f"the worst takeoff is now {worst} km from a station"
        south = [entry for site, entry in zip(render_html.SITES, found)
                 if site["country"] in ("IT", "SI")]
        assert south and not any(south), "an Alpine takeoff was paired with a flymet station"


class TestThePage:
    def test_the_payload_carries_the_sites_and_the_levels(self):
        html = render_html.body()
        blob = re.search(r'<script type="application/json" class="met-data">(.*?)</script>',
                         html, re.S)
        payload = json.loads(blob.group(1))
        assert len(payload["sites"]) == len(render_html.SITES)
        assert payload["levels"] == list(render_html.LEVELS)
        assert payload["endpoint"].startswith("https://api.open-meteo.com/")
        # One entry per site and in the same order: the page indexes it by the site's own
        # index, so a shorter or re-sorted list would hand out other takeoffs' airfields.
        assert len(payload["flymet"]["near"]) == len(render_html.SITES)
        assert payload["flymet"]["today"].startswith("https://")

    def test_the_pressure_levels_match_the_viewer_s(self):
        """A forecast profile and a flown profile are read against each other, and two
        different level sets would make that a conversion nobody remembers to do."""
        import re
        from pathlib import Path

        from tracklog_viewer import render_html as report_html

        source = (Path(report_html.__file__).parent / "js" / "meteo.js").read_text()
        flown = re.search(r"var PRESSURE_LEVELS = \[([^\]]*)\]", source).group(1)
        assert list(render_html.LEVELS) == [int(x) for x in flown.split(",")]

    def test_the_caption_states_the_threshold_the_script_uses(self):
        """The shading is a judgement with a number behind it, and the caption prints that
        number. Two copies, because one is prose and one is code — so this is what keeps
        the page from claiming 2 °C/km while shading at 3."""
        assert f"var CAP_LAPSE = {render_html.CAP_LAPSE}" in render_html.SCRIPT
        assert f"under {render_html.CAP_LAPSE:.0f} °C/km" in render_html.body()

    def test_the_page_says_it_needs_a_network(self):
        """It is the one artifact here that is not self-contained. Saying so is the
        difference between a page that is honest and a page that looks broken."""
        assert "needs a network" in render_html.SCRIPT

    def test_the_page_credits_its_sources(self):
        html = cli.page(render_html.body(), "Meteo")
        assert "Open-Meteo" in html
        assert "ParaglidingEarth" in html
        assert "flymet" in html


NO_ROSE = {"name": "Unknown", "lat": 50.0, "lon": 15.0, "alt": 500, "winds": [], "id": 1}

# Wind is in **metres per second** here, which is what a pilot on a hill says out loud.
# Open-Meteo is asked for `wind_speed_unit=ms`, so nothing in the page converts anything.
# The two gates are the old km/h ones converted exactly — 28 km/h is 7.78 and 20 km/h is
# 5.56 — so no takeoff changed verdict when the unit did.
VERDICTS = [
    # A good octant and a workable strength is the only unqualified yes.
    ([0, 0, 0, 0, 0, 0, 2, 0], 3.9, 270, "flyable"),
    # Same hill, same direction, twice the wind.
    ([0, 0, 0, 0, 0, 0, 2, 0], 9.4, 270, "too strong"),
    # Between the two gates: flyable, and worth saying it will be lively.
    ([0, 0, 0, 0, 0, 0, 2, 0], 6.5, 270, "brisk"),
    # Right strength, wrong side of the hill.
    ([0, 0, 0, 0, 0, 0, 2, 0], 3.9, 90, "wrong way"),
    # The site's own "marginal" survives as marginal rather than being rounded up.
    ([0, 0, 0, 0, 0, 0, 1, 0], 3.9, 270, "marginal"),
    # Nothing recorded: the page refuses rather than guesses.
    ([], 3.9, 270, "no rose"),
]


def test_the_thresholds_are_in_metres_per_second():
    """Cheap, and it runs without a browser. The gates are named in the source in the
    unit the page prints, so a reader of either can check the other."""
    source = render_html.SCRIPT
    assert "STRONG = 7.8" in source and "BRISK = 5.6" in source
    assert "wind_speed_unit=ms" in source, (
        "the page asks Open-Meteo for a unit it then does not convert; if that changes "
        "back to kmh the gates above are silently wrong by 3.6×")


@needs_chrome
def test_the_verdict_is_the_sites_own_rose():
    """The real function, driven in the page, over every case at once.

    This used to be a second copy of the rule written in Python beside it — it could
    fail on the *numbers* changing and never on the *shape* — two copies of a rule drift
    apart. `window.__meteo.verdict` is the real
    one, and one probe runs the whole table rather than paying for six browsers.
    """
    answer = _probe_page("""
    var cases = %s;
    return cases.map(function (row) {
      return window.__meteo.verdict({ winds: row[0] }, row[1], row[2]).text;
    });
    """ % json.dumps([[winds, speed, direction] for winds, speed, direction, _ in VERDICTS]))
    assert answer == [expected for *_, expected in VERDICTS]


class TestTheSiteStrip:
    """Four pages published side by side under `public/` with no way between them are
    four orphans. The strip is the only thing every tool's page shares."""

    def test_the_page_you_are_on_is_not_a_link_to_itself(self):
        import parainsights_common as common

        strip = common.nav("meteo", depth=1)
        assert '<span class="is-on">Meteo</span>' in strip
        assert 'href="../meteo/"' not in strip

    def test_a_page_one_level_down_reaches_its_siblings(self):
        import parainsights_common as common

        strip = common.nav("airspace", depth=1)
        assert 'href="../meteo/"' in strip
        # The report has its own address since October 2026, one level down like the rest.
        assert 'href="../flights/"' in strip

    def test_the_report_at_the_top_level_does_not_climb(self):
        import parainsights_common as common

        strip = common.nav("flights", depth=0)
        assert 'href="meteo/"' in strip
        assert ".." not in strip

    def test_every_tool_is_in_the_strip(self):
        import parainsights_common as common

        keys = {key for key, _, _ in common.PAGES}
        assert keys == {"flights", "airspace", "meteo"}


# ------------------------------------------- the sounding, in a browser
#
# What this page draws about the air — the layer that stops the day, and the numbers under
# the pointer — is JavaScript reading a forecast, and neither can be checked from Python
# without writing a second copy of the rule, and a second copy drifts. So instead the real
# page runs in a real browser with `fetch`
# answering from a profile built here: an inversion at a height this file chose, and a
# wind that turns through north so the interpolation has something to get wrong.
#
# This is also the harness `docs/meteo.md` asked for under "the verdict rule needs a
# browser test".

_LEVEL_HEIGHT = {1000: 110, 975: 330, 950: 540, 925: 760, 900: 990,
                 850: 1460, 800: 1950, 700: 3000, 600: 4200, 500: 5600}

# 7 °C/km through the day's working layer, then an inversion between 900 and 850 hPa —
# 990 to 1 460 m, warming 1.5 °C through it — and 6.5 above. A real capping layer, at a
# height nothing in the page can have guessed.
_INVERSION = (900, 850)


def _fake_profile(hours: int = 96) -> dict:
    """An Open-Meteo pressure-level answer, built to have one known feature in it."""
    ground, surface_t = 400.0, 26.0
    hourly: dict[str, list] = {"time": []}
    start = dt.datetime(2026, 8, 11, 0, 0)
    for h in range(hours):
        hourly["time"].append((start + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M"))
    hourly["temperature_2m"] = [surface_t] * hours
    hourly["dew_point_2m"] = [10.0] * hours
    hourly["cloud_cover"] = [20.0] * hours
    hourly["boundary_layer_height"] = [1200.0] * hours
    hourly["wind_speed_10m"] = [12.0] * hours
    hourly["wind_direction_10m"] = [180.0] * hours

    def temperature(level: int) -> float:
        height = _LEVEL_HEIGHT[level]
        if height <= _LEVEL_HEIGHT[_INVERSION[0]]:
            return surface_t - 7.0 * (height - ground) / 1000
        top = surface_t - 7.0 * (_LEVEL_HEIGHT[_INVERSION[0]] - ground) / 1000
        if height <= _LEVEL_HEIGHT[_INVERSION[1]]:
            return top + 1.5 * ((height - _LEVEL_HEIGHT[_INVERSION[0]])
                                / (_LEVEL_HEIGHT[_INVERSION[1]]
                                   - _LEVEL_HEIGHT[_INVERSION[0]]))
        return (top + 1.5) - 6.5 * (height - _LEVEL_HEIGHT[_INVERSION[1]]) / 1000

    for level in render_html.LEVELS:
        hourly[f"geopotential_height_{level}hPa"] = [float(_LEVEL_HEIGHT[level])] * hours
        hourly[f"temperature_{level}hPa"] = [round(temperature(level), 2)] * hours
        hourly[f"dew_point_{level}hPa"] = [round(temperature(level) - 9, 2)] * hours
        hourly[f"cloud_cover_{level}hPa"] = [10.0] * hours
        hourly[f"wind_speed_{level}hPa"] = [20.0 if level != 925 else 40.0] * hours
        # 350 at 950 hPa and 010 at 925: averaged as numbers that is 180 — due south,
        # the exact opposite of the answer — which is why the readout interpolates the
        # components instead.
        hourly[f"wind_direction_{level}hPa"] = [
            {950: 350.0, 925: 10.0}.get(level, 270.0)] * hours
    return {"elevation": ground, "hourly": hourly}


# ICON-D2's run ends at 18:00 on the fixture's second day — the page's "tomorrow" — so
# today and tomorrow afternoon are D2, tomorrow evening is the blend, and later is ICON-EU.
# The stub answers both models' metadata with it; `utc_offset_seconds` is absent from the
# fixture, so local and UTC are the same clock here.
_FAKE_META = {
    "data_end_time": int(dt.datetime(2026, 8, 12, 18, tzinfo=dt.timezone.utc).timestamp()),
    "last_run_initialisation_time": int(
        dt.datetime(2026, 8, 10, 15, tzinfo=dt.timezone.utc).timestamp()),
}


def _as_two_models(profile: dict) -> dict:
    """The profile as Open-Meteo sends it when asked for two models at once: every key
    carrying its model's name, ICON's with no boundary layer and IFS's with one. The page
    has to take each field from the right one, and a stub that answered in the old shape
    would pass whether it did or not."""
    hourly = {"time": profile["hourly"]["time"]}
    for key, values in profile["hourly"].items():
        if key == "time":
            continue
        hourly[f"{key}_ecmwf_ifs"] = [None if v is None else v - 500 for v in values] \
            if key != "boundary_layer_height" else values
        hourly[f"{key}_icon_seamless"] = values if key != "boundary_layer_height" \
            else [None] * len(values)
    return {**profile, "hourly": hourly}


# A 1 x 1 PNG for every flymet meteogram the page asks for. The page loads flymet's
# picture as an <img>, which the `fetch` stub cannot answer: left pointing at flymet.cz,
# every run of these tests reached the internet, and offline the image failed, the page
# swapped its caption for "flymet has no meteogram", and a test failed for a reason that
# had nothing to do with the code.
_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
_FLYMET_HOST = sources.FLYMET_INDEX.split("/meteogram/")[0]


@contextlib.contextmanager
def _local_flymet():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(_PIXEL)))
            self.end_headers()
            self.wfile.write(_PIXEL)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


# The takeoff a returning reader has chosen, for every probe that does not ask for an
# empty page: the one the page used to choose by itself on a first visit, before it
# opened the picker instead — under the stub's wind every takeoff with a rose is "too
# strong", so it was the first without one.
_REMEMBERED = [next(i for i, s in enumerate(render_html.SITES) if not s["winds"])]


def _probe_page(body: str, *, site_count: int = 3, hold: bool = False,
                remembered: list | None = _REMEMBERED) -> dict:
    """Run the real meteo page against a stubbed Open-Meteo and return what `body` says.
    `remembered` is the takeoffs chosen on an earlier visit; None is a first visit."""
    chrome = CHROME
    profile = json.dumps(_as_two_models(_fake_profile()))
    surface = json.dumps([{
        "hourly": {
            "time": _fake_profile()["hourly"]["time"],
            "wind_speed_10m": [12.0] * 96,
            "wind_direction_10m": [180.0] * 96,
            "temperature_2m": [26.0] * 96,
            "cloud_cover": [20.0] * 96,
            "cape": [200.0] * 96,
        }
    }] * len(render_html.SITES))
    stub = """
    <script>
    window.__profile = %s;
    window.__surface = %s;
    // Every request this page makes, answered from the two objects above. The URL tells
    // them apart the same way the page builds them: only the profile call asks for
    // geopotential height.
    window.__meta = %s;
    // `hold`: the day's forecast waits until `__release()`, to see the page before it.
    window.__held = %s;
    var released = null;
    window.__release = function () { if (released) released(); };
    (function (remembered) {
      var key = 'parainsights.meteo.sites';
      try {
        if (remembered) {
          localStorage.setItem(key, JSON.stringify(remembered));
          localStorage.setItem(key + '.order', JSON.stringify(remembered));
        } else { localStorage.removeItem(key); localStorage.removeItem(key + '.order'); }
      } catch (error) { /* file:// without storage: a first visit */ }
    })(%s);
    window.fetch = function (url) {
      var surfaceAsk = String(url).indexOf('meta.json') < 0 && String(url).indexOf('geopotential_height') < 0;
      if (window.__held && surfaceAsk) {
        return new Promise(function (resolve) { released = resolve; }).then(function () {
          return { ok: true, json: function () { return Promise.resolve(JSON.parse(JSON.stringify(window.__surface))); } };
        });
      }
      var body = String(url).indexOf('meta.json') >= 0 ? window.__meta
        : String(url).indexOf('geopotential_height') >= 0
        ? window.__profile : window.__surface;
      return Promise.resolve({ ok: true, json: function () {
        return Promise.resolve(JSON.parse(JSON.stringify(body)));
      } });
    };
    </script>
    """ % (profile, surface, json.dumps(_FAKE_META), "true" if hold else "false",
       json.dumps(remembered))
    page = cli.page(render_html.body(), "Meteo")
    assert _FLYMET_HOST in page, "flymet's host moved; this test rewrites it by hand"
    probe = """
    <pre id="probe-out"></pre>
    <script>
    window.addEventListener('load', function () { setTimeout(function () {
      var out;
      function put(value) { document.getElementById('probe-out').textContent = JSON.stringify(value); }
      try { out = (function () { %s })(); }
      catch (error) { out = { error: String((error && error.stack) || error) }; }
      if (out && typeof out.then === 'function') {
        out.then(put, function (error) { put({ error: String((error && error.stack) || error) }); });
      } else put(out);
    }, 700); });
    </script>
    """ % body
    with tempfile.TemporaryDirectory() as folder, _local_flymet() as flymet:
        target = Path(folder) / "meteo.html"
        target.write_text(stub + page.replace(_FLYMET_HOST, flymet) + probe, encoding="utf-8")
        out = subprocess.run([chrome, *CHROME_FLAGS, target.as_uri()],
                             capture_output=True, text=True, timeout=180).stdout
    found = re.search(r'<pre id="probe-out">(.*?)</pre>', out, re.S)
    assert found, out[-2000:]
    answer = json.loads(found.group(1) or "null")
    assert answer and "error" not in answer, answer
    return answer


@needs_chrome
def test_the_capping_layer_is_found_where_the_air_stops_cooling():
    """The whole point of shading it: a pilot reading two lines against a scale should
    not have to work out where the lapse rate goes stable. The fixture puts an inversion
    between 990 m and 1 460 m and nothing else, so the answer is checkable."""
    answer = _probe_page("""
    var m = window.__meteo;
    var hourly = m.state.profile.hourly;
    var bands = m.cappingLayers(hourly, m.at(), m.state.profile.elevation, 4000);
    return { bands: bands, lapse: bands.length ? bands[0].lapse : null };
    """)
    assert len(answer["bands"]) == 1, answer["bands"]
    band = answer["bands"][0]
    assert band["base"] == pytest.approx(990, abs=1)
    assert band["top"] == pytest.approx(1460, abs=1)
    assert band["inversion"] is True, "air that warms with height is an inversion"
    # +1.5 °C over 470 m is a lapse of -3.2 °C/km.
    assert answer["lapse"] == pytest.approx(-3.2, abs=0.2)


@needs_chrome
def test_a_working_layer_is_not_shaded():
    """The failure that would matter more than missing one: shading the whole chart. A
    day cooling at 7 °C/km has no lid in it and must be drawn without one."""
    answer = _probe_page("""
    var m = window.__meteo;
    var hourly = m.state.profile.hourly;
    var ground = m.state.profile.elevation;
    // The fixture's inversion straightened out: every level put back on one 7 °C/km line
    // from the surface, so there is nothing anywhere for the rule to find.
    %s.forEach(function (level) {
      var z = hourly['geopotential_height_' + level + 'hPa'];
      hourly['temperature_' + level + 'hPa'] = z.map(function (height) {
        return 26 - 7 * (height - ground) / 1000;
      });
    });
    var bands = m.cappingLayers(hourly, m.at(), ground, 4000);
    return { bands: bands };
    """ % json.dumps(list(render_html.LEVELS)))
    assert answer["bands"] == []


@needs_chrome
def test_the_readout_names_the_height_the_pointer_is_at():
    """The pointer and the chart have to agree about which height a pixel is, and they
    are written in two places — the drawing and the handler. Half the chart is 2 000 m,
    and a readout that says 1 700 there is worse than no readout."""
    answer = _probe_page("""
    var canvas = document.getElementById('met-sounding');
    var box = canvas.getBoundingClientRect();
    // Exactly half way down the plotting area, which is 2 000 m of a 4 000 m chart.
    var mid = box.top + 10 + (box.height - 10 - 24) / 2;
    canvas.dispatchEvent(new PointerEvent('pointermove', {
      clientX: box.left + box.width / 2, clientY: mid,
      bubbles: true, pointerType: 'mouse' }));
    var at = window.__meteo.state.probe;
    canvas.dispatchEvent(new PointerEvent('pointerleave', {
      clientX: box.left, clientY: box.top, bubbles: true, pointerType: 'mouse' }));
    return { at: at, after: window.__meteo.state.probe };
    """)
    assert answer["at"] == pytest.approx(2000, abs=25)
    assert answer["after"] is None, "the readout stayed up after the pointer left"


@needs_chrome
def test_the_wind_between_two_levels_does_not_go_the_wrong_way():
    """350° at 950 hPa and 010° at 925 is a wind backing through north, and the mean of
    the two numbers is 180 — due south, the one answer a pilot would act on and be
    exactly wrong about. Interpolating the components is what avoids it."""
    answer = _probe_page("""
    var m = window.__meteo;
    var hourly = m.state.profile.hourly;
    // Half way between 950 hPa (540 m) and 925 hPa (760 m).
    var here = m.sampleProfile(hourly, m.at(), 650, m.state.profile.elevation);
    return { dir: here.dir, speed: here.speed };
    """)
    assert answer["dir"] == pytest.approx(0, abs=12) or answer["dir"] == pytest.approx(
        360, abs=12), f"the wind came out at {answer['dir']}°"
    # Two winds 20° apart barely cancel, so the speed stays between the two.
    assert 20 < answer["speed"] < 40


@needs_chrome
def test_flymet_is_shown_for_today_and_tomorrow_and_not_beyond():
    """flymet publishes two days. The third day of the strip must show nothing rather
    than yesterday's picture under a Thursday heading."""
    answer = _probe_page("""
    // In the takeoff's own column, under its charts (the redesign).
    var seen = [];
    for (var day = 0; day < 4; day++) {
      window.__meteo.state.day = day;
      window.__meteo.draw();
      var list = document.querySelector('.met-col-fly');
      var image = list.querySelector('img');
      seen.push({ day: day, hidden: list.hidden,
                  src: image ? image.getAttribute('src') : null,
                  // Read per day: the panel is emptied on a day flymet has nothing for,
                  // so reading it after the loop reads the empty one.
                  caption: list.textContent });
    }
    return { seen: seen };
    """)
    today, tomorrow, third, fourth = answer["seen"]
    assert not today["hidden"] and "/meteogram/" in today["src"]
    assert not tomorrow["hidden"] and "/meteogram2/" in tomorrow["src"]
    assert third["hidden"] and fourth["hidden"]
    assert " km" in today["caption"] and "flymet" in today["caption"]



@needs_chrome
def test_flymet_carries_the_hour_on_its_own_utc_axis():
    """The bar across flymet's picture stands where the slider's Prague hour falls on
    flymet's UTC axis: 00:00 at x 65.5, 24:00 at x 962.5 of its 1024-wide frame — and
    moves with the slider without the picture being fetched again."""
    import datetime
    import zoneinfo

    answer = _probe_page("""
    var m = window.__meteo;
    m.state.day = 0;
    var seen = [];
    [9, 14].forEach(function (hour) {
      m.state.hour = hour;
      m.draw();
      var figure = document.querySelector('.met-col-fly');
      var svg = figure.querySelector('.met-fly-frame svg');
      seen.push({ hour: hour, utc: Number(svg.dataset.utc),
                  bars: svg.querySelectorAll('.met-fly-bar').length,
                  x: svg.querySelectorAll('.met-fly-bar')[0].getAttribute('x1'),
                  image: figure.querySelector('img') });
    });
    return { seen: seen.map(function (s) { return { hour: s.hour, utc: s.utc, bars: s.bars, x: Number(s.x) }; }),
             same: seen[0].image === seen[1].image };
    """)
    today = datetime.date.today()
    for s in answer["seen"]:
        local = datetime.datetime(today.year, today.month, today.day, s["hour"],
                                  tzinfo=zoneinfo.ZoneInfo("Europe/Prague"))
        utc = local.astimezone(datetime.timezone.utc).hour
        assert s["utc"] == utc
        assert s["x"] == pytest.approx(65.5 + 897 * utc / 24, abs=0.01)
        assert s["bars"] == 4, "one segment per panel, clear of the hour labels"
    assert answer["same"], "the slider moved the bar, not the picture"

# ------------------------------------------- choosing takeoffs, in a browser
#
# The picker used to be a 159-row list holding the top-left corner of the page: it was
# the first thing a reader met, it needed scrolling to get past, and it stayed there for
# as long as the page was open. It is a dialog now, and the page keeps up to three
# takeoffs and compares them. These are the behaviours that rework has to have, and the
# ones a screenshot cannot check.


@needs_chrome
class TestChoosingTakeoffs:
    def test_a_first_visit_chooses_nothing_and_opens_the_picker(self):
        """The page used to choose the day's best-ranked takeoff, a hill the reader may
        never fly. Now nothing is chosen, + is lit, and the ranked list is open."""
        answer = _probe_page("""
        var m = window.__meteo;
        var add = document.getElementById('met-add');
        var open = document.getElementById('met-modal').open === true;
        var lit = add.classList.contains('is-invite');
        m.add(0);
        return { chosen: m.chosen().length, open: open, lit: lit,
                 rows: document.querySelectorAll('.met-site').length,
                 litAfter: add.classList.contains('is-invite') };
        """, remembered=None)
        assert answer["open"] is True, "the picker should open by itself"
        assert answer["rows"] == len(render_html.SITES)
        assert answer["lit"] is True
        assert answer["litAfter"] is False, "+ stays lit after a takeoff is chosen"

    def test_a_remembered_takeoff_opens_without_the_picker(self):
        answer = _probe_page("""
        var m = window.__meteo;
        return { chosen: m.chosen().length, focused: m.state.site,
                 open: document.getElementById('met-modal').open === true,
                 lit: document.getElementById('met-add').classList.contains('is-invite'),
                 panel: document.getElementById('met-panel').hidden,
                 chips: document.querySelectorAll('.met-pick').length };
        """)
        assert answer["chosen"] == 1
        assert answer["focused"] == _REMEMBERED[0]
        assert answer["open"] is False and answer["lit"] is False
        assert answer["panel"] is False
        assert answer["chips"] == 1

    def test_the_list_is_behind_the_dialog_and_not_on_the_page(self):
        """The whole point of the rework: 159 rows are not the page's furniture."""
        answer = _probe_page("""
        var modal = document.getElementById('met-modal');
        var before = modal.open === true;
        window.__meteo.open();
        return { openBefore: before, openAfter: modal.open === true,
                 rows: document.querySelectorAll('.met-site').length,
                 inDialog: !!document.getElementById('met-list').closest('dialog') };
        """)
        assert answer["openBefore"] is False, "the picker is open before it is asked for"
        assert answer["openAfter"] is True
        assert answer["inDialog"] is True
        assert answer["rows"] == len(render_html.SITES), "the dialog should hold the whole list"

    def test_searching_narrows_the_list(self):
        answer = _probe_page("""
        var m = window.__meteo;
        m.open();
        var all = document.querySelectorAll('.met-site').length;
        var search = document.getElementById('met-search');
        search.value = 'rana';
        search.dispatchEvent(new Event('input', { bubbles: true }));
        var narrowed = Array.prototype.map.call(
          document.querySelectorAll('.met-site-name'), function (n) { return n.textContent; });
        search.value = 'zzzznothing';
        search.dispatchEvent(new Event('input', { bubbles: true }));
        return { all: all, narrowed: narrowed,
                 empty: document.querySelectorAll('.met-empty').length };
        """)
        assert answer["all"] == len(render_html.SITES)
        # Typed without the accent, and it still finds Raná.
        assert answer["narrowed"] == ["Raná"], "searching for a real takeoff found nothing"
        assert answer["empty"] == 1, "a search with no hits must say so"

    def test_six_takeoffs_can_be_compared_and_a_seventh_is_refused(self):
        """Six at a time since October 2026 (three was the first palette's limit). What
        matters here is that the refusal is explicit rather than an eviction the reader
        cannot see."""
        answer = _probe_page("""
        var m = window.__meteo;
        var picked = [];
        for (var i = 0; i < 9 && picked.length < 8; i++) {
          if (m.chosen().indexOf(i) < 0) { m.add(i); picked.push(i); }
        }
        return { chosen: m.chosen().length,
                 chips: document.querySelectorAll('.met-pick').length,
                 rows: document.querySelectorAll('.met-compare tbody tr').length,
                 hidden: document.getElementById('met-compare').hidden,
                 status: document.getElementById('met-status').textContent };
        """)
        assert answer["chosen"] == 6
        assert answer["chips"] == 6
        assert answer["hidden"] is False
        assert answer["rows"] == 6
        assert "6 at a time" in answer["status"]

    def test_the_comparison_appears_only_with_something_to_compare(self):
        answer = _probe_page("""
        var m = window.__meteo;
        var table = document.getElementById('met-compare');
        var alone = table.hidden;
        var free = null;
        for (var i = 0; i < 6; i++) if (m.chosen().indexOf(i) < 0) { free = i; break; }
        m.add(free);
        return { alone: alone, withTwo: table.hidden };
        """)
        assert answer["alone"] is True, "one takeoff is not a comparison"
        assert answer["withTwo"] is False

    def test_dropping_one_leaves_the_others_their_colour(self):
        """Colour follows the takeoff, not its position in the list. A reader who has
        just learned that the orange line is Raná must not find Raná blue a second later
        because something above it was removed."""
        answer = _probe_page("""
        var m = window.__meteo;
        var first = m.chosen()[0];
        var added = [];
        for (var i = 0; i < 8 && added.length < 2; i++) {
          if (m.chosen().indexOf(i) < 0) { m.add(i); added.push(i); }
        }
        var before = m.state.slots.slice();
        m.drop(first);
        return { before: before, after: m.state.slots.slice() };
        """)
        before, after = answer["before"], answer["after"]
        assert after[0] is None, "the dropped takeoff freed its own slot"
        assert after[1] == before[1] and after[2] == before[2], (
            f"the survivors were repainted: {before} became {after}")

    def test_focus_is_marked_on_the_takeoff_and_not_on_the_panel(self):
        """The panel used to carry the focused takeoff's name, elevation and wind rose
        in a heading above charts belonging to three of them — one hill's octants over
        three hills' numbers. Those facts live in each column now, and focus is a mark on
        the takeoff: its chip, its row, its column."""
        answer = _probe_page("""
        var m = window.__meteo;
        var free = null;
        for (var i = 0; i < 8; i++) if (m.chosen().indexOf(i) < 0) { free = i; break; }
        m.add(free);
        m.focus(free);
        var conf = JSON.parse(document.querySelector('.met-data').textContent);
        var column = document.querySelector('.met-col.is-focus');
        return { wanted: conf.sites[free].name,
                 column: column ? column.querySelector('.name').textContent : null,
                 heading: document.getElementById('met-name').textContent,
                 focusedRows: document.querySelectorAll('.met-compare tr.is-focus').length,
                 focusedChips: document.querySelectorAll('.met-pick.is-on').length,
                 focusedCols: document.querySelectorAll('.met-col.is-focus').length };
        """)
        assert answer["column"] == answer["wanted"]
        assert answer["focusedRows"] == 1
        assert answer["focusedChips"] == 1
        assert answer["focusedCols"] == 1
        assert answer["wanted"] not in answer["heading"], (
            "the panel heading names one takeoff again, over charts belonging to several")

    def test_every_line_on_the_meteogram_is_named_somewhere_that_is_not_colour(self):
        """Two of the three light-mode series sit under 3:1 against the panel, which the
        palette's relief rule permits only where identity is carried by something other
        than colour. Here it is carried twice: the legend and the comparison table."""
        answer = _probe_page("""
        var m = window.__meteo;
        for (var i = 0; i < 8 && m.chosen().length < 3; i++) {
          if (m.chosen().indexOf(i) < 0) m.add(i);
        }
        var conf = JSON.parse(document.querySelector('.met-data').textContent);
        return {
          chosen: m.chosen().map(function (i) { return conf.sites[i].name; }),
          keys: document.getElementById('met-keys').textContent,
          table: document.querySelector('.met-compare tbody').textContent
        };
        """)
        assert len(answer["chosen"]) == 3
        for name in answer["chosen"]:
            assert name in answer["keys"], f"{name} is on the chart but not in the legend"
            assert name in answer["table"], f"{name} is on the chart but not in the table"


def _mixed_layer(lapse: float = 10.5, inversion: float = 2.0) -> tuple[dict, float]:
    """A profile with a real mixed layer, and where the dry adiabat leaves it.

    The page's fixture is a flat 7 °C/km, which is *stable to dry convection* — under the
    adiabat's 9.8, a parcel is colder than the air from the ground up and there is no top
    to find. That is the right answer there and it draws nothing, so it cannot exercise
    the construction. This builds the ordinary summer shape instead: a mixed layer a
    little steeper than the adiabat, capped by an inversion at 1 460 m.

    The crossing is worked out here, from the two levels that bracket it, so the target
    the test measures against is computed independently of the page that draws it.
    """
    ground, surface = 400.0, 26.0
    kink = _LEVEL_HEIGHT[850]

    def air(height: float) -> float:
        if height <= kink:
            return surface - lapse * (height - ground) / 1000
        return surface - lapse * (kink - ground) / 1000 + inversion * (height - kink) / 1000

    def parcel(height: float) -> float:
        return surface - render_html.DRY_LAPSE * (height - ground) / 1000

    temperatures = {level: round(air(float(height)), 4)
                    for level, height in _LEVEL_HEIGHT.items() if height > ground}
    # The first level where the parcel is no longer the warmer of the two, and the last
    # where it still is: the crossing is between them, linear in height because both
    # lines are straight over that interval.
    above = sorted(h for h in _LEVEL_HEIGHT.values() if h > ground)
    under, over = None, None
    for height in above:
        gap = parcel(height) - air(height)
        if gap > 0:
            under = height
        elif under is not None:
            over = height
            break
    assert under is not None and over is not None, "the fixture has no crossing in it"
    low, high = parcel(under) - air(under), air(over) - parcel(over)
    return temperatures, under + low / (low + high) * (over - under)


@needs_chrome
def test_the_sounding_shows_where_the_parcel_stops():
    """"How is the thermal top deduced" is a fair question to ask of a dashed line with a
    number beside it, and the honest answer is that the line is the *model's* boundary
    layer height — handed over, not read off this chart. So the chart now draws the
    construction as well: the dry adiabat from the surface, stopping where it meets the
    temperature trace, with a ring on the crossing.

    Two cases, and the second matters as much as the first. On an ordinary mixed-layer
    day the crossing is found and matches an arithmetic done outside the page. On the flat
    7 °C/km fixture — stable to dry convection, so no parcel ever leaves the ground — it
    returns nothing and marks nothing, rather than putting a ring at an arbitrary height.
    """
    temperatures, expected = _mixed_layer()
    answer = _probe_page("""
    var m = window.__meteo;
    var index = m.chosen()[0];
    var profile = m.state.profiles[index];
    var before = document.querySelector('.met-col-sounding').__drawn.parcelTop;
    var wanted = %s;
    Object.keys(wanted).forEach(function (level) {
      var series = profile.hourly['temperature_' + level + 'hPa'];
      for (var i = 0; i < series.length; i++) series[i] = wanted[level];
    });
    m.draw();
    var drawn = document.querySelector('.met-col-sounding').__drawn;
    return { stable: before, mixed: drawn.parcelTop, top: drawn.thermalTop,
             ground: drawn.ground };
    """ % json.dumps({str(k): v for k, v in temperatures.items()}))

    assert answer["stable"] is None, (
        "a 7 °C/km profile is stable to dry convection and has no parcel top to mark")
    assert answer["mixed"] == pytest.approx(expected, abs=2), (
        f"the parcel stops at {answer['mixed']} m, not the {expected:.0f} m the two "
        "bracketing levels put it at")
    assert answer["ground"] < answer["mixed"], "the parcel stopped at or under the ground"


def test_the_dry_adiabat_is_one_number_on_both_sides():
    """The caption quotes it and the script constructs the parcel with it, the same shape
    as `CAP_LAPSE` — two copies that must not drift."""
    assert f"var DRY_LAPSE = {render_html.DRY_LAPSE};" in render_html.SCRIPT
    assert f"{render_html.DRY_LAPSE:.1f} °C/km" in render_html.body()


@needs_chrome
def test_the_charts_fill_the_row_however_many_takeoffs_are_chosen():
    """The columns were capped at 340 px, which is what three of them come to — so three
    filled the panel and one used a third of it, with two thirds of the row empty beside
    the chart the reader had asked to look at.

    Three things are asserted, and the third is the one that bites. The row is filled at
    every count; the sounding keeps its 380:300 shape, because a sounding widened against
    a fixed height flattens the lapse rate it exists to show; and the canvas *backing
    store* matches the box, which is what says the chart was drawn at the size it ended
    up — `fit()` measures the box, so a layout change applied after the draw leaves every
    chart drawn for the width it used to have and quietly upscaled.
    """
    answer = _probe_page("""
    var m = window.__meteo;
    function shape() {
      var row = document.getElementById('met-columns').getBoundingClientRect();
      var cells = document.querySelectorAll('.met-col');
      var canvases = document.querySelectorAll('.met-col .met-canvas');
      var left = Infinity, right = -Infinity, drawn = true, ratio = null;
      Array.prototype.forEach.call(canvases, function (canvas) {
        var box = canvas.getBoundingClientRect();
        left = Math.min(left, box.left); right = Math.max(right, box.right);
        // devicePixelRatio is 1 headless, so the backing store is the box in CSS px.
        if (Math.abs(canvas.width - box.width) > 2) drawn = false;
      });
      var sounding = document.querySelector('.met-col-sounding').getBoundingClientRect();
      ratio = Math.round(sounding.width / sounding.height * 100) / 100;
      return { columns: cells.length, filled: Math.round((right - left) / row.width * 100),
               drawn: drawn, ratio: ratio, width: Math.round(sounding.width) };
    }
    var seen = [shape()];
    var free = [];
    for (var i = 0; i < 12 && free.length < 2; i++) if (m.chosen().indexOf(i) < 0) free.push(i);
    m.add(free[0]); seen.push(shape());
    m.add(free[1]); seen.push(shape());
    return { seen: seen };
    """)
    one, two, three = answer["seen"]
    assert (one["columns"], two["columns"], three["columns"]) == (1, 2, 3)
    for count, at in (("one", one), ("two", two), ("three", three)):
        assert at["filled"] >= 95, (
            f"with {count} chosen the charts cover {at['filled']}% of the row")
        assert at["ratio"] == pytest.approx(380 / 300, abs=0.02), (
            f"with {count} chosen the sounding is {at['ratio']}, not its own 1.27")
        assert at["drawn"], (
            f"with {count} chosen a chart was drawn for a different width than it got")
    # A lone takeoff puts its two charts side by side, so they come out the size a pair's
    # do rather than one 839 px sounding under a 645 px meteogram.
    assert one["width"] == two["width"], (
        f"one takeoff drew a {one['width']} px sounding against a pair's {two['width']}")


@needs_chrome
def test_past_three_takeoffs_the_columns_scroll_and_can_be_reordered():
    """Three columns to the row at most; a fourth is scrolled to, not squeezed in. A
    takeoff moved keeps its colour, and the chips, the table and the columns follow."""
    answer = _probe_page("""
    var m = window.__meteo;
    var free = [];
    for (var i = 0; i < 20 && m.chosen().length + free.length < 4; i++)
      if (m.chosen().indexOf(i) < 0) free.push(i);
    free.forEach(function (i) { m.add(i); });
    var box = document.getElementById('met-columns');
    var cells = document.querySelectorAll('.met-col');
    var shown = Array.prototype.filter.call(cells, function (cell) {
      var r = cell.getBoundingClientRect(), b = box.getBoundingClientRect();
      return r.left >= b.left - 1 && r.right <= b.right + 1;
    }).length;
    function order() {
      return { cols: Array.prototype.map.call(document.querySelectorAll('.met-col'),
                 function (c) { return Number(c.dataset.site); }),
               chips: Array.prototype.map.call(document.querySelectorAll('.met-pick'),
                 function (c) { return Number(c.dataset.site); }) };
    }
    var before = order();
    var last = before.cols[before.cols.length - 1];
    var colour = document.querySelector('.met-col[data-site="' + last + '"] .met-col-head i').style.background;
    m.move(last, 0);
    var after = order();
    return { columns: cells.length, shown: shown, scrolls: box.scrollWidth > box.clientWidth,
             before: before, after: after, colour: colour,
             colourAfter: document.querySelector('.met-col[data-site="' + last + '"] .met-col-head i').style.background,
             leftDisabled: document.querySelector('.met-col .met-col-move[data-by="-1"]').disabled };
    """)
    assert answer["columns"] == 4
    assert answer["shown"] == 3 and answer["scrolls"]
    moved = answer["before"]["cols"][-1]
    assert answer["after"]["cols"] == [moved] + answer["before"]["cols"][:-1]
    assert answer["after"]["chips"] == answer["after"]["cols"]
    assert answer["colourAfter"] == answer["colour"]
    assert answer["leftDisabled"] is True


@needs_chrome
def test_one_switcher_and_a_takeoff_is_removed_from_its_column():
    """The chosen takeoffs are one switcher in the sticky row — no chips, no second
    switcher over the columns — and a takeoff is removed by the × under its own name."""
    answer = _probe_page("""
    var m = window.__meteo;
    for (var i = 0; i < 20 && m.chosen().length < 3; i++) if (m.chosen().indexOf(i) < 0) m.add(i);
    var before = m.chosen().slice();
    var gone = before[1];
    var pick = document.querySelector('.met-pick[data-site="' + before[2] + '"]');
    pick.click();
    var focused = m.state.site;
    document.querySelector('.met-col[data-site="' + gone + '"] .met-col-drop').click();
    return { switchers: document.querySelectorAll('.met-sticky .met-picks .seg').length,
             chips: document.querySelectorAll('.met-chip, #met-swipe').length,
             focused: focused, wanted: before[2], gone: gone, after: m.chosen(),
             picks: document.querySelectorAll('.met-pick').length,
             cols: document.querySelectorAll('.met-col').length };
    """)
    assert answer["switchers"] == 1
    assert answer["chips"] == 0
    assert answer["focused"] == answer["wanted"]
    assert answer["gone"] not in answer["after"] and len(answer["after"]) == 2
    assert answer["picks"] == 2 and answer["cols"] == 2


@needs_chrome
def test_the_day_applies_to_everything_the_hour_does():
    """The day and the hour are one setting with two controls, and the two controls each
    carried their own hand-written list of redraws. They drifted: the hour repainted the
    comparison table and the day did not, so picking tomorrow moved every chart and left
    the numbers under them describing today.

    This drives the *button*, which is the part that was broken. The existing day test
    sets `state.day` and calls `draw()` — it reaches past the handler, so it passed
    throughout. The tomorrow-shaped hole in the data is put there by this test rather
    than by the fixture, because the fixture is deliberately flat: every hour of every
    day holds the same numbers, and a page that ignored the day entirely would agree
    with one that honoured it.
    """
    answer = _probe_page("""
    var m = window.__meteo;
    var free = null;
    for (var i = 0; i < 8; i++) if (m.chosen().indexOf(i) < 0) { free = i; break; }
    m.add(free);

    // Mark tomorrow, in the series the comparison's wind column reads.
    var chosen = m.chosen();
    var times = m.state.surface[chosen[0]].hourly.time;
    var start = new Date(times[0].replace(' ', 'T'));
    var wanted = new Date(start);
    wanted.setHours(0, 0, 0, 0); wanted.setDate(wanted.getDate() + 1);
    wanted.setHours(m.state.hour);
    var mark = 0;
    for (var t = 0; t < times.length; t++) {
      if (new Date(times[t].replace(' ', 'T')).getTime() >= wanted.getTime()) { mark = t; break; }
    }
    chosen.forEach(function (index) {
      m.state.surface[index].hourly.wind_speed_10m[mark] = 33.0;
    });

    var before = document.querySelector('.met-compare tbody').textContent;
    var buttons = document.querySelectorAll('#met-days button');
    buttons[1].click();
    // Re-queried, because `drawDays` rebuilds the strip inside the handler: the element
    // clicked is detached by the time the click returns, and still wears its old class.
    var now = document.querySelectorAll('#met-days button');
    return { before: before,
             after: document.querySelector('.met-compare tbody').textContent,
             day: m.state.day,
             pressed: now[1].className, was: now[0].className };
    """)
    assert answer["day"] == 1, "clicking tomorrow did not select it"
    assert "is-on" in answer["pressed"], "the pressed day is not marked"
    assert "is-on" not in answer["was"], "today is still marked as well as tomorrow"
    assert "33.0 m/s" not in answer["before"], "the fixture already read 33.0 today"
    assert "33.0 m/s" in answer["after"], (
        "the comparison table still describes today after picking tomorrow")


@needs_chrome
def test_the_hour_applies_to_everything_at_once():
    """The slider used to sit under the sounding, where it read as a control for that one
    chart. It ranks the list, fills the comparison and picks the sounding's hour."""
    answer = _probe_page("""
    var m = window.__meteo;
    var free = null;
    for (var i = 0; i < 8; i++) if (m.chosen().indexOf(i) < 0) { free = i; break; }
    m.add(free);
    var input = document.getElementById('met-hour-input');
    input.value = '9';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return { hour: m.state.hour,
             readout: document.getElementById('met-hour-readout').textContent,
             inHead: !!document.getElementById('met-hour-input').closest('.met-head'),
             rows: document.querySelectorAll('.met-compare tbody tr').length };
    """)
    assert answer["hour"] == 9
    assert answer["readout"] == "9:00"
    assert answer["inHead"] is True
    assert answer["rows"] == 2


@needs_chrome
class TestTheSoundingsAndFlymetCompareToo:
    """The comparison started as a table and one shared meteogram. The sounding and
    flymet's picture were still the focused takeoff's alone, which left the two charts a
    pilot actually argues over — *is there a lid on it, and what does the other model
    think* — answerable for one hill at a time.
    """

    def _with_three(self, body: str) -> dict:
        return _probe_page("""
        var m = window.__meteo;
        for (var i = 0; i < 10 && m.chosen().length < 3; i++) {
          if (m.chosen().indexOf(i) < 0) m.add(i);
        }
        %s
        """ % body)

    def test_one_sounding_per_chosen_takeoff(self):
        answer = self._with_three("""
        var conf = JSON.parse(document.querySelector('.met-data').textContent);
        var cells = document.querySelectorAll('.met-col');
        return { cells: cells.length,
                 canvases: document.querySelectorAll('.met-col-sounding').length,
                 names: Array.prototype.map.call(cells, function (cell) {
                   return cell.querySelector('.met-col-head .name').textContent; }),
                 chosen: m.chosen().map(function (i) { return conf.sites[i].name; }) };
        """)
        assert answer["cells"] == 3
        assert answer["canvases"] == 3
        assert answer["names"] == answer["chosen"], (
            "the soundings are in a different order from the chips beside them")

    def test_the_focused_one_keeps_the_id_the_page_has_always_used(self):
        """Small multiples must not cost the pointer readout its anchor: one known
        element, not "whichever sounding happens to be first"."""
        answer = self._with_three("""
        var focused = document.getElementById('met-sounding');
        var cell = focused && focused.closest('.met-col');
        var conf = JSON.parse(document.querySelector('.met-data').textContent);
        return { found: !!focused,
                 site: cell ? Number(cell.dataset.site) : null,
                 focus: m.state.site,
                 marked: document.querySelectorAll('.met-col.is-focus').length };
        """)
        assert answer["found"] is True
        assert answer["site"] == answer["focus"]
        assert answer["marked"] == 1

    def test_pointing_at_one_sounding_reads_all_of_them_at_that_height(self):
        """The whole reason three soundings are worth having on one page. Point at
        1 500 m over one hill and the other two answer at 1 500 m, because "what is the
        air doing at the height I will be at" is the question being asked of all three."""
        answer = self._with_three("""
        var canvases = document.querySelectorAll('.met-col-sounding');
        var second = canvases[1];
        var box = second.getBoundingClientRect();
        // Half way down the plot, which is 2 000 m of a 4 000 m chart.
        var mid = box.top + 10 + (box.height - 10 - 24) / 2;
        second.dispatchEvent(new PointerEvent('pointermove', {
          clientX: box.left + box.width / 2, clientY: mid,
          bubbles: true, pointerType: 'mouse' }));
        var probe = m.state.probe;
        second.dispatchEvent(new PointerEvent('pointerleave', {
          clientX: box.left, clientY: box.top, bubbles: true, pointerType: 'mouse' }));
        return { probe: probe, after: m.state.probe, canvases: canvases.length };
        """)
        assert answer["canvases"] == 3
        assert answer["probe"] == pytest.approx(2000, abs=25), (
            "a sounding that is not the first one reads the wrong height")
        assert answer["after"] is None

    def test_a_flymet_picture_for_every_chosen_takeoff(self):
        answer = self._with_three("""
        var conf = JSON.parse(document.querySelector('.met-data').textContent);
        var near = conf.flymet.near;
        var stations = {};
        m.chosen().forEach(function (i) { if (near[i]) stations[near[i].slug] = 1; });
        var withStation = m.chosen().filter(function (i) { return near[i]; }).length;
        return { figures: document.querySelectorAll('.met-col-fly:not([hidden])').length,
                 images: document.querySelectorAll('.met-col-fly img').length,
                 wanted: withStation };
        """)
        assert answer["figures"] == answer["wanted"], (
            "every chosen takeoff with a station shows its meteogram in its column")
        assert answer["images"] == answer["figures"]

    def test_two_takeoffs_sharing_an_airfield_ask_flymet_once(self, monkeypatch):
        """Two hills sharing their nearest airfield: each column shows the meteogram under
        its own charts, side by side as the redesign wants, and both ask for the same
        address — so flymet is fetched once and the browser shows it twice. The chosen
        list is short enough that no two share one today, so the first two are made to."""
        real = render_html.nearest_stations

        def shared(*args, **kwargs):
            found = real(*args, **kwargs)
            assert found[0] and found[1], "the first two takeoffs need a station each"
            found[1] = dict(found[0])
            return found

        monkeypatch.setattr(render_html, "nearest_stations", shared)
        answer = _probe_page("""
        var m = window.__meteo;
        var conf = JSON.parse(document.querySelector('.met-data').textContent);
        var near = conf.flymet.near;
        // Find two takeoffs the committed data puts at the same station.
        var bySlug = {}, pair = null;
        for (var i = 0; i < conf.sites.length && !pair; i++) {
          if (!near[i]) continue;
          if (bySlug[near[i].slug] !== undefined) pair = [bySlug[near[i].slug], i];
          else bySlug[near[i].slug] = i;
        }
        if (!pair) return { skipped: true };
        m.chosen().slice().forEach(function (i) { m.drop(i); });
        m.add(pair[0]);
        m.add(pair[1]);
        var images = document.querySelectorAll('.met-col-fly:not([hidden]) img');
        return {
          skipped: false,
          figures: images.length,
          sources: Array.prototype.map.call(images, function (i) { return i.getAttribute('src'); })
        };
        """)
        assert not answer["skipped"], "no two takeoffs share an airfield"
        assert answer["figures"] == 2, "each column shows its meteogram"
        assert answer["sources"][0] == answer["sources"][1], "the one picture, fetched once"


@needs_chrome
class TestEachChartMeansOneThing:
    """The combined meteogram carried every chosen takeoff's boundary layer *and* one
    takeoff's cloud, ground and cloudbase, with nothing on the frame saying which was
    which — so the cloud a reader was looking at belonged to a hill they might not have
    been thinking about. Split in two: a strip that is only the comparison, and a column
    per takeoff that is only that takeoff.
    """

    def _with_three(self, body: str) -> dict:
        return _probe_page("""
        var m = window.__meteo;
        for (var i = 0; i < 10 && m.chosen().length < 3; i++) {
          if (m.chosen().indexOf(i) < 0) m.add(i);
        }
        %s
        """ % body)

    def test_every_takeoff_gets_its_own_airgram_and_sounding(self):
        answer = self._with_three("""
        return { columns: document.querySelectorAll('.met-col').length,
                 grams: document.querySelectorAll('.met-col-air').length,
                 soundings: document.querySelectorAll('.met-col-sounding').length };
        """)
        assert answer["columns"] == 3
        assert answer["grams"] == 3, "cloud and cloudbase for one takeoff out of three"
        assert answer["soundings"] == 3

    def test_the_comparison_strip_holds_nothing_that_belongs_to_one_takeoff(self):
        """It draws boundary layers and axes. If cloud shading or a ground fill comes
        back to this frame, it is one hill's fact on a chart labelled with three."""
        source = render_html.SCRIPT
        strip = source[source.index("function drawStrip()"):source.index("function boundaryLayer")]
        assert "boundaryLayer" in strip
        for one_site_only in ("cloud_cover", "levelSeries", "cloudbase("):
            assert one_site_only not in strip, (
                f"{one_site_only} is back on the comparison strip")

    def test_the_strip_appears_only_with_something_to_compare(self):
        answer = _probe_page("""
        var m = window.__meteo;
        var strip = document.getElementById('met-strip');
        var alone = strip.hidden;
        var free = null;
        for (var i = 0; i < 6; i++) if (m.chosen().indexOf(i) < 0) { free = i; break; }
        m.add(free);
        return { alone: alone, withTwo: strip.hidden };
        """)
        assert answer["alone"] is True, "a comparison of one is the chart below it"
        assert answer["withTwo"] is False

    def test_each_column_carries_its_own_takeoff_s_rose_and_link(self):
        answer = self._with_three("""
        var conf = JSON.parse(document.querySelector('.met-data').textContent);
        return Array.prototype.map.call(document.querySelectorAll('.met-col'),
          function (cell) {
            var i = Number(cell.dataset.site);
            return { name: cell.querySelector('.name').textContent,
                     wanted: conf.sites[i].name,
                     rose: cell.querySelector('.met-col-rose span').textContent,
                     href: cell.querySelector('.met-col-head a.met-col-pge').getAttribute('href'),
                     id: String(conf.sites[i].id) };
          });
        """)
        for column in answer:
            assert column["name"] == column["wanted"]
            assert column["rose"], "no wind rose, not even the refusal to judge"
            assert column["id"] in column["href"], (
                "a column links to another takeoff's page on ParaglidingEarth")


@needs_chrome
def test_wind_is_metres_per_second_everywhere_it_is_printed():
    """One unit on the page, and it is the one a pilot says out loud. A page that mixes
    km/h in the table with m/s in the readout is worse than either."""
    answer = _probe_page("""
    var m = window.__meteo;
    var free = null;
    for (var i = 0; i < 8; i++) if (m.chosen().indexOf(i) < 0) { free = i; break; }
    m.add(free);
    m.open();
    var canvas = document.getElementById('met-sounding');
    var box = canvas.getBoundingClientRect();
    canvas.dispatchEvent(new PointerEvent('pointermove', {
      clientX: box.left + box.width / 2, clientY: box.top + box.height / 2,
      bubbles: true, pointerType: 'mouse' }));
    return { list: document.querySelector('.met-site-note').textContent,
             table: document.querySelector('.met-compare .wind').textContent,
             asked: window.__askedUrl || '' };
    """)
    assert "m/s" in answer["list"], "the picker still ranks in another unit"
    assert "m/s" in answer["table"]
    assert "km/h" not in answer["list"] + answer["table"]


def test_the_charts_leave_the_scroll_to_the_page():
    """A finger scrolls the page over the charts as anywhere else (October 2026): the
    sounding kept the vertical drag, and with the charts most of a phone's screen the
    page was hard to scroll. A tap reads; a held press drags the reading."""
    style = render_html.STYLE
    assert ".met-col-sounding, .met-col-air { touch-action: manipulation;" in style
    assert "pan-x; }" not in style


def _touch(kind, canvas_js, dx=0, dy=0):
    return f"""
    (function () {{
      var c = {canvas_js}, b = c.getBoundingClientRect();
      var t = new Touch({{ identifier: 1, target: c, clientX: b.left + b.width / 2 + {dx},
                           clientY: b.top + b.height / 2 + {dy} }});
      var e = new TouchEvent('{kind}', {{ touches: '{kind}' === 'touchend' ? [] : [t],
        changedTouches: [t], bubbles: true, cancelable: true }});
      c.dispatchEvent(e);
      return e.defaultPrevented;
    }})()"""


@needs_chrome
def test_a_tap_reads_the_sounding_and_a_drag_scrolls_past_it():
    answer = _probe_page(f"""
    var m = window.__meteo;
    var free = null;
    for (var i = 0; i < 8; i++) if (m.chosen().indexOf(i) < 0) {{ free = i; break; }}
    m.add(free);
    var c = "document.getElementById('met-sounding')";
    {_touch('touchstart', "document.getElementById('met-sounding')")};
    {_touch('touchend', "document.getElementById('met-sounding')")};
    var tapped = m.state.probe;
    // A drag straight away is a scroll: not cancelled, and no reading taken.
    {_touch('touchstart', "document.querySelector('.met-col-air')")};
    var cancelled = {_touch('touchmove', "document.querySelector('.met-col-air')", 0, 40)};
    {_touch('touchend', "document.querySelector('.met-col-air')", 0, 40)};
    return {{ tapped: tapped, cancelled: cancelled, cleared: m.state.probe,
              air: m.state.airProbe || null,
              action: getComputedStyle(document.getElementById('met-sounding')).touchAction }};
    """)
    assert answer["tapped"] is not None, "a tap read no height"
    assert answer["cancelled"] is False, "the chart kept the page from scrolling"
    assert answer["air"] is None, "a scroll over the airgram left a reading"
    assert answer["cleared"] is None, "touching elsewhere left the sounding's reading up"
    assert answer["action"] == "manipulation"


@needs_chrome
class TestTheSoundingSaysWhereTheDayStops:
    """"The *zadržná vrstva* is not visible" — and on a day with nothing stable under
    4 km it was not, because there was nothing to shade and the chart said so by drawing
    nothing at all. A blank chart and a chart that checked look identical, which is the
    rule this repository already applies to findings.
    """

    def test_a_capping_layer_is_shaded_and_counted(self):
        answer = _probe_page("""
        var canvas = document.getElementById('met-sounding');
        return canvas.__drawn;
        """)
        # The fixture puts an inversion between 990 m and 1 460 m and nothing else.
        assert answer["caps"] == 1

    def test_a_day_with_no_lid_still_says_something(self):
        answer = _probe_page("""
        var m = window.__meteo;
        var hourly = m.state.profile.hourly;
        // The fixture's inversion straightened out: one 7 °C/km line from the surface,
        // so there is nothing anywhere for the rule to find.
        %s.forEach(function (level) {
          var z = hourly['geopotential_height_' + level + 'hPa'];
          hourly['temperature_' + level + 'hPa'] = z.map(function (height) {
            return 26 - 7 * (height - 400) / 1000;
          });
        });
        m.draw();
        var canvas = document.getElementById('met-sounding');
        return canvas.__drawn;
        """ % json.dumps(list(render_html.LEVELS)))
        assert answer["caps"] == 0, "the fixture still has a lid in it"
        assert answer["thermalTop"] is not None, (
            "no lid and no thermal top: the chart about the shape of the column now says "
            "nothing at all about where the day stops")
        assert answer["thermalTop"] > answer["ground"]

    def test_the_thermal_top_is_the_models_own_number(self):
        answer = _probe_page("""
        var m = window.__meteo;
        var canvas = document.getElementById('met-sounding');
        var hourly = m.state.profile.hourly;
        var at = m.at();
        return { drawn: canvas.__drawn.thermalTop,
                 wanted: Math.round(m.state.profile.elevation
                                    + hourly.boundary_layer_height[at]) };
        """)
        assert answer["drawn"] == answer["wanted"]


@needs_chrome
class TestTheModelIsNamed:
    def test_the_label_follows_the_hour_from_icon_d2_to_icon_eu(self):
        """The forecast is ICON-D2 to its horizon and ICON-EU after, and a reader looking
        at Saturday should not be told it is the 2 km model."""
        answer = _probe_page("""
        var label = function () { return document.getElementById('met-model').textContent; };
        var pick = function (day) {
          document.querySelector('#met-days button[data-day="' + day + '"]').click();
          return label();
        };
        var today = label();
        var hour = document.getElementById('met-hour-input');
        hour.value = 17; hour.dispatchEvent(new Event('input', { bubbles: true }));
        var blend = pick(1);
        var later = pick(3);
        return { today: today, blend: blend, later: later };
        """)
        assert "ICON-D2 · 2 km" in answer["today"]
        assert "15 UTC run" in answer["today"]
        assert "ECMWF IFS" in answer["today"], "the boundary layer's own model is unnamed"
        assert "ICON-D2 → ICON-EU" in answer["blend"]
        assert "ICON-EU · 7 km" in answer["later"]

    def test_each_field_comes_from_its_own_model(self):
        """ICON for everything it has, IFS for the boundary layer only. The stub's IFS
        numbers are 500 lower on every other field, so taking one from the wrong model
        shows."""
        answer = _probe_page("""
        var m = window.__meteo;
        var p = m.state.profiles[m.chosen()[0]].hourly;
        return { blh: p.boundary_layer_height[14], t: p.temperature_2m[14],
                 t850: p.temperature_850hPa[14], leftovers: Object.keys(p).filter(
                   function (k) { return /_(icon_seamless|ecmwf_ifs)$/.test(k); }).length };
        """)
        assert answer["blh"] == 1200.0
        assert answer["t"] == 26.0
        assert answer["t850"] > 0
        assert answer["leftovers"] == 0


@needs_chrome
def test_the_two_thermal_tops_are_named_and_the_difference_explained():
    """The dashed model top and the parcel's ring are two estimates of one height, and
    they disagree by hundreds of metres on an ordinary day. The chart names both, a line
    under it gives the range, and the page's fold says what the two are."""
    temperatures, _ = _mixed_layer()
    answer = _probe_page("""
    var m = window.__meteo;
    var box = document.querySelector('.met-col-top');
    var stable = box.querySelector('.txt').textContent;
    var profile = m.state.profiles[m.chosen()[0]];
    var wanted = %s;
    Object.keys(wanted).forEach(function (level) {
      var series = profile.hourly['temperature_' + level + 'hPa'];
      for (var i = 0; i < series.length; i++) series[i] = wanted[level];
    });
    m.draw();
    var canvas = document.querySelector('.met-col-sounding');
    return { drawn: canvas.__drawn, hidden: box.hidden, stable: stable,
             summary: box.querySelector('.txt').textContent };
    """ % json.dumps(temperatures))
    assert "(model only)" in answer["stable"], answer["stable"]
    drawn = answer["drawn"]
    assert drawn["thermalTop"] and drawn["parcelTop"], drawn
    assert answer["hidden"] is False
    low, high = sorted((drawn["thermalTop"], drawn["parcelTop"]))
    shown = [int(n.replace(" ", "")) for n in
             re.findall(r"(\d[\d ]*) m", answer["summary"])]
    assert shown == [low, high], answer["summary"]
    # What the two are is said once, in the page's fold, not under every column.
    terms = render_html.body().split('class="gloss met-terms"')[1]
    assert "ECMWF" in terms and "parcel" in terms


@needs_chrome
def test_the_airgram_draws_the_day_and_reads_the_wind_under_the_pointer():
    """Wind by hour and height for the takeoff. The fixture's 925 hPa level, at 760 m,
    blows 40 m/s from 010° all day, between 20 m/s levels from 350° and 270° — so the
    readout at that height has to say 40 from the north, and the shading has to exist."""
    answer = _probe_page("""
    var canvas = document.querySelector('.met-col-air');
    var box = canvas.getBoundingClientRect();
    var top = 8, bottom = 22, ceiling = 4000;
    var y = box.top + top + (1 - 760 / ceiling) * (box.height - top - bottom);
    var x = box.left + 38 + (13 - 5) / 16 * (box.width - 38 - 8);
    canvas.dispatchEvent(new PointerEvent('pointermove', {
      clientX: x, clientY: y, bubbles: true, pointerType: 'mouse' }));
    var p = window.__meteo.state.airProbe, text = canvas.__readout;
    var probe = p && { hour: p.hour, metres: p.metres, speed: p.speed, dir: p.dir };
    canvas.dispatchEvent(new PointerEvent('pointerleave', {
      clientX: box.left, clientY: box.top, bubbles: true, pointerType: 'mouse' }));
    return { cells: Number(canvas.dataset.cells), probe: probe, text: text,
             after: canvas.__readout, gone: window.__meteo.state.airProbe, height: box.height };
    """)
    assert answer["cells"] > 17 * 20, answer
    probe = answer["probe"]
    assert probe["hour"] == 13
    assert probe["metres"] == pytest.approx(760, abs=15)
    assert probe["speed"] == pytest.approx(40, abs=1.5)
    assert probe["dir"] == pytest.approx(10, abs=3)
    assert "m/s from N" in answer["text"], answer["text"]
    assert answer["after"] == "" and answer["gone"] is None, (
        "the readout stayed up after the pointer left")


@needs_chrome
def test_nothing_moves_when_the_first_forecast_arrives():
    """Layout shift: the page once waited for the day's forecast with no column at all,
    and the first takeoff's arrived half a screen tall, pushing the page under it down
    (0.19 of the 0.23 measured on a phone). A remembered takeoff's column stands where it
    will be from the start (a first visit has none: it opens the picker); the status is a
    notice floating over the page, not a line in its header, and the day row is its
    height before its buttons are added."""
    answer = _probe_page("""
    function box(selector) {
      var r = document.querySelector(selector).getBoundingClientRect();
      return [Math.round(r.top), Math.round(r.left), Math.round(r.width), Math.round(r.height)];
    }
    var before = { air: box('.met-col-air'), sounding: box('.met-col-sounding'),
                   status: getComputedStyle(document.getElementById('met-status')).position,
                   days: document.getElementById('met-days').getBoundingClientRect().height };
    window.__release();
    return new Promise(function (done) { setTimeout(done, 600); }).then(function () {
      return { before: before, after: { air: box('.met-col-air'), sounding: box('.met-col-sounding') } };
    });
    """, hold=True)
    before, after = answer["before"], answer["after"]
    assert before["status"] == "fixed"
    assert before["days"] >= 44
    # The charts arrive exactly where the stand-in's were.
    assert before["air"] == after["air"] and before["sounding"] == after["sounding"], answer

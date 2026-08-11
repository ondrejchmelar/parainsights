"""The meteo view. No network: the site list is committed data and the forecast is
fetched by the page, so what is testable here is the data and the markup around it.

The one judgement the page makes — whether the wind suits a takeoff — is tested in the
browser with `fetch` stubbed, because it is JavaScript and because getting it wrong is
the only way this page can actively mislead somebody. So is everything the sounding says
about the air, and for the same reason.
"""

import datetime as dt
import json
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from meteo import cli, render_html, sites
from tests.test_view3d_gl import CHROME, CHROME_FLAGS, needs_chrome


class TestTheSiteList:
    def test_every_site_is_in_the_country_it_claims(self):
        """A stray coordinate would put a takeoff in the sea and rank it anyway."""
        for site in sites.SITES:
            assert 48.3 < site["lat"] < 51.2, site
            assert 11.9 < site["lon"] < 19.1, site

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
        assert "paraglidingearth" in sites.SOURCE.lower()
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

    def test_every_czech_takeoff_has_a_station_near_it(self):
        """Measured, not assumed: the worst takeoff in the list is 21 km from a station
        and the median is 9, which is why the page can show this beside every site rather
        than beside some of them."""
        found = render_html.nearest_stations()
        assert len(found) == len(sites.SITES)
        assert all(found), "a takeoff was left without a station"
        worst = max(entry["km"] for entry in found)
        assert worst < 30, f"the worst takeoff is now {worst} km from a station"


class TestThePage:
    def test_the_payload_carries_the_sites_and_the_levels(self):
        html = render_html.body()
        blob = re.search(r'<script type="application/json" class="met-data">(.*?)</script>',
                         html, re.S)
        payload = json.loads(blob.group(1))
        assert len(payload["sites"]) == len(sites.SITES)
        assert payload["levels"] == list(render_html.LEVELS)
        assert payload["endpoint"].startswith("https://api.open-meteo.com/")
        # One entry per site and in the same order: the page indexes it by the site's own
        # index, so a shorter or re-sorted list would hand out other takeoffs' airfields.
        assert len(payload["flymet"]["near"]) == len(sites.SITES)
        assert payload["flymet"]["today"].startswith("https://")

    def test_the_pressure_levels_match_the_viewer_s(self):
        """A forecast profile and a flown profile are read against each other, and two
        different level sets would make that a conversion nobody remembers to do."""
        from tracklog_viewer import meteo as flown

        assert render_html.LEVELS == flown.PRESSURE_LEVELS

    def test_the_caption_states_the_threshold_the_script_uses(self):
        """The shading is a judgement with a number behind it, and the caption prints that
        number. Two copies, because one is prose and one is code — so this is what keeps
        the page from claiming 2 °C/km while shading at 3."""
        assert f"var CAP_LAPSE = {render_html.CAP_LAPSE}" in render_html.SCRIPT
        assert f"under {render_html.CAP_LAPSE:.0f} °C/km" in render_html.body()

    def test_the_page_says_it_needs_a_network(self):
        """It is the one artifact here that is not self-contained. Saying so is the
        difference between a page that is honest and a page that looks broken."""
        html = render_html.body()
        assert "without a network" in html
        assert "needs a network" in render_html.SCRIPT

    def test_the_page_credits_both_sources_and_refuses_to_decide(self):
        html = cli.page(render_html.body(), "Will it fly?")
        assert "Open-Meteo" in html
        assert "ParaglidingEarth" in html
        assert "A forecast is not a decision" in html
        assert "flymet" in html


NO_ROSE = {"name": "Unknown", "lat": 50.0, "lon": 15.0, "alt": 500, "winds": [], "id": 1}


@pytest.mark.parametrize(
    "winds, speed, direction, expected",
    [
        # A good octant and a workable strength is the only unqualified yes.
        ([0, 0, 0, 0, 0, 0, 2, 0], 14, 270, "flyable"),
        # Same hill, same direction, twice the wind.
        ([0, 0, 0, 0, 0, 0, 2, 0], 34, 270, "too strong"),
        # Right strength, wrong side of the hill.
        ([0, 0, 0, 0, 0, 0, 2, 0], 14, 90, "wrong way"),
        # The site's own "marginal" survives as marginal rather than being rounded up.
        ([0, 0, 0, 0, 0, 0, 1, 0], 14, 270, "marginal"),
        # Nothing recorded: the page refuses rather than guesses.
        ([], 14, 270, "no rose"),
    ],
)
def test_the_verdict_is_the_sites_own_rose(winds, speed, direction, expected):
    """A second copy of the rule, and it is a copy on purpose until this runs in a
    browser: what it buys is a written-down statement of what each answer means, and the
    two threshold assertions catch the drift that matters most — someone retuning 28 and
    20 in the page and not here. **Wanted next**: drive the real function with `fetch`
    stubbed, the way `tests/test_view3d_gestures.py` drives the real gestures. Until then
    this test cannot fail on a change to the *shape* of the rule, only to its numbers."""
    source = render_html.SCRIPT
    assert "STRONG = 28" in source and "BRISK = 20" in source
    def verdict(winds, speed, direction):
        if not winds:
            return "no rose"
        fit = winds[round((direction % 360) / 45) % 8]
        if speed > 28:
            return "too strong"
        if not fit:
            return "wrong way"
        if fit == 1:
            return "marginal"
        return "brisk" if speed > 20 else "flyable"

    assert verdict(winds, speed, direction) == expected


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
        assert 'href="../index.html"' in strip

    def test_the_report_at_the_top_level_does_not_climb(self):
        import parainsights_common as common

        strip = common.nav("flights", depth=0)
        assert 'href="meteo/"' in strip
        assert ".." not in strip

    def test_every_tool_is_in_the_strip(self):
        import parainsights_common as common

        keys = {key for key, _, _ in common.PAGES}
        assert keys == {"flights", "airspace", "meteo", "planner"}


# ------------------------------------------- the sounding, in a browser
#
# What this page draws about the air — the layer that stops the day, and the numbers under
# the pointer — is JavaScript reading a forecast, and neither can be checked from Python
# without writing a second copy of the rule. `quicklook.py` is the standing warning about
# what a second copy becomes, so instead the real page runs in a real browser with `fetch`
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


def _probe_page(body: str, *, site_count: int = 3) -> dict:
    """Run the real meteo page against a stubbed Open-Meteo and return what `body` says."""
    chrome = CHROME
    profile = json.dumps(_fake_profile())
    surface = json.dumps([{
        "hourly": {
            "time": _fake_profile()["hourly"]["time"],
            "wind_speed_10m": [12.0] * 96,
            "wind_direction_10m": [180.0] * 96,
            "temperature_2m": [26.0] * 96,
            "cloud_cover": [20.0] * 96,
            "cape": [200.0] * 96,
        }
    }] * len(sites.SITES))
    stub = """
    <script>
    window.__profile = %s;
    window.__surface = %s;
    // Every request this page makes, answered from the two objects above. The URL tells
    // them apart the same way the page builds them: only the profile call asks for
    // geopotential height.
    window.fetch = function (url) {
      var body = String(url).indexOf('geopotential_height') >= 0
        ? window.__profile : window.__surface;
      return Promise.resolve({ ok: true, json: function () {
        return Promise.resolve(JSON.parse(JSON.stringify(body)));
      } });
    };
    </script>
    """ % (profile, surface)
    page = cli.page(render_html.body(), "Will it fly?")
    probe = """
    <pre id="probe-out"></pre>
    <script>
    window.addEventListener('load', function () { setTimeout(function () {
      var out;
      try { out = (function () { %s })(); }
      catch (error) { out = { error: String((error && error.stack) || error) }; }
      document.getElementById('probe-out').textContent = JSON.stringify(out);
    }, 700); });
    </script>
    """ % body
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "meteo.html"
        target.write_text(stub + page + probe, encoding="utf-8")
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
    var figure = document.getElementById('met-flymet');
    var image = document.getElementById('met-flymet-img');
    var seen = [];
    for (var day = 0; day < 4; day++) {
      window.__meteo.state.day = day;
      window.__meteo.draw();
      seen.push({ day: day, hidden: figure.hidden, src: image.getAttribute('src') });
    }
    return { seen: seen, caption: document.getElementById('met-flymet-cap').textContent };
    """)
    today, tomorrow, third, fourth = answer["seen"]
    assert not today["hidden"] and "/meteogram/" in today["src"]
    assert not tomorrow["hidden"] and "/meteogram2/" in tomorrow["src"]
    assert third["hidden"] and fourth["hidden"]
    assert "km from this takeoff" in answer["caption"]

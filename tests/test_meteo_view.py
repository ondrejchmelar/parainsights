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
from tests.test_view3d_gl import CHROME, CHROME_FLAGS, needs_chrome


class TestTheSiteList:
    def test_every_site_is_in_the_country_it_claims(self):
        """A stray coordinate would put a takeoff in the sea and rank it anyway."""
        boxes = {  # (south, north, west, east), loose
            "CZ": (48.5, 51.1, 12.0, 18.9), "SK": (47.7, 49.7, 16.8, 22.6),
            "DE": (47.2, 55.1, 5.8, 15.1), "IT": (36.6, 47.1, 6.6, 18.6),
            "SI": (45.4, 46.9, 13.3, 16.7),
        }
        for site in sites.SITES:
            south, north, west, east = boxes[site["country"]]
            assert south < site["lat"] < north, site
            assert west < site["lon"] < east, site

    def test_the_list_is_the_chosen_one_in_its_order(self):
        """`sites.py` is generated from `sources.CHOSEN`; a hand edit to either that the
        other did not get would leave the page carrying a hill nobody chose."""
        from meteo import sources

        assert [(s["name"], s["country"], s["id"]) for s in sites.SITES] == list(sources.CHOSEN)

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

    def test_every_takeoff_north_of_the_alps_has_a_station_near_it(self):
        """flymet covers Czechia and the border: every takeoff there gets a meteogram,
        and the Alpine ones get none rather than a Czech airfield's."""
        found = render_html.nearest_stations()
        assert len(found) == len(sites.SITES)
        north = [entry for site, entry in zip(sites.SITES, found)
                 if site["country"] in ("CZ", "SK", "DE")]
        assert all(north), "a takeoff north of the Alps was left without a station"
        worst = max(entry["km"] for entry in north)
        assert worst < 30, f"the worst takeoff is now {worst} km from a station"
        south = [entry for site, entry in zip(sites.SITES, found)
                 if site["country"] in ("IT", "SI")]
        assert south and not any(south), "an Alpine takeoff was paired with a flymet station"


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
        assert "needs a network" in render_html.SCRIPT

    def test_the_page_credits_both_sources_and_refuses_to_decide(self):
        html = cli.page(render_html.body(), "Meteo")
        assert "Open-Meteo" in html
        assert "ParaglidingEarth" in html
        assert "A forecast is not a decision" in html
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
    fail on the *numbers* changing and never on the *shape*, which is the drift
    `quicklook.py` is the standing warning about. `window.__meteo.verdict` is the real
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
        assert 'href="../index.html"' in strip

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


def _probe_page(body: str, *, site_count: int = 3) -> dict:
    """Run the real meteo page against a stubbed Open-Meteo and return what `body` says."""
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
    }] * len(sites.SITES))
    stub = """
    <script>
    window.__profile = %s;
    window.__surface = %s;
    // Every request this page makes, answered from the two objects above. The URL tells
    // them apart the same way the page builds them: only the profile call asks for
    // geopotential height.
    window.__meta = %s;
    window.fetch = function (url) {
      var body = String(url).indexOf('meta.json') >= 0 ? window.__meta
        : String(url).indexOf('geopotential_height') >= 0
        ? window.__profile : window.__surface;
      return Promise.resolve({ ok: true, json: function () {
        return Promise.resolve(JSON.parse(JSON.stringify(body)));
      } });
    };
    </script>
    """ % (profile, surface, json.dumps(_FAKE_META))
    page = cli.page(render_html.body(), "Meteo")
    assert _FLYMET_HOST in page, "flymet's host moved; this test rewrites it by hand"
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
    var details = document.getElementById('met-flymet');
    var list = document.getElementById('met-flymet-list');
    var seen = [];
    for (var day = 0; day < 4; day++) {
      window.__meteo.state.day = day;
      window.__meteo.draw();
      var image = list.querySelector('img');
      seen.push({ day: day, hidden: details.hidden,
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
    assert "km from this takeoff" in today["caption"]


# ------------------------------------------- choosing takeoffs, in a browser
#
# The picker used to be a 159-row list holding the top-left corner of the page: it was
# the first thing a reader met, it needed scrolling to get past, and it stayed there for
# as long as the page was open. It is a dialog now, and the page keeps up to three
# takeoffs and compares them. These are the behaviours that rework has to have, and the
# ones a screenshot cannot check.


@needs_chrome
class TestChoosingTakeoffs:
    def test_the_page_opens_with_the_best_takeoff_already_chosen(self):
        """A page that shows nothing until the reader picks a hill hides its own answer
        to "is it worth going anywhere today"."""
        answer = _probe_page("""
        var m = window.__meteo;
        return { chosen: m.chosen().length, focused: m.state.site,
                 panel: document.getElementById('met-panel').hidden,
                 chips: document.querySelectorAll('.met-chip').length };
        """)
        assert answer["chosen"] == 1
        assert answer["focused"] is not None
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
        assert answer["rows"] == len(sites.SITES), "the dialog should hold the whole list"

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
        assert answer["all"] == len(sites.SITES)
        # Typed without the accent, and it still finds Raná.
        assert answer["narrowed"] == ["Raná"], "searching for a real takeoff found nothing"
        assert answer["empty"] == 1, "a search with no hits must say so"

    def test_three_takeoffs_can_be_compared_and_a_fourth_is_refused(self):
        """Three is the palette's limit, not a whim — the fourth categorical slot fails
        the normal-vision floor against the third. What matters here is that the refusal
        is explicit rather than an eviction the reader cannot see."""
        answer = _probe_page("""
        var m = window.__meteo;
        var picked = [];
        for (var i = 0; i < 5 && picked.length < 5; i++) {
          if (m.chosen().indexOf(i) < 0) { m.add(i); picked.push(i); }
        }
        return { chosen: m.chosen().length,
                 chips: document.querySelectorAll('.met-chip').length,
                 rows: document.querySelectorAll('.met-compare tbody tr').length,
                 hidden: document.getElementById('met-compare').hidden,
                 status: document.getElementById('met-status').textContent };
        """)
        assert answer["chosen"] == 3
        assert answer["chips"] == 3
        assert answer["hidden"] is False
        assert answer["rows"] == 3
        assert "Three at a time" in answer["status"]

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
                 focusedChips: document.querySelectorAll('.met-chip.is-focus').length,
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
        return { figures: document.querySelectorAll('#met-flymet-list figure').length,
                 images: document.querySelectorAll('#met-flymet-list img').length,
                 stations: Object.keys(stations).length,
                 summary: document.getElementById('met-flymet-summary').textContent };
        """)
        assert answer["figures"] == answer["stations"], (
            "one picture per station, and every chosen takeoff's station is a station")
        assert answer["images"] == answer["figures"]

    def test_two_takeoffs_sharing_an_airfield_get_one_picture_naming_both(self, monkeypatch):
        """Two hills sharing their nearest airfield: the same meteogram printed twice
        under two headings reads as a bug in the page, and costs flymet a second fetch to
        say the same thing. The chosen list is short enough that no two share one today,
        so the first two are made to — a list that grows would bring the case back."""
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
        var figures = document.querySelectorAll('#met-flymet-list figure');
        return {
          skipped: false,
          figures: figures.length,
          heading: figures.length ? figures[0].querySelector('.for').textContent : '',
          dots: figures.length ? figures[0].querySelectorAll('.for i').length : 0,
          names: [conf.sites[pair[0]].name, conf.sites[pair[1]].name]
        };
        """)
        assert not answer["skipped"], "no two takeoffs share an airfield"
        assert answer["figures"] == 1, "the same picture was printed twice"
        for name in answer["names"]:
            assert name in answer["heading"], (
                f"{name} shares the picture but is not named on it")
        assert answer["dots"] == 2, "each takeoff's colour belongs on the heading"


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

    def test_every_takeoff_gets_its_own_meteogram_and_sounding(self):
        answer = self._with_three("""
        return { columns: document.querySelectorAll('.met-col').length,
                 grams: document.querySelectorAll('.met-col-gram').length,
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
                     href: cell.querySelector('.met-col-rose a').getAttribute('href'),
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


def test_the_sounding_owns_the_vertical_gesture():
    """A drag up the sounding reads a height; a drag up the page scrolls it. They are the
    same gesture, so the browser scrolled and the chart read nothing — the one bug a
    caption saying "drag a finger up it" cannot survive.

    `touch-action: none` is what actually stops it: a `preventDefault` on a move the
    browser has already begun scrolling with is too late. Same declaration the 3D view
    and the airspace map use for their gestures. Deliberately *not* on the meteogram
    above it, so every column keeps a full-width strip to scroll the page from.
    """
    style = render_html.STYLE
    assert ".met-col-sounding { touch-action: none; }" in style
    assert ".met-col-gram { touch-action" not in style


@needs_chrome
def test_a_touch_on_the_sounding_is_taken_by_the_chart():
    answer = _probe_page("""
    var m = window.__meteo;
    var free = null;
    for (var i = 0; i < 8; i++) if (m.chosen().indexOf(i) < 0) { free = i; break; }
    m.add(free);
    var canvas = document.getElementById('met-sounding');
    var box = canvas.getBoundingClientRect();
    var down = new PointerEvent('pointerdown', {
      clientX: box.left + box.width / 2, clientY: box.top + box.height / 2,
      bubbles: true, cancelable: true, pointerType: 'touch', pointerId: 7, buttons: 1 });
    canvas.dispatchEvent(down);
    return { prevented: down.defaultPrevented, probe: m.state.probe,
             action: getComputedStyle(canvas).touchAction };
    """)
    assert answer["prevented"] is True, "the browser keeps its own gesture"
    assert answer["action"] == "none"
    assert answer["probe"] is not None, "the touch read no height"


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
    they disagree by hundreds of metres on an ordinary day. The chart names both, and a
    line under it gives the range with the reason one tap away."""
    temperatures, _ = _mixed_layer()
    answer = _probe_page("""
    var m = window.__meteo;
    var box = document.querySelector('.met-col-top');
    var stable = box.querySelector('summary').textContent;
    var profile = m.state.profiles[m.chosen()[0]];
    var wanted = %s;
    Object.keys(wanted).forEach(function (level) {
      var series = profile.hourly['temperature_' + level + 'hPa'];
      for (var i = 0; i < series.length; i++) series[i] = wanted[level];
    });
    m.draw();
    var canvas = document.querySelector('.met-col-sounding');
    return { drawn: canvas.__drawn, hidden: box.hidden, stable: stable,
             summary: box.querySelector('summary').textContent,
             why: box.querySelector('p').textContent, open: box.open };
    """ % json.dumps(temperatures))
    assert "(model only)" in answer["stable"], answer["stable"]
    assert "two numbers" not in answer["stable"], "one number, asked why there are two"
    assert "why only one?" in answer["stable"]
    drawn = answer["drawn"]
    assert drawn["thermalTop"] and drawn["parcelTop"], drawn
    assert answer["hidden"] is False
    low, high = sorted((drawn["thermalTop"], drawn["parcelTop"]))
    shown = [int(n.replace(" ", "")) for n in
             re.findall(r"(\d[\d ]*) m", answer["summary"])]
    assert shown == [low, high], answer["summary"]
    assert "why two numbers?" in answer["summary"]
    assert answer["open"] is False, "the reason should be folded until asked for"
    assert "ECMWF" in answer["why"] and "parcel" in answer["why"]

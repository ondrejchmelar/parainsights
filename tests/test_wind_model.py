"""The day's wind and ceiling, one place each (October 2026).

The climbs' drift and the model's wind are one chart in "The air that day" — it was a
chart in one section and a table of the same climbs against the model in the next — and
your top is a line on the sounding beside the cloudbase and thermal top it is measured
against. A flight older than 60 days asks Open-Meteo's archived forecast, which has the
pressure levels a sounding needs, and ERA5 (surface only) where that has nothing.
"""

from tests import js
from tests.js import needs_node
from tests.test_analysis import build, circling, straight

pytestmark = needs_node

DAY = 86400


def a_drifting_day(tmp_path):
    """Four circled climbs, each drifting slowly — so each one sounds a wind."""
    points, t, alt, x = [], 0.0, 900.0, 0.0
    for _ in range(4):
        leg = circling(300, climb=1.2, drift=(1.0, 0.0), t0=t, alt0=alt, x0=x, y0=0.0)
        points += leg
        t, alt, x = leg[-1][0] + 1, leg[-1][3], leg[-1][1]
        run = straight(200, speed=12.0, climb=-1.2, t0=t, alt0=alt, x0=x, y0=0.0,
                       heading=90.0)
        points += run
        t, alt, x = run[-1][0] + 1, run[-1][3], run[-1][1]
    return build(tmp_path / "wind.igc", points)


def the_day(levels=True):
    """A parsed day (`TV.meteo.parse`'s shape), from the valley to 5 km."""
    rows = [(1000, 110, 24, 10), (950, 540, 20, 8), (900, 990, 16, 6), (850, 1460, 12, 2),
            (800, 1950, 8, -2), (700, 3000, 0, -10), (600, 4200, -8, -20), (500, 5600, -18, -30)]
    return {"valid_at": "2026-07-01 12:00 UTC", "source": "Open-Meteo archived forecast",
            "latitude": 0, "longitude": 0, "elevation": 100.0,
            "surface_temperature": 25.0, "surface_dew_point": 11.0,
            "surface_wind_speed": 2.0, "surface_wind_direction": 270.0,
            "cape": 300.0, "boundary_layer_height": None, "cloud_cover_low": 10.0,
            "cloud_cover_mid": 0.0,
            "levels": [{"pressure": p, "height": h, "temperature": t, "dew_point": d,
                        "wind_speed": 6.0, "wind_direction": 300.0}
                       for p, h, t, d in rows] if levels else []}


def article(path, meteo):
    return js.run("return TV.report.flightBody(TV.analysis.analyse(await load(input.path)),"
                  " { uid: 'f0', meteo: input.meteo, now: 0 });", path=path, meteo=meteo)


def air_section(html):
    start = html.index("<h2>The air that day")
    return html[start:html.index("</section>", start)]


class TestOneWindChart:
    def test_the_wind_sits_beside_the_sounding_and_the_table_is_gone(self, tmp_path):
        html = article(a_drifting_day(tmp_path), the_day())
        air = air_section(html)
        assert "<h3>Sounding</h3>" in air and "<h3>Wind</h3>" in air and "chart-wind" in air
        assert "Wind against the model" not in html
        assert html.count("chart-wind") == 1, "the wind is drawn once"

    def test_the_model_is_drawn_with_its_directions(self, tmp_path):
        air = air_section(article(a_drifting_day(tmp_path), the_day()))
        assert "model-dot" in air and "model-arrow" in air
        assert "Model, by pressure level" in air

    def test_each_climb_says_how_far_it_was_from_the_model(self, tmp_path):
        air = air_section(article(a_drifting_day(tmp_path), the_day()))
        assert "° apart</title>" in air

    def test_no_levels_no_model_and_no_legend_for_one(self, tmp_path):
        air = air_section(article(a_drifting_day(tmp_path), the_day(levels=False)))
        assert "chart-wind" in air and "model-dot" not in air
        assert "Model, by pressure level" not in air

    def test_no_weather_keeps_the_climbs_wind(self, tmp_path):
        html = article(a_drifting_day(tmp_path), None)
        air = air_section(html)
        assert "No weather: the weather service did not answer." in air
        assert "chart-wind" in air
        assert "air-fetch" not in html, "the page no longer fetches a second, smaller answer"


class TestYourTopOnTheSounding:
    def test_your_top_is_a_line_against_the_ceiling(self, tmp_path):
        html = article(a_drifting_day(tmp_path), the_day())
        air = air_section(html)
        assert 'class="your-top"' in air and "Your top " in air
        assert "You topped out" not in html, "the sentence is the line now"


class TestTheHistogramsName:
    def test_renamed(self, tmp_path):
        html = article(a_drifting_day(tmp_path), the_day())
        assert "<h3>Climb rates while circling</h3>" in html
        assert "Lift you sat in" not in html


class TestOldFlightsAskTheArchivedForecast:
    def ask(self, days_ago):
        return js.run("""var now = 1790000000, when = now - input.days * 86400;
          return { url: TV.meteo.request(46.5, 11.7, when, now),
                   fallback: TV.meteo.fallback(46.5, 11.7, when, now) };""", days=days_ago)

    def test_recent_is_the_forecast_and_needs_no_fallback(self):
        answer = self.ask(3)
        assert answer["url"].startswith("https://api.open-meteo.com/v1/forecast")
        assert answer["fallback"] is None

    def test_old_is_the_archived_forecast_then_era5(self):
        answer = self.ask(400)
        assert answer["url"].startswith("https://historical-forecast-api.open-meteo.com/")
        assert answer["fallback"].startswith("https://archive-api.open-meteo.com/v1/archive")

    def test_the_source_says_which_answered(self):
        names = js.run("""var now = 1790000000, when = 1760000000, hourly = { time: ['2025-10-09T08:53'],
              temperature_2m: [20], dew_point_2m: [10] };
            var stamp = new Date(when * 1000).toISOString().slice(0, 16);
            hourly.time = [stamp];
            return [TV.meteo.parse({ hourly: hourly }, when, now).source,
                    TV.meteo.parse({ hourly: hourly, era5: true }, when, now).source];""")
        assert names == ["Open-Meteo archived forecast", "ERA5 reanalysis, surface only"]

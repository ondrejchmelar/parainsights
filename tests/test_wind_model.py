"""The model wind profile, drawn into a chart that was built without one.

A report built without ``--meteo`` has no forecast in it, and until now the wind chart
said so and stopped there — even though the same page fetches the day at view time to
fill "The air that day". The two halves are now joined: the wind chart (`js/charts.js`,
`windProfile`) publishes its axis mapping in ``data-wind-frame``, each point carries the
speed and altitude it was placed from, and ``plotModelWind`` in the page draws the
profile into the ``<g class="model">`` the article left empty.

The part worth testing is the *rescale*. Measured winds are drift inside thermals, the
model is the free air, and the model is routinely several times the fastest thing the
glider felt — so a plotter that clipped to the existing axis would draw a vertical line
up the right-hand edge and call it a profile. These tests move a model of 30 km/h into a
chart whose axis stops at 10 and check that the axis grew, the measured points moved
with it, and the two are still on the same scale.

No network: ``fetch`` is stubbed in the page with a canned Open-Meteo answer.
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path


from tests import js
from tests.js import needs_node
from tests.test_analysis import build, circling, straight
from tests.test_view3d_gl import CHROME, CHROME_FLAGS, needs_chrome
from tracklog_viewer import render_html

pytestmark = needs_node
PRESSURE_LEVELS = render_html.PRESSURE_LEVELS

# What the stubbed forecast says at each pressure level: fast, and getting faster with
# height. Deliberately far outside anything the fixture's gentle drift can produce.
MODEL_KMH = {1000: 18.0, 975: 22.0, 950: 26.0, 925: 28.0, 900: 30.0,
             850: 32.0, 800: 34.0, 700: 40.0, 600: 46.0, 500: 52.0}
MODEL_HEIGHT = {1000: 110.0, 975: 320.0, 950: 540.0, 925: 760.0, 900: 990.0,
                850: 1460.0, 800: 1950.0, 700: 3000.0, 600: 4200.0, 500: 5600.0}


def a_drifting_day(tmp_path):
    """Four circled climbs, each drifting slowly — so each one sounds a wind.

    ``wind_profile`` only plots a climb with a wind estimate and at least two turns, so
    a fixture of perfect stationary circles produces an empty chart and nothing to
    rescale. 1 m/s of drift is about 4 km/h, well under the model above.
    """
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


def wind_chart(path, meteo=None):
    """The wind chart as the article writes it, with the constants it was drawn with."""
    return js.run("""var a = TV.analysis.analyse(await load(input.path));
      return { svg: TV.charts.windProfile(a, input.meteo), step: TV.charts.WIND_SPEED_STEP,
               altStep: TV.charts.WIND_ALT_STEP, band: TV.charts.WIND_MODEL_BAND };""",
                  path=path, meteo=meteo)


def _hourly(levels_have_wind: bool = True) -> dict:
    """One Open-Meteo answer, in the shape `fetchMeteo` reads."""
    hours = [f"2026-07-01T{hour:02d}:00" for hour in range(24)]
    hourly = {
        "time": hours,
        "temperature_2m": [22.0] * 24,
        "dew_point_2m": [8.0] * 24,
        "boundary_layer_height": [1600.0] * 24,
        "wind_speed_850hPa": [MODEL_KMH[850]] * 24,
        "wind_direction_850hPa": [270.0] * 24,
    }
    for pressure in PRESSURE_LEVELS:
        value = MODEL_KMH[pressure] if levels_have_wind else None
        height = MODEL_HEIGHT[pressure] if levels_have_wind else None
        hourly[f"wind_speed_{pressure}hPa"] = [value] * 24
        hourly[f"wind_direction_{pressure}hPa"] = [280.0 if value else None] * 24
        hourly[f"geopotential_height_{pressure}hPa"] = [height] * 24
    return {"elevation": 400.0, "hourly": hourly}


_PROBE = """
<pre id="probe-out"></pre>
<script>
// Installed during parse, so it is in place before the report's own idle callback runs.
// Stubbing `fetch` rather than `__fetchMeteo` keeps the level parsing under test: the
// profile fields are added to the URL by `fetchMeteo` (render_html.SCRIPT), and a stub one layer
// higher would skip exactly the code that reads them back.
(function () {
  var answer = %s;
  window.__askedFor = null;
  window.fetch = function (url) {
    window.__askedFor = String(url);
    return Promise.resolve({ ok: true, status: 200,
                             json: function () { return Promise.resolve(answer); } });
  };
})();
// Waits for the request rather than a fixed time: the report asks from an idle callback,
// and under a loaded parallel run that came after a fixed 4 s often enough to fail.
function whenAsked(done) {
  var started = Date.now();
  (function poll() {
    if (window.__askedFor || Date.now() - started > 15000) { setTimeout(done, 500); return; }
    setTimeout(poll, 100);
  })();
}
window.addEventListener('load', function () {
  whenAsked(function () {
    var out = {};
    try {
      var svg = document.querySelector('.chart-wind');
      var frame = JSON.parse(svg.getAttribute('data-wind-frame'));
      var model = svg.querySelector('.model');
      var line = model && model.querySelector('polyline');
      out.frame = frame;
      out.asked = window.__askedFor;
      out.modelPoints = line ? line.getAttribute('points') : null;
      out.modelDots = model ? model.querySelectorAll('.model-dot').length : 0;
      // Where the fastest measured point sits now, and what it measured: the two have
      // to agree under the axis the chart currently claims.
      var points = Array.prototype.slice.call(svg.querySelectorAll('.wind-point'));
      out.measured = points.map(function (point) {
        var dot = point.querySelector('.wind-dot');
        return { speed: parseFloat(point.dataset.speed),
                 alt: parseFloat(point.dataset.alt),
                 cx: parseFloat(dot.getAttribute('cx')),
                 cy: parseFloat(dot.getAttribute('cy')) };
      });
      out.xLabels = Array.prototype.map.call(
        svg.querySelectorAll('.axis-x'), function (t) { return t.textContent; });
      out.yLabels = Array.prototype.map.call(
        svg.querySelectorAll('.axis-y'), function (t) { return t.textContent; });
      // Read the elements, never `body.textContent`: the page carries its own script
      // inline, and every sentence this feature writes appears in that source too — so
      // a whole-document search says "the caption is there" on a page where it is not.
      function captions() {
        return Array.prototype.map.call(
          document.querySelectorAll('.caption'), function (p) { return p.textContent; });
      }
      out.legend = !!document.querySelector('.legend .model-swatch');
      out.caption = captions().some(function (text) {
        return text.indexOf('forecast profile would be drawn behind these') >= 0;
      });
      out.captionSays = captions().some(function (text) {
        return text.indexOf('forecast profile is drawn behind these') >= 0;
      });
    } catch (error) {
      out.error = String((error && error.stack) || error);
    }
    document.getElementById('probe-out').textContent = JSON.stringify(out);
  });
});
</script>
"""


def _render(path, *, levels_have_wind: bool = True) -> dict:
    body = js.run("return TV.report.flightBody(TV.analysis.analyse(await load(input.path)),"
                  " { uid: 'f0', now: Date.now() / 1000 });", path=path)
    page = render_html._page("wind", [body])
    assert 'data-wind-frame' in page, "the chart published no axis mapping"
    page += _PROBE % json.dumps(_hourly(levels_have_wind))

    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "wind.html"
        target.write_text(page, encoding="utf-8")
        result = subprocess.run(
            [CHROME, *CHROME_FLAGS, target.as_uri()],
            capture_output=True, text=True, timeout=180,
        )
    match = re.search(r'<pre id="probe-out">(.*?)</pre>', result.stdout, re.S)
    assert match and match.group(1).strip(), (
        "the probe produced nothing:\n" + result.stderr[-2000:])
    text = match.group(1)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&amp;", "&")):
        text = text.replace(entity, char)
    answer = json.loads(text)
    assert "error" not in answer, answer["error"]
    return answer


class TestTheChartPublishesEnoughToBeFinished:
    """The article's half, checkable without a browser."""

    def test_the_frame_carries_the_axis_and_the_rounding(self, tmp_path):
        chart = wind_chart(a_drifting_day(tmp_path))
        frame = json.loads(re.search(r"data-wind-frame='([^']+)'", chart.svg).group(1))
        for key in ("left", "top", "plotW", "plotH", "speedMax", "altMin", "altMax",
                    "speedStep", "altStep", "band", "hasModel"):
            assert key in frame, f"the frame does not publish {key}"
        assert frame["speedStep"] == chart.step
        assert frame["altStep"] == chart.altStep
        assert frame["band"] == chart.band
        assert frame["hasModel"] is False

    def test_every_point_carries_what_it_was_placed_from(self, tmp_path):
        svg = wind_chart(a_drifting_day(tmp_path)).svg
        groups = re.findall(r'<g class="wind-point"[^>]*>', svg)
        assert groups, "no measured points in the chart"
        for group in groups:
            assert "data-speed=" in group and "data-alt=" in group \
                and "data-dir=" in group

    def test_the_model_group_exists_even_when_it_is_empty(self, tmp_path):
        """The page has to draw *behind* the measured points, and appending a group of
        its own would put it in front of them."""
        assert '<g class="model"></g>' in wind_chart(a_drifting_day(tmp_path)).svg

    def test_the_frame_says_so_when_the_article_already_drew_the_model(self, tmp_path):
        """`hasModel` is what stops the page drawing a second line over the first."""
        day = {"levels": [{"pressure": p, "height": MODEL_HEIGHT[p], "temperature": 10.0,
                           "dew_point": 2.0, "wind_speed": MODEL_KMH[p], "wind_direction": 280.0}
                          for p in PRESSURE_LEVELS]}
        svg = wind_chart(a_drifting_day(tmp_path), day).svg
        frame = json.loads(re.search(r"data-wind-frame='([^']+)'", svg).group(1))
        assert frame["hasModel"] is True


@needs_chrome
class TestThePageFinishesTheChart:
    def test_the_profile_fields_are_asked_for(self, tmp_path):
        answer = _render(a_drifting_day(tmp_path))
        assert answer["asked"], "no request was made"
        assert "geopotential_height_850hPa" in answer["asked"]
        assert "wind_speed_700hPa" in answer["asked"]

    def test_the_model_line_is_drawn(self, tmp_path):
        answer = _render(a_drifting_day(tmp_path))
        assert answer["modelPoints"], "no model polyline was drawn"
        assert answer["modelDots"] >= 2

    def test_the_axis_grows_to_fit_a_model_faster_than_the_glider_felt(self, tmp_path):
        """The whole reason this is a rescale and not a plot."""
        answer = _render(a_drifting_day(tmp_path))
        assert answer["frame"]["speedMax"] <= 10, (
            "the fixture's measured winds were not gentle; the test proves nothing")
        biggest = max(int(label) for label in answer["xLabels"])
        assert biggest >= 20, (
            f"the speed axis still stops at {biggest} km/h with a 30 km/h model on it")

    def test_the_measured_points_move_with_the_axis(self, tmp_path):
        """A rescale that redrew only the grid would leave every point lying."""
        answer = _render(a_drifting_day(tmp_path))
        frame = answer["frame"]
        speed_max = max(int(label) for label in answer["xLabels"])
        alt_min = min(int(label) for label in answer["yLabels"])
        alt_max = max(int(label) for label in answer["yLabels"])
        for point in answer["measured"]:
            want_x = frame["left"] + frame["plotW"] * point["speed"] / speed_max
            want_y = frame["top"] + frame["plotH"] * (
                1 - (point["alt"] - alt_min) / max(alt_max - alt_min, 1))
            assert abs(point["cx"] - want_x) < 1.0, (
                f"a point measuring {point['speed']:.1f} km/h sits at x={point['cx']} "
                f"where the redrawn axis puts {want_x:.1f}")
            assert abs(point["cy"] - want_y) < 1.0

    def test_the_caption_stops_saying_the_model_is_missing(self, tmp_path):
        answer = _render(a_drifting_day(tmp_path))
        assert answer["caption"] is False, (
            "the caption still explains the absence of a line that is now on the chart")
        assert answer["captionSays"] is True, (
            "the caption says nothing about where the line came from")
        assert answer["legend"] is True, "the legend never gained the model swatch"

    def test_an_answer_with_no_levels_leaves_the_chart_alone(self, tmp_path):
        """The ERA5 archive returns nulls on every pressure level, so a flight older
        than the 60-day cutoff gets no profile — and the caption has to go on saying
        why rather than the chart growing an axis with nothing on it."""
        answer = _render(a_drifting_day(tmp_path), levels_have_wind=False)
        assert answer["modelPoints"] is None
        assert answer["modelDots"] == 0
        assert answer["caption"] is True

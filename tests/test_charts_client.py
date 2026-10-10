"""The side view and the top view, drawn in the browser.

Nine profile SVGs at 577 KB and three plan views at 153 KB used to sit in the published
document — 730 KB of 2.97 MB, and nine profiles because the axis toggle shipped all three
modes and hid two. They are drawn in the page now, from the payload the hover cursor was
already carrying.

Two kinds of test here. The first checks the payload (`js/charts.js`) is what the
renderer needs and that the article (`js/report.js`) carries no SVG for these two. The
browser ones check the DOM the page builds — its groups, classes and data attributes —
because every feature downstream of these charts was written against that DOM, and a
renderer that draws a *pretty* chart with different innards silently breaks the cursor,
the tooltip and the debrief's "show me".
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests import js
from tests.js import needs_node
from tests.test_analysis import build, circling, straight
from tests.browser import CHROME, CHROME_FLAGS, needs_chrome
from tracklog_viewer import render_html

pytestmark = needs_node


@pytest.fixture(scope="module")
def flight(tmp_path_factory):
    """A day with several climbs and glides, so there are bands and marks to draw. What
    comes back is everything the tests ask of it, computed once: the chart payload, the
    cursor's own sample, the segments, and the article the page would carry."""
    folder = tmp_path_factory.mktemp("charts")
    points, t, alt, x = [], 0.0, 1000.0, 0.0
    for rate in (2.4, 1.1, 1.8, 0.9):
        leg = circling(300, climb=rate, drift=(1.0, 0.0), t0=t, alt0=alt, x0=x, y0=0.0)
        points += leg
        t, alt, x = leg[-1][0] + 1, leg[-1][3], leg[-1][1]
        run = straight(400, speed=12.0, climb=-1.1, t0=t, alt0=alt, x0=x, y0=0.0,
                       heading=90.0)
        points += run
        t, alt, x = run[-1][0] + 1, run[-1][3], run[-1][1]
    return js.run("""
      var a = TV.analysis.analyse(await load(input.path)), sample = TV.report.sampleIndices(a);
      return { payload: TV.charts.payload(a, null, null, sample, TV.charts.planHeight(a)),
               cursor: TV.report.cursorData(a), segments: a.segments, ramp: TV.charts.CLIMB_RAMP.length,
               html: TV.report.flightBody(a, { uid: 'f0', now: Date.now() / 1000 }) };
    """, path=build(folder / "charts.igc", points))


def _payload(flight):
    return flight.payload


class TestThePayload:
    def test_one_value_per_sample_in_every_series(self, flight):
        """The trace, the cursor and the bands all index the same list. Two lists of
        different lengths is a marker that lands on a different moment than the one
        under the pointer."""
        data = _payload(flight)
        n = len(flight.cursor["alt"])
        for key in ("x", "y"):
            assert len(data[key]) == n, f"{key} is {len(data[key])} against {n} samples"

    def test_it_does_not_repeat_what_the_cursor_payload_carries(self, flight):
        """The whole saving: altitude, climb and time are already in the document once."""
        data = _payload(flight)
        for key in ("alt", "climb", "t", "clock", "speed"):
            assert key not in data, f"{key} is shipped twice"

    def test_bands_and_marks_are_sample_positions(self, flight):
        data = _payload(flight)
        n = len(data["x"])
        for start, stop, _phase, _segment in data["bands"]:
            assert 0 <= start <= stop < n
        for mark in data["marks"]:
            assert 0 <= mark["at"] < n

    def test_a_band_keeps_the_fix_index_it_is_addressed_by(self, flight):
        """`data-segment` is how the tooltip, the tables and "show me" name a segment;
        it has to stay a fix index even though the drawing uses sample positions."""
        data = _payload(flight)
        starts = {segment.start for segment in flight.segments}
        assert {band[3] for band in data["bands"]} <= starts

    def test_the_clock_ticks_ship_with_the_payload(self, flight):
        """In the flight's own clock, worked out once where the article is written rather
        than again by the chart — `lon / 15` is the documented trap."""
        data = _payload(flight)
        assert data["clockTicks"], "the time axis would have no labels"
        for at, label in data["clockTicks"]:
            assert re.fullmatch(r"\d{2}:\d{2}", label)
            assert at >= 0

    def test_the_ramp_travels_as_data(self, flight):
        """One climb ramp, not a second copy of it in JavaScript. JSON has no infinity,
        so the open end is null and the renderer treats it as the catch-all."""
        data = _payload(flight)
        assert len(data["ramp"]) == flight.ramp
        assert data["ramp"][-1][0] is None

    def test_the_headroom_rule_is_applied_here_and_not_there(self, flight):
        """`_with_headroom` needs the meteo lines and the 1 000 m cap. The answer ships;
        the rule does not."""
        data = _payload(flight)
        assert data["ceiling"] >= data["floor"]
        assert data["floor"] % 100 == 0 and data["ceiling"] % 100 == 0


class TestTheDocument:
    def test_the_article_carries_no_profile_or_plan_svg(self, flight):
        """What must not appear is an `<svg>` wearing one of these classes: they are
        drawn in the page."""
        assert 'class="chart chart-profile"' not in flight.html, (
            "a side view is baked into the article")
        assert 'class="chart chart-plan"' not in flight.html, (
            "a top view is baked into the article")

    def test_it_carries_one_payload_and_two_hosts(self, flight):
        assert flight.html.count('class="chart-data"') == 1
        assert flight.html.count('data-chart="profile"') == 1
        assert flight.html.count('data-chart="plan"') == 1

    def test_the_hosts_reserve_their_own_height(self, flight):
        """A chart that lands 420 px tall into a 0 px box moves everything under it."""
        assert flight.html.count("aspect-ratio:") >= 2

    def test_the_page_says_what_it_needs_where_the_chart_would_be(self, flight):
        assert "needs JavaScript" in flight.html

    def test_the_sparklines_ship_as_data_not_drawings(self, flight):
        """Each climb row carries its climb-rate series; the bars are drawn in the page."""
        assert 'class="spark"' not in flight.html
        cells = re.findall(r'<td class="spark-cell" data-climb="([^"]*)"></td>', flight.html)
        climbs = [s for s in flight.segments if s.phase == "thermal"]
        assert len(cells) == len(climbs)
        for cell, climb in zip(cells, climbs):
            values = [float(v) for v in cell.split(",")]
            assert len(values) == climb.stop - climb.start, "one value a fix, not a sample"


_PROBE = """
<pre id="probe-out"></pre>
<script>
window.addEventListener('load', function () { setTimeout(function () {
  var out = {};
  try { out = (function () { %s })(); }
  catch (error) { out = { error: String((error && error.stack) || error) }; }
  document.getElementById('probe-out').textContent = JSON.stringify(out);
}, 2500); });
</script>
"""


def _probe(flight, body: str) -> dict:
    page = render_html._page("t", [flight.html])
    page += _PROBE % body
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "charts.html"
        target.write_text(page, encoding="utf-8")
        out = subprocess.run([CHROME, *CHROME_FLAGS, target.as_uri()],
                             capture_output=True, text=True, timeout=180).stdout
    found = re.search(r'<pre id="probe-out">(.*?)</pre>', out, re.S)
    assert found and found.group(1).strip(), out[-2000:]
    text = found.group(1)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&amp;", "&")):
        text = text.replace(entity, char)
    answer = json.loads(text)
    assert "error" not in answer, answer["error"]
    return answer


@needs_chrome
class TestThePageDrawsThem:
    def test_both_charts_appear_and_only_one_of_each(self, flight):
        answer = _probe(flight, """
        var a = document.querySelector('[data-flight-report]');
        return { profiles: a.querySelectorAll('svg.chart-profile').length,
                 plans: a.querySelectorAll('svg.chart-plan').length };
        """)
        assert answer["profiles"] == 1, "three copies of the side view are what this removed"
        assert answer["plans"] == 1

    def test_it_builds_the_dom_the_report_is_written_against(self, flight):
        """Element for element. Everything downstream —
        the cursor, the tooltip, the band highlight, "show me", the theme's `var()`
        fills — was written against this DOM."""
        answer = _probe(flight, """
        var svg = document.querySelector('svg.chart-profile');
        function tally(sel) { return svg.querySelectorAll(sel).length; }
        return {
          groups: Array.prototype.map.call(svg.children, function (n) {
            return n.getAttribute('class') || n.tagName; }),
          bands: tally('.bands .band'), drops: tally('.drops line'),
          track: tally('.track polyline'), marks: tally('.marks .mark'),
          endpoints: tally('.endpoints .endpoint'), hit: tally('.hit[data-px]'),
          crosshair: tally('.cursor .crosshair'), dot: tally('.cursor .cursor-dot'),
          axisTitles: tally('.axes .axis-title'),
          segments: Array.prototype.map.call(svg.querySelectorAll('.band'),
            function (n) { return n.getAttribute('data-segment'); })
        };
        """)
        assert answer["groups"] == ["bands", "grid", "drops", "references", "track",
                                    "endpoints", "marks", "cursor", "hit", "axes"]
        assert answer["bands"] == len(flight.segments)
        assert answer["marks"] == len(flight.payload["marks"])
        assert answer["endpoints"] == 2
        assert answer["hit"] == 1 and answer["crosshair"] == 1 and answer["dot"] == 1
        assert answer["axisTitles"] == 2
        assert answer["track"] > 1, "the trace should be several runs of one colour"
        assert answer["drops"] > 50
        # Every band names the fix index the rest of the report addresses it by.
        assert all(value and value.isdigit() for value in answer["segments"])

    def test_the_trace_is_drawn_through_the_cursors_own_sample(self, flight):
        """One sample, shared. Two independently decimated ones put the marker on a
        different moment than the one under the pointer."""
        answer = _probe(flight, """
        var hit = document.querySelector('svg.chart-profile .hit');
        var cursor = JSON.parse(
          document.querySelector('.cursor-data').textContent);
        return { points: hit.dataset.px.split(',').length,
                 samples: cursor.alt.length };
        """)
        assert answer["points"] == answer["samples"]

    def test_the_side_view_runs_on_the_clock_alone(self, flight):
        """Time of day, labelled as a clock (13:30) — no distance axis and no switch."""
        answer = _probe(flight, """
        var a = document.querySelector('[data-flight-report]');
        var ticks = Array.prototype.map.call(
          a.querySelectorAll('svg.chart-profile .axis-x'),
          function (n) { return n.textContent; });
        return { title: a.querySelector('svg.chart-profile .axis-title').textContent,
                 ticks: ticks, toggles: a.querySelectorAll('[data-profile]').length,
                 copies: a.querySelectorAll('svg.chart-profile').length };
        """)
        assert "time of day" in answer["title"].lower()
        assert answer["toggles"] == 0
        assert answer["copies"] == 1
        assert any(re.fullmatch(r"\d{2}:\d{2}", tick) for tick in answer["ticks"]), (
            "the time axis lost its clock labels")

    def test_the_cursor_still_works_after_a_redraw(self, flight):
        """The failure this could most easily have shipped: a redraw produces a chart
        the cursor cannot drive, which looks exactly like the cursor being broken."""
        answer = _probe(flight, """
        var a = document.querySelector('[data-flight-report]');
        window.__drawProfile(a);
        var hit = a.querySelector('svg.chart-profile .hit');
        var box = hit.getBoundingClientRect();
        hit.dispatchEvent(new MouseEvent('mousemove', {
          clientX: box.left + box.width * 0.6, clientY: box.top + box.height * 0.5,
          bubbles: true }));
        var dot = a.querySelector('svg.chart-profile .cursor-dot');
        return { tip: document.getElementById('tip').classList.contains('on'),
                 cx: Number(dot.getAttribute('cx')),
                 lit: a.querySelectorAll('.band.active').length,
                 on: a.querySelector('svg.chart-profile .cursor')
                   .classList.contains('on') };
        """)
        assert answer["tip"] is True, "the tooltip did not open on the redrawn chart"
        assert answer["on"] is True
        assert answer["cx"] > 100, "the cursor dot never moved off the left edge"

    def test_every_climb_gets_a_sparkline_drawn_in_the_page(self, flight):
        answer = _probe(flight, """
        var cells = document.querySelectorAll('td.spark-cell');
        return { cells: cells.length,
                 drawn: document.querySelectorAll('td.spark-cell svg.spark').length,
                 bars: Array.prototype.map.call(cells, function (c) {
                   return c.querySelectorAll('rect').length; }),
                 coloured: Array.prototype.every.call(
                   document.querySelectorAll('svg.spark rect'),
                   function (r) { return !!r.getAttribute('fill'); }) };
        """)
        assert answer["cells"] >= 1
        assert answer["drawn"] == answer["cells"]
        assert all(0 < bars <= 22 for bars in answer["bars"])
        assert answer["coloured"]

    def test_the_top_view_keeps_its_furniture(self, flight):
        answer = _probe(flight, """
        var svg = document.querySelector('svg.chart-plan');
        return { compass: svg.querySelectorAll('.compass').length,
                 scalebar: svg.querySelectorAll('.scalebar text').length,
                 bar: (svg.querySelector('.scalebar text') || {}).textContent,
                 discs: svg.querySelectorAll('.plan-thermal').length,
                 byGain: svg.querySelectorAll('.plan-by-gain').length,
                 hit: svg.querySelectorAll('.hit[data-mode="xy"]').length };
        """)
        assert answer["compass"] == 1
        assert answer["scalebar"] == 1 and answer["bar"].endswith("km")
        assert answer["hit"] == 1
        # Two discs per climb, one for each encoding the toggle switches between.
        assert answer["discs"] == 2 * answer["byGain"]

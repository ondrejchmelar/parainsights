"""Tier-1 metrics on synthetic flights with known answers.

Same discipline as `test_analysis.py`: fly exact geometry so the expected number is
arithmetic rather than opinion. The tests that matter most here are the *refusals* —
every metric that cannot be supported by the data has to return `None` rather than a
plausible number, and that is the rule the debrief's credibility rests on.
"""


import pytest

from tests import js
from tests.js import needs_node
from tests.test_analysis import build, circling, straight

pytestmark = needs_node


def flight(tmp_path, name, points):
    return build(tmp_path / name, points)


def metric(path, call, *args):
    """`TV.metrics.<call>(analysis, ...args)` on the file, with the analysis beside it."""
    return js.run("""
      var a = TV.analysis.analyse(await load(input.path));
      return { value: TV.metrics[input.call].apply(null, [a].concat(input.args || [])) };
    """, path=path, call=call, args=list(args))


class TestTierOne:
    def _day(self, tmp_path, name, climbs, *, glide=200):
        """A day of climbs joined by glides. `climbs` is a list of (seconds, m/s)."""
        points, t, alt, x = [], 0.0, 1000.0, 0.0
        for seconds, rate in climbs:
            leg = circling(seconds, climb=rate, t0=t, alt0=alt, x0=x, y0=0.0)
            points += leg
            t, alt = leg[-1][0] + 1, leg[-1][3]
            run = straight(glide, speed=12.0, climb=-1.0, t0=t, alt0=alt,
                           x0=x, y0=0.0, heading=90.0)
            points += run
            t, alt, x = run[-1][0] + 1, run[-1][3], x + 12.0 * glide
        return flight(tmp_path, name, points)

    def test_climb_selection_measures_time_in_the_weaker_half(self, tmp_path):
        analysis = self._day(tmp_path, "sel.igc",
                             [(200, 2.0), (200, 0.4), (200, 0.4), (200, 0.4)])
        selection = metric(analysis, "climbSelection").value

        assert selection is not None
        assert selection.best == pytest.approx(2.0, abs=0.3)
        assert selection.weak_climbs == 3
        assert selection.weak_seconds / selection.total_seconds > 0.6

    def test_working_band_finds_where_the_lift_was(self, tmp_path):
        """One climb that is weak low and strong high: the top band must win."""
        points = circling(120, climb=0.4, alt0=1000.0)
        points += circling(120, climb=2.5, t0=121, alt0=points[-1][3])
        band = metric(flight(tmp_path, "band.igc", points), "workingBand").value

        assert band is not None
        assert int(band.climbs.argmax()) == 2, f"expected the top third to be strongest, got {band.climbs}"
        assert band.climbs[2] > band.climbs[0]

    def test_centring_compares_the_first_minute_with_the_rest(self, tmp_path):
        """Climbs that start badly and improve: the ratio is under 1 and costs time."""
        points, t, alt = [], 0.0, 1000.0
        for _ in range(3):
            slow = circling(60, climb=0.5, t0=t, alt0=alt)
            fast = circling(140, climb=2.0, t0=slow[-1][0] + 1, alt0=slow[-1][3])
            points += slow + fast
            t, alt = fast[-1][0] + 1, fast[-1][3]
            glide = straight(200, speed=12.0, climb=-1.0, t0=t, alt0=alt, heading=90.0)
            points += glide
            t, alt = glide[-1][0] + 1, glide[-1][3]
        index = metric(flight(tmp_path, "centre.igc", points), "centring").value

        assert index is not None
        assert index.ratio < 0.8, f"a slow first minute should show, got {index.ratio}"
        assert index.first < index.rest
        assert index.cost_seconds > 0

    def test_centring_is_refused_on_a_coarse_track(self, tmp_path):
        """Gated with everything else that reasons about circling."""
        points = [(t, 0.0, 0.0, 1000.0 + t) for t in range(0, 1200, 15)]
        analysis = flight(tmp_path, "coarse.igc", points)
        assert metric(analysis, "centring").value is None

    def test_climb_gaps_report_the_longest_against_the_median(self, tmp_path):
        analysis = self._day(tmp_path, "gaps.igc",
                             [(200, 1.5), (200, 1.5), (200, 1.5), (200, 1.5)])
        gaps = metric(analysis, "climbGaps").value

        assert gaps is not None
        assert gaps.median > 0
        assert gaps.longest >= gaps.median
        assert gaps.longest_loss < 0, "the gaps were glides, so height was lost"

    def test_concentration_of_gain(self, tmp_path):
        """One big climb and three small ones: the top three hold nearly everything."""
        analysis = self._day(tmp_path, "conc.igc",
                             [(400, 2.5), (200, 0.4), (200, 0.4), (200, 0.4)])
        share = metric(analysis, "concentration").value

        assert share is not None
        assert share.climbs == 4
        assert share.share > 0.8

    def test_day_envelope_sees_a_decaying_day(self, tmp_path):
        # Long glides between the climbs: the fit is refused under an hour of flying,
        # because a trend through 30 minutes of a day is not a trend.
        analysis = self._day(tmp_path, "decay.igc",
                             [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8), (300, 0.5)],
                             glide=700)
        envelope = metric(analysis, "dayEnvelope").value

        assert envelope is not None
        assert envelope.slope < 0, "a weakening day should fit a negative slope"
        assert envelope.first > envelope.last

    def test_day_envelope_refuses_a_short_flight(self, tmp_path):
        analysis = self._day(tmp_path, "short.igc",
                             [(100, 2.0), (100, 1.8), (100, 1.6), (100, 1.4)])
        assert metric(analysis, "dayEnvelope").value is None


class TestRefusals:
    """The rule that pays for the debrief: no data, no finding — not an empty card."""


    def test_ceiling_use_refuses_without_meteo(self, tmp_path):
        analysis = flight(tmp_path, "ceil.igc", circling(200, climb=2.0, alt0=1000.0))
        assert metric(analysis, "ceilingUse", None).value is None

    def test_ceiling_use_reports_a_fraction(self, tmp_path):
        analysis = flight(tmp_path, "ceil2.igc", circling(200, climb=2.0, alt0=1000.0))

        use = metric(analysis, "ceilingUse", {"cloudbase": 2000.0}).value
        assert use is not None
        assert use.ceiling == 2000
        assert 0.0 < use.fraction <= 1.2

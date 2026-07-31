"""Tier-1 metrics on synthetic flights with known answers.

Same discipline as `test_analysis.py`: fly exact geometry so the expected number is
arithmetic rather than opinion. The tests that matter most here are the *refusals* —
every metric that cannot be supported by the data has to return `None` rather than a
plausible number, and that is the rule the debrief's credibility rests on.
"""


import pytest

from tests.test_analysis import build, circling, straight
from tracklog_viewer import igc, metrics
from tracklog_viewer.analysis import analyse


def flight(tmp_path, name, points):
    return analyse(igc.parse(build(tmp_path / name, points)))


class Route:
    """Just enough of `xc.Route` for the two metrics that take one."""

    def __init__(self, distance):
        self.distance = distance


class TestCorrections:
    def test_rising_straight_flight_is_counted_outside_glides_too(self, tmp_path):
        """Correction 2: the metric is defined over straight flight, not over Phase.GLIDE.

        A straight run through lift is refused as a thermal and is too short to be a
        glide, so it is invisible to any "share of glide time in lift" measure — which is
        why that measure reads 5–8% on two good XC days.
        """
        points = straight(200, speed=12.0, climb=-1.2, alt0=2500.0, heading=90.0)
        points += straight(120, speed=12.0, climb=1.0, t0=201,
                           alt0=points[-1][3], heading=90.0)
        points += straight(200, speed=12.0, climb=-1.2, t0=322,
                           alt0=points[-1][3], heading=90.0)
        air = metrics.straight_air(flight(tmp_path, "dolphin.igc", points))

        assert air is not None
        assert air.rising_seconds > 60
        assert air.rising_gain > 0
        # The rising run is outside any glide, which is the whole point of the correction.
        assert air.gain_outside_glides > 0

    def test_cross_country_speed_uses_the_scored_route(self, tmp_path):
        """Correction 3: take-off to landing is nearly zero on a triangle."""
        analysis = flight(tmp_path, "speed.igc",
                          straight(3600, speed=10.0, climb=-0.1, alt0=3000.0))
        assert metrics.cross_country_speed(analysis, Route(36000.0)) == pytest.approx(36.0, abs=0.5)

    def test_cross_country_speed_refuses_without_a_route(self, tmp_path):
        analysis = flight(tmp_path, "noroute.igc",
                          straight(600, speed=10.0, climb=-0.5, alt0=3000.0))
        assert metrics.cross_country_speed(analysis, None) is None

    def test_glide_ratio_is_a_median_not_a_maximum(self, tmp_path):
        """Correction 4: a "glide" that crossed lift reads 116.2 on Rodella.

        Three honest glides at ~8:1 and one that barely sinks. The maximum is the outlier;
        the median is the wing.
        """
        points, t, alt, x = [], 0.0, 4000.0, 0.0
        for sink in (-1.5, -1.5, -1.5, -0.05):
            # A climb between the glides, or `_condense` welds all four into one run.
            lift = circling(200, climb=1.5, t0=t, alt0=alt, x0=x, y0=0.0)
            points += lift
            t, alt = lift[-1][0] + 1, lift[-1][3]
            leg = straight(200, speed=12.0, climb=sink, t0=t, alt0=alt,
                           x0=x, y0=0.0, heading=90.0)
            points += leg
            t, alt, x = leg[-1][0] + 1, leg[-1][3], x + 2400.0
        analysis = flight(tmp_path, "ld.igc", points)

        median = metrics.glide_ratio_median(analysis)
        ratios = [g.average_ld for g in analysis.glides if g.average_ld]
        assert median is not None
        assert ratios and median < max(ratios), "the median tracked the outlier"


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
        selection = metrics.climb_selection(analysis)

        assert selection is not None
        assert selection.best == pytest.approx(2.0, abs=0.3)
        assert selection.weak_climbs == 3
        assert selection.fraction > 0.6

    def test_working_band_finds_where_the_lift_was(self, tmp_path):
        """One climb that is weak low and strong high: the top band must win."""
        points = circling(120, climb=0.4, alt0=1000.0)
        points += circling(120, climb=2.5, t0=121, alt0=points[-1][3])
        band = metrics.working_band(flight(tmp_path, "band.igc", points))

        assert band is not None
        assert band.best == 2, f"expected the top third to be strongest, got {band.climbs}"
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
        index = metrics.centring(flight(tmp_path, "centre.igc", points))

        assert index is not None
        assert index.ratio < 0.8, f"a slow first minute should show, got {index.ratio}"
        assert index.first < index.rest
        assert index.cost_seconds > 0

    def test_centring_is_refused_on_a_coarse_track(self, tmp_path):
        """Gated with everything else that reasons about circling."""
        points = [(t, 0.0, 0.0, 1000.0 + t) for t in range(0, 1200, 15)]
        analysis = flight(tmp_path, "coarse.igc", points)
        assert metrics.centring(analysis) is None

    def test_climb_gaps_report_the_longest_against_the_median(self, tmp_path):
        analysis = self._day(tmp_path, "gaps.igc",
                             [(200, 1.5), (200, 1.5), (200, 1.5), (200, 1.5)])
        gaps = metrics.climb_gaps(analysis)

        assert gaps is not None
        assert gaps.median > 0
        assert gaps.longest >= gaps.median
        assert gaps.longest_loss < 0, "the gaps were glides, so height was lost"

    def test_concentration_of_gain(self, tmp_path):
        """One big climb and three small ones: the top three hold nearly everything."""
        analysis = self._day(tmp_path, "conc.igc",
                             [(400, 2.5), (200, 0.4), (200, 0.4), (200, 0.4)])
        share = metrics.concentration(analysis)

        assert share is not None
        assert share.climbs == 4
        assert share.share > 0.8

    def test_day_envelope_sees_a_decaying_day(self, tmp_path):
        # Long glides between the climbs: the fit is refused under an hour of flying,
        # because a trend through 30 minutes of a day is not a trend.
        analysis = self._day(tmp_path, "decay.igc",
                             [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8), (300, 0.5)],
                             glide=700)
        envelope = metrics.day_envelope(analysis)

        assert envelope is not None
        assert envelope.slope < 0, "a weakening day should fit a negative slope"
        assert envelope.first > envelope.last

    def test_day_envelope_refuses_a_short_flight(self, tmp_path):
        analysis = self._day(tmp_path, "short.igc",
                             [(100, 2.0), (100, 1.8), (100, 1.6), (100, 1.4)])
        assert metrics.day_envelope(analysis) is None

    def test_detour_ratio(self, tmp_path):
        analysis = flight(tmp_path, "detour.igc",
                          straight(1000, speed=12.0, climb=-0.5, alt0=3000.0))
        ratio = metrics.detour(analysis, Route(6000.0))

        assert ratio is not None
        assert ratio.ratio == pytest.approx(2.0, abs=0.1)

    def test_detour_refuses_without_a_route(self, tmp_path):
        analysis = flight(tmp_path, "nodetour.igc",
                          straight(600, speed=12.0, climb=-0.5, alt0=3000.0))
        assert metrics.detour(analysis, None) is None


class TestRefusals:
    """The rule that pays for the debrief: no data, no finding — not an empty card."""

    def test_lowest_save_refuses_without_terrain(self, tmp_path):
        points = circling(400, climb=1.5, alt0=1000.0)
        analysis = flight(tmp_path, "save.igc", points)
        assert metrics.lowest_save(analysis, None) is None

    def test_lowest_save_is_measured_above_the_ground(self, tmp_path):
        points = circling(400, climb=1.5, alt0=1000.0)
        analysis = flight(tmp_path, "save2.igc", points)
        clearance = [250.0] * len(analysis.series)
        save = metrics.lowest_save(analysis, clearance)

        assert save is not None
        assert save.from_agl == 250
        assert save.gain >= metrics.MIN_SAVE_GAIN

    def test_ceiling_use_refuses_without_meteo(self, tmp_path):
        analysis = flight(tmp_path, "ceil.igc", circling(200, climb=2.0, alt0=1000.0))
        assert metrics.ceiling_use(analysis, None) is None

    def test_ceiling_use_reports_a_fraction(self, tmp_path):
        analysis = flight(tmp_path, "ceil2.igc", circling(200, climb=2.0, alt0=1000.0))

        class Weather:
            cloudbase = 2000.0

        use = metrics.ceiling_use(analysis, Weather())
        assert use is not None
        assert use.ceiling == 2000
        assert 0.0 < use.fraction <= 1.2

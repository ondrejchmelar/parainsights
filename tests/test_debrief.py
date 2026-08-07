"""Debrief tests: the measurements on synthetic flights, the rules on real ones.

Two halves, for two different kinds of claim. The measurements are checked against
geometry with a known answer — a flight built from 300 s of straight sink and 300 s of
circling has exactly that in its decomposition, and nobody has to agree about what a
thermal "really" is. The rules are checked against the archive, because "a finding that
fires on most flights is a constant, not a finding" is a claim about a distribution and
cannot be tested on one made-up flight.

The archive half skips when `~/Downloads/*.igc` is not there. It reads no network.
"""

import glob
import math
from pathlib import Path

import pytest

from tracklog_viewer import airmass, debrief, sources, xc
from tracklog_viewer.analysis import analyse
from tracklog_viewer.igc import parse

from .test_analysis import build, circling, straight

ARCHIVE = sorted(glob.glob(str(Path.home() / "Downloads" / "*.igc")))


def flight_with(tmp_path, points, name="d.igc"):
    return analyse(parse(build(tmp_path / name, points)))


class TestOtherDecomposition:
    """The three parts must sum to the slice, and the slice plus the phases to airtime."""

    def test_parts_sum_to_the_slice(self, tmp_path):
        points = straight(300, climb=-1.0)
        points += circling(400, t0=301, alt0=points[-1][3], climb=1.5)
        points += straight(300, t0=702, alt0=points[-1][3], climb=-1.0,
                           x0=points[-1][1], y0=points[-1][2])
        analysis = flight_with(tmp_path, points)
        other = debrief.measure(analysis).other
        assert other.straight_sink + other.scratching + other.rising == other.seconds

    def test_slice_plus_phases_is_airtime(self, tmp_path):
        points = straight(300, climb=-1.0)
        points += circling(400, t0=301, alt0=points[-1][3], climb=1.5)
        analysis = flight_with(tmp_path, points)
        other = debrief.measure(analysis).other
        accounted = sum(s.duration for s in analysis.segments)
        # Close, not exact, and the gap is a definition rather than an error: a segment's
        # duration is `t[stop - 1] - t[start]`, which drops the interval on each side of
        # every phase boundary, while the slice is measured with midpoint weights that
        # keep it. A few seconds per boundary is the whole discrepancy — anything larger
        # means a stretch of flight is being counted twice or not at all.
        assert other.seconds + accounted == pytest.approx(
            analysis.summary.duration, rel=0.05
        )

    def test_rising_uncounted_is_not_called_a_loss(self, tmp_path):
        """A straight climb is not a thermal, and it is not a loss either.

        The straight run-in to a climb is pushed out of the thermal phase on purpose —
        that rule is what keeps the wind estimate honest. It lands in `other`, and
        publishing that slice undifferentiated would call a profitable 24 minutes a loss.
        """
        points = straight(200, climb=1.2, speed=14.0)
        points += circling(300, t0=201, alt0=points[-1][3], climb=1.5)
        analysis = flight_with(tmp_path, points)
        other = debrief.measure(analysis).other
        assert other.rising > 100
        assert other.rising_height > 100
        assert other.net_height > 0


class TestStraightFlight:
    def test_lift_is_measured_over_straight_flight_not_the_glide_phase(self, tmp_path):
        """Dolphin flying cannot be measured inside `Phase.GLIDE`.

        A glide ends where the air gives something back, so the rising parts are
        reclassified out of the phase by construction and the share inside it comes out
        implausibly low. Measured over straight flight the same seconds are visible.
        """
        points = straight(200, climb=-1.0)
        points += straight(200, t0=201, alt0=points[-1][3], climb=+0.8,
                           x0=points[-1][1], y0=points[-1][2])
        points += straight(200, t0=402, alt0=points[-1][3], climb=-1.0,
                           x0=points[-1][1], y0=points[-1][2])
        metrics = debrief.measure(flight_with(tmp_path, points))
        assert metrics.lift_seconds > 120
        assert metrics.lift_height > 100


class TestCosts:
    def test_a_finding_without_a_cost_does_not_ship(self, tmp_path):
        """The rule that stops the list becoming twelve items of trivia."""
        analysis = flight_with(tmp_path, straight(400, climb=-1.0))
        collected = []
        for finding in debrief.findings(analysis, debrief.measure(analysis)):
            collected.append(finding)
            assert finding.cost_value > 0
            assert finding.cost_unit in ("min", "m")

    def test_metres_rank_against_minutes_through_the_day_own_climb(self):
        """The one currency conversion, and it is measured rather than assumed."""
        weak = debrief._seconds_for(300, 0.5)
        strong = debrief._seconds_for(300, 3.0)
        assert weak == pytest.approx(600)
        assert strong == pytest.approx(100)
        assert weak > strong


class TestGating:
    def test_centring_is_refused_on_a_coarse_track(self, tmp_path):
        """Every circling metric inherits `TURN_RESOLUTION_LIMIT`."""
        points = circling(600, period=20.0, climb=1.5)
        coarse = [p for p in points if p[0] % 15 == 0]
        metrics = debrief.measure(flight_with(tmp_path, coarse, "coarse.igc"))
        assert metrics.coarse is True
        assert metrics.centring is None

    def test_no_terrain_means_no_ground_findings(self, tmp_path):
        points = circling(400, climb=1.5)
        analysis = flight_with(tmp_path, points)
        metrics = debrief.measure(analysis)          # no clearance passed
        assert metrics.min_clearance is None
        assert metrics.save_agl is None
        ids = {f.id for f in debrief.findings(analysis, metrics)}
        assert "low-point" not in ids and "the-save" not in ids

    def test_no_meteo_means_no_ceiling_finding(self, tmp_path):
        analysis = flight_with(tmp_path, circling(400, climb=1.5))
        metrics = debrief.measure(analysis)
        assert metrics.ceiling is None
        assert "ceiling" not in {f.id for f in debrief.findings(analysis, metrics)}


class TestVerdict:
    def test_comparison_ranks_the_shared_figures(self):
        low = debrief.Verdict("a", [debrief.Figure("scored", "10", " km", sort=10.0)])
        high = debrief.Verdict("b", [debrief.Figure("scored", "90", " km", sort=90.0)])
        debrief.compare([low, high])
        assert "best" in high.figures[0].comparison
        assert "lowest" in low.figures[0].comparison

    def test_a_lone_flight_has_nothing_to_compare_against(self):
        one = debrief.Verdict("a", [debrief.Figure("scored", "10", " km", sort=10.0)])
        debrief.compare([one])
        assert one.figures[0].comparison == ""

    def test_the_sentence_keeps_its_capitals(self, tmp_path):
        """`str.capitalize()` lower-cases everything after the first letter."""
        analysis = flight_with(tmp_path, circling(400, climb=1.5))
        metrics = debrief.measure(analysis)
        one = debrief.verdict(analysis, metrics, shape="FAI triangle")
        assert "fai triangle" not in one.sentence


@pytest.fixture(scope="module")
def fired():
    """Every finding, over every flight in the archive. Slow, so it runs once."""
    counts, cards = {}, []
    for path in ARCHIVE:
        flight = sources.load(path)
        analysis = analyse(flight)
        clock = [flight.local_time(i).strftime("%H:%M:%S") for i in range(len(flight))]
        free = xc.optimise(flight.lat, flight.lon, times=clock)
        closed = xc.triangle(flight.lat, flight.lon, times=clock)
        route = closed if closed is not None and xc.score(closed) > free.km else free
        metrics = debrief.measure(analysis, route=route,
                                  air=airmass.analyse(analysis))
        found = debrief.findings(analysis, metrics, route=route)
        cards.append(len(found))
        for finding in found:
            counts[finding.id] = counts.get(finding.id, 0) + 1
    return counts, cards


@pytest.mark.skipif(not ARCHIVE, reason="no sample tracklogs on this machine")
class TestAgainstTheArchive:
    """A metric that fires on most flights is a constant, not a finding.

    Thresholds come from the distribution over the archive rather than from a round
    number that sounded right — the first pass had three findings over 70% — so the
    distribution is what the test asserts on. Loosening a threshold that pushes one of
    these over a third is the change this test exists to catch.
    """

    def test_no_finding_fires_on_more_than_a_third(self, fired):
        counts, cards = fired
        worst = max(counts.items(), key=lambda item: item[1])
        assert worst[1] / len(cards) <= 0.34, f"{worst[0]} fires on {worst[1]}/{len(cards)}"

    def test_the_list_stays_short(self, fired):
        _, cards = fired
        assert max(cards) <= debrief.THRESHOLDS["max_findings"]
        # And it is not so short that the feature does nothing: most flights get one.
        assert sum(1 for n in cards if n) / len(cards) > 0.8

    def test_every_flight_measures_without_raising(self, fired):
        counts, cards = fired
        assert len(cards) == len(ARCHIVE)


def test_thresholds_are_serialisable():
    """`THRESHOLDS` ships into the page so quicklook reads the same numbers."""
    import json

    round_trip = json.loads(json.dumps(debrief.THRESHOLDS))
    assert round_trip["glide_progress"] == debrief.THRESHOLDS["glide_progress"]
    assert all(isinstance(v, (int, float)) for v in round_trip.values())

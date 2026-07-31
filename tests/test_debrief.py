"""The debrief layer: what fires, what refuses, and what it is forbidden to say.

The interesting tests here are not that a finding appears. They are that findings
*disappear* when the data cannot carry them, that the ranking is by cost rather than by
the order the builders happen to run in, and that no finding ever tells the pilot what
they should have done — the rule the report's credibility rests on.
"""

import pytest

from tests.test_analysis import build, circling, straight
from tracklog_viewer import debrief, igc
from tracklog_viewer.analysis import analyse


def flight(tmp_path, name, points):
    return analyse(igc.parse(build(tmp_path / name, points)))


def a_day(tmp_path, name, climbs, *, glide=200):
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


class Route:
    def __init__(self, distance, *, closed=False, sides=None, points=None):
        self.distance = distance
        self.closed = closed
        self.sides = sides or []
        self.points = points or []


class TestVoice:
    """A finding is a measurement plus a link, never an imperative."""

    FORBIDDEN = (
        "you should", "should have", "you could", "could have", "try to",
        "make sure", "next time", "consider ", "avoid ", "remember to",
    )

    def test_no_finding_gives_advice(self, tmp_path):
        analysis = a_day(tmp_path, "voice.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        result = debrief.build(analysis)

        assert result.findings, "expected this day to produce at least one finding"
        for finding in result.findings:
            text = f"{finding.title} {finding.sentence}".lower()
            for phrase in self.FORBIDDEN:
                assert phrase not in text, f"{finding.id} gives advice: {text!r}"

    def test_the_verdict_is_not_advice_either(self, tmp_path):
        analysis = a_day(tmp_path, "verdict.igc",
                         [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8), (300, 0.5)],
                         glide=700)
        verdict = debrief.build(analysis).verdict

        assert verdict is not None
        text = verdict.sentence.lower()
        for phrase in self.FORBIDDEN:
            assert phrase not in text


class TestCostAndRanking:
    def test_every_finding_carries_a_cost(self, tmp_path):
        """A finding with no cost does not ship."""
        analysis = a_day(tmp_path, "cost.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        for finding in debrief.build(analysis).findings:
            assert finding.cost is not None
            assert finding.cost.unit in ("min", "m")
            assert finding.cost.value > 0
            assert finding.cost.label

    def test_findings_are_ranked_by_cost_share(self, tmp_path):
        analysis = a_day(tmp_path, "rank.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        shares = [f.cost.share for f in debrief.build(analysis).findings]
        assert shares == sorted(shares, reverse=True)

    def test_the_card_count_is_capped(self, tmp_path):
        analysis = a_day(tmp_path, "cap.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        assert len(debrief.build(analysis, limit=2).findings) <= 2


class TestRefusals:
    """Degrade, do not blank — the rule that pays for the debrief."""

    def _analysis(self, tmp_path, name="ref.igc"):
        return a_day(tmp_path, name,
                     [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                     glide=700)

    def test_terrain_findings_do_not_exist_without_terrain(self, tmp_path):
        result = debrief.build(self._analysis(tmp_path))
        assert "low-point" not in {f.id for f in result.findings}
        assert "terrain" in result.suppressed

    def test_ceiling_findings_do_not_exist_without_meteo(self, tmp_path):
        result = debrief.build(self._analysis(tmp_path))
        assert "ceiling-used" not in {f.id for f in result.findings}
        assert "meteo" in result.suppressed

    def test_route_findings_do_not_exist_without_a_route(self, tmp_path):
        result = debrief.build(self._analysis(tmp_path))
        ids = {f.id for f in result.findings}
        assert "detour" not in ids and "near-close" not in ids
        assert "route" in result.suppressed

    def test_the_ceiling_finding_appears_once_meteo_is_supplied(self, tmp_path):
        class Weather:
            cloudbase = 6000.0

        result = debrief.build(self._analysis(tmp_path), weather=Weather())
        assert "ceiling-used" in {f.id for f in result.findings}

    def test_the_low_point_appears_once_terrain_is_supplied(self, tmp_path):
        analysis = self._analysis(tmp_path, "low.igc")
        clearance = [500.0] * len(analysis.series)
        clearance[len(clearance) // 2] = 40.0
        result = debrief.build(analysis, clearance=clearance)

        low = next((f for f in result.findings if f.id == "low-point"), None)
        assert low is not None
        assert "40 m" in low.title
        assert low.cursor is not None, "the card has to be able to say 'show me'"


class Point:
    def __init__(self, lat, lon):
        self.lat, self.lon = lat, lon


class TestRouteFindings:
    """UX findings 6 and the detour ratio: framing of numbers already on the page."""

    def _analysis(self, tmp_path, name="route.igc"):
        return a_day(tmp_path, name,
                     [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                     glide=700)

    def test_a_triangle_that_nearly_closed_is_reported_with_what_it_would_have_scored(
        self, tmp_path
    ):
        # Start and finish ~1.6 km apart, on a route whose sides total 60 km.
        route = Route(
            48000.0,
            closed=False,
            sides=[20000.0, 20000.0, 20000.0],
            points=[Point(49.0, 14.0), Point(49.2, 14.2), Point(49.1, 14.3),
                    Point(49.0, 14.022)],
        )
        card = debrief._close_that_wasnt(self._analysis(tmp_path), route)

        assert card is not None
        assert "closing" in card.title
        # Equal sides are an FAI triangle, which is the ×1.4 multiplier.
        assert card.evidence["category"] == "fai"
        assert card.evidence["multiplier"] == pytest.approx(1.4)

    def test_a_closed_triangle_has_no_near_miss_to_report(self, tmp_path):
        route = Route(48000.0, closed=True, sides=[20000.0, 20000.0, 20000.0],
                      points=[Point(49.0, 14.0), Point(49.2, 14.2), Point(49.1, 14.3)])
        assert debrief._close_that_wasnt(self._analysis(tmp_path), route) is None

    def test_detour_is_measured_against_the_scored_route(self, tmp_path):
        analysis = self._analysis(tmp_path, "detour.igc")
        track = analysis.summary.track_distance
        card = debrief._detour(analysis, Route(track / 3.0))

        assert card is not None
        assert card.evidence["ratio"] == pytest.approx(3.0, abs=0.05)


class TestOtherSlice:
    def test_a_profitable_slice_is_not_reported_as_a_loss(self, tmp_path):
        """The plan's first correction, in the card's own words.

        On the reference flight `other` nets +385 m. A card saying "you lost 40 minutes"
        would be the first confidently wrong sentence in the report.
        """
        points = straight(240, speed=12.0, climb=1.0, alt0=1000.0, heading=90.0)
        points += circling(300, climb=1.5, t0=241, alt0=points[-1][3])
        points += straight(240, speed=12.0, climb=1.0, t0=542,
                           alt0=points[-1][3], heading=90.0)
        analysis = flight(tmp_path, "profit.igc", points)

        assert analysis.other.net_altitude > 0
        card = debrief._other_slice(analysis)
        # Either it is suppressed for want of a lossy part, or it says "gained".
        if card is not None:
            assert "gained" in card.title
            assert "lost" not in card.title


class TestSerialisation:
    def test_thresholds_ship_with_the_debrief(self, tmp_path):
        """So `quicklook.py` reads these numbers rather than holding a second copy."""
        analysis = a_day(tmp_path, "ser.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        payload = debrief.build(analysis).to_dict()

        assert payload["thresholds"] == debrief.THRESHOLDS
        assert isinstance(payload["findings"], list)
        for finding in payload["findings"]:
            assert finding["cost"]["label"]
            assert set(finding) >= {"id", "title", "sentence", "cost", "evidence"}

    def test_the_payload_is_json_serialisable(self, tmp_path):
        import json

        analysis = a_day(tmp_path, "json.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        json.dumps(debrief.build(analysis).to_dict())

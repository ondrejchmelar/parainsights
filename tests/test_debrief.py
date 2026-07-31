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
    def __init__(self, distance, *, closed=False, sides=None, points=None,
                 kind="fai_triangle", shape="fai"):
        self.distance = distance
        self.closed = closed
        self.sides = sides or []
        self.points = points or []
        # Only a route from `triangle()` may claim a triangle category, so the findings
        # ask for `kind`/`shape` rather than classifying the sides themselves.
        self.kind = kind
        self.shape = shape


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


class TestLowPoint:
    """Two bugs that only real flights could find."""

    def _analysis(self, tmp_path):
        return a_day(tmp_path, "low2.igc",
                     [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8)], glide=700)

    def test_the_launch_and_landing_cannot_win(self, tmp_path):
        """The lowest ground clearance of any flight is the ground it started on.

        On the reference flight the minimum is 1 m at t=25 s — the takeoff — while the
        lowest point actually flown is 441 m. Reporting a launch as a scrape is the
        confidently wrong sentence the debrief cannot afford.
        """
        analysis = self._analysis(tmp_path)
        n = len(analysis.series)
        clearance = [800.0] * n
        clearance[:40] = [2.0] * 40          # on the ground at the start
        clearance[-40:] = [2.0] * 40         # and at the end
        clearance[n // 2] = 60.0             # the real low point, in flight

        card = debrief._low_point(analysis, clearance)
        assert card is not None
        assert "60 m" in card.title, f"the launch or landing won: {card.title!r}"
        assert card.evidence["lowest"] == 60

    def test_a_flight_that_never_got_low_produces_nothing(self, tmp_path):
        analysis = self._analysis(tmp_path)
        clearance = [800.0] * len(analysis.series)
        assert debrief._low_point(analysis, clearance) is None

    def test_a_negative_clearance_is_not_printed_as_a_number(self, tmp_path):
        """It means the DEM and the GPS disagree, not that the glider was underground.

        Measured on a 400 km flight: about 1.2 km per DEM cell, which averages a valley
        floor with the ridges beside it — the same flight reads -36 m alone and -227 m in
        a shared document, where the per-flight budget is halved.
        """
        analysis = self._analysis(tmp_path)
        n = len(analysis.series)
        clearance = [800.0] * n
        clearance[n // 2] = -227.0

        card = debrief._low_point(analysis, clearance)
        assert card is not None
        assert "-227" not in card.title, f"a negative clearance was headlined: {card.title!r}"
        # Wording-agnostic: what matters is that the card blames the model rather than
        # asserting the glider was underground, not which noun it picks for the model.
        assert "model" in card.title.lower()
        assert card.confidence < 1.0, "an untrustworthy number must be downgraded"


class TestTriangleCategory:
    """Only a route from `triangle()` may claim a triangle category.

    The verdict classified `route.sides` directly, which called a 64 km open-distance
    flight a "flat triangle" while the flight picker three centimetres above it said
    OPEN DISTANCE. `Route.shape` is where that rule lives.
    """

    def _analysis(self, tmp_path):
        return a_day(tmp_path, "cat.igc",
                     [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8)], glide=700)

    def test_an_open_route_is_not_called_a_triangle(self, tmp_path):
        route = Route(64000.0, sides=[20000.0, 20000.0, 24000.0],
                      kind="free_3tp", shape="open")
        verdict = debrief._verdict(self._analysis(tmp_path), route, None)

        assert verdict is not None
        assert "triangle" not in verdict.sentence, verdict.sentence

    def test_a_real_triangle_still_is_one(self, tmp_path):
        route = Route(201000.0, sides=[70000.0, 65000.0, 66000.0],
                      kind="fai_triangle", shape="fai")
        verdict = debrief._verdict(self._analysis(tmp_path), route, None)

        assert verdict is not None
        assert "FAI triangle" in verdict.sentence, verdict.sentence

    def test_the_near_close_finding_refuses_an_open_route(self, tmp_path):
        """`optimise()`'s route is a four-leg path, not a perimeter, so asking what
        multiplier it would have earned compares two different quantities."""
        route = Route(64000.0, sides=[20000.0, 20000.0, 24000.0],
                      kind="free_3tp", shape="open",
                      points=[Point(49.0, 14.0), Point(49.2, 14.2),
                              Point(49.1, 14.3), Point(49.0, 14.01)])
        assert debrief._close_that_wasnt(self._analysis(tmp_path), route) is None

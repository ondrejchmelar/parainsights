"""The debrief layer: what fires, what refuses, and what it is forbidden to say.

The interesting tests here are not that a finding appears. They are that findings
*disappear* when the data cannot carry them, that the ranking is by cost rather than by
the order the builders happen to run in, and that no finding ever tells the pilot what
they should have done — the rule the report's credibility rests on.
"""

import math

import pytest

from tests import js
from tests.js import needs_node
from tests.test_analysis import build, circling, straight

pytestmark = needs_node


def flight(tmp_path, name, points):
    return build(tmp_path / name, points)


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


def debrief(path, **options):
    """`TV.debrief.build` on the file, serialised. A `clearance` option is built in JS from
    the series length (`CLEARANCE`): {"base": m, "runs": [[from, to, m]], "at": [[fraction, m]]}."""
    return js.run("""
      var a = TV.analysis.analyse(await load(input.path));
      var o = input.options;
      if (o.clearance) o.clearance = clearance(a, o.clearance);
      return TV.debrief.toDict(TV.debrief.build(a, o));
    """ + CLEARANCE, path=path, options=options)


def part(path, name, *args):
    """One of the debrief's builders on its own: `TV.debrief.parts[name](a, ...args)`."""
    return js.run("""
      var a = TV.analysis.analyse(await load(input.path));
      var args = input.args.map(function (x) { return x && x.base !== undefined ? clearance(a, x) : x; });
      return { value: TV.debrief.parts[input.name].apply(null, [a].concat(args)), other: a.other,
               track: a.summary.track_distance };
    """ + CLEARANCE, path=path, name=name, args=list(args))


CLEARANCE = """
  function clearance(a, spec) {
    var n = a.series.t.length, out = new Array(n).fill(spec.base);
    (spec.runs || []).forEach(function (r) {
      var from = r[0] < 0 ? n + r[0] : r[0], to = r[1] <= 0 ? n + r[1] : r[1];
      for (var i = from; i < to; i++) out[i] = r[2];
    });
    (spec.at || []).forEach(function (p) { out[Math.floor(n * p[0])] = p[1]; });
    return out;
  }
"""


# ---- routes ---------------------------------------------------------------------------
#
# `xc.sides` reads a route's three corners from its five points (start, three turnpoints,
# finish), so a triangle here is a real one on the map rather than a list of side lengths.

def _offset(lat, lon, east_km, north_km):
    return (lat + north_km / 111.195,
            lon + east_km / (111.195 * math.cos(math.radians(lat))))


def route(kind, side_km, *, gap_km=0.0, closed=False, scored_km=None):
    a = (49.0, 14.0)
    b = _offset(*a, side_km, 0.0)
    c = _offset(*a, side_km / 2, side_km * math.sqrt(3) / 2)
    start, finish = a, _offset(*a, gap_km, 0.0)
    points = [dict(lat=p[0], lon=p[1], index=i, time="")
              for i, p in enumerate([start, a, b, c, finish])]
    return {"kind": kind, "closed": closed, "points": points,
            "distance": (scored_km or 3 * side_km) * 1000.0, "legs": []}


DAY = [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)]


class TestVoice:
    """A finding is a measurement plus a link, never an imperative."""

    FORBIDDEN = (
        "you should", "should have", "you could", "could have", "try to",
        "make sure", "next time", "consider ", "avoid ", "remember to",
    )

    def test_no_finding_gives_advice(self, tmp_path):
        result = debrief(a_day(tmp_path, "voice.igc", DAY, glide=700))
        assert result.findings, "expected this day to produce at least one finding"
        for finding in result.findings:
            text = f"{finding.title} {finding.sentence}".lower()
            for phrase in self.FORBIDDEN:
                assert phrase not in text, f"{finding.id} gives advice: {text!r}"

    def test_the_verdict_is_not_advice_either(self, tmp_path):
        path = a_day(tmp_path, "verdict.igc",
                     [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8), (300, 0.5)], glide=700)
        verdict = debrief(path).verdict
        assert verdict is not None
        text = verdict.sentence.lower()
        for phrase in self.FORBIDDEN:
            assert phrase not in text


class TestCostAndRanking:
    def test_every_finding_carries_a_cost(self, tmp_path):
        """A finding with no cost does not ship."""
        for finding in debrief(a_day(tmp_path, "cost.igc", DAY, glide=700)).findings:
            assert finding.cost is not None
            assert finding.cost.unit in ("min", "m")
            assert finding.cost.value > 0
            assert finding.cost.label

    def test_findings_are_ranked_by_cost_share(self, tmp_path):
        shares = [f.cost.share for f in debrief(a_day(tmp_path, "rank.igc", DAY, glide=700)).findings]
        assert shares == sorted(shares, reverse=True)

    def test_the_card_count_is_capped(self, tmp_path):
        assert len(debrief(a_day(tmp_path, "cap.igc", DAY, glide=700), limit=2).findings) <= 2


class TestRefusals:
    """Degrade, do not blank — the rule that pays for the debrief."""

    def _day(self, tmp_path, name="ref.igc"):
        return a_day(tmp_path, name, DAY, glide=700)

    def test_terrain_findings_do_not_exist_without_terrain(self, tmp_path):
        result = debrief(self._day(tmp_path))
        assert "low-point" not in {f.id for f in result.findings}
        assert "terrain" in result.suppressed

    def test_ceiling_findings_do_not_exist_without_meteo(self, tmp_path):
        result = debrief(self._day(tmp_path))
        assert "ceiling-used" not in {f.id for f in result.findings}
        assert "meteo" in result.suppressed

    def test_route_findings_do_not_exist_without_a_route(self, tmp_path):
        result = debrief(self._day(tmp_path))
        ids = {f.id for f in result.findings}
        assert "detour" not in ids and "near-close" not in ids
        assert "route" in result.suppressed

    def test_the_ceiling_finding_appears_once_meteo_is_supplied(self, tmp_path):
        result = debrief(self._day(tmp_path), weather={"cloudbase": 6000.0})
        assert "ceiling-used" in {f.id for f in result.findings}

    def test_the_low_point_appears_once_terrain_is_supplied(self, tmp_path):
        result = debrief(self._day(tmp_path, "low.igc"),
                         clearance={"base": 500.0, "at": [[0.5, 40.0]]})
        low = next((f for f in result.findings if f.id == "low-point"), None)
        assert low is not None
        assert "40 m" in low.title
        assert low.cursor is not None, "the card has to be able to say 'show me'"


class TestRouteFindings:
    """UX findings 6 and the detour ratio: framing of numbers already on the page."""

    def _day(self, tmp_path, name="route.igc"):
        return a_day(tmp_path, name, DAY, glide=700)

    def test_a_triangle_that_nearly_closed_is_reported_with_what_it_would_have_scored(
        self, tmp_path
    ):
        # Start and finish 1.6 km apart, on an equilateral 60 km triangle.
        card = part(self._day(tmp_path), "closeThatWasnt",
                    route("fai_triangle", 20.0, gap_km=1.6, scored_km=48.0)).value
        assert card is not None
        assert "closing" in card.title
        # Equal sides are an FAI triangle, which is the ×1.4 multiplier.
        assert card.evidence["category"] == "fai"
        assert card.evidence["multiplier"] == pytest.approx(1.4)

    def test_a_closed_triangle_has_no_near_miss_to_report(self, tmp_path):
        assert part(self._day(tmp_path), "closeThatWasnt",
                    route("fai_triangle", 20.0, closed=True)).value is None

    def test_flying_far_to_score_little_is_not_a_finding(self, tmp_path):
        """"You flew 121 km to score 48.64 km" describes the scoring rules, not the day.

        A scored route is three turnpoints through a track that also had to climb, so the
        ratio between the two is near-constant for the discipline — and charging the
        difference as a cost in metres made a rule of the sport read as a mistake the
        pilot made.
        """
        path = self._day(tmp_path, "detour.igc")
        track = part(path, "lowPoint", None).track
        scored = {"kind": "free_3tp", "closed": False, "points": [], "legs": [],
                  "distance": track / 3.0}
        ids = {f.id for f in debrief(path, route=scored).findings}
        assert "detour" not in ids


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
        out = part(flight(tmp_path, "profit.igc", points), "otherSlice")
        assert out.other.net_altitude > 0
        card = out.value
        # Either it is suppressed for want of a lossy part, or it says "gained".
        if card is not None:
            assert "gained" in card.title
            assert "lost" not in card.title


class TestSerialisation:
    def test_thresholds_ship_with_the_debrief(self, tmp_path):
        """The thresholds travel with the debrief, so a reader of it has the numbers it was
        judged by rather than a second copy."""
        payload = debrief(a_day(tmp_path, "ser.igc", DAY, glide=700))
        assert payload["thresholds"] == js.run("return TV.debrief.THRESHOLDS;")
        assert isinstance(payload["findings"], list)
        for finding in payload["findings"]:
            assert finding["cost"]["label"]
            assert set(finding) >= {"id", "title", "sentence", "cost", "evidence"}


class TestLowPoint:
    """Two bugs that only real flights could find."""

    def _day(self, tmp_path):
        return a_day(tmp_path, "low2.igc", [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8)], glide=700)

    def test_the_launch_and_landing_cannot_win(self, tmp_path):
        """The lowest ground clearance of any flight is the ground it started on.

        On the reference flight the minimum is 1 m at t=25 s — the takeoff — while the
        lowest point actually flown is 441 m. Reporting a launch as a scrape is the
        confidently wrong sentence the debrief cannot afford.
        """
        card = part(self._day(tmp_path), "lowPoint",
                    {"base": 800.0, "runs": [[0, 40, 2.0], [-40, 0, 2.0]], "at": [[0.5, 60.0]]}).value
        assert card is not None
        assert "60 m" in card.title, f"the launch or landing won: {card.title!r}"
        assert card.evidence["lowest"] == 60

    def test_a_flight_that_never_got_low_produces_nothing(self, tmp_path):
        assert part(self._day(tmp_path), "lowPoint", {"base": 800.0}).value is None

    def test_a_negative_clearance_produces_no_card_at_all(self, tmp_path):
        """It means the DEM and the GPS disagree, not that the glider was underground.

        Measured on a 400 km flight: about 1.2 km per DEM cell, which averages a valley
        floor with the ridges beside it — the same flight reads -36 m alone and -227 m in
        a shared document, where the per-flight budget is halved.

        A card that explained why its own headline was wrong was tried first and was worse
        than nothing: "the elevation model puts you underground at 15:35:38" sat at the
        top of a ranked list of things the flight did, and no disclaimer underneath undid
        that framing. There is nothing here to tell the pilot, so nothing is told.
        """
        assert part(self._day(tmp_path), "lowPoint",
                    {"base": 800.0, "at": [[0.5, -227.0]]}).value is None


class TestLowPointOverTheValley:
    """How low a pilot was is how far above the ground they would land on — the valley —
    not the slope beneath. 70 m over a ridge top with 500 m to the valley beside it is
    ridge soaring, and was reported as the closest call of the day."""

    def _day(self, tmp_path):
        return a_day(tmp_path, "valley.igc", [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8)], glide=700)

    def test_skimming_a_ridge_high_over_the_valley_is_not_a_low_point(self, tmp_path):
        card = part(self._day(tmp_path), "lowPoint",
                    {"base": 800.0, "at": [[0.5, 70.0]]},
                    {"base": 1200.0, "at": [[0.5, 520.0]]}).value
        assert card is None, card

    def test_a_low_save_over_the_valley_is_one_and_says_so(self, tmp_path):
        card = part(self._day(tmp_path), "lowPoint",
                    {"base": 800.0, "at": [[0.5, 150.0]]},
                    {"base": 1200.0, "at": [[0.5, 180.0]]}).value
        assert card is not None
        assert card["title"] == "Your lowest was 180 m above the valley floor"
        assert card["evidence"]["valley"] and card["evidence"]["lowest"] == 180

    def test_the_glide_out_to_land_cannot_win(self, tmp_path):
        """After the last climb the flight only goes down, and always ends lower than any
        low point it climbed out of."""
        card = part(self._day(tmp_path), "lowPoint",
                    {"base": 800.0},
                    {"base": 1200.0, "at": [[0.97, 150.0]]}).value
        assert card is None, card


class TestTriangleCategory:
    """Only a route from `triangle()` may claim a triangle category.

    The verdict classified the sides directly, which called a 64 km open-distance flight
    a "flat triangle" while the flight picker three centimetres above it said OPEN
    DISTANCE. `xc.shape` is where that rule lives.
    """

    def _day(self, tmp_path):
        return a_day(tmp_path, "cat.igc", [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8)], glide=700)

    def test_an_open_route_is_not_called_a_triangle(self, tmp_path):
        verdict = part(self._day(tmp_path), "verdict", route("free_3tp", 21.3), None).value
        assert verdict is not None
        assert "triangle" not in verdict.sentence, verdict.sentence

    def test_a_real_triangle_still_is_one(self, tmp_path):
        verdict = part(self._day(tmp_path), "verdict", route("fai_triangle", 67.0), None).value
        assert verdict is not None
        assert "FAI triangle" in verdict.sentence, verdict.sentence

    def test_the_near_close_finding_refuses_an_open_route(self, tmp_path):
        """`optimise()`'s route is a four-leg path, not a perimeter, so asking what
        multiplier it would have earned compares two different quantities."""
        assert part(self._day(tmp_path), "closeThatWasnt",
                    route("free_3tp", 21.3, gap_km=0.7)).value is None

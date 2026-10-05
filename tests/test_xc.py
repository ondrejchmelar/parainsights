"""Free-distance optimisation tests, on routes whose optimum is known by hand."""

import math

import numpy as np
import pytest

from tests import js
from tests.js import needs_node

pytestmark = needs_node

LAT0, LON0 = 49.0, 14.0
R = 6371000.0


def leg(bearing_deg: float, km: float, steps: int = 60, start=(0.0, 0.0)):
    """Points along a straight leg, in local metres."""
    x0, y0 = start
    return [(x0 + km * 1000 * i / steps * math.sin(math.radians(bearing_deg)),
             y0 + km * 1000 * i / steps * math.cos(math.radians(bearing_deg)))
            for i in range(1, steps + 1)]


def to_arrays(points):
    lat = np.array([LAT0 + math.degrees(y / R) for _, y in points])
    lon = np.array([LON0 + math.degrees(x / (R * math.cos(math.radians(LAT0)))) for x, _ in points])
    return lat, lon


def optimise(lat, lon, turnpoints=None):
    """`TV.xc.optimise`, with its shape and score beside it."""
    return js.run("""
      var r = TV.xc.optimise(input.lat, input.lon, undefined, input.k === null ? undefined : input.k);
      r.km = r.distance / 1000; r.shape = TV.xc.shape(r);
      r.track = TV.geo.cumulativeDistance(input.lat, input.lon).slice(-1)[0];
      return r;""", lat=lat, lon=lon, k=turnpoints)


def triangle(lat, lon, samples):
    return js.run("""
      var r = TV.xc.triangle(input.lat, input.lon, undefined, input.samples);
      if (r) { r.km = r.distance / 1000; r.shape = TV.xc.shape(r); r.sides = TV.xc.sides(r); }
      return r;""", lat=lat, lon=lon, samples=samples)


def test_straight_line_scores_its_own_length():
    route = optimise(*to_arrays([(0.0, 0.0)] + leg(90, 50)))
    assert route.km == pytest.approx(50.0, rel=0.01)
    assert not route.closed


def test_dogleg_needs_a_turnpoint():
    """Out 40 km east then 40 km north: 80 km with a turnpoint, 56.6 without."""
    points = [(0.0, 0.0)] + leg(90, 40)
    points += leg(0, 40, start=points[-1])
    lat, lon = to_arrays(points)
    assert optimise(lat, lon, 0).km == pytest.approx(56.6, rel=0.02)
    assert optimise(lat, lon, 1).km == pytest.approx(80.0, rel=0.02)


def test_more_turnpoints_never_score_less():
    points = [(0.0, 0.0)] + leg(90, 30)
    points += leg(20, 25, start=points[-1])
    points += leg(200, 20, start=points[-1])
    points += leg(120, 28, start=points[-1])
    lat, lon = to_arrays(points)
    scores = [optimise(lat, lon, k).km for k in range(4)]
    assert scores == sorted(scores)


def test_turnpoints_stay_in_time_order():
    points = [(0.0, 0.0)] + leg(90, 30)
    points += leg(180, 25, start=points[-1])
    points += leg(270, 30, start=points[-1])
    route = optimise(*to_arrays(points))
    indices = [p.index for p in route.points]
    assert indices == sorted(indices)
    assert len(route.points) == 5  # start, three turnpoints, finish


def test_distance_never_exceeds_the_track_flown():
    points = [(0.0, 0.0)] + leg(90, 20)
    points += leg(45, 20, start=points[-1])
    points += leg(315, 20, start=points[-1])
    route = optimise(*to_arrays(points))
    assert route.distance <= route.track + 1.0


def test_triangle_is_flagged_closed():
    """Equilateral-ish circuit returning near the start."""
    points = [(0.0, 0.0)] + leg(90, 30)
    points += leg(210, 30, start=points[-1])
    points += leg(330, 30, start=points[-1])
    route = optimise(*to_arrays(points))
    assert route.closed
    assert route.km == pytest.approx(90.0, rel=0.03)


def test_legs_sum_to_the_total():
    route = optimise(*to_arrays([(0.0, 0.0)] + leg(70, 45)))
    assert sum(route.legs) == pytest.approx(route.distance, rel=1e-6)


def test_large_track_is_sampled_not_exhausted():
    lat, lon = to_arrays([(0.0, 0.0)] + leg(90, 100, steps=20000))
    route = optimise(lat, lon)
    assert route.km == pytest.approx(100.0, rel=0.02)
    assert len(lat) > js.run("return TV.xc.MAX_SAMPLES;")  # the sampling path was exercised


def test_a_turnpoint_between_samples_is_found_on_the_full_track():
    """The optimum is searched on a sample, ~1 fix in 50 on a long flight, then each
    turnpoint slides over the full-resolution fixes. Without the slide two real flights
    scored 39.87 and 70.97 km where XContest says 40.25 and 71.17 — the furthest fix sat
    between samples. Here it is the peak of a 300 m bump off a straight line: the best
    route goes through it exactly."""
    points = [(0.0, 0.0)] + leg(90, 60, steps=20000)
    # A bump 300 m high peaking at one fix, gradual enough that sampling by distance
    # flown lands on its slopes rather than on the peak.
    spike = 10007
    for i in range(spike - 40, spike + 41):
        x, y = points[i]
        points[i] = (x, y + 300.0 * (1 - abs(i - spike) / 41))
    lat, lon = to_arrays(points)
    # One turnpoint, so the best route is start, spike, finish and nothing else.
    route = optimise(lat, lon, 1)
    assert spike in [p["index"] for p in route.points]
    exact = js.run("""var d = TV.geo.distance;
      return d(input.lat[0], input.lon[0], input.lat[input.k], input.lon[input.k]) +
             d(input.lat[input.k], input.lon[input.k], input.lat[input.n], input.lon[input.n]);""",
                   lat=lat, lon=lon, k=spike, n=len(lat) - 1)
    assert route.distance == pytest.approx(exact, abs=1.0)


class TestShape:
    """XContest's categories: closure under the 20% rule, then FAI's 28% shortest side."""

    def _shape(self, corners, *, close=True, kind=None, legs=None):
        points = [corners[0]] + list(corners) + ([corners[0]] if close else [(corners[0][0] + 3.0, corners[0][1])])
        route = {"kind": kind or ("fai_triangle" if close else "free_3tp"), "closed": close,
                 "points": [{"index": i, "lat": p[0], "lon": p[1], "time": None} for i, p in enumerate(points)],
                 "legs": legs, "distance": 1.0}
        return js.run("""var r = input.route;
          if (!r.legs) r.legs = r.points.slice(1).map(function (p, i) {
            return TV.geo.distance(r.points[i].lat, r.points[i].lon, p.lat, p.lon); });
          return { shape: TV.xc.shape(r), sides: TV.xc.sides(r), legs: r.legs };""", route=route)

    def test_equilateral_triangle_is_fai(self):
        # Each side a third of the perimeter, comfortably over the 28% floor.
        assert self._shape([(49.0, 14.0), (49.45, 14.0), (49.225, 14.6)]).shape == "fai"

    def test_one_short_side_is_a_flat_triangle(self):
        # A long thin triangle: shortest side well under 28% but not degenerate.
        route = self._shape([(49.0, 14.0), (49.9, 14.0), (49.95, 14.25)])
        assert min(route.sides) / sum(route.sides) < 0.28
        assert route.shape == "flat"

    def test_a_closed_there_and_back_is_still_a_flat_triangle(self):
        """Its shortest side is a quarter of the perimeter, not nothing: a + b = c when a
        triangle is flattened onto a line. So no degeneracy test on side ratios can find
        this, and XContest scores it as a flat triangle regardless."""
        route = self._shape([(49.0, 14.0), (49.8, 14.0), (49.4, 14.0)])
        assert min(route.sides) / sum(route.sides) == pytest.approx(0.25, abs=0.01)
        assert route.shape == "flat"

    def test_an_unclosed_route_is_open_whatever_its_corners(self):
        assert self._shape([(49.0, 14.0), (49.45, 14.0), (49.225, 14.6)], close=False).shape == "open"

    def test_the_open_optimum_never_claims_a_triangle(self):
        """Its distance is the four-leg path from start to finish, not a perimeter. Scoring
        it as a triangle compares two different quantities, and it won every time."""
        route = self._shape([(49.0, 14.0), (49.45, 14.0), (49.225, 14.6)], kind="free_3tp",
                            legs=[1.0, 1.0, 1.0, 1.0])
        assert route.shape == "open"

    def test_sides_are_the_triangle_not_the_legs(self):
        route = self._shape([(49.0, 14.0), (49.45, 14.0), (49.225, 14.6)])
        assert len(route.legs) == 4
        assert len(route.sides) == 3


class TestScoredTriangle:
    """`triangle()` maximises perimeter × multiplier, which is what XContest ranks by."""

    def test_score_prefers_a_shorter_fai_triangle_over_a_longer_flat_one(self):
        """The rule that matters, stated as arithmetic. The real case: a flight whose
        longest triangle is flat at 51.0 km and whose best FAI triangle is 48.6 km.
        XContest reports the FAI one because 48.6 x 1.4 beats 51.0 x 1.2, so maximising
        distance alone gets both the number and the category wrong."""
        multiplier = js.run("return TV.xc.MULTIPLIER;")
        assert 48.6 * multiplier["fai"] > 51.0 * multiplier["flat"]
        assert multiplier["open"] < multiplier["flat"] < multiplier["fai"]

    def test_finds_an_equilateral_loop_and_calls_it_fai(self):
        corners = [(49.0, 14.0), (49.45, 14.0), (49.225, 14.62)]
        lat, lon = [], []
        for a, b in zip(corners + corners[:1], corners[1:] + corners[:1]):
            lat += list(np.linspace(a[0], b[0], 90))
            lon += list(np.linspace(a[1], b[1], 90))
        route = triangle(np.array(lat), np.array(lon), 140)
        assert route is not None
        assert route.shape == "fai"
        expected = js.run("""var c = input.c, s = 0;
          for (var i = 0; i < 3; i++) s += TV.geo.distance(c[i][0], c[i][1], c[(i + 1) % 3][0], c[(i + 1) % 3][1]);
          return s;""", c=corners)
        # The corners are on the track, so the optimum is the triangle itself.
        assert route.distance == pytest.approx(expected, rel=0.02)

    def test_refuses_a_course_that_does_not_close(self):
        # A straight line out: no closing, so no triangle at any multiplier.
        route = triangle(np.linspace(49.0, 50.0, 300), np.full(300, 14.0), 120)
        assert route is None or route.km < 1.0

    def test_points_close_the_figure_for_the_plan_view(self):
        lat = np.array(list(np.linspace(49.0, 49.4, 80)) + list(np.linspace(49.4, 49.2, 80))
                       + list(np.linspace(49.2, 49.0, 80)))
        lon = np.array(list(np.full(80, 14.0)) + list(np.linspace(14.0, 14.5, 80))
                       + list(np.linspace(14.5, 14.0, 80)))
        route = triangle(lat, lon, 120)
        assert route is not None
        assert len(route.points) == 5
        assert route.points[0].index == route.points[-1].index
        assert len(route.sides) == 3

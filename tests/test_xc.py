"""Free-distance optimisation tests, on routes whose optimum is known by hand."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tracklog_viewer import geo, xc
from tracklog_viewer.geo import R

LAT0, LON0 = 49.0, 14.0


def leg(bearing_deg: float, km: float, steps: int = 60, start=(0.0, 0.0)):
    """Points along a straight leg, in local metres."""
    x0, y0 = start
    out = []
    for i in range(1, steps + 1):
        distance = km * 1000 * i / steps
        out.append(
            (
                x0 + distance * math.sin(math.radians(bearing_deg)),
                y0 + distance * math.cos(math.radians(bearing_deg)),
            )
        )
    return out


def to_arrays(points):
    lat = np.array([LAT0 + math.degrees(y / R) for _, y in points])
    lon = np.array(
        [LON0 + math.degrees(x / (R * math.cos(math.radians(LAT0)))) for x, _ in points]
    )
    return lat, lon


def test_straight_line_scores_its_own_length():
    lat, lon = to_arrays([(0.0, 0.0)] + leg(90, 50))
    route = xc.optimise(lat, lon)
    assert route.km == pytest.approx(50.0, rel=0.01)
    assert not route.closed


def test_dogleg_needs_a_turnpoint():
    """Out 40 km east then 40 km north: 80 km with a turnpoint, 56.6 without."""
    points = [(0.0, 0.0)] + leg(90, 40)
    points += leg(0, 40, start=points[-1])
    lat, lon = to_arrays(points)
    assert xc.optimise(lat, lon, turnpoints=0).km == pytest.approx(56.6, rel=0.02)
    assert xc.optimise(lat, lon, turnpoints=1).km == pytest.approx(80.0, rel=0.02)


def test_more_turnpoints_never_score_less():
    points = [(0.0, 0.0)] + leg(90, 30)
    points += leg(20, 25, start=points[-1])
    points += leg(200, 20, start=points[-1])
    points += leg(120, 28, start=points[-1])
    lat, lon = to_arrays(points)
    scores = [xc.optimise(lat, lon, turnpoints=k).km for k in range(4)]
    assert scores == sorted(scores)


def test_turnpoints_stay_in_time_order():
    points = [(0.0, 0.0)] + leg(90, 30)
    points += leg(180, 25, start=points[-1])
    points += leg(270, 30, start=points[-1])
    lat, lon = to_arrays(points)
    route = xc.optimise(lat, lon)
    indices = [p.index for p in route.points]
    assert indices == sorted(indices)
    assert len(route.points) == 5  # start, three turnpoints, finish


def test_distance_never_exceeds_the_track_flown():
    from tracklog_viewer.geo import cumulative_distance

    points = [(0.0, 0.0)] + leg(90, 20)
    points += leg(45, 20, start=points[-1])
    points += leg(315, 20, start=points[-1])
    lat, lon = to_arrays(points)
    route = xc.optimise(lat, lon)
    assert route.distance <= cumulative_distance(lat, lon)[-1] + 1.0


def test_triangle_is_flagged_closed():
    """Equilateral-ish circuit returning near the start."""
    points = [(0.0, 0.0)] + leg(90, 30)
    points += leg(210, 30, start=points[-1])
    points += leg(330, 30, start=points[-1])
    lat, lon = to_arrays(points)
    route = xc.optimise(lat, lon)
    assert route.closed
    assert route.km == pytest.approx(90.0, rel=0.03)


def test_legs_sum_to_the_total():
    lat, lon = to_arrays([(0.0, 0.0)] + leg(70, 45))
    route = xc.optimise(lat, lon)
    assert sum(route.legs) == pytest.approx(route.distance, rel=1e-6)


def test_large_track_is_sampled_not_exhausted():
    lat, lon = to_arrays([(0.0, 0.0)] + leg(90, 100, steps=20000))
    route = xc.optimise(lat, lon)
    assert route.km == pytest.approx(100.0, rel=0.02)
    assert len(lat) > xc.MAX_SAMPLES  # the sampling path was exercised


class TestShape:
    """XContest's categories: closure under the 20% rule, then FAI's 28% shortest side."""

    def _route(self, corners, *, close=True):
        from tracklog_viewer.xc import Route, Turnpoint

        points = [Turnpoint(index=0, lat=corners[0][0], lon=corners[0][1], time=None)]
        points += [
            Turnpoint(index=i + 1, lat=lat, lon=lon, time=None)
            for i, (lat, lon) in enumerate(corners)
        ]
        if close:
            points.append(points[1])
        else:
            points.append(Turnpoint(index=9, lat=corners[0][0] + 3.0,
                                    lon=corners[0][1], time=None))
        legs = [
            geo.distance(a.lat, a.lon, b.lat, b.lon) for a, b in zip(points, points[1:])
        ]
        return Route(kind="fai_triangle" if close else "free_3tp",
                     distance=sum(legs) or 1.0, points=points, legs=legs, closed=close)

    def test_equilateral_triangle_is_fai(self):
        # Each side a third of the perimeter, comfortably over the 28% floor.
        corners = [(49.0, 14.0), (49.45, 14.0), (49.225, 14.6)]
        assert self._route(corners).shape == "fai"

    def test_one_short_side_is_a_flat_triangle(self):
        # A long thin triangle: shortest side well under 28% but not degenerate.
        corners = [(49.0, 14.0), (49.9, 14.0), (49.95, 14.25)]
        route = self._route(corners)
        sides = route.sides
        assert min(sides) / sum(sides) < 0.28
        assert route.shape == "flat"

    def test_a_closed_there_and_back_is_still_a_flat_triangle(self):
        """Its shortest side is a quarter of the perimeter, not nothing: a + b = c when a
        triangle is flattened onto a line. So no degeneracy test on side ratios can find
        this, and XContest scores it as a flat triangle regardless."""
        corners = [(49.0, 14.0), (49.8, 14.0), (49.4, 14.0)]
        route = self._route(corners)
        assert min(route.sides) / sum(route.sides) == pytest.approx(0.25, abs=0.01)
        assert route.shape == "flat"

    def test_an_unclosed_route_is_open_whatever_its_corners(self):
        corners = [(49.0, 14.0), (49.45, 14.0), (49.225, 14.6)]
        assert self._route(corners, close=False).shape == "open"

    def test_the_open_optimum_never_claims_a_triangle(self):
        """Its distance is the four-leg path from start to finish, not a perimeter. Scoring
        it as a triangle compares two different quantities, and it won every time."""
        from tracklog_viewer.xc import Route, Turnpoint

        corners = [(49.0, 14.0), (49.45, 14.0), (49.225, 14.6)]
        points = [Turnpoint(index=i, lat=lat, lon=lon, time=None)
                  for i, (lat, lon) in enumerate(corners + corners[:2])]
        route = Route(kind="free_3tp", distance=100000.0, points=points,
                      legs=[1.0, 1.0, 1.0, 1.0], closed=True)
        assert route.shape == "open"

    def test_sides_are_the_triangle_not_the_legs(self):
        corners = [(49.0, 14.0), (49.45, 14.0), (49.225, 14.6)]
        route = self._route(corners)
        assert len(route.legs) == 4
        assert len(route.sides) == 3


class TestScoredTriangle:
    """`triangle()` maximises perimeter × multiplier, which is what XContest ranks by."""

    def test_score_prefers_a_shorter_fai_triangle_over_a_longer_flat_one(self):
        """The rule that matters, stated as arithmetic. The real case: a flight whose
        longest triangle is flat at 51.0 km and whose best FAI triangle is 48.6 km.
        XContest reports the FAI one because 48.6 x 1.4 beats 51.0 x 1.2, so maximising
        distance alone gets both the number and the category wrong."""
        from tracklog_viewer.xc import MULTIPLIER

        assert 48.6 * MULTIPLIER["fai"] > 51.0 * MULTIPLIER["flat"]
        assert MULTIPLIER["open"] < MULTIPLIER["flat"] < MULTIPLIER["fai"]

    def test_finds_an_equilateral_loop_and_calls_it_fai(self):
        corners = [(49.0, 14.0), (49.45, 14.0), (49.225, 14.62)]
        lat, lon = [], []
        for a, b in zip(corners + corners[:1], corners[1:] + corners[:1]):
            lat += list(np.linspace(a[0], b[0], 90))
            lon += list(np.linspace(a[1], b[1], 90))
        route = xc.triangle(np.array(lat), np.array(lon), samples=140)
        assert route is not None
        assert route.shape == "fai"
        expected = sum(
            geo.distance(a[0], a[1], b[0], b[1])
            for a, b in zip(corners, corners[1:] + corners[:1])
        )
        # The corners are on the track, so the optimum is the triangle itself.
        assert route.distance == pytest.approx(expected, rel=0.02)

    def test_refuses_a_course_that_does_not_close(self):
        # A straight line out: no closing, so no triangle at any multiplier.
        lat = np.linspace(49.0, 50.0, 300)
        lon = np.full(300, 14.0)
        route = xc.triangle(lat, lon, samples=120)
        assert route is None or route.km < 1.0

    def test_points_close_the_figure_for_the_plan_view(self):
        lat = np.array(list(np.linspace(49.0, 49.4, 80)) + list(np.linspace(49.4, 49.2, 80))
                       + list(np.linspace(49.2, 49.0, 80)))
        lon = np.array(list(np.full(80, 14.0)) + list(np.linspace(14.0, 14.5, 80))
                       + list(np.linspace(14.5, 14.0, 80)))
        route = xc.triangle(lat, lon, samples=120)
        assert route is not None
        assert len(route.points) == 5
        assert route.points[0].index == route.points[-1].index
        assert len(route.sides) == 3

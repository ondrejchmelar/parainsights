"""Free-distance optimisation tests, on routes whose optimum is known by hand."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tracklog_viewer import xc
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

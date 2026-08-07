"""The flight plan, and the two ways it can lie about a flight.

Both failure modes here were found by running the module over the real archive rather
than by imagining them, and each would have produced a confidently wrong sentence:

- **A declared task the flight never went near.** Of the ten sample files carrying `C`
  records, the two with a real task have turnpoints 29 km and 432 km from anywhere the
  glider flew — tasks left loaded in XCTrack from another site, which the logger writes
  out because that is what is loaded. Scored, they read "the flight turned 478 km short".
- **A turnpoint scored out of order.** An out-and-return whose far turnpoint was missed
  still "reaches" its finish, because the finish is back where the launch was. A 51.4 km
  plan reported 51.4 km flown on a flight that turned 12 km short.
"""

import json
import math

import pytest

from tracklog_viewer import plan as plan_module
from tracklog_viewer.analysis import analyse
from tracklog_viewer.igc import Turnpoint, parse

from .test_analysis import LAT0, LON0, build, straight, to_latlon


def flight_at(tmp_path, points, name="p.igc"):
    return parse(build(tmp_path / name, points))


def east(metres):
    """A waypoint `metres` east of the fixture's origin."""
    lat, lon = to_latlon(metres, 0.0)
    return plan_module.Waypoint(f"E{metres:.0f}", lat, lon, radius=500.0)


class TestDeclaredTask:
    def test_a_launch_and_landing_pair_is_not_a_task(self, tmp_path):
        """What XCTrack writes when the pilot declared nothing at all."""
        flight = flight_at(tmp_path, straight(400, speed=12.0))
        flight.task = [Turnpoint("TAKEOFF", LAT0, LON0),
                       Turnpoint("LANDING", LAT0, LON0)]
        assert plan_module.from_flight(flight) is None

    def test_a_task_from_another_day_is_refused(self, tmp_path):
        """The measured state of the archive, not a hypothetical."""
        flight = flight_at(tmp_path, straight(400, speed=12.0))
        far_lat, far_lon = to_latlon(400_000.0, 0.0)
        flight.task = [
            Turnpoint("TAKEOFF", LAT0, LON0),
            Turnpoint("START", far_lat, far_lon),
            Turnpoint("FINISH", far_lat, far_lon),
        ]
        assert plan_module.from_flight(flight) is None

    def test_a_task_the_flight_flew_is_accepted(self, tmp_path):
        points = straight(600, speed=12.0, heading=90.0)
        flight = flight_at(tmp_path, points)
        near_lat, near_lon = to_latlon(3000.0, 0.0)
        flight.task = [
            Turnpoint("TAKEOFF", LAT0, LON0),
            Turnpoint("TP1", near_lat, near_lon),
            Turnpoint("FINISH", near_lat, near_lon),
        ]
        answer = plan_module.from_flight(flight)
        assert answer is not None
        assert answer.source == "declared"
        assert not answer.reconstructed, "a C record was written before takeoff"


class TestAdherence:
    def _flight(self, tmp_path, metres=4000.0):
        """A glider flying due east for `metres`, so where it got to is known exactly."""
        return analyse(flight_at(
            tmp_path, straight(int(metres / 12), speed=12.0, heading=90.0)
        ))

    def test_turnpoints_are_taken_in_order(self, tmp_path):
        """Missing one ends the task, however near the later ones happen to be.

        The finish here sits back at the launch — an out and return — so without the
        ordering rule it scores from the first fix and the plan reads as complete.
        """
        analysis = self._flight(tmp_path, 4000.0)
        plan = plan_module.Plan([
            plan_module.Waypoint("Launch", LAT0, LON0, radius=500.0),
            east(2000.0),
            east(40_000.0),                        # never reached
            plan_module.Waypoint("Home", LAT0, LON0, radius=500.0),
        ], made_at="2026-08-07T09:00:00Z")
        answer = plan_module.compare(analysis, plan)
        states = [r.index is not None for r in answer.reached]
        assert states == [True, True, False, False]
        assert not answer.completed
        assert answer.shortfall > 0

    def test_a_completed_task_reports_no_shortfall(self, tmp_path):
        analysis = self._flight(tmp_path, 6000.0)
        plan = plan_module.Plan([
            plan_module.Waypoint("Launch", LAT0, LON0, radius=500.0),
            east(2000.0),
            east(4000.0),
        ], made_at="2026-08-07T09:00:00Z")
        answer = plan_module.compare(analysis, plan)
        assert answer.completed
        assert answer.shortfall == pytest.approx(0.0, abs=1.0)

    def test_the_departure_point_needs_a_sustained_departure(self, tmp_path):
        """A glide around a shower is not abandoning the plan.

        The fixture flies due east while the plan runs due north, so it is off the line
        from the first minute and stays off — which is what a real departure looks like.
        """
        analysis = self._flight(tmp_path, 12_000.0)
        north_lat, north_lon = to_latlon(0.0, 20_000.0)
        plan = plan_module.Plan([
            plan_module.Waypoint("Launch", LAT0, LON0, radius=500.0),
            plan_module.Waypoint("North", north_lat, north_lon, radius=500.0),
            plan_module.Waypoint("Far", north_lat, north_lon, radius=500.0),
        ], made_at="2026-08-07T09:00:00Z")
        answer = plan_module.compare(analysis, plan)
        assert answer.departure_index is not None
        assert answer.departure_distance > plan_module.DEPARTURE

    def test_a_flight_that_follows_the_line_never_departs(self, tmp_path):
        analysis = self._flight(tmp_path, 12_000.0)
        plan = plan_module.Plan([
            plan_module.Waypoint("Launch", LAT0, LON0, radius=500.0),
            east(6000.0),
            east(12_000.0),
        ], made_at="2026-08-07T09:00:00Z")
        answer = plan_module.compare(analysis, plan)
        assert answer.departure_index is None


class TestProvenance:
    def test_a_plan_with_no_timestamp_is_reconstructed_intent(self):
        """Without this the feature quietly becomes a tool for justifying whatever
        happened."""
        after = plan_module.Plan([], source="sidecar")
        assert after.reconstructed
        before = plan_module.Plan([], made_at="2026-08-07T09:00:00Z", source="sidecar")
        assert not before.reconstructed

    def test_a_declared_task_is_never_reconstructed(self):
        """A `C` record is in the tracklog, so it was written before the flight."""
        assert not plan_module.Plan([], source="declared").reconstructed

    def test_a_sidecar_round_trips(self, tmp_path):
        original = plan_module.Plan(
            [plan_module.Waypoint("A", 46.5, 11.7, 1000.0),
             plan_module.Waypoint("B", 46.3, 11.6, 2000.0)],
            made_at="2026-08-07T09:00:00Z", notes="down the ridge", source="sidecar",
        )
        path = tmp_path / "f.plan.json"
        path.write_text(json.dumps(original.to_dict()), encoding="utf-8")
        again = plan_module.load(path)
        assert again.made_at == original.made_at
        assert again.notes == original.notes
        assert [w.radius for w in again.turnpoints] == [1000.0, 2000.0]
        assert again.distance == pytest.approx(original.distance, rel=1e-9)

    def test_a_sidecar_is_found_beside_the_tracklog(self, tmp_path):
        track = tmp_path / "2026-08-07.igc"
        track.write_text("A", encoding="utf-8")
        assert plan_module.discover(track) is None
        (tmp_path / "2026-08-07.plan.json").write_text("{}", encoding="utf-8")
        assert plan_module.discover(track) is not None


def test_the_planned_distance_is_the_line_not_the_track():
    plan = plan_module.Plan([
        plan_module.Waypoint("A", 46.0, 11.0),
        plan_module.Waypoint("B", 46.0, 11.5),
        plan_module.Waypoint("C", 46.0, 11.0),
    ])
    one_leg = plan.distance / 2
    # Two legs there and back, so the total is twice one of them.
    assert plan.distance == pytest.approx(2 * one_leg)
    assert one_leg == pytest.approx(
        math.radians(0.5) * 6371000 * math.cos(math.radians(46.0)), rel=0.01
    )

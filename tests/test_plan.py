"""The flight plan: the reference frame the debrief is missing.

The behaviour worth pinning is not that a plan produces findings — it is the honesty
machinery around it. A plan with no timestamp is a story about the flight rather than a
plan, and everything derived from it has to say so; a two-point "task" is a line rather
than an intent and must be refused; and no plan at all has to leave the debrief exactly
as it was.
"""

import json

import pytest

from tests.test_analysis import build, circling, straight, to_latlon
from tracklog_viewer import igc, plan
from tracklog_viewer.analysis import analyse
from tracklog_viewer.igc import Turnpoint


def with_task(path, points, task):
    """Write a synthetic IGC carrying `C` task records, as 10 of the 50 samples do."""
    build(path, points)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = [f"C010726120000000000{len(task):02d}01Task"]
    for point in task:
        lat, lon = point.lat, point.lon
        lat_deg, lon_deg = int(abs(lat)), int(abs(lon))
        lat_min = round((abs(lat) - lat_deg) * 60000)
        lon_min = round((abs(lon) - lon_deg) * 60000)
        header.append(
            f"C{lat_deg:02d}{lat_min:05d}N{lon_deg:03d}{lon_min:05d}E{point.name}"
        )
    # C records go with the headers, before the B records.
    at = next(i for i, line in enumerate(lines) if line.startswith("B"))
    path.write_text("\n".join(lines[:at] + header + lines[at:]) + "\n", encoding="utf-8")
    return path


def a_flight(tmp_path, name="p.igc"):
    """A flight running east, so a plan running north is unmistakably departed from."""
    points = straight(1200, speed=12.0, climb=-0.4, alt0=3000.0, heading=90.0)
    return analyse(igc.parse(build(tmp_path / name, points)))


class TestSources:
    def test_a_declared_task_is_read_from_the_tracklog(self, tmp_path):
        """Before this, `.task` was parsed and the only reference in the tree was the
        constructor: it was carried through `sources.py` and never read again."""
        task = [Turnpoint("START", *to_latlon(0, 0)),
                Turnpoint("TP1", *to_latlon(0, 20000)),
                Turnpoint("FINISH", *to_latlon(0, 0))]
        path = with_task(tmp_path / "task.igc",
                         straight(600, speed=12.0, climb=-0.5, alt0=3000.0), task)
        flight = igc.parse(path)

        assert len(flight.task) == 3, "the C records did not parse"
        found = plan.from_flight(flight)
        assert found is not None
        assert found.declared
        assert found.source == "task"

    def test_a_two_point_task_is_not_an_intent(self, tmp_path):
        """Most XCTrack files carry only the takeoff/landing pair. Two points is a line."""
        task = [Turnpoint("TAKEOFF", *to_latlon(0, 0)),
                Turnpoint("LANDING", *to_latlon(0, 5000))]
        path = with_task(tmp_path / "pair.igc",
                         straight(600, speed=12.0, climb=-0.5, alt0=3000.0), task)
        assert plan.from_flight(igc.parse(path)) is None

    def test_a_task_from_the_file_is_reconstructed_intent(self, tmp_path):
        """The parser does not keep the C header's declaration date, and inferring one
        from the flight's own date is exactly the self-justifying move `made_at` exists
        to prevent."""
        task = [Turnpoint("A", *to_latlon(0, 0)), Turnpoint("B", *to_latlon(0, 20000)),
                Turnpoint("C", *to_latlon(0, 0))]
        path = with_task(tmp_path / "recon.igc",
                         straight(600, speed=12.0, climb=-0.5, alt0=3000.0), task)
        found = plan.from_flight(igc.parse(path))
        assert found.reconstructed

    def test_a_sidecar_is_loaded_and_can_be_timestamped(self, tmp_path):
        sidecar = tmp_path / "f.plan.json"
        sidecar.write_text(json.dumps({
            "made_at": "2026-07-01T08:30:00",
            "goal_distance": 100000,
            "turnpoints": [
                {"name": "start", "lat": 49.0, "lon": 14.0},
                {"name": "goal", "lat": 49.5, "lon": 14.0},
                {"name": "home", "lat": 49.0, "lon": 14.0},
            ],
        }), encoding="utf-8")
        found = plan.load(sidecar)

        assert found is not None
        assert not found.reconstructed, "a timestamped plan is a plan"
        assert found.goal_distance == 100000
        assert found.declared

    def test_a_broken_sidecar_is_not_fatal(self, tmp_path):
        bad = tmp_path / "bad.plan.json"
        bad.write_text("{not json", encoding="utf-8")
        assert plan.load(bad) is None

    def test_a_sidecar_beside_the_track_is_discovered(self, tmp_path):
        track = tmp_path / "flight.igc"
        track.write_text("x", encoding="utf-8")
        (tmp_path / "flight.plan.json").write_text("{}", encoding="utf-8")
        assert plan.discover(track) is not None

    def test_nothing_to_discover_is_not_an_error(self, tmp_path):
        track = tmp_path / "lonely.igc"
        track.write_text("x", encoding="utf-8")
        assert plan.discover(track, remembered=tmp_path / "nope") is None


class TestAdherence:
    def _plan(self, *, goal=None):
        return plan.Plan(
            made_at="2026-07-01T08:00:00",
            turnpoints=[Turnpoint("start", *to_latlon(0, 0)),
                        Turnpoint("north", *to_latlon(0, 40000))],
            goal_distance=goal,
        )

    def test_a_flight_that_leaves_the_line_reports_a_decision_point(self, tmp_path):
        followed = plan.adherence(a_flight(tmp_path), self._plan())

        assert followed is not None
        assert followed.departed_index is not None
        assert followed.departed_at is not None
        assert followed.max_off > plan.DEPARTURE_METRES

    def test_a_flight_along_the_line_never_departs(self, tmp_path):
        """Flying the plan is not a finding."""
        points = straight(1200, speed=12.0, climb=-0.4, alt0=3000.0, heading=0.0)
        analysis = analyse(igc.parse(build(tmp_path / "on.igc", points)))
        followed = plan.adherence(analysis, self._plan())

        assert followed is not None
        assert followed.departed_index is None
        assert followed.median_off < plan.DEPARTURE_METRES

    def test_a_brief_excursion_is_not_a_decision(self, tmp_path):
        """A thermal drifts a kilometre off course without anyone deciding anything, so
        the departure has to be sustained."""
        points = straight(200, speed=12.0, climb=-0.4, alt0=3000.0, heading=0.0)
        points += straight(60, speed=12.0, climb=-0.4, t0=201, alt0=points[-1][3],
                           x0=points[-1][1], y0=points[-1][2], heading=90.0)
        points += straight(400, speed=12.0, climb=-0.4, t0=262, alt0=points[-1][3],
                           x0=points[-1][1], y0=points[-1][2], heading=0.0)
        analysis = analyse(igc.parse(build(tmp_path / "brief.igc", points)))
        followed = plan.adherence(analysis, self._plan())

        assert followed is not None
        assert followed.departed_index is None, "a 60 s excursion is not a decision"

    def test_no_plan_means_no_adherence(self, tmp_path):
        assert plan.adherence(a_flight(tmp_path), None) is None


class TestTurnpoints:
    def test_reached_turnpoints_are_counted_in_order(self, tmp_path):
        """A turnpoint clipped after skipping the one before it has not been reached in
        any sense that scores."""
        points = straight(2000, speed=12.0, climb=-0.3, alt0=3000.0, heading=90.0)
        analysis = analyse(igc.parse(build(tmp_path / "tp.igc", points)))
        task = plan.Plan(
            made_at="2026-07-01T08:00:00",
            turnpoints=[Turnpoint("a", *to_latlon(0, 0)),
                        Turnpoint("b", *to_latlon(12000, 0)),
                        Turnpoint("far", *to_latlon(0, 90000))],
        )
        marks = plan.turnpoints(analysis, task)

        assert marks is not None
        assert marks.total == 3
        assert marks.reached == 2
        assert marks.first_missed == "far"


class TestBudget:
    class Route:
        distance = 40000.0

    def test_planned_against_scored(self, tmp_path):
        task = plan.Plan(made_at="2026-07-01T08:00:00", goal_distance=100000.0,
                         turnpoints=[Turnpoint("a", 49.0, 14.0),
                                     Turnpoint("b", 49.5, 14.0),
                                     Turnpoint("c", 49.0, 14.0)])
        held = plan.budget(a_flight(tmp_path), task, self.Route())

        assert held is not None
        assert held.planned_km == 100.0
        assert held.short_km == pytest.approx(60.0, abs=0.1)

    def test_no_route_means_no_budget(self, tmp_path):
        task = plan.Plan(made_at="x", goal_distance=100000.0)
        assert plan.budget(a_flight(tmp_path), task, None) is None


class TestDebriefIntegration:
    def test_no_plan_leaves_the_debrief_unchanged(self, tmp_path):
        """Degrade, never blank — the same rule meteo and terrain already follow."""
        from tracklog_viewer import debrief

        analysis = a_flight(tmp_path, "nodebrief.igc")
        result = debrief.build(analysis)

        assert "plan" in result.suppressed
        assert not any(f.id.startswith("plan-") for f in result.findings)

    def test_a_plan_adds_a_departure_finding(self, tmp_path):
        from tracklog_viewer import debrief

        analysis = a_flight(tmp_path, "withplan.igc")
        task = plan.Plan(
            made_at="2026-07-01T08:00:00",
            turnpoints=[Turnpoint("start", *to_latlon(0, 0)),
                        Turnpoint("north", *to_latlon(0, 40000))],
            goal_distance=80000.0,
        )
        card = debrief._plan_departure(analysis, task)

        assert card is not None
        assert card.cursor is not None, "the card has to be able to say 'show me'"
        assert card.confidence == 1.0

    def test_a_reconstructed_plan_downgrades_its_findings(self, tmp_path):
        """Without this the feature quietly becomes a tool for justifying whatever
        happened."""
        from tracklog_viewer import debrief

        analysis = a_flight(tmp_path, "recon2.igc")
        task = plan.Plan(
            made_at=None,
            turnpoints=[Turnpoint("start", *to_latlon(0, 0)),
                        Turnpoint("north", *to_latlon(0, 40000))],
            goal_distance=80000.0,
        )
        card = debrief._plan_departure(analysis, task)

        assert card is not None
        assert card.confidence < 1.0
        assert "reconstructed intent" in card.sentence

    def test_plan_findings_give_no_advice_either(self, tmp_path):
        from tests.test_debrief import TestVoice
        from tracklog_viewer import debrief

        analysis = a_flight(tmp_path, "voice2.igc")
        task = plan.Plan(
            made_at="2026-07-01T08:00:00",
            turnpoints=[Turnpoint("start", *to_latlon(0, 0)),
                        Turnpoint("north", *to_latlon(0, 40000))],
            goal_distance=80000.0,
        )
        card = debrief._plan_departure(analysis, task)
        text = f"{card.title} {card.sentence}".lower()
        for phrase in TestVoice.FORBIDDEN:
            assert phrase not in text, f"plan finding gives advice: {text!r}"

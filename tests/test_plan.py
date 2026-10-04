"""The flight plan: the reference frame the debrief is missing.

The behaviour worth pinning is not that a plan produces findings — it is the honesty
machinery around it. A plan with no timestamp is a story about the flight rather than a
plan, and everything derived from it has to say so; a two-point "task" is a line rather
than an intent and must be refused; and no plan at all has to leave the debrief exactly
as it was. (Finding a sidecar plan on disk is the CLI's job: `tests/test_cli.py`.)
"""

import pytest

from tests import js
from tests.js import needs_node
from tests.test_analysis import build, straight, to_latlon
from tests.test_debrief import TestVoice

pytestmark = needs_node

DEPARTURE_METRES = 1500.0 if not __import__("shutil").which("node") else \
    js.run("return TV.plan.DEPARTURE_METRES;")


def tp(name, x, y):
    lat, lon = to_latlon(x, y)
    return {"name": name, "lat": lat, "lon": lon}


def with_task(path, points, task):
    """Write a synthetic IGC carrying `C` task records, as 10 of the 50 samples do."""
    build(path, points)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = [f"C010726120000000000{len(task):02d}01Task"]
    for point in task:
        lat, lon = point["lat"], point["lon"]
        lat_deg, lon_deg = int(abs(lat)), int(abs(lon))
        lat_min = round((abs(lat) - lat_deg) * 60000)
        lon_min = round((abs(lon) - lon_deg) * 60000)
        header.append(f"C{lat_deg:02d}{lat_min:05d}N{lon_deg:03d}{lon_min:05d}E{point['name']}")
    # C records go with the headers, before the B records.
    at = next(i for i, line in enumerate(lines) if line.startswith("B"))
    path.write_text("\n".join(lines[:at] + header + lines[at:]) + "\n", encoding="utf-8")
    return path


def a_flight(tmp_path, name="p.igc"):
    """A flight running east, so a plan running north is unmistakably departed from."""
    return build(tmp_path / name, straight(1200, speed=12.0, climb=-0.4, alt0=3000.0, heading=90.0))


def a_plan(turnpoints, *, made_at="2026-07-01T08:00:00", goal=None):
    return {"made_at": made_at, "turnpoints": turnpoints, "goal_distance": goal}


def ask(path, code, **inputs):
    """`code` with the file's analysis as `a` and `input.plan` read as a sidecar plan."""
    return js.run("""
      var a = TV.analysis.analyse(await load(input.path));
      var plan = input.plan ? TV.plan.fromJson(input.plan) : null;
      if (plan && input.plan.made_at === null) plan.made_at = null;
      """ + code, path=path, **inputs)


NORTH = [tp("start", 0, 0), tp("north", 0, 40000)]


class TestSources:
    def test_a_declared_task_is_read_from_the_tracklog(self, tmp_path):
        task = [tp("START", 0, 0), tp("TP1", 0, 20000), tp("FINISH", 0, 0)]
        path = with_task(tmp_path / "task.igc", straight(600, speed=12.0, climb=-0.5, alt0=3000.0), task)
        out = js.run("""var f = await load(input.path), p = TV.plan.fromFlight(f);
                        return { task: f.task.length, plan: p, declared: p && TV.plan.declared(p) };""",
                     path=path)
        assert out.task == 3, "the C records did not parse"
        assert out.plan is not None
        assert out.declared
        assert out.plan.source == "task"

    def test_a_two_point_task_is_not_an_intent(self, tmp_path):
        """Most XCTrack files carry only the takeoff/landing pair. Two points is a line."""
        task = [tp("TAKEOFF", 0, 0), tp("LANDING", 0, 5000)]
        path = with_task(tmp_path / "pair.igc", straight(600, speed=12.0, climb=-0.5, alt0=3000.0), task)
        assert js.run("return TV.plan.fromFlight(await load(input.path));", path=path) is None

    def test_a_task_from_the_file_is_reconstructed_intent(self, tmp_path):
        """The parser does not keep the C header's declaration date, and inferring one
        from the flight's own date is exactly the self-justifying move `made_at` exists
        to prevent."""
        task = [tp("A", 0, 0), tp("B", 0, 20000), tp("C", 0, 0)]
        path = with_task(tmp_path / "recon.igc", straight(600, speed=12.0, climb=-0.5, alt0=3000.0), task)
        assert js.run("return TV.plan.reconstructed(TV.plan.fromFlight(await load(input.path)));",
                      path=path) is True

    def test_a_sidecar_can_be_timestamped(self):
        found = js.run("""var p = TV.plan.fromJson(input.plan);
                          return { plan: p, reconstructed: TV.plan.reconstructed(p), declared: TV.plan.declared(p) };""",
                       plan={"made_at": "2026-07-01T08:30:00", "goal_distance": 100000,
                             "turnpoints": [{"name": "start", "lat": 49.0, "lon": 14.0},
                                            {"name": "goal", "lat": 49.5, "lon": 14.0},
                                            {"name": "home", "lat": 49.0, "lon": 14.0}]})
        assert found.reconstructed is False, "a timestamped plan is a plan"
        assert found.plan.goal_distance == 100000
        assert found.declared

    def test_a_sidecar_that_is_not_an_object_is_no_plan(self):
        assert js.run("return TV.plan.fromJson(input.plan);", plan=[1, 2]) is None


class TestAdherence:
    def test_a_flight_that_leaves_the_line_reports_a_decision_point(self, tmp_path):
        followed = ask(a_flight(tmp_path), "return TV.plan.adherence(a, plan);", plan=a_plan(NORTH))
        assert followed is not None
        assert followed.departed_index is not None
        assert followed.departed_at is not None
        assert followed.max_off > DEPARTURE_METRES

    def test_a_flight_along_the_line_never_departs(self, tmp_path):
        """Flying the plan is not a finding."""
        path = build(tmp_path / "on.igc", straight(1200, speed=12.0, climb=-0.4, alt0=3000.0, heading=0.0))
        followed = ask(path, "return TV.plan.adherence(a, plan);", plan=a_plan(NORTH))
        assert followed is not None
        assert followed.departed_index is None
        assert followed.median_off < DEPARTURE_METRES

    def test_a_brief_excursion_is_not_a_decision(self, tmp_path):
        """A thermal drifts a kilometre off course without anyone deciding anything, so
        the departure has to be sustained."""
        points = straight(200, speed=12.0, climb=-0.4, alt0=3000.0, heading=0.0)
        points += straight(60, speed=12.0, climb=-0.4, t0=201, alt0=points[-1][3],
                           x0=points[-1][1], y0=points[-1][2], heading=90.0)
        points += straight(400, speed=12.0, climb=-0.4, t0=262, alt0=points[-1][3],
                           x0=points[-1][1], y0=points[-1][2], heading=0.0)
        followed = ask(build(tmp_path / "brief.igc", points), "return TV.plan.adherence(a, plan);",
                       plan=a_plan(NORTH))
        assert followed is not None
        assert followed.departed_index is None, "a 60 s excursion is not a decision"

    def test_no_plan_means_no_adherence(self, tmp_path):
        assert ask(a_flight(tmp_path), "return TV.plan.adherence(a, null);") is None

    def test_a_plan_from_somewhere_else_is_not_this_flight_plan(self, tmp_path):
        """The failure this gate exists for, and it was live on real files.

        Ten of the fifty sample tracklogs carry `C` records; the two carrying a real
        task declare turnpoints 29 km and 432 km from anywhere the glider went — tasks
        left loaded in XCTrack from another site, which the logger writes out because
        that is what is loaded. Compared against, `2021-07-06-XCT-ROP-01` produced the
        loudest card on its own report: *"cost 33 525 m — the track left the planned
        line at 13:31:08"*, with a median distance from the line of 18 812 m.

        A stale plan is worse than no plan: it does not shade a finding slightly wrong,
        it invents the most confident one on the page.
        """
        out = ask(a_flight(tmp_path), """
          return { describes: TV.plan.describes(a, plan), adherence: TV.plan.adherence(a, plan),
                   turnpoints: TV.plan.turnpoints(a, plan), budget: TV.plan.budget(a, plan, null) };""",
                  plan=a_plan([tp("far", 0, 400_000), tp("farther", 0, 440_000)]))
        assert out.describes is False
        assert out.adherence is None and out.turnpoints is None and out.budget is None

    def test_a_plan_this_flight_abandoned_keeps_its_findings(self, tmp_path):
        """The case the gate must not swallow: a flight that flew most of a task and then
        bailed still sits near the line for most of its length — which is why the test is
        the *median* cross-track error and not the closest approach or the maximum."""
        out = ask(a_flight(tmp_path), """
          return { describes: TV.plan.describes(a, plan), adherence: TV.plan.adherence(a, plan) };""",
                  plan=a_plan([tp("start", 0, 0), tp("east", 60_000, 0)]))
        assert out.describes is True
        assert out.adherence is not None


class TestTurnpoints:
    def test_reached_turnpoints_are_counted_in_order(self, tmp_path):
        """A turnpoint clipped after skipping the one before it has not been reached in
        any sense that scores."""
        path = build(tmp_path / "tp.igc", straight(2000, speed=12.0, climb=-0.3, alt0=3000.0, heading=90.0))
        marks = ask(path, "return TV.plan.turnpoints(a, plan);",
                    plan=a_plan([tp("a", 0, 0), tp("b", 12000, 0), tp("far", 0, 90000)]))
        assert marks is not None
        assert marks.total == 3
        assert marks.reached == 2
        assert marks.first_missed == "far"


class TestBudget:
    def test_planned_against_scored(self, tmp_path):
        held = ask(a_flight(tmp_path), "return TV.plan.budget(a, plan, { distance: 40000.0 });",
                   plan=a_plan([{"name": "a", "lat": 49.0, "lon": 14.0},
                                {"name": "b", "lat": 49.5, "lon": 14.0},
                                {"name": "c", "lat": 49.0, "lon": 14.0}], goal=100000.0))
        assert held is not None
        assert held.planned_km == 100.0
        assert held.short_km == pytest.approx(60.0, abs=0.1)

    def test_no_route_means_no_budget(self, tmp_path):
        assert ask(a_flight(tmp_path), "return TV.plan.budget(a, plan, null);",
                   plan=a_plan([], made_at="x", goal=100000.0)) is None


class TestDebriefIntegration:
    def test_no_plan_leaves_the_debrief_unchanged(self, tmp_path):
        """Degrade, never blank — the same rule meteo and terrain already follow."""
        result = ask(a_flight(tmp_path, "nodebrief.igc"),
                     "return TV.debrief.toDict(TV.debrief.build(a, {}));")
        assert "plan" in result.suppressed
        assert not any(f.id.startswith("plan-") for f in result.findings)

    def _departure(self, tmp_path, name, made_at):
        return ask(a_flight(tmp_path, name), "return TV.debrief.parts.planDeparture(a, plan);",
                   plan=a_plan(NORTH, made_at=made_at, goal=80000.0))

    def test_a_plan_adds_a_departure_finding(self, tmp_path):
        card = self._departure(tmp_path, "withplan.igc", "2026-07-01T08:00:00")
        assert card is not None
        assert card.cursor is not None, "the card has to be able to say 'show me'"
        assert card.confidence == 1.0

    def test_a_reconstructed_plan_downgrades_its_findings(self, tmp_path):
        """Without this the feature quietly becomes a tool for justifying whatever
        happened."""
        card = self._departure(tmp_path, "recon2.igc", None)
        assert card is not None
        assert card.confidence < 1.0
        assert "reconstructed intent" in card.sentence

    def test_plan_findings_give_no_advice_either(self, tmp_path):
        card = self._departure(tmp_path, "voice2.igc", "2026-07-01T08:00:00")
        text = f"{card.title} {card.sentence}".lower()
        for phrase in TestVoice.FORBIDDEN:
            assert phrase not in text, f"plan finding gives advice: {text!r}"

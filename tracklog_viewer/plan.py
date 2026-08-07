"""The flight plan, and the flight measured against it.

**The single most valuable input this tool does not have is the pilot's intent.** Every
other measurement works around its absence, and the debrief's central rule — *a finding
is a measurement plus a link, never an imperative* — exists because the tool cannot see
the sky, the gaggle, the airspace or the pilot's plan. Three of those four are genuinely
out of reach. The fourth is not: the pilot can simply say what the plan was, and then the
comparison is against something they themselves signed.

That converts a family of forbidden sentences into legitimate ones without touching the
no-imperatives rule:

    ✗ "You should have pushed on to Predazzo."
    ✓ "The plan was Predazzo and back, 100 km. The flight turned 31 km short, at 14:10,
       from 2 350 m — the first point where the track leaves the planned line by more
       than 3 km."

Still past tense, still two measurements and a link, and now about the pilot's own stated
intention rather than about an ideal flight nobody declared.

**This is the cheapest possible first version, and it throws nothing away that was not
already parsed.** Ten of the fifty sample IGCs carry `C` task records — most the minimal
takeoff/landing pair XCTrack writes, but `2020-08-16-XCT-ROP-01.igc` carries a full
12-point competition task with names. `igc.py` parses all of it into `Flight.task`, and
before this module the only reference to `.task` in the whole tree was the constructor.

Two rules that keep it honest:

- **A plan is timestamped and frozen at takeoff.** `made_at` is recorded; without one the
  comparison is labelled *reconstructed intent* and its findings are downgraded, because
  a plan written after landing is a story about the flight rather than a plan. Without
  this the feature quietly becomes a tool for justifying whatever happened.
- **No plan means today's debrief, unchanged.** Degrade, never blank — the same rule the
  meteo and terrain findings already follow.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import geo
from .analysis import Analysis

# A declared task whose turnpoints are only the launch and the landing is not a task —
# it is what XCTrack writes when the pilot declared nothing. Scoring against it would
# state, with a straight face, that the pilot planned to fly from where they took off to
# where they landed.
MIN_TURNPOINTS = 3
# How far off the planned line counts as leaving it. A thermal drifts a kilometre and a
# course line is flown as a series of glides between climbs, so anything tighter marks
# every normal flight as a departure.
DEPARTURE = 3000.0        # metres
# …and for how long. One glide around a shower is not abandoning the plan.
DEPARTURE_SECONDS = 300.0
# How near the flight has to come to the task before the task is believed to be *this*
# flight's task. This gate is not defensive programming, it is the measured state of the
# archive: of the ten sample files carrying `C` records, the two with a real task have
# turnpoints **29 km and 432 km** from anywhere the glider went. They are tasks left
# loaded in XCTrack from another site and another day, and the logger writes whatever is
# loaded. Scoring against one produces "the flight turned 478 km short of goal", stated
# with a straight face — which is exactly the confidently wrong sentence the whole
# debrief is built to avoid. A declared task the flight never approached is not a plan;
# it is a leftover, and it is refused.
STALE_LIMIT = 10_000.0    # metres


@dataclass
class Waypoint:
    name: str
    lat: float
    lon: float
    radius: float = 400.0     # metres; the default cylinder a task uses when unstated


@dataclass
class Plan:
    """What the pilot meant to do. Every field optional; the object may be nearly empty.

    `source` says where it came from, because that is what a reader needs to judge it:
    a task read out of the tracklog's own `C` records was declared before takeoff by
    construction, and one typed afterwards was not.
    """

    turnpoints: list[Waypoint] = field(default_factory=list)
    made_at: str | None = None          # None ⇒ reconstructed, findings downgraded
    goal_distance: float | None = None  # metres
    planned_start: str | None = None
    planned_turn: str | None = None
    planned_finish: str | None = None
    min_clearance: float | None = None
    notes: str | None = None
    source: str = "declared"

    @property
    def reconstructed(self) -> bool:
        return self.made_at is None and self.source != "declared"

    @property
    def distance(self) -> float:
        """The planned line's length, turnpoint to turnpoint."""
        return sum(
            float(geo.distance(a.lat, a.lon, b.lat, b.lon))
            for a, b in zip(self.turnpoints, self.turnpoints[1:])
        )

    def to_dict(self) -> dict:
        return {
            "turnpoints": [
                {"name": w.name, "lat": w.lat, "lon": w.lon, "radius": w.radius}
                for w in self.turnpoints
            ],
            "made_at": self.made_at,
            "goal_distance": self.goal_distance,
            "planned_start": self.planned_start,
            "planned_turn": self.planned_turn,
            "planned_finish": self.planned_finish,
            "min_clearance": self.min_clearance,
            "notes": self.notes,
            "source": self.source,
        }


def from_flight(flight) -> Plan | None:
    """The task the logger recorded, if the pilot declared one worth the name.

    A declared task is the one plan that needs no storage question answered: it is in the
    tracklog, it was written before the flight, and it is already parsed. Two tests it
    has to pass first — enough turnpoints to be a task at all, and near enough to the
    flight to be *this* flight's task. See `MIN_TURNPOINTS` and `STALE_LIMIT`; both were
    written after looking at what the archive actually contains.
    """
    points = [
        Waypoint(tp.name or f"TP{index}", tp.lat, tp.lon)
        for index, tp in enumerate(flight.task)
    ]
    if len(points) < MIN_TURNPOINTS:
        return None
    # The first turnpoint that is not the launch: the launch always matches, because the
    # logger wrote it from the same fix the flight starts at.
    for point in points[1:]:
        closest = float(np.min(geo.distance(point.lat, point.lon, flight.lat, flight.lon)))
        if closest > STALE_LIMIT:
            return None
        break
    plan = Plan(points, source="declared")
    plan.goal_distance = plan.distance
    return plan


def load(path) -> Plan:
    """A sidecar plan: plain JSON, hand-editable, diffable.

    What a pre-flight run would write, and what an in-page plan exports to.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    points = [
        Waypoint(w.get("name", ""), float(w["lat"]), float(w["lon"]),
                 float(w.get("radius", 400.0)))
        for w in data.get("turnpoints", [])
    ]
    return Plan(
        turnpoints=points,
        made_at=data.get("made_at"),
        goal_distance=data.get("goal_distance"),
        planned_start=data.get("planned_start"),
        planned_turn=data.get("planned_turn"),
        planned_finish=data.get("planned_finish"),
        min_clearance=data.get("min_clearance"),
        notes=data.get("notes"),
        source=data.get("source", "sidecar"),
    )


def discover(track_path) -> Path | None:
    """`FLIGHT.plan.json` beside the tracklog, which is where a plan naturally lands."""
    path = Path(track_path)
    for candidate in (path.with_suffix(".plan.json"),
                      path.parent / f"{path.stem}.plan.json"):
        if candidate.exists():
            return candidate
    return None


@dataclass
class Reached:
    """One turnpoint, and whether the flight got to it."""

    ordinal: int            # position in the task, which is what identifies it
    name: str
    index: int | None       # fix index it was reached at, None if it never was
    time: str | None
    distance: float         # metres, closest the flight ever came


@dataclass
class Adherence:
    """The flight measured against the plan."""

    plan: Plan
    reached: list[Reached] = field(default_factory=list)
    planned_km: float = 0.0
    flown_km: float = 0.0             # along the planned line, as far as it got
    departure_index: int | None = None
    departure_time: str | None = None
    departure_distance: float | None = None   # how far off the line at that point
    shortfall: float | None = None            # metres of the plan not flown

    @property
    def completed(self) -> bool:
        return all(r.index is not None for r in self.reached)

    @property
    def last_reached(self) -> Reached | None:
        got = [r for r in self.reached if r.index is not None]
        return got[-1] if got else None


def _cross_track(plan: Plan, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Distance from each fix to the nearest point on the planned line.

    Legs are short enough relative to the earth that a local plane is exact to well under
    the DEM's own resolution, and the point-to-segment distance there is ordinary
    algebra. Doing it on the sphere would be more correct and no more accurate.
    """
    points = plan.turnpoints
    lat0 = float(np.mean([w.lat for w in points]))
    scale = np.cos(np.radians(lat0))

    def to_xy(la, lo):
        return np.asarray(lo) * scale * geo.R * np.pi / 180, np.asarray(la) * geo.R * np.pi / 180

    fx, fy = to_xy(lat, lon)
    best = np.full(len(fx), np.inf)
    for a, b in zip(points, points[1:]):
        ax, ay = to_xy(a.lat, a.lon)
        bx, by = to_xy(b.lat, b.lon)
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        if length <= 0:
            continue
        t = np.clip(((fx - ax) * dx + (fy - ay) * dy) / length, 0.0, 1.0)
        best = np.minimum(best, np.hypot(fx - (ax + t * dx), fy - (ay + t * dy)))
    return best


def compare(analysis: Analysis, plan: Plan) -> Adherence | None:
    """Where the flight followed the plan, and where — and when — it stopped.

    The decision point is the **first sustained** departure, not the first fix off the
    line: a glide around a shower is not abandoning the plan, and calling it one would
    put a marker on a moment the pilot would not recognise.
    """
    if plan is None or len(plan.turnpoints) < 2:
        return None
    flight, series = analysis.flight, analysis.series
    result = Adherence(plan=plan, planned_km=plan.distance / 1000)

    # A task is taken **in order**, and missing one ends it. Without that rule an
    # out-and-return whose far turnpoint was missed still scores its finish, because the
    # finish is back where the launch was — which reported a 51.4 km plan as 51.4 km
    # flown on a flight that turned 12 km short of its only real turnpoint.
    reached, cursor, live = [], 0, True
    for ordinal, point in enumerate(plan.turnpoints):
        distances = geo.distance(point.lat, point.lon, flight.lat, flight.lon)
        ahead = distances[cursor:] if live else distances[:0]
        closest = float(ahead.min()) if len(ahead) else float(distances.min())
        inside = np.flatnonzero(ahead <= point.radius) if len(ahead) else np.array([])
        if live and inside.size:
            at = cursor + int(inside[0])
            reached.append(Reached(
                ordinal, point.name, at,
                flight.local_time(at).strftime("%H:%M:%S"), closest,
            ))
            cursor = at
        else:
            reached.append(Reached(ordinal, point.name, None, None, closest))
            live = False
    result.reached = reached

    last = result.last_reached
    if last is not None:
        result.flown_km = sum(
            float(geo.distance(a.lat, a.lon, b.lat, b.lon))
            for a, b in zip(plan.turnpoints[:last.ordinal + 1],
                            plan.turnpoints[1:last.ordinal + 1])
        ) / 1000
        result.shortfall = max(plan.distance - result.flown_km * 1000, 0.0)

    off = _cross_track(plan, flight.lat, flight.lon) > DEPARTURE
    if off.any():
        run_start = None
        for index, away in enumerate(off):
            if away and run_start is None:
                run_start = index
            elif not away:
                run_start = None
            elif run_start is not None and (
                series.t[index] - series.t[run_start] >= DEPARTURE_SECONDS
            ):
                result.departure_index = run_start
                result.departure_time = flight.local_time(run_start).strftime("%H:%M:%S")
                result.departure_distance = float(
                    _cross_track(plan, flight.lat[run_start:run_start + 1],
                                 flight.lon[run_start:run_start + 1])[0]
                )
                break
    return result

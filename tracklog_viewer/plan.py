"""The pilot's intent — the reference frame the debrief is missing.

Everything else in this repository works around the absence of a plan, and the debrief's
central rule exists because of it: *a finding is a measurement plus a link, never an
imperative*, because the tool cannot see the sky, the gaggle, the airspace or **the
pilot's plan**. Three of those four are genuinely out of reach. The fourth is not — the
pilot can simply say what the plan was, and then the tool compares against something the
pilot themselves signed.

That converts a family of forbidden sentences into legitimate ones without touching the
no-imperatives rule:

    ✗ "You should have pushed on to Predazzo."
    ✓ "The plan was Predazzo and back, 100 km. The flight turned 31 km short, at 14:10,
       from 2 350 m — the first point where the track leaves the planned line by more
       than 3 km."

Still past tense, still two measurements and a link, and now about the pilot's own stated
intention rather than about an ideal flight nobody declared.

**The cheapest first version throws nothing away that is not already parsed.** 10 of the
50 sample IGCs carry `C` task records, one of them a full 12-point competition task with
names; `igc.py` parses all of it into `Flight.task`, and before this module the only
reference to `.task` in the whole tree was the constructor. So the first source of a plan
is the tracklog itself.

Two rules keep it honest:

* **A plan is timestamped and frozen at takeoff.** `made_at` is recorded, and a plan
  written after landing is a story about the flight rather than a plan — so it is labelled
  *reconstructed intent* and its findings are downgraded. Without this the feature quietly
  becomes a tool for justifying whatever happened.
* **No plan means today's debrief, unchanged.** Degrade, never blank, the same rule the
  meteo and terrain findings already follow.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import geo
from .igc import Turnpoint

# How far off the planned line counts as having left it, and for how long. A single fix
# 3 km wide of the line is a thermal drifting; four minutes of it is a decision.
DEPARTURE_METRES = 3000.0
DEPARTURE_SECONDS = 240.0
# Beyond this the "plan" is not this flight's plan, and comparing against it is worse
# than having no plan at all.
#
# This is the measured state of the archive, not a defensive guess. Ten of the fifty
# sample files carry `C` records; the two that carry a *task* — `2020-08-16-XCT-ROP-01`
# and `2021-07-06-XCT-ROP-01` — declare turnpoints 29 km and 432 km from anywhere the
# glider went. They are tasks left loaded in XCTrack from another site on another day,
# and the logger writes out whatever is loaded. Compared against, the second produced
# the loudest card on that flight's report: *"cost 33 525 m — the track left the planned
# line at 13:31:08"*, with a median distance from the line of 18 812 m. A flight whose
# median cross-track error is eighteen kilometres has not departed from a plan; it is
# being measured against somebody else's.
#
# The median is the right test rather than the closest approach: a flight that genuinely
# flew most of a task and then bailed is still near the line for most of its length, and
# refusing that case would throw away the findings the feature exists for.
#
# What this does *not* catch, and knowingly: `2020-08-16-XCT-ROP-01` carries a 12-point
# task whose nearest real turnpoint is 29 km away, yet its median cross-track error is
# 2 628 m — the long leg from the takeoff towards those turnpoints happens to run over
# the flying area. That flight still reports "1 of 12 planned turnpoints reached", which
# is *true*, and the task is labelled reconstructed intent because a `C` record carries
# no `made_at`. Telling it apart from a genuinely abandoned task needs progress along
# the line rather than distance from it, and two files is not enough to tune that on.
STALE_MEDIAN_METRES = 10_000.0
# A turnpoint is reached inside its radius; competition tasks declare one, a hand-written
# plan usually does not, so this is the default cylinder.
DEFAULT_RADIUS = 400.0
# Where a plan is remembered between runs, so a plan made on Friday is found by Sunday's
# analysis without being named again.
REMEMBERED = Path.home() / ".config" / "parainsights" / "plans"


@dataclass
class Plan:
    """A declared task, an intent, or an expected day — all three optional.

    `made_at` is the load-bearing field. `None` means the plan was not timestamped before
    the flight, which makes it reconstructed intent rather than a plan, and everything
    derived from it says so.
    """

    made_at: str | None = None
    turnpoints: list[Turnpoint] = field(default_factory=list)
    radii: list[float] = field(default_factory=list)
    goal_distance: float | None = None  # metres
    planned_start: str | None = None
    planned_turn: str | None = None
    planned_finish: str | None = None
    min_clearance: float | None = None  # metres AGL
    notes: str | None = None
    source: str = "none"  # "task", "sidecar", "remembered"

    @property
    def reconstructed(self) -> bool:
        """A plan with no `made_at` is a story about the flight, not a plan."""
        return self.made_at is None

    @property
    def declared(self) -> bool:
        return len(self.turnpoints) >= 2

    def radius(self, index: int) -> float:
        if index < len(self.radii) and self.radii[index]:
            return float(self.radii[index])
        return DEFAULT_RADIUS

    def to_dict(self) -> dict:
        return {**asdict(self), "reconstructed": self.reconstructed}


def from_flight(flight) -> Plan | None:
    """A plan from the tracklog's own `C` records.

    Most XCTrack files carry only the minimal takeoff/landing pair, which declares no task
    at all — two points is a line, not an intent — so anything under three turnpoints is
    refused rather than compared against.

    A task in the file has no `made_at`: the IGC C record carries a declaration date in
    its header, but the parser does not keep it, and inferring one from the flight's own
    date would be exactly the self-justifying move `made_at` exists to prevent. So a task
    read here is reconstructed intent until something says otherwise.
    """
    task = getattr(flight, "task", None) or []
    if len(task) < 3:
        return None
    return Plan(made_at=None, turnpoints=list(task), source="task")


def load(path) -> Plan | None:
    """A plan from a sidecar JSON file: hand-editable, diffable, and what a pre-flight
    run would write."""
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    points = [
        Turnpoint(str(p.get("name", "")), float(p["lat"]), float(p["lon"]))
        for p in payload.get("turnpoints", [])
        if isinstance(p, dict) and "lat" in p and "lon" in p
    ]
    return Plan(
        made_at=payload.get("made_at"),
        turnpoints=points,
        radii=[float(r) for r in payload.get("radii", []) if r is not None],
        goal_distance=payload.get("goal_distance"),
        planned_start=payload.get("planned_start"),
        planned_turn=payload.get("planned_turn"),
        planned_finish=payload.get("planned_finish"),
        min_clearance=payload.get("min_clearance"),
        notes=payload.get("notes"),
        source="sidecar",
    )


def discover(tracklog, *, remembered: Path | None = None, date: str | None = None,
             site: str | None = None) -> Path | None:
    """Where a plan for this tracklog would be, in the order a plan is looked for.

    A sidecar beside the file beats a remembered one: if the pilot wrote a plan next to
    this flight, that is the plan for this flight.
    """
    track = Path(tracklog)
    for candidate in (track.with_suffix(".plan.json"),
                      track.with_name(track.stem + ".plan.json")):
        if candidate.is_file():
            return candidate
    directory = remembered or REMEMBERED
    if date and directory.is_dir():
        key = f"{date}-{(site or 'flight').replace(' ', '-')}.json"
        candidate = directory / key
        if candidate.is_file():
            return candidate
        loose = sorted(directory.glob(f"{date}*.json"))
        if loose:
            return loose[0]
    return None


def for_flight(analysis, tracklog=None, *, explicit=None,
               remembered: Path | None = None) -> Plan | None:
    """The plan for this flight, from whichever source has one."""
    if explicit:
        found = load(explicit)
        if found:
            return found
    if tracklog:
        path = discover(tracklog, remembered=remembered,
                        date=analysis.summary.date, site=analysis.summary.site)
        if path:
            found = load(path)
            if found:
                found.source = "sidecar" if path.parent == Path(tracklog).parent else "remembered"
                return found
    return from_flight(analysis.flight)


# ---------------------------------------------------------------------------
# What the analysis does with it
# ---------------------------------------------------------------------------


def _leg_distance(points) -> float:
    return float(
        sum(
            geo.distance(a.lat, a.lon, b.lat, b.lon)
            for a, b in zip(points, points[1:])
        )
    )


def _cross_track(plan: Plan, lat, lon) -> np.ndarray:
    """Distance from the planned line, per fix, in metres.

    Distance to the nearest *leg*, taken as the minimum over the legs of the distance to
    each leg's endpoints and to its interior. A great-circle cross-track would be more
    correct and is not worth it here: at the 3 km threshold this comparison uses, over legs
    of tens of kilometres, the difference is metres.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    best = np.full(lat.shape, np.inf)
    for a, b in zip(plan.turnpoints, plan.turnpoints[1:]):
        # Project onto the leg in a local flat frame; the legs are short enough.
        mid = np.radians((a.lat + b.lat) / 2.0)
        ax, ay = a.lon * np.cos(mid), a.lat
        bx, by = b.lon * np.cos(mid), b.lat
        px, py = lon * np.cos(mid), lat
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = np.zeros_like(px) if length == 0 else np.clip(
            ((px - ax) * dx + (py - ay) * dy) / length, 0.0, 1.0
        )
        nx, ny = ax + t * dx, ay + t * dy
        best = np.minimum(best, geo.distance(py, px / np.cos(mid), ny, nx / np.cos(mid)))
    return best


def describes(analysis, plan: Plan | None) -> bool:
    """Is this plan plausibly a plan *for this flight*?

    Every comparison below goes through here, because a stale plan does not produce a
    slightly wrong finding — it produces the most confident and most prominent card on
    the page, about a flight nobody flew. See `STALE_MEDIAN_METRES` for the two files in
    the archive that forced it.
    """
    if plan is None or not plan.declared:
        return False
    off = _cross_track(plan, analysis.flight.lat, analysis.flight.lon)
    if not np.isfinite(off).any():
        return False
    return float(np.median(off)) <= STALE_MEDIAN_METRES


@dataclass
class Adherence:
    """How closely the flight followed the planned line, and where it left it."""

    median_off: float
    max_off: float
    departed_at: str | None
    departed_index: int | None
    departed_distance: float | None  # how far short of the goal, along the plan
    reconstructed: bool


def adherence(analysis, plan: Plan | None) -> Adherence | None:
    """Cross-track error over time, and the decision point.

    The decision point is the first *sustained* departure — `DEPARTURE_SECONDS` beyond
    `DEPARTURE_METRES` — rather than the first fix over the line, because a thermal drifts
    a kilometre off course without anyone deciding anything.
    """
    if not describes(analysis, plan):
        return None
    flight = analysis.flight
    off = _cross_track(plan, flight.lat, flight.lon)

    t = analysis.series.t
    outside = off > DEPARTURE_METRES
    departed_index = None
    start = None
    for i, away in enumerate(outside):
        if away and start is None:
            start = i
        elif not away:
            start = None
        elif start is not None and t[i] - t[start] >= DEPARTURE_SECONDS:
            departed_index = start
            break

    remaining = None
    if departed_index is not None and plan.goal_distance:
        flown = float(analysis.series.s[departed_index])
        remaining = max(plan.goal_distance - flown, 0.0)

    return Adherence(
        median_off=round(float(np.median(off))),
        max_off=round(float(np.max(off))),
        departed_at=(
            flight.local_time(departed_index).strftime("%H:%M:%S")
            if departed_index is not None
            else None
        ),
        departed_index=departed_index,
        departed_distance=round(remaining) if remaining else None,
        reconstructed=plan.reconstructed,
    )


@dataclass
class Turnpoints:
    """Which planned turnpoints were reached, and when."""

    reached: int
    total: int
    first_missed: str | None
    times: list[str | None]
    reconstructed: bool


def turnpoints(analysis, plan: Plan | None) -> Turnpoints | None:
    """Turnpoint accounting: which were reached, in order, and where the deficit began.

    In order on purpose — a task is a sequence, and a turnpoint clipped on the way home
    after skipping the one before it has not been reached in any sense that scores.
    """
    if not describes(analysis, plan):
        return None
    flight = analysis.flight
    times: list[str | None] = []
    first_missed = None
    cursor = 0

    for index, point in enumerate(plan.turnpoints):
        radius = plan.radius(index)
        distances = geo.distance(point.lat, point.lon,
                                 flight.lat[cursor:], flight.lon[cursor:])
        inside = np.flatnonzero(np.asarray(distances) <= radius)
        if inside.size:
            at = cursor + int(inside[0])
            times.append(flight.local_time(at).strftime("%H:%M:%S"))
            cursor = at
        else:
            times.append(None)
            if first_missed is None:
                first_missed = point.name or f"turnpoint {index + 1}"

    return Turnpoints(
        reached=sum(1 for t in times if t),
        total=len(plan.turnpoints),
        first_missed=first_missed,
        times=times,
        reconstructed=plan.reconstructed,
    )


@dataclass
class Budget:
    """Planned distance against scored distance."""

    planned_km: float
    scored_km: float
    short_km: float
    reconstructed: bool


def budget(analysis, plan: Plan | None, route) -> Budget | None:
    """Planned against scored. Refused without both — a target and an achievement."""
    if plan is None or not describes(analysis, plan):
        return None
    planned = plan.goal_distance or (
        _leg_distance(plan.turnpoints) if plan.declared else None
    )
    if not planned or route is None or not getattr(route, "distance", 0):
        return None
    return Budget(
        planned_km=round(planned / 1000.0, 1),
        scored_km=round(route.distance / 1000.0, 2),
        short_km=round((planned - route.distance) / 1000.0, 1),
        reconstructed=plan.reconstructed,
    )

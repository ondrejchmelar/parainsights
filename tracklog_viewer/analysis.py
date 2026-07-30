"""Flight analysis: phases, per-thermal and per-glide statistics, wind, time budget.

The phase heuristic is igc2kmz's and is documented in its HACKING.md: compare the
*progress* (straight-line distance over distance flown, in a 20 s window) with the
climb rate. Flying straight gives progress near 1; circling drives it towards 0.

Everything here returns plain dataclasses so both renderers can serialise them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

import numpy as np

from . import geo
from .flight import Series, derive
from .igc import Flight

GLIDE_PROGRESS = 0.9
MIN_THERMAL_SECONDS = 60
MIN_THERMAL_GAIN = 50.0
MIN_GLIDE_SECONDS = 120
MIN_DIVE_SECONDS = 30
MIN_DIVE_LOSS = 100.0
MAX_DIVE_CLIMB = -2.0
CONDENSE_THERMAL = 60
CONDENSE_GLIDE = 60
CONDENSE_DIVE = 30
TURNING_THRESHOLD = 3.0  # deg/s; below this the glider is not really circling
# How long the glider has to be turning before the climb counts as started. One stray
# sample over the threshold is noise; five seconds of it is a pilot entering a turn.
TURN_ONSET_SECONDS = 5.0
# A thermal circle takes ~18–22 s. Sampling slower than a quarter of that cannot
# reconstruct the turn — the heading change between fixes aliases, and the count comes
# out low and confident. KML exports are typically 15 s, so this matters in practice.
TURN_RESOLUTION_LIMIT = 5.0  # seconds between fixes

# A tow is the launch, not a thermal: it starts with the flight, climbs steadily,
# and is flown essentially straight. A thermal turns ~3 times a minute (20 s per
# circle); anything under a third of that was not being circled.
TOW_START_SECONDS = 120
TOW_MIN_CLIMB = 1.0
TOW_MAX_TURNS_PER_MINUTE = 1.5
# A tow lasts two to five minutes, so judging one needs several fixes inside it. Above
# this the whole launch is three or four points, `progress` reads as straight because
# every corner has been cut, and any brisk launch climb gets called a tow: an XContest
# KMZ of an 11-hour flight is sampled at 83 s and reported a winch launch releasing at
# 4 574 m in the Himalaya.
TOW_RESOLUTION_LIMIT = 15.0  # seconds between fixes


class Phase(Enum):
    UNKNOWN = "unknown"
    THERMAL = "thermal"
    GLIDE = "glide"
    DIVE = "dive"
    TOW = "tow"


@dataclass
class Wind:
    """Wind estimated from how far a thermal drifts while being circled."""

    speed: float  # m/s
    direction: float  # degrees, the direction the wind blows FROM
    cardinal: str
    confidence: float  # 0..1, from the straightness of the drift

    @property
    def kmh(self) -> float:
        return self.speed * 3.6


@dataclass
class Segment:
    """One detected phase of flight."""

    phase: Phase
    start: int
    stop: int
    start_time: str
    finish_time: str
    duration: int  # seconds
    altitude_change: float
    start_altitude: float
    finish_altitude: float
    distance: float  # straight-line, metres
    average_speed: float  # km/h
    average_climb: float  # m/s
    maximum_climb: float  # m/s, on the 20 s average
    peak_climb: float  # m/s, fix to fix
    maximum_descent: float
    accumulated_gain: float
    accumulated_loss: float
    efficiency: float | None = None  # average climb / maximum climb, %
    average_ld: float | None = None  # glide ratio
    turns: float | None = None  # number of 360s flown
    turn_direction: str | None = None  # "left", "right" or "mixed"
    reversals: int | None = None  # changes of turn direction
    circle_seconds: float | None = None  # mean time for one 360
    circle_radius: float | None = None  # metres
    wind: Wind | None = None
    centre: tuple[float, float] | None = None  # lat, lon of the segment midpoint


@dataclass
class Summary:
    pilot: str | None
    glider: str | None
    site: str | None
    date: str
    takeoff_time: str
    landing_time: str
    timezone: str | None
    duration: int
    fixes: int
    sample_interval: float  # median seconds between fixes
    altitude_source: str
    baro_offset: float | None
    takeoff_altitude: float
    landing_altitude: float
    max_altitude: float
    min_altitude: float
    total_gain: float
    max_gain: float
    max_climb: float
    max_sink: float
    max_speed: float
    track_distance: float  # metres flown
    straight_distance: float  # take-off to landing
    max_distance_from_takeoff: float


@dataclass
class TimeBudget:
    thermalling: int  # seconds
    gliding: int
    diving: int
    towing: int
    other: int

    @property
    def total(self) -> int:
        return self.thermalling + self.gliding + self.diving + self.towing + self.other

    def fractions(self) -> dict[str, float]:
        total = self.total or 1
        return {
            "thermalling": self.thermalling / total,
            "gliding": self.gliding / total,
            "diving": self.diving / total,
            "towing": self.towing / total,
            "other": self.other / total,
        }


@dataclass
class Analysis:
    flight: Flight
    series: Series
    summary: Summary
    segments: list[Segment]
    budget: TimeBudget
    wind: Wind | None
    climb_histogram: dict[str, list[float]] = field(default_factory=dict)

    @property
    def thermals(self) -> list[Segment]:
        return [s for s in self.segments if s.phase is Phase.THERMAL]

    @property
    def tow(self) -> Segment | None:
        return next((s for s in self.segments if s.phase is Phase.TOW), None)

    @property
    def glides(self) -> list[Segment]:
        return [s for s in self.segments if s.phase is Phase.GLIDE]

    @property
    def dives(self) -> list[Segment]:
        return [s for s in self.segments if s.phase is Phase.DIVE]

    def to_dict(self) -> dict:
        """Serialisable form — the contract both renderers consume."""
        return {
            "summary": asdict(self.summary),
            "budget": {**asdict(self.budget), "fractions": self.budget.fractions()},
            "wind": asdict(self.wind) if self.wind else None,
            "climb_histogram": self.climb_histogram,
            "segments": [
                {**asdict(s), "phase": s.phase.value} for s in self.segments
            ],
        }


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Half-open index ranges where ``mask`` is True."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    # Plain ints: these indices end up in dataclasses that get serialised to JSON,
    # and numpy scalars are not JSON-serialisable.
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2])]


def _condense(runs: list[tuple[int, int]], t: np.ndarray, gap: float) -> list[tuple[int, int]]:
    """Merge runs separated by less than ``gap`` seconds.

    A thermal briefly exited and re-entered is one thermal, not three.
    """
    if not runs:
        return []
    merged = [list(runs[0])]
    for start, stop in runs[1:]:
        if t[start] - t[merged[-1][1] - 1] <= gap:
            merged[-1][1] = stop
        else:
            merged.append([start, stop])
    return [(a, b) for a, b in merged]


def _sustained(mask: np.ndarray, need: int) -> np.ndarray:
    """``mask`` with any run shorter than ``need`` samples removed.

    Instantaneous turn rate is noisy: a 1 Hz GPS heading wanders several degrees a second
    while the glider flies dead straight, so `|turn_rate| > 3` fires every 20–45 s during
    a glide. Left in, those specks keep the gaps inside a "thermal" short enough for
    `_condense` to bridge, and a 90 s glide between two climbs is welded into one segment
    whose drift is the glide. Turning has to be *sustained* before it counts as circling.
    """
    out = np.zeros_like(mask, dtype=bool)
    for start, stop in _runs(mask):
        if stop - start >= need:
            out[start:stop] = True
    return out


def classify(series: Series) -> np.ndarray:
    """Assign a :class:`Phase` to every fix.

    Three rules here exist because of what they exclude, and all three came out of the
    same failure: a straight climbing run into a thermal is not a thermal, and calling it
    one wrecks the wind estimate. Wind is fitted as the drift of a *circling* glider, so
    any straight flight inside the phase is measured as if it were moving air. On one
    Dolomites flight that put 30 s of a 70 s climb into a straight westward run and
    reported 18 km/h from the east; the same file had a 242 s "thermal" that was really
    two climbs with a 90 s glide welded between them, reported as 22 km/h.
    """
    phases = np.full(len(series), Phase.UNKNOWN.value, dtype=object)
    t = series.t
    # Actually turning, and turning for long enough to mean it. `progress` falls in a
    # slow S as well as in a circle, and only a circle averages the glider's own airspeed
    # away. Sustained in seconds rather than samples: a 15 s KML would otherwise need
    # 75 s of continuous turning before it counted.
    onset = max(int(round(TURN_ONSET_SECONDS / max(sample_interval(series), 1e-6))), 1)
    circling = _sustained(np.abs(series.turn_rate) > TURNING_THRESHOLD, onset)

    # A glide ends when the air starts giving something back. Without the climb test a
    # straight run through lift stayed "gliding" until progress broke, which is well
    # after the climb began.
    glide = (series.progress >= GLIDE_PROGRESS) & (series.climb <= 0.0)
    for start, stop in _condense(_runs(glide), t, CONDENSE_GLIDE):
        phases[start:stop] = Phase.GLIDE.value

    dive = (series.progress < GLIDE_PROGRESS) & (series.climb < 1.0)
    for start, stop in _condense(_runs(dive), t, CONDENSE_DIVE):
        if series.alt[stop - 1] - series.alt[start] < -MIN_DIVE_LOSS:
            phases[start:stop] = Phase.DIVE.value

    # Climbing *and* not going straight. The clause this replaces was `climb > 1.0`
    # alone, which fires on a glider flying dead straight through a lift band at full
    # speed — and, worse, fires on scattered single samples during a long glide, which
    # CONDENSE_THERMAL then bridges into one enormous "thermal" spanning the glide.
    thermal = (series.climb > 0.0) & (
        (series.progress < GLIDE_PROGRESS) | (series.speed < 10.0) | circling
    )
    for start, stop in _condense(_runs(thermal), t, CONDENSE_THERMAL):
        # The phase is the circling. Trim the straight run-in at the front and the
        # straight exit at the back; both are left unclassified, which the time budget
        # already accounts for as "other". Safe to span first-to-last here because a
        # long straight stretch in the middle has already split the run above — the only
        # gaps left inside are short enough to be one thermal exited and re-entered.
        inside = np.flatnonzero(circling[start:stop])
        if inside.size:
            start, stop = start + int(inside[0]), start + int(inside[-1]) + 1
        phases[start:stop] = Phase.THERMAL.value

    return phases


def _estimate_wind(series: Series, start: int, stop: int) -> Wind | None:
    """Fit the drift of a circling glider to get the wind at that altitude.

    While circling, the glider's own airspeed averages out over each turn, so the
    mean motion of the track is the motion of the air. A straight-line fit of
    position against time gives that mean directly, and how well the fit holds
    tells us how much to trust it.
    """
    if stop - start < 20:
        return None
    t = series.t[start:stop]
    x, y = series.x[start:stop], series.y[start:stop]
    span = t[-1] - t[0]
    if span < 30:
        return None

    (vx, x0), residuals_x = np.polyfit(t, x, 1, full=True)[:2]
    (vy, y0), residuals_y = np.polyfit(t, y, 1, full=True)[:2]
    speed = float(np.hypot(vx, vy))
    if speed < 0.1:
        return Wind(0.0, 0.0, "calm", 1.0)

    # Direction the air moves towards, then reversed: wind is named for where it
    # comes from.
    towards = np.degrees(np.arctan2(vx, vy)) % 360
    direction = (towards + 180) % 360

    # Confidence: drift explained vs the spread of the circles around it.
    drift = speed * span
    scatter = float(np.sqrt((residuals_x.sum() + residuals_y.sum()) / len(t))) if len(t) else 0.0
    confidence = float(np.clip(drift / (drift + 2 * scatter), 0.0, 1.0)) if drift else 0.0

    return Wind(speed, float(direction), geo.cardinal(direction), confidence)


def salient(values, threshold: float) -> list[int]:
    """Indices of the altitude extremes worth labelling.

    Marking every local maximum and minimum of a real trace buries the reader; the
    interesting ones are those separated from their neighbours by a real height change.
    So: take the local extremes, then repeatedly drop the one whose swing to an adjacent
    extreme is smallest, until every remaining swing clears ``threshold``. That is
    prominence pruning, and it is easy to check — a single hill gives three marks, and
    the count falls monotonically as the threshold rises.

    igc2kmz uses a recursive largest-drop/largest-climb split for this. A direct port
    produced four marks for a flight with eleven climbs, so this is deliberately a
    different algorithm rather than a broken copy of that one.
    """
    values = np.asarray(values, dtype=float)
    if len(values) < 3:
        return list(range(len(values)))

    # Turning points of the sequence, endpoints always included.
    marks = [0]
    for i in range(1, len(values) - 1):
        if (values[i] - values[i - 1]) * (values[i + 1] - values[i]) < 0:
            marks.append(i)
    marks.append(len(values) - 1)

    # Prune the least prominent extreme until nothing small remains.
    while len(marks) > 2:
        swings = [abs(values[marks[i + 1]] - values[marks[i]]) for i in range(len(marks) - 1)]
        smallest = min(range(len(swings)), key=lambda i: swings[i])
        if swings[smallest] >= threshold:
            break
        # Drop whichever end of the flattest pair is interior; keep the endpoints.
        drop = smallest if 0 < smallest < len(marks) - 1 else smallest + 1
        if drop in (0, len(marks) - 1):
            drop = smallest + 1 if smallest == 0 else smallest
        marks.pop(drop)
    return marks


def sample_interval(series: Series) -> float:
    """Median seconds between fixes."""
    if len(series) < 2:
        return 0.0
    return float(np.median(np.diff(series.t)))


def _turn_stats(series: Series, start: int, stop: int) -> dict:
    """Count the 360s in a climb, and how tidily they were flown.

    The number of turns is the total heading change divided by 360. Turn direction,
    reversals and circle time say whether the climb was cored smoothly or scratched
    around — which is what you actually want to know when reviewing a thermal.
    """
    heading = series.heading[start:stop]
    rate = series.turn_rate[start:stop]
    t = series.t[start:stop]
    if len(heading) < 2:
        return {}

    net = float(heading[-1] - heading[0])
    total = float(np.abs(np.diff(heading)).sum())
    turns = total / 360.0

    turning = np.abs(rate) > TURNING_THRESHOLD
    signs = np.sign(rate[turning])
    if signs.size:
        right = float((signs > 0).mean())
        direction = "right" if right > 0.8 else "left" if right < 0.2 else "mixed"
        reversals = int((np.diff(signs) != 0).sum())
    else:
        direction, reversals = None, 0

    duration = float(t[-1] - t[0])
    circle_seconds = duration / turns if turns >= 0.5 else None
    # Radius from the circle period and the speed actually flown while turning.
    radius = None
    if circle_seconds:
        turning_speed = float(np.mean(series.speed[start:stop][turning]) / 3.6) if turning.any() else None
        if turning_speed:
            radius = turning_speed * circle_seconds / (2 * np.pi)

    return {
        "turns": round(turns, 1),
        "turn_direction": direction,
        "reversals": reversals,
        "circle_seconds": round(circle_seconds, 1) if circle_seconds else None,
        "circle_radius": round(radius) if radius else None,
        "net_rotation": net,
    }


def _segment(flight: Flight, series: Series, phase: Phase, start: int, stop: int) -> Segment:
    last = stop - 1
    alt = series.alt
    duration = int(series.t[last] - series.t[start])
    dz = float(alt[last] - alt[start])
    steps = np.diff(alt[start:stop])
    step_t = np.diff(series.t[start:stop])
    peak = steps / np.where(step_t == 0, np.nan, step_t)

    straight = float(
        geo.distance(flight.lat[start], flight.lon[start], flight.lat[last], flight.lon[last])
    )
    window_climb = series.climb[start:stop]
    max_climb = float(window_climb.max())

    segment = Segment(
        phase=phase,
        start=start,
        stop=stop,
        start_time=flight.local_time(start).strftime("%H:%M:%S"),
        finish_time=flight.local_time(last).strftime("%H:%M:%S"),
        duration=duration,
        altitude_change=round(dz),
        start_altitude=round(float(alt[start])),
        finish_altitude=round(float(alt[last])),
        distance=round(straight),
        average_speed=round(3.6 * straight / duration, 1) if duration else 0.0,
        average_climb=round(dz / duration, 2) if duration else 0.0,
        maximum_climb=round(max_climb, 1),
        peak_climb=round(float(np.nanmax(peak)), 1) if peak.size else 0.0,
        maximum_descent=round(float(window_climb.min()), 1),
        accumulated_gain=round(float(steps[steps > 0].sum())),
        accumulated_loss=round(float(steps[steps < 0].sum())),
        centre=(
            round(float(np.mean(flight.lat[start:stop])), 6),
            round(float(np.mean(flight.lon[start:stop])), 6),
        ),
    )

    if phase is Phase.THERMAL:
        # Efficiency: how much of the best climb on offer was actually realised.
        if duration and max_climb > 0:
            segment.efficiency = round(100.0 * dz / (duration * max_climb))
        segment.wind = _estimate_wind(series, start, stop)
        # Turn statistics are simply unavailable at coarse sampling. Leaving them
        # None is honest; a plausible-looking wrong number is not.
        if sample_interval(series) <= TURN_RESOLUTION_LIMIT:
            for key, value in _turn_stats(series, start, stop).items():
                if hasattr(segment, key):
                    setattr(segment, key, value)
    elif phase in (Phase.GLIDE, Phase.DIVE):
        segment.average_ld = round(-straight / dz, 1) if dz < 0 else None

    return segment


def _launch_climb(flight: Flight, series: Series, segments: list[Segment]) -> Segment | None:
    """A straight launch climb, built as a segment so it can be judged as a tow.

    `classify` will not call a straight climb a thermal — that rule is what stops a run
    through a lift band being measured as wind — but a tow *is* a straight climb, and it
    has to exist as a segment before it can be recognised as one. So it is constructed
    here, at the launch only, and only when no phase already covers it.

    It is built over the *whole* launch climb, deliberately overlapping whatever phases
    fall inside it. A tow is rarely flown perfectly straight — the one on the reference
    flight contains 2.8 turns — so the circling part of it is detected as a short, turny
    thermal. Judged on that fragment the launch looks like a thermal at 2.8 turns per
    minute; judged over the whole 113 s climb it is a tow. If it is one, the fragments
    inside it are dropped in favour of it.

    It is built from the climb alone, with no straightness test: whether it was flown
    straight is `_reclassify_tow`'s judgement and it makes it on turns per minute, which
    is the better measure. A `progress` test here would also break on any discontinuity
    in the track, because the 20 s progress window straddles it.
    """
    for start, stop in _condense(_runs(series.climb > TOW_MIN_CLIMB), series.t,
                                 CONDENSE_THERMAL):
        if series.t[start] > TOW_START_SECONDS:
            break                       # only the launch can be a tow
        # A tow runs from the ground, so the candidate starts at the first fix rather
        # than where the climb first passes TOW_MIN_CLIMB. The difference is the few
        # seconds of acceleration on the wire, and leaving them out inflates turns per
        # minute over a shorter window — enough to fail the reference flight at 1.54
        # against a limit of 1.5.
        start = 0
        duration = series.t[stop - 1] - series.t[start]
        gain = series.alt[stop - 1] - series.alt[start]
        if duration < MIN_THERMAL_SECONDS or gain <= MIN_THERMAL_GAIN:
            return None
        return _segment(flight, series, Phase.THERMAL, start, stop)
    return None


def _reclassify_tow(series: Series, segments: list[Segment]) -> None:
    """Relabel a launch climb as a tow rather than a thermal.

    At a winch or aerotow site the first climb is the launch: it starts with the
    flight, climbs hard and steadily, and is flown straight instead of circled.
    Left as a thermal it flatters the thermal statistics and — because a straight
    climb drifts with the glider rather than the air — poisons the wind estimate.
    """
    if sample_interval(series) > TOW_RESOLUTION_LIMIT:
        return  # too coarse to tell a tow from any other launch climb
    for segment in segments:
        if series.t[segment.start] > TOW_START_SECONDS:
            return  # only the launch can be a tow
        if segment.phase is not Phase.THERMAL:
            continue
        if segment.average_climb < TOW_MIN_CLIMB:
            continue
        if segment.turns is None:
            # Sampling too coarse to count turns, so ask the progress series instead:
            # a tow is flown close to straight, a thermal is not. Treating unknown
            # turns as zero would label every coarse soarable launch a tow.
            straightness = float(np.mean(series.progress[segment.start:segment.stop]))
            if straightness < 0.55:
                continue
        else:
            minutes = segment.duration / 60 or 1
            if segment.turns / minutes > TOW_MAX_TURNS_PER_MINUTE:
                continue  # it was circled: a thermal straight off launch
        segment.phase = Phase.TOW
        segment.efficiency = None  # thermal efficiency is meaningless under tow
        segment.wind = None
        return


def _summary(flight: Flight, series: Series) -> Summary:
    alt = series.alt
    steps = np.diff(alt)
    # Largest gain from any low point, i.e. the best single sustained climb.
    running_min = np.minimum.accumulate(alt)
    from_takeoff = geo.distance(flight.lat[0], flight.lon[0], flight.lat, flight.lon)

    return Summary(
        pilot=flight.headers.pilot,
        glider=flight.headers.glider_type,
        site=flight.headers.site,
        date=flight.local_time(0).strftime("%Y-%m-%d"),
        takeoff_time=flight.local_time(0).strftime("%H:%M:%S"),
        landing_time=flight.local_time(-1).strftime("%H:%M:%S"),
        timezone=flight.timezone_source,
        duration=int(series.t[-1]),
        fixes=len(flight),
        sample_interval=round(sample_interval(series), 1),
        altitude_source="baro" if flight.has_baro else "gps",
        baro_offset=round(flight.baro_offset) if flight.baro_offset is not None else None,
        takeoff_altitude=round(float(alt[0])),
        landing_altitude=round(float(alt[-1])),
        max_altitude=round(float(alt.max())),
        min_altitude=round(float(alt.min())),
        total_gain=round(float(steps[steps > 0].sum())),
        max_gain=round(float((alt - running_min).max())),
        max_climb=round(float(series.climb.max()), 1),
        max_sink=round(float(series.climb.min()), 1),
        max_speed=round(float(series.speed.max()), 1),
        track_distance=round(float(series.s[-1])),
        straight_distance=round(
            float(geo.distance(flight.lat[0], flight.lon[0], flight.lat[-1], flight.lon[-1]))
        ),
        max_distance_from_takeoff=round(float(from_takeoff.max())),
    )


def _climb_histogram(series: Series, phases: np.ndarray) -> dict[str, list[float]]:
    """Distribution of climb rate while thermalling, in 0.5 m/s buckets."""
    thermalling = phases == Phase.THERMAL.value
    values = series.climb[thermalling]
    if not values.size:
        return {}
    edges = np.arange(-2.0, 6.5, 0.5)
    counts, _ = np.histogram(values, bins=edges)
    return {
        "edges": edges.tolist(),
        "counts": counts.astype(float).tolist(),
        "seconds_per_count": [float(np.median(np.diff(series.t)))],
    }


def analyse(flight: Flight, *, window: float | None = None) -> Analysis:
    """Run the full analysis over a parsed flight."""
    series = derive(flight, **({"window": window} if window else {}))
    phases = classify(series)

    segments: list[Segment] = []
    for phase, minimum, test in (
        (Phase.THERMAL, MIN_THERMAL_SECONDS, lambda dz, dt: dz > MIN_THERMAL_GAIN),
        (Phase.GLIDE, MIN_GLIDE_SECONDS, lambda dz, dt: True),
        (Phase.DIVE, MIN_DIVE_SECONDS, lambda dz, dt: dz / dt < MAX_DIVE_CLIMB),
    ):
        for start, stop in _runs(phases == phase.value):
            duration = series.t[stop - 1] - series.t[start]
            dz = series.alt[stop - 1] - series.alt[start]
            if duration >= minimum and test(dz, max(duration, 1)):
                segments.append(_segment(flight, series, phase, start, stop))
    segments.sort(key=lambda s: s.start)
    # Offer the launch climb for judgement, then take it back unless it was a tow: a
    # straight climb that is not a tow is not a phase at all, it is transition time.
    candidate = _launch_climb(flight, series, segments)
    overlapped: list[Segment] = []
    if candidate is not None:
        overlapped = [s for s in segments
                      if s.start < candidate.stop and candidate.start < s.stop]
        segments.append(candidate)
        segments.sort(key=lambda s: s.start)
    _reclassify_tow(series, segments)
    if candidate is not None:
        if candidate.phase is Phase.TOW:
            # The tow won, so the turny fragments inside it are not separate climbs.
            for segment in overlapped:
                segments.remove(segment)
        else:
            segments.remove(candidate)

    accounted = dict.fromkeys((Phase.THERMAL, Phase.GLIDE, Phase.DIVE, Phase.TOW), 0)
    for segment in segments:
        accounted[segment.phase] += segment.duration
    total = int(series.t[-1])
    budget = TimeBudget(
        thermalling=accounted[Phase.THERMAL],
        gliding=accounted[Phase.GLIDE],
        diving=accounted[Phase.DIVE],
        towing=accounted[Phase.TOW],
        other=max(total - sum(accounted.values()), 0),
    )

    # Flight-level wind: average the per-thermal estimates, weighted by confidence
    # and by how long each thermal was circled. Only count climbs that were
    # actually circled in one direction for at least two full turns — drift only
    # measures the air if the glider's own airspeed has averaged out, which a tow,
    # a straight climb or a scratchy S-turn does not do.
    coarse = sample_interval(series) > TURN_RESOLUTION_LIMIT
    winds = [
        (s.wind, s.duration)
        for s in segments
        if s.phase is Phase.THERMAL
        and s.wind
        # Where turns could be counted, insist on a properly circled climb. Where the
        # sampling was too coarse to count them, drift over a few minutes is still a
        # valid measure of the air, so fall back to a duration test.
        and (
            (s.turns or 0) >= 2 and s.turn_direction in ("left", "right")
            if not coarse
            else s.duration >= 120
        )
    ]
    overall = None
    if winds:
        weights = np.array([w.confidence * d for w, d in winds])
        if weights.sum() > 0:
            vectors = np.array(
                [[w.speed * np.sin(np.radians(w.direction)), w.speed * np.cos(np.radians(w.direction))]
                 for w, _ in winds]
            )
            mean = (vectors * weights[:, None]).sum(axis=0) / weights.sum()
            speed = float(np.hypot(*mean))
            direction = float(np.degrees(np.arctan2(mean[0], mean[1])) % 360)
            overall = Wind(speed, direction, geo.cardinal(direction), float(weights.mean() / weights.max()))

    return Analysis(
        flight=flight,
        series=series,
        summary=_summary(flight, series),
        segments=segments,
        budget=budget,
        wind=overall,
        climb_histogram=_climb_histogram(series, phases),
    )

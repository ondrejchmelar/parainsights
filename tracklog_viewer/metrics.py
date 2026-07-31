"""Tier-1 measurements over an :class:`~tracklog_viewer.analysis.Analysis`.

Everything here is a pass over `list[Segment]` and `Series` — no new inputs, no network,
no payload growth. `debrief.py` turns these numbers into sentences; nothing in this
module knows about HTML, and nothing in it decides whether a number is worth printing.

Two rules from `docs/analysis-plan.md` are enforced here rather than left to the caller:

* **A measurement that cannot be supported is `None`, never a plausible number.** Every
  function that rests on turn statistics checks `TURN_RESOLUTION_LIMIT` itself, so a
  500-point KMZ from a scoring site gets a refusal rather than a confident wrong answer.
* **Nothing here is a counterfactual.** Where the honest measurement is two numbers side
  by side ("left at 3 656 m, 118 m under the day's best") that is what is returned; the
  question "what would the abandoned climb have given" is not answerable from a tracklog
  and is not asked.
"""

from dataclasses import dataclass

import numpy as np

from .analysis import (
    GLIDE_PROGRESS,
    TURN_RESOLUTION_LIMIT,
    Analysis,
    Phase,
    sample_interval,
)

# A glide has to last this long before its ratio means anything about the wing. Rodella's
# best glide reads 116.2 — a "glide" that crossed lift. That is why no L/D finding uses a
# maximum, and why the median below is taken over glides long enough to average out.
MIN_GLIDE_FOR_LD = 60.0  # seconds
# A climb has to run this long before the first minute can be compared with the rest of
# it: on a 90 s climb "the rest" is 30 s and the ratio is noise.
MIN_CLIMB_FOR_CENTRING = 120.0  # seconds
CENTRING_WINDOW = 60.0  # seconds
# How much a climb has to gain before it counts as a save worth retelling.
MIN_SAVE_GAIN = 300.0  # metres


def _thermal_mask(analysis: Analysis) -> np.ndarray:
    mask = np.zeros(len(analysis.series), dtype=bool)
    for segment in analysis.segments:
        if segment.phase is Phase.THERMAL:
            mask[segment.start : segment.stop] = True
    return mask


def _gaps(analysis: Analysis) -> np.ndarray:
    """Seconds between consecutive fixes; the weight for every time-weighted mean here."""
    return np.diff(analysis.series.t)


# ---------------------------------------------------------------------------
# The four corrections (docs/analysis-plan.md, "Four corrections")
# ---------------------------------------------------------------------------


@dataclass
class StraightAir:
    """How much of the *straight* flying was done in rising air, and what it was worth.

    Correction 2. Measuring this inside `Phase.GLIDE` gives 8% on Rodella and 5% on the
    flatland day — implausibly low for two good XC days, and for the same reason the
    `other` slice nets positive: the good bits were reclassified out of the glide. So the
    metric is defined over **all straight flight**, glides and unclassified alike, and
    reports the two halves separately because the split is the interesting part.
    """

    seconds: int
    rising_seconds: int
    rising_gain: float  # metres gained in the rising portions
    gain_in_glides: float
    gain_outside_glides: float

    @property
    def rising_fraction(self) -> float:
        return self.rising_seconds / self.seconds if self.seconds else 0.0


def straight_air(analysis: Analysis) -> StraightAir | None:
    """Rising air met while flying straight, wherever it was met."""
    steps = _gaps(analysis)
    if not steps.size:
        return None
    series = analysis.series
    straight = series.progress[:-1] >= GLIDE_PROGRESS
    if not straight.any():
        return None

    in_glide = np.zeros(len(steps), dtype=bool)
    for segment in analysis.segments:
        if segment.phase is Phase.GLIDE:
            in_glide[segment.start : max(segment.stop - 1, segment.start)] = True

    dz = np.diff(series.alt)
    rising = straight & (series.climb[:-1] > 0.0)
    return StraightAir(
        seconds=int(round(float(steps[straight].sum()))),
        rising_seconds=int(round(float(steps[rising].sum()))),
        rising_gain=round(float(dz[rising].sum())),
        gain_in_glides=round(float(dz[rising & in_glide].sum())),
        gain_outside_glides=round(float(dz[rising & ~in_glide].sum())),
    )


def cross_country_speed(analysis: Analysis, route) -> float | None:
    """Achieved cross-country speed, km/h, over the **scored** route.

    Correction 3. `summary.straight_distance` is take-off to landing, which on a triangle
    is nearly zero — it reads 0.5 km/h on Rodella, a flight that scored 48.64 km FAI. So
    the distance is the route's, and with no route there is no speed rather than a wrong
    one.
    """
    if route is None or not getattr(route, "distance", 0) or not analysis.summary.duration:
        return None
    return round(3.6 * route.distance / analysis.summary.duration, 1)


def glide_ratio_median(analysis: Analysis) -> float | None:
    """Median glide ratio over glides long enough to mean something.

    Correction 4. Never a maximum: the best glide on Rodella reads 116.2, which is not a
    measurement of the wing but of a glide that crossed lift. `airmass.py` corrects this
    for the wind; uncorrected it is still a ratio over the ground, and the finding that
    uses it says so.
    """
    ratios = [
        s.average_ld
        for s in analysis.glides
        if s.average_ld is not None and s.duration >= MIN_GLIDE_FOR_LD
    ]
    return round(float(np.median(ratios)), 1) if ratios else None


# ---------------------------------------------------------------------------
# Tier 1
# ---------------------------------------------------------------------------


@dataclass
class ClimbSelection:
    """Time spent circling in climbs well under what the day was offering."""

    weak_seconds: int
    total_seconds: int
    threshold: float  # half the day's best climb
    best: float  # the day's best climb, m/s
    weak_climbs: int

    @property
    def fraction(self) -> float:
        return self.weak_seconds / self.total_seconds if self.total_seconds else 0.0


def climb_selection(analysis: Analysis) -> ClimbSelection | None:
    """How much of the circling was done in the day's weaker half."""
    thermals = [s for s in analysis.thermals if s.duration > 0]
    if len(thermals) < 3:
        return None
    best = max(s.average_climb for s in thermals)
    if best <= 0:
        return None
    threshold = best / 2
    weak = [s for s in thermals if s.average_climb < threshold]
    return ClimbSelection(
        weak_seconds=sum(s.duration for s in weak),
        total_seconds=sum(s.duration for s in thermals),
        threshold=round(threshold, 2),
        best=round(best, 2),
        weak_climbs=len(weak),
    )


@dataclass
class WorkingBand:
    """Climb rate by altitude third — where in the column the lift actually was."""

    edges: tuple[float, float, float, float]  # the four altitudes bounding three bands
    climbs: tuple[float, float, float]  # mean climb in each, m/s
    seconds: tuple[int, int, int]

    @property
    def best(self) -> int:
        return int(np.argmax(self.climbs))

    @property
    def worst(self) -> int:
        return int(np.argmin(self.climbs))


def working_band(analysis: Analysis) -> WorkingBand | None:
    """Split the thermalling altitude range into thirds and measure each.

    The point is the shape, not the average: on Rodella the middle band gave 1.36 and the
    top 588 m gave 0.85 for 24 minutes of circling, which is a different flight from the
    one "mean climb +1.04" describes.
    """
    mask = _thermal_mask(analysis)[:-1]
    steps = _gaps(analysis)
    if not steps.size or not mask.any():
        return None
    alt = analysis.series.alt[:-1][mask]
    low, high = float(alt.min()), float(alt.max())
    if high - low < 100.0:
        return None

    edges = np.linspace(low, high, 4)
    dz = np.diff(analysis.series.alt)[mask]
    weights = steps[mask]
    climbs, seconds = [], []
    for i in range(3):
        lo, hi = edges[i], edges[i + 1]
        band = (alt >= lo) & (alt <= hi if i == 2 else alt < hi)
        held = float(weights[band].sum())
        climbs.append(round(float(dz[band].sum()) / held, 2) if held else 0.0)
        seconds.append(int(round(held)))
    return WorkingBand(
        edges=tuple(round(float(e)) for e in edges),
        climbs=tuple(climbs),
        seconds=tuple(seconds),
    )


@dataclass
class Centring:
    """The first minute of a climb against the rest of it."""

    ratio: float
    first: float  # m/s over the first CENTRING_WINDOW
    rest: float  # m/s over the remainder
    climbs: int
    cost_seconds: int  # what the shortfall cost, in seconds of circling


def centring(analysis: Analysis) -> Centring | None:
    """How much worse the first minute of a climb was than the rest of it.

    Gated at `TURN_RESOLUTION_LIMIT` with everything else that reasons about circling: at
    15 s sampling a 60 s window is four fixes.
    """
    if sample_interval(analysis.series) > TURN_RESOLUTION_LIMIT:
        return None
    series = analysis.series
    first_gain = first_time = rest_gain = rest_time = 0.0
    counted = 0
    for segment in analysis.thermals:
        if segment.duration < MIN_CLIMB_FOR_CENTRING:
            continue
        t = series.t[segment.start : segment.stop]
        alt = series.alt[segment.start : segment.stop]
        split = t[0] + CENTRING_WINDOW
        edge = float(np.interp(split, t, alt))
        first_gain += edge - float(alt[0])
        first_time += CENTRING_WINDOW
        rest_gain += float(alt[-1]) - edge
        rest_time += float(t[-1]) - split
        counted += 1
    if counted < 3 or first_time <= 0 or rest_time <= 0:
        return None

    first, rest = first_gain / first_time, rest_gain / rest_time
    if rest <= 0:
        return None
    # The cost is time, and it is a measurement rather than a counterfactual about the
    # air: the first minutes gained `first_gain`, which at the rate the *same climbs*
    # went on to give would have taken this much less circling.
    cost = first_time - (first_gain / rest if first_gain > 0 else 0.0)
    return Centring(
        ratio=round(first / rest, 2),
        first=round(first, 2),
        rest=round(rest, 2),
        climbs=counted,
        cost_seconds=int(round(max(cost, 0.0))),
    )


@dataclass
class ClimbGaps:
    """The stretches between one climb and the next."""

    median: int
    longest: int
    longest_at: str
    longest_loss: float
    longest_index: int  # fix where the longest gap starts, so a card can link to it


def climb_gaps(analysis: Analysis) -> ClimbGaps | None:
    """Time between the end of one climb and the start of the next.

    The comparison is the day's own median rather than a constant — an eight-minute gap is
    unremarkable on a day whose median is seven and the story of the flight on a day whose
    median is three.
    """
    thermals = sorted(analysis.thermals, key=lambda s: s.start)
    if len(thermals) < 3:
        return None
    series = analysis.series
    gaps = []
    for before, after in zip(thermals, thermals[1:]):
        seconds = float(series.t[after.start] - series.t[before.stop - 1])
        if seconds <= 0:
            continue
        loss = float(series.alt[after.start] - series.alt[before.stop - 1])
        gaps.append((seconds, loss, before.finish_time, before.stop - 1))
    if len(gaps) < 2:
        return None

    longest = max(gaps, key=lambda g: g[0])
    return ClimbGaps(
        median=int(round(float(np.median([g[0] for g in gaps])))),
        longest=int(round(longest[0])),
        longest_at=longest[2],
        longest_loss=round(longest[1]),
        longest_index=int(longest[3]),
    )


@dataclass
class Concentration:
    """How much of the day's height came from how few climbs."""

    share: float
    top: int
    total_gain: float
    climbs: int


def concentration(analysis: Analysis, *, top: int = 3) -> Concentration | None:
    """Share of the total climbing done by the best few climbs — a fragility measure."""
    gains = sorted(
        (s.altitude_change for s in analysis.thermals if s.altitude_change > 0), reverse=True
    )
    if len(gains) <= top:
        return None
    total = float(sum(gains))
    if total <= 0:
        return None
    return Concentration(
        share=round(float(sum(gains[:top])) / total, 2),
        top=top,
        total_gain=round(total),
        climbs=len(gains),
    )


@dataclass
class DayEnvelope:
    """Climb rate against the hour of the flight: was the day building or decaying."""

    slope: float  # m/s per hour
    first: float  # fitted climb at the first thermal
    last: float  # fitted climb at the last
    climbs: int
    hours: float


def day_envelope(analysis: Analysis) -> DayEnvelope | None:
    """Fit the day's trend through the climbs.

    This is what makes a late turnpoint decision legible: "the day was decaying at
    0.17 m/s per hour by the time you turned for home" is a measurement about the day, and
    it is the half of that sentence the tool can actually supply.
    """
    thermals = [s for s in analysis.thermals if s.duration > 0]
    if len(thermals) < 4:
        return None
    series = analysis.series
    hours = np.array([float(series.t[s.start]) / 3600.0 for s in thermals])
    climbs = np.array([s.average_climb for s in thermals])
    span = float(hours[-1] - hours[0])
    if span < 1.0:
        return None  # too short a flight for a trend to mean anything

    slope, intercept = np.polyfit(hours, climbs, 1, w=np.array([s.duration for s in thermals]))
    return DayEnvelope(
        slope=round(float(slope), 2),
        first=round(float(slope * hours[0] + intercept), 2),
        last=round(float(slope * hours[-1] + intercept), 2),
        climbs=len(thermals),
        hours=round(span, 1),
    )


@dataclass
class Detour:
    """Track distance against scored distance."""

    ratio: float
    track_km: float
    scored_km: float


def detour(analysis: Analysis, route) -> Detour | None:
    """How far was flown to score what was scored. Both numbers are already on the page."""
    if route is None or not getattr(route, "distance", 0):
        return None
    scored = route.distance
    track = analysis.summary.track_distance
    if scored <= 0 or track <= 0:
        return None
    return Detour(
        ratio=round(track / scored, 2),
        track_km=round(track / 1000.0, 1),
        scored_km=round(scored / 1000.0, 2),
    )


@dataclass
class LowestSave:
    """The lowest point the flight climbed away from."""

    gain: float
    from_agl: float
    from_altitude: float
    at: str


def lowest_save(analysis: Analysis, clearance) -> LowestSave | None:
    """The number pilots retell — and it is meaningless without terrain.

    2 051 m on Rodella is a ridge top, not a save. So this is height **above ground**, and
    without `--terrain` it does not exist rather than being quietly computed from altitude.
    """
    if clearance is None:
        return None
    agl = np.asarray(clearance, dtype=float)
    if agl.size != len(analysis.series):
        return None

    saves = [
        s
        for s in analysis.thermals
        if s.altitude_change >= MIN_SAVE_GAIN and np.isfinite(agl[s.start])
    ]
    if not saves:
        return None
    best = min(saves, key=lambda s: float(agl[s.start]))
    return LowestSave(
        gain=round(best.altitude_change),
        from_agl=round(float(agl[best.start])),
        from_altitude=best.start_altitude,
        at=best.start_time,
    )


@dataclass
class CeilingUse:
    """Where the flight topped out against what the day offered."""

    reached: float
    ceiling: float
    fraction: float
    source: str  # "cloudbase" or "thermal_top"


def ceiling_use(analysis: Analysis, weather) -> CeilingUse | None:
    """Topped at 3 774 of a 3 954 m cloudbase = 95%. Refused without `--meteo`."""
    if weather is None:
        return None
    ceiling, source = None, ""
    for name in ("cloudbase", "thermal_top"):
        value = getattr(weather, name, None)
        if callable(value):
            value = value()
        if value:
            ceiling, source = float(value), name
            break
    if not ceiling or ceiling <= 0:
        return None
    reached = float(analysis.summary.max_altitude)
    return CeilingUse(
        reached=round(reached),
        ceiling=round(ceiling),
        fraction=round(reached / ceiling, 2),
        source=source,
    )

"""The debrief: measurements over the analysis, ranked into findings.

Two layers, and the split matters.

`measure()` is arithmetic. It runs over `list[Segment]` and `Series` — no new inputs, no
network — and returns `Metrics`, a bag of plain numbers with no opinion in them. Every
number in it is checkable against the flight.

`findings()` is judgement, and it is deliberately constrained. **A finding is a
measurement plus a link, never an imperative**: past tense, about this flight, no
"should". The tool cannot see the sky, the gaggle, the airspace or the pilot's plan, so
advice from it is wrong often enough to poison the numbers around it. Two rules keep the
list short and honest:

- **Every finding carries a cost**, in metres or minutes. A finding with no cost does not
  ship — that is what stops the list becoming twelve items of trivia.
- **A finding must not fire on data that cannot support it.** Turn-derived findings are
  gated at `TURN_RESOLUTION_LIMIT`, height-above-ground findings need `--terrain`, ceiling
  findings need `--meteo`. Absent, the finding does not exist; it is not an empty card.

Ranking needs one currency, and the flight supplies it: metres divided by the day's own
mean climb are the seconds it took to get them back. So a cost in metres and a cost in
minutes are comparable *on this day* without importing a constant from anywhere.
"""

from dataclasses import dataclass, field

import numpy as np

from . import geo
from .analysis import (
    Analysis,
    GLIDE_PROGRESS,
    MIN_GLIDE_SECONDS,
    MIN_THERMAL_GAIN,
    MIN_THERMAL_SECONDS,
    Phase,
    Segment,
    TURN_RESOLUTION_LIMIT,
    TURNING_THRESHOLD,
    sample_interval,
)

# Every number a finding tests against, in one place. Serialised into the report so
# `quicklook.py` can read the same values instead of holding a second copy of them —
# the documented gap is that the browser side duplicates thresholds with no shared
# source, and this is the cheap half of closing it.
THRESHOLDS = {
    # Analysis constants the browser side re-implements.
    "glide_progress": GLIDE_PROGRESS,
    "min_thermal_seconds": MIN_THERMAL_SECONDS,
    "min_thermal_gain": MIN_THERMAL_GAIN,
    "min_glide_seconds": MIN_GLIDE_SECONDS,
    "turning_threshold": TURNING_THRESHOLD,
    "turn_resolution_limit": TURN_RESOLUTION_LIMIT,
    # The debrief's own. Every one of these was set from the distribution over the 50
    # sample flights rather than from a round number that sounded right: the rule is
    # that a finding firing on more than a third of flights is a constant, not a
    # finding, and the first pass had three of them over 70%. `tests/test_debrief.py`
    # pins the rates that came out of the tuning.
    "weak_climb_share": 0.5,      # "weak" is under half the day's best climb
    "weak_share_fires": 0.65,     # …and the card needs two thirds of the circling in them
    "centring_window": 60.0,      # seconds of a climb that count as finding it
    "centring_ratio": 0.75,       # below this the first minute is worth reporting
    "gap_excess": 3.0,            # a gap this many times the day's median is expensive
    "gap_minimum": 900.0,         # …and no gap under a quarter of an hour is expensive
    "low_clearance": 200.0,       # metres AGL: under this the flight was not going far
    "save_gain": 300.0,           # a climb this big from low is a save
    "other_share": 0.25,          # unclassified time worth decomposing on the page
    "concentration_share": 0.6,   # gain from the best three climbs, above this is fragile
    "envelope_decay": 0.20,       # m/s per hour of decay worth naming
    "detour_ratio": 2.0,          # track flown over scored distance
    "ceiling_used": 0.85,         # share of cloudbase reached
    "close_share": 0.2,           # XContest's closing rule, for the close that wasn't
    "band_advantage": 0.70,       # m/s between the best and worst altitude third
    "left_below": 150.0,          # metres under the day's best height before it counts
    "wind_glide_share": 0.30,     # relative gap between the ground and air glide ratios
    "min_cost_seconds": 120.0,    # below this a finding is trivia and is dropped
    "max_findings": 5,
}


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------


def _weights(t: np.ndarray) -> np.ndarray:
    """Seconds attributable to each sample, summing to the flight's duration.

    Midpoint weights rather than a forward difference: a forward difference charges the
    last sample nothing and biases every time share by one interval, which shows up as
    the decomposition below failing to sum to the slice it decomposes.
    """
    if len(t) < 2:
        return np.zeros_like(t)
    edges = np.empty(len(t) + 1)
    edges[1:-1] = (t[1:] + t[:-1]) / 2
    edges[0], edges[-1] = t[0], t[-1]
    return np.diff(edges)


@dataclass
class OtherTime:
    """The unclassified slice of the time budget, decomposed into three parts.

    Publishing `other` as a loss would have been the report's first confidently wrong
    sentence. Measured on the reference flight it is **profitable** — +385 m net, 56% of
    its samples rising — because the thermal rule pushes the straight run-in to a climb
    and the straight exit out of the phase on purpose. The slice is bimodal, so it gets
    three names and three different stories: straight sink is the price of the glide,
    scratching is the price of being low, and rising-uncounted is mostly ridge and street
    flying that the phase model has no name for.
    """

    seconds: int
    straight_sink: int
    scratching: int
    rising: int
    net_height: float      # metres gained or lost over the whole slice
    rising_height: float   # metres gained in the rising part alone
    sinking_height: float  # metres lost in the other two

    @property
    def rising_share(self) -> float:
        return self.rising / self.seconds if self.seconds else 0.0


@dataclass
class Gap:
    """The stretch between the end of one climb and the start of the next."""

    seconds: int
    height: float          # metres, negative when the gap cost height
    start_time: str
    index: int             # fix index where the gap began


@dataclass
class Band:
    """Climbing measured in one third of the height the flight used."""

    low: float
    high: float
    seconds: int
    rate: float            # m/s, height gained over time circling in the band


@dataclass
class Metrics:
    """Everything the debrief measures. Plain numbers; no judgement, no strings.

    Fields are `None` where the flight cannot support them — a coarse KMZ has no turn
    statistics, a flight without `--terrain` has no clearance, one without `--meteo` has
    no ceiling. Consumers check rather than defaulting, because a default here becomes a
    confident wrong number on the page.
    """

    coarse: bool
    airtime: int
    mean_climb: float                       # m/s over all thermalling
    best_climb: float                       # m/s, the day's strongest climb
    other: OtherTime
    # Climb selection
    weak_seconds: int = 0
    weak_rate: float = 0.0
    strong_seconds: int = 0
    strong_rate: float = 0.0
    # The working band: the flight's height range in thirds
    bands: list[Band] = field(default_factory=list)
    # Centring: mean climb over the first minute of a climb, over the rest
    centring: float | None = None
    centring_climbs: int = 0
    centring_height: float = 0.0            # metres the first minutes gave up
    # Gaps between climbs
    gaps: list[Gap] = field(default_factory=list)
    gap_median: float | None = None
    longest_gap: Gap | None = None
    # Concentration and shape of the day
    concentration: float | None = None      # share of gain from the best three climbs
    envelope: float | None = None           # m/s per hour, negative when decaying
    envelope_first: float | None = None
    envelope_last: float | None = None
    # Straight flight, which is where dolphin flying lives — not `Phase.GLIDE`
    straight_seconds: int = 0
    lift_seconds: int = 0
    lift_height: float = 0.0
    median_ld: float | None = None
    # Route-derived
    detour: float | None = None
    xc_speed: float | None = None
    closing_distance: float | None = None   # metres still to close a triangle
    # Terrain-derived
    min_clearance: float | None = None
    min_clearance_index: int | None = None
    low_seconds: int = 0                    # time under THRESHOLDS["low_clearance"]
    save_gain: float | None = None
    save_agl: float | None = None
    save_index: int | None = None
    # Meteo-derived
    ceiling: float | None = None            # metres, the day's cloudbase
    ceiling_used: float | None = None       # share of it reached
    best_index: int | None = None           # fix index of the day's strongest climb
    # Air-frame, from `airmass.py`. All None when the wind is too weak to correct with,
    # which is the case the whole module exists to keep off the page.
    air_ld: float | None = None
    airspeed: float | None = None
    wind_confidence: float | None = None
    wander: float | None = None
    wander_climbs: int = 0
    glide_distance: float = 0.0             # metres flown in glides, for the wind cost


def _climb_rate(segments: list[Segment]) -> float:
    """Height gained over time spent, across a set of climbs."""
    seconds = sum(s.duration for s in segments)
    if not seconds:
        return 0.0
    return sum(s.altitude_change for s in segments) / seconds


def _decompose_other(analysis: Analysis) -> OtherTime:
    """Split the unclassified time three ways: straight sink, scratching, rising."""
    series = analysis.series
    covered = np.zeros(len(series), dtype=bool)
    for segment in analysis.segments:
        covered[segment.start:segment.stop] = True
    rest = ~covered
    weights = _weights(series.t)

    rising = rest & (series.climb > 0)
    straight = rest & (series.climb <= 0) & (series.progress >= GLIDE_PROGRESS)
    scratch = rest & (series.climb <= 0) & (series.progress < GLIDE_PROGRESS)

    def height(mask: np.ndarray) -> float:
        return float((series.climb[mask] * weights[mask]).sum())

    return OtherTime(
        seconds=int(round(weights[rest].sum())),
        straight_sink=int(round(weights[straight].sum())),
        scratching=int(round(weights[scratch].sum())),
        rising=int(round(weights[rising].sum())),
        net_height=round(height(rest)),
        rising_height=round(height(rising)),
        sinking_height=round(height(straight) + height(scratch)),
    )


def _bands(analysis: Analysis) -> list[Band]:
    """Climb rate in each third of the height the flight used.

    The working band, measured. On the reference flight the top 588 m returned 0.85 m/s
    for 24 minutes of circling where the middle third gave 1.36 — which is the shape of
    a day that caps out, and is invisible in a single mean climb rate.
    """
    series = analysis.series
    thermalling = np.zeros(len(series), dtype=bool)
    for segment in analysis.thermals:
        thermalling[segment.start:segment.stop] = True
    if not thermalling.any():
        return []
    weights = _weights(series.t)
    low, high = float(series.alt.min()), float(series.alt.max())
    if high - low < 300:
        return []
    edges = np.linspace(low, high, 4)
    bands = []
    for a, b in zip(edges, edges[1:]):
        inside = thermalling & (series.alt >= a) & (series.alt < b + (b == edges[-1]))
        seconds = float(weights[inside].sum())
        if seconds < 60:
            continue
        gained = float((series.climb[inside] * weights[inside]).sum())
        bands.append(Band(round(a), round(b), int(round(seconds)), gained / seconds))
    return bands


def _centring(analysis: Analysis, window: float) -> tuple[float | None, int, float]:
    """Mean climb over the first ``window`` seconds of each climb, against the rest.

    Below 1.0 the pilot spent the opening of their climbs finding it. The cost is the
    height those opening minutes gave up against the rate the same thermal went on to
    prove it had — which is a comparison inside one climb, not a counterfactual about a
    climb that was left.
    """
    ratios, cost = [], 0.0
    for segment in analysis.thermals:
        if segment.duration < 2 * window:
            continue
        t = analysis.series.t
        split = t[segment.start] + window
        cut = int(np.searchsorted(t[segment.start:segment.stop], split)) + segment.start
        if cut <= segment.start or cut >= segment.stop - 1:
            continue
        alt = analysis.series.alt
        first = (alt[cut] - alt[segment.start]) / (t[cut] - t[segment.start])
        rest = (alt[segment.stop - 1] - alt[cut]) / (t[segment.stop - 1] - t[cut])
        if rest <= 0:
            continue
        ratios.append(first / rest)
        cost += max(rest - first, 0.0) * (t[cut] - t[segment.start])
    if not ratios:
        return None, 0, 0.0
    return float(np.mean(ratios)), len(ratios), round(cost)


def _gaps(analysis: Analysis) -> list[Gap]:
    """The stretches between climbs: how long, and what they cost in height."""
    climbs = [s for s in analysis.segments if s.phase in (Phase.THERMAL, Phase.TOW)]
    series, flight = analysis.series, analysis.flight
    gaps = []
    for previous, following in zip(climbs, climbs[1:]):
        start, stop = previous.stop - 1, following.start
        if stop <= start:
            continue
        seconds = int(series.t[stop] - series.t[start])
        if seconds < 60:
            continue
        gaps.append(Gap(
            seconds=seconds,
            height=round(float(series.alt[stop] - series.alt[start])),
            start_time=flight.local_time(start).strftime("%H:%M:%S"),
            index=start,
        ))
    return gaps


def _envelope(analysis: Analysis) -> tuple[float | None, float | None, float | None]:
    """Climb rate regressed on the hour of the flight: is the day building or decaying?

    Weighted by how long each climb was circled, because a 9-minute climb is better
    evidence about the air than a 70-second one. Needs four climbs spread over more than
    an hour before the slope means anything.
    """
    climbs = analysis.thermals
    if len(climbs) < 4:
        return None, None, None
    t = analysis.series.t
    hours = np.array([(t[s.start] + t[s.stop - 1]) / 7200 for s in climbs])
    rates = np.array([s.average_climb for s in climbs])
    weights = np.array([s.duration for s in climbs], dtype=float)
    if hours.max() - hours.min() < 1.0:
        return None, None, None
    # `np.polyfit`'s weights multiply the residual, so passing seconds directly weights
    # by the *square* of the climb's duration and lets one long thermal set the slope —
    # on the flatland flight that read −0.59 m/s/h against −0.17 for the same climbs.
    slope, intercept = np.polyfit(hours, rates, 1, w=np.sqrt(weights))
    return (
        round(float(slope), 3),
        round(float(intercept + slope * hours.min()), 2),
        round(float(intercept + slope * hours.max()), 2),
    )


def _straight_flight(analysis: Analysis) -> tuple[int, int, float]:
    """Time and height in rising air over *all* straight flight, glides included.

    Measured inside `Phase.GLIDE` the share comes out at 5–8% on two good XC days, which
    is implausible and is an artefact: the rule that ends a glide when the air gives
    something back reclassifies the good bits out of the phase. Rodella's rising portions
    are worth +299 m inside glides and +385 m outside them, so the metric has to be
    defined over straight flight rather than over the glide phase.
    """
    series = analysis.series
    weights = _weights(series.t)
    straight = series.progress >= GLIDE_PROGRESS
    lift = straight & (series.climb > 0)
    return (
        int(round(weights[straight].sum())),
        int(round(weights[lift].sum())),
        round(float((series.climb[lift] * weights[lift]).sum())),
    )


def _median_ld(analysis: Analysis) -> float | None:
    """A median glide ratio over glides worth the name.

    Never a maximum. The best glide on the reference flight reads 116.2 — a "glide" that
    crossed lift, and not a measurement of the wing at all.
    """
    ratios = [
        s.average_ld for s in analysis.glides
        if s.average_ld and s.duration >= 60
    ]
    return round(float(np.median(ratios)), 1) if ratios else None


def _closing_distance(route) -> float | None:
    """How far the course was from closing, in metres, for a route that did not.

    Only meaningful for a route with turnpoints; a route that already closed returns
    None, as does one too short to have a shape.
    """
    if route is None or route.closed or len(route.points) < 3:
        return None
    first, last = route.points[0], route.points[-1]
    return float(geo.distance(first.lat, first.lon, last.lat, last.lon))


def measure(analysis: Analysis, *, meteo=None, route=None,
            clearance: np.ndarray | None = None, air=None) -> Metrics:
    """Every number the debrief can state, measured from what already exists."""
    series = analysis.series
    thermals = analysis.thermals
    weights = _weights(series.t)
    coarse = sample_interval(series) > TURN_RESOLUTION_LIMIT

    best = max(thermals, key=lambda s: s.average_climb) if thermals else None
    best_rate = best.average_climb if best else 0.0
    weak_cut = THRESHOLDS["weak_climb_share"] * best_rate
    weak = [s for s in thermals if s.average_climb < weak_cut]
    strong = [s for s in thermals if s.average_climb >= weak_cut]

    straight_seconds, lift_seconds, lift_height = _straight_flight(analysis)
    gaps = _gaps(analysis)
    centring, centring_climbs, centring_height = _centring(
        analysis, THRESHOLDS["centring_window"]
    )
    slope, first_rate, last_rate = _envelope(analysis)

    metrics = Metrics(
        coarse=coarse,
        airtime=analysis.summary.duration,
        mean_climb=round(_climb_rate(thermals), 2),
        best_climb=round(best_rate, 2),
        other=_decompose_other(analysis),
        weak_seconds=sum(s.duration for s in weak),
        weak_rate=round(_climb_rate(weak), 2),
        strong_seconds=sum(s.duration for s in strong),
        strong_rate=round(_climb_rate(strong), 2),
        bands=_bands(analysis),
        centring=None if coarse else centring,
        centring_climbs=0 if coarse else centring_climbs,
        centring_height=0.0 if coarse else centring_height,
        gaps=gaps,
        gap_median=float(np.median([g.seconds for g in gaps])) if gaps else None,
        longest_gap=max(gaps, key=lambda g: g.seconds) if gaps else None,
        straight_seconds=straight_seconds,
        lift_seconds=lift_seconds,
        lift_height=lift_height,
        median_ld=_median_ld(analysis),
        best_index=best.start if best else None,
    )

    # How much of the flight rested on how few climbs. A fragility measure, and it is
    # what frames the gap finding: a day carried by three climbs is a day where one
    # missed connection ends it.
    gains = sorted((s.altitude_change for s in thermals if s.altitude_change > 0),
                   reverse=True)
    if len(gains) >= 4 and sum(gains) > 0:
        metrics.concentration = round(sum(gains[:3]) / sum(gains), 2)
    metrics.envelope, metrics.envelope_first, metrics.envelope_last = (
        slope, first_rate, last_rate
    )

    if route is not None and route.distance > 0:
        metrics.detour = round(analysis.summary.track_distance / route.distance, 2)
        # Speed over the scored route, not take-off to landing: `straight_distance`
        # on a triangle is nearly zero and reads 0.5 km/h for a flight that scored
        # 48.64 km. The clock runs over the span of the route's points — min and max
        # rather than first and last, because `triangle()` repeats its first corner as
        # the closing point, so `points[-1]` is *earlier* than `points[0]`.
        indices = [p.index for p in route.points]
        span = float(series.t[max(indices)] - series.t[min(indices)])
        if span > 600:
            metrics.xc_speed = round(3.6 * route.distance / span, 1)
        metrics.closing_distance = _closing_distance(route)

    if clearance is not None and len(clearance) == len(series):
        low = int(np.argmin(clearance))
        metrics.min_clearance = round(float(clearance[low]))
        metrics.min_clearance_index = low
        metrics.low_seconds = int(round(
            weights[clearance < THRESHOLDS["low_clearance"]].sum()
        ))
        # The save: the biggest climb, judged by how low it started *above the ground*.
        # 2 051 m on an alpine flight is a ridge top, not a save, which is why this one
        # is refused without terrain rather than approximated from altitude.
        saves = [s for s in thermals if s.altitude_change >= THRESHOLDS["save_gain"]]
        if saves:
            save = min(saves, key=lambda s: float(clearance[s.start]))
            metrics.save_gain = save.altitude_change
            metrics.save_agl = round(float(clearance[save.start]))
            metrics.save_index = save.start

    if air is not None:
        metrics.wind_confidence = round(air.field.confidence, 2)
        metrics.airspeed = air.airspeed
        metrics.wander = air.wander
        metrics.wander_climbs = air.wander_climbs
        # Only when the field is trustworthy. `airmass` already refuses below its own
        # threshold and leaves `air_ld` as None; carrying that through rather than
        # substituting the ground figure is the point.
        metrics.air_ld = air.air_ld
        metrics.glide_distance = round(sum(s.distance for s in analysis.glides))

    if meteo is not None:
        offset = analysis.summary.baro_offset or 0
        top = analysis.summary.max_altitude + offset
        ceiling = meteo.thermal_top or meteo.cloudbase
        if ceiling and ceiling > 0:
            metrics.ceiling = round(float(ceiling))
            metrics.ceiling_used = round(top / ceiling, 2)

    return metrics


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """One ranked observation about the flight.

    `title` is the sentence a reader takes away, `detail` is the evidence under it, and
    `cost` is what it was worth in metres or minutes. `index` is a fix index, which is
    what "show me" drives — the linked cursor already connects the charts and the 3D
    view, so a finding only has to name the moment.
    """

    id: str
    title: str
    detail: str
    cost_value: float
    cost_unit: str            # "min" or "m"
    cost_seconds: float       # the ranking currency
    when: str | None = None
    index: int | None = None
    note: str | None = None   # what to distrust about this particular finding

    @property
    def cost(self) -> str:
        if self.cost_unit == "min":
            return f"{self.cost_value:.0f} min"
        return _m(self.cost_value)


def _num(value: float, sign: str = "") -> str:
    """A number with a space in the thousands.

    A helper rather than `.replace(",", " ")` on the finished sentence, which is what the
    rest of the renderer does: a finding is prose, and stripping commas out of prose
    silently unpunctuates it. Every long number here goes through this instead.
    """
    return f"{value:{sign},.0f}".replace(",", "&#8201;")


def _m(value: float, sign: str = "") -> str:
    return f"{_num(value, sign)}&nbsp;m"


def _seconds_for(metres: float, mean_climb: float) -> float:
    """Metres converted to the seconds this day's own climbs took to supply them.

    The one currency conversion in the module, and it is measured rather than assumed:
    a day of +0.5 m/s makes 100 m expensive, a day of +3 makes it cheap. Where there was
    no climbing to measure, fall back to a weak day rather than dividing by zero.
    """
    return abs(metres) / max(mean_climb, 0.3)


def _clock(analysis: Analysis, index: int | None) -> str | None:
    if index is None:
        return None
    return analysis.flight.local_time(index).strftime("%H:%M:%S")


def _minutes(seconds: float) -> str:
    return f"{seconds / 60:.0f} min"


def findings(analysis: Analysis, metrics: Metrics, *, meteo=None, route=None,
             shape: str = "") -> list[Finding]:
    """The flight's findings, ranked by cost, longest list first and then trimmed.

    Everything here is a sentence about a number in `metrics`. Nothing computes; nothing
    advises. A candidate that cannot state a cost, or whose cost is under
    `min_cost_seconds`, never reaches the page.

    **The detour ratio is deliberately not a card.** 121 km flown to score 48.64 km is
    2.49&#215;, and converting the difference at the flight's own glide values it at over
    9 000 m — which would top this list on every triangle ever flown, because a triangle
    has to be flown round and the circling is in the numerator. It is a real measurement
    with no honest cost, so it goes in the verdict strip as a figure and stays out of
    here, where the cost rule would make it the loudest thing on the page.
    """
    mean_climb = metrics.mean_climb
    out: list[Finding] = []

    def add(finding_id: str, title: str, detail: str, *, metres: float | None = None,
            seconds: float | None = None, index: int | None = None,
            note: str | None = None) -> None:
        if metres is not None:
            value, unit, rank = abs(metres), "m", _seconds_for(metres, mean_climb)
        elif seconds is not None:
            value, unit, rank = abs(seconds) / 60, "min", abs(seconds)
        else:
            return                       # no cost, no card
        if rank < THRESHOLDS["min_cost_seconds"]:
            return
        out.append(Finding(finding_id, title, detail, round(value), unit, rank,
                           when=_clock(analysis, index), index=index, note=note))

    _left_the_best(analysis, metrics, add)
    _expensive_gap(analysis, metrics, add)
    _low_point(analysis, metrics, add)
    _climb_selection(analysis, metrics, add)
    _working_band(analysis, metrics, add)
    _centring_finding(analysis, metrics, add)
    _the_close(analysis, metrics, add, route=route, shape=shape)
    _ceiling(analysis, metrics, add, meteo=meteo)
    _other_time(analysis, metrics, add)
    _the_save(analysis, metrics, add)
    _day_envelope(analysis, metrics, add)
    _the_wind_on_glides(analysis, metrics, add)

    out.sort(key=lambda f: f.cost_seconds, reverse=True)
    return out[: THRESHOLDS["max_findings"]]


# ---------------------------------------------------------------------------
# The verdict strip
# ---------------------------------------------------------------------------


@dataclass
class Figure:
    """One headline number, with the comparison that gives it a scale.

    `comparison` is filled in later by `compare()`, once the other flights in the
    document are known — a flight on its own has nothing to be better or worse than, and
    inventing a scale for it would be the first opinion in the report.
    """

    key: str
    value: str
    unit: str = ""
    sub: str = ""
    sort: float | None = None       # what `compare()` ranks on; higher is better
    comparison: str = ""


@dataclass
class Verdict:
    """The flight in one line, above everything else on the page."""

    sentence: str
    figures: list[Figure] = field(default_factory=list)


def verdict(analysis: Analysis, m: Metrics, *, route=None, shape: str = "",
            meteo=None) -> Verdict:
    """The flight stated as a sentence, then as three or four numbers.

    Every clause is a measurement. There is no adjective here that is not defined by a
    number next to it — "weak" would need an archive to mean anything, and until
    `baseline.py` exists the report does not have one.
    """
    summary = analysis.summary
    hours, minutes = summary.duration // 3600, summary.duration % 3600 // 60
    length = f"{hours} h {minutes:02d} m" if hours else f"{minutes} m"
    thermals = analysis.thermals

    opening = f"A {length} flight"
    if route is not None:
        opening += f", scored {route.km:.2f} km as {shape or 'open distance'}"
    opening += "."

    clauses = []
    if thermals:
        clauses.append(
            f"{len(thermals)} climbs averaged {m.mean_climb:+.2f} m/s, the best "
            f"{m.best_climb:+.2f}"
        )
    if m.envelope is not None and abs(m.envelope) >= THRESHOLDS["envelope_decay"]:
        clauses.append(
            f"the day was {'decaying' if m.envelope < 0 else 'building'} at "
            f"{abs(m.envelope):.2f} m/s per hour"
        )
    if m.closing_distance is not None and route is not None and len(route.points) >= 5:
        clauses.append(f"the course finished {m.closing_distance / 1000:.1f} km from closing")
    elif m.ceiling_used is not None:
        clauses.append(f"{m.ceiling_used * 100:.0f}% of the modelled ceiling was used")

    sentence = opening
    if clauses:
        # Upper-case the first letter only. `str.capitalize()` lower-cases everything
        # after it, which would quietly turn "FAI" into "fai" the first time a clause
        # carried one.
        joined = "; ".join(clauses)
        sentence += " " + joined[:1].upper() + joined[1:] + "."

    figures = [
        Figure("scored", f"{route.km:.2f}" if route else "—", " km",
               # The detour ratio, framed as what it cost to score that: two numbers
               # already on the page that were never put next to each other.
               f"{shape or 'open distance'} &middot; "
               f"{analysis.summary.track_distance / 1000:.0f} km flown, {m.detour:.1f}&#215;"
               if m.detour else (shape or "open distance"),
               sort=route.km if route else None),
        Figure("mean climb", f"{m.mean_climb:+.2f}", " m/s",
               f"best {m.best_climb:+.2f} &middot; {len(thermals)} climbs",
               sort=m.mean_climb),
        Figure("height gained", _num(summary.total_gain), " m",
               f"best single climb {_m(summary.max_gain)}",
               sort=float(summary.total_gain)),
    ]
    if m.ceiling_used is not None:
        figures.append(Figure(
            "ceiling used", f"{m.ceiling_used * 100:.0f}", "%",
            f"{_num(summary.max_altitude + (summary.baro_offset or 0))} of "
            f"{_m(m.ceiling)}",
            sort=m.ceiling_used,
        ))
    elif m.xc_speed is not None:
        figures.append(Figure(
            "xc speed", f"{m.xc_speed:.0f}", " km/h", "over the scored route",
            sort=m.xc_speed,
        ))
    return Verdict(sentence, figures)


def compare(verdicts: list[Verdict]) -> None:
    """Fill in each figure's comparison against the same figure on the other flights.

    The document holds several flights and never puts them side by side — free insight
    sitting on the table. Ranking is by key, so a document whose flights carry different
    figures (one with meteo, one without) simply compares the ones they share.
    """
    if len(verdicts) < 2:
        return
    by_key: dict[str, list[Figure]] = {}
    for one in verdicts:
        for figure in one.figures:
            if figure.sort is not None:
                by_key.setdefault(figure.key, []).append(figure)
    for group in by_key.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda f: f.sort, reverse=True)
        if group[0].sort == group[-1].sort:
            continue
        count = len(group)
        group[0].comparison = f"&#9650; best of the {count} here"
        group[-1].comparison = f"&#9660; lowest of the {count} here"
        for rank, figure in enumerate(group[1:-1], start=2):
            figure.comparison = f"{_ordinal(rank)} of the {count} here"


def _ordinal(n: int) -> str:
    return {1: "best", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def _left_the_best(analysis: Analysis, m: Metrics, add) -> None:
    """The day's strongest climb, and what came after leaving it.

    Two measurements and no counterfactual: where the climb was left against the day's
    own ceiling, and what the next one cost. What the abandoned climb *would* have given
    is not in the data and is not claimed.
    """
    thermals = analysis.thermals
    if len(thermals) < 3 or m.best_index is None:
        return
    best = next(s for s in thermals if s.start == m.best_index)
    ceiling = max(s.finish_altitude for s in thermals)
    below = ceiling - best.finish_altitude
    following = [s for s in thermals if s.start > best.stop]
    if not following or below < THRESHOLDS["left_below"]:
        return
    nxt = following[0]
    gap = int(analysis.series.t[nxt.start] - analysis.series.t[best.stop - 1])
    add(
        "left-the-best",
        f"Left the day&rsquo;s strongest climb {_m(below)} below the day&rsquo;s best height",
        f"Climb {thermals.index(best) + 1} ran at {best.average_climb:+.2f} m/s and it was "
        f"left at {_m(best.finish_altitude)}, against {_m(ceiling)} reached later in "
        f"the flight. The next climb took {_minutes(gap)} to find and averaged "
        f"{nxt.average_climb:+.2f} m/s.",
        seconds=gap,
        index=best.stop - 1,
    )


def _expensive_gap(analysis: Analysis, m: Metrics, add) -> None:
    """The longest stretch between two climbs, against the day's own median."""
    gap, median = m.longest_gap, m.gap_median
    if gap is None or median is None or len(m.gaps) < 3:
        return
    if gap.seconds < max(THRESHOLDS["gap_excess"] * median, THRESHOLDS["gap_minimum"]):
        return
    excess = gap.seconds - median
    add(
        "expensive-gap",
        f"{_minutes(gap.seconds)} between climbs at {gap.start_time[:5]}, "
        f"{_m(gap.height, '+')}",
        f"The day&rsquo;s median gap between climbs was {_minutes(median)}; this one ran "
        f"{_minutes(gap.seconds)} and cost {_m(abs(gap.height))}. That is "
        f"{gap.seconds / median:.1f}&#215; the day&rsquo;s own normal, measured on this "
        f"flight rather than against a constant.",
        seconds=excess,
        index=gap.index,
    )


def _low_point(analysis: Analysis, m: Metrics, add) -> None:
    """The lowest ground clearance of the flight — currently buried in a caption."""
    if m.min_clearance is None or m.min_clearance_index is None:
        return
    if m.low_seconds < 120:
        return
    # A negative clearance is the DEM's error, not the flight's — a 30 m grid cuts the
    # top off a ridge — so the headline is the time spent low, which is robust to it,
    # and the lowest reading is reported in the detail where it can be qualified.
    lowest = (
        f"the lowest reading is {_m(m.min_clearance)}"
        if m.min_clearance > 0
        else f"the lowest reading is {_m(m.min_clearance)}, which is the DEM cutting the "
             f"top off a ridge rather than the flight going underground"
    )
    add(
        "low-point",
        f"{_minutes(m.low_seconds)} were flown under "
        f"{THRESHOLDS['low_clearance']:.0f} m above the ground",
        f"Height above the DEM, not above sea level: {_minutes(m.low_seconds)} of "
        f"{_minutes(m.airtime)} under {THRESHOLDS['low_clearance']:.0f} m AGL, and "
        f"{lowest}, at {_clock(analysis, m.min_clearance_index)}.",
        seconds=m.low_seconds,
        index=m.min_clearance_index,
        note="Terrain is a public DEM, not a survey, and it knows nothing about "
             "fields, wires or trees.",
    )


def _climb_selection(analysis: Analysis, m: Metrics, add) -> None:
    """How much circling went into the day's weaker half of climbs."""
    if not m.weak_seconds or not m.strong_seconds:
        return
    total = m.weak_seconds + m.strong_seconds
    if m.weak_seconds / total < THRESHOLDS["weak_share_fires"]:
        return
    add(
        "climb-selection",
        f"{_minutes(m.weak_seconds)} of {_minutes(total)} circling was in the "
        f"day&rsquo;s weaker climbs",
        f"Climbs under {THRESHOLDS['weak_climb_share'] * m.best_climb:+.2f} m/s — half "
        f"the day&rsquo;s best of {m.best_climb:+.2f} — averaged {m.weak_rate:+.2f} m/s "
        f"across {_minutes(m.weak_seconds)}. The rest averaged {m.strong_rate:+.2f} m/s. "
        f"Both are measurements of the same day; which of them was available at the time "
        f"is not something the track can say.",
        seconds=m.weak_seconds,
    )


def _working_band(analysis: Analysis, m: Metrics, add) -> None:
    """Where in the height range the climbing actually paid."""
    if len(m.bands) < 3:
        return
    best = max(m.bands, key=lambda b: b.rate)
    worst = min(m.bands, key=lambda b: b.rate)
    if best.rate - worst.rate < THRESHOLDS["band_advantage"]:
        return
    if worst.seconds < 600:
        return          # a band with ten minutes in it is not a working band
    # What the time spent in the weakest band would have been worth at the best band's
    # rate. Both rates are measured on this flight; the difference is the cost.
    metres = worst.seconds * (best.rate - worst.rate)
    add(
        "working-band",
        f"The band {_num(best.low)}&ndash;{_m(best.high)} gave {best.rate:+.2f} m/s; "
        f"{_num(worst.low)}&ndash;{_m(worst.high)} gave {worst.rate:+.2f}",
        f"Circling time split into three equal slices of the height the flight used. "
        f"{_minutes(worst.seconds)} were spent circling in the weaker band and "
        f"{_minutes(best.seconds)} in the better one. The difference over that time is "
        f"{_m(metres)}.",
        metres=metres,
    )


def _centring_finding(analysis: Analysis, m: Metrics, add) -> None:
    """The opening minute of a climb against the rest of the same climb."""
    if m.centring is None or m.centring_climbs < 3:
        return
    if m.centring >= THRESHOLDS["centring_ratio"]:
        return
    add(
        "centring",
        f"The first minute of a climb averaged {m.centring * 100:.0f}% of what the rest "
        f"of it gave",
        f"Measured across {m.centring_climbs} climbs longer than two minutes: the "
        f"opening {THRESHOLDS['centring_window']:.0f} s against the remainder of the same "
        f"thermal. The difference over those openings is {_m(m.centring_height)} — a "
        f"comparison inside each climb, so it is not affected by which climbs were "
        f"chosen.",
        metres=m.centring_height,
    )


def _the_close(analysis: Analysis, m: Metrics, add, *, route, shape: str) -> None:
    """The close that wasn't: what closing the triangle would have been worth."""
    if route is None or m.closing_distance is None or len(route.points) < 5:
        return
    perimeter = route.distance
    if perimeter <= 0:
        return
    share = m.closing_distance / perimeter
    if share > 0.6:
        return                      # not a course that was ever close to closing
    add(
        "the-close",
        f"The course finished {m.closing_distance / 1000:.1f} km from closing, at "
        f"{share * 100:.0f}% of its own length",
        f"XContest closes a course when the finish lands within "
        f"{THRESHOLDS['close_share'] * 100:.0f}% of the distance flown "
        f"({perimeter * THRESHOLDS['close_share'] / 1000:.1f} km here), and a closed "
        f"triangle scores 1.2&#215; or 1.4&#215; its perimeter against 1.0 for open "
        f"distance. This one scored as {shape or 'open distance'}.",
        # The cost is the height it would have taken to fly the remaining distance at the
        # flight's own measured glide — not an assumed one.
        metres=(m.closing_distance / m.median_ld) if m.median_ld else None,
    )


def _ceiling(analysis: Analysis, m: Metrics, add, *, meteo) -> None:
    """How much of the day's ceiling the flight used."""
    if meteo is None or m.ceiling is None or m.ceiling_used is None:
        return
    tops = [s.finish_altitude for s in analysis.thermals]
    if len(tops) < 3:
        return
    offset = analysis.summary.baro_offset or 0
    mean_top = float(np.mean(tops)) + offset
    share = mean_top / m.ceiling
    if m.ceiling_used >= THRESHOLDS["ceiling_used"] and share >= 0.75:
        return                      # the ceiling was used; nothing to report
    add(
        "ceiling",
        f"Climbs were left at {share * 100:.0f}% of the day&rsquo;s modelled ceiling "
        f"on average",
        f"The sounding puts the useful top at {_m(m.ceiling)}; the flight&rsquo;s "
        f"highest point was {m.ceiling_used * 100:.0f}% of it and its climbs finished at "
        f"{_m(mean_top)} on average — {_m(m.ceiling - mean_top)} under it per climb.",
        # One climb's worth of unused ceiling, not that figure multiplied by the number
        # of climbs: the height is only available once per glide, and multiplying it
        # would put this card at the top of every capped day.
        metres=m.ceiling - mean_top,
        note="The ceiling is a model&rsquo;s analysis for a point near the course line, "
             "not a radiosonde. Treat it as &#177;100 m.",
    )


def _other_time(analysis: Analysis, m: Metrics, add) -> None:
    """The unclassified slice, decomposed rather than blamed."""
    other = m.other
    if other.seconds < 600:
        return
    share = other.seconds / max(m.airtime, 1)
    if share < THRESHOLDS["other_share"]:
        return
    add(
        "other-time",
        f"{_minutes(other.seconds)} were neither a climb nor a glide, and they netted "
        f"{_m(other.net_height, '+')}",
        f"{_minutes(other.straight_sink)} straight and sinking, "
        f"{_minutes(other.scratching)} turning without climbing, and "
        f"{_minutes(other.rising)} rising without being counted as a climb — the last of "
        f"those is worth {_m(other.rising_height, '+')} and is mostly the straight run-in "
        f"to a thermal, ridge lift and streets, which the phase model has no name for. "
        f"The losing part of the slice is {_m(abs(other.sinking_height))} over "
        f"{_minutes(other.straight_sink + other.scratching)}.",
        seconds=other.straight_sink + other.scratching,
    )


def _the_save(analysis: Analysis, m: Metrics, add) -> None:
    """The climb taken from lowest above the ground — the number pilots retell."""
    if m.save_gain is None or m.save_agl is None:
        return
    if m.save_agl > 400:
        return
    add(
        "the-save",
        f"A {_m(m.save_gain, '+')} climb from {_m(m.save_agl)} above the ground",
        f"Taken at {_clock(analysis, m.save_index)}. Height above the DEM, so it is the "
        f"save as flown rather than as read off an altimeter.",
        metres=m.save_gain,
        index=m.save_index,
        note="Reported as a measurement, not as a margin: the DEM is coarse and knows "
             "nothing about what was under the wing.",
    )


def _the_wind_on_glides(analysis: Analysis, m: Metrics, add) -> None:
    """What the day's wind was worth on the glides, in height.

    Only fires when the wind field is good enough to correct with — `airmass` leaves
    `air_ld` as None below its own confidence threshold, and this reads that rather than
    quietly substituting the ground figure. The difference is arithmetic on two measured
    ratios: the same glide distance at the two ratios is two heights, and the gap between
    them is what the air did.
    """
    if m.air_ld is None or m.median_ld is None or not m.glide_distance:
        return
    # On the *ratio*, relative — an absolute gap of half a point fires on three flights
    # in four, because subtracting the wind moves the number on almost every flight that
    # has any wind at all. What is worth a card is a correction big enough to change how
    # the glides read, and that is a fraction, not a difference.
    if abs(m.air_ld - m.median_ld) / max(m.air_ld, 1e-6) < THRESHOLDS["wind_glide_share"]:
        return
    metres = m.glide_distance * (1 / m.median_ld - 1 / m.air_ld)
    helped = metres < 0
    add(
        "wind-on-glides",
        f"Glides ran {m.median_ld:.1f} over the ground against {m.air_ld:.1f} through "
        f"the air",
        f"Over {m.glide_distance / 1000:.0f} km of glide, the difference between the two "
        f"ratios is {_m(abs(metres))} of height &mdash; "
        + ("gained from the air the glides were flown in"
           if helped else "spent on the air the glides were flown in") + ". "
        f"The air-frame ratio subtracts an interpolated wind field built from "
        f"{'the day&rsquo;s circled climbs' if m.wind_confidence else 'the model'}, "
        f"at confidence {m.wind_confidence:.2f}.",
        metres=metres,
        note="Airspeed is inferred, not measured: no file in the sample set records it, "
             "so every through-the-air number inherits the wind estimate&rsquo;s "
             "uncertainty.",
    )


def _day_envelope(analysis: Analysis, m: Metrics, add) -> None:
    """Was the day building or decaying while it was being flown?"""
    if m.envelope is None or m.envelope_first is None or m.envelope_last is None:
        return
    if abs(m.envelope) < THRESHOLDS["envelope_decay"]:
        return
    direction = "decaying" if m.envelope < 0 else "building"
    hours = m.airtime / 3600
    add(
        "day-envelope",
        f"The day was {direction} at {abs(m.envelope):.2f} m/s per hour while it was "
        f"being flown",
        f"Climb rate fitted against the hour of the flight, weighted by how long each "
        f"climb was circled: {m.envelope_first:+.2f} m/s at the start against "
        f"{m.envelope_last:+.2f} m/s at the end, over {hours:.1f} h. A trend measured on "
        f"{len(analysis.thermals)} climbs of one flight, not on the day itself.",
        metres=abs(m.envelope) * hours * 600,
    )


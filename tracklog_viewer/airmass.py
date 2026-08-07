"""The air-mass frame: the flight as the glider flew it, not as the day carried it.

Subtract the wind from the track and everything downstream is about the glider rather
than about the day. Measured with the flight-level wind the correction is already visible
and it goes both ways — 8.0 to 7.9 ground-to-air L/D on the alpine flight, 6.3 to **7.0**
on the flatland day, an 11% correction from an 8 km/h wind. That is exactly the size of
error that makes a glide-quality finding wrong.

**The flight-level wind is not good enough to do it with.** Measured, its confidence is
0.36 on the alpine flight and 0.39 on the flatland one. The per-thermal winds are the
trustworthy ones (0.7–9.7 km/h with no outliers after the `_sustained` fix), so the field
below is built from those, interpolated in time *and* height, with the model profile as a
fallback where no climb was near — and the confidence is carried through so a finding can
refuse itself rather than publish a corrected number that is really an uncorrected one.

There is **no airspeed anywhere in the sample**: 49 of 50 IGC files carry `LAD`/`LOD`
only. Every "through the air" number here therefore comes from the wind estimate and
inherits its confidence. That is why `WindField.confidence` is not decoration.
"""

from dataclasses import dataclass

import numpy as np

from .analysis import Analysis, Phase, sample_interval, TURN_RESOLUTION_LIMIT

# How far away in time and height a measured climb can be and still say something about
# the air here. A thermal's drift describes the air it was circling in; an hour later and
# a kilometre higher it describes a different day.
TIME_SCALE = 2400.0  # seconds
HEIGHT_SCALE = 600.0  # metres
# Below this the field is not worth correcting with, and every consumer refuses.
MIN_CONFIDENCE = 0.5
# Fewer trusted climbs than this and there is no field to interpolate, only a guess.
MIN_SOUNDINGS = 2
# A glide has to last this long before its ratio means anything about the wing.
MIN_GLIDE_SECONDS = 60.0


@dataclass
class Sounding:
    """One measured wind, at the time and height it was measured."""

    t: float
    altitude: float
    vx: float  # m/s, east
    vy: float  # m/s, north
    confidence: float


@dataclass
class WindField:
    """Wind as a function of time and height, from the climbs that measured it."""

    soundings: list[Sounding]
    confidence: float
    source: str  # "measured", "model" or "mixed"
    fallback: tuple[float, float] | None = None  # model wind, east/north m/s

    @property
    def trusted(self) -> bool:
        return self.confidence >= MIN_CONFIDENCE and len(self.soundings) >= MIN_SOUNDINGS

    def at(self, t: float, altitude: float) -> tuple[float, float]:
        """Wind vector at a moment and a height, east/north in m/s.

        Inverse-distance weighting in a (time, height) plane with separate scales, rather
        than a fit: two or three soundings do not support a surface, and a linear fit
        through them extrapolates confidently past the top and bottom of the flight. IDW
        degrades to "the nearest measured climb" where the soundings are sparse, which is
        the honest answer.
        """
        if not self.soundings:
            return self.fallback or (0.0, 0.0)
        weights, vx, vy = 0.0, 0.0, 0.0
        for s in self.soundings:
            dt = (t - s.t) / TIME_SCALE
            dz = (altitude - s.altitude) / HEIGHT_SCALE
            distance = dt * dt + dz * dz
            weight = s.confidence / (distance + 0.05)
            weights += weight
            vx += weight * s.vx
            vy += weight * s.vy
        if weights <= 0:
            return self.fallback or (0.0, 0.0)
        return vx / weights, vy / weights


def _vector(wind) -> tuple[float, float]:
    """A `Wind` as east/north components of where the air is *going*.

    `Wind.direction` is where it comes from — the convention the whole codebase uses and
    the classic place to drop a 180. Reversing it here, once, is what keeps every consumer
    below from having to remember.
    """
    towards = np.radians((wind.direction + 180.0) % 360.0)
    return wind.speed * float(np.sin(towards)), wind.speed * float(np.cos(towards))


def field(analysis: Analysis, *, weather=None) -> WindField:
    """Build the wind field from the climbs that actually measured the air.

    Only climbs circled in one direction for at least two turns count, which is the same
    test `analyse()` applies before it will average them: drift measures the air only once
    the glider's own airspeed has averaged out, and a tow, a straight climb or a scratchy
    S-turn never does that.
    """
    coarse = sample_interval(analysis.series) > TURN_RESOLUTION_LIMIT
    soundings = []
    for segment in analysis.segments:
        if segment.phase is not Phase.THERMAL or not segment.wind:
            continue
        circled = (segment.turns or 0) >= 2 and segment.turn_direction in ("left", "right")
        if not (circled if not coarse else segment.duration >= 120):
            continue
        vx, vy = _vector(segment.wind)
        soundings.append(
            Sounding(
                t=float(analysis.series.t[segment.start]),
                altitude=(segment.start_altitude + segment.finish_altitude) / 2.0,
                vx=vx,
                vy=vy,
                confidence=segment.wind.confidence,
            )
        )

    fallback = None
    if weather is not None and hasattr(weather, "wind_at"):
        middle = float(np.median(analysis.series.alt))
        modelled = weather.wind_at(middle)
        if modelled:
            speed, direction = modelled
            towards = np.radians((direction + 180.0) % 360.0)
            fallback = (speed * float(np.sin(towards)), speed * float(np.cos(towards)))

    if not soundings:
        return WindField([], 0.0 if fallback is None else 0.4,
                         "model" if fallback else "none", fallback)

    confidence = float(np.mean([s.confidence for s in soundings]))
    return WindField(
        soundings=soundings,
        confidence=confidence,
        source="mixed" if fallback else "measured",
        fallback=fallback,
    )


def air_velocity(analysis: Analysis, wind: WindField) -> tuple[np.ndarray, np.ndarray]:
    """Ground velocity minus the wind: east/north components in m/s.

    This is the whole air-mass frame in two lines; everything else in this module is a
    statistic over it.
    """
    series = analysis.series
    t = series.t
    step = np.gradient(t)
    vx = np.gradient(series.x) / np.where(step == 0, np.nan, step)
    vy = np.gradient(series.y) / np.where(step == 0, np.nan, step)
    wx = np.empty_like(vx)
    wy = np.empty_like(vy)
    for i in range(len(t)):
        wx[i], wy[i] = wind.at(float(t[i]), float(series.alt[i]))
    return np.nan_to_num(vx - wx), np.nan_to_num(vy - wy)


def airspeed(analysis: Analysis, wind: WindField) -> np.ndarray:
    """Speed through the air, km/h."""
    vx, vy = air_velocity(analysis, wind)
    return 3.6 * np.hypot(vx, vy)


@dataclass
class GlidePerformance:
    """Glide ratio through the air, against the same figure over the ground."""

    air_ld: float
    ground_ld: float
    median_airspeed: float
    glides: int
    confidence: float


def glide_performance(analysis: Analysis, wind: WindField) -> GlidePerformance | None:
    """Wind-corrected median glide ratio.

    A median over glides past 60 s, never a maximum: the best glide on the alpine flight
    reads 116.2, which is not a measurement of the wing but of a glide that crossed lift.
    Refused on an untrusted wind — a "corrected" number from a 0.36-confidence field is an
    uncorrected number wearing a hat.
    """
    if not wind.trusted:
        return None
    series = analysis.series
    vx, vy = air_velocity(analysis, wind)

    air, ground = [], []
    for segment in analysis.glides:
        if segment.duration < MIN_GLIDE_SECONDS:
            continue
        drop = series.alt[segment.start] - series.alt[segment.stop - 1]
        if drop <= 0:
            continue
        span = slice(segment.start, segment.stop)
        step = np.diff(series.t[span])
        if not step.size:
            continue
        # Distance through the air is the air-relative speed integrated over the glide,
        # not the straight line between its ends: the two differ by exactly the drift the
        # correction exists to remove.
        flown = float(np.sum(np.hypot(vx[span][:-1], vy[span][:-1]) * step))
        air.append(flown / drop)
        if segment.average_ld:
            ground.append(segment.average_ld)
    if len(air) < 2:
        return None

    speeds = airspeed(analysis, wind)
    inside = np.zeros(len(series), dtype=bool)
    for segment in analysis.glides:
        if segment.duration >= MIN_GLIDE_SECONDS:
            inside[segment.start : segment.stop] = True

    return GlidePerformance(
        air_ld=round(float(np.median(air)), 1),
        ground_ld=round(float(np.median(ground)), 1) if ground else 0.0,
        median_airspeed=round(float(np.median(speeds[inside])), 1) if inside.any() else 0.0,
        glides=len(air),
        confidence=round(wind.confidence, 2),
    )


@dataclass
class CircleWander:
    """How far the centre of each circle moved, once the drift is taken out.

    This is the thing `circle_radius` cannot tell you: a climb circled tidily in a 20 km/h
    wind has a centre that moves a long way over the ground and hardly at all in the air.
    Separating the two is what makes "you were circling 40 m downwind of it" sayable.
    """

    median: float  # metres per circle
    worst: float
    climbs: int


def circle_wander(analysis: Analysis, wind: WindField) -> CircleWander | None:
    """Centre-to-centre movement per revolution, in the air frame.

    Gated at `TURN_RESOLUTION_LIMIT` with everything else that counts circles, and on the
    wind, because in a wind the whole measurement *is* the correction.
    """
    if not wind.trusted:
        return None
    if sample_interval(analysis.series) > TURN_RESOLUTION_LIMIT:
        return None

    from .analysis import _revolutions

    series = analysis.series
    vx, vy = air_velocity(analysis, wind)
    step = np.gradient(series.t)
    # Positions in the air frame: integrate the air-relative velocity.
    ax = np.cumsum(vx * step)
    ay = np.cumsum(vy * step)

    moves = []
    for segment in analysis.thermals:
        runs = _revolutions(series.heading[segment.start : segment.stop])
        centres = []
        for start, stop, _ in runs:
            lo, hi = segment.start + start, segment.start + stop
            if hi - lo < 3:
                continue
            centres.append((float(np.mean(ax[lo:hi])), float(np.mean(ay[lo:hi]))))
        for before, after in zip(centres, centres[1:]):
            moves.append(float(np.hypot(after[0] - before[0], after[1] - before[1])))
    if len(moves) < 3:
        return None

    return CircleWander(
        median=round(float(np.median(moves))),
        worst=round(float(np.max(moves))),
        climbs=len([s for s in analysis.thermals if s.turns]),
    )


@dataclass
class Polar:
    """Sink against airspeed, measured on this wing with this pilot at this loading.

    Better evidence than a manufacturer's curve because it is *this* glider, and it costs
    no new data. Sparse, though: one flight gives a few points and the archive gives a
    curve, so `bins` is deliberately small and the refusal is deliberately easy.
    """

    speeds: list[float]  # km/h, bin centres
    sink: list[float]  # m/s, negative
    counts: list[int]
    best_glide: tuple[float, float] | None  # (km/h, L/D) at the best bin, or None
    confidence: float
    # Does sink increase with airspeed, as a wing's must? When it does not, the curve is
    # measuring the air the glides happened to be in rather than the glider, and
    # `best_glide` is withheld. Measured on the 2020-07-12 tow flight, which published
    # "best glide 10.3:1 at 38.8 km/h" off a curve running 1.30 m/s down at 22.5 km/h
    # and 1.05 at 38.8 — a wing that sinks *less* the faster you fly it, all the way to
    # the fastest bin, which then wins by construction.
    monotone: bool = True


def polar(analysis: Analysis, wind: WindField, *, bins: int = 6,
          minimum: int = 20) -> Polar | None:
    """Fit sink against airspeed over straight glides, robust median per bin.

    Only straight glides: a circling glider is banked, and its sink says more about the
    turn than about the polar. A bin under `minimum` samples is dropped rather than
    plotted, which is what stops one noisy fast bin inventing a stall.
    """
    if not wind.trusted:
        return None
    series = analysis.series
    speeds = airspeed(analysis, wind)

    inside = np.zeros(len(series), dtype=bool)
    for segment in analysis.glides:
        if segment.duration >= MIN_GLIDE_SECONDS:
            inside[segment.start : segment.stop] = True
    if inside.sum() < minimum * 2:
        return None

    v = speeds[inside]
    w = series.climb[inside]
    low, high = float(np.percentile(v, 5)), float(np.percentile(v, 95))
    if high - low < 5.0:
        return None  # every glide flown at one speed says nothing about a curve

    edges = np.linspace(low, high, bins + 1)
    centres, sinks, counts = [], [], []
    for i in range(bins):
        band = (v >= edges[i]) & (v < edges[i + 1] if i < bins - 1 else v <= edges[i + 1])
        if band.sum() < minimum:
            continue
        centres.append(round(float((edges[i] + edges[i + 1]) / 2), 1))
        sinks.append(round(float(np.median(w[band])), 2))
        counts.append(int(band.sum()))
    if len(centres) < 2:
        return None

    # A wing sinks faster the faster it is flown. One bin's worth of noise is tolerated;
    # a larger reversal is the day, not the glider, and nothing is claimed off it. The
    # curve is still returned — its shape is the evidence for the refusal.
    monotone = all(b <= a + 0.1 for a, b in zip(sinks, sinks[1:]))

    ratios = [
        (speed, speed / 3.6 / -rate) for speed, rate in zip(centres, sinks) if rate < 0
    ]
    best = max(ratios, key=lambda pair: pair[1]) if ratios and monotone else None
    return Polar(
        speeds=centres,
        sink=sinks,
        counts=counts,
        best_glide=(round(best[0], 1), round(best[1], 1)) if best else None,
        confidence=round(wind.confidence, 2),
        monotone=monotone,
    )

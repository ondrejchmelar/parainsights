"""The air-mass frame: the flight as the glider flew it, with the day subtracted.

Subtract the wind from the track and everything downstream is about the glider rather
than about the day. The correction is not cosmetic — on a flatland day with 8 km/h of
wind the glide ratio moves from 6.3 over the ground to 7.0 through the air, which is
exactly the size of error that makes a glide-quality statement wrong.

**Which wind, though, is the whole problem.** `Analysis.wind` is a single vector for the
flight and its confidence measures 0.36–0.39 on both reference flights: it is not good
enough to correct a glide with, and correcting with it would publish an uncorrected
number wearing a corrected number's clothes. The per-thermal winds *are* trustworthy —
0.7–9.7 km/h with no outliers once `_sustained` cleaned the circling — so the field here
is interpolated from those, in time **and** in height, with the model profile from
`meteo.wind_at()` as the fallback where no climb was worked nearby, and a confidence
that travels with every query so a consumer can refuse itself.

Nothing here knows about HTML. It is derived data, beside `flight.py`.
"""

from dataclasses import dataclass, field as dataclass_field

import numpy as np

from .analysis import Analysis, Phase, TURN_RESOLUTION_LIMIT, sample_interval

# How far a measured climb's wind is allowed to reach. A thermal sounds the air where and
# when it was circled; an hour later and a kilometre higher it is describing a different
# air mass. These set the Gaussian falloff, not a hard cut — beyond about twice them the
# weight is negligible and the model takes over on its own.
TIME_SCALE = 2400.0       # seconds
HEIGHT_SCALE = 600.0      # metres
# Below this, say so rather than correcting. The flight-level estimate sits at 0.36–0.39,
# which is the number this threshold exists to keep out of a published glide ratio.
MIN_CONFIDENCE = 0.5
# A glide has to last this long before it measures anything about the wing: shorter and
# the 20 s windows at each end are most of it.
MIN_GLIDE = 60.0
# Airspeed bins for the polar, in km/h. Below 20 the glider is not flying; above 60 a
# paraglider is on bar and the sample is thin.
POLAR_BINS = np.arange(20.0, 62.0, 5.0)
MIN_BIN_SAMPLES = 20


def _components(speed: float, direction: float) -> tuple[float, float]:
    """A wind named for where it comes from, as the velocity of the air (east, north).

    The reversal is the classic error in this file's subject: `direction` is the bearing
    the wind blows *from*, so the air is moving towards `direction + 180`.
    """
    towards = np.radians(direction + 180.0)
    return speed * float(np.sin(towards)), speed * float(np.cos(towards))


@dataclass
class Sounding:
    """One climb's wind, at the time and height it was measured."""

    t: float
    height: float
    u: float           # m/s east
    v: float           # m/s north
    confidence: float


@dataclass
class WindField:
    """Wind over time and height, interpolated from the climbs that sounded it."""

    soundings: list[Sounding] = dataclass_field(default_factory=list)
    model: object | None = None       # a Meteo, or None
    baro_offset: float = 0.0

    @property
    def measured(self) -> bool:
        return bool(self.soundings)

    @property
    def confidence(self) -> float:
        """How well the field is pinned down, over the flight as a whole.

        The mean of the soundings' own confidences, discounted when there are only one
        or two of them: a field interpolated from a single climb is that climb's wind
        with a straight line drawn through it.
        """
        if not self.soundings:
            return 0.35 if self.model is not None else 0.0
        base = float(np.mean([s.confidence for s in self.soundings]))
        # Half credit for a lone climb, full from three. Not steeper than that: `at()`
        # already discounts a query far from every sounding, and taxing the count as
        # well would charge the same worry twice — the risk in one sounding is
        # extrapolation, which is exactly what that other factor measures.
        return base * min((len(self.soundings) + 1) / 4.0, 1.0)

    def at(self, t: float, height: float) -> tuple[float, float, float]:
        """The air's velocity at a moment and a height: (east, north, confidence).

        Gaussian weights in both axes, which degrades gracefully rather than stepping:
        a query in the middle of the soundings is nearly the local wind, and one far
        from all of them falls back towards the model — or, with no model, towards the
        flight's mean, at a confidence that says so.
        """
        if self.soundings:
            dt = np.array([s.t for s in self.soundings]) - t
            dh = np.array([s.height for s in self.soundings]) - height
            weights = np.exp(-0.5 * ((dt / TIME_SCALE) ** 2 + (dh / HEIGHT_SCALE) ** 2))
            weights = weights * np.array([s.confidence for s in self.soundings])
            total = float(weights.sum())
            if total > 1e-6:
                u = float((weights * np.array([s.u for s in self.soundings])).sum() / total)
                v = float((weights * np.array([s.v for s in self.soundings])).sum() / total)
                # Nearness is what the confidence is really about: the same soundings
                # describe a query inside their span much better than one outside it.
                reach = float(np.max(weights)) / max(
                    max(s.confidence for s in self.soundings), 1e-6
                )
                return u, v, self.confidence * min(reach, 1.0)
        if self.model is not None:
            answer = self.model.wind_at(height + self.baro_offset)
            if answer:
                u, v = _components(answer[0] / 3.6, answer[1])
                # A model's analysis for a point near the course line, and it says so.
                return u, v, 0.35
        return 0.0, 0.0, 0.0


def wind_field(analysis: Analysis, *, meteo=None) -> WindField:
    """Build the field from the climbs that were properly circled.

    The same test the flight-level estimate uses, and for the same reason: drift only
    measures the air once the glider's own airspeed has averaged out, which a tow, a
    straight climb or a scratchy S-turn never does.
    """
    coarse = sample_interval(analysis.series) > TURN_RESOLUTION_LIMIT
    soundings = []
    for segment in analysis.segments:
        if segment.phase is not Phase.THERMAL or not segment.wind:
            continue
        trusted = (
            segment.duration >= 120 if coarse
            else (segment.turns or 0) >= 2 and segment.turn_direction in ("left", "right")
        )
        if not trusted:
            continue
        u, v = _components(segment.wind.speed, segment.wind.direction)
        soundings.append(Sounding(
            t=float((analysis.series.t[segment.start] + analysis.series.t[segment.stop - 1]) / 2),
            height=(segment.start_altitude + segment.finish_altitude) / 2,
            u=u, v=v, confidence=segment.wind.confidence,
        ))
    return WindField(soundings, model=meteo,
                     baro_offset=float(analysis.summary.baro_offset or 0))


def velocities(analysis: Analysis) -> tuple[np.ndarray, np.ndarray]:
    """Ground velocity per fix, east and north, in m/s.

    Differenced over the fix spacing rather than over the 20 s window: the window is what
    smooths climb rate, and smoothing the horizontal velocity as well would blur the very
    circles the air frame is meant to separate.
    """
    series = analysis.series
    dt = np.diff(series.t)
    dt = np.where(dt <= 0, np.nan, dt)
    vx = np.concatenate(([np.nan], np.diff(series.x) / dt))
    vy = np.concatenate(([np.nan], np.diff(series.y) / dt))
    vx[0], vy[0] = vx[1] if len(vx) > 1 else 0.0, vy[1] if len(vy) > 1 else 0.0
    return np.nan_to_num(vx), np.nan_to_num(vy)


def air_velocities(analysis: Analysis, field: WindField) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Velocity through the air per fix: east, north, and the confidence of each.

    One field query per fix would be a few hundred thousand exponentials on a long
    flight, so the field is sampled on a coarse grid of the flight's own time and
    interpolated between — the field varies over tens of minutes and hundreds of metres
    by construction, so nothing is lost that was ever there.
    """
    series = analysis.series
    vx, vy = velocities(analysis)
    steps = max(int(series.t[-1] // 60), 4)
    knots = np.linspace(series.t[0], series.t[-1], steps)
    heights = np.interp(knots, series.t, series.alt)
    sampled = [field.at(float(t), float(h)) for t, h in zip(knots, heights)]
    wu = np.interp(series.t, knots, [s[0] for s in sampled])
    wv = np.interp(series.t, knots, [s[1] for s in sampled])
    confidence = np.interp(series.t, knots, [s[2] for s in sampled])
    return vx - wu, vy - wv, confidence


@dataclass
class PolarPoint:
    airspeed: float    # km/h, bin centre
    sink: float        # m/s, negative
    samples: int


@dataclass
class Polar:
    """Sink against airspeed over straight glides, binned, median per bin.

    Better evidence than a manufacturer's curve because it is *this* glider with *this*
    pilot at *this* loading, and it costs no new data. One flight gives a few points; the
    archive would give a curve. It is also the input every speed-to-fly statement needs,
    which is why it gates that whole family — including the honest refusal when the fit
    is too sparse to say anything.
    """

    points: list[PolarPoint] = dataclass_field(default_factory=list)
    confidence: float = 0.0

    @property
    def monotone(self) -> bool:
        """Does sink increase with airspeed, as a wing's must?

        This is the sanity gate, and it earns its place on real data: the tow flight's
        one-flight polar comes out *inverted* — 1.40 m/s down at 32 km/h and 0.80 at
        42 — which is not a wing that goes better the faster you fly it, it is a pilot
        who flew fast in the good air. A single flight measures the day at least as much
        as the glider, and the honest response is to refuse rather than to publish a
        speed-to-fly number built on it.
        """
        if len(self.points) < 3:
            return False
        # One bin's worth of noise is tolerated; a reversal larger than that is the day.
        return all(
            b.sink <= a.sink + 0.1
            for a, b in zip(self.points, self.points[1:])
        )

    @property
    def usable(self) -> bool:
        return (
            len(self.points) >= 3
            and self.confidence >= MIN_CONFIDENCE
            and self.monotone
        )

    @property
    def best_glide(self) -> tuple[float, float] | None:
        """The bin with the best ratio: (km/h, L/D). Not a maximum over samples."""
        if not self.points:
            return None
        best = max(self.points, key=lambda p: (p.airspeed / 3.6) / max(-p.sink, 1e-6))
        return best.airspeed, (best.airspeed / 3.6) / max(-best.sink, 1e-6)


@dataclass
class Airmass:
    """The flight in the air's own frame, and what that lets us say about the wing."""

    field: WindField
    ground_ld: float | None = None
    air_ld: float | None = None
    airspeed: float | None = None        # median over straight glides, km/h
    ground_speed: float | None = None
    polar: Polar | None = None
    wander: float | None = None          # metres, circle centre to circle centre
    wander_climbs: int = 0

    @property
    def trustworthy(self) -> bool:
        return self.field.confidence >= MIN_CONFIDENCE


def _glide_slices(analysis: Analysis) -> list[tuple[int, int]]:
    """Straight flight long enough to measure a wing with.

    Deliberately `Phase.GLIDE`, not all straight flight: the polar wants the glider
    doing one thing, and a straight run through lift is the air's contribution, not the
    wing's. That is the opposite choice from the dolphin metric, and for the opposite
    reason.
    """
    return [
        (s.start, s.stop) for s in analysis.glides
        if s.duration >= MIN_GLIDE and s.stop - s.start > 3
    ]


def analyse(analysis: Analysis, *, meteo=None) -> Airmass:
    """Everything the air frame supports, with its confidence attached."""
    field = wind_field(analysis, meteo=meteo)
    result = Airmass(field=field)
    # Before the early return: circling is not gliding, and a flight with no glide long
    # enough to measure a wing with still has thermals whose centres can be followed.
    result.wander, result.wander_climbs = _circle_wander(analysis, field)
    slices = _glide_slices(analysis)
    if not slices:
        return result

    series = analysis.series
    ax, ay, confidence = air_velocities(analysis, field)
    gx, gy = velocities(analysis)
    dt = np.gradient(series.t)
    sink = series.climb

    air_speeds, ground_speeds, air_ratios, ground_ratios = [], [], [], []
    polar_speed, polar_sink = [], []
    for start, stop in slices:
        span = slice(start, stop)
        seconds = float(series.t[stop - 1] - series.t[start])
        drop = float(series.alt[start] - series.alt[stop - 1])
        air = float(np.mean(np.hypot(ax[span], ay[span]))) * 3.6
        ground = float(np.mean(np.hypot(gx[span], gy[span]))) * 3.6
        air_speeds.append(air)
        ground_speeds.append(ground)
        if drop > 0:
            ground_ratios.append(float(np.hypot(
                series.x[stop - 1] - series.x[start], series.y[stop - 1] - series.y[start]
            )) / drop)
            # Through the air the distance is the integral of airspeed, not the
            # displacement: the air itself has moved under the glider.
            air_ratios.append(float(np.sum(np.hypot(ax[span], ay[span]) * dt[span])) / drop)
        # Only samples the field actually reaches contribute to the polar, and only
        # where the vario is behaving like a glide rather than a dolphin.
        usable = (confidence[span] >= MIN_CONFIDENCE) & (sink[span] < 0)
        polar_speed.extend((np.hypot(ax[span], ay[span]) * 3.6)[usable].tolist())
        polar_sink.extend(sink[span][usable].tolist())
        del seconds

    if air_speeds:
        result.airspeed = round(float(np.median(air_speeds)), 1)
        result.ground_speed = round(float(np.median(ground_speeds)), 1)
    if ground_ratios:
        result.ground_ld = round(float(np.median(ground_ratios)), 1)
    if air_ratios and field.confidence >= MIN_CONFIDENCE:
        result.air_ld = round(float(np.median(air_ratios)), 1)

    result.polar = _fit_polar(np.array(polar_speed), np.array(polar_sink),
                              field.confidence)
    return result


def _fit_polar(speeds: np.ndarray, sink: np.ndarray, confidence: float) -> Polar:
    """Median sink per airspeed bin. Robust, because one dolphin ruins a mean."""
    points = []
    for low, high in zip(POLAR_BINS, POLAR_BINS[1:]):
        inside = (speeds >= low) & (speeds < high)
        if int(inside.sum()) < MIN_BIN_SAMPLES:
            continue
        points.append(PolarPoint(
            airspeed=round(float((low + high) / 2), 1),
            sink=round(float(np.median(sink[inside])), 2),
            samples=int(inside.sum()),
        ))
    return Polar(points, confidence=round(confidence, 2))


def _circle_wander(analysis: Analysis, field: WindField) -> tuple[float | None, int]:
    """How far the circle centre moved between revolutions, in the air's frame.

    This is the thing `circle_radius` cannot tell you. Over the ground a thermal's
    circles march downwind and the centre "wanders" by exactly the drift, which says
    nothing about the pilot. Subtract the air and what is left is the centring: a climb
    held in one place reads a few metres, one chased around reads tens.

    Gated at `TURN_RESOLUTION_LIMIT` like everything else that counts circles.
    """
    from .analysis import _revolutions           # local: this is the only user

    series = analysis.series
    if sample_interval(series) > TURN_RESOLUTION_LIMIT:
        return None, 0
    ax, ay, confidence = air_velocities(analysis, field)
    dt = np.gradient(series.t)
    # Position in the air frame: integrate the air-relative velocity. Absolute origin is
    # arbitrary and irrelevant — only the distance between successive centres is read.
    px = np.cumsum(ax * dt)
    py = np.cumsum(ay * dt)

    moves, climbs = [], 0
    for segment in analysis.thermals:
        if not segment.turns or segment.turns < 2:
            continue
        centres = _circle_centres(series.heading, px, py, segment)
        if len(centres) < 2:
            continue
        climbs += 1
        moves.extend(
            float(np.hypot(b[0] - a[0], b[1] - a[1]))
            for a, b in zip(centres, centres[1:])
        )
    if not moves:
        return None, 0
    return round(float(np.median(moves))), climbs


def _circle_centres(heading: np.ndarray, px: np.ndarray, py: np.ndarray,
                    segment) -> list[tuple[float, float]]:
    """The centre of each *whole* circle inside a climb.

    Whole is the load-bearing word. Averaging position over a run that `_revolutions`
    returned is only the centre when the run is an exact number of circles — a run of
    1.5 circles has its mean displaced by most of a radius, and over a climb those
    displacements read as the thermal being chased around. Measured on the flatland
    flight that was the difference between 240 m of "wander" and 40 m: nearly all of it
    was the arc, not the pilot.

    So each run is cut at every 360° of its own heading, and only the complete arcs
    between those cuts contribute.
    """
    from .analysis import _revolutions

    centres = []
    for a, b, _ in _revolutions(heading[segment.start:segment.stop]):
        lo, hi = segment.start + a, segment.start + b + 1
        arc = heading[lo:hi]
        if hi - lo < 6:
            continue
        turns = int(abs(arc[-1] - arc[0]) // 360)
        sign = 1.0 if arc[-1] >= arc[0] else -1.0
        for turn in range(turns):
            # Where this circle starts and ends, in indices, by walking the heading.
            start_at = arc[0] + sign * 360 * turn
            end_at = start_at + sign * 360
            if sign > 0:
                first = int(np.searchsorted(arc, start_at))
                last = int(np.searchsorted(arc, end_at))
            else:
                first = int(np.searchsorted(-arc, -start_at))
                last = int(np.searchsorted(-arc, -end_at))
            if last - first < 4:
                continue
            centres.append((
                float(np.mean(px[lo + first:lo + last])),
                float(np.mean(py[lo + first:lo + last])),
            ))
    return centres

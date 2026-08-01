"""What the sun was doing to the ground, from the DEM and the solar tables.

Both halves are already in the report and neither costs a byte of new data: `terrain.py`
holds the elevation grid, and `sun.py` tabulates the day's solar position every ten
minutes for the 3D view's re-lighting. Slope and aspect are a gradient of that grid, and
the cosine of the angle between a cell's surface normal and the sun vector is its relative
insolation at any moment. The machinery to *show* this already exists — the 3D view lights
the terrain from the same tables — and what was missing was reading a number out of it.

Two findings fall straight out:

* **The trigger** — which face was lit, and how strongly, at the minute each climb
  started, and how that compares with the ground around it. This is the question a pilot
  asks about a new site all day long.
* **The windward face** — aspect against the measured wind gives ridge-lift potential,
  which is a candidate explanation for the "rising, uncounted" minutes that the `other`
  decomposition uncovered.

Nothing here claims a cause. A lit south-west face under a climb is a coincidence the
pilot can weigh, not a reason the thermal existed — the tool cannot see the sky.
"""

from dataclasses import dataclass

import numpy as np

from . import geo, sun

# How far around a climb's start point to look when asking whether its face was unusual.
# Small enough to mean "the slope you were on" rather than "the valley".
NEIGHBOURHOOD = 1200.0  # metres
# A slope flatter than this has no meaningful aspect, and calling one is noise.
MIN_SLOPE = 5.0  # degrees


@dataclass
class Face:
    """The ground under a point: how it lies, and how hard the sun was hitting it."""

    slope: float  # degrees from horizontal
    aspect: float  # degrees clockwise from north, the direction it faces
    cardinal: str
    insolation: float  # 0..1, cosine of the sun's incidence on the surface
    relative: float  # insolation over the neighbourhood's mean, 1.0 = ordinary
    sun_elevation: float


def _gradients(terrain) -> tuple[np.ndarray, np.ndarray]:
    """Ground slope in metres per metre, east and north.

    The grid is regular in *degrees*, not metres, so the east spacing shrinks with the
    cosine of latitude — using one spacing for both axes tilts every aspect towards the
    poles. The row order matters too: row 0 is north, so the north gradient is negated.
    """
    rows, cols = terrain.elevations.shape
    if rows < 2 or cols < 2:
        return np.zeros((rows, cols)), np.zeros((rows, cols))

    mid_lat = (terrain.north + terrain.south) / 2.0
    dy = geo.R * np.radians(terrain.north - terrain.south) / (rows - 1)
    dx = (
        geo.R
        * np.radians(terrain.east - terrain.west)
        * np.cos(np.radians(mid_lat))
        / (cols - 1)
    )
    d_north, d_east = np.gradient(terrain.elevations.astype(float))
    return d_east / max(dx, 1e-6), -d_north / max(dy, 1e-6)


def grid(terrain, position: sun.Position) -> np.ndarray:
    """Relative insolation of every cell, 0..1, for one solar position.

    The surface normal of a cell with gradients (gx, gy) is (-gx, -gy, 1) normalised; the
    illumination is its dot product with the unit vector towards the sun. Negative means
    the face is turned away, and is clamped to zero rather than allowed to go negative and
    quietly subtract from a mean later.
    """
    gx, gy = _gradients(terrain)
    sx, sy, sz = position.vector()
    norm = np.sqrt(gx * gx + gy * gy + 1.0)
    lit = (-gx * sx - gy * sy + sz) / norm
    if position.elevation <= 0:
        return np.zeros_like(lit)
    return np.clip(lit, 0.0, 1.0)


def face_at(terrain, position: sun.Position, lat: float, lon: float) -> Face | None:
    """How the ground lies under one point, and how lit it was.

    `relative` is the local comparison the finding needs: an insolation of 0.8 means
    nothing on a day when every slope reads 0.8, and everything when the ground around it
    reads 0.4.
    """
    rows, cols = terrain.elevations.shape
    if rows < 3 or cols < 3:
        return None
    if not (terrain.south <= lat <= terrain.north and terrain.west <= lon <= terrain.east):
        return None

    gx, gy = _gradients(terrain)
    row = (terrain.north - lat) / (terrain.north - terrain.south) * (rows - 1)
    col = (lon - terrain.west) / (terrain.east - terrain.west) * (cols - 1)
    r, c = int(round(row)), int(round(col))
    r = min(max(r, 0), rows - 1)
    c = min(max(c, 0), cols - 1)

    slope = float(np.degrees(np.arctan(np.hypot(gx[r, c], gy[r, c]))))
    # Aspect is the compass bearing the slope faces, which is the direction of *descent*.
    aspect = float(np.degrees(np.arctan2(-gx[r, c], -gy[r, c])) % 360.0)

    lit = grid(terrain, position)
    here = float(lit[r, c])

    # The neighbourhood, in cells rather than metres.
    span_lat = (terrain.north - terrain.south) / max(rows - 1, 1)
    span_lon = (terrain.east - terrain.west) / max(cols - 1, 1)
    metres_per_row = geo.R * np.radians(span_lat)
    metres_per_col = geo.R * np.radians(span_lon) * np.cos(np.radians(lat))
    dr = max(int(NEIGHBOURHOOD / max(metres_per_row, 1.0)), 1)
    dc = max(int(NEIGHBOURHOOD / max(metres_per_col, 1.0)), 1)
    patch = lit[max(r - dr, 0) : r + dr + 1, max(c - dc, 0) : c + dc + 1]
    around = float(np.mean(patch)) if patch.size else 0.0

    return Face(
        slope=round(slope, 1),
        aspect=round(aspect),
        cardinal=geo.cardinal(aspect),
        insolation=round(here, 2),
        relative=round(here / around, 2) if around > 0.01 else 1.0,
        sun_elevation=round(position.elevation, 1),
    )


@dataclass
class Trigger:
    """The face under one climb, at the minute it started."""

    climb: int
    at: str
    face: Face


def triggers(analysis, terrain, *, limit: int | None = None) -> list[Trigger]:
    """The ground under each climb, lit as it was when the climb began.

    Solar position is computed per climb rather than once for the flight: the whole point
    is that a face lit at 11:00 is in shadow at 17:00, which is the question a pilot is
    actually asking.
    """
    if terrain is None:
        return []
    found = []
    for number, segment in enumerate(analysis.thermals, start=1):
        if segment.centre is None:
            continue
        lat, lon = segment.centre
        when = analysis.flight.local_time(segment.start)
        position = sun.position(when, lat, lon)
        face = face_at(terrain, position, lat, lon)
        if face is None or face.slope < MIN_SLOPE:
            continue
        found.append(Trigger(climb=number, at=segment.start_time, face=face))
        if limit and len(found) >= limit:
            break
    return found


# Ridge lift only exists near the slope making it, so height above the ground is what
# separates a climb the hill was producing from a thermal that happened to trigger on a
# windward face. 250 m is generous for a paraglider working a ridge and well inside the
# height a thermal is normally centred at. Measured as the *median* over the climb: the
# first fix is a single sample and the DEM disagrees with GPS by tens of metres in
# either direction, which is how a climb worked at 90 m came to report −29.
RIDGE_CLEARANCE = 250.0  # metres above the ground, median over the climb
# Flatter than this and there is no ridge, whatever the wind is doing.
RIDGE_SLOPE = 12.0  # degrees
# Complete circles per minute. A thermal is circled — every thermal across the six real
# flights this was measured on runs above 1.2 — and a ridge is beaten, back and forth
# along the slope, which scores essentially none. Half a circle a minute sits in the gap.
RIDGE_TURN_RATE = 0.5  # revolutions per minute
# A slope within this of the wind's bearing is the one the air runs up. Reported, not
# required: see `sources`.
RIDGE_TOLERANCE = 60.0  # degrees


@dataclass
class Source:
    """What appears to have been holding one climb up.

    Two labels, and deliberately not three. **Ridge** is claimable because it needs three
    things to agree that a thermal does not need at all — a steep face, the glider staying
    within a couple of hundred metres of it, and a track that beats along the slope rather
    than turning inside a core — and the absence of any one of them settles it.
    **Thermal** is the rest.

    *Convergence is not a label here.* Its honest signature is a climb whose drift departs
    from the surrounding air, and one tracklog cannot separate that from a ridge climb
    holding station, a poorly sounded wind, or a pilot flying the climb badly. Naming it
    would be the confidently wrong sentence this report exists to avoid; it wants either
    several gliders on the same day or a wind field with a real discontinuity in it.

    `confident` is False where the label is the fallback rather than a finding: no terrain,
    or a climb the flight never located.
    """

    climb: int
    at: str
    label: str  # "ridge" | "thermal"
    confident: bool
    clearance: float | None = None  # metres above the ground, median over the climb
    slope: float | None = None  # degrees, the ground under the climb
    turn_rate: float | None = None  # complete circles per minute
    offset: float | None = None  # degrees between the face and the wind it came from


def _ground_clearance(analysis, terrain, segment) -> float | None:
    """Median height above the DEM over a climb, or None if it cannot be measured.

    The median rather than the first fix or the minimum: one fix is one sample of a
    disagreement between a 60 m DEM cell and a GPS altitude that is worth tens of metres
    on its own, and the minimum is whatever the worst of those was. On the ridge flight
    every climb reported a *negative* start clearance while its median sat at 32–89 m,
    which is the number a pilot would recognise.
    """
    flight = analysis.flight
    start, stop = segment.start, max(segment.stop, segment.start + 1)
    lat = flight.lat[start:stop]
    lon = flight.lon[start:stop]
    if len(lat) == 0:
        return None
    altitude = flight.alt_gps if np.any(flight.alt_gps) else analysis.series.alt
    ground = terrain.at(lat, lon)
    if ground is None:
        return None
    return float(np.median(np.asarray(altitude[start:stop], dtype=float) - ground))


def sources(analysis, terrain) -> dict[int, Source]:
    """Classify each climb by what was most likely holding it up, keyed by climb number.

    Three measurements have to agree before this says ridge, and all three come off the
    tracklog and the DEM: the ground is **steep**, the climb **stayed on it**, and it was
    **beaten rather than circled**. The last is the one that carries the claim. A thermal
    is a thing you turn inside of; a ridge is a slope you fly along and come back. Across
    the six real flights this was measured on, every thermal ran above 1.2 complete
    circles a minute and every ridge beat scored none at all — the separation is not
    marginal, it is a different manoeuvre.

    **The wind does not gate the label**, and that is a correction rather than a
    simplification. It used to: a climb was ridge only if the flight's wind exceeded
    12 km/h and ran into the face. That rule found ridge lift on none of the six flights,
    for two reasons that are both structural. On a soaring flight the wind estimate is
    *derived from circling drift* — so a pilot who spends the evening beating a ridge and
    never circles produces no wind estimate at all, and the one test that could have
    recognised the flight was disabled by the very behaviour it was looking for. And on
    the cross-country flights the flight-level average sat just under the threshold while
    individual climbs ran three times it. The offset is still measured and still
    reported, because it is worth seeing; it is no longer allowed to veto.
    """
    wind = getattr(analysis, "wind", None)
    found: dict[int, Source] = {}
    for number, segment in enumerate(analysis.thermals, start=1):
        at = segment.start_time
        if terrain is None or segment.centre is None:
            found[number] = Source(number, at, "thermal", confident=False)
            continue

        lat, lon = segment.centre
        when = analysis.flight.local_time(segment.start)
        face = face_at(terrain, sun.position(when, lat, lon), lat, lon)
        clearance = _ground_clearance(analysis, terrain, segment)
        if face is None or clearance is None:
            found[number] = Source(number, at, "thermal", confident=False)
            continue

        minutes = max(segment.duration / 60.0, 1 / 60.0)
        turn_rate = (segment.turns or 0.0) / minutes
        ridge = (
            face.slope >= RIDGE_SLOPE
            and clearance <= RIDGE_CLEARANCE
            and turn_rate <= RIDGE_TURN_RATE
        )
        # The climb's own drift where it has one, the flight's otherwise. Neither decides
        # anything here, so the weaker estimate costs nothing beyond a number in a tooltip.
        against = segment.wind or wind
        offset = (
            abs(((face.aspect - against.direction + 540) % 360) - 180)
            if against is not None
            else None
        )
        found[number] = Source(
            climb=number,
            at=at,
            label="ridge" if ridge else "thermal",
            confident=True,
            clearance=round(clearance),
            slope=face.slope,
            turn_rate=round(turn_rate, 2),
            offset=None if offset is None else round(offset),
        )
    return found


@dataclass
class WindwardFaces:
    """How many climbs started over ground facing into the measured wind."""

    windward: int
    total: int
    mean_offset: float  # degrees between the face and the wind it came from

    @property
    def fraction(self) -> float:
        return self.windward / self.total if self.total else 0.0


def windward(analysis, terrain, *, tolerance: float = 60.0) -> WindwardFaces | None:
    """Climbs whose ground faced into the wind — candidate ridge lift.

    `Wind.direction` is where the air comes *from*, and a slope facing that bearing is the
    one the air runs up: so the comparison is aspect against direction directly, with no
    180 in it. Refused without a wind, because every one of these is a comparison to it.
    """
    if terrain is None or analysis.wind is None:
        return None
    found = triggers(analysis, terrain)
    if not found:
        return None

    offsets = [
        abs(((trigger.face.aspect - analysis.wind.direction + 540) % 360) - 180)
        for trigger in found
    ]
    return WindwardFaces(
        windward=sum(1 for offset in offsets if offset <= tolerance),
        total=len(offsets),
        mean_offset=round(float(np.mean(offsets))),
    )

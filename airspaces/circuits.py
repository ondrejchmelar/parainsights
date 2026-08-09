"""The okruh: where the landing aeroplanes are.

A paraglider may fly in a Czech ATZ, but not through the traffic circuit. This draws
that circuit as a **band following the circuit path** — a racetrack around the runway,
300 m wide, hollow in the middle.

**Why a band and not a filled box.** The obvious representation would be XCTrack's
obstacle layer, and it is not available: obstacles are a curated per-country download
from airspace.xcontest.org (Austria, France, Germany, Italy, Slovenia, Switzerland —
not Czechia), there is no import path, and the request for one has been open as
xctrack-public#855 since April 2022. An obstacle there is also a *line with an
altitude* — a power line or a cable car — which a volume of circling traffic is not.
So this stays OpenAir, but takes the shape the idea was reaching for: a filled box is
14 km² of alert per runway, most of it corners where nothing ever flies, where the band
is 4.4 km² and reads like the circuit it represents.

**Both sides, always.** The published handedness would let the band be half this size,
but at a Czech aeroclub field the glider circuit is the mirror of the powered one
(LKBE: `RWY 06, 09L/R - left hand` … `gliders RWY 06, 09L/R - right`), so a one-sided
band would be wrong at exactly the fields with the most traffic. The AIP states no
direction at all for 15 of the 82 and states it ambiguously for several more. A
both-sides band needs none of that and cannot be silently wrong; what the AIP does say
goes into the airspace name, where XCTrack shows it on a tap.

**The band is cut by a small gap rather than closed around a hole.** OpenAir has no
hole primitive, and the alternative — tracing the outer ring into the inner one through
a zero-width slit — makes a polygon that touches itself, which different point-in-
polygon implementations resolve differently: even-odd gives the hollow centre, nonzero
winding fills it in. A real 60 m gap makes the ring a *simple* polygon that every
implementation reads identically. The cost is a 60 m break in one short end of the
band, which is nothing against a 300 m width.

The dimensions are the ordinary shape of a light-aircraft circuit, not a published
figure — a downwind leg about 1.2 km abeam and the turns roughly 2 km beyond each
threshold. `AN` says so, so nobody reads the boundary as an official one.

Ceiling is the published circuit altitude where there is one. That is an *altitude*
AMSL, which is what OpenAir wants and what a paraglider's instrument shows.
"""

from __future__ import annotations

from . import geo, openair
from .aerodromes import FEET, Aerodrome, Runway

# The circuit path: downwind leg abeam, turns beyond the threshold.
BESIDE_M = 1200.0
BEYOND_M = 2000.0

# How wide the band around that path is, and the gap that keeps the ring simple.
RIBBON_M = 300.0
GAP_M = 60.0

# When the AIP publishes no circuit altitude, fall back to this above the aerodrome.
# 1000 ft is the standard light-aircraft circuit height.
DEFAULT_CIRCUIT_AGL_FT = 1000.0


class _Frame:
    """The runway's own axes: x along it from the midpoint, y across to the right."""

    def __init__(self, runway: Runway):
        self.heading = geo.bearing(
            runway.low_lat, runway.low_lon, runway.high_lat, runway.high_lon
        )
        self.mid = (
            (runway.low_lat + runway.high_lat) / 2,
            (runway.low_lon + runway.high_lon) / 2,
        )
        self.half = runway.length_m / 2

    def point(self, along: float, across: float) -> tuple[float, float]:
        moved = geo.destination(*self.mid, self.heading, along)
        return geo.destination(*moved, (self.heading + 90) % 360, across)


def _rectangle(frame: _Frame, along: float, across: float):
    """Corners of a rectangle about the runway midpoint, anticlockwise."""
    return [
        frame.point(-along, across),
        frame.point(along, across),
        frame.point(along, -across),
        frame.point(-along, -across),
    ]


def box(runway: Runway, beside: float = BESIDE_M, beyond: float = BEYOND_M):
    """The filled rectangle the band is built around. Kept for measuring against."""
    frame = _Frame(runway)
    return _rectangle(frame, frame.half + beyond, beside)


def ribbon(runway: Runway, beside: float = BESIDE_M, beyond: float = BEYOND_M,
           width: float = RIBBON_M, gap: float = GAP_M):
    """The circuit path thickened into a band, as one simple closed ring.

    Traced outer edge anticlockwise from one side of the gap all the way round, then
    back along the inner edge — so the enclosed area is the band and the middle is
    outside it, with no self-touching anywhere.
    """
    frame = _Frame(runway)
    half = width / 2
    out_along, out_across = frame.half + beyond + half, beside + half
    in_along, in_across = frame.half + beyond - half, beside - half
    edge = gap / 2

    outer = _rectangle(frame, out_along, out_across)
    inner = _rectangle(frame, in_along, in_across)
    # `_rectangle` yields (-along, +across), (+along, +across), (+along, -across),
    # (-along, -across). The outer edge has to be walked from the gap *away* from it,
    # which is index 1 → 0 → 3 → 2; taking them in stored order instead folds the ring
    # over itself and the polygon stops being simple.
    return [
        # Outer edge, from one side of the gap all the way round to the other.
        frame.point(out_along, edge),
        outer[1], outer[0], outer[3], outer[2],
        frame.point(out_along, -edge),
        # Across the width of the band, then the inner edge back.
        frame.point(in_along, -edge),
        inner[2], inner[3], inner[0], inner[1],
        frame.point(in_along, edge),
    ]


def ceiling_ft(field: Aerodrome) -> float | None:
    """Circuit altitude in feet AMSL, published where the AIP states one."""
    if field.circuit_ft:
        return field.circuit_ft
    if field.elevation_ft is not None:
        return field.elevation_ft + DEFAULT_CIRCUIT_AGL_FT
    return None


def _name(field: Aerodrome, runway: Runway, ceiling: float | None, published: bool) -> str:
    parts = [f"OKRUH {field.icao}"]
    if field.name:
        parts.append(field.name)
    parts.append(f"RWY {runway.name}")
    if ceiling is not None:
        metres = round(ceiling * FEET / 10) * 10
        parts.append(f"{round(ceiling)}ft/{metres}m" + ("" if published else " est"))
    if field.circuit_note:
        parts.append(field.circuit_note)
    return " ".join(parts)


def to_airspaces(field: Aerodrome) -> list[openair.Airspace]:
    """Every runway's circuit box at this aerodrome.

    Class `Q`: orange and silent in XCTrack. The box sits inside an ATZ that already
    alerts on its boundary, so a second alert a kilometre later would only train the
    pilot to dismiss it.
    """
    ceiling = ceiling_ft(field)
    if ceiling is None:
        return []
    published = field.circuit_ft is not None
    out = []
    for runway in field.runways:
        out.append(
            openair.Airspace(
                name=_name(field, runway, ceiling, published),
                airspace_class="Q",
                floor="GND",
                ceiling=f"{round(ceiling)}ft AMSL",
                frequency=field.frequency,
                points=ribbon(runway),
                meta={"icao": field.icao, "kind": "circuit", "runway": runway.name},
            )
        )
    return out

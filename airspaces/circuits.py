"""The okruh: where the landing aeroplanes are.

A paraglider may fly in a Czech ATZ, but not through the traffic circuit. This draws
each circuit as a **band following the circuit path** — 300 m wide, hollow inside —
and there are **two per runway, one each side, abutting along the runway itself**.
That is how the AIP draws them, and it matters: an earlier version drew a single ring
at ±1 300 m with a hole in the middle, and at an SLZ field, whose ATZ is only ~976 m
in radius, the entire ATZ fell inside that hole. Nothing was marked over the field,
the approach or the climb-out — the ground where an aeroplane is lowest and least able
to avoid anybody.

**Why a band and not a filled box.** The obvious representation would be XCTrack's
obstacle layer, and it is not available: obstacles are a curated per-country download
from airspace.xcontest.org (Austria, France, Germany, Italy, Slovenia, Switzerland —
not Czechia), there is no import path, and the request for one has been open as
xctrack-public#855 since April 2022. An obstacle there is also a *line with an
altitude* — a power line or a cable car — which a volume of circling traffic is not.
So this stays OpenAir, but takes the shape the idea was reaching for: a band that reads
like the circuit it represents, rather than a slab over everything within it.

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

The dimensions come off the AIP's own VOC charts (see below), but the band is still
this tool's drawing and not a published boundary. `AN` says so.

Ceiling is the published circuit altitude where there is one. That is an *altitude*
AMSL, which is what OpenAir wants and what a paraglider's instrument shows.
"""

from __future__ import annotations

from . import geo, openair
from .aerodromes import FEET, Aerodrome, Runway

# The circuit path: downwind leg abeam, turns beyond the threshold.
#
# **Measured off the AIP's own charts, not assumed.** The VOC chart at
# `aim.rlp.cz/vfrmanual/actual/ad/{ident}_voc.jpg` draws the published circuit, and the
# ATZ ring on it is a known 5 500 m radius, which gives the scale to within a few metres:
#
#   LKCAST, RWY 10/28, 500 m strip: two rectangles abutting on the runway, each about
#   2 950 m long and 1 300 m wide -- 2 661 m across for the pair, 1 293 m beyond each
#   threshold. LKTA, 1 100 + 850 m: both circuits together span 4 672 x 4 161 m.
#
# The lesson is that **circuit size barely tracks runway length**: a 500 m SLZ strip flies
# a circuit nearly as large as a 1 100 m aerodrome, because the size is set by how an
# aeroplane turns, not by how long the tarmac is. An earlier version scaled these with
# the runway and made the SLZ bands less than half the published size.
BESIDE_M = 1300.0   # runway centreline to the downwind leg (measured 1277-1330 m)
BEYOND_M = 1300.0   # threshold to the turn (measured 1293 m)

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


def dimensions(runway: Runway) -> tuple[float, float]:
    """How far abeam the downwind leg sits, and how far past each threshold it turns.

    The runway is deliberately ignored — see the measurements above. It stays an
    argument because that is the thing you would reach for if this ever does need to
    vary, and because every caller already has one.
    """
    return BESIDE_M, BEYOND_M


def box(runway: Runway, beside: float | None = None, beyond: float | None = None):
    """The filled rectangle the band is built around. Kept for measuring against."""
    fitted = dimensions(runway)
    beside = fitted[0] if beside is None else beside
    beyond = fitted[1] if beyond is None else beyond
    frame = _Frame(runway)
    return _rectangle(frame, frame.half + beyond, beside)


def ribbon(runway: Runway, side: int = 1, beside: float | None = None,
           beyond: float | None = None, width: float = RIBBON_M, gap: float = GAP_M):
    """One side's circuit, as a band tracing that rectangle: a simple closed ring.

    **The rectangle runs from the runway outward, not around the field.** The AIP draws
    two of them per runway, abutting along the runway itself — measured at LKCAST, each
    is about 2 950 m long and 1 300 m wide, and together they fill the box. An earlier
    version drew a single ring at ±`beside` with a hole in the middle, which put the
    whole ATZ inside the hole: no marking at all over the field, the approach or the
    climb-out, which is precisely where the aeroplanes are lowest.

    `side` is +1 or −1, the two sides of the runway. Traced outer edge round, then back
    along the inner edge, with a `gap` slit so the ring never touches itself.
    """
    fitted = dimensions(runway)
    beside = fitted[0] if beside is None else beside
    beyond = fitted[1] if beyond is None else beyond
    frame = _Frame(runway)
    h = width / 2
    a = frame.half + beyond            # half-length of the circuit rectangle
    edge = gap / 2
    mid = beside / 2                   # the slit sits mid-way up one short end
    s = 1 if side >= 0 else -1

    return [frame.point(along, s * across) for along, across in (
        # Outer edge, from one lip of the slit all the way round to the other.
        (a + h, mid + edge),
        (a + h, beside + h),
        (-(a + h), beside + h),
        (-(a + h), -h),                # the runway-side edge, straddling the centreline
        (a + h, -h),
        (a + h, mid - edge),
        # Across the band at the slit, then the inner edge back.
        (a - h, mid - edge),
        (a - h, h),
        (-(a - h), h),
        (-(a - h), beside - h),
        (a - h, beside - h),
        (a - h, mid + edge),
    )]


def ceiling_ft(field: Aerodrome) -> float | None:
    """Circuit altitude in feet AMSL, published where the AIP states one."""
    if field.circuit_ft:
        return field.circuit_ft
    if field.elevation_ft is not None:
        return field.elevation_ft + DEFAULT_CIRCUIT_AGL_FT
    return None


def _name(field: Aerodrome, runway: Runway, ceiling: float | None, published: bool,
          side: str = "") -> str:
    """`est` marks a number the AIP did not publish — an assumed 1 000 ft circuit height,
    or a runway reconstructed from the reference point and a heading rounded to 10°.
    Both apply to every SLZ field, none of which publishes a circuit altitude.

    **The operating hours go last, because the name is the only channel there is.**
    XCTrack reads a schedule for the airspace it downloads from xcontest and honours it —
    hidden when inactive, grey when it is about to activate — but an imported OpenAir
    file carries no schedule at all, and there is no record to put one in. So this band
    is drawn at three in the morning in January exactly as it is on a Saturday, and the
    one place a pilot can be told otherwise is the name XCTrack shows on a tap.
    """
    parts = [f"OKRUH {field.icao}"]
    if field.name:
        parts.append(field.name)
    parts.append(f"RWY {runway.name}")
    if side:
        parts.append(side)
    if ceiling is not None:
        metres = round(ceiling * FEET / 10) * 10
        parts.append(f"{round(ceiling)}ft/{metres}m")
    if not published or runway.estimated:
        parts.append("est")
    if field.circuit_note:
        parts.append(field.circuit_note)
    schedule = field.hours.short()
    if schedule:
        parts.append(schedule)
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
        heading = geo.bearing(
            runway.low_lat, runway.low_lon, runway.high_lat, runway.high_lon
        )
        # One per side, as the AIP draws them. They share the runway leg, so the two
        # overlap in a band 300 m wide along the centreline — which is the leg both
        # circuits actually fly, so the overlap is the truth rather than an artefact.
        for side in (1, -1):
            where = geo.cardinal((heading + side * 90) % 360)
            out.append(
                openair.Airspace(
                    name=_name(field, runway, ceiling, published, where),
                    airspace_class="Q",
                    floor="GND",
                    ceiling=f"{round(ceiling)}ft AMSL",
                    frequency=field.frequency,
                    points=ribbon(runway, side),
                    meta={"icao": field.icao, "kind": "circuit",
                          "runway": runway.name, "side": where,
                          "hours": field.hours.payload()},
                )
            )
    return out

"""The okruh: where the landing aeroplanes are.

A paraglider may fly in a Czech ATZ, but not through the traffic circuit. This draws
each circuit as a **band following the circuit path** — 300 m wide, hollow inside —
**where the AIP's own VOC chart draws it, at the size it draws it** (`voc.py`, October
2026). The rectangles run from the runway outward, not around the field: an earlier
version drew a single ring at ±1 300 m with a hole in the middle, and at an SLZ field,
whose ATZ is only ~976 m in radius, the entire ATZ fell inside that hole. Nothing was
marked over the field, the approach or the climb-out — the ground where an aeroplane
is lowest and least able to avoid anybody.

**Why a band and not a filled box.** The obvious representation would be XCTrack's
obstacle layer, and it is not available: obstacles are a curated per-country download
from airspace.xcontest.org (Austria, France, Germany, Italy, Slovenia, Switzerland —
not Czechia), there is no import path, and the request for one has been open as
xctrack-public#855 since April 2022. An obstacle there is also a *line with an
altitude* — a power line or a cable car — which a volume of circling traffic is not.
So this stays OpenAir, but takes the shape the idea was reaching for: a band that reads
like the circuit it represents, rather than a slab over everything within it.

**The published side, and the mirror only where the AIP says gliders fly it.** Most
charts draw the circuit on one side of the runway, and the band goes there. Until
October 2026 every runway had a band on both sides, on the reasoning that the glider
circuit is *often* the mirror of the powered one; often is not a reason to mark a side
nobody publishes (the pilot's call). The mirror is added where the AIP's text says the
gliders fly the other side — LKBE `gliders RWY 06, 09L/R - right` against `left hand`
for aeroplanes, LKCB, LKHK, LKTD, LKVL, LKZB — which `aerodromes.circuit_note` reports
as *gliders mirrored*.

A runway the charts could not measure keeps a standard box, the measured median,
on the side the text states (`RWY 12 left`, `to the north`) and on both sides where it
states none — there is then no published side to prefer, and one side picked at random
would be wrong half the time.

**The band is cut by a small gap rather than closed around a hole.** OpenAir has no
hole primitive, and the alternative — tracing the outer ring into the inner one through
a zero-width slit — makes a polygon that touches itself, which different point-in-
polygon implementations resolve differently: even-odd gives the hollow centre, nonzero
winding fills it in. A real 60 m gap makes the ring a *simple* polygon that every
implementation reads identically. The cost is a 60 m break in one short end of the
band, which is nothing against a 300 m width.

The shapes come off the AIP's own charts, but the band is still this tool's drawing
and not a published boundary. `AN` says so.

Ceiling is the published circuit altitude where there is one. That is an *altitude*
AMSL, which is what OpenAir wants and what a paraglider's instrument shows.
"""

from __future__ import annotations

import re

from . import geo, openair, voc
from .aerodromes import FEET, Aerodrome, Runway

# The standard box, for a runway whose chart has no rectangle to measure: downwind leg
# abeam, turns beyond the threshold. **The medians of the measured circuits** (`voc`):
# at an SLZ strip 1 260 m abeam and 1 240 m past the threshold (quartiles 1 100-1 530),
# at an ICAO aerodrome 1 490 and 1 550 (quartiles within ±60 m). **Circuit size barely
# tracks runway length** — a 500 m strip flies a circuit nearly as large as a 1 100 m
# aerodrome's, because the size is set by how an aeroplane turns — so neither scales
# with the runway.
BESIDE_M = 1300.0   # runway centreline to the downwind leg, SLZ strip
BEYOND_M = 1300.0   # threshold to the turn, SLZ strip
AERODROME_BESIDE_M = 1500.0
AERODROME_BEYOND_M = 1550.0

# How wide the band around that path is, and the gap that keeps the ring simple.
RIBBON_M = 300.0
GAP_M = 60.0
# The maps' copy needs no 60 m: their coordinates are floats, not OpenAir's rounded
# seconds, and a slit that wide drawn as a wall across the band read as a hole in the
# circuit — on every band, now that each ends where its chart has it. 2 m keeps the
# ring simple and is under a pixel at any zoom the map opens at.
MAP_GAP_M = 2.0

# When the AIP publishes no circuit altitude, fall back to this above the aerodrome.
# 1000 ft is the standard light-aircraft circuit height.
DEFAULT_CIRCUIT_AGL_FT = 1000.0


class _Frame:
    """The runway's own axes: x along it from the midpoint, y across to the right —
    turned `turn` degrees clockwise where the chart draws the circuit at an angle."""

    def __init__(self, runway: Runway, turn: float = 0.0):
        self.heading = (geo.bearing(
            runway.low_lat, runway.low_lon, runway.high_lat, runway.high_lon
        ) + turn) % 360
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


def band(frame: _Frame, a0: float, a1: float, c0: float, c1: float,
         width: float = RIBBON_M, gap: float = GAP_M):
    """A circuit rectangle — along `a0`..`a1`, across `c0`..`c1` in `frame` — as a band
    tracing its edge: a simple closed ring.

    Traced outer edge round, then back along the inner edge, with a `gap` slit mid-way up
    the `a1` end so the ring never touches itself.
    """
    h = width / 2
    edge = gap / 2
    mid = (c0 + c1) / 2
    return [frame.point(along, across) for along, across in (
        # Outer edge, from one lip of the slit all the way round to the other.
        (a1 + h, mid + edge),
        (a1 + h, c1 + h),
        (a0 - h, c1 + h),
        (a0 - h, c0 - h),
        (a1 + h, c0 - h),
        (a1 + h, mid - edge),
        # Across the band at the slit, then the inner edge back.
        (a1 - h, mid - edge),
        (a1 - h, c0 + h),
        (a0 + h, c0 + h),
        (a0 + h, c1 - h),
        (a1 - h, c1 - h),
        (a1 - h, mid + edge),
    )]


def ribbon(runway: Runway, side: int = 1, beside: float | None = None,
           beyond: float | None = None, width: float = RIBBON_M, gap: float = GAP_M):
    """The standard box on one side, as a band: from the runway out to `beside`.

    **The rectangle runs from the runway outward, not around the field.** An earlier
    version drew a single ring at ±`beside` with a hole in the middle, which put the
    whole ATZ inside the hole: no marking at all over the field, the approach or the
    climb-out, which is precisely where the aeroplanes are lowest.

    `side` is +1 (right of the low→high direction) or −1 (left).
    """
    fitted = dimensions(runway)
    beside = fitted[0] if beside is None else beside
    beyond = fitted[1] if beyond is None else beyond
    frame = _Frame(runway)
    a = frame.half + beyond
    c0, c1 = (0.0, beside) if side >= 0 else (-beside, 0.0)
    return band(frame, -a, a, c0, c1, width, gap)


def _ends(designators: str) -> set[str]:
    """`06,09L/R` → {06, 09L, 09R}."""
    out = set()
    for part in designators.split(","):
        number = re.match(r"\d{2}", part)
        if not number:
            continue
        suffixes = re.findall(r"[LRC]", part[2:]) or [""]
        out.update(number.group() + x for x in suffixes)
    return out


def _is(end: str, said: set[str]) -> bool:
    return end in said or end[:2] in said


def published_sides(field: Aerodrome, runway: Runway) -> tuple[int, ...]:
    """The sides of this runway the AIP's text puts the circuit on: +1 right of the
    low→high direction, −1 left. Both where the text says nothing usable about it.

    A left-hand circuit flown toward the high end lies left of low→high; flown toward
    the low end, its left is low→high's right.
    """
    note = field.circuit_note or ""
    sides: set[int] = set()
    for designators, hand in re.findall(r"RWY ([\dLRC/,]+) (left|right)", note):
        said = _ends(designators)
        sign = 1 if hand == "right" else -1
        if _is(runway.low, said):
            sides.add(sign)
        if _is(runway.high, said):
            sides.add(-sign)
    if re.search(r"all RWY|both sides", note):
        sides.update((1, -1))
    compass = re.search(r"to the (north|south|east|west)", note)
    if compass:
        bearing = {"north": 0, "east": 90, "south": 180, "west": 270}[compass.group(1)]
        right = (_Frame(runway).heading + 90) % 360
        sides.add(1 if abs((bearing - right + 180) % 360 - 180) < 90 else -1)
    return tuple(sorted(sides, reverse=True)) or (1, -1)


def circuit_rects(field: Aerodrome, runway: Runway) -> tuple[_Frame, list[tuple]]:
    """The frame and the rectangles to draw for one runway: measured off its chart where
    `voc` has it, the standard box on the published sides otherwise."""
    measured = voc.CHARTS.get(field.icao, {}).get("runways", {}).get(runway.name)
    if measured is None:
        frame = _Frame(runway)
        # An ICAO aerodrome's ident is four letters; an SLZ strip's, six.
        aerodrome = len(field.icao) == 4
        beside = AERODROME_BESIDE_M if aerodrome else BESIDE_M
        a = frame.half + (AERODROME_BEYOND_M if aerodrome else BEYOND_M)
        return frame, [(-a, a, 0.0, beside) if side > 0 else (-a, a, -beside, 0.0)
                       for side in published_sides(field, runway)]
    frame = _Frame(runway, measured["turn"])
    rects = []
    for a0, a1, c0, c1 in measured["rects"]:
        # Two rectangles abutting on the runway, read as one: split them there.
        if c0 < -300 < 300 < c1:
            rects += [(a0, a1, c0, 0.0), (a0, a1, 0.0, c1)]
        else:
            rects.append((a0, a1, c0, c1))
    if "gliders mirrored" in (field.circuit_note or ""):
        drawn = {1 if c0 + c1 > 0 else -1 for _, _, c0, c1 in rects}
        rects += [(a0, a1, -c1, -c0) for a0, a1, c0, c1 in rects
                  if (-1 if c0 + c1 > 0 else 1) not in drawn]
    return frame, rects


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
    """Every runway's circuit at this aerodrome, one band per rectangle.

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
        frame, rects = circuit_rects(field, runway)
        for a0, a1, c0, c1 in rects:
            where = geo.cardinal((frame.heading + (90 if c0 + c1 > 0 else -90)) % 360)
            out.append(
                openair.Airspace(
                    name=_name(field, runway, ceiling, published, where),
                    airspace_class="Q",
                    floor="GND",
                    ceiling=f"{round(ceiling)}ft AMSL",
                    frequency=field.frequency,
                    points=band(frame, a0, a1, c0, c1),
                    meta={"icao": field.icao, "kind": "circuit",
                          "runway": runway.name, "side": where,
                          "hours": field.hours.payload(),
                          "map_points": band(frame, a0, a1, c0, c1, gap=MAP_GAP_M)},
                )
            )
    return out

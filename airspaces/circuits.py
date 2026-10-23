"""The okruh: where the landing aeroplanes are.

A paraglider may fly in a Czech ATZ, but not through the traffic circuit. This draws
each circuit as a **band following the circuit path** — 300 m wide, hollow inside —
**exactly as the AIP's own VOC chart draws it** (`voc.py`, October 2026): its outline
traced point by point, slanted legs, teardrops and one-way hooks included. The circuits
run from the runway outward, not around the field: an earlier
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

**A band is two halves, not a ring with a gap.** OpenAir has no hole primitive, and a
ring traced into itself through a zero-width slit touches itself, which readers fill
differently. Until October 2026 the band carried a 60 m break for it, which showed on
the map as a hole in the circuit; now `band` cuts each loop in two simple polygons that
meet exactly.

The shapes come off the AIP's own charts, but the band is still this tool's drawing
and not a published boundary. `AN` says so.

Ceiling is the published circuit altitude where there is one. That is an *altitude*
AMSL, which is what OpenAir wants and what a paraglider's instrument shows.
"""

from __future__ import annotations

import math
import re

from . import geo, openair, voc
from .aerodromes import FEET, Aerodrome, Runway

# The standard box, for a runway whose chart has no readable scale: downwind leg
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

# How wide the band around the circuit's path is.
RIBBON_M = 300.0

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


def _offset(points, d, closed):
    """`points` moved `d` metres to their left (mitred), as a closed ring or an open path."""
    n = len(points)
    out = []
    for i in range(n):
        normals = []
        for j, k in ((i - 1, i), (i, i + 1)):
            if not closed and (j < 0 or k >= n):
                continue
            (x0, y0), (x1, y1) = points[j % n], points[k % n]
            length = math.hypot(x1 - x0, y1 - y0) or 1.0
            normals.append((-(y1 - y0) / length, (x1 - x0) / length))
        if len(normals) == 1:
            nx, ny = normals[0]
            scale = 1.0
        else:
            (ax, ay), (bx, by) = normals
            nx, ny = ax + bx, ay + by
            # A mitre, capped where a corner is so sharp it would shoot off.
            scale = 1.0 / max(0.25, (1.0 + ax * bx + ay * by))
        out.append((points[i][0] + d * nx * scale, points[i][1] + d * ny * scale))
    return out


def _area(points):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
               in zip(points, points[1:] + points[:1])) / 2


def _split_at(ring, at):
    """Index of the edge of `ring` nearest the point `at`, and the parameter along it."""
    best = None
    for i in range(len(ring)):
        (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % len(ring)]
        dx, dy = x1 - x0, y1 - y0
        t = max(0.0, min(1.0, ((at[0] - x0) * dx + (at[1] - y0) * dy) / (dx * dx + dy * dy or 1)))
        d = math.hypot(x0 + t * dx - at[0], y0 + t * dy - at[1])
        if best is None or d < best[0]:
            best = (d, i, t)
    return best[1], best[2]


def band(points, closed=True, at=(0.0, 0.0), width: float = RIBBON_M):
    """A circuit outline (metres, a local plane) as the band a paraglider keeps out of.

    **No gap.** OpenAir cannot express a ring with a hole, and closing one through a
    zero-width slit makes a polygon that touches itself, which readers fill differently
    (even-odd hollow, nonzero solid). Until October 2026 the band carried a 60 m break
    for it; now a closed band is cut into two halves at two points — the one nearest
    `at` (the runway's midpoint) and the one half-way round — and each half is a simple
    polygon. The halves meet exactly, so nothing reads as open. An open path (a hook or
    a U the chart draws for a one-way strip) is a single simple polygon.
    """
    h = width / 2
    points = list(points)
    if not closed:
        left, right = _offset(points, h, False), _offset(points, -h, False)
        return [left + right[::-1]]
    if _area(points) < 0:
        points = points[::-1]                      # anticlockwise: left is inside
    inner, outer = _offset(points, h, True), _offset(points, -h, True)
    n = len(points)
    i, t = _split_at(points, at)
    # The second cut half-way round the perimeter.
    lengths = [math.dist(points[k], points[(k + 1) % n]) for k in range(n)]
    total = sum(lengths)
    goal = (sum(lengths[:i]) + t * lengths[i] + total / 2) % total
    j, run = 0, 0.0
    while run + lengths[j] < goal:
        run += lengths[j]
        j += 1
    u = (goal - run) / (lengths[j] or 1)

    def along(ring, k, f):
        (x0, y0), (x1, y1) = ring[k], ring[(k + 1) % n]
        return (x0 + f * (x1 - x0), y0 + f * (y1 - y0))

    def half(k0, f0, k1, f1):
        """Outer from cut (k0, f0) round to cut (k1, f1), then the inner back."""
        steps = [(k0 + m) % n for m in range(1, (k1 - k0) % n + 1)]
        if k0 == k1 and f1 <= f0:
            steps = [(k0 + m) % n for m in range(1, n + 1)]
        out = [along(outer, k0, f0)] + [outer[k] for k in steps] + [along(outer, k1, f1)]
        back = [along(inner, k1, f1)] + [inner[k] for k in reversed(steps)] + [along(inner, k0, f0)]
        return out + back

    return [half(i, t, j, u), half(j, u, i, t)]


def standard_box(runway: Runway, side: int, beside: float = BESIDE_M,
                 beyond: float = BEYOND_M):
    """The standard box on one side, as (lat, lon) corners: from the runway out to
    `beside`. `side` is +1 (right of the low→high direction) or −1 (left).

    **The rectangle runs from the runway outward, not around the field.** An earlier
    version drew a single ring at ±`beside` with a hole in the middle, which put the
    whole ATZ inside the hole: no marking at all over the field, the approach or the
    climb-out, which is precisely where the aeroplanes are lowest.
    """
    frame = _Frame(runway)
    a = frame.half + beyond
    c = beside if side >= 0 else -beside
    return [frame.point(-a, 0.0), frame.point(a, 0.0), frame.point(a, c), frame.point(-a, c)]


def ribbon(runway: Runway, side: int = 1, beside: float = BESIDE_M,
           beyond: float = BEYOND_M, width: float = RIBBON_M):
    """The standard box on one side as its band: two (lat, lon) halves."""
    mid = ((runway.low_lat + runway.high_lat) / 2, (runway.low_lon + runway.high_lon) / 2)
    plane = geo.Plane(*mid)
    corners = [plane.to_xy(*p) for p in standard_box(runway, side, beside, beyond)]
    return [[plane.to_ll(*q) for q in part] for part in band(corners, True, (0.0, 0.0), width)]


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


def _mirror(points, a, b):
    """`points` reflected across the line through `a` and `b`."""
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    k = dx * dx + dy * dy or 1.0
    out = []
    for x, y in points:
        t = ((x - ax) * dx + (y - ay) * dy) / k
        px, py = ax + t * dx, ay + t * dy
        out.append((2 * px - x, 2 * py - y))
    return out


def _side(points, a, b):
    """+1 if the outline lies right of a→b, −1 if left."""
    (ax, ay), (bx, by) = a, b
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    return 1 if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) < 0 else -1


def circuit_shapes(field: Aerodrome, runway: Runway, plane: geo.Plane):
    """The outlines to draw for one runway, in `plane`'s metres: `(closed, points)`.

    Traced off its VOC chart where `voc` has it — metres from the reference point, which
    is the chart's centre — and the standard box on the published sides otherwise.
    """
    a = plane.to_xy(runway.low_lat, runway.low_lon)
    b = plane.to_xy(runway.high_lat, runway.high_lon)
    traced = voc.CHARTS.get(field.icao, {}).get("runways", {}).get(runway.name)
    if traced is None:
        # An ICAO aerodrome's ident is four letters; an SLZ strip's, six.
        aerodrome = len(field.icao) == 4
        beside = AERODROME_BESIDE_M if aerodrome else BESIDE_M
        beyond = AERODROME_BEYOND_M if aerodrome else BEYOND_M
        return [(True, [plane.to_xy(*p) for p in standard_box(runway, side, beside, beyond)])
                for side in published_sides(field, runway)]
    centre = geo.Plane(field.lat, field.lon)
    shapes = [(s["closed"], [plane.to_xy(*centre.to_ll(e, n)) for e, n in s["points"]])
              for s in traced]
    if "gliders mirrored" in (field.circuit_note or "") and shapes:
        drawn = {_side(p, a, b) for _, p in shapes}
        shapes += [(c, _mirror(p, a, b)) for c, p in shapes if -_side(p, a, b) not in drawn]
    return shapes


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
    """Every runway's circuit at this aerodrome: each band as its two halves.

    Class `Q`: orange and silent in XCTrack. The box sits inside an ATZ that already
    alerts on its boundary, so a second alert a kilometre later would only train the
    pilot to dismiss it.
    """
    ceiling = ceiling_ft(field)
    if ceiling is None:
        return []
    published = field.circuit_ft is not None
    out = []
    plane = geo.Plane(field.lat, field.lon) if field.lat is not None else None
    for runway in field.runways:
        if plane is None:
            plane = geo.Plane(runway.low_lat, runway.low_lon)
        a = plane.to_xy(runway.low_lat, runway.low_lon)
        b = plane.to_xy(runway.high_lat, runway.high_lon)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        heading = geo.bearing(runway.low_lat, runway.low_lon, runway.high_lat, runway.high_lon)
        for closed, points in circuit_shapes(field, runway, plane):
            where = geo.cardinal((heading + 90 * _side(points, a, b)) % 360)
            for k, part in enumerate(band(points, closed, mid)):
                out.append(
                    openair.Airspace(
                        name=_name(field, runway, ceiling, published, where),
                        airspace_class="Q",
                        floor="GND",
                        ceiling=f"{round(ceiling)}ft AMSL",
                        frequency=field.frequency,
                        points=[plane.to_ll(*q) for q in part],
                        meta={"icao": field.icao, "kind": "circuit",
                              "runway": runway.name, "side": where, "part": k,
                              "hours": field.hours.payload()},
                    )
                )
    return out

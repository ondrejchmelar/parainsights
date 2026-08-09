"""OpenAir: read the base file, write one XCTrack will actually load.

**The writer emits only `AC AN AH AL AF V DP DC DB`.** That restriction is not
tidiness, it is two failures observed in XCTrack:

- `AG` (the label-placement record, which Aeroklub's own file uses 204 times) is
  rejected outright with *"Unsupported command"*.
- An `AC` block missing any of `AN`/`AH`/`AL` does not fail on itself. It fails on the
  *next* `AC`, with *"Duplicate AC record"* — so the reported line is never the broken
  one. `Airspace.records()` therefore refuses to emit a block that is missing them
  rather than trusting the caller.

Colour comes from the class and nothing else, so the class is the only lever there is:

| class | XCTrack |
|---|---|
| `Q` | orange, no alert |
| `W` | green, alerts |
| anything else | red |

Which is why an ATZ goes out as `W` (green, and an alert on the boundary is right —
you are in someone's traffic zone) and a circuit box as `Q` (orange, silent, because
it sits inside an ATZ that has already alerted).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# Metres per nautical mile. OpenAir's DC radius is in NM, always.
NM = 1852.0

SAFE_RECORDS = ("AC", "AN", "AH", "AL", "AF", "V", "DP", "DC", "DB")


def dms(value: float, axis: str) -> str:
    """A coordinate as OpenAir's `DD:MM:SS N`.

    Seconds are rounded, and rounding 59.6 has to carry into minutes and degrees or
    the file contains `49:24:60 N`, which parsers variously reject or read as 49:24:00.
    """
    hemis = "NS" if axis == "lat" else "EW"
    sign = hemis[0] if value >= 0 else hemis[1]
    total = round(abs(value) * 3600)
    degrees, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    width = 2 if axis == "lat" else 3
    return f"{degrees:0{width}d}:{minutes:02d}:{seconds:02d} {sign}"


def point(lat: float, lon: float) -> str:
    return f"{dms(lat, 'lat')} {dms(lon, 'lon')}"


@dataclass
class Airspace:
    """One airspace, in the terms OpenAir can express."""

    name: str
    airspace_class: str
    floor: str
    ceiling: str
    frequency: str | None = None
    centre: tuple[float, float] | None = None
    radius_nm: float | None = None
    points: list[tuple[float, float]] = field(default_factory=list)
    # Free-form, ours; never written to the file.
    meta: dict = field(default_factory=dict)

    def records(self) -> list[str]:
        if not (self.name and self.floor and self.ceiling and self.airspace_class):
            raise ValueError(
                f"{self.name or '<unnamed>'}: AC needs AN, AH and AL, or XCTrack "
                "reports 'Duplicate AC record' against the *following* airspace"
            )
        out = [
            f"AC {self.airspace_class}",
            f"AN {self.name}",
            f"AH {self.ceiling}",
            f"AL {self.floor}",
        ]
        if self.frequency:
            out.append(f"AF {self.frequency}")
        if self.radius_nm is not None and self.centre is not None:
            out.append(f"V X={point(*self.centre)}")
            out.append(f"DC {self.radius_nm:.4f}".rstrip("0").rstrip("."))
        else:
            out.extend(f"DP {point(lat, lon)}" for lat, lon in self.points)
        return out


def write(airspaces: list[Airspace], header: str = "") -> str:
    """The complete file. `\\r\\n`, because that is what every other OpenAir file uses
    and at least one parser in the wild treats a bare `\\n` as part of the last field."""
    lines: list[str] = []
    for raw in header.splitlines():
        lines.append(f"* {raw}".rstrip())
    if header:
        lines.append("*")
    for airspace in airspaces:
        lines.extend(airspace.records())
        lines.append("")
    return "\r\n".join(lines) + "\r\n"


_COORD = re.compile(
    r"(\d+)[:\s]+(\d+(?:\.\d+)?)(?:[:\s]+([\d.]+))?\s*([NS])"
    r"[\s,]+(\d+)[:\s]+(\d+(?:\.\d+)?)(?:[:\s]+([\d.]+))?\s*([EW])",
    re.I,
)


def parse_coord(text: str) -> tuple[float, float] | None:
    """A `DD:MM:SS N DDD:MM:SS E` pair. Seconds are optional — the base file mixes
    `50:07:30 N` with `50:07.5 N` and both have to read the same."""
    match = _COORD.search(text)
    if not match:
        return None
    g = match.groups()
    lat = int(g[0]) + float(g[1]) / 60 + (float(g[2]) if g[2] else 0) / 3600
    lon = int(g[4]) + float(g[5]) / 60 + (float(g[6]) if g[6] else 0) / 3600
    return (-lat if g[3].upper() == "S" else lat, -lon if g[7].upper() == "W" else lon)


def _arc(centre, start, end, clockwise, steps=48):
    """Points along a `DB` arc, for display. XCTrack gets the `DB` record itself."""
    from . import geo

    plane = geo.Plane(*centre)
    sx, sy = plane.to_xy(*start)
    ex, ey = plane.to_xy(*end)
    radius = (math.hypot(sx, sy) + math.hypot(ex, ey)) / 2
    a0, a1 = math.atan2(sy, sx), math.atan2(ey, ex)
    if clockwise:
        while a1 > a0:
            a1 -= 2 * math.pi
    else:
        while a1 < a0:
            a1 += 2 * math.pi
    return [
        plane.to_ll(radius * math.cos(a0 + (a1 - a0) * i / steps),
                    radius * math.sin(a0 + (a1 - a0) * i / steps))
        for i in range(steps + 1)
    ]


def read(text: str) -> list[Airspace]:
    """Parse an OpenAir file into airspaces with resolved outlines.

    Tolerant on input in a way `write` is not on output: the base file uses `AG`, `AY`,
    `SP` and `SB`, all of which are simply skipped. Arcs (`DB`) and circles (`DC`) are
    expanded into `points` so a renderer has one thing to draw, while `centre`/`radius`
    survive for anything that would rather keep the circle.
    """
    out: list[Airspace] = []
    current: Airspace | None = None
    centre: tuple[float, float] | None = None
    clockwise = True

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        head, _, rest = line.partition(" ")
        head, rest = head.upper(), rest.strip()
        if head == "AC":
            current = Airspace(name="", airspace_class=rest, floor="", ceiling="")
            out.append(current)
            centre, clockwise = None, True
        elif current is None:
            continue
        elif head == "AN":
            current.name = rest
        elif head == "AH":
            current.ceiling = rest
        elif head == "AL":
            current.floor = rest
        elif head == "AF":
            current.frequency = rest
        elif head == "V":
            key, _, value = rest.partition("=")
            key = key.strip().upper()
            if key == "X":
                centre = parse_coord(value)
            elif key == "D":
                clockwise = "-" not in value
        elif head == "DP":
            got = parse_coord(rest)
            if got:
                current.points.append(got)
        elif head == "DC" and centre:
            radius = float(re.sub(r"[^\d.]", "", rest.split("*")[0]) or 0)
            current.centre, current.radius_nm = centre, radius
            current.points.extend(_circle_points(centre, radius * NM))
        elif head == "DB" and centre:
            halves = rest.split(",")
            if len(halves) == 2:
                start, end = parse_coord(halves[0]), parse_coord(halves[1])
                if start and end:
                    current.points.extend(_arc(centre, start, end, clockwise))
    return [a for a in out if a.points]


def _circle_points(centre, radius_m, steps=64):
    from . import geo

    plane = geo.Plane(*centre)
    return [
        plane.to_ll(radius_m * math.cos(2 * math.pi * i / steps),
                    radius_m * math.sin(2 * math.pi * i / steps))
        for i in range(steps + 1)
    ]


def circle_points(centre, radius_m, steps=64):
    """A circle as a ring of points, for drawing."""
    return _circle_points(centre, radius_m, steps)

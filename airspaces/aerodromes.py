"""Aerodromes: reference point, circuit altitude, runways, and which way the circuit goes.

Two sources, because neither is enough alone. The RLP VFR manual publishes the
reference point, the elevation and the circuit altitude in a fixed header line, and the
traffic-circuit rules in prose. OurAirports publishes runway *threshold coordinates*,
which the VFR manual does not — it gives magnetic runway directions only, and a circuit
built from a reference point plus a magnetic heading is wrong by however far the
reference point sits from the runway, which at a field with two strips is hundreds of
metres.

Measured over all 82 ATZ aerodromes: the reference point parses for 81, the circuit
altitude for 80, and OurAirports has both thresholds for 137 of 140 Czech runways.

Handedness is the part that does not parse cleanly. The AIP says it five different
ways — `RWY 27 - left`, `Traffic circuits on both RWYs are performed to the left`,
`Carry out the traffic circuits to the north`, `The traffic circuits - right hand and
left hand`, and at two aerodromes nothing at all. `circuit_note` recognises all of
them and reports what it found as text, but **no geometry depends on it**: the circuit
box is drawn on both sides of the runway regardless. That is deliberate. At a Czech
aeroclub field the glider circuit is routinely the mirror of the powered one — LKBE
publishes `RWY 06, 09L/R - left hand` and then `gliders RWY 06, 09L/R - right` — so a
box on the published side alone would be quietly wrong exactly where it matters.
"""

from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass, field

FEET = 0.3048


@dataclass
class Runway:
    low: str
    high: str
    low_lat: float
    low_lon: float
    high_lat: float
    high_lon: float

    @property
    def name(self) -> str:
        return f"{self.low}/{self.high}"

    @property
    def length_m(self) -> float:
        from . import geo

        return geo.distance(self.low_lat, self.low_lon, self.high_lat, self.high_lon)


@dataclass
class Aerodrome:
    icao: str
    name: str = ""
    lat: float | None = None
    lon: float | None = None
    elevation_m: float | None = None
    elevation_ft: float | None = None
    circuit_m: float | None = None
    circuit_ft: float | None = None
    frequency: str | None = None
    circuit_note: str = ""
    runways: list[Runway] = field(default_factory=list)


def _text(page: str) -> str:
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))


_ARP = re.compile(
    r"ARP:\s*(\d+)°\s*(\d+)['′\s]+(\d+)[\"″\s]*\s*([NS])\s*,\s*"
    r"(\d+)°\s*(\d+)['′\s]+(\d+)[\"″\s]*\s*([EW])"
)
_ELEV = re.compile(r"ELEV:\s*([\d\s]+)\s*ft\s*/\s*([\d\s]+)\s*m", re.I)
_CIRCUIT = re.compile(r"Circuit:\s*([\d\s]+)\s*ft\s*/\s*([\d\s]+)\s*m", re.I)
_FREQ = re.compile(r"\b([A-ZÁ-Ž][\wá-ž]+)\s+RADIO\s+(\d{3}[,.]\d{2,3})")
_NAME = re.compile(r"\b(LK[A-Z]{2})\s*[-–]\s*([^ ]+(?: [A-ZČŘŠŽÁÉÍÓÚŮ][^ ]*)?)")

# The heading runs `LKBA - Břeclav INFO`, and a two-word aerodrome name is common
# (Česká Lípa, Dvůr Králové), so the name cannot just be the first token. These are the
# service words that follow it.
_SERVICE_WORDS = ("INFO", "RADIO", "TOWER", "AFIS", "ATIS", "GLIDING")


def _number(raw: str) -> float:
    return float(raw.replace(" ", "").replace(" ", ""))


# The ways the AIP states a circuit direction, most specific first: a per-runway
# statement beats a blanket one, and the loop stops at the first family that matches.
# "hand" is the reliable signal — it is only ever used of a circuit — which is what
# lets the looser patterns tolerate filler without catching an unrelated "left".
_HAND_RULES = (
    # `RWY 27 - left`, `RWY 06, 09L/R - left hand`
    (re.compile(r"RWY\s*([\dLRC/,\s]+?)\s*[-–:]?\s*(left|right)\s*(?:hand)?", re.I), "runway"),
    # `RWY 24 is only one-way with right hand traffic circuits` (LKSU)
    (re.compile(r"RWY\s*(\d{2}[LRC]?)[^.]{0,60}?\b(left|right)\s*hand\b", re.I), "runway"),
    # `The traffic circuits to RWY 34 are carried out to the right only` (LKTA)
    (re.compile(r"circuits?\s+to\s+RWY\s*(\d{2}[LRC]?)[^.]{0,50}?\b(left|right)\b", re.I),
     "runway"),
    # `Traffic circuits 09 left hand 27 right hand` — no RWY prefix at all (LKRY)
    (re.compile(r"\b(\d{2}[LRC]?)\s+(left|right)\s+hand\b", re.I), "runway"),
    (re.compile(r"circuits?\s+on\s+both\s+RWYs?[^.]*?\b(left|right)\b", re.I), "both runways"),
    # `Only left hand traffic circuits.` (LKTO)
    (re.compile(r"only\s+(left|right)\s+hand\s+traffic\s+circuits?", re.I), "blanket"),
    (re.compile(r"circuits?[^.]{0,40}?to the (north|south|east|west)\b", re.I), "compass"),
    (re.compile(r"circuits?\s*[-–]?\s*right hand and left hand", re.I), "both sides"),
)


def circuit_note(text: str) -> str:
    """The published circuit direction, as a short phrase, or "" when nothing is said.

    Reported, never used for geometry — see the module docstring.
    """
    found: list[str] = []
    for pattern, kind in _HAND_RULES:
        for match in pattern.finditer(text):
            if kind == "runway":
                runways = re.sub(r"\s+", "", match.group(1)).strip(",")
                if not re.match(r"^\d", runways):
                    continue
                found.append(f"RWY {runways} {match.group(2).lower()}")
            elif kind in ("both runways", "blanket"):
                found.append(f"all RWY {match.group(1).lower()}")
            elif kind == "compass":
                found.append(f"to the {match.group(1).lower()}")
            else:
                found.append("both sides")
        if found:
            break
    # Deduplicate, keeping order.
    seen, unique = set(), []
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    # The name is read on a phone in a list, so keep it short: two statements is enough
    # to convey the pattern, and the glider flag matters more than a third runway.
    note = ", ".join(unique[:2])
    if len(unique) > 2:
        note += ", …"
    if re.search(r"gliders?[^.]{0,40}\b(left|right)\b", text, re.I):
        note += ", gliders mirrored" if note else "gliders mirrored"
    return note


def parse_vfr(icao: str, page: str) -> Aerodrome:
    """One aerodrome from its VFR manual text page."""
    text = _text(page)
    field_ = Aerodrome(icao=icao)

    match = _NAME.search(text)
    if match and match.group(1) == icao:
        words = match.group(2).split()
        while words and words[-1].upper() in _SERVICE_WORDS:
            words.pop()
        field_.name = " ".join(words)

    match = _ARP.search(text)
    if match:
        g = match.groups()
        lat = int(g[0]) + int(g[1]) / 60 + int(g[2]) / 3600
        lon = int(g[4]) + int(g[5]) / 60 + int(g[6]) / 3600
        field_.lat = -lat if g[3] == "S" else lat
        field_.lon = -lon if g[7] == "W" else lon

    match = _ELEV.search(text)
    if match:
        field_.elevation_ft = _number(match.group(1))
        field_.elevation_m = _number(match.group(2))

    match = _CIRCUIT.search(text)
    if match:
        # Both units are published; keep the foot value rather than converting, so the
        # file carries the number the AIP prints.
        field_.circuit_ft = _number(match.group(1))
        field_.circuit_m = _number(match.group(2))

    match = _FREQ.search(text)
    if match:
        field_.frequency = match.group(2).replace(",", ".")

    field_.circuit_note = circuit_note(text)
    return field_


def parse_runways(csv_text: str, icaos: set[str]) -> dict[str, list[Runway]]:
    """Runways with both thresholds, from the OurAirports table."""
    out: dict[str, list[Runway]] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        icao = row["airport_ident"]
        if icao not in icaos or row.get("closed") == "1":
            continue
        try:
            runway = Runway(
                row["le_ident"] or "?",
                row["he_ident"] or "?",
                float(row["le_latitude_deg"]),
                float(row["le_longitude_deg"]),
                float(row["he_latitude_deg"]),
                float(row["he_longitude_deg"]),
            )
        except (ValueError, KeyError):
            continue
        if runway.length_m < 100:
            continue
        out.setdefault(icao, []).append(runway)
    return out


def parse_airports(csv_text: str, icaos: set[str]) -> dict[str, tuple[float, float]]:
    """Aerodrome positions, as an independent check on the VFR manual."""
    out = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row["ident"] in icaos and row["latitude_deg"]:
            out[row["ident"]] = (float(row["latitude_deg"]), float(row["longitude_deg"]))
    return out

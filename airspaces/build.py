"""Assemble the ATZ overlay from the four sources."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import aerodromes, atz, circuits, openair, sources

HEADER = """Czech ATZ and traffic circuits, for XCTrack

ATZ (class W, green): aerodrome traffic zones, GND - 4000 ft AMSL. An unpowered
paraglider may fly here, but call the aerodrome and stay out of the circuit.

OKRUH (class Q, orange): the traffic circuit, ground to the published circuit
altitude. NOT an official boundary -- a {width} m wide band following the circuit
path, {beside} m abeam the runway and turning {beyond} m beyond each threshold. It is
hollow: the ground over the runway itself is outside it. Drawn on BOTH sides,
because the glider circuit is often the mirror of the powered one. The published
circuit direction, where the AIP states one, is in the airspace name.

The band has a {gap} m break in one short end. OpenAir cannot express a polygon with
a hole, and closing the ring through a zero-width slit makes a shape that some
readers fill in and others do not; a real gap keeps it unambiguous everywhere.

This file is an ADDITION to your normal airspace. Czech ATZ are not in the XContest
or Aeroklub data unless a specific activity is active. Keep both loaded.

ATZ geometry from {atz_source}, publication LKR315A, {atz_date}.
Circuit altitudes and runway data from the RLP VFR manual and OurAirports.
{correction}
Generated {generated} by parainsights. Not for navigation; verify against the AIP."""

CORRECTION_NOTE = """
Note: the published ATZ polygons are offset {offset:.0f} m to the south-west of the
aerodrome reference points ({samples} circular zones measured, mean bearing {bearing:.0f}
deg). The RLP VFR manual's own reference points and the OurAirports database agree
with each other to 7 m and disagree with the zone file, so the zone file is the
outlier -- the signature of an S-JTSK to WGS84 conversion without the grid. Circles
here are re-centred on the published reference point and clipped polygons shifted by
the measured mean. Use --raw to reproduce the publication unchanged."""


@dataclass
class Overlay:
    airspaces: list[openair.Airspace]
    zones: list[atz.ATZ]
    fields: dict[str, aerodromes.Aerodrome]
    offset: tuple[float, float, int] = (0.0, 0.0, 0)
    atz_date: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def atz_count(self) -> int:
        return sum(1 for a in self.airspaces if a.meta.get("kind") == "atz")

    @property
    def circuit_count(self) -> int:
        return sum(1 for a in self.airspaces if a.meta.get("kind") == "circuit")

    @property
    def circle_count(self) -> int:
        return sum(1 for z in self.zones if z.is_circle)


def load_aerodromes(icaos, *, refresh: bool = False):
    """VFR manual plus OurAirports runways, for the aerodromes that have an ATZ."""
    fields: dict[str, aerodromes.Aerodrome] = {}
    for icao in sorted(icaos):
        page = sources.vfr_page(icao, refresh=refresh)
        fields[icao] = (
            aerodromes.parse_vfr(icao, page) if page else aerodromes.Aerodrome(icao=icao)
        )
    runways = aerodromes.parse_runways(sources.ourairports("runways", refresh=refresh), icaos)
    positions = aerodromes.parse_airports(
        sources.ourairports("airports", refresh=refresh), icaos
    )
    for icao, field_ in fields.items():
        field_.runways = runways.get(icao, [])
        # OurAirports is the fallback position, not the primary: the VFR manual is the
        # official publication and the two agree to 7 m where both exist.
        if field_.lat is None and icao in positions:
            field_.lat, field_.lon = positions[icao]
    return fields, positions


def build(*, correct: bool = True, refresh: bool = False, with_circuits: bool = True) -> Overlay:
    """The complete ATZ overlay."""
    geojson = sources.atz(refresh=refresh)
    zones = atz.parse(geojson)
    icaos = {z.icao for z in zones}
    fields, positions = load_aerodromes(icaos, refresh=refresh)

    # Reference points for the datum correction: the VFR manual first, OurAirports
    # where the manual has no parseable ARP.
    reference = {
        icao: (f.lat, f.lon) for icao, f in fields.items() if f.lat is not None
    }
    for icao, pos in positions.items():
        reference.setdefault(icao, pos)

    offset = atz.measure_offset(zones, reference)
    if correct:
        zones = atz.correct(zones, reference)

    out: list[openair.Airspace] = []
    notes: list[str] = []
    for zone in zones:
        field_ = fields.get(zone.icao)
        label = f"ATZ {zone.icao}"
        if field_ and field_.name:
            label += f" {field_.name}"
        if not zone.is_circle:
            label += " (clipped)"
        out.append(atz.to_airspace(zone, label, field_.frequency if field_ else None))

    if with_circuits:
        for icao in sorted(icaos):
            field_ = fields.get(icao)
            if not field_:
                continue
            made = circuits.to_airspaces(field_)
            out.extend(made)
            if not made:
                notes.append(f"{icao}: no circuit box (no runway or altitude data)")
            elif not field_.circuit_note:
                notes.append(f"{icao}: AIP states no circuit direction")

    dates = sources.airac_dates()
    return Overlay(
        airspaces=out,
        zones=zones,
        fields=fields,
        offset=offset,
        atz_date=dates[0].isoformat() if dates else "",
        notes=notes,
    )


def to_openair(overlay: Overlay, *, corrected: bool = True) -> str:
    east, north, samples = overlay.offset
    import math

    if corrected and samples >= 5:
        correction = CORRECTION_NOTE.format(
            offset=math.hypot(east, north),
            samples=samples,
            # The offset points from zone to ARP, so the error runs the other way.
            bearing=(math.degrees(math.atan2(-east, -north))) % 360,
        )
    else:
        correction = "\nGeometry reproduced from the publication unchanged."
    return openair.write(
        overlay.airspaces,
        HEADER.format(
            beside=round(circuits.BESIDE_M),
            beyond=round(circuits.BEYOND_M),
            width=round(circuits.RIBBON_M),
            gap=round(circuits.GAP_M),
            atz_source="aim.rlp.cz",
            atz_date=overlay.atz_date,
            correction=correction,
            generated=dt.date.today().isoformat(),
        ),
    )

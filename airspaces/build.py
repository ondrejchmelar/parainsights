"""Assemble the ATZ overlay from the four sources."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import aerodromes, atz, circuits, openair, sources

HEADER = """Czech ATZ and traffic circuits, for XCTrack

ATZ (class W, green): aerodrome traffic zones at the 82 ICAO aerodromes, GND -
4000 ft AMSL. An unpowered paraglider may fly here, but call the aerodrome and stay
out of the circuit.

An SLZ strip (a plocha SLZ, the ultralight fields) has NO ATZ, so the 74 of those
carry only their traffic circuit. The circles the UAS zone file publishes for them
are a drone rule, not airspace, and are left out.

OKRUH (class Q, orange): the traffic circuit, ground to the published circuit
altitude. NOT an official boundary -- a {width} m wide band tracing the circuit,
which runs from the runway out to {beside} m abeam and turns {beyond} m beyond each
threshold. TWO per runway, one each side, abutting along the runway -- which is how
the AIP draws them, and it means the shared leg runs down the runway itself. Both
sides because the glider circuit is often the mirror of the powered one. The
published circuit direction, where the AIP states one, is in the airspace name.

The dimensions were measured off the AIP's own VOC charts, where the ATZ ring gives
the scale, to about +/-10%. At LKCAST each published rectangle is about 2950 x 1300 m;
these are 3100 x 1300.

The band has a {gap} m break in one short end. OpenAir cannot express a polygon with
a hole, and closing the ring through a zero-width slit makes a shape that some
readers fill in and others do not; a real gap keeps it unambiguous everywhere.

This file is an ADDITION to your normal airspace. Czech ATZ are not in the XContest
or Aeroklub data unless a specific activity is active. Keep both loaded.

An OKRUH marked "est" is reconstructed rather than published: an assumed 1000 ft
circuit height, or a runway placed from the aerodrome reference point and a heading
rounded to 10 deg. Every SLZ field is in that case -- none publishes a circuit
altitude.

ATZ geometry from {atz_source}, {publications}, {atz_date}.
Circuit altitudes and runway data from the RLP VFR manual and OurAirports.
{correction}

=====================================================================
CHECK THIS IS STILL CURRENT, AND CHECK IT AGAINST THE AIP.

This is a snapshot, generated {generated}. The ATZ come from the AIRAC cycle
effective {atz_date} and the base airspace from {base_version}. Airspace changes
every 28-day AIRAC cycle, and a NOTAM changes it the same day. This file will
go out of date and has no way to tell you that it has.

It is INFORMATIVE ONLY. It is not a navigation source, it is not an official
publication, and it does not replace your own preflight check. The OKRUH
outlines are drawn by this tool from ordinary circuit proportions -- they are
not published boundaries.

The pilot in command remains responsible for knowing the airspace flown in.
=====================================================================

Built by parainsights."""

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

    @property
    def by_publication(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for zone in self.zones:
            counts[zone.publication] = counts.get(zone.publication, 0) + 1
        return counts

    @property
    def publication_label(self) -> str:
        return ", ".join(f"LKR315{p}" for p in sorted(self.by_publication))


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
        # Surveyed thresholds where OurAirports has them; otherwise keep the ones
        # `parse_vfr` reconstructed from the manual's runway table.
        if runways.get(icao):
            field_.runways = runways[icao]
        # OurAirports is the fallback position, not the primary: the VFR manual is the
        # official publication and the two agree to 7 m where both exist.
        if field_.lat is None and icao in positions:
            field_.lat, field_.lon = positions[icao]
    return fields, positions


def nearby_fields(zones, csv_text: str, limit: float = 2000.0):
    """Match zones to the nearest Czech airfield in OurAirports, for a human name.

    A fallback for the name only. B's fields do have a VFR manual page — under their
    own six-letter ident — and that is where the name normally comes from; this covers
    the ones whose heading does not parse, and would cover C and D, which have no page.
    73 of B's 74 land within 2 km of a listed airfield.
    """
    import csv
    import io

    listed = [
        (row["name"], float(row["latitude_deg"]), float(row["longitude_deg"]))
        for row in csv.DictReader(io.StringIO(csv_text))
        if row.get("iso_country") == "CZ" and row["latitude_deg"]
    ]
    out = {}
    for zone in zones:
        best = min(listed, key=lambda f: geo_distance(zone, f), default=None)
        if best and geo_distance(zone, best) < limit:
            out[zone.icao] = (best[0], best[1], best[2])
    return out


def geo_distance(zone, field_) -> float:
    from . import geo

    return geo.distance(zone.lat, zone.lon, field_[1], field_[2])


def build(*, correct: bool = True, refresh: bool = False, with_circuits: bool = True,
          publications=None, slz_zones: bool = False) -> Overlay:
    """The complete ATZ overlay, across every requested publication.

    **The correction is measured per publication, never across them.** Publication A is
    115 m out; B, generated by the same organisation on the same day, is right to 5 m.
    Measuring the two together would average a real error with clean data and move both.
    """
    publications = tuple(publications or sources.DEFAULT_PUBLICATIONS)
    airports_csv = sources.ourairports("airports", refresh=refresh)

    zones: list[atz.ATZ] = []
    offset = (0.0, 0.0, 0)
    fields: dict[str, aerodromes.Aerodrome] = {}
    positions: dict[str, tuple[float, float]] = {}

    for pub in publications:
        found = atz.parse(sources.atz(refresh=refresh, pub=pub), publication=pub)
        if pub == "A":
            icaos = {z.icao for z in found}
            fields, positions = load_aerodromes(icaos, refresh=refresh)
            # Reference points: the VFR manual first, OurAirports where the manual has
            # no parseable ARP.
            reference = {
                icao: (f.lat, f.lon) for icao, f in fields.items() if f.lat is not None
            }
            for icao, pos in positions.items():
                reference.setdefault(icao, pos)
            for zone in found:
                field_ = fields.get(zone.icao)
                if field_ and field_.name:
                    zone.name = field_.name
        else:
            # SLZ fields have a VFR manual page too, under their own six-letter ident —
            # `lkcast_text_en.html`. All 74 of B's do, with a reference point and a
            # runway table, which is the whole basis for their okruh.
            more, _ = load_aerodromes({z.icao for z in found}, refresh=refresh)
            fields.update(more)
            matched = nearby_fields(found, airports_csv)
            reference = {
                code: (f.lat, f.lon) for code, f in more.items() if f.lat is not None
            }
            for code, (_, lat, lon) in matched.items():
                reference.setdefault(code, (lat, lon))
            for zone in found:
                field_ = more.get(zone.icao)
                if field_ and field_.name:
                    zone.name = field_.name
                elif zone.icao in matched:
                    zone.name = matched[zone.icao][0].replace(" Airfield", "")

        measured = atz.measure_offset(found, reference)
        if pub == "A":
            offset = measured
        if correct:
            found = atz.correct(found, reference)
        zones.extend(found)

    out: list[openair.Airspace] = []
    notes: list[str] = []
    for zone in zones:
        # **An SLZ field has no ATZ.** Publication B's circles are UAS geographical
        # zones — dronview labels them `SLZ LKCAST`, and the VFR manual calls the place
        # a *neveřejná plocha SLZ*, not an aerodrome. Emitting them as green `ATZ`
        # invented 74 aerodrome traffic zones that do not exist, and left the okruh
        # looking wrong for sitting outside one. What a paraglider needs at an SLZ strip
        # is the circuit; the zone is a drone rule. Off unless asked for.
        if not zone.is_aerodrome and not slz_zones:
            continue
        field_ = fields.get(zone.icao)
        label = f"{'ATZ' if zone.is_aerodrome else 'SLZ'} {zone.icao}"
        if zone.name:
            label += f" {zone.name}"
        if not zone.is_circle:
            label += " (clipped)"
        out.append(atz.to_airspace(zone, label, field_.frequency if field_ else None))

    if with_circuits:
        for icao in sorted(fields):
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


def to_openair(overlay: Overlay, *, corrected: bool = True, base_version: str = "") -> str:
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
            publications=overlay.publication_label,
            atz_date=overlay.atz_date,
            base_version=base_version or "Aeroklub CZ_low",
            correction=correction,
            generated=dt.date.today().isoformat(),
        ),
    )

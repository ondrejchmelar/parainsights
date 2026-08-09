"""Czech ATZ, from the UAS geographical zone publication.

An ATZ is a circle of radius 5 500 m about the aerodrome reference point, GND to
4 000 ft AMSL. That is what it *is*; what RLP publishes is a polygon of up to 3 549
vertices approximating it, because the zone file is generated for drone software. Two
things follow.

**Refit the circles.** 67 of the 82 fit a circle to within 8 m, at 5 500.3 m ± 0.4 m —
the published radius exactly, recovered. Emitting `V X=` + `DC` gives eight lines where
the polygon gives three and a half thousand, and it is *more* accurate, not less,
because it drops the polygonal approximation rather than resampling it. The remaining
15 are clipped by an overlying CTR or TMA and stay polygons, simplified to 50 m.

**Correct the datum.** The fitted centres sit a systematic 110 m to the south-west of
the aerodrome reference points — mean bearing 227°, standard deviation 8°, which is a
transformation error and not scatter. Two independent sources agree with each other and
not with it: the RLP VFR manual's own published ARP and the OurAirports database are
7 m apart, and both are 110 m from the zone centre. The signature is a S-JTSK (Křovák)
to WGS84 conversion done without the transformation grid.

So a fitted circle is re-centred on the published ARP, and a clipped polygon is shifted
by the offset measured across all the circles at that same aerodrome's latitude. Pass
`correct=False` to reproduce the publication as-is. 110 m on a 5 500 m radius changes
nothing a pilot can fly, but it is a known error and there is no reason to copy it.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass

from . import geo, openair

# Everything in the publication is GND - 4000 ft AMSL, all 82 of them.
CEILING = "4000ft AMSL"
FLOOR = "GND"

# A ring within this of a circle is one. Well clear of the 8 m the true circles show
# and the 417 m of the nearest clipped one, so nothing sits near the boundary.
CIRCLE_TOLERANCE = 50.0

# The regulated ATZ radius. Every one of the 67 fits lands within 0.5 m of it, so the
# remaining spread is fit noise from the source polygon, not real variation — snapping
# removes it and stops the file carrying `DC 2.9699` next to `DC 2.97` for two zones
# that are by definition the same size.
NOMINAL_RADIUS_M = 5500.0
RADIUS_SNAP_M = 5.0

# Douglas-Peucker for the clipped polygons. 50 m takes 15 rings from 9 000 vertices
# to about 500 points total, which is a rounding error against a 5 500 m radius.
SIMPLIFY_TOLERANCE = 50.0


@dataclass
class ATZ:
    icao: str
    zone: str
    lat: float
    lon: float
    radius_m: float | None
    points: list[tuple[float, float]]
    fit_error: float
    shifted_by: float = 0.0
    publication: str = "A"
    name: str = ""

    @property
    def is_circle(self) -> bool:
        return self.radius_m is not None

    @property
    def is_aerodrome(self) -> bool:
        """A publication-A zone: a real ICAO aerodrome with a VFR manual entry."""
        return self.publication == "A"


# `905LKBA` in publication A; `LKCAST` in B; `HELLKUHIII` and `PISLK011II` in C and D.
_NUMBERED = re.compile(r"^(\d{3})(LK[A-Z]{2})$")


def split_ident(ident: str) -> tuple[str, str]:
    """(code, zone-number). Publication A prefixes the ICAO with a zone number; the
    others do not, and their idents are not ICAO codes at all."""
    match = _NUMBERED.match(ident)
    return (match.group(2), match.group(1)) if match else (ident, "")


def _ring(feature) -> list[tuple[float, float]]:
    ring = [(lat, lon) for lon, lat, *_ in feature["geometry"]["coordinates"][0]]
    # GeoJSON rings repeat the first point; a fit should not weight it twice.
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring


def parse(geojson: dict, publication: str = "A") -> list[ATZ]:
    """Every zone in the publication, as circles where they are circles."""
    out = []
    for feature in geojson.get("features", []):
        ident = feature["properties"]["ident"]
        code, zone_number = split_ident(ident)
        ring = _ring(feature)
        if len(ring) < 3:
            continue
        lat0, lon0 = geo.centroid([(lat, lon) for lat, lon in ring])
        plane = geo.Plane(lat0, lon0)
        planar = [plane.to_xy(lat, lon) for lat, lon in ring]
        cx, cy, radius, error = geo.fit_circle(planar)
        if error < CIRCLE_TOLERANCE:
            clat, clon = plane.to_ll(cx, cy)
            if abs(radius - NOMINAL_RADIUS_M) < RADIUS_SNAP_M:
                radius = NOMINAL_RADIUS_M
            # `points` is the outline to *draw*; the circle is what gets written. Keep
            # the fitted circle rather than the source ring, so a renderer shows the
            # same geometry the file carries — and 64 points rather than 3 549.
            out.append(
                ATZ(code, zone_number, clat, clon, radius,
                    openair.circle_points((clat, clon), radius), error,
                    publication=publication)
            )
        else:
            simple = geo.simplify(planar, SIMPLIFY_TOLERANCE)
            out.append(
                ATZ(
                    code,
                    zone_number,
                    lat0,
                    lon0,
                    None,
                    [plane.to_ll(x, y) for x, y in simple],
                    error,
                    publication=publication,
                )
            )
    return sorted(out, key=lambda z: z.icao)


def measure_offset(zones: list[ATZ], reference: dict[str, tuple[float, float]]):
    """Mean east/north offset in metres from published zone centre to true ARP.

    Measured only over the circular zones, where the centre is exact. Returns
    `(east, north, samples)`; the sign is the correction *to add* to the zone.
    """
    east, north = [], []
    for zone in zones:
        if not zone.is_circle or zone.icao not in reference:
            continue
        ref_lat, ref_lon = reference[zone.icao]
        m_lat, m_lon = geo.metres_per_degree(ref_lat)
        east.append((ref_lon - zone.lon) * m_lon)
        north.append((ref_lat - zone.lat) * m_lat)
    if len(east) < 5:
        return 0.0, 0.0, len(east)
    return statistics.fmean(east), statistics.fmean(north), len(east)


def correct(zones: list[ATZ], reference: dict[str, tuple[float, float]]) -> list[ATZ]:
    """Re-centre circles on the true ARP; shift clipped polygons by the mean offset.

    A circle gets its own aerodrome's reference point, which is exact. A clipped
    polygon has no single reference point to anchor to — its centre is a centroid of a
    partial ring — so it gets the offset measured across all the circles.
    """
    east, north, samples = measure_offset(zones, reference)
    if samples < 5:
        return zones
    out = []
    for zone in zones:
        if zone.is_circle and zone.icao in reference:
            lat, lon = reference[zone.icao]
            moved = geo.distance(zone.lat, zone.lon, lat, lon)
            out.append(
                ATZ(zone.icao, zone.zone, lat, lon, zone.radius_m,
                    openair.circle_points((lat, lon), zone.radius_m),
                    zone.fit_error, moved, zone.publication, zone.name)
            )
        else:
            points = [geo.offset(lat, lon, east, north) for lat, lon in zone.points]
            lat, lon = geo.offset(zone.lat, zone.lon, east, north)
            out.append(
                ATZ(zone.icao, zone.zone, lat, lon, zone.radius_m, points,
                    zone.fit_error, math.hypot(east, north),
                    zone.publication, zone.name)
            )
    return out


def to_airspace(zone: ATZ, name: str, frequency: str | None = None) -> openair.Airspace:
    """One ATZ as an OpenAir airspace.

    Class `W`: XCTrack paints `W` green and alerts on it. Green was asked for; the
    alert is arguably right anyway, since entering an ATZ means you should be listening
    on the aerodrome's frequency even though a paraglider is permitted there.

    `points` is carried even for a circle, because a renderer needs an outline —
    `Airspace.records()` writes `V X=`/`DC` whenever a radius is set and ignores them.
    """
    return openair.Airspace(
        name=name,
        airspace_class="W",
        floor=FLOOR,
        ceiling=CEILING,
        frequency=frequency,
        centre=(zone.lat, zone.lon) if zone.is_circle else None,
        radius_nm=zone.radius_m / openair.NM if zone.is_circle else None,
        points=zone.points,
        meta={"icao": zone.icao, "kind": "atz"},
    )

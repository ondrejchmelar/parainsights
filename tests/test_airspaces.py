"""Airspace module. No network: every source is a fixture under tests/data."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

from airspaces import aerodromes, atz, build, circuits, geo, openair, render_html
from airspaces.aerodromes import Aerodrome, Runway

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def zones():
    return atz.parse(json.loads((DATA / "atz_sample.json").read_text()))


def vfr(icao: str) -> Aerodrome:
    return aerodromes.parse_vfr(icao.upper(), (DATA / f"vfr_{icao}.html").read_text())


# ---------------------------------------------------------------- geodesy


def test_metres_per_degree_matches_wgs84():
    # At 50 N a degree of latitude is 111 229 m and of longitude 71 697 m on WGS84.
    m_lat, m_lon = geo.metres_per_degree(50.0)
    assert m_lat == pytest.approx(111229, abs=3)
    assert m_lon == pytest.approx(71697, abs=3)


def test_fai_sphere_would_be_wrong_here():
    """The reason this module has its own geodesy rather than reusing the viewer's.

    A 6 371 km sphere reads a 5 500 m radius as ~5 490 m — a 0.2% error that is exactly
    what made the published ATZ radius look like a ragged number instead of 5.5 km.
    The discrepancy lives in the east-west scale: the prime-vertical radius at 50 N is
    6 390 km, 0.3% larger than the FAI sphere.
    """
    _, m_lon = geo.metres_per_degree(50.0)
    sphere = 6371000.0 * math.pi / 180 * math.cos(math.radians(50.0))
    assert abs(m_lon - sphere) / m_lon > 0.002


def test_destination_and_bearing_round_trip():
    lat, lon = geo.destination(50.0, 15.0, 47.0, 5000.0)
    assert geo.distance(50.0, 15.0, lat, lon) == pytest.approx(5000.0, abs=0.5)
    assert geo.bearing(50.0, 15.0, lat, lon) == pytest.approx(47.0, abs=0.05)


def test_simplify_keeps_the_ends_and_drops_the_middle():
    line = [(x, 0.0) for x in range(0, 100, 5)]
    assert geo.simplify(line, 1.0) == [(0.0, 0.0), (95.0, 0.0)]


def test_simplify_survives_a_ring_too_deep_to_recurse():
    ring = [(math.cos(t / 500 * math.tau) * 1000, math.sin(t / 500 * math.tau) * 1000)
            for t in range(4000)]
    assert 3 < len(geo.simplify(ring, 50.0)) < 200


def test_fit_circle_recovers_a_known_circle():
    ring = [(300 + 800 * math.cos(i / 90 * math.tau), -50 + 800 * math.sin(i / 90 * math.tau))
            for i in range(90)]
    cx, cy, radius, error = geo.fit_circle(ring)
    assert (cx, cy) == pytest.approx((300, -50), abs=0.01)
    assert radius == pytest.approx(800, abs=0.01)
    assert error < 0.01


# ---------------------------------------------------------------- ATZ


def test_a_smooth_ring_becomes_an_exact_5500_m_circle(zones):
    circle = next(z for z in zones if z.icao == "LKHB")
    assert circle.is_circle
    # The published radius, recovered from a polygon that only approximates it.
    assert circle.radius_m == pytest.approx(5500, abs=3)
    assert circle.fit_error < atz.CIRCLE_TOLERANCE


def test_a_clipped_zone_stays_a_polygon_and_is_simplified(zones):
    clipped = next(z for z in zones if z.icao == "LKBR")
    assert not clipped.is_circle
    assert clipped.fit_error > atz.CIRCLE_TOLERANCE
    assert len(clipped.points) < 120


def test_every_zone_carries_an_outline_to_draw(zones):
    """Circles are written as `DC` but still need points, or the map renders nothing.

    This is the bug that made 67 of 82 ATZ invisible on the first map.
    """
    for zone in zones:
        assert len(zone.points) >= 3, zone.icao


def synthetic_circles(count=8, east=85.0, north=78.0):
    """`count` circular zones whose reference points sit a known offset away.

    The bundled fixture holds one circle, and `measure_offset` deliberately refuses to
    call an offset systematic on fewer than five, so the sample has to be built here.
    """
    zones, reference = [], {}
    for i in range(count):
        lat, lon = 49.0 + i * 0.1, 15.0 + i * 0.1
        zones.append(
            atz.ATZ(f"LK{i:02d}", "900", lat, lon, 5500.0,
                    openair.circle_points((lat, lon), 5500.0), 1.0)
        )
        reference[f"LK{i:02d}"] = geo.offset(lat, lon, east, north)
    return zones, reference


def test_correction_measures_the_offset_it_is_given():
    zones, reference = synthetic_circles()
    east, north, samples = atz.measure_offset(zones, reference)
    assert samples == 8
    assert (east, north) == pytest.approx((85.0, 78.0), abs=0.5)


def test_correction_recentres_a_circle_on_the_reference_point():
    zones, reference = synthetic_circles()
    for fixed in atz.correct(zones, reference):
        want = reference[fixed.icao]
        assert geo.distance(fixed.lat, fixed.lon, *want) < 0.5
        # The radius is the published one and must survive the move untouched.
        assert fixed.radius_m == pytest.approx(5500.0, abs=0.01)
        assert fixed.shifted_by == pytest.approx(math.hypot(85.0, 78.0), abs=1.0)


@pytest.mark.parametrize(
    "ident, code, number",
    [
        ("905LKBA", "LKBA", "905"),      # publication A: zone number + ICAO
        ("LKCAST", "LKCAST", ""),        # B: an SLZ field, not an ICAO code
        ("HELLKUHIII", "HELLKUHIII", ""),  # C: a heliport
        ("PISLK011II", "PISLK011II", ""),  # D: a landing site
    ],
)
def test_ident_forms_across_the_four_publications(ident, code, number):
    """Only A prefixes the ICAO with a zone number. Slicing `ident[3:]` unconditionally
    turned `LKCAST` into `AST`, which is why Částkovice could not be found."""
    assert atz.split_ident(ident) == (code, number)


def test_a_publication_b_zone_keeps_its_whole_ident():
    geojson = {"features": [{
        "properties": {"ident": "LKCAST"},
        "geometry": {"type": "Polygon", "coordinates": [[
            [15.144 + 0.013 * math.cos(t / 40 * math.tau),
             49.409 + 0.0088 * math.sin(t / 40 * math.tau)] for t in range(40)
        ]]},
    }]}
    zone = atz.parse(geojson, publication="B")[0]
    assert zone.icao == "LKCAST"
    assert zone.publication == "B"
    assert not zone.is_aerodrome


def test_correction_is_skipped_without_enough_samples(zones):
    """Fewer than five circles is not enough to call a systematic offset, so the
    geometry must pass through untouched rather than be shifted on noise."""
    assert atz.correct(zones, {}) == zones


def test_atz_ceiling_is_the_published_one(zones):
    space = atz.to_airspace(zones[0], "ATZ TEST")
    assert space.ceiling == "4000ft AMSL"
    assert space.floor == "GND"
    assert space.airspace_class == "W"


# ---------------------------------------------------------------- OpenAir


def test_dms_carries_a_rounded_second():
    # 49.99999 deg is 49:59:59.96, which must not be written as 49:59:60.
    assert openair.dms(49.999999, "lat") == "50:00:00 N"
    assert openair.dms(14.5, "lon") == "014:30:00 E"
    assert openair.dms(-3.25, "lat") == "03:15:00 S"


def test_longitude_is_three_digits():
    """OpenAir wants DDD for longitude; two digits is read as degrees by some parsers
    and silently mangled by others."""
    assert openair.dms(9.0, "lon").startswith("009:")


def test_a_block_missing_ah_is_refused():
    """XCTrack reports this as 'Duplicate AC record' against the *next* airspace, so
    the writer has to catch it rather than let it into the file."""
    with pytest.raises(ValueError):
        openair.Airspace("X", "W", floor="GND", ceiling="").records()


def test_writer_emits_only_records_xctrack_accepts(zones):
    spaces = [atz.to_airspace(z, f"ATZ {z.icao}") for z in zones]
    spaces += circuits.to_airspaces(vfr("lkta"))
    text = openair.write(spaces, "header")
    used = {line.split()[0] for line in text.splitlines()
            if line.strip() and not line.startswith("*")}
    assert used <= set(openair.SAFE_RECORDS)
    # AG in particular: it is in Aeroklub's own file and XCTrack rejects it outright.
    assert "\r\nAG " not in text


def test_a_circle_is_written_as_dc_not_as_a_thousand_points(zones):
    circle = next(z for z in zones if z.is_circle)
    records = atz.to_airspace(circle, "ATZ").records()
    assert sum(1 for r in records if r.startswith("DP")) == 0
    assert sum(1 for r in records if r.startswith("DC")) == 1
    assert len(records) < 10


def test_dc_radius_is_in_nautical_miles(zones):
    circle = next(z for z in zones if z.is_circle)
    records = atz.to_airspace(circle, "ATZ").records()
    radius = float(next(r for r in records if r.startswith("DC")).split()[1])
    assert radius * openair.NM == pytest.approx(5500, abs=5)


def test_round_trip_preserves_geometry(zones):
    spaces = [atz.to_airspace(z, f"ATZ {z.icao}") for z in zones]
    back = openair.read(openair.write(spaces))
    assert len(back) == len(spaces)
    first = next(a for a in back if a.radius_nm)
    assert first.radius_nm * openair.NM == pytest.approx(5500, abs=5)


def test_reader_tolerates_records_the_writer_will_not_emit():
    text = (
        "* comment\r\nAC Q\r\nAN Test\r\nAH 4000 MSL\r\nAL GND\r\n"
        "AG Test\r\nAY DROPZONE\r\nV X=50:00:00 N 015:00:00 E\r\nDC 2\r\n"
    )
    got = openair.read(text)
    assert len(got) == 1
    assert got[0].radius_nm == 2
    assert len(got[0].points) > 10


def test_reader_accepts_decimal_minutes():
    assert openair.parse_coord("50:07.5 N 015:30.0 E") == pytest.approx((50.125, 15.5))


# ---------------------------------------------------------------- aerodromes


def test_reference_point_elevation_and_circuit_parse():
    field = vfr("lkta")
    assert field.icao == "LKTA"
    assert field.name == "Tábor"          # not "Tábor INFO"
    assert field.lat == pytest.approx(49 + 23 / 60 + 28 / 3600, abs=1e-6)
    assert field.lon == pytest.approx(14 + 42 / 60 + 30 / 3600, abs=1e-6)
    assert field.elevation_ft == 1440
    assert field.circuit_ft == 2460
    assert field.circuit_m == 750
    assert field.frequency == "122.610"


@pytest.mark.parametrize(
    "icao, expected",
    [
        ("lkta", "RWY 34 right"),        # "circuits to RWY 34 are carried out to the right"
        ("lkmb", "RWY 04,16 right"),     # "RWY 04, 16 - right hand"
        ("lkbe", "RWY 06,09L/R left"),   # "RWY 06, 09L/R - left hand"
    ],
)
def test_circuit_direction_is_read_from_prose(icao, expected):
    assert vfr(icao).circuit_note.startswith(expected)


def test_a_glider_field_is_flagged_as_mirrored():
    """LKBE publishes the powered circuit left and the glider circuit right on the same
    runway. That is why the box is drawn on both sides."""
    assert "gliders mirrored" in vfr("lkbe").circuit_note


def test_circuit_note_stays_short_enough_to_read_on_a_phone():
    assert len(vfr("lkbe").circuit_note) < 70


def test_runways_need_both_thresholds():
    csv_text = (
        "airport_ident,length_ft,closed,le_ident,le_latitude_deg,le_longitude_deg,"
        "he_ident,he_latitude_deg,he_longitude_deg\n"
        "LKAA,2000,0,08,49.0,16.0,26,49.001,16.02\n"
        "LKAA,2000,0,17,,,35,49.0,16.0\n"
        "LKBB,2000,0,09,49.0,16.0,27,49.0,16.02\n"
    )
    got = aerodromes.parse_runways(csv_text, {"LKAA"})
    assert list(got) == ["LKAA"]
    assert len(got["LKAA"]) == 1


def test_a_closed_runway_is_dropped():
    csv_text = (
        "airport_ident,length_ft,closed,le_ident,le_latitude_deg,le_longitude_deg,"
        "he_ident,he_latitude_deg,he_longitude_deg\n"
        "LKAA,2000,1,08,49.0,16.0,26,49.001,16.02\n"
    )
    assert aerodromes.parse_runways(csv_text, {"LKAA"}) == {}


# ---------------------------------------------------------------- circuits


def runway() -> Runway:
    # Due east, 1 km long, at 50 N.
    end = geo.destination(50.0, 15.0, 90.0, 1000.0)
    return Runway("09", "27", 50.0, 15.0, end[0], end[1])


def frame_xy(points, runway_=None):
    """Points in the runway's own frame: along it, and across to the right of the
    take-off direction.

    `Plane.to_xy` gives east/north with y *up*; an along/across basis built as
    (sin, -cos) is the image convention with y down, and silently rotates everything.
    """
    rw = runway_ or runway()
    plane = geo.Plane((rw.low_lat + rw.high_lat) / 2, (rw.low_lon + rw.high_lon) / 2)
    t = math.radians(geo.bearing(rw.low_lat, rw.low_lon, rw.high_lat, rw.high_lon))
    out = []
    for lat, lon in points:
        x, y = plane.to_xy(lat, lon)
        out.append((x * math.sin(t) + y * math.cos(t), x * math.cos(t) - y * math.sin(t)))
    return out


def contains(ring, point) -> bool:
    """Even-odd ray cast, the test every OpenAir consumer does."""
    x, y = point
    inside = False
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def both_sides(rw=None):
    rw = rw or runway()
    return [frame_xy(circuits.ribbon(rw, s), rw) for s in (1, -1)]


def covered(point, rw=None) -> bool:
    return any(contains(r, point) for r in both_sides(rw))


def segments_cross(a, b, c, d) -> bool:
    def side(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])

    return ((side(c, d, a) > 0) != (side(c, d, b) > 0)) and (
        (side(a, b, c) > 0) != (side(a, b, d) > 0)
    )


@pytest.mark.parametrize("side", [1, -1])
def test_the_ribbon_is_a_simple_polygon(side):
    """A ring that touches or crosses itself is read one way under even-odd fill and
    another under nonzero winding. The slit exists so this assertion can hold."""
    ring = frame_xy(circuits.ribbon(runway(), side))
    n = len(ring)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue
            assert not segments_cross(ring[i], ring[(i + 1) % n],
                                      ring[j], ring[(j + 1) % n]), f"edges {i},{j}"


def test_each_side_runs_from_the_runway_outward():
    """The AIP draws two rectangles abutting *on* the runway, not one ring around the
    field. Drawing the ring left the whole ATZ inside the hole — nothing marked over the
    field, the approach or the climb-out, which is where the aeroplanes are lowest."""
    ring = frame_xy(circuits.ribbon(runway(), 1))
    across = [a for _, a in ring]
    assert min(across) == pytest.approx(-circuits.RIBBON_M / 2, abs=1)   # on the runway
    assert max(across) == pytest.approx(circuits.BESIDE_M + circuits.RIBBON_M / 2, abs=1)
    # And the other side is its mirror.
    other = [a for _, a in frame_xy(circuits.ribbon(runway(), -1))]
    assert max(other) == pytest.approx(circuits.RIBBON_M / 2, abs=1)


def test_the_band_covers_the_runway_and_the_approach():
    """The reason the shape changed: this is the ground a paraglider shares with an
    aeroplane that is low and committed."""
    assert covered((0, 0))                       # over the runway
    assert covered((250, 0))                     # the threshold
    assert covered((950, 0))                     # 700 m out on final
    assert covered((1650, 0))                    # 1400 m out


def test_the_band_covers_both_downwind_legs():
    """Both sides: the glider circuit mirrors the powered one."""
    assert covered((0, circuits.BESIDE_M))
    assert covered((0, -circuits.BESIDE_M))


def test_the_band_is_still_hollow_and_bounded():
    assert not covered((0, circuits.BESIDE_M / 2))          # inside the circuit
    assert not covered((0, circuits.BESIDE_M * 1.4))        # outside it
    assert not covered((2000, 0))                           # past the turn


def test_the_band_overlaps_its_atz():
    """At an SLZ field the ATZ is only ~976 m in radius. A ring at +/-1300 m never
    touched it, so the green circle carried no okruh marking at all."""
    reached = sum(
        1 for d in (0, 300, 600, 900)
        for k in range(16)
        if covered((d * math.cos(k * math.tau / 16), d * math.sin(k * math.tau / 16)))
    )
    assert reached > 0.25 * 64


def test_the_ribbon_is_much_smaller_than_the_filled_box():
    def area(ring):
        return abs(sum(
            ring[i][0] * ring[(i + 1) % len(ring)][1]
            - ring[(i + 1) % len(ring)][0] * ring[i][1]
            for i in range(len(ring))
        )) / 2

    # The exact fraction depends on the runway, since the band keeps a fixed width while
    # the box scales — so assert the point of the band, not one geometry's number.
    band = sum(area(r) for r in both_sides())
    box = area(frame_xy(circuits.box(runway())))
    assert 0.25 < band / box < 0.75


LKCAST_TABLE = "RWY Magnetic direction RWY dimensions 10 100° 500 x 15 28 280° 500 x 15"


def test_a_runway_can_be_rebuilt_from_the_vfr_table():
    """An SLZ field has no surveyed thresholds anywhere — OurAirports has them for 2 of
    the 35 it lists — so the manual's own table is the only geometry there is."""
    got = aerodromes.runways_from_table(LKCAST_TABLE, 49.409, 15.144)
    assert len(got) == 1                      # 10 and 28 are one runway, not two
    runway = got[0]
    assert runway.name == "10/28"
    assert runway.estimated
    assert runway.length_m == pytest.approx(500, abs=2)
    # Magnetic 100° plus the variation, and the reference point is the midpoint.
    assert geo.bearing(runway.low_lat, runway.low_lon, runway.high_lat, runway.high_lon) \
        == pytest.approx(100 + aerodromes.DECLINATION, abs=0.5)
    assert geo.distance(49.409, 15.144,
                        (runway.low_lat + runway.high_lat) / 2,
                        (runway.low_lon + runway.high_lon) / 2) < 1.0


def test_reciprocal_designators_collapse_to_one_runway():
    assert aerodromes._reciprocal("10") == "28"
    assert aerodromes._reciprocal("28") == "10"
    assert aerodromes._reciprocal("36") == "18"
    assert aerodromes._reciprocal("01") == "19"


def test_an_slz_field_gets_an_okruh_marked_estimated():
    """Částkovice publishes a reference point, a runway table and no circuit altitude —
    which is every SLZ field. The okruh is built, and says it was reconstructed."""
    field_ = Aerodrome(icao="LKCAST", name="Částkovice", lat=49.409, lon=15.144,
                       elevation_ft=1925.0)
    field_.runways = aerodromes.runways_from_table(LKCAST_TABLE, 49.409, 15.144)
    spaces = circuits.to_airspaces(field_)
    assert len(spaces) == 2                      # one per side of the runway
    assert {a.meta["side"] for a in spaces} == {"NNE", "SSW"}
    for space in spaces:
        assert space.name.startswith("OKRUH LKCAST Částkovice RWY 10/28")
        assert "est" in space.name
        assert space.ceiling == "2925ft AMSL"    # elevation + 1000 ft, none published


def test_a_six_letter_ident_still_yields_a_name():
    """`LK[A-Z]{2}` matched `LKCA` and then failed on the `S`, leaving all 74 unnamed."""
    page = "<p>LKCAST - Částkovice</p><p>ARP: 49° 24' 33\" N, 15° 08' 39\" E</p>"
    assert aerodromes.parse_vfr("LKCAST", page).name == "Částkovice"


def test_circuit_ceiling_prefers_the_published_altitude():
    field = vfr("lkta")
    field.runways = [runway()]
    space = circuits.to_airspaces(field)[0]
    assert space.ceiling == "2460ft AMSL"
    assert space.airspace_class == "Q"      # orange and silent, inside an alerting ATZ
    assert " est" not in space.name


def test_an_unpublished_circuit_altitude_is_estimated_and_says_so():
    field = Aerodrome(icao="LKXX", elevation_ft=1000.0, runways=[runway()])
    space = circuits.to_airspaces(field)[0]
    assert space.ceiling == "2000ft AMSL"
    assert " est" in space.name


def test_no_altitude_at_all_means_no_box():
    assert circuits.to_airspaces(Aerodrome(icao="LKXX", runways=[runway()])) == []


def test_a_field_with_no_runway_gets_no_box():
    assert circuits.to_airspaces(Aerodrome(icao="LKXX", elevation_ft=1000.0)) == []


def test_the_box_fits_inside_the_atz(zones):
    """A circuit box that escaped its own ATZ would be drawn over open country."""
    circle = next(z for z in zones if z.is_circle)
    field = Aerodrome(icao=circle.icao, elevation_ft=1000.0,
                      runways=[Runway("09", "27", circle.lat, circle.lon,
                                      *geo.destination(circle.lat, circle.lon, 90, 1200))])
    for lat, lon in circuits.to_airspaces(field)[0].points:
        assert geo.distance(circle.lat, circle.lon, lat, lon) < circle.radius_m


# ---------------------------------------------------------------- rendering


def test_floor_parses_the_forms_the_base_file_uses():
    def floor(text):
        return render_html.floor_metres(openair.Airspace("n", "R", text, "FL95"))

    assert floor("GND") == 0
    assert floor("0 AGL") == 0
    assert floor("FL 95") == pytest.approx(2895, abs=5)
    assert floor("4000 MSL") == pytest.approx(1219, abs=2)
    assert floor("1000ft AMSL") == pytest.approx(305, abs=2)
    assert floor("500m AMSL") == pytest.approx(500, abs=1)


def test_our_own_airspaces_classify_by_kind_not_by_name(zones):
    assert render_html.classify(atz.to_airspace(zones[0], "ATZ LKHB")) == "atz"
    field = vfr("lkta")
    field.runways = [runway()]
    assert render_html.classify(circuits.to_airspaces(field)[0]) == "circuit"


def test_projection_puts_north_up_and_east_right():
    project = render_html.Projection((48.5, 51.0, 12.0, 19.0))
    x_west, y_north = project(51.0, 12.0)
    x_east, y_south = project(48.5, 19.0)
    assert x_east > x_west
    assert y_south > y_north


def test_map_draws_a_path_for_every_airspace(zones):
    spaces = [atz.to_airspace(z, f"ATZ {z.icao}") for z in zones]
    project = render_html.Projection((48.5, 51.0, 12.0, 19.0))
    svg = render_html.map_svg(spaces, project)
    assert svg.count('class="asp-zone"') == len(spaces)
    assert 'd=""' not in svg


def test_the_download_points_at_a_sibling_file():
    """A relative href, so the file has to be published next to the page. Deliberate —
    see the module docstring — and the one place here that is not self-contained."""
    html = render_html.download_link("CZ_ATZ_20260806.txt", "Download", "note")
    assert 'href="CZ_ATZ_20260806.txt"' in html
    assert 'download="CZ_ATZ_20260806.txt"' in html
    assert "data:" not in html


def test_the_download_says_the_file_is_not_a_full_airspace_set(zones):
    """Reading it as a replacement would take every CTR and TMA off the instrument, so
    the panel has to rule that out rather than merely not imply it."""
    overlay = build.Overlay(
        airspaces=[atz.to_airspace(z, f"ATZ {z.icao}") for z in zones],
        zones=zones, fields={},
    )
    article = render_html.body(
        overlay, [], "26-04-01", openair_name="CZ_ATZ.txt", openair_size=71000
    )
    assert "not a full airspace set" in article
    assert "alongside" in article
    assert "ATZ + okruhy only" in article


# ------------------------------------------- the airspace view inside the report


def airspace_article(zones):
    overlay = build.Overlay(
        airspaces=[atz.to_airspace(z, f"ATZ {z.icao}") for z in zones],
        zones=zones, fields={}, atz_date="2026-08-06",
    )
    return overlay, render_html.body(overlay, [], "26-04-01", openair_name="CZ_ATZ.txt",
                                     openair_size=71000, openair_href="airspace/CZ_ATZ.txt")


def test_the_article_stays_out_of_the_flight_tab_controller(zones):
    """It lives in a top-level view section, and the flight strip's controller hides
    every `[data-flight-report]` that is not the open flight. Carrying that attribute
    made the two fight over `hidden`."""
    _, article = airspace_article(zones)
    assert "data-flight-report" not in article
    assert " hidden>" not in article


def test_the_download_href_can_differ_from_the_filename(zones):
    """Embedded in a report one directory up, the link is `airspace/NAME` while the
    saved file must still be `NAME`."""
    _, article = airspace_article(zones)
    assert 'href="airspace/CZ_ATZ.txt"' in article
    assert 'download="CZ_ATZ.txt"' in article


def test_the_page_warns_and_puts_responsibility_on_the_pilot(zones):
    """Short by design — the dates it would otherwise recite are in the sources table."""
    _, article = airspace_article(zones)
    assert "no guarantee" in article
    assert "Pilots are responsible for the airspace they fly in" in article


def test_the_sources_table_says_where_each_layer_came_from(zones):
    """The question a reader has is 'that green circle — who says so?', and only a
    per-layer table answers it."""
    _, article = airspace_article(zones)
    assert "What is on this map, and where it came from" in article
    assert "Aeroklub" in article and "26-04-01" in article        # base airspace
    assert "LKR315" in article and "2026-08-06" in article        # ATZ
    assert "not a published boundary" in article                  # circuits
    # Every legend colour appears as a swatch in the table.
    for _, _, colour in render_html.CLASSES:
        assert colour in article


def test_every_source_is_a_link_to_the_file_it_came_from(zones):
    """So currency can be checked at the source instead of taken on trust. A link is
    not a fetch at view time, so the offline guarantee is intact."""
    overlay, article = airspace_article(zones)
    table = article[article.index('<table class="asp-src"'):]
    table = table[:table.index("</table>")]
    hrefs = re.findall(r'href="([^"]+)"', table)
    assert any("airspace.aeroklub.cz" in h and h.endswith("26-04-01.txt") for h in hrefs)
    assert any("ourairports.com" in h for h in hrefs)
    assert any("vfrmanual" in h for h in hrefs)
    # One link per publication actually included, pointing at that AIRAC cycle.
    for pub in overlay.by_publication:
        assert any(f"LKR315{pub}.json" in h and "2026_08_06" in h for h in hrefs)


def test_the_report_puts_extras_above_the_flight_tabs():
    """One level up: the flight strip chooses which flight, the view switch chooses
    whether you are looking at flights at all."""
    from tracklog_viewer import render_html as report_html

    extra = report_html.Extra(uid="airspace", label="Airspace", body="<article>x</article>")
    page = report_html._page("t", ["<article data-flight-report='f0'></article>"],
                             tabs="<nav id='flight-tabs'></nav>", extras=[extra])
    assert page.index('id="views"') < page.index("flight-tabs")
    assert '<section data-view="flights">' in page
    assert '<section data-view="airspace" hidden>' in page
    # And not a flight tab.
    assert 'data-flight-tab="airspace"' not in page


def test_a_report_with_no_extras_has_no_view_switch():
    """The switch is meaningless with one view, and every existing report has one."""
    from tracklog_viewer import render_html as report_html

    page = report_html._page("t", ["<article></article>"], tabs="<nav></nav>")
    assert 'id="views"' not in page
    assert "data-view=" not in page


def test_the_label_does_not_hide_itself_on_a_touchscreen():
    """A touchscreen fires pointerout when the finger lifts, so a hover-driven label
    appeared and vanished inside one tap. Touch is now tap-to-pin."""
    script = render_html.SCRIPT
    assert "e.pointerType === 'touch'" in script
    # pointerout must bail out on touch rather than hiding.
    out = script[script.index("'pointerout'"):]
    out = out[:out.index("});")]
    assert "e.pointerType === 'touch') return" in out
    # And a tap has to be able to show it in the first place.
    down = script[script.index("svg.addEventListener('pointerdown', function (e) {\n    if (!tip"):]
    assert "showTip(zone, e.clientX, e.clientY, true)" in down[:400]


def test_map_escapes_a_name_that_would_break_the_svg(zones):
    space = atz.to_airspace(zones[0], 'ATZ <b>"x"</b> & co')
    project = render_html.Projection((48.5, 51.0, 12.0, 19.0))
    svg = render_html.map_svg([space], project)
    assert "<b>" not in svg
    assert "&amp; co" in svg

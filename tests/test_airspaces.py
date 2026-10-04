"""Airspace module. No network: every source is a fixture under tests/data."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from pathlib import Path

import pytest

from airspaces import aerodromes, atz, build, circuits, geo, hours, openair, render_html
from airspaces.aerodromes import Aerodrome, Runway
from tests.test_view3d_gl import CHROME, CHROME_FLAGS, needs_chrome

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


# ---------------------------------------------------------------- operating hours


def when(text: str) -> dt.datetime:
    """A UTC instant, written the way the AIP writes its own times."""
    return dt.datetime.fromisoformat(text)


def test_the_hours_are_only_reachable_from_the_raw_page():
    """They sit in an unlabelled `<div>` whose only marker is an image's alt text, so
    `_text()` — which strips tags — destroys the one thing that identifies them."""
    page = (DATA / "vfr_lkta.html").read_text()
    assert "Provozní doba" not in aerodromes._text(page)
    assert aerodromes.operating_hours(page).startswith("15 APR - 15 OCT")


def test_lkta_is_a_weekend_field_and_the_times_are_utc():
    """`15 APR - 15 OCT SAT, SUN, HOL 0700-1400` is 0900-1600 local, which is the Czech
    XC day — so this dims nothing on a summer Saturday and everything on a Tuesday."""
    schedule = vfr("lkta").hours
    assert schedule.active(when("2026-08-08 11:00"))       # Saturday, mid-window
    assert not schedule.active(when("2026-08-11 11:00"))   # Tuesday
    assert not schedule.active(when("2026-08-08 05:00"))   # Saturday, before 0700 UTC
    assert not schedule.active(when("2026-01-10 11:00"))   # Saturday, out of season


def test_hol_means_a_public_holiday_and_the_calendar_is_computed():
    """6 July 2026 is a Monday and Den upálení mistra Jana Husa, so LKTA is open on it
    while the Monday before is shut. Without the calendar `HOL` would be a dead word at
    the 61 fields that publish it."""
    schedule = vfr("lkta").hours
    assert schedule.active(when("2026-07-06 11:00"))
    assert not schedule.active(when("2026-06-29 11:00"))
    assert hours.easter(2026) == dt.date(2026, 4, 5)
    assert dt.date(2026, 4, 6) in hours.czech_holidays(2026)   # Easter Monday


def test_lkbe_publishes_three_seasons_with_a_gap_between_them():
    """`1 APR - 31 OCT 0800-1500  1 NOV - 15 DEC 0900-1300  6 JAN - 31 MAR 0900-1300` —
    three periods, and 16 December to 5 January is in none of them."""
    schedule = vfr("lkbe").hours
    assert len(schedule.periods) == 3
    assert schedule.active(when("2026-05-04 09:00"))
    assert schedule.active(when("2026-11-20 10:00"))
    assert not schedule.active(when("2026-12-20 10:00"))
    assert not schedule.active(when("2026-11-20 14:00"))   # past 1300 in the winter window


def test_days_alone_are_not_a_schedule():
    """LKPO's page is `O/R ... 48 HR O/R SAT, SUN, HOL.` — an on-request field with a
    sentence about weekends in it. Read as a period it says "shut Monday to Friday",
    which is the one direction this must never be wrong in."""
    schedule = hours.parse("O/R In case of arrivals outside the Schengen Area "
                           "48 HR O/R SAT, SUN, HOL.")
    assert not schedule.known
    assert schedule.on_request
    assert schedule.active(when("2026-08-11 11:00"))
    assert schedule.short() == "O/R"


def test_except_lists_exclusions_and_is_cut_off():
    """LKHK writes `... except 24-26 DEC, 31 DEC - 1 JAN, Easter Monday`. `31 DEC - 1
    JAN` is a season by shape, and reading it as one shrank a whole-year entry to two
    days in December."""
    schedule = hours.parse("MON-FRI 0700-TE SAT, SUN, HOL 0800-TE "
                           "except 24-26 DEC, 31 DEC - 1 JAN; otherwise O/R")
    assert not schedule.known, "an exclusion list was read as a published period"
    assert schedule.active(when("2026-08-11 11:00"))


def test_a_repeated_window_keeps_the_days_it_repeats_under():
    """LKSB's `SAT, SUN, HOL 0900 - 1600 (0800 - 1500) UTC` is the winter figure and the
    summer one. Two periods over the same days, and their union is the wider answer."""
    schedule = hours.parse("15 APR - 15 OCT SAT, SUN, HOL 0900 - 1600 (0800 - 1500) UTC")
    assert len(schedule.periods) == 2
    assert all(period.days == frozenset({"SAT", "SUN", "HOL"})
               for period in schedule.periods)
    assert schedule.active(when("2026-05-02 08:30"))      # only the bracketed window
    assert schedule.active(when("2026-05-02 15:30"))      # only the printed one
    assert not schedule.active(when("2026-05-02 16:30"))
    assert not schedule.active(when("2026-04-29 12:00"))  # a Wednesday


def test_an_slz_strip_publishes_no_hours_at_all():
    """All 74 of them say this, and it is the reason the feature can never dim the
    layer that most deserves dimming — the reconstructed okruh marked `est`."""
    for text in ("Year-round", "Operating hours are not specified. According to the "
                 "operator's needs. Year-round according to the current state."):
        schedule = hours.parse(text)
        assert not schedule.known
        assert schedule.short() == ""
        assert schedule.active(when("2026-01-01 03:00")), "an unread page must stay open"


def test_operators_needs_is_not_the_aip_s_o_slash_r():
    """`O/R` means arranged in advance; an SLZ strip's "according to the operator's
    needs" means flown whenever the operator likes, which is the opposite claim. Writing
    `O/R` on those 74 okruhy would say a strip is quiet when its page says no such thing.
    """
    loose = hours.parse("Year-round. According to the needs of the operator.")
    assert loose.on_request and not loose.request_only
    assert loose.short() == ""
    strict = hours.parse("Operational hours not specified, only O/R")
    assert strict.request_only
    assert strict.short() == "O/R"


def test_a_window_that_parsed_still_says_o_slash_r_is_possible():
    """Nearly every page adds it, and it is why no caller may render "outside published
    hours" as "closed"."""
    assert vfr("lkta").hours.on_request
    assert vfr("lkbe").hours.on_request


def test_the_short_form_carries_the_zulu_marker():
    """The name is read by a pilot whose instrument is set to local time, and the two
    are two hours apart for the whole season."""
    assert vfr("lkta").hours.short() == "15APR-15OCT SAT-SUN,HOL 0700-1400Z"
    assert vfr("lkmb").hours.short() == "15APR-15OCT 0700-1600Z"
    # LKOL publishes four periods; a name is not the place for all of them.
    many = hours.parse("1 APR - 30 APR: THU - SUN, HOL: 0600 - 1600 "
                       "1 MAY - 30 SEP: TUE - SUN, HOL: 0500 - 1800 "
                       "1 OCT - 31 OCT: THU - SUN, HOL: 0600 - 1600 "
                       "1 NOV - 31 MAR: SAT, SUN, HOL: 0800 - 1500 otherwise O/R")
    assert many.short() == "1APR-30APR THU-SUN,HOL 0600-1600Z +3 more"


def test_a_season_may_wrap_the_year():
    schedule = hours.parse("1 NOV - 31 MAR 0900-1300")
    assert schedule.active(when("2026-01-15 10:00"))
    assert schedule.active(when("2026-12-15 10:00"))
    assert not schedule.active(when("2026-06-15 10:00"))


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


def test_the_hours_reach_the_name_because_nothing_else_can_carry_them():
    """XCTrack honours an activation schedule only for the airspace it downloads from
    xcontest; an imported OpenAir file has no record for one, so the band is drawn at
    three in the morning in January exactly as on a Saturday. The name is the only
    channel there is, and it is the one XCTrack shows on a tap."""
    field_ = vfr("lkta")
    field_.runways = [runway()]
    names = [space.name for space in circuits.to_airspaces(field_)]
    assert names, "LKTA publishes a circuit altitude, so it must produce a band"
    for name in names:
        assert name.endswith("15APR-15OCT SAT-SUN,HOL 0700-1400Z")
        assert "2460ft/750m" in name, "the hours must not have displaced the altitude"


def test_a_field_with_no_published_hours_gets_no_token():
    """Every SLZ strip is in this case, so a token here would be 410 rectangles of
    invented precision."""
    field_ = Aerodrome(icao="LKCAST", name="Částkovice", lat=49.409, lon=15.144,
                       elevation_ft=1925.0)
    field_.runways = aerodromes.runways_from_table(LKCAST_TABLE, 49.409, 15.144)
    for space in circuits.to_airspaces(field_):
        assert space.name.endswith("est")
        assert space.meta["hours"] is None


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


def test_a_limit_carries_its_datum_as_well_as_its_number():
    """The number alone is not enough to draw a lid with. `1000 AGL` and `1000 MSL` are
    the same integer and 700 m apart over the Šumava."""
    assert render_html.limit_metres("GND") == (0.0, True)
    assert render_html.limit_metres("0 AGL") == (0.0, True)
    assert render_html.limit_metres("")[1] is True
    metres, ground = render_html.limit_metres("1000 AGL")
    assert metres == pytest.approx(305, abs=2) and ground is True
    metres, ground = render_html.limit_metres("4000 MSL")
    assert metres == pytest.approx(1219, abs=2) and ground is False
    assert render_html.limit_metres("FL 95")[0] == pytest.approx(2895, abs=5)
    assert render_html.limit_metres("UNL") == (None, False)


def test_the_ceiling_reads_the_forms_the_two_sources_write():
    def ceiling(text):
        return render_html.ceiling_metres(openair.Airspace("n", "R", "GND", text))

    assert ceiling("FL 95")[0] == pytest.approx(2895, abs=5)
    assert ceiling("4000ft AMSL")[0] == pytest.approx(1219, abs=2)
    assert ceiling("1000 AGL") == (pytest.approx(305, abs=2), True)


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
    html = render_html.download_link("CZ_airfield_zones_20260806.txt", "Download", "note")
    assert 'href="CZ_airfield_zones_20260806.txt"' in html
    assert 'download="CZ_airfield_zones_20260806.txt"' in html
    assert "data:" not in html


def test_the_download_filename_has_one_source(zones):
    """Both CLIs write this file and both used to spell the name themselves; they had
    already drifted. The name is also what a pilot picks out of XCTrack's import list,
    so it says what is in the file rather than which acronym the tool began as."""
    overlay = build.Overlay(airspaces=[], zones=zones, fields={}, atz_date="2026-08-06")
    assert overlay.filename == "CZ_airfield_zones_20260806.txt"

    for module in ("airspaces/cli.py", "tracklog_viewer/cli.py"):
        source = (Path(__file__).parent.parent / module).read_text(encoding="utf-8")
        assert "overlay.filename" in source, module
        assert ".txt\"" not in source.replace("overlay.filename", ""), module


def test_the_counts_offered_are_circuits_not_rectangles(zones):
    """One circuit is drawn as two rectangles meeting on the runway, so the shape count
    is about twice the number of circuits and is the wrong thing to print."""
    field_a = Aerodrome(icao="LKAA", name="A", lat=50.0, lon=15.0, elevation_ft=1000)
    spaces = [
        openair.Airspace("okruh LKAA RWY 09 N", "Q", floor="GND", ceiling="2000ft AMSL",
                         points=[(50.0, 15.0), (50.1, 15.0), (50.1, 15.1)],
                         meta={"icao": "LKAA", "kind": "circuit", "runway": "09/27",
                               "side": "N"}),
        openair.Airspace("okruh LKAA RWY 09 S", "Q", floor="GND", ceiling="2000ft AMSL",
                         points=[(50.0, 15.0), (49.9, 15.0), (49.9, 15.1)],
                         meta={"icao": "LKAA", "kind": "circuit", "runway": "09/27",
                               "side": "S"}),
    ]
    overlay = build.Overlay(airspaces=spaces, zones=[], fields={"LKAA": field_a})
    assert overlay.circuit_count == 2
    assert overlay.circuits == 1
    assert overlay.circuit_fields == 1


def test_the_download_says_the_file_is_not_a_full_airspace_set(zones):
    """Reading it as a replacement would take every CTR and TMA off the instrument, so
    the panel has to rule that out rather than merely not imply it."""
    overlay = build.Overlay(
        airspaces=[atz.to_airspace(z, f"ATZ {z.icao}") for z in zones],
        zones=zones, fields={},
    )
    article = render_html.body(
        overlay, [], "26-04-01", openair_name="CZ_airfield_zones.txt", openair_size=71000
    )
    assert "not a full airspace set" in article
    assert "alongside" in article


def test_the_download_sits_under_the_map(zones):
    """The map is what the page is for and it is what a reader arrives to look at; the
    file is what they want *after* deciding it is worth having. A download panel above
    the map pushed the map itself below the fold on a phone."""
    overlay = build.Overlay(
        airspaces=[atz.to_airspace(z, f"ATZ {z.icao}") for z in zones],
        zones=zones, fields={},
    )
    article = render_html.body(
        overlay, [], "26-04-01", openair_name="CZ_airfield_zones.txt", openair_size=71000
    )
    assert article.index("asp-holder") < article.index("asp-download")
    assert article.index("asp-download") < article.index("asp-src")


# ------------------------------------------- the airspace view inside the report


def airspace_article(zones):
    overlay = build.Overlay(
        airspaces=[atz.to_airspace(z, f"ATZ {z.icao}") for z in zones],
        zones=zones, fields={}, atz_date="2026-08-06",
    )
    return overlay, render_html.body(overlay, [], "26-04-01", openair_name="CZ_airfield_zones.txt",
                                     openair_size=71000, openair_href="airspace/CZ_airfield_zones.txt")


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
    assert 'href="airspace/CZ_airfield_zones.txt"' in article
    assert 'download="CZ_airfield_zones.txt"' in article


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


def test_the_smallest_shape_under_the_cursor_is_the_one_on_top():
    """SVG has no z-index: paint order is hit order, so the last thing drawn both covers
    and captures the pointer. Ordering by class put every ATZ above the dropzone inside
    it, and Tábor's dropzone could not be clicked through its own ATZ."""
    def ring(radius, label, klass):
        space = openair.Airspace(label, klass, "GND", "4000ft AMSL",
                                 points=openair.circle_points((49.4, 15.0), radius))
        space.meta["kind"] = "atz" if klass == "W" else None
        return space

    big = ring(5500, "ATZ LKTA", "W")          # the ATZ
    small = ring(3704, "DROPZONE Tabor", "Q")  # the dropzone inside it
    project = render_html.Projection((48.5, 51.0, 12.0, 19.0))
    svg = render_html.map_svg([small, big], project)
    assert svg.index("ATZ LKTA") < svg.index("DROPZONE Tabor"), \
        "the smaller shape must be painted last, so it is the one hit"


def test_an_slz_zone_is_not_called_an_atz(zones):
    """dronview labels it `SLZ LKCAST`, and the VFR manual calls the place a *neveřejná
    plocha SLZ*. Emitting 74 green `ATZ` invented aerodrome traffic zones that do not
    exist — and made the okruh look wrong for sitting outside one."""
    slz = atz.ATZ("LKCAST", "", 49.409, 15.144, 976.0,
                  openair.circle_points((49.409, 15.144), 976.0), 1.0,
                  publication="B", name="Částkovice")
    assert not slz.is_aerodrome
    overlay = build.Overlay(airspaces=[], zones=[slz], fields={})
    assert overlay.by_publication == {"B": 1}


def test_map_escapes_a_name_that_would_break_the_svg(zones):
    space = atz.to_airspace(zones[0], 'ATZ <b>"x"</b> & co')
    project = render_html.Projection((48.5, 51.0, 12.0, 19.0))
    svg = render_html.map_svg([space], project)
    assert "<b>" not in svg
    assert "&amp; co" in svg


# ------------------------------------------- the 3D map


def test_a_ring_carries_its_own_floor(zones):
    """The argument for airspace in 3D: a CTR whose floor is 1 000 ft above you is a
    different object from one that starts at the ground, and on a flat map both are the
    same red outline. So each ring ships the floor it is drawn at, in metres AMSL, and
    it is the same number the floor slider filters on."""
    from airspaces import scene as airspace_scene

    high = openair.Airspace("TMA TEST", "C", floor="FL 95", ceiling="FL 195",
                            points=[(50.0, 15.0), (50.2, 15.0), (50.2, 15.3)])
    ground = atz.to_airspace(zones[0], "ATZ TEST")
    rings = airspace_scene.rings([high, ground])
    tma = next(r for r in rings if r["n"].startswith("TMA"))
    assert tma["f"] == round(render_html.floor_metres(high))
    assert tma["f"] > 2800 and not tma["g"], "FL95 was drawn on the ground"

    atz_ring = next(r for r in rings if r["n"].startswith("ATZ"))
    assert atz_ring["g"] is True, "a GND floor must follow the terrain, not sit at 0 m"


def test_a_ring_carries_the_lid_that_makes_it_a_box(zones):
    """The other half of the same argument. A floor says where a zone starts and says
    nothing about whether it is a 300 m band over a field or a wall to FL95, and those
    are different answers to "can I climb here"."""
    from airspaces import scene as airspace_scene

    points = [(50.0, 15.0), (50.2, 15.0), (50.2, 15.3)]
    tma = openair.Airspace("TMA TEST", "C", floor="1000 ft AMSL", ceiling="FL 95",
                           points=points)
    ring = airspace_scene.rings([tma])[0]
    assert ring["c"] == pytest.approx(2895, abs=5)
    assert "t" not in ring, "FL95 is drawn true and must not be marked as capped"
    assert "cu" not in ring, "an AMSL ceiling is an altitude, not a height above ground"


def test_a_lid_above_the_cap_is_drawn_short_and_says_so(zones):
    """21 of the 251 base airspaces run to FL165 or higher. Drawn true they are towers
    that hide every zone a paraglider meets, so the box stops at the cap — and carries
    the mark that says the drawn top is not the published one."""
    from airspaces import scene as airspace_scene

    points = [(50.0, 15.0), (50.2, 15.0), (50.2, 15.3)]
    high = openair.Airspace("LKR TEST", "R", floor="GND", ceiling="FL 660", points=points)
    ring = airspace_scene.rings([high])[0]
    assert ring["c"] == pytest.approx(airspace_scene.DRAWN_TOP, abs=1)
    assert ring["t"] is True
    # The reader is never left to infer the real ceiling from the drawn one.
    assert "FL 660" in ring["n"]


def test_an_agl_lid_stays_a_height_above_the_ground(zones):
    """A traffic circuit is 1 000 ft *above the field*, and the 19 base airspaces with an
    AGL ceiling are the same shape. Flattened to an altitude at build time the lid lands
    at 305 m — under the terrain it belongs to everywhere but the lowlands — so the height
    has to survive all the way into the renderer."""
    from airspaces import scene as airspace_scene

    points = [(50.0, 15.0), (50.2, 15.0), (50.2, 15.3)]
    band = openair.Airspace("TSA TEST", "R", floor="GND", ceiling="1000 AGL",
                            points=points)
    ring = airspace_scene.rings([band])[0]
    assert ring["cu"] == pytest.approx(305, abs=2)
    assert "c" not in ring, "an AGL lid has no altitude to be drawn at"
    assert ring["g"] is True

    over = openair.Airspace("TSA HIGH", "R", floor="300 AGL", ceiling="1000 AGL",
                            points=points)
    high = airspace_scene.rings([over])[0]
    assert high["fu"] == pytest.approx(91, abs=2), "an AGL floor is a height too"
    assert high["g"] is False


def test_only_a_ring_with_published_hours_carries_a_schedule(zones):
    """The time filter can only ever speak for the layer it has hours for. The 251 base
    airspaces get their activation from NOTAMs this repository does not fetch, and the
    74 SLZ okruhy from pages that publish no hours — so neither may carry a schedule,
    and the filter must leave both alone."""
    from airspaces import scene as airspace_scene

    base = openair.Airspace("MCTR KBELY", "C", floor="GND", ceiling="FL 95",
                            points=[(50.0, 14.5), (50.2, 14.5), (50.2, 14.8)])
    field_ = vfr("lkta")
    field_.runways = [runway()]
    okruh = circuits.to_airspaces(field_)[0]

    rings = airspace_scene.rings([base, okruh])
    assert "w" not in next(r for r in rings if r["n"].startswith("MCTR"))
    scheduled = next(r for r in rings if r["n"].startswith("OKRUH"))
    assert scheduled["w"]["p"], "the okruh lost the hours its field publishes"
    assert scheduled["w"]["r"] == 1, "LKTA says 'otherwise O/R' and the ring must say so"


def test_the_time_filter_is_off_when_the_page_opens():
    """Same decision as the floor slider, and for a stronger reason: this one would
    withhold airspace on the strength of prose parsed out of a VFR manual page."""
    markup = render_html.when_control(render_html.WHEN_NOTE)
    box = re.search(r'<input type="checkbox" id="asp-when-on"[^>]*>', markup).group()
    assert "checked" not in box
    assert "not “closed”" in markup, "the O/R caveat has to be on screen, not in a doc"
    # The holiday calendar rides on the control, because the flat map has no scene to
    # put it in and both maps must answer the same question.
    assert f"{dt.date.today().year}-12-24" in markup


def test_rings_are_ordered_biggest_first(zones):
    """Paint order is hit order on a canvas exactly as it is in SVG, so the smallest
    thing under the pointer has to be drawn last or a dropzone cannot be read through
    the zone around it."""
    from airspaces import scene as airspace_scene

    big = openair.Airspace("BIG", "C", floor="GND", ceiling="FL 195",
                           points=[(50.0, 15.0), (51.0, 15.0), (51.0, 16.0)])
    small = openair.Airspace("SMALL", "C", floor="GND", ceiling="FL 195",
                             points=[(50.1, 15.1), (50.2, 15.1), (50.2, 15.2)])
    names = [r["n"].split(" ")[0] for r in airspace_scene.rings([small, big])]
    assert names.index("BIG") < names.index("SMALL")


def test_the_scene_needs_no_flight_in_it(zones):
    """The whole reason `view3d` can be reused here: its payload is a map, and the
    track, the climbs and the phases are optional passengers."""
    from airspaces import scene as airspace_scene

    payload = airspace_scene.build([atz.to_airspace(z, f"ATZ {z.icao}") for z in zones])
    assert "track" not in payload and "climbs" not in payload
    assert payload["airspaces"] and payload["airspaceColours"]["atz"]
    # Nearly flat: the flight camera's 0.46 turns 500 km of country into a sliver.
    assert payload["view"]["pitch"] > 1.0


def test_the_page_falls_back_to_the_flat_map_without_terrain(zones):
    """A tile server being slow must never cost the reader the airspace itself."""
    _, article = airspace_article(zones)
    assert "asp-map" in article and "view3d" not in article


def test_the_map_fetches_its_ground_in_the_page():
    """The 3D map's ground is fetched by the page (`scene.remote`), over the planner's
    box — Czechia and the Alps. A build therefore cannot lose it and quietly fall back to
    the flat map, which a `--require-terrain` flag once had to guard a deploy against."""
    from airspaces import cli, scene as airspace_scene

    terrain = airspace_scene.remote([])["terrain"]
    assert terrain["remote"] and "z" not in terrain
    assert (terrain["west"], terrain["east"], terrain["south"], terrain["north"]) == \
        airspace_scene.PLAN_BOX
    assert terrain["rows"] * terrain["cols"] <= airspace_scene.PLAN_NODES
    # It opens on the airspace, not on the whole of the planner's box.
    focus = airspace_scene.remote([])["view"]["focus"]
    assert airspace_scene.PLAN_BOX[0] < focus["west"] < focus["east"] < airspace_scene.PLAN_BOX[1]
    source = __import__("pathlib").Path(cli.__file__).read_text(encoding="utf-8")
    assert "airspace_scene.remote(" in source


def test_a_zero_floor_is_the_ground_however_it_is_written():
    """`0 AGL` is what the base file mostly says, and it means the same as `GND`. Read as
    an altitude it puts the ring at sea level — 200 to 1 600 m under the terrain it
    belongs to in this country — so it draws in the wrong place and prints "floor 0 m"
    for something that starts under your feet."""
    from airspaces import scene as airspace_scene

    points = [(50.0, 15.0), (50.1, 15.0), (50.1, 15.1)]
    for floor in ("GND", "0 AGL", "SFC", ""):
        space = openair.Airspace("X", "C", floor=floor, ceiling="FL 95", points=points)
        assert airspace_scene.rings([space])[0]["g"] is True, floor
    high = openair.Airspace("Y", "C", floor="1000 ft AMSL", ceiling="FL 95",
                            points=points)
    assert airspace_scene.rings([high])[0]["g"] is False


# ------------------------------------------- the time filter, in a browser
#
# The rest of this module is pure Python, and these two are here because the filter
# cannot be checked any other way: whether a Prague wall-clock time lands on the right
# UTC minute, and whether a ring with no schedule survives, are claims about what the
# browser does with the payload.
#
# Both maps are driven, because they filter by different means and the duplication is
# deliberate — the flat map sets `display` on an SVG element and the 3D map hands the
# view a predicate. A reader must get the same answer from either, and the flat one is
# the fallback nothing else exercises, so a syntax error in it would surface on the day
# a tile server was slow.


def _hours_fixture():
    """LKTA with its published weekend hours, an SLZ strip with none, and a piece of
    base airspace. One of each kind the filter has to treat differently."""
    field_ = vfr("lkta")
    field_.runways = [runway()]
    slz = Aerodrome(icao="LKCAST", name="Částkovice", lat=49.409, lon=15.144,
                    elevation_ft=1925.0)
    slz.runways = aerodromes.runways_from_table(LKCAST_TABLE, 49.409, 15.144)
    base = [openair.Airspace("MCTR KBELY", "C", floor="GND", ceiling="FL 95",
                             points=[(50.0, 14.5), (50.2, 14.5), (50.2, 14.8)])]
    overlay = build.Overlay(
        airspaces=circuits.to_airspaces(field_) + circuits.to_airspaces(slz),
        zones=[], fields={"LKTA": field_, "LKCAST": slz}, atz_date="2026-08-06",
    )
    return overlay, base


# Tick the box on a Tuesday, read what is left, then move to the Saturday. 11:00 Prague
# is 09:00 Z, which is inside LKTA's `SAT, SUN, HOL 0700-1400` on the one day and outside
# it on the other — the whole feature, in two wall-clock times a pilot would actually use.
_ASK = """
var input = document.getElementById('asp-when');
var box = document.getElementById('asp-when-on');
input.value = '2026-08-11T11:00';
box.checked = true;
box.dispatchEvent(new Event('change', { bubbles: true }));
var tuesday = names();
var says = document.getElementById('asp-when-out').textContent;
input.value = '2026-08-08T11:00';
input.dispatchEvent(new Event('input', { bubbles: true }));
return { all: all, tuesday: tuesday, saturday: names().length, says: says,
         satSays: document.getElementById('asp-when-out').textContent };
"""


def _probe(page: str, body: str) -> dict:
    import subprocess
    import tempfile

    probe = """
    <pre id="probe-out"></pre>
    <script>
    window.addEventListener('load', function () { setTimeout(function () {
      var out;
      try { out = (function () { %s })(); }
      catch (error) { out = { error: String((error && error.stack) || error) }; }
      document.getElementById('probe-out').textContent = JSON.stringify(out);
    }, 900); });
    </script>
    """ % body
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "airspace.html"
        target.write_text(page + probe, encoding="utf-8")
        out = subprocess.run([CHROME, *CHROME_FLAGS, target.as_uri()],
                             capture_output=True, text=True, timeout=180).stdout
    found = re.search(r'<pre id="probe-out">(.*?)</pre>', out, re.S)
    assert found, out[-2000:]
    answer = json.loads(found.group(1) or "null")
    assert answer and "error" not in answer, answer
    return answer


def _check(answer: dict):
    """The same four claims, whichever map produced them."""
    assert answer["all"] == answer["saturday"], "a Saturday hid a field that is open"
    assert answer["tuesday"], "the Tuesday hid the whole map"
    assert not any(name.startswith("OKRUH LKTA") for name in answer["tuesday"]), (
        "LKTA publishes weekend hours and was still drawn on a Tuesday")
    assert any(name.startswith("OKRUH LKCAST") for name in answer["tuesday"]), (
        "an SLZ strip publishes no hours at all and must never be hidden by the clock")
    assert any(name.startswith("MCTR") for name in answer["tuesday"]), (
        "the base airspace carries no hours and must never be hidden by the clock")
    # Never silent either way: hiding airspace without saying how much, and saying
    # nothing when nothing was hidden, both look like a page that has not run.
    assert "outside published hours" in answer["says"]
    assert "every field with published hours is open" in answer["satSays"]


@needs_chrome
def test_the_flat_map_hides_only_the_fields_that_publish_hours():
    from airspaces import cli as airspace_cli

    overlay, base = _hours_fixture()
    page = airspace_cli._page(render_html.body(overlay, base, "26-04-01"),
                              "Czech airspace")
    _check(_probe(page, """
    function names() {
      return Array.prototype.filter.call(
        document.querySelectorAll('.asp-zone'),
        function (zone) { return zone.style.display !== 'none'; }
      ).map(function (zone) { return zone.dataset.label.split('  (')[0]; });
    }
    var all = names().length;
    """ + _ASK))


@needs_chrome
def test_the_3d_map_gives_the_same_answer_as_the_flat_one():
    """It filters by a different route — a predicate handed to the view rather than a
    pass over the DOM — and it is the one the report and the published page actually
    open with."""
    import numpy as np

    from airspaces import cli as airspace_cli
    from airspaces import scene as airspace_scene
    from parainsights_map import terrain as terrain_module

    overlay, base = _hours_fixture()
    ground = terrain_module.Terrain(
        west=14.0, east=16.0, south=49.0, north=51.0,
        elevations=np.full((24, 24), 400.0),
    )
    payload = airspace_scene.build(base + overlay.airspaces, terrain=ground,
                                   tiles=False)
    page = airspace_cli._page(
        render_html.body(overlay, base, "26-04-01", scene=payload),
        "Czech airspace", three_d=True,
    )
    _check(_probe(page, """
    var canvas = document.querySelector('canvas.view3d');
    var handle = window.__view3dAll[canvas.id];
    function names() {
      var when = window.aspHours.chosen(), holidays = window.aspHours.holidays();
      return (handle.scene().airspaces || []).filter(function (space) {
        return window.aspHours.activeAt(space.w, when, holidays);
      }).map(function (space) { return space.n.split('  (')[0]; });
    }
    var all = names().length;
    """ + _ASK))


# ------------------------------------------- the boxes, in a browser
#
# The claim is geometric and about pixels, so it cannot be made from Python: that a zone
# is drawn as a solid between two heights, and that the solid — not only the outline on
# its floor — is what the reader can point at. Both were wrong in the flat version by
# construction, and both are what somebody looking for "what is above me" is doing.


def _box_page():
    """One base airspace over flat ground, on the real published page."""
    import numpy as np

    from airspaces import cli as airspace_cli
    from airspaces import scene as airspace_scene
    from parainsights_map import terrain as terrain_module

    overlay, base = _hours_fixture()
    ground = terrain_module.Terrain(
        west=14.0, east=16.0, south=49.0, north=51.0,
        elevations=np.full((24, 24), 400.0),
    )
    payload = airspace_scene.build(base + overlay.airspaces, terrain=ground,
                                   tiles=False)
    return airspace_cli._page(
        render_html.body(overlay, base, "26-04-01", scene=payload),
        "Czech airspace", three_d=True,
    )


# Tilted well off the top-down opening camera, because a box seen from straight above is
# its own floor and this test would pass on the flat renderer. North up (`yaw = 0`) so
# that "above the northmost vertex on screen" is a place the floor ring does not reach.
#
# Zoomed in, too, and that is not a convenience: heights are drawn at true scale, so a
# 2 500 m box on a map of the whole country is five pixels tall. Reading it needs the
# zoom a reader looking at one CTR would have used anyway.
_BOX = """
var canvas = document.querySelector('canvas.view3d');
var handle = window.__view3dAll[canvas.id];
handle.view.yaw = 0; handle.view.pitch = 0.45; handle.view.zoom = 6;
handle.view.panX = 0; handle.view.panY = 0;
handle.redraw();
var space = handle.scene().airspaces.filter(function (s) {
  return s.n.indexOf('MCTR') === 0;
})[0];
var centre = handle.toMetres(space.lon[0], space.lat[0]);
var middle = handle.worldProject(centre[0], centre[1], 1500);
var size = handle.metrics();
handle.view.panX += size.W / 2 - middle[0];
handle.view.panY += size.H / 2 - middle[1];
handle.redraw();
var north = 0;
for (var i = 1; i < space.lat.length; i++) {
  if (space.lat[i] > space.lat[north]) north = i;
}
function screenAt(lon, lat, z) {
  var m = handle.toMetres(lon, lat);
  var p = handle.worldProject(m[0], m[1], z);
  var box = canvas.getBoundingClientRect();
  return { x: box.left + p[0] / canvas.width * box.width,
           y: box.top + p[1] / canvas.height * box.height };
}
var lon = space.lon[north], lat = space.lat[north];
var onFloor = screenAt(lon, lat, handle.groundAt(lon, lat));
var onLid = screenAt(lon, lat, space.c);
"""


@needs_chrome
def test_the_box_is_drawn_between_its_two_heights():
    """A ceiling at FL95 over ground at 400 m is 2 500 m of box, and at true scale and
    this zoom that is a measurable number of pixels — up the screen, because the lid is
    above the floor and not merely inside it."""
    answer = _probe(_box_page(), _BOX + """
    return { rise: onFloor.y - onLid.y, ceiling: space.c,
             capped: !!space.t, label: space.n };
    """)
    assert answer["ceiling"] > 2800, "FL95 did not survive into the payload"
    assert not answer["capped"], "FL95 is under the cap and must be drawn true"
    assert answer["rise"] > 25, (
        f"the lid landed {answer['rise']:.1f} px above the floor: not a box")
    assert "FL 95" in answer["label"], "the published ceiling left the label"


@needs_chrome
def test_pointing_at_the_wall_names_the_airspace():
    """What the reader gains, and the reason the hit test had to change with the drawing.
    Tilted, most of what can be seen of a zone is its walls and its lid; a hit test that
    knew only the floor made two thirds of the drawn shape unpointable — and the second
    half of this asserts the point really is off the floor, so it cannot pass by the old
    route."""
    answer = _probe(_box_page(), _BOX + """
    var onBox = handle.airspaceAt(onLid.x, onLid.y);
    // The same page with the lid taken away is the flat renderer, and the same point
    // must then find nothing: that is what makes this a test of the walls.
    delete space.c;
    handle.redraw();
    var flat = handle.airspaceAt(onLid.x, onLid.y);
    return { box: onBox ? onBox.n : null, flat: flat ? flat.n : null };
    """)
    assert answer["box"] and answer["box"].startswith("MCTR"), (
        "a point on the lid found nothing: the box is not hit-tested")
    assert answer["flat"] is None, (
        "the point was inside the floor ring anyway, so this proves nothing about walls")


# ------------------------------------------- the layer over a flight


def _terrain_box(west=14.0, east=14.5, south=50.0, north=50.4):
    import numpy as np

    from parainsights_map import terrain as terrain_module

    return terrain_module.Terrain(west=west, east=east, south=south, north=north,
                                  elevations=np.full((8, 8), 400.0))


def _band(name, west, east, south, north):
    return openair.Airspace(name, "C", floor="GND", ceiling="FL 95", points=[
        (south, west), (south, east), (north, east), (north, west),
    ])


def test_a_flight_gets_the_airspace_that_reaches_its_own_map():
    """743 airspaces over a country is not a layer for a map of one flight. What belongs
    on it is what it can draw: the box the terrain was fetched for."""
    from airspaces import scene as airspace_scene

    over = _band("OVER", 14.1, 14.3, 50.1, 50.3)
    beside = _band("BESIDE", 16.0, 16.2, 50.1, 50.3)
    found = airspace_scene.near(
        [over, beside], west=14.0, east=14.5, south=50.0, north=50.4)
    assert [a.name for a in found] == ["OVER"]


def test_an_airspace_bigger_than_the_map_is_still_over_it():
    """Boxes against boxes, not "has a vertex inside": a TMA the size of Bohemia can
    contain a whole flight without putting one of its own vertices near it, and that is
    exactly the airspace a pilot most wants drawn."""
    from airspaces import scene as airspace_scene

    huge = _band("HUGE", 12.0, 19.0, 48.5, 51.0)
    found = airspace_scene.near(
        [huge], west=14.0, east=14.5, south=50.0, north=50.4)
    assert [a.name for a in found] == ["HUGE"]


def test_the_layer_carries_the_rings_and_their_colours():
    from airspaces import scene as airspace_scene

    layer = airspace_scene.layer([_band("OVER", 14.1, 14.3, 50.1, 50.3)], _terrain_box())
    assert len(layer["airspaces"]) == 1
    assert layer["airspaces"][0]["c"] == pytest.approx(2895, abs=5)
    assert layer["airspaceColours"]["base"]


def test_a_flight_with_nothing_near_it_gets_no_layer_at_all():
    """A flight in Pakistan must carry no button rather than an empty one, and no bytes
    for a layer with nothing in it."""
    from airspaces import scene as airspace_scene

    away = _band("AWAY", 74.0, 74.2, 36.0, 36.2)
    assert airspace_scene.layer([away], _terrain_box()) == {}


def test_the_rings_are_delta_encoded_and_lose_nothing():
    """19 000 vertices on the Planner map, sent as steps of 1e-4° from the vertex before:
    about half the bytes, and the decoded ring is the four-decimal ring exactly."""
    from airspaces import openair, scene as airspace_scene

    space = openair.Airspace("BOX", "C", floor="GND", ceiling="FL 95",
                             points=[(50.0, 14.0), (50.1234, 14.0), (50.1234, 14.5678), (50.0, 14.5678)])
    [ring] = airspace_scene.rings([space])
    assert ring["enc"] == 1e4
    plain = airspace_scene.decoded(ring)
    assert "enc" not in plain
    assert plain["lat"] == pytest.approx([50.0, 50.1234, 50.1234, 50.0], abs=1e-9)
    assert plain["lon"] == pytest.approx([14.0, 14.0, 14.5678, 14.5678], abs=1e-9)

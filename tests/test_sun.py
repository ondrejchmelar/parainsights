"""Solar position, checked against things that are true by astronomy rather than by
whatever this file happened to compute first.

A table of expected numbers copied out of one's own implementation proves it has not
changed, not that it is right. These assert the geometry instead: where the sun stands at
noon on the equinox, how far it gets on the solstices, which side of the sky it is in
before noon, and the hemispheres being opposite. Anchoring it all is a second, genuinely
different algorithm — the Astronomical Almanac's low-precision one, which goes through
right ascension and sidereal time where `sun.py` goes through the equation of time —
written out in this file so the check depends on nothing the code under test does.
"""

import datetime as dt
import math

import pytest

from tracklog_viewer import sun

# Obliquity of the ecliptic: the sun's declination at the solstices, and the number every
# "how high does it get" answer is built from.
TILT = 23.44


def utc(year, month, day, hour=12, minute=0):
    return dt.datetime(year, month, day, hour, minute, tzinfo=dt.timezone.utc)


def solar_noon(day: dt.date, lat: float, lon: float) -> sun.Position:
    """The highest the sun gets that day, found by searching rather than by formula."""
    best = None
    for minute in range(0, 24 * 60, 2):
        when = dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc) + dt.timedelta(
            minutes=minute)
        where = sun.position(when, lat, lon)
        if best is None or where.elevation > best.elevation:
            best = where
    return best


class TestTheGeometryIsRight:
    def test_the_equinox_sun_stands_at_ninety_minus_your_latitude(self):
        """The definition of an equinox, near enough: declination passes through zero."""
        for lat in (0.0, 25.0, 49.0, -34.0):
            noon = solar_noon(dt.date(2024, 3, 20), lat, 14.0)
            assert noon.elevation == pytest.approx(90 - abs(lat), abs=0.6)

    def test_the_solstices_are_the_tilt_either_side_of_that(self):
        lat = 49.0
        june = solar_noon(dt.date(2024, 6, 20), lat, 14.0)
        december = solar_noon(dt.date(2024, 12, 21), lat, 14.0)
        assert june.elevation == pytest.approx(90 - lat + TILT, abs=0.5)
        assert december.elevation == pytest.approx(90 - lat - TILT, abs=0.5)

    def test_at_noon_it_is_south_from_the_north_and_north_from_the_south(self):
        north = solar_noon(dt.date(2024, 4, 10), 49.0, 14.0)
        south = solar_noon(dt.date(2024, 4, 10), -33.0, 151.0)
        assert north.azimuth == pytest.approx(180, abs=2)
        assert south.azimuth % 360 == pytest.approx(0, abs=2) or \
               south.azimuth == pytest.approx(360, abs=2)

    def test_it_comes_up_in_the_east_and_goes_down_in_the_west(self):
        day, lat, lon = dt.date(2024, 6, 20), 49.0, 14.0
        morning = sun.position(utc(2024, 6, 20, 6), lat, lon)
        evening = sun.position(utc(2024, 6, 20, 17), lat, lon)
        assert 0 < morning.azimuth < 180, "before noon the sun is in the eastern half"
        assert 180 < evening.azimuth < 360, "after noon it is in the western half"
        rise, set_ = sun.rise_and_set(day, lat, lon)
        assert rise is not None and set_ is not None
        assert sun.position(
            dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc)
            + dt.timedelta(minutes=rise), lat, lon).azimuth < 90, "midsummer: north of east"

    def test_the_day_is_longer_in_june_than_in_december(self):
        lat, lon = 49.0, 14.0
        june = sun.rise_and_set(dt.date(2024, 6, 20), lat, lon)
        december = sun.rise_and_set(dt.date(2024, 12, 21), lat, lon)
        assert (june[1] - june[0]) - (december[1] - december[0]) == pytest.approx(
            8 * 60, abs=40), "about eight hours of it at this latitude"

    def test_a_polar_day_has_no_sunrise(self):
        rise, set_ = sun.rise_and_set(dt.date(2024, 6, 20), 78.2, 15.6)  # Svalbard
        assert rise is None and set_ is None
        assert sun.position(utc(2024, 6, 20, 0), 78.2, 15.6).up, "and the sun is up at midnight"


def _almanac(when: dt.datetime, lat: float, lon: float) -> tuple[float, float]:
    """The Astronomical Almanac's low-precision solar position, as a second opinion.

    A different algorithm, not a rearrangement of the same one: it goes through right
    ascension and Greenwich mean sidereal time where `sun.position` goes through the
    equation of time. The Almanac quotes it as good to about 0.01° in declination over
    1950–2050, which makes it a fair check on a hillshade direction. Written out here
    rather than imported so the test depends on nothing the code under test does.
    """
    days = (when - dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)).total_seconds() / 86400
    mean_long = math.radians((280.460 + 0.9856474 * days) % 360)
    anomaly = math.radians((357.528 + 0.9856003 * days) % 360)
    ecliptic = mean_long + math.radians(1.915) * math.sin(anomaly) \
        + math.radians(0.020) * math.sin(2 * anomaly)
    obliquity = math.radians(23.439 - 0.0000004 * days)

    right_ascension = math.atan2(math.cos(obliquity) * math.sin(ecliptic), math.cos(ecliptic))
    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic))

    gmst = (18.697374558 + 24.06570982441908 * days) % 24
    local_sidereal = math.radians((gmst * 15 + lon) % 360)
    hour_angle = local_sidereal - right_ascension

    lat_r = math.radians(lat)
    elevation = math.asin(math.sin(lat_r) * math.sin(declination)
                          + math.cos(lat_r) * math.cos(declination) * math.cos(hour_angle))
    azimuth = math.atan2(-math.sin(hour_angle) * math.cos(declination),
                         math.sin(declination) * math.cos(lat_r)
                         - math.cos(declination) * math.sin(lat_r) * math.cos(hour_angle))
    return math.degrees(azimuth) % 360, math.degrees(elevation)


@pytest.mark.parametrize("when,lat,lon", [
    (utc(2024, 6, 21, 10), 50.088, 14.420),     # Prague, midsummer morning
    (utc(2024, 6, 21, 16), 50.088, 14.420),     # and the same day's afternoon
    (utc(2020, 9, 28, 11), 46.50, 11.77),       # the Dolomites, autumn
    (utc(2026, 6, 16, 6), 36.32, 74.65),        # the Hunza flight's launch
    (utc(2022, 12, 3, 13), -33.87, 151.21),     # southern hemisphere
])
def test_it_agrees_with_a_different_algorithm(when, lat, lon):
    """Two independent routes to the same sky. Half a degree is far finer than the DEM
    this is lighting, and finer than the difference a slider step makes."""
    mine = sun.position(when, lat, lon)
    theirs = _almanac(when, lat, lon)
    assert mine.elevation == pytest.approx(theirs[1], abs=0.5)
    gap = (mine.azimuth - theirs[0] + 180) % 360 - 180
    assert gap == pytest.approx(0, abs=0.5)


class TestWhatTheViewGets:
    def test_the_vector_points_at_the_sun_in_the_views_own_frame(self):
        """x east, y north, z up — the frame `view3d` shades in."""
        east = sun.Position(azimuth=90, elevation=0).vector()
        assert east[0] == pytest.approx(1) and east[1] == pytest.approx(0, abs=1e-9)
        overhead = sun.Position(azimuth=123, elevation=90).vector()
        assert overhead[2] == pytest.approx(1)
        south_low = sun.Position(azimuth=180, elevation=30).vector()
        assert south_low[1] == pytest.approx(-math.cos(math.radians(30)))
        assert south_low[2] == pytest.approx(0.5)

    def test_the_day_track_covers_the_day_at_the_step_asked_for(self):
        track = sun.day_track(dt.date(2024, 6, 20), 49.0, 14.0, step_minutes=10)
        assert track["step"] == 10
        assert len(track["az"]) == 144 and len(track["el"]) == 144
        assert max(track["el"]) == pytest.approx(
            solar_noon(dt.date(2024, 6, 20), 49.0, 14.0).elevation, abs=0.3)

    def test_the_azimuth_never_jumps_the_long_way_round(self):
        """Unwrapped, so interpolating two samples cannot sweep the light backwards
        through the whole compass — which is what a wrap at 360 looks like on a slider."""
        track = sun.day_track(dt.date(2024, 6, 20), 49.0, 14.0)
        steps = [b - a for a, b in zip(track["az"], track["az"][1:])]
        assert max(abs(step) for step in steps) < 20

    def test_the_track_is_small_enough_to_embed(self):
        import json

        track = sun.day_track(dt.date(2024, 6, 20), 49.0, 14.0)
        assert len(json.dumps(track, separators=(",", ":"))) < 2000


class TestWhatTheReportGets:
    """`view3d._sun` turns a flight into the payload the panel reads."""

    def _analysis(self, tmp_path):
        from tests.test_analysis import build, circling
        from tracklog_viewer import analysis, igc

        return analysis.analyse(igc.parse(build(tmp_path / "s.igc", circling(400))))

    def test_it_opens_on_the_middle_of_the_flight(self, tmp_path):
        from tracklog_viewer import view3d

        payload = view3d._sun(self._analysis(tmp_path))
        assert payload["launch"] <= payload["at"] <= payload["landing"]
        assert payload["track"]["step"] == 10

    def test_the_offset_turns_utc_into_the_pilots_own_clock(self, tmp_path):
        """The tables in the report are local time; the sun is computed in UTC. This is
        the one number where the two meet, and getting it backwards moves the light by
        a couple of hours without looking wrong."""
        from tracklog_viewer import view3d

        flight = self._analysis(tmp_path).flight
        payload = view3d._sun(self._analysis(tmp_path))
        launch = flight.local_time(0)
        assert payload["offset"] == int((launch.utcoffset() or dt.timedelta()).total_seconds() // 60)
        local = (payload["launch"] + payload["offset"]) % 1440
        assert local // 60 == launch.hour and local % 60 == launch.minute

    def test_the_caption_names_where_the_sun_stood(self, tmp_path):
        from tracklog_viewer import render_html, view3d

        note = render_html._sun_note(view3d._sun(self._analysis(tmp_path)))
        assert "The sun was up from" in note
        assert "at launch it stood" in note
        assert render_html._sun_note(None) == ""

"""Where the sun was, minute by minute, over the flight.

A pilot's questions about light are questions about slopes: which face was working at
eleven, when did the west side switch on, why did that spine die at four. The hillshade
in the 3D view answers none of them while it is lit from a fixed north-west — a direction
the sun is never in, anywhere in the northern hemisphere.

This is the NOAA solar position algorithm, the one behind their published calculator.
Pure arithmetic on a datetime and a coordinate: no dependencies, no network, and cheap
enough to tabulate the whole day.

Two deliberate omissions. **No atmospheric refraction**: it lifts the apparent sun by
about half a degree at the horizon and by almost nothing above 10°, and the question here
is which slope the light reaches, which is a geometric question. **No topographic
horizon**: the sun rises when it clears the *sea* horizon, not when it clears the ridge
to your east — a real answer would need to march the DEM along the bearing, and the view
draws the terrain's own shadows anyway.

Accuracy is a few tenths of a degree over the years a tracklog can plausibly come from,
which is far finer than the DEM the light is being cast on.
"""

import datetime as dt
import math
from dataclasses import dataclass

# Below this the sun is down. It is 0 rather than the -0.833 a sunrise table uses,
# because that figure exists to account for refraction and the sun's own disc, and
# neither is modelled here.
HORIZON = 0.0


@dataclass(frozen=True)
class Position:
    """Where the sun is, as a compass bearing and a height above the horizon."""

    azimuth: float    # degrees clockwise from north
    elevation: float  # degrees above the horizon, negative when down

    @property
    def up(self) -> bool:
        return self.elevation > HORIZON

    def vector(self) -> tuple[float, float, float]:
        """Unit vector *towards* the sun, in the view's frame: x east, y north, z up."""
        az = math.radians(self.azimuth)
        el = math.radians(self.elevation)
        return (math.cos(el) * math.sin(az), math.cos(el) * math.cos(az), math.sin(el))


def _julian_century(when: dt.datetime) -> float:
    """Julian centuries since J2000.0, from a UTC datetime."""
    when = when.astimezone(dt.timezone.utc) if when.tzinfo else when.replace(
        tzinfo=dt.timezone.utc)
    year, month = when.year, when.month
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    day = (when.day + (when.hour + (when.minute + when.second / 60) / 60) / 24)
    jd = (math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1))
          + day + b - 1524.5)
    return (jd - 2451545.0) / 36525.0


def position(when: dt.datetime, lat: float, lon: float) -> Position:
    """The sun's azimuth and elevation, seen from (lat, lon) at `when`.

    `when` is UTC — naive datetimes are read as UTC rather than as local time, because a
    tracklog's B records are UTC and guessing otherwise is how a flight ends up analysed
    against the wrong day's light.
    """
    jc = _julian_century(when)

    mean_long = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    mean_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    eccentricity = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)

    centre = (math.sin(math.radians(mean_anom)) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
              + math.sin(math.radians(2 * mean_anom)) * (0.019993 - 0.000101 * jc)
              + math.sin(math.radians(3 * mean_anom)) * 0.000289)
    true_long = mean_long + centre
    # The apparent longitude: the true one corrected for aberration and nutation.
    apparent = true_long - 0.00569 - 0.00478 * math.sin(math.radians(125.04 - 1934.136 * jc))

    mean_obliquity = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    obliquity = mean_obliquity + 0.00256 * math.cos(math.radians(125.04 - 1934.136 * jc))

    declination = math.degrees(math.asin(
        math.sin(math.radians(obliquity)) * math.sin(math.radians(apparent))))

    # The equation of time, in minutes: the gap between clock noon and the sun's own.
    vary = math.tan(math.radians(obliquity / 2)) ** 2
    eq_time = 4 * math.degrees(
        vary * math.sin(2 * math.radians(mean_long))
        - 2 * eccentricity * math.sin(math.radians(mean_anom))
        + 4 * eccentricity * vary * math.sin(math.radians(mean_anom))
        * math.cos(2 * math.radians(mean_long))
        - 0.5 * vary * vary * math.sin(4 * math.radians(mean_long))
        - 1.25 * eccentricity * eccentricity * math.sin(2 * math.radians(mean_anom)))

    utc = when.astimezone(dt.timezone.utc) if when.tzinfo else when
    minutes = utc.hour * 60 + utc.minute + utc.second / 60
    true_solar = (minutes + eq_time + 4 * lon) % 1440
    # Solar time runs 0–1440 minutes, so a quarter of it is 0–360°; subtracting 180 puts
    # noon at zero and lands the result in [-180, 180) without a wrap test.
    hour_angle = true_solar / 4 - 180

    lat_r = math.radians(lat)
    dec_r = math.radians(declination)
    ha_r = math.radians(hour_angle)

    cos_zenith = (math.sin(lat_r) * math.sin(dec_r)
                  + math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r))
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    zenith = math.acos(cos_zenith)
    elevation = 90 - math.degrees(zenith)

    sin_zenith = math.sin(zenith)
    if abs(sin_zenith) < 1e-9 or abs(math.cos(lat_r)) < 1e-9:
        # Straight overhead, or standing on a pole: the bearing is undefined, and 180 is
        # the least surprising answer for a shading direction.
        azimuth = 180.0
    else:
        ratio = ((math.sin(lat_r) * cos_zenith) - math.sin(dec_r)) / (math.cos(lat_r) * sin_zenith)
        ratio = max(-1.0, min(1.0, ratio))
        azimuth = math.degrees(math.acos(ratio))
        azimuth = (azimuth + 180) % 360 if hour_angle > 0 else (540 - azimuth) % 360

    return Position(azimuth=azimuth, elevation=elevation)


def day_track(day: dt.date, lat: float, lon: float, *, step_minutes: int = 10) -> dict:
    """The sun's whole day at one place, sampled for the browser to interpolate.

    Tabulating beats porting the algorithm into JavaScript. `quicklook.py` already
    duplicates a subset of the analysis and every threshold in it is a thing that can
    drift; a table cannot drift. Two parallel arrays rather than a list of objects,
    because the keys would be two thirds of the bytes: this comes to under 2 KB.

    Azimuth is *unwrapped* — it passes 360 rather than dropping to 0 — so that
    interpolating between two samples never sweeps the light the long way round the
    compass, which on a slider reads as the sun jumping backwards through the whole sky.
    """
    az, el = [], []
    previous = None
    for minute in range(0, 24 * 60, step_minutes):
        when = dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc) + dt.timedelta(
            minutes=minute)
        where = position(when, lat, lon)
        bearing = where.azimuth
        if previous is not None:
            while bearing - previous > 180:
                bearing -= 360
            while previous - bearing > 180:
                bearing += 360
        previous = bearing
        az.append(round(bearing, 1))
        el.append(round(where.elevation, 1))
    return {"step": step_minutes, "az": az, "el": el}


def _crossing(day: dt.date, lat: float, lon: float, low: int, high: int) -> float | None:
    """Minute (UTC) between `low` and `high` at which the elevation crosses the horizon."""
    def at(minute: float) -> float:
        when = dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc) + dt.timedelta(
            minutes=minute)
        return position(when, lat, lon).elevation

    if (at(low) > HORIZON) == (at(high) > HORIZON):
        return None
    for _ in range(24):                      # bisection to well under a minute
        mid = (low + high) / 2
        if (at(low) > HORIZON) == (at(mid) > HORIZON):
            low = mid
        else:
            high = mid
    return (low + high) / 2


def rise_and_set(day: dt.date, lat: float, lon: float) -> tuple[float | None, float | None]:
    """Sunrise and sunset as minutes past midnight UTC, or None inside a polar day/night.

    Found by bisecting the elevation rather than by the closed-form hour angle: the same
    `position()` answers both, so the two cannot disagree about where the sun is.
    """
    samples = [(m, position(
        dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc) + dt.timedelta(minutes=m),
        lat, lon).elevation) for m in range(0, 24 * 60 + 1, 10)]
    rise = set_ = None
    for (m0, e0), (m1, e1) in zip(samples, samples[1:]):
        if e0 <= HORIZON < e1 and rise is None:
            rise = _crossing(day, lat, lon, m0, m1)
        if e0 > HORIZON >= e1 and set_ is None:
            set_ = _crossing(day, lat, lon, m0, m1)
    return rise, set_

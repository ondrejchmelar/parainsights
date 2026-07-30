"""Weather for the day and place of the flight.

Opt-in: this is the only part of the tracklog viewer that touches the network, and it is off
unless asked for. What it fetches gets embedded in the report, so the report itself
stays self-contained afterwards.

Source is Open-Meteo's operational model archive, which carries recent past days —
that matters, because a flight is usually reviewed the day after and the ERA5
reanalysis archive lags several days behind. Flymet's meteograms
(``flymet.meteopress.cz/meteogram/<SITE>.png``) are same-day forecast images with no
archive endpoint, so they can enrich a *pre-flight* plan but cannot describe a flight
already flown.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import geo

FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
# ERA5 reanalysis: has the whole back catalogue, but lags the present by days.
ARCHIVE_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
# The forecast endpoint's past_days tops out at 92, and the archive's coverage stops
# short of the present, so recent flights use one and old flights the other.
RECENT_DAYS = 60
PRESSURE_LEVELS = (1000, 975, 950, 925, 900, 850, 800, 700, 600, 500)
SURFACE_FIELDS = (
    "temperature_2m",
    "dew_point_2m",
    "cape",
    "boundary_layer_height",
    "cloud_cover_low",
    "cloud_cover_mid",
    "wind_speed_10m",
    "wind_direction_10m",
)
LEVEL_FIELDS = ("temperature", "dew_point", "wind_speed", "wind_direction", "geopotential_height")
DALR = 9.8 / 1000  # dry adiabatic lapse rate, °C per metre
LCL_PER_DEGREE = 125.0  # metres of cloudbase per °C of spread — the usual rule of thumb
CACHE = Path.home() / ".cache" / "parainsights"
TIMEOUT = 25


@dataclass
class Level:
    pressure: int  # hPa
    height: float  # metres above sea level
    temperature: float  # °C
    dew_point: float  # °C
    wind_speed: float  # km/h
    wind_direction: float  # degrees, the direction it blows FROM


@dataclass
class Meteo:
    valid_at: str
    source: str
    latitude: float
    longitude: float
    elevation: float  # model ground elevation, m
    surface_temperature: float
    surface_dew_point: float
    surface_wind_speed: float
    surface_wind_direction: float
    cape: float | None
    boundary_layer_height: float | None  # metres above ground
    cloud_cover_low: float | None
    cloud_cover_mid: float | None
    levels: list[Level] = field(default_factory=list)

    @property
    def cloudbase(self) -> float:
        """Estimated cumulus base, metres above sea level."""
        spread = self.surface_temperature - self.surface_dew_point
        return self.elevation + LCL_PER_DEGREE * max(spread, 0.0)

    @property
    def boundary_layer_top(self) -> float | None:
        """Boundary layer top as an absolute altitude, which is how pilots think."""
        if self.boundary_layer_height is None:
            return None
        return self.elevation + self.boundary_layer_height

    @property
    def thermal_top(self) -> float | None:
        """Where a surface parcel stops being warmer than its surroundings.

        A dry adiabat from the surface temperature, crossed against the model's
        temperature profile: the classic thermal-top construction, and the number
        a pilot can compare against the height they actually reached.
        """
        parcel_base = self.surface_temperature
        previous = None
        for level in self.levels:
            if level.height <= self.elevation:
                continue
            parcel = parcel_base - DALR * (level.height - self.elevation)
            excess = parcel - level.temperature
            if previous is not None and previous[1] > 0 >= excess:
                # Linear interpolation onto the crossing point.
                (height0, excess0) = previous
                span = excess0 - excess
                fraction = excess0 / span if span else 0.0
                return height0 + fraction * (level.height - height0)
            previous = (level.height, excess)
        return None

    def wind_at(self, height: float) -> tuple[float, float] | None:
        """Interpolate the model wind to an altitude: (km/h, degrees from)."""
        levels = [level for level in self.levels if level.height is not None]
        if not levels:
            return None
        below = [level for level in levels if level.height <= height]
        above = [level for level in levels if level.height > height]
        if not below:
            return above[0].wind_speed, above[0].wind_direction
        if not above:
            return below[-1].wind_speed, below[-1].wind_direction
        low, high = below[-1], above[0]
        span = high.height - low.height
        fraction = (height - low.height) / span if span else 0.0
        speed = low.wind_speed + fraction * (high.wind_speed - low.wind_speed)
        # Interpolate direction the short way around the compass.
        delta = ((high.wind_direction - low.wind_direction + 180) % 360) - 180
        direction = (low.wind_direction + fraction * delta) % 360
        return speed, direction

    def to_dict(self) -> dict:
        data = asdict(self)
        data["cloudbase"] = round(self.cloudbase)
        data["thermal_top"] = round(self.thermal_top) if self.thermal_top else None
        data["boundary_layer_top"] = (
            round(self.boundary_layer_top) if self.boundary_layer_top else None
        )
        return data


def _request(endpoint: str, params: dict) -> dict:
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _cache_path(params: dict) -> Path:
    key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
    return CACHE / f"meteo-{key}.json"


def fetch(lat: float, lon: float, when: dt.datetime, *, use_cache: bool = True) -> Meteo | None:
    """Fetch the vertical profile over (lat, lon) at the hour nearest ``when``.

    Returns None rather than raising if the network is unavailable or the day is
    out of range — a flight report must still render on a train.
    """
    hourly = list(SURFACE_FIELDS) + [
        f"{field}_{level}hPa" for level in PRESSURE_LEVELS for field in LEVEL_FIELDS
    ]
    days_ago = (dt.date.today() - when.date()).days
    params = {
        "latitude": round(lat, 3),
        "longitude": round(lon, 3),
        "hourly": ",".join(hourly),
        "timezone": "UTC",
    }
    if days_ago > RECENT_DAYS:
        # An old flight from the back catalogue: ask the reanalysis for that date.
        endpoint = ARCHIVE_ENDPOINT
        params["start_date"] = when.date().isoformat()
        params["end_date"] = when.date().isoformat()
    else:
        # Reviewing a recent flight, possibly yesterday's: the operational model
        # carries the recent past, which the reanalysis does not.
        endpoint = FORECAST_ENDPOINT
        params["past_days"] = max(min(days_ago + 1, 92), 1)
        params["forecast_days"] = 1

    path = _cache_path(params)
    payload = None
    if use_cache and path.exists():
        try:
            payload = json.loads(path.read_text())
        except ValueError:
            payload = None
    if payload is None:
        try:
            payload = _request(endpoint, params)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return None
        if use_cache:
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload))

    return _parse(payload, when)


def _parse(payload: dict, when: dt.datetime) -> Meteo | None:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None

    target = when.astimezone(dt.timezone.utc).replace(tzinfo=None) if when.tzinfo else when
    stamps = [dt.datetime.fromisoformat(t) for t in times]
    index = min(range(len(stamps)), key=lambda i: abs((stamps[i] - target).total_seconds()))
    if abs((stamps[index] - target).total_seconds()) > 5400:
        return None  # the requested hour is not in the response

    def value(name):
        column = hourly.get(name)
        if not column or index >= len(column):
            return None
        return column[index]

    levels = []
    for pressure in PRESSURE_LEVELS:
        height = value(f"geopotential_height_{pressure}hPa")
        temperature = value(f"temperature_{pressure}hPa")
        if height is None or temperature is None:
            continue
        levels.append(
            Level(
                pressure=pressure,
                height=float(height),
                temperature=float(temperature),
                dew_point=float(value(f"dew_point_{pressure}hPa") or temperature),
                wind_speed=float(value(f"wind_speed_{pressure}hPa") or 0.0),
                wind_direction=float(value(f"wind_direction_{pressure}hPa") or 0.0),
            )
        )
    levels.sort(key=lambda level: level.height)
    # No levels is not a failure. The ERA5 archive serves surface fields for any past
    # date but returns nulls for every pressure level, so an old flight gets a
    # surface-only picture: cloudbase, instability and mixing depth still say
    # something useful about the day, and the consumers all check for levels.
    surface_temperature = value("temperature_2m")
    if surface_temperature is None:
        return None

    return Meteo(
        valid_at=stamps[index].strftime("%Y-%m-%d %H:%M UTC"),
        source=(
            ("ERA5 reanalysis, surface only" if not levels else "ERA5 reanalysis")
            if (dt.date.today() - stamps[index].date()).days > RECENT_DAYS
            else "Open-Meteo operational model"
        ),
        latitude=float(payload.get("latitude", 0.0)),
        longitude=float(payload.get("longitude", 0.0)),
        elevation=float(payload.get("elevation", 0.0)),
        surface_temperature=float(surface_temperature),
        surface_dew_point=float(value("dew_point_2m") or surface_temperature),
        surface_wind_speed=float(value("wind_speed_10m") or 0.0),
        surface_wind_direction=float(value("wind_direction_10m") or 0.0),
        cape=_maybe_float(value("cape")),
        boundary_layer_height=_maybe_float(value("boundary_layer_height")),
        cloud_cover_low=_maybe_float(value("cloud_cover_low")),
        cloud_cover_mid=_maybe_float(value("cloud_cover_mid")),
        levels=levels,
    )


def _maybe_float(value):
    return None if value is None else float(value)


def for_flight(analysis, *, use_cache: bool = True) -> Meteo | None:
    """Fetch the profile over the middle of the track, at mid-flight."""
    flight = analysis.flight
    middle = len(flight) // 2
    when = flight.time[middle].astype("datetime64[s]").item()
    return fetch(
        float(flight.lat[middle]), float(flight.lon[middle]), when, use_cache=use_cache
    )


def cardinal(direction: float) -> str:
    return geo.cardinal(direction)

"""Meteo parsing and derived-quantity tests. No network: the payload is a fixture."""

import datetime as dt

import pytest

from tracklog_viewer import meteo as meteo_module

# Shaped like a real Open-Meteo response, with the values from 2026-07-28 over the
# Všechov course line — including the stable layer that capped that day.
PAYLOAD = {
    "latitude": 49.46,
    "longitude": 14.96,
    "elevation": 612.0,
    "hourly": {
        "time": ["2026-07-28T11:00", "2026-07-28T12:00", "2026-07-28T13:00"],
        "temperature_2m": [21.0, 23.0, 24.0],
        "dew_point_2m": [8.0, 8.3, 8.5],
        "cape": [10.0, 20.0, 30.0],
        "boundary_layer_height": [1500.0, 1760.0, 1800.0],
        "cloud_cover_low": [10.0, 16.0, 25.0],
        "cloud_cover_mid": [0.0, 5.0, 10.0],
        "wind_speed_10m": [9.0, 10.0, 11.0],
        "wind_direction_10m": [250.0, 253.0, 255.0],
        "temperature_950hPa": [19.0, 21.0, 21.5],
        "dew_point_950hPa": [7.0, 7.2, 7.4],
        "wind_speed_950hPa": [12.0, 13.0, 14.0],
        "wind_direction_950hPa": [252.0, 254.0, 256.0],
        "geopotential_height_950hPa": [630.0, 631.0, 632.0],
        "temperature_850hPa": [11.0, 11.1, 11.3],
        "dew_point_850hPa": [4.5, 4.8, 5.0],
        "wind_speed_850hPa": [14.0, 15.0, 16.0],
        "wind_direction_850hPa": [265.0, 267.0, 269.0],
        "geopotential_height_850hPa": [1575.0, 1576.0, 1577.0],
        "temperature_800hPa": [9.0, 9.1, 9.2],
        "dew_point_800hPa": [-4.0, -3.9, -3.8],
        "wind_speed_800hPa": [24.0, 25.0, 26.0],
        "wind_direction_800hPa": [285.0, 287.0, 289.0],
        "geopotential_height_800hPa": [2079.0, 2080.0, 2081.0],
    },
}


@pytest.fixture
def sample():
    return meteo_module._parse(PAYLOAD, dt.datetime(2026, 7, 28, 12, 0))


def test_picks_the_nearest_hour(sample):
    assert sample.valid_at == "2026-07-28 12:00 UTC"
    assert sample.surface_temperature == 23.0
    assert sample.cape == 20.0


def test_levels_are_sorted_by_height(sample):
    heights = [level.height for level in sample.levels]
    assert heights == sorted(heights)
    assert [level.pressure for level in sample.levels] == [950, 850, 800]


def test_cloudbase_from_the_spread(sample):
    # 23.0 - 8.3 = 14.7 K spread, 125 m per K, above 612 m of ground.
    assert sample.cloudbase == pytest.approx(612 + 14.7 * 125, abs=1)


def test_boundary_layer_top_is_absolute(sample):
    assert sample.boundary_layer_top == pytest.approx(612 + 1760)


def test_thermal_top_is_where_the_adiabat_crosses(sample):
    top = sample.thermal_top
    assert top is not None
    # A parcel leaving 612 m at 23 °C is still warmer than the 850 hPa level but
    # colder than the stable 800 hPa layer, so the crossing is between them.
    assert 1576 < top < 2080


def test_wind_interpolates_between_levels(sample):
    speed, direction = sample.wind_at(1075.5)  # midway between 950 and 850 hPa
    assert speed == pytest.approx(14.0, abs=0.3)
    assert 254 < direction < 267


def test_wind_below_and_above_the_profile_clamps(sample):
    assert sample.wind_at(0)[0] == pytest.approx(13.0)
    assert sample.wind_at(9000)[0] == pytest.approx(25.0)


def test_wind_direction_interpolation_takes_the_short_way():
    payload = {
        "latitude": 0,
        "longitude": 0,
        "elevation": 0,
        "hourly": {
            "time": ["2026-07-28T12:00"],
            "temperature_2m": [20.0],
            "dew_point_2m": [10.0],
            "temperature_950hPa": [18.0],
            "geopotential_height_950hPa": [500.0],
            "wind_speed_950hPa": [10.0],
            "wind_direction_950hPa": [350.0],
            "temperature_850hPa": [12.0],
            "geopotential_height_850hPa": [1500.0],
            "wind_speed_850hPa": [10.0],
            "wind_direction_850hPa": [10.0],
        },
    }
    sample = meteo_module._parse(payload, dt.datetime(2026, 7, 28, 12, 0))
    # 350° to 10° is 20° apart across north, not 340° the other way.
    _, direction = sample.wind_at(1000.0)
    assert direction == pytest.approx(0.0, abs=1) or direction == pytest.approx(360.0, abs=1)


def test_missing_hour_returns_none():
    assert meteo_module._parse(PAYLOAD, dt.datetime(2026, 7, 20, 12, 0)) is None


def test_empty_payload_returns_none():
    assert meteo_module._parse({}, dt.datetime(2026, 7, 28, 12, 0)) is None


def test_serialises_with_derived_values(sample):
    data = sample.to_dict()
    assert data["cloudbase"] == round(sample.cloudbase)
    assert data["boundary_layer_top"] == round(sample.boundary_layer_top)
    assert data["levels"][0]["pressure"] == 950

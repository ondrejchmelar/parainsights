"""Spherical geometry on the FAI sphere.

FAI-sanctioned distances are measured on a sphere of radius 6 371 000 m, so this
is the correct model for flight distances, not an approximation we tolerate.
"""

import numpy as np

R = 6371000.0

CARDINALS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()


def distance(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres. Scalars or arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    # Haversine rather than the spherical law of cosines: acos loses precision
    # badly at the ~10 m separations between consecutive 1 Hz fixes.
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def bearing(lat1, lon1, lat2, lon2):
    """Initial bearing in degrees, 0 = north, clockwise. Scalars or arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlon = lon2 - lon1
    y = np.sin(dlon) * np.cos(lat2)
    x = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
    return np.degrees(np.arctan2(y, x)) % 360.0


def cardinal(degrees: float) -> str:
    """Nearest 16-point compass name for a bearing in degrees."""
    return CARDINALS[int(degrees / 22.5 + 0.5) % 16]


def cumulative_distance(lat, lon) -> np.ndarray:
    """Distance flown along the track, in metres, starting at 0."""
    steps = distance(lat[:-1], lon[:-1], lat[1:], lon[1:])
    return np.concatenate(([0.0], np.cumsum(steps)))

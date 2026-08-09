"""Local-plane geodesy on the WGS84 ellipsoid.

Deliberately not `tracklog_viewer.geo`, which works on the FAI sphere of radius
6 371 000 m. That sphere is the right model for a scored distance and the wrong one
here: an airspace boundary is published against WGS84, and the two disagree by about
0.2%. Over the 5 500 m radius of a Czech ATZ that is 11 m — small, but it is the
difference between the fitted radius reading 5 500.3 m and reading 5 490 m, and the
whole argument for replacing a thousand-vertex polygon with one circle is that the
circle is *exact*.

Everything here is a local tangent-plane approximation about a reference latitude.
Over a 20 km box that is good to well under a metre, and no airspace item this module
builds is larger than that.
"""

from __future__ import annotations

import math

# WGS84.
A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)


def metres_per_degree(lat: float) -> tuple[float, float]:
    """Metres per degree of latitude and of longitude at this latitude.

    The two radii differ — meridional curvature is not prime-vertical curvature — and
    using one for both is the usual way a "spherical earth" fit ends up 0.2% out.
    """
    sin_lat = math.sin(math.radians(lat))
    w = math.sqrt(1 - E2 * sin_lat * sin_lat)
    meridional = A * (1 - E2) / w**3
    prime_vertical = A / w
    return (
        meridional * math.pi / 180,
        prime_vertical * math.cos(math.radians(lat)) * math.pi / 180,
    )


class Plane:
    """A local east/north plane in metres, anchored at one point."""

    def __init__(self, lat: float, lon: float):
        self.lat0, self.lon0 = lat, lon
        self.m_lat, self.m_lon = metres_per_degree(lat)

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.m_lon, (lat - self.lat0) * self.m_lat

    def to_ll(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / self.m_lat, self.lon0 + x / self.m_lon


def offset(lat: float, lon: float, east: float, north: float) -> tuple[float, float]:
    """Move a point by a metric offset."""
    m_lat, m_lon = metres_per_degree(lat)
    return lat + north / m_lat, lon + east / m_lon


def destination(lat: float, lon: float, bearing: float, distance: float) -> tuple[float, float]:
    """The point `distance` metres from here along a true `bearing` in degrees.

    Refined once about the midpoint latitude. Taking the scale at the *start* instead
    leaves the result inconsistent with `distance`, which uses the midpoint — 0.8 m
    over a 5 km leg, which is small but is the kind of asymmetry that makes a box's
    two ends disagree.
    """
    theta = math.radians(bearing)
    east, north = distance * math.sin(theta), distance * math.cos(theta)
    rough_lat, _ = offset(lat, lon, east, north)
    m_lat, m_lon = metres_per_degree((lat + rough_lat) / 2)
    return lat + north / m_lat, lon + east / m_lon


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """True bearing in degrees, 0 = north, clockwise, on the local plane."""
    m_lat, m_lon = metres_per_degree((lat1 + lat2) / 2)
    return math.degrees(math.atan2((lon2 - lon1) * m_lon, (lat2 - lat1) * m_lat)) % 360.0


def distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Metres between two nearby points."""
    m_lat, m_lon = metres_per_degree((lat1 + lat2) / 2)
    return math.hypot((lon2 - lon1) * m_lon, (lat2 - lat1) * m_lat)


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker on a planar point list, iteratively so a 3 500-vertex ring
    cannot blow the recursion limit."""
    if len(points) < 3:
        return list(points)
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        ax, ay = points[i]
        bx, by = points[j]
        dx, dy = bx - ax, by - ay
        span = math.hypot(dx, dy)
        worst, worst_at = 0.0, None
        for k in range(i + 1, j):
            px, py = points[k]
            if span:
                off = abs(dy * px - dx * py + bx * ay - by * ax) / span
            else:
                off = math.hypot(px - ax, py - ay)
            if off > worst:
                worst, worst_at = off, k
        if worst > tolerance and worst_at is not None:
            keep.add(worst_at)
            stack.append((i, worst_at))
            stack.append((worst_at, j))
    return [points[i] for i in sorted(keep)]


def fit_circle(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Least-squares circle through planar points: (cx, cy, radius, max_error).

    Kåsa's algebraic fit. It is biased when the points cover only a short arc, which
    does not arise here — every candidate is either a full circle or is rejected by
    the error it reports.
    """
    n = len(points)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    syy = sum(y * y for y in ys)
    sxy = sum(x * y for x, y in points)
    sxxx = sum(x**3 for x in xs)
    syyy = sum(y**3 for y in ys)
    sxyy = sum(x * y * y for x, y in points)
    sxxy = sum(x * x * y for x, y in points)
    c = n * sxx - sx * sx
    d = n * sxy - sx * sy
    e = n * sxxx + n * sxyy - (sxx + syy) * sx
    g = n * syy - sy * sy
    h = n * sxxy + n * syyy - (sxx + syy) * sy
    det = 2 * (c * g - d * d)
    if abs(det) < 1e-9:
        return 0.0, 0.0, 0.0, float("inf")
    cx = (e * g - d * h) / det
    cy = (c * h - d * e) / det
    radii = [math.hypot(x - cx, y - cy) for x, y in points]
    radius = sum(radii) / n
    return cx, cy, radius, max(abs(r - radius) for r in radii)


CARDINALS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()


def cardinal(degrees: float) -> str:
    """Nearest 16-point compass name for a bearing."""
    return CARDINALS[int(degrees / 22.5 + 0.5) % 16]


def centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)

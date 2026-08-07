"""Which face was lit, and how strongly, at the minute each climb started.

Two data the report already carries, joined for the first time. `terrain.py` holds the
elevation grid; `sun.py` computes the solar position that the 3D view already re-lights
the terrain from. Slope and aspect are a gradient of that grid, and the cosine of the
angle between a cell's surface normal and the sun vector is its relative insolation at
any moment. So the question a pilot asks about a new site all day long — *what was the
sun doing to that face when it worked* — is arithmetic over data that costs nothing new.

Two rules carried in from the analysis plan and worth restating because they are what
keeps this honest:

- **Relative, never absolute.** This is `cos θ` on a bare geometric surface. It knows
  nothing about cloud, haze, ground cover, soil moisture or albedo, so a cell's number
  only means anything next to another cell's on the same grid at the same minute. Every
  figure below is a comparison, never a W/m².
- **A trigger is not a cause.** A climb started over a lit south-west face is a
  measurement; that the face *caused* the climb is a story, and the pilot is the one who
  gets to tell it.
"""

import datetime as dt
from dataclasses import dataclass

import numpy as np

from . import sun as sun_module
from .analysis import Analysis, Phase

# How far around a climb's trigger point to look when asking "compared with what". A
# thermal is fed by a slope, not by a pixel, and a 30 m DEM cell is far smaller than the
# feature that made the lift.
NEIGHBOURHOOD = 1500.0     # metres
# Below this the sun is too low for the cosine to mean much: at 5 degrees every slope is
# either in shadow or edge-on, and the ratios blow up.
MIN_ELEVATION = 8.0        # degrees
# A slope flatter than this has no aspect worth naming — the gradient is noise, and a
# DEM's own quantisation is most of it.
MIN_SLOPE = 3.0            # degrees


@dataclass
class Face:
    """The ground under one climb, and what the sun was doing to it."""

    index: int                 # fix index the climb started at
    minute: int                # UTC minute of the day
    slope: float               # degrees from horizontal
    aspect: float | None       # degrees, the compass bearing the slope faces
    lit: float                 # cos of the angle to the sun, 0..1, clipped at the horizon
    neighbourhood: float       # mean `lit` over the ground around it
    elevation: float           # the sun's height, degrees

    @property
    def advantage(self) -> float:
        """How much better lit than the ground around it. 1.0 is average."""
        return self.lit / self.neighbourhood if self.neighbourhood > 0.02 else 1.0


@dataclass
class Insolation:
    faces: list[Face]
    windward: float | None = None      # share of climbs on a slope facing the wind
    wind_from: float | None = None

    @property
    def measured(self) -> bool:
        return bool(self.faces)

    @property
    def mean_advantage(self) -> float | None:
        if not self.faces:
            return None
        return round(float(np.mean([f.advantage for f in self.faces])), 2)


def gradient(terrain) -> tuple[np.ndarray, np.ndarray]:
    """Slope and aspect of every cell, in degrees.

    The grid is in degrees of latitude and longitude, so the two axes are different
    lengths on the ground and getting that wrong tilts every slope towards north-south.
    A degree of latitude is ~111 km everywhere; a degree of longitude is that times the
    cosine of the latitude, which at 46 degrees is a 30% difference — enough to rotate a
    south-west face into a south one.
    """
    rows, cols = terrain.elevations.shape
    mid_lat = (terrain.north + terrain.south) / 2
    metres_per_degree = 111_320.0
    dy = (terrain.north - terrain.south) / max(rows - 1, 1) * metres_per_degree
    dx = ((terrain.east - terrain.west) / max(cols - 1, 1) * metres_per_degree
          * float(np.cos(np.radians(mid_lat))))
    # Row 0 is the northern edge, so a positive row step goes *south*: negate the row
    # gradient to get a northward derivative.
    dz_dy, dz_dx = np.gradient(terrain.elevations.astype(float), dy, dx)
    dz_dy = -dz_dy
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    # Aspect: the compass bearing of steepest *descent*, which is the way the face looks.
    aspect = (np.degrees(np.arctan2(-dz_dx, -dz_dy))) % 360
    return slope, aspect


def lit_grid(slope: np.ndarray, aspect: np.ndarray, azimuth: float,
             elevation: float) -> np.ndarray:
    """Relative insolation of every cell: the cosine of the angle to the sun, clipped.

    Clipped at zero rather than allowed negative: a face turned away from the sun gets
    no direct light, and how far away it is turned makes no difference to that.
    """
    if elevation <= 0:
        return np.zeros_like(slope)
    s, a = np.radians(slope), np.radians(aspect)
    sun_el, sun_az = np.radians(elevation), np.radians(azimuth)
    cos_theta = (
        np.cos(s) * np.sin(sun_el)
        + np.sin(s) * np.cos(sun_el) * np.cos(sun_az - a)
    )
    return np.clip(cos_theta, 0.0, 1.0)


def _cell(terrain, lat: float, lon: float) -> tuple[int, int]:
    row = (terrain.north - lat) / (terrain.north - terrain.south) * (terrain.rows - 1)
    col = (lon - terrain.west) / (terrain.east - terrain.west) * (terrain.cols - 1)
    return (
        int(np.clip(round(row), 0, terrain.rows - 1)),
        int(np.clip(round(col), 0, terrain.cols - 1)),
    )


def for_flight(analysis: Analysis, terrain, *, wind=None) -> Insolation:
    """The lit face under every climb's trigger, against the ground around it."""
    if terrain is None or terrain.elevations.size < 9:
        return Insolation([])
    flight = analysis.flight
    slope, aspect = gradient(terrain)

    mid_lat = (terrain.north + terrain.south) / 2
    metres_per_row = ((terrain.north - terrain.south) / max(terrain.rows - 1, 1)
                      * 111_320.0)
    metres_per_col = ((terrain.east - terrain.west) / max(terrain.cols - 1, 1)
                      * 111_320.0 * float(np.cos(np.radians(mid_lat))))
    reach_rows = max(int(NEIGHBOURHOOD / max(metres_per_row, 1)), 1)
    reach_cols = max(int(NEIGHBOURHOOD / max(metres_per_col, 1)), 1)

    faces = []
    for segment in analysis.segments:
        if segment.phase is not Phase.THERMAL:
            continue
        when = flight.time[segment.start].astype("datetime64[s]").astype(object)
        # The trigger is where the climb started, not its centre: by the middle of a
        # thermal the glider has drifted, sometimes over quite different ground.
        lat = float(flight.lat[segment.start])
        lon = float(flight.lon[segment.start])
        where = sun_module.position(when.replace(tzinfo=dt.timezone.utc), lat, lon)
        if where.elevation < MIN_ELEVATION:
            continue
        lit = lit_grid(slope, aspect, where.azimuth, where.elevation)
        row, col = _cell(terrain, lat, lon)
        patch = lit[
            max(row - reach_rows, 0):row + reach_rows + 1,
            max(col - reach_cols, 0):col + reach_cols + 1,
        ]
        cell_slope = float(slope[row, col])
        faces.append(Face(
            index=segment.start,
            minute=when.hour * 60 + when.minute,
            slope=round(cell_slope, 1),
            aspect=round(float(aspect[row, col])) if cell_slope >= MIN_SLOPE else None,
            lit=round(float(lit[row, col]), 3),
            neighbourhood=round(float(patch.mean()), 3) if patch.size else 0.0,
            elevation=round(where.elevation, 1),
        ))

    result = Insolation(faces)
    if wind is not None and faces:
        # A slope faces the wind when its aspect is within a quadrant of where the wind
        # is coming from. Ridge lift is a candidate explanation for the "rising,
        # uncounted" time the `other` decomposition uncovered, and this is the cheapest
        # possible test of it.
        facing = [
            f for f in faces
            if f.aspect is not None
            and abs(((f.aspect - wind.direction + 180) % 360) - 180) <= 45
        ]
        withaspect = [f for f in faces if f.aspect is not None]
        if withaspect:
            result.windward = round(len(facing) / len(withaspect), 2)
            result.wind_from = round(wind.direction)
    return result

"""A basemap image for the 3D view, stitched and embedded at build time.

The point is orientation: a hillshade tells you the shape of the ground but not that
the ridge you crossed is above Chýnov. OpenStreetMap raster tiles carry the place
names, so a handful of them are fetched once, stitched, and embedded as a data URI —
which is the only way a page under a strict content-security policy can show a map.

Tiles are cached, requested with a real User-Agent, and deliberately few (a couple of
dozen at most per flight) to stay a polite consumer of a donated service. Attribution
is not optional: every report that uses this credits OpenStreetMap contributors.
"""

from __future__ import annotations

import base64
import io
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
CACHE = Path.home() / ".cache" / "parainsights" / "osm"
TILE_SIZE = 256
MAX_TILES = 24
TIMEOUT = 30
USER_AGENT = "parainsights-tracklog-viewer/0.1 flight-analysis (contact: local user)"


@dataclass
class Basemap:
    """A stitched raster image and the exact geographic box it covers."""

    west: float
    east: float
    south: float
    north: float
    data_uri: str
    width: int
    height: int
    zoom: int

    def to_dict(self) -> dict:
        return {
            "west": round(self.west, 6),
            "east": round(self.east, 6),
            "south": round(self.south, 6),
            "north": round(self.north, 6),
            "uri": self.data_uri,
            "zoom": self.zoom,
        }


def _tile_x(lon: float, zoom: int) -> float:
    return (lon + 180.0) / 360.0 * 2**zoom


def _tile_y(lat: float, zoom: int) -> float:
    radians = math.radians(lat)
    return (1 - math.log(math.tan(radians) + 1 / math.cos(radians)) / math.pi) / 2 * 2**zoom


def _lon_of(x: float, zoom: int) -> float:
    return x / 2**zoom * 360.0 - 180.0


def _lat_of(y: float, zoom: int) -> float:
    n = math.pi - 2 * math.pi * y / 2**zoom
    return math.degrees(math.atan(0.5 * (math.exp(n) - math.exp(-n))))


def _choose_zoom(west: float, east: float, south: float, north: float) -> int:
    for zoom in range(13, 5, -1):
        wide = int(_tile_x(east, zoom)) - int(_tile_x(west, zoom)) + 1
        tall = int(_tile_y(south, zoom)) - int(_tile_y(north, zoom)) + 1
        if wide * tall <= MAX_TILES:
            return zoom
    return 6


def _fetch_tile(zoom: int, x: int, y: int) -> bytes | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{zoom}-{x}-{y}.png"
    if cached.exists():
        return cached.read_bytes()
    request = urllib.request.Request(
        TILE_URL.format(z=zoom, x=x, y=y), headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = response.read()
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    cached.write_bytes(data)
    return data


def fetch(west: float, east: float, south: float, north: float, *,
          max_width: int = 2200, quality: int = 72) -> Basemap | None:
    """Stitch a basemap covering the box. Returns None if tiles or Pillow are missing."""
    try:
        from PIL import Image
    except ImportError:
        return None

    zoom = _choose_zoom(west, east, south, north)
    x0 = int(_tile_x(west, zoom))
    x1 = int(_tile_x(east, zoom))
    y0 = int(_tile_y(north, zoom))
    y1 = int(_tile_y(south, zoom))

    canvas = Image.new("RGB", ((x1 - x0 + 1) * TILE_SIZE, (y1 - y0 + 1) * TILE_SIZE), (238, 236, 231))
    fetched = 0
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            data = _fetch_tile(zoom, tx, ty)
            if not data:
                continue
            try:
                with Image.open(io.BytesIO(data)) as tile:
                    canvas.paste(tile.convert("RGB"), ((tx - x0) * TILE_SIZE, (ty - y0) * TILE_SIZE))
                fetched += 1
            except Exception:
                continue
    if not fetched:
        return None

    if canvas.width > max_width:
        scale = max_width / canvas.width
        canvas = canvas.resize(
            (max_width, max(int(canvas.height * scale), 1)), Image.LANCZOS
        )

    buffer = io.BytesIO()
    # JPEG, not PNG: a photograph-like raster of a map costs several times more as PNG,
    # and this image is embedded in the document.
    canvas.save(buffer, format="JPEG", quality=quality, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    return Basemap(
        # The stitched image spans whole tiles, so its box is larger than requested.
        west=_lon_of(x0, zoom),
        east=_lon_of(x1 + 1, zoom),
        south=_lat_of(y1 + 1, zoom),
        north=_lat_of(y0, zoom),
        data_uri=f"data:image/jpeg;base64,{encoded}",
        width=canvas.width,
        height=canvas.height,
        zoom=zoom,
    )


def for_terrain(terrain, **kwargs) -> Basemap | None:
    """A basemap covering exactly the terrain grid's box."""
    return fetch(terrain.west, terrain.east, terrain.south, terrain.north, **kwargs)

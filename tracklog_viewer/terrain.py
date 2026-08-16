"""Ground elevation under and around the flight, from DEM tiles.

Source is the AWS Open Data terrarium DEM — global, free, no API key. Tiles are
fetched once, cached, and turned into a coarse grid that gets embedded in the
report: that is what makes a 3D terrain view possible inside a page that is not
allowed to touch the network when it is opened.

Terrarium encodes elevation in the RGB channels of an ordinary PNG:

    metres = R * 256 + G + B / 256 - 32768
"""

import hashlib
import io
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
CACHE = Path.home() / ".cache" / "parainsights" / "dem"
TILE_SIZE = 256
MAX_TILES = 20
TIMEOUT = 30
USER_AGENT = "parainsights-tracklog-viewer/0.1 (+https://github.com/)"


@dataclass
class Terrain:
    """A regular lat/lon grid of ground elevations."""

    west: float
    east: float
    south: float
    north: float
    elevations: np.ndarray  # shape (rows, cols), metres, row 0 = north

    @property
    def rows(self) -> int:
        return self.elevations.shape[0]

    @property
    def cols(self) -> int:
        return self.elevations.shape[1]

    def at(self, lat, lon):
        """Bilinear ground elevation at (lat, lon). Scalars or arrays."""
        # Fractional grid coordinates; row 0 is the northern edge.
        gx = (np.asarray(lon) - self.west) / (self.east - self.west) * (self.cols - 1)
        gy = (self.north - np.asarray(lat)) / (self.north - self.south) * (self.rows - 1)
        gx = np.clip(gx, 0, self.cols - 1)
        gy = np.clip(gy, 0, self.rows - 1)
        x0 = np.floor(gx).astype(int)
        y0 = np.floor(gy).astype(int)
        x1 = np.minimum(x0 + 1, self.cols - 1)
        y1 = np.minimum(y0 + 1, self.rows - 1)
        fx = gx - x0
        fy = gy - y0
        top = self.elevations[y0, x0] * (1 - fx) + self.elevations[y0, x1] * fx
        bottom = self.elevations[y1, x0] * (1 - fx) + self.elevations[y1, x1] * fx
        return top * (1 - fy) + bottom * fy

    def to_dict(self, *, decimals: int = 0) -> dict:
        return {
            "west": round(self.west, 6),
            "east": round(self.east, 6),
            "south": round(self.south, 6),
            "north": round(self.north, 6),
            "rows": self.rows,
            "cols": self.cols,
            "min": int(np.floor(self.elevations.min())),
            "max": int(np.ceil(self.elevations.max())),
            # Flat list of ints: a nested array of floats triples the size for
            # precision nobody can see on a hillshade.
            "z": np.round(self.elevations, decimals).astype(int).ravel().tolist(),
        }


def _tile_indices(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Fractional slippy-map tile coordinates."""
    n = 2**zoom
    x = (lon + 180.0) / 360.0 * n
    radians = math.radians(lat)
    y = (1 - math.log(math.tan(radians) + 1 / math.cos(radians)) / math.pi) / 2 * n
    return x, y


def _choose_zoom(west: float, east: float, south: float, north: float) -> int:
    """Highest zoom whose tile count stays within budget.

    Detail is wasted if the grid is coarser than the tiles, and a long XC flight at
    z12 would be hundreds of tiles, so this trades resolution for a bounded fetch.
    """
    for zoom in range(12, 5, -1):
        x0, y0 = _tile_indices(north, west, zoom)
        x1, y1 = _tile_indices(south, east, zoom)
        tiles = (int(x1) - int(x0) + 1) * (int(y1) - int(y0) + 1)
        if tiles <= MAX_TILES:
            return zoom
    return 6


def _fetch_tile(zoom: int, x: int, y: int, *, problems: list | None = None
                ) -> np.ndarray | None:
    """One decoded tile as an elevation array, or None if unavailable.

    Every failure appends *why* to `problems`. A tile that does not arrive is not an
    error here — a mosaic survives a missing edge tile — but when none of them arrive
    the caller has to be able to say what went wrong, and "terrain unavailable" is not
    something anyone can act on. A deploy spent two runs saying exactly that.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{zoom}-{x}-{y}.png"
    if cached.exists():
        data = cached.read_bytes()
    else:
        url = TILE_URL.format(z=zoom, x=x, y=y)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                data = response.read()
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            # The class as well as the message: `URLError` wrapping an SSL failure and
            # `URLError` wrapping a refused connection read very differently, and the
            # message alone sometimes carries neither.
            _note(problems, f"{type(error).__name__}: {error}")
            return None
        cached.write_bytes(data)

    try:
        from PIL import Image
    except ImportError:
        _note(problems, "Pillow is not installed, so a PNG tile cannot be decoded")
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            pixels = np.asarray(image.convert("RGB"), dtype=np.float64)
    except Exception as error:                                          # noqa: BLE001
        _note(problems, f"a tile did not decode ({type(error).__name__}: {error})")
        return None
    return pixels[:, :, 0] * 256 + pixels[:, :, 1] + pixels[:, :, 2] / 256 - 32768


def _note(problems: list | None, reason: str) -> None:
    """Record a reason once. Twenty tiles failing the same way is one fact."""
    if problems is not None and reason not in problems:
        problems.append(reason)


def fetch(west: float, east: float, south: float, north: float, *,
          cols: int = 320, max_points: int = 26000, report=None) -> Terrain | None:
    """Build an elevation grid covering the box. Returns None if tiles are unreachable.

    `report` is called with one line when tiles are missing, and it is the whole reason
    this parameter exists: the failure used to be swallowed whole, so a publishing
    pipeline could say *that* the terrain was unavailable and never *why*. Two green
    deploys published a page without its 3D view before anyone could tell whether the
    tile host was blocked, slow or simply not answering.

    It stays a callback rather than a raise: a missing DEM is not an error anywhere in
    this repository — the airspace map falls back to a flat one, the planner declines to
    draw, an uploaded track gets a flat plane — and turning it into an exception would
    change all three. What was missing was the sentence, not the failure.
    """
    zoom = _choose_zoom(west, east, south, north)
    x0, y0 = _tile_indices(north, west, zoom)
    x1, y1 = _tile_indices(south, east, zoom)
    tile_x0, tile_x1 = int(math.floor(x0)), int(math.floor(x1))
    tile_y0, tile_y1 = int(math.floor(y0)), int(math.floor(y1))

    mosaic = np.full(
        ((tile_y1 - tile_y0 + 1) * TILE_SIZE, (tile_x1 - tile_x0 + 1) * TILE_SIZE),
        np.nan,
    )
    fetched = 0
    wanted = (tile_y1 - tile_y0 + 1) * (tile_x1 - tile_x0 + 1)
    problems: list[str] = []
    for ty in range(tile_y0, tile_y1 + 1):
        for tx in range(tile_x0, tile_x1 + 1):
            tile = _fetch_tile(zoom, tx, ty, problems=problems)
            if tile is None:
                continue
            fetched += 1
            row = (ty - tile_y0) * TILE_SIZE
            col = (tx - tile_x0) * TILE_SIZE
            mosaic[row:row + TILE_SIZE, col:col + TILE_SIZE] = tile
    if report is not None and fetched < wanted:
        why = "; ".join(problems[:2]) if problems else "no reason recorded"
        report(f"terrain: {fetched} of {wanted} tiles at zoom {zoom} from "
               f"{urllib.parse.urlsplit(TILE_URL).netloc} — {why}")
    if not fetched or np.isnan(mosaic).all():
        return None
    # A missing tile at the edge should not punch a hole in the mesh.
    mosaic = np.nan_to_num(mosaic, nan=float(np.nanmin(mosaic)))

    # Aspect-aware grid: keep cells roughly square on the ground.
    width_m = (east - west) * 111320 * math.cos(math.radians((north + south) / 2))
    height_m = (north - south) * 110540
    rows = max(int(round(cols * height_m / max(width_m, 1))), 8)
    rows = min(rows, cols)
    # The grid is embedded in the report, so it pays a size cost per node. A roughly
    # square box would otherwise cost 200×200 = 40 000 nodes; scale both axes back to
    # stay inside a budget the document can carry.
    if rows * cols > max_points:
        shrink = math.sqrt(max_points / (rows * cols))
        cols = max(int(cols * shrink), 24)
        rows = max(int(rows * shrink), 8)

    lons = np.linspace(west, east, cols)
    lats = np.linspace(north, south, rows)
    # Pixel coordinates within the mosaic for every grid node.
    px = np.array([(_tile_indices(lats[0], lon, zoom)[0] - tile_x0) * TILE_SIZE for lon in lons])
    py = np.array([(_tile_indices(lat, lons[0], zoom)[1] - tile_y0) * TILE_SIZE for lat in lats])
    px = np.clip(px, 0, mosaic.shape[1] - 1).astype(int)
    py = np.clip(py, 0, mosaic.shape[0] - 1).astype(int)

    elevations = mosaic[np.ix_(py, px)]
    return Terrain(west=west, east=east, south=south, north=north, elevations=elevations)


def for_flight(analysis, *, margin: float = 0.35, cols: int = 320,
               max_points: int = 26000, report=None) -> Terrain | None:
    """Terrain covering the flight's bounding box, with a margin for context."""
    flight = analysis.flight
    west, east = float(flight.lon.min()), float(flight.lon.max())
    south, north = float(flight.lat.min()), float(flight.lat.max())
    # Pad generously for context. The node budget is unchanged, so a wider box costs
    # nothing to draw — each cell simply covers more ground.
    pad_x = max((east - west) * margin, 0.06)
    pad_y = max((north - south) * margin, 0.06)
    return fetch(
        west - pad_x, east + pad_x, south - pad_y, north + pad_y,
        cols=cols, max_points=max_points, report=report,
    )


def clearance(terrain: Terrain, analysis) -> np.ndarray:
    """Height above terrain for every fix, in metres.

    Uses GPS altitude: the DEM is geometric, and pressure altitude is offset by the
    day's QNH, which would show up as a constant error in ground clearance.
    """
    flight = analysis.flight
    altitude = flight.alt_gps if np.any(flight.alt_gps) else analysis.series.alt
    return altitude - terrain.at(flight.lat, flight.lon)

"""The airspace map as a 3D scene: terrain, imagery, and rings at their own floors.

Why this imports from `tracklog_viewer`. The repository's rule is that the two tools
share a page and not code, and `airspaces/geo.py` exists beside `tracklog_viewer/geo.py`
rather than importing it. That rule is about *geodesy and analysis*, where the two tools
genuinely disagree — the viewer works on the FAI sphere because a scored distance is
measured on one, and airspace is published against WGS84.

`view3d` is not that. It is a map widget: it takes a payload of a terrain grid, some
imagery and a list of things to draw, and it knows nothing about flights — a scene with
no track in it renders perfectly well. The alternatives were to copy 120 KB of JavaScript
or to move it to a third package, and the second is the right end state; what stops it
today is that `view3d.data()` and `cursor_track()` in the same module *are* flight code,
so the split is a refactor rather than a move. Until then this is one import of a widget,
made lazily so `airspaces` still builds its OpenAir file with the viewer absent.

The elevations and the imagery are fetched, so building this needs a network; the page it
produces does not, beyond the tiles it is explicitly told to fetch at view time.
"""

from __future__ import annotations

from . import basemap as border
from .render_html import CLASSES, classify, floor_metres

# One grid for the whole country. 320 columns over 6.7 degrees of longitude is about
# 1.4 km a node, which is coarse for a mountain and about right for a backdrop that
# exists to say "this zone sits over that ridge". The node budget is the report's, since
# this grid is embedded the same way.
COLUMNS = 320
MAX_NODES = 26000

# Rings are simplified before they ship: at the zoom this map opens on, a 5 500 m circle
# is 40 pixels across and its 72 published vertices are 36 of them wasted.
RING_TOLERANCE_DEG = 0.0015    # about 110 m


def bounds(airspaces, margin: float = 0.12):
    """The box to fetch terrain and imagery for: everything drawn, plus a margin."""
    lats = [lat for a in airspaces for lat, _ in a.points] or [lat for lat, _ in border.BORDER]
    lons = [lon for a in airspaces for _, lon in a.points] or [lon for _, lon in border.BORDER]
    lats += [lat for lat, _ in border.BORDER]
    lons += [lon for _, lon in border.BORDER]
    return (min(lons) - margin, max(lons) + margin,
            min(lats) - margin, max(lats) + margin)


def _thin(points, tolerance: float):
    """Drop vertices that say nothing at map scale. A cheap perpendicular-distance walk
    rather than Douglas-Peucker: these are convex-ish rings, the tolerance is generous,
    and `geo.simplify` works in metres on a local plane that this does not have."""
    if len(points) < 8:
        return list(points)
    kept = [points[0]]
    for point in points[1:-1]:
        last = kept[-1]
        if abs(point[0] - last[0]) > tolerance or abs(point[1] - last[1]) > tolerance:
            kept.append(point)
    kept.append(points[-1])
    return kept if len(kept) >= 3 else list(points)


def _is_ground(airspace) -> bool:
    raw = (airspace.floor or "").upper().replace(" ", "")
    return not raw or raw.startswith("GND") or raw.startswith("SFC")


def rings(airspaces) -> list[dict]:
    """Every airspace as a ring the view can draw, ordered back to front.

    Biggest first, exactly as the SVG map orders them and for the same reason: paint
    order is hit order, so the smallest thing under the pointer is the one a reader gets.
    """
    ranked = sorted(airspaces, key=lambda a: -_area(a))
    out = []
    for airspace in ranked:
        if len(airspace.points) < 3:
            continue
        points = _thin(airspace.points, RING_TOLERANCE_DEG)
        label = airspace.name
        if airspace.floor or airspace.ceiling:
            label += f"  ({airspace.floor} – {airspace.ceiling})"
        out.append({
            "k": classify(airspace),
            "n": label,
            # Metres AMSL, and the number the floor filter compares against, so the
            # slider and the drawing height can never disagree.
            "f": round(floor_metres(airspace)),
            "g": _is_ground(airspace),
            "lon": [round(lon, 4) for _, lon in points],
            "lat": [round(lat, 4) for lat, _ in points],
        })
    return out


def _area(airspace) -> float:
    points = airspace.points
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i in range(len(points)):
        y1, x1 = points[i]
        y2, x2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def fetch(airspaces, *, online: bool, report=print):
    """Terrain, imagery and rings for these airspaces — or None if the ground could not
    be fetched, which is the flat map's cue to take over.

    Both callers want exactly this, so it lives here rather than in either `cli.py`;
    `tracklog_viewer/cli.py` reaching into `airspaces.cli` for a private helper was how
    it started and is not a seam anyone should have to find.
    """
    from tracklog_viewer import basemap as viewer_basemap
    from tracklog_viewer import terrain as viewer_terrain

    west, east, south, north = bounds(airspaces)
    ground = viewer_terrain.fetch(west, east, south, north,
                                  cols=COLUMNS, max_points=MAX_NODES)
    if ground is None:
        return None
    # Online, the page stitches its own imagery at view time and nothing is baked in.
    # Offline it carries one embedded stitch, which over a whole country is coarse — about
    # 300 m a pixel — and is a backdrop rather than something to read.
    images = {} if online else viewer_basemap.for_view(ground, max_tiles=90, quality=52)
    if report:
        report(f"terrain {ground.cols}x{ground.rows} nodes"
               + (", imagery fetched at view time" if online
                  else f", {len(images)} basemap styles embedded"))
    return build(airspaces, terrain=ground, basemaps=images, tiles=online)


def build(airspaces, *, terrain=None, basemaps=None, tiles: bool = True) -> dict:
    """A `view3d` payload for these airspaces.

    `terrain` and `basemaps` are passed in rather than fetched here so that a caller
    without a network — every test in this suite — can build the payload from fixtures,
    and so the CLI decides the fetch budget.
    """
    from tracklog_viewer import view3d

    payload = {
        "terrain": terrain.to_dict() if terrain is not None else None,
        "basemaps": {name: image.to_dict() for name, image in (basemaps or {}).items()},
        "tiles": (tiles and {
            name: source for name, source in view3d.TILE_SOURCES.items()
            if name not in (basemaps or {})
        }) or None,
        "airspaces": rings(airspaces),
        "airspaceColours": {key: colour for key, _, colour in CLASSES},
        # Nearly flat and square to north. The flight view's three-quarter camera is the
        # angle a pilot recognises over one valley; over 500 km of country it turns the
        # far half of the map into a sliver, and there is no relief at this scale for the
        # obliqueness to be showing off anyway. Tilting is a gesture away.
        "view": {"yaw": 0.0, "pitch": 1.32},
    }
    return payload

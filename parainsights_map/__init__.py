"""The 3D map every page on the site draws with.

A map widget, not flight code: hand it a terrain grid (or the box to fetch one for), tile
sources, and whatever to draw — a track, climbs, airspace rings, a planned route — and it
never asks what a flight is. The flight viewer, the Planner and the airspace map all use
it, which is why it is a package of its own rather than a corner of one of them.

- `view3d`      the canvas view: camera, gestures, tiles, the 2D fallback
- `view3d_gl`   the WebGL heightfield, a backend for `view3d`
- `map3d`       the merged view: MapLibre's engine under the canvas view's controls
- `render_map`  the plain MapLibre view, the renderer switch and the shared loader
- `terrain`     DEM grids from the AWS terrarium tiles, fetched at build time or described
                for the page to fetch (`Terrain.to_remote`, `remote`)
"""

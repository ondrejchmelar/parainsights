"""The 3D map every page on the site draws with.

A map widget, not flight code: hand it a terrain grid (or the box to fetch one for), tile
sources, and whatever to draw — a track, climbs, airspace rings, a planned route — and it
never asks what a flight is. The flight viewer, the Planner and the airspace map all use
it, which is why it is a package of its own rather than a corner of one of them.

- `map3d`       the map: MapLibre and deck.gl, and its controls (script in `js/map3d.js`)
- `view3d`      the panel the map mounts in, and the scene, ground grid and airspace it
                draws from; the handle the charts drive it through (`js/view3d.js`)
- `render_map`  loading MapLibre and deck.gl, opening the map, reviving a lost context
- `terrain`     DEM grids from the AWS terrarium tiles, fetched at build time or described
                for the page to fetch (`Terrain.to_remote`, `remote`)
"""

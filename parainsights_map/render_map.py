"""Loading MapLibre and deck.gl, and opening the 3D map (`map3d`) in a panel.

Every 3D panel is a `.renderer-host` holding a `view3d.panel`; once the panel's scene is
ready (`initView3dWhenReady`), `window.__openMap(host)` mounts the map over it. MapLibre
and deck.gl are loaded from unpkg once per page, on the first map opened. Nothing needs an
API key: the terrain is the AWS Open Data terrarium DEM and the imagery is the panel's
own tile sources.

There used to be three renderers behind a switch here — the canvas (`view3d`), plain
MapLibre and the merged view. The merged view became the default and then the only one
(October 2026); the other two are in git history. Without a network there is no map,
and the panel says so: the canvas was the offline fallback, and nobody reads these pages
offline.
"""

from pathlib import Path



MAPLIBRE = "https://unpkg.com/maplibre-gl@4.7.1/dist"
DECK = "https://unpkg.com/deck.gl@9.0.35/dist.min.js"
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


STYLE = """
.maplibre-view { position: absolute; inset: 0; z-index: 30; background: var(--panel); }
.maplibre-view .ml-map { position: absolute; inset: 0; }
.maplibre-view .maplibregl-ctrl-bottom-right { bottom: 48px; }
.maplibre-view .maplibregl-ctrl-bottom-left { bottom: 48px; }
"""


SCRIPT = (
    (Path(__file__).parent / "js/render_map.js").read_text(encoding="utf-8")
    .replace("__MAPLIBRE__", MAPLIBRE)
    .replace("__DECK__", DECK)
    .replace("__TERRARIUM__", TERRARIUM)
)

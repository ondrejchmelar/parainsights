"""The 3D map's panel and the scene under it: the data, not the drawing.

A map widget, not flight code: a payload — a terrain grid (or the box to fetch one for),
tile sources, and optionally a track, climbs, airspace rings — read in the page. A
flight's payload is written by `js/scene.js`; the airspace map's by `airspaces.scene`.

The drawing is `map3d` (MapLibre and deck.gl). This module was the canvas renderer, which
drew the same scene on a 2D canvas or WebGL heightfield of its own; it was retired in
October 2026 with the plain MapLibre view beside it (both are in git history), and what
is left is what the map is built from: the panel the map mounts in, the scene decoded
from it, the ground grid fetched for it, the airspace loaded for it, and a handle the
charts drive the cursor through.
"""

import json
from pathlib import Path


TILE_SOURCES = {
    "satellite": {
        "label": "Satellite",
        "layers": [
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery"
            "/MapServer/tile/{z}/{y}/{x}",
            # The place names of `World_Boundaries_and_Places` (white on a dark halo)
            # without its region and district borders; only the national one remains.
            # Canvas/World_Dark_Gray_Reference has no lines at all, but its names are
            # faint grey with no halo, made for a dark canvas rather than a photograph.
            "https://server.arcgisonline.com/ArcGIS/rest/services/Reference"
            "/World_Boundaries_and_Places_Alternate/MapServer/tile/{z}/{y}/{x}",
        ],
        "attribution": "Imagery © Esri, Maxar, Earthstar Geographics",
        "max_zoom": 18,
        # Esri's levels 12 and up are one mosaic; 11 and below are an older, darker one
        # (over the same Dolomites ground: blue channel 26 against 59). A map that crosses
        # between them jumps colour on every zoom, so the merged view never shows the
        # imagery below this level — it builds those tiles from this level's (`map3d`).
        "consistent_from": 12,
        # The label layer's last level: past it Esri answers empty tiles, and every name
        # vanished as the reader zoomed in. The map draws OpenFreeMap's place names as
        # text instead (`map3d`).
        "label_max_zoom": 12,
    },
    "map": {
        "label": "Map",
        "layers": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        "attribution": "© OpenStreetMap contributors",
        "max_zoom": 19,
    },
}



def panel(payload: dict, uid: str, *, verticals: tuple = (1, 2, 4),
          vertical: float | None = None) -> str:
    """The box the map mounts in, and the embedded data.

    `verticals` is the exaggeration the map offers and `vertical` is where it starts,
    which are two questions: the buttons read best in increasing order whichever one is
    pressed. It is the page's choice because the right answer depends on what the scene
    *is*. A flight is a few kilometres of air over tens of kilometres of ground and reads
    honestly at true scale — the default. A map of a whole country is not: at national
    scale a 300 m traffic circuit projects to **0.3 px**, so every box on it is two
    coincident rings. See `airspaces/cli.py`, which asks for more.
    """
    start = verticals[0] if vertical is None else vertical
    levels = ",".join(str(level) for level in verticals)
    return f"""
    <div class="panel view3d-panel" data-verticals="{levels}" data-vertical="{start}">
      <div class="view3d" id="view3d-{uid}"></div>
      <script type="application/json" class="view3d-data">{json.dumps(payload)}</script>
    </div>"""


STYLE = """
/* Full-bleed: the map is the one thing worth more than the page's reading width. The
   clip has to go on the *root* — html is the scroll container, so clipping body alone
   leaves the page scrolling sideways by the scrollbar's width, which 100vw includes.
   `clip` rather than `hidden` so no new scroll container is created. */
:root, body { overflow-x: clip; }
/* --scrollbar is measured in JS. 100vw includes the scrollbar, so a panel that wide
   hangs off the layout viewport and anything anchored to its right edge is clipped. */
.view3d-panel { position: relative; padding: 0; overflow: hidden;
  --page: calc(100vw - var(--scrollbar, 0px));
  width: var(--page); margin-left: calc(50% - var(--page) / 2);
  border-left: 0; border-right: 0; border-radius: 0; }
/* The box the map fills: its proportions are the panel's. */
.view3d { display: block; width: 100%; aspect-ratio: 21 / 9;
  background: linear-gradient(180deg, var(--panel-2) 0%, var(--panel) 62%); }
@media (max-width: 900px) { .view3d { aspect-ratio: 4 / 3; } }
/* A phone in portrait: taller than wide, so the rail, the bar and the track all fit. */
@media (max-width: 640px) { .view3d { aspect-ratio: 3 / 4; } }
/* Real full screen. The UA stylesheet positions the element over the screen; this undoes
   the full-bleed sizing. 100%/100% and not 100vw/100vh: the viewport units are the
   *page's* viewport, and this element's containing block is the screen. */
.view3d-panel:fullscreen { width: 100%; height: 100%; margin: 0; border: 0; }
.view3d-panel:fullscreen .view3d { width: 100%; height: 100%; aspect-ratio: auto; }
/* The backdrop is black by default and flashes against a light report. */
.view3d-panel::backdrop { background: var(--panel); }
/* The fallback where real full screen is refused (an iframe without the permission). */
.view3d-panel.is-maximised { position: fixed; inset: 0; z-index: 60; width: auto;
  height: auto; margin: 0; }
.view3d-panel.is-maximised .view3d { width: 100%; height: 100%; aspect-ratio: auto; }
/* The airspace label. `pointer-events: none` or it would sit under the cursor, take the
   next pointermove for itself and flicker the label it is showing. */
.view3d-asp { position: absolute; pointer-events: none; z-index: 5; max-width: 62%;
  background: var(--ink); color: var(--paper); font-size: 15px; line-height: 1.4;
  padding: 7px 11px; border-radius: 10px; }
/* The map's own controls (`map3d`), in the site's language (the redesign, October 2026):
   10 px corners, sentence case, the page's type — translucent like the panels that float
   over a map, so the ground shows through and the buttons still read on snow and forest.
   A segmented group carries state, a bare button is a one-shot action. The bar runs along
   the bottom; the labels sit top left; zoom, tilt and straight-down in a rail on the right. */
.view3d-panel { --mh: 36px; }
.view3d-controls, .m3-corner, .m3-rail { display: flex; gap: 6px; align-items: center; }
.view3d-controls { position: absolute; right: 10px; bottom: 10px; left: 10px; flex-wrap: wrap;
  justify-content: flex-end; z-index: 3; }
.m3-corner { position: absolute; left: 10px; top: 10px; z-index: 3; flex-direction: column; align-items: flex-start; gap: 8px; }
.m3-rail { position: absolute; right: 10px; top: 10px; z-index: 3; flex-direction: column; gap: 8px; }
.m3-rose:not([hidden]) ~ .m3-rail { top: 76px; }
.m3-corner[hidden], .m3-rail[hidden] { display: none; }
.view3d-seg { display: flex; gap: 0; border-radius: 10px; box-shadow: var(--float-shadow); }
.m3-rail .view3d-seg { flex-direction: column; }
.view3d-controls button, .m3-corner button, .m3-rail button, .m3-replay button {
  position: relative; height: var(--mh); min-width: var(--mh); padding: 0 12px; margin: 0; box-sizing: border-box;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  font: 600 15px/1 "Noto Sans", ui-sans-serif, system-ui, sans-serif; text-transform: none; letter-spacing: 0;
  color: var(--ink); background: var(--float); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  border: 1px solid var(--float-edge); border-radius: 10px; box-shadow: var(--float-shadow); cursor: pointer; }
/* 36–38 px to see, 44 px to hit. */
.view3d-controls button::after, .m3-corner button::after, .m3-rail button::after, .m3-replay button::after {
  content: ""; position: absolute; inset: -4px; }
.view3d-controls button:hover, .m3-corner button:hover, .m3-rail button:hover, .m3-replay button:hover {
  background: var(--float-2); }
.view3d-controls button:focus-visible, .m3-corner button:focus-visible, .m3-rail button:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px; z-index: 2; }
.view3d-controls .m3-icon, .m3-rail button { width: var(--mh); padding: 0; }
.view3d-controls button svg, .m3-corner button svg, .m3-rail button svg, .m3-replay button svg { display: block; flex: none; }
.view3d-seg button { border-radius: 0; box-shadow: none; }
.view3d-seg button + button { margin-left: -1px; }
.view3d-seg button:first-child { border-radius: 10px 0 0 10px; }
.view3d-seg button:last-child { border-radius: 0 10px 10px 0; }
.m3-rail .view3d-seg button + button { margin-left: 0; margin-top: -1px; }
.m3-rail .view3d-seg button:first-child { border-radius: 10px 10px 0 0; }
.m3-rail .view3d-seg button:last-child { border-radius: 0 0 10px 10px; }
.view3d-seg button:only-child { border-radius: 10px; }
/* Selected: filled with ink, as every selected control on the site is. */
.view3d-controls button.is-on, .m3-corner button.is-on, .m3-rail button.is-on, .m3-replay button.is-on,
.view3d-controls button[aria-pressed="true"], .m3-corner button[aria-pressed="true"], .m3-rail button[aria-pressed="true"] {
  background: var(--ink); border-color: var(--ink); color: var(--paper); z-index: 1; }
.view3d-controls button:disabled { opacity: 0.5; cursor: default; }
html[data-help="off"] .m3-help { display: none; }
@media (max-width: 640px) {
  .view3d-panel { --mh: 38px; }
  .view3d-controls { gap: 4px; flex-wrap: nowrap; }
  .view3d-controls button { padding: 0 8px; font-size: 14px; }
  .view3d-controls .m3-icon { padding: 0; width: 34px; min-width: 34px; }
  .view3d-reset { display: none; }
  .m3-rose:not([hidden]) ~ .m3-rail { top: 70px; }
}
/* The help list, over the controls: the one overlay a reader opens deliberately. The
   panel clips its overflow, so the list is capped to the box and scrolls. */
.view3d-keys { position: absolute; z-index: 4; left: 50%; top: 50%; transform: translate(-50%, -50%);
  background: var(--panel); border: 1px solid var(--edge); border-radius: 14px; padding: 16px 20px;
  font-size: 15px; max-height: calc(100% - 20px); max-width: calc(100% - 20px); overflow: auto;
  box-sizing: border-box; cursor: pointer; box-shadow: var(--float-shadow); }
.view3d-keys dl { margin: 0; display: grid; grid-template-columns: auto auto; gap: 4px 16px; }
.view3d-keys-head { margin: 0 0 6px; font-size: 15px; font-weight: 600; color: var(--ink); }
.view3d-keys dl + .view3d-keys-head { margin-top: 12px; }
.view3d-keys-foot { margin: 12px 0 0; font-size: 15px; color: var(--ink-2); }
/* `shift + <- ->` is one key combination; wrapped, it read as two bindings. */
.view3d-keys dt { color: var(--ink); font-family: ui-monospace, monospace; white-space: nowrap; }
.view3d-keys dd { margin: 0; color: var(--ink-2); }
.view3d-keys[hidden] { display: none; }
"""


SCRIPT = (Path(__file__).parent / "js/view3d.js").read_text(encoding="utf-8")

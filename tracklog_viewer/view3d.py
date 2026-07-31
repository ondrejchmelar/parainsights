"""An interactive 3D view that survives a content-security policy.

`render_map.py` gives the better 3D map — real basemap, real tiles, deck.gl — but it
needs the network at view time, so it cannot be embedded in a published page. This
renders the same idea with nothing but a canvas and about a hundred lines of
JavaScript: the DEM is fetched once at build time and travels inside the document.

The heightfield is drawn back-to-front by walking the grid from the farthest corner,
which is exact for a regular grid seen from outside it — no depth sort, no z-buffer.
"""

import datetime as dt
import json

import numpy as np

from . import sun
from .analysis import Analysis, Phase
from .charts import decimate
from .render_map import RAMP_RGB, climb_rgb

TRACK_TOLERANCE = 4.0  # metres of horizontal detail kept in the 3D track


def _colour_index(value: float) -> int:
    """Index into the shared climb ramp.

    An index costs three characters in the payload where an [r,g,b] triple costs
    fifteen, and a long flight has thousands of points.
    """
    for index, (threshold, _) in enumerate(RAMP_RGB):
        if value < threshold:
            return index
    return len(RAMP_RGB) - 1


TILE_SOURCES = {
    "satellite": {
        "label": "Satellite",
        "layers": [
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery"
            "/MapServer/tile/{z}/{y}/{x}",
            "https://server.arcgisonline.com/ArcGIS/rest/services/Reference"
            "/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        ],
        "attribution": "Imagery © Esri, Maxar, Earthstar Geographics",
        "max_zoom": 18,
    },
    "map": {
        "label": "Map",
        "layers": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        "attribution": "© OpenStreetMap contributors",
        "max_zoom": 19,
    },
}


def data(analysis: Analysis, terrain, *, tolerance: float | None = None,
         basemaps: dict | None = None, tiles: bool = True) -> dict:
    """Terrain grid, track and climbs, in the compact form the renderer wants."""
    flight = analysis.flight
    series = analysis.series
    altitude = flight.alt_gps if np.any(flight.alt_gps) else series.alt

    tolerance = TRACK_TOLERANCE if tolerance is None else tolerance
    keep = np.union1d(
        decimate(series.x, series.y, tolerance),
        decimate(series.t, series.alt, tolerance * 0.75),
    )
    track = {
        # 4 decimals is ~11 m — below what a pixel represents at these zooms.
        "lon": [round(float(flight.lon[i]), 4) for i in keep],
        "lat": [round(float(flight.lat[i]), 4) for i in keep],
        "alt": [int(altitude[i]) for i in keep],
        "c": [_colour_index(float(series.climb[i])) for i in keep],
    }

    climbs = []
    number = 0
    for segment in analysis.segments:
        if segment.phase not in (Phase.THERMAL, Phase.TOW):
            continue
        middle = (segment.start + segment.stop) // 2
        if segment.phase is Phase.TOW:
            label = "T"
        else:
            number += 1
            label = str(number)
        climbs.append(
            {
                "label": label,
                "lon": round(float(flight.lon[middle]), 5),
                "lat": round(float(flight.lat[middle]), 5),
                "alt": int(altitude[middle]),
                "tow": segment.phase is Phase.TOW,
            }
        )

    # Cursor positions for the shared hover, at the same sample indices the charts use.
    return {
        "terrain": terrain.to_dict(),
        "trackTop": int(max(track["alt"])) if track["alt"] else 0,
        "track": track,
        "climbs": climbs,
        "palette": [list(colour) for _, colour in RAMP_RGB],
        # Imagery baked into the document, keyed by the style the button names. A
        # published artifact cannot fetch anything, so a style that is not in here has no
        # way to appear there — which is why both are embedded by default and the tile
        # templates below are only an upgrade for a page that does have a network.
        "basemaps": {name: image.to_dict() for name, image in (basemaps or {}).items()},
        "tiles": (tiles and {
            name: source for name, source in TILE_SOURCES.items()
            if name not in (basemaps or {})
        }) or None,
        "landing": {
            "lon": round(float(flight.lon[-1]), 5),
            "lat": round(float(flight.lat[-1]), 5),
            "alt": int(altitude[-1]),
        },
        "sun": _sun(analysis),
        # The flight's wind, for the arrow on the view. `direction` is where it blows
        # *from*, the way every pilot and every forecast states it; the arrow has to
        # point the other way, and that inversion is done once, in the drawing code.
        "wind": ({
            "kmh": round(analysis.wind.kmh, 1),
            "from": round(analysis.wind.direction, 1),
            "cardinal": analysis.wind.cardinal,
        } if analysis.wind else None),
    }


def _sun(analysis: Analysis) -> dict:
    """The day's sun over the middle of the flight, tabulated for the slider.

    A table rather than the algorithm: porting `sun.py` into JavaScript would be a second
    place for it to be wrong, and 144 pairs of numbers cannot drift. The browser
    interpolates between samples, which is why `day_track` unwraps the azimuth.

    Times are handled as UTC minutes throughout and turned into clock time only for the
    label, using the offset the flight's own timezone had *that day* — one flight, one
    place, one date, so a single offset is exact and a timezone database is not needed in
    the page.
    """
    flight = analysis.flight
    lat = float(np.median(flight.lat))
    lon = float(np.median(flight.lon))
    launch = flight.local_time(0)
    day = launch.astimezone(dt.timezone.utc).date() if launch.tzinfo else launch.date()

    def utc_minutes(index: int) -> int:
        when = flight.time[index].astype("datetime64[s]").astype(object)
        return when.hour * 60 + when.minute

    offset = launch.utcoffset() or dt.timedelta(0)
    rise, set_ = sun.rise_and_set(day, lat, lon)
    start, finish = utc_minutes(0), utc_minutes(len(flight.time) - 1)
    return {
        "track": sun.day_track(day, lat, lon),
        "date": day.isoformat(),
        # Minutes to add to a UTC minute to read it as the pilot's own clock.
        "offset": int(offset.total_seconds() // 60),
        "launch": start,
        "landing": finish,
        # Mid-flight is what the view opens on: the light the day was actually worked in,
        # rather than an hour nobody flew.
        "at": (start + finish) // 2 if finish >= start else start,
        "rise": round(rise) if rise is not None else None,
        "set": round(set_) if set_ is not None else None,
    }


def cursor_track(analysis: Analysis, sample) -> dict:
    """Positions for the hover cursor, aligned with the chart sample indices.

    `min` is the UTC minute of each sample, which is what lets the hover move the sun:
    the reader points at a moment in the flight and the terrain is lit as it was then.
    """
    flight = analysis.flight
    altitude = flight.alt_gps if np.any(flight.alt_gps) else analysis.series.alt

    def minute(index: int) -> int:
        when = flight.time[index].astype("datetime64[s]").astype(object)
        return when.hour * 60 + when.minute

    return {
        "lon": [round(float(flight.lon[i]), 5) for i in sample],
        "lat": [round(float(flight.lat[i]), 5) for i in sample],
        "alt": [int(altitude[i]) for i in sample],
        "min": [minute(i) for i in sample],
    }


GLOBE_ICON = (
    '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true" focusable="false">'
    '<circle cx="8" cy="8" r="6.6" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    '<ellipse cx="8" cy="8" rx="2.9" ry="6.6" fill="none" stroke="currentColor" '
    'stroke-width="1.1"/>'
    '<path d="M1.6 6.1h12.8M1.6 9.9h12.8" stroke="currentColor" stroke-width="1.1" '
    'fill="none"/></svg>'
)
EXPAND_ICON = (
    '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" focusable="false">'
    '<path d="M1.5 5.5v-4h4M14.5 10.5v4h-4M14.5 5.5v-4h-4M1.5 10.5v4h4" fill="none" '
    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
)


def panel(payload: dict, uid: str, *, kmz_uri: str | None = None,
          kmz_name: str = "flight.kmz") -> str:
    """The canvas, its controls, and the embedded data."""
    earth = ""
    if kmz_uri:
        # A download link rather than a button: the KMZ travels inside the report, so
        # the file is available with no server and no second request.
        earth = (
            f'<a class="view3d-earth" href="{kmz_uri}" download="{kmz_name}" '
            f'title="Download the KMZ and open it in Google Earth">'
            f'{GLOBE_ICON}<span>Open in Earth</span></a>'
        )
    # The button names what is on screen, not what comes next: cycling through several
    # styles, a fixed "Map" label says nothing about where you are.
    available = {**(payload.get("tiles") or {}), **(payload.get("basemaps") or {})}
    initial_style = "satellite" if "satellite" in available else next(iter(available), "")
    basemap_label = TILE_SOURCES.get(initial_style, {}).get("label", "Map")
    credit = (available.get(initial_style) or {}).get("attribution", "")
    return f"""
    <div class="panel view3d-panel">
      <canvas class="view3d" id="view3d-{uid}"
              aria-label="Interactive three-dimensional view of the flight over terrain">
      </canvas>
      {earth}
      <p class="view3d-credit">{credit}</p>
      <div class="view3d-controls">
        <button type="button" data-view3d-act="rotate-left"
                title="Rotate left" aria-label="Rotate left">&#8630;</button>
        <button type="button" data-view3d-act="rotate-right"
                title="Rotate right" aria-label="Rotate right">&#8631;</button>
        <button type="button" data-view3d-act="tilt-up"
                title="Tilt up" aria-label="Tilt up">&#8593;</button>
        <button type="button" data-view3d-act="tilt-down"
                title="Tilt down" aria-label="Tilt down">&#8595;</button>
        <button type="button" data-view3d-act="zoom-in"
                title="Zoom in" aria-label="Zoom in">+</button>
        <button type="button" data-view3d-act="zoom-out"
                title="Zoom out" aria-label="Zoom out">&minus;</button>
        <button type="button" data-view3d-act="basemap" class="is-on"
                title="Satellite, map or bare terrain"
                aria-label="Basemap: satellite, map or bare terrain">{basemap_label}</button>
        <button type="button" data-view3d-act="exaggerate"
                title="Vertical exaggeration" aria-label="Vertical exaggeration">
          &#215;1 height</button>
        <button type="button" data-view3d-act="fullscreen"
                title="Full screen" aria-label="Full screen">
          {EXPAND_ICON}</button>
        <button type="button" data-view3d-act="reset" aria-label="Reset view">Reset view</button>
      </div>
      <script type="application/json" class="view3d-data">{json.dumps(payload)}</script>
    </div>"""


STYLE = """
/* Full-bleed: the map is the one thing worth more than the page's reading width. The
   clip has to go on the *root* — html is the scroll container, so clipping body alone
   leaves the page scrolling sideways by the scrollbar's width, which 100vw includes.
   `clip` rather than `hidden` so no new scroll container is created. Verified by trying
   to scroll: scrollWidth still reports the ink extent, which is why the naive check
   looked like a bug that was not there. */
:root, body { overflow-x: clip; }
/* --scrollbar is measured in JS. 100vw includes the scrollbar, so a panel that wide
   hangs off the layout viewport and anything anchored to its right edge — the controls,
   the credit — is clipped. */
.view3d-panel { position: relative; padding: 0; overflow: hidden;
  --page: calc(100vw - var(--scrollbar, 0px));
  width: var(--page); margin-left: calc(50% - var(--page) / 2);
  border-left: 0; border-right: 0; border-radius: 0; }
/* aspect-ratio rather than a height attribute, so the canvas can be re-sized to its box
   — a canvas with fixed width/height attributes and height:auto cannot. */
canvas.view3d { display: block; width: 100%; aspect-ratio: 21 / 9; cursor: grab;
  background: linear-gradient(180deg, var(--panel-2) 0%, var(--panel) 62%); touch-action: none; }
@media (max-width: 900px) { canvas.view3d { aspect-ratio: 4 / 3; } }
/* Real full screen, which is the path taken wherever the permission allows it. The UA
   stylesheet already positions the element over the screen; all that is needed is to
   undo the full-bleed sizing, which would otherwise keep the panel `--page` wide and
   pulled left by half the difference. 100%/100% and not 100vw/100vh: the viewport units
   are the *page's* viewport, and this element's containing block is the screen. */
.view3d-panel:fullscreen { width: 100%; height: 100%; margin: 0; border: 0; }
.view3d-panel:fullscreen canvas.view3d { width: 100%; height: 100%; aspect-ratio: auto; }
/* The backdrop is black by default and shows for a frame at either edge of the
   transition, which reads as a flash against a light report. */
.view3d-panel::backdrop { background: var(--panel); }
/* The fallback for an iframe that is not allowed real fullscreen. inset:0 with auto
   width and height fills the layout viewport exactly — 100vw/100vh would overshoot by
   the scrollbar and leave the canvas the wrong height. */
.view3d-panel.is-maximised { position: fixed; inset: 0; z-index: 60; width: auto;
  height: auto; margin: 0; }
.view3d-panel.is-maximised canvas.view3d { width: 100%; height: 100%; aspect-ratio: auto; }
.view3d-earth {
  position: absolute;
  top: 12px;
  left: 12px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  text-decoration: none;
  padding: 7px 12px;
  border-radius: 2px;
  border: 1px solid var(--rule-strong);
  background: var(--panel);
  color: var(--ink);
}
.view3d-earth:hover { background: var(--climb); border-color: var(--climb); color: var(--paper); }
/* Top right, opposite the Earth link: at the bottom it fought the control row, which
   on a phone wraps into the same space. */
.view3d-credit { position: absolute; right: 12px; top: 12px; margin: 0; font-size: 11px;
  color: var(--ink-2); background: color-mix(in srgb, var(--panel) 78%, transparent);
  padding: 3px 7px; border-radius: 2px; max-width: 46%; text-align: right; }
canvas.view3d.is-dragging { cursor: grabbing; }
/* The sun and the wind are drawn *on the canvas*, not in the DOM: both are geographic
   directions and have to turn with the view, which means living in the same coordinate
   system as the terrain they describe. There is no control here any more — the sun
   follows the chart cursor, so the time comes from wherever the reader is pointing. */
.view3d-controls { position: absolute; right: 10px; bottom: 10px; left: 10px; display: flex;
  gap: 5px; flex-wrap: wrap; justify-content: flex-end; }
/* This media query used to reduce padding to `5px 7px` and type to 10.5 px — shrinking
   the targets on the one device where a finger replaces a mouse, which is backwards. On
   a phone the controls get *more* room, not less, and the type sits on the 12 px mobile
   floor rather than under the 11 px desktop one. */
@media (max-width: 640px) {
  .view3d-controls { gap: 4px; }
  .view3d-controls button { padding: 8px 10px; font-size: 12px; }
}
.view3d-controls button {
  font: inherit;
  font-size: 11.5px;
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 4px 9px;
  border: 1px solid var(--rule-strong);
  border-radius: 2px;
  background: var(--panel);
  color: var(--ink-2);
  cursor: pointer;
}
.view3d-controls button:hover { color: var(--ink); background: var(--panel-2); }
.view3d-controls button.is-on { background: var(--climb); border-color: var(--climb);
  color: var(--paper); }
.view3d-controls button svg { display: block; }
"""


SCRIPT = """
// The scrollbar's width, so a full-bleed panel can be exactly the layout viewport.
//
// This has to be innerWidth - clientWidth: an offscreen probe element reports 0 in a
// browser that gives overlay scrollbars to elements and a classic one to the document,
// which is exactly what headless Chrome does, and the panel then overhangs by the
// scrollbar's width and clips its own controls.
//
// The catch is *when* it is measured. On a phone, showing or hiding the address bar fires
// a resize during which the two numbers are briefly inconsistent, and re-measuring then
// gave the panel a phantom 10-20 px of scrollbar mid-scroll — the 3D view visibly
// shrinking as you dragged. So: only on a width change, clamped to a plausible scrollbar,
// and callable by anything that grows the page enough to introduce one.
function measureScrollbar() {
  var width = window.innerWidth - document.documentElement.clientWidth;
  document.documentElement.style.setProperty(
    '--scrollbar', Math.max(Math.min(width, 30), 0) + 'px');
}
measureScrollbar();
window.__measureScrollbar = measureScrollbar;
var scrollbarWidth = window.innerWidth;
window.addEventListener('resize', function () {
  // A height-only resize is the address bar, and must not move anything sideways.
  if (window.innerWidth === scrollbarWidth) return;
  scrollbarWidth = window.innerWidth;
  measureScrollbar();
});


function initView3d(root, cursorTrack) {
  var canvas = root.querySelector('canvas.view3d');
  var payload = root.querySelector('.view3d-data');
  if (!canvas || !payload) return null;
  var scene = JSON.parse(payload.textContent);
  var dem = scene.terrain;
  var ctx = canvas.getContext('2d');
  // The canvas has no width/height attributes: CSS sizes the box and this matches the
  // backing store to it, so the same code serves an inline panel and full screen.
  var W = 0, H = 0;

  function resize() {
    var rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return false;
    // Cap the pixel ratio: at 3× a phone would ask for a 3000-pixel-wide heightfield
    // redraw on every frame of a drag.
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    var width = Math.round(rect.width * ratio);
    var height = Math.round(rect.height * ratio);
    if (width === W && height === H) return false;
    canvas.width = W = width;
    canvas.height = H = height;
    if (renderer) renderer.resize(W, H);
    return true;
  }
  resize();

  // Local metric frame about the DEM centre, so rotation is about the middle of
  // the terrain rather than the corner of a bounding box.
  var lat0 = (dem.north + dem.south) / 2;
  var lon0 = (dem.east + dem.west) / 2;
  var mPerDegLat = 110540;
  var mPerDegLon = 111320 * Math.cos(lat0 * Math.PI / 180);
  function toMetres(lon, lat) {
    return [(lon - lon0) * mPerDegLon, (lat - lat0) * mPerDegLat];
  }

  var spanX = (dem.east - dem.west) * mPerDegLon;
  var spanY = (dem.north - dem.south) * mPerDegLat;

  // True scale by default: the whole point of putting the flight over a DEM is that
  // heights can be compared with the ground, and an exaggerated vertical breaks that.
  // The ×2 button is there for when the relief needs help.
  var baseVertical = 1;
  // panX/panY are screen-space offsets applied after the fit, which is what lets the
  // view be dragged off centre — the fit alone always recentres, so without these the
  // camera was welded to the middle of the flight.
  var view = { yaw: -0.42, pitch: 0.46, zoom: 1, vertical: baseVertical, map: true,
               panX: 0, panY: 0 };

  // The basemap carries the place names, which is the whole reason it is here: a
  // hillshade shows the shape of a ridge but never tells you which village it is above.
  var basemap = null;
  var cellColour = null;      // one averaged map colour per texture cell
  var cellCols = 0, cellRows = 0;

  // Two drape resolutions. Each cell costs a drawImage and an overlay fillRect, so the
  // fine mesh is far too expensive to run on every frame of a drag — but a mesh coarse
  // enough to drag smoothly shows its own quadrilaterals, which is what "visible squares"
  // was. So: coarse while the reader is moving the camera, fine once they stop.
  // Budgets in *cells*, not in columns: the grid's aspect varies wildly between a ridge
  // run and a triangle, and what costs time is the cell count. Measured at ~22 us per
  // cell in software rendering, so 5 200 is about 110 ms for the settled frame and 1 800
  // keeps a drag near 40 fps.
  var FINE_BUDGET = 5200;
  var COARSE_BUDGET = 1800;
  var interacting = false;
  var settle = null;

  function texStep() {
    var scale = Math.sqrt(cols * rows / (interacting ? COARSE_BUDGET : FINE_BUDGET));
    var step = Math.max(Math.round(scale), 1);
    return { c: step, r: step };
  }

  // Called by every gesture handler. The trailing redraw is what actually puts the fine
  // mesh on screen, so it has to fire even if the gesture ended without a final event.
  function moving() {
    interacting = true;
    if (settle) clearTimeout(settle);
    settle = setTimeout(function () {
      settle = null;
      interacting = false;
      draw();
    }, 180);
  }

  // A per-cell average of the map, taken once by letting the browser downscale the
  // image. It is painted under each textured cell so the small gaps where a non-planar
  // cell disagrees with its affine fit show ground colour rather than sky.
  function sampleCellColours() {
    // Only the 2D drape has cells to fill under. A depth-buffered backend draws the
    // texture once over real geometry, so this would be a getImageData for nothing.
    if (renderer) { cellColour = null; return; }
    try {
      var steps = texStep();
      cellCols = Math.max(Math.round(cols / steps.c), 1);
      cellRows = Math.max(Math.round(rows / steps.r), 1);
      var off = document.createElement('canvas');
      off.width = cellCols;
      off.height = cellRows;
      var octx = off.getContext('2d');
      octx.drawImage(basemap, 0, 0, cellCols, cellRows);
      cellColour = octx.getImageData(0, 0, cellCols, cellRows).data;
    } catch (e) {
      cellColour = null;
    }
  }

  // Which imagery the reader is looking at. Styles baked into the document are used as
  // they are; anything else is stitched from tiles when it is first selected, which only
  // works where the page can reach the network.
  var embedded = scene.basemaps || {};
  var order = ['satellite', 'map'].filter(function (name) {
    return embedded[name] || (scene.tiles && scene.tiles[name]);
  });
  var style = order[0] || null;
  var loading = false;

  function tileNumbers(lon, lat, zoom) {
    var n = Math.pow(2, zoom);
    var x = (lon + 180) / 360 * n;
    var radians = lat * Math.PI / 180;
    var y = (1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2 * n;
    return [x, y];
  }

  function tileZoom(source) {
    // Enough tiles to be sharp, few enough to be polite: aim for a mosaic no wider than
    // Nothing is embedded on this path, so the budget buys sharpness rather than bytes:
    // 120 tiles reaches zoom 12-13 on a cross-country box, roughly 10-20 m per pixel
    // against the 80 m that a 30-tile budget allowed.
    for (var zoom = Math.min(14, source.max_zoom); zoom > 5; zoom--) {
      var a = tileNumbers(dem.west, dem.north, zoom);
      var b = tileNumbers(dem.east, dem.south, zoom);
      var across = Math.floor(b[0]) - Math.floor(a[0]) + 1;
      var down = Math.floor(b[1]) - Math.floor(a[1]) + 1;
      if (across * down <= 120) return zoom;
    }
    return 6;
  }

  // Images ready to drape, keyed by style: the embedded ones from the start, a stitched
  // mosaic once it has been fetched. Switching back to one is then instant.
  var ready = {};

  function labelFor(name) {
    if (name === 'off') return 'Basemap';
    var source = (scene.tiles && scene.tiles[name]) || {};
    return source.label || (name === 'satellite' ? 'Satellite' : 'Map');
  }

  function basemapButtons() {
    return root.querySelectorAll('[data-view3d-act="basemap"]');
  }

  function setBasemapStyle(next) {
    basemapButtons().forEach(function (button) {
      button.textContent = labelFor(next);
      button.classList.toggle('is-on', next !== 'off');
    });
    if (next === 'off') { view.map = false; draw(); return; }
    view.map = true;
    style = next;
    if (ready[next]) {
      basemap = ready[next].shaded || ready[next].image;
      scene.basemap = ready[next].box;
      sampleCellColours();
      showCredit(ready[next].box.attribution);
      draw();
      return;
    }
    basemap = null;
    cellColour = null;
    draw();
    loadTiles(next);
  }

  // Decode whatever was baked in. Each style is an independent image, so a document that
  // carries only one still shows that one and falls back to tiles for the other.
  Object.keys(embedded).forEach(function (name) {
    var box = embedded[name];
    var image = new Image();
    image.onload = function () {
      ready[name] = { image: image, box: box };
      // Shading depends on the style (a photograph needs less than a road map), so it is
      // baked per style rather than once.
      var was = style;
      style = name;
      ready[name].shaded = shadedTexture(image, box);
      style = was;
      if (style === name) setBasemapStyle(name);
    };
    image.src = box.uri;
  });

  function showCredit(text) {
    var credit = root.querySelector('.view3d-credit');
    if (credit) credit.textContent = text;
  }

  function loadTiles(styleName) {
    var source = scene.tiles && scene.tiles[styleName];
    if (!source || loading) return;
    loading = true;
    showCredit('Loading ' + source.label.toLowerCase() + ' tiles…');
    var zoom = tileZoom(source);
    var a = tileNumbers(dem.west, dem.north, zoom);
    var b = tileNumbers(dem.east, dem.south, zoom);
    var x0 = Math.floor(a[0]), x1 = Math.floor(b[0]);
    var y0 = Math.floor(a[1]), y1 = Math.floor(b[1]);
    var size = 256;
    var mosaic = document.createElement('canvas');
    mosaic.width = (x1 - x0 + 1) * size;
    mosaic.height = (y1 - y0 + 1) * size;
    var mctx = mosaic.getContext('2d');
    var pending = 0, done = 0;

    // One canvas per layer, composited in declaration order at the end. Painting every
    // tile straight into the mosaic as it arrives makes z-order a race — the labels
    // layer is requested second but frequently answers first, and then the imagery
    // covers it.
    var layers = source.layers.map(function () {
      var layer = document.createElement('canvas');
      layer.width = mosaic.width;
      layer.height = mosaic.height;
      return layer;
    });

    // The mosaic covers whole tiles, so its geographic box is larger than the DEM's.
    function lonOf(x) { return x / Math.pow(2, zoom) * 360 - 180; }
    function latOf(y) {
      var t = Math.PI - 2 * Math.PI * y / Math.pow(2, zoom);
      return 180 / Math.PI * Math.atan(0.5 * (Math.exp(t) - Math.exp(-t)));
    }
    var box = {
      west: lonOf(x0), east: lonOf(x1 + 1),
      north: latOf(y0), south: latOf(y1 + 1),
      attribution: source.attribution
    };

    function finish() {
      loading = false;
      if (done === 0) {
        // No tiles at all: almost certainly a content-security policy. Skip to the next
        // style the document can actually show rather than leaving the button dead.
        var fallback = order.filter(function (name) {
          return name !== styleName && (ready[name] || embedded[name]);
        })[0];
        if (fallback) { setBasemapStyle(fallback); return; }
        showCredit('Map imagery unavailable here — hillshade only');
        basemapButtons().forEach(function (button) {
          button.classList.remove('is-on');
        });
        view.map = false;
        draw();
        return;
      }
      layers.forEach(function (layer) { mctx.drawImage(layer, 0, 0); });
      var image = new Image();
      image.onload = function () {
        var was = style;
        style = styleName;
        ready[styleName] = {image: image, box: box, shaded: shadedTexture(image, box)};
        style = was;
        if (style !== styleName) return;    // the reader cycled on while we stitched
        basemap = ready[styleName].shaded || image;
        scene.basemap = box;
        sampleCellColours();
        showCredit(source.attribution);
        draw();
      };
      image.src = mosaic.toDataURL('image/jpeg', 0.82);
    }

    source.layers.forEach(function (template, index) {
      for (var ty = y0; ty <= y1; ty++) {
        for (var tx = x0; tx <= x1; tx++) {
          pending++;
          (function (tx, ty, index) {
            var image = new Image();
            image.crossOrigin = 'anonymous';   // needed to read the mosaic back out
            image.onload = function () {
              layers[index].getContext('2d').drawImage(
                image, (tx - x0) * size, (ty - y0) * size, size, size);
              done++;
              if (--pending === 0) finish();
            };
            image.onerror = function () {
              if (--pending === 0) finish();
            };
            image.src = template.replace('{z}', zoom).replace('{x}', tx).replace('{y}', ty);
          })(tx, ty, index);
        }
      }
    });
    if (!pending) finish();
  }

  // Nothing baked in for the opening style: fetch it. An embedded one is already decoding.
  if (style && !embedded[style]) loadTiles(style);

  function world(x, y, z) {
    var cy = Math.cos(view.yaw), sy = Math.sin(view.yaw);
    var wx = x * cy - y * sy;
    var wy = x * sy + y * cy;
    var wz = (z - dem.min) * view.vertical;
    var cp = Math.cos(view.pitch), sp = Math.sin(view.pitch);
    // Screen y grows downward, so the northward axis has to be negated: without it
    // the far side of the terrain lands at the bottom of the canvas, which is the
    // same picture as looking from the north — east and west come out swapped.
    return [wx, -wy * sp - wz * cp, wy];
  }

  // Fit is recomputed per frame because yaw and pitch change the outline. It is
  // deliberately computed at ×1 regardless of the current exaggeration: fitting the
  // exaggerated outline zooms out by exactly the factor the user just asked for, which
  // is why the ×2 button appeared to do nothing at all.
  var fit = { scale: 1, dx: 0, dy: 0 };
  // Where the fit puts the middle of the scene. zoomAt has to measure the cursor from
  // this point, not from the canvas corner, so it is named rather than written twice.
  function anchorX() { return W / 2; }
  function anchorY() { return H * 0.58; }
  function refit() {
    var wanted = view.vertical;
    view.vertical = 1;
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    function consider(p) {
      if (p[0] < minX) minX = p[0];
      if (p[0] > maxX) maxX = p[0];
      if (p[1] < minY) minY = p[1];
      if (p[1] > maxY) maxY = p[1];
    }
    // Sampling the grid is enough for bounds and keeps this cheap.
    for (var r = 0; r < rows; r += 3) {
      for (var c = 0; c < cols; c += 6) {
        var i = r * cols + c;
        consider(world(nodeX[i], nodeY[i], dem.z[i]));
      }
    }
    var t = scene.track;
    for (var k = 0; k < t.lon.length; k += 7) {
      var m = toMetres(t.lon[k], t.lat[k]);
      consider(world(m[0], m[1], t.alt[k]));
    }
    // Slight overfill: the bounds are of a *rotated* rectangle, whose bounding box is
    // wider than the rectangle itself, so fitting the box exactly leaves visible margins
    // on every side. Overflowing the terrain edge costs nothing — it is only terrain.
    var scale = Math.min(W * 1.08 / Math.max(maxX - minX, 1),
                         H * 1.02 / Math.max(maxY - minY, 1));
    view.vertical = wanted;
    fit.scale = scale * view.zoom;
    fit.dx = anchorX() - (minX + maxX) / 2 * fit.scale;
    // Keep the *ground* centred rather than the whole scene: as the exaggeration grows
    // the flight should climb up the canvas, not push the terrain off the bottom.
    fit.dy = anchorY() - (minY + maxY) / 2 * fit.scale;
  }

  function project(x, y, z) {
    var w = world(x, y, z);
    return [fit.dx + w[0] * fit.scale + view.panX, fit.dy + w[1] * fit.scale + view.panY];
  }

  // Grid node positions in metres, computed once; only the projection changes.
  var cols = dem.cols, rows = dem.rows;
  var nodeX = new Float64Array(rows * cols);
  var nodeY = new Float64Array(rows * cols);
  for (var r = 0; r < rows; r++) {
    var lat = dem.north - (dem.north - dem.south) * r / (rows - 1);
    for (var c = 0; c < cols; c++) {
      var lon = dem.west + (dem.east - dem.west) * c / (cols - 1);
      var m = toMetres(lon, lat);
      nodeX[r * cols + c] = m[0];
      nodeY[r * cols + c] = m[1];
    }
  }

  // How hard to shade a draped image. Satellite imagery is a photograph and already
  // shows its own light; a cartographic map is flat fill and needs real relief on top.
  function reliefBoost() { return style === 'satellite' ? 1.0 : 1.5; }

  // The lit range this particular terrain actually spans, measured once. A fixed
  // shading curve assumes alpine relief: over the gentle ground most flights happen on,
  // `lit` stays within a few hundredths of flat-ground illumination and the overlay does
  // nothing at all — which is how a road map came out looking like a flat sheet. Stretch
  // the observed range instead, so relief reads at whatever scale the ground has.
  var litMid = 0.86, litSpread = 0;
  function measureLit() {
    litMid = 0.86; litSpread = 0;
    var lo = Infinity, hi = -Infinity;
    for (var r = 0; r < rows; r += 2) {
      for (var c = 0; c < cols; c += 2) {
        var lit = shadeFactor(r, c);
        if (lit < lo) lo = lit;
        if (lit > hi) hi = lit;
      }
    }
    if (!isFinite(lo) || hi - lo < 0.01) return;   // genuinely flat: leave it unshaded
    litMid = (lo + hi) / 2;
    litSpread = (hi - lo) / 2;
  }
  measureLit();

  // The heightfield is the only part of this that a depth buffer changes, so it is the
  // only part a backend may replace. `view3d_gl.py` registers one; with nothing
  // registered — or on a machine with no WebGL, or after a context loss — the per-cell
  // 2D drape below runs exactly as it always has.
  //
  // Everything else stays here and is shared: one camera, one set of gestures, one tile
  // stitcher, one set of probes. That is deliberate. The camera in particular has to
  // invert through groundUnder()/holdGround() for every gesture to anchor, and the
  // surest way to keep a second renderer bit-compatible with that is for it to read the
  // same `view` and `fit` objects rather than to own a copy.
  var renderer = window.__view3dBackend ? window.__view3dBackend({
    canvas: canvas,
    dem: dem,
    cols: cols,
    rows: rows,
    nodeX: nodeX,
    nodeY: nodeY,
    view: view,          // held by reference: the gestures mutate it in place
    fit: fit,            // ditto, recomputed by refit() before every frame
    size: function () { return [W, H]; },
    shadeFactor: shadeFactor,
    lit: function () { return { mid: litMid, spread: litSpread }; },
    // The already-shaded basemap and the geographic box it covers. Both change when the
    // reader cycles the style or a tile mosaic finishes stitching, and the backend
    // notices by identity rather than by being told.
    texture: function () { return basemap; },
    textureBox: function () { return scene.basemap; },
    // Hand the heightfield back to the 2D path. Context loss on a phone is real, and a
    // blank panel is a worse outcome than a slower one.
    fallback: function () { renderer = null; sampleCellColours(); draw(); }
  }) : null;

  // Where the light comes from, in the frame the gradients below are computed in: x
  // east, y *south* (rows run north to south), z up. The default is the fixed direction
  // this always used; `setLight` replaces it with the real sun when the payload carries
  // a day track, which is what makes "which slopes were lit, and when" a question the
  // view can answer rather than a decoration.
  var lightX = -0.55, lightY = 0.55, lightZ = 0.63;

  function setLight(azimuth, elevation) {
    // A sun on the horizon lights nothing and the hillshade collapses to a silhouette,
    // so hold it a few degrees up. Below the horizon the terrain is drawn by the same
    // rule — there is no night mode; the label says the sun is down and the shading
    // shows the last light it had.
    var el = Math.max(elevation, 3) * Math.PI / 180;
    var az = azimuth * Math.PI / 180;
    lightX = Math.cos(el) * Math.sin(az);
    lightY = -Math.cos(el) * Math.cos(az);   // north in the payload, south in this frame
    lightZ = Math.sin(el);
  }

  function shadeFactor(r, c) {
    var i = r * cols + c;
    var here = dem.z[i];
    var right = dem.z[i + (c + 1 < cols ? 1 : 0)];
    var below = dem.z[i + (r + 1 < rows ? cols : 0)];
    var cellX = spanX / (cols - 1), cellY = spanY / (rows - 1);
    var dzdx = (right - here) / cellX, dzdy = (below - here) / cellY;
    var nx = -dzdx, ny = -dzdy, nz = 1;
    var len = Math.sqrt(nx * nx + ny * ny + nz * nz);
    var light = (nx * lightX + ny * lightY + nz * lightZ) / len;
    return Math.max(0.25, Math.min(1.15, 0.55 + light * 0.65));
  }

  function shade(r, c) {
    // Slope shading from the two in-grid gradients, lit from the north-west, stretched
    // to this terrain's own lit range for the same reason the draped version is.
    var i = r * cols + c;
    var here = dem.z[i];
    var lit = 0.96;
    if (litSpread > 0) {
      var t = Math.max(-1, Math.min(1, (shadeFactor(r, c) - litMid) / litSpread));
      lit = 0.86 + t * 0.30;
    }
    // Elevation tint: low ground greener, high ground paler and greyer.
    var t = Math.min(1, Math.max(0, (here - dem.min) / Math.max(dem.max - dem.min, 1)));
    var rr = (120 + t * 95) * lit;
    var gg = (135 + t * 80) * lit;
    var bb = (105 + t * 95) * lit;
    return 'rgb(' + (rr | 0) + ',' + (gg | 0) + ',' + (bb | 0) + ')';
  }

  // The map has to follow the relief, not lie flat under it: at these vertical
  // exaggerations a flat floor and an exaggerated mesh separate visibly. Drawing it in
  // north-south bands, each affine-fitted to that band's mean ground height, keeps the
  // names readable and the geometry honest for a dozen drawImage calls a frame.
  var STRIPS = 10;
  // Banding exists to follow relief. Where there is little relief it only buys seams,
  // so flat ground gets one exact affine fit at the mean elevation instead.
  var BAND_THRESHOLD = 500;  // metres of terrain range

  // Ground elevation anywhere in the box, bilinear on the DEM grid. Everything that
  // belongs on the ground — the track's shadow, the cursor's drop line — needs this:
  // drawing it on a flat plane at the minimum elevation makes it slide against the
  // terrain as the view rotates, because it is simply not where the ground is.
  function groundAt(lon, lat) {
    var gx = (lon - dem.west) / (dem.east - dem.west) * (cols - 1);
    var gy = (dem.north - lat) / (dem.north - dem.south) * (rows - 1);
    gx = Math.max(0, Math.min(cols - 1, gx));
    gy = Math.max(0, Math.min(rows - 1, gy));
    var x0 = Math.floor(gx), y0 = Math.floor(gy);
    var x1 = Math.min(x0 + 1, cols - 1), y1 = Math.min(y0 + 1, rows - 1);
    var fx = gx - x0, fy = gy - y0;
    var top = dem.z[y0 * cols + x0] * (1 - fx) + dem.z[y0 * cols + x1] * fx;
    var bottom = dem.z[y1 * cols + x0] * (1 - fx) + dem.z[y1 * cols + x1] * fx;
    return top * (1 - fy) + bottom * fy;
  }

  // Source rectangle in basemap pixels for a grid cell, so the map can be drawn cell
  // by cell and therefore sits *on* the surface rather than under it.
  // The shading has to live in the texture, not in the geometry pass.
  //
  // Tinting each cell was three artefacts in a row. Cells must overdraw their neighbours,
  // because a projected quad is not a parallelogram and the affine texture fit leaves
  // hairline gaps otherwise — but a semi-transparent tint drawn over that overdraw lands
  // twice in the overlap, which is a dark lattice over the whole slab; matching the tint
  // to a smaller extent instead gives every cell an untinted border, which is the same
  // lattice again. There is no per-cell extent that is right.
  //
  // The basemap raster and the DEM are both axis-aligned in lon/lat, so the illumination
  // can be composited into a copy of the image once, at grid resolution, and stretched by
  // the browser — which also interpolates it, so the result is smooth rather than faceted.
  function shadedTexture(image, box) {
    var iw = image.naturalWidth || image.width;
    var ih = image.naturalHeight || image.height;
    if (!iw || !ih) return image;
    var out = document.createElement('canvas');
    out.width = iw;
    out.height = ih;
    var octx = out.getContext('2d');
    octx.drawImage(image, 0, 0);
    if (litSpread <= 0) return out;

    var shade = document.createElement('canvas');
    shade.width = cols;
    shade.height = rows;
    var sctx = shade.getContext('2d');
    var pixels = sctx.createImageData(cols, rows);
    var boost = reliefBoost();
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var t = Math.max(-1, Math.min(1, (shadeFactor(r, c) - litMid) / litSpread));
        var i = (r * cols + c) * 4;
        if (t >= 0) {
          pixels.data[i] = 255; pixels.data[i + 1] = 252; pixels.data[i + 2] = 242;
        } else {
          pixels.data[i] = 18; pixels.data[i + 1] = 26; pixels.data[i + 2] = 38;
        }
        pixels.data[i + 3] = Math.round(Math.min(Math.abs(t) * 0.34 * boost, 1) * 255);
      }
    }
    sctx.putImageData(pixels, 0, 0);

    // Where the DEM's box sits inside the image's, in the same linear lon/lat mapping
    // sourceRect uses — so the shading registers with the texture cell for cell.
    var x0 = (dem.west - box.west) / (box.east - box.west) * iw;
    var x1 = (dem.east - box.west) / (box.east - box.west) * iw;
    var y0 = (box.north - dem.north) / (box.north - box.south) * ih;
    var y1 = (box.north - dem.south) / (box.north - box.south) * ih;
    octx.imageSmoothingEnabled = true;
    octx.imageSmoothingQuality = 'high';
    octx.drawImage(shade, 0, 0, cols, rows, x0, y0, x1 - x0, y1 - y0);
    return out;
  }

  function sourceRect(r, c, rStep, cStep) {
    var bm = scene.basemap;
    var iw = basemap.naturalWidth || basemap.width;
    var ih = basemap.naturalHeight || basemap.height;
    var lonW = dem.west + (dem.east - dem.west) * c / (cols - 1);
    var lonE = dem.west + (dem.east - dem.west) * Math.min(c + cStep, cols - 1) / (cols - 1);
    var latN = dem.north - (dem.north - dem.south) * r / (rows - 1);
    var latS = dem.north - (dem.north - dem.south) * Math.min(r + rStep, rows - 1) / (rows - 1);
    var sx = (lonW - bm.west) / (bm.east - bm.west) * iw;
    var ex = (lonE - bm.west) / (bm.east - bm.west) * iw;
    var sy = (bm.north - latN) / (bm.north - bm.south) * ih;
    var ey = (bm.north - latS) / (bm.north - bm.south) * ih;
    return [sx, sy, Math.max(ex - sx, 0.5), Math.max(ey - sy, 0.5)];
  }

  // One triangle of a cell, textured exactly.
  //
  // Three points determine an affine map, so a triangle's texture mapping is exact even
  // when the cell as a whole has folded — which is the whole reason for this path. The
  // clip is set under the identity transform (clips live in device space) and the texture
  // transform is applied after it.
  function texturedTriangle(a, b, c, m11, m12, m21, m22, rect) {
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(b[0], b[1]);
    ctx.lineTo(c[0], c[1]);
    ctx.closePath();
    ctx.clip();
    ctx.setTransform(m11, m12, m21, m22, a[0], a[1]);
    // A whisker of overdraw so the shared edge of the two triangles does not show.
    ctx.drawImage(basemap, rect[0], rect[1], rect[2], rect[3], -0.01, -0.01, 1.02, 1.02);
    ctx.restore();
  }

  // The convex hull of the cell's four projected corners, as a filled polygon.
  //
  // A folded cell has to be covered by *one convex* shape. Its own outline is
  // self-intersecting, and canvas fills that as a bowtie — the wedge artefact. Splitting it
  // into two triangles is no better: for a folded quad the two triangles overlap and their
  // union leaves slivers uncovered, which then show whatever was painted earlier, which is
  // another wedge. The hull covers the whole cell, always convex, in one fill.
  function fillHull(points) {
    var sorted = points.slice().sort(function (a, b) {
      return a[0] - b[0] || a[1] - b[1];
    });
    var chain = [];
    for (var pass = 0; pass < 2; pass++) {
      var start = chain.length;
      for (var i = 0; i < 4; i++) {
        var q = pass === 0 ? sorted[i] : sorted[3 - i];
        while (chain.length - start >= 2 &&
               cross(chain[chain.length - 2], chain[chain.length - 1], q) <= 0) {
          chain.pop();
        }
        chain.push(q);
      }
      chain.pop();
    }
    if (chain.length < 3) return;
    ctx.beginPath();
    ctx.moveTo(chain[0][0], chain[0][1]);
    for (var k = 1; k < chain.length; k++) ctx.lineTo(chain[k][0], chain[k][1]);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }

  function cross(a, b, c) {
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  }

  // Convex, wound the way a front-facing cell is, and big enough to be worth drawing.
  function convex(a, b, c, d, facing) {
    var t1 = cross(a, b, c) * facing;
    if (t1 <= 0) return false;
    var t2 = cross(b, c, d) * facing;
    if (t2 <= 0) return false;
    var t3 = cross(c, d, a) * facing;
    if (t3 <= 0) return false;
    var t4 = cross(d, a, b) * facing;
    return t4 > 0 && (t1 + t2 + t3 + t4) > 0.5;
  }

  // Reused across frames: allocating 5 000 cells' worth of arrays per frame is its own
  // performance problem.
  var cellDepth = null, cellR = null, cellC = null, cellOrder = null;
  var stats = { cells: 0, folded: 0 };

  function drawTerrain(withMap) {
    // Paint far to near, by *camera* depth — which is not the same as the horizontal
    // depth this used to walk. `world()` projects to screen y = −(wy·sin p + wz·cos p),
    // so the axis into the screen is wy·cos p − wz·sin p: height matters, and at a
    // top-down pitch it is all that matters. Ordering by wy alone is exact only in the
    // horizontal-view limit, and everywhere else it lets a cell on the far side of a
    // ridge paint over the near slope — fragments of the wrong slope appearing as wedges
    // across a zoomed-in view. Sorting is a couple of milliseconds and it is correct.
    var cyaw = Math.cos(view.yaw), syaw = Math.sin(view.yaw);
    var cp = Math.cos(view.pitch), sp = Math.sin(view.pitch);
    var steps = texStep();
    var cStep = withMap ? steps.c : 1;
    var rStep = withMap ? steps.r : 1;

    var down = Math.floor((rows - 1) / rStep);
    var across = Math.floor((cols - 1) / cStep);
    var capacity = Math.max(down * across, 1);
    if (!cellDepth || cellDepth.length < capacity) {
      cellDepth = new Float64Array(capacity);
      cellR = new Int32Array(capacity);
      cellC = new Int32Array(capacity);
      cellOrder = new Int32Array(capacity);
    }
    var count = 0;
    for (var rr = 0; rr <= rows - 1 - rStep; rr += rStep) {
      for (var cc = 0; cc <= cols - 1 - cStep; cc += cStep) {
        var a00 = rr * cols + cc;
        var a01 = a00 + cStep;
        var a10 = a00 + cols * rStep;
        var zc = 0.25 * (dem.z[a00] + dem.z[a01] + dem.z[a10] + dem.z[a10 + cStep]);
        var xm = 0.5 * (nodeX[a00] + nodeX[a01]);
        var ym = 0.5 * (nodeY[a00] + nodeY[a10]);
        cellDepth[count] = (xm * syaw + ym * cyaw) * cp -
                           (zc - dem.min) * view.vertical * sp;
        cellR[count] = rr;
        cellC[count] = cc;
        cellOrder[count] = count;
        count++;
      }
    }
    // Sorting a typed array's *indices* needs a plain array; subarray+sort would reorder
    // the depths and lose the mapping.
    var order = Array.prototype.slice.call(cellOrder.subarray(0, count));
    order.sort(function (a, b) { return cellDepth[b] - cellDepth[a]; });
    stats.cells = count;
    stats.folded = 0;

    var refA = project(nodeX[0], nodeY[0], dem.min);

    // Which way round a front-facing cell comes out, taken from a flat cell at this
    // camera. Painting far-to-near needs no depth buffer, but it does not stop a cell on
    // the far side of a ridge from being drawn: at true scale that cell projects to a
    // sliver or turns inside out, and its affine texture map smears the imagery into a
    // wedge. Those were the pale triangles all over a zoomed-in view. Culling on the
    // determinant's sign and size drops exactly those cells and nothing else.
    var refB = project(nodeX[Math.min(cStep, cols - 1)],
                       nodeY[Math.min(cStep, cols - 1)], dem.min);
    var refIndex = Math.min(rStep, rows - 1) * cols;
    var refC = project(nodeX[refIndex], nodeY[refIndex], dem.min);
    var refDet = (refB[0] - refA[0]) * (refC[1] - refA[1]) -
                 (refB[1] - refA[1]) * (refC[0] - refA[0]);
    var facing = refDet >= 0 ? 1 : -1;

    for (var k = 0; k < count; k++) {
      {
        var slot = order[k];
        var r = cellR[slot], c = cellC[slot];
        var i00 = r * cols + c;
        var i01 = i00 + cStep;
        var i10 = i00 + cols * rStep;
        var i11 = i10 + cStep;
        var p00 = project(nodeX[i00], nodeY[i00], dem.z[i00]);
        var p01 = project(nodeX[i01], nodeY[i01], dem.z[i01]);
        var p11 = project(nodeX[i11], nodeY[i11], dem.z[i11]);
        var p10 = project(nodeX[i10], nodeY[i10], dem.z[i10]);

        // A cell whose projected quad has folded over gets a flat fill and no texture.
        //
        // Folds are unavoidable here: this is painter's order with no depth buffer, and on
        // a cliff seen from a shallow angle the far edge of a cell projects past its near
        // edge. Three ways to handle that, and only one is any good. Texturing it anyway
        // smears the imagery into a wedge — that was the original artefact. Skipping it
        // leaves a hole showing the sky, because painter's order means nothing was drawn
        // behind it. Filling it with the cell's own average colour reads as a plain facet,
        // which is what it is.
        var folded = !convex(p00, p01, p11, p10, facing);
        if (folded) stats.folded++;

        if (withMap) {
          if (folded) {
            // Flat fill over the cell's convex hull, in its own average colour. It cannot
            // be textured — the affine map of a folded quad smears the imagery — and it
            // cannot be skipped, because painter's order means nothing was drawn behind it
            // and the sky would show through. See fillHull for why the hull specifically.
            if (cellColour) {
              var fi = (Math.min(Math.floor(r / rStep), cellRows - 1) * cellCols +
                        Math.min(Math.floor(c / cStep), cellCols - 1)) * 4;
              ctx.fillStyle = 'rgb(' + cellColour[fi] + ',' + cellColour[fi + 1] + ',' +
                cellColour[fi + 2] + ')';
              ctx.strokeStyle = ctx.fillStyle;
              ctx.lineWidth = 1;
              fillHull([p00, p01, p11, p10]);
            }
            // While the camera is moving the flat hull is all it gets: two clipped draws
            // per folded cell is affordable for a still frame and not for a drag.
            if (!interacting) {
              var frect = sourceRect(r, c, rStep, cStep);
              texturedTriangle(p00, p01, p11,
                               p01[0] - p00[0], p01[1] - p00[1],
                               p11[0] - p01[0], p11[1] - p01[1], frect);
              texturedTriangle(p00, p11, p10,
                               p11[0] - p10[0], p11[1] - p10[1],
                               p10[0] - p00[0], p10[1] - p00[1], frect);
            }
            continue;
          }
          if (cellColour) {
            // Opaque base in the cell's average colour, on the true four corners.
            var ci = (Math.min(Math.floor(r / rStep), cellRows - 1) * cellCols +
                      Math.min(Math.floor(c / cStep), cellCols - 1)) * 4;
            ctx.beginPath();
            ctx.moveTo(p00[0], p00[1]);
            ctx.lineTo(p01[0], p01[1]);
            ctx.lineTo(p11[0], p11[1]);
            ctx.lineTo(p10[0], p10[1]);
            ctx.closePath();
            ctx.fillStyle = 'rgb(' + cellColour[ci] + ',' + cellColour[ci + 1] + ',' +
              cellColour[ci + 2] + ')';
            ctx.strokeStyle = ctx.fillStyle;
            ctx.lineWidth = 1;
            ctx.fill();
            ctx.stroke();
          }
          var rect = sourceRect(r, c, rStep, cStep);
          // Map the cell's own slice of the image onto the cell's parallelogram. No
          // clip and no save/restore: the drawn area *is* the cell, and a small
          // overdraw closes the hairline seams between neighbours.
          ctx.setTransform(
            p01[0] - p00[0], p01[1] - p00[1],
            p10[0] - p00[0], p10[1] - p00[1],
            p00[0], p00[1]
          );
          // Overdraw the *destination* to cover the affine seams, and expand the
          // *source* by the same fraction about the same centre so the texture keeps its
          // scale. Stretching the same slice over a larger quad — which is what an
          // overdraw on the destination alone does — scales the imagery up inside every
          // cell, so the content no longer lines up with its neighbour's, and every cell
          // boundary becomes a visible step. That was the lattice of squares: not the
          // shading, not the tint, but the texture drawn 10% too large in each cell.
          var grow = 0.05;
          ctx.drawImage(
            basemap,
            rect[0] - rect[2] * grow, rect[1] - rect[3] * grow,
            rect[2] * (1 + 2 * grow), rect[3] * (1 + 2 * grow),
            -grow, -grow, 1 + 2 * grow, 1 + 2 * grow
          );
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          continue;
        }

        ctx.beginPath();
        ctx.moveTo(p00[0], p00[1]);
        ctx.lineTo(p01[0], p01[1]);
        ctx.lineTo(p11[0], p11[1]);
        ctx.lineTo(p10[0], p10[1]);
        ctx.closePath();
        ctx.fillStyle = shade(r, c);
        // Stroke with the same colour: hairline gaps between quads otherwise show
        // the sky through the mesh.
        ctx.strokeStyle = ctx.fillStyle;
        ctx.lineWidth = 1;
        ctx.fill();
        ctx.stroke();
      }
    }
  }

  function drawTrack() {
    var t = scene.track;
    var n = t.lon.length;
    var pts = new Array(n);
    for (var i = 0; i < n; i++) {
      var m = toMetres(t.lon[i], t.lat[i]);
      pts[i] = project(m[0], m[1], t.alt[i]);
    }
    // Shadow drawn on the ground surface itself, so it stays under the track at every
    // angle instead of sliding about on a flat plane.
    ctx.strokeStyle = 'rgba(20,24,28,0.34)';
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    for (var j = 0; j < n; j++) {
      var mg = toMetres(t.lon[j], t.lat[j]);
      var g = project(mg[0], mg[1], groundAt(t.lon[j], t.lat[j]));
      if (j === 0) ctx.moveTo(g[0], g[1]); else ctx.lineTo(g[0], g[1]);
    }
    ctx.stroke();

    ctx.lineWidth = 2.6;
    ctx.lineCap = 'round';
    for (var k = 1; k < n; k++) {
      var col = scene.palette[t.c[k]];
      ctx.strokeStyle = 'rgb(' + col[0] + ',' + col[1] + ',' + col[2] + ')';
      ctx.beginPath();
      ctx.moveTo(pts[k - 1][0], pts[k - 1][1]);
      ctx.lineTo(pts[k][0], pts[k][1]);
      ctx.stroke();
    }

    scene.climbs.forEach(function (climb) {
      var m = toMetres(climb.lon, climb.lat);
      var p = project(m[0], m[1], climb.alt);
      ctx.beginPath();
      ctx.arc(p[0], p[1], 8.5, 0, Math.PI * 2);
      ctx.fillStyle = climb.tow ? 'rgba(27,175,122,0.92)' : 'rgba(235,104,52,0.92)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.85)';
      ctx.lineWidth = 1.4;
      ctx.stroke();
      ctx.fillStyle = '#fff';
      ctx.font = '600 11px ui-sans-serif, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(climb.label, p[0], p[1] + 0.5);
    });
  }

  var cursorIndex = null;
  function drawCursor() {
    if (cursorIndex === null || !cursorTrack) return;
    var i = Math.min(cursorIndex, cursorTrack.lon.length - 1);
    var m = toMetres(cursorTrack.lon[i], cursorTrack.lat[i]);
    var p = project(m[0], m[1], cursorTrack.alt[i]);
    var g = project(m[0], m[1], groundAt(cursorTrack.lon[i], cursorTrack.lat[i]));
    ctx.strokeStyle = 'rgba(255,255,255,0.7)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(p[0], p[1]);
    ctx.lineTo(g[0], g[1]);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(p[0], p[1], 5.5, 0, Math.PI * 2);
    ctx.fillStyle = '#fff';
    ctx.fill();
    ctx.strokeStyle = '#14171c';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // The sun and the wind, as arrows that turn with the view.
  //
  // Both are geographic bearings, so both have to be drawn in the scene's own frame:
  // `view.yaw` rotates the world counter-clockwise on screen, and screen y grows
  // downward, which together turn a compass bearing b into the screen angle below. Get
  // that wrong and the arrow points somewhere plausible at yaw 0 and lies at every other
  // heading — the failure that is invisible until you rotate the view.
  //
  // Shading already says where the light is, but only to someone who can read a
  // hillshade; an arrow says it outright, and the wind has no shading to say it at all.
  function bearingToScreen(bearing) {
    return (bearing - view.yaw * 180 / Math.PI - 90) * Math.PI / 180;
  }

  function drawArrow(cx, cy, angle, length, head, colour, width) {
    var tx = cx + Math.cos(angle) * length, ty = cy + Math.sin(angle) * length;
    ctx.strokeStyle = colour;
    ctx.fillStyle = colour;
    ctx.lineWidth = width;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(cx - Math.cos(angle) * length, cy - Math.sin(angle) * length);
    ctx.lineTo(tx, ty);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - Math.cos(angle - 0.42) * head, ty - Math.sin(angle - 0.42) * head);
    ctx.lineTo(tx - Math.cos(angle + 0.42) * head, ty - Math.sin(angle + 0.42) * head);
    ctx.closePath();
    ctx.fill();
  }

  // The numbers the rose is drawn from, exposed so a test can hold the wind arrow
  // against the convention it inverts: `from` is where the wind comes from, and drawing
  // along it rather than opposite it is the classic 180° error, invisible on any single
  // screenshot because a wrong arrow is still an arrow.
  function roseAngles() {
    var wind = scene.wind || null;
    var sunNow = sunTrack ? sunAt(sunMinute) : null;
    return {
      north: bearingToScreen(0),
      sun: sunNow ? { az: sunNow.az, el: sunNow.el, screen: bearingToScreen(sunNow.az),
                      minute: sunMinute } : null,
      wind: wind ? { from: wind.from, kmh: wind.kmh,
                     screen: bearingToScreen(wind.from + 180) } : null
    };
  }

  function drawRose() {
    var wind = scene.wind || null;
    var sunNow = sunTrack ? sunAt(sunMinute) : null;
    if (!wind && !sunNow) return;
    // Bottom left: the controls own the bottom right and the credit the top right.
    // Scaled off the backing store so it is the same size on a phone, in the panel and
    // full screen, where W changes by a factor of three.
    var scale = Math.max(0.75, Math.min(1.6, W / 1280));
    var radius = 30 * scale;
    var lines = [];
    if (sunNow) {
      lines.push('Sun ' + clock(sunMinute) + ' \\u00b7 ' +
                 (sunNow.el > 0 ? Math.round(sunNow.el) + '\\u00b0 ' + compass(sunNow.az)
                                : 'below the horizon'));
    }
    if (wind) lines.push('Wind ' + wind.kmh.toFixed(0) + ' km/h from ' + wind.cardinal);
    // The labels go under the rose, so the *block* has to fit — placing the circle first
    // and the text afterwards clipped the second line off the bottom of a 21:9 panel.
    var lineHeight = 13 * scale;
    var textBlock = lines.length * lineHeight;
    var cx = 16 * scale + radius;
    var cy = H - (14 * scale + textBlock + radius);

    ctx.save();
    ctx.font = (11 * scale).toFixed(0) + 'px ui-sans-serif, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(16,19,24,0.55)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.28)';
    ctx.lineWidth = 1 * scale;
    ctx.stroke();

    // North, so the two arrows can be read as bearings rather than as decoration.
    var north = bearingToScreen(0);
    ctx.fillStyle = 'rgba(255,255,255,0.75)';
    ctx.fillText('N', cx + Math.cos(north) * (radius - 8 * scale),
                 cy + Math.sin(north) * (radius - 8 * scale));

    if (wind) {
      // `wind.from` is where the wind blows *from* — the convention every forecast and
      // every pilot uses — so the arrow, which shows where the air is going, points the
      // opposite way. Drawing it along the reported bearing is the classic 180° error.
      drawArrow(cx, cy, bearingToScreen(wind.from + 180), radius - 11 * scale,
                7 * scale, 'rgba(120,190,255,0.95)', 2.2 * scale);
    }
    if (sunNow) {
      // The sun sits at its bearing, out at the rim, and dims when it is below the
      // horizon — where the shading is holding the light artificially at 3° and the
      // reader is entitled to know.
      var at = bearingToScreen(sunNow.az);
      var up = sunNow.el > 0;
      var sx = cx + Math.cos(at) * (radius - 9 * scale);
      var sy = cy + Math.sin(at) * (radius - 9 * scale);
      ctx.beginPath();
      ctx.arc(sx, sy, 5.5 * scale, 0, Math.PI * 2);
      ctx.fillStyle = up ? 'rgba(255,205,80,0.98)' : 'rgba(255,205,80,0.32)';
      ctx.fill();
      // Rays towards the middle: the direction the light actually travels, which is what
      // the hillshade is doing.
      ctx.strokeStyle = ctx.fillStyle;
      ctx.lineWidth = 1.6 * scale;
      ctx.beginPath();
      ctx.moveTo(sx - Math.cos(at) * 8 * scale, sy - Math.sin(at) * 8 * scale);
      ctx.lineTo(sx - Math.cos(at) * 15 * scale, sy - Math.sin(at) * 15 * scale);
      ctx.stroke();
    }

    // Drawn with a dark stroke behind the fill rather than a box: the rose sits over
    // whatever the terrain happens to be, and white text alone disappears against a
    // limestone face or a snowfield.
    ctx.textAlign = 'left';
    ctx.lineJoin = 'round';
    ctx.lineWidth = 3 * scale;
    ctx.strokeStyle = 'rgba(12,14,18,0.85)';
    ctx.fillStyle = 'rgba(255,255,255,0.95)';
    lines.forEach(function (line, i) {
      var y = cy + radius + (10 + i * 13) * scale;
      ctx.strokeText(line, cx - radius, y);
      ctx.fillText(line, cx - radius, y);
    });
    ctx.restore();
  }

  function paint() {
    // Match the backing store to the box on every frame. Relying on a ResizeObserver
    // or a post-toggle callback to do this was fragile: entering the maximised state
    // changed the box, the observer's timing did not line up with it, and the canvas
    // kept its old height while its CSS box was already full screen.
    resize();
    ctx.clearRect(0, 0, W, H);
    refit();
    var mapped = view.map && basemap && (basemap.width || basemap.naturalWidth) > 0;
    // With a backend mounted this canvas keeps only the track, the climb markers and the
    // cursor — a few thousand points and some text, which 2D draws well and which is
    // already wired to the charts. The heightfield goes underneath it in GL.
    if (renderer) renderer.terrain(mapped); else drawTerrain(mapped);
    drawTrack();
    drawCursor();
    drawRose();
  }

  var pending = false;
  function draw() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; paint(); });
  }

  // Input model borrowed from Google Earth, because that is what pilots already know:
  //   left-drag            pan
  //   right-drag, or ctrl/shift/alt + left-drag, or middle-drag   rotate and tilt
  //   wheel                zoom towards the pointer
  //   one finger           pan
  //   two fingers          pinch to zoom, twist to rotate
  var pointers = new Map();
  var gesture = null;   // 'pan' | 'orbit'
  var pinch = null;
  // Accumulated since the second finger went down, and which of rotate/tilt has won.
  var twistTotal = 0, tiltTotal = 0, twoFingerMode = null;
  var orbitAnchor = null;   // the ground point a rotate-drag grabbed
  var tiltAnchor = null;
  var undoPanX = 0, undoPanY = 0;
  var TWIST_DEADZONE = 0.10;   // radians, about 6 degrees
  var TILT_DEADZONE = 13;      // CSS pixels of two-finger travel

  function points() { return Array.from(pointers.values()); }

  // Signed shortest angle from a to b, so a twist through the ±pi seam does not jump.
  function angleDelta(a, b) {
    var d = b - a;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    return d;
  }

  function twoFingerState() {
    var p = points();
    return {
      distance: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y),
      angle: Math.atan2(p[1].y - p[0].y, p[1].x - p[0].x),
      cx: (p[0].x + p[1].x) / 2,
      cy: (p[0].y + p[1].y) / 2
    };
  }

  function orbitModifier(event) {
    return event.button === 2 || event.button === 1 ||
           event.ctrlKey || event.shiftKey || event.altKey || event.metaKey;
  }

  // Where a screen point lands on the ground plane, and the inverse.
  //
  // Rotating and tilting have to happen *about the fingers*, not about the middle of the
  // flight. The fit recentres the scene every frame, so changing yaw or pitch on its own
  // swings the whole view around the scene's centre — which is what "twist is centred on
  // the wrong position" and "the centre shifts at higher angles" both are. Anchoring needs
  // a fixed world point, and the ground plane gives an exact one: at z = dem.min the
  // height term drops out of the projection and it inverts in closed form.
  function groundUnder(clientX, clientY) {
    var box = canvas.getBoundingClientRect();
    var sp = Math.sin(view.pitch);
    if (Math.abs(sp) < 1e-4 || !fit.scale) return null;
    var sx = (clientX - box.left) / box.width * W;
    var sy = (clientY - box.top) / box.height * H;
    var wx = (sx - fit.dx - view.panX) / fit.scale;
    var wy = -(sy - fit.dy - view.panY) / (fit.scale * sp);
    var cy = Math.cos(view.yaw), sn = Math.sin(view.yaw);
    return [wx * cy + wy * sn, -wx * sn + wy * cy];
  }

  // Move the pan so that `point` (a ground-plane position from groundAt) projects back to
  // the same place on screen. Called after yaw or pitch has changed.
  function holdGround(point, clientX, clientY) {
    if (!point) return;
    var box = canvas.getBoundingClientRect();
    refit();
    var now = project(point[0], point[1], dem.min);
    var sx = (clientX - box.left) / box.width * W;
    var sy = (clientY - box.top) / box.height * H;
    view.panX += sx - now[0];
    view.panY += sy - now[1];
  }

  // Keep the point under the cursor fixed while zooming, the way every map does.
  function zoomAt(factor, clientX, clientY) {
    var box = canvas.getBoundingClientRect();
    // Measured from the fit's anchor, because a point's screen position is
    // anchor + world*scale*zoom + pan. Measuring from the canvas corner instead drops
    // the anchor term and biases every zoom by anchor*(ratio-1) — which read as the view
    // diving towards the bottom-right on both wheel and pinch.
    var sx = (clientX - box.left) / box.width * W - anchorX();
    var sy = (clientY - box.top) / box.height * H - anchorY();
    var before = view.zoom;
    view.zoom = Math.max(0.3, Math.min(12, view.zoom * factor));
    var ratio = view.zoom / before;
    view.panX = sx - (sx - view.panX) * ratio;
    view.panY = sy - (sy - view.panY) * ratio;
  }

  canvas.addEventListener('contextmenu', function (event) { event.preventDefault(); });

  canvas.addEventListener('pointerdown', function (event) {
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 2) {
      gesture = 'pinch';
      pinch = twoFingerState();
      twistTotal = 0;
      tiltTotal = 0;
      twoFingerMode = null;
      tiltAnchor = null;
      undoPanX = 0;
      undoPanY = 0;
    } else if (pointers.size === 1) {
      gesture = orbitModifier(event) ? 'orbit' : 'pan';
      // The point the drag grabbed, captured once. See the orbit branch below for why
      // it cannot be re-picked as the cursor travels.
      orbitAnchor = gesture === 'orbit'
        ? { x: event.clientX, y: event.clientY,
            point: groundUnder(event.clientX, event.clientY) }
        : null;
    }
    canvas.classList.add('is-dragging');
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener('pointermove', function (event) {
    var previous = pointers.get(event.pointerId);
    if (!previous) return;
    moving();
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    var box = canvas.getBoundingClientRect();
    var toCanvas = W / box.width;   // CSS pixels to canvas units

    if (pointers.size >= 2) {
      var now = twoFingerState();
      if (pinch) {
        // Pan by the centroid's movement first, then scale about where the fingers are
        // now. Doing it the other way round makes the view slide out from under the
        // fingers — zoomAt already moves the pan to anchor the point, and adding the
        // centroid delta afterwards double-counts it.
        //
        // Not while tilting, though: there the vertical travel *is* the gesture, so panning
        // with it drags the ground out from under the anchor by exactly the distance the
        // fingers moved. Measured as a 30 px drift on a 30 px drag before this exception.
        if (twoFingerMode !== 'tilt') {
          var stepX = (now.cx - pinch.cx) * toCanvas;
          var stepY = (now.cy - pinch.cy) * toCanvas;
          view.panX += stepX;
          view.panY += stepY;
          // Remembered only until the gesture is classified: if it turns out to be a tilt,
          // the pan spent crossing the deadzone has to come back, or the view has already
          // slid by the width of the deadzone before tilting starts.
          if (!twoFingerMode) { undoPanX += stepX; undoPanY += stepY; }
        }
        if (pinch.distance > 4 && now.distance > 4) {
          zoomAt(now.distance / pinch.distance, now.cx, now.cy);
        }

        // Twist to rotate, drag the pair up or down to tilt. Both sit behind a deadzone
        // that has to be broken before either engages — without it, twist-to-rotate spun
        // the camera on every imprecise pinch, which is why it was removed the first time.
        //
        // Whichever gesture is further through *its own* threshold wins, rather than
        // rotate being tested first: tilt was hard to trigger because a twist of half a
        // degree claimed the gesture before 26 px of travel could accumulate.
        twistTotal += angleDelta(pinch.angle, now.angle);
        tiltTotal += (now.cy - pinch.cy);
        if (!twoFingerMode) {
          var rotateProgress = Math.abs(twistTotal) / TWIST_DEADZONE;
          var tiltProgress = Math.abs(tiltTotal) / TILT_DEADZONE;
          if (rotateProgress >= 1 || tiltProgress >= 1) {
            twoFingerMode = rotateProgress >= tiltProgress ? 'rotate' : 'tilt';
            if (twoFingerMode === 'tilt') {
              view.panX -= undoPanX;
              view.panY -= undoPanY;
            }
            undoPanX = 0;
            undoPanY = 0;
          }
        }
        if (twoFingerMode === 'rotate') {
          // Rotate about the point between the fingers, which may drift with them.
          //
          // Minus, not plus. The finger angle is measured with atan2 in client
          // coordinates, where y grows *downward*, so a twist the reader sees as
          // clockwise comes out as a positive delta — while a positive `view.yaw`
          // turns the scene counter-clockwise on screen. Adding the two put the
          // ground under the fingers and then span it the other way, which is the
          // one thing a direct-manipulation gesture must never do. Measured rather
          // than reasoned: see the twist test in tests/test_view3d_gl.py.
          var hold = groundUnder(now.cx, now.cy);
          view.yaw -= angleDelta(pinch.angle, now.angle);
          holdGround(hold, now.cx, now.cy);
        } else if (twoFingerMode === 'tilt') {
          // Tilt about a *fixed* screen point, taken where the gesture began: the fingers
          // are travelling, so following them would be the pan this deliberately skips.
          if (!tiltAnchor) {
            tiltAnchor = { x: now.cx, y: now.cy, point: groundUnder(now.cx, now.cy) };
          }
          view.pitch = Math.max(0.18, Math.min(1.45,
            view.pitch + (now.cy - pinch.cy) * 0.005));
          holdGround(tiltAnchor.point, tiltAnchor.x, tiltAnchor.y);
        }
      }
      pinch = now;
      draw();
      return;
    }

    // Two units, on purpose. A pan moves the scene *in the canvas*, so it converts to
    // canvas pixels; a rotation is a statement about how far the hand travelled, so it
    // stays in CSS pixels. Rotating with the converted delta ties the gesture to the
    // backing store: measured on the same 90 px drag, a device pixel ratio of 2 gave
    // 0.900 rad of yaw against 0.450 at ratio 1 — the same movement turning the view
    // twice as far on a retina screen as on the machine it was tuned on.
    var cssX = event.clientX - previous.x;
    var cssY = event.clientY - previous.y;
    var dx = cssX * toCanvas;
    var dy = cssY * toCanvas;
    if (gesture === 'orbit') {
      // Orbit about the point the drag *grabbed*, held where it was grabbed — not about
      // whatever is under the cursor now.
      //
      // Re-picking the anchor each event looks equivalent and is not: the cursor has
      // travelled since the last one, so each event pins a different ground point, and
      // the centre of rotation creeps across the terrain with the mouse. Measured on a
      // 90 px drag, the point the drag started on slid 29 px at a device pixel ratio of
      // 1 and 92 px at 2 — which reads as the view swinging about somewhere off to the
      // side, and reads worst full screen, where the canvas is large enough to drag a
      // long way. This is the same reason the two-finger tilt captures `tiltAnchor` once.
      if (!orbitAnchor) {
        orbitAnchor = { x: event.clientX, y: event.clientY,
                        point: groundUnder(event.clientX, event.clientY) };
      }
      view.yaw += cssX * 0.005;
      view.pitch = Math.max(0.18, Math.min(1.45, view.pitch - cssY * 0.004));
      holdGround(orbitAnchor.point, orbitAnchor.x, orbitAnchor.y);
    } else {
      view.panX += dx;
      view.panY += dy;
    }
    draw();
  });

  function endPointer(event) {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) { pinch = null; twoFingerMode = null; tiltAnchor = null; }
    if (!pointers.size) {
      gesture = null;
      orbitAnchor = null;
      canvas.classList.remove('is-dragging');
    }
  }
  canvas.addEventListener('pointerup', endPointer);
  canvas.addEventListener('pointercancel', endPointer);
  canvas.addEventListener('pointerleave', endPointer);

  canvas.addEventListener('wheel', function (event) {
    event.preventDefault();
    moving();
    zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX, event.clientY);
    draw();
  }, { passive: false });

  function box() {
    var r = canvas.getBoundingClientRect();
    return { cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
  }

  // ---- the sun ---------------------------------------------------------------------
  //
  // The payload carries the whole day sampled every ten minutes rather than the
  // algorithm, so there is no second implementation of solar position to drift out of
  // step with `sun.py`. Interpolation between samples is linear and the azimuth arrives
  // unwrapped, so the light never sweeps the long way round the compass.
  //
  // There is no time control. The sun follows the **chart cursor**: hovering the
  // altitude trace at 14:40 lights the terrain as it was at 14:40, which is the question
  // a pilot is actually asking — was that face still in the sun when I got there. A
  // slider was the first attempt and it was the wrong instrument twice over: it offered
  // hours the flight never saw, and it made the reader hunt for a moment the charts were
  // already pointing at.
  var sunTrack = scene.sun || null;
  var sunMinute = sunTrack ? sunTrack.at : null;
  // The sun the shading was last built for. Re-lighting costs a pass over the grid, a
  // re-bake of the draped texture and a rebuild of the vertex colours, which is far too
  // much to do on every mousemove — so it only happens once the sun has actually moved
  // enough to see. A degree of azimuth is about a third of the width of the sun's own
  // disc on screen and four minutes of a summer afternoon.
  var appliedSun = null;
  var SUN_STEP_DEG = 1.0;

  function sunAt(minute) {
    var track = sunTrack.track;
    var span = track.az.length * track.step;
    var at = ((minute % span) + span) % span / track.step;
    var i = Math.floor(at), f = at - i;
    var j = (i + 1) % track.az.length;
    // The wrap at midnight is the one place the unwrapped azimuth has a real step in it;
    // ignore the fraction there rather than interpolate across a day boundary.
    if (j === 0) return { az: track.az[i], el: track.el[i] };
    return { az: track.az[i] + (track.az[j] - track.az[i]) * f,
             el: track.el[i] + (track.el[j] - track.el[i]) * f };
  }

  function clock(minute) {
    var local = ((Math.round(minute) + sunTrack.offset) % 1440 + 1440) % 1440;
    return String(Math.floor(local / 60)).padStart(2, '0') + ':' +
           String(local % 60).padStart(2, '0');
  }

  function compass(azimuth) {
    var names = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    return names[Math.round((((azimuth % 360) + 360) % 360) / 22.5) % 16];
  }

  // Rebuild the shading for wherever the sun is now. Everything that carries light has to
  // be redone: the lit range is measured against the light, the draped texture has the
  // hillshade baked into it, and the WebGL backend keeps its bare-relief shading in
  // vertex colours.
  function relight() {
    if (!sunTrack) return;
    var where = sunAt(sunMinute);
    appliedSun = where;
    setLight(where.az, where.el);
    measureLit();
    Object.keys(ready).forEach(function (name) {
      if (ready[name].image) ready[name].shaded = shadedTexture(ready[name].image,
                                                               ready[name].box);
    });
    if (style && ready[style]) basemap = ready[style].shaded || ready[style].image;
    if (renderer && renderer.relight) renderer.relight();
    sampleCellColours();
    draw();
  }

  // Move the sun to `minute`, re-lighting only when it has travelled far enough to be
  // worth the work. The arrow still reads the exact position, so it follows the cursor
  // smoothly while the shading catches up in steps nobody can see.
  function sunTo(minute) {
    if (!sunTrack || minute === null || minute === undefined) return;
    sunMinute = minute;
    var where = sunAt(minute);
    if (appliedSun) {
      var turned = Math.abs(((where.az - appliedSun.az + 540) % 360) - 180);
      if (turned < SUN_STEP_DEG && Math.abs(where.el - appliedSun.el) < SUN_STEP_DEG / 2) {
        draw();
        return;
      }
    }
    relight();
  }

  // The UTC minute a cursor sample sits at. The cursor track carries it per sample
  // rather than being interpolated from the flight's span: fixes are not evenly spaced
  // in time, and a KMZ from a scoring site is not evenly spaced at all.
  function cursorMinute(index) {
    if (!sunTrack || !cursorTrack || !cursorTrack.min) return null;
    if (index === null || index === undefined) return null;
    return cursorTrack.min[Math.min(index, cursorTrack.min.length - 1)];
  }

  if (sunTrack && sunTrack.track && sunTrack.track.az) relight();

  root.querySelectorAll('[data-view3d-act]').forEach(function (button) {
    button.addEventListener('click', function () {
      var act = button.dataset.view3dAct;
      moving();
      var centre = box();
      var buttonHold = ('rotate-left rotate-right tilt-up tilt-down'.indexOf(act) >= 0)
        ? groundUnder(centre.cx, centre.cy) : null;
      if (act === 'rotate-left') view.yaw -= 0.35;
      else if (act === 'rotate-right') view.yaw += 0.35;
      else if (act === 'tilt-up') view.pitch = Math.min(1.45, view.pitch + 0.15);
      else if (act === 'tilt-down') view.pitch = Math.max(0.18, view.pitch - 0.15);
      if (buttonHold) holdGround(buttonHold, centre.cx, centre.cy);
      else if (act === 'fullscreen') {
        toggleMaximise();
        return;   // the resize path redraws once the box has its new size
      }
      else if (act === 'zoom-in') zoomAt(1.25, box().cx, box().cy);
      else if (act === 'zoom-out') zoomAt(1 / 1.25, box().cx, box().cy);
      else if (act === 'exaggerate') {
        // True scale is the default because it is the only setting you can read height
        // above ground from. But a 90 km flight through 2 km of air is 2 % of its own
        // width, so the multiples are here for when the shape of the climbs matters
        // more than their absolute height.
        var ladder = [1, 2, 4];
        var at = ladder.indexOf(view.vertical);
        var next = ladder[(at + 1) % ladder.length];
        view.vertical = next;
        button.classList.toggle('is-on', next !== 1);
        button.innerHTML = '&#215;' + next + ' height';
      } else if (act === 'basemap') {
        // Every style the document can show, then bare relief, then round again — so a
        // document carrying one style degrades to a plain on/off toggle by itself.
        var cycle = order.concat(['off']);
        var at = cycle.indexOf(view.map ? style : 'off');
        setBasemapStyle(cycle[(at + 1) % cycle.length]);
      } else if (act === 'reset') {
        view.yaw = -0.42; view.pitch = 0.46; view.zoom = 1; view.vertical = baseVertical;
        view.panX = 0; view.panY = 0;
        if (order.length) setBasemapStyle(order[0]);
        root.querySelectorAll('[data-view3d-act="exaggerate"]').forEach(function (b) {
          b.classList.remove('is-on');
          b.innerHTML = '&#215;1 height';
        });
      }
      draw();
    });
  });

  // Full screen is the real Fullscreen API, with the in-page maximise as the fallback.
  //
  // The API is what a reader means by full screen — it takes the browser chrome with it
  // and the OS knows the window is presenting — and where the report is served from a
  // host it is granted. But it fails two ways at once inside an iframe without the
  // permission: `requestFullscreen` throws synchronously without a user activation, and
  // rejects without the permission. So the fallback is not decoration, it is the path a
  // published artifact takes, and it must be exercised. Both end in the same state as far
  // as everything else here is concerned — `panelIsFull()` is the one question asked.
  function panelIsFull(panel) {
    return panel.classList.contains('is-maximised') ||
           document.fullscreenElement === panel ||
           document.webkitFullscreenElement === panel;
  }

  // Percentage height on a canvas resolves against a parent whose own height is being
  // established in the same pass, and it did not settle before the redraw — the CSS box
  // read 100 % of the viewport while the backing store kept the aspect-ratio height. An
  // explicit pixel size removes the dependency entirely.
  // Measured from the panel, never from a global. Maximised or truly full screen, the
  // panel's own box *is* the space to fill, and it is the same box the GL canvas
  // underneath gets from `inset: 0` — two measurements that cannot disagree.
  // `document.documentElement.clientWidth/clientHeight` looked equivalent and is not:
  // in quirks mode clientHeight is the height of the whole *document*, so a report five
  // screens long maximised to a 4 316 px canvas inside an 813 px panel. The report has
  // a doctype now, but a viewer that renders it another way — an iframe, an email
  // client, a page that embeds the panel in something taller — must not be able to do
  // that again.
  function applyMaximisedSize() {
    var panel = canvas.closest('.view3d-panel');
    if (panelIsFull(panel)) {
      // clientWidth/clientHeight, not getBoundingClientRect: the panel keeps a 1 px
      // border top and bottom, and `inset: 0` on the GL canvas resolves against the
      // padding box. This is the same box, to the pixel.
      canvas.style.width = panel.clientWidth + 'px';
      canvas.style.height = panel.clientHeight + 'px';
    } else {
      canvas.style.width = '';
      canvas.style.height = '';
    }
  }

  // The new box is not measurable immediately, and one follow-up frame was not enough:
  // measured with __view3d.metrics(), the box read 713 px while the backing store was
  // still 508 until an explicit later redraw. A short ladder of redraws costs nothing on
  // a toggle and is not sensitive to how long layout takes. Real full screen needs it
  // more than the in-page path, not less: the box changes when the compositor says so.
  function settleSize() {
    applyMaximisedSize();
    view.panX = 0;
    view.panY = 0;
    [0, 80, 200, 500].forEach(function (delay) {
      setTimeout(function () { applyMaximisedSize(); resize(); draw(); }, delay);
    });
  }

  function maximiseInPage(panel) {
    panel.classList.add('is-maximised');
    settleSize();
  }

  function toggleMaximise() {
    var panel = canvas.closest('.view3d-panel');
    var full = document.fullscreenElement === panel ||
               document.webkitFullscreenElement === panel;
    if (full) {
      // Leaving is symmetrical, and the fullscreenchange handler does the resizing.
      (document.exitFullscreen || document.webkitExitFullscreen).call(document);
      return;
    }
    if (panel.classList.contains('is-maximised')) {
      panel.classList.remove('is-maximised');
      settleSize();
      return;
    }
    var request = panel.requestFullscreen || panel.webkitRequestFullscreen;
    if (!request) return maximiseInPage(panel);
    // Three ways this can fail and only one of them is a rejected promise: a synchronous
    // throw with no user activation, a rejection without the permission, and an older
    // implementation that returns undefined and simply does nothing. The check after a
    // tick catches the third, which no amount of promise handling would.
    try {
      var pending = request.call(panel);
      if (pending && pending.catch) pending.catch(function () { maximiseInPage(panel); });
    } catch (error) {
      return maximiseInPage(panel);
    }
    setTimeout(function () {
      if (!panelIsFull(panel)) maximiseInPage(panel);
    }, 120);
  }

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    var panel = canvas.closest('.view3d-panel');
    // Real full screen exits on Escape by itself, and taking the key from it would only
    // race the browser. This is the in-page path, which has nobody else to do it.
    if (panel.classList.contains('is-maximised')) toggleMaximise();
  });

  // Re-measure whenever the box changes: entering full screen, rotating a phone, or a
  // window drag all change it, and a stale backing store renders blurred or clipped.
  function refresh() {
    applyMaximisedSize();
    // Only the pan is reset here; the size itself is picked up by draw().
    var rect = canvas.getBoundingClientRect();
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    if (Math.round(rect.width * ratio) !== W || Math.round(rect.height * ratio) !== H) {
      view.panX = 0;
      view.panY = 0;
    }
    draw();
  }
  window.addEventListener('resize', refresh);
  // Entering or leaving real full screen is the same event either way, including the
  // browser's own Escape. `settleSize` rather than `refresh`: the screen-sized box is not
  // measurable in the frame the event arrives in, which is the whole reason for the
  // ladder. Both spellings, because Safari still fires only the prefixed one.
  ['fullscreenchange', 'webkitfullscreenchange'].forEach(function (name) {
    document.addEventListener(name, function () {
      if (canvas.closest('.view3d-panel')) settleSize();
    });
  });
  if (window.ResizeObserver) new ResizeObserver(refresh).observe(canvas);

  draw();
  var handle = {
    // The hover moves the sun as well as the marker: the reader points at a moment and
    // the ground is lit as it was then. `sunTo` decides whether that is worth a re-light
    // and draws either way, so this stays one call per hover.
    setCursor: function (index) {
      cursorIndex = index;
      var minute = cursorMinute(index);
      if (minute === null) { draw(); return; }
      sunTo(minute);
    },
    clearCursor: function () {
      cursorIndex = null;
      if (sunTrack) sunTo(sunTrack.at); else draw();
    },
    // Exposed for tests: driving the camera from a headless browser is the only way to
    // check that a gesture does what it claims.
    view: view,
    // Synchronous on purpose: a headless browser stops servicing requestAnimationFrame
    // once the page goes idle, so a test that scheduled a frame and then measured the
    // projection was reading numbers from before its own input. Every measurement of a
    // gesture was wrong in the same invisible way until this bypassed the scheduler.
    redraw: function () { paint(); },
    // Exposed for tests: what resize() actually measures, versus what it has stored.
    metrics: function () {
      var rect = canvas.getBoundingClientRect();
      return { W: W, H: H, boxW: rect.width, boxH: rect.height,
               ratio: Math.min(window.devicePixelRatio || 1, 2),
               attrW: canvas.width, attrH: canvas.height };
    },
    // Exposed for tests: the grid it is drawing, and the drape resolution in force. The
    // coarse-while-moving trick is a claim about frame cost, so both have to be measurable.
    grid: function () {
      var steps = texStep();
      return { cols: cols, rows: rows, interacting: interacting,
               cellCols: Math.round(cols / steps.c), cellRows: Math.round(rows / steps.r) };
    },
    setInteracting: function (on) { interacting = !!on; },
    // Exposed for tests: the ground-plane point under a screen position, and where a
    // ground point is on screen now. Rotating and tilting *about the fingers* is a claim
    // about exactly these two agreeing across a gesture.
    ground: function (clientX, clientY) { return groundUnder(clientX, clientY); },
    screenOfGround: function (point) {
      var box = canvas.getBoundingClientRect();
      var p = project(point[0], point[1], dem.min);
      return [p[0] / W * box.width, p[1] / H * box.height];
    },
    stats: function () {
      // A folded cell is an artefact of painter's order. Under a depth buffer there is
      // no such thing — the backend reports its own cell count and a folded count of
      // zero, and that difference is the whole point of it.
      return renderer ? renderer.stats() : { cells: stats.cells, folded: stats.folded };
    },
    // Exposed for tests: whether the WebGL backend took, and where it puts a world
    // point. The overlay track is drawn with project() on top of a heightfield drawn
    // from a matrix, so the two have to agree — any disagreement shows up as the track
    // floating above or sinking into the ground.
    gl: function () { return renderer ? renderer.info() : null; },
    glScreenOf: function (x, y, z) {
      return renderer ? renderer.screenOf(x, y, z) : null;
    },
    glDepthOf: function (x, y, z) {
      return renderer ? renderer.depthOf(x, y, z) : null;
    },
    // project() in canvas pixels for a world point, which is the unit glScreenOf
    // answers in. screenOf()/nearest() speak CSS pixels and track indices, so neither
    // can be held against the matrix directly.
    worldProject: function (x, y, z) { return project(x, y, z); },
    // Exposed for tests: the ground-plane point under a screen position. Every rotation
    // anchors through this, so "the twist is centred on the wrong place" is a claim
    // about it and cannot be checked without it.
    groundUnder: function (clientX, clientY) { return groundUnder(clientX, clientY); },
    // Exposed for tests: the sun and wind arrows as angles rather than as pixels.
    rose: function () { return roseAngles(); },
    toMetres: function (lon, lat) { return toMetres(lon, lat); },
    // Called when the flight this panel belongs to is removed from the document. The
    // DEM grid and the stitched basemap go with the handle, but a WebGL context does
    // not: a page gets about sixteen of them, so one has to be handed back explicitly.
    dispose: function () {
      if (renderer && renderer.dispose) renderer.dispose();
      renderer = null;
    },
    // Exposed for tests: the projection as it currently stands. Zoom anchoring is a
    // claim about these numbers, so the numbers have to be readable.
    projection: function () {
      return { dx: fit.dx, dy: fit.dy, scale: fit.scale, W: W, H: H,
               anchorX: anchorX(), anchorY: anchorY(),
               panX: view.panX, panY: view.panY, zoom: view.zoom };
    },
    // Exposed for tests: the track vertex nearest a screen point, and where a given
    // vertex is on screen now. Zoom anchoring is the claim that these two agree before
    // and after a wheel event, which is only checkable by measuring it.
    nearest: function (clientX, clientY) {
      var box = canvas.getBoundingClientRect();
      var sx = (clientX - box.left) / box.width * W;
      var sy = (clientY - box.top) / box.height * H;
      var t = scene.track, best = 0, bestD = Infinity;
      for (var i = 0; i < t.lon.length; i++) {
        var m = toMetres(t.lon[i], t.lat[i]);
        var p = project(m[0], m[1], t.alt[i]);
        var d = (p[0] - sx) * (p[0] - sx) + (p[1] - sy) * (p[1] - sy);
        if (d < bestD) { bestD = d; best = i; }
      }
      return best;
    },
    screenOf: function (index) {
      var box = canvas.getBoundingClientRect();
      var t = scene.track;
      var m = toMetres(t.lon[index], t.lat[index]);
      var p = project(m[0], m[1], t.alt[index]);
      return [p[0] / W * box.width, p[1] / H * box.height];
    },
    // Exposed for tests: which basemap the reader is looking at, and whether its tiles
    // actually arrived. A style that is selected but has no image is the failure the
    // toggle must not hide.
    basemap: function () {
      return { style: style, on: view.map, loading: loading,
               painted: !!basemap, cells: !!cellColour,
               isCanvas: !!(basemap && basemap.tagName === 'CANVAS'),
               cached: Object.keys(ready),
               credit: (root.querySelector('.view3d-credit') || {}).textContent };
    }
  };
  window.__view3d = handle;
  // A multi-flight document initialises one of these per tab, so the bare global is
  // whichever went last. Keyed by canvas id as well, so a test can address the panel it
  // is actually clicking on — driving one panel's button while reading another's numbers
  // produced a convincing false failure.
  window.__view3dAll = window.__view3dAll || {};
  window.__view3dAll[canvas.id] = handle;
  return handle;
}
"""

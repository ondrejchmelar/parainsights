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
  background: var(--ink); color: var(--paper); font-size: 12px; line-height: 1.35;
  padding: 5px 8px; border-radius: 3px; }
/* The map's own bar (`map3d`). A segmented group carries state, a bare button is a
   one-shot action. */
.view3d-controls { position: absolute; right: 10px; bottom: 10px; left: 10px; display: flex;
  gap: 5px; flex-wrap: wrap; justify-content: flex-end; }
.view3d-seg { display: flex; gap: 0; }
.view3d-seg button { border-radius: 0; }
.view3d-seg button + button { margin-left: -1px; }
.view3d-seg button:first-child { border-top-left-radius: 2px; border-bottom-left-radius: 2px; }
.view3d-seg button:last-child { border-top-right-radius: 2px; border-bottom-right-radius: 2px; }
.view3d-reset { font-size: 15px; line-height: 1; }
/* On a phone the bar is one row, and its targets grow rather than shrink: the zoom pair,
   reset and the phase labels go (pinch, the compass and a 295 px map have no room). */
@media (max-width: 640px) {
  .view3d-controls { gap: 4px; flex-wrap: nowrap; }
  .view3d-controls button { padding: 8px 10px; font-size: 12px; }
  .view3d-zoom { display: none; }
  .view3d-reset { display: none; }
  .view3d-labels { display: none; }
}
/* The stack, stated: the controls, then the help list over them, because it is the one
   overlay a reader opens deliberately. */
.view3d-controls { z-index: 3; }
.view3d-keys { z-index: 4; }
.view3d-keys {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  background: var(--panel);
  border: 1px solid var(--rule-strong);
  padding: 14px 18px;
  border-radius: 3px;
  font-size: 12px;
  /* The panel clips its overflow, so a list taller than the map would lose its first
     rows off the top. Capped to the box and scrolled instead. */
  max-height: calc(100% - 20px);
  max-width: calc(100% - 20px);
  overflow: auto;
  box-sizing: border-box;
  cursor: pointer;
}
.view3d-keys dl {
  margin: 0;
  display: grid;
  grid-template-columns: auto auto;
  gap: 4px 16px;
}
.view3d-keys-head { margin: 0 0 5px; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--ink-3); }
.view3d-keys dl + .view3d-keys-head { margin-top: 11px; }
.view3d-keys-foot { margin: 11px 0 0; font-size: 11px; color: var(--ink-3); }
/* `shift + <- ->` is one key combination; wrapped, it read as two bindings. */
.view3d-keys dt { color: var(--ink); font-family: ui-monospace, monospace;
  white-space: nowrap; }
.view3d-keys dd { margin: 0; color: var(--ink-2); }
.view3d-keys[hidden] { display: none; }
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


// ---- terrain fetched by the page ---------------------------------------------------
//
// A scene may carry its terrain as `terrain.remote` — the box, the grid and the tile
// source, no heights — rather than as the heights themselves (`terrain.remote()` in
// Python). The page then fetches the same terrarium tiles at the same zoom and samples
// them onto the same nodes `terrain.fetch` would have: nearest pixel, a missing tile
// filled with the lowest height found, heights rounded to the metre. It is one grid built
// in two places, and everything downstream of `dem` cannot tell which — so the arithmetic
// is Python's, operation for operation: `math.radians` is lat × (π/180), numpy's
// linspace is start + i × step, `np.round` rounds a half to even, and the bounds are the
// unrounded heights'. A test builds both from the same tiles and compares every node.
function loadTerrain(dem) {
  var zoom = dem.remote.zoom, n = Math.pow(2, zoom), size = 256;
  function tileX(lon) { return (lon + 180) / 360 * n; }
  function tileY(lat) {
    var rad = lat * (Math.PI / 180);
    return (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2 * n;
  }
  var x0 = Math.floor(tileX(dem.west)), x1 = Math.floor(tileX(dem.east));
  var y0 = Math.floor(tileY(dem.north)), y1 = Math.floor(tileY(dem.south));
  var width = (x1 - x0 + 1) * size, height = (y1 - y0 + 1) * size;
  var mosaic = new Float64Array(width * height).fill(NaN);
  var scratch = document.createElement('canvas');
  scratch.width = scratch.height = size;
  var sctx = scratch.getContext('2d', { willReadFrequently: true });

  function tile(x, y) {
    return new Promise(function (resolve) {
      var image = new Image();
      image.crossOrigin = 'anonymous';
      image.onload = function () {
        sctx.clearRect(0, 0, size, size);
        sctx.drawImage(image, 0, 0);
        var px = sctx.getImageData(0, 0, size, size).data;
        var ox = (x - x0) * size, oy = (y - y0) * size;
        for (var r = 0; r < size; r++) {
          for (var c = 0; c < size; c++) {
            var k = (r * size + c) * 4;
            mosaic[(oy + r) * width + ox + c] =
              px[k] * 256 + px[k + 1] + px[k + 2] / 256 - 32768;
          }
        }
        resolve(true);
      };
      // A missing tile is a hole to fill, not a failure: the Python side does the same.
      // But a tile is asked again twice first, a moment apart: every tile of a page has
      // been seen to fail at once and succeed on reload, which with no retry is a 3D view
      // that never appears.
      var tries = 0;
      var src = dem.remote.url.replace('{z}', zoom).replace('{x}', x).replace('{y}', y);
      image.onerror = function () {
        if (++tries > 2) { resolve(false); return; }
        setTimeout(function () { image.src = src + (src.indexOf('?') < 0 ? '?' : '&') + 'r=' + tries; },
                   400 * tries);
      };
      image.src = src;
    });
  }

  var wanted = [];
  for (var ty = y0; ty <= y1; ty++) for (var tx = x0; tx <= x1; tx++) wanted.push(tile(tx, ty));
  return Promise.all(wanted).then(function (got) {
    if (got.indexOf(true) < 0) throw new Error('no elevation tile could be fetched');
    var low = Infinity;
    for (var i = 0; i < mosaic.length; i++) if (mosaic[i] < low) low = mosaic[i];
    function linspace(start, stop, count, i) {
      if (count < 2) return start;
      return i === count - 1 ? stop : i * ((stop - start) / (count - 1)) + start;
    }
    function roundHalfEven(value) {
      var down = Math.floor(value), rest = value - down;
      if (rest !== 0.5) return Math.round(value);
      return down % 2 === 0 ? down : down + 1;
    }
    var z = new Array(dem.rows * dem.cols), min = Infinity, max = -Infinity;
    for (var r = 0; r < dem.rows; r++) {
      // np.linspace(north, south, rows) and (west, east, cols), then truncated to a pixel
      // and clipped — `terrain.fetch`, step for step.
      var lat = linspace(dem.north, dem.south, dem.rows, r);
      var py = Math.min(Math.max(Math.floor((tileY(lat) - y0) * size), 0), height - 1);
      for (var c = 0; c < dem.cols; c++) {
        var lon = linspace(dem.west, dem.east, dem.cols, c);
        var px = Math.min(Math.max(Math.floor((tileX(lon) - x0) * size), 0), width - 1);
        var value = mosaic[py * width + px];
        if (value !== value) value = low;
        if (value < min) min = value;
        if (value > max) max = value;
        z[r * dem.cols + c] = roundHalfEven(value);
      }
    }
    dem.z = z;
    dem.min = Math.floor(min);
    dem.max = Math.ceil(max);
    return dem;
  });
}

// A scene as the page carries it, parsed and decoded. The track (every fix) and the
// airspace rings are delta-encoded where they are written (`js/scene.js`,
// `airspaces.scene.rings`): each value the difference from the one before, in steps of
// 1/`enc` for coordinates. Decoded here, once, so everything else reads plain arrays.
function readScene(node) {
  var scene = JSON.parse(node.textContent);
  function run(steps, scale) {
    var out = new Array(steps.length), total = 0;
    for (var i = 0; i < steps.length; i++) { total += steps[i]; out[i] = scale ? total / scale : total; }
    return out;
  }
  var t = scene.track;
  if (t && t.enc) {
    t.lon = run(t.lon, t.enc); t.lat = run(t.lat, t.enc);
    t.alt = run(t.alt); if (t.t) t.t = run(t.t);
    delete t.enc;
  }
  (scene.airspaces || []).forEach(function (ring) {
    if (!ring.enc) return;
    ring.lon = run(ring.lon, ring.enc); ring.lat = run(ring.lat, ring.enc);
    delete ring.enc;
  });
  return scene;
}

// The airspace under a flight's ground, from the layer files `airspaces/openaip.py` writes
// beside the Planner: the index once per page, then only the files whose box reaches this
// one, each fetched and decoded once however many flights share it. Never rejects — a
// map without its airspace is still a map — and fills `scene.airspaces` in place, before
// the views are built from the scene. Then the switch: enabled, or disabled saying why.
var airspaceFiles = {};
function airspaceJson(url) {
  if (!airspaceFiles[url]) {
    airspaceFiles[url] = fetch(url).then(function (response) {
      if (!response.ok) throw new Error(response.status + ' ' + url);
      return response.json();
    });
    airspaceFiles[url].catch(function () { delete airspaceFiles[url]; });
  }
  return airspaceFiles[url];
}
function loadAirspace(root, scene) {
  var href = scene.airspaceRemote, dem = scene.terrain;
  if (!href || !dem || typeof fetch !== 'function') return Promise.resolve();
  function overlaps(b) {
    return b && !(b[1] < dem.west || b[0] > dem.east || b[3] < dem.south || b[2] > dem.north);
  }
  function decode(ring) {
    if (!ring.enc) return ring;
    var lon = [], lat = [], x = 0, y = 0;
    for (var i = 0; i < ring.lon.length; i++) {
      x += ring.lon[i]; y += ring.lat[i];
      lon.push(x / ring.enc); lat.push(y / ring.enc);
    }
    var out = {};
    Object.keys(ring).forEach(function (k) { if (k !== 'enc') out[k] = ring[k]; });
    out.lon = lon; out.lat = lat;
    return out;
  }
  var credits = [];
  var found = airspaceJson(href + 'index.json').then(function (index) {
    scene.airspaceColours = index.colours || {};
    var names = Object.keys(index.files || {}).filter(function (name) {
      return overlaps(index.files[name].bbox);
    });
    return Promise.all(names.map(function (name) {
      return airspaceJson(href + name).then(function (file) {
        if (!file.decoded) file.decoded = (file.airspaces || []).map(decode);
        var near = file.decoded.filter(function (ring) {
          var w = Math.min.apply(null, ring.lon), e = Math.max.apply(null, ring.lon);
          var s = Math.min.apply(null, ring.lat), n = Math.max.apply(null, ring.lat);
          return !(e < dem.west || w > dem.east || n < dem.south || s > dem.north);
        });
        if (near.length && index.files[name].credit && credits.indexOf(index.files[name].credit) < 0) {
          credits.push(index.files[name].credit);
        }
        return near;
      }, function () { return []; });
    }));
  }).then(function (parts) {
    // Back to front across files as within one: the biggest first, so the smallest thing
    // under the pointer is the one hovered (`airspaces.scene.rings`).
    function size(ring) {
      return (Math.max.apply(null, ring.lon) - Math.min.apply(null, ring.lon)) *
             (Math.max.apply(null, ring.lat) - Math.min.apply(null, ring.lat));
    }
    scene.airspaces = [].concat.apply([], parts).sort(function (a, b) { return size(b) - size(a); });
    scene.airspaceCredit = credits.join(' · ');
  }, function () { scene.airspaces = []; scene.airspaceFailed = true; });
  return found;
}

// What a flight's map draws of the airspace it loaded: only what the flight had to do
// with. Two cuts, both the pilot's (October 2026), and zones openAIP marks as active only
// by NOTAM go too. Kinds that bind nobody — danger and
// firing areas, sport and aerobatic boxes, alert and warning areas, gliding sectors — are
// not drawn; protected areas and parks are, because they do bind. And of the rest, only
// zones the track came within 5 km of sideways and 200 m of vertically: the ground box a
// flight's map covers holds a hundred zones in the Alps, and an aerobatic box or a firing
// range the flight never went near is clutter on a map about this flight. Run after the
// terrain is in, because a limit measured from the ground needs the ground.
var NON_BINDING = /^(D|Sport|Alert|Warning|Gliding)$/;
var NEAR_SIDEWAYS = 5000, NEAR_VERTICALLY = 200;
function relevantAirspace(scene) {
  var tr = scene.track, dem = scene.terrain || {};
  var all = scene.airspaces || [];
  scene.airspaceLoaded = all.length;
  if (!tr || !tr.lon || tr.lon.length < 2 || !all.length) return;
  var step = Math.max(1, Math.floor(tr.lon.length / 2000)), fixes = [];
  for (var i = 0; i < tr.lon.length; i += step) fixes.push([tr.lon[i], tr.lat[i], tr.alt[i]]);
  function ground(lon, lat) {
    if (!dem.z || !dem.rows) return dem.min || 0;
    var gx = Math.max(0, Math.min(dem.cols - 1, (lon - dem.west) / (dem.east - dem.west) * (dem.cols - 1)));
    var gy = Math.max(0, Math.min(dem.rows - 1, (dem.north - lat) / (dem.north - dem.south) * (dem.rows - 1)));
    return dem.z[Math.round(gy) * dem.cols + Math.round(gx)];
  }
  function sideways(ring, p) {
    // Metres from the fix to the ring: 0 inside, else to the nearest edge.
    var kx = 111320 * Math.cos(p[1] * Math.PI / 180), ky = 111320, inside = false, best = Infinity;
    var n = ring.lon.length;
    for (var a = 0, b = n - 1; a < n; b = a++) {
      var ax = (ring.lon[a] - p[0]) * kx, ay = (ring.lat[a] - p[1]) * ky;
      var bx = (ring.lon[b] - p[0]) * kx, by = (ring.lat[b] - p[1]) * ky;
      if ((ay > 0) !== (by > 0) && 0 < (bx - ax) * (0 - ay) / (by - ay) + ax) inside = !inside;
      var dx = bx - ax, dy = by - ay, len = dx * dx + dy * dy;
      var t = len ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len)) : 0;
      best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
    }
    return inside ? 0 : best;
  }
  scene.airspaces = all.filter(function (ring) {
    if (ring.ac && NON_BINDING.test(ring.ac)) return false;
    if (ring.nt) return false;     // active only by NOTAM: the file cannot know if it is
    var mx = NEAR_SIDEWAYS / (111320 * Math.cos(ring.lat[0] * Math.PI / 180)), my = NEAR_SIDEWAYS / 111320;
    var w = Math.min.apply(null, ring.lon) - mx, e = Math.max.apply(null, ring.lon) + mx;
    var s = Math.min.apply(null, ring.lat) - my, n = Math.max.apply(null, ring.lat) + my;
    for (var k = 0; k < fixes.length; k++) {
      var p = fixes[k];
      if (p[0] < w || p[0] > e || p[1] < s || p[1] > n) continue;
      if (sideways(ring, p) > NEAR_SIDEWAYS) continue;
      var g = ground(p[0], p[1]);
      var floor = ring.g ? g : (ring.fu !== undefined ? g + ring.fu : ring.f);
      var top = ring.t ? Infinity : (ring.cu !== undefined ? g + ring.cu : ring.c);
      if (p[2] >= floor - NEAR_VERTICALLY && p[2] <= top + NEAR_VERTICALLY) return true;
    }
    return false;
  });
}

// What the map's airspace switch says once the airspace is settled (`scene.airspaceWhy`):
// what it draws, with the credit, or why there is nothing to draw.
function settleAirspace(root, scene) {
  if (!scene.airspaceRemote) return;
  relevantAirspace(scene);
  scene.airspaceWhy = scene.airspaces.length
    ? 'Draw the airspace this flight came near' + (scene.airspaceCredit ? ' (' + scene.airspaceCredit + ')' : '')
    : scene.airspaceFailed ? 'The airspace could not be loaded'
    : scene.airspaceLoaded ? 'No binding airspace within 5 km and 200 m of this flight'
    : 'No airspace data under this flight — the layers cover Europe';
}

// The scene a panel carries, completed: the ground fetched where it was left to the page,
// the airspace loaded and settled. Resolves with the panel's handle, or null where there
// is no panel. Never rejects: ground that could not be fetched leaves a map whose
// heights come from MapLibre's own terrain, which is still a map.
function initView3dWhenReady(root, cursorTrack) {
  var payload = root.querySelector('.view3d-data');
  if (!payload) return Promise.resolve(null);
  var scene = readScene(payload);
  var dem = scene.terrain;
  var airspace = loadAirspace(root, scene);
  if (!dem || !dem.remote || dem.z) {
    return airspace.then(function () {
      settleAirspace(root, scene);
      return initView3d(root, cursorTrack, scene);
    });
  }
  var ground = loadTerrain(dem).then(null, function (error) {
    dem.failed = error.message;
  });
  return Promise.all([ground, airspace]).then(function () {
    settleAirspace(root, scene);
    return initView3d(root, cursorTrack, scene);
  });
}

// The handle a panel is driven through: what the map draws (`built`), the ground under a
// point, the linked cursor and the airspace filter. The map (`map3d`) wraps the cursor
// and filter members, which is how a chart hover or a table row reaches it; here they
// only remember.
function initView3d(root, cursorTrack, preset) {
  var box = root.querySelector('.view3d');
  var payload = root.querySelector('.view3d-data');
  if (!box || !payload) return null;
  var scene = preset || readScene(payload);
  // A scene need not carry a flight. The airspace map is the same widget over the same
  // terrain with no track in it, so the flight-shaped members are defaulted here once.
  if (!scene.track) scene.track = { lon: [], lat: [], alt: [], c: [] };
  if (!scene.climbs) scene.climbs = [];
  if (!scene.palette) scene.palette = [[120, 120, 120]];
  var dem = scene.terrain || {};
  var cursorIndex = null, airspaceFilter = null;
  // Bilinear over the grid; null where there is no grid (it could not be fetched).
  function groundAt(lon, lat) {
    if (!dem.z || !dem.rows) return null;
    var cols = dem.cols, rows = dem.rows;
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
  var handle = {
    built: { scene: scene, cursorTrack: cursorTrack || null },
    scene: function () { return scene; },
    groundAt: groundAt,
    setCursor: function (index) { cursorIndex = index; },
    revealCursor: function (index) { cursorIndex = index; return false; },
    clearCursor: function () { cursorIndex = null; },
    cursor: function () { return cursorIndex; },
    setAirspaceFilter: function (fn) { airspaceFilter = fn || null; },
    airspaceFilter: function () { return airspaceFilter; },
    redraw: function () {},
    dispose: function () {}
  };
  window.__view3d = handle;
  // A multi-flight document builds one of these per tab, so the bare global is whichever
  // went last; keyed by the box's id as well, which is how the map and the tests find it.
  window.__view3dAll = window.__view3dAll || {};
  window.__view3dAll[box.id] = handle;
  return handle;
}
"""

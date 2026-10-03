"""Interactive 3D map: the track at true altitude over real terrain.

This is the renderer that cannot be an embedded artifact. It needs a map library
and terrain tiles at view time, and a strict content-security policy blocks both —
which is exactly why the SVG report in ``render_html`` exists alongside it. Open
the file this writes in an ordinary browser.

Nothing here needs an API key:

* basemap        OpenStreetMap raster tiles
* terrain        AWS Open Data terrarium DEM (``elevation-tiles-prod``)
* map library    MapLibre GL JS
* 3D track       deck.gl ``PathLayer`` and ``TripsLayer``, in altitude-aware mode

The flight is embedded as JSON, so the page is one file plus those network
dependencies — no sidecar data to keep next to it.
"""

import json
from pathlib import Path

import numpy as np

from .analysis import Analysis, Phase
from .charts import CLIMB_RAMP, decimate

MAPLIBRE = "https://unpkg.com/maplibre-gl@4.7.1/dist"
DECK = "https://unpkg.com/deck.gl@9.0.35/dist.min.js"
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

# Literal colours, not CSS variables: deck.gl takes RGB arrays, and the ramp has to
# match the SVG report's climb colours so the two views read as one tool.
RAMP_RGB = [
    (-4.0, [23, 80, 143]),
    (-2.0, [42, 120, 214]),
    (-0.7, [143, 182, 230]),
    (0.7, [169, 164, 154]),
    (2.0, [240, 160, 122]),
    (4.0, [235, 104, 52]),
    (float("inf"), [200, 67, 26]),
]


def climb_rgb(value: float) -> list[int]:
    for threshold, colour in RAMP_RGB:
        if value < threshold:
            return colour
    return RAMP_RGB[-1][1]


def _track_payload(analysis: Analysis) -> dict:
    """The flight as coloured 3D path segments plus timed points for the animation."""
    flight = analysis.flight
    series = analysis.series
    # Decimate against horizontal position and altitude together, in metres, so the
    # simplification cannot flatten a thermal into a straight line.
    keep = decimate(series.x, series.y, 3.0)
    keep = np.union1d(keep, decimate(series.t, series.alt, 2.0))

    # Use GPS altitude for the map: the terrain is geometric, and a pressure
    # altitude offset by the day's QNH would float or sink the whole track.
    altitude = flight.alt_gps if np.any(flight.alt_gps) else series.alt

    segments = []
    current_colour = climb_rgb(float(series.climb[keep[0]]))
    run: list[list[float]] = []
    for index in keep:
        colour = climb_rgb(float(series.climb[index]))
        point = [
            round(float(flight.lon[index]), 6),
            round(float(flight.lat[index]), 6),
            round(float(altitude[index]), 1),
        ]
        run.append(point)
        if colour != current_colour:
            if len(run) > 1:
                segments.append({"path": run, "colour": current_colour})
            run = [point]
            current_colour = colour
    if len(run) > 1:
        segments.append({"path": run, "colour": current_colour})

    trip = [
        [
            round(float(flight.lon[i]), 6),
            round(float(flight.lat[i]), 6),
            round(float(altitude[i]), 1),
            round(float(series.t[i]), 1),
        ]
        for i in keep
    ]

    climbs = []
    number = 0
    for segment in analysis.segments:
        if segment.phase not in (Phase.THERMAL, Phase.TOW):
            continue
        middle = (segment.start + segment.stop) // 2
        if segment.phase is Phase.TOW:
            label = "tow"
        else:
            number += 1
            label = f"climb {number}"
        climbs.append(
            {
                "label": label,
                "lon": round(float(flight.lon[middle]), 6),
                "lat": round(float(flight.lat[middle]), 6),
                "altitude": round(float(altitude[middle]), 1),
                "gain": segment.altitude_change,
                "climb": segment.average_climb,
                "turns": segment.turns,
                "time": segment.start_time,
                "tow": segment.phase is Phase.TOW,
            }
        )

    return {
        "segments": segments,
        "trip": trip,
        "climbs": climbs,
        "duration": float(series.t[-1]),
        "bounds": {
            "west": round(float(flight.lon.min()), 6),
            "east": round(float(flight.lon.max()), 6),
            "south": round(float(flight.lat.min()), 6),
            "north": round(float(flight.lat.max()), 6),
        },
        "centre": [
            round(float((flight.lon.min() + flight.lon.max()) / 2), 6),
            round(float((flight.lat.min() + flight.lat.max()) / 2), 6),
        ],
    }


def _route_payload(route) -> list[dict]:
    if route is None or len(route.points) < 2:
        return []
    return [
        {
            "path": [[a.lon, a.lat], [b.lon, b.lat]],
        }
        for a, b in zip(route.points, route.points[1:])
    ]


STYLE = """
html, body { margin: 0; height: 100%; background: #0d1013; color: #eef1f4;
  font-family: ui-sans-serif, system-ui, "DejaVu Sans", sans-serif; }
#map { position: absolute; inset: 0; }
.hud {
  position: absolute; top: 14px; left: 14px; z-index: 2; max-width: 330px;
  background: rgba(13, 16, 19, 0.88); border: 1px solid #2b323b; border-radius: 3px;
  padding: 13px 15px 15px; backdrop-filter: blur(3px);
}
.hud h1 { margin: 0 0 2px; font-size: 17px; font-weight: 500; }
.hud .sub { color: #a3adb8; font-size: 12.5px; margin-bottom: 11px; }
.hud .row { display: flex; justify-content: space-between; gap: 12px; font-size: 12.5px;
  padding: 2px 0; }
.hud .row span:last-child { font-variant-numeric: tabular-nums; }
.hud label { display: block; font-size: 10.5px; text-transform: uppercase;
  letter-spacing: 0.1em; color: #737d88; margin: 12px 0 4px; }
.hud input[type=range] { width: 100%; accent-color: #eb6834; }
.controls { display: flex; gap: 7px; margin-top: 9px; }
.controls button {
  flex: 1; font: inherit; font-size: 12px; padding: 5px 8px; cursor: pointer;
  background: #171b21; color: #eef1f4; border: 1px solid #414a55; border-radius: 2px;
}
.controls button:hover { background: #1e232a; }
.controls button.is-on { background: #eb6834; border-color: #eb6834; color: #14171c; }
.ramp { display: flex; gap: 2px; margin-top: 10px; }
.ramp i { flex: 1; height: 8px; border-radius: 1px; }
.ramp-labels { display: flex; justify-content: space-between; font-size: 10px;
  color: #737d88; margin-top: 3px; }
.note { font-size: 11.5px; color: #737d88; margin-top: 12px; line-height: 1.45; }
.maplibregl-popup-content { background: #171b21; color: #eef1f4; font-size: 12.5px;
  border: 1px solid #414a55; }
.maplibregl-popup-tip { border-top-color: #414a55 !important; }
"""


def render(analysis: Analysis, *, route=None) -> str:
    """Build the 3D map page."""
    summary = analysis.summary
    payload = _track_payload(analysis)
    payload["route"] = _route_payload(route)

    ramp = "".join(
        f'<i style="background: rgb({r},{g},{b})"></i>' for _, (r, g, b) in RAMP_RGB
    )
    rows = [
        ("Airtime", f"{summary.duration // 3600} h {summary.duration % 3600 // 60:02d} m"),
        ("Flown", f"{summary.track_distance / 1000:.1f} km"),
        ("Max altitude", f"{summary.max_altitude + (summary.baro_offset or 0):,.0f} m".replace(",", " ")),
        ("Climbs", str(len(analysis.thermals))),
    ]
    if route:
        rows.insert(1, ("XC distance", f"{route.km:.1f} km"))
    row_html = "".join(
        f'<div class="row"><span>{label}</span><span>{value}</span></div>'
        for label, value in rows
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{summary.date} · {summary.site or "flight"} — 3D</title>
<link rel="stylesheet" href="{MAPLIBRE}/maplibre-gl.css">
<style>{STYLE}</style>
</head>
<body>
<div id="map"></div>
<div class="hud">
  <h1>{summary.site or "Flight"} <span style="color:#737d88">{summary.date}</span></h1>
  <div class="sub">{summary.pilot or ""}{" · " if summary.pilot else ""}{summary.glider or ""}</div>
  {row_html}
  <label for="time">Replay</label>
  <input type="range" id="time" min="0" max="{payload["duration"]:.0f}"
         value="{payload["duration"]:.0f}" step="1">
  <div class="controls">
    <button type="button" id="play">Play</button>
    <button type="button" id="whole" class="is-on">Whole track</button>
    <button type="button" id="terrain" class="is-on">Terrain</button>
  </div>
  <div class="ramp">{ramp}</div>
  <div class="ramp-labels"><span>&minus;4 m/s</span><span>climb</span><span>+4 m/s</span></div>
  <div class="note">Right-drag to tilt and rotate. Terrain is the AWS terrarium DEM;
    basemap &copy; OpenStreetMap contributors.</div>
</div>

<script src="{MAPLIBRE}/maplibre-gl.js"></script>
<script src="{DECK}"></script>
<script>
const FLIGHT = {json.dumps(payload)};

const map = new maplibregl.Map({{
  container: 'map',
  center: FLIGHT.centre,
  zoom: 9.5,
  pitch: 62,
  bearing: 15,
  maxPitch: 85,
  style: {{
    version: 8,
    sources: {{
      osm: {{
        type: 'raster',
        tiles: ['{OSM}'],
        tileSize: 256,
        maxzoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }},
      dem: {{
        type: 'raster-dem',
        tiles: ['{TERRARIUM}'],
        tileSize: 256,
        maxzoom: 15,
        encoding: 'terrarium',
        attribution: 'AWS Open Data Terrain Tiles'
      }}
    }},
    layers: [
      {{ id: 'osm', type: 'raster', source: 'osm', paint: {{ 'raster-opacity': 0.85 }} }},
      {{ id: 'hillshade', type: 'hillshade', source: 'dem',
         paint: {{ 'hillshade-exaggeration': 0.4 }} }}
    ],
    terrain: {{ source: 'dem', exaggeration: 1.0 }},
    sky: {{}}
  }}
}});
map.addControl(new maplibregl.NavigationControl({{ visualizePitch: true }}), 'top-right');
map.addControl(new maplibregl.ScaleControl({{ unit: 'metric' }}), 'bottom-right');

let cutoff = FLIGHT.duration;
let showWhole = true;
let playing = false;
let overlay = null;

function pathLayers() {{
  const layers = [];
  if (FLIGHT.route.length) {{
    layers.push(new deck.PathLayer({{
      id: 'xc-route',
      data: FLIGHT.route,
      getPath: d => d.path,
      getColor: [140, 148, 158, 190],
      getWidth: 2,
      widthUnits: 'pixels',
      billboard: false
    }}));
  }}
  if (showWhole) {{
    layers.push(new deck.PathLayer({{
      id: 'track',
      data: FLIGHT.segments,
      getPath: d => d.path,
      getColor: d => d.colour,
      getWidth: 3.2,
      widthUnits: 'pixels',
      billboard: true,
      capRounded: true,
      jointRounded: true
    }}));
  }}
  layers.push(new deck.TripsLayer({{
    id: 'replay',
    data: [{{ waypoints: FLIGHT.trip }}],
    getPath: d => d.waypoints.map(p => [p[0], p[1], p[2]]),
    getTimestamps: d => d.waypoints.map(p => p[3]),
    getColor: [255, 255, 255],
    widthUnits: 'pixels',
    getWidth: 4,
    trailLength: 420,
    currentTime: cutoff,
    capRounded: true,
    jointRounded: true
  }}));
  layers.push(new deck.ScatterplotLayer({{
    id: 'climbs',
    data: FLIGHT.climbs,
    getPosition: d => [d.lon, d.lat, d.altitude],
    getFillColor: d => (d.tow ? [27, 175, 122] : [235, 104, 52]),
    getLineColor: [255, 255, 255, 210],
    lineWidthMinPixels: 1.5,
    stroked: true,
    radiusUnits: 'pixels',
    getRadius: 6,
    pickable: true
  }}));
  return layers;
}}

function refresh() {{
  if (overlay) overlay.setProps({{ layers: pathLayers() }});
}}

// Added immediately rather than inside a 'load' handler. With terrain in the style,
// MapLibre can leave the style reporting unloaded while tiles stream in, and 'load'
// then never fires — which silently costs you every deck.gl layer. Non-interleaved
// mode also draws on deck's own canvas, so it does not need the map's GL context to
// be ready. The trade is that the track is not occluded by hills, which barely
// matters for a line that is above the ground by definition.
function start() {{
  overlay = new deck.MapboxOverlay({{
    interleaved: false,
    layers: pathLayers(),
    getTooltip: ({{ object }}) => object && object.label && {{
      html: '<b>' + object.label + '</b><br>' + object.time + '<br>' +
            (object.gain > 0 ? '+' : '') + object.gain + ' m at ' + object.climb +
            ' m/s' + (object.turns ? '<br>' + object.turns + ' turns' : ''),
      style: {{ background: '#171b21', color: '#eef1f4', border: '1px solid #414a55',
               fontSize: '12px', padding: '7px 9px' }}
    }}
  }});
  map.addControl(overlay);

  map.fitBounds(
    [[FLIGHT.bounds.west, FLIGHT.bounds.south], [FLIGHT.bounds.east, FLIGHT.bounds.north]],
    {{ padding: 90, pitch: 62, bearing: 15, duration: 0 }}
  );
}}
start();

const slider = document.getElementById('time');
slider.addEventListener('input', () => {{
  cutoff = Number(slider.value);
  refresh();
}});

const playButton = document.getElementById('play');
let frame = null;
function step() {{
  cutoff += FLIGHT.duration / 900;
  if (cutoff > FLIGHT.duration) cutoff = 0;
  slider.value = cutoff;
  refresh();
  if (playing) frame = requestAnimationFrame(step);
}}
playButton.addEventListener('click', () => {{
  playing = !playing;
  playButton.classList.toggle('is-on', playing);
  playButton.textContent = playing ? 'Pause' : 'Play';
  if (playing) frame = requestAnimationFrame(step);
  else if (frame) cancelAnimationFrame(frame);
}});

const wholeButton = document.getElementById('whole');
wholeButton.addEventListener('click', () => {{
  showWhole = !showWhole;
  wholeButton.classList.toggle('is-on', showWhole);
  refresh();
}});

const terrainButton = document.getElementById('terrain');
let terrainOn = true;
terrainButton.addEventListener('click', () => {{
  terrainOn = !terrainOn;
  terrainButton.classList.toggle('is-on', terrainOn);
  map.setTerrain(terrainOn ? {{ source: 'dem', exaggeration: 1.0 }} : null);
}});
</script>
</body>
</html>
"""


def write(analysis: Analysis, path, *, route=None) -> Path:
    path = Path(path)
    path.write_text(render(analysis, route=route), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------
# The same map as a second renderer inside the report, behind a switch.
#
# It draws from the scene the canvas view was built from (`handle.built`) rather than from
# a payload of its own, so a flight bundled in the report and a track the reader uploads
# get it alike, and the two renderers cannot be showing different flights. It follows the
# same linked cursor by wrapping the canvas handle's `setCursor` / `revealCursor` /
# `clearCursor`, which is the one place every chart and table row already calls.
#
# Nothing is fetched until the reader asks for it: MapLibre and deck.gl are ~1.4 MB, and
# the canvas view is still what the report opens on.
# ---------------------------------------------------------------------------------------

def switch_html() -> str:
    """The renderer switch that goes above a `view3d.panel` inside a `.renderer-host`."""
    return (
        '<div class="toggle renderer-switch" role="group" aria-label="3D renderer">'
        '<button type="button" class="toggle-button is-on" data-renderer="canvas"'
        ' aria-pressed="true">canvas</button>'
        '<button type="button" class="toggle-button" data-renderer="maplibre"'
        ' aria-pressed="false">MapLibre</button>'
        '<button type="button" class="toggle-button" data-renderer="merged"'
        ' aria-pressed="false">merged</button>'
        "</div>"
    )


SWITCH_STYLE = """
.renderer-switch { margin-bottom: 8px; }
.maplibre-view { position: absolute; inset: 0; z-index: 30; background: var(--panel); }
.maplibre-view .ml-map { position: absolute; inset: 0; }
.maplibre-view .ml-status { position: absolute; left: 12px; top: 10px; z-index: 2;
  font-size: 12px; color: var(--ink-2, var(--ink)); }
.maplibre-view .ml-replay { position: absolute; left: 10px; right: 10px; bottom: 10px; z-index: 2;
  display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.maplibre-view .ml-replay button { font: inherit; font-size: 12px; padding: 5px 9px;
  cursor: pointer; background: var(--panel); color: var(--ink);
  border: 1px solid var(--rule, #414a55); border-radius: 2px; }
.maplibre-view .ml-replay button.is-on { background: var(--climb); border-color: var(--climb);
  color: var(--paper, #14171c); }
.maplibre-view .ml-slider { flex: 1 1 160px; display: flex; gap: 8px; align-items: center;
  background: var(--panel); border: 1px solid var(--rule, #414a55); border-radius: 2px;
  padding: 3px 9px; font-size: 12px; font-variant-numeric: tabular-nums; }
.maplibre-view .ml-slider input { flex: 1; accent-color: var(--climb); }
.maplibre-view .ml-seg { display: flex; }
.maplibre-view .ml-seg button { border-radius: 0; }
.maplibre-view .ml-seg button + button { margin-left: -1px; }
.maplibre-view .maplibregl-ctrl-bottom-right { bottom: 48px; }
.maplibre-view .maplibregl-ctrl-bottom-left { bottom: 48px; }
"""


SWITCH_SCRIPT = (
    """
(function () {
  var MAPLIBRE = '__MAPLIBRE__', DECK = '__DECK__', TERRARIUM = '__TERRARIUM__';
  var libraries = null;

  function load(tag, attrs) {
    return new Promise(function (resolve, reject) {
      var node = document.createElement(tag);
      Object.keys(attrs).forEach(function (key) { node[key] = attrs[key]; });
      node.onload = resolve;
      node.onerror = function () { reject(new Error('could not load ' + (attrs.src || attrs.href))); };
      document.head.appendChild(node);
    });
  }

  // Once per page, however many flights switch — and shared with `map3d`'s merged view.
  window.__mapTerrarium = TERRARIUM;
  window.__mapLibs = libs;
  function libs() {
    if (!libraries) {
      libraries = Promise.all([
        load('link', { rel: 'stylesheet', href: MAPLIBRE + '/maplibre-gl.css' }),
        load('script', { src: MAPLIBRE + '/maplibre-gl.js' })
      ]).then(function () { return load('script', { src: DECK }); });
      libraries.catch(function () { libraries = null; });
    }
    return libraries;
  }

  function handleFor(host) {
    var canvas = host.querySelector('canvas.view3d');
    return canvas && window.__view3dAll ? window.__view3dAll[canvas.id] : null;
  }

  // The track cut into runs of one colour, which is what a PathLayer wants: the canvas
  // view colours per vertex from the palette index, and this is the same index.
  function segments(scene) {
    var tr = scene.track, out = [], run = [], colour = null;
    for (var i = 0; i < tr.lon.length; i++) {
      var point = [tr.lon[i], tr.lat[i], tr.alt[i]];
      var c = tr.c[i];
      run.push(point);
      if (colour === null) colour = c;
      if (c !== colour) {
        if (run.length > 1) out.push({ path: run, colour: scene.palette[colour] });
        run = [point];
        colour = c;
      }
    }
    if (run.length > 1) out.push({ path: run, colour: scene.palette[colour] });
    return out;
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  // The flight's own clock where the scene carries the sun table (which knows the launch
  // minute and the day's offset), elapsed time where it does not — an upload.
  function clockFor(scene) {
    var sun = scene.sun;
    if (sun && sun.launch != null) {
      return function (seconds) {
        var minute = Math.floor(sun.launch + (sun.offset || 0) + seconds / 60);
        minute = ((minute % 1440) + 1440) % 1440;
        return pad(Math.floor(minute / 60)) + ':' + pad(minute % 60);
      };
    }
    return function (seconds) {
      var m = Math.floor(seconds / 60);
      return '+' + Math.floor(m / 60) + ':' + pad(m % 60);
    };
  }

  function styleFor(scene, basemap) {
    var tiles = scene.tiles || {};
    var sources = {
      dem: { type: 'raster-dem', tiles: [TERRARIUM], tileSize: 256, maxzoom: 15,
             encoding: 'terrarium', attribution: 'AWS Open Data Terrain Tiles' }
    };
    var layers = [];
    var source = tiles[basemap];
    if (source) {
      source.layers.forEach(function (template, index) {
        sources['b' + index] = { type: 'raster', tiles: [template], tileSize: 256,
                                 maxzoom: source.max_zoom || 18 };
        // One credit per style, not per layer — and MapLibre rejects the whole style
        // over an `attribution: undefined`, so the key is only set where there is one.
        if (!index && source.attribution) sources.b0.attribution = source.attribution;
        layers.push({ id: 'b' + index, type: 'raster', source: 'b' + index });
      });
    } else {
      layers.push({ id: 'bg', type: 'background', paint: { 'background-color': '#d9d4c7' } });
    }
    layers.push({ id: 'hillshade', type: 'hillshade', source: 'dem',
                  paint: { 'hillshade-exaggeration': source ? 0.25 : 0.6 } });
    return { version: 8, sources: sources, layers: layers, sky: {} };
  }

  function mount(host, handle) {
    var panel = host.querySelector('.view3d-panel');
    var scene = handle.built.scene, cursorTrack = handle.built.cursorTrack;
    var tr = scene.track;
    var hasTime = !!(tr.t && tr.t.length === tr.lon.length && tr.lon.length > 1);
    var duration = hasTime ? tr.t[tr.t.length - 1] : 0;
    var clock = clockFor(scene);
    var styles = Object.keys(scene.tiles || {});
    var basemap = styles.indexOf('satellite') >= 0 ? 'satellite' : (styles[0] || 'off');

    var view = document.createElement('div');
    view.className = 'maplibre-view';
    view.innerHTML =
      '<div class="ml-map"></div>' +
      '<p class="ml-status">Loading MapLibre…</p>' +
      '<div class="ml-replay" hidden>' +
        (hasTime ? '<button type="button" data-ml="play">Play</button>' +
          '<label class="ml-slider"><span class="ml-clock"></span>' +
          '<input type="range" min="0" max="' + duration + '" step="1" value="' + duration + '"' +
          ' aria-label="Replay time"></label>' +
          '<button type="button" data-ml="whole" class="is-on" aria-pressed="true">whole track</button>'
          : '') +
        '<div class="ml-seg">' +
          styles.map(function (key) {
            return '<button type="button" data-ml-style="' + key + '"' +
              (key === basemap ? ' class="is-on"' : '') + '>' +
              ((scene.tiles[key] || {}).label || key) + '</button>';
          }).join('') +
          '<button type="button" data-ml-style="off"' + (basemap === 'off' ? ' class="is-on"' : '') +
          '>relief</button></div>' +
        '<div class="ml-seg">' +
          [1, 2, 4].map(function (v) {
            return '<button type="button" data-ml-vert="' + v + '"' + (v === 1 ? ' class="is-on"' : '') +
              '>&#215;' + v + '</button>';
          }).join('') + '</div>' +
      '</div>';
    panel.appendChild(view);

    var api = { view: view, map: null, show: function () { view.hidden = false;
      if (api.map) api.map.resize(); }, hide: function () { view.hidden = true; pause(); } };
    var playing = false, frame = null;
    function pause() {
      playing = false;
      if (frame) cancelAnimationFrame(frame);
      var button = view.querySelector('[data-ml="play"]');
      if (button) { button.textContent = 'Play'; button.classList.remove('is-on'); }
    }

    libs().then(function () {
      view.querySelector('.ml-status').hidden = true;
      view.querySelector('.ml-replay').hidden = false;
      var dem = scene.terrain || {};
      var west = Math.min.apply(null, tr.lon.length ? tr.lon : [dem.west]);
      var east = Math.max.apply(null, tr.lon.length ? tr.lon : [dem.east]);
      var south = Math.min.apply(null, tr.lat.length ? tr.lat : [dem.south]);
      var north = Math.max.apply(null, tr.lat.length ? tr.lat : [dem.north]);
      var vertical = 1;
      var map = api.map = new maplibregl.Map({
        container: view.querySelector('.ml-map'),
        style: styleFor(scene, basemap),
        center: [(west + east) / 2, (south + north) / 2], zoom: 10,
        pitch: 62, bearing: 15, maxPitch: 85, attributionControl: { compact: true }
      });
      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
      map.addControl(new maplibregl.FullscreenControl({ container: panel }), 'top-right');
      map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');
      function terrain() { map.setTerrain({ source: 'dem', exaggeration: vertical }); }
      map.on('style.load', terrain);

      var lines = segments(scene);
      var trip = [{ path: tr.lon.map(function (lon, i) { return [lon, tr.lat[i], tr.alt[i]]; }),
                    times: hasTime ? tr.t : [] }];
      var cutoff = duration, whole = true, cursor = null;

      // MapLibre exaggerates the terrain from sea level, so the track is scaled the same
      // way or it would float over the valleys and sink into the ridges.
      function z(alt) { return alt * vertical; }

      function layers() {
        var out = [];
        if (whole || !hasTime) out.push(new deck.PathLayer({
          id: 'track', data: lines,
          getPath: function (d) { return d.path.map(function (p) { return [p[0], p[1], z(p[2])]; }); },
          getColor: function (d) { return d.colour; }, getWidth: 3, widthUnits: 'pixels',
          capRounded: true, jointRounded: true, billboard: true,
          updateTriggers: { getPath: vertical }
        }));
        if (hasTime) out.push(new deck.TripsLayer({
          id: 'replay', data: trip,
          getPath: function (d) { return d.path.map(function (p) { return [p[0], p[1], z(p[2])]; }); },
          getTimestamps: function (d) { return d.times; },
          getColor: [255, 255, 255], getWidth: 4, widthUnits: 'pixels',
          trailLength: whole ? 420 : duration + 1, currentTime: cutoff,
          capRounded: true, jointRounded: true, updateTriggers: { getPath: vertical }
        }));
        out.push(new deck.ScatterplotLayer({
          id: 'climbs', data: scene.climbs || [],
          getPosition: function (d) { return [d.lon, d.lat, z(d.alt)]; },
          getFillColor: function (d) { return d.tow ? [27, 175, 122] : [235, 104, 52]; },
          getLineColor: [255, 255, 255, 220], stroked: true, lineWidthMinPixels: 1.5,
          radiusUnits: 'pixels', getRadius: 6, updateTriggers: { getPosition: vertical }
        }));
        if (cursor) out.push(new deck.ScatterplotLayer({
          id: 'cursor', data: [cursor],
          getPosition: function (d) { return [d[0], d[1], z(d[2])]; },
          getFillColor: [255, 255, 255], getLineColor: [20, 20, 20], stroked: true,
          lineWidthMinPixels: 2, radiusUnits: 'pixels', getRadius: 7,
          updateTriggers: { getPosition: vertical }
        }));
        return out;
      }
      var overlay = new deck.MapboxOverlay({ interleaved: false, layers: layers() });
      map.addControl(overlay);
      function refresh() { overlay.setProps({ layers: layers() }); }
      if (west < east || south < north) {
        map.fitBounds([[west, south], [east, north]],
                      { padding: 60, pitch: 62, bearing: 15, duration: 0 });
      }

      var slider = view.querySelector('.ml-slider input');
      var label = view.querySelector('.ml-clock');
      function setTime(seconds) {
        cutoff = seconds;
        if (slider) slider.value = seconds;
        if (label) label.textContent = clock(seconds);
        refresh();
      }
      if (slider) {
        setTime(duration);
        slider.addEventListener('input', function () { pause(); setTime(Number(slider.value)); });
      }
      var last = 0;
      function step(now) {
        // Two minutes of flight a second, whatever the frame rate.
        var dt = last ? (now - last) / 1000 : 0;
        last = now;
        var next = cutoff + dt * 120;
        setTime(next > duration ? 0 : next);
        if (playing) frame = requestAnimationFrame(step);
      }
      view.addEventListener('click', function (event) {
        var button = event.target.closest('button');
        if (!button) return;
        if (button.dataset.ml === 'play') {
          if (playing) { pause(); return; }
          playing = true; last = 0;
          button.textContent = 'Pause'; button.classList.add('is-on');
          if (cutoff >= duration) setTime(0);
          frame = requestAnimationFrame(step);
        } else if (button.dataset.ml === 'whole') {
          whole = !whole;
          button.classList.toggle('is-on', whole);
          button.setAttribute('aria-pressed', String(whole));
          refresh();
        } else if (button.dataset.mlStyle) {
          view.querySelectorAll('[data-ml-style]').forEach(function (b) {
            b.classList.toggle('is-on', b === button);
          });
          map.setStyle(styleFor(scene, button.dataset.mlStyle));
        } else if (button.dataset.mlVert) {
          vertical = Number(button.dataset.mlVert);
          view.querySelectorAll('[data-ml-vert]').forEach(function (b) {
            b.classList.toggle('is-on', b === button);
          });
          terrain();
          refresh();
        }
      });

      // Follow the charts. The canvas handle is still the one every chart and table row
      // calls, so wrapping it is enough; the canvas keeps doing its own part too, which is
      // what makes switching back land on the same moment.
      function at(index) {
        if (!cursorTrack || index == null || index < 0 || index >= cursorTrack.lon.length) return null;
        return [cursorTrack.lon[index], cursorTrack.lat[index], cursorTrack.alt[index]];
      }
      ['setCursor', 'revealCursor'].forEach(function (name) {
        var original = handle[name];
        if (typeof original !== 'function') return;
        handle[name] = function (index) {
          cursor = at(index);
          if (!view.hidden) {
            refresh();
            if (name === 'revealCursor' && cursor) map.easeTo({ center: [cursor[0], cursor[1]] });
          }
          return original.apply(handle, arguments);
        };
      });
      var clear = handle.clearCursor;
      handle.clearCursor = function () {
        cursor = null;
        if (!view.hidden) refresh();
        return clear.apply(handle, arguments);
      };
      window.__maplibreAll = window.__maplibreAll || {};
      window.__maplibreAll[panel.querySelector('canvas.view3d').id] = {
        map: map, setTime: setTime, cursor: function () { return cursor; }
      };
    }, function (error) {
      view.querySelector('.ml-status').textContent =
        'MapLibre could not be loaded (' + error.message + '). It needs a network; the ' +
        'canvas view does not.';
    });
    return api;
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-renderer]');
    if (!button) return;
    var host = button.closest('.renderer-host');
    if (!host) return;
    var handle = handleFor(host);
    var want = button.dataset.renderer;
    host.querySelectorAll('[data-renderer]').forEach(function (b) {
      var on = b === button;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-pressed', String(on));
    });
    var mounts = { maplibre: mount, merged: window.__mountMerged };
    if (want !== 'canvas' && (!handle || !handle.built || !mounts[want])) {
      // An upload whose view is still loading: nothing to draw from yet.
      host.querySelector('[data-renderer="canvas"]').click();
      return;
    }
    // One overlay per renderer, kept once built: switching back is instant and the camera
    // is where it was left. Rebuilt only when the panel underneath is a new one.
    host.__renderers = host.__renderers || {};
    Object.keys(host.__renderers).forEach(function (key) {
      if (key !== want) host.__renderers[key].api.hide();
    });
    if (want === 'canvas') return;
    var built = host.__renderers[want];
    if (!built || built.handle !== handle) {
      if (built) built.api.view.remove();
      built = host.__renderers[want] = { handle: handle, api: mounts[want](host, handle) };
    }
    built.api.show();
  });
})();
"""
    .replace("__MAPLIBRE__", MAPLIBRE)
    .replace("__DECK__", DECK)
    .replace("__TERRARIUM__", TERRARIUM)
)

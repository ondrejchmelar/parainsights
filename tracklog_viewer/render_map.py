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

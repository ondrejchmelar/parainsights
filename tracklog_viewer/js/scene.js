/* The 3D map's scene and panel for one flight: `view3d.data` and `view3d.panel`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * The map (`view3d.SCRIPT`, `render_map.SCRIPT`, `map3d.SCRIPT`) was always in the page;
 * what was built in Python was what it draws — the track, the climbs, the phase labels,
 * the sun table, the wind — and the markup around it. Both are
 * here now, with the same output, so an uploaded track gets the same 3D view as a
 * bundled one.
 */
(function (TV) {
  'use strict';
  var np = TV.np, igc = TV.igc, sun = TV.sun, fmt = np.fmt, R = np.pyRound;

  // view3d.TILE_SOURCES — the imagery the page fetches at view time.
  var TILE_SOURCES = {
    satellite: {
      label: 'Satellite',
      layers: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
               'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places_Alternate/MapServer/tile/{z}/{y}/{x}'],
      attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
      max_zoom: 18,
      consistent_from: 12,
      label_max_zoom: 12
    },
    map: {
      label: 'Map',
      layers: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      attribution: '© OpenStreetMap contributors',
      max_zoom: 19
    }
  };
  var RAMP_RGB = [[-4.0, [23, 80, 143]], [-2.0, [42, 120, 214]], [-0.7, [143, 182, 230]], [0.7, [169, 164, 154]],
                  [2.0, [240, 160, 122]], [4.0, [235, 104, 52]], [Infinity, [200, 67, 26]]];

  function colourIndex(value) {
    for (var i = 0; i < RAMP_RGB.length; i++) if (value < RAMP_RGB[i][0]) return i;
    return null;
  }

  // `terrain` is the grid object as the page carries it (`Terrain.to_remote()` for a
  // bundled flight, the fetched grid for an upload); `options`: airspaceRemote (where
  // the airspace layer files are; the map loads them when opened). The imagery is always fetched in the page (`tiles`).
  function data(a, terrain, options) {
    options = options || {};
    var f = a.flight, s = a.series;
    var alt = f.alt_gps.some(function (v) { return v !== 0; }) ? f.alt_gps : s.alt;
    // Every fix, delta-encoded: lon and lat in 1e-5° steps (the precision they had as
    // decimals), altitude in metres and time in seconds, each as the difference from the
    // fix before. The same values in about half the bytes — `readScene` in the page
    // (`parainsights_map.view3d`) puts them back before anything reads them.
    var track = { enc: 1e5, lon: [], lat: [], alt: [], c: [], t: [] };
    var prev = [0, 0, 0, 0];
    for (var i = 0; i < f.lon.length; i++) {
      var now = [Math.round(f.lon[i] * 1e5), Math.round(f.lat[i] * 1e5), Math.trunc(alt[i]), Math.trunc(s.t[i])];
      track.lon.push(now[0] - prev[0]);
      track.lat.push(now[1] - prev[1]);
      track.alt.push(now[2] - prev[2]);
      track.t.push(now[3] - prev[3]);
      track.c.push(colourIndex(s.climb[i]));
      prev = now;
    }
    var climbs = [], number = 0;
    a.segments.forEach(function (seg) {
      if (seg.phase !== 'thermal' && seg.phase !== 'tow') return;
      var middle = Math.floor((seg.start + seg.stop) / 2), label;
      if (seg.phase === 'tow') label = 'T'; else { number += 1; label = String(number); }
      climbs.push({ label: label, lon: R(f.lon[middle], 5), lat: R(f.lat[middle], 5), alt: Math.trunc(alt[middle]),
                    tow: seg.phase === 'tow' });
    });
    var phases = [];
    a.segments.forEach(function (seg) {
      var kind, value;
      if (seg.phase === 'thermal') {
        kind = 'climb';
        value = fmt(seg.average_climb, 1, { plus: true }) + ' m/s · ' + fmt(seg.altitude_change, 0, { plus: true }) + ' m';
      } else if (seg.phase === 'glide') {
        kind = 'glide';
        value = seg.average_ld ? fmt(seg.average_ld, 1) + ':1 · ' + fmt(seg.distance / 1000, 1) + ' km'
                               : fmt(seg.distance / 1000, 1) + ' km';
      } else return;
      var last = seg.stop - 1;
      phases.push({ kind: kind, text: value, lon: [R(f.lon[seg.start], 5), R(f.lon[last], 5)],
                    lat: [R(f.lat[seg.start], 5), R(f.lat[last], 5)],
                    alt: [Math.trunc(alt[seg.start]), Math.trunc(alt[last])] });
    });
    var n = f.lon.length;
    var out = {
      terrain: terrain,
      trackTop: f.lon.length ? Math.max.apply(null, alt.map(Math.trunc)) : 0,
      track: track, climbs: climbs, phases: phases,
      palette: RAMP_RGB.map(function (r) { return r[1].slice(); }),
      tiles: Object.assign({}, TILE_SOURCES),
      landing: { lon: R(f.lon[n - 1], 5), lat: R(f.lat[n - 1], 5), alt: Math.trunc(alt[n - 1]) },
      sun: sun.forFlight(f),
      // The first fix, UTC seconds: compared flights' replays run on one clock from it.
      start: Math.round(f.time[0]),
      wind: a.wind ? { ms: R(a.wind.speed, 1), from: R(a.wind.direction, 1), cardinal: a.wind.cardinal } : null
    };
    if (options.airspaceRemote) {
      // Loaded when the map is opened (`loadAirspace` in `parainsights_map.view3d`): the
      // switch is there from the start, waiting, and says why if nothing reaches here.
      Object.assign(out, { airspaceToggle: true, airspaceRemote: options.airspaceRemote, airspaces: [] });
    }
    return out;
  }

  // `view3d.panel`: the box the map mounts in, and the embedded data.
  function panel(payload, uid, options) {
    options = options || {};
    var verticals = options.verticals || [1, 2, 4];
    var start = options.vertical === undefined || options.vertical === null ? verticals[0] : options.vertical;
    return '\n    <div class="panel view3d-panel" data-verticals="' + verticals.join(',') +
      '" data-vertical="' + start + '">\n' +
      '      <div class="view3d" id="view3d-' + uid + '"></div>\n' +
      '      <script type="application/json" class="view3d-data">' + JSON.stringify(payload) + '</script>\n    </div>';
  }

  TV.scene = { TILE_SOURCES: TILE_SOURCES, RAMP_RGB: RAMP_RGB, data: data, panel: panel };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

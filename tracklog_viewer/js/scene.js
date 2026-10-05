/* The 3D view's scene and panel for one flight: `view3d.data`, `view3d.panel` and
 * `render_map.switch_html`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * The renderers (`view3d.SCRIPT`, `map3d.SCRIPT`, `render_map.SWITCH_SCRIPT`) were always
 * in the page; what was built in Python was what they draw — the track, the climbs, the
 * phase labels, the sun table, the wind — and the markup around the canvas. Both are
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
  var EXPAND_ICON = '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" focusable="false">' +
    '<path d="M1.5 5.5v-4h4M14.5 10.5v4h-4M14.5 5.5v-4h-4M1.5 10.5v4h4" fill="none" ' +
    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

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

  function panel(payload, uid, options) {
    options = options || {};
    var verticals = options.verticals || [1, 2, 4];
    var vertical = options.vertical === undefined ? null : options.vertical;
    var available = Object.assign({}, payload.tiles || {}, payload.basemaps || {});
    var keys = Object.keys(available);
    var initial = 'satellite' in available ? 'satellite' : (keys[0] || '');
    var credit = (available[initial] || {}).attribution || '';
    var styles = ['satellite', 'map'].filter(function (k) { return k in available; });
    keys.forEach(function (k) { if (styles.indexOf(k) < 0) styles.push(k); });
    var segments = styles.map(function (key) {
      var on = key === initial;
      return '<button type="button" data-view3d-act="basemap-set" data-style="' + key + '" aria-pressed="' + (on ? 'true' : 'false') + '"' +
        (on ? ' class=is-on' : '') + '>' + ((TILE_SOURCES[key] || {}).label || key) + '</button>';
    }).join('') + '<button type="button" data-view3d-act="basemap-set" data-style="off" aria-pressed="false">relief</button>';
    var start = vertical === null ? verticals[0] : vertical;
    var exaggeration = verticals.map(function (level) {
      var on = level === start;
      return '<button type="button" data-view3d-act="exaggerate-set" data-vertical="' + level + '" aria-pressed="' +
        (on ? 'true' : 'false') + '"' + (on ? ' class=is-on' : '') + ' aria-label="Vertical exaggeration &#215;' + level +
        '">&#215;' + level + '</button>';
    }).join('');
    var labels = payload.phases && payload.phases.length
      ? '<div class="view3d-seg view3d-labels" role="group" aria-label="Phase labels">' +
        '<button type="button" data-view3d-act="labels-toggle" data-kind="climb" aria-pressed="false" aria-label="Label each climb with its rate and gain">climbs</button>' +
        '<button type="button" data-view3d-act="labels-toggle" data-kind="glide" aria-pressed="false" aria-label="Label each glide with its ratio and distance">glides</button></div>'
      : '';
    // Disabled until the map has loaded the airspace under it (`loadAirspace`).
    var airspace = payload.airspaceToggle
      ? '<div class="view3d-seg view3d-airspace" role="group" aria-label="Airspace">' +
        '<button type="button" data-view3d-act="airspace-toggle" aria-pressed="false" disabled title="Loading the airspace…" aria-label="Loading the airspace…">airspace</button></div>'
      : '';
    var airspaceName = payload.airspaceToggle ? '<div class="view3d-asp" hidden></div>' : '';
    return '\n    <div class="panel view3d-panel">\n' +
      '      <canvas class="view3d" id="view3d-' + uid + '" tabindex="0"\n' +
      '              aria-label="Interactive three-dimensional view of the flight over terrain.\n' +
      '                          Arrow keys pan and shift with them turns and tilts; press\n' +
      '                          question mark for the key list.">\n      </canvas>\n' +
      '      ' + airspaceName + '\n' +
      '      <p class="view3d-credit">' + credit + '</p>\n' +
      '      <p class="view3d-hint" hidden>arrows pan &middot; shift + arrows turn and tilt &middot;\n' +
      '        <kbd>?</kbd> for keys</p>\n' +
      '      <div class="view3d-loading" hidden>\n        <span class="view3d-spin"></span><span class="view3d-loading-text"></span>\n      </div>\n' +
      '      <div class="view3d-keys" hidden data-view3d-act="help">\n' +
      '        <p class="view3d-keys-head">Mouse and touch</p>\n        <dl>\n' +
      '          <dt>drag</dt><dd>pan</dd>\n          <dt>right-drag / ctrl-drag</dt><dd>rotate and tilt</dd>\n' +
      '          <dt>scroll / pinch</dt><dd>zoom</dd>\n          <dt>two-finger twist</dt><dd>rotate</dd>\n        </dl>\n' +
      '        <p class="view3d-keys-head">Keys, once the view has focus</p>\n        <dl>\n' +
      '          <dt>arrows</dt><dd>pan</dd>\n          <dt>shift + &larr; &rarr;</dt><dd>rotate</dd>\n' +
      '          <dt>shift + &uarr; &darr;</dt><dd>tilt</dd>\n          <dt>+ &minus;</dt><dd>zoom</dd>\n' +
      '          <dt>1 2 4</dt><dd>exaggeration</dd>\n          <dt>s m r</dt><dd>satellite, map, relief</dd>\n' +
      '          ' + (payload.airspaceToggle ? '<dt>a</dt><dd>airspace</dd>' : '') + '\n' +
      '          <dt>f</dt><dd>full screen</dd>\n          <dt>0</dt><dd>reset view</dd>\n        </dl>\n' +
      '        <p class="view3d-keys-foot">Hovering the charts moves the marker here too.\n          Click this list to close it.</p>\n      </div>\n' +
      '      <div class="view3d-controls">\n' +
      '        <div class="view3d-seg" role="group" aria-label="What the ground is">' + segments + '</div>\n' +
      '        <div class="view3d-seg view3d-vert" role="group"\n             aria-label="Vertical exaggeration">' + exaggeration + '</div>\n' +
      '        \n        ' + labels + '\n        ' + airspace + '\n        \n' +
      '        <div class="view3d-seg view3d-zoom" role="group" aria-label="Zoom">\n' +
      '          <button type="button" data-view3d-act="zoom-out"\n                  title="Zoom out" aria-label="Zoom out">&minus;</button>\n' +
      '          <button type="button" data-view3d-act="zoom-in"\n                  title="Zoom in" aria-label="Zoom in">+</button>\n        </div>\n' +
      '        <button type="button" data-view3d-act="help"\n                title="Controls" aria-label="How to control this view">?</button>\n' +
      '        <button type="button" data-view3d-act="fullscreen"\n                title="Full screen" aria-label="Full screen">\n          ' +
      EXPAND_ICON + '</button>\n' +
      '        <button type="button" class="view3d-reset" data-view3d-act="reset"\n                title="Reset view" aria-label="Reset view">&#8634;</button>\n      </div>\n' +
      '      <script type="application/json" class="view3d-data">' + JSON.stringify(payload) + '</script>\n    </div>';
  }

  function switchHtml() {
    return '<div class="toggle renderer-switch" role="group" aria-label="3D renderer">' +
      '<button type="button" class="toggle-button is-on" data-renderer="canvas" aria-pressed="true">canvas</button>' +
      '<button type="button" class="toggle-button" data-renderer="maplibre" aria-pressed="false">MapLibre</button>' +
      '<button type="button" class="toggle-button" data-renderer="merged" aria-pressed="false">merged</button></div>';
  }

  TV.scene = { TILE_SOURCES: TILE_SOURCES, RAMP_RGB: RAMP_RGB, data: data, panel: panel, switchHtml: switchHtml };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

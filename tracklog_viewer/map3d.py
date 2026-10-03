"""The merged 3D map: MapLibre's engine under the canvas view's controls.

What each renderer was better at, in one view. From MapLibre (`render_map`): the whole
planet rather than one fetched rectangle, imagery and terrain streamed at every zoom,
and the replay slider. From the canvas view (`view3d`): the control bar, its keys, the
sun and wind rose, the climb and glide labels, the airspace boxes — and the canvas's
imagery treatment: the photograph shaded towards warm white and dark blue from the
sun's real position, never MapLibre's default black-and-white overlay that greys it.

It is the third position of the renderer switch (`render_map.switch_html`) while the
three are compared, and it draws from the same scene and follows the same linked
cursor as the other two (`handle.built`, and the wrapped `setCursor`). MapLibre and
deck.gl come from `render_map`'s loader, on the first switch.

Heights: MapLibre exaggerates terrain from sea level, so everything drawn above it is
scaled the same way — `alt × vertical` — or a track 500 m over a 1 000 m ridge would
sink into it at ×2.
"""

STYLE = """
.merged-view .ml-map:focus-visible { outline: 2px solid var(--climb); outline-offset: -2px; }
.merged-view .m3-rose { position: absolute; top: 12px; right: 12px; z-index: 3;
  pointer-events: none; text-align: right; }
.merged-view .m3-rose svg { display: block; margin-left: auto; }
.merged-view .m3-rose p { margin: 4px 0 0; font-size: 11px; line-height: 1.3; color: #fff;
  text-shadow: 0 0 3px rgba(12,14,18,0.95), 0 0 2px rgba(12,14,18,0.95); }
.merged-view .view3d-credit { z-index: 3; }
.merged-view .m3-replay { position: absolute; left: 10px; right: 10px; bottom: 52px; z-index: 3;
  display: flex; gap: 5px; align-items: center; }
.merged-view .m3-replay[hidden] { display: none; }
.merged-view .m3-replay button { font: inherit; font-size: 11px; letter-spacing: 0.06em;
  text-transform: uppercase; padding: 6px 9px; cursor: pointer; color: var(--ink-2);
  background: var(--panel); border: 1px solid var(--rule); border-radius: 2px; }
.merged-view .m3-replay button:hover { color: var(--ink); background: var(--panel-2); }
.merged-view .m3-replay button.is-on { background: var(--climb); border-color: var(--climb);
  color: var(--paper); }
.merged-view .m3-time { flex: 1; display: flex; gap: 8px; align-items: center;
  background: var(--panel); border: 1px solid var(--rule); border-radius: 2px;
  padding: 3px 9px; font-size: 12px; color: var(--ink); font-variant-numeric: tabular-nums; }
.merged-view .m3-time input { flex: 1; accent-color: var(--climb); }
.merged-view .m3-status { position: absolute; left: 12px; top: 34px; z-index: 3; margin: 0;
  font-size: 12px; color: var(--ink-2); }
.merged-view .maplibregl-ctrl-attrib { display: none; }
@media (max-width: 640px) {
  .merged-view .m3-replay { bottom: 92px; }
}
"""

SCRIPT = r"""
(function () {
  var COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  function compass(azimuth) {
    return COMPASS[Math.round((((azimuth % 360) + 360) % 360) / 22.5) % 16];
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  // Markers and labels draw over the track rather than fighting it for depth: a number
  // at the same point as its own circle otherwise loses to it and vanishes.
  var ON_TOP = { depthCompare: 'always', depthWriteEnabled: false };
  function rgb(hex, alpha) {
    var v = parseInt(String(hex).replace('#', ''), 16);
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255, alpha];
  }

  // The track as runs of one colour: the palette index per fix is the canvas view's own.
  function segments(scene) {
    var tr = scene.track, out = [], run = [], colour = null;
    for (var i = 0; i < tr.lon.length; i++) {
      var point = [tr.lon[i], tr.lat[i], tr.alt[i]];
      run.push(point);
      if (colour === null) colour = tr.c[i];
      if (tr.c[i] !== colour) {
        if (run.length > 1) out.push({ path: run, colour: scene.palette[colour] });
        run = [point];
        colour = tr.c[i];
      }
    }
    if (run.length > 1) out.push({ path: run, colour: scene.palette[colour] });
    return out;
  }

  function keysHtml(airspace) {
    return '<p class="view3d-keys-head">Mouse and touch</p><dl>' +
      '<dt>drag</dt><dd>pan</dd>' +
      '<dt>right-drag / ctrl-drag</dt><dd>rotate and tilt</dd>' +
      '<dt>scroll / pinch</dt><dd>zoom</dd>' +
      '<dt>two-finger twist</dt><dd>rotate</dd></dl>' +
      '<p class="view3d-keys-head">Keys, once the map has focus</p><dl>' +
      '<dt>arrows</dt><dd>pan</dd>' +
      '<dt>shift + &larr; &rarr;</dt><dd>rotate</dd>' +
      '<dt>shift + &uarr; &darr;</dt><dd>tilt</dd>' +
      '<dt>+ &minus;</dt><dd>zoom</dd>' +
      '<dt>1 2 4</dt><dd>exaggeration</dd>' +
      '<dt>s m r</dt><dd>satellite, map, relief</dd>' +
      (airspace ? '<dt>a</dt><dd>airspace</dd>' : '') +
      '<dt>space</dt><dd>play / pause the replay</dd>' +
      '<dt>f</dt><dd>full screen</dd>' +
      '<dt>0</dt><dd>reset view</dd></dl>' +
      '<p class="view3d-keys-foot">Hovering the charts moves the marker here too. ' +
      'Click this list to close it.</p>';
  }

  window.__mountMerged = function (host, handle) {
    var panel = host.querySelector('.view3d-panel');
    var scene = handle.built.scene, cursorTrack = handle.built.cursorTrack;
    var tr = scene.track || { lon: [], lat: [], alt: [], c: [] };
    var tiles = scene.tiles || {};
    var styles = ['satellite', 'map'].filter(function (k) { return tiles[k]; });
    Object.keys(tiles).forEach(function (k) { if (styles.indexOf(k) < 0) styles.push(k); });
    var basemap = styles[0] || 'off';
    var hasTime = !!(tr.t && tr.t.length === tr.lon.length && tr.lon.length > 1);
    var duration = hasTime ? tr.t[tr.t.length - 1] : 0;
    var sun = scene.sun && scene.sun.track && scene.sun.track.az ? scene.sun : null;
    var wind = scene.wind || null;
    var hasAirspace = !!(scene.airspaceToggle && scene.airspaces && scene.airspaces.length);
    var hasPhases = !!(scene.phases && scene.phases.length);

    var view = document.createElement('div');
    view.className = 'maplibre-view merged-view';
    view.innerHTML =
      '<div class="ml-map" tabindex="0" aria-label="Interactive three-dimensional map of the ' +
        'flight. Arrow keys pan and shift with them turns and tilts; press question mark ' +
        'for the key list."></div>' +
      '<p class="view3d-credit"></p>' +
      '<p class="m3-status">Loading MapLibre…</p>' +
      '<div class="m3-rose" hidden><svg width="64" height="64" viewBox="-32 -32 64 64">' +
        '<circle r="30" fill="rgba(16,19,24,0.55)" stroke="rgba(255,255,255,0.28)"/>' +
        '<text class="m3-n" text-anchor="middle" dominant-baseline="central" font-size="11"' +
        ' fill="rgba(255,255,255,0.75)">N</text>' +
        '<g class="m3-wind"><line x1="0" y1="19" x2="0" y2="-15" stroke="rgba(120,190,255,0.95)"' +
        ' stroke-width="2.2" stroke-linecap="round"/><path d="M0,-21 L-4.5,-12 L4.5,-12 Z"' +
        ' fill="rgba(120,190,255,0.95)"/></g>' +
        '<g class="m3-sun"><line x1="0" y1="-13" x2="0" y2="-6" stroke-width="1.6"/>' +
        '<circle cy="-21" r="5.5"/></g>' +
      '</svg><p class="m3-rose-text"></p></div>' +
      '<div class="view3d-asp" hidden></div>' +
      '<div class="view3d-keys" hidden data-m3="help">' + keysHtml(hasAirspace) + '</div>' +
      (hasTime ?
        '<div class="m3-replay" hidden>' +
          '<button type="button" data-m3="play" aria-pressed="false">play</button>' +
          '<label class="m3-time"><span class="m3-clock"></span>' +
          '<input type="range" min="0" max="' + duration + '" step="1" value="' + duration + '"' +
          ' aria-label="Replay time"></label>' +
          '<button type="button" data-m3="whole" class="is-on" aria-pressed="true"' +
          ' title="Show the whole track behind the replay">whole track</button>' +
        '</div>' : '') +
      '<div class="view3d-controls" hidden>' +
        '<div class="view3d-seg" role="group" aria-label="What the ground is">' +
          styles.map(function (k) {
            var on = k === basemap;
            return '<button type="button" data-m3-style="' + k + '" aria-pressed="' + on + '"' +
              (on ? ' class="is-on"' : '') + '>' + ((tiles[k] || {}).label || k) + '</button>';
          }).join('') +
          '<button type="button" data-m3-style="off" aria-pressed="false">relief</button>' +
        '</div>' +
        '<div class="view3d-seg view3d-vert" role="group" aria-label="Vertical exaggeration">' +
          [1, 2, 4].map(function (v) {
            return '<button type="button" data-m3-vert="' + v + '" aria-pressed="' + (v === 1) + '"' +
              (v === 1 ? ' class="is-on"' : '') + ' aria-label="Vertical exaggeration &#215;' + v +
              '">&#215;' + v + '</button>';
          }).join('') +
        '</div>' +
        (hasPhases ?
          '<div class="view3d-seg view3d-labels" role="group" aria-label="Phase labels">' +
          '<button type="button" data-m3-label="climb" aria-pressed="false"' +
          ' aria-label="Label each climb with its rate and gain">climbs</button>' +
          '<button type="button" data-m3-label="glide" aria-pressed="false"' +
          ' aria-label="Label each glide with its ratio and distance">glides</button></div>' : '') +
        (hasAirspace ?
          '<div class="view3d-seg view3d-airspace" role="group" aria-label="Airspace">' +
          '<button type="button" data-m3="airspace" aria-pressed="false"' +
          ' aria-label="Draw the airspace over this flight">airspace</button></div>' : '') +
        '<div class="view3d-seg view3d-zoom" role="group" aria-label="Zoom">' +
          '<button type="button" data-m3="zoom-out" title="Zoom out" aria-label="Zoom out">&minus;</button>' +
          '<button type="button" data-m3="zoom-in" title="Zoom in" aria-label="Zoom in">+</button></div>' +
        '<button type="button" data-m3="help" title="Controls" aria-label="How to control this view">?</button>' +
        '<button type="button" data-m3="fullscreen" title="Full screen" aria-label="Full screen">' +
          '<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor"' +
          ' stroke-width="1.5"><path d="M1 4.5V1h3.5M8.5 1H12v3.5M12 8.5V12H8.5M4.5 12H1V8.5"/></svg></button>' +
        '<button type="button" class="view3d-reset" data-m3="reset" title="Reset view"' +
        ' aria-label="Reset view">&#8634;</button>' +
      '</div>';
    panel.appendChild(view);

    var playing = false, frame = null, map = null;
    function pause() {
      playing = false;
      if (frame) cancelAnimationFrame(frame);
      var b = view.querySelector('[data-m3="play"]');
      if (b) { b.textContent = 'play'; b.classList.remove('is-on'); b.setAttribute('aria-pressed', 'false'); }
    }
    var api = {
      view: view,
      show: function () { view.hidden = false; if (map) map.resize(); },
      hide: function () { view.hidden = true; pause(); }
    };

    window.__mapLibs().then(function () {
      view.querySelector('.m3-status').hidden = true;
      view.querySelector('.view3d-controls').hidden = false;
      var replay = view.querySelector('.m3-replay');
      if (replay) replay.hidden = false;

      var vertical = 1, whole = true, cursor = null, cutoff = duration;
      var labels = { climb: false, glide: false }, airspaceOn = false;
      var sunMinute = sun ? sun.at : null;
      var lines = segments(scene);

      function ground(lon, lat) {
        var g = handle.groundAt ? handle.groundAt(lon, lat) : null;
        return (g === null || g === undefined || isNaN(g)) ? ((scene.terrain || {}).min || 0) : g;
      }
      function z(alt) { return alt * vertical; }

      // ---- the ground ----------------------------------------------------------------
      function sunAt(minute) {
        var t = sun.track, span = t.az.length * t.step;
        var at = ((minute % span) + span) % span / t.step;
        var i = Math.floor(at), f = at - i, j = (i + 1) % t.az.length;
        if (j === 0) return { az: t.az[i], el: t.el[i] };
        return { az: t.az[i] + (t.az[j] - t.az[i]) * f, el: t.el[i] + (t.el[j] - t.el[i]) * f };
      }
      function style(key) {
        var source = tiles[key];
        var sources = {
          // Declared at half their size so MapLibre asks one zoom deeper than it would:
          // four times the tiles, and relief and imagery as sharp as the canvas's grid.
          // At their natural size the DEM it picks is ~4x coarser and the hills read flat.
          dem: { type: 'raster-dem', tiles: [window.__mapTerrarium], tileSize: 128, maxzoom: 15,
                 encoding: 'terrarium' }
        };
        var layers = [];
        if (source) {
          source.layers.forEach(function (template, i) {
            // The photograph at half size (sharper), the place-name layer at full size —
            // halved, its lettering would be too small to read.
            sources['b' + i] = { type: 'raster', tiles: [template], tileSize: i ? 256 : 128,
                                 maxzoom: source.max_zoom || 18 };
            // A slight lift: the raw Esri mosaic is dark next to the canvas's, which the
            // shading's highlights brighten by a third on the sunlit side.
            layers.push({ id: 'b' + i, type: 'raster', source: 'b' + i,
                          paint: i ? { 'raster-fade-duration': 150 }
                                   : { 'raster-fade-duration': 150, 'raster-brightness-min': 0.06,
                                       'raster-contrast': 0.05 } });
          });
        } else {
          layers.push({ id: 'bg', type: 'background', paint: { 'background-color': '#d6d2c4' } });
        }
        // The canvas view's own shading, not MapLibre's default: sunlit slopes lifted
        // towards a warm white and shaded ones towards a dark blue, lit from where the sun
        // was. Black-and-white shading over the photograph is what greyed it out; these
        // two colours are what makes the canvas imagery read clean and the relief read at
        // all. Under the labels layer, so place names stay crisp.
        var shade = {
          id: 'hillshade', type: 'hillshade', source: 'dem', paint: {
            'hillshade-exaggeration': source ? 0.45 : 1,
            'hillshade-highlight-color': source ? 'rgba(255,252,242,0.45)' : 'rgba(255,252,242,1)',
            'hillshade-shadow-color': source ? 'rgba(18,26,38,0.7)' : 'rgba(18,26,38,1)',
            'hillshade-accent-color': 'rgba(0,0,0,0)',
            'hillshade-illumination-anchor': 'map',
            'hillshade-illumination-direction': sun ? ((sunAt(sunMinute).az % 360) + 360) % 360 : 315
          }
        };
        if (layers.length > 1) layers.splice(1, 0, shade); else layers.push(shade);
        return {
          version: 8, sources: sources, layers: layers,
          // A sky without the haze: fog only at the horizon, and no atmosphere tint over
          // the ground — the haze is what washed the satellite colours out.
          sky: { 'sky-color': '#7fa3c4', 'horizon-color': '#c9d6e0', 'fog-color': '#c9d6e0',
                 'fog-ground-blend': 1, 'horizon-fog-blend': 0.15,
                 'sky-horizon-blend': 0.6, 'atmosphere-blend': 0 }
        };
      }
      function credit() {
        var parts = [];
        if (tiles[basemap]) parts.push(tiles[basemap].attribution);
        parts.push('terrain: AWS Terrain Tiles', 'MapLibre');
        view.querySelector('.view3d-credit').textContent = parts.join(' · ');
      }

      var dem = scene.terrain || {};
      var west = tr.lon.length ? Math.min.apply(null, tr.lon) : dem.west;
      var east = tr.lon.length ? Math.max.apply(null, tr.lon) : dem.east;
      var south = tr.lat.length ? Math.min.apply(null, tr.lat) : dem.south;
      var north = tr.lat.length ? Math.max.apply(null, tr.lat) : dem.north;
      map = new maplibregl.Map({
        container: view.querySelector('.ml-map'), style: style(basemap),
        center: [(west + east) / 2, (south + north) / 2], zoom: 10, pitch: 60, bearing: 0,
        maxPitch: 85, attributionControl: false, keyboard: true
      });
      map.on('style.load', function () { map.setTerrain({ source: 'dem', exaggeration: vertical }); });
      credit();
      function fit(animate) {
        if (!(west < east || south < north)) return;
        map.fitBounds([[west, south], [east, north]],
                      { padding: { top: 70, bottom: 110, left: 50, right: 90 },
                        pitch: 60, bearing: 0, duration: animate ? 600 : 0 });
      }
      fit(false);

      // ---- what is drawn over it -----------------------------------------------------
      var phaseLabels = (scene.phases || []).map(function (p) {
        return { kind: p.kind, text: p.text,
                 position: [(p.lon[0] + p.lon[1]) / 2, (p.lat[0] + p.lat[1]) / 2,
                            Math.max(p.alt[0], p.alt[1])] };
      });
      var boxes = hasAirspace ? scene.airspaces.map(function (ring) {
        var low = Infinity, high = -Infinity;
        if (ring.g || ring.fu !== undefined || ring.cu !== undefined) {
          ring.lon.forEach(function (lon, i) {
            var g = ground(lon, ring.lat[i]);
            low = Math.min(low, g); high = Math.max(high, g);
          });
        }
        var floor = ring.g ? low : (ring.fu !== undefined ? low + ring.fu : ring.f);
        var top = ring.cu !== undefined ? high + ring.cu : ring.c;
        return { name: ring.n, colour: (scene.airspaceColours || {})[ring.k] || '#888888',
                 ring: ring.lon.map(function (lon, i) { return [lon, ring.lat[i]]; }),
                 floor: floor, top: Math.max(top, floor + 30), capped: !!ring.t };
      }) : [];

      function layers() {
        var out = [];
        if (airspaceOn && boxes.length) {
          out.push(new deck.SolidPolygonLayer({
            id: 'airspace', data: boxes, extruded: true, wireframe: false, pickable: true,
            getPolygon: function (d) { return d.ring.map(function (p) { return [p[0], p[1], z(d.floor)]; }); },
            getElevation: function (d) { return (d.top - d.floor) * vertical; },
            getFillColor: function (d) { return rgb(d.colour, 46); },
            material: false, updateTriggers: { getPolygon: vertical, getElevation: vertical }
          }));
          out.push(new deck.PathLayer({
            id: 'airspace-edges', data: boxes.reduce(function (all, d) {
              var shut = d.ring.concat([d.ring[0]]);
              all.push({ colour: d.colour, path: shut.map(function (p) { return [p[0], p[1], z(d.floor)]; }) });
              all.push({ colour: d.colour, path: shut.map(function (p) { return [p[0], p[1], z(d.top)]; }) });
              return all;
            }, []),
            getPath: function (d) { return d.path; }, getColor: function (d) { return rgb(d.colour, 200); },
            getWidth: 1.2, widthUnits: 'pixels', updateTriggers: { data: vertical }
          }));
        }
        if (whole || !hasTime) out.push(new deck.PathLayer({
          id: 'track', data: lines,
          getPath: function (d) { return d.path.map(function (p) { return [p[0], p[1], z(p[2])]; }); },
          getColor: function (d) { return d.colour; }, getWidth: 3, widthUnits: 'pixels',
          capRounded: true, jointRounded: true, billboard: true,
          updateTriggers: { getPath: vertical }
        }));
        if (hasTime) out.push(new deck.TripsLayer({
          id: 'replay', data: [{ path: tr.lon.map(function (lon, i) { return [lon, tr.lat[i], tr.alt[i]]; }),
                                 times: tr.t }],
          getPath: function (d) { return d.path.map(function (p) { return [p[0], p[1], z(p[2])]; }); },
          getTimestamps: function (d) { return d.times; },
          getColor: [255, 255, 255], getWidth: 4, widthUnits: 'pixels',
          trailLength: whole ? 420 : duration + 1, currentTime: cutoff,
          capRounded: true, jointRounded: true, updateTriggers: { getPath: vertical }
        }));
        var marks = (scene.climbs || []).map(function (c) {
          return { label: c.label, tow: c.tow, position: [c.lon, c.lat, c.alt] };
        });
        out.push(new deck.ScatterplotLayer({
          id: 'climbs', data: marks,
          getPosition: function (d) { return [d.position[0], d.position[1], z(d.position[2])]; },
          getFillColor: function (d) { return d.tow ? [27, 175, 122] : [226, 96, 44]; },
          getLineColor: [255, 255, 255, 235], stroked: true, lineWidthMinPixels: 1.5,
          radiusUnits: 'pixels', getRadius: 9, billboard: true, updateTriggers: { getPosition: vertical },
          parameters: ON_TOP
        }));
        out.push(new deck.TextLayer({
          id: 'climb-numbers', data: marks, getText: function (d) { return d.label; },
          getPosition: function (d) { return [d.position[0], d.position[1], z(d.position[2])]; },
          getColor: [255, 255, 255], getSize: 11, fontWeight: 700,
          fontFamily: 'ui-sans-serif, system-ui, sans-serif', billboard: true,
          updateTriggers: { getPosition: vertical }, parameters: ON_TOP
        }));
        if (scene.landing) out.push(new deck.ScatterplotLayer({
          id: 'landing', data: [scene.landing],
          getPosition: function (d) { return [d.lon, d.lat, z(d.alt)]; },
          getFillColor: [20, 22, 26], getLineColor: [255, 255, 255], stroked: true,
          lineWidthMinPixels: 2, radiusUnits: 'pixels', getRadius: 6, billboard: true,
          updateTriggers: { getPosition: vertical }, parameters: ON_TOP
        }));
        var shown = phaseLabels.filter(function (p) { return labels[p.kind]; });
        if (shown.length) out.push(new deck.TextLayer({
          id: 'phase-labels', data: shown, getText: function (d) { return d.text; },
          getPosition: function (d) { return [d.position[0], d.position[1], z(d.position[2])]; },
          getPixelOffset: [0, -16], getSize: 11, characterSet: 'auto',
          fontFamily: 'ui-sans-serif, system-ui, sans-serif',
          getColor: [255, 255, 255], background: true, backgroundPadding: [5, 2],
          getBackgroundColor: function (d) { return d.kind === 'climb' ? [200, 80, 30, 225] : [36, 92, 160, 225]; },
          updateTriggers: { getPosition: vertical }, parameters: ON_TOP
        }));
        if (cursor) {
          var g = ground(cursor[0], cursor[1]);
          out.push(new deck.LineLayer({
            id: 'cursor-stem', data: [cursor],
            getSourcePosition: function (d) { return [d[0], d[1], z(g)]; },
            getTargetPosition: function (d) { return [d[0], d[1], z(d[2])]; },
            getColor: [255, 255, 255, 170], getWidth: 1.5
          }));
          out.push(new deck.ScatterplotLayer({
            id: 'cursor', data: [cursor],
            getPosition: function (d) { return [d[0], d[1], z(d[2])]; },
            getFillColor: [255, 255, 255], getLineColor: [20, 20, 20], stroked: true,
            lineWidthMinPixels: 2, radiusUnits: 'pixels', getRadius: 7, billboard: true,
            parameters: ON_TOP
          }));
        }
        return out;
      }

      var asp = view.querySelector('.view3d-asp');
      var overlay = new deck.MapboxOverlay({
        interleaved: false, layers: layers(),
        onHover: function (info) {
          var box = info && info.layer && info.layer.id === 'airspace' && info.object;
          if (!box) { asp.hidden = true; return; }
          asp.hidden = false;
          asp.textContent = box.name + (box.capped ? ' — drawn to 4 000 m' : '');
          asp.style.left = (info.x + 14) + 'px';
          asp.style.top = (info.y + 14) + 'px';
        }
      });
      map.addControl(overlay);
      function refresh() { overlay.setProps({ layers: layers() }); }

      // ---- the rose --------------------------------------------------------------------
      var rose = view.querySelector('.m3-rose');
      function screenAngle(bearing) { return bearing - map.getBearing(); }
      function drawRose() {
        if (!sun && !wind) return;
        rose.hidden = false;
        var svg = rose.querySelector('svg');
        var n = screenAngle(0) * Math.PI / 180;
        var label = svg.querySelector('.m3-n');
        label.setAttribute('x', Math.sin(n) * 22);
        label.setAttribute('y', -Math.cos(n) * 22);
        var windGroup = svg.querySelector('.m3-wind');
        windGroup.style.display = wind ? '' : 'none';
        // Where the air goes: opposite the bearing it is reported *from*.
        if (wind) windGroup.setAttribute('transform', 'rotate(' + screenAngle(wind.from + 180) + ')');
        var sunGroup = svg.querySelector('.m3-sun');
        var text = [];
        if (sun) {
          var now = sunAt(sunMinute), up = now.el > 0;
          var colour = up ? 'rgba(255,205,80,0.98)' : 'rgba(255,205,80,0.32)';
          sunGroup.setAttribute('transform', 'rotate(' + screenAngle(now.az) + ')');
          sunGroup.querySelector('circle').setAttribute('fill', colour);
          sunGroup.querySelector('line').setAttribute('stroke', colour);
          var local = ((Math.round(sunMinute) + (sun.offset || 0)) % 1440 + 1440) % 1440;
          text.push('Sun ' + pad(Math.floor(local / 60)) + ':' + pad(local % 60) + ' · ' +
                    (up ? Math.round(now.el) + '° ' + compass(now.az) : 'below the horizon'));
        } else {
          sunGroup.style.display = 'none';
        }
        if (wind) text.push('Wind ' + wind.ms.toFixed(1) + ' m/s from ' + wind.cardinal);
        rose.querySelector('.m3-rose-text').innerHTML = text.join('<br>');
      }
      map.on('rotate', drawRose);
      drawRose();
      var lastLight = null;
      function sunTo(minute) {
        if (!sun || minute === null || minute === undefined) return;
        sunMinute = minute;
        drawRose();
        if (map.getLayer('hillshade')) {
          var az = ((sunAt(minute).az % 360) + 360) % 360;
          if (lastLight === null || Math.abs(az - lastLight) >= 1) {
            lastLight = az;
            map.setPaintProperty('hillshade', 'hillshade-illumination-direction', az);
          }
        }
      }

      // ---- replay ----------------------------------------------------------------------
      var slider = view.querySelector('.m3-time input');
      var clockLabel = view.querySelector('.m3-clock');
      function clockAt(seconds) {
        if (sun && sun.launch !== undefined) {
          var m = Math.floor(sun.launch + (sun.offset || 0) + seconds / 60);
          m = ((m % 1440) + 1440) % 1440;
          return pad(Math.floor(m / 60)) + ':' + pad(m % 60);
        }
        var e = Math.floor(seconds / 60);
        return '+' + Math.floor(e / 60) + ':' + pad(e % 60);
      }
      function setTime(seconds) {
        cutoff = seconds;
        if (slider) slider.value = seconds;
        if (clockLabel) clockLabel.textContent = clockAt(seconds);
        if (sun && sun.launch !== undefined) sunTo(sun.launch + seconds / 60);
        refresh();
      }
      if (slider) {
        clockLabel.textContent = clockAt(duration);
        slider.addEventListener('input', function () { pause(); setTime(Number(slider.value)); });
      }
      var last = 0;
      function step(now) {
        var dt = last ? (now - last) / 1000 : 0;
        last = now;
        var next = cutoff + dt * 120;           // two minutes of flight a second
        setTime(next > duration ? 0 : next);
        if (playing) frame = requestAnimationFrame(step);
      }
      function togglePlay() {
        if (!hasTime) return;
        var b = view.querySelector('[data-m3="play"]');
        if (playing) { pause(); return; }
        playing = true; last = 0;
        b.textContent = 'pause'; b.classList.add('is-on'); b.setAttribute('aria-pressed', 'true');
        if (cutoff >= duration) setTime(0);
        frame = requestAnimationFrame(step);
      }

      // ---- controls --------------------------------------------------------------------
      function press(selector, button) {
        view.querySelectorAll(selector).forEach(function (b) {
          var on = b === button;
          b.classList.toggle('is-on', on);
          b.setAttribute('aria-pressed', String(on));
        });
      }
      function setBasemap(key) {
        if (key !== 'off' && !tiles[key]) return;
        basemap = key;
        press('[data-m3-style]', view.querySelector('[data-m3-style="' + key + '"]'));
        lastLight = null;
        map.setStyle(style(key));
        credit();
      }
      function setVertical(v) {
        vertical = v;
        press('[data-m3-vert]', view.querySelector('[data-m3-vert="' + v + '"]'));
        map.setTerrain({ source: 'dem', exaggeration: v });
        refresh();
      }
      function toggle(button, on) {
        button.classList.toggle('is-on', on);
        button.setAttribute('aria-pressed', String(on));
      }
      var help = view.querySelector('[data-m3="help"].view3d-keys');
      function fullscreen() {
        var maximise = function () {
          panel.classList.toggle('is-maximised');
          setTimeout(function () { map.resize(); }, 0);
        };
        if (document.fullscreenElement === panel) { document.exitFullscreen(); return; }
        if (panel.classList.contains('is-maximised')) { maximise(); return; }
        try {
          var p = panel.requestFullscreen && panel.requestFullscreen();
          if (p && p.catch) p.catch(maximise); else if (!p) maximise();
        } catch (error) { maximise(); }
      }
      document.addEventListener('fullscreenchange', function () { map.resize(); });

      view.addEventListener('click', function (event) {
        var b = event.target.closest('button, .view3d-keys');
        if (!b || !view.contains(b)) return;
        var act = b.dataset.m3;
        if (b.dataset.m3Style) setBasemap(b.dataset.m3Style);
        else if (b.dataset.m3Vert) setVertical(Number(b.dataset.m3Vert));
        else if (b.dataset.m3Label) {
          labels[b.dataset.m3Label] = !labels[b.dataset.m3Label];
          toggle(b, labels[b.dataset.m3Label]);
          refresh();
        } else if (act === 'airspace') { airspaceOn = !airspaceOn; toggle(b, airspaceOn); refresh(); }
        else if (act === 'zoom-in') map.zoomIn();
        else if (act === 'zoom-out') map.zoomOut();
        else if (act === 'help') help.hidden = !help.hidden;
        else if (act === 'fullscreen') fullscreen();
        else if (act === 'reset') fit(true);
        else if (act === 'play') togglePlay();
        else if (act === 'whole') { whole = !whole; toggle(b, whole); refresh(); }
      });
      // Arrows, shift + arrows and + / − are MapLibre's own keyboard handler, which maps
      // them the way the canvas view does. These are the rest of the canvas's keys.
      view.querySelector('.ml-map').addEventListener('keydown', function (event) {
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        var k = event.key, done = true;
        if (k === 's' || k === 'S') setBasemap('satellite');
        else if (k === 'm' || k === 'M') setBasemap('map');
        else if (k === 'r' || k === 'R') setBasemap('off');
        else if (k === '1' || k === '2' || k === '4') setVertical(Number(k));
        else if ((k === 'a' || k === 'A') && hasAirspace) view.querySelector('[data-m3="airspace"]').click();
        else if (k === 'f' || k === 'F') fullscreen();
        else if (k === '0') fit(true);
        else if (k === '?') help.hidden = !help.hidden;
        else if (k === 'Escape' && !help.hidden) help.hidden = true;
        else if (k === ' ') togglePlay();
        else done = false;
        if (done) event.preventDefault();
      });

      // ---- the linked cursor -----------------------------------------------------------
      function at(index) {
        if (!cursorTrack || index === null || index === undefined || index < 0
            || index >= cursorTrack.lon.length) return null;
        return [cursorTrack.lon[index], cursorTrack.lat[index], cursorTrack.alt[index]];
      }
      ['setCursor', 'revealCursor'].forEach(function (name) {
        var original = handle[name];
        if (typeof original !== 'function') return;
        handle[name] = function (index) {
          cursor = at(index);
          if (!view.hidden) {
            if (cursorTrack && cursorTrack.min && index !== null && index !== undefined) {
              sunTo(cursorTrack.min[Math.min(index, cursorTrack.min.length - 1)]);
            }
            refresh();
            if (name === 'revealCursor' && cursor) {
              var p = map.project([cursor[0], cursor[1]]), c = map.getContainer();
              var inset = 60;
              if (p.x < inset || p.y < inset || p.x > c.clientWidth - inset
                  || p.y > c.clientHeight - 110) map.easeTo({ center: [cursor[0], cursor[1]] });
            }
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

      window.__mergedAll = window.__mergedAll || {};
      window.__mergedAll[panel.querySelector('canvas.view3d').id] = {
        map: map, setTime: setTime, cursor: function () { return cursor; },
        setBasemap: setBasemap, setVertical: setVertical,
        state: function () {
          return { basemap: basemap, vertical: vertical, labels: labels, airspace: airspaceOn,
                   bearing: map.getBearing(), sunMinute: sunMinute };
        }
      };
    }, function (error) {
      view.querySelector('.m3-status').textContent =
        'MapLibre could not be loaded (' + error.message + '). It needs a network; the ' +
        'canvas view does not.';
    });
    return api;
  };
})();
"""

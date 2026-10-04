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
.merged-view .m3-rose svg { display: block; margin-left: auto; pointer-events: auto;
  cursor: pointer; }
.merged-view .m3-rose p { margin: 4px 0 0; font-size: 11px; line-height: 1.3; color: #fff;
  text-shadow: 0 0 3px rgba(12,14,18,0.95), 0 0 2px rgba(12,14,18,0.95); }
.merged-view .m3-bottom { position: absolute; left: 10px; right: 10px; bottom: 10px; z-index: 3;
  display: flex; flex-wrap: wrap; align-items: center; gap: 5px; pointer-events: none; }
.merged-view .m3-bottom > * { pointer-events: auto; }
.merged-view .m3-bottom .view3d-controls { position: static; margin-left: auto; }
.merged-view .m3-replay { display: flex; gap: 5px; align-items: center; }
.merged-view .m3-replay[hidden], .merged-view .m3-time[hidden],
.merged-view .view3d-controls[hidden] { display: none; }
.merged-view .m3-replay button { font: inherit; font-size: 11px; letter-spacing: 0.06em;
  text-transform: uppercase; padding: 6px 9px; cursor: pointer; color: var(--ink-2);
  background: var(--panel); border: 1px solid var(--rule); border-radius: 2px; }
.merged-view .m3-replay button:hover { color: var(--ink); background: var(--panel-2); }
.merged-view .m3-replay button.is-on { background: var(--climb); border-color: var(--climb);
  color: var(--paper); }
.merged-view .m3-icon svg { display: block; }
.merged-view .m3-cycle { min-width: 3.2em; }
.merged-view .view3d-controls { flex-wrap: wrap; }
.merged-view .m3-speed { display: flex; align-items: center; }
.merged-view .m3-speed button { border-radius: 0; }
.merged-view .m3-speed button:first-child { border-radius: 2px 0 0 2px; }
.merged-view .m3-speed button:last-child { border-radius: 0 2px 2px 0; }
.merged-view .m3-speed button:disabled { opacity: 0.4; cursor: default; }
.merged-view .m3-rate { min-width: 64px; text-align: center; font-size: 12px; color: var(--ink);
  font-variant-numeric: tabular-nums; background: var(--panel); border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule); padding: 5px 4px; }
.merged-view .m3-time { flex: 1 1 100%; display: flex; gap: 8px; align-items: center;
  background: var(--panel); border: 1px solid var(--rule); border-radius: 2px;
  padding: 3px 9px; font-size: 12px; color: var(--ink); font-variant-numeric: tabular-nums; }
.merged-view .m3-clock { white-space: nowrap; }
/* Two range inputs stacked on one track: each input ignores the pointer and only its
   thumb takes it, so either handle can be grabbed wherever the two sit. */
.merged-view .m3-range { position: relative; flex: 1; height: 22px; }
.merged-view .m3-range::before { content: ""; position: absolute; left: 0; right: 0; top: 9px;
  height: 4px; border-radius: 2px; background: var(--rule); }
.merged-view .m3-fill { position: absolute; top: 9px; height: 4px; border-radius: 2px;
  background: var(--climb); }
.merged-view .m3-range input { position: absolute; left: 0; top: 0; width: 100%; height: 22px;
  margin: 0; background: none; pointer-events: none; -webkit-appearance: none; appearance: none; }
.merged-view .m3-range input::-webkit-slider-runnable-track { background: none; height: 22px; }
.merged-view .m3-range input::-moz-range-track { background: none; }
.merged-view .m3-range input::-webkit-slider-thumb { -webkit-appearance: none; appearance: none;
  pointer-events: auto; width: 16px; height: 16px; margin-top: 3px; border-radius: 50%;
  background: var(--paper, #fff); border: 2px solid var(--climb); cursor: grab; }
.merged-view .m3-range input::-moz-range-thumb { pointer-events: auto; width: 12px; height: 12px;
  border-radius: 50%; background: var(--paper, #fff); border: 2px solid var(--climb); cursor: grab; }
@media (pointer: coarse) {
  .merged-view .m3-range input::-webkit-slider-thumb { width: 22px; height: 22px; margin-top: 0; }
}
.merged-view .m3-status { position: absolute; left: 12px; top: 34px; z-index: 3; margin: 0;
  font-size: 12px; color: var(--ink-2); }
/* MapLibre's own credits, the openable kind: an (i) at the top left that opens to name
   every source on screen. Top left because the rose holds the top right and the
   controls the bottom. */
.merged-view .maplibregl-ctrl-top-left { z-index: 3; }
.merged-view .maplibregl-ctrl-attrib { font-size: 11px; }
/* Last, so it wins over the rules above it at equal specificity. */
/* A phone: the bar stays one row; where it and the replay buttons do not fit side by
   side, the bar wraps under them, still at the right. */
@media (max-width: 640px) {
  .merged-view .view3d-controls { flex-wrap: nowrap; justify-content: flex-end; }
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
  // The canvas view strokes its track 2.6 px wide on a backing store of up to twice the
  // screen's density, so on a phone it is 1.3 CSS px and on a desktop 2.6. deck.gl's
  // pixels are CSS pixels, so the same line takes the same arithmetic.
  var TRACK_WIDTH = 2.6 / Math.min(window.devicePixelRatio || 1, 2);
  var PLAY_ICON = '<svg width="11" height="12" viewBox="0 0 11 12" aria-hidden="true">' +
    '<path d="M1 1 L10 6 L1 11 Z" fill="currentColor"/></svg>';
  var PAUSE_ICON = '<svg width="11" height="12" viewBox="0 0 11 12" aria-hidden="true">' +
    '<path d="M1.5 1h3v10h-3zM6.5 1h3v10h-3z" fill="currentColor"/></svg>';
  function rgb(hex, alpha) {
    var v = parseInt(String(hex).replace('#', ''), 16);
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255, alpha];
  }

  // The track as runs of one colour: the palette index per fix is the canvas view's own.
  // Each run carries its fixes' times too, so the track can be cut to a window of the
  // flight (the from-to slider) by a TripsLayer rather than rebuilt on every drag.
  function segments(scene) {
    var tr = scene.track, out = [], run = [], times = [], colour = null;
    var t = tr.t || [];
    for (var i = 0; i < tr.lon.length; i++) {
      var point = [tr.lon[i], tr.lat[i], tr.alt[i]];
      run.push(point);
      times.push(t[i] || 0);
      if (colour === null) colour = tr.c[i];
      if (tr.c[i] !== colour) {
        if (run.length > 1) out.push({ path: run, times: times, colour: scene.palette[colour] });
        run = [point];
        times = [t[i] || 0];
        colour = tr.c[i];
      }
    }
    if (run.length > 1) out.push({ path: run, times: times, colour: scene.palette[colour] });
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
      '<dt>space</dt><dd>replay: open, play, pause</dd>' +
      '<dt>f</dt><dd>full screen</dd>' +
      '<dt>0</dt><dd>reset view</dd></dl>' +
      '<p class="view3d-keys-foot">Hovering the charts moves the marker here too. ' +
      'Click this list to close it.</p>';
  }

  // Tiles below a source's `consistent_from` level, built from that level's tiles. For
  // Esri the levels under 12 are a different, darker mosaic, so a map that ever shows
  // them jumps colour as the zoom crosses the line — and at a tilt the far half of the
  // view always sits on them. One level down costs 4 requests, two levels 16; deeper
  // than that (64+) the native tile is used, which only the far horizon ever asks for.
  var STITCH_LEVELS = 2;
  function registerStitching() {
    if (window.__m3Stitching) return;
    window.__m3Stitching = true;
    maplibregl.addProtocol('m3tiles', function (params, abortController) {
      var parts = params.url.slice('m3tiles://'.length).split('/');
      var template = decodeURIComponent(parts[0]);
      var from = +parts[1], z = +parts[2], x = +parts[3], y = +parts[4];
      var signal = abortController.signal;
      function url(zz, xx, yy) {
        return template.replace('{z}', zz).replace('{x}', xx).replace('{y}', yy);
      }
      function image(src) {
        return fetch(src, { signal: signal }).then(function (response) {
          if (!response.ok) throw new Error(response.status + ' ' + src);
          return response.blob();
        }).then(function (blob) { return createImageBitmap(blob); });
      }
      if (z >= from || z < from - STITCH_LEVELS) {
        return fetch(url(z, x, y), { signal: signal }).then(function (response) {
          if (!response.ok) throw new Error(response.status + ' ' + url(z, x, y));
          return response.arrayBuffer();
        }).then(function (data) { return { data: data }; });
      }
      var k = 1 << (from - z), size = 512, cell = size / k;
      var canvas = document.createElement('canvas');
      canvas.width = canvas.height = size;
      var ctx = canvas.getContext('2d');
      ctx.imageSmoothingQuality = 'high';
      var jobs = [];
      for (var i = 0; i < k; i++) for (var j = 0; j < k; j++) {
        jobs.push((function (i, j) {
          return image(url(from, x * k + i, y * k + j)).then(function (bitmap) {
            ctx.drawImage(bitmap, i * cell, j * cell, cell, cell);
          }, function () { return null; });   // a missing child is a hole, not a failure
        })(i, j));
      }
      // Handed over as an ImageBitmap, which MapLibre takes from a protocol as it is. It
      // went through `toBlob('image/jpeg')` and back, an encode on the main thread and a
      // decode after it for every stitched tile: the imagery arrived in five seconds and
      // took thirty to appear, a patch at a time.
      return Promise.all(jobs).then(function () {
        return createImageBitmap(canvas);
      }).then(function (bitmap) { return { data: bitmap }; });
    });
  }

  // Whether a map's WebGL is gone: MapLibre's canvas or deck.gl's. A phone takes the
  // contexts of a page it backgrounds or locks and often never gives them back, and the
  // view then stays black while every button still answers.
  function contextLost(view) {
    return Array.prototype.some.call(view.querySelectorAll('canvas'), function (canvas) {
      var gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      return !!(gl && gl.isContextLost());
    });
  }

  // `restore` is a snapshot from a view being rebuilt after its context was lost: the
  // camera and every setting come back as the reader left them.
  window.__mountMerged = function (host, handle, restore) {
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
    // A flight's map offers its airspace behind a switch; the airspace map *is* its
    // airspace, so a scene with rings and no switch draws them always.
    var hasAirspace = !!(scene.airspaceToggle && scene.airspaces && scene.airspaces.length);
    // Offered but empty: the page has airspace, none of it under this flight.
    var noAirspace = !!(scene.airspaceToggle && !hasAirspace);
    var alwaysAirspace = !!(!scene.airspaceToggle && scene.airspaces && scene.airspaces.length);
    // The exaggerations this panel offers, and the one it opens on, are the canvas
    // panel's own (`view3d.panel(verticals=…)`): ×1/2/4 under a flight, ×1/5/15 under a
    // country of airspace, where a traffic circuit at ×1 is a third of a pixel tall.
    var offered = Array.prototype.map.call(
      panel.querySelectorAll('[data-view3d-act="exaggerate-set"]'),
      function (b) { return parseFloat(b.dataset.vertical); }).filter(function (v) { return v > 0; });
    var pressed = panel.querySelector('[data-view3d-act="exaggerate-set"].is-on');
    var openVertical = pressed ? parseFloat(pressed.dataset.vertical) : 1;
    var hasPhases = !!(scene.phases && scene.phases.length);

    var view = document.createElement('div');
    view.className = 'maplibre-view merged-view';
    view.innerHTML =
      '<div class="ml-map" tabindex="0" aria-label="Interactive three-dimensional map of the ' +
        'flight. Arrow keys pan and shift with them turns and tilts; press question mark ' +
        'for the key list."></div>' +
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
      // The bottom of the map, in one flowing box: the slider across the full width, and
      // under it the replay's own buttons at the left and the bar at the right. On a phone
      // the two groups do not fit one line, and wrap onto two. The replay half is hidden
      // until the bar's play button opens it: most of the time the reader wants the whole
      // flight, and a slider parked at the end is a row of nothing.
      '<div class="m3-bottom">' +
      (hasTime ?
        // Two handles on one bar: the track is drawn between them. Left hides the start of
        // the flight where it overlaps the rest; right is the replay's "now". Both at the
        // ends is the whole track, and a double click puts them there.
        '<div class="m3-time" hidden><span class="m3-clock"></span>' +
          '<div class="m3-range" title="Drag either end; double-click for the whole flight">' +
            '<div class="m3-fill"></div>' +
            '<input type="range" class="m3-from" min="0" max="' + duration + '" step="1" value="0"' +
            ' aria-label="Show the track from">' +
            '<input type="range" class="m3-to" min="0" max="' + duration + '" step="1"' +
            ' value="' + duration + '" aria-label="Show the track to">' +
          '</div></div>' +
        '<div class="m3-replay" hidden>' +
          '<button type="button" data-m3="play" class="m3-icon" aria-pressed="false"' +
          ' title="Play / pause (space)" aria-label="Play">' + PLAY_ICON + '</button>' +
          '<div class="m3-speed" role="group" aria-label="Replay speed">' +
            '<button type="button" data-m3="slower" title="Slower" aria-label="Slower">&minus;</button>' +
            '<span class="m3-rate" aria-live="polite"></span>' +
            '<button type="button" data-m3="faster" title="Faster" aria-label="Faster">+</button>' +
          '</div>' +
        '</div>' : '') +
      '<div class="view3d-controls" hidden>' +
        // One button each, naming what is on and stepping to the next: two segmented
        // groups of three were six of the bar's slots, and on a phone the bar is one row.
        '<button type="button" data-m3="ground" class="m3-cycle"></button>' +
        '<button type="button" data-m3="vertical" class="m3-cycle"></button>' +
        (hasPhases ?
          '<div class="view3d-seg view3d-labels" role="group" aria-label="Phase labels">' +
          '<button type="button" data-m3-label="climb" aria-pressed="false"' +
          ' aria-label="Label each climb with its rate and gain">climbs</button>' +
          '<button type="button" data-m3-label="glide" aria-pressed="false"' +
          ' aria-label="Label each glide with its ratio and distance">glides</button></div>' : '') +
        (hasAirspace ?
          '<div class="view3d-seg view3d-airspace" role="group" aria-label="Airspace">' +
          '<button type="button" data-m3="airspace" aria-pressed="false"' +
          ' aria-label="Draw the airspace over this flight">airspace</button></div>' :
         noAirspace ?
          '<div class="view3d-seg view3d-airspace" role="group" aria-label="Airspace">' +
          '<button type="button" data-m3="airspace" aria-pressed="false" disabled' +
          ' title="No airspace data under this flight — the layer covers Czechia only" aria-label="No airspace data under this flight — the layer covers Czechia only">airspace</button></div>' : '') +
        '<div class="view3d-seg view3d-zoom" role="group" aria-label="Zoom">' +
          '<button type="button" data-m3="zoom-out" title="Zoom out" aria-label="Zoom out">&minus;</button>' +
          '<button type="button" data-m3="zoom-in" title="Zoom in" aria-label="Zoom in">+</button></div>' +
        (hasTime ? '<button type="button" data-m3="replay" class="m3-icon" aria-pressed="false"' +
          ' title="Replay the flight" aria-label="Replay the flight">' + PLAY_ICON + '</button>' : '') +
        '<button type="button" data-m3="help" title="Controls" aria-label="How to control this view">?</button>' +
        '<button type="button" data-m3="fullscreen" title="Full screen" aria-label="Full screen">' +
          '<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor"' +
          ' stroke-width="1.5"><path d="M1 4.5V1h3.5M8.5 1H12v3.5M12 8.5V12H8.5M4.5 12H1V8.5"/></svg></button>' +
        '<button type="button" class="view3d-reset" data-m3="reset" title="Reset view"' +
        ' aria-label="Reset view">&#8634;</button>' +
      '</div></div>';
    panel.appendChild(view);

    var playing = false, frame = null, map = null;
    function pause() {
      playing = false;
      if (frame) cancelAnimationFrame(frame);
      var b = view.querySelector('[data-m3="play"]');
      if (b) {
        b.innerHTML = PLAY_ICON; b.classList.remove('is-on');
        b.setAttribute('aria-pressed', 'false'); b.setAttribute('aria-label', 'Play');
      }
    }
    var api = {
      view: view,
      show: function () { view.hidden = false; if (map) map.resize(); },
      hide: function () { view.hidden = true; pause(); }
    };

    window.__mapLibs().then(function () {
      registerStitching();
      view.querySelector('.m3-status').hidden = true;
      view.querySelector('.view3d-controls').hidden = false;
      var replay = view.querySelector('.m3-replay');
      var timeRow = view.querySelector('.m3-time');

      // A rebuilt view starts on the basemap and exaggeration it was left on, built into
      // its first style rather than set over it: setting them before that style has
      // loaded throws inside this callback, and the rebuild silently never finished.
      var vertical = restore ? restore.vertical : (openVertical > 0 ? openVertical : 1);
      var cursor = null, from = 0, cutoff = duration;
      if (restore) basemap = restore.basemap;
      var labels = { climb: false, glide: false }, airspaceOn = alwaysAirspace;
      // The canvas handle's airspace filter (class, floor, hours), followed here: the
      // page's controls set it on that handle, and the two maps must hide the same rings.
      var airspaceFilter = handle.airspaceFilter ? handle.airspaceFilter() : null;
      var route = null;       // a planned task: { walk: [[lon, lat]…], points: [[lon, lat]…] }
      var clickers = [];
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
      // How strongly the ground is shaded: lightly over a photograph or a map, fully on
      // bare relief, where the shading *is* the picture. Two layers with fixed paint,
      // switched by visibility like the basemaps — changing one layer's paint between
      // the two left tiles shaded the old way under the 3D terrain: white streaks down
      // every slope after satellite, relief, satellite.
      function shading(over) {
        return {
          'hillshade-exaggeration': over ? 0.45 : 1,
          'hillshade-highlight-color': over ? 'rgba(255,252,242,0.45)' : 'rgba(255,252,242,1)',
          'hillshade-shadow-color': over ? 'rgba(18,26,38,0.7)' : 'rgba(18,26,38,1)',
          'hillshade-accent-color': 'rgba(0,0,0,0)',
          'hillshade-illumination-anchor': 'map',
          'hillshade-illumination-direction': sun ? ((sunAt(sunMinute).az % 360) + 360) % 360 : 315
        };
      }
      var SHADES = ['hillshade-over', 'hillshade-relief'];
      function shadeFor(key) { return key === 'off' ? 'hillshade-relief' : 'hillshade-over'; }
      // Every basemap in one style, and a switch shows one and hides the rest. Swapping
      // whole styles with `setStyle` was the first version, and three quick presses left
      // the map with no imagery and no terrain: MapLibre does not survive a style change
      // arriving while the last one is still loading. A hidden layer fetches no tiles,
      // so carrying all of them costs nothing until one is shown.
      function style(key) {
        var sources = {
          // Declared at half their size so MapLibre asks one zoom deeper than it would:
          // four times the tiles, and relief and imagery as sharp as the canvas's grid.
          // At their natural size the DEM it picks is ~4x coarser and the hills read flat.
          dem: { type: 'raster-dem', tiles: [window.__mapTerrarium], tileSize: 128, maxzoom: 15,
                 encoding: 'terrarium', attribution: 'Terrain: AWS Open Data Terrain Tiles' },
          // Its own source for the shading: MapLibre renders both worse when the hillshade
          // and the 3D terrain share one.
          shade: { type: 'raster-dem', tiles: [window.__mapTerrarium], tileSize: 128, maxzoom: 15,
                   encoding: 'terrarium' }
        };
        var below = [{ id: 'bg', type: 'background', paint: { 'background-color': '#d6d2c4' } }];
        var above = [];
        styles.forEach(function (name) {
          var source = tiles[name];
          source.layers.forEach(function (template, i) {
            var id = name + '-' + i;
            // The photograph at half size (sharper), a label layer at full size — halved,
            // its lettering would be too small to read.
            var consistent = !i && source.consistent_from;
            sources[id] = { type: 'raster', tileSize: i ? 256 : 128,
                            maxzoom: source.max_zoom || 18,
                            tiles: [consistent
                              ? 'm3tiles://' + encodeURIComponent(template) + '/' +
                                source.consistent_from + '/{z}/{x}/{y}'
                              : template] };
            if (!i && source.attribution) sources[id].attribution = source.attribution;
            // A slight lift on the picture itself: the raw Esri mosaic is dark next to the
            // canvas's, which the shading's highlights brighten on the sunlit side.
            (i ? above : below).push({
              id: id, type: 'raster', source: id,
              layout: { visibility: name === key ? 'visible' : 'none' },
              paint: i ? { 'raster-fade-duration': 150 }
                       : { 'raster-fade-duration': 150, 'raster-brightness-min': 0.06,
                           'raster-contrast': 0.05 }
            });
          });
        });
        // The canvas view's own shading, not MapLibre's default: sunlit slopes lifted
        // towards a warm white and shaded ones towards a dark blue, lit from where the sun
        // was. Black-and-white shading over the photograph is what greyed it out. Under
        // any label layer, so place names stay crisp.
        var shades = SHADES.map(function (id) {
          return { id: id, type: 'hillshade', source: 'shade', paint: shading(id === 'hillshade-over'),
                   layout: { visibility: id === shadeFor(key) ? 'visible' : 'none' } };
        });
        return {
          version: 8, sources: sources,
          // No paint transitions: the sun's direction moves in steps with the cursor, and
          // a half-finished transition is one more way for tiles to disagree.
          transition: { duration: 0, delay: 0 },
          layers: below.concat(shades, above),
          // MapLibre's own sky and haze, every value its default: the distance fades into
          // the horizon the way air does, which is what reads as depth at a low pitch.
          sky: {},
          terrain: { source: 'dem', exaggeration: vertical }
        };
      }

      var dem = scene.terrain || {};
      // What to open on: the flight; else the part of the ground the scene names
      // (`view.focus` — the airspace map opens on Czechia, not on the Alps beside it);
      // else the whole ground.
      var focus = (scene.view && scene.view.focus) || dem;
      var west = tr.lon.length ? Math.min.apply(null, tr.lon) : focus.west;
      var east = tr.lon.length ? Math.max.apply(null, tr.lon) : focus.east;
      var south = tr.lat.length ? Math.min.apply(null, tr.lat) : focus.south;
      var north = tr.lat.length ? Math.max.apply(null, tr.lat) : focus.north;
      // The canvas's opening pitch is the camera's elevation angle; MapLibre's is the tilt
      // from straight down.
      var openPitch = scene.view && typeof scene.view.pitch === 'number' && !tr.lon.length
        ? Math.max(0, 90 - scene.view.pitch * 180 / Math.PI) : 60;
      var styleReady = false;
      map = new maplibregl.Map({
        container: view.querySelector('.ml-map'), style: style(basemap),
        center: [(west + east) / 2, (south + north) / 2], zoom: 10, pitch: openPitch, bearing: 0,
        maxPitch: 85, attributionControl: false, keyboard: true
      });
      // 'style.load', not 'load': 'load' waits for the first complete frame, every tile
      // included, which on a slow connection is long after a reader has pressed things.
      map.once('style.load', function () {
        styleReady = true;
        if (vertical !== 1) map.setTerrain({ source: 'dem', exaggeration: vertical });
      });
      // Credits from the sources themselves, so switching the basemap changes them.
      map.addControl(new maplibregl.AttributionControl({ compact: true }), 'top-left');
      // Start closed: MapLibre opens a compact control on a wide map, and the credits then
      // sit over the flight until someone closes them.
      // MapLibre opens it by itself the moment the first credit text arrives from a source,
      // so close it on that first opening and leave every later one to the reader.
      (function () {
        var box = view.querySelector('.maplibregl-ctrl-attrib');
        if (!box || !window.MutationObserver) return;
        var watch = new MutationObserver(function () {
          if (!box.classList.contains('maplibregl-compact-show')) return;
          box.classList.remove('maplibregl-compact-show');
          box.removeAttribute('open');
          watch.disconnect();
        });
        watch.observe(box, { attributes: true, attributeFilter: ['class'] });
      })();

      // The canvas view's mouse: a left drag with any modifier — shift, ctrl, alt or meta —
      // rotates and tilts, as a right drag does. MapLibre only knows ctrl and the right
      // button, and gives shift-drag to a box zoom the canvas never had.
      //
      // And it turns about the ground that was grabbed, as the canvas does
      // (`pickAnchor`/`holdGround` in view3d.py), not about the middle of the map: the
      // point under the pointer is found on the terrain at pointerdown, and after every
      // step the map is panned so that point is back under where it was grabbed. The
      // pivot is clamped into the middle half of the canvas for the canvas's reason — a
      // pivot at the edge puts the whole view on a long lever.
      map.boxZoom.disable();
      (function () {
        var surface = map.getCanvasContainer(), last = null, pivot = null;
        var ANCHOR_INSET = 0.25;
        function pickPivot(event) {
          var box = surface.getBoundingClientRect();
          var x = Math.min(Math.max(event.clientX - box.left, box.width * ANCHOR_INSET),
                           box.width * (1 - ANCHOR_INSET));
          var y = Math.min(Math.max(event.clientY - box.top, box.height * ANCHOR_INSET),
                           box.height * (1 - ANCHOR_INSET));
          try {
            var ground = map.unproject([x, y]);
            return ground ? { point: [x, y], ground: ground } : null;
          } catch (e) { return null; }
        }
        function holdPivot() {
          if (!pivot) return;
          // A few passes: over terrain the centre's own height moves with the pan, so one
          // correction lands near the point rather than on it.
          for (var pass = 0; pass < 4; pass++) {
            var now = map.project(pivot.ground);
            if (!isFinite(now.x) || !isFinite(now.y)) return;
            var dx = now.x - pivot.point[0], dy = now.y - pivot.point[1];
            if (Math.abs(dx) < 0.25 && Math.abs(dy) < 0.25) return;
            map.panBy([dx, dy], { animate: false });
          }
        }
        api.pivot = function () { return pivot; };
        function modified(event) {
          return event.button === 0 && (event.shiftKey || event.altKey || event.metaKey);
        }
        surface.addEventListener('pointerdown', function (event) {
          if (!modified(event)) return;
          // Ahead of MapLibre's own handlers, which would otherwise start a pan.
          event.preventDefault();
          event.stopImmediatePropagation();
          last = { x: event.clientX, y: event.clientY };
          pivot = pickPivot(event);
          try { surface.setPointerCapture(event.pointerId); } catch (e) { /* synthetic */ }
        }, true);
        surface.addEventListener('pointermove', function (event) {
          if (!last) return;
          event.stopImmediatePropagation();
          // MapLibre's own right-drag rates, so the two gestures turn the view alike.
          map.jumpTo({ bearing: map.getBearing() + (event.clientX - last.x) * 0.8,
                       pitch: map.getPitch() - (event.clientY - last.y) * 0.5 });
          holdPivot();
          last = { x: event.clientX, y: event.clientY };
        }, true);
        function end(event) {
          if (!last) return;
          last = null;
          pivot = null;
          event.stopImmediatePropagation();
        }
        surface.addEventListener('pointerup', end, true);
        surface.addEventListener('pointercancel', end, true);
        // MapLibre listens for the mouse events a browser fires *alongside* pointer events,
        // so those have to stop too or it pans underneath the turn.
        ['mousedown', 'mousemove', 'mouseup'].forEach(function (type) {
          surface.addEventListener(type, function (event) {
            if (last || (type === 'mousedown' && modified(event))) {
              event.preventDefault();
              event.stopImmediatePropagation();
            }
          }, true);
        });
      })();
      function fit(animate) {
        if (!(west < east || south < north)) return;
        map.fitBounds([[west, south], [east, north]],
                      { padding: { top: 70, bottom: 110, left: 50, right: 90 },
                        pitch: openPitch, bearing: 0, duration: animate ? 600 : 0 });
      }
      if (!restore) fit(false);

      // ---- what is drawn over it -----------------------------------------------------
      // The canvas view's labels: the phase as a span from where it began to where it
      // ended, dots at both ends, and its numbers in white over the middle — no box.
      // When a point on the track was flown: the time of the nearest fix. The climbs and
      // the phases arrive as places, not times, and the from-to window hides by time.
      function flownAt(lon, lat) {
        if (!hasTime) return 0;
        var best = 0, bestD = Infinity;
        for (var i = 0; i < tr.lon.length; i++) {
          var d = (tr.lon[i] - lon) * (tr.lon[i] - lon) + (tr.lat[i] - lat) * (tr.lat[i] - lat);
          if (d < bestD) { bestD = d; best = i; }
        }
        return tr.t[best];
      }
      // The track from the left handle on. TripsLayer hides what is after `currentTime`
      // (the right handle) but only cuts the start of the trail when it is *fading* it, and
      // this one does not fade — so the left handle moved and the track stayed. Cut here
      // instead, and only when the handle has moved: each run sliced from its first fix at
      // or after `from`.
      var clippedFrom = 0, clipped = lines;
      function linesFrom() {
        if (from === clippedFrom) return clipped;
        clippedFrom = from;
        clipped = [];
        lines.forEach(function (run) {
          var times = run.times, lo = 0, hi = times.length;
          while (lo < hi) { var mid = (lo + hi) >> 1; if (times[mid] < from) lo = mid + 1; else hi = mid; }
          if (times.length - lo < 2) return;
          clipped.push(lo ? { path: run.path.slice(lo), times: times.slice(lo), colour: run.colour } : run);
        });
        return clipped;
      }
      function inWindow(t) { return !hasTime || (t >= from - 1 && t <= cutoff + 1); }
      var marks = (scene.climbs || []).map(function (c) {
        return { label: c.label, tow: c.tow, position: [c.lon, c.lat, c.alt], t: flownAt(c.lon, c.lat) };
      });
      var phaseLabels = (scene.phases || []).map(function (p) {
        return { kind: p.kind, text: p.text,
                 t: [flownAt(p.lon[0], p.lat[0]), flownAt(p.lon[1], p.lat[1])],
                 colour: p.kind === 'climb' ? [235, 104, 52, 242] : [42, 120, 214, 242],
                 ends: [[p.lon[0], p.lat[0], p.alt[0]], [p.lon[1], p.lat[1], p.alt[1]]],
                 position: [(p.lon[0] + p.lon[1]) / 2, (p.lat[0] + p.lat[1]) / 2,
                            (p.alt[0] + p.alt[1]) / 2] };
      });
      var boxes = (hasAirspace || alwaysAirspace) ? scene.airspaces.map(function (ring) {
        var low = Infinity, high = -Infinity;
        if (ring.g || ring.fu !== undefined || ring.cu !== undefined) {
          ring.lon.forEach(function (lon, i) {
            var g = ground(lon, ring.lat[i]);
            low = Math.min(low, g); high = Math.max(high, g);
          });
        }
        var floor = ring.g ? low : (ring.fu !== undefined ? low + ring.fu : ring.f);
        var top = ring.cu !== undefined ? high + ring.cu : ring.c;
        return { space: ring, name: ring.n, colour: (scene.airspaceColours || {})[ring.k] || '#888888',
                 ring: ring.lon.map(function (lon, i) { return [lon, ring.lat[i]]; }),
                 floor: floor, top: Math.max(top, floor + 30), capped: !!ring.t };
      }) : [];

      function layers() {
        var out = [];
        var drawn = airspaceFilter ? boxes.filter(function (d) { return airspaceFilter(d.space); })
                                   : boxes;
        if (airspaceOn && drawn.length) {
          out.push(new deck.SolidPolygonLayer({
            id: 'airspace', data: drawn, extruded: true, wireframe: false, pickable: true,
            getPolygon: function (d) { return d.ring.map(function (p) { return [p[0], p[1], z(d.floor)]; }); },
            getElevation: function (d) { return (d.top - d.floor) * vertical; },
            getFillColor: function (d) { return rgb(d.colour, 46); },
            material: false, updateTriggers: { getPolygon: vertical, getElevation: vertical }
          }));
          out.push(new deck.PathLayer({
            id: 'airspace-edges', data: drawn.reduce(function (all, d) {
              var shut = d.ring.concat([d.ring[0]]);
              all.push({ colour: d.colour, path: shut.map(function (p) { return [p[0], p[1], z(d.floor)]; }) });
              all.push({ colour: d.colour, path: shut.map(function (p) { return [p[0], p[1], z(d.top)]; }) });
              return all;
            }, []),
            getPath: function (d) { return d.path; }, getColor: function (d) { return rgb(d.colour, 200); },
            getWidth: 1.2, widthUnits: 'pixels', updateTriggers: { data: vertical }
          }));
          // The corners' vertical edges, where a zone has corners (as the canvas view).
          out.push(new deck.LineLayer({
            id: 'airspace-corners', data: drawn.reduce(function (all, d) {
              if (d.ring.length > 24) return all;
              d.ring.forEach(function (p) { all.push({ colour: d.colour, p: p, floor: d.floor, top: d.top }); });
              return all;
            }, []),
            getSourcePosition: function (d) { return [d.p[0], d.p[1], z(d.floor)]; },
            getTargetPosition: function (d) { return [d.p[0], d.p[1], z(d.top)]; },
            getColor: function (d) { return rgb(d.colour, 150); }, getWidth: 1,
            updateTriggers: { getSourcePosition: vertical, getTargetPosition: vertical }
          }));
        }
        // A planned task (the planner on the airspace page): the course 60 m over the
        // ground, as the canvas draws it, and the turnpoints numbered.
        if (route && route.walk.length > 1) {
          out.push(new deck.PathLayer({
            id: 'plan-line', data: [route.walk],
            getPath: function (d) {
              return d.map(function (p) { return [p[0], p[1], z(ground(p[0], p[1]) + 60)]; });
            },
            getColor: [255, 255, 255, 235], getWidth: 3, widthUnits: 'pixels',
            capRounded: true, jointRounded: true, billboard: true,
            updateTriggers: { getPath: vertical }, parameters: ON_TOP
          }));
        }
        if (route && route.points.length) {
          var tps = route.points.map(function (p, i) {
            return { label: String(i + 1), position: [p[0], p[1], ground(p[0], p[1]) + 60] };
          });
          out.push(new deck.ScatterplotLayer({
            id: 'plan-points', data: tps,
            getPosition: function (d) { return [d.position[0], d.position[1], z(d.position[2])]; },
            getFillColor: [226, 96, 44], getLineColor: [255, 255, 255], stroked: true,
            lineWidthMinPixels: 1.5, radiusUnits: 'pixels', getRadius: 9, billboard: true,
            updateTriggers: { getPosition: vertical }, parameters: ON_TOP
          }));
          out.push(new deck.TextLayer({
            id: 'plan-labels', data: tps, getText: function (d) { return d.label; },
            getPosition: function (d) { return [d.position[0], d.position[1], z(d.position[2])]; },
            getSize: 11, fontWeight: 700, getColor: [255, 255, 255],
            fontFamily: 'ui-sans-serif, system-ui, sans-serif',
            updateTriggers: { getPosition: vertical }, parameters: ON_TOP
          }));
        }
        if (!hasTime) out.push(new deck.PathLayer({
          id: 'track', data: lines,
          getPath: function (d) { return d.path.map(function (p) { return [p[0], p[1], z(p[2])]; }); },
          getColor: function (d) { return d.colour; }, getWidth: TRACK_WIDTH, widthUnits: 'pixels',
          capRounded: true, jointRounded: true, billboard: true,
          updateTriggers: { getPath: vertical }
        }));
        // The track between the two handles, in its climb colours: a trip whose "now" is
        // the right handle and whose trail reaches back to the left one, unfaded.
        if (hasTime) out.push(new deck.TripsLayer({
          id: 'track', data: linesFrom(),
          getPath: function (d) { return d.path.map(function (p) { return [p[0], p[1], z(p[2])]; }); },
          getTimestamps: function (d) { return d.times; },
          getColor: function (d) { return d.colour; }, getWidth: TRACK_WIDTH, widthUnits: 'pixels',
          currentTime: cutoff, trailLength: Math.max(cutoff - from, 0) + 0.5, fadeTrail: false,
          capRounded: true, jointRounded: true, updateTriggers: { getPath: vertical }
        }));
        // While the replay runs, its leading edge: the last seven minutes in white.
        if (hasTime && replay && !replay.hidden) out.push(new deck.TripsLayer({
          id: 'replay', data: [{ path: tr.lon.map(function (lon, i) { return [lon, tr.lat[i], tr.alt[i]]; }),
                                 times: tr.t }],
          getPath: function (d) { return d.path.map(function (p) { return [p[0], p[1], z(p[2])]; }); },
          getTimestamps: function (d) { return d.times; },
          getColor: [255, 255, 255], getWidth: TRACK_WIDTH * 1.5, widthUnits: 'pixels',
          trailLength: Math.min(420, Math.max(cutoff - from, 0)), currentTime: cutoff,
          capRounded: true, jointRounded: true, updateTriggers: { getPath: vertical }
        }));
        // Where each climb was, as a dot: the numbers crowded the track and said nothing
        // the climbs table does not.
        out.push(new deck.ScatterplotLayer({
          id: 'climbs', data: marks.filter(function (d) { return inWindow(d.t); }),
          getPosition: function (d) { return [d.position[0], d.position[1], z(d.position[2])]; },
          getFillColor: function (d) { return d.tow ? [27, 175, 122] : [226, 96, 44]; },
          getLineColor: [255, 255, 255, 220], stroked: true, lineWidthMinPixels: 1,
          radiusUnits: 'pixels', getRadius: 4, billboard: true, updateTriggers: { getPosition: vertical },
          parameters: ON_TOP
        }));
        if (scene.landing && inWindow(duration)) out.push(new deck.ScatterplotLayer({
          id: 'landing', data: [scene.landing],
          getPosition: function (d) { return [d.lon, d.lat, z(d.alt)]; },
          getFillColor: [20, 22, 26], getLineColor: [255, 255, 255], stroked: true,
          lineWidthMinPixels: 2, radiusUnits: 'pixels', getRadius: 6, billboard: true,
          updateTriggers: { getPosition: vertical }, parameters: ON_TOP
        }));
        var shown = phaseLabels.filter(function (p) {
          return labels[p.kind] && inWindow(p.t[0]) && inWindow(p.t[1]);
        });
        if (shown.length) {
          var lift = function (p) { return [p[0], p[1], z(p[2])]; };
          out.push(new deck.PathLayer({
            id: 'phase-spans', data: shown,
            getPath: function (d) { return d.ends.map(lift); },
            getColor: function (d) { return d.colour; }, getWidth: 2, widthUnits: 'pixels',
            capRounded: true, billboard: true, updateTriggers: { getPath: vertical },
            parameters: ON_TOP
          }));
          out.push(new deck.ScatterplotLayer({
            id: 'phase-ends', data: shown.reduce(function (all, d) {
              return all.concat([{ p: d.ends[0], c: d.colour }, { p: d.ends[1], c: d.colour }]);
            }, []),
            getPosition: function (d) { return lift(d.p); }, getFillColor: function (d) { return d.c; },
            radiusUnits: 'pixels', getRadius: 2.6, billboard: true,
            updateTriggers: { getPosition: vertical }, parameters: ON_TOP
          }));
          out.push(new deck.TextLayer({
            id: 'phase-labels', data: shown, getText: function (d) { return d.text; },
            getPosition: function (d) { return lift(d.position); },
            getPixelOffset: [0, -9], getSize: 11, fontWeight: 600, characterSet: 'auto',
            fontFamily: 'ui-sans-serif, system-ui, sans-serif',
            getColor: [255, 255, 255],
            // The canvas strokes the text 3 px in translucent black; an SDF outline is the
            // same thing in deck.gl, and needs the SDF atlas switched on to draw at all.
            fontSettings: { sdf: true, fontSize: 64, buffer: 6 },
            outlineWidth: 2.5, outlineColor: [0, 0, 0, 150],
            updateTriggers: { getPosition: vertical }, parameters: ON_TOP
          }));
        }
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
      // A click on the rose turns the map north, as a compass on any map does; the tilt
      // stays where it was.
      rose.querySelector('svg').addEventListener('click', function () {
        map.easeTo({ bearing: 0, duration: 500 });
      });
      rose.querySelector('svg').setAttribute('aria-label', 'Turn the map north');
      rose.querySelector('svg').setAttribute('role', 'button');
      drawRose();
      var lastLight = null;
      function sunTo(minute) {
        if (!sun || minute === null || minute === undefined) return;
        sunMinute = minute;
        drawRose();
        if (styleReady) {
          var az = ((sunAt(minute).az % 360) + 360) % 360;
          if (lastLight === null || Math.abs(az - lastLight) >= 1) {
            lastLight = az;
            SHADES.forEach(function (id) {
              map.setPaintProperty(id, 'hillshade-illumination-direction', az);
            });
          }
        }
      }

      // ---- replay ----------------------------------------------------------------------
      var fromInput = view.querySelector('.m3-from'), toInput = view.querySelector('.m3-to');
      var fill = view.querySelector('.m3-fill');
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
      function showRange() {
        if (!fromInput) return;
        fromInput.value = from;
        toInput.value = cutoff;
        fill.style.left = (from / duration * 100) + '%';
        fill.style.right = (100 - cutoff / duration * 100) + '%';
        clockLabel.textContent = clockAt(from) + ' – ' + clockAt(cutoff);
      }
      // The right handle: the replay's "now", and the moment the sun is lit for.
      function setTime(seconds) {
        cutoff = Math.max(seconds, from);
        showRange();
        if (sun && sun.launch !== undefined) sunTo(sun.launch + cutoff / 60);
        refresh();
      }
      function setFrom(seconds) {
        from = Math.min(Math.max(seconds, 0), cutoff);
        showRange();
        refresh();
      }
      if (fromInput) {
        fromInput.addEventListener('input', function () { pause(); setFrom(Number(fromInput.value)); });
        toInput.addEventListener('input', function () { pause(); setTime(Number(toInput.value)); });
        view.querySelector('.m3-range').addEventListener('dblclick', function () {
          pause(); from = 0; setTime(duration);
        });
        showRange();
      }
      // Seconds of flight per second of replay. Two minutes a second is where it opens:
      // a three-hour flight in a minute and a half, a single climb still watchable.
      var SPEEDS = [10, 30, 60, 120, 300, 600, 1200];
      var speed = 3;
      var rateLabel = view.querySelector('.m3-rate');
      function showSpeed() {
        if (!rateLabel) return;
        var s = SPEEDS[speed];
        rateLabel.textContent = s < 60 ? s + ' s/s' : (s / 60) + ' min/s';
        view.querySelector('[data-m3="slower"]').disabled = speed === 0;
        view.querySelector('[data-m3="faster"]').disabled = speed === SPEEDS.length - 1;
      }
      showSpeed();
      var last = 0;
      function step(now) {
        var dt = last ? (now - last) / 1000 : 0;
        last = now;
        var next = cutoff + dt * SPEEDS[speed];
        // It stops at the end, on the landing, rather than wrapping round: a replay that
        // starts again by itself throws away the moment the reader was watching for.
        // Play again from there starts over from the left handle (`togglePlay`).
        if (next >= duration) { setTime(duration); pause(); return; }
        setTime(next);
        if (playing) frame = requestAnimationFrame(step);
      }
      function togglePlay() {
        if (!hasTime) return;
        if (replay.hidden) { openReplay(true); return; }
        var b = view.querySelector('[data-m3="play"]');
        if (playing) { pause(); return; }
        playing = true; last = 0;
        b.innerHTML = PAUSE_ICON; b.classList.add('is-on');
        b.setAttribute('aria-pressed', 'true'); b.setAttribute('aria-label', 'Pause');
        if (cutoff >= duration) setTime(from);
        frame = requestAnimationFrame(step);
      }
      // One button opens the replay and closing it puts the flight back as it was: the
      // whole track, no trail.
      function openReplay(on) {
        var toggle = view.querySelector('[data-m3="replay"]');
        toggle.classList.toggle('is-on', on);
        toggle.setAttribute('aria-pressed', String(on));
        replay.hidden = timeRow.hidden = !on;
        if (on) { from = 0; setTime(0); togglePlay(); return; }
        pause();
        from = 0;
        setTime(duration);
      }

      // ---- controls --------------------------------------------------------------------
      var GROUNDS = styles.concat(['off']);
      var VERTICALS = offered.length ? offered : [1, 2, 4];
      function groundName(key) {
        return key === 'off' ? 'relief' : ((tiles[key] || {}).label || key);
      }
      function label() {
        var g = view.querySelector('[data-m3="ground"]'), v = view.querySelector('[data-m3="vertical"]');
        var nextGround = GROUNDS[(GROUNDS.indexOf(basemap) + 1) % GROUNDS.length];
        var nextVertical = VERTICALS[(VERTICALS.indexOf(vertical) + 1) % VERTICALS.length];
        g.textContent = groundName(basemap);
        g.title = 'Ground: ' + groundName(basemap) + ' — press for ' + groundName(nextGround) + ' (s m r)';
        g.setAttribute('aria-label', g.title);
        v.innerHTML = '&#215;' + vertical;
        v.title = 'Vertical exaggeration ×' + vertical + ' — press for ×' + nextVertical + ' (1 2 4)';
        v.setAttribute('aria-label', v.title);
      }
      function setBasemap(key) {
        if (key !== 'off' && !tiles[key]) return;
        basemap = key;
        label();
        styles.forEach(function (name) {
          tiles[name].layers.forEach(function (_, i) {
            map.setLayoutProperty(name + '-' + i, 'visibility', name === key ? 'visible' : 'none');
          });
        });
        SHADES.forEach(function (id) {
          map.setLayoutProperty(id, 'visibility', id === shadeFor(key) ? 'visible' : 'none');
        });
      }
      function setVertical(v) {
        vertical = v;
        label();
        // The redraw first: if MapLibre throws below, the climbs, the track and the
        // ground must not end up at three different heights.
        refresh();
        // Before the style is parsed MapLibre throws here, so a press that early is
        // applied when it is. Not `isStyleLoaded()`: that stays false while any tile is still
        // arriving, long after 'load' has fired, and a press then was silently lost — the
        // track went to x2 over ground left at x1.
        if (styleReady) map.setTerrain({ source: 'dem', exaggeration: v });
      }
      label();
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
        if (act === 'ground') setBasemap(GROUNDS[(GROUNDS.indexOf(basemap) + 1) % GROUNDS.length]);
        else if (act === 'vertical') setVertical(VERTICALS[(VERTICALS.indexOf(vertical) + 1) % VERTICALS.length]);
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
        else if (act === 'replay') openReplay(replay.hidden);
        else if (act === 'slower' && speed > 0) { speed--; showSpeed(); }
        else if (act === 'faster' && speed < SPEEDS.length - 1) { speed++; showSpeed(); }
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
      // Every wrapper is remembered, so a rebuilt view can take its own back off: wrapping
      // again on top would leave the dead view's redraw in the chain.
      var unwrap = [];
      ['setCursor', 'revealCursor'].forEach(function (name) {
        var original = handle[name];
        if (typeof original !== 'function') return;
        unwrap.push({ name: name, original: original });
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
      unwrap.push({ name: 'clearCursor', original: clear });
      handle.clearCursor = function () {
        cursor = null;
        if (!view.hidden) refresh();
        return clear ? clear.apply(handle, arguments) : undefined;
      };
      unwrap.forEach(function (w) { w.wrapper = handle[w.name]; });

      api.lost = function () { return contextLost(view); };
      api.snapshot = function () {
        var c = map.getCenter();
        return { center: [c.lng, c.lat], zoom: map.getZoom(), bearing: map.getBearing(),
                 pitch: map.getPitch(), basemap: basemap, vertical: vertical,
                 labels: { climb: labels.climb, glide: labels.glide }, airspace: airspaceOn,
                 replay: !!(replay && !replay.hidden), from: from, cutoff: cutoff, speed: speed };
      };
      api.dispose = function () {
        pause();
        unwrap.forEach(function (w) { if (handle[w.name] === w.wrapper) handle[w.name] = w.original; });
        handle.__mergedFilterHooks = (handle.__mergedFilterHooks || []).filter(function (h) {
          return h !== filterHook;
        });
        try { map.remove(); } catch (error) { /* a dead context can throw on the way out */ }
        view.remove();
      };
      // MapLibre reports the loss; a browser that is going to restore the context does so
      // within a moment, so only a context still dead after that is rebuilt.
      map.on('webglcontextlost', function () {
        setTimeout(function () { if (window.__reviveMaps) window.__reviveMaps(); }, 1500);
      });

      if (restore) {
        map.jumpTo({ center: restore.center, zoom: restore.zoom, bearing: restore.bearing,
                     pitch: restore.pitch });
        ['climb', 'glide'].forEach(function (kind) {
          var b = view.querySelector('[data-m3-label="' + kind + '"]');
          if (b && restore.labels[kind] !== labels[kind]) b.click();
        });
        var a = view.querySelector('[data-m3="airspace"]');
        if (a && restore.airspace !== airspaceOn) a.click();
        speed = restore.speed; showSpeed();
        if (restore.replay) { openReplay(true); pause(); }
        from = restore.from;
        setTime(restore.cutoff);
      }

      // The canvas handle's airspace filter, followed: wrapped like the cursor calls, and
      // unwrapped by `dispose` with them.
      if (handle.setAirspaceFilter && !handle.setAirspaceFilter.__merged) {
        var ownFilter = handle.setAirspaceFilter;
        handle.setAirspaceFilter = function (fn) {
          ownFilter.apply(handle, arguments);
          (handle.__mergedFilterHooks || []).forEach(function (hook) { hook(fn); });
        };
        handle.setAirspaceFilter.__merged = true;
      }
      function filterHook(fn) { airspaceFilter = fn || null; refresh(); }
      handle.__mergedFilterHooks = (handle.__mergedFilterHooks || []).concat([filterHook]);
      // A click that is not a drag, as a place on the ground: what the planner drops a
      // turnpoint with. MapLibre's own `click` already refuses a pointer that moved.
      map.on('click', function (event) {
        var at = [event.lngLat.lng, event.lngLat.lat];
        clickers.forEach(function (fn) { fn(at, event.originalEvent); });
      });

      var entry = {
        map: map, setTime: setTime, setFrom: setFrom, cursor: function () { return cursor; },
        setBasemap: setBasemap, setVertical: setVertical,
        setRoute: function (walk, points) {
          route = walk || points ? { walk: walk || [], points: points || [] } : null;
          refresh();
        },
        onClick: function (fn) { clickers.push(fn); },
        airspaceShown: function () {
          return airspaceOn ? boxes.filter(function (d) {
            return !airspaceFilter || airspaceFilter(d.space);
          }).length : 0;
        },
        state: function () {
          return { basemap: basemap, vertical: vertical, labels: labels, airspace: airspaceOn,
                   bearing: map.getBearing(), sunMinute: sunMinute };
        }
      };
      window.__mergedAll = window.__mergedAll || {};
      window.__mergedAll[panel.querySelector('canvas.view3d').id] = entry;
      // For whatever else draws on this panel — the planner listens for it.
      panel.dispatchEvent(new CustomEvent('merged-ready', { detail: entry }));
    }, function (error) {
      view.querySelector('.m3-status').textContent =
        'MapLibre could not be loaded (' + error.message + '). It needs a network; the ' +
        'canvas view does not.';
    });
    return api;
  };
})();
"""

"""The 3D map: MapLibre's engine with deck.gl drawing over it, and the report's controls.

It began as the third of three renderers (October 2026) — the canvas view (`view3d`),
plain MapLibre, and this, merging what each was better at. From MapLibre: the whole
planet rather than one fetched rectangle, imagery and terrain streamed at every zoom,
and the replay slider. From the canvas view: the control bar, its keys, the sun and wind
rose, the climb and glide labels, the airspace boxes — and its imagery treatment: the
photograph shaded towards warm white and dark blue from the sun's real position, never
MapLibre's default black-and-white overlay that greys it. It is now the only one; the
comments below still say "the canvas" where a choice was made to match it.

It draws from the panel's scene and follows the linked cursor through the panel's handle
(`view3d.initView3d`: `handle.built`, and the wrapped `setCursor`). MapLibre and deck.gl
come from `render_map`'s loader, which also mounts this (`window.__openMap`).

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
.merged-view .m3-now[hidden] { display: none; }
.merged-view .m3-now { font-variant-numeric: tabular-nums; }
.merged-view .m3-now b { font-weight: 600; }
.merged-view .m3-rose p { margin: 4px 0 0; font-size: 11px; line-height: 1.3; color: #fff;
  /* A dark halo, several deep, so the text holds over the light relief as well as over
     the photograph: one soft shadow vanished against the pale ground. */
  text-shadow: 0 0 2px rgba(8,10,14,1), 0 0 3px rgba(8,10,14,1), 0 0 5px rgba(8,10,14,0.9),
    1px 1px 1px rgba(8,10,14,1), -1px -1px 1px rgba(8,10,14,1); }
.merged-view .m3-bottom { position: absolute; left: 10px; right: 10px; bottom: 10px; z-index: 3;
  display: flex; flex-wrap: wrap; align-items: center; gap: 5px; pointer-events: none; }
.merged-view .m3-bottom > * { pointer-events: auto; }
.merged-view .m3-bottom .view3d-controls { position: static; margin-left: auto; }
.merged-view .m3-replay { display: flex; gap: 5px; align-items: center; }
.merged-view .m3-replay[hidden], .merged-view .m3-time[hidden],
.merged-view .view3d-controls[hidden] { display: none; }
.merged-view .m3-bottom button, .merged-view .m3-rate { height: 30px; box-sizing: border-box; }
.merged-view .m3-icon { display: inline-flex; align-items: center; justify-content: center; }
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
.merged-view .m3-measure { position: absolute; left: 50%; transform: translateX(-50%); top: 12px;
  z-index: 3; margin: 0; white-space: nowrap;
  padding: 4px 9px; font-size: 12px; color: var(--ink); background: var(--panel);
  border: 1px solid var(--rule); border-radius: 2px; font-variant-numeric: tabular-nums; }
.merged-view .m3-measure[hidden] { display: none; }
.merged-view .m3-others { float: left; margin: 10px 0 0 10px; pointer-events: auto;
  max-width: calc(100vw - 200px);
  padding: 3px 8px; list-style: none; font-size: 11.5px; line-height: 1.5; color: var(--ink);
  background: var(--panel); border: 1px solid var(--rule); border-radius: 2px; }
.merged-view .m3-others[hidden] { display: none; }
.merged-view .m3-others i { display: inline-block; width: 14px; height: 3px; margin: 0 7px 3px 0;
  vertical-align: middle; border-radius: 2px; }
.merged-view .m3-others li { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.merged-view .m3-others .is-own { font-weight: 600; }
.merged-view .m3-others .is-far { color: var(--ink-3); }
.merged-view .m3-status { position: absolute; left: 12px; top: 34px; z-index: 3; margin: 0;
  font-size: 12px; color: var(--ink-2); }
/* MapLibre's own credits, the openable kind: an (i) at the top left that opens to name
   every source on screen, after the legend of compared flights in the same row. At the
   bottom left it never lined up with the bar beside it. */
.merged-view .maplibregl-ctrl-top-left { z-index: 4; }
/* MapLibre stacks each corner control on a line of its own (`clear: both`); the (i) sits
   beside the legend instead. */
.merged-view .maplibregl-ctrl-top-left .maplibregl-ctrl { clear: none; }
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
  // The airspace is glass: hidden behind a mountain, but it must hide nothing itself.
  // Writing depth, a translucent box drawn before the track hid every part of the flight
  // inside or behind it — over Krupka, nearly all of it, the moment airspace was on.
  var GLASS = { depthWriteEnabled: false };
  // The canvas view strokes its track 2.6 px wide on a backing store of up to twice the
  // screen's density, so on a phone it is 1.3 CSS px and on a desktop 2.6. deck.gl's
  // pixels are CSS pixels, so the same line takes the same arithmetic.
  var TRACK_WIDTH = 2.6 / Math.min(window.devicePixelRatio || 1, 2);
  var PLAY_ICON = '<svg width="11" height="12" viewBox="0 0 11 12" aria-hidden="true">' +
    '<path d="M1 1 L10 6 L1 11 Z" fill="currentColor"/></svg>';
  // The replay's own button: a camera. The play triangle is the play button inside the
  // replay, and two buttons with the same triangle were one too many.
  var CAMERA_ICON = '<svg width="16" height="12" viewBox="0 0 16 12" aria-hidden="true" fill="currentColor">' +
    '<rect x="0.5" y="2" width="10" height="8" rx="1.5"/><path d="M11.5 5 L15.5 2.5 L15.5 9.5 L11.5 7 Z"/></svg>';
  var RULER_ICON = '<svg width="14" height="12" viewBox="0 0 14 12" aria-hidden="true" fill="none"' +
    ' stroke="currentColor" stroke-width="1.3"><path d="M1 8.5 8.5 1l4.5 4.5L5 13z" transform="translate(0 -1.5)"/>' +
    '<path d="M4 5.5l1.5 1.5M6 3.5l1.5 1.5M8 1.5l1.5 1.5" transform="translate(0 -0.5)"/></svg>';
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
      '<dt>d</dt><dd>measure: click points; backspace undoes one, esc ends</dd>' +
      '<dt>space</dt><dd>replay: open, play, pause</dd>' +
      '<dt>c</dt><dd>replay: follow the glider</dd>' +
      '<dt>f</dt><dd>full screen</dd>' +
      '<dt>0</dt><dd>reset view</dd></dl>' +
      // What still works once the camera rides with the glider (`setFollow`), and what
      // hands it back: the keys and gestures above mean something else there.
      '<p class="view3d-keys-head">While following the replay</p><dl>' +
      '<dt>scroll, pinch, + &minus;, double-click</dt><dd>zoom</dd>' +
      '<dt>&uarr; &darr;, two fingers up / down</dt><dd>tilt</dd>' +
      '<dt>&larr; &rarr;, two-finger twist</dt><dd>turn the view off the direction of flight</dd>' +
      '<dt>drag, the compass, reset</dt><dd>stop following</dd></dl>' +
      '<p class="view3d-keys-foot">Hovering the charts moves the marker here too. ' +
      'Click this list to close it.</p>';
  }

  // Tiles below a source's `consistent_from` level, built from that level's tiles. For
  // Esri the levels under 12 are a different, darker mosaic, so a map that ever shows
  // them jumps colour as the zoom crosses the line — and at a tilt the far half of the
  // view always sits on them. One level down costs 4 requests, two levels 16; deeper
  // than that (64+) the native tile is used, which only the far horizon ever asks for.
  var STITCH_LEVELS = 2;
  // Place names (`style`): OpenFreeMap's planet tiles and their fonts, no key.
  var PLACES = 'https://tiles.openfreemap.org/planet';
  var GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';
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
    // What the switch says, from `settleAirspace`: drawn with its credit, or why not.
    var airspaceWhy = String(scene.airspaceWhy || (hasAirspace ? 'Draw the airspace over this flight'
      : 'No airspace data under this flight — the layers cover Europe')).replace(/"/g, '&quot;');
    // The exaggerations this panel offers, and the one it opens on, are the page's
    // (`view3d.panel(verticals=…)`): ×1/2/4 under a flight, ×1/5/15 under a country of
    // airspace, where a traffic circuit at ×1 is a third of a pixel tall.
    var offered = (panel.dataset.verticals || '1,2,4').split(',').map(parseFloat)
      .filter(function (v) { return v > 0; });
    var openVertical = parseFloat(panel.dataset.vertical) || offered[0] || 1;
    var hasPhases = !!(scene.phases && scene.phases.length);

    var view = document.createElement('div');
    view.className = 'maplibre-view merged-view';
    view.innerHTML =
      '<div class="ml-map" tabindex="0" aria-label="Interactive three-dimensional map of the ' +
        'flight. Arrow keys pan and shift with them turns and tilts; press question mark ' +
        'for the key list."></div>' +
      '<p class="m3-status">Loading MapLibre…</p>' +
      '<p class="m3-measure" hidden aria-live="polite"></p>' +
      '<ul class="m3-others" hidden aria-label="Flights compared with this one"></ul>' +
      '<div class="m3-rose" hidden><svg width="64" height="64" viewBox="-32 -32 64 64">' +
        '<circle r="30" fill="rgba(16,19,24,0.55)" stroke="rgba(255,255,255,0.28)"/>' +
        '<text class="m3-n" text-anchor="middle" dominant-baseline="central" font-size="11"' +
        ' fill="rgba(255,255,255,0.75)">N</text>' +
        '<g class="m3-wind"><line x1="0" y1="19" x2="0" y2="-15" stroke="rgba(120,190,255,0.95)"' +
        ' stroke-width="2.2" stroke-linecap="round"/><path d="M0,-21 L-4.5,-12 L4.5,-12 Z"' +
        ' fill="rgba(120,190,255,0.95)"/></g>' +
        '<g class="m3-sun"><line x1="0" y1="-13" x2="0" y2="-6" stroke-width="1.6"/>' +
        '<circle cy="-21" r="5.5"/></g>' +
      '</svg><p class="m3-rose-text"></p><p class="m3-now" hidden></p></div>' +
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
          '<button type="button" data-m3="follow" aria-pressed="false" title="Follow the glider, ' +
          'facing the way the flight was going (c)">follow</button>' +
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
          '<button type="button" data-m3="airspace" aria-pressed="false" title="' + airspaceWhy + '"' +
          ' aria-label="' + airspaceWhy + '">airspace</button></div>' :
         noAirspace ?
          '<div class="view3d-seg view3d-airspace" role="group" aria-label="Airspace">' +
          '<button type="button" data-m3="airspace" aria-pressed="false" disabled' +
          ' title="' + airspaceWhy + '" aria-label="' + airspaceWhy + '">airspace</button></div>' : '') +
        '<div class="view3d-seg view3d-zoom" role="group" aria-label="Zoom">' +
          '<button type="button" data-m3="zoom-out" title="Zoom out" aria-label="Zoom out">&minus;</button>' +
          '<button type="button" data-m3="zoom-in" title="Zoom in" aria-label="Zoom in">+</button></div>' +
        (hasTime ? '<button type="button" data-m3="replay" class="m3-icon" aria-pressed="false"' +
          ' title="Replay the flight" aria-label="Replay the flight">' + CAMERA_ICON + '</button>' : '') +
        '<button type="button" data-m3="measure" class="m3-icon" aria-pressed="false"' +
          ' title="Measure a distance (d)" aria-label="Measure a distance">' + RULER_ICON + '</button>' +
        '<button type="button" data-m3="help" title="Controls" aria-label="How to control this view">?</button>' +
        '<button type="button" data-m3="fullscreen" title="Full screen" aria-label="Full screen">' +
          '<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor"' +
          ' stroke-width="1.5"><path d="M1 4.5V1h3.5M8.5 1H12v3.5M12 8.5V12H8.5M4.5 12H1V8.5"/></svg></button>' +
        '<button type="button" class="view3d-reset" data-m3="reset" title="Reset view"' +
        ' aria-label="Reset view">&#8634;</button>' +
      '</div></div>';
    panel.appendChild(view);

    var playing = false, frame = null, map = null;
    // While the replay plays, the screen stays on: a phone dims and locks a page nobody
    // touches, mid-flight. Released on pause; taken again if the page comes back to the
    // front still playing (a browser drops the lock when it is hidden).
    var wakeLock = null;
    function holdAwake(on) {
      if (on && !wakeLock && navigator.wakeLock && navigator.wakeLock.request) {
        navigator.wakeLock.request('screen').then(function (lock) {
          if (!playing) { lock.release(); return; }
          wakeLock = lock;
          lock.addEventListener('release', function () { if (wakeLock === lock) wakeLock = null; });
        }, function () { /* refused: the screen may dim, the replay still runs */ });
      } else if (!on && wakeLock) {
        var held = wakeLock; wakeLock = null;
        held.release();
      }
    }
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && playing) holdAwake(true);
    });
    function pause() {
      playing = false;
      holdAwake(false);
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
      // The replay's span, in this flight's seconds: its own flight, or — comparing — from
      // the first of the flights to start to the last to land, so the replay runs until
      // all of them are down, whichever one this map belongs to (`setOthers`).
      var spanStart = 0, spanEnd = duration;
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
      var labelled = {};      // basemaps that carried a label layer: the place names show over them
      function shadeFor(key) { return key === 'off' ? 'hillshade-relief' : 'hillshade-over'; }
      // Every basemap in one style, and a switch shows one and hides the rest. Swapping
      // whole styles with `setStyle` was the first version, and three quick presses left
      // the map with no imagery and no terrain: MapLibre does not survive a style change
      // arriving while the last one is still loading. A hidden layer fetches no tiles,
      // so carrying all of them costs nothing until one is shown.
      // Under the imagery the dark green that hides a missing tile; under the bare relief,
      // where the background *is* the ground, the light one the shading was made for.
      function groundColour(key) { return key === 'off' ? '#d6d2c4' : '#3d4436'; }
      function style(key) {
        var sources = {
          // Declared at half their size so MapLibre asks one zoom deeper than it would:
          // four times the tiles, and relief and imagery as sharp as the canvas's grid.
          // At their natural size the DEM it picks is ~4x coarser and the hills read flat.
          dem: { type: 'raster-dem', tiles: [window.__mapTerrarium], tileSize: 128, maxzoom: 15,
                 encoding: 'terrarium', attribution: 'Terrain: AWS Open Data Terrain Tiles' },
          // Its own source for the shading: MapLibre renders both worse when the hillshade
          // and the 3D terrain share one.
          // The shading from level 12 at most, smoothed up from there: at 15 the DEM's
          // whole-metre steps terraced every gentle slope into bands, plain to see in the
          // relief view.
          shade: { type: 'raster-dem', tiles: [window.__mapTerrarium], tileSize: 128, maxzoom: 12,
                   encoding: 'terrarium' }
        };
        // Under the imagery: what shows where a tile has not arrived yet. A pale beige
        // here flashed against the dark ground every time the follow camera moved into
        // new tiles; a dark muted green, near the photograph's own average, barely shows.
        var below = [{ id: 'bg', type: 'background', paint: { 'background-color': groundColour(key) } }];
        var above = [];
        styles.forEach(function (name) {
          var source = tiles[name];
          source.layers.forEach(function (template, i) {
            var id = name + '-' + i;
            // A raster label layer is replaced by the place names below: Esri's stops at
            // level 12 and answers empty tiles past it, so every name vanished as the
            // reader zoomed in to the ground they were about.
            if (i) { labelled[name] = true; return; }
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
              paint: i ? { 'raster-fade-duration': 300 }
                       : { 'raster-fade-duration': 300, 'raster-brightness-min': 0.06,
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
        // Place names as text, from OpenFreeMap's OpenStreetMap tiles (keyless, CORS-open):
        // crisp at every zoom and placed by MapLibre so they never collide, where a
        // raster label is a picture of text at one scale. Shown where the basemap had
        // labels (the photograph), switched with it.
        sources.places = { type: 'vector', url: PLACES };
        // Two overlays drawn by MapLibre itself, so they lie on the terrain: shapes a page
        // hands in (`setShapes` — the planner's FAI area) and the measuring line.
        var empty = { type: 'FeatureCollection', features: [] };
        sources.shapes = { type: 'geojson', data: empty };
        sources.measure = { type: 'geojson', data: empty };
        above.push(
          { id: 'shapes-fill', type: 'fill', source: 'shapes',
            paint: { 'fill-color': ['coalesce', ['get', 'colour'], '#3b4cc0'],
                     'fill-opacity': ['coalesce', ['get', 'opacity'], 0.4] } },
          { id: 'shapes-edge', type: 'line', source: 'shapes',
            paint: { 'line-color': ['coalesce', ['get', 'colour'], '#3b4cc0'], 'line-width': 2 } });
        above.push({
          id: 'place-labels', type: 'symbol', source: 'places', 'source-layer': 'place',
          // Villages only from zoom 11: hidden by opacity they would still take the room
          // the towns' names need.
          filter: ['any', ['match', ['get', 'class'], ['city', 'town'], true, false],
                   ['all', ['==', ['get', 'class'], 'village'], ['>=', ['zoom'], 11]]],
          minzoom: 6,
          layout: {
            visibility: labelled[key] ? 'visible' : 'none',
            'text-field': ['coalesce', ['get', 'name'], ['get', 'name:latin']],
            'text-font': ['match', ['get', 'class'], 'city', ['literal', ['Noto Sans Bold']],
                          ['literal', ['Noto Sans Regular']]],
            'text-size': ['interpolate', ['linear'], ['zoom'],
                          6, ['match', ['get', 'class'], 'city', 13, 'town', 10, 9],
                          12, ['match', ['get', 'class'], 'city', 18, 'town', 15, 12],
                          16, ['match', ['get', 'class'], 'city', 22, 'town', 18, 15]],
            // Cities win the room first, then towns, then villages.
            'symbol-sort-key': ['match', ['get', 'class'], 'city', 0, 'town', 1, 2],
            'text-padding': 4
          },
          paint: { 'text-color': '#ffffff', 'text-halo-color': 'rgba(12,14,18,0.85)',
                   'text-halo-width': 1.4, 'text-halo-blur': 0.4 }
        });
        above.push(
          { id: 'measure-line', type: 'line', source: 'measure', filter: ['==', ['geometry-type'], 'LineString'],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': '#ffffff', 'line-width': 2.5, 'line-dasharray': [2, 1.5] } },
          { id: 'measure-dots', type: 'circle', source: 'measure', filter: ['==', ['geometry-type'], 'Point'],
            paint: { 'circle-radius': 4.5, 'circle-color': '#ffffff',
                     'circle-stroke-color': 'rgba(12,14,18,0.9)', 'circle-stroke-width': 1.5 } });
        return {
          version: 8, sources: sources, glyphs: GLYPHS,
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
      var styleReady = false, pendingShapes = [];
      map = new maplibregl.Map({
        container: view.querySelector('.ml-map'), style: style(basemap),
        center: [(west + east) / 2, (south + north) / 2], zoom: 10, pitch: openPitch, bearing: 0,
        maxPitch: 85, attributionControl: false, keyboard: true
      });
      // 'style.load', not 'load': 'load' waits for the first complete frame, every tile
      // included, which on a slow connection is long after a reader has pressed things.
      map.once('style.load', function () {
        styleReady = true;
        if (pendingShapes.length) {
          var shapes = map.getSource('shapes');
          if (shapes) shapes.setData({ type: 'FeatureCollection', features: pendingShapes });
        }
        if (vertical !== 1) map.setTerrain({ source: 'dem', exaggeration: vertical });
      });
      // Credits from the sources themselves, so switching the basemap changes them.
      // Top left, after the legend of compared flights, in one row: at the bottom left the
      // (i) never lined up with the bar beside it.
      map.addControl(new maplibregl.AttributionControl({ compact: true }), 'top-left');
      (function () {
        var corner = view.querySelector('.maplibregl-ctrl-top-left');
        if (corner) corner.insertBefore(view.querySelector('.m3-others'), corner.firstChild);
      })();
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
          // The canvas's box, not the canvas container's: that element has no height of
          // its own, and clamped into it every pivot went to y = 0 — the horizon, 200 km
          // away at a 60° tilt — and a shift-drag flung the map across the country.
          var box = map.getCanvas().getBoundingClientRect();
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

      // ---- compared flights ----------------------------------------------------------
      // Handed in by the page's comparison (`setOthers`, from `render_html`): the other
      // flights the reader marked. On one clock when they were flown the same day — a
      // replay at 13:20 shows every glider where it was at 13:20 — and otherwise from each
      // one's own launch. The map streams its ground for anywhere, so the only guard is
      // against the absurd: a flight more than 150 km from this one's ground is listed as
      // too far rather than drawn, and the view is not stretched across a continent. When
      // the set changes the view is framed on all of them, keeping its tilt and heading.
      var others = [], ownColour = null, ownName = '';
      var othersList = view.querySelector('.m3-others');
      function firstAt(times, t) {
        var lo = 0, hi = times.length;
        while (lo < hi) { var mid = (lo + hi) >> 1; if (times[mid] < t) lo = mid + 1; else hi = mid; }
        return lo;
      }
      function positionOf(o, t) {
        var j = Math.min(Math.max(firstAt(o.t, t), 1), o.t.length - 1), i = j - 1;
        var span = o.t[j] - o.t[i], f = span > 0 ? Math.min(Math.max((t - o.t[i]) / span, 0), 1) : 0;
        return [o.lon[i] + (o.lon[j] - o.lon[i]) * f, o.lat[i] + (o.lat[j] - o.lat[i]) * f,
                o.alt[i] + (o.alt[j] - o.alt[i]) * f];
      }
      // `compared`: { own: { name, colour }, others: [{ name, colour, track, start }] }, or
      // nothing — what `window.__compareFor` gives (`render_html`).
      // A compared glider's position over ±45 s, as `steadyAt` is for this one.
      function steadyOf(o, t) {
        var n = 9, q = { lon: 0, lat: 0, alt: 0 };
        for (var i = 0; i < n; i++) {
          var at = positionOf(o, t - 45 + 90 * i / (n - 1));
          q.lon += at[0] / n; q.lat += at[1] / n; q.alt += at[2] / n;
        }
        return q;
      }
      function setOthers(compared) {
        var list = (compared && compared.others) || [];
        var box = scene.terrain || {}, margin = 150000;
        var mx = margin / (111320 * Math.cos(((box.south || 0) + (box.north || 0)) / 2 * Math.PI / 180));
        var my = margin / 111320;
        others = (list || []).filter(function (o) { return o.track && o.track.lon && o.track.lon.length > 1; })
          .map(function (o) {
            var tr2 = o.track;
            var w = Math.min.apply(null, tr2.lon), e = Math.max.apply(null, tr2.lon);
            var s2 = Math.min.apply(null, tr2.lat), n2 = Math.max.apply(null, tr2.lat);
            var far = box.west === undefined ? false
              : (e < box.west - mx || w > box.east + mx || n2 < box.south - my || s2 > box.north + my);
            var sameDay = scene.start && o.start && Math.abs(o.start - scene.start) < 12 * 3600;
            // Each climb at the time of the fix nearest it, so the replay can window it.
            var climbs = (o.climbs || []).map(function (c) {
              var best = 0, bestD = Infinity;
              for (var i = 0; i < tr2.lon.length; i++) {
                var d = (tr2.lon[i] - c.lon) * (tr2.lon[i] - c.lon) + (tr2.lat[i] - c.lat) * (tr2.lat[i] - c.lat);
                if (d < bestD) { bestD = d; best = i; }
              }
              return { lon: c.lon, lat: c.lat, alt: c.alt, t: tr2.t ? tr2.t[best] : best };
            });
            return { name: o.name, colour: o.colour, lon: tr2.lon, lat: tr2.lat, alt: tr2.alt, climbs: climbs,
                     t: tr2.t || tr2.lon.map(function (_, i) { return i; }), far: far,
                     offset: sameDay ? o.start - scene.start : 0, sameDay: !!sameDay };
          });
        // The replay spans every compared flight: first start to last landing.
        spanStart = 0; spanEnd = duration;
        others.forEach(function (o) {
          if (o.far) return;
          spanStart = Math.min(spanStart, o.t[0] + o.offset);
          spanEnd = Math.max(spanEnd, o.t[o.t.length - 1] + o.offset);
        });
        if (fromInput) {
          [fromInput, toInput].forEach(function (input) { input.min = spanStart; input.max = spanEnd; });
          if (replay && replay.hidden) { from = spanStart; cutoff = spanEnd; }
          from = Math.max(from, spanStart); cutoff = Math.min(Math.max(cutoff, from), spanEnd);
          showRange();
        }
        ownColour = others.length && compared.own ? compared.own.colour : null;
        ownName = others.length && compared.own ? compared.own.name : '';
        // Top left, one short line a flight: this one in bold; how each is aligned in time
        // is in its tooltip.
        othersList.innerHTML = (ownColour ? '<li class="is-own" title="This flight"><i style="background:' +
            ownColour + '"></i>' + ownName.replace(/[<&]/g, '') + '</li>' : '') + others.map(function (o) {
          // Another day is aligned by launch without saying so on the line: the tooltip has
          // it, and the line has no room for it beside the (i).
          var note = o.far ? ' · too far to show' : '';
          var title = o.far ? 'More than 150 km away: not drawn'
            : o.sameDay ? 'Same day: replayed on the same clock' : 'Another day: replayed by time since launch';
          return '<li' + (o.far ? ' class="is-far"' : '') + ' title="' + title + '"><i style="background:' +
            o.colour + '"></i>' + o.name.replace(/[<&]/g, '') + note + '</li>';
        }).join('');
        othersList.hidden = !others.length;
        var shown = others.filter(function (o) { return !o.far; });
        var key = shown.map(function (o) { return o.name; }).join('|');
        if (key && key !== framedFor) {
          var w = Infinity, e = -Infinity, s = Infinity, n = -Infinity;
          [tr].concat(shown).forEach(function (o) {
            for (var i = 0; i < o.lon.length; i++) {
              w = Math.min(w, o.lon[i]); e = Math.max(e, o.lon[i]);
              s = Math.min(s, o.lat[i]); n = Math.max(n, o.lat[i]);
            }
          });
          map.fitBounds([[w, s], [e, n]],
                        { padding: { top: 70, bottom: 110, left: 50, right: 90 },
                          pitch: map.getPitch(), bearing: map.getBearing(), duration: 600 });
        }
        framedFor = key;
        refresh();
      }
      var framedFor = '';

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
            material: false, parameters: GLASS,
            updateTriggers: { getPolygon: vertical, getElevation: vertical }
          }));
          out.push(new deck.PathLayer({
            id: 'airspace-edges', data: drawn.reduce(function (all, d) {
              var shut = d.ring.concat([d.ring[0]]);
              all.push({ colour: d.colour, path: shut.map(function (p) { return [p[0], p[1], z(d.floor)]; }) });
              all.push({ colour: d.colour, path: shut.map(function (p) { return [p[0], p[1], z(d.top)]; }) });
              return all;
            }, []),
            getPath: function (d) { return d.path; }, getColor: function (d) { return rgb(d.colour, 200); },
            getWidth: 1.2, widthUnits: 'pixels', parameters: GLASS, updateTriggers: { data: vertical }
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
            getColor: function (d) { return rgb(d.colour, 150); }, getWidth: 1, parameters: GLASS,
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
          // While comparing, one colour per flight instead of the climb ramp: several
          // tracks each in five climb colours were five times too many colours to read.
          getColor: function (d) { return ownColour ? rgb(ownColour, 235) : d.colour; },
          getWidth: TRACK_WIDTH, widthUnits: 'pixels',
          currentTime: cutoff, trailLength: Math.max(cutoff - from, 0) + 0.5, fadeTrail: false,
          capRounded: true, jointRounded: true,
          updateTriggers: { getPath: vertical, getColor: ownColour }
        }));
        // While the replay runs, its leading edge: the last seven minutes in white.
        // Not while comparing: each flight is its one colour there, and a white stretch on
        // this one alone read as a different flight.
        if (hasTime && replay && !replay.hidden && !ownColour) out.push(new deck.TripsLayer({
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
          // Comparing, this flight's climbs in its own colour, as the others' are in theirs.
          getFillColor: function (d) {
            return d.tow ? [27, 175, 122] : ownColour ? rgb(ownColour, 255) : [226, 96, 44];
          },
          updateTriggers: { getFillColor: ownColour, getPosition: vertical },
          getLineColor: [255, 255, 255, 220], stroked: true, lineWidthMinPixels: 1,
          radiusUnits: 'pixels', getRadius: 4, billboard: true,
          parameters: ON_TOP
        }));
        // Where this glider is at the replay's "now", as each compared one is shown.
        if (hasTime && replay && !replay.hidden && cutoff >= 0 && cutoff <= duration) {
          var me = positionAt(cutoff);
          out.push(new deck.ScatterplotLayer({
            id: 'own-now', data: [[me.lon, me.lat, me.alt]],
            getPosition: function (d) { return [d[0], d[1], z(d[2])]; },
            getFillColor: ownColour ? rgb(ownColour, 255) : [255, 255, 255, 255],
            getLineColor: ownColour ? [255, 255, 255, 255] : [20, 20, 20, 255],
            stroked: true, lineWidthMinPixels: 2, radiusUnits: 'pixels', getRadius: 6,
            billboard: true, parameters: ON_TOP, updateTriggers: { getPosition: vertical }
          }));
        }
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
        // The flights compared with this one (`setOthers`), each in its own colour: the
        // whole track; or, while the replay is open, the part flown inside the same window
        // of the shared clock and a dot where the glider was at its "now".
        others.forEach(function (o, k) {
          if (o.far) return;
          var a = 0, b = o.t.length - 1;
          if (hasTime && replay && !replay.hidden) {
            var lo = from - o.offset, hi = cutoff - o.offset;
            a = firstAt(o.t, lo); b = firstAt(o.t, hi + 1e-6) - 1;
            if (b >= 0 && b < o.t.length && hi >= o.t[0] && hi <= o.t[o.t.length - 1]) {
              var now = positionOf(o, hi);
              out.push(new deck.ScatterplotLayer({
                id: 'other-now-' + k, data: [now],
                getPosition: function (d) { return [d[0], d[1], z(d[2])]; },
                getFillColor: rgb(o.colour, 255), getLineColor: [255, 255, 255, 255],
                stroked: true, lineWidthMinPixels: 2, radiusUnits: 'pixels', getRadius: 6,
                billboard: true, parameters: ON_TOP,
                updateTriggers: { getPosition: vertical }
              }));
            }
          }
          // Its climbs, in its colour, inside the same window as its track.
          var shownClimbs = (o.climbs || []).filter(function (c) {
            return !(hasTime && replay && !replay.hidden) || (c.t >= from - o.offset && c.t <= cutoff - o.offset);
          });
          if (shownClimbs.length) out.push(new deck.ScatterplotLayer({
            id: 'other-climbs-' + k, data: shownClimbs,
            getPosition: function (d) { return [d.lon, d.lat, z(d.alt)]; },
            getFillColor: rgb(o.colour, 255), getLineColor: [255, 255, 255, 220], stroked: true,
            lineWidthMinPixels: 1, radiusUnits: 'pixels', getRadius: 4, billboard: true,
            parameters: ON_TOP, updateTriggers: { getPosition: vertical }
          }));
          if (b - a < 1) return;
          out.push(new deck.PathLayer({
            id: 'other-' + k, data: [{ a: a, b: b }],
            getPath: function (d) {
              var path = [];
              for (var i = d.a; i <= d.b; i++) path.push([o.lon[i], o.lat[i], z(o.alt[i])]);
              return path;
            },
            // Drawn as this flight's own track is (a TripsLayer, not billboarded): as a
            // billboard it faced the camera at full width and read thicker at any tilt.
            getColor: rgb(o.colour, 235), getWidth: TRACK_WIDTH, widthUnits: 'pixels',
            capRounded: true, jointRounded: true,
            updateTriggers: { getPath: [a, b, vertical] }
          }));
        });
        // Not while the replay is open: it drives the charts' cursor itself, and its own
        // dot already marks the glider — the two side by side read as two gliders.
        if (cursor && !(hasTime && replay && !replay.hidden)) {
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
        // Interleaved: drawn in MapLibre's own pass against the terrain's depth, so a ridge
        // hides the track, the airspace and the route behind it. On a canvas of its own
        // over the map, everything showed through the mountains.
        interleaved: true, layers: layers(),
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
        setFollow(false);
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
        var span = Math.max(spanEnd - spanStart, 1);
        fill.style.left = ((from - spanStart) / span * 100) + '%';
        fill.style.right = (100 - (cutoff - spanStart) / span * 100) + '%';
        clockLabel.textContent = clockAt(from) + ' – ' + clockAt(cutoff);
      }
      // The right handle: the replay's "now", and the moment the sun is lit for.
      function setTime(seconds) {
        cutoff = Math.max(seconds, from);
        showRange();
        if (sun && sun.launch !== undefined) sunTo(sun.launch + cutoff / 60);
        refresh();
        if (following) kickFollow();
        if (replay && !replay.hidden) showNow();
      }
      // While the replay is open: the side and top views' cursor at its "now"
      // (`__cursorAtTime`, `render_html`), and the height at "now" top right — this
      // flight's with its climb, and each compared glider's in its colour.
      var nowText = view.querySelector('.m3-now');
      function heightAt(t) {
        var i = Math.min(Math.max(firstAt(tr.t, t), 1), tr.t.length - 1), j = i - 1;
        var span = tr.t[i] - tr.t[j], f = span > 0 ? Math.min(Math.max((t - tr.t[j]) / span, 0), 1) : 0;
        return tr.alt[j] + (tr.alt[i] - tr.alt[j]) * f;
      }
      function showNow() {
        var article = panel.closest('[data-flight-report]');
        var flying = cutoff >= 0 && cutoff <= duration;
        if (flying && article && article.__cursorAtTime) article.__cursorAtTime(cutoff);
        var lines = [];
        if (flying) {
          var climb = (heightAt(cutoff + 10) - heightAt(cutoff - 10)) / 20;
          // In this flight's comparison colour when comparing, as every other mark of it is.
          lines.push('<span' + (ownColour ? ' style="color:' + ownColour + '"' : '') + '><b>' +
                     Math.round(heightAt(cutoff)).toLocaleString('en-US') + ' m</b> · ' +
                     (climb >= 0 ? '+' : '') + climb.toFixed(1) + ' m/s</span>');
        }
        others.forEach(function (o) {
          var at = cutoff - o.offset;
          if (o.far || at < o.t[0] || at > o.t[o.t.length - 1]) return;
          var rate = (positionOf(o, at + 10)[2] - positionOf(o, at - 10)[2]) / 20;
          lines.push('<span style="color:' + o.colour + '"><b>' +
                     Math.round(positionOf(o, at)[2]).toLocaleString('en-US') + ' m</b> · ' +
                     (rate >= 0 ? '+' : '') + rate.toFixed(1) + ' m/s</span>');
        });
        nowText.innerHTML = lines.join('<br>');
        nowText.hidden = !lines.length;
        // It lives under the rose; a flight with no sun or wind has no rose to show, only this.
        if (lines.length) {
          rose.hidden = false;
          if (!sun && !wind) rose.querySelector('svg').style.display = 'none';
        } else if (!sun && !wind) rose.hidden = true;
      }
      function setFrom(seconds) {
        from = Math.min(Math.max(seconds, spanStart), cutoff);
        showRange();
        refresh();
      }
      if (fromInput) {
        fromInput.addEventListener('input', function () { pause(); setFrom(Number(fromInput.value)); });
        toInput.addEventListener('input', function () { pause(); setTime(Number(toInput.value)); });
        view.querySelector('.m3-range').addEventListener('dblclick', function () {
          pause(); from = spanStart; setTime(spanEnd);
        });
        showRange();
      }
      // Seconds of flight per second of replay. A minute a second is where it opens: a
      // three-hour flight in three minutes, a climb slow enough to watch it worked.
      var SPEEDS = [10, 30, 60, 120, 300, 600, 1200];
      var speed = 2;
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
        if (next >= spanEnd) { setTime(spanEnd); pause(); return; }
        setTime(next);
        if (playing) frame = requestAnimationFrame(step);
      }
      function togglePlay() {
        if (!hasTime) return;
        if (replay.hidden) { openReplay(true); return; }
        var b = view.querySelector('[data-m3="play"]');
        if (playing) { pause(); return; }
        playing = true; last = 0;
        holdAwake(true);
        b.innerHTML = PAUSE_ICON; b.classList.add('is-on');
        b.setAttribute('aria-pressed', 'true'); b.setAttribute('aria-label', 'Pause');
        if (cutoff >= spanEnd) setTime(from);
        frame = requestAnimationFrame(step);
      }
      // One button opens the replay and closing it puts the flight back as it was: the
      // whole track, no trail.
      function openReplay(on) {
        var toggle = view.querySelector('[data-m3="replay"]');
        toggle.classList.toggle('is-on', on);
        toggle.setAttribute('aria-pressed', String(on));
        replay.hidden = timeRow.hidden = !on;
        if (!on) nowText.hidden = true;
        if (on) { from = spanStart; setTime(spanStart); togglePlay(); return; }
        setFollow(false);
        pause();
        from = spanStart;
        setTime(spanEnd);
      }


      // ---- follow ----------------------------------------------------------------------
      // The camera rides with the replay's "now", facing the direction of flight smoothed
      // out rather than the glider's nose: turning with every circle of a thermal is
      // unwatchable. The direction is where the glider got to over a few minutes, held
      // while it circles, averaged again, and then eased towards in real time, so a fast
      // replay cannot snap it round either. (The scored route's legs were the first try,
      // and too coarse: a leg is an hour of flying in one fixed direction.)
      function bearingDeg(lon1, lat1, lon2, lat2) {
        var k = Math.cos((lat1 + lat2) / 2 * Math.PI / 180);
        return Math.atan2((lon2 - lon1) * k, lat2 - lat1) * 180 / Math.PI;
      }
      function metres(lon1, lat1, lon2, lat2) {
        var k = Math.cos((lat1 + lat2) / 2 * Math.PI / 180);
        return Math.hypot((lon2 - lon1) * k, lat2 - lat1) * 111320;
      }
      function turn(from, to) { return ((to - from) % 360 + 540) % 360 - 180; }
      // The fix at or before a time, and where the glider was at that time.
      function indexAt(t) {
        var lo = 0, hi = tr.t.length - 1;
        if (t <= tr.t[0]) return 0;
        if (t >= tr.t[hi]) return hi;
        while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (tr.t[mid] <= t) lo = mid; else hi = mid; }
        return lo;
      }
      function positionAt(t) {
        var i = indexAt(t), j = Math.min(i + 1, tr.t.length - 1);
        var span = tr.t[j] - tr.t[i], f = span > 0 ? Math.min(Math.max((t - tr.t[i]) / span, 0), 1) : 0;
        return { lon: tr.lon[i] + (tr.lon[j] - tr.lon[i]) * f, lat: tr.lat[i] + (tr.lat[j] - tr.lat[i]) * f,
                 alt: tr.alt[i] + (tr.alt[j] - tr.alt[i]) * f };
      }
      // Every 10 s, the bearing from where the glider was 2.5 minutes before to where it
      // was 2.5 minutes after: circles of 20-30 s cancel out of that. Where the path over
      // those five minutes is mostly circling — under half of it went anywhere — the
      // heading is held, so a climb drifting downwind does not swing the view round and
      // back. Then averaged over ±2 minutes, as vectors, so the result turns smoothly.
      var STEP = 10, HALF = 150, SMOOTH = 12;
      var course = (function () {
        if (!hasTime) return null;
        var along = [0];
        for (var i = 1; i < tr.lon.length; i++) {
          along.push(along[i - 1] + metres(tr.lon[i - 1], tr.lat[i - 1], tr.lon[i], tr.lat[i]));
        }
        var raw = [], last = null;
        for (var t = 0; t <= duration + STEP; t += STEP) {
          var a = positionAt(t - HALF), b = positionAt(t + HALF);
          var moved = metres(a.lon, a.lat, b.lon, b.lat);
          var path = along[indexAt(t + HALF)] - along[indexAt(t - HALF)];
          if (moved > 300 && moved > path / 2) last = bearingDeg(a.lon, a.lat, b.lon, b.lat);
          raw.push(last);
        }
        // Before the first straight flight, the first direction there was; north if none.
        var first = null;
        for (var f = 0; f < raw.length && first === null; f++) first = raw[f];
        raw = raw.map(function (v) { return v === null ? (first === null ? 0 : first) : v; });
        return raw.map(function (_, i) {
          var x = 0, y = 0;
          for (var d = -SMOOTH; d <= SMOOTH; d++) {
            var w = SMOOTH + 1 - Math.abs(d);
            var v = raw[Math.min(Math.max(i + d, 0), raw.length - 1)] * Math.PI / 180;
            x += w * Math.cos(v); y += w * Math.sin(v);
          }
          return Math.atan2(y, x) * 180 / Math.PI;
        });
      })();
      function courseAt(t) {
        if (!course) return map.getBearing();
        var at = Math.min(Math.max(t / STEP, 0), course.length - 1), i = Math.floor(at);
        var j = Math.min(i + 1, course.length - 1);
        return turn(0, course[i] + turn(course[i], course[j]) * (at - i));
      }

      // Where the camera looks: the glider's mean position over ±45 s of flight, not the
      // glider itself. Locked to the glider the whole view swung round every thermal
      // circle; a circle takes 20-30 s, so over 90 s it averages to its middle and the
      // glider circles inside a steady frame instead of the frame circling with it.
      function steadyAt(t) {
        var n = 13, lon = 0, lat = 0, alt = 0;
        for (var i = 0; i < n; i++) {
          var q = positionAt(t - 45 + 90 * i / (n - 1));
          lon += q.lon; lat += q.lat; alt += q.alt;
        }
        return { lon: lon / n, lat: lat / n, alt: alt / n };
      }
      var following = false, followFrame = null, followLast = 0, fitBias = 0;
      // Where the reader has turned the view off the direction of flight, with the arrows.
      var yawOffset = 0, camCourse = null, camOffset = 0;
      // The reader's turn stays within half a circle (the pilot's call): past 180° it is the
      // same view the other way round, and kept growing it wound up into a turn the camera
      // then had to unwind. The shown offset moves with it, so wrapping does not spin.
      function wrapOffset() {
        if (yawOffset > 180) { yawOffset -= 360; camOffset -= 360; }
        else if (yawOffset <= -180) { yawOffset += 360; camOffset += 360; }
      }
      var cam = null;          // { bearing, zoom, pitch } the camera is easing towards
      // The next step on an animation frame or, failing one within 100 ms, a timer: a
      // browser that stops serving frames to a page it considers hidden or idle (an
      // occluded window, a headless one) would otherwise freeze the camera mid-turn.
      function kickFollow() {
        if (!following || followFrame) return;
        var done = false;
        function go(now) {
          if (done) return;
          done = true;
          cancelAnimationFrame(followFrame.frame);
          clearTimeout(followFrame.timer);
          followFrame = null;
          followTick(typeof now === 'number' ? now : performance.now());
        }
        followFrame = { frame: requestAnimationFrame(go), timer: setTimeout(go, 100) };
      }
      function stopFollowFrame() {
        if (!followFrame) return;
        cancelAnimationFrame(followFrame.frame);
        clearTimeout(followFrame.timer);
        followFrame = null;
      }
      function followTick(now) {
        if (!following || view.hidden) return;
        var dt = followLast ? Math.min((now - followLast) / 1000, 1) : 1 / 60;
        followLast = now;
        // Two parts, eased apart so they cannot fight: the direction of flight, smoothed and
        // rate-limited as before, and the reader's own turn off it (arrows, twist), which
        // follows them within a fraction of a second. Mixed into one eased target, a turn
        // pressed while the flight was turning came out slow, partial — and past 180°
        // went the short way round, the opposite way to the one pressed.
        var target = courseAt(cutoff);
        if (camCourse === null) camCourse = map.getBearing() - camOffset;
        // Heading over 0.7 s, zoom and tilt over 0.3 s: the zoom is the reader's own.
        var kTurn = 1 - Math.exp(-dt / 0.7), kZoom = 1 - Math.exp(-dt / 0.3);
        var bearing = map.getBearing(), zoom = map.getZoom(), pitch = map.getPitch();
        var p = steadyAt(cutoff);
        var H = map.getContainer().clientHeight || 500, W = map.getContainer().clientWidth || 800;
        // Where the gliders go: 60% of the way down the part of the map nothing covers. The
        // legend, the replay bar and the buttons take the bottom third of a phone's map, and
        // a fixed "a fifth below the middle" put the gliders right under them.
        var free = freeHeight(H);
        var aimY = free * 0.6, lift = aimY - H / 2;
        // Comparing: every glider in the picture. The camera looks at the middle of the
        // group (each one's steady position at the shared "now") and pulls back just far
        // enough to hold them all with a margin — never closer than the reader's own zoom.
        // Across the view a metre is a metre; along it, the tilt foreshortens it.
        // Every glider in the air at "now", this one included only while it is flying: in
        // the map all compared flights are equal, and the replay outlasts the shortest.
        var fitZoom = Infinity, fitting = false;
        var group = (others.length && (cutoff < 0 || cutoff > duration)) ? [] : [p];
        others.forEach(function (o) {
          if (o.far) return;
          var at = cutoff - o.offset;
          if (at < o.t[0] || at > o.t[o.t.length - 1]) return;
          group.push(steadyOf(o, at));
        });
        if (group.length > 1 || (group.length === 1 && group[0] !== p)) {
          var c = { lon: 0, lat: 0, alt: 0 };
          group.forEach(function (q) { c.lon += q.lon / group.length; c.lat += q.lat / group.length; c.alt += q.alt / group.length; });
          var kx = 111320 * Math.cos(c.lat * Math.PI / 180), ky = 111320, rb = (target + yawOffset) * Math.PI / 180;
          var across = 0, along = 0;
          group.forEach(function (q) {
            var dx = (q.lon - c.lon) * kx, dy = (q.lat - c.lat) * ky;
            across = Math.max(across, Math.abs(dx * Math.cos(rb) - dy * Math.sin(rb)));
            along = Math.max(along, Math.abs(dx * Math.sin(rb) + dy * Math.cos(rb)));
          });
          // Metres a pixel that hold them. Across: half the width, with a margin. Along the
          // view it is a pinhole, not a scale — a glider nearer the camera than the centre
          // is magnified, and the centre sits `lift` px below the middle (the look-ahead),
          // so the near side has less room: d·cos t·C / (C·m − d·sin t) ≤ room, solved for m.
          var tiltNow = Math.min(pitch, 80) * Math.PI / 180;
          var Cpx = map.transform.cameraToCenterDistance || (H / 2 / Math.tan(36.87 / 2 * Math.PI / 180));
          // Measured from the point the camera looks at, which is the look-ahead's distance
          // beyond the group's middle — itself proportional to the answer, so a few rounds.
          var room = (free - aimY) * 0.8, liftPx = lift, need = across / (W / 2 * 0.8);
          for (var round = 0; round < 4; round++) {
            var aheadM = liftPx * Cpx * need / (Cpx * Math.cos(tiltNow) + liftPx * Math.sin(tiltNow));
            var near = along + aheadM;
            need = Math.max(across / (W / 2 * 0.8),
                            near * (Math.sin(tiltNow) / Cpx + Math.cos(tiltNow) / room));
          }
          if (need > 0) fitZoom = Math.log2(40075016.686 * Math.cos(c.lat * Math.PI / 180) / (512 * need));
          // And checked against what is drawn: the model is close, not exact, so each frame
          // the gliders are projected and the fit eases out while one is outside the free
          // area, and back in while all have room to spare.
          fitZoom += fitBias;
          var worst = 0;
          group.forEach(function (q) {
            try {
              var at = map.transform.coordinatePoint(
                maplibregl.MercatorCoordinate.fromLngLat([q.lon, q.lat]), q.alt * vertical);
              worst = Math.max(worst, at.y / free, Math.abs(at.x - W / 2) / (W / 2));
            } catch (error) { /* no projection yet */ }
          });
          if (worst > 0.92 && fitBias > -3) { fitBias -= 0.04; fitting = true; }
          else if (worst < 0.75 && fitBias < 0) { fitBias = Math.min(fitBias + 0.01, 0); fitting = true; }
          p = c;
        }
        var dTurn = turn(camCourse, target), dZoom = Math.min(cam.zoom, fitZoom) - zoom, dPitch = cam.pitch - pitch;
        // And never faster than 90° a second: where the flight really turns back, the
        // smoothed heading still swings half round in a few minutes of flight, which at
        // 5 min/s is under a second on screen.
        camCourse += Math.max(-90 * dt, Math.min(90 * dt, dTurn * kTurn));
        var dOffset = yawOffset - camOffset;
        camOffset += dOffset * (1 - Math.exp(-dt / 0.15));
        bearing = camCourse + camOffset;
        zoom += dZoom * kZoom; pitch += dPitch * kZoom;
        // MapLibre orbits a point on the ground, at the height of the terrain under the
        // centre, and the glider is kilometres above it (here its steady position). Estimating where on the ground
        // to look so the glider lands mid-screen worked over Krupka and hunted over the
        // Karakoram, where moving the centre onto a 7 km peak lifts the whole camera. So
        // while following, the orbit height is frozen at the glider's own altitude
        // (`_elevationFreeze`, which MapLibre's own animations use for the same purpose;
        // 4.7.1 is pinned) and the camera turns about the glider itself. The top padding
        // puts it a little below the middle, to show where it is going.
        // The glider a little below the middle, to show where it is going: the camera
        // looks at a point ahead of it, on the plane at its height. The glider is then
        // nearer the camera than that point, so it is a pinhole projection, not a scale:
        // with C the camera's distance to the centre in pixels, a point d metres before
        // the centre shows at d·cos(t)·C / (C·m − d·sin(t)) px below it (m metres a pixel,
        // t the tilt), and solving that for `lift` gives the distance. Not padding:
        // MapLibre puts the sky by the unpadded horizon, and with padding a band between
        // the sky and the far terrain was drawn as nothing at all.
        if (map.terrain) {
          map._elevationFreeze = true;
          map.transform.elevation = p.alt * vertical;
        }
        var metresPerPixel = 40075016.686 * Math.cos(p.lat * Math.PI / 180) / (512 * Math.pow(2, zoom));
        var tilt = Math.min(pitch, 85) * Math.PI / 180;
        var C = map.transform.cameraToCenterDistance || (H / 2 / Math.tan(36.87 / 2 * Math.PI / 180));
        var ahead = lift * C * metresPerPixel / (C * Math.cos(tilt) + lift * Math.sin(tilt));
        var heading = bearing * Math.PI / 180;
        map.jumpTo({ center: [p.lon + ahead * Math.sin(heading) / (111320 * Math.cos(p.lat * Math.PI / 180)),
                              p.lat + ahead * Math.cos(heading) / 111320],
                     bearing: bearing, zoom: zoom, pitch: pitch });
        if (playing || fitting || Math.abs(dTurn) > 0.05 || Math.abs(dOffset) > 0.05 ||
            Math.abs(dZoom) > 0.01 || Math.abs(dPitch) > 0.05) {
          kickFollow();
        } else followLast = 0;
      }
      // Handing the camera back: it stays where it is, now looking at the ground under
      // the middle of the view instead of at the glider, so nothing moves.
      function release() {
        if (!map.terrain || !map._elevationFreeze) {
          map.jumpTo({ padding: { top: 0, bottom: 0, left: 0, right: 0 } });
          return;
        }
        try {
          var c = map.getContainer(), tf = map.transform, was = tf.getCameraPosition();
          tf.recalculateZoom(map.terrain);
          var middle = map.unproject([c.clientWidth / 2, c.clientHeight / 2]);
          map.jumpTo({ center: middle, padding: { top: 0, bottom: 0, left: 0, right: 0 } });
          tf.recalculateZoom(map.terrain);
          // Dropping the padding still slides the camera a few kilometres over high
          // ground; at a fixed zoom, tilt and heading the camera moves with the centre,
          // so moving the centre back by the slide puts it where it was.
          for (var pass = 0; pass < 2; pass++) {
            var now = tf.getCameraPosition(), at = map.getCenter();
            map.jumpTo({ center: [at.lng + was.lngLat.lng - now.lngLat.lng,
                                  at.lat + was.lngLat.lat - now.lngLat.lat] });
          }
        } catch (error) { /* the next render settles the height either way */ }
        map._elevationFreeze = false;
        map.triggerRepaint();
      }
      // How far down the map is free of the controls along its bottom (`.m3-bottom`: the
      // replay bar and the buttons), in the map's own pixels. The legend of compared
      // flights sits top left, out of their way; at the bottom it collided with the bar.
      function freeHeight(H) {
        var top = map.getContainer().getBoundingClientRect().top, bottom = H;
        [view.querySelector('.m3-bottom')].forEach(function (el) {
          if (!el || el.hidden) return;
          var r = el.getBoundingClientRect();
          if (r.height) bottom = Math.min(bottom, r.top - top);
        });
        return Math.max(bottom, H * 0.4);
      }
      function setFollow(on) {
        if (!hasTime || on === following) return;
        following = on;
        var b = view.querySelector('[data-m3="follow"]');
        if (b) toggle(b, on);
        stopFollowFrame();
        followLast = 0;
        if (!on) release();
        // Opening on the whole flight, follow comes down to a few kilometres around the
        // glider and a view along the ground; a reader already closer keeps their zoom.
        if (on) {
          yawOffset = 0; camOffset = 0; camCourse = null;
          fitBias = 0;
          cam = { zoom: Math.max(map.getZoom(), 12.5), pitch: Math.max(map.getPitch(), 60) };
          kickFollow();
        }
      }
      // A press steps from where the camera is, never more than half a level ahead of it;
      // a pinch (`direct`) moves the target with the fingers.
      function followZoomBy(delta, direct) {
        var from = direct ? cam.zoom : Math.min(cam.zoom, map.getZoom() + 0.5);
        cam.zoom = Math.min(Math.max(from + delta, 3), 18);
        kickFollow();
      }
      // While following, every camera move is this loop's, and any of MapLibre's
      // gestures would be stopped by the next frame of it. So the wheel zooms the
      // follow camera instead, and a drag, a turn, a pinch or an arrow key hands the
      // camera back to the reader.
      // On the view, in the capture phase, so they run before MapLibre's own listeners
      // on the elements inside it.
      function onMap(event) { return map.getContainer().contains(event.target); }
      view.addEventListener('wheel', function (event) {
        if (!following || !onMap(event)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        var lines = event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? 800 : 1;
        followZoomBy(-event.deltaY * lines / 450);
      }, { capture: true, passive: false });
      // A press alone does not end following, a drag does: a click, a double-click and a
      // pinch are zooms, or nothing. With the mouse, the drag is 4 px of movement with a
      // button down; with fingers, 8 px of one finger. Two fingers are a pinch, taken
      // here from MapLibre — whose own pinch the next follow frame would stop — and
      // turned into the follow camera's zoom.
      function onCanvas(event) { return map.getCanvasContainer().contains(event.target); }
      var pressed = null;
      view.addEventListener('pointerdown', function (event) {
        if (following && onCanvas(event) && event.pointerType === 'mouse') {
          pressed = { x: event.clientX, y: event.clientY };
        }
      }, true);
      view.addEventListener('pointermove', function (event) {
        if (!pressed || !following || event.pointerType !== 'mouse') return;
        if (Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) > 4) {
          pressed = null;
          setFollow(false);
        }
      }, true);
      window.addEventListener('pointerup', function () { pressed = null; }, true);
      view.addEventListener('dblclick', function (event) {
        if (!following || !onCanvas(event)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        followZoomBy(event.shiftKey ? -1 : 1);
      }, true);
      var touch = null;   // { x, y } of one finger, or two: { spread, y, angle }
      var lastTap = 0;
      function spread(touches) {
        return Math.hypot(touches[0].clientX - touches[1].clientX,
                          touches[0].clientY - touches[1].clientY);
      }
      // Two fingers as MapLibre reads them, onto the follow camera: their spread zooms,
      // moving both up or down tilts (half a degree a pixel, MapLibre's own rate), and a
      // twist turns the view off the direction of flight as ← → do. A phone has no
      // arrows, and taking two fingers as a pinch alone left it no way to tilt or turn.
      function fingers(touches) {
        return { spread: spread(touches),
                 y: (touches[0].clientY + touches[1].clientY) / 2,
                 angle: Math.atan2(touches[1].clientY - touches[0].clientY,
                                   touches[1].clientX - touches[0].clientX) * 180 / Math.PI };
      }
      function takeTouch(event) {
        if (event.cancelable) event.preventDefault();
        event.stopImmediatePropagation();
      }
      view.addEventListener('touchstart', function (event) {
        if (!following || !onCanvas(event)) return;
        if (event.touches.length >= 2) {
          touch = fingers(event.touches);
          takeTouch(event);
        } else {
          touch = { x: event.touches[0].clientX, y: event.touches[0].clientY, at: Date.now() };
          // A double tap zooms in, as MapLibre's own does.
          if (touch.at - lastTap < 300) { followZoomBy(1); takeTouch(event); }
          lastTap = touch.at;
        }
      }, { capture: true, passive: false });
      view.addEventListener('touchmove', function (event) {
        if (!following || !touch) return;
        if (event.touches.length >= 2) {
          var now = fingers(event.touches);
          if (touch.spread && now.spread > 0) {
            followZoomBy(Math.log2(now.spread / touch.spread), true);
            cam.pitch = Math.min(85, Math.max(0, cam.pitch - (now.y - touch.y) * 0.5));
            yawOffset -= turn(touch.angle, now.angle);
            wrapOffset();
            kickFollow();
          }
          touch = now;
          takeTouch(event);
        } else if (touch.x !== undefined && Math.hypot(event.touches[0].clientX - touch.x,
                                                      event.touches[0].clientY - touch.y) > 8) {
          touch = null;
          setFollow(false);
        } else if (touch.spread) {
          // One finger left of a pinch: still the pinch, not a drag.
          takeTouch(event);
        }
      }, { capture: true, passive: false });
      view.addEventListener('touchend', function (event) {
        if (!touch) return;
        if (touch.spread) {
          takeTouch(event);
          if (!event.touches.length) touch = null;
        } else if (!event.touches.length) touch = null;
      }, { capture: true, passive: false });
      // Keys anywhere in the view, not only on the map: the reader has just pressed the
      // follow button, so that is where focus is, and arrows sent there did nothing.
      function inView(event) {
        return view.contains(event.target) && !/^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName);
      }
      // Space plays and pauses from anywhere in the view. On a focused bar button it also
      // "clicked" that button — the camera, say — as well as toggling the replay.
      view.addEventListener('keydown', function (event) {
        if (event.key !== ' ' || !inView(event) || event.ctrlKey || event.metaKey || event.altKey) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        togglePlay();
      }, true);
      view.addEventListener('keydown', function (event) {
        if (!following || !inView(event)) return;
        var k = event.key;
        if (k === '+' || k === '=' || k === '-' || k === '_') {
          event.preventDefault();
          event.stopImmediatePropagation();
          followZoomBy(k === '+' || k === '=' ? 1 : -1);
        } else if (/^Arrow/.test(k)) {
          // The arrows turn and tilt the following camera rather than ending it: ← → put
          // the view 15° off the direction of flight and keep it there as the flight
          // turns, ↑ ↓ tilt by 10° — MapLibre's own shift+arrow steps and senses. A pan
          // means nothing while the camera rides with the glider, so shift is not needed.
          event.preventDefault();
          event.stopImmediatePropagation();
          // The pilot's way round (October 2026): → turns the view 15° to the left of the
          // direction of flight, ↑ tilts it down towards the ground.
          if (k === 'ArrowLeft') { yawOffset += 15; wrapOffset(); }
          else if (k === 'ArrowRight') { yawOffset -= 15; wrapOffset(); }
          else cam.pitch = Math.min(85, Math.max(0, cam.pitch + (k === 'ArrowUp' ? -10 : 10)));
          kickFollow();
        }
      }, true);

      // ---- measure ---------------------------------------------------------------------
      // Click points, read the distance: the total and the last leg, on the FAI sphere —
      // what a scored distance is measured on (`js/geo.js`). The line is MapLibre's own,
      // so it lies on the ground. Backspace takes a point back; Esc or the button ends it.
      var measuring = false, measurePoints = [];
      var measureText = view.querySelector('.m3-measure');
      function sphere(a, b) {
        var r = Math.PI / 180, la1 = a[1] * r, la2 = b[1] * r;
        var h = Math.pow(Math.sin((la2 - la1) / 2), 2)
          + Math.cos(la1) * Math.cos(la2) * Math.pow(Math.sin((b[0] - a[0]) * r / 2), 2);
        return 2 * 6371000 * Math.asin(Math.min(1, Math.sqrt(h)));
      }
      function km(metres) { return metres < 10000 ? (metres / 1000).toFixed(2) : (metres / 1000).toFixed(1); }
      function drawOverlay(id, features) {
        var source = map.getSource(id);
        if (source) source.setData({ type: 'FeatureCollection', features: features });
      }
      function showMeasure() {
        var features = measurePoints.map(function (p) {
          return { type: 'Feature', geometry: { type: 'Point', coordinates: p }, properties: {} };
        });
        if (measurePoints.length > 1) {
          features.unshift({ type: 'Feature', properties: {},
                             geometry: { type: 'LineString', coordinates: measurePoints } });
        }
        drawOverlay('measure', features);
        var total = 0;
        for (var i = 1; i < measurePoints.length; i++) total += sphere(measurePoints[i - 1], measurePoints[i]);
        var last = measurePoints.length > 1
          ? sphere(measurePoints[measurePoints.length - 2], measurePoints[measurePoints.length - 1]) : 0;
        measureText.textContent = measurePoints.length < 2 ? 'Measure: click points on the map'
          : km(total) + ' km' + (measurePoints.length > 2 ? ' · last leg ' + km(last) + ' km' : '');
      }
      function setMeasure(on) {
        measuring = on;
        measurePoints = [];
        var b = view.querySelector('[data-m3="measure"]');
        toggle(b, on);
        measureText.hidden = !on;
        map.getCanvas().style.cursor = on ? 'crosshair' : '';
        showMeasure();
      }
      view.addEventListener('keydown', function (event) {
        if (!measuring || !inView(event)) return;
        if (event.key === 'Escape') { setMeasure(false); event.preventDefault(); event.stopImmediatePropagation(); }
        else if (event.key === 'Backspace') {
          measurePoints.pop(); showMeasure();
          event.preventDefault(); event.stopImmediatePropagation();
        }
      }, true);

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
          map.setLayoutProperty(name + '-0', 'visibility', name === key ? 'visible' : 'none');
        });
        SHADES.forEach(function (id) {
          map.setLayoutProperty(id, 'visibility', id === shadeFor(key) ? 'visible' : 'none');
        });
        map.setLayoutProperty('place-labels', 'visibility', labelled[key] ? 'visible' : 'none');
        map.setPaintProperty('bg', 'background-color', groundColour(key));
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
      // Full screen takes the flight's map block where the page has one (`.flight-map`:
      // the map with the side view under it), the panel alone where it does not.
      function fullscreen() {
        var target = panel.closest('.flight-map') || panel;
        var maximise = function () {
          target.classList.toggle('is-maximised');
          setTimeout(function () { map.resize(); }, 0);
        };
        if (document.fullscreenElement === target) { document.exitFullscreen(); return; }
        if (target.classList.contains('is-maximised')) { maximise(); return; }
        try {
          var p = target.requestFullscreen && target.requestFullscreen();
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
        else if (act === 'zoom-in') { if (following) followZoomBy(1); else map.zoomIn(); }
        else if (act === 'zoom-out') { if (following) followZoomBy(-1); else map.zoomOut(); }
        else if (act === 'help') help.hidden = !help.hidden;
        else if (act === 'measure') setMeasure(!measuring);
        else if (act === 'fullscreen') fullscreen();
        else if (act === 'reset') { setFollow(false); fit(true); }
        else if (act === 'play') togglePlay();
        else if (act === 'replay') openReplay(replay.hidden);
        else if (act === 'follow') setFollow(!following);
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
        else if (k === '0') { setFollow(false); fit(true); }
        else if ((k === 'c' || k === 'C') && hasTime) {
          if (replay.hidden) openReplay(true);
          setFollow(!following);
        }
        else if (k === '?') help.hidden = !help.hidden;
        else if (k === 'd' || k === 'D') setMeasure(!measuring);
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
                 replay: !!(replay && !replay.hidden), from: from, cutoff: cutoff, speed: speed,
                 follow: following };
      };
      api.dispose = function () {
        pause();
        setFollow(false);
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
        if (restore.follow) setFollow(true);
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
        // Measuring takes the click: it is not also a turnpoint.
        if (measuring) { measurePoints.push(at); showMeasure(); return; }
        clickers.forEach(function (fn) { fn(at, event.originalEvent); });
      });

      // A comparison chosen before this view was built.
      var myUid = (panel.querySelector('.view3d') || { id: '' }).id.replace(/^view3d-/, '');
      if (window.__compareFor) setOthers(window.__compareFor(myUid));

      var entry = {
        setOthers: setOthers,
        map: map, setTime: setTime, setFrom: setFrom, cursor: function () { return cursor; },
        setFollow: setFollow, following: function () { return following; }, courseAt: courseAt,
        followCamera: function () { return following ? { zoom: cam.zoom, pitch: cam.pitch, turn: yawOffset } : null; },
        setBasemap: setBasemap, setVertical: setVertical,
        setRoute: function (walk, points) {
          route = walk || points ? { walk: walk || [], points: points || [] } : null;
          refresh();
        },
        onClick: function (fn) { clickers.push(fn); },
        // What deck.gl draws now, as ids and depth parameters: for the tests, which cannot
        // tell a hidden track from a missing one by looking.
        layers: function () {
          return layers().map(function (l) { return { id: l.id, parameters: l.props.parameters || null }; });
        },
        // GeoJSON polygons drawn on the ground under everything else on the map, each with
        // optional `colour` and `opacity` properties; null or [] clears them.
        setShapes: function (features) {
          pendingShapes = features || [];
          if (styleReady) drawOverlay('shapes', pendingShapes);
        },
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
      window.__mergedAll[panel.querySelector('.view3d').id] = entry;
      // For whatever else draws on this panel — the planner listens for it.
      panel.dispatchEvent(new CustomEvent('merged-ready', { detail: entry }));
    }, function (error) {
      view.querySelector('.m3-status').textContent =
        'The map could not be loaded (' + error.message + '). It needs a network.';
    });
    return api;
  };
})();
"""

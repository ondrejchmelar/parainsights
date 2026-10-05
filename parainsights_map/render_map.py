"""The plain MapLibre 3D view and the renderer switch above every 3D panel.

The report's 3D panels offer three renderers — the canvas (`view3d`), plain MapLibre
(here) and the merged view (`map3d`) — behind one switch (`switch_html`,
`SWITCH_SCRIPT`). MapLibre and deck.gl are loaded from unpkg on the first switch, never
before; the loader is shared with `map3d`. Nothing needs an API key: the terrain is the
AWS Open Data terrarium DEM and the imagery is the panel's own tile sources.
"""


MAPLIBRE = "https://unpkg.com/maplibre-gl@4.7.1/dist"
DECK = "https://unpkg.com/deck.gl@9.0.35/dist.min.js"
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


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
      // CORS mode, so an error inside MapLibre or deck.gl reaches `window.onerror` with
      // its message rather than as an opaque "Script error.".
      node.crossOrigin = 'anonymous';
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

  // The canvas view's handle where it came up; otherwise a stand-in carrying the scene
  // from the panel's own data. MapLibre fetches its own ground, so a canvas view that
  // failed to fetch terrain must not take the other two renderers down with it — there is
  // just no linked cursor to follow until the canvas exists.
  function handleFor(host) {
    var canvas = host.querySelector('canvas.view3d');
    var real = canvas && window.__view3dAll ? window.__view3dAll[canvas.id] : null;
    if (real) return real;
    if (host.__standIn) return host.__standIn;
    var data = host.querySelector('.view3d-data');
    try {
      var scene = data && readScene(data);
      if (!scene || !scene.track || !scene.track.lon || !scene.track.lon.length) return null;
      return (host.__standIn = { built: { scene: scene, cursorTrack: null } });
    } catch (error) {
      return null;
    }
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

  function mount(host, handle, restore) {
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
      if (restore) {
        map.jumpTo(restore);
      } else if (west < east || south < north) {
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
        // Stops on the landing rather than wrapping round; play again starts over.
        if (next >= duration) { setTime(duration); pause(); return; }
        setTime(next);
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
      var unwrap = [];
      ['setCursor', 'revealCursor'].forEach(function (name) {
        var original = handle[name];
        if (typeof original !== 'function') return;
        unwrap.push({ name: name, original: original });
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
      unwrap.push({ name: 'clearCursor', original: clear });
      handle.clearCursor = function () {
        cursor = null;
        if (!view.hidden) refresh();
        return clear ? clear.apply(handle, arguments) : undefined;
      };
      unwrap.forEach(function (w) { w.wrapper = handle[w.name]; });
      // The same recovery as the merged view's: see `contextLost` there.
      api.lost = function () {
        return Array.prototype.some.call(view.querySelectorAll('canvas'), function (canvas) {
          var gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
          return !!(gl && gl.isContextLost());
        });
      };
      api.snapshot = function () {
        var c = map.getCenter();
        return { center: [c.lng, c.lat], zoom: map.getZoom(), bearing: map.getBearing(),
                 pitch: map.getPitch() };
      };
      api.dispose = function () {
        pause();
        unwrap.forEach(function (w) { if (handle[w.name] === w.wrapper) handle[w.name] = w.original; });
        try { map.remove(); } catch (error) { /* a dead context can throw on the way out */ }
        view.remove();
      };
      map.on('webglcontextlost', function () {
        setTimeout(function () { if (window.__reviveMaps) window.__reviveMaps(); }, 1500);
      });
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

  function mounts() { return { maplibre: mount, merged: window.__mountMerged }; }

  // Rebuild any MapLibre view whose WebGL context is gone, in place and as it was. A
  // phone takes the contexts of a page it locks or backgrounds and often never returns
  // them; the map then stays black while its buttons still answer. Checked when the page
  // comes back into view, and shortly after MapLibre reports a loss.
  // Open a host on the renderer it asks for (`data-renderer-default`), once its canvas
  // view is built, and fall back to the canvas if MapLibre cannot be fetched — offline,
  // or blocked — rather than leaving a panel that says so.
  window.__openDefaultRenderer = function (host) {
    var wanted = host && host.dataset.rendererDefault;
    var button = wanted && host.querySelector('[data-renderer="' + wanted + '"]');
    if (!button || !window.__mapLibs) return;
    button.click();
    window.__mapLibs().catch(function () {
      var canvasButton = host.querySelector('[data-renderer="canvas"]');
      if (canvasButton) canvasButton.click();
    });
  };

  window.__reviveMaps = function () {
    document.querySelectorAll('.renderer-host').forEach(function (host) {
      var all = host.__renderers || {};
      Object.keys(all).forEach(function (key) {
        var built = all[key];
        if (!built.api.lost || !built.api.lost()) return;
        var snapshot = built.api.snapshot();
        var shown = !built.api.view.hidden;
        built.api.dispose();
        built.api = mounts()[key](host, built.handle, snapshot);
        if (shown) built.api.show(); else built.api.hide();
      });
    });
  };
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') setTimeout(window.__reviveMaps, 300);
  });
  window.addEventListener('pageshow', function () { setTimeout(window.__reviveMaps, 300); });

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
    var mount_ = mounts();
    if (want !== 'canvas' && (!handle || !handle.built || !mount_[want])) {
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
      built = host.__renderers[want] = { handle: handle, api: mount_[want](host, handle) };
    }
    built.api.show();
  });
})();
"""
    .replace("__MAPLIBRE__", MAPLIBRE)
    .replace("__DECK__", DECK)
    .replace("__TERRARIUM__", TERRARIUM)
)

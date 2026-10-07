"""Loading MapLibre and deck.gl, and opening the 3D map (`map3d`) in a panel.

Every 3D panel is a `.renderer-host` holding a `view3d.panel`; once the panel's scene is
ready (`initView3dWhenReady`), `window.__openMap(host)` mounts the map over it. MapLibre
and deck.gl are loaded from unpkg once per page, on the first map opened. Nothing needs an
API key: the terrain is the AWS Open Data terrarium DEM and the imagery is the panel's
own tile sources.

There used to be three renderers behind a switch here — the canvas (`view3d`), plain
MapLibre and the merged view. The merged view became the default and then the only one
(October 2026); the other two are in git history. Without a network there is no map,
and the panel says so: the canvas was the offline fallback, and nobody reads these pages
offline.
"""


MAPLIBRE = "https://unpkg.com/maplibre-gl@4.7.1/dist"
DECK = "https://unpkg.com/deck.gl@9.0.35/dist.min.js"
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


STYLE = """
.maplibre-view { position: absolute; inset: 0; z-index: 30; background: var(--panel); }
.maplibre-view .ml-map { position: absolute; inset: 0; }
.maplibre-view .maplibregl-ctrl-bottom-right { bottom: 48px; }
.maplibre-view .maplibregl-ctrl-bottom-left { bottom: 48px; }
"""


SCRIPT = (
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

  // Once per page, however many maps open.
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

  // The panel's handle (`view3d.initView3d`), keyed by its box's id.
  function handleFor(host) {
    var box = host.querySelector('.view3d');
    return box && window.__view3dAll ? window.__view3dAll[box.id] || null : null;
  }

  // Mount the map in a host, or show the one already there. Rebuilt only when the panel
  // underneath is a new one (a flight re-analysed, an upload replaced).
  window.__openMap = function (host) {
    if (!host || !window.__mountMerged) return;
    var handle = handleFor(host);
    if (!handle || !handle.built) return;
    var built = host.__map;
    if (!built || built.handle !== handle) {
      if (built) built.api.view.remove();
      built = host.__map = { handle: handle, api: window.__mountMerged(host, handle) };
    }
    built.api.show();
  };

  // Rebuild any map whose WebGL context is gone, in place and as it was. A phone takes
  // the contexts of a page it locks or backgrounds and often never gives them back; the
  // map then stays black while its buttons still answer. Checked when the page comes back
  // into view, and shortly after MapLibre reports a loss.
  window.__reviveMaps = function () {
    document.querySelectorAll('.renderer-host').forEach(function (host) {
      var built = host.__map;
      if (!built || !built.api.lost || !built.api.lost()) return;
      var snapshot = built.api.snapshot();
      var shown = !built.api.view.hidden;
      built.api.dispose();
      built.api = window.__mountMerged(host, built.handle, snapshot);
      if (shown) built.api.show(); else built.api.hide();
    });
  };
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') setTimeout(window.__reviveMaps, 300);
  });
  window.addEventListener('pageshow', function () { setTimeout(window.__reviveMaps, 300); });
})();
"""
    .replace("__MAPLIBRE__", MAPLIBRE)
    .replace("__DECK__", DECK)
    .replace("__TERRARIUM__", TERRARIUM)
)

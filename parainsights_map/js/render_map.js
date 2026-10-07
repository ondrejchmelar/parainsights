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

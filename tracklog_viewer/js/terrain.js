/* The ground under the flight: `Terrain.at` and `terrain.clearance`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * A grid is the shape the page already uses for every DEM — bounds, `rows`, `cols` and a
 * flat row-major `z`, row 0 at the north edge — whether it came with a showcase flight or
 * was fetched for an upload. Fetching is not here: the page's own loaders do that.
 */
(function (TV) {
  'use strict';
  var igc = TV.igc;

  function cell(grid, r, c) { return grid.z[r * grid.cols + c]; }

  // Bilinear ground elevation at (lat, lon), clamped to the grid.
  function at(grid, lat, lon) {
    var gx = (lon - grid.west) / (grid.east - grid.west) * (grid.cols - 1);
    var gy = (grid.north - lat) / (grid.north - grid.south) * (grid.rows - 1);
    gx = Math.min(Math.max(gx, 0), grid.cols - 1);
    gy = Math.min(Math.max(gy, 0), grid.rows - 1);
    var x0 = Math.floor(gx), y0 = Math.floor(gy);
    var x1 = Math.min(x0 + 1, grid.cols - 1), y1 = Math.min(y0 + 1, grid.rows - 1);
    var fx = gx - x0, fy = gy - y0;
    var top = cell(grid, y0, x0) * (1 - fx) + cell(grid, y0, x1) * fx;
    var bottom = cell(grid, y1, x0) * (1 - fx) + cell(grid, y1, x1) * fx;
    return top * (1 - fy) + bottom * fy;
  }

  // Height above the ground for every fix, from GPS altitude: the DEM is geometric, and
  // pressure altitude carries the day's QNH as a constant error.
  function clearance(grid, analysis) {
    var f = analysis.flight;
    var alt = f.alt_gps.some(function (v) { return v !== 0; }) ? f.alt_gps : analysis.series.alt;
    return f.lat.map(function (lat, i) { return alt[i] - at(grid, lat, f.lon[i]); });
  }

  // The valley floor: the lowest ground within `radius` metres of each node, as a grid of
  // its own (a square window, min-filtered along the rows and then the columns).
  //
  // Height above the ground directly beneath says a pilot soaring 70 m over a ridge top
  // nearly hit the ground, with 500 m of air to the valley beside them. How low a pilot
  // really was is how far above the ground they would have to land on: the valley. The
  // radius is the floor's reach, and the answer barely depends on it — measured on five
  // flights from Krupka to the Karakoram, the lowest point moves 40 m at most between 1
  // and 5 km.
  var VALLEY_RADIUS = 2000;
  function valleyFloor(grid, radius) {
    var rows = grid.rows, cols = grid.cols, z = grid.z;
    var rowM = 111320 * (grid.north - grid.south) / Math.max(rows - 1, 1);
    var colM = 111320 * Math.cos((grid.north + grid.south) / 2 * Math.PI / 180) *
      (grid.east - grid.west) / Math.max(cols - 1, 1);
    var rx = Math.max(1, Math.round(radius / colM)), ry = Math.max(1, Math.round(radius / rowM));
    var along = new Array(rows * cols), out = new Array(rows * cols), r, c, k, low;
    for (r = 0; r < rows; r++) {
      for (c = 0; c < cols; c++) {
        low = Infinity;
        for (k = Math.max(0, c - rx); k <= Math.min(cols - 1, c + rx); k++) low = Math.min(low, z[r * cols + k]);
        along[r * cols + c] = low;
      }
    }
    for (c = 0; c < cols; c++) {
      for (r = 0; r < rows; r++) {
        low = Infinity;
        for (k = Math.max(0, r - ry); k <= Math.min(rows - 1, r + ry); k++) low = Math.min(low, along[k * cols + c]);
        out[r * cols + c] = low;
      }
    }
    return { west: grid.west, east: grid.east, south: grid.south, north: grid.north,
             rows: rows, cols: cols, z: out };
  }

  // Height above the valley floor for every fix (`valleyFloor`), from GPS altitude as
  // `clearance` is.
  function valleyClearance(grid, analysis, radius) {
    return clearance(valleyFloor(grid, radius || VALLEY_RADIUS), analysis);
  }

  // ---- the grid an upload asks for: `terrain.for_flight` + `Terrain.to_remote` ---------
  var TILE_URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
  var MAX_TILES = 64;

  function tileIndices(lat, lon, zoom) {
    var n = Math.pow(2, zoom), r = lat * TV.np.DEG;
    return [(lon + 180.0) / 360.0 * n, (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * n];
  }
  function chooseZoom(west, east, south, north) {
    for (var zoom = 12; zoom > 5; zoom--) {
      var a = tileIndices(north, west, zoom), b = tileIndices(south, east, zoom);
      if ((Math.trunc(b[0]) - Math.trunc(a[0]) + 1) * (Math.trunc(b[1]) - Math.trunc(a[1]) + 1) <= MAX_TILES) return zoom;
    }
    return 6;
  }
  function grid(west, east, south, north, cols, maxPoints) {
    var widthM = (east - west) * 111320 * Math.cos((north + south) / 2 * TV.np.DEG);
    var heightM = (north - south) * 110540;
    var rows = Math.max(Math.trunc(TV.np.pyRound(cols * heightM / Math.max(widthM, 1))), 8);
    rows = Math.min(rows, cols);
    if (rows * cols > maxPoints) {
      var shrink = Math.sqrt(maxPoints / (rows * cols));
      cols = Math.max(Math.trunc(cols * shrink), 24);
      rows = Math.max(Math.trunc(rows * shrink), 8);
    }
    return [rows, cols];
  }
  // The DEM box and grid the CLI would fetch for this flight (margin 0.35, at least 0.06°,
  // 480 columns, 120 000 nodes), as the page's `loadTerrain` takes it.
  function remoteFor(flight, options) {
    options = options || {};
    var margin = options.margin === undefined ? 0.35 : options.margin;
    var cols = options.cols || 480, maxPoints = options.maxPoints || 120000;
    var np = TV.np, west = np.min(flight.lon), east = np.max(flight.lon), south = np.min(flight.lat), north = np.max(flight.lat);
    var padX = Math.max((east - west) * margin, 0.06), padY = Math.max((north - south) * margin, 0.06);
    west -= padX; east += padX; south -= padY; north += padY;
    var size = grid(west, east, south, north, cols, maxPoints);
    return { west: np.pyRound(west, 6), east: np.pyRound(east, 6), south: np.pyRound(south, 6), north: np.pyRound(north, 6),
             rows: size[0], cols: size[1], remote: { url: TILE_URL, zoom: chooseZoom(west, east, south, north) } };
  }

  TV.terrain = { at: at, clearance: clearance, valleyFloor: valleyFloor, valleyClearance: valleyClearance,
                 VALLEY_RADIUS: VALLEY_RADIUS, cell: cell, remoteFor: remoteFor, chooseZoom: chooseZoom };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

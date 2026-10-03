/* The ground under the flight: `Terrain.at` and `terrain.clearance`, ported.
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

  TV.terrain = { at: at, clearance: clearance, cell: cell };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

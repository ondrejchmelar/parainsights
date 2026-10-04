/* Spherical geometry on the FAI sphere: `tracklog_viewer/geo.py`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * FAI-sanctioned distances are measured on a sphere of radius 6 371 000 m, so this is
 * the correct model for flight distances, not an approximation tolerated.
 */
(function (TV) {
  'use strict';
  var np = TV.np;
  var R = 6371000.0;
  var CARDINALS = 'N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW'.split(' ');

  // Haversine rather than the law of cosines: acos loses precision at the ~10 m between
  // consecutive 1 Hz fixes.
  function distance(lat1, lon1, lat2, lon2) {
    var p1 = lat1 * np.DEG, l1 = lon1 * np.DEG, p2 = lat2 * np.DEG, l2 = lon2 * np.DEG;
    var dlat = p2 - p1, dlon = l2 - l1;
    var s1 = Math.sin(dlat / 2), s2 = Math.sin(dlon / 2);
    var a = s1 * s1 + Math.cos(p1) * Math.cos(p2) * s2 * s2;
    return 2 * R * Math.asin(Math.sqrt(np.clip(a, 0, 1)));
  }

  function bearing(lat1, lon1, lat2, lon2) {
    var p1 = lat1 * np.DEG, l1 = lon1 * np.DEG, p2 = lat2 * np.DEG, l2 = lon2 * np.DEG;
    var dlon = l2 - l1;
    var y = Math.sin(dlon) * Math.cos(p2);
    var x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dlon);
    return np.mod(Math.atan2(y, x) * np.RAD, 360);
  }

  function cardinal(degrees) {
    return CARDINALS[Math.trunc(degrees / 22.5 + 0.5) % 16];
  }

  // Distance flown along the track, starting at 0. A running sum, as np.cumsum is.
  function cumulativeDistance(lat, lon) {
    var out = new Array(lat.length);
    if (!lat.length) return out;
    out[0] = 0;
    var s = 0;
    for (var i = 1; i < lat.length; i++) {
      s += distance(lat[i - 1], lon[i - 1], lat[i], lon[i]);
      out[i] = s;
    }
    return out;
  }

  TV.geo = { R: R, distance: distance, bearing: bearing, cardinal: cardinal,
             cumulativeDistance: cumulativeDistance };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

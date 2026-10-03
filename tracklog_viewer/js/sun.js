/* Where the sun was: `tracklog_viewer/sun.py` (NOAA's solar position algorithm), ported,
 * with `view3d._sun` as `forFlight`.
 *
 * The Python once tabulated the day so the page would not need the algorithm; with the
 * analysis itself in the page that reason is gone, and the table is still what the 3D
 * view interpolates, so `forFlight` builds the same one. No refraction and no
 * topographic horizon, as in the Python: the question is which slope the light reaches.
 */
(function (TV) {
  'use strict';
  var np = TV.np, igc = TV.igc;
  var HORIZON = 0.0;
  var rad = function (d) { return d * np.DEG; }, deg = function (r) { return r * np.RAD; };
  var pymod = np.mod;   // Python's float % is floored, as np.mod is

  // Julian centuries since J2000.0 from a UTC epoch in seconds.
  function julianCentury(seconds) {
    var d = new Date(seconds * 1000);
    var year = d.getUTCFullYear(), month = d.getUTCMonth() + 1;
    if (month <= 2) { year -= 1; month += 12; }
    var a = Math.floor(year / 100), b = 2 - a + Math.floor(a / 4);
    var day = d.getUTCDate() + (d.getUTCHours() + (d.getUTCMinutes() + d.getUTCSeconds() / 60) / 60) / 24;
    var jd = Math.floor(365.25 * (year + 4716)) + Math.floor(30.6001 * (month + 1)) + day + b - 1524.5;
    return (jd - 2451545.0) / 36525.0;
  }

  function position(seconds, lat, lon) {
    var jc = julianCentury(seconds);
    var meanLong = pymod(280.46646 + jc * (36000.76983 + jc * 0.0003032), 360);
    var meanAnom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc);
    var eccentricity = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc);
    var centre = Math.sin(rad(meanAnom)) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
      + Math.sin(rad(2 * meanAnom)) * (0.019993 - 0.000101 * jc)
      + Math.sin(rad(3 * meanAnom)) * 0.000289;
    var trueLong = meanLong + centre;
    var apparent = trueLong - 0.00569 - 0.00478 * Math.sin(rad(125.04 - 1934.136 * jc));
    var meanObliquity = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60;
    var obliquity = meanObliquity + 0.00256 * Math.cos(rad(125.04 - 1934.136 * jc));
    var declination = deg(Math.asin(Math.sin(rad(obliquity)) * Math.sin(rad(apparent))));
    var vary = Math.pow(Math.tan(rad(obliquity / 2)), 2);
    var eqTime = 4 * deg(
      vary * Math.sin(2 * rad(meanLong))
      - 2 * eccentricity * Math.sin(rad(meanAnom))
      + 4 * eccentricity * vary * Math.sin(rad(meanAnom)) * Math.cos(2 * rad(meanLong))
      - 0.5 * vary * vary * Math.sin(4 * rad(meanLong))
      - 1.25 * eccentricity * eccentricity * Math.sin(2 * rad(meanAnom)));
    var d = new Date(seconds * 1000);
    var minutes = d.getUTCHours() * 60 + d.getUTCMinutes() + d.getUTCSeconds() / 60;
    var trueSolar = pymod(minutes + eqTime + 4 * lon, 1440);
    var hourAngle = trueSolar / 4 - 180;
    var latR = rad(lat), decR = rad(declination), haR = rad(hourAngle);
    var cosZenith = Math.sin(latR) * Math.sin(decR) + Math.cos(latR) * Math.cos(decR) * Math.cos(haR);
    cosZenith = Math.max(-1.0, Math.min(1.0, cosZenith));
    var zenith = Math.acos(cosZenith);
    var elevation = 90 - deg(zenith);
    var azimuth, sinZenith = Math.sin(zenith);
    if (Math.abs(sinZenith) < 1e-9 || Math.abs(Math.cos(latR)) < 1e-9) {
      azimuth = 180.0;
    } else {
      var ratio = ((Math.sin(latR) * cosZenith) - Math.sin(decR)) / (Math.cos(latR) * sinZenith);
      ratio = Math.max(-1.0, Math.min(1.0, ratio));
      azimuth = deg(Math.acos(ratio));
      azimuth = hourAngle > 0 ? pymod(azimuth + 180, 360) : pymod(540 - azimuth, 360);
    }
    return { azimuth: azimuth, elevation: elevation };
  }

  function midnight(date) { return Date.UTC(date.year, date.month - 1, date.day) / 1000; }

  // The whole day at one place, every `step` minutes, azimuth unwrapped so interpolation
  // never sweeps the light the long way round.
  function dayTrack(date, lat, lon, step) {
    step = step || 10;
    var az = [], el = [], previous = null, base = midnight(date);
    for (var minute = 0; minute < 24 * 60; minute += step) {
      var where = position(base + minute * 60, lat, lon), bearing = where.azimuth;
      if (previous !== null) {
        while (bearing - previous > 180) bearing -= 360;
        while (previous - bearing > 180) bearing += 360;
      }
      previous = bearing;
      az.push(np.pyRound(bearing, 1));
      el.push(np.pyRound(where.elevation, 1));
    }
    return { step: step, az: az, el: el };
  }

  function crossing(date, lat, lon, low, high) {
    var base = midnight(date);
    function at(minute) { return position(base + minute * 60, lat, lon).elevation; }
    if ((at(low) > HORIZON) === (at(high) > HORIZON)) return null;
    for (var i = 0; i < 24; i++) {
      var mid = (low + high) / 2;
      if ((at(low) > HORIZON) === (at(mid) > HORIZON)) low = mid; else high = mid;
    }
    return (low + high) / 2;
  }

  function riseAndSet(date, lat, lon) {
    var base = midnight(date), samples = [];
    for (var m = 0; m <= 24 * 60; m += 10) samples.push([m, position(base + m * 60, lat, lon).elevation]);
    var rise = null, set = null;
    for (var k = 0; k + 1 < samples.length; k++) {
      var e0 = samples[k][1], e1 = samples[k + 1][1];
      if (e0 <= HORIZON && HORIZON < e1 && rise === null) rise = crossing(date, lat, lon, samples[k][0], samples[k + 1][0]);
      if (e0 > HORIZON && HORIZON >= e1 && set === null) set = crossing(date, lat, lon, samples[k][0], samples[k + 1][0]);
    }
    return { rise: rise, set: set };
  }

  // `view3d._sun`: the day over the middle of the flight, in UTC minutes, with the
  // minutes to add to read them as the pilot's own clock.
  function forFlight(flight) {
    var lat = np.median(flight.lat), lon = np.median(flight.lon);
    var t0 = flight.time[0], n = flight.time.length;
    var utc0 = new Date(t0 * 1000);
    var date = { year: utc0.getUTCFullYear(), month: utc0.getUTCMonth() + 1, day: utc0.getUTCDate() };
    var p = igc.localParts(t0, flight.timezone);
    var offset = Math.floor((Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) / 1000 - t0) / 60);
    function utcMinutes(t) { var d = new Date(t * 1000); return d.getUTCHours() * 60 + d.getUTCMinutes(); }
    var times = riseAndSet(date, lat, lon);
    var start = utcMinutes(t0), finish = utcMinutes(flight.time[n - 1]);
    return {
      track: dayTrack(date, lat, lon),
      date: date.year + '-' + (date.month < 10 ? '0' : '') + date.month + '-' + (date.day < 10 ? '0' : '') + date.day,
      offset: offset, launch: start, landing: finish,
      at: finish >= start ? Math.floor((start + finish) / 2) : start,
      rise: times.rise !== null ? np.pyRound(times.rise) : null,
      set: times.set !== null ? np.pyRound(times.set) : null
    };
  }

  TV.sun = { HORIZON: HORIZON, position: position, dayTrack: dayTrack, riseAndSet: riseAndSet,
             forFlight: forFlight };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

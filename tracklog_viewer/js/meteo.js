/* The day's vertical profile: `tracklog_viewer/meteo.py`, ported — the request and the
 * reading of the answer. The fetching is the page's (Open-Meteo answers CORS), and
 * `now` is a parameter wherever the Python asks the clock, so the same response reads
 * the same way in a test.
 *
 * Metres per second throughout, asked for as `wind_speed_unit=ms`: a modelled wind in
 * km/h mixed into an m/s field was once 3.6 times too strong.
 */
(function (TV) {
  'use strict';
  var geo = TV.geo, np = TV.np;

  var FORECAST_ENDPOINT = 'https://api.open-meteo.com/v1/forecast';
  var ARCHIVE_ENDPOINT = 'https://archive-api.open-meteo.com/v1/archive';
  var RECENT_DAYS = 60;
  var PRESSURE_LEVELS = [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500];
  var SURFACE_FIELDS = ['temperature_2m', 'dew_point_2m', 'cape', 'boundary_layer_height',
                        'cloud_cover_low', 'cloud_cover_mid', 'wind_speed_10m', 'wind_direction_10m'];
  var LEVEL_FIELDS = ['temperature', 'dew_point', 'wind_speed', 'wind_direction', 'geopotential_height'];
  var DALR = 9.8 / 1000, LCL_PER_DEGREE = 125.0;

  function dayNumber(seconds) { return Math.floor(seconds / 86400); }
  function isoDay(seconds) { return new Date(seconds * 1000).toISOString().slice(0, 10); }

  // The URL for the hour nearest `when` (UTC epoch seconds) over (lat, lon).
  function request(lat, lon, when, now) {
    var hourly = SURFACE_FIELDS.slice();
    PRESSURE_LEVELS.forEach(function (level) {
      LEVEL_FIELDS.forEach(function (field) { hourly.push(field + '_' + level + 'hPa'); });
    });
    var daysAgo = dayNumber(now) - dayNumber(when);
    var params = [['wind_speed_unit', 'ms'], ['latitude', np.pyRound(lat, 3)], ['longitude', np.pyRound(lon, 3)],
                  ['hourly', hourly.join(',')], ['timezone', 'UTC']];
    var endpoint;
    if (daysAgo > RECENT_DAYS) {
      endpoint = ARCHIVE_ENDPOINT;
      params.push(['start_date', isoDay(when)], ['end_date', isoDay(when)]);
    } else {
      endpoint = FORECAST_ENDPOINT;
      params.push(['past_days', Math.max(Math.min(daysAgo + 1, 92), 1)], ['forecast_days', 1]);
    }
    return endpoint + '?' + params.map(function (p) {
      return encodeURIComponent(p[0]) + '=' + encodeURIComponent(String(p[1]));
    }).join('&');
  }

  function maybe(v) { return v === null || v === undefined ? null : +v; }
  // Python's `x or y`: a zero, like a missing value, falls through.
  function or(v, fallback) { return v ? v : fallback; }

  function parseStamp(text) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/.exec(text);
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) / 1000 : NaN;
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function parse(payload, when, now) {
    var hourly = (payload && payload.hourly) || {}, times = hourly.time || [];
    if (!times.length) return null;
    var stamps = times.map(parseStamp), index = 0;
    for (var i = 1; i < stamps.length; i++) if (Math.abs(stamps[i] - when) < Math.abs(stamps[index] - when)) index = i;
    if (Math.abs(stamps[index] - when) > 5400) return null;
    function value(name) {
      var column = hourly[name];
      if (!column || !column.length || index >= column.length) return null;
      return column[index];
    }
    var levels = [];
    PRESSURE_LEVELS.forEach(function (pressure) {
      var height = value('geopotential_height_' + pressure + 'hPa'), temperature = value('temperature_' + pressure + 'hPa');
      if (height === null || height === undefined || temperature === null || temperature === undefined) return;
      levels.push({ pressure: pressure, height: +height, temperature: +temperature,
                    dew_point: +or(value('dew_point_' + pressure + 'hPa'), temperature),
                    wind_speed: +or(value('wind_speed_' + pressure + 'hPa'), 0.0),
                    wind_direction: +or(value('wind_direction_' + pressure + 'hPa'), 0.0) });
    });
    levels.sort(function (a, b) { return a.height - b.height; });
    var surface = value('temperature_2m');
    if (surface === null || surface === undefined) return null;
    var d = new Date(stamps[index] * 1000);
    var old = dayNumber(now) - dayNumber(stamps[index]) > RECENT_DAYS;
    return {
      valid_at: d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) + ' ' +
        pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ' UTC',
      source: old ? (levels.length ? 'ERA5 reanalysis' : 'ERA5 reanalysis, surface only') : 'Open-Meteo operational model',
      latitude: +or(payload.latitude, 0.0), longitude: +or(payload.longitude, 0.0),
      elevation: +or(payload.elevation, 0.0),
      surface_temperature: +surface, surface_dew_point: +or(value('dew_point_2m'), surface),
      surface_wind_speed: +or(value('wind_speed_10m'), 0.0),
      surface_wind_direction: +or(value('wind_direction_10m'), 0.0),
      cape: maybe(value('cape')), boundary_layer_height: maybe(value('boundary_layer_height')),
      cloud_cover_low: maybe(value('cloud_cover_low')), cloud_cover_mid: maybe(value('cloud_cover_mid')),
      levels: levels
    };
  }

  function cloudbase(m) { return m.elevation + LCL_PER_DEGREE * Math.max(m.surface_temperature - m.surface_dew_point, 0.0); }
  function boundaryLayerTop(m) { return m.boundary_layer_height === null ? null : m.elevation + m.boundary_layer_height; }

  // A dry adiabat from the surface, crossed against the model's temperatures.
  function thermalTop(m) {
    var previous = null;
    for (var i = 0; i < m.levels.length; i++) {
      var level = m.levels[i];
      if (level.height <= m.elevation) continue;
      var excess = m.surface_temperature - DALR * (level.height - m.elevation) - level.temperature;
      if (previous && previous[1] > 0 && 0 >= excess) {
        var span = previous[1] - excess, fraction = span ? previous[1] / span : 0.0;
        return previous[0] + fraction * (level.height - previous[0]);
      }
      previous = [level.height, excess];
    }
    return null;
  }

  // The model wind at an altitude: [m/s, degrees from], the short way round.
  function windAt(m, height) {
    var levels = m.levels.filter(function (l) { return l.height !== null; });
    if (!levels.length) return null;
    var below = levels.filter(function (l) { return l.height <= height; });
    var above = levels.filter(function (l) { return l.height > height; });
    if (!below.length) return [above[0].wind_speed, above[0].wind_direction];
    if (!above.length) return [below[below.length - 1].wind_speed, below[below.length - 1].wind_direction];
    var low = below[below.length - 1], high = above[0], span = high.height - low.height;
    var fraction = span ? (height - low.height) / span : 0.0;
    var speed = low.wind_speed + fraction * (high.wind_speed - low.wind_speed);
    var delta = np.mod(high.wind_direction - low.wind_direction + 180, 360) - 180;
    return [speed, np.mod(low.wind_direction + fraction * delta, 360)];
  }

  function toDict(m) {
    var top = thermalTop(m), bl = boundaryLayerTop(m);
    return Object.assign({}, m, { cloudbase: np.pyRound(cloudbase(m)), thermal_top: top ? np.pyRound(top) : null,
                                  boundary_layer_top: bl ? np.pyRound(bl) : null });
  }

  // The weather object the debrief and the air mass take, as Python's Meteo is used.
  function weather(m) {
    return { cloudbase: cloudbase(m), thermal_top: thermalTop(m),
             windAt: function (h) { return windAt(m, h); } };
  }

  // The fix the Python asks about: the middle one, by index.
  function middleOf(flight) {
    var k = Math.floor(flight.time.length / 2);
    return { lat: flight.lat[k], lon: flight.lon[k], when: flight.time[k] };
  }

  TV.meteo = { request: request, parse: parse, cloudbase: cloudbase, thermalTop: thermalTop,
               boundaryLayerTop: boundaryLayerTop, windAt: windAt, toDict: toDict, weather: weather,
               middleOf: middleOf, cardinal: function (d) { return geo.cardinal(d); } };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));

"""The meteo view: a day, ranked by site, with the sounding behind each verdict.

Three things a pilot asks before driving, in the order they are asked:

1. **Is it worth going anywhere today?** — the day strip, and the sounding.
2. **Where?** — the site list, ordered by how the forecast wind sits on each takeoff.
3. **When?** — the meteogram, hour by hour.

Everything here is drawn in the browser from numbers fetched at view time, which is the
one place in this repository that is deliberately not self-contained: a forecast built at
03:00 and published is wrong by lunchtime, and there is no build step between the reader
and the site. See `docs/meteo.md` for what that costs.

The charts are canvas rather than SVG for the same reason `quicklook.py`'s are: they are
redrawn whenever the reader moves the hour slider, and rebuilding a few hundred SVG nodes
on every step of a range input is what makes a page feel heavy.
"""

from __future__ import annotations

import json

from . import flymet as flymet_data
from . import sites as site_data
from .sources import distance_m

# Past this the nearest station is not the same weather and saying so would be worse than
# saying nothing. Nothing in the Czech list is anywhere near it — the worst takeoff here
# is 21 km from a station and the median is 9 — so this is a guard for a list that grows
# rather than a filter that fires today.
FLYMET_RANGE_KM = 60

# Open-Meteo, keyless and CORS-open. The pressure levels are `tracklog_viewer/meteo.py`'s,
# so a forecast profile and a flown profile are the same shape and can be read against
# each other without a conversion nobody would remember.
LEVELS = (1000, 975, 950, 925, 900, 850, 800, 700, 600, 500)
ENDPOINT = "https://api.open-meteo.com/v1/forecast"

# The lapse rate at or below which a layer is drawn as the lid on the day. Here because
# the caption has to state it and the caption is written in Python; the rule itself is in
# the script, and a test holds the two to the same number.
CAP_LAPSE = 2.0

STYLE = """
.met-head { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:baseline;
  margin: 0 0 12px; }
.met-days { display:inline-flex; border:1px solid var(--rule); border-radius:3px;
  overflow:hidden; }
.met-days button { border:0; border-right:1px solid var(--rule); border-radius:0;
  padding:5px 13px; background:var(--panel); }
.met-days button:last-child { border-right:0; }
.met-days button.is-on { background:var(--ink); color:var(--paper); }
.met-grid { display:grid; grid-template-columns: minmax(0,340px) minmax(0,1fr);
  gap:18px; align-items:start; }
@media (max-width: 820px) { .met-grid { grid-template-columns: 1fr; } }
.met-list { border:1px solid var(--rule); border-radius:4px; overflow:hidden;
  max-height:70vh; overflow-y:auto; }
.met-site { display:grid; grid-template-columns: 1fr auto; gap:2px 10px; width:100%;
  text-align:left; border:0; border-bottom:1px solid var(--rule); border-radius:0;
  padding:8px 11px; background:var(--paper); cursor:pointer; }
.met-site:last-child { border-bottom:0; }
.met-site:hover { background:var(--panel); }
.met-site.is-on { background:var(--panel-2); }
.met-site-name { font-weight:600; font-size:13.5px; }
.met-site-note { grid-column:1; font-size:11.5px; color:var(--ink-3);
  font-variant-numeric:tabular-nums; }
.met-verdict { grid-column:2; grid-row:1 / span 2; align-self:center; font-size:11px;
  text-transform:uppercase; letter-spacing:.06em; padding:3px 7px; border-radius:3px;
  white-space:nowrap; }
.met-good { background:#15803d; color:#fff; }
.met-fair { background:#a16207; color:#fff; }
.met-poor { background:var(--panel-2); color:var(--ink-3); }
.met-none { background:transparent; color:var(--ink-3); border:1px dashed var(--rule); }
.met-panel { border:1px solid var(--rule); border-radius:4px; padding:14px 16px; }
.met-panel h3 { margin:0 0 2px; font-size:17px; }
.met-sub { margin:0 0 12px; color:var(--ink-3); font-size:12.5px; }
.met-charts { display:grid; grid-template-columns: minmax(0,1fr) minmax(0,260px);
  gap:16px; }
@media (max-width: 700px) { .met-charts { grid-template-columns: 1fr; } }
.met-canvas { width:100%; display:block; background:var(--panel); border-radius:3px; }
.met-hour { display:flex; align-items:center; gap:10px; margin:10px 0 0;
  font-size:12.5px; color:var(--ink-2); }
.met-hour input { flex:1; }
.met-figures { display:flex; flex-wrap:wrap; gap:6px 22px; margin:12px 0 0;
  font-size:12.5px; }
.met-figures div { display:flex; flex-direction:column; }
.met-figures .k { font-size:10.5px; text-transform:uppercase; letter-spacing:.07em;
  color:var(--ink-3); }
.met-figures .v { font-variant-numeric:tabular-nums; font-size:15px; }
.met-flymet { margin:16px 0 0; }
/* Its own width, not the panel's: the meteogram is 1024 px of small type and axis
   labels, and stretched past that it is a blurred picture of a chart. */
.met-flymet img { display:block; width:100%; max-width:1024px; border-radius:3px;
  background:var(--panel); }
.met-flymet figcaption { font-size:11.5px; color:var(--ink-3); margin:5px 0 0; }
.met-flymet a { color:inherit; }
.met-status { color:var(--ink-3); font-size:13px; margin:10px 0 0; }
.met-links { margin:14px 0 0; font-size:12.5px; color:var(--ink-3); }
.met-legend { font-size:11.5px; color:var(--ink-3); margin:6px 0 0; }
"""


def nearest_stations(sites=None, stations=None) -> list[dict | None]:
    """The flymet station nearest each takeoff, one entry per site and in the same order.

    Paired here rather than in the page because neither list moves: takeoffs and airfields
    are both committed data, so this is arithmetic the build can do once instead of 159
    times in every reader's browser — and it is arithmetic a test can check without a
    browser at all.
    """
    sites = site_data.SITES if sites is None else sites
    stations = flymet_data.STATIONS if stations is None else stations
    out: list[dict | None] = []
    for site in sites:
        best, best_m = None, None
        for station in stations:
            metres = distance_m(site["lat"], site["lon"], station["lat"], station["lon"])
            if best_m is None or metres < best_m:
                best, best_m = station, metres
        if best is None or best_m > FLYMET_RANGE_KM * 1000:
            out.append(None)
            continue
        out.append({"slug": best["slug"], "name": best["name"],
                    "km": round(best_m / 1000, 1)})
    return out


def body(uid: str = "meteo") -> str:
    """The view's markup. Everything with a number in it is filled by the script."""
    payload = json.dumps({
        "sites": site_data.SITES,
        "octants": list(site_data.OCTANTS),
        "levels": list(LEVELS),
        "endpoint": ENDPOINT,
        "attribution": site_data.ATTRIBUTION,
        "fetched": site_data.FETCHED,
        # The flymet meteogram for the station nearest each takeoff: a second opinion,
        # from a model and a hand this page does not have. Only two days of it exist.
        "flymet": {
            "near": nearest_stations(),
            "today": flymet_data.TODAY,
            "tomorrow": flymet_data.TOMORROW,
            "index": flymet_data.SOURCE,
        },
    }, separators=(",", ":"))
    return f"""<article class="flight meteo-article" id="{uid}-article">
  <h1>Will it fly?</h1>
  <p class="lede">The day's forecast against {len(site_data.SITES)} Czech takeoffs, sorted
  by how the wind sits on each one. Pick a site for its sounding, its hour-by-hour
  meteogram, and flymet's own meteogram for the airfield nearest it. The numbers are
  fetched when you open this page, so they are as current as the model is — and there are
  none at all without a network.</p>
  <div class="met-head">
    <div class="met-days" id="met-days" role="group" aria-label="Which day"></div>
    <span class="met-status" id="met-status">Fetching the forecast…</span>
  </div>
  <div class="met-grid">
    <div class="met-list" id="met-list"></div>
    <div class="met-panel" id="met-panel">
      <h3 id="met-name">Pick a takeoff</h3>
      <p class="met-sub" id="met-sub">Its sounding and meteogram appear here.</p>
      <div class="met-charts">
        <div>
          <canvas class="met-canvas" id="met-gram" width="720" height="300"></canvas>
          <p class="met-legend">Meteogram — height against the hour. The shading is cloud
            cover on the pressure levels, the line is the convective boundary layer, and
            the dashes are the estimated cloudbase. Barbs are the wind at 900 hPa.</p>
        </div>
        <div>
          <canvas class="met-canvas" id="met-sounding" width="380" height="300"></canvas>
          <p class="met-legend">Sounding at the chosen hour: temperature solid, dew point
            dashed, the dry adiabat from the surface faint. The dotted blue line is the
            estimated cloudbase; a shaded band is a layer the thermals stop at
            (<em>zadržná vrstva</em> — under {CAP_LAPSE:.0f} °C/km, red where the air warms
            with height), read between the model's pressure levels and so no finer than
            they are. Point at it — or drag a finger up it — for the numbers at that
            height.</p>
        </div>
      </div>
      <div class="met-hour">
        <label for="met-hour-input">Hour</label>
        <input type="range" id="met-hour-input" min="6" max="20" step="1" value="14">
        <span id="met-hour-readout" style="min-width:3.5em">14:00</span>
      </div>
      <div class="met-figures" id="met-figures"></div>
      <figure class="met-flymet" id="met-flymet" hidden>
        <img id="met-flymet-img" alt="flymet meteogram" loading="lazy">
        <figcaption id="met-flymet-cap"></figcaption>
      </figure>
      <p class="met-links" id="met-links"></p>
    </div>
  </div>
  <p class="met-links">Forecast from <a href="https://open-meteo.com/"
    rel="noreferrer">Open-Meteo</a> (GFS/ICON), fetched in this page.
    {site_data.ATTRIBUTION}, list taken {site_data.FETCHED}.
    {flymet_data.ATTRIBUTION}, loaded from <a
    href="{flymet_data.SOURCE}" rel="noreferrer">flymet</a> when you open a takeoff —
    {len(flymet_data.STATIONS)} stations, matched to the nearest takeoff here.
    <strong>A forecast is not a decision.</strong> Check the airspace, the NOTAMs and the
    sky before you fly.</p>
  <script type="application/json" class="met-data">{payload}</script>
</article>"""


SCRIPT = r"""
(function () {
  var holder = document.querySelector('.meteo-article');
  if (!holder) return;
  var conf = JSON.parse(holder.querySelector('.met-data').textContent);
  // `probe` is the height the pointer is at in the sounding, in metres, and `probeX`
  // where it is across it — the readout follows the pointer sideways but reads the
  // profile, so what it says never depends on which temperature you happen to be over.
  var state = { day: 0, site: null, hour: 14, surface: null, profile: null,
                probe: null, probeX: 0 };

  var status = document.getElementById('met-status');
  function say(text) { status.textContent = text; }

  // ---- the wind, against the takeoff -------------------------------------------------
  //
  // The one judgement this page makes, and it is made from the site's own record rather
  // than from a rule about hills: ParaglidingEarth stores which octants each takeoff
  // works in, and a site with no record is left unjudged rather than guessed at. Two
  // gates, because they fail differently — a good direction blowing 40 km/h is not a
  // good day, and neither is 8 km/h onto a face that needs 20.
  var STRONG = 28, BRISK = 20;
  function octant(direction) { return Math.round(((direction % 360) + 360) % 360 / 45) % 8; }
  function verdict(site, speed, direction) {
    if (!site.winds || !site.winds.length) return { key: 'none', text: 'no rose' };
    var fit = site.winds[octant(direction)];
    if (speed > STRONG) return { key: 'poor', text: 'too strong' };
    if (!fit) return { key: 'poor', text: 'wrong way' };
    if (fit === 1) return { key: 'fair', text: 'marginal' };
    return { key: speed > BRISK ? 'fair' : 'good', text: speed > BRISK ? 'brisk' : 'flyable' };
  }
  function compass(direction) {
    return conf.octants[octant(direction)];
  }

  // ---- fetching ----------------------------------------------------------------------
  //
  // Two requests, deliberately. Every site in one multi-coordinate call for the ranking —
  // 159 of them cost about half a megabyte and one round trip — and the pressure levels
  // for one site only when that site is opened. Asking for the profile of every takeoff
  // up front would be tens of megabytes to answer a question about one hill.
  function surfaceUrl() {
    var lat = conf.sites.map(function (s) { return s.lat; }).join(',');
    var lon = conf.sites.map(function (s) { return s.lon; }).join(',');
    return conf.endpoint + '?latitude=' + lat + '&longitude=' + lon
      + '&hourly=wind_speed_10m,wind_direction_10m,temperature_2m,cloud_cover,cape'
      + '&forecast_days=4&timezone=Europe%2FPrague&wind_speed_unit=kmh';
  }
  function profileUrl(site) {
    var fields = ['temperature_2m', 'dew_point_2m', 'cloud_cover',
                  'boundary_layer_height', 'wind_speed_10m', 'wind_direction_10m'];
    conf.levels.forEach(function (hpa) {
      fields.push('temperature_' + hpa + 'hPa', 'dew_point_' + hpa + 'hPa',
                  'cloud_cover_' + hpa + 'hPa', 'wind_speed_' + hpa + 'hPa',
                  'wind_direction_' + hpa + 'hPa', 'geopotential_height_' + hpa + 'hPa');
    });
    return conf.endpoint + '?latitude=' + site.lat + '&longitude=' + site.lon
      + '&hourly=' + fields.join(',')
      + '&forecast_days=4&timezone=Europe%2FPrague&wind_speed_unit=kmh';
  }

  function get(url) {
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    });
  }

  // ---- the day strip -----------------------------------------------------------------
  function drawDays() {
    var strip = document.getElementById('met-days');
    strip.innerHTML = '';
    var names = ['today', 'tomorrow'];
    for (var d = 0; d < 4; d++) {
      var when = new Date();
      when.setDate(when.getDate() + d);
      var button = document.createElement('button');
      button.type = 'button';
      button.textContent = names[d] || when.toLocaleDateString(undefined, { weekday: 'short' });
      button.className = d === state.day ? 'is-on' : '';
      button.dataset.day = d;
      strip.appendChild(button);
    }
    strip.onclick = function (event) {
      var button = event.target.closest('button');
      if (!button) return;
      state.day = Number(button.dataset.day);
      drawDays();
      drawList();
      drawSite();
    };
  }

  // The index into an hourly array for a given day and hour. Open-Meteo returns one flat
  // series in the requested timezone, so this is arithmetic and not a search — but it is
  // arithmetic that is wrong by an hour twice a year if the series is assumed to start at
  // midnight, so the first timestamp is read rather than assumed.
  function indexFor(times, day, hour) {
    var start = new Date(times[0].replace(' ', 'T'));
    var wanted = new Date(start);
    wanted.setHours(0, 0, 0, 0);
    wanted.setDate(wanted.getDate() + day);
    wanted.setHours(hour);
    for (var i = 0; i < times.length; i++) {
      var at = new Date(times[i].replace(' ', 'T'));
      if (at.getTime() >= wanted.getTime()) return i;
    }
    return times.length - 1;
  }

  // ---- the list ----------------------------------------------------------------------
  var RANK = { good: 0, fair: 1, none: 2, poor: 3 };
  function drawList() {
    var list = document.getElementById('met-list');
    if (!state.surface) return;
    var rows = conf.sites.map(function (site, i) {
      var series = state.surface[i];
      if (!series || !series.hourly) return null;
      var at = indexFor(series.hourly.time, state.day, state.hour);
      var speed = series.hourly.wind_speed_10m[at];
      var direction = series.hourly.wind_direction_10m[at];
      return {
        site: site, speed: speed, direction: direction,
        cloud: series.hourly.cloud_cover[at],
        temperature: series.hourly.temperature_2m[at],
        verdict: verdict(site, speed, direction), index: i
      };
    }).filter(Boolean);
    rows.sort(function (a, b) {
      var by = RANK[a.verdict.key] - RANK[b.verdict.key];
      return by || a.site.name.localeCompare(b.site.name);
    });

    list.innerHTML = '';
    rows.forEach(function (row) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'met-site' + (state.site === row.index ? ' is-on' : '');
      button.dataset.index = row.index;
      button.innerHTML =
        '<span class="met-site-name"></span>'
        + '<span class="met-verdict met-' + row.verdict.key + '"></span>'
        + '<span class="met-site-note"></span>';
      button.querySelector('.met-site-name').textContent = row.site.name;
      button.querySelector('.met-verdict').textContent = row.verdict.text;
      button.querySelector('.met-site-note').textContent =
        Math.round(row.speed) + ' km/h from ' + compass(row.direction)
        + ' · ' + row.site.alt + ' m · ' + Math.round(row.cloud) + '% cloud';
      list.appendChild(button);
    });
    list.onclick = function (event) {
      var button = event.target.closest('.met-site');
      if (!button) return;
      state.site = Number(button.dataset.index);
      state.profile = null;
      drawList();
      loadProfile();
    };
  }

  // ---- charts ------------------------------------------------------------------------
  function fit(canvas) {
    // Backing store to CSS box, capped at 2x, so the charts are sharp on a phone without
    // asking a phone to fill four times the pixels.
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    var box = canvas.getBoundingClientRect();
    if (!box.width) return null;
    canvas.width = Math.round(box.width * ratio);
    canvas.height = Math.round(box.height * ratio);
    var ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { ctx: ctx, w: box.width, h: box.height };
  }
  function ink(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
      || '#888';
  }

  function levelSeries(hourly, prefix) {
    return conf.levels.map(function (hpa) { return hourly[prefix + '_' + hpa + 'hPa']; });
  }

  // Cloudbase from the surface spread, the same 125 m per degree the report uses. It is a
  // rule of thumb and is labelled as one; the model's own cloud cover is drawn beside it
  // so the two can disagree in front of the reader.
  function cloudbase(temperature, dewPoint, ground) {
    if (temperature == null || dewPoint == null) return null;
    return ground + Math.max(temperature - dewPoint, 0) * 125;
  }

  // ---- the layer that stops the day ---------------------------------------------------
  //
  // The *zadržná vrstva*: a layer stable enough that a thermal arriving at it stops. A
  // parcel rising dry cools at 9.8 °C per km, so it keeps going while the air around it
  // cools faster than that and is stopped where the air cools slowly, not at all
  // (isothermal), or warms with height (an inversion). Two degrees a kilometre is drawn
  // as the line between "still climbing" and "this is the lid": it is well below the 6-9
  // of a working day and above the noise of a level pair 250 m apart.
  //
  // It is read between adjacent pressure levels and no finer, because that is the
  // resolution the model publishes — 220 m near the ground and 1 000 m at 4 km. A shallow
  // morning inversion 100 m thick sits inside one of those gaps and cannot be seen here at
  // all, which is why the caption says what the shading is read from.
  var CAP_LAPSE = 2.0;    // °C per km

  // The sounding's frame, shared by the chart and by the pointer that reads heights off
  // it. Two copies of these three numbers is a readout that quietly points at the wrong
  // height the first time the chart is retuned.
  var SOUND_TOP = 10, SOUND_BOTTOM = 24, SOUND_CEILING = 4000;

  function cappingLayers(hourly, at, ground, ceiling) {
    var heights = levelSeries(hourly, 'geopotential_height');
    var temps = levelSeries(hourly, 'temperature');
    var out = [];
    for (var l = 0; l + 1 < conf.levels.length; l++) {
      if (!heights[l] || !heights[l + 1] || !temps[l] || !temps[l + 1]) continue;
      var base = heights[l][at], top = heights[l + 1][at];
      var below = temps[l][at], above = temps[l + 1][at];
      if (base == null || top == null || below == null || above == null) continue;
      if (top <= ground || base >= ceiling || top <= base) continue;
      // Positive is the ordinary case, air cooling with height; negative is an inversion.
      var lapse = (below - above) / (top - base) * 1000;
      if (lapse >= CAP_LAPSE) continue;
      var band = { base: Math.max(base, ground), top: Math.min(top, ceiling),
                   lapse: lapse, inversion: lapse < 0 };
      // Two level pairs that meet are one layer, and drawing them as two puts a seam
      // through the middle of it and offers to label it twice.
      var last = out[out.length - 1];
      if (last && Math.abs(last.top - band.base) < 1) {
        last.top = band.top;
        last.lapse = Math.min(last.lapse, band.lapse);
        last.inversion = last.inversion || band.inversion;
      } else {
        out.push(band);
      }
    }
    return out;
  }

  // The profile at any height, for the readout: linear between the levels either side,
  // which is the same line the chart draws, and the 2 m values below the lowest level.
  // Wind is interpolated as components — averaging 350 and 010 as numbers gives 180,
  // which is the one wrong answer a reader would act on.
  function sampleProfile(hourly, at, metres, ground) {
    var heights = levelSeries(hourly, 'geopotential_height');
    var temps = levelSeries(hourly, 'temperature');
    var dews = levelSeries(hourly, 'dew_point');
    var speeds = levelSeries(hourly, 'wind_speed');
    var dirs = levelSeries(hourly, 'wind_direction');
    var have = [];
    for (var l = 0; l < conf.levels.length; l++) {
      var z = heights[l] ? heights[l][at] : null;
      if (z == null) continue;
      have.push({ z: z, t: temps[l] ? temps[l][at] : null,
                  td: dews[l] ? dews[l][at] : null,
                  speed: speeds[l] ? speeds[l][at] : null,
                  dir: dirs[l] ? dirs[l][at] : null });
    }
    var surface = { z: ground, t: hourly.temperature_2m[at], td: hourly.dew_point_2m[at],
                    speed: hourly.wind_speed_10m[at], dir: hourly.wind_direction_10m[at] };
    have = have.filter(function (level) { return level.z > ground; });
    have.unshift(surface);
    if (metres <= have[0].z) return have[0];
    for (var i = 1; i < have.length; i++) {
      if (metres > have[i].z) continue;
      var lo = have[i - 1], hi = have[i];
      var f = (metres - lo.z) / (hi.z - lo.z);
      var mix = function (a, b) {
        return a == null || b == null ? null : a + (b - a) * f;
      };
      var wind = null;
      if (lo.speed != null && hi.speed != null && lo.dir != null && hi.dir != null) {
        var u = mix(-lo.speed * Math.sin(lo.dir * Math.PI / 180),
                    -hi.speed * Math.sin(hi.dir * Math.PI / 180));
        var v = mix(-lo.speed * Math.cos(lo.dir * Math.PI / 180),
                    -hi.speed * Math.cos(hi.dir * Math.PI / 180));
        wind = { speed: Math.hypot(u, v),
                 dir: (Math.atan2(-u, -v) * 180 / Math.PI + 360) % 360 };
      }
      return { z: metres, t: mix(lo.t, hi.t), td: mix(lo.td, hi.td),
               speed: wind && wind.speed, dir: wind && wind.dir };
    }
    return have[have.length - 1];
  }

  function drawMeteogram() {
    var canvas = document.getElementById('met-gram');
    var frame = fit(canvas);
    if (!frame || !state.profile) return;
    var ctx = frame.ctx, W = frame.w, H = frame.h;
    var hourly = state.profile.hourly;
    var ground = state.profile.elevation;
    var left = 42, right = 8, top = 10, bottom = 26;
    var top_m = 4000;
    function x(hour) { return left + (hour - 5) / 16 * (W - left - right); }
    function y(metres) { return top + (1 - metres / top_m) * (H - top - bottom); }

    ctx.clearRect(0, 0, W, H);
    var heights = levelSeries(hourly, 'geopotential_height');
    var clouds = levelSeries(hourly, 'cloud_cover');

    // Cloud, as a column per hour per level. Grey rather than white: this is a light and
    // a dark theme, and white cloud on a white panel is a blank chart.
    for (var hour = 5; hour <= 21; hour++) {
      var at = indexFor(hourly.time, state.day, hour);
      for (var l = 0; l < conf.levels.length; l++) {
        var cover = clouds[l] ? clouds[l][at] : null;
        var height = heights[l] ? heights[l][at] : null;
        if (cover == null || height == null || cover < 5) continue;
        var band = (l === 0 ? 300 : Math.abs(heights[l][at] - heights[l - 1][at])) || 300;
        ctx.fillStyle = 'rgba(128,132,140,' + Math.min(cover / 100, 1) * 0.75 + ')';
        ctx.fillRect(x(hour) - (W - left - right) / 34, y(height + band / 2),
                     (W - left - right) / 17, Math.abs(y(height - band / 2) - y(height + band / 2)));
      }
    }

    // The ground, the boundary layer and the cloudbase.
    ctx.fillStyle = ink('--panel-2');
    ctx.fillRect(left, y(ground), W - left - right, H - bottom - y(ground));
    function line(values, dashed, colour) {
      ctx.save();
      ctx.beginPath();
      ctx.setLineDash(dashed ? [5, 4] : []);
      ctx.strokeStyle = colour;
      ctx.lineWidth = 1.8;
      var started = false;
      for (var h = 5; h <= 21; h++) {
        var value = values(indexFor(hourly.time, state.day, h));
        if (value == null) continue;
        if (!started) { ctx.moveTo(x(h), y(value)); started = true; }
        else ctx.lineTo(x(h), y(value));
      }
      ctx.stroke();
      ctx.restore();
    }
    line(function (at) {
      return hourly.boundary_layer_height[at] == null ? null
        : ground + hourly.boundary_layer_height[at];
    }, false, '#eb6834');
    line(function (at) {
      return cloudbase(hourly.temperature_2m[at], hourly.dew_point_2m[at], ground);
    }, true, '#2f6fb3');

    // Axes last, over everything.
    ctx.strokeStyle = ink('--rule');
    ctx.fillStyle = ink('--ink-3');
    ctx.font = '10px ui-sans-serif, sans-serif';
    ctx.lineWidth = 1;
    for (var m = 0; m <= top_m; m += 1000) {
      ctx.beginPath(); ctx.moveTo(left, y(m)); ctx.lineTo(W - right, y(m)); ctx.stroke();
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText(m + ' m', left - 5, y(m));
    }
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (var t = 6; t <= 20; t += 2) ctx.fillText(t + ':00', x(t), H - bottom + 5);
  }

  function drawSounding() {
    var canvas = document.getElementById('met-sounding');
    var frame = fit(canvas);
    if (!frame || !state.profile) return;
    var ctx = frame.ctx, W = frame.w, H = frame.h;
    var hourly = state.profile.hourly;
    var at = indexFor(hourly.time, state.day, state.hour);
    var ground = state.profile.elevation;
    var left = 34, right = 10, top = SOUND_TOP, bottom = SOUND_BOTTOM;
    var top_m = SOUND_CEILING, minT = -20, maxT = 35;
    function x(celsius) { return left + (celsius - minT) / (maxT - minT) * (W - left - right); }
    function y(metres) { return top + (1 - metres / top_m) * (H - top - bottom); }

    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = ink('--rule');
    ctx.fillStyle = ink('--ink-3');
    ctx.font = '10px ui-sans-serif, sans-serif';
    ctx.lineWidth = 1;
    for (var m = 0; m <= top_m; m += 1000) {
      ctx.beginPath(); ctx.moveTo(left, y(m)); ctx.lineTo(W - right, y(m)); ctx.stroke();
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText(m / 1000 + 'k', left - 4, y(m));
    }
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (var c = -20; c <= 30; c += 10) {
      ctx.beginPath(); ctx.moveTo(x(c), top); ctx.lineTo(x(c), H - bottom); ctx.stroke();
      ctx.fillText(c + '°', x(c), H - bottom + 4);
    }

    // The ground, so every height on this chart has something to be measured from. The
    // meteogram beside it has had one all along and the sounding read as if the site were
    // at sea level.
    ctx.fillStyle = ink('--panel-2');
    ctx.fillRect(left, y(ground), W - left - right, H - bottom - y(ground));

    // The layer that stops the day, under the traces it is read from.
    var caps = cappingLayers(hourly, at, ground, top_m);
    caps.forEach(function (band, index) {
      var height = Math.max(y(band.base) - y(band.top), 2);
      ctx.save();
      ctx.fillStyle = band.inversion ? 'rgba(178,58,58,0.20)' : 'rgba(140,140,150,0.22)';
      ctx.fillRect(left, y(band.top), W - left - right, height);
      ctx.strokeStyle = band.inversion ? 'rgba(178,58,58,0.55)' : 'rgba(140,140,150,0.5)';
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(left, y(band.base)); ctx.lineTo(W - right, y(band.base));
      ctx.stroke();
      // Only the lowest one is named. It is the one a thermal meets first, and stacking
      // three labels down a 300 px chart says less than one.
      if (index === 0) {
        ctx.setLineDash([]);
        ctx.fillStyle = ink('--ink-2');
        ctx.textAlign = 'left';
        ctx.textBaseline = height > 15 ? 'middle' : 'bottom';
        ctx.fillText(band.inversion ? 'inversion' : 'capping layer',
                     left + 4, height > 15 ? y(band.top) + height / 2 : y(band.top) - 2);
      }
      ctx.restore();
    });

    // The cloudbase, drawn where the figures below already print it.
    var base = cloudbase(hourly.temperature_2m[at], hourly.dew_point_2m[at], ground);
    if (base != null && base > ground && base < top_m) {
      ctx.save();
      ctx.strokeStyle = '#2f6fb3';
      ctx.setLineDash([2, 3]);
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(left, y(base)); ctx.lineTo(W - right, y(base));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#2f6fb3';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'bottom';
      ctx.fillText('cloudbase', W - right - 3, y(base) - 2);
      ctx.restore();
    }

    // The dry adiabat from the surface temperature: where it meets the profile is the
    // trigger, and how far the two run apart is the day's strength. Drawn faint because
    // it is a construction, not a measurement.
    var surface = hourly.temperature_2m[at];
    if (surface != null) {
      ctx.save();
      ctx.strokeStyle = '#eb6834'; ctx.globalAlpha = 0.45; ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x(surface), y(ground));
      ctx.lineTo(x(surface - 9.8 * (top_m - ground) / 1000), y(top_m));
      ctx.stroke();
      ctx.restore();
    }

    var heights = levelSeries(hourly, 'geopotential_height');
    function trace(values, dashed, colour) {
      ctx.save();
      ctx.beginPath();
      ctx.setLineDash(dashed ? [4, 3] : []);
      ctx.strokeStyle = colour; ctx.lineWidth = 2;
      var started = false;
      for (var l = 0; l < conf.levels.length; l++) {
        var height = heights[l] ? heights[l][at] : null;
        var value = values[l] ? values[l][at] : null;
        if (height == null || value == null || height < ground || height > top_m) continue;
        if (!started) { ctx.moveTo(x(value), y(height)); started = true; }
        else ctx.lineTo(x(value), y(height));
      }
      ctx.stroke();
      ctx.restore();
    }
    trace(levelSeries(hourly, 'temperature'), false, '#c2410c');
    trace(levelSeries(hourly, 'dew_point'), true, '#2f6fb3');

    // ---- what it says at one height --------------------------------------------------
    //
    // A sounding is two lines against a scale, and reading a number off it by eye is
    // three conversions a reader should not have to do. So the pointer names the height
    // it is at and everything the model says there — including the wind, which the chart
    // does not draw at all and which decides where the day is flyable.
    if (state.probe == null) return;
    var metres = Math.min(Math.max(state.probe, ground), top_m);
    var here = sampleProfile(hourly, at, metres, ground);
    ctx.save();
    ctx.strokeStyle = ink('--ink-3');
    ctx.setLineDash([1, 3]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(left, y(metres)); ctx.lineTo(W - right, y(metres));
    ctx.stroke();
    ctx.setLineDash([]);
    [[here.t, '#c2410c'], [here.td, '#2f6fb3']].forEach(function (pair) {
      if (pair[0] == null) return;
      ctx.fillStyle = pair[1];
      ctx.beginPath();
      ctx.arc(x(pair[0]), y(metres), 3, 0, Math.PI * 2);
      ctx.fill();
    });

    var lines = [Math.round(metres) + ' m · ' + Math.round(metres - ground) + ' m agl'];
    if (here.t != null) {
      lines.push(here.t.toFixed(1) + ' °C'
        + (here.td == null ? ''
           : ' · dew ' + here.td.toFixed(1) + ' · spread '
             + (here.t - here.td).toFixed(1)));
    }
    if (here.speed != null && here.dir != null) {
      lines.push(Math.round(here.speed) + ' km/h from ' + compass(here.dir)
                 + ' (' + Math.round(here.dir) + '°)');
    }
    ctx.font = '11px ui-sans-serif, sans-serif';
    var width = 0;
    lines.forEach(function (line) { width = Math.max(width, ctx.measureText(line).width); });
    var boxW = width + 12, boxH = lines.length * 13 + 7;
    // Above the pointer where there is room and below it near the top, and always inside
    // the chart: a readout that hangs off the edge is a readout with a number cut in half.
    var boxY = y(metres) - boxH - 8;
    if (boxY < top) boxY = y(metres) + 8;
    var boxX = Math.min(Math.max(left + 2, state.probeX - boxW / 2), W - right - boxW);
    ctx.globalAlpha = 0.93;
    ctx.fillStyle = ink('--paper');
    ctx.fillRect(boxX, boxY, boxW, boxH);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = ink('--rule');
    ctx.strokeRect(boxX + 0.5, boxY + 0.5, boxW, boxH);
    ctx.fillStyle = ink('--ink');
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    lines.forEach(function (line, i) {
      ctx.fillText(line, boxX + 6, boxY + 5 + i * 13);
    });
    ctx.restore();
  }

  function drawFigures() {
    var box = document.getElementById('met-figures');
    box.innerHTML = '';
    if (!state.profile) return;
    var hourly = state.profile.hourly;
    var at = indexFor(hourly.time, state.day, state.hour);
    var ground = state.profile.elevation;
    var base = cloudbase(hourly.temperature_2m[at], hourly.dew_point_2m[at], ground);
    var blh = hourly.boundary_layer_height[at];
    var pairs = [
      ['temperature', Math.round(hourly.temperature_2m[at]) + ' °C'],
      ['dew point', Math.round(hourly.dew_point_2m[at]) + ' °C'],
      ['wind', Math.round(hourly.wind_speed_10m[at]) + ' km/h from '
        + compass(hourly.wind_direction_10m[at])],
      ['thermal top', blh == null ? '—' : Math.round(ground + blh) + ' m'],
      ['cloudbase', base == null ? '—' : Math.round(base) + ' m'],
      ['ground', Math.round(ground) + ' m']
    ];
    pairs.forEach(function (pair) {
      var cell = document.createElement('div');
      cell.innerHTML = '<span class="k"></span><span class="v"></span>';
      cell.querySelector('.k').textContent = pair[0];
      cell.querySelector('.v').textContent = pair[1];
      box.appendChild(cell);
    });
  }

  // ---- the flymet meteogram ------------------------------------------------------
  //
  // The one thing on this page that is neither drawn here nor computed from Open-Meteo: a
  // picture from flymet, in the form Czech glider pilots already read. It is a second
  // opinion from a different model and a different hand, and where it disagrees with the
  // charts above that disagreement is worth seeing.
  //
  // It is *linked*, not copied: the reader's browser fetches it from flymet, and the
  // caption names flymet and links back to its own page. Two days exist — today and
  // tomorrow — so the other two days of the strip show nothing rather than yesterday's
  // picture under today's heading.
  function drawFlymet() {
    var figure = document.getElementById('met-flymet');
    var image = document.getElementById('met-flymet-img');
    var caption = document.getElementById('met-flymet-cap');
    var near = (conf.flymet.near || [])[state.site];
    var template = state.day === 0 ? conf.flymet.today
      : (state.day === 1 ? conf.flymet.tomorrow : null);
    if (!near || !template) {
      figure.hidden = true;
      return;
    }
    figure.hidden = false;
    // Stamped with the hour. flymet sends no cache lifetime, so a browser is free to
    // guess one from the file's age — and today's meteogram is regenerated through the
    // day, which makes a guessed cache an old picture under a current heading. The stamp
    // is the hour and not the minute, so it is still one fetch an hour and not one a view.
    var stamp = new Date();
    var hour = stamp.getFullYear() + ('0' + (stamp.getMonth() + 1)).slice(-2)
      + ('0' + stamp.getDate()).slice(-2) + ('0' + stamp.getHours()).slice(-2);
    var url = template.replace('{slug}', encodeURIComponent(near.slug)) + '?h=' + hour;
    image.hidden = false;
    // Only when it actually changed: the hour slider redraws this panel on every step,
    // and reassigning the same src makes the picture blink on each one.
    if (image.getAttribute('src') !== url) {
      image.src = url;
      image.alt = 'flymet meteogram for ' + near.name;
    }
    image.onerror = function () {
      image.hidden = true;
      caption.textContent = 'flymet has no meteogram for ' + near.name + ' just now.';
    };
    caption.innerHTML = '';
    var link = document.createElement('a');
    link.href = conf.flymet.index;
    link.rel = 'noreferrer';
    link.textContent = 'flymet';
    caption.appendChild(link);
    caption.appendChild(document.createTextNode(
      ' — ' + near.name + ', ' + near.km + ' km from this takeoff, for '
      + (state.day === 0 ? 'today' : 'tomorrow')
      + '. Cloud, rain, stability with the convective cloud height, and wind by height.'));
  }

  function drawSite() {
    if (state.site == null) return;
    var site = conf.sites[state.site];
    document.getElementById('met-name').textContent = site.name;
    var good = (site.winds || []).length
      ? conf.octants.filter(function (point, i) { return site.winds[i] === 2; })
      : null;
    var rose = good === null
      ? 'no wind directions recorded, so this page will not judge it'
      : (good.length ? 'works in ' + good.join(' ') : 'only marginal directions recorded');
    document.getElementById('met-sub').textContent =
      site.alt + ' m · ' + rose;
    var links = document.getElementById('met-links');
    links.innerHTML = '';
    var a = document.createElement('a');
    a.href = 'https://www.paraglidingearth.com/index.php?site=' + site.id;
    a.rel = 'noreferrer';
    a.textContent = 'This takeoff on ParaglidingEarth';
    links.appendChild(a);
    drawMeteogram();
    drawSounding();
    drawFigures();
    drawFlymet();
  }

  function loadProfile() {
    var site = conf.sites[state.site];
    say('Fetching the sounding for ' + site.name + '…');
    get(profileUrl(site)).then(function (answer) {
      state.profile = answer;
      say('');
      drawSite();
    }).catch(function (error) {
      say('No sounding: ' + error.message);
    });
  }

  // Hover on a mouse, drag-to-read on a touchscreen. The same split the airspace map
  // makes, and for the same reason: a touchscreen's pointerout means the finger lifted,
  // not that the reader stopped wanting the number.
  (function () {
    var canvas = document.getElementById('met-sounding');
    function read(event) {
      if (!state.profile) return;
      var box = canvas.getBoundingClientRect();
      var y = event.clientY - box.top;
      var plot = box.height - SOUND_TOP - SOUND_BOTTOM;
      state.probe = (1 - (y - SOUND_TOP) / plot) * SOUND_CEILING;
      state.probeX = event.clientX - box.left;
      drawSounding();
    }
    function clear() { state.probe = null; drawSounding(); }
    canvas.addEventListener('pointermove', function (event) {
      if (event.pointerType === 'touch' && !event.buttons) return;
      read(event);
    });
    canvas.addEventListener('pointerdown', function (event) {
      if (event.pointerType !== 'touch') return;
      // Held rather than tapped: a finger dragged up the chart reads it off, and lifting
      // it puts the readout away.
      canvas.setPointerCapture(event.pointerId);
      read(event);
    });
    canvas.addEventListener('pointerup', clear);
    canvas.addEventListener('pointercancel', clear);
    canvas.addEventListener('pointerleave', function (event) {
      if (event.pointerType !== 'touch') clear();
    });
  })();

  var hourInput = document.getElementById('met-hour-input');
  hourInput.addEventListener('input', function () {
    state.hour = Number(hourInput.value);
    document.getElementById('met-hour-readout').textContent = state.hour + ':00';
    drawList();
    drawSite();
  });
  window.addEventListener('resize', function () { drawSite(); });

  // Exposed for tests, and only what a test cannot reach any other way: the two rules
  // that read a sounding, the state the pointer writes into, and a redraw. Everything
  // else about this page is observable in the DOM. The alternative was a second copy of
  // the capping rule in Python, which is exactly the drift `quicklook.py` is a warning
  // about.
  window.__meteo = {
    state: state,
    cappingLayers: cappingLayers,
    sampleProfile: sampleProfile,
    cloudbase: cloudbase,
    draw: drawSite,
    at: function () { return indexFor(state.profile.hourly.time, state.day, state.hour); }
  };

  drawDays();
  get(surfaceUrl()).then(function (answer) {
    state.surface = Array.isArray(answer) ? answer : [answer];
    say('');
    drawList();
    // Open the best site rather than an empty panel: the page's answer to "is it worth
    // going" is a sounding, and making the reader click to see one hides the point.
    var first = document.querySelector('.met-site');
    if (first && state.site === null) {
      state.site = Number(first.dataset.index);
      drawList();
      loadProfile();
    }
  }).catch(function (error) {
    say('The forecast could not be fetched (' + error.message + '). '
        + 'This page has no numbers of its own — it needs a network.');
  });
})();
"""

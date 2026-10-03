"""Client-side quick look at a track the reader supplies.

A published report is a static file: it cannot call the analysis in Python, and the
content-security policy means it cannot call anything over the network either. So the
only way to let someone drop their own flight onto the page is to do the work in the
browser, and this is a deliberately reduced version of it:

* reads IGC, KML and KMZ (the ZIP is inflated with ``DecompressionStream``)
* derives climb, progress and the phase split with the same thresholds *and the same
  condensing* as :mod:`tracklog_viewer.analysis` — see ``mark``, where they once differed
* draws a side view and a top view, lists the climbs and the glides, and links all of
  them to the 3D map through one cursor (``linkCharts``)

What it does not do — because the inputs simply are not there — is the basemap, the
weather profile, or XC optimisation. Those need the CLI. The panel says so rather than
quietly presenting a thinner analysis as the whole thing. Terrain is the exception it
used to share: the DEM is fetched here now, wherever the page is allowed to reach a
host, and falls back to a flat plane where it is not.
"""

import json

from . import analysis, debrief, flight, meteo, render_map, view3d
from .render_map import RAMP_RGB


def constants() -> dict:
    """Every number this page shares with the Python analysis, in one payload.

    The documented gap was that ``quicklook.py`` held its own copy of each threshold and
    the two drifted — on *shape* rather than on a value the first time, which is worse,
    because a number that differs by ten percent looks like rounding and a rule that
    differs looks like a bug in the file the reader uploaded. ``debrief.THRESHOLDS`` was
    already serialised beside the debrief; this is the other half, and it is emitted from
    the drop panel rather than from a flight, so an upload into a report with no bundled
    flights still gets it.

    Names are camelCase because the only consumer is JavaScript. Anything added here has
    to be a rule the page actually applies — a constant nobody reads is a second place
    for the truth to live.
    """
    return {
        "window": flight.WINDOW,
        "glideProgress": analysis.GLIDE_PROGRESS,
        "thermalSlowKmh": analysis.THERMAL_SLOW_KMH,
        "minThermalSeconds": analysis.MIN_THERMAL_SECONDS,
        "minThermalGain": analysis.MIN_THERMAL_GAIN,
        "minGlideSeconds": analysis.MIN_GLIDE_SECONDS,
        "condenseThermal": analysis.CONDENSE_THERMAL,
        "condenseGlide": analysis.CONDENSE_GLIDE,
        "reversalHysteresis": analysis.REVERSAL_HYSTERESIS,
        "turnResolutionLimit": analysis.TURN_RESOLUTION_LIMIT,
        # The levels `meteo.py` asks Open-Meteo for, so a profile fetched in the page is
        # the same shape as one baked in at build time and the two can be read against
        # each other.
        "pressureLevels": list(meteo.PRESSURE_LEVELS),
        "thresholds": debrief.THRESHOLDS,
    }


def panel() -> str:
    """The drop panel, plus a template for a result article.

    Two pieces on purpose. The drop panel is a fixed article the `+ your track` tab shows.
    A loaded flight becomes a *clone* of the template with its own uid, so several tracks
    can be open at once — each with its own tab, charts and 3D view. Everything inside the
    template is addressed by class, never by id: ids would collide the moment there were
    two flights.
    """
    ramp = "".join(
        f'<i style="background: rgb({r},{g},{b})"></i>' for _, (r, g, b) in RAMP_RGB
    )
    rules = json.dumps(constants(), separators=(",", ":"))
    return f"""
  <script type="application/json" id="ql-constants">{rules}</script>
  <article class="flight" data-flight-report="own" id="quicklook" hidden>
    <header class="masthead">
      <div>
        <p class="eyebrow">tracklog viewer</p>
        <h1>Your own tracks</h1>
      </div>
    </header>
    <div class="section-head" style="margin-top:26px">
      <h2>Read in this page</h2>
      <p>Nothing is uploaded: the file is parsed and analysed here. Each track you add gets
         its own tab, and the &times; on a tab removes that flight again.</p>
    </div>
    <div class="panel ql-drop" id="ql-drop">
      <input type="file" id="ql-file" accept=".igc,.IGC,.kml,.kmz" multiple hidden>
      <button type="button" class="ql-button" id="ql-pick">Choose track files</button>
      <span class="ql-hint"><strong>.igc preferred</strong> &middot; or drag them
        here &middot; .kml and .kmz also read</span>
      <p class="ql-note-inline">A KMZ downloaded from a scoring site is usually reduced to
        500 points — every few minutes on a long flight. Distances, height gained and turn
        counts are all measured along the track, so they come out low, and turns cannot be
        counted at all. The IGC your instrument recorded is the file to use.</p>
      <p class="ql-status" id="ql-status" role="status" aria-live="polite"></p>
    </div>
  </article>
  <template id="ql-template">
    <article class="flight" data-flight-report="">
      <header class="masthead">
        <div>
          <p class="eyebrow">tracklog viewer</p>
          <h1 class="ql-heading">Your own track</h1>
        </div>
        <div class="identity"><div><span class="key">source</span>
          <span class="val ql-source">—</span></div></div>
      </header>
      <p class="ql-coarse" hidden></p>
      <div class="stats ql-stats"></div>
      <div class="ql-3d">
        <div class="section-head" style="margin-top:30px">
          <h2>The flight in three dimensions</h2>
          <p>Drag to pan, right-drag or ctrl-drag to rotate and tilt, scroll to zoom. The
             terrain and the imagery are fetched when this page opens — served from a host
             they arrive; inside a published artifact, which may reach no host at all, the
             ground falls back to a flat plane and the caption says so. The altitudes are
             your own either way, at true vertical scale.</p>
        </div>
        <div class="renderer-host">
        {render_map.switch_html()}
        {view3d.panel(dict(tiles=view3d.TILE_SOURCES), "own")}
        </div>
        <p class="caption ql-3d-note"></p>
      </div>
      <div class="panel hero ql-result">
        <p class="chart-title">Side view — altitude against distance flown</p>
        <canvas class="ql-canvas ql-side" width="1080" height="330"></canvas>
        <div class="panel-divide"></div>
        <p class="chart-title">Top view — the course line</p>
        <canvas class="ql-canvas ql-plan" width="1080" height="420"></canvas>
        <div class="table-scroll">
          <table class="ql-table">
            <thead><tr><th>#</th><th>start</th><th>time</th><th>gain m</th><th>avg m/s</th>
              <th>best m/s</th><th>turns</th><th>m/turn</th><th>wind</th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
      <ul class="legend">
        <li class="ramp">{ramp}</li>
        <li>trace colour: sink &minus;4 m/s → climb +4 m/s</li>
      </ul>
      <div class="section-head" style="margin-top:30px"><h2>Glides</h2></div>
      <div class="panel" style="padding:14px 16px 4px">
        <div class="table-scroll">
          <table class="ql-glides">
            <thead><tr><th>#</th><th>start</th><th>time</th><th>km</th><th>height m</th>
              <th>glide</th><th>km/h</th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
      <div class="section-head" style="margin-top:30px"><h2>The air that day</h2></div>
      <div class="stats ql-meteo-stats"></div>
      <p class="caption ql-note"></p>
    </article>
  </template>"""


STYLE = """
.ql-drop { padding: 20px 22px; display: flex; align-items: center; gap: 14px;
  flex-wrap: wrap; border-style: dashed; }
.ql-drop.is-over { border-color: var(--climb); background: var(--panel-2); }
.ql-button {
  font: inherit;
  font-size: 12.5px;
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  padding: 8px 16px;
  border: 1px solid var(--ink);
  border-radius: 2px;
  background: var(--ink);
  color: var(--paper);
  cursor: pointer;
}
.ql-button:hover { background: var(--climb); border-color: var(--climb); }
.ql-hint { color: var(--ink-3); font-size: 12.5px; }
.ql-note-inline { flex-basis: 100%; margin: 2px 0 0; font-size: 12.5px; color: var(--ink-3);
  max-width: 74ch; }
/* Sampling warning on a flight read from a reduced file: the numbers are all low, and
   saying so beside them is the only honest way to show them at all. */
.ql-coarse { margin: 0 6px 12px; padding: 9px 12px; border-left: 2px solid var(--climb);
  background: var(--panel-2); font-size: 12.5px; color: var(--ink-2); }
.ql-status { margin: 0; font-size: 12.5px; color: var(--ink-2); flex-basis: 100%; }
.ql-status.is-error { color: var(--climb); }
.ql-status.is-busy::before {
  content: ""; display: inline-block; width: 11px; height: 11px; margin: 0 7px -1px 0;
  border: 2px solid var(--rule, currentColor); border-top-color: var(--ink, currentColor);
  border-radius: 50%; animation: ql-spin .8s linear infinite;
}
@keyframes ql-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .ql-status.is-busy::before { animation-duration: 2.4s; } }
canvas.ql-canvas { display: block; width: 100%; height: auto; }
.ql-stats { margin: 6px 6px 12px; }
.ql-result .table-scroll { margin: 10px 6px 0; }
"""


SCRIPT = r"""
(function () {
  var drop = document.getElementById('ql-drop');
  if (!drop) return;
  var input = document.getElementById('ql-file');
  var status = document.getElementById('ql-status');
  var template = document.getElementById('ql-template');
  // Every uploaded flight is a clone of the template with its own uid, so the lookups
  // below are all scoped to one article. Nothing here may use an id.
  var loaded = 0;

  // Every threshold this page applies, read from the payload `quicklook.constants()`
  // writes rather than typed again here. Not defensive: the panel and the JSON are
  // emitted by the same function, so if this element is missing the page is broken and
  // failing at load says so louder than analysing a flight by different rules would.
  // `TH` is `debrief.THRESHOLDS`, the same dict the built report's debrief carries.
  var RULES = JSON.parse(document.getElementById('ql-constants').textContent);
  var TH = RULES.thresholds;

  var RAMP = [[-4, [23,80,143]], [-2, [42,120,214]], [-0.7, [143,182,230]],
              [0.7, [169,164,154]], [2, [240,160,122]], [4, [235,104,52]],
              [Infinity, [200,67,26]]];
  function climbColour(v) {
    for (var i = 0; i < RAMP.length; i++) if (v < RAMP[i][0]) return RAMP[i][1];
    return RAMP[RAMP.length - 1][1];
  }
  function rgb(c) { return 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')'; }

  var R = 6371000;
  function distance(la1, lo1, la2, lo2) {
    var p = Math.PI / 180;
    var dLat = (la2 - la1) * p, dLon = (lo2 - lo1) * p;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(la1 * p) * Math.cos(la2 * p) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  // ---- readers ---------------------------------------------------------------
  var B_RE = /^B(\d{2})(\d{2})(\d{2})(\d{2})(\d{5})([NS])(\d{3})(\d{5})([EW])([AV])(-\d{4}|\d{5})(-\d{4}|\d{5})/;

  // Both syntaxes in the wild: HFDTE290523 and HFDTEDATE:280918,01.
  var DATE_RE = /^HFDTE(?:DATE:)?(\d{2})(\d{2})(\d{2})/;
  // SkyDrop and friends: HFTZNTIMEZONE:+2.0. B records are UTC, and a report that says
  // a climb started at 15:43 when the pilot remembers 17:43 is describing someone
  // else's flight. The Python side resolves this out of the header too (`igc.py`), and
  // an upload showing a different clock than a built report of the same file is the
  // kind of disagreement that makes a reader distrust both.
  var TZ_RE = /^HFTZN(?:TIMEZONE:)?\s*([-+]?\d+(?:\.\d+)?)/;
  // XCTrack writes no HFTZN and instead hides an IANA zone name inside a base64 JSON
  // blob split across dozens of L records. `Intl` speaks IANA natively, so the browser
  // can use it directly — and a named zone beats a fixed offset, because it knows about
  // the day's daylight saving where a number does not.
  var DEVICE_RE = /^L(?:XCT)?DEVICE\s?(.*)$/;

  // The IANA zone out of XCTrack's device blob, or null. Every step here can fail on a
  // file that merely looks like XCTrack's — the chunking drops base64 padding, older
  // versions carry no `os.timezone` at all (three of six sample files), and `Intl`
  // rejects a name it does not know — so each failure returns null and the clock falls
  // back rather than throwing on load.
  function deviceZone(chunks) {
    if (!chunks.length) return null;
    try {
      // The chunking drops padding, and `atob` — unlike Python's `b64decode` with
      // `validate=False` — throws on the wrong *amount* of it rather than ignoring the
      // excess, which is what a blind `+ '=='` gives on a payload that was already a
      // multiple of four. So it is rebuilt exactly: strip what survived, pad to four.
      // Getting this wrong is silent, because the catch below turns it into "no
      // timezone" and the table quietly goes on printing UTC.
      var payload = chunks.join('').replace(/[\s=]+/g, '');
      while (payload.length % 4) payload += '=';
      var raw = atob(payload);
      var bytes = new Uint8Array(raw.length);
      for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
      var name = JSON.parse(new TextDecoder().decode(bytes)).os.timezone;
      if (!name) return null;
      // Ask Intl whether it knows the zone before trusting it to format times later.
      new Intl.DateTimeFormat('en-GB', { timeZone: name });
      return name;
    } catch (error) {
      return null;
    }
  }

  function parseIgc(text) {
    var lines = text.split(/\r?\n/);
    var fixes = [];
    var day = 0, previous = null, baroSeen = false, offset = 0;
    var device = [];
    // Midnight of the flight's date, in Unix seconds. Fixes carry absolute times, as the
    // ones read out of a KML already do: B records give only a time of day, and treating
    // that as an epoch put every IGC flight on 1 January 1970 — which the weather lookup
    // dutifully went and fetched the real weather for.
    var base = null;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var d = DATE_RE.exec(line);
      if (d) {
        var yy = +d[3];
        base = Date.UTC(yy < 80 ? 2000 + yy : 1900 + yy, +d[2] - 1, +d[1]) / 1000;
        continue;
      }
      var z = TZ_RE.exec(line);
      if (z) { offset = Math.round(parseFloat(z[1]) * 3600); continue; }
      var dev = DEVICE_RE.exec(line);
      if (dev) { device.push(dev[1]); continue; }
      var m = B_RE.exec(line);
      if (!m) continue;
      var seconds = +m[1] * 3600 + +m[2] * 60 + +m[3];
      // Midnight rollover, the same rule the Python parser uses.
      if (previous !== null && seconds < previous - 43200) day += 86400;
      previous = seconds;
      var lat = (+m[4] + +m[5] / 60000) * (m[6] === 'S' ? -1 : 1);
      var lon = (+m[7] + +m[8] / 60000) * (m[9] === 'W' ? -1 : 1);
      var baro = +m[11], gps = +m[12];
      if (baro) baroSeen = true;
      fixes.push({ t: (base || 0) + seconds + day, lat: lat, lon: lon,
                   baro: baro, gps: gps });
    }
    return { fixes: fixes, baro: baroSeen, kind: 'IGC', dated: base !== null,
             offset: offset, zone: deviceZone(device) };
  }

  function parseKmlText(text) {
    var doc = new DOMParser().parseFromString(text, 'application/xml');
    var fixes = [];
    var whens = [], coords = [];
    var all = doc.getElementsByTagName('*');
    for (var i = 0; i < all.length; i++) {
      var name = all[i].localName;
      if (name === 'when') whens.push(all[i].textContent.trim());
      else if (name === 'coord') coords.push(all[i].textContent.trim());
    }
    if (whens.length && coords.length) {
      // gx:Track — parallel when and coord children.
      var n = Math.min(whens.length, coords.length);
      for (var k = 0; k < n; k++) {
        var parts = coords[k].split(/\s+/).map(Number);
        var stamp = Date.parse(whens[k]) / 1000;
        if (!isFinite(stamp) || parts.length < 2) continue;
        fixes.push({ t: stamp, lat: parts[1], lon: parts[0], baro: 0, gps: parts[2] || 0 });
      }
      if (fixes.length > 1) {
        return { fixes: fixes, baro: false, kind: 'KML gx:Track', dated: true };
      }
      fixes = [];
    }
    // Otherwise: placemarks carrying a Point and a TimeStamp or TimeSpan.
    var marks = doc.getElementsByTagName('Placemark');
    for (var p = 0; p < marks.length; p++) {
      var when = null, position = null;
      var nodes = marks[p].getElementsByTagName('*');
      for (var q = 0; q < nodes.length; q++) {
        var local = nodes[q].localName;
        if ((local === 'when' || local === 'begin') && when === null) {
          when = Date.parse(nodes[q].textContent.trim()) / 1000;
        } else if (local === 'coordinates' && position === null) {
          var bits = nodes[q].textContent.trim().split(/[\s,]+/).map(Number);
          if (bits.length >= 2) position = bits;
        }
      }
      if (when !== null && isFinite(when) && position) {
        fixes.push({ t: when, lat: position[1], lon: position[0], baro: 0,
                     gps: position[2] || 0 });
      }
    }
    fixes.sort(function (a, b) { return a.t - b.t; });
    return { fixes: fixes, baro: false, kind: 'KML placemarks', dated: true };
  }

  // Minimal ZIP reader: locate the first .kml entry and inflate it. Browsers ship
  // DecompressionStream, so no library is needed for the one format that needs one.
  function readKmz(buffer) {
    var view = new DataView(buffer);
    var bytes = new Uint8Array(buffer);
    var eocd = -1;
    for (var i = buffer.byteLength - 22; i >= 0 && i > buffer.byteLength - 66000; i--) {
      if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) return Promise.reject(new Error('not a ZIP archive'));
    var count = view.getUint16(eocd + 10, true);
    var offset = view.getUint32(eocd + 16, true);
    var found = null;
    for (var e = 0; e < count && !found; e++) {
      if (view.getUint32(offset, true) !== 0x02014b50) break;
      var method = view.getUint16(offset + 10, true);
      var compressed = view.getUint32(offset + 20, true);
      var nameLength = view.getUint16(offset + 28, true);
      var extraLength = view.getUint16(offset + 30, true);
      var commentLength = view.getUint16(offset + 32, true);
      var localOffset = view.getUint32(offset + 42, true);
      var name = new TextDecoder().decode(bytes.subarray(offset + 46, offset + 46 + nameLength));
      if (/\.kml$/i.test(name)) {
        found = { method: method, compressed: compressed, localOffset: localOffset };
      }
      offset += 46 + nameLength + extraLength + commentLength;
    }
    if (!found) return Promise.reject(new Error('KMZ holds no .kml document'));

    var localName = view.getUint16(found.localOffset + 26, true);
    var localExtra = view.getUint16(found.localOffset + 28, true);
    var start = found.localOffset + 30 + localName + localExtra;
    var slice = bytes.subarray(start, start + found.compressed);
    if (found.method === 0) {
      return Promise.resolve(new TextDecoder().decode(slice));
    }
    if (typeof DecompressionStream === 'undefined') {
      return Promise.reject(new Error('this browser cannot inflate a KMZ; unzip it first'));
    }
    var stream = new Blob([slice]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Response(stream).text();
  }

  // ---- analysis --------------------------------------------------------------
  // Both from `RULES`, so `flight.WINDOW` and `analysis.GLIDE_PROGRESS` are the only
  // places these two exist. Aliased rather than used through `RULES` because they are
  // read inside the per-fix loops below and the names are the ones Python uses.
  var WINDOW = RULES.window, GLIDE_PROGRESS = RULES.glideProgress;

  function interpolate(ts, values, at) {
    if (at <= ts[0]) return values[0];
    if (at >= ts[ts.length - 1]) return values[values.length - 1];
    var lo = 0, hi = ts.length - 1;
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (ts[mid] <= at) lo = mid; else hi = mid; }
    var span = ts[hi] - ts[lo];
    var f = span ? (at - ts[lo]) / span : 0;
    return values[lo] + f * (values[hi] - values[lo]);
  }

  function analyse(track) {
    var fixes = track.fixes;
    // Drop duplicate or backwards timestamps, and obvious position jumps.
    var clean = [fixes[0]];
    for (var i = 1; i < fixes.length; i++) {
      var gap = fixes[i].t - clean[clean.length - 1].t;
      if (gap <= 0) continue;
      var previous = clean[clean.length - 1];
      if (distance(previous.lat, previous.lon, fixes[i].lat, fixes[i].lon) / gap > 100) continue;
      clean.push(fixes[i]);
    }
    fixes = clean;
    if (fixes.length < 20) throw new Error('too few usable fixes');

    var t = [], alt = [], s = [0], lat = [], lon = [], x = [], y = [];
    var useBaro = track.baro;
    var lat0 = fixes[0].lat, lon0 = fixes[0].lon;
    var mLat = 110540, mLon = 111320 * Math.cos(lat0 * Math.PI / 180);
    for (var j = 0; j < fixes.length; j++) {
      t.push(fixes[j].t - fixes[0].t);
      alt.push(useBaro ? fixes[j].baro : fixes[j].gps);
      lat.push(fixes[j].lat);
      lon.push(fixes[j].lon);
      x.push((fixes[j].lon - lon0) * mLon);
      y.push((fixes[j].lat - lat0) * mLat);
      if (j) s.push(s[j - 1] + distance(lat[j - 1], lon[j - 1], lat[j], lon[j]));
    }

    var climb = [], progress = [], speed = [];
    for (var k = 0; k < t.length; k++) {
      var t0 = Math.max(t[k] - WINDOW / 2, t[0]);
      var t1 = Math.min(t0 + WINDOW, t[t.length - 1]);
      if (t1 - t0 < WINDOW) t0 = Math.max(t1 - WINDOW, t[0]);
      var span = Math.max(t1 - t0, 1e-9);
      var s0 = interpolate(t, s, t0), s1 = interpolate(t, s, t1);
      var flown = s1 - s0;
      var straight = Math.hypot(interpolate(t, x, t1) - interpolate(t, x, t0),
                                interpolate(t, y, t1) - interpolate(t, y, t0));
      climb.push((interpolate(t, alt, t1) - interpolate(t, alt, t0)) / span);
      progress.push(flown > 1 ? Math.min(straight / flown, 1) : 0);
      speed.push(3.6 * flown / span);
    }

    // Heading, unwrapped, for turn counting where the sampling allows it.
    var interval = [];
    for (var d = 1; d < t.length; d++) interval.push(t[d] - t[d - 1]);
    interval.sort(function (a, b) { return a - b; });
    var median = interval[Math.floor(interval.length / 2)] || 1;
    var heading = [0];
    for (var h = 1; h < t.length; h++) {
      var course = Math.atan2(x[h] - x[h - 1], y[h] - y[h - 1]) * 180 / Math.PI;
      var delta = ((course - (heading[h - 1] % 360)) + 540) % 360 - 180;
      heading.push(heading[h - 1] + delta);
    }

    // Full revolutions between two fixes, the same way `analysis._revolutions` counts
    // them: split the unwrapped heading into runs of one turn direction — a run ends
    // only where the heading backs up by more than REVERSAL_HYSTERESIS, so noise and
    // the wander inside a circle extend it — and count only the runs that came all the
    // way round. Summing |dheading| instead scores a wingover as most of a turn, and
    // taking the net rotation (what this used to do) cancels a climb flown both ways.
    var REVERSAL_HYSTERESIS = RULES.reversalHysteresis;
    function revolutions(from, to) {
      var last = heading[from], way = 0, total = 0, run = 0;
      for (var r = from + 1; r < to; r++) {
        var step = heading[r] - last;
        if (way && step * way > 0) {
          run += step; last = heading[r];
        } else if (Math.abs(step) >= REVERSAL_HYSTERESIS) {
          if (Math.abs(run) >= 360) total += Math.abs(run) / 360;
          way = step > 0 ? 1 : -1;
          run = step; last = heading[r];
        }
      }
      if (Math.abs(run) >= 360) total += Math.abs(run) / 360;
      return total;
    }

    var phases = new Array(t.length).fill('cruise');
    // Runs of `test`, bridged across gaps shorter than `bridge` seconds and then kept
    // only where what is left lasts `least`. The bridging half was missing, and it is
    // not a refinement: `analysis.py` has always condensed first, because a thermal
    // briefly left and re-entered is one thermal (`_condense`, CONDENSE_THERMAL). A
    // climb gains height in surges, so `climb > 0` breaks every twenty seconds, and
    // demanding one unbroken minute meant a ridge-soaring upload reported "No climbs
    // met the thresholds" while the Python analysis of the same file found three.
    function mark(test, name, least, bridge) {
      var runs = [], run = null;
      for (var i2 = 0; i2 <= t.length; i2++) {
        var on = i2 < t.length && test(i2);
        if (on && run === null) run = i2;
        if (!on && run !== null) { runs.push([run, i2]); run = null; }
      }
      var merged = [];
      for (var r = 0; r < runs.length; r++) {
        var last = merged[merged.length - 1];
        if (last && t[runs[r][0]] - t[last[1] - 1] < bridge) last[1] = runs[r][1];
        else merged.push([runs[r][0], runs[r][1]]);
      }
      for (var m = 0; m < merged.length; m++) {
        if (t[merged[m][1] - 1] - t[merged[m][0]] < least) continue;
        for (var f2 = merged[m][0]; f2 < merged[m][1]; f2++) phases[f2] = name;
      }
    }
    mark(function (i2) { return progress[i2] >= GLIDE_PROGRESS; },
         'glide', RULES.minGlideSeconds, RULES.condenseGlide);
    // `analysis.py`'s thermal rule, minus the circling clause it cannot evaluate: this
    // page has no smoothed turn rate, so `climb > 1` stands in for "turning" and is the
    // one place the two implementations knowingly differ. Everything else — the slow
    // speed gate, the progress gate, both windows — comes from `RULES`.
    mark(function (i2) {
      return (progress[i2] < GLIDE_PROGRESS && climb[i2] > 0) ||
             (speed[i2] < RULES.thermalSlowKmh && climb[i2] > 0) || climb[i2] > 1;
    }, 'thermal', RULES.minThermalSeconds, RULES.condenseThermal);

    var climbs = [];
    var current = null;
    for (var i3 = 0; i3 < t.length; i3++) {
      if (phases[i3] === 'thermal' && current === null) current = i3;
      if ((phases[i3] !== 'thermal' || i3 === t.length - 1) && current !== null) {
        var stop = i3;
        var duration = t[stop] - t[current];
        var gain = alt[stop] - alt[current];
        if (duration >= RULES.minThermalSeconds && gain > RULES.minThermalGain) {
          var best = -Infinity;
          for (var b2 = current; b2 < stop; b2++) best = Math.max(best, climb[b2]);
          var turns = median <= RULES.turnResolutionLimit
            ? revolutions(current, stop) : null;
          climbs.push({
            start: current, stop: stop, duration: duration, gain: gain,
            average: gain / duration, best: best, turns: turns,
            startTime: fixes[current].t
          });
        }
        current = null;
      }
    }

    // Wind per climb from the drift of the circles: fit position against time, which
    // works because the glider's own airspeed averages out over a full turn.
    climbs.forEach(function (climb) {
      var n = climb.stop - climb.start;
      if (n < 20 || climb.duration < 30) return;
      var sumT = 0, sumX = 0, sumY = 0, sumTT = 0, sumTX = 0, sumTY = 0;
      for (var i = climb.start; i < climb.stop; i++) {
        sumT += t[i]; sumX += x[i]; sumY += y[i];
        sumTT += t[i] * t[i]; sumTX += t[i] * x[i]; sumTY += t[i] * y[i];
      }
      var denominator = n * sumTT - sumT * sumT;
      if (!denominator) return;
      var vx = (n * sumTX - sumT * sumX) / denominator;
      var vy = (n * sumTY - sumT * sumY) / denominator;
      var speedMs = Math.hypot(vx, vy);
      if (speedMs < 0.1) { climb.wind = { ms: 0, from: 0 }; return; }
      var towards = (Math.atan2(vx, vy) * 180 / Math.PI + 360) % 360;
      climb.wind = { ms: speedMs, from: (towards + 180) % 360 };
    });

    // Glides, with the same thresholds as the full analysis.
    var glides = [];
    var open = null;
    for (var i4 = 0; i4 < t.length; i4++) {
      if (phases[i4] === 'glide' && open === null) open = i4;
      if ((phases[i4] !== 'glide' || i4 === t.length - 1) && open !== null) {
        var stop4 = i4;
        var seconds = t[stop4] - t[open];
        if (seconds >= RULES.minGlideSeconds) {
          var straightM = distance(lat[open], lon[open], lat[stop4], lon[stop4]);
          var drop = alt[stop4] - alt[open];
          glides.push({
            start: open, stop: stop4, duration: seconds, distance: straightM,
            height: drop, ld: drop < 0 ? -straightM / drop : null,
            speed: 3.6 * straightM / Math.max(seconds, 1)
          });
        }
        open = null;
      }
    }

    // Free distance through up to three turnpoints, same dynamic program as xc.py but
    // on a coarser sample so it stays instant in a browser.
    var course = freeDistance(lat, lon, s);

    var budget = { thermal: 0, glide: 0, other: 0 };
    climbs.forEach(function (c) { budget.thermal += c.duration; });
    glides.forEach(function (g) { budget.glide += g.duration; });
    budget.other = Math.max(t[t.length - 1] - budget.thermal - budget.glide, 0);

    var winds = climbs.filter(function (c) {
      return c.wind && (c.turns === null ? c.duration >= 120 : c.turns >= 2);
    });
    var overall = null;
    if (winds.length) {
      var ex = 0, ey = 0;
      winds.forEach(function (c) {
        ex += c.wind.ms * Math.sin(c.wind.from * Math.PI / 180);
        ey += c.wind.ms * Math.cos(c.wind.from * Math.PI / 180);
      });
      ex /= winds.length; ey /= winds.length;
      overall = { ms: Math.hypot(ex, ey),
                  from: (Math.atan2(ex, ey) * 180 / Math.PI + 360) % 360 };
    }

    var gained = 0;
    for (var g = 1; g < alt.length; g++) if (alt[g] > alt[g - 1]) gained += alt[g] - alt[g - 1];

    return {
      lat: lat, lon: lon, glides: glides, xc: course.km, shape: course.shape,
      budget: budget, wind: overall,
      t: t, alt: alt, s: s, x: x, y: y, climb: climb, phases: phases, climbs: climbs,
      median: median, useBaro: useBaro, kind: track.kind, dated: !!track.dated,
      epoch: fixes[0].t,
      // Where the flight's clock comes from. `zone` is an IANA name and wins when it is
      // there, because it knows the day's daylight saving; `offset` is seconds east of
      // UTC from a plain header. Neither, and the clock reads UTC — which a KML always
      // does, and which is honest rather than a guess from the reader's own machine.
      offset: track.offset || 0,
      zone: track.zone || null,
      duration: t[t.length - 1],
      flown: s[s.length - 1],
      straight: distance(lat[0], lon[0], lat[lat.length - 1], lon[lon.length - 1]),
      gained: gained,
      altMin: Math.min.apply(null, alt), altMax: Math.max.apply(null, alt)
    };
  }

  var CARDINALS = 'N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW'.split(' ');
  function cardinal(d) { return CARDINALS[Math.round(d / 22.5) % 16]; }

  // Maximise the sum of four legs through points in time order. Sampling by distance
  // flown rather than by index keeps the samples where the flight actually goes
  // somewhere instead of piling them up inside the thermals.
  function freeDistance(lat, lon, s) {
    var limit = 220;
    var total = s[s.length - 1];
    var pick = [0];
    for (var k = 1; k < limit; k++) {
      var target = total * k / (limit - 1);
      var lo = 0, hi = s.length - 1;
      while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (s[mid] < target) lo = mid; else hi = mid; }
      if (pick[pick.length - 1] !== hi) pick.push(hi);
    }
    var n = pick.length;
    var d = [];
    for (var a = 0; a < n; a++) {
      d.push(new Float64Array(n));
      for (var b = a + 1; b < n; b++) {
        d[a][b] = distance(lat[pick[a]], lon[pick[a]], lat[pick[b]], lon[pick[b]]);
      }
    }
    // Predecessors per stage as well as the best value, so the chain can be walked back
    // out: the distance alone cannot say whether the flight was a triangle.
    var best = new Float64Array(n);
    var back = [];
    for (var leg = 0; leg < 4; leg++) {
      var next = new Float64Array(n);
      var prev = new Int32Array(n);
      for (var q = 0; q < n; q++) prev[q] = -1;
      for (var to = 0; to < n; to++) {
        var top = 0, arg = -1;
        for (var from = 0; from < to; from++) {
          var value = best[from] + d[from][to];
          if (value > top) { top = value; arg = from; }
        }
        next[to] = top;
        prev[to] = arg;
      }
      back.push(prev);
      best = next;
    }
    var km = 0, end = 0;
    for (var e = 0; e < n; e++) if (best[e] > km) { km = best[e]; end = e; }

    var chain = [end], at = end;
    for (var lg = 3; lg >= 0; lg--) {
      at = back[lg][at];
      if (at < 0) break;
      chain.unshift(at);
    }
    return { km: km, shape: shapeOf(lat, lon, chain.map(function (i) { return pick[i]; }), km) };
  }

  // XContest's categories, the same test the Python side applies: closed under the 20%
  // rule, then FAI if every side of the triangle is at least 28% of its perimeter.
  function shapeOf(lat, lon, points, total) {
    if (points.length < 5 || !total) return '';
    var closing = distance(lat[points[0]], lon[points[0]],
                           lat[points[4]], lon[points[4]]);
    if (closing / total >= 0.2) return 'open distance';
    var corners = [points[1], points[2], points[3]];
    var sides = [];
    for (var i = 0; i < 3; i++) {
      var a = corners[i], b = corners[(i + 1) % 3];
      sides.push(distance(lat[a], lon[a], lat[b], lon[b]));
    }
    var perimeter = sides[0] + sides[1] + sides[2];
    if (perimeter <= 0) return 'open distance';
    var shortest = Math.min(sides[0], Math.min(sides[1], sides[2])) / perimeter;
    return shortest >= 0.28 ? 'FAI triangle' : 'flat triangle';
  }

  // ---- drawing ---------------------------------------------------------------
  function panelInk() {
    var probe = getComputedStyle(document.body);
    return { ink: probe.color };
  }

  // The charts are drawn once into an offscreen canvas and then blitted, so the linked
  // cursor can repaint on every pointer move without re-running the track loop. A
  // five-hour flight is thousands of coloured segments and redrawing them at pointer
  // rate is exactly what makes a canvas chart feel heavy; a blit and one circle does not.
  function baseOf(canvas) {
    var base = canvas.__base;
    if (!base || base.width !== canvas.width || base.height !== canvas.height) {
      base = document.createElement('canvas');
      base.width = canvas.width;
      base.height = canvas.height;
      canvas.__base = base;
    }
    return base;
  }

  // `fix` is an index into the *full* track, which is what a climb, a glide and a
  // pointer all naturally point at; the 3D view is indexed by position in the decimated
  // sample instead, and `linkCharts` is the one place that converts between them.
  function paint(canvas, fix) {
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (canvas.__base) ctx.drawImage(canvas.__base, 0, 0);
    if (fix === null || fix === undefined || !canvas.__at) return;
    var at = canvas.__at(fix);
    if (!at) return;
    ctx.beginPath();
    ctx.arc(at[0], at[1], 6, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,255,255,0.95)';
    ctx.fill();
    ctx.lineWidth = 2.4;
    ctx.strokeStyle = 'rgba(235,104,52,0.98)';
    ctx.stroke();
  }

  function drawSide(root, a) {
    var canvas = root.querySelector('.ql-side');
    var ctx = baseOf(canvas).getContext('2d');
    var W = canvas.width, H = canvas.height;
    var left = 54, right = 16, top = 14, bottom = 30;
    ctx.clearRect(0, 0, W, H);
    var styles = getComputedStyle(document.body);
    // The floor drops to the ground once there is a ground: a side view whose lowest
    // gridline is the flight's own lowest point draws the terrain off the bottom of the
    // chart, which is the one part of it the clearance series exists to show.
    var lowest = a.ground ? Math.min(a.altMin, groundFloor(a)) : a.altMin;
    var floor = Math.floor(lowest / 100) * 100, ceiling = Math.ceil(a.altMax / 100) * 100;
    function sx(v) { return left + (W - left - right) * v / Math.max(a.flown, 1); }
    function sy(v) {
      return top + (H - top - bottom) * (1 - (v - floor) / Math.max(ceiling - floor, 1));
    }

    // The ground under the track, where the DEM was fetched. Filled rather than lined,
    // because the question it answers — how much air was under you — is an area, and a
    // line alone reads as a second altitude trace.
    if (a.ground) {
      ctx.beginPath();
      ctx.moveTo(sx(0), sy(floor));
      for (var gi = 0; gi < a.ground.length; gi++) ctx.lineTo(sx(a.s[gi]), sy(a.ground[gi]));
      ctx.lineTo(sx(a.s[a.s.length - 1]), sy(floor));
      ctx.closePath();
      ctx.fillStyle = 'rgba(128,132,140,0.30)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(128,132,140,0.75)';
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }

    ctx.strokeStyle = 'rgba(128,128,128,0.3)';
    ctx.fillStyle = styles.color;
    ctx.font = '10px ui-sans-serif, sans-serif';
    ctx.textAlign = 'right';
    for (var level = floor; level <= ceiling; level += 500) {
      var y = sy(level);
      ctx.globalAlpha = 0.25;
      ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(W - right, y); ctx.stroke();
      ctx.globalAlpha = 0.75;
      ctx.fillText(String(level), left - 8, y + 3);
    }
    ctx.globalAlpha = 1;
    ctx.lineWidth = 2.2;
    for (var i = 1; i < a.t.length; i++) {
      ctx.strokeStyle = rgb(climbColour(a.climb[i]));
      ctx.beginPath();
      ctx.moveTo(sx(a.s[i - 1]), sy(a.alt[i - 1]));
      ctx.lineTo(sx(a.s[i]), sy(a.alt[i]));
      ctx.stroke();
    }
    ctx.textAlign = 'center';
    ctx.fillStyle = styles.color;
    ctx.globalAlpha = 0.75;
    var stepKm = Math.max(Math.round(a.flown / 1000 / 10), 1);
    for (var km = 0; km * 1000 <= a.flown; km += stepKm) {
      ctx.fillText(String(km), sx(km * 1000), H - 10);
    }
    ctx.globalAlpha = 1;
    a.climbs.forEach(function (climb, index) {
      var mid = (climb.start + climb.stop) >> 1;
      markerAt(ctx, sx(a.s[mid]), sy(a.alt[mid]), String(index + 1));
    });

    // How to place the cursor here, and how to read one off a pointer. Kept on the
    // element rather than in a closure the linker cannot see, so the two charts can be
    // driven identically without either of them knowing about the other.
    canvas.__at = function (fix) { return [sx(a.s[fix]), sy(a.alt[fix])]; };
    canvas.__nearest = function (px) {
      var want = (px - left) / Math.max(W - left - right, 1) * Math.max(a.flown, 1);
      var low = 0, high = a.s.length - 1;
      while (low < high) {
        var mid = (low + high) >> 1;
        if (a.s[mid] < want) low = mid + 1; else high = mid;
      }
      if (low > 0 && Math.abs(a.s[low - 1] - want) <= Math.abs(a.s[low] - want)) low -= 1;
      return low;
    };
    paint(canvas, null);
  }

  function markerAt(ctx, cx, cy, label) {
    ctx.beginPath();
    ctx.arc(cx, cy, 8, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(235,104,52,0.92)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.85)';
    ctx.lineWidth = 1.3;
    ctx.stroke();
    ctx.fillStyle = '#fff';
    ctx.font = '600 10px ui-sans-serif, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, cx, cy + 0.5);
    ctx.textBaseline = 'alphabetic';
  }

  function drawPlan(root, a) {
    var canvas = root.querySelector('.ql-plan');
    var ctx = baseOf(canvas).getContext('2d');
    var W = canvas.width, H = canvas.height;
    var pad = 24;
    ctx.clearRect(0, 0, W, H);
    var minX = Math.min.apply(null, a.x), maxX = Math.max.apply(null, a.x);
    var minY = Math.min.apply(null, a.y), maxY = Math.max.apply(null, a.y);
    var scale = Math.min((W - 2 * pad) / Math.max(maxX - minX, 1),
                         (H - 2 * pad) / Math.max(maxY - minY, 1));
    var offX = (W - (maxX - minX) * scale) / 2, offY = (H - (maxY - minY) * scale) / 2;
    function px(v) { return offX + (v - minX) * scale; }
    function py(v) { return H - offY - (v - minY) * scale; }
    ctx.lineWidth = 2.2;
    for (var i = 1; i < a.x.length; i++) {
      ctx.strokeStyle = rgb(climbColour(a.climb[i]));
      ctx.beginPath();
      ctx.moveTo(px(a.x[i - 1]), py(a.y[i - 1]));
      ctx.lineTo(px(a.x[i]), py(a.y[i]));
      ctx.stroke();
    }
    a.climbs.forEach(function (climb, index) {
      var mid = (climb.start + climb.stop) >> 1;
      markerAt(ctx, px(a.x[mid]), py(a.y[mid]), String(index + 1));
    });

    canvas.__at = function (fix) { return [px(a.x[fix]), py(a.y[fix])]; };
    // Nearest in the plane rather than along the track: a top view crosses itself, and
    // "which point is under the pointer" has no answer in one dimension. Every fix, not
    // the decimated sample — the loop is a few thousand squared distances and runs on a
    // pointer move, which is nothing beside the blit it precedes.
    canvas.__nearest = function (pointerX, pointerY) {
      var best = 0, bestGap = Infinity;
      for (var i = 0; i < a.x.length; i++) {
        var dx = px(a.x[i]) - pointerX, dy = py(a.y[i]) - pointerY;
        var gap = dx * dx + dy * dy;
        if (gap < bestGap) { bestGap = gap; best = i; }
      }
      return best;
    };
    paint(canvas, null);
  }

  // Every fifth fix or so: the 3D view redraws the whole track on each frame of a drag,
  // and 1 Hz for a five-hour flight is more points than the canvas can resolve. The
  // cursor track has to be sampled *identically*, because `initView3d` indexes it by
  // position and the charts point at fixes.
  function sampleIndices(a) {
    var step = Math.max(Math.round(a.t.length / 1400), 1);
    var sample = [];
    for (var k = 0; k < a.t.length; k += step) sample.push(k);
    return sample;
  }

  function samplePosition(sample, fix) {
    var low = 0, high = sample.length - 1;
    while (low < high) {
      var mid = (low + high) >> 1;
      if (sample[mid] < fix) low = mid + 1; else high = mid;
    }
    if (low > 0 && Math.abs(sample[low - 1] - fix) <= Math.abs(sample[low] - fix)) low -= 1;
    return low;
  }

  // One cursor across the side view, the top view and the 3D map, plus the tables that
  // list the same moments. A built report has had this for a while; an upload had none
  // of it — `initView3d` was handed a null cursor track, so the map could not follow
  // anything, and the rows carried no position to point at.
  //
  // Same behaviour as `render_html`'s linked cursor, reduced to what a canvas chart can
  // carry — no tooltip and no band highlight — but the part that matters is kept: hover
  // previews, a click *pins*, and leaving the chart returns to the pin rather than
  // clearing. Hover alone takes the marker away at exactly the moment the reader wants
  // it, which is when they have found something and are about to look at the map.
  //
  // A pin uses `revealCursor` rather than `setCursor`, so the map pans until the marker
  // is on screen. Marking a point that projects off the edge of the panel is the same
  // as not marking it: the reader asked where this was on the ground and the map did
  // not move.
  function linkCharts(root, a, sample, view) {
    var charts = [root.querySelector('.ql-side'), root.querySelector('.ql-plan')];
    var pinned = null;

    function show(fix, pin) {
      charts.forEach(function (canvas) { if (canvas) paint(canvas, fix); });
      if (!view) return;
      if (fix === null) { view.clearCursor(); return; }
      var position = samplePosition(sample, fix);
      if (pin && view.revealCursor) view.revealCursor(position);
      else view.setCursor(position);
    }

    function preview(fix) { show(fix, false); }
    function restore() { show(pinned, pinned !== null); }

    function pin(fix) {
      pinned = (fix === pinned) ? null : fix;
      restore();
      return pinned !== null;
    }

    charts.forEach(function (canvas) {
      if (!canvas || !canvas.__nearest) return;
      canvas.style.cursor = 'crosshair';
      function fixUnder(event) {
        var box = canvas.getBoundingClientRect();
        // The canvas has a fixed backing size and CSS scales it, so a client coordinate
        // has to come back through that scale before the projections can invert it.
        var scaleX = canvas.width / Math.max(box.width, 1);
        var scaleY = canvas.height / Math.max(box.height, 1);
        return canvas.__nearest((event.clientX - box.left) * scaleX,
                                (event.clientY - box.top) * scaleY);
      }
      canvas.addEventListener('pointermove', function (event) {
        preview(fixUnder(event));
      });
      canvas.addEventListener('pointerleave', restore);
      canvas.addEventListener('click', function (event) { pin(fixUnder(event)); });
    });

    root.querySelectorAll('tr[data-cursor]').forEach(function (row) {
      row.classList.add('is-linked');
      row.tabIndex = 0;
      row.addEventListener('mouseenter', function () {
        preview(parseInt(row.dataset.cursor, 10));
      });
      row.addEventListener('mouseleave', restore);
      function go() {
        var fix = parseInt(row.dataset.cursor, 10);
        if (isNaN(fix)) return;
        var panel = root.querySelector('.ql-3d .view3d-panel');
        // Only on the pin, never on the release: scrolling the reader back to the map
        // they have just finished with is the wrong half of a toggle.
        if (pin(fix) && panel) {
          panel.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
      }
      row.addEventListener('click', go);
      row.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') { go(); event.preventDefault(); }
      });
    });
  }

  // ---- presentation ----------------------------------------------------------
  // Local time where the flight happened, not the reader's and not UTC. `toISOString`
  // is UTC, so the offset is added to the instant and the result still read as UTC —
  // which is the standard trick and the reason this takes a comment.
  var clockFormat = null, clockZone = null;
  function clock(a, seconds) {
    if (a.zone) {
      if (clockZone !== a.zone) {
        // Built once and cached: `Intl.DateTimeFormat` is expensive to construct and
        // this is called per table row.
        clockFormat = new Intl.DateTimeFormat('en-GB', {
          timeZone: a.zone, hourCycle: 'h23',
          hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
        clockZone = a.zone;
      }
      return clockFormat.format(new Date((a.epoch + seconds) * 1000));
    }
    // `toISOString` is UTC, so a fixed offset is added to the instant and the result
    // still read as UTC. That is the standard trick and the reason this takes a comment.
    var date = new Date((a.epoch + seconds + (a.offset || 0)) * 1000);
    return date.toISOString().substr(11, 8);
  }

  function tile(key, value, sub) {
    return '<div class="stat"><span class="key">' + key + '</span>' +
      '<span class="stat-value">' + value + '</span>' +
      (sub ? '<span class="sub">' + sub + '</span>' : '') + '</div>';
  }

  // The 3D view, driven by the same initView3d the built reports use.
  //
  // The elevation model is fetched here, in the page, from the same keyless terrarium
  // DEM `terrain.py` uses — the tiles are CORS-open, so a browser may read their pixels.
  // Served from a host that works and an uploaded track gets real ground. Inside a
  // published artifact every host is blocked, the fetch fails, and the ground falls back
  // to one flat plane at the lowest point of the flight, which is what this always did.
  // Either way the shape of the flight *in the air* is exact, because the altitudes are
  // the track's own; what the DEM adds is the ground under it.
  //
  // Terrarium encodes metres in the RGB channels of an ordinary PNG:
  //     metres = R * 256 + G + B / 256 - 32768
  var DEM_TILE = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
  var DEM_TILE_SIZE = 256;
  // The CLI's budget: quality over the wait, and the finer patch on zoom-in comes on top.
  var DEM_MAX_TILES = 64;
  // Long enough for a slow phone, short enough that a blocked page is not left staring at
  // a spinner. A CSP refusal fires `onerror` immediately and never reaches this.
  var DEM_TIMEOUT = 9000;
  // Nodes in the grid, matching the CLI's 120 000. Never serialised, so the only cost is
  // the mesh itself — and the drape is budgeted separately from it.
  var DEM_NODES = 120000;

  function demTileXY(lat, lon, zoom) {
    var n = Math.pow(2, zoom);
    var radians = lat * Math.PI / 180;
    return [(lon + 180) / 360 * n,
            (1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2 * n];
  }

  // Highest zoom whose tile count stays inside the budget — detail is wasted once the
  // grid is coarser than the tiles, and an XC flight at z12 is hundreds of them.
  function demZoom(box) {
    for (var zoom = 12; zoom > 5; zoom--) {
      var a = demTileXY(box.north, box.west, zoom);
      var b = demTileXY(box.south, box.east, zoom);
      var tiles = (Math.floor(b[0]) - Math.floor(a[0]) + 1) *
                  (Math.floor(b[1]) - Math.floor(a[1]) + 1);
      if (tiles <= DEM_MAX_TILES) return zoom;
    }
    return 6;
  }

  // Calls back with a grid in the shape `view3d` wants, or with null. Never throws and
  // never leaves the caller waiting: a tile that fails is one tile, and the timeout
  // settles with whatever arrived.
  function loadDem(box, done) {
    var zoom = demZoom(box);
    var a = demTileXY(box.north, box.west, zoom);
    var b = demTileXY(box.south, box.east, zoom);
    var x0 = Math.floor(a[0]), y0 = Math.floor(a[1]);
    var x1 = Math.floor(b[0]), y1 = Math.floor(b[1]);
    var wide = x1 - x0 + 1, high = y1 - y0 + 1;
    var mosaic = document.createElement('canvas');
    mosaic.width = wide * DEM_TILE_SIZE;
    mosaic.height = high * DEM_TILE_SIZE;
    var ctx;
    try {
      ctx = mosaic.getContext('2d', { willReadFrequently: true });
    } catch (error) {
      return done(null);
    }
    if (!ctx) return done(null);

    var pending = wide * high, arrived = 0, settled = false;
    var timer = setTimeout(function () { finish(); }, DEM_TIMEOUT);

    function finish() {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (!arrived) return done(null);
      var pixels;
      try {
        pixels = ctx.getImageData(0, 0, mosaic.width, mosaic.height);
      } catch (error) {
        // A tile served without CORS headers taints the canvas and this throws. Better
        // the flat plane than a broken page.
        return done(null);
      }
      done(demGrid(box, zoom, x0, y0, pixels));
    }

    function count() { if (--pending <= 0) finish(); }

    for (var ty = y0; ty <= y1; ty++) {
      for (var tx = x0; tx <= x1; tx++) {
        (function (tileX, tileY) {
          var image = new Image();
          // Required before the pixels can be read back, and the reason the tiles being
          // CORS-open matters rather than merely being reachable.
          image.crossOrigin = 'anonymous';
          image.onload = function () {
            try {
              ctx.drawImage(image, (tileX - x0) * DEM_TILE_SIZE,
                            (tileY - y0) * DEM_TILE_SIZE);
              arrived++;
            } catch (error) { /* one tile short is not a failure */ }
            count();
          };
          image.onerror = count;
          image.src = DEM_TILE.replace('{z}', zoom)
                              .replace('{x}', tileX).replace('{y}', tileY);
        })(tx, ty);
      }
    }
  }

  function demGrid(box, zoom, x0, y0, pixels) {
    // Aspect-aware, so cells stay roughly square on the ground, then scaled to the node
    // budget on both axes at once.
    var mid = (box.north + box.south) / 2;
    var wideM = (box.east - box.west) * 111320 * Math.cos(mid * Math.PI / 180);
    var highM = (box.north - box.south) * 110540;
    var cols = 480;
    var rows = Math.max(Math.round(cols * highM / Math.max(wideM, 1)), 8);
    rows = Math.min(rows, cols);
    if (rows * cols > DEM_NODES) {
      var shrink = Math.sqrt(DEM_NODES / (rows * cols));
      cols = Math.max(Math.round(cols * shrink), 24);
      rows = Math.max(Math.round(rows * shrink), 8);
    }

    var z = new Array(cols * rows);
    var min = Infinity, max = -Infinity, found = 0;
    for (var r = 0; r < rows; r++) {
      var lat = box.north - (box.north - box.south) * r / (rows - 1);
      var py = Math.min(Math.max(
        Math.round((demTileXY(lat, box.west, zoom)[1] - y0) * DEM_TILE_SIZE), 0),
        pixels.height - 1);
      for (var c = 0; c < cols; c++) {
        var lon = box.west + (box.east - box.west) * c / (cols - 1);
        var px = Math.min(Math.max(
          Math.round((demTileXY(lat, lon, zoom)[0] - x0) * DEM_TILE_SIZE), 0),
          pixels.width - 1);
        var at = (py * pixels.width + px) * 4;
        // Alpha 0 is a tile that never arrived: leave a hole and fill it below rather
        // than reading -32768 m of "sea" into the middle of the mesh.
        if (pixels.data[at + 3] === 0) { z[r * cols + c] = null; continue; }
        var metres = pixels.data[at] * 256 + pixels.data[at + 1] +
                     pixels.data[at + 2] / 256 - 32768;
        metres = Math.round(metres);
        z[r * cols + c] = metres;
        if (metres < min) min = metres;
        if (metres > max) max = metres;
        found++;
      }
    }
    if (!found) return null;
    for (var i = 0; i < z.length; i++) if (z[i] === null) z[i] = min;
    return { west: box.west, east: box.east, south: box.south, north: box.north,
             rows: rows, cols: cols, min: min, max: max, z: z, zoom: zoom };
  }

  // ---- the ground under the track ---------------------------------------------
  //
  // The DEM was already fetched for the 3D view; what was missing was the series that
  // says how much air was under the glider, which is the number a pilot asks for after
  // "how high was I". Bilinear rather than nearest-node: at 240 columns over a
  // cross-country box a cell is a few hundred metres across, and nearest-node makes the
  // ground under a glide a staircase that the clearance figure then reads the treads of.
  //
  // This is the *page's* copy of what `terrain.py` does for a built report, and it is
  // the same disagreement between a DEM cell and a GPS altitude — so a clearance can
  // come out slightly negative over steep ground and that is the model losing an
  // argument, not the pilot. Nothing here reports a negative number as a finding; see
  // the "no finding may assert something the run did not check" rule.
  function groundUnder(dem, lat, lon) {
    var fx = (lon - dem.west) / Math.max(dem.east - dem.west, 1e-9) * (dem.cols - 1);
    var fy = (dem.north - lat) / Math.max(dem.north - dem.south, 1e-9) * (dem.rows - 1);
    fx = Math.min(Math.max(fx, 0), dem.cols - 1);
    fy = Math.min(Math.max(fy, 0), dem.rows - 1);
    var c0 = Math.floor(fx), r0 = Math.floor(fy);
    var c1 = Math.min(c0 + 1, dem.cols - 1), r1 = Math.min(r0 + 1, dem.rows - 1);
    var tx = fx - c0, ty = fy - r0;
    var z00 = dem.z[r0 * dem.cols + c0], z10 = dem.z[r0 * dem.cols + c1];
    var z01 = dem.z[r1 * dem.cols + c0], z11 = dem.z[r1 * dem.cols + c1];
    return (z00 * (1 - tx) + z10 * tx) * (1 - ty) + (z01 * (1 - tx) + z11 * tx) * ty;
  }

  // Writes `a.ground` and `a.agl` in place. Called once, when the DEM lands.
  function addClearance(a, dem) {
    var ground = new Float64Array(a.lat.length);
    var agl = new Float64Array(a.lat.length);
    for (var i = 0; i < a.lat.length; i++) {
      ground[i] = groundUnder(dem, a.lat[i], a.lon[i]);
      agl[i] = a.alt[i] - ground[i];
    }
    a.ground = ground;
    a.agl = agl;
  }

  function groundFloor(a) {
    var least = Infinity;
    for (var i = 0; i < a.ground.length; i++) if (a.ground[i] < least) least = a.ground[i];
    return least;
  }

  // The lowest the flight got, excluding its own launch and landing — `metrics.
  // airborne_window` in the report, and the same `ground_margin` from `THRESHOLDS`,
  // because the lowest clearance of *any* flight is the ground it started on.
  function lowestClearance(a) {
    if (!a.agl) return null;
    var margin = TH.ground_margin;
    var first = -1, last = -1;
    for (var i = 0; i < a.agl.length; i++) {
      if (a.agl[i] <= margin) continue;
      if (first < 0) first = i;
      last = i;
    }
    if (first < 0 || last - first < 2) return null;
    var best = Infinity, at = first;
    for (var k = first; k <= last; k++) {
      if (a.agl[k] < best) { best = a.agl[k]; at = k; }
    }
    return { metres: best, fix: at };
  }

  // One tile, appended to the stats the moment the ground exists. Appended rather than
  // written into the row up front: a placeholder that may never be filled is worse than
  // a row that grows, and inside a published artifact the DEM never arrives at all.
  //
  // The launch and the landing are excluded, so this is the lowest the flight got while
  // it was actually flying — `low_clearance` decides only whether the tile says the
  // number was a low one, and the wording stays a measurement either way.
  function showClearance(root, a) {
    var low = lowestClearance(a);
    if (!low) return;
    var stats = root.querySelector('.ql-stats');
    if (!stats || stats.querySelector('.ql-clearance')) return;
    var cell = document.createElement('div');
    cell.className = 'stat ql-clearance';
    cell.innerHTML = '<span class="key"></span><span class="stat-value"></span>' +
                     '<span class="sub"></span>';
    cell.querySelector('.key').textContent = 'lowest clearance';
    cell.querySelector('.stat-value').textContent = Math.round(low.metres) + ' m';
    cell.querySelector('.sub').textContent =
      'at ' + clock(a, a.t[low.fix]) +
      (low.metres < TH.low_clearance ? ' · under ' + TH.low_clearance + ' m agl' : '') +
      ' · launch and landing excluded';
    stats.appendChild(cell);
  }

  // The tile templates are already in the template's markup; read them back rather than
  // repeating the URLs here, so there is one place they can be wrong.
  var TILES = (function () {
    try {
      var node = template && template.content.querySelector('.view3d-data');
      return node ? (JSON.parse(node.textContent).tiles || null) : null;
    } catch (error) {
      return null;
    }
  })();

  // The box the terrain covers. Padded for context the way `terrain.for_flight` pads it:
  // a wider box costs nothing to draw, each cell simply covers more ground.
  function demBox(a) {
    var west = Math.min.apply(null, a.lon), east = Math.max.apply(null, a.lon);
    var south = Math.min.apply(null, a.lat), north = Math.max.apply(null, a.lat);
    var padX = Math.max((east - west) * 0.35, 0.06);
    var padY = Math.max((north - south) * 0.35, 0.06);
    return { west: west - padX, east: east + padX,
             south: south - padY, north: north + padY };
  }

  function scene3d(a, dem, sample) {
    var pad = 0.02;
    var west = Math.min.apply(null, a.lon) - pad, east = Math.max.apply(null, a.lon) + pad;
    var south = Math.min.apply(null, a.lat) - pad, north = Math.max.apply(null, a.lat) + pad;
    // A grid rather than a single quad: the renderer shades and drapes per cell, and a
    // coarse mesh is all a flat plane needs.
    var cols = 61, rows = 25;
    var ground = Math.round(a.altMin - 30);
    var z = new Array(cols * rows);
    for (var i = 0; i < z.length; i++) z[i] = ground;

    // Every fix, not the decimated sample: the sample keeps ~1 400 points whatever the
    // flight's length, which on a long 1 Hz flight is one point per 13 s — a thermal
    // circle drawn as a triangle. The cursor track (built in `show3d`) still uses the
    // sample, because that is what the charts index; the view reads the two separately.
    var track = { lon: [], lat: [], alt: [], c: [], t: [] };
    a.lon.forEach(function (_, k) {
      track.lon.push(+a.lon[k].toFixed(5));
      track.lat.push(+a.lat[k].toFixed(5));
      track.alt.push(Math.round(a.alt[k]));
      track.c.push(bandIndex(a.climb[k]));
      track.t.push(Math.round(a.t[k] - a.t[0]));
    });

    var climbs = a.climbs.map(function (climb, index) {
      var middle = (climb.start + climb.stop) >> 1;
      return {
        label: String(index + 1),
        lon: +a.lon[middle].toFixed(5), lat: +a.lat[middle].toFixed(5),
        alt: Math.round(a.alt[middle]), tow: false
      };
    });

    return {
      terrain: dem || { west: west, east: east, south: south, north: north,
                        rows: rows, cols: cols, min: ground, max: ground, z: z },
      trackTop: Math.round(a.altMax),
      track: track,
      climbs: climbs,
      palette: RAMP.map(function (band) { return band[1]; }),
      basemaps: {},
      tiles: TILES,
      landing: { lon: +a.lon[a.lon.length - 1].toFixed(5),
                 lat: +a.lat[a.lat.length - 1].toFixed(5),
                 alt: Math.round(a.alt[a.alt.length - 1]) }
    };
  }

  function bandIndex(value) {
    for (var i = 0; i < RAMP.length; i++) if (value < RAMP[i][0]) return i;
    return RAMP.length - 1;
  }

  function show3d(root, a, uid, sample) {
    var host = root.querySelector('.ql-3d');
    var panel = host && host.querySelector('.view3d-panel');
    // The charts still link to each other when there is no 3D view to link to — that is
    // the whole of "degrade, do not blank", and it is why `linkCharts` runs either way.
    if (!panel || typeof initView3d !== 'function') {
      linkCharts(root, a, sample, null);
      return;
    }
    var note = root.querySelector('.ql-3d-note');
    var heights = 'Heights are ' + (a.useBaro ? 'pressure' : 'GPS') +
                  ' altitude, at true vertical scale.';
    note.textContent = 'Fetching terrain…';
    // The DEM is fetched *before* initView3d rather than swapped in after it. Re-running
    // initView3d on a live panel would bind a second set of pointer handlers to the same
    // canvas and every gesture would count twice; there is no API for replacing the grid
    // under a running view, and inventing one to save a second of waiting is the worse
    // trade. The caption says what is happening meanwhile.
    loadDem(demBox(a), function (dem) {
      // The clearance series, before anything is drawn with it. The DEM was fetched for
      // the 3D view and the height above ground fell out of it for free; what it needed
      // was somewhere to be written. The side view is redrawn here rather than in
      // `present`, because that ran while this fetch was still in the air — and it is
      // redrawn *before* `linkCharts`, which reads `__at`/`__nearest` off the canvas
      // that `drawSide` writes.
      if (dem) {
        addClearance(a, dem);
        drawSide(root, a);
        showClearance(root, a);
      }
      // Unique canvas id per flight: initView3d registers itself under it, and two panels
      // sharing an id would leave the second unreachable.
      panel.querySelector('canvas.view3d').id = 'view3d-' + uid;
      panel.querySelector('.view3d-data').textContent =
        JSON.stringify(scene3d(a, dem, sample));
      // The cursor track the map follows, over the same sample the scene's track uses.
      // `min` is the UTC minute per sample, which is what walks the sun with the cursor;
      // without it the light stays frozen wherever the flight's midpoint put it.
      var cursorTrack = { lon: [], lat: [], alt: [], min: [] };
      sample.forEach(function (k) {
        cursorTrack.lon.push(+a.lon[k].toFixed(5));
        cursorTrack.lat.push(+a.lat[k].toFixed(5));
        cursorTrack.alt.push(Math.round(a.alt[k]));
        var when = new Date((a.epoch + a.t[k]) * 1000);
        cursorTrack.min.push(when.getUTCHours() * 60 + when.getUTCMinutes());
      });
      linkCharts(root, a, sample, initView3d(panel, cursorTrack));
      note.textContent = dem
        ? 'Ground from the terrarium elevation model at zoom ' + dem.zoom + ' (' +
          dem.cols + '×' + dem.rows + ' nodes, ' + dem.min + '–' + dem.max + ' m), and ' +
          'the same grid gives the ground under the side view and the clearance figure. ' +
          heights
        : 'Ground drawn as a flat plane at ' + Math.round(a.altMin - 30) + ' m — ' +
          Math.round(a.altMin) + ' m was your lowest point, and the elevation model ' +
          'could not be fetched from here. ' + heights;
    });
  }

  function present(root, a, name, uid) {
    root.querySelector('.ql-heading').textContent = name.replace(/\.[^.]+$/, '');
    root.querySelector('.ql-source').textContent = a.kind + ', ' + a.t.length +
      ' fixes at ~' + a.median.toFixed(0) + ' s';
    // Everything measured along the track is understated on a reduced file, and by a lot:
    // the same flight read from a 500-point KMZ and from its IGC gave 476 km against
    // 623 km flown and 24 900 m against 44 900 m gained. Say so next to the numbers.
    var coarse = root.querySelector('.ql-coarse');
    if (a.median > RULES.turnResolutionLimit) {
      coarse.hidden = false;
      coarse.textContent = 'Sampled every ' + a.median.toFixed(0) + ' s. Distance flown, ' +
        'height gained and climb rates are measured along the track, so at this spacing ' +
        'they are all understated — often by a third — and turns cannot be counted. ' +
        'Straight-line and XC distances survive, because those only need the corners. ' +
        'Load the IGC from your instrument for the real numbers.';
    } else {
      coarse.hidden = true;
    }
    var hours = Math.floor(a.duration / 3600);
    var minutes = Math.round((a.duration % 3600) / 60);
    var turnTotal = a.climbs.reduce(function (sum, c) {
      return sum + (c.turns || 0);
    }, 0);
    root.querySelector('.ql-stats').innerHTML =
      tile('airtime', hours + ' h ' + (minutes < 10 ? '0' : '') + minutes + ' m', '') +
      tile('xc distance', (a.xc / 1000).toFixed(1) + ' km',
           (a.shape ? a.shape + ' · ' : '') + (a.flown / 1000).toFixed(0) +
           ' km flown, ' + (a.straight / 1000).toFixed(0) + ' km straight') +
      tile('altitude', Math.round(a.altMax) + ' m',
           'from ' + Math.round(a.altMin) + ' m, ' + (a.useBaro ? 'baro' : 'GPS')) +
      tile('height gained', Math.round(a.gained) + ' m', '') +
      tile('climbs', String(a.climbs.length),
           (a.median > RULES.turnResolutionLimit ? 'turns not resolvable' : Math.round(turnTotal) + ' turns')) +
      tile('wind', a.wind ? a.wind.ms.toFixed(1) + ' m/s' : '—',
           a.wind ? 'from ' + cardinal(a.wind.from) + ' · from circle drift' : '') +
      tile('time', Math.round(100 * a.budget.thermal / Math.max(a.duration, 1)) + '% up',
           Math.round(100 * a.budget.glide / Math.max(a.duration, 1)) + '% gliding');

    var rows = a.climbs.map(function (climb, index) {
      var turns = climb.turns === null ? '—' : climb.turns.toFixed(1);
      var perTurn = (climb.turns && climb.turns >= 0.5)
        ? Math.round(climb.gain / climb.turns) : '—';
      var m = Math.floor(climb.duration / 60), sec = Math.round(climb.duration % 60);
      return '<tr data-cursor="' + climb.start + '"><td>' + (index + 1) +
        '</td><td>' + clock(a, a.t[climb.start]) +
        '</td><td>' + m + ':' + (sec < 10 ? '0' : '') + sec +
        '</td><td>+' + Math.round(climb.gain) +
        '</td><td>' + climb.average.toFixed(2) +
        '</td><td>' + climb.best.toFixed(1) +
        '</td><td>' + turns + '</td><td>' + perTurn + '</td><td>' +
        (climb.wind ? climb.wind.ms.toFixed(1) + ' ' + cardinal(climb.wind.from) : '—') +
        '</td></tr>';
    }).join('');
    root.querySelector('.ql-table tbody').innerHTML = rows ||
      '<tr><td colspan="9">No climbs met the thresholds.</td></tr>';

    root.querySelector('.ql-glides tbody').innerHTML = a.glides.map(function (g, i) {
      var m2 = Math.floor(g.duration / 60), s2 = Math.round(g.duration % 60);
      return '<tr data-cursor="' + g.start + '"><td>' + (i + 1) + '</td><td>' +
        clock(a, a.t[g.start]) + '</td><td>' +
        m2 + ':' + (s2 < 10 ? '0' : '') + s2 + '</td><td>' + (g.distance / 1000).toFixed(1) +
        '</td><td>' + Math.round(g.height) + '</td><td>' +
        (g.ld ? g.ld.toFixed(1) : '—') + '</td><td>' + Math.round(g.speed) + '</td></tr>';
    }).join('') || '<tr><td colspan="7">No glides met the thresholds.</td></tr>';

    root.querySelector('.ql-note').textContent =
      'Quick look: phases use the same ' + WINDOW + ' s progress heuristic as the full ' +
      'analysis, and the same thresholds — this page reads them out of one payload ' +
      'rather than carrying its own copies. No basemap, and no scored triangle: those ' +
      'need the command line, which also reads the pressure altitude and the logger ' +
      'headers.' +
      (a.median > RULES.turnResolutionLimit ? ' Sampled every ' + a.median.toFixed(0) +
        ' s, too coarse to resolve a circle, so turn counts are omitted.' : '');

    drawSide(root, a);
    drawPlan(root, a);
    // After the tables, because `linkCharts` binds the rows it finds and they are
    // written above; before the meteo fetch, because that resolves whenever it resolves.
    show3d(root, a, uid, sampleIndices(a));

    // Always attempted. It was a checkbox, on the reasoning that a request which cannot
    // succeed in a published page should not be made silently — but the failure message
    // says that better than an unticked box does, and every reader wanted the weather.
    var meteoStats = root.querySelector('.ql-meteo-stats');
    meteoStats.innerHTML = '<div class="stat"><span class="key">weather</span>' +
      '<span class="stat-value" style="font-size:15px">fetching…</span></div>';
    fetchMeteo(a).then(function (m) {
      meteoStats.innerHTML =
        tile('surface', Math.round(m.temperature) + ' °C',
             'dew ' + Math.round(m.dew) + ' °C') +
        tile('cloudbase', Math.round(m.cloudbase) + ' m', 'from the spread') +
        tile('boundary layer', m.blTop ? Math.round(m.blTop) + ' m' : '—', 'model depth') +
        tile('you reached', Math.round(a.altMax) + ' m', 'highest point') +
        tile('model wind', m.wind.toFixed(1) + ' m/s',
             'from ' + cardinal(m.windFrom) + ' at 850 hPa');
    }).catch(function (error) {
      meteoStats.innerHTML = '<div class="stat"><span class="key">weather</span>' +
        '<span class="stat-value" style="font-size:15px">unavailable</span>' +
        '<span class="sub">' + (error.message || error) + '</span></div>';
    });
  }

  // The same source the CLI uses. A published artifact runs under a policy that blocks
  // every external request, so this can only succeed when the page is opened locally —
  // hence the explicit opt-in and the plain failure message.
  // `want.profile` adds the pressure levels — thirty more fields on the same one
  // request, so a report can draw the model wind profile behind its own measurements.
  // Off by default because an uploaded track has no chart to draw it in, and asking for
  // data nobody displays is a bigger answer for nothing.
  function fetchMeteo(a, want) {
    want = want || {};
    // Without a date there is no day to ask about, and asking anyway returns the weather
    // of 1 January 1970 rather than an error.
    if (!a.dated) return Promise.reject(new Error('the file carries no flight date'));
    var midLat = a.lat[Math.floor(a.lat.length / 2)];
    var midLon = a.lon[Math.floor(a.lon.length / 2)];
    var when = new Date(a.epoch * 1000);
    var day = when.toISOString().slice(0, 10);
    var ageDays = (Date.now() / 1000 - a.epoch) / 86400;
    var fields = 'temperature_2m,dew_point_2m,boundary_layer_height,' +
      'wind_speed_850hPa,wind_direction_850hPa';
    // m/s from the source. `meteo.py` asks for the same, so a wind is the same number
    // whether the report baked it in or the page fetched it.
    var units = '&wind_speed_unit=ms';
    if (want.profile) {
      RULES.pressureLevels.forEach(function (hpa) {
        fields += ',wind_speed_' + hpa + 'hPa,wind_direction_' + hpa + 'hPa' +
                  ',geopotential_height_' + hpa + 'hPa';
      });
    }
    var url;
    if (ageDays > 60) {
      url = 'https://archive-api.open-meteo.com/v1/archive?latitude=' + midLat.toFixed(3) +
        '&longitude=' + midLon.toFixed(3) + '&hourly=' + fields +
        '&start_date=' + day + '&end_date=' + day + '&timezone=UTC' + units;
    } else {
      url = 'https://api.open-meteo.com/v1/forecast?latitude=' + midLat.toFixed(3) +
        '&longitude=' + midLon.toFixed(3) + '&hourly=' + fields +
        '&past_days=' + Math.min(Math.ceil(ageDays) + 1, 92) +
        '&forecast_days=1&timezone=UTC' + units;
    }
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error('weather service returned ' + response.status);
      return response.json();
    }).then(function (payload) {
      var hourly = payload.hourly || {};
      var times = hourly.time || [];
      if (!times.length) throw new Error('no data for that date');
      var target = when.toISOString().slice(0, 13);
      var index = times.findIndex(function (stamp) { return stamp.slice(0, 13) === target; });
      if (index < 0) index = Math.floor(times.length / 2);
      var temperature = hourly.temperature_2m[index];
      var dew = hourly.dew_point_2m[index];
      if (temperature === null || temperature === undefined) {
        throw new Error('no surface data for that hour');
      }
      // The profile, where it was asked for and where the answer has one. The ERA5
      // archive returns nulls on every pressure level, so a flight older than the
      // 60-day cutoff comes back with an empty list rather than a line of zeroes —
      // which is the same distinction the 850 hPa tile makes between "calm" and
      // "not known", and it is the one that matters on a windy day.
      var levels = [];
      if (want.profile) {
        RULES.pressureLevels.forEach(function (hpa) {
          var height = hourly['geopotential_height_' + hpa + 'hPa'];
          var speed = hourly['wind_speed_' + hpa + 'hPa'];
          var from = hourly['wind_direction_' + hpa + 'hPa'];
          if (!height || !speed || !from) return;
          if (height[index] == null || speed[index] == null || from[index] == null) return;
          levels.push({ pressure: hpa, height: height[index],
                        speed: speed[index], direction: from[index] });
        });
        levels.sort(function (p, q) { return p.height - q.height; });
      }
      return {
        temperature: temperature, dew: dew,
        cloudbase: (payload.elevation || 0) + 125 * Math.max(temperature - dew, 0),
        blTop: hourly.boundary_layer_height && hourly.boundary_layer_height[index] !== null
          ? (payload.elevation || 0) + hourly.boundary_layer_height[index] : null,
        wind: hourly.wind_speed_850hPa ? hourly.wind_speed_850hPa[index] : 0,
        windFrom: hourly.wind_direction_850hPa ? hourly.wind_direction_850hPa[index] : 0,
        levels: levels
      };
    });
  }

  // Shared with the bundled flights. `render_html.py` has the same problem — a report
  // built without --meteo has no sounding — and the fix is the same request, so it is
  // exposed rather than written twice. One copy also means one place where the endpoint,
  // the 60-day archive cutoff and the cloudbase formula live.
  window.__fetchMeteo = fetchMeteo;

  // The report's own tab controller owns the strip; this only asks it to switch or to
  // add. Reimplementing the switch here was how the two got out of step.
  function tabs() { return window.__flightTabs; }

  function fail(message) {
    status.textContent = 'Could not read that file: ' + message;
    status.classList.add('is-error');
  }

  // A tab for a flight the reader added, inserted at the end of the strip so the order
  // is the order they were dropped in.
  function addTab(uid, label, meta, stat) {
    var strip = tabs() && tabs().strip;
    if (!strip) return;
    var tab = document.createElement('span');
    tab.className = 'tab';
    tab.dataset.flightTab = uid;
    var open = document.createElement('button');
    open.type = 'button';
    open.className = 'tab-open';
    open.setAttribute('aria-pressed', 'false');
    var date = document.createElement('span');
    date.className = 'tab-date';
    date.textContent = label;
    var sub = document.createElement('span');
    sub.className = 'tab-meta';
    sub.textContent = meta;
    open.appendChild(date);
    open.appendChild(sub);
    if (stat) {
      var third = document.createElement('span');
      third.className = 'tab-stat';
      third.textContent = stat;
      open.appendChild(third);
    }
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'tab-close';
    close.title = 'Remove this flight';
    close.setAttribute('aria-label', 'Remove this flight');
    close.innerHTML = '&#215;';
    tab.appendChild(open);
    tab.appendChild(close);
    strip.appendChild(tab);
  }

  function dateOf(a) {
    if (!a.dated) return 'no date';
    var when = new Date(a.epoch * 1000);
    return isFinite(when.getTime()) ? when.toISOString().slice(0, 10) : 'no date';
  }

  function handleText(text, name) {
    try {
      var track = /^\s*A|^\s*H[FO]/m.test(text.slice(0, 400)) && !/<kml/i.test(text.slice(0, 400))
        ? parseIgc(text) : parseKmlText(text);
      if (!track.fixes.length) throw new Error('no timed positions found');
      var a = analyse(track);
      status.textContent = '';
      status.classList.remove('is-error');
      var uid = 'own' + (++loaded);
      var article = template.content.firstElementChild.cloneNode(true);
      article.dataset.flightReport = uid;
      article.hidden = true;
      // After the last flight in the document, before the quicklook drop panel's own
      // article, so the reading order matches the tab order.
      var host = document.getElementById('quicklook');
      host.parentNode.insertBefore(article, host);
      present(article, a, name, uid);
      addTab(uid, dateOf(a), name.replace(/\.[^.]+$/, '').slice(0, 22),
             (a.xc / 1000).toFixed(0) + ' km' + (a.shape ? ' · ' + a.shape : ''));
      if (window.__measureScrollbar) window.__measureScrollbar();
      tabs().show(uid);
    } catch (error) {
      fail(error.message || String(error));
    }
  }
  window.__quickLook = handleText;   // the test harness calls these directly
  window.__quickLookKmz = function (buffer, name) {
    return readKmz(buffer).then(function (text) { handleText(text, name); },
                               function (error) { fail(error.message || String(error)); });
  };

  // The full analysis and the same article a bundled flight gets (`js/upload.js`), with
  // the reduced quick look below kept as the fallback should anything in it throw.
  // The spinner is on while any upload is in hand: several files can be dropped at once.
  // It is a CSS transform animation, which the compositor keeps turning while the
  // analysis holds the main thread; a JavaScript-driven one would freeze exactly then.
  var busy = 0;
  function working(on) {
    busy = Math.max(0, busy + (on ? 1 : -1));
    status.classList.toggle('is-busy', busy > 0);
    status.setAttribute('aria-busy', busy > 0 ? 'true' : 'false');
  }
  var STAGES = {
    analysing: 'Analysing {name}…',
    fetching: 'Analysed {name}; fetching the ground and the day\'s weather…',
    writing: 'Writing the article for {name}…'
  };

  function handleFull(file) {
    status.classList.remove('is-error');
    status.textContent = 'Reading ' + file.name + '…';
    working(true);
    return TV.upload.read(file).then(function (flight) {
      return TV.upload.build(flight, file.name, function (stage) {
        status.textContent = STAGES[stage].replace('{name}', file.name);
      });
    }).then(function (built) {
      TV.upload.place(built, document.getElementById('quicklook'));
      addTab(built.uid, built.label, built.meta, built.stat);
      if (window.__measureScrollbar) window.__measureScrollbar();
      tabs().show(built.uid);
      status.textContent = built.missing.length
        ? 'Analysed. Not available just now: ' + built.missing.join(', ') + '.' : '';
    }).then(function () {
      working(false);
    }, function (error) {
      working(false);
      throw error;
    });
  }

  function handleFile(file) {
    if (!file) return;
    if (window.TV && TV.upload) {
      handleFull(file).catch(function (error) {
        if (window.console) console.warn('full analysis failed, falling back to the quick look', error);
        handleQuick(file);
      });
      return;
    }
    handleQuick(file);
  }

  function handleQuick(file) {
    status.classList.remove('is-error');
    status.textContent = 'Reading ' + file.name + '…';
    if (/\.kmz$/i.test(file.name)) {
      file.arrayBuffer().then(readKmz).then(function (text) {
        handleText(text, file.name);
      }).catch(function (error) { fail(error.message || String(error)); });
      return;
    }
    file.text().then(function (text) { handleText(text, file.name); })
      .catch(function (error) { fail(error.message || String(error)); });
  }

  // Several at once: dropping a season's folder on the panel should just work. They are
  // read one at a time so the tab order matches the file order.
  function handleFiles(list) {
    var files = Array.prototype.slice.call(list || []);
    (function next() {
      var file = files.shift();
      if (!file) return;
      handleFile(file);
      if (files.length) setTimeout(next, 60);
    })();
  }

  document.getElementById('ql-pick').addEventListener('click', function () { input.click(); });
  // The "+" tab shows the drop panel; the report's tab controller has already switched to
  // it by the time this runs, so all that is left is to open the picker.
  document.querySelectorAll('.tab[data-flight-tab="own"]').forEach(function (tab) {
    tab.addEventListener('click', function () {
      input.click();
    });
  });
  input.addEventListener('change', function () { handleFiles(input.files); });
  ['dragenter', 'dragover'].forEach(function (type) {
    drop.addEventListener(type, function (event) {
      event.preventDefault();
      drop.classList.add('is-over');
    });
  });
  ['dragleave', 'drop'].forEach(function (type) {
    drop.addEventListener(type, function (event) {
      event.preventDefault();
      drop.classList.remove('is-over');
      if (type === 'drop' && event.dataTransfer && event.dataTransfer.files.length) {
        handleFiles(event.dataTransfer.files);
      }
    });
  });
})();
"""

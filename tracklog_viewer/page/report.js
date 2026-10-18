// Cross-flight comparison, opt-in.
//
// Comparing whatever happens to be open is a claim nobody asked for — three unrelated
// flights are not a set — so nothing is compared until the reader marks two or more tabs
// with the compare control. Then each marked flight's headline figures gain a line
// saying where they stand *among the flights the reader chose*.
//
// Document-level on purpose, unlike the cursor code, which is per flight: this is a fact
// about the document rather than about one article.
(function () {
  var HIGHER_IS_BETTER = { 'scored_km': true, 'mean_climb': true, 'ceiling_used': true };
  var UNITS = { 'scored_km': ' km', 'mean_climb': ' m/s', 'ceiling_used': '' };
  var chosen = {};

  function articles() {
    return Array.prototype.slice.call(
      document.querySelectorAll('[data-flight-report]'));
  }

  function valueOf(article, key) {
    var raw = article.getAttribute('data-compare-' + key.replace(/_/g, '-'));
    if (raw === null || raw === '') return null;
    var value = parseFloat(raw);
    return isNaN(value) ? null : value;
  }

  function refresh() {
    var picked = articles().filter(function (a) {
      return chosen[a.getAttribute('data-flight-report')];
    });
    articles().forEach(function (article) {
      var mine = chosen[article.getAttribute('data-flight-report')];
      article.querySelectorAll('.verdict-delta').forEach(function (slot) {
        var key = slot.parentNode.getAttribute('data-key');
        // Under two flights there is nothing to compare against, and a flight the reader
        // did not pick is not part of the comparison at all.
        if (!mine || picked.length < 2 || !key) { slot.hidden = true; return; }
        var value = valueOf(article, key);
        var others = picked.filter(function (a) { return a !== article; })
                           .map(function (a) { return valueOf(a, key); })
                           .filter(function (v) { return v !== null; });
        if (value === null || !others.length) { slot.hidden = true; return; }
        var up = HIGHER_IS_BETTER[key] !== false;
        var rival = up ? Math.max.apply(null, others) : Math.min.apply(null, others);
        var leads = up ? value >= rival : value <= rival;
        var unit = UNITS[key] || '';
        slot.hidden = false;
        slot.className = 'verdict-delta' + (leads ? ' is-best' : '');
        slot.textContent = leads
          ? 'best of ' + picked.length + ' compared'
          : (up ? '▼ ' : '▲ ') + Math.abs(value - rival).toFixed(2) + unit +
            ' off the best of ' + picked.length;
      });
    });
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest && event.target.closest('[data-compare-toggle]');
    if (!button) return;
    // The compare control lives inside the tab, which opens the flight. Without this the
    // tab would switch every time someone marked one for comparison.
    event.stopPropagation();
    // Busy until the comparison is redrawn: a second or two of work — every compared
    // flight's scene read, every map and side view redrawn — that used to start inside the
    // click, with nothing on the screen to say so, and a second click undid the first.
    if (button.classList.contains('is-busy')) return;
    var uid = button.getAttribute('data-compare-toggle');
    chosen[uid] = !chosen[uid];
    button.setAttribute('aria-pressed', chosen[uid] ? 'true' : 'false');
    button.classList.toggle('is-on', chosen[uid]);
    button.classList.add('is-busy');
    button.setAttribute('aria-busy', 'true');
    // After a frame is painted, so the spinner is on the screen before the work holds the
    // page (a CSS animation keeps turning through it).
    requestAnimationFrame(function () {
      setTimeout(function () {
        try { settle(); } finally {
          button.classList.remove('is-busy');
          button.removeAttribute('aria-busy');
        }
      }, 0);
    });
  }, true);

  // Counted from the flights still in the document: a removed flight leaves the
  // comparison, and the others' lines say "of 2" again rather than "of 3".
  function settle() {
    var count = articles().filter(function (a) {
      return chosen[a.getAttribute('data-flight-report')];
    }).length;
    document.documentElement.classList.toggle('is-comparing', count >= 2);
    refresh();
    showOthers();
  }

  // Each compared flight's 3D map draws the others too (`setOthers` in `map3d`): usually
  // the same area, often the same day. Colours from outside the climb-rate ramp the
  // flight's own track uses, so a compared track never reads as a climb. Scenes are read
  // once per flight; a map built later asks `__compareFor` itself.
  // XContest's own way of telling tracks apart: thin lines, one muted colour each — orange,
  // sky blue, brick red, indigo, olive. Bright ones shouted over the ground; the climb ramp
  // is dropped while comparing, because five climb colours a track times several tracks
  // is no way to tell them apart. A flight keeps its colour on every map.
  var OTHER_COLOURS = ['#e0893a', '#3aa8d0', '#c9483c', '#5a5fc0', '#8a9a3a'];
  var scenes = {};
  function sceneOf(article) {
    var uid = article.getAttribute('data-flight-report');
    if (scenes[uid] !== undefined) return scenes[uid];
    var node = article.querySelector('.view3d-data');
    scenes[uid] = null;
    if (node && typeof readScene === 'function') {
      try {
        var scene = readScene(node);
        scenes[uid] = { track: scene.track, start: scene.start, utcOffset: scene.utcOffset,
                        climbs: scene.climbs || [],
                        phases: scene.phases || [],
                        name: article.getAttribute('data-compare-name') || uid };
      } catch (error) { /* a flight without a scene is compared by its figures only */ }
    }
    return scenes[uid];
  }
  // The label each compared flight goes by, chosen among them: the pilot's name where the
  // pilots differ, and among one pilot's flights the day, or — the same day — the launch
  // time. Two flights from the same day were both "2026-10-11" in the map's legend.
  function compareLabels(all) {
    var info = all.map(function (a) {
      return { pilot: a.getAttribute('data-compare-pilot') || '', date: a.getAttribute('data-compare-date') || '',
               time: a.getAttribute('data-compare-time') || '',
               fallback: a.getAttribute('data-compare-name') || a.getAttribute('data-flight-report') };
    });
    var pilots = info.map(function (i) { return i.pilot; })
      .filter(function (p, k, list) { return list.indexOf(p) === k; });
    return info.map(function (i) {
      var parts = [];
      if (pilots.length > 1) parts.push(i.pilot || i.fallback);
      var same = info.filter(function (j) { return j.pilot === i.pilot; });
      if (same.length > 1) {
        var days = same.map(function (j) { return j.date; })
          .filter(function (d, k, list) { return list.indexOf(d) === k; });
        parts.push(days.length > 1 ? i.date : (i.time || i.date));
      }
      return parts.join(' \u00b7 ') || i.fallback;
    });
  }
  function picked() {
    return articles().filter(function (a) { return chosen[a.getAttribute('data-flight-report')]; });
  }
  window.__compareFor = function (uid) {
    var all = picked();
    if (all.length < 2 || !chosen[uid]) return null;
    var out = { own: null, others: [] }, labels = compareLabels(all);
    all.forEach(function (article, i) {
      var colour = OTHER_COLOURS[i % OTHER_COLOURS.length];
      var name = labels[i];
      if (article.getAttribute('data-flight-report') === uid) {
        var mine = sceneOf(article);
        out.own = { name: name, colour: colour, start: mine ? mine.start : null,
                    utcOffset: mine ? mine.utcOffset : undefined };
        return;
      }
      var scene = sceneOf(article);
      if (scene) out.others.push({ name: name, track: scene.track, start: scene.start, utcOffset: scene.utcOffset,
                                   climbs: scene.climbs, phases: scene.phases, colour: colour });
    });
    return out;
  };
  function showOthers() {
    articles().forEach(function (article) {
      var box = article.querySelector('.view3d');
      var entry = box && window.__mergedAll && window.__mergedAll[box.id];
      if (entry && entry.setOthers) entry.setOthers(window.__compareFor(article.getAttribute('data-flight-report')));
      // The side view draws the compared flights too.
      var host = article.querySelector('.chart-host[data-chart="profile"]');
      if (host && window.__drawProfile) window.__drawProfile(article);
    });
  }
  // Flights come and go (uploads, the × on a tab); re-settle when they do.
  var holder = document.querySelector('[data-flight-report]');
  if (holder && window.MutationObserver) {
    new MutationObserver(settle).observe(holder.parentNode, { childList: true });
  }
})();

// Resolves when `element` is first on screen: now if it already is, else when it comes
// into view (the flight tabs toggle `hidden`). An IntersectionObserver, not a watch on
// every attribute in the page: that one ran — and laid the page out — on each move of
// the chart cursor, once for every flight not yet opened.
function whenShown(element) {
  function shown() { return element.getClientRects().length > 0; }
  if (shown()) return Promise.resolve();
  return new Promise(function (resolve) {
    if (window.IntersectionObserver) {
      var seen = new IntersectionObserver(function (entries) {
        if (entries.some(function (e) { return e.isIntersecting; }) || shown()) {
          seen.disconnect(); resolve();
        }
      });
      seen.observe(element);
      return;
    }
    var watch = new MutationObserver(function () {
      if (shown()) { watch.disconnect(); resolve(); }
    });
    watch.observe(document.body, { attributes: true, subtree: true,
                                   attributeFilter: ['hidden', 'class', 'style'] });
  });
}

// ---- the airspace against the track ------------------------------------------------
// The report's Airspace section, from what the map measured once it had the zones
// (`airspaceAlong`, `parainsights_map.view3d`): cards for what was entered and what came
// closest, the height over time with each zone's floor and top drawn where the track was
// over its ground, and a row per nearby zone with a way to it on the map. Nothing
// nearby, a note that says so. Measurements, not verdicts: no zone is called an
// infringement here that its limits do not make one, and a pass under a floor is not.
function aspEsc(text) {
  return String(text).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}
function aspMetres(m) { return String(Math.round(m)).replace(/\B(?=(\d{3})+(?!\d))/g, ' '); }
function aspClock(along, t) {
  if (!along.start) {
    var e = Math.floor(t / 60);
    return '+' + Math.floor(e / 60) + ':' + ('0' + e % 60).slice(-2);
  }
  var d = new Date((along.start + along.offset + t) * 1000);
  return ('0' + d.getUTCHours()).slice(-2) + ':' + ('0' + d.getUTCMinutes()).slice(-2);
}
// How long, in the unit that says it: a ten-second clip of a zone's corner is not "1 min".
function aspDuration(seconds, short) {
  if (seconds < 60) {
    var s = Math.max(1, Math.round(seconds));
    return s + (short ? ' s' : s === 1 ? ' second' : ' seconds');
  }
  var m = Math.round(seconds / 60);
  return m + (short ? ' min' : m === 1 ? ' minute' : ' minutes');
}
// What came closest, in a few words: the table's chip and the second card.
function aspClosest(zone) {
  if (zone.closest === 'inside') {
    return 'Inside ' + aspDuration(zone.inside.seconds, true) + ' · ' + aspMetres(zone.inside.depth) + ' m in';
  }
  if (zone.closest === 'under') return aspMetres(zone.under.m) + ' m under the floor';
  if (zone.closest === 'over') return aspMetres(zone.over.m) + ' m over the top';
  return (zone.beside.m / 1000).toFixed(1) + ' km to the side';
}
// The zone's class as openAIP gives it (`ac`), in words a pilot reads: "TMA D", "class E",
// "restricted". And whether being inside needs a clearance or is barred: classes A-D,
// restricted, prohibited and reserved areas, aerodrome zones. Inside class E or G, a
// radio or transponder zone or a circuit is flown legally every day, and is not marked
// as if it were not.
var ASP_LETTERS = { R: 'restricted', P: 'prohibited', D: 'danger area' };
function aspClass(zone) {
  var c = zone.cls;
  if (!c) return '';
  return ASP_LETTERS[c] || c.replace(/^Other /, 'class ');
}
function aspBarred(zone) {
  var c = zone.cls || '';
  if (zone.kind === 'restricted') return /^(R|P|TRA|TSA|MTA|Overflight restriction)$/.test(c);
  if (zone.kind === 'atz') return true;
  if (/^(RMZ|TMZ|TIZ|TIA)\b/.test(c)) return false;
  return /(^| )[A-D]$/.test(c) || /^(CTR|TMA|CTA|MCTR)$/.test(c);
}
function aspLimits(zone) {
  if (zone.limits) return zone.limits;
  var r = zone.ring;
  return (r.g ? 'GND' : aspMetres(r.f) + ' m') + ' – ' + (r.t ? 'unlimited' : aspMetres(r.c) + ' m');
}
function aspChart(along, width) {
  var pr = along.profile, n = pr.t.length;
  if (n < 2) return '';
  var h = width < 560 ? 210 : 250, left = 54, right = 8, top = 10, bottom = 26;
  var t0 = pr.t[0], t1 = pr.t[n - 1], high = 0;
  pr.alt.forEach(function (a) { high = Math.max(high, a); });
  along.zones.forEach(function (z) {
    z.spans.forEach(function (sp) { if (isFinite(sp.floor)) high = Math.max(high, sp.floor + 150); });
  });
  var stepY = high > 3000 ? 1000 : 500;
  high = Math.ceil(high * 1.08 / stepY) * stepY;
  function x(t) { return left + (t - t0) / Math.max(1, t1 - t0) * (width - left - right); }
  function y(a) { return top + (1 - Math.max(0, Math.min(a, high)) / high) * (h - top - bottom); }
  var out = [];
  for (var a = 0; a <= high; a += stepY) {
    out.push('<line class="asp-grid" x1="' + left + '" x2="' + (width - right) + '" y1="' + y(a) + '" y2="' + y(a) + '"/>' +
             '<text class="asp-axis" x="' + (left - 6) + '" y="' + (y(a) + 4) + '" text-anchor="end">' + aspMetres(a) + '</text>');
  }
  var ticks = Math.max(2, Math.floor((width - left - right) / 110));
  for (var i = 0; i <= ticks; i++) {
    var tt = t0 + (t1 - t0) * i / ticks;
    out.push('<text class="asp-axis" x="' + x(tt) + '" y="' + (h - 6) + '" text-anchor="' +
             (i === 0 ? 'start' : i === ticks ? 'end' : 'middle') + '">' + aspClock(along, tt) + '</text>');
  }
  var ground = 'M' + x(t0) + ' ' + y(0);
  pr.t.forEach(function (t, k) { ground += 'L' + x(t).toFixed(1) + ' ' + y(pr.ground[k]).toFixed(1); });
  out.push('<path class="asp-ground" d="' + ground + 'L' + x(t1) + ' ' + y(0) + 'Z"/>');
  // Each zone's box where the track was over its ground, labelled once, over its widest.
  along.zones.forEach(function (z) {
    var colour = along.colours[z.kind] || '#888888', widest = null;
    z.spans.forEach(function (sp) {
      var x0 = x(sp.t0), x1 = Math.max(x(sp.t1), x0 + 2);
      var yTop = isFinite(sp.top) ? y(sp.top) : top, yFloor = y(sp.floor);
      out.push('<rect class="asp-zone" x="' + x0.toFixed(1) + '" y="' + yTop.toFixed(1) + '" width="' + (x1 - x0).toFixed(1) +
               '" height="' + Math.max(1, yFloor - yTop).toFixed(1) + '" style="fill:' + colour + ';stroke:' + colour + '"/>');
      if (!widest || sp.t1 - sp.t0 > widest.t1 - widest.t0) widest = sp;
    });
    if (widest) {
      out.push('<text class="asp-zone-name" x="' + (x(widest.t0) + 4) + '" y="' + ((isFinite(widest.top) ? y(widest.top) : top) + 16) +
               '" style="fill:' + colour + '">' + aspEsc(z.name) + '</text>');
    }
  });
  var line = '', red = '', was = false;
  pr.t.forEach(function (t, k) {
    var pt = x(t).toFixed(1) + ' ' + y(pr.alt[k]).toFixed(1);
    line += (k ? 'L' : 'M') + pt;
    if (pr.inside[k]) { red += (was ? 'L' : 'M') + pt; }
    was = pr.inside[k];
  });
  out.push('<path class="asp-track" d="' + line + '"/>');
  if (red) out.push('<path class="asp-inside" d="' + red + '"/>');
  // The closest misses, marked where they were.
  along.zones.forEach(function (z) {
    if (z.closest === 'inside' || !z.at) return;
    var cx = x(z.at.t), cy = y(z.at.alt);
    out.push('<circle class="asp-mark" cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="4"/>');
  });
  return '<svg class="asp-side" viewBox="0 0 ' + width + ' ' + h + '" width="' + width + '" height="' + h +
         '" role="img" aria-label="Height over time against the zones over the track">' + out.join('') + '</svg>';
}
function renderAirspaceAlong(section, along, show) {
  var body = section.querySelector('.asp-body');
  if (!body) return;
  section.hidden = false;
  if (along.status !== 'ok' || !along.zones.length) {
    body.innerHTML = '<p class="note asp-none">' + (along.status === 'failed' ? 'The airspace could not be loaded.'
      : along.status === 'uncovered' ? 'No airspace data here: only Europe is covered.'
      : 'No airspace in the vicinity.') + '</p>';
    return;
  }
  // The zones entered first, in the order they were entered, then the near misses in the
  // map's order (closest first).
  var zones = along.zones.map(function (z, i) { return [z, i]; }).sort(function (a, b) {
    var ia = a[0].inside, ib = b[0].inside;
    if (ia && ib) return ia.from - ib.from || a[1] - b[1];
    return (ia ? 0 : 1) - (ib ? 0 : 1) || a[1] - b[1];
  }).map(function (pair) { return pair[0]; });
  var entered = zones.filter(function (z) { return z.inside; });
  var misses = zones.filter(function (z) { return !z.inside; });
  var cards = [];
  if (entered.length) {
    var e = entered[0];
    cards.push('<div class="card"><b>' + entered.length + (entered.length === 1 ? ' zone' : ' zones') + '</b><span>Entered: ' +
      aspEsc(e.name) + ', for ' + aspDuration(e.inside.seconds) + ', up to ' + aspMetres(e.inside.depth) + '&nbsp;m inside' +
      (entered.length > 1 ? ', and ' + (entered.length - 1) + ' more' : '') + '<small>' + aspClock(along, e.inside.from) +
      ' – ' + aspClock(along, e.inside.to) + ', between ' + aspMetres(e.inside.low) + ' and ' + aspMetres(e.inside.high) + ' m.</small></span></div>');
  } else {
    cards.push('<div class="card"><b>None</b><span>No zone entered<small>Passing under a zone’s floor is not entering it.</small></span></div>');
  }
  if (misses.length) {
    var m = misses[0], what = m.closest === 'under' ? 'Closest under a floor' : m.closest === 'over' ? 'Closest over a top' : 'Closest beside';
    var value = m.closest === 'beside' ? (m.beside.m / 1000).toFixed(1) + '&nbsp;km' : aspMetres(m[m.closest].m) + '&nbsp;m';
    cards.push('<div class="card"><b>' + value + '</b><span>' + what + ': ' + aspEsc(m.name) + ' (' + aspEsc(aspLimits(m)) + ')<small>At ' +
      aspClock(along, m.at.t) + ', ' + aspMetres(m.at.alt) + ' m.</small></span></div>');
  }
  var notIn = misses.length + along.others;
  if (notIn) {
    cards.push('<div class="card"><b>' + notIn + (notIn === 1 ? ' zone' : ' zones') + '</b><span>Over or beside the flight, not entered' +
      (entered.length ? '<small>Passing under a zone’s floor is not entering it.</small>' : '') + '</span></div>');
  }
  var rows = zones.map(function (z, i) {
    var chip = z.closest === 'inside' ? (aspBarred(z) ? 'asp-in' : 'asp-near')
      : (z.closest === 'beside' ? z.beside.m > 1000 : z[z.closest].m > 250) ? 'asp-clear' : 'asp-near';
    var cls = aspClass(z);
    var when = z.inside ? aspClock(along, z.inside.from) + '–' + aspClock(along, z.inside.to) : aspClock(along, z.at.t);
    var at = z.inside ? aspMetres(z.inside.low) + '–' + aspMetres(z.inside.high) + ' m' : aspMetres(z.at.alt) + ' m';
    return '<tr><td class="zone"><i style="background:' + (along.colours[z.kind] || '#888888') + '"></i>' + aspEsc(z.name) +
      (cls ? ' <small class="asp-class">' + aspEsc(cls) + '</small>' : '') + '</td>' +
      '<td class="asp-limits">' + aspEsc(aspLimits(z)) + '</td><td><span class="asp-chip ' + chip + '">' + aspClosest(z) + '</span></td>' +
      '<td class="asp-when">' + when + '</td><td class="asp-at">' + at + '</td>' +
      '<td><button type="button" class="lnk asp-show" data-asp-zone="' + i + '">Show on map</button></td></tr>';
  });
  if (along.others) {
    rows.push('<tr class="asp-more"><td colspan="6">+ ' + along.others + ' more on the map, none within 500 m above or below or 2 km beside</td></tr>');
  }
  body.innerHTML = '<div class="context">' + cards.join('') + '</div>' +
    '<div class="panel asp-chart"></div>' +
    '<div class="panel"><div class="table-scroll"><table class="table-asp"><thead><tr><th>Zone</th><th>Limits</th>' +
    '<th>Closest</th><th>When</th><th>At</th><th></th></tr></thead><tbody>' + rows.join('') + '</tbody></table></div></div>';
  var chart = body.querySelector('.asp-chart'), drawnAt = 0;
  function draw() {
    var width = Math.round(chart.clientWidth - 2 * parseFloat(getComputedStyle(chart).paddingLeft || 0));
    if (width < 50 || width === drawnAt) return;
    drawnAt = width;
    chart.innerHTML = aspChart(along, width);
  }
  draw();
  if (typeof ResizeObserver === 'function') new ResizeObserver(draw).observe(chart);
  body.querySelectorAll('[data-asp-zone]').forEach(function (button) {
    button.addEventListener('click', function () { show(zones[Number(button.dataset.aspZone)]); });
  });
}

function initFlight(root) {
  var payload = root.querySelector('.cursor-data');
  var tip = document.getElementById('tip');
  if (!tip || !payload) return;
  var data = JSON.parse(payload.textContent);
  // The ground is fetched by the page (`terrain.to_remote`), so the view arrives once it
  // has; every use of `terrainView` below is in a handler that runs after that. And only
  // once the flight is first shown: each 3D view fetches its own ground and imagery and
  // holds a WebGL context, and a page of three flights was starting all three on arrival
  // for the one the reader sees — 600 requests and most of the page's memory.
  var terrainView = null;
  // The scored route, for the map to draw while it looks straight down (`setScored` in
  // `map3d`): the chart payload names the route's fixes, the cursor data where they are.
  var mapPanel = root.querySelector('.view3d-panel');
  if (mapPanel && data.cursor3d) {
    mapPanel.addEventListener('merged-ready', function (event) {
      var entry = event.detail, charts = root.querySelector('.chart-data');
      if (!entry || !entry.setScored || !charts) return;
      try {
        var route = JSON.parse(charts.textContent).route || [];
        entry.setScored(route.map(function (i) { return [data.cursor3d.lon[i], data.cursor3d.lat[i]]; }));
      } catch (error) { /* no route, nothing to draw */ }
    });
  }
  // The map's own controls (`map3d`'s entry), for the Airspace section's way to a zone.
  var mapEntry = null;
  if (mapPanel) mapPanel.addEventListener('merged-ready', function (event) { mapEntry = event.detail || null; });
  var aspSection = root.querySelector('[data-airspace-along]');
  if (aspSection) {
    root.addEventListener('airspace-along', function (event) {
      renderAirspaceAlong(aspSection, event.detail, function (zone) {
        // The moment on every chart and the map, pinned as a debrief card's is, and the
        // zone shown as well as the map's airspace menu can show it.
        if (zone.at && data.t && data.t.length) {
          var lo = 0, hi = data.t.length - 1;
          while (lo < hi) { var mid = (lo + hi) >> 1; if (data.t[mid] < zone.at.t) lo = mid + 1; else hi = mid; }
          var view = visibleView();
          if (view) pinAt(lo, view);
          if (terrainView && terrainView.revealTime) terrainView.revealTime(data.t[lo]);
        }
        if (mapEntry && mapEntry.focusAirspace) {
          mapEntry.focusAirspace(zone.ring, zone.at ? [zone.at.lon, zone.at.lat] : null);
        }
        var map = root.querySelector('.view3d');
        if (map) map.scrollIntoView({ block: 'center', behavior: 'smooth' });
      });
    });
  }
  if (typeof initView3dWhenReady === 'function') {
    whenShown(root).then(function () {
      return initView3dWhenReady(root, data.cursor3d || null);
    }).then(function (handle) {
      terrainView = handle;
      // The map draws from the panel's handle (`render_map`, `map3d`).
      var host = root.querySelector('.renderer-host');
      if (handle && host && window.__openMap) window.__openMap(host);
    }, function () {});
  }

  // Every chart that can host the cursor publishes its own projected sample
  // coordinates on its hit rect, so one index drives a dot in all of them and
  // none of the projection maths is repeated here.
  //
  // Rebuilt rather than collected once, because the side view is now *drawn* in the page
  // and the axis toggle replaces its SVG: the views array would otherwise still point at
  // an element that is no longer in the document. Listeners are bound per hit rect and
  // only once — a replaced SVG takes its own listeners with it, and the charts that
  // survived must not collect a second copy.
  var views = [];
  function collectViews() {
    views = [];
    lit = undefined;   // a redrawn chart has lost its lit bands
    root.querySelectorAll('.hit[data-px]').forEach(function (hit) {
      if (!hit.dataset.px) return;
      var svg = hit.ownerSVGElement;
      views.push({
        svg: svg,
        hit: hit,
        mode: hit.dataset.mode || 'x',
        px: hit.dataset.px.split(',').map(Number),
        py: hit.dataset.py.split(',').map(Number),
        cursor: svg.querySelector('.cursor'),
        dot: svg.querySelector('.cursor-dot'),
        crosshair: svg.querySelector('.crosshair')
      });
    });
    views.forEach(bindView);
    if (range) drawRange();
  }

  function svgPoint(view, event) {
    var box = view.svg.getBoundingClientRect();
    var vb = view.svg.viewBox.baseVal;
    return {
      x: (event.clientX - box.left) / box.width * vb.width,
      y: (event.clientY - box.top) / box.height * vb.height,
      box: box,
      vb: vb
    };
  }

  function nearestIndex(view, point) {
    var best = 0;
    var bestDistance = Infinity;
    for (var i = 0; i < view.px.length; i++) {
      var dx = view.px[i] - point.x;
      // A profile or barogram is a function of x, so judging on x alone keeps the
      // cursor on the fix under the pointer even where the trace doubles back.
      var d = view.mode === 'xy' ? dx * dx + (view.py[i] - point.y) * (view.py[i] - point.y)
                                 : dx * dx;
      if (d < bestDistance) { bestDistance = d; best = i; }
    }
    return best;
  }

  function place(index, source, point) {
    // Everything read before anything is written: a read after a write makes the browser
    // lay the page out again, and this runs on every move of the pointer. The tooltip's
    // size is the last one's — its text changes, its size by a few pixels at most.
    var drawn = views.filter(function (view) {
      // A hidden profile variant must not be drawn on: it has no layout box.
      return index < view.px.length && view.svg.getClientRects().length;
    });
    var tipBox = tip.classList.contains('on') ? tip.getBoundingClientRect() : null;
    drawn.forEach(function (view) {
      var x = view.px[index];
      var y = view.py[index];
      if (view.dot) { view.dot.setAttribute('cx', x); view.dot.setAttribute('cy', y); }
      if (view.crosshair) {
        view.crosshair.setAttribute('x1', x);
        view.crosshair.setAttribute('x2', x);
      }
      if (view.cursor) view.cursor.classList.add('on');
    });

    tip.innerHTML =
      '<div class="t-time">' + data.clock[index] + '</div>' +
      '<div class="t-row">' + data.alt[index] + ' m AMSL' +
      (data.agl ? ' &middot; ' + Math.max(0, data.agl[index]) + ' m AGL' : '') + '</div>' +
      '<div class="t-row">' + (data.climb[index] > 0 ? '+' : '') + data.climb[index].toFixed(1) + ' m/s &middot; ' +
      data.speed[index] + ' km/h &middot; ' + data.phase[index] + '</div>';
    if (terrainView) terrainView.setCursor(index);
    tip.classList.add('on');
    var pageX = point.box.left + source.px[index] / point.vb.width * point.box.width;
    var pageY = point.box.top + source.py[index] / point.vb.height * point.box.height;
    // In full screen (or the in-page maximise) the map block is all there is on screen, and
    // a tooltip left in the page under it is never seen: it moves into the block, which
    // sits at the viewport's corner, so it is placed without the page's scroll.
    // (The full-screen element is inside this flight's article, not around it.)
    var full = document.fullscreenElement && root.contains(document.fullscreenElement)
      ? document.fullscreenElement : root.querySelector('.flight-map.is-maximised');
    var into = full || document.body;
    if (tip.parentNode !== into) {
      into.appendChild(tip);
      tipBox = null;
    }
    if (!tipBox || !tipBox.width) tipBox = tip.getBoundingClientRect();
    // Measured in the screen's pixels, placed in the page's: aA zooms the page an eighth,
    // and a tooltip placed in screen pixels landed an eighth further right, off the edge.
    var zoom = document.body.getBoundingClientRect().width / (document.body.offsetWidth || 1) || 1;
    var left = Math.max(Math.min(pageX + 14, window.innerWidth - tipBox.width - 10), 10);
    tip.style.left = (left + (full ? 0 : window.scrollX)) / zoom + 'px';
    tip.style.top = (pageY - tipBox.height - 12 + (full ? 0 : window.scrollY)) / zoom + 'px';
    highlight(data.segment[index]);
  }

  function clearMarker() {
    views.forEach(function (view) {
      if (view.cursor) view.cursor.classList.remove('on');
    });
    tip.classList.remove('on');
    if (terrainView) terrainView.clearCursor();
    highlight(null);
  }

  // A click pins the moment; hover alone is only a preview.
  //
  // Hover is the right default — sweep a chart and the map keeps up — but on its own it
  // takes the marker away at exactly the moment the reader wants it: they have found
  // something, and now they want to look at the 3D view, or read the row in the table, or
  // point at the screen. Both the chart hover and the debrief's "show me" had that fault,
  // and "show me" had it worse, because it is a deliberate act that any stray mouse
  // movement then undid.
  //
  // So: a click pins. Hovering still previews and moves the marker; leaving the chart
  // returns to the pinned point rather than clearing; and the pin lets go on a second
  // click, on Escape, or after PIN_IDLE_MS with no interaction with this flight at all.
  // The timeout is re-armed by any hover, so it expires after the reader has stopped
  // looking rather than while they are still reading.
  var PIN_IDLE_MS = 30000;
  var pinned = null;
  var pinTimer = null;

  function armPin() {
    if (pinTimer) { clearTimeout(pinTimer); pinTimer = null; }
    if (pinned !== null) pinTimer = setTimeout(release, PIN_IDLE_MS);
  }

  function release() {
    if (pinTimer) { clearTimeout(pinTimer); pinTimer = null; }
    pinned = null;
    root.classList.remove('is-pinned');
    clearMarker();
  }

  // The view a marker should be positioned from: `place` skips a chart with no layout
  // box, so a hidden profile variant would leave the tooltip placed against nothing.
  function visibleView() {
    for (var i = 0; i < views.length; i++) {
      if (views[i].svg.getClientRects().length) return views[i];
    }
    return null;
  }

  function markAt(index, view) {
    view = view || visibleView();
    if (!view) return false;
    index = Math.max(0, Math.min(index, view.px.length - 1));
    place(index, view,
          { box: view.svg.getBoundingClientRect(), vb: view.svg.viewBox.baseVal });
    return true;
  }

  // Pin, and bring the moment into view in the 3D panel as well — a pinned point the
  // reader cannot see on the map answers half the question they asked.
  function pinAt(index, view) {
    if (!markAt(index, view)) return;
    pinned = index;
    root.classList.add('is-pinned');
    if (terrainView && terrainView.revealCursor) terrainView.revealCursor(index);
    armPin();
  }

  function restore() {
    if (pinned === null) { clearMarker(); return; }
    markAt(pinned);
    armPin();
  }

  function bindView(view) {
    if (view.hit.__cursorBound) return;
    view.hit.__cursorBound = true;
    function show(event) {
      var point = svgPoint(view, event);
      place(nearestIndex(view, point), view, point);
      armPin();
    }
    view.hit.addEventListener('mousemove', show);
    view.hit.addEventListener('mouseleave', restore);
    view.hit.addEventListener('click', function (event) {
      var point = svgPoint(view, event);
      var index = nearestIndex(view, point);
      // Clicking the pinned point again is how the reader lets go without hunting for a
      // key, so the same click both pins and unpins.
      if (pinned === index) release(); else pinAt(index, view);
    });
    view.hit.addEventListener('touchmove', function (event) {
      if (event.touches.length) { show(event.touches[0]); event.preventDefault(); }
    }, { passive: false });
  }

  collectViews();
  // How a redrawn chart gets back into the cursor. `page/charts.js` calls this after
  // the axis toggle rebuilds the side view; without it the toggle silently produces a
  // chart the cursor cannot drive, which looks exactly like the cursor being broken.
  // After a redraw (a comparison, a new shape) the replay's bar and window go back on.
  root.__relinkCharts = function () { collectViews(); if (range) drawRange(); };
  // The 3D map's replay drives the charts (`map3d`, `setTime`): its "now", in seconds
  // since the first fix, as the cursor on the side and top views. Quiet — no tooltip, and
  // not back to the map, which is showing the replay already.
  root.__cursorAtTime = function (t) {
    if (!data.t || !data.t.length) return;
    var lo = 0, hi = data.t.length - 1;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (data.t[mid] < t) lo = mid + 1; else hi = mid; }
    if (lo > 0 && Math.abs(data.t[lo - 1] - t) < Math.abs(data.t[lo] - t)) lo--;
    // No check that each chart has a layout box, as `place` makes for its tooltip: an
    // attribute on a hidden one costs nothing, and asking, after this frame's writes,
    // made the browser lay the page out on every frame of the replay.
    views.forEach(function (view) {
      if (lo >= view.px.length) return;
      if (view.dot) { view.dot.setAttribute('cx', view.px[lo]); view.dot.setAttribute('cy', view.py[lo]); }
      if (view.crosshair) { view.crosshair.setAttribute('x1', view.px[lo]); view.crosshair.setAttribute('x2', view.px[lo]); }
      if (view.cursor) view.cursor.classList.add('on');
    });
    highlight(data.segment[lo]);
  };

  // The 3D replay's window (`map3d`, `showRange`) on the side view: a bar at its "now"
  // (the right handle), and — once the left handle has been moved off the start — what
  // lies outside the two handles dimmed, so the slider's choice reads against the whole
  // day. Seconds since this flight's first fix, as `__cursorAtTime`; null when the replay
  // closes.
  //
  // Placed by time along the axis, not by this flight's own samples: compared flights
  // from the same day share the axis and can fly on after this one has landed, and a
  // window clamped to this flight's last fix dimmed everything after its landing while
  // the others were still in the air.
  var range = null;
  function drawRange() {
    views.forEach(function (view) {
      if (view.mode !== 'x') return;
      var shade = view.svg.querySelector('.replay-range');
      var n = Math.min(view.px.length, data.t ? data.t.length : 0);
      if (!range || n < 2) { if (shade) shade.remove(); return; }
      var t0 = data.t[0], t1 = data.t[n - 1];
      var x0 = view.px[0], x1 = view.px[n - 1];
      var box = +view.hit.getAttribute('x'), w = +view.hit.getAttribute('width');
      function xAt(t) {
        var x = t1 > t0 ? x0 + (t - t0) / (t1 - t0) * (x1 - x0) : x0;
        return Math.min(Math.max(x, box), box + w);
      }
      var left = xAt(range[0]), right = xAt(range[1]);
      var y = view.hit.getAttribute('y'), h = view.hit.getAttribute('height');
      if (!shade) {
        var NS = 'http://www.w3.org/2000/svg';
        shade = document.createElementNS(NS, 'g');
        shade.setAttribute('class', 'replay-range');
        ['before', 'after'].forEach(function () {
          var r = document.createElementNS(NS, 'rect');
          r.setAttribute('class', 'replay-dim');
          r.setAttribute('y', y);
          r.setAttribute('height', h);
          shade.appendChild(r);
        });
        var bar = document.createElementNS(NS, 'line');
        bar.setAttribute('class', 'replay-now');
        bar.setAttribute('y1', y);
        bar.setAttribute('y2', +y + +h);
        shade.appendChild(bar);
        view.svg.insertBefore(shade, view.cursor || view.hit);
      }
      var dims = shade.querySelectorAll('.replay-dim'), dim = !!range[2];
      dims[0].setAttribute('x', box);
      dims[0].setAttribute('width', dim ? Math.max(left - box, 0) : 0);
      dims[1].setAttribute('x', right);
      dims[1].setAttribute('width', dim ? Math.max(box + w - right, 0) : 0);
      var now = shade.querySelector('.replay-now');
      now.setAttribute('x1', right);
      now.setAttribute('x2', right);
    });
  }
  root.__rangeAtTime = function (span) {
    range = span ? [span[0], span[1], !!span[2]] : null;
    drawRange();
  };

  // Escape lets go from anywhere, which is the one shortcut a reader will guess.
  root.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && pinned !== null) { release(); event.preventDefault(); }
  });

  // "show me" on a debrief card drives the cursor the charts already share, rather than
  // scrolling to a section and hoping. That is what makes the card a measurement *plus a
  // link*: the sentence names a moment, and the button puts the marker on it in the side
  // view, the top view and the 3D view at once.
  //
  // Scoped to `root` like everything else here — a document holds several flights, and a
  // document-level query would move another flight's cursor.
  root.querySelectorAll('[data-finding-cursor]').forEach(function (button) {
    button.addEventListener('click', function () {
      var index = parseInt(button.getAttribute('data-finding-cursor'), 10);
      if (isNaN(index)) return;
      var view = visibleView();
      if (!view) return;
      // Pinned rather than merely placed. "Show me" is a deliberate act, and it used to
      // be undone by the reader's own mouse on its way to look at what had been shown.
      pinAt(index, view);
      // The replay's window moved to the moment if it lies outside it (`map3d`).
      if (terrainView && terrainView.revealTime && data.t && data.t[index] !== undefined) {
        terrainView.revealTime(data.t[index]);
      }
      view.svg.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  });

  // The segment lit last: hovering along one climb or glide asks for the same rows on
  // every move, and each time they were all found again and switched off and on.
  var lit;
  function highlight(key) {
    if (key === lit) return;
    lit = key;
    // Scoped to this flight: with several flights in one document, a global query
    // would light up the matching segment index in every other flight too.
    root.querySelectorAll('.band.active, .mark.active, .wind-point.active, tr.active')
      .forEach(function (node) { node.classList.remove('active'); });
    if (key === null || key === undefined) return;
    root.querySelectorAll('[data-segment="' + key + '"]')
      .forEach(function (node) { node.classList.add('active'); });
  }

  // The circling columns fold away by default. A single button rather than a two-state
  // pair, because there is nothing to compare against: it is showing five extra columns
  // or not showing them.
  root.querySelectorAll('.toggle-button[data-detail]').forEach(function (button) {
    button.addEventListener('click', function () {
      var on = button.getAttribute('aria-pressed') !== 'true';
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      button.classList.toggle('is-on', on);
      root.querySelectorAll('.table-climbs').forEach(function (table) {
        table.classList.toggle('show-circling', on);
      });
    });
  });

  // The glides table shows the longest few; this unfolds the rest, in flight order.
  root.querySelectorAll('[data-show-all]').forEach(function (button) {
    var label = button.textContent;
    button.addEventListener('click', function () {
      var open = button.getAttribute('aria-expanded') !== 'true';
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
      button.textContent = open ? 'Show the longest only' : label;
      var table = button.parentNode.querySelector('.table-glides');
      if (table) table.classList.toggle('show-all', open);
    });
  });

  root.querySelectorAll('.toggle-button[data-circles]').forEach(function (button) {
    button.addEventListener('click', function () {
      var wanted = button.dataset.circles;
      root.querySelectorAll('.toggle-button[data-circles]').forEach(function (other) {
        var on = other === button;
        other.classList.toggle('is-on', on);
        other.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      root.querySelectorAll('.chart-plan').forEach(function (chart) {
        chart.classList.toggle('circles-by-rate', wanted === 'rate');
      });
    });
  });

  // The tables are the third way into the same moment. Hovering a row lights the matching
  // band and mark, which it always did; clicking one now pins the cursor to where that
  // climb or glide began, in both charts and on the 3D map — the reader had a row in
  // front of them and no way to ask where on the ground it happened.
  //
  // `data-cursor` is a position in the sampled arrays the charts are drawn over, mapped
  // from the segment's fix index when the article is written (`js/report.js`), exactly as
  // a finding's cursor is. A row
  // without one (a table built with no sample) simply stays hover-only.
  root.querySelectorAll('tr[data-segment]').forEach(function (row) {
    row.tabIndex = 0;
    row.addEventListener('mouseenter', function () { highlight(row.dataset.segment); });
    row.addEventListener('focus', function () { highlight(row.dataset.segment); });
    row.addEventListener('mouseleave', function () {
      if (pinned === null) highlight(null); else restore();
    });
    row.addEventListener('blur', function () {
      if (pinned === null) highlight(null); else restore();
    });

    var at = parseInt(row.dataset.cursor, 10);
    if (isNaN(at)) return;
    row.classList.add('is-linked');
    function go() {
      if (pinned === at) release(); else pinAt(at);
    }
    row.addEventListener('click', go);
    row.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') { go(); event.preventDefault(); }
    });
  });
}

document.querySelectorAll('[data-flight-report]').forEach(initFlight);

// One controller for the whole tab strip, delegated from the strip itself, because tabs
// are added and removed at runtime: a listener attached per tab at load would miss every
// flight the reader drops in later.
var flightTabs = (function () {
  var strip = document.getElementById('flight-tabs');
  var firstTitle = document.title;

  function show(key) {
    document.querySelectorAll('.tab[data-flight-tab]').forEach(function (tab) {
      var on = tab.dataset.flightTab === key;
      tab.classList.toggle('is-on', on);
      var open = tab.querySelector('.tab-open');
      if (open) open.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    var titled = null;
    document.querySelectorAll('[data-flight-report]').forEach(function (report) {
      report.hidden = report.dataset.flightReport !== key;
      if (!report.hidden && report.dataset.title) titled = report.dataset.title;
    });
    // The tab's flight names the page (a browser tab, a bookmark, the history); the drop
    // panel, with no flight yet, says what it is for.
    document.title = titled || (key === 'own' ? 'Your track — parainsights' : firstTitle);
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  function remove(key) {
    var tab = strip.querySelector('.tab[data-flight-tab="' + key + '"]');
    var report = document.querySelector('[data-flight-report="' + key + '"]');
    var wasOn = tab && tab.classList.contains('is-on');
    if (tab) tab.parentNode.removeChild(tab);
    if (report) {
      // Drop the 3D map and handle this article owned: the handle holds a DEM grid, so
      // leaving it in the registry keeps a removed flight's memory, and a WebGL context
      // is scarcer still — a page gets about sixteen — so it is handed back rather than
      // left for the collector.
      report.querySelectorAll('.renderer-host').forEach(function (host) {
        if (host.__map) { host.__map.api.dispose(); host.__map = null; }
      });
      report.querySelectorAll('.view3d').forEach(function (box) {
        if (window.__view3dAll) delete window.__view3dAll[box.id];
        if (window.__mergedAll) delete window.__mergedAll[box.id];
      });
      report.parentNode.removeChild(report);
    }
    if (!wasOn) return;
    // Fall back to the first flight still in the document, or to the drop panel.
    var next = strip.querySelector('.tab[data-flight-tab]:not(.tab-add)');
    show(next ? next.dataset.flightTab : 'own');
  }

  if (strip) {
    strip.addEventListener('click', function (event) {
      var tab = event.target.closest('.tab[data-flight-tab]');
      if (!tab) return;
      if (event.target.closest('.tab-close')) remove(tab.dataset.flightTab);
      else show(tab.dataset.flightTab);
    });
  }
  return { show: show, remove: remove, strip: strip };
})();
window.__flightTabs = flightTabs;

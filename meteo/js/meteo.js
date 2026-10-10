(function () {
  var holder = document.querySelector('.meteo-article');
  if (!holder) return;
  var conf = JSON.parse(holder.querySelector('.met-data').textContent);

  // `slots` is the whole of the multi-site model, and it is an array of fixed length
  // rather than a list of chosen sites *on purpose*: a slot is a colour, and colour
  // follows the takeoff rather than its position in a list. Drop the first of three and
  // the other two keep the colour they had — a reader who has just learned that the
  // orange line is Raná should not find Raná blue a second later.
  //
  // `site` is the *focused* one: whose sounding, figures and flymet picture the panel
  // shows, and whose cloud the meteogram shades. It is also the name `window.__meteo`
  // has always exposed, along with `profile`, which is that site's profile.
  //
  // `probe` is the height the pointer is at in the sounding, in metres, and `probeX`
  // where it is across it — the readout follows the pointer sideways but reads the
  // profile, so what it says never depends on which temperature you happen to be over.
  var MAX_CHOSEN = __MAX_CHOSEN__;
  var noSlots = [];
  for (var n = 0; n < MAX_CHOSEN; n++) noSlots.push(null);
  var state = { day: 0, hour: 14, slots: noSlots, order: [], site: null,
                surface: null, profile: null, profiles: {}, search: '',
                probe: null, probeX: 0 };

  var status = document.getElementById('met-status');
  function say(text) { status.textContent = text; }

  // The chosen takeoffs in the reader's order (`state.order`, set by moving a column or
  // dragging a chip), skipping the empty slots. The slot is the colour and the order is
  // only where it stands, so a takeoff moved keeps its colour.
  function chosen() {
    var picked = state.slots.filter(function (index) { return index !== null; });
    var out = state.order.filter(function (index) { return picked.indexOf(index) >= 0; });
    picked.forEach(function (index) { if (out.indexOf(index) < 0) out.push(index); });
    return out;
  }
  function slotOf(index) { return state.slots.indexOf(index); }
  function seriesColour(slot) {
    return ink('--series-' + (slot + 1)) || '#888';
  }

  // The chosen takeoffs, remembered. A pilot checks the same two or three hills all season,
  // and making them pick them again every morning is the kind of small rudeness that
  // makes a tool feel like a demo. Wrapped because a page opened from a file:// URL in
  // some browsers throws on even reading localStorage, and a page that fails to load
  // because it could not remember something is worse than one that forgets.
  var REMEMBER = 'parainsights.meteo.sites';
  function remember() {
    try {
      window.localStorage.setItem(REMEMBER, JSON.stringify(state.slots));
      window.localStorage.setItem(REMEMBER + '.order', JSON.stringify(chosen()));
    } catch (error) { /* private mode, file://, or a full quota: forget instead */ }
  }
  function recall() {
    try {
      var saved = JSON.parse(window.localStorage.getItem(REMEMBER) || 'null');
      if (!Array.isArray(saved)) return;
      for (var s = 0; s < MAX_CHOSEN; s++) {
        var index = saved[s];
        // Validated, not trusted: the site list is regenerated from ParaglidingEarth and
        // an index saved against an older one could point anywhere, or nowhere.
        state.slots[s] = (typeof index === 'number' && conf.sites[index]) ? index : null;
      }
      var order = JSON.parse(window.localStorage.getItem(REMEMBER + '.order') || '[]');
      state.order = Array.isArray(order) ? order.filter(function (index) {
        return typeof index === 'number' && conf.sites[index];
      }) : [];
      state.site = chosen().length ? chosen()[0] : null;
    } catch (error) { /* nothing remembered, which is the normal first visit */ }
  }

  // ---- the wind, against the takeoff -------------------------------------------------
  //
  // The one judgement this page makes, and it is made from the site's own record rather
  // than from a rule about hills: ParaglidingEarth stores which octants each takeoff
  // works in, and a site with no record is left unjudged rather than guessed at. Two
  // gates, because they fail differently — a good direction blowing 11 m/s is not a
  // good day, and neither is 2 m/s onto a face that needs 5.
  // In metres per second, which is what a pilot on a hill says out loud and what every
  // vario and windsock conversation is already in. The two numbers are the same rule as
  // before, converted exactly rather than re-chosen: 28 km/h is 7.78 m/s and 20 km/h is
  // 5.56 m/s, so no takeoff changes verdict on the day this shipped. Open-Meteo is asked
  // for `wind_speed_unit=ms`, so nothing here divides by 3.6 — a conversion in the page
  // is one more place to be wrong, and the readouts, the table and these gates would
  // each have needed their own.
  var STRONG = 7.8, BRISK = 5.6;
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
  // one round trip however many there are — and the pressure levels
  // for one site only when that site is opened. Asking for the profile of every takeoff
  // up front would be tens of megabytes to answer a question about one hill.
  function surfaceUrl() {
    var lat = conf.sites.map(function (s) { return s.lat; }).join(',');
    var lon = conf.sites.map(function (s) { return s.lon; }).join(',');
    return conf.endpoint + '?latitude=' + lat + '&longitude=' + lon
      + '&hourly=wind_speed_10m,wind_direction_10m,temperature_2m,cloud_cover,cape'
      + '&forecast_days=4&timezone=Europe%2FPrague&wind_speed_unit=ms'
      + '&models=' + MODEL;
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
      + '&forecast_days=4&timezone=Europe%2FPrague&wind_speed_unit=ms'
      + '&models=' + MODEL + ',' + BLH_MODEL;
  }

  // Asked for by name, not left to Open-Meteo's `best_match`. Best match *was* exactly
  // this — ICON-D2 to its horizon, ICON-EU after, the boundary layer height from ECMWF
  // IFS because ICON publishes none; measured hour by hour on 2026-09-23, identical in
  // every value — but a blend nobody names cannot be shown to the reader, and it can
  // change under the page without a word. Two models in one request come back with
  // their names on every key, so the profile is put back into the one shape the charts
  // read: everything from ICON, the boundary layer from IFS.
  function unpack(answer) {
    var hourly = answer.hourly || {};
    var mine = '_' + MODEL, blh = '_' + BLH_MODEL;
    var out = {};
    Object.keys(hourly).forEach(function (key) {
      if (key.slice(-mine.length) === mine) out[key.slice(0, -mine.length)] = hourly[key];
      else if (key.slice(-blh.length) !== blh && !(key in out)) out[key] = hourly[key];
    });
    if (hourly['boundary_layer_height' + blh]) {
      out.boundary_layer_height = hourly['boundary_layer_height' + blh];
    }
    answer.hourly = out;
    return answer;
  }

  // Which ICON the chosen hour comes from. ICON-D2 runs every three hours out to +48 h
  // and Open-Meteo blends the last three hours of it into ICON-EU; its own metadata says
  // where the current run ends, so the label is read, not assumed.
  function loadRuns() {
    var runs = {};
    return Promise.all(['dwd_icon_d2', 'dwd_icon_eu'].map(function (name) {
      return get(META.replace('{model}', name)).then(function (meta) { runs[name] = meta; })
        .catch(function () { /* the label falls back to naming ICON without the run */ });
    })).then(function () { state.runs = runs; drawModel(); });
  }

  // The site's icons (`parainsights_common.ICONS`), for what this script draws.
  var CLOSE_ICON = '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 5l10 10M15 5 5 15"/></svg>';
  var LINK_ICON = '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11.5 3.5h5v5M16.5 3.5 9 11M14 11.5v5H3.5V6h5"/></svg>';
  var LEFT_ICON = '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5.5 7.5 10l4.5 4.5"/></svg>';
  var RIGHT_ICON = '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 5.5l4.5 4.5L8 14.5"/></svg>';
  var PLUS_ICON = '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 4v12M4 10h12"/></svg>';
  var EXPAND_ICON = '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11.5 3.5h5v5M8.5 16.5h-5v-5M16.5 3.5 11 9M3.5 16.5 9 11"/></svg>';
  function cap(text) { return text ? text.charAt(0).toUpperCase() + text.slice(1) : text; }

  function drawModel() {
    var box = document.getElementById('met-model');
    var surface = state.surface && state.surface[0];
    var d2 = state.runs && state.runs.dwd_icon_d2;
    var eu = state.runs && state.runs.dwd_icon_eu;
    var name = 'ICON', run = null;
    if (surface && surface.hourly && d2 && d2.data_end_time) {
      var at = indexFor(surface.hourly.time, state.day, state.hour);
      var local = surface.hourly.time[at];
      var when = Date.parse(local + ':00Z') / 1000 - (surface.utc_offset_seconds || 0);
      if (when < d2.data_end_time - 3 * 3600) { name = 'ICON-D2 · 2 km'; run = d2; }
      else if (when < d2.data_end_time) { name = 'ICON-D2 → ICON-EU'; run = d2; }
      else { name = 'ICON-EU · 7 km'; run = eu; }
    }
    var init = run && run.last_run_initialisation_time
      ? ('0' + new Date(run.last_run_initialisation_time * 1000).getUTCHours()).slice(-2)
        + ' UTC run'
      : null;
    box.innerHTML = 'Model <b></b>' + (init ? ' · <span class="run"></span>' : '')
      + ' · boundary layer <b>ECMWF IFS</b>';
    box.querySelector('b').textContent = name;
    if (init) box.querySelector('.run').textContent = init;
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
    var names = ['Today', 'Tomorrow'];
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
      drawTime();
    };
  }

  // The day and the hour are one setting with two controls, and everything that reads
  // them has to be repainted together. They were two lists of redraws written out by
  // hand, and they drifted: the hour repainted the comparison table and the day did not,
  // so switching to tomorrow moved every chart and left the numbers under them still
  // describing today — the wind, the verdict, the thermal top and the cloudbase, which
  // is the half of this page a reader actually reads. One list now, and both controls
  // call it.
  function drawTime() {
    drawModel();
    drawList();
    drawCompare();
    drawSite();
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

  // ---- what the surface forecast says about one takeoff, this hour --------------------
  function surfaceAt(index) {
    var series = state.surface && state.surface[index];
    if (!series || !series.hourly) return null;
    var at = indexFor(series.hourly.time, state.day, state.hour);
    var speed = series.hourly.wind_speed_10m[at];
    var direction = series.hourly.wind_direction_10m[at];
    return {
      index: index, site: conf.sites[index], speed: speed, direction: direction,
      cloud: series.hourly.cloud_cover[at],
      temperature: series.hourly.temperature_2m[at],
      verdict: verdict(conf.sites[index], speed, direction)
    };
  }

  // ---- the picker ---------------------------------------------------------------------
  //
  // 159 takeoffs used to be a scrolling column occupying the top-left of the page for as
  // long as the page was open — a list nobody reads twice, in the space the answer wants.
  // It is a dialog now: opened deliberately, searched rather than scrolled, and closed
  // again. What stays on the page is the two or three places the reader chose.
  var RANK = { good: 0, fair: 1, none: 2, poor: 3 };
  var modal = document.getElementById('met-modal');

  // Accents folded away on both sides: the names are pgweb's, with their háčky and
  // čárky, and "cerna" has to find Černá hora on a keyboard without them.
  function folded(text) {
    return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  }

  function drawList() {
    var list = document.getElementById('met-list');
    if (!state.surface) return;
    var needle = folded(state.search.trim());
    var rows = conf.sites.map(function (site, i) { return surfaceAt(i); })
      .filter(Boolean)
      .filter(function (row) {
        return !needle || folded(row.site.name).indexOf(needle) >= 0;
      });
    // Ranked by the verdict, then by name. The chosen ones are *not* pulled to the top:
    // the list is a ranking of the day and re-sorting it under the reader's own choices
    // would move the row they are about to click.
    rows.sort(function (a, b) {
      var by = RANK[a.verdict.key] - RANK[b.verdict.key];
      return by || a.site.name.localeCompare(b.site.name);
    });

    list.textContent = '';
    if (!rows.length) {
      var empty = document.createElement('p');
      empty.className = 'met-empty';
      empty.textContent = 'No takeoff matches “' + state.search.trim() + '”.';
      list.appendChild(empty);
    }
    rows.forEach(function (row) {
      var on = slotOf(row.index) >= 0;
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'met-site' + (on ? ' is-on' : '');
      button.dataset.index = row.index;
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      button.innerHTML =
        '<span class="tick"></span>'
        + '<span class="met-site-name"></span>'
        + '<span class="met-verdict met-' + row.verdict.key + '"></span>'
        + '<span class="met-site-note"></span>';
      // The tick is the state, and it is a character rather than a colour: this row is
      // already carrying a coloured verdict badge, and two colours competing to mean two
      // different things in 30 px of row is one too many.
      button.querySelector('.tick').textContent = on ? '✓' : '+';
      button.querySelector('.met-site-name').textContent = row.site.name;
      button.querySelector('.met-verdict').textContent = row.verdict.text;
      button.querySelector('.met-site-note').textContent =
        row.speed.toFixed(1) + ' m/s from ' + compass(row.direction)
        + ' · ' + row.site.alt + ' m · ' + Math.round(row.cloud) + '% cloud';
      list.appendChild(button);
    });

    var count = document.getElementById('met-count');
    var picked = chosen().length;
    count.textContent = picked
      ? picked + ' of ' + MAX_CHOSEN + ' chosen'
        + (picked >= MAX_CHOSEN ? ' — drop one to add another' : '')
      : 'Choose up to ' + MAX_CHOSEN + ' takeoffs to compare';
  }

  function toggle(index) {
    var slot = slotOf(index);
    if (slot >= 0) {
      drop(index);
      return;
    }
    var free = state.slots.indexOf(null);
    if (free < 0) {
      // Refuse rather than silently evicting the oldest: a reader who has just added one
      // more takeoff and had one of their own disappear has no way to know which or why.
      say(MAX_CHOSEN + ' at a time — drop one first.');
      return;
    }
    state.slots[free] = index;
    state.order = chosen();
    if (state.site === null) state.site = index;
    remember();
    drawChosen();
    drawList();
    drawCompare();
    // Redrawn now rather than when the sounding lands: adding a takeoff has to change
    // the page in the same gesture, or the reader taps it again. The row and the legend
    // entry appear at once and say they are waiting; the line arrives with the numbers.
    drawSite();
    loadProfiles();
  }

  function drop(index) {
    var slot = slotOf(index);
    if (slot < 0) return;
    state.slots[slot] = null;
    delete state.profiles[index];
    if (state.site === index) {
      var left = chosen();
      state.site = left.length ? left[0] : null;
      state.profile = state.site === null ? null : (state.profiles[state.site] || null);
    }
    remember();
    drawChosen();
    drawList();
    drawCompare();
    drawSite();
  }

  // A takeoff moved to `to` in the order, by its column's arrows or a dragged chip:
  // the chips, the table and the columns all follow, and its colour stays its own.
  function moveTo(index, to) {
    var list = chosen(), at = list.indexOf(index);
    if (at < 0 || to < 0 || to >= list.length || to === at) return;
    list.splice(at, 1);
    list.splice(to, 0, index);
    state.order = list;
    remember();
    drawChosen();
    drawCompare();
    drawSite();
    swipeTo(index);
  }

  // `fromSwipe`: the columns were swiped to it, so they are not swiped again.
  function focus(index, fromSwipe) {
    if (slotOf(index) < 0 || state.site === index) return;
    state.site = index;
    state.profile = state.profiles[index] || null;
    drawChosen();
    drawCompare();
    drawSite();
    if (!state.profile) loadProfiles();
    if (!fromSwipe) swipeTo(index);
  }

  // On a phone the takeoffs' columns swipe sideways (`.met-columns`), under the chips.
  // The two follow each other: a swipe that settles on a takeoff focuses it and brings
  // its chip into the middle of the chips' row, and a chip pressed swipes to its column.
  // The chips' row stood still while the columns moved under it.
  var columnsBox = document.getElementById('met-columns');
  // On a desktop the same strip shows three columns at a time and scrolls sideways past
  // them, so a column already in view is left where it is, and one out of view is
  // brought in at the nearer edge.
  function swiping() { return columnsBox && columnsBox.scrollWidth > columnsBox.clientWidth + 1; }
  function oneAtATime() {
    var cell = columnsBox && columnsBox.querySelector('.met-col');
    return !!cell && cell.getBoundingClientRect().width > columnsBox.clientWidth * 0.6;
  }
  function swipeTo(index) {
    if (!swiping()) return;
    var cell = columnsBox.querySelector('.met-col[data-site="' + index + '"]');
    if (!cell) return;
    var box = columnsBox.getBoundingClientRect(), r = cell.getBoundingClientRect(), by;
    if (oneAtATime()) by = r.left - box.left - (box.width - r.width) / 2;
    else if (r.left < box.left - 1) by = r.left - box.left;
    else if (r.right > box.right + 1) by = r.right - box.right;
    else return;
    columnsBox.scrollTo({ left: columnsBox.scrollLeft + by, behavior: 'smooth' });
  }
  function chipIntoView() {
    var row = document.getElementById('met-chosen'), chip = row && row.querySelector('.met-chip.is-focus');
    if (!chip || row.scrollWidth <= row.clientWidth + 1) return;
    var box = row.getBoundingClientRect(), r = chip.getBoundingClientRect();
    row.scrollTo({ left: row.scrollLeft + r.left - box.left - (box.width - r.width) / 2, behavior: 'smooth' });
  }
  if (columnsBox) {
    var settle = null;
    columnsBox.addEventListener('scroll', function () {
      if (!swiping() || !oneAtATime()) return;
      clearTimeout(settle);
      settle = setTimeout(function () {
        var box = columnsBox.getBoundingClientRect(), mid = box.left + box.width / 2;
        var best = null, bestD = Infinity;
        columnsBox.querySelectorAll('.met-col').forEach(function (cell) {
          var r = cell.getBoundingClientRect(), d = Math.abs(r.left + r.width / 2 - mid);
          if (d < bestD) { bestD = d; best = cell; }
        });
        if (best) focus(Number(best.dataset.site), true);
        chipIntoView();
      }, 140);
    }, { passive: true });
  }

  // ---- the chips ----------------------------------------------------------------------
  function drawChosen() {
    var box = document.getElementById('met-chosen');
    var add = document.getElementById('met-add');
    Array.prototype.slice.call(box.querySelectorAll('.met-chip, .met-cap'))
      .forEach(function (node) { node.remove(); });
    chosen().forEach(function (index) {
      var slot = slotOf(index), site = conf.sites[index];
      var chip = document.createElement('span');
      chip.className = 'chip met-chip' + (state.site === index ? ' is-focus' : '');
      chip.innerHTML = '<i class="swatch"></i>'
        + '<button type="button" class="met-chip-name"></button>'
        + '<button type="button" class="met-chip-drop" aria-label="Remove"></button>';
      chip.querySelector('.swatch').style.background = seriesColour(slot);
      var name = chip.querySelector('.met-chip-name');
      name.textContent = site.name;
      name.setAttribute('aria-pressed', state.site === index ? 'true' : 'false');
      name.onclick = function () { focus(index); };
      var close = chip.querySelector('.met-chip-drop');
      close.innerHTML = CLOSE_ICON;
      close.setAttribute('aria-label', 'Remove ' + site.name);
      close.onclick = function () { drop(index); };
      // Dragged onto another chip, it takes that chip's place in the order.
      chip.draggable = true;
      chip.dataset.site = index;
      chip.addEventListener('dragstart', function (event) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(index));
        chip.classList.add('is-dragged');
      });
      chip.addEventListener('dragend', function () { chip.classList.remove('is-dragged'); });
      chip.addEventListener('dragover', function (event) { event.preventDefault(); });
      chip.addEventListener('drop', function (event) {
        event.preventDefault();
        var moved = Number(event.dataTransfer.getData('text/plain'));
        if (slotOf(moved) >= 0) moveTo(moved, chosen().indexOf(index));
      });
      box.insertBefore(chip, add);
    });
    add.innerHTML = PLUS_ICON + '<span>Add takeoff</span>';
    // The cap, said only when it matters: on the button that stops working.
    add.disabled = chosen().length >= MAX_CHOSEN;
    add.title = add.disabled ? MAX_CHOSEN + ' at a time — remove one to add another' : '';
  }

  // ---- the comparison ------------------------------------------------------------------
  //
  // The answer to "where should I drive", in one table: every chosen takeoff on the same
  // row shape, at the same hour, from the same model. It is also the palette's *table
  // view* — two of the three light-mode series sit under 3:1 against the panel, which the
  // colour rules allow only where identity is also carried by something that is not
  // colour. Here it is carried twice: this table, and a label on each line.
  function drawCompare() {
    var table = document.getElementById('met-compare');
    var body = table.querySelector('tbody');
    var rows = chosen();
    table.hidden = rows.length < 2;
    body.textContent = '';
    if (rows.length < 2) return;

    var measured = rows.map(function (index) {
      var surface = surfaceAt(index);
      var profile = state.profiles[index];
      var top = null, base = null, lid = null, ground = null;
      if (profile && profile.hourly) {
        var at = indexFor(profile.hourly.time, state.day, state.hour);
        ground = profile.elevation;
        var blh = profile.hourly.boundary_layer_height[at];
        top = blh == null ? null : ground + blh;
        base = cloudbase(profile.hourly.temperature_2m[at],
                         profile.hourly.dew_point_2m[at], ground);
        var caps = cappingLayers(profile.hourly, at, ground, ceilingFor(ground));
        lid = caps.length ? caps[0] : null;
      }
      var temperature = null, dew = null;
      if (profile && profile.hourly) {
        var hour = indexFor(profile.hourly.time, state.day, state.hour);
        temperature = profile.hourly.temperature_2m[hour];
        dew = profile.hourly.dew_point_2m[hour];
      }
      return { index: index, surface: surface, top: top, base: base, lid: lid,
               ground: ground, temperature: temperature, dew: dew };
    });
    // The best figure in each column is marked, which is the comparison doing its job:
    // three numbers in a column are three numbers until one of them is the answer.
    var bestTop = Math.max.apply(null, measured.map(function (m) {
      return m.top == null ? -Infinity : m.top; }));
    var bestBase = Math.max.apply(null, measured.map(function (m) {
      return m.base == null ? -Infinity : m.base; }));

    measured.forEach(function (m) {
      var row = document.createElement('tr');
      row.className = state.site === m.index ? 'is-focus' : '';
      row.tabIndex = 0;
      var slot = slotOf(m.index);
      var verdictKey = m.surface ? m.surface.verdict.key : 'none';
      row.innerHTML =
        '<th scope="row"><span class="site"><i class="swatch"></i><span></span></span></th>'
        + '<td><span class="met-verdict met-' + verdictKey + '"></span></td>'
        + '<td class="wind"></td><td class="top"></td><td class="base"></td>'
        + '<td class="surface hide-narrow"></td>'
        + '<td class="lid hide-narrow"></td><td class="ground hide-narrow"></td>';
      row.querySelector('.swatch').style.background = seriesColour(slot);
      row.querySelector('.site span').textContent = conf.sites[m.index].name;
      row.querySelector('.met-verdict').textContent =
        m.surface ? m.surface.verdict.text : '—';
      row.querySelector('.wind').textContent = m.surface
        ? m.surface.speed.toFixed(1) + ' m/s ' + compass(m.surface.direction) : '—';
      var top = row.querySelector('.top');
      top.textContent = m.top == null ? '…' : Math.round(m.top) + ' m';
      if (m.top != null && m.top === bestTop) top.className = 'top best';
      var base = row.querySelector('.base');
      base.textContent = m.base == null ? '…' : Math.round(m.base) + ' m';
      if (m.base != null && m.base === bestBase) base.className = 'base best';
      // The surface pair. These were a tile row under the charts for the *focused*
      // takeoff, which is a comparison page showing one of something it has three of.
      row.querySelector('.surface').textContent = m.temperature == null ? '…'
        : Math.round(m.temperature) + ' / ' + Math.round(m.dew) + ' °C';
      // A lid whose base *is* the ground is not a height, it is a state: the column is
      // stable from the surface up, and printing "402 m" beside a ground of 402 m reads
      // as a coincidence rather than as the thing it is. `cappingLayers` clamps the base
      // to the ground, so this is the common morning case and it was the one number on
      // the table a reader had to do arithmetic to understand.
      row.querySelector('.lid').textContent = m.lid
        ? ((m.ground != null && m.lid.base <= m.ground + 1)
             ? 'from the ground' : Math.round(m.lid.base) + ' m')
          + (m.lid.inversion ? ' inv' : '')
        : (m.top == null ? '…' : 'none');
      row.querySelector('.ground').textContent =
        m.ground == null ? conf.sites[m.index].alt + ' m' : Math.round(m.ground) + ' m';
      row.onclick = function () { focus(m.index); };
      row.onkeydown = function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          focus(m.index);
          event.preventDefault();
        }
      };
      body.appendChild(row);
    });
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
  var MODEL = 'icon_seamless';     // ICON-D2, then ICON-EU, then ICON global
  var BLH_MODEL = 'ecmwf_ifs';     // the boundary layer height, which ICON does not publish
  var META = 'https://api.open-meteo.com/data/{model}/static/meta.json';
  var DRY_LAPSE = 9.8;    // °C per km, the dry adiabat a parcel climbs

  // The sounding's frame, shared by the chart and by the pointer that reads heights off
  // it. Two copies of these three numbers is a readout that quietly points at the wrong
  // height the first time the chart is retuned.
  var SOUND_TOP = 10, SOUND_BOTTOM = 24, SOUND_CEILING = 4000;

  // The top of a takeoff's charts: 4 km, or three above its ground where that is higher.
  // A fixed 4 km was drawn for Czech hills; Col Rodella stands at 2 400 m, and under a
  // 4 km lid its sounding was one pressure level — a dot, not a column.
  function ceilingFor(ground) {
    return Math.max(SOUND_CEILING, Math.ceil(((ground || 0) + 3000) / 1000) * 1000);
  }

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

  // ---- one airgram per takeoff, and one strip that compares them ----------------------
  //
  // The single-takeoff chart is `drawAir` (below the columns): wind, cloud, ground,
  // boundary layer and cloudbase on one frame of hour against height. `drawStrip` is every
  // chosen takeoff and *nothing else* — boundary layers alone, the only quantity on this
  // page that compares across hills standing at different heights. A cloud or a ground
  // drawn there would be one hill's fact on a chart labelled with three.
  // The comparison, and only the comparison: one line per chosen takeoff, nothing that
  // belongs to a single one of them. Hidden below two takeoffs, because a comparison of
  // one is the chart above it with more steps.
  function drawStrip() {
    var holder = document.getElementById('met-strip');
    var wanted = chosen();
    holder.hidden = wanted.length < 2;
    if (holder.hidden) return;
    var canvas = document.getElementById('met-band');
    var frame = fit(canvas);
    if (!frame) return;
    var ctx = frame.ctx, W = frame.w, H = frame.h;
    var left = 38, right = 8, top = 8, bottom = 22;
    // Scaled to the day rather than to a fixed 4 000 m. The per-takeoff meteograms keep
    // the fixed ceiling — they carry cloud, which goes all the way up — but this one
    // holds boundary layers alone, and on a 1 600 m day a fixed ceiling spends half the
    // frame on empty sky and squashes the difference between three hills into a
    // centimetre. That difference is the entire chart.
    var highest = 0;
    state.slots.forEach(function (index) {
      if (index === null) return;
      var profile = state.profiles[index];
      if (!profile || !profile.hourly) return;
      var blh = profile.hourly.boundary_layer_height;
      for (var h = 5; h <= 21; h++) {
        var value = blh[indexFor(profile.hourly.time, state.day, h)];
        if (value != null) highest = Math.max(highest, profile.elevation + value);
      }
    });
    var top_m = Math.max(Math.ceil((highest * 1.1) / 500) * 500, 1500);
    var grid = top_m <= 2500 ? 500 : 1000;
    function x(hour) { return left + (hour - 5) / 16 * (W - left - right); }
    function y(metres) { return top + (1 - metres / top_m) * (H - top - bottom); }
    ctx.clearRect(0, 0, W, H);

    var box = { left: left, top: top, W: W, H: H, right: right, bottom: bottom };
    var labels = [];
    state.slots.forEach(function (index, slot) {
      if (index === null) return;
      var profile = state.profiles[index];
      if (!profile || !profile.hourly) return;
      var end = hourLine(ctx, profile, x, y, boundaryLayer(profile), false,
                         seriesColour(slot), index === state.site ? 2.6 : 2, box);
      if (end) labels.push({ x: end[0], y: end[1], slot: slot,
                             name: conf.sites[index].name });
    });
    gramAxes(ctx, x, y, top_m, left, right, bottom, W, H, 4, grid);
    directLabels(ctx, labels, top, H - bottom);
  }

  function boundaryLayer(profile) {
    return function (at) {
      var blh = profile.hourly.boundary_layer_height[at];
      return blh == null ? null : profile.elevation + blh;
    };
  }

  function hourLine(ctx, profile, x, y, values, dashed, colour, width, box) {
    ctx.save();
    // Clipped to the plot box. A cloudbase of 4 290 m on a chart that stops at 4 000
    // otherwise draws a dashed line across the caption above it, which reads as a
    // rendering fault rather than as "higher than this chart goes".
    ctx.beginPath();
    ctx.rect(box.left, box.top, box.W - box.left - box.right,
             box.H - box.top - box.bottom);
    ctx.clip();
    ctx.beginPath();
    ctx.setLineDash(dashed ? [5, 4] : []);
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.lineJoin = 'round';
    var started = false, lastX = null, lastY = null;
    for (var h = 5; h <= 21; h++) {
      var value = values(indexFor(profile.hourly.time, state.day, h));
      if (value == null) continue;
      lastX = x(h); lastY = y(value);
      if (!started) { ctx.moveTo(lastX, lastY); started = true; }
      else ctx.lineTo(lastX, lastY);
    }
    ctx.stroke();
    ctx.restore();
    return started ? [lastX, lastY] : null;
  }

  function gramAxes(ctx, x, y, top_m, left, right, bottom, W, H, step, grid) {
    grid = grid || 1000;
    ctx.strokeStyle = ink('--rule');
    ctx.fillStyle = ink('--ink-3');
    ctx.font = '14px "Noto Sans", ui-sans-serif, sans-serif';
    ctx.lineWidth = 1;
    for (var m = 0; m <= top_m; m += grid) {
      ctx.beginPath(); ctx.moveTo(left, y(m)); ctx.lineTo(W - right, y(m)); ctx.stroke();
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText(m >= 1000 ? (m / 1000) + 'k' : String(m), left - 5, y(m));
    }
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (var t = 6; t <= 20; t += step) ctx.fillText(t + ':00', x(t), H - bottom + 4);
  }

  // Pushed apart where two takeoffs end the day at the same height — which on a good
  // day they do — and drawn on a pad, because a label read against a line is a label
  // read twice.
  function directLabels(ctx, labels, topEdge, bottomEdge) {
    labels.forEach(function (label) {
      label.y = Math.min(Math.max(label.y, topEdge + 7), bottomEdge - 7);
    });
    labels.sort(function (a, b) { return a.y - b.y; });
    for (var i = 1; i < labels.length; i++) {
      if (labels[i].y - labels[i - 1].y < 12) labels[i].y = labels[i - 1].y + 12;
    }
    ctx.font = '600 14px "Noto Sans", ui-sans-serif, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    labels.forEach(function (label) {
      var text = label.name.length > 14 ? label.name.slice(0, 13) + '…' : label.name;
      var width = ctx.measureText(text).width;
      ctx.globalAlpha = 0.85;
      ctx.fillStyle = ink('--panel');
      ctx.fillRect(label.x - width - 5, label.y - 7, width + 6, 14);
      ctx.globalAlpha = 1;
      ctx.fillStyle = seriesColour(label.slot);
      ctx.fillText(text, label.x - 2, label.y);
    });
  }

  // The legend, in the DOM rather than on the canvas: it is text, and text in a canvas
  // is invisible to a screen reader and to a find-in-page.
  function drawKeys() {
    var box = document.getElementById('met-keys');
    box.textContent = '';
    state.slots.forEach(function (index, slot) {
      if (index === null) return;
      var key = document.createElement('span');
      key.innerHTML = '<i></i><span></span>';
      key.querySelector('i').style.borderTopColor = seriesColour(slot);
      key.querySelector('span').textContent = conf.sites[index].name
        + (state.profiles[index] ? '' : ' — fetching…');
      box.appendChild(key);
    });
  }

  // One column per chosen takeoff: its name, its airgram, its sounding. Small
  // multiples, and the reason is the same for both charts — three temperature traces and
  // three dew points on one frame is six crossing lines, and three sets of cloud shading
  // is a grey smear. What compares across hills is on the strip above; what belongs to
  // one hill is in that hill's column, under its name.
  function drawColumns() {
    var box = document.getElementById('met-columns');
    var wanted = chosen();
    // Set before anything is drawn: `fit()` measures the canvas box, so a layout change
    // applied after the draw leaves every chart drawn for the width it used to have.
    box.classList.toggle('is-single', wanted.length === 1);
    box.classList.toggle('is-two', wanted.length === 2);
    // Rebuilt only when the set changes: canvases recreated on every hour step lose
    // their backing stores and their pointer handlers, and the slider steps a lot.
    var have = Array.prototype.map.call(box.children, function (cell) {
      return Number(cell.dataset.site);
    });
    if (have.join(',') !== wanted.join(',')) {
      box.textContent = '';
      wanted.forEach(function (index) {
        var cell = document.createElement('div');
        cell.className = 'met-col';
        cell.dataset.site = index;
        cell.innerHTML = '<p class="met-col-head"><i></i><span class="name"></span>'
          + '<span class="ground"></span><span class="met-col-tools">'
          + '<a class="met-col-pge" rel="noreferrer" target="_blank">' + LINK_ICON + '</a>'
          + '<button type="button" class="met-col-move" data-by="-1">' + LEFT_ICON + '</button>'
          + '<button type="button" class="met-col-move" data-by="1">' + RIGHT_ICON + '</button>'
          + '</span></p>'
          + '<p class="met-col-rose"><span></span></p>'
          + '<canvas class="met-canvas met-col-air" width="380" height="270"'
          + ' aria-label="The day by hour and height: wind, cloud, boundary layer and cloudbase">'
          + '</canvas>'
          + '<canvas class="met-canvas met-col-sounding" width="380" height="300"></canvas>'
          + '<p class="met-col-airout"></p>'
          + '<p class="met-col-top" hidden><span class="txt"></span><span class="info-wrap">'
          + '<button type="button" class="info" aria-expanded="false" aria-label="About the thermal top">i</button>'
          + '<span class="info-pop" role="note"></span></span></p>'
          + '<figure class="met-col-fly" hidden></figure>';
        cell.querySelector('i').style.background = seriesColour(slotOf(index));
        cell.querySelector('.name').textContent = conf.sites[index].name;
        // Clicking a column focuses that takeoff, the same as its chip or its table row.
        cell.querySelector('.name').onclick = function () { focus(index); };
        // The wind rose and the source link are facts about *this* takeoff, and they
        // used to sit in a header over the whole panel — which, with three takeoffs
        // under it, said one hill's octants above three hills' charts.
        var site = conf.sites[index];
        var good = (site.winds || []).length
          ? conf.octants.filter(function (point, i) { return site.winds[i] === 2; })
          : null;
        cell.querySelector('.met-col-rose span').textContent = good === null
          ? 'No directions recorded, so this page will not judge it'
          : (good.length ? 'Works in ' + good.join(' ') : 'Only marginal directions');
        // The takeoff's own page, as an icon by its name: the source of its directions.
        var link = cell.querySelector('.met-col-pge');
        link.href = 'https://www.paraglidingearth.com/index.php?site=' + site.id;
        link.title = site.name + ' on ParaglidingEarth';
        link.setAttribute('aria-label', link.title);
        // Moved a place left or right; the end a column cannot go past is disabled.
        var at = wanted.indexOf(index);
        cell.querySelectorAll('.met-col-move').forEach(function (button) {
          var by = Number(button.dataset.by);
          button.title = by < 0 ? 'Move ' + site.name + ' left' : 'Move ' + site.name + ' right';
          button.setAttribute('aria-label', button.title);
          button.disabled = at + by < 0 || at + by >= wanted.length;
          button.onclick = function () { moveTo(index, chosen().indexOf(index) + by); };
        });
        cell.querySelector('.met-col-sounding').title =
          box.dataset.soundingHint.replace(/\s+/g, ' ');
        bindProbe(cell.querySelector('.met-col-sounding'));
        bindAir(cell.querySelector('.met-col-air'), cell.querySelector('.met-col-airout'),
                index);
        box.appendChild(cell);
      });
      drawSwipe(box, wanted);
    }
    Array.prototype.forEach.call(box.children, function (cell) {
      var index = Number(cell.dataset.site);
      var profile = state.profiles[index];
      cell.classList.toggle('is-focus', index === state.site);
      cell.querySelector('.ground').textContent =
        profile ? Math.round(profile.elevation) + ' m' : 'fetching…';
      var sounding = cell.querySelector('.met-col-sounding');
      // The focused takeoff's sounding keeps the id the pointer readout has always
      // addressed, so nothing has to hunt for "whichever chart happens to be first".
      sounding.id = index === state.site ? 'met-sounding' : '';
      drawSounding(sounding, profile);
      drawAir(cell.querySelector('.met-col-air'), profile, slotOf(index));
    });
  }

  // On a phone the columns are a strip to swipe; this is its selector, and it follows the
  // swipe. Built with the columns, because it names them.
  function drawSwipe(box, wanted) {
    var holder = document.getElementById('met-swipe');
    if (!holder) return;
    holder.textContent = '';
    if (wanted.length < 2) return;
    var seg = document.createElement('div');
    seg.className = 'seg';
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', 'Show the charts for');
    wanted.forEach(function (index, i) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = i === 0 ? 'is-on' : '';
      b.innerHTML = '<i class="dot"></i><span></span>';
      b.querySelector('i').style.background = seriesColour(slotOf(index));
      b.querySelector('span').textContent = conf.sites[index].name;
      b.onclick = function () { box.children[i].scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' }); };
      seg.appendChild(b);
    });
    holder.appendChild(seg);
    box.onscroll = function () {
      var middle = box.scrollLeft + box.clientWidth / 2, best = 0;
      Array.prototype.forEach.call(box.children, function (cell, i) {
        if (Math.abs(cell.offsetLeft + cell.offsetWidth / 2 - middle) <
            Math.abs(box.children[best].offsetLeft + box.children[best].offsetWidth / 2 - middle)) best = i;
      });
      Array.prototype.forEach.call(seg.children, function (b, i) { b.className = i === best ? 'is-on' : ''; });
    };
  }

  // ---- the airgram: wind by hour and height ---------------------------------------------
  //
  // The sounding is the air at one hour; this is the wind at every hour of the day and
  // every height up to the chart's ceiling — the question "when does it turn, and does
  // it get strong up where I will be" that one hour cannot answer. It took over the
  // meteogram's job too — cloud, ground, boundary layer and cloudbase are drawn on it —
  // so one chart answers "when, and how high". The same height scale as the sounding
  // beside it, so the two read across.
  //
  // Speed is the shading, one hue deepening with speed and laid over the panel so both
  // themes work; direction is an arrow pointing *downwind*, the convention of every other
  // arrow on this site (the 3D view's rose), with the reported direction in the readout.
  // Heights between pressure levels come from `sampleProfile`, which interpolates the
  // wind as components — the readout and the shading cannot disagree.
  var AIR_FULL = 15;      // m/s at which the shading is at its deepest
  var AIR_STEP = 100;     // metres per shaded row
  function airFrame(canvas, profile) {
    var box = canvas.getBoundingClientRect();
    var W = box.width, H = box.height;
    var left = 38, right = 8, top = 8, bottom = 22;
    var top_m = ceilingFor(profile.elevation);
    return { W: W, H: H, left: left, right: right, top: top, bottom: bottom, top_m: top_m,
             x: function (hour) { return left + (hour - 5) / 16 * (W - left - right); },
             y: function (metres) { return top + (1 - metres / top_m) * (H - top - bottom); },
             hour: function (px) { return 5 + (px - left) / (W - left - right) * 16; },
             metres: function (py) { return (1 - (py - top) / (H - top - bottom)) * top_m; } };
  }
  function airShade(speed) {
    return 'rgba(37,99,235,' + (0.08 + Math.min(speed / AIR_FULL, 1) * 0.8).toFixed(3) + ')';
  }
  function drawAir(canvas, profile, slot) {
    var frame = fit(canvas);
    if (!frame || !profile) return;
    var ctx = frame.ctx, f = airFrame(canvas, profile);
    var hourly = profile.hourly, ground = profile.elevation;
    ctx.clearRect(0, 0, f.W, f.H);
    var colW = (f.W - f.left - f.right) / 16;
    var cells = [];
    for (var hour = 5; hour <= 21; hour++) {
      var at = indexFor(hourly.time, state.day, hour);
      for (var m = Math.floor(ground / AIR_STEP) * AIR_STEP; m < f.top_m; m += AIR_STEP) {
        var lo = Math.max(m, ground), hi = Math.min(m + AIR_STEP, f.top_m);
        if (hi <= lo) continue;
        var sample = sampleProfile(hourly, at, (lo + hi) / 2, ground);
        if (!sample || sample.speed == null) continue;
        cells.push(sample.speed);
        ctx.fillStyle = airShade(sample.speed);
        var x0 = Math.max(f.x(hour) - colW / 2, f.left), x1 = Math.min(f.x(hour) + colW / 2, f.W - f.right);
        ctx.fillRect(x0, f.y(hi), x1 - x0 + 0.5, f.y(lo) - f.y(hi) + 0.5);
      }
    }
    // Cloud over the wind, grey, as a column per hour per level — the meteogram's cloud,
    // which this chart replaced. Grey reads over the blue in both themes, and the deeper
    // the cover the more of the wind under it is hidden, which is what a cloud does.
    var heights = levelSeries(hourly, 'geopotential_height');
    var clouds = levelSeries(hourly, 'cloud_cover');
    for (var ch = 5; ch <= 21; ch++) {
      var cat = indexFor(hourly.time, state.day, ch);
      for (var l = 0; l < conf.levels.length; l++) {
        var cover = clouds[l] ? clouds[l][cat] : null;
        var height = heights[l] ? heights[l][cat] : null;
        if (cover == null || height == null || cover < 5) continue;
        var band = (l === 0 ? 300 : Math.abs(heights[l][cat] - heights[l - 1][cat])) || 300;
        ctx.fillStyle = 'rgba(150,154,162,' + (Math.min(cover / 100, 1) * 0.7).toFixed(3) + ')';
        ctx.fillRect(f.x(ch) - colW / 2, f.y(height + band / 2), colW,
                     Math.abs(f.y(height - band / 2) - f.y(height + band / 2)));
      }
    }
    ctx.fillStyle = ink('--panel-2');
    ctx.fillRect(f.left, f.y(ground), f.W - f.left - f.right, f.H - f.bottom - f.y(ground));

    var box = { left: f.left, top: f.top, W: f.W, H: f.H, right: f.right, bottom: f.bottom };
    // Under a halo of the panel's colour: the takeoff's own series colour is blue for the
    // first takeoff, over a wind shaded in blue.
    hourLine(ctx, profile, f.x, f.y, boundaryLayer(profile), false, ink('--panel'), 5, box);
    var layer = hourLine(ctx, profile, f.x, f.y, boundaryLayer(profile), false,
                         seriesColour(slot), 2.4, box);
    var based = hourLine(ctx, profile, f.x, f.y, function (at) {
      return cloudbase(hourly.temperature_2m[at], hourly.dew_point_2m[at], ground);
    }, true, ink('--ink'), 1.5, box);

    // Arrows every two hours, every 500 m above the ground. Dark ink where the shading is
    // light and white where it is deep, so an arrow is never the colour of its cell.
    for (var h = 6; h <= 20; h += 2) {
      var idx = indexFor(hourly.time, state.day, h);
      for (var z = Math.ceil((ground + 150) / 500) * 500; z < f.top_m; z += 500) {
        var w = sampleProfile(hourly, idx, z, ground);
        if (!w || w.speed == null || w.dir == null) continue;
        var to = (w.dir + 180) * Math.PI / 180, len = 8;
        var cx = f.x(h), cy = f.y(z), dx = Math.sin(to) * len, dy = -Math.cos(to) * len;
        ctx.strokeStyle = ctx.fillStyle = w.speed / AIR_FULL > 0.45 ? '#fff' : ink('--ink');
        ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.moveTo(cx - dx, cy - dy); ctx.lineTo(cx + dx, cy + dy); ctx.stroke();
        var back = Math.atan2(dy, dx);
        ctx.beginPath();
        ctx.moveTo(cx + dx, cy + dy);
        ctx.lineTo(cx + dx - 5 * Math.cos(back - 0.45), cy + dy - 5 * Math.sin(back - 0.45));
        ctx.lineTo(cx + dx - 5 * Math.cos(back + 0.45), cy + dy - 5 * Math.sin(back + 0.45));
        ctx.closePath(); ctx.fill();
      }
    }

    // The hour the rest of the page is at.
    ctx.save();
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = ink('--ink-2');
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(f.x(state.hour), f.top); ctx.lineTo(f.x(state.hour), f.H - f.bottom);
    ctx.stroke();
    ctx.restore();

    gramAxes(ctx, f.x, f.y, f.top_m, f.left, f.right, f.bottom, f.W, f.H, 4);
    // Each line named at its evening end, where it has stopped moving, pushed apart when
    // the two end close together — which on a blue day they do.
    var named = [];
    if (layer && layer[1] > f.top) named.push({ y: layer[1], text: 'Boundary layer', colour: seriesColour(slot) });
    if (based && based[1] > f.top) named.push({ y: based[1], text: 'Cloudbase', colour: ink('--ink') });
    named.sort(function (a, b) { return a.y - b.y; });
    named.forEach(function (label, i) {
      label.y = Math.min(Math.max(label.y - 3, f.top + 26), f.H - f.bottom - 2);
      if (i && label.y - named[i - 1].y < 12) label.y = named[i - 1].y + 12;
      padded(ctx, label.text, f.W - f.right - 3, label.y, label.colour, 'right');
    });
    // The key: what the shading means, on the chart rather than in a caption nobody reads
    // twice.
    var kx = f.left + 4, ky = f.top + 4;
    ctx.font = '14px "Noto Sans", ui-sans-serif, sans-serif';
    var label = 'Wind 0 \u2192 ' + AIR_FULL + '+ m/s \u00b7 grey: cloud';
    var kw = ctx.measureText(label).width;
    ctx.globalAlpha = 0.88; ctx.fillStyle = ink('--panel');
    ctx.fillRect(kx - 2, ky - 1, kw + 52, 14); ctx.globalAlpha = 1;
    for (var k = 0; k < 40; k++) {
      ctx.fillStyle = airShade(k / 40 * AIR_FULL);
      ctx.fillRect(kx + k, ky + 2, 1.2, 9);
    }
    ctx.fillStyle = ink('--ink-3'); ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(label, kx + 46, ky + 1);
    canvas.dataset.cells = cells.length;
  }

  // The readout: the wind at the hour and height under the pointer.
  function bindAir(canvas, out, index) {
    function say(event) {
      var profile = state.profiles[index];
      if (!profile) return;
      var f = airFrame(canvas, profile), box = canvas.getBoundingClientRect();
      var hour = Math.round(f.hour(event.clientX - box.left));
      var metres = f.metres(event.clientY - box.top);
      if (hour < 5 || hour > 21 || metres < profile.elevation || metres > f.top_m) {
        out.textContent = ''; state.airProbe = null; return;
      }
      var w = sampleProfile(profile.hourly, indexFor(profile.hourly.time, state.day, hour),
                            metres, profile.elevation);
      state.airProbe = { hour: hour, metres: metres, speed: w && w.speed, dir: w && w.dir };
      out.textContent = ('0' + hour).slice(-2) + ':00 · ' + Math.round(metres / 50) * 50
        + ' m · ' + (w && w.speed != null
          ? w.speed.toFixed(1) + ' m/s from ' + compass(w.dir) + ' (' + Math.round(w.dir) + '°)'
          : 'no wind in the model here');
    }
    canvas.addEventListener('pointermove', say);
    canvas.addEventListener('pointerdown', say);
    canvas.addEventListener('pointerleave', function () {
      out.textContent = ''; state.airProbe = null;
    });
  }

  function drawSoundings() {
    Array.prototype.forEach.call(
      document.querySelectorAll('.met-col'), function (cell) {
        drawSounding(cell.querySelector('.met-col-sounding'),
                     state.profiles[Number(cell.dataset.site)]);
      });
  }

  // Where a parcel leaving the ground stops climbing: the dry adiabat from the surface
  // temperature against the model's own temperature profile. It rises while it is warmer
  // than the air around it and stops where the two meet, so this walks the pressure
  // levels for the first one where the parcel is no longer warmer and interpolates the
  // crossing between that level and the one below — linear in height, because both lines
  // are straight between two levels.
  //
  // Returns null in the two cases that are not a crossing, rather than a number that
  // would draw a marker somewhere arbitrary: a profile that never gets stable inside the
  // chart (the parcel is still warmer at the ceiling), and one already stable off the
  // deck, where there is no parcel climbing to find a top for. A 7 °C/km day is the
  // second of those — under the dry adiabat's 9.8, the air is stable to dry convection
  // from the ground up, and the honest drawing is no marker at all.
  function parcelTop(hourly, at, ground, ceiling) {
    var surface = hourly.temperature_2m[at];
    if (surface == null) return null;
    var heights = levelSeries(hourly, 'geopotential_height');
    var temps = levelSeries(hourly, 'temperature');
    var prevHeight = null, prevGap = null;
    for (var l = 0; l < conf.levels.length; l++) {
      var height = heights[l] ? heights[l][at] : null;
      var air = temps[l] ? temps[l][at] : null;
      if (height == null || air == null || height <= ground) continue;
      if (height > ceiling) break;
      var gap = (surface - DRY_LAPSE * (height - ground) / 1000) - air;
      if (prevGap !== null && prevGap > 0 && gap <= 0) {
        return prevHeight + prevGap / (prevGap - gap) * (height - prevHeight);
      }
      prevHeight = height; prevGap = gap;
    }
    return null;
  }

  // A label on a pad. The thermal top and the cloudbase land within a few metres of
  // each other on a lot of days, and each was then read against the other's line.
  function padded(ctx, text, x, y, colour, align) {
    ctx.font = '14px "Noto Sans", ui-sans-serif, sans-serif';
    ctx.textAlign = align;
    ctx.textBaseline = 'bottom';
    var width = ctx.measureText(text).width;
    // Never past the chart's left edge: a label hung to the left of a trace near it was
    // cut off there. It turns to hang right of the point instead.
    if (align === 'right' && x - width < 4) { align = 'left'; ctx.textAlign = 'left'; x = Math.max(x + 8, 4); }
    ctx.globalAlpha = 0.85;
    ctx.fillStyle = ink('--panel');
    ctx.fillRect(align === 'right' ? x - width - 3 : x - 3, y - 10, width + 6, 12);
    ctx.globalAlpha = 1;
    ctx.fillStyle = colour;
    ctx.fillText(text, x, y);
  }

  // The line under a sounding that says what its two thermal tops are, and — folded —
  // why there are two. Written only when it changes: the pointer redraws the sounding on
  // every move, and rewriting an open <details> would fight the reader's own tap.
  function drawTop(canvas, model, parcel) {
    var box = canvas.parentNode && canvas.parentNode.querySelector('.met-col-top');
    if (!box) return;
    var metres = function (value) { return Math.round(value).toLocaleString('en-GB')
      .replace(/,/g, '\u2009') + ' m'; };
    var MODEL = 'The model’s estimate (dashed) is where ECMWF’s own turbulence dies out; '
      + 'it counts thermals overshooting into the stable air and the wind stirring it. ';
    var PARCEL = 'The parcel’s (ring) lifts the 2 m air through this sounding (ICON) at '
      + DRY_LAPSE + ' °C/km until it is no warmer than the air around it, and counts '
      + 'neither. ';
    var text = null, ask = null, why = null;
    if (model != null && parcel != null) {
      var low = Math.min(model, parcel), high = Math.max(model, parcel);
      if (Math.abs(model - parcel) < 50) {
        text = 'Thermal top ' + metres((model + parcel) / 2) + ' (model and parcel agree)';
        ask = 'How is it estimated?';
        why = 'Two ways, and this hour they land together. ' + MODEL + PARCEL;
      } else {
        text = 'Thermal top ' + metres(low) + '–' + metres(high);
        ask = 'Why two numbers?';
        why = 'Two estimates of the same height. ' + MODEL + PARCEL
          + 'So the parcel usually comes out lower: read it as the cautious figure and the '
          + 'model as the generous one.';
      }
    } else if (model != null) {
      text = 'Thermal top ' + metres(model) + ' (model only)';
      ask = 'Why only one?';
      why = 'No dry parcel rises from the ground this hour: lifted at ' + DRY_LAPSE
        + ' °C/km, the 2 m air is already colder than the air above it, so the second '
        + 'estimate has nothing to mark. ' + MODEL + 'That is why it can still find mixing '
        + 'the parcel does not.';
    } else if (parcel != null) {
      text = 'Thermal top ' + metres(parcel) + ' (parcel only)';
      ask = 'Why only one?';
      why = 'ECMWF gives no boundary layer height for this hour, so only the parcel’s '
        + 'estimate is drawn. ' + PARCEL;
    }
    box.hidden = text === null;
    if (text === null || box.dataset.text === text) return;
    box.dataset.text = text;
    box.querySelector('.txt').textContent = text;
    box.querySelector('.info').setAttribute('aria-label', ask);
    box.querySelector('.info-pop').textContent = why;
  }


  function drawSounding(canvas, profile) {
    var frame = fit(canvas);
    if (!frame || !profile) return;
    var ctx = frame.ctx, W = frame.w, H = frame.h;
    var hourly = profile.hourly;
    var at = indexFor(hourly.time, state.day, state.hour);
    var ground = profile.elevation;
    var left = 34, right = 10, top = SOUND_TOP, bottom = SOUND_BOTTOM;
    var top_m = ceilingFor(ground), minT = -20, maxT = 35;
    canvas.__ceiling = top_m;
    // Wide enough for the coldest reading in the column: a dry day's dew point aloft, at
    // −30 °C and below, was drawn off the chart's left edge.
    var heights = levelSeries(hourly, 'geopotential_height');
    ['temperature', 'dew_point'].forEach(function (name) {
      levelSeries(hourly, name).forEach(function (series, l) {
        var value = series ? series[at] : null, height = heights[l] ? heights[l][at] : null;
        if (value == null || height == null || height < ground || height > top_m) return;
        minT = Math.min(minT, Math.floor(value / 10) * 10);
      });
    });
    function x(celsius) { return left + (celsius - minT) / (maxT - minT) * (W - left - right); }
    function y(metres) { return top + (1 - metres / top_m) * (H - top - bottom); }

    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = ink('--rule');
    ctx.fillStyle = ink('--ink-3');
    ctx.font = '14px "Noto Sans", ui-sans-serif, sans-serif';
    ctx.lineWidth = 1;
    for (var m = 0; m <= top_m; m += 1000) {
      ctx.beginPath(); ctx.moveTo(left, y(m)); ctx.lineTo(W - right, y(m)); ctx.stroke();
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText(m / 1000 + 'k', left - 4, y(m));
    }
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    // Every 10° on the usual range; every 20° when it reaches far below freezing, where
    // ten labels crowded into each other.
    var tick = maxT - minT > 60 ? 20 : 10;
    for (var c = Math.ceil(minT / tick) * tick; c <= 30; c += tick) {
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

    // **An absent lid is a statement, not a silence.** A day with nothing stable under
    // 4 km draws no band at all, which looks exactly like a chart that did not check —
    // and "no finding may assert something the run did not check" cuts both ways. So the
    // chart says which it is.
    if (!caps.length) {
      ctx.save();
      ctx.fillStyle = ink('--ink-3');
      ctx.font = '14px "Noto Sans", ui-sans-serif, sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText('No lid below ' + (top_m / 1000) + ' km', left + 4, top + 2);
      ctx.restore();
    }

    // The thermal top: the model's own answer for where the day stops, which is the
    // number a pilot came to this chart for. It was on the meteogram and in the table
    // and not here — so on a day with no capping layer to shade, the one chart about
    // the shape of the column said nothing about the top of it.
    var blh = hourly.boundary_layer_height[at];
    if (blh != null && ground + blh > ground && ground + blh < top_m) {
      var thermalTop = ground + blh;
      // **Neutral, not a third hue.** Two colours on this chart are *measurements* —
      // red temperature, blue dew point — and everything else on it is a construction:
      // the adiabat, the cloudbase, this. Drawing the thermal top in #eb6834 put it
      // ΔE 11.8 from the temperature trace on the skill's validator, under the 15 floor
      // for normal vision in both themes: two orange-red lines nobody can separate. The
      // constructions are told apart by their dash pattern and their label, which is
      // what the meteogram's cloudbase already does.
      ctx.save();
      ctx.strokeStyle = ink('--ink-2');
      ctx.setLineDash([6, 3]);
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(left, y(thermalTop)); ctx.lineTo(W - right, y(thermalTop));
      ctx.stroke();
      ctx.setLineDash([]);
      padded(ctx, 'Thermal top · model', left + 4, y(thermalTop) - 2, ink('--ink-2'), 'left');
      ctx.restore();
    }

    // The cloudbase, drawn where the figures below already print it.
    var base = cloudbase(hourly.temperature_2m[at], hourly.dew_point_2m[at], ground);
    if (base != null && base > ground && base < top_m) {
      ctx.save();
      ctx.strokeStyle = ink('--ink-3');
      ctx.setLineDash([2, 3]);
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(left, y(base)); ctx.lineTo(W - right, y(base));
      ctx.stroke();
      ctx.setLineDash([]);
      padded(ctx, 'Cloudbase', W - right - 3, y(base) - 2, ink('--ink-3'), 'right');
      ctx.restore();
    }

    // The dry adiabat from the surface temperature, and the whole visual answer to "where
    // does the thermal top come from". A parcel leaving the ground at the surface
    // temperature cools at 9.8 °C/km whatever the air around it does; it keeps rising for
    // as long as it stays warmer than that air, and stops where the two meet. So the
    // adiabat is drawn from the surface up to that crossing and marked there, and the gap
    // between the two lines on the way up is the day's strength.
    //
    // **The dashed `thermal top` is not this crossing, and must not be drawn as if it
    // were.** That line is the model's own convective boundary layer height — it knows
    // the day's heating, the wind's mixing and the entrainment at the top, none of which
    // a hand construction off one profile can see. Drawing them both is the honest
    // version: usually they land within a hundred metres of each other, and where they do
    // not, the reader can see the disagreement rather than being handed one number.
    var surface = hourly.temperature_2m[at];
    var parcel = parcelTop(hourly, at, ground, top_m);
    if (surface != null) {
      var end = parcel == null ? top_m : parcel;
      ctx.save();
      ctx.strokeStyle = '#eb6834'; ctx.globalAlpha = 0.45; ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x(surface), y(ground));
      ctx.lineTo(x(surface - DRY_LAPSE * (end - ground) / 1000), y(end));
      ctx.stroke();
      ctx.restore();
      if (parcel != null) {
        // The crossing itself. A ring rather than a fourth full-width rule: the chart
        // already carries three of those, and what this marks is one *point* — the height
        // where the two lines meet — not a level across the whole frame.
        ctx.save();
        ctx.strokeStyle = '#eb6834'; ctx.globalAlpha = 0.9; ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.arc(x(surface - DRY_LAPSE * (parcel - ground) / 1000), y(parcel), 4, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
        padded(ctx, 'Thermal top · parcel',
               x(surface - DRY_LAPSE * (parcel - ground) / 1000) - 7, y(parcel) - 5,
               ink('--ink-2'), 'right');
      }
    }

    // Returns where the trace ends at the top, for its label.
    function trace(values, dashed, colour) {
      ctx.save();
      ctx.beginPath();
      ctx.setLineDash(dashed ? [4, 3] : []);
      ctx.strokeStyle = colour; ctx.lineWidth = 2;
      var started = false, end = null;
      for (var l = 0; l < conf.levels.length; l++) {
        var height = heights[l] ? heights[l][at] : null;
        var value = values[l] ? values[l][at] : null;
        if (height == null || value == null || height < ground || height > top_m) continue;
        if (!started) { ctx.moveTo(x(value), y(height)); started = true; }
        else ctx.lineTo(x(value), y(height));
        end = [x(value), y(height)];
      }
      ctx.stroke();
      ctx.restore();
      return end;
    }
    var tEnd = trace(levelSeries(hourly, 'temperature'), false, '#c2410c');
    var dEnd = trace(levelSeries(hourly, 'dew_point'), true, '#2f6fb3');
    // Named where they end, which is where the two lines are furthest apart on any day
    // worth flying — the dew point is the one on the left.
    if (tEnd) padded(ctx, 'Temp', tEnd[0] + 4, tEnd[1] + 12, '#c2410c', 'left');
    if (dEnd) padded(ctx, 'Dew point', dEnd[0] - 4, dEnd[1] + 12, '#2f6fb3', 'right');

    // What this chart ended up saying, for a test to assert on rather than a screenshot
    // failing to. `view3d.rose()` is the same idea and exists for the same reason: a
    // wrong arrow is still an arrow, and a missing lid looks exactly like a chart that
    // did not look for one.
    drawTop(canvas, blh == null ? null : ground + blh, parcel);

    canvas.__drawn = {
      caps: caps.length,
      thermalTop: blh == null ? null : Math.round(ground + blh),
      parcelTop: parcel == null ? null : Math.round(parcel),
      cloudbase: base == null ? null : Math.round(base),
      ground: Math.round(ground)
    };

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
      lines.push(here.speed.toFixed(1) + ' m/s from ' + compass(here.dir)
                 + ' (' + Math.round(here.dir) + '°)');
    }
    ctx.font = '15px "Noto Sans", ui-sans-serif, sans-serif';
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
  // flymet's own meteogram for the airfield nearest each takeoff, in that takeoff's column
  // under its charts: side by side, three of them were 2 500 px of scrolling when they
  // were stacked full width under the columns. A thumbnail at the column's width; the
  // full picture is a tap away.
  function drawFlymet() {
    var template = state.day === 0 ? conf.flymet.today
      : (state.day === 1 ? conf.flymet.tomorrow : null);
    // Stamped with the hour. flymet sends no cache lifetime, so a browser is free to
    // guess one from the file's age — and today's meteogram is regenerated through the
    // day, which makes a guessed cache an old picture under a current heading. The stamp
    // is the hour and not the minute, so it is still one fetch an hour and not one a view.
    var stamp = new Date();
    var hour = stamp.getFullYear() + ('0' + (stamp.getMonth() + 1)).slice(-2)
      + ('0' + stamp.getDate()).slice(-2) + ('0' + stamp.getHours()).slice(-2);
    document.querySelectorAll('#met-columns .met-col').forEach(function (cell) {
      var index = Number(cell.dataset.site);
      var figure = cell.querySelector('.met-col-fly');
      var near = (conf.flymet.near || [])[index];
      if (!figure) return;
      if (!near || !template) { figure.hidden = true; figure.textContent = ''; delete figure.dataset.key; return; }
      // Rebuilt only when what it shows changes — the hour slider redraws this panel on
      // every step, and reassigning `src` makes the picture blink. The day is in the key:
      // without it, tomorrow kept today's picture under a tomorrow heading.
      var key = near.slug + '|' + state.day + '|' + hour;
      if (figure.dataset.key === key) return;
      figure.dataset.key = key;
      figure.hidden = false;
      figure.textContent = '';
      var url = template.replace('{slug}', encodeURIComponent(near.slug)) + '?h=' + hour;
      var image = document.createElement('img');
      image.loading = 'lazy';
      image.alt = 'flymet meteogram for ' + near.name + ', ' + (state.day === 0 ? 'today' : 'tomorrow');
      image.src = url;
      figure.appendChild(image);
      var caption = document.createElement('figcaption');
      var credit = document.createElement('span');
      var link = document.createElement('a');
      link.href = conf.flymet.index;
      link.rel = 'noreferrer';
      link.textContent = 'flymet';
      credit.appendChild(link);
      credit.appendChild(document.createTextNode(' · ' + near.name + ' · ' + near.km + ' km'));
      caption.appendChild(credit);
      var open = document.createElement('a');
      open.className = 'lnk';
      open.href = url;
      open.target = '_blank';
      open.rel = 'noreferrer';
      open.innerHTML = EXPAND_ICON + 'Enlarge';
      caption.appendChild(open);
      figure.appendChild(caption);
      image.onerror = function () {
        image.hidden = true;
        open.hidden = true;
        credit.textContent = 'flymet has no meteogram for ' + near.name + ' just now.';
      };
    });
  }

  function drawSite() {
    var panel = document.getElementById('met-panel');
    var picked = chosen();
    panel.hidden = !picked.length;
    document.getElementById('met-sub').textContent = picked.length > 1
      ? picked.length + ' takeoffs, the same hour and the same model'
      : '';
    if (!picked.length) {
      drawKeys();
      return;
    }
    drawStrip();
    drawColumns();
    drawFlymet();
    drawKeys();
  }

  // One profile per chosen takeoff, fetched once and kept. Three requests where there
  // used to be one, and they are the reason the surface call is separate: asking for the
  // pressure levels of every takeoff to rank them would be megabytes spent to
  // answer a question about three hills.
  function loadProfiles() {
    var wanted = chosen().filter(function (index) { return !state.profiles[index]; });
    if (!wanted.length) return;
    var names = wanted.map(function (index) { return conf.sites[index].name; });
    say('Fetching the sounding for ' + names.join(', ') + '…');
    var failed = [];
    Promise.all(wanted.map(function (index) {
      return get(profileUrl(conf.sites[index])).then(unpack).then(function (answer) {
        // Still chosen? A reader who drops a takeoff while its sounding is in the air
        // should not have it reappear when the answer lands.
        if (slotOf(index) < 0) return;
        state.profiles[index] = answer;
        if (index === state.site) state.profile = answer;
      }).catch(function (error) {
        failed.push(conf.sites[index].name + ' (' + error.message + ')');
      });
    })).then(function () {
      say(failed.length ? 'No sounding for ' + failed.join(', ') : '');
      drawCompare();
      drawSite();
    });
  }

  // Hover on a mouse, drag-to-read on a touchscreen. The same split the airspace map
  // makes, and for the same reason: a touchscreen's pointerout means the finger lifted,
  // not that the reader stopped wanting the number.
  //
  // Bound per sounding, and every one of them writes the *same* `state.probe`, so
  // pointing at 1 500 m on one hill reads 1 500 m on all of them. `probeX` stays
  // per-pointer, because the readout box follows the pointer sideways on the chart it is
  // over and would otherwise be drawn off the edge of its neighbours.
  function bindProbe(canvas) {
    function read(event) {
      var box = canvas.getBoundingClientRect();
      var y = event.clientY - box.top;
      var plot = box.height - SOUND_TOP - SOUND_BOTTOM;
      state.probe = (1 - (y - SOUND_TOP) / plot) * (canvas.__ceiling || SOUND_CEILING);
      state.probeX = event.clientX - box.left;
      drawSoundings();
    }
    function clear() { state.probe = null; drawSoundings(); }
    canvas.addEventListener('pointermove', function (event) {
      if (event.pointerType === 'touch' && !event.buttons) return;
      read(event);
    });
    canvas.addEventListener('pointerdown', function (event) {
      if (event.pointerType !== 'touch') return;
      // Held rather than tapped: a finger dragged up the chart reads it off, and lifting
      // it puts the readout away. `preventDefault` stops the long-press menu and the
      // text-selection gesture; the page not scrolling underneath is `touch-action:
      // none` in the stylesheet, which is the only thing that actually stops it — a
      // `preventDefault` on a move the browser has already begun scrolling with is too
      // late by then.
      event.preventDefault();
      // **Read first, capture second, and never let the capture stop the read.**
      // `setPointerCapture` throws on a pointer the browser does not have live — which
      // is any synthetic one, and also a real one that has already been released — and
      // it used to run first, so the throw took the reading with it. Capture is what
      // keeps the *rest of the drag* coming to this canvas; the first touch does not
      // need it, and a chart that shows nothing when a finger lands on it is a chart
      // that looks broken.
      read(event);
      try {
        canvas.setPointerCapture(event.pointerId);
      } catch (error) { /* the drag still reads; it just is not captured */ }
    });
    canvas.addEventListener('pointerup', clear);
    canvas.addEventListener('pointercancel', clear);
    canvas.addEventListener('pointerleave', function (event) {
      if (event.pointerType !== 'touch') clear();
    });
  }

  // ---- the picker's controls -----------------------------------------------------------
  //
  // A real `<dialog>`: Escape closes it, the backdrop closes it, focus stays inside it
  // and the page behind it is inert — four behaviours a hand-rolled overlay has to
  // reimplement and usually gets two of. `showModal` is missing only on browsers old
  // enough that the fallback matters more than the polish, and there it opens inline.
  var search = document.getElementById('met-search');

  function openPicker() {
    state.search = '';
    search.value = '';
    drawList();
    if (modal.showModal) modal.showModal(); else modal.setAttribute('open', '');
    // Not focused on a touchscreen: raising the keyboard covers the list the reader
    // came here to look at, and they can tap the field if they want to type.
    if (!window.matchMedia('(hover: none)').matches) search.focus();
  }
  function closePicker() {
    if (modal.close) modal.close(); else modal.removeAttribute('open');
  }

  document.getElementById('met-add').onclick = openPicker;
  document.getElementById('met-close').onclick = closePicker;
  document.getElementById('met-done').onclick = closePicker;
  // Clicking the backdrop. A dialog's own box is the click target for everything inside
  // it, so "outside" is a click whose coordinates fall beyond its rectangle.
  modal.addEventListener('click', function (event) {
    if (event.target !== modal) return;
    var box = modal.getBoundingClientRect();
    var outside = event.clientX < box.left || event.clientX > box.right
      || event.clientY < box.top || event.clientY > box.bottom;
    if (outside) closePicker();
  });
  search.addEventListener('input', function () {
    state.search = search.value;
    drawList();
  });
  document.getElementById('met-list').addEventListener('click', function (event) {
    var button = event.target.closest('.met-site');
    if (!button) return;
    toggle(Number(button.dataset.index));
  });

  var hourInput = document.getElementById('met-hour-input');
  hourInput.addEventListener('input', function () {
    state.hour = Number(hourInput.value);
    document.getElementById('met-hour-readout').textContent = state.hour + ':00';
    drawTime();
  });
  // Debounced, because a canvas redraw per resize event is what makes a window drag
  // stutter — and three profiles' worth of lines is three times the redraw it was.
  var resizing = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizing);
    resizing = setTimeout(drawSite, 120);
  });

  // Exposed for tests, and only what a test cannot reach any other way: the two rules
  // that read a sounding, the state the pointer writes into, and a redraw. Everything
  // else about this page is observable in the DOM. The alternative was a second copy of
  // the capping rule in Python, and two copies of a rule drift apart.
  window.__meteo = {
    state: state,
    // The one judgement this page makes. Exposed so a test can drive *it* rather than a
    // second copy of it written in Python — `docs/meteo.md` has been asking for that
    // since the harness that makes it possible existed.
    verdict: verdict,
    cappingLayers: cappingLayers,
    sampleProfile: sampleProfile,
    drawAir: drawAir,
    cloudbase: cloudbase,
    draw: drawSite,
    // The multi-site controls, so a browser test can drive the page the way a reader
    // does rather than reaching into `state` and hoping the redraws follow.
    open: openPicker,
    add: toggle,
    drop: drop,
    focus: focus,
    chosen: chosen,
    move: moveTo,
    at: function () { return indexFor(state.profile.hourly.time, state.day, state.hour); }
  };

  drawDays();
  recall();
  drawChosen();
  drawSite();
  loadRuns();
  get(surfaceUrl()).then(function (answer) {
    state.surface = Array.isArray(answer) ? answer : [answer];
    say('');
    drawModel();
    drawList();
    // Open the best takeoff of the day rather than an empty page: this page's answer to
    // "is it worth going anywhere" is a sounding, and making the reader pick a hill
    // before it will show them one hides the point. Only on a first visit — a reader who
    // has chosen their own hills is not shown a fourth one they did not ask for.
    if (!chosen().length) {
      var first = document.querySelector('.met-site');
      if (first) toggle(Number(first.dataset.index));
    } else {
      drawCompare();
      loadProfiles();
    }
  }).catch(function (error) {
    say('The forecast could not be fetched (' + error.message + '). '
        + 'This page has no numbers of its own — it needs a network.');
  });
})();

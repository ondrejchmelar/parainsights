(function () {
  var holder = document.querySelector('[data-planner]');
  if (!holder) return;
  var panel = holder.querySelector('.view3d-panel');
  if (!panel) return;
  // The map is the airspace map's: `airspaces.render_html.SCRIPT3D` builds it once and
  // publishes the handle here, so the two halves of the page share one view.
  (window.__airspaceMap || Promise.resolve(null))
    .then(function (handle) { if (handle) plan(handle); },
          function () { /* the panel says why */ });

  function plan(handle) {
  var box = panel.querySelector('.view3d');

  var FAI_MIN_SIDE = __FAI_MIN_SIDE__;
  // Two rule sets, chosen under the map. XContest world: the report's own (`js/xc.js`).
  // ČPP, the Czech cup on XContest (xcontest.org/cesko/pravidla): a closed course must
  // close within 5 per cent of the perimeter, not 20, and in the Central European zone
  // (V4, Austria, Germany north of 48.5°) a flat triangle scores 1.8 and an FAI one 2.2.
  var RULES = {
    world: { closing: __MAX_CLOSING__, multiplier: __MULTIPLIER__ },
    cpp: { closing: 0.05, multiplier: { open: 1.0, flat: 1.8, fai: 2.2 } }
  };
  function rules() {
    var pick = document.getElementById('plan-rules');
    return RULES[pick && pick.value] || RULES.world;
  }
  var points = [];          // [lon, lat] per turnpoint, in the order dropped
  // Undo and redo: the turnpoints before each change (a point dropped, one dragged, an
  // import, a clear), and the ones undone. A new change forgets what was undone.
  var past = [], future = [];
  function remember() {
    past.push(points.map(function (p) { return p.slice(); }));
    if (past.length > 200) past.shift();
    future = [];
  }

  // ---- geodesy -----------------------------------------------------------------------
  //
  // The FAI sphere, because that is what a scored distance is measured on — the same
  // choice, and the same reason, as `tracklog_viewer/geo.py`. The airspace half of this
  // page works on WGS84 and the two must not be confused: one measures a task, the other
  // draws a boundary.
  var R = 6371000;
  function distance(a, b) {
    var la1 = a[1] * Math.PI / 180, la2 = b[1] * Math.PI / 180;
    var dla = la2 - la1, dlo = (b[0] - a[0]) * Math.PI / 180;
    var h = Math.sin(dla / 2) * Math.sin(dla / 2)
      + Math.cos(la1) * Math.cos(la2) * Math.sin(dlo / 2) * Math.sin(dlo / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  // ---- the route -----------------------------------------------------------------------
  //
  // What the reader drew, walked in order, and it is defined once because three parts of
  // this page consume it: the line on the map, the airspace it crosses, and the number
  // under it. They disagreed. A three-point route drew as two legs and was checked
  // against airspace as two legs, while the score closed it into a triangle nobody had
  // asked for and added a third side — 250 km of drawn course reported as 397 km, and
  // scored a flat triangle at x1.2 with a "closing gap" of zero that was an assumption
  // rather than a measurement. Closing a course is the reader's to declare, so the box
  // says it and everything here reads the box.
  function course() {
    var walk = points.slice(0);
    if (points.length > 2 && document.getElementById('plan-close').checked) {
      walk.push(points[0]);
    }
    return walk;
  }

  // ---- what the line crosses -----------------------------------------------------------
  //
  // The reason this planner draws on the airspace map at all. A line that looks like a
  // good 60 km and clips the corner of a TMA is not a plan, and the map alone does not
  // answer it: at the zoom a whole task fits into, a 2 km overlap is two pixels.
  //
  // Exact, not sampled. For each leg and each ring, every crossing of the segment with a
  // ring edge is collected as a parameter along the segment; the parameters are sorted,
  // and the midpoint of each resulting interval is tested for being inside. That gives
  // the intervals the leg spends inside the ring, and their lengths are real kilometres
  // rather than a count of sample points that happened to land in it. The cheaper way —
  // walking the leg at some spacing and counting the samples inside — was not taken
  // because its error is worst exactly where the answer matters: a long leg brushing a
  // small zone can pass between two samples and be reported as clear.
  function pointInRing(lon, lat, ring) {
    var inside = false;
    var n = ring.lon.length;
    for (var i = 0, j = n - 1; i < n; j = i++) {
      var yi = ring.lat[i], yj = ring.lat[j];
      if ((yi > lat) === (yj > lat)) continue;
      var x = ring.lon[i] + (lat - yi) / (yj - yi) * (ring.lon[j] - ring.lon[i]);
      if (lon < x) inside = !inside;
    }
    return inside;
  }

  // Where along `a`→`b` the segment is inside `ring`, as a fraction of its length.
  function fractionInside(a, b, ring) { return inside(a, b, ring).fraction; }
  // The same, and where along it (0–1) it first goes in.
  function inside(a, b, ring) {
    var ts = [0, 1];
    var n = ring.lon.length;
    var dx = b[0] - a[0], dy = b[1] - a[1];
    for (var i = 0, j = n - 1; i < n; j = i++) {
      var ex = ring.lon[i] - ring.lon[j], ey = ring.lat[i] - ring.lat[j];
      var denominator = dx * ey - dy * ex;
      if (!denominator) continue;             // parallel, and a grazing edge is not entry
      var px = ring.lon[j] - a[0], py = ring.lat[j] - a[1];
      var t = (px * ey - py * ex) / denominator;
      var u = (px * dy - py * dx) / denominator;
      if (t > 0 && t < 1 && u >= 0 && u <= 1) ts.push(t);
    }
    if (ts.length === 2) {
      // No crossing at all: either wholly inside or wholly outside.
      return pointInRing(a[0] + dx / 2, a[1] + dy / 2, ring) ? { fraction: 1, first: 0 }
                                                             : { fraction: 0, first: null };
    }
    ts.sort(function (x, y) { return x - y; });
    var total = 0, first = null;
    for (var k = 1; k < ts.length; k++) {
      var mid = (ts[k - 1] + ts[k]) / 2;
      if (pointInRing(a[0] + dx * mid, a[1] + dy * mid, ring)) {
        total += ts[k] - ts[k - 1];
        if (first === null) first = ts[k - 1];
      }
    }
    return { fraction: total, first: first };
  }

  // A leg's worth of ground is only ever compared against rings whose own bounding box it
  // could reach. 743 airspaces times a few thousand edges is otherwise recomputed on every
  // turnpoint, and the box test throws away all but a handful.
  function ringBox(ring) {
    if (ring.__box) return ring.__box;
    var west = Infinity, east = -Infinity, south = Infinity, north = -Infinity;
    for (var i = 0; i < ring.lon.length; i++) {
      if (ring.lon[i] < west) west = ring.lon[i];
      if (ring.lon[i] > east) east = ring.lon[i];
      if (ring.lat[i] < south) south = ring.lat[i];
      if (ring.lat[i] > north) north = ring.lat[i];
    }
    ring.__box = { west: west, east: east, south: south, north: north };
    return ring.__box;
  }

  function crossings() {
    var rings = allRings();
    if (!rings.length || points.length < 2) return [];
    var walk = course(), legs = [];
    for (var i = 1; i < walk.length; i++) legs.push([walk[i - 1], walk[i]]);

    var found = {}, along = 0;
    legs.forEach(function (leg) {
      var length = distance(leg[0], leg[1]), start = along;
      along += length;
      var west = Math.min(leg[0][0], leg[1][0]), east = Math.max(leg[0][0], leg[1][0]);
      var south = Math.min(leg[0][1], leg[1][1]), north = Math.max(leg[0][1], leg[1][1]);
      rings.forEach(function (ring) {
        var box = ringBox(ring);
        if (box.east < west || box.west > east || box.north < south || box.south > north) {
          return;
        }
        var span = inside(leg[0], leg[1], ring), fraction = span.fraction;
        if (fraction <= 0) return;
        // Keyed by name: one CTR is published as several rings and one okruh is two
        // rectangles, and a list that says "LKPR CTR" four times is a list nobody reads.
        var seen = found[ring.n];
        if (!seen) found[ring.n] = seen = { name: ring.n, k: ring.k, f: ring.f,
                                            g: ring.g, w: ring.w, act: ring.act, off: ring.off,
                                            metres: 0, at: Infinity };
        seen.metres += fraction * length;
        seen.at = Math.min(seen.at, start + span.first * length);
        seen.f = Math.min(seen.f, ring.f);
      });
    });
    // In the order the task reaches them, as a pilot meets them flying it (October 2026:
    // it was the lowest floor first).
    return Object.keys(found).map(function (key) { return found[key]; })
      .sort(function (a, b) { return a.at - b.at || a.f - b.f; });
  }

  // The whole list is always shown, even when the map has hidden a field for being
  // shut. The map is decluttering; the list is the answer, and an answer that quietly
  // drops a zone because a VFR manual page said "SAT, SUN, HOL" is not one.
  // How much of the route runs where the map has no airspace to check it against.
  var coverage = JSON.parse(
    (document.getElementById('plan-coverage') || {}).textContent || 'null');
  // Checked where the route is inside Czechia (this page's own zones) or inside a
  // country whose layer has been loaded for it (`loadNear`); measured on 100 points a leg.
  function uncheckedMetres() {
    if (!coverage) return 0;
    var walk = course(), metres = 0, boxes = loadedBoxes();
    for (var i = 1; i < walk.length; i++) {
      var a = walk[i - 1], b = walk[i], length = distance(a, b), missing = 0, n = 100;
      for (var k = 0; k < n; k++) {
        var p = [a[0] + (b[0] - a[0]) * (k + 0.5) / n, a[1] + (b[1] - a[1]) * (k + 0.5) / n];
        if (pointIn(coverage, p)) continue;
        if (boxes.some(function (bb) { return p[0] >= bb[0] && p[0] <= bb[1] && p[1] >= bb[2] && p[1] <= bb[3]; })) continue;
        missing++;
      }
      metres += missing / n * length;
    }
    return metres;
  }
  function pointIn(ring, p) {
    var inside = false, n = ring.lon.length;
    for (var i = 0, j = n - 1; i < n; j = i++) {
      var yi = ring.lat[i], yj = ring.lat[j];
      if ((yi > p[1]) !== (yj > p[1]) &&
          p[0] < (ring.lon[j] - ring.lon[i]) * (p[1] - yi) / (yj - yi) + ring.lon[i]) inside = !inside;
    }
    return inside;
  }

  // ---- the airspace near the task -----------------------------------------------------
  //
  // The map starts empty and draws only the zones within NEAR of the task's legs (October
  // 2026): the whole of Czechia's 763 zones over the map hid the ground a task is planned
  // on, and the zones a task does not go near say nothing about it. Not only Czechia's:
  // where the task reaches another country, that country's layer (`airspaces/openaip.py`,
  // the same files a flight's map loads, `view3d.loadAirspace`) is fetched for it.
  // Czechia's own come from this page, which carries more than its layer — the circuits.
  var NEAR = 10000;         // 5 km until October 2026: too tight to see what is coming
  var LAYERS = ((document.querySelector('meta[name="airspace-layers"]') || {}).content) || 'layers/';
  var OWN_FILES = /^(CZ|cz-circuits)\.json$/;
  var remote = {};          // file name -> { bbox: [w, e, s, n], rings }
  function loadedBoxes() {
    return Object.keys(remote).map(function (name) { return remote[name].bbox; })
      .filter(function (bb) { return bb; });
  }
  function allRings() {
    var out = (handle.scene().airspaces || []).slice();
    Object.keys(remote).forEach(function (name) { out = out.concat(remote[name].rings); });
    return out;
  }
  function decodeRing(ring) {
    if (!ring.enc) return ring;
    var lon = [], lat = [], x = 0, y = 0;
    for (var i = 0; i < ring.lon.length; i++) {
      x += ring.lon[i]; y += ring.lat[i];
      lon.push(x / ring.enc); lat.push(y / ring.enc);
    }
    var out = {};
    Object.keys(ring).forEach(function (k) { if (k !== 'enc') out[k] = ring[k]; });
    out.lon = lon; out.lat = lat;
    return out;
  }
  // The task's box, NEAR wider all round, as [w, e, s, n].
  function taskBox() {
    var walk = course(), w = Infinity, e = -Infinity, so = Infinity, n = -Infinity;
    walk.forEach(function (p) { w = Math.min(w, p[0]); e = Math.max(e, p[0]); so = Math.min(so, p[1]); n = Math.max(n, p[1]); });
    var my = NEAR / 111320, mx = NEAR / (111320 * Math.cos((so + n) / 2 * Math.PI / 180));
    return [w - mx, e + mx, so - my, n + my];
  }
  // Fetch the layers of the countries the task's box reaches and has not yet loaded.
  // Resolves true when something new arrived.
  function loadNear() {
    if (points.length < 2 || typeof airspaceJson !== 'function') return Promise.resolve(false);
    var bb = taskBox();
    return airspaceJson(LAYERS + 'index.json').then(function (index) {
      var files = index.files || {};
      var wanted = Object.keys(files).filter(function (name) {
        var f = files[name].bbox;
        return !OWN_FILES.test(name) && !remote[name] && f &&
          !(f[1] < bb[0] || f[0] > bb[1] || f[3] < bb[2] || f[2] > bb[3]);
      });
      if (!wanted.length) return false;
      return Promise.all(wanted.map(function (name) {
        return airspaceJson(LAYERS + name).then(function (file) {
          remote[name] = { bbox: files[name].bbox, rings: (file.airspaces || []).map(decodeRing) };
        }, function () { remote[name] = { bbox: null, rings: [] }; });
      })).then(function () { return true; });
    }, function () { return false; });
  }
  // Metres from a point to a ring: 0 inside, else to its nearest edge.
  function metresTo(ring, p) {
    var kx = 111320 * Math.cos(p[1] * Math.PI / 180), ky = 111320, best = Infinity, n = ring.lon.length;
    for (var a = 0, b = n - 1; a < n; b = a++) {
      var ax = (ring.lon[a] - p[0]) * kx, ay = (ring.lat[a] - p[1]) * ky;
      var bx = (ring.lon[b] - p[0]) * kx, by = (ring.lat[b] - p[1]) * ky;
      var dx = bx - ax, dy = by - ay, len = dx * dx + dy * dy;
      var t = len ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len)) : 0;
      best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
    }
    return pointIn(ring, p) ? 0 : best;
  }
  // The zones within NEAR of the task: its legs sampled every kilometre.
  var nearNow = [];
  function nearTask() {
    if (points.length < 2) return [];
    var walk = course(), samples = [];
    for (var i = 1; i < walk.length; i++) {
      var a = walk[i - 1], b = walk[i], n = Math.max(1, Math.ceil(distance(a, b) / 1000));
      for (var k = 0; k <= n; k++) samples.push([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n]);
    }
    return allRings().filter(function (ring) {
      var box = ringBox(ring), my = NEAR / 111320;
      var mx = NEAR / (111320 * Math.cos((box.south + box.north) / 2 * Math.PI / 180));
      for (var s = 0; s < samples.length; s++) {
        var p = samples[s];
        if (p[0] < box.west - mx || p[0] > box.east + mx || p[1] < box.south - my || p[1] > box.north + my) continue;
        if (metresTo(ring, p) <= NEAR) return true;
      }
      return false;
    });
  }
  function showNear() {
    nearNow = nearTask();
    var merged = mergedEntry();
    if (merged && merged.setAirspaces) merged.setAirspaces(nearNow);
    if (window.__aspRefilter) window.__aspRefilter();
  }
  // What the map's airspace menu counts: these, not the page's whole payload.
  handle.drawnAirspaces = function () { return nearNow; };
  window.__plannerTask = function () { return points.length >= 2 ? xctrackTask() : null; };
  // For the tests: the import path a file, a code and a QR code all end in.
  window.__plannerImport = function (text) { return readTask(text).then(function (task) { importTask(task, 'a test'); return points.length; }); };
  handle.planned = function () { return points.length >= 2; };
  var loading = null;
  function refreshAirspace() {
    showNear();
    if (loading) return;
    loading = loadNear().then(function (arrived) {
      loading = null;
      if (arrived) { showNear(); reportAirspace(); refreshAirspace(); }
    });
  }

  function reportAirspace() {
    var box = document.getElementById('plan-airspace');
    var crossed = crossings();
    box.innerHTML = '';
    if (points.length < 2) return;
    var outside = uncheckedMetres();
    var total = 0, walk = course();
    for (var w = 1; w < walk.length; w++) total += distance(walk[w - 1], walk[w]);
    if (outside > 50) {
      var gap = document.createElement('p');
      gap.className = 'plan-clear plan-unchecked';
      var wholly = outside >= total - 50;
      gap.textContent = wholly
        ? 'This route is outside ' + coverage.name + ', and this map has no airspace '
          + 'there — nothing on it has been checked.'
        : (outside / 1000).toFixed(1) + ' km of this route is outside ' + coverage.name
          + ', where this map has no airspace — that part has not been checked.';
      box.appendChild(gap);
      if (wholly) return;
    }
    if (!crossed.length) {
      var clear = document.createElement('p');
      clear.className = 'plan-clear';
      clear.textContent = 'Nothing on this map is crossed by the route. That is the '
        + 'drawn airspace only — check the NOTAMs.';
      box.appendChild(clear);
      return;
    }
    var colours = handle.scene().airspaceColours || {};
    var when = window.aspHours ? window.aspHours.chosen() : null;
    var holidays = window.aspHours ? window.aspHours.holidays() : {};
    var shut = 0, off = 0, booked = 0;
    function tag(state, text, title) {
      var span = document.createElement('span');
      span.className = 'plan-when ' + state;
      span.textContent = text;
      if (title) span.title = title;
      return span;
    }
    var heading = document.createElement('p');
    heading.className = 'plan-crossed-head';
    heading.textContent = crossed.length + (crossed.length === 1
      ? ' airspace crossed, in the order the task reaches it'
      : ' airspaces crossed, in the order the task reaches them');
    box.appendChild(heading);
    var list = document.createElement('ul');
    list.className = 'plan-crossed';
    crossed.forEach(function (item) {
      var row = document.createElement('li');
      var swatch = document.createElement('span');
      swatch.className = 'plan-swatch';
      swatch.style.background = colours[item.k] || '#888';
      var name = document.createElement('span');
      name.className = 'plan-crossed-name';
      name.textContent = item.name;
      var much = document.createElement('span');
      much.className = 'plan-crossed-km';
      much.textContent = (item.metres / 1000).toFixed(1) + ' km through'
        + (item.g ? ', from the ground' : ', floor ' + Math.round(item.f) + ' m');
      row.appendChild(swatch);
      row.appendChild(name);
      row.appendChild(much);
      // Only a ring that carries hours can be marked, and only when a time was asked
      // for. Everything else says nothing, which is the truth about it.
      var hours = window.aspHours;
      if (hours && hours.inactive(item, when)) {
        // Its published off-season: not there at all on this date.
        row.appendChild(tag('is-shut', 'inactive ' + hours.offLabel(item.off),
                            'Published inactive ' + hours.offLabel(item.off) + ' every year.'));
        row.classList.add('is-shut');
        off++;
      } else if (hours && hours.activatedBy(item)) {
        // Booked, not scheduled: a date cannot say, so it stays in and says so.
        row.appendChild(tag('is-booked', 'if activated',
                            'Active only when activated ' + hours.activatedBy(item)
                            + (item.off ? '; inactive ' + hours.offLabel(item.off) + ' every year' : '')
                            + ' — check before flying.'));
        booked++;
      } else if (when && item.w) {
        var open = hours.activeAt(item.w, when, holidays);
        row.appendChild(tag(open ? 'is-open' : 'is-shut', open ? 'operating' : 'outside hours'));
        if (!open) { row.classList.add('is-shut'); shut++; }
      }
      list.appendChild(row);
    });
    box.appendChild(list);
    if (booked) {
      var booking = document.createElement('p');
      booking.className = 'plan-clear';
      booking.textContent = (booked === 1 ? 'One of these is' : booked + ' of these are')
        + ' there only when activated — the day\u2019s AUP (or NOTAM, where the tag says so) '
        + 'says whether ' + (booked === 1 ? 'it is.' : 'they are.');
      box.appendChild(booking);
    }
    if (off) {
      var season = document.createElement('p');
      season.className = 'plan-clear';
      season.textContent = (off === 1 ? 'One of these is' : off + ' of these are')
        + ' in ' + (off === 1 ? 'its' : 'their') + ' published inactive season on '
        + window.aspHours.label(when).replace(/,? \d\d:\d\d$/, '') + '.';
      box.appendChild(season);
    }
    // Said only where there are hours to speak of: "every field is open" beside a list
    // with none in it read as a verdict on the TSA above it.
    if (when && crossed.some(function (item) { return item.w; })) {
      var note = document.createElement('p');
      note.className = 'plan-clear';
      note.textContent = shut
        ? shut + ' of these are outside their published hours at '
          + window.aspHours.label(when)
          + ' — which means nobody is there unless somebody asked, not that nobody is.'
        : 'Every field on this route with published hours is open at '
          + window.aspHours.label(when) + '.';
      box.appendChild(note);
    }
  }

  // ---- scoring -----------------------------------------------------------------------
  function score() {
    var closed = document.getElementById('plan-close').checked;
    var walk = course(), legs = [];
    for (var i = 1; i < walk.length; i++) legs.push(distance(walk[i - 1], walk[i]));
    var out = { legs: legs, total: legs.reduce(function (a, b) { return a + b; }, 0),
                shape: 'open', closing: null };
    if (!points.length) return out;

    // A triangle as XContest scores one: any three points of the route, in its order,
    // are the corners, the perimeter is the closed figure — not the path walked — and the
    // closing gap is from where the route starts to where it ends. A start on a leg, as a
    // flight launched mid-course flies it (1 on the leg 4–2, corners 2, 3, 4), was scored
    // as open distance, because only the first three points were ever tried as corners
    // and only with the box ticked. Every set of three is tried now, and the best score
    // is kept: the triangle where it beats the open distance.
    var walkGap = walk.length > 2 ? distance(walk[0], walk[walk.length - 1]) : null;
    var open = out.total / 1000 * (rules().multiplier.open || 1), best = null;
    if (walk.length >= 3) {
      for (var a = 0; a < walk.length - 2; a++) {
        for (var b = a + 1; b < walk.length - 1; b++) {
          for (var c = b + 1; c < walk.length; c++) {
            var sides = [distance(walk[a], walk[b]), distance(walk[b], walk[c]), distance(walk[c], walk[a])];
            var perimeter = sides[0] + sides[1] + sides[2];
            if (perimeter <= 0 || walkGap / perimeter >= rules().closing) continue;
            var shape = Math.min.apply(null, sides) / perimeter >= FAI_MIN_SIDE ? 'fai' : 'flat';
            var points_ = perimeter / 1000 * (rules().multiplier[shape] || 1);
            if (!best || points_ > best.score) {
              best = { sides: sides, perimeter: perimeter, shape: shape, score: points_,
                       corners: [walk[a], walk[b], walk[c]] };
            }
          }
        }
      }
    }
    if (closed || best) out.closing = walkGap;
    if (best && best.score > open) {
      out.total = best.perimeter;
      out.sides = best.sides;
      out.shape = best.shape;
      out.corners = best.corners;
    }
    out.score = out.total / 1000 * (rules().multiplier[out.shape] || 1);
    return out;
  }

  // ---- drawing -----------------------------------------------------------------------
  //
  // On the map (`map3d`): the course as a line on the ground and the turnpoints numbered
  // (`setRoute`), the FAI areas under them (`setShapes`).
  function redraw() {
    var undo = document.getElementById('plan-undo'), redo = document.getElementById('plan-redo');
    var wipe = document.getElementById('plan-clear');
    if (undo) undo.disabled = !past.length;
    if (redo) redo.disabled = !future.length;
    if (wipe) wipe.disabled = !points.length;
    if (takeoff) lightSun();
    var walk = course();
    var merged = mergedEntry();
    if (merged) {
      merged.setRoute(walk, points);
      if (merged.setShapes) merged.setShapes(faiShapes());
    }
    refreshAirspace();
    report();
    reportAirspace();
  }

  // ---- the FAI area ------------------------------------------------------------------
  //
  // Where the third turnpoint can go, given the first two, for the triangle to be FAI:
  // every side at least FAI_MIN_SIDE of the perimeter. On each side of the first leg it is
  // a band between two curves — too close to the leg and the other two sides are short,
  // too far and the leg itself is. Traced along rays from the leg's midpoint, the band
  // being an interval along each ray, and every edge found by bisection so the outline is
  // smooth. In a flat plane around the leg: a guide for where to click, at well under a
  // percent from the sphere the score is measured on.
  // `towards`: only the side of the leg this point is on. `colour`: the fill.
  function faiArea(a, b, colour, towards) {
    var lat0 = (a[1] + b[1]) / 2, lon0 = (a[0] + b[0]) / 2;
    var kx = 111320 * Math.cos(lat0 * Math.PI / 180), ky = 111320;
    var ax = (a[0] - lon0) * kx, ay = (a[1] - lat0) * ky, bx = (b[0] - lon0) * kx, by = (b[1] - lat0) * ky;
    var c = Math.hypot(bx - ax, by - ay);
    if (c < 200) return [];
    var ux = (bx - ax) / c, uy = (by - ay) / c;
    // How far inside the FAI rule a point is: positive inside, zero on the edge.
    function margin(x, y) {
      var sa = Math.hypot(x - bx, y - by), sb = Math.hypot(x - ax, y - ay);
      return Math.min(sa, sb, c) - FAI_MIN_SIDE * (sa + sb + c);
    }
    function lonlat(x, y) { return [lon0 + x / kx, lat0 + y / ky]; }
    var top = 4 * c;
    // Along the ray at angle `t`: where the margin peaks. Sampled, then narrowed down, so a
    // band thinner than any sample step — the lobe's ends — is still found. Fixed steps
    // alone missed it, and the lobe stopped short of its corner by the first turnpoint.
    function ray(side, t) {
      var vx = -uy * side, vy = ux * side;
      var dx = Math.cos(t) * vx + Math.sin(t) * ux, dy = Math.cos(t) * vy + Math.sin(t) * uy;
      var steps = 400, best = 1, bestM = -Infinity;
      for (var i = 1; i < steps; i++) {
        var m = margin(dx * top * i / steps, dy * top * i / steps);
        if (m > bestM) { bestM = m; best = i; }
      }
      var lo = top * (best - 1) / steps, hi = top * (best + 1) / steps;
      for (var k = 0; k < 40; k++) {
        var m1 = lo + (hi - lo) / 3, m2 = hi - (hi - lo) / 3;
        if (margin(dx * m1, dy * m1) < margin(dx * m2, dy * m2)) lo = m1; else hi = m2;
      }
      var r = (lo + hi) / 2;
      return { dx: dx, dy: dy, r: r, m: margin(dx * r, dy * r) };
    }
    // Where the margin crosses zero between `inside` and `outside`, along the ray.
    function edge(q, inside, outside) {
      for (var k = 0; k < 24; k++) {
        var mid = (inside + outside) / 2;
        if (margin(q.dx * mid, q.dy * mid) >= 0) inside = mid; else outside = mid;
      }
      return (inside + outside) / 2;
    }
    // The lobe's end between an angle with a band and one without: the angle where the
    // band closes, and the point it closes at.
    function tip(side, tIn, tOut) {
      for (var k = 0; k < 24; k++) {
        var mid = (tIn + tOut) / 2;
        if (ray(side, mid).m >= 0) tIn = mid; else tOut = mid;
      }
      var q = ray(side, tIn);
      return lonlat(q.dx * q.r, q.dy * q.r);
    }
    var shapes = [], sides = [1, -1];
    if (towards) {
      var tx = (towards[0] - lon0) * kx, ty = (towards[1] - lat0) * ky;
      sides = [(-uy * tx + ux * ty) >= 0 ? 1 : -1];
    }
    sides.forEach(function (side) {
      var outer = [], inner = [], start = null, end = null, prevT = null, prevIn = false;
      for (var deg = -89; deg <= 89; deg += 1) {
        var t = deg * Math.PI / 180, q = ray(side, t), inside = q.m >= 0;
        if (inside && prevT !== null && !prevIn && !start) start = tip(side, t, prevT);
        if (!inside && prevIn && !end) end = tip(side, prevT, t);
        prevT = t; prevIn = inside;
        if (!inside || end) continue;
        var near = edge(q, q.r, 0), far = edge(q, q.r, top);
        inner.push(lonlat(q.dx * near, q.dy * near));
        outer.push(lonlat(q.dx * far, q.dy * far));
      }
      if (outer.length < 3) return;
      var ring = (start ? [start] : []).concat(outer, end ? [end] : [], inner.reverse());
      ring.push(ring[0]);
      shapes.push({ type: 'Feature', properties: { colour: colour, opacity: 0.45 },
                    geometry: { type: 'Polygon', coordinates: [ring] } });
    });
    return shapes;
  }
  // xcplanner's convention (dkm/xcplanner, `faiSector`), which pilots know: turnpoint 1
  // green, 2 blue, 3 red, and each colour is the area where *that* turnpoint can be with
  // the other two where they are — drawn on the side of the opposite leg the turnpoint
  // is on. With two turnpoints placed, the third's area on both sides of the leg. With a
  // closed course, the yellow circle: where the flight must finish, a fifth of the
  // triangle's perimeter around the first turnpoint.
  var CORNER_COLOURS = ['#22c55e', '#3b82f6', '#ef4444'];
  function closingCircle(centre, radius) {
    var kx = 111320 * Math.cos(centre[1] * Math.PI / 180), ring = [];
    for (var i = 0; i <= 64; i++) {
      var t = 2 * Math.PI * i / 64;
      ring.push([centre[0] + radius * Math.sin(t) / kx, centre[1] + radius * Math.cos(t) / 111320]);
    }
    return { type: 'Feature', properties: { colour: '#eab308', opacity: 0.3 },
             geometry: { type: 'Polygon', coordinates: [ring] } };
  }
  function faiShapes() {
    var box = document.getElementById('plan-fai');
    if (!box || !box.checked || points.length < 2) return [];
    if (points.length === 2) return faiArea(points[0], points[1], CORNER_COLOURS[2]);
    // Around the corners the score chose, once it has chosen a triangle; the first three
    // points while the route is still being drawn.
    var scored = score();
    var corners = scored.corners || points.slice(0, 3), shapes = [];
    corners.forEach(function (corner, i) {
      shapes = shapes.concat(faiArea(corners[(i + 1) % 3], corners[(i + 2) % 3],
                                     CORNER_COLOURS[i], corner));
    });
    // Where the route must end to close: round its start, which is where a closed course
    // is measured from.
    if (scored.corners || document.getElementById('plan-close').checked) {
      var perimeter = distance(corners[0], corners[1]) + distance(corners[1], corners[2])
        + distance(corners[2], corners[0]);
      shapes.push(closingCircle(points[0], rules().closing * perimeter));
    }
    return shapes;
  }

  // ---- the merged map ------------------------------------------------------------------
  //
  // The page opens on the merged renderer (`map3d.py`), which draws over this same
  // panel and takes its clicks. It gets the route from `redraw` and hands its clicks back
  // here, so a turnpoint dropped on either map is one turnpoint, in one list.
  function mergedEntry() {
    return window.__mergedAll && window.__mergedAll[box.id];
  }
  function hookMerged(entry) {
    if (!entry || entry.__planner) return;
    entry.__planner = true;
    entry.onClick(function (at) {
      if (holder.dataset.drawing !== 'on') return;
      addPoint(at);
    });
    // A turnpoint dragged on the map moves; the task, its distance and the FAI areas follow.
    // Redrawn once a frame at most: the airspace along the task is checked on each redraw.
    var moved = null, dragged = false;
    if (entry.onDragPoint) entry.onDragPoint(function (index, at, done) {
      if (!points[index]) return;
      if (!dragged) { remember(); dragged = true; }
      if (done) dragged = false;
      points[index] = [Math.round(at[0] * 100000) / 100000, Math.round(at[1] * 100000) / 100000];
      if (done) { if (moved) cancelAnimationFrame(moved); moved = null; redraw(); return; }
      if (!moved) moved = requestAnimationFrame(function () { moved = null; redraw(); });
    });
    entry.setRoute(course(), points);
    if (entry.setShapes) entry.setShapes(faiShapes());
    showNear();
    lightSun();
  }

  // The takeoff time, a day and a time slid through it: the sun over the task (or the
  // map's middle, before there is one) at that moment, handed to the map as the table a
  // flight's map is lit from (`TV.sun`), and the forecast wind at about 1500 m (850 hPa,
  // Open-Meteo) for the rose. The reader's own clock; it opens on tomorrow at 12:00. The
  // aerodrome hours follow it.
  var day = document.getElementById('plan-day');
  var time = document.getElementById('plan-time');
  var timeOut = document.getElementById('plan-time-out');
  var takeoff = day && time;
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function clock(minutes) { return pad2(Math.floor(minutes / 60)) + ':' + pad2(minutes % 60); }
  if (takeoff && !day.value) {
    var tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    day.value = tomorrow.getFullYear() + '-' + pad2(tomorrow.getMonth() + 1) + '-' + pad2(tomorrow.getDate());
  }
  function takeoffValue() {
    return takeoff && day.value ? day.value + 'T' + clock(Number(time.value)) : null;
  }
  function takeoffAt() {
    var value = takeoffValue(), when = value ? new Date(value) : null;
    return when && !isNaN(when.getTime()) ? when : null;
  }
  function sunPlace() {
    if (points.length) {
      return [points.reduce(function (s, p) { return s + p[0]; }, 0) / points.length,
              points.reduce(function (s, p) { return s + p[1]; }, 0) / points.length];
    }
    var dem = handle.scene().terrain || {};
    var lon = (dem.west + dem.east) / 2, lat = (dem.south + dem.north) / 2;
    return isNaN(lon) || isNaN(lat) ? [15.5, 49.8] : [lon, lat];
  }
  function sunTable() {
    var when = takeoffAt();
    if (!when || !window.TV || !TV.sun) return null;
    var at = sunPlace();
    var date = { year: when.getUTCFullYear(), month: when.getUTCMonth() + 1, day: when.getUTCDate() };
    return { track: TV.sun.dayTrack(date, at[1], at[0]), offset: -when.getTimezoneOffset(),
             at: when.getUTCHours() * 60 + when.getUTCMinutes() };
  }
  // The wind: one day of hourly answers per place (to 0.25°) and day, fetched once, read
  // at the hour nearest the slider. A day the forecast does not reach has no wind.
  var winds = {};
  var CARDINALS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  function windDay(lon, lat, date) {
    var key = lon.toFixed(2) + ',' + lat.toFixed(2) + ',' + date;
    if (!winds[key] && typeof fetch === 'function') {
      winds[key] = fetch('https://api.open-meteo.com/v1/forecast?latitude=' + lat.toFixed(2) +
          '&longitude=' + lon.toFixed(2) + '&hourly=wind_speed_850hPa,wind_direction_850hPa' +
          '&wind_speed_unit=ms&timezone=GMT&start_date=' + date + '&end_date=' + date)
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) { return data.hourly || null; });
      winds[key].catch(function () { delete winds[key]; });
    }
    return winds[key] || Promise.resolve(null);
  }
  var windAsked = 0;
  function lightWind() {
    var merged = mergedEntry(), when = takeoffAt();
    if (!merged || !merged.setWind) return;
    if (!when) { merged.setWind(null); return; }
    var at = sunPlace(), ask = ++windAsked;
    var lon = Math.round(at[0] * 4) / 4, lat = Math.round(at[1] * 4) / 4;
    var date = when.getUTCFullYear() + '-' + pad2(when.getUTCMonth() + 1) + '-' + pad2(when.getUTCDate());
    windDay(lon, lat, date).then(function (hourly) {
      if (ask !== windAsked) return;
      var hour = Math.min(23, Math.round(when.getUTCHours() + when.getUTCMinutes() / 60));
      var ms = hourly && hourly.wind_speed_850hPa ? hourly.wind_speed_850hPa[hour] : null;
      var from = hourly && hourly.wind_direction_850hPa ? hourly.wind_direction_850hPa[hour] : null;
      merged.setWind(ms === null || ms === undefined || from === null || from === undefined ? null
        : { ms: ms, from: from, cardinal: CARDINALS[Math.round(from / 22.5) % 16], at: 'at 1500 m' });
    }, function () { if (ask === windAsked) merged.setWind(null); });
  }
  function lightSun() {
    var merged = mergedEntry();
    if (merged && merged.setSun) merged.setSun(sunTable());
    lightWind();
  }
  function followTakeoff() {
    if (timeOut && time) timeOut.textContent = clock(Number(time.value));
    lightSun();
    var hoursAt = document.getElementById('asp-when'), value = takeoffValue();
    if (hoursAt && value && hoursAt.value !== value) {
      hoursAt.value = value;
      hoursAt.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }
  if (takeoff) {
    day.addEventListener('input', followTakeoff);
    time.addEventListener('input', followTakeoff);
  }
  panel.addEventListener('merged-ready', function (event) { hookMerged(event.detail); });
  hookMerged(mergedEntry());

  function addPoint(at) {
    remember();
    points.push([Math.round(at[0] * 100000) / 100000, Math.round(at[1] * 100000) / 100000]);
    redraw();
  }

  var legsNode = null;    // the legs' line, moved into the figures' second row
  function report() {
    xctRefresh();
    var answer = score();
    var figures = document.getElementById('plan-figures');
    var legs = legsNode || (legsNode = document.getElementById('plan-legs'));
    // Two rows: the distance with its shape, then the rest on one quiet line — score,
    // multiplier, the legs — with no labels. Spans, so a figure is still the one `div`
    // holding a label and a value; the legs are moved into the second row.
    figures.innerHTML = '';
    var head = document.createElement('span'), rest = document.createElement('span');
    head.className = 'plan-row plan-row-head'; rest.className = 'plan-row plan-row-sub';
    figures.appendChild(head); figures.appendChild(rest);
    legs.innerHTML = '';
    if (points.length < 2) {
      head.innerHTML = '<div><span class="k">task</span><span class="v">— km</span></div>';
      rest.innerHTML = '<span class="plan-row-hint">Press <b>Draw</b>, then click the map</span>';
      rest.appendChild(legs);
      return;
    }
    var names = { open: 'open distance', flat: 'flat triangle', fai: 'FAI triangle' };
    var cells = [
      ['distance', (answer.total / 1000).toFixed(2) + ' km'],
      ['score', answer.score.toFixed(2) + ' pts'],
      ['multiplier', '\u00d7' + (rules().multiplier[answer.shape] || 1).toFixed(1)],
      ['turnpoints', String(points.length)]
    ];
    cells.forEach(function (pair) {
      var cell = document.createElement('div');
      cell.className = 'plan-fig-' + pair[0];
      cell.innerHTML = '<span class="k"></span><span class="v"></span>';
      cell.querySelector('.k').textContent = pair[0];
      cell.querySelector('.v').textContent = pair[1];
      (pair[0] === 'distance' ? head : rest).appendChild(cell);
    });
    // Last in the figures, shown beside the distance (CSS).
    var shape = document.createElement('div');
    shape.className = 'plan-shape-cell';
    shape.innerHTML = '<span class="k">shape</span>'
      + '<span class="v"><span class="plan-shape"></span></span>';
    var chip = shape.querySelector('.plan-shape');
    chip.textContent = names[answer.shape];
    chip.className = 'plan-shape is-' + answer.shape;
    head.appendChild(shape);
    rest.appendChild(legs);

    (answer.sides || answer.legs).forEach(function (metres, i) {
      var span = document.createElement('span');
      span.textContent = (answer.sides ? 'side ' : 'leg ') + (i + 1) + ': '
        + (metres / 1000).toFixed(1) + ' km';
      legs.appendChild(span);
    });
    if (answer.closing !== null && answer.closing !== undefined) {
      var span = document.createElement('span');
      span.textContent = 'closing gap: ' + (answer.closing / 1000).toFixed(1) + ' km';
      legs.appendChild(span);
    }
  }

  // ---- to XCTrack -----------------------------------------------------------------------
  //
  // The route as XCTrack's waypoints task (xctrack.org/Competition_Interfaces.html, "XC /
  // Waypoints task"): the turnpoints in order with no cylinders — what an XC route is,
  // where a competition task would want start, goal and radii nobody drew. Three ways in,
  // because a phone and a desktop want different ones:
  //  - a .xctsk file, which on the phone XCTrack runs on opens straight into it;
  //  - a task code: the task stored with XContest (tools.xcontest.org, the service XCTrack
  //    itself shares tasks through) for a month, four letters to type into XCTrack;
  //  - a QR code to scan from a desktop's screen, drawn by the same service.
  // The last two send the route to XContest, and only when their button is pressed.
  // Each point carries the ground's height under it, which the format requires.
  var XCT_API = 'https://tools.xcontest.org/api/xctsk/';
  function polyline(values) {
    return values.map(function (value) {
      var v = Math.round(value);
      v = v < 0 ? ~(v << 1) : v << 1;
      var out = '';
      while (v >= 0x20) { out += String.fromCharCode((0x20 | (v & 0x1f)) + 63); v >>= 5; }
      return out + String.fromCharCode(v + 63);
    }).join('');
  }
  function xctrackTask() {
    var walk = course();
    return {
      T: 'W', V: 2,
      t: walk.map(function (p, i) {
        var ground = handle.groundAt ? handle.groundAt(p[0], p[1]) : null;
        var alt = ground === null || ground === undefined || isNaN(ground) ? 0 : ground;
        // Named as the map numbers them; a closed course returns to turnpoint 1.
        var n = i < points.length ? i + 1 : 1;
        return { n: 'TP' + n, z: polyline([p[0] * 1e5, p[1] * 1e5, alt]) };
      })
    };
  }
  var xctOut = document.getElementById('plan-xct-out');
  var dlg = document.getElementById('plan-xct-dlg'), dlgBody = document.getElementById('plan-xct-body');
  function xctSay(text) { if (xctOut) xctOut.textContent = text; }
  // The dialog: the QR code or the code, big enough to scan or to type, over the page
  // rather than growing the panel under the route.
  function xctDialog(html, title) {
    var walk = course();
    document.getElementById('plan-xct-title').textContent = title || 'Send the task to XCTrack';
    var sub = document.getElementById('plan-xct-sub');
    sub.hidden = !!title;
    sub.textContent = title ? '' : walk.map(function (p, i) {
      return 'TP' + (i < points.length ? i + 1 : 1);
    }).join(' \u2192 ') + ' \u00b7 ' + (score().total / 1000).toFixed(0) + ' km';
    dlgBody.innerHTML = html;
    if (dlg.showModal && !dlg.open) dlg.showModal(); else dlg.setAttribute('open', '');
    return dlgBody;
  }
  if (dlg) {
    document.getElementById('plan-xct-close').addEventListener('click', function () { dlg.close(); });
    dlg.addEventListener('click', function (event) { if (event.target === dlg) dlg.close(); });
  }
  function xctFile() {
    var blob = new Blob([JSON.stringify(xctrackTask())], { type: 'application/xctsk' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    var d = new Date();
    link.download = 'task-' + d.getFullYear() + ('0' + (d.getMonth() + 1)).slice(-2)
      + ('0' + d.getDate()).slice(-2) + '.xctsk';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 10000);
    xctSay('Saved \u2014 open it from the download and choose XCTrack.');
  }
  function xctPost(path) {
    return fetch(XCT_API + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(xctrackTask())
    }).then(function (response) {
      if (!response.ok) throw new Error('XContest answered ' + response.status);
      return response;
    });
  }
  function xctCode() {
    var body = xctDialog('<p>Asking XContest for a code\u2026</p>');
    xctPost('save').then(function (r) { return r.json(); }).then(function (answer) {
      var code = String(answer.taskCode || '').toUpperCase();
      if (!code) throw new Error('no code in the answer');
      body.innerHTML = '<b class="plan-xct-code"></b><p>In XCTrack, import a task by its XContest '
        + 'code and type these letters. The code lasts a month.</p>';
      body.querySelector('.plan-xct-code').textContent = code;
    }).catch(function (error) {
      body.innerHTML = '<p></p>';
      body.querySelector('p').textContent = 'No code: ' + error.message + '. The file works without a network.';
    });
  }
  function xctQr() {
    var body = xctDialog('<p>Drawing the QR code\u2026</p>');
    xctPost('qr2z').then(function (r) { return r.blob(); }).then(function (svg) {
      // As an image, not markup: what another site sends is drawn, never run.
      body.innerHTML = '<img class="plan-xct-qr" alt="QR code of the task for XCTrack">'
        + '<p>Scan it with XCTrack\u2019s task import (QR code). Drawn by XContest\u2019s task service.</p>';
      body.querySelector('img').src = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
    }).catch(function (error) {
      body.innerHTML = '<p></p>';
      body.querySelector('p').textContent = 'No QR code: ' + error.message + '. The file works without a network.';
    });
  }
  // One split button: the device's best way as the button, the other two behind the
  // arrow. On a phone XCTrack runs there, so the file opens straight into it; on a
  // desktop the phone is in the other hand, so the QR code is the way across.
  var touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
  function glyph(paths) {
    return '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75"'
      + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>';
  }
  var GLYPHS = {
    file: glyph('<path d="M10 3v10M6 9l4 4 4-4M4 16.5h12"/>'),
    qr: glyph('<rect x="3" y="3" width="5" height="5" rx="1"/><rect x="12" y="3" width="5" height="5" rx="1"/>'
      + '<rect x="3" y="12" width="5" height="5" rx="1"/><path d="M12 12h2v2M17 12v1M12 17h1M15 15h2v2"/>'),
    code: glyph('<path d="M4 7h12M4 13h12M8 3.5 6.5 16.5M13.5 3.5 12 16.5"/>'),
    save: glyph('<path d="M5.5 3h9v14l-4.5-3.5L5.5 17z"/>'),
    drop: glyph('<path d="M5 5l10 10M15 5 5 15"/>')
  };
  var xctMethods = {
    file: { label: touch ? 'Open in XCTrack' : 'Download .xctsk file', run: xctFile },
    qr: { label: touch ? 'QR code to scan' : 'QR code for XCTrack', run: xctQr },
    code: { label: 'Task code (XContest)', run: xctCode }
  };
  var xctOrder = touch ? ['file', 'qr', 'code'] : ['qr', 'file', 'code'];
  var xctMain = document.getElementById('plan-xct-main');
  var xctMore = document.getElementById('plan-xct-more');
  var xctMenu = document.getElementById('plan-xct-menu');
  function menuOpen(on) {
    xctMenu.hidden = !on;
    xctMore.setAttribute('aria-expanded', on ? 'true' : 'false');
    if (on) xctMenu.querySelector('button').focus();
  }
  if (xctMain) {
    xctMain.innerHTML = GLYPHS[xctOrder[0]] + '<span></span>';
    xctMain.querySelector('span').textContent = xctMethods[xctOrder[0]].label;
    xctMain.dataset.method = xctOrder[0];
    xctMain.addEventListener('click', function () { if (points.length >= 2) xctMethods[xctOrder[0]].run(); });
    xctOrder.slice(1).forEach(function (key) {
      var item = document.createElement('button');
      item.type = 'button';
      item.setAttribute('role', 'menuitem');
      item.dataset.method = key;
      item.innerHTML = GLYPHS[key] + '<span></span>';
      item.querySelector('span').textContent = xctMethods[key].label;
      item.addEventListener('click', function () {
        menuOpen(false);
        if (points.length >= 2) xctMethods[key].run();
      });
      xctMenu.appendChild(item);
    });
    // Kept in this browser, beside the ways to XCTrack (`saveTask`).
    var keep = document.createElement('button');
    keep.type = 'button';
    keep.setAttribute('role', 'menuitem');
    keep.dataset.method = 'save';
    keep.className = 'plan-menu-keep';
    keep.innerHTML = GLYPHS.save + '<span>Save in this browser</span>';
    keep.addEventListener('click', function () {
      menuOpen(false);
      if (points.length >= 2) saveTask();
    });
    xctMenu.appendChild(keep);
    xctMore.addEventListener('click', function (event) {
      event.stopPropagation();
      menuOpen(xctMenu.hidden);
    });
    document.addEventListener('click', function (event) {
      if (!xctMenu.hidden && !xctMenu.contains(event.target)) menuOpen(false);
    });
    xctMenu.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') { menuOpen(false); xctMore.focus(); }
    });
  }
  // Shown once there is a route to send, and its note cleared when the route changes.
  var xctBox = document.getElementById('plan-xct-export');
  var xctFor = '';
  function xctRefresh() {
    if (!xctBox) return;
    xctBox.hidden = points.length < 2;
    var key = JSON.stringify(course());
    if (key !== xctFor) { xctFor = key; xctSay(''); }
  }

  // ---- kept in this browser ------------------------------------------------------------
  //
  // A task saved under a name in localStorage, to come back to without XCTrack: its
  // turnpoints, whether it is closed, and the rules it was scored by. Newest first, the
  // same name saved again replaces the old one. Listed in the Import menu, each with its
  // own ×. Nothing leaves the browser.
  var SAVED_KEY = 'parainsights.planner.tasks';
  function savedTasks() {
    try {
      var list = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]');
      return Array.isArray(list) ? list.filter(function (t) { return t && t.name && Array.isArray(t.points); }) : [];
    } catch (error) { return []; }
  }
  function storeTasks(list) {
    try { localStorage.setItem(SAVED_KEY, JSON.stringify(list.slice(0, 50))); return true; }
    catch (error) { return false; }
  }
  function defaultName() {
    var answer = score(), names = { open: 'open distance', flat: 'flat triangle', fai: 'FAI triangle' };
    return (answer.total / 1000).toFixed(0) + ' km ' + (names[answer.shape] || 'task');
  }
  function saveTask(name) {
    if (name === undefined) {
      var body = xctDialog('<label for="plan-keep-name">Name</label>'
        + '<div class="plan-imp-row"><input id="plan-keep-name" class="plan-keep-name" autocomplete="off" maxlength="60">'
        + '<button type="button" class="btn primary" id="plan-keep-go">Save</button></div>'
        + '<p class="plan-imp-say">Kept in this browser only. Load it again from Import.</p>', 'Save the task');
      var input = body.querySelector('input');
      input.value = defaultName();
      input.focus(); input.select();
      function go() { if (saveTask(input.value) !== false) dlg.close(); }
      body.querySelector('#plan-keep-go').addEventListener('click', go);
      input.addEventListener('keydown', function (event) { if (event.key === 'Enter') go(); });
      return;
    }
    name = String(name || '').trim() || defaultName();
    var entry = { name: name, saved: new Date().toISOString(),
                  points: points.map(function (p) { return p.slice(); }),
                  closed: document.getElementById('plan-close').checked,
                  rules: document.getElementById('plan-rules').value };
    var list = savedTasks().filter(function (t) { return t.name !== name; });
    list.unshift(entry);
    if (!storeTasks(list)) { xctSay('Could not save: this browser keeps nothing for this page.'); return false; }
    xctSay('Saved \u201c' + name + '\u201d in this browser.');
    return true;
  }
  function loadSaved(name) {
    var task = savedTasks().filter(function (t) { return t.name === name; })[0];
    if (!task || task.points.length < 2) return false;
    remember();
    points = task.points.map(function (p) { return [Number(p[0]), Number(p[1])]; });
    document.getElementById('plan-close').checked = !!task.closed;
    if (task.rules) document.getElementById('plan-rules').value = task.rules;
    drawing(false);
    redraw();
    var merged = mergedEntry();
    if (merged && merged.frame) {
      var w = Infinity, e = -Infinity, so = Infinity, n = -Infinity;
      points.forEach(function (p) { w = Math.min(w, p[0]); e = Math.max(e, p[0]); so = Math.min(so, p[1]); n = Math.max(n, p[1]); });
      merged.frame([[w, so], [e, n]]);
    }
    xctSay('Loaded \u201c' + task.name + '\u201d.');
    return true;
  }
  function dropSaved(name) {
    storeTasks(savedTasks().filter(function (t) { return t.name !== name; }));
  }
  // The Import menu's list of them, drawn each time the menu opens.
  function drawSaved(box) {
    var list = savedTasks();
    box.innerHTML = '';
    box.hidden = !list.length;
    if (!list.length) return;
    var head = document.createElement('p');
    head.className = 'plan-saved-head';
    head.textContent = 'Saved in this browser';
    box.appendChild(head);
    list.forEach(function (task) {
      var row = document.createElement('div');
      row.className = 'plan-saved-row';
      row.innerHTML = '<button type="button" role="menuitem" class="plan-saved-load">' + GLYPHS.save
        + '<span class="plan-saved-name"></span><small></small></button>'
        + '<button type="button" class="plan-saved-drop">' + GLYPHS.drop + '</button>';
      row.querySelector('.plan-saved-name').textContent = task.name;
      var when = new Date(task.saved);
      row.querySelector('small').textContent = isNaN(when) ? '' : when.toLocaleDateString();
      var drop = row.querySelector('.plan-saved-drop');
      drop.title = 'Delete \u201c' + task.name + '\u201d';
      drop.setAttribute('aria-label', drop.title);
      row.querySelector('.plan-saved-load').addEventListener('click', function () {
        impOpen(false);
        loadSaved(task.name);
      });
      drop.addEventListener('click', function (event) {
        event.stopPropagation();
        dropSaved(task.name);
        drawSaved(box);
        xctSay('Deleted \u201c' + task.name + '\u201d.');
      });
      box.appendChild(row);
    });
  }
  // For the tests.
  window.__plannerSaved = { list: savedTasks, save: saveTask, load: loadSaved, drop: dropSaved };

  // ---- from XCTrack ----------------------------------------------------------------------
  //
  // A task back into the planner the three ways it goes out: an .xctsk file, an XContest
  // task code, a QR code. Every form XCTrack writes is read — the competition task
  // (version 1, `turnpoints[].waypoint`), its QR form (version 2, `t[].z` polyline), the
  // waypoints task (`T` "W", which the export here writes), and a QR code compressed with
  // zlib (`XCTSKZ:`). The turnpoints replace the route drawn; one that ends where it
  // starts comes in closed. Cylinders, start gates and times are not a plan's, and are
  // left behind.
  function decodePolyline(text) {
    var values = [], i = 0;
    while (i < text.length) {
      var result = 0, shift = 0, b;
      do { b = text.charCodeAt(i++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20 && i <= text.length);
      values.push(result & 1 ? ~(result >> 1) : result >> 1);
    }
    return values;
  }
  function turnpointsOf(task) {
    var list = task && (task.t || task.turnpoints);
    if (!Array.isArray(list)) throw new Error('not an XCTrack task');
    return list.map(function (tp) {
      if (tp.z) { var v = decodePolyline(tp.z); return [v[0] / 1e5, v[1] / 1e5]; }
      var w = tp.waypoint || tp;
      if (typeof w.lat !== 'number' || typeof w.lon !== 'number') throw new Error('a turnpoint has no position');
      return [w.lon, w.lat];
    });
  }
  // The text of a file or a QR code to the task in it.
  function readTask(text) {
    text = String(text || '').trim();
    if (/^XCTSKZ:/i.test(text)) {
      if (typeof DecompressionStream !== 'function') return Promise.reject(new Error('this browser cannot unpack a compressed QR code'));
      var bin = atob(text.slice(7).trim()), bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate'));
      return new Response(stream).text().then(function (json) { return JSON.parse(json); });
    }
    if (/^XCTSK:/i.test(text)) text = text.slice(6);
    try { return Promise.resolve(JSON.parse(text)); }
    catch (error) { return Promise.reject(new Error('not an XCTrack task')); }
  }
  function importTask(task, from) {
    var list = turnpointsOf(task).filter(function (p) { return isFinite(p[0]) && isFinite(p[1]); });
    if (list.length < 2) throw new Error('the task has fewer than two turnpoints');
    var closed = list.length > 3 && distance(list[0], list[list.length - 1]) < 400;
    if (closed) list.pop();
    remember();
    points = list.map(function (p) { return [Math.round(p[0] * 1e5) / 1e5, Math.round(p[1] * 1e5) / 1e5]; });
    document.getElementById('plan-close').checked = closed;
    drawing(false);
    redraw();
    var merged = mergedEntry();
    if (merged && merged.frame) {
      var w = Infinity, e = -Infinity, so = Infinity, n = -Infinity;
      points.forEach(function (p) { w = Math.min(w, p[0]); e = Math.max(e, p[0]); so = Math.min(so, p[1]); n = Math.max(n, p[1]); });
      merged.frame([[w, so], [e, n]]);
    }
    xctSay('Imported ' + points.length + ' turnpoints from ' + from + '.');
  }
  function importFailed(error) {
    var say = dlg && dlg.open ? dlgBody.querySelector('.plan-imp-say') : null;
    var text = 'Could not import: ' + ((error && error.message) || error) + '.';
    if (say) { say.textContent = text; say.classList.add('is-error'); } else xctSay(text);
  }

  // The file: picked, read, imported.
  var impFile = document.getElementById('plan-imp-file');
  if (impFile) impFile.addEventListener('change', function () {
    var file = impFile.files && impFile.files[0];
    impFile.value = '';
    if (!file) return;
    file.text().then(readTask).then(function (task) { importTask(task, file.name); }).catch(importFailed);
  });

  // The task code: XContest's own service, the one XCTrack shares tasks through.
  function importCode() {
    var body = xctDialog('<label for="plan-imp-code">XContest task code</label>'
      + '<div class="plan-imp-row"><input id="plan-imp-code" class="plan-imp-code" autocomplete="off"'
      + ' autocapitalize="characters" spellcheck="false" maxlength="12">'
      + '<button type="button" class="btn primary" id="plan-imp-load">Load</button></div>'
      + '<p class="plan-imp-say">The letters XCTrack or XContest shows when a task is shared.</p>', 'Import a task');
    var input = body.querySelector('input'), say = body.querySelector('.plan-imp-say');
    function load() {
      var code = input.value.trim().toLowerCase();
      if (!code) return;
      say.classList.remove('is-error');
      say.textContent = 'Loading ' + code.toUpperCase() + '\u2026';
      fetch(XCT_API + 'load/' + encodeURIComponent(code)).then(function (r) {
        if (r.status === 404) throw new Error('XContest has no task ' + code.toUpperCase() + ' (codes last a month)');
        if (!r.ok) throw new Error('XContest answered ' + r.status);
        return r.text();
      }).then(readTask).then(function (task) {
        importTask(task, 'task code ' + code.toUpperCase());
        dlg.close();
      }).catch(importFailed);
    }
    body.querySelector('#plan-imp-load').addEventListener('click', load);
    input.addEventListener('keydown', function (event) { if (event.key === 'Enter') load(); });
    setTimeout(function () { input.focus(); }, 50);
  }

  // The QR code: the camera, or a photo of one. The browser's own reader where it has one
  // (Chrome on Android and on macOS), else jsQR, fetched the first time it is needed.
  var JSQR = 'https://unpkg.com/jsqr@1.4.0/dist/jsQR.js', jsqrLoading = null;
  function qrReader() {
    if ('BarcodeDetector' in window) {
      return BarcodeDetector.getSupportedFormats().then(function (formats) {
        if (formats.indexOf('qr_code') < 0) throw new Error('no qr');
        var detector = new BarcodeDetector({ formats: ['qr_code'] });
        return function (source) {
          return detector.detect(source).then(function (found) { return found.length ? found[0].rawValue : null; });
        };
      }).catch(function () { return jsqrReader(); });
    }
    return jsqrReader();
  }
  function jsqrReader() {
    if (!jsqrLoading) {
      jsqrLoading = new Promise(function (resolve, reject) {
        if (window.jsQR) { resolve(); return; }
        var script = document.createElement('script');
        script.src = JSQR;
        script.onload = function () { resolve(); };
        script.onerror = function () { jsqrLoading = null; reject(new Error('the QR reader could not be loaded')); };
        document.head.appendChild(script);
      });
    }
    var canvas = document.createElement('canvas'), ctx = canvas.getContext('2d', { willReadFrequently: true });
    return jsqrLoading.then(function () {
      return function (source) {
        var w = source.videoWidth || source.naturalWidth || source.width;
        var h = source.videoHeight || source.naturalHeight || source.height;
        if (!w || !h) return Promise.resolve(null);
        var scale = Math.min(1, 1000 / Math.max(w, h));
        canvas.width = Math.round(w * scale); canvas.height = Math.round(h * scale);
        ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
        var found = window.jsQR(ctx.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height);
        return Promise.resolve(found ? found.data : null);
      };
    });
  }
  var camera = null;
  function stopCamera() {
    if (camera) { camera.getTracks().forEach(function (t) { t.stop(); }); camera = null; }
  }
  if (dlg) dlg.addEventListener('close', stopCamera);
  function importQr() {
    var body = xctDialog('<video class="plan-imp-video" playsinline muted hidden></video>'
      + '<div class="plan-imp-row" style="margin-top:10px">'
      + '<label class="btn" style="margin:0">Choose a photo<input type="file" accept="image/*" hidden></label></div>'
      + '<p class="plan-imp-say">Starting the camera\u2026</p>', 'Scan a QR code');
    var video = body.querySelector('video'), say = body.querySelector('.plan-imp-say');
    var done = false;
    function found(text) {
      if (done || !text) return false;
      if (!/^XCTSKZ?:/i.test(text)) { say.textContent = 'That QR code is not an XCTrack task.'; return false; }
      done = true;
      stopCamera();
      readTask(text).then(function (task) { importTask(task, 'a QR code'); dlg.close(); })
        .catch(function (error) { done = false; importFailed(error); });
      return true;
    }
    var reading = qrReader();
    body.querySelector('input[type=file]').addEventListener('change', function (event) {
      var file = event.target.files && event.target.files[0];
      if (!file) return;
      var img = new Image();
      img.onload = function () {
        reading.then(function (read) { return read(img); }).then(function (text) {
          URL.revokeObjectURL(img.src);
          if (!found(text)) say.textContent = text ? say.textContent : 'No QR code found in that photo.';
        }).catch(importFailed);
      };
      img.src = URL.createObjectURL(file);
    });
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      say.textContent = 'No camera here — choose a photo of the QR code.';
      return;
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }).then(function (stream) {
      if (!dlg.open) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
      camera = stream;
      video.srcObject = stream;
      video.hidden = false;
      return video.play().then(function () {
        say.textContent = 'Point the camera at the task\u2019s QR code.';
        return reading;
      }).then(function (read) {
        (function scan() {
          if (done || !camera) return;
          read(video).then(function (text) { if (!found(text)) setTimeout(scan, 250); },
                           function () { setTimeout(scan, 500); });
        })();
      });
    }).catch(function () {
      say.textContent = 'The camera is not available — choose a photo of the QR code instead.';
    });
  }

  // The import menu, as the export's: a button, the three ways under it.
  var impMore = document.getElementById('plan-imp-more'), impMenu = document.getElementById('plan-imp-menu');
  var savedBox = null;
  function impOpen(on) {
    if (on) {
      if (!savedBox) {
        savedBox = document.createElement('div');
        savedBox.className = 'plan-saved';
        impMenu.appendChild(savedBox);
      }
      drawSaved(savedBox);
    }
    impMenu.hidden = !on;
    impMore.setAttribute('aria-expanded', on ? 'true' : 'false');
    if (on) impMenu.querySelector('button').focus();
  }
  if (impMore) {
    impMore.addEventListener('click', function (event) { event.stopPropagation(); impOpen(impMenu.hidden); });
    document.addEventListener('click', function (event) {
      if (!impMenu.hidden && !impMenu.contains(event.target)) impOpen(false);
    });
    impMenu.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') { impOpen(false); impMore.focus(); }
    });
    impMenu.querySelectorAll('[data-import]').forEach(function (item) {
      item.addEventListener('click', function () {
        impOpen(false);
        var how = item.dataset.import;
        if (how === 'file') impFile.click();
        else if (how === 'code') importCode();
        else importQr();
      });
    });
  }

  // ---- input -------------------------------------------------------------------------
  //
  // A click on the map is a turnpoint while drawing (`hookMerged`): MapLibre's `click`
  // already refuses a pointer that moved, so a drag of the map leaves no point behind.
  var drawButton = document.getElementById('plan-draw');
  function drawing(on) {
    holder.dataset.drawing = on ? 'on' : 'off';
    if (drawButton) {
      drawButton.setAttribute('aria-pressed', on ? 'true' : 'false');
      // Pressed, it says what pressing again does. How to drop turnpoints is in the
      // Task ⓘ.
      drawButton.querySelector('span').textContent = on ? 'Done' : 'Draw';
      drawButton.title = on ? 'Stop adding turnpoints' : 'Click the map to add turnpoints';
    }
  }
  if (drawButton) drawButton.addEventListener('click', function () {
    drawing(holder.dataset.drawing !== 'on');
  });
  drawing(false);

  document.getElementById('plan-undo').addEventListener('click', function () {
    if (!past.length) return;
    future.push(points);
    points = past.pop();
    redraw();
  });
  document.getElementById('plan-redo').addEventListener('click', function () {
    if (!future.length) return;
    past.push(points);
    points = future.pop();
    redraw();
  });
  document.getElementById('plan-clear').addEventListener('click', function () {
    if (!points.length) return;
    remember();
    points = [];
    redraw();
  });
  document.getElementById('plan-close').addEventListener('change', redraw);
  document.getElementById('plan-rules').addEventListener('change', redraw);
  document.getElementById('plan-fai').addEventListener('change', redraw);

  // The time control belongs to the airspace map, which takes the shut fields off it;
  // here it only re-marks the list, which keeps every crossing either way.
  var whenBox = document.getElementById('asp-when-on');
  var whenInput = document.getElementById('asp-when');
  if (whenBox) whenBox.addEventListener('change', reportAirspace);
  if (whenInput) whenInput.addEventListener('input', reportAirspace);

  // The strip's height, for the map above it to leave room for (`--plan-strip-h`): on a
  // desktop the two fill the screen together.
  var strip = document.getElementById('plan-strip'), stage = strip && strip.closest('.asp-stage');
  if (strip && stage && window.ResizeObserver) {
    new ResizeObserver(function () {
      stage.style.setProperty('--plan-strip-h', strip.offsetHeight + 'px');
    }).observe(strip);
  }

  followTakeoff();
  redraw();
  }
})();

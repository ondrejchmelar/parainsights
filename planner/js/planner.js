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
  function fractionInside(a, b, ring) {
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
      return pointInRing(a[0] + dx / 2, a[1] + dy / 2, ring) ? 1 : 0;
    }
    ts.sort(function (x, y) { return x - y; });
    var total = 0;
    for (var k = 1; k < ts.length; k++) {
      var mid = (ts[k - 1] + ts[k]) / 2;
      if (pointInRing(a[0] + dx * mid, a[1] + dy * mid, ring)) total += ts[k] - ts[k - 1];
    }
    return total;
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
    var rings = handle.scene().airspaces || [];
    if (!rings.length || points.length < 2) return [];
    var walk = course(), legs = [];
    for (var i = 1; i < walk.length; i++) legs.push([walk[i - 1], walk[i]]);

    var found = {};
    legs.forEach(function (leg) {
      var length = distance(leg[0], leg[1]);
      var west = Math.min(leg[0][0], leg[1][0]), east = Math.max(leg[0][0], leg[1][0]);
      var south = Math.min(leg[0][1], leg[1][1]), north = Math.max(leg[0][1], leg[1][1]);
      rings.forEach(function (ring) {
        var box = ringBox(ring);
        if (box.east < west || box.west > east || box.north < south || box.south > north) {
          return;
        }
        var fraction = fractionInside(leg[0], leg[1], ring);
        if (fraction <= 0) return;
        // Keyed by name: one CTR is published as several rings and one okruh is two
        // rectangles, and a list that says "LKPR CTR" four times is a list nobody reads.
        var seen = found[ring.n];
        if (!seen) found[ring.n] = seen = { name: ring.n, k: ring.k, f: ring.f,
                                            g: ring.g, w: ring.w, metres: 0 };
        seen.metres += fraction * length;
        seen.f = Math.min(seen.f, ring.f);
      });
    });
    // Lowest floor first: what a paraglider hits soonest is what it most needs to know.
    return Object.keys(found).map(function (key) { return found[key]; })
      .sort(function (a, b) { return a.f - b.f || b.metres - a.metres; });
  }

  // The whole list is always shown, even when the map has hidden a field for being
  // shut. The map is decluttering; the list is the answer, and an answer that quietly
  // drops a zone because a VFR manual page said "SAT, SUN, HOL" is not one.
  // How much of the route runs where the map has no airspace to check it against.
  var coverage = JSON.parse(
    (document.getElementById('plan-coverage') || {}).textContent || 'null');
  function uncheckedMetres() {
    if (!coverage) return 0;
    var walk = course(), metres = 0;
    for (var i = 1; i < walk.length; i++) {
      metres += (1 - fractionInside(walk[i - 1], walk[i], coverage))
        * distance(walk[i - 1], walk[i]);
    }
    return metres;
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
    var shut = 0;
    var heading = document.createElement('p');
    heading.className = 'plan-crossed-head';
    heading.textContent = crossed.length + (crossed.length === 1
      ? ' airspace crossed, lowest floor first'
      : ' airspaces crossed, lowest floor first');
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
      if (when && item.w) {
        var open = window.aspHours.activeAt(item.w, when, holidays);
        var tag = document.createElement('span');
        tag.className = 'plan-when ' + (open ? 'is-open' : 'is-shut');
        tag.textContent = open ? 'operating' : 'outside hours';
        row.appendChild(tag);
        if (!open) { row.classList.add('is-shut'); shut++; }
      }
      list.appendChild(row);
    });
    box.appendChild(list);
    if (when) {
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

    // A triangle is three corners, and the perimeter is the closed figure — not the
    // path walked. Four points with the closing box ticked is the same three corners
    // with the flight coming home, which is how a task is actually flown.
    var corners = points.length === 3 && closed ? points.slice(0)
      : (points.length === 4 && closed ? points.slice(0, 3) : null);
    if (corners) {
      var sides = [distance(corners[0], corners[1]), distance(corners[1], corners[2]),
                   distance(corners[2], corners[0])];
      var perimeter = sides[0] + sides[1] + sides[2];
      var gap = points.length === 4 ? distance(points[3], points[0]) : 0;
      out.closing = gap;
      if (perimeter > 0 && gap / perimeter < rules().closing) {
        out.total = perimeter;
        out.sides = sides;
        out.shape = Math.min.apply(null, sides) / perimeter >= FAI_MIN_SIDE ? 'fai' : 'flat';
      }
    }
    out.score = out.total / 1000 * (rules().multiplier[out.shape] || 1);
    return out;
  }

  // ---- drawing -----------------------------------------------------------------------
  //
  // On the map (`map3d`): the course as a line on the ground and the turnpoints numbered
  // (`setRoute`), the FAI areas under them (`setShapes`).
  function redraw() {
    var walk = course();
    var merged = mergedEntry();
    if (merged) {
      merged.setRoute(walk, points);
      if (merged.setShapes) merged.setShapes(faiShapes());
    }
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
    function fai(x, y) {
      var sa = Math.hypot(x - bx, y - by), sb = Math.hypot(x - ax, y - ay);
      return Math.min(sa, sb, c) >= FAI_MIN_SIDE * (sa + sb + c);
    }
    function lonlat(x, y) { return [lon0 + x / kx, lat0 + y / ky]; }
    var shapes = [], sides = [1, -1];
    if (towards) {
      var tx = (towards[0] - lon0) * kx, ty = (towards[1] - lat0) * ky;
      sides = [(-uy * tx + ux * ty) >= 0 ? 1 : -1];
    }
    sides.forEach(function (side) {
      var vx = -uy * side, vy = ux * side, outer = [], inner = [];
      for (var deg = -85; deg <= 85; deg += 1) {
        var t = deg * Math.PI / 180;
        var dx = Math.cos(t) * vx + Math.sin(t) * ux, dy = Math.cos(t) * vy + Math.sin(t) * uy;
        var steps = 240, top = 4 * c, first = -1, last = -1;
        for (var i = 1; i <= steps; i++) {
          var r = top * i / steps;
          if (fai(dx * r, dy * r)) { if (first < 0) first = i; last = i; }
        }
        if (first < 0) continue;
        function edge(lo, hi) {      // lo inside, hi outside, or the other way round
          var inLo = fai(dx * lo, dy * lo);
          for (var k = 0; k < 16; k++) {
            var mid = (lo + hi) / 2;
            if (fai(dx * mid, dy * mid) === inLo) lo = mid; else hi = mid;
          }
          return (lo + hi) / 2;
        }
        var near = edge(top * first / steps, top * (first - 1) / steps);
        var far = edge(top * last / steps, top * (last + 1) / steps);
        inner.push(lonlat(dx * near, dy * near));
        outer.push(lonlat(dx * far, dy * far));
      }
      if (outer.length < 3) return;
      var ring = outer.concat(inner.reverse());
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
    var corners = points.slice(0, 3), shapes = [];
    corners.forEach(function (corner, i) {
      shapes = shapes.concat(faiArea(corners[(i + 1) % 3], corners[(i + 2) % 3],
                                     CORNER_COLOURS[i], corner));
    });
    if (document.getElementById('plan-close').checked) {
      var perimeter = distance(corners[0], corners[1]) + distance(corners[1], corners[2])
        + distance(corners[2], corners[0]);
      shapes.push(closingCircle(corners[0], rules().closing * perimeter));
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
    var moved = null;
    if (entry.onDragPoint) entry.onDragPoint(function (index, at, done) {
      if (!points[index]) return;
      points[index] = [Math.round(at[0] * 100000) / 100000, Math.round(at[1] * 100000) / 100000];
      if (done) { if (moved) cancelAnimationFrame(moved); moved = null; redraw(); return; }
      if (!moved) moved = requestAnimationFrame(function () { moved = null; redraw(); });
    });
    entry.setRoute(course(), points);
    if (entry.setShapes) entry.setShapes(faiShapes());
  }
  panel.addEventListener('merged-ready', function (event) { hookMerged(event.detail); });
  hookMerged(mergedEntry());

  function addPoint(at) {
    points.push([Math.round(at[0] * 100000) / 100000, Math.round(at[1] * 100000) / 100000]);
    redraw();
  }

  function report() {
    var answer = score();
    var figures = document.getElementById('plan-figures');
    figures.innerHTML = '';
    if (points.length < 2) {
      figures.innerHTML = '<div><span class="k">task</span>'
        + '<span class="v">— km</span></div>';
      document.getElementById('plan-legs').textContent = '';
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
      cell.innerHTML = '<span class="k"></span><span class="v"></span>';
      cell.querySelector('.k').textContent = pair[0];
      cell.querySelector('.v').textContent = pair[1];
      figures.appendChild(cell);
    });
    // Last in the figures, shown at the panel's top right, level with its heading (CSS).
    var shape = document.createElement('div');
    shape.className = 'plan-shape-cell';
    shape.innerHTML = '<span class="k">shape</span>'
      + '<span class="v"><span class="plan-shape"></span></span>';
    var chip = shape.querySelector('.plan-shape');
    chip.textContent = names[answer.shape];
    chip.className = 'plan-shape is-' + answer.shape;
    figures.appendChild(shape);

    var legs = document.getElementById('plan-legs');
    legs.innerHTML = '';
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

  // ---- input -------------------------------------------------------------------------
  //
  // A click on the map is a turnpoint while drawing (`hookMerged`): MapLibre's `click`
  // already refuses a pointer that moved, so a drag of the map leaves no point behind.
  var drawButton = document.getElementById('plan-draw');
  function drawing(on) {
    holder.dataset.drawing = on ? 'on' : 'off';
    if (drawButton) {
      drawButton.setAttribute('aria-pressed', on ? 'true' : 'false');
      // Pressed, it says what pressing again does; "Drawing — click the map" pushed Clear off
      // the desktop's panel. How to drop turnpoints is in the Task ⓘ.
      drawButton.textContent = on ? 'Done drawing' : 'Draw a task';
    }
  }
  if (drawButton) drawButton.addEventListener('click', function () {
    drawing(holder.dataset.drawing !== 'on');
  });
  drawing(false);

  document.getElementById('plan-undo').addEventListener('click', function () {
    points.pop();
    redraw();
  });
  document.getElementById('plan-clear').addEventListener('click', function () {
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

  redraw();
  }
})();

"""The planner: draw a task on the map you will actually fly it over.

It is no longer a page of its own. The planner and the airspace map were two tabs
drawing the same airspace over the same ground, so the planner is now a section of the
airspace article (`airspaces.render_html.body`): its bar sits over the map, its figures
and crossings under it, and `planner/cli.py` only writes a redirect for old links.

flyxc.app is the reference, and the thing worth copying from it is that the route is
drawn on a real map and scored as you drag it. What this one adds — because both halves
already live in this repository — is that the map underneath is the **airspace** map: a
line that looks 60 km long and crosses a TMA is not a plan, and on a bare basemap you
cannot see that.

Nothing here re-implements the 3D view or the airspace layer. The planner is a *layer
over* `view3d`, and it draws through the same two members a flight uses:

- `scene.track` — the course line, at ground level;
- `scene.climbs` — the numbered turnpoint markers.

That is the whole reason the planner is ~200 lines. It also means a planned task and a
flown flight are drawn by exactly the same code, and cannot disagree about where a line
on this map is.

The scoring rules are XContest's and are `tracklog_viewer/js/xc.js`'s, read from it with
their constants asserted against it by a test: every side at least 28% of the perimeter
for FAI, a closing gap under 20% of the perimeter for a closed course, and multipliers
1.0 / 1.2 / 1.4. A planner that scored a task differently from the report that later
measures the flight would be worse than no planner.
"""

from __future__ import annotations

import json

import re
from pathlib import Path
from types import SimpleNamespace


def _scoring() -> SimpleNamespace:
    """XContest's constants as the report's scorer holds them, read from `js/xc.js`: the
    planner must score a task exactly as the flight it becomes will be scored, and that
    scorer is the JavaScript. Read, not retyped, so the two cannot drift."""
    source = (Path(__file__).parent.parent / "tracklog_viewer" / "js" / "xc.js").read_text(
        encoding="utf-8")

    def number(name):
        return float(re.search(rf"var {name} = ([0-9.]+);", source).group(1))

    multipliers = re.search(r"var MULTIPLIER = \{([^}]*)\}", source).group(1)
    return SimpleNamespace(
        FAI_MIN_SIDE=number("FAI_MIN_SIDE"), MAX_CLOSING=number("MAX_CLOSING"),
        MULTIPLIER={k: float(v) for k, v in re.findall(r"(\w+): ([0-9.]+)", multipliers)})


xc = _scoring()

STYLE = """
.plan-bar { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center;
  margin:12px 0 10px; font-size:13px; }
.plan-bar .plan-hint { color:var(--ink-3); font-size:12.5px; }
.plan-figures { display:flex; flex-wrap:wrap; gap:10px 26px; margin:12px 0 0; }
.plan-figures div { display:flex; flex-direction:column; }
.plan-figures .k { font-size:10.5px; text-transform:uppercase; letter-spacing:.07em;
  color:var(--ink-3); }
.plan-figures .v { font-size:19px; font-variant-numeric:tabular-nums; }
.plan-shape { display:inline-block; padding:3px 9px; border-radius:3px; font-size:11px;
  text-transform:uppercase; letter-spacing:.06em; background:var(--panel-2); }
.plan-shape.is-fai { background:#15803d; color:#fff; }
.plan-shape.is-flat { background:#a16207; color:#fff; }
.plan-legs { margin:12px 0 0; font-size:12.5px; color:var(--ink-2);
  font-variant-numeric:tabular-nums; }
.plan-legs span { margin-right:14px; white-space:nowrap; }
.plan-airspace { margin:16px 0 0; }
.plan-crossed-head { margin:0 0 6px; font-size:12px; text-transform:uppercase;
  letter-spacing:.07em; color:var(--ink-3); }
.plan-clear { margin:0; font-size:12.5px; color:var(--ink-3); }
.plan-crossed { list-style:none; margin:0; padding:0; border:1px solid var(--rule);
  border-radius:4px; max-height:15em; overflow-y:auto; }
.plan-crossed li { display:flex; align-items:baseline; gap:9px; padding:6px 11px;
  border-bottom:1px solid var(--rule); font-size:13px; }
.plan-crossed li:last-child { border-bottom:0; }
.plan-swatch { width:10px; height:10px; border-radius:2px; flex:none;
  transform:translateY(1px); }
.plan-crossed-name { flex:1; min-width:0; }
.plan-crossed-km { color:var(--ink-3); font-size:12px; white-space:nowrap;
  font-variant-numeric:tabular-nums; }
.plan-crossed li.is-shut .plan-crossed-name { color:var(--ink-3); }
.plan-when { font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
  padding:2px 6px; border-radius:3px; white-space:nowrap; flex:none; }
.plan-when.is-open { background:#15803d; color:#fff; }
.plan-when.is-shut { background:var(--panel-2); color:var(--ink-3); }
.plan-draw[aria-pressed="true"] { background:var(--ink); color:var(--paper);
  border-color:var(--ink); }
.plan-section { margin:18px 0 0; }
.plan-section h2 { font-size:17px; margin:0 0 4px; }
[data-planner][data-drawing="on"] canvas.view3d,
[data-planner][data-drawing="on"] .maplibregl-canvas-container.maplibregl-interactive { cursor:crosshair; }
"""


def controls() -> str:
    """The bar over the map. Drawing is a mode, off until asked for: the same map is the
    airspace map, where a tap on a phone names the zone under the finger, and a tap that
    also dropped a turnpoint would make the one gesture mean two things."""
    return (
        '<div class="plan-bar">'
        '<button type="button" class="plan-draw" id="plan-draw" aria-pressed="false">'
        "Draw a task</button>"
        '<button type="button" id="plan-undo">Undo point</button>'
        '<button type="button" id="plan-clear">Clear</button>'
        '<label><input type="checkbox" id="plan-close"> closed course</label>'
        '<span class="plan-hint" id="plan-hint">Press <em>Draw a task</em>, then click the '
        "map to drop turnpoints. Drag, pinch and twist still move the view — a click that "
        "moved is a drag, not a point.</span>"
        "</div>"
    )


def results() -> str:
    """What the drawn route is worth and what it crosses, under the map."""
    return f"""<section class="plan-section" aria-label="The task">
    <div class="plan-figures" id="plan-figures"></div>
    <p class="plan-legs" id="plan-legs"></p>
    <div class="plan-airspace" id="plan-airspace"></div>
    <p class="met-links">Scored with the same rules as the flight report:
    every side at least {xc.FAI_MIN_SIDE:.0%} of the perimeter for FAI, a closing gap under
    {xc.MAX_CLOSING:.0%} of it for a closed course, multipliers
    {xc.MULTIPLIER['open']:g}&thinsp;/&thinsp;{xc.MULTIPLIER['flat']:g}&thinsp;/&thinsp;{xc.MULTIPLIER['fai']:g}.
    Airspace is drawn for Czechia only.
    <strong>This is a plan, not a clearance.</strong> Check the airspace and the NOTAMs.</p>
    <script type="application/json" id="plan-coverage">{_coverage()}</script>
  </section>"""


def body(uid: str = "planner", *, scene_panel: str = "") -> str:
    """The planner on its own over a given panel — the shape the airspace article puts
    together, kept for a caller that has no airspace overlay to build (the tests)."""
    from airspaces import render_html as airspace_html

    return f"""<article class="flight airspace-article" id="{uid}-article" data-planner>
  {airspace_html.when_control()}
  {controls()}
  <div class="asp-holder">
    {scene_panel}
    <div class="asp-name" id="asp-name"></div>
  </div>
  {results()}
</article>"""


def _coverage() -> str:
    """Where the airspace on this map is complete: the Czech border, as a ring the page
    can test a leg against. Outside it the map has no airspace, and a route there crosses
    "nothing" only in the sense that nothing was looked for."""
    from airspaces import basemap as border

    return json.dumps({"name": "Czechia",
                       "lon": [lon for _, lon in border.BORDER],
                       "lat": [lat for lat, _ in border.BORDER]},
                      separators=(",", ":"))


# The constants are interpolated from `js/xc.js` rather than typed, so the planner cannot
# drift from the scorer that later measures the flight. A hand-written 0.28 here would go
# stale the moment FAI_MIN_SIDE moved, in the one place that exists to agree with it.
SCRIPT = """
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
  var canvas = panel.querySelector('canvas.view3d');

  var FAI_MIN_SIDE = %(fai)s, MAX_CLOSING = %(closing)s;
  var MULTIPLIER = %(multiplier)s;
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
      if (perimeter > 0 && gap / perimeter < MAX_CLOSING) {
        out.total = perimeter;
        out.sides = sides;
        out.shape = Math.min.apply(null, sides) / perimeter >= FAI_MIN_SIDE ? 'fai' : 'flat';
      }
    }
    out.score = out.total / 1000 * (MULTIPLIER[out.shape] || 1);
    return out;
  }

  // ---- drawing -----------------------------------------------------------------------
  //
  // Straight into the scene the view already knows how to draw: the course line is a
  // track at ground level and the turnpoints are the numbered markers a flight uses for
  // its climbs. No second renderer, and no way for the two to disagree about where a
  // point on this map is.
  function redraw() {
    var scene = handle.scene();
    var line = { lon: [], lat: [], alt: [], c: [] };
    var walk = course();
    walk.forEach(function (point) {
      line.lon.push(point[0]);
      line.lat.push(point[1]);
      line.alt.push(handle.groundAt(point[0], point[1]) + 60);
      line.c.push(scene.palette.length - 1);
    });
    scene.track = line;
    scene.climbs = points.map(function (point, i) {
      return { label: String(i + 1), lon: point[0], lat: point[1],
               alt: handle.groundAt(point[0], point[1]) + 60, tow: false };
    });
    handle.redraw();
    var merged = mergedEntry();
    if (merged) merged.setRoute(walk, points);
    report();
    reportAirspace();
  }

  // ---- the merged map ------------------------------------------------------------------
  //
  // The page opens on the merged renderer (`map3d.py`), which draws over this same
  // panel and takes its clicks. It gets the route from `redraw` and hands its clicks back
  // here, so a turnpoint dropped on either map is one turnpoint, in one list.
  function mergedEntry() {
    return window.__mergedAll && window.__mergedAll[canvas.id];
  }
  function hookMerged(entry) {
    if (!entry || entry.__planner) return;
    entry.__planner = true;
    entry.onClick(function (at) {
      if (holder.dataset.drawing !== 'on') return;
      addPoint(at);
    });
    entry.setRoute(course(), points);
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
      ['multiplier', '\\u00d7' + (MULTIPLIER[answer.shape] || 1).toFixed(1)],
      ['turnpoints', String(points.length)]
    ];
    cells.forEach(function (pair) {
      var cell = document.createElement('div');
      cell.innerHTML = '<span class="k"></span><span class="v"></span>';
      cell.querySelector('.k').textContent = pair[0];
      cell.querySelector('.v').textContent = pair[1];
      figures.appendChild(cell);
    });
    var shape = document.createElement('div');
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
  // A click, and only a click. The same canvas pans, zooms, rotates and tilts, so a
  // pointerup that has travelled more than a few pixels since its pointerdown is a
  // gesture and must not drop a turnpoint — otherwise every drag of the map would leave
  // a point behind, which is the way this kind of tool is usually broken.
  var down = null;
  canvas.addEventListener('pointerdown', function (event) {
    down = { x: event.clientX, y: event.clientY, id: event.pointerId, count: 1 };
  });
  canvas.addEventListener('pointerup', function (event) {
    if (!down || down.id !== event.pointerId) { down = null; return; }
    if (holder.dataset.drawing !== 'on') { down = null; return; }
    // The rose turns the view north; it is not a place on the ground.
    if (handle.overRose && handle.overRose(event.clientX, event.clientY)) { down = null; return; }
    var moved = Math.hypot(event.clientX - down.x, event.clientY - down.y);
    down = null;
    if (moved > 6) return;
    var point = handle.groundLonLat(event.clientX, event.clientY);
    if (!point) return;
    addPoint(point);
  });

  var drawButton = document.getElementById('plan-draw');
  function drawing(on) {
    holder.dataset.drawing = on ? 'on' : 'off';
    if (drawButton) {
      drawButton.setAttribute('aria-pressed', on ? 'true' : 'false');
      drawButton.textContent = on ? 'Drawing — click the map' : 'Draw a task';
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

  // The time control belongs to the airspace map, which takes the shut fields off it;
  // here it only re-marks the list, which keeps every crossing either way.
  var whenBox = document.getElementById('asp-when-on');
  var whenInput = document.getElementById('asp-when');
  if (whenBox) whenBox.addEventListener('change', reportAirspace);
  if (whenInput) whenInput.addEventListener('input', reportAirspace);

  redraw();
  }
})();
""" % {
    "fai": xc.FAI_MIN_SIDE,
    "closing": xc.MAX_CLOSING,
    "multiplier": (
        "{" + ", ".join(f"{name}: {value}" for name, value in xc.MULTIPLIER.items()) + "}"
    ),
}

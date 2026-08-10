"""The planner: draw a task on the map you will actually fly it over.

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

The scoring rules are XContest's and are `tracklog_viewer/xc.py`'s, transcribed with
their constants asserted against it by a test: every side at least 28% of the perimeter
for FAI, a closing gap under 20% of the perimeter for a closed course, and multipliers
1.0 / 1.2 / 1.4. A planner that scored a task differently from the report that later
measures the flight would be worse than no planner.
"""

from __future__ import annotations

from tracklog_viewer import xc

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
"""


def controls() -> str:
    return (
        '<div class="plan-bar">'
        '<button type="button" id="plan-undo">Undo point</button>'
        '<button type="button" id="plan-clear">Clear</button>'
        '<label><input type="checkbox" id="plan-close"> closed course</label>'
        '<span class="plan-hint">Click the map to drop a turnpoint. '
        "Drag, pinch and twist still move the view — a click that moved is a drag, not a "
        "point.</span>"
        "</div>"
    )


def body(uid: str = "planner", *, scene_panel: str = "") -> str:
    """The planner view. `scene_panel` is the 3D map, already built by `airspaces`."""
    return f"""<article class="flight planner-article" id="{uid}-article">
  <h1>Plan a task</h1>
  <p class="lede">Drop turnpoints on the ground you are going to fly over, and see what
  the route is worth. Scored the way XContest scores it — a shorter FAI triangle beats a
  longer flat one — and drawn over the airspace, because a line that crosses a TMA is not
  a plan.</p>
  {controls()}
  <div class="asp-holder">
    {scene_panel}
    <div class="asp-name" id="asp-name"></div>
  </div>
  <div class="plan-figures" id="plan-figures"></div>
  <p class="plan-legs" id="plan-legs"></p>
  <p class="met-links">Scored with the same rules as the flight report:
  every side at least {xc.FAI_MIN_SIDE:.0%} of the perimeter for FAI, a closing gap under
  {xc.MAX_CLOSING:.0%} of it for a closed course, multipliers
  {xc.MULTIPLIER['open']:g}&thinsp;/&thinsp;{xc.MULTIPLIER['flat']:g}&thinsp;/&thinsp;{xc.MULTIPLIER['fai']:g}.
  <strong>This is a plan, not a clearance.</strong> Check the airspace and the NOTAMs.</p>
</article>"""


# The constants are interpolated from `xc.py` rather than typed, so the planner cannot
# drift from the scorer that later measures the flight. A hand-written 0.28 here would go
# stale the moment FAI_MIN_SIDE moved, in the one place that exists to agree with it.
SCRIPT = """
(function () {
  var holder = document.querySelector('.planner-article');
  if (!holder) return;
  var panel = holder.querySelector('.view3d-panel');
  if (!panel || typeof initView3d !== 'function') return;
  var handle = window.__view3dAll && window.__view3dAll[
    (panel.querySelector('canvas.view3d') || {}).id];
  if (!handle) handle = initView3d(panel, null);
  if (!handle) return;
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

  // ---- scoring -----------------------------------------------------------------------
  function score() {
    var legs = [];
    for (var i = 1; i < points.length; i++) legs.push(distance(points[i - 1], points[i]));
    var closed = document.getElementById('plan-close').checked;
    var out = { legs: legs, total: legs.reduce(function (a, b) { return a + b; }, 0),
                shape: 'open', closing: null };
    if (!points.length) return out;

    // A triangle is three corners, and the perimeter is the closed figure — not the
    // path walked. Four points with the closing box ticked is the same three corners
    // with the flight coming home, which is how a task is actually flown.
    var corners = points.length === 3 ? points.slice(0)
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
    var closed = document.getElementById('plan-close').checked;
    var walk = points.slice(0);
    if (closed && points.length > 2) walk.push(points[0]);
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
    report();
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
    var moved = Math.hypot(event.clientX - down.x, event.clientY - down.y);
    down = null;
    if (moved > 6) return;
    var point = handle.groundLonLat(event.clientX, event.clientY);
    if (!point) return;
    points.push([Math.round(point[0] * 100000) / 100000,
                 Math.round(point[1] * 100000) / 100000]);
    redraw();
  });

  document.getElementById('plan-undo').addEventListener('click', function () {
    points.pop();
    redraw();
  });
  document.getElementById('plan-clear').addEventListener('click', function () {
    points = [];
    redraw();
  });
  document.getElementById('plan-close').addEventListener('change', redraw);

  redraw();
})();
""" % {
    "fai": xc.FAI_MIN_SIDE,
    "closing": xc.MAX_CLOSING,
    "multiplier": (
        "{" + ", ".join(f"{name}: {value}" for name, value in xc.MULTIPLIER.items()) + "}"
    ),
}

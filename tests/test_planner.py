"""The planner, driven in a real browser.

Clicking a canvas that also pans, zooms, rotates and tilts is the whole difficulty here,
and none of it is visible from Python: whether a click lands where the reader pointed,
whether a drag leaves a turnpoint behind, and whether three points score as a triangle
are all claims about what the page does with a PointerEvent. So this renders the page
over a synthetic DEM, dispatches real events at it and reads the answers out of the DOM.

No network: the terrain is generated and there is no basemap.
"""

import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

from planner import cli as planner_cli
from planner import render_html as planner_html
from tests.test_view3d_gl import CHROME, CHROME_FLAGS, needs_chrome
from tracklog_viewer import terrain as terrain_module
from tracklog_viewer import view3d, xc


def _terrain():
    """A gentle grid over a degree of ground. Elevation is deliberately not flat: the
    course line is drawn 60 m above the terrain under each point, so a flat plane would
    let a bug that ignores the DEM pass."""
    rows, cols = 24, 24
    z = np.array([[400 + 300 * math.sin(r / 5) * math.cos(c / 7)
                   for c in range(cols)] for r in range(rows)])
    return terrain_module.Terrain(west=14.0, east=15.0, south=49.0, north=50.0,
                                  elevations=z)


def _band(name, west, east, south, north, floor="GND", ceiling="FL 95", klass="C",
          hours=None):
    """A rectangular airspace, so that what a leg through it should measure is arithmetic
    a reader can check rather than a number this code produced.

    `hours` is a *Provozní doba* line, parsed the same way a real page's is — writing the
    payload out by hand here would test the renderer against a schedule the parser might
    never produce.
    """
    from airspaces import hours as hours_module
    from airspaces import openair

    space = openair.Airspace(
        name, klass, floor=floor, ceiling=ceiling,
        points=[(south, west), (north, west), (north, east), (south, east)],
    )
    if hours:
        space.meta["hours"] = hours_module.parse(hours).payload()
    return space


def _page(spaces=()) -> str:
    from airspaces import scene as airspace_scene

    payload = airspace_scene.build(list(spaces), terrain=_terrain(),
                                   basemaps={}, tiles=False)
    panel = view3d.panel(payload, "planner")
    return planner_cli.page(planner_html.body(scene_panel=panel), "Plan a task")


PROBE = """
<pre id="probe-out"></pre>
<script>
window.addEventListener('load', function () {
  setTimeout(function () {
    var answer;
    try { answer = (function () { %s })(); }
    catch (error) { answer = { error: String((error && error.stack) || error) }; }
    document.getElementById('probe-out').textContent = JSON.stringify(answer);
  }, 900);
});
</script>
"""


def _run(body: str, spaces=()) -> dict:
    with tempfile.TemporaryDirectory() as folder:
        page = Path(folder) / "planner.html"
        page.write_text(_page(spaces) + PROBE % body, encoding="utf-8")
        out = subprocess.run(
            [CHROME, *CHROME_FLAGS, page.as_uri()],
            capture_output=True, text=True, timeout=180,
        ).stdout
    found = re.search(r'<pre id="probe-out">(.*?)</pre>', out, re.S)
    assert found, out[-2000:]
    answer = json.loads(found.group(1) or "null")
    assert answer is not None and "error" not in answer, answer
    return answer


# Three points around the middle of the canvas, and one drag. `tap` is a pointerdown and
# a pointerup at the same place; `drag` moves between them, which is how the map is
# panned and must therefore *not* leave a turnpoint behind.
_HARNESS = """
var canvas = document.querySelector('canvas.view3d');
var handle = window.__view3dAll[canvas.id];
var box = canvas.getBoundingClientRect();
function send(type, x, y) {
  canvas.dispatchEvent(new PointerEvent(type, {
    pointerId: 3, clientX: x, clientY: y, bubbles: true, cancelable: true,
    pointerType: 'mouse', isPrimary: true, button: 0, buttons: type === 'pointerup' ? 0 : 1
  }));
}
function tap(fx, fy) {
  var x = box.left + box.width * fx, y = box.top + box.height * fy;
  send('pointerdown', x, y);
  send('pointerup', x, y);
}
function drag(fx, fy, dx, dy) {
  var x = box.left + box.width * fx, y = box.top + box.height * fy;
  send('pointerdown', x, y);
  send('pointermove', x + dx, y + dy);
  send('pointerup', x + dx, y + dy);
}
function figure(name) {
  var cells = document.querySelectorAll('#plan-figures div');
  for (var i = 0; i < cells.length; i++) {
    if (cells[i].querySelector('.k').textContent === name) {
      return cells[i].querySelector('.v').textContent.trim();
    }
  }
  return null;
}
function turnpoints() { return handle.scene().climbs.length; }
"""


@needs_chrome
def test_a_tap_drops_a_turnpoint_and_a_drag_does_not():
    """The failure this exists for: the planner shares its canvas with the map's own
    gestures, so a naive click handler leaves a turnpoint behind on every pan. A
    pointerup that has travelled is a gesture, not a point."""
    answer = _run(_HARNESS + """
    tap(0.4, 0.5);
    var afterTap = turnpoints();
    drag(0.6, 0.5, 60, 20);
    var afterDrag = turnpoints();
    return { afterTap: afterTap, afterDrag: afterDrag };
    """)
    assert answer["afterTap"] == 1, "a tap on the map dropped no turnpoint"
    assert answer["afterDrag"] == 1, "a drag of the map left a turnpoint behind"


@needs_chrome
def test_three_points_are_scored_as_a_triangle():
    """And scored with XContest's multipliers, so a shape that is worth more says so.

    The course has to be declared closed. Three points on their own are two legs — see
    `test_three_points_left_open_are_two_legs_and_not_a_triangle`."""
    answer = _run(_HARNESS + """
    document.getElementById('plan-close').checked = true;
    tap(0.35, 0.40); tap(0.60, 0.40); tap(0.48, 0.62);
    return {
      points: turnpoints(),
      shape: document.querySelector('.plan-shape').textContent,
      klass: document.querySelector('.plan-shape').className,
      distance: figure('distance'),
      score: figure('score'),
      multiplier: figure('multiplier'),
      sides: document.getElementById('plan-legs').textContent
    };
    """)
    assert answer["points"] == 3
    assert "triangle" in answer["shape"]
    kilometres = float(answer["distance"].split(" ")[0])
    points = float(answer["score"].split(" ")[0])
    factor = float(answer["multiplier"].replace("×", ""))
    assert kilometres > 1, "three taps on a one-degree box measured nothing"
    assert points == pytest.approx(kilometres * factor, rel=1e-3), (
        "the score is not the distance times the multiplier it printed")
    assert factor in (xc.MULTIPLIER["flat"], xc.MULTIPLIER["fai"])
    assert answer["sides"].count("side") == 3, "a triangle printed legs, not sides"


@needs_chrome
def test_three_points_left_open_are_two_legs_and_not_a_triangle():
    """The route is what the reader drew, and the score is not allowed to draw a leg of
    its own. Three taps with the box unticked draw two legs on the map and are checked
    against airspace as two legs; the score closed them into a triangle anyway, adding a
    third side, calling the gap it had invented zero, and multiplying the result by 1.2.
    On the real page that reported a 250 km course as 397 km.

    The target is measured off the line the map drew, not recomputed here — the question
    is whether the number under the map describes the course above it."""
    answer = _run(_HARNESS + """
    tap(0.35, 0.40); tap(0.60, 0.40); tap(0.48, 0.62);
    var track = handle.scene().track;
    var open = { shape: document.querySelector('.plan-shape').textContent,
                 multiplier: figure('multiplier'),
                 distance: figure('distance'),
                 legs: document.getElementById('plan-legs').textContent,
                 drawn: track.lon.map(function (lon, i) { return [lon, track.lat[i]]; }) };
    document.getElementById('plan-close').checked = true;
    document.getElementById('plan-close').dispatchEvent(new Event('change'));
    var shut = handle.scene().track;
    open.closedDistance = figure('distance');
    open.closedShape = document.querySelector('.plan-shape').textContent;
    open.closedDrawn = shut.lon.length;
    return open;
    """)
    assert answer["shape"] == "open distance"
    assert float(answer["multiplier"].replace("×", "")) == xc.MULTIPLIER["open"]
    assert answer["legs"].count("leg") == 2, "an open route printed sides, not legs"

    drawn = answer["drawn"]
    assert len(drawn) == 3, "the map drew a leg the reader had not asked for"
    walked = sum(_haversine(drawn[i - 1], drawn[i]) for i in range(1, len(drawn)))
    assert float(answer["distance"].split(" ")[0]) == pytest.approx(walked / 1000, abs=0.02), (
        "the printed distance is not the course the map drew")

    # And ticking the box is what closes it: the same three points, a third leg on the
    # map, and a triangle under it.
    assert answer["closedDrawn"] == 4
    assert "triangle" in answer["closedShape"]
    assert float(answer["closedDistance"].split(" ")[0]) > walked / 1000


def _haversine(a, b):
    """The FAI sphere, as `planner/render_html.py` and `tracklog_viewer/geo.py` both use."""
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2)
    return 2 * 6371000 * math.asin(min(1, math.sqrt(h)))


@needs_chrome
def test_undo_and_clear_take_the_points_back_off():
    answer = _run(_HARNESS + """
    tap(0.35, 0.40); tap(0.60, 0.40); tap(0.48, 0.62);
    document.getElementById('plan-undo').click();
    var afterUndo = turnpoints();
    document.getElementById('plan-clear').click();
    return { afterUndo: afterUndo, afterClear: turnpoints(),
             empty: document.getElementById('plan-legs').textContent };
    """)
    assert answer["afterUndo"] == 2
    assert answer["afterClear"] == 0
    assert answer["empty"] == ""


@needs_chrome
def test_two_points_are_open_distance_and_not_a_triangle():
    """The degenerate case that a triangle-shaped scorer gets wrong: two points have no
    perimeter, and calling them a flat triangle would multiply an out-and-back by 1.2."""
    answer = _run(_HARNESS + """
    tap(0.35, 0.45); tap(0.62, 0.45);
    return { shape: document.querySelector('.plan-shape').textContent,
             multiplier: figure('multiplier'),
             legs: document.getElementById('plan-legs').textContent };
    """)
    assert answer["shape"] == "open distance"
    assert float(answer["multiplier"].replace("×", "")) == xc.MULTIPLIER["open"]
    assert answer["legs"].count("leg") == 1


def test_the_planner_scores_with_the_reports_own_constants():
    """A planner that scored a task differently from the report that later measures the
    flight would be worse than no planner, so the constants are interpolated from
    `xc.py` rather than typed into the script."""
    source = planner_html.SCRIPT
    assert f"FAI_MIN_SIDE = {xc.FAI_MIN_SIDE}" in source
    assert f"MAX_CLOSING = {xc.MAX_CLOSING}" in source
    for name, value in xc.MULTIPLIER.items():
        assert f"{name}: {value}" in source

    page = planner_html.body()
    assert "28%" in page and "20%" in page, "the page states the rules it scores by"


# ---- what the line crosses -----------------------------------------------------------
#
# The feature the whole page is arranged around. The turnpoints are dropped by lon/lat
# here rather than by clicking, because where a click lands is already tested above and
# what is being measured now is the geometry, which wants exact coordinates.

_DROP = """
var canvas = document.querySelector('canvas.view3d');
var handle = window.__view3dAll[canvas.id];
function at(lon, lat) {
  var m = handle.toMetres(lon, lat);
  var p = handle.worldProject(m[0], m[1], handle.groundAt(lon, lat));
  var box = canvas.getBoundingClientRect();
  var x = box.left + p[0] / canvas.width * box.width;
  var y = box.top + p[1] / canvas.height * box.height;
  canvas.dispatchEvent(new PointerEvent('pointerdown', {
    pointerId: 5, clientX: x, clientY: y, bubbles: true, cancelable: true,
    pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1 }));
  canvas.dispatchEvent(new PointerEvent('pointerup', {
    pointerId: 5, clientX: x, clientY: y, bubbles: true, cancelable: true,
    pointerType: 'mouse', isPrimary: true, button: 0, buttons: 0 }));
}
function crossed() {
  return Array.prototype.map.call(
    document.querySelectorAll('#plan-airspace .plan-crossed li'),
    function (row) {
      return { name: row.querySelector('.plan-crossed-name').textContent,
               note: row.querySelector('.plan-crossed-km').textContent };
    });
}
function kmOf(note) { return parseFloat(note); }

// The time control, driven the way a reader drives it: type a Czech wall-clock time and
// tick the box. Everything downstream — the list marks and the map filter — hangs off
// the two events those two actions fire.
function askAbout(local) {
  var input = document.getElementById('asp-when');
  var box = document.getElementById('asp-when-on');
  input.value = local;
  box.checked = true;
  box.dispatchEvent(new Event('change', { bubbles: true }));
  input.dispatchEvent(new Event('input', { bubbles: true }));
}
function marks() {
  return Array.prototype.map.call(
    document.querySelectorAll('#plan-airspace .plan-crossed li'),
    function (row) {
      var tag = row.querySelector('.plan-when');
      return { name: row.querySelector('.plan-crossed-name').textContent,
               mark: tag ? tag.textContent : null };
    });
}
// What is under a point on the map. A ring the filter dropped was never drawn and so is
// not in the hit list — which is the reader-facing consequence of hiding it, and the
// only one observable from here. `redraw` first because `setAirspaceFilter` paints on
// the next animation frame and this probe returns before one arrives; on the page that
// is 16 ms and nobody sees it, in here it is the difference between the two answers.
function under(lon, lat) {
  handle.redraw();
  var m = handle.toMetres(lon, lat);
  var p = handle.worldProject(m[0], m[1], handle.groundAt(lon, lat));
  var box = canvas.getBoundingClientRect();
  var found = handle.airspaceAt(box.left + p[0] / canvas.width * box.width,
                               box.top + p[1] / canvas.height * box.height);
  return found ? found.n : null;
}
"""


@needs_chrome
def test_a_leg_through_a_band_measures_how_far_through_it_goes():
    """A 0.2 degree band of longitude at 49.5 N is 14.4 km wide, and a leg crossing it
    square must report that — not the leg's own length, and not a count of samples."""
    band = _band("TMA TEST", 14.4, 14.6, 49.0, 50.0)
    answer = _run(_DROP + """
    at(14.1, 49.5); at(14.9, 49.5);
    return { crossed: crossed(), legs: document.getElementById('plan-legs').textContent };
    """, spaces=[band])
    assert len(answer["crossed"]) == 1, answer["crossed"]
    row = answer["crossed"][0]
    assert row["name"].startswith("TMA TEST")
    kilometres = float(row["note"].split(" ")[0])
    assert 13.5 < kilometres < 15.3, f"a 14.4 km band measured {kilometres} km"
    assert "from the ground" in row["note"], "a GND floor was reported as an altitude"


@needs_chrome
def test_a_leg_that_misses_says_so_rather_than_saying_nothing():
    """Silence and 'nothing crossed' look the same on screen and mean opposite things:
    one is an answer and the other is a page that has not run."""
    band = _band("TMA TEST", 14.4, 14.6, 49.0, 49.2)
    answer = _run(_DROP + """
    at(14.1, 49.8); at(14.9, 49.8);
    return { crossed: crossed(),
             text: document.getElementById('plan-airspace').textContent };
    """, spaces=[band])
    assert answer["crossed"] == []
    assert "Nothing on this map is crossed" in answer["text"]
    assert "NOTAM" in answer["text"], (
        "a clear route must still say what this check does not cover")


@needs_chrome
def test_the_lowest_floor_comes_first():
    """What a paraglider hits soonest is what it most needs to know, so the order is by
    floor and not by how much of the route is inside."""
    high = _band("HIGH TMA", 14.2, 14.9, 49.0, 50.0, floor="FL 95")
    low = _band("LOW ZONE", 14.55, 14.6, 49.0, 50.0, floor="1000 ft AMSL")
    answer = _run(_DROP + """
    at(14.1, 49.5); at(14.95, 49.5);
    return { crossed: crossed() };
    """, spaces=[high, low])
    names = [row["name"].split(" ")[0] for row in answer["crossed"]]
    assert names[0] == "LOW", f"the higher floor was listed first: {names}"
    assert "HIGH" in names[1]
    # ...even though the high one covers far more of the route.
    kilometres = [float(row["note"].split(" ")[0]) for row in answer["crossed"]]
    assert kilometres[1] > kilometres[0]
    assert "floor 305 m" in answer["crossed"][0]["note"], (
        f"1 000 ft was not converted to metres: {answer['crossed'][0]['note']}")


@needs_chrome
def test_the_closing_leg_is_checked_too():
    """A closed course flies home, and the leg home crosses whatever it crosses. Checking
    only the drawn legs would clear a task that flies straight through a CTR on the way
    back — the one leg a pilot is most tired on."""
    band = _band("HOME CTR", 14.4, 14.6, 49.0, 49.35)
    answer = _run(_DROP + """
    at(14.1, 49.2); at(14.5, 49.9); at(14.9, 49.2);
    var open = crossed().length;
    document.getElementById('plan-close').checked = true;
    document.getElementById('plan-close').dispatchEvent(new Event('change'));
    return { open: open, closed: crossed().length, rows: crossed() };
    """, spaces=[band])
    assert answer["open"] == 0, (
        "the outward legs already crossed it, so the test proves nothing")
    assert answer["closed"] == 1, "the closing leg was never checked"


# ---- when the field is open ----------------------------------------------------------
#
# The one layer on this map that is genuinely time-varying. An ATZ is class G airspace
# permanently; what keeps hours is the aerodrome, and therefore the traffic in the okruh.


@needs_chrome
def test_a_crossing_is_marked_open_or_shut_at_the_planned_hour():
    """`15 APR - 15 OCT SAT, SUN, HOL 0700-1400` is UTC, so a Saturday at 11:00 Prague
    time is 09:00 Z and inside it, and the same hour on the Tuesday is not. Getting the
    two apart is the whole feature: the published window *is* the Czech XC weekend, so a
    planner that ignored it would say the same thing on both days."""
    band = _band("OKRUH LKTA", 14.4, 14.6, 49.0, 50.0,
                 hours="15 APR - 15 OCT SAT, SUN, HOL 0700-1400, otherwise O/R")
    answer = _run(_DROP + """
    at(14.1, 49.5); at(14.9, 49.5);
    askAbout('2026-08-08T11:00');
    var saturday = marks();
    askAbout('2026-08-11T11:00');
    var tuesday = marks();
    return { saturday: saturday, tuesday: tuesday,
             note: document.getElementById('plan-airspace').textContent };
    """, spaces=[band])
    assert [row["mark"] for row in answer["saturday"]] == ["operating"]
    assert [row["mark"] for row in answer["tuesday"]] == ["outside hours"]
    assert "not that nobody is" in answer["note"], (
        "'outside published hours' must never be rendered as 'closed' — nearly every "
        "field adds 'otherwise O/R'")


@needs_chrome
def test_the_shut_field_leaves_the_map_but_stays_in_the_list():
    """The map is decluttering and the list is the answer. Dropping a zone out of the
    list because a VFR manual page said `SAT, SUN, HOL` would be the tool quietly
    deciding something it does not know."""
    band = _band("OKRUH LKTA", 14.4, 14.6, 49.0, 50.0,
                 hours="15 APR - 15 OCT SAT, SUN, HOL 0700-1400, otherwise O/R")
    answer = _run(_DROP + """
    at(14.1, 49.5); at(14.9, 49.5);
    var before = under(14.5, 49.5);
    askAbout('2026-08-11T11:00');
    return { before: before, after: under(14.5, 49.5), rows: marks().length };
    """, spaces=[band])
    assert answer["before"] == "OKRUH LKTA  (GND – FL 95)"
    assert answer["after"] is None, "a shut field was still drawn on the map"
    assert answer["rows"] == 1, "the list dropped a zone the route really does cross"


@needs_chrome
def test_a_zone_with_no_published_hours_is_never_marked():
    """Which is 251 base airspaces, whose activation is in NOTAMs this repository does
    not fetch, and all 74 SLZ okruhy, whose pages publish no hours. Marking those would
    be inventing an answer for three quarters of the map."""
    band = _band("MCTR KBELY", 14.4, 14.6, 49.0, 50.0)
    answer = _run(_DROP + """
    at(14.1, 49.5); at(14.9, 49.5);
    askAbout('2026-08-11T03:00');
    return { rows: marks(), under: under(14.5, 49.5) };
    """, spaces=[band])
    assert [row["mark"] for row in answer["rows"]] == [None]
    assert answer["under"] is not None, "a ring with no hours was hidden by the clock"

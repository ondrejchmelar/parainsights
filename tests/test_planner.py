"""The planner, driven in a real browser.

Whether three points score as a triangle, whether an open course is two legs, what a
leg crosses and when — all claims about what the page does with the points it is given.
So this renders the page over a synthetic DEM, hands it clicks the way the map would
(`_MAP`) and reads the answers out of the DOM.

No network: the terrain is generated and there is no basemap."""

import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

from airspaces import cli as airspaces_cli
from planner import render_html as planner_html
from tests.js import needs_node

xc = planner_html.xc
from tests.browser import CHROME, CHROME_FLAGS, needs_chrome
from parainsights_map import terrain as terrain_module
from parainsights_map import view3d


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


def _page(spaces=(), terrain=None) -> str:
    from airspaces import scene as airspace_scene

    payload = airspace_scene.build(list(spaces), terrain=terrain or _terrain(),
                                   tiles=False)
    panel = view3d.panel(payload, "planner")
    return airspaces_cli._page(planner_html.body(scene_panel=panel), "Plan a task",
                               three_d=True)


PROBE = """
<pre id="probe-out"></pre>
<script>
window.addEventListener('load', function () {
  setTimeout(function () {
    var answer;
    function put(value) { document.getElementById('probe-out').textContent = JSON.stringify(value); }
    try { answer = (function () { %s })(); }
    catch (error) { answer = { error: String((error && error.stack) || error) }; }
    // A body may return a promise (the import is one); its value is the answer.
    if (answer && typeof answer.then === 'function') {
      answer.then(put, function (error) { put({ error: String((error && error.stack) || error) }); });
    } else put(answer);
  }, 900);
});
</script>
"""


def _run(body: str, spaces=(), terrain=None) -> dict:
    with tempfile.TemporaryDirectory() as folder:
        page = Path(folder) / "planner.html"
        page.write_text(_page(spaces, terrain) + PROBE % body, encoding="utf-8")
        out = subprocess.run(
            [CHROME, *CHROME_FLAGS, page.as_uri()],
            capture_output=True, text=True, timeout=180,
        ).stdout
    found = re.search(r'<pre id="probe-out">(.*?)</pre>', out, re.S)
    assert found, out[-2000:]
    answer = json.loads(found.group(1) or "null")
    assert answer is not None and "error" not in answer, answer
    return answer


# The map (`map3d`) needs MapLibre, which these probes do not load; the planner's side of
# its contract is three members, so a stand-in carries them: `onClick` (a click on the
# ground, as [lon, lat]), `setRoute` (the course drawn) and `setShapes` (the FAI areas).
# A drag of the map dropping no turnpoint is MapLibre's own `click`, not the planner's.
_MAP = """
var box = document.querySelector('.view3d');
var handle = window.__view3dAll[box.id];
var route = { walk: [], points: [] }, clicked = null;
var entry = { onClick: function (fn) { clicked = fn; },
              setRoute: function (walk, points) { route = { walk: walk || [], points: points || [] }; },
              setShapes: function () {} };
window.__mergedAll = window.__mergedAll || {};
window.__mergedAll[box.id] = entry;
document.querySelector('[data-planner] .view3d-panel')
  .dispatchEvent(new CustomEvent('merged-ready', { detail: entry }));
document.getElementById('plan-draw').click();
function turnpoints() { return route.points.length; }
"""


# Three points around the middle of the ground, by fraction of its box.
_HARNESS = _MAP + """
var dem = handle.scene().terrain;
function tap(fx, fy) {
  clicked([dem.west + (dem.east - dem.west) * fx, dem.north - (dem.north - dem.south) * fy]);
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
"""


@needs_chrome
def test_a_click_drops_a_turnpoint_only_while_drawing():
    """Off, a click on the map is the map's; pressing *Draw a task* makes it a point."""
    answer = _run(_HARNESS + """
    document.getElementById('plan-draw').click();
    tap(0.4, 0.5);
    var off = turnpoints();
    document.getElementById('plan-draw').click();
    tap(0.4, 0.5);
    return { off: off, on: turnpoints() };
    """)
    assert answer["off"] == 0, "a click dropped a turnpoint while not drawing"
    assert answer["on"] == 1, "a click on the map dropped no turnpoint"


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
    var track = route.walk;
    var open = { shape: document.querySelector('.plan-shape').textContent,
                 multiplier: figure('multiplier'),
                 distance: figure('distance'),
                 legs: document.getElementById('plan-legs').textContent,
                 drawn: track.slice() };
    document.getElementById('plan-close').checked = true;
    document.getElementById('plan-close').dispatchEvent(new Event('change'));
    var shut = route.walk;
    open.closedDistance = figure('distance');
    open.closedShape = document.querySelector('.plan-shape').textContent;
    open.closedDrawn = shut.length;
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
def test_redo_brings_back_what_undo_took_and_a_clear_can_be_undone():
    """Undo and redo walk the task's history — a point dropped, a clear — and a new point
    forgets what was undone. Each tool is disabled when it has nothing to do."""
    answer = _run(_HARNESS + """
    function state() {
      return [turnpoints()].concat(['plan-undo', 'plan-redo', 'plan-clear'].map(function (id) {
        return document.getElementById(id).disabled; }));
    }
    var steps = [state()];
    tap(0.35, 0.40); tap(0.60, 0.40); tap(0.48, 0.62);
    steps.push(state());
    document.getElementById('plan-clear').click(); steps.push(state());
    document.getElementById('plan-undo').click(); steps.push(state());
    document.getElementById('plan-undo').click(); steps.push(state());
    document.getElementById('plan-redo').click(); steps.push(state());
    document.getElementById('plan-undo').click();
    tap(0.30, 0.70); steps.push(state());
    return { steps: steps, label: document.querySelector('#plan-draw span').textContent,
             pressed: document.getElementById('plan-draw').getAttribute('aria-pressed') };
    """)
    # [points, undo disabled, redo disabled, clear disabled]
    assert answer["steps"] == [
        [0, True, True, True],      # nothing yet
        [3, False, True, False],    # three dropped
        [0, False, True, True],     # cleared
        [3, False, False, False],   # the clear undone
        [2, False, False, False],   # and the third point
        [3, False, False, False],   # redone
        [3, False, True, False],    # undone, then a new point: nothing left to redo
    ]
    assert answer["label"] == "Done" and answer["pressed"] == "true"


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


@needs_node
def test_the_planner_scores_with_the_reports_own_constants():
    """A planner that scored a task differently from the report that later measures the
    flight would be worse than no planner, so the constants are read from `js/xc.js` —
    the scorer itself, asked here — rather than typed into the script."""
    from tests import js

    scorer = js.run("return { fai: TV.xc.FAI_MIN_SIDE, closing: TV.xc.MAX_CLOSING, m: TV.xc.MULTIPLIER };")
    assert (xc.FAI_MIN_SIDE, xc.MAX_CLOSING) == (scorer.fai, scorer.closing)
    assert xc.MULTIPLIER == dict(scorer.m)
    source = planner_html.SCRIPT
    assert f"FAI_MIN_SIDE = {xc.FAI_MIN_SIDE}" in source
    # The world rules are the report's; ČPP's are the Czech cup's own (5%, 1.8/2.2).
    assert f"world: {{ closing: {xc.MAX_CLOSING}," in source
    assert "cpp: { closing: 0.05, multiplier: { open: 1.0, flat: 1.8, fai: 2.2 } }" in source
    for name, value in xc.MULTIPLIER.items():
        assert f"{name}: {value}" in source

    page = planner_html.body()
    assert "28%" in page and "20%" in page, "the page states the rules it scores by"


# ---- what the line crosses -----------------------------------------------------------
#
# The feature the whole page is arranged around. The turnpoints are dropped by lon/lat
# here rather than by clicking, because where a click lands is already tested above and
# what is being measured now is the geometry, which wants exact coordinates.

_DROP = _MAP + """
function at(lon, lat) { clicked([lon, lat]); }
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
// What is under a point on the map: the smallest ring there that the map's airspace
// filter keeps (`setAirspaceFilter`). A ring the filter dropped is not drawn, which is
// the reader-facing consequence of hiding it.
function under(lon, lat) {
  var keep = handle.airspaceFilter(), found = null;
  (handle.scene().airspaces || []).forEach(function (ring) {
    if (keep && !keep(ring)) return;
    var inside = false;
    for (var a = 0, b = ring.lon.length - 1; a < ring.lon.length; b = a++) {
      if ((ring.lat[a] > lat) !== (ring.lat[b] > lat) &&
          lon < (ring.lon[b] - ring.lon[a]) * (lat - ring.lat[a]) / (ring.lat[b] - ring.lat[a]) + ring.lon[a]) {
        inside = !inside;
      }
    }
    if (inside) found = ring;   // the rings run biggest first, so the last is the smallest
  });
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
def test_zones_are_listed_in_the_order_the_task_reaches_them():
    """As a pilot meets them flying the task, not by floor: a high zone the route enters
    first comes before a low one it reaches later, and flown the other way round the
    order turns round too."""
    high = _band("HIGH TMA", 14.2, 14.5, 49.0, 50.0, floor="FL 95")
    low = _band("LOW ZONE", 14.7, 14.8, 49.0, 50.0, floor="1000 ft AMSL")
    answer = _run(_DROP + """
    at(14.1, 49.5); at(14.95, 49.5);
    var east = crossed();
    document.getElementById('plan-clear').click();
    at(14.95, 49.5); at(14.1, 49.5);
    return { east: east, west: crossed() };
    """, spaces=[high, low])
    assert [row["name"].split(" ")[0] for row in answer["east"]] == ["HIGH", "LOW"]
    assert [row["name"].split(" ")[0] for row in answer["west"]] == ["LOW", "HIGH"]
    note = next(row["note"] for row in answer["east"] if row["name"].startswith("LOW"))
    assert "floor 305 m" in note, f"1 000 ft was not converted to metres: {note}"


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


@needs_chrome
def test_the_task_menu_sets_the_scoring_and_the_strip_says_what_is_set():
    """The options moved into a Task menu in the map's top row (October 2026); the strip
    under the map keeps one line of what is set, and pressing it opens the menu."""
    answer = _run(_DROP + """
    var before = document.getElementById('plan-opts-sum').textContent;
    document.querySelector('.plan-rules-seg [data-rules="cpp"]').click();
    var close = document.getElementById('plan-close');
    close.checked = true; close.dispatchEvent(new Event('change'));
    document.getElementById('plan-opts-sum').click();
    return { before: before, after: document.getElementById('plan-opts-sum').textContent,
             rules: document.getElementById('plan-rules').value,
             pressed: document.querySelector('.plan-rules-seg [data-rules="cpp"]').getAttribute('aria-pressed'),
             open: !document.getElementById('plan-task-menu').hidden };
    """)
    assert answer["before"].startswith("Open · FAI areas · XContest · takeoff ")
    assert answer["after"].startswith("Closed · FAI areas · ČPP · takeoff ")
    assert answer["rules"] == "cpp" and answer["pressed"] == "true"
    assert answer["open"], "the line under the score opens the menu"


# ---- when the zone is booked, or off for the season (October 2026) -------------------
#
# openAIP carries both in the name: `LKTSA26 PRAVONIN (INACTIVE 01 JUL TO 31 AUG)` was
# drawn on an August date, and in September nothing said it is there only when booked.


def test_the_name_says_when_the_zone_is_there():
    from airspaces.scene import activation

    assert activation("LKTSA26 PRAVONIN (INACTIVE 01 JUL TO 31 AUG)", "TSA") == (
        "LKTSA26 PRAVONIN", "", [7, 1, 8, 31])
    assert activation("LKTSA44 JESENIKY (BY AUP)", "TSA") == ("LKTSA44 JESENIKY", "AUP", None)
    assert activation("NTM-SPALOV (BY NOTAM)", "TSA") == ("NTM-SPALOV", "NOTAM", None)
    assert activation("LKTRA12 UNANOV", "TRA") == ("LKTRA12 UNANOV", "", None), (
        "activated, but by what is the AIS's to say")
    assert activation("LKD2 KOURIM", "D") == ("LKD2 KOURIM", None, None), "ENR 5.1: H24"
    assert activation("CTR PRAHA", "CTR D") == ("CTR PRAHA", None, None), (
        "a CTR is there whether or not anybody books it")


@needs_chrome
def test_a_zone_off_for_the_summer_leaves_the_map_and_a_booked_one_says_so():
    tsa = _band("LKTSA26 PRAVONIN (INACTIVE 01 JUL TO 31 AUG)", 14.4, 14.6, 49.0, 50.0,
                floor="300ft AGL", ceiling="1000ft AGL", klass="TSA")
    answer = _run(_DROP + """
    at(14.1, 49.5); at(14.9, 49.5);
    askAbout('2026-08-11T11:00');
    var august = { rows: marks(), under: under(14.5, 49.5),
                   note: document.getElementById('plan-airspace').textContent };
    askAbout('2026-09-15T11:00');
    return { august: august, september: marks(), under: under(14.5, 49.5),
             note: document.getElementById('plan-airspace').textContent };
    """, spaces=[tsa])
    assert answer["august"]["rows"] == [{"name": "LKTSA26 PRAVONIN  (300ft AGL – 1000ft AGL)",
                                         "mark": "inactive 1 Jul – 31 Aug"}]
    assert answer["august"]["under"] is None, "drawn in its inactive season"
    assert "published inactive season" in answer["august"]["note"]
    assert [row["mark"] for row in answer["september"]] == ["if activated"]
    assert answer["under"] is not None, "a booked zone is hidden: no date can say it is not"
    assert "AUP" in answer["note"]


# ------------------------------------------- outside the airspace's country
#
# The planner's ground reaches the Alps and its airspace is Czech only. A route there
# crosses "nothing" only in the sense that nothing was looked for, and the list has to
# say which of the two it means.


def _terrain_at(west, east, south, north):
    base = _terrain()
    return terrain_module.Terrain(west=west, east=east, south=south, north=north,
                                  elevations=base.elevations)


@needs_chrome
def test_a_route_outside_czechia_is_not_called_clear():
    answer = _run(_DROP + """
    at(13.7, 47.3); at(14.3, 47.7);
    return { points: turnpoints(),
             text: document.getElementById('plan-airspace').textContent };
    """, terrain=_terrain_at(13.5, 14.5, 47.0, 48.0))
    assert answer["points"] == 2, "a turnpoint in Austria was refused"
    assert "outside Czechia" in answer["text"]
    assert "nothing on it has been checked" in answer["text"]
    assert "Nothing on this map is crossed" not in answer["text"], (
        "a route the map has no airspace for was reported as clear")


@needs_chrome
def test_a_route_over_the_border_says_how_much_was_not_checked():
    """South from 48.4 N to 49.2 N along 14.5 E: the border is at about 48.6, so a
    quarter of the leg is in Austria and the rest is checked and clear."""
    answer = _run(_DROP + """
    at(14.5, 48.4); at(14.5, 49.2);
    return document.getElementById('plan-airspace').textContent;
    """, terrain=_terrain_at(14.0, 15.0, 48.3, 49.3))
    found = re.search(r"([\d.]+) km of this route is outside Czechia", answer)
    assert found, answer
    assert 10 < float(found.group(1)) < 35, answer
    assert "Nothing on this map is crossed" in answer, "the checked part lost its answer"


def _decode_polyline(text):
    """Google's polyline algorithm, read back: what XCTrack does with a turnpoint's `z`."""
    values, i = [], 0
    while i < len(text):
        result = shift = 0
        while True:
            b = ord(text[i]) - 63
            i += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        values.append(~(result >> 1) if result & 1 else result >> 1)
    return values


@needs_chrome
def test_the_task_goes_to_xctrack_as_a_waypoints_task():
    """XCTrack's waypoints task (xctrack.org/Competition_Interfaces.html): `T` "W", `V` 2,
    each turnpoint a name and its longitude, latitude and altitude polyline-encoded. A
    closed course returns to turnpoint 1, and the export is offered only once there is a
    route."""
    answer = _run(_HARNESS + """
    var before = document.getElementById('plan-xct-export').hidden;
    document.getElementById('plan-close').checked = true;
    tap(0.35, 0.40); tap(0.60, 0.40); tap(0.48, 0.62);
    var ground = handle.groundAt(dem.west + (dem.east - dem.west) * 0.35,
                                 dem.north - (dem.north - dem.south) * 0.40);
    return { before: before, after: document.getElementById('plan-xct-export').hidden,
             task: window.__plannerTask(), ground: ground,
             first: [dem.west + (dem.east - dem.west) * 0.35, dem.north - (dem.north - dem.south) * 0.40] };
    """)
    assert answer["before"] is True, "an export was offered with no route to send"
    assert answer["after"] is False
    task = answer["task"]
    assert task["T"] == "W" and task["V"] == 2
    assert [tp["n"] for tp in task["t"]] == ["TP1", "TP2", "TP3", "TP1"]
    lon, lat, alt = _decode_polyline(task["t"][0]["z"])
    assert lon / 1e5 == pytest.approx(answer["first"][0], abs=2e-5)
    assert lat / 1e5 == pytest.approx(answer["first"][1], abs=2e-5)
    assert alt == pytest.approx(answer["ground"], abs=1), "the turnpoint lost the ground's height"



@needs_chrome
def test_xctrack_is_one_split_button_under_the_strip():
    """One button for the device's best way, the other two behind its arrow; a desktop
    (no coarse pointer here) leads with the QR code, which opens in the dialog. It sits
    under the map's strip, ahead of what the task crosses; the score is in the strip."""
    answer = _run(_HARNESS + """
    tap(0.35, 0.40); tap(0.60, 0.40);
    var more = document.getElementById('plan-xct-more');
    var shut = document.getElementById('plan-xct-menu').hidden;
    more.click();
    function before(a, b) {
      return !!(document.getElementById(a).compareDocumentPosition(document.getElementById(b))
                & Node.DOCUMENT_POSITION_FOLLOWING);
    }
    return { main: document.getElementById('plan-xct-main').dataset.method,
             menu: Array.prototype.map.call(document.querySelectorAll('#plan-xct-menu button'),
                                            function (b) { return b.dataset.method; }),
             shut: shut, open: !document.getElementById('plan-xct-menu').hidden,
             order: before('plan-strip', 'plan-xct') && before('plan-xct', 'plan-airspace'),
             scoreInStrip: !!document.getElementById('plan-figures').closest('#plan-strip') };
    """)
    assert answer["main"] == "qr"
    assert answer["menu"] == ["file", "code", "save"], "the other two ways, then keeping it here"
    assert answer["shut"] is True and answer["open"] is True
    assert answer["order"], "the export is not under the strip, ahead of the crossings"
    assert answer["scoreInStrip"]


def test_the_polyline_encoding_is_googles():
    """The encoder against the algorithm's own published example
    (developers.google.com/maps/documentation/utilities/polylinealgorithm): -179.9832104
    encodes as `` `~oia@ ``. Run through Node, from the planner's own source."""
    source = (Path(__file__).parent.parent / "planner/js/planner.js").read_text(encoding="utf-8")
    start = source.index("  function polyline(values) {")
    end = source.index("  function xctrackTask() {")
    script = source[start:end] + "\nconsole.log(polyline([-179.9832104 * 1e5]));\n"
    try:
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        pytest.skip("no node")
    assert out.stdout.strip() == "`~oia@"


@needs_chrome
def test_a_start_on_a_leg_scores_the_triangle_of_the_other_three():
    """XContest scores any three points of the route as the corners, the closing gap from
    start to end (October 2026: 1 on the leg 4–2, corners 2, 3, 4, was open distance).
    Not ticked closed: the route ends at 4, near the start, which is the closing gap."""
    answer = _run(_HARNESS + """
    function at(fx, fy) { return [dem.west + (dem.east - dem.west) * fx, dem.north - (dem.north - dem.south) * fy]; }
    var A = [0.30, 0.70], B = [0.70, 0.65], C = [0.50, 0.30];
    var S = [C[0] + (A[0] - C[0]) * 0.12, C[1] + (A[1] - C[1]) * 0.12];
    [S, A, B, C].forEach(function (p) { tap(p[0], p[1]); });
    return { shape: document.querySelector('.plan-shape').className,
             distance: figure('distance'), legs: document.getElementById('plan-legs').textContent };
    """)
    assert "is-open" not in answer["shape"], answer
    assert answer["legs"].count("side") == 3, answer
    assert "closing gap" in answer["legs"]


_XCTSK_V1 = {
    "taskType": "CLASSIC", "version": 1, "earthModel": "WGS84",
    "turnpoints": [
        {"type": "TAKEOFF", "radius": 400, "waypoint": {"name": "Rana", "lat": 50.4075, "lon": 13.7715, "altSmoothed": 426}},
        {"type": "SSS", "radius": 2000, "waypoint": {"name": "B", "lat": 50.6, "lon": 14.2, "altSmoothed": 300}},
        {"radius": 400, "waypoint": {"name": "C", "lat": 50.8, "lon": 13.9, "altSmoothed": 500}},
        {"type": "ESS", "radius": 400, "waypoint": {"name": "Rana", "lat": 50.4076, "lon": 13.7716, "altSmoothed": 426}},
    ],
    "sss": {"type": "RACE", "direction": "EXIT", "timeGates": ["10:00:00Z"]}, "goal": {"type": "CYLINDER"},
}


def _waypoints_v2():
    """The waypoints task as the export writes it, encoded here with the polyline rules."""
    def enc(v):
        v = round(v)
        v = ~(v << 1) if v < 0 else v << 1
        out = ""
        while v >= 0x20:
            out += chr((0x20 | (v & 0x1F)) + 63)
            v >>= 5
        return out + chr(v + 63)
    pts = [(13.7715, 50.4075, 426), (14.2, 50.6, 300), (13.9, 50.8, 500)]
    return {"T": "W", "V": 2, "t": [{"n": f"TP{i + 1}", "z": enc(lon * 1e5) + enc(lat * 1e5) + enc(alt)}
                                    for i, (lon, lat, alt) in enumerate(pts)]}


@needs_chrome
@pytest.mark.parametrize("form", ["file-v1", "waypoints", "qr", "qr-compressed"])
def test_a_task_comes_in_from_xctrack_in_every_form(form):
    """The three ways in end in one reader: the competition task (v1), the waypoints task
    the export writes, a QR code's `XCTSK:` text and its zlib form `XCTSKZ:`. A task that
    ends where it starts comes in closed, its last point dropped."""
    import base64
    import zlib
    task = _XCTSK_V1 if form == "file-v1" else _waypoints_v2()
    text = json.dumps(task)
    if form == "qr":
        text = "XCTSK:" + text
    elif form == "qr-compressed":
        text = "XCTSKZ:" + base64.b64encode(zlib.compress(text.encode())).decode()
    answer = _run(_MAP + """
    return window.__plannerImport(%s).then(function (n) {
      return { n: n, closed: document.getElementById('plan-close').checked,
               first: route.points[0], exportShown: !document.getElementById('plan-xct-export').hidden };
    });""" % json.dumps(text))
    if form == "file-v1":
        assert answer["n"] == 3 and answer["closed"] is True
    else:
        assert answer["n"] == 3 and answer["closed"] is False
    assert answer["first"][0] == pytest.approx(13.7715, abs=1e-4)
    assert answer["first"][1] == pytest.approx(50.4075, abs=1e-4)
    assert answer["exportShown"] is True


@needs_chrome
def test_something_that_is_not_a_task_is_refused():
    answer = _run(_MAP + """
    return window.__plannerImport('{"hello": 1}').then(function () { return { ok: true }; },
      function (error) { return { refused: String(error.message || error) }; });""")
    assert "not an XCTrack task" in answer["refused"]


@needs_chrome
def test_the_takeoff_time_opens_on_tomorrow_noon_and_lights_the_map():
    """The takeoff time is the sun's moment: a day, opening on tomorrow, and a time slid
    through it, opening on 12:00, in the reader's clock. Each change hands the map a sun
    table (`setSun`) for that moment over the task — the UTC minute of the day, and the
    offset that reads it back — and the aerodrome hours follow it."""
    answer = _run(_MAP + """
    var suns = [];
    entry.setSun = function (table) { suns.push(table); };
    var day = document.getElementById('plan-day'), time = document.getElementById('plan-time');
    var opened = [day.value, time.value, document.getElementById('plan-time-out').textContent];
    var tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    var expect = tomorrow.getFullYear() + '-' + pad(tomorrow.getMonth() + 1) + '-' + pad(tomorrow.getDate());
    day.value = '2026-07-04';
    day.dispatchEvent(new Event('input', { bubbles: true }));
    time.value = 930;
    time.dispatchEvent(new Event('input', { bubbles: true }));
    var last = suns[suns.length - 1], when = new Date('2026-07-04T15:30');
    return { opened: opened, expect: expect, at: last.at, offset: last.offset,
             wantAt: when.getUTCHours() * 60 + when.getUTCMinutes(),
             wantOffset: -when.getTimezoneOffset(), steps: last.track.az.length,
             step: last.track.step, hours: document.getElementById('asp-when').value,
             shown: document.getElementById('plan-time-out').textContent };
    """)
    assert answer["opened"] == [answer["expect"], "720", "12:00"]
    assert answer["at"] == answer["wantAt"]
    assert answer["offset"] == answer["wantOffset"]
    assert answer["step"] == 10 and answer["steps"] == 144
    assert answer["shown"] == "15:30"
    assert answer["hours"] == "2026-07-04T15:30", "the aerodrome hours follow the takeoff"


@needs_chrome
def test_the_rose_gets_the_forecast_wind_at_the_takeoff_hour():
    """The wind at 850 hPa (about 1500 m) from Open-Meteo, read at the hour nearest the
    slider; one request a day and place, and no wind where the forecast has none."""
    answer = _run(_MAP + """
    var winds = [], asked = [];
    entry.setSun = function () {};
    entry.setWind = function (w) { winds.push(w); };
    window.fetch = function (url) {
      asked.push(url);
      var speed = [], dir = [];
      for (var h = 0; h < 24; h++) { speed.push(h); dir.push(h < 12 ? 225 : null); }
      return Promise.resolve({ ok: true, json: function () {
        return Promise.resolve({ hourly: { wind_speed_850hPa: speed, wind_direction_850hPa: dir } }); } });
    };
    var day = document.getElementById('plan-day'), time = document.getElementById('plan-time');
    day.value = '2026-07-04';
    time.value = 600;
    time.dispatchEvent(new Event('input', { bubbles: true }));
    var hour = new Date('2026-07-04T10:00').getUTCHours();
    return new Promise(function (done) { setTimeout(done, 50); }).then(function () {
      var morning = winds[winds.length - 1];
      time.value = 1200;
      time.dispatchEvent(new Event('input', { bubbles: true }));
      return new Promise(function (done) { setTimeout(done, 50); }).then(function () {
        return { morning: morning, evening: winds[winds.length - 1], hour: hour,
                 requests: asked.filter(function (u) { return u.indexOf('2026-07-04') > 0; }).length,
                 url: asked[asked.length - 1] };
      });
    });
    """)
    assert answer["morning"] == {"ms": answer["hour"], "from": 225, "cardinal": "SW", "at": "at 1500 m"}
    assert answer["evening"] is None, "no direction in the forecast, no wind on the rose"
    assert answer["requests"] == 1
    assert "wind_speed_unit=ms" in answer["url"] and "850hPa" in answer["url"]


@needs_chrome
def test_the_strip_stays_under_the_map_in_full_screen():
    """The task's strip is part of the stage, as a flight's side view is part of its map
    block: full screen (here the maximised fallback) keeps it at the foot, map above."""
    answer = _run(_MAP + """
    var stage = document.querySelector('.asp-stage');
    stage.classList.add('is-maximised');
    var strip = document.getElementById('plan-strip').getBoundingClientRect();
    var map = document.querySelector('.asp-holder').getBoundingClientRect();
    return { inside: !!document.getElementById('plan-strip').closest('.asp-stage'),
             bottom: Math.round(strip.bottom), height: innerHeight,
             mapAbove: Math.round(map.bottom) <= Math.round(strip.top) + 1, mapTall: map.height > 200 };
    """)
    assert answer["inside"]
    assert abs(answer["bottom"] - answer["height"]) <= 1, answer
    assert answer["mapAbove"] and answer["mapTall"], answer


@needs_chrome
def test_a_task_is_kept_in_the_browser_and_comes_back():
    """Saved under a name in localStorage, listed in the Import menu with its own ×, and
    loaded back with its turnpoints, its closing and its rules. The same name saved again
    replaces the old one; deleting takes it off the list."""
    answer = _run(_HARNESS + """
    localStorage.removeItem('parainsights.planner.tasks');
    tap(0.35, 0.40); tap(0.60, 0.40); tap(0.48, 0.62);
    var close = document.getElementById('plan-close'), rules = document.getElementById('plan-rules');
    close.checked = true; rules.value = 'cpp';
    var S = window.__plannerSaved;
    S.save('Ridge run');
    var saved = JSON.parse(JSON.stringify(route.points));
    tap(0.20, 0.20);
    S.save('Ridge run');                     // the same name again: replaced, not added
    var afterReplace = S.list().length, replacedHas = S.list()[0].points.length;
    S.save('Short');
    document.getElementById('plan-clear').click();
    close.checked = false; rules.value = 'world';
    document.getElementById('plan-imp-more').click();
    var rows = Array.prototype.map.call(document.querySelectorAll('#plan-imp-menu .plan-saved-name'),
      function (n) { return n.textContent; });
    document.querySelectorAll('#plan-imp-menu .plan-saved-load')[1].click();   // "Ridge run"
    var loaded = { n: route.points.length, closed: close.checked, rules: rules.value };
    document.getElementById('plan-imp-more').click();
    document.querySelector('#plan-imp-menu .plan-saved-drop').click();       // delete "Short"
    var left = S.list().map(function (t) { return t.name; });
    return { afterReplace: afterReplace, replacedHas: replacedHas, rows: rows, loaded: loaded,
             left: left, savedFirst: saved[0] };
    """)
    assert answer["afterReplace"] == 1 and answer["replacedHas"] == 4
    assert answer["rows"] == ["Short", "Ridge run"], "newest first"
    assert answer["loaded"] == {"n": 4, "closed": True, "rules": "cpp"}
    assert answer["left"] == ["Ridge run"]

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
    try { answer = (function () { %s })(); }
    catch (error) { answer = { error: String((error && error.stack) || error) }; }
    document.getElementById('probe-out').textContent = JSON.stringify(answer);
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

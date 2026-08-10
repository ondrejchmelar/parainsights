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


def _page() -> str:
    from airspaces import scene as airspace_scene

    payload = airspace_scene.build([], terrain=_terrain(), basemaps={}, tiles=False)
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


def _run(body: str) -> dict:
    with tempfile.TemporaryDirectory() as folder:
        page = Path(folder) / "planner.html"
        page.write_text(_page() + PROBE % body, encoding="utf-8")
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
    """And scored with XContest's multipliers, so a shape that is worth more says so."""
    answer = _run(_HARNESS + """
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

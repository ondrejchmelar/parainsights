"""The sun and the wind in the 3D view: the light following the hover, and the arrows.

The solar table comes from `js/sun.js`, tested against a second algorithm in
`test_sun.py`. What that cannot see is whether the terrain is *lit* from where the table
says the sun was, whether hovering a chart moves it, and whether the arrows point where
they claim to. The shading is computed in the page — baked into vertex colours by the
WebGL backend and into the draped texture by the canvas one — so this drives a browser.

The arrows are measured as angles rather than as pixels. A wrong arrow is still an arrow,
and the wind one inverts a convention (`from` is where the wind comes *from*), which is
exactly the kind of error a screenshot cannot fail on.
"""

import json
import math

import pytest

from tests.test_view3d_gl import _probe, _scene, needs_chrome

# A real day over the fixture's own terrain, from the real generator: a table typed by
# hand here would be a second implementation to keep in step.
if __import__("shutil").which("node"):
    from tests import js
    DAY = {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in js.run(
        "return TV.sun.dayTrack({ year: 2024, month: 6, day: 20 }, 49.12, 14.12);").items()}
else:
    DAY = {"step": 10, "az": [], "el": []}
SUN = {
    "track": DAY,
    "date": "2024-06-20",
    "offset": 120,          # CEST
    "launch": 9 * 60,
    "landing": 15 * 60,
    "at": 12 * 60,
    "rise": 180,
    "set": 1200,
}
WIND = {"ms": 5.0, "from": 180.0, "cardinal": "S"}

# A cursor track over the fixture's terrain, carrying the minute of each sample — which
# is the whole mechanism: the hover names a moment, and the moment lights the ground.
CURSOR = {
    "lon": [round(14.02 + i * 0.002, 5) for i in range(20)],
    "lat": [round(49.05 + i * 0.001, 5) for i in range(20)],
    "alt": [2000 + i * 10 for i in range(20)],
    "min": [9 * 60 + i * 19 for i in range(20)],       # 09:00 to about 15:00 UTC
}

_HOVER = """
var panel = document.querySelector('.view3d-panel');
var h = window.__handle;
var out = {};

function frame() {
  h.redraw();
  var source = panel.querySelector('canvas.view3d-gl') ||
               panel.querySelector('canvas.view3d');
  var small = document.createElement('canvas');
  small.width = 32; small.height = 32;
  small.getContext('2d').drawImage(source, 0, 0, 32, 32);
  return small.toDataURL();
}

out.hasSlider = !!panel.querySelector('.view3d-sun-slider');
out.atRest = h.rose().sun.minute;
var rest = frame();

h.setCursor(0);
out.early = h.rose().sun;
var early = frame();

h.setCursor(19);
out.late = h.rose().sun;
var late = frame();

h.clearCursor();
out.afterLeaving = h.rose().sun.minute;
out.restored = frame() === rest;
out.moved = early !== late;
return out;
"""

_ARROWS = """
var h = window.__handle;
var out = {};
h.view.yaw = 0;
h.redraw();
out.atNorthUp = h.rose();
h.view.yaw = Math.PI / 2;
h.redraw();
out.turned = h.rose();
return out;
"""

_NO_SUN = """
var h = window.__handle;
var rose = h.rose();
return { sun: rose.sun, wind: rose.wind ? rose.wind.from : null };
"""


def wrapped(radians: float) -> float:
    """Screen angle in degrees, in (-180, 180]. 270 and -90 are the same direction, and
    only one of them is a readable assertion."""
    return (math.degrees(radians) + 180) % 360 - 180


@pytest.fixture(scope="module")
def hovered():
    return _probe(_scene(sun=SUN, wind=WIND, cursor=CURSOR), _HOVER)


@needs_chrome
class TestTheSunFollowsTheCursor:
    def test_there_is_no_time_control(self, hovered):
        """The slider offered hours the flight never saw and made the reader hunt for a
        moment the charts were already pointing at."""
        assert hovered["hasSlider"] is False

    def test_it_rests_on_the_middle_of_the_flight(self, hovered):
        assert hovered["atRest"] == SUN["at"]

    def test_hovering_moves_the_sun_to_that_moment(self, hovered):
        assert hovered["early"]["minute"] == CURSOR["min"][0]
        assert hovered["late"]["minute"] == CURSOR["min"][-1]
        # Morning in the east, afternoon in the west, at 49°N in June.
        assert hovered["early"]["az"] < 180 < hovered["late"]["az"]

    def test_the_terrain_is_relit_as_the_cursor_moves(self, hovered):
        assert hovered["moved"] is True

    def test_leaving_the_charts_holds_the_light_where_it_was(self, hovered):
        """The marker goes; the light stays.

        Snapping back to mid-flight was a full re-light and a colour swing across the
        whole terrain, fired by the pointer merely leaving a chart on its way somewhere
        else — and it undid the comparison the reader had just set up, usually at the
        moment they turned to look at the ground. Mid-flight is still where an untouched
        panel starts, which `test_it_rests_on_the_middle_of_the_flight` holds.
        """
        assert hovered["afterLeaving"] == CURSOR["min"][-1]
        assert hovered["afterLeaving"] != SUN["at"], "the fixture cannot tell the two apart"
        assert hovered["restored"] is False


@needs_chrome
class TestTheArrows:
    def test_the_wind_arrow_points_where_the_wind_is_going(self):
        """`from` is where it comes from — every forecast, every pilot. The arrow shows
        where the air is going, so it is the opposite bearing. Drawing it along the
        reported one is the classic 180° error, and it looks perfectly fine."""
        answer = _probe(_scene(sun=SUN, wind=WIND, cursor=CURSOR), _ARROWS)
        wind = answer["atNorthUp"]["wind"]
        assert wind["from"] == 180.0
        # A southerly blows northward, and with north up that is straight up the screen:
        # screen angles are measured with y growing downward, so up is -90°.
        assert wrapped(wind["screen"]) == pytest.approx(-90, abs=0.5)

    def test_north_is_up_until_the_view_turns(self):
        answer = _probe(_scene(sun=SUN, wind=WIND, cursor=CURSOR), _ARROWS)
        assert wrapped(answer["atNorthUp"]["north"]) == pytest.approx(-90, abs=0.5)
        # A yaw of +90° turns the scene counter-clockwise, so north swings to the right.
        assert abs(wrapped(answer["turned"]["north"])) == pytest.approx(180, abs=0.5)

    def test_both_arrows_turn_with_the_view_by_the_same_amount(self):
        """They are bearings drawn into the scene's frame; if they did not turn with it
        they would agree with the terrain at one heading and lie at every other."""
        answer = _probe(_scene(sun=SUN, wind=WIND, cursor=CURSOR), _ARROWS)
        for arrow in ("sun", "wind"):
            before = answer["atNorthUp"][arrow]["screen"]
            after = answer["turned"][arrow]["screen"]
            assert wrapped(after - before) == pytest.approx(-90, abs=0.5)

    def test_a_panel_with_neither_draws_no_rose(self):
        """An uploaded track may have no date and no wind estimate at all."""
        answer = _probe(_scene(), _NO_SUN)
        assert answer["sun"] is None
        assert answer["wind"] is None


@needs_chrome
def test_the_light_moves_on_the_canvas_renderer_too():
    """The 2D path bakes the hillshade into the draped texture rather than into vertex
    colours, so it re-lights by a completely different route and has to be checked."""
    answer = _probe(_scene(sun=SUN, wind=WIND, cursor=CURSOR), _HOVER, gl=False)
    assert answer["moved"] is True
    # And holds the last light on leaving, by that same different route.
    assert answer["afterLeaving"] == CURSOR["min"][-1]
    assert answer["restored"] is False


@pytest.mark.skipif(not DAY["az"], reason="needs node")
def test_the_payload_carries_a_day_the_page_can_interpolate():
    """The view interpolates a table rather than running the solar algorithm per frame:
    144 pairs of numbers, small enough to carry with every flight."""
    assert set(SUN["track"]) == {"step", "az", "el"}
    assert len(SUN["track"]["az"]) == 24 * 60 // SUN["track"]["step"]
    assert len(json.dumps(SUN, separators=(",", ":"))) < 2500


_ROSE_CLICK = """
var h = window.__handle, canvas = document.querySelector('canvas.view3d');
function click(x, y) {
  ['pointerdown', 'pointerup'].forEach(function (type) {
    canvas.dispatchEvent(new PointerEvent(type, { pointerId: 4, clientX: x, clientY: y,
      bubbles: true, pointerType: 'mouse', isPrimary: true, button: 0,
      buttons: type === 'pointerup' ? 0 : 1 }));
  });
}
var box = canvas.getBoundingClientRect(), W = canvas.width;
var scale = Math.max(0.75, Math.min(1.6, W / 1280)), radius = 30 * scale;
var rx = box.left + (W - (16 * scale + radius)) / W * box.width;
var ry = box.top + (14 * scale + radius) / canvas.height * box.height;
h.view.yaw = 1.2; h.redraw();
click(box.left + box.width / 2, box.top + box.height / 2);   // not on the rose
var elsewhere = h.view.yaw;
click(rx, ry);
return { elsewhere: elsewhere, yaw: h.view.yaw, north: h.rose().north,
         over: h.overRose(rx, ry) };
"""


@needs_chrome
def test_a_click_on_the_rose_turns_the_view_north():
    """As a compass on any map: a click on the rose puts north at the top, and a click
    anywhere else on the map does not."""
    answer = _probe(_scene(sun=SUN, wind=WIND, cursor=CURSOR), _ROSE_CLICK)
    assert answer["over"] is True
    assert answer["elsewhere"] == pytest.approx(1.2)
    assert answer["yaw"] == pytest.approx(0.0, abs=1e-9)
    assert wrapped(answer["north"]) == pytest.approx(-90, abs=0.5)

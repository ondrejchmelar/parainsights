"""The sun in the 3D view: the slider, and the light actually moving.

The Python side of this is `sun.py` and is tested against a second algorithm in
`test_sun.py`. What that cannot see is whether the terrain is *lit* from where the table
says the sun was — the shading is computed in the page, baked into vertex colours by the
WebGL backend and into the draped texture by the canvas one. So this drives a browser,
moves the slider, and reads back both the label and the pixels.
"""

import datetime as dt
import json

import pytest

from tests.test_view3d_gl import _probe, _scene, needs_chrome
from tracklog_viewer import sun as sun_module

# A real day over the fixture's own terrain, from the real generator: a table typed by
# hand here would be a second implementation to keep in step.
DAY = sun_module.day_track(dt.date(2024, 6, 20), 49.12, 14.12)
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


# Reads the label and the drawn pixels at three times of day. The pixels are taken from
# the GL canvas through a 32 px downscale: the question is whether the shading moved at
# all, and a thumbnail answers it without depending on a single pixel's value.
_SUN = """
var panel = document.querySelector('.view3d-panel');
var h = window.__handle;
var slider = panel.querySelector('.view3d-sun-slider');
var read = panel.querySelector('.view3d-sun-read');
var out = { shown: !panel.querySelector('.view3d-sun').hidden };
if (!slider) return { error: 'no slider in the panel' };

function frame() {
  h.redraw();
  var source = panel.querySelector('canvas.view3d-gl') ||
               panel.querySelector('canvas.view3d');
  var small = document.createElement('canvas');
  small.width = 32; small.height = 32;
  small.getContext('2d').drawImage(source, 0, 0, 32, 32);
  return small.toDataURL();
}

function at(minute) {
  slider.value = minute;
  slider.dispatchEvent(new Event('input', { bubbles: true }));
  return { label: read.textContent, pixels: frame() };
}

out.initialLabel = read.textContent;
out.initialValue = Number(slider.value);
var morning = at(7 * 60);
var noon = at(13 * 60);
var evening = at(19 * 60);
var night = at(1 * 60);
out.morning = morning.label;
out.noon = noon.label;
out.evening = evening.label;
out.night = night.label;
out.movedByMorningEvening = morning.pixels !== evening.pixels;
out.movedByMorningNoon = morning.pixels !== noon.pixels;
out.backend = h.gl() ? h.gl().version : 'canvas2d';
return out;
"""

# `offsetParent` is null for anything inside a hidden ancestor, which is the question
# worth asking: the slider element exists in the markup either way, and what matters is
# whether a reader can see and drag it.
_NO_SUN = """
var panel = document.querySelector('.view3d-panel');
var slider = panel.querySelector('.view3d-sun-slider');
return { hidden: panel.querySelector('.view3d-sun').hidden,
         visible: !!(slider && slider.offsetParent) };
"""


@pytest.fixture(scope="module")
def lit():
    return _probe(_scene(sun=SUN), _SUN)


@needs_chrome
class TestTheSunSlider:
    def test_it_starts_where_the_flight_was(self, lit):
        """Mid-flight, in the pilot's own clock: the light the day was worked in."""
        assert lit["shown"] is True
        assert lit["initialValue"] == 12 * 60 + 120, "12:00 UTC read as 14:00 local"
        assert lit["initialLabel"].startswith("14:00")

    def test_the_label_reads_the_sun_out_of_the_table(self, lit):
        # Midsummer at 49°N: low in the east early, high in the south at midday, low in
        # the west late. The bearings come from the same table `sun.py` generated.
        assert "E" in lit["morning"].split("·")[1]
        assert lit["noon"].split("·")[1].strip().endswith(("S", "SSW", "SSE", "SW"))
        assert "W" in lit["evening"].split("·")[1]
        assert lit["night"].endswith("sun down")

    def test_moving_it_moves_the_light(self, lit):
        """The point of the whole thing: which slopes are lit has to change."""
        assert lit["movedByMorningEvening"] is True
        assert lit["movedByMorningNoon"] is True

    def test_a_panel_with_no_sun_does_not_show_the_control(self):
        """An uploaded track may have no date at all, and a dead slider is worse than
        no slider."""
        answer = _probe(_scene(), _NO_SUN)
        assert answer["hidden"] is True
        assert answer["visible"] is False


@needs_chrome
def test_the_light_moves_on_the_canvas_renderer_too():
    """The 2D path bakes the hillshade into the draped texture rather than into vertex
    colours, so it re-lights by a completely different route and has to be checked."""
    answer = _probe(_scene(sun=SUN), _SUN, gl=False)
    assert answer["backend"] == "canvas2d"
    assert answer["movedByMorningEvening"] is True


def test_the_payload_carries_a_day_the_page_can_interpolate():
    """No solar algorithm in JavaScript: a table cannot drift out of step with `sun.py`
    the way `quicklook.py`'s duplicated thresholds can."""
    assert set(SUN["track"]) == {"step", "az", "el"}
    assert len(SUN["track"]["az"]) == 24 * 60 // SUN["track"]["step"]
    assert len(json.dumps(SUN, separators=(",", ":"))) < 2500

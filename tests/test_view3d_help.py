"""The key-help overlay, measured in a real browser at a phone-sized viewport.

Everything drawn over the 3D canvas is an absolutely positioned sibling, and for as long
as none of them declared a `z-index` their stacking was the order they happened to appear
in the markup. The control bar is last, so it painted *over* the list explaining it: on a
390 px screen the SATELLITE / MAP / RELIEF row sat squarely across the `s m r` line that
names those very keys, and the panel's `overflow: hidden` cut the first section off the
top because the list was taller than the canvas.

Neither of those is visible in the source — one is paint order and the other is a box
measurement — so these are browser probes rather than string assertions. The viewport is
390 x 844, the same phone the rest of the UX work was measured on.
"""

from tests.test_view3d_gl import _probe, _scene, needs_chrome

PHONE = (390, 844)

# Open the list, then report where it and the control bar actually landed. `elementFromPoint`
# is the question being asked — not "what does the stylesheet say" but "which element would
# a finger hit here", which is the same thing the reader experiences.
_HELP = """
var root = document.querySelector('.view3d-panel');
var canvas = root.querySelector('canvas.view3d');
var keys = root.querySelector('.view3d-keys');
var controls = root.querySelector('.view3d-controls');

root.querySelector('[data-view3d-act="help"]').click();

var box = keys.getBoundingClientRect();
var frame = canvas.getBoundingClientRect();
var bar = controls.getBoundingClientRect();

// A point inside both boxes, if they overlap at all: the middle of the control bar.
var x = Math.max(bar.left, box.left) + 1;
var y = bar.top + bar.height / 2;
var overlaps = x < Math.min(bar.right, box.right) && y > box.top && y < box.bottom;
var hit = document.elementFromPoint(x, y);

return {
  hidden: keys.hidden,
  overlaps: overlaps,
  onTop: !!(hit && keys.contains(hit)),
  hitClass: hit ? hit.className || hit.tagName : null,
  // Positive numbers mean the list spills past the edge that clips it.
  above: frame.top - box.top,
  below: box.bottom - frame.bottom,
  leftOf: frame.left - box.left,
  rightOf: box.right - frame.right,
  scrolls: keys.scrollHeight > keys.clientHeight + 1,
  // Line boxes per term, counted with a Range rather than by the element's height: a
  // grid row is as tall as its tallest cell, so a `dt` whose `dd` wrapped is tall
  // without having wrapped itself.
  wrappedTerms: Array.prototype.filter.call(keys.querySelectorAll('dt'), function (dt) {
    var range = document.createRange();
    range.selectNodeContents(dt);
    return range.getClientRects().length > 1;
  }).map(function (dt) { return dt.textContent; })
};
"""


@needs_chrome
def test_the_key_list_is_not_painted_over_by_the_controls_it_explains():
    """The bar and the list share the bottom of a phone-sized canvas; the list wins.

    Without a declared stacking order the hit test at the bar's centre returned a
    control button, which is precisely what the screenshot showed — `s m r ->
    satellite, map, relief` hidden behind the buttons doing that job.
    """
    seen = _probe(_scene(basemap=False), _HELP, window=PHONE)

    assert seen["hidden"] is False, "the ? button did not open the list"
    assert seen["overlaps"], (
        "the list and the control bar no longer overlap on a phone — this test is "
        "measuring nothing; re-point it at whatever they collide with now")
    assert seen["onTop"], (
        f"the control bar is still painted over the key list (hit {seen['hitClass']})")


@needs_chrome
def test_the_key_list_stays_inside_the_canvas_that_clips_it():
    """`.view3d-panel` hides its overflow, so anything past an edge is gone for good."""
    seen = _probe(_scene(basemap=False), _HELP, window=PHONE)

    for edge in ("above", "below", "leftOf", "rightOf"):
        assert seen[edge] <= 0.5, (
            f"the key list spills {seen[edge]:.0f} px {edge} the canvas, where the "
            "panel's overflow rule clips it away")


@needs_chrome
def test_a_key_combination_stays_on_one_line():
    """`shift + <- ->` wrapping reads as two bindings, the second of them blank."""
    seen = _probe(_scene(basemap=False), _HELP, window=PHONE)
    assert seen["wrappedTerms"] == [], f"these key rows wrapped: {seen['wrappedTerms']}"


_CLOSE = """
var root = document.querySelector('.view3d-panel');
var keys = root.querySelector('.view3d-keys');
root.querySelector('[data-view3d-act="help"]').click();
var opened = !keys.hidden;
// A click on the list itself, which is the only affordance left once it covers the bar.
keys.click();
return { opened: opened, closed: keys.hidden };
"""


@needs_chrome
def test_the_list_closes_when_it_is_clicked():
    """It covers the ? button that opened it, so it has to be its own dismiss target."""
    seen = _probe(_scene(basemap=False), _CLOSE, window=PHONE)
    assert seen["opened"], "the ? button did not open the list"
    assert seen["closed"], "clicking the list left it open, with no way back to the view"

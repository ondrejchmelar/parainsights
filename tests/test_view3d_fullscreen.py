"""The maximised 3D view, measured in a real browser.

The controls in full screen were reported broken and nothing in Python can see it: the
bug is a disagreement between three different measurements of "the viewport" — the panel
box, the 2D canvas sized in pixels by JS, and the GL canvas sized by CSS underneath it.
So the probe maximises the panel and asks the page where things actually are, including
`document.elementFromPoint` at each button's own centre, which is the question a click
asks.

The page here is deliberately several screens tall. The report is, the document therefore
has a scrollbar from the first layout, and `--scrollbar` is the term that makes a
full-bleed panel come out the width of the layout viewport rather than overhanging it.
"""

import pytest

from tests.test_view3d_gl import _probe, _scene, needs_chrome

# Tall enough to guarantee a document scrollbar, which is what the real report has.
TALL = '<div style="height: 3000px"></div>'


# Measures the panel before and after the maximise button, from the DOM rather than from
# anything the renderer believes. `elementFromPoint` is the load-bearing part: a control
# can be in the right place and still be unclickable, and it can be off the viewport
# entirely while its own getBoundingClientRect looks reasonable.
_MAXIMISE = """
var panel = document.querySelector('.view3d-panel');
var h = window.__handle;

function box(el) {
  var r = el.getBoundingClientRect();
  return { x: Math.round(r.x), y: Math.round(r.y),
           w: Math.round(r.width), h: Math.round(r.height) };
}

// The viewport, asked for in the one way that means the same thing in both modes.
// documentElement.clientHeight is the document's height in quirks mode, which is the
// whole bug, so nothing here may be measured against it.
function viewport() {
  var v = window.visualViewport;
  return { w: Math.round(v ? v.width : window.innerWidth),
           h: Math.round(v ? v.height : window.innerHeight) };
}

function snap() {
  var c2 = panel.querySelector('canvas.view3d');
  var gl = panel.querySelector('canvas.view3d-gl');
  var doc = document.documentElement;
  var view = viewport();
  var buttons = [].slice.call(panel.querySelectorAll('.view3d-controls button'))
    .map(function (button) {
      var r = button.getBoundingClientRect();
      var cx = Math.round(r.left + r.width / 2);
      var cy = Math.round(r.top + r.height / 2);
      var hit = document.elementFromPoint(cx, cy);
      return {
        act: button.getAttribute('data-view3d-act'),
        box: box(button),
        // A control the media query has removed is not a control that is badly
        // placed. Headless Chrome reports `(hover: none)`, which is the touch case,
        // and there the zoom pair is deliberately gone — pinch, drag and twist are
        // all native on a touch screen and the panel supports all three.
        shown: r.width > 0 && r.height > 0,
        inViewport: r.left >= 0 && r.top >= 0 &&
                    r.right <= view.w && r.bottom <= view.h,
        hit: hit ? (hit.tagName + '.' + (hit.className || '')) : null,
        clickable: !!(hit && (hit === button || button.contains(hit)))
      };
    });
  return {
    panel: box(panel),
    panelBoxes: { w: panel.clientWidth, h: panel.clientHeight },
    canvas: box(c2),
    canvasStore: { w: c2.width, h: c2.height },
    gl: gl ? box(gl) : null,
    glStore: gl ? { w: gl.width, h: gl.height } : null,
    controls: box(panel.querySelector('.view3d-controls')),
    buttons: buttons,
    viewport: view,
    compatMode: document.compatMode,
    docClientHeight: doc.clientHeight,
    scrollbar: getComputedStyle(doc).getPropertyValue('--scrollbar').trim(),
    metrics: h.metrics ? h.metrics() : null
  };
}

var out = { maximised: false };
out.before = snap();
panel.querySelector('[data-view3d-act="fullscreen"]').click();
return new Promise(function (resolve) {
  // Past the whole ladder of redraws in toggleMaximise (the last is at 500 ms).
  setTimeout(function () {
    out.maximised = panel.classList.contains('is-maximised');
    out.after = snap();
    resolve(out);
  }, 900);
});
"""


# Standards mode is what the report renders in. Quirks mode is what it rendered in until
# this bug was traced: with no doctype, `document.documentElement.clientHeight` is the
# height of the whole document, and the maximised canvas was sized from it — 4 316 px of
# canvas inside an 813 px panel on a real report. The sizing must not depend on which
# mode the panel finds itself in, because the panel is embeddable and does not own the
# document.
@pytest.fixture(scope="module", params=["standards", "quirks"])
def maximised(request):
    return _probe(_scene(), _MAXIMISE, page_extra=TALL,
                  doctype=request.param == "standards")


# Real full screen cannot be entered from a script: `requestFullscreen` needs a user
# activation, and a synthetic click is not one — which is why headless Chrome exercises
# the fallback for free, and why the granted path has to be stubbed to be seen at all.
# The stub stands in for the browser: it records the request, reports the panel as the
# fullscreen element, and fires the event the real API would.
_API = """
var panel = document.querySelector('.view3d-panel');
var button = panel.querySelector('[data-view3d-act="fullscreen"]');
var element = null;
var requested = 0;
var exited = 0;
Object.defineProperty(document, 'fullscreenElement',
  { configurable: true, get: function () { return element; } });
panel.requestFullscreen = function () {
  requested++;
  element = panel;
  document.dispatchEvent(new Event('fullscreenchange'));
  return Promise.resolve();
};
document.exitFullscreen = function () {
  exited++;
  element = null;
  document.dispatchEvent(new Event('fullscreenchange'));
  return Promise.resolve();
};

var out = {};
button.click();
return new Promise(function (resolve) {
  setTimeout(function () {
    var canvas = panel.querySelector('canvas.view3d');
    out.requested = requested;
    out.fellBack = panel.classList.contains('is-maximised');
    out.sizedInPixels = /px$/.test(canvas.style.height) && canvas.style.height !== '';
    button.click();                       // and out again
    setTimeout(function () {
      out.exited = exited;
      out.stillFull = document.fullscreenElement === panel;
      out.sizeCleared = canvas.style.height === '';
      out.leftBehind = panel.classList.contains('is-maximised');
      resolve(out);
    }, 700);
  }, 700);
});
"""

# The published-artifact case: an iframe without the permission. The API rejects and the
# button must still do something, which is the whole reason the in-page path exists.
_REFUSED = """
var panel = document.querySelector('.view3d-panel');
panel.requestFullscreen = function () { return Promise.reject(new Error('denied')); };
panel.querySelector('[data-view3d-act="fullscreen"]').click();
return new Promise(function (resolve) {
  setTimeout(function () {
    resolve({ fellBack: panel.classList.contains('is-maximised'),
              height: panel.querySelector('canvas.view3d').style.height });
  }, 700);
});
"""


# A drag, measured against a fixed world point, in whichever state the parameter asks
# for. Panning moves the ground by exactly the pointer delta, so this is the one gesture
# with an answer that can be stated in advance — and it is the gesture that goes wrong
# when the canvas box and its backing store disagree, which is what full screen used to
# do. `pointermove` goes to the canvas, not the window: the handler owns the element.
_DRAG = """
var h = window.__handle;
var canvas = document.querySelector('canvas.view3d');
var panel = canvas.closest('.view3d-panel');
function send(type, x, y, buttons) {
  canvas.dispatchEvent(new PointerEvent(type, {
    pointerId: 1, clientX: x, clientY: y, button: 0,
    buttons: buttons === undefined ? 1 : buttons,
    bubbles: true, cancelable: true, pointerType: 'mouse', isPrimary: true
  }));
}
function drag(dx, dy) {
  h.view.panX = 0; h.view.panY = 0; h.redraw();
  var before = h.worldProject(0, 0, 0);
  var box = canvas.getBoundingClientRect();
  var x = box.left + box.width / 2, y = box.top + box.height / 2;
  send('pointerdown', x, y);
  for (var i = 1; i <= 10; i++) send('pointermove', x + dx * i / 10, y + dy * i / 10);
  send('pointerup', x + dx, y + dy, 0);
  h.redraw();
  var after = h.worldProject(0, 0, 0);
  return { dx: after[0] - before[0], dy: after[1] - before[1] };
}

if (MAXIMISE) panel.querySelector('[data-view3d-act="fullscreen"]').click();
return new Promise(function (resolve) {
  setTimeout(function () {
    resolve({ maximised: panel.classList.contains('is-maximised'),
              moved: drag(80, 40),
              metrics: h.metrics() });
  }, MAXIMISE ? 900 : 0);
});
"""


@needs_chrome
class TestDraggingStillWorks:
    """The gesture, not the button. Pointer positions are client coordinates and the
    projection is in backing-store pixels; full screen changes both at once."""

    @pytest.mark.parametrize("maximise", [False, True], ids=["inline", "maximised"])
    def test_a_drag_moves_the_ground_by_the_pointer_delta(self, maximise):
        answer = _probe(_scene(), ("var MAXIMISE = %s;" % ("true" if maximise else "false"))
                        + _DRAG, page_extra=TALL)
        assert answer["maximised"] is maximise
        assert answer["moved"]["dx"] == pytest.approx(80, abs=1.5)
        assert answer["moved"]["dy"] == pytest.approx(40, abs=1.5)
        assert answer["metrics"]["W"] == round(answer["metrics"]["boxW"]
                                               * answer["metrics"]["ratio"])


@needs_chrome
class TestTheFullscreenApiIsPreferred:
    def test_it_asks_the_browser_rather_than_faking_it(self):
        answer = _probe(_scene(), _API, page_extra=TALL)
        assert answer["requested"] == 1
        assert answer["fellBack"] is False, "the API was granted; nothing should fake it"
        assert answer["sizedInPixels"] is True, "the canvas still has to fill the screen"

    def test_pressing_it_again_leaves_full_screen(self):
        answer = _probe(_scene(), _API, page_extra=TALL)
        assert answer["exited"] == 1
        assert answer["stillFull"] is False
        assert answer["sizeCleared"] is True
        assert answer["leftBehind"] is False, "the in-page class must not be left on"

    def test_a_refused_request_falls_back_to_the_in_page_maximise(self):
        """An iframe without the permission — which is what a published artifact is."""
        answer = _probe(_scene(), _REFUSED, page_extra=TALL)
        assert answer["fellBack"] is True
        assert answer["height"].endswith("px")


@needs_chrome
class TestMaximised:
    def test_the_button_maximises(self, maximised):
        assert maximised["maximised"] is True
        after = maximised["after"]
        assert after["panel"]["w"] == after["viewport"]["w"]
        assert after["panel"]["h"] == after["viewport"]["h"]

    def test_the_canvas_is_not_sized_from_the_document(self, maximised):
        """The bug itself, stated as the measurement that gave it away.

        In quirks mode `documentElement.clientHeight` is the height of the whole page —
        4 316 px on a real report against an 813 px viewport — and the maximised canvas
        was sized from it. The fixture renders both modes; in the quirks one this is the
        assertion that fails if the sizing ever goes back to a global.
        """
        after = maximised["after"]
        assert after["canvas"]["h"] <= after["viewport"]["h"]
        assert after["canvasStore"]["h"] <= after["viewport"]["h"] * 2

    def test_both_canvases_are_the_same_box(self, maximised):
        """The track is drawn on one canvas and the terrain on the other.

        They are sized by different mechanisms — the 2D canvas in pixels by JS, the GL
        canvas by `inset: 0` — and if those disagree the track sits offset from the
        terrain it belongs to.
        """
        after = maximised["after"]
        assert after["gl"] is not None, "no WebGL in this browser: nothing to compare"
        assert after["canvas"] == after["gl"]

    def test_the_canvas_fills_the_panel(self, maximised):
        """The panel's padding box, which is also what `inset: 0` gives the GL canvas."""
        after = maximised["after"]
        assert after["canvas"]["w"] == after["panelBoxes"]["w"]
        assert after["canvas"]["h"] == after["panelBoxes"]["h"]

    def test_the_controls_are_on_screen_and_clickable(self, maximised):
        """The reported bug. A control row anchored to the right edge of a panel that
        overhangs the viewport is off the screen, and one under another element is
        unclickable while looking perfectly placed."""
        for state in ("before", "after"):
            shown = [b for b in maximised[state]["buttons"] if b["shown"]]
            assert shown, state
            for button in shown:
                assert button["inViewport"], (state, button)
                assert button["clickable"], (state, button)

    def test_touch_gets_the_bigger_targets_and_loses_the_nudge_pair(self, maximised):
        """The mobile rule used to make every target *smaller* — 5px 7px padding and
        10.5px type on the one device where a finger replaces a mouse. Headless Chrome
        reports `(hover: none)`, so this is the touch branch being measured: zoom is
        gone, and everything still on screen clears 44 px."""
        shown = [b for b in maximised["before"]["buttons"] if b["shown"]]
        acts = {b["act"] for b in shown}
        assert "zoom-in" not in acts and "zoom-out" not in acts
        for button in shown:
            assert button["box"]["h"] >= 44, button

    def test_the_backing_store_follows_the_box(self, maximised):
        """A stale backing store renders blurred and, worse, projects to the wrong
        place — every gesture anchors through that projection."""
        after = maximised["after"]
        ratio = min(after["metrics"]["ratio"], 2) if after["metrics"] else 1
        assert after["canvasStore"]["w"] == round(after["canvas"]["w"] * ratio)
        assert after["canvasStore"]["h"] == round(after["canvas"]["h"] * ratio)
        assert after["glStore"] == after["canvasStore"]

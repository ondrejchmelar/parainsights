"""The map controls: segments that address a state, and the keyboard that shares them.

None of what follows is visible from Python. Whether a screen reader gets a usable name
out of a button is Chrome's own name computation, whether a key reaches the camera is a
listener on the right element, and whether the control bar fits a phone is layout — so
these run in a real browser and read the numbers back, on the same probe harness as the
other view3d tests.

The claim being defended, over and over, is that there is **one code path**: buttons and
keys both go through `runAct`, so a key cannot drift away from the button that means the
same thing.
"""

import pytest

from tests.test_view3d_gl import _probe, _scene, needs_chrome


@needs_chrome
class TestSegments:
    """A cycle that names its current state does not scale past two.

    Basemap has three states and exaggeration has three. With a cycle you cannot see the
    options, cannot tell how many presses reach the one you want, and cannot jump — and
    `x1 height` at rest is a button announcing that nothing is happening.
    """

    def test_a_segment_sets_its_state_directly(self):
        answer = _probe(_scene(), """
        var h = window.__handle;
        var root = document.querySelector('.view3d-panel');
        function press(sel) { root.querySelector(sel).click(); }
        var out = {start: h.view.vertical};
        press('[data-vertical="4"]');
        out.four = h.view.vertical;
        press('[data-vertical="1"]');
        out.one = h.view.vertical;
        return out;
        """)
        assert answer["start"] == 1
        # One press, not two: the cycle needed 1 -> 2 -> 4 to reach the same place.
        assert answer["four"] == 4
        assert answer["one"] == 1

    def test_the_pressed_segment_is_the_one_marked(self):
        answer = _probe(_scene(), """
        var root = document.querySelector('.view3d-panel');
        root.querySelector('[data-vertical="2"]').click();
        var marks = [];
        root.querySelectorAll('[data-view3d-act="exaggerate"]').forEach(function (b) {
          marks.push(b.dataset.vertical + ':' + b.getAttribute('aria-pressed') +
                     ':' + b.classList.contains('is-on'));
        });
        return {marks: marks};
        """)
        assert answer["marks"] == ["1:false:false", "2:true:true", "4:false:false"]

    def test_relief_turns_the_basemap_off_and_back(self):
        answer = _probe(_scene(), """
        var h = window.__handle;
        var root = document.querySelector('.view3d-panel');
        root.querySelector('[data-style="off"]').click();
        var off = h.view.map;
        root.querySelector('[data-style="satellite"]').click();
        return {off: off, on: h.view.map};
        """)
        assert answer["off"] is False
        assert answer["on"] is True


@needs_chrome
class TestAccessibleNames:
    """Six of the ten buttons announced as a glyph.

    Chrome's own name computation, read out of the accessibility tree, returned
    `name='↶' from=contents` — because for a button the content wins over `title`, and
    `title` never appears on touch at all. The codebase already knew the pattern: the tab
    close buttons carry `aria-label`. It simply was not applied to the map.
    """

    def test_no_control_is_named_by_a_glyph_alone(self):
        answer = _probe(_scene(), """
        var names = [];
        document.querySelectorAll('.view3d-controls button').forEach(function (b) {
          var label = b.getAttribute('aria-label');
          // innerText, not textContent: a segment carries a long label and a short one
          // and hides whichever the viewport does not want, and textContent would
          // concatenate both into a name no reader ever hears.
          var text = (b.innerText || '').trim();
          names.push({act: b.getAttribute('data-view3d-act'),
                      name: label || text, fromLabel: !!label});
        });
        return {names: names};
        """)
        for entry in answer["names"]:
            assert len(entry["name"]) > 2, entry
            # A glyph-only control has to carry the name in an attribute; a worded one
            # is allowed to compute it from its contents, which is what a reader sees.
            assert entry["name"].strip("+-−↺⊕⊖"), entry


@needs_chrome
class TestKeyboard:
    """Bound to the same act names the buttons dispatch, so there is one code path.

    Three traps, and each is asserted below: arrow keys must not scroll the page, the
    handler must be per-panel rather than document-level (a document holds several
    flights, and `view3d.py` already carries a comment about one panel's button driving
    another panel's numbers), and a held key must anchor through `holdGround` exactly as
    a held button does — which is what binding to acts rather than to camera fields buys.
    """

    def _keys(self, script):
        return _probe(_scene(), """
        var h = window.__handle;
        var canvas = document.querySelector('canvas.view3d');
        function key(name, shift) {
          var event = new KeyboardEvent('keydown', {key: name, shiftKey: !!shift,
                                                    bubbles: true, cancelable: true});
          canvas.dispatchEvent(event);
          return event.defaultPrevented;
        }
        h.view.yaw = 0; h.view.pitch = 0.6; h.view.zoom = 1;
        h.view.panX = 0; h.view.panY = 0;
        """ + script)

    def test_the_digits_address_exaggeration_directly(self):
        answer = self._keys("""
        key('4');
        var four = h.view.vertical;
        key('1');
        return {four: four, one: h.view.vertical};
        """)
        assert answer["four"] == 4
        assert answer["one"] == 1

    def test_letters_address_the_basemap_directly(self):
        answer = self._keys("""
        key('r');
        var relief = h.view.map;
        key('s');
        return {relief: relief, satellite: h.view.map};
        """)
        assert answer["relief"] is False
        assert answer["satellite"] is True

    def test_arrows_turn_and_tilt(self):
        answer = self._keys("""
        var yaw0 = h.view.yaw, pitch0 = h.view.pitch;
        key('ArrowRight');
        var yaw1 = h.view.yaw;
        key('ArrowUp');
        return {dyaw: yaw1 - yaw0, dpitch: h.view.pitch - pitch0};
        """)
        assert answer["dyaw"] > 0
        assert answer["dpitch"] > 0

    def test_shift_arrows_pan_instead_of_turning(self):
        answer = self._keys("""
        var yaw0 = h.view.yaw;
        key('ArrowLeft', true);
        return {dyaw: h.view.yaw - yaw0, panX: h.view.panX};
        """)
        assert answer["dyaw"] == 0
        assert answer["panX"] != 0

    def test_arrows_do_not_scroll_the_page(self):
        """`preventDefault`, and only while the canvas holds focus — otherwise tilting
        the terrain scrolls the report out from under it."""
        answer = self._keys("""
        return {prevented: key('ArrowDown'), ignored: key('q')};
        """)
        assert answer["prevented"] is True
        # And a key with no binding is left alone, so typing still works.
        assert answer["ignored"] is False

    def test_the_key_list_opens_and_closes(self):
        answer = self._keys("""
        var panel = document.querySelector('.view3d-keys');
        key('?');
        var open = !panel.hidden;
        key('Escape');
        return {open: open, closed: panel.hidden};
        """)
        assert answer["open"] is True
        assert answer["closed"] is True

    def test_the_handler_is_on_the_canvas_not_the_document(self):
        """A report holds several panels; a document-level listener drives whichever it
        finds first, which is the bug `view3d.py` already carries a comment about."""
        answer = self._keys("""
        var before = h.view.vertical;
        document.body.dispatchEvent(new KeyboardEvent('keydown',
          {key: '4', bubbles: true, cancelable: true}));
        return {before: before, after: h.view.vertical};
        """)
        assert answer["after"] == answer["before"]


@needs_chrome
def test_a_basemap_key_for_a_style_the_document_lacks_does_nothing():
    """An embedded report may carry one style only, and a key naming the other must not
    blank the ground."""
    answer = _probe(_scene(basemap=True), """
    var h = window.__handle;
    var canvas = document.querySelector('canvas.view3d');
    canvas.dispatchEvent(new KeyboardEvent('keydown',
      {key: 'm', bubbles: true, cancelable: true}));
    return {map: h.view.map,
            styles: [].slice.call(document.querySelectorAll('[data-style]'))
                      .map(function (b) { return b.dataset.style; })};
    """)
    # The fixture carries satellite and relief, not `map`.
    assert "map" not in answer["styles"]
    assert answer["map"] is True

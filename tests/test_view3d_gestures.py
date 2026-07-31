"""Rotation gestures, driven as real pointer events in a real browser.

The direction a gesture turns the scene cannot be read off the source: it is the product
of three sign conventions that each look right alone — `atan2` measured in client
coordinates where y grows *downward*, a yaw that rotates the world counter-clockwise in
a right-handed frame, and a projection that negates northing so north is up. Two of
those cancel and one does not, and the only way to know which is to twist and look.

So these dispatch PointerEvents at the canvas and measure where the ground ended up.
The probe harness is shared with `test_view3d_gl`; that is deliberate rather than
duplicated, in the same way `test_terrain` borrows its flight builders from
`test_analysis`.
"""

import pytest

from tests.test_view3d_gl import _probe, _scene, needs_chrome

# A vector between two fixed world points, in a frame the reader would recognise: right
# is +x and up is -canvasY, so a rising bearing is counter-clockwise as a human sees it.
# Measuring a vector rather than a point makes it independent of the pan and the fit's
# anchor, both of which the gesture also moves.
_BEARING = """
function bearing() {
  var a = h.worldProject(0, 0, 0), b = h.worldProject(10000, 0, 0);
  return Math.atan2(-(b[1] - a[1]), b[0] - a[0]);
}
function settle(d) {
  while (d > Math.PI) d -= 2 * Math.PI;
  while (d < -Math.PI) d += 2 * Math.PI;
  return d;
}
function send(type, id, x, y) {
  canvas.dispatchEvent(new PointerEvent(type, {
    pointerId: id, clientX: x, clientY: y, bubbles: true, cancelable: true,
    pointerType: 'touch', isPrimary: id === 1
  }));
}
"""

_TWIST = """
var h = window.__handle;
var canvas = document.querySelector('canvas.view3d');
%s
h.view.yaw = 0; h.view.pitch = 0.6; h.view.zoom = 1;
h.view.panX = 0; h.view.panY = 0;
h.redraw();

var box = canvas.getBoundingClientRect();
var cx = box.left + box.width / 2, cy = box.top + box.height / 2, R = 120;
// Two fingers opposed through the centre. Client y grows downward, so advancing the
// angle walks each finger *clockwise* around the centre as the reader sees it.
function place(angle, id) {
  var sign = id === 1 ? -1 : 1;
  return [cx + sign * R * Math.cos(angle), cy + sign * R * Math.sin(angle)];
}

var before = bearing();
var start1 = place(0, 1), start2 = place(0, 2);
send('pointerdown', 1, start1[0], start1[1]);
send('pointerdown', 2, start2[0], start2[1]);
var steps = 14, sweep = Math.PI / 4;      // 45 degrees, well past TWIST_DEADZONE
for (var i = 1; i <= steps; i++) {
  var at = sweep * i / steps;
  var a = place(at, 1), b = place(at, 2);
  send('pointermove', 1, a[0], a[1]);
  send('pointermove', 2, b[0], b[1]);
}
send('pointerup', 1, 0, 0);
send('pointerup', 2, 0, 0);
h.redraw();

return { yaw: h.view.yaw, scene: settle(bearing() - before) };
""" % _BEARING


@needs_chrome
def test_a_clockwise_twist_turns_the_ground_clockwise():
    """Direct manipulation: the ground goes where the fingers go.

    This was inverted, and inverted in a way that reads as correct in the source —
    `view.yaw += angleDelta(...)`. The finger angle comes from `atan2` in client
    coordinates, where y grows downward, so a twist the reader sees as clockwise is a
    *positive* delta; a positive `view.yaw` turns the scene counter-clockwise on screen.
    Adding them pinned the ground point under the fingers and then span it the other
    way, which is the one thing this gesture must not do — the pinch beside it goes to
    real trouble to keep the same point under the same fingers.
    """
    twisted = _probe(_scene(basemap=False), _TWIST)
    assert twisted["scene"] < -0.02, (
        "a clockwise twist turned the ground counter-clockwise: the scene moved "
        f"{twisted['scene']:+.3f} rad")
    # Roughly one-for-one, less the deadzone that has to be broken before it engages.
    assert -0.80 < twisted["yaw"] < -0.55, (
        f"twist tracked the fingers in direction but not in size: yaw {twisted['yaw']:+.3f}")


_ORBIT = """
var h = window.__handle;
var canvas = document.querySelector('canvas.view3d');
%s
h.view.yaw = 0; h.view.pitch = 0.6; h.view.zoom = 1;
h.view.panX = 0; h.view.panY = 0;
h.redraw();

var box = canvas.getBoundingClientRect();
var x = box.left + box.width / 2, y = box.top + box.height / 2;
var before = bearing();
// ctrl-drag is the orbit modifier on a mouse.
canvas.dispatchEvent(new PointerEvent('pointerdown', {
  pointerId: 1, clientX: x, clientY: y, bubbles: true, cancelable: true,
  ctrlKey: true, isPrimary: true
}));
for (var i = 1; i <= 10; i++) {
  canvas.dispatchEvent(new PointerEvent('pointermove', {
    pointerId: 1, clientX: x + i * 12, clientY: y, bubbles: true, cancelable: true,
    ctrlKey: true, isPrimary: true
  }));
}
send('pointerup', 1, 0, 0);
h.redraw();
return { yaw: h.view.yaw, scene: settle(bearing() - before) };
""" % _BEARING


@needs_chrome
def test_dragging_the_camera_right_swings_the_view_the_other_way():
    """The orbit drag is camera-centric on purpose, and stays that way.

    Google Earth's model, which is what pilots already know: dragging right walks the
    *camera* to the right, so the ground appears to swing left. That is the opposite
    sense to the twist above and it is not a bug — a twist is the reader turning the
    map, a drag is the reader walking around it. Pinned here so that fixing one is
    never quietly applied to the other.
    """
    orbited = _probe(_scene(basemap=False), _ORBIT)
    assert orbited["yaw"] > 0.05, "the orbit drag did not rotate at all"
    assert orbited["scene"] > 0.02, (
        "the orbit drag changed sense; it is deliberately opposite to the twist")


# Rotating about a *fixed* ground point: the one the drag grabbed, held where it was
# grabbed. Measured as the screen drift of that point over a 90 px drag — an orbit that
# anchors correctly leaves it exactly where it was.
_ORBIT_ANCHOR = """
var h = window.__handle;
var canvas = document.querySelector('canvas.view3d');
var panel = canvas.closest('.view3d-panel');
var dem = JSON.parse(document.querySelector('.view3d-data').textContent).terrain;

function mouse(type, x, y, buttons) {
  canvas.dispatchEvent(new PointerEvent(type, {
    pointerId: 7, clientX: x, clientY: y, bubbles: true, cancelable: true,
    pointerType: 'mouse', isPrimary: true, button: 0,
    buttons: buttons === undefined ? 1 : buttons, ctrlKey: true
  }));
}

function orbit(fx, fy, dx, dy) {
  h.view.yaw = 0; h.view.pitch = 0.6; h.view.zoom = 1;
  h.view.panX = 0; h.view.panY = 0;
  h.redraw();
  var hold = h.groundUnder(fx, fy);
  var before = h.worldProject(hold[0], hold[1], dem.min);
  mouse('pointerdown', fx, fy);
  for (var i = 1; i <= 10; i++) mouse('pointermove', fx + dx * i / 10, fy + dy * i / 10);
  mouse('pointerup', fx + dx, fy + dy, 0);
  h.redraw();
  var after = h.worldProject(hold[0], hold[1], dem.min);
  return { driftX: after[0] - before[0], driftY: after[1] - before[1],
           yaw: h.view.yaw, pitch: h.view.pitch, ratio: h.metrics().ratio };
}

var box = canvas.getBoundingClientRect();
var out = { inline: orbit(box.left + box.width * 0.35, box.top + box.height * 0.4, 90, -40) };
panel.querySelector('[data-view3d-act="fullscreen"]').click();
return new Promise(function (resolve) {
  setTimeout(function () {
    var b2 = canvas.getBoundingClientRect();
    out.maximised = orbit(b2.left + b2.width * 0.35, b2.top + b2.height * 0.4, 90, -40);
    resolve(out);
  }, 900);
});
"""


@needs_chrome
@pytest.mark.parametrize("state", ["inline", "maximised"])
def test_the_orbit_turns_about_the_point_it_grabbed(state):
    """Not about whatever is under the cursor at each event.

    Re-picking the anchor per event looks equivalent and is not: the cursor has travelled
    since the last one, so every event pins a different ground point and the centre of
    rotation creeps across the terrain with the mouse. It measured 29 px of slide on a
    90 px drag, and worst full screen, where there is room to drag a long way.
    """
    answer = _probe(_scene(basemap=False), _ORBIT_ANCHOR)
    drift = answer[state]
    assert abs(drift["driftX"]) < 0.5 and abs(drift["driftY"]) < 0.5, drift


@needs_chrome
def test_rotation_is_the_same_gesture_on_a_retina_screen():
    """The hand moved the same distance, so the view must turn the same amount.

    Yaw came from a delta converted into *backing store* pixels, which ties the gesture
    to the device pixel ratio: the same 90 px drag turned the view 0.900 rad at ratio 2
    against 0.450 at ratio 1. A pan does convert — it moves the scene in the canvas —
    which is why the two units sit side by side in the handler.
    """
    ordinary = _probe(_scene(basemap=False), _ORBIT_ANCHOR)["inline"]
    retina = _probe(_scene(basemap=False), _ORBIT_ANCHOR, device_scale=2)["inline"]
    assert retina["ratio"] == 2 and ordinary["ratio"] == 1, "the fixture did not scale"
    assert retina["yaw"] == pytest.approx(ordinary["yaw"], abs=1e-6)
    assert retina["pitch"] == pytest.approx(ordinary["pitch"], abs=1e-6)


# The keyboard, measured the same way as the pointer. Which modifier carries which action
# cannot be read off the source either — `SHIFT_ACTS` beside `KEY_ACTS` looks right
# whichever way round it is written — and the direction a key turns the ground is the same
# three-convention problem the twist has.
_KEYS = """
var h = window.__handle;
var canvas = document.querySelector('canvas.view3d');
%s
function reset() {
  h.view.yaw = 0; h.view.pitch = 0.6; h.view.zoom = 1;
  h.view.panX = 0; h.view.panY = 0;
  h.redraw();
}
function press(key, shift) {
  reset();
  var before = bearing();
  canvas.dispatchEvent(new KeyboardEvent('keydown', {
    key: key, shiftKey: !!shift, bubbles: true, cancelable: true
  }));
  h.redraw();
  return { yaw: h.view.yaw, pitch: h.view.pitch,
           panX: h.view.panX, panY: h.view.panY,
           scene: settle(bearing() - before) };
}
return {
  left: press('ArrowLeft', false),
  right: press('ArrowRight', false),
  up: press('ArrowUp', false),
  shiftLeft: press('ArrowLeft', true),
  shiftRight: press('ArrowRight', true),
  shiftUp: press('ArrowUp', true)
};
""" % _BEARING


@needs_chrome
def test_bare_arrows_pan_and_shifted_arrows_turn():
    """The keyboard agrees with the pointer about what shift means.

    A plain drag pans and a modified drag rotates, so a plain arrow has to pan and a
    shifted one has to rotate. It was the other way round, which made shift mean
    "rotate instead of pan" on the mouse and "pan instead of rotate" on the keyboard —
    on the same panel, at the same time.
    """
    keys = _probe(_scene(basemap=False), _KEYS)

    for name in ("left", "right", "up"):
        step = keys[name]
        assert step["yaw"] == 0 and step["pitch"] == pytest.approx(0.6), (
            f"a bare {name} arrow moved the camera instead of panning: {step}")
    assert keys["left"]["panX"] != 0 and keys["right"]["panX"] != 0, "arrows did not pan"
    assert keys["left"]["panX"] == -keys["right"]["panX"], "left and right pan differently"
    assert keys["up"]["panY"] != 0, "the up arrow did not pan"

    # A shifted arrow moves the camera. It moves the pan as well, and that is not a pan:
    # a turn is anchored through `holdGround` so the ground under the middle of the view
    # stays under it, exactly as the orbit drag does, and that costs a pan offset.
    assert keys["shiftLeft"]["yaw"] != 0 and keys["shiftRight"]["yaw"] != 0, (
        "shift + left/right did not turn the camera")
    assert keys["shiftLeft"]["yaw"] == -keys["shiftRight"]["yaw"], (
        "shift + left and shift + right turn by different amounts")
    assert keys["shiftUp"]["pitch"] > 0.6, "shift + up did not tilt up"
    assert keys["shiftUp"]["yaw"] == 0, "shift + up turned as well as tilting"


@needs_chrome
def test_shift_left_turns_the_ground_to_the_left():
    """The map turns the way the key points, which is *not* the orbit drag's sense.

    Taking the sign from the drag reads as obviously right and is backwards: a drag is
    direct manipulation of a grabbed point, so pushing left walks the camera and spins the
    world the other way. A key grabs nothing. Reported as "left/right arrows turn the
    other direction", and it is the same class of error the twist gesture carried for its
    whole life.
    """
    keys = _probe(_scene(basemap=False), _KEYS)
    # Counter-clockwise on screen is a rising bearing, which is what "to the left" means
    # for a map that is not being grabbed.
    assert keys["shiftLeft"]["scene"] > 0.02, (
        "shift + left turned the ground clockwise: the scene moved "
        f"{keys['shiftLeft']['scene']:+.3f} rad")
    assert keys["shiftRight"]["scene"] < -0.02, (
        "shift + right turned the ground counter-clockwise: the scene moved "
        f"{keys['shiftRight']['scene']:+.3f} rad")


# Marking a moment that is off the edge of the panel. `revealCursor` answers whether it
# had to move the view, which is the only part of "the reader can now see it" a test can
# hold without looking at pixels.
_REVEAL = """
var h = window.__handle;
h.view.yaw = 0; h.view.pitch = 0.6; h.view.zoom = 1;
h.view.panX = 0; h.view.panY = 0;
h.redraw();

var out = {};
out.visible = h.revealCursor(3);          // already on screen: nothing to do
out.restX = h.view.panX;

h.view.panX = -4000;                      // shove the flight off to the left
h.redraw();
out.offscreen = h.revealCursor(3);
out.afterX = h.view.panX;
out.settled = h.revealCursor(3);          // and it is on screen now
return out;
"""


@needs_chrome
def test_marking_an_offscreen_moment_brings_it_into_view():
    """A click on a chart can name a point the panel is not looking at.

    The marker was drawn correctly and off the edge of the canvas, so the reader asked
    "where was this on the ground" and the map did not move. Panning is enough — this
    projection has no behind-the-camera case — and it is all that happens, because
    turning the view unasked throws away the orientation the reader had just built up.
    """
    from tests.test_view3d_sun import CURSOR

    answer = _probe(_scene(basemap=False, cursor=CURSOR), _REVEAL)
    assert answer["visible"] is False, "a point already in view was panned to anyway"
    assert answer["restX"] == 0, "the resting view was moved for nothing"
    assert answer["offscreen"] is True, "an off-screen point was left off screen"
    assert answer["afterX"] > -4000, "the view did not pan towards the marker"
    assert answer["settled"] is False, "the pan did not actually bring it into view"

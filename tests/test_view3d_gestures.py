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
  // At the height that came back with it. `groundUnder` used to answer on the flat datum
  // plane and now answers on the terrain surface, so projecting at `dem.min` here would
  // be measuring the drift of a point nobody grabbed.
  var holdZ = hold.length > 2 ? hold[2] : dem.min;
  var before = h.worldProject(hold[0], hold[1], holdZ);
  mouse('pointerdown', fx, fy);
  for (var i = 1; i <= 10; i++) mouse('pointermove', fx + dx * i / 10, fy + dy * i / 10);
  mouse('pointerup', fx + dx, fy + dy, 0);
  h.redraw();
  var after = h.worldProject(hold[0], hold[1], holdZ);
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


# A rotation is not a zoom. `refit()` used to re-measure the fitted scale from the
# bounding box of the *rotated, pitched* scene on every frame, so turning the view
# rescaled it — worst at low pitch, where the projected height of the scene is dominated
# by relief rather than by northing and the box a rotation sweeps out changes most.
_TWIST_SCALE = """
var h = window.__handle;
var canvas = document.querySelector('canvas.view3d');
%s

function twistAt(pitch) {
  h.view.yaw = 0; h.view.pitch = pitch; h.view.zoom = 1;
  h.view.panX = 0; h.view.panY = 0;
  h.redraw();
  var before = h.projection().scale;
  var box = canvas.getBoundingClientRect();
  var cx = box.left + box.width / 2, cy = box.top + box.height / 2, R = 120;
  function place(angle, id) {
    var sign = id === 1 ? -1 : 1;
    return [cx + sign * R * Math.cos(angle), cy + sign * R * Math.sin(angle)];
  }
  var a0 = place(0, 1), b0 = place(0, 2);
  send('pointerdown', 1, a0[0], a0[1]);
  send('pointerdown', 2, b0[0], b0[1]);
  for (var i = 1; i <= 14; i++) {
    var at = Math.PI / 4 * i / 14;
    var a = place(at, 1), b = place(at, 2);
    send('pointermove', 1, a[0], a[1]);
    send('pointermove', 2, b[0], b[1]);
  }
  send('pointerup', 1, 0, 0);
  send('pointerup', 2, 0, 0);
  h.redraw();
  return { pitch: pitch, before: before, after: h.projection().scale,
           zoom: h.view.zoom, yaw: h.view.yaw };
}

return { low: twistAt(0.18), mid: twistAt(0.6), high: twistAt(1.45) };
""" % _BEARING


@needs_chrome
@pytest.mark.parametrize("state", ["low", "mid", "high"])
def test_a_twist_does_not_rescale_the_scene(state):
    """Reported as "it rotates weirdly when tilted down", and that is exactly what it is.

    The fitted scale came off the bounding box of the rotated scene, so a 45 degree
    twist at pitch 0.18 took the ground scale from 778 px per 10 km to 345 — the view
    zooming itself out by 2.3x in the middle of a gesture meant only to rotate. It is
    a low-pitch problem because there the projected height of the scene is relief rather
    than northing, so the box a rotation sweeps out changes most; at pitch 1.45 the same
    twist cost only 16%, which is why it read as a tilt bug rather than a rotate bug.
    The scale is now measured when the framing changes — a resize, an exaggeration, a
    reset — and held through every gesture.
    """
    answer = _probe(_scene(basemap=False), _TWIST_SCALE)[state]
    # Floating-point exact is too strong: the pinch's own scale factor is
    # `now.distance / pinch.distance`, which on a pure twist is 1 to a rounding error.
    assert answer["zoom"] == pytest.approx(1, rel=1e-6), (
        "the twist changed view.zoom, which it must not touch")
    assert answer["after"] == pytest.approx(answer["before"], rel=1e-9), (
        f"a twist rescaled the scene by {answer['after'] / answer['before']:.2f}x "
        f"at pitch {answer['pitch']}")


_ZOOM_RANGE = """
var h = window.__handle;
var canvas = document.querySelector('canvas.view3d');
var box = canvas.getBoundingClientRect();
var cx = box.left + box.width / 2, cy = box.top + box.height / 2;
function wheel(dy, times) {
  for (var i = 0; i < times; i++) {
    canvas.dispatchEvent(new WheelEvent('wheel', {
      deltaY: dy, clientX: cx, clientY: cy, bubbles: true, cancelable: true
    }));
  }
  h.redraw();
}
h.view.zoom = 1; h.view.panX = 0; h.view.panY = 0; h.redraw();
wheel(-100, 60);
var closest = h.view.zoom;
wheel(100, 120);
return { closest: closest, farthest: h.view.zoom };
"""


@needs_chrome
def test_the_view_zooms_closer_than_it_used_to():
    """12x stopped about 2 km across the canvas, which is too far out to see which side
    of a spine a climb was worked on. The imagery is soft long before 40x — a stitch is
    about 20 m a pixel — but a soft picture the reader asked for beats a sharp one that
    refuses."""
    answer = _probe(_scene(basemap=False), _ZOOM_RANGE)
    assert answer["closest"] == pytest.approx(40, rel=1e-6)
    assert answer["farthest"] == pytest.approx(0.2, rel=1e-6)


_BUTTON_ZOOM = """
var h = window.__handle;
var panel = document.querySelector('.view3d-panel');
var canvas = panel.querySelector('canvas.view3d');

// A zoom with no pointer behind it — a button, or the `+` key — should be a *pure
// magnification about the fit's anchor*: every point lands on
// anchor + (before - anchor) * ratio, and nothing translates. Predicting it that way
// needs no inverse projection, so this measures the zoom rather than the probe.
function worstDrift(act, times) {
  h.view.zoom = 1; h.view.panX = 0; h.view.panY = 0; h.redraw();
  var anchor = [canvas.width / 2, canvas.height * 0.58];
  var points = [[0, 0, 1000], [4000, -3000, 1500], [-6000, 5000, 800]];
  var before = points.map(function (p) { return h.worldProject(p[0], p[1], p[2]); });
  var was = h.view.zoom;
  for (var i = 0; i < times; i++) {
    panel.querySelector('[data-view3d-act="' + act + '"]').click();
  }
  h.redraw();
  var ratio = h.view.zoom / was;
  var worst = 0;
  points.forEach(function (p, i) {
    var after = h.worldProject(p[0], p[1], p[2]);
    worst = Math.max(worst,
      Math.abs(after[0] - (anchor[0] + (before[i][0] - anchor[0]) * ratio)),
      Math.abs(after[1] - (anchor[1] + (before[i][1] - anchor[1]) * ratio)));
  });
  return worst;
}

return { one: worstDrift('zoom-in', 1), five: worstDrift('zoom-in', 5),
         ten: worstDrift('zoom-in', 10), out: worstDrift('zoom-out', 5) };
"""


@needs_chrome
def test_a_button_zoom_moves_nothing_but_the_scale():
    """The buttons zoomed about the middle of the canvas while `refit` centres the scene
    on `0.58H` — the sky above a flight needs more room than the ground below it. Every
    point except that one pixel row therefore slid on each press, always the same way:
    13 px per zoom-in on a 549 px canvas, so five presses walked what the reader was
    looking at 60 px down the panel. It accumulates, which is why it reads as a fault
    rather than as a choice, and it is what "the zoom drifts" means.

    The wheel was never wrong — it anchors on the pointer, and
    `test_zoom_holds_the_point_under_the_cursor` covers it. This is the path with no
    pointer to anchor on, which is also the keyboard's, since `+` maps to the same act.
    """
    answer = _probe(_scene(basemap=False), _BUTTON_ZOOM)
    for presses, drift in answer.items():
        assert drift < 0.5, (
            f"a {presses}-press button zoom translated the scene by {drift:.1f} px")


_ROTATE_HOLDS_THE_GROUND = """
var h = window.__handle;
var canvas = document.querySelector('canvas.view3d');
var box = canvas.getBoundingClientRect();
// Well down the canvas, where the ridged fixture stands highest above its datum.
var gx = box.left + box.width * 0.5, gy = box.top + box.height * 0.72;

// The point on the terrain *surface* under the cursor, worked out here rather than
// asked of the page, so the test states its own definition of what the reader grabbed.
function surfaceUnder(x, y) {
  var p = h.ground(x, y);
  if (!p) return null;
  var lonLat = h.groundLonLat(x, y);
  for (var pass = 0; pass < 6; pass++) {
    var height = h.groundAt(lonLat[0], lonLat[1]);
    var here = h.worldProject(p[0], p[1], height);
    var dy = here[1] - ((y - box.top) / box.height * canvas.height);
    if (Math.abs(dy) < 0.05) break;
    var stepped = h.ground(x, y - dy);
    if (!stepped) break;
    p = [stepped[0], stepped[1]];
    lonLat = h.groundLonLat(x, y - dy);
  }
  return { p: p, z: h.groundAt(lonLat[0], lonLat[1]) };
}

function slip(dragPx) {
  h.view.yaw = 0; h.view.pitch = 0.7; h.view.zoom = 3;
  h.view.panX = 0; h.view.panY = 0; h.redraw();
  var target = surfaceUnder(gx, gy);
  var was = h.worldProject(target.p[0], target.p[1], target.z);
  canvas.dispatchEvent(new PointerEvent('pointerdown', { clientX: gx, clientY: gy,
    button: 2, buttons: 2, bubbles: true, pointerId: 1, pointerType: 'mouse' }));
  for (var step = 1; step <= 6; step++) {
    canvas.dispatchEvent(new PointerEvent('pointermove', {
      clientX: gx + dragPx * step / 6, clientY: gy,
      buttons: 2, bubbles: true, pointerId: 1, pointerType: 'mouse' }));
  }
  canvas.dispatchEvent(new PointerEvent('pointerup', { clientX: gx + dragPx, clientY: gy,
    buttons: 0, bubbles: true, pointerId: 1, pointerType: 'mouse' }));
  h.redraw();
  var now = h.worldProject(target.p[0], target.p[1], target.z);
  return Math.max(Math.abs(now[0] - was[0]), Math.abs(now[1] - was[1]));
}

return { relief: Math.round(surfaceUnder(gx, gy).z - h.scene().terrain.min),
         short: slip(90), long: slip(180) };
"""


@needs_chrome
def test_an_orbit_turns_about_the_terrain_that_was_grabbed():
    """Not about the flat datum plane under it, which is what it used to hold.

    `world()` measures height from `dem.min`, so inverting the projection with `wz = 0`
    solves the *datum*, and the mountainside the reader put their cursor on sits well
    above it — the two are the same screen pixel but kilometres apart on the ground.
    Turning about the wrong one swings the view. Measured on this fixture's 618 m of
    relief: the grabbed terrain slid **7.1 px on a 90 px drag and 12.7 px on 180 px**,
    growing with the drag. An alpine flight carries five times the relief, which is why
    the report's map felt wrong to rotate while the airspace map — 1.4 km of relief
    across 500 km of country — felt fine.

    `groundUnder` iterates onto the surface now and the height travels with the point.
    """
    answer = _probe(_scene(), _ROTATE_HOLDS_THE_GROUND)
    assert answer["relief"] > 300, (
        "the fixture stopped being ridged, so this test cannot fail on the bug it is for")
    assert answer["short"] < 1.0, (
        f"the grabbed terrain slid {answer['short']:.1f} px on a 90 px rotate")
    assert answer["long"] < 1.0, (
        f"the grabbed terrain slid {answer['long']:.1f} px on a 180 px rotate")

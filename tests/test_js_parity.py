"""The JavaScript analysis gives Python's answer, field for field.

`tracklog_viewer/js/` is the analysis an uploaded track gets, and the Python is still the
reference. `tracklog_viewer.js_parity` holds them together on real tracklogs (63 of 63
identical when this landed), but those files stay out of the repository — so this runs
the same comparison over synthetic flights shaped to reach each rule: a drifting thermal
for the wind fit, a straight launch climb for the tow, a slalom and a ridge beat for the
turn counting, a reversal, a glide and a dive, and a coarse 15 s file for the limits.
"""

import shutil

import pytest

from tests.test_analysis import beat, build, circling, slalom, straight
from tracklog_viewer import js_parity

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def _chain(*parts):
    """Glue fix lists end to end, each starting where the last one stopped."""
    out = []
    for make in parts:
        t0, x0, y0, alt0 = out[-1] if out else (0.0, 0.0, 0.0, 1000.0)
        points = make(t0=t0 + (1 if out else 0), x0=x0, y0=y0, alt0=alt0)
        out += points
    return out


FLIGHTS = {
    "thermal-glide-thermal": lambda: _chain(
        lambda **k: circling(300, drift=(3.0, -1.0), **k),
        lambda **k: straight(400, climb=-1.1, heading=60, **k),
        lambda **k: circling(240, climb=1.4, clockwise=False, drift=(2.5, 0.5), **k),
        lambda **k: straight(300, climb=-1.3, heading=200, **k),
    ),
    "tow-then-thermal": lambda: _chain(
        lambda **k: straight(150, speed=14.0, climb=3.0, heading=90, **k),
        lambda **k: straight(120, climb=-1.0, heading=90, **k),
        lambda **k: circling(260, climb=1.8, **k),
    ),
    "slalom-and-reversal": lambda: _chain(
        lambda **k: slalom(200, **k),
        lambda **k: circling(100, **k),
        lambda **k: circling(100, clockwise=False, **k),
        lambda **k: straight(200, climb=-1.0, **k),
    ),
    "ridge-beat": lambda: _chain(
        lambda **k: beat(400, **k),
        lambda **k: straight(300, climb=-1.2, heading=140, **k),
    ),
    "dive": lambda: _chain(
        lambda **k: circling(200, **k),
        lambda **k: circling(60, climb=-6.0, radius=25.0, **k),
        lambda **k: straight(200, climb=-1.0, **k),
    ),
}


@needs_node
@pytest.mark.parametrize("name", sorted(FLIGHTS))
def test_the_javascript_analysis_matches_the_python(tmp_path, name):
    path = build(tmp_path / f"{name}.igc", FLIGHTS[name]())
    [(_, result)] = js_parity.compare([path])
    assert result == [], result if isinstance(result, str) else "\n".join(result[:20])


@needs_node
def test_a_coarse_file_matches_too(tmp_path):
    """15 s fixes: turn statistics and tow detection are refused on both sides alike."""
    points = _chain(
        lambda **k: straight(150, speed=14.0, climb=3.0, **k),
        lambda **k: circling(400, drift=(2.0, 0.0), **k),
        lambda **k: straight(400, climb=-1.0, heading=45, **k),
    )
    path = build(tmp_path / "coarse.igc", points[::15])
    [(_, result)] = js_parity.compare([path])
    assert result == [], result if isinstance(result, str) else "\n".join(result[:20])


def test_differences_are_reported_by_path():
    """The comparison itself: a mismatch names where it is and what each side said."""
    assert js_parity.differences({"a": [1, 2.0]}, {"a": [1, 2.0]}) == []
    assert js_parity.differences({"a": [1, 2.0]}, {"a": [1, 2.1]}) == [".a[1]: 2.0 != 2.1"]
    assert js_parity.differences({"a": None}, {"a": 0}) == [".a: None != 0"]
    assert js_parity.differences({"a": 1}, {}) == [".a: only in python"]

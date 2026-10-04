"""Synthetic flights shaped to reach each rule of the analysis: a drifting thermal for the
wind fit, a straight launch climb for the tow, a slalom and a ridge beat for the turn
counting, a reversal, a glide and a dive. Used where a test needs a whole flight rather
than one manoeuvre.
"""

from tests.test_analysis import beat, circling, slalom, straight


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

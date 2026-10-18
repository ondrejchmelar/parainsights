"""The flight against the airspace (`airspaceAlong` in `parainsights_map/js/view3d.js`),
which the report's Airspace section reads: inside for how long and how deep, and where
never inside, how close — under a floor, over a top, beside. The one rule that matters
most is the vertical one: a track under a zone's floor is *not* inside it, however long
it stays there, and a report that called it an infringement would be wrong in the way
that costs a pilot's trust.

Run in Node on a hand-built scene: flat ground at 300 m, a straight track east at
1 500 m, one fix every 10 s, and a zone for each answer.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

VIEW3D = Path(__file__).resolve().parents[1] / "parainsights_map" / "js" / "view3d.js"


def _box(name, kind, ac, west, east, south, north, **limits):
    return {"n": name, "nm": name, "k": kind, "ac": ac, "lon": [west, east, east, west],
            "lat": [south, south, north, north], **limits}


ZONES = [
    _box("FAR R", "restricted", "R", 14.35, 14.38, 50.18, 50.20, f=0, g=True, c=2500),
    _box("HIGH TMA", "base", "TMA C", 14.32, 14.34, 50.0, 50.2, f=2600, c=3500),
    _box("SIDE R", "restricted", "R", 14.25, 14.30, 50.115, 50.2, f=0, g=True, c=2500),
    _box("OVER TMA", "base", "TMA D", 14.15, 14.20, 50.0, 50.2, f=1700, c=3000),
    _box("THE CTR", "base", "CTR D", 14.05, 14.10, 50.0, 50.2, f=0, g=True, c=2000),
]


def _along(zones=ZONES):
    n = 401
    scene = {
        "terrain": {"west": 13.9, "east": 14.5, "south": 49.9, "north": 50.3,
                    "cols": 2, "rows": 2, "z": [300] * 4, "min": 300},
        "track": {"lon": [14.0 + 0.001 * i for i in range(n)], "lat": [50.1] * n,
                  "alt": [1500] * n, "t": [10 * i for i in range(n)]},
        "airspaces": zones, "start": 1_650_000_000, "utcOffset": 7200,
    }
    script = f"""
      const vm = require('vm'), fs = require('fs');
      const ctx = {{ window: {{ innerWidth: 0, addEventListener() {{}} }}, document: {{ documentElement: {{ clientWidth: 0, style: {{ setProperty() {{}} }} }} }} }};
      vm.createContext(ctx);
      vm.runInContext(fs.readFileSync({json.dumps(str(VIEW3D))}, 'utf8'), ctx);
      ctx.scene = {json.dumps(scene)};
      const out = vm.runInContext('airspaceAlong(scene)', ctx);
      out.zones.forEach(z => {{ delete z.ring; }});
      process.stdout.write(JSON.stringify(out));
    """
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def along():
    return _along()


def test_the_nearby_zones_in_order_entered_first_then_closest(along):
    assert [z["name"] for z in along["zones"]] == ["THE CTR", "OVER TMA", "SIDE R"]
    assert along["others"] == 2, "the high TMA and the far zone are counted, not listed"


def test_inside_is_how_long_and_how_deep(along):
    ctr = along["zones"][0]
    assert ctr["closest"] == "inside"
    assert ctr["inside"]["seconds"] == pytest.approx(500, abs=20)   # 0.05° at 0.001° a fix
    # 1 500 m between a floor on the ground (300 m) and a top at 2 000 m: 500 m from the top.
    assert ctr["inside"]["depth"] == pytest.approx(500, abs=1)
    assert ctr["inside"]["low"] == ctr["inside"]["high"] == 1500


def test_under_a_floor_is_not_inside(along):
    """The track crosses the whole of this zone's ground, 200 m under its floor."""
    tma = along["zones"][1]
    assert tma["inside"] is None
    assert tma["closest"] == "under"
    assert tma["under"]["m"] == pytest.approx(200, abs=1)
    assert tma["at"]["alt"] == 1500


def test_beside_is_metres_to_the_ring_at_a_height_within_it(along):
    side = along["zones"][2]
    assert side["closest"] == "beside"
    assert side["beside"]["m"] == pytest.approx(0.015 * 111320, abs=30)


def test_the_height_chart_has_the_inside_stretch_and_the_ground(along):
    profile = along["profile"]
    assert len(profile["t"]) == len(profile["alt"]) == len(profile["ground"]) == len(profile["inside"])
    inside = [t for t, flag in zip(profile["t"], profile["inside"]) if flag]
    assert inside and min(inside) >= 490 and max(inside) <= 1010    # 14.05°-14.10°
    assert set(profile["ground"]) == {300}
    ctr = along["zones"][0]
    assert ctr["spans"] and ctr["spans"][0]["floor"] == 300 and ctr["spans"][0]["top"] == 2000


def test_nothing_nearby_is_an_empty_list(along):
    far = [z for z in ZONES if z["n"] in ("FAR R", "HIGH TMA")]
    out = _along(far)
    assert out["zones"] == [] and out["others"] == 2

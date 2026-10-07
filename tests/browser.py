"""Headless Chrome for the tests that need a real browser, and the scene they load.

`_probe` renders a 3D panel (`view3d.panel`) with the panel script and nothing else —
no MapLibre — runs a snippet against its handle and returns what the snippet answered.
The tests that need the map itself drive Chrome over the DevTools protocol instead
(`test_merged_controls.Browser`).

No network: the DEM is synthetic, and every host but this machine resolves to nothing.
"""

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from parainsights_map import view3d

CHROME = shutil.which("google-chrome") or shutil.which("chromium")
needs_chrome = pytest.mark.skipif(CHROME is None, reason="needs headless Chrome")

# swiftshader, so this runs the same on a machine with no GPU — including CI. It is a
# software rasteriser, which makes the timing pessimistic and the geometry identical.
CHROME_FLAGS = [
    "--headless", "--disable-gpu", "--no-sandbox", "--window-size=1280,900",
    "--virtual-time-budget=20000", "--enable-unsafe-swiftshader",
    "--use-gl=angle", "--use-angle=swiftshader", "--dump-dom",
    # No test reaches the internet. Every host but this machine resolves to nothing, so a
    # page under test that still points at a real tile server, CDN or image fails here
    # rather than quietly downloading on every run (flymet's meteogram did, for months).
    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
]


def _terrain(cols: int = 81, rows: int = 81) -> dict:
    """A ridged DEM: 200 m to 1 400 m of relief over a quarter of a degree."""
    z = []
    for r in range(rows):
        for c in range(cols):
            ridge = math.sin(4 * math.pi * c / cols) * math.cos(3 * math.pi * r / rows)
            z.append(round(800 + 600 * ridge))
    return {
        "west": 14.0, "east": 14.25, "south": 49.0, "north": 49.25,
        "cols": cols, "rows": rows, "min": min(z), "max": max(z), "z": z,
    }


def _scene(*, terrain: dict | None = None, sun: dict | None = None,
           wind: dict | None = None, cursor: dict | None = None,
           tiles: bool = False, airspace: bool = False) -> dict:
    dem = terrain or _terrain()
    track = {"lon": [], "lat": [], "alt": [], "c": []}
    for i in range(120):
        track["lon"].append(round(14.02 + i * 0.0015, 5))
        track["lat"].append(round(49.05 + math.sin(i / 15) * 0.02, 5))
        track["alt"].append(dem["max"] + 200 + i * 5)
        track["c"].append(i % 6)
    return {
        "terrain": dem,
        "trackTop": max(track["alt"]),
        "track": track,
        "climbs": [{"label": "1", "lon": 14.1, "lat": 49.1,
                    "alt": dem["max"] + 400, "tow": False}],
        # One of each, so a test can turn the two label switches on independently and see
        # that each drew only its own.
        "phases": [
            {"kind": "climb", "text": "+2.1 m/s · +480 m",
             "lon": [14.04, 14.06], "lat": [49.06, 49.08],
             "alt": [dem["max"] + 220, dem["max"] + 700]},
            {"kind": "glide", "text": "8.4:1 · 12.0 km",
             "lon": [14.06, 14.14], "lat": [49.08, 49.12],
             "alt": [dem["max"] + 700, dem["max"] + 260]},
        ],
        "palette": [[20, 40, 60], [60, 90, 120], [120, 150, 60],
                    [200, 160, 40], [230, 110, 50], [240, 60, 40]],
        # Templates only: no test reaches the hosts they name.
        "tiles": view3d.TILE_SOURCES if tiles else None,
        "landing": {"lon": 14.2, "lat": 49.2, "alt": dem["min"]},
        # Absent unless a test asks for them: a panel with no date has no sun and an
        # uploaded track may have no wind estimate, and neither may draw anything then.
        **({"sun": sun} if sun else {}),
        **({"wind": wind} if wind else {}),
        # One zone over the flight, behind the switch a flight map offers — the shape
        # the viewer sees, which is not the shape the airspace map sees: there the layer
        # is the subject, is on, and has no button.
        **({
            "airspaces": [{
                "k": "base", "n": "TMA TEST  (GND – FL 95)", "f": 0, "g": True,
                "c": 2896,
                "lon": [14.05, 14.20, 14.20, 14.05],
                "lat": [49.05, 49.05, 49.20, 49.20],
            }],
            "airspaceColours": {"base": "#c2410c"},
            "airspaceToggle": True,
        } if airspace else {}),
        # Not part of the payload: the cursor track is initView3d's second argument, and
        # `_probe` lifts it out of here and hands it over as one.
        **({"__cursor": cursor} if cursor else {}),
    }


_HARNESS = """
<pre id="probe-out"></pre>
<script>%s
window.__handle = initView3d(document.querySelector('.view3d-panel'),
                            window.__cursorTrack || null);
</script>
<script>
window.addEventListener('load', function () {
  // setTimeout, never a chained requestAnimationFrame: rAF hangs outright under
  // --virtual-time-budget.
  setTimeout(function () {
    var answer;
    try { answer = (function () { %s })(); }
    catch (error) { answer = { error: String((error && error.stack) || error) }; }
    Promise.resolve(answer).then(function (value) {
      document.getElementById('probe-out').textContent = JSON.stringify(value);
    });
  }, 1200);
});
</script>
"""


def _probe(scene: dict, body: str, *, page_extra: str = "",
           doctype: bool = True, device_scale: float | None = None,
           window: tuple[int, int] | None = None) -> dict:
    """Render a panel carrying `scene`, run `body` in it, and return what it answered.

    `page_extra` is markup appended after the panel. The real report is several screens
    tall, so the document has a scrollbar from the first layout — which is a fact the
    full-bleed panel is sized against, and a short probe page does not have one.

    `window` replaces the default 1280 x 900 viewport. It has to be the real window and
    not a narrowed wrapper: the panel is full-bleed to `100vw` and its own layout rules
    are media queries, so a phone layout only exists at a phone-sized viewport.

    `doctype=False` renders the page in quirks mode, which the report itself did until
    the full-screen bug was traced to it. It is kept as a switch because the panel is
    embeddable and cannot control the document it lands in.

    `device_scale` drives the device pixel ratio. The backing store is the box times that
    ratio, so anything that converts between CSS and canvas pixels is only half tested at
    a ratio of 1 — which is how a rotation gesture came to turn twice as far on a retina
    screen as on the machine it was tuned on.
    """
    cursor = dict(scene).pop("__cursor", None)
    scene = {k: v for k, v in scene.items() if k != "__cursor"}
    page = (
        ('<!doctype html>' if doctype else '')
        + '<meta charset="utf-8"><title>probe</title>'
        f"<style>{view3d.STYLE}</style>"
        f'<div class="wrap">{view3d.panel(scene, "t")}</div>'
        + (f"<script>window.__cursorTrack = {json.dumps(cursor)};</script>" if cursor else "")
        + page_extra
        + _HARNESS % (view3d.SCRIPT, body)
    )
    flags = list(CHROME_FLAGS)
    if window is not None:
        flags = [f for f in flags if not f.startswith("--window-size=")]
        flags.append(f"--window-size={window[0]},{window[1]}")
    if device_scale is not None:
        flags.append(f"--force-device-scale-factor={device_scale}")
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "probe.html"
        target.write_text(page, encoding="utf-8")
        result = subprocess.run(
            [CHROME, *flags, target.as_uri()],
            capture_output=True, text=True, timeout=180,
        )
    match = re.search(r'<pre id="probe-out">(.*?)</pre>', result.stdout, re.S)
    assert match and match.group(1).strip(), (
        "the probe produced nothing:\n" + result.stderr[-2000:])
    text = match.group(1)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                         ("&amp;", "&")):
        text = text.replace(entity, char)
    answer = json.loads(text)
    assert "error" not in answer, answer.get("error")
    return answer

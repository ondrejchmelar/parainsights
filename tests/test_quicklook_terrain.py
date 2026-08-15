"""Terrain for an uploaded track, fetched and decoded in the page.

An uploaded track used to get a flat plane, because the DEM is a tile fetch and a
published artifact may reach no host. On a host it can, and the terrarium tiles are
CORS-open, so the browser is allowed to read their pixels. This is the test that the
decode and the sampling are right.

No network: the tile URL is rewritten to a data URI carrying a tile this file encodes
itself, with two known elevations in it. That is the same trick as generating the PNG
icons rather than pasting a base64 constant — a constant nobody can verify is how a
corrupt tile would get in.
"""

import base64
import datetime as dt
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.test_view3d_gl import CHROME, CHROME_FLAGS, _png, needs_chrome
from tracklog_viewer import quicklook, render_html

# Terrarium encodes metres as R * 256 + G + B / 256 - 32768. Two flat halves, so the
# grid has a known minimum, a known maximum, and a step the sampler has to land on both
# sides of.
LOW, HIGH = 100, 1000


def _terrarium_tile(size: int = 256) -> str:
    import numpy as np

    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    for half, metres in ((slice(0, size // 2), LOW), (slice(size // 2, size), HIGH)):
        raw = metres + 32768
        rgba[:, half, 0] = raw // 256
        rgba[:, half, 1] = raw % 256
        rgba[:, half, 2] = 0
    rgba[..., 3] = 255
    return "data:image/png;base64," + base64.b64encode(_png(rgba)).decode("ascii")


def _igc() -> str:
    """A short synthetic flight, written the way `tests/test_analysis` writes them."""
    lines = ["AXCT000", "HFDTE010726", "HFPLTPILOTINCHARGE:Test"]
    base = 12 * 3600
    for second in range(0, 900):
        # A circling climb, so the quicklook has a thermal to report as well.
        angle = 2 * math.pi * second / 20
        lat = 46.0 + (40 * math.cos(angle) + second * 0.4) / 111320
        lon = 14.0 + (40 * math.sin(angle)) / (111320 * math.cos(math.radians(46.0)))
        alt = 1200 + 1.5 * second
        clock = base + second
        lat_deg, lon_deg = int(lat), int(lon)
        lat_min = round((lat - lat_deg) * 60000)
        lon_min = round((lon - lon_deg) * 60000)
        lines.append(
            f"B{clock // 3600:02d}{(clock // 60) % 60:02d}{clock % 60:02d}"
            f"{lat_deg:02d}{lat_min:05d}N{lon_deg:03d}{lon_min:05d}E"
            f"A{int(alt):05d}{int(alt):05d}"
        )
    return "\n".join(lines) + "\n"


_UPLOAD = """
<pre id="probe-out"></pre>
<script id="igc-source" type="text/plain">%s</script>
<script>
window.addEventListener('load', function () {
  setTimeout(function () {
    var out = {};
    try {
      window.__quickLook(document.getElementById('igc-source').textContent, 'probe.igc');
      setTimeout(function () {
        var article = document.querySelector('[data-flight-report="own1"]');
        out.uploaded = !!article;
        if (article) {
          out.note = article.querySelector('.ql-3d-note').textContent;
          var clearance = article.querySelector('.ql-clearance');
          out.clearance = clearance
            ? clearance.querySelector('.stat-value').textContent : null;
          out.clearanceSub = clearance
            ? clearance.querySelector('.sub').textContent : null;
          var data = article.querySelector('.view3d-data');
          var terrain = data ? JSON.parse(data.textContent).terrain : null;
          out.terrain = terrain && { cols: terrain.cols, rows: terrain.rows,
                                     min: terrain.min, max: terrain.max,
                                     zoom: terrain.zoom || null,
                                     nodes: terrain.z.length,
                                     distinct: terrain.z.filter(function (v, i, all) {
                                       return all.indexOf(v) === i;
                                     }).length };
        }
        document.getElementById('probe-out').textContent = JSON.stringify(out);
      }, 6000);
    } catch (error) {
      document.getElementById('probe-out').textContent =
        JSON.stringify({ error: String((error && error.stack) || error) });
    }
  }, 800);
});
</script>
"""


def _upload(*, tiles: bool = True) -> dict:
    """Render a report page, hand the uploader a track, and read back what it built.

    `tiles=False` cuts the tile URL to nothing, which is the published-artifact case:
    every request fails and the ground has to fall back to a flat plane.
    """
    page = render_html._page("probe", [])
    tile = _terrarium_tile() if tiles else "about:blank#{z}/{x}/{y}"
    original = "'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'"
    assert original in page, "the DEM tile URL moved; this test rewrites it by hand"
    page = page.replace(original, json.dumps(tile))
    page += _UPLOAD % _igc()

    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "upload.html"
        target.write_text(page, encoding="utf-8")
        result = subprocess.run(
            [CHROME, *CHROME_FLAGS, target.as_uri()],
            capture_output=True, text=True, timeout=180,
        )
    match = re.search(r'<pre id="probe-out">(.*?)</pre>', result.stdout, re.S)
    assert match and match.group(1).strip(), (
        "the probe produced nothing:\n" + result.stderr[-2000:])
    text = match.group(1)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&amp;", "&")):
        text = text.replace(entity, char)
    answer = json.loads(text)
    assert "error" not in answer, answer.get("error")
    return answer


@needs_chrome
class TestAnUploadedTrackGetsRealTerrain:
    def test_the_dem_is_decoded_and_sampled(self):
        answer = _upload()
        assert answer["uploaded"] is True
        terrain = answer["terrain"]
        assert terrain is not None
        # Both halves of the tile land in the grid, decoded to the metre.
        assert terrain["min"] == LOW
        assert terrain["max"] == HIGH
        assert terrain["distinct"] == 2, "only the two encoded elevations should appear"
        assert terrain["nodes"] == terrain["cols"] * terrain["rows"]
        assert terrain["nodes"] <= 16000, "the node budget"
        assert 6 <= terrain["zoom"] <= 12

    def test_the_caption_says_where_the_ground_came_from(self):
        answer = _upload()
        assert "terrarium" in answer["note"]
        assert "flat plane" not in answer["note"]

    def test_it_falls_back_to_a_flat_plane_when_the_tiles_cannot_be_had(self):
        """The published-artifact case: no host is reachable, and the view still works."""
        answer = _upload(tiles=False)
        assert answer["uploaded"] is True
        terrain = answer["terrain"]
        assert terrain["min"] == terrain["max"], "a flat plane"
        assert "flat plane" in answer["note"]
        assert "could not be fetched" in answer["note"]


@needs_chrome
class TestTheClearanceSeriesIsWritten:
    """The DEM was fetched and then only drawn: height above ground was never derived.

    The fixture flies from 1 200 m upwards over the western half of the tile, which
    encodes 100 m — so the lowest clearance is the launch altitude less the ground, and
    a page that forgot to subtract the ground reports 1 200.
    """

    def test_the_lowest_clearance_is_the_track_less_the_ground(self):
        answer = _upload()
        assert answer["clearance"], "no clearance tile after the DEM arrived"
        metres = int(answer["clearance"].split()[0])
        assert abs(metres - (1200 - LOW)) <= 60, (
            f"clearance came out {metres} m against an expected {1200 - LOW}")

    def test_it_says_the_launch_and_the_landing_are_out_of_it(self):
        """The lowest clearance of any flight is the ground it started on, so the window
        excludes both ends — the same `ground_margin` the report's low-point card uses.
        A number that does not say this is a number about the takeoff."""
        answer = _upload()
        assert "launch and landing excluded" in answer["clearanceSub"]

    def test_no_ground_means_no_clearance_rather_than_a_wrong_one(self):
        """The published-artifact case. A flat plane at the flight's own lowest point
        would report a clearance measured against an invention."""
        answer = _upload(tiles=False)
        assert answer["uploaded"] is True
        assert answer["clearance"] is None


@needs_chrome
def test_the_quicklook_and_the_cli_decode_terrarium_the_same_way():
    """One formula, written twice — so it is worth checking they still agree."""
    assert "R * 256 + G + B / 256 - 32768" in quicklook.SCRIPT
    from tracklog_viewer import terrain as terrain_module

    assert "R * 256 + G + B / 256 - 32768" in terrain_module.__doc__

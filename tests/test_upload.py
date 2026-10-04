"""An uploaded track gets the bundled flights' article, built in the page (`js/upload.js`).

No network here, so the three optional inputs all fail — no ground, no weather, no glider
table — and that is the case worth holding: the article must still be complete in every
other respect, and say what it could not fetch rather than leaving a blank where it was.
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path

from tests.test_analysis import build
from tests.test_js_parity import FLIGHTS
from tests.test_view3d_gl import CHROME, CHROME_FLAGS, needs_chrome
from tracklog_viewer import render_html

# A longer virtual clock than the suite's default: virtual time runs on while the file
# read is pending, and under a loaded parallel run the read and the analysis can outlast
# 20 s of it. The probes poll and stop as soon as the article is there.
_FLAGS = [f if not f.startswith("--virtual-time-budget") else "--virtual-time-budget=60000"
          for f in CHROME_FLAGS]

_PROBE = """
<pre id="probe-out"></pre>
<script id="igc-source" type="text/plain">%s</script>
<script>
window.addEventListener('load', function () {
  setTimeout(function () {
    var file = new File([document.getElementById('igc-source').textContent], 'mine.igc');
    var input = document.getElementById('ql-file');
    var dt = new DataTransfer(); dt.items.add(file); input.files = dt.files;
    input.dispatchEvent(new Event('change'));
    var seen = { busy: false };
    setTimeout(function () {
      var st = document.getElementById('ql-status');
      seen.busy = st.classList.contains('is-busy') && st.getAttribute('aria-busy') === 'true';
      seen.spin = getComputedStyle(st, '::before').animationName;
    }, 10);
    var waited = 0;
    (function poll() {
      var st = document.getElementById('ql-status');
      if (!document.querySelector('[data-flight-report="up1"]') && !st.classList.contains('is-error')
          && (waited += 500) < 55000) return setTimeout(poll, 500);
      var a = document.querySelector('[data-flight-report="up1"]'), out = { article: !!a };
      if (a) {
        out.visible = !a.hidden;
        out.sections = Array.prototype.map.call(a.querySelectorAll('h2'), function (h) { return h.textContent; });
        out.climbRows = a.querySelectorAll('.table-climbs tbody tr').length;
        out.profileDrawn = !!a.querySelector('.chart-host[data-chart="profile"] svg');
        out.planDrawn = !!a.querySelector('.chart-host[data-chart="plan"] svg');
        out.verdict = (a.querySelector('.verdict-line') || {}).textContent || '';
      }
      out.status = document.getElementById('ql-status').textContent;
      out.busyWhileWorking = seen.busy;
      out.spinner = seen.spin;
      out.busyAfter = document.getElementById('ql-status').classList.contains('is-busy');
      document.getElementById('probe-out').textContent = JSON.stringify(out);
    })();
  }, 800);
});
</script>
"""


@needs_chrome
def test_an_upload_gets_the_full_article_even_offline(tmp_path):
    igc = build(tmp_path / "mine.igc", FLIGHTS["thermal-glide-thermal"]()).read_text()
    page = render_html._page("probe", []) + _PROBE % igc
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "upload.html"
        target.write_text(page, encoding="utf-8")
        result = subprocess.run([CHROME, *_FLAGS, target.as_uri()],
                                capture_output=True, text=True, timeout=180)
    found = re.search(r'<pre id="probe-out">(.*?)</pre>', result.stdout, re.S)
    assert found and found.group(1).strip(), result.stderr[-2000:]
    out = json.loads(found.group(1))
    assert out["article"] and out["visible"], out
    # The flight's own sections are all there; with no ground there is no 3D view, so the
    # side view carries the first section, as in a report built without --terrain.
    assert "Debrief" in out["sections"] or out["verdict"], out
    for heading in ("The flight from the side", "Top view", "Where the time went", "Climbs",
                    "Glides", "How to read this, and what to distrust"):
        assert heading in out["sections"], (heading, out["sections"])
    assert out["climbRows"] >= 2 and out["profileDrawn"] and out["planDrawn"], out
    assert out["verdict"].startswith("A "), out
    # And it says what it could not fetch.
    assert "ground" in out["status"] and "weather" in out["status"], out["status"]
    # A spinner while it works, and none once it is done.
    assert out["busyWhileWorking"] and out["spinner"] == "ql-spin", out
    assert not out["busyAfter"], out


_AIRSPACE_PROBE = """
<div class="airspace-article" hidden><script type="application/json" class="view3d-data">%s</script></div>
<pre id="probe-out"></pre>
<script id="igc-source" type="text/plain">%s</script>
<script>
// Ground for the upload without a network: every node at 300 m.
window.loadTerrain = function (grid) {
  grid.z = new Array(grid.rows * grid.cols).fill(300);
  grid.min = 300; grid.max = 300;
  return Promise.resolve();
};
window.addEventListener('load', function () {
  setTimeout(function () {
    var file = new File([document.getElementById('igc-source').textContent], 'mine.igc');
    var input = document.getElementById('ql-file');
    var dt = new DataTransfer(); dt.items.add(file); input.files = dt.files;
    input.dispatchEvent(new Event('change'));
    var waited = 0;
    (function poll() {
      var st = document.getElementById('ql-status');
      if (!document.querySelector('[data-flight-report="up1"]') && !st.classList.contains('is-error')
          && (waited += 500) < 55000) return setTimeout(poll, 500);
      var a = document.querySelector('[data-flight-report="up1"]'), out = { article: !!a };
      if (a) {
        var scene = JSON.parse(a.querySelector('.view3d-data').textContent);
        out.rings = (scene.airspaces || []).map(function (r) { return r.n; });
        out.toggle = !!scene.airspaceToggle;
        out.button = !!a.querySelector('[data-view3d-act="airspace-toggle"]');
      }
      document.getElementById('probe-out').textContent = JSON.stringify(out);
    })();
  }, 800);
});
</script>
"""


def _ring(name, west, east, south, north):
    return {"n": name, "k": "base", "f": 0, "c": 1500, "g": True,
            "lon": [west, east, east, west], "lat": [south, south, north, north]}


@needs_chrome
def test_an_upload_gets_the_airspace_the_page_carries(tmp_path):
    """The Planner view carries every Czech ring; an uploaded flight takes the ones over its
    own ground, and its 3D map gains the same airspace button a bundled flight has."""
    from tests.test_analysis import LAT0, LON0

    igc = build(tmp_path / "mine.igc", FLIGHTS["thermal-glide-thermal"]()).read_text()
    rings = {"airspaces": [_ring("OVER THE FLIGHT", LON0 - 0.05, LON0 + 0.05, LAT0 - 0.05, LAT0 + 0.05),
                           _ring("FAR AWAY", LON0 + 5, LON0 + 6, LAT0 + 5, LAT0 + 6)],
             "airspaceColours": {"base": "#d33"}}
    page = render_html._page("probe", []) + _AIRSPACE_PROBE % (json.dumps(rings), igc)
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "upload.html"
        target.write_text(page, encoding="utf-8")
        result = subprocess.run([CHROME, *_FLAGS, target.as_uri()],
                                capture_output=True, text=True, timeout=180)
    found = re.search(r'<pre id="probe-out">(.*?)</pre>', result.stdout, re.S)
    assert found and found.group(1).strip(), result.stderr[-2000:]
    out = json.loads(found.group(1))
    assert out["article"], out
    assert out["rings"] == ["OVER THE FLIGHT"], out
    assert out["toggle"] and out["button"], out

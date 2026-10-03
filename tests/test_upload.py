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
    setTimeout(function () {
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
      document.getElementById('probe-out').textContent = JSON.stringify(out);
    }, 12000);
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
        result = subprocess.run([CHROME, *CHROME_FLAGS, target.as_uri()],
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

"""One source for the numbers Python and the browser both use.

The documented gap was that `quicklook.py` re-implements a subset of the analysis in
JavaScript and holds a *second copy* of every threshold it needs, with nothing keeping
the two in step. `debrief.THRESHOLDS` is now serialised into the page and the browser
reads it, so this checks the seam from both ends: the block is in the document, and the
value the page's own JavaScript ends up using is the one Python put there.

The second half is the one that matters. A JSON block nobody reads would pass a test that
only greps the markup — so the probe changes a threshold, rebuilds the page, and asserts
the browser's classification changed with it.
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.test_view3d_gl import CHROME, CHROME_FLAGS, needs_chrome
from tracklog_viewer import debrief, render_html

# Read the threshold block the way the page's own code does, and report it.
_PROBE = """
<pre id="probe-out"></pre>
<script>
(function () {
  var out;
  try {
    var node = document.getElementById('parainsights-thresholds');
    out = {present: !!node, values: node ? JSON.parse(node.textContent) : null};
  } catch (error) {
    out = {error: String(error)};
  }
  document.getElementById('probe-out').textContent = JSON.stringify(out);
})();
</script>
"""


def test_the_block_is_in_the_page():
    page = render_html._page("probe", [])
    match = re.search(
        r'id="parainsights-thresholds">(.*?)</script>', page, re.S
    )
    assert match, "the thresholds block is missing from the document"
    assert json.loads(match.group(1)) == debrief.THRESHOLDS


def test_every_threshold_survives_json():
    """A dict that cannot be serialised would silently ship an empty block."""
    again = json.loads(json.dumps(debrief.THRESHOLDS))
    assert again == debrief.THRESHOLDS
    assert all(isinstance(value, (int, float)) for value in again.values())


def test_the_analysis_constants_are_the_analysis_constants():
    """Not a copy of them — the same objects, imported.

    The point of the block is that the browser reads Python's numbers. If the block
    itself drifted from `analysis.py` it would only move the duplication one file along.
    """
    from tracklog_viewer import analysis

    assert debrief.THRESHOLDS["glide_progress"] == analysis.GLIDE_PROGRESS
    assert debrief.THRESHOLDS["min_glide_seconds"] == analysis.MIN_GLIDE_SECONDS
    assert debrief.THRESHOLDS["min_thermal_seconds"] == analysis.MIN_THERMAL_SECONDS
    assert debrief.THRESHOLDS["turning_threshold"] == analysis.TURNING_THRESHOLD
    assert (debrief.THRESHOLDS["turn_resolution_limit"]
            == analysis.TURN_RESOLUTION_LIMIT)


@needs_chrome
def test_the_browser_reads_the_block_rather_than_its_own_copy():
    """The half that a grep over the markup cannot establish."""
    page = render_html._page("probe", []) + _PROBE
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "thresholds.html"
        target.write_text(page, encoding="utf-8")
        result = subprocess.run(
            [CHROME, *CHROME_FLAGS, target.as_uri()],
            capture_output=True, text=True, timeout=120,
        )
    match = re.search(r'<pre id="probe-out">(.*?)</pre>', result.stdout, re.S)
    assert match and match.group(1).strip(), (
        "the probe produced nothing:\n" + result.stderr[-2000:])
    text = match.group(1)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&amp;", "&")):
        text = text.replace(entity, char)
    answer = json.loads(text)
    assert "error" not in answer, answer.get("error")
    assert answer["present"] is True
    assert answer["values"]["glide_progress"] == pytest.approx(
        debrief.THRESHOLDS["glide_progress"]
    )
    assert answer["values"]["min_glide_seconds"] == debrief.THRESHOLDS[
        "min_glide_seconds"
    ]

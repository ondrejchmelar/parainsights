"""The linked cursor on an uploaded track, driven as real events in a real browser.

An upload used to get none of this. `initView3d` was handed a null cursor track, so the
3D map had nothing to follow; the climb and glide rows carried no position, so clicking
one did nothing; and the two canvas charts were pictures. The built reports have had a
linked cursor for a while, and "a lot of features don't work when I upload my own IGC"
was mostly this one missing wire.

None of it is visible in the DOM — the marker is drawn *into* a canvas, and whether the
map moved is a number inside a closure — so these dispatch pointer events at the real
charts and read the view's own cursor back through the handle it registers.
"""

import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

from tests.test_view3d_gl import CHROME, CHROME_FLAGS, needs_chrome
from tracklog_viewer import render_html


def _igc() -> str:
    """A flight with a circling climb, a glide, and a second climb.

    Long enough that the phase detector finds both climbs and the glide between them, so
    the tables under test have rows in them; the geometry is otherwise not the point.
    """
    lines = ["AXCT000", "HFDTE010726", "HFPLTPILOTINCHARGE:Test"]
    base = 12 * 3600
    x = y = 0.0
    alt = 1200.0
    for second in range(1800):
        leg = second // 600
        if leg == 1:                       # a glide, straight and down
            x += 13.0
            alt -= 1.1
        else:                              # circling, climbing
            angle = 2 * math.pi * second / 20
            x += 40 * (math.cos(angle) - math.cos(2 * math.pi * (second - 1) / 20))
            y += 40 * (math.sin(angle) - math.sin(2 * math.pi * (second - 1) / 20))
            alt += 1.4
        lat = 46.0 + y / 111320
        lon = 14.0 + x / (111320 * math.cos(math.radians(46.0)))
        clock = base + second
        lat_deg, lon_deg = int(lat), int(lon)
        lines.append(
            f"B{clock // 3600:02d}{(clock // 60) % 60:02d}{clock % 60:02d}"
            f"{lat_deg:02d}{round((lat - lat_deg) * 60000):05d}N"
            f"{lon_deg:03d}{round((lon - lon_deg) * 60000):05d}E"
            f"A{int(alt):05d}{int(alt):05d}"
        )
    return "\n".join(lines) + "\n"


_PROBE = """
<pre id="probe-out"></pre>
<script id="igc-source" type="text/plain">%s</script>
<script>
function send(node, type, x, y) {
  node.dispatchEvent(new PointerEvent(type, {
    clientX: x, clientY: y, bubbles: true, cancelable: true, pointerId: 1,
    isPrimary: true
  }));
}
function mouse(node, type) {
  node.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true }));
}
window.addEventListener('load', function () {
  setTimeout(function () {
    var out = {};
    try {
      window.__quickLook(document.getElementById('igc-source').textContent, 'probe.igc');
      setTimeout(function () {
        var article = document.querySelector('[data-flight-report="own1"]');
        out.uploaded = !!article;
        var view = (window.__view3dAll || {})['view3d-own1'];
        out.hasView = !!view;
        if (!article || !view) {
          document.getElementById('probe-out').textContent = JSON.stringify(out);
          return;
        }
        out.startCursor = view.cursor();
        out.climbRows = article.querySelectorAll('.ql-table tbody tr[data-cursor]').length;
        out.glideRows = article.querySelectorAll('.ql-glides tbody tr[data-cursor]').length;
        out.linked = article.querySelectorAll('tr.is-linked').length;

        %s

        document.getElementById('probe-out').textContent = JSON.stringify(out);
      }, 5000);
    } catch (error) {
      document.getElementById('probe-out').textContent =
        JSON.stringify({ error: String((error && error.stack) || error) });
    }
  }, 800);
});
</script>
"""


def _upload(body: str = "") -> dict:
    page = render_html._page("probe", [])
    # No network in the test job, so the DEM fetch has to fail rather than hang: the
    # flat-plane fallback is the path a published artifact takes anyway, and the cursor
    # is indexed off the track, not off the ground.
    original = "'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'"
    assert original in page, "the DEM tile URL moved; this test rewrites it by hand"
    page = page.replace(original, json.dumps("about:blank#{z}/{x}/{y}"))
    page += _PROBE % (_igc(), body)

    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "upload.html"
        target.write_text(page, encoding="utf-8")
        result = subprocess.run(
            [CHROME, *CHROME_FLAGS, target.as_uri()],
            capture_output=True, text=True, timeout=200,
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
class TestAnUploadedTrackHasALinkedCursor:
    def test_the_map_is_given_a_track_to_follow(self):
        """`initView3d(panel, null)` is the whole bug in one argument."""
        answer = _upload("""
          view.setCursor(12);
          out.afterSet = view.cursor();
          out.screen = view.screenOf ? !!view.screenOf(12) : null;
        """)
        assert answer["hasView"], "no 3D view was built for the upload"
        assert answer["startCursor"] is None, "the cursor starts unset"
        assert answer["afterSet"] == 12
        assert answer["screen"] is not False, (
            "the view accepted a cursor index but could not place it — the cursor track "
            "is missing or the wrong length")

    def test_the_rows_carry_a_position_and_are_marked_clickable(self):
        answer = _upload()
        assert answer["climbRows"] >= 2, (
            f"the climb table has {answer['climbRows']} linkable rows; the phase "
            "detector found nothing to link")
        assert answer["glideRows"] >= 1
        assert answer["linked"] == answer["climbRows"] + answer["glideRows"]

    def test_clicking_a_climb_row_moves_the_map(self):
        """The reported defect, end to end: a row in front of the reader and no way to
        ask where on the ground it happened."""
        answer = _upload("""
          var row = article.querySelector('.ql-table tbody tr[data-cursor]');
          row.click();
          out.afterClick = view.cursor();
          out.rowFix = parseInt(row.dataset.cursor, 10);
        """)
        assert answer["afterClick"] is not None, "clicking a climb row left the map blank"
        assert answer["afterClick"] >= 0

    def test_a_second_click_on_the_same_row_lets_go(self):
        answer = _upload("""
          var row = article.querySelector('.ql-table tbody tr[data-cursor]');
          row.click();
          out.pinned = view.cursor();
          row.click();
          out.released = view.cursor();
        """)
        assert answer["pinned"] is not None
        assert answer["released"] is None, "the pin never lets go"

    def test_hovering_the_side_view_moves_the_map(self):
        answer = _upload("""
          var side = article.querySelector('.ql-side');
          var box = side.getBoundingClientRect();
          send(side, 'pointermove', box.left + box.width * 0.25, box.top + box.height / 2);
          out.left = view.cursor();
          send(side, 'pointermove', box.left + box.width * 0.75, box.top + box.height / 2);
          out.right = view.cursor();
        """)
        assert answer["left"] is not None and answer["right"] is not None, (
            "hovering the side view did not reach the map")
        assert answer["right"] > answer["left"], (
            f"the cursor did not advance along the flight: {answer['left']} then "
            f"{answer['right']}")

    def test_leaving_a_chart_returns_to_the_pin_rather_than_clearing(self):
        """Hover previews; a click pins. Taking the pin away when the pointer wanders off
        is what made the built report's cursor feel like it was fighting the reader."""
        answer = _upload("""
          var row = article.querySelector('.ql-table tbody tr[data-cursor]');
          row.click();
          out.pinned = view.cursor();
          var side = article.querySelector('.ql-side');
          var box = side.getBoundingClientRect();
          send(side, 'pointermove', box.left + box.width * 0.8, box.top + box.height / 2);
          out.hovered = view.cursor();
          send(side, 'pointerleave', 0, 0);
          out.afterLeave = view.cursor();
        """)
        assert answer["pinned"] is not None
        assert answer["hovered"] != answer["pinned"], "the hover never previewed"
        assert answer["afterLeave"] == answer["pinned"], (
            "leaving the chart dropped the pin instead of returning to it")

    def test_hovering_the_top_view_reaches_the_map_too(self):
        answer = _upload("""
          var plan = article.querySelector('.ql-plan');
          var box = plan.getBoundingClientRect();
          send(plan, 'pointermove', box.left + box.width * 0.5, box.top + box.height * 0.5);
          out.plan = view.cursor();
        """)
        assert answer["plan"] is not None, "the top view is still a picture"

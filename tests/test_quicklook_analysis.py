"""What the in-page analysis makes of a track, against what the Python one makes of it.

`quicklook` is a deliberately reduced re-implementation of `analysis` in JavaScript, and
the risk that comes with any second implementation is that the two quietly drift. Two
places where they had:

* the phase detector demanded one *unbroken* run over the threshold, where `analysis.py`
  has always condensed runs separated by less than `CONDENSE_THERMAL` first. A climb
  gains height in surges, so an evening spent working a ridge reported "No climbs met
  the thresholds" in the browser while the same file gave three climbs in Python.
* the clock printed UTC, where the report prints local time from the logger's own
  `HFTZN` header — so the same flight read 15:43 in one place and 17:43 in the other.

Neither is visible without running the page, so these upload a track built to have the
answer in it and read the tables back.
"""

import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

from tests.test_view3d_gl import CHROME, CHROME_FLAGS, needs_chrome
from tracklog_viewer import render_html

TZ_HOURS = 2


def _surging_igc(*, timezone: bool = True) -> str:
    """A climb worked in surges, the way a slope is: up, level, up, level.

    Twenty minutes of it, gaining far more than the 50 m floor, but the lift comes in
    25 second surges with 15 seconds of nothing between them — so no unbroken run of the
    thermal test survives the 60 second minimum, and only a detector that bridges the
    gaps first finds a climb at all. Verified both ways: with the bridge removed the
    page prints the reported "No climbs met the thresholds."
    """
    lines = ["AXCT000", "HFDTE010726", "HFPLTPILOTINCHARGE:Test"]
    if timezone:
        lines.append(f"HFTZNTIMEZONE:+{TZ_HOURS}.0")
    base = 12 * 3600
    x = y = 0.0
    alt = 900.0
    for second in range(1200):
        # Beating along a line, turning back every 20 s: no complete circles, which is
        # what working a ridge looks like. The leg has to be short enough that the 20 s
        # progress window sees the glider come back — a long out-and-back reads as
        # straight flight at every fix inside it, and neither implementation calls that
        # a climb.
        leg = (second // 20) % 2
        x += 11.0 if leg == 0 else -11.0
        y += 1.5
        # Lift in 25 s surges with 15 s of nothing between them.
        alt += 1.6 if (second % 40) < 25 else 0.0
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


def _device_igc(zone: str) -> str:
    """The surging flight, with XCTrack's device blob carrying `zone` and no `HFTZN`.

    The blob is generated rather than pasted: a base64 constant nobody can read is
    exactly how a broken fixture gets in, and the chunk width is what the padding bug
    turned on — `atob` throws on a payload that was already a multiple of four and then
    had `==` stapled to it, and the failure is silent because the clock just stays UTC.
    """
    import base64
    import json as _json

    payload = base64.b64encode(
        _json.dumps({"os": {"timezone": zone, "type": "android"}}).encode()
    ).decode()
    records = [
        f"LXCTDEVICE {payload[at:at + 61]}" for at in range(0, len(payload), 61)
    ]
    lines = _surging_igc(timezone=False).split("\n")
    # After the headers, before the B records, which is where XCTrack writes them.
    return "\n".join(lines[:3] + records + lines[3:])


_PROBE = """
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
          var rows = article.querySelectorAll('.ql-table tbody tr[data-cursor]');
          out.climbs = rows.length;
          out.firstStart = rows.length
            ? rows[0].children[1].textContent : null;
          out.body = article.querySelector('.ql-table tbody').textContent.slice(0, 60);
        }
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


_RULES_RE = re.compile(
    r'(<script type="application/json" id="ql-constants">)(.*?)(</script>)', re.S
)


def _upload(igc: str, **rules) -> dict:
    page = render_html._page("probe", [])
    original = "'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'"
    assert original in page, "the DEM tile URL moved; this test rewrites it by hand"
    page = page.replace(original, json.dumps("about:blank#{z}/{x}/{y}"))
    if rules:
        # Rewriting the payload rather than the script is the whole point: if the page
        # still holds its own copy of a threshold, changing the payload changes nothing
        # and the test that depends on it fails.
        match = _RULES_RE.search(page)
        assert match, "the shared-constants payload is not in the page"
        patched = {**json.loads(match.group(2)), **rules}
        page = page[:match.start(2)] + json.dumps(patched) + page[match.end(2):]
    page += _PROBE % igc

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
class TestTheBrowserFindsTheClimbsPythonDoes:
    def test_a_climb_worked_in_surges_is_still_a_climb(self):
        """"No climbs met the thresholds" on a flight that plainly had some."""
        answer = _upload(_surging_igc())
        assert answer["uploaded"] is True
        assert answer["climbs"] >= 1, (
            f"the browser found no climbs in a surging climb: {answer['body']!r}")

    def test_python_agrees_that_there_is_a_climb_there(self):
        """The fixture has to be one the reference implementation accepts, or the test
        above is only asserting that a looser rule is looser."""
        import tempfile as tf

        from tracklog_viewer import analysis, igc

        with tf.TemporaryDirectory() as folder:
            path = Path(folder) / "surge.igc"
            path.write_text(_surging_igc(), encoding="utf-8")
            found = analysis.analyse(igc.parse(path))
        assert len(found.thermals) >= 1, (
            "the fixture does not contain a climb by the Python rule either")


class TestTheThresholdsComeFromPython:
    """The other half of the documented gap: the page had its own copies of these.

    `debrief.THRESHOLDS` was already serialised beside the debrief; what was missing was
    the analysis constants and a reader for either. The Python check below is the cheap
    one — it says the payload carries what the modules say. The browser check is the one
    that matters: it moves a number in the payload only, and the page has to change its
    answer, which it cannot do if it is still reading a literal.
    """

    def test_the_payload_is_the_modules_own_numbers(self):
        from tracklog_viewer import analysis, debrief, flight, quicklook

        rules = quicklook.constants()
        assert rules["window"] == flight.WINDOW
        assert rules["glideProgress"] == analysis.GLIDE_PROGRESS
        assert rules["minThermalSeconds"] == analysis.MIN_THERMAL_SECONDS
        assert rules["minThermalGain"] == analysis.MIN_THERMAL_GAIN
        assert rules["minGlideSeconds"] == analysis.MIN_GLIDE_SECONDS
        assert rules["condenseThermal"] == analysis.CONDENSE_THERMAL
        assert rules["thermalSlowKmh"] == analysis.THERMAL_SLOW_KMH
        assert rules["turnResolutionLimit"] == analysis.TURN_RESOLUTION_LIMIT
        assert rules["thresholds"] is debrief.THRESHOLDS

    def test_the_page_carries_the_payload(self):
        from tracklog_viewer import quicklook

        assert 'id="ql-constants"' in quicklook.panel()
        assert "RULES.minThermalGain" in quicklook.SCRIPT

    @needs_chrome
    def test_moving_a_threshold_in_the_payload_moves_the_page(self):
        """A gain floor no climb can clear, changed nowhere but in the payload."""
        answer = _upload(_surging_igc(), minThermalGain=100000)
        assert answer["uploaded"] is True
        assert answer["climbs"] == 0, (
            "the page found climbs under a 100 km gain floor, so it is not reading the "
            f"shared thresholds: {answer['body']!r}")
        assert "No climbs met the thresholds" in answer["body"]


@needs_chrome
class TestTheClockIsTheFlightsOwn:
    def test_the_logger_header_moves_the_clock_off_utc(self):
        answer = _upload(_surging_igc())
        assert answer["firstStart"], "no climb row to read a time from"
        hour = int(answer["firstStart"].split(":")[0])
        assert hour >= 12 + TZ_HOURS, (
            f"the climb starts at {answer['firstStart']} — the +{TZ_HOURS} header was "
            "ignored and the table is printing UTC")

    def test_without_a_header_the_clock_stays_where_it_was(self):
        """A KML carries no timezone at all, so UTC is the honest fallback rather than
        a guess from the reader's own machine — which would differ per reader."""
        answer = _upload(_surging_igc(timezone=False))
        assert answer["firstStart"], "no climb row to read a time from"
        assert int(answer["firstStart"].split(":")[0]) == 12

    def test_xctrack_hides_its_zone_in_a_base64_blob_and_it_is_read(self):
        """XCTrack writes no `HFTZN`. It writes an IANA name into a JSON blob split
        across dozens of `L` records instead, and `Intl` speaks IANA — so the browser
        can do what `igc.py` does, and a named zone beats a fixed offset because it
        knows the day's daylight saving.

        `Europe/Prague` is UTC+2 in July, so the answer is the same 14:00 the plain
        header gives, reached by a different route.
        """
        answer = _upload(_device_igc("Europe/Prague"))
        assert answer["firstStart"], "no climb row to read a time from"
        assert int(answer["firstStart"].split(":")[0]) == 12 + TZ_HOURS, (
            f"the climb starts at {answer['firstStart']} — the device blob was not read")

    def test_a_zone_the_browser_does_not_know_falls_back_rather_than_throwing(self):
        """Everything in that blob is someone else's data: bad base64, no `os.timezone`,
        a name Intl rejects. Each of those has to end in UTC, not in a page that fails
        to load — the timezone is the least important thing on it."""
        answer = _upload(_device_igc("Mars/Olympus_Mons"))
        assert answer["uploaded"] is True, "an unknown zone stopped the page building"
        assert int(answer["firstStart"].split(":")[0]) == 12

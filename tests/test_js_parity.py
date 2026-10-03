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


@needs_node
def test_a_ridge_climb_matches_too(tmp_path):
    """A beat flown 100 m over a steep slope, so the ridge rule fires on both sides."""
    import numpy as np

    from tracklog_viewer.terrain import Terrain

    def slope_under(flight):
        west, east = float(flight.lon.min()) - 0.02, float(flight.lon.max()) + 0.02
        south, north = float(flight.lat.min()) - 0.02, float(flight.lat.max()) + 0.02
        lon = np.linspace(west, east, 80)[None, :]
        lat = np.linspace(north, south, 60)[:, None]
        # A face rising 30 m per 100 m eastwards, set so the beat sits ~100 m over it.
        z = 950.0 + (lon - (west + east) / 2) * 111000 * 0.3 + 0 * lat
        return Terrain(west, east, south, north, np.round(z, 1))

    path = build(tmp_path / "ridge.igc", beat(500, bearing=0.0, climb=0.6))
    [(_, result)] = js_parity.compare([path], terrain=slope_under)
    assert result == [], result if isinstance(result, str) else "\n".join(result[:20])
    from tracklog_viewer import igc, insolation
    from tracklog_viewer.analysis import analyse
    flight = igc.parse(path)
    labels = {s.label for s in insolation.sources(analyse(flight), slope_under(flight)).values()}
    assert "ridge" in labels, "the fixture no longer reaches the ridge rule"


@needs_node
def test_a_declared_task_matches_too(tmp_path):
    """C records along the route, the last turnpoint well past where the flight went, so
    the plan's departure and turnpoint findings run on both sides."""
    from tests.test_analysis import to_latlon

    points = FLIGHTS["thermal-glide-thermal"]()
    path = build(tmp_path / "task.igc", points)

    def c_record(x, y, name):
        lat, lon = to_latlon(x, y)
        la, lo = int(lat), int(lon)
        return (f"C{la:02d}{round((lat - la) * 60000):05d}N"
                f"{lo:03d}{round((lon - lo) * 60000):05d}E{name}")

    task = [c_record(0, 0, "Launch"), c_record(points[600][1], points[600][2], "Glide end"),
            c_record(points[-1][1] + 9000, points[-1][2] + 9000, "Goal")]
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:4] + task + lines[4:]) + "\n")

    [(_, result)] = js_parity.compare([path])
    assert result == [], result if isinstance(result, str) else "\n".join(result[:20])
    from tracklog_viewer import igc, plan
    from tracklog_viewer.analysis import analyse
    flight = igc.parse(path)
    assert plan.describes(analyse(flight), plan.from_flight(flight)), "the task no longer fits the flight"


@needs_node
def test_kml_and_kmz_match_too(tmp_path):
    """Both shapes a KML comes in — gx:Track, and timed placemarks inside a KMZ — read
    into the same flight on both sides, and a KML with no times refused on both."""
    import datetime as dt
    import zipfile

    from tests.test_analysis import to_latlon

    points = FLIGHTS["thermal-glide-thermal"]()[::3]
    base = dt.datetime(2026, 7, 1, 10, 0, 0, tzinfo=dt.timezone.utc)

    def stamp(seconds):
        return (base + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")

    whens = "".join(f"<when>{stamp(t)}</when>" for t, *_ in points)
    coords = "".join(f"<gx:coord>{to_latlon(x, y)[1]:.6f} {to_latlon(x, y)[0]:.6f} {alt:.1f}</gx:coord>"
                     for _, x, y, alt in points)
    track = (f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2" '
             f'xmlns:gx="http://www.google.com/kml/ext/2.2"><Document><name>Test &amp; track</name>'
             f'<Placemark><gx:Track>{whens}{coords}</gx:Track></Placemark></Document></kml>')
    (tmp_path / "track.kml").write_text(track, encoding="utf-8")

    marks = "".join(
        f"<Placemark><TimeStamp><when>{stamp(t)}</when></TimeStamp><Point><coordinates>"
        f"{to_latlon(x, y)[1]:.6f},{to_latlon(x, y)[0]:.6f},{alt:.0f}</coordinates></Point></Placemark>"
        for t, x, y, alt in points)
    placemarks = (f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Marks</name>'
                  f'{marks}</Document></kml>')
    with zipfile.ZipFile(tmp_path / "marks.kmz", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", placemarks)

    (tmp_path / "line.kml").write_text(
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><LineString><coordinates>'
        '14,46,1000 14.1,46.1,900</coordinates></LineString></Placemark></kml>', encoding="utf-8")

    for name in ("track.kml", "marks.kmz", "line.kml"):
        [(_, result)] = js_parity.compare([tmp_path / name])
        assert result == [], (name, result if isinstance(result, str) else "\n".join(result[:20]))


@needs_node
def test_the_glider_class_lookup_matches(tmp_path):
    """The page's lookup against Python's, over every name in both registers and the ways
    a logger writes them: case, a size left off, a number run into the name, no brand.
    The answers themselves come from `certification.compact()`; what is compared is the
    half the page runs — turning a header into a key."""
    import json
    import re
    import subprocess

    from tracklog_viewer import certification
    from tracklog_viewer.gliders import GLIDERS

    names = {"", "OZONE", "Ozone Zeolite 2", "GIN GLIDERS Bonanza 2", "Advance Sigma 10",
             "SKY PARAGLIDERS Apollo", "Apollo", "Rush 6", "Nova Mentor 7 &amp; light"}
    for row in GLIDERS:
        n = row[0]
        names.update({n, n.upper(), re.sub(r"\s+\S+$", "", n), re.sub(r"\s+(\d)", r"\1", n),
                      " ".join(n.split()[1:])})
    names = sorted(names)
    want = [None if (w := certification.lookup(n)) is None else
            {"label": w.label, "name": w.name, "certificate": w.certificate, "source": w.source}
            for n in names]
    runner = tmp_path / "lookup.js"
    runner.write_text(
        "global.TV = {};\n"
        f"require({json.dumps(str(js_parity.RUNNER.parent / 'certification.js'))});\n"
        "var input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
        "process.stdout.write(JSON.stringify(input.names.map(function (n) {"
        " return TV.certification.lookup(n, input.table); })));\n")
    got = json.loads(subprocess.run(
        ["node", str(runner)], input=json.dumps({"names": names, "table": certification.compact()}),
        capture_output=True, text=True, check=True).stdout)
    differ = [(n, a, b) for n, a, b in zip(names, want, got) if a != b]
    assert not differ, differ[:5]
    assert sum(w is not None for w in want) > 1000, "the lookup stopped answering"


def test_differences_are_reported_by_path():
    """The comparison itself: a mismatch names where it is and what each side said."""
    assert js_parity.differences({"a": [1, 2.0]}, {"a": [1, 2.0]}) == []
    assert js_parity.differences({"a": [1, 2.0]}, {"a": [1, 2.1]}) == [".a[1]: 2.0 != 2.1"]
    assert js_parity.differences({"a": None}, {"a": 0}) == [".a: None != 0"]
    assert js_parity.differences({"a": 1}, {}) == [".a: only in python"]

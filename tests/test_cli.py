"""The CLI builds the page; the JavaScript writes what is in it.

`cli` reads the inputs, asks the JavaScript what each flight needs (`js_build.inspect`),
fetches it, finds a plan, and has the JavaScript write the articles (`js_build.render`)
with `TV.upload.compose` — the function an uploaded track goes through in the page. No
network here: the ground and the weather are stubbed where a test needs them.
"""

import json
import re

import numpy as np
import pytest

from tests.flights import FLIGHTS
from tests.js import needs_node
from tests.test_analysis import LAT0, LON0, build
from tracklog_viewer import cli, js_build
from parainsights_map import terrain as terrain_module

pytestmark = needs_node


def _articles(page: str) -> dict:
    out = {}
    for m in re.finditer(r'<article class="flight[^"]*"[^>]*data-flight-report="(f\d)"', page):
        rest = page[m.end():]
        end = re.search(r'<article class="flight[^"]*"[^>]*data-flight-report="(f\d|own)"', rest)
        out[m.group(1)] = page[m.start(): m.end() + (end.start() if end else len(rest))]
    return out


def _flights(tmp_path, *names):
    return [build(tmp_path / f"{name}.igc", FLIGHTS[name]()) for name in names]


def test_the_page_is_written_by_the_uploads_javascript(tmp_path, capsys):
    flights = _flights(tmp_path, "thermal-glide-thermal", "tow-then-thermal")
    page = tmp_path / "out" / "index.html"
    assert cli.main([*map(str, flights), "--label", "Ana Bell|Ridge|", "--label", "",
                     "--html", str(page)]) == 0
    text = page.read_text()
    articles = _articles(text)
    assert sorted(articles) == ["f0", "f1"]
    assert "hidden" not in articles["f0"].split(">", 1)[0] and "hidden" in articles["f1"].split(">", 1)[0]
    # The label override reached the article and the tab, not only one of them.
    assert "Ana Bell" in articles["f0"] and "Ridge" in articles["f0"]
    tabs = re.search(r'<nav class="tabs".*?</nav>', text, re.S).group(0)
    # The tab names the place first, then the date and the pilot.
    assert "Ridge" in tabs and "· Ana" in tabs
    assert "TV.upload" in text, "the page carries the same JavaScript for an upload"
    assert (page.parent / "gliders.json").exists()
    # One line a flight on the console, from the JavaScript's own tab text.
    out = capsys.readouterr().out
    assert "Ridge" in out and "· Ana" in out


def test_a_file_the_javascript_refuses_stops_the_build(tmp_path, capsys):
    """Not a page with a hole in it: a build that cannot read a flight the way an upload
    would is a build that would publish something else."""
    bad = tmp_path / "bad.igc"
    bad.write_text("AXXX\nHFDTE010120\n", encoding="utf-8")
    page = tmp_path / "index.html"
    assert cli.main([str(bad), "--html", str(page)]) == 2
    assert "no valid B records" in capsys.readouterr().err
    assert not page.exists()


def test_ground_and_weather_are_handed_to_the_javascript(tmp_path, monkeypatch):
    """What the JavaScript asked for is what is fetched, and what is fetched reaches the
    article: the box `TV.terrain.remoteFor` named, and the request `TV.meteo.request`
    built."""
    asked = {}

    def ground(west, east, south, north, *, cols, max_points, report=None):
        asked["box"] = (west, east, south, north, cols, max_points)
        rows = max_points // cols
        return terrain_module.Terrain(west=west, east=east, south=south, north=north,
                                      elevations=np.full((rows, cols), 300.0))

    def weather(url):
        asked["url"] = url
        return None

    monkeypatch.setattr(terrain_module, "fetch", ground)
    monkeypatch.setattr(cli, "_weather", weather)
    [flight] = _flights(tmp_path, "thermal-glide-thermal")
    page = tmp_path / "index.html"
    assert cli.main([str(flight), "--terrain", "--meteo", "--html", str(page)]) == 0

    west, east, south, north, cols, _ = asked["box"]
    assert west < LON0 < east and south < LAT0 < north and cols <= 480
    assert "open-meteo.com" in asked["url"] and "latitude=49" in asked["url"]
    article = _articles(page.read_text())["f0"]
    scene = json.loads(re.search(r'class="view3d-data"[^>]*>(.*?)</script>', article, re.S).group(1))
    # The page fetches the heights itself: the box goes in, not the grid.
    assert scene["terrain"]["remote"] and "z" not in scene["terrain"]


class TestPlanDiscovery:
    """Where a plan is found, in order: --plan, a sidecar beside the tracklog, one
    remembered for the date and site. Reading it is the page's (`js/plan.js`)."""

    def _track(self, tmp_path):
        track = tmp_path / "flight.igc"
        track.write_text("x", encoding="utf-8")
        return track

    def test_a_sidecar_beside_the_track_is_found(self, tmp_path):
        track = self._track(tmp_path)
        (tmp_path / "flight.plan.json").write_text('{"goal_distance": 5}', encoding="utf-8")
        found = cli._plan_payload(track, "2026-07-01", None, None, remembered=tmp_path / "nope")
        assert found == {"payload": {"goal_distance": 5}, "source": "sidecar"}

    def test_an_explicit_plan_wins(self, tmp_path):
        track = self._track(tmp_path)
        (tmp_path / "flight.plan.json").write_text('{"goal_distance": 5}', encoding="utf-8")
        mine = tmp_path / "mine.json"
        mine.write_text('{"goal_distance": 9}', encoding="utf-8")
        found = cli._plan_payload(track, "2026-07-01", None, mine, remembered=tmp_path / "nope")
        assert found["payload"]["goal_distance"] == 9

    def test_a_remembered_plan_is_found_by_date_and_site(self, tmp_path):
        track = self._track(tmp_path)
        plans = tmp_path / "plans"
        plans.mkdir()
        (plans / "2026-07-01-Col-Rodella.json").write_text('{"notes": "x"}', encoding="utf-8")
        found = cli._plan_payload(track, "2026-07-01", "Col Rodella", None, remembered=plans)
        assert found == {"payload": {"notes": "x"}, "source": "remembered"}

    def test_a_broken_sidecar_is_not_fatal(self, tmp_path):
        track = self._track(tmp_path)
        (tmp_path / "flight.plan.json").write_text("{not json", encoding="utf-8")
        assert cli._plan_payload(track, "2026-07-01", None, None, remembered=tmp_path / "nope") is None

    def test_nothing_to_discover_is_not_an_error(self, tmp_path):
        assert cli._plan_payload(self._track(tmp_path), "2026-07-01", None, None,
                                 remembered=tmp_path / "nope") is None


def test_the_javascript_refuses_by_name(tmp_path):
    """`js_build` reports which file, so a build of twenty flights says which one."""
    bad = tmp_path / "broken.igc"
    bad.write_text("AXXX\n", encoding="utf-8")
    with pytest.raises(js_build.BuildError, match="broken.igc"):
        js_build.inspect([{"path": str(bad), "name": "broken.igc", "label": ""}], now=0)

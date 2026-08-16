"""Terrain grid arithmetic and the 3D payload. No network: the grid is synthetic."""

import urllib.error

import numpy as np
import pytest

from tracklog_viewer import terrain as terrain_module
from tracklog_viewer import terrain
from tracklog_viewer.terrain import Terrain


@pytest.fixture
def ramp():
    """A 3×3 grid rising from 100 m in the south-west to 500 m in the north-east."""
    elevations = np.array(
        [
            [300.0, 400.0, 500.0],  # north row
            [200.0, 300.0, 400.0],
            [100.0, 200.0, 300.0],  # south row
        ]
    )
    return Terrain(west=14.0, east=15.0, south=49.0, north=50.0, elevations=elevations)


class TestSampling:
    def test_corners_are_exact(self, ramp):
        assert ramp.at(50.0, 14.0) == pytest.approx(300)  # north-west
        assert ramp.at(50.0, 15.0) == pytest.approx(500)  # north-east
        assert ramp.at(49.0, 14.0) == pytest.approx(100)  # south-west
        assert ramp.at(49.0, 15.0) == pytest.approx(300)  # south-east

    def test_centre_interpolates(self, ramp):
        assert ramp.at(49.5, 14.5) == pytest.approx(300)

    def test_quarter_point_is_bilinear(self, ramp):
        # A quarter east and a quarter north of the south-west corner.
        assert ramp.at(49.25, 14.25) == pytest.approx(200)

    def test_outside_the_box_clamps(self, ramp):
        assert ramp.at(60.0, 20.0) == pytest.approx(500)
        assert ramp.at(40.0, 10.0) == pytest.approx(100)

    def test_vectorised(self, ramp):
        lat = np.array([50.0, 49.0])
        lon = np.array([14.0, 15.0])
        assert list(ramp.at(lat, lon)) == pytest.approx([300, 300])


class TestSerialisation:
    def test_payload_shape(self, ramp):
        data = ramp.to_dict()
        assert data["rows"] == 3 and data["cols"] == 3
        assert len(data["z"]) == 9  # flat list, row-major from the north
        assert data["z"][0] == 300
        assert data["min"] == 100 and data["max"] == 500

    def test_elevations_are_integers_for_size(self, ramp):
        assert all(isinstance(v, int) for v in ramp.to_dict()["z"])


class TestZoomChoice:
    def test_small_area_gets_high_zoom(self):
        assert terrain_module._choose_zoom(14.0, 14.05, 49.0, 49.05) == 12

    def test_large_area_backs_off(self):
        big = terrain_module._choose_zoom(10.0, 20.0, 45.0, 52.0)
        small = terrain_module._choose_zoom(14.0, 14.05, 49.0, 49.05)
        assert big < small

    def test_tile_budget_is_respected(self):
        import math

        for box in ((14.0, 15.1, 49.4, 49.5), (5.0, 18.0, 44.0, 52.0)):
            zoom = terrain_module._choose_zoom(*box)
            x0, y0 = terrain_module._tile_indices(box[3], box[0], zoom)
            x1, y1 = terrain_module._tile_indices(box[2], box[1], zoom)
            tiles = (int(x1) - int(x0) + 1) * (int(y1) - int(y0) + 1)
            assert tiles <= terrain_module.MAX_TILES or zoom == 6
            assert not math.isnan(tiles)


class TestClearance:
    def test_clearance_uses_gps_altitude(self, ramp, tmp_path):
        from tracklog_viewer import igc
        from tracklog_viewer.analysis import analyse

        # Two fixes over the middle of the ramp (ground 300 m), flying at 1300 m GPS
        # with a baro trace offset well away from it.
        text = "AXCT1\nHFDTE010726\n"
        for second in range(80):
            minute, sec = divmod(second, 60)
            text += f"B12{minute:02d}{sec:02d}4930000N01430000EA00800{1300:05d}\n"
        path = tmp_path / "f.igc"
        path.write_text(text, encoding="utf-8")
        analysis = analyse(igc.parse(path))
        clearance = terrain_module.clearance(ramp, analysis)
        # Ground under 49.5,14.5 is 300 m, so clearance is ~1000 m — computed from
        # GPS altitude (1300), not the 800 m pressure altitude.
        assert clearance[0] == pytest.approx(1000, abs=5)


def _fake_basemap():
    from tracklog_viewer.basemap import Basemap

    return Basemap(
        west=14.0, east=15.0, south=49.0, north=50.0, zoom=12,
        data_uri="data:image/jpeg;base64,AA==", width=256, height=256,
        attribution="Imagery © Esri",
    )


class TestView3dPayload:
    def test_payload_contains_terrain_track_and_climbs(self, ramp, tmp_path):
        from tracklog_viewer import igc, view3d
        from tracklog_viewer.analysis import analyse
        from tests.test_analysis import build, circling

        flight = igc.parse(build(tmp_path / "t.igc", circling(200)))
        analysis = analyse(flight)
        payload = view3d.data(analysis, ramp)
        assert payload["terrain"]["rows"] == 3
        assert len(payload["track"]["lon"]) == len(payload["track"]["alt"])
        assert len(payload["track"]["c"]) == len(payload["track"]["lon"])
        assert payload["trackTop"] >= max(payload["track"]["alt"])
        assert payload["climbs"], "the synthetic circling flight is a climb"
        assert all(0 <= i < len(payload["palette"]) for i in payload["track"]["c"])
        assert all(len(colour) == 3 for colour in payload["palette"])

    def test_a_style_is_either_embedded_or_fetched_never_both(self, ramp, tmp_path):
        """A published page cannot fetch a tile, so every style the button offers has to
        be in the document. Tile templates are only for the styles that are not."""
        from tracklog_viewer import igc, view3d
        from tracklog_viewer.analysis import analyse
        from tests.test_analysis import build, circling

        analysis = analyse(igc.parse(build(tmp_path / "t.igc", circling(200))))

        runtime = view3d.data(analysis, ramp)
        assert runtime["basemaps"] == {}
        assert set(runtime["tiles"]) == {"satellite", "map"}

        one = view3d.data(analysis, ramp, basemaps={"satellite": _fake_basemap()})
        assert set(one["basemaps"]) == {"satellite"}
        assert set(one["tiles"]) == {"map"}, "the style we have must not be re-fetched"

        both = view3d.data(analysis, ramp, basemaps={
            "satellite": _fake_basemap(), "map": _fake_basemap(),
        })
        assert set(both["basemaps"]) == {"satellite", "map"}
        assert both["tiles"] is None

    def test_the_basemap_control_shows_which_style_is_on(self, ramp, tmp_path):
        """This replaces a test that asserted the *cycle* button relabelled itself.

        Naming what is on screen is right for a two-state toggle and wrong for three:
        with a cycle you cannot see the options, cannot tell how many presses reach the
        one you want, and cannot jump. The segmented control answers the same question —
        which style am I looking at — by pressing the segment instead, which is also what
        lets the keyboard address a style directly.
        """
        import re

        from tests.test_analysis import build, circling
        from tracklog_viewer import igc, view3d
        from tracklog_viewer.analysis import analyse

        analysis = analyse(igc.parse(build(tmp_path / "t.igc", circling(200))))
        markup = view3d.panel(view3d.data(analysis, ramp), "x")

        segments = re.findall(
            r'data-view3d-act="basemap-set" data-style="(\w+)" aria-pressed="(\w+)"',
            markup,
        )
        assert segments, "no basemap segments in the panel"
        pressed = [style for style, on in segments if on == "true"]
        assert pressed == ["satellite"], f"expected satellite pressed, got {pressed}"
        # Every style the document can show, plus bare relief.
        assert "off" in [style for style, _ in segments]

    def test_cursor_track_matches_sample_length(self, ramp, tmp_path):
        from tracklog_viewer import igc, view3d
        from tracklog_viewer.analysis import analyse
        from tests.test_analysis import build, circling

        analysis = analyse(igc.parse(build(tmp_path / "t.igc", circling(200))))
        sample = [0, 10, 20, 30]
        cursor = view3d.cursor_track(analysis, sample)
        assert len(cursor["lon"]) == len(sample)
        assert len(cursor["alt"]) == len(sample)


class TestASilentFailureIsNotAFailureReport:
    """A missing DEM is never an error here — the airspace map falls back to a flat one,
    the planner declines to draw, an uploaded track gets a flat plane. What was missing
    was the *sentence*: `fetch` swallowed the cause, so a deploy could say "terrain
    unavailable" twice in a row and nobody could tell whether the tile host was blocked,
    slow, or simply not answering. Two published pages lost their 3D view to that.

    No network: `urlopen` is replaced, and the cache is pointed at nothing.
    """

    @pytest.fixture(autouse=True)
    def _no_tiles(self, tmp_path, monkeypatch):
        monkeypatch.setattr(terrain, "CACHE", tmp_path / "empty")

    def _refuse(self, monkeypatch, error):
        def blow_up(request, timeout=None):
            raise error
        monkeypatch.setattr(terrain.urllib.request, "urlopen", blow_up)

    def test_it_names_the_cause_the_host_and_how_many_tiles(self, monkeypatch):
        self._refuse(monkeypatch, urllib.error.URLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"))
        said = []
        assert terrain.fetch(14.0, 14.4, 50.0, 50.3, report=said.append) is None
        assert len(said) == 1
        line = said[0]
        assert "0 of" in line and "tiles" in line
        assert "s3.amazonaws.com" in line, "a reader cannot check a host that is unnamed"
        assert "CERTIFICATE_VERIFY_FAILED" in line
        assert "URLError" in line, (
            "the exception class matters: URLError around an SSL failure and URLError "
            "around a refused connection are different problems with different fixes")

    def test_two_failures_read_differently(self, monkeypatch):
        """The whole point. If every cause produced the same line there would be no
        reason to have added one."""
        seen = []
        for error in (urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] nope"),
                      urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))):
            self._refuse(monkeypatch, error)
            said = []
            terrain.fetch(14.0, 14.4, 50.0, 50.3, report=said.append)
            seen.append(said[0])
        assert seen[0] != seen[1]

    def test_one_reason_is_reported_once_however_many_tiles_fail(self, monkeypatch):
        """Twenty tiles failing the same way is one fact, not twenty lines of log."""
        self._refuse(monkeypatch, urllib.error.URLError("the same thing every time"))
        said = []
        terrain.fetch(12.0, 19.0, 48.5, 51.0, report=said.append)
        assert len(said) == 1
        assert said[0].count("the same thing every time") == 1

    def test_without_a_reporter_it_is_as_quiet_as_it_ever_was(self, monkeypatch):
        """The callback is opt-in: every existing caller that does not pass one keeps
        the behaviour it was written against, which is a `None` and no output."""
        self._refuse(monkeypatch, urllib.error.URLError("boom"))
        assert terrain.fetch(14.0, 14.4, 50.0, 50.3) is None

    def test_a_partly_fetched_mosaic_says_so_and_still_builds(self, monkeypatch):
        """A missing edge tile does not punch a hole in the mesh — that is deliberate,
        and it is also worth one line, because a grid built from half its tiles is a
        grid whose edges are made up."""
        import numpy as np

        real = [0]

        def one_tile_only(zoom, x, y, *, problems=None):
            if real[0]:
                terrain._note(problems, "URLError: gave up on the rest")
                return None
            real[0] = 1
            return np.full((terrain.TILE_SIZE, terrain.TILE_SIZE), 500.0)

        monkeypatch.setattr(terrain, "_fetch_tile", one_tile_only)
        said = []
        grid = terrain.fetch(12.0, 19.0, 48.5, 51.0, report=said.append)
        assert grid is not None, "one good tile is still a mesh"
        assert len(said) == 1 and said[0].startswith("terrain: 1 of ")

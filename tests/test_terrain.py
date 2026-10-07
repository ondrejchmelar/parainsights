"""Terrain grid arithmetic and the 3D payload. No network: the grid is synthetic."""

import urllib.error

import numpy as np
import pytest

from tests import js
from tests.js import needs_node
from parainsights_map import terrain
from parainsights_map.terrain import Terrain


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


@needs_node
class TestSampling:
    """Bilinear ground under a point, as the page samples it (`TV.terrain.at`)."""

    def at(self, ramp, *points):
        return js.run("return input.points.map(function (p) { return TV.terrain.at(input.grid, p[0], p[1]); });",
                      grid=_grid(ramp), points=[list(p) for p in points])

    def test_corners_are_exact(self, ramp):
        corners = self.at(ramp, (50.0, 14.0), (50.0, 15.0), (49.0, 14.0), (49.0, 15.0))
        assert list(corners) == pytest.approx([300, 500, 100, 300])  # NW, NE, SW, SE

    def test_centre_interpolates(self, ramp):
        assert self.at(ramp, (49.5, 14.5))[0] == pytest.approx(300)

    def test_quarter_point_is_bilinear(self, ramp):
        # A quarter east and a quarter north of the south-west corner.
        assert self.at(ramp, (49.25, 14.25))[0] == pytest.approx(200)

    def test_outside_the_box_clamps(self, ramp):
        assert list(self.at(ramp, (60.0, 20.0), (40.0, 10.0))) == pytest.approx([500, 100])


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
        assert terrain._choose_zoom(14.0, 14.05, 49.0, 49.05) == 12

    def test_large_area_backs_off(self):
        big = terrain._choose_zoom(10.0, 20.0, 45.0, 52.0)
        small = terrain._choose_zoom(14.0, 14.05, 49.0, 49.05)
        assert big < small

    def test_tile_budget_is_respected(self):
        import math

        for box in ((14.0, 15.1, 49.4, 49.5), (5.0, 18.0, 44.0, 52.0)):
            zoom = terrain._choose_zoom(*box)
            x0, y0 = terrain._tile_indices(box[3], box[0], zoom)
            x1, y1 = terrain._tile_indices(box[2], box[1], zoom)
            tiles = (int(x1) - int(x0) + 1) * (int(y1) - int(y0) + 1)
            assert tiles <= terrain.MAX_TILES or zoom == 6
            assert not math.isnan(tiles)


def _grid(terrain_):
    from tracklog_viewer import js_build
    return js_build.grid(terrain_)


@needs_node
class TestClearance:
    def test_clearance_uses_gps_altitude(self, ramp, tmp_path):
        # Fixes over the middle of the ramp (ground 300 m), flying at 1300 m GPS with a
        # baro trace offset well away from it.
        text = "AXCT1\nHFDTE010726\n"
        for second in range(80):
            minute, sec = divmod(second, 60)
            text += f"B12{minute:02d}{sec:02d}4930000N01430000EA00800{1300:05d}\n"
        path = tmp_path / "f.igc"
        path.write_text(text, encoding="utf-8")
        clearance = js.run("return TV.terrain.clearance(input.grid, TV.analysis.analyse(await load(input.path)));",
                           path=path, grid=_grid(ramp))
        # Ground under 49.5,14.5 is 300 m, so clearance is ~1000 m — computed from
        # GPS altitude (1300), not the 800 m pressure altitude.
        assert clearance[0] == pytest.approx(1000, abs=5)


@needs_node
class TestView3dPayload:
    """The scene a flight's 3D panel is drawn from (`js/scene.js`)."""

    def _scene(self, ramp, tmp_path, options=None):
        from tests.test_analysis import build, circling
        return js.run("""var a = TV.analysis.analyse(await load(input.path));
          var scene = TV.scene.data(a, input.grid, input.options || {});
          return { scene: scene, panel: TV.scene.panel(scene, 'x', {}),
                   cursor: TV.report.cursorData(a).alt.length, sample: TV.report.sampleIndices(a).length };""",
                      path=build(tmp_path / "t.igc", circling(200)), grid=_grid(ramp), options=options)

    def test_payload_contains_terrain_track_and_climbs(self, ramp, tmp_path):
        payload = self._scene(ramp, tmp_path).scene
        assert payload["terrain"]["rows"] == 3
        assert len(payload["track"]["lon"]) == len(payload["track"]["alt"])
        assert len(payload["track"]["c"]) == len(payload["track"]["lon"])
        assert payload["trackTop"] >= max(np.cumsum(payload["track"]["alt"]))
        assert payload["climbs"], "the synthetic circling flight is a climb"
        assert all(0 <= i < len(payload["palette"]) for i in payload["track"]["c"])
        assert all(len(colour) == 3 for colour in payload["palette"])

    def test_the_track_is_every_fix_to_the_same_precision(self, ramp, tmp_path):
        """Delta-encoded to halve its bytes, and nothing lost: the running sums are each
        fix's coordinates at 1e-5°, its altitude and its time, exactly."""
        from tests.test_analysis import build, circling
        out = js.run("""var f = await load(input.path), a = TV.analysis.analyse(f);
          return { scene: TV.scene.data(a, input.grid, {}), lon: f.lon, lat: f.lat, t: a.series.t };""",
                     path=build(tmp_path / "enc.igc", circling(120)), grid=_grid(ramp))
        track = out.scene["track"]
        assert track["enc"] == 1e5
        assert list(np.cumsum(track["lon"])) == [round(v * 1e5) for v in out.lon]
        assert list(np.cumsum(track["lat"])) == [round(v * 1e5) for v in out.lat]
        assert list(np.cumsum(track["t"])) == [int(v) for v in out.t]
        # Mostly one or two characters a step at 1 Hz, which is the whole saving.
        assert max(abs(v) for v in track["lon"][1:]) < 100

    def test_the_airspace_is_loaded_by_the_page(self, ramp, tmp_path):
        """A page with airspace offers it on every flight: the map loads the layers under
        its ground (`loadAirspace`) and its switch then draws them or says why not
        (`settleAirspace`). The rings are not in the scene: a monthly refresh reaches
        every flight without a rebuild."""
        out = self._scene(ramp, tmp_path, {"airspaceRemote": "airspace/layers/"})
        assert out.scene["airspaceRemote"] == "airspace/layers/"
        assert out.scene["airspaceToggle"] is True and out.scene["airspaces"] == []
        plain = self._scene(ramp, tmp_path)
        assert not plain.scene.get("airspaceToggle"), "no airspace on the page, no switch"

    def test_every_style_is_fetched_at_view_time(self, ramp, tmp_path):
        payload = self._scene(ramp, tmp_path).scene
        assert not payload.get("basemaps")
        assert set(payload["tiles"]) == {"satellite", "map"}

    def test_the_cursor_track_is_the_charts_own_sample(self, ramp, tmp_path):
        out = self._scene(ramp, tmp_path)
        assert out.cursor == out.sample


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


def test_the_valley_floor_is_the_lowest_ground_within_the_radius():
    """A ridge at 1 000 m with a valley at 200 m 1.5 km away: within 2 km of the ridge the
    floor is the valley's, and beyond the radius the ridge's own height again."""
    cols, rows = 41, 41          # 0.002° steps: about 222 m north-south, 146 m east-west
    z = []
    for r in range(rows):
        for c in range(cols):
            z.append(200 if c == 0 else 1000)
    grid = {"west": 14.0, "east": 14.08, "south": 49.0, "north": 49.08, "rows": rows, "cols": cols, "z": z}
    floor = js.run("return TV.terrain.valleyFloor(input.grid, 2000).z;", grid=grid)
    row = floor[20 * cols:21 * cols]
    assert row[0] == 200 and row[10] == 200, "1.5 km from the valley the floor is the valley's"
    assert row[14] == 200 and row[15] == 1000, "the radius is 2 km: 14 steps of 146 m, and no more"


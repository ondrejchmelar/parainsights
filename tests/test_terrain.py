"""Terrain grid arithmetic and the 3D payload. No network: the grid is synthetic."""

import numpy as np
import pytest

from tracklog_viewer import terrain as terrain_module
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

    def test_the_basemap_button_names_the_style_it_is_showing(self, ramp, tmp_path):
        from tracklog_viewer import igc, view3d
        from tracklog_viewer.analysis import analyse
        from tests.test_analysis import build, circling

        analysis = analyse(igc.parse(build(tmp_path / "t.igc", circling(200))))
        markup = view3d.panel(view3d.data(analysis, ramp), "x")
        button = markup[markup.index('data-view3d-act="basemap"'):]
        assert button[:button.index("</button>")].endswith(">Satellite")

    def test_cursor_track_matches_sample_length(self, ramp, tmp_path):
        from tracklog_viewer import igc, view3d
        from tracklog_viewer.analysis import analyse
        from tests.test_analysis import build, circling

        analysis = analyse(igc.parse(build(tmp_path / "t.igc", circling(200))))
        sample = [0, 10, 20, 30]
        cursor = view3d.cursor_track(analysis, sample)
        assert len(cursor["lon"]) == len(sample)
        assert len(cursor["alt"]) == len(sample)

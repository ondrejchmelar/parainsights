"""Insolation from the DEM, on slopes whose aspect is known by construction.

A synthetic ramp has one aspect everywhere, so "which way does this face" has an exact
answer and the sun can be put where its effect is unambiguous — a low sun in the west lights
a west-facing slope and leaves an east-facing one in shadow. That is the whole physics of
the module, and it is checkable without a real DEM.
"""


import numpy as np
import pytest

from tracklog_viewer import insolation, sun
from tracklog_viewer.terrain import Terrain


def ramp(direction: str, *, size: int = 41, relief: float = 800.0) -> Terrain:
    """A DEM that slopes one way. `direction` is the way the ground *faces* — downhill.

    Row 0 is north and column 0 is west, so "faces north" means high in the south, which
    is a large row index. The box is 0.05 degrees rather than 0.4: 800 m over 44 km is a
    one-degree slope, which has no meaningful aspect and is not what a pilot means by a
    face. Over 5.5 km the same relief gives 8 degrees.
    """
    up = np.linspace(0.0, 1.0, size)
    if direction == "west":        # high in the east
        grid = np.tile(up[None, :], (size, 1))
    elif direction == "east":      # high in the west
        grid = np.tile(up[::-1][None, :], (size, 1))
    elif direction == "north":     # high in the south, i.e. at large row indices
        grid = np.tile(up[:, None], (1, size))
    elif direction == "south":     # high in the north, i.e. at row 0
        grid = np.tile(up[::-1][:, None], (1, size))
    else:
        raise ValueError(direction)
    return Terrain(west=14.0, east=14.05, south=49.0, north=49.05,
                   elevations=grid * relief)


class TestAspect:
    @pytest.mark.parametrize("facing,expected", [
        ("south", 180.0), ("north", 0.0), ("west", 270.0), ("east", 90.0),
    ])
    def test_a_uniform_slope_has_the_aspect_it_was_built_with(self, facing, expected):
        overhead = sun.Position(azimuth=180.0, elevation=80.0)
        face = insolation.face_at(ramp(facing), overhead, 49.025, 14.025)

        assert face is not None
        offset = abs(((face.aspect - expected + 540) % 360) - 180)
        assert offset < 20.0, f"{facing} slope reported aspect {face.aspect}"
        assert face.slope > insolation.MIN_SLOPE

    def test_the_east_west_spacing_is_scaled_by_latitude(self):
        """The grid is regular in degrees, not metres. One spacing for both axes tilts
        every aspect towards the poles, which is a wrong answer that looks plausible."""
        overhead = sun.Position(azimuth=180.0, elevation=80.0)
        face = insolation.face_at(ramp("west"), overhead, 49.025, 14.025)
        assert face is not None
        assert abs(((face.aspect - 270.0 + 540) % 360) - 180) < 15.0


class TestInsolation:
    def test_a_low_western_sun_lights_a_west_face_and_shades_an_east_one(self):
        evening = sun.Position(azimuth=270.0, elevation=15.0)
        west = insolation.face_at(ramp("west"), evening, 49.025, 14.025)
        east = insolation.face_at(ramp("east"), evening, 49.025, 14.025)

        assert west is not None and east is not None
        assert west.insolation > east.insolation, (
            f"west {west.insolation} should beat east {east.insolation} at sunset"
        )
        assert east.insolation < 0.2

    def test_a_sun_below_the_horizon_lights_nothing(self):
        night = sun.Position(azimuth=270.0, elevation=-5.0)
        lit = insolation.grid(ramp("west"), night)
        assert float(lit.max()) == 0.0

    def test_insolation_never_goes_negative(self):
        """A face turned away is unlit, not negatively lit — otherwise it quietly
        subtracts from the neighbourhood mean the comparison is made against."""
        low = sun.Position(azimuth=90.0, elevation=10.0)
        lit = insolation.grid(ramp("west"), low)
        assert float(lit.min()) >= 0.0

    def test_relative_insolation_compares_with_the_ground_around_it(self):
        """0.8 means nothing on a day when every slope reads 0.8."""
        evening = sun.Position(azimuth=270.0, elevation=15.0)
        face = insolation.face_at(ramp("west"), evening, 49.025, 14.025)
        assert face is not None
        # A uniform ramp is its own neighbourhood, so nothing here is unusual.
        assert face.relative == pytest.approx(1.0, abs=0.15)


class TestTriggersAndWind:
    def _analysis(self, tmp_path):
        from tests.test_analysis import build, circling
        from tracklog_viewer import igc
        from tracklog_viewer.analysis import analyse

        return analyse(igc.parse(build(tmp_path / "t.igc", circling(400, climb=1.5))))

    def test_no_terrain_means_no_triggers(self, tmp_path):
        assert insolation.triggers(self._analysis(tmp_path), None) == []

    def test_windward_refuses_without_a_wind(self, tmp_path):
        analysis = self._analysis(tmp_path)
        analysis.wind = None
        assert insolation.windward(analysis, ramp("west")) is None

    def test_a_flat_grid_yields_no_face_worth_naming(self):
        flat = Terrain(west=14.0, east=14.05, south=49.0, north=49.05,
                       elevations=np.full((41, 41), 500.0))
        overhead = sun.Position(azimuth=180.0, elevation=60.0)
        face = insolation.face_at(flat, overhead, 49.025, 14.025)

        assert face is not None
        assert face.slope < insolation.MIN_SLOPE, "a flat grid has no meaningful aspect"

    def test_a_point_outside_the_grid_is_refused(self):
        overhead = sun.Position(azimuth=180.0, elevation=60.0)
        assert insolation.face_at(ramp("west"), overhead, 40.0, 14.02) is None

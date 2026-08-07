"""Slope, aspect and the sun on it — checked against geometry with a known answer.

Aspect is a convention stack with three chances to be wrong: the DEM's row 0 is the
*northern* edge, so a positive row step goes south; the compass runs clockwise from north
while `atan2` runs counter-clockwise from east; and the grid is in degrees, whose two
axes are different lengths on the ground. Each of those alone looks right, and together
they will happily rotate a south-west face into a north-east one. So the fixtures are
planes tilted in a known direction, and the assertions are the bearing they face.
"""

import math

import numpy as np
import pytest

from tracklog_viewer import insolation
from tracklog_viewer.terrain import Terrain


def plane(*, rise_north=0.0, rise_east=0.0, size=21, span=0.02, lat=49.0):
    """A tilted plane. `rise_north` metres gained per grid step going north."""
    rows = np.arange(size)[:, None]
    cols = np.arange(size)[None, :]
    # Row 0 is the northern edge, so northing decreases with the row index.
    z = 1000.0 + rise_north * (size - 1 - rows) + rise_east * cols
    return Terrain(west=14.0, east=14.0 + span, south=lat, north=lat + span,
                   elevations=np.broadcast_to(z, (size, size)).astype(float).copy())


class TestAspect:
    def test_ground_rising_to_the_north_faces_south(self):
        slope, aspect = insolation.gradient(plane(rise_north=10.0))
        middle = aspect[10, 10]
        assert slope[10, 10] > 5
        assert middle == pytest.approx(180.0, abs=1.0)

    def test_ground_rising_to_the_east_faces_west(self):
        _, aspect = insolation.gradient(plane(rise_east=10.0))
        assert aspect[10, 10] == pytest.approx(270.0, abs=1.0)

    def test_a_south_west_face_is_south_west(self):
        """Rising to the north-east means looking to the south-west.

        Not to exactly 225, and the difference is the point: the same metres per grid
        *step* is a steeper gradient per metre along the shorter axis, and at 49 degrees
        longitude is the shorter one. So an equal-per-step tilt leans west of the
        diagonal — measured at 237. A gradient that ignored the latitude would answer
        exactly 225 and be wrong in a way no assertion on the quadrant would catch.
        """
        _, aspect = insolation.gradient(plane(rise_north=10.0, rise_east=10.0))
        assert 180.0 < float(aspect[10, 10]) < 270.0
        assert float(aspect[10, 10]) > 225.0

    def test_flat_ground_has_no_slope(self):
        slope, _ = insolation.gradient(plane())
        assert float(slope.max()) == pytest.approx(0.0, abs=1e-9)

    def test_the_longitude_axis_is_shortened_by_the_latitude(self):
        """A degree of longitude is a degree of latitude times cos(lat).

        Ignoring it tilts every slope towards north-south — at 60 degrees a symmetric
        grid would read as a 27-degree error in aspect, which is a whole compass point.
        """
        equator = insolation.gradient(plane(rise_north=10.0, rise_east=10.0, lat=0.0))[0]
        high = insolation.gradient(plane(rise_north=10.0, rise_east=10.0, lat=60.0))[0]
        # The same metres over half the ground distance is a steeper slope. Only the
        # east component shortens, so the whole slope grows by less than the factor of
        # two the longitude axis does.
        assert float(high[10, 10]) > float(equator[10, 10]) * 1.4


class TestLight:
    def test_the_sun_square_on_a_face_lights_it_fully(self):
        """A 30-degree slope facing south, with the sun in the south 60 degrees up, is
        illuminated exactly normally: cos(0) = 1."""
        slope = np.array([[30.0]])
        aspect = np.array([[180.0]])
        lit = insolation.lit_grid(slope, aspect, azimuth=180.0, elevation=60.0)
        assert float(lit[0, 0]) == pytest.approx(1.0, abs=1e-6)

    def test_flat_ground_is_the_sine_of_the_sun_height(self):
        lit = insolation.lit_grid(np.array([[0.0]]), np.array([[0.0]]),
                                  azimuth=180.0, elevation=30.0)
        assert float(lit[0, 0]) == pytest.approx(math.sin(math.radians(30)), abs=1e-6)

    def test_a_face_turned_away_gets_no_direct_light(self):
        """Clipped at zero rather than allowed negative: how far past the terminator a
        face is turned makes no difference to it being in shadow."""
        lit = insolation.lit_grid(np.array([[60.0]]), np.array([[0.0]]),
                                  azimuth=180.0, elevation=20.0)
        assert float(lit[0, 0]) == 0.0

    def test_a_sun_below_the_horizon_lights_nothing(self):
        lit = insolation.lit_grid(np.array([[30.0]]), np.array([[180.0]]),
                                  azimuth=180.0, elevation=-3.0)
        assert float(lit.max()) == 0.0


class TestForFlight:
    def _flight(self, tmp_path):
        from tracklog_viewer.analysis import analyse
        from tracklog_viewer.igc import parse
        from tests.test_analysis import build, circling

        return analyse(parse(build(tmp_path / "s.igc", circling(400, climb=1.5))))

    def test_no_terrain_is_no_measurement_rather_than_a_zero(self, tmp_path):
        answer = insolation.for_flight(self._flight(tmp_path), None)
        assert not answer.measured
        assert answer.mean_advantage is None

    def test_a_climb_over_flat_ground_has_no_aspect(self, tmp_path):
        answer = insolation.for_flight(self._flight(tmp_path), plane())
        assert answer.measured
        assert all(face.aspect is None for face in answer.faces)
        # And it is exactly as lit as its surroundings, because they are the same plane.
        assert answer.mean_advantage == pytest.approx(1.0, abs=0.01)

    def test_advantage_is_relative_to_the_ground_around_it(self, tmp_path):
        """The number only means anything next to another cell's on the same grid.

        A uniform slope is uniformly lit, so however steep and however well aimed, its
        advantage over its own neighbourhood is 1.
        """
        answer = insolation.for_flight(self._flight(tmp_path), plane(rise_north=8.0))
        assert answer.measured
        assert answer.mean_advantage == pytest.approx(1.0, abs=0.05)

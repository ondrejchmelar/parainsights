"""Insolation from the DEM, on slopes whose aspect is known by construction.

A synthetic ramp has one aspect everywhere, so "which way does this face" has an exact
answer and the sun can be put where its effect is unambiguous — a low sun in the west lights
a west-facing slope and leaves an east-facing one in shadow. That is the whole physics of
the module, and it is checkable without a real DEM.
"""

import numpy as np
import pytest

from tests import js
from tests.js import needs_node

pytestmark = needs_node

K = js.run("""var i = TV.insolation; return { MIN_SLOPE: i.MIN_SLOPE, RIDGE_SLOPE: i.RIDGE_SLOPE,
  RIDGE_CLEARANCE: i.RIDGE_CLEARANCE, RIDGE_TURN_RATE: i.RIDGE_TURN_RATE,
  RIDGE_TOLERANCE: i.RIDGE_TOLERANCE };""") if __import__("shutil").which("node") else {}


def grid(elevations, west=14.0, east=14.05, south=49.0, north=49.05) -> dict:
    """The page's grid shape: row 0 at the north edge, flat row-major heights."""
    z = np.asarray(elevations, dtype=float)
    return {"west": west, "east": east, "south": south, "north": north,
            "rows": z.shape[0], "cols": z.shape[1], "z": z.ravel().tolist()}


def ramp(direction: str, *, size: int = 41, relief: float = 800.0) -> dict:
    """A DEM that slopes one way. `direction` is the way the ground *faces* — downhill.

    Row 0 is north and column 0 is west, so "faces north" means high in the south, which
    is a large row index. The box is 0.05 degrees rather than 0.4: 800 m over 44 km is a
    one-degree slope, which has no meaningful aspect and is not what a pilot means by a
    face. Over 5.5 km the same relief gives 8 degrees.
    """
    up = np.linspace(0.0, 1.0, size)
    shapes = {
        "west": np.tile(up[None, :], (size, 1)),          # high in the east
        "east": np.tile(up[::-1][None, :], (size, 1)),    # high in the west
        "north": np.tile(up[:, None], (1, size)),         # high in the south
        "south": np.tile(up[::-1][:, None], (1, size)),   # high in the north
    }
    return grid(shapes[direction] * relief)


def face(terrain, azimuth, elevation, lat=49.025, lon=14.025):
    return js.run("return TV.insolation.faceAt(input.grid, input.sun, input.lat, input.lon);",
                  grid=terrain, sun={"azimuth": azimuth, "elevation": elevation}, lat=lat, lon=lon)


def lit(terrain, azimuth, elevation):
    return js.run("return Array.from(TV.insolation.litGrid(input.grid, input.sun));",
                  grid=terrain, sun={"azimuth": azimuth, "elevation": elevation})


class TestAspect:
    @pytest.mark.parametrize("facing,expected", [
        ("south", 180.0), ("north", 0.0), ("west", 270.0), ("east", 90.0),
    ])
    def test_a_uniform_slope_has_the_aspect_it_was_built_with(self, facing, expected):
        found = face(ramp(facing), 180.0, 80.0)
        assert found is not None
        offset = abs(((found.aspect - expected + 540) % 360) - 180)
        assert offset < 20.0, f"{facing} slope reported aspect {found.aspect}"
        assert found.slope > K["MIN_SLOPE"]

    def test_the_east_west_spacing_is_scaled_by_latitude(self):
        """The grid is regular in degrees, not metres. One spacing for both axes tilts
        every aspect towards the poles, which is a wrong answer that looks plausible."""
        found = face(ramp("west"), 180.0, 80.0)
        assert found is not None
        assert abs(((found.aspect - 270.0 + 540) % 360) - 180) < 15.0


class TestInsolation:
    def test_a_low_western_sun_lights_a_west_face_and_shades_an_east_one(self):
        west, east = face(ramp("west"), 270.0, 15.0), face(ramp("east"), 270.0, 15.0)
        assert west is not None and east is not None
        assert west.insolation > east.insolation, (
            f"west {west.insolation} should beat east {east.insolation} at sunset")
        assert east.insolation < 0.2

    def test_a_sun_below_the_horizon_lights_nothing(self):
        assert float(lit(ramp("west"), 270.0, -5.0).max()) == 0.0

    def test_insolation_never_goes_negative(self):
        """A face turned away is unlit, not negatively lit — otherwise it quietly
        subtracts from the neighbourhood mean the comparison is made against."""
        assert float(lit(ramp("west"), 90.0, 10.0).min()) >= 0.0

    def test_relative_insolation_compares_with_the_ground_around_it(self):
        """0.8 means nothing on a day when every slope reads 0.8."""
        found = face(ramp("west"), 270.0, 15.0)
        assert found is not None
        # A uniform ramp is its own neighbourhood, so nothing here is unusual.
        assert found.relative == pytest.approx(1.0, abs=0.15)


class TestTriggersAndWind:
    def _path(self, tmp_path):
        from tests.test_analysis import build, circling
        return build(tmp_path / "t.igc", circling(400, climb=1.5))

    def test_no_terrain_means_no_triggers(self, tmp_path):
        assert js.run("return TV.insolation.triggers(TV.analysis.analyse(await load(input.path)), null);",
                      path=self._path(tmp_path)) == []

    def test_windward_refuses_without_a_wind(self, tmp_path):
        assert js.run("""var a = TV.analysis.analyse(await load(input.path)); a.wind = null;
                         return TV.insolation.windward(a, input.grid);""",
                      path=self._path(tmp_path), grid=ramp("west")) is None

    def test_a_flat_grid_yields_no_face_worth_naming(self):
        found = face(grid(np.full((41, 41), 500.0)), 180.0, 60.0)
        assert found is not None
        assert found.slope < K["MIN_SLOPE"], "a flat grid has no meaningful aspect"

    def test_a_point_outside_the_grid_is_refused(self):
        assert face(ramp("west"), 180.0, 60.0, lat=40.0, lon=14.02) is None


class TestWhatHeldTheClimbUp:
    """Ridge against thermal, on a slope whose aspect is known by construction.

    The classifier needs three things to agree before it says ridge — steep ground, a
    climb that stayed on it, and a track that beat along it instead of circling — so each
    test moves exactly one of them and checks the label follows. The third is the one
    that carries the claim, and it is the one the old rule did not have: it asked whether
    the wind ran into the face instead, which found ridge lift on no real flight at all.

    Nothing here checks *convergence* — it is deliberately not a label, because one
    tracklog cannot separate it from a ridge climb holding station or a badly sounded
    wind.

    The flights are flown at the middle of the ramp rather than at the origin of the test
    projection, which is the ramp's south-west *corner*: with the track in the corner,
    `faceAt` read one part of the hill and the ground clearance another, and a fixture
    built to sit 80 m over the slope measured 778.
    """

    # 1400 m of relief over the box rather than 800: a 12.3° ramp is a coin-toss against
    # a 12° threshold, and a test should not be one bad rounding from the other answer.
    RELIEF = 1400.0
    # Metres from the ramp's south-west corner to its middle, at 49°N.
    MID_X, MID_Y = 1825.0, 2780.0

    def _source(self, tmp_path, points, terrain, *, wind_from=270.0, wind_kmh=25.0,
                name="c.igc", no_wind=False):
        """The first climb's label, with the fixture's wind set on the flight *and* on
        every climb: `sources` prefers the climb's own drift and falls back to the
        flight's, so setting only one leaves the fixture's wind unused."""
        from tests.test_analysis import build
        return js.run("""
          var a = TV.analysis.analyse(await load(input.path));
          var wind = input.noWind ? null : { speed: input.kmh / 3.6, direction: input.from,
                                             cardinal: TV.geo.cardinal(input.from), confidence: 1.0 };
          a.wind = wind;
          a.segments.forEach(function (s) { if (s.phase === 'thermal') s.wind = wind; });
          var found = TV.insolation.sources(a, input.grid);
          return found[1] || null;
        """, path=build(tmp_path / name, points), grid=terrain, kmh=wind_kmh, **{"from": wind_from},
            noWind=no_wind)

    def _hill(self, direction="west"):
        return ramp(direction, relief=self.RELIEF)

    def _ground(self):
        return js.run("return TV.terrain.at(input.grid, 49.025, 14.025);", grid=self._hill())

    def _beat(self, tmp_path, *, over, terrain="hill", **kw):
        from tests.test_analysis import beat
        points = beat(300, climb=0.8, alt0=self._ground() + over, x0=self.MID_X, y0=self.MID_Y)
        return self._source(tmp_path, points, self._hill() if terrain == "hill" else terrain, **kw)

    def test_a_steep_slope_beaten_close_in_is_ridge(self, tmp_path):
        """The whole signature: steep ground, stayed on it, never closed a circle."""
        source = self._beat(tmp_path, over=60)
        assert source is not None, "no climbs were classified"
        assert source.label == "ridge", source
        assert source.confident is True
        assert source.slope >= K["RIDGE_SLOPE"]
        assert source.clearance <= K["RIDGE_CLEARANCE"]
        assert source.turn_rate <= K["RIDGE_TURN_RATE"]

    def test_the_same_slope_worked_high_above_it_is_a_thermal(self, tmp_path):
        """Ridge lift does not reach. Height above the slope is a hard separator."""
        source = self._beat(tmp_path, over=1200, name="high.igc")
        assert source.label == "thermal", source
        assert source.clearance > K["RIDGE_CLEARANCE"]

    def test_a_climb_circled_low_over_the_slope_is_still_a_thermal(self, tmp_path):
        """The measurement the old rule did not have, and the one that does the work.

        Same hill, same height above it, same wind — only the manoeuvre differs. A pilot
        turning complete circles is in a core, whatever is under them; ridge lift is
        beaten, because there is no room to turn.
        """
        from tests.test_analysis import circling
        points = circling(200, climb=1.5, alt0=self._ground() + 60, x0=self.MID_X, y0=self.MID_Y)
        source = self._source(tmp_path, points, self._hill(), name="cored.igc")
        assert source.label == "thermal", source
        assert source.clearance <= K["RIDGE_CLEARANCE"], (
            "the fixture is meant to be low over the slope, so height is not what settled this")
        assert source.turn_rate > K["RIDGE_TURN_RATE"]

    def test_flat_ground_beaten_close_in_is_not_ridge(self, tmp_path):
        """Beating along nothing is not ridge soaring — there has to be a hill."""
        from tests.test_analysis import beat
        points = beat(300, climb=0.8, alt0=560.0, x0=self.MID_X, y0=self.MID_Y)
        source = self._source(tmp_path, points, grid(np.full((41, 41), 500.0)), name="flat.igc")
        assert source.label == "thermal", source
        assert source.slope < K["RIDGE_SLOPE"]

    def test_the_wind_no_longer_vetoes_the_label(self, tmp_path):
        """A ridge worked in a wind the flight measured as coming off the back of it.

        This is not a hypothetical. On the flight that prompted the rewrite every climb
        reported a wind under 3 km/h, one of them 116° off the face — because the wind
        estimate is derived from *circling drift*, and a pilot who spends the evening
        beating a ridge never circles. The estimate that would have vetoed the label is
        an artifact of the very behaviour being classified.
        """
        source = self._beat(tmp_path, over=60, wind_from=90.0, name="lee.igc")
        assert source.label == "ridge", source
        assert source.offset > K["RIDGE_TOLERANCE"], (
            "the fixture is meant to put the wind off the back of the hill")

    def test_the_wind_offset_is_still_reported(self, tmp_path):
        """Demoted from a gate to a measurement, not deleted: it goes in the tooltip."""
        source = self._beat(tmp_path, over=60, wind_from=270.0)
        assert source.offset is not None
        assert source.offset < K["RIDGE_TOLERANCE"]

    def test_without_terrain_the_label_is_offered_but_not_claimed(self, tmp_path):
        """"Thermal because there was nothing to check" is not the same claim as
        "thermal because the ground was flat", and the report shows a dash rather than
        the fallback."""
        source = self._beat(tmp_path, over=60, terrain=None, name="noterrain.igc")
        assert source.label == "thermal"
        assert source.confident is False

    def test_without_a_wind_the_label_still_stands(self, tmp_path):
        """Nothing in the rule needs one any more, so a missing wind costs the offset
        and nothing else. It must not quietly become a number: a face `0°` off a wind
        that was never measured is a fabrication."""
        source = self._beat(tmp_path, over=60, name="nowind.igc", no_wind=True)
        assert source.label == "ridge", source
        assert source.confident is True
        assert source.offset is None


class TestTheReportExplainsTheLabel:
    """"How to read this, and what to distrust" makes claims about the rule.

    The section is where a reader goes to find out whether to believe a number, so a
    sentence in it that has drifted from the code is worse than no sentence. The
    thresholds are interpolated from the module rather than typed, and this holds that.
    """

    def _report(self, tmp_path):
        from tests.test_debrief import a_day
        path = a_day(tmp_path, "notes.igc", [(300, 2.5), (300, 2.0), (300, 1.4)], glide=700)
        return js.run("return TV.report.flightBody(TV.analysis.analyse(await load(input.path)),"
                      " { uid: 'f0', now: Date.now() / 1000 });", path=path)

    def test_the_thresholds_in_the_prose_are_the_ones_the_code_uses(self, tmp_path):
        html = self._report(tmp_path)
        assert f"steeper than {K['RIDGE_SLOPE']:.0f}°" in html, (
            "the slope threshold in the note is not the one the classifier uses")
        assert f"within {K['RIDGE_CLEARANCE']:.0f}&nbsp;m of the slope" in html, (
            "the clearance threshold in the note is not the one the classifier uses")

    def test_the_prose_reads_the_constants_rather_than_repeating_them(self):
        """The regression this exists for: someone moves a threshold and not the note. A
        hand-typed "12°" is stale the moment `RIDGE_SLOPE` moves, in the section of the
        report least likely to be re-read."""
        import pathlib
        source = (pathlib.Path(js.BRIDGE).parent.parent / "tracklog_viewer" / "js" / "report.js").read_text()
        start = source.index("Ridge only when three things agree")
        paragraph = source[start:source.index("</th>", start)]
        assert "TV.insolation.RIDGE_SLOPE" in paragraph
        assert "TV.insolation.RIDGE_CLEARANCE" in paragraph

    def test_convergence_is_named_as_a_deliberate_omission(self, tmp_path):
        """A reader who knows the sky will ask where convergence went, and "we did not
        bother" and "one tracklog cannot support it" are different answers."""
        assert "Convergence is deliberately not a label" in self._report(tmp_path)

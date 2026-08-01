"""Insolation from the DEM, on slopes whose aspect is known by construction.

A synthetic ramp has one aspect everywhere, so "which way does this face" has an exact
answer and the sun can be put where its effect is unambiguous — a low sun in the west lights
a west-facing slope and leaves an east-facing one in shadow. That is the whole physics of
the module, and it is checkable without a real DEM.
"""


import numpy as np
import pytest

from tracklog_viewer import geo, insolation, sun
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
    projection, which is the ramp's south-west *corner*. Placing them mattered more than
    it looks: with the track in the corner and the segment's centre reassigned by hand to
    the middle, `face_at` read one part of the hill and the ground clearance another, and
    a fixture built to sit 80 m over the slope measured 778.
    """

    # 1400 m of relief over the box rather than 800: a 12.3° ramp is a coin-toss against
    # a 12° threshold, and a test should not be one bad rounding from the other answer.
    RELIEF = 1400.0
    # Metres from the ramp's south-west corner to its middle, at 49°N.
    MID_X, MID_Y = 1825.0, 2780.0

    def _analysis(self, tmp_path, points, *, wind_from=270.0, wind_kmh=25.0, name="c.igc"):
        from tests.test_analysis import build
        from tracklog_viewer import igc
        from tracklog_viewer.analysis import Wind, analyse

        analysis = analyse(igc.parse(build(tmp_path / name, points)))
        wind = Wind(speed=wind_kmh / 3.6, direction=wind_from,
                    cardinal=geo.cardinal(wind_from), confidence=1.0)
        # Both, because `sources` prefers the climb's own drift and falls back to the
        # flight's: setting only one leaves the fixture's wind unused and the test
        # asserting against whatever the synthetic track happened to drift.
        analysis.wind = wind
        for segment in analysis.thermals:
            segment.wind = wind
        return analysis

    def _beat(self, tmp_path, *, over, climb=0.8, duration=300, **kw):
        """A glider working back and forth along the slope, `over` metres above it."""
        from tests.test_analysis import beat

        return self._analysis(tmp_path, beat(
            duration, climb=climb, alt0=self._ground() + over,
            x0=self.MID_X, y0=self.MID_Y), **kw)

    def _circle(self, tmp_path, *, over, climb=1.5, duration=200, **kw):
        """A glider turning inside a core, `over` metres above the same slope."""
        from tests.test_analysis import circling

        return self._analysis(tmp_path, circling(
            duration, climb=climb, alt0=self._ground() + over,
            x0=self.MID_X, y0=self.MID_Y), **kw)

    def _hill(self, direction="west"):
        return ramp(direction, relief=self.RELIEF)

    def _ground(self, direction="west"):
        return float(self._hill(direction).at(49.025, 14.025))

    def _label(self, analysis, terrain):
        found = insolation.sources(analysis, terrain)
        assert found, "no climbs were classified"
        return found[1]

    def test_a_steep_slope_beaten_close_in_is_ridge(self, tmp_path):
        """The whole signature: steep ground, stayed on it, never closed a circle."""
        source = self._label(self._beat(tmp_path, over=60), self._hill())

        assert source.label == "ridge", source
        assert source.confident is True
        assert source.slope >= insolation.RIDGE_SLOPE
        assert source.clearance <= insolation.RIDGE_CLEARANCE
        assert source.turn_rate <= insolation.RIDGE_TURN_RATE

    def test_the_same_slope_worked_high_above_it_is_a_thermal(self, tmp_path):
        """Ridge lift does not reach. Height above the slope is a hard separator."""
        source = self._label(
            self._beat(tmp_path, over=1200, name="high.igc"), self._hill())

        assert source.label == "thermal", source
        assert source.clearance > insolation.RIDGE_CLEARANCE

    def test_a_climb_circled_low_over_the_slope_is_still_a_thermal(self, tmp_path):
        """The measurement the old rule did not have, and the one that does the work.

        Same hill, same height above it, same wind — only the manoeuvre differs. A pilot
        turning complete circles is in a core, whatever is under them; ridge lift is
        beaten, because there is no room to turn.
        """
        source = self._label(
            self._circle(tmp_path, over=60, name="cored.igc"), self._hill())

        assert source.label == "thermal", source
        assert source.clearance <= insolation.RIDGE_CLEARANCE, (
            "the fixture is meant to be low over the slope, so height is not what "
            "settled this")
        assert source.turn_rate > insolation.RIDGE_TURN_RATE

    def test_flat_ground_beaten_close_in_is_not_ridge(self, tmp_path):
        """Beating along nothing is not ridge soaring — there has to be a hill."""
        from tests.test_analysis import beat

        flat = Terrain(west=14.0, east=14.05, south=49.0, north=49.05,
                       elevations=np.full((41, 41), 500.0))
        analysis = self._analysis(
            tmp_path,
            beat(300, climb=0.8, alt0=560.0, x0=self.MID_X, y0=self.MID_Y),
            name="flat.igc")

        source = self._label(analysis, flat)
        assert source.label == "thermal", source
        assert source.slope < insolation.RIDGE_SLOPE

    def test_the_wind_no_longer_vetoes_the_label(self, tmp_path):
        """A ridge worked in a wind the flight measured as coming off the back of it.

        This is not a hypothetical. On the flight that prompted the rewrite every climb
        reported a wind under 3 km/h, one of them 116° off the face — because the wind
        estimate is derived from *circling drift*, and a pilot who spends the evening
        beating a ridge never circles. The estimate that would have vetoed the label is
        an artifact of the very behaviour being classified.
        """
        source = self._label(
            self._beat(tmp_path, over=60, wind_from=90.0, name="lee.igc"), self._hill())

        assert source.label == "ridge", source
        assert source.offset > insolation.RIDGE_TOLERANCE, (
            "the fixture is meant to put the wind off the back of the hill")

    def test_the_wind_offset_is_still_reported(self, tmp_path):
        """Demoted from a gate to a measurement, not deleted: it goes in the tooltip."""
        source = self._label(self._beat(tmp_path, over=60, wind_from=270.0), self._hill())
        assert source.offset is not None
        assert source.offset < insolation.RIDGE_TOLERANCE

    def test_without_terrain_the_label_is_offered_but_not_claimed(self, tmp_path):
        """"Thermal because there was nothing to check" is not the same claim as
        "thermal because the ground was flat", and the report shows a dash rather than
        the fallback."""
        source = self._label(self._beat(tmp_path, over=60, name="noterrain.igc"), None)

        assert source.label == "thermal"
        assert source.confident is False

    def test_without_a_wind_the_label_still_stands(self, tmp_path):
        """Nothing in the rule needs one any more, so a missing wind costs the offset
        and nothing else. It must not quietly become a number: a face `0°` off a wind
        that was never measured is a fabrication."""
        analysis = self._beat(tmp_path, over=60, name="nowind.igc")
        analysis.wind = None
        for segment in analysis.thermals:
            segment.wind = None

        source = self._label(analysis, self._hill())
        assert source.label == "ridge", source
        assert source.confident is True
        assert source.offset is None


class TestTheReportExplainsTheLabel:
    """"How to read this, and what to distrust" makes claims about the rule.

    The section is where a reader goes to find out whether to believe a number, so a
    sentence in it that has drifted from the code is worse than no sentence — it is the
    one place the report promises to be exact about its own limits. The thresholds are
    interpolated from the module rather than typed, and this holds that: a hand-typed
    "12°" would have gone stale the moment `RIDGE_SLOPE` moved, silently and in the
    section least likely to be re-read.
    """

    def _report(self, tmp_path):
        from tests.test_debrief import a_day
        from tracklog_viewer import render_html

        analysis = a_day(tmp_path, "notes.igc",
                         [(300, 2.5), (300, 2.0), (300, 1.4)], glide=700)
        return render_html.render(analysis, terrain=None)

    def test_the_thresholds_in_the_prose_are_the_ones_the_code_uses(self, tmp_path):
        html = self._report(tmp_path)
        # Matched with the words that follow rather than those before: the whitespace
        # ahead of each number is the template's line wrap and would make this brittle
        # for no gain.
        assert f"{insolation.RIDGE_SLOPE:.0f}°, the glider stayed within" in html, (
            "the slope threshold in the note is not the one the classifier uses")
        assert f"{insolation.RIDGE_CLEARANCE:.0f} m of it" in html, (
            "the clearance threshold in the note is not the one the classifier uses")

    def test_the_prose_reads_the_constants_rather_than_repeating_them(self):
        """The regression this exists for: someone moves a threshold and not the note.

        The test above catches a mismatch only because both sides are evaluated in the
        same run. This catches the *shape*, which is the thing that actually rots: a
        hand-typed "12°" is stale the moment `RIDGE_SLOPE` moves, in the section of
        the report least likely to be re-read.
        """
        import pathlib

        from tracklog_viewer import render_html

        source = pathlib.Path(render_html.__file__).read_text(encoding="utf-8")
        start = source.index('"Ridge" is three measurements')
        paragraph = source[start:source.index("</p>", start)]
        assert "insolation.RIDGE_SLOPE" in paragraph
        assert "insolation.RIDGE_CLEARANCE" in paragraph

    def test_convergence_is_named_as_a_deliberate_omission(self, tmp_path):
        """A reader who knows the sky will ask where convergence went, and "we did not
        bother" and "one tracklog cannot support it" are different answers."""
        assert "Convergence is deliberately not a label" in self._report(tmp_path)

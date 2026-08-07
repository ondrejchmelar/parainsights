"""The air-mass frame, on synthetic flights whose wind is known by construction.

This is the only way to test a wind correction. On a real tracklog nobody knows what the
air was doing — that is the entire problem the module addresses — so the fixtures fly
exact geometry through an exact wind and the assertions are the numbers that geometry
implies. `circling(drift=…)` from `test_analysis` already builds a glider circling in
moving air, which is precisely the input.
"""

import math

import numpy as np
import pytest

from tracklog_viewer import airmass
from tracklog_viewer.analysis import analyse
from tracklog_viewer.igc import parse

from .test_analysis import build, circling, straight


def flight(tmp_path, points, name="a.igc"):
    return analyse(parse(build(tmp_path / name, points)))


def three_climbs(*, drift=(0.0, 0.0), climb=1.5, each=260,
                 glide_speed=11.0, glide_sink=-1.2):
    """Three circled climbs in the same air, separated by short glides.

    The field wants several soundings before it trusts itself, and a real flight has
    them: this is the smallest fixture that is not arguing with that rule.
    """
    points = []
    t, alt, x, y = 0.0, 1000.0, 0.0, 0.0
    for _ in range(3):
        points += circling(each, drift=drift, climb=climb, t0=t, alt0=alt, x0=x, y0=y)
        t, x, y, alt = points[-1][0] + 1, points[-1][1], points[-1][2], points[-1][3]
        points += straight(140, speed=glide_speed, climb=glide_sink, t0=t, alt0=alt,
                           x0=x, y0=y, heading=90.0)
        t, x, y, alt = points[-1][0] + 1, points[-1][1], points[-1][2], points[-1][3]
    return points


class TestTheField:
    def test_a_circled_climb_sounds_the_wind_it_drifted_in(self, tmp_path):
        """5 m/s of easterly drift is 5 m/s of easterly air, at the height it was
        measured. Three climbs rather than one: a lone sounding is deliberately only
        half trusted, so a fixture built on one would be testing the discount."""
        analysis = flight(tmp_path, three_climbs(drift=(5.0, 0.0)))
        field = airmass.wind_field(analysis)
        assert field.measured
        u, v, confidence = field.at(200.0, 1300.0)
        assert u == pytest.approx(5.0, abs=0.6)
        assert abs(v) < 0.6
        assert confidence > 0.5

    def test_a_wind_named_from_is_air_moving_towards(self):
        """The classic 180 in this subject, pinned so it cannot come back."""
        # Wind *from* the north: the air moves south, so north is negative.
        u, v = airmass._components(10.0, 0.0)
        assert v == pytest.approx(-10.0, abs=1e-6)
        assert abs(u) < 1e-6
        # Wind from the west: the air moves east.
        u, v = airmass._components(10.0, 270.0)
        assert u == pytest.approx(10.0, abs=1e-6)

    def test_no_sounding_and_no_model_is_no_wind_and_says_so(self, tmp_path):
        analysis = flight(tmp_path, straight(400, climb=-1.0))
        field = airmass.wind_field(analysis)
        assert not field.measured
        assert field.confidence == 0.0
        assert field.at(100.0, 1000.0) == (0.0, 0.0, 0.0)

    def test_the_field_falls_off_away_from_its_soundings(self, tmp_path):
        """A thermal sounds the air where and when it was circled, not everywhere."""
        analysis = flight(tmp_path, three_climbs(drift=(5.0, 0.0)))
        field = airmass.wind_field(analysis)
        near = field.at(200.0, 1300.0)[2]
        far = field.at(200.0 + 4 * airmass.HEIGHT_SCALE, 1300.0)[2]
        assert far < near


class TestGlides:
    def _into_wind(self, tmp_path, wind_east):
        """A glide flown east at 10 m/s through the air, sinking 1 m/s, in a known wind.

        Ground speed is 10 + wind, air speed is 10, so the two glide ratios differ by
        exactly the wind — which is the arithmetic the module exists to do.
        """
        # *Every* glide in the fixture flies the same way, connectors included — the
        # air ratio is a median over all of them, so a fixture whose connectors glide
        # differently would be measuring the connectors.
        points = three_climbs(drift=(wind_east, 0.0),
                              glide_speed=10.0 + wind_east, glide_sink=-1.0)
        t0 = points[-1][0] + 1
        x0, y0, alt0 = points[-1][1], points[-1][2], points[-1][3]
        points += straight(300, speed=10.0 + wind_east, climb=-1.0, t0=t0,
                           alt0=alt0, x0=x0, y0=y0, heading=90.0)
        return flight(tmp_path, points, f"w{wind_east:.0f}.igc")

    def test_a_tailwind_flatters_the_ground_glide(self, tmp_path):
        analysis = self._into_wind(tmp_path, 4.0)
        air = airmass.analyse(analysis)
        assert air.ground_ld is not None and air.air_ld is not None
        # Ground: 14 m/s over 1 m/s of sink. Air: 10 over 1.
        assert air.ground_ld > air.air_ld
        assert air.air_ld == pytest.approx(10.0, rel=0.25)

    def test_the_correction_is_refused_on_a_weak_field(self, tmp_path):
        """Below the confidence threshold a corrected number is an uncorrected one
        wearing a correction, so there is no number at all."""
        points = straight(200, climb=-1.0)
        points += straight(300, t0=201, alt0=points[-1][3], climb=-1.0,
                           x0=points[-1][1], y0=points[-1][2], heading=90.0)
        air = airmass.analyse(flight(tmp_path, points, "weak.igc"))
        assert air.field.confidence < airmass.MIN_CONFIDENCE
        assert air.air_ld is None
        assert air.ground_ld is not None, "the ground figure needs no wind at all"


class TestCircleWander:
    def test_pure_drift_is_not_wander(self, tmp_path):
        """Over the ground a thermal's circles march downwind and the centre moves by
        exactly the drift, which says nothing about the pilot. That is the whole reason
        the metric is defined in the air frame."""
        analysis = flight(tmp_path, three_climbs(drift=(5.0, 0.0), each=600))
        air = airmass.analyse(analysis)
        assert air.wander is not None
        # Ground frame, the same climb, for comparison: 5 m/s x 20 s is 100 m a circle.
        series = analysis.series
        centres = airmass._circle_centres(
            series.heading, series.x, series.y, analysis.thermals[0]
        )
        ground = float(np.median([
            math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(centres, centres[1:])
        ]))
        assert ground > 60
        assert air.wander < ground / 2

    def test_it_is_refused_at_coarse_sampling(self, tmp_path):
        """Every circling metric inherits `TURN_RESOLUTION_LIMIT`."""
        points = [p for p in three_climbs(each=600) if p[0] % 15 == 0]
        air = airmass.analyse(flight(tmp_path, points, "coarse.igc"))
        assert air.wander is None


class TestPolar:
    def test_an_inverted_curve_is_refused(self):
        """Less sink the faster you fly is not a wing, it is the day.

        The tow flight's one-flight polar comes out exactly like this — 1.40 m/s down at
        32 km/h and 0.80 at 42 — and publishing a speed-to-fly number from it would be
        the blind coach with arithmetic.
        """
        inverted = airmass.Polar([
            airmass.PolarPoint(25.0, -1.40, 100),
            airmass.PolarPoint(30.0, -1.40, 100),
            airmass.PolarPoint(35.0, -0.80, 100),
        ], confidence=0.9)
        assert not inverted.monotone
        assert not inverted.usable

    def test_a_wings_curve_is_accepted(self):
        wing = airmass.Polar([
            airmass.PolarPoint(25.0, -0.90, 100),
            airmass.PolarPoint(30.0, -1.10, 100),
            airmass.PolarPoint(35.0, -1.50, 100),
        ], confidence=0.9)
        assert wing.monotone and wing.usable
        speed, ratio = wing.best_glide
        assert speed == 25.0
        assert ratio == pytest.approx((25.0 / 3.6) / 0.9, rel=0.01)

    def test_a_sparse_curve_is_refused_however_good_the_wind(self):
        thin = airmass.Polar([airmass.PolarPoint(30.0, -1.0, 400)], confidence=1.0)
        assert not thin.usable

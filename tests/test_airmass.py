"""The air-mass frame, on synthetic flights where the wind is known exactly.

These are the tests that matter most in the whole analysis layer, because the wind is the
weakest input in the tool and everything speed-to-fly waits on it. So they check two
things in equal measure: that a *known* wind is recovered and removed, and that an
untrusted wind is refused rather than quietly applied.
"""

import pytest

from tests import js
from tests.js import needs_node
from tests.test_analysis import build, circling, straight

pytestmark = needs_node

UNTRUSTED = {"soundings": [], "confidence": 0.1, "source": "none", "fallback": None}


def windy_day(tmp_path, name, *, drift=(3.0, 0.0), climbs=4):
    """Climbs circled in a known wind, joined by glides.

    `drift` is the air's own motion in m/s east/north — so the wind is *from* the west
    when drift is positive east, which is the convention reversal `vector` exists for.
    """
    points, t, alt, x, y = [], 0.0, 1000.0, 0.0, 0.0
    for _ in range(climbs):
        leg = circling(240, climb=2.0, t0=t, alt0=alt, x0=x, y0=y, drift=drift)
        points += leg
        t, alt, x, y = leg[-1][0] + 1, leg[-1][3], leg[-1][1], leg[-1][2]
        # The glide moves through the air *and* is carried by it, so the ground track is
        # the sum — which is exactly what the correction has to undo.
        run = []
        for second in range(200):
            run.append((t + second,
                        x + (12.0 + drift[0]) * second,
                        y + drift[1] * second,
                        alt - 1.0 * second))
        points += run
        t, alt, x, y = run[-1][0] + 1, run[-1][3], run[-1][1], run[-1][2]
    return build(tmp_path / name, points)


def ask(path, code, **inputs):
    """Run `code` with the file's analysis as `a` and its wind field as `wind`."""
    return js.run("""
      var a = TV.analysis.analyse(await load(input.path));
      var wind = input.wind || TV.airmass.field(a);
      """ + code, path=path, **inputs)


class TestWindField:
    def test_the_field_is_built_from_circled_climbs(self, tmp_path):
        wind = ask(windy_day(tmp_path, "field.igc"), "return wind;")
        assert wind.soundings, "no climb produced a sounding"
        assert wind.source == "measured"

    def test_the_field_recovers_the_wind_that_was_flown_in(self, tmp_path):
        """3 m/s of easterly drift is a wind *from* the west."""
        out = ask(windy_day(tmp_path, "recover.igc", drift=(3.0, 0.0)), """
          var mid = Math.floor(a.series.t.length / 2);
          return { soundings: wind.soundings.length,
                   v: TV.airmass.windAt(wind, a.series.t[mid], a.series.alt[mid]) };""")
        if not out.soundings:
            pytest.skip("no trusted soundings on this synthetic day")
        vx, vy = out.v
        assert vx == pytest.approx(3.0, abs=1.2), f"east component {vx}"
        assert abs(vy) < 1.5, f"spurious north component {vy}"

    def test_a_field_with_no_soundings_is_not_trusted(self, tmp_path):
        path = build(tmp_path / "nowind.igc", straight(600, speed=12.0, climb=-1.0, alt0=2000.0))
        assert ask(path, "return TV.airmass.trusted(wind);") is False

    def test_the_model_profile_is_only_a_fallback(self, tmp_path):
        path = build(tmp_path / "model.igc", straight(600, speed=12.0, climb=-1.0, alt0=2000.0))
        out = ask(path, """
          var modelled = TV.airmass.field(a, { windAt: function () { return [5.0, 270.0]; } });
          return { field: modelled, trusted: TV.airmass.trusted(modelled) };""")
        assert out.field.fallback is not None
        assert out.field.source == "model"
        # A model profile alone is not a measurement of *this* air, so it stays untrusted
        # and every consumer below refuses.
        assert out.trusted is False


class TestRefusals:
    """No air-mass correction on a low-confidence wind — the plan's third prohibition."""

    @pytest.mark.parametrize("call", ["glidePerformance", "polar"])
    def test_each_correction_refuses(self, tmp_path, call):
        path = windy_day(tmp_path, f"ref-{call}.igc")
        assert ask(path, f"return TV.airmass.{call}(a, wind);", wind=UNTRUSTED) is None


class TestGlidePerformance:
    def _performance(self, tmp_path, name):
        out = ask(windy_day(tmp_path, name, drift=(3.0, 0.0)), """
          return { trusted: TV.airmass.trusted(wind),
                   performance: TV.airmass.glidePerformance(a, wind) };""")
        if not out.trusted:
            pytest.skip("no trusted wind on this synthetic day")
        assert out.performance is not None
        return out.performance

    def test_the_correction_moves_the_ratio_towards_the_wing(self, tmp_path):
        """Gliding downwind flatters the ground ratio; the air ratio should be lower.

        This is the 6.3 -> 7.0 case from the plan with the sign reversed: here the glides
        run *with* the wind, so the ground figure is the optimistic one.
        """
        performance = self._performance(tmp_path, "perf.igc")
        assert performance.air_ld < performance.ground_ld, (
            f"air {performance.air_ld} vs ground {performance.ground_ld}: a tailwind "
            "glide should read better over the ground than through the air"
        )
        # 12 m/s through the air at 1 m/s down is 12:1 by construction.
        assert performance.air_ld == pytest.approx(12.0, abs=2.0)

    def test_airspeed_is_reported_through_the_air(self, tmp_path):
        performance = self._performance(tmp_path, "speed.igc")
        # 12 m/s = 43.2 km/h through the air, against 15 m/s = 54 km/h over the ground.
        assert performance.median_airspeed == pytest.approx(43.2, abs=6.0)


class TestPolar:
    def test_a_single_speed_gives_no_curve(self, tmp_path):
        """Every glide flown at one speed says nothing about a polar."""
        out = ask(windy_day(tmp_path, "flat.igc", drift=(3.0, 0.0)), """
          return { trusted: TV.airmass.trusted(wind), polar: TV.airmass.polar(a, wind) };""")
        if not out.trusted:
            pytest.skip("no trusted wind on this synthetic day")
        # All glides here are flown at exactly 12 m/s, so the speed spread is nil.
        assert out.polar is None

    def test_an_inverted_curve_claims_no_best_glide(self):
        """Less sink the faster you fly is the day, not the wing.

        Measured on `2020-07-12`, which published *"best glides came at about 39 km/h,
        where the wing returned 10.3:1"* off a curve running 1.30 m/s down at 22.5 km/h
        and 1.05 at 38.8. The fastest bin wins by construction on a curve like that, so
        the number is an artefact of a pilot who flew fast in the good air.
        """
        inverted = js.run("return TV.airmass.curve([22.5, 29.0, 38.8], [-1.30, -1.35, -1.05],"
                          " [100, 100, 100], 0.9);")
        assert inverted.monotone is False
        assert inverted.best_glide is None

    def test_a_wings_curve_keeps_its_best_glide(self):
        wing = js.run("return TV.airmass.curve([25.0, 30.0, 35.0], [-0.90, -1.10, -1.50],"
                      " [100, 100, 100], 0.9);")
        assert wing.monotone is True
        assert wing.best_glide is not None


class TestConventions:
    def test_the_wind_vector_points_where_the_air_is_going(self):
        """A wind's direction is where it comes *from* — the classic place to drop a 180."""
        # From the west (270) means the air moves east: +x, no y.
        vx, vy = js.run("return TV.airmass.vector(5.0, 270.0);")
        assert vx == pytest.approx(5.0, abs=1e-6)
        assert vy == pytest.approx(0.0, abs=1e-6)
        # From the north (0) means the air moves south: -y.
        vx, vy = js.run("return TV.airmass.vector(5.0, 0.0);")
        assert vy == pytest.approx(-5.0, abs=1e-6)
        assert abs(vx) < 1e-6

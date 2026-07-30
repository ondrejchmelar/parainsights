"""Analysis tests built on synthetic flights with known answers.

Real tracklogs are good for smoke tests but useless as assertions — nobody knows
how many turns are truly in a real thermal. These fly exact geometry instead: a
40 m circle every 20 s climbing at 2 m/s has 10 turns in 200 s, by construction.
"""

import datetime as dt
import math

import numpy as np
import pytest

from tracklog_viewer import igc
from tracklog_viewer.analysis import Phase, analyse
from tracklog_viewer.geo import R

LAT0, LON0 = 49.0, 14.0


def to_latlon(x: float, y: float) -> tuple[float, float]:
    """Inverse of flight.local_frame: metres east/north back to degrees."""
    lat = LAT0 + math.degrees(y / R)
    lon = LON0 + math.degrees(x / (R * math.cos(math.radians(LAT0))))
    return lat, lon


def build(path, points, *, start=dt.time(12, 0, 0)):
    """Write a synthetic IGC file from (seconds, x, y, altitude) tuples."""
    lines = ["AXCT000", "HFDTE010726", "HFPLTPILOTINCHARGE:Test", "HFPRSPRESSALTSENSOR:synthetic"]
    base = start.hour * 3600 + start.minute * 60 + start.second
    for seconds, x, y, alt in points:
        lat, lon = to_latlon(x, y)
        clock = int(base + seconds)
        hh, mm, ss = clock // 3600, (clock // 60) % 60, clock % 60
        lat_deg, lon_deg = int(abs(lat)), int(abs(lon))
        lat_min = round((abs(lat) - lat_deg) * 60000)
        lon_min = round((abs(lon) - lon_deg) * 60000)
        lines.append(
            f"B{hh:02d}{mm:02d}{ss:02d}"
            f"{lat_deg:02d}{lat_min:05d}N{lon_deg:03d}{lon_min:05d}E"
            f"A{int(round(alt)):05d}{int(round(alt)):05d}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def circling(duration, *, radius=40.0, period=20.0, climb=2.0, drift=(0.0, 0.0), t0=0.0, alt0=1000.0,
             clockwise=True, x0=0.0, y0=0.0):
    """Fixes for a glider circling, optionally drifting with the air."""
    points = []
    for second in range(int(duration) + 1):
        angle = 2 * math.pi * second / period * (1 if clockwise else -1)
        x = x0 + radius * math.sin(angle) + drift[0] * second
        y = y0 + radius * math.cos(angle) + drift[1] * second
        points.append((t0 + second, x, y, alt0 + climb * second))
    return points


def straight(duration, *, speed=11.0, climb=0.0, t0=0.0, alt0=1000.0, x0=0.0, y0=0.0, heading=0.0):
    """Fixes for a glider flying straight. Speed in m/s, heading in degrees."""
    points = []
    for second in range(int(duration) + 1):
        distance = speed * second
        x = x0 + distance * math.sin(math.radians(heading))
        y = y0 + distance * math.cos(math.radians(heading))
        points.append((t0 + second, x, y, alt0 + climb * second))
    return points


class TestTurnCounting:
    def test_counts_exact_circles(self, tmp_path):
        """200 s at 20 s per circle is 10 turns."""
        flight = igc.parse(build(tmp_path / "t.igc", circling(200)))
        thermal = analyse(flight).thermals[0]
        assert thermal.turns == pytest.approx(10.0, abs=0.4)
        assert thermal.circle_seconds == pytest.approx(20.0, abs=1.0)

    def test_reports_turn_direction(self, tmp_path):
        right = analyse(igc.parse(build(tmp_path / "r.igc", circling(200)))).thermals[0]
        left = analyse(
            igc.parse(build(tmp_path / "l.igc", circling(200, clockwise=False)))
        ).thermals[0]
        assert right.turn_direction == "right"
        assert left.turn_direction == "left"
        assert right.reversals == 0

    def test_counts_reversals_when_direction_changes(self, tmp_path):
        points = circling(100)
        points += circling(100, t0=101, alt0=points[-1][3], clockwise=False)
        thermal = analyse(igc.parse(build(tmp_path / "s.igc", points))).thermals[0]
        assert thermal.turn_direction == "mixed"
        assert thermal.reversals >= 1

    def test_recovers_circle_radius(self, tmp_path):
        flight = igc.parse(build(tmp_path / "t.igc", circling(200, radius=60.0)))
        assert analyse(flight).thermals[0].circle_radius == pytest.approx(60, abs=12)


class TestWind:
    def test_recovers_drift_as_wind(self, tmp_path):
        """A thermal drifting east at 4 m/s means a 4 m/s wind from the west."""
        flight = igc.parse(build(tmp_path / "w.igc", circling(300, drift=(4.0, 0.0))))
        wind = analyse(flight).thermals[0].wind
        assert wind.speed == pytest.approx(4.0, abs=0.4)
        assert wind.direction == pytest.approx(270.0, abs=8.0)
        assert wind.cardinal == "W"

    def test_recovers_northerly(self, tmp_path):
        flight = igc.parse(build(tmp_path / "n.igc", circling(300, drift=(0.0, -3.0))))
        wind = analyse(flight).thermals[0].wind
        assert wind.direction == pytest.approx(0.0, abs=8.0) or wind.direction == pytest.approx(
            360.0, abs=8.0
        )
        assert wind.cardinal == "N"

    def test_still_air_reads_calm(self, tmp_path):
        flight = igc.parse(build(tmp_path / "c.igc", circling(300)))
        assert analyse(flight).thermals[0].wind.speed < 0.5


class TestPhases:
    def test_circling_climb_is_a_thermal(self, tmp_path):
        analysis = analyse(igc.parse(build(tmp_path / "t.igc", circling(200))))
        assert [s.phase for s in analysis.segments] == [Phase.THERMAL]
        assert analysis.thermals[0].average_climb == pytest.approx(2.0, abs=0.1)
        assert analysis.thermals[0].altitude_change == pytest.approx(400, abs=10)

    def test_straight_glide_gives_glide_ratio(self, tmp_path):
        # 10 m/s forward, 1 m/s down for 300 s: glide ratio 10:1.
        flight = igc.parse(build(tmp_path / "g.igc", straight(300, speed=10.0, climb=-1.0)))
        glide = analyse(flight).glides[0]
        assert glide.average_ld == pytest.approx(10.0, abs=0.3)
        assert glide.average_speed == pytest.approx(36.0, abs=1.0)

    def test_launch_climb_flown_straight_is_a_tow(self, tmp_path):
        """A winch or aerotow launch, not a thermal off the deck."""
        points = straight(180, speed=8.0, climb=3.0, alt0=400.0)
        points += straight(300, speed=10.0, climb=-1.0, t0=181, alt0=points[-1][3], x0=1440.0)
        analysis = analyse(igc.parse(build(tmp_path / "tow.igc", points)))
        tow = analysis.tow
        assert tow is not None
        assert tow.phase is Phase.TOW
        assert tow.average_climb == pytest.approx(3.0, abs=0.2)
        assert tow.finish_altitude == pytest.approx(940, abs=15)
        assert analysis.thermals == []  # not counted as a thermal
        assert tow.wind is None  # a straight climb says nothing about the wind
        assert tow.efficiency is None

    def test_straight_climb_later_in_the_flight_is_not_a_tow(self, tmp_path):
        """Only the launch can be a tow — mid-flight it is convergence or ridge lift."""
        points = circling(200, climb=2.0, alt0=1000.0)
        points += straight(200, speed=10.0, climb=2.0, t0=201, alt0=points[-1][3])
        analysis = analyse(igc.parse(build(tmp_path / "late.igc", points)))
        assert analysis.tow is None
        assert all(s.phase is not Phase.TOW for s in analysis.segments)

    def test_tow_is_refused_when_sampling_cannot_resolve_one(self, tmp_path):
        """The same straight launch climb, sampled every 40 s instead of every second.

        At that spacing the whole launch is a handful of points, every corner in the track
        has been cut, and `progress` reads as straight everywhere — so the straightness
        test that identifies a tow has nothing left to measure. An XContest KMZ of a long
        flight is sampled at 83 s and was reported as a winch launch releasing at 4574 m.
        """
        points = straight(600, speed=8.0, climb=3.0, alt0=400.0)
        points += straight(600, speed=10.0, climb=-1.0, t0=601, alt0=points[-1][3],
                           x0=4800.0)
        coarse = points[::40]
        analysis = analyse(igc.parse(build(tmp_path / "coarse.igc", coarse)))
        assert analysis.summary.sample_interval > 15
        assert analysis.tow is None
        assert all(s.phase is not Phase.TOW for s in analysis.segments)

        fine = analyse(igc.parse(build(tmp_path / "fine.igc", points)))
        assert fine.tow is not None, "the same flight at 1 Hz is still a tow"

    def test_circling_climb_at_launch_stays_a_thermal(self, tmp_path):
        """Soarable launch: climbing away in circles immediately is not a tow."""
        analysis = analyse(igc.parse(build(tmp_path / "soar.igc", circling(300, alt0=400.0))))
        assert analysis.tow is None
        assert len(analysis.thermals) == 1


class TestBudgetAndSummary:
    def test_budget_accounts_for_the_whole_flight(self, tmp_path):
        points = circling(200)
        points += straight(300, speed=10.0, climb=-1.0, t0=201, alt0=points[-1][3])
        analysis = analyse(igc.parse(build(tmp_path / "b.igc", points)))
        assert analysis.budget.total == analysis.summary.duration
        assert analysis.budget.thermalling > 0
        assert analysis.budget.gliding > 0
        assert sum(analysis.budget.fractions().values()) == pytest.approx(1.0)

    def test_summary_distances(self, tmp_path):
        flight = igc.parse(build(tmp_path / "d.igc", straight(300, speed=10.0, climb=-1.0)))
        summary = analyse(flight).summary
        assert summary.track_distance == pytest.approx(3000, abs=20)
        assert summary.straight_distance == pytest.approx(3000, abs=20)
        assert summary.max_altitude == 1000
        assert summary.min_altitude == 700

    def test_total_gain_accumulates_only_climbs(self, tmp_path):
        points = circling(100, climb=2.0)
        points += straight(100, speed=10.0, climb=-2.0, t0=101, alt0=points[-1][3])
        summary = analyse(igc.parse(build(tmp_path / "gain.igc", points))).summary
        assert summary.total_gain == pytest.approx(200, abs=10)
        assert summary.max_gain == pytest.approx(200, abs=10)

    def test_serialises_to_plain_data(self, tmp_path):
        analysis = analyse(igc.parse(build(tmp_path / "j.igc", circling(200))))
        data = analysis.to_dict()
        assert data["segments"][0]["phase"] == "thermal"
        assert isinstance(data["summary"]["duration"], int)
        assert set(data["budget"]["fractions"]) == {
            "thermalling", "gliding", "diving", "towing", "other",
        }


class TestSeries:
    def test_total_energy_ignores_speed_traded_for_height(self, tmp_path):
        """Pulling up converts speed into height; TE climb should not see a climb."""
        # Decelerate from 20 m/s to 5 m/s while gaining the matching energy height.
        points = []
        x = 0.0
        alt = 1000.0
        for second in range(61):
            speed = 20.0 - 15.0 * second / 60
            x += speed
            alt += (20.0**2 - speed**2) / (2 * 9.80665) - (alt - 1000.0)
            points.append((second, x, 0.0, 1000.0 + (20.0**2 - speed**2) / (2 * 9.80665)))
        flight = igc.parse(build(tmp_path / "te.igc", points))
        from tracklog_viewer.flight import derive

        series = derive(flight)
        middle = slice(10, 50)
        assert np.mean(series.climb[middle]) > 0.1  # barometrically, a climb
        assert abs(np.mean(series.te_climb[middle])) < 0.1  # energetically, nothing


class TestWindShearNote:
    def test_two_climbs_at_the_same_altitude_do_not_break_the_note(self, tmp_path):
        """A bare sort() on (altitude, wind) pairs falls through to comparing Wind objects
        when two climbs share a mean altitude, which is not orderable. That took down the
        whole report on a real flight with eighteen climbs."""
        from tracklog_viewer import render_html

        points = []
        t = 0
        # Three identical circled climbs, so their mean altitudes match exactly.
        for _ in range(3):
            points += circling(240, t0=t, alt0=1000.0, x0=0.0)
            t = points[-1][0] + 1
            points += straight(200, speed=10.0, climb=-1.5, t0=t, alt0=points[-1][3])
            t = points[-1][0] + 1
        analysis = analyse(igc.parse(build(tmp_path / "flat.igc", points)))
        altitudes = [
            (s.start_altitude + s.finish_altitude) / 2
            for s in analysis.thermals if s.wind and s.turns and s.turns >= 2
        ]
        assert len(altitudes) != len(set(altitudes)), "the fixture must produce a tie"
        render_html._wind_shear_note(analysis)   # raised TypeError before the key= fix


class TestThermalStartsWhenTurningDoes:
    """A thermal is the circling, not the run-in to it.

    Wind is fitted as the drift of a circling glider, so any straight flight inside the
    phase is measured as though it were moving air. On a real Dolomites flight that
    produced 18 km/h "from the east" out of a climb whose first 30 s of 70 was a straight
    westward run, and 22 km/h out of a 242 s "thermal" that was two climbs with a 90 s
    glide welded between them.

    Every flight here opens with a glide, deliberately: a straight climb inside the first
    two minutes is a candidate *tow* and is admitted on purpose, so testing the run-in
    rule at t=0 tests the wrong rule.
    """

    @staticmethod
    def _glide_then_runin_then_circle(tmp_path, name):
        points = straight(180, speed=12.0, climb=-1.0, alt0=1500.0, heading=0.0)
        points += straight(90, speed=10.0, climb=1.5, t0=181, alt0=points[-1][3],
                           x0=0.0, y0=2160.0, heading=90.0)
        points += circling(200, climb=2.0, t0=272, alt0=points[-1][3],
                           x0=900.0, y0=2160.0)
        return analyse(igc.parse(build(tmp_path / name, points)))

    def test_a_straight_run_in_is_not_part_of_the_thermal(self, tmp_path):
        analysis = self._glide_then_runin_then_circle(tmp_path, "runin.igc")
        assert len(analysis.thermals) == 1
        thermal = analysis.thermals[0]
        # 90 s of straight climbing precede the first turn. The phase must begin at the
        # turn, not at the lift.
        assert analysis.series.t[thermal.start] >= 255, (
            "the straight climb into the thermal was counted as part of it")
        # And with the run-in excluded the drift is what it should be: nothing.
        assert thermal.wind is not None
        assert thermal.wind.kmh < 4.0, (
            f"a straight run-in leaked into the wind fit: {thermal.wind.kmh:.1f} km/h")

    def test_the_glide_ends_where_the_climb_begins(self, tmp_path):
        """Not when progress finally breaks, which is well after the air started giving
        something back. The straight climb between is neither glide nor thermal, and the
        time budget already has a bucket for exactly that."""
        analysis = self._glide_then_runin_then_circle(tmp_path, "other.igc")
        assert len(analysis.glides) == 1
        glide = analysis.glides[0]
        assert analysis.series.t[glide.stop - 1] <= 200, (
            "the glide ran on into the climb")
        assert analysis.budget.other >= 60, (
            "the straight climb should be accounted as other, not as a phase")

    def test_a_glide_through_lift_does_not_weld_two_thermals_into_one(self, tmp_path):
        """A straight run through a lift band satisfied the old `climb > 1.0` clause
        outright, so the whole 150 s transition was "thermal" and the two climbs either
        side of it became one segment 1.8 km long. Its drift is the transition, not the
        air — which is how a 22 km/h wind appeared in a 5 km/h day."""
        points = circling(160, climb=2.0, alt0=1000.0)
        points += straight(150, speed=12.0, climb=1.2, t0=161,
                           alt0=points[-1][3], heading=90.0)
        points += circling(160, climb=2.0, t0=312, alt0=points[-1][3], x0=1800.0)
        analysis = analyse(igc.parse(build(tmp_path / "welded.igc", points)))

        assert len(analysis.thermals) == 2, (
            "the glide between the two climbs was absorbed into one thermal")
        for thermal in analysis.thermals:
            assert thermal.wind is None or thermal.wind.kmh < 5.0, (
                "the glide between the climbs was measured as wind")

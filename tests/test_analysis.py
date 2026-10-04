"""Analysis tests built on synthetic flights with known answers.

Real tracklogs are good for smoke tests but useless as assertions — nobody knows
how many turns are truly in a real thermal. These fly exact geometry instead: a
40 m circle every 20 s climbing at 2 m/s has 10 turns in 200 s, by construction.
"""

import datetime as dt
import math

import numpy as np
import pytest

from tests import js
from tests.js import needs_node

pytestmark = needs_node

R = 6371000.0          # the FAI sphere, as `js/geo.js`

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


def slalom(duration, *, radius=40.0, period=20.0, climb=2.0, t0=0.0, alt0=1000.0,
           x0=0.0, y0=0.0):
    """Fixes for a glider swinging the nose without ever completing a circle.

    Half a circle one way, half a circle back, for as long as you like: the heading
    sweeps 180° at a time and comes back, which is the shape of a wingover or a slalom
    along a ridge. Summing |Δheading| calls this a turn every 20 s; no circle is flown.

    `x0`/`y0` place it, which matters the moment the ground under it does: the terrain
    tests fly this over a synthetic slope and the answer depends on which part of the
    slope it is over.
    """
    speed = 2 * math.pi * radius / period
    points, heading, x, y = [], 0.0, x0, y0
    for second in range(int(duration) + 1):
        points.append((t0 + second, x, y, alt0 + climb * second))
        way = 1 if int(second // (period / 2)) % 2 == 0 else -1
        heading += way * 2 * math.pi / period
        x += speed * math.sin(heading)
        y += speed * math.cos(heading)
    return points


def beat(duration, *, bearing=0.0, leg=45.0, radius=25.0, speed=11.0, climb=0.8,
         t0=0.0, alt0=1000.0, x0=0.0, y0=0.0):
    """Fixes for a glider working a ridge: a straight beat, a 180, a beat back.

    This is what ridge soaring looks like from above and `circling` is what thermalling
    looks like, and the difference between them is the whole of what the climb classifier
    reads. The 180s alternate hands — a pilot turns *away* from the hill at each end —
    which matters to the measurement rather than only to the picture: two same-handed
    180s either side of a straight leg are one stretched circle, and `_revolutions` is
    right to count them as one. Alternating, no run of heading ever reaches 360, and the
    climb scores no complete turns at all.

    The alternation costs a slow sideways walk of about `4 * radius` per cycle, which is
    real — a glider that turns away from the slope at both ends does drift off it, and a
    pilot spends the beat correcting back in. The fixtures keep `duration` short enough
    that the walk stays inside the hill it is flown over.
    """
    half = math.pi * radius / speed        # seconds to swing 180° at this radius
    cycle = 2 * (leg + half)
    points, heading, x, y = [], math.radians(bearing), x0, y0
    for second in range(int(duration) + 1):
        points.append((t0 + second, x, y, alt0 + climb * second))
        at = second % cycle
        if at < leg or leg + half <= at < 2 * leg + half:
            rate = 0.0                      # straight along the ridge
        elif at < leg + half:
            rate = math.pi / half           # the turn at one end
        else:
            rate = -math.pi / half          # and the other way at the other
        heading += rate
        x += speed * math.sin(heading)
        y += speed * math.cos(heading)
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
        path = build(tmp_path / "t.igc", circling(200))
        thermal = js.analyse(path).thermals[0]
        assert thermal.turns == pytest.approx(10.0, abs=0.4)
        assert thermal.circle_seconds == pytest.approx(20.0, abs=1.0)

    def test_reports_turn_direction(self, tmp_path):
        right = js.analyse(build(tmp_path / "r.igc", circling(200))).thermals[0]
        left = js.analyse(build(tmp_path / "l.igc", circling(200, clockwise=False))
        ).thermals[0]
        assert right.turn_direction == "right"
        assert left.turn_direction == "left"
        assert right.reversals == 0

    def test_counts_reversals_when_direction_changes(self, tmp_path):
        points = circling(100)
        points += circling(100, t0=101, alt0=points[-1][3], clockwise=False)
        thermal = js.analyse(build(tmp_path / "s.igc", points)).thermals[0]
        assert thermal.turn_direction == "mixed"
        assert thermal.reversals >= 1
        # Five circles each way is ten circles flown: a reversal does not cancel the
        # ones already flown, which counting net rotation would have it do.
        assert thermal.turns == pytest.approx(10.0, abs=0.8)

    def test_swinging_the_nose_is_not_a_turn(self, tmp_path):
        """A wingover, or a slalom: 180° out and 180° back, over and over, no circle."""
        thermal = js.analyse(build(tmp_path / "w.igc", slalom(200))).thermals[0]
        assert thermal.turns == 0.0
        # 200 s of half-circles at 10 s each is 20 of them: ten turns' worth of heading
        # for no circles at all. That is what the tow test asks about, so it has to stay
        # visible somewhere — and it is exactly what the old count reported as `turns`.
        assert thermal.swept_turns == pytest.approx(10.0, abs=0.6)
        assert thermal.circle_seconds is None

    def test_a_part_circle_is_not_a_turn(self, tmp_path):
        """Three quarters of a circle and out again: 0.75 of a turn is not a turn."""
        points = circling(15)  # 15 s of a 20 s circle
        points += straight(120, speed=11.0, climb=-1.0, t0=16, alt0=points[-1][3])
        thermals = js.analyse(build(tmp_path / "p.igc", points)).thermals
        assert all(t.turns == 0.0 for t in thermals)

    def test_recovers_circle_radius(self, tmp_path):
        path = build(tmp_path / "t.igc", circling(200, radius=60.0))
        assert js.analyse(path).thermals[0].circle_radius == pytest.approx(60, abs=12)


class TestWind:
    def test_recovers_drift_as_wind(self, tmp_path):
        """A thermal drifting east at 4 m/s means a 4 m/s wind from the west."""
        path = build(tmp_path / "w.igc", circling(300, drift=(4.0, 0.0)))
        wind = js.analyse(path).thermals[0].wind
        assert wind.speed == pytest.approx(4.0, abs=0.4)
        assert wind.direction == pytest.approx(270.0, abs=8.0)
        assert wind.cardinal == "W"

    def test_recovers_northerly(self, tmp_path):
        path = build(tmp_path / "n.igc", circling(300, drift=(0.0, -3.0)))
        wind = js.analyse(path).thermals[0].wind
        assert wind.direction == pytest.approx(0.0, abs=8.0) or wind.direction == pytest.approx(
            360.0, abs=8.0
        )
        assert wind.cardinal == "N"

    def test_still_air_reads_calm(self, tmp_path):
        path = build(tmp_path / "c.igc", circling(300))
        assert js.analyse(path).thermals[0].wind.speed < 0.5


class TestPhases:
    def test_circling_climb_is_a_thermal(self, tmp_path):
        analysis = js.analyse(build(tmp_path / "t.igc", circling(200)))
        assert [s.phase for s in analysis.segments] == ["thermal"]
        assert analysis.thermals[0].average_climb == pytest.approx(2.0, abs=0.1)
        assert analysis.thermals[0].altitude_change == pytest.approx(400, abs=10)

    def test_straight_glide_gives_glide_ratio(self, tmp_path):
        # 10 m/s forward, 1 m/s down for 300 s: glide ratio 10:1.
        path = build(tmp_path / "g.igc", straight(300, speed=10.0, climb=-1.0))
        glide = js.analyse(path).glides[0]
        assert glide.average_ld == pytest.approx(10.0, abs=0.3)
        assert glide.average_speed == pytest.approx(36.0, abs=1.0)

    def test_launch_climb_flown_straight_is_a_tow(self, tmp_path):
        """A winch or aerotow launch, not a thermal off the deck."""
        points = straight(180, speed=8.0, climb=3.0, alt0=400.0)
        points += straight(300, speed=10.0, climb=-1.0, t0=181, alt0=points[-1][3], x0=1440.0)
        analysis = js.analyse(build(tmp_path / "tow.igc", points))
        tow = analysis.tow
        assert tow is not None
        assert tow.phase == "tow"
        assert tow.average_climb == pytest.approx(3.0, abs=0.2)
        assert tow.finish_altitude == pytest.approx(940, abs=15)
        assert analysis.thermals == []  # not counted as a thermal
        assert tow.wind is None  # a straight climb says nothing about the wind
        assert tow.efficiency is None

    def test_straight_climb_later_in_the_flight_is_not_a_tow(self, tmp_path):
        """Only the launch can be a tow — mid-flight it is convergence or ridge lift."""
        points = circling(200, climb=2.0, alt0=1000.0)
        points += straight(200, speed=10.0, climb=2.0, t0=201, alt0=points[-1][3])
        analysis = js.analyse(build(tmp_path / "late.igc", points))
        assert analysis.tow is None
        assert all(s.phase != "tow" for s in analysis.segments)

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
        analysis = js.analyse(build(tmp_path / "coarse.igc", coarse))
        assert analysis.summary.sample_interval > 15
        assert analysis.tow is None
        assert all(s.phase != "tow" for s in analysis.segments)

        fine = js.analyse(build(tmp_path / "fine.igc", points))
        assert fine.tow is not None, "the same flight at 1 Hz is still a tow"

    def test_circling_climb_at_launch_stays_a_thermal(self, tmp_path):
        """Soarable launch: climbing away in circles immediately is not a tow."""
        analysis = js.analyse(build(tmp_path / "soar.igc", circling(300, alt0=400.0)))
        assert analysis.tow is None
        assert len(analysis.thermals) == 1


class TestBudgetAndSummary:
    def test_budget_accounts_for_the_whole_flight(self, tmp_path):
        points = circling(200)
        points += straight(300, speed=10.0, climb=-1.0, t0=201, alt0=points[-1][3])
        analysis = js.analyse(build(tmp_path / "b.igc", points))
        assert analysis.budget.total == analysis.summary.duration
        assert analysis.budget.thermalling > 0
        assert analysis.budget.gliding > 0
        assert sum(analysis.budget.fractions.values()) == pytest.approx(1.0)

    def test_summary_distances(self, tmp_path):
        path = build(tmp_path / "d.igc", straight(300, speed=10.0, climb=-1.0))
        summary = js.analyse(path).summary
        assert summary.track_distance == pytest.approx(3000, abs=20)
        assert summary.straight_distance == pytest.approx(3000, abs=20)
        assert summary.max_altitude == 1000
        assert summary.min_altitude == 700

    def test_total_gain_accumulates_only_climbs(self, tmp_path):
        points = circling(100, climb=2.0)
        points += straight(100, speed=10.0, climb=-2.0, t0=101, alt0=points[-1][3])
        summary = js.analyse(build(tmp_path / "gain.igc", points)).summary
        assert summary.total_gain == pytest.approx(200, abs=10)
        assert summary.max_gain == pytest.approx(200, abs=10)

    def test_serialises_to_plain_data(self, tmp_path):
        data = js.run("return TV.analysis.toDict(TV.analysis.analyse(await load(input.path)));",
                      path=build(tmp_path / "j.igc", circling(200)))
        assert data["segments"][0]["phase"] == "thermal"
        assert float(data["summary"]["duration"]).is_integer()
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
        series = js.run("return TV.flight.derive(await load(input.path));",
                        path=build(tmp_path / "te.igc", points))
        middle = slice(10, 50)
        assert np.mean(series.climb[middle]) > 0.1  # barometrically, a climb
        assert abs(np.mean(series.te_climb[middle])) < 0.1  # energetically, nothing


class TestWindShearNote:
    def test_two_climbs_at_the_same_altitude_do_not_break_the_note(self, tmp_path):
        """A bare sort() on (altitude, wind) pairs falls through to comparing Wind objects
        when two climbs share a mean altitude, which is not orderable. That took down the
        whole report on a real flight with eighteen climbs."""
        points = []
        t = 0
        # Three identical circled climbs, so their mean altitudes match exactly.
        for _ in range(3):
            points += circling(240, t0=t, alt0=1000.0, x0=0.0)
            t = points[-1][0] + 1
            points += straight(200, speed=10.0, climb=-1.5, t0=t, alt0=points[-1][3])
            t = points[-1][0] + 1
        analysis = js.analyse(build(tmp_path / "flat.igc", points))
        altitudes = [
            (s.start_altitude + s.finish_altitude) / 2
            for s in analysis.thermals if s.wind and s.turns and s.turns >= 2
        ]
        assert len(altitudes) != len(set(altitudes)), "the fixture must produce a tie"
        js.run("return TV.report.parts.windShearNote(TV.analysis.analyse(await load(input.path)));",
               path=tmp_path / "flat.igc")   # Python raised TypeError here before the key= fix

    def test_the_note_speaks_in_the_unit_the_wind_is_stored_in(self):
        """`Wind.speed` is m/s. The note printed those numbers as km/h and gated on a
        km/h threshold, so a 2 m/s shear read as "about 3 km/h throughout"."""
        def climb(alt, speed):
            return {"phase": "thermal", "start_altitude": alt, "finish_altitude": alt, "turns": 3,
                    "wind": {"speed": speed, "direction": 270.0}}

        def note(speeds):
            segments = [climb(1000 + 500 * i, v) for i, v in enumerate(speeds)]
            return js.run("return TV.report.parts.windShearNote({ segments: input.segments });",
                          segments=segments)
        assert note([3.0, 3.2, 3.4, 3.5]).startswith("about 3.1 m/s throughout")
        note = note([2.0, 2.2, 4.0, 4.4])
        assert "km/h" not in note and note.endswith("2.1 m/s stronger with height."), note


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
        return js.analyse(build(tmp_path / name, points))

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
        assert thermal.wind.speed * 3.6 < 4.0, (
            f"a straight run-in leaked into the wind fit: {thermal.wind.speed * 3.6:.1f} km/h")

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
        analysis = js.analyse(build(tmp_path / "welded.igc", points))

        assert len(analysis.thermals) == 2, (
            "the glide between the two climbs was absorbed into one thermal")
        for thermal in analysis.thermals:
            assert thermal.wind is None or thermal.wind.speed * 3.6 < 5.0, (
                "the glide between the climbs was measured as wind")


class TestOtherDecomposition:
    """The unclassified slice, split three ways.

    The plan's first correction: `other` is not a loss. On the reference flight it nets
    +385 m, because `classify` deliberately pushes the straight run-in to a climb and
    everything outside the sustained circling into exactly this bucket.
    """

    def test_the_parts_reconstruct_the_slice(self, tmp_path):
        """The identity the whole decomposition rests on, asserted rather than assumed.

        Charging *gaps between fixes* rather than fixes is what makes this exact; a
        sample-counting version double-counts every phase boundary.
        """
        points = circling(160, climb=2.0, alt0=1000.0)
        points += straight(150, speed=12.0, climb=1.2, t0=161,
                           alt0=points[-1][3], heading=90.0)
        points += straight(200, speed=12.0, climb=-1.2, t0=312,
                           alt0=points[-1][3], heading=90.0)
        analysis = js.analyse(build(tmp_path / "recon.igc", points))
        other = analysis.other

        assert other.straight_sink + other.scratching + other.rising == other.seconds
        assert other.seconds == analysis.budget.other
        assert analysis.budget.total == analysis.summary.duration

    def test_a_straight_climb_lands_in_rising_not_in_loss(self, tmp_path):
        """The correction itself.

        A straight run through lift is refused as a thermal — that rule is what keeps the
        wind estimate honest — so it lands here. Publishing this slice as "time lost"
        would be the first confidently wrong sentence in the report: this one gains height.
        """
        points = straight(240, speed=12.0, climb=1.0, alt0=1000.0, heading=90.0)
        analysis = js.analyse(build(tmp_path / "rising.igc", points))
        other = analysis.other

        assert other.rising > other.straight_sink + other.scratching
        assert other.net_altitude > 0, "a climbing slice was reported as a loss"
        assert other.mean_climb > 0
        assert other.fractions["rising"] > 0.8

    def test_a_straight_glide_is_charged_to_straight_sink(self, tmp_path):
        """Short enough that no GLIDE phase claims it, so it falls to the slice."""
        points = straight(90, speed=12.0, climb=-1.5, alt0=2000.0, heading=90.0)
        other = js.analyse(build(tmp_path / "sink.igc", points)).other

        assert other.straight_sink > other.rising
        assert other.net_altitude < 0

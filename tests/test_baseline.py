"""The archive, on fixtures of summary JSON.

`docs/analysis-plan.md` is explicit that tracklogs stay out of the repository and archive
baselines are fixtures of summary JSON. That is not only a size decision — it is what
makes these tests possible at all, since no flights ship here.

The behaviour worth pinning is the cold start. An archive of one flight must say nothing
rather than rank a flight against itself, and every accessor has to return None rather
than a number that would read as a judgement.
"""

import json

import pytest

from tracklog_viewer import baseline


def entry(date, **fields):
    payload = {
        "date": date, "takeoff_time": "12:00:00", "site": "Test", "duration": 7200, "airtime_climbing": 2000,
        "climbs": 10, "mean_climb": 1.0, "best_climb": 2.0, "total_gain": 2000,
        "max_altitude": 2500, "track_km": 80.0, "scored_km": 50.0, "glide_ld": 8.0,
        "weak_climb_share": 0.4, "centring_ratio": 0.9, "day_slope": -0.1,
        "detour_ratio": 1.6, "ceiling_used": 0.8, "wind_kmh": 10.0,
        "sample_interval": 1.0, "format": baseline.FORMAT,
    }
    payload.update(fields)
    return payload


def archive(tmp_path, flights):
    directory = tmp_path / "arch"
    directory.mkdir()
    for i, flight in enumerate(flights):
        (directory / f"{i:03d}.json").write_text(json.dumps(flight), encoding="utf-8")
    return directory


class TestColdStart:
    """One flight has no percentiles, and saying so is the honest answer."""

    def test_an_empty_archive_is_not_usable(self, tmp_path):
        assert not baseline.build(archive(tmp_path, [])).usable

    def test_a_single_flight_ranks_nothing(self, tmp_path):
        held = baseline.build(archive(tmp_path, [entry("2026-01-01")]))
        assert len(held) == 1
        assert not held.usable
        assert held.percentile_of("mean_climb", 1.0) is None
        assert held.median("mean_climb") is None
        assert held.rank_sentence("mean_climb", 1.0, "Mean climb") is None

    def test_no_archive_at_all_is_not_an_error(self):
        held = baseline.build(None)
        assert len(held) == 0
        assert not held.usable


class TestPercentiles:
    def _held(self, tmp_path):
        return baseline.build(archive(tmp_path, [
            entry(f"2026-01-{day:02d}", mean_climb=rate)
            for day, rate in enumerate([0.5, 0.8, 1.0, 1.2, 1.5, 2.0], start=1)
        ]))

    def test_the_best_flight_lands_at_the_top(self, tmp_path):
        held = self._held(tmp_path)
        assert held.percentile_of("mean_climb", 2.0) > 0.8

    def test_the_worst_flight_lands_at_the_bottom(self, tmp_path):
        held = self._held(tmp_path)
        assert held.percentile_of("mean_climb", 0.5) < 0.2

    def test_the_median_is_the_median(self, tmp_path):
        held = self._held(tmp_path)
        assert held.median("mean_climb") == pytest.approx(1.1, abs=0.01)

    def test_a_rank_sentence_names_the_sample_size(self, tmp_path):
        """'best of 12' and 'best of 3' are very different claims."""
        sentence = self._held(tmp_path).rank_sentence("mean_climb", 2.0, "Mean climb")
        assert sentence is not None
        assert "6 flights" in sentence
        assert "best" in sentence

    def test_a_lower_is_better_metric_is_inverted(self, tmp_path):
        """Weak-climb share is a cost: less of it is better."""
        held = baseline.build(archive(tmp_path, [
            entry(f"2026-02-{day:02d}", weak_climb_share=share)
            for day, share in enumerate([0.1, 0.2, 0.3, 0.4, 0.5, 0.9], start=1)
        ]))
        best = held.rank_sentence("weak_climb_share", 0.1, "Climb selection",
                                  higher_is_better=False)
        worst = held.rank_sentence("weak_climb_share", 0.9, "Climb selection",
                                   higher_is_better=False)
        assert "best" in best
        assert "weakest" in worst

    def test_a_metric_missing_from_most_flights_is_refused(self, tmp_path):
        """Six flights, but only two carry a scored route."""
        flights = [entry(f"2026-03-{d:02d}", scored_km=None) for d in range(1, 5)]
        flights += [entry("2026-03-05", scored_km=40.0), entry("2026-03-06", scored_km=60.0)]
        held = baseline.build(archive(tmp_path, flights))
        assert held.percentile_of("scored_km", 50.0) is None


class TestStorage:
    def test_a_summary_round_trips(self, tmp_path):
        directory = tmp_path / "arch"
        entry_ = baseline.Summary(
            date="2026-07-01", takeoff_time="12:00:00", site="Test", duration=3600, airtime_climbing=900,
            climbs=5, mean_climb=1.1, best_climb=2.2, total_gain=1200,
            max_altitude=2400, track_km=40.0, scored_km=30.0, glide_ld=8.0,
            weak_climb_share=0.3, centring_ratio=0.9, day_slope=-0.05,
            detour_ratio=1.3, ceiling_used=0.75, wind_kmh=9.0, sample_interval=1.0,
        )
        baseline.save(entry_, directory)
        held = baseline.load(directory)

        assert len(held) == 1
        assert held[0]["date"] == "2026-07-01"
        assert held[0]["mean_climb"] == 1.1

    def test_re_analysing_the_same_flight_does_not_duplicate_it(self, tmp_path):
        directory = tmp_path / "arch"
        entry_ = baseline.Summary(
            date="2026-07-01", takeoff_time="12:00:00", site="Test", duration=3600, airtime_climbing=900,
            climbs=5, mean_climb=1.1, best_climb=2.2, total_gain=1200,
            max_altitude=2400, track_km=40.0, scored_km=30.0, glide_ld=8.0,
            weak_climb_share=0.3, centring_ratio=0.9, day_slope=-0.05,
            detour_ratio=1.3, ceiling_used=0.75, wind_kmh=9.0, sample_interval=1.0,
        )
        baseline.save(entry_, directory)
        baseline.save(entry_, directory)
        assert len(baseline.load(directory)) == 1

    def test_a_corrupt_file_is_skipped_rather_than_fatal(self, tmp_path):
        """An archive is a cache the user owns; one bad file must not take the report
        down with it."""
        directory = archive(tmp_path, [entry("2026-01-01"), entry("2026-01-02")])
        (directory / "broken.json").write_text("{not json", encoding="utf-8")
        assert len(baseline.load(directory)) == 2

    def test_a_foreign_format_is_ignored(self, tmp_path):
        directory = archive(tmp_path, [entry("2026-01-01")])
        (directory / "old.json").write_text(
            json.dumps({"date": "2020-01-01", "format": 0}), encoding="utf-8")
        assert len(baseline.load(directory)) == 1

    def test_a_missing_directory_is_empty_not_an_error(self, tmp_path):
        assert baseline.load(tmp_path / "nope") == []

    def test_no_track_data_is_stored(self, tmp_path):
        """The archive is summaries. It must not become a place tracklogs live."""
        from tests.test_analysis import build, circling
        from tracklog_viewer import igc
        from tracklog_viewer.analysis import analyse

        analysis = analyse(igc.parse(build(tmp_path / "t.igc", circling(400, climb=1.5))))
        payload = baseline.summarise(analysis).to_dict()

        for key, value in payload.items():
            assert not isinstance(value, (list, dict)), (
                f"{key} carries structured data; the archive stores scalars only"
            )

    def test_two_flights_on_one_day_from_one_site_do_not_collide(self, tmp_path):
        """A pilot can fly twice in a day from the same launch.

        Keying on date and site alone silently overwrote the morning flight with the
        afternoon one, so an archive of six flights held one entry.
        """
        directory = tmp_path / "arch"
        for clock, rate in (("10:15:00", 1.0), ("15:40:00", 1.8)):
            baseline.save(
                baseline.Summary(
                    date="2026-07-01", takeoff_time=clock, site="Test", duration=3600,
                    airtime_climbing=900, climbs=5, mean_climb=rate, best_climb=2.2,
                    total_gain=1200, max_altitude=2400, track_km=40.0, scored_km=30.0,
                    glide_ld=8.0, weak_climb_share=0.3, centring_ratio=0.9,
                    day_slope=-0.05, detour_ratio=1.3, ceiling_used=0.75,
                    wind_kmh=9.0, sample_interval=1.0,
                ),
                directory,
            )
        held = baseline.load(directory)
        assert len(held) == 2, "the second flight of the day overwrote the first"
        assert {f["mean_climb"] for f in held} == {1.0, 1.8}

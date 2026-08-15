"""The threshold calibrator: what it measures, and what it refuses to measure.

`debrief.THRESHOLDS` used to be seeded from three flights and marked provisional. It is
now set from the distribution over a real archive, and this is the tool that measured it
— so the tests that matter are the ones that keep it honest: that every calibrated
threshold has a quantity behind it, that the two which cannot be measured offline are
*named* as uncalibrated rather than quietly reported as fine, and that a directory of
decimated KMZs cannot get into the distribution.

The archive itself is not here — `*.igc` is gitignored — so these run on synthetic
flights. The numbers they produce are meaningless; the shape of the report is not.
"""

import io

from tests.test_analysis import build, circling, straight
from tests.test_debrief import a_day
from tracklog_viewer import calibrate, debrief


def test_every_calibrated_threshold_has_a_quantity_behind_it():
    """A threshold in `QUANTITIES` the calibrator cannot measure is a threshold whose
    provenance comment is a story."""
    for name in calibrate.QUANTITIES:
        assert name in debrief.THRESHOLDS, f"{name} is not a threshold"


def test_every_threshold_is_either_calibrated_or_named_as_not():
    """The point of the exercise: no number in `THRESHOLDS` gets to be a round guess
    without saying so. Two are bookkeeping rather than measurements, and are listed."""
    bookkeeping = {"cards", "minimum_share", "gap_minimum_seconds", "band_ratio"}
    accounted = set(calibrate.QUANTITIES) | set(calibrate.UNCALIBRATED) | bookkeeping
    missing = set(debrief.THRESHOLDS) - accounted
    assert not missing, (
        f"{sorted(missing)} is neither calibrated, declared uncalibrated, nor "
        "bookkeeping — add it to one of the three")


def test_an_empty_archive_produces_no_percentiles():
    """Zero flights is a cold start, not a distribution: say so rather than dividing."""
    out = io.StringIO()
    calibrate.report([], out=out)
    assert "no flights" in out.getvalue()


class TestItMeasuresAFlight:
    def test_the_quantities_come_out(self, tmp_path):
        analysis = a_day(tmp_path, "cal.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        measured = calibrate.measure(analysis)
        for name in ("weak_climb_share", "other_lossy_share", "best_under"):
            assert name in measured.values, f"{name} was not measured"

    def test_the_report_names_every_offline_finding(self, tmp_path):
        analysis = a_day(tmp_path, "cal.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        out = io.StringIO()
        calibrate.report([calibrate.measure(analysis)], out=out)
        text = out.getvalue()
        for finding in calibrate.OFFLINE_FINDINGS:
            assert finding in text
        for name in calibrate.UNCALIBRATED:
            assert name in text

    def test_a_finding_on_every_flight_is_flagged(self, tmp_path):
        """The whole rule, in one assertion: fire on everything and the report says so."""
        analysis = a_day(tmp_path, "cal.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        one = calibrate.measure(analysis)
        one.fired = set(calibrate.OFFLINE_FINDINGS)
        out = io.StringIO()
        calibrate.report([one], out=out)
        assert "fires on most flights" in out.getvalue()


class TestItReadsOnlyWhatItCanTrust:
    def test_a_kmz_is_not_in_the_distribution(self, tmp_path):
        """A scoring site's KMZ is ~500 points and understates everything measured along
        the track, which is half of these thresholds. It must not move a percentile."""
        points = []
        t, alt, x = 0.0, 1000.0, 0.0
        for _ in range(3):
            leg = circling(300, climb=1.5, t0=t, alt0=alt, x0=x, y0=0.0)
            points += leg
            t, alt, x = leg[-1][0] + 1, leg[-1][3], leg[-1][1]
            run = straight(300, speed=12.0, climb=-1.0, t0=t, alt0=alt, x0=x, y0=0.0,
                           heading=90.0)
            points += run
            t, alt, x = run[-1][0] + 1, run[-1][3], run[-1][1]
        build(tmp_path / "real.igc", points)
        (tmp_path / "reduced.kmz").write_bytes(b"PK\x03\x04not really a kmz")
        (tmp_path / "reduced.kml").write_text("<kml/>", encoding="utf-8")

        measured = calibrate.read(tmp_path)
        assert len(measured) == 1, "only the IGC belongs in the distribution"

    def test_one_unreadable_file_does_not_stop_the_run(self, tmp_path):
        points = []
        t, alt, x = 0.0, 1000.0, 0.0
        for _ in range(3):
            leg = circling(300, climb=1.5, t0=t, alt0=alt, x0=x, y0=0.0)
            points += leg
            t, alt, x = leg[-1][0] + 1, leg[-1][3], leg[-1][1]
            run = straight(300, speed=12.0, climb=-1.0, t0=t, alt0=alt, x0=x, y0=0.0,
                           heading=90.0)
            points += run
            t, alt, x = run[-1][0] + 1, run[-1][3], run[-1][1]
        build(tmp_path / "good.igc", points)
        (tmp_path / "broken.igc").write_text("this is not an IGC file", encoding="utf-8")

        measured = calibrate.read(tmp_path)
        assert len(measured) == 1


def test_the_shipped_thresholds_still_gate_something(tmp_path):
    """A guard against the opposite failure: calibrating until nothing ever fires.

    This day is deliberately awful — one good climb and four weak ones with long gaps —
    and a debrief that finds nothing to say about it has been tuned into silence.
    """
    analysis = a_day(tmp_path, "awful.igc",
                     [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                     glide=900)
    result = debrief.build(analysis)
    assert result.findings, "no finding at all on a day with an obvious shape"

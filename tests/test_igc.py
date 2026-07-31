"""Parser tests. Each case is a quirk found in a real file in ~/Downloads."""

import base64
import datetime as dt
import json

import numpy as np
import pytest

from tracklog_viewer import igc
from tracklog_viewer.geo import bearing, cardinal, distance

HEADER = "AXCT1234\nHFDTEDATE:280726,00\nHFPLTPILOTINCHARGE:Ondřej Chmelař\n"
FIX = "B1053324925977N01437750EA0041000492\n"


def write(tmp_path, text, name="flight.igc"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_date_time_position_and_both_altitudes(tmp_path):
    flight = igc.parse(write(tmp_path, HEADER + FIX + "B1053334925977N01437750EA0041100493\n"))
    assert len(flight) == 2
    assert flight.headers.date == dt.date(2026, 7, 28)
    assert flight.time[0].item() == dt.datetime(2026, 7, 28, 10, 53, 32)
    # 49 + 25977/60000 and 14 + 37750/60000 — no LAD/LOD digit in this fix.
    assert flight.lat[0] == pytest.approx(49.43295, abs=1e-6)
    assert flight.lon[0] == pytest.approx(14.629167, abs=1e-6)
    assert flight.alt_baro[0] == 410
    assert flight.alt_gps[0] == 492
    assert flight.validity.all()


def test_old_style_hfdte_without_colon(tmp_path):
    """SkyDrop writes HFDTE290523; XCTrack writes HFDTEDATE:280918,01."""
    flight = igc.parse(write(tmp_path, "AXSB1\nHFDTE290523\n" + FIX))
    assert flight.headers.date == dt.date(2023, 5, 29)
    assert flight.headers.flight_of_day is None


def test_flight_of_day_is_read(tmp_path):
    flight = igc.parse(write(tmp_path, "AXCT1\nHFDTEDATE:280918,02\n" + FIX))
    assert flight.headers.date == dt.date(2018, 9, 28)
    assert flight.headers.flight_of_day == 2


def test_lad_lod_extensions_add_precision(tmp_path):
    """I023636LAD3737LOD appears in 47 of the 60 sample files."""
    plain = igc.parse(write(tmp_path, HEADER + FIX))
    text = HEADER + "I023636LAD3737LOD\n" + FIX.rstrip("\n") + "53\n"
    refined = igc.parse(write(tmp_path, text, "refined.igc"))
    assert refined.lat[0] > plain.lat[0]
    assert refined.lat[0] == pytest.approx(plain.lat[0] + 5 / 600000, abs=1e-9)
    assert refined.lon[0] == pytest.approx(plain.lon[0] + 3 / 600000, abs=1e-9)
    assert "LAD" not in refined.extensions  # consumed, not exposed


def test_southern_and_western_hemispheres(tmp_path):
    text = "AXCT1\nHFDTE010120\nB1200004925977S01437750WA0041000492\n"
    flight = igc.parse(write(tmp_path, text))
    assert flight.lat[0] < 0
    assert flight.lon[0] < 0


def test_midnight_rollover_advances_the_date(tmp_path):
    text = (
        "AXCT1\nHFDTE010120\n"
        "B2359594925977N01437750EA0041000492\n"
        "B0000014925977N01437750EA0041000492\n"
    )
    flight = igc.parse(write(tmp_path, text))
    assert flight.time[0].item().day == 1
    assert flight.time[1].item().day == 2


def test_negative_altitude_form(tmp_path):
    """Below-datum altitudes are written as -0123, not 00123."""
    text = "AXCT1\nHFDTE010120\nB1200004925977N01437750EA-0050-0012\n"
    flight = igc.parse(write(tmp_path, text))
    assert flight.alt_baro[0] == -50
    assert flight.alt_gps[0] == -12


def test_empty_and_placeholder_headers_become_none(tmp_path):
    """SkyDrop leaves these blank; XCTrack sometimes writes '?' for the site."""
    text = "AXSB1\nHFDTE010120\nHFPLTPILOTINCHARGE:\nHFGTYGLIDERTYPE:\nHOSITSite:?\n" + FIX
    flight = igc.parse(write(tmp_path, text))
    assert flight.headers.pilot is None
    assert flight.headers.glider_type is None
    assert flight.headers.site is None


def test_non_standard_source_letter_is_accepted(tmp_path):
    """XCTrack emits HSCCL, where the spec allows only F, O or P."""
    text = "AXCT1\nHFDTE010120\nHSCCLCOMPETITION CLASS:FAI-3\n" + FIX
    flight = igc.parse(write(tmp_path, text))
    assert flight.headers.competition_class == "FAI-3"


def test_junk_record_is_a_warning_not_an_exception(tmp_path):
    flight = igc.parse(write(tmp_path, HEADER + "Bnonsense\n" + FIX))
    assert len(flight) == 1
    assert any("unparseable B record" in w for w in flight.warnings)


def test_timezone_from_xctrack_device_json(tmp_path):
    payload = base64.b64encode(
        json.dumps({"os": {"timezone": "Europe/Prague"}}).encode()
    ).decode()
    chunks = "".join(f"LXCTDEVICE {payload[i:i + 20]}\n" for i in range(0, len(payload), 20))
    flight = igc.parse(write(tmp_path, HEADER + chunks + FIX))
    assert flight.timezone_source.startswith("LXCTDEVICE")
    assert flight.local_time(0).utcoffset() == dt.timedelta(hours=2)


def test_timezone_from_hftzn_header(tmp_path):
    text = "AXSB1\nHFDTE010120\nHFTZNTIMEZONE:+2.0\n" + FIX
    flight = igc.parse(write(tmp_path, text))
    assert flight.timezone_source.startswith("HFTZN")
    assert flight.local_time(0).utcoffset() == dt.timedelta(hours=2)


def test_timezone_falls_back_to_position(tmp_path):
    """Only XCTrack >= 0.9.12 records a timezone; 47 of 60 samples need this."""
    pytest.importorskip("timezonefinder")
    flight = igc.parse(write(tmp_path, HEADER + FIX))
    assert flight.timezone_source.startswith("position")
    assert "Prague" in flight.timezone_source


def test_baro_offset_reports_the_isa_discrepancy(tmp_path):
    flight = igc.parse(write(tmp_path, HEADER + FIX))
    assert flight.has_baro
    assert flight.baro_offset == pytest.approx(82.0)  # 492 - 410
    assert flight.alt is flight.alt_baro


def test_gps_altitude_is_used_when_there_is_no_baro(tmp_path):
    text = "AXCT1\nHFDTE010120\nB1200004925977N01437750EA0000000492\n"
    flight = igc.parse(write(tmp_path, text))
    assert not flight.has_baro
    assert flight.baro_offset is None
    assert flight.alt is flight.alt_gps


def test_duplicate_timestamps_are_dropped(tmp_path):
    flight = igc.parse(write(tmp_path, HEADER + FIX + FIX + FIX))
    assert len(flight) == 1
    assert flight.dropped["duplicate or backwards timestamp"] == 2


def test_altitude_spike_is_repaired_not_dropped(tmp_path):
    """36 of 60 files are GPS-altitude only; a vertical glitch must not cost us
    the horizontal fix."""
    text = "AXCT1\nHFDTE010120\n" + "".join(
        f"B1200{second:02d}4925977N01437750EA00000{9500 if second == 5 else 500:05d}\n"
        for second in range(11)
    )
    flight = igc.parse(write(tmp_path, text))
    assert len(flight) == 11  # nothing dropped
    assert flight.dropped["GPS altitude spikes repaired"] == 1
    assert flight.alt_gps[5] == 500  # replaced by the local median


def test_teleport_is_dropped(tmp_path):
    text = (
        "AXCT1\nHFDTE010120\n"
        "B1200004925977N01437750EA0041000492\n"
        "B1200015925977N01437750EA0041000492\n"  # 10 degrees north in one second
        "B1200024925978N01437750EA0041000492\n"
    )
    flight = igc.parse(write(tmp_path, text))
    assert len(flight) == 2
    assert flight.dropped["implausible ground speed"] == 1


def test_task_turnpoints_are_read_and_padding_ignored(tmp_path):
    text = (
        "AXCT1\nHFDTE010120\n"
        "C0000000000000000000000002\n"
        "C4925977N01437750ETAKEOFF\n"
        "C0000000N00000000ESTART\n"  # all-zero padding
        + FIX
    )
    flight = igc.parse(write(tmp_path, text))
    assert [tp.name for tp in flight.task] == ["TAKEOFF"]
    assert flight.task[0].lat == pytest.approx(49.43295, abs=1e-5)


def test_crlf_and_utf8_headers(tmp_path):
    path = tmp_path / "crlf.igc"
    path.write_bytes((HEADER + FIX).replace("\n", "\r\n").encode("utf-8"))
    flight = igc.parse(path)
    assert flight.headers.pilot == "Ondřej Chmelař"
    assert len(flight) == 1


def test_impossible_clock_reading_costs_only_that_fix(tmp_path):
    """Six digits always match the regex; 61 seconds is still not a time."""
    text = HEADER + "B1053614925977N01437750EA0041000492\n" + FIX
    flight = igc.parse(write(tmp_path, text))
    assert len(flight) == 1
    assert any("impossible time" in w for w in flight.warnings)


def test_no_b_records_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no valid B records"):
        igc.parse(write(tmp_path, HEADER))


class TestGeo:
    def test_distance_matches_known_separation(self):
        # One minute of latitude on the FAI sphere is 1853.2 m.
        assert distance(49.0, 14.0, 49.0 + 1 / 60, 14.0) == pytest.approx(1853.2, abs=0.5)

    def test_distance_is_precise_at_1hz_separations(self):
        """The law-of-cosines formula igc2kmz uses loses precision here."""
        d = distance(49.0, 14.0, 49.0, 14.0 + 1e-4)
        assert d == pytest.approx(7.30, abs=0.05)

    def test_bearing_cardinals(self):
        assert bearing(49.0, 14.0, 50.0, 14.0) == pytest.approx(0.0, abs=1e-6)
        assert bearing(49.0, 14.0, 49.0, 15.0) == pytest.approx(89.6, abs=0.5)
        assert cardinal(0) == "N"
        assert cardinal(90) == "E"
        assert cardinal(placeholder := 247.5) == "WSW" and placeholder
        assert cardinal(359) == "N"

    def test_vectorised(self):
        lat = np.array([49.0, 49.1])
        lon = np.array([14.0, 14.0])
        assert distance(lat[:-1], lon[:-1], lat[1:], lon[1:]).shape == (1,)

"""Input handling: KML/KMZ reading, dispatch, and XContest page recognition."""

import datetime as dt
import zipfile

import pytest

from tests import js
from tests.js import needs_node
from tracklog_viewer import sources

KML_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">'


def timed_placemarks(count: int = 60, step: int = 15) -> str:
    """XContest's shape: one Placemark per sample, with TimeStamp and Point."""
    marks = []
    for i in range(count):
        stamp = (dt.datetime(2026, 7, 28, 10, 53, 32) + dt.timedelta(seconds=i * step)).isoformat()
        marks.append(
            f"<Placemark><name>{i}</name><TimeStamp><when>{stamp}Z</when></TimeStamp>"
            f"<Point><coordinates>{14.6 + i * 0.001},{49.4 + i * 0.0005},{500 + i * 3}"
            f"</coordinates></Point></Placemark>"
        )
    return f"{KML_HEAD}<Document><name>test flight</name>{''.join(marks)}</Document></kml>"


def gx_track(count: int = 60, step: int = 1) -> str:
    """The modern shape: a gx:Track with parallel when and coord children."""
    whens, coords = [], []
    for i in range(count):
        stamp = (dt.datetime(2026, 7, 28, 10, 53, 32) + dt.timedelta(seconds=i * step)).isoformat()
        whens.append(f"<when>{stamp}Z</when>")
        coords.append(f"<gx:coord>{14.6 + i * 0.0005} {49.4 + i * 0.0002} {500 + i * 2}</gx:coord>")
    interleaved = "".join(w + c for w, c in zip(whens, coords))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">'
        f"<Document><Placemark><gx:Track>{interleaved}</gx:Track></Placemark></Document></kml>"
    )


def write_kmz(path, document: str, inner_name="doc.kml"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(inner_name, document)
    return path


def read(path):
    """The file through the page's own dispatch, with what the tests ask about."""
    return js.run("""var f = await load(input.path); f.n = f.time.length;
                     f.has_baro = TV.igc.hasBaro(f); return f;""", path=path)


@needs_node
class TestKmlReading:
    def test_timed_placemarks(self, tmp_path):
        path = tmp_path / "x.kml"
        path.write_text(timed_placemarks(), encoding="utf-8")
        flight = read(path)
        assert flight.n == 60
        assert flight.lat[0] == pytest.approx(49.4)
        assert flight.lon[0] == pytest.approx(14.6)
        assert flight.alt_gps[0] == 500
        assert not flight.has_baro  # KML never carries pressure altitude

    def test_gx_track(self, tmp_path):
        path = tmp_path / "t.kml"
        path.write_text(gx_track(), encoding="utf-8")
        flight = read(path)
        assert flight.n == 60
        assert "gx:Track" in flight.headers.logger_type

    def test_kmz_archive(self, tmp_path):
        assert read(write_kmz(tmp_path / "x.kmz", timed_placemarks())).n == 60

    def test_kmz_without_kml_is_rejected(self, tmp_path):
        path = tmp_path / "empty.kmz"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", "nothing here")
        with pytest.raises(js.JSError, match="no .kml"):
            read(path)

    def test_linestring_only_is_rejected_with_a_reason(self, tmp_path):
        """A KML with geometry but no timestamps cannot support any analysis."""
        path = tmp_path / "line.kml"
        path.write_text(
            f"{KML_HEAD}<Document><Placemark><LineString><coordinates>"
            "14.6,49.4,500 14.7,49.5,600</coordinates></LineString></Placemark></Document></kml>",
            encoding="utf-8",
        )
        with pytest.raises(js.JSError, match="no timed positions"):
            read(path)

    def test_records_the_sampling_interval_as_a_warning(self, tmp_path):
        path = tmp_path / "x.kml"
        path.write_text(timed_placemarks(step=15), encoding="utf-8")
        assert any("15 s" in w for w in read(path).warnings)

    def test_timezone_resolved_from_position(self, tmp_path):
        path = tmp_path / "x.kml"
        path.write_text(timed_placemarks(), encoding="utf-8")
        assert read(path).timezone_source.startswith("position")

    def test_out_of_order_points_are_sorted(self, tmp_path):
        marks = []
        for i in (2, 0, 1):
            stamp = (dt.datetime(2026, 7, 28, 12, 0, 0) + dt.timedelta(seconds=i * 15)).isoformat()
            marks.append(
                f"<Placemark><TimeStamp><when>{stamp}Z</when></TimeStamp>"
                f"<Point><coordinates>{14.6 + i * 0.01},49.4,{500 + i * 10}</coordinates></Point>"
                f"</Placemark>"
            )
        path = tmp_path / "x.kml"
        path.write_text(f"{KML_HEAD}<Document>{''.join(marks)}</Document></kml>", encoding="utf-8")
        flight = read(path)
        assert list(flight.time) == sorted(flight.time)


IGC = ("AXCT1\nHFDTE010726\nB1200004925977N01437750EA0041000492\n"
       "B1200014925977N01437750EA0041100493\n")


@needs_node
class TestDispatch:
    def test_igc_by_extension(self, tmp_path):
        path = tmp_path / "f.igc"
        path.write_text(IGC, encoding="utf-8")
        assert read(path).n == 2

    def test_kmz_by_extension(self, tmp_path):
        assert read(write_kmz(tmp_path / "f.kmz", timed_placemarks())).n == 60

    def test_unknown_extension_is_sniffed(self, tmp_path):
        """A download named .bin is still an IGC if it looks like one, and a KML if it
        says <kml — URLs lie about what they serve."""
        path = tmp_path / "f.bin"
        path.write_text(IGC, encoding="utf-8")
        assert read(path).n == 2
        disguised = tmp_path / "g.bin"
        disguised.write_text(timed_placemarks(), encoding="utf-8")
        assert read(disguised).n == 60

    def test_missing_file(self, tmp_path):
        with pytest.raises(sources.SourceError, match="does not exist"):
            sources.local_path(tmp_path / "nope.igc")

    def test_unrecognised_content(self, tmp_path):
        path = tmp_path / "f.bin"
        path.write_bytes(b"\x00\x01\x02 not a tracklog")
        with pytest.raises(js.JSError, match="no valid B records"):
            read(path)


class TestXContest:
    def test_detail_page_is_recognised_as_a_page_not_a_track(self):
        import urllib.parse

        parsed = urllib.parse.urlparse(
            "https://www.xcontest.org/cesko/prelety/detail:ondrej20/28.07.2026/10:53"
        )
        assert sources._is_xcontest_page(parsed)

    def test_direct_track_url_is_not_treated_as_a_page(self):
        import urllib.parse

        parsed = urllib.parse.urlparse("https://www.xcontest.org/some/path/flight.igc")
        assert not sources._is_xcontest_page(parsed)

    def test_title_parsing_extracts_the_scored_distance(self):
        html = (
            "<html><head><title>Detail přeletu : Ondřej Chmelař - 28.7.2026 - VP - "
            "64.09 km :: XContest.org - world of XC paragliding</title></head></html>"
        )
        match = sources.XC_TITLE_RE.search(html)
        assert match is not None
        assert match.group("pilot").strip() == "Ondřej Chmelař"
        assert match.group("date") == "28.7.2026"
        assert match.group("kind") == "VP"
        assert float(match.group("distance")) == 64.09

    def test_non_xcontest_host_is_left_alone(self):
        import urllib.parse

        parsed = urllib.parse.urlparse("https://example.com/flights/detail:someone/1.1.2026")
        assert not sources._is_xcontest_page(parsed)

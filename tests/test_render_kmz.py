"""KMZ output: structure, coordinate order, and the things Google Earth needs."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pytest

from tests.test_analysis import build, circling, straight
from tracklog_viewer import igc, render_kmz
from tracklog_viewer.analysis import analyse, salient

NS = "{http://www.opengis.net/kml/2.2}"


@pytest.fixture
def flight_analysis(tmp_path):
    """A tow, two circled climbs and a glide — enough to exercise every folder."""
    points = straight(180, speed=8.0, climb=3.0, alt0=400.0)
    points += straight(300, speed=10.0, climb=-1.0, t0=181, alt0=points[-1][3], x0=1440.0)
    points += circling(240, t0=482, alt0=points[-1][3], x0=4440.0)
    points += straight(300, speed=10.0, climb=-1.0, t0=723, alt0=points[-1][3], x0=4440.0)
    points += circling(240, t0=1024, alt0=points[-1][3], x0=7440.0, clockwise=False)
    return analyse(igc.parse(build(tmp_path / "f.igc", points)))


@pytest.fixture
def document(flight_analysis):
    return render_kmz.document(flight_analysis)


@pytest.fixture
def root(document):
    return ET.fromstring(document)


class TestStructure:
    def test_parses_as_xml(self, document):
        ET.fromstring(document)   # raises on malformed output

    def test_expected_folders_are_present(self, root):
        names = {folder.findtext(NS + "name") for folder in root.iter(NS + "Folder")}
        assert {"Track", "Shadow", "Climbs", "Glides", "Altitude marks", "Time marks",
                "Animation"} <= names

    def test_the_track_is_a_single_detail_level(self, root):
        """Region/Lod is ignored on mobile Earth, where stacked levels draw on top of
        one another — including a three-point coarse one."""
        assert not list(root.iter(NS + "Region"))

    def test_the_document_carries_a_summary(self, root):
        description = root.find(f"{NS}Document/{NS}description")
        assert description is not None
        assert "km flown" in description.text


class TestGeometry:
    def test_coordinates_are_lon_lat_alt(self, root, flight_analysis):
        first = next(root.iter(NS + "coordinates")).text.split()[0].split(",")
        lon, lat, alt = float(first[0]), float(first[1]), float(first[2])
        assert lon == pytest.approx(float(flight_analysis.flight.lon[0]), abs=1e-4)
        assert lat == pytest.approx(float(flight_analysis.flight.lat[0]), abs=1e-4)
        assert alt == pytest.approx(float(flight_analysis.series.alt[0]), abs=1)

    def test_coordinates_are_rounded_to_five_decimals(self, root):
        for element in list(root.iter(NS + "coordinates"))[:20]:
            for triple in element.text.split():
                for part in triple.split(",")[:2]:
                    _, _, fraction = part.partition(".")
                    assert len(fraction) <= 5

    def test_the_flown_track_is_absolute_and_the_shadow_is_clamped(self, root):
        modes = {element.text for element in root.iter(NS + "altitudeMode")}
        assert "absolute" in modes
        assert "clampToGround" in modes

    def test_one_linestring_per_colour_run_not_per_fix(self, root, flight_analysis):
        lines = list(root.iter(NS + "LineString"))
        # Far fewer lines than fixes: the whole point of batching by colour band.
        assert len(lines) < len(flight_analysis.flight) / 4


class TestBalloons:
    def test_climbs_carry_their_statistics(self, root):
        climbs = next(
            folder for folder in root.iter(NS + "Folder")
            if folder.findtext(NS + "name") == "Climbs"
        )
        data = {}
        for element in climbs.iter(NS + "Data"):
            data[element.get("name")] = element.find(NS + "value").text
        assert "average_climb" in data and "m/s" in data["average_climb"]
        assert "turns" in data
        assert "per_turn" in data

    def test_glides_carry_a_glide_ratio(self, root):
        glides = next(
            folder for folder in root.iter(NS + "Folder")
            if folder.findtext(NS + "name") == "Glides"
        )
        keys = {element.get("name") for element in glides.iter(NS + "Data")}
        assert {"ld", "distance", "average_speed"} <= keys

    def test_balloon_style_references_the_data_keys(self, document):
        assert "$[average_climb]" in document
        assert "$[ld]" in document


class TestAnimation:
    def test_timespans_drive_the_time_slider(self, root):
        spans = list(root.iter(NS + "TimeSpan"))
        assert spans, "no TimeSpan means no animation in Google Earth"
        begin = spans[0].findtext(NS + "begin")
        assert begin.endswith("Z") and "T" in begin

    def test_animation_is_sampled_not_per_fix(self, root, flight_analysis):
        spans = list(root.iter(NS + "TimeSpan"))
        assert len(spans) <= render_kmz.ANIMATION_POINTS + 1


class TestColours:
    """KML colours are aabbggrr. Writing them as rrggbb silently inverts them, which is
    how the whole track ended up drawn in blue."""

    def test_conversion_reverses_the_bytes(self):
        assert render_kmz.kml_colour("eb6834") == "ff3468eb"
        assert render_kmz.kml_colour("ffffff", 176) == "b0ffffff"

    def test_climb_ramp_runs_cool_to_warm(self):
        def rgb(colour):
            return (int(colour[6:8], 16), int(colour[4:6], 16), int(colour[2:4], 16))

        sink = rgb(render_kmz.CLIMB_BANDS[0][1])
        lift = rgb(render_kmz.CLIMB_BANDS[-1][1])
        assert sink[2] > sink[0], "the sink end must be blue, not red"
        assert lift[0] > lift[2], "the climb end must be warm, not blue"

    def test_the_solid_track_is_the_report_orange(self):
        document = render_kmz.document
        colour = render_kmz.kml_colour("eb6834")
        assert (int(colour[6:8], 16), int(colour[4:6], 16), int(colour[2:4], 16)) == (235, 104, 52)

    def test_climb_colouring_is_drawn_last(self, root):
        """A viewer that ignores per-folder visibility draws them all, and the last one
        wins where they overlap — so it has to be the useful one."""
        track = next(
            folder for folder in root.iter(NS + "Folder")
            if folder.findtext(NS + "name") == "Track"
        )
        names = [
            child.findtext(NS + "name") for child in track
            if child.tag == NS + "Folder"
        ]
        assert names[-1] == "Coloured by climb"


class TestIcons:
    def test_every_packaged_icon_is_a_real_png(self, flight_analysis, tmp_path):
        path = render_kmz.write(flight_analysis, tmp_path / "out.kmz")
        with zipfile.ZipFile(path) as archive:
            icons = [n for n in archive.namelist() if n.endswith(".png")]
            assert icons
            for name in icons:
                data = archive.read(name)
                assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG"
                # A hand-typed base64 constant once passed the signature check and still
                # had a corrupt IDAT, which Earth drew as a red X. Decode it properly.
                png = __import__("PIL.Image", fromlist=["Image"])
                png.open(__import__("io").BytesIO(data)).verify()

    def test_every_referenced_icon_is_packaged(self, flight_analysis, tmp_path):
        import re

        path = render_kmz.write(flight_analysis, tmp_path / "out.kmz")
        with zipfile.ZipFile(path) as archive:
            document = archive.read("doc.kml").decode("utf-8")
            packaged = set(archive.namelist())
        referenced = set(re.findall(r"<href>([^<]+)</href>", document))
        assert referenced, "no icons referenced at all"
        assert referenced <= packaged, f"missing from the archive: {referenced - packaged}"


class TestDescriptions:
    def test_document_description_is_plain_text(self, root):
        """Google Earth on mobile prints a Document description verbatim, so markup
        there shows up as markup."""
        description = root.find(f"{NS}Document/{NS}description").text
        assert "<" not in description

    def test_the_table_lives_on_a_placemark(self, root):
        summary = next(
            placemark for placemark in root.iter(NS + "Placemark")
            if placemark.findtext(NS + "name") == "Flight summary"
        )
        assert "<table" in summary.findtext(NS + "description")

    def test_crowded_folders_do_not_draw_labels(self, document):
        import re

        for style in ("thermal-balloon", "tow-balloon", "glide-balloon"):
            match = re.search(
                rf'id="{style}".*?<LabelStyle><scale>([\d.]+)', document, re.S
            )
            assert match and float(match.group(1)) == 0, f"{style} would label every mark"


class TestSelfContained:
    def test_no_external_references(self, document):
        # The namespace URL is not a fetch; anything else would be.
        stripped = document.replace("http://www.opengis.net/kml/2.2", "")
        assert "http://" not in stripped
        assert "https://" not in stripped

    def test_icons_are_packaged(self, flight_analysis, tmp_path):
        path = render_kmz.write(flight_analysis, tmp_path / "out.kmz")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            assert names[0] == "doc.kml", "Earth opens the first .kml in the archive"

    def test_kmz_is_a_readable_zip(self, flight_analysis, tmp_path):
        path = render_kmz.write(flight_analysis, tmp_path / "out.kmz")
        with zipfile.ZipFile(path) as archive:
            ET.fromstring(archive.read("doc.kml").decode("utf-8"))


class TestSalient:
    def test_single_hill_keeps_ends_and_peak(self):
        values = np.concatenate([np.arange(0, 500, 10), np.arange(500, 0, -10)])
        assert salient(values, 100) == [0, 50, len(values) - 1]

    def test_flat_sequence_keeps_only_the_ends(self):
        assert salient(np.zeros(50), 100) == [0, 49]

    def test_raising_the_threshold_never_adds_marks(self):
        rng = np.random.default_rng(7)
        values = np.cumsum(rng.normal(0, 12, 3000))
        counts = [len(salient(values, threshold)) for threshold in (20, 60, 150, 400)]
        assert counts == sorted(counts, reverse=True)

    def test_every_kept_swing_clears_the_threshold(self):
        rng = np.random.default_rng(11)
        values = np.cumsum(rng.normal(0, 8, 2000))
        marks = salient(values, 100)
        swings = [abs(values[b] - values[a]) for a, b in zip(marks, marks[1:])]
        # The endpoints are always kept, so the first and last swing may be short.
        interior = swings[1:-1] if len(swings) > 2 else []
        assert all(swing >= 100 for swing in interior)

    def test_short_input_is_returned_whole(self):
        assert salient([1.0, 2.0], 50) == [0, 1]

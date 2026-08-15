"""The glider's certification class: what it will claim, and what it refuses to.

This is the one part of the report that repeats someone else's safety claim, so the
tests are weighted accordingly. Most of them are about the *refusals* — a class printed
for a wing one character away from the pilot's, or for another maker's wing of the same
name, or an LTF class printed as an EN class, is worse than a blank space, because a
reader has no way to tell a looked-up class from an invented one.

The register itself is committed data fetched from the DHV and Air Turquoise; these run
against a small hand-built table wherever the shape of the rule is what matters, and
against the real one only where coverage is the point.
"""

import pytest

from tracklog_viewer import certification as cert


def entry(name, klass, *, maker="", source="DHV", addendum="", weight="",
          certificate="X-1", date="01.01.2020"):
    return cert.Certification(name=name, manufacturer=maker, source=source,
                              klass=klass, addendum=addendum, weight=weight,
                              certificate=certificate, date=date)


def table(*entries):
    return cert.index(list(entries))


class TestNormalising:
    def test_case_spacing_and_punctuation_go(self):
        assert cert.normalise("OZONE  Zeolite-2") == cert.normalise("ozone zeolite 2")

    def test_a_digit_running_into_a_letter_is_a_word_boundary(self):
        """The DHV writes "GIN Bonanza2" and the logger writes "GIN GLIDERS Bonanza 2"."""
        assert cert.normalise("Bonanza2") == cert.normalise("Bonanza 2")
        assert cert.normalise("Summit XC4") == cert.normalise("Summit XC 4")

    def test_the_model_number_survives(self):
        """"Mentor 7" and "Mentor 6" are different wings with different classes."""
        assert cert.normalise("Mentor 7") != cert.normalise("Mentor 6")


class TestSizes:
    def test_a_trailing_size_is_stripped(self):
        assert cert._model("Ozone Zeolite 2 MS") == cert._model("Ozone Zeolite 2")

    def test_a_small_number_is_part_of_the_name_and_a_large_one_is_a_size(self):
        """A wing's flat area is 15–40 m², so "27" is a size and "2" is the model."""
        assert cert._model("Aonic 2 L") == "aonic 2"
        assert cert._model("Apollo 22") == "apollo"

    def test_light_is_a_variant_and_not_a_size(self):
        """A lightweight version is its own certification, usually but not always the
        same class — folding it into the standard wing is a claim about a different one."""
        assert cert._model("Base2 Lite M") != cert._model("Base2 M")


class TestWhatItRefusesToAnswer:
    def test_sizes_certified_differently_have_no_single_class(self):
        """Advance's Sigma 10 is D in 21 and C in the larger sizes. A header with no
        size in it cannot be answered, and answering C for a pilot who might be on the
        21 is the error this module exists to avoid."""
        found = cert.lookup("Advance Sigma 10", table(
            entry("Advance Thun AG Sigma 10 21", "D"),
            entry("Advance Thun AG Sigma 10 23", "C"),
            entry("Advance Thun AG Sigma 10 25", "C"),
        ))
        assert found is None

    def test_a_named_maker_never_falls_through_to_another_maker(self):
        """Sky Paragliders make an Apollo and so does Edel. A header naming Sky must not
        be answered with Edel's row — the class would be from the wrong wing and the
        certificate would be there to prove it."""
        found = cert.lookup("SKY PARAGLIDERS Apollo", table(
            entry("Apollo 22", "2", maker="Edel Korea, HISPO Co.Ltd"),
            entry("Apollo 27", "2", maker="Edel Korea, HISPO Co.Ltd"),
        ))
        assert found is None

    def test_two_makers_with_one_model_name_and_no_maker_in_the_header(self):
        found = cert.lookup("Apollo", table(
            entry("Apollo 22", "2", maker="Edel Korea"),
            entry("Sky Paragliders a.s. Apollo XL", "B", source="Air Turquoise"),
        ))
        assert found is None

    def test_a_condition_on_the_class_is_part_of_the_class(self):
        """A class granted only with a particular harness is not the same claim as one
        granted outright, so sizes that disagree about the condition have no answer."""
        found = cert.lookup("Maker Thing", table(
            entry("Maker Thing M", "2", addendum="GH", maker="Maker"),
            entry("Maker Thing L", "2", addendum="", maker="Maker"),
        ))
        assert found is None

    def test_a_wing_that_is_simply_not_there(self):
        assert cert.lookup("Gradient Orbit 2", table(entry("NOVA Mentor 7 S", "B"))) is None

    def test_an_empty_header(self):
        assert cert.lookup("", table(entry("NOVA Mentor 7 S", "B"))) is None

    def test_there_is_no_fuzzy_match(self):
        """"Rush 6" against "Rush 5" is one character and a whole class of wing."""
        found = cert.lookup("Ozone Rush 6", table(
            entry("Ozone Gliders Rush 5 MS", "B", source="Air Turquoise"),
        ))
        assert found is None


class TestWhatItDoesAnswer:
    def test_the_maker_and_the_model_agree_across_the_sizes(self):
        found = cert.lookup("GIN GLIDERS Bonanza 2", table(
            entry("GIN Bonanza2 M", "C", maker="GIN Gliders Inc."),
            entry("GIN Bonanza2 L", "C", maker="GIN Gliders Inc."),
        ))
        assert found is not None
        assert found.klass == "C"
        assert found.label == "EN C"

    def test_the_makers_legal_name_inside_the_type_name_is_survived(self):
        """Air Turquoise publishes "Ozone Gliders LTD Alpina 4 L" and the logger writes
        "OZONE Alpina 4"."""
        found = cert.lookup("OZONE Alpina 4", table(
            entry("Ozone Gliders LTD Alpina 4 L", "C", source="Air Turquoise"),
            entry("Ozone Gliders LTD Alpina 4 M", "C", source="Air Turquoise"),
        ))
        assert found is not None and found.klass == "C"

    def test_a_company_word_the_registers_teach_it(self):
        """"Thun" is not a corporate suffix anyone would list, and without it every
        Advance wing reads as a model called "thun ag sigma 10"."""
        found = cert.lookup("ADVANCE Iota 3", table(
            entry("ADVANCE Thun AG Iota 3 23", "B", maker="ADVANCE Thun AG"),
            entry("ADVANCE Thun AG Iota 3 26", "B", maker="ADVANCE Thun AG"),
        ))
        assert found is not None and found.klass == "B"

    def test_the_newest_row_is_the_one_cited(self):
        found = cert.lookup("Maker Thing", table(
            entry("Maker Thing M", "B", maker="Maker", certificate="OLD",
                  date="01.02.2015"),
            entry("Maker Thing L", "B", maker="Maker", certificate="NEW",
                  date="03.09.2021"),
        ))
        assert found is not None and found.certificate == "NEW"


class TestTheTwoScalesAreNotOneScale:
    def test_en_wins_over_ltf_for_the_same_wing(self):
        """The DHV carries a wing as LTF 1-2 and Air Turquoise as EN B. They are not in
        conflict — one is the EN class and it is what "the class" means to a reader."""
        found = cert.lookup("NOVA Ion 5", table(
            entry("NOVA Ion 5 S", "1-2", maker="NOVA Vertriebsgesellschaft m.b.H."),
            entry("NOVA Ion 5 M", "1-2", maker="NOVA Vertriebsgesellschaft m.b.H."),
            entry("Nova Vertriebsgesellschaft Ion 5 S", "B", source="Air Turquoise"),
        ))
        assert found is not None
        assert found.klass == "B" and found.source == "Air Turquoise"

    def test_an_ltf_only_wing_is_labelled_ltf(self):
        """LTF 1-2 is *about* EN B and every pilot knows it. "About" is not a
        certification, and a B printed beside a 1-2 wing is an invented claim."""
        found = cert.lookup("Maker Oldie", table(
            entry("Maker Oldie 26", "1-2", maker="Maker"),
            entry("Maker Oldie 28", "1-2", maker="Maker"),
        ))
        assert found is not None
        assert found.label == "LTF 1-2"
        assert found.en is None


class TestTheCommittedRegister:
    """Coverage and provenance of the real table — the part a fixture cannot check."""

    def test_it_is_big_enough_to_be_the_real_thing(self):
        from tracklog_viewer.gliders import GLIDERS

        assert len(GLIDERS) > 4000

    def test_every_row_can_be_checked(self):
        """A class with no reference is a claim a reader has to take on trust."""
        from tracklog_viewer.gliders import GLIDERS

        missing = [row for row in GLIDERS if not row[6]]
        assert not missing, f"{len(missing)} rows carry no certificate reference"

    def test_both_registers_are_in_it(self):
        """Neither alone covers the field: the DHV's newest Ozone is from 2018, and Air
        Turquoise only has what Air Turquoise tested."""
        from tracklog_viewer.gliders import GLIDERS

        sources = {row[2] for row in GLIDERS}
        assert sources == {"DHV", "Air Turquoise"}

    def test_it_says_where_it_came_from_and_when(self):
        from tracklog_viewer import gliders

        assert gliders.SOURCE.startswith("https://")
        assert gliders.REPORTS.startswith("https://")
        assert len(gliders.FETCHED) == 10  # an ISO date
        assert "DHV" in gliders.ATTRIBUTION and "Air Turquoise" in gliders.ATTRIBUTION

    def test_no_class_outside_the_two_scales_got_in(self):
        from tracklog_viewer.gliders import GLIDERS

        allowed = {"A", "B", "C", "D", "1", "1-2", "2", "2-3", "3"}
        found = {row[3] for row in GLIDERS}
        assert found <= allowed, f"unexpected classes: {sorted(found - allowed)}"

    @pytest.mark.parametrize("header,klass", [
        ("OZONE Zeno 2", "D"),
        ("GIN GLIDERS Bonanza 2", "C"),
        ("UP Kantega XC2", "B"),
    ])
    def test_a_wing_from_the_sample_archive_resolves(self, header, klass):
        found = cert.lookup(header)
        assert found is not None, f"{header} is no longer found in the register"
        assert found.klass == klass


class TestParsingTheRegisters:
    def test_a_dhv_row_without_a_detail_link_still_yields_its_number(self):
        """815 of 3 887 rows have no link — an EAPR or Air Turquoise approval the portal
        lists without a page of its own — and requiring the anchor dropped every one."""
        page = '''<div class="mu_listRow">
          <h2 title="Gleitschirm AIRDESIGN Rise 3 M">x</h2>
          <b>Hersteller: </b><p><strong>
          Musterprüfung:                    </strong>
          EAPR-GS-0653/17 (24.08.2017)<br />
          <strong>Klasse:</strong> B <br /><strong>Startgewicht:</strong> 85 - 105 kg</p>
        </div>'''
        rows = cert.parse_dhv(page)
        assert len(rows) == 1
        assert rows[0].certificate == "EAPR-GS-0653/17"
        assert rows[0].date == "24.08.2017"
        assert rows[0].klass == "B"

    def test_the_class_addendum_is_split_off_the_class(self):
        page = '''<div class="mu_listRow">
          <h2 title="Gleitschirm Maker Thing 26">x</h2>
          <b>Hersteller: </b>Maker<p><strong>Musterprüfung:</strong>
          DHV GS-01-1234-99 (01.01.1999)<br />
          <strong>Klasse:</strong> 1-2 GH <br /></p></div>'''
        rows = cert.parse_dhv(page)
        assert rows[0].klass == "1-2" and rows[0].addendum == "GH"

    def test_a_harness_is_not_a_glider(self):
        """"Gleitschirm-Gurtzeug" starts with "Gleitschirm" and has a class of its own,
        which is the sort of wrong answer that looks perfectly plausible."""
        page = '''<div class="mu_listRow">
          <h2 title="Gleitschirm-Gurtzeug Maker Seat">x</h2>
          <strong>Klasse:</strong> B </div>'''
        assert cert.parse_dhv(page) == []

    def test_air_turquoise_rows_that_are_not_gliders_are_skipped(self):
        page = """
        <tr><td>07.08.2026</td><td>DLCO Little Cloud SuperFly 22</td>
            <td>No classification</td><td>Load tests</td></tr>
        <tr><td>10.07.2026</td><td>Skywalk GmbH TWIST M</td>
            <td>Inflatable</td><td>Harness</td></tr>
        <tr><td><a href="/reports?model=Glider&id=3722">x</a>27.07.2026</td>
            <td>Sky Country Mystic-5 M</td><td>C</td><td>Gliders</td></tr>
        """
        rows = cert.parse_airturquoise(page)
        assert len(rows) == 1
        assert rows[0].name == "Sky Country Mystic-5 M"
        assert rows[0].klass == "C"
        assert rows[0].certificate == "para-test report 3722"

    def test_no_classification_never_becomes_a_classification(self):
        page = ('<tr><td>01.01.2026</td><td>Maker Prototype M</td>'
                '<td>No classification</td><td>Gliders</td></tr>')
        assert cert.parse_airturquoise(page) == []

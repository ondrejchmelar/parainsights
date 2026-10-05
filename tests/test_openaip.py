"""openAIP airspace as layer files (`airspaces/openaip.py`). No network: items are built
here in the shape the API returns them."""

import json

import pytest

from airspaces import openaip, render_html


def item(name="TEST", type_=4, icao=3, lower=(0, 1, 0), upper=(4500, 1, 1), country="IT",
         box=(11.0, 11.2, 46.0, 46.2)):
    west, east, south, north = box
    limit = lambda v: {"value": v[0], "unit": v[1], "referenceDatum": v[2]}
    return {"name": name, "type": type_, "icaoClass": icao, "country": country,
            "lowerLimit": limit(lower), "upperLimit": limit(upper),
            "geometry": {"type": "Polygon", "coordinates": [[
                [west, south], [east, south], [east, north], [west, north], [west, south]]]}}


@pytest.mark.parametrize("limit, text", [
    ({"value": 0, "unit": 1, "referenceDatum": 0}, "GND"),
    ({"value": 95, "unit": 6, "referenceDatum": 2}, "FL95"),
    ({"value": 3500, "unit": 1, "referenceDatum": 1}, "3500ft MSL"),
    ({"value": 300, "unit": 0, "referenceDatum": 0}, "300m AGL"),
    ({"value": 1000, "unit": 1, "referenceDatum": 0}, "1000ft AGL"),
])
def test_limits_read_back_as_the_heights_they_are(limit, text):
    """The text is what the rest of `airspaces` parses, so it must parse to the height."""
    assert openaip._limit(limit) == text


def test_feet_and_metres_survive_the_round_trip_through_the_parser():
    metres, ground = render_html.limit_metres(openaip._limit({"value": 3500, "unit": 1, "referenceDatum": 1}))
    assert metres == pytest.approx(1066.8) and not ground
    metres, ground = render_html.limit_metres(openaip._limit({"value": 300, "unit": 0, "referenceDatum": 0}))
    assert metres == pytest.approx(300) and ground


def test_service_boundaries_and_upper_airspace_are_not_drawn():
    """A FIR, an airway or a sector bounds a service, not where a paraglider may fly;
    and nothing starting at FL195 or above is a paraglider's."""
    assert openaip.to_airspace(item(type_=10)) is None          # FIR
    assert openaip.to_airspace(item(type_=15)) is None          # airway
    assert openaip.to_airspace(item(lower=(195, 6, 2), upper=(660, 6, 2))) is None
    assert openaip.to_airspace(item(lower=(125, 6, 2), upper=(195, 6, 2))) is not None


def test_types_land_in_the_map_filter_groups():
    """The legend's groups, so the filters and colours work as for the Czech data."""
    groups = {t: render_html.classify(openaip.to_airspace(item(type_=t))) for t in (1, 2, 4, 13, 21)}
    assert groups == {1: "restricted", 2: "restricted", 4: "base", 13: "atz", 21: "gliding"}
    assert openaip.to_airspace(item(type_=4, icao=3)).airspace_class == "CTR D"


def test_a_layer_file_gives_the_airspace_back(tmp_path):
    """The Planner page is built from the committed file with no key: the name, class and
    limits must come back as published, and the ring as the map draws it."""
    spaces = openaip.drawn("IT", [item("FIEMME RMZ", type_=6, icao=6, lower=(3500, 1, 1),
                                       upper=(115, 6, 2))])
    data = openaip.layer_file(spaces, version="2026-10-05", credit=openaip.CREDIT)
    assert data["bbox"] == [11.0, 11.2, 46.0, 46.2]
    ring = data["airspaces"][0]
    assert ring["k"] == "base" and ring["f"] == 1067 and ring["lo"] == "3500ft MSL"
    (tmp_path / "IT.json").write_text(json.dumps(data))
    back, version = openaip.read(tmp_path / "IT.json")
    assert version == "2026-10-05"
    assert (back[0].name, back[0].airspace_class, back[0].floor, back[0].ceiling) == \
        ("FIEMME RMZ", "RMZ G", "3500ft MSL", "FL115")
    assert back[0].points[0] == pytest.approx((46.0, 11.0))
    assert render_html.classify(back[0]) == "base"


def test_the_index_lists_each_file_with_its_box_and_credit(tmp_path):
    data = openaip.layer_file(openaip.drawn("IT", [item()]), version="v", credit=openaip.CREDIT)
    (tmp_path / "IT.json").write_text(json.dumps(data))
    (tmp_path / "XX.json").write_text(json.dumps({"bbox": None, "airspaces": []}))
    index = openaip.write_index(tmp_path)
    assert list(index["files"]) == ["IT.json"], "a file with nothing in it is not listed"
    assert index["files"]["IT.json"]["credit"].startswith("Airspace © openAIP")
    assert index["colours"]["restricted"]
    assert json.loads((tmp_path / "index.json").read_text()) == index


def test_the_key_never_comes_from_the_repository(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAIP_API_KEY", "from-env")
    assert openaip.api_key() == "from-env"
    monkeypatch.delenv("OPENAIP_API_KEY")
    monkeypatch.setattr(openaip, "KEY_FILE", tmp_path / "missing")
    assert openaip.api_key() is None

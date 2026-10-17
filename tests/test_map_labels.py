"""The maps' names: which language a bilingual place is shown in.

The vector tiles join a bilingual area's names ("Brixen - Bressanone") and say nothing
about country, so the map looks its centre up in `public/countries.json` and shows the
name in that country's language (`labelName`, `countryAt` in `map3d.js`).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / "parainsights_map" / "js" / "map3d.js").read_text(encoding="utf-8")
COUNTRIES = json.loads((ROOT / "public" / "countries.json").read_text(encoding="utf-8"))


def country_at(lon: float, lat: float) -> str | None:
    """The same ray casting as `countryAt` in map3d.js."""
    x, y = lon * 10, lat * 10
    for iso, rings in COUNTRIES.items():
        for ring in rings:
            inside = False
            j = len(ring) - 2
            for i in range(0, len(ring), 2):
                xi, yi, xj, yj = ring[i], ring[i + 1], ring[j], ring[j + 1]
                if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                    inside = not inside
                j = i
            if inside:
                return iso
    return None


def test_the_places_the_report_flies_are_in_the_right_country():
    assert country_at(11.35, 46.50) == "IT", "Bolzano"
    assert country_at(11.75, 46.55) == "IT", "Col Rodella"
    assert country_at(7.32, 45.74) == "IT", "Aosta"
    assert country_at(14.42, 50.08) == "CZ", "Prague"
    assert country_at(15.60, 50.68) == "CZ", "Krkonoše"
    assert country_at(11.40, 47.27) == "AT", "Innsbruck"
    assert country_at(74.65, 36.32) == "PK", "Hunza"
    assert country_at(-30.0, 40.0) is None, "the Atlantic"


def test_the_language_table_names_the_languages_the_tiles_carry():
    table = dict(re.findall(r"\b([A-Z]{2}): '([a-z]{2})'", SCRIPT))
    assert table["IT"] == "it" and table["CZ"] == "cs" and table["PL"] == "pl"
    assert table["CH"] == "de"
    assert all(code in COUNTRIES for code in ("IT", "CZ", "AT", "CH", "SI", "PK"))


def test_a_local_name_is_only_replaced_by_one_of_its_own_parts():
    """`name:it` is preferred only where it is *inside* the joined name: an exonym
    ("Monaco di Baviera" for München) never replaces a local name."""
    body = SCRIPT[SCRIPT.index("function labelName"):SCRIPT.index("var LABEL_NAME")]
    assert "['in', own, ['get', 'name']]" in body

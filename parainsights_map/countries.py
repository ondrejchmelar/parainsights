"""The country outlines the maps use to choose a name's language (`map3d.js`, `countryAt`).

A bilingual area's place name is all its official names joined ("Brixen - Bressanone"),
and the map shows the one in the language of the country it stands in. The vector tiles
say nothing about country, so the map asks these outlines which country its centre is
in. Natural Earth's 1:50m countries, simplified to ~10 km and rounded to 0.1°: which
country a mountain view is in, not where a border runs. Committed as
`public/countries.json` (160 KB, 60 KB gzipped), loaded once when a map opens.

Rebuild (it needs shapely, which nothing else here does):

    uv run --with shapely python -m parainsights_map.countries public/countries.json
"""
from __future__ import annotations

import json
import sys
import urllib.request

SOURCE = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
          "ne_50m_admin_0_countries.geojson")
TOLERANCE = 0.1   # degrees: the simplification
MIN_AREA = 0.02   # square degrees: islands smaller than this are left out


def build(geojson: dict) -> dict:
    """{ISO alpha-2: [ring, …]}, each ring a flat [lon×10, lat×10, …] list."""
    from shapely.geometry import shape

    out: dict[str, list] = {}
    for feature in geojson["features"]:
        props = feature["properties"]
        iso = props.get("ISO_A2_EH")
        if not iso or iso == "-99":
            iso = props.get("ISO_A2")
        if not iso or iso == "-99":
            continue
        geometry = shape(feature["geometry"]).simplify(TOLERANCE, preserve_topology=True)
        polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
        for polygon in polygons:
            if polygon.area < MIN_AREA:
                continue
            ring = []
            for x, y in polygon.exterior.coords:
                ring += [round(x * 10), round(y * 10)]
            out.setdefault(iso, []).append(ring)
    return out


def main(argv: list[str]) -> None:
    target = argv[1] if len(argv) > 1 else "public/countries.json"
    with urllib.request.urlopen(SOURCE) as response:
        geojson = json.load(response)
    data = build(geojson)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"{target}: {len(data)} countries")


if __name__ == "__main__":
    main(sys.argv)

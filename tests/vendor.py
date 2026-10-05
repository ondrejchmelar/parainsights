"""MapLibre and deck.gl for the merged map's browser tests, cached on disk.

The page loads both from a CDN when the merged view opens (`render_map.MAPLIBRE`,
`.DECK`), and the suite has no network — so the merged view, now the default 3D map,
went untested, and its controls broke twice where the canvas view's never did. The same
pinned files are fetched once into a cache (`python -m tests.vendor`, a network step CI
runs before pytest) and served to the page under test from localhost.
"""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

from parainsights_map import render_map

FOLDER = Path(os.environ.get("PARAINSIGHTS_VENDOR",
                             Path.home() / ".cache" / "parainsights" / "vendor"))
FILES = {
    "maplibre-gl.js": render_map.MAPLIBRE + "/maplibre-gl.js",
    "maplibre-gl.css": render_map.MAPLIBRE + "/maplibre-gl.css",
    "deck.min.js": render_map.DECK,
}


def folder() -> Path | None:
    """The cache, when every file is in it — named by version, so a bump re-fetches."""
    tag = FOLDER / (render_map.MAPLIBRE.split("@")[1].split("/")[0] + "_"
                    + render_map.DECK.split("@")[1].split("/")[0])
    return tag if all((tag / name).is_file() for name in FILES) else None


def fetch() -> Path:
    tag = FOLDER / (render_map.MAPLIBRE.split("@")[1].split("/")[0] + "_"
                    + render_map.DECK.split("@")[1].split("/")[0])
    tag.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        if not (tag / name).is_file():
            with urllib.request.urlopen(url, timeout=120) as response:
                (tag / name).write_bytes(response.read())
            print(f"fetched {url}", file=sys.stderr)
    return tag


if __name__ == "__main__":
    print(fetch())

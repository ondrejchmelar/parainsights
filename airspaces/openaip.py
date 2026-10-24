"""Airspace across Europe from openAIP, as static files the pages read at view time —
the files, and what the pages are built from.

openAIP (openaip.net) is the community airspace database, worldwide, under CC BY-NC 4.0:
free for a non-commercial site that credits it. Its API needs a key, and a key in a
published page is a key anyone can copy — so the pages never ask openAIP for anything.
A monthly job fetches it (`airspaces.openaip_refresh`) and writes one file per country
into `public/planner/layers/`, beside an `index.json` that says what area each file
covers. A flight's 3D map loads the files under its ground when it is opened
(`loadAirspace` in `parainsights_map.view3d`), bundled flights and uploads alike, so a
refresh reaches every flight without rebuilding the report.

**Czechia is openAIP too**, its aerodrome zones included, with one layer of this
repository's own on top: the traffic circuits (`airspaces.build`), which no published
source draws, in `cz-circuits.json`. (Our own aerodrome zones stay in the OpenAir
download for XCTrack, which is what that file is for.)

Each file holds the rings the map draws (`scene.rings`) plus, per ring, the name, class
and limits as published (`nm`, `ac`, `lo`, `hi`), so the Planner page can be rebuilt as
airspace objects from the committed file without the key (`read`).

Two modules, so that what the Planner page is built from is only this one: the fetch,
the key and the choice of what is drawn are `openaip_refresh`, which the page never
imports — and `ci/stale.sh` does not hold a change there against the page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .openair import Airspace

CREDIT = "Airspace © openAIP (openaip.net), CC BY-NC 4.0"
CREDIT_HREF = "https://www.openaip.net"
CIRCUITS = "cz-circuits.json"
INDEX = "index.json"


def layer_file(airspaces: list[Airspace], *, version: str, credit: str,
               credit_href: str = "", source: bool = True) -> dict:
    """A file the page reads: the rings, their box, and who to credit. `source` adds the
    published name, class and limits to each ring, so `read` can give the objects back."""
    from .scene import rings

    out = rings(airspaces, source=source)
    lats = [lat for a in airspaces for lat, _ in a.points]
    lons = [lon for a in airspaces for _, lon in a.points]
    box = [round(min(lons), 4), round(max(lons), 4), round(min(lats), 4),
           round(max(lats), 4)] if lats else None
    return {"version": version, "credit": credit, "creditHref": credit_href,
            "bbox": box, "airspaces": out}


def read(path: Path) -> tuple[list[Airspace], str]:
    """A committed country file back as airspace objects, and its version — what the
    Planner page is built from, with no key and no network."""
    from .scene import decoded

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for ring in data["airspaces"]:
        ring = decoded(ring)
        meta = {"group": ring["k"]}
        # An aerodrome zone names its aerodrome, so the map can link to its page.
        icao = _atz_icao(ring["nm"]) if ring["k"] == "atz" else None
        if icao:
            meta.update(icao=icao, kind="atz")
        out.append(Airspace(name=ring["nm"], airspace_class=ring["ac"], floor=ring["lo"],
                            ceiling=ring["hi"],
                            points=list(zip(ring["lat"], ring["lon"])),
                            meta=meta))
    return out, data["version"]


# openAIP names a Czech ATZ "LKSN ATZ", all but the one it spells out.
_ATZ_NAME = re.compile(r"^(LK[A-Z]{2,4}) ATZ\b")
_ATZ_SPELLED = {"ATZ CESKE BUDEJOVICE": "LKCS"}


def _atz_icao(name: str) -> str | None:
    found = _ATZ_NAME.match(name)
    return found.group(1) if found else _ATZ_SPELLED.get(name)


def base(folder: Path) -> tuple[list[Airspace], str]:
    """The Czech base airspace for the Planner: openAIP's Czech file, as objects, and a
    version line for the page and the OpenAir header."""
    spaces, version = read(Path(folder) / "CZ.json")
    return spaces, f"openAIP {version}"


def write_circuits(folder: Path, overlay) -> None:
    """This repository's own layer — the Czech traffic circuits — beside openAIP's files,
    for the flights' maps to load with them, and the index again."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    data = layer_file(overlay.circuit_airspaces, version=overlay.atz_date, source=False,
                      credit="Traffic circuits: this site, from ŘLP ČR publications")
    (folder / CIRCUITS).write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False),
                                   encoding="utf-8")
    write_index(folder)


def write_index(folder: Path) -> dict:
    """`index.json`: every layer file in the folder, with the box it covers and its
    credit, so a page loads only the files under a flight."""
    files = {}
    for path in sorted(folder.glob("*.json")):
        if path.name == INDEX:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("bbox"):
            continue
        files[path.name] = {"bbox": data["bbox"], "credit": data.get("credit", ""),
                            "creditHref": data.get("creditHref", ""),
                            "version": data.get("version", "")}
    from .render_html import CLASSES

    index = {"files": files, "colours": {key: colour for key, _, colour in CLASSES},
             "classes": [[key, label] for key, label, _ in CLASSES]}
    (folder / INDEX).write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    return index

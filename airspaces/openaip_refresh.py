"""The monthly refresh of the openAIP layer files (`airspaces.openaip`): every country in
`COUNTRIES` fetched once (`python -m airspaces.openaip_refresh`, monthly in
`.github/workflows/airspace.yml`, the key a repository secret), what a paraglider's map
has use for kept (`to_airspace`, `drawn`), and one file per country written.

Not imported by any page build: the Planner page reads the committed files
(`openaip.read`), so a change here changes the files, not the page.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .openair import Airspace
from .openaip import CREDIT, CREDIT_HREF, layer_file, write_index

API = "https://api.core.openaip.net/api/airspaces"
KEY_FILE = Path.home() / ".config" / "parainsights" / "openaip-key"

# Europe, the Alps included, and Turkey for Ölüdeniz.
COUNTRIES = (
    "AD AL AT BA BE BG BY CH CY CZ DE DK EE ES FI FR GB GR HR HU IE IS IT LI LT LU LV "
    "MC MD ME MK MT NL NO PL PT RO RS SE SI SK SM TR UA XK"
).split()

# openAIP's `type`: the name a label prints, and the filter group (`render_html.CLASSES`)
# it is drawn and filtered under. A type that is not here is not drawn: FIR, UIR, ADIZ,
# airways, ACC/FIS/VFR sectors and the like are boundaries of a service, not of where a
# paraglider may fly, and drawn as boxes they would bury everything else.
TYPES = {
    0: ("Other", "base"),
    1: ("R", "restricted"),
    2: ("D", "restricted"),
    3: ("P", "restricted"),
    4: ("CTR", "base"),
    5: ("TMZ", "base"),
    6: ("RMZ", "base"),
    7: ("TMA", "base"),
    8: ("TRA", "restricted"),
    9: ("TSA", "restricted"),
    13: ("ATZ", "atz"),
    14: ("MATZ", "atz"),
    17: ("Alert", "restricted"),
    18: ("Warning", "restricted"),
    19: ("Protected", "restricted"),
    20: ("HTZ", "atz"),
    21: ("Gliding", "gliding"),
    23: ("TIZ", "base"),
    24: ("TIA", "base"),
    25: ("MTA", "restricted"),
    26: ("CTA", "base"),
    28: ("Sport", "gliding"),
    29: ("Overflight restriction", "restricted"),
    31: ("TFR", "restricted"),
    34: ("LTA", "base"),
    36: ("MCTR", "base"),
}
ICAO = "ABCDEFG"

# Nothing whose floor is at FL195 or higher: upper airspace is not a paraglider's.
TOP_FLOOR_M = 195 * 100 * 0.3048

PAUSE = 2.0          # seconds between requests: openAIP answers a burst with 429
PAGE = 1000


def api_key() -> str | None:
    """`OPENAIP_API_KEY`, or the file in ~/.config — never the repository."""
    key = os.environ.get("OPENAIP_API_KEY", "").strip()
    if key:
        return key
    try:
        return KEY_FILE.read_text().strip() or None
    except OSError:
        return None


def _get(url: str, key: str) -> dict:
    """One page of the API, backing off on 429 (it rate-limits through Cloudflare)."""
    wait = 30.0
    for attempt in range(6):
        request = urllib.request.Request(url, headers={
            "x-openaip-api-key": key, "Accept": "application/json",
            "User-Agent": "parainsights/1.0 (+https://github.com/ondrejchmelar/parainsights)"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 5:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 5:
                raise
        print(f"  openAIP is pacing us, waiting {wait:.0f} s", file=sys.stderr)
        time.sleep(wait)
        wait *= 2
    raise RuntimeError("unreachable")


def fetch_country(code: str, key: str) -> list[dict]:
    """Every airspace openAIP files under this country, page by page."""
    items, page = [], 1
    while True:
        data = _get(f"{API}?country={code}&limit={PAGE}&page={page}", key)
        items.extend(data.get("items", []))
        page = data.get("nextPage")
        time.sleep(PAUSE)
        if not page:
            return items


def _limit(limit: dict) -> str:
    """openAIP's {value, unit, referenceDatum} as the OpenAir-style text the rest of
    `airspaces` reads (`render_html.limit_metres`): `GND`, `FL95`, `3500ft MSL`,
    `300m AGL`. Units: 0 metres, 1 feet, 6 flight level. Datum: 0 ground, 1 MSL, 2 STD."""
    value, unit, datum = limit.get("value", 0), limit.get("unit", 1), limit.get("referenceDatum", 1)
    if unit == 6 or datum == 2:
        level = value if unit == 6 else round(value * (1 if unit == 1 else 3.28084) / 100)
        return f"FL{level}"
    if datum == 0 and not value:
        return "GND"
    text = f"{value}{'m' if unit == 0 else 'ft'}"
    return f"{text} {'AGL' if datum == 0 else 'MSL'}"


def to_airspace(item: dict) -> Airspace | None:
    """One openAIP item as an `Airspace`, or None where it is not drawn (see `TYPES`)."""
    kind = TYPES.get(item.get("type"))
    geometry = item.get("geometry") or {}
    if not kind or geometry.get("type") != "Polygon" or not geometry.get("coordinates"):
        return None
    label, group = kind
    icao = item.get("icaoClass")
    if group == "base" and isinstance(icao, int) and icao < len(ICAO):
        label = f"{label} {ICAO[icao]}"
    floor, ceiling = _limit(item.get("lowerLimit") or {}), _limit(item.get("upperLimit") or {})
    from .render_html import limit_metres

    metres, _ = limit_metres(floor)
    if metres is not None and metres >= TOP_FLOOR_M:
        return None
    points = [(lat, lon) for lon, lat in geometry["coordinates"][0]]
    # Active only when a NOTAM says so, by openAIP's own flags: a flight's map leaves
    # these out (`relevantAirspace`), since the file cannot know whether one was issued.
    hours = (item.get("hoursOfOperation") or {}).get("operatingHours") or []
    notam = bool(item.get("byNotam") or any(h.get("byNotam") for h in hours))
    return Airspace(name=item.get("name") or label, airspace_class=label, floor=floor,
                    ceiling=ceiling, points=points,
                    meta={"group": group, "type": item.get("type"), "notam": notam})


# Germany files its general class E as zones of no other type: the blanket from 2 500 ft
# above the ground to FL 100 ("AREA"), the Alpine one to FL 130, and the class E let down
# to 1 000 or 1 700 ft around each airport. Class E needs no clearance and no radio of a
# paraglider, and nearly every German flight is in it — so "entered AREA" said nothing,
# and its boxes covered every German map (October 2026). Elsewhere a class E zone of no
# other type is a structure with a name (Greece's military TMAs, Barcelona's sectors),
# and stays.
BLANKET = {("DE", "Other E")}


def drawn(code: str, items: list[dict]) -> list[Airspace]:
    """A country's items as the airspace its file holds."""
    spaces = [a for a in (to_airspace(item) for item in items) if a is not None]
    return [a for a in spaces if (code, a.airspace_class) not in BLANKET]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="airspaces.openaip_refresh",
                                     description="Fetch openAIP airspace per country.")
    parser.add_argument("--out", type=Path, default=Path("public/planner/layers"))
    parser.add_argument("--countries", default=",".join(COUNTRIES),
                        help="comma-separated ISO codes (default: Europe and the Alps)")
    args = parser.parse_args(argv)
    key = api_key()
    if not key:
        parser.error(f"no openAIP key: set OPENAIP_API_KEY or write it to {KEY_FILE}")
    args.out.mkdir(parents=True, exist_ok=True)
    version = dt.date.today().isoformat()
    failed = []
    for code in [c.strip().upper() for c in args.countries.split(",") if c.strip()]:
        try:
            items = fetch_country(code, key)
        except Exception as error:      # one country down is not the rest of Europe down
            print(f"{code}: failed ({error}); the committed file stays", file=sys.stderr)
            failed.append(code)
            continue
        spaces = drawn(code, items)
        if not spaces:
            # Andorra, Monaco and the like have nothing filed; a country that had and now
            # answers nothing is more likely a blip than a cleared sky. Keep what is there.
            print(f"{code}: nothing drawn, no file written")
            continue
        data = layer_file(spaces, version=version, credit=CREDIT, credit_href=CREDIT_HREF)
        path = args.out / f"{code}.json"
        if path.exists():
            # Rewritten only when the airspace changed: a new date on unchanged data would
            # add a megabyte of history to the repository every month for nothing.
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("airspaces") == data["airspaces"]:
                print(f"{code}: unchanged since {old.get('version')}")
                continue
        text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        path.write_text(text, encoding="utf-8")
        print(f"{code}: {len(items)} items, {len(spaces)} drawn, {len(text) / 1024:.0f} KB")
    write_index(args.out)
    return 1 if failed and len(failed) == len(args.countries.split(",")) else 0


if __name__ == "__main__":
    raise SystemExit(main())

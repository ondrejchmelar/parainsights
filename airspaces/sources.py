"""Where the data comes from, and the cache that keeps it off the network twice.

Four sources, all public and all free to use:

`RLP_ATZ`
    The ATZ themselves, as UAS geographical zones. This is the only machine-readable
    publication of Czech ATZ geometry there is; the AIP gives them as prose. The path
    carries an AIRAC date, so `atz_url` finds the current one by walking back from
    today over the publication dates.

`AEROKLUB`
    `CZ_low` in OpenAir, by Jan Zahradka on behalf of Aeroklub ČR. This is the base
    airspace and it is the same data airspace.xcontest.org carries for Czechia —
    xcontest's own about page says it builds from soaringweb.org, and soaringweb's
    Czech page is this file, republished. Going to the origin instead of the mirror
    gets a file that is current rather than one AIRAC cycle stale, and xcontest's
    export endpoint needs an account anyway.

`VFR_MANUAL`
    Per-aerodrome text pages: reference point, elevation, circuit altitude, and the
    traffic-circuit rules in prose. `{icao}_text_en.html`, lowercase.

`OURAIRPORTS`
    Runway threshold coordinates, public domain. The VFR manual gives runway *magnetic*
    directions but no thresholds, and a circuit box built from a reference point and a
    magnetic heading is out by however far the reference point sits from the runway.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".cache" / "parainsights" / "airspace"

RLP_ATZ = "https://aim.rlp.cz/data/uas/{date}/actual/LKR315{pub}.json"

# The UAS zone data comes in four publications, all GND - 4000 ft AMSL, none of them
# indexed anywhere — they were found by asking for the next letter.
#
#   A  82 ATZ at ICAO aerodromes, `905LKBA`,   5 500 m
#   B  74 SLZ/ultralight fields,  `LKCAST`,      ~965 m
#   C  222 heliports,             `HELLKUHIII`,  127-1 979 m
#   D  195 landing sites,         `PISLK011II`,  126-1 976 m
#
# A and B are aerodromes with circuit traffic and are the default. C and D are mostly
# hospital pads and small strips: 417 more circles for a paraglider to be warned about,
# which is why they are opt-in.
PUBLICATIONS = ("A", "B", "C", "D")
DEFAULT_PUBLICATIONS = ("A", "B")
AEROKLUB_DIR = "https://airspace.aeroklub.cz/docs/public/"
VFR_MANUAL = "https://aim.rlp.cz/vfrmanual/actual/{icao}_text_en.html"
OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/{table}.csv"

# A real one: aim.rlp.cz answers 403 to the default urllib agent on some paths.
AGENT = "parainsights/0.1 (paragliding airspace tool; +https://github.com/)"

# AIRAC is 28 days from a fixed epoch; 2024-01-25 is a cycle start. Checked against two
# real publications — RLP's 2026_08_06 and soaringweb's 25-08-07 are both on it.
# Aeroklub is *not*: its current file is 26-04-01, which is no AIRAC date. So RLP is
# found by arithmetic and Aeroklub by reading the directory.
AIRAC_EPOCH = dt.date(2024, 1, 25)


def airac_dates(before: dt.date | None = None, count: int = 14) -> list[dt.date]:
    """Recent AIRAC effective dates, most recent first."""
    today = before or dt.date.today()
    elapsed = (today - AIRAC_EPOCH).days
    latest = AIRAC_EPOCH + dt.timedelta(days=(elapsed // 28) * 28)
    return [latest - dt.timedelta(days=28 * i) for i in range(count)]


def fetch(url: str, *, cache_key: str | None = None, refresh: bool = False) -> bytes:
    """GET a URL, through the cache. Raises on anything but a 200."""
    key = cache_key or url.rsplit("/", 2)[-2] + "-" + url.rsplit("/", 1)[-1]
    path = CACHE / key.replace("/", "-")
    if path.exists() and not refresh:
        return path.read_bytes()
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _try(url: str, **kwargs) -> bytes | None:
    try:
        return fetch(url, **kwargs)
    except Exception:
        return None


def atz(*, refresh: bool = False, on: dt.date | None = None, pub: str = "A") -> dict:
    """One UAS zone publication, as parsed GeoJSON.

    The URL carries the AIRAC date it was published under and there is no index, so
    walk back from the current cycle until one answers.
    """
    for date in airac_dates(on):
        stamp = date.strftime("%Y_%m_%d")
        data = _try(
            RLP_ATZ.format(date=stamp, pub=pub),
            cache_key=f"atz{pub}-{stamp}.json", refresh=refresh,
        )
        if data:
            return json.loads(data)
    raise RuntimeError(f"no LKR315{pub} publication in the last 14 AIRAC cycles")


def base_airspace(*, refresh: bool = False, variant: str = "CZ_low") -> tuple[str, str]:
    """Aeroklub's `CZ_low` OpenAir file, as (text, version).

    The version in the filename is Aeroklub's own effective date and does not follow
    AIRAC, so it is read from the directory listing rather than computed. `CZ_low` is
    the one to use — below FL95, which is where a paraglider is.
    """
    listing = fetch(
        AEROKLUB_DIR, cache_key="aeroklub-index.html", refresh=refresh
    ).decode("utf-8", "replace")
    versions = sorted(set(re.findall(rf"{variant}_(\d\d-\d\d-\d\d)\.txt", listing)))
    if not versions:
        raise RuntimeError(f"no {variant} file offered at {AEROKLUB_DIR}")
    version = versions[-1]
    name = f"{variant}_{version}.txt"
    return fetch(
        AEROKLUB_DIR + name, cache_key=name, refresh=refresh
    ).decode("utf-8", "replace"), version


def vfr_page(icao: str, *, refresh: bool = False) -> str | None:
    """One aerodrome's VFR manual text page. None when it is not published."""
    code = icao.lower()
    data = _try(
        VFR_MANUAL.format(icao=code), cache_key=f"vfr-{code}.html", refresh=refresh
    )
    return data.decode("utf-8", "replace") if data else None


def ourairports(table: str, *, refresh: bool = False) -> str:
    """`airports` or `runways` as CSV text."""
    return fetch(
        OURAIRPORTS.format(table=table), cache_key=f"oa-{table}.csv", refresh=refresh
    ).decode("utf-8", "replace")

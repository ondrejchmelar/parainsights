"""Where the two committed lists come from, and the scripts that regenerate them.

**The takeoffs.** One source, and it is not scraped: ParaglidingEarth publishes a
documented GeoJSON API per country, and its records carry the two things this page needs
and a weather site cannot know — where the takeoff is, and **which wind directions it
works in**. That second field is what turns a forecast into an answer: 20 km/h from the
north-west is a good day at one hill and unflyable at the next one along.

*Which* takeoffs is a choice, not a fetch — see `CHOSEN`. Every Czech record was 159
rows, most of them hills nobody drives to, and a ranking of all of them buried the ones
that matter under the ones that happened to score.

**The flymet stations.** Scraped, because there is nothing else to read: flymet publishes
its 186 stations as an HTML image map over a picture of the country, and the only
statement anywhere of where a station *is* is the pixel its circle sits on. So the pixels
are georeferenced — see `flymet_frame` — and the answer is checked before it is written
rather than trusted.

Both lists are fetched once and committed rather than fetched at build time. Takeoffs and
airfields do not move, the files are small, and a page that cannot be built because a
community database is down is a bad trade. `--refresh-sites` and `--refresh-flymet`
rewrite them, and the header each writes records where and when, so the next person can
tell how stale it is.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import unicodedata
import urllib.request
from pathlib import Path

ENDPOINT = ("https://www.paraglidingearth.com/api/geojson/getCountrySites.php"
            "?iso={iso}&style=detailled")
ATTRIBUTION = "Takeoffs from ParaglidingEarth, CC BY-SA"
OCTANTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
TIMEOUT = 60

# The takeoffs the page carries: gfs.pgweb.cz's own **ESSENTIALS** group — the hills Czech
# pilots actually drive to, chosen by people who fly them, read 2026-09-23 — and four in
# the Alps and the Julians that are the usual trips south. Each is pinned to the one
# ParaglidingEarth record it means, by id: pgweb gives a point and a name, PGE gives the
# wind rose, and every pgweb point had exactly one PGE takeoff within a kilometre of it.
# The name is pgweb's, because it is the one a Czech pilot would type into the search.
# (name, country, ParaglidingEarth id)
CHOSEN = (
    ("Raná", "CZ", 10099),
    ("Krupka", "CZ", 6737),
    ("Kozákov", "CZ", 7197),
    ("Černá hora", "CZ", 7188),
    ("Dolní Morava", "CZ", 21878),      # PGE: Slamník
    ("Velký Lopeník", "SK", 10270),     # the takeoff is over the border, the hill is not
    ("Martinské hole", "SK", 22106),    # no wind rose on PGE, so it is left unjudged
    ("Pálava - Děvín", "CZ", 22931),
    ("Všechov", "CZ", 10333),
    ("Doubrava", "CZ", 12436),
    ("Hausstein", "DE", 8590),
    ("Bassano", "IT", 9200),            # PGE: Bassano - South (da Bepi)
    ("Col Rodella", "IT", 7243),
    ("Meduno", "IT", 19791),
    ("Kobala", "SI", 7183),
)


def fetch(iso: str = "CZ") -> list[dict]:
    """Every published takeoff in the country, as this module's own records."""
    url = ENDPOINT.format(iso=iso)
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))

    sites = []
    for feature in payload.get("features", []):
        properties = feature.get("properties", {})
        lon, lat = feature["geometry"]["coordinates"][:2]
        name = (properties.get("name") or "").strip()
        if not name:
            continue
        # 0 no, 1 marginal, 2 good — ParaglidingEarth's own scale, kept rather than
        # flattened to a boolean: "marginal" is a real answer about a takeoff.
        winds = [int(properties.get(point) or 0) for point in OCTANTS]
        if not any(winds):
            # A takeoff with no direction recorded cannot be judged against the wind,
            # and judging it anyway would be the page's one unforgivable error.
            winds = []
        sites.append({
            "name": name,
            "lat": round(float(lat), 4),
            "lon": round(float(lon), 4),
            "alt": int(float(properties.get("takeoff_altitude") or 0)),
            "winds": winds,
            "id": int(properties.get("pge_site_id") or 0),
        })
    sites.sort(key=lambda site: site["name"].lower())
    return sites


def fetch_chosen(chosen=CHOSEN) -> list[dict]:
    """The `CHOSEN` takeoffs, each from its own country's ParaglidingEarth record.

    Refuses rather than drops: a chosen takeoff whose record has gone is a list somebody
    has to look at, not a hill that should quietly vanish from the page.
    """
    by_country = {iso: {site["id"]: site for site in fetch(iso)}
                  for iso in dict.fromkeys(iso for _, iso, _ in chosen)}
    sites = []
    for name, iso, pge_id in chosen:
        record = by_country[iso].get(pge_id)
        if record is None:
            raise ValueError(f"ParaglidingEarth no longer has {name} ({iso} #{pge_id})")
        sites.append(record | {"name": name, "country": iso})
    return sites


def write(path: Path, sites: list[dict]) -> None:
    """Rewrite `sites.py` from a fetch, provenance first."""
    today = dt.date.today().isoformat()
    countries = ",".join(dict.fromkeys(site["country"] for site in sites))
    lines = [
        '"""Paragliding takeoffs, as committed data.',
        "",
        f"Generated by `meteo.sources.write` from ParaglidingEarth on {today}, for the",
        "takeoffs `meteo.sources.CHOSEN` names, in its order:",
        f"    {ENDPOINT.format(iso='{' + countries + '}')}",
        "",
        "`winds` is ParaglidingEarth's own suitability per octant, N first and clockwise:",
        "0 unflyable, 1 marginal, 2 good. An empty list means the site records none, and",
        "the page then refuses to judge it against the forecast rather than guessing.",
        '"""',
        "",
        f'SOURCE = "{ENDPOINT.format(iso="{" + countries + "}")}"',
        f'FETCHED = "{today}"',
        f'ATTRIBUTION = "{ATTRIBUTION}"',
        'OCTANTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")',
        "",
        "SITES = [",
    ]
    for site in sites:
        lines.append(
            f'    {{"name": {site["name"]!r}, "country": {site["country"]!r}, '
            f'"lat": {site["lat"]}, '
            f'"lon": {site["lon"]}, "alt": {site["alt"]}, '
            f'"winds": {site["winds"]}, "id": {site["id"]}}},'
        )
    lines.append("]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ flymet

# https throughout, and for the images it is not a detail: this site is served over https,
# and a browser drops an http image on an https page without drawing anything or saying
# why. flymet answers on both — checked August 2026, HTTP/2 with a valid certificate.
FLYMET_INDEX = "https://flymet.meteopress.cz/meteogram/"
FLYMET_TODAY = "https://flymet.meteopress.cz/meteogram/{slug}.png"
FLYMET_TOMORROW = "https://flymet.meteopress.cz/meteogram2/{slug}.png"
FLYMET_ATTRIBUTION = "Meteograms by FLYMET, Meteopress"

# Twelve stations whose real position is known, used to solve the map's projection.
#
# Coordinates are the aerodrome reference points OurAirports publishes — the same source
# `airspaces` takes its runway thresholds from — read out of `oa-airports.csv` on
# 2026-08-11. They are spread to the edges of the country on purpose: an affine fitted on
# a cluster in the middle extrapolates badly to the corners, which is where the border
# stations are.
#
# Every one of them is an airfield rather than a town, because flymet's own point is the
# airfield: matching on town names put Černovice u Tábora on Brno-Černovice, 170 pixels
# out, and that is the failure this list exists to avoid.
FLYMET_ANCHORS = (
    ("KARLOVY-VARY", 50.2030, 12.9150),
    ("RANA", 50.4039, 13.7519),
    ("CESKA-LIPA", 50.7094, 14.5667),
    ("BROUMOV", 50.5619, 16.3428),
    ("MIKULOVICE", 50.3017, 17.2975),
    ("FRYDLANT", 49.5894, 18.3792),
    ("PRIEVIDZA", 48.7661, 18.5867),
    ("VYSKOV", 49.3003, 17.0253),
    ("JINDRICHUV-HRADEC", 49.1507, 14.9724),
    ("STRAKONICE", 49.2517, 13.8928),
    ("LETKOV", 49.7231, 13.4522),
    ("CHOTEBOR", 49.6858, 15.6761),
)

# How far the fit may miss an anchor before the answer is refused. The measured spread
# over the 67 stations that could be checked against OurAirports is 0.46 pixels — about
# 300 m — so a kilometre is a wide gate that still catches a redrawn map or a station
# moved on it, which is the failure mode that would otherwise pass silently and put a
# takeoff's meteogram at the wrong airfield.
FLYMET_TOLERANCE_M = 1000.0


def _solve(rows: list[list[float]], targets: list[float]) -> list[float]:
    """Least squares for a three-term fit, by normal equations and Gaussian elimination.

    Small enough to write out: three unknowns and a dozen rows. numpy is a dependency of
    the viewer, not of `meteo`, and a refresh script should not be the thing that drags
    it in.
    """
    n = len(rows[0])
    matrix = [[sum(row[i] * row[j] for row in rows) for j in range(n)] for i in range(n)]
    vector = [sum(row[i] * t for row, t in zip(rows, targets)) for i in range(n)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda r: abs(matrix[r][i]))
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        vector[i], vector[pivot] = vector[pivot], vector[i]
        if abs(matrix[i][i]) < 1e-12:
            raise ValueError("the anchor positions do not determine a projection")
        for r in range(n):
            if r == i:
                continue
            factor = matrix[r][i] / matrix[i][i]
            for c in range(i, n):
                matrix[r][c] -= factor * matrix[i][c]
            vector[r] -= factor * vector[i]
    return [vector[i] / matrix[i][i] for i in range(n)]


def flymet_frame(pixels: dict[str, tuple[int, int]], anchors=FLYMET_ANCHORS):
    """The map's projection, solved from the anchors, as a pixel → (lat, lon) function.

    A full six-parameter affine rather than a scale and an offset: the picture is a
    rendered map, not a crop of a plate carrée, and nothing published says which
    projection or whether it is square to north. Six parameters absorb a rotation and a
    shear as well, and the residual reports whether they were needed.
    """
    known = [(pixels[slug], lat, lon) for slug, lat, lon in anchors if slug in pixels]
    if len(known) < 4:
        raise ValueError(f"only {len(known)} of {len(anchors)} anchors are on the map")
    rows = [[lon, lat, 1.0] for _, lat, lon in known]
    to_x = _solve(rows, [float(px[0]) for px, _, _ in known])
    to_y = _solve(rows, [float(px[1]) for px, _, _ in known])
    det = to_x[0] * to_y[1] - to_x[1] * to_y[0]
    if abs(det) < 1e-9:
        raise ValueError("the anchors are collinear on the map")

    def place(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - to_x[2], y - to_y[2]
        lon = (dx * to_y[1] - to_x[1] * dy) / det
        lat = (to_x[0] * dy - dx * to_y[0]) / det
        return lat, lon

    # Metres per pixel at the middle of the country, for reporting the residual in units
    # anyone can judge. `to_x[0]` is pixels per degree of longitude and `to_y[1]` pixels
    # per degree of latitude, so each axis is a degree in metres over its own term.
    scale = (111320.0 * math.cos(math.radians(49.8)) / abs(to_x[0])
             + 111132.0 / abs(to_y[1])) / 2
    worst = max(
        distance_m(lat, lon, *place(*px)) for px, lat, lon in known
    )
    return place, worst, scale


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle metres. Small and local: the page ranks a takeoff against stations a
    few tens of kilometres away, and every one of them is in this country."""
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _pretty(html: str) -> dict[str, str]:
    """The station names as flymet writes them for a reader — `Mnichovo Hradiště`, not
    `MNICHOVO-HRADISTE`. They are only in the regional lists beside the map, keyed by the
    same image, so the two halves of the page have to be read and joined."""
    names: dict[str, str] = {}
    # `<a` and not merely `href`: every station is *also* an `<area>` of the image map
    # carrying the same href, and what follows that tag is the newline before the next
    # one. Matched loosely, the whole list came back named "".
    for slug, text in re.findall(
        r'<a\s[^>]*href="https?://flymet\.meteopress\.cz/meteogram/([^"/]+)\.png"'
        r'[^>]*>([^<]+)</a>',
        html,
    ):
        text = unicodedata.normalize("NFC", text.strip())
        if text:
            names.setdefault(slug, text)
    return names


def fetch_flymet() -> tuple[list[dict], float, float]:
    """Every station flymet marks on its own map, with a coordinate for each.

    Returns the stations, the worst anchor residual in metres and the map's scale, so the
    caller can refuse to write an answer it does not believe.
    """
    with urllib.request.urlopen(FLYMET_INDEX, timeout=TIMEOUT) as response:
        raw = response.read()
    # The page is Windows-1250 and says so in a meta tag; the station names are the whole
    # reason to care, and decoded as UTF-8 they come back as replacement characters.
    html = raw.decode("cp1250", errors="replace")

    # One `<area>` per station: a circle at a pixel, linking to that station's image.
    # The centre is what is wanted, so the radius is matched and thrown away.
    pixels: dict[str, tuple[int, int]] = {}
    for x, y, slug in re.findall(
        r'<area[^>]*coords="(\d+),(\d+),\d+"[^>]*href="[^"]*/meteogram/([^"/]+)\.png"',
        html,
    ):
        pixels.setdefault(slug, (int(x), int(y)))
    if not pixels:
        raise ValueError(f"no stations found on {FLYMET_INDEX}")

    place, worst, scale = flymet_frame(pixels)
    names = _pretty(html)
    stations = []
    for slug, (x, y) in pixels.items():
        lat, lon = place(x, y)
        stations.append({
            "slug": slug,
            "name": names.get(slug, slug.replace("-", " ").title()),
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "x": x,
            "y": y,
        })
    stations.sort(key=lambda station: station["slug"])
    return stations, worst, scale


def write_flymet(path: Path, stations: list[dict], worst: float, scale: float) -> None:
    """Rewrite `flymet.py` from a fetch, provenance and the fit's own error first."""
    today = dt.date.today().isoformat()
    lines = [
        '"""flymet meteogram stations, as committed data.',
        "",
        f"Generated by `meteo.sources.write_flymet` on {today} from flymet's own",
        f"station map: {FLYMET_INDEX}",
        "",
        "`x` and `y` are where flymet draws the station on that 800x600 picture of the",
        "country, and they are the only statement it publishes of where a station is.",
        "`lat` and `lon` are those pixels through the affine `sources.flymet_frame`",
        f"solves from {len(FLYMET_ANCHORS)} airfields of known position; the fit missed the",
        f"worst of them by {worst:.0f} m, against a map scale of {scale:.0f} m a pixel.",
        "That is far inside what picking the nearest station to a takeoff needs, and the",
        "pixels are kept so the derivation can be checked rather than believed.",
        '"""',
        "",
        f'SOURCE = "{FLYMET_INDEX}"',
        f'FETCHED = "{today}"',
        f'ATTRIBUTION = "{FLYMET_ATTRIBUTION}"',
        f'RESIDUAL_M = {worst:.0f}',
        f'METRES_PER_PIXEL = {scale:.0f}',
        "",
        "# Today's meteogram and tomorrow's. flymet publishes no further ahead, which is",
        "# why the page shows the image on two of its four days and says so on the others.",
        f'TODAY = "{FLYMET_TODAY}"',
        f'TOMORROW = "{FLYMET_TOMORROW}"',
        "",
        "STATIONS = [",
    ]
    for station in stations:
        lines.append(
            f'    {{"slug": {station["slug"]!r}, "name": {station["name"]!r}, '
            f'"lat": {station["lat"]}, "lon": {station["lon"]}, '
            f'"x": {station["x"]}, "y": {station["y"]}}},'
        )
    lines.append("]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

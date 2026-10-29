"""Where the two committed lists come from, and the scripts that regenerate them.

**The takeoffs.** One source, and it is not scraped: ParaglidingEarth publishes a
documented GeoJSON API per country, and its records carry the two things this page needs
and a weather site cannot know — where the takeoff is, and **which wind directions it
works in**. That second field is what turns a forecast into an answer: 20 km/h from the
north-west is a good day at one hill and unflyable at the next one along.

*Which* takeoffs is pgweb's choice — see `PGWEB`. Every Czech record was 159 rows, most
of them hills nobody drives to, and a ranking of all of them buried the ones that matter
under the ones that happened to score; pgweb's list is the ones pilots there chose.

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

# The takeoffs the page carries are pgweb's (meteoweb.pgweb.cz/termika, where
# gfs.pgweb.cz now redirects): its select box lists ~685 takeoffs in groups chosen by
# people who fly them — ESSENTIALS, nine Czech regions, Slovak essentials, and a list per
# country for Slovakia, Austria, Italy, Slovenia, Switzerland, Germany and France. That is
# "more, but not all": ParaglidingEarth alone has thousands. pgweb gives a name and a
# point; ParaglidingEarth gives the wind rose, paired by distance (`pair`).
# The pilot's call, October 2026 (it was ESSENTIALS and four trips south, 15 takeoffs).
PGWEB = "https://meteoweb.pgweb.cz/termika/"
PGWEB_ATTRIBUTION = "Takeoff list from pgweb (meteoweb.pgweb.cz)"

# Which country each pgweb group belongs to, and what the page calls it. The Czech
# groups are regions already; the others are a list per country, split below.
GROUPS = {
    "ESSENTIALS": ("CZ", "Essentials Czechia"),
    "Středohoří & Krušné": ("CZ", "Středohoří & Krušné hory"),
    "Praha sever": ("CZ", "Praha sever"),
    "Praha jih & Berounsko": ("CZ", "Praha jih & Berounsko"),
    "Krkonoše & okolí": ("CZ", "Krkonoše & okolí"),
    "Orlické, Kraličák & Jeseníky": ("CZ", "Orlické, Kraličák & Jeseníky"),
    "Plzeňsko & Šumava": ("CZ", "Plzeňsko & Šumava"),
    "vlekání": ("CZ", "Tow (winch)"),
    "Beskydy & Bíle Karpaty": ("CZ", "Beskydy & Bílé Karpaty"),
    "Brno": ("CZ", "Brno & Pálava"),
    "SK ESSENTIALS": ("SK", "Essentials Slovakia"),
    "SLOVENSKO": ("SK", None),
    "ITALIE": ("IT", None),
    "FRANCIE": ("FR", None),
    "NĚMECKO": ("DE", None),
    "SWISS": ("CH", None),
    "RAKOUSKO": ("AT", None),
    "SLOVENIE": ("SI", None),
}
COUNTRY_NAMES = {"AT": "Austria", "CH": "Switzerland", "CZ": "Czechia", "DE": "Germany",
                 "FR": "France", "IT": "Italy", "SI": "Slovenia", "SK": "Slovakia"}

# A whole country's list is 55-100 takeoffs, too many to scroll, so it is split into
# regions: each takeoff goes to the nearest of these points (lon, lat), and the ones that
# lands on the wrong side of a ridge or a border are moved by name in `MOVES` — every
# list was read through by hand (October 2026). A region with no point is filled by
# `MOVES` alone. The order here is the order on the page.
REGIONS = {
    "SK": [("Western Slovakia", 17.6, 48.6), ("Malá & Veľká Fatra, Orava", 19.0, 49.15),
           ("Low Tatras & Central", 19.4, 48.75), ("Tatras & Spiš", 20.8, 49.0),
           ("Eastern Slovakia", 21.0, 48.6)],
    "AT": [("Vorarlberg", 9.9, 47.3), ("Tyrol", 11.4, 47.3),
           ("East Tyrol & Carinthia", 13.6, 46.75), ("Salzburg & Salzkammergut", 13.2, 47.6),
           ("Styria", 15.2, 47.3), ("Upper & Lower Austria", 15.0, 47.9)],
    "IT": [("Dolomites & South Tyrol", 11.6, 46.6), ("Friuli", 13.0, 46.25),
           ("Veneto, Grappa & Belluno", 11.8, 45.85), ("Trentino & Garda", 11.0, 46.0),
           ("Lombardy & the lakes", 9.6, 45.9), ("Piedmont, Aosta & Liguria", 7.6, 45.2),
           ("Apennines, Central & South", 13.0, 42.5)],
    "SI": [("Soča & Julian Alps", 13.6, 46.25), ("Gorenjska & Ljubljana", 14.3, 46.25),
           ("Primorska & Karst", 13.9, 45.75), ("Štajerska, Dolenjska & East", 15.3, 46.3)],
    "CH": [("Valais", 7.6, 46.2), ("Bernese Oberland", 7.8, 46.65),
           ("Lake Geneva & Vaud Alps", None, None), ("Fribourg & Jura", 6.9, 46.85),
           ("Central Switzerland", 8.4, 46.95), ("Eastern Switzerland & Zurich", 9.3, 47.15),
           ("Graubünden", 9.7, 46.7), ("Ticino", 8.9, 46.2)],
    "DE": [("Bavarian Alps", 11.4, 47.65), ("Allgäu", 10.3, 47.55),
           ("Eastern Bavaria & Altmühltal", 13.0, 48.9),
           ("Black Forest & Swabian Jura", 8.6, 48.3), ("Mosel, Palatinate & Hesse", 7.6, 49.9),
           ("Central uplands", 10.5, 51.0), ("North & East", 11.5, 52.6)],
    "FR": [("Haute-Savoie & Mont Blanc", None, None), ("Savoie, Grenoble & Vercors", 6.4, 45.9),
           ("Southern Alps", 6.3, 44.5), ("Provence, Riviera & Corsica", 6.5, 43.7),
           ("Pyrenees", 0.0, 42.95), ("Massif Central & South", 3.0, 44.8),
           ("Jura & Vosges", 6.0, 47.8), ("Normandy & the north", None, None)],
}
MOVES = {
    "SK": {"Eastern Slovakia": ["Kapušianský hrad", "Šarišské Čierne", "Roztoki", "Ďurkovec"],
           "Low Tatras & Central": ["Králova Hoľa"], "Tatras & Spiš": ["Baranec"]},
    "AT": {"Tyrol": ["Hahnenkamm", "Neunerköpfle", "Schönjoch", "Venet", "Kössen"],
           "East Tyrol & Carinthia": ["Defereggen", "Virgen", "Goding"],
           "Styria": ["Greim", "Hauser Kaibling", "Stoderzinken"],
           "Upper & Lower Austria": ["Marsbach"]},
    "IT": {"Apennines, Central & South": ["Monfestino", "Pizzorne", "Sestola", "Monte Caio",
                                          "San Giuliano Terme"],
           "Veneto, Grappa & Belluno": ["Valdagno", "Monte Dolada"]},
    "SI": {"Primorska & Karst": ["Jelenk"], "Štajerska, Dolenjska & East": ["Zapodje"]},
    "CH": {"Valais": ["Fiesch", "Moosfluh", "Riederalp"],
           "Bernese Oberland": ["Wispile", "Metschstand", "Planplatten"],
           "Lake Geneva & Vaud Alps": ["Leysin", "Ollon", "Jaman", "Pléiades", "Sonchaux"],
           "Fribourg & Jura": ["Grandvillard", "Moléson", "Vounetz", "Chasseral", "Le Cernil",
                               "Le Suchet", "Mauborget", "Mont-Soleil", "Montoz",
                               "Niederwiler Stierenberg", "Raimeux", "Saint-Cergue",
                               "Weissenstein", "Hohwacht", "Obere Wengi", "Schwängimatt"],
           "Graubünden": ["Lai Alv", "Cassons", "Crap Sogn Gion"],
           "Eastern Switzerland & Zurich": ["Balderen"]},
    "DE": {"North & East": ["Coesfeld Gaupel", "Fichtelberg", "Zschochau"],
           "Central uplands": ["Wenholthausen"]},
    "FR": {"Haute-Savoie & Mont Blanc": [
               "Abondance", "Col de l'Arpettaz", "Col de la Forclaz", "Col des Aravis",
               "Entrevernes", "La Clusaz", "Le Morclan", "Les Couteaux", "Marlens", "Mieussy",
               "Mont Lachat", "Morzine", "Méruz", "Plaine Joux", "Plan de l'Aigulle",
               "Planfait", "Planpraz", "Salève", "Samoens", "Semnoz", "Varan"],
           "Savoie, Grenoble & Vercors": ["Chamrousse", "Col Vert", "Le Belvédère",
                                         "Moucherotte", "Serpaton"],
           "Jura & Vosges": ["Métabief", "Vesancy", "Drumont", "Treh", "Reinhardsmunster",
                             "Mont Poupet"],
           "Normandy & the north": ["Clécy - Saint Omer", "St Marc d'Ouilly",
                                    "Notre-Dame-de-la-Mer", "Fumay", "Revin", "Létanne"]},
}

# A pgweb point and a ParaglidingEarth takeoff are the same place within this distance;
# two pgweb entries are one takeoff within `SAME_PLACE_M` (pgweb lists a hill in each
# group it belongs to, sometimes under two names: Osser and Osser - Ostrý).
PAIR_M = 1000.0
SAME_PLACE_M = 300.0


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
            "landing": _landing(properties),
            # A tow (winch) site: launched on a line, so the takeoff's height is the
            # field's and there is no hill to fly down.
            "tow": properties.get("winch") == "1",
            "winds": winds,
            "id": int(properties.get("pge_site_id") or 0),
        })
    sites.sort(key=lambda site: site["name"].lower())
    return sites


def _landing(properties: dict) -> int | None:
    """The landing field's altitude, metres AMSL, or None where the record has none.

    The record's own number: checked against Open-Meteo's terrain at the landing's
    coordinates for all fourteen chosen takeoffs that have one (October 2026), it agreed
    to 14 m at worst. A landing with no altitude is left out rather than guessed from a
    DEM, because which field is the landing is the record's knowledge, not the map's.
    """
    landing = properties.get("landing")
    if isinstance(landing, list):
        landing = landing[0] if landing else None
    if not isinstance(landing, dict):
        return None
    try:
        altitude = int(float(landing.get("landing_altitude") or ""))
    except ValueError:
        return None
    return altitude if altitude > 0 else None


def fetch_pgweb() -> list[tuple[str, list[dict]]]:
    """pgweb's groups, in its order: (group name, [{name, country, alt, lat, lon}]).

    Its page hands the whole list to its script as `WeatherApp.init([...])`; an entry at
    0,0 is a group's heading. A name carries ` [CC]` for a takeoff abroad and `, 1234 m`
    in the country lists; both come off here."""
    with urllib.request.urlopen(PGWEB, timeout=TIMEOUT) as response:
        html = response.read().decode("utf-8")
    return read_pgweb(html)


def read_pgweb(html: str) -> list[tuple[str, list[dict]]]:
    marker = "WeatherApp.init("
    at = html.index(marker) + len(marker)
    entries, _ = json.JSONDecoder().raw_decode(html[at:])
    groups: list[tuple[str, list[dict]]] = []
    for entry in entries:
        name = unicodedata.normalize("NFC", entry["name"]).strip()
        if entry["x"] == 0 and entry["y"] == 0:
            groups.append((name.strip("* "), []))
            continue
        if not groups:
            raise ValueError(f"pgweb lists {name!r} before any group")
        found = re.match(r"(.*?)(?: \[(\w\w)\])?(?:, (\d+) m)?$", name)
        groups[-1][1].append({
            "name": found.group(1).strip().rstrip("_").strip(),
            "country": found.group(2),
            "alt": int(found.group(3)) if found.group(3) else None,
            "lat": round(float(entry["y"]), 4),
            "lon": round(float(entry["x"]), 4),
        })
    unknown = [group for group, _ in groups if group not in GROUPS]
    if unknown:
        raise ValueError(f"pgweb has groups this module does not place: {unknown}")
    return groups


def _folded(text: str) -> str:
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode().lower()


def region_of(country: str, name: str, lat: float, lon: float) -> str:
    """The region a takeoff in a country-wide pgweb list goes in (`REGIONS`, `MOVES`)."""
    for region, names in MOVES.get(country, {}).items():
        if name in names:
            return region
    scale = math.cos(math.radians(lat))
    placed = [(r, x, y) for r, x, y in REGIONS[country] if x is not None]
    return min(placed, key=lambda r: ((r[1] - lon) * scale) ** 2 + (r[2] - lat) ** 2)[0]


def build(groups) -> tuple[list[dict], list[dict]]:
    """pgweb's groups as the page's two lists: the takeoffs, each once, and the countries,
    each with its regions holding takeoff indices. Countries alphabetical by name (the
    pilot's call); regions in pgweb's order for Czechia and `REGIONS` order elsewhere,
    essentials first."""
    sites: list[dict] = []

    def place(point: dict, home: str) -> int:
        for i, site in enumerate(sites):
            metres = distance_m(site["lat"], site["lon"], point["lat"], point["lon"])
            if metres < SAME_PLACE_M or (metres < PAIR_M
                                         and _folded(site["name"]) == _folded(point["name"])):
                return i
        sites.append({"name": point["name"], "country": point["country"] or home,
                      "lat": point["lat"], "lon": point["lon"], "alt": point["alt"],
                      "landing": None, "tow": False, "winds": [], "id": 0})
        return len(sites) - 1

    regions: dict[str, dict[str, list[int]]] = {}
    for group, points in groups:
        country, label = GROUPS[group]
        into = regions.setdefault(country, {})
        if label is not None:
            into.setdefault(label, [])
        for point in points:
            index = place(point, country)
            if group == "vlekání":
                sites[index]["tow"] = True
            name = label or region_of(country, point["name"], point["lat"], point["lon"])
            if index not in into.setdefault(name, []):
                into[name].append(index)

    countries = []
    for code in sorted(regions, key=lambda c: COUNTRY_NAMES[c]):
        ordered = list(regions[code])
        if code in REGIONS:
            wanted = [r for r, _, _ in REGIONS[code]]
            ordered = ([r for r in ordered if r not in wanted]
                       + [r for r in wanted if r in regions[code]])
        countries.append({"code": code, "name": COUNTRY_NAMES[code], "regions": [
            {"name": r, "sites": sorted(regions[code][r], key=lambda i: _folded(sites[i]["name"]))}
            for r in ordered if regions[code][r]]})
    return sites, countries


def pair(sites: list[dict], records: dict[str, list[dict]]) -> int:
    """Give each takeoff the wind rose, altitude, landing and id of the ParaglidingEarth
    takeoff within `PAIR_M` of it, nearest first, from `records` (country → that
    country's records, `fetch`). Returns how many were paired; the rest keep no rose and
    are left unjudged rather than guessed at."""
    paired = 0
    for site in sites:
        best, best_m = None, PAIR_M
        for record in records.get(site["country"], []):
            metres = distance_m(site["lat"], site["lon"], record["lat"], record["lon"])
            if metres < best_m:
                best, best_m = record, metres
        if best is None:
            continue
        paired += 1
        # ParaglidingEarth's point is the takeoff itself, to four decimals; pgweb's is
        # to three (~100 m) and sometimes the hill rather than the launch.
        site.update(winds=best["winds"], landing=best["landing"], id=best["id"],
                    tow=site["tow"] or best["tow"], alt=best["alt"] or site["alt"],
                    lat=best["lat"], lon=best["lon"])
    return paired


def keep_roses(sites: list[dict], previous: list[dict]) -> int:
    """For a refresh while ParaglidingEarth is down: each takeoff keeps what the
    committed list had for the same place, so no rose is lost to an outage."""
    kept = 0
    for site in sites:
        for old in previous:
            if old.get("winds") and distance_m(site["lat"], site["lon"], old["lat"], old["lon"]) < PAIR_M:
                site.update(winds=old["winds"], landing=old["landing"], id=old["id"],
                            alt=old["alt"] or site["alt"], lat=old["lat"], lon=old["lon"])
                kept += 1
                break
    return kept


ELEVATION = "https://api.open-meteo.com/v1/elevation?latitude={lat}&longitude={lon}"


def fill_altitudes(sites: list[dict]) -> int:
    """The takeoffs neither list gives a height for (pgweb's Czech groups carry none),
    from Open-Meteo's terrain model (Copernicus, 90 m), a hundred at a time."""
    missing = [site for site in sites if not site["alt"]]
    for start in range(0, len(missing), 100):
        chunk = missing[start:start + 100]
        url = ELEVATION.format(lat=",".join(str(s["lat"]) for s in chunk),
                               lon=",".join(str(s["lon"]) for s in chunk))
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            heights = json.loads(response.read().decode("utf-8"))["elevation"]
        for site, height in zip(chunk, heights):
            site["alt"] = int(round(height))
    return len(missing)


def write(path: Path, sites: list[dict], countries: list[dict], roses: str) -> None:
    """Rewrite `sites.py`, provenance first."""
    today = dt.date.today().isoformat()
    lines = [
        '"""Paragliding takeoffs, as committed data.',
        "",
        f"Generated by `meteo.sources` on {today}: the takeoffs and their regions from",
        f"pgweb's list ({PGWEB}), each paired with the",
        "ParaglidingEarth takeoff within a kilometre for its wind rose, landing and id",
        f"({roses}).",
        "",
        "`landing` is the landing field's altitude in metres, None where none is recorded;",
        "`tow` marks a winch site, where the height to the landing means nothing.",
        "`winds` is ParaglidingEarth's own suitability per octant, N first and clockwise:",
        "0 unflyable, 1 marginal, 2 good. An empty list means no rose was found, and",
        "the page then refuses to judge it against the forecast rather than guessing.",
        "`COUNTRIES` holds each country's regions as indices into `SITES`; a takeoff can",
        "be in more than one region (Essentials Czechia, and its own).",
        '"""',
        "",
        f'SOURCE = "{PGWEB}"',
        f'FETCHED = "{today}"',
        f'ATTRIBUTION = "{PGWEB_ATTRIBUTION}; wind roses from ParaglidingEarth, CC BY-SA"',
        'OCTANTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")',
        "",
        "SITES = [",
    ]
    for site in sites:
        lines.append(
            f'    {{"name": {site["name"]!r}, "country": {site["country"]!r}, '
            f'"lat": {site["lat"]}, '
            f'"lon": {site["lon"]}, "alt": {site["alt"]}, "landing": {site["landing"]}, '
            f'"tow": {site["tow"]}, '
            f'"winds": {site["winds"]}, "id": {site["id"]}}},'
        )
    lines += ["]", "", "COUNTRIES = ["]
    for country in countries:
        lines.append(f'    {{"code": {country["code"]!r}, "name": {country["name"]!r}, "regions": [')
        for region in country["regions"]:
            lines.append(f'        {{"name": {region["name"]!r}, "sites": {region["sites"]}}},')
        lines.append("    ]},")
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

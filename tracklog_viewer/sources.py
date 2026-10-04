"""Where a flight can come from: a file, a URL, or an XContest page.

One entry point, :func:`load`, so the CLI and any future front-end do not have to
know how many shapes an input can take.

On XContest links: a flight *detail page* does not carry the track. The page is a
JavaScript shell behind Cloudflare Turnstile, and the download links only appear for
a logged-in session — so there is nothing to scrape without holding someone's
credentials, and no amount of cleverness here changes that. What we do instead is
read the public metadata out of the page title (pilot, date, XContest's own scored
distance — useful as an independent check on our optimiser) and then tell the caller
exactly which file to hand over. A *direct* link to an .igc/.kmz file downloads and
works normally.
"""

import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import igc, kml
from .igc import Flight

CACHE = Path.home() / ".cache" / "parainsights" / "downloads"
TIMEOUT = 30
# Plain browser UA: some track hosts refuse the urllib default outright.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)
XCONTEST_HOST_RE = re.compile(r"(^|\.)xcontest\.org$", re.I)
# "Detail přeletu : Ondřej Chmelař - 28.7.2026 - VP - 64.09 km :: XContest.org …"
XC_TITLE_RE = re.compile(
    r"<title>[^:<]*:\s*(?P<pilot>[^-<]+?)\s*-\s*(?P<date>[\d.]+)\s*-\s*"
    r"(?P<kind>[A-Z]{1,4})\s*-\s*(?P<distance>[\d.]+)\s*km",
    re.I | re.S,
)
TRACK_SUFFIXES = (".igc", ".kmz", ".kml")


class SourceError(ValueError):
    """The input could not be turned into a flight."""


@dataclass
class XContestFlight:
    """Public metadata from an XContest flight page."""

    url: str
    pilot: str | None = None
    date: str | None = None
    kind: str | None = None
    distance_km: float | None = None


def _download(url: str) -> tuple[bytes, str]:
    """Fetch a URL, caching by URL. Returns (body, filename)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    name = Path(urllib.parse.urlparse(url).path).name or "download"
    cached = CACHE / f"{key}-{name}"
    if cached.exists():
        return cached.read_bytes(), cached.name

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise SourceError(f"could not fetch {url}: {error}") from None
    cached.write_bytes(body)
    return body, cached.name


def xcontest_metadata(url: str) -> XContestFlight:
    """Read what the public XContest page will tell us without a login."""
    body, _ = _download(url)
    text = body.decode("utf-8", errors="replace")
    match = XC_TITLE_RE.search(text)
    if not match:
        return XContestFlight(url=url)
    return XContestFlight(
        url=url,
        pilot=match.group("pilot").strip(),
        date=match.group("date").strip(),
        kind=match.group("kind").strip(),
        distance_km=float(match.group("distance")),
    )


def _is_xcontest_page(parsed) -> bool:
    if not XCONTEST_HOST_RE.search(parsed.netloc.split(":")[0]):
        return False
    return not parsed.path.lower().endswith(TRACK_SUFFIXES)


def _parse_bytes(body: bytes, name: str, *, filter_fixes: bool) -> Flight:
    """Dispatch on content, not just on the file name, since URLs lie."""
    suffix = Path(name).suffix.lower()
    scratch = CACHE / f"parse-{name}"
    CACHE.mkdir(parents=True, exist_ok=True)
    scratch.write_bytes(body)
    try:
        if suffix == ".igc" or body[:1] in (b"A", b"H"):
            return igc.parse(scratch, filter_fixes=filter_fixes)
        if suffix in (".kmz", ".kml") or body[:2] == b"PK" or b"<kml" in body[:2000]:
            return kml.parse(scratch, filter_fixes=filter_fixes)
    finally:
        scratch.unlink(missing_ok=True)
    raise SourceError(f"{name}: not recognised as IGC, KML or KMZ")


def local_path(source: str | Path) -> Path:
    """Where the bytes of a source are on disk: the file itself, or a URL's download in
    the cache (`load` has fetched it by the time anyone asks)."""
    text = str(source)
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme in ("http", "https"):
        _download(text)
        key = hashlib.sha256(text.encode()).hexdigest()[:16]
        return CACHE / f"{key}-{Path(parsed.path).name or 'download'}"
    return Path(text).expanduser()


def load(source: str | Path, *, filter_fixes: bool = True) -> Flight:
    """Load a flight from a path, a track URL, or raise for an XContest page."""
    text = str(source)
    parsed = urllib.parse.urlparse(text)

    if parsed.scheme in ("http", "https"):
        if _is_xcontest_page(parsed):
            meta = xcontest_metadata(text)
            described = (
                f"{meta.pilot}, {meta.date}, {meta.distance_km:.2f} km"
                if meta.pilot and meta.distance_km
                else "this flight"
            )
            raise SourceError(
                f"XContest flight page recognised ({described}), but the track is not "
                "downloadable without a login: the page is a JavaScript shell behind a "
                "Cloudflare challenge and the IGC link only exists for a signed-in "
                "session. Download the IGC or KMZ from the page and pass the file, or "
                "pass a direct link to the .igc/.kmz."
            )
        body, name = _download(text)
        return _parse_bytes(body, name, filter_fixes=filter_fixes)

    path = Path(text).expanduser()
    if not path.exists():
        raise SourceError(f"{path} does not exist")
    suffix = path.suffix.lower()
    if suffix == ".igc":
        return igc.parse(path, filter_fixes=filter_fixes)
    if suffix in (".kmz", ".kml"):
        return kml.parse(path, filter_fixes=filter_fixes)
    # Unknown extension: sniff the content rather than refuse.
    return _parse_bytes(path.read_bytes(), path.name, filter_fixes=filter_fixes)

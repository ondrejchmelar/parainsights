"""Read a flight track out of KML or KMZ.

Written against the two flavours in hand — XContest's export and igc2kmz's output —
plus ``gx:Track``, which is what Google Earth and most modern exporters write.

A KML is a lossy container for a tracklog: XContest samples its timed points every
~15 s even though the file also holds the full-resolution line (without times), and
nobody records pressure altitude. So an IGC is always the better input when you have
one; this exists for when you only kept the KMZ.
"""

import datetime as dt
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import numpy as np

from .igc import Flight, Headers, _timezone_from_position

# Namespace-agnostic: KML in the wild uses kml/2.2, earth.google.com/kml/2.2 and
# occasionally none at all, and matching on the local name sidesteps all of it.
GX_WHEN = "when"
COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)[,\s]+(-?\d+(?:\.\d+)?)(?:[,\s]+(-?\d+(?:\.\d+)?))?")


class NoTrackError(ValueError):
    """The file parsed, but holds no timed positions we can analyse."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element) -> str:
    return (element.text or "").strip()


def _parse_when(value: str) -> dt.datetime | None:
    """KML timestamps are ISO 8601, usually with a Z, sometimes with an offset."""
    value = value.strip()
    if not value:
        return None
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return stamp


def read_bytes(data: bytes) -> str:
    """Return the KML document from either raw KML or a KMZ archive."""
    if data[:2] == b"PK":
        import io

        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".kml")]
            if not names:
                raise NoTrackError("KMZ contains no .kml document")
            # Google Earth takes the first .kml it finds; so do we.
            return archive.read(names[0]).decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


def _from_gx_track(root) -> list[tuple[dt.datetime, float, float, float]]:
    """``gx:Track``: alternating <when> and <gx:coord> children."""
    fixes = []
    for element in root.iter():
        if _local(element.tag) != "Track":
            continue
        whens, coords = [], []
        for child in element:
            name = _local(child.tag)
            if name == "when":
                whens.append(_parse_when(_text(child)))
            elif name == "coord":
                parts = _text(child).split()
                if len(parts) >= 2:
                    coords.append(
                        (
                            float(parts[0]),
                            float(parts[1]),
                            float(parts[2]) if len(parts) > 2 else 0.0,
                        )
                    )
        for when, (lon, lat, alt) in zip(whens, coords):
            if when is not None:
                fixes.append((when, lat, lon, alt))
    return fixes


def _from_timed_placemarks(root) -> list[tuple[dt.datetime, float, float, float]]:
    """Placemarks carrying a Point and a TimeStamp or TimeSpan.

    This is XContest's shape (``<TimeStamp><when>``) and igc2kmz's animation folder
    (``<TimeSpan><begin>``).
    """
    fixes = []
    for element in root.iter():
        if _local(element.tag) != "Placemark":
            continue
        when = None
        position = None
        for node in element.iter():
            name = _local(node.tag)
            if name in ("when", "begin") and when is None:
                when = _parse_when(_text(node))
            elif name == "coordinates" and position is None:
                match = COORD_RE.search(_text(node))
                if match:
                    lon, lat, alt = match.groups()
                    position = (float(lon), float(lat), float(alt) if alt else 0.0)
        if when is not None and position is not None:
            fixes.append((when, position[1], position[0], position[2]))
    return fixes


def parse(path, *, filter_fixes: bool = True) -> Flight:
    """Parse a KML or KMZ file into the same :class:`Flight` an IGC produces."""
    path = Path(path)
    document = read_bytes(path.read_bytes())
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise NoTrackError(f"{path.name}: not parseable XML ({error})") from None

    fixes = _from_gx_track(root)
    source = "gx:Track"
    if not fixes:
        fixes = _from_timed_placemarks(root)
        source = "timed placemarks"
    if len(fixes) < 2:
        raise NoTrackError(
            f"{path.name}: no timed positions found. A KML holding only a LineString has "
            "no timestamps, so climb rates and phases cannot be derived — use the IGC."
        )

    fixes.sort(key=lambda fix: fix[0])
    times = np.array([fix[0] for fix in fixes], dtype="datetime64[s]")
    lat = np.array([fix[1] for fix in fixes])
    lon = np.array([fix[2] for fix in fixes])
    alt = np.array([fix[3] for fix in fixes], dtype=float)

    name = next(
        (
            _text(node)
            for node in root.iter()
            if _local(node.tag) == "name" and _text(node)
        ),
        path.stem,
    )
    headers = Headers(
        manufacturer="KML",
        date=times[0].astype("datetime64[s]").item().date(),
        logger_type=f"{name} ({source})",
    )

    flight = Flight(
        headers=headers,
        time=times,
        lat=lat,
        lon=lon,
        # A KML records one altitude and never says which datum; treat it as GPS,
        # which is what every exporter in hand actually writes.
        alt_baro=np.zeros_like(alt),
        alt_gps=alt,
        validity=np.ones(len(alt), dtype=bool),
        warnings=[
            f"read from {path.suffix.lstrip('.').upper()} via {source}: "
            f"{len(fixes)} points at ~{_interval(times):.0f} s, no pressure altitude"
        ],
    )

    resolved = _timezone_from_position(flight.lat[0], flight.lon[0])
    if resolved:
        flight.timezone, flight.timezone_source = resolved

    if filter_fixes:
        from .igc import filter_bad_fixes

        return filter_bad_fixes(flight)
    return flight


def _interval(times: np.ndarray) -> float:
    if len(times) < 2:
        return 0.0
    steps = np.diff(times).astype("int64")
    return float(np.median(steps))

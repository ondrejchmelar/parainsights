"""IGC tracklog parsing.

Every logger quirk lives in this module. Everything downstream sees clean numpy
arrays and a resolved timezone, and never has to know that XCTrack hides the
timezone in a base64 blob or that SkyDrop leaves the pilot name empty.
"""

import base64
import datetime as dt
import functools
import json
import re
import zoneinfo
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

# B1053324925977N01437750EA004100049253
#  ^time  ^lat      ^lon      ^ ^baro ^gps  ^I-record extensions
B_RE = re.compile(
    r"B(\d{2})(\d{2})(\d{2})"
    r"(\d{2})(\d{5})([NS])"
    r"(\d{3})(\d{5})([EW])"
    r"([AV])"
    r"(-\d{4}|\d{5})(-\d{4}|\d{5})"
)
# Both spellings occur in the wild: HFDTE290523 and HFDTEDATE:280918,01
HFDTE_RE = re.compile(r"H.DTE(?:DATE:)?(\d\d)(\d\d)(\d\d)(?:,(\d\d))?\s*$")
# Source letter is F/O/P per spec, but XCTrack emits HSCCL — accept any letter.
H_RE = re.compile(r"H(.)([0-9A-Z]{3})([^:]*)(?::(.*))?$", re.S)
I_RE = re.compile(r"I(\d{2})(.*)$")
I_FIELD_RE = re.compile(r"(\d{2})(\d{2})([A-Z]{3})")
C_TASK_RE = re.compile(r"C(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{6}|-{6})(\d{2})(\d{2})(.*)$")
C_TP_RE = re.compile(r"C(\d{2})(\d{5})([NS])(\d{3})(\d{5})([EW])(.*)$")
# XCTrack splits a JSON device description across many L records.
LXCT_DEVICE_RE = re.compile(r"L(?:XCT)?DEVICE\s?(.*)$")
# SkyDrop: HFTZNTIMEZONE:+2.0
TZ_OFFSET_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*$")
NOT_SET_RE = re.compile(r"\s*(not\s+set|n/?a|\?|-+)?\s*$", re.I)

FILTER_MAX_GROUND_SPEED = 100.0  # m/s
FILTER_MAX_VERTICAL_SPEED = 30.0  # m/s


def _clean(value: str | None) -> str | None:
    """Return a header value, or None if it is absent or a placeholder."""
    if value is None:
        return None
    value = value.strip()
    return None if NOT_SET_RE.match(value) else value


@dataclass
class Headers:
    """Flight metadata from the A/H records."""

    manufacturer: str | None = None
    logger_id: str | None = None
    date: dt.date | None = None
    flight_of_day: int | None = None
    pilot: str | None = None
    glider_type: str | None = None
    glider_id: str | None = None
    site: str | None = None
    logger_type: str | None = None
    firmware: str | None = None
    competition_class: str | None = None
    pressure_sensor: str | None = None
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class Turnpoint:
    name: str
    lat: float
    lon: float


@dataclass
class Flight:
    """A parsed tracklog: metadata plus parallel arrays, one entry per fix.

    Altitudes are kept as two separate series on purpose. ``alt_baro`` is
    ISA-referenced pressure altitude, so it is offset from true altitude by
    whatever the QNH was, but it is smooth and is the better input for climb
    rate. ``alt_gps`` is geometric and is what should be displayed. Never mix
    them in one calculation; see :attr:`baro_offset`.
    """

    headers: Headers
    time: np.ndarray  # datetime64[s], UTC
    lat: np.ndarray  # degrees, +N
    lon: np.ndarray  # degrees, +E
    alt_baro: np.ndarray  # metres, ISA pressure altitude (0 if no baro)
    alt_gps: np.ndarray  # metres, WGS-84 geometric
    validity: np.ndarray  # bool, True for a 3D fix
    extensions: dict[str, np.ndarray] = field(default_factory=dict)
    timezone: dt.tzinfo | None = None
    timezone_source: str | None = None
    task: list[Turnpoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dropped: Counter = field(default_factory=Counter)

    def __len__(self) -> int:
        return len(self.time)

    @property
    def has_baro(self) -> bool:
        return bool(np.any(self.alt_baro))

    @property
    def alt(self) -> np.ndarray:
        """The altitude series to use for vertical analysis."""
        return self.alt_baro if self.has_baro else self.alt_gps

    @property
    def baro_offset(self) -> float | None:
        """Median GPS-minus-baro difference, in metres.

        Reflects the QNH of the day. Add it to ``alt_baro`` to get a series that
        is both smooth and roughly correct in absolute terms.
        """
        if not self.has_baro:
            return None
        return float(np.median(self.alt_gps - self.alt_baro))

    @property
    def duration(self) -> dt.timedelta:
        return (self.time[-1] - self.time[0]).astype("timedelta64[s]").item()

    def local_time(self, index: int = 0) -> dt.datetime:
        """Fix ``index`` as a local datetime, if the timezone is known."""
        utc = self.time[index].astype("datetime64[s]").item().replace(tzinfo=dt.timezone.utc)
        return utc.astimezone(self.timezone) if self.timezone else utc


def _parse_i_record(line: str) -> dict[str, slice]:
    """Map extension codes to the byte range they occupy in every B record."""
    match = I_RE.match(line)
    if not match:
        return {}
    fields = {}
    for field_match in I_FIELD_RE.finditer(match.group(2)):
        start, end, code = field_match.groups()
        fields[code] = slice(int(start) - 1, int(end))
    return fields


def _parse_headers(line: str, headers: Headers) -> None:
    date_match = HFDTE_RE.match(line)
    if date_match:
        day, month, year, flight = date_match.groups()
        # Two-digit years: IGC has no century, but no tracklog predates 1980.
        year = int(year)
        year += 2000 if year < 80 else 1900
        try:
            headers.date = dt.date(year, int(month), int(day))
        except ValueError:
            raise ValueError(f"invalid date in {line!r}") from None
        if flight is not None:
            headers.flight_of_day = int(flight)
        return

    match = H_RE.match(line)
    if not match:
        raise ValueError(f"unparseable H record {line!r}")
    _source, code, inline, after_colon = match.groups()
    # Value is after the colon when there is one, else whatever follows the code.
    value = after_colon if after_colon is not None else inline
    headers.raw[code] = (value or "").strip()

    setters = {
        "PLT": "pilot",
        "GTY": "glider_type",
        "GID": "glider_id",
        "SIT": "site",
        "FTY": "logger_type",
        "RFW": "firmware",
        "CCL": "competition_class",
        "PRS": "pressure_sensor",
    }
    if code in setters:
        setattr(headers, setters[code], _clean(value))


def _timezone_from_l_records(l_records: list[str]) -> tuple[dt.tzinfo, str] | None:
    """Recover the IANA timezone from XCTrack's base64 device JSON."""
    chunks = [m.group(1) for line in l_records if (m := LXCT_DEVICE_RE.match(line))]
    if not chunks:
        return None
    payload = "".join(chunks)
    try:
        # The chunking drops padding; base64 tolerates too much of it.
        decoded = base64.b64decode(payload + "==", validate=False)
        name = json.loads(decoded)["os"]["timezone"]
        return zoneinfo.ZoneInfo(name), f"LXCTDEVICE ({name})"
    except (ValueError, KeyError, TypeError, zoneinfo.ZoneInfoNotFoundError):
        return None


@functools.cache
def _timezone_finder():
    """One finder per process. Building one loads its boundary dataset, 1.6-1.9 s, and
    it used to be built afresh for every file parsed — which is most of what a test of a
    synthetic 200 s flight spent its time on. The lookup itself is microseconds."""
    from timezonefinder import TimezoneFinder
    return TimezoneFinder()


def _timezone_from_position(lat: float, lon: float) -> tuple[dt.tzinfo, str] | None:
    """Fall back to looking the timezone up from the take-off coordinates.

    Needed for the majority of real files: XCTrack only started writing
    ``os.timezone`` into its device JSON in 0.9.12, and nothing before that
    records a timezone at all.
    """
    try:
        finder = _timezone_finder()
    except ImportError:
        return None
    name = finder.timezone_at(lat=lat, lng=lon)
    if not name:
        return None
    return zoneinfo.ZoneInfo(name), f"position ({name})"


def _timezone_from_header(headers: Headers) -> tuple[dt.tzinfo, str] | None:
    """SkyDrop and friends write a fixed UTC offset in HFTZN."""
    raw = headers.raw.get("TZN")
    if not raw:
        return None
    match = TZ_OFFSET_RE.search(raw)
    if not match:
        return None
    hours = float(match.group(1))
    offset = dt.timezone(dt.timedelta(hours=hours))
    return offset, f"HFTZN ({hours:+g})"


def parse(path, *, filter_fixes: bool = True) -> Flight:
    """Parse an IGC file.

    Malformed records are collected in :attr:`Flight.warnings` rather than
    raising: real files from real loggers contain junk, and one bad line should
    not cost us a flight.
    """
    with open(path, encoding="utf-8", errors="replace") as stream:
        lines = stream.read().splitlines()

    headers = Headers()
    extension_fields: dict[str, slice] = {}
    l_records: list[str] = []
    task: list[Turnpoint] = []
    warnings: list[str] = []

    times: list[dt.datetime] = []
    lats: list[float] = []
    lons: list[float] = []
    baros: list[int] = []
    gpss: list[int] = []
    valids: list[bool] = []
    raw_extensions: dict[str, list[int | None]] = {}

    date = None
    previous_seconds = None

    for line in lines:
        line = line.rstrip()
        if not line:
            continue
        record = line[0]

        if record == "A":
            headers.manufacturer = line[1:4] or None
            headers.logger_id = line[4:].strip() or None

        elif record == "H":
            try:
                _parse_headers(line, headers)
            except ValueError as error:
                warnings.append(str(error))
            if headers.date is not None:
                date = headers.date

        elif record == "I":
            extension_fields = _parse_i_record(line)
            raw_extensions = {code: [] for code in extension_fields}

        elif record == "L":
            l_records.append(line)

        elif record == "C":
            if C_TASK_RE.match(line):
                continue  # task header, not a turnpoint
            match = C_TP_RE.match(line)
            if match:
                lat = int(match.group(1)) + int(match.group(2)) / 60000
                if match.group(3) == "S":
                    lat = -lat
                lon = int(match.group(4)) + int(match.group(5)) / 60000
                if match.group(6) == "W":
                    lon = -lon
                if lat or lon:  # all-zero turnpoints are padding
                    task.append(Turnpoint(match.group(7).strip(), lat, lon))

        elif record == "B":
            match = B_RE.match(line)
            if not match:
                warnings.append(f"unparseable B record {line!r}")
                continue
            if date is None:
                warnings.append("B record before HFDTE; assuming 1970-01-01")
                date = dt.date(1970, 1, 1)
                headers.date = date

            hours, minutes, seconds = (int(match.group(i)) for i in (1, 2, 3))
            time_of_day = hours * 3600 + minutes * 60 + seconds
            if previous_seconds is not None and time_of_day < previous_seconds - 43200:
                # Went backwards by more than half a day: midnight rollover.
                date += dt.timedelta(days=1)
            previous_seconds = time_of_day

            lat = int(match.group(4)) + int(match.group(5)) / 60000
            lon = int(match.group(7)) + int(match.group(8)) / 60000
            # LAD/LOD add a further decimal digit of minutes.
            for code, sign_group, accumulator in (("LAD", 6, "lat"), ("LOD", 9, "lon")):
                if code in extension_fields:
                    digits = line[extension_fields[code]]
                    if digits.isdigit():
                        delta = int(digits) / (60000 * 10 ** len(digits))
                        if accumulator == "lat":
                            lat += delta
                        else:
                            lon += delta
            if match.group(6) == "S":
                lat = -lat
            if match.group(9) == "W":
                lon = -lon

            try:
                stamp = dt.datetime.combine(date, dt.time(hours, minutes, seconds))
            except ValueError:
                # The regex accepts any six digits, so 61 seconds or hour 25 get this
                # far. One impossible clock reading should cost that fix, not the file.
                warnings.append(f"impossible time in {line!r}")
                previous_seconds = None
                continue
            times.append(stamp)
            lats.append(lat)
            lons.append(lon)
            valids.append(match.group(10) == "A")
            baros.append(int(match.group(11)))
            gpss.append(int(match.group(12)))
            for code, byte_range in extension_fields.items():
                digits = line[byte_range]
                raw_extensions[code].append(int(digits) if digits.isdigit() else None)

    if not times:
        raise ValueError(f"{path}: no valid B records")

    flight = Flight(
        headers=headers,
        time=np.array(times, dtype="datetime64[s]"),
        lat=np.array(lats),
        lon=np.array(lons),
        alt_baro=np.array(baros, dtype=float),
        alt_gps=np.array(gpss, dtype=float),
        validity=np.array(valids, dtype=bool),
        extensions={
            code: np.array([np.nan if v is None else v for v in values], dtype=float)
            for code, values in raw_extensions.items()
            if code not in ("LAD", "LOD") and any(v for v in values)
        },
        task=task,
        warnings=warnings,
    )

    resolved = (
        _timezone_from_l_records(l_records)
        or _timezone_from_header(headers)
        or _timezone_from_position(flight.lat[0], flight.lon[0])
    )
    if resolved:
        flight.timezone, flight.timezone_source = resolved

    return filter_bad_fixes(flight) if filter_fixes else flight


def despike_altitude(alt: np.ndarray, *, window: int = 5, threshold: float = 30.0) -> tuple[np.ndarray, int]:
    """Replace GPS altitude spikes with a local median.

    A spike is a sample more than ``threshold`` metres from the median of its
    neighbours. At 1 Hz no paraglider can move 30 m vertically between fixes, so
    anything that far off the local median is receiver noise, not flight.

    Returns the repaired series and the number of samples changed.
    """
    if len(alt) < window:
        return alt, 0
    half = window // 2
    padded = np.pad(alt, half, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)
    median = np.median(windows, axis=1)
    spikes = np.abs(alt - median) > threshold
    if not spikes.any():
        return alt, 0
    repaired = alt.copy()
    repaired[spikes] = median[spikes]
    return repaired, int(spikes.sum())


def filter_bad_fixes(flight: Flight) -> Flight:
    """Clean up fixes, recording what happened in ``flight.dropped``.

    Two different problems, deliberately handled differently:

    * broken *position* or time — duplicate/backwards timestamps and wild GPS
      jumps — the fix is dropped, there is nothing to salvage;
    * broken *altitude* — the fix is kept and the altitude repaired. 36 of the
      60 sample files have no baro sensor at all, so GPS altitude is the only
      vertical source and it is spiky; dropping those fixes would throw away
      good horizontal track to fix a vertical problem.
    """
    from .geo import distance  # local import: geo has no dependency on igc

    keep = np.zeros(len(flight), dtype=bool)
    keep[0] = True
    dropped: Counter = Counter()

    last = 0
    for i in range(1, len(flight)):
        gap = (flight.time[i] - flight.time[last]).astype("int64").item()
        if gap <= 0:
            dropped["duplicate or backwards timestamp"] += 1
            continue
        ground = distance(flight.lat[last], flight.lon[last], flight.lat[i], flight.lon[i])
        if ground / gap > FILTER_MAX_GROUND_SPEED:
            dropped["implausible ground speed"] += 1
            continue
        keep[i] = True
        last = i

    alt_gps, gps_spikes = despike_altitude(flight.alt_gps[keep])
    if gps_spikes:
        dropped["GPS altitude spikes repaired"] = gps_spikes
    alt_baro = flight.alt_baro[keep]
    if flight.has_baro:
        alt_baro, baro_spikes = despike_altitude(alt_baro)
        if baro_spikes:
            dropped["baro altitude spikes repaired"] = baro_spikes

    if not dropped:
        return flight

    filtered = Flight(
        headers=flight.headers,
        time=flight.time[keep],
        lat=flight.lat[keep],
        lon=flight.lon[keep],
        alt_baro=alt_baro,
        alt_gps=alt_gps,
        validity=flight.validity[keep],
        extensions={code: values[keep] for code, values in flight.extensions.items()},
        timezone=flight.timezone,
        timezone_source=flight.timezone_source,
        task=flight.task,
        warnings=flight.warnings,
        dropped=dropped,
    )
    return filtered

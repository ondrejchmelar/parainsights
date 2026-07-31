"""The pilot's own archive: percentiles instead of opinions.

`docs/analysis-plan.md` calls this the single biggest win available, and the reason is
narrow: it is what turns every threshold in `debrief.THRESHOLDS` from a round number that
sounds right into an observation. *"Your weakest climb selection in 12 flights"* is a
sentence no single flight can produce, and it is the difference between the tool answering
*"was that a good flight"* and *"was that a good flight **for you**"*.

Three constraints shape the whole design:

* **Tracklogs stay out of the repository** — `*.igc` is gitignored, and the archive is a
  cache of *summaries*, a few KB of JSON per flight and no track data at all. That is also
  what makes the tests possible without shipping flights: the fixtures are summary JSON.
* **Offline.** Reading an archive touches no network, and neither does writing one.
* **A cold start is normal.** One flight has no percentiles, and the honest answer is to
  say nothing rather than to rank a flight against itself. Every accessor below returns
  `None` rather than a meaningless number.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import metrics
from .analysis import Analysis

# The archive format's version, so a summary written by an older build can be recognised
# rather than silently misread. Bump it when a field changes meaning, not when one is
# added — a reader tolerates missing keys by design.
FORMAT = 1
# Fewer flights than this and a percentile is theatre.
MIN_FLIGHTS = 5


@dataclass
class Summary:
    """One flight, reduced to the numbers a baseline is built from.

    Deliberately flat and deliberately small: no per-segment data, no series, nothing that
    could reconstruct a track. What is here is what a percentile can be taken of.
    """

    date: str
    takeoff_time: str
    site: str | None
    duration: int
    airtime_climbing: int
    climbs: int
    mean_climb: float | None
    best_climb: float | None
    total_gain: float
    max_altitude: float
    track_km: float
    scored_km: float | None
    glide_ld: float | None
    weak_climb_share: float | None
    centring_ratio: float | None
    day_slope: float | None
    detour_ratio: float | None
    ceiling_used: float | None
    wind_kmh: float | None
    sample_interval: float
    format: int = FORMAT

    def to_dict(self) -> dict:
        return asdict(self)


def summarise(analysis: Analysis, *, route=None, weather=None) -> Summary:
    """Reduce a flight to its archive entry."""
    summary = analysis.summary
    thermals = analysis.thermals
    climbing = sum(s.duration for s in thermals)
    mean_climb = (
        sum(s.altitude_change for s in thermals) / climbing if climbing else None
    )

    selection = metrics.climb_selection(analysis)
    index = metrics.centring(analysis)
    envelope = metrics.day_envelope(analysis)
    ratio = metrics.detour(analysis, route)
    ceiling = metrics.ceiling_use(analysis, weather)

    return Summary(
        date=summary.date,
        takeoff_time=summary.takeoff_time,
        site=summary.site,
        duration=summary.duration,
        airtime_climbing=climbing,
        climbs=len(thermals),
        mean_climb=round(mean_climb, 2) if mean_climb is not None else None,
        best_climb=round(max((s.average_climb for s in thermals), default=0.0), 2)
        if thermals
        else None,
        total_gain=summary.total_gain,
        max_altitude=summary.max_altitude,
        track_km=round(summary.track_distance / 1000.0, 1),
        scored_km=round(route.distance / 1000.0, 2)
        if route is not None and getattr(route, "distance", 0)
        else None,
        glide_ld=metrics.glide_ratio_median(analysis),
        weak_climb_share=round(selection.fraction, 2) if selection else None,
        centring_ratio=index.ratio if index else None,
        day_slope=envelope.slope if envelope else None,
        detour_ratio=ratio.ratio if ratio else None,
        ceiling_used=ceiling.fraction if ceiling else None,
        wind_kmh=round(analysis.wind.kmh, 1) if analysis.wind else None,
        sample_interval=summary.sample_interval,
    )


def _key(summary: Summary) -> str:
    """One file per flight.

    Date and site alone are not unique — a pilot can fly twice in a day from the same
    launch, and keying on those silently overwrote the morning flight with the afternoon
    one. Take-off time disambiguates, and re-analysing the *same* flight still lands on
    the same file rather than accumulating duplicates.
    """
    site = (summary.site or "flight").replace("/", "-").replace(" ", "-")
    clock = summary.takeoff_time.replace(":", "")
    return f"{summary.date}-{clock}-{site}.json"


def save(summary: Summary, directory: str | Path) -> Path:
    """Write one summary into the archive, overwriting the same flight's entry."""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    target = path / _key(summary)
    target.write_text(json.dumps(summary.to_dict(), indent=1), encoding="utf-8")
    return target


def load(directory: str | Path) -> list[dict]:
    """Every summary in an archive directory.

    A file that is not readable JSON is skipped rather than fatal: an archive is a cache
    the user owns, and one bad file should not take the report down with it.
    """
    path = Path(directory)
    if not path.is_dir():
        return []
    found = []
    for entry in sorted(path.glob("*.json")):
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("format") == FORMAT:
            found.append(payload)
    return found


@dataclass
class Baseline:
    """The distribution of one pilot's own flights."""

    flights: list[dict] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.flights)

    @property
    def usable(self) -> bool:
        return len(self.flights) >= MIN_FLIGHTS

    def values(self, name: str) -> list[float]:
        return [
            float(flight[name])
            for flight in self.flights
            if flight.get(name) is not None
        ]

    def median(self, name: str) -> float | None:
        values = self.values(name)
        return round(float(np.median(values)), 2) if len(values) >= MIN_FLIGHTS else None

    def percentile_of(self, name: str, value: float | None) -> float | None:
        """Where `value` sits in the archive, 0..1.

        The flight being described is normally *in* the archive, which is correct: a
        percentile of one's own flights includes the flight. What is not correct is
        ranking a flight against fewer than `MIN_FLIGHTS` others, so that returns None.
        """
        if value is None:
            return None
        values = self.values(name)
        if len(values) < MIN_FLIGHTS:
            return None
        below = sum(1 for other in values if other < value)
        equal = sum(1 for other in values if other == value)
        return round((below + equal / 2.0) / len(values), 2)

    def rank_sentence(self, name: str, value: float | None, label: str,
                      *, higher_is_better: bool = True) -> str | None:
        """One phrase placing this flight among the others, or nothing.

        Past tense, no advice, and it names the sample size — "best of 12" and "best of 3"
        are very different claims and the reader is entitled to know which one this is.
        """
        share = self.percentile_of(name, value)
        if share is None:
            return None
        count = len(self.values(name))
        if not higher_is_better:
            share = 1.0 - share
        if share >= 0.9:
            where = "among your best"
        elif share >= 0.6:
            where = "above your median"
        elif share > 0.4:
            where = "about your median"
        elif share > 0.1:
            where = "below your median"
        else:
            where = "among your weakest"
        return f"{label}: {where} of {count} flights"


def build(directory: str | Path | None) -> Baseline:
    """Load an archive, or an empty baseline when there is none.

    An absent `--archive` is the normal case, not an error: the report degrades to saying
    nothing about the pilot's history, which is exactly what it knows.
    """
    if directory is None:
        return Baseline([])
    return Baseline(load(directory))

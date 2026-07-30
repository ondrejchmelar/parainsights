"""Cross-country distance optimisation.

igc2kmz shelled out to an external ``olc2002`` binary for this and read the result
back as GPX. We do it ourselves: the free-distance problem is a small dynamic
program once the track is sampled down, and a self-contained tool beats one that
depends on a decade-old executable being present.

What is computed here is *free distance through up to three turnpoints* — the
open-distance figure XContest shows for a flight that is not a triangle. Our
optimiser is our own, on the FAI sphere, over a sampled track: expect agreement
with XContest's own number to within a few tenths of a percent, not exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import geo

MAX_SAMPLES = 400


@dataclass
class Turnpoint:
    index: int
    lat: float
    lon: float
    time: str | None = None


@dataclass
class Route:
    """An optimised route: the legs between start, turnpoints and finish."""

    kind: str  # "free_3tp"
    distance: float  # metres
    points: list[Turnpoint]
    legs: list[float]  # metres, one per leg
    closed: bool = False

    @property
    def km(self) -> float:
        return self.distance / 1000.0


def _sample(lat: np.ndarray, lon: np.ndarray, limit: int = MAX_SAMPLES) -> np.ndarray:
    """Indices of a shape-preserving subsample of the track.

    Uniform sampling by *index* would put most points in the thermals, where the
    glider is not going anywhere; sampling by distance flown spreads them along
    the course line where the optimum actually lives. The endpoints are always
    kept — the optimum frequently sits on one of them.
    """
    if len(lat) <= limit:
        return np.arange(len(lat))
    s = geo.cumulative_distance(lat, lon)
    targets = np.linspace(0, s[-1], limit)
    indices = np.unique(np.searchsorted(s, targets).clip(0, len(lat) - 1))
    return np.unique(np.concatenate(([0], indices, [len(lat) - 1])))


def optimise(lat: np.ndarray, lon: np.ndarray, *, turnpoints: int = 3,
             times: list[str] | None = None) -> Route:
    """Maximise the distance through ``turnpoints`` intermediate points, in order."""
    sample = _sample(lat, lon)
    slat, slon = lat[sample], lon[sample]
    n = len(sample)
    legs = turnpoints + 1

    # Full pairwise distance matrix on the sampled track: n is bounded by
    # MAX_SAMPLES, so this is a few hundred kilobytes.
    matrix = geo.distance(slat[:, None], slon[:, None], slat[None, :], slon[None, :])
    matrix = np.triu(matrix)  # legs must run forwards in time

    # best[j] = best total distance of the legs so far, finishing at j.
    best = np.zeros(n)
    came_from = np.zeros((legs, n), dtype=int)
    for leg in range(legs):
        candidates = best[:, None] + matrix  # (from, to)
        # A leg cannot end at or before where the previous one ended.
        candidates[np.tril_indices(n)] = -np.inf
        came_from[leg] = np.argmax(candidates, axis=0)
        best = candidates[came_from[leg], np.arange(n)]
        best[np.isneginf(best)] = 0.0

    end = int(np.argmax(best))
    total = float(best[end])

    # Walk the choices back to recover the turnpoints.
    chain = [end]
    for leg in range(legs - 1, -1, -1):
        chain.append(int(came_from[leg][chain[-1]]))
    chain.reverse()

    points = [
        Turnpoint(
            index=int(sample[i]),
            lat=float(lat[sample[i]]),
            lon=float(lon[sample[i]]),
            time=times[int(sample[i])] if times else None,
        )
        for i in chain
    ]
    leg_distances = [
        float(geo.distance(a.lat, a.lon, b.lat, b.lon)) for a, b in zip(points, points[1:])
    ]
    closing = float(geo.distance(points[0].lat, points[0].lon, points[-1].lat, points[-1].lon))

    return Route(
        kind=f"free_{turnpoints}tp",
        distance=total,
        points=points,
        legs=leg_distances,
        # XContest treats a flight as a triangle when the gap back to the start is
        # under 20% of the total; below that this is an open-distance flight.
        closed=bool(total > 0 and closing / total < 0.2),
    )

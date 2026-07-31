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


# Every side of an FAI triangle is at least 28% of the perimeter. There is no third
# category: a closed course that fails the test is a flat triangle, which is what XContest
# scores it as even when its three turnpoints are nearly in a line.
FAI_MIN_SIDE = 0.28
MAX_CLOSING = 0.20     # the gap back to the start, as a fraction of the perimeter
# XContest's category multipliers. They are why a *shorter* triangle can score higher, and
# why matching XContest means maximising the product rather than the distance.
MULTIPLIER = {"open": 1.0, "flat": 1.2, "fai": 1.4}
TRIANGLE_SAMPLES = 260


def classify(sides) -> str:
    """`fai` or `flat` for a triangle's three sides; `open` if they are not a triangle.

    FAI requires every side to be at least 28% of the perimeter. There is deliberately no
    degeneracy test: a triangle flattened onto a line has a + b = c, so its shortest side
    can still be a quarter of the perimeter, and XContest scores a closed there-and-back as
    a flat triangle anyway.
    """
    sides = list(sides)
    perimeter = sum(sides)
    if len(sides) != 3 or perimeter <= 0:
        return "open"
    return "fai" if min(sides) / perimeter >= FAI_MIN_SIDE else "flat"


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

    @property
    def sides(self) -> list[float]:
        """The three sides of the triangle, when the route has three turnpoints.

        Not the same as `legs`: those run start → tp1 → tp2 → tp3 → finish, five points
        and four legs. The triangle is the closed figure tp1-tp2-tp3, and its shortest
        side is what decides FAI.
        """
        if len(self.points) < 5:
            return []
        corners = self.points[1:4]
        return [
            float(geo.distance(a.lat, a.lon, b.lat, b.lon))
            for a, b in zip(corners, corners[1:] + corners[:1])
        ]

    @property
    def shape(self) -> str:
        """`fai`, `flat` or `open` — XContest's three categories and nothing else.

        Only a route that came out of `triangle()` can claim a triangle category. The
        open-distance optimum frequently *does* close, but its distance is the four-leg
        path from start to finish, not a perimeter, so crediting it a triangle multiplier
        compares two different quantities — and it beat the real triangle every time.
        """
        if self.kind in ("fai_triangle", "flat_triangle"):
            return classify(self.sides)
        return "open"


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


def score(route: Route) -> float:
    """Kilometres times XContest's category multiplier — what it actually ranks by."""
    return route.km * MULTIPLIER.get(route.shape, 1.0)


def _closing_matrix(matrix: np.ndarray) -> np.ndarray:
    """`closing[i, k]` = the shortest gap between any sample at or before *i* and any at or
    after *k*.

    A triangle does not have to start where the flight did: the loop may be flown in the
    middle of a longer flight, and the closing distance is measured between the point where
    the pilot entered the loop and the point where they left it. Computed once by dynamic
    programming rather than searched per triple.
    """
    n = len(matrix)
    closing = matrix.copy()
    for i in range(1, n):                       # allow the entry to be earlier
        np.minimum(closing[i], closing[i - 1], out=closing[i])
    for k in range(n - 2, -1, -1):              # allow the exit to be later
        np.minimum(closing[:, k], closing[:, k + 1], out=closing[:, k])
    return closing


def triangle(lat: np.ndarray, lon: np.ndarray, *, times: list[str] | None = None,
             samples: int = TRIANGLE_SAMPLES) -> Route | None:
    """The best-scoring closed triangle, by XContest's rules.

    Maximises perimeter × category multiplier, not perimeter: an FAI triangle is worth 1.4
    against a flat one's 1.2, so a *shorter* triangle regularly scores higher and is the one
    XContest reports. Searching for distance alone gave 53.5 km flat on a flight XContest
    scores as 48.63 km FAI.
    """
    sample = _sample(lat, lon, samples)
    slat, slon = lat[sample], lon[sample]
    n = len(sample)
    if n < 3:
        return None
    matrix = geo.distance(slat[:, None], slon[:, None], slat[None, :], slon[None, :])
    closing = _closing_matrix(matrix)

    best_score, best = 0.0, None
    for i in range(n - 2):
        for j in range(i + 1, n - 1):
            side_a = matrix[i, j]
            side_b = matrix[j, j + 1:]
            side_c = matrix[j + 1:, i]
            perimeter = side_a + side_b + side_c
            open_enough = closing[i, j + 1:] <= MAX_CLOSING * perimeter
            shortest = np.minimum(np.minimum(side_a, side_b), side_c)
            is_fai = shortest >= FAI_MIN_SIDE * perimeter
            score = perimeter * np.where(is_fai, MULTIPLIER["fai"], MULTIPLIER["flat"])
            score = np.where(open_enough, score, 0.0)
            k = int(np.argmax(score))
            if score[k] > best_score:
                best_score = float(score[k])
                best = (i, j, j + 1 + k, float(perimeter[k]), bool(is_fai[k]))
    if best is None:
        return None

    i, j, k, perimeter, fai = best
    # Refine on the full-resolution track. The coarse search puts each corner within half a
    # sample spacing of the true one, which costs a consistent ~0.6% against XContest;
    # sliding each corner over the real fixes in that window recovers most of it.
    spacing = max(len(lat) // max(n, 1), 1)
    picks = [int(sample[i]), int(sample[j]), int(sample[k])]
    for _ in range(3):
        moved = False
        for slot in range(3):
            low = max(picks[slot] - spacing, 0 if slot == 0 else picks[slot - 1] + 1)
            high = min(picks[slot] + spacing,
                       len(lat) - 1 if slot == 2 else picks[slot + 1] - 1)
            if high <= low:
                continue
            window = np.arange(low, high + 1)
            others = [picks[(slot + 1) % 3], picks[(slot + 2) % 3]]
            side_1 = geo.distance(lat[window], lon[window], lat[others[0]], lon[others[0]])
            side_2 = geo.distance(lat[window], lon[window], lat[others[1]], lon[others[1]])
            side_3 = geo.distance(lat[others[0]], lon[others[0]],
                                  lat[others[1]], lon[others[1]])
            candidate = side_1 + side_2 + side_3
            shortest = np.minimum(np.minimum(side_1, side_2), side_3)
            # Keep the category the coarse search chose: sliding a corner until an FAI
            # triangle becomes a longer flat one would score lower, not higher.
            allowed = (shortest >= FAI_MIN_SIDE * candidate) if fai else np.ones_like(
                candidate, dtype=bool)
            candidate = np.where(allowed, candidate, 0.0)
            spot = int(np.argmax(candidate))
            if candidate[spot] > perimeter + 1.0:
                perimeter = float(candidate[spot])
                picks[slot] = int(window[spot])
                moved = True
        if not moved:
            break

    corners = [
        Turnpoint(
            index=c,
            lat=float(lat[c]),
            lon=float(lon[c]),
            time=times[c] if times else None,
        )
        for c in picks
    ]
    sides = [
        float(geo.distance(a.lat, a.lon, b.lat, b.lon))
        for a, b in zip(corners, corners[1:] + corners[:1])
    ]
    return Route(
        kind="fai_triangle" if fai else "flat_triangle",
        distance=perimeter,
        # Start and finish repeat the first corner: a triangle is a closed figure, and
        # `points` is what the plan view draws.
        points=[corners[0]] + corners + [corners[0]],
        legs=sides,
        closed=True,
    )

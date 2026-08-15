"""Measure `debrief.THRESHOLDS` against a directory of real tracklogs.

`docs/analysis-plan.md` states the rule this exists to enforce: *"A metric that fires on
most flights is not a finding, it is a constant. Thresholds come from the distribution
over the archive, not from a round number that sounds right."* That is a claim about a
distribution, so it needs the distribution, and until this module existed the numbers in
`THRESHOLDS` were seeded from three flights and marked provisional.

    uv run python -m tracklog_viewer.calibrate ~/Downloads

prints two tables. **How often each finding fires**, which is the rule above — anything
much over a third is a constant wearing a finding's clothes. And **the distribution of
each quantity a threshold is set against**, with the percentile the current threshold
sits at, which is what says where to move it to.

Three things it deliberately does not do. It touches **no network**, so the two findings
that need a DEM or a sounding (`low_clearance`, `ceiling_used`) are listed as
uncalibrated rather than measured against data that is not there. It reads tracklogs and
writes nothing — the archive of *summaries* is `baseline.py`'s job and a different
question ("how does this flight compare to my others" rather than "does this rule fire
too often"). And it does not edit `THRESHOLDS`: a threshold is a decision with a reason,
and the reason belongs in the comment beside it.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import debrief, igc, metrics
from .analysis import Analysis, analyse

# Every finding that can be judged from a tracklog alone, and the builder behind it.
# `low-point`, `ceiling-used`, `near-close` and the two plan findings are absent on
# purpose: each needs an input this reads nothing of, and a firing rate of 0% measured
# by never supplying the data would be a lie in the shape of a number.
OFFLINE_FINDINGS = (
    "best-climb-left",
    "expensive-gap",
    "climb-selection",
    "centring",
    "working-band",
    "other-slice",
)

# What each calibrated threshold is a percentile *of*, and which way the gate points.
# `above` means the finding fires when the measurement is above the threshold.
QUANTITIES = {
    "weak_climb_share": ("weak_climb_share", "above"),
    "gap_over_median": ("gap_over_median", "above"),
    "centring_ratio": ("centring_ratio", "below"),
    "best_climb_left_metres": ("best_under", "above"),
    "other_lossy_share": ("other_lossy_share", "above"),
    "band_share": ("band_share", "below"),
}

UNCALIBRATED = {
    "low_clearance": "needs a DEM per flight",
    "ground_margin": "needs a DEM per flight",
    "ceiling_used": "needs a sounding per flight, and ERA5 is surface-only past 60 days",
    "near_close": "needs a scored triangle, and only near-closures are in it at all",
}


@dataclass
class Measured:
    """One flight, reduced to what a threshold is judged against."""

    name: str
    values: dict
    fired: set


def measure(analysis: Analysis) -> Measured:
    """The quantities every calibrated threshold is compared with, for one flight."""
    values: dict[str, float] = {}

    gaps = metrics.climb_gaps(analysis)
    if gaps is not None and gaps.median:
        values["gap_over_median"] = gaps.longest / gaps.median

    selection = metrics.climb_selection(analysis)
    if selection is not None:
        values["weak_climb_share"] = selection.fraction

    index = metrics.centring(analysis)
    if index is not None:
        values["centring_ratio"] = index.ratio

    band = metrics.working_band(analysis)
    if band is not None and sum(band.seconds):
        values["band_share"] = min(band.seconds) / sum(band.seconds)

    slice_ = analysis.other
    if slice_ is not None:
        lossy = slice_.straight_sink + slice_.scratching
        values["other_lossy_share"] = lossy / max(analysis.summary.duration, 1)

    thermals = sorted(analysis.thermals, key=lambda s: s.start)
    if len(thermals) >= 3:
        best = max(thermals, key=lambda s: s.average_climb)
        if best.average_climb > 0:
            ceiling = max(s.finish_altitude for s in thermals)
            values["best_under"] = ceiling - best.finish_altitude

    # What the builders actually produce, *before* the `cards` cut — a finding pushed off
    # a crowded list is still a finding that fired, and hiding it behind the cut would
    # make a too-loud threshold look well behaved.
    result = debrief.build(analysis, limit=len(OFFLINE_FINDINGS))
    fired = {finding.id for finding in result.findings}
    return Measured(name=analysis.summary.date, values=values, fired=fired)


def _percentile_of(values: list[float], threshold: float) -> float | None:
    """Where `threshold` sits in `values`, 0..1 — the fraction at or below it."""
    if not values:
        return None
    return sum(1 for value in values if value <= threshold) / len(values)


def report(measured: list[Measured], out=sys.stdout) -> None:
    flights = len(measured)
    if not flights:
        print("no flights read", file=out)
        return

    print(f"{flights} flights\n", file=out)
    print("how often each finding fires "
          "(over a third is a constant, not a finding)", file=out)
    for finding in OFFLINE_FINDINGS:
        hits = sum(1 for flight in measured if finding in flight.fired)
        share = hits / flights
        flag = "  <-- fires on most flights" if share > 0.34 else ""
        print(f"  {finding:20s} {hits:3d}  {share:4.0%}{flag}", file=out)

    print("\nthe distribution behind each calibrated threshold", file=out)
    for name, (quantity, sense) in QUANTITIES.items():
        values = sorted(
            flight.values[quantity] for flight in measured if quantity in flight.values
        )
        threshold = debrief.THRESHOLDS[name]
        if not values:
            print(f"  {name:24s} no flight produced {quantity}", file=out)
            continue
        at = _percentile_of(values, threshold)
        # A gate that fires *below* its threshold catches the low tail, so the share of
        # the archive it fires on is the percentile itself; one that fires above catches
        # what is left.
        share = at if sense == "below" else 1 - at
        print(
            f"  {name:24s} {threshold:8.2f} at p{at * 100:2.0f} -> {share:4.0%} of "
            f"flights   (n={len(values):2d} "
            f"med {np.median(values):7.2f} p67 {np.percentile(values, 67):7.2f} "
            f"max {values[-1]:7.2f})",
            file=out,
        )

    print("\nnot calibrated here", file=out)
    for name, why in UNCALIBRATED.items():
        print(f"  {name:24s} {debrief.THRESHOLDS[name]:8.2f}  {why}", file=out)


def read(directory: Path, out=sys.stdout) -> list[Measured]:
    """Every IGC in `directory`, measured. A file that will not parse is skipped.

    **IGC only, and that is not laziness.** A KMZ from a scoring site is reduced to
    about 500 points, and everything measured along the track comes out low — 476 km
    against 623 km flown on one of these very files, turn counts unavailable entirely.
    Half of these thresholds are ratios over exactly those quantities, so mixing
    decimated files into the distribution moves the percentiles by an artefact of the
    export format rather than by anything a pilot did.
    """
    paths = sorted(
        path for path in directory.iterdir() if path.suffix.lower() == ".igc"
    )
    measured = []
    for path in paths:
        try:
            measured.append(measure(analyse(igc.parse(path))))
        except Exception as error:                      # noqa: BLE001
            # One unreadable file in an archive of sixty is not a reason to produce no
            # numbers at all; it is a reason to name it and go on.
            print(f"  skipped {path.name}: {type(error).__name__}: {error}",
                  file=sys.stderr)
    return measured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tracklog_viewer.calibrate",
        description="Measure debrief.THRESHOLDS against a directory of tracklogs.",
    )
    parser.add_argument("directory", type=Path, help="a directory of IGC files")
    args = parser.parse_args(argv)
    if not args.directory.is_dir():
        parser.error(f"{args.directory} is not a directory")
    report(read(args.directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

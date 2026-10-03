"""The JavaScript analysis against the Python one, field for field, on real tracklogs.

    uv run python -m tracklog_viewer.js_parity ~/Downloads            # every IGC there
    uv run python -m tracklog_viewer.js_parity a.igc b.igc --show 20  # more detail

The page is moving to one analysis written in JavaScript (`tracklog_viewer/js/`), so a
track the reader uploads gets everything a bundled flight gets. Until the Python is
retired it is the reference, and this is the check: both run over the same files and
every number in `Analysis.to_dict()` is compared. Numbers agree within 1e-9 relative;
strings, booleans, nulls and the shape must be identical.

Python's timezonefinder answer is handed to the JavaScript (`positionZone`), so a file
whose timezone only its take-off coordinates can give is compared on the analysis, not
on that one known gap.

Prints one line per file and a total, and exits non-zero on any difference — a
regression check, not a report. The tracklogs stay out of the repository, which is why
this reads a directory you point it at.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import subprocess
import sys
from pathlib import Path

import types

from . import debrief, igc, metrics, xc
from .analysis import analyse

RUNNER = Path(__file__).parent / "js" / "parity_runner.js"
TOLERANCE = 1e-9


def _plain(value):
    """`to_dict()` as JSON would carry it: tuples become lists, numpy scalars floats."""
    return json.loads(json.dumps(value, default=float))


def differences(py, js, where: str = "") -> list[str]:
    """Every place the two disagree, as `path: python != javascript` lines."""
    out: list[str] = []
    if isinstance(py, bool) or isinstance(js, bool) or py is None or js is None:
        if py != js or type(py) is not type(js):
            out.append(f"{where}: {py!r} != {js!r}")
    elif isinstance(py, (int, float)) and isinstance(js, (int, float)):
        if math.isnan(py) and math.isnan(js):
            return out
        scale = max(1.0, abs(py), abs(js))
        if abs(py - js) > TOLERANCE * scale:
            out.append(f"{where}: {py!r} != {js!r}")
    elif isinstance(py, dict) and isinstance(js, dict):
        for key in sorted(set(py) | set(js)):
            if key not in py or key not in js:
                out.append(f"{where}.{key}: only in {'python' if key in py else 'javascript'}")
            else:
                out.extend(differences(py[key], js[key], f"{where}.{key}"))
    elif isinstance(py, list) and isinstance(js, list):
        if len(py) != len(js):
            out.append(f"{where}: {len(py)} items != {len(js)} items")
        for i, (a, b) in enumerate(zip(py, js)):
            out.extend(differences(a, b, f"{where}[{i}]"))
    elif py != js:
        out.append(f"{where}: {py!r} != {js!r}")
    return out


def _best_route(flight):
    """The route `cli.py` reports: the triangle when it outscores the open distance."""
    clock = [flight.local_time(i).strftime("%H:%M:%S") for i in range(len(flight))]
    free = xc.optimise(flight.lat, flight.lon, times=clock)
    closed = xc.triangle(flight.lat, flight.lon, times=clock)
    return closed if closed is not None and xc.score(closed) > free.km else free


def _asdict(value):
    return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else value


def _expected(flight) -> dict:
    """Everything the JS side reports, computed the Python way.

    The terrain and weather findings get a synthetic ground (60 m under the flight's
    lowest point) and a cloudbase (400 m over its highest), identical on both sides: the
    harness has no network, and what is compared is the rule, not the inputs.
    """
    analysis = analyse(flight)
    route = _best_route(flight)
    alt = analysis.series.alt
    clearance = alt - (alt.min() - 60)
    weather = types.SimpleNamespace(cloudbase=analysis.summary.max_altitude + 400)
    return {
        **analysis.to_dict(),
        "route": {**dataclasses.asdict(route), "shape": route.shape, "score": xc.score(route)},
        "metrics": {name: _asdict(value) for name, value in {
            "straight_air": metrics.straight_air(analysis),
            "cross_country_speed": metrics.cross_country_speed(analysis, route),
            "glide_ratio_median": metrics.glide_ratio_median(analysis),
            "climb_selection": metrics.climb_selection(analysis),
            "working_band": metrics.working_band(analysis),
            "centring": metrics.centring(analysis),
            "climb_gaps": metrics.climb_gaps(analysis),
            "concentration": metrics.concentration(analysis),
            "day_envelope": metrics.day_envelope(analysis),
            "detour": metrics.detour(analysis, route),
            "lowest_save": metrics.lowest_save(analysis, clearance),
            "ceiling_use": metrics.ceiling_use(analysis, weather),
            "airborne_window": metrics.airborne_window(clearance),
        }.items()},
        "debrief": debrief.build(analysis, route=route).to_dict(),
        "debrief_full": debrief.build(analysis, route=route, weather=weather,
                                      clearance=clearance).to_dict(),
    }


def _zone_from_position(flight) -> str | None:
    source = flight.timezone_source or ""
    return source[len("position ("):-1] if source.startswith("position (") else None


def compare(paths: list[Path]) -> list[tuple[Path, list[str] | str]]:
    jobs, expected = [], []
    for path in paths:
        flight = igc.parse(path)
        expected.append(_plain(_expected(flight)))
        jobs.append({"path": str(path), "positionZone": _zone_from_position(flight)})
    run = subprocess.run(["node", str(RUNNER)], input=json.dumps(jobs),
                         capture_output=True, text=True, check=True)
    results = json.loads(run.stdout)
    out = []
    for path, want, got in zip(paths, expected, results):
        out.append((path, differences(want, got["result"]) if got["ok"] else got["error"]))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("inputs", nargs="+", type=Path, help="IGC files, or directories of them")
    parser.add_argument("--show", type=int, default=5, help="differences to print per file")
    args = parser.parse_args(argv)
    paths: list[Path] = []
    for item in args.inputs:
        paths += sorted(p for p in item.iterdir() if p.suffix.lower() == ".igc") if item.is_dir() else [item]

    failed = 0
    for path, result in compare(paths):
        if isinstance(result, str):
            failed += 1
            print(f"ERROR {path.name}: {result.splitlines()[0]}")
        elif result:
            failed += 1
            print(f"DIFF  {path.name}: {len(result)} differences")
            for line in result[: args.show]:
                print(f"        {line}")
        else:
            print(f"ok    {path.name}")
    print(f"{len(paths) - failed} of {len(paths)} identical")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

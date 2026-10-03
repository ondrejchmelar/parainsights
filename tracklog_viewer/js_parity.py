"""The JavaScript analysis against the Python one, field for field, on real tracklogs.

    uv run python -m tracklog_viewer.js_parity ~/Downloads            # every IGC, KML, KMZ
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
import datetime as dt
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import types

import numpy as np

from . import airmass, debrief, igc, insolation, kml, metrics, plan as plan_module, view3d, xc
from .terrain import Terrain, clearance as terrain_clearance
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
        "plan": _plan(analysis, route),
        "sun": view3d._sun(analysis),
        **{key: _airmass(analysis, model) for key, model in (
            ("airmass", None),
            ("airmass_model", types.SimpleNamespace(wind_at=lambda altitude: (5.0, 270.0))),
        )},
    }


def _plan(analysis, route) -> dict | None:
    """The task in the tracklog's own C records, judged both ways."""
    found = plan_module.from_flight(analysis.flight)
    if found is None:
        return None
    return {
        "plan": found.to_dict(), "describes": plan_module.describes(analysis, found),
        "adherence": _asdict(plan_module.adherence(analysis, found)),
        "turnpoints": _asdict(plan_module.turnpoints(analysis, found)),
        "budget": _asdict(plan_module.budget(analysis, found, route)),
        "debrief": debrief.build(analysis, route=route, flight_plan=found).to_dict(),
    }


def _airmass(analysis, weather) -> dict:
    wind = airmass.field(analysis, weather=weather)
    return {"field": dataclasses.asdict(wind),
            "glide": _asdict(airmass.glide_performance(analysis, wind)),
            "wander": _asdict(airmass.circle_wander(analysis, wind)),
            "polar": _asdict(airmass.polar(analysis, wind))}


def synthetic_terrain(flight) -> Terrain:
    """Ridges over the flight's box, steep enough for the ridge rule to have something to
    find, and in whole decimetres so both sides read the same numbers from the JSON."""
    west, east = float(flight.lon.min()) - 0.03, float(flight.lon.max()) + 0.03
    south, north = float(flight.lat.min()) - 0.03, float(flight.lat.max()) + 0.03
    rows, cols = 90, 110
    lat = np.linspace(north, south, rows)[:, None]
    lon = np.linspace(west, east, cols)[None, :]
    base = float(np.min(flight.alt_gps if np.any(flight.alt_gps) else flight.alt_baro)) - 250
    z = base + 380 * np.sin(lat * 230.0) * np.cos(lon * 170.0) + 60 * np.sin(lon * 900.0)
    return Terrain(west, east, south, north, np.round(z, 1))


def _grid(t: Terrain) -> dict:
    return {"west": t.west, "east": t.east, "south": t.south, "north": t.north,
            "rows": t.rows, "cols": t.cols, "z": t.elevations.ravel().tolist()}


def _insolation(analysis, t: Terrain) -> dict:
    agl = terrain_clearance(t, analysis)
    return {
        "clearance": agl[::37].tolist(),
        "triggers": [dataclasses.asdict(x) for x in insolation.triggers(analysis, t)],
        "sources": {str(k): dataclasses.asdict(v) for k, v in insolation.sources(analysis, t).items()},
        "windward": _asdict(insolation.windward(analysis, t)),
    }


def _zone_from_position(flight) -> str | None:
    source = flight.timezone_source or ""
    return source[len("position ("):-1] if source.startswith("position (") else None


def _parse(path: Path):
    return kml.parse(path) if path.suffix.lower() in (".kml", ".kmz") else igc.parse(path)


def compare(paths: list[Path], *, terrain=synthetic_terrain) -> list[tuple[Path, list[str] | str]]:
    """`terrain(flight)` makes the ground both sides are given; a test can shape it."""
    jobs, expected = [], []
    for path in paths:
        try:
            flight = _parse(path)
        except ValueError as error:
            # A file the Python refuses has to be refused by the JS too, and that agreement
            # is a result rather than an error in the harness.
            expected.append({"refused": str(error)})
            jobs.append({"path": str(path), "positionZone": None, "terrain": None})
            continue
        ground = terrain(flight)
        want = _expected(flight)
        want["parsed"] = {"fixes": len(flight), "warnings": flight.warnings,
                          "dropped": dict(flight.dropped), "logger_type": flight.headers.logger_type,
                          "timezone_source": flight.timezone_source}
        want["insolation"] = _insolation(analyse(flight), ground)
        expected.append(_plain(want))
        jobs.append({"path": str(path), "positionZone": _zone_from_position(flight),
                     "terrain": _grid(ground)})
    run = subprocess.run(["node", str(RUNNER)], input=json.dumps(jobs),
                         capture_output=True, text=True, check=True)
    results = json.loads(run.stdout)
    out = []
    for path, want, got in zip(paths, expected, results):
        if "refused" in want:
            out.append((path, [] if not got["ok"] else
                        [f"python refused it ({want['refused']}) and javascript did not"]))
        else:
            out.append((path, differences(want, got["result"]) if got["ok"] else got["error"]))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("inputs", nargs="+", type=Path, help="IGC files, or directories of them")
    parser.add_argument("--show", type=int, default=5, help="differences to print per file")
    parser.add_argument("--report", action="store_true",
                        help="compare the rendered article instead of the analysis")
    args = parser.parse_args(argv)
    paths: list[Path] = []
    for item in args.inputs:
        paths += sorted(p for p in item.iterdir()
                        if p.suffix.lower() in (".igc", ".kml", ".kmz")) if item.is_dir() else [item]

    failed = 0
    for path, result in (compare_reports(paths) if args.report else compare(paths)):
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



# ---------------------------------------------------------------------------------------
# The article: `render_html._flight_body` against `js/report.js`.
# ---------------------------------------------------------------------------------------

REPORT_RUNNER = Path(__file__).parent / "js" / "report_runner.js"
_JSON_SCRIPT = re.compile(r'<script type="application/json" class="([^"]+)">(.*?)</script>', re.S)


def normalise_html(html: str) -> tuple[str, list]:
    """Markup with comments dropped and whitespace collapsed, and the JSON payloads lifted
    out to be compared as values: Python writes 1.0 where JavaScript writes 1."""
    payloads = [(name, json.loads(body)) for name, body in _JSON_SCRIPT.findall(html)]
    html = _JSON_SCRIPT.sub(lambda m: f'<script class="{m.group(1)}"></script>', html)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"\s+", " ", html)
    html = re.sub(r">\s+<", "><", html)
    return html.strip(), payloads


def _first_difference(a: str, b: str, context: int = 90) -> str:
    at = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return f"python  …{a[max(at - context, 0):at + context]}…\n        javascript …{b[max(at - context, 0):at + context]}…"


def compare_reports(paths: list[Path]) -> list[tuple[Path, list[str] | str]]:
    """Each flight's article both ways, with the inputs a published report has: the route,
    the synthetic ground, the glider table, and the day's weather where the cache holds
    it. No network: a weather fetch the cache cannot answer fails, as on a train."""
    import time

    from . import certification, meteo as meteo_module, render_html

    captured = {}

    def offline(*_args, **_kwargs):
        raise OSError("parity harness: no network")

    real_parse = meteo_module._parse

    def capture(payload, when):
        captured["payload"], captured["when"] = payload, when
        return real_parse(payload, when)

    meteo_module._request, meteo_module._parse = offline, capture
    table = certification.compact()
    now = time.time()
    jobs, expected = [], []
    for path in paths:
        flight = _parse(path)
        analysis = analyse(flight)
        route = _best_route(flight)
        ground = synthetic_terrain(flight)
        captured.clear()
        weather = meteo_module.for_flight(analysis)
        found = plan_module.for_flight(analysis)
        html = render_html._flight_body(analysis, meteo=weather, route=route, terrain=ground,
                                        uid="f0", flight_plan=found)
        expected.append(normalise_html(html))
        jobs.append({"path": str(path), "positionZone": _zone_from_position(flight),
                     "terrain": _grid(ground), "sceneTerrain": ground.to_remote(),
                     "meteo": captured.get("payload") if weather is not None else None,
                     "when": captured["when"].replace(tzinfo=dt.timezone.utc).timestamp()
                     if weather is not None else None,
                     "now": now})
    stdin = json.dumps({"jobs": jobs, "certification": table})
    run = subprocess.run(["node", str(REPORT_RUNNER)], input=stdin, capture_output=True,
                         text=True, check=True)
    out = []
    for path, (want_html, want_json), got in zip(paths, expected, json.loads(run.stdout)):
        if not got["ok"]:
            out.append((path, got["error"]))
            continue
        got_html, got_json = normalise_html(got["html"])
        problems = []
        if want_html != got_html:
            problems.append("markup differs:\n        " + _first_difference(want_html, got_html))
        if [n for n, _ in want_json] != [n for n, _ in got_json]:
            problems.append(f"payloads differ: {[n for n, _ in want_json]} != {[n for n, _ in got_json]}")
        for (name, a), (_, b) in zip(want_json, got_json):
            problems += [f"{name}{line}" for line in differences(a, b)]
        out.append((path, problems))
    return out


if __name__ == "__main__":
    sys.exit(main())

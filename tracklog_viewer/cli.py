"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from . import (
    basemap as basemap_module,
    kml,
    meteo as meteo_module,
    render_html,
    render_kmz,
    render_map,
    sources,
    terrain as terrain_module,
    xc,
)
from .analysis import analyse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parainsights", description="Analyse a paragliding IGC tracklog."
    )
    parser.add_argument(
        "flight", nargs="+",
        help="flights to analyse: .igc, .kmz or .kml files, or URLs to such files. "
             "Several inputs produce one report with a flight picker.",
    )
    parser.add_argument("--html", type=Path, metavar="FILE", help="write an HTML report")
    parser.add_argument(
        "--kmz", type=Path, metavar="FILE", help="write a KMZ for Google Earth",
    )
    parser.add_argument(
        "--map", type=Path, metavar="FILE", dest="map_file",
        help="write an interactive 3D map (needs network when opened, so not embeddable)",
    )
    parser.add_argument("--json", type=Path, metavar="FILE", help="write the analysis as JSON")
    parser.add_argument(
        "--window", type=float, default=None, metavar="SECONDS",
        help="averaging window for climb and progress (default 20)",
    )
    parser.add_argument(
        "--meteo", action="store_true",
        help="fetch the day's weather profile (the only feature that uses the network)",
    )
    parser.add_argument(
        "--no-xc", action="store_true", help="skip free-distance optimisation",
    )
    parser.add_argument(
        "--no-basemap", action="store_true",
        help="with --terrain, skip the OpenStreetMap basemap image",
    )
    parser.add_argument(
        "--terrain", action="store_true",
        help="fetch DEM tiles and embed a 3D terrain view in the report (uses the network)",
    )
    args = parser.parse_args(argv)

    try:
        reports = [_one(path, args) for path in args.flight]
    except (sources.SourceError, kml.NoTrackError) as error:
        # These are the user's problem to fix, not a bug: say what is wrong and stop,
        # without a traceback.
        print(f"tracklog-viewer: {error}", file=sys.stderr)
        return 2

    if args.json:
        payload = (
            reports[0]["payload"] if len(reports) == 1 else [r["payload"] for r in reports]
        )
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    if args.html:
        if len(reports) == 1:
            render_html.write(
                reports[0]["analysis"], args.html,
                meteo=reports[0]["meteo"], route=reports[0]["route"],
                terrain=reports[0]["terrain"], basemap=reports[0]["basemap"],
            )
        else:
            render_html.write_multi(reports, args.html)
        print(f"wrote {args.html}")
    if args.kmz:
        render_kmz.write(
            reports[0]["analysis"], args.kmz,
            route=reports[0]["route"], meteo=reports[0]["meteo"],
        )
        print(f"wrote {args.kmz}")
        if len(reports) > 1:
            print("note: the KMZ covers the first flight only", file=sys.stderr)
    if args.map_file:
        render_map.write(
            reports[0]["analysis"], args.map_file, route=reports[0]["route"],
        )
        print(f"wrote {args.map_file}")
        if len(reports) > 1:
            print("note: the 3D map covers the first flight only", file=sys.stderr)

    return 0


def shape_of(route, analysis) -> str:
    """A short description of the flight's geometry, for the flight picker.

    Deliberately not "triangle": a closed scored route satisfies XContest's 20%
    closing rule, but calling it a triangle would claim the three-leg geometry and
    FAI leg-ratio rules that we do not check.
    """
    if route is None:
        return ""
    summary = analysis.summary
    if route.closed:
        return "closed course"
    if summary.straight_distance < 0.5 * summary.max_distance_from_takeoff:
        return "out and return"
    return "open distance"


def _one(source: str, args) -> dict:
    """Analyse a single flight and report it on stdout."""
    # A source may be a path or a URL; both reduce to a last path component for display.
    label = Path(urlsplit(str(source)).path or str(source)).name or str(source)
    flight = sources.load(source)
    analysis = analyse(flight, window=args.window)
    summary = analysis.summary

    route = None
    if not args.no_xc:
        route = xc.optimise(
            flight.lat,
            flight.lon,
            times=[flight.local_time(i).strftime("%H:%M:%S") for i in range(len(flight))],
        )

    ground = None
    tiles = None
    if args.terrain:
        # Several flights in one document each carry their own grid, so trim the
        # budget when the report is shared.
        budget = 6000 if len(args.flight) == 1 else 2600
        ground = terrain_module.for_flight(analysis, max_points=budget)
        if ground is None:
            print(f"warning: no terrain data for {label}", file=sys.stderr)
        elif not args.no_basemap:
            # Place names are what make the 3D view navigable.
            tiles = basemap_module.for_terrain(
                ground, max_width=2200 if len(args.flight) == 1 else 1400,
                quality=72 if len(args.flight) == 1 else 62,
            )
            if tiles is None:
                print(f"warning: no basemap tiles for {label}", file=sys.stderr)

    weather = None
    if args.meteo:
        weather = meteo_module.for_flight(analysis)
        if weather is None:
            print(f"warning: no weather data for {label}", file=sys.stderr)

    for warning in flight.warnings[:5]:
        print(f"warning: {warning}", file=sys.stderr)
    for reason, count in flight.dropped.items():
        print(f"note: {count} × {reason}", file=sys.stderr)

    tow = analysis.tow
    print(f"{summary.date}  {summary.site or '—'}  {summary.pilot or '—'}  {summary.glider or '—'}")
    print(
        f"  {summary.takeoff_time}–{summary.landing_time} "
        f"({summary.duration // 3600}h{summary.duration % 3600 // 60:02d})  "
        f"{summary.track_distance / 1000:.1f} km flown, "
        f"{summary.straight_distance / 1000:.1f} km straight"
    )
    if route:
        print(
            f"  XC free distance {route.km:.1f} km via {len(route.points) - 2} turnpoints "
            f"({'closed' if route.closed else 'open'})"
        )
    print(
        f"  altitude {summary.min_altitude:.0f}–{summary.max_altitude:.0f} m "
        f"({summary.altitude_source}), gained {summary.total_gain:.0f} m"
    )
    if tow:
        print(
            f"  tow: {tow.duration} s, {tow.altitude_change:+.0f} m, "
            f"release {tow.finish_altitude:.0f} m"
        )
    turns = [s.turns for s in analysis.thermals if s.turns is not None]
    print(
        f"  {len(analysis.thermals)} thermals, {len(analysis.glides)} glides, "
        + (
            f"{sum(turns):.0f} turns"
            if turns
            else f"turns not resolvable at {summary.sample_interval:.0f} s sampling"
        )
    )
    if analysis.wind:
        print(f"  wind {analysis.wind.kmh:.0f} km/h from {analysis.wind.cardinal}")
    if weather:
        print(
            f"  weather {weather.valid_at}: {weather.surface_temperature:.0f}°C, "
            f"cloudbase ~{weather.cloudbase:.0f} m, "
            f"thermal top ~{weather.thermal_top:.0f} m"
            if weather.thermal_top
            else f"  weather {weather.valid_at}"
        )

    payload = analysis.to_dict()
    payload["file"] = label
    if route:
        payload["xc"] = {
            "kind": route.kind,
            "distance": route.distance,
            "closed": route.closed,
            "legs": route.legs,
            "points": [
                {"index": p.index, "lat": p.lat, "lon": p.lon, "time": p.time}
                for p in route.points
            ],
        }
    if weather:
        payload["meteo"] = weather.to_dict()

    return {
        "analysis": analysis,
        "meteo": weather,
        "route": route,
        "payload": payload,
        "terrain": ground,
        "basemap": tiles if args.terrain and not args.no_basemap else None,
        "shape": shape_of(route, analysis),
        "file": label,
        # Shown in the flight picker: two reports of the same flight from an IGC and
        # a KMZ are otherwise indistinguishable, and they do not say the same thing.
        "format": Path(label).suffix.lstrip(".").upper() or "?",
    }


if __name__ == "__main__":
    raise SystemExit(main())

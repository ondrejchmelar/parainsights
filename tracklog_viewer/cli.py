"""Command line entry point."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from . import (
    baseline,
    basemap as basemap_module,
    kml,
    meteo as meteo_module,
    plan as plan_module,
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
        "--earth-link", action="store_true",
        help="embed the KMZ in the HTML report as a download (adds about 170 KB); "
             "otherwise use --kmz to write one on demand",
    )
    parser.add_argument(
        "--no-basemap", action="store_true",
        help="with --terrain, leave the map imagery out of the report (saves about "
             "550 KB per flight, and the 3D view then shows hillshade only)",
    )
    parser.add_argument(
        "--embed", action="store_true",
        help="bake the imagery into the file instead of fetching it at view time. The "
             "report then needs no network at all, at about 550 KB per flight per style "
             "and at a resolution a stitch can afford. For a viewer behind a policy that "
             "blocks every host — otherwise leave it off.",
    )
    parser.add_argument(
        "--online", action="store_true",
        help=argparse.SUPPRESS,   # now the default; accepted so old commands still run
    )
    parser.add_argument(
        "--label", action="append", default=[], metavar="PILOT|SITE|GLIDER",
        help="override what a flight is credited to, one --label per flight in order. "
             "Empty fields keep what the file says: --label '|Hunza' sets only the site. "
             "For flights whose logger recorded no pilot or launch.",
    )
    parser.add_argument(
        "--terrain", action="store_true",
        help="fetch DEM tiles and embed a 3D terrain view in the report (uses the network)",
    )
    parser.add_argument(
        "--plan", type=Path, metavar="FILE", dest="plan_file",
        help="a flight plan as JSON: turnpoints, a goal distance, planned times. "
             "Auto-discovered as FLIGHT.plan.json beside the tracklog, or from the "
             "remembered plans directory, and read from the tracklog's own C task "
             "records when it has them. A plan without a made_at timestamp is treated "
             "as reconstructed intent and its findings are downgraded.",
    )
    parser.add_argument(
        "--airspace", metavar="HREF", nargs="?", const="",
        help="add an airspace tab to the report, built by the `airspaces` tool. Needs "
             "the network. HREF is where the OpenAir download sits relative to the "
             "report — pass 'airspace/' when the report is at public/index.html and the "
             "file at public/airspace/, or omit it when they are side by side.",
    )
    parser.add_argument(
        "--archive", type=Path, metavar="DIR",
        help="a directory of per-flight summaries (a few KB of JSON each, no track data). "
             "Every flight analysed is added to it, and the report places this one against "
             "the others: 'among your best of 12 flights' rather than a bare number. "
             "Offline, and the first few flights say nothing until there are enough to "
             "rank against.",
    )
    args = parser.parse_args(argv)

    try:
        reports = [_one(path, args, index) for index, path in enumerate(args.flight)]
    except (sources.SourceError, kml.NoTrackError) as error:
        # These are the user's problem to fix, not a bug: say what is wrong and stop,
        # without a traceback.
        print(f"tracklog-viewer: {error}", file=sys.stderr)
        return 2

    # The archive is written *before* the report is rendered, so this flight is in its
    # own baseline. That is correct rather than circular: a percentile of your own flights
    # includes the flight, and excluding it would make "your best" unreachable.
    held = None
    if args.archive:
        for report in reports:
            entry = baseline.summarise(
                report["analysis"], route=report["route"], weather=report["meteo"]
            )
            baseline.save(entry, args.archive)
        held = baseline.build(args.archive)
        print(f"archive: {len(held)} flights in {args.archive}"
              + ("" if held.usable
                 else f" — {baseline.MIN_FLIGHTS} needed before it can rank anything"))

    if args.json:
        payload = (
            reports[0]["payload"] if len(reports) == 1 else [r["payload"] for r in reports]
        )
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    extras = []
    if args.airspace is not None:
        # Imported here, not at module scope: the two tools share a tab strip, not code,
        # and the viewer must keep working with the airspace package absent or offline.
        from airspaces import build as airspace_build
        from airspaces import openair as airspace_openair
        from airspaces import render_html as airspace_html
        from airspaces import sources as airspace_sources

        overlay = airspace_build.build()
        base_text, base_version = airspace_sources.base_airspace()
        name = overlay.filename
        text = airspace_build.to_openair(overlay, base_version=base_version)
        # The download has to exist where the page points, which is `--airspace`'s
        # argument resolved against the report's own directory.
        target = (args.html.parent / args.airspace / name) if args.html else Path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="")
        base = airspace_openair.read(base_text)
        # The same 3D view the flights use, over the same terrain. It needs a network at
        # build time and falls back to the flat SVG map without one — a page that draws
        # no airspace because a tile server was slow would be the wrong trade.
        payload = None
        if args.terrain:
            from airspaces import scene as airspace_scene

            payload = airspace_scene.fetch(
                list(base) + list(overlay.airspaces), online=not args.embed
            )
        extras.append(render_html.Extra(
            uid="airspace",
            label="Airspace",
            meta=f"{overlay.atz_count} zones &middot; {overlay.circuits} okruhy",
            body=airspace_html.body(
                overlay, base, base_version,
                openair_name=name, openair_size=len(text),
                openair_href=f"{args.airspace}{name}",
                scene=payload,
            ),
            style=airspace_html.STYLE,
            script=(airspace_html.SCRIPT
                    + (airspace_html.SCRIPT3D if payload else "")),
        ))
        print(f"wrote {target}")

        # And over each flight's own map, behind a switch. The whole set is 743 airspaces
        # over a country; what belongs on a map of one flight is what that map can draw,
        # so each report gets only the airspace reaching its own terrain box — which for a
        # flight in Pakistan is none, and it then carries no button rather than an empty
        # one.
        from airspaces import scene as airspace_scene

        spaces = list(base) + list(overlay.airspaces)
        for report in reports:
            if report.get("terrain") is None:
                continue
            report["airspace"] = airspace_scene.layer(spaces, report["terrain"])
        counted = sum(len(r.get("airspace", {}).get("airspaces", [])) for r in reports)
        if counted:
            print(f"airspace over {sum(1 for r in reports if r.get('airspace'))} "
                  f"of {len(reports)} flights, {counted} zones in all")

    if args.html:
        if len(reports) == 1:
            render_html.write(
                reports[0]["analysis"], args.html,
                meteo=reports[0]["meteo"], route=reports[0]["route"],
                terrain=reports[0]["terrain"], basemaps=reports[0]["basemaps"],
                fetch_tiles=reports[0]["fetch_tiles"], kmz=reports[0]["kmz"],
                archive=held if args.archive else None,
                flight_plan=reports[0]["plan"],
                airspace=reports[0].get("airspace"), extras=extras,
            )
        else:
            render_html.write_multi(
                reports, args.html,
                archive=held if args.archive else None, extras=extras,
            )
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


SHAPE_NAMES = {
    "fai": "FAI triangle",
    "flat": "flat triangle",
    "open": "open distance",
}


def _annotate(summary, label: str) -> None:
    """Apply a `PILOT|SITE|GLIDER` override, leaving empty fields as the file had them."""
    if not label:
        return
    fields = (label.split("|") + ["", "", ""])[:3]
    for name, value in zip(("pilot", "site", "glider"), fields):
        if value.strip():
            setattr(summary, name, value.strip())


def shape_of(route, analysis) -> str:
    """A short description of the flight's geometry, for the flight picker.

    The names are the ones a pilot uses. `xc.Route.shape` does the work: closure under
    XContest's 20% rule, then the FAI 28% shortest-side test against the triangle's own
    perimeter. Out and return is only offered for a course that did *not* close — a closed
    there-and-back is a flat triangle, which is how it scores.
    """
    if route is None:
        return ""
    shape = route.shape
    if shape == "open":
        summary = analysis.summary
        if summary.straight_distance < 0.5 * summary.max_distance_from_takeoff:
            return "out and return"
    return SHAPE_NAMES.get(shape, "open distance")


def _one(source: str, args, index: int = 0) -> dict:
    """Analyse a single flight and report it on stdout."""
    # A source may be a path or a URL; both reduce to a last path component for display.
    label = Path(urlsplit(str(source)).path or str(source)).name or str(source)
    flight = sources.load(source)
    analysis = analyse(flight, window=args.window)
    summary = analysis.summary
    _annotate(summary, args.label[index] if index < len(args.label) else "")

    route = None
    if not args.no_xc:
        clock = [flight.local_time(i).strftime("%H:%M:%S") for i in range(len(flight))]
        free = xc.optimise(flight.lat, flight.lon, times=clock)
        # XContest scores the *category*, not the raw distance: a triangle is worth 1.2 or
        # 1.4 times its perimeter, so a shorter closed course routinely beats a longer open
        # one. Reporting the open optimum gave 53.5 km on a flight XContest scores 48.63.
        closed = xc.triangle(flight.lat, flight.lon, times=clock)
        route = free
        if closed is not None and xc.score(closed) > free.km:
            route = closed

    ground = None
    tiles = None
    if args.terrain:
        # Several flights in one document each carry their own grid, so trim the
        # budget when the report is shared. 2 600 nodes was 59x43 over an alpine box —
        # every facet of the heightfield visible as a quadrilateral. The drape mesh is
        # capped separately in the renderer, so a finer grid costs bytes, not frames.
        budget = 26000 if len(args.flight) == 1 else 17000
        ground = terrain_module.for_flight(analysis, max_points=budget)
        if ground is None:
            print(f"warning: no terrain data for {label}", file=sys.stderr)
        elif not args.no_basemap and args.embed:
            # Place names are what make the 3D view navigable, and both styles are
            # embedded so the button works in a page that cannot fetch anything. A
            # shared document pays that twice per flight, so it gets smaller, harder
            # compressed images.
            single = len(args.flight) == 1
            # A single-flight report can afford zoom 12 (about 22 m/px); a document with
            # one image per flight per style cannot, and takes zoom 11 at 45 m/px.
            tiles = basemap_module.for_view(
                ground,
                max_tiles=80 if single else 30,
                max_width=2400 if single else 1150,
                quality=55 if single else 45,
            )
            if not tiles:
                print(f"warning: no basemap tiles for {label}", file=sys.stderr)

    # The KMZ is embedded in the report as a download, so the Earth file travels with it.
    earth = None
    # One KMZ per flight would add ~170 KB each; in a shared document only the first
    # flight carries one, and `--kmz` still writes a file for any of them.
    if args.earth_link and (len(args.flight) == 1 or index == 0):
        earth = render_kmz.to_bytes(analysis, route=route)

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
        print(f"  XC {route.km:.2f} km — {shape_of(route, analysis)}")
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
        # Resolved here rather than in main(), because a plan is discovered relative to
        # the tracklog's own path and only this function knows it.
        "plan": plan_module.for_flight(analysis, source, explicit=args.plan_file),
        "payload": payload,
        "terrain": ground,
        "basemaps": tiles if args.terrain and not args.no_basemap else None,
        # Templates for the styles that are not embedded. Suppressed by --no-basemap,
        # which asks for no imagery at all rather than imagery from somewhere else.
        "fetch_tiles": not args.no_basemap,
        "kmz": earth,
        "shape": shape_of(route, analysis),
        "file": label,
        # Shown in the flight picker: two reports of the same flight from an IGC and
        # a KMZ are otherwise indistinguishable, and they do not say the same thing.
        "format": Path(label).suffix.lstrip(".").upper() or "?",
    }


if __name__ == "__main__":
    raise SystemExit(main())

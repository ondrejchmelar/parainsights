"""Command line: build the report page.

The analysis and the article are the JavaScript in `js/` — the same code an uploaded track
goes through in the page. This reads the inputs, fetches what the JavaScript says each
flight needs (the ground, the day's weather), finds a sidecar plan, adds the airspace,
and has the JavaScript write the articles (`js_build`).
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from parainsights_map import terrain as terrain_module

from . import certification, js_build, render_html, sources

# Where a pilot's pre-flight plans are remembered, by date and site, when there is no
# sidecar beside the tracklog.
REMEMBERED_PLANS = Path.home() / ".config" / "parainsights" / "plans"
WEATHER_CACHE = Path.home() / ".cache" / "parainsights" / "meteo"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parainsights", description="Build the flight report page from tracklogs.",
    )
    parser.add_argument(
        "flight", nargs="+",
        help="flights: .igc, .kmz or .kml files, or URLs to such files. Several inputs "
             "produce one page with a flight picker.",
    )
    parser.add_argument("--html", type=Path, metavar="FILE", required=True,
                        help="the page to write")
    parser.add_argument(
        "--terrain", action="store_true",
        help="fetch the ground under each flight: the 3D view, clearance and the "
             "ridge-or-thermal label (uses the network)",
    )
    parser.add_argument(
        "--meteo", action="store_true",
        help="fetch the day's weather profile for each flight (uses the network)",
    )
    parser.add_argument(
        "--label", action="append", default=[], metavar="PILOT|SITE|GLIDER",
        help="override what a flight is credited to, one --label per flight in order. "
             "Empty fields keep what the file says: --label '|Hunza' sets only the site.",
    )
    parser.add_argument(
        "--plan", type=Path, metavar="FILE", dest="plan_file",
        help="a flight plan as JSON (turnpoints, goal distance, planned times) for the "
             "first flight. Otherwise found as FLIGHT.plan.json beside the tracklog or "
             "in the remembered plans directory; a task in the tracklog's own C records "
             "is read by the page itself.",
    )
    parser.add_argument(
        "--airspace", metavar="HREF", nargs="?", const="",
        help="add the Planner view (airspace and task planner) and the airspace over each "
             "flight's map. Needs the network. HREF is where the OpenAir download sits "
             "relative to the page: 'airspace/' when the page is public/index.html.",
    )
    args = parser.parse_args(argv)

    now = time.time()
    try:
        paths = [sources.local_path(source) for source in args.flight]
    except sources.SourceError as error:
        print(f"parainsights: {error}", file=sys.stderr)
        return 2
    names = [Path(urlsplit(str(s)).path or str(s)).name or str(s) for s in args.flight]
    labels = [args.label[i] if i < len(args.label) else "" for i in range(len(paths))]

    try:
        seen = js_build.inspect(
            [{"path": str(p), "name": n, "label": l} for p, n, l in zip(paths, names, labels)],
            now=now)
    except js_build.BuildError as error:
        print(f"parainsights: {error}", file=sys.stderr)
        return 2

    reports = []
    for index, (path, name, found) in enumerate(zip(paths, names, seen)):
        for warning in found["warnings"]:
            print(f"warning: {name}: {warning}", file=sys.stderr)
        for reason, count in (found["dropped"] or {}).items():
            print(f"note: {name}: {count} × {reason}", file=sys.stderr)
        ground = None
        if args.terrain:
            box = found["ground"]
            ground = terrain_module.fetch(box["west"], box["east"], box["south"], box["north"],
                                          cols=box["cols"], max_points=box["rows"] * box["cols"],
                                          report=print)
            if ground is None:
                print(f"warning: no terrain data for {name}", file=sys.stderr)
        weather = _weather(found["meteo"]["url"]) if args.meteo else None
        if args.meteo and weather is None:
            print(f"warning: no weather data for {name}", file=sys.stderr)
        explicit = args.plan_file if index == 0 else None
        reports.append({"path": path, "name": name, "label": labels[index], "ground": ground,
                        "weather": weather, "when": found["meteo"]["when"],
                        "plan": _plan_payload(path, found["date"], found["site"], explicit)})

    extras = []
    if args.airspace is not None:
        extras.append(_planner_view(args, reports))

    jobs = []
    for index, report in enumerate(reports):
        ground = report["ground"]
        jobs.append({
            "path": str(report["path"]), "name": report["name"],
            "terrain": js_build.grid(ground) if ground is not None else None,
            # The page fetches the heights itself, as for every 3D map on this site.
            "sceneTerrain": ground.to_remote() if ground is not None else None,
            "meteo": report["weather"], "when": report["when"],
            "options": {"uid": f"f{index}", "hidden": index > 0, "label": report["label"],
                        # The flight's map loads the airspace under its ground when it is
                        # opened, from the layer files beside the Planner (`openaip.py`).
                        "airspaceRemote": (args.airspace + "layers/")
                                          if args.airspace is not None and ground is not None
                                          else None,
                        "format": Path(report["name"]).suffix.lstrip(".").upper(),
                        "plan": report["plan"]},
        })
    try:
        made = js_build.render(jobs, certification_table=certification.compact(), now=now)
    except js_build.BuildError as error:
        print(f"parainsights: {error}", file=sys.stderr)
        return 2
    for article in made:
        print(f"{article['label']}  {article['meta']}  {article['stat']}")

    tabs = (
        '<nav class="tabs" id="flight-tabs" role="group" aria-label="Choose a flight">'
        + render_html.ADD_TAB
        + "".join(render_html._tab(m["uid"], render_html.escape(m["label"]),
                                   render_html.escape(m["meta"]),
                                   render_html.escape(m["stat"]).replace(" · ", " &middot; "),
                                   on=i == 0)
                  for i, m in enumerate(made))
        + "</nav>"
    )
    page = render_html._page(made[0]["title"], [m["html"] for m in made], tabs, extras)
    if args.airspace is not None:
        # Where an uploaded flight's map finds the airspace layers (`js/upload.js`).
        page = page.replace("<meta charset=\"utf-8\">", "<meta charset=\"utf-8\">\n"
                            f"<meta name=\"airspace-layers\" content=\"{args.airspace}layers/\">", 1)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(page, encoding="utf-8")
    print(f"wrote {args.html}")
    # The glider classes an uploaded track is looked up in, beside the page and fetched
    # only when an upload needs one (`js/upload.js`): 50 KB compressed, not 720 KB.
    gliders = args.html.parent / "gliders.json"
    gliders.write_text(json.dumps(certification.compact(), separators=(",", ":")),
                       encoding="utf-8")
    print(f"wrote {gliders}")
    return 0


def _weather(url: str) -> dict | None:
    """Open-Meteo's answer to the request `js/meteo.js` built, unparsed and cached by URL.
    None on any failure: a report must still build on a train."""
    path = WEATHER_CACHE / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")
    if path.exists():
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    WEATHER_CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return payload


def _plan_payload(track: Path, date: str, site: str | None, explicit: Path | None,
                  *, remembered: Path = REMEMBERED_PLANS) -> dict | None:
    """A plan file for this flight, as JSON for `js/plan.js`: an explicit `--plan`, a
    sidecar beside the tracklog (FLIGHT.plan.json), or one remembered for the date and site,
    in that order. A file that is not a JSON object is skipped, not fatal."""
    candidates = []
    if explicit:
        candidates.append((Path(explicit), "sidecar"))
    for beside in (track.with_suffix(".plan.json"), track.with_name(track.stem + ".plan.json")):
        if beside.is_file():
            candidates.append((beside, "sidecar"))
            break
    if date and remembered.is_dir():
        key = remembered / f"{date}-{(site or 'flight').replace(' ', '-')}.json"
        loose = sorted(remembered.glob(f"{date}*.json"))
        for found in ([key] if key.is_file() else []) + loose[:1]:
            candidates.append((found, "remembered"))
    for path, kind in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            return {"payload": payload, "source": kind}
    return None


def _planner_view(args, reports) -> "render_html.Extra":
    """The Planner view (`airspaces` and `planner`), and the airspace over each flight's
    map. Imported here: the viewer must build with the airspace package absent."""
    from airspaces import build as airspace_build
    from airspaces import openaip
    from airspaces import render_html as airspace_html
    from airspaces import scene as airspace_scene
    from planner import render_html as planner_html

    overlay = airspace_build.build()
    layers = args.html.parent / args.airspace / "layers"
    base, base_version = openaip.base(layers)
    openaip.write_circuits(layers, overlay)
    name = overlay.filename
    text = airspace_build.to_openair(overlay, base_version=base_version)
    # The download has to exist where the page points, which is `--airspace`'s argument
    # resolved against the page's own directory.
    target = args.html.parent / args.airspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="")
    print(f"wrote {target}")
    spaces = list(base) + overlay.circuit_airspaces
    # The view's ground is fetched in the page; without --terrain, the flat SVG map.
    payload = airspace_scene.remote(spaces) if args.terrain else None
    return render_html.Extra(
        uid="airspace",
        label="Planner",
        meta=f"{overlay.atz_count} zones &middot; {overlay.circuits} okruhy",
        body=airspace_html.body(overlay, base, base_version, openair_name=name,
                                openair_size=len(text), openair_href=f"{args.airspace}{name}",
                                scene=payload),
        style=airspace_html.STYLE + (planner_html.STYLE if payload else ""),
        script=(airspace_html.SCRIPT
                + (airspace_html.SCRIPT3D + planner_html.SCRIPT if payload else "")),
    )


if __name__ == "__main__":
    raise SystemExit(main())

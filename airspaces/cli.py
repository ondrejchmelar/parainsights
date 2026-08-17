"""Command line: write the XCTrack file, the map, or both."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import parainsights_common as common

from . import build, openair, render_html, sources


def _page(article: str, title: str, *, three_d: bool = False) -> str:
    """A standalone document holding just the airspace tab.

    Deliberately the same shape as the tracklog report's own page so the article can be
    lifted into it later without changing: one `<article data-flight-report>` switched
    by the report's existing tab strip.

    With a 3D map it also has to carry the view's own stylesheet and script, which in the
    report come from the page around it. `view3d.STYLE` after this file's own, so the
    panel's rules win where the two name the same thing.
    """
    view_style, view_script = "", ""
    if three_d:
        from tracklog_viewer import view3d, view3d_gl

        view_style = view3d.STYLE + view3d_gl.STYLE
        view_script = (f"<script>{view3d.SCRIPT}\n{view3d_gl.SCRIPT}</script>\n"
                       f"<script>{render_html.SCRIPT3D}</script>")
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script>{common.THEME_BOOT}</script>
<style>
{common.TOKENS}
body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55
  system-ui,-apple-system,"Segoe UI",sans-serif; }}
.wrap {{ max-width:1100px; margin:0 auto; padding:26px 18px 60px; }}
h1 {{ font-size:26px; margin:0 0 6px; }}
.lede {{ color:var(--ink-2); margin:0 0 14px; }}
button {{ font:inherit; padding:3px 10px; background:var(--panel);
  color:var(--ink); border:1px solid var(--rule); border-radius:3px; cursor:pointer; }}
{render_html.STYLE}
{common.STYLE}
{view_style}
</style>
<div class="wrap">
{common.nav("airspace", depth=1)}
{article}
</div>
<script>{render_html.SCRIPT}</script>
<script>{common.THEME_SCRIPT}</script>
{view_script}
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="airspaces",
        description="Czech ATZ and traffic circuits for XCTrack, and a map of the lot.",
    )
    parser.add_argument("--openair", metavar="FILE", type=Path,
                        help="write the XCTrack overlay (ATZ + circuits)")
    parser.add_argument("--html", metavar="FILE", type=Path,
                        help="write the airspace map as a standalone page")
    parser.add_argument("--flat", action="store_true",
                        help="the old flat SVG map instead of the 3D view. Needs no "
                             "network at build time and carries no imagery")
    parser.add_argument("--embed", action="store_true",
                        help="bake a stitched image into the page instead of fetching "
                             "imagery at view time. Needs no network to view, and over a "
                             "whole country it is a 300 m/pixel backdrop rather than a "
                             "map you can read")
    parser.add_argument("--online", action="store_true",
                        help=argparse.SUPPRESS)   # now the default
    parser.add_argument("--raw", action="store_true",
                        help="reproduce the ATZ publication unchanged, datum error and all")
    parser.add_argument("--no-circuits", action="store_true",
                        help="ATZ only, no traffic-circuit bands")
    parser.add_argument("--slz-zones", action="store_true",
                        help="also emit publication B's circles as airspace. Off by "
                             "default: an SLZ strip has no ATZ — those circles are UAS "
                             "zones, and only their traffic circuit concerns a pilot.")
    parser.add_argument("--publications", metavar="LETTERS", default="A,B",
                        help="which RLP UAS zone publications to include. "
                             "A=82 ICAO aerodromes, B=74 SLZ fields, C=222 heliports, "
                             "D=195 landing sites. Default A,B — C and D are mostly "
                             "hospital pads and add 417 small circles.")
    parser.add_argument("--require-terrain", action="store_true",
                        help="fail instead of falling back to the flat map when the "
                             "elevation model cannot be fetched. For a publishing "
                             "pipeline: silently replacing the 3D view with the flat "
                             "one is a downgrade, and a downgrade that reports success "
                             "is how a worse page gets published behind a green run")
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch every source instead of using the cache")
    parser.add_argument("--report", action="store_true",
                        help="print what was built and what could not be")
    args = parser.parse_args(argv)

    if not (args.openair or args.html or args.report):
        parser.error("nothing to do: pass --openair, --html or --report")

    pubs = [p.strip().upper() for p in args.publications.split(",") if p.strip()]
    unknown = [p for p in pubs if p not in sources.PUBLICATIONS]
    if unknown:
        parser.error(f"unknown publication(s) {', '.join(unknown)}; "
                     f"choose from {', '.join(sources.PUBLICATIONS)}")
    overlay = build.build(
        correct=not args.raw, refresh=args.refresh,
        with_circuits=not args.no_circuits, publications=pubs,
        slz_zones=args.slz_zones,
    )

    # Fetched once. The version goes in the OpenAir header's currency warning, so it is
    # needed even when only the file is being written; the text itself only when a map is.
    base_text, base_version = sources.base_airspace(refresh=args.refresh)
    text = build.to_openair(overlay, corrected=not args.raw, base_version=base_version)
    name = overlay.filename

    if args.openair:
        args.openair.write_text(text, encoding="utf-8", newline="")
        print(f"{args.openair}: {overlay.atz_count} ATZ, {overlay.circuit_count} circuits, "
              f"{len(text) / 1024:.0f} KB")

    if args.html:
        base = openair.read(base_text)
        # The terrain first, and *before* anything is written. A refused build has to
        # leave the committed page and its sidecar exactly as they were — the whole
        # point of refusing is that what is already published is better than what this
        # run can produce.
        payload = None
        if not args.flat:
            from . import scene as airspace_scene

            payload = airspace_scene.fetch(list(base) + list(overlay.airspaces),
                                           online=not args.embed)
            if payload is None:
                # The flat map is a real fallback and stays the default: a build with no
                # network still produces a usable page, which is "degrade, do not blank".
                # What it must not be is *silent* where the output is going to be
                # published — the deploy that taught this rebuilt the page without
                # terrain, overwrote a good 3D one, and reported success.
                if args.require_terrain:
                    parser.exit(1, "terrain unavailable, and --require-terrain says not "
                                   "to publish the flat map in its place. The 3D view "
                                   "needs the elevation model; nothing was written.\n")
                print("terrain unavailable, falling back to the flat map")

        # The page links to the OpenAir file rather than carrying it, so the file has
        # to be written beside the page — publishing the HTML alone gives a dead button.
        args.html.parent.mkdir(parents=True, exist_ok=True)
        beside = args.html.parent / name
        beside.write_text(text, encoding="utf-8", newline="")
        article = render_html.body(
            overlay, base, base_version, openair_name=name, openair_size=len(text),
            scene=payload,
        )
        args.html.write_text(_page(article, "Czech airspace",
                                   three_d=payload is not None), encoding="utf-8")
        print(f"{args.html}: {len(base)} base airspaces + {len(overlay.airspaces)} added")
        print(f"{beside}: linked from the page ({len(text) / 1024:.0f} KB)")

    if args.report:
        east, north, samples = overlay.offset
        print(f"ATZ            {overlay.atz_count}  "
              f"({overlay.circle_count} circles, {len(overlay.zones) - overlay.circle_count} clipped)")
        print(f"circuit bands  {overlay.circuit_count}")
        print(f"datum offset   E{east:+.0f} m N{north:+.0f} m over {samples} zones")
        with_note = sum(1 for f in overlay.fields.values() if f.circuit_note)
        print(f"circuit direction published for {with_note} of {len(overlay.fields)} aerodromes")
        for note in overlay.notes:
            print(f"  - {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Command line: write the XCTrack file, the map, or both."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import build, openair, render_html, sources


def _page(article: str, title: str) -> str:
    """A standalone document holding just the airspace tab.

    Deliberately the same shape as the tracklog report's own page so the article can be
    lifted into it later without changing: one `<article data-flight-report>` switched
    by the report's existing tab strip.
    """
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --paper:#fff; --panel:#f7f7f5; --panel-2:#eeeeea; --rule:#dcdcd6;
  --ink:#1b1b19; --ink-2:#4a4a45; --ink-3:#82827a; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --paper:#151513; --panel:#1e1e1b; --panel-2:#262622; --rule:#3a3a34;
    --ink:#eeeee8; --ink-2:#c0c0b8; --ink-3:#8a8a80; }}
}}
body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55
  system-ui,-apple-system,"Segoe UI",sans-serif; }}
.wrap {{ max-width:1100px; margin:0 auto; padding:26px 18px 60px; }}
h1 {{ font-size:26px; margin:0 0 6px; }}
.lede {{ color:var(--ink-2); margin:0 0 14px; }}
button {{ font:inherit; padding:3px 10px; background:var(--panel);
  color:var(--ink); border:1px solid var(--rule); border-radius:3px; cursor:pointer; }}
{render_html.STYLE}
</style>
<div class="wrap">
{article.replace(" hidden>", ">", 1)}
</div>
<script>{render_html.SCRIPT}</script>
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
    parser.add_argument("--raw", action="store_true",
                        help="reproduce the ATZ publication unchanged, datum error and all")
    parser.add_argument("--no-circuits", action="store_true",
                        help="ATZ only, no traffic-circuit boxes")
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch every source instead of using the cache")
    parser.add_argument("--report", action="store_true",
                        help="print what was built and what could not be")
    args = parser.parse_args(argv)

    if not (args.openair or args.html or args.report):
        parser.error("nothing to do: pass --openair, --html or --report")

    overlay = build.build(
        correct=not args.raw, refresh=args.refresh, with_circuits=not args.no_circuits
    )

    # Built once whether or not it is written out: the map embeds it as a download.
    text = build.to_openair(overlay, corrected=not args.raw)
    name = f"CZ_ATZ_{overlay.atz_date or 'current'}.txt".replace("-", "")

    if args.openair:
        args.openair.write_text(text, encoding="utf-8", newline="")
        print(f"{args.openair}: {overlay.atz_count} ATZ, {overlay.circuit_count} circuits, "
              f"{len(text) / 1024:.0f} KB")

    if args.html:
        base_text, version = sources.base_airspace(refresh=args.refresh)
        base = openair.read(base_text)
        article = render_html.body(
            overlay, base, version, openair_text=text, openair_name=name
        )
        args.html.write_text(_page(article, "Czech airspace"), encoding="utf-8")
        print(f"{args.html}: {len(base)} base airspaces + {len(overlay.airspaces)} added, "
              f"{name} embedded for download")

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

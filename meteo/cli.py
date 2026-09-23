"""Command line: write the meteo page, or refresh the site list behind it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import parainsights_common as common

from . import render_html, sites, sources


def page(article: str, title: str) -> str:
    """A standalone document holding just the meteo view.

    The same shell `airspaces.cli` writes, and for the same reason: the article is meant
    to be liftable into the report's view switch without changing.
    """
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script>{common.THEME_BOOT}</script>
<style>
{common.TOKENS}
body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55
  system-ui,-apple-system,"Segoe UI",sans-serif; }}
/* Wider than a reading column, because the charts are the page. At 1 100 px three
   soundings came to 340 px each, which is a temperature axis 30 °C wide in 300 px and a
   trace whose bends a reader has to lean in for. The prose does not stretch with it —
   `.lede` keeps its 70ch — so this buys width for the only things that want it. */
.wrap {{ max-width:1440px; margin:0 auto; padding:26px 18px 60px; }}
h1 {{ font-size:26px; margin:0 0 6px; }}
.lede {{ color:var(--ink-2); margin:0 0 14px; max-width:70ch; }}
a {{ color: inherit; }}
button {{ font:inherit; padding:3px 10px; background:var(--panel);
  color:var(--ink); border:1px solid var(--rule); border-radius:3px; cursor:pointer; }}
{render_html.STYLE}
{common.STYLE}
</style>
<div class="wrap">
{common.nav("meteo", depth=1)}
{article}
</div>
<script>{render_html.SCRIPT}</script>
<script>{common.THEME_SCRIPT}</script>
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="meteo",
        description="The day's forecast against the Czech takeoffs.",
    )
    parser.add_argument("--html", metavar="FILE", type=Path,
                        help="write the meteo page")
    parser.add_argument("--refresh-sites", action="store_true",
                        help="re-fetch the chosen takeoffs (meteo.sources.CHOSEN) from "
                             "ParaglidingEarth and rewrite meteo/sites.py")
    parser.add_argument("--refresh-flymet", action="store_true",
                        help="re-read flymet's station map and rewrite meteo/flymet.py")
    args = parser.parse_args(argv)

    if not (args.html or args.refresh_sites or args.refresh_flymet):
        parser.error("nothing to do: pass --html, --refresh-sites or --refresh-flymet")

    if args.refresh_sites:
        fetched = sources.fetch_chosen()
        target = Path(sites.__file__)
        sources.write(target, fetched)
        with_rose = sum(1 for site in fetched if site["winds"])
        print(f"{target}: {len(fetched)} takeoffs, {with_rose} with a wind rose")

    if args.refresh_flymet:
        from . import flymet

        stations, worst, scale = sources.fetch_flymet()
        # Refused rather than written. The stations carry no coordinates of their own —
        # they are solved from where flymet draws them — so a redrawn map would quietly
        # move every one of them, and a page that hands a takeoff the wrong airfield's
        # meteogram looks exactly like a page that works.
        if worst > sources.FLYMET_TOLERANCE_M:
            parser.exit(1, f"the station map no longer fits: {worst:.0f} m at the worst "
                           f"anchor, against a {sources.FLYMET_TOLERANCE_M:.0f} m limit. "
                           "Check meteo/sources.py FLYMET_ANCHORS against the map.\n")
        target = Path(flymet.__file__)
        sources.write_flymet(target, stations, worst, scale)
        print(f"{target}: {len(stations)} stations, worst anchor {worst:.0f} m "
              f"at {scale:.0f} m a pixel")

    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(page(render_html.body(), "Will it fly?"), encoding="utf-8")
        print(f"{args.html}: {len(sites.SITES)} takeoffs, forecast fetched at view time")
    return 0


if __name__ == "__main__":
    sys.exit(main())

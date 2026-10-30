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
{common.FAVICON}
<script>{common.THEME_BOOT}</script>
<style>
{common.TOKENS}
body {{ margin:0; background:var(--paper); color:var(--ink); }}
.wrap {{ max-width:1240px; margin:0 auto; padding:0 28px 60px; }}
@media (max-width: 640px) {{ .wrap {{ padding:0 14px 40px; }} }}
a {{ color: inherit; }}
{common.STYLE}
{render_html.STYLE}
</style>
<div class="wrap">
{common.nav("meteo", depth=1)}
{article}
{common.footer()}
{common.welcome("meteo")}
</div>
<script>{render_html.SCRIPT}</script>
<script>{common.THEME_SCRIPT}</script>
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="meteo",
        description="The day's forecast against the takeoffs.",
    )
    parser.add_argument("--html", metavar="FILE", type=Path,
                        help="write the meteo page")
    parser.add_argument("--refresh-sites", action="store_true",
                        help="re-read pgweb's takeoff list, pair each with its "
                             "ParaglidingEarth wind rose and rewrite meteo/sites.py")
    parser.add_argument("--keep-roses", action="store_true",
                        help="with --refresh-sites, when ParaglidingEarth cannot be "
                             "reached: keep the roses the committed list has")
    parser.add_argument("--refresh-flymet", action="store_true",
                        help="re-read flymet's station map and rewrite meteo/flymet.py")
    args = parser.parse_args(argv)

    if not (args.html or args.refresh_sites or args.refresh_flymet):
        parser.error("nothing to do: pass --html, --refresh-sites or --refresh-flymet")

    if args.refresh_sites:
        fetched, countries = sources.build(sources.fetch_pgweb())
        try:
            records = {iso: sources.fetch(iso)
                       for iso in sorted({site["country"] for site in fetched})}
            paired = sources.pair(fetched, records)
            roses = f"{paired} paired"
        except (OSError, ValueError) as error:
            # ParaglidingEarth was down for days in October 2026. Refused by default,
            # because a list written without roses judges nothing; --keep-roses writes
            # it with the roses the committed list already had.
            if not args.keep_roses:
                parser.exit(1, f"ParaglidingEarth could not be read ({error}); "
                               "pass --keep-roses to keep the committed roses\n")
            paired = sources.keep_roses(fetched, sites.SITES)
            roses = (f"ParaglidingEarth unreachable on this refresh, so {paired} roses "
                     "were kept from the previous list")
        sources.fill_altitudes(fetched)
        target = Path(sites.__file__)
        sources.write(target, fetched, countries, roses)
        with_rose = sum(1 for site in fetched if site["winds"])
        print(f"{target}: {len(fetched)} takeoffs in {len(countries)} countries, "
              f"{with_rose} with a wind rose")

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
        args.html.write_text(page(render_html.body(), "Meteo"), encoding="utf-8")
        print(f"{args.html}: {len(render_html.SITES)} takeoffs, forecast fetched at view time")
    return 0


if __name__ == "__main__":
    sys.exit(main())

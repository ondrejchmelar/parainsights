"""Command line: write the planner page.

The map under the planner is the airspace map, built by `airspaces.scene` — the same
terrain, the same imagery and the same rings, because the point of planning here rather
than on a bare basemap is seeing what the line crosses.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import parainsights_common as common

from . import render_html


def page(article: str, title: str, *, extra_style: str = "",
         extra_script: str = "") -> str:
    from airspaces import render_html as airspace_html
    from tracklog_viewer import view3d, view3d_gl

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
.lede {{ color:var(--ink-2); margin:0 0 14px; max-width:70ch; }}
a {{ color: inherit; }}
.met-links {{ margin:14px 0 0; font-size:12.5px; color:var(--ink-3); }}
button {{ font:inherit; padding:3px 10px; background:var(--panel);
  color:var(--ink); border:1px solid var(--rule); border-radius:3px; cursor:pointer; }}
{airspace_html.STYLE}
{view3d.STYLE}{view3d_gl.STYLE}
{render_html.STYLE}
{common.STYLE}
{extra_style}
</style>
<div class="wrap">
{common.nav("planner", depth=1)}
{article}
</div>
<script>{view3d.SCRIPT}
{view3d_gl.SCRIPT}</script>
<script>{render_html.SCRIPT}</script>
{extra_script}
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="planner",
        description="Draw a task over the terrain and the airspace, and score it.",
    )
    parser.add_argument("--html", metavar="FILE", type=Path, required=True,
                        help="write the planner page")
    parser.add_argument("--online", action="store_true",
                        help="fetch imagery at view time rather than embedding a stitch")
    parser.add_argument("--no-airspace", action="store_true",
                        help="terrain only. Faster to build, and the map then shows "
                             "nothing about what the line crosses")
    args = parser.parse_args(argv)

    from airspaces import build as airspace_build
    from airspaces import openair as airspace_openair
    from airspaces import scene as airspace_scene
    from airspaces import sources as airspace_sources
    from tracklog_viewer import view3d

    spaces = []
    if not args.no_airspace:
        overlay = airspace_build.build()
        base_text, _ = airspace_sources.base_airspace()
        spaces = list(airspace_openair.read(base_text)) + list(overlay.airspaces)

    payload = airspace_scene.fetch(spaces, online=args.online)
    if payload is None:
        print("terrain could not be fetched; the planner needs a map to draw on")
        return 1
    panel = view3d.panel(payload, "planner")

    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(
        page(render_html.body(scene_panel=panel), "Plan a task"), encoding="utf-8"
    )
    print(f"{args.html}: {len(payload['airspaces'])} airspaces under the planner")
    return 0


if __name__ == "__main__":
    sys.exit(main())

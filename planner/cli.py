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
<script>{common.THEME_BOOT}</script>
<style>
{common.TOKENS}
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
<script>{airspace_html.HOURS_SCRIPT}</script>
<script>{render_html.SCRIPT}</script>
<script>{common.THEME_SCRIPT}</script>
{extra_script}
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="planner",
        description="Draw a task over the terrain and the airspace, and score it.",
    )
    parser.add_argument("--html", metavar="FILE", type=Path, required=True,
                        help="write the planner page")
    parser.add_argument("--embed", action="store_true",
                        help="bake a stitched image into the page rather than fetching "
                             "imagery at view time")
    parser.add_argument("--online", action="store_true",
                        help=argparse.SUPPRESS)   # now the default
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

    # `airspace_scene.fetch`, but over `PLAN_BOX` rather than the airspace's own extent:
    # the planner's ground reaches past the country its airspace covers.
    from tracklog_viewer import basemap as viewer_basemap
    from tracklog_viewer import terrain as viewer_terrain

    ground = viewer_terrain.fetch(*render_html.PLAN_BOX, cols=render_html.PLAN_COLUMNS,
                                  max_points=render_html.PLAN_NODES, report=print)
    payload = None
    if ground is not None:
        images = ({} if not args.embed
                  else viewer_basemap.for_view(ground, max_tiles=90, quality=52))
        print(f"terrain {ground.cols}x{ground.rows} nodes")
        payload = airspace_scene.build(spaces, terrain=ground, basemaps=images,
                                       tiles=not args.embed)
    if payload is None:
        print("terrain could not be fetched; the planner needs a map to draw on")
        return 1
    # Same map, same reason as `airspaces/render_html.py`: at national scale a
    # traffic circuit is a third of a pixel tall.
    panel = view3d.panel(payload, "planner", verticals=(1, 5, 15), vertical=5)

    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(
        page(render_html.body(scene_panel=panel), "Plan a task"), encoding="utf-8"
    )
    print(f"{args.html}: {len(payload['airspaces'])} airspaces under the planner")
    return 0


if __name__ == "__main__":
    sys.exit(main())

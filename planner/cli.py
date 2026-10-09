"""Command line: write the redirect where the planner page used to be.

The planner is a section of the airspace page now (`airspaces.render_html.body`) — it
always drew on the airspace map, and two tabs over the same map were one too many. A
bookmark to `planner/` still has to land somewhere, so this writes a page that sends it
on to `../airspace/`, keeping the query and anchor, with a link for a reader without
JavaScript. Themed like every other page (`common.TOKENS`), because it may be on screen
for a frame.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import parainsights_common as common

TARGET = "../airspace/"


def page() -> str:
    return common.redirect(TARGET, "The planner has moved",
                           f'The task planner is now part of the <a href="{TARGET}">airspace page</a>.')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="planner",
        description="Write the redirect from the old planner page to the airspace page, "
                    "where the planner now lives.",
    )
    parser.add_argument("--html", metavar="FILE", type=Path, required=True,
                        help="where the old planner page was")
    args = parser.parse_args(argv)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(page(), encoding="utf-8")
    print(f"{args.html}: redirects to {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

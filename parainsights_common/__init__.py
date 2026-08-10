"""The one thing every tool's page shares: the strip that says what else is here.

This package is what `CLAUDE.md` reserves for shared code, and a navigation strip is the
first thing that has genuinely earned it — four pages published side by side under
`public/` with no way to get from one to another are four orphans, not a site. It holds
markup and nothing else: no geodesy, no analysis, and nothing a tool could disagree with
another tool about.

The links are relative and assume the published layout, which is the only layout the
`pages` job produces:

    public/index.html        the flight report      → `.`
    public/airspace/         the airspace map       → `airspace/`
    public/meteo/            the day's forecast     → `meteo/`
    public/planner/          the task planner       → `planner/`

`depth` is how far below `public/` the page being written lives, because a page in
`airspace/` has to reach its siblings through `../`. It is passed in rather than guessed
from a path: the same article is also embedded in the report at the top level, and a
strip that guessed would be wrong in one of the two places.
"""

from __future__ import annotations

# key, label, directory under public/. Order is the order a day happens in: what is the
# weather, where shall I go, what will I fly, and then what did I actually do.
PAGES = [
    ("meteo", "Meteo", "meteo/"),
    ("planner", "Planner", "planner/"),
    ("airspace", "Airspace", "airspace/"),
    ("flights", "Flights", ""),
]

STYLE = """
.site-nav { display:flex; gap:4px; flex-wrap:wrap; margin:0 0 18px;
  border-bottom:1px solid var(--rule); }
.site-nav a, .site-nav span { font-size:15px; font-weight:600; letter-spacing:0.01em;
  color:var(--ink-3); text-decoration:none; padding:9px 15px 8px; margin-bottom:-1px;
  border-bottom:2px solid transparent; }
.site-nav a:hover { color:var(--ink-2); }
.site-nav .is-on { color:var(--ink); border-bottom-color:#eb6834; }
"""


def nav(current: str, depth: int = 0) -> str:
    """The strip, with `current` marked and not linked.

    The page you are on is a `<span>`, not a link to itself: a tab that navigates to the
    page it is already on looks broken on a slow connection and is the classic way a
    reader loses their scroll position.
    """
    up = "../" * depth
    parts = []
    for key, label, where in PAGES:
        if key == current:
            parts.append(f'<span class="is-on">{label}</span>')
        else:
            parts.append(f'<a href="{up}{where or "index.html"}">{label}</a>')
    return f'<nav class="site-nav" aria-label="The tools here">{"".join(parts)}</nav>'

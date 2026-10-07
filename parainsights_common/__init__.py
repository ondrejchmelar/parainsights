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
    public/planner/          a redirect to the airspace page, where the planner is now

`depth` is how far below `public/` the page being written lives, because a page in
`airspace/` has to reach its siblings through `../`. It is passed in rather than guessed
from a path: the same article is also embedded in the report at the top level, and a
strip that guessed would be wrong in one of the two places.
"""

from __future__ import annotations
from pathlib import Path

# key, label, directory under public/. Order is the order a day happens in: what is the
# weather, where shall I go, what will I fly, and then what did I actually do.
#
# The planner is not a page of its own any more: it draws on the airspace map, and two
# tabs over the same map were one too many. `public/planner/` only redirects.
PAGES = [
    ("meteo", "Meteo", "meteo/"),
    ("airspace", "Planner", "airspace/"),
    ("flights", "Flights", ""),
]

# The tokens every tool's page draws on, in one place because they were in three —
# `meteo`, `airspaces` and `planner` each carried an identical copy, which is three
# chances for the site to disagree with itself about what grey means.
#
# **Two scopes for the dark theme, and the order matters.** The media query answers the
# operating system; `[data-theme]` answers the reader's own button and has to win either
# way. `:where(:not([data-theme="light"]))` keeps the media block's specificity at zero,
# so a light stamp beats OS-dark, and the explicit dark scope below beats OS-light. The
# report has carried this shape for a while; it is the rest of the site catching up.
TOKENS = """
:root { --paper:#fff; --panel:#f7f7f5; --panel-2:#eeeeea; --rule:#dcdcd6;
  --ink:#1b1b19; --ink-2:#4a4a45; --ink-3:#82827a; color-scheme: light; }
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) { color-scheme: dark;
    --paper:#151513; --panel:#1e1e1b; --panel-2:#262622; --rule:#3a3a34;
    --ink:#eeeee8; --ink-2:#c0c0b8; --ink-3:#8a8a80; }
}
:root[data-theme="dark"] { color-scheme: dark;
  --paper:#151513; --panel:#1e1e1b; --panel-2:#262622; --rule:#3a3a34;
  --ink:#eeeee8; --ink-2:#c0c0b8; --ink-3:#8a8a80; }
"""

# Applied before anything is painted. A theme read from storage *after* the first paint
# is a white flash on a dark page every time the reader opens it, which is worse than
# not remembering at all — so this is the one script that goes in the head, and it is
# three lines long for exactly that reason.
THEME_BOOT = """
try {
  var t = localStorage.getItem('parainsights.theme');
  if (t) document.documentElement.dataset.theme = t;
} catch (e) {}
"""

# The button's behaviour. Deliberately *not* a third state: the button says what it will
# do next, and "follow the system" is a thing readers set once in their system and never
# think about again — a page that offers it as a third click is a page asking them to
# manage a preference they already expressed.
THEME_SCRIPT = (Path(__file__).parent / "js/theme.js").read_text(encoding="utf-8")


def theme_button() -> str:
    """The switch. One glyph, a title and an `aria-pressed`, and no visible label.

    It sits in the strip on every page, so it is furniture: a word beside it would be
    read once and then be in the way forever. The glyph says what you will *get*, which
    is the convention every reader already has from every other site.
    """
    return ('<button type="button" class="theme-toggle" aria-pressed="false" '
            'aria-label="Switch between the light and dark theme">'
            '<span class="theme-glyph" aria-hidden="true">\u263D</span></button>')


STYLE = """
.site-nav { display:flex; gap:4px; flex-wrap:wrap; margin:0 0 18px;
  border-bottom:1px solid var(--rule); }
/* Direct children only. `.site-nav span` caught the glyph *inside* the theme button and
   gave it 15 px of side padding in a 30 px circle, which pushed the moon hard against
   the right edge — the strip styles its own items, not whatever they happen to contain. */
.site-nav > a, .site-nav > span { font-size:15px; font-weight:600; letter-spacing:0.01em;
  color:var(--ink-3); text-decoration:none; padding:9px 15px 8px; margin-bottom:-1px;
  border-bottom:2px solid transparent; }
.site-nav > a:hover { color:var(--ink-2); }
.site-nav > .is-on { color:var(--ink); border-bottom-color:#eb6834; }
.theme-toggle { margin:0 0 0 auto; align-self:center; border:1px solid var(--rule);
  background:var(--panel); color:var(--ink-2); border-radius:999px; cursor:pointer;
  width:30px; height:30px; padding:0; font-size:14px;
  /* Grid rather than `line-height`: the glyph is a character whose ink sits high in its
     em box (☽ higher than ☀), so a line box centres the *box* and leaves the mark
     visibly above centre. A grid cell centres the thing that was actually drawn. */
  display:grid; place-items:center; line-height:1; }
.theme-toggle .theme-glyph { display:block; }
.site-nav > a.site-source { align-self:center; margin:0 0 0 6px; padding:0; width:30px;
  height:30px; display:grid; place-items:center; border:1px solid var(--rule);
  border-radius:999px; background:var(--panel); color:var(--ink-2); }
.site-foot { margin:48px 0 0; padding:14px 0 0; border-top:1px solid var(--rule);
  font-size:12.5px; line-height:1.55; color:var(--ink-3); }
.site-foot a { color:var(--ink-2); }
.site-nav > a.site-source:hover { color:var(--ink); border-color:var(--ink-3); }
.theme-toggle:hover { color:var(--ink); border-color:var(--ink-3); }
"""


SOURCE = "https://github.com/ondrejchmelar/parainsights"
_GITHUB_MARK = (
    '<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">'
    '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01'
    '-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53'
    '.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89'
    '-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32'
    '-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82'
    ' 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0'
    ' .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>')


def strip_end() -> str:
    """What closes every page's strip: the theme switch and the link to the source."""
    return (theme_button()
            + f'<a class="site-source" href="{SOURCE}" rel="noreferrer" '
              f'title="The source, on GitHub" aria-label="The source, on GitHub">{_GITHUB_MARK}</a>')


def footer() -> str:
    """The foot of every page: what this is, where its source is, and who to credit."""
    return (
        '<footer class="site-foot">'
        f'<a href="{SOURCE}" rel="noreferrer">parainsights on GitHub</a> — the source, the '
        "issues, and how every number on these pages is worked out. Airspace © "
        '<a href="https://www.openaip.net" rel="noreferrer">openAIP</a> (CC BY-NC 4.0); '
        "imagery © Esri, Maxar, Earthstar Geographics; place names © OpenMapTiles, "
        "© OpenStreetMap contributors; terrain: AWS Open Data; weather: Open-Meteo."
        "</footer>"
    )


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
    parts.append(strip_end())
    return f'<nav class="site-nav" aria-label="The tools here">{"".join(parts)}</nav>'

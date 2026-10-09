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
# chances for the site to disagree with itself about what grey means. Since the redesign
# (October 2026) the report draws on them too, data colours included: it had its own
# cool blue-grey set, and the site read as two products.
#
# **Two scopes for the dark theme, and the order matters.** The media query answers the
# operating system; `[data-theme]` answers the reader's own button and has to win either
# way. `:where(:not([data-theme="light"]))` keeps the media block's specificity at zero,
# so a light stamp beats OS-dark, and the explicit dark scope below beats OS-light.
#
# What each is for, because the names are the design system:
#   paper, panel, panel-2  the page, a card, a hover or a quiet fill
#   ink, ink-2             text; ink-2 is the quiet one and still passes 4.5 : 1 on every
#                          background. **ink-3 is ink-2 now**: the old faint grey was
#                          3.3–3.9 : 1 in the light theme, and it was the most used colour
#                          on the site. Kept as a name so nothing that says it breaks.
#   rule                   dividers and card outlines — things you do not click
#   edge (= rule-strong)   the outline of anything you can click, ≥ 3 : 1
#   accent, on-accent      the one action colour: primary buttons, links, focus
#   good, warn, bad        verdicts, always with a word beside them
#   series-1..3            a takeoff's own colour on the meteo page, never a status colour
#   float*                 panels and buttons floating over a map
#   climb*, sink*, ld-*,   the data: the climb-rate diverging ramp, the glide-ratio ramp,
#   tow, neutral, shadow-ink  phases — validated palettes (see "Design system")
_LIGHT = """--paper:#f6f5f1; --panel:#ffffff; --panel-2:#eeece6; --ink:#161614; --ink-2:#45433d;
  --ink-3:#45433d; --rule:#d9d5cb; --edge:#8f8a80; --rule-strong:#8f8a80;
  --accent:#c2410c; --on-accent:#ffffff; --good:#13803f; --on-good:#ffffff;
  --warn:#8f6200; --on-warn:#ffffff; --bad:#b42318;
  --series-1:#7c3aed; --series-2:#0e7f93; --series-3:#c42a72;
  --float:rgba(255,255,255,.92); --float-2:rgba(238,236,230,.96); --float-edge:rgba(0,0,0,.16);
  --float-shadow:0 6px 20px rgba(0,0,0,.18); --pop-bg:#1d1d1a; --pop-ink:#f2f0ea;
  --climb:#eb6834; --climb-1:#f0a07a; --climb-2:#eb6834; --climb-3:#c8431a;
  --sink:#1d5fd1; --sink-1:#8fb6e6; --sink-2:#1d5fd1; --sink-3:#17508f;
  --tow:#1baf7a; --neutral:#a9a49a; --shadow-ink:#c3bfb4;
  --ld-1:#86aed8; --ld-2:#5f92c9; --ld-3:#3f74b4; --ld-4:#2a5894; --ld-5:#173d69;"""
_DARK = """--paper:#141412; --panel:#1d1d1a; --panel-2:#272723; --ink:#efede8; --ink-2:#c3bfb6;
    --ink-3:#c3bfb6; --rule:#34332e; --edge:#6b685f; --rule-strong:#6b685f;
    --accent:#e8692c; --on-accent:#141412; --good:#2fb36a; --on-good:#0b1a10;
    --warn:#d9a21b; --on-warn:#111111; --bad:#e5484d;
    --series-1:#a78bfa; --series-2:#3cc8dc; --series-3:#f47fb0;
    --float:rgba(20,20,18,.84); --float-2:rgba(39,39,35,.92); --float-edge:rgba(255,255,255,.16);
    --float-shadow:0 6px 20px rgba(0,0,0,.35); --pop-bg:#f3f1ec; --pop-ink:#181816;
    --climb:#e8692c; --climb-1:#b06a4a; --climb-2:#e8692c; --climb-3:#f08a55;
    --sink:#4b8ff0; --sink-1:#4a6f9e; --sink-2:#4b8ff0; --sink-3:#86b2f5;
    --tow:#199e70; --neutral:#8a877f; --shadow-ink:#3a3934;
    --ld-1:#35577f; --ld-2:#4874a6; --ld-3:#5b91cc; --ld-4:#74aae0; --ld-5:#9cc6f0;"""
TOKENS = f"""
:root {{ color-scheme: light; {_LIGHT} }}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{ color-scheme: dark; {_DARK} }}
}}
:root[data-theme="dark"] {{ color-scheme: dark; {_DARK} }}
"""

# Applied before anything is painted. A theme read from storage *after* the first paint
# is a white flash on a dark page every time the reader opens it, which is worse than
# not remembering at all — so this is the one script that goes in the head, and it is
# three lines long for exactly that reason.
THEME_BOOT = """
try {
  var t = localStorage.getItem('parainsights.theme');
  if (t) document.documentElement.dataset.theme = t;
  if (localStorage.getItem('parainsights.text') === 'large') document.documentElement.dataset.text = 'large';
  if (localStorage.getItem('parainsights.help') === 'off') document.documentElement.dataset.help = 'off';
} catch (e) {}
"""

# The button's behaviour. Deliberately *not* a third state: the button says what it will
# do next, and "follow the system" is a thing readers set once in their system and never
# think about again — a page that offers it as a third click is a page asking them to
# manage a preference they already expressed.
THEME_SCRIPT = (Path(__file__).parent / "js/theme.js").read_text(encoding="utf-8")
# The text-size and Help switches, and the ⓘ: shipped with the theme's script because
# every page that has the one has the others.
THEME_SCRIPT += (Path(__file__).parent / "js/prefs.js").read_text(encoding="utf-8")


# One icon set for the whole site: 20 px, a 1.75 px round stroke in `currentColor`. A
# Unicode glyph as an icon (☽ ⇆ × ＋ ✎ ↓) draws in whatever font the reader has, at a size
# and weight nobody chose, and the site mixed filled, stroked and typed marks.
def icon(paths: str, size: int = 20) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
            'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{paths}</svg>')


ICONS = {
    "sun": '<circle cx="10" cy="10" r="3.5"/><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M4.3 15.7l1.4-1.4M14.3 5.7l1.4-1.4"/>',
    "moon": '<path d="M15.5 12.5A6.5 6.5 0 0 1 7.5 4.5a6.5 6.5 0 1 0 8 8z"/>',
    "swap": '<path d="M4 7h12l-3-3M16 13H4l3 3"/>',
    "close": '<path d="M5 5l10 10M15 5 5 15"/>',
    "plus": '<path d="M10 4v12M4 10h12"/>',
    "minus": '<path d="M4 10h12"/>',
    "pencil": '<path d="M4 16l1-4 8.5-8.5 3 3L8 15z"/><path d="M11.5 5.5l3 3"/>',
    "download": '<path d="M10 3v10M6 9l4 4 4-4M4 16.5h12"/>',
    "down": '<path d="M5.5 8l4.5 4.5L14.5 8"/>',
    "right": '<path d="M8 5.5l4.5 4.5L8 14.5"/>',
    "arrow": '<path d="M4 10h12M12 6l4 4-4 4"/>',
    "expand": '<path d="M11.5 3.5h5v5M8.5 16.5h-5v-5M16.5 3.5 11 9M3.5 16.5 9 11"/>',
}


def _attr(markup: str) -> str:
    return markup.replace("&", "&amp;").replace('"', "&quot;")


def theme_button() -> str:
    """The switch. One icon, a title and an `aria-pressed`, and no visible label.

    It sits in the strip on every page, so it is furniture: a word beside it would be
    read once and then be in the way forever. The icon says what you will *get*, which
    is the convention every reader already has from every other site.
    """
    return ('<button type="button" class="tool theme-toggle" aria-pressed="false" '
            'aria-label="Switch between the light and dark theme">'
            f'<span class="theme-glyph" data-sun="{_attr(icon(ICONS["sun"]))}" '
            f'data-moon="{_attr(icon(ICONS["moon"]))}">{icon(ICONS["moon"])}</span></button>')


def text_button() -> str:
    """aA: the whole page an eighth larger, remembered like the theme. For readers who
    find 16 px small and would rather not zoom the browser, which zooms the map too."""
    return ('<button type="button" class="tool text-toggle" aria-pressed="false" '
            'title="Larger text" aria-label="Larger text">A<b>A</b></button>')


def help_button() -> str:
    """Help: shows or hides every ⓘ (and the map's ? button). A first-time reader wants
    the explanations; someone on their fortieth flight wants them gone."""
    return ('<button type="button" class="tool help-toggle" aria-pressed="true" '
            'title="Show or hide the explanations (ⓘ)">Help<span class="switch" aria-hidden="true">'
            '</span></button>')


def info(text: str, label: str = "More about this") -> str:
    """The ⓘ: a small circled i straight after the label it explains. Hover on a desktop,
    tap on touch, Esc or a tap elsewhere closes it; `prefs.js` keeps the bubble on
    screen. `text` is HTML. The same markup as `TV.report`'s `info` in the article."""
    return (f'<span class="info-wrap"><button type="button" class="info" aria-expanded="false" '
            f'aria-label="{_attr(label)}">i</button><span class="info-pop" role="note">{text}</span></span>')


# What every page shares beyond the tokens: type, the controls, the ⓘ, legends, focus.
# The redesign's rules, stated once (October 2026):
#   - text 16 px, nothing a reader must read under 15 px, sentence case — no 11 px
#     letter-spaced capitals, which were most of the labels on the site;
#   - controls 44 px high, 16 px / 600, outlined in --edge; hover --panel-2; the selected
#     one filled with ink (the nav, segmented controls, map toggles);
#   - four radii: 10 controls, 11 segmented controls, 14 cards / panels / images, a pill
#     for chips, nav tools and badges. Checkboxes keep 5, so they never read as radios;
#   - one link style: accent, 600, underlined on hover.
BASE = """
body { font-family: "Noto Sans", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 16px; line-height: 1.55; -webkit-font-smoothing: antialiased; }
/* aA: the page an eighth larger, the maps excepted — MapLibre reads its pointer through
   the zoom, and a zoomed canvas blurs. */
html[data-text="large"] body { zoom: 1.125; }
html[data-text="large"] .view3d-panel { zoom: calc(1 / 1.125); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.lnk, a.lnk { color: var(--accent); font-weight: 600; text-decoration: none; cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px; background: none; border: 0; padding: 0;
  font-family: inherit; font-size: inherit; }
.lnk:hover { text-decoration: underline; }
.btn { height: 44px; padding: 0 16px; border-radius: 10px; border: 1px solid var(--edge);
  background: var(--panel-2); color: var(--ink); font-family: inherit; font-size: 16px; font-weight: 600;
  line-height: 1; display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  cursor: pointer; text-decoration: none; white-space: nowrap; }
.btn:hover { background: var(--panel); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.btn.primary:hover { filter: brightness(1.06); }
.btn:disabled { opacity: .5; cursor: default; }
.btn svg, .tool svg, .lnk svg, .chip svg { display: block; flex: none; }
.seg { display: inline-flex; border: 1px solid var(--edge); border-radius: 11px; overflow: hidden;
  background: var(--panel); vertical-align: middle; }
.seg > button, .seg > span { height: 42px; padding: 0 16px; border: 0; border-radius: 0; background: none;
  color: var(--ink-2); font-family: inherit; font-size: 16px; font-weight: 600; line-height: 1;
  cursor: pointer; display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; }
.seg > * + * { border-left: 1px solid var(--rule); }
.seg > button:hover { background: var(--panel-2); color: var(--ink); }
.seg > .is-on, .seg > [aria-pressed="true"] { background: var(--ink); color: var(--paper); }
.seg > .is-on:hover, .seg > [aria-pressed="true"]:hover { background: var(--ink); color: var(--paper); }
.chip { display: inline-flex; align-items: center; gap: 8px; height: 44px; padding: 0 16px;
  border-radius: 999px; border: 1px solid var(--edge); background: var(--panel); color: var(--ink);
  font-family: inherit; font-size: 16px; font-weight: 600; line-height: 1; }
.dot { display: inline-block; width: 11px; height: 11px; border-radius: 50%; flex: none; }
.badge { display: inline-flex; align-items: center; padding: 3px 11px; border-radius: 999px;
  font-weight: 600; font-size: 15px; line-height: 1.3; white-space: nowrap; }
.badge.good { background: var(--good); color: var(--on-good); }
.badge.warn { background: var(--warn); color: var(--on-warn); }
.badge.bad { border: 1.5px solid var(--edge); color: var(--ink-2); }
.badge.accent { background: var(--accent); color: var(--on-accent); }
.legend-row { display: flex; flex-wrap: wrap; gap: 6px 18px; align-items: center; margin: 10px 0 0;
  padding: 0; list-style: none; font-size: 15px; color: var(--ink-2); }
.legend-row > * { display: inline-flex; align-items: center; gap: 7px; }
.legend-row i { width: 14px; height: 10px; border-radius: 3px; display: inline-block; flex: none; }
.legend-row .grad { width: 70px; height: 10px; border-radius: 5px; display: inline-block;
  background: linear-gradient(90deg, var(--sink), var(--neutral), var(--climb)); }
/* The ⓘ: about the cap height of the text it follows, a 44 px target for a finger. */
.info-wrap { position: relative; display: inline-flex; align-items: center; vertical-align: 0.1em;
  margin-left: 0.4em; font-weight: 400; text-transform: none; letter-spacing: 0; line-height: 1; }
.info { position: relative; display: inline-flex; align-items: center; justify-content: center;
  width: 1.3em; height: 1.3em; min-width: 13px; min-height: 13px; padding: 0; border-radius: 50%;
  border: 1.5px solid var(--ink-2); background: none; color: var(--ink-2);
  font: italic 700 0.66em/1 Georgia, serif; cursor: help; box-sizing: border-box; flex: none; }
.info::after { content: ""; position: absolute; inset: -12px; }
.info:hover, .info[aria-expanded="true"] { color: var(--ink); border-color: var(--ink); }
.info-pop { display: none; position: absolute; z-index: 80; left: 50%; top: calc(100% + 10px);
  transform: translateX(-50%); width: max-content; max-width: min(320px, 86vw); padding: 12px 15px;
  background: var(--pop-bg); color: var(--pop-ink); border-radius: 14px; box-shadow: 0 10px 34px rgba(0,0,0,.35);
  font: 400 15.5px/1.5 "Noto Sans", ui-sans-serif, system-ui, sans-serif; text-align: left;
  white-space: normal; letter-spacing: 0; text-transform: none; }
.info-pop a { color: inherit; }
.info-wrap.to-left .info-pop { left: auto; right: -12px; transform: none; }
.info-wrap.to-right .info-pop { left: -12px; transform: none; }
@media (hover: hover) { .info-wrap:hover .info-pop { display: block; } }
.info[aria-expanded="true"] + .info-pop { display: block; }
html[data-help="off"] .info-wrap { display: none; }
"""

STYLE = """
/* The strip: the three tools, then aA, Help, the theme and the source. */
.site-nav { display:flex; align-items:center; gap:4px; min-height:62px; margin:0 0 18px;
  border-bottom:1px solid var(--rule); flex-wrap:wrap; }
.site-nav > a, .site-nav > span:not(.site-sp), .site-nav > .view-tab { height:44px; display:inline-flex;
  align-items:center; padding:0 15px; border-radius:10px; font-family:inherit; font-size:16px;
  font-weight:600; line-height:1; color:var(--ink-2); text-decoration:none; border:0; background:none;
  cursor:pointer; margin:0; }
.site-nav > a:hover, .site-nav > .view-tab:hover { background:var(--panel-2); color:var(--ink); }
.site-nav > .is-on:not(.site-sp), .site-nav > .is-on:not(.site-sp):hover { background:var(--ink); color:var(--paper); }
.site-nav > .site-sp { flex:1; }
.site-nav > a.tool { padding:0 13px; border:1px solid var(--edge); border-radius:999px; }
.tool { height:44px; min-width:44px; padding:0 13px; display:inline-flex; align-items:center; justify-content:center;
  gap:8px; border:1px solid var(--edge); border-radius:999px; background:transparent; color:var(--ink-2);
  font-family:inherit; font-size:16px; font-weight:600; line-height:1; cursor:pointer; text-decoration:none; }
.tool:hover { background:var(--panel-2); color:var(--ink); }
.text-toggle { gap:1px; } .text-toggle b { font-size:19px; }
/* aA and the theme: the same circle, side by side at the end of the strip. */
.tool.text-toggle, .tool.theme-toggle { width:44px; min-width:44px; padding:0; }
.text-toggle[aria-pressed="true"] { background:var(--ink); color:var(--paper); border-color:var(--ink); }
.switch { width:36px; height:21px; border-radius:11px; background:var(--edge); position:relative; flex:none; }
.switch::after { content:""; position:absolute; left:3px; top:3px; width:15px; height:15px; border-radius:50%;
  background:#fff; transition:left .15s; }
.help-toggle[aria-pressed="true"] .switch { background:var(--accent); }
.help-toggle[aria-pressed="true"] .switch::after { left:18px; }
.theme-glyph, .theme-glyph svg { display:block; }
.site-foot { margin:56px 0 0; padding:18px 0 0; border-top:1px solid var(--rule);
  font-size:15px; line-height:1.55; color:var(--ink-2); display:block; }
.site-foot a { color:var(--ink-2); }
.site-foot .gh { vertical-align: -2px; margin-right: 6px; }
@media (max-width: 640px) {
  .site-nav { gap:2px; min-height:56px; }
  .site-nav { flex-wrap:nowrap; }
  .site-nav > a, .site-nav > span:not(.site-sp), .site-nav > .view-tab { padding:0 8px; }
  .site-nav > a.tool, .tool { padding:0 9px; min-width:40px; }
  /* Help is a desktop switch: on a phone the ⓘ are there to tap, and the strip is full. */
  .help-toggle { display:none; }
}
""" + BASE



SOURCE = "https://github.com/ondrejchmelar/parainsights"
# GitHub's mark, small, beside the source link in the foot of every page.
_GITHUB_MARK = (
    '<svg class="gh" width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">'
    '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01'
    '-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53'
    '.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89'
    '-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32'
    '-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82'
    ' 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0'
    ' .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>')


def strip_end() -> str:
    """What closes every page's strip: aA, Help and the theme switch. The source is linked
    from the foot of the page (`footer`), with GitHub's mark beside it."""
    return '<span class="site-sp"></span>' + text_button() + help_button() + theme_button()


def footer() -> str:
    """The foot of every page: what this is, where its source is, and who to credit."""
    return (
        '<footer class="site-foot">'
        f'<a href="{SOURCE}" rel="noreferrer">{_GITHUB_MARK}parainsights on GitHub</a> — the source, the '
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

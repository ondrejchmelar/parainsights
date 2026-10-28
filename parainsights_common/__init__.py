"""The one thing every tool's page shares: the strip that says what else is here.

This package is what `CLAUDE.md` reserves for shared code, and a navigation strip is the
first thing that has genuinely earned it — four pages published side by side under
`public/` with no way to get from one to another are four orphans, not a site. It holds
markup and nothing else: no geodesy, no analysis, and nothing a tool could disagree with
another tool about.

The links are relative and assume the published layout, which is the only layout the
`pages` job produces:

    public/flights/          the flight report      → `flights/`
    public/planner/          the planner and airspace map, with its layers → `planner/`
    public/meteo/            the day's forecast     → `meteo/`
    public/index.html        a redirect to `flights/` (`redirect`), for old links
    public/airspace/         a redirect to `planner/`, the page's address until October 2026

Every tool is one level down, its own address (October 2026: the report was the site's
root, the one page without a name of its own).

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
    ("airspace", "Planner", "planner/"),
    ("flights", "Flights", "flights/"),
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
  --series-4:#a16207; --series-5:#475569; --series-6:#4d7c0f;
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
    --series-4:#e0a458; --series-5:#a8b3c4; --series-6:#9bc25b;
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

# The published site's host: what counts visits and shows the welcome, so a page built and
# opened locally does neither.
SITE_HOST = "ondrejchmelar.github.io"

# Applied before anything is painted. A theme read from storage *after* the first paint
# is a white flash on a dark page every time the reader opens it, which is worse than
# not remembering at all — so this is the one script that goes in the head, and it is
# three lines long for exactly that reason.
THEME_BOOT = """
try {
  var t = localStorage.getItem('parainsights.theme');
  if (t) document.documentElement.dataset.theme = t;
  if (localStorage.getItem('parainsights.text') === 'large') document.documentElement.dataset.text = 'large';
} catch (e) {}
"""

# The button's behaviour. Deliberately *not* a third state: the button says what it will
# do next, and "follow the system" is a thing readers set once in their system and never
# think about again — a page that offers it as a third click is a page asking them to
# manage a preference they already expressed.
THEME_SCRIPT = (Path(__file__).parent / "js/theme.js").read_text(encoding="utf-8")
# The text-size switch and the ⓘ: shipped with the theme's script because
# every page that has the one has the others.
THEME_SCRIPT += (Path(__file__).parent / "js/prefs.js").read_text(encoding="utf-8")
# And the welcome (`welcome`), which does nothing on a page without one.
THEME_SCRIPT += ((Path(__file__).parent / "js/welcome.js").read_text(encoding="utf-8")
                 .replace("__SITE_HOST__", SITE_HOST))


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


def fold(title: str, body: str, cls: str = "") -> str:
    """A collapsible panel, closed: the title row opens it (`details.fold`). The same
    markup as `sourcesFold` in `tracklog_viewer/js/report.js`."""
    return (f'<details class="fold{(" " + cls) if cls else ""}"><summary><span>{title}</span>'
            f'{icon(ICONS["down"])}</summary><div class="fold-body">{body}</div></details>')


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
/* A collapsible panel (`fold`): a panel whose title row opens it, the chevron turning.
   Sources and method on every page; closed until asked for. */
details.fold { margin: 40px 0 0; background: var(--panel); border: 1px solid var(--rule); border-radius: 14px; }
details.fold > summary { list-style: none; display: flex; align-items: center; justify-content: space-between;
  gap: 12px; min-height: 52px; padding: 0 14px 0 18px; font-weight: 600; color: var(--ink); cursor: pointer;
  border-radius: 14px; }
details.fold > summary::-webkit-details-marker { display: none; }
details.fold > summary:hover { background: var(--panel-2); }
details.fold[open] > summary { border-radius: 14px 14px 0 0; }
details.fold > summary svg { flex: none; color: var(--ink-2); transition: transform .15s; }
details.fold[open] > summary svg { transform: rotate(180deg); }
details.fold > .fold-body { padding: 0 18px 14px; }
details.fold tr:last-child, details.fold tr:last-child > * { border-bottom: 0; }
/* A section's ⓘ: its terms, one line each. */
.info-pop:has(.gloss) { max-width: min(420px, 90vw); }
.gloss { display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; margin: 0; }
.gloss dt { font-weight: 600; white-space: nowrap; }
.gloss dd { margin: 0; }
@media (max-width: 640px) { .gloss { grid-template-columns: 1fr; gap: 0; } .gloss dd { margin-bottom: 6px; } }
"""

STYLE = """
/* The strip: the three tools, then aA and the theme. */
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
    """What closes every page's strip: aA and the theme switch. The source is linked from
    the foot of the page (`footer`), with GitHub's mark beside it. There was a Help switch
    hiding every ⓘ until October 2026; with one ⓘ per section there is nothing to hide."""
    return '<span class="site-sp"></span>' + text_button() + theme_button()


ANALYTICS_TOKEN = "fb27179888c0414ca33f514014e088d2"
# Cloudflare Web Analytics: no cookies, nothing stored on the reader's device. Loaded only on
# the published site, so a report built and opened locally neither counts nor calls out.
_ANALYTICS = (
    f"<script>if (location.hostname === '{SITE_HOST}') {{"
    "const s = document.createElement('script'); s.defer = true;"
    "s.src = 'https://static.cloudflareinsights.com/beacon.min.js';"
    f"s.dataset.cfBeacon = '{{\"token\": \"{ANALYTICS_TOKEN}\"}}';"
    "document.head.appendChild(s); }</script>"
)


def footer() -> str:
    """The foot of every page: what this is, where its source is, and who to credit."""
    return (
        '<footer class="site-foot">'
        f'<a href="{SOURCE}" rel="noreferrer">{_GITHUB_MARK}parainsights on GitHub</a>. Airspace © '
        '<a href="https://www.openaip.net" rel="noreferrer">openAIP</a> (CC BY-NC 4.0); '
        "imagery © Esri, Maxar, Earthstar Geographics; place names © OpenMapTiles, "
        "© OpenStreetMap contributors; terrain © "
        '<a href="https://mapterhorn.com/attribution" rel="noreferrer">Mapterhorn</a> '
        "(Copernicus DEM and national surveys); weather: Open-Meteo. "
        "Visits are counted by Cloudflare Web Analytics, without cookies."
        f"</footer>{_ANALYTICS}"
    )


def redirect(target: str, title: str, says: str) -> str:
    """A page that sends its reader on to `target`, keeping the query and the anchor, with
    a link for a reader without JavaScript. Themed (`TOKENS`), because it may be on screen
    for a frame. Where a page used to be: the root, now that the report is in `flights/`;
    the planner's old address."""
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="{target}">
<meta http-equiv="refresh" content="0; url={target}">
<script>{THEME_BOOT}
location.replace('{target}' + location.search + location.hash);</script>
<style>{TOKENS}
body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55
  system-ui,-apple-system,"Segoe UI",sans-serif; padding:26px 18px; }}
a {{ color:inherit; }}</style>
<p>{says}</p>
"""


def root_redirect() -> str:
    """`public/index.html`: the site's root, sending a reader on to the flights."""
    return redirect("flights/", "parainsights",
                    'The flights are at <a href="flights/">flights/</a>.')


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
            parts.append(f'<a href="{up}{where}">{label}</a>')
    parts.append(strip_end())
    return f'<nav class="site-nav" aria-label="The tools here">{"".join(parts)}</nav>'


# The welcome: a modal on a browser's first visit to any of the three pages, a card per
# tool (October 2026, the pilot's pick of a mock). Each card's picture is drawn in the
# tokens, not a screenshot: it holds in both themes and does not go stale when a page
# changes. Only on the published site (`js/welcome.js`); `?welcome` shows it anywhere.
_PICTURES = {
    "meteo": """
      <path d="M24 92 C 60 88, 80 60, 110 50 S 150 64, 174 80 L174 104 L24 104 Z" fill="var(--climb-1)" opacity=".5"/>
      <rect x="24" y="18" width="150" height="86" fill="var(--sink-1)" opacity=".3" rx="4"/>
      <path d="M24 92 C 60 88, 80 60, 110 50 S 150 64, 174 80" fill="none" stroke="var(--series-1)" stroke-width="2.5"/>
      <path d="M24 60 C 70 56, 110 44, 174 52" fill="none" stroke="var(--ink-2)" stroke-width="1.5" stroke-dasharray="4 4"/>
      <line x1="110" y1="18" x2="110" y2="104" stroke="var(--ink)" stroke-width="1.2" stroke-dasharray="2 3"/>
      <path d="M40 30l10 6M70 28l10 4M140 28l10 2M40 76l8 8M140 74l9 6" stroke="var(--ink-2)" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M196 18 V104 H300" fill="none" stroke="var(--rule)" stroke-width="1.5"/>
      <path d="M282 104 L250 58 L262 22" fill="none" stroke="var(--climb)" stroke-width="2.5"/>
      <path d="M232 104 L220 60 L206 24" fill="none" stroke="var(--sink)" stroke-width="2.5" stroke-dasharray="4 3"/>
      <path d="M282 104 L246 52" stroke="var(--ink-2)" stroke-width="1.2" stroke-dasharray="3 3"/>
      <circle cx="250" cy="58" r="5" fill="none" stroke="var(--ink)" stroke-width="2"/>
      <text class="w-cap" x="24" y="126">wind · thermal top · cloudbase</text>""",
    "airspace": """
      <path d="M0 108 L40 92 L80 100 L120 78 L160 90 L210 70 L260 88 L320 76 L320 140 L0 140Z" fill="var(--shadow-ink)" opacity=".7"/>
      <path d="M196 34 L262 26 L262 76 L196 84 Z" fill="var(--bad)" fill-opacity=".16" stroke="var(--bad)" stroke-width="1.6"/>
      <path d="M196 34 L222 44 L288 36 L262 26 M222 44 L222 94 M288 36 L288 86 L262 76" fill="none" stroke="var(--bad)" stroke-width="1.2" opacity=".7"/>
      <path d="M58 98 L150 36 L178 104 Z" fill="var(--accent)" fill-opacity=".12" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round"/>
      <g fill="var(--panel)" stroke="var(--accent)" stroke-width="2.5">
        <circle cx="58" cy="98" r="6"/><circle cx="150" cy="36" r="6"/><circle cx="178" cy="104" r="6"/></g>
      <text x="80" y="62" font-weight="700">96 km</text>
      <text class="w-cap" x="24" y="126">task · score · airspace it crosses</text>""",
    "flights": """
      <path d="M0 112 L50 96 L100 106 L150 84 L210 100 L260 86 L320 98 L320 140 L0 140Z" fill="var(--shadow-ink)" opacity=".7"/>
      <path d="M24 100 C 50 96, 60 88, 76 84" fill="none" stroke="var(--neutral)" stroke-width="2.5"/>
      <g fill="none" stroke-width="2.5">
        <ellipse cx="86" cy="80" rx="12" ry="4" stroke="var(--climb-1)"/>
        <ellipse cx="88" cy="66" rx="12" ry="4" stroke="var(--climb-2)"/>
        <ellipse cx="90" cy="52" rx="12" ry="4" stroke="var(--climb-3)"/>
        <ellipse cx="92" cy="38" rx="12" ry="4" stroke="var(--climb-2)"/>
        <ellipse cx="206" cy="64" rx="11" ry="4" stroke="var(--climb-1)"/>
        <ellipse cx="208" cy="52" rx="11" ry="4" stroke="var(--climb-2)"/>
        <ellipse cx="210" cy="40" rx="11" ry="4" stroke="var(--climb-3)"/></g>
      <path d="M104 38 C 140 44, 170 58, 196 66" fill="none" stroke="var(--sink-2)" stroke-width="2.5"/>
      <path d="M221 40 C 250 48, 276 60, 296 74" fill="none" stroke="var(--sink-1)" stroke-width="2.5"/>
      <circle cx="296" cy="74" r="4.5" fill="var(--ink)"/>
      <text class="w-cap" x="24" y="126">climbs · glides · debrief</text>""",
}

# key → the question it answers and three bullets; the label and the address are `PAGES`'.
WELCOME = {
    "meteo": ("Is it worth driving anywhere today, and where?", [
        "Compare any takeoffs side by side, four days ahead",
        "Wind by hour and height, the thermal top and the cloudbase",
        "The sounding, and flymet's meteogram for the nearest airfield"]),
    "airspace": ("What is that task worth, and what does it cross?", [
        "Draw a task on a 3D map and see its XContest score",
        "Every airspace it crosses, floor to ceiling, plus Czech ATZs and circuits",
        "Export to XCTrack, sun and wind for your takeoff time"]),
    "flights": ("How did that flight go?", [
        "Drop in your IGC or KMZ; it is analysed in your browser, nothing is uploaded",
        "Every climb and glide, the wind you flew in, a replay in 3D",
        "A debrief of where the flight lost time and height; compare with friends"]),
}

WELCOME_STYLE = """
.welcome { border: 0; padding: 0; background: transparent; color: var(--ink); width: 100%;
  max-width: min(1040px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); }
.welcome::backdrop { background: rgba(10, 10, 9, .55); backdrop-filter: blur(2px); }
.welcome .w-box { position: relative; padding: 26px 28px 24px; background: var(--paper);
  border: 1px solid var(--rule); border-radius: 14px; box-shadow: 0 18px 60px rgba(0,0,0,.4); }
.welcome h2 { margin: 0; padding-right: 52px; font-size: 26px; line-height: 1.2; font-weight: 700; }
.welcome .w-lead { margin: 6px 0 22px; color: var(--ink-2); max-width: 60ch; }
.welcome .w-close { position: absolute; top: 14px; right: 14px; }
.welcome .w-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 0;
  padding: 0; list-style: none; }
.welcome .w-card { display: flex; flex-direction: column; overflow: hidden; background: var(--panel);
  border: 1px solid var(--rule); border-radius: 14px; }
.welcome .w-card.is-here { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.welcome .w-pic { display: block; width: 100%; height: auto; background: var(--panel-2);
  border-bottom: 1px solid var(--rule); }
.welcome .w-pic text { font-family: inherit; font-size: 15px; fill: var(--ink-2); }
.welcome .w-pic text:not(.w-cap) { fill: var(--ink); }
.welcome .w-body { display: flex; flex-direction: column; flex: 1; padding: 14px 18px 16px; }
.welcome h3 { display: flex; align-items: center; gap: 10px; margin: 0; font-size: 19px; line-height: 1.3; }
.welcome .w-q { margin: 2px 0 10px; color: var(--ink-2); font-size: 15.5px; }
.welcome .w-pts { margin: 0 0 14px; padding: 0 0 0 18px; font-size: 15.5px; line-height: 1.5; }
.welcome .w-pts li + li { margin-top: 4px; }
.welcome .w-go { margin-top: auto; align-self: flex-start; }
.welcome .w-foot { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  flex-wrap: wrap; margin: 20px 0 0; }
.welcome .w-foot p { margin: 0; color: var(--ink-2); font-size: 15px; }
@media (max-width: 860px) {
  .welcome .w-box { padding: 20px 16px 16px; }
  .welcome h2 { font-size: 22px; }
  .welcome .w-cards { grid-template-columns: 1fr; gap: 12px; }
  .welcome .w-pic { height: 96px; }
  .welcome .w-cap { display: none; }
  .welcome .w-foot .btn { width: 100%; }
}
"""
STYLE += WELCOME_STYLE


def welcome(current: str, depth: int = 1) -> str:
    """The welcome dialog, closed; `js/welcome.js` opens it on a first visit. The card
    for `current` is marked and closes the dialog; the others link to their pages."""
    up = "../" * depth
    cards = []
    for key, label, where in PAGES:
        question, points = WELCOME[key]
        here = key == current
        go = ('<button class="w-go lnk">Start here</button>' if here else
              f'<a class="w-go lnk" href="{up}{where}">Open {"the " if key == "airspace" else ""}'
              f'{label} {icon(ICONS["arrow"], 18)}</a>')
        badge = ' <span class="badge accent">You are here</span>' if here else ""
        cards.append(
            f'<li class="w-card{" is-here" if here else ""}">'
            '<svg class="w-pic" viewBox="0 0 320 140" preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
            f'{_PICTURES[key]}</svg>'
            f'<div class="w-body"><h3>{label}{badge}</h3><p class="w-q">{question}</p>'
            f'<ul class="w-pts">{"".join(f"<li>{p}</li>" for p in points)}</ul>{go}</div></li>')
    return (
        '<dialog class="welcome" id="welcome" aria-labelledby="welcome-title">'
        '<form method="dialog" class="w-box">'
        f'<button class="tool w-close" aria-label="Close">{icon(ICONS["close"])}</button>'
        '<h2 id="welcome-title">Welcome to parainsights</h2>'
        '<p class="w-lead">Free tools for paraglider pilots, one for each part of the day: is it '
        'worth going, what to fly, and how it went.</p>'
        f'<ul class="w-cards">{"".join(cards)}</ul>'
        '<div class="w-foot"><p>The tabs at the top of every page switch between the three.</p>'
        '<button class="btn primary">Got it</button></div>'
        '</form></dialog>')

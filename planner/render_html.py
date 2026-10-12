"""The planner: draw a task on the map you will actually fly it over.

It is no longer a page of its own. The planner and the airspace map were two tabs
drawing the same airspace over the same ground, so the planner is now a section of the
airspace article (`airspaces.render_html.body`): its bar sits over the map, its figures
and crossings under it, and `planner/cli.py` only writes a redirect for old links.

flyxc.app is the reference, and the thing worth copying from it is that the route is
drawn on a real map and scored as you drag it. What this one adds — because both halves
already live in this repository — is that the map underneath is the **airspace** map: a
line that looks 60 km long and crosses a TMA is not a plan, and on a bare basemap you
cannot see that.

Nothing here re-implements the 3D map or the airspace layer. The planner is a *layer
over* the map (`parainsights_map.map3d`): it hands the route over with `setRoute` and
the FAI areas with `setShapes`, and takes clicks back with `onClick`. The map draws the
course with the same code that draws a flight's, so the two cannot disagree about where
a line on this map is.

The scoring rules are XContest's and are `tracklog_viewer/js/xc.js`'s, read from it with
their constants asserted against it by a test: every side at least 28% of the perimeter
for FAI, a closing gap under 20% of the perimeter for a closed course, and multipliers
1.0 / 1.2 / 1.4. A planner that scored a task differently from the report that later
measures the flight would be worse than no planner.
"""

from __future__ import annotations

import json

import re
from pathlib import Path
from types import SimpleNamespace


def _scoring() -> SimpleNamespace:
    """XContest's constants as the report's scorer holds them, read from `js/xc.js`: the
    planner must score a task exactly as the flight it becomes will be scored, and that
    scorer is the JavaScript. Read, not retyped, so the two cannot drift."""
    source = (Path(__file__).parent.parent / "tracklog_viewer" / "js" / "xc.js").read_text(
        encoding="utf-8")

    def number(name):
        return float(re.search(rf"var {name} = ([0-9.]+);", source).group(1))

    multipliers = re.search(r"var MULTIPLIER = \{([^}]*)\}", source).group(1)
    return SimpleNamespace(
        FAI_MIN_SIDE=number("FAI_MIN_SIDE"), MAX_CLOSING=number("MAX_CLOSING"),
        MULTIPLIER={k: float(v) for k, v in re.findall(r"(\w+): ([0-9.]+)", multipliers)})


xc = _scoring()

STYLE = """
.plan-bar { display:flex; gap:8px; margin:14px 0 10px; flex-wrap:wrap; }
.plan-bar .btn { padding:0 14px; }
.plan-draw[aria-pressed="true"] { background:var(--ink); color:var(--paper); border-color:var(--ink); }
.plan-opts { display:flex; flex-wrap:wrap; gap:10px 16px; align-items:center; margin:0 0 6px; }
.chk { display:inline-flex; align-items:center; gap:9px; font-size:16px; cursor:pointer; min-height:44px; }
.chk input { width:20px; height:20px; margin:0; accent-color:var(--accent); }
.plan-opts select.btn { height:44px; padding:0 12px; appearance:auto; }
.sr { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); }
.plan-hint[hidden] { display:none; }
/* The score: the distance large, the rest as a line under it. The cells are the script's
   (`report` in planner.js), labelled in lower case; the first letter is raised here. */
/* The task's length on a line of its own, then score, multiplier, turnpoints and shape,
   each kept whole and wrapping as whole figures where a phone runs out of width. */
.plan-figures { display:flex; flex-wrap:wrap; gap:4px 18px; margin:2px 0 0; }
.plan-figures div { display:flex; flex-direction:column; }
.plan-figures div:first-child { flex-basis:100%; }
.plan-figures .v, .plan-shape { white-space:nowrap; }
/* The shape: a pill at the panel's top right, beside "Task", not a fifth figure. */
.plan-figures .plan-shape-cell { position:absolute; top:16px; right:20px; }
.plan-figures .plan-shape-cell .k { display:none; }
@media (max-width: 900px) { .plan-figures .plan-shape-cell { right:14px; } }
.plan-figures div:first-child .v { font-size:38px; font-weight:700; line-height:1.1; }
.plan-figures div:first-child .k { display:none; }
.plan-figures .k { font-size:15px; color:var(--ink-2); }
.plan-figures .k::first-letter, .plan-shape::first-letter { text-transform:uppercase; }
.plan-figures .v { font-size:17px; font-weight:600; font-variant-numeric:tabular-nums; }
.plan-shape { display:inline-block; padding:2px 10px; border-radius:999px; font-size:15px; font-weight:600;
  border:1.5px solid var(--edge); color:var(--ink-2); }
.plan-shape.is-fai { background:var(--good); border-color:var(--good); color:var(--on-good); }
.plan-shape.is-flat { background:var(--warn); border-color:var(--warn); color:var(--on-warn); }
/* A wrapping row: the sides are spans with nothing between them, so as inline text the
   line had nowhere to break and ran off a phone. */
.plan-legs { margin:8px 0 0; font-size:15px; color:var(--ink-2); font-variant-numeric:tabular-nums;
  display:flex; flex-wrap:wrap; gap:2px 14px; }
.plan-legs:empty { display:none; }
.plan-legs span { white-space:nowrap; }
.plan-airspace { margin:10px 0 0; }
.plan-crossed-head { margin:0 0 4px; font-size:15px; color:var(--ink-2); }
.plan-crossed-head::first-letter { text-transform:uppercase; }
.plan-clear { margin:0; font-size:15px; color:var(--ink-2); }
.plan-crossed { list-style:none; margin:0; padding:0; max-height:12em; overflow-y:auto; }
.plan-crossed li { display:flex; align-items:baseline; gap:9px; padding:9px 0; border-top:1px solid var(--rule); font-size:16px; }
.plan-swatch { width:11px; height:11px; border-radius:50%; flex:none; transform:translateY(1px); }
.plan-crossed-name { flex:1; min-width:0; }
.plan-crossed-km { color:var(--ink-2); font-size:15px; white-space:nowrap; font-variant-numeric:tabular-nums; }
.plan-crossed li.is-shut .plan-crossed-name { color:var(--ink-2); }
.plan-when { font-size:15px; font-weight:600; padding:1px 9px; border-radius:999px; white-space:nowrap; flex:none; }
.plan-when::first-letter { text-transform:uppercase; }
.plan-when.is-open { background:var(--good); color:var(--on-good); }
.plan-when.is-shut { border:1.5px solid var(--edge); color:var(--ink-2); }
.plan-section { margin:0; }
.plan-note { margin:12px 0 0; font-size:15px; color:var(--ink-2); }
.plan-xct { display:flex; flex-wrap:wrap; align-items:center; gap:6px 8px; margin:14px 0 0;
  padding-top:12px; border-top:1px solid var(--rule); }
.plan-xct[hidden], .plan-split[hidden] { display:none; }
.plan-import .btn svg:last-child { margin-left: -2px; }
.plan-xct-dlg-body label { display:block; margin:0 0 8px; color:var(--ink); font-weight:600; }
.plan-imp-code { font:inherit; font-size:24px; letter-spacing:.12em; text-transform:uppercase; width:8ch;
  height:48px; padding:0 12px; border:1px solid var(--edge); border-radius:10px; background:var(--paper); color:var(--ink); }
.plan-imp-row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.plan-imp-video { display:block; width:100%; max-height:52vh; border-radius:10px; background:#000; object-fit:cover; }
.plan-imp-say { margin:10px 0 0; }
.plan-imp-say.is-error { color:var(--climb); }
.plan-split { display:inline-flex; position:relative; }
.plan-split-main { border-radius:10px 0 0 10px; }
.plan-split-more { border-radius:0 10px 10px 0; margin-left:-1px; padding:0 10px; }
.plan-split-menu { position:absolute; bottom:calc(100% + 6px); left:0; z-index:8; min-width:250px; padding:6px;
  background:var(--panel); border:1px solid var(--edge); border-radius:12px; box-shadow:0 12px 30px rgba(0,0,0,.3); }
.plan-split-menu[hidden] { display:none; }
.plan-split-menu button { display:flex; align-items:center; gap:10px; width:100%; text-align:left; background:none; border:0;
  color:var(--ink); font:inherit; font-size:16px; padding:10px 12px; border-radius:8px; cursor:pointer; }
.plan-split-menu button:hover, .plan-split-menu button:focus-visible { background:var(--panel-2); }
.plan-xct-out { flex-basis:100%; margin:0; font-size:15px; color:var(--ink-2); }
.plan-xct-out:empty { display:none; }
.plan-xct-dlg { width:min(420px, 92vw); padding:0; border:1px solid var(--edge); border-radius:14px;
  background:var(--panel); color:var(--ink); box-shadow:0 18px 44px rgba(0,0,0,.45); }
.plan-xct-dlg::backdrop { background:rgba(0,0,0,.55); }
.plan-xct-dlg-head { display:flex; justify-content:space-between; align-items:center; gap:10px; padding:14px 16px 0; }
.plan-xct-dlg-head h2 { margin:0; font-size:19px; }
.plan-xct-dlg-sub { margin:4px 16px 12px; font-size:15px; color:var(--ink-2); }
.plan-xct-dlg-body { padding:0 16px 18px; font-size:15.5px; color:var(--ink-2); }
.plan-xct-code { display:block; margin:6px 0 8px; font-size:40px; font-weight:700; letter-spacing:.12em;
  color:var(--ink); font-variant-numeric:tabular-nums; text-align:center; }
.plan-xct-qr { display:block; width:min(280px, 100%); height:auto; margin:0 auto 10px; background:#fff;
  padding:10px; border-radius:10px; box-sizing:border-box; }
[data-planner][data-drawing="on"] .maplibregl-canvas-container.maplibregl-interactive { cursor:crosshair; }
"""


def controls() -> str:
    """The task tools, in the Task panel over the map. Drawing is a mode, off until asked
    for: the same map is the airspace map, where a tap on a phone names the zone under the
    finger, and a tap that also dropped a turnpoint would make the one gesture mean two."""
    import parainsights_common as common

    return (
        '<div class="plan-bar">'
        f'<button type="button" class="btn primary plan-draw" id="plan-draw" aria-pressed="false">'
        "Draw a task</button>"
        '<button type="button" class="btn" id="plan-undo">Undo</button>'
        '<button type="button" class="btn" id="plan-clear">Clear</button>'
        "</div>"
        '<div class="plan-opts">'
        '<label class="chk"><input type="checkbox" id="plan-close"> Closed</label>'
        '<label class="chk"><input type="checkbox" id="plan-fai" checked> FAI areas'
        + common.info("Where each turnpoint can go for an FAI triangle (every side at least "
                      "28% of the perimeter), the other two staying put: turnpoint 1 green, "
                      "2 blue, 3 red. Yellow: where a closed course must finish.")
        + '</label>'
        '<label class="plan-rules-label"><span class="sr">Rules</span><select id="plan-rules" class="btn">'
        '<option value="world">XContest</option>'
        '<option value="cpp">ČPP (Czech)</option></select></label>'
        "</div>"
        # Said only before the first point: the button itself turns into "Drawing — click
        # the map" once pressed.
        '<span class="plan-hint" id="plan-hint" hidden></span>'
    )


# Import: an arrow into a tray; the code and QR glyphs as the export menu draws them.
IMPORT_ICON = '<path d="M10 3v9M6 8.5l4 4 4-4"/><path d="M3.5 12.5v4h13v-4"/>'
FILE_ICON = '<path d="M5.5 2.5h6l4 4v11h-10z"/><path d="M11.5 2.5v4h4"/>'
CODE_ICON = '<path d="M4 7h12M4 13h12M8 3.5 6.5 16.5M13.5 3.5 12 16.5"/>'
QR_ICON = ('<rect x="3" y="3" width="5" height="5" rx="1"/><rect x="12" y="3" width="5" height="5" rx="1"/>'
           '<rect x="3" y="12" width="5" height="5" rx="1"/><path d="M12 12h2v2M17 12v1M12 17h1M15 15h2v2"/>')

XCT_HELP = ("The route as an XCTrack waypoints task: the turnpoints in order, with the "
            "ground's height under each, no cylinders. <b>File</b>: a .xctsk file — on the "
            "phone XCTrack runs on, open it from the download and choose XCTrack. "
            "<b>Task code</b>: the task is stored with XContest for a month and you get four "
            "letters to import it by in XCTrack. <b>QR code</b>: to scan from this screen "
            "with XCTrack's task import. The code and the QR code send the route to "
            "XContest's task service (tools.xcontest.org); the file stays on your device. "
            "<b>Import</b> takes a task back the same three ways — an .xctsk file, an "
            "XContest task code, or a QR code scanned with the camera or from a photo — and "
            "replaces the route drawn.")


def results() -> str:
    """What the drawn route is worth and what it crosses, in the Task panel."""
    import parainsights_common as common

    rules = (f"Scored with the same rules as the flight report: every side at least "
             f"{xc.FAI_MIN_SIDE:.0%} of the perimeter for FAI, a closing gap under "
             f"{xc.MAX_CLOSING:.0%} of it for a closed course, multipliers "
             f"{xc.MULTIPLIER['open']:g}&thinsp;/&thinsp;{xc.MULTIPLIER['flat']:g}&thinsp;/&thinsp;{xc.MULTIPLIER['fai']:g}. "
             "With ČPP chosen, the Czech cup's: closing under 5%, and in the Central European "
             "zone 1&thinsp;/&thinsp;1.8&thinsp;/&thinsp;2.2 "
             '(<a href="https://www.xcontest.org/cesko/pravidla/" rel="noreferrer">rules</a>). '
             "The map draws the airspace within 5&nbsp;km of the task, and none before "
             "there is one: Czechia's from this page, with its traffic circuits; any other "
             "European country's from openAIP once the task reaches it.")
    return f"""<section class="plan-section" aria-label="The task">
    <div class="plan-figures" id="plan-figures"></div>
    <p class="plan-legs" id="plan-legs"></p>
    <div class="plan-airspace" id="plan-airspace"></div>
    <p class="plan-note">A plan, not a clearance.{common.info(rules, "How the task is scored")}</p>
    <!-- To XCTrack: one split button at the panel's foot, the device's best way first
         (`xctMethods` in planner.js); a QR code or a task code opens in the dialog. -->
    <div class="plan-xct" id="plan-xct">
      <div class="plan-split plan-import">
        <button type="button" class="btn" id="plan-imp-more" aria-haspopup="menu" aria-expanded="false"
                title="Import a task from XCTrack">{common.icon(IMPORT_ICON)}Import{common.icon(common.ICONS["down"])}</button>
        <div class="plan-split-menu" id="plan-imp-menu" role="menu" hidden>
          <button type="button" role="menuitem" data-import="file">{common.icon(FILE_ICON)}.xctsk file</button>
          <button type="button" role="menuitem" data-import="code">{common.icon(CODE_ICON)}Task code (XContest)</button>
          <button type="button" role="menuitem" data-import="qr">{common.icon(QR_ICON)}Scan a QR code</button>
        </div>
        <input type="file" id="plan-imp-file" accept=".xctsk,application/xctsk,application/json,text/plain" hidden>
      </div>
      <div class="plan-split plan-export" id="plan-xct-export" hidden>
        <button type="button" class="btn plan-split-main" id="plan-xct-main"></button>
        <button type="button" class="btn plan-split-more" id="plan-xct-more" aria-haspopup="menu"
                aria-expanded="false" aria-label="Other ways to XCTrack">{common.icon(common.ICONS["down"])}</button>
        <div class="plan-split-menu" id="plan-xct-menu" role="menu" hidden></div>
      </div>{common.info(XCT_HELP, "Sending the task to XCTrack")}
      <p class="plan-xct-out" id="plan-xct-out" role="status"></p>
    </div>
    <dialog class="plan-xct-dlg" id="plan-xct-dlg" aria-labelledby="plan-xct-title">
      <div class="plan-xct-dlg-head"><h2 id="plan-xct-title">Send the task to XCTrack</h2>
        <button type="button" class="tool" id="plan-xct-close" aria-label="Close">{common.icon(common.ICONS["close"])}</button></div>
      <p class="plan-xct-dlg-sub" id="plan-xct-sub"></p>
      <div class="plan-xct-dlg-body" id="plan-xct-body"></div>
    </dialog>
    <script type="application/json" id="plan-coverage">{_coverage()}</script>
  </section>"""


def body(uid: str = "planner", *, scene_panel: str = "") -> str:
    """The planner on its own over a given panel — the shape the airspace article puts
    together, kept for a caller that has no airspace overlay to build (the tests)."""
    from airspaces import render_html as airspace_html

    return f"""<article class="flight airspace-article" id="{uid}-article" data-planner>
  {airspace_html.when_control()}
  {controls()}
  <div class="asp-holder">
    {scene_panel}
    <div class="asp-name" id="asp-name"></div>
  </div>
  {results()}
</article>"""


def _coverage() -> str:
    """Where the airspace on this map is complete: the Czech border, as a ring the page
    can test a leg against. Outside it the map has no airspace, and a route there crosses
    "nothing" only in the sense that nothing was looked for."""
    from airspaces import basemap as border

    return json.dumps({"name": "Czechia",
                       "lon": [lon for _, lon in border.BORDER],
                       "lat": [lat for lat, _ in border.BORDER]},
                      separators=(",", ":"))


# The constants are interpolated from `js/xc.js` rather than typed, so the planner cannot
# drift from the scorer that later measures the flight. A hand-written 0.28 here would go
# stale the moment FAI_MIN_SIDE moved, in the one place that exists to agree with it.
SCRIPT = (
    (Path(__file__).parent / "js/planner.js").read_text(encoding="utf-8")
    .replace("__FAI_MIN_SIDE__", str(xc.FAI_MIN_SIDE))
    .replace("__MAX_CLOSING__", str(xc.MAX_CLOSING))
    .replace("__MULTIPLIER__", "{" + ", ".join(f"{name}: {value}" for name, value in xc.MULTIPLIER.items()) + "}")
)

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
/* Draw is the accent on or off; pressed, it says Done and carries a ring. */
.merged-view .plan-draw { background:var(--accent); border-color:var(--accent); color:var(--on-accent); }
.merged-view .plan-draw:hover { background:var(--accent); filter:brightness(1.06); }
.merged-view .plan-draw[aria-pressed="true"] { background:var(--accent); border-color:var(--accent);
  color:var(--on-accent); box-shadow:0 0 0 3px var(--paper), 0 0 0 5px var(--accent); }
.merged-view .plan-mapbar button:disabled { cursor:default; background:var(--float); }
.merged-view .plan-mapbar button:disabled svg { opacity:.35; }
.chk { display:inline-flex; align-items:center; gap:9px; font-size:16px; cursor:pointer; min-height:44px; }
.chk input { width:20px; height:20px; margin:0; accent-color:var(--accent); }
.sr { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); }
.plan-hint[hidden] { display:none; }
/* The strip under the map, edge to edge as the map is, its content on the page's
   column: the score, the options, the takeoff time — three groups on one line on a
   desktop, divided by a hairline, one under another on a phone. No ⓘ in it: what each
   control does is its title. */
.plan-strip { display:flex; flex-wrap:wrap; align-items:center; gap:10px 28px; position:relative; z-index:1;
  margin:0 calc(50% - (100vw - var(--scrollbar, 0px)) / 2);
  padding:12px calc((100vw - var(--scrollbar, 0px)) / 2 - 50%) 12px;
  background:var(--panel); border-bottom:1px solid var(--rule); }
.plan-strip-score { flex:0 1 auto; min-width:0; }
.plan-strip .plan-opts { margin:0; flex:0 1 auto; display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.plan-strip .plan-takeoff { margin:0 0 0 auto; flex:0 1 420px; }
.plan-strip .plan-hint:not([hidden]) { flex-basis:100%; }
@media (min-width: 901px) {
  .plan-strip .plan-opts, .plan-strip .plan-takeoff { padding-left:28px; border-left:1px solid var(--rule); }
}
@media (max-width: 900px) {
  .plan-strip { gap:10px; }
  .plan-strip > * { flex-basis:100% !important; }
}
/* The score: the distance large with its shape, then one quiet line. */
.plan-figures { display:grid; gap:2px; }
.plan-row { display:flex; flex-wrap:wrap; align-items:baseline; }
.plan-row-head { align-items:center; gap:4px 10px; }
.plan-row-head .k, .plan-row-sub .k, .plan-fig-turnpoints { display:none !important; }
.plan-row-head .v:first-child, .plan-row-head > div:first-child .v { font-size:30px; font-weight:700; line-height:1.1;
  font-variant-numeric:tabular-nums; white-space:nowrap; }
.plan-row-sub { font-size:15px; color:var(--ink-2); font-variant-numeric:tabular-nums; }
.plan-row-sub > div, .plan-legs > span { white-space:nowrap; }
.plan-row-sub .v { font-weight:500; }
.plan-row-sub > div + div::before, .plan-row-sub .plan-legs > span::before { content:"·"; padding:0 8px; }
.plan-legs { display:contents; }
.plan-figures .plan-row-sub > div { display:inline; }
@media (max-width: 900px) {
  .plan-row-sub .plan-legs { display:flex; flex-wrap:wrap; flex-basis:100%; }
  .plan-row-sub .plan-legs > span:first-child::before { content:none; }
}
.plan-row-hint b { color:var(--ink); }
.plan-shape { display:inline-block; padding:2px 10px; border-radius:999px; font-size:14px; font-weight:600;
  border:1.5px solid var(--edge); color:var(--ink-2); white-space:nowrap; }
.plan-shape::first-letter { text-transform:uppercase; }
.plan-shape.is-fai { background:var(--good); border-color:var(--good); color:var(--on-good); }
.plan-shape.is-flat { background:var(--warn); border-color:var(--warn); color:var(--on-warn); }
.plan-figures div { display:inline-flex; gap:5px; align-items:baseline; }
/* Toggles as chips, filled when on; the rules as a pill of the same height. */
.plan-chip { position:relative; display:inline-flex; align-items:center; height:38px; padding:0 14px;
  border:1px solid var(--edge); border-radius:999px; background:var(--panel); color:var(--ink);
  font-size:15px; font-weight:600; cursor:pointer; user-select:none; }
.plan-chip input { position:absolute; opacity:0; width:1px; height:1px; margin:0; }
.plan-chip:hover { background:var(--panel-2); }
.plan-chip:has(input:checked) { background:var(--ink); border-color:var(--ink); color:var(--paper); }
.plan-chip:has(input:focus-visible), .plan-select:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.plan-select { height:38px; padding:0 12px; border:1px solid var(--edge); border-radius:999px;
  background:var(--panel); color:var(--ink); font:600 15px "Noto Sans", ui-sans-serif, system-ui, sans-serif; }
/* The takeoff on one line: its day, the time slid through it, the time. */
.plan-takeoff { display:grid; grid-template-columns:auto auto minmax(80px, 1fr) auto; align-items:center;
  gap:10px; font-size:15px; color:var(--ink-2); }
.plan-field { height:38px; padding:0 10px; box-sizing:border-box; font:inherit; color:var(--ink); min-width:0;
  border:1px solid var(--edge); border-radius:10px; background:var(--panel); }
#plan-time { width:100%; margin:0; accent-color:var(--accent); }
#plan-time-out { font-variant-numeric:tabular-nums; font-weight:600; color:var(--ink); min-width:3em; text-align:right; }
/* Under the strip: to and from XCTrack, then what the task crosses. */
.plan-section { margin:18px 0 0; display:grid; gap:14px; }
.plan-section .plan-crossed-head { font-size:20px; font-weight:700; color:var(--ink); margin:0 0 6px; }
.plan-section .plan-crossed { max-height:none; overflow:visible; }
.plan-section .plan-xct { margin:0; padding:0; border:0; }
.plan-section .plan-airspace { margin:0; }
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
.plan-split-menu { position:absolute; top:calc(100% + 6px); left:0; z-index:8; min-width:250px; padding:6px;
  background:var(--panel); border:1px solid var(--edge); border-radius:12px; box-shadow:0 12px 30px rgba(0,0,0,.3); }
.plan-split-menu[hidden] { display:none; }
.plan-split-menu button { display:flex; align-items:center; gap:10px; width:100%; text-align:left; background:none; border:0;
  color:var(--ink); font:inherit; font-size:16px; padding:10px 12px; border-radius:8px; cursor:pointer; }
.plan-split-menu button:hover, .plan-split-menu button:focus-visible { background:var(--panel-2); }
/* Kept in this browser: the export menu's last item, and the import menu's list. */
.plan-menu-keep { border-top:1px solid var(--rule) !important; border-radius:0 0 8px 8px; margin-top:4px; }
.plan-saved { max-height:min(50vh, 360px); overflow-y:auto; }
.plan-saved[hidden] { display:none; }
.plan-saved-head { margin:6px 0 2px; padding:8px 10px 0; border-top:1px solid var(--rule); font-size:14px;
  font-weight:600; color:var(--ink-2); }
.plan-saved-row { display:flex; align-items:center; }
.plan-split-menu .plan-saved-load { flex:1; min-width:0; }
.plan-saved-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.plan-saved-load small { margin-left:auto; color:var(--ink-2); font-size:13px; white-space:nowrap; }
.plan-split-menu .plan-saved-drop { width:40px; flex:none; justify-content:center; color:var(--ink-2); padding:0; }
.plan-keep-name { font:inherit; font-size:18px; height:44px; padding:0 12px; min-width:0; flex:1 1 220px;
  border:1px solid var(--edge); border-radius:10px; background:var(--panel); color:var(--ink); }
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


# The rules the task is scored by, on the rules pill's title — from `js/xc.js`'s own
# constants, so the page cannot state rules it does not score by.
RULES_TITLE = (f"XContest: FAI when every side is at least {xc.FAI_MIN_SIDE:.0%} of the "
               f"perimeter, closed when the gap is under {xc.MAX_CLOSING:.0%} of it, "
               f"multipliers {xc.MULTIPLIER['open']:g} / {xc.MULTIPLIER['flat']:g} / "
               f"{xc.MULTIPLIER['fai']:g} (open / flat / FAI). ČPP, the Czech cup: closed "
               "under 5%, and in the Central European zone 1 / 1.8 / 2.2.")


def controls() -> str:
    """The task tools, in the Task panel over the map. Drawing is a mode, off until asked
    for: the same map is the airspace map, where a tap on a phone names the zone under the
    finger, and a tap that also dropped a turnpoint would make the one gesture mean two."""
    import parainsights_common as common

    return (
        '<div class="plan-opts">'
        '<label class="plan-chip" title="Score the task as a closed course: it must end near '
        'where it starts"><input type="checkbox" id="plan-close">Closed</label>'
        '<label class="plan-chip" title="Where each turnpoint can go for an FAI triangle (every '
        'side at least 28% of the perimeter), the other two staying put: turnpoint 1 green, 2 '
        'blue, 3 red. Yellow: where a closed course must finish.">'
        '<input type="checkbox" id="plan-fai" checked>FAI areas</label>'
        f'<label class="plan-rules-label" title="{RULES_TITLE}"><span class="sr">Rules</span>'
        '<select id="plan-rules" class="plan-select">'
        '<option value="world">XContest</option>'
        '<option value="cpp">ČPP (Czech)</option></select></label>'
        "</div>"
        '<div class="plan-takeoff" title="Slide through the day: the ground is shaded from where '
        'the sun stands (strongest on the Relief ground), and the rose shows the sun and the '
        'forecast wind at about 1500 m. Your own clock; the aerodrome hours follow it.">'
        '<label for="plan-day">Takeoff</label>'
        '<input type="date" id="plan-day" class="plan-field">'
        '<input type="range" id="plan-time" min="300" max="1260" step="15" value="720" '
        'aria-label="Time of day">'
        '<output id="plan-time-out" for="plan-time">12:00</output>'
        "</div>"
        # Said only before the first point: the button itself turns into "Drawing — click
        # the map" once pressed.
        '<span class="plan-hint" id="plan-hint" hidden></span>'
    )


UNDO_ICON = '<path d="M7.5 5 4 8.5 7.5 12"/><path d="M4 8.5h8a4 4 0 0 1 0 8H9"/>'
REDO_ICON = '<path d="M12.5 5 16 8.5 12.5 12"/><path d="M16 8.5H8a4 4 0 0 0 0 8h3"/>'
CLEAR_ICON = ('<path d="M3.5 5.5h13M8 5.5V3.5h4v2"/>'
              '<path d="M5.5 5.5l.8 11h7.4l.8-11M8.5 8.5v5M11.5 8.5v5"/>')


def map_bar() -> str:
    """The drawing tools, on the map at the middle of its foot (`map3d` moves
    `.m3-bottom-extra` there): Draw, in the accent whether on or off, and undo, redo and
    clear as icons. They were buttons in the Task panel until October 2026."""
    import parainsights_common as common

    def tool(id_, icon, label):
        return (f'<button type="button" id="{id_}" class="m3-icon" title="{label}" '
                f'aria-label="{label}">{common.icon(icon)}</button>')

    return (
        '<div class="m3-bottom-extra plan-mapbar" hidden>'
        '<button type="button" class="plan-draw" id="plan-draw" aria-pressed="false">'
        f'{common.icon(common.ICONS["pencil"])}<span>Draw</span></button>'
        '<div class="view3d-seg" role="group" aria-label="Edit the task">'
        + tool("plan-undo", UNDO_ICON, "Undo")
        + tool("plan-redo", REDO_ICON, "Redo")
        + tool("plan-clear", CLEAR_ICON, "Clear the task")
        + "</div></div>"
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


def strip() -> str:
    """The task under the map, as the side view sits under a flight's map, and with the
    map in full screen: what it is worth, its options and the takeoff time. There was a
    Task panel floating over the map until October 2026."""
    return ('<div class="plan-strip" id="plan-strip" aria-label="The task">'
            # As `report` in planner.js draws it with no task, so the strip is its own
            # height before the script runs and nothing under it moves when it does.
            '<div class="plan-strip-score"><div class="plan-figures" id="plan-figures">'
            '<span class="plan-row plan-row-head"><div><span class="k">task</span>'
            '<span class="v">— km</span></div></span>'
            '<span class="plan-row plan-row-sub"><span class="plan-row-hint">Press <b>Draw</b>, '
            'then click the map</span><span class="plan-legs" id="plan-legs"></span></span>'
            '</div></div>'
            + controls() + "</div>")


def results() -> str:
    """Under the strip: to and from XCTrack, and what the task crosses."""
    import parainsights_common as common

    return f"""<section class="plan-section" aria-label="The task in detail">
    <!-- To XCTrack: import, and one split button with the device's best way first
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
    <div class="plan-airspace" id="plan-airspace"></div>
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
  <div class="asp-stage">
  <div class="asp-holder">
    {scene_panel.replace('<div class="view3d', map_bar() + '<div class="view3d', 1)}
    <div class="asp-name" id="asp-name"></div>
  </div>
  {strip()}
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
# The sun is the report's (`js/sun.js`, on `js/np.js`): the planner lights its map for the
# takeoff time as a flight's map is lit for the moment under the cursor.
_VIEWER_JS = Path(__file__).parent.parent / "tracklog_viewer" / "js"
SCRIPT = (
    (_VIEWER_JS / "np.js").read_text(encoding="utf-8") + "\n"
    + (_VIEWER_JS / "sun.js").read_text(encoding="utf-8") + "\n"
    + (Path(__file__).parent / "js/planner.js").read_text(encoding="utf-8")
    .replace("__FAI_MIN_SIDE__", str(xc.FAI_MIN_SIDE))
    .replace("__MAX_CLOSING__", str(xc.MAX_CLOSING))
    .replace("__MULTIPLIER__", "{" + ", ".join(f"{name}: {value}" for name, value in xc.MULTIPLIER.items()) + "}")
)

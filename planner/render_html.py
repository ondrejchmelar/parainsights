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
.plan-bar { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center;
  margin:12px 0 10px; font-size:13px; }
.plan-bar .plan-hint { color:var(--ink-3); font-size:12.5px; }
.plan-figures { display:flex; flex-wrap:wrap; gap:10px 26px; margin:12px 0 0; }
.plan-figures div { display:flex; flex-direction:column; }
.plan-figures .k { font-size:10.5px; text-transform:uppercase; letter-spacing:.07em;
  color:var(--ink-3); }
.plan-figures .v { font-size:19px; font-variant-numeric:tabular-nums; }
.plan-shape { display:inline-block; padding:3px 9px; border-radius:3px; font-size:11px;
  text-transform:uppercase; letter-spacing:.06em; background:var(--panel-2); }
.plan-shape.is-fai { background:#15803d; color:#fff; }
.plan-shape.is-flat { background:#a16207; color:#fff; }
.plan-legs { margin:12px 0 0; font-size:12.5px; color:var(--ink-2);
  font-variant-numeric:tabular-nums; }
.plan-legs span { margin-right:14px; white-space:nowrap; }
.plan-airspace { margin:16px 0 0; }
.plan-crossed-head { margin:0 0 6px; font-size:12px; text-transform:uppercase;
  letter-spacing:.07em; color:var(--ink-3); }
.plan-clear { margin:0; font-size:12.5px; color:var(--ink-3); }
.plan-crossed { list-style:none; margin:0; padding:0; border:1px solid var(--rule);
  border-radius:4px; max-height:15em; overflow-y:auto; }
.plan-crossed li { display:flex; align-items:baseline; gap:9px; padding:6px 11px;
  border-bottom:1px solid var(--rule); font-size:13px; }
.plan-crossed li:last-child { border-bottom:0; }
.plan-swatch { width:10px; height:10px; border-radius:2px; flex:none;
  transform:translateY(1px); }
.plan-crossed-name { flex:1; min-width:0; }
.plan-crossed-km { color:var(--ink-3); font-size:12px; white-space:nowrap;
  font-variant-numeric:tabular-nums; }
.plan-crossed li.is-shut .plan-crossed-name { color:var(--ink-3); }
.plan-when { font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
  padding:2px 6px; border-radius:3px; white-space:nowrap; flex:none; }
.plan-when.is-open { background:#15803d; color:#fff; }
.plan-when.is-shut { background:var(--panel-2); color:var(--ink-3); }
.plan-draw[aria-pressed="true"] { background:var(--ink); color:var(--paper);
  border-color:var(--ink); }
.plan-section { margin:18px 0 0; }
.plan-section h2 { font-size:17px; margin:0 0 4px; }
[data-planner][data-drawing="on"] .maplibregl-canvas-container.maplibregl-interactive { cursor:crosshair; }
"""


def controls() -> str:
    """The bar over the map. Drawing is a mode, off until asked for: the same map is the
    airspace map, where a tap on a phone names the zone under the finger, and a tap that
    also dropped a turnpoint would make the one gesture mean two things."""
    return (
        '<div class="plan-bar">'
        '<button type="button" class="plan-draw" id="plan-draw" aria-pressed="false">'
        "Draw a task</button>"
        '<button type="button" id="plan-undo">Undo point</button>'
        '<button type="button" id="plan-clear">Clear</button>'
        '<label><input type="checkbox" id="plan-close"> closed course</label>'
        '<label title="XContest world: closing within 20%, flat ×1.2, FAI ×1.4. ČPP (the Czech '
        'cup): closing within 5%, and in the Central European zone — V4, Austria, Germany '
        'north of 48.5° — flat ×1.8, FAI ×2.2">rules <select id="plan-rules">'
        '<option value="world">XContest world</option>'
        '<option value="cpp">ČPP (Czech)</option></select></label>'
        '<label title="Where each turnpoint can go for an FAI triangle (every side at least '
        '28% of the perimeter), the other two staying put: turnpoint 1 green, 2 blue, 3 red. '
        'Yellow: where a closed course must finish"><input type="checkbox" id="plan-fai" '
        'checked> FAI areas</label>'
        '<span class="plan-hint" id="plan-hint">Press <em>Draw a task</em>, then click the '
        "map to drop turnpoints. Drag, pinch and twist still move the view — a click that "
        "moved is a drag, not a point.</span>"
        "</div>"
    )


def results() -> str:
    """What the drawn route is worth and what it crosses, under the map."""
    return f"""<section class="plan-section" aria-label="The task">
    <div class="plan-figures" id="plan-figures"></div>
    <p class="plan-legs" id="plan-legs"></p>
    <div class="plan-airspace" id="plan-airspace"></div>
    <p class="met-links">Scored with the same rules as the flight report:
    every side at least {xc.FAI_MIN_SIDE:.0%} of the perimeter for FAI, a closing gap under
    {xc.MAX_CLOSING:.0%} of it for a closed course, multipliers
    {xc.MULTIPLIER['open']:g}&thinsp;/&thinsp;{xc.MULTIPLIER['flat']:g}&thinsp;/&thinsp;{xc.MULTIPLIER['fai']:g}.
    With <em>ČPP</em> chosen, the Czech cup's: closing under 5%, and in the Central European
    zone 1&thinsp;/&thinsp;1.8&thinsp;/&thinsp;2.2
    (<a href="https://www.xcontest.org/cesko/pravidla/" rel="noreferrer">rules</a>).
    Airspace is drawn for Czechia only.
    <strong>This is a plan, not a clearance.</strong> Check the airspace and the NOTAMs.</p>
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

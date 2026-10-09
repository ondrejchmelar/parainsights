"""The airspace map, as a self-contained tab in the report.

Same constraint as everything else this repo publishes: no external request at view
time, because a published artifact runs under a policy that blocks every host. So the
map is inline SVG over an embedded border outline — no tile layer, no map library.

**One deliberate exception**: the OpenAir download is a relative link to a file next to
the page, not a data URI. That makes this the one page here that needs a sibling to be
published with it. The trade is worth it — the download keeps its filename on every
phone, can be curl'd or linked directly, and the page does not carry 79 KB of base64
that most readers never click. Nothing the map *renders* fetches anything.

The projection is equirectangular with the longitude axis scaled by cos(lat) at the
centre of the country. Over 6.7° of longitude and 2.5° of latitude the shape error is
under a pixel at the sizes drawn here, and it keeps the pan/zoom arithmetic to a scale
and an offset, which is what makes the whole interaction thirty lines of JavaScript.

Airspaces are drawn back to front by ceiling, so the low ones a paraglider actually has
to care about end up on top rather than buried under a TMA.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re

from . import basemap, hours
from .aerodromes import FEET
from pathlib import Path

# The class filter, and how each class is painted. Order is draw order.
CLASSES = [
    ("base", "Controlled (CTR/TMA/CTA)", "#c2410c"),
    ("restricted", "Restricted, danger, prohibited", "#b91c1c"),
    ("gliding", "Gliding, dropzones, PGZ", "#a16207"),
    # "ATZ" was the label here and is now only the technical name, kept where the AIP is
    # being quoted. A reader filtering a map wants to know what the green ring *is* — the
    # zone around an aerodrome — not the acronym for it, and half the airfields drawn have
    # no ATZ at all, only a circuit.
    ("atz", "Aerodrome zone", "#15803d"),
    ("circuit", "Traffic circuit (okruh)", "#ea580c"),
]

STYLE = """
.airspace-article .renderer-host { position: relative; }
.airspace-article .lede { color: var(--ink-2); margin: 0 0 14px; max-width: 70ch; }
.asp-wrap { margin: 0 0 30px; }
.asp-map { width: 100%; aspect-ratio: 3 / 2; background: var(--panel); border: 1px solid var(--rule);
  border-radius: 14px; touch-action: none; cursor: grab; display: block; }
.asp-map.is-dragging { cursor: grabbing; }
.asp-border { fill: var(--panel-2); stroke: var(--ink-2); stroke-width: 1; vector-effect: non-scaling-stroke; }
.asp-city { fill: var(--ink-2); font-size: 13px; }
.asp-dot { fill: var(--ink-2); }
.asp-zone { vector-effect: non-scaling-stroke; }
.asp-zone:hover { fill-opacity: 0.42; }
.asp-controls { display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: center; margin: 8px 0; font-size: 16px; }
.asp-swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; flex: none; }
.asp-classes { flex-direction: column; align-items: flex-start; gap: 0; }
.asp-slider { display: flex; align-items: center; gap: 10px; flex: 1 1 100%; }
.asp-slider input { flex: 1; accent-color: var(--accent); }
.asp-readout { font-variant-numeric: tabular-nums; color: var(--ink-2); font-size: 15px; }
.asp-when-out { flex: 1 1 100%; min-width: 0; }
.asp-controls input[type="datetime-local"] { font: inherit; font-size: 16px; height: 44px; padding: 0 10px;
  background: var(--panel); color: var(--ink); border: 1px solid var(--edge); border-radius: 10px; }
.asp-name { position: absolute; pointer-events: none; background: var(--ink); color: var(--paper);
  padding: 7px 11px; border-radius: 10px; font-size: 15px; max-width: 320px; opacity: 0;
  transition: opacity 0.1s; z-index: 5; }
.asp-name.is-on { opacity: 1; }
.asp-holder { position: relative; }

/* The stage: the map as tall as the screen, everything else floating over it. */
.asp-stage { position: relative; }
/* The map's own layers stack among themselves, under the panels. */
.asp-stage .asp-holder { isolation: isolate; z-index: 0; }
.asp-stage .view3d { aspect-ratio: auto; height: calc(100vh - 80px); min-height: 560px; }
/* Full screen takes the whole stage, the task and layers panels floating over the map as
   they do on a desktop (the map's own button, `fullscreen` in map3d). */
.asp-stage:fullscreen, .asp-stage.is-maximised { background: var(--paper); width: 100%; height: 100%; }
.asp-stage.is-maximised { position: fixed; inset: 0; z-index: 60; width: auto; height: auto; }
.asp-stage::backdrop { background: var(--paper); }
.asp-stage:fullscreen .asp-holder, .asp-stage.is-maximised .asp-holder,
.asp-stage:fullscreen .renderer-host, .asp-stage.is-maximised .renderer-host,
.asp-stage:fullscreen .view3d-panel, .asp-stage.is-maximised .view3d-panel { height: 100%; margin: 0; }
.asp-stage:fullscreen .view3d, .asp-stage.is-maximised .view3d { height: 100%; min-height: 0; aspect-ratio: auto; }
.asp-stage:fullscreen .asp-floats, .asp-stage.is-maximised .asp-floats { left: 16px; }
.asp-floats { position: absolute; top: 16px; bottom: 16px; z-index: 6; width: 380px;
  left: calc(50% - (100vw - var(--scrollbar, 0px)) / 2 + 16px);
  display: flex; flex-direction: column; gap: 12px; pointer-events: none; }
.float { pointer-events: auto; background: var(--float); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  border: 1px solid var(--float-edge); border-radius: 14px; box-shadow: var(--float-shadow); }
.float h2 { font-size: 20px; margin: 0; display: flex; align-items: center; gap: 4px; }
.plan-panel { position: relative; padding: 16px 20px; overflow-y: auto; min-height: 0; flex: 0 1 auto; }
.asp-layers { padding: 0; flex: none; max-height: 60%; overflow-y: auto; }
/* Folded, nothing to scroll, and the ⓘ's bubble must hang out below it, not be cut off. */
.asp-layers:not([open]) { overflow: visible; }
.asp-layers > summary { list-style: none; display: flex; align-items: center; justify-content: space-between;
  gap: 10px; padding: 10px 20px; min-height: 52px; cursor: pointer; }
.asp-layers > summary::-webkit-details-marker { display: none; }
.asp-layers > summary svg { transition: transform .15s; margin-left: -4px; }
.asp-layers[open] > summary svg { transform: rotate(90deg); }
.asp-layers-count { color: var(--ink-2); font-size: 15px; }
.asp-layers .asp-controls { padding: 0 20px; }
.asp-layers .asp-when-row { padding-bottom: 14px; }
.asp-get-float { margin-top: auto; flex: none; display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 8px 8px 8px 18px; font-weight: 600; }
.asp-get-label { display: inline-flex; align-items: center; }
.asp-sources { margin: 24px 0 0; }
.asp-sources > summary { color: var(--accent); font-weight: 600; cursor: pointer; min-height: 44px; display: flex; align-items: center; }
/* The flat fallback's download box. */
.asp-get { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; margin: 0 0 16px; padding: 14px 16px;
  border: 1px solid var(--rule); border-radius: 14px; background: var(--panel); }
.asp-download { display: inline-flex; flex-direction: column; gap: 1px; text-decoration: none; background: var(--accent);
  color: var(--on-accent); padding: 8px 16px; border-radius: 10px; }
.asp-dl-label { font-weight: 600; font-size: 16px; }
.asp-dl-note { font-size: 15px; opacity: 0.9; font-variant-numeric: tabular-nums; }
.asp-get-how { margin: 0; flex: 1 1 320px; font-size: 15px; color: var(--ink-2); }
.asp-warn { flex: 1 1 100%; margin: 2px 0 0; padding: 10px 14px; font-size: 15px; line-height: 1.5; color: var(--ink-2);
  background: var(--panel-2); border-left: 3px solid var(--warn); border-radius: 6px; }
.asp-warn strong { color: var(--ink); }
.asp-src { width: 100%; border-collapse: collapse; margin: 12px 0 0; font-size: 15px; }
.asp-src caption { text-align: left; font-size: 16px; font-weight: 600; color: var(--ink-2); padding: 0 0 8px; }
.asp-src th { text-align: left; font-weight: 600; font-size: 15px; color: var(--ink-2); border-bottom: 1px solid var(--rule);
  padding: 0 10px 6px 0; }
.asp-src td { padding: 8px 10px 8px 0; border-bottom: 1px solid var(--rule); color: var(--ink-2); vertical-align: top; }
.asp-src a { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
.asp-src a:hover { color: var(--ink); }
.asp-src-key { color: var(--ink) !important; }
.asp-src-key .asp-swatch { margin-right: 5px; vertical-align: -1px; }
.asp-src-when { white-space: nowrap; font-variant-numeric: tabular-nums; }
.asp-nw { white-space: nowrap; }
@media (max-width: 900px) {
  /* A phone or a narrow window: the map first, the task right under it like a sheet,
     then the layers and the download. Over a small map the panels would hide it. */
  .asp-stage .view3d { height: auto; min-height: 0; aspect-ratio: 3 / 4; }
  /* The task right under the map and as wide as it, flat, as the side view sits under a
     flight's map: an inset card under an edge-to-edge map read as the wrong width, and the
     sheet that overlapped the map's edge covered its buttons. The layers likewise, one
     band after it; the download alone stays a card. */
  .asp-floats { position: static; width: auto; display: flex; gap: 0; margin-top: 0; }
  .float { -webkit-backdrop-filter: none; backdrop-filter: none; background: var(--panel); box-shadow: none; }
  .plan-panel, .asp-layers { position: relative; margin: 0 -14px; border-radius: 0;
    border-width: 0 0 1px; border-color: var(--rule); }
  .plan-panel { z-index: 7; padding: 16px 14px; }
  .asp-layers > summary { padding: 10px 14px; }
  .asp-layers .asp-controls { padding: 0 14px; }
  /* The dates wrap between themselves; at one line each the table ran off a phone. */
  .asp-src-when { white-space: normal; }
  .asp-layers { max-height: none; }
  /* Full screen on a phone: the map on the top part, the panels scrolling under it — not
     over it, where they hid the map's own bar and the button that leaves full screen. */
  .asp-stage:fullscreen .asp-holder, .asp-stage.is-maximised .asp-holder { height: 58%; }
  .asp-stage:fullscreen .asp-floats, .asp-stage.is-maximised .asp-floats {
    position: absolute; left: 0; right: 0; top: 58%; bottom: 0; width: auto;
    overflow-y: auto; margin: 0; padding: 0 14px 14px; background: var(--panel);
    pointer-events: auto; border-top: 1px solid var(--rule); }
  .asp-stage:fullscreen .asp-floats > *, .asp-stage.is-maximised .asp-floats > * {
    flex: none; overflow: visible; }
  .asp-get-float { margin-top: 16px; }
}
"""

# Shared by the flat map, the 3D map and the planner, all three of which ask the same
# question of the same payload. It is its own IIFE rather than part of `SCRIPT` because
# `SCRIPT` returns immediately when there is no flat `<svg>` to drive, which is every
# page that draws the 3D view.
HOURS_SCRIPT = (Path(__file__).parent / "js/hours.js").read_text(encoding="utf-8")

MAP_SCRIPT = (Path(__file__).parent / "js/flat_map.js").read_text(encoding="utf-8")

# What every caller has always included. The hours helper has to come first: the map
# script gives up immediately when there is no flat `<svg>` on the page, and the 3D
# script and the planner both need `window.aspHours` regardless.
SCRIPT = HOURS_SCRIPT + MAP_SCRIPT

WIDTH, HEIGHT = 1000.0, 667.0


class Projection:
    """Lon/lat to SVG units, fitted to a bounding box."""

    def __init__(self, bounds, width=WIDTH, height=HEIGHT, pad=0.04):
        min_lat, max_lat, min_lon, max_lon = bounds
        self.lat0 = (min_lat + max_lat) / 2
        self.k = math.cos(math.radians(self.lat0))
        span_x = (max_lon - min_lon) * self.k
        span_y = max_lat - min_lat
        scale = min(width * (1 - 2 * pad) / span_x, height * (1 - 2 * pad) / span_y)
        self.scale = scale
        self.min_lon, self.max_lat = min_lon, max_lat
        self.dx = (width - span_x * scale) / 2
        self.dy = (height - span_y * scale) / 2

    def __call__(self, lat, lon):
        return (
            self.dx + (lon - self.min_lon) * self.k * self.scale,
            self.dy + (self.max_lat - lat) * self.scale,
        )


def _bounds(rings):
    lats = [lat for ring in rings for lat, _ in ring]
    lons = [lon for ring in rings for _, lon in ring]
    return min(lats), max(lats), min(lons), max(lons)


def classify(airspace) -> str:
    """Which filter group an airspace belongs to."""
    kind = airspace.meta.get("kind")
    if kind in ("atz", "circuit"):
        return kind
    # openAIP's type says it outright (`openaip.TYPES`), where OpenAir has to be read.
    if airspace.meta.get("group"):
        return airspace.meta["group"]
    name = (airspace.name or "").upper()
    cls = (airspace.airspace_class or "").upper()
    if cls in ("R", "P", "D") or "DANGER" in name:
        return "restricted"
    if cls in ("GS", "W", "Q") or "GLID" in name or "DROPZONE" in name or "PGZ" in name:
        return "gliding"
    return "base"


_FL = 100 * FEET


def limit_metres(text: str) -> tuple[float | None, bool]:
    """A published limit as metres, and whether it is measured from the ground.

    Every form the two sources write: `GND`, `SFC`, `0 AGL`, `FL 95`, `4000 MSL`,
    `1000ft AMSL`, `500m AMSL`, `1000 AGL`. `None` is unlimited, which nothing in the
    Czech low airspace says today but an OpenAir file is entitled to.

    The second half of the answer only became worth having when the map started drawing
    boxes: for the filter, a limit quoted above ground can be read as an altitude, and
    for a box it cannot — `1000 AGL` drawn at 305 m AMSL is a lid *under* the terrain
    over most of this country.
    """
    raw = (text or "").upper().replace(" ", "")
    if not raw or raw.startswith("GND") or raw.startswith("SFC"):
        return 0.0, True
    if raw.startswith("UNL"):
        return None, False
    match = re.search(r"FL(\d+)", raw)
    if match:
        return float(match.group(1)) * _FL, False
    ground = bool(re.search(r"AGL|AAL", raw))
    # Strip the datum words *before* looking for a unit. `4000 MSL` is 4000 feet, and
    # testing for an "M" in the string reads it as 4000 metres — a 2 800 m error on the
    # 18 airspaces in the base file that use that form.
    body = re.sub(r"A?(MSL|GND|AGL|AAL|SFC|ALT)", "", raw)
    match = re.search(r"(\d+(?:\.\d+)?)", body)
    if not match:
        return 0.0, True
    value = float(match.group(1))
    metres = value if re.search(r"\d\s*M$|\dM(?![A-Z])", body) else value * FEET
    return metres, ground


def floor_metres(airspace) -> float:
    """The floor as metres AMSL, for the altitude filter.

    AGL is treated as AMSL: the filter's question is "could this be in my way low
    down", and a floor quoted above ground is by definition low down.
    """
    metres, _ = limit_metres(airspace.floor)
    return 0.0 if metres is None else metres


def ceiling_metres(airspace) -> tuple[float | None, bool]:
    """The ceiling as metres and whether it is above the ground — what the 3D map needs
    to put a lid on the box. `None` metres is an unlimited ceiling."""
    return limit_metres(airspace.ceiling)


def _path(points, project) -> str:
    if not points:
        return ""
    out = []
    for index, (lat, lon) in enumerate(points):
        x, y = project(lat, lon)
        out.append(f"{'M' if index == 0 else 'L'}{x:.1f} {y:.1f}")
    return " ".join(out) + " Z"


def _escape(text: str) -> str:
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )


def map_svg(airspaces, project) -> str:
    """The whole map: border, cities, then airspaces low-ceiling last."""
    parts = [
        f'<svg id="asp-map" class="asp-map" viewBox="0 0 {WIDTH:.0f} {HEIGHT:.0f}" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="Czech airspace map">'
    ]
    parts.append(f'<path class="asp-border" d="{_path(basemap.BORDER, project)}"/>')

    colours = dict((key, colour) for key, _, colour in CLASSES)
    # Purely biggest-first, ignoring class. SVG has no z-index — paint order *is* hit
    # order — so whatever is drawn last both covers and captures the pointer. Ordering
    # by class put every ATZ above the dropzone inside it, and Tábor's dropzone could
    # not be clicked through its own ATZ. Smallest on top means the most specific thing
    # under the cursor is the one you get, which is what a reader means by clicking.
    ranked = sorted(airspaces, key=lambda a: -_area(a))
    for airspace in ranked:
        group = classify(airspace)
        label = airspace.name
        if airspace.floor or airspace.ceiling:
            label += f"  ({airspace.floor} – {airspace.ceiling})"
        schedule = airspace.meta.get("hours")
        parts.append(
            f'<path class="asp-zone" data-klass="{group}" '
            f'data-floor="{floor_metres(airspace):.0f}" '
            + (f'data-hours="{_escape(json.dumps(schedule, separators=(",", ":")))}" '
               if schedule else "")
            + f'data-label="{_escape(label)}" '
            f'fill="{colours[group]}" fill-opacity="0.18" '
            f'stroke="{colours[group]}" stroke-width="1.1" '
            f'd="{_path(airspace.points, project)}"><title>{_escape(label)}</title></path>'
        )
    for name, lat, lon in basemap.CITIES:
        x, y = project(lat, lon)
        parts.append(f'<circle class="asp-dot" cx="{x:.1f}" cy="{y:.1f}" r="2.2"/>')
        parts.append(
            f'<text class="asp-city" x="{x + 5:.1f}" y="{y + 3.5:.1f}">{_escape(name)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _area(airspace) -> float:
    """Rough planar area, only ever used to order the drawing."""
    points = airspace.points
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i in range(len(points)):
        y1, x1 = points[i]
        y2, x2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def when_control(note: str = "") -> str:
    """The time filter: hide the fields that are outside their published hours.

    **Off by default**, for the same reason the floor slider opens showing everything: a
    map that silently withholds airspace is the wrong thing to open with, and this one
    would withhold it on the strength of prose parsed out of a VFR manual page.

    The input is Czech wall-clock time, because that is what a pilot plans in; the
    published hours are UTC and the script converts. It carries the holiday calendar in
    a data attribute rather than in the scene payload, because the flat map has no scene
    and both maps have to answer the same question.

    Only the aerodrome layers can be hidden by it. The base airspace's own activation
    lives in NOTAMs this repository does not fetch, and the 74 SLZ strips publish no
    hours — so the count beside the control is the honest measure of how much of the map
    this control can actually speak for.
    """
    years = range(dt.date.today().year - 1, dt.date.today().year + 3)
    calendar = ",".join(hours.holiday_list(years))
    import parainsights_common as common

    return (
        '<div class="asp-controls asp-when-row">'
        '<label class="chk" for="asp-when-on"><input type="checkbox" id="asp-when-on">'
        f"Only fields open at</label>{common.info(note) if note else ''}"
        f'<input type="datetime-local" id="asp-when" data-holidays="{calendar}" '
        'aria-label="date and time, Czech local">'
        '<button type="button" class="btn" id="asp-when-now">Now</button>'
        '<span class="asp-readout asp-when-out" id="asp-when-out"></span>'
        "</div>"
    )


WHEN_NOTE = (
    "Czech local time. Aerodrome hours are published for 68 of the 82 aerodromes and "
    "for <strong>none</strong> of the 74 ultralight strips, and nothing else on this map "
    "carries hours at all — so this hides part of one layer, not the map. "
    "<strong>Outside published hours is not “closed”</strong>: almost every field adds "
    "“otherwise on request”, and a tow launch needs no published hour."
)


def controls(top: int, flat: bool = True) -> str:
    """The class checkboxes and the floor slider.

    The slider's range is the data's, not a round number: `CZ_low` stops at FL95, so its
    highest floor is about 2 300 m and a slider running to 10 000 m spends three
    quarters of its travel doing nothing. It starts at the top — showing everything —
    because most of this airspace has a ground floor, so the filter answers "what is
    above me at 1 500 m" rather than decluttering, and a view that silently hides
    airspace is the wrong thing to open with.
    """
    boxes = "".join(
        f'<label class="chk"><input type="checkbox" data-asp-class="{key}" checked>'
        f'<span class="asp-swatch" style="background:{colour}"></span>{_escape(label)}</label>'
        for key, label, colour in CLASSES
    )
    return (
        f'<div class="asp-controls asp-classes">{boxes}</div>'
        '<div class="asp-controls">'
        '<span class="asp-slider">'
        '<label for="asp-floor">Floor at or below</label>'
        f'<input type="range" id="asp-floor" min="0" max="{top}" step="50" '
        f'value="{top}" data-top="{top}">'
        '<span class="asp-readout" id="asp-readout"></span></span>'
        '<span class="asp-readout" id="asp-count"></span>'
        # The 3D map carries its own reset in the bar across its bottom,
        # and two buttons that both say "reset" and do different amounts is worse than
        # one. There, this button clears the filters *and* presses that one.
        f'<button type="button" class="btn" id="asp-reset">'
        f'{"Reset view" if flat else "Reset"}</button>'
        "</div>"
        + when_control(WHEN_NOTE)
    )


def _atz_row(overlay, clipped: int, shift: float) -> str:
    """What the aerodrome-zone layer actually contains — counted off what is drawn, not
    what was parsed, because an SLZ field's circle is not an aerodrome zone and is
    normally left out."""
    drawn = [a for a in overlay.airspaces if a.meta.get("kind") == "atz"]
    aerodromes = sum(1 for a in drawn if not a.name.startswith("SLZ"))
    slz = len(drawn) - aerodromes
    detail = (f"{aerodromes} public aerodromes, 5 500 m radius, ground to 4 000 ft "
              "(the AIP calls these ATZ)")
    if clipped:
        detail += f", {clipped} clipped by an overlying CTR or TMA"
    if shift >= 1:
        detail += f"; positions corrected by {shift:.0f} m"
    if slz:
        detail += f". Plus {slz} SLZ circles — UAS zones, and not the same thing"
    else:
        detail += (". <strong>An ultralight strip has no zone of its own</strong>, so "
                   "those 74 fields carry only their traffic circuit")
    return f"Aerodrome zones — {detail}"


def _link(href: str, text: str) -> str:
    """A link out to a source. Not a request at view time — only when clicked — so this
    does not break the rule that a published artifact fetches nothing."""
    return f'<a href="{_escape(href)}" rel="noreferrer">{_escape(text)}</a>'


def _dates_whole(text: str) -> str:
    """Each date kept on one line, so a narrow column wraps between dates, not inside one."""
    return re.sub(r"(\d{4}-\d{2}-\d{2})", r'<span class="asp-nw">\1</span>', text)


def sources_table(overlay, base_version: str, shift: float) -> str:
    """Which layer on the map came from where. State, not explanation.

    Keyed by the legend swatch, because the question a reader actually has is "that
    green circle — who says so?" and a paragraph cannot answer it colour by colour.
    Every source links to the file it actually came from, so the reader can check
    currency at the source rather than take this table's word for it.
    """
    from . import sources

    colour = dict((key, hue) for key, _, hue in CLASSES)
    clipped = len(overlay.zones) - overlay.circle_count
    stamp = overlay.atz_date.replace("-", "_")
    # openAIP, refreshed monthly (`openaip.py`); CC BY-NC 4.0, which asks for this credit.
    base_source = _link("https://www.openaip.net", "openAIP") + " — CC BY-NC 4.0"
    zone_links = ", ".join(
        _link(sources.RLP_ATZ.format(date=stamp, pub=pub), f"LKR315{pub}")
        for pub in sorted(overlay.by_publication)
    )
    rows = [
        (["base", "restricted"],
         "Controlled, restricted, danger, prohibited",
         base_source,
         _escape(base_version)),
        (["gliding"],
         "Gliding areas, dropzones, PGZ",
         base_source,
         _escape(base_version)),
        (["atz"],
         "Aerodrome zones on the map — openAIP's. The download's are this site's own: "
         + _atz_row(overlay, clipped, shift)[len("Aerodrome zones — "):],
         f"map: {base_source}; download: {_link('https://aim.rlp.cz/', 'ŘLP ČR')} — "
         f"UAS zones, {zone_links}",
         f"{_escape(base_version)}; {_escape(overlay.atz_date)}"),
        (["circuit"],
         "Traffic circuits (okruhy) — <strong>drawn by this tool, not a published "
         "boundary.</strong> Shape scaled off the AIP's VOC charts (±10%); altitude "
         "published where stated, otherwise 1 000 ft above the field (measured mean "
         "993 ft over five, spread 820–1 150). At an SLZ strip the runway itself is "
         "reconstructed from the reference point and a heading rounded to 10°, so those "
         "are marked <code>est</code>",
         "circuit drawn from the "
         + _link("https://aim.rlp.cz/vfrmanual/actual/ad/lkcast_voc.jpg", "VOC charts")
         + ", altitudes and runway tables from the "
         + _link("https://aim.rlp.cz/vfrmanual/actual/lkta_text_en.html",
                 "AIP VFR manual")
         + ", thresholds from "
         + _link("https://ourairports.com/countries/CZ/", "OurAirports"),
         "—"),
    ]
    body = "".join(
        "<tr><td class='asp-src-key'>"
        + "".join(
            f'<span class="asp-swatch" style="background:{colour[k]}"></span>'
            for k in keys
        )
        + f"{label}</td><td>{source}</td><td class='asp-src-when'>{_dates_whole(when)}</td></tr>"
        for keys, label, source, when in rows
    )
    return (
        '<table class="asp-src"><caption>What is on this map, and where it came from'
        "</caption><thead><tr><th>Layer</th><th>Source</th><th>Effective</th></tr>"
        f"</thead><tbody>{body}</tbody></table>"
    )


def warning() -> str:
    """Short on purpose. The dates it would otherwise recite are in the sources table
    below the map, which is where a reader goes to check currency anyway."""
    return (
        '<p class="asp-warn">Provided with no guarantee — it may be out of date or '
        "wrong. <strong>Pilots are responsible for the airspace they fly in.</strong> "
        "Check the AIP and NOTAMs before flying.</p>"
    )


def download_link(filename: str, label: str, note: str) -> str:
    """A link to the OpenAir file sitting next to the page.

    A plain relative href, not a data URI. The page therefore is not self-contained —
    the one place in this repository where that is true — and the file has to be
    published alongside it. In exchange the download is an ordinary file: it keeps its
    name on every browser and phone, it can be linked to and curl'd directly, and the
    page does not carry 79 KB of base64 that most readers never click.
    """
    return (
        f'<a class="asp-download" download="{_escape(filename.rsplit("/", 1)[-1])}" '
        f'href="{_escape(filename)}">'
        f'<span class="asp-dl-label">{_escape(label)}</span>'
        f'<span class="asp-dl-note">{_escape(note)}</span></a>'
    )


SCRIPT3D = (Path(__file__).parent / "js/map.js").read_text(encoding="utf-8")


def body(overlay, base, base_version: str, uid: str = "airspace",
         openair_name: str = "", openair_size: int = 0, openair_href: str = "",
         scene: dict | None = None) -> str:
    """The airspace article, ready to drop into the report.

    Carries no `data-flight-report` and is not hidden: in the report it sits inside a
    top-level view section that owns its visibility. Giving it the flight attribute put
    it under the flight tab strip's controller too, and the two then fought over
    `hidden` — the flight controller hides everything that is not the open flight.

    `openair_href` is where the download lives *relative to the page*, which is not the
    same as its filename once this article is embedded in a report one directory up.
    """
    airspaces = list(base) + overlay.circuit_airspaces
    rings = [a.points for a in airspaces if a.points] + [basemap.BORDER]
    project = Projection(_bounds(rings))
    east, north, samples = overlay.offset
    shift = math.hypot(east, north)
    top = int(math.ceil(max((floor_metres(a) for a in airspaces), default=0) / 50.0) * 50)

    # Only where there is a 3D view to say it about. The flat fallback draws outlines,
    # and a page that described boxes nobody could see would be worse than silent.
    boxes = ""
    if scene is not None:
        from .scene import DRAWN_TOP

        capped = sum(1 for ring in scene.get("airspaces", []) if ring.get("t"))
        boxes = (
            " Each zone is the box it really is — floor to ceiling — so drag with the "
            "right button to tilt and see what sits over what. <strong>The vertical is "
            "exaggerated five times</strong>, which the \u00d7 buttons under the map set: "
            "at true scale, across 500 km of country, a 300 m traffic circuit is a third "
            "of a pixel tall and every box here is two rings on top of each other. "
            "\u00d71 is one press away, and the limits in each label are the real ones "
            "whichever setting you are on."
            + (f" The {capped} that run above {DRAWN_TOP / 1000:.0f} km are cut off at a "
               "dashed lid, which is a cap and not their ceiling; the label says how high "
               "they go." if capped else "")
        )

    download = ""
    if openair_name:
        download = (
            '<div class="asp-get">'
            + download_link(
                openair_href or openair_name,
                "Download the airfield layer",
                f"OpenAir · {overlay.atz_count} aerodrome zones, {overlay.circuits} "
                f"circuits at {overlay.circuit_fields} fields "
                f"· {openair_size / 1024:.0f} KB",
            )
            + '<p class="asp-get-how"><strong>This file is not a full airspace set.</strong> '
            "It holds the green and orange layers only — the aerodrome zones and traffic "
            "circuits that XCTrack and XContest leave out — so load it <em>alongside</em> "
            "your usual airspace, never instead of it. Nothing in red or amber on the map "
            "above is in this file.<br>"
            "Import under <em>Preferences → Airspaces and obstacles → Files → Import "
            "OpenAir files</em>, or copy it into the <code>XCTrack/Airspaces</code> "
            "folder and tick it there.</p>"
            + warning()
            + "</div>"
        )

    # The planner draws on the 3D view, so the flat fallback carries no planner.
    plan_bar, plan_results, plan_attr, plan_lede = "", "", "", ""
    if scene is not None:
        from planner import render_html as planner_html

        plan_bar, plan_results = planner_html.controls(), planner_html.results()
        plan_attr = " data-planner"
        plan_lede = (" <strong>Plan a task on the same map:</strong> press <em>Draw a "
                     "task</em> and click turnpoints, and the route is scored as XContest "
                     "would and checked against every zone it crosses.")

    import parainsights_common as common

    if scene is None:
        # The flat fallback (`--flat`): no stage, the controls above the map as before.
        return f"""<article class="flight airspace-article" id="{uid}-article"{plan_attr}>
  <p class="lede">Czech airspace and the traffic circuits no published source draws.</p>
  {controls(top, flat=True)}
  <div class="asp-holder">
    {_map(airspaces, project, scene, uid)}
    <div class="asp-name" id="asp-name"></div>
  </div>
  {download}
  <details class="asp-sources"><summary>Sources</summary>{sources_table(overlay, base_version, shift)}</details>
</article>"""

    about = ("Everything openAIP carries over Czechia, plus what no published source draws: "
             f"the traffic circuit at {overlay.circuit_fields} fields and ultralight strips. A "
             "paraglider may fly inside an aerodrome zone but must stay out of its circuit, and "
             "no instrument draws the circuit. Hover a zone for its name and limits." + boxes)
    get = ""
    if openair_name:
        get = (f'<div class="float asp-get-float">'
               f'<span class="asp-get-label">Airfield layer for XCTrack'
               + common.info(
                   "Aerodrome zones and traffic circuits XCTrack and XContest leave out "
                   f"(OpenAir · {overlay.atz_count} zones, {overlay.circuits} circuits at "
                   f"{overlay.circuit_fields} fields · {openair_size / 1024:.0f} KB). "
                   "<strong>Not a full airspace set</strong>: load it alongside your usual "
                   "airspace, never instead of it. Import under Preferences → Airspaces and "
                   "obstacles → Files → Import OpenAir files, or copy it into the "
                   "XCTrack/Airspaces folder. Provided with no guarantee — it may be out of "
                   "date or wrong; you are responsible for the airspace you fly in.",
                   "About the airfield layer")
               + '</span>'
               f'<a class="btn primary" download="{_escape((openair_href or openair_name).rsplit("/", 1)[-1])}" '
               f'href="{_escape(openair_href or openair_name)}">'
               f'{common.icon(common.ICONS["download"])}Download</a></div>')
    task = ""
    if plan_bar:
        task = (f'<div class="float plan-panel"><h2>Task{common.info("Press Draw a task, then click the map to drop turnpoints; drag, pinch and twist still move the view. The route is scored as XContest would and checked against every zone it crosses.")}</h2>'
                + plan_results.replace('<div class="plan-figures" id="plan-figures"></div>',
                                       '<div class="plan-figures" id="plan-figures"></div>' + plan_bar, 1)
                + '</div>')
    return f"""<article class="flight airspace-article" id="{uid}-article"{plan_attr}>
  <!-- The map is the page: everything else floats over it, and on a phone the task is a
       sheet across its foot. -->
  <div class="asp-stage">
    <div class="asp-holder">
      {_map(airspaces, project, scene, uid)}
      <div class="asp-name" id="asp-name"></div>
    </div>
    <div class="asp-floats">
      {task}
      <details class="float asp-layers">
        <summary><h2>{common.icon(common.ICONS["right"])}Layers{common.info(about, "About this map")}</h2><span class="asp-layers-count" id="asp-count"></span></summary>
        {controls(top, flat=False).replace('<span class="asp-readout" id="asp-count"></span>', '', 1)}
      </details>
      {get}
    </div>
  </div>
  <details class="asp-sources"><summary>Sources and dates</summary>{sources_table(overlay, base_version, shift)}</details>
</article>"""


def _map(airspaces, project, scene: dict | None, uid: str) -> str:
    """The map itself: the 3D map where a scene was built for it, the flat SVG where it
    was not — which is only when asked for (`--flat`): the 3D map fetches its ground and
    imagery in the page, so a build cannot lose them (`scene.remote`)."""
    if scene is None:
        return map_svg(airspaces, project)
    from parainsights_map import view3d

    # The exaggeration this map offers, and it starts at x5. At true scale over 500 km
    # of country a 300 m traffic circuit is **0.3 px** tall and an ATZ 0.7 px, so every
    # box is two coincident rings — the flat map with extra steps. x1 is still one press
    # away and the segmented control says which is on, so nothing here is hidden; what is
    # hidden at true scale is the entire point of the view. The map is the flights' own
    # (`map3d`, opened by `render_map`), and the planner draws on it too.
    return ('<div class="renderer-host">'
            + view3d.panel(scene, uid, verticals=(1, 5, 15), vertical=5)
            + "</div>")

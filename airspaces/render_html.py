"""The airspace map, as a self-contained tab in the report.

Same constraint as everything else this repo publishes: no external request at view
time, because a published artifact runs under a policy that blocks every host. So the
map is inline SVG over an embedded border outline — no tile layer, no map library.

The projection is equirectangular with the longitude axis scaled by cos(lat) at the
centre of the country. Over 6.7° of longitude and 2.5° of latitude the shape error is
under a pixel at the sizes drawn here, and it keeps the pan/zoom arithmetic to a scale
and an offset, which is what makes the whole interaction thirty lines of JavaScript.

Airspaces are drawn back to front by ceiling, so the low ones a paraglider actually has
to care about end up on top rather than buried under a TMA.
"""

from __future__ import annotations

import base64
import math
import re

from . import basemap
from .aerodromes import FEET

# The class filter, and how each class is painted. Order is draw order.
CLASSES = [
    ("base", "Controlled (CTR/TMA/CTA)", "#c2410c"),
    ("restricted", "Restricted, danger, prohibited", "#b91c1c"),
    ("gliding", "Gliding, dropzones, PGZ", "#a16207"),
    ("atz", "ATZ", "#15803d"),
    ("circuit", "Traffic circuit (okruh)", "#ea580c"),
]

STYLE = """
.asp-wrap { margin: 0 0 30px; }
.asp-map { width: 100%; aspect-ratio: 3 / 2; background: var(--panel);
  border: 1px solid var(--rule); border-radius: 4px; touch-action: none;
  cursor: grab; display: block; }
.asp-map.is-dragging { cursor: grabbing; }
.asp-border { fill: var(--panel-2); stroke: var(--ink-3); stroke-width: 1;
  vector-effect: non-scaling-stroke; }
.asp-city { fill: var(--ink-3); font-size: 10px; }
.asp-dot { fill: var(--ink-3); }
.asp-zone { vector-effect: non-scaling-stroke; }
.asp-zone:hover { fill-opacity: 0.42; }
.asp-controls { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center;
  margin: 12px 0 8px; font-size: 13px; }
.asp-controls label { display: inline-flex; align-items: center; gap: 5px;
  cursor: pointer; }
.asp-swatch { width: 11px; height: 11px; border-radius: 2px; display: inline-block; }
.asp-slider { display: flex; align-items: center; gap: 8px; flex: 1 1 260px; }
.asp-slider input { flex: 1; }
.asp-readout { font-variant-numeric: tabular-nums; color: var(--ink-2);
  min-width: 8.5em; }
.asp-hint { font-size: 12.5px; color: var(--ink-3); margin: 6px 0 0; }
.asp-name { position: absolute; pointer-events: none; background: var(--ink);
  color: var(--paper); padding: 5px 8px; border-radius: 3px; font-size: 12px;
  max-width: 320px; opacity: 0; transition: opacity 0.1s; z-index: 5; }
.asp-name.is-on { opacity: 1; }
.asp-holder { position: relative; }
.asp-get { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px;
  margin: 0 0 16px; padding: 13px 15px; border: 1px solid var(--rule);
  border-left: 3px solid var(--atz, #15803d); border-radius: 4px; background: var(--panel); }
.asp-download { display: inline-flex; flex-direction: column; gap: 1px;
  text-decoration: none; background: var(--atz, #15803d); color: #fff; padding: 8px 15px;
  border-radius: 3px; }
.asp-download:hover { filter: brightness(1.12); }
.asp-dl-label { font-weight: 600; font-size: 14px; }
.asp-dl-note { font-size: 11.5px; opacity: 0.85; font-variant-numeric: tabular-nums; }
.asp-get-how { margin: 0; flex: 1 1 320px; font-size: 12.5px; color: var(--ink-2); }
.asp-get-how code { font-size: 12px; background: var(--panel-2); padding: 1px 4px;
  border-radius: 2px; }
"""

SCRIPT = """
(function () {
  var svg = document.getElementById('asp-map');
  if (!svg) return;
  var view = { x: 0, y: 0, w: 1000, h: 667 };
  var home = { x: 0, y: 0, w: 1000, h: 667 };
  var tip = document.getElementById('asp-name');

  function apply() {
    svg.setAttribute('viewBox', view.x + ' ' + view.y + ' ' + view.w + ' ' + view.h);
  }

  function zoomAt(clientX, clientY, ratio) {
    var box = svg.getBoundingClientRect();
    // Anchor the zoom on the cursor: the world point under it must not move.
    var fx = (clientX - box.left) / box.width;
    var fy = (clientY - box.top) / box.height;
    var wx = view.x + fx * view.w, wy = view.y + fy * view.h;
    var next = Math.min(Math.max(view.w * ratio, home.w / 400), home.w);
    ratio = next / view.w;
    view.w = next; view.h = view.h * ratio;
    view.x = wx - fx * view.w; view.y = wy - fy * view.h;
    apply();
  }

  svg.addEventListener('wheel', function (e) {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, e.deltaY > 0 ? 1.15 : 1 / 1.15);
  }, { passive: false });

  var drag = null, pinch = null;
  svg.addEventListener('pointerdown', function (e) {
    svg.setPointerCapture(e.pointerId);
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY };
    svg.classList.add('is-dragging');
  });
  svg.addEventListener('pointermove', function (e) {
    if (!drag || e.pointerId !== drag.id) return;
    var box = svg.getBoundingClientRect();
    view.x -= (e.clientX - drag.x) * view.w / box.width;
    view.y -= (e.clientY - drag.y) * view.h / box.height;
    drag.x = e.clientX; drag.y = e.clientY;
    apply();
  });
  function endDrag() { drag = null; svg.classList.remove('is-dragging'); }
  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);

  // Two-finger pinch, tracked off the raw touch list because pointer events give one
  // stream per finger and the midpoint is what the zoom has to anchor on.
  svg.addEventListener('touchmove', function (e) {
    if (e.touches.length !== 2) { pinch = null; return; }
    e.preventDefault();
    var a = e.touches[0], b = e.touches[1];
    var span = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
    var mx = (a.clientX + b.clientX) / 2, my = (a.clientY + b.clientY) / 2;
    if (pinch) zoomAt(mx, my, pinch / span);
    pinch = span;
    drag = null;
  }, { passive: false });
  svg.addEventListener('touchend', function () { pinch = null; });

  function refilter() {
    var on = {};
    document.querySelectorAll('[data-asp-class]').forEach(function (box) {
      on[box.dataset.aspClass] = box.checked;
    });
    var slider = document.getElementById('asp-floor');
    var limit = slider ? Number(slider.value) : Infinity;
    var top = slider ? Number(slider.dataset.top) : 0;
    var out = document.getElementById('asp-readout');
    if (out) out.textContent = limit >= top ? 'every floor'
      : 'floor at or below ' + limit + ' m';
    var shown = 0;
    svg.querySelectorAll('.asp-zone').forEach(function (zone) {
      var visible = on[zone.dataset.klass] !== false
        && Number(zone.dataset.floor) <= limit;
      zone.style.display = visible ? '' : 'none';
      if (visible) shown++;
    });
    var count = document.getElementById('asp-count');
    if (count) count.textContent = shown + ' shown';
  }
  document.querySelectorAll('[data-asp-class]').forEach(function (box) {
    box.addEventListener('change', refilter);
  });
  var slider = document.getElementById('asp-floor');
  if (slider) slider.addEventListener('input', refilter);

  svg.addEventListener('pointerover', function (e) {
    var zone = e.target.closest('.asp-zone');
    if (!zone || !tip) return;
    tip.textContent = zone.dataset.label;
    tip.classList.add('is-on');
  });
  svg.addEventListener('pointermove', function (e) {
    if (!tip || !tip.classList.contains('is-on')) return;
    var holder = tip.parentNode.getBoundingClientRect();
    tip.style.left = (e.clientX - holder.left + 12) + 'px';
    tip.style.top = (e.clientY - holder.top + 12) + 'px';
  });
  svg.addEventListener('pointerout', function (e) {
    if (tip && !e.relatedTarget) tip.classList.remove('is-on');
    else if (tip && !e.relatedTarget.closest('.asp-zone')) tip.classList.remove('is-on');
  });

  var reset = document.getElementById('asp-reset');
  if (reset) reset.addEventListener('click', function () {
    view = { x: home.x, y: home.y, w: home.w, h: home.h };
    apply();
  });

  refilter();
  apply();
})();
"""

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
    name = (airspace.name or "").upper()
    cls = (airspace.airspace_class or "").upper()
    if cls in ("R", "P", "D") or "DANGER" in name:
        return "restricted"
    if cls in ("GS", "W", "Q") or "GLID" in name or "DROPZONE" in name or "PGZ" in name:
        return "gliding"
    return "base"


_FL = 100 * FEET


def floor_metres(airspace) -> float:
    """The floor as metres AMSL, for the altitude filter.

    AGL is treated as AMSL: the filter's question is "could this be in my way low
    down", and a floor quoted above ground is by definition low down.
    """
    raw = (airspace.floor or "").upper().replace(" ", "")
    if not raw or raw.startswith("GND") or raw.startswith("SFC") or raw.startswith("0"):
        return 0.0
    match = re.search(r"FL(\d+)", raw)
    if match:
        return float(match.group(1)) * _FL
    # Strip the datum words *before* looking for a unit. `4000 MSL` is 4000 feet, and
    # testing for an "M" in the string reads it as 4000 metres — a 2 800 m error on the
    # 18 airspaces in the base file that use that form.
    body = re.sub(r"A?(MSL|GND|AGL|SFC|ALT)", "", raw)
    match = re.search(r"(\d+(?:\.\d+)?)", body)
    if not match:
        return 0.0
    value = float(match.group(1))
    return value if re.search(r"\d\s*M$|\dM(?![A-Z])", body) else value * FEET


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
    order = {key: index for index, (key, _, _) in enumerate(CLASSES)}
    # Big and high first, small and low on top — otherwise a TMA covers every ATZ
    # underneath it and the layer a paraglider cares about is the one you cannot click.
    ranked = sorted(
        airspaces,
        key=lambda a: (order.get(classify(a), 0), -_area(a)),
    )
    for airspace in ranked:
        group = classify(airspace)
        label = airspace.name
        if airspace.floor or airspace.ceiling:
            label += f"  ({airspace.floor} – {airspace.ceiling})"
        parts.append(
            f'<path class="asp-zone" data-klass="{group}" '
            f'data-floor="{floor_metres(airspace):.0f}" '
            f'data-label="{_escape(label)}" '
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


def controls(top: int) -> str:
    """The class checkboxes and the floor slider.

    The slider's range is the data's, not a round number: `CZ_low` stops at FL95, so its
    highest floor is about 2 300 m and a slider running to 10 000 m spends three
    quarters of its travel doing nothing. It starts at the top — showing everything —
    because most of this airspace has a ground floor, so the filter answers "what is
    above me at 1 500 m" rather than decluttering, and a view that silently hides
    airspace is the wrong thing to open with.
    """
    boxes = "".join(
        f'<label><input type="checkbox" data-asp-class="{key}" checked>'
        f'<span class="asp-swatch" style="background:{colour}"></span>{_escape(label)}</label>'
        for key, label, colour in CLASSES
    )
    return (
        f'<div class="asp-controls">{boxes}</div>'
        '<div class="asp-controls">'
        '<span class="asp-slider">'
        '<label for="asp-floor">Floor at or below</label>'
        f'<input type="range" id="asp-floor" min="0" max="{top}" step="50" '
        f'value="{top}" data-top="{top}">'
        '<span class="asp-readout" id="asp-readout"></span></span>'
        '<span class="asp-readout" id="asp-count"></span>'
        '<button type="button" id="asp-reset">Reset view</button>'
        "</div>"
    )


def download_link(text: str, filename: str, label: str, note: str) -> str:
    """The OpenAir file as a data URI, so the page carries it rather than links to it.

    Same rule as the rest of the repository: a published artifact reaches no external
    host, and that has to include its own attachments. base64 rather than percent
    encoding because an OpenAir file is `*`, `:` and newlines throughout, which
    percent-encoding roughly doubles anyway.
    """
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return (
        f'<a class="asp-download" download="{_escape(filename)}" '
        f'href="data:text/plain;base64,{payload}">'
        f'<span class="asp-dl-label">{_escape(label)}</span>'
        f'<span class="asp-dl-note">{_escape(note)}</span></a>'
    )


def body(overlay, base, base_version: str, uid: str = "airspace",
         openair_text: str = "", openair_name: str = "CZ_ATZ.txt") -> str:
    """The airspace article, ready to drop into the report as a tab."""
    airspaces = list(base) + list(overlay.airspaces)
    rings = [a.points for a in airspaces if a.points] + [basemap.BORDER]
    project = Projection(_bounds(rings))
    east, north, samples = overlay.offset
    shift = math.hypot(east, north)
    top = int(math.ceil(max(floor_metres(a) for a in airspaces) / 50.0) * 50)

    download = ""
    if openair_text:
        download = (
            '<div class="asp-get">'
            + download_link(
                openair_text,
                openair_name,
                "Download for XCTrack",
                f"OpenAir · {overlay.atz_count} ATZ + {overlay.circuit_count} circuits "
                f"· {len(openair_text) / 1024:.0f} KB",
            )
            + '<p class="asp-get-how">Import in XCTrack under <em>Preferences → '
            "Airspaces and obstacles → Files → Import OpenAir files</em>, or copy it into "
            "the <code>XCTrack/Airspaces</code> folder and tick it there. It is an "
            "<strong>addition</strong> — keep your usual airspace loaded as well.</p>"
            "</div>"
        )

    return f"""<article class="flight" data-flight-report="{uid}" hidden>
  <h1>Czech airspace</h1>
  <p class="lede">The published base airspace, plus the {overlay.atz_count} ATZ it
  leaves out. Scroll to zoom, drag to pan, hover for the name and limits.</p>
  {download}
  {controls(top)}
  <div class="asp-holder">
    {map_svg(airspaces, project)}
    <div class="asp-name" id="asp-name"></div>
  </div>
  <p class="asp-hint">
    Base airspace: <strong>CZ_low {_escape(base_version)}</strong>, Jan Zahradka for
    Aeroklub ČR — the same data airspace.xcontest.org carries for Czechia, taken from
    the origin rather than the mirror. ATZ: RLP publication LKR315A,
    {_escape(overlay.atz_date)}, {overlay.circle_count} of {len(overlay.zones)} refitted
    as exact 5 500 m circles and the rest kept as clipped polygons; all of them shifted
    {shift:.0f} m north-east to correct a datum error in the source, measured over
    {samples} zones. Circuit boxes are drawn by this tool and are not an official
    boundary. Not for navigation.</p>
</article>"""

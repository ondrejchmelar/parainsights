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
/* The renderer switch, for the standalone page — the report styles `.toggle` itself. */
.airspace-article .renderer-host { position: relative; }
.airspace-article .toggle { display:inline-flex; margin:0 0 8px; border:1px solid var(--rule);
  border-radius:3px; overflow:hidden; }
.airspace-article .toggle-button { font:inherit; font-size:11.5px; text-transform:uppercase;
  letter-spacing:.08em; padding:5px 12px; background:none; border:0; border-radius:0;
  color:var(--ink-3); cursor:pointer; }
.airspace-article .toggle-button + .toggle-button { border-left:1px solid var(--rule); }
.airspace-article .toggle-button.is-on { background:var(--ink); color:var(--paper); }
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
.asp-when-out { flex: 1 1 20em; min-width: 0; }
.asp-controls input[type="datetime-local"] { font: inherit; padding: 2px 6px;
  background: var(--panel); color: var(--ink); border: 1px solid var(--rule);
  border-radius: 3px; }
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
.asp-warn { flex: 1 1 100%; margin: 2px 0 0; padding: 9px 12px; font-size: 12.5px;
  line-height: 1.5; color: var(--ink-2); background: var(--panel-2);
  border-left: 3px solid #b45309; border-radius: 3px; }
.asp-warn strong { color: var(--ink); }
.asp-src { width: 100%; border-collapse: collapse; margin: 18px 0 0; font-size: 12.5px; }
.asp-src caption { text-align: left; font-size: 12.5px; font-weight: 600;
  color: var(--ink-2); padding: 0 0 6px; }
.asp-src th { text-align: left; font-weight: 600; font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-3);
  border-bottom: 1px solid var(--rule); padding: 0 10px 5px 0; }
.asp-src td { padding: 7px 10px 7px 0; border-bottom: 1px solid var(--rule);
  color: var(--ink-2); vertical-align: top; }
.asp-src a { color: inherit; text-decoration: underline;
  text-decoration-color: var(--ink-3); text-underline-offset: 2px; }
.asp-src a:hover { color: var(--ink); text-decoration-color: currentColor; }
.asp-src-key { color: var(--ink) !important; }
.asp-src-key .asp-swatch { margin-right: 5px; vertical-align: -1px; }
.asp-src-when { white-space: nowrap; font-variant-numeric: tabular-nums; }
"""

# Shared by the flat map, the 3D map and the planner, all three of which ask the same
# question of the same payload. It is its own IIFE rather than part of `SCRIPT` because
# `SCRIPT` returns immediately when there is no flat `<svg>` to drive, which is every
# page that draws the 3D view.
HOURS_SCRIPT = """
(function () {
  // The published hours are UTC and the reader thinks in Czech local time — two hours
  // apart for the whole flying season, which is a big enough error to be the very thing
  // this control exists to prevent. So the input is wall-clock Prague and the comparison
  // is UTC, with `Intl` doing the conversion rather than a hand-rolled DST rule.
  function pragueOffset(instant) {
    var parts = {};
    new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Prague', hour12: false, year: 'numeric', month: '2-digit',
      day: '2-digit', hour: '2-digit', minute: '2-digit'
    }).formatToParts(instant).forEach(function (part) { parts[part.type] = part.value; });
    var wall = Date.UTC(+parts.year, +parts.month - 1, +parts.day,
                        +parts.hour % 24, +parts.minute);
    return (wall - instant.getTime()) / 60000;
  }

  // Prague wall-clock to the instant it names. Twice round, because the first offset is
  // sampled at an instant that is wrong by the offset itself — which only matters within
  // an hour of a DST change, and the second pass lands.
  function fromPrague(text) {
    var m = /^(\\d{4})-(\\d{2})-(\\d{2})T(\\d{2}):(\\d{2})/.exec(text || '');
    if (!m) return null;
    var wall = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    var instant = wall;
    for (var i = 0; i < 2; i++) instant = wall - pragueOffset(new Date(instant)) * 60000;
    return new Date(instant);
  }

  function toPrague(instant) {
    var shifted = new Date(instant.getTime() + pragueOffset(instant) * 60000);
    return shifted.toISOString().slice(0, 16);
  }

  function inSeason(month, day, season) {
    var here = month * 100 + day;
    var from = season[0] * 100 + season[1], to = season[2] * 100 + season[3];
    return from <= to ? (here >= from && here <= to) : (here >= from || here <= to);
  }

  // True whenever nothing is known, which is the entire point: a ring with no schedule
  // is a ring this filter must not touch, and that is 251 base airspaces plus every one
  // of the 74 SLZ circuits. No instant answers the same way — the filter is off — and
  // every caller guards for that already, so this is one line to stop the next one
  // having to. The date is read in UTC, which is the AIP's own frame: its operating days
  // go with its operating hours, and both are published Zulu.
  function activeAt(schedule, instant, holidays) {
    if (!instant) return true;
    if (!schedule || !schedule.p || !schedule.p.length) return true;
    var month = instant.getUTCMonth() + 1, day = instant.getUTCDate();
    var weekday = (instant.getUTCDay() + 6) % 7;      // 0 = Monday, as the payload counts
    var minutes = instant.getUTCHours() * 60 + instant.getUTCMinutes();
    var stamp = instant.toISOString().slice(0, 10);
    var holiday = !!(holidays && holidays[stamp]);
    for (var i = 0; i < schedule.p.length; i++) {
      var period = schedule.p[i];
      if (period.s && !inSeason(month, day, period.s)) continue;
      if (period.d && period.d.indexOf(weekday) < 0 && !(period.h && holiday)) continue;
      if (period.w) {
        var from = period.w[0], to = period.w[1];
        var within = from <= to ? (minutes >= from && minutes < to)
                                : (minutes >= from || minutes < to);
        if (!within) continue;
      }
      return true;
    }
    return false;
  }

  var cachedHolidays = null;
  function holidays() {
    if (cachedHolidays) return cachedHolidays;
    var input = document.getElementById('asp-when');
    cachedHolidays = {};
    if (input && input.dataset.holidays) {
      input.dataset.holidays.split(',').forEach(function (day) {
        cachedHolidays[day] = true;
      });
    }
    return cachedHolidays;
  }

  // The instant the controls are asking about, or null when the filter is off.
  function chosen() {
    var box = document.getElementById('asp-when-on');
    var input = document.getElementById('asp-when');
    if (!box || !input || !box.checked) return null;
    return fromPrague(input.value);
  }

  function label(instant) {
    if (!instant) return '';
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Prague', weekday: 'short', day: 'numeric', month: 'short',
      hour: '2-digit', minute: '2-digit', hour12: false
    }).format(instant);
  }

  window.aspHours = { activeAt: activeAt, holidays: holidays, chosen: chosen,
                      toPrague: toPrague, label: label };

  // Open on the reader's own clock. The page is static and may be read months after it
  // was built, so a build-time default would be a date nobody asked about.
  var input = document.getElementById('asp-when');
  if (input && !input.value) input.value = toPrague(new Date());
  var now = document.getElementById('asp-when-now');
  if (now && input) now.addEventListener('click', function () {
    input.value = toPrague(new Date());
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
})();
"""

MAP_SCRIPT = """
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
    var when = window.aspHours ? window.aspHours.chosen() : null;
    var holidays = window.aspHours ? window.aspHours.holidays() : {};
    var shown = 0, dimmed = 0;
    svg.querySelectorAll('.asp-zone').forEach(function (zone) {
      var visible = on[zone.dataset.klass] !== false
        && Number(zone.dataset.floor) <= limit;
      if (visible && when) {
        var schedule = zone.dataset.hours ? JSON.parse(zone.dataset.hours) : null;
        if (!window.aspHours.activeAt(schedule, when, holidays)) {
          visible = false;
          dimmed++;
        }
      }
      zone.style.display = visible ? '' : 'none';
      if (visible) shown++;
    });
    var count = document.getElementById('asp-count');
    if (count) count.textContent = shown + ' shown';
    reportWhen(when, dimmed);
  }

  // Never silent. Hiding airspace without saying how much was hidden is the one thing
  // this control must not do, so the readout states the count even when it is zero.
  function reportWhen(when, dimmed) {
    var out = document.getElementById('asp-when-out');
    if (!out) return;
    if (!when) { out.textContent = ''; return; }
    out.textContent = dimmed
      ? dimmed + ' outside published hours at ' + window.aspHours.label(when)
      : 'every field with published hours is open at ' + window.aspHours.label(when);
  }

  document.querySelectorAll('[data-asp-class]').forEach(function (box) {
    box.addEventListener('change', refilter);
  });
  var slider = document.getElementById('asp-floor');
  if (slider) slider.addEventListener('input', refilter);
  var whenBox = document.getElementById('asp-when-on');
  var whenInput = document.getElementById('asp-when');
  if (whenBox) whenBox.addEventListener('change', refilter);
  if (whenInput) whenInput.addEventListener('input', refilter);

  // The label: hover on a mouse, tap-to-pin on a touchscreen.
  //
  // A touchscreen fires pointerover on touch-down and pointerout on touch-up, so a
  // hover-driven label appears and vanishes within the same tap — which is exactly
  // what it did. On touch the label is therefore pinned by a tap and dismissed by
  // tapping somewhere else, and it is placed *above* the finger, because a label under
  // the fingertip is a label you cannot read.
  function placeTip(x, y, above) {
    var holder = tip.parentNode.getBoundingClientRect();
    var left = x - holder.left + (above ? -tip.offsetWidth / 2 : 12);
    var top = y - holder.top + (above ? -tip.offsetHeight - 16 : 12);
    // Keep it inside the map rather than letting it hang off an edge.
    left = Math.max(4, Math.min(left, holder.width - tip.offsetWidth - 4));
    top = Math.max(4, top);
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }
  function showTip(zone, x, y, above) {
    tip.textContent = zone.dataset.label;
    tip.classList.add('is-on');
    placeTip(x, y, above);
  }
  function hideTip() { if (tip) tip.classList.remove('is-on'); }

  svg.addEventListener('pointerover', function (e) {
    if (!tip || e.pointerType === 'touch') return;
    var zone = e.target.closest('.asp-zone');
    if (zone) showTip(zone, e.clientX, e.clientY, false);
  });
  svg.addEventListener('pointermove', function (e) {
    if (!tip || e.pointerType === 'touch') return;
    if (tip.classList.contains('is-on')) placeTip(e.clientX, e.clientY, false);
  });
  svg.addEventListener('pointerout', function (e) {
    // Never on touch: pointerout there means the finger lifted, not that the label
    // stopped being wanted.
    if (!tip || e.pointerType === 'touch') return;
    if (!e.relatedTarget || !e.relatedTarget.closest('.asp-zone')) hideTip();
  });
  svg.addEventListener('pointerdown', function (e) {
    if (!tip || e.pointerType !== 'touch') return;
    var zone = e.target.closest('.asp-zone');
    if (zone) showTip(zone, e.clientX, e.clientY, true);
    else hideTip();
  });
  // A tap anywhere else in the document puts it away.
  document.addEventListener('pointerdown', function (e) {
    if (tip && e.pointerType === 'touch' && !svg.contains(e.target)) hideTip();
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
    return (
        '<div class="asp-controls">'
        '<label for="asp-when-on"><input type="checkbox" id="asp-when-on">'
        "Only fields open at</label>"
        f'<input type="datetime-local" id="asp-when" data-holidays="{calendar}" '
        'aria-label="date and time, Czech local">'
        '<button type="button" id="asp-when-now">now</button>'
        '<span class="asp-readout asp-when-out" id="asp-when-out"></span>'
        "</div>"
        f'<p class="asp-hint">{note}</p>'
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
        # The 3D view carries its own reset in the bar across the bottom of the canvas,
        # and two buttons that both say "reset" and do different amounts is worse than
        # one. There, this button clears the filters *and* presses that one.
        f'<button type="button" id="asp-reset">'
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
    aeroklub = _link(
        f"{sources.AEROKLUB_DIR}CZ_low_{base_version}.txt",
        "Aeroklub ČR — CZ_low, Jan Zahradka",
    )
    zone_links = ", ".join(
        _link(sources.RLP_ATZ.format(date=stamp, pub=pub), f"LKR315{pub}")
        for pub in sorted(overlay.by_publication)
    )
    rows = [
        (["base", "restricted"],
         "Controlled, restricted, danger, prohibited",
         aeroklub,
         _escape(base_version)),
        (["gliding"],
         "Gliding areas, dropzones, PGZ",
         aeroklub,
         _escape(base_version)),
        (["atz"],
         _atz_row(overlay, clipped, shift),
         f"{_link('https://aim.rlp.cz/', 'ŘLP ČR')} — UAS zones, {zone_links}",
         _escape(overlay.atz_date)),
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
        + f"{label}</td><td>{source}</td><td class='asp-src-when'>{when}</td></tr>"
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


SCRIPT3D = """
(function () {
  var article = document.querySelector('.airspace-article');
  var panel = article && article.querySelector('.view3d-panel');
  if (!panel || typeof initView3d !== 'function') return;
  // Built once, and shared: the planner on this page draws on the same handle
  // (`planner/render_html.py` waits on this promise). The ground is fetched at view time,
  // so in the report — where this view starts hidden behind its tab — nothing is fetched
  // until the reader opens it.
  function visible() { return panel.getClientRects().length > 0; }
  function whenVisible() {
    if (visible()) return Promise.resolve();
    return new Promise(function (resolve) {
      var watch = new MutationObserver(function () {
        if (visible()) { watch.disconnect(); resolve(); }
      });
      watch.observe(document.body, { attributes: true, subtree: true,
                                     attributeFilter: ['hidden', 'class', 'style'] });
    });
  }
  window.__airspaceMap = whenVisible().then(function () {
    return initView3dWhenReady(panel, null);
  }).then(function (handle) {
    if (handle) wire(handle);
    return handle;
  });

  function wire(handle) {
  var tip = document.getElementById('asp-name');
  var canvas = panel.querySelector('canvas.view3d');

  // The filter is a predicate handed to the view, not a pass over the DOM: on the flat
  // map every airspace was an SVG element with a `display` to set, and here they are
  // entries in a payload that the canvas redraws from scratch every frame.
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
    var when = window.aspHours ? window.aspHours.chosen() : null;
    var holidays = window.aspHours ? window.aspHours.holidays() : {};
    function open(space) {
      return !when || window.aspHours.activeAt(space.w, when, holidays);
    }
    var shown = 0, dimmed = 0;
    var spaces = handle.scene().airspaces || [];
    for (var i = 0; i < spaces.length; i++) {
      if (on[spaces[i].k] === false || spaces[i].f > limit) continue;
      if (open(spaces[i])) shown++; else dimmed++;
    }
    var count = document.getElementById('asp-count');
    if (count) count.textContent = shown + ' shown';
    var says = document.getElementById('asp-when-out');
    if (says) {
      says.textContent = !when ? ''
        : (dimmed ? dimmed + ' outside published hours at ' + window.aspHours.label(when)
                  : 'every field with published hours is open at '
                    + window.aspHours.label(when));
    }
    handle.setAirspaceFilter(function (space) {
      return on[space.k] !== false && space.f <= limit && open(space);
    });
  }
  document.querySelectorAll('[data-asp-class]').forEach(function (box) {
    box.addEventListener('change', refilter);
  });
  var slider = document.getElementById('asp-floor');
  if (slider) slider.addEventListener('input', refilter);
  var whenBox = document.getElementById('asp-when-on');
  var whenInput = document.getElementById('asp-when');
  if (whenBox) whenBox.addEventListener('change', refilter);
  if (whenInput) whenInput.addEventListener('input', refilter);

  // Hover on a mouse, tap-to-pin on a touchscreen — the same split the flat map made,
  // and for the same reason: a touchscreen's pointerout means the finger lifted, not
  // that the label stopped being wanted. Not while a gesture is running, or every drag
  // would fight the label for the frame.
  function placeTip(x, y, above) {
    var holder = tip.parentNode.getBoundingClientRect();
    var left = x - holder.left + (above ? -tip.offsetWidth / 2 : 12);
    var top = y - holder.top + (above ? -tip.offsetHeight - 16 : 12);
    left = Math.max(4, Math.min(left, holder.width - tip.offsetWidth - 4));
    tip.style.left = left + 'px';
    tip.style.top = Math.max(4, top) + 'px';
  }
  function show(space, x, y, above) {
    tip.textContent = space.n;
    tip.classList.add('is-on');
    placeTip(x, y, above);
  }
  function hide() { if (tip) tip.classList.remove('is-on'); }

  if (canvas && tip) {
    canvas.addEventListener('pointermove', function (e) {
      if (e.pointerType === 'touch' || e.buttons) return;
      var space = handle.airspaceAt(e.clientX, e.clientY);
      if (space) show(space, e.clientX, e.clientY, false); else hide();
    });
    canvas.addEventListener('pointerleave', hide);
    canvas.addEventListener('pointerdown', function (e) {
      // While a task is being drawn a tap is a turnpoint, not a question.
      if (e.pointerType !== 'touch' || article.dataset.drawing === 'on') return;
      var space = handle.airspaceAt(e.clientX, e.clientY);
      if (space) show(space, e.clientX, e.clientY, true); else hide();
    });
    document.addEventListener('pointerdown', function (e) {
      if (tip && e.pointerType === 'touch' && !panel.contains(e.target)) hide();
    });
  }

  var reset = document.getElementById('asp-reset');
  if (reset) reset.addEventListener('click', function () {
    document.querySelectorAll('[data-asp-class]').forEach(function (box) {
      box.checked = true;
    });
    if (slider) slider.value = slider.dataset.top;
    if (whenBox) whenBox.checked = false;
    refilter();
    var act = panel.querySelector('[data-view3d-act="reset"]');
    if (act) act.click();
  });

  refilter();

  // Open on the renderer the host asks for, and fall back to the canvas if MapLibre
  // cannot be fetched — offline, or blocked — rather than leaving a panel that says so.
  var host = panel.closest('.renderer-host');
  var wanted = host && host.dataset.rendererDefault;
  var button = wanted && host.querySelector('[data-renderer="' + wanted + '"]');
  if (button && window.__mapLibs) {
    button.click();
    window.__mapLibs().catch(function () {
      var canvasButton = host.querySelector('[data-renderer="canvas"]');
      if (canvasButton) canvasButton.click();
    });
  }
  }
})();
"""


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
    airspaces = list(base) + list(overlay.airspaces)
    rings = [a.points for a in airspaces if a.points] + [basemap.BORDER]
    project = Projection(_bounds(rings))
    east, north, samples = overlay.offset
    shift = math.hypot(east, north)
    top = int(math.ceil(max(floor_metres(a) for a in airspaces) / 50.0) * 50)

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

    return f"""<article class="flight airspace-article" id="{uid}-article"{plan_attr}>
  <h1>Airspace and task planner</h1>
  <p class="lede">Everything the published airspace carries, plus the airfields it leaves
  out: a zone around each of the {overlay.atz_count} public aerodromes, and the traffic
  circuit at {overlay.circuit_fields} fields and ultralight strips. A paraglider may fly
  inside the zone but must stay out of the circuit, and no instrument draws either.
  Scroll to zoom, drag to pan, hover for the name and limits.{boxes}{plan_lede}</p>
  {controls(top, flat=scene is None)}
  {plan_bar}
  <div class="asp-holder">
    {_map(airspaces, project, scene, uid)}
    <div class="asp-name" id="asp-name"></div>
  </div>
  {plan_results}
  {download}
  {sources_table(overlay, base_version, shift)}
</article>"""


def _map(airspaces, project, scene: dict | None, uid: str) -> str:
    """The map itself: the 3D view where a scene was built for it, the flat SVG where
    one could not be — no network at build time, or no Pillow to stitch imagery with.

    The fallback is not a courtesy. The 3D view needs an elevation grid and a stitched
    basemap, both fetched, and the one thing this page must never do is fail to draw the
    airspace because a tile server was slow."""
    if scene is None:
        return map_svg(airspaces, project)
    from tracklog_viewer import view3d

    # The exaggeration this map offers, and it starts at x5. At true scale over 500 km
    # of country a 300 m traffic circuit is **0.3 px** tall and an ATZ 0.7 px, so every
    # box is two coincident rings — the flat map with extra steps. x1 is still one press
    # away and the segmented control says which is on, so nothing here is hidden; what is
    # hidden at true scale is the entire point of the view.
    from tracklog_viewer import render_map

    # The flights' renderer switch, opening on the merged map (MapLibre's engine under
    # the canvas's controls), which the planner draws on too. The canvas stays one press
    # away, and is what the page falls back to when MapLibre cannot be fetched.
    return ('<div class="renderer-host" data-renderer-default="merged">'
            + render_map.switch_html()
            + view3d.panel(scene, uid, verticals=(1, 5, 15), vertical=5)
            + "</div>")

"""SVG chart generation.

Everything is rendered locally into inline SVG. igc2kmz built its graphs as Google
Image Charts URLs and that service was switched off in 2019, so every chart in its
output is now a broken image — the lesson being that a chart should not depend on a
network service that outlives neither the flight nor the tool.
"""

import math
from dataclasses import dataclass

import numpy as np

from . import geo
from .analysis import Analysis, Phase

# Diverging ramp for climb rate: warm = up, cool = down, neutral gray midpoint.
# Matches the vario convention, and is the pairing that reads as opposite.
CLIMB_RAMP = [
    (-4.0, "var(--sink-3)"),
    (-2.0, "var(--sink-2)"),
    (-0.7, "var(--sink-1)"),
    (0.7, "var(--neutral)"),
    (2.0, "var(--climb-1)"),
    (4.0, "var(--climb-2)"),
    (float("inf"), "var(--climb-3)"),
]

PHASE_COLOR = {
    Phase.THERMAL: "var(--climb)",
    Phase.GLIDE: "var(--sink)",
    Phase.TOW: "var(--tow)",
    Phase.DIVE: "var(--sink-3)",
    Phase.UNKNOWN: "var(--neutral)",
}


def _with_headroom(ceiling: float, data_max: float, meteo) -> float:
    """Raise a chart's altitude ceiling to fit the meteo reference lines.

    Capped at 1 000 m above the data: a cloudbase far above where the pilot flew
    should not squash the trace into the bottom of the panel to make room for a
    line nobody needs to see.
    """
    if meteo is None:
        return ceiling
    for value in (getattr(meteo, "boundary_layer_top", None), getattr(meteo, "cloudbase", None)):
        if value is not None and ceiling < value <= data_max + 1000:
            ceiling = math.ceil(value / 100) * 100
    return ceiling


def _cursor_layer(px, py, sample, left, top, plot_w, plot_h, *, mode: str = "x") -> str:
    """A hit area carrying its own projected sample coordinates, plus a cursor dot.

    The coordinates travel with the chart rather than being recomputed in JavaScript:
    every chart already knows its own projection, and duplicating that maths in the
    browser is how linked cursors drift apart from the thing they point at.
    """
    if sample is None or not len(sample):
        return ""
    xs = ",".join(f"{px[i]:.1f}" for i in sample)
    ys = ",".join(f"{py[i]:.1f}" for i in sample)
    return (
        f'<g class="cursor"><circle class="cursor-dot" cx="{left}" cy="{top}" r="4.5" /></g>'
        f'<rect class="hit" x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" '
        f'data-mode="{mode}" data-px="{xs}" data-py="{ys}" />'
    )


def climb_color(value: float) -> str:
    for threshold, color in CLIMB_RAMP:
        if value < threshold:
            return color
    return CLIMB_RAMP[-1][1]


def escape(text) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def decimate(x: np.ndarray, y: np.ndarray, tolerance: float) -> np.ndarray:
    """Douglas–Peucker, returning the indices to keep.

    Iterative rather than recursive so a 30 000-fix flight cannot blow the stack.
    """
    keep = np.zeros(len(x), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(x) - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        px, py = x[start], y[start]
        qx, qy = x[end], y[end]
        dx, dy = qx - px, qy - py
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        # Perpendicular distance of every interior point from the chord.
        segment = slice(start + 1, end)
        distances = np.abs(dy * (x[segment] - px) - dx * (y[segment] - py)) / length
        if not distances.size:
            continue
        worst = int(np.argmax(distances))
        if distances[worst] > tolerance:
            index = start + 1 + worst
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return np.flatnonzero(keep)


@dataclass
class Oblique:
    """Axonometric projection: metres east/north/up to SVG coordinates.

    Altitude is exaggerated — a 59 km flight climbing 1.7 km would otherwise
    render as a flat line, which is exactly the reading problem the shadow and
    drop-lines exist to solve.
    """

    scale: float  # px per metre horizontally
    z_scale: float  # px per metre vertically
    shear_x: float  # fraction of a projected northward metre that goes right
    shear_y: float  # fraction of a projected northward metre that goes up
    origin_x: float
    origin_y: float
    z_ref: float

    def project(self, x, y, z):
        # The shear is a fraction of the *projected* north offset, not of raw
        # metres — otherwise a wide flight's north spread swamps the box and
        # crushes the altitude scale to nothing.
        sx = self.origin_x + self.scale * (x + self.shear_x * y)
        sy = self.origin_y - self.z_scale * (z - self.z_ref) - self.scale * self.shear_y * y
        return sx, sy

    @property
    def exaggeration(self) -> float:
        return self.z_scale / self.scale


def _polyline_by_climb(points, climb, colors_used: set) -> list[str]:
    """Emit one path per run of constant climb colour, so the track is a handful
    of paths rather than thousands of two-point segments."""
    parts: list[str] = []
    if len(points) < 2:
        return parts
    current = climb_color(climb[0])
    run = [points[0]]
    for index in range(1, len(points)):
        color = climb_color(climb[index])
        run.append(points[index])
        if color != current:
            colors_used.add(current)
            coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in run)
            parts.append(f'<polyline points="{coords}" stroke="{current}" />')
            run = [points[index]]
            current = color
    if len(run) > 1:
        colors_used.add(current)
        coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in run)
        parts.append(f'<polyline points="{coords}" stroke="{current}" />')
    return parts


PROFILE_MODES = {
    "flown": (
        "distance flown, km — always increasing, so a climb draws as a near-vertical step",
        "distance flown",
    ),
    "from_start": (
        "straight-line distance from launch, km — the trace doubles back on a return leg",
        "distance from launch",
    ),
    "time": (
        "time of day — the classic barogram: time on the ground axis, height above",
        "time",
    ),
}


def altitude_profile(analysis: Analysis, *, width: int = 1080, height: int = 420,
                     meteo=None, mode: str = "flown", sample=None) -> str:
    """Altitude against distance, either flown along the track or from the launch point.

    Deliberately *not* an oblique projection of position: projecting east/north onto
    one screen axis makes the trace fold back over itself on every return leg, which
    reads as a drawing error rather than as information.

    ``flown`` is the default because it only ever increases, so the axis can be
    labelled in kilometres and believed. ``from_start`` is offered as a toggle: on an
    out-and-return or a triangle it genuinely does double back, and seeing the outbound
    and homebound legs stacked over each other is the point — you can compare how high
    you were at the same place on the way out and the way home.
    """
    series = analysis.series
    flight = analysis.flight
    left, right, top, bottom = 56, 20, 20, 46
    plot_w = width - left - right
    plot_h = height - top - bottom

    if mode == "from_start":
        s = geo.distance(flight.lat[0], flight.lon[0], flight.lat, flight.lon)
    elif mode == "time":
        s = series.t
    else:
        s = series.s
    z = series.alt
    s_max = max(float(s.max()), 1.0)
    z_floor = math.floor(z.min() / 100) * 100
    z_ceiling = _with_headroom(math.ceil(z.max() / 100) * 100, z.max(), meteo)

    def sx(value):
        return left + plot_w * value / s_max

    def sy(value):
        return top + plot_h * (1 - (value - z_floor) / max(z_ceiling - z_floor, 1))

    px, py = sx(s), sy(z)
    keep = decimate(px, py, 0.5)
    colors_used: set[str] = set()
    track = _polyline_by_climb([(px[i], py[i]) for i in keep], series.climb[keep], colors_used)

    baseline = top + plot_h

    # Detected phases shaded behind the trace. This is what the separate barogram used
    # to carry; with a time axis available here, two charts of the same quantity against
    # near-identical axes was one chart too many.
    bands = []
    for segment in analysis.segments:
        x0, x1 = sx(float(s[segment.start])), sx(float(s[segment.stop - 1]))
        bands.append(
            f'<rect class="band band-{segment.phase.value}" data-segment="{segment.start}" '
            f'x="{x0:.1f}" y="{top}" width="{max(x1 - x0, 1):.1f}" height="{plot_h}" />'
        )

    drops = []
    step = max(int(len(s) / 110), 1)
    for i in range(0, len(s), step):
        drops.append(
            f'<line x1="{px[i]:.1f}" y1="{py[i]:.1f}" x2="{px[i]:.1f}" y2="{baseline}" />'
        )

    grid, labels = [], []
    for value in range(int(math.ceil(z_floor / 500) * 500), int(z_ceiling) + 1, 500):
        y = sy(value)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" />')
        labels.append(
            f'<text x="{left - 10}" y="{y + 3.5:.1f}" class="axis-label axis-y">{value}</text>'
        )

    ticks = []
    if mode == "time":
        # Quarter-hour marks on the local clock.
        quarter = 900
        takeoff = flight.local_time(0)
        first = (-takeoff.minute % 15) * 60 - takeoff.second
        tick = first if first > 0 else first + quarter
        while tick <= s_max:
            x = sx(tick)
            clock = flight.local_time(int(np.searchsorted(series.t, tick)))
            ticks.append(
                f'<line class="tick" x1="{x:.1f}" y1="{baseline}" x2="{x:.1f}" '
                f'y2="{baseline + 4}" />'
                f'<text x="{x:.1f}" y="{baseline + 17}" class="axis-label axis-x">'
                f'{clock.strftime("%H:%M")}</text>'
            )
            tick += quarter
    else:
        # Distance ticks on a round step that yields roughly ten of them.
        step_km = max(round(s_max / 1000 / 10), 1)
        if step_km > 7:
            step_km = round(step_km / 5) * 5
        km = 0
        while km * 1000 <= s_max:
            x = sx(km * 1000)
            ticks.append(
                f'<line class="tick" x1="{x:.1f}" y1="{baseline}" x2="{x:.1f}" '
                f'y2="{baseline + 4}" />'
                f'<text x="{x:.1f}" y="{baseline + 17}" class="axis-label axis-x">{km}</text>'
            )
            km += step_km

    references = []
    if meteo is not None:
        candidates = [
            (value, label)
            for value, label in (
                (meteo.boundary_layer_top, "boundary layer top"),
                (meteo.cloudbase, "cloudbase"),
            )
            if value is not None and z_floor < value < z_ceiling
        ]
        # Cloudbase and boundary layer top are often within 100 m of each other, so
        # alternate which end of the line the label hangs from.
        for index, (value, label) in enumerate(candidates):
            y = sy(value)
            if index % 2:
                anchor = f'x="{left + 6}" class="reference-label band-label"'
            else:
                anchor = f'x="{width - right - 4}" class="reference-label"'
            references.append(
                f'<line class="reference" x1="{left}" y1="{y:.1f}" x2="{width - right}" '
                f'y2="{y:.1f}" />'
                f'<text {anchor} y="{y - 6:.1f}">{label} {value:.0f} m</text>'
            )

    markers = []
    number = 0
    for segment in analysis.segments:
        if segment.phase not in (Phase.THERMAL, Phase.TOW):
            continue
        mid = (segment.start + segment.stop) // 2
        mx, my = sx(s[mid]), sy(z[mid])
        if segment.phase is Phase.TOW:
            label, color = "T", "var(--tow)"
        else:
            number += 1
            label, color = str(number), "var(--climb)"
        markers.append(
            f'<g class="mark" data-segment="{segment.start}">'
            f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="9" fill="var(--panel)" stroke="{color}" />'
            f'<text x="{mx:.1f}" y="{my + 3.4:.1f}" class="mark-label">{label}</text>'
            f"</g>"
        )

    axis_title, short_title = PROFILE_MODES.get(mode, PROFILE_MODES["flown"])

    return f"""<svg viewBox="0 0 {width} {height}" class="chart chart-profile" role="img"
     aria-label="Altitude against {short_title}, coloured by climb rate, with climbs numbered">
  <g class="bands">{"".join(bands)}</g>
  <g class="grid">{"".join(grid)}</g>
  <g class="drops">{"".join(drops)}</g>
  <g class="references">{"".join(references)}</g>
  <g class="track">{"".join(track)}</g>
  <g class="endpoints">
    <circle cx="{px[0]:.1f}" cy="{py[0]:.1f}" r="4.5" class="endpoint" />
    <circle cx="{px[-1]:.1f}" cy="{py[-1]:.1f}" r="4.5" class="endpoint" />
    <text x="{min(px[-1], width - right - 26):.1f}" y="{py[-1] + 20:.1f}"
          class="endpoint-label">landing</text>
  </g>
  <g class="marks">{"".join(markers)}</g>
  <g class="cursor">
    <line class="crosshair" x1="{left}" x2="{left}" y1="{top}" y2="{baseline}" />
  </g>
  {_cursor_layer(px, py, sample, left, top, plot_w, plot_h)}
  <g class="axes">
    <line x1="{left}" y1="{baseline}" x2="{width - right}" y2="{baseline}" />
    {"".join(ticks)}{"".join(labels)}
    <text x="{left + plot_w / 2:.1f}" y="{height - 8}" class="axis-title">{axis_title}</text>
    <text x="{14}" y="{top + plot_h / 2:.1f}" class="axis-title"
          transform="rotate(-90 14 {top + plot_h / 2:.1f})">altitude m</text>
  </g>
</svg>"""


def plan_height(analysis: Analysis, *, width: int = 1080, floor: int = 260,
                ceiling: int = 620) -> int:
    """Panel height that matches the flight's own aspect ratio.

    A fixed short panel squashes a triangle or an out-and-return into a letterbox while
    a straight-line flight rattles around in it. Deriving the height from the data keeps
    the scale honest — no vertical stretching — and gives round flights the room they
    need.
    """
    series = analysis.series
    span_x = max(float(series.x.max() - series.x.min()), 1.0)
    span_y = max(float(series.y.max() - series.y.min()), 1.0)
    return int(min(max(round(width * span_y / span_x) + 70, floor), ceiling))


def plan_view(analysis: Analysis, *, width: int = 1080, height: int = 230, route=None,
              sample=None) -> str:
    """The route over the ground, coloured by climb.

    The side view shows how high; this shows where. On a straight-line flatland
    flight the two are genuinely different pictures — the side view cannot show
    that the course line wandered north around the middle of the flight.
    """
    series = analysis.series
    pad = 26
    x, y = series.x, series.y
    span_x = max(x.max() - x.min(), 1.0)
    span_y = max(y.max() - y.min(), 1.0)
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad - 20) / span_y)

    # Centre the track in both directions: an XC flight is a long thin shape and
    # whichever axis does not set the scale would otherwise sit against one edge.
    offset_x = ((width - 2 * pad) - span_x * scale) / 2
    offset_y = ((height - 2 * pad - 20) - span_y * scale) / 2

    def project(px, py):
        return (
            pad + offset_x + (px - x.min()) * scale,
            height - pad - 16 - offset_y - (py - y.min()) * scale,
        )

    sx, sy = project(x, y)
    keep = decimate(sx, sy, 0.5)
    colors_used: set[str] = set()
    track = _polyline_by_climb([(sx[i], sy[i]) for i in keep], series.climb[keep], colors_used)

    markers = []
    number = 0
    for segment in analysis.segments:
        if segment.phase not in (Phase.THERMAL, Phase.TOW):
            continue
        mid = (segment.start + segment.stop) // 2
        mx, my = project(x[mid], y[mid])
        if segment.phase is Phase.TOW:
            markers.append(
                f'<g class="mark" data-segment="{segment.start}">'
                f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="6" fill="var(--panel)" '
                f'stroke="var(--tow)" /></g>'
            )
            continue
        number += 1
        # Two encodings of the same climbs, one visible at a time: height gained finds
        # the big climbs, average rate finds the good ones — which are not the same
        # thing, since a long weak climb can out-gain a short strong one.
        by_gain = 3.5 + 6.0 * min(segment.altitude_change / 1200, 1.0)
        by_rate = 3.5 + 6.0 * min(max(segment.average_climb, 0) / 3.0, 1.0)
        colour = climb_color(segment.average_climb)
        title = (
            f"climb {number}: {segment.altitude_change:+.0f} m at "
            f"{segment.average_climb:+.2f} m/s"
        )
        markers.append(
            f'<g class="mark" data-segment="{segment.start}">'
            f'<circle class="plan-thermal plan-by-gain" cx="{mx:.1f}" cy="{my:.1f}" '
            f'r="{by_gain:.1f}" fill="{colour}" />'
            f'<circle class="plan-thermal plan-by-rate" cx="{mx:.1f}" cy="{my:.1f}" '
            f'r="{by_rate:.1f}" fill="{colour}" />'
            f"<title>{title}</title></g>"
        )

    # The optimised free-distance route, drawn as the straight legs it is scored on.
    xc_route = ""
    if route is not None and len(route.points) >= 2:
        legs = []
        for a, b in zip(route.points, route.points[1:]):
            ax, ay = project(x[a.index], y[a.index])
            bx, by = project(x[b.index], y[b.index])
            legs.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" />')
        corners = "".join(
            f'<rect x="{project(x[p.index], y[p.index])[0] - 3:.1f}" '
            f'y="{project(x[p.index], y[p.index])[1] - 3:.1f}" width="6" height="6" />'
            for p in route.points
        )
        xc_route = f'<g class="xc-route">{"".join(legs)}{corners}</g>'

    bar_km = max(round(span_x / 1000 / 3), 1)
    bar_px = bar_km * 1000 * scale
    bar_y = height - 10
    north_x, north_y = width - pad + 4, pad + 4

    return f"""<svg viewBox="0 0 {width} {height}" class="chart chart-plan" role="img"
     aria-label="Plan view of the course line, coloured by climb rate, with climbs marked
     and the scored free-distance route">
  {xc_route}
  <g class="track">{"".join(track)}</g>
  <g class="marks">{"".join(markers)}</g>
  <circle cx="{sx[0]:.1f}" cy="{sy[0]:.1f}" r="4" class="endpoint" />
  <circle cx="{sx[-1]:.1f}" cy="{sy[-1]:.1f}" r="4" class="endpoint" />
  <g class="compass">
    <line x1="{north_x}" y1="{north_y + 22}" x2="{north_x}" y2="{north_y}" />
    <path d="M{north_x - 3.5},{north_y + 5} L{north_x},{north_y} L{north_x + 3.5},{north_y + 5}" />
    <text x="{north_x}" y="{north_y + 34}" class="axis-label axis-x">N</text>
  </g>
  <g class="scalebar">
    <line x1="{pad}" y1="{bar_y}" x2="{pad + bar_px:.1f}" y2="{bar_y}" />
    <text x="{pad + bar_px + 7:.1f}" y="{bar_y + 3.5}" class="axis-label">{bar_km} km</text>
  </g>
  {_cursor_layer(sx, sy, sample, 0, 0, width, height, mode="xy")}
</svg>"""


def budget_bar(analysis: Analysis, *, width: int = 460, height: int = 58) -> str:
    """How the airtime was spent: one stacked bar, 2 px surface gaps.

    The last slice used to be one grey block called "other", which on a real flight is
    forty unexplained minutes — and it is the slice most worth knowing, because the
    transitions live in it. `analysis.other` already measures it three ways, so the bar
    shows those instead of their total: sink flown straight, turning that did not climb,
    and rising air no phase claimed.
    """
    fractions = analysis.budget.fractions()
    order = [
        ("towing", "var(--tow)", "tow"),
        ("thermalling", "var(--climb)", "climbing"),
        ("gliding", "var(--sink)", "gliding"),
    ]
    slice_ = getattr(analysis, "other", None)
    total = analysis.budget.total or 1
    if slice_ is not None and slice_.seconds:
        # Sub-shares of the same airtime, so they stack against the phases on one scale.
        # Any rounding remainder rides with the largest of the three rather than becoming
        # a fourth sliver: three parts rounded to the second are not guaranteed to
        # reproduce the budget's own `other`, and a three-second grey gap is not
        # information.
        split = {
            "other_sink": slice_.straight_sink / total,
            "other_scratch": slice_.scratching / total,
            "other_rising": slice_.rising / total,
        }
        biggest = max(split, key=lambda key: split[key])
        split[biggest] += fractions["other"] - sum(split.values())
        fractions = {**fractions, **split}
        order += [
            ("other_sink", "var(--neutral)", "sinking"),
            ("other_scratch", "var(--shadow-ink)", "scratching"),
            ("other_rising", "var(--climb-1)", "drifting up"),
        ]
    else:
        order.append(("other", "var(--neutral)", "other"))
    gap = 2
    bar_h = 26
    parts, labels = [], []
    x = 0.0
    total_gaps = gap * (sum(1 for key, _, _ in order if fractions[key] > 0) - 1)
    usable = width - total_gaps
    for key, color, label in order:
        fraction = fractions[key]
        if fraction <= 0:
            continue
        w = usable * fraction
        parts.append(
            f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{bar_h}" rx="3" fill="{color}" />'
        )
        if fraction > 0.06:
            # Keep the label inside the viewBox: a centred label on the last
            # segment otherwise runs off the right edge and gets clipped.
            label_x = min(max(x + w / 2, 26.0), width - 26.0)
            labels.append(
                f'<text x="{label_x:.1f}" y="{bar_h + 18}" class="budget-label">'
                f'{label} {fraction * 100:.0f}%</text>'
            )
        x += w + gap
    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart chart-budget" role="img" '
        f'aria-label="Share of airtime spent climbing, gliding and under tow">'
        f'{"".join(parts)}{"".join(labels)}</svg>'
    )


def wind_profile(analysis: Analysis, *, width: int = 620, height: int = 350, meteo=None,
                 uid: str = "") -> str:
    """Wind measured in each thermal, against the altitude of that thermal.

    Each point is one climb, labelled with the time it was flown: the drift of the
    circles gives the air's motion at that height, so an afternoon's climbs are a
    wind sounding taken by the glider. When model data is supplied it is drawn behind
    as a reference line, which is the honest way to show that an inferred quantity
    agrees — or does not — with an independent source.
    """
    thermals = [s for s in analysis.thermals if s.wind and s.turns and s.turns >= 2]
    if not thermals:
        return ""
    left, right, top, bottom = 52, 58, 22, 42
    plot_w = width - left - right
    plot_h = height - top - bottom

    speeds = [s.wind.kmh for s in thermals]
    altitudes = [(s.start_altitude + s.finish_altitude) / 2 for s in thermals]
    model_levels = []
    if meteo is not None:
        model_levels = [
            level
            for level in meteo.levels
            if min(altitudes) - 400 <= level.height <= max(altitudes) + 400
        ]
    speed_max = max(
        math.ceil(max(speeds + [level.wind_speed for level in model_levels]) / 5) * 5, 10
    )
    alt_min = math.floor(min(altitudes + [level.height for level in model_levels]) / 250) * 250
    alt_max = math.ceil(max(altitudes + [level.height for level in model_levels]) / 250) * 250

    def sx(value):
        return left + plot_w * value / speed_max

    def sy(value):
        return top + plot_h * (1 - (value - alt_min) / max(alt_max - alt_min, 1))

    grid, labels = [], []
    for value in range(0, int(speed_max) + 1, 5):
        x = sx(value)
        grid.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" />')
        labels.append(
            f'<text x="{x:.1f}" y="{top + plot_h + 17}" class="axis-label axis-x">{value}</text>'
        )
    # Every 250 m: the whole point of the chart is how wind changes with height, so
    # the height axis needs enough labels to read a value off it.
    for value in range(int(alt_min), int(alt_max) + 1, 250):
        y = sy(value)
        labels.append(
            f'<text x="{left - 9}" y="{y + 3.5:.1f}" class="axis-label axis-y">{value}</text>'
        )
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" />')

    model = ""
    if len(model_levels) >= 2:
        path = " ".join(f"{sx(l.wind_speed):.1f},{sy(l.height):.1f}" for l in model_levels)
        dots = "".join(
            f'<circle cx="{sx(l.wind_speed):.1f}" cy="{sy(l.height):.1f}" r="2.5" '
            f'class="model-dot"><title>model {l.wind_speed:.0f} km/h from '
            f'{l.wind_direction:.0f}° at {l.height:.0f} m ({l.pressure} hPa)</title></circle>'
            for l in model_levels
        )
        model = f'<g class="model"><polyline points="{path}" />{dots}</g>'

    # Lay the time labels out greedily: with eleven climbs in a small panel the
    # naive "just offset it upward" approach produces unreadable overlaps.
    # Each point carries its climb number rather than its clock time. Eleven times
    # inside a 6 km/h spread cannot be laid out without collisions, and the numbers
    # tie every point to the row in the climbs table — where the time is exact.
    # The first and last climbs keep their times, to anchor the sequence in the day.
    numbers = {segment.start: index for index, segment in enumerate(analysis.thermals, start=1)}
    points = []
    for position, (segment, speed, altitude) in enumerate(zip(thermals, speeds, altitudes)):
        x, y = sx(speed), sy(altitude)
        angle = math.radians((segment.wind.direction + 180) % 360)
        # Start the tail at the edge of the dot, not its centre, or the dot swallows
        # the only thing that carries direction.
        unit_x, unit_y = math.sin(angle), -math.cos(angle)
        start_x, start_y = x + unit_x * 9, y + unit_y * 9
        dx, dy = unit_x * 22, unit_y * 22
        time_label = ""
        if position in (0, len(thermals) - 1):
            anchor = "end" if x > left + plot_w * 0.6 else "start"
            offset = -13 if anchor == "end" else 13
            time_label = (
                f'<text x="{x + offset:.1f}" y="{y + 3.5:.1f}" class="wind-time" '
                f'text-anchor="{anchor}">{escape(segment.start_time[:5])}</text>'
            )
        points.append(
            f'<g class="wind-point" data-segment="{segment.start}">'
            f'<line x1="{start_x:.1f}" y1="{start_y:.1f}" x2="{x + dx:.1f}" y2="{y + dy:.1f}" '
            f'class="wind-arrow" marker-end="url(#arrow{uid})" />'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8.5" class="wind-dot" />'
            f'<text x="{x:.1f}" y="{y + 3.4:.1f}" class="wind-number">'
            f'{numbers.get(segment.start, "")}</text>'
            f"{time_label}"
            f'<title>climb {numbers.get(segment.start, "")} at '
            f'{escape(segment.start_time)} — {speed:.0f} km/h from '
            f'{escape(segment.wind.cardinal)} at {altitude:.0f} m</title>'
            f"</g>"
        )

    return f"""<svg viewBox="0 0 {width} {height}" class="chart chart-wind" role="img"
     aria-label="Wind speed measured in each thermal against altitude, with the model
     wind profile for comparison">
  <defs>
    <marker id="arrow{uid}" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="5" markerHeight="5"
            orient="auto"><path d="M0,1 L7,4 L0,7 z" fill="var(--sink)" /></marker>
  </defs>
  <g class="grid">{"".join(grid)}</g>
  {model}
  <g class="axes">{"".join(labels)}
    <text x="{left + plot_w / 2:.1f}" y="{height - 5}" class="axis-title">wind km/h</text>
    <text x="{12}" y="{top + plot_h / 2:.1f}" class="axis-title"
          transform="rotate(-90 12 {top + plot_h / 2:.1f})">altitude m</text>
  </g>
  {"".join(points)}
</svg>"""


def sounding(meteo, analysis: Analysis, *, width: int = 620, height: int = 350,
             uid: str = "") -> str:
    """Temperature and dew point against altitude, with the flight's band overlaid.

    A stripped-down sounding rather than a skew-T: for a paraglider the questions are
    how high the lift should have gone and where the air went stable, and both are
    answered by the dry adiabat crossing the environmental curve.
    """
    if meteo is None or not meteo.levels:
        return ""
    left, right, top, bottom = 52, 20, 22, 42
    plot_w = width - left - right
    plot_h = height - top - bottom

    summary = analysis.summary
    # Compare against GPS-referenced altitude: the model heights are geometric, while
    # the baro trace is ISA-referenced and sits offset from it.
    offset = summary.baro_offset or 0
    flight_top = summary.max_altitude + offset
    flight_bottom = summary.min_altitude + offset

    alt_max = math.ceil(max(flight_top + 300, meteo.cloudbase + 200) / 500) * 500
    alt_min = math.floor(min(flight_bottom, meteo.elevation) / 500) * 500
    # Levels inside the window set the temperature scale; one level beyond each end
    # is carried so the lines reach the frame instead of stopping short. Anything
    # further out would stretch the scale for air nobody flew in.
    inside = [l for l in meteo.levels if alt_min <= l.height <= alt_max]
    if len(inside) < 2:
        return ""
    below = [l for l in meteo.levels if l.height < alt_min]
    above = [l for l in meteo.levels if l.height > alt_max]
    levels = ([below[-1]] if below else []) + inside + ([above[0]] if above else [])

    temps = [l.temperature for l in inside] + [l.dew_point for l in inside]
    t_min = math.floor(min(temps + [meteo.surface_dew_point]) / 5) * 5
    t_max = math.ceil(max(temps + [meteo.surface_temperature]) / 5) * 5

    def sx(value):
        return left + plot_w * (value - t_min) / max(t_max - t_min, 1)

    def sy(value):
        return top + plot_h * (1 - (value - alt_min) / max(alt_max - alt_min, 1))

    grid, labels = [], []
    for value in range(int(t_min), int(t_max) + 1, 5):
        x = sx(value)
        grid.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" />')
        labels.append(
            f'<text x="{x:.1f}" y="{top + plot_h + 17}" class="axis-label axis-x">{value}</text>'
        )
    for value in range(int(alt_min), int(alt_max) + 1, 500):
        y = sy(value)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" />')
        labels.append(
            f'<text x="{left - 9}" y="{y + 3.5:.1f}" class="axis-label axis-y">{value}</text>'
        )

    environment = " ".join(f"{sx(l.temperature):.1f},{sy(l.height):.1f}" for l in levels)
    dewpoint = " ".join(f"{sx(l.dew_point):.1f},{sy(l.height):.1f}" for l in levels)

    # The dry adiabat a surface thermal follows, from the model's ground temperature.
    # Note the loop variable is not called `height`: that is the SVG's own height
    # parameter, and shadowing it puts a 3 000-unit viewBox on the chart.
    adiabat_points = []
    altitude = meteo.elevation
    while altitude <= alt_max:
        temperature = meteo.surface_temperature - 9.8 / 1000 * (altitude - meteo.elevation)
        adiabat_points.append(f"{sx(temperature):.1f},{sy(altitude):.1f}")
        altitude += 100
    adiabat = " ".join(adiabat_points)

    band = (
        f'<rect class="flight-band" x="{left}" y="{sy(flight_top):.1f}" width="{plot_w}" '
        f'height="{max(sy(flight_bottom) - sy(flight_top), 1):.1f}" />'
        f'<text x="{left + 6}" y="{sy(flight_bottom) - 6:.1f}" '
        f'class="reference-label band-label">flown {flight_bottom:.0f}–{flight_top:.0f} m</text>'
    )

    # Cloudbase, boundary layer top and thermal top routinely land within a couple of
    # hundred metres of each other, so alternate which end each label hangs from.
    candidates = [
        (value, label, css)
        for value, label, css in (
            (meteo.thermal_top, "thermal top", "thermal-top"),
            (meteo.cloudbase, "cloudbase", "cloudbase"),
            (meteo.boundary_layer_top, "bl top", "bl-top"),
        )
        if value is not None and alt_min <= value <= alt_max
    ]
    references = []
    for index, (value, label, css) in enumerate(candidates):
        y = sy(value)
        if index % 2:
            anchor = f'x="{left + 6}" class="reference-label band-label"'
        else:
            anchor = f'x="{width - right - 4}" class="reference-label"'
        references.append(
            f'<line class="reference {css}" x1="{left}" y1="{y:.1f}" x2="{width - right}" '
            f'y2="{y:.1f}" />'
            f'<text {anchor} y="{y - 5:.1f}">{label} {value:.0f} m</text>'
        )

    return f"""<svg viewBox="0 0 {width} {height}" class="chart chart-sounding" role="img"
     aria-label="Model temperature and dew point profile for the day of the flight, with the
     altitude band actually flown">
  <defs>
    <clipPath id="clip{uid}">
      <rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" />
    </clipPath>
  </defs>
  <g class="grid">{"".join(grid)}</g>
  {band}
  <g class="references">{"".join(references)}</g>
  <g clip-path="url(#clip{uid})">
    <polyline class="adiabat" points="{adiabat}" />
    <polyline class="dewpoint" points="{dewpoint}" />
    <polyline class="environment" points="{environment}" />
  </g>
  <g class="axes">{"".join(labels)}
    <text x="{left + plot_w / 2:.1f}" y="{height - 5}" class="axis-title">temperature °C</text>
    <text x="{12}" y="{top + plot_h / 2:.1f}" class="axis-title"
          transform="rotate(-90 12 {top + plot_h / 2:.1f})">altitude m</text>
  </g>
</svg>"""


def climb_histogram(analysis: Analysis, *, width: int = 460, height: int = 260) -> str:
    """Time spent at each climb rate while circling."""
    data = analysis.climb_histogram
    if not data:
        return ""
    edges = data["edges"]
    counts = data["counts"]
    interval = data["seconds_per_count"][0] if data.get("seconds_per_count") else 1.0
    seconds = [c * interval for c in counts]
    if not any(seconds):
        return ""

    left, right, top, bottom = 46, 16, 18, 40
    plot_w = width - left - right
    plot_h = height - top - bottom
    peak = max(seconds)
    gap = 2
    bar_w = plot_w / len(seconds) - gap

    bars, labels = [], []
    for index, value in enumerate(seconds):
        x = left + index * (bar_w + gap)
        h = plot_h * value / peak
        centre = (edges[index] + edges[index + 1]) / 2
        bars.append(
            f'<rect x="{x:.1f}" y="{top + plot_h - h:.1f}" width="{bar_w:.1f}" '
            f'height="{h:.1f}" rx="2" fill="{climb_color(centre)}">'
            f"<title>{edges[index]:+.1f} to {edges[index + 1]:+.1f} m/s — "
            f"{value / 60:.1f} min</title></rect>"
        )
        if abs(centre % 2) < 0.3:
            tick = f"{edges[index]:+.0f}" if edges[index] else "0"
            labels.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{top + plot_h + 17}" '
                f'class="axis-label axis-x">{tick}</text>'
            )

    best = int(np.argmax(seconds))
    best_x = left + best * (bar_w + gap) + bar_w / 2
    best_h = plot_h * seconds[best] / peak
    annotation = (
        f'<text x="{best_x:.1f}" y="{top + plot_h - best_h - 8:.1f}" class="point-label">'
        f'{seconds[best] / 60:.0f} min</text>'
    )

    return f"""<svg viewBox="0 0 {width} {height}" class="chart chart-hist" role="img"
     aria-label="Minutes spent at each climb rate while thermalling">
  <line class="axis" x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}" />
  {"".join(bars)}{annotation}
  <g class="axes">{"".join(labels)}
    <text x="{left + plot_w / 2:.1f}" y="{height - 6}" class="axis-title">climb rate m/s
      (20 s average)</text>
  </g>
</svg>"""


# Bins for the per-climb sparkline: the same half-metre buckets as the big histogram,
# trimmed to the range a thermal actually spends time in.
SPARK_EDGES = [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]


def climb_spark(series, start: int, stop: int, *, width: int = 66, height: int = 18) -> str:
    """A thumbnail of one climb's own climb-rate distribution.

    The table already gives average and best; this shows the shape between them — a
    single tall bar is a steady climb, a wide spread is one that kept falling out of
    the core and being re-centred.
    """
    values = series.climb[start:stop]
    if not len(values):
        return ""
    counts, _ = np.histogram(values, bins=SPARK_EDGES)
    peak = counts.max()
    if not peak:
        return ""
    gap = 1
    bar_w = (width - gap * (len(counts) - 1)) / len(counts)
    bars = []
    for index, count in enumerate(counts):
        if not count:
            continue
        h = max(height * count / peak, 1.0)
        centre = (SPARK_EDGES[index] + SPARK_EDGES[index + 1]) / 2
        bars.append(
            f'<rect x="{index * (bar_w + gap):.1f}" y="{height - h:.1f}" '
            f'width="{bar_w:.1f}" height="{h:.1f}" fill="{climb_color(centre)}" />'
        )
    zero = SPARK_EDGES.index(0.0) * (bar_w + gap) - gap / 2
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="distribution of climb rate within this climb">'
        f'<line class="spark-zero" x1="{zero:.1f}" y1="0" x2="{zero:.1f}" y2="{height}" />'
        f'{"".join(bars)}</svg>'
    )


# Sequential ramp for glide ratio: one hue, light to dark, as magnitude demands.
LD_STEPS = [
    (5.0, "var(--ld-1)"),
    (7.0, "var(--ld-2)"),
    (9.0, "var(--ld-3)"),
    (12.0, "var(--ld-4)"),
    (float("inf"), "var(--ld-5)"),
]


def ld_color(value: float | None) -> str:
    if value is None:
        return "var(--neutral)"
    for threshold, color in LD_STEPS:
        if value < threshold:
            return color
    return LD_STEPS[-1][1]


def ld_bar(value: float | None, *, best: float, width: int = 54, height: int = 8) -> str:
    """A bar whose length is the glide ratio and whose shade is the same quantity.

    Double-encoding on purpose: the length gives the comparison at a glance and the
    shade survives being skimmed in a long column.
    """
    if value is None:
        return ""
    fraction = max(min(value / max(best, 1e-9), 1.0), 0.02)
    return (
        f'<svg class="ldbar" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="glide ratio {value:.1f} to 1">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="1" fill="var(--rule)" />'
        f'<rect x="0" y="0" width="{width * fraction:.1f}" height="{height}" rx="1" '
        f'fill="{ld_color(value)}" /></svg>'
    )


TREND_CEILING = 4.0  # m/s; the fixed vertical scale that makes rows comparable
TREND_BARS = 22


def climb_trend(series, start: int, stop: int, *, width: int = 76, height: int = 18) -> str:
    """How the climb rate changed through the climb, from entry to exit.

    The spread sparkline says *what* rates you got; this says *when*. A climb that
    starts weak and firms up looks different from one that is strong on entry and dies
    — same average, same spread, different lesson.
    """
    values = series.climb[start:stop]
    times = series.t[start:stop]
    if len(values) < 3:
        return ""
    # A fixed vertical scale, not per-row: auto-scaling each row would make a weak climb
    # look identical to a strong one, and the point of a column of sparklines is that the
    # rows can be compared.
    def sy(value):
        clipped = max(min(float(value), TREND_CEILING), -TREND_CEILING)
        # Zero sits mid-height so time spent sinking reads immediately.
        return height / 2 - clipped / TREND_CEILING * (height / 2 - 1)

    # Averaged into a couple of dozen buckets: a bar per fix at this size is texture,
    # not shape.
    buckets = min(TREND_BARS, len(values))
    edges = np.linspace(0, len(values), buckets + 1).astype(int)
    gap = 0.8
    bar_w = (width - gap * (buckets - 1)) / buckets
    bars = []
    for position in range(buckets):
        chunk = values[edges[position]:max(edges[position + 1], edges[position] + 1)]
        value = float(np.mean(chunk))
        y = sy(value)
        top = min(y, height / 2)
        bars.append(
            f'<rect x="{position * (bar_w + gap):.2f}" y="{top:.2f}" width="{bar_w:.2f}" '
            f'height="{max(abs(height / 2 - y), 0.7):.2f}" fill="{climb_color(value)}" />'
        )
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="climb rate through the climb, entry on the left">'
        f'{"".join(bars)}'
        f'<line class="spark-zero" x1="0" y1="{height / 2:.1f}" x2="{width}" '
        f'y2="{height / 2:.1f}" /></svg>'
    )

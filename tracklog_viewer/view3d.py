"""An interactive 3D view that survives a content-security policy.

`render_map.py` gives the better 3D map — real basemap, real tiles, deck.gl — but it
needs the network at view time, so it cannot be embedded in a published page. This
renders the same idea with nothing but a canvas and about a hundred lines of
JavaScript: the DEM is fetched once at build time and travels inside the document.

The heightfield is drawn back-to-front by walking the grid from the farthest corner,
which is exact for a regular grid seen from outside it — no depth sort, no z-buffer.
"""

import datetime as dt
import json

import numpy as np

from . import sun
from .analysis import Analysis, Phase
from .charts import decimate
from .render_map import RAMP_RGB, climb_rgb

# Metres of horizontal detail the 3D track may drop; 0 keeps every fix. It was 4 m (12 m
# per flight in a shared document), and Douglas-Peucker at that tolerance left five or six
# vertices per thermal circle — every climb drawn as a jagged polygon. Fidelity first.
TRACK_TOLERANCE = 0.0


def _colour_index(value: float) -> int:
    """Index into the shared climb ramp.

    An index costs three characters in the payload where an [r,g,b] triple costs
    fifteen, and a long flight has thousands of points.
    """
    for index, (threshold, _) in enumerate(RAMP_RGB):
        if value < threshold:
            return index
    return len(RAMP_RGB) - 1


TILE_SOURCES = {
    "satellite": {
        "label": "Satellite",
        "layers": [
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery"
            "/MapServer/tile/{z}/{y}/{x}",
            "https://server.arcgisonline.com/ArcGIS/rest/services/Reference"
            "/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        ],
        "attribution": "Imagery © Esri, Maxar, Earthstar Geographics",
        "max_zoom": 18,
        # Esri's levels 12 and up are one mosaic; 11 and below are an older, darker one
        # (over the same Dolomites ground: blue channel 26 against 59). A map that crosses
        # between them jumps colour on every zoom, so the merged view never shows the
        # imagery below this level — it builds those tiles from this level's (`map3d`).
        "consistent_from": 12,
    },
    "map": {
        "label": "Map",
        "layers": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        "attribution": "© OpenStreetMap contributors",
        "max_zoom": 19,
    },
}


def data(analysis: Analysis, terrain, *, tolerance: float | None = None,
         basemaps: dict | None = None, tiles: bool = True,
         airspace: dict | None = None) -> dict:
    """Terrain grid, track and climbs, in the compact form the renderer wants.

    `airspace` is a layer built by `airspaces.scene.layer` — rings and their colours,
    already cut to this terrain's box. It arrives prepared rather than as airspace
    objects because nothing in this module knows what an ATZ is, which is the property
    that lets the airspace tool reuse this view at all.
    """
    flight = analysis.flight
    series = analysis.series
    altitude = flight.alt_gps if np.any(flight.alt_gps) else series.alt

    tolerance = TRACK_TOLERANCE if tolerance is None else tolerance
    keep = np.arange(len(flight.lon)) if tolerance <= 0 else np.union1d(
        decimate(series.x, series.y, tolerance),
        decimate(series.t, series.alt, tolerance * 0.75),
    )
    track = {
        # 5 decimals is ~1 m. 4 was ~11 m, a grid coarse enough to put a staircase into a
        # 40 m thermal circle once the reader zooms in.
        "lon": [round(float(flight.lon[i]), 5) for i in keep],
        "lat": [round(float(flight.lat[i]), 5) for i in keep],
        "alt": [int(altitude[i]) for i in keep],
        "c": [_colour_index(float(series.climb[i])) for i in keep],
        # Seconds since the first fix, for the replay in `render_map`'s renderer.
        "t": [int(series.t[i]) for i in keep],
    }

    climbs = []
    number = 0
    for segment in analysis.segments:
        if segment.phase not in (Phase.THERMAL, Phase.TOW):
            continue
        middle = (segment.start + segment.stop) // 2
        if segment.phase is Phase.TOW:
            label = "T"
        else:
            number += 1
            label = str(number)
        climbs.append(
            {
                "label": label,
                "lon": round(float(flight.lon[middle]), 5),
                "lat": round(float(flight.lat[middle]), 5),
                "alt": int(altitude[middle]),
                "tow": segment.phase is Phase.TOW,
            }
        )

    # Every climb and glide as a start point, an end point and what it was worth, for the
    # optional labels on the view. The numbers are the table's own — a climb rate and a
    # height gain, a glide ratio and a distance — so the map cannot disagree with the
    # rows below it. About 40 bytes a phase, which is why it ships unconditionally and
    # the *drawing* is what the toggle controls.
    phases = []
    for segment in analysis.segments:
        if segment.phase is Phase.THERMAL:
            kind, value = "climb", (
                f"{segment.average_climb:+.1f} m/s · {segment.altitude_change:+.0f} m"
            )
        elif segment.phase is Phase.GLIDE:
            kind, value = "glide", (
                f"{segment.average_ld:.1f}:1 · {segment.distance / 1000:.1f} km"
                if segment.average_ld
                else f"{segment.distance / 1000:.1f} km"
            )
        else:
            continue
        last = segment.stop - 1
        phases.append({
            "kind": kind,
            "text": value,
            "lon": [round(float(flight.lon[segment.start]), 5),
                    round(float(flight.lon[last]), 5)],
            "lat": [round(float(flight.lat[segment.start]), 5),
                    round(float(flight.lat[last]), 5)],
            "alt": [int(altitude[segment.start]), int(altitude[last])],
        })

    # Cursor positions for the shared hover, at the same sample indices the charts use.
    return {
        # Fetched by the page, not embedded: the report's flights are a showcase and the
        # grid was ~600 KB of each. The analysis still used the fetched heights in Python.
        "terrain": terrain.to_remote(),
        "trackTop": int(max(track["alt"])) if track["alt"] else 0,
        "track": track,
        "climbs": climbs,
        "phases": phases,
        "palette": [list(colour) for _, colour in RAMP_RGB],
        # Imagery baked into the document, keyed by the style the button names. A
        # published artifact cannot fetch anything, so a style that is not in here has no
        # way to appear there — which is why both are embedded by default and the tile
        # templates below are only an upgrade for a page that does have a network.
        "basemaps": {name: image.to_dict() for name, image in (basemaps or {}).items()},
        "tiles": (tiles and {
            name: source for name, source in TILE_SOURCES.items()
            if name not in (basemaps or {})
        }) or None,
        "landing": {
            "lon": round(float(flight.lon[-1]), 5),
            "lat": round(float(flight.lat[-1]), 5),
            "alt": int(altitude[-1]),
        },
        "sun": _sun(analysis),
        # The flight's wind, for the arrow on the view. `direction` is where it blows
        # *from*, the way every pilot and every forecast states it; the arrow has to
        # point the other way, and that inversion is done once, in the drawing code.
        "wind": ({
            "ms": round(analysis.wind.speed, 1),
            "from": round(analysis.wind.direction, 1),
            "cardinal": analysis.wind.cardinal,
        } if analysis.wind else None),
        # The airspace over this flight's own ground, and the switch that says the reader
        # owns it. On a map whose subject *is* the airspace there is no switch and the
        # layer is simply on; here the flight is the subject, so it starts off and the bar
        # carries a button — the same call the phase labels make, for the same reason.
        **(airspace or {}),
        **({"airspaceToggle": True} if airspace else {}),
    }


def _sun(analysis: Analysis) -> dict:
    """The day's sun over the middle of the flight, tabulated for the slider.

    A table rather than the algorithm: porting `sun.py` into JavaScript would be a second
    place for it to be wrong, and 144 pairs of numbers cannot drift. The browser
    interpolates between samples, which is why `day_track` unwraps the azimuth.

    Times are handled as UTC minutes throughout and turned into clock time only for the
    label, using the offset the flight's own timezone had *that day* — one flight, one
    place, one date, so a single offset is exact and a timezone database is not needed in
    the page.
    """
    flight = analysis.flight
    lat = float(np.median(flight.lat))
    lon = float(np.median(flight.lon))
    launch = flight.local_time(0)
    day = launch.astimezone(dt.timezone.utc).date() if launch.tzinfo else launch.date()

    def utc_minutes(index: int) -> int:
        when = flight.time[index].astype("datetime64[s]").astype(object)
        return when.hour * 60 + when.minute

    offset = launch.utcoffset() or dt.timedelta(0)
    rise, set_ = sun.rise_and_set(day, lat, lon)
    start, finish = utc_minutes(0), utc_minutes(len(flight.time) - 1)
    return {
        "track": sun.day_track(day, lat, lon),
        "date": day.isoformat(),
        # Minutes to add to a UTC minute to read it as the pilot's own clock.
        "offset": int(offset.total_seconds() // 60),
        "launch": start,
        "landing": finish,
        # Mid-flight is what the view opens on: the light the day was actually worked in,
        # rather than an hour nobody flew.
        "at": (start + finish) // 2 if finish >= start else start,
        "rise": round(rise) if rise is not None else None,
        "set": round(set_) if set_ is not None else None,
    }


def cursor_track(analysis: Analysis, sample) -> dict:
    """Positions for the hover cursor, aligned with the chart sample indices.

    `min` is the UTC minute of each sample, which is what lets the hover move the sun:
    the reader points at a moment in the flight and the terrain is lit as it was then.
    """
    flight = analysis.flight
    altitude = flight.alt_gps if np.any(flight.alt_gps) else analysis.series.alt

    def minute(index: int) -> int:
        when = flight.time[index].astype("datetime64[s]").astype(object)
        return when.hour * 60 + when.minute

    return {
        "lon": [round(float(flight.lon[i]), 5) for i in sample],
        "lat": [round(float(flight.lat[i]), 5) for i in sample],
        "alt": [int(altitude[i]) for i in sample],
        "min": [minute(i) for i in sample],
    }


GLOBE_ICON = (
    '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true" focusable="false">'
    '<circle cx="8" cy="8" r="6.6" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    '<ellipse cx="8" cy="8" rx="2.9" ry="6.6" fill="none" stroke="currentColor" '
    'stroke-width="1.1"/>'
    '<path d="M1.6 6.1h12.8M1.6 9.9h12.8" stroke="currentColor" stroke-width="1.1" '
    'fill="none"/></svg>'
)
EXPAND_ICON = (
    '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" focusable="false">'
    '<path d="M1.5 5.5v-4h4M14.5 10.5v4h-4M14.5 5.5v-4h-4M1.5 10.5v4h4" fill="none" '
    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
)


def panel(payload: dict, uid: str, *, kmz_uri: str | None = None,
          kmz_name: str = "flight.kmz",
          verticals: tuple = (1, 2, 4), vertical: float | None = None) -> str:
    """The canvas, its controls, and the embedded data.

    `verticals` is the exaggeration the segmented control offers and `vertical` is where
    the view starts, which are two questions: the buttons read best in increasing order
    whichever one is pressed. It is the page's choice because the right answer depends on what the
    scene *is*. A flight is a few kilometres of air over tens of kilometres of ground and
    reads honestly at true scale — that is the setting you can measure height above ground
    from, and the default. A map of a whole country is not: at national scale a 300 m
    traffic circuit projects to **0.3 px**, and 2.8 px even zoomed a long way in, so every
    box on it is two coincident rings and the 3D view shows nothing the flat map did not.
    See `airspaces/cli.py`, which asks for more.
    """
    earth = ""
    if kmz_uri:
        # A download link rather than a button: the KMZ travels inside the report, so
        # the file is available with no server and no second request.
        earth = (
            f'<a class="view3d-earth" href="{kmz_uri}" download="{kmz_name}" '
            f'title="Download the KMZ and open it in Google Earth">'
            f'{GLOBE_ICON}<span>Open in Earth</span></a>'
        )
    # A segmented control rather than a cycle. The code's old comment defended naming what
    # is on screen rather than what comes next, and for a *two*-state toggle that is right
    # — but basemap is three states and exaggeration is three. With a cycle you cannot see
    # the options, cannot tell how many presses reach the one you want, and cannot jump;
    # `x1 height` at rest is a button announcing that nothing is happening. The segments
    # double as a legend for what is available, and they agree with the keyboard, which
    # can address a state directly and so could never match a cycle.
    available = {**(payload.get("tiles") or {}), **(payload.get("basemaps") or {})}
    initial_style = "satellite" if "satellite" in available else next(iter(available), "")
    credit = (available.get(initial_style) or {}).get("attribution", "")

    # One segment per style the document can actually show, then bare relief. A document
    # carrying a single style degrades to a two-segment control by itself.
    styles = [key for key in ("satellite", "map") if key in available]
    styles += [key for key in available if key not in styles]
    segments = "".join(
        f'<button type="button" data-view3d-act="basemap-set" data-style="{key}" '
        f'aria-pressed="{"true" if key == initial_style else "false"}"'
        f'{" class=is-on" if key == initial_style else ""}>'
        f'{TILE_SOURCES.get(key, {}).get("label", key)}</button>'
        for key in styles
    )
    segments += (
        '<button type="button" data-view3d-act="basemap-set" data-style="off" '
        'aria-pressed="false">relief</button>'
    )
    start = verticals[0] if vertical is None else vertical
    exaggeration = "".join(
        f'<button type="button" data-view3d-act="exaggerate-set" data-vertical="{level}" '
        f'aria-pressed="{"true" if level == start else "false"}"'
        f'{" class=is-on" if level == start else ""} '
        f'aria-label="Vertical exaggeration &#215;{level}">&#215;{level}</button>'
        for level in verticals
    )
    # The phase switches only exist where there are phases. A scene with no flight in it
    # — the airspace map is one — would otherwise carry two buttons that label nothing,
    # on a bar that is already tight on a phone.
    labels = (
        '<div class="view3d-seg view3d-labels" role="group" aria-label="Phase labels">'
        '<button type="button" data-view3d-act="labels-toggle" data-kind="climb"'
        ' aria-pressed="false" aria-label="Label each climb with its rate and gain"'
        '>climbs</button>'
        '<button type="button" data-view3d-act="labels-toggle" data-kind="glide"'
        ' aria-pressed="false"'
        ' aria-label="Label each glide with its ratio and distance">glides</button>'
        "</div>"
    ) if payload.get("phases") else ""
    # Only where the payload says the reader owns the layer. The airspace map's own panel
    # carries the same rings and no button: there the airspace is the subject, the page
    # has class and floor and time filters of its own, and a second way to hide the whole
    # thing would leave its "743 shown" count describing something nobody can see.
    airspace = (
        '<div class="view3d-seg view3d-airspace" role="group" aria-label="Airspace">'
        '<button type="button" data-view3d-act="airspace-toggle" aria-pressed="false"'
        ' aria-label="Draw the airspace over this flight">airspace</button>'
        "</div>"
    ) if payload.get("airspaceToggle") else ""
    # The label the layer needs to be worth anything: a translucent shape with no name
    # says something is there and not what. Placed by the widget, which is the only thing
    # that knows what is under a point.
    airspace_name = (
        '<div class="view3d-asp" hidden></div>' if payload.get("airspaceToggle") else ""
    )
    return f"""
    <div class="panel view3d-panel">
      <!-- `tabindex` is what makes the view itself reachable. Without it the only
           keyboard route into the panel was the button row, and tab order walked all ten
           before reaching the next section. The page's existing `:focus-visible` rule
           gives it a ring for free. -->
      <canvas class="view3d" id="view3d-{uid}" tabindex="0"
              aria-label="Interactive three-dimensional view of the flight over terrain.
                          Arrow keys pan and shift with them turns and tilts; press
                          question mark for the key list.">
      </canvas>
      {earth}
      {airspace_name}
      <p class="view3d-credit">{credit}</p>
      <p class="view3d-hint" hidden>arrows pan &middot; shift + arrows turn and tilt &middot;
        <kbd>?</kbd> for keys</p>
      <div class="view3d-loading" hidden>
        <span class="view3d-spin"></span><span class="view3d-loading-text"></span>
      </div>
      <!-- Click anywhere on it to close. The panel covers the control bar, `?` included,
           so the button that opened it is not available to close it — and a reader who
           opened the list by clicking has no reason to know Escape works. -->
      <div class="view3d-keys" hidden data-view3d-act="help">
        <p class="view3d-keys-head">Mouse and touch</p>
        <dl>
          <dt>drag</dt><dd>pan</dd>
          <dt>right-drag / ctrl-drag</dt><dd>rotate and tilt</dd>
          <dt>scroll / pinch</dt><dd>zoom</dd>
          <dt>two-finger twist</dt><dd>rotate</dd>
        </dl>
        <p class="view3d-keys-head">Keys, once the view has focus</p>
        <dl>
          <dt>arrows</dt><dd>pan</dd>
          <dt>shift + &larr; &rarr;</dt><dd>rotate</dd>
          <dt>shift + &uarr; &darr;</dt><dd>tilt</dd>
          <dt>+ &minus;</dt><dd>zoom</dd>
          <dt>1 2 4</dt><dd>exaggeration</dd>
          <dt>s m r</dt><dd>satellite, map, relief</dd>
          {'<dt>a</dt><dd>airspace</dd>' if payload.get("airspaceToggle") else ''}
          <dt>f</dt><dd>full screen</dd>
          <dt>0</dt><dd>reset view</dd>
        </dl>
        <p class="view3d-keys-foot">Hovering the charts moves the marker here too.
          Click this list to close it.</p>
      </div>
      <div class="view3d-controls">
        <div class="view3d-seg" role="group" aria-label="What the ground is">{segments}</div>
        <div class="view3d-seg view3d-vert" role="group"
             aria-label="Vertical exaggeration">{exaggeration}</div>
        <!-- Two independent switches, not a segmented control: the reader can want both,
             either, or — the default — neither. Both on at once over a long flight is
             more label than terrain, which is why neither starts on. -->
        {labels}
        {airspace}
        <!-- The zoom pair survives on a desktop because pinch is the one gesture that is
             genuinely awkward on a trackpad. Rotate and tilt do not: they are a drag, a
             ctrl-drag and a right-drag, the caption above teaches exactly that, and they
             were the slots pushing the bar onto a second row. On a phone even zoom goes —
             pinch, drag and twist are all native there. -->
        <div class="view3d-seg view3d-zoom" role="group" aria-label="Zoom">
          <button type="button" data-view3d-act="zoom-out"
                  title="Zoom out" aria-label="Zoom out">&minus;</button>
          <button type="button" data-view3d-act="zoom-in"
                  title="Zoom in" aria-label="Zoom in">+</button>
        </div>
        <button type="button" data-view3d-act="help"
                title="Controls" aria-label="How to control this view">?</button>
        <button type="button" data-view3d-act="fullscreen"
                title="Full screen" aria-label="Full screen">
          {EXPAND_ICON}</button>
        <button type="button" class="view3d-reset" data-view3d-act="reset"
                title="Reset view" aria-label="Reset view">&#8634;</button>
      </div>
      <script type="application/json" class="view3d-data">{json.dumps(payload)}</script>
    </div>"""


STYLE = """
/* Full-bleed: the map is the one thing worth more than the page's reading width. The
   clip has to go on the *root* — html is the scroll container, so clipping body alone
   leaves the page scrolling sideways by the scrollbar's width, which 100vw includes.
   `clip` rather than `hidden` so no new scroll container is created. Verified by trying
   to scroll: scrollWidth still reports the ink extent, which is why the naive check
   looked like a bug that was not there. */
:root, body { overflow-x: clip; }
/* --scrollbar is measured in JS. 100vw includes the scrollbar, so a panel that wide
   hangs off the layout viewport and anything anchored to its right edge — the controls,
   the credit — is clipped. */
.view3d-panel { position: relative; padding: 0; overflow: hidden;
  --page: calc(100vw - var(--scrollbar, 0px));
  width: var(--page); margin-left: calc(50% - var(--page) / 2);
  border-left: 0; border-right: 0; border-radius: 0; }
/* aspect-ratio rather than a height attribute, so the canvas can be re-sized to its box
   — a canvas with fixed width/height attributes and height:auto cannot. */
canvas.view3d { display: block; width: 100%; aspect-ratio: 21 / 9; cursor: grab;
  background: linear-gradient(180deg, var(--panel-2) 0%, var(--panel) 62%); touch-action: none; }
@media (max-width: 900px) { canvas.view3d { aspect-ratio: 4 / 3; } }
/* Real full screen, which is the path taken wherever the permission allows it. The UA
   stylesheet already positions the element over the screen; all that is needed is to
   undo the full-bleed sizing, which would otherwise keep the panel `--page` wide and
   pulled left by half the difference. 100%/100% and not 100vw/100vh: the viewport units
   are the *page's* viewport, and this element's containing block is the screen. */
.view3d-panel:fullscreen { width: 100%; height: 100%; margin: 0; border: 0; }
.view3d-panel:fullscreen canvas.view3d { width: 100%; height: 100%; aspect-ratio: auto; }
/* The backdrop is black by default and shows for a frame at either edge of the
   transition, which reads as a flash against a light report. */
.view3d-panel::backdrop { background: var(--panel); }
/* The fallback for an iframe that is not allowed real fullscreen. inset:0 with auto
   width and height fills the layout viewport exactly — 100vw/100vh would overshoot by
   the scrollbar and leave the canvas the wrong height. */
.view3d-panel.is-maximised { position: fixed; inset: 0; z-index: 60; width: auto;
  height: auto; margin: 0; }
.view3d-panel.is-maximised canvas.view3d { width: 100%; height: 100%; aspect-ratio: auto; }
.view3d-earth {
  position: absolute;
  top: 12px;
  left: 12px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  text-decoration: none;
  padding: 7px 12px;
  border-radius: 2px;
  border: 1px solid var(--rule-strong);
  background: var(--panel);
  color: var(--ink);
}
.view3d-earth:hover { background: var(--climb); border-color: var(--climb); color: var(--paper); }
/* Top right, opposite the Earth link: at the bottom it fought the control row, which
   on a phone wraps into the same space. */
.view3d-credit { position: absolute; right: 12px; top: 12px; margin: 0; font-size: 11px;
  color: var(--ink-2); background: color-mix(in srgb, var(--panel) 78%, transparent);
  padding: 3px 7px; border-radius: 2px; max-width: 46%; text-align: right; }
canvas.view3d.is-dragging { cursor: grabbing; }
/* The airspace label. `pointer-events: none` or it would sit under the cursor, take the
   next pointermove for itself and flicker the label it is showing. Positioned by the
   widget in the panel's own coordinates, which is why the panel is the containing block
   and not the canvas. */
.view3d-asp { position: absolute; pointer-events: none; z-index: 5; max-width: 62%;
  background: var(--ink); color: var(--paper); font-size: 12px; line-height: 1.35;
  padding: 5px 8px; border-radius: 3px; }
/* The sun and the wind are drawn *on the canvas*, not in the DOM: both are geographic
   directions and have to turn with the view, which means living in the same coordinate
   system as the terrain they describe. There is no control here any more — the sun
   follows the chart cursor, so the time comes from wherever the reader is pointing. */
.view3d-controls { position: absolute; right: 10px; bottom: 10px; left: 10px; display: flex;
  gap: 5px; flex-wrap: wrap; justify-content: flex-end; }
/* Three kinds of control, and they no longer share one undifferentiated style: a
   segmented group carries state, a bare button is a one-shot action. Nothing used to
   signal that RESET VIEW throws away the camera you just set up while SATELLITE is a
   mode. Size follows frequency too — reset was the *widest* button at 87 px, in the prime
   thumb position, for the action taken least often. It is an icon now. */
.view3d-seg { display: flex; gap: 0; }
.view3d-seg button { border-radius: 0; }
.view3d-seg button + button { margin-left: -1px; }
.view3d-seg button:first-child { border-top-left-radius: 2px; border-bottom-left-radius: 2px; }
.view3d-seg button:last-child { border-top-right-radius: 2px; border-bottom-right-radius: 2px; }
.view3d-reset { font-size: 15px; line-height: 1; }

/* A fifth of the map was chrome on the device with the least map: at 390 x 844 the panel
   is 390 x 295 and the bar was 370 x 60 — 20.2% of the panel height — with the rose in
   the same canvas below it. Dropping the four rotate/tilt nudges and the zoom pair takes
   the bar to one row. Exaggeration deliberately *stays*: a 295 px map is exactly where
   relief is hardest to read, so x2 earns its place more on a phone than on a desktop.

   This media query used to reduce padding to `5px 7px` and type to 10.5 px, shrinking
   the targets on the one device where a finger replaces a mouse. It now grows them, and
   the type sits on the 12 px mobile floor. */
@media (max-width: 640px) {
  .view3d-controls { gap: 4px; flex-wrap: nowrap; }
  .view3d-controls button { padding: 8px 10px; font-size: 12px; }
  .view3d-zoom { display: none; }
  .view3d-reset { display: none; }
  /* Goes with the zoom pair, and for the same reason: on a 295 px map there is no room
     for a label per phase, so the switch that would draw them is not worth the bar. */
  .view3d-labels { display: none; }
}

/* The rose moves to the top right and the attribution to the top left.
   `render_map.py:274` already puts navigation top-right by MapLibre's own default, and
   two viewers of the same flights should not disagree about where north lives. But the
   corner was occupied, and the Esri/Maxar attribution is required rather than optional —
   so the move is a reallocation, not an addition. Top-left for the credit rather than
   bottom-left: on a 360 px phone the control bar is 327 px of the 340 available, so
   anything else along the bottom edge collides with it, and top-left needs no media
   query to get out of the way. */
.view3d-credit { right: auto; left: 12px; text-align: left; }

.view3d-hint {
  position: absolute;
  left: 12px;
  bottom: 12px;
  margin: 0;
  font-size: 11px;
  color: var(--ink-2);
  background: color-mix(in srgb, var(--panel) 82%, transparent);
  padding: 4px 8px;
  border-radius: 2px;
  pointer-events: none;
}
/* Everything over the canvas is a positioned sibling, so paint order was DOM order and
   nothing said which layer was which. The control bar comes last in the markup and so
   drew *over* the key list — on a 390 px phone the SATELLITE/MAP/RELIEF row sat across
   the "s m r" line describing it. The stack is stated here instead: badges at the bottom,
   then the loading spinner, then the controls, and the help list over all of it, because
   it is the one overlay a reader opens deliberately and expects to obscure the view. */
.view3d-earth, .view3d-credit, .view3d-hint { z-index: 1; }
.view3d-loading { z-index: 2; }
.view3d-controls { z-index: 3; }
.view3d-keys { z-index: 4; }

.view3d-keys {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  /* Opaque, not 94%: it now covers the satellite imagery, and a light aerial behind
     12 px type is the one background this list cannot be read against. */
  background: var(--panel);
  border: 1px solid var(--rule-strong);
  padding: 14px 18px;
  border-radius: 3px;
  font-size: 12px;
  /* The panel clips its overflow, so a list taller than the canvas loses its first rows
     off the top — on a phone the whole "Mouse and touch" section vanished, silently.
     Cap it to the box and let it scroll instead. */
  max-height: calc(100% - 20px);
  max-width: calc(100% - 20px);
  overflow: auto;
  box-sizing: border-box;
  cursor: pointer;
}
.view3d-keys dl {
  margin: 0;
  display: grid;
  grid-template-columns: auto auto;
  gap: 4px 16px;
}
.view3d-keys-head { margin: 0 0 5px; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--ink-3); }
.view3d-keys dl + .view3d-keys-head { margin-top: 11px; }
.view3d-keys-foot { margin: 11px 0 0; font-size: 11px; color: var(--ink-3); }
/* `shift + <- ->` is one key combination and wrapped into two lines the moment the grid
   was squeezed, which read as two separate bindings with the second one blank. */
.view3d-keys dt { color: var(--ink); font-family: ui-monospace, monospace;
  white-space: nowrap; }
.view3d-keys dd { margin: 0; color: var(--ink-2); }
.view3d-hint[hidden], .view3d-keys[hidden] { display: none; }
.view3d-loading[hidden] { display: none; }

/* Centred over the terrain rather than in a corner: it is telling the reader that the
   thing they are looking at is about to change, and a stitch over a cross-country box
   takes long enough that "did my click register" is a real question. */
.view3d-loading {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 14px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--panel) 88%, transparent);
  border: 1px solid var(--rule-strong);
  font-size: 12px;
  color: var(--ink-2);
  pointer-events: none;
}
.view3d-spin {
  width: 14px;
  height: 14px;
  flex: none;
  border: 2px solid var(--rule-strong);
  border-top-color: var(--climb);
  border-radius: 50%;
  animation: view3d-spin 0.8s linear infinite;
}
@keyframes view3d-spin { to { transform: rotate(360deg); } }
/* The report's global reduced-motion rule kills the animation, which would leave a
   static ring saying nothing. The label beside it is what actually carries the message,
   so the frozen ring is fine — but it must not read as a broken control, so it dims. */
@media (prefers-reduced-motion: reduce) {
  .view3d-spin { opacity: 0.35; }
}
.view3d-hint kbd {
  font-family: ui-monospace, monospace;
  border: 1px solid var(--rule-strong);
  border-radius: 2px;
  padding: 0 3px;
}
.view3d-controls button {
  font: inherit;
  font-size: 11.5px;
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 4px 9px;
  border: 1px solid var(--rule-strong);
  border-radius: 2px;
  background: var(--panel);
  color: var(--ink-2);
  cursor: pointer;
}
.view3d-controls button:hover { color: var(--ink); background: var(--panel-2); }
.view3d-controls button.is-on { background: var(--climb); border-color: var(--climb);
  color: var(--paper); }
.view3d-controls button svg { display: block; }
"""


SCRIPT = """
// The scrollbar's width, so a full-bleed panel can be exactly the layout viewport.
//
// This has to be innerWidth - clientWidth: an offscreen probe element reports 0 in a
// browser that gives overlay scrollbars to elements and a classic one to the document,
// which is exactly what headless Chrome does, and the panel then overhangs by the
// scrollbar's width and clips its own controls.
//
// The catch is *when* it is measured. On a phone, showing or hiding the address bar fires
// a resize during which the two numbers are briefly inconsistent, and re-measuring then
// gave the panel a phantom 10-20 px of scrollbar mid-scroll — the 3D view visibly
// shrinking as you dragged. So: only on a width change, clamped to a plausible scrollbar,
// and callable by anything that grows the page enough to introduce one.
function measureScrollbar() {
  var width = window.innerWidth - document.documentElement.clientWidth;
  document.documentElement.style.setProperty(
    '--scrollbar', Math.max(Math.min(width, 30), 0) + 'px');
}
measureScrollbar();
window.__measureScrollbar = measureScrollbar;
var scrollbarWidth = window.innerWidth;
window.addEventListener('resize', function () {
  // A height-only resize is the address bar, and must not move anything sideways.
  if (window.innerWidth === scrollbarWidth) return;
  scrollbarWidth = window.innerWidth;
  measureScrollbar();
});


// ---- terrain fetched by the page ---------------------------------------------------
//
// A scene may carry its terrain as `terrain.remote` — the box, the grid and the tile
// source, no heights — rather than as the heights themselves (`terrain.remote()` in
// Python). The page then fetches the same terrarium tiles at the same zoom and samples
// them onto the same nodes `terrain.fetch` would have: nearest pixel, a missing tile
// filled with the lowest height found, heights rounded to the metre. It is one grid built
// in two places, and everything downstream of `dem` cannot tell which — so the arithmetic
// is Python's, operation for operation: `math.radians` is lat × (π/180), numpy's
// linspace is start + i × step, `np.round` rounds a half to even, and the bounds are the
// unrounded heights'. A test builds both from the same tiles and compares every node.
function loadTerrain(dem) {
  var zoom = dem.remote.zoom, n = Math.pow(2, zoom), size = 256;
  function tileX(lon) { return (lon + 180) / 360 * n; }
  function tileY(lat) {
    var rad = lat * (Math.PI / 180);
    return (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2 * n;
  }
  var x0 = Math.floor(tileX(dem.west)), x1 = Math.floor(tileX(dem.east));
  var y0 = Math.floor(tileY(dem.north)), y1 = Math.floor(tileY(dem.south));
  var width = (x1 - x0 + 1) * size, height = (y1 - y0 + 1) * size;
  var mosaic = new Float64Array(width * height).fill(NaN);
  var scratch = document.createElement('canvas');
  scratch.width = scratch.height = size;
  var sctx = scratch.getContext('2d', { willReadFrequently: true });

  function tile(x, y) {
    return new Promise(function (resolve) {
      var image = new Image();
      image.crossOrigin = 'anonymous';
      image.onload = function () {
        sctx.clearRect(0, 0, size, size);
        sctx.drawImage(image, 0, 0);
        var px = sctx.getImageData(0, 0, size, size).data;
        var ox = (x - x0) * size, oy = (y - y0) * size;
        for (var r = 0; r < size; r++) {
          for (var c = 0; c < size; c++) {
            var k = (r * size + c) * 4;
            mosaic[(oy + r) * width + ox + c] =
              px[k] * 256 + px[k + 1] + px[k + 2] / 256 - 32768;
          }
        }
        resolve(true);
      };
      // A missing tile is a hole to fill, not a failure: the Python side does the same.
      // But a tile is asked again twice first, a moment apart: every tile of a page has
      // been seen to fail at once and succeed on reload, which with no retry is a 3D view
      // that never appears.
      var tries = 0;
      var src = dem.remote.url.replace('{z}', zoom).replace('{x}', x).replace('{y}', y);
      image.onerror = function () {
        if (++tries > 2) { resolve(false); return; }
        setTimeout(function () { image.src = src + (src.indexOf('?') < 0 ? '?' : '&') + 'r=' + tries; },
                   400 * tries);
      };
      image.src = src;
    });
  }

  var wanted = [];
  for (var ty = y0; ty <= y1; ty++) for (var tx = x0; tx <= x1; tx++) wanted.push(tile(tx, ty));
  return Promise.all(wanted).then(function (got) {
    if (got.indexOf(true) < 0) throw new Error('no elevation tile could be fetched');
    var low = Infinity;
    for (var i = 0; i < mosaic.length; i++) if (mosaic[i] < low) low = mosaic[i];
    function linspace(start, stop, count, i) {
      if (count < 2) return start;
      return i === count - 1 ? stop : i * ((stop - start) / (count - 1)) + start;
    }
    function roundHalfEven(value) {
      var down = Math.floor(value), rest = value - down;
      if (rest !== 0.5) return Math.round(value);
      return down % 2 === 0 ? down : down + 1;
    }
    var z = new Array(dem.rows * dem.cols), min = Infinity, max = -Infinity;
    for (var r = 0; r < dem.rows; r++) {
      // np.linspace(north, south, rows) and (west, east, cols), then truncated to a pixel
      // and clipped — `terrain.fetch`, step for step.
      var lat = linspace(dem.north, dem.south, dem.rows, r);
      var py = Math.min(Math.max(Math.floor((tileY(lat) - y0) * size), 0), height - 1);
      for (var c = 0; c < dem.cols; c++) {
        var lon = linspace(dem.west, dem.east, dem.cols, c);
        var px = Math.min(Math.max(Math.floor((tileX(lon) - x0) * size), 0), width - 1);
        var value = mosaic[py * width + px];
        if (value !== value) value = low;
        if (value < min) min = value;
        if (value > max) max = value;
        z[r * dem.cols + c] = roundHalfEven(value);
      }
    }
    dem.z = z;
    dem.min = Math.floor(min);
    dem.max = Math.ceil(max);
    return dem;
  });
}

// `initView3d` for a scene that may still have to fetch its terrain. Resolves with the
// handle, or with null where `initView3d` would have returned null; rejects only when the
// terrain could not be fetched at all, which the caller has to say something about.
function initView3dWhenReady(root, cursorTrack) {
  var payload = root.querySelector('.view3d-data');
  if (!payload) return Promise.resolve(null);
  var scene = JSON.parse(payload.textContent);
  var dem = scene.terrain;
  if (!dem || !dem.remote || dem.z) return Promise.resolve(initView3d(root, cursorTrack, scene));
  var box = root.querySelector('.view3d-loading');
  if (box) {
    box.querySelector('.view3d-loading-text').textContent = 'Loading terrain…';
    box.hidden = false;
  }
  return loadTerrain(dem).then(function () {
    if (box) box.hidden = true;
    return initView3d(root, cursorTrack, scene);
  }, function (error) {
    if (box) {
      box.querySelector('.view3d-spin').hidden = true;
      box.querySelector('.view3d-loading-text').textContent =
        'The terrain could not be fetched (' + error.message + ').';
    }
    throw error;
  });
}

function initView3d(root, cursorTrack, preset) {
  var canvas = root.querySelector('canvas.view3d');
  var payload = root.querySelector('.view3d-data');
  if (!canvas || !payload) return null;
  // `preset` is the scene `initView3dWhenReady` has already parsed and completed.
  var scene = preset || JSON.parse(payload.textContent);
  // A scene need not carry a flight. The airspace map is the same widget over the same
  // terrain with no track in it, so the flight-shaped members are defaulted here once
  // rather than guarded at each of the dozen places that read them.
  if (!scene.track) scene.track = { lon: [], lat: [], alt: [], c: [] };
  if (!scene.climbs) scene.climbs = [];
  if (!scene.palette) scene.palette = [[120, 120, 120]];
  var dem = scene.terrain;
  var ctx = canvas.getContext('2d');
  // The canvas has no width/height attributes: CSS sizes the box and this matches the
  // backing store to it, so the same code serves an inline panel and full screen.
  var W = 0, H = 0;

  function resize() {
    var rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return false;
    // Cap the pixel ratio: at 3× a phone would ask for a 3000-pixel-wide heightfield
    // redraw on every frame of a drag.
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    var width = Math.round(rect.width * ratio);
    var height = Math.round(rect.height * ratio);
    if (width === W && height === H) return false;
    canvas.width = W = width;
    canvas.height = H = height;
    if (renderer) renderer.resize(W, H);
    // The fitted scale is measured against the canvas, so a new canvas needs a new one.
    refitScale();
    return true;
  }
  resize();

  // Local metric frame about the DEM centre, so rotation is about the middle of
  // the terrain rather than the corner of a bounding box.
  var lat0 = (dem.north + dem.south) / 2;
  var lon0 = (dem.east + dem.west) / 2;
  var mPerDegLat = 110540;
  var mPerDegLon = 111320 * Math.cos(lat0 * Math.PI / 180);
  function toMetres(lon, lat) {
    return [(lon - lon0) * mPerDegLon, (lat - lat0) * mPerDegLat];
  }

  var spanX = (dem.east - dem.west) * mPerDegLon;
  var spanY = (dem.north - dem.south) * mPerDegLat;

  // True scale by default: the whole point of putting the flight over a DEM is that
  // heights can be compared with the ground, and an exaggerated vertical breaks that.
  // The ×2 button is there for when the relief needs help.
  // The exaggeration the page's own control starts on, read from the button that is
  // pressed rather than assumed to be 1: a scene whose control opens on x5 and whose
  // view opens at true scale disagrees with itself, and the reader sees the wrong one.
  var baseVertical = (function () {
    var pressed = root.querySelector('[data-view3d-act="exaggerate-set"].is-on');
    var level = pressed ? parseFloat(pressed.dataset.vertical) : 1;
    return level > 0 ? level : 1;
  })();
  // panX/panY are screen-space offsets applied after the fit, which is what lets the
  // view be dragged off centre — the fit alone always recentres, so without these the
  // camera was welded to the middle of the flight.
  // The opening camera. A flight wants the oblique three-quarter view — that is the
  // angle a pilot recognises — while a scene that is a map of a whole country wants to
  // open nearly flat, because at 0.46 the far half of it is a sliver. So the payload may
  // name its own, and `reset` goes back to whatever it named.
  var HOME = { yaw: -0.42, pitch: 0.46 };
  if (scene.view) {
    if (typeof scene.view.yaw === 'number') HOME.yaw = scene.view.yaw;
    if (typeof scene.view.pitch === 'number') HOME.pitch = scene.view.pitch;
  }
  var view = { yaw: HOME.yaw, pitch: HOME.pitch, zoom: 1, vertical: baseVertical,
               map: true, panX: 0, panY: 0 };

  // The basemap carries the place names, which is the whole reason it is here: a
  // hillshade shows the shape of a ridge but never tells you which village it is above.
  var basemap = null;
  var cellColour = null;      // one averaged map colour per texture cell
  var cellCols = 0, cellRows = 0;

  // Two drape resolutions. Each cell costs a drawImage and an overlay fillRect, so the
  // fine mesh is far too expensive to run on every frame of a drag — but a mesh coarse
  // enough to drag smoothly shows its own quadrilaterals, which is what "visible squares"
  // was. So: coarse while the reader is moving the camera, fine once they stop.
  // Budgets in *cells*, not in columns: the grid's aspect varies wildly between a ridge
  // run and a triangle, and what costs time is the cell count. Measured at ~22 us per
  // cell in software rendering, so 5 200 is about 110 ms for the settled frame and 1 800
  // keeps a drag near 40 fps.
  var FINE_BUDGET = 5200;
  var COARSE_BUDGET = 1800;
  var interacting = false;
  var settle = null;

  function texStep() {
    var scale = Math.sqrt(cols * rows / (interacting ? COARSE_BUDGET : FINE_BUDGET));
    var step = Math.max(Math.round(scale), 1);
    return { c: step, r: step };
  }

  // Called by every gesture handler. The trailing redraw is what actually puts the fine
  // mesh on screen, so it has to fire even if the gesture ended without a final event.
  function moving() {
    interacting = true;
    if (settle) clearTimeout(settle);
    settle = setTimeout(function () {
      settle = null;
      interacting = false;
      draw();
      scheduleDetail();
    }, 180);
  }

  // A per-cell average of the map, taken once by letting the browser downscale the
  // image. It is painted under each textured cell so the small gaps where a non-planar
  // cell disagrees with its affine fit show ground colour rather than sky.
  function sampleCellColours() {
    // Only the 2D drape has cells to fill under. A depth-buffered backend draws the
    // texture once over real geometry, so this would be a getImageData for nothing.
    if (renderer) { cellColour = null; return; }
    try {
      var steps = texStep();
      cellCols = Math.max(Math.round(cols / steps.c), 1);
      cellRows = Math.max(Math.round(rows / steps.r), 1);
      var off = document.createElement('canvas');
      off.width = cellCols;
      off.height = cellRows;
      var octx = off.getContext('2d');
      octx.drawImage(basemap, 0, 0, cellCols, cellRows);
      cellColour = octx.getImageData(0, 0, cellCols, cellRows).data;
    } catch (e) {
      cellColour = null;
    }
  }

  // Which imagery the reader is looking at. Styles baked into the document are used as
  // they are; anything else is stitched from tiles when it is first selected, which only
  // works where the page can reach the network.
  var embedded = scene.basemaps || {};
  var order = ['satellite', 'map'].filter(function (name) {
    return embedded[name] || (scene.tiles && scene.tiles[name]);
  });
  var style = order[0] || null;
  var loading = false;

  function tileNumbers(lon, lat, zoom) {
    var n = Math.pow(2, zoom);
    var x = (lon + 180) / 360 * n;
    var radians = lat * Math.PI / 180;
    var y = (1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2 * n;
    return [x, y];
  }

  // The finest zoom whose tile count over `box` stays inside `budget`.
  function zoomFor(source, box, budget) {
    for (var zoom = Math.min(18, source.max_zoom); zoom > 5; zoom--) {
      if (tileCount(box, zoom) <= budget) return zoom;
    }
    return 6;
  }

  function tileCount(box, zoom) {
    var a = tileNumbers(box.west, box.north, zoom);
    var b = tileNumbers(box.east, box.south, zoom);
    return (Math.floor(b[0]) - Math.floor(a[0]) + 1) *
           (Math.floor(b[1]) - Math.floor(a[1]) + 1);
  }

  function tileZoom(source) {
    // Enough tiles to be sharp, few enough to be polite: aim for a mosaic no wider than
    // Nothing is embedded on this path, so the budget buys sharpness rather than bytes:
    // 120 tiles reaches zoom 12-13 on a cross-country box, roughly 10-20 m per pixel
    // against the 80 m that a 30-tile budget allowed.
    //
    // Capped at 14 on purpose even though the *detail* mosaic below will go further: the
    // base image covers the whole terrain and is what a page carries before anyone
    // touches it, so it buys coverage. Sharpness is the second fetch's job.
    return Math.min(zoomFor(source, dem, 120), 14);
  }

  // ---- detail imagery ----------------------------------------------------------------
  //
  // The base mosaic is stitched once for the whole terrain, so its resolution is fixed by
  // a tile budget spread over the whole box — about 300 m a pixel over a country, which
  // is a backdrop and not something to read. Zooming in used to magnify exactly those
  // pixels: the view got closer and the ground got blurrier, which is the opposite of
  // what zooming is for.
  //
  // So once the camera settles, if what is on screen is a small enough part of the
  // terrain that a finer zoom would fit in a tile budget, a *second* mosaic is stitched
  // over just that box and handed to the renderer as a detail layer. The shader draws it
  // where it covers and the base image everywhere else.
  //
  // Three things keep this from becoming a tile-fetching machine:
  //
  //  - it only ever fires when the camera has been still for `DETAIL_DELAY`;
  //  - it wants at least `DETAIL_STEP` zoom levels of improvement, so nudging the view
  //    does not re-fetch the same ground at the same sharpness;
  //
  // `DETAIL_STEP` was 2, and two levels is a **4x zoom** of no improvement, because
  // halving the visible box buys exactly one tile level within a fixed tile budget.
  // Measured on the fixture: a fetch at tile zoom 15 around view zoom 8, then nothing at
  // all through view 12, 16, 20 and 28 — the reader zooms three and a half times closer
  // and the ground only gets blurrier — and the next fetch at view 40, the ceiling. That
  // is "the tiles stopped updating with zoom", and it was a threshold rather than a
  // fault. One level is still a doubling of resolution, which is worth a fetch; the
  // stillness delay and the padded box are what stop it becoming a fetching machine, and
  // they are untouched.
  //  - the box it asks for is padded, so small pans stay inside what has already been
  //    fetched and ask for nothing.
  var detail = null;          // { image, box, shaded, style, zoom }
  var detailPending = null;   // the box currently being stitched, so it is asked once
  var DETAIL_TILES = 96;      // a fetch is one screenful at retina density; quality first
  var DETAIL_STEP = 1;        // zoom levels of improvement worth a fetch
  var DETAIL_PAD = 0.35;      // of the visible box, on each side
  var DETAIL_DELAY = 420;     // ms of stillness before asking

  // What is on screen, as a lon/lat box, clamped to the terrain.
  //
  // Taken from the four canvas corners inverted onto the ground plane. At a low pitch the
  // top corners land near the horizon — enormous or behind the camera — which is exactly
  // why the result is clamped to the DEM rather than trusted: the answer wanted here is
  // "which part of the terrain is being looked at", and terrain is all there is.
  function visibleBox() {
    if (!fit.scale || Math.abs(Math.sin(view.pitch)) < 1e-3) return null;
    var west = Infinity, east = -Infinity, south = Infinity, north = -Infinity;
    var corners = [[0, 0], [W, 0], [0, H], [W, H]];
    for (var i = 0; i < corners.length; i++) {
      var point = groundAtCanvas(corners[i][0], corners[i][1]);
      if (!point) return null;
      var lon = lon0 + point[0] / mPerDegLon;
      var lat = lat0 + point[1] / mPerDegLat;
      if (!isFinite(lon) || !isFinite(lat)) return null;
      west = Math.min(west, lon); east = Math.max(east, lon);
      south = Math.min(south, lat); north = Math.max(north, lat);
    }
    var box = {
      west: Math.max(west, dem.west), east: Math.min(east, dem.east),
      south: Math.max(south, dem.south), north: Math.min(north, dem.north)
    };
    if (box.east <= box.west || box.north <= box.south) return null;
    return box;
  }

  // The ground under a canvas pixel — the *surface*, not the datum plane at `dem.min`.
  // `groundUnder` is this in client pixels, and every turn, twist and tilt pivots on it.
  //
  // A pixel is a line through the world: at lift L = (z − dem.min) × vertical it lands at
  // one ground position, and the ground there has its own lift. The pick is where the two
  // agree. It was three fixed-point passes (pick at the datum, read the height there,
  // re-pick at that height), which converge only while the slope times vertical times
  // cot(pitch) stays under one — on a steep camera, not on the flight report's opening
  // pitch of 0.46 over alpine relief, where the answer came back 4–7 px from the pixel on
  // a real flight and 88 px on the ridged test fixture. Turning the map then slid the
  // ground out from under the finger, because the point being held was not the point
  // under it.
  //
  // So: walk the line down from the highest the terrain can reach to the first place it
  // meets the surface — the first, because the ground nearest the camera is the ground
  // that is seen, and a ridge can hide the valley behind it — then bisect that step.
  var PICK_STEPS = 48, PICK_BISECT = 24;
  function groundAtCanvas(sx, sy) {
    var sp = Math.sin(view.pitch);
    if (Math.abs(sp) < 1e-4 || !fit.scale) return null;
    var cp = Math.cos(view.pitch);
    var cy = Math.cos(view.yaw), sn = Math.sin(view.yaw);
    var wx = (sx - fit.dx - view.panX) / fit.scale;
    var screenY = (sy - fit.dy - view.panY) / fit.scale;
    var vertical = view.vertical || 1;
    function at(lift) {
      // screen y = -wy*sin(pitch) - lift*cos(pitch), so a known lift moves the northing.
      var wy = -(screenY + lift * cp) / sp;
      return [wx * cy + wy * sn, -wx * sn + wy * cy];
    }
    // Above the surface is positive: the line is still in the air at this lift.
    function gap(lift) {
      var point = at(lift);
      var height = groundAt(lon0 + point[0] / mPerDegLon, lat0 + point[1] / mPerDegLat);
      if (height === null || height === undefined) return null;
      return lift - (height - dem.min) * vertical;
    }
    // From the highest ground there is — the detail terrain's included, which can find a
    // summit the base grid averaged away. Starting under it, the first step is already
    // below the surface and the pick is wherever the walk began.
    var highest = terrainDetail ? Math.max(dem.max, terrainDetail.max) : dem.max;
    var top = Math.max(highest - dem.min, 0) * vertical;
    var above = null, below = null;
    var previousLift = null, previousGap = null;
    for (var step = 0; step <= PICK_STEPS; step++) {
      var lift = top * (1 - step / PICK_STEPS);
      var g = gap(lift);
      if (g === null) { previousLift = null; previousGap = null; continue; }
      if (g <= 0) {
        if (previousGap === null) { above = lift; below = lift; }
        else { above = previousLift; below = lift; }
        break;
      }
      previousLift = lift; previousGap = g;
    }
    var point, liftFound;
    if (above === null) {
      // Off the terrain, or over ground this line never meets: the datum, as before, so a
      // pan past the edge of the map still has a plane to drag.
      liftFound = 0;
    } else {
      for (var k = 0; k < PICK_BISECT && above - below > 1e-6; k++) {
        var mid = (above + below) / 2;
        var gm = gap(mid);
        if (gm !== null && gm > 0) above = mid; else below = mid;
      }
      liftFound = (above + below) / 2;
    }
    point = at(liftFound);
    // The height travels with the point, so whatever holds it can re-project it where
    // it actually is rather than back on the datum.
    point.push(dem.min + liftFound / vertical);
    return point;
  }


  function padded(box) {
    var padX = (box.east - box.west) * DETAIL_PAD;
    var padY = (box.north - box.south) * DETAIL_PAD;
    return {
      west: Math.max(box.west - padX, dem.west),
      east: Math.min(box.east + padX, dem.east),
      south: Math.max(box.south - padY, dem.south),
      north: Math.min(box.north + padY, dem.north)
    };
  }

  function covers(outer, inner) {
    return outer && inner && outer.west <= inner.west && outer.east >= inner.east
      && outer.south <= inner.south && outer.north >= inner.north;
  }

  // Whether a detail fetch is worth making, and for what. Pure, and exposed on the
  // handle, because "would this zoom trigger a fetch" is the part worth testing without
  // a network.
  function detailPlan() {
    var source = scene.tiles && style && scene.tiles[style];
    if (!source || !view.map) return null;
    var seen = visibleBox();
    if (!seen) return null;
    var want = padded(seen);
    var zoom = zoomFor(source, want, DETAIL_TILES);
    var have = detail && detail.style === style ? detail.zoom : (mosaicZoom || 0);
    if (zoom < have + DETAIL_STEP) return null;
    // Already inside what was fetched, at the same sharpness: nothing to do.
    if (detail && detail.style === style && detail.zoom >= zoom
        && covers(detail.box, seen)) return null;
    if (detailPending && covers(detailPending, seen)) return null;
    return { zoom: zoom, box: want, style: style, tiles: tileCount(want, zoom) };
  }

  var detailTimer = null;
  function scheduleDetail() {
    if (detailTimer) clearTimeout(detailTimer);
    detailTimer = setTimeout(function () {
      detailTimer = null;
      var plan = detailPlan();
      if (plan) loadTiles(plan.style, plan);
      var ground = terrainPlan();
      if (ground) loadTerrainDetail(ground);
    }, DETAIL_DELAY);
  }

  // ---- detail terrain ----------------------------------------------------------------
  //
  // The imagery sharpens as the reader zooms in, and until this the ground under it did
  // not: one grid for the whole box, 1.6 km a node over a country and 2.5 km over the
  // planner's Alps, so a zoomed-in hill was a handful of flat facets with a sharp
  // photograph on them. Once the camera settles over a small enough part of the terrain,
  // a finer grid is fetched for just that part — the same terrarium tiles `loadTerrain`
  // reads — and the renderer draws it as a patch, cutting a hole in the base mesh under
  // it. `groundAt` reads the patch where there is one, so a pick, a turnpoint's height and
  // a track's shadow sit on the ground that is drawn.
  //
  // WebGL only. The 2D renderer draws the base grid cell by cell and has no way to put a
  // patch in it, and a `groundAt` that answered from ground the picture does not show
  // would be worse than the coarse answer — so without a backend there is no patch.
  var terrainDetail = null;     // { west, east, south, north, rows, cols, z, min, max, spacing }
  var terrainPending = null;
  var TERRAIN_NODES = 320;      // across the longer side of a patch; ~25 m caps it anyway
  var TERRAIN_TILES = 36;       // DEM tiles a patch may cost
  var TERRAIN_FINEST_M = 25;    // the DEM behind the tiles is about 30 m; no finer than that
  var TERRAIN_MAX_ZOOM = 15;    // the deepest terrarium tiles there are

  function terrainSource() {
    return dem.remote && dem.remote.url ? dem.remote.url : null;
  }

  // Whether a patch is worth fetching, and for what. Pure, like `detailPlan`, and exposed
  // on the handle for the same reason.
  function terrainPlan() {
    var url = terrainSource();
    if (!url || !renderer || !renderer.setTerrainDetail) return null;
    var seen = visibleBox();
    if (!seen) return null;
    var want = padded(seen);
    var midLat = (want.north + want.south) / 2;
    var widthM = (want.east - want.west) * mPerDegLon;
    var heightM = (want.north - want.south) * mPerDegLat;
    var spacing = Math.max(Math.max(widthM, heightM) / TERRAIN_NODES, TERRAIN_FINEST_M);
    // Two and a half times finer at least: a patch that is only a little finer is a fetch
    // and a seam for nothing anyone would see. (Half was the first guess, and a single
    // flight's box sat right on it at rest, asking for its own resolution again.)
    if (spacing > (spanX / (cols - 1)) * 0.4) return null;
    if (terrainDetail && covers(terrainDetail, seen)
        && terrainDetail.spacing <= spacing * 1.5) return null;
    if (terrainPending && covers(terrainPending, seen)) return null;
    // The coarsest tile zoom whose pixel is no bigger than a node, then back off until
    // the fetch fits the budget.
    var pixelAtZero = 156543.034 * Math.cos(midLat * Math.PI / 180);
    var zoom = Math.min(TERRAIN_MAX_ZOOM,
                        Math.max(0, Math.ceil(Math.log(pixelAtZero / spacing) / Math.LN2)));
    while (zoom > 1 && tileCount(want, zoom) > TERRAIN_TILES) zoom--;
    // Nodes no finer than the pixels behind them. Where the budget backed the zoom off,
    // a finer grid is only nearest-pixel steps — a staircase, not detail.
    spacing = Math.max(spacing, pixelAtZero / Math.pow(2, zoom));
    return {
      west: want.west, east: want.east, south: want.south, north: want.north,
      cols: Math.max(2, Math.round(widthM / spacing) + 1),
      rows: Math.max(2, Math.round(heightM / spacing) + 1),
      spacing: spacing,
      tiles: tileCount(want, zoom),
      remote: { url: url, zoom: zoom }
    };
  }

  function loadTerrainDetail(plan) {
    terrainPending = plan;
    loadTerrain(plan).then(function (patch) {
      if (terrainPending === plan) terrainPending = null;
      if (!renderer) return;
      setTerrainDetail(patch);
      // Ask again. While this patch was in the air it covered the view and blocked any
      // newer plan, so a reader who zoomed in meanwhile would be left on ground fetched
      // for where they had been. A plan that matches what just landed returns null.
      scheduleDetail();
    }, function () {
      // A patch that does not arrive changes nothing: the base grid is still there.
      if (terrainPending === plan) terrainPending = null;
    });
  }

  // Where the reader last zoomed, in canvas pixels; the middle of the fit until then.
  var lastFocus = null;

  // **A patch changes the ground's height, and so where it is on screen.** Over the
  // Dolomites the ground under the cursor sat 5, 19 and then 39 px from it as each finer
  // patch landed — the map jumping away a moment after the reader stopped zooming, which
  // is what "zoom is broken at the detailed levels" was. So the ground at the point the
  // reader zoomed on is held: picked before the patch goes in, re-projected at its new
  // height after, and the pan takes up the difference. The terrain around it still
  // sharpens; the place the reader was looking at does not move.
  function setTerrainDetail(patch) {
    var focus = lastFocus || [anchorX(), anchorY()];
    var held = W && H ? groundAtCanvas(focus[0], focus[1]) : null;
    var lon = held ? lon0 + held[0] / mPerDegLon : null;
    var lat = held ? lat0 + held[1] / mPerDegLat : null;
    terrainDetail = patch;
    if (renderer && renderer.setTerrainDetail) renderer.setTerrainDetail(patch);
    reshadeImagery();
    if (held) {
      var now = project(held[0], held[1], groundAt(lon, lat));
      view.panX += focus[0] - now[0];
      view.panY += focus[1] - now[1];
    }
    draw();
  }

  // Images ready to drape, keyed by style: the embedded ones from the start, a stitched
  // mosaic once it has been fetched. Switching back to one is then instant.
  var ready = {};
  // The zoom the base mosaic reached, which is what a detail fetch has to beat. Zero
  // until one has been stitched — an embedded image has no tile zoom, and over a whole
  // country it is coarse enough that the first detail fetch is always worth making.
  var mosaicZoom = 0;

  // A segment shows which state is current by being pressed, not by relabelling itself.
  // `aria-pressed` and the `is-on` class move together, so the keyboard, the buttons and
  // a screen reader all agree about what the view is showing.
  function pressSegment(selector, matches) {
    root.querySelectorAll(selector).forEach(function (button) {
      var on = matches(button);
      button.classList.toggle('is-on', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function setVertical(level) {
    view.vertical = level;
    // Exaggeration changes how tall the scene projects, which is a framing change and
    // not a gesture, so it is one of the three things allowed to re-fit the scale.
    refitScale();
    pressSegment('[data-view3d-act="exaggerate-set"]', function (button) {
      return parseFloat(button.dataset.vertical) === level;
    });
  }

  function setBasemapStyle(next) {
    pressSegment('[data-view3d-act="basemap-set"]', function (button) {
      return button.dataset.style === next;
    });
    if (next === 'off') { view.map = false; draw(); return; }
    view.map = true;
    // The detail patch belongs to the style it was stitched from — satellite imagery
    // laid over a road map is not a sharper road map, it is two maps.
    if (style !== next) { detail = null; detailPending = null; }
    style = next;
    if (ready[next]) {
      basemap = ready[next].shaded || ready[next].image;
      scene.basemap = ready[next].box;
      sampleCellColours();
      showCredit(ready[next].box.attribution);
      draw();
      return;
    }
    basemap = null;
    cellColour = null;
    draw();
    loadTiles(next);
  }

  // Decode whatever was baked in. Each style is an independent image, so a document that
  // carries only one still shows that one and falls back to tiles for the other.
  Object.keys(embedded).forEach(function (name) {
    var box = embedded[name];
    var image = new Image();
    image.onload = function () {
      ready[name] = { image: image, box: box };
      // Shading depends on the style (a photograph needs less than a road map), so it is
      // baked per style rather than once.
      var was = style;
      style = name;
      ready[name].shaded = shadedTexture(image, box);
      style = was;
      if (style === name) setBasemapStyle(name);
    };
    image.src = box.uri;
  });

  function showCredit(text) {
    var credit = root.querySelector('.view3d-credit');
    if (credit) credit.textContent = text;
  }

  function showLoading(label) {
    var box = root.querySelector('.view3d-loading');
    if (!box) return;
    box.querySelector('.view3d-loading-text').textContent = label;
    box.hidden = false;
  }

  function hideLoading() {
    var box = root.querySelector('.view3d-loading');
    if (box) box.hidden = true;
  }

  // How long a stitch may go with *no tile arriving at all* before it is given up on.
  // A stall detector rather than a deadline: a slow connection trickling 80 tiles in is
  // still making progress and must not be cut off, but a request that hangs — which is
  // what a blocked host or a captive portal does, rather than returning an error — used
  // to leave "Loading satellite tiles…" on screen forever. Measured here against a
  // proxy that drops the tile hosts: nothing ever resolved, and before this the credit
  // line and the spinner both ran indefinitely.
  var TILE_STALL_MS = 12000;

  // One stitcher for both fetches. `plan` is absent for the base mosaic — the whole
  // terrain, at whatever zoom 120 tiles reaches — and present for a detail mosaic over a
  // smaller box at a finer zoom. The differences are all at the ends: a detail fetch
  // takes over neither the spinner nor the credit line, and failing it changes nothing
  // the reader can see, because the base image is still there underneath.
  function loadTiles(styleName, plan) {
    var source = scene.tiles && scene.tiles[styleName];
    if (!source) return;
    if (plan ? detailPending : loading) return;
    if (plan) {
      detailPending = plan.box;
    } else {
      loading = true;
      showCredit('Loading ' + source.label.toLowerCase() + ' tiles…');
      showLoading('Loading ' + source.label.toLowerCase() + '…');
    }
    var want = plan ? plan.box : dem;
    var zoom = plan ? plan.zoom : tileZoom(source);
    var a = tileNumbers(want.west, want.north, zoom);
    var b = tileNumbers(want.east, want.south, zoom);
    var x0 = Math.floor(a[0]), x1 = Math.floor(b[0]);
    var y0 = Math.floor(a[1]), y1 = Math.floor(b[1]);
    var size = 256;
    var mosaic = document.createElement('canvas');
    mosaic.width = (x1 - x0 + 1) * size;
    mosaic.height = (y1 - y0 + 1) * size;
    var mctx = mosaic.getContext('2d');
    var pending = 0, done = 0;

    // One canvas per layer, composited in declaration order at the end. Painting every
    // tile straight into the mosaic as it arrives makes z-order a race — the labels
    // layer is requested second but frequently answers first, and then the imagery
    // covers it.
    var layers = source.layers.map(function () {
      var layer = document.createElement('canvas');
      layer.width = mosaic.width;
      layer.height = mosaic.height;
      return layer;
    });

    // The mosaic covers whole tiles, so its geographic box is larger than the DEM's.
    function lonOf(x) { return x / Math.pow(2, zoom) * 360 - 180; }
    function latOf(y) {
      var t = Math.PI - 2 * Math.PI * y / Math.pow(2, zoom);
      return 180 / Math.PI * Math.atan(0.5 * (Math.exp(t) - Math.exp(-t)));
    }
    var box = {
      west: lonOf(x0), east: lonOf(x1 + 1),
      north: latOf(y0), south: latOf(y1 + 1),
      attribution: source.attribution
    };

    var settled = false;
    var watchdog = null;

    function stall() {
      if (settled) return;
      settled = true;
      if (plan) { detailPending = null; return; }   // the base image carries on
      loading = false;
      hideLoading();
      showCredit('Map imagery timed out — hillshade only');
      pressSegment('[data-view3d-act="basemap-set"]', function (button) {
        return button.dataset.style === 'off';
      });
      view.map = false;
      draw();
    }

    function progress() {
      if (watchdog) clearTimeout(watchdog);
      watchdog = setTimeout(stall, TILE_STALL_MS);
    }

    function finish() {
      if (settled) return;    // the watchdog gave up first
      settled = true;
      if (watchdog) clearTimeout(watchdog);
      if (plan) {
        detailPending = null;
        if (done === 0) return;
        layers.forEach(function (layer) { mctx.drawImage(layer, 0, 0); });
        var patch = new Image();
        patch.onerror = function () { detailPending = null; };
        patch.onload = function () {
          if (style !== styleName) return;   // the reader cycled on while we stitched
          // Shaded exactly as the base image is, or the sharp patch would read as a
          // flat rectangle laid over hillshaded ground — the terrain looks *wrong*
          // rather than merely different, because relief is what carries its shape.
          detail = {
            image: shadedTexture(patch, box) || patch,
            // Kept unshaded, so a new light or finer ground can shade it again.
            raw: patch,
            box: box, style: styleName, zoom: zoom
          };
          draw();
        };
        patch.src = mosaic.toDataURL('image/jpeg', 0.85);
        return;
      }
      loading = false;
      if (done === 0) {
        // No tiles at all: almost certainly a content-security policy. Skip to the next
        // style the document can actually show rather than leaving the button dead.
        var fallback = order.filter(function (name) {
          return name !== styleName && (ready[name] || embedded[name]);
        })[0];
        if (fallback) { setBasemapStyle(fallback); return; }
        hideLoading();
        showCredit('Map imagery unavailable here — hillshade only');
        pressSegment('[data-view3d-act="basemap-set"]', function (button) {
          return button.dataset.style === 'off';
        });
        view.map = false;
        draw();
        return;
      }
      mosaicZoom = zoom;
      layers.forEach(function (layer) { mctx.drawImage(layer, 0, 0); });
      var image = new Image();
      // Hidden once the stitched image has decoded, not when the last tile arrives:
      // `shadedTexture` and `sampleCellColours` still run after that, and hiding early
      // leaves the reader looking at unchanged terrain with nothing happening.
      image.onerror = hideLoading;
      image.onload = function () {
        var was = style;
        style = styleName;
        ready[styleName] = {image: image, box: box, shaded: shadedTexture(image, box)};
        style = was;
        if (style !== styleName) return;    // the reader cycled on while we stitched
        basemap = ready[styleName].shaded || image;
        scene.basemap = box;
        sampleCellColours();
        showCredit(source.attribution);
        hideLoading();
        draw();
      };
      image.src = mosaic.toDataURL('image/jpeg', 0.82);
    }

    progress();
    source.layers.forEach(function (template, index) {
      for (var ty = y0; ty <= y1; ty++) {
        for (var tx = x0; tx <= x1; tx++) {
          pending++;
          (function (tx, ty, index) {
            var image = new Image();
            image.crossOrigin = 'anonymous';   // needed to read the mosaic back out
            image.onload = function () {
              layers[index].getContext('2d').drawImage(
                image, (tx - x0) * size, (ty - y0) * size, size, size);
              done++;
              progress();
              if (--pending === 0) finish();
            };
            image.onerror = function () {
              // An error is progress too: the host answered, so the load is not stalled.
              progress();
              if (--pending === 0) finish();
            };
            image.src = template.replace('{z}', zoom).replace('{x}', tx).replace('{y}', ty);
          })(tx, ty, index);
        }
      }
    });
    if (!pending) finish();
  }

  // Nothing baked in for the opening style: fetch it. An embedded one is already decoding.
  if (style && !embedded[style]) loadTiles(style);

  function world(x, y, z) {
    var cy = Math.cos(view.yaw), sy = Math.sin(view.yaw);
    var wx = x * cy - y * sy;
    var wy = x * sy + y * cy;
    var wz = (z - dem.min) * view.vertical;
    var cp = Math.cos(view.pitch), sp = Math.sin(view.pitch);
    // Screen y grows downward, so the northward axis has to be negated: without it
    // the far side of the terrain lands at the bottom of the canvas, which is the
    // same picture as looking from the north — east and west come out swapped.
    return [wx, -wy * sp - wz * cp, wy];
  }

  // Fit is recomputed per frame because yaw and pitch change the outline. It is
  // deliberately computed at ×1 regardless of the current exaggeration: fitting the
  // exaggerated outline zooms out by exactly the factor the user just asked for, which
  // is why the ×2 button appeared to do nothing at all.
  var fit = { scale: 1, dx: 0, dy: 0 };
  // The scale the scene was fitted at, held rather than re-measured every frame.
  //
  // `refit()` used to derive it from the bounding box of the *rotated, pitched* scene,
  // so turning the view rescaled it: a 45 degree twist shrank the ground scale from
  // 778 px per 10 km to 345 at pitch 0.18 — the view zooming itself out by 2.3x in the
  // middle of a gesture that was only meant to rotate. That is what "it rotates weirdly
  // when tilted down" is, and it is worst at low pitch because there the projected
  // height of the scene is dominated by terrain relief rather than by its northing, so
  // the box a rotation sweeps out changes most. A yaw is not a zoom, and now it is not
  // one. `refitScale()` asks for a new measurement, and only the three things that
  // genuinely change the framing call it: a resize, a change of vertical exaggeration,
  // and the reset button.
  var fitBase = 0;
  function refitScale() { fitBase = 0; }
  // Where the fit puts the middle of the scene. zoomAt has to measure the cursor from
  // this point, not from the canvas corner, so it is named rather than written twice.
  function anchorX() { return W / 2; }
  function anchorY() { return H * 0.58; }
  function refit() {
    var wanted = view.vertical;
    view.vertical = 1;
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    function consider(p) {
      if (p[0] < minX) minX = p[0];
      if (p[0] > maxX) maxX = p[0];
      if (p[1] < minY) minY = p[1];
      if (p[1] > maxY) maxY = p[1];
    }
    // A payload may name the part of its ground to open on (`view.focus`, a lon/lat
    // box): the airspace map carries the Alps for the planner, and opens on the country
    // its airspace covers. Otherwise the whole grid, sampled, which keeps this cheap.
    var focus = scene.view && scene.view.focus;
    if (focus) {
      [[focus.west, focus.south], [focus.east, focus.south], [focus.west, focus.north],
       [focus.east, focus.north]].forEach(function (corner) {
        var m = toMetres(corner[0], corner[1]);
        consider(world(m[0], m[1], dem.min));
      });
    } else {
      for (var r = 0; r < rows; r += 3) {
        for (var c = 0; c < cols; c += 6) {
          var i = r * cols + c;
          consider(world(nodeX[i], nodeY[i], dem.z[i]));
        }
      }
    }
    var t = scene.track;
    for (var k = 0; k < t.lon.length; k += 7) {
      var m = toMetres(t.lon[k], t.lat[k]);
      consider(world(m[0], m[1], t.alt[k]));
    }
    // Slight overfill: the bounds are of a *rotated* rectangle, whose bounding box is
    // wider than the rectangle itself, so fitting the box exactly leaves visible margins
    // on every side. Overflowing the terrain edge costs nothing — it is only terrain.
    if (!fitBase) {
      fitBase = Math.min(W * 1.08 / Math.max(maxX - minX, 1),
                         H * 1.02 / Math.max(maxY - minY, 1));
    }
    view.vertical = wanted;
    fit.scale = fitBase * view.zoom;
    fit.dx = anchorX() - (minX + maxX) / 2 * fit.scale;
    // Keep the *ground* centred rather than the whole scene: as the exaggeration grows
    // the flight should climb up the canvas, not push the terrain off the bottom.
    fit.dy = anchorY() - (minY + maxY) / 2 * fit.scale;
  }

  function project(x, y, z) {
    var w = world(x, y, z);
    return [fit.dx + w[0] * fit.scale + view.panX, fit.dy + w[1] * fit.scale + view.panY];
  }

  // Grid node positions in metres, computed once; only the projection changes.
  var cols = dem.cols, rows = dem.rows;
  var nodeX = new Float64Array(rows * cols);
  var nodeY = new Float64Array(rows * cols);
  for (var r = 0; r < rows; r++) {
    var lat = dem.north - (dem.north - dem.south) * r / (rows - 1);
    for (var c = 0; c < cols; c++) {
      var lon = dem.west + (dem.east - dem.west) * c / (cols - 1);
      var m = toMetres(lon, lat);
      nodeX[r * cols + c] = m[0];
      nodeY[r * cols + c] = m[1];
    }
  }

  // How hard to shade a draped image. Satellite imagery is a photograph and already
  // shows its own light; a cartographic map is flat fill and needs real relief on top.
  function reliefBoost() { return style === 'satellite' ? 1.0 : 1.5; }

  // The lit range this particular terrain actually spans, measured once. A fixed
  // shading curve assumes alpine relief: over the gentle ground most flights happen on,
  // `lit` stays within a few hundredths of flat-ground illumination and the overlay does
  // nothing at all — which is how a road map came out looking like a flat sheet. Stretch
  // the observed range instead, so relief reads at whatever scale the ground has.
  // Where the light comes from — see setLight below. Declared here because measureLit()
  // runs a few lines down, at startup: declared where setLight is, it was still
  // undefined then, every slope came out NaN, the lit range stayed zero, and any page
  // without a sun track — the airspace map and the planner — never had a hillshade at
  // all. The report was spared only because its sun track relights once it is known.
  var lightX = -0.55, lightY = 0.55, lightZ = 0.63;
  var litMid = 0.86, litSpread = 0;
  function measureLit() {
    litMid = 0.86; litSpread = 0;
    var lo = Infinity, hi = -Infinity;
    for (var r = 0; r < rows; r += 2) {
      for (var c = 0; c < cols; c += 2) {
        var lit = shadeFactor(r, c);
        if (lit < lo) lo = lit;
        if (lit > hi) hi = lit;
      }
    }
    if (!isFinite(lo) || hi - lo < 0.01) return;   // genuinely flat: leave it unshaded
    litMid = (lo + hi) / 2;
    litSpread = (hi - lo) / 2;
  }
  measureLit();

  // The heightfield is the only part of this that a depth buffer changes, so it is the
  // only part a backend may replace. `view3d_gl.py` registers one; with nothing
  // registered — or on a machine with no WebGL, or after a context loss — the per-cell
  // 2D drape below runs exactly as it always has.
  //
  // Everything else stays here and is shared: one camera, one set of gestures, one tile
  // stitcher, one set of probes. That is deliberate. The camera in particular has to
  // invert through groundUnder()/holdGround() for every gesture to anchor, and the
  // surest way to keep a second renderer bit-compatible with that is for it to read the
  // same `view` and `fit` objects rather than to own a copy.
  var renderer = window.__view3dBackend ? window.__view3dBackend({
    canvas: canvas,
    dem: dem,
    cols: cols,
    rows: rows,
    nodeX: nodeX,
    nodeY: nodeY,
    view: view,          // held by reference: the gestures mutate it in place
    fit: fit,            // ditto, recomputed by refit() before every frame
    size: function () { return [W, H]; },
    shadeFactor: shadeFactor,
    slopeShade: slopeShade,
    toMetres: function (lon, lat) { return toMetres(lon, lat); },
    lit: function () { return { mid: litMid, spread: litSpread }; },
    // The already-shaded basemap and the geographic box it covers. Both change when the
    // reader cycles the style or a tile mosaic finishes stitching, and the backend
    // notices by identity rather than by being told.
    texture: function () { return basemap; },
    textureBox: function () { return scene.basemap; },
    // The sharper mosaic over whatever the reader has zoomed in on, or null. Same
    // contract as `texture()`: handed over by identity, and the backend decides when it
    // has changed.
    detail: function () { return detail; },
    // Hand the heightfield back to the 2D path. Context loss on a phone is real, and a
    // blank panel is a worse outcome than a slower one.
    fallback: function () {
      renderer = null; terrainDetail = null; terrainPending = null;
      sampleCellColours(); draw();
    }
  }) : null;

  // Where the light comes from, in the frame the gradients below are computed in: x
  // east, y *south* (rows run north to south), z up. The default is the fixed direction
  // this always used; `setLight` replaces it with the real sun when the payload carries
  // a day track, which is what makes "which slopes were lit, and when" a question the
  // view can answer rather than a decoration.
  // (Declared up with the lit range, which is measured against it before this point.)

  function setLight(azimuth, elevation) {
    // A sun on the horizon lights nothing and the hillshade collapses to a silhouette,
    // so hold it a few degrees up. Below the horizon the terrain is drawn by the same
    // rule — there is no night mode; the label says the sun is down and the shading
    // shows the last light it had.
    var el = Math.max(elevation, 3) * Math.PI / 180;
    var az = azimuth * Math.PI / 180;
    lightX = Math.cos(el) * Math.sin(az);
    lightY = -Math.cos(el) * Math.cos(az);   // north in the payload, south in this frame
    lightZ = Math.sin(el);
  }

  function shadeFactor(r, c) {
    var i = r * cols + c;
    var here = dem.z[i];
    var right = dem.z[i + (c + 1 < cols ? 1 : 0)];
    var below = dem.z[i + (r + 1 < rows ? cols : 0)];
    var cellX = spanX / (cols - 1), cellY = spanY / (rows - 1);
    return slopeShade((right - here) / cellX, (below - here) / cellY);
  }

  // The light on a slope, from its two gradients — x east, y south. Shared with the
  // detail terrain, which has its own grid and the same sun.
  function slopeShade(dzdx, dzdy) {
    var nx = -dzdx, ny = -dzdy, nz = 1;
    var len = Math.sqrt(nx * nx + ny * ny + nz * nz);
    var light = (nx * lightX + ny * lightY + nz * lightZ) / len;
    return Math.max(0.25, Math.min(1.15, 0.55 + light * 0.65));
  }

  function shade(r, c) {
    // Slope shading from the two in-grid gradients, lit from the north-west, stretched
    // to this terrain's own lit range for the same reason the draped version is.
    var i = r * cols + c;
    var here = dem.z[i];
    var lit = 0.96;
    if (litSpread > 0) {
      var t = Math.max(-1, Math.min(1, (shadeFactor(r, c) - litMid) / litSpread));
      lit = 0.86 + t * 0.30;
    }
    // Elevation tint: low ground greener, high ground paler and greyer.
    var t = Math.min(1, Math.max(0, (here - dem.min) / Math.max(dem.max - dem.min, 1)));
    var rr = (120 + t * 95) * lit;
    var gg = (135 + t * 80) * lit;
    var bb = (105 + t * 95) * lit;
    return 'rgb(' + (rr | 0) + ',' + (gg | 0) + ',' + (bb | 0) + ')';
  }

  // The map has to follow the relief, not lie flat under it: at these vertical
  // exaggerations a flat floor and an exaggerated mesh separate visibly. Drawing it in
  // north-south bands, each affine-fitted to that band's mean ground height, keeps the
  // names readable and the geometry honest for a dozen drawImage calls a frame.
  var STRIPS = 10;
  // Banding exists to follow relief. Where there is little relief it only buys seams,
  // so flat ground gets one exact affine fit at the mean elevation instead.
  var BAND_THRESHOLD = 500;  // metres of terrain range

  // Ground elevation anywhere in the box, bilinear on the DEM grid. Everything that
  // belongs on the ground — the track's shadow, the cursor's drop line — needs this:
  // drawing it on a flat plane at the minimum elevation makes it slide against the
  // terrain as the view rotates, because it is simply not where the ground is.
  function groundAt(lon, lat) {
    var patch = terrainDetail;
    if (patch && lon >= patch.west && lon <= patch.east
        && lat >= patch.south && lat <= patch.north) {
      return bilinear(patch, lon, lat);
    }
    var gx = (lon - dem.west) / (dem.east - dem.west) * (cols - 1);
    var gy = (dem.north - lat) / (dem.north - dem.south) * (rows - 1);
    gx = Math.max(0, Math.min(cols - 1, gx));
    gy = Math.max(0, Math.min(rows - 1, gy));
    var x0 = Math.floor(gx), y0 = Math.floor(gy);
    var x1 = Math.min(x0 + 1, cols - 1), y1 = Math.min(y0 + 1, rows - 1);
    var fx = gx - x0, fy = gy - y0;
    var top = dem.z[y0 * cols + x0] * (1 - fx) + dem.z[y0 * cols + x1] * fx;
    var bottom = dem.z[y1 * cols + x0] * (1 - fx) + dem.z[y1 * cols + x1] * fx;
    return top * (1 - fy) + bottom * fy;
  }

  function bilinear(grid, lon, lat) {
    var gx = (lon - grid.west) / (grid.east - grid.west) * (grid.cols - 1);
    var gy = (grid.north - lat) / (grid.north - grid.south) * (grid.rows - 1);
    gx = Math.max(0, Math.min(grid.cols - 1, gx));
    gy = Math.max(0, Math.min(grid.rows - 1, gy));
    var x0 = Math.floor(gx), y0 = Math.floor(gy);
    var x1 = Math.min(x0 + 1, grid.cols - 1), y1 = Math.min(y0 + 1, grid.rows - 1);
    var fx = gx - x0, fy = gy - y0, n = grid.cols;
    var top = grid.z[y0 * n + x0] * (1 - fx) + grid.z[y0 * n + x1] * fx;
    var bottom = grid.z[y1 * n + x0] * (1 - fx) + grid.z[y1 * n + x1] * fx;
    return top * (1 - fy) + bottom * fy;
  }

  // Source rectangle in basemap pixels for a grid cell, so the map can be drawn cell
  // by cell and therefore sits *on* the surface rather than under it.
  // The shading has to live in the texture, not in the geometry pass.
  //
  // Tinting each cell was three artefacts in a row. Cells must overdraw their neighbours,
  // because a projected quad is not a parallelogram and the affine texture fit leaves
  // hairline gaps otherwise — but a semi-transparent tint drawn over that overdraw lands
  // twice in the overlap, which is a dark lattice over the whole slab; matching the tint
  // to a smaller extent instead gives every cell an untinted border, which is the same
  // lattice again. There is no per-cell extent that is right.
  //
  // The basemap raster and the DEM are both axis-aligned in lon/lat, so the illumination
  // can be composited into a copy of the image once, at grid resolution, and stretched by
  // the browser — which also interpolates it, so the result is smooth rather than faceted.
  function shadedTexture(image, box) {
    var iw = image.naturalWidth || image.width;
    var ih = image.naturalHeight || image.height;
    if (!iw || !ih) return image;
    var out = document.createElement('canvas');
    out.width = iw;
    out.height = ih;
    var octx = out.getContext('2d');
    octx.drawImage(image, 0, 0);
    if (litSpread <= 0) return out;

    var shade = document.createElement('canvas');
    shade.width = cols;
    shade.height = rows;
    var sctx = shade.getContext('2d');
    var pixels = sctx.createImageData(cols, rows);
    var boost = reliefBoost();
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var t = Math.max(-1, Math.min(1, (shadeFactor(r, c) - litMid) / litSpread));
        var i = (r * cols + c) * 4;
        if (t >= 0) {
          pixels.data[i] = 255; pixels.data[i + 1] = 252; pixels.data[i + 2] = 242;
        } else {
          pixels.data[i] = 18; pixels.data[i + 1] = 26; pixels.data[i + 2] = 38;
        }
        pixels.data[i + 3] = Math.round(Math.min(Math.abs(t) * 0.34 * boost, 1) * 255);
      }
    }
    sctx.putImageData(pixels, 0, 0);

    // Where the DEM's box sits inside the image's, in the same linear lon/lat mapping
    // sourceRect uses — so the shading registers with the texture cell for cell.
    // The whole shade goes onto one layer first and the layer onto the image, so the
    // detail terrain's own shading can *replace* the base grid's where the patch lies
    // rather than being laid over it: two hillshades composited is a double shadow.
    var layer = document.createElement('canvas');
    layer.width = iw;
    layer.height = ih;
    var lctx = layer.getContext('2d');
    lctx.imageSmoothingEnabled = true;
    lctx.imageSmoothingQuality = 'high';
    var place = function (grid) {
      return [(grid.west - box.west) / (box.east - box.west) * iw,
              (box.north - grid.north) / (box.north - box.south) * ih,
              (grid.east - box.west) / (box.east - box.west) * iw,
              (box.north - grid.south) / (box.north - box.south) * ih];
    };
    var at = place(dem);
    lctx.drawImage(shade, 0, 0, cols, rows, at[0], at[1], at[2] - at[0], at[3] - at[1]);
    // The finer ground's hillshade where there is finer ground. Without it a zoomed-in
    // photograph carried the base grid's 2.5 km shading: the new ridges stood up in the
    // geometry and the light on them still belonged to the old ones.
    var patch = terrainDetail;
    if (patch && patch.east > box.west && patch.west < box.east
        && patch.north > box.south && patch.south < box.north) {
      var fine = patchShade(patch, boost);
      var p = place(patch);
      lctx.clearRect(p[0], p[1], p[2] - p[0], p[3] - p[1]);
      lctx.drawImage(fine, 0, 0, patch.cols, patch.rows, p[0], p[1], p[2] - p[0], p[3] - p[1]);
    }
    octx.drawImage(layer, 0, 0);
    return out;
  }

  // The same shade, from the detail terrain's grid and the same light and lit range —
  // so where the patch's shading meets the base's, the two are one curve at two
  // resolutions and not two different curves.
  function patchShade(patch, boost) {
    var pc = patch.cols, pr = patch.rows, z = patch.z;
    var a = toMetres(patch.west, patch.north), b = toMetres(patch.east, patch.south);
    var cellX = (b[0] - a[0]) / (pc - 1), cellY = (a[1] - b[1]) / (pr - 1);
    var canvasOut = document.createElement('canvas');
    canvasOut.width = pc;
    canvasOut.height = pr;
    var pctx = canvasOut.getContext('2d');
    var pixels = pctx.createImageData(pc, pr);
    for (var r = 0; r < pr; r++) {
      for (var c = 0; c < pc; c++) {
        var i = r * pc + c;
        var right = z[i + (c + 1 < pc ? 1 : 0)], below = z[i + (r + 1 < pr ? pc : 0)];
        var t = Math.max(-1, Math.min(1, (slopeShade((right - z[i]) / cellX,
                                                     (below - z[i]) / cellY)
                                          - litMid) / litSpread));
        var k = i * 4;
        if (t >= 0) {
          pixels.data[k] = 255; pixels.data[k + 1] = 252; pixels.data[k + 2] = 242;
        } else {
          pixels.data[k] = 18; pixels.data[k + 1] = 26; pixels.data[k + 2] = 38;
        }
        pixels.data[k + 3] = Math.round(Math.min(Math.abs(t) * 0.34 * boost, 1) * 255);
      }
    }
    pctx.putImageData(pixels, 0, 0);
    return canvasOut;
  }

  // Every draped image re-shaded from the ground and the light as they are now: the base
  // mosaic of each style, and the detail mosaic from the unshaded copy it keeps. Called
  // when the sun moves and when a finer terrain patch lands.
  function reshadeImagery() {
    var was = style;
    Object.keys(ready).forEach(function (name) {
      // Each style at its own strength (reliefBoost reads `style`), as it was first baked.
      style = name;
      if (ready[name].image) ready[name].shaded = shadedTexture(ready[name].image,
                                                               ready[name].box);
    });
    style = was;
    if (style && ready[style]) basemap = ready[style].shaded || ready[style].image;
    if (detail && detail.raw) detail.image = shadedTexture(detail.raw, detail.box) || detail.raw;
  }

  function sourceRect(r, c, rStep, cStep) {
    var bm = scene.basemap;
    var iw = basemap.naturalWidth || basemap.width;
    var ih = basemap.naturalHeight || basemap.height;
    var lonW = dem.west + (dem.east - dem.west) * c / (cols - 1);
    var lonE = dem.west + (dem.east - dem.west) * Math.min(c + cStep, cols - 1) / (cols - 1);
    var latN = dem.north - (dem.north - dem.south) * r / (rows - 1);
    var latS = dem.north - (dem.north - dem.south) * Math.min(r + rStep, rows - 1) / (rows - 1);
    var sx = (lonW - bm.west) / (bm.east - bm.west) * iw;
    var ex = (lonE - bm.west) / (bm.east - bm.west) * iw;
    var sy = (bm.north - latN) / (bm.north - bm.south) * ih;
    var ey = (bm.north - latS) / (bm.north - bm.south) * ih;
    return [sx, sy, Math.max(ex - sx, 0.5), Math.max(ey - sy, 0.5)];
  }

  // One triangle of a cell, textured exactly.
  //
  // Three points determine an affine map, so a triangle's texture mapping is exact even
  // when the cell as a whole has folded — which is the whole reason for this path. The
  // clip is set under the identity transform (clips live in device space) and the texture
  // transform is applied after it.
  function texturedTriangle(a, b, c, m11, m12, m21, m22, rect) {
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(b[0], b[1]);
    ctx.lineTo(c[0], c[1]);
    ctx.closePath();
    ctx.clip();
    ctx.setTransform(m11, m12, m21, m22, a[0], a[1]);
    // A whisker of overdraw so the shared edge of the two triangles does not show.
    ctx.drawImage(basemap, rect[0], rect[1], rect[2], rect[3], -0.01, -0.01, 1.02, 1.02);
    ctx.restore();
  }

  // The convex hull of the cell's four projected corners, as a filled polygon.
  //
  // A folded cell has to be covered by *one convex* shape. Its own outline is
  // self-intersecting, and canvas fills that as a bowtie — the wedge artefact. Splitting it
  // into two triangles is no better: for a folded quad the two triangles overlap and their
  // union leaves slivers uncovered, which then show whatever was painted earlier, which is
  // another wedge. The hull covers the whole cell, always convex, in one fill.
  function fillHull(points) {
    var sorted = points.slice().sort(function (a, b) {
      return a[0] - b[0] || a[1] - b[1];
    });
    var chain = [];
    for (var pass = 0; pass < 2; pass++) {
      var start = chain.length;
      for (var i = 0; i < 4; i++) {
        var q = pass === 0 ? sorted[i] : sorted[3 - i];
        while (chain.length - start >= 2 &&
               cross(chain[chain.length - 2], chain[chain.length - 1], q) <= 0) {
          chain.pop();
        }
        chain.push(q);
      }
      chain.pop();
    }
    if (chain.length < 3) return;
    ctx.beginPath();
    ctx.moveTo(chain[0][0], chain[0][1]);
    for (var k = 1; k < chain.length; k++) ctx.lineTo(chain[k][0], chain[k][1]);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }

  function cross(a, b, c) {
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  }

  // Convex, wound the way a front-facing cell is, and big enough to be worth drawing.
  function convex(a, b, c, d, facing) {
    var t1 = cross(a, b, c) * facing;
    if (t1 <= 0) return false;
    var t2 = cross(b, c, d) * facing;
    if (t2 <= 0) return false;
    var t3 = cross(c, d, a) * facing;
    if (t3 <= 0) return false;
    var t4 = cross(d, a, b) * facing;
    return t4 > 0 && (t1 + t2 + t3 + t4) > 0.5;
  }

  // Reused across frames: allocating 5 000 cells' worth of arrays per frame is its own
  // performance problem.
  var cellDepth = null, cellR = null, cellC = null, cellOrder = null;
  var stats = { cells: 0, folded: 0 };

  function drawTerrain(withMap) {
    // Paint far to near, by *camera* depth — which is not the same as the horizontal
    // depth this used to walk. `world()` projects to screen y = −(wy·sin p + wz·cos p),
    // so the axis into the screen is wy·cos p − wz·sin p: height matters, and at a
    // top-down pitch it is all that matters. Ordering by wy alone is exact only in the
    // horizontal-view limit, and everywhere else it lets a cell on the far side of a
    // ridge paint over the near slope — fragments of the wrong slope appearing as wedges
    // across a zoomed-in view. Sorting is a couple of milliseconds and it is correct.
    var cyaw = Math.cos(view.yaw), syaw = Math.sin(view.yaw);
    var cp = Math.cos(view.pitch), sp = Math.sin(view.pitch);
    var steps = texStep();
    var cStep = withMap ? steps.c : 1;
    var rStep = withMap ? steps.r : 1;

    var down = Math.floor((rows - 1) / rStep);
    var across = Math.floor((cols - 1) / cStep);
    var capacity = Math.max(down * across, 1);
    if (!cellDepth || cellDepth.length < capacity) {
      cellDepth = new Float64Array(capacity);
      cellR = new Int32Array(capacity);
      cellC = new Int32Array(capacity);
      cellOrder = new Int32Array(capacity);
    }
    var count = 0;
    for (var rr = 0; rr <= rows - 1 - rStep; rr += rStep) {
      for (var cc = 0; cc <= cols - 1 - cStep; cc += cStep) {
        var a00 = rr * cols + cc;
        var a01 = a00 + cStep;
        var a10 = a00 + cols * rStep;
        var zc = 0.25 * (dem.z[a00] + dem.z[a01] + dem.z[a10] + dem.z[a10 + cStep]);
        var xm = 0.5 * (nodeX[a00] + nodeX[a01]);
        var ym = 0.5 * (nodeY[a00] + nodeY[a10]);
        cellDepth[count] = (xm * syaw + ym * cyaw) * cp -
                           (zc - dem.min) * view.vertical * sp;
        cellR[count] = rr;
        cellC[count] = cc;
        cellOrder[count] = count;
        count++;
      }
    }
    // Sorting a typed array's *indices* needs a plain array; subarray+sort would reorder
    // the depths and lose the mapping.
    var order = Array.prototype.slice.call(cellOrder.subarray(0, count));
    order.sort(function (a, b) { return cellDepth[b] - cellDepth[a]; });
    stats.cells = count;
    stats.folded = 0;

    var refA = project(nodeX[0], nodeY[0], dem.min);

    // Which way round a front-facing cell comes out, taken from a flat cell at this
    // camera. Painting far-to-near needs no depth buffer, but it does not stop a cell on
    // the far side of a ridge from being drawn: at true scale that cell projects to a
    // sliver or turns inside out, and its affine texture map smears the imagery into a
    // wedge. Those were the pale triangles all over a zoomed-in view. Culling on the
    // determinant's sign and size drops exactly those cells and nothing else.
    var refB = project(nodeX[Math.min(cStep, cols - 1)],
                       nodeY[Math.min(cStep, cols - 1)], dem.min);
    var refIndex = Math.min(rStep, rows - 1) * cols;
    var refC = project(nodeX[refIndex], nodeY[refIndex], dem.min);
    var refDet = (refB[0] - refA[0]) * (refC[1] - refA[1]) -
                 (refB[1] - refA[1]) * (refC[0] - refA[0]);
    var facing = refDet >= 0 ? 1 : -1;

    for (var k = 0; k < count; k++) {
      {
        var slot = order[k];
        var r = cellR[slot], c = cellC[slot];
        var i00 = r * cols + c;
        var i01 = i00 + cStep;
        var i10 = i00 + cols * rStep;
        var i11 = i10 + cStep;
        var p00 = project(nodeX[i00], nodeY[i00], dem.z[i00]);
        var p01 = project(nodeX[i01], nodeY[i01], dem.z[i01]);
        var p11 = project(nodeX[i11], nodeY[i11], dem.z[i11]);
        var p10 = project(nodeX[i10], nodeY[i10], dem.z[i10]);

        // A cell whose projected quad has folded over gets a flat fill and no texture.
        //
        // Folds are unavoidable here: this is painter's order with no depth buffer, and on
        // a cliff seen from a shallow angle the far edge of a cell projects past its near
        // edge. Three ways to handle that, and only one is any good. Texturing it anyway
        // smears the imagery into a wedge — that was the original artefact. Skipping it
        // leaves a hole showing the sky, because painter's order means nothing was drawn
        // behind it. Filling it with the cell's own average colour reads as a plain facet,
        // which is what it is.
        var folded = !convex(p00, p01, p11, p10, facing);
        if (folded) stats.folded++;

        if (withMap) {
          if (folded) {
            // Flat fill over the cell's convex hull, in its own average colour. It cannot
            // be textured — the affine map of a folded quad smears the imagery — and it
            // cannot be skipped, because painter's order means nothing was drawn behind it
            // and the sky would show through. See fillHull for why the hull specifically.
            if (cellColour) {
              var fi = (Math.min(Math.floor(r / rStep), cellRows - 1) * cellCols +
                        Math.min(Math.floor(c / cStep), cellCols - 1)) * 4;
              ctx.fillStyle = 'rgb(' + cellColour[fi] + ',' + cellColour[fi + 1] + ',' +
                cellColour[fi + 2] + ')';
              ctx.strokeStyle = ctx.fillStyle;
              ctx.lineWidth = 1;
              fillHull([p00, p01, p11, p10]);
            }
            // While the camera is moving the flat hull is all it gets: two clipped draws
            // per folded cell is affordable for a still frame and not for a drag.
            if (!interacting) {
              var frect = sourceRect(r, c, rStep, cStep);
              texturedTriangle(p00, p01, p11,
                               p01[0] - p00[0], p01[1] - p00[1],
                               p11[0] - p01[0], p11[1] - p01[1], frect);
              texturedTriangle(p00, p11, p10,
                               p11[0] - p10[0], p11[1] - p10[1],
                               p10[0] - p00[0], p10[1] - p00[1], frect);
            }
            continue;
          }
          if (cellColour) {
            // Opaque base in the cell's average colour, on the true four corners.
            var ci = (Math.min(Math.floor(r / rStep), cellRows - 1) * cellCols +
                      Math.min(Math.floor(c / cStep), cellCols - 1)) * 4;
            ctx.beginPath();
            ctx.moveTo(p00[0], p00[1]);
            ctx.lineTo(p01[0], p01[1]);
            ctx.lineTo(p11[0], p11[1]);
            ctx.lineTo(p10[0], p10[1]);
            ctx.closePath();
            ctx.fillStyle = 'rgb(' + cellColour[ci] + ',' + cellColour[ci + 1] + ',' +
              cellColour[ci + 2] + ')';
            ctx.strokeStyle = ctx.fillStyle;
            ctx.lineWidth = 1;
            ctx.fill();
            ctx.stroke();
          }
          var rect = sourceRect(r, c, rStep, cStep);
          // Map the cell's own slice of the image onto the cell's parallelogram. No
          // clip and no save/restore: the drawn area *is* the cell, and a small
          // overdraw closes the hairline seams between neighbours.
          ctx.setTransform(
            p01[0] - p00[0], p01[1] - p00[1],
            p10[0] - p00[0], p10[1] - p00[1],
            p00[0], p00[1]
          );
          // Overdraw the *destination* to cover the affine seams, and expand the
          // *source* by the same fraction about the same centre so the texture keeps its
          // scale. Stretching the same slice over a larger quad — which is what an
          // overdraw on the destination alone does — scales the imagery up inside every
          // cell, so the content no longer lines up with its neighbour's, and every cell
          // boundary becomes a visible step. That was the lattice of squares: not the
          // shading, not the tint, but the texture drawn 10% too large in each cell.
          var grow = 0.05;
          ctx.drawImage(
            basemap,
            rect[0] - rect[2] * grow, rect[1] - rect[3] * grow,
            rect[2] * (1 + 2 * grow), rect[3] * (1 + 2 * grow),
            -grow, -grow, 1 + 2 * grow, 1 + 2 * grow
          );
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          continue;
        }

        ctx.beginPath();
        ctx.moveTo(p00[0], p00[1]);
        ctx.lineTo(p01[0], p01[1]);
        ctx.lineTo(p11[0], p11[1]);
        ctx.lineTo(p10[0], p10[1]);
        ctx.closePath();
        ctx.fillStyle = shade(r, c);
        // Stroke with the same colour: hairline gaps between quads otherwise show
        // the sky through the mesh.
        ctx.strokeStyle = ctx.fillStyle;
        ctx.lineWidth = 1;
        ctx.fill();
        ctx.stroke();
      }
    }
  }

  // ---- airspace ----------------------------------------------------------------------
  //
  // A second thing this view can carry, and the reason it is a map widget rather than a
  // flight renderer: `scene.airspaces` is a list of rings with a floor and a lid, and
  // nothing in here knows what an ATZ is. Each one is drawn as the *box* it is — from its
  // own floor to its own ceiling — which is the whole argument for showing airspace in 3D
  // at all. A CTR whose floor is 1 000 ft above you is a different object from one that
  // starts at the ground and a different object again from one that stops at 2 000 ft,
  // and on a flat map all three are the same red outline.
  //
  // Four numbers describe the vertical, and each is a height *or* a height above the
  // terrain, because the sources publish both: `f` is the floor as an altitude, `g` says
  // that floor is the ground itself, `fu`/`cu` are heights above the ground, and `c` is
  // the lid as an altitude. Anything ground-relative samples the DEM under each vertex,
  // so the box follows the hill rather than slicing through it.
  //
  // `t` marks a lid that is a cap rather than the airspace's own ceiling — see
  // `airspaces/scene.py` for why 21 zones get one — and a capped box is drawn without
  // its top face, so the eye reads it as continuing rather than as ending there.
  //
  // No depth buffer is involved: this is the 2D overlay canvas, so airspace always draws
  // over the terrain. That is right far more often than it is wrong — the floors that
  // matter are above the ground under them — and a wrong occlusion here would hide the
  // thing the layer exists to show.
  var airspaceFilter = null;
  var airspaceHits = [];    // { box, space }, in draw order; hit-tested back to front
  // Off to begin with wherever the payload offers a button, on wherever it does not: a
  // map of the airspace draws it, a map of a flight offers it.
  var airspaceOn = !scene.airspaceToggle;

  // Floor and lid at one vertex, in metres AMSL.
  function airspaceFloorAt(space, lon, lat) {
    if (space.g) return groundAt(lon, lat);
    if (space.fu != null) return groundAt(lon, lat) + space.fu;
    return space.f;
  }
  function airspaceTopAt(space, lon, lat) {
    if (space.cu != null) return groundAt(lon, lat) + space.cu;
    return space.c != null ? space.c : airspaceFloorAt(space, lon, lat);
  }

  // The box as three paths: the floor ring, the lid, and every wall in one path.
  //
  // The walls are one Path2D holding a subpath per side rather than a fill per side, and
  // that is the whole trick that makes a translucent box readable: filled once under the
  // nonzero rule, the union of overlapping quads takes the alpha exactly once. Filling
  // them one at a time doubles the alpha wherever a near wall crosses a far one, and a
  // 70-sided circle then paints itself into an opaque drum.
  function airspaceBox(space) {
    var n = space.lon.length;
    var floor = new Path2D(), lid = new Path2D(), walls = new Path2D();
    var fx = new Array(n), fy = new Array(n), tx = new Array(n), ty = new Array(n);
    var flat = true;
    for (var i = 0; i < n; i++) {
      var lon = space.lon[i], lat = space.lat[i];
      var m = toMetres(lon, lat);
      var bottom = airspaceFloorAt(space, lon, lat);
      // Never under its own floor. An AMSL lid over ground that rises past it would
      // otherwise turn the box inside out — walls crossing, the lid painted below the
      // floor — where the honest picture is a zone with nothing left of it up there.
      var top = Math.max(airspaceTopAt(space, lon, lat), bottom);
      var a = project(m[0], m[1], bottom), b = project(m[0], m[1], top);
      fx[i] = a[0]; fy[i] = a[1]; tx[i] = b[0]; ty[i] = b[1];
      if (Math.abs(b[1] - a[1]) > 0.7) flat = false;
      if (i === 0) { floor.moveTo(a[0], a[1]); lid.moveTo(b[0], b[1]); }
      else { floor.lineTo(a[0], a[1]); lid.lineTo(b[0], b[1]); }
    }
    floor.closePath();
    lid.closePath();
    // Under a pixel of height on screen there is no box to draw, only a ring drawn three
    // times: at country scale a 300 m okruh is a tenth of a pixel tall. Say so, and the
    // painter falls back to the flat ring rather than spending three paths on it.
    if (!flat) {
      for (var j = 0; j < n; j++) {
        var k = (j + 1) % n;
        walls.moveTo(fx[j], fy[j]);
        walls.lineTo(fx[k], fy[k]);
        walls.lineTo(tx[k], ty[k]);
        walls.lineTo(tx[j], ty[j]);
        walls.closePath();
      }
    }
    return { floor: floor, lid: lid, walls: walls, flat: flat };
  }

  function drawAirspaces() {
    var spaces = airspaceOn ? (scene.airspaces || []) : [];
    // Cleared, not kept: a hit list left behind by the last frame would still answer for
    // a layer that is no longer on screen.
    airspaceHits = [];
    if (!spaces.length) return;
    var colours = scene.airspaceColours || {};
    ctx.save();
    ctx.lineJoin = 'round';
    for (var i = 0; i < spaces.length; i++) {
      var space = spaces[i];
      if (airspaceFilter && !airspaceFilter(space)) continue;
      var colour = colours[space.k] || '#888888';
      var box = airspaceBox(space);
      var solid = space.k === 'circuit' ? 0.30 : 0.16;
      ctx.fillStyle = colour;
      ctx.strokeStyle = colour;
      ctx.globalAlpha = solid;
      ctx.fill(box.floor);
      if (!box.flat) {
        // Walls lighter than the floor: a box seen through its own two near walls is
        // already twice the ink of the ring it replaces, and the layer has to stay
        // something you can see the country through.
        ctx.globalAlpha = solid * 0.55;
        ctx.fill(box.walls);
        // The lid filled only where the box is its own ceiling. A capped box gets an
        // outline and no fill, which is what makes "this goes on up" visible at a glance.
        if (!space.t) {
          ctx.globalAlpha = solid * 0.7;
          ctx.fill(box.lid);
        }
        ctx.globalAlpha = 0.55;
        ctx.lineWidth = 1;
        ctx.save();
        if (space.t) ctx.setLineDash([4, 3]);
        ctx.stroke(box.lid);
        ctx.restore();
      }
      ctx.globalAlpha = 0.95;
      ctx.lineWidth = 1.3;
      ctx.stroke(box.floor);
      airspaceHits.push({ box: box, space: space });
    }
    ctx.restore();
  }

  // Which airspace is under a client point, or null. The last one drawn wins, because
  // the payload is ordered back to front and the smallest zone — the one a reader is
  // actually pointing at — is on top.
  //
  // The whole box answers, not just its floor: with the view tilted, most of what a
  // reader can see of a zone is its walls and its lid, and a hit test that only knew the
  // floor made two thirds of the drawn shape unpointable.
  function airspaceAt(clientX, clientY) {
    if (!airspaceHits.length) return null;
    var box = canvas.getBoundingClientRect();
    var x = (clientX - box.left) / box.width * W;
    var y = (clientY - box.top) / box.height * H;
    for (var i = airspaceHits.length - 1; i >= 0; i--) {
      var hit = airspaceHits[i].box;
      if (ctx.isPointInPath(hit.floor, x, y)
          || (!hit.flat && (ctx.isPointInPath(hit.lid, x, y)
                            || ctx.isPointInPath(hit.walls, x, y)))) {
        return airspaceHits[i].space;
      }
    }
    return null;
  }

  // The airspace label, for a panel that carries the layer as an option rather than as
  // its subject. The airspace *map* wires its own — it has a tooltip, a class legend and
  // a floor slider around it — so this only runs where the page has none of that and a
  // translucent shape would otherwise be an unnamed colour.
  //
  // Hover on a mouse, tap-to-pin on a touchscreen, and never while a gesture is running:
  // a touchscreen's pointerout means the finger lifted, not that the label stopped being
  // wanted, and a drag that fought the label for the frame would drop the frame rate of
  // the drag itself.
  var airspaceName = root.querySelector('.view3d-asp');

  function hideAirspaceName() {
    if (airspaceName) airspaceName.hidden = true;
  }

  function placeAirspaceName(space, clientX, clientY, above) {
    if (!airspaceName) return;
    airspaceName.textContent = space.n;
    airspaceName.hidden = false;
    var host = root.getBoundingClientRect();
    var left = clientX - host.left + (above ? -airspaceName.offsetWidth / 2 : 14);
    var top = clientY - host.top + (above ? -airspaceName.offsetHeight - 18 : 14);
    left = Math.max(6, Math.min(left, host.width - airspaceName.offsetWidth - 6));
    airspaceName.style.left = left + 'px';
    airspaceName.style.top = Math.max(6, top) + 'px';
  }

  if (airspaceName) {
    canvas.addEventListener('pointermove', function (event) {
      if (event.pointerType === 'touch' || event.buttons || !airspaceOn) return;
      var space = airspaceAt(event.clientX, event.clientY);
      if (space) placeAirspaceName(space, event.clientX, event.clientY, false);
      else hideAirspaceName();
    });
    canvas.addEventListener('pointerleave', hideAirspaceName);
    canvas.addEventListener('pointerdown', function (event) {
      if (event.pointerType !== 'touch' || !airspaceOn) return;
      var space = airspaceAt(event.clientX, event.clientY);
      if (space) placeAirspaceName(space, event.clientX, event.clientY, true);
      else hideAirspaceName();
    });
  }

  function drawTrack() {
    var t = scene.track;
    var n = t.lon.length;
    var pts = new Array(n);
    for (var i = 0; i < n; i++) {
      var m = toMetres(t.lon[i], t.lat[i]);
      pts[i] = project(m[0], m[1], t.alt[i]);
    }
    // Shadow drawn on the ground surface itself, so it stays under the track at every
    // angle instead of sliding about on a flat plane.
    ctx.strokeStyle = 'rgba(20,24,28,0.34)';
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    for (var j = 0; j < n; j++) {
      var mg = toMetres(t.lon[j], t.lat[j]);
      var g = project(mg[0], mg[1], groundAt(t.lon[j], t.lat[j]));
      if (j === 0) ctx.moveTo(g[0], g[1]); else ctx.lineTo(g[0], g[1]);
    }
    ctx.stroke();

    ctx.lineWidth = 2.6;
    ctx.lineCap = 'round';
    for (var k = 1; k < n; k++) {
      var col = scene.palette[t.c[k]];
      ctx.strokeStyle = 'rgb(' + col[0] + ',' + col[1] + ',' + col[2] + ')';
      ctx.beginPath();
      ctx.moveTo(pts[k - 1][0], pts[k - 1][1]);
      ctx.lineTo(pts[k][0], pts[k][1]);
      ctx.stroke();
    }

    scene.climbs.forEach(function (climb) {
      var m = toMetres(climb.lon, climb.lat);
      var p = project(m[0], m[1], climb.alt);
      ctx.beginPath();
      ctx.arc(p[0], p[1], 8.5, 0, Math.PI * 2);
      ctx.fillStyle = climb.tow ? 'rgba(27,175,122,0.92)' : 'rgba(235,104,52,0.92)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.85)';
      ctx.lineWidth = 1.4;
      ctx.stroke();
      ctx.fillStyle = '#fff';
      ctx.font = '600 11px ui-sans-serif, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(climb.label, p[0], p[1] + 0.5);
    });
  }

  // What each climb and glide was worth, drawn on the phase itself.
  //
  // Off by default, and two toggles rather than one, because the two answer different
  // questions: climbs label where the day's lift was, glides label whether the lines
  // between it paid. Both at once on a long flight is more ink than terrain, which is why
  // neither is on to begin with.
  //
  // A chord from the first fix of the phase to the last, not the flown track — the track
  // is already drawn underneath in climb colour, and a second line along it would say
  // nothing. The chord is the phase's *extent*, which is the thing a label needs to sit
  // on. Labels are pinned to the midpoint of the chord and drawn with a halo rather than
  // a filled box: over satellite imagery a box is a hole in the map, and there may be
  // twenty of them.
  var showPhase = { climb: false, glide: false };
  function drawPhaseLabels() {
    var phases = scene.phases || [];
    if (!phases.length || (!showPhase.climb && !showPhase.glide)) return;
    ctx.save();
    ctx.font = '600 11px ui-sans-serif, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineCap = 'round';
    phases.forEach(function (phase) {
      if (!showPhase[phase.kind]) return;
      var a = toMetres(phase.lon[0], phase.lat[0]);
      var b = toMetres(phase.lon[1], phase.lat[1]);
      var p = project(a[0], a[1], phase.alt[0]);
      var q = project(b[0], b[1], phase.alt[1]);
      var colour = phase.kind === 'climb' ? 'rgba(235,104,52,0.95)'
                                          : 'rgba(42,120,214,0.95)';
      ctx.strokeStyle = colour;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(p[0], p[1]);
      ctx.lineTo(q[0], q[1]);
      ctx.stroke();
      // End caps, so a short climb still reads as a span rather than a dot.
      [p, q].forEach(function (end) {
        ctx.beginPath();
        ctx.arc(end[0], end[1], 2.6, 0, Math.PI * 2);
        ctx.fillStyle = colour;
        ctx.fill();
      });
      var mx = (p[0] + q[0]) / 2, my = (p[1] + q[1]) / 2;
      ctx.lineWidth = 3;
      ctx.strokeStyle = 'rgba(0,0,0,0.55)';
      ctx.strokeText(phase.text, mx, my - 9);
      ctx.fillStyle = '#fff';
      ctx.fillText(phase.text, mx, my - 9);
    });
    ctx.restore();
  }

  var cursorIndex = null;
  function drawCursor() {
    if (cursorIndex === null || !cursorTrack) return;
    var i = Math.min(cursorIndex, cursorTrack.lon.length - 1);
    var m = toMetres(cursorTrack.lon[i], cursorTrack.lat[i]);
    var p = project(m[0], m[1], cursorTrack.alt[i]);
    var g = project(m[0], m[1], groundAt(cursorTrack.lon[i], cursorTrack.lat[i]));
    ctx.strokeStyle = 'rgba(255,255,255,0.7)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(p[0], p[1]);
    ctx.lineTo(g[0], g[1]);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(p[0], p[1], 5.5, 0, Math.PI * 2);
    ctx.fillStyle = '#fff';
    ctx.fill();
    ctx.strokeStyle = '#14171c';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // The sun and the wind, as arrows that turn with the view.
  //
  // Both are geographic bearings, so both have to be drawn in the scene's own frame:
  // `view.yaw` rotates the world counter-clockwise on screen, and screen y grows
  // downward, which together turn a compass bearing b into the screen angle below. Get
  // that wrong and the arrow points somewhere plausible at yaw 0 and lies at every other
  // heading — the failure that is invisible until you rotate the view.
  //
  // Shading already says where the light is, but only to someone who can read a
  // hillshade; an arrow says it outright, and the wind has no shading to say it at all.
  function bearingToScreen(bearing) {
    return (bearing - view.yaw * 180 / Math.PI - 90) * Math.PI / 180;
  }

  function drawArrow(cx, cy, angle, length, head, colour, width) {
    var tx = cx + Math.cos(angle) * length, ty = cy + Math.sin(angle) * length;
    ctx.strokeStyle = colour;
    ctx.fillStyle = colour;
    ctx.lineWidth = width;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(cx - Math.cos(angle) * length, cy - Math.sin(angle) * length);
    ctx.lineTo(tx, ty);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - Math.cos(angle - 0.42) * head, ty - Math.sin(angle - 0.42) * head);
    ctx.lineTo(tx - Math.cos(angle + 0.42) * head, ty - Math.sin(angle + 0.42) * head);
    ctx.closePath();
    ctx.fill();
  }

  // The numbers the rose is drawn from, exposed so a test can hold the wind arrow
  // against the convention it inverts: `from` is where the wind comes from, and drawing
  // along it rather than opposite it is the classic 180° error, invisible on any single
  // screenshot because a wrong arrow is still an arrow.
  function roseAngles() {
    var wind = scene.wind || null;
    var sunNow = sunTrack ? sunAt(sunMinute) : null;
    return {
      north: bearingToScreen(0),
      sun: sunNow ? { az: sunNow.az, el: sunNow.el, screen: bearingToScreen(sunNow.az),
                      minute: sunMinute } : null,
      wind: wind ? { from: wind.from, ms: wind.ms,
                     screen: bearingToScreen(wind.from + 180) } : null
    };
  }

  function drawRose() {
    var wind = scene.wind || null;
    var sunNow = sunTrack ? sunAt(sunMinute) : null;
    if (!wind && !sunNow) return;
    // Top right. `render_map.py` already puts navigation top-right by MapLibre's own
    // default, and two viewers of the same flights should not disagree about where north
    // lives. The credit moved to the top left to make room; the controls keep the bottom.
    // Scaled off the backing store so it is the same size on a phone, in the panel and
    // full screen, where W changes by a factor of three.
    var scale = Math.max(0.75, Math.min(1.6, W / 1280));
    var radius = 30 * scale;
    var lines = [];
    if (sunNow) {
      lines.push('Sun ' + clock(sunMinute) + ' \\u00b7 ' +
                 (sunNow.el > 0 ? Math.round(sunNow.el) + '\\u00b0 ' + compass(sunNow.az)
                                : 'below the horizon'));
    }
    if (wind) lines.push('Wind ' + wind.ms.toFixed(1) + ' m/s from ' + wind.cardinal);
    // The labels go under the rose, so the *block* has to fit — placing the circle first
    // and the text afterwards clipped the second line off the bottom of a 21:9 panel.
    var lineHeight = 13 * scale;
    var textBlock = lines.length * lineHeight;
    var cx = W - (16 * scale + radius);
    var cy = 14 * scale + radius;

    ctx.save();
    ctx.font = (11 * scale).toFixed(0) + 'px ui-sans-serif, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(16,19,24,0.55)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.28)';
    ctx.lineWidth = 1 * scale;
    ctx.stroke();

    // North, so the two arrows can be read as bearings rather than as decoration.
    var north = bearingToScreen(0);
    ctx.fillStyle = 'rgba(255,255,255,0.75)';
    ctx.fillText('N', cx + Math.cos(north) * (radius - 8 * scale),
                 cy + Math.sin(north) * (radius - 8 * scale));

    if (wind) {
      // `wind.from` is where the wind blows *from* — the convention every forecast and
      // every pilot uses — so the arrow, which shows where the air is going, points the
      // opposite way. Drawing it along the reported bearing is the classic 180° error.
      drawArrow(cx, cy, bearingToScreen(wind.from + 180), radius - 11 * scale,
                7 * scale, 'rgba(120,190,255,0.95)', 2.2 * scale);
    }
    if (sunNow) {
      // The sun sits at its bearing, out at the rim, and dims when it is below the
      // horizon — where the shading is holding the light artificially at 3° and the
      // reader is entitled to know.
      var at = bearingToScreen(sunNow.az);
      var up = sunNow.el > 0;
      var sx = cx + Math.cos(at) * (radius - 9 * scale);
      var sy = cy + Math.sin(at) * (radius - 9 * scale);
      ctx.beginPath();
      ctx.arc(sx, sy, 5.5 * scale, 0, Math.PI * 2);
      ctx.fillStyle = up ? 'rgba(255,205,80,0.98)' : 'rgba(255,205,80,0.32)';
      ctx.fill();
      // Rays towards the middle: the direction the light actually travels, which is what
      // the hillshade is doing.
      ctx.strokeStyle = ctx.fillStyle;
      ctx.lineWidth = 1.6 * scale;
      ctx.beginPath();
      ctx.moveTo(sx - Math.cos(at) * 8 * scale, sy - Math.sin(at) * 8 * scale);
      ctx.lineTo(sx - Math.cos(at) * 15 * scale, sy - Math.sin(at) * 15 * scale);
      ctx.stroke();
    }

    // Drawn with a dark stroke behind the fill rather than a box: the rose sits over
    // whatever the terrain happens to be, and white text alone disappears against a
    // limestone face or a snowfield.
    // Right-aligned to the canvas edge, not left-aligned from the circle. With the rose
    // in the top *left* the labels could run rightwards into open canvas; against the
    // right edge the same code ran them off it, and "Wind 1.7 m/s from WSW" lost its last
    // two words. The anchor has to follow the corner the rose moved to.
    ctx.textAlign = 'right';
    ctx.lineJoin = 'round';
    ctx.lineWidth = 3 * scale;
    ctx.strokeStyle = 'rgba(12,14,18,0.85)';
    ctx.fillStyle = 'rgba(255,255,255,0.95)';
    lines.forEach(function (line, i) {
      var y = cy + radius + (10 + i * 13) * scale;
      ctx.strokeText(line, cx + radius, y);
      ctx.fillText(line, cx + radius, y);
    });
    ctx.restore();
  }

  function paint() {
    // Match the backing store to the box on every frame. Relying on a ResizeObserver
    // or a post-toggle callback to do this was fragile: entering the maximised state
    // changed the box, the observer's timing did not line up with it, and the canvas
    // kept its old height while its CSS box was already full screen.
    resize();
    ctx.clearRect(0, 0, W, H);
    refit();
    var mapped = view.map && basemap && (basemap.width || basemap.naturalWidth) > 0;
    // With a backend mounted this canvas keeps only the track, the climb markers and the
    // cursor — a few thousand points and some text, which 2D draws well and which is
    // already wired to the charts. The heightfield goes underneath it in GL.
    if (renderer) renderer.terrain(mapped); else drawTerrain(mapped);
    // Under the track: where a report carries both, the flight is the subject and the
    // airspace is the context it happened in.
    drawAirspaces();
    drawTrack();
    // After the track and before the cursor: the labels annotate the track, and the
    // cursor is the one thing that must never be written over.
    drawPhaseLabels();
    drawCursor();
    drawRose();
  }

  var pending = false;
  function draw() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; paint(); });
  }

  // Input model borrowed from Google Earth, because that is what pilots already know:
  //   left-drag            pan
  //   right-drag, or ctrl/shift/alt + left-drag, or middle-drag   rotate and tilt
  //   wheel                zoom towards the pointer
  //   one finger           pan
  //   two fingers          pinch to zoom, twist to rotate
  var pointers = new Map();
  var gesture = null;   // 'pan' | 'orbit'
  var pinch = null;
  // Accumulated since the second finger went down, and which of rotate/tilt has won.
  var twistTotal = 0, tiltTotal = 0, twoFingerMode = null;
  var orbitAnchor = null;   // the ground point a rotate-drag grabbed
  var tiltAnchor = null;
  var undoPanX = 0, undoPanY = 0;
  var TWIST_DEADZONE = 0.10;   // radians, about 6 degrees
  var TILT_DEADZONE = 13;      // CSS pixels of two-finger travel

  function points() { return Array.from(pointers.values()); }

  // Signed shortest angle from a to b, so a twist through the ±pi seam does not jump.
  function angleDelta(a, b) {
    var d = b - a;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    return d;
  }

  function twoFingerState() {
    var p = points();
    return {
      distance: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y),
      angle: Math.atan2(p[1].y - p[0].y, p[1].x - p[0].x),
      cx: (p[0].x + p[1].x) / 2,
      cy: (p[0].y + p[1].y) / 2
    };
  }

  function orbitModifier(event) {
    return event.button === 2 || event.button === 1 ||
           event.ctrlKey || event.shiftKey || event.altKey || event.metaKey;
  }

  // Where a screen point lands on the ground plane, and the inverse.
  //
  // Rotating and tilting have to happen *about the fingers*, not about the middle of the
  // flight. The fit recentres the scene every frame, so changing yaw or pitch on its own
  // swings the whole view around the scene's centre — which is what "twist is centred on
  // the wrong position" and "the centre shifts at higher angles" both are. Anchoring needs
  // a fixed world point, and the ground plane gives an exact one: at z = dem.min the
  // height term drops out of the projection and it inverts in closed form.
  // The point on the **terrain** under a screen position — not the point on the flat
  // datum plane beneath it, which is what this used to answer.
  //
  // `world()` measures height from `dem.min`, so inverting with `wz = 0` solves the
  // datum plane. Over a country that is close enough: the airspace map's relief is
  // 1.4 km across 500 km of extent, a couple of pixels. Over a flight it is not. On an
  // alpine day the ground under the cursor stands 2–3 km above `dem.min`, and the datum
  // point at the same screen position lies kilometres further north — so a rotation
  // that "holds the point you grabbed" was holding somewhere off the side of the
  // mountain, and the view swung. That is "rotate is off in flights", and why the
  // airspace map felt fine.
  //
  // Solved by iteration, because the height depends on the position and the position on
  // the height. Three passes: the datum guess, then the terrain height there, then the
  // corrected position. It converges on anything that is not a cliff face — each pass
  // moves the answer by the *slope* times the previous error — and on a cliff the
  // remaining error is smaller than the one it started with, which is the point.
  function groundUnder(clientX, clientY) {
    var box = canvas.getBoundingClientRect();
    return groundAtCanvas((clientX - box.left) / box.width * W,
                          (clientY - box.top) / box.height * H);
  }


  // Move the pan so that `point` (a ground-plane position from groundAt) projects back to
  // the same place on screen. Called after yaw or pitch has changed.
  // The point a turn pivots on, with the lever arm bounded.
  //
  // Orbiting about the grabbed point is direct manipulation and right in the middle of
  // the canvas. Near an edge it is violent: the turn swings everything else by the lever
  // arm times the angle, so an 8 degree drag grabbed 8 km off centre sweeps the middle of
  // the picture clean off the screen. Measured as what the reader is actually watching —
  // how far the ground in the *middle* of the picture slides during a 30 px rotate:
  // 2 px grabbed centrally, and **45 to 88 px grabbed near an edge**, so the subject
  // moves three times as far as the finger and leaves the screen. That is the map
  // "jumping away", which is what it was reported as.
  //
  // So the *screen position* of the pivot is clamped into the middle of the canvas
  // before the ground under it is taken. It is continuous — a grab inside the box is
  // untouched, and one outside pivots about the nearest point on its edge — so there is
  // no threshold to feel, and a central grab still behaves exactly as it did. At 0.25
  // those same measurements are 2 px central and 21 to 50 px at the edges, with the
  // central *half* of the canvas untouched. What is left is inherent: a turn about a
  // point the reader chose out there has a lever arm, and honouring the grab is the
  // whole reason for orbiting about it rather than about the middle.
  var ANCHOR_INSET = 0.25;   // of the canvas, kept clear on each side
  function pickAnchor(clientX, clientY) {
    var r = canvas.getBoundingClientRect();
    var x = Math.min(Math.max(clientX, r.left + r.width * ANCHOR_INSET),
                     r.left + r.width * (1 - ANCHOR_INSET));
    var y = Math.min(Math.max(clientY, r.top + r.height * ANCHOR_INSET),
                     r.top + r.height * (1 - ANCHOR_INSET));
    return { x: x, y: y, point: groundUnder(x, y) };
  }

  function holdGround(point, clientX, clientY) {
    if (!point) return;
    var box = canvas.getBoundingClientRect();
    refit();
    // At its own height. `groundUnder` returns one now, and re-projecting on the datum
    // instead is the same error the inversion used to make, applied in the other
    // direction: the anchor would sit below the ground it was taken from and the view
    // would climb as it turned.
    var now = project(point[0], point[1],
                      point.length > 2 ? point[2] : dem.min);
    var sx = (clientX - box.left) / box.width * W;
    var sy = (clientY - box.top) / box.height * H;
    view.panX += sx - now[0];
    view.panY += sy - now[1];
  }

  // How far in the view may go: until about 1.5 km of ground fills it, and never less
  // than the 40 it always allowed. A fixed 40 was a limit on *magnification*, which is
  // the wrong unit — over one flight's box it reached 2.5 km across, and over the
  // planner's Alps it stopped at 27 km, where the place names printed on the imagery are
  // still too small to read and a turnpoint cannot be put on a particular hill.
  var CLOSEST_SPAN_M = 1500;
  function maxZoom() {
    return Math.max(40, (dem.east - dem.west) * mPerDegLon / CLOSEST_SPAN_M);
  }

  // Keep the point under the cursor fixed while zooming, the way every map does.
  function zoomAt(factor, clientX, clientY) {
    var box = canvas.getBoundingClientRect();
    // Measured from the fit's anchor, because a point's screen position is
    // anchor + world*scale*zoom + pan. Measuring from the canvas corner instead drops
    // the anchor term and biases every zoom by anchor*(ratio-1) — which read as the view
    // diving towards the bottom-right on both wheel and pinch.
    var sx = (clientX - box.left) / box.width * W - anchorX();
    var sy = (clientY - box.top) / box.height * H - anchorY();
    // Remembered, so the ground here is the ground that stays put when a finer terrain
    // patch lands — see setTerrainDetail.
    lastFocus = [(clientX - box.left) / box.width * W, (clientY - box.top) / box.height * H];
    var before = view.zoom;
    // 12 was the ceiling and it is not enough: on a cross-country box it stops at about
    // 2 km across the canvas, which is still too far out to see which side of a spine a
    // climb was worked on. The imagery goes soft well before 40 — the stitch is ~20 m a
    // pixel — but a soft picture the reader chose to look at closely is better than a
    // sharp one that refuses to. The floor comes down to 0.2 for the same reason in the
    // other direction: tilting no longer re-fits the scale, so a top-down view of a long
    // flight needs room to pull back.
    view.zoom = Math.max(0.2, Math.min(maxZoom(), view.zoom * factor));
    var ratio = view.zoom / before;
    view.panX = sx - (sx - view.panX) * ratio;
    view.panY = sy - (sy - view.panY) * ratio;
  }

  canvas.addEventListener('contextmenu', function (event) { event.preventDefault(); });

  canvas.addEventListener('pointerdown', function (event) {
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 2) {
      gesture = 'pinch';
      pinch = twoFingerState();
      twistTotal = 0;
      tiltTotal = 0;
      twoFingerMode = null;
      tiltAnchor = null;
      undoPanX = 0;
      undoPanY = 0;
    } else if (pointers.size === 1) {
      gesture = orbitModifier(event) ? 'orbit' : 'pan';
      // The point the drag grabbed, captured once. See the orbit branch below for why
      // it cannot be re-picked as the cursor travels.
      orbitAnchor = gesture === 'orbit'
        ? pickAnchor(event.clientX, event.clientY)
        : null;
    }
    canvas.classList.add('is-dragging');
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener('pointermove', function (event) {
    var previous = pointers.get(event.pointerId);
    if (!previous) return;
    moving();
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    var box = canvas.getBoundingClientRect();
    var toCanvas = W / box.width;   // CSS pixels to canvas units

    if (pointers.size >= 2) {
      var now = twoFingerState();
      if (pinch) {
        // Pan by the centroid's movement first, then scale about where the fingers are
        // now. Doing it the other way round makes the view slide out from under the
        // fingers — zoomAt already moves the pan to anchor the point, and adding the
        // centroid delta afterwards double-counts it.
        //
        // Not while tilting, though: there the vertical travel *is* the gesture, so panning
        // with it drags the ground out from under the anchor by exactly the distance the
        // fingers moved. Measured as a 30 px drift on a 30 px drag before this exception.
        if (twoFingerMode !== 'tilt') {
          var stepX = (now.cx - pinch.cx) * toCanvas;
          var stepY = (now.cy - pinch.cy) * toCanvas;
          view.panX += stepX;
          view.panY += stepY;
          // Remembered only until the gesture is classified: if it turns out to be a tilt,
          // the pan spent crossing the deadzone has to come back, or the view has already
          // slid by the width of the deadzone before tilting starts.
          if (!twoFingerMode) { undoPanX += stepX; undoPanY += stepY; }
        }
        if (pinch.distance > 4 && now.distance > 4) {
          zoomAt(now.distance / pinch.distance, now.cx, now.cy);
        }

        // Twist to rotate, drag the pair up or down to tilt. Both sit behind a deadzone
        // that has to be broken before either engages — without it, twist-to-rotate spun
        // the camera on every imprecise pinch, which is why it was removed the first time.
        //
        // Whichever gesture is further through *its own* threshold wins, rather than
        // rotate being tested first: tilt was hard to trigger because a twist of half a
        // degree claimed the gesture before 26 px of travel could accumulate.
        twistTotal += angleDelta(pinch.angle, now.angle);
        tiltTotal += (now.cy - pinch.cy);
        if (!twoFingerMode) {
          var rotateProgress = Math.abs(twistTotal) / TWIST_DEADZONE;
          var tiltProgress = Math.abs(tiltTotal) / TILT_DEADZONE;
          if (rotateProgress >= 1 || tiltProgress >= 1) {
            twoFingerMode = rotateProgress >= tiltProgress ? 'rotate' : 'tilt';
            if (twoFingerMode === 'tilt') {
              view.panX -= undoPanX;
              view.panY -= undoPanY;
            }
            undoPanX = 0;
            undoPanY = 0;
          }
        }
        if (twoFingerMode === 'rotate') {
          // Rotate about the point between the fingers, which may drift with them.
          //
          // Minus, not plus. The finger angle is measured with atan2 in client
          // coordinates, where y grows *downward*, so a twist the reader sees as
          // clockwise comes out as a positive delta — while a positive `view.yaw`
          // turns the scene counter-clockwise on screen. Adding the two put the
          // ground under the fingers and then span it the other way, which is the
          // one thing a direct-manipulation gesture must never do. Measured rather
          // than reasoned: see the twist test in tests/test_view3d_gl.py.
          var hold = groundUnder(now.cx, now.cy);
          view.yaw -= angleDelta(pinch.angle, now.angle);
          holdGround(hold, now.cx, now.cy);
        } else if (twoFingerMode === 'tilt') {
          // Tilt about a *fixed* screen point, taken where the gesture began: the fingers
          // are travelling, so following them would be the pan this deliberately skips.
          if (!tiltAnchor) {
            tiltAnchor = { x: now.cx, y: now.cy, point: groundUnder(now.cx, now.cy) };
          }
          view.pitch = Math.max(0.18, Math.min(1.45,
            view.pitch + (now.cy - pinch.cy) * 0.005));
          holdGround(tiltAnchor.point, tiltAnchor.x, tiltAnchor.y);
        }
      }
      pinch = now;
      draw();
      return;
    }

    // Two units, on purpose. A pan moves the scene *in the canvas*, so it converts to
    // canvas pixels; a rotation is a statement about how far the hand travelled, so it
    // stays in CSS pixels. Rotating with the converted delta ties the gesture to the
    // backing store: measured on the same 90 px drag, a device pixel ratio of 2 gave
    // 0.900 rad of yaw against 0.450 at ratio 1 — the same movement turning the view
    // twice as far on a retina screen as on the machine it was tuned on.
    var cssX = event.clientX - previous.x;
    var cssY = event.clientY - previous.y;
    var dx = cssX * toCanvas;
    var dy = cssY * toCanvas;
    if (gesture === 'orbit') {
      // Orbit about the point the drag *grabbed*, held where it was grabbed — not about
      // whatever is under the cursor now.
      //
      // Re-picking the anchor each event looks equivalent and is not: the cursor has
      // travelled since the last one, so each event pins a different ground point, and
      // the centre of rotation creeps across the terrain with the mouse. Measured on a
      // 90 px drag, the point the drag started on slid 29 px at a device pixel ratio of
      // 1 and 92 px at 2 — which reads as the view swinging about somewhere off to the
      // side, and reads worst full screen, where the canvas is large enough to drag a
      // long way. This is the same reason the two-finger tilt captures `tiltAnchor` once.
      if (!orbitAnchor) orbitAnchor = pickAnchor(event.clientX, event.clientY);
      view.yaw += cssX * 0.005;
      view.pitch = Math.max(0.18, Math.min(1.45, view.pitch - cssY * 0.004));
      holdGround(orbitAnchor.point, orbitAnchor.x, orbitAnchor.y);
    } else {
      view.panX += dx;
      view.panY += dy;
    }
    draw();
  });

  function endPointer(event) {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) { pinch = null; twoFingerMode = null; tiltAnchor = null; }
    if (!pointers.size) {
      gesture = null;
      orbitAnchor = null;
      canvas.classList.remove('is-dragging');
    }
  }
  canvas.addEventListener('pointerup', endPointer);
  canvas.addEventListener('pointercancel', endPointer);
  canvas.addEventListener('pointerleave', endPointer);

  canvas.addEventListener('wheel', function (event) {
    event.preventDefault();
    moving();
    zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX, event.clientY);
    draw();
  }, { passive: false });

  // Where a zoom with no pointer behind it should anchor: the point the scene is fitted
  // around, **not** the middle of the canvas.
  //
  // `refit` centres the scene on (W/2, 0.58H) — the sky above a flight is bigger than the
  // ground below it — and the buttons zoomed about (W/2, H/2) instead. Everything except
  // that one pixel row then slid on every press: measured at 13 px down per zoom-in on a
  // 549 px canvas, in the same direction every time, so five presses walked what you were
  // looking at 60 px down the panel. That is "the zoom drifts", and it accumulates, which
  // is why it reads as a fault rather than as a choice. Anchoring on the fit makes a
  // button press a pure magnification: nothing translates.
  function box() {
    var r = canvas.getBoundingClientRect();
    return {
      cx: r.left + anchorX() / W * r.width,
      cy: r.top + anchorY() / H * r.height
    };
  }

  // ---- the sun ---------------------------------------------------------------------
  //
  // The payload carries the whole day sampled every ten minutes rather than the
  // algorithm, so there is no second implementation of solar position to drift out of
  // step with `sun.py`. Interpolation between samples is linear and the azimuth arrives
  // unwrapped, so the light never sweeps the long way round the compass.
  //
  // There is no time control. The sun follows the **chart cursor**: hovering the
  // altitude trace at 14:40 lights the terrain as it was at 14:40, which is the question
  // a pilot is actually asking — was that face still in the sun when I got there. A
  // slider was the first attempt and it was the wrong instrument twice over: it offered
  // hours the flight never saw, and it made the reader hunt for a moment the charts were
  // already pointing at.
  var sunTrack = scene.sun || null;
  var sunMinute = sunTrack ? sunTrack.at : null;
  // The sun the shading was last built for. Re-lighting costs a pass over the grid, a
  // re-bake of the draped texture and a rebuild of the vertex colours, which is far too
  // much to do on every mousemove — so it only happens once the sun has actually moved
  // enough to see. A degree of azimuth is about a third of the width of the sun's own
  // disc on screen and four minutes of a summer afternoon.
  var appliedSun = null;
  var SUN_STEP_DEG = 1.0;

  function sunAt(minute) {
    var track = sunTrack.track;
    var span = track.az.length * track.step;
    var at = ((minute % span) + span) % span / track.step;
    var i = Math.floor(at), f = at - i;
    var j = (i + 1) % track.az.length;
    // The wrap at midnight is the one place the unwrapped azimuth has a real step in it;
    // ignore the fraction there rather than interpolate across a day boundary.
    if (j === 0) return { az: track.az[i], el: track.el[i] };
    return { az: track.az[i] + (track.az[j] - track.az[i]) * f,
             el: track.el[i] + (track.el[j] - track.el[i]) * f };
  }

  function clock(minute) {
    var local = ((Math.round(minute) + sunTrack.offset) % 1440 + 1440) % 1440;
    return String(Math.floor(local / 60)).padStart(2, '0') + ':' +
           String(local % 60).padStart(2, '0');
  }

  function compass(azimuth) {
    var names = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    return names[Math.round((((azimuth % 360) + 360) % 360) / 22.5) % 16];
  }

  // Rebuild the shading for wherever the sun is now. Everything that carries light has to
  // be redone: the lit range is measured against the light, the draped texture has the
  // hillshade baked into it, and the WebGL backend keeps its bare-relief shading in
  // vertex colours.
  function relight() {
    if (!sunTrack) return;
    var where = sunAt(sunMinute);
    appliedSun = where;
    setLight(where.az, where.el);
    measureLit();
    reshadeImagery();
    if (renderer && renderer.relight) renderer.relight();
    sampleCellColours();
    draw();
  }

  // Move the sun to `minute`, re-lighting only when it has travelled far enough to be
  // worth the work. The arrow still reads the exact position, so it follows the cursor
  // smoothly while the shading catches up in steps nobody can see.
  function sunTo(minute) {
    if (!sunTrack || minute === null || minute === undefined) return;
    sunMinute = minute;
    var where = sunAt(minute);
    if (appliedSun) {
      var turned = Math.abs(((where.az - appliedSun.az + 540) % 360) - 180);
      if (turned < SUN_STEP_DEG && Math.abs(where.el - appliedSun.el) < SUN_STEP_DEG / 2) {
        draw();
        return;
      }
    }
    relight();
  }

  // The UTC minute a cursor sample sits at. The cursor track carries it per sample
  // rather than being interpolated from the flight's span: fixes are not evenly spaced
  // in time, and a KMZ from a scoring site is not evenly spaced at all.
  function cursorMinute(index) {
    if (!sunTrack || !cursorTrack || !cursorTrack.min) return null;
    if (index === null || index === undefined) return null;
    return cursorTrack.min[Math.min(index, cursorTrack.min.length - 1)];
  }

  if (sunTrack && sunTrack.track && sunTrack.track.az) relight();

  // One code path for the buttons and the keyboard. Binding keys to *act names* rather
  // than to camera fields is what keeps a held arrow anchored exactly as a held button is
  // — through `holdGround` — instead of drifting, and it means a new control cannot
  // acquire behaviour the keyboard does not have.
  function runAct(act, options) {
    options = options || {};
    moving();
    var centre = box();
    var buttonHold = ('rotate-left rotate-right tilt-up tilt-down'.indexOf(act) >= 0)
      ? groundUnder(centre.cx, centre.cy) : null;
    // The map turns the way the key points: `rotate-left` swings the ground — and the
    // compass rose with it — anticlockwise, which is `yaw` *increasing*. Reading the sign
    // off the orbit drag gets this backwards, and did: a drag is direct manipulation of a
    // grabbed point, so pushing left spins the world clockwise, exactly as the twist
    // gesture is deliberately opposite to the drag. A key grabs nothing, so it follows the
    // map, not the hand.
    if (act === 'rotate-left') view.yaw += 0.35;
    else if (act === 'rotate-right') view.yaw -= 0.35;
    else if (act === 'tilt-up') view.pitch = Math.min(1.45, view.pitch + 0.15);
    else if (act === 'tilt-down') view.pitch = Math.max(0.18, view.pitch - 0.15);
    if (buttonHold) holdGround(buttonHold, centre.cx, centre.cy);
    else if (act === 'pan-left') view.panX += 40;
    else if (act === 'pan-right') view.panX -= 40;
    else if (act === 'pan-up') view.panY += 40;
    else if (act === 'pan-down') view.panY -= 40;
    else if (act === 'fullscreen') {
      toggleMaximise();
      return;   // the resize path redraws once the box has its new size
    }
    else if (act === 'zoom-in') zoomAt(1.25, box().cx, box().cy);
    else if (act === 'zoom-out') zoomAt(1 / 1.25, box().cx, box().cy);
    else if (act === 'exaggerate-set') {
      // True scale is the default because it is the only setting you can read height
      // above ground from. But a 90 km flight through 2 km of air is 2 % of its own
      // width, so the multiples are here for when the shape of the climbs matters
      // more than their absolute height.
      setVertical(parseFloat(options.vertical));
    } else if (act === 'help') {
      toggleKeyHelp();
      return;
    } else if (act === 'basemap-set') {
      setBasemapStyle(options.style);
    } else if (act === 'labels-toggle') {
      var kind = options.kind;
      if (showPhase[kind] === undefined) return;
      showPhase[kind] = !showPhase[kind];
      root.querySelectorAll('[data-view3d-act="labels-toggle"]').forEach(function (button) {
        var on = !!showPhase[button.dataset.kind];
        button.classList.toggle('is-on', on);
        button.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    } else if (act === 'airspace-toggle') {
      // Only where the reader was offered the switch. Without this, `a` on the airspace
      // map — whose subject is the layer, and which has no button — would turn the whole
      // map off with nothing on screen saying it had.
      if (!scene.airspaceToggle) return;
      airspaceOn = !airspaceOn;
      if (!airspaceOn) hideAirspaceName();
      root.querySelectorAll('[data-view3d-act="airspace-toggle"]').forEach(
        function (button) {
          button.classList.toggle('is-on', airspaceOn);
          button.setAttribute('aria-pressed', airspaceOn ? 'true' : 'false');
        });
    } else if (act === 'reset') {
      view.yaw = HOME.yaw; view.pitch = HOME.pitch;
      view.zoom = 1; view.panX = 0; view.panY = 0;
      setVertical(baseVertical);
      if (order.length) setBasemapStyle(order[0]);
    }
    draw();
    // The buttons and the keyboard zoom too, and they never go through `moving()` —
    // which is where a pointer gesture schedules its detail fetch.
    scheduleDetail();
  }

  root.querySelectorAll('[data-view3d-act]').forEach(function (button) {
    button.addEventListener('click', function () {
      runAct(button.dataset.view3dAct, button.dataset);
    });
  });

  // Keyboard control of the view.
  //
  // Three traps, all of them load-bearing. The handler is bound to the **canvas**, never
  // to the document: a report holds several flights, each with its own panel, and a
  // document-level keydown would drive whichever panel the code found first — the exact
  // bug this file already carries a comment about for buttons. `preventDefault` fires
  // only for keys actually bound and only while the canvas has focus, or tilting the
  // terrain would scroll the report out from under it. And every key goes through
  // `runAct`, so a held arrow anchors through `holdGround` exactly as a held button does.
  //
  // `1 2 4` and `S M R` address a state directly, which a cycling button could never do —
  // an independent argument for the segmented controls above.
  //
  // Bare arrows pan and shift + arrows rotate, which is the way round the pointer already
  // works: a plain drag pans and a modified drag rotates. It was the other way round, so
  // holding shift changed a turn into a pan on the keyboard and a pan into a turn on the
  // mouse — the same modifier meaning opposite things on the same panel.
  var KEY_ACTS = {
    ArrowLeft: 'pan-left', ArrowRight: 'pan-right',
    ArrowUp: 'pan-up', ArrowDown: 'pan-down',
    '+': 'zoom-in', '=': 'zoom-in', '-': 'zoom-out', '_': 'zoom-out',
    f: 'fullscreen', F: 'fullscreen', '0': 'reset',
    a: 'airspace-toggle', A: 'airspace-toggle'
  };
  var SHIFT_ACTS = {
    ArrowLeft: 'rotate-left', ArrowRight: 'rotate-right',
    ArrowUp: 'tilt-up', ArrowDown: 'tilt-down'
  };
  var KEY_STYLES = { s: 'satellite', S: 'satellite', m: 'map', M: 'map',
                     r: 'off', R: 'off' };

  canvas.addEventListener('keydown', function (event) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    var key = event.key;
    if (key === '?') { toggleKeyHelp(); event.preventDefault(); return; }
    if (key === '1' || key === '2' || key === '4') {
      runAct('exaggerate-set', { vertical: key });
      event.preventDefault();
      return;
    }
    if (KEY_STYLES[key] !== undefined) {
      runAct('basemap-set', { style: KEY_STYLES[key] });
      event.preventDefault();
      return;
    }
    var act = (event.shiftKey && SHIFT_ACTS[key]) || KEY_ACTS[key];
    if (!act) return;          // an unbound key keeps its normal meaning
    runAct(act);
    event.preventDefault();
  });

  // A keyboard affordance nobody knows about is worth little, so the panel says so when
  // it takes focus and `?` opens the list.
  function toggleKeyHelp() {
    var help = root.querySelector('.view3d-keys');
    if (help) help.hidden = !help.hidden;
  }
  canvas.addEventListener('focus', function () {
    var hint = root.querySelector('.view3d-hint');
    if (hint) hint.hidden = false;
  });
  canvas.addEventListener('blur', function () {
    var hint = root.querySelector('.view3d-hint');
    if (hint) hint.hidden = true;
    var help = root.querySelector('.view3d-keys');
    if (help) help.hidden = true;
  });

  // Full screen is the real Fullscreen API, with the in-page maximise as the fallback.
  //
  // The API is what a reader means by full screen — it takes the browser chrome with it
  // and the OS knows the window is presenting — and where the report is served from a
  // host it is granted. But it fails two ways at once inside an iframe without the
  // permission: `requestFullscreen` throws synchronously without a user activation, and
  // rejects without the permission. So the fallback is not decoration, it is the path a
  // published artifact takes, and it must be exercised. Both end in the same state as far
  // as everything else here is concerned — `panelIsFull()` is the one question asked.
  function panelIsFull(panel) {
    return panel.classList.contains('is-maximised') ||
           document.fullscreenElement === panel ||
           document.webkitFullscreenElement === panel;
  }

  // Percentage height on a canvas resolves against a parent whose own height is being
  // established in the same pass, and it did not settle before the redraw — the CSS box
  // read 100 % of the viewport while the backing store kept the aspect-ratio height. An
  // explicit pixel size removes the dependency entirely.
  // Measured from the panel, never from a global. Maximised or truly full screen, the
  // panel's own box *is* the space to fill, and it is the same box the GL canvas
  // underneath gets from `inset: 0` — two measurements that cannot disagree.
  // `document.documentElement.clientWidth/clientHeight` looked equivalent and is not:
  // in quirks mode clientHeight is the height of the whole *document*, so a report five
  // screens long maximised to a 4 316 px canvas inside an 813 px panel. The report has
  // a doctype now, but a viewer that renders it another way — an iframe, an email
  // client, a page that embeds the panel in something taller — must not be able to do
  // that again.
  function applyMaximisedSize() {
    var panel = canvas.closest('.view3d-panel');
    if (panelIsFull(panel)) {
      // clientWidth/clientHeight, not getBoundingClientRect: the panel keeps a 1 px
      // border top and bottom, and `inset: 0` on the GL canvas resolves against the
      // padding box. This is the same box, to the pixel.
      canvas.style.width = panel.clientWidth + 'px';
      canvas.style.height = panel.clientHeight + 'px';
    } else {
      canvas.style.width = '';
      canvas.style.height = '';
    }
  }

  // The new box is not measurable immediately, and one follow-up frame was not enough:
  // measured with __view3d.metrics(), the box read 713 px while the backing store was
  // still 508 until an explicit later redraw. A short ladder of redraws costs nothing on
  // a toggle and is not sensitive to how long layout takes. Real full screen needs it
  // more than the in-page path, not less: the box changes when the compositor says so.
  function settleSize() {
    applyMaximisedSize();
    view.panX = 0;
    view.panY = 0;
    [0, 80, 200, 500].forEach(function (delay) {
      setTimeout(function () { applyMaximisedSize(); resize(); draw(); }, delay);
    });
  }

  function maximiseInPage(panel) {
    panel.classList.add('is-maximised');
    settleSize();
  }

  function toggleMaximise() {
    var panel = canvas.closest('.view3d-panel');
    var full = document.fullscreenElement === panel ||
               document.webkitFullscreenElement === panel;
    if (full) {
      // Leaving is symmetrical, and the fullscreenchange handler does the resizing.
      (document.exitFullscreen || document.webkitExitFullscreen).call(document);
      return;
    }
    if (panel.classList.contains('is-maximised')) {
      panel.classList.remove('is-maximised');
      settleSize();
      return;
    }
    var request = panel.requestFullscreen || panel.webkitRequestFullscreen;
    if (!request) return maximiseInPage(panel);
    // Three ways this can fail and only one of them is a rejected promise: a synchronous
    // throw with no user activation, a rejection without the permission, and an older
    // implementation that returns undefined and simply does nothing. The check after a
    // tick catches the third, which no amount of promise handling would.
    try {
      var pending = request.call(panel);
      if (pending && pending.catch) pending.catch(function () { maximiseInPage(panel); });
    } catch (error) {
      return maximiseInPage(panel);
    }
    setTimeout(function () {
      if (!panelIsFull(panel)) maximiseInPage(panel);
    }, 120);
  }

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    var panel = canvas.closest('.view3d-panel');
    // Real full screen exits on Escape by itself, and taking the key from it would only
    // race the browser. This is the in-page path, which has nobody else to do it.
    if (panel.classList.contains('is-maximised')) toggleMaximise();
  });

  // Re-measure whenever the box changes: entering full screen, rotating a phone, or a
  // window drag all change it, and a stale backing store renders blurred or clipped.
  function refresh() {
    applyMaximisedSize();
    // Only the pan is reset here; the size itself is picked up by draw().
    var rect = canvas.getBoundingClientRect();
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    if (Math.round(rect.width * ratio) !== W || Math.round(rect.height * ratio) !== H) {
      view.panX = 0;
      view.panY = 0;
    }
    draw();
  }
  window.addEventListener('resize', refresh);
  // Entering or leaving real full screen is the same event either way, including the
  // browser's own Escape. `settleSize` rather than `refresh`: the screen-sized box is not
  // measurable in the frame the event arrives in, which is the whole reason for the
  // ladder. Both spellings, because Safari still fires only the prefixed one.
  ['fullscreenchange', 'webkitfullscreenchange'].forEach(function (name) {
    document.addEventListener(name, function () {
      if (canvas.closest('.view3d-panel')) settleSize();
    });
  });
  if (window.ResizeObserver) new ResizeObserver(refresh).observe(canvas);

  draw();
  var handle = {
    // The hover moves the sun as well as the marker: the reader points at a moment and
    // the ground is lit as it was then. `sunTo` decides whether that is worth a re-light
    // and draws either way, so this stays one call per hover.
    setCursor: function (index) {
      cursorIndex = index;
      var minute = cursorMinute(index);
      if (minute === null) { draw(); return; }
      sunTo(minute);
    },
    // The marker goes; the light stays where the reader last put it.
    //
    // Snapping the sun back to mid-flight on every mouse-out was a full re-light and a
    // visible colour swing across the whole terrain, fired by nothing more deliberate
    // than the pointer leaving a chart on its way somewhere else — and it undid the
    // comparison the reader had just set up, which is usually the moment they were about
    // to look at the ground for. Holding the last time costs nothing: `sunMinute` is
    // already where they left it, so this only has to stop moving it. Mid-flight remains
    // the *initial* light, for a panel nobody has hovered yet.
    clearCursor: function () {
      cursorIndex = null;
      draw();
    },
    // Exposed for tests, like `basemap()` below: whether the map is actually following
    // the charts is not readable from the DOM — the marker is drawn into the canvas —
    // and "the click did nothing" is precisely the regression worth catching.
    cursor: function () { return cursorIndex; },
    // Mark a moment *and* make sure it can be seen. Clicking a chart point that projects
    // off the edge of the panel used to mark it invisibly: the reader asked "where was
    // this on the ground" and the map did not move. The pan is nudged until the marker
    // sits inside a comfortable inset of the canvas.
    //
    // Pan only, deliberately. This projection has no behind-the-camera case, so shifting
    // always suffices to bring a point on screen, and turning the view unasked moves the
    // ground the reader was orienting against — the one thing they had just built up.
    // Answers whether it had to move, which is what a test can hold it to.
    revealCursor: function (index) {
      cursorIndex = index;
      var minute = cursorMinute(index);
      if (minute === null) draw(); else sunTo(minute);
      if (!cursorTrack || index === null || index === undefined) return false;
      var i = Math.min(index, cursorTrack.lon.length - 1);
      var m = toMetres(cursorTrack.lon[i], cursorTrack.lat[i]);
      // `project` answers in backing-store pixels, which is also what `panX`/`panY` are
      // in, so the correction is the shortfall itself with no unit conversion.
      var p = project(m[0], m[1], cursorTrack.alt[i]);
      // A pixel of slack, because `panX += (padX - p)` does not land p back on `padX`
      // exactly: floating-point addition leaves it a hair short, so a strict comparison
      // reports the point as still outside and asks for another correction every time it
      // is called. Below a pixel there is nothing to see anyway.
      var padX = W * 0.15, padY = H * 0.15, slack = 1, dx = 0, dy = 0;
      if (p[0] < padX - slack) dx = padX - p[0];
      else if (p[0] > W - padX + slack) dx = (W - padX) - p[0];
      if (p[1] < padY - slack) dy = padY - p[1];
      else if (p[1] > H - padY + slack) dy = (H - padY) - p[1];
      if (!dx && !dy) return false;
      view.panX += dx;
      view.panY += dy;
      draw();
      return true;
    },
    // Exposed for tests: driving the camera from a headless browser is the only way to
    // check that a gesture does what it claims.
    view: view,
    // Synchronous on purpose: a headless browser stops servicing requestAnimationFrame
    // once the page goes idle, so a test that scheduled a frame and then measured the
    // projection was reading numbers from before its own input. Every measurement of a
    // gesture was wrong in the same invisible way until this bypassed the scheduler.
    redraw: function () { paint(); },
    // Exposed for tests: what resize() actually measures, versus what it has stored.
    metrics: function () {
      var rect = canvas.getBoundingClientRect();
      return { W: W, H: H, boxW: rect.width, boxH: rect.height,
               ratio: Math.min(window.devicePixelRatio || 1, 2),
               attrW: canvas.width, attrH: canvas.height };
    },
    // Exposed for tests: the grid it is drawing, and the drape resolution in force. The
    // coarse-while-moving trick is a claim about frame cost, so both have to be measurable.
    grid: function () {
      var steps = texStep();
      return { cols: cols, rows: rows, interacting: interacting,
               cellCols: Math.round(cols / steps.c), cellRows: Math.round(rows / steps.r) };
    },
    setInteracting: function (on) { interacting = !!on; },
    // Exposed for tests: the ground-plane point under a screen position, and where a
    // ground point is on screen now. Rotating and tilting *about the fingers* is a claim
    // about exactly these two agreeing across a gesture.
    ground: function (clientX, clientY) { return groundUnder(clientX, clientY); },
    screenOfGround: function (point) {
      var box = canvas.getBoundingClientRect();
      var p = project(point[0], point[1], dem.min);
      return [p[0] / W * box.width, p[1] / H * box.height];
    },
    stats: function () {
      // A folded cell is an artefact of painter's order. Under a depth buffer there is
      // no such thing — the backend reports its own cell count and a folded count of
      // zero, and that difference is the whole point of it.
      return renderer ? renderer.stats() : { cells: stats.cells, folded: stats.folded };
    },
    // Exposed for tests: whether the WebGL backend took, and where it puts a world
    // point. The overlay track is drawn with project() on top of a heightfield drawn
    // from a matrix, so the two have to agree — any disagreement shows up as the track
    // floating above or sinking into the ground.
    gl: function () { return renderer ? renderer.info() : null; },
    glScreenOf: function (x, y, z) {
      return renderer ? renderer.screenOf(x, y, z) : null;
    },
    glDepthOf: function (x, y, z) {
      return renderer ? renderer.depthOf(x, y, z) : null;
    },
    // project() in canvas pixels for a world point, which is the unit glScreenOf
    // answers in. screenOf()/nearest() speak CSS pixels and track indices, so neither
    // can be held against the matrix directly.
    worldProject: function (x, y, z) { return project(x, y, z); },
    // Exposed for tests: the ground-plane point under a screen position. Every rotation
    // anchors through this, so "the twist is centred on the wrong place" is a claim
    // about it and cannot be checked without it.
    groundUnder: function (clientX, clientY) { return groundUnder(clientX, clientY); },
    // The airspace layer's two controls. The page owns the filter UI and the label —
    // this widget only knows how to draw rings and say which one a point is inside.
    setAirspaceFilter: function (fn) { airspaceFilter = fn || null; draw(); },
    scene: function () { return scene; },
    // Exposed for tests: whether the current camera would ask for a sharper mosaic and
    // for what. The fetch itself needs a network and a tile server; the decision does
    // not, and the decision is where this can be wrong.
    detailPlan: function () { return detailPlan(); },
    // Exposed for tests: what the detail imagery believes is on screen.
    visibleBox: function () { return visibleBox(); },
    detailState: function () {
      return detail ? { zoom: detail.zoom, style: detail.style, box: detail.box } : null;
    },
    // Exposed for tests: the detail terrain's plan, what is loaded, and a way to hand it
    // a patch without a tile server — the shape `loadTerrain` produces.
    terrainPlan: function () { return terrainPlan(); },
    terrainState: function () {
      return terrainDetail ? { west: terrainDetail.west, east: terrainDetail.east,
                               south: terrainDetail.south, north: terrainDetail.north,
                               rows: terrainDetail.rows, cols: terrainDetail.cols,
                               spacing: terrainDetail.spacing } : null;
    },
    setTerrainDetail: function (patch) { setTerrainDetail(patch); },
    // Exposed for tests: the draped image as the renderer receives it, shading and all.
    shadedBasemap: function () { return basemap; },
    // Exposed for tests: stand in for a stitch that cannot happen offline. Takes the
    // same shape the stitcher produces, so the renderer cannot tell the difference.
    setDetail: function (image, box, zoom) {
      detail = image ? { image: image, box: box, style: style, zoom: zoom || 99 } : null;
      draw();
    },
    // What is under this point on the map, in the coordinates a plan is written in.
    // `groundUnder` answers in the local metric frame, which is an implementation
    // detail of the projection; a turnpoint is a longitude and a latitude.
    groundLonLat: function (clientX, clientY) {
      var point = groundUnder(clientX, clientY);
      if (!point) return null;
      return [lon0 + point[0] / mPerDegLon, lat0 + point[1] / mPerDegLat];
    },
    // The terrain height under a coordinate, so a planned line can be drawn on the
    // ground rather than at an altitude nobody chose.
    groundAt: function (lon, lat) { return groundAt(lon, lat); },
    airspaceAt: function (clientX, clientY) { return airspaceAt(clientX, clientY); },
    // Exposed for tests: the sun and wind arrows as angles rather than as pixels.
    rose: function () { return roseAngles(); },
    toMetres: function (lon, lat) { return toMetres(lon, lat); },
    // Called when the flight this panel belongs to is removed from the document. The
    // DEM grid and the stitched basemap go with the handle, but a WebGL context does
    // not: a page gets about sixteen of them, so one has to be handed back explicitly.
    dispose: function () {
      if (renderer && renderer.dispose) renderer.dispose();
      renderer = null;
    },
    // Exposed for tests: the projection as it currently stands. Zoom anchoring is a
    // claim about these numbers, so the numbers have to be readable.
    projection: function () {
      return { dx: fit.dx, dy: fit.dy, scale: fit.scale, W: W, H: H, maxZoom: maxZoom(),
               anchorX: anchorX(), anchorY: anchorY(),
               panX: view.panX, panY: view.panY, zoom: view.zoom };
    },
    // Exposed for tests: the track vertex nearest a screen point, and where a given
    // vertex is on screen now. Zoom anchoring is the claim that these two agree before
    // and after a wheel event, which is only checkable by measuring it.
    nearest: function (clientX, clientY) {
      var box = canvas.getBoundingClientRect();
      var sx = (clientX - box.left) / box.width * W;
      var sy = (clientY - box.top) / box.height * H;
      var t = scene.track, best = 0, bestD = Infinity;
      for (var i = 0; i < t.lon.length; i++) {
        var m = toMetres(t.lon[i], t.lat[i]);
        var p = project(m[0], m[1], t.alt[i]);
        var d = (p[0] - sx) * (p[0] - sx) + (p[1] - sy) * (p[1] - sy);
        if (d < bestD) { bestD = d; best = i; }
      }
      return best;
    },
    screenOf: function (index) {
      var box = canvas.getBoundingClientRect();
      var t = scene.track;
      var m = toMetres(t.lon[index], t.lat[index]);
      var p = project(m[0], m[1], t.alt[index]);
      return [p[0] / W * box.width, p[1] / H * box.height];
    },
    // Exposed for tests: which basemap the reader is looking at, and whether its tiles
    // actually arrived. A style that is selected but has no image is the failure the
    // toggle must not hide.
    basemap: function () {
      return { style: style, on: view.map, loading: loading,
               painted: !!basemap, cells: !!cellColour,
               isCanvas: !!(basemap && basemap.tagName === 'CANVAS'),
               cached: Object.keys(ready),
               credit: (root.querySelector('.view3d-credit') || {}).textContent };
    }
  };
  // What the panel was built from, for a second renderer to draw the same flight with
  // (`render_map.SWITCH_SCRIPT`): one scene, one cursor track, read rather than rebuilt.
  handle.built = { scene: scene, cursorTrack: cursorTrack || null };
  window.__view3d = handle;
  // A multi-flight document initialises one of these per tab, so the bare global is
  // whichever went last. Keyed by canvas id as well, so a test can address the panel it
  // is actually clicking on — driving one panel's button while reading another's numbers
  // produced a convincing false failure.
  window.__view3dAll = window.__view3dAll || {};
  window.__view3dAll[canvas.id] = handle;
  return handle;
}
"""

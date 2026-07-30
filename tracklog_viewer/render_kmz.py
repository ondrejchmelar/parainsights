"""Google Earth output: a KMZ carrying the whole analysis.

Two lineages meet here. The *content* is igc2kmz's — colour-by-climb tracks, a shadow,
an animation, thermal and glide placemarks with statistics in the balloon, altitude and
time marks. The *geometry hygiene* is XContest's: `Region`/`Lod` detail levels, one
`LineString` per colour run instead of one per segment, coordinates at five decimals,
and time points sampled rather than emitted per fix.

The difference that matters: igc2kmz writes one Placemark per fix, which is 8.8 MB of
KML and 20 274 placemarks for a two-hour flight. Same flight through here is a fraction
of that, because a reader that has to load twenty thousand placemarks to see a track is
paying for nothing.

Nothing in the output points at the network. igc2kmz's charts were Google Image Charts
URLs and stopped resolving in 2019, so every graph in an old KMZ is a broken image;
charts here are rendered to PNG locally, and simply omitted if Pillow is unavailable.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from pathlib import Path

import numpy as np

from .analysis import Analysis, Phase, salient
from .charts import decimate

def kml_colour(rgb: str, alpha: int = 255) -> str:
    """Convert a familiar #rrggbb to KML's aabbggrr.

    Every colour in this module is written in rrggbb and converted here, because KML's
    reversed byte order is a trap: `ffeb6834` looks like the report's orange and is in
    fact blue, and the solid track drew last, so on any viewer that ignores per-folder
    visibility it painted the whole flight that colour.
    """
    rgb = rgb.lstrip("#")
    return f"{alpha:02x}{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}"


# Same breakpoints and hues as the report's diverging climb ramp, so the two views read
# as one tool. Written rrggbb; converted above.
CLIMB_BANDS = [
    (-4.0, kml_colour("17508f")),
    (-2.0, kml_colour("2a78d6")),
    (-0.7, kml_colour("8fb6e6")),
    (0.7, kml_colour("a9a49a")),
    (2.0, kml_colour("f0a07a")),
    (4.0, kml_colour("eb6834")),
    (float("inf"), kml_colour("c8431a")),
]
ALTITUDE_BANDS = 8
SPEED_BANDS = 8
TRACK_WIDTH = 3
TIME_MARK_STEP = 300  # seconds
ALTITUDE_MARK_THRESHOLD = 150.0  # metres of swing worth a label
ANIMATION_POINTS = 900
TIME_POINTS = 400

def _png(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    """Encode RGBA rows as a PNG using only the standard library.

    Written rather than embedded as base64: a hand-typed constant is unverifiable, and
    the first attempt at one was a corrupt file that Google Earth drew as a red X on
    every placemark. zlib and struct are enough, and Pillow stays optional.
    """
    height = len(pixels)
    width = len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)   # filter type 0: no filtering
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _marker_icon(rgb: str, size: int = 16) -> bytes:
    """A filled disc with a soft edge, in the given rrggbb."""
    r, g, b = (int(rgb[i:i + 2], 16) for i in (0, 2, 4))
    centre = (size - 1) / 2
    radius = size / 2 - 1
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            distance = ((x - centre) ** 2 + (y - centre) ** 2) ** 0.5
            if distance <= radius - 1:
                row.append((r, g, b, 255))
            elif distance <= radius:
                # One-pixel feather, so the disc does not look jagged when scaled.
                row.append((r, g, b, int(255 * (radius - distance))))
            else:
                row.append((0, 0, 0, 0))
        rows.append(row)
    return _png(rows)


GLIDER_ICON_PNG = _marker_icon("eb6834")
TOW_ICON_PNG = _marker_icon("1baf7a")
GLIDE_ICON_PNG = _marker_icon("2a78d6")
MARK_ICON_PNG = _marker_icon("f2f1ed")


def _escape(text) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _coords(lat, lon, alt=None, indices=None) -> str:
    """Coordinate list, lon,lat[,alt]. Five decimals is about a metre — plenty, and it
    halves the file next to the full float repr."""
    indices = range(len(lat)) if indices is None else indices
    if alt is None:
        return " ".join(f"{lon[i]:.5f},{lat[i]:.5f}" for i in indices)
    return " ".join(f"{lon[i]:.5f},{lat[i]:.5f},{alt[i]:.0f}" for i in indices)


def _band_index(value: float, bands) -> int:
    for index, (threshold, _) in enumerate(bands):
        if value < threshold:
            return index
    return len(bands) - 1


def _runs_by_band(values, bands, keep) -> list[tuple[int, list[int]]]:
    """Split the kept indices into runs of one colour band.

    One LineString per run rather than per segment: a run is usually hundreds of fixes
    long, and the placemark count is what makes a KML slow to open.
    """
    runs: list[tuple[int, list[int]]] = []
    current = None
    for index in keep:
        band = _band_index(float(values[index]), bands)
        if current is None or band != current[0]:
            if current is not None and len(current[1]) > 1:
                runs.append(current)
            # Start the next run at the previous point so the line stays unbroken.
            previous = [current[1][-1]] if current is not None else []
            current = (band, previous + [index])
        else:
            current[1].append(index)
    if current is not None and len(current[1]) > 1:
        runs.append(current)
    return runs


def _linear_bands(low: float, high: float, count: int, palette) -> list:
    """Evenly spaced bands between low and high, for altitude and speed colourings."""
    step = (high - low) / max(count, 1)
    return [(low + step * (i + 1), palette[i]) for i in range(count - 1)] + [
        (float("inf"), palette[count - 1])
    ]


# Low to high: warm ground colours through to cold heights.
ALTITUDE_PALETTE = [kml_colour(c) for c in (
    "9a3c00", "d06a00", "e0a020", "b8c840", "70d880", "40c8d0", "3080e8", "2040c0",
)]
# Slow to fast.
SPEED_PALETTE = [kml_colour(c) for c in (
    "b0b0b0", "c0d0a0", "a0d878", "60c8b0", "40a8e0", "3070ea", "2848d8", "2020b0",
)]


def _style(identifier: str, colour: str, width: int = TRACK_WIDTH) -> str:
    return (
        f'<Style id="{identifier}"><LineStyle><color>{colour}</color>'
        f"<width>{width}</width></LineStyle>"
        f"<PolyStyle><color>60{colour[2:]}</color></PolyStyle></Style>"
    )


def _region(lat, lon, alt, min_pixels: int, max_pixels: int) -> str:
    """Level-of-detail box. Google Earth then loads only the detail level that matches
    the track's size on screen — the trick that keeps XContest's KMZ small and quick."""
    return (
        "<Region><LatLonAltBox>"
        f"<north>{lat.max():.5f}</north><south>{lat.min():.5f}</south>"
        f"<east>{lon.max():.5f}</east><west>{lon.min():.5f}</west>"
        f"<minAltitude>{alt.min():.0f}</minAltitude><maxAltitude>{alt.max():.0f}</maxAltitude>"
        "<altitudeMode>absolute</altitudeMode></LatLonAltBox>"
        f"<Lod><minLodPixels>{min_pixels}</minLodPixels>"
        f"<maxLodPixels>{max_pixels}</maxLodPixels></Lod></Region>"
    )


def _coloured_folder(name: str, analysis: Analysis, values, bands, keep, *,
                     prefix: str, visible: bool) -> str:
    """One colouring of the track: a folder of per-band LineStrings."""
    flight = analysis.flight
    alt = analysis.series.alt
    placemarks = []
    for band, indices in _runs_by_band(values, bands, keep):
        placemarks.append(
            f'<Placemark><styleUrl>#{prefix}{band}</styleUrl><LineString>'
            "<extrude>0</extrude><tessellate>0</tessellate>"
            "<altitudeMode>absolute</altitudeMode>"
            f"<coordinates>{_coords(flight.lat, flight.lon, alt, indices)}</coordinates>"
            "</LineString></Placemark>"
        )
    return (
        f"<Folder><name>{_escape(name)}</name>"
        f"<visibility>{1 if visible else 0}</visibility>"
        f'<styleUrl>#hide-children</styleUrl>{"".join(placemarks)}</Folder>'
    )


def _summary_text(analysis: Analysis, route=None) -> str:
    """A plain-text summary for the Document description.

    Google Earth on mobile shows a Document's description verbatim, markup and all, so
    the HTML version goes on a placemark instead — where it is rendered everywhere.
    """
    summary = analysis.summary
    parts = [
        f"{summary.pilot or 'Unknown pilot'} · {summary.glider or 'unknown glider'}",
        f"{summary.takeoff_time}–{summary.landing_time} "
        f"({summary.duration // 3600}h{summary.duration % 3600 // 60:02d})",
        f"{summary.track_distance / 1000:.1f} km flown",
    ]
    if route:
        parts.append(f"{route.km:.1f} km XC")
    parts.append(f"{summary.min_altitude:.0f}–{summary.max_altitude:.0f} m")
    parts.append(f"{len(analysis.thermals)} climbs")
    if analysis.wind:
        parts.append(f"wind {analysis.wind.kmh:.0f} km/h from {analysis.wind.cardinal}")
    return " · ".join(parts)


def _summary_placemark(analysis: Analysis, route=None, meteo=None) -> str:
    """The full statistics table, on a placemark at the launch point."""
    flight = analysis.flight
    alt = analysis.series.alt
    return (
        "<Placemark><name>Flight summary</name><styleUrl>#summary</styleUrl>"
        f"<description>{_summary_table(analysis, route, meteo)}</description>"
        "<Point><altitudeMode>absolute</altitudeMode>"
        f"<coordinates>{flight.lon[0]:.5f},{flight.lat[0]:.5f},{alt[0]:.0f}"
        "</coordinates></Point></Placemark>"
    )


def _summary_table(analysis: Analysis, route=None, meteo=None) -> str:
    summary = analysis.summary
    rows = [
        ("Pilot", summary.pilot or "—"),
        ("Glider", summary.glider or "—"),
        ("Site", summary.site or "—"),
        ("Take-off", summary.takeoff_time),
        ("Landing", summary.landing_time),
        ("Duration", f"{summary.duration // 3600}h {summary.duration % 3600 // 60:02d}m"),
        ("Distance flown", f"{summary.track_distance / 1000:.1f} km"),
        ("Straight distance", f"{summary.straight_distance / 1000:.1f} km"),
    ]
    if route:
        rows.append(("XC free distance", f"{route.km:.1f} km via {len(route.points) - 2} TPs"))
    rows += [
        ("Maximum altitude", f"{summary.max_altitude:.0f} m"),
        ("Minimum altitude", f"{summary.min_altitude:.0f} m"),
        ("Total height gained", f"{summary.total_gain:.0f} m"),
        ("Best single climb", f"{summary.max_gain:.0f} m"),
        ("Maximum climb", f"{summary.max_climb:+.1f} m/s"),
        ("Maximum sink", f"{summary.max_sink:+.1f} m/s"),
        ("Maximum speed", f"{summary.max_speed:.0f} km/h"),
        ("Altitude source", summary.altitude_source),
    ]
    if analysis.tow:
        rows.append(("Off tow at", f"{analysis.tow.finish_altitude:.0f} m"))
    if analysis.wind:
        rows.append(("Wind", f"{analysis.wind.kmh:.0f} km/h from {analysis.wind.cardinal}"))
    if meteo:
        rows.append(("Cloudbase (model)", f"{meteo.cloudbase:.0f} m"))
        if meteo.thermal_top:
            rows.append(("Thermal top (model)", f"{meteo.thermal_top:.0f} m"))

    cells = "".join(
        f'<tr bgcolor="{"#eeeeee" if i % 2 else "#ffffff"}">'
        f'<th align="right">{_escape(key)}</th><td>{_escape(value)}</td></tr>'
        for i, (key, value) in enumerate(rows)
    )
    return (
        "<![CDATA[<table cellpadding='2' cellspacing='0'>"
        f"{cells}</table>"
        "<p><small>tracklog viewer</small></p>]]>"
    )


def _balloon_style(identifier: str, rows: list[tuple[str, str]], icon: str) -> str:
    """A BalloonStyle whose text pulls named values out of the placemark's ExtendedData."""
    cells = "".join(
        f'<tr bgcolor="{"#eeeeee" if i % 2 else "#ffffff"}">'
        f'<th align="right">{label}</th><td>$[{key}]</td></tr>'
        for i, (label, key) in enumerate(rows)
    )
    return (
        f'<Style id="{identifier}"><BalloonStyle><text><![CDATA[<h3>$[name]</h3>'
        f"<table cellpadding='2' cellspacing='0'>{cells}</table>]]></text></BalloonStyle>"
        f'<IconStyle><scale>0.9</scale><Icon><href>images/{icon}</href></Icon></IconStyle>'
        # Labels off: eleven climb names at once overlap into an unreadable mat, and the
        # name is already the balloon's heading.
        "<LabelStyle><scale>0</scale></LabelStyle></Style>"
    )


THERMAL_ROWS = [
    ("Height gained", "gain"), ("Average climb", "average_climb"),
    ("Best 20 s climb", "maximum_climb"), ("Peak climb", "peak_climb"),
    ("Efficiency", "efficiency"), ("Turns", "turns"), ("Height per turn", "per_turn"),
    ("Turn direction", "direction"), ("Seconds per turn", "circle_seconds"),
    ("Circle radius", "circle_radius"), ("Drift", "wind"),
    ("Start", "start_time"), ("Finish", "finish_time"), ("Duration", "duration"),
    ("From", "start_altitude"), ("To", "finish_altitude"),
]
GLIDE_ROWS = [
    ("Distance", "distance"), ("Glide ratio", "ld"), ("Average speed", "average_speed"),
    ("Height lost", "gain"), ("Start", "start_time"), ("Finish", "finish_time"),
    ("Duration", "duration"), ("From", "start_altitude"), ("To", "finish_altitude"),
]


def _extended_data(pairs: dict) -> str:
    return (
        "<ExtendedData>"
        + "".join(
            f'<Data name="{key}"><value>{_escape(value)}</value></Data>'
            for key, value in pairs.items()
        )
        + "</ExtendedData>"
    )


def _segment_placemark(analysis: Analysis, segment, number: int) -> str:
    flight = analysis.flight
    alt = analysis.series.alt
    middle = (segment.start + segment.stop) // 2
    minutes, seconds = divmod(segment.duration, 60)

    if segment.phase is Phase.GLIDE:
        style, rows = "#glide-balloon", GLIDE_ROWS
        name = (
            f"{segment.distance / 1000:.1f} km at "
            f"{segment.average_ld:.1f}:1, {segment.average_speed:.0f} km/h"
            if segment.average_ld
            else f"{segment.distance / 1000:.1f} km glide"
        )
        data = {
            "distance": f"{segment.distance / 1000:.1f} km",
            "ld": f"{segment.average_ld:.1f}:1" if segment.average_ld else "—",
            "average_speed": f"{segment.average_speed:.0f} km/h",
            "gain": f"{segment.altitude_change:+.0f} m",
        }
    else:
        style = "#tow-balloon" if segment.phase is Phase.TOW else "#thermal-balloon"
        rows = THERMAL_ROWS
        label = "Tow" if segment.phase is Phase.TOW else f"Climb {number}"
        name = f"{label}: {segment.altitude_change:+.0f} m at {segment.average_climb:+.2f} m/s"
        per_turn = (
            f"{segment.altitude_change / segment.turns:.0f} m"
            if segment.turns and segment.turns >= 0.5
            else "—"
        )
        data = {
            "gain": f"{segment.altitude_change:+.0f} m",
            "average_climb": f"{segment.average_climb:+.2f} m/s",
            "maximum_climb": f"{segment.maximum_climb:+.1f} m/s",
            "peak_climb": f"{segment.peak_climb:+.1f} m/s",
            "efficiency": f"{segment.efficiency:.0f}%" if segment.efficiency else "—",
            "turns": f"{segment.turns:.1f}" if segment.turns is not None else "—",
            "per_turn": per_turn,
            "direction": segment.turn_direction or "—",
            "circle_seconds": f"{segment.circle_seconds:.0f} s" if segment.circle_seconds else "—",
            "circle_radius": f"{segment.circle_radius:.0f} m" if segment.circle_radius else "—",
            "wind": (
                f"{segment.wind.kmh:.0f} km/h from {segment.wind.cardinal}"
                if segment.wind else "—"
            ),
        }

    data.update({
        "start_time": segment.start_time,
        "finish_time": segment.finish_time,
        "duration": f"{minutes}m {seconds:02d}s",
        "start_altitude": f"{segment.start_altitude:.0f} m",
        "finish_altitude": f"{segment.finish_altitude:.0f} m",
    })

    point = (
        "<Point><altitudeMode>absolute</altitudeMode>"
        f"<coordinates>{flight.lon[middle]:.5f},{flight.lat[middle]:.5f},"
        f"{alt[middle]:.0f}</coordinates></Point>"
    )
    line = (
        f'<Placemark><styleUrl>{style}-line</styleUrl><LineString>'
        "<altitudeMode>absolute</altitudeMode><coordinates>"
        f"{flight.lon[segment.start]:.5f},{flight.lat[segment.start]:.5f},"
        f"{alt[segment.start]:.0f} "
        f"{flight.lon[segment.stop - 1]:.5f},{flight.lat[segment.stop - 1]:.5f},"
        f"{alt[segment.stop - 1]:.0f}"
        "</coordinates></LineString></Placemark>"
    )
    return (
        f"<Placemark><name>{_escape(name)}</name><styleUrl>{style}</styleUrl>"
        f"{_extended_data(data)}{point}</Placemark>{line}"
    )


def _animation(analysis: Analysis) -> str:
    """Timed points so Google Earth's time slider flies the track."""
    flight = analysis.flight
    alt = analysis.series.alt
    # Ceiling, not floor: with floor, any flight shorter than ANIMATION_POINTS fixes
    # gets step 1 and one placemark per fix — precisely the behaviour this renderer
    # exists to avoid.
    step = max(-(-len(flight) // ANIMATION_POINTS), 1)
    placemarks = []
    for i in range(0, len(flight), step):
        when = flight.time[i].astype("datetime64[s]").item()
        nxt = min(i + step, len(flight) - 1)
        until = flight.time[nxt].astype("datetime64[s]").item()
        placemarks.append(
            "<Placemark><styleUrl>#glider</styleUrl>"
            f"<TimeSpan><begin>{when.isoformat()}Z</begin>"
            f"<end>{until.isoformat()}Z</end></TimeSpan>"
            "<Point><altitudeMode>absolute</altitudeMode>"
            f"<coordinates>{flight.lon[i]:.5f},{flight.lat[i]:.5f},{alt[i]:.0f}"
            "</coordinates></Point></Placemark>"
        )
    return (
        "<Folder><name>Animation</name><visibility>0</visibility>"
        f'<styleUrl>#hide-children</styleUrl>{"".join(placemarks)}</Folder>'
    )


def _time_marks(analysis: Analysis) -> str:
    flight = analysis.flight
    alt = analysis.series.alt
    t = analysis.series.t
    placemarks = []
    for mark in range(0, int(t[-1]) + 1, TIME_MARK_STEP):
        index = int(np.searchsorted(t, mark))
        if index >= len(flight):
            break
        placemarks.append(
            f"<Placemark><name>{flight.local_time(index).strftime('%H:%M')}</name>"
            "<styleUrl>#time-mark</styleUrl>"
            "<Point><altitudeMode>absolute</altitudeMode>"
            f"<coordinates>{flight.lon[index]:.5f},{flight.lat[index]:.5f},{alt[index]:.0f}"
            "</coordinates></Point></Placemark>"
        )
    return (
        "<Folder><name>Time marks</name><visibility>0</visibility>"
        f'<styleUrl>#hide-children</styleUrl>{"".join(placemarks)}</Folder>'
    )


def _altitude_marks(analysis: Analysis) -> str:
    flight = analysis.flight
    alt = analysis.series.alt
    marks = salient(alt, ALTITUDE_MARK_THRESHOLD)
    placemarks = []
    for index in marks:
        placemarks.append(
            f"<Placemark><name>{alt[index]:.0f} m</name>"
            "<styleUrl>#altitude-mark</styleUrl>"
            f"<description>{flight.local_time(index).strftime('%H:%M:%S')}</description>"
            "<Point><altitudeMode>absolute</altitudeMode>"
            f"<coordinates>{flight.lon[index]:.5f},{flight.lat[index]:.5f},{alt[index]:.0f}"
            "</coordinates></Point></Placemark>"
        )
    return (
        "<Folder><name>Altitude marks</name><visibility>0</visibility>"
        f'<styleUrl>#hide-children</styleUrl>{"".join(placemarks)}</Folder>'
    )


def _xc_folder(route) -> str:
    if route is None or len(route.points) < 2:
        return ""
    legs = []
    for index, (a, b) in enumerate(zip(route.points, route.points[1:]), start=1):
        legs.append(
            f"<Placemark><name>Leg {index}: {route.legs[index - 1] / 1000:.1f} km</name>"
            "<styleUrl>#xc-leg</styleUrl><LineString><tessellate>1</tessellate>"
            "<altitudeMode>clampToGround</altitudeMode>"
            f"<coordinates>{a.lon:.5f},{a.lat:.5f} {b.lon:.5f},{b.lat:.5f}</coordinates>"
            "</LineString></Placemark>"
        )
    for index, point in enumerate(route.points):
        label = "Start" if index == 0 else (
            "Finish" if index == len(route.points) - 1 else f"TP{index}"
        )
        legs.append(
            f"<Placemark><name>{label}</name><styleUrl>#xc-point</styleUrl>"
            "<Point><altitudeMode>clampToGround</altitudeMode>"
            f"<coordinates>{point.lon:.5f},{point.lat:.5f}</coordinates></Point></Placemark>"
        )
    return (
        f"<Folder><name>XC route — {route.km:.1f} km</name><visibility>0</visibility>"
        f'<styleUrl>#hide-children</styleUrl>{"".join(legs)}</Folder>'
    )


def _chart_overlay(png_name: str, name: str) -> str:
    return (
        f"<ScreenOverlay><name>{_escape(name)}</name><visibility>0</visibility>"
        f"<Icon><href>images/{png_name}</href></Icon>"
        '<overlayXY x="0" y="0" xunits="fraction" yunits="fraction"/>'
        '<screenXY x="12" y="12" xunits="pixels" yunits="pixels"/>'
        '<size x="0" y="0" xunits="fraction" yunits="fraction"/></ScreenOverlay>'
    )


def barogram_png(analysis: Analysis, *, width: int = 640, height: int = 260) -> bytes | None:
    """A barogram as a PNG, for the ScreenOverlay. None when Pillow is missing."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    series = analysis.series
    alt = series.alt
    t = series.t
    image = Image.new("RGBA", (width, height), (255, 255, 255, 205))
    draw = ImageDraw.Draw(image)
    left, right, top, bottom = 44, 8, 10, 22
    plot_w, plot_h = width - left - right, height - top - bottom
    floor = float(np.floor(alt.min() / 250) * 250)
    ceiling = float(np.ceil(alt.max() / 250) * 250)

    # Array-safe: these are called with the whole series to project it in one go, and
    # float() on an array raises.
    span = max(float(t[-1]), 1.0)

    def sx(value):
        return left + plot_w * np.asarray(value, dtype=float) / span

    def sy(value):
        return top + plot_h * (
            1 - (np.asarray(value, dtype=float) - floor) / max(ceiling - floor, 1)
        )

    for level in np.arange(floor, ceiling + 1, 250):
        y = float(sy(level))
        draw.line([(left, y), (width - right, y)], fill=(190, 190, 190, 255))
        draw.text((4, y - 5), f"{level:.0f}", fill=(70, 70, 70, 255))

    px, py = sx(t), sy(alt)
    keep = decimate(px, py, 0.5)
    for a, b in zip(keep, keep[1:]):
        band = _band_index(float(series.climb[b]), CLIMB_BANDS)
        colour = CLIMB_BANDS[band][1]
        # Back from KML's aabbggrr to PIL's rgba.
        rgba = (int(colour[6:8], 16), int(colour[4:6], 16), int(colour[2:4], 16), 255)
        draw.line([(float(px[a]), float(py[a])), (float(px[b]), float(py[b]))],
                  fill=rgba, width=2)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def document(analysis: Analysis, *, route=None, meteo=None) -> str:
    """The KML document for one flight."""
    flight = analysis.flight
    series = analysis.series
    alt = series.alt
    summary = analysis.summary

    # Three detail levels, decimated in projected metres. The coarse one is what Earth
    # draws when the track is a thumbnail; the fine one only loads when it fills the view.
    # Three detail levels with Region/Lod, ordered coarse → fine. Earth on the desktop
    # measures the flight's on-screen size and draws only the matching level: 56 points
    # when the track is a thumbnail, 1 727 when it fills the window. A viewer that
    # ignores Region draws all three, and because the finest is last it wins the
    # overdraw — so the fallback is correct, merely wasteful.
    detail = [
        ("Coarse", decimate(series.x, series.y, 120.0), 16, 320),
        ("Medium", decimate(series.x, series.y, 25.0), 320, 1400),
        ("Detailed", decimate(series.x, series.y, 4.0), 1400, -1),
    ]
    # The shadow stays single-level: it is a reference line on the ground, not the data.
    keep_shadow = decimate(series.x, series.y, 20.0)

    styles = [
        '<Style id="hide-children"><ListStyle>'
        "<listItemType>checkHideChildren</listItemType></ListStyle></Style>",
        '<Style id="radio"><ListStyle><listItemType>radioFolder</listItemType></ListStyle></Style>',
        '<Style id="summary"><IconStyle><scale>1.1</scale>'
        "<Icon><href>images/mark.png</href></Icon></IconStyle>"
        "<LabelStyle><scale>0.8</scale></LabelStyle></Style>",
        _style("shadow", kml_colour("303030", 128), 2),
        _style("solid", kml_colour("eb6834")),
        _style("xc-leg", kml_colour("ffffff", 176), 2),
        '<Style id="xc-point"><IconStyle><scale>0.7</scale>'
        "<Icon><href>images/mark.png</href></Icon></IconStyle></Style>",
        '<Style id="glider"><IconStyle><scale>1.2</scale>'
        "<Icon><href>images/climb.png</href></Icon></IconStyle>"
        "<LabelStyle><scale>0</scale></LabelStyle></Style>",
        '<Style id="time-mark"><IconStyle><scale>0.5</scale>'
        "<Icon><href>images/mark.png</href></Icon></IconStyle>"
        "<LabelStyle><scale>0.7</scale></LabelStyle></Style>",
        '<Style id="altitude-mark"><IconStyle><scale>0.5</scale>'
        "<Icon><href>images/mark.png</href></Icon></IconStyle>"
        "<LabelStyle><scale>0.7</scale></LabelStyle></Style>",
        _balloon_style("thermal-balloon", THERMAL_ROWS, "climb.png"),
        _balloon_style("tow-balloon", THERMAL_ROWS, "tow.png"),
        _balloon_style("glide-balloon", GLIDE_ROWS, "glide.png"),
        _style("thermal-balloon-line", kml_colour("eb6834"), 2),
        _style("tow-balloon-line", kml_colour("1baf7a"), 2),
        _style("glide-balloon-line", kml_colour("2a78d6"), 2),
    ]
    for index, (_, colour) in enumerate(CLIMB_BANDS):
        styles.append(_style(f"climb{index}", colour))
    altitude_bands = _linear_bands(
        float(alt.min()), float(alt.max()), ALTITUDE_BANDS, ALTITUDE_PALETTE
    )
    for index, (_, colour) in enumerate(altitude_bands):
        styles.append(_style(f"height{index}", colour))
    speed_bands = _linear_bands(0.0, float(series.speed.max()), SPEED_BANDS, SPEED_PALETTE)
    for index, (_, colour) in enumerate(speed_bands):
        styles.append(_style(f"speed{index}", colour))

    # Track folder: one LOD folder per detail level, each holding the colourings.
    lod_folders = []
    for level, (label, keep, min_pixels, max_pixels) in enumerate(detail):
        # Deliberate order: the alternatives first, climb last. Google Earth on mobile
        # ignores per-folder visibility inside a radioFolder and draws them all, and the
        # last one drawn wins where they overlap — so the last one must be the good one.
        # (This is why the whole track appeared solid blue: "Solid colour" was last.)
        colourings = [
            f'<Folder><name>Solid colour</name><visibility>0</visibility>'
            f'<styleUrl>#hide-children</styleUrl>'
            f'<Placemark><styleUrl>#solid</styleUrl><LineString>'
            f"<altitudeMode>absolute</altitudeMode>"
            f"<coordinates>{_coords(flight.lat, flight.lon, alt, keep)}</coordinates>"
            f"</LineString></Placemark></Folder>",
            _coloured_folder("Coloured by ground speed", analysis, series.speed, speed_bands,
                             keep, prefix="speed", visible=False),
            _coloured_folder("Coloured by altitude", analysis, alt, altitude_bands, keep,
                             prefix="height", visible=False),
            _coloured_folder("Coloured by total energy", analysis, series.te_climb, CLIMB_BANDS,
                             keep, prefix="climb", visible=False),
            _coloured_folder("Coloured by climb", analysis, series.climb, CLIMB_BANDS, keep,
                             prefix="climb", visible=True),
        ]
        lod_folders.append(
            f"<Folder><name>{label}</name>"
            # KML's Feature sequence puts styleUrl before Region; a strict validator
            # rejects the other order even though Earth tolerates it.
            f"<styleUrl>#radio</styleUrl>"
            f"{_region(flight.lat, flight.lon, alt, min_pixels, max_pixels)}"
            f'{"".join(colourings)}</Folder>'
        )

    shadow = (
        "<Folder><name>Shadow</name><visibility>0</visibility>"
        '<styleUrl>#radio</styleUrl>'
        "<Folder><name>On the ground</name><styleUrl>#hide-children</styleUrl>"
        '<Placemark><styleUrl>#shadow</styleUrl><LineString><tessellate>1</tessellate>'
        "<altitudeMode>clampToGround</altitudeMode>"
        f"<coordinates>{_coords(flight.lat, flight.lon, indices=keep_shadow)}</coordinates>"
        "</LineString></Placemark></Folder>"
        "<Folder><name>Curtain</name><visibility>0</visibility>"
        '<styleUrl>#hide-children</styleUrl>'
        '<Placemark><styleUrl>#shadow</styleUrl><LineString><extrude>1</extrude>'
        "<altitudeMode>absolute</altitudeMode>"
        f"<coordinates>{_coords(flight.lat, flight.lon, alt, keep_shadow)}</coordinates>"
        "</LineString></Placemark></Folder></Folder>"
    )

    climbs = []
    number = 0
    for segment in analysis.segments:
        if segment.phase in (Phase.THERMAL, Phase.TOW):
            if segment.phase is Phase.THERMAL:
                number += 1
            climbs.append(_segment_placemark(analysis, segment, number))
    glides = [
        _segment_placemark(analysis, segment, index)
        for index, segment in enumerate(analysis.glides, start=1)
    ]

    overlays = ""
    if barogram_png(analysis) is not None:
        overlays = _chart_overlay("barogram.png", "Barogram")

    name = f"{summary.date} {summary.site or ''}".strip()
    snippet = (
        f"{summary.track_distance / 1000:.0f} km flown"
        + (f", {route.km:.1f} km XC" if route else "")
        + f", {summary.duration // 3600}h{summary.duration % 3600 // 60:02d}"
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n'
        f"<name>{_escape(name)}</name>"
        f"<Snippet>{_escape(snippet)}</Snippet>"
        f"<description>{_escape(_summary_text(analysis, route))}</description>"
        f'{"".join(styles)}'
        f"{_summary_placemark(analysis, route, meteo)}"
        # radioFolder on the Track folder: the colourings are alternatives, so a viewer
        # that honours it shows exactly one.
        f'<Folder><name>Track</name><open>1</open><styleUrl>#radio</styleUrl>'
        f'{"".join(lod_folders)}</Folder>'
        f"{shadow}"
        f"<Folder><name>Climbs</name><styleUrl>#hide-children</styleUrl>"
        f'{"".join(climbs)}</Folder>'
        f"<Folder><name>Glides</name><visibility>0</visibility>"
        f'<styleUrl>#hide-children</styleUrl>{"".join(glides)}</Folder>'
        f"{_xc_folder(route)}"
        f"{_altitude_marks(analysis)}"
        f"{_time_marks(analysis)}"
        f"{_animation(analysis)}"
        f"{overlays}"
        "</Document>\n</kml>\n"
    )


def to_bytes(analysis: Analysis, *, route=None, meteo=None) -> bytes:
    """The KMZ as bytes, for embedding in the HTML report as a download."""
    buffer = io.BytesIO()
    _archive(buffer, analysis, route=route, meteo=meteo)
    return buffer.getvalue()


def _archive(target, analysis: Analysis, *, route=None, meteo=None) -> None:
    kml = document(analysis, route=route, meteo=meteo)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        # doc.kml first: Google Earth opens the first .kml it finds.
        archive.writestr("doc.kml", kml)
        archive.writestr("images/climb.png", GLIDER_ICON_PNG)
        archive.writestr("images/tow.png", TOW_ICON_PNG)
        archive.writestr("images/glide.png", GLIDE_ICON_PNG)
        archive.writestr("images/mark.png", MARK_ICON_PNG)
        chart = barogram_png(analysis)
        if chart:
            archive.writestr("images/barogram.png", chart)


def write(analysis: Analysis, path, *, route=None, meteo=None) -> Path:
    """Write a KMZ: doc.kml plus the images it references, nothing external."""
    path = Path(path)
    with open(path, "wb") as handle:
        _archive(handle, analysis, route=route, meteo=meteo)
    return path

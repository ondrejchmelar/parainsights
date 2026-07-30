"""Derived series: everything computed per-fix from a parsed :class:`~tracklog_viewer.igc.Flight`.

All series are computed over a sliding time window with *interpolated* edges rather
than snapping to the nearest fix. That matters because loggers are not reliably 1 Hz —
snapping makes the window length vary with the sample rate and quietly biases climb
rates.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import geo
from .igc import Flight

G = 9.80665
WINDOW = 20.0  # seconds; the de facto standard averaging period for climb rate
TURN_SMOOTHING = 5.0  # seconds


@dataclass
class Series:
    """Per-fix derived quantities. Every array is the same length as the flight."""

    t: np.ndarray  # seconds since take-off
    s: np.ndarray  # distance flown, metres
    alt: np.ndarray  # altitude used for vertical analysis, metres
    speed: np.ndarray  # ground speed, km/h
    climb: np.ndarray  # vertical speed, m/s
    te_climb: np.ndarray  # total-energy-compensated vertical speed, m/s
    progress: np.ndarray  # straight-line / flown distance over the window, 0..1
    heading: np.ndarray  # unwrapped course over ground, degrees
    turn_rate: np.ndarray  # degrees/second, + = clockwise (right)
    x: np.ndarray  # local east offset from take-off, metres
    y: np.ndarray  # local north offset from take-off, metres

    def __len__(self) -> int:
        return len(self.t)


def local_frame(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project to a local east/north plane in metres, origin at the first fix.

    An equirectangular projection about the take-off point. Over the ~100 km of a
    cross-country flight the distortion is centimetres, and it makes drift fitting
    and circle geometry ordinary linear algebra.
    """
    lat0, lon0 = lat[0], lon[0]
    x = np.radians(lon - lon0) * geo.R * np.cos(np.radians(lat0))
    y = np.radians(lat - lat0) * geo.R
    return x, y


def _window_edges(t: np.ndarray, window: float) -> tuple[np.ndarray, np.ndarray]:
    """Start and end times of the averaging window centred on each fix, clipped
    to the flight so the window never extends past the data."""
    half = window / 2
    t0 = np.clip(t - half, t[0], t[-1])
    t1 = np.clip(t + half, t[0], t[-1])
    # Where clipping shortened one side, shift the other to keep the full length.
    short = t1 - t0 < window
    if short.any():
        t0[short] = np.clip(t1[short] - window, t[0], t[-1])
        t1[short] = np.clip(t0[short] + window, t[0], t[-1])
    return t0, t1


def derive(flight: Flight, *, window: float = WINDOW) -> Series:
    """Compute all derived series for a flight."""
    t = (flight.time - flight.time[0]).astype("int64").astype(float)
    alt = flight.alt.astype(float)
    x, y = local_frame(flight.lat, flight.lon)
    s = geo.cumulative_distance(flight.lat, flight.lon)

    # Total energy altitude: trading speed for height should not read as a climb.
    step_t = np.diff(t)
    step_v = np.diff(s) / np.where(step_t == 0, np.nan, step_t)
    v = np.concatenate(([step_v[0]], step_v)) if len(step_v) else np.zeros_like(t)
    v = np.nan_to_num(v)
    te_alt = alt + v**2 / (2 * G)

    t0, t1 = _window_edges(t, window)
    span = np.maximum(t1 - t0, 1e-9)

    def at(times, values):
        return np.interp(times, t, values)

    s0, s1 = at(t0, s), at(t1, s)
    flown = s1 - s0
    straight = np.hypot(at(t1, x) - at(t0, x), at(t1, y) - at(t0, y))

    speed = 3.6 * flown / span
    climb = (at(t1, alt) - at(t0, alt)) / span
    te_climb = (at(t1, te_alt) - at(t0, te_alt)) / span
    # Progress: 1.0 flying straight, ~0 circling. Guard the stationary case, where
    # flown distance is noise and the ratio is meaningless.
    progress = np.where(flown > 1.0, np.clip(straight / np.maximum(flown, 1e-9), 0.0, 1.0), 0.0)

    heading, turn_rate = _turning(t, x, y)

    return Series(
        t=t, s=s, alt=alt, speed=speed, climb=climb, te_climb=te_climb,
        progress=progress, heading=heading, turn_rate=turn_rate, x=x, y=y,
    )


def _turning(t: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Unwrapped course and turn rate.

    Unwrapping is what makes turn *counting* possible later: the cumulative heading
    change over a thermal divided by 360 is the number of circles flown.
    """
    dx, dy = np.diff(x), np.diff(y)
    course = np.degrees(np.arctan2(dx, dy))  # 0 = north, + = clockwise
    course = np.concatenate(([course[0]], course)) if len(course) else np.zeros_like(t)
    # Where the glider barely moved the course is noise; hold the previous value.
    moved = np.concatenate(([True], np.hypot(dx, dy) > 0.5))
    idx = np.maximum.accumulate(np.where(moved, np.arange(len(course)), 0))
    course = course[idx]
    heading = np.degrees(np.unwrap(np.radians(course)))

    # Differentiate over a few seconds: fix-to-fix heading change is too noisy.
    smooth = np.interp(t + TURN_SMOOTHING / 2, t, heading) - np.interp(
        t - TURN_SMOOTHING / 2, t, heading
    )
    return heading, smooth / TURN_SMOOTHING

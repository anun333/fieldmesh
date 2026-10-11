#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Where the sun is, and the most sunshine a clear sky gives (FAO-56, chapter 3).

A pyranometer is checked against the sky: at night it reads nothing, and in the day no
more than a clear sky delivers at that hour, give or take the brief excess at a
cloud's edge. Everything here is FAO-56's (Allen et al. 1998), from the site's latitude,
longitude and elevation and the moment in UTC:

* the inverse relative distance Earth–Sun, `dr` (eq. 23), and the solar declination
  `δ` (eq. 24);
* the seasonal correction for solar time, `Sc` (eqs. 32–33), and the hour angle `ω`
  (eq. 31), counted here from UTC and the longitude east;
* the extraterrestrial irradiance on a horizontal surface, `Gsc · dr · cos θz`, with
  `cos θz = sin φ sin δ + cos φ cos δ cos ω`, the instantaneous form of eq. 28;
* the clear-sky irradiance, `Rso = (0.75 + 2×10⁻⁵ z) Ra` (eq. 37).

    clear_sky_w(36.01, -85.13, 573.0, when)                 # W m-2 at that instant
    clear_sky_mean_w(36.01, -85.13, 573.0, when, 3600.0)    # over the hour ending then
"""
from __future__ import annotations

import datetime as _dt
import math

#: The solar constant, FAO-56's 0.0820 MJ m-2 min-1, in W m-2.
GSC_W = 0.0820e6 / 60.0
STEP_S = 300.0


def _day(when: _dt.datetime) -> int:
    return when.timetuple().tm_yday


def cos_zenith(lat: float, lon: float, when: _dt.datetime) -> float:
    """The cosine of the sun's zenith angle at a UTC moment; negative below the horizon."""
    if when.tzinfo is None or when.utcoffset() != _dt.timedelta(0):
        raise ValueError("a moment for the sun is timezone-aware UTC")
    j = _day(when)
    delta = 0.409 * math.sin(2.0 * math.pi * j / 365.0 - 1.39)
    b = 2.0 * math.pi * (j - 81) / 364.0
    sc = 0.1645 * math.sin(2.0 * b) - 0.1255 * math.cos(b) - 0.025 * math.sin(b)
    hours = when.hour + when.minute / 60.0 + when.second / 3600.0
    omega = math.pi / 12.0 * ((hours + lon / 15.0 + sc) - 12.0)
    phi = math.radians(lat)
    return (math.sin(phi) * math.sin(delta)
            + math.cos(phi) * math.cos(delta) * math.cos(omega))


def extraterrestrial_w(lat: float, lon: float, when: _dt.datetime) -> float:
    """Sunshine on a horizontal surface at the top of the atmosphere, W m-2."""
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * _day(when) / 365.0)
    return GSC_W * dr * max(0.0, cos_zenith(lat, lon, when))


def clear_sky_w(lat: float, lon: float, elevation_m: float, when: _dt.datetime) -> float:
    """What a clear sky delivers to a horizontal surface at a moment, W m-2 (eq. 37)."""
    return (0.75 + 2e-5 * elevation_m) * extraterrestrial_w(lat, lon, when)


def clear_sky_mean_w(lat: float, lon: float, elevation_m: float, end: _dt.datetime,
                     window_s: float) -> float:
    """The clear sky's mean over the window ending at `end`, as a station's mean over
    the same window would be compared with it; a window of 0 is the moment itself."""
    if window_s <= 0:
        return clear_sky_w(lat, lon, elevation_m, end)
    n = max(1, int(round(window_s / STEP_S)))
    step = window_s / n
    return sum(clear_sky_w(lat, lon, elevation_m,
                           end - _dt.timedelta(seconds=(k + 0.5) * step))
               for k in range(n)) / n


def clear_sky_max_w(lat: float, lon: float, elevation_m: float, end: _dt.datetime,
                    window_s: float) -> float:
    """The clear sky's most at any moment in the window ending at `end`."""
    if window_s <= 0:
        return clear_sky_w(lat, lon, elevation_m, end)
    n = max(1, int(round(window_s / STEP_S)))
    return max(clear_sky_w(lat, lon, elevation_m, end - _dt.timedelta(seconds=k * window_s / n))
               for k in range(n + 1))

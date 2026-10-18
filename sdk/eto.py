#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reference evapotranspiration from a farm's own station (FAO-56 Penman–Monteith).

A day's reference ET, the water a well-watered grass gives up, is what watering by the
weather rests on ([lawn sprinklers](../docs/notes/lawn-sprinklers.md): the best single
add-on). This computes it as FAO-56 does (Allen et al. 1998, chapters 3 and 4), from a
day's minimum and maximum air temperature, humidity, sunshine and wind:

    ETo = [0.408 Δ (Rn − G) + γ 900/(T + 273) u₂ (es − ea)] / [Δ + γ (1 + 0.34 u₂)]   (eq. 6)

When a sensor is missing it uses FAO-56's own stand-ins, and says which it used:

* no sunshine: Hargreaves' radiation from the temperature range (eq. 50, `krs` 0.16
  inland, 0.19 near a coast);
* no humidity: the dew point taken as the day's minimum (eq. 48);
* no wind: 2 m/s (FAO-56's "temporary estimate").

`day_summary` reads a station's day out of the log: only readings the health checks had
passed, within the farm's local day, in whatever unit each series declares.

    eto_daily(12.3, 21.5, lat=50.8, elevation_m=100.0, day_of_year=187, rs=22.07,
              rh_max=84.0, rh_min=63.0, u2=2.078)     # FAO-56 Example 18: 3.88 mm
"""
from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from uuid import UUID
from zoneinfo import ZoneInfo

GSC_MJ = 0.0820                      # MJ m-2 min-1
SIGMA = 4.903e-9                     # MJ K-4 m-2 day-1
WIND_DEFAULT = 2.0


def e0(t: float) -> float:
    """Saturation vapour pressure at a temperature, kPa (eq. 11)."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def ra_daily(lat: float, day_of_year: int) -> float:
    """Extraterrestrial radiation for a day, MJ m-2 (eqs. 21, 23–25)."""
    phi = math.radians(lat)
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * day_of_year / 365.0)
    delta = 0.409 * math.sin(2.0 * math.pi * day_of_year / 365.0 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    return (24.0 * 60.0 / math.pi * GSC_MJ * dr
            * (ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws)))


def u2_from(speed: float, height_m: float) -> float:
    """Wind measured at a height brought to 2 m (eq. 47)."""
    if abs(height_m - 2.0) < 1e-9:
        return speed
    return speed * 4.87 / math.log(67.8 * height_m - 5.42)


def eto_daily(tmin: float, tmax: float, *, lat: float, elevation_m: float, day_of_year: int,
              rs: float | None = None, rh_mean: float | None = None,
              rh_max: float | None = None, rh_min: float | None = None,
              tdew: float | None = None, u2: float | None = None,
              krs: float = 0.16) -> tuple[float, tuple]:
    """A day's reference ET, mm, and which FAO-56 stand-ins it used (`"sunshine"`,
    `"humidity"`, `"wind"`). `rs` is the day's sunshine, MJ m-2; humidity in percent."""
    estimated = []
    t = (tmax + tmin) / 2.0
    p = 101.3 * ((293.0 - 0.0065 * elevation_m) / 293.0) ** 5.26        # eq. 7
    gamma = 0.665e-3 * p                                                  # eq. 8
    delta = 4098.0 * e0(t) / (t + 237.3) ** 2                             # eq. 13
    es = (e0(tmax) + e0(tmin)) / 2.0                                      # eq. 12
    if rh_max is not None and rh_min is not None:
        ea = (e0(tmin) * rh_max / 100.0 + e0(tmax) * rh_min / 100.0) / 2.0  # eq. 17
    elif rh_mean is not None:
        ea = rh_mean / 100.0 * es                                         # eq. 19
    else:
        ea = e0(tdew if tdew is not None else tmin)                       # eqs. 14, 48
        if tdew is None:
            estimated.append("humidity")
    ra = ra_daily(lat, day_of_year)
    if rs is None:
        rs = krs * math.sqrt(max(0.0, tmax - tmin)) * ra                  # eq. 50
        estimated.append("sunshine")
    rso = (0.75 + 2e-5 * elevation_m) * ra                                # eq. 37
    rns = (1.0 - 0.23) * rs                                               # eq. 38
    ratio = min(1.0, rs / rso) if rso > 0 else 0.0
    rnl = (SIGMA * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2.0
           * (0.34 - 0.14 * math.sqrt(max(0.0, ea))) * (1.35 * ratio - 0.35))  # eq. 39
    rn = rns - rnl
    if u2 is None:
        u2 = WIND_DEFAULT
        estimated.append("wind")
    eto = ((0.408 * delta * rn + gamma * 900.0 / (t + 273.0) * u2 * (es - ea))
           / (delta + gamma * (1.0 + 0.34 * u2)))
    return max(0.0, eto), tuple(estimated)


# ------------------------------------------------------------ from the log

@dataclass(frozen=True)
class Station:
    """A farm's weather station: where it is, and the series it keeps. Only the air
    temperature is required; each missing series is replaced by FAO-56's stand-in."""

    lat: float
    elevation_m: float
    timezone: str
    air_temperature: UUID
    relative_humidity: UUID | None = None
    solar_radiation: UUID | None = None
    wind_speed: UUID | None = None
    wind_height_m: float = 2.0
    #: The site's mean wind at 2 m in each month, January first, m/s: a regional figure
    #: for the days it has no wind of its own, as FAO-56 prefers to its 2 m/s (NASA
    #: POWER's WS2M over the years, `tools/nasa_power.py`).
    wind_normal: tuple | None = None
    precipitation: UUID | None = None
    krs: float = 0.16


#: Units a station's series may declare, to the ones FAO-56 works in.
_TO = {
    "Cel": lambda v: v, "K": lambda v: v - 273.15, "[degF]": lambda v: (v - 32.0) * 5.0 / 9.0,
    "%": lambda v: v, "1": lambda v: v * 100.0,
    "m/s": lambda v: v, "km/h": lambda v: v / 3.6, "[mi_i]/h": lambda v: v * 0.44704,
    "W/m2": lambda v: v,
    "mm": lambda v: v, "m": lambda v: v * 1000.0, "[in_i]": lambda v: v * 25.4,
}
#: A day counts when its readings span this much of it.
MIN_SPAN_H = 20.0


def _readings(state, datastream: UUID | None, start, end, at) -> list:
    """`[(measured_at, value)]` in FAO-56's units, readings the checks had passed by
    `at`, between two moments, oldest first."""
    if datastream is None or datastream not in state.datastreams:
        return []
    from model import Usable
    convert = _TO.get(state.datastreams[datastream].unit)
    if convert is None:
        return []
    out = []
    for o in state.live_observations_of(datastream):
        if not (start <= o.measured_at < end) or o.received_at > at:
            continue
        if not isinstance(o.result, (int, float)) or isinstance(o.result, bool):
            continue
        if state.quality_as_of(o.id, at)[0] is not Usable.GOOD:
            continue
        out.append((o.measured_at, convert(float(o.result))))
    return sorted(out)


def rain_between(state, station: Station, start: _dt.datetime, end: _dt.datetime,
                 at: _dt.datetime) -> float | None:
    """The station's rain between two moments, mm, from the readings the checks had passed
    by `at`; None for a station with no gauge."""
    if station.precipitation is None:
        return None
    return sum(v for _, v in _readings(state, station.precipitation, start, end, at))


def _spans_day(rows) -> bool:
    return len(rows) >= 8 and (rows[-1][0] - rows[0][0]) >= _dt.timedelta(hours=MIN_SPAN_H)


def _bounds(station: Station, day: _dt.date):
    tz = ZoneInfo(station.timezone)
    start = _dt.datetime.combine(day, _dt.time(), tzinfo=tz).astimezone(_dt.timezone.utc)
    end = _dt.datetime.combine(day + _dt.timedelta(days=1), _dt.time(),
                               tzinfo=tz).astimezone(_dt.timezone.utc)
    return start, end


def summaries(state, station: Station, first: _dt.date, last: _dt.date,
              at: _dt.datetime) -> dict:
    """Each local day from `first` to `last`, as `day_summary` gives it, each series
    read once for the whole span."""
    start, _ = _bounds(station, first)
    _, end = _bounds(station, last)
    series = {name: _readings(state, getattr(station, name), start, end, at)
              for name in ("air_temperature", "relative_humidity", "solar_radiation",
                           "wind_speed", "precipitation")}
    out, day = {}, first
    while day <= last:
        lo, hi = _bounds(station, day)
        part = {name: [r for r in rows if lo <= r[0] < hi] for name, rows in series.items()}
        air = part["air_temperature"]
        if not _spans_day(air):
            out[day] = None
        else:
            rh, sun, wind = (part["relative_humidity"], part["solar_radiation"],
                             part["wind_speed"])
            out[day] = {
                "tmin": min(v for _, v in air), "tmax": max(v for _, v in air),
                "rh_mean": sum(v for _, v in rh) / len(rh) if _spans_day(rh) else None,
                # W m-2 averaged over the day, to MJ m-2 a day.
                "rs": sum(v for _, v in sun) / len(sun) * 0.0864 if _spans_day(sun) else None,
                "u2": (u2_from(sum(v for _, v in wind) / len(wind), station.wind_height_m)
                       if _spans_day(wind) else None),
                "rain": (sum(v for _, v in part["precipitation"])
                         if station.precipitation is not None else None)}
        day += _dt.timedelta(days=1)
    return out


def daily_temperatures(state, station: Station, first: _dt.date, last: _dt.date,
                       at: _dt.datetime) -> dict:
    """`{local day: (tmin, tmax) or None}` from `first` to `last`: the air temperature
    alone, read once, for a crop's degree-days; None for a day the readings do not span."""
    start, _ = _bounds(station, first)
    _, end = _bounds(station, last)
    rows = _readings(state, station.air_temperature, start, end, at)
    out, i, day = {}, 0, first
    while day <= last:
        lo, hi = _bounds(station, day)
        while i < len(rows) and rows[i][0] < lo:
            i += 1
        j = i
        while j < len(rows) and rows[j][0] < hi:
            j += 1
        part = rows[i:j]
        out[day] = ((min(v for _, v in part), max(v for _, v in part))
                    if _spans_day(part) else None)
        i, day = j, day + _dt.timedelta(days=1)
    return out


def day_summary(state, station: Station, day: _dt.date, at: _dt.datetime) -> dict | None:
    """A local day's weather from the station as it stood at `at`: `tmin`, `tmax`,
    `rh_mean`, `rs` (MJ m-2), `u2` (m/s), `rain` (mm), each None when its series did not
    cover the day; None altogether without the day's air temperature."""
    return summaries(state, station, day, day, at)[day]


def eto_of(station: Station, day: _dt.date, s: dict | None):
    """`(eto_mm, rain_mm, estimated)` from a day's summary, or None."""
    if s is None:
        return None
    u2, normal = s["u2"], False
    if u2 is None and station.wind_normal is not None:
        u2, normal = float(station.wind_normal[day.month - 1]), True
    eto, estimated = eto_daily(s["tmin"], s["tmax"], lat=station.lat,
                               elevation_m=station.elevation_m,
                               day_of_year=day.timetuple().tm_yday, rs=s["rs"],
                               rh_mean=s["rh_mean"], u2=u2, krs=station.krs)
    return eto, s["rain"], estimated + (("wind normal",) if normal else ())


def eto_for_day(state, station: Station, day: _dt.date, at: _dt.datetime):
    """`(eto_mm, rain_mm, estimated)` for a local day, or None when the station has
    not got the day's air temperature."""
    return eto_of(station, day, day_summary(state, station, day, at))

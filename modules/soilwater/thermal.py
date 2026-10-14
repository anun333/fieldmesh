# SPDX-License-Identifier: AGPL-3.0-or-later
"""A crop's clock in degree-days.

FAO-56's 1998 edition gave a crop's stages in days (Table 11), for a typical season where
it was measured. A warm year runs a crop through its stages sooner and a cool one later,
and the 2025 revision (FAO-56 Rev.1, section 6.8.1) gives them in growing degree-days
instead: for the crops with field-observed values, each stage's (its Table 6.11). Such a
crop's clock is the degree-days it has gathered since sowing (`cumulative_gdd`).

For a crop the revision has no observed values for, the 1998 days are taken as right for
this farm's normal year, and a season runs ahead of them or behind as it is warmer or
cooler than normal: on any day the crop is as far through its curve as a normal year
would have taken it to gather the degree-days this year has given it (`growing_days`).
That is how the revision's own Table 6.12 turns the 1998 days into degree-days, at a
representative place rather than this farm. In a normal year it is the calendar.

A day's degree-days are the revision's Eq. 6.23: the day's mean temperature less the
crop's base, nothing below the base, and no more than the upper threshold less the base,
with each crop's thresholds from its Table 6.10 (`data/fao56rev-crops.csv`). The normal
is the mean of each day of the year over a record of past years, such as NASA POWER's
that `tools/weather_csv.py` writes, smoothed over `SMOOTH_DAYS` either side.
"""
from __future__ import annotations

import csv
import datetime as _dt
import os

HERE = os.path.dirname(os.path.abspath(__file__))

#: Days either side each day of the year's normal is averaged over.
SMOOTH_DAYS = 7
#: Degree-days a day counts for at least, in the normal year and this one alike, so a
#: cold spell in both still moves the crop on by the calendar rather than stopping its clock.
FLOOR_GDD = 0.05


def _load_thresholds() -> dict:
    out = {}
    with open(os.path.join(HERE, "data", "fao56rev-crops.csv"), encoding="utf-8") as h:
        for r in csv.DictReader(h):
            pair = (float(r["tbase_c"]), float(r["tupper_c"]))
            if r["variant"]:
                out[f'{r["crop"]}:{r["variant"]}'] = pair
            if r["default"] == "1":
                out[r["crop"]] = pair
    return out


#: `{crop: (base, upper)}`, °C: the revision's Table 6.10, for each crop and `crop:variant`.
THRESHOLDS = _load_thresholds()


def gdd(tmin: float, tmax: float, base: float, upper: float) -> float:
    """A day's growing degree-days (FAO-56 Rev.1, Eq. 6.23)."""
    mean = (tmin + tmax) / 2.0
    if mean <= base:
        return 0.0
    return min(mean, upper) - base


def read_climate(path: str) -> dict:
    """`{date: (tmin, tmax)}` from a daily record with `date`, `T2M_MIN` and `T2M_MAX`
    columns under `#` comment lines, as `tools/weather_csv.py` writes NASA POWER's."""
    out = {}
    with open(path, encoding="utf-8") as h:
        for r in csv.DictReader(line for line in h if not line.startswith("#")):
            if r.get("T2M_MIN") and r.get("T2M_MAX"):
                out[_dt.date.fromisoformat(r["date"])] = (float(r["T2M_MIN"]),
                                                          float(r["T2M_MAX"]))
    return out


class Normal:
    """A farm's normal year from its record of past years: each day of the year's mean
    degree-days for a crop's thresholds. `without` leaves a year out of the record, as a
    backtest of that year must."""

    def __init__(self, record: dict, *, without: int | None = None) -> None:
        self.record = {d: t for d, t in record.items() if d.year != without}
        if not self.record:
            raise ValueError("a normal needs a record of past years")
        self._by_thresholds: dict = {}

    def _table(self, base: float, upper: float) -> list:
        key = (base, upper)
        if key not in self._by_thresholds:
            sums, counts = [0.0] * 366, [0] * 366
            for d, (tmin, tmax) in self.record.items():
                i = _day_index(d)
                sums[i] += gdd(tmin, tmax, base, upper)
                counts[i] += 1
            raw = [s / c if c else None for s, c in zip(sums, counts)]
            table = []
            for i in range(366):
                near = [raw[(i + k) % 366] for k in range(-SMOOTH_DAYS, SMOOTH_DAYS + 1)]
                near = [v for v in near if v is not None]
                table.append(sum(near) / len(near) if near else 0.0)
            self._by_thresholds[key] = table
        return self._by_thresholds[key]

    def gdd(self, day: _dt.date, base: float, upper: float) -> float:
        return self._table(base, upper)[_day_index(day)]


def _day_index(day: _dt.date) -> int:
    """0 to 365, a leap year's 29 February its own day and the days after it shifted, so
    1 March is the same index in every year."""
    start = _dt.date(day.year, 1, 1)
    i = (day - start).days
    leap = day.year % 4 == 0 and (day.year % 100 != 0 or day.year % 400 == 0)
    return i if leap or i < 59 else i + 1


def growing_days(crop: str, planted: _dt.date, last: _dt.date, actual: dict,
                 normal: Normal) -> dict:
    """`{day: growing days}` from `planted` to `last`: on each day, how many days a normal
    year takes from sowing to gather the degree-days this year had given the crop by the
    start of that day. `actual` is `{date: (tmin, tmax) or None}`; a day it lacks counts as
    a normal one, so a station that misses a day neither stops the crop nor hurries it."""
    base, upper = THRESHOLDS[crop]
    out, have, normal_sum, k = {}, 0.0, [0.0], 0
    span = (last - planted).days
    for n in range(span + 1):
        day = planted + _dt.timedelta(days=n)
        # The normal year's sum, extended as far as this year's has reached.
        while normal_sum[-1] < have or k <= n:
            g = max(FLOOR_GDD, normal.gdd(planted + _dt.timedelta(days=k), base, upper))
            normal_sum.append(normal_sum[-1] + g)
            k += 1
        i = _first_reaching(normal_sum, have)
        if i == 0:
            out[day] = 0.0
        else:
            lo, hi = normal_sum[i - 1], normal_sum[i]
            out[day] = round(i - 1 + (have - lo) / (hi - lo), 3)
        today = actual.get(day)
        g = (gdd(today[0], today[1], base, upper) if today is not None
             else normal.gdd(day, base, upper))
        have += max(FLOOR_GDD, g)
    return out


def cumulative_gdd(crop: str, planted: _dt.date, last: _dt.date, actual: dict,
                   normal: Normal | None = None) -> dict:
    """`{day: degree-days}` from `planted` to `last`: what the crop had gathered by the start
    of each day. `actual` is `{date: (tmin, tmax) or None}`; a day it lacks counts as the
    normal year's, or, without one, as the mean of the days it has had."""
    base, upper = THRESHOLDS[crop]
    out, have, seen = {}, 0.0, []
    for n in range((last - planted).days + 1):
        day = planted + _dt.timedelta(days=n)
        out[day] = round(have, 1)
        today = actual.get(day)
        if today is not None:
            g = gdd(today[0], today[1], base, upper)
            seen.append(g)
        elif normal is not None:
            g = normal.gdd(day, base, upper)
        else:
            g = sum(seen[-7:]) / len(seen[-7:]) if seen else 0.0
        have += g
    return out


def _first_reaching(sums: list, value: float) -> int:
    """The first index whose running sum reaches `value` (0 for none needed)."""
    lo, hi = 0, len(sums) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if sums[mid] >= value:
            hi = mid
        else:
            lo = mid + 1
    return lo

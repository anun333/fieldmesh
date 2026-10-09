#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""When stone fruit blooms at a site, and how often a frost follows it.

    python3 tools/fruit_bloom.py LAT LON --cache CACHE [--warm 1.0]

Getting its chill is half of a fruit tree's spring; the other half is whether the bloom
that follows meets a frost. For every cultivar in docs/notes/chill-requirements.csv
with both a chill-hour and a heat requirement — 132 of them, from the review by Fadón
et al. (2020) — this runs the sequential model the requirements were measured against,
on the site's own thirty winters:

* **chill** from November 1 (May 1 south of the equator), counting hours above 0 and at
  or below 7.2 °C — the review's definition, and chillR's — until the cultivar's
  requirement is met;
* **heat** after that, in growing degree hours (Anderson, Richardson & Kesner 1986,
  Acta Hort. 184:71–78: base 4, optimum 25, ceiling 36 °C), until its requirement is met:
  that day is bloom;
* **frost**: a daily minimum at or below −2.2 °C on any day from bloom through the two
  weeks after it. −2.2 °C is 28 °F, the temperature that kills 10% of sweet cherry
  buds at full bloom; peach and apricot lose 10% at 27 °F (Washington State's Prosser
  measurements, as tabulated by Penn State Extension, Orchard Frost: Critical
  Temperatures for Various Fruits). The warmer of the two is used for every crop, and
  plum and almond are assumed to match.

Hours are a sine between each day's minimum and maximum. A requirement given as a range
is taken at its middle, "828 ± 139" at 828. NASA POWER's grid-cell minimum is milder
than an orchard floor's on a still night, so the frost counts err low.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import math
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dssat_crops  # noqa: E402
import site_profile  # noqa: E402

NOTES = os.path.join(HERE, os.pardir, "docs", "notes")
TB, TU, TC = 4.0, 25.0, 36.0
CHILL_LOW_C, CHILL_HIGH_C = 0.0, 7.2
FROST_C = -2.2
FROST_DAYS = 14
SEASON_DAYS = 240                    # November to June: bloom after this is no bloom
#: Chill counts until the end of March (end of September south): a requirement not met
#: by then is a winter that fell short, whatever bloom straggles out after it.
CHILL_DAYS = 151


def gdh_weight(t: float) -> float:
    """Anderson et al. (1986), as chillR implements it: a rising half-cosine from the
    base to the optimum, a falling quarter-cosine from there to the ceiling."""
    if TB <= t <= TU:
        return (TU - TB) / 2.0 * (1.0 + math.cos(math.pi + math.pi * (t - TB) / (TU - TB)))
    if TU < t <= TC:
        return (TU - TB) * (1.0 + math.cos(math.pi / 2.0 + math.pi / 2.0 * (t - TU) / (TC - TU)))
    return 0.0


def central(value: str):
    """A published requirement's middle: a range's midpoint, a mean without its spread,
    the bound of "<300". None for none, an open bound, or a word."""
    v = (value or "").strip().replace("−", "-")
    if v in ("", "-", "–") or v.startswith(">"):
        return None
    if v.startswith("<"):
        return float(v[1:].strip())
    if m := re.fullmatch(r"([\d.]+)\s*±\s*[\d.]+", v):
        return float(m.group(1))
    if m := re.fullmatch(r"([\d.]+)\s*[–-]\s*([\d.]+)", v):
        return (float(m.group(1)) + float(m.group(2))) / 2.0
    try:
        return float(v)
    except ValueError:
        return None


def daily_units(days: list) -> list:
    """Per day: (chill hours, growing degree hours), from 24 sine hours."""
    out = []
    for _, v in days:
        if "T2M_MIN" not in v or "T2M_MAX" not in v:
            out.append((0.0, 0.0))
            continue
        hours = dssat_crops.hourly(v["T2M_MIN"], v["T2M_MAX"])
        out.append((sum(1.0 for t in hours if CHILL_LOW_C < t <= CHILL_HIGH_C),
                    sum(gdh_weight(t) for t in hours)))
    return out


def season_starts(days: list, north: bool) -> list:
    """Index of each November 1 (May 1 south) with a full season after it."""
    month = 11 if north else 5
    return [i for i, (d, _) in enumerate(days)
            if d.month == month and d.day == 1 and i + SEASON_DAYS + FROST_DAYS < len(days)]


def winter_chill(days: list, lat: float, units: list | None = None) -> list:
    """Each winter's chill hours, November through March (May through September south)."""
    units = units or daily_units(days)
    return [sum(units[i][0] for i in range(s, s + CHILL_DAYS)) for s in season_starts(days, lat >= 0)]


def bloom(units: list, days: list, start: int, chill_need: float, heat_need: float):
    """-> (bloom index or None, frost after bloom, chill met by the end of March)."""
    chill = heat = 0.0
    met = met_in_time = False
    for i in range(start, start + SEASON_DAYS):
        ch, gd = units[i]
        if not met:
            chill += ch
            if chill >= chill_need:
                met = True                    # heat counts from the next day
                met_in_time = i < start + CHILL_DAYS
            continue
        heat += gd
        if heat >= heat_need:
            frost = any(days[j][1].get("T2M_MIN", 99.0) <= FROST_C
                        for j in range(i, min(len(days), i + FROST_DAYS + 1)))
            return i, frost, met_in_time
    return None, False, met_in_time


def cultivars(requirements: list) -> list:
    """(crop, cultivar, chill hours, heat GDH) for each row carrying both numbers; a
    cultivar measured in several studies keeps each, as a separate estimate."""
    out = []
    for r in requirements:
        ch, gd = central(r["chill_hours"]), central(r["heat_gdh"])
        if ch is not None and gd is not None:
            out.append((r["crop"], r["cultivar"], ch, gd))
    return out


def simulate(requirements: list, days: list, lat: float) -> list:
    """Per cultivar estimate: its median bloom, as days after the season's start
    (November 1, or May 1 south), and the shares of seasons with a frost after bloom
    and with chill never met. Days, not dates, so a December bloom and a February one
    do not average to a day in October."""
    units = daily_units(days)
    starts = season_starts(days, lat >= 0)
    out = []
    for crop, name, ch, gd in cultivars(requirements):
        blooms, frosts, unmet = [], 0, 0
        for s in starts:
            i, frost, met = bloom(units, days, s, ch, gd)
            unmet += not met
            if i is None:
                continue
            blooms.append(i - s)
            frosts += frost
        out.append({"crop": crop, "cultivar": name, "chill_hours": ch, "heat_gdh": gd,
                    "bloom_day": int(statistics.median(blooms)) if blooms else None,
                    "frost_share": round(frosts / len(starts), 2) if starts else None,
                    "unmet_share": round(unmet / len(starts), 2) if starts else None,
                    "seasons": len(starts)})
    return out


def summarize(per_cultivar: list) -> dict:
    """Per crop: estimates, the median and spread of bloom dates, and the median frost
    share — in years of ten — across its cultivars."""
    by = {}
    for r in per_cultivar:
        by.setdefault(r["crop"], []).append(r)
    out = {}
    for crop, rows in by.items():
        bl = sorted(r["bloom_day"] for r in rows if r["bloom_day"] is not None)
        out[crop] = {"estimates": len(rows),
                     "bloom_early": bl[int(0.1 * (len(bl) - 1))] if bl else None,
                     "bloom_median": bl[len(bl) // 2] if bl else None,
                     "bloom_late": bl[int(0.9 * (len(bl) - 1))] if bl else None,
                     "frost_in_10": round(10 * statistics.median(r["frost_share"] for r in rows)),
                     "unmet": sum(1 for r in rows if (r["unmet_share"] or 0) > 0.2)}
    return out


def as_date(day: int, north: bool = True) -> str:
    """Days after the season's start, as a month and day."""
    return (_dt.date(2001, 11 if north else 5, 1) + _dt.timedelta(days=day)).strftime("%b %d")


def read_csv(path: str) -> list:
    with open(path, encoding="utf-8") as h:
        return list(csv.DictReader(line for line in h if not line.startswith("#")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--warm", type=float, default=0.0, help="shift every day this many °C")
    ap.add_argument("--out", help="per-cultivar CSV")
    args = ap.parse_args(argv)
    days = site_profile.days_of(site_profile.fetch_power(args.lat, args.lon, 1991, 2020,
                                                         os.path.join(args.cache, "power")))
    days = site_profile.shift(days, args.warm)
    rows = simulate(read_csv(os.path.join(NOTES, "chill-requirements.csv")), days, args.lat)
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    for crop, s in sorted(summarize(rows).items()):
        if s["bloom_median"] is None:
            print(f"  {crop:<24} {s['estimates']:>3} estimates: no bloom")
            continue
        north = args.lat >= 0
        print(f"  {crop:<24} {s['estimates']:>3} estimates: bloom {as_date(s['bloom_early'], north)}–"
              f"{as_date(s['bloom_late'], north)} (median {as_date(s['bloom_median'], north)}); frost after bloom in "
              f"{s['frost_in_10']} years of 10" + (f"; chill unmet for {s['unmet']}" if s["unmet"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

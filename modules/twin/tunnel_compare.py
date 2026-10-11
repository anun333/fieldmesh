#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Q28 step 1: the virtual farm's tunnel against GreenLight configured as one, on the same
real weather (McAllister Farm, NASA POWER hourly, spring and July 2025).

    python3 tunnel_compare.py --run      # in this module's environment (requirements.txt):
                                         # runs GreenLight and writes data/greenlight-*.csv
    python3 tunnel_compare.py            # anywhere: compares from those files

GreenLight's hourly inside air is kept in data/, so the comparison reruns without it.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import twin as T  # noqa: E402

LON = -86.5914
PERIODS = {"spring": "mcallister-2025-spring-hourly.csv", "july": "mcallister-2025-july-hourly.csv"}
SOIL_C = 16.05          # the 2025 mean air temperature, standing for the soil at 2 m
ELEVATION_M = 243.0


def data(name: str) -> str:
    return os.path.join(HERE, "data", name)


def greenlight_file(period: str, cover: str) -> str:
    return data(f"greenlight-tunnel-{cover}-{period}.csv")


def run(period: str, cover: str) -> None:
    hours = T.read_hours(data(PERIODS[period]))
    with tempfile.TemporaryDirectory() as d:
        weather = os.path.join(d, "weather.csv")
        T.greenlight_weather(hours, weather, soil_c=SOIL_C, elevation_m=ELEVATION_M)
        days = (hours[-1].when - hours[0].when).total_seconds() / 86400.0
        out = T.run_greenlight(weather, days, os.path.join(d, "out.csv"), cover=cover)
        inside = T.read_greenlight(out, hours[0].when)
    with open(greenlight_file(period, cover), "w", encoding="utf-8", newline="") as h:
        h.write(f"# GreenLight 2.0.5 (BSD-3-Clause-Clear), Vanthoor (2011) greenhouse and crop as an "
                f"unheated single-poly tunnel, {cover} film (modules/twin/twin.py); hourly mean inside air\n")
        w = csv.writer(h)
        w.writerow(["utc", "t_air_c"])
        for when in sorted(inside):
            w.writerow([when.strftime("%Y-%m-%dT%H:%MZ"), round(inside[when], 3)])


def read_inside(path: str) -> dict:
    out = {}
    with open(path, encoding="utf-8") as h:
        for r in csv.DictReader(line for line in h if not line.startswith("#")):
            out[_dt.datetime.strptime(r["utc"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=T.UTC)] = float(r["t_air_c"])
    return out


def compare() -> dict:
    result = {}
    for period, name in PERIODS.items():
        hours = T.read_hours(data(name))
        models = {"virtual farm": T.run_sim_tunnel(hours, lon=LON, sky=False),
                  "virtual farm, sky known": T.run_sim_tunnel(hours, lon=LON),
                  "virtual farm, sky known, clear film": T.run_sim_tunnel(hours, lon=LON, film="clear")}
        for cover in T.COVERS:
            path = greenlight_file(period, cover)
            if os.path.exists(path):
                models[f"GreenLight, {cover} film"] = read_inside(path)
        outside = {x.when: x.t for x in hours}
        result[period] = {}
        for label, inside in models.items():
            rows = T.nights(hours, inside, lon=LON)
            common = [w for w in inside if w in outside]
            day_max = {}
            for w in common:
                day = (w + _dt.timedelta(hours=LON / 15.0)).date()
                day_max[day] = max(day_max.get(day, -99), inside[w] - outside[w])
            result[period][label] = {**T.summarise(rows),
                                     "mean_day_excess_c": round(sum(day_max.values()) / len(day_max), 2),
                                     "hottest_inside_c": round(max(inside[w] for w in common), 1)}
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run GreenLight first (needs requirements.txt)")
    args = ap.parse_args(argv)
    if args.run:
        for period in PERIODS:
            for cover in T.COVERS:
                run(period, cover)
                print(f"ran GreenLight: {period}, {cover}", flush=True)
    print(json.dumps(compare(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

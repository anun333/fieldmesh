#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A site's climate change by month, from five CMIP6 models (NASA NEX-GDDP-CMIP6, CC0).

    python3 modules/advise/cmip6.py 35.06445 -86.59137 --cache DIR [--scenario ssp245]

The advisor's 2050s run first shifted every day by one number (`site_profile.shift`):
honest about its level, blind to its shape. Summer and winter do not warm alike, nights
and days do not, and rain changes by season. NASA's NEX-GDDP-CMIP6 downscales CMIP6 models
to a quarter of a degree, daily and bias-corrected, and its THREDDS service hands out one
grid cell at a time; since September 2022 all of it is CC0.

For each model, this compares 2041–2070 under a scenario with the same model's 1991–2014
(the historical runs end in 2014), month by month: the change in mean daily maximum and
minimum temperature, and the ratio of rain. The median of the five models, month by month,
is applied to the site's own thirty years (`shift_monthly`) — the delta method, as before,
but by month and separately for days and nights. Today's weather stays the weather; its
level moves by what the models agree on.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import os
import re
import statistics
import time
import urllib.error
import urllib.request

THREDDS = "https://ds.nccs.nasa.gov/thredds"
ROOT = "AMES/NEX/GDDP-CMIP6"
MODELS = ("ACCESS-CM2", "GFDL-ESM4", "MPI-ESM1-2-HR", "MRI-ESM2-0", "NorESM2-MM")
MEMBER = "r1i1p1f1"
VARIABLES = ("tasmax", "tasmin", "pr")
HISTORICAL = (1991, 2014)
FUTURE = (2041, 2070)


def scenario_name(code: str) -> str:
    """"ssp245" as it is written: SSP2-4.5."""
    m = re.fullmatch(r"ssp(\d)(\d)(\d)", code.lower())
    return f"SSP{m.group(1)}-{m.group(2)}.{m.group(3)}" if m else code.upper()


def _get(url: str, retries: int = 4) -> str:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "librefarm/0.1"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def files(model: str, scenario: str, variable: str, cache: str) -> dict:
    """{year: file name} from the THREDDS catalog, cached: names differ by grid and version."""
    path = os.path.join(cache, f"catalog-{model}-{scenario}-{variable}.json")
    if os.path.exists(path):
        return {int(k): v for k, v in json.load(open(path)).items()}
    html = _get(f"{THREDDS}/catalog/{ROOT}/{model}/{scenario}/{MEMBER}/{variable}/catalog.html")
    out = {}
    for m in re.finditer(rf"({variable}_day_{re.escape(model)}_{scenario}_{MEMBER}_\w+?_(\d{{4}})(?:_v([\d.]+))?\.nc)", html):
        year, version = int(m.group(2)), m.group(3) or "0"
        if year not in out or version > out[year][1]:
            out[year] = (m.group(1), version)
    out = {y: v[0] for y, v in out.items()}
    os.makedirs(cache, exist_ok=True)
    json.dump(out, open(path, "w"))
    return out


def point_year(model, scenario, variable, year, lat, lon, cache) -> list:
    """[(month, value)] for every day of a year at the grid cell nearest the point, in the
    file's units (K for temperature, kg m-2 s-1 for rain)."""
    path = os.path.join(cache, f"{model}-{scenario}-{variable}-{year}-{lat:.3f}-{lon:.3f}.csv")
    if not os.path.exists(path):
        name = files(model, scenario, variable, cache)[year]
        url = (f"{THREDDS}/ncss/grid/{ROOT}/{model}/{scenario}/{MEMBER}/{variable}/{name}"
               f"?var={variable}&latitude={lat}&longitude={lon % 360:.4f}"
               f"&time_start={year}-01-01T00:00:00Z&time_end={year}-12-31T23:59:59Z&accept=csv")
        text = _get(url)
        with open(path, "w", encoding="utf-8") as h:
            h.write(text)
    out = []
    with open(path, encoding="utf-8") as h:
        for row in csv.reader(h):
            if not row or not row[0][:4].isdigit():
                continue
            out.append((int(row[0][5:7]), float(row[-1])))
    return out


def monthly_means(model, scenario, years, lat, lon, cache) -> dict:
    """{variable: {month: mean}}: temperatures in °C, rain in mm a day."""
    out = {}
    for var in VARIABLES:
        by_month = {m: [] for m in range(1, 13)}
        for year in range(years[0], years[1] + 1):
            for month, v in point_year(model, scenario, var, year, lat, lon, cache):
                by_month[month].append(v - 273.15 if var.startswith("tas") else v * 86400.0)
        out[var] = {m: statistics.mean(v) for m, v in by_month.items() if v}
    return out


def deltas(lat: float, lon: float, cache: str, scenario: str = "ssp245",
           models=MODELS, future=FUTURE, workers: int = 6) -> dict:
    """Per month: the five-model median change in daily maximum and minimum (°C) and the
    ratio of rain, with every model's own numbers kept for the record."""
    # The server answers a point-year in about half a minute; fetch several at once, each
    # cached, so the whole set is an hour rather than an afternoon.
    from concurrent.futures import ThreadPoolExecutor
    jobs = [(model, sc, var, year) for model in models
            for sc, years in (("historical", HISTORICAL), (scenario, future))
            for var in VARIABLES for year in range(years[0], years[1] + 1)]
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda j: point_year(*j, lat, lon, cache), jobs))
    per_model = {}
    for model in models:
        hist = monthly_means(model, "historical", HISTORICAL, lat, lon, cache)
        fut = monthly_means(model, scenario, future, lat, lon, cache)
        per_model[model] = {m: {"tmax": fut["tasmax"][m] - hist["tasmax"][m],
                                "tmin": fut["tasmin"][m] - hist["tasmin"][m],
                                "rain": fut["pr"][m] / hist["pr"][m] if hist["pr"][m] else 1.0}
                            for m in range(1, 13)}
    median = {m: {k: statistics.median(per_model[mod][m][k] for mod in models)
                  for k in ("tmax", "tmin", "rain")} for m in range(1, 13)}
    return {"scenario": scenario, "future": list(future), "historical": list(HISTORICAL),
            "models": list(models), "median": median, "per_model": per_model}


def shift_monthly(days: list, monthly: dict) -> list:
    """The site's days with each month's change applied: daily maximum and minimum moved by
    their own deltas, the mean by their average, rain scaled. Like `site_profile.shift`,
    but by month and by time of day."""
    out = []
    for date, v in days:
        d = monthly[date.month]
        w = dict(v)
        if "T2M_MAX" in w:
            w["T2M_MAX"] = w["T2M_MAX"] + d["tmax"]
        if "T2M_MIN" in w:
            w["T2M_MIN"] = w["T2M_MIN"] + d["tmin"]
        if "T2M" in w:
            w["T2M"] = w["T2M"] + (d["tmax"] + d["tmin"]) / 2.0
        if "PRECTOTCORR" in w:
            w["PRECTOTCORR"] = w["PRECTOTCORR"] * d["rain"]
        out.append((date, w))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--scenario", default="ssp245")
    ap.add_argument("--out", help="write the deltas as JSON here")
    args = ap.parse_args(argv)
    d = deltas(args.lat, args.lon, args.cache, args.scenario)
    print(f"{args.scenario}, {FUTURE[0]}-{FUTURE[1]} against {HISTORICAL[0]}-{HISTORICAL[1]}, "
          f"median of {', '.join(d['models'])}")
    print(f"{'month':>6} {'Δ max °C':>9} {'Δ min °C':>9} {'rain ×':>7}")
    for m in range(1, 13):
        x = d["median"][m]
        print(f"{calendar.month_abbr[m]:>6} {x['tmax']:>+9.2f} {x['tmin']:>+9.2f} {x['rain']:>7.2f}")
    if args.out:
        json.dump(d, open(args.out, "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

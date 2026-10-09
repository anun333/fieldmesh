#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""What a farm's site offers: climate, sun, soil and erosion risk, for one point.

    python3 tools/site_profile.py 35.0645 -86.5914 --cache /path/to/cache --json out.json

The site side of docs/notes/plant-conditions.md. Climate and sun come from NASA POWER's
daily agroclimatology record for the point (CC BY 4.0 — cite NASA POWER), 1991–2020 by
default, the same thirty years as the current climate normals; soil comes from the USDA
soil survey via `soil_survey.py`, in the United States only.

Several numbers are estimates from daily data, and say so:

* **chill hours** — hours below 7.2 °C (45 °F) in winter, from each day's minimum and
  maximum on a sine curve; an hourly record would be better;
* **heat-stress days** — two bounds: days whose *average* temperature–humidity index
  reaches the threshold (errs low), and days whose peak likely does, from the day's
  maximum with its mean humidity (errs high, since afternoon humidity is lower);
* **cold extremes and frost dates** — POWER's temperatures are averages over a grid
  cell tens of kilometres across, so its extremes are milder than a field's: winter
  lows run warm by roughly half a hardiness zone or more, and frost dates are optimistic.
  Compare with the USDA hardiness map, and treat a plant at its cold limit as at risk;
* **daily light** — photosynthetically active photons from total solar radiation by a
  fixed factor;
* **erosion** — RUSLE with the rainfall factor estimated from annual rainfall (Renard and
  Freimund, 1994), a slope of the survey's representative steepness and the standard
  22.1 m length, and bare soil: the potential before cover and practice reduce it.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import math
import os
import statistics
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soil_survey  # noqa: E402

POWER = ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters="
         "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,ALLSKY_SFC_SW_DWN,RH2M&community=AG"
         "&longitude={lon}&latitude={lat}&start={start}0101&end={end}1231&format=JSON")
FILL = -999.0
#: Photosynthetic photons per unit of total solar energy: about 48% of shortwave energy
#: is PAR, at about 4.57 µmol per joule.
DLI_PER_MJ = 2.1
CHILL_BELOW_C = 7.2
THI_DAIRY_ONSET = 72.0
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ------------------------------------------------------------------- weather

def fetch_power(lat: float, lon: float, start: int, end: int, cache: str | None) -> dict:
    url = POWER.format(lat=round(lat, 4), lon=round(lon, 4), start=start, end=end)
    file = None
    if cache:
        os.makedirs(cache, exist_ok=True)
        file = os.path.join(cache, hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")
        if os.path.exists(file):
            with open(file, encoding="utf-8") as h:
                return json.load(h)
    with urllib.request.urlopen(url, timeout=300) as response:
        doc = json.loads(response.read().decode("utf-8"))
    if file:
        with open(file, "w", encoding="utf-8") as h:
            json.dump(doc, h)
    return doc


def days_of(doc: dict) -> list:
    """[(date, {T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, ALLSKY_SFC_SW_DWN, RH2M})], with
    fill values left out per parameter."""
    params = doc["properties"]["parameter"]
    dates = sorted(next(iter(params.values())))
    out = []
    for d in dates:
        values = {k: v[d] for k, v in params.items() if v.get(d, FILL) != FILL}
        out.append((_dt.date(int(d[:4]), int(d[4:6]), int(d[6:])), values))
    return out


# --------------------------------------------------------------- the numbers

def day_length_h(lat: float, day_of_year: int) -> float:
    """Hours from sunrise to sunset, by solar declination; 0 or 24 in polar night and day."""
    decl = math.radians(23.44) * math.sin(2 * math.pi * (day_of_year - 81) / 365.0)
    x = -math.tan(math.radians(lat)) * math.tan(decl)
    if x >= 1:
        return 0.0
    if x <= -1:
        return 24.0
    return 2 * math.degrees(math.acos(x)) / 15.0


def hours_below(tmin: float, tmax: float, threshold: float) -> float:
    """Hours of a day below `threshold`, the day's temperature a sine between min and max."""
    if tmax <= threshold:
        return 24.0
    if tmin >= threshold:
        return 0.0
    mean, amp = (tmax + tmin) / 2.0, (tmax - tmin) / 2.0
    return 24.0 * (0.5 + math.asin((threshold - mean) / amp) / math.pi)


def thi(temp_c: float, rh: float) -> float:
    """Temperature–humidity index (NRC 1971), the usual livestock heat-stress measure."""
    return (1.8 * temp_c + 32) - (0.55 - 0.0055 * rh) * (1.8 * temp_c - 26)


def gdd(tmin: float, tmax: float, base: float = 10.0, cap: float = 30.0) -> float:
    """Growing degree days by the 86/50 method: maximum capped at 30 °C, minimum floored
    at the 10 °C base."""
    hi, lo = min(tmax, cap), max(tmin, base)
    return max(0.0, (hi + max(lo, min(hi, lo))) / 2.0 - base) if hi > base else 0.0


def hardiness_zone(mean_annual_min_c: float) -> str:
    """USDA plant hardiness zone from the average annual extreme minimum: 10 °F bands
    from −60 °F, each halved into a and b."""
    f = mean_annual_min_c * 9 / 5 + 32
    zone = int(math.floor((f + 60) / 10)) + 1
    half = "a" if (f + 60) % 10 < 5 else "b"
    zone = max(1, min(13, zone))
    return f"{zone}{half}"


def koppen(temps: list, precs: list, lat: float) -> str:
    """Köppen–Geiger class from twelve monthly mean temperatures (°C) and precipitation
    totals (mm), by Peel, Finlayson and McMahon (2007)."""
    mat, map_ = sum(temps) / 12, sum(precs)
    thot, tcold = max(temps), min(temps)
    summer = [3, 4, 5, 6, 7, 8] if lat >= 0 else [9, 10, 11, 0, 1, 2]
    winter = [m for m in range(12) if m not in summer]
    p_summer = sum(precs[m] for m in summer)
    p_winter = sum(precs[m] for m in winter)
    if p_winter >= 0.7 * map_:
        p_th = 2 * mat
    elif p_summer >= 0.7 * map_:
        p_th = 2 * mat + 28
    else:
        p_th = 2 * mat + 14
    if thot < 10:
        return "ET" if thot > 0 else "EF"
    if map_ < 10 * p_th:
        return ("BW" if map_ < 5 * p_th else "BS") + ("h" if mat >= 18 else "k")
    pdry = min(precs)
    if tcold >= 18:
        if pdry >= 60:
            return "Af"
        return "Am" if pdry >= 100 - map_ / 25 else "Aw"
    first = "C" if tcold > 0 else "D"
    ps_dry, ps_wet = min(precs[m] for m in summer), max(precs[m] for m in summer)
    pw_dry, pw_wet = min(precs[m] for m in winter), max(precs[m] for m in winter)
    if ps_dry < 40 and ps_dry < pw_wet / 3:
        second = "s"
    elif pw_dry < ps_wet / 10:
        second = "w"
    else:
        second = "f"
    warm_months = sum(1 for t in temps if t >= 10)
    if thot >= 22:
        third = "a"
    elif warm_months >= 4:
        third = "b"
    elif first == "D" and tcold <= -38:
        third = "d"
    else:
        third = "c"
    return first + second + third


def rainfall_erosivity(annual_mm: float) -> float:
    """RUSLE R (MJ·mm/(ha·h·yr)) from annual rainfall — Renard and Freimund (1994), fitted
    on US data: a first estimate where no erosivity map is at hand."""
    if annual_mm <= 850:
        return 0.0483 * annual_mm ** 1.61
    return 587.8 - 1.219 * annual_mm + 0.004105 * annual_mm ** 2


def ls_factor(slope_pct: float, length_m: float = 22.13) -> float:
    """RUSLE slope length and steepness (McCool et al.)."""
    theta = math.atan(slope_pct / 100.0)
    s = 10.8 * math.sin(theta) + 0.03 if slope_pct < 9 else 16.8 * math.sin(theta) - 0.50
    beta = (math.sin(theta) / 0.0896) / (3 * math.sin(theta) ** 0.8 + 0.56) if theta else 0.0
    m = beta / (1 + beta)
    return (length_m / 22.13) ** m * s


# ------------------------------------------------------------------- profile

def climate(days: list, lat: float) -> dict:
    north = lat >= 0
    by_month = collections.defaultdict(lambda: collections.defaultdict(list))
    years = sorted({d.year for d, _ in days})
    month_totals = collections.defaultdict(float)
    for d, v in days:
        for k, x in v.items():
            by_month[d.month][k].append(x)
        if "PRECTOTCORR" in v:
            month_totals[(d.year, d.month)] += v["PRECTOTCORR"]
    monthly = []
    for m in range(1, 13):
        bm = by_month[m]
        totals = [month_totals[(y, m)] for y in years if (y, m) in month_totals]
        mid = _dt.date(2001, m, 15).timetuple().tm_yday
        sw = statistics.mean(bm["ALLSKY_SFC_SW_DWN"]) if bm["ALLSKY_SFC_SW_DWN"] else None
        monthly.append({
            "month": MONTHS[m - 1],
            "mean_c": round(statistics.mean(bm["T2M"]), 1),
            "mean_max_c": round(statistics.mean(bm["T2M_MAX"]), 1),
            "mean_min_c": round(statistics.mean(bm["T2M_MIN"]), 1),
            "rain_mm": round(statistics.mean(totals), 0) if totals else None,
            "solar_mj_m2_day": round(sw, 1) if sw is not None else None,
            "daily_light_mol_m2_est": round(sw * DLI_PER_MJ, 0) if sw is not None else None,
            "day_length_h": round(day_length_h(lat, mid), 1),
            "humidity_pct": round(statistics.mean(bm["RH2M"]), 0) if bm["RH2M"] else None})

    # A "season year" runs July to June in the north and January to December in the
    # south, so one winter's frosts are never split between two years.
    def season(d):
        return d.year if not north else (d.year if d.month >= 7 else d.year - 1)

    annual_min = collections.defaultdict(lambda: math.inf)
    for d, v in days:
        if "T2M_MIN" in v:
            annual_min[season(d)] = min(annual_min[season(d)], v["T2M_MIN"])
    winters = [t for y, t in annual_min.items() if t < math.inf]
    mean_extreme_min = statistics.mean(winters)

    last_spring, first_fall, ffd = [], [], []
    for y in years:
        grow = [(d, v) for d, v in days if (d.year == y if north else season(d) == y)]
        if len(grow) < 300:
            continue
        mid = _dt.date(y, 7, 1) if north else _dt.date(y + 1, 1, 1)
        frosts = [d for d, v in grow if v.get("T2M_MIN", 99) <= 0.0]
        spring = [d for d in frosts if d < mid]
        fall = [d for d in frosts if d >= mid]
        start = max(spring) if spring else None
        end = min(fall) if fall else None
        if start:
            last_spring.append(start.timetuple().tm_yday)
        if end:
            first_fall.append(end.timetuple().tm_yday)
        span_start = start or (mid - _dt.timedelta(days=182))
        span_end = end or (mid + _dt.timedelta(days=183))
        ffd.append((span_end - span_start).days - 1)

    def as_date(doy):
        return (_dt.date(2001, 1, 1) + _dt.timedelta(days=int(round(doy)) - 1)).strftime("%b %d")

    gdd_year = collections.defaultdict(float)
    chill = collections.defaultdict(float)
    heat_days = collections.defaultdict(int)
    heat_days_mean = collections.defaultdict(int)
    hot_days = collections.defaultdict(int)
    for d, v in days:
        if "T2M_MIN" in v and "T2M_MAX" in v:
            gdd_year[d.year] += gdd(v["T2M_MIN"], v["T2M_MAX"])
            winter = (d.month in (11, 12, 1, 2)) if north else (d.month in (5, 6, 7, 8))
            if winter:
                chill[season(d)] += hours_below(v["T2M_MIN"], v["T2M_MAX"], CHILL_BELOW_C)
            if "RH2M" in v and thi(v["T2M_MAX"], v["RH2M"]) >= THI_DAIRY_ONSET:
                heat_days[d.year] += 1
            if "RH2M" in v and "T2M" in v and thi(v["T2M"], v["RH2M"]) >= THI_DAIRY_ONSET:
                heat_days_mean[d.year] += 1
            if v["T2M_MAX"] >= 35:
                hot_days[d.year] += 1
    full = [y for y in years if sum(1 for d, _ in days if d.year == y) >= 360]
    annual_rain = [sum(month_totals[(y, m)] for m in range(1, 13)) for y in full]
    annual_mean = {y: statistics.mean(v["T2M"] for d, v in days if d.year == y and "T2M" in v)
                   for y in full}
    half = len(full) // 2
    early, late = full[:half], full[half:]
    temps = [m["mean_c"] for m in monthly]
    precs = [m["rain_mm"] for m in monthly]
    return {
        "period": f"{years[0]}–{years[-1]}",
        "koppen": koppen(temps, precs, lat),
        "annual_mean_c": round(statistics.mean(annual_mean.values()), 1),
        "annual_rain_mm": round(statistics.mean(annual_rain), 0),
        "annual_rain_in": round(statistics.mean(annual_rain) / 25.4, 1),
        "mean_annual_extreme_min_c": round(mean_extreme_min, 1),
        "mean_annual_extreme_min_f": round(mean_extreme_min * 9 / 5 + 32, 0),
        "hardiness_zone": hardiness_zone(mean_extreme_min),
        "last_spring_frost_median": as_date(statistics.median(last_spring)) if last_spring else None,
        "first_fall_frost_median": as_date(statistics.median(first_fall)) if first_fall else None,
        "frost_free_days_median": int(statistics.median(ffd)) if ffd else 365,
        "frost_free_days_8_in_10": int(sorted(ffd)[int(0.2 * len(ffd))]) if ffd else 365,
        "growing_degree_days_c": round(statistics.mean(gdd_year[y] for y in full), 0),
        "chill_hours_est": round(statistics.mean(chill.values()), 0) if chill else 0,
        "heat_stress_days_dairy_est": {
            "low": round(statistics.mean(heat_days_mean.get(y, 0) for y in full), 0),
            "high": round(statistics.mean(heat_days.get(y, 0) for y in full), 0)},
        "caution": "POWER grid-cell temperatures: extremes milder and frost dates "
                   "earlier in spring and later in autumn than in a field",
        "days_over_35c": round(statistics.mean(hot_days.get(y, 0) for y in full), 1),
        "trend": {"first_half": f"{early[0]}–{early[-1]}", "second_half": f"{late[0]}–{late[-1]}",
                  "mean_c_change": round(statistics.mean(annual_mean[y] for y in late)
                                         - statistics.mean(annual_mean[y] for y in early), 2),
                  "rain_mm_change": round(statistics.mean(annual_rain[full.index(y)] for y in late)
                                          - statistics.mean(annual_rain[full.index(y)] for y in early), 0)},
        "monthly": monthly,
    }


def soil_and_erosion(lat: float, lon: float, annual_rain_mm: float) -> dict:
    soil = soil_survey.query(lat, lon)
    if not soil["horizons"]:
        return {"soil": None, "erosion": None}
    top = soil["horizons"][0]
    texture = soil_survey.texture(top) if top.get("clay_pct") is not None else None
    out = {"soil": {"map_unit": soil["map_unit"], "component": soil["component"],
                    "state": soil.get("state"),
                    "drainage": soil.get("drainage"), "slope_pct": soil.get("slope_pct"),
                    "topsoil_texture": texture, "topsoil_sand_pct": top.get("sand_pct"),
                    "topsoil_clay_pct": top.get("clay_pct"), "topsoil_ph": top.get("ph"),
                    "topsoil_organic_matter_pct": top.get("organic_matter_pct"),
                    "topsoil_ec_ds_per_m": top.get("ec_ds_per_m"),
                    "available_water_m3_m3": (round(top["field_capacity"] - top["wilting_point"], 3)
                                              if top.get("field_capacity") and top.get("wilting_point")
                                              else None),
                    "source": "USDA NRCS SSURGO via Soil Data Access"},
           "erosion": None}
    k, slope = top.get("erodibility_k"), soil.get("slope_pct")
    if k is not None and slope is not None:
        r = rainfall_erosivity(annual_rain_mm)
        ls = ls_factor(slope)
        bare = r * (k * 0.1317) * ls
        t = soil.get("tolerable_loss_t_per_acre")
        out["erosion"] = {"r_est": round(r, 0), "k": k, "ls": round(ls, 2),
                          "bare_soil_loss_t_ha_yr_est": round(bare, 1),
                          "tolerable_t_ha_yr": round(t * 2.2417, 1) if t else None,
                          "times_tolerable_if_bare": round(bare / (t * 2.2417), 1) if t else None}
    return out


def profile(lat: float, lon: float, start: int = 1991, end: int = 2020,
            cache: str | None = None, soil: bool = True) -> dict:
    doc = fetch_power(lat, lon, start, end, cache)
    out = {"lat": lat, "lon": lon,
           "climate": climate(days_of(doc), lat),
           "sources": {"climate": "NASA POWER daily agroclimatology, CC BY 4.0"}}
    if soil:
        out.update(soil_and_erosion(lat, lon, out["climate"]["annual_rain_mm"]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--start", type=int, default=1991)
    ap.add_argument("--end", type=int, default=2020)
    ap.add_argument("--cache")
    ap.add_argument("--json", help="write the profile here")
    ap.add_argument("--no-soil", action="store_true")
    args = ap.parse_args(argv)
    p = profile(args.lat, args.lon, args.start, args.end, args.cache, not args.no_soil)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as h:
            json.dump(p, h, indent=1)
    c = p["climate"]
    print(f"{args.lat}, {args.lon}  ·  {c['period']}  ·  Köppen {c['koppen']}  ·  zone {c['hardiness_zone']}")
    print(f"  mean {c['annual_mean_c']} °C; rain {c['annual_rain_mm']:.0f} mm ({c['annual_rain_in']} in); "
          f"extreme minimum {c['mean_annual_extreme_min_c']} °C on average")
    print(f"  frost: last {c['last_spring_frost_median']}, first {c['first_fall_frost_median']}; "
          f"frost-free {c['frost_free_days_median']} days (at least {c['frost_free_days_8_in_10']} in 8 years of 10)")
    print(f"  growing degree days {c['growing_degree_days_c']:.0f} (°C, base 10); chill hours ≈ {c['chill_hours_est']:.0f}; "
          f"heat-stress days for dairy {c['heat_stress_days_dairy_est']['low']:.0f}–{c['heat_stress_days_dairy_est']['high']:.0f}; days over 35 °C {c['days_over_35c']}")
    print(f"  caution: {c['caution']}")
    t = c["trend"]
    print(f"  within the record: {t['second_half']} was {t['mean_c_change']:+.2f} °C and "
          f"{t['rain_mm_change']:+.0f} mm/yr against {t['first_half']}")
    print("  month   mean  max   min   rain  sun MJ  light mol  day h")
    for m in c["monthly"]:
        print(f"  {m['month']:<5}{m['mean_c']:>6}{m['mean_max_c']:>6}{m['mean_min_c']:>6}{m['rain_mm']:>7.0f}"
              f"{m['solar_mj_m2_day']:>8}{m['daily_light_mol_m2_est']:>10.0f}{m['day_length_h']:>7}")
    if p.get("soil"):
        s = p["soil"]
        print(f"  soil: {s['map_unit']} — {s['drainage']}, {s['slope_pct']}% slope; topsoil {s['topsoil_texture']}, "
              f"pH {s['topsoil_ph']}, organic matter {s['topsoil_organic_matter_pct']}%, available water {s['available_water_m3_m3']}")
    if p.get("erosion"):
        e = p["erosion"]
        print(f"  erosion if bare ≈ {e['bare_soil_loss_t_ha_yr_est']} t/ha/yr against a tolerable {e['tolerable_t_ha_yr']} "
              f"({e['times_tolerable_if_bare']}×) — R≈{e['r_est']:.0f}, K {e['k']}, LS {e['ls']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

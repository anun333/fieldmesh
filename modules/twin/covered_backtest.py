#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The covered-crop frost watch on the 2025–26 season at McAllister Farm (Q28, step 2).

    python3 -I covered_backtest.py --cache NBM_CACHE --cover thermic   # this module's env
    python3 covered_backtest.py --summary                              # from the saved nights

Each night from mid-October to the end of April: NOAA's National Blend of Models issued
at 00 UTC (6 pm local) — temperature, humidity, wind and cloud cover three-hourly to
dawn — through the twin, after 36 hours of warm-up on what the weather actually did
(NASA POWER hourly). The same night run on what the weather did gives the twin's own
answer with a perfect forecast. Outside, the McAllister SCAN station says what happened.

Two watches are scored, both warning at 0 °C:
* the open-bed frost watch, on NBM's outside low, against the station's outside low;
* the covered-crop watch, on the twin's forecast inside low, against the twin's inside low
  on what the weather did — the best "truth" available while no real tunnel is logged.

A night is a frost at 0 °C or below and a damaging one at −2.2 °C or below, as the open-bed
watch's backtest has it. The question for a tunnel grower is how many of the open-bed
watch's warnings the covered-crop watch spares, and whether it misses a night the tunnel
froze.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "tools"))
import twin as T  # noqa: E402

LAT, LON = 35.0644, -86.5914
SEASON = (_dt.date(2025, 10, 16), _dt.date(2026, 4, 30))
OBSERVED = os.path.join(HERE, "data", "mcallister-2025-26-frost-season-hourly.csv")
LEADS = (3, 6, 9, 12, 15)
NIGHT_H = 14                       # 6 pm to 8 am local standard time
WARN_C, DAMAGE_C = 0.0, -2.2


def results_path(cover: str) -> str:
    return os.path.join(HERE, "data", f"frost-backtest-2025-26-{cover}.csv")


def forecasts(cache: str) -> dict:
    """{issue: {field: [(valid, value)]}} for the 00 UTC runs, NBM's own units."""
    import nbm_verify as NV
    out = {}
    for var in ("temp", "rh", "windspd", "sky"):
        runs = NV.nbm_runs(*SEASON, LAT, LON, cache, hours=(0,), var=var, leads=LEADS)
        for issued, pts in runs.items():
            out.setdefault(issued, {})[var] = [(t, v) for t, v in pts
                                               if (t - issued).total_seconds() / 3600 in LEADS]
    return {k: v for k, v in out.items() if len(v) == 4 and all(len(x) == len(LEADS) for x in v.values())}


def station(cache: str) -> dict:
    import nbm_verify as NV
    rows = NV.scan_hourly("2075:TN:SCAN", _dt.date(2025, 10, 15), _dt.date(2026, 5, 8), -6.0, cache)
    return {t: NV.f_to_c(f) for t, f in rows}


def tonight(issued: _dt.datetime, fc: dict, at_dusk: T.Hour) -> list:
    """The night's hourly weather from the forecast, starting from what the weather was
    at dusk, which is known when the forecast is read."""
    import frostwatch as F
    series = {"t_c": [(issued, at_dusk.t)] + [(t, (v - 32) * 5 / 9) for t, v in fc["temp"]],
              "rh_pct": [(issued, at_dusk.rh)] + fc["rh"],
              "wind_m_s": [(issued, at_dusk.wind)] + [(t, v * F.KNOT) for t, v in fc["windspd"]],
              "cloud": [(issued, at_dusk.lw / (T.SIGMA * (at_dusk.t + 273.15) ** 4) > 0.85 and 0.8 or 0.2)]
                       + [(t, v / 100.0) for t, v in fc["sky"]]}
    return F.forecast_hours(series, lat=LAT, lon=LON, ps_kpa=at_dusk.ps)


def run(cache: str, cover: str) -> None:
    import frostwatch as F
    observed = T.read_hours(OBSERVED)
    by_hour = {h.when: h for h in observed}
    outside = station(cache)
    rows = []
    for issued, fc in sorted(forecasts(cache).items()):
        if issued not in by_hour:
            continue
        dawn = issued + NIGHT_H * F.HOUR
        night_obs = [h for h in observed if issued <= h.when <= dawn]
        scan = [t for w, t in outside.items() if issued <= w <= dawn]
        if len(night_obs) < NIGHT_H or len(scan) < NIGHT_H - 2:
            continue
        try:
            predicted = F.night(observed, tonight(issued, fc, by_hour[issued]), dusk=issued,
                                dawn=dawn, cover=cover)
            actual = F.night(observed, night_obs, dusk=issued, dawn=dawn, cover=cover)
        except RuntimeError as exc:
            print(f"{issued:%Y-%m-%d}: {exc}", flush=True)
            continue
        rows.append({"night": issued.strftime("%Y-%m-%d"),
                     "nbm_outside_low_c": round(min((v - 32) * 5 / 9 for _, v in fc["temp"]), 2),
                     "station_outside_low_c": round(min(scan), 2),
                     "twin_inside_low_forecast_c": predicted["inside_low_c"],
                     "twin_inside_low_actual_c": actual["inside_low_c"]})
        print(f"{rows[-1]['night']} out {rows[-1]['station_outside_low_c']:6.1f} "
              f"in fc {predicted['inside_low_c']:6.1f} in act {actual['inside_low_c']:6.1f}", flush=True)
    with open(results_path(cover), "w", encoding="utf-8", newline="") as h:
        h.write(f"# Covered-crop frost watch backtest, McAllister Farm 2025-26, {cover} film "
                "(modules/twin/covered_backtest.py). NBM 00 UTC (NOAA, public domain); NASA POWER "
                "hourly (CC BY 4.0); SCAN 2075:TN:SCAN (NRCS, public domain).\n")
        w = csv.DictWriter(h, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def read(cover: str) -> list:
    with open(results_path(cover), encoding="utf-8") as h:
        return [{k: (v if k == "night" else float(v)) for k, v in r.items()}
                for r in csv.DictReader(line for line in h if not line.startswith("#"))]


def score(rows: list, warned_key: str, truth_key: str) -> dict:
    out = {"hits": 0, "misses": 0, "false": 0, "quiet": 0, "damaging_missed": 0}
    for r in rows:
        warned, frost = r[warned_key] <= WARN_C, r[truth_key] <= DAMAGE_C
        out["hits" if warned and frost else "misses" if frost else "false" if warned else "quiet"] += 1
        if frost and not warned:
            out["damaging_missed"] += 1
    return out


def summary(cover: str) -> dict:
    rows = read(cover)
    open_bed = score(rows, "nbm_outside_low_c", "station_outside_low_c")
    covered = score(rows, "twin_inside_low_forecast_c", "twin_inside_low_actual_c")
    open_warnings = [r for r in rows if r["nbm_outside_low_c"] <= WARN_C]
    spared = [r for r in open_warnings if r["twin_inside_low_forecast_c"] > WARN_C]
    froze_anyway = [r for r in spared if r["twin_inside_low_actual_c"] <= WARN_C]
    errors = [r["twin_inside_low_forecast_c"] - r["twin_inside_low_actual_c"] for r in rows]
    return {"cover": cover, "nights": len(rows), "open_bed_watch": open_bed,
            "covered_crop_watch": covered,
            "open_bed_warnings": len(open_warnings), "spared_by_the_twin": len(spared),
            "spared_but_the_tunnel_reached_0c": len(froze_anyway),
            "inside_low_forecast_bias_c": round(sum(errors) / len(errors), 2),
            "inside_low_forecast_mae_c": round(sum(abs(e) for e in errors) / len(errors), 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", help="NBM and SCAN cache (tools/nbm_verify.py)")
    ap.add_argument("--cover", default="thermic", choices=sorted(T.COVERS))
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args(argv)
    if not args.summary:
        if not args.cache:
            ap.error("--cache is needed to run")
        run(args.cache, args.cover)
    print(json.dumps(summary(args.cover), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""pyfao56's own irrigation scheduler on recorded summers, saved for the irrigation drill.

pyfao56 (USDA ARS; public domain in the US, CC0 elsewhere) is the FAO-56 dual crop
coefficient water balance with an automatic irrigation scheduler (Thorp, DeJonge and Kukal
2025, Agricultural Water Management 322, 110013). A bed with no soil probe can still be
watered by it: it keeps the root zone's depletion from the weather alone and waters when a
set share of the available water is gone. This runs it, as published, on each recorded
summer and writes the days and depths it would water. `sim/irrigation_drill.py` then waters
the virtual bed on that schedule beside its other rules (`pyfao56` policy), so the scheduler
is scored on the same ground as a timer, the soil probe and the free controllers
(docs/notes/irrigation-projects.md).

pyfao56 brings pandas, numpy and matplotlib, so this runs in an environment of its own,
as GreenLight does for the twin; the drill reads only the file it writes:

    python3 -m venv fao-env && fao-env/bin/pip install pyfao56
    fao-env/bin/python -I tools/pyfao56_schedules.py --weather mcallister-1991-2020.csv \\
        --from 1991 --to 2020 --out sim/data/pyfao56-mcallister-summers.csv

The bed is the drill's (`irrigation_drill.bed`): a 30 cm root zone in silt loam, field
capacity 0.30, wilting point 0.12, starting at field capacity, a full canopy whose basal
crop coefficient stays at 1.05. It is watered when a third of the available water is gone,
the soil probe rule's refill point, back to field capacity, pyfao56's default amount.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sim"))

LAT, ELEVATION_M = 35.06, 243.0
BED = {"thetaFC": 0.30, "thetaWP": 0.12, "theta0": 0.30, "Zrini": 0.30, "Zrmax": 0.30,
       # 1.049, not 1.05: pyfao56 1.4.3 scales plant height by (Kcb - Kcbini) / (Kcbmid -
       # Kcbini), which divides by zero for a canopy that does not grow over the season.
       "Kcbini": 1.049, "Kcbmid": 1.05, "Kcbend": 1.05, "Lini": 1, "Ldev": 1, "Lmid": 120,
       "Lend": 1, "hini": 1.0, "hmax": 1.0, "pbase": 0.5, "Ze": 0.10, "REW": 9.0, "CN2": 70}
MAD = 1.0 / 3.0


def _key(d: _dt.date) -> str:
    return f"{d.year}-{d.timetuple().tm_yday:03d}"


def weather(climate, start: _dt.date, end: _dt.date):
    """pyfao56's daily weather table from recorded days: vapour pressure from the mean
    humidity, FAO-56's 2 m/s where no wind is recorded, ETref by its own ASCE routine."""
    import pandas as pd
    from pyfao56 import Weather
    w = Weather()
    w.rfcrp, w.z, w.lat, w.wndht = "S", ELEVATION_M, LAT, 2.0
    rows, d = {}, start
    while d <= end:
        v = climate.days[d]
        es = (0.6108 * math.exp(17.27 * v["T2M_MAX"] / (v["T2M_MAX"] + 237.3))
              + 0.6108 * math.exp(17.27 * v["T2M_MIN"] / (v["T2M_MIN"] + 237.3))) / 2.0
        rows[_key(d)] = {"Srad": v["ALLSKY_SFC_SW_DWN"], "Tmax": v["T2M_MAX"], "Tmin": v["T2M_MIN"],
                         "Vapr": v["RH2M"] / 100.0 * es, "Tdew": float("nan"),
                         "RHmax": float("nan"), "RHmin": float("nan"), "Wndsp": 2.0,
                         "Rain": v["PRECTOTCORR"], "ETref": float("nan"), "MorP": "M"}
        d += _dt.timedelta(days=1)
    w.wdata = pd.DataFrame.from_dict(rows, orient="index")[w.cnames]
    for index in w.wdata.index:
        w.wdata.loc[index, "ETref"] = w.compute_etref(index)
    return w


def schedule(climate, year: int) -> list[tuple[_dt.date, float]]:
    """The days, June 1 to August 31, pyfao56 would water, and how much (mm)."""
    from pyfao56 import AutoIrrigate, Model, Parameters
    start, end = _dt.date(year, 6, 1), _dt.date(year, 8, 31)
    par = Parameters()
    for name, value in BED.items():
        setattr(par, name, value)
    auto = AutoIrrigate()
    auto.addset(_key(start), _key(end), mad=MAD)
    model = Model(_key(start), _key(end), par, weather(climate, start, end), autoirr=auto)
    model.run()
    out = []
    for index, mm in model.odata["Irrig"].items():
        if mm > 0:
            year, doy = (int(x) for x in str(index).split("-"))
            out.append((_dt.date(year, 1, 1) + _dt.timedelta(days=doy - 1), round(float(mm), 2)))
    return out


def main(argv=None) -> int:
    import pyfao56
    import physics as ph
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--weather", required=True, help="a whole-years recorded-weather CSV")
    ap.add_argument("--from", dest="first", type=int, required=True)
    ap.add_argument("--to", dest="last", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    climate = ph.RecordedClimate.from_csv(args.weather)
    with open(args.out, "w", encoding="utf-8") as h:
        h.write(f"# pyfao56 {pyfao56.__version__} (USDA ARS, public domain / CC0), its automatic "
                f"irrigation scheduler on McAllister Farm's recorded summers\n")
        h.write("# (NASA POWER daily, CC BY 4.0): the irrigation drill's bed, watered at a third "
                "of the available water gone, back to field capacity.\n")
        h.write("# tools/pyfao56_schedules.py wrote it; sim/irrigation_drill.py reads it.\n")
        h.write("date,irrigation_mm\n")
        for year in range(args.first, args.last + 1):
            for day, mm in schedule(climate, year):
                h.write(f"{day.isoformat()},{mm}\n")
            print(year, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

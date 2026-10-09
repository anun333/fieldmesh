#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Will a crop mature at a site? DSSAT's CROPGRO phenology, run on the site's weather.

    python3 tools/dssat_crops.py 35.06445 -86.59137 --cache CACHE --out seasons.csv \\
        [--params docs/notes/crop-parameters-dssat.csv]

USDA PLANTS has almost nothing on food crops (docs/notes/site-match-tennessee.md). The
DSSAT crop models do: for each crop, the cardinal temperatures of its development, its
response to day length, and — per cultivar — how many photothermal days each phase
takes. DSSAT is BSD-3-Clause (Copyright (c) 2021, DSSAT Foundation); its parameter files
are read from a pinned commit, and docs/notes/crop-parameters-dssat-LICENSE.txt carries
the notice that must travel with anything derived from them.

What is ported, from DSSAT's own source:

* `curv` — UTILS.for CURV: the LIN, QDR, SIN, NON, INL, SHO and LON response curves
  (the ones these crops use);
* the cultivar and ecotype read formats — Ipphenol.for, `(24X,A6,7F6.0)` and the
  ecotype FORMAT 3100 — and the derived thresholds: PHTHRS(5) as the remainder of EM-FL,
  CLDVAR = CSDVAR + (1−THVAR)/PPSEN, CSDVRR = CSDVAR − R1PPO;
* PHENOL.for's daily rate for a phase: the temperature curve averaged over 24 hourly
  temperatures, times the day-length curve.

What is simplified, and said so: hourly temperatures are a sine between the day's minimum
and maximum, not DSSAT's own diurnal model; soil temperature at seed depth is taken as
the air's; water, nitrogen and phosphorus stress are not simulated, so development runs
at its unstressed pace; and only the path to physiological maturity is followed
(planting → emergence → first flower → first seed → maturity).

Planting: a warm-season crop (vegetative base temperature 5 °C or more) a week after each
year's last spring frost; a cool-season crop four weeks before the median last frost.
Fall plantings of cool-season crops are not tried yet.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import math
import os
import statistics
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import site_profile  # noqa: E402

COMMIT = "25c93b9a2f73f8ec45bf441b198dac5fb7b22849"
RAW = "https://raw.githubusercontent.com/DSSAT/dssat-csm-os/{commit}/Data/Genotype/{name}"

#: DSSAT CROPGRO crop code → the plant list's scientific name. Forage models (Brachiaria,
#: Bahia) are left out: they are grazed, not taken to maturity.
CROPS = {
    "AM": "Amaranthus cruentus", "BG": "Vigna subterranea", "BN": "Phaseolus vulgaris",
    "CB": "Brassica oleracea var. capitata", "CH": "Cicer arietinum", "CN": "Brassica napus",
    "CO": "Gossypium hirsutum", "CP": "Vigna unguiculata", "FB": "Vicia faba",
    "FX": "Linum usitatissimum", "GY": "Cyamopsis tetragonoloba", "HM": "Cannabis sativa",
    "LT": "Lens culinaris", "PN": "Arachis hypogaea", "PP": "Cajanus cajan",
    "PR": "Capsicum annuum", "QU": "Chenopodium quinoa", "SB": "Glycine max",
    "SF": "Carthamus tinctorius", "SU": "Helianthus annuus", "TM": "Solanum lycopersicum",
    "VB": "Mucuna pruriens",
}
#: The phases on the path to physiological maturity, in order (PHENOL.for's numbering).
PATH = (1, 3, 4, 5, 8, 10)
FLOWER_AFTER = 5            # first flower is reached at the end of phase 5
COOL_SEASON_BASE_C = 5.0


# ----------------------------------------------------------------- DSSAT, ported

def curv(ctype: str, xb: float, x1: float, x2: float, xm: float, x: float) -> float:
    """DSSAT UTILS.for CURV."""
    t = ctype.upper()
    if t == "NON":
        return 1.0
    if t == "LIN":
        v = 0.0
        if xb < x < x1:
            v = (x - xb) / (x1 - xb)
        if x1 <= x <= x2:
            v = 1.0
        if x2 < x < xm:
            v = 1.0 - (x - x2) / (xm - x2)
        return min(max(v, 0.0), 1.0)
    if t == "QDR":
        v = 0.0
        if xb < x < x1:
            v = 1.0 - ((x1 - x) / (x1 - xb)) ** 2
        if x1 <= x <= x2:
            v = 1.0
        if x2 < x < xm:
            v = 1.0 - ((x - x2) / (xm - x2)) ** 2
        return min(max(v, 0.0), 1.0)
    if t == "SIN":
        # DSSAT writes pi as 22./7.; kept, so results match DSSAT's own.
        pi = 22.0 / 7.0
        v = 0.0
        if xb < x < x1:
            v = 0.5 * (1.0 + math.cos(2.0 * pi * (x - x1) / (2.0 * (x1 - xb))))
        if x1 <= x <= x2:
            v = 1.0
        if x2 < x < xm:
            v = 0.5 * (1.0 + math.cos(2.0 * pi * (x2 - x) / (2.0 * (xm - x2))))
        return min(max(v, 0.0), 1.0)
    if t in ("INL", "SHO"):
        v = 1.0
        if x1 < x < x2:
            v = 1.0 - (1.0 - xm) * ((x - x1) / (x2 - x1))
        if x >= x2:
            v = xm
        return min(max(v, xm), 1.0)
    if t == "LON":
        if x < x2:
            v = xm
        elif x < x1:
            v = 1.0 - (1.0 - xm) * ((x1 - x) / (x1 - x2))
        else:
            v = 1.0
        return min(max(v, xm), 1.0)
    raise ValueError(f"curve type {ctype!r} not ported")


def _f(text: str) -> float | None:
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_spe(text: str) -> dict:
    """Crop name, the cardinal temperatures of development (rows 1-3: vegetative, early
    and late reproductive), and the phase table (J, reference stage, day-length curve,
    temperature curve, which temperature row)."""
    lines = text.replace("\r", "").splitlines()
    name = lines[0].lstrip("*").split("SPECIES")[0].strip().title()
    temps, phases = {}, {}
    start = next(i for i, l in enumerate(lines) if "PHENOLOGY PARAMETERS" in l.upper())
    for line in lines[start + 1:]:
        if line.startswith("!*"):
            break
        parts = line.split()
        if not parts or line.lstrip().startswith("!"):
            continue
        if len(parts) >= 5 and parts[4] in ("1", "2", "3") and _f(parts[0]) is not None \
                and "." in parts[0]:
            temps[int(parts[4])] = tuple(float(x) for x in parts[:4])
        elif len(parts) >= 5 and parts[0].isdigit() and parts[2].isalpha():
            phases[int(parts[0])] = {"prior": int(parts[1]), "daylength": parts[2],
                                     "temperature": parts[3], "row": int(parts[4])}
    return {"name": name, "temps": temps, "phases": phases}


def parse_eco(text: str) -> dict:
    """Ecotype rows by FORMAT 3100 of Ipphenol.for."""
    out = {}
    for line in text.replace("\r", "").splitlines():
        if not line.strip() or line[0] in "!*@" or len(line) < 72:
            continue
        line = line.ljust(126)
        out[line[0:6].strip()] = {
            "THVAR": _f(line[31:36]), "PL-EM": _f(line[37:42]), "EM-V1": _f(line[43:48]),
            "V1-JU": _f(line[49:54]), "JU-R0": _f(line[55:60]),
            "R1PPO": _f(line[109:114]) or 0.0}
    return out


def parse_cul(text: str) -> list:
    """Cultivar rows of a .CUL file: VAR#, VRNAME (16), EXPNO, ECO#, then six-character
    fields CSDL, PPSEN, EM-FL, FL-SH, FL-SD, SD-PM. (Ipphenol.for's `(24X,A6,7F6.0)` reads
    DSSAT's intermediate input file, where the same values sit six columns earlier; the
    first version here used it on the .CUL file and read nothing.)"""
    out = []
    for line in text.replace("\r", "").splitlines():
        if not line.strip() or line[0] in "!*@" or len(line) < 72:
            continue
        code = line[0:6].strip()
        if code in ("999991", "999992"):            # the MINIMA and MAXIMA rows
            continue
        out.append({"code": code, "name": line[7:23].strip(), "eco": line[30:36].strip(),
                    "CSDL": _f(line[36:42]), "PPSEN": _f(line[42:48]),
                    "EM-FL": _f(line[48:54]), "FL-SH": _f(line[54:60]),
                    "FL-SD": _f(line[60:66]), "SD-PM": _f(line[66:72])})
    return out


def thresholds(cul: dict, eco: dict) -> dict:
    """PHTHRS on the path to maturity, and the day-length curve's critical lengths."""
    ph3, ph4 = eco["V1-JU"] or 0.0, eco["JU-R0"] or 0.0
    th = {1: eco["PL-EM"] or 0.0, 3: ph3, 4: ph4,
          5: max(0.0, (cul["EM-FL"] or 0.0) - ph3 - ph4),
          8: cul["FL-SD"] or 0.0, 10: cul["SD-PM"] or 0.0}
    ppsen, csdl, thvar = cul["PPSEN"] or 0.0, cul["CSDL"] or 12.0, eco["THVAR"] or 0.0
    cldl = csdl + (1.0 - thvar) / (max(ppsen, 1e-6) if ppsen >= 0 else min(ppsen, -1e-6))
    return {"phthrs": th, "csdl": csdl, "cldl": cldl, "thvar": thvar,
            "r1ppo": eco["R1PPO"] or 0.0}


# ------------------------------------------------------------------ simulation

def hourly(tmin: float, tmax: float) -> list:
    """24 temperatures on a sine, minimum at 02:00 and maximum at 14:00 — a stand-in
    for DSSAT's own diurnal model."""
    mean, amp = (tmin + tmax) / 2.0, (tmax - tmin) / 2.0
    return [mean - amp * math.cos(2 * math.pi * (h - 2) / 24.0) for h in range(24)]


def civil_day_length(lat: float, doy: int) -> float:
    """Day length including civil twilight (sun 6° below the horizon), as DSSAT uses for
    photoperiod."""
    decl = math.radians(23.44) * math.sin(2 * math.pi * (doy - 81) / 365.0)
    phi = math.radians(lat)
    x = (math.sin(math.radians(-6.0)) - math.sin(phi) * math.sin(decl)) / (
        math.cos(phi) * math.cos(decl))
    if x >= 1:
        return 0.0
    if x <= -1:
        return 24.0
    return 2 * math.degrees(math.acos(x)) / 15.0


def develop(spe: dict, th: dict, days: list, start: int, lat: float,
            stop: int | None = None) -> dict:
    """Run from `days[start]` (planting) to `stop` (the first fall frost) at the latest:
    -> {flower, maturity} as indices into `days`, None if not reached by then. The first
    version had no stop, and a crop that frost would kill "matured" two winters later."""
    out = {"flower": None, "maturity": None}
    phase_i, acc = 0, 0.0
    end = min(len(days), stop if stop is not None else start + 365)
    for i in range(start, end):
        date, v = days[i]
        if "T2M_MIN" not in v or "T2M_MAX" not in v:
            continue
        phase = PATH[phase_i]
        p = spe["phases"].get(phase, {"daylength": "NON", "temperature": "LIN", "row": 1})
        tb, to1, to2, tm = spe["temps"][p["row"]]
        ft = statistics.mean(curv(p["temperature"], tb, to1, to2, tm, t)
                             for t in hourly(v["T2M_MIN"], v["T2M_MAX"]))
        after_r1 = phase in (8, 10)
        lo = th["csdl"] - (th["r1ppo"] if after_r1 else 0.0)
        hi = th["cldl"] - (th["r1ppo"] if after_r1 else 0.0)
        fu = curv(p["daylength"], 1.0, lo, hi, th["thvar"],
                  civil_day_length(lat, date.timetuple().tm_yday))
        acc += ft * fu
        while acc >= th["phthrs"][PATH[phase_i]]:
            acc -= th["phthrs"][PATH[phase_i]]
            if PATH[phase_i] == FLOWER_AFTER:
                out["flower"] = i
            phase_i += 1
            if phase_i == len(PATH):
                out["maturity"] = i
                return out
    return out


def frost_years(days: list, north: bool) -> list:
    """Per year: (index of the last spring frost or None, index of the first fall frost
    or None). Northern hemisphere: split at 1 July."""
    years = {}
    for i, (d, v) in enumerate(days):
        if v.get("T2M_MIN", 99) > 0.0:
            continue
        y = d.year
        spring = d.month < 7 if north else d.month >= 7
        last, first = years.get(y, (None, None))
        if spring:
            last = i
        elif first is None:
            first = i
        years[y] = (last, first)
    return [(y, *years[y]) for y in sorted(years)]


def evaluate(spe: dict, cultivars: list, ecos: dict, days: list, lat: float) -> list:
    """For each cultivar: median days to flower and maturity, and the share of years it
    matures before the first fall frost."""
    north = lat >= 0
    index = {d: i for i, (d, _) in enumerate(days)}
    seasons = frost_years(days, north)
    lasts = [days[l][0].timetuple().tm_yday for _, l, _ in seasons if l is not None]
    median_last = int(statistics.median(lasts)) if lasts else 60
    cool = spe["temps"][1][0] < COOL_SEASON_BASE_C
    out = []
    for cul in cultivars:
        eco = ecos.get(cul["eco"]) or ecos.get("DFAULT")
        if eco is None:
            continue
        th = thresholds(cul, eco)
        to_flower, to_mature, safe, tried = [], [], 0, 0
        for year, last, first in seasons:
            if cool:
                plant = _dt.date(year, 1, 1) + _dt.timedelta(days=median_last - 1 - 28)
            elif last is not None:
                plant = days[last][0] + _dt.timedelta(days=7)
            else:
                continue
            start = index.get(plant)
            if start is None:
                continue
            tried += 1
            r = develop(spe, th, days, start, lat, stop=first)
            if r["flower"] is not None:
                to_flower.append(r["flower"] - start)
            if r["maturity"] is not None:
                to_mature.append(r["maturity"] - start)
                safe += 1
        if tried:
            out.append({"cultivar": cul["name"], "code": cul["code"],
                        "planting": "4 weeks before last frost" if cool else "1 week after last frost",
                        "days_to_flower": int(statistics.median(to_flower)) if to_flower else None,
                        "days_to_maturity": int(statistics.median(to_mature)) if to_mature else None,
                        "matures_before_frost": round(safe / tried, 2), "years": tried,
                        "photoperiod": ("day-neutral" if abs(cul["PPSEN"] or 0) < 1e-6
                                        else "short-day" if (cul["PPSEN"] or 0) > 0 else "long-day"),
                        "csdl_h": cul["CSDL"]})
    return out


# ---------------------------------------------------------------------- I/O

def fetch(name: str, cache: str) -> str:
    url = RAW.format(commit=COMMIT, name=name)
    os.makedirs(cache, exist_ok=True)
    file = os.path.join(cache, hashlib.sha256(url.encode()).hexdigest()[:24] + ".txt")
    if not os.path.exists(file):
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read().decode("latin-1")
        with open(file, "w", encoding="utf-8") as h:
            h.write(data)
    with open(file, encoding="utf-8") as h:
        return h.read()


def load(code: str, cache: str) -> tuple:
    base = f"{code}GRO048"
    return (parse_spe(fetch(base + ".SPE", cache)), parse_eco(fetch(base + ".ECO", cache)),
            parse_cul(fetch(base + ".CUL", cache)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True, help="per crop: the best cultivar's season at this site")
    ap.add_argument("--params", help="also write the crops' DSSAT parameters here")
    args = ap.parse_args(argv)
    days = site_profile.days_of(site_profile.fetch_power(args.lat, args.lon, 1991, 2020,
                                                         os.path.join(args.cache, "power")))
    rows, params = [], []
    for code, scientific in CROPS.items():
        spe, ecos, culs = load(code, os.path.join(args.cache, "dssat"))
        results = evaluate(spe, culs, ecos, days, args.lat)
        if not results:
            continue
        best = max(results, key=lambda r: (r["matures_before_frost"],
                                           -(r["days_to_maturity"] or 999)))
        maturing = [r for r in results if r["days_to_maturity"]]
        # The longest-season cultivar that still matures 8 years in 10: the one that
        # uses the season — for soybean, the latest maturity group that fits.
        fitting = [r for r in results if r["matures_before_frost"] >= 0.8 and r["days_to_maturity"]]
        longest = max(fitting, key=lambda r: r["days_to_maturity"]) if fitting else None
        rows.append({"scientific_name": scientific, "dssat_crop": spe["name"], "dssat_code": code,
                     "cultivars": len(results), "best_cultivar": best["cultivar"],
                     "best_matures_before_frost": best["matures_before_frost"],
                     "best_days_to_maturity": best["days_to_maturity"],
                     "best_days_to_flower": best["days_to_flower"],
                     "cultivars_maturing_8_in_10": sum(1 for r in results if r["matures_before_frost"] >= 0.8),
                     "days_to_maturity_range": (f"{min(r['days_to_maturity'] for r in maturing)}–"
                                                f"{max(r['days_to_maturity'] for r in maturing)}"
                                                if maturing else ""),
                     "longest_cultivar_8_in_10": longest["cultivar"] if longest else "",
                     "longest_days_to_maturity": longest["days_to_maturity"] if longest else "",
                     "planting": best["planting"], "photoperiod": best["photoperiod"]})
        t = spe["temps"]
        params.append({"scientific_name": scientific, "dssat_crop": spe["name"], "dssat_code": code,
                       "vegetative_tb_to1_to2_tm_c": " ".join(f"{x:g}" for x in t[1]),
                       "early_reproductive_c": " ".join(f"{x:g}" for x in t.get(2, ())),
                       "late_reproductive_c": " ".join(f"{x:g}" for x in t.get(3, ())),
                       "cultivars": len(culs),
                       "critical_day_length_h": f"{min(c['CSDL'] for c in culs):g}–{max(c['CSDL'] for c in culs):g}",
                       "photoperiod_sensitivity": f"{min(c['PPSEN'] for c in culs):g}–{max(c['PPSEN'] for c in culs):g}"})
    with open(args.out, "w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    if args.params:
        with open(args.params, "w", newline="", encoding="utf-8") as h:
            h.write(f"# SPDX-License-Identifier: BSD-3-Clause\n# Derived from DSSAT CSM genotype files, "
                    f"github.com/DSSAT/dssat-csm-os at {COMMIT}. Copyright (c) 2021, DSSAT "
                    f"Foundation; see crop-parameters-dssat-LICENSE.txt.\n")
            w = csv.DictWriter(h, fieldnames=list(params[0]))
            w.writeheader()
            w.writerows(params)
    for r in rows:
        if r["cultivars_maturing_8_in_10"]:
            print(f"  {r['dssat_crop']:<18} {r['cultivars_maturing_8_in_10']:>2}/{r['cultivars']:<2} cultivars mature 8 years in 10: "
                  f"fastest {r['best_cultivar'][:18]} {r['best_days_to_maturity']} d, longest {r['longest_cultivar_8_in_10'][:18]} "
                  f"{r['longest_days_to_maturity']} d ({r['photoperiod']}, {r['planting']})")
        else:
            print(f"  {r['dssat_crop']:<18}  0/{r['cultivars']:<2} cultivars mature before frost 8 years in 10 — best "
                  f"{r['best_cultivar'][:18]} in {r['best_matures_before_frost']:.0%} of years ({r['photoperiod']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

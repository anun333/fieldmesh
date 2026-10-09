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
  temperatures, times the day-length curve;
* for maize, MZ_PHENOL.for's CERES phenology: daily thermal time (soil-temperature rule
  before ten leaves, a 24-point sine when the day crosses base or optimum), emergence,
  the juvenile phase, the day-length index to tassel initiation, the leaf-number rule to
  silking, and P5 to maturity.

What is simplified, and said so: hourly temperatures are a sine between the day's minimum
and maximum, not DSSAT's own diurnal model; soil temperature at seed depth is taken as
the air's; water, nitrogen and phosphorus stress are not simulated, so development runs
at its unstressed pace; and only the path to physiological maturity is followed
(planting → emergence → first flower → first seed → maturity).

Planting: a warm-season crop (vegetative base temperature 5 °C or more) a week after each
year's last spring frost; a cool-season crop four weeks before the median last frost.
`--windows` also sweeps sowing week by week through the year, with three representative
cultivars, ending each season at the first freeze below the crop's own damage threshold
(CROPGRO's FREEZ1: −2.22 °C for tomato, −6 for cabbage, −29 for lentil) — which is what
lets a fall sowing of a hardy crop overwinter and a tender one fail.
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
    freeze = None
    for line in lines:
        # "SENRTE,SENRT2,SENDAY,FREEZ1,FREEZ2" — the live line, not a commented-out one.
        if "FREEZ1,FREEZ2" in line.upper() and not line.lstrip().startswith("!"):
            nums = [_f(x) for x in line.split()[:5]]
            if len(nums) == 5 and None not in nums:
                freeze = (nums[3], nums[4])
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
    return {"name": name, "temps": temps, "phases": phases, "freeze": freeze}


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


def evaluate(runners: list, days: list, lat: float, cool: bool) -> list:
    """For each cultivar runner: median days to flower and maturity, and the share of
    years it matures before the first fall frost. A runner is (name, code, photoperiod,
    critical day length, run) where `run(days, start, stop)` -> {flower, maturity}."""
    north = lat >= 0
    index = {d: i for i, (d, _) in enumerate(days)}
    seasons = frost_years(days, north)
    lasts = [days[l][0].timetuple().tm_yday for _, l, _ in seasons if l is not None]
    median_last = int(statistics.median(lasts)) if lasts else 60
    out = []
    for name, code, photoperiod, csdl, run in runners:
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
            r = run(days, start, first)
            if r["flower"] is not None:
                to_flower.append(r["flower"] - start)
            if r["maturity"] is not None:
                to_mature.append(r["maturity"] - start)
                safe += 1
        if tried:
            out.append({"cultivar": name, "code": code,
                        "planting": "4 weeks before last frost" if cool else "1 week after last frost",
                        "days_to_flower": int(statistics.median(to_flower)) if to_flower else None,
                        "days_to_maturity": int(statistics.median(to_mature)) if to_mature else None,
                        "matures_before_frost": round(safe / tried, 2), "years": tried,
                        "photoperiod": photoperiod, "csdl_h": csdl})
    return out


def cropgro_runners(spe: dict, cultivars: list, ecos: dict, lat: float) -> list:
    runners = []
    for cul in cultivars:
        eco = ecos.get(cul["eco"]) or ecos.get("DFAULT")
        if eco is None:
            continue
        th = thresholds(cul, eco)
        photoperiod = ("day-neutral" if abs(cul["PPSEN"] or 0) < 1e-6
                       else "short-day" if (cul["PPSEN"] or 0) > 0 else "long-day")
        runners.append((cul["name"], cul["code"], photoperiod, cul["CSDL"],
                        lambda days, start, stop, th=th: develop(spe, th, days, start, lat, stop)))
    return runners


# ----------------------------------------------------------- CERES-Maize, ported

def parse_maize_cul(text: str) -> list:
    """MZCER048.CUL: VAR#, VRNAME, EXPNO, ECO#, then P1, P2, P5, G2, G3, PHINT."""
    out = []
    for line in text.replace("\r", "").splitlines():
        if not line.strip() or line[0] in "!*@" or len(line) < 72:
            continue
        code = line[0:6].strip()
        if code in ("999991", "999992"):
            continue
        out.append({"code": code, "name": line[7:23].strip(), "eco": line[30:36].strip(),
                    "P1": _f(line[36:42]), "P2": _f(line[42:48]), "P5": _f(line[48:54]),
                    "PHINT": _f(line[66:72])})
    return out


def parse_maize_eco(text: str) -> dict:
    """MZ_PHENOL.for FORMAT 3100: (A6,1X,A16,1X,10(1X,F5.0),...): TBASE, TOPT, ROPT, P2O,
    DJTI, GDDE, DSGFT, ..."""
    out = {}
    for line in text.replace("\r", "").splitlines():
        if not line.strip() or line[0] in "!*@" or len(line) < 66:
            continue
        out[line[0:6].strip()] = {"TBASE": _f(line[25:30]), "TOPT": _f(line[31:36]),
                                  "P2O": _f(line[43:48]), "DJTI": _f(line[49:54]),
                                  "GDDE": _f(line[55:60]), "DSGFT": _f(line[61:66])}
    return out


def maize_dtt(tmin: float, tmax: float, srad: float, dayl: float, leafno: float,
              tbase: float, dopt: float) -> float:
    """MZ_PHENOL.for's daily thermal time, without snow: before ten leaves, from the
    soil-temperature estimate; otherwise the mean, or a 24-point sine when the day
    crosses the base or the optimum."""
    if tmax < tbase:
        dtt = 0.0
    elif tmin > dopt:
        dtt = dopt - tbase
    elif leafno <= 10:
        acoef = 0.01061 * srad + 0.5902
        tdsoil = acoef * tmax + (1.0 - acoef) * tmin
        tnsoil = 0.36354 * tmax + 0.63646 * tmin
        if tdsoil < tbase:
            dtt = 0.0
        else:
            tnsoil = max(tnsoil, tbase)
            tdsoil = min(tdsoil, dopt)
            tmsoil = tdsoil * (dayl / 24.0) + tnsoil * ((24.0 - dayl) / 24.0)
            dtt = ((tbase + tdsoil) / 2.0 - tbase) if tmsoil < tbase else ((tnsoil + tdsoil) / 2.0 - tbase)
            dtt = min(dtt, dopt - tbase)
    elif tmin < tbase or tmax > dopt:
        dtt = 0.0
        for i in range(1, 25):
            th = (tmax + tmin) / 2.0 + (tmax - tmin) / 2.0 * math.sin(3.14 / 12.0 * i)
            th = min(max(th, tbase), dopt)
            dtt += (th - tbase) / 24.0
    else:
        dtt = (tmax + tmin) / 2.0 - tbase
    return max(dtt, 0.0)


SOWING_DEPTH_CM = 5.0


def develop_maize(cul: dict, eco: dict, days: list, start: int, lat: float,
                  stop: int | None = None) -> dict:
    """MZ_PHENOL.for's stages from sowing: emergence after 45 + GDDE x depth; juvenile to
    P1; tassel initiation when the day-length index reaches 1, at 1/(DJTI + P2 x
    (twilight day length − P2O)) a day; then P3 = (leaves + 0.5) x PHINT − thermal time
    so far to silking, with leaves = thermal time / (0.5 x PHINT) + 5; maturity at P5
    after silking. Germination is taken as immediate (moist soil); the leaf count that
    switches the early soil-temperature rule is estimated as one leaf per PHINT."""
    out = {"flower": None, "maturity": None}
    tbase, dopt = eco["TBASE"], eco["TOPT"]
    p9 = 45.0 + eco["GDDE"] * SOWING_DEPTH_CM
    stage, sumdtt, sind, p3, since_emergence = 9, 0.0, 0.0, None, 0.0
    end = min(len(days), stop if stop is not None else start + 365)
    for i in range(start, end):
        date, v = days[i]
        if "T2M_MIN" not in v or "T2M_MAX" not in v:
            continue
        doy = date.timetuple().tm_yday
        leafno = 1.0 + since_emergence / cul["PHINT"] if stage != 9 else 0.0
        dtt = maize_dtt(v["T2M_MIN"], v["T2M_MAX"], v.get("ALLSKY_SFC_SW_DWN", 15.0),
                        site_profile.day_length_h(lat, doy), leafno, tbase, dopt)
        sumdtt += dtt
        if stage != 9:
            since_emergence += dtt
        if stage == 9 and sumdtt >= p9:
            stage, sumdtt = 1, sumdtt - p9
        elif stage == 1 and sumdtt >= cul["P1"]:
            stage, sind = 2, 0.0
        elif stage == 2:
            twilen = civil_day_length(lat, doy)
            rate = (1.0 / (eco["DJTI"] + cul["P2"] * (twilen - eco["P2O"]))
                    if twilen > eco["P2O"] else 1.0 / eco["DJTI"])
            sind += rate
            if sind >= 1.0:
                tlno = sumdtt / (cul["PHINT"] * 0.5) + 5.0
                p3 = (tlno + 0.5) * cul["PHINT"] - sumdtt
                stage, sumdtt = 3, 0.0
        elif stage == 3 and sumdtt >= p3:
            stage, sumdtt = 4, sumdtt - p3
            out["flower"] = i                            # silking
        elif stage == 4 and sumdtt >= cul["P5"]:
            out["maturity"] = i                          # black layer
            return out
    return out


def maize_runners(cultivars: list, ecos: dict, lat: float) -> list:
    runners = []
    for cul in cultivars:
        eco = ecos.get(cul["eco"]) or ecos.get("DFAULT") or next(iter(ecos.values()))
        if None in (cul["P1"], cul["P2"], cul["P5"], cul["PHINT"]):
            continue
        runners.append((cul["name"], cul["code"], "short-day" if cul["P2"] > 0 else "day-neutral",
                        eco["P2O"], lambda days, start, stop, cul=cul, eco=eco:
                        develop_maize(cul, eco, days, start, lat, stop)))
    return runners


# ------------------------------------------------------------- planting windows

#: A killing-frost stand-in for maize, whose file gives none: the leaf-damage
#: threshold CROPGRO gives most warm-season crops (FREEZ1 = −2.22 °C). An assumption.
MAIZE_FREEZE_C = -2.22
WINDOW_SHARE = 0.8


def representatives(runners: list, size) -> list:
    """The fastest, a middle and the slowest cultivar by `size` (their total thermal or
    photothermal requirement) — enough to find the windows without running every one."""
    if len(runners) <= 3:
        return runners
    ordered = sorted(runners, key=size)
    return [ordered[0], ordered[len(ordered) // 2], ordered[-1]]


def sweep(runners: list, days: list, freeze_c: float, step_days: int = 7) -> list:
    """For sowings every `step_days` through the year: the share of years in which the
    best of `runners` matures before the first freeze below `freeze_c` after sowing.
    -> [(day of year, share)]."""
    index = {d: i for i, (d, _) in enumerate(days)}
    years = sorted({d.year for d, _ in days})[:-1]        # each needs the year after it
    tmins = [v.get("T2M_MIN", 99.0) for _, v in days]
    out = []
    for doy in range(1, 366, step_days):
        best = 0.0
        for runner in runners:
            ok = tried = 0
            for y in years:
                start = index.get(_dt.date(y, 1, 1) + _dt.timedelta(days=doy - 1))
                if start is None:
                    continue
                stop = next((i for i in range(start + 1, min(len(days), start + 366))
                             if tmins[i] < freeze_c), None)
                tried += 1
                r = runner[4](days, start, stop)
                ok += r["maturity"] is not None
            if tried:
                best = max(best, ok / tried)
        out.append((doy, best))
    return out


def windows(swept: list, share: float = WINDOW_SHARE) -> list:
    """Runs of sowing dates at or above `share`, as ("Apr 08", "Jun 10") pairs; a run
    that crosses the new year is joined."""
    runs, current = [], []
    for doy, s in swept:
        if s >= share:
            current.append(doy)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    if len(runs) > 1 and runs[0][0] == swept[0][0] and runs[-1][-1] == swept[-1][0]:
        runs[0] = runs.pop() + runs[0]

    def md(doy):
        return (_dt.date(2001, 1, 1) + _dt.timedelta(days=doy - 1)).strftime("%b %d")
    return [(md(r[0]), md(r[-1])) for r in runs]


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


def seasons_for(lat: float, lon: float, cache: str, windows_too: bool = False,
                days: list | None = None) -> tuple[list, list]:
    """Every modelled crop's season at a site -> (season rows, parameter rows)."""
    if days is None:
        days = site_profile.days_of(site_profile.fetch_power(lat, lon, 1991, 2020,
                                                             os.path.join(cache, "power")))
    rows, params = [], []
    models = [(code, scientific, "CROPGRO") for code, scientific in CROPS.items()]
    models.append(("MZ", "Zea mays", "CERES-Maize"))
    for code, scientific, model in models:
        dcache = os.path.join(cache, "dssat")
        if model == "CERES-Maize":
            culs = parse_maize_cul(fetch("MZCER048.CUL", dcache))
            ecos = parse_maize_eco(fetch("MZCER048.ECO", dcache))
            spe = {"name": "Maize", "temps": {1: (ecos["IB0001"]["TBASE"], ecos["IB0001"]["TOPT"],
                                                  ecos["IB0001"]["TOPT"], 44.0)},
                   "freeze": (MAIZE_FREEZE_C, None)}
            runners = maize_runners(culs, ecos, lat)
            size = {c["code"]: c["P1"] + c["P5"] for c in culs}
            results = evaluate(runners, days, lat, cool=False)
        else:
            spe, ecos, culs = load(code, dcache)
            runners = cropgro_runners(spe, culs, ecos, lat)
            size = {c["code"]: (c["EM-FL"] or 0) + (c["FL-SD"] or 0) + (c["SD-PM"] or 0) for c in culs}
            results = evaluate(runners, days, lat,
                               cool=spe["temps"][1][0] < COOL_SEASON_BASE_C)
        if not results:
            continue
        freeze_c = (spe.get("freeze") or (-2.22, None))[0]
        if windows_too:
            swept = sweep(representatives(runners, lambda r: size.get(r[1], 0)), days, freeze_c)
            sowing = "; ".join(f"{a}–{b}" for a, b in windows(swept)) or "none"
        else:
            sowing = ""
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
                     "planting": best["planting"], "photoperiod": best["photoperiod"],
                     "damaging_freeze_c": freeze_c,
                     "sowing_windows_8_in_10": sowing})
        t = spe["temps"]
        if model == "CERES-Maize":
            cd = f"{min(e['P2O'] for e in ecos.values()):g}–{max(e['P2O'] for e in ecos.values()):g}"
            ps = f"P2 {min(c['P2'] for c in culs):g}–{max(c['P2'] for c in culs):g} days/h"
        else:
            cd = f"{min(c['CSDL'] for c in culs):g}–{max(c['CSDL'] for c in culs):g}"
            ps = f"{min(c['PPSEN'] for c in culs):g}–{max(c['PPSEN'] for c in culs):g}"
        params.append({"scientific_name": scientific, "dssat_crop": spe["name"], "dssat_code": code,
                       "model": model,
                       "vegetative_tb_to1_to2_tm_c": " ".join(f"{x:g}" for x in t[1]),
                       "early_reproductive_c": " ".join(f"{x:g}" for x in t.get(2, ())),
                       "late_reproductive_c": " ".join(f"{x:g}" for x in t.get(3, ())),
                       "cultivars": len(culs), "critical_day_length_h": cd,
                       "photoperiod_sensitivity": ps})
    return rows, params


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True, help="per crop: the best cultivar's season at this site")
    ap.add_argument("--params", help="also write the crops' DSSAT parameters here")
    ap.add_argument("--windows", action="store_true",
                    help="also sweep sowing dates through the year for each crop's windows")
    args = ap.parse_args(argv)
    rows, params = seasons_for(args.lat, args.lon, args.cache, args.windows)
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
        if r["sowing_windows_8_in_10"]:
            print(f"  {'':<18} sow: {r['sowing_windows_8_in_10']} (freeze below {r['damaging_freeze_c']:g} °C ends it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

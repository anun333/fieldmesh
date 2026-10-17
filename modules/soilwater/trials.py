# SPDX-License-Identifier: AGPL-3.0-or-later
"""The advisory's defaults tried on a virtual farm that departs from what the advice is
told (`backtest.VirtualFarm`): ten beds, each with the choices that bear on it, through two
sites' recorded summers, the years the defaults were chosen on and years they were not.

    python3 trials.py run --weather DIR --out trials.jsonl --workers 4 [--cache DIR]
    python3 trials.py report trials.jsonl

`run` writes one line per backtest, stamped with the code it ran on (`--stamp`), and skips
the ones already written, so a run can be stopped and taken up again. Each site's weather
is DIR's `<site>-1991-2025.csv` (tools/weather_csv.py), its water loss FAO-56
Penman–Monteith with the day's own wind (`physics.RecordedClimate`), and each summer is run
on two farms drawn from it (`DRAWS`), each probe's noise and the forecasts drawn with them.

`report` sets each choice beside the default it would replace, on the same site, summer and
farm, the difference's mean and its 90% interval over those pairs (`BOOTSTRAP` resamples):
the years the defaults were chosen on (`TUNED`) apart from the rest."""
from __future__ import annotations

import argparse
import datetime as _dt
import itertools
import json
import os
import random
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.join(HERE, os.pardir, os.pardir, "sim")

#: Each site: its latitude and elevation, m, for the station and the farm's water loss.
SITES = {"mcallister": (35.06445, 243.0), "davis": (38.5382, 16.0)}
YEARS = range(1991, 2026)
#: The summers the defaults were chosen on; the rest are held out.
TUNED = ("mcallister", range(1991, 2021))
DRAWS = (1, 2)

MARGINS = (0.0, 0.1, 0.2)
YOUNG = ("stage", "roots")
SIGNS = (True, False)
SHALLOW = (1 / 3, 0.2)
#: Each bed, and the choices tried on it.
BEDS = {
    "bucket, its probe": {},
    "bucket, by the weather": {"margin": MARGINS},
    "tomatoes, probes": {"young": YOUNG, "signs": SIGNS},
    "tomatoes, by the weather": {"margin": MARGINS, "young": YOUNG},
    "lettuce, probes": {"young": YOUNG, "signs": SIGNS},
    "lettuce, by the weather": {"margin": MARGINS, "young": YOUNG},
    "lawn, its probe": {"p": SHALLOW},
    "lawn, by the weather": {"margin": MARGINS, "p": SHALLOW},
    "yard, its probes": {"p": SHALLOW},
    "tomatoes over a dense pan, probes": {"young": YOUNG, "signs": SIGNS},
}
#: The advisory as built: margin `WEATHER_MARGIN`, a young crop's refill point held until its
#: roots pass `YOUNG_ROOTS_MM`, the root signs on, a third of the water before watering.
DEFAULTS = {"margin": 0.2, "young": "roots", "signs": True, "p": 1 / 3}
#: What each backtest is scored by (`backtest.Score`).
SCORES = ("applied_mm", "drained_mm", "transpiration_lost_mm", "stressed_h", "below_p_h",
          "airless_h")
BOOTSTRAP = 2000


def jobs() -> list:
    """Every backtest of the trial: `(bed, choices, site, year, draw)`."""
    out = []
    for bed, options in BEDS.items():
        names = sorted(options)
        for values in itertools.product(*(options[n] for n in names)):
            choices = dict(zip(names, values))
            for site in SITES:
                for year in YEARS:
                    for draw in DRAWS:
                        out.append((bed, choices, site, year, draw))
    return out


def _key(bed: str, choices: dict, site: str, year: int, draw: int) -> str:
    return json.dumps([bed, sorted(choices.items()), site, year, draw])


def farm_seed(site: str, year: int, draw: int) -> int:
    """The seed a summer's farm is drawn from: the same for every bed and choice, so their
    backtests are of one farm and pair."""
    return zlib.crc32(f"{site} {year} {draw}".encode())


def run_one(job: tuple, weather: str, out: str, stamp: str) -> None:
    bed, choices, site, year, draw = job
    sys.path.insert(0, SIM)
    sys.path.insert(0, HERE)
    import backtest as B
    import lawn_drill as LD
    import physics as ph
    import soilwater as S
    picked = {**DEFAULTS, **choices}
    S.WEATHER_MARGIN = picked["margin"]
    S.YOUNG_ROOTS_MM = 250.0 if picked["young"] == "roots" else 0.0
    if not picked["signs"]:
        S.rooted = lambda curve, signs, held=None: (curve, 0.0, None)
    shallow = picked["p"] if picked["p"] != DEFAULTS["p"] else None
    lat_elevation = SITES[site]
    climate = ph.RecordedClimate.from_csv(os.path.join(weather, f"{site}-1991-2025.csv"),
                                          seed=1, et0_by="penman", site=lat_elevation)
    farm = B.VirtualFarm.drawn(farm_seed(site, year, draw))
    may = _dt.datetime(year, 5, 1, tzinfo=_dt.timezone.utc)
    june = _dt.datetime(year, 6, 1, tzinfo=_dt.timezone.utc)
    common = dict(seed=draw, farm=farm)
    weather_too = dict(common, record_valve=False, site=lat_elevation)
    if bed == "bucket, its probe":
        r = B.backtest(climate, june, 92, **common)
    elif bed == "bucket, by the weather":
        r = B.weather_backtest(climate, june, 92, **weather_too)
    elif bed in ("tomatoes, probes", "lettuce, probes"):
        crop = "tomato" if bed.startswith("tomatoes") else "lettuce"
        r = B.backtest(climate, may, S.CROPS[crop]["season_days"], depths=(0.10, 0.30),
                       crop=crop, planted=may.date(), knows_crop=True, **common)
    elif bed in ("tomatoes, by the weather", "lettuce, by the weather"):
        crop = "tomato" if bed.startswith("tomatoes") else "lettuce"
        r = B.weather_backtest(climate, may, S.CROPS[crop]["season_days"], crop=crop,
                               planted=may.date(), knows_crop=True, **weather_too)
    elif bed == "lawn, its probe":
        r = B.backtest(climate, june, 92, soil=LD.lawn("native"), crop="turf_cool",
                       knows_crop=True, hardpan_mm=LD.ROOTS_MM, knows_hardpan=True,
                       depths=(0.07,), depletion_fraction=shallow, **common)
    elif bed == "lawn, by the weather":
        r = B.weather_backtest(climate, june, 92, soil=LD.lawn("native"), crop="turf_cool",
                               knows_crop=True, virtual_crop="turf_cool",
                               hardpan_mm=LD.ROOTS_MM, knows_hardpan=True,
                               depletion_fraction=shallow, **weather_too)
    elif bed == "yard, its probes":
        yard = ph.LayeredBed(name="yard", depth_mm=150,
                             horizons=(ph.Horizon(100, **ph.SANDY_LOAM),
                                       ph.Horizon(500, **ph.COMPACTED_CLAY)))
        r = B.backtest(climate, june, 92, soil=yard, depths=(0.05, 0.12),
                       configured=(0.38, 0.25), learn=True, layers=((0.10, 0.20, 0.09),),
                       depletion_fraction=shallow, **common)
    elif bed == "tomatoes over a dense pan, probes":
        r = B.backtest(climate, may, S.CROPS["tomato"]["season_days"],
                       depths=(0.10, 0.30, 0.60), crop="tomato", planted=may.date(),
                       knows_crop=True, hardpan_mm=300.0, dense_pan=True, **common)
    else:
        raise ValueError(bed)
    line = {"bed": bed, "choices": choices, "site": site, "year": year, "draw": draw,
            "stamp": stamp, "farm": r["farm"],
            **{k: round(r[k], 2) for k in SCORES if r.get(k) is not None}}
    with open(out, "a", encoding="utf-8") as h:
        h.write(json.dumps(line) + "\n")


def _run(job_and_args):
    job, weather, out, stamp = job_and_args
    run_one(job, weather, out, stamp)


def run(weather: str, out: str, workers: int, stamp: str) -> int:
    from multiprocessing import Pool
    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8") as h:
            for line in h:
                r = json.loads(line)
                done.add(_key(r["bed"], r["choices"], r["site"], r["year"], r["draw"]))
    todo = [j for j in jobs() if _key(*j) not in done]
    random.Random(1).shuffle(todo)                     # long seasons and short ones mixed
    print(f"{len(todo)} backtests to run, {len(done)} done", flush=True)
    with Pool(workers, maxtasksperchild=1) as pool:
        for _ in pool.imap_unordered(_run, [(j, weather, out, stamp) for j in todo]):
            pass
    return 0


def _tuned(r: dict) -> bool:
    return r["site"] == TUNED[0] and r["year"] in TUNED[1]


def _interval(diffs: list, rng: random.Random) -> tuple:
    """The mean of `diffs` and its 90% interval, by resampling them `BOOTSTRAP` times."""
    n = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(BOOTSTRAP))
    return sum(diffs) / n, means[int(0.05 * BOOTSTRAP)], means[int(0.95 * BOOTSTRAP) - 1]


def report(path: str) -> str:
    """Markdown: each bed as built, and each choice against the default it would replace."""
    rows = []
    with open(path, encoding="utf-8") as h:
        for line in h:
            rows.append(json.loads(line))
    by = {(r["bed"], json.dumps(sorted(r["choices"].items())), r["site"], r["year"], r["draw"]): r
          for r in rows}
    rng = random.Random(1)
    out = ["| bed | summers | water | lost transpiration | summers losing over 1 mm | "
           "hours short of air |", "| --- | --- | --- | --- | --- | --- |"]
    for bed, options in BEDS.items():
        built = json.dumps(sorted({n: DEFAULTS[n] for n in options}.items()))
        for held_out in (False, True):
            got = [r for k, r in by.items() if k[0] == bed and k[1] == built
                   and _tuned(r) != held_out]
            if not got:
                continue
            n = len(got)
            out.append(f"| {bed}, {'held out' if held_out else 'tuned'} | {n} | "
                       f"{sum(r['applied_mm'] for r in got) / n:.0f} mm | "
                       f"{sum(r['transpiration_lost_mm'] for r in got) / n:.1f} mm | "
                       f"{sum(1 for r in got if r['transpiration_lost_mm'] > 1.0)} | "
                       f"{sum(r['airless_h'] for r in got) / n:.0f} |")
    out += ["", "| bed | choice, against the default | summers | water | lost transpiration | "
            "hours short of air |", "| --- | --- | --- | --- | --- | --- |"]
    for bed, options in BEDS.items():
        for name, values in sorted(options.items()):
            for value in values:
                if value == DEFAULTS[name]:
                    continue
                for held_out in (False, True):
                    base = {n: DEFAULTS[n] for n in options}
                    tried = dict(base, **{name: value})
                    pairs = []
                    for site in SITES:
                        for year in YEARS:
                            for draw in DRAWS:
                                a = by.get((bed, json.dumps(sorted(base.items())), site, year, draw))
                                b = by.get((bed, json.dumps(sorted(tried.items())), site, year, draw))
                                if a and b and _tuned(a) != held_out:
                                    pairs.append((a, b))
                    if not pairs:
                        continue
                    cells = []
                    for score in ("applied_mm", "transpiration_lost_mm", "airless_h"):
                        mean, lo, hi = _interval([b[score] - a[score] for a, b in pairs], rng)
                        cells.append(f"{mean:+.1f} ({lo:+.1f} to {hi:+.1f})")
                    shown = f"{value:.2g}" if isinstance(value, float) else str(value)
                    out.append(f"| {bed} | {name} {shown}, {'held out' if held_out else 'tuned'}"
                               f" | {len(pairs)} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--weather", required=True, help="the directory of <site>-1991-2025.csv")
    r.add_argument("--out", required=True)
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--cache", help="a directory to keep each season's forecasts in")
    r.add_argument("--stamp", default="", help="the code the trial runs on, as a commit")
    p = sub.add_parser("report")
    p.add_argument("results")
    args = ap.parse_args(argv)
    if args.command == "run":
        if args.cache:
            os.environ["FIELDMESH_FORECASTS"] = args.cache
        return run(args.weather, args.out, args.workers, args.stamp)
    print(report(args.results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

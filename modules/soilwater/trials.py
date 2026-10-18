# SPDX-License-Identifier: AGPL-3.0-or-later
"""The advisory's defaults tried on a virtual farm that departs from what the advice is
told (`backtest.VirtualFarm`): ten beds, each with the choices that bear on it, through
sites' recorded summers, the years the defaults were chosen on, years they were not, and
sites kept sealed until the defaults were chosen.

    python3 trials.py run --weather DIR --out trials.jsonl --workers 4 [--cache DIR]
                          [--sites mcallister,davis] [--stamp COMMIT]
    python3 trials.py report trials.jsonl

`run` writes one line per backtest, stamped with the code it ran on (`--stamp`), and skips
the ones already written on that code, so a run can be stopped and taken up again; a file
with lines on other code is refused. Each site's weather is DIR's `<site>-1991-2025.csv`
(tools/weather_csv.py), its water loss FAO-56 Penman–Monteith with the day's own wind
(`physics.RecordedClimate`), and each summer is run on a farm drawn for it (`DRAWS`), each
probe's noise and the forecasts drawn with it.

`report` gives each bed as built, then sets each choice and each thing measured besides
beside the bed as built, on the same summer and farm: the difference's mean and its 90%
interval over those pairs (`BOOTSTRAP` resamples), site by site (`group`)."""
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
#: McAllister Farm, Tennessee, humid; Davis, California, dry and windier; and, sealed until
#: the defaults of 2026-10-18 were chosen, Bushland, Texas, semi-arid and windy, and
#: Tifton, Georgia, humid and hot.
SITES = {"mcallister": (35.06445, 243.0), "davis": (38.5382, 16.0),
         "bushland": (35.186, 1170.0), "tifton": (31.475, 116.0)}
#: The sites the defaults are chosen on; the rest are sealed.
OPEN_SITES = ("mcallister", "davis")
YEARS = range(1991, 2026)
#: The summers the margin was first chosen on.
TUNED = ("mcallister", range(1991, 2021))
#: One farm a summer: a second, of the same summer's weather, moved the water by much the
#: same in the trial of 2026-10-17 (its two draws' differences correlated 0.8 to 0.99).
DRAWS = (1,)

MARGINS = (0.0, 0.1, 0.2)
SHALLOW = (1 / 3, 0.2)
#: Each bed, and the choices tried on it, crossed.
BEDS = {
    "bucket, its probe": {},
    "bucket, by the weather": {"margin": MARGINS},
    "tomatoes, probes": {},
    "tomatoes, by the weather": {"margin": MARGINS},
    "lettuce, probes": {},
    "lettuce, by the weather": {"margin": MARGINS},
    "lawn, its probe": {"p": SHALLOW},
    "lawn, by the weather": {"margin": MARGINS},
    "yard, its probes": {"p": SHALLOW},
    "tomatoes over a dense pan, probes": {},
}
#: The advisory as built: margin `WEATHER_MARGIN`, a third of the water before watering. A
#: young crop's refill point held by its roots and the root signs stay on: tried on
#: 2026-10-17 (README), not again.
DEFAULTS = {"margin": 0.2, "p": 1 / 3}

#: Besides `BEDS`' choices: what a farm might measure or set, each bed's blocks, each block
#: crossed with the choices it names, the bed's others at their defaults. The station's
#: wind (`weather_backtest(wind=True)`) or its site's monthly normal (`wind_normal`); the
#: hot-day refill point (`Bed.adjust_p`); a tension sensor beside each probe
#: (`backtest(tension=True)`); learning held within 0.05 of the configured field capacity
#: (`Bed.learn_within`); a probe at 5 cm over the others (`top`).
WEATHER_BLOCKS = tuple(({m: (True,), "margin": (0.1, 0.2)}, ())
                       for m in ("wind", "normal", "adjust"))
PROBE_BLOCKS = (({"adjust": (True,)}, ()), ({"tension": (True,)}, ()),
                ({"within": (0.05,)}, ()), ({"adjust": (True,), "within": (0.05,)}, ()),
                ({"adjust": (True,), "tension": (True,)}, ()))
TOP_BLOCKS = (({"top": (True,)}, ()), ({"adjust": (True,), "top": (True,)}, ()))
MEASURES = {
    "bucket, its probe": (({"adjust": (True,)}, ()),),
    "bucket, by the weather": WEATHER_BLOCKS,
    "tomatoes, probes": PROBE_BLOCKS + TOP_BLOCKS,
    "tomatoes, by the weather": WEATHER_BLOCKS,
    "lettuce, probes": PROBE_BLOCKS + TOP_BLOCKS,
    "lettuce, by the weather": WEATHER_BLOCKS,
    "lawn, its probe": tuple((m, ("p",)) for m, _ in PROBE_BLOCKS),
    "lawn, by the weather": WEATHER_BLOCKS,
    "yard, its probes": tuple((m, ("p",)) for m, _ in PROBE_BLOCKS),
    "tomatoes over a dense pan, probes": PROBE_BLOCKS,
}
#: Each measure or setting not taken. A backtest's choices leave it out.
OFF = {"wind": False, "normal": False, "adjust": False, "tension": False, "within": None,
       "top": False}
#: Each, as the report names it.
SAID = {"wind": "wind measured", "normal": "the wind's monthly normal",
        "adjust": "hot-day refill point", "tension": "tension sensors",
        "within": "learning within {}", "top": "a probe at 5 cm"}
#: What each backtest is scored by (`backtest.Score`).
SCORES = ("applied_mm", "drained_mm", "transpiration_lost_mm", "demand_mm", "stressed_h",
          "below_p_h", "airless_h", "waterlogged_h", "runoff_mm", "stored_change_mm")
BOOTSTRAP = 2000


def _product(options: dict) -> list:
    names = sorted(options)
    return [dict(zip(names, values)) for values in itertools.product(*(options[n] for n in names))]


def configs(bed: str) -> list:
    """Each set of choices the trial tries on `bed`: `BEDS`' choices crossed, then each
    block of `MEASURES` crossed with the choices it names, the measures off left out."""
    options = BEDS[bed]
    out = _product(options)
    built = {n: DEFAULTS[n] for n in options}
    for measures, crossed in MEASURES.get(bed, ()):
        for measured in _product({**measures, **{n: options[n] for n in crossed}}):
            choices = {**built, **{n: v for n, v in measured.items()
                                   if n not in OFF or OFF[n] != v}}
            if choices not in out:
                out.append(choices)
    return out


def jobs(sites=OPEN_SITES) -> list:
    """Every backtest of the trial on `sites`: `(bed, choices, site, year, draw)`."""
    out = []
    for bed in BEDS:
        for choices in configs(bed):
            for site in sites:
                for year in YEARS:
                    for draw in DRAWS:
                        out.append((bed, choices, site, year, draw))
    return out


def _key(bed: str, choices: dict, site: str, year: int, draw: int) -> str:
    return json.dumps([bed, sorted(choices.items()), site, year, draw])


def farm_seed(site: str, year: int, draw: int) -> int:
    """The seed a summer's farm is drawn from, and its probes' noise and its forecasts: the
    same for every bed and choice, so their backtests are of one farm and pair. (Until
    2026-10-18 the noise and forecasts were drawn from `draw` alone, the same each summer.)"""
    return zlib.crc32(f"{site} {year} {draw}".encode())


def run_one(job: tuple, weather: str, out: str, stamp: str) -> None:
    bed, choices, site, year, draw = job
    sys.path.insert(0, SIM)
    sys.path.insert(0, HERE)
    import backtest as B
    import lawn_drill as LD
    import physics as ph
    import soilwater as S
    picked = {**DEFAULTS, **OFF, **choices}
    S.WEATHER_MARGIN = picked["margin"]
    shallow = picked["p"] if picked["p"] != DEFAULTS["p"] else None
    settings = {k: v for k, v in (("adjust_p", picked["adjust"]),
                                  ("learn_within", picked["within"])) if v}
    lat_elevation = SITES[site]
    climate = ph.RecordedClimate.from_csv(os.path.join(weather, f"{site}-1991-2025.csv"),
                                          seed=1, et0_by="penman", site=lat_elevation)
    seed = farm_seed(site, year, draw)
    farm = B.VirtualFarm.drawn(seed)
    may = _dt.datetime(year, 5, 1, tzinfo=_dt.timezone.utc)
    june = _dt.datetime(year, 6, 1, tzinfo=_dt.timezone.utc)
    common = dict(seed=seed, farm=farm, settings=settings)
    weather_too = dict(common, record_valve=False, site=lat_elevation, wind=picked["wind"],
                       wind_normal=picked["normal"])
    probes_too = dict(common, tension=picked["tension"])
    top = (0.05,) if picked["top"] else ()
    if bed == "bucket, its probe":
        r = B.backtest(climate, june, 92, **common)
    elif bed == "bucket, by the weather":
        r = B.weather_backtest(climate, june, 92, **weather_too)
    elif bed in ("tomatoes, probes", "lettuce, probes"):
        crop = "tomato" if bed.startswith("tomatoes") else "lettuce"
        r = B.backtest(climate, may, S.CROPS[crop]["season_days"], depths=top + (0.10, 0.30),
                       crop=crop, planted=may.date(), knows_crop=True, **probes_too)
    elif bed in ("tomatoes, by the weather", "lettuce, by the weather"):
        crop = "tomato" if bed.startswith("tomatoes") else "lettuce"
        r = B.weather_backtest(climate, may, S.CROPS[crop]["season_days"], crop=crop,
                               planted=may.date(), knows_crop=True, **weather_too)
    elif bed == "lawn, its probe":
        r = B.backtest(climate, june, 92, soil=LD.lawn("native"), crop="turf_cool",
                       knows_crop=True, hardpan_mm=LD.ROOTS_MM, knows_hardpan=True,
                       depths=(0.07,), depletion_fraction=shallow, **probes_too)
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
                       depletion_fraction=shallow, **probes_too)
    elif bed == "tomatoes over a dense pan, probes":
        r = B.backtest(climate, may, S.CROPS["tomato"]["season_days"],
                       depths=(0.10, 0.30, 0.60), crop="tomato", planted=may.date(),
                       knows_crop=True, hardpan_mm=300.0, dense_pan=True, **probes_too)
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


def run(weather: str, out: str, workers: int, stamp: str, sites=OPEN_SITES) -> int:
    from multiprocessing import Pool
    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8") as h:
            for line in h:
                r = json.loads(line)
                if r.get("stamp") != stamp:
                    raise SystemExit(f"{out} holds backtests on code {r.get('stamp')!r}, "
                                     f"not {stamp!r}: write to a file of its own")
                done.add(_key(r["bed"], r["choices"], r["site"], r["year"], r["draw"]))
    todo = [j for j in jobs(sites) if _key(*j) not in done]
    random.Random(1).shuffle(todo)                     # long seasons and short ones mixed
    print(f"{len(todo)} backtests to run, {len(done)} done", flush=True)
    with Pool(workers, maxtasksperchild=1) as pool:
        for _ in pool.imap_unordered(_run, [(j, weather, out, stamp) for j in todo]):
            pass
    return 0


def group(r: dict) -> str:
    """The summers a backtest is reported among: the margin's first site and years apart
    from its later ones, each other site its own, the sealed ones named so."""
    if r["site"] == TUNED[0]:
        return (f"McAllister {TUNED[1][0]}–{TUNED[1][-1]}" if r["year"] in TUNED[1]
                else f"McAllister {TUNED[1][-1] + 1}–{YEARS[-1]}")
    name = r["site"].capitalize()
    return name if r["site"] in OPEN_SITES else f"{name} (sealed)"


def _interval(diffs: list, rng: random.Random) -> tuple:
    """The mean of `diffs` and its 90% interval, by resampling them `BOOTSTRAP` times."""
    n = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(BOOTSTRAP))
    return sum(diffs) / n, means[int(0.05 * BOOTSTRAP)], means[int(0.95 * BOOTSTRAP) - 1]


def _choices(choices: dict) -> str:
    return json.dumps(sorted(choices.items()))


def _shown(value) -> str:
    return f"{value:.2g}" if isinstance(value, float) else str(value)


def _lost_share(r: dict) -> float:
    return 100.0 * r["transpiration_lost_mm"] / r["demand_mm"] if r.get("demand_mm") else 0.0


def report(path: str) -> str:
    """Markdown: each bed as built, then each choice and each measure against it."""
    rows = []
    with open(path, encoding="utf-8") as h:
        for line in h:
            rows.append(json.loads(line))
    stamps = sorted({r.get("stamp") for r in rows})
    by = {(r["bed"], _choices(r["choices"]), r["site"], r["year"], r["draw"]): r for r in rows}
    groups = sorted({group(r) for r in rows}, key=lambda g: ("sealed" in g, g))
    rng = random.Random(1)
    out = [f"Code: {', '.join(str(s) for s in stamps)}. Each summer one farm.", "",
           "| bed | summers | water | lost transpiration | share of demand | summers losing "
           "over 1% | hours waterlogged | ran off | stored at the end |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for bed, options in BEDS.items():
        built = _choices({n: DEFAULTS[n] for n in options})
        for g in groups:
            got = [r for k, r in by.items() if k[0] == bed and k[1] == built and group(r) == g]
            if not got:
                continue
            n = len(got)
            mean = lambda k: sum(r.get(k) or 0.0 for r in got) / n
            out.append(f"| {bed}, {g} | {n} | {mean('applied_mm'):.0f} mm | "
                       f"{mean('transpiration_lost_mm'):.1f} mm | "
                       f"{sum(_lost_share(r) for r in got) / n:.1f}% | "
                       f"{sum(1 for r in got if _lost_share(r) > 1.0)} | "
                       f"{mean('waterlogged_h'):.0f} | {mean('runoff_mm'):.0f} mm | "
                       f"{mean('stored_change_mm'):+.0f} mm |")
    out += ["", "| bed | against the bed as built | summers | water | lost transpiration | "
            "hours waterlogged |", "| --- | --- | --- | --- | --- | --- |"]
    for bed, options in BEDS.items():
        base = {n: DEFAULTS[n] for n in options}
        for tried in configs(bed):
            if tried == base:
                continue
            what = [SAID[n].format(_shown(tried[n])) for n in sorted(tried) if n in OFF]
            what += [f"{n} {_shown(tried[n])}" for n in sorted(options) if tried[n] != DEFAULTS[n]]
            for g in groups:
                pairs = []
                for k, b in by.items():
                    if k[0] != bed or k[1] != _choices(tried) or group(b) != g:
                        continue
                    a = by.get((bed, _choices(base), k[2], k[3], k[4]))
                    if a:
                        pairs.append((a, b))
                if not pairs:
                    continue
                cells = []
                for score in ("applied_mm", "transpiration_lost_mm", "waterlogged_h"):
                    mean, lo, hi = _interval([(b.get(score) or 0.0) - (a.get(score) or 0.0)
                                              for a, b in pairs], rng)
                    cells.append(f"{mean:+.1f} ({lo:+.1f} to {hi:+.1f})")
                out.append(f"| {bed} | {', '.join(what)}, {g} | {len(pairs)} | "
                           + " | ".join(cells) + " |")
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
    r.add_argument("--sites", default=",".join(OPEN_SITES), help="comma-separated, of SITES")
    p = sub.add_parser("report")
    p.add_argument("results")
    args = ap.parse_args(argv)
    if args.command == "run":
        if args.cache:
            os.environ["FIELDMESH_FORECASTS"] = args.cache
        sites = tuple(s for s in args.sites.split(",") if s)
        if any(s not in SITES for s in sites):
            raise SystemExit(f"sites are of {sorted(SITES)}")
        return run(args.weather, args.out, args.workers, args.stamp, sites)
    print(report(args.results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

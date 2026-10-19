# SPDX-License-Identifier: Apache-2.0
"""A probe falls silent for 72 hours: how well is its 10 cm reading carried?

Real hourly records from three Tennessee SCAN stations (ISMN, flag G only), growing
seasons of 2015 to 2025. At random hours a window's next 72 hours of sm_10 are hidden and
filled by:

  persistence      the last reading held
  fieldmesh        the last reading less what the other probes (5 and 20 cm) dried since,
                   as soilwater._from_probes carries a silent probe; drying only
  neighbours       the last reading moved as the other probes moved, rises too
  regression       sm_10 fitted on the other probes over the context, least squares
  timestral        the model on sm_10's history alone
  timestral+wx     with the rain gauge and the air temperature through the gap
  timestral+wx+nb  with those and the 5 and 20 cm probes, which go on reading

and, to read what the model makes of rain, timestral+wx+nb again with the gap's rain set
to none. Scored by mean absolute error of the median (or the value) over the gap, the
quantile loss over the 21 levels, and how often the truth fell in the 10-90% band.

    python gapfill.py DATA_DIR OUT.json MODEL [N_PER_STATION] [CONTEXT_H]
"""
import csv
import datetime as dt
import json
import os
import random
import sys
import time

import numpy as np

DATA, OUT, MODEL = sys.argv[1], sys.argv[2], sys.argv[3]
N = int(sys.argv[4]) if len(sys.argv) > 4 else 150
CONTEXT = int(sys.argv[5]) if len(sys.argv) > 5 else 1024
TARGET = sys.argv[6] if len(sys.argv) > 6 else "sm_10"
NB = tuple(c for c in ("sm_05", "sm_10", "sm_20") if c != TARGET)
H = 72
COLS = ("sm_05", "sm_10", "sm_20", "rain_mm", "air_c")


def load(path):
    times, cols = [], {c: [] for c in COLS}
    with open(path) as h:
        for row in csv.DictReader(h):
            times.append(row["time"])
            for c in COLS:
                flag = row.get(c + "_flag", "")
                bad = flag != "" and flag.split(",")[0] != "G"       # ISMN's good only
                cols[c].append(float(row[c]) if row[c] != "" and not bad else np.nan)
    return times, {c: np.array(v, dtype=np.float64) for c, v in cols.items()}


def windows(times, cols, rng, n):
    """Hours t0 in Apr 15 to Oct 15 of 2015-2025 with sm_10 seen at t0-1 and through the
    gap, the context at least nine-tenths seen, and the covariates through the gap."""
    out, tries = [], 0
    candidates = [i for i, t in enumerate(times)
                  if "2015" <= t[:4] <= "2025" and "04-15" <= t[5:10] <= "10-15" and i > CONTEXT]
    while len(out) < n and tries < 200000:
        tries += 1
        i = rng.choice(candidates)
        if i + H > len(times):
            continue
        ctx, gap = slice(i - CONTEXT, i), slice(i, i + H)
        if np.isnan(cols[TARGET][i - 1]) or np.isnan(cols[TARGET][gap]).any():
            continue
        if np.isnan(cols[TARGET][ctx]).mean() > 0.1:
            continue
        if any(np.isnan(cols[c][gap]).any() for c in NB + ("rain_mm", "air_c")):
            continue
        if any(np.isnan(cols[c][i - 1]) for c in NB):
            continue
        out.append(i)
    return sorted(set(out))


def carried(cols, i):
    """fieldmesh's carried probe: the last reading less the others' drying since."""
    others = (cols[NB[0]] + cols[NB[1]]) / 2.0
    then = others[i - 1]
    now = others[i:i + H]
    return cols[TARGET][i - 1] - np.maximum(0.0, then - now)


def neighbours(cols, i):
    others = (cols[NB[0]] + cols[NB[1]]) / 2.0
    return cols[TARGET][i - 1] + (others[i:i + H] - others[i - 1])


def regression(cols, i):
    ctx = slice(i - CONTEXT, i)
    x = np.stack([np.ones(CONTEXT), cols[NB[0]][ctx], cols[NB[1]][ctx]], axis=1)
    y = cols[TARGET][ctx]
    ok = ~np.isnan(x).any(axis=1) & ~np.isnan(y)
    coef, *_ = np.linalg.lstsq(x[ok], y[ok], rcond=None)
    xg = np.stack([np.ones(H), cols[NB[0]][i:i + H], cols[NB[1]][i:i + H]], axis=1)
    return xg @ coef


def pinball(q, levels, y):
    """Mean quantile loss over the levels and the gap: (H, Q) against (H,)."""
    diff = y[:, None] - q
    lv = np.asarray(levels)[None, :]
    return float(np.mean(np.maximum(lv * diff, (lv - 1.0) * diff)))


def main():
    from timestral import TimestralForecaster
    forecaster = TimestralForecaster.from_pretrained(MODEL)
    rng = random.Random(1)
    results = []
    for f in sorted(os.listdir(DATA)):
        times, cols = load(os.path.join(DATA, f))
        idx = windows(times, cols, rng, N)
        print(f, len(idx), "windows", flush=True)
        target = np.stack([cols[TARGET][i - CONTEXT:i] for i in idx])[:, None, :]
        wx = lambda i, rain: np.stack([rain[i - CONTEXT:i + H], cols["air_c"][i - CONTEXT:i + H]])
        nb = lambda i: np.stack([cols[NB[0]][i - CONTEXT:i + H], cols[NB[1]][i - CONTEXT:i + H]])
        variants = {
            "timestral": {},
            "timestral+wx": {"known_covariates": np.stack([wx(i, cols["rain_mm"]) for i in idx])},
            "timestral+wx+nb": {"known_covariates": np.stack(
                [np.concatenate([wx(i, cols["rain_mm"]), nb(i)]) for i in idx])},
        }
        no_rain = []
        for i in idx:
            r = cols["rain_mm"].copy()
            r[i:i + H] = 0.0
            no_rain.append(np.concatenate([wx(i, r), nb(i)]))
        variants["timestral+wx+nb, no rain in the gap"] = {"known_covariates": np.stack(no_rain)}
        preds = {}
        for name, kw in variants.items():
            t = time.time()
            qs = []
            for b in range(0, len(idx), 16):
                sub = {k: v[b:b + 16] for k, v in kw.items()}
                fc = forecaster.forecast(target[b:b + 16], prediction_length=H, **sub)
                qs.append(np.asarray(fc.quantiles)[:, 0])
            preds[name] = np.concatenate(qs)
            levels = fc.quantile_levels
            print(f"  {name}: {time.time() - t:.1f} s", flush=True)
        for k, i in enumerate(idx):
            y = cols[TARGET][i:i + H]
            rain = float(np.nansum(cols["rain_mm"][i:i + H]))
            row = {"station": f[:-4], "time": times[i], "rain_in_gap_mm": rain,
                   "last": float(cols[TARGET][i - 1]), "end": float(y[-1])}
            row["persistence"] = {"mae": float(np.mean(np.abs(y - cols[TARGET][i - 1])))}
            c = carried(cols, i)
            row["fieldmesh"] = {"mae": float(np.mean(np.abs(y - c)))}
            row["neighbours"] = {"mae": float(np.mean(np.abs(y - neighbours(cols, i))))}
            row["regression"] = {"mae": float(np.mean(np.abs(y - regression(cols, i))))}
            lo, hi = levels.index(0.1), levels.index(0.9)
            for name, q in preds.items():
                q = q[k]
                med = q[:, levels.index(0.5)]
                row[name] = {"mae": float(np.mean(np.abs(y - med))),
                             "mae_24": float(np.mean(np.abs(y[:24] - med[:24]))),
                             "pinball": pinball(q, levels, y),
                             "covered": float(np.mean((y >= q[:, lo]) & (y <= q[:, hi]))),
                             "median_end": float(med[-1])}
            results.append(row)
    with open(OUT, "w") as h:
        json.dump({"model": MODEL, "context_h": CONTEXT, "horizon_h": H, "target": TARGET,
                   "windows": results}, h)
    print("wrote", OUT, len(results), "windows")


if __name__ == "__main__":
    main()

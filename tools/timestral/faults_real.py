# SPDX-License-Identifier: Apache-2.0
"""Readings ISMN's quality algorithm flagged at 10 cm: does the model's band catch them,
and how often does it catch a reading ISMN rates good?

For each event in 2015 to 2025 (a run of hours flagged D06 spike, D07 drop, D08 jump, D10
saturated plateau or C03 above what the soil holds), the model forecasts 24 hours from the
1024 good hours before it, with the 5 and 20 cm probes, the rain and the air through them;
the event is caught if a flagged reading among its first 24 hours lies outside the 1-99%
band. The peer check: off the regression on the other probes by more than 0.03. The same
two on as many random hours whose next 24 readings are all good, for false alarms.

    python faults_real.py DATA_DIR OUT.json MODEL
"""
import csv
import json
import os
import random
import sys

import numpy as np
import torch

DATA, OUT, MODEL = sys.argv[1], sys.argv[2], sys.argv[3]
torch.set_num_threads(4)
torch.set_num_interop_threads(1)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = [sys.argv[0], DATA, "/dev/null", MODEL, "1", "1024"]
import gapfill as G
from timestral import TimestralForecaster

C, H, TOL = 1024, 24, 0.03
KINDS = ("D06", "D07", "D08", "D10", "C03")


def raw(path):
    """sm_10 as reported, and its flags."""
    vals, flags = [], []
    for r in csv.DictReader(open(path)):
        vals.append(float(r["sm_10"]) if r["sm_10"] else np.nan)
        flags.append(r["sm_10_flag"])
    return np.array(vals), flags


def main():
    f = TimestralForecaster.from_pretrained(MODEL)
    rng = random.Random(3)
    rows = []
    for name in sorted(os.listdir(DATA)):
        times, cols = G.load(os.path.join(DATA, name))          # good readings only
        values, flags = raw(os.path.join(DATA, name))
        events, i = [], C
        while i < len(times) - H:
            kind = next((k for k in KINDS if k in flags[i].split(",")), None)
            if kind and "2015" <= times[i][:4] <= "2025" and kind not in flags[i - 1].split(","):
                if (np.isnan(cols["sm_10"][i - C:i]).mean() < 0.1
                        and not any(np.isnan(cols[c][i:i + H]).any() for c in ("sm_05", "sm_20", "rain_mm", "air_c"))):
                    events.append((i, kind))
                    i += H
                    continue
            i += 1
        clean = []
        candidates = [j for j in range(C, len(times) - H) if "2015" <= times[j][:4] <= "2025"]
        while len(clean) < len(events) and candidates:
            j = rng.choice(candidates)
            if (all(fl.split(",")[0] == "G" for fl in flags[j:j + H])
                    and np.isnan(cols["sm_10"][j - C:j]).mean() < 0.1
                    and not any(np.isnan(cols[c][j:j + H]).any() for c in ("sm_05", "sm_20", "rain_mm", "air_c"))):
                clean.append((j, "clean"))
        cases = events + clean
        print(name, len(events), "events", len(clean), "clean", flush=True)
        for b in range(0, len(cases), 16):
            batch = cases[b:b + 16]
            target = np.stack([cols["sm_10"][i - C:i] for i, _ in batch])[:, None, :]
            cov = np.stack([np.stack([cols["rain_mm"][i - C:i + H], cols["air_c"][i - C:i + H],
                                      cols["sm_05"][i - C:i + H], cols["sm_20"][i - C:i + H]]) for i, _ in batch])
            fc = f.forecast(target, prediction_length=H, known_covariates=cov)
            q = np.asarray(fc.quantiles)[:, 0]
            lv = list(fc.quantile_levels)
            lo, hi = lv.index(0.01), lv.index(0.99)
            for k, (i, kind) in enumerate(batch):
                x = values[i:i + H]
                if kind == "clean":
                    judged = np.ones(H, dtype=bool)
                else:
                    judged = np.array([any(c in flags[i + h].split(",") for c in KINDS) for h in range(H)])
                ok = judged & ~np.isnan(x)
                band = (x < q[k][:, lo]) | (x > q[k][:, hi])
                peer = np.abs(x - _peer(cols, i)) > TOL
                rows.append({"station": name[:-4], "time": times[i], "kind": kind,
                             "timestral": bool((band & ok).any()), "peer": bool((peer & ok).any()),
                             "hours_judged": int(ok.sum())})
    json.dump(rows, open(OUT, "w"))
    for kind in ("clean",) + KINDS:
        sel = [r for r in rows if r["kind"] == kind]
        if sel:
            print(f"{kind:6} {len(sel):5}: timestral {100 * np.mean([r['timestral'] for r in sel]):.0f}%"
                  f" | peer {100 * np.mean([r['peer'] for r in sel]):.0f}%")


def _peer(cols, i):
    ctx = slice(i - C, i)
    x = np.stack([np.ones(C), cols["sm_05"][ctx], cols["sm_20"][ctx]], axis=1)
    y = cols["sm_10"][ctx]
    good = ~np.isnan(x).any(axis=1) & ~np.isnan(y)
    coef, *_ = np.linalg.lstsq(x[good], y[good], rcond=None)
    return np.stack([np.ones(H), cols["sm_05"][i:i + H], cols["sm_20"][i:i + H]], axis=1) @ coef


if __name__ == "__main__":
    main()

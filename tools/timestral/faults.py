# SPDX-License-Identifier: Apache-2.0
"""A probe goes wrong: who sees it first, and who cries wolf?

The same windows as gapfill.py. Over the 72 hours after t0 the 10 cm reading is left as
it was (clean, for false alarms) or made stuck at its last value, stepped up 0.05, or
drifted up to 0.06 by the end. Three detectors read the 72 hours:

  timestral   the model, from the clean history before t0 and the rain gauge, the air and
              the 5 and 20 cm probes through the 72 hours, forecasts sm_10; a reading
              outside its 1-99% band for 3 hours running is a fault
  peer        the reading against the regression on the other probes (gapfill.py): off by
              more than `PEER_TOL` for 3 hours running
  flatline    layer zero's: no change for 18 hours (`ismn_score.OUR_THRESHOLDS`)

    python faults.py DATA_DIR OUT.json MODEL [N_PER_STATION]
"""
import json
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gapfill as G

DATA, OUT, MODEL = sys.argv[1], sys.argv[2], sys.argv[3]
N = int(sys.argv[4]) if len(sys.argv) > 4 else 150
H, RUN, PEER_TOL, FLAT_H = 72, 3, 0.03, 18
FAULTS = ("clean", "stuck", "step", "drift")


def faulted(y, last, kind):
    t = np.arange(len(y))
    if kind == "stuck":
        return np.full_like(y, last)
    if kind == "step":
        return y + 0.05
    if kind == "drift":
        return y + 0.06 * (t + 1) / len(y)
    return y.copy()


def first_run(flags, run=RUN):
    count = 0
    for k, f in enumerate(flags):
        count = count + 1 if f else 0
        if count >= run:
            return k
    return None


def flatline(x, last):
    seq = np.concatenate([[last], x])
    same = np.abs(np.diff(seq)) < 1e-9
    return first_run(same, FLAT_H)


def main():
    import torch
    torch.set_num_threads(4)              # four threads, no more, and no spare pool
    torch.set_num_interop_threads(1)
    from timestral import TimestralForecaster
    G.CONTEXT = 1024
    forecaster = TimestralForecaster.from_pretrained(MODEL)
    rng = random.Random(2)
    out = []
    for f in sorted(os.listdir(DATA)):
        times, cols = G.load(os.path.join(DATA, f))
        idx = G.windows(times, cols, rng, N)
        target = np.stack([cols["sm_10"][i - 1024:i] for i in idx])[:, None, :]
        cov = np.stack([np.stack([cols["rain_mm"][i - 1024:i + H], cols["air_c"][i - 1024:i + H],
                                  cols["sm_05"][i - 1024:i + H], cols["sm_20"][i - 1024:i + H]])
                        for i in idx])
        qs = []
        for b in range(0, len(idx), 16):
            fc = forecaster.forecast(target[b:b + 16], prediction_length=H, known_covariates=cov[b:b + 16])
            qs.append(np.asarray(fc.quantiles)[:, 0])
        qs = np.concatenate(qs)
        levels = fc.quantile_levels
        lo, hi = levels.index(0.01), levels.index(0.99)
        print(f, len(idx), "windows", flush=True)
        for k, i in enumerate(idx):
            y, last = cols["sm_10"][i:i + H], cols["sm_10"][i - 1]
            peer_pred = G.regression(cols, i)
            for kind in FAULTS:
                x = faulted(y, last, kind)
                out.append({"station": f[:-4], "time": times[i], "fault": kind,
                            "timestral": first_run((x < qs[k][:, lo]) | (x > qs[k][:, hi])),
                            "peer": first_run(np.abs(x - peer_pred) > PEER_TOL),
                            "flatline": flatline(x, last)})
    with open(OUT, "w") as h:
        json.dump({"model": MODEL, "rows": out}, h)
    for kind in FAULTS:
        rows = [r for r in out if r["fault"] == kind]
        cells = []
        for det in ("timestral", "peer", "flatline"):
            hits = [r[det] for r in rows if r[det] is not None]
            cells.append(f"{det} {100 * len(hits) / len(rows):.0f}%"
                         + (f" (median {np.median(hits):.0f} h)" if hits else ""))
        print(f"{kind:6} {len(rows):4}: " + " | ".join(cells))


if __name__ == "__main__":
    main()

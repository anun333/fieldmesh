# SPDX-License-Identifier: Apache-2.0
"""Check gapfill.py's numbers, written apart from it.

1. The same gaps, chosen again from the same seed, forecast again by the 28M model, and
   scored by this script's own arithmetic; set beside gap-28M.json's per-gap errors.
2. Three gaps printed hour by hour: the truth, the neighbours' rule, the model's median
   and band.
3. Leakage: the neighbouring probes shifted a week earlier (168 h), the rain and air left
   true. If the model's edge is the neighbours' real information, it collapses.

    python verify.py /data /out/gap-28M.json mistralai/Timestral-28M
"""
import json
import os
import random
import sys

import numpy as np
import torch

DATA, SAVED, MODEL = sys.argv[1], sys.argv[2], sys.argv[3]
torch.set_num_threads(4)
torch.set_num_interop_threads(1)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = [sys.argv[0], DATA, "/dev/null", MODEL, "200", "1024"]
import gapfill as G                                         # the windows and loader only
from timestral import TimestralForecaster

H, C = 72, 1024
saved = json.load(open(SAVED))["windows"]
f = TimestralForecaster.from_pretrained(MODEL)
rng = random.Random(1)                                     # as gapfill.main draws them
recomputed, shifted, printed = [], [], 0
for name in sorted(os.listdir(DATA)):
    times, cols = G.load(os.path.join(DATA, name))
    idx = G.windows(times, cols, rng, 200)
    keep = [i for i in idx if i - C - 168 >= 0]
    def cov(i, lag):
        return np.stack([cols["rain_mm"][i - C:i + H], cols["air_c"][i - C:i + H],
                         cols["sm_05"][i - C - lag:i + H - lag], cols["sm_20"][i - C - lag:i + H - lag]])
    for lag, out in ((0, recomputed), (168, shifted)):
        target = np.stack([cols["sm_10"][i - C:i] for i in keep])[:, None, :]
        cv = np.stack([cov(i, lag) for i in keep])
        for b in range(0, len(keep), 16):
            fc = f.forecast(target[b:b + 16], prediction_length=H, known_covariates=cv[b:b + 16])
            q = np.asarray(fc.quantiles)[:, 0]
            mid = list(fc.quantile_levels).index(0.5)
            for k, i in enumerate(keep[b:b + 16]):
                truth = cols["sm_10"][i:i + H]
                err = float(np.abs(truth - q[k][:, mid]).sum() / H)
                out.append((name[:-4], times[i], err))
                if lag == 0 and printed < 3 and np.nansum(cols["rain_mm"][i:i + H]) > 5:
                    printed += 1
                    others = (cols["sm_05"] + cols["sm_20"]) / 2.0
                    rule = cols["sm_10"][i - 1] + others[i:i + H] - others[i - 1]
                    lo, hi = list(fc.quantile_levels).index(0.1), list(fc.quantile_levels).index(0.9)
                    print(f"\n{name[:-4]} from {times[i]}, rain in the gap {np.nansum(cols['rain_mm'][i:i + H]):.1f} mm,"
                          f" last reading {cols['sm_10'][i - 1]:.3f}")
                    print("  hour  truth  rule   median  10%    90%")
                    for h in (0, 6, 12, 24, 36, 48, 71):
                        print(f"  {h:4}  {truth[h]:.3f}  {rule[h]:.3f}  {q[k][h, mid]:.3f}   {q[k][h, lo]:.3f}  {q[k][h, hi]:.3f}")

by = {(r["station"], r["time"]): r["timestral+wx+nb"]["mae"] for r in saved}
pairs = [(e, by[(s, t)]) for s, t, e in recomputed if (s, t) in by]
diffs = np.array([a - b for a, b in pairs])
print(f"\n1. recomputed {len(pairs)} gaps: mean error {np.mean([a for a, _ in pairs]):.5f}, "
      f"saved {np.mean([b for _, b in pairs]):.5f}, largest per-gap difference {np.max(np.abs(diffs)):.2e}")
print(f"3. neighbours a week off: mean error {np.mean([e for *_, e in shifted]):.5f}, "
      f"against {np.mean([e for *_, e in recomputed]):.5f} with them true")

# SPDX-License-Identifier: Apache-2.0
"""Slow drifts, judged against a stretch kept from before them (2026-10-20): the 10 cm
probe drifting 0.02 over 14 days, 0.03 over 28 and 0.03 over 56, wetter and drier, judged
at the drift's end; and clean, for false alarms. Three looks, each against a trusted
stretch that ended 60 days before:

  soak        the 10 cm probe's reading 24 hours after each day of 15 mm of rain or more
              stops, less the 5 and 20 cm probes' mean then; off when the soaks of the last
              60 days differ from those of the 180 before by more than 0.015 (one recent and
              two before needed, else it cannot judge)
  regression  the 10 cm probe on the 5 and 20 cm probes fitted over the 60 days that ended
              60 days before; off when its mean residual over the last week passes 0.015
  timestral   the 10 cm probe as silent since the trusted stretch, forecast from its 1,024
              hours before then with the other probes, the rain and the air; off when the
              last week's readings lie outside the 1-99% band 24 hours running

    python slow_drift.py STATION.csv OUT.json N [MODEL]

On a station's record as extract.py writes it; only water readings ISMN flagged good."""
import csv
import datetime as dt
import json
import os
import random
import sys

import numpy as np

SRC, OUT, N = sys.argv[1], sys.argv[2], int(sys.argv[3])
MODEL = sys.argv[4] if len(sys.argv) > 4 else "mistralai/Timestral-28M"
H, D = 1, 24
CTX, WEEK = 1024, 7 * D
TRUST = 60 * D                      # the trusted stretch ends this long before the judgment
REG_FIT = 60 * D                    # the regression's fit, the 60 days before that
SOAK_BEFORE = 180 * D               # the soaks before the trusted stretch's end
SOAK_MM, SHIFT, RUN_H = 15.0, 0.015, 24
BAND = (0.01, 0.99)
DRIFTS = tuple((s * total, days) for total, days in ((0.02, 14), (0.03, 28), (0.03, 56)) for s in (1, -1))
BACK = TRUST + SOAK_BEFORE + CTX + 30
COLS = ("sm_05", "sm_10", "sm_20", "rain_mm", "air_c")

times, raw = [], {c: [] for c in COLS}
with open(SRC, newline="") as h:
    for row in csv.DictReader(h):
        times.append(dt.datetime.fromisoformat(row["time"]))
        for c in COLS:
            v = row.get(c, "")
            good = not c.startswith("sm_") or row.get(f"{c}_flag", "").split(",")[0] in ("", "G")
            raw[c].append(float(v) if v != "" and good else np.nan)
cols = {c: np.array(v) for c, v in raw.items()}
rain_day = {}
for k, t in enumerate(times):
    if not np.isnan(cols["rain_mm"][k]):
        rain_day[t.date()] = rain_day.get(t.date(), 0.0) + cols["rain_mm"][k]


def present(i):
    k0 = i - BACK
    if k0 < 0 or times[i - 1] - times[k0] != (i - 1 - k0) * dt.timedelta(hours=1):
        return False
    if any(np.isnan(cols[c][i - WEEK:i]).any() for c in COLS):
        return False
    return all(np.isnan(cols[c][k0:i]).mean() <= 0.1 for c in COLS)


def drifted(i, total, days):
    out = cols["sm_10"].copy()
    n = days * D
    out[i - n:i] += total * np.arange(1, n + 1) / n
    return out


def soak(sm10, i):
    """`(off, judged)`."""
    recent, before = [], []
    first = times[i - TRUST - SOAK_BEFORE].date()
    for day in sorted(d for d, mm in rain_day.items() if mm >= SOAK_MM and first <= d < times[i - 1].date()):
        k = next((k for k in range(i - TRUST - SOAK_BEFORE, i) if times[k].date() == day), None)
        if k is None:
            continue
        stop = max((j for j in range(k, min(k + D, i)) if cols["rain_mm"][j] > 0), default=None)
        if stop is None or stop + D >= i:
            continue
        t = stop + D
        diff = sm10[t] - (cols["sm_05"][t] + cols["sm_20"][t]) / 2.0
        if np.isnan(diff):
            continue
        (recent if t >= i - TRUST else before).append(diff)
    if len(recent) < 1 or len(before) < 2:
        return False, False
    return bool(abs(np.mean(recent) - np.mean(before)) > SHIFT), True


def regression(sm10, i):
    fit = slice(i - TRUST - REG_FIT, i - TRUST)
    x = np.stack([np.ones(REG_FIT), cols["sm_05"][fit], cols["sm_20"][fit]], axis=1)
    y = sm10[fit]
    ok = ~np.isnan(x).any(axis=1) & ~np.isnan(y)
    coef, *_ = np.linalg.lstsq(x[ok], y[ok], rcond=None)
    week = slice(i - WEEK, i)
    xw = np.stack([np.ones(WEEK), cols["sm_05"][week], cols["sm_20"][week]], axis=1)
    return abs(np.nanmean(sm10[week] - xw @ coef)) > SHIFT


def timestral(sm10, i):
    end = i - TRUST
    covs = np.array([cols[c][end - CTX:i] for c in ("sm_05", "sm_20", "rain_mm", "air_c")])[None]
    out = forecaster.forecast(sm10[end - CTX:end][None, None, :], prediction_length=TRUST,
                              known_covariates=covs)
    q = np.asarray(out.quantiles)[0, 0]
    lv = list(out.quantile_levels)
    lo, hi = q[-WEEK:, lv.index(BAND[0])], q[-WEEK:, lv.index(BAND[1])]
    run = longest = 0
    for r, a, b in zip(sm10[i - WEEK:i], lo, hi):
        run = run + 1 if not np.isnan(r) and not a <= r <= b else 0
        longest = max(longest, run)
    return longest >= RUN_H


from timestral import TimestralForecaster  # noqa: E402
import torch  # noqa: E402
torch.set_num_threads(4)
forecaster = TimestralForecaster.from_pretrained(MODEL)
rng = random.Random(7)
starts = list(range(BACK, len(times), 97))
rng.shuffle(starts)
results = []
for i in starts:
    if len(results) >= N:
        break
    if not present(i):
        continue
    r = {"judged_at": times[i - 1].isoformat()}
    for label, sm10 in [("clean", cols["sm_10"])] + [(f"{total:+.2f} over {days} d", drifted(i, total, days))
                                                      for total, days in DRIFTS]:
        off, judged = soak(sm10, i)
        r[label] = {"soak": off, "soak_judged": judged, "regression": bool(regression(sm10, i)),
                    "timestral": bool(timestral(sm10, i))}
    results.append(r)
    print(json.dumps(r), flush=True)

methods = ("soak", "regression", "timestral")
drift_keys = [f"{total:+.2f} over {days} d" for total, days in DRIFTS]
share = lambda xs: sum(xs) / len(xs) if xs else None
summary = {"station": os.path.basename(SRC), "n": len(results),
           "caught": {m: share([r[k][m] for r in results for k in drift_keys]) for m in methods},
           "clean_off": {m: share([r["clean"][m] for r in results]) for m in methods},
           "soak_judged": share([r["clean"]["soak_judged"] for r in results]),
           "by_drift": {k: {m: share([r[k][m] for r in results]) for m in methods} for k in drift_keys}}
print(json.dumps(summary, indent=1))
with open(OUT, "w") as h:
    json.dump({"summary": summary, "results": results}, h, indent=1)

# SPDX-License-Identifier: Apache-2.0
"""A probe silent through a storm: the 10 cm probe hidden 72 hours that hold 20 mm of rain
or more, carried by the forecast, by the forecast also given the rain since the silence
began, by fieldmesh's rule, and held, against the truth.

    python storms.py DATA_DIR OUT.json [MODEL] [N_PER_STATION]

Silences are chosen as gapfill.py chooses them (every series present through the silence,
no more than a tenth missing before), at 06:00 each day, those with the rain; at most N a
station, drawn with a fixed seed. Only readings ISMN flagged good count. The rule is
`soilwater`'s arithmetic for a carried probe with the two others weighed alike: drier as
both have dried since its last reading, wetter only as the one below has wetted."""
import csv
import datetime as dt
import json
import os
import random
import sys

import numpy as np

DATA, OUT = sys.argv[1], sys.argv[2]
MODEL = sys.argv[3] if len(sys.argv) > 3 else "mistralai/Timestral-28M"
N = int(sys.argv[4]) if len(sys.argv) > 4 else 60
CTX, GAP, STORM_MM = 1024, 72, 20.0
HOUR = dt.timedelta(hours=1)


def load(path):
    times, cols = [], {c: [] for c in ("sm_05", "sm_10", "sm_20", "rain_mm", "air_c")}
    with open(path, newline="") as h:
        for row in csv.DictReader(h):
            times.append(dt.datetime.fromisoformat(row["time"]))
            for c in cols:
                v = row[c]
                good = not c.startswith("sm_") or row.get(f"{c}_flag", "G").split(",")[0] in ("", "G")
                cols[c].append(float(v) if v != "" and good else np.nan)
    return times, {c: np.array(v) for c, v in cols.items()}


def rule(cols, i):
    last = cols["sm_10"][i - 1]
    d05 = cols["sm_05"][i:i + GAP] - cols["sm_05"][i - 1]
    d20 = cols["sm_20"][i:i + GAP] - cols["sm_20"][i - 1]
    return last + np.minimum(0.0, (d05 + d20) / 2.0) + np.maximum(0.0, d20)


def main():
    from timestral import TimestralForecaster
    import torch
    torch.set_num_threads(4)
    f = TimestralForecaster.from_pretrained(MODEL)
    rng = random.Random(7)
    out = []
    for name in sorted(os.listdir(DATA)):
        times, cols = load(os.path.join(DATA, name))
        found = []
        for i in range(CTX + 1, len(times) - GAP):
            if times[i].hour != 6 or np.nansum(cols["rain_mm"][i:i + GAP]) < STORM_MM:
                continue
            if any(np.isnan(cols[c][i - 1:i + GAP]).any() for c in cols):
                continue
            if np.isnan(cols["sm_10"][i - CTX:i]).mean() > 0.1:
                continue
            found.append(i)
        rng.shuffle(found)
        found = sorted(found[:N])
        print(name, len(found), "storm silences", flush=True)
        for i in found:
            target = cols["sm_10"][i - CTX:i][None, None, :]
            span = slice(i - CTX, i + GAP)
            base = [cols["sm_05"][span], cols["sm_20"][span], cols["rain_mm"][span], cols["air_c"][span]]
            since = np.concatenate([np.zeros(CTX), np.cumsum(cols["rain_mm"][i:i + GAP])])
            truth = cols["sm_10"][i:i + GAP]
            row = {"station": name, "start": times[i].isoformat(),
                   "rain_mm": round(float(np.nansum(cols["rain_mm"][i:i + GAP])), 1),
                   "truth_rise": round(float(np.nanmax(truth) - cols["sm_10"][i - 1]), 4)}
            for label, covs in (("forecast", base), ("forecast + rain since", base + [since])):
                fc = f.forecast(target, prediction_length=GAP, known_covariates=np.array(covs)[None])
                m = np.asarray(fc.quantiles)[0, 0][:, list(fc.quantile_levels).index(0.5)]
                row[label] = {"mae": float(np.mean(np.abs(m - truth))), "end": float(m[-1] - truth[-1])}
            for label, est in (("rule", rule(cols, i)), ("held", np.full(GAP, cols["sm_10"][i - 1]))):
                row[label] = {"mae": float(np.mean(np.abs(est - truth))), "end": float(est[-1] - truth[-1])}
            out.append(row)
    methods = ("forecast", "forecast + rain since", "rule", "held")
    summary = {"silences": len(out), **{m: {"mae": float(np.mean([r[m]["mae"] for r in out])),
                                            "end_bias": float(np.mean([r[m]["end"] for r in out])),
                                            "end_abs": float(np.mean([abs(r[m]["end"]) for r in out]))}
                                        for m in methods},
               "forecast_beats_rule": sum(r["forecast"]["mae"] < r["rule"]["mae"] for r in out)}
    print(json.dumps(summary, indent=1))
    with open(OUT, "w") as h:
        json.dump({"summary": summary, "silences": out}, h, indent=1)


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: Apache-2.0
"""The day ahead with the NWS forecast as the known future: McAllister Farm's 10 cm probe,
silent 72 hours before each NWS issue a farm collected, forecast 24 hours past it.

    python ahead_nws.py ISMN.csv SCAN.jsonl NWS.jsonl OUT.json [MODEL]

The station's hours from ISMN's archive (extract.py) to its end, then from the live log
`tools/scan_collect.py` fills (percent, degF and inches, converted); their shared hours
are compared first, and the run stops if they disagree. For each issue (`tools/
forecast_collect.py`), the 10 cm probe's 24 hours after it, forecast from its 1,024 hours
before the silence with the 5 and 20 cm probes, the rain and the air: (a) as built, every
input missing past the issue; (d) with the issue's own rain and temperature through the
day ahead; against (c) the forecast at the issue held."""
import csv
import datetime as dt
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "sdk"))
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from model import DatastreamKind, Usable  # noqa: E402

HOUR = dt.timedelta(hours=1)
CTX, GAP, AHEAD = 1024, 72, 24
SRC, SCAN, NWS, OUT = sys.argv[1:5]
MODEL = sys.argv[5] if len(sys.argv) > 5 else "mistralai/Timestral-28M"
DEPTHS = {"sm_05": 0.0508, "sm_10": 0.1016, "sm_20": 0.2032}
UNIT = {"%": lambda v: v / 100.0, "[degF]": lambda f: (f - 32.0) * 5.0 / 9.0,
        "[in_i]": lambda i: i * 25.4, "mm": lambda v: v, "Cel": lambda c: c}


def hour(t):
    return t.replace(minute=0, second=0, microsecond=0)


series = {c: {} for c in ("sm_05", "sm_10", "sm_20", "rain_mm", "air_c")}
with open(SRC, newline="") as h:
    for row in csv.DictReader(h):
        t = dt.datetime.fromisoformat(row["time"])
        for c in series:
            if row[c] != "":
                series[c][t] = float(row[c])
ismn_end = max(series["sm_10"])

live = {c: {} for c in series}
state = P.state_from_log(L.Log(SCAN))
now = dt.datetime.now(tz=dt.timezone.utc)
for ds in state.datastreams.values():
    if ds.kind is DatastreamKind.FORECAST:
        continue
    inst = state.installation_of(ds.sensor, now)
    name = None
    if ds.observed_property == V.SOIL_WATER and inst is not None:
        name = next((c for c, d in DEPTHS.items() if abs(inst.depth_m - d) < 0.005), None)
    elif ds.observed_property == V.PRECIPITATION_DEPTH:
        name = "rain_mm"
    elif ds.observed_property == V.AIR_TEMPERATURE:
        name = "air_c"
    if name is None:
        continue
    for o in state.live_observations_of(ds.id):
        if isinstance(o.result, (int, float)) and state.quality_as_of(o.id, now)[0] is Usable.GOOD:
            live[name][hour(o.measured_at)] = UNIT[ds.unit](float(o.result))

shared = {c: sorted(set(series[c]) & set(live[c])) for c in series}
agreement = {c: (len(ts), float(np.max(np.abs([series[c][t] - live[c][t] for t in ts]))) if ts else None)
             for c, ts in shared.items()}
print("the shared hours, and the most they differ:", agreement, flush=True)
TOLERANCE = {"sm_05": 0.005, "sm_10": 0.005, "sm_20": 0.005, "rain_mm": 0.5, "air_c": 0.6}
if any(n == 0 or diff > TOLERANCE[c] for c, (n, diff) in agreement.items()):
    raise SystemExit("ISMN's hours and the live log's disagree; not joined")
for c in series:
    series[c].update({t: v for t, v in live[c].items() if t > ismn_end})

nws = P.state_from_log(L.Log(NWS))
issues = {}
for ds in nws.datastreams.values():
    if ds.kind is not DatastreamKind.FORECAST:
        continue
    name = {V.PRECIPITATION_DEPTH: "rain_mm", V.AIR_TEMPERATURE: "air_c"}.get(ds.observed_property)
    if name is None:
        continue
    for o in nws.observations_of(ds.id):
        if isinstance(o.result, (int, float)):
            issues.setdefault(o.issued_at, {}).setdefault(name, {})[hour(o.measured_at)] = UNIT[ds.unit](float(o.result))

from timestral import TimestralForecaster  # noqa: E402
import torch  # noqa: E402
torch.set_num_threads(4)
forecaster = TimestralForecaster.from_pretrained(MODEL)


def row(c, first, n, known_until=None, future=None):
    out = []
    for k in range(n):
        t = first + k * HOUR
        if known_until is None or t <= known_until:
            out.append(series[c].get(t, np.nan))
        else:
            out.append((future or {}).get(t, np.nan))
    return out


results = []
last_hour = max(series["sm_10"])
for issued, fc in sorted(issues.items()):
    at = hour(issued)
    start = at - (GAP - 1) * HOUR                  # the 10 cm probe silent from here
    end = at + AHEAD * HOUR
    if end > last_hour or "rain_mm" not in fc or "air_c" not in fc:
        continue
    first = start - CTX * HOUR
    horizon = GAP + AHEAD - 1 + 1
    target = np.array([row("sm_10", first, CTX)], dtype=np.float64)[None]
    medians = {}
    for name, weather in (("as_built", None), ("nws", fc)):
        cov = np.array([row("sm_05", first, CTX + horizon, at), row("sm_20", first, CTX + horizon, at),
                        row("rain_mm", first, CTX + horizon, at, weather and weather["rain_mm"]),
                        row("air_c", first, CTX + horizon, at, weather and weather["air_c"])])[None]
        out = forecaster.forecast(target, prediction_length=horizon, known_covariates=cov)
        q = np.asarray(out.quantiles)[0, 0]
        medians[name] = q[:, list(out.quantile_levels).index(0.5)]
    truth = np.array(row("sm_10", start, horizon))
    ahead = slice(GAP, GAP + AHEAD)
    if np.isnan(truth[ahead]).any():
        continue
    results.append({"issued_at": issued.isoformat(),
                    "rain_ahead_mm": round(sum(fc["rain_mm"].get(at + (k + 1) * HOUR, 0.0) for k in range(AHEAD)), 1),
                    "fell_mm": round(sum(series["rain_mm"].get(at + (k + 1) * HOUR, 0.0) for k in range(AHEAD)), 1),
                    "mae": {"as_built": float(np.nanmean(np.abs(medians["as_built"][ahead] - truth[ahead]))),
                            "nws": float(np.nanmean(np.abs(medians["nws"][ahead] - truth[ahead]))),
                            "held": float(np.nanmean(np.abs(medians["as_built"][GAP - 1] - truth[ahead])))}})
    print(json.dumps(results[-1]), flush=True)
summary = {"issues": len(results), "agreement": agreement,
           "mae": {k: float(np.mean([r["mae"][k] for r in results])) for k in ("as_built", "nws", "held")}
           if results else None}
print(json.dumps(summary, indent=1))
with open(OUT, "w") as h:
    json.dump({"summary": summary, "results": results}, h, indent=1)

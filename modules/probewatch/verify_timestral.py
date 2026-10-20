# SPDX-License-Identifier: AGPL-3.0-or-later
"""The add-on through fieldmesh's own code (sdk/tsfm.py, tools/probe_forecast.py,
probewatch.probe_context) against the real Timestral-28M, on a station's record as
tools/timestral/extract.py writes it. Here, not in tools/timestral/, because it imports this
module, and layer zero never imports a module (tools/test_layering.py).

    python verify_timestral.py STATION.csv OUT.json N

For N stretches chosen as gapfill.py chose its gaps: the 10 cm probe hidden 72 hours, forecast by
`forecast_silent` into a fieldmesh state, and checked against
  (a) the truth, and the last reading held (persistence);
  (b) the same forecast made by calling the forecaster directly, as the trial did, with the
      same arrays: it must match bit for bit;
  (c) finite values through the day ahead, where the covariates are missing.
Then `probe_context` on the day before, clean and with a drift put in."""
import csv
import datetime as dt
import json
import os
import random
import sys
import time

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir)
sys.path[:0] = [os.path.join(REPO, p) for p in ("sdk", "tools", "modules/probewatch")]
import numpy as np  # noqa: E402

import fixtures as FX  # noqa: E402
import log as L  # noqa: E402
import probe_forecast as PF  # noqa: E402
import probewatch as PW  # noqa: E402
import tsfm as TS  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import Installation  # noqa: E402
from project import State  # noqa: E402

HOUR = dt.timedelta(hours=1)
SRC, OUT, N = sys.argv[1], sys.argv[2], int(sys.argv[3])
GAP, AHEAD, CTX = 72, 24, TS.CONTEXT_H
COLS = ("sm_05", "sm_10", "sm_20", "rain_mm", "air_c")

times, cols = [], {c: [] for c in COLS}
with open(SRC, newline="") as h:
    for row in csv.DictReader(h):
        times.append(dt.datetime.fromisoformat(row["time"]))
        for c in COLS:
            cols[c].append(float(row[c]) if row[c] != "" else None)
index = {t: k for k, t in enumerate(times)}


def present(k0, i, k1):
    """Hourly rows from k0 to k1; as gapfill.py chose its gaps: every series present from
    the hour before i to k1, and no more than a tenth of any missing before."""
    if k1 > len(times) or times[k1 - 1] - times[k0] != (k1 - 1 - k0) * HOUR:
        return False
    if any(cols[c][k] is None for c in COLS for k in range(i - 1, k1)):
        return False
    return all(sum(cols[c][k] is None for k in range(k0, i)) <= 0.1 * (i - k0) for c in COLS)


def series(state, feature, name, k0, k1, depth=None):
    unit = {"rain_mm": "mm", "air_c": "Cel"}.get(name, "1")
    prop = {"rain_mm": V.PRECIPITATION_DEPTH, "air_c": V.AIR_TEMPERATURE}.get(name, V.SOIL_WATER)
    raw = FX.raw_datastream(unit=unit, observed_property=prop, feature=feature,
                            expected_interval=3600.0)
    ds = FX.derived_datastream(raw, unit="cm3/cm3" if depth else unit)
    cal = FX.calibration(raw.sensor, valid_from=times[k0] - 48 * HOUR)
    for rec in (raw, ds, cal):
        state.add(rec)
    if depth:
        state.add(Installation(uuid7(), raw.sensor, feature, times[k0] - 24 * HOUR, depth_m=depth))
    for k in range(k0, k1):
        if cols[name][k] is None:
            continue
        state.add(FX.observation(ds, result=cols[name][k], measured_at=times[k], calibration=cal.id,
                                 seq=k % 65536))
    return ds


rng = random.Random(7)
need = CTX + GAP + AHEAD + 30
starts = [k for k in range(need, len(times) - GAP - AHEAD, 97)]
rng.shuffle(starts)
model = TS.load(TS.DEFAULT_MODEL, accept_weights_licence=True, offline=True)
results, took = [], []
for i in starts:
    if len(results) >= N:
        break
    if not present(i - CTX - 30, i, i + GAP + AHEAD):
        continue
    state, bed, station = State(), uuid7(), uuid7()
    k0 = i - CTX - 30
    top = series(state, bed, "sm_05", k0, i + GAP + AHEAD, depth=0.05)
    mid = series(state, bed, "sm_10", k0, i, depth=0.10)              # silent from row i
    deep = series(state, bed, "sm_20", k0, i + GAP + AHEAD, depth=0.20)
    rain = series(state, station, "rain_mm", k0, i + GAP + AHEAD)
    air = series(state, station, "air_c", k0, i + GAP + AHEAD)
    at = times[i + GAP - 1]
    log = L.Log()
    t = time.time()
    done = PF.forecast_silent(log, state, model, at, station={"rain": rain.id, "air": air.id})
    took.append(time.time() - t)
    [(probe, horizon, receipt)] = done
    assert probe == mid.id and horizon == GAP + AHEAD, (probe, horizon)
    [stream] = state.entities_named(PF.stream_name(mid))
    fc = state.forecast(stream, times[i], times[i] + horizon * HOUR, as_of=at)
    median = np.array([o.result for o in fc])
    truth = np.array(cols["sm_10"][i:i + GAP])

    # (b) the trial's own call, the same arrays, the covariates' hours after `at` missing
    def arr(name, k_end):
        return [cols[name][k] if k <= index[at] and cols[name][k] is not None else np.nan
                for k in range(k_end - CTX - horizon, k_end)]
    end = i + horizon
    target = np.array([np.nan if v is None else v for v in cols["sm_10"][i - CTX:i]],
                      dtype=np.float64)[None, None, :]
    cov = np.array([arr(c, end) for c in ("sm_05", "sm_20", "rain_mm", "air_c")])[None]
    raw_fc = model.forecaster.forecast(target, prediction_length=horizon, known_covariates=cov)
    direct = np.asarray(raw_fc.quantiles)[0, 0]
    mid_k = list(raw_fc.quantile_levels).index(0.5)

    # probe_context on the day before the silence, clean and with a drift up to 0.06
    watch_at = times[i - 1]
    others = [(top, 0.05), (deep, 0.20)]
    wb = PW.WatchBed(bed, rain=rain.id, air=air.id)
    clean, _ = PW.probe_context(model, state, wb, mid, 0.10, others, watch_at)
    drifted_state = State()
    for rec in list(state.datastreams.values()) + list(state.calibrations.values()) + list(state.installations.values()):
        drifted_state.add(rec)
    for ds in (top, deep, rain, air, mid):
        for o in state.live_observations_of(ds.id):
            k = index[o.measured_at]
            if ds is mid and i - 24 <= k < i:
                o = FX.observation(ds, result=o.result + 0.0025 * (k - (i - 24) + 1),
                                   measured_at=o.measured_at, calibration=o.calibration, seq=k % 65536)
            drifted_state.add(o)
    drift, _ = PW.probe_context(model, drifted_state, wb, mid, 0.10, others, watch_at)

    results.append({
        "start": times[i].isoformat(),
        "mae_forecast": float(np.mean(np.abs(median[:GAP] - truth))),
        "mae_persistence": float(np.mean(np.abs(cols["sm_10"][i - 1] - truth))),
        "end_error": float(median[GAP - 1] - truth[-1]),
        "direct_max_diff": float(np.max(np.abs(direct[:, mid_k] - median))),
        "ahead_finite": bool(np.isfinite(median[GAP:]).all()),
        "moved_by": receipt["moved_by"],
        "clean": {k: clean[k] for k in ("off", "longest_run_h", "band_points")},
        "drift": {k: drift[k] for k in ("off", "longest_run_h", "wetter", "departure_points")},
    })
    print(json.dumps(results[-1]), flush=True)

summary = {
    "n": len(results),
    "mae_forecast": float(np.mean([r["mae_forecast"] for r in results])),
    "mae_persistence": float(np.mean([r["mae_persistence"] for r in results])),
    "direct_max_diff": max(r["direct_max_diff"] for r in results),
    "ahead_finite": all(r["ahead_finite"] for r in results),
    "clean_off": sum(r["clean"]["off"] for r in results),
    "drift_off": sum(r["drift"]["off"] for r in results),
    "drift_wetter": sum(r["drift"]["wetter"] for r in results if r["drift"]["off"]),
    "seconds_per_forecast_silent": float(np.mean(took)),
    "receipt_model": receipt["model"], "receipt_weights": receipt["weights"],
    "receipt_package": receipt["package"],
}
print(json.dumps(summary, indent=1))
with open(OUT, "w") as h:
    json.dump({"summary": summary, "results": results}, h, indent=1)

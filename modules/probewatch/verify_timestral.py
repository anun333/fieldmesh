# SPDX-License-Identifier: AGPL-3.0-or-later
"""The add-on through fieldmesh's own code (sdk/tsfm.py, tools/probe_forecast.py,
probewatch.probe_context) against the real Timestral-28M, on a station's record as
tools/timestral/extract.py writes it. Here, not in tools/timestral/, because it imports this
module, and layer zero never imports a module (tools/test_layering.py).

    python verify_timestral.py STATION.csv OUT.json N

For N stretches chosen as gapfill.py chose its gaps, each built into a fieldmesh state:

* **The silent probe.** The 10 cm probe hidden 72 hours and forecast by `forecast_silent`,
  against the truth and its last reading held; the same forecast made by calling the
  forecaster directly, as the trial did, must match bit for bit.
* **The day ahead.** The 24 hours after the run's time, (a) as built, the inputs past it
  missing, and (b) with the true rain and air through them, against (c) the forecast at the
  run's time held.
* **The watch.** On the day before, each probe judged by `probe_context`, clean and with a
  drift of 0.0025 an hour put into the 10 cm probe; in the bed of three and in a bed of two
  (the 20 cm probe taken away); with the day's rain."""
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
DEPTHS = {0.05: "sm_05", 0.10: "sm_10", 0.20: "sm_20"}
DRIFT_PER_H = 0.0025

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


def series(state, feature, name, k0, k1, depth=None, shift=None):
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
        v = cols[name][k] + (shift(k) if shift else 0.0)
        state.add(FX.observation(ds, result=v, measured_at=times[k], calibration=cal.id,
                                 seq=k % 65536))
    return ds


def build(i, *, depths=tuple(DEPTHS), silent=False, drift=False):
    """A bed with probes at `depths` and a station, rows from 1,054 hours before row i to
    the day ahead's end; with `silent`, the 10 cm probe gives nothing from row i; with
    `drift`, it reads wetter by `DRIFT_PER_H` an hour over the 24 hours before row i."""
    state, bed, station = State(), uuid7(), uuid7()
    k0, k1 = i - CTX - 30, i + GAP + AHEAD
    probes = {}
    for d in depths:
        shift = ((lambda k: DRIFT_PER_H * (k - (i - 24) + 1) if i - 24 <= k < i else 0.0)
                 if drift and d == 0.10 else None)
        probes[d] = series(state, bed, DEPTHS[d], k0, i if silent and d == 0.10 else k1,
                           depth=d, shift=shift)
    return (state, bed, probes, series(state, station, "rain_mm", k0, k1),
            series(state, station, "air_c", k0, k1))


rng = random.Random(7)
starts = [k for k in range(CTX + GAP + AHEAD + 30, len(times) - GAP - AHEAD, 97)]
rng.shuffle(starts)
model = TS.load(TS.DEFAULT_MODEL, accept_weights_licence=True, offline=True)
results, took = [], []
for i in starts:
    if len(results) >= N:
        break
    if not present(i - CTX - 30, i, i + GAP + AHEAD):
        continue
    at = times[i + GAP - 1]

    # The silent probe, and the day ahead as built
    state, bed, probes, rain, air = build(i, silent=True)
    t = time.time()
    [(probe, horizon, _)] = PF.forecast_silent(L.Log(), state, model, at, ablate=False,
                                               station={"rain": rain.id, "air": air.id})
    took.append(time.time() - t)
    [stream] = state.entities_named(PF.stream_name(probes[0.10]))
    median = np.array([o.result for o in state.forecast(stream, times[i], times[i] + horizon * HOUR,
                                                        as_of=at)])
    truth = np.array(cols["sm_10"][i:i + GAP + AHEAD])

    # The trial's own call: the same arrays (the probes' and station's hours after `at`
    # missing), and again with the true rain and air through the day ahead
    def arr(name, known_all=False):
        return [cols[name][k] if (k <= index[at] or known_all) and cols[name][k] is not None
                else np.nan for k in range(i - CTX, i + horizon)]
    target = np.array([np.nan if v is None else v for v in cols["sm_10"][i - CTX:i]],
                      dtype=np.float64)[None, None, :]

    def direct(known_weather):
        cov = np.array([arr("sm_05"), arr("sm_20"), arr("rain_mm", known_weather),
                        arr("air_c", known_weather)])[None]
        fc = model.forecaster.forecast(target, prediction_length=horizon, known_covariates=cov)
        return np.asarray(fc.quantiles)[0, 0][:, list(fc.quantile_levels).index(0.5)]
    as_built, weather_known = direct(False), direct(True)

    # The watch, the day before the silence
    watch_at = times[i - 1]
    judged = {}
    for bed_name, depths in (("three", (0.05, 0.10, 0.20)), ("two", (0.05, 0.10))):
        for case in ("clean", "drift"):
            st, b, ps, rn, ar = build(i, depths=depths, drift=case == "drift")
            wb = PW.WatchBed(b, rain=rn.id, air=ar.id)
            for d in depths:
                ctx, _ = PW.probe_context(model, st, wb, ps[d], d, [(ps[o], o) for o in depths if o != d],
                                          watch_at, ablate=False)
                judged[f"{bed_name} {case} {round(d * 100)}"] = {
                    k: ctx[k] for k in ("off", "longest_run_h", "wetter", "departure_points", "band_points")}
    ahead = slice(GAP, GAP + AHEAD)
    results.append({
        "start": times[i].isoformat(),
        "mae_forecast": float(np.mean(np.abs(median[:GAP] - truth[:GAP]))),
        "mae_persistence": float(np.mean(np.abs(cols["sm_10"][i - 1] - truth[:GAP]))),
        "direct_max_diff": float(np.max(np.abs(as_built - median))),
        "ahead_finite": bool(np.isfinite(median[ahead]).all()),
        "ahead_mae": {"as_built": float(np.mean(np.abs(median[ahead] - truth[ahead]))),
                      "weather_known": float(np.mean(np.abs(weather_known[ahead] - truth[ahead]))),
                      "held": float(np.mean(np.abs(median[GAP - 1] - truth[ahead])))},
        "window_rain_mm": round(sum(cols["rain_mm"][k] or 0.0 for k in range(i - 25, i - 1)), 1),
        "judged": judged,
    })
    print(json.dumps({k: results[-1][k] for k in ("start", "mae_forecast", "ahead_mae", "window_rain_mm")}),
          flush=True)


def share(rows, key):
    return sum(r["judged"][key]["off"] for r in rows) / len(rows) if rows else None


wet = [r for r in results if r["window_rain_mm"] >= 1.0]
dry = [r for r in results if r["window_rain_mm"] < 1.0]
summary = {
    "station": os.path.basename(SRC), "n": len(results),
    "mae_forecast": float(np.mean([r["mae_forecast"] for r in results])),
    "mae_persistence": float(np.mean([r["mae_persistence"] for r in results])),
    "direct_max_diff": max(r["direct_max_diff"] for r in results),
    "ahead_finite": all(r["ahead_finite"] for r in results),
    "ahead_mae": {k: float(np.mean([r["ahead_mae"][k] for r in results]))
                  for k in ("as_built", "weather_known", "held")},
    "ahead_as_built_closer_than_held": sum(r["ahead_mae"]["as_built"] < r["ahead_mae"]["held"]
                                           for r in results),
    "clean_off": {k: share(results, k) for k in ("three clean 5", "three clean 10", "three clean 20",
                                                 "two clean 5", "two clean 10")},
    "drift_caught": {"three": share(results, "three drift 10"), "two": share(results, "two drift 10"),
                     "three, wet days": share(wet, "three drift 10"),
                     "three, dry days": share(dry, "three drift 10"), "wet_days": len(wet)},
    "healthy_said_off_beside_drift": {k: share(results, k) for k in ("three drift 5", "three drift 20",
                                                                     "two drift 5")},
    "seconds_per_forecast_silent": float(np.mean(took)),
}
print(json.dumps(summary, indent=1))
with open(OUT, "w") as h:
    json.dump({"summary": summary, "results": results}, h, indent=1)

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Three questions of the watch and the forecast source (2026-10-20), on a station's record
as tools/timestral/extract.py writes it, soil temperature included:

    python watch_tests.py STATION.csv OUT.json N

* **Soil temperature as an input.** The 10 cm probe hidden 72 hours and forecast, and
  judged by the watch on a clean day and with a drift of 0.0025 an hour, each with and
  without the probes' soil temperatures (in the watch the judged probe's own too).
* **Slow drifts.** The 10 cm probe drifting wetter by 0.02 over 14 days, 0.03 over 28 and
  0.03 over 56, judged at the drift's end by (a) the watch as built, the last day, and (b) a
  week's look, the last 7 days against the forecast from the 1,024 hours before them, off
  when outside the band 24 hours running; and clean weeks by (b).
* **Which probe of two.** A bed of two (5 and 10 cm), a drift put into the 10 cm probe and
  separately into the 5 cm one. Where the watch says both are off: (A) each judged against
  the rain and the air alone, (B) the first to leave the band; and (A) on clean days.

The model is called directly, as `probewatch.probe_context` calls it (the band its 1% and
99% quantiles, off at `RUN_H` hours running outside it); on the first stretches the two are
set side by side and the run stops if they differ. Only readings ISMN flagged good count."""
import csv
import datetime as dt
import json
import os
import random
import sys

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir)
sys.path[:0] = [os.path.join(REPO, p) for p in ("sdk", "modules/probewatch")]
import numpy as np  # noqa: E402

import fixtures as FX  # noqa: E402
import probewatch as PW  # noqa: E402
import tsfm as TS  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import Installation  # noqa: E402
from project import State  # noqa: E402

HOUR = dt.timedelta(hours=1)
SRC, OUT, N = sys.argv[1], sys.argv[2], int(sys.argv[3])
CTX, GAP, DAY, WEEK = TS.CONTEXT_H, 72, PW.WINDOW_H, 168
WEEK_RUN_H = 24
DRIFT_PER_H = 0.0025
SLOW = ((0.02, 14), (0.03, 28), (0.03, 56))
COLS = ("sm_05", "sm_10", "sm_20", "rain_mm", "air_c", "ts_05", "ts_10", "ts_20")
BACK = CTX + WEEK + 56 * 24 + 30               # rows needed before i

times, raw = [], {c: [] for c in COLS}
with open(SRC, newline="") as h:
    for row in csv.DictReader(h):
        times.append(dt.datetime.fromisoformat(row["time"]))
        for c in COLS:
            v = row.get(c, "")
            good = not c.startswith("sm_") or row.get(f"{c}_flag", "").split(",")[0] in ("", "G")
            raw[c].append(float(v) if v not in ("", None) and good else np.nan)
cols = {c: np.array(v) for c, v in raw.items()}


def present(i):
    """Hourly rows from BACK before i to the silence's end: every series present from a week
    before i to the silence's end, and no more than a tenth of any missing before."""
    k0, k1 = i - BACK, i + GAP
    if k0 < 0 or k1 > len(times) or times[k1 - 1] - times[k0] != (k1 - 1 - k0) * HOUR:
        return False
    if any(np.isnan(cols[c][i - WEEK - 1:k1]).any() for c in COLS):
        return False
    return all(np.isnan(cols[c][k0:i]).mean() <= 0.1 for c in COLS)


def drifted(col, i, total, days):
    """`col` wetter by `total` over the `days` before row i, rising evenly."""
    out = cols[col].copy()
    n = days * 24
    out[i - n:i] += total * np.arange(1, n + 1) / n
    return out


def forecast(target, covs, horizon):
    out = model.forecaster.forecast(np.asarray(target, dtype=np.float64)[None, None, :],
                                    prediction_length=horizon,
                                    **({"known_covariates": np.array(covs, dtype=np.float64)[None]} if covs else {}))
    q = np.asarray(out.quantiles)[0, 0]
    levels = list(out.quantile_levels)
    return q, levels


def judge(series, others, ws, window, run_h):
    """The watch over rows [ws, ws + window): `series` against the band forecast from the
    `CTX` rows before, given `others` through the window. `(off, first hour off, longest)`."""
    q, lv = forecast(series[ws - CTX:ws], [o[ws - CTX:ws + window] for o in others], window)
    lo, hi = q[:, lv.index(PW.BAND[0])], q[:, lv.index(PW.BAND[1])]
    readings = series[ws:ws + window]
    outside = [not np.isnan(r) and not a <= r <= b for r, a, b in zip(readings, lo, hi)]
    longest = run = 0
    first = None
    for k, o in enumerate(outside):
        run = run + 1 if o else 0
        if run > longest:
            longest = run
        if first is None and run >= run_h:
            first = k - run_h + 1
    return longest >= run_h, first, longest


def through_the_watch(i, sm10):
    """`probewatch.probe_context` itself on the bed of three, the 10 cm probe's readings
    `sm10`: `(off, longest)`, to check `judge` against."""
    state, bed, station = State(), uuid7(), uuid7()
    k0, k1 = i - CTX - DAY - 30, i

    def series(feature, values, prop, unit, depth=None):
        raw_ds = FX.raw_datastream(unit=unit, observed_property=prop, feature=feature, expected_interval=3600.0)
        ds = FX.derived_datastream(raw_ds, unit="cm3/cm3" if depth else unit)
        cal = FX.calibration(raw_ds.sensor, valid_from=times[k0] - 48 * HOUR)
        for rec in (raw_ds, ds, cal):
            state.add(rec)
        if depth:
            state.add(Installation(uuid7(), raw_ds.sensor, feature, times[k0] - 24 * HOUR, depth_m=depth))
        for k in range(k0, k1):
            if not np.isnan(values[k]):
                state.add(FX.observation(ds, result=float(values[k]), measured_at=times[k], calibration=cal.id,
                                         seq=k % 65536))
        return ds
    p05 = series(bed, cols["sm_05"], V.SOIL_WATER, "1", 0.05)
    p10 = series(bed, sm10, V.SOIL_WATER, "1", 0.10)
    p20 = series(bed, cols["sm_20"], V.SOIL_WATER, "1", 0.20)
    rain = series(station, cols["rain_mm"], V.PRECIPITATION_DEPTH, "mm")
    air = series(station, cols["air_c"], V.AIR_TEMPERATURE, "Cel")
    ctx, _ = PW.probe_context(model, state, PW.WatchBed(bed, rain=rain.id, air=air.id), p10, 0.10,
                              [(p05, 0.05), (p20, 0.20)], times[i - 1], ablate=False)
    return ctx["off"], ctx["longest_run_h"]


rng = random.Random(7)
starts = list(range(BACK, len(times) - GAP, 97))
rng.shuffle(starts)
model = TS.load(TS.DEFAULT_MODEL, accept_weights_licence=True, offline=True)
results, checked = [], 0
for i in starts:
    if len(results) >= N:
        break
    if not present(i):
        continue
    ws_day = i - DAY - 1                       # the watch at times[i - 1]: rows [i - 25, i - 1)
    ws_week = i - WEEK - 1
    weather = [cols["rain_mm"], cols["air_c"]]
    temps = [cols["ts_05"], cols["ts_10"], cols["ts_20"]]
    fast = drifted("sm_10", i - 1, DRIFT_PER_H * DAY, 1)
    fast5 = drifted("sm_05", i - 1, DRIFT_PER_H * DAY, 1)
    r = {"start": times[i].isoformat()}

    # 3: soil temperature
    truth = cols["sm_10"][i:i + GAP]
    nb = [cols["sm_05"][i - CTX:i + GAP], cols["sm_20"][i - CTX:i + GAP]]
    wx = [c[i - CTX:i + GAP] for c in weather]
    tnb = [cols["ts_05"][i - CTX:i + GAP], cols["ts_20"][i - CTX:i + GAP]]
    r["silent_mae"] = {}
    for label, covs in (("without", nb + wx), ("with", nb + wx + tnb)):
        q, lv = forecast(cols["sm_10"][i - CTX:i], covs, GAP)
        r["silent_mae"][label] = float(np.mean(np.abs(q[:, lv.index(0.5)] - truth)))
    three = [cols["sm_05"], cols["sm_20"]] + weather
    r["watch"] = {}
    for case, s10 in (("clean", cols["sm_10"]), ("drift", fast)):
        r["watch"][f"{case} without"] = judge(s10, three, ws_day, DAY, PW.RUN_H)[0]
        r["watch"][f"{case} with"] = judge(s10, three + temps, ws_day, DAY, PW.RUN_H)[0]
    if checked < 3:
        for case, s10 in (("clean", cols["sm_10"]), ("drift", fast)):
            mine = judge(s10, three, ws_day, DAY, PW.RUN_H)
            theirs = through_the_watch(i, s10)
            if (mine[0], mine[2]) != theirs:
                raise SystemExit(f"judge {mine} and probe_context {theirs} differ at {times[i]} ({case})")
        checked += 1

    # 4: slow drifts
    r["slow"] = {}
    for total, days in SLOW:
        s10 = drifted("sm_10", i - 1, total, days)
        r["slow"][f"{total} over {days} d"] = {
            "day": judge(s10, three, ws_day, DAY, PW.RUN_H)[0],
            "week": judge(s10, three, ws_week, WEEK, WEEK_RUN_H)[0]}
    r["clean_week"] = judge(cols["sm_10"], three, ws_week, WEEK, WEEK_RUN_H)[0]

    # 5: which of two
    r["two"] = {}
    for drifting, s05, s10 in (("10", cols["sm_05"], fast), ("5", fast5, cols["sm_10"])):
        j10 = judge(s10, [s05] + weather, ws_day, DAY, PW.RUN_H)
        j05 = judge(s05, [s10] + weather, ws_day, DAY, PW.RUN_H)
        alone10 = judge(s10, weather, ws_day, DAY, PW.RUN_H)[0]
        alone05 = judge(s05, weather, ws_day, DAY, PW.RUN_H)[0]
        named_a = "10" if alone10 and not alone05 else "5" if alone05 and not alone10 else None
        named_b = (None if j10[1] is None or j05[1] is None or j10[1] == j05[1]
                   else "10" if j10[1] < j05[1] else "5")
        r["two"][drifting] = {"both_off": j10[0] and j05[0], "A": named_a, "B": named_b,
                              "caught": (j10 if drifting == "10" else j05)[0]}
    r["two_clean_alone"] = [judge(cols["sm_10"], weather, ws_day, DAY, PW.RUN_H)[0],
                            judge(cols["sm_05"], weather, ws_day, DAY, PW.RUN_H)[0]]
    results.append(r)
    print(json.dumps({"start": r["start"], "silent": r["silent_mae"], "slow": r["slow"]}), flush=True)


def share(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


both = [(d, r["two"][d]) for r in results for d in ("10", "5") if r["two"][d]["both_off"]]
summary = {
    "station": os.path.basename(SRC), "n": len(results), "checked_against_probe_context": checked,
    "temperature": {
        "silent_mae": {k: float(np.mean([r["silent_mae"][k] for r in results])) for k in ("without", "with")},
        **{f"{case} {k}": share(r["watch"][f"{case} {k}"] for r in results)
           for case in ("clean", "drift") for k in ("without", "with")}},
    "slow": {f"{total} over {days} d": {k: share(r["slow"][f"{total} over {days} d"][k] for r in results)
                                         for k in ("day", "week")} for total, days in SLOW},
    "clean_week_off": share(r["clean_week"] for r in results),
    "two": {"both_off_days": len(both),
            "A_named_right": share(x["A"] == d for d, x in both),
            "B_named_right": share(x["B"] == d for d, x in both),
            "A_clean_off": share(any(r["two_clean_alone"]) for r in results)},
}
print(json.dumps(summary, indent=1))
with open(OUT, "w") as h:
    json.dump({"summary": summary, "results": results}, h, indent=1)

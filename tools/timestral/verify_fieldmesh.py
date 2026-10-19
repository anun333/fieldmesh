# SPDX-License-Identifier: Apache-2.0
"""Check 4: the silent probe as fieldmesh's own advice code carries it, not a copy.

For each gap of gap-28M.json: a bed with probes at 5, 10 and 20 cm and a 30 cm root zone,
fed the real readings of the week before (the 10 cm probe silent from the gap's start, the
others reading through it). At 24, 48 and 71 hours into the gap `soilwater.bed_context`
runs, and the value `_from_probes` carries the 10 cm probe at is taken from inside it. Set
beside the truth and beside gapfill.py's copy of the rule.

    python -I verify_fieldmesh.py DATA_DIR gap-28M.json
"""
import datetime as dt
import json
import os
import sys

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir)
for p in ("modules/soilwater", "sdk", "sim", "modules/rules"):
    sys.path.insert(0, os.path.join(REPO, p))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DATA, SAVED = sys.argv[1], sys.argv[2]
TARGET = sys.argv[3] if len(sys.argv) > 3 else "sm_10"
sys.argv = [sys.argv[0], DATA, "/dev/null", "none", "1", "1024", TARGET]
import numpy as np
import gapfill as G
import fixtures as FX
import soilwater as S
import vocab as V
from ids import uuid7
from model import Installation
from project import State

HOUR = dt.timedelta(hours=1)
captured = {}


def capture(frame, event, arg):
    """Take `extra` (the carried probes' values) from `_from_probes` as it returns."""
    if event == "return" and frame.f_code is S._from_probes.__code__:
        captured["extra"] = frame.f_locals.get("extra")


def bed_for(cols, times, i, hours):
    state, land = State(), uuid7()
    t0 = dt.datetime.fromisoformat(times[i])
    for depth, col in ((0.05, "sm_05"), (0.10, "sm_10"), (0.20, "sm_20")):
        last = i if col == TARGET else i + hours
        raw = FX.raw_datastream(unit="1", observed_property=V.SOIL_WATER,
                                expected_interval=3600.0, max_latency=3600.0)
        ds = FX.derived_datastream(raw, unit="cm3/cm3")
        cal = FX.calibration(raw.sensor)
        start = i - 7 * 24
        for rec in (raw, ds, cal, Installation(uuid7(), raw.sensor, land, t0 - (i - start + 24) * HOUR,
                                               depth_m=depth)):
            state.add(rec)
        for j in range(start, last + 1):
            v = cols[col][j]
            if not np.isnan(v):
                state.add(FX.observation(ds, result=round(float(v), 4), calibration=cal.id, seq=j & 0xFFFF,
                                         measured_at=dt.datetime.fromisoformat(times[j])))
    bed = S.Bed(land, field_capacity=0.45, wilting_point=0.08, root_depth_mm=300.0, learn=False)
    return state, bed


saved = json.load(open(SAVED))["windows"]
data = {}
real_err, copy_err, n_missing = {24: [], 48: [], 71: []}, {24: [], 48: [], 71: []}, 0
for r in saved:
    station = r["station"]
    if station not in data:
        data[station] = G.load(os.path.join(DATA, station + ".csv"))
    times, cols = data[station]
    i = times.index(r["time"])
    for h in (24, 48, 71):
        state, bed = bed_for(cols, times, i, h)
        captured.clear()
        sys.setprofile(capture)
        try:
            S.bed_context(state, bed, dt.datetime.fromisoformat(times[i + h]) + dt.timedelta(minutes=1))
        finally:
            sys.setprofile(None)
        extra = captured.get("extra") or []
        if len(extra) != 1:
            n_missing += 1
            continue
        carried = extra[0][1]
        truth = cols[TARGET][i + h]
        copy = G.carried(cols, i)[h]
        real_err[h].append(abs(truth - carried))
        copy_err[h].append(abs(truth - copy))
wet = [k for k, r in enumerate(saved) if r["rain_in_gap_mm"] >= 5]
for h in (24, 48, 71):
    print(f"{TARGET} at {h:2} h: fieldmesh's own code {np.mean(real_err[h]):.4f}, the old rule's copy {np.mean(copy_err[h]):.4f} "
          f"({len(real_err[h])} gaps)")
print("gaps where the code carried no probe:", n_missing)

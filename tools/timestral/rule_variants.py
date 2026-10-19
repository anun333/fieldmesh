# SPDX-License-Identifier: Apache-2.0
"""Ways to carry a silent probe from its neighbours, on the same gaps as the model's tests.
  old       last reading, less the neighbours' drying (fieldmesh until 2026-10-19)
  both      moved as the neighbours moved, wetter or drier (4a2c51a)
  deeper    drier as they dried; wetter only as the neighbours at or below it wetted"""
import json, os, sys
import numpy as np
sys.argv_saved = sys.argv[:]
for path, data, target in ((p.split(":")[0], p.split(":")[1], p.split(":")[2]) for p in sys.argv[1:]):
    sys.argv = [sys.argv_saved[0], data, "/dev/null", "none", "1", "1024", target]
    import importlib
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    G = importlib.reload(importlib.import_module("gapfill"))
    depth = {"sm_05": 5, "sm_10": 10, "sm_20": 20}
    deeper = [c for c in G.NB if depth[c] > depth[target]]
    saved = json.load(open(path))["windows"]
    err = {"old": [], "both": [], "deeper": []}
    wet = []
    cache = {}
    for r in saved:
        if r["station"] not in cache:
            cache[r["station"]] = G.load(os.path.join(data, r["station"] + ".csv"))
        times, cols = cache[r["station"]]
        i = times.index(r["time"])
        y, last = cols[target][i:i + 72], cols[target][i - 1]
        others = (cols[G.NB[0]] + cols[G.NB[1]]) / 2.0
        d_all = others[i:i + 72] - others[i - 1]
        if deeper:
            dd = np.mean([cols[c][i:i + 72] - cols[c][i - 1] for c in deeper], axis=0)
            rise = np.maximum(0.0, dd)
        else:
            rise = np.zeros(72)
        est = {"old": last - np.maximum(0.0, -d_all), "both": last + d_all,
               "deeper": last - np.maximum(0.0, -d_all) + rise}
        for k, v in est.items():
            err[k].append(float(np.mean(np.abs(y - v))))
        wet.append(r["rain_in_gap_mm"] >= 5)
    wet = np.array(wet)
    print(f"{os.path.basename(path):22} {target}: " + " | ".join(
        f"{k} {np.mean(v):.4f} (wet {np.mean(np.array(v)[wet]):.4f})" for k, v in err.items()))

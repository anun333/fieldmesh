# SPDX-License-Identifier: Apache-2.0
"""Summarize gapfill.py's results: each method's error over the gap, dry gaps and wet
ones apart, and what the model makes of the gap's rain."""
import json
import sys

import numpy as np

for path in sys.argv[1:]:
    d = json.load(open(path))
    w = d["windows"]
    print(f"\n== {path.split('/')[-1]}: {d['model']}, {d['context_h']} h of context, "
          f"{len(w)} gaps of {d['horizon_h']} h")
    methods = ["persistence", "fieldmesh", "neighbours", "regression", "timestral", "timestral+wx",
               "timestral+wx+nb"]
    for label, sel in (("all", lambda r: True), ("dry gaps (<2 mm)", lambda r: r["rain_in_gap_mm"] < 2),
                       ("wet gaps (>=5 mm)", lambda r: r["rain_in_gap_mm"] >= 5)):
        rows = [r for r in w if sel(r)]
        if not rows:
            continue
        cells = []
        for m in methods:
            mae = np.mean([r[m]["mae"] for r in rows])
            extra = ""
            if m.startswith("timestral"):
                extra = (f", loss {np.mean([r[m]['pinball'] for r in rows]):.4f}, "
                         f"in 10-90% {100 * np.mean([r[m]['covered'] for r in rows]):.0f}%")
            cells.append(f"{m} {mae:.4f}{extra}")
        print(f"  {label} ({len(rows)}): " + " | ".join(cells))
    wet = [r for r in w if r["rain_in_gap_mm"] >= 5]
    if wet:
        rise = np.array([r["end"] - r["last"] for r in wet])
        with_rain = np.array([r["timestral+wx+nb"]["median_end"] - r["last"] for r in wet])
        without = np.array([r["timestral+wx+nb, no rain in the gap"]["median_end"] - r["last"] for r in wet])
        print(f"  rain read: in {len(wet)} wet gaps the probe rose {np.mean(rise):+.4f} on average; "
              f"the model's median {np.mean(with_rain):+.4f} with the gap's rain, {np.mean(without):+.4f} "
              f"with it taken away (the rain moved it {np.mean(with_rain - without):+.4f})")

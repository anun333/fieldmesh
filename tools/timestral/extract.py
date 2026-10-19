# SPDX-License-Identifier: Apache-2.0
"""Hourly soil water (5, 10, 20 cm) with ISMN's flags, rain and air temperature, for the
SCAN stations named, from the ISMN archive read member by member. A reading flagged
other than G is kept with its flag (column `<depth>_flag`); rain and air, G only."""
import csv, datetime as dt, sys, zipfile
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
import ismn_score as I
ZIP, OUT, NAMES = sys.argv[1], sys.argv[2], set(sys.argv[3].split(","))
DEPTHS = (0.05, 0.10, 0.20)
vals, flags = defaultdict(lambda: defaultdict(dict)), defaultdict(lambda: defaultdict(dict))
with zipfile.ZipFile(ZIP) as z:
    for info in z.infolist():
        n = info.filename
        if not (n.startswith("SCAN/") and n.endswith(".stm")):
            continue
        kind = next((v for v in ("_sm_", "_p_", "_ta_") if v in n), None)
        if kind is None:
            continue
        with z.open(info) as h:
            s = I.parse_header(h.readline().decode("utf-8", "replace"), n)
            if s.station not in NAMES:
                continue
            if kind == "_sm_":
                d = next((d for d in DEPTHS if abs(s.depth_from - d) < 0.006), None)
                if d is None:
                    continue
                col = f"sm_{int(round(d * 100)):02d}"
            else:
                col = {"_p_": "rain_mm", "_ta_": "air_c"}[kind]
            lines = h.read().decode("utf-8", "replace").splitlines()
        for when, value, fl in I.parse_records(lines):
            if value is None:
                continue
            first = fl.split(",")[0]
            if col.startswith("sm_"):
                vals[s.station][col][when] = value
                flags[s.station][col][when] = fl
            elif first == "G":
                vals[s.station][col][when] = value
for st in vals:
    cols = vals[st]
    times = sorted(set().union(*(c.keys() for c in cols.values())))
    path = f"{OUT}/{st}.csv"
    names = ["sm_05", "sm_10", "sm_20", "rain_mm", "air_c"]
    with open(path, "w", newline="") as h:
        w = csv.writer(h)
        w.writerow(["time"] + names + [f"{c}_flag" for c in names[:3]])
        t = times[0]
        while t <= times[-1]:
            w.writerow([t.isoformat()] + [cols[c].get(t, "") for c in names]
                       + [flags[st][c].get(t, "") for c in names[:3]])
            t += dt.timedelta(hours=1)
    print(st, times[0], times[-1], path, flush=True)

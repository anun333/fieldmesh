#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A site's daily weather, as the CSV the virtual farm replays.

    python3 tools/weather_csv.py 35.06445 -86.59137 --from 1991 --to 2020 \\
        --cache CACHE --out mcallister-1991-2020.csv

NASA POWER's daily record (CC BY 4.0) for any point, written in the shape
`sim/physics.RecordedClimate.from_csv` reads — `date,T2M_MIN,T2M_MAX,T2M,PRECTOTCORR,
RH2M,ALLSKY_SFC_SW_DWN,WS2M` under a header that credits the source — so the farm can live
through thirty real springs rather than the one bundled with the tests. The wind at 2 m,
WS2M, since 2026-10-17: files written before have none.
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nasa_power  # noqa: E402

COLUMNS = ("T2M_MIN", "T2M_MAX", "T2M", "PRECTOTCORR", "RH2M", "ALLSKY_SFC_SW_DWN", "WS2M")


def write(days: list, lat: float, lon: float, path: str) -> int:
    rows = 0
    with open(path, "w", encoding="utf-8") as h:
        h.write(f"# NASA POWER daily agroclimatology at {lat:.5f}, {lon:.5f}, local solar days.\n"
                f"# NASA Langley Research Center POWER Project, CC BY 4.0. Written by tools/weather_csv.py.\n")
        h.write("date," + ",".join(COLUMNS) + "\n")
        for d, v in days:
            if all(c in v for c in ("T2M_MIN", "T2M_MAX")):
                h.write(d.isoformat() + "," + ",".join(f"{v[c]:g}" if c in v else "" for c in COLUMNS) + "\n")
                rows += 1
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--from", dest="start", type=int, default=1991)
    ap.add_argument("--to", dest="end", type=int, default=2020)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    doc = nasa_power.fetch_power(args.lat, args.lon, args.start, args.end, os.path.join(args.cache, "power"))
    rows = write(nasa_power.days_of(doc), args.lat, args.lon, args.out)
    print(f"wrote {rows} days to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

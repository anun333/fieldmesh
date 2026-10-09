#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Learned flatline thresholds (Q24) scored on real probes from the ISMN archive.

    python3 -I tools/ismn_learn.py ~/Downloads/ISMN_archive_20261008.zip \\
        --box 34.98,36.68,-90.31,-81.65 --cache soil-cache.json

For every SCAN soil-moisture probe in the box: the default flatline its soil gives
(tools/soil_survey.py: depth, texture at that depth, climate), and the one the series
learns from its own first year (sdk/checks.py `learned_flat_seconds`, bounded by that
default). Both are then run over the years after, counting **false `stuck` runs** —
runs of one value, on readings ISMN rates good, at least as long as the threshold — per
probe-year, and the threshold itself, which is how long a probe that really freezes
goes unnoticed. Agreement with ISMN, not accuracy (see ismn_score.py).
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import ismn_score as S  # noqa: E402
import soil_survey as SS  # noqa: E402
import checks as C  # noqa: E402

YEAR = _dt.timedelta(days=365)
MAX_GAP_S = 3 * 3600.0


class _Id:
    __slots__ = ("int",)

    def __init__(self, n):
        self.int = n


class Row:
    """What the SDK's ordering and run-length code reads of an observation."""
    __slots__ = ("measured_at", "result", "id", "node", "node_order")

    def __init__(self, n, when, value):
        self.measured_at, self.result, self.id = when, value, _Id(n)
        self.node, self.node_order = "", None


def default_for(sensor, soils: dict) -> tuple[float, str]:
    """The soil's flatline at the probe's depth, temperate climate, or the clay column
    where the survey has nothing (Q24)."""
    soil = soils.get(f"{sensor.lat:.5f},{sensor.lon:.5f}")
    if soil and soil.get("horizons"):
        limits = SS.proposed_limits(soil, sensor.depth_to, "C")
        if limits:
            return float(limits["flat_seconds"]), limits["texture"]
    dwell = SS.DWELL_P999_H[None][("clayey", SS.band(sensor.depth_to))]
    return dwell * SS.DWELL_FACTOR * 3600.0, "no survey (clay column)"


def false_runs(rows, threshold_s) -> int:
    return sum(1 for r in C.dwell_runs(rows, max_gap_s=MAX_GAP_S) if r >= threshold_s)


def score(sensor, records, default_s):
    good = [Row(i, w, v) for i, (w, v, f) in enumerate(records) if v is not None and f == "G"]
    if len(good) < 2:
        return None
    split = good[0].measured_at + YEAR
    train = [r for r in good if r.measured_at < split]
    test = [r for r in good if r.measured_at >= split]
    learned = C.learned_flat_seconds(train, default_s, max_gap_s=MAX_GAP_S)
    if learned is None or len(test) < 24 * 90:
        return None
    value, basis = learned
    years = (test[-1].measured_at - test[0].measured_at).total_seconds() / YEAR.total_seconds()
    return {"depth": sensor.depth_to, "default_s": default_s, "learned_s": value,
            "bounded": basis["bounded"], "years": years,
            "false_default": false_runs(test, default_s),
            "false_learned": false_runs(test, value)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive")
    ap.add_argument("--box", required=True, help="lat_min,lat_max,lon_min,lon_max")
    ap.add_argument("--cache", required=True, help="JSON cache of soil-survey answers by station")
    ap.add_argument("--factor", type=float, help="override checks.LEARN_FACTOR, to compare")
    ap.add_argument("--floor", type=float, help="override the lower bound, as a share of the default")
    ap.add_argument("--detail", action="store_true", help="one line per probe")
    args = ap.parse_args(argv)
    if args.factor:
        C.LEARN_FACTOR = args.factor
    if args.floor is not None:
        C.LEARN_BOUNDS = (args.floor, C.LEARN_BOUNDS[1])
    box = tuple(float(x) for x in args.box.split(","))
    soils = json.load(open(args.cache)) if os.path.exists(args.cache) else {}
    sensors = list(S.sensors(args.archive, network="SCAN", box=box))
    for s in sensors:
        key = f"{s.lat:.5f},{s.lon:.5f}"
        if key not in soils:
            try:
                soils[key] = SS.query(s.lat, s.lon)
            except Exception as exc:                    # noqa: BLE001 - recorded, not hidden
                soils[key] = {"horizons": [], "error": str(exc)}
            with open(args.cache, "w") as h:
                json.dump(soils, h)
    out = []
    for s in sensors:
        default_s, texture = default_for(s, soils)
        r = score(s, S.read_sensor(args.archive, s), default_s)
        if r:
            r.update(station=s.station, texture=texture)
            out.append(r)
    if args.detail:
        for r in sorted(out, key=lambda r: (r["depth"], r["station"])):
            print(f"{r['station']:<22} {r['depth']:>5.2f} m {r['texture']:<24} default "
                  f"{r['default_s'] / 3600:>4.0f} h learned {r['learned_s'] / 3600:>4.0f} h "
                  f"({r['bounded'] or 'free'}); false runs {r['false_default']} vs "
                  f"{r['false_learned']} in {r['years']:.1f} y")
    print(f"{len(out)} probes with a year to learn from and three months after\n")
    print(f"{'depth':>6} {'probes':>6} {'default h':>9} {'learned h':>9} "
          f"{'false/probe-yr default':>23} {'learned':>8}  bounded")
    by = collections.defaultdict(list)
    for r in out:
        by[SS.band(r["depth"])].append(r)
    for band in ("top", "mid", "deep"):
        rs = by.get(band)
        if not rs:
            continue
        yrs = sum(r["years"] for r in rs)
        print(f"{band:>6} {len(rs):>6} {statistics.median(r['default_s'] for r in rs) / 3600:>9.0f} "
              f"{statistics.median(r['learned_s'] for r in rs) / 3600:>9.0f} "
              f"{sum(r['false_default'] for r in rs) / yrs:>23.2f} "
              f"{sum(r['false_learned'] for r in rs) / yrs:>8.2f}  "
              f"{collections.Counter(r['bounded'] or 'no' for r in rs).most_common()}")
    yrs = sum(r["years"] for r in out)
    print(f"\n{'all':>6} {len(out):>6} {'':>9} {'':>9} "
          f"{sum(r['false_default'] for r in out) / yrs:>23.2f} "
          f"{sum(r['false_learned'] for r in out) / yrs:>8.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

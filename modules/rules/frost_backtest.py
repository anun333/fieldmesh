#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The frost watch backtested on a real season, as §11 requires before a rule goes live.

    python3 modules/rules/frost_backtest.py --cache NBM_CACHE --from 2025-10-15 --to 2026-04-30

Builds the log tools/nbm_verify.py builds — every 00 and 12 UTC run of NOAA's National
Blend of Models for McAllister Farm's cell, and its SCAN station's hourly air temperature
— and runs `rules.frost_watch` at every dusk, through CEL, against the night the station
recorded. It must agree with the Python scoring that chose the 0 °C threshold
(docs/notes/forecasts.md: 38 of 38 frosts, 6 false alerts): a rule language that changed
the answer would be a bug in the language's use, not a finding.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "tools"))
import nbm_verify as NV  # noqa: E402
import rules as R  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--warn-at", type=float, nargs="+", default=[1.0, 0.0, -1.0, -2.2])
    args = ap.parse_args(argv)
    start, end = _dt.date.fromisoformat(args.start), _dt.date.fromisoformat(args.end)
    runs = NV.nbm_runs(start, end, 35.06437, -86.59136, args.cache)
    station = NV.scan_hourly("2075:TN:SCAN", start, end + _dt.timedelta(days=8), -6.0, args.cache)
    state, raw, fc = NV.build_log(runs, station)
    to_c = lambda v: NV.celsius(v, "[degF]")
    print(f"{len(runs)} forecast runs, {len(station)} station hours")
    print(f"{'warn at':>8} {'frosts warned':>14} {'missed':>7} {'false alerts':>13}")
    for w in args.warn_at:
        s = R.backtest(R.frost_watch(w), state, fc.id, raw.id, to_c=to_c, forecast_to_c=to_c)
        print(f"{w:>7.1f}° {s['hits']:>7} of {s['hits'] + s['misses']:<4} {s['misses']:>7} {s['false']:>13}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

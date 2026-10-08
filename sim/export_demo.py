#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Export a simulated season and verify it (spec v0.1 §7.6).

    python3 export_demo.py                  # a week, to a temporary directory
    python3 export_demo.py --days 30 --out /tmp/harrow-bend

The point of running this rather than reading the tests: it prints what a farmer
actually receives, and whether it verifies.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "sdk"))

import harrow_bend as hb

import export as X  # noqa: E402
import project as P  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    farm = hb.build(seed=args.seed)
    hb.season(farm, days=args.days, seed=args.seed)
    directory = args.out or tempfile.mkdtemp(prefix="harrow-bend-export-")

    started = _dt.datetime.now()
    manifest = X.export_log(farm.log, directory, state=farm.state,
                            geometries=hb.geometries(farm))
    elapsed = (_dt.datetime.now() - started).total_seconds()

    print(f"{args.days:g} simulated days, {manifest.events} events -> {directory}")
    print(f"written in {elapsed:.1f}s\n")
    width = max(len(f.name) for f in manifest.files)
    print(f"  {'file':<{width}}  {'rows':>8}  bytes       what")
    for entry in manifest.files:
        size = os.path.getsize(os.path.join(directory, entry.name))
        what = "lossless" if entry.lossless else "a view (lossy)"
        print(f"  {entry.name:<{width}}  {entry.rows:>8}  {size:>10}  {what}")

    problems = X.verify(directory)
    print(f"\nverify: {'intact' if not problems else problems}")

    # The claim worth making out loud: it replays into the same farm.
    back = X.import_log(directory)
    replayed = P.state_from_log(back)
    same_events = ([e.to_jsonable() for e in back.events]
                   == [e.to_jsonable() for e in farm.log.events])
    print(f"replays into an identical event list: {same_events}")
    print(f"replayed state validates clean:       {replayed.validate() == []}")
    print(f"observations: {len(farm.state.observations)} -> "
          f"{len(replayed.observations)}")
    return 0 if same_events and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Spikes and jumps by shape: candidate §4.2 detectors scored on ISMN (open question Q23).

    cd /tmp && python3 -I ~/dev/fieldmesh/tools/ismn_spikes.py \\
        ~/Downloads/ISMN_archive_20261008.zip --network SCAN --max-depth 0.21

The §4.2 rate check allows `max_rate_per_s × gap`, which at hourly sampling is nearly the
whole physical range, and on ISMN's record it caught none of 1,849 spikes and jumps. Q23
recommended detecting the *shape* instead. These are the candidates, measured:

* **spike** — a reading that leaves both neighbours by at least `a`, in the same
  direction, and whose neighbours agree to within 30% of the excursion: out and back in
  one sample. Rain rises and holds; a glitch comes back. Judged on samples, not rates, so
  the sampling interval does not stretch it; no decision where either neighbour is more
  than three hours away.
* **drop** — a fall faster than `c` per hour. Soil gains water fast, by infiltration,
  and loses it slowly, by drainage and evaporation, so a cap on falls can be much tighter
  than one on rises.
* **stable drop** — the same, from a level that has not risen by 0.02 in the six hours
  before. Drainage just after rain is fast and legitimate; a fall from a steady level is
  not.
* **rise** — a backstop cap on rises, near the healthy 99.99th percentile.

Scored by *event* against ISMN's D06 (spike), D07 (negative jump) and D08 (positive
jump) — ISMN marks a region, so a detection anywhere in an event or one reading either
side counts — and by the flags each raises on readings ISMN rates good, per probe-year.
Agreement, not accuracy: the note docs/notes/spikes-and-jumps.md shows that ISMN's D06 is
not a glitch detector, and that some of what it rates good plainly is a glitch.

Every reading is also re-scored at 2- and 3-hourly sampling (the readings on even or
every third hour), because a check that only works at one interval is the defect Q23 is
about. The archive is untrusted data, read in place.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)          # explicit: this runs under -I against downloaded data
import ismn_score as I  # noqa: E402

HOUR = _dt.timedelta(hours=1)
#: Neighbours further apart than this leave the shape undecided.
MAX_GAP = _dt.timedelta(hours=3)
#: A spike's neighbours must agree to within this share of the excursion.
RETURN_SHARE = 0.3
#: A "stable" level has not risen by more than this in the window before a drop.
STABLE_RISE = 0.02
STABLE_WINDOW = _dt.timedelta(hours=6)

CONFIGS = [("spike", 0.03), ("spike", 0.05), ("drop", 0.03), ("drop", 0.05),
           ("stable drop", 0.03), ("stable drop", 0.05), ("rise", 0.17), ("rise", 0.25)]


def detect(rows) -> dict:
    """rows: [(time, value, ...)] sorted by time -> {(kind, threshold): set(index)}."""
    n = len(rows)
    t = [r[0] for r in rows]
    v = [r[1] for r in rows]
    out = collections.defaultdict(set)
    spikes = set()
    for i in range(1, n - 1):
        if t[i] - t[i - 1] > MAX_GAP or t[i + 1] - t[i] > MAX_GAP:
            continue
        out_by = v[i] - v[i - 1]
        back_by = v[i] - v[i + 1]
        for a in sorted({c for k, c in CONFIGS if k == "spike"}):
            if (abs(out_by) >= a and abs(back_by) >= a and (out_by > 0) == (back_by > 0)
                    and abs(v[i + 1] - v[i - 1]) <= RETURN_SHARE * abs(out_by)):
                out[("spike", a)].add(i)
                spikes.add(i)
    for i in range(1, n):
        hours = (t[i] - t[i - 1]) / HOUR
        if hours > MAX_GAP / HOUR:
            continue
        step = v[i] - v[i - 1]
        if (i - 1) in spikes:
            continue                                  # the way back from a spike
        rose, j = 0.0, i - 1
        while j > 0 and t[i - 1] - t[j - 1] <= STABLE_WINDOW:
            rose = max(rose, v[j] - v[j - 1])
            j -= 1
        for kind, c in CONFIGS:
            if kind == "drop" and step < -c * hours:
                out[(kind, c)].add(i)
            elif kind == "stable drop" and step < -c * hours and rose < STABLE_RISE:
                out[(kind, c)].add(i)
            elif kind == "rise" and step > c * hours:
                out[(kind, c)].add(i)
    return out


def events(rows, code: str) -> list:
    """[first, last] index ranges of readings carrying ISMN flag `code`, a gap of up to
    two readings joining them."""
    found = []
    for i, r in enumerate(rows):
        if code not in r[2].split(","):
            continue
        if found and i - found[-1][1] <= 2:
            found[-1][1] = i
        else:
            found.append([i, i])
    return found


def decimate(rows, every_h: int):
    return rows if every_h == 1 else [r for r in rows
                                      if r[0].minute == 0 and r[0].hour % every_h == 0]


def score(archive: str, *, network: str | None, max_depth: float | None):
    per_probe = {k: [] for k in (1, 2, 3)}
    n_events, hits = collections.Counter(), collections.Counter()
    for sensor in I.sensors(archive, network=network, max_depth=max_depth):
        rows = sorted((r for r in I.read_sensor(archive, sensor) if r[1] is not None),
                      key=lambda r: r[0])
        if len(rows) < 1000:
            continue
        years = (rows[-1][0] - rows[0][0]).days / 365.25
        for every_h in (1, 2, 3):
            sub = decimate(rows, every_h)
            found = detect(sub)
            good = {i for i, r in enumerate(sub) if r[2] == "G"}
            per_probe[every_h].append(
                (years, {c: len(found[c] & good) for c in CONFIGS}, sensor.station))
            if every_h == 1:
                for code in ("D06", "D07", "D08"):
                    for a, b in events(sub, code):
                        n_events[code] += 1
                        span = set(range(a - 1, b + 2))
                        for c in CONFIGS:
                            if found[c] & span:
                                hits[(code, c)] += 1
    return per_probe, n_events, hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive")
    ap.add_argument("--network", default="SCAN")
    ap.add_argument("--max-depth", type=float, default=0.21)
    args = ap.parse_args(argv)
    per_probe, n_events, hits = score(args.archive, network=args.network,
                                      max_depth=args.max_depth)
    probes = per_probe[1]
    years = sum(p[0] for p in probes)
    print(f"{len(probes)} probes, {years:.0f} probe-years; ISMN events: spike (D06) "
          f"{n_events['D06']}, negative jump (D07) {n_events['D07']}, positive jump (D08) "
          f"{n_events['D08']}")
    print(f"\n{'detector':<20}{'D06':>6}{'D07':>6}{'D08':>6}   flags on good readings "
          f"per probe-year: all, median probe, probes with none, top 5% of probes' share, "
          f"at 2 h, at 3 h")
    for c in CONFIGS:
        recall = "".join(f"{hits[(code, c)] / max(n_events[code], 1):>6.0%}"
                         for code in ("D06", "D07", "D08"))
        rate = {k: sum(p[1][c] for p in per_probe[k]) / sum(p[0] for p in per_probe[k])
                for k in (1, 2, 3)}
        per = sorted(p[1][c] / p[0] for p in probes if p[0])
        counts = sorted((p[1][c] for p in probes), reverse=True)
        top = sum(counts[:max(1, len(counts) // 20)]) / max(sum(counts), 1)
        none = sum(1 for p in probes if p[1][c] == 0) / len(probes)
        print(f"{f'{c[0]} {c[1]}':<20}{recall}   {rate[1]:>8.2f}{statistics.median(per):>8.2f}"
              f"{none:>8.0%}{top:>8.0%}{rate[2]:>8.2f}{rate[3]:>8.2f}")
    print("\nThe ten probes with the most `spike 0.03` flags on readings ISMN rates good:")
    for y, c, station in sorted(probes, key=lambda p: -p[1][("spike", 0.03)])[:10]:
        print(f"  {station:<24}{c[('spike', 0.03)]:>6} over {y:.1f} years")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

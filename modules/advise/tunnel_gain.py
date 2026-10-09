#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a hoop house actually does: its gain measured from an inside and an outside sensor.

    python3 modules/advise/tunnel_gain.py inside.csv outside.csv [--limit-c 35]

modules/advise/notes/hoop-houses.md: how much warmer an unheated tunnel keeps a night varies by
tunnel and by night, so the matcher leaves the winter low unchanged until it is measured.
This measures it, from two air-temperature series of `time,value` rows (an export of two
librefarm datastreams, or any logger's), and reports:

* **winter gain** — inside minus outside nightly minimum, binned by how cold the night was
  outside, because the gain shrinks on the coldest, clearest nights; and the figure to pass
  to `plant_match.py --winter-gain-f`, taken from the coldest nights (the 10th percentile of
  the gain on nights below −5 °C, or below 0 °C if there are none), so it errs cold;
* **season** — last spring and first fall frost inside and outside, and the frost-free
  days each gives: the tunnel's measured season extension;
* **overheating** — hours above a crop's limit, and the fastest rise in an hour, which says
  how soon the sides must open on a sunny morning.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import statistics


#: Outside-night bands, coldest first, by the outside nightly minimum.
BANDS = (("below −5 °C", -5.0), ("−5 to 0 °C", 0.0), ("0 to 5 °C", 5.0), ("above 5 °C", float("inf")))


def band_of(outside_min_c: float) -> str:
    return next(name for name, upper in BANDS if outside_min_c < upper)


def read(path: str) -> list:
    """`time,value` CSV -> [(datetime, float)], times in ISO 8601."""
    out = []
    with open(path, encoding="utf-8") as h:
        for row in csv.reader(line for line in h if not line.startswith("#")):
            if len(row) < 2:
                continue
            try:
                out.append((_dt.datetime.fromisoformat(row[0]), float(row[1])))
            except ValueError:
                continue                                  # a header, or a blank value
    return sorted(out)


def nightly_minima(series: list) -> dict:
    """Night of `date` = 18:00 that day to 09:00 the next, in the series' own clock."""
    out = {}
    for t, v in series:
        night = (t - _dt.timedelta(hours=18)).date() if t.hour < 9 else (t.date() if t.hour >= 18 else None)
        if night is None:
            continue
        out[night] = min(v, out.get(night, v))
    return out


def frost_season(series: list, frost_c: float = 0.0) -> dict:
    """Per year: last spring frost (before July) and first fall frost (from July), as dates."""
    per = collections.defaultdict(lambda: [None, None])
    for t, v in series:
        if v > frost_c:
            continue
        y = per[t.year]
        if t.month < 7:
            y[0] = t.date() if y[0] is None or t.date() > y[0] else y[0]
        elif y[1] is None:
            y[1] = t.date()
    return {year: tuple(v) for year, v in per.items()}


def analyse(inside: list, outside: list, limit_c: float = 35.0) -> dict:
    nin, nout = nightly_minima(inside), nightly_minima(outside)
    nights = sorted(set(nin) & set(nout))
    bins = collections.defaultdict(list)
    for n in nights:
        bins[band_of(nout[n])].append(nin[n] - nout[n])
    cold = bins.get("below −5 °C") or bins.get("−5 to 0 °C") or []
    gain_c = sorted(cold)[int(0.1 * (len(cold) - 1))] if cold else None

    seasons = []
    fin, fout = frost_season(inside), frost_season(outside)
    for year in sorted(set(fin) | set(fout)):
        (li, fi), (lo, fo) = fin.get(year, (None, None)), fout.get(year, (None, None))
        if lo and fo:
            free_out = (fo - lo).days - 1
            free_in = ((fi or _dt.date(year, 12, 31)) - (li or _dt.date(year, 1, 1))).days - 1
            seasons.append({"year": year, "outside": free_out, "inside": free_in,
                            "extension": free_in - free_out})

    hot = sum(1 for _, v in inside if v > limit_c)
    step_h = statistics.median((b[0] - a[0]).total_seconds() / 3600.0
                               for a, b in zip(inside, inside[1:])) if len(inside) > 1 else 1.0
    rises = [(b[1] - a[1]) / ((b[0] - a[0]).total_seconds() / 3600.0)
             for a, b in zip(inside, inside[1:]) if 0 < (b[0] - a[0]).total_seconds() <= 2 * 3600]
    return {"nights": len(nights),
            "gain_by_outside_night": {k: {"nights": len(v), "median_c": round(statistics.median(v), 1)}
                                      for k, _ in BANDS if (v := bins.get(k))},
            "winter_gain_c": round(gain_c, 1) if gain_c is not None else None,
            "winter_gain_f": round(gain_c * 9 / 5, 1) if gain_c is not None else None,
            "seasons": seasons,
            "median_extension_days": int(statistics.median(s["extension"] for s in seasons)) if seasons else None,
            "hours_over_limit": round(hot * step_h, 1), "limit_c": limit_c,
            "fastest_rise_c_per_h": round(max(rises), 1) if rises else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inside")
    ap.add_argument("outside")
    ap.add_argument("--limit-c", type=float, default=35.0, help="the crop's heat limit")
    args = ap.parse_args(argv)
    a = analyse(read(args.inside), read(args.outside), args.limit_c)
    print(f"{a['nights']} nights with both sensors")
    for band, b in a["gain_by_outside_night"].items():
        print(f"  outside night {band:<12} {b['nights']:>4} nights, inside warmer by {b['median_c']:+.1f} °C (median)")
    if a["winter_gain_c"] is not None:
        print(f"  for plant_match.py: --winter-gain-f {a['winter_gain_f']}  (coldest nights, 10th percentile: "
              f"{a['winter_gain_c']:+.1f} °C)")
    if a["median_extension_days"] is not None:
        print(f"  frost-free season: {a['median_extension_days']:+d} days inside "
              f"(median over {len(a['seasons'])} year(s) with both frosts outside)")
    print(f"  {a['hours_over_limit']} hours above {a['limit_c']:g} °C inside; fastest rise "
          f"{a['fastest_rise_c_per_h']} °C an hour")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

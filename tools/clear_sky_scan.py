#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The clear-sky check (`sdk/checks.clear_sky`) on a reference station's sunshine.

NOAA's Climate Reference Network measures global solar radiation at each station with a
calibrated pyranometer and publishes every hour, quality-controlled, in the public
domain. On a station's good hours the check should say nothing; with the faults a farm's
station really has put in, it should:

* `clock_lst` — the logger keeps local standard time and is read as UTC, so the sun
  rises hours early;
* `clock_hour` — the clock is an hour fast, as one that missed the change from daylight
  saving time is;
* `lux` — light in lux sent as W/m2, at 100 lux per W/m2, below sunlight's own ratio;
* `gain` — a sensor reading 30% high.

    python3 tools/clear_sky_scan.py tools/fixtures/uscrn-crossville-2024-solar.csv.gz
    python3 tools/clear_sky_scan.py CRNH0203-2023-TN_Crossville_7_NW.txt \\
        --lat 36.01 --lon -85.13 --elevation-m 583

A USCRN `hourly02` file or the trimmed fixture; each hour is judged as a mean over the
hour (`clear_sky_window_s` 3600) at the factor the check's comments give for hourly means
(1.25), and as a reading of a moment at the default (1.7) from the hour's maximum.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import checks as C  # noqa: E402
import fixtures as FX  # noqa: E402
import vocab as V  # noqa: E402

CROSSVILLE = {"lat": 36.01, "lon": -85.13, "elevation_m": 1913 * 0.3048}
HOUR = _dt.timedelta(hours=1)
FAULTS = ("clock_lst", "clock_hour", "lux", "gain")


def read(path: str) -> list:
    """`[(utc_end, mean, mean_good, maximum, maximum_good)]`, a USCRN hourly02 file or the
    fixture. Missing values (-9999) are None."""
    opener = gzip.open if path.endswith(".gz") else open
    rows = []
    with opener(path, "rt", encoding="utf-8") as h:
        for line in h:
            if line.startswith("#") or line.startswith("utc_end") or not line.strip():
                continue
            if "," in line:
                t, avg, avg_f, mx, mx_f = line.strip().split(",")
                when = _dt.datetime.strptime(t, "%Y-%m-%dT%H:%MZ").replace(tzinfo=_dt.timezone.utc)
            else:
                f = line.split()
                when = (_dt.datetime.strptime(f[1], "%Y%m%d").replace(tzinfo=_dt.timezone.utc)
                        + _dt.timedelta(hours=int(f[2][:2]), minutes=int(f[2][2:])))
                avg, avg_f, mx, mx_f = f[13], f[14], f[15], f[16]
            value = lambda x: None if float(x) <= -9000 else float(x)
            rows.append((when, value(avg), avg_f == "0", value(mx), mx_f == "0"))
    return rows


def faulty(rows: list, fault: str, utc_offset_h: float = -6.0) -> list:
    """The same hours with a fault put in, as `(utc_end, mean, maximum)`."""
    out = []
    for when, avg, ok, mx, mx_ok in rows:
        if not ok or avg is None:
            continue
        if fault == "clock_lst":
            when = when + _dt.timedelta(hours=utc_offset_h)
        elif fault == "clock_hour":
            when = when - HOUR
        elif fault == "lux":
            avg, mx = avg * 100.0, (mx or 0.0) * 100.0
        elif fault == "gain":
            avg, mx = avg * 1.3, (mx or 0.0) * 1.3
        out.append((when, avg, mx if mx_ok else None))
    return out


def judge(hours: list, site: dict, *, hourly: bool = True) -> list:
    """The hours the check flags: as hourly means at 1.25, or, `hourly=False`, the hour's
    maximum as a reading of a moment at the default, judged against the clear sky's most
    in that hour (its end minus the moments in it)."""
    ds = FX.raw_datastream(unit="W/m2", observed_property=V.SOLAR_RADIATION)
    values = dict(C.DEFAULTS, clear_sky_lat=site["lat"], clear_sky_lon=site["lon"],
                  clear_sky_elevation_m=site["elevation_m"])
    if hourly:
        values.update(clear_sky_window_s=3600.0, clear_sky_factor=1.25)
    flagged = []
    for when, avg, mx in hours:
        value = avg if hourly else mx
        if value is None:
            continue
        if hourly:
            obs = FX.observation(ds, result=value, measured_at=when)
            if C.clear_sky(obs, ds, values)[1] is not None:
                flagged.append(when)
        else:
            # A moment anywhere in the hour: flagged only if it beats the sky at every
            # moment of it, so the hour's brightest moment is judged at its best case.
            moments = [when - _dt.timedelta(minutes=m) for m in range(0, 61, 5)]
            if all(C.clear_sky(FX.observation(ds, result=value, measured_at=t), ds,
                               values)[1] is not None for t in moments):
                flagged.append(when)
    return flagged


def scan(rows: list, site: dict) -> dict:
    """Flags on the good hours, and on each fault, by hour and by day."""
    good = [(w, a, m if mo else None) for w, a, ok, m, mo in rows if ok and a is not None]
    sunny = {w.date() for w, a, _ in good if a > 100}
    out = {"hours": len(good), "sunny_days": len(sunny),
           "clean": {"hourly": len(judge(good, site)), "moment": len(judge(good, site, hourly=False))}}
    for fault in FAULTS:
        hours = faulty(rows, fault)
        flagged = judge(hours, site)
        out[fault] = {"hours": len(flagged),
                      "days": len({w.date() for w in flagged}),
                      "moment_days": len({w.date() for w in judge(hours, site, hourly=False)})}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+", help="USCRN hourly02 files, or the trimmed fixture")
    ap.add_argument("--lat", type=float, default=CROSSVILLE["lat"])
    ap.add_argument("--lon", type=float, default=CROSSVILLE["lon"])
    ap.add_argument("--elevation-m", type=float, default=CROSSVILLE["elevation_m"])
    args = ap.parse_args(argv)
    rows = [r for path in args.files for r in read(path)]
    site = {"lat": args.lat, "lon": args.lon, "elevation_m": args.elevation_m}
    r = scan(rows, site)
    print(f"{r['hours']} good hours, {r['sunny_days']} days with sun; flagged when healthy: "
          f"{r['clean']['hourly']} as hourly means, {r['clean']['moment']} as moments")
    for fault in FAULTS:
        f = r[fault]
        print(f"  {fault:11s} flagged {f['hours']:5d} hours on {f['days']:3d} days as hourly "
              f"means; on {f['moment_days']:3d} days as moments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

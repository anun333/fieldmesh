#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Does the depth-from-temperature siting check work on real soil? (§4.1, §9.2)

Until now `sdk/siting.py` had only met the simulator's heat model. ISMN carries real
soil temperature at several depths per station, so a farm of real probes can be
assembled — each recorded at its true depth — and then lied to:

* **Control.** Every probe recorded where it is. Anything but `consistent` is a false
  alarm or an admission the check cannot see.
* **Unlogged moves.** A probe *recorded* at one depth is given the readings actually
  taken at another, and the real probe at that other depth is removed from the peers,
  so the check cannot simply notice two identical series. It should say `displaced`, and
  the depth it implies should be near the true one.

Two-day windows, sampled weekly across each station's record, reported by season
because snow and overcast winter days weaken the daily wave the check reads.

    cd /tmp && python3 -I ~/dev/librefarm/tools/ismn_siting.py \\
        ~/Downloads/ISMN_archive_20261008.zip --stations AllenFarms,EastviewFarm,McAllisterFarm

`--persistence` instead assesses every day and scores the k-of-n rules that
`siting.assess_siting_persistent` applies — false-alarm episodes per probe-year, and how
often each move is caught.

Only readings ISMN rates good are used. The archive is untrusted data, read in place.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import datetime as _dt
import os
import statistics
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
# Explicitly, because this runs under `python3 -I` against downloaded data, which keeps
# the script's own directory off the path. These are our directories, not the archive's.
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
sys.path.insert(0, HERE)
import ismn_score as I  # noqa: E402

import log as L  # noqa: E402
import project as P  # noqa: E402
import siting as S  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import (Calibration, ClockQuality, Datastream,  # noqa: E402
                   DatastreamKind, Device, DeviceKind, Installation, Observation)

UTC = _dt.timezone.utc
WINDOW = _dt.timedelta(hours=48)

#: (recorded depth, depth the readings really came from). The shallowest three depths
#: are where a farm's probes live and where the daily wave is strong enough to read.
MOVES = [(0.20, 0.05, "lifted 15 cm"), (0.20, 0.10, "lifted 10 cm"),
         (0.10, 0.05, "lifted 5 cm"), (0.10, 0.20, "pushed 10 cm"),
         (0.20, 0.51, "pushed 31 cm")]


def season(when: _dt.datetime) -> str:
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
            5: "spring", 6: "summer", 7: "summer", 8: "summer"}.get(when.month, "autumn")


def load_station(archive: str, station_folder: str) -> dict:
    """depth (rounded) -> {utc time -> temperature}, good readings only, all sensors at
    that depth merged (ISMN numbers replacements at the same position separately)."""
    out: dict = collections.defaultdict(dict)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            n = info.filename
            if not (n.startswith(f"SCAN/{station_folder}/") and n.endswith(".stm")
                    and "_ts_" in n):
                continue
            with z.open(info) as h:
                text = h.read().decode("utf-8", "replace").splitlines()
            sensor = I.parse_header(text[0], n)
            series = out[round(sensor.depth_to, 2)]
            for when, value, flags in I.parse_records(text[1:]):
                if value is not None and flags == "G" and when not in series:
                    series[when] = value
    return out


def windower(depths: dict):
    """`window(depth, at)` -> the readings in the WINDOW ending at `at`, by bisection.

    The first version filtered every reading of a 23-year record for every window,
    which is quadratic in the record: weekly windows took minutes, daily ones would
    have taken hours."""
    index = {d: (sorted(series), series) for d, series in depths.items()}

    def window(depth: float, at: _dt.datetime) -> dict:
        times, series = index[depth]
        lo = bisect.bisect_left(times, at - WINDOW)
        hi = bisect.bisect_right(times, at)
        return {t: series[t] for t in times[lo:hi]}
    return window


def build_state(probes: dict, at: _dt.datetime):
    """A one-window farm: probes = {name: (recorded depth, {time: temperature})}."""
    log = L.Log()
    site, feature = uuid7(), uuid7()
    since = at - WINDOW
    ids = {}
    for name, (recorded, readings) in probes.items():
        device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=site)
        raw = Datastream(id=uuid7(), thing=uuid7(), sensor=device.id,
                         observed_property=V.SOIL_TEMPERATURE, feature=feature,
                         kind=DatastreamKind.RAW, unit="Cel")
        derived = Datastream(id=uuid7(), thing=raw.thing, sensor=device.id,
                             observed_property=V.SOIL_TEMPERATURE, feature=feature,
                             kind=DatastreamKind.DERIVED, derived_from=raw.id,
                             unit="Cel")
        cal = Calibration(id=uuid7(), sensor=device.id, datastream=raw.id,
                          method="identity", valid_from=since - _dt.timedelta(days=30))
        install = Installation(id=uuid7(), device=device.id, feature=feature,
                               installed_at=since - _dt.timedelta(days=30),
                               depth_m=recorded)
        for record in (device, raw, derived, cal, install):
            log.append_record(record)
        for when, value in readings.items():
            if since <= when <= at:
                log.append_record(Observation(
                    id=uuid7(), datastream=derived.id, measured_at=when,
                    measured_at_uncertainty=1800.0, received_at=at,
                    result=value, clock_quality=ClockQuality.NETWORK,
                    calibration=cal.id))
        ids[name] = device.id
    return P.state_from_log(log), ids


def run(archive: str, stations: list[str], every_days: int = 7):
    control = collections.defaultdict(collections.Counter)      # (season, depth)
    control_error = collections.defaultdict(list)
    moved = collections.defaultdict(collections.Counter)        # (label, season)
    moved_implied = collections.defaultdict(list)
    for station in stations:
        depths = load_station(archive, station)
        shallow = [d for d in (0.05, 0.10, 0.20, 0.51, 1.02) if d in depths]
        if len(shallow) < 4:
            continue
        times = sorted(set().union(*(depths[d].keys() for d in shallow)))
        start = times[0].replace(hour=0, minute=0) + _dt.timedelta(days=3)
        at = start
        slice_ = windower(depths)
        while at <= times[-1]:
            window = {d: slice_(d, at) for d in shallow}
            if sum(1 for d in shallow if len(window[d]) >= 40) >= 4:
                sea = season(at)
                state, ids = build_state({f"p{d}": (d, window[d]) for d in shallow}, at)
                for d in shallow:
                    if len(window[d]) < 40:
                        continue
                    finding = S.assess_siting(state, ids[f"p{d}"], at)
                    control[(sea, d)][finding.verdict] += 1
                    if finding.implied_depth_m is not None and finding.verdict != S.INDETERMINATE:
                        control_error[(sea, d)].append(abs(finding.implied_depth_m - d))
                for recorded, actual, label in MOVES:
                    if recorded not in window or actual not in window or \
                            len(window[actual]) < 40:
                        continue
                    # The probe at the recorded depth is replaced by the moved one; the
                    # probe whose readings it borrows stays, as a second probe at that
                    # depth would on a farm with redundancy. A first version removed it
                    # as well, leaving one peer and a check that could never decide.
                    probes = {f"p{d}": (d, window[d]) for d in shallow if d != recorded}
                    probes["moved"] = (recorded, window[actual])
                    state, ids = build_state(probes, at)
                    finding = S.assess_siting(state, ids["moved"], at)
                    moved[(label, sea)][finding.verdict] += 1
                    if finding.implied_depth_m is not None:
                        moved_implied[label].append(finding.implied_depth_m)
            at += _dt.timedelta(days=every_days)
    return control, control_error, moved, moved_implied


#: The persistence scenarios: (recorded depth, depth the readings came from).
DAILY = {"control 0.05": (0.05, 0.05), "control 0.10": (0.10, 0.10),
         "control 0.20": (0.20, 0.20), "lifted 15 cm": (0.20, 0.05),
         "pushed 10 cm": (0.10, 0.20), "lifted 10 cm": (0.20, 0.10)}
RULES = [(1, 1), (2, 3), (3, 5), (4, 7), (5, 7)]


def daily_verdicts(archive: str, station: str) -> dict:
    """scenario -> [(date, verdict, implied depth)], one 48 h window ending each midnight
    where all four of 5, 10, 20 and 51 cm have readings."""
    depths = load_station(archive, station)
    shallow = [d for d in (0.05, 0.10, 0.20, 0.51) if d in depths]
    rows = collections.defaultdict(list)
    if len(shallow) < 4:
        return rows
    window_of = windower(depths)
    times = sorted(depths[0.05])
    at = times[0].replace(hour=0, minute=0) + _dt.timedelta(days=3)
    while at <= times[-1]:
        window = {d: window_of(d, at) for d in shallow}
        if all(len(window[d]) >= 40 for d in shallow):
            for name, (recorded, actual) in DAILY.items():
                probes = {f"p{d}": (d, window[d]) for d in shallow if d != recorded}
                probes["x"] = (recorded, window[actual])
                state, ids = build_state(probes, at)
                f = S.assess_siting(state, ids["x"], at)
                rows[name].append((at.date(), f.verdict, f.implied_depth_m))
        at += _dt.timedelta(days=1)
    return rows


def k_of_n(rows: list, k: int, n: int) -> list:
    """[(date, alarm or None)]: displaced on at least k of the last n consecutive days,
    as `siting.assess_siting_persistent` decides. None where fewer than k could decide."""
    by_day = {d: v for d, v, _ in rows}
    out = []
    for day, _, _ in rows:
        last = [by_day.get(day - _dt.timedelta(days=i)) for i in range(n)]
        if any(v is None for v in last):
            continue                       # a gap in the record: not n consecutive days
        decided = [v for v in last if v != S.INDETERMINATE]
        out.append((day, None if len(decided) < k
                    else sum(v == S.DISPLACED for v in decided) >= k))
    return out


def episodes(decisions: list) -> int:
    """Alarm episodes: runs of consecutive alarmed days. What a farmer would be told."""
    count, inside, prev = 0, False, None
    for day, alarm in decisions:
        if prev is not None and (day - prev).days > 1:
            inside = False
        prev = day
        if alarm is None:
            continue
        if alarm and not inside:
            count += 1
        inside = bool(alarm)
    return count


def persistence(archive: str, stations: list[str], exclude: dict) -> None:
    """False-alarm episodes per probe-year on undisturbed profiles, and how often moves
    are caught, for each k-of-n rule. `exclude` = {station: date} drops that station's
    windows from that date on — a period with a known displaced probe."""
    per_station = {s: daily_verdicts(archive, s) for s in stations}
    for s, cut in exclude.items():
        if s in per_station:
            per_station[s] = {k: [r for r in v if r[0] < cut]
                              for k, v in per_station[s].items()}
    controls = [k for k in DAILY if k.startswith("control")]
    moves = [k for k in DAILY if not k.startswith("control")]
    print("False `displaced` episodes per probe-year, correctly placed probes; and the "
          "share of decided days a move is caught")
    print(f"  {'rule':<8}{'all':>7}" + "".join(f"{c[-4:]:>7}" for c in controls)
          + "".join(f"{m:>14}" for m in moves))
    for k, n in RULES:
        total_e = total_y = 0
        cells = []
        for c in controls:
            e = y = 0
            for rows in per_station.values():
                e += episodes(k_of_n(rows[c], k, n))
                y += len(rows[c]) / 365.25
            cells.append(f"{e / y:>7.2f}" if y else f"{'-':>7}")
            total_e += e
            total_y += y
        caught = []
        for m in moves:
            got = [a for rows in per_station.values()
                   for _, a in k_of_n(rows[m], k, n) if a is not None]
            caught.append(f"{sum(got) / len(got):>14.0%}" if got else f"{'-':>14}")
        print(f"  {f'{k} of {n}':<8}{total_e / max(total_y, 1e-9):>7.2f}" + "".join(cells)
              + "".join(caught))
    print(f"\n  {total_y / len(controls):.0f} station-years, three control probes each")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive")
    ap.add_argument("--stations", default="AllenFarms,EastviewFarm,McAllisterFarm")
    ap.add_argument("--every-days", type=int, default=7)
    ap.add_argument("--persistence", action="store_true",
                    help="daily windows, scored under each k-of-n persistence rule")
    ap.add_argument("--exclude", default="",
                    help="STATION:YYYY-MM-DD,... drop a station's windows from that date "
                         "(a period with a known displaced probe)")
    args = ap.parse_args(argv)
    if args.persistence:
        exclude = {s: _dt.date.fromisoformat(d) for s, d in
                   (item.split(":") for item in args.exclude.split(",") if item)}
        persistence(args.archive, args.stations.split(","), exclude)
        return 0
    control, error, moved, implied = run(args.archive, args.stations.split(","),
                                         args.every_days)

    def pct(counter, key):
        total = sum(counter.values())
        return f"{counter[key] / total:>6.0%}" if total else "     -"

    print("CONTROL — probes at their recorded depth (false alarms are `displaced`)")
    print(f"  {'season':<8}{'depth':>6}{'windows':>9}{'consistent':>12}{'displaced':>11}"
          f"{'cannot tell':>13}{'median error':>14}")
    for sea in ("winter", "spring", "summer", "autumn"):
        for d in (0.05, 0.10, 0.20, 0.51, 1.02):
            c = control.get((sea, d))
            if not c:
                continue
            err = error.get((sea, d))
            med = f"{statistics.median(err) * 100:>11.1f} cm" if err else f"{'-':>14}"
            print(f"  {sea:<8}{d:>5.2f}m{sum(c.values()):>9}{pct(c, 'consistent'):>12}"
                  f"{pct(c, 'displaced'):>11}{pct(c, 'indeterminate'):>13}{med}")
    print("\nUNLOGGED MOVES — the check should say `displaced`")
    print(f"  {'move':<14}{'season':<8}{'windows':>9}{'displaced':>11}{'consistent':>12}"
          f"{'cannot tell':>13}")
    for _, _, label in MOVES:
        for sea in ("winter", "spring", "summer", "autumn"):
            c = moved.get((label, sea))
            if not c:
                continue
            print(f"  {label:<14}{sea:<8}{sum(c.values()):>9}{pct(c, 'displaced'):>11}"
                  f"{pct(c, 'consistent'):>12}{pct(c, 'indeterminate'):>13}")
    print("\nMedian implied depth for each move (all seasons):")
    for recorded, actual, label in MOVES:
        values = implied.get(label)
        if values:
            print(f"  {label:<14} recorded {recorded:.2f} m, really {actual:.2f} m -> "
                  f"implied {statistics.median(values):.2f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

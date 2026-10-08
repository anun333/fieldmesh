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

Only readings ISMN rates good are used. The archive is untrusted data, read in place.
"""
from __future__ import annotations

import argparse
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
        while at <= times[-1]:
            window = {d: {t: v for t, v in depths[d].items() if at - WINDOW <= t <= at}
                      for d in shallow}
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive")
    ap.add_argument("--stations", default="AllenFarms,EastviewFarm,McAllisterFarm")
    ap.add_argument("--every-days", type=int, default=7)
    args = ap.parse_args(argv)
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

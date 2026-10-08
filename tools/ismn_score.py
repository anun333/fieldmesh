#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Score layer zero's health checks against ISMN's quality flags (spec v0.1 §9.2).

The International Soil Moisture Network keeps flagged readings rather than deleting
them, so a series comes with an independent judgement on every value. Running our §4.2
checks over the same values and comparing is the strongest validation available
without hardware: real sensors, real faults, someone else's labels.

**This measures agreement, not correctness.** Where we and ISMN disagree, either could
be right — their checks use ancillary data ours do not, and ours use thresholds theirs
do not. The report says "agreement" and never "accuracy".

## The flag mapping, verified against the archive

Checked on 2026-10-08 against `ISMN_qualityflags_description.txt` inside a complete ISMN
download, which matched the documentation exactly. ISMN asks that the paper behind the
flags be cited wherever they are used:

    Dorigo, W.A. et al. (2013). Global Automated Quality Control of In Situ Soil
    Moisture data from the International Soil Moisture Network. Vadose Zone Journal
    12(3). doi:10.2136/vzj2012.0097

Two things the real files showed that the documentation did not:

* **C03 is common** — 7.5% of one Tennessee probe's readings. Its "saturation point" is
  derived from the global HWSD soil database, not from the site, so on a clay-rich soil a
  C03 may be the database disagreeing with the sensor rather than the sensor being wrong.
* **D01-D03 are freezing flags** (soil and air below 0 C). Capacitance probes read only
  liquid water, so frozen soil reads falsely dry. Our probes now report temperature on
  the same device, so this is a check layer zero could run; it has no counterpart yet.

## Reading the archive

Straight from the zip, member by member. Never extracted: the complete archive is 6.3 GB
compressed and **49 GB** uncompressed. Treat it as untrusted data — the tool reads values
and never executes anything in it. Each `.stm` file is a header line —
`CSE Network Station Lat Lon Elevation DepthFrom DepthTo 'Sensor'` — then records of
`yyyy/mm/dd HH:MM value ismn_flags provider_flag`, times in UTC.

    python3 -I ismn_score.py ~/Downloads/ISMN_archive_20261008.zip \
        --network SCAN --box 34.98,36.68,-90.31,-81.65 --max-depth 0.11
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from collections import Counter
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "sdk"))
import checks as C  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import (ClockQuality, Datastream, DatastreamKind,  # noqa: E402
                   Observation, QualityFlag)

UTC = _dt.timezone.utc

#: ISMN flag -> (family, the §4.2 flag that would be the counterpart, or None).
#: Verified against ISMN_qualityflags_description.txt — see the module docstring.
ISMN_FLAGS = {
    "G": ("good", None),
    "C01": ("range", QualityFlag.OUT_OF_RANGE),     # below 0 m3/m3
    "C02": ("range", QualityFlag.OUT_OF_RANGE),     # above 0.6 m3/m3
    "C03": ("range", QualityFlag.OUT_OF_RANGE),     # above saturation
    "D01": ("ancillary", None),     # negative soil temperature
    "D02": ("ancillary", None),     # negative air temperature
    "D03": ("ancillary", None),     # modelled soil temperature below zero
    "D04": ("ancillary", None),     # rise without precipitation (in situ)
    "D05": ("ancillary", None),     # rise without precipitation (modelled)
    "D06": ("spike", QualityFlag.RATE_EXCEEDED),
    "D07": ("break", QualityFlag.RATE_EXCEEDED),    # negative break
    "D08": ("break", QualityFlag.RATE_EXCEEDED),    # positive break
    "D09": ("plateau", QualityFlag.STUCK),          # low constant values
    "D10": ("plateau", QualityFlag.STUCK),          # saturated plateau
}

#: Our thresholds, not ISMN's. Scoring the range check with their own 0 and 0.6 would
#: make range agreement true by construction and tell us nothing.
OUR_THRESHOLDS = {"min": 0.02, "max": 0.46, "flat_seconds": 18 * 3600, "flat_n": 4,
                  "max_rate_per_s": 0.00015}


def families(flag_text: str) -> set[str]:
    """ISMN flags on one reading, possibly several, as families. Unknown ones are
    returned as `unknown:<flag>` so a vocabulary surprise is visible, not silent."""
    out = set()
    for part in (flag_text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        known = ISMN_FLAGS.get(part)
        out.add(known[0] if known else f"unknown:{part}")
    return out or {"unknown:<none>"}


@dataclass
class Score:
    readings: int = 0
    by_family: Counter = field(default_factory=Counter)
    caught: Counter = field(default_factory=Counter)
    ours_on_good: Counter = field(default_factory=Counter)

    def agreement(self, family: str) -> float | None:
        n = self.by_family.get(family, 0)
        return self.caught.get(family, 0) / n if n else None


def score_series(rows, *, interval_s: float = 3600.0,
                 thresholds: dict | None = None) -> Score:
    """Run the §4.2 suite over one sensor's `(utc time, value, ismn flags)` rows.

    Readings land on a raw datastream exactly as ISMN published them (m3/m3), the way
    `csv_import` would land them, and each is assessed in time order with the history
    before it — which is how the gateway sees a series arrive.
    """
    thresholds = dict(thresholds or OUR_THRESHOLDS)
    ds = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(),
                    observed_property=V.SOIL_WATER, feature=uuid7(),
                    kind=DatastreamKind.RAW, unit="m3/m3",
                    expected_interval=interval_s, thresholds=thresholds)
    log = L.Log()
    log.append_record(ds)
    state = P.state_from_log(log)
    score = Score()
    received = _dt.datetime.now(tz=UTC)
    for when, value, flag_text in sorted(rows, key=lambda r: r[0]):
        if value is None:
            continue
        obs = Observation(id=uuid7(), datastream=ds.id, measured_at=when,
                          measured_at_uncertainty=interval_s / 2, received_at=received,
                          result=value, clock_quality=ClockQuality.NETWORK)
        state.add(obs)
        ours = C.assess(state, obs, asserted_at=received).flags
        score.readings += 1
        for family in families(flag_text):
            score.by_family[family] += 1
            expected = next((flag for code, (fam, flag) in ISMN_FLAGS.items()
                             if fam == family and flag is not None), None)
            if family == "good":
                for flag in ours:
                    score.ours_on_good[flag.value] += 1
            elif expected is not None and expected in ours:
                score.caught[family] += 1
    return score


# ---------------------------------------------------------------- the reader

@dataclass(frozen=True, slots=True)
class Sensor:
    member: str
    network: str
    station: str
    lat: float
    lon: float
    depth_from: float
    depth_to: float
    instrument: str


def parse_header(line: str, member: str) -> Sensor:
    parts = line.split()
    instrument = line.split("'")[1] if line.count("'") >= 2 else " ".join(parts[8:])
    return Sensor(member=member, network=parts[1], station=parts[2],
                  lat=float(parts[3]), lon=float(parts[4]),
                  depth_from=float(parts[6]), depth_to=float(parts[7]),
                  instrument=instrument)


def parse_records(lines):
    """`(utc datetime, value or None, ismn_flags)` per record. A malformed line raises
    rather than being skipped, so a format surprise is found, not averaged away."""
    for number, line in enumerate(lines, start=2):
        parts = line.split()
        if not parts:
            continue
        if len(parts) < 4:
            raise ValueError(f"line {number}: expected date, time, value, flag: {line!r}")
        when = _dt.datetime.strptime(parts[0] + " " + parts[1],
                                     "%Y/%m/%d %H:%M").replace(tzinfo=UTC)
        flags = parts[3]
        value = None if "M" in flags.split(",") else float(parts[2])
        yield when, value, flags


def sensors(zip_path: str, *, network: str | None = None, variable: str = "sm",
            box=None, max_depth: float | None = None):
    """Soil-moisture sensors in the archive that match the filters, headers only."""
    import zipfile
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename
            if not name.endswith(".stm") or f"_{variable}_" not in name:
                continue
            if network and not name.startswith(network + "/"):
                continue
            with archive.open(info) as handle:
                header = handle.readline().decode("utf-8", "replace")
            sensor = parse_header(header, name)
            if box and not (box[0] <= sensor.lat <= box[1]
                            and box[2] <= sensor.lon <= box[3]):
                continue
            if max_depth is not None and sensor.depth_to > max_depth:
                continue
            yield sensor


def read_sensor(zip_path: str, sensor: Sensor):
    import zipfile
    with zipfile.ZipFile(zip_path) as archive:
        text = archive.read(sensor.member).decode("utf-8", "replace")
    lines = text.splitlines()
    return list(parse_records(lines[1:]))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive")
    ap.add_argument("--network")
    ap.add_argument("--box", help="lat_min,lat_max,lon_min,lon_max")
    ap.add_argument("--max-depth", type=float)
    ap.add_argument("--limit", type=int, help="score at most this many sensors")
    args = ap.parse_args(argv)
    box = tuple(float(x) for x in args.box.split(",")) if args.box else None

    total = Score()
    chosen = list(sensors(args.archive, network=args.network, box=box,
                          max_depth=args.max_depth))[:args.limit]
    print(f"{len(chosen)} sensors\n")
    for sensor in chosen:
        score = score_series(read_sensor(args.archive, sensor))
        total.readings += score.readings
        total.by_family.update(score.by_family)
        total.caught.update(score.caught)
        total.ours_on_good.update(score.ours_on_good)
        print(f"  {sensor.station:<18} {sensor.depth_to:5.3f} m  "
              f"{score.readings:>7} readings  "
              + "  ".join(f"{fam} {score.caught.get(fam, 0)}/{n}"
                          for fam, n in sorted(score.by_family.items())
                          if fam != "good"))
    print(f"\n{total.readings} readings scored\n")
    print(f"  {'ISMN family':<14}{'readings':>10}{'we flag it':>12}{'agreement':>11}")
    for family, n in sorted(total.by_family.items(), key=lambda kv: -kv[1]):
        rate = total.agreement(family)
        shown = "-" if family in ("good", "ancillary") or rate is None else f"{rate:.0%}"
        print(f"  {family:<14}{n:>10}{total.caught.get(family, 0):>12}{shown:>11}")
    good = total.by_family.get("good", 0)
    flagged_good = sum(total.ours_on_good.values())
    print(f"\n  On readings ISMN calls good ({good}), we raised: "
          + (", ".join(f"{k} {v}" for k, v in total.ours_on_good.most_common())
             or "nothing"))
    print("  Agreement, not accuracy: where we differ, either could be right.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

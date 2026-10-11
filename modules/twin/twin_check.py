#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The twin against the tunnel's own sensor — Q28 step 3.

A tunnel has one air sensor more often than two, and a single sensor cannot see its own
fault. The twin is a second opinion that never drifts. When the sensor and the twin part
company and stay apart, something is wrong:

* with the sensor: miscalibrated, its sun shield gone, knocked down, moved;
* or with the tunnel: sides left up, a door open, the film torn.

So this says, as an **advisory decision** (§7.7), that they disagree and for how long. It
never marks the reading bad. A module does not write quality verdicts (§8.3), and the
twin may be the one that is wrong.

**What counts as apart is learned, not assumed.** Two models of one tunnel never agree
exactly, and how far apart they normally sit depends on the time of day. On McAllister
Farm's spring of 2025, GreenLight and the virtual farm's tunnel differ by about 1 °C at
night and nearly 2 °C in the middle of the day. So the check first learns the usual
difference and its spread for each four hours of the solar day over a calibration window
of good data, two weeks by default, after installation or after the sensor is serviced.
After that, an hour departs when its difference is further from the usual one than the
larger of `band_c` and `k` spreads, and the alert stands once `hold_h` such hours run in a
row.

    cal = calibrate(sensor, twin, start, start + 14 * DAY, lon=-86.59)
    ctx, inputs = context(sensor, twin, cal, at, lon=-86.59)
    decision = rules.judge(rule(), ctx, inputs, at)
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import statistics
import sys
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
import i18n  # noqa: E402
import rules as R  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "twin")
HOUR = _dt.timedelta(hours=1)
DAY = 24 * HOUR
BIN_H = 4
#: Full sun for the virtual tunnel's daylight, W m-2 (`sensor_series`).
FULL_SUN = 700.0


@dataclass(frozen=True)
class Calibration:
    """The usual sensor-minus-twin difference and its spread, per four solar hours."""

    mean: dict
    sd: dict
    hours: int

    def ok(self) -> bool:
        return len(self.mean) == 24 // BIN_H and self.hours >= 24 * 7


def _bin(when: _dt.datetime, lon: float) -> int:
    return int((when + _dt.timedelta(hours=lon / 15.0)).hour // BIN_H)


def calibrate(sensor: dict, twin: dict, start: _dt.datetime, end: _dt.datetime, *,
              lon: float) -> Calibration:
    """Learn the usual difference from hours both have, between two times. `sensor` and
    `twin` are `{UTC hour: °C}`."""
    by = {}
    for when, s in sensor.items():
        if start <= when < end and when in twin:
            by.setdefault(_bin(when, lon), []).append(s - twin[when])
    return Calibration({b: statistics.mean(r) for b, r in by.items()},
                       {b: statistics.pstdev(r) for b, r in by.items()},
                       sum(len(r) for r in by.values()))


def excess(sensor: dict, twin: dict, cal: Calibration, when: _dt.datetime, *, lon: float,
           band_c: float = 2.0, k: float = 3.0) -> float | None:
    """How far an hour's difference lies beyond what is usual, signed: 0 when within it,
    None when either side has no value for the hour."""
    if when not in sensor or when not in twin:
        return None
    b = _bin(when, lon)
    off = sensor[when] - twin[when] - cal.mean[b]
    limit = max(band_c, k * cal.sd[b])
    return 0.0 if abs(off) <= limit else off


def context(sensor: dict, twin: dict, cal: Calibration, at: _dt.datetime, *, lon: float,
            band_c: float = 2.0, k: float = 3.0) -> tuple[dict, dict]:
    """What the check knew at `at`: how many hours in a row, up to the latest hour both
    have, have departed, and by how much on average beyond the usual difference."""
    latest = max((w for w in sensor if w <= at and w in twin), default=None)
    # CEL compares a double only with a double: hours are counted as one.
    ctx = {"calibrated": cal.ok(), "hours_apart": 0.0, "delta_c": 0.0,
           "has_reading": latest is not None}
    if latest is None or not cal.ok():
        return ctx, {"hours": []}
    run, w = [], latest
    while True:
        e = excess(sensor, twin, cal, w, lon=lon, band_c=band_c, k=k)
        if not e:
            break
        run.append(sensor[w] - twin[w] - cal.mean[_bin(w, lon)])
        w -= HOUR
    if run:
        ctx.update({"hours_apart": float(len(run)), "delta_c": round(statistics.mean(run), 1)})
    return ctx, {"hours": [latest.isoformat()]}


def rule(hold_h: float = 3.0) -> R.Rule:
    return R.Rule("twin-sensor-disagree", "1", "calibrated && hours_apart >= hold_h",
                  {"hold_h": hold_h}, alert_key="twin.disagree",
                  message_params={"delta": "delta_c", "hours": "hours_apart"},
                  subject_param="tunnel")


# ----------------------------------------------------------------- backtest

def sensor_series(hours: list, *, faults=(), seed: int = 1, noise_c: float = 0.2,
                  full_sun: float = FULL_SUN) -> dict:
    """A tunnel's air sensor on recorded weather, for the backtest: the virtual farm's
    tunnel (`sim/physics.Tunnel`, fitted to GreenLight), lit by the measured sunshine,
    stepped every five minutes, read hourly with noise. `faults` are `(kind, start, end,
    size)`:

    * `"offset"` — the sensor reads `size` °C high: miscalibrated, or replaced;
    * `"sun"` — its shield is gone, so it reads up to `size` °C high in full sun;
    * `"sides"` — the sides are left up whatever the temperature;
    * `"outside"` — it reads the outside air: knocked down, or moved.
    """
    import random
    sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sim"))
    import physics as ph
    tunnel, rng, out = ph.Tunnel(name="hoop"), random.Random(seed), {}
    vent, close = tunnel.vent_at_c, tunnel.close_at_c
    for a, b in zip(hours, hours[1:] + hours[-1:]):
        active = {kind: size for kind, start, end, size in faults if start <= a.when < end}
        tunnel.vent_at_c, tunnel.close_at_c = ((-99.0, -100.0) if "sides" in active else (vent, close))
        acc = []
        for i in range(12):
            f = i / 12.0
            w = ph.Weather(air_temp_c=a.t + (b.t - a.t) * f, relative_humidity=a.rh,
                           rain_mm=a.rain / 12.0, et0_mm=0.0, raining=False)
            acc.append(tunnel.step(w, min(1.0, (a.sw + (b.sw - a.sw) * f) / full_sun)))
        reading = sum(acc) / len(acc)
        if "outside" in active:
            reading = a.t
        reading += active.get("offset", 0.0) + active.get("sun", 0.0) * min(1.0, a.sw / full_sun)
        out[a.when] = round(reading + rng.gauss(0.0, noise_c), 2)
    return out


def backtest(sensor: dict, twin: dict, faults: list, *, lon: float, calibrate_days: float = 14,
             hold_h: float = 3.0, band_c: float = 2.0, k: float = 3.0) -> dict:
    """The check every hour after its calibration window: alerts raised and cleared, as
    a monitor writes them, scored against the faults put in. A fault is caught when an
    alert is raised while it lasts; an alert raised with no fault running, nor in the
    six hours after one ends, is false."""
    first = min(sensor)
    cal = calibrate(sensor, twin, first, first + calibrate_days * DAY, lon=lon)
    r = rule(hold_h)
    raised, standing = [], False
    t = first + calibrate_days * DAY
    end = max(sensor)
    while t <= end:
        ctx, _ = context(sensor, twin, cal, t, lon=lon, band_c=band_c, k=k)
        alert = R._cel(r.condition, {**ctx, **r.params})
        if alert and not standing:
            raised.append(t)
        standing = alert
        t += HOUR
    out = {"faults": [], "false": [], "calibration": cal}
    for kind, start, stop, size in faults:
        hits = [x for x in raised if start <= x < stop]
        out["faults"].append({"kind": kind, "start": start, "hours": (stop - start) / HOUR,
                              "caught_after_h": (hits[0] - start) / HOUR if hits else None})
    out["false"] = [x for x in raised
                    if not any(start <= x < stop + 6 * HOUR for _, start, stop, _ in faults)]
    out["clean_days"] = ((end - first) / DAY - calibrate_days
                         - sum((stop - start) / DAY for _, start, stop, _ in faults))
    return out

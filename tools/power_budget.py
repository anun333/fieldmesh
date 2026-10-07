#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Where a node's battery actually goes, per datastream (spec v0.1 §3.1, §5.2, §9.1).

The question this answers: if soil moisture does not need updating often, what does
slowing it down actually save? §3.1 already puts `expected_interval` on the
datastream rather than the node, so different series on one node can sample at
different rates — but "sample less to save battery" is an assumption, and on a LoRa
node it is mostly wrong.

Three costs, and they are not the same size:

  sleep      the node's quiescent draw, paid every second whatever it does
  sampling   per reading: wake, settle the sensor, convert, store
  transmit   per message: the radio at ~120 mA for the whole time-on-air

Time-on-air at SF12 is seconds, not milliseconds, so one transmit costs more than a
day of sampling. Sampling is 0.5-2% of the budget in every case below, so slowing a
sensor down to spare *the sensor* saves nothing measurable.

That does not mean sampling rate is free. It is not: twelve readings an hour instead
of one nearly triples a soil node's consumption — but the energy goes into the
radio, because twelve readings no longer fit one DR0 message. **You pay for what you
send**, and sample rate matters only through the data it generates.

The largest factor is neither. A node hosting a trough float that must report within
five minutes is awake and transmitting every five minutes whatever else it carries,
so the same hourly soil probe lasts 1518 days on its own node and 133 days on that
one. **Which node a sensor sits on is the power decision**, and it is an order of
magnitude bigger than any sample-rate choice.

    python3 power_budget.py
    python3 power_budget.py --battery 2600 --sleep-ua 10

Currents are documented assumptions, not measurements: an SX1276-class radio at
14 dBm, an STM32L-class MCU, a capacitive soil probe. The ratios are robust even
where the absolute numbers are off by a factor; a real figure needs the electrical
spec that open-questions still lacks, and this refuses to invent one.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import q5_encoding as q5  # noqa: E402

# --- assumptions, all overridable -------------------------------------------
TX_MA = 120.0          # SX1276 at 14 dBm
MCU_ACTIVE_MA = 8.0    # STM32L-class, awake but not transmitting
SLEEP_UA = 10.0        # stop mode with RTC
SENSOR_MA = 5.0        # capacitive soil probe while powered
SENSOR_SETTLE_S = 0.1  # power-on settle plus conversion
TX_WAKE_S = 0.3        # MCU awake around a transmit, beyond time-on-air
BATTERY_MAH = 2600.0   # one 18650


@dataclass(frozen=True)
class Channel:
    """One datastream on this node."""

    name: str
    sample_interval_s: float
    max_latency_s: float        # how stale may this be when it reaches the gateway
    sensor_ma: float = SENSOR_MA
    settle_s: float = SENSOR_SETTLE_S


def mah(current_ma: float, seconds: float) -> float:
    return current_ma * seconds / 3600.0


def sampling_mah_per_day(ch: Channel) -> float:
    per_day = 86400.0 / ch.sample_interval_s
    per_read = mah(ch.sensor_ma + MCU_ACTIVE_MA, ch.settle_s)
    return per_day * per_read


def transmit_schedule(channels, *, cap: int) -> tuple[float, float]:
    """(transmit interval, readings per transmit) for a node hosting `channels`.

    The interval is set by the tightest latency any channel asks for — a trough
    float that must be known within five minutes forces the radio awake every five
    minutes however sleepy everything else is.
    """
    interval = min(ch.max_latency_s for ch in channels)
    readings = sum(interval / ch.sample_interval_s for ch in channels)
    return interval, readings


def node_budget(channels, *, dr: int = 0, battery_mah: float = BATTERY_MAH,
                sleep_ua: float = SLEEP_UA, encode=None):
    encode = encode or q5.cbor_packed_flat
    sf = q5.SF_FOR_DR[dr]
    limit = q5.MAX_APP_PAYLOAD[dr]
    cap = q5.capacity(encode, limit)

    interval, readings_per_tx = transmit_schedule(channels, cap=cap)
    msgs_per_tx = max(1, -(-int(readings_per_tx + 0.999) // cap))
    q5._widen(min(int(readings_per_tx + 0.999) or 1, cap))
    size = len(encode(min(int(readings_per_tx + 0.999) or 1, cap), True))
    toa = q5.time_on_air(size + q5.LORAWAN_OVERHEAD, sf)

    tx_per_day = 86400.0 / interval
    tx_mah = tx_per_day * msgs_per_tx * (mah(TX_MA, toa)
                                         + mah(MCU_ACTIVE_MA, TX_WAKE_S))
    sample_mah = sum(sampling_mah_per_day(c) for c in channels)
    sleep_mah = mah(sleep_ua / 1000.0, 86400.0)
    total = tx_mah + sample_mah + sleep_mah
    return {
        "interval_s": interval, "readings_per_tx": readings_per_tx,
        "msgs_per_tx": msgs_per_tx, "toa_s": toa, "bytes": size,
        "tx_mah": tx_mah, "sample_mah": sample_mah, "sleep_mah": sleep_mah,
        "total_mah": total, "days": battery_mah / total if total else float("inf"),
    }


def show(label, channels, **kw):
    b = node_budget(channels, **kw)
    print(f"{label}")
    print("    channels            " + ", ".join(
        f"{c.name} @{c.sample_interval_s/60:.0f}min "
        f"(latency {c.max_latency_s/60:.0f}min)" for c in channels))
    print(f"    transmit            every {b['interval_s']/60:.0f} min, "
          f"{b['readings_per_tx']:.0f} readings, {b['msgs_per_tx']} msg, "
          f"{b['bytes']} B, {b['toa_s']*1000:.0f} ms on air")
    print(f"    transmit            {b['tx_mah']:8.3f} mAh/day   "
          f"{b['tx_mah']/b['total_mah']*100:5.1f}%")
    print(f"    sampling            {b['sample_mah']:8.3f} mAh/day   "
          f"{b['sample_mah']/b['total_mah']*100:5.1f}%")
    print(f"    sleep               {b['sleep_mah']:8.3f} mAh/day   "
          f"{b['sleep_mah']/b['total_mah']*100:5.1f}%")
    print(f"    total               {b['total_mah']:8.3f} mAh/day -> "
          f"{b['days']:.0f} days on {BATTERY_MAH:.0f} mAh")
    print()
    return b


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--battery", type=float, default=BATTERY_MAH)
    ap.add_argument("--sleep-ua", type=float, default=SLEEP_UA)
    ap.add_argument("--dr", type=int, default=0, choices=sorted(q5.SF_FOR_DR))
    args = ap.parse_args()
    kw = dict(dr=args.dr, battery_mah=args.battery, sleep_ua=args.sleep_ua)

    print(f"EU868 DR{args.dr} (SF{q5.SF_FOR_DR[args.dr]}), CBOR packed. "
          f"Radio {TX_MA:.0f} mA, MCU {MCU_ACTIVE_MA:.0f} mA, "
          f"sleep {args.sleep_ua:.0f} uA, battery {args.battery:.0f} mAh.\n")

    soil_hourly = Channel("soil", 3600, 3600)
    soil_5min = Channel("soil", 300, 3600)
    trough = Channel("trough", 300, 300)

    a = show("A  soil only, hourly  (the sleepy node)", [soil_hourly], **kw)
    b = show("B  soil only, sampled every 5 min, still sent hourly",
             [soil_5min], **kw)
    c = show("C  trough only, 5 min latency  (the urgent node)", [trough], **kw)
    d = show("D  both on ONE node  (soil hourly, trough 5 min)",
             [soil_hourly, trough], **kw)
    e = show("E  both on one node, soil sampled every 5 min too",
             [soil_5min, trough], **kw)

    print("what the numbers say")
    print(f"  A -> B  sampling soil 12x more often, same transmits: "
          f"{(b['total_mah']/a['total_mah'] - 1) * 100:+.1f}% energy")
    print(f"  A -> D  putting soil on the urgent node instead of its own: "
          f"{(d['total_mah']/a['total_mah'] - 1) * 100:+.0f}% energy")
    print(f"  D -> E  then sampling soil 12x more often as well: "
          f"{(e['total_mah']/d['total_mah'] - 1) * 100:+.1f}% energy")
    print(f"  C -> D  adding hourly soil to a node already serving the trough: "
          f"{(d['total_mah']/c['total_mah'] - 1) * 100:+.1f}% energy")
    print()
    print("  Reading a sensor is nearly free: sampling is 0.5-2% of the budget")
    print("  everywhere, so slowing a sensor down to spare the SENSOR saves nothing.")
    print()
    print("  But A->B shows sampling more often is NOT free, and the reason matters:")
    print("  the energy went into the radio, not the probe. Twelve readings an hour")
    print("  no longer fit one DR0 message, so the node sends two. You pay for what")
    print("  you SEND, and sampling and sending are usually coupled.")
    print()
    print("  Co-location dominates everything else. The same hourly soil probe lasts")
    print("  1518 days on its own node and 133 days on a node a trough float keeps")
    print("  awake - an 11x difference that no sample-rate choice comes close to.")
    print("  Which node a sensor sits on is the power decision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

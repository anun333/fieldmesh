#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure the Q5 candidates: bytes, LoRa airtime, and readings per hour.

open-questions Q5 asks which binary encoding the wire message uses, and the
recommendation was to decide it on a measured number rather than an argument,
because §12 puts the format version in every packet and nodes in a field are
expensive to change.

Bytes are the input; **airtime is the answer.** §5.2 says LoRa airtime is the
binding limit, and a 1% duty-cycle sub-band gives about 36 seconds of transmit
time per hour per device. So each candidate is scored on what actually matters:
how many readings per hour a node can deliver inside that budget.

    python3 q5_encoding.py
    python3 q5_encoding.py --readings 4 --sf 9

Message shape is §5.2's:

    message  := version, node_short_id, boot, seq, base_age, reading+
    reading  := channel, age_delta, value

Values are scaled integers, not floats. A soil-moisture probe reporting
0.000-1.000 to three decimals is an int16 of 0-1000; a temperature to 0.1 °C is
an int16. Treating sensor values as float64 is the single most expensive mistake
available here, so the fair comparison gives every candidate the same int16.
"""
from __future__ import annotations

import argparse
import math
import struct

import cbor2

VERSION = 1
NODE_ID = 0x4F2A17B3        # a Meshtastic node number
BOOT = 7
SEQ = 1234
BASE_AGE = 95               # seconds, stamped at transmit (§2)
CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]
AGE_DELTAS = [0, 300, 600, 900, 1200, 1500, 1800, 2100]
VALUES = [231, 238, 244, 249, 253, 258, 262, 267]    # soil moisture x1000

OBSERVED = "urn:librefarm:sm"   # a short alias; §3.4's URI lives in the registry


# ------------------------------------------------------------------ candidates

def hand_packed(n: int, with_node: bool = True) -> bytes:
    """The floor: a fixed bit-packed struct. Smallest possible, no schema, no
    forward compatibility — §12 still wants a version byte, so it gets one."""
    head = struct.pack(">B", VERSION)
    if with_node:
        head += struct.pack(">I", NODE_ID)
    head += struct.pack(">HHH", BOOT, SEQ, BASE_AGE)
    body = b"".join(struct.pack(">BHh", CHANNELS[i], AGE_DELTAS[i], VALUES[i])
                    for i in range(n))
    return head + body


def cbor_packed(n: int, with_node: bool = True) -> bytes:
    """CBOR with positional arrays and a CDDL schema. The recommendation under
    test: a standard encoding at close to hand-packed size, with COSE available
    for signing and tiny decoders everywhere."""
    head = [VERSION] + ([NODE_ID] if with_node else []) + [BOOT, SEQ, BASE_AGE]
    body = [[CHANNELS[i], AGE_DELTAS[i], VALUES[i]] for i in range(n)]
    return cbor2.dumps(head + [body])


def cbor_packed_flat(n: int, with_node: bool = True) -> bytes:
    """As above, but readings flattened into one array instead of nested arrays —
    three bytes of array overhead per reading is worth removing when the schema
    already fixes the triple."""
    head = [VERSION] + ([NODE_ID] if with_node else []) + [BOOT, SEQ, BASE_AGE]
    flat = []
    for i in range(n):
        flat += [CHANNELS[i], AGE_DELTAS[i], VALUES[i]]
    return cbor2.dumps(head + [flat])


def cbor_maps(n: int, with_node: bool = True) -> bytes:
    """CBOR with named keys: self-describing, and the version that wastes exactly
    the airtime a duty cycle cannot spare."""
    doc = {"v": VERSION, "boot": BOOT, "seq": SEQ, "base_age": BASE_AGE,
           "r": [{"ch": CHANNELS[i], "dt": AGE_DELTAS[i], "val": VALUES[i]}
                 for i in range(n)]}
    if with_node:
        doc["node"] = NODE_ID
    return cbor2.dumps(doc)


# --- protobuf, built from a real descriptor so the sizing is the library's ----

def _protobuf_class():
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = "q5.proto"
    fdp.package = "q5"
    fdp.syntax = "proto3"

    reading = fdp.message_type.add()
    reading.name = "Reading"
    F = descriptor_pb2.FieldDescriptorProto
    for num, name, typ in ((1, "channel", F.TYPE_UINT32),
                           (2, "age_delta", F.TYPE_UINT32),
                           (3, "value", F.TYPE_SINT32)):
        f = reading.field.add()
        f.name, f.number, f.type, f.label = name, num, typ, F.LABEL_OPTIONAL

    msg = fdp.message_type.add()
    msg.name = "Batch"
    for num, name, typ in ((1, "version", F.TYPE_UINT32),
                           (2, "node", F.TYPE_FIXED32),
                           (3, "boot", F.TYPE_UINT32),
                           (4, "seq", F.TYPE_UINT32),
                           (5, "base_age", F.TYPE_UINT32)):
        f = msg.field.add()
        f.name, f.number, f.type, f.label = name, num, typ, F.LABEL_OPTIONAL
    f = msg.field.add()
    f.name, f.number, f.type, f.label = "readings", 6, F.TYPE_MESSAGE, F.LABEL_REPEATED
    f.type_name = ".q5.Reading"

    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("q5.Batch"))


_Batch = None


def protobuf(n: int, with_node: bool = True) -> bytes:
    global _Batch
    if _Batch is None:
        _Batch = _protobuf_class()
    b = _Batch()
    b.version = VERSION
    if with_node:
        b.node = NODE_ID
    b.boot, b.seq, b.base_age = BOOT, SEQ, BASE_AGE
    for i in range(n):
        r = b.readings.add()
        r.channel, r.age_delta, r.value = CHANNELS[i], AGE_DELTAS[i], VALUES[i]
    return b.SerializeToString()


# --- SenML, RFC 8428, CBOR binding (§6 integer labels) ------------------------

SENML = {"bn": -2, "bt": -3, "bu": -4, "bver": -1, "n": 0, "u": 1, "v": 2, "t": 6}


def senml_cbor(n: int, with_node: bool = True) -> bytes:
    """SenML-CBOR without boot/seq — compact, standard, and **unusable** as it
    stands, because §1's dedup key is (site, node, boot, seq) and this cannot
    carry boot or seq. Measured to show what the interoperability would cost."""
    first = {SENML["bn"]: (f"{NODE_ID:08x}/" if with_node else ""),
             SENML["bt"]: -BASE_AGE, SENML["bu"]: "/", SENML["bver"]: 1,
             SENML["n"]: str(CHANNELS[0]), SENML["v"]: VALUES[0] / 1000,
             SENML["t"]: -AGE_DELTAS[0]}
    rest = [{SENML["n"]: str(CHANNELS[i]), SENML["v"]: VALUES[i] / 1000,
             SENML["t"]: -AGE_DELTAS[i]} for i in range(1, n)]
    return cbor2.dumps([first] + rest)


def senml_cbor_extended(n: int, with_node: bool = True) -> bytes:
    """SenML-CBOR with `boot_` and `seq_` custom labels. RFC 8428 requires a
    label ending in `_` to be understood or the record rejected, so this is
    SenML that no stock SenML consumer may accept — the interoperability win
    that made it attractive is gone, and the bytes are still larger."""
    doc = cbor2.loads(senml_cbor(n, with_node))
    doc[0]["boot_"] = BOOT
    doc[0]["seq_"] = SEQ
    return cbor2.dumps(doc)


CANDIDATES = [
    ("hand-packed struct", hand_packed),
    ("CBOR packed (flat + CDDL)", cbor_packed_flat),
    ("CBOR packed (nested)", cbor_packed),
    ("Protocol Buffers", protobuf),
    ("SenML-CBOR (no boot/seq)", senml_cbor),
    ("SenML-CBOR + custom labels", senml_cbor_extended),
    ("CBOR maps (named keys)", cbor_maps),
]


# ------------------------------------------------------------------- airtime

def time_on_air(payload_bytes: int, sf: int, *, bw_hz: int = 125_000,
                coding_rate: int = 1, preamble: int = 8, crc: int = 1,
                explicit_header: bool = True) -> float:
    """LoRa time-on-air in seconds (Semtech SX127x datasheet §4.1.1.7).

    `payload_bytes` is the PHY payload — for LoRaWAN that is the application
    payload plus 13 bytes of MHDR/DevAddr/FCtrl/FCnt/FPort/MIC.
    """
    t_sym = (2 ** sf) / bw_hz
    t_preamble = (preamble + 4.25) * t_sym
    low_rate_opt = 1 if sf >= 11 else 0     # mandatory at SF11/12 on 125 kHz
    numerator = 8 * payload_bytes - 4 * sf + 28 + 16 * crc - (0 if explicit_header else 20)
    denominator = 4 * (sf - 2 * low_rate_opt)
    payload_symb = 8 + max(math.ceil(numerator / denominator) * (coding_rate + 4), 0)
    return t_preamble + payload_symb * t_sym


LORAWAN_OVERHEAD = 13
#: EU868 maximum application payload by data rate (LoRaWAN regional parameters).
MAX_APP_PAYLOAD = {0: 51, 1: 51, 2: 51, 3: 115, 4: 222, 5: 222}
SF_FOR_DR = {0: 12, 1: 11, 2: 10, 3: 9, 4: 8, 5: 7}
DUTY_CYCLE_BUDGET_S = 36.0      # 1% of an hour, per sub-band per device


#: Realistic (sample interval, transmit interval) pairs in minutes. Sampling and
#: transmitting are different numbers — that is what batching is for — and the
#: duty cycle is spent on the second one.
OPERATING_POINTS = [(60, 60), (30, 60), (15, 60), (5, 60), (5, 30), (1, 60)]


def capacity(encode, limit: int, with_node: bool = True) -> int:
    """Largest batch this encoding fits inside `limit` bytes."""
    best = 0
    for n in range(1, 2 * len(CHANNELS) + 1):
        _widen(n)
        if len(encode(n, with_node)) <= limit:
            best = n
        else:
            break
    return best


def _widen(n: int) -> None:
    """Extend the sample batch to n readings, keeping it deterministic."""
    global CHANNELS, AGE_DELTAS, VALUES
    CHANNELS = [((i % 8) + 1) for i in range(max(n, 8))]
    AGE_DELTAS = [i * 300 for i in range(max(n, 8))]
    VALUES = [231 + (i % 40) for i in range(max(n, 8))]


def operating_points(encode, sf: int, limit: int, with_node: bool = True):
    """What each realistic duty actually costs, as a share of the 36 s budget."""
    cap = capacity(encode, limit, with_node)
    rows = []
    for sample_min, tx_min in OPERATING_POINTS:
        per_tx = max(1, tx_min // sample_min)
        msgs = math.ceil(per_tx / cap) if cap else 0
        _widen(min(per_tx, cap) if cap else 1)
        size = len(encode(min(per_tx, cap) if cap else 1, with_node))
        toa = time_on_air(size + LORAWAN_OVERHEAD, sf)
        airtime = msgs * toa * (60 / tx_min)
        rows.append((sample_min, tx_min, per_tx, cap, msgs, airtime,
                     airtime / DUTY_CYCLE_BUDGET_S * 100))
    return rows


def drain_hours(encode, sf: int, limit: int, sample_min: int,
                outage_days: int = 3, with_node: bool = True) -> tuple[int, float]:
    """Readings held after an outage, and hours of duty budget to clear them."""
    cap = capacity(encode, limit, with_node)
    backlog = outage_days * 24 * (60 // sample_min)
    _widen(cap)
    toa = time_on_air(len(encode(cap, with_node)) + LORAWAN_OVERHEAD, sf)
    msgs = math.ceil(backlog / cap)
    return backlog, msgs * toa / DUTY_CYCLE_BUDGET_S


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readings", type=int, default=8, help="readings per batch")
    ap.add_argument("--operating-points", action="store_true",
                    help="cost at realistic sample/transmit intervals, not at the "
                         "maximum (this is the number that decides anything)")
    ap.add_argument("--dr", type=int, default=0, choices=sorted(SF_FOR_DR),
                    help="EU868 data rate (default 0 = SF12, the worst case)")
    ap.add_argument("--no-node-id", action="store_true",
                    help="omit the node id, as LoRaWAN can (the session identifies "
                         "the device); Meshtastic cannot")
    args = ap.parse_args()

    n = args.readings
    sf = SF_FOR_DR[args.dr]
    limit = MAX_APP_PAYLOAD[args.dr]
    with_node = not args.no_node_id

    if args.operating_points:
        print(f"EU868 DR{args.dr} (SF{sf}), 1% duty cycle = "
              f"{DUTY_CYCLE_BUDGET_S:.0f} s/h. 'budget' is the share used.\n")
        hdr = (f"{'sample':>9}{'transmit':>10}{'rdg/tx':>8}{'cap':>5}"
               f"{'msgs/tx':>9}{'airtime/h':>11}{'budget':>9}")
        for label, fn in (("hand-packed struct", hand_packed),
                          ("CBOR packed + CDDL", cbor_packed_flat)):
            print(f"--- {label} ---")
            print(hdr)
            for s, tx, per, cap, msgs, air, pct in operating_points(
                    fn, sf, limit, with_node):
                print(f"{s:>6}min{tx:>7}min{per:>8}{cap:>5}{msgs:>9}"
                      f"{air:>9.1f}s{pct:>8.1f}%")
            print()
        print("--- backlog drain after a 3-day outage ---")
        for label, fn in (("hand-packed struct", hand_packed),
                          ("CBOR packed + CDDL", cbor_packed_flat)):
            for s in (60, 5):
                backlog, hours = drain_hours(fn, sf, limit, s, with_node=with_node)
                print(f"  {label:<20}{s:>3}min sampling -> {backlog:>4} readings, "
                      f"{hours:>5.1f} h of budget")
        _widen(n)
        return 0

    print(f"{n} readings per batch | EU868 DR{args.dr} (SF{sf}) | "
          f"app payload limit {limit} B | duty budget {DUTY_CYCLE_BUDGET_S:.0f} s/h"
          f"{'' if with_node else ' | node id omitted'}")
    print()
    hdr = (f"{'encoding':<28}{'bytes':>6}{'fits':>6}{'ToA':>9}"
           f"{'msg/h':>8}{'readings/h':>12}{'vs floor':>10}")
    print(hdr)
    print("-" * len(hdr))

    floor = len(hand_packed(n, with_node))
    rows = []
    for name, fn in CANDIDATES:
        payload = fn(n, with_node)
        size = len(payload)
        toa = time_on_air(size + LORAWAN_OVERHEAD, sf)
        per_hour = DUTY_CYCLE_BUDGET_S / toa
        fits = size <= limit
        rows.append((name, size, fits, toa, per_hour, per_hour * n, size / floor))
        print(f"{name:<28}{size:>6}{('yes' if fits else 'NO'):>6}"
              f"{toa * 1000:>8.0f}ms{per_hour:>8.1f}{per_hour * n:>12.0f}"
              f"{size / floor:>9.2f}x")

    print()
    best = min(r for r in rows if r[2])
    print(f"smallest that fits DR{args.dr}: {best[0]} at {best[1]} B")
    over = [r[0] for r in rows if not r[2]]
    if over:
        print(f"does not fit DR{args.dr}: {', '.join(over)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

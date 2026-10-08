<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Q5 measured: which binary encoding

Run 2026-10-07 with [tools/q5_encoding.py](../../tools/q5_encoding.py).
Reproduce with `make q5`; the operating-point tables with `make q5-points`.

open-questions Q5 recommended deciding this on a measured number rather than an
argument, because §12 puts the format version in every packet and nodes already in
a field are expensive to change. **The measurement overturned the recommendation's
confidence and eliminated two candidates outright.**

## Method

One realistic batch in §5.2's shape — `version, node_short_id, boot, seq,
base_age, reading+` where `reading := channel, age_delta, value` — with eight
readings, encoded by each candidate. Values are **scaled integers, not floats**: a
soil probe reporting 0.000–1.000 to three decimals is an int16 of 0–1000. Treating
sensor values as float64 is the most expensive mistake available here, so every
candidate gets the same int16.

Bytes are the input; **airtime is the answer.** §5.2 says LoRa airtime is the
binding limit, so each candidate is scored on readings per hour inside a 1%
duty-cycle budget of 36 s, at EU868 DR0 (SF12) — the worst case a node must
survive. Time-on-air is the Semtech SX127x formula, with both reference points
hand-derived and pinned to the microsecond in `tools/test_q5_encoding.py`.

## Result at DR0 (SF12, 51-byte application payload)

| Encoding | 8 readings | Fits DR0 | Max batch | Readings/h | vs floor |
| --- | --- | --- | --- | --- | --- |
| Hand-packed struct | 51 B | yes | 8 | **103** | 1.00x |
| CBOR packed, flat + CDDL | 64 B | no | 6 | **77** | 1.25x |
| CBOR packed, nested arrays | 71 B | no | 5 | 68 | 1.39x |
| Protocol Buffers | 91 B | no | 4 | 52 | 1.78x |
| SenML-CBOR (no boot/seq) | 162 B | no | 1 | 16 | 3.18x |
| SenML-CBOR + custom labels | 177 B | no | 1 | 13 | 3.47x |
| CBOR maps, named keys | 178 B | no | **0** | 0 | 3.49x |

## Two candidates are eliminated, not merely ranked

**CBOR with named keys cannot carry a single reading at DR0.** One reading is
56 bytes against a 51-byte limit. Map keys on every message waste exactly the
airtime a duty cycle cannot spare, and at SF12 that is not inefficiency, it is
non-function.

**SenML-CBOR does not survive carrying `boot` and `seq`.** It was the most
interesting candidate — an IETF standard built for sensor measurement lists, whose
base-name and base-time fields are precisely the delta compression §5.2's batching
wants. But §1's dedup key is `(site, node, boot, seq)` and SenML has nowhere to put
`boot` or `seq`. Adding them as `boot_` and `seq_` custom labels costs 15 bytes and,
worse, RFC 8428 requires a label ending in `_` to be understood or the record
rejected — so extended SenML is SenML no stock consumer may accept. The
interoperability that made it attractive is gone and the bytes are still 3.5x the
floor. One reading per message at DR0.

## Correction: the 25% was the wrong number

The table above compares candidates at their **maximum** batch size, and a maximum
is not an operating point. Asked whether hourly sampling would do, the comparison
had to be redone at realistic duties — `--operating-points`:

| Sample | Transmit | Readings/tx | Msgs/tx | Airtime/h | Share of 36 s |
| --- | --- | --- | --- | --- | --- |
| 60 min | 60 min | 1 | 1 | 1.6 / **1.8** s | 4.6% / **5.0%** |
| 30 min | 60 min | 2 | 1 | 1.8 / **2.0** s | 5.0% / **5.5%** |
| 15 min | 60 min | 4 | 1 | 2.1 / **2.3** s | 5.9% / **6.4%** |
| 5 min | 60 min | 12 | 2 | 5.6 / **5.6** s | 15.5% / **15.5%** |
| 1 min | 60 min | 60 | 8 / **10** | 22.3 / **27.9** s | 62% / **78%** |

(hand-packed / **CBOR packed**.)

**At every realistic duty the two encodings are within a few tenths of a second of
each other, out of 36.** At hourly sampling the difference is 0.2 s/h — half a
percent of the budget. At five-minute sampling with hourly transmission they are
*identical*, because both need two messages.

So the honest conclusion is not "CBOR costs 25% and that is affordable". It is
**airtime does not decide between the surviving candidates at all.** The 25%
difference in maximum throughput is invisible at any rate a farm would actually
run, and it becomes visible only in two places:

- **one-minute sampling** — 62% of the budget against 78%, where the margin starts
  to matter;
- **backlog drain** (§5.3) — after a three-day outage a five-minute node holds 864
  readings, 8.4 hours of budget hand-packed against 11.2 in CBOR. At hourly
  sampling the same outage is 72 readings and under an hour either way.

## The decision: CBOR packed arrays with a CDDL schema

Since airtime does not decide it, what does is tooling. CBOR brings a schema
language (CDDL), COSE for signing, and a decoder in every language — which is what
§12's versioned format and §9.2's conformance suite need. A hand-rolled struct has
no schema, no versioning story beyond a byte we define ourselves, and no tooling,
and §9.2 cannot certify a driver against a layout that exists only in prose. That
was always the argument; the measurement's contribution is showing that it costs
nothing to act on.

**Protocol Buffers is rejected, though more narrowly than the first table
suggested.** 91 bytes and four readings per message is half the floor's maximum
throughput, which the operating-point table shows is mostly irrelevant — at hourly
sampling it would also sit around 5% of the budget. It loses on the same ground
CBOR wins: field tags and varint framing buy nothing over CDDL here, while
requiring a code generator in the node's build. A closer call than it looked.

**The hand-packed layout stays documented as an escape hatch**, for a node that must
drain a very long backlog at SF12 and nothing else. Not the default, and not two
formats to maintain — a profile of one, with the version byte distinguishing it.

## Two findings that change §5.2 regardless of the choice

**The node id belongs on the wire optionally, not always.** On LoRaWAN the session
already identifies the device, so the four bytes are pure waste; on Meshtastic they
are required. Measured: omitting it takes hand-packed from 51 to 47 bytes and CBOR
from 64 to 59. §5.2's grammar should mark `node_short_id` optional, present per link
driver.

**Never size a batch to exactly the payload limit.** Hand-packed at eight readings
is *exactly* 51 bytes, which looks like a tidy fit and is a trap: LoRaWAN MAC
commands piggyback in `FOpts` and shrink the available `FRMPayload`, and ADR moves
the data rate under the node while it is running. Batch size must be computed from
the **current** data rate with headroom, not fixed at build time. The encoder needs
a `max_payload` argument, not a constant.

## Is hourly sampling enough?

For soil moisture **trends**, yes — ET depletion is a slow process, commercial
loggers commonly default to 15-60 minutes, and the power budget prefers it. But
three clauses want faster data, and they are the reason sampling and transmission
are separate numbers:

- **A stuck float valve on a stock trough.** Hourly detection of an empty trough in
  summer is an animal-welfare problem, and livestock water monitoring is the module
  recommended to ship first.
- **Flatline detection (§4.2).** A threshold expressed in samples means twelve hours
  at hourly sampling and one hour at five-minute — which is the defect this question
  exposed; see below.
- **Rate-of-change (§4.2).** At hourly resolution a real irrigation event and a
  sensor fault look alike, so the check loses most of its discriminating power.

The resolution is that **batching exists precisely so these can differ**: sample
every five minutes for the health checks, transmit once an hour. That is 15.5% of
the duty budget, and the readings arrive in two messages instead of twelve.

## The defect this exposed: count-based thresholds

§4.2's own wording is "identical values for **longer than** physically plausible" —
a duration. The first implementation used a *count* (`flat_n`), which means the same
configured threshold is a different physical test on two farms that sample at
different rates. `flat_n: 12` catches a one-hour freeze at five-minute sampling and
misses it entirely at hourly.

Fixed: `flat_seconds` is now the primary threshold and `flat_n` is a confidence
guard (two equal readings an hour apart prove little, whatever the span between
them). `sdk/test_checks.py::TestFlatlineIsSampleRateIndependent` asserts the
property that was missing — the same duration threshold gives the same verdict at
60, 15, 5 and 1 minute sampling — and demonstrates the count-only trap rather than
describing it.

## What this does not settle

Meshtastic's payload ceiling is roughly 237 bytes, so payload size is not its
binding constraint — airtime still is, and the 25% is paid there too, as airtime
rather than as a fitting problem. The numbers above are the LoRaWAN worst case,
which is the right case to design against; a Meshtastic-specific run is worth doing
once Q6 is settled.

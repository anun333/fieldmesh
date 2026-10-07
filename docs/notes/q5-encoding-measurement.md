# Q5 measured: which binary encoding

Run 2026-10-07 with [tools/q5_encoding.py](../../tools/q5_encoding.py).
Reproduce with `make q5`.

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

## The decision: CBOR packed arrays with a CDDL schema

Unchanged from the recommendation, but now on evidence rather than taste, and with
the cost known instead of assumed.

**What it costs: 25%.** Six readings per message instead of eight, 77 readings per
hour instead of 103.

**Why that is affordable.** A five-minute sampling interval is 12 readings an hour,
so 77 is six times any realistic steady-state rate for one node. The place the 25%
actually bites is backlog drain (§5.3): after a three-day outage a five-minute node
holds about 864 readings, which is 8.4 hours of draining hand-packed against 11.2
hours in CBOR. Real, and not decisive — both are well inside the next outage.

**What it buys.** A standard encoding with a schema language (CDDL), COSE for
signing, and a decoder in every language — which is what §12's versioned format and
§9.2's conformance suite actually need. A hand-rolled struct is 25% better on
airtime and has no schema, no versioning story beyond a byte we define ourselves,
and no tooling; §9.2 cannot certify a driver against a layout that exists only in
prose.

**Protocol Buffers is rejected on measurement.** 91 bytes, four readings per
message, half the throughput of the floor, for a schema story CDDL already
provides. Field tags and varint framing are the wrong trade at this payload size.

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

## What this does not settle

Meshtastic's payload ceiling is roughly 237 bytes, so payload size is not its
binding constraint — airtime still is, and the 25% is paid there too, as airtime
rather than as a fitting problem. The numbers above are the LoRaWAN worst case,
which is the right case to design against; a Meshtastic-specific run is worth doing
once Q6 is settled.

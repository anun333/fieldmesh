# Provenance of the code in `sdk/`

Everything here originates in **campus_twin** (`~/dev/campus_twin`), the sibling
buildings/BAS platform by the same author. It arrives by **copy and relicense**, not by
import: librefarm owns these files now and is free to diverge, which is what the
constellation rule asks for — no repo stops building because a sibling moved.

## The license arrangement

campus_twin is GPL-3.0 as a whole. The transport spine was dual-licensed **in its
original home** before anything was copied, each file carrying:

```
# SPDX-License-Identifier: Apache-2.0 OR GPL-3.0-or-later
```

librefarm exercises the Apache-2.0 option, so files here carry
`SPDX-License-Identifier: Apache-2.0` alone.

Relicensing at the source rather than at the destination is deliberate. Stamping a
GPL-3.0 copy as Apache-2.0 on arrival would have worked, but it builds a one-way valve:
the permissive copy could flow back to campus_twin, while later GPL-only improvements
there could never come forward. Dual-licensing upstream keeps both directions open
permanently. Full reasoning in `campus_twin/LICENSING.md`.

The author holds sole copyright on every campus_twin commit and there is no CLA, so no
third party's agreement was needed.

The repository's licensing was **decided on 2026-10-07** ([open-questions.md](../docs/spec/open-questions.md)
Q2, [LICENSING.md](../LICENSING.md)): `sdk/` is Apache-2.0, so files ported here take the
Apache-2.0 option of their upstream dual licence and say so in their SPDX line.

## What moved

| Here | From | Change |
| --- | --- | --- |
| `spool.py` | `open-bas/connectors/_ingest.py` | Adapted. Ingest path and token environment variable parameterised (`TWIN_TOKEN` → `LIBREFARM_TOKEN`, `/api/ingest` now a default rather than a constant); docstring retargeted at spec §5.2 and §5.4. Logic unchanged. |
| `modbus_rtu.py` | `open-bas/connectors/modbus_rtu.py` | Verbatim logic — CRC-16/MODBUS, frame building, reply parsing, `RtuSource`, `RtuResponder`. Docstring retargeted: the equipment examples are farm equipment, and the read-only rationale is **reversed in meaning** (see below). |
| `test_spool.py` | — | New. Written here; no counterpart upstream. |
| `csv_import.py` | `open-bas/connectors/csv_replay.py` | **Retargeted, and two defaults reversed.** Writes `Observation`s on declared raw datastreams instead of POSTing campus-twin/v1 batches. Upstream read every timestamp as UTC; here a timezone must be declared, because a spreadsheet's `14:00` is local and the UTC assumption shifts every reading invisibly — and the autumn hour that occurs twice and the spring hour that never occurs are reported, not guessed. Upstream applied a scale and offset on import; here that is refused, because it would store a value the file never contained with no record of the change (§3.2). Adds required `uncertainty_s` (§2), idempotent re-import, and per-row provenance with the file's SHA-256. |
| `mqtt_bridge.py` | `open-bas/connectors/mqtt_bridge.py` | **Profile parsers kept; everything they feed rewritten.** Bindings point at raw datastreams and remain the allowlist, with unbound devices reported by id. Scale, offset and invert removed for the same §3.2 reason; ON/OFF becomes a boolean, not `1.0`. **Fixes an upstream bug**: Tasmota's `Time` has no offset, and upstream's `fromisoformat(...).timestamp()` read it in the *host machine's* zone, so one message got different timestamps on different machines — here a naive stamp needs the binding's `timezone` or is stamped on arrival and counted. Link health (RSSI, SNR, battery, LQI) is bindable like any point (§4.3) rather than auto-emitted. The ESPresense profile is removed: it exists to see people's phones. No `paho-mqtt`: the live path is `mosquitto_sub -F '%j'` on stdin, keeping `sdk/` stdlib-only. |
| `mqtt_emulator.py` | `open-bas/connectors/mqtt_emulator.py` | Same shape; devices moved from a plant room to a farm (hoop-house ESPHome node, Tasmota pump plug, Shelly well-pump relay, Zigbee tank-leak and soil sensors, a Home Assistant rain gauge, a ChirpStack field probe using a common LoRaWAN soil probe's published decoder field names). Presence-tracking messages removed. |
| `test_csv_import.py`, `test_mqtt_bridge.py` | — | New. The upstream tests were never relicensed and assert campus-twin/v1 shapes, so these were written here. |

### The one semantic change worth knowing about

`modbus_rtu.py` has no write function codes, in both repos, for opposite reasons.
Upstream it is permanent: *"the twin reads equipment, it never commands it."* Here it is
temporary: layer zero does command pumps and valves (§6), but the first release ships
observations only, and writes arrive later underneath the command contract — desired
state rather than toggle, expiry, bounded idempotency, node-side limits. A bare Modbus
write with none of that is the unsafe path §6 exists to prevent, so the absence is
load-bearing until §6 is implemented.

This file will diverge rather than track. That is expected.

## What has not moved, and what it is waiting on

These are wanted, and in several cases nearly ready, but each depends on a decision or
an artifact that does not exist yet. Copying them now would mean rewriting them.

| Upstream file | Wanted for | Blocked on |
| --- | --- | --- |
| `mesh_emulator.py` | Virtual nodes for the simulated farm | **Superseded rather than blocked.** Q5 was decided (CBOR packed arrays), and `sim/node.py` with `sim/link.py` already emit that wire format from simulated nodes, which is what this would have done. Its profile table was buildings-domain throughout. |
| `meshtastic_bridge.py` | The gateway's first link driver | **Q6**, which link ships first, and real hardware (build step 7). Q5, the registry (§1) and batching (§5.2) — the old blockers — all exist now |
| `modbus_collector.py`, `modbus_emulator.py` | The wired driver and its emulator | The driver manifest (§9.1) |
| `test_metric_registry.py` | The gate that fails a producer emitting an unregistered name — the enforcement §3.4 needs | **Unblocked** — Q4b was decided and `vocab.py` is the registry. Not yet ported: today a datastream is refused only if its observed property is not a URI, not if the URI is unregistered or does not resolve |

What remains upstream is waiting on Q6 and hardware for the Meshtastic driver, the
driver manifest (§9.1) for the Modbus collector pair, and nothing at all for the
vocabulary gate, which is simply unported.

## Dependencies

Everything in `sdk/` is **stdlib only**, which is why these two could move first. Upstream's
optional extras (`paho-mqtt` for the live MQTT path, `bacpypes3` for BACnet) are not
required by anything in `sdk/`.

No file here depends on the `meshtastic` PyPI package, which is GPL-3.0 and would have
been an obstacle to an Apache-2.0 SDK regardless of who wrote the calling code.

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

**The repo-wide license is still undecided** — see [open-questions.md](../docs/spec/open-questions.md)
Q2, which recommends a three-way split (spec CC-BY-4.0, SDK and wire format Apache-2.0,
reference implementation AGPL-3.0). `sdk/` is Apache-2.0 under that recommendation;
nothing else in librefarm has a license yet, and `LICENSE-APACHE-2.0` at the repo root
is the text these files point at, not a decision about the whole project.

## What moved

| Here | From | Change |
| --- | --- | --- |
| `spool.py` | `open-bas/connectors/_ingest.py` | Adapted. Ingest path and token environment variable parameterised (`TWIN_TOKEN` → `LIBREFARM_TOKEN`, `/api/ingest` now a default rather than a constant); docstring retargeted at spec §5.2 and §5.4. Logic unchanged. |
| `modbus_rtu.py` | `open-bas/connectors/modbus_rtu.py` | Verbatim logic — CRC-16/MODBUS, frame building, reply parsing, `RtuSource`, `RtuResponder`. Docstring retargeted: the equipment examples are farm equipment, and the read-only rationale is **reversed in meaning** (see below). |
| `test_spool.py` | — | New. Written here; no counterpart upstream. |

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
| `mesh_emulator.py` | Virtual nodes for the simulated farm | **Q5** — the emulator has to emit layer zero's wire message, and the encoding is undecided. The harness ports cleanly (deterministic seed, profile table, stdout-or-MQTT, `--once`, `--no-jitter`); the payload cannot. Its profile table is also entirely buildings domain (CO₂, PM2.5, chilled water, condenser probes) and becomes soil moisture, trough level and hoop-house climate. |
| `meshtastic_bridge.py` | The gateway's first link driver | **Q5**, plus the registry (§1) and batching (§5.2) in code |
| `csv_replay.py` | CSV adapter (§10) and dataset replay (§9.2) | The observation and datastream model in code (§3); also coupled to the `campus-twin/v1` batch shape and its metric/unit/layer binding |
| `modbus_collector.py`, `modbus_emulator.py` | The wired driver and its emulator | The driver manifest (§9.1) |
| `mqtt_bridge.py`, `mqtt_emulator.py` | The bus observations publish on (§5.1) | The observation shape |
| `test_metric_registry.py` | The gate that fails a producer emitting an unregistered name — the enforcement §3.4 needs | **Q4b** — which vocabulary |

Most of these unblock at step 1 of the build order in
[VIRTUAL_FARM.md](../docs/VIRTUAL_FARM.md): the data model and the log, as code.

## Dependencies

Both files here are **stdlib only**, which is why they could move first. Upstream's
optional extras (`paho-mqtt` for the live MQTT path, `bacpypes3` for BACnet) are not
required by anything in `sdk/`.

No file here depends on the `meshtastic` PyPI package, which is GPL-3.0 and would have
been an obstacle to an Apache-2.0 SDK regardless of who wrote the calling code.

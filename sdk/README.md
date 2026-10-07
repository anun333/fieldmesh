# `sdk/` — layer zero as code

Build-order step 1 from [docs/VIRTUAL_FARM.md](../docs/VIRTUAL_FARM.md): the data
model and the log, with no devices at all. Stdlib only, Apache-2.0.

```sh
cd sdk && python3 -m unittest discover -p 'test_*.py'    # 116 tests, ~0.06s
```

## Modules

| Module | Clause | What it is |
| --- | --- | --- |
| `ids.py` | §1 | UUIDv7 per RFC 9562, with a per-millisecond counter so ids are *strictly* monotonic — which §3.3's precedence tiebreak depends on |
| `hlc.py` | §7.4 | Hybrid logical clocks. Event ordering a bad clock cannot reorder, which §2 says to expect |
| `model.py` | §1–§4 | The contract types, frozen, rejecting at construction what the spec forbids |
| `codec.py` | §7.1, §7.6 | Exact JSON round-trip for every record — the log and the export share one encoding |
| `log.py` | §7.1, §7.3 | The append-only log. No update, no delete, by construction |
| `project.py` | §2, §3.2, §3.3, §4.2, §7.1 | Derived state: live rows, quality precedence, calibration by `measured_at`, staleness, ordering |
| `fixtures.py` | — | Record builders for tests, and the seed of the virtual farm's own |
| `spool.py` | §5.2 | Gateway-side store-and-forward: retry, auth, spool, drain |
| `modbus_rtu.py` | §9 | Modbus RTU framing over serial, read function codes only (see [PROVENANCE.md](PROVENANCE.md)) |

## The four rules worth knowing

Each was a defect in the v0 draft, and each has a test class named after it in
`test_project.py`:

1. **Recalibration appends.** Raw and calibrated values are separate datastreams;
   a re-derivation carries `supersedes`; exactly one live row exists per
   `(datastream, measured_at)` and `live_observations` *checks* that rather than
   assuming it. Two live rows at one timestamp is precisely what v0 produced, and
   it doubles every SensorThings client's data.
2. **Calibration is selected by `measured_at`.** A reading that spent three days
   in a node's buffer gets the coefficients that were in force when it was taken,
   not whatever is current at ingest.
3. **Quality is an assertion, not a column.** A flag *set* plus a derived
   `usable` summary, carrying the check and threshold version it used. A person
   outranks the foundation and the machine's original stays readable. Retuning a
   threshold cannot re-flag history.
4. **Ordering is honest.** Within one node `(boot, seq)` beats `measured_at`,
   because the counter is reliable when the clock is not. Across nodes,
   observations whose uncertainty windows overlap are genuinely unordered —
   `concurrent()` is how you ask, and `order_observations()` is for display only.

## What is deliberately not here

| Missing | Waiting on |
| --- | --- |
| The wire message and gateway ingest (§5.1, §5.2) | open-questions **Q5** — the binary encoding |
| Health-check implementations (§4.2) | Nothing. The assertion shape is here; the checks are build-order step 4 |
| The command contract (§6) | Scope: the first release ships observations only, and §6 freezes after a season |
| Sharing grants and erasure (§7.3, §7.6) | **Q16**, **Q17** |
| SensorThings serialization (§10) | Nothing structural — next obvious piece of work |
| Field-level conflict resolution and conflict events (§7.4) | **Q14** — which fields must never resolve silently |

`State.validate()` returns every violation it can see rather than raising on the
first, so a conformance run can show all of them at once.

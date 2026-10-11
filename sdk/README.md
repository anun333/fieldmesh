# `sdk/` — layer zero as code

Build-order step 1 from [docs/VIRTUAL_FARM.md](../docs/VIRTUAL_FARM.md): the data
model and the log, with no devices at all. Apache-2.0. Two dependencies: `cbor2`, for the CBOR wire format in `wire.py`, and `cryptography`, only in `erasure.py`; everything
else is the standard library.

```sh
cd sdk
python3 -m unittest discover -p 'test_*.py'   # 259 tests, ~0.15s
python3 demo.py                               # see it run: log -> state -> SensorThings
python3 demo.py --interval                    # phenomenonTime as the §2 uncertainty window
python3 demo.py --v2                          # the unpublished 2.0 draft dialect
python3 demo.py --json                        # the served Observations collection
```

## Modules

| Module | Clause | What it is |
| --- | --- | --- |
| `ids.py` | §1 | UUIDv7 per RFC 9562, with a per-millisecond counter so ids are *strictly* monotonic — which §3.3's precedence tiebreak depends on |
| `hlc.py` | §7.4 | Hybrid logical clocks. Event ordering a bad clock cannot reorder, which §2 says to expect |
| `model.py` | §1–§4 | The contract types, frozen, rejecting at construction what the spec forbids |
| `codec.py` | §7.1, §7.6 | Exact JSON round-trip for every record — the log and the export share one encoding |
| `log.py` | §7.1, §7.3 | The append-only log. No update, no delete, by construction |
| `project.py` | §2, §3.2, §3.3, §4.2, §7.1 | Derived state: live rows, quality precedence and quality as known at a moment, calibration by `measured_at`, staleness, ordering |
| `fixtures.py` | — | Record builders for tests, and the seed of the virtual farm's own |
| `wire.py` | §5.2, §5.3 | The wire message: CBOR packed arrays, a CDDL schema, payload-budget-aware packing, transmit-time restamping, and `Window`, a node's aggregate of a low-urgency series (Q20) |
| `registry.py` | §1, §8.1, §9.1 | Short wire ids to full identities, plus each node's clock source and uncertainty budget |
| `gateway.py` | §5.1, §5.4, §8.1 | Ingest: decode, quarantine, dedup, gaps, reboots, raw, derive, assess |
| `checks.py` | §4.2 | The four health checks, writing assertions and never mutations. One assertion per run carrying the union of flags |
| `sensorthings.py` | §10, §3.2 | The SensorThings out-adapter. Serves **live observations only**, which is the compatibility promise v0 would have broken. Validated against FROST-Server |
| `records.py` | §3, §7.4; Q14 | The farm's records, farmOS-shaped: land and its boundary, animals and groups, inputs applied, animal treatments and their withdrawal, harvest lots. Each declares the fields that never resolve silently and the ones that merge by union |
| `edits.py` | §7.4; Q7 | Offline edits: each names the versions its writer had seen, so concurrency is decided by knowledge, not clocks. Conflicts keep both values and are noticed into the log; withdrawal and pre-harvest checks read every candidate |
| `sharing.py` | §7.6; Q16 | Sharing grants: what a grantee may read at a moment. A grant covers what had arrived when it was made unless it asks for more and says when that ends; revoking stops access from then on |
| `erasure.py` | §7.3; Q17 | Erasure by key destruction: personal text sealed to a per-person key, wrapped by a farm key kept out of backups; erasing destroys the person's key and rotates the farm key |
| `forecast.py` | §3.1, §3.2, §10; Q26 | Weather forecasts as input data: runs onto a `forecast` datastream with `issued_at`, the latest issue live, every run kept and scored against the farm's sensors by lead time |
| `demo.py` | — | One command that exercises the whole chain, no hardware and no site data |
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
| A *real* node (firmware) | **Q6**, and hardware. The behaviour is specified and simulated in [sim/node.py](../sim/node.py) |
| A link driver (Meshtastic) | **Q6** |
| The aggregate datastream kind | **Q20** |

| The command contract (§6) | Scope: the first release ships observations only, and §6 freezes after a season |
| Sharing grants and erasure (§7.3, §7.6) | **Q16**, **Q17** |
| A GIS client actually reading it (QGIS) | The HTTP layer below — documents being right is necessary, not sufficient |
| An HTTP service (`$filter`, `$expand`, `$top`, paging) | Nothing. `sensorthings.py` produces the documents; routing and query options are the next layer |
| Harrow Bend assembled — six beds, paddock, research plot, hoop house, well | Nothing. Build-order step 5, and the biggest remaining gap |
| Field-level conflict resolution and conflict events (§7.4) | **Q14** — which fields must never resolve silently |

`State.validate()` returns every violation it can see rather than raising on the
first, so a conformance run can show all of them at once.

## The SensorThings mapping

Four decisions in `sensorthings.py` that could each reasonably have gone the other
way, so they are stated rather than buried:

1. **Only live observations are served.** A recalibrated series keeps both rows in
   the log forever; serving both would put two observations at one
   `phenomenonTime` and double every client's chart. This is the single most
   important line in the adapter.
2. **Layer-zero fields are namespaced under `parameters/fieldmesh`.** 1.1
   documents `parameters` as environmental conditions during measurement;
   `received_at`, `boot` and `seq` are not that. Nesting keeps `$filter` paths
   working and reduces the 2.0 migration (`parameters` → `properties`) to one key.
3. **`resultTime` is null.** It means "when the result was generated", which layer
   zero does not record. `received_at` is a different thing, and claiming it here
   would be a small lie in a field researchers read. 1.1 explicitly allows null.
4. **`resultQuality` is emitted for a clean assertion too**, and omitted only when
   nothing has been asserted — "checked, no objection" is a judgement, and
   collapsing it into "not checked" discards what a certifier cares about.

Validated against the reference implementation: FROST-Server accepted a deep
insert of these documents (`201`), round-tripped `resultQuality` with nested
`evidence` and `parameters/fieldmesh` intact, and after one fix the Datastream and
Observation documents are at full key parity with its own. The findings are pinned
in `TestValidatedAgainstFrost` so they survive without the container; the method
and what it caught are in [frost-validation.md](../docs/notes/frost-validation.md).

## Ingest

`wire.py` + `registry.py` + `gateway.py` are §5.1's step 4 in order: resolve ids,
compute times, dedup on `(site, node, boot, seq)`, write raw, derive by the
calibration in force at `measured_at`, assess.

Everything it learns that is not a reading, it records — an unparseable frame, an
unapproved device, a hole in a sequence, a reboot, an evicted backlog, a channel with
no binding, a calibration it cannot apply. The alternative is a dataset with quiet
holes and no way to tell a gap from a reading that never existed.

Four behaviours where the easy implementation is wrong, each with a test:

1. **An unregistered node is quarantined, not dropped** (§8.1). Its frames are
   logged so the device can be approved and the data replayed; nothing of its
   reaches an observation.
2. **A sequence going backwards is usually a wrap, not a replay** (§1). Getting this
   wrong discards a node's next 32768 readings.
3. **A `seq` reset after a reboot is not a duplicate** — the v0 defect, now a
   regression test.
4. **Two readings may not land on one instant.** Wire ages are whole seconds, so a
   channel sampled faster than 1 Hz cannot express distinct instants, and writing
   both would break §3.2's uniqueness. The gateway keeps the first and records the
   second. This one was found by `State.validate()` failing in a test — the
   invariant earning its keep.

## Health checks

Four checks (§4.2), writing assertions and never touching an observation. The
thing worth knowing is that they produce **one assertion per run** carrying the
union of flags, not one assertion each. §4.2's four one-flag checks and §3.3's
single live assertion could not both hold as written: two checks firing together
meant one won on precedence and the other's finding silently vanished.
`test_separate_assertions_per_check_would_lose_a_flag` demonstrates it rather than
asserting it, and the spec now carries the amendment (§17) with `evidence`
recording which check fired and why.

Three smaller judgements: cross-check flags only `suspect`, because when two
probes disagree it cannot say which lies; a longer gap permits a larger rate
change, since three hours of absence genuinely allows more movement than three
minutes; and `assess_series` will never supersede a person's override with a
machine verdict (§3.3).

The version-dependent names live in one `Dialect` class, which is what makes §10's
"one thin layer" checkable: `test_the_model_knows_nothing_about_sensorthings`
greps `model.py` for `@iot`, `phenomenonTime`, `resultQuality` and
`unitOfMeasurement` and fails if any of them leaked in. `SensorThings20Draft`
exists to prove the seam, and its `supports_quality = False` is where the dropped
`resultQuality` of open-questions Q18 becomes visible: quality falls into the
extras bag, where nothing standards-aware will look.

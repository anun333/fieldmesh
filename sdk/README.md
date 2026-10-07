# `sdk/` — layer zero as code

Build-order step 1 from [docs/VIRTUAL_FARM.md](../docs/VIRTUAL_FARM.md): the data
model and the log, with no devices at all. Stdlib only, Apache-2.0.

```sh
cd sdk
python3 -m unittest discover -p 'test_*.py'   # 192 tests, ~0.10s
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
| `project.py` | §2, §3.2, §3.3, §4.2, §7.1 | Derived state: live rows, quality precedence, calibration by `measured_at`, staleness, ordering |
| `fixtures.py` | — | Record builders for tests, and the seed of the virtual farm's own |
| `checks.py` | §4.2 | The four health checks, writing assertions and never mutations. One assertion per run carrying the union of flags |
| `sensorthings.py` | §10, §3.2 | The SensorThings out-adapter. Serves **live observations only**, which is the compatibility promise v0 would have broken. Validated against FROST-Server |
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
| The wire message and gateway ingest (§5.1, §5.2) | open-questions **Q5** — the binary encoding |

| The command contract (§6) | Scope: the first release ships observations only, and §6 freezes after a season |
| Sharing grants and erasure (§7.3, §7.6) | **Q16**, **Q17** |
| A GIS client actually reading it (QGIS) | The HTTP layer below — documents being right is necessary, not sufficient |
| An HTTP service (`$filter`, `$expand`, `$top`, paging) | Nothing. `sensorthings.py` produces the documents; routing and query options are the next layer |
| The physics that makes readings mean something | Nothing. Build-order step 2 |
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
2. **Layer-zero fields are namespaced under `parameters/librefarm`.** 1.1
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
`evidence` and `parameters/librefarm` intact, and after one fix the Datastream and
Observation documents are at full key parity with its own. The findings are pinned
in `TestValidatedAgainstFrost` so they survive without the container; the method
and what it caught are in [frost-validation.md](../docs/notes/frost-validation.md).

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

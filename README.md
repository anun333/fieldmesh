<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# librefarm

**Layer zero of a farmer-owned farm stack:** the data and device contract underneath
everything else. It covers what a reading is, what a device is, how a reading crosses an
unreliable radio link, how its quality is judged, and how a farmer gets all of it back
out.

Everything here is designed for the farm that cannot afford a good answer. That means
intermittent connectivity, battery power, cheap radios, and a log the farmer owns
outright.

> **Status: pre-release, built against a simulated farm.** There is no hardware in the
> loop yet, and no pilot farm. Commands — actually driving a pump or valve — are
> deliberately out of the first release (§6). See [What is not done](#what-is-not-done).

## Try it

Tested on Python 3.12. **One dependency**, `cbor2`, for the CBOR wire format
(`pip install -r requirements.txt`, or `python3-cbor2` on Debian and Ubuntu); everything
else is the standard library. On Windows the `zoneinfo` module also wants `tzdata`.

```sh
make test       # every test, about a minute
make demo       # a log becomes derived state becomes a SensorThings document
make serve      # a SensorThings 1.1 endpoint over two simulated days, on :8080
make drill      # seed sensor faults, score the detectors against ground truth
make siting     # score the depth check against probe moves nobody logged
make export     # a week out in open formats, then verify it replays identically
make help       # everything else
```

`make serve` is readable by **QGIS 3.36+** through its SensorThings provider, and by
Fraunhofer's `frost-sta-client`. Both were used to find defects — see
[docs/notes/qgis-validation.md](docs/notes/qgis-validation.md).

## What is here

| | |
| --- | --- |
| [docs/spec/v0.1.md](docs/spec/v0.1.md) | **The contract.** §17 records every amendment, and most were found by running code rather than by reading |
| [docs/spec/open-questions.md](docs/spec/open-questions.md) | Every open decision, with every option and its trade-offs |
| [docs/VIRTUAL_FARM.md](docs/VIRTUAL_FARM.md) | Why the build is simulator-first, and the completeness matrix that turns a spec clause with nothing exercising it into a failing test |
| [docs/LANGUAGE_PACKS.md](docs/LANGUAGE_PACKS.md) | For a university adding its farmers' language — one JSON file, no code |
| [docs/notes/](docs/notes/) | Measurements and validations behind decisions: encoding, power, FROST, QGIS, public datasets, pilot candidates |
| [sdk/](sdk/) | The contract as code: model, append-only log, projection, quality checks, wire format, gateway, SensorThings view, export, subscriptions, siting checks, CSV and MQTT adapters, language packs |
| [sim/](sim/) | **Harrow Bend**, a fictional farm on the prime meridian: soil water and heat physics, troughs, simulated nodes and radio links, fault injection, scored drills |
| [server/](server/) | A read-only SensorThings 1.1 HTTP service — the reference implementation |
| [tools/](tools/) | The measurements behind decisions, and the language-pack tool |

About 790 tests. The simulator runs a 180-day season in under eight minutes.

## A few things this does that are easy to get wrong

- **Nothing is overwritten.** Readings, calibrations, quality judgements, device
  sitings and even names are append-only. A correction is a new record. A recalibration
  supersedes, and the raw reading stays the archival truth.
- **Quality is a judgement with provenance**, not a column. It records who or what
  asserted it, under which threshold version, with the evidence. A person outranks the
  machine, and a retune never silently re-flags history.
- **The offline case is the main case.** Readings are stamped by when they were taken,
  not when they arrived. A delayed batch keeps the calibration that was in force when it
  was measured. A subscriber's cursor cannot miss an edit that syncs late.
- **The installation record is checked against physics.** A probe's daily temperature
  wave shows its depth, and a GPS-timed node's fix shows where it stands. A move nobody
  logged gets flagged — with the check's blind spots stated rather than hidden.
- **Records store codes, never translated text.** Interfaces render them in the
  reader's language, including languages that had no pack when the record was written.
- **Every export verifies.** The archive replays into an identical log, and each file
  says whether it is lossless. Losslessness is checked by decoding, not assumed.

## Licensing

Three licences, one per kind of artifact. The full reasoning is in
[LICENSING.md](LICENSING.md).

| | |
| --- | --- |
| `docs/` — the spec and all prose | CC-BY-4.0 |
| `sdk/`, `sim/`, `tools/` | Apache-2.0 — embeddable in firmware |
| `server/` | AGPL-3.0-or-later — so a hosting vendor cannot enclose a farmer-owned stack |

Some of `sdk/` derives from **campus_twin**, by the same author. See
[sdk/PROVENANCE.md](sdk/PROVENANCE.md).

## What is not done

Plainly, so nobody has to discover it:

- **No hardware.** Build step 7 — one real radio and one real device driver — waits on
  [Q6](docs/spec/open-questions.md), which link ships first.
- **No pilot farm** ([Q1](docs/spec/open-questions.md)). Seasons do not reschedule.
- **No commands.** §6 is deferred until a season of field evidence exists. The
  irrigation controller, livestock water monitor and research logger — the three
  acceptance apps — are not built.
- **Nothing above layer zero.** Layers 1–5 (rules, domain modules, decision support,
  apps, ecosystem) are described in §11 and do not exist.
- **Four rows of the completeness matrix are skipped**, each on a named decision:
  offline-edit conflicts (Q7, Q14), sharing grants (Q16, Q17), and the two that need §6.
- **The Spanish language pack is an unreviewed draft.** It needs a native-speaking
  agronomist before farmers see it.
- **Not hardened for a network.** The HTTP server is single-threaded and read-only by
  design, and has never faced the internet.

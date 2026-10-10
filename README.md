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
else is the standard library. `make test` also runs the Q5 measurement tool's tests, which
need `protobuf` — `pip install -r requirements-tools.txt` installs both. On Windows the `zoneinfo` module also wants `tzdata`.

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
| [docs/notes/](docs/notes/) | Measurements and validations behind decisions: encoding, power, FROST, QGIS, public datasets, validation sites |
| [sdk/](sdk/) | The contract as code: model, append-only log, projection, quality checks, wire format, gateway, SensorThings view, export, subscriptions, siting checks, CSV and MQTT adapters, language packs |
| [sim/](sim/) | **Harrow Bend**, a fictional farm on the prime meridian: soil water and heat physics, troughs, simulated nodes and radio links, fault injection, scored drills |
| [server/](server/) | A read-only SensorThings 1.1 HTTP service — the reference implementation |
| [tools/](tools/) | The measurements behind decisions, weather and forecast adapters, and the language-pack tool |
| [modules/rules/](modules/rules/) | **Layer 1, rules and alerts**: CEL conditions over the log, each evaluation a logged decision. First rule: a frost watch, backtested on NOAA's forecasts against McAllister Farm's station |
| [modules/advise/](modules/advise/) | **The first module above layer zero** (layer 3, decision support): for any point, what grows and when to sow it, which fruit cultivars get their chill and how often frost follows bloom, what the soil needs, bees, livestock heat, and the 2050s — in English and Spanish |

About 1,130 tests. The simulator runs a 180-day season in under eight minutes.

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
| `modules/rules/` | AGPL-3.0-or-later, as the reference server |
| `modules/advise/` | AGPL-3.0-or-later for code, the same reasoning; its data under each source's licence ([MANIFEST](modules/advise/data/MANIFEST.csv)) |

Some of `sdk/` derives from **campus_twin**, by the same author. See
[sdk/PROVENANCE.md](sdk/PROVENANCE.md).

## What is not done

Plainly, so nobody has to discover it:

- **No hardware.** Build step 7 — one real radio and one real device driver — is decided
  ([Q6](docs/spec/open-questions.md): Meshtastic first, a wired Modbus control) and waits
  on the hardware itself.
- **No pilot farm** ([Q1](docs/spec/open-questions.md)). The approach is decided and the
  letters drafted; nobody has been asked yet. Seasons do not reschedule.
- **No commands.** §6 is deferred until a season of field evidence exists. The
  irrigation controller, livestock water monitor and research logger — the three
  acceptance apps — are not built.
- **Little above layer zero.** Two modules exist: the advisor (layer 3) and rules and
  alerts (layer 1), whose one rule is a frost watch. Domain modules (2), apps (4) and the
  ecosystem (5) are described in §11 and do not; the irrigation rules in `sim/` stand in.
- **Three rows of the completeness matrix are skipped**: offline-edit conflicts (Q14 named
  the fields; the records they belong to are not built) and the two that need §6.
- **The Spanish language pack is an unreviewed draft.** It needs a native-speaking
  agronomist before farmers see it.
- **Not hardened for a network.** The HTTP server is single-threaded and read-only by
  design, and has never faced the internet.

<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# fieldmesh

**Layer zero of a farmer-owned farm stack:** the data and device contract underneath
everything else. It covers what a reading is, what a device is, how a reading crosses an
unreliable radio link, how its quality is judged, and how a farmer gets all of it back
out.

*Formerly librefarm; renamed on 2026-10-10.*

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
make serve      # a SensorThings 1.1 endpoint over two simulated days, on this machine's :8080
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
| [sdk/](sdk/) | The contract as code: model, append-only log, projection, farm records with offline edits, quality checks, wire format, gateway, SensorThings view, export, subscriptions, siting checks, CSV and MQTT adapters, language packs |
| [sim/](sim/) | **Harrow Bend**, a fictional farm on the prime meridian: soil water and heat physics, troughs, simulated nodes and radio links, fault injection, scored drills |
| [server/](server/) | A read-only SensorThings 1.1 HTTP service — the reference implementation |
| [deploy/](deploy/) | systemd units that run each module as its own sandboxed service, reaching the farm's data only through the module host's socket (§8.3, Q11) |
| [tools/](tools/) | The measurements behind decisions, weather and forecast adapters, and the language-pack tool |
| [modules/rules/](modules/rules/) | **Layer 1, rules and alerts**: CEL conditions over the log, each evaluation a logged decision. First rule: a frost watch, backtested on NOAA's forecasts against McAllister Farm's station |
| [modules/water/](modules/water/) | **Layer 2, the livestock water monitor**: empty, low, not refilling, unseen, untrusted, per trough, as advisory decisions in English and Spanish. Passes §15's acceptance test on the virtual farm, whose first run found two defects in the node's backlog handling |
| [modules/soilwater/](modules/soilwater/) | **Layer 2, the soil-moisture advisory**: each morning, per bed, water now and how much, rain coming, water soon, too wet, enough — or why it cannot say. Backtested on a recorded summer: 72% less water than a drip timer with no hour of stress |
| [modules/advise/](modules/advise/) | **The first module above layer zero** (layer 3, decision support): for any point, what grows and when to sow it, which fruit cultivars get their chill and how often frost follows bloom, what the soil needs, bees, livestock heat, and the 2050s — in English and Spanish |

About 1,200 tests. The simulator runs a 180-day season in under eight minutes.

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
- **Two phones, one record, no signal.** An edit names what its writer had already
  seen, so a later edit follows an earlier one whatever either clock said. Concurrent
  changes to a harvest's weight, a spray's rate or an animal's withdrawal keep both
  values and ask a person, and the withdrawal check reads the longer of the two meanwhile.
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
| `sdk/`, `sim/`, `tools/`, `deploy/` | Apache-2.0 — embeddable in firmware |
| `server/` | AGPL-3.0-or-later — so a hosting vendor cannot enclose a farmer-owned stack |
| `modules/rules/` | AGPL-3.0-or-later, as the reference server |
| `modules/water/`, `modules/soilwater/` | AGPL-3.0-or-later, the same |
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
- **No commands.** §6 is deferred until a season of field evidence exists. Of the three
  acceptance apps, the livestock water monitor is built (read-only, so it needs none);
  the irrigation controller waits on §6 and the research logger is not built.
- **Little above layer zero.** Four modules exist: rules and alerts (layer 1), the
  livestock water monitor and the soil-moisture advisory (layer 2), and the advisor
  (layer 3). Apps (4) and the
  ecosystem (5) are described in §11 and do not; the irrigation rules in `sim/` stand in,
  and no app writes the farm's records yet.
- **Two rows of the completeness matrix are skipped**, the two that need §6. The farm's
  records exist (land, animals, inputs, treatments, harvests, with offline conflicts), but
  no app writes them yet and nothing projects them to farmOS (Q8).
- **The Spanish language pack is an unreviewed draft.** It needs a native-speaking
  agronomist before farmers see it.
- **Hardened, but never yet faced the internet.** The HTTP server asks every request for
  a token, answers a sharing grantee from what their grant covers and nothing else,
  refuses to listen beyond the machine without TLS, and rate-limits and times out its
  clients. Nobody outside has tried to break it.

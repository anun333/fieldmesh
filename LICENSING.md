<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Licensing

**Decided 2026-10-07** ([open-questions.md](docs/spec/open-questions.md) Q2). Three
licenses, because the three kinds of artifact here have three different jobs.

| What | License | File | Why this one |
| --- | --- | --- | --- |
| The specification and all prose in `docs/` | **CC-BY-4.0** | [LICENSE-CC-BY-4.0](LICENSE-CC-BY-4.0) | A contract nobody may implement is not a contract. Anyone — including a competitor — may implement this, with attribution. |
| `sdk/`, `sim/`, `tools/` — the SDK, the wire format and the conformance suite | **Apache-2.0** | [LICENSE-APACHE-2.0](LICENSE-APACHE-2.0) | A sensor manufacturer must be able to put this in firmware without consulting a lawyer, and the explicit patent grant matters in agriculture. This is the part we most want adopted, so it carries the fewest conditions. |
| `server/` — the reference implementation | **AGPL-3.0-or-later** | [LICENSE-AGPL-3.0](LICENSE-AGPL-3.0) | The project's premise is that the farmer owns the data. A hosting vendor running this as a closed service, with the farmer's data inside it, would defeat that premise specifically. The network clause is the only license term that reaches that case. |
| `modules/rules/` — rules and alerts, layer 1 | **AGPL-3.0-or-later** | [modules/rules/LICENSE](modules/rules/LICENSE) | The reference server's reasoning: run as a service, its improvements stay open. Depends on cel-python (Apache-2.0) |
| `modules/water/` — livestock water monitor, layer 2 | **AGPL-3.0-or-later** | [modules/water/LICENSE](modules/water/LICENSE) | The same, and it is built on `modules/rules/` |
| `modules/advise/` — the advisor, a layer-3 module | **AGPL-3.0-or-later** for code; each data file its source's licence | [modules/advise/LICENSE](modules/advise/LICENSE), [data/MANIFEST.csv](modules/advise/data/MANIFEST.csv) | Decided 2026-10-09: an advisor is the piece most likely to be run as a hosted service, so the server's reasoning applies to it too. |

Every file carries an `SPDX-License-Identifier` line. The file is authoritative; this
table explains it.

## Third-party data

The advisor's data — USDA PLANTS (CC0), GloBI (CC BY 4.0), DSSAT genotype files
(BSD-3-Clause, with DSSAT's notice), and the chill-requirement tables re-keyed from three
CC BY 4.0 articles — is listed file by file, with source, licence, retrieval date and
checksum, in [modules/advise/data/MANIFEST.csv](modules/advise/data/MANIFEST.csv). A test
fails if a file changes without its line.

Test fixtures: `sim/data/mcallister-2007-spring.csv` and
`sim/data/mcallister-2013-summer.csv`, NASA POWER daily weather (CC-BY-4.0, credited in
their headers), and
`tools/fixtures/nws-gridpoint-HUN-62-57.json` and `nws-gridpoint-HUN-62-57-pop.json`,
trimmed National Weather Service forecasts (public domain, a US government work).

Figures quoted in notes from NASA POWER (CC-BY-4.0), ISMN (CC-BY-4.0) and the USDA soil
survey (public domain) are attributed where they appear. FAO's ECOCROP is **not** used:
its licence is non-commercial, and a request to FAO for permission has been drafted. Nor is CITA
Aragón's dataset of fruit-tree chill requirements (CC BY-NC-ND). The chill tables come from
the 2020 review as MDPI published it under CC BY 4.0; CITA's repository files its copy of
the same article as CC BY-NC-ND 3.0 ES, but a CC BY grant cannot be withdrawn, and the
version of record is what is cited.

## Why not one license

A single permissive license would let a vendor take the farmer-owned stack and make it
not farmer-owned. A single copyleft license would keep the SDK out of firmware, which
harms the one component whose whole purpose is to be embedded. The split is not
fence-sitting — each boundary is placed where a real failure would otherwise occur.

## How the parts combine

`server/` (AGPL-3.0-or-later) imports `sdk/` (Apache-2.0). That direction is fine:
Apache-2.0 is one-way compatible with GPLv3-family licenses, so Apache code may be
combined into an AGPL work. **The reverse is not true** — nothing in `sdk/`, `sim/` or
`tools/` may import from `server/`, or the SDK's Apache-2.0 promise is broken for
everyone who embeds it. That constraint is architectural, not merely legal: the SDK
has no business depending on a server. The same holds for modules: `modules/advise/`
(AGPL) imports layer zero, and nothing in layer zero imports it —
`tools/test_layering.py` checks.

`-or-later` on the AGPL is deliberate. farmOS sits on Drupal, which is GPLv2-or-later;
the "or later" on both sides is what keeps a future combination possible at v3. Under
v0.1 §7.1 the question is moot today, because nothing links — the integration speaks
HTTP.

## Contributions

Decided **before** the first outside contribution, which was the point: relicensing
afterwards needs every contributor's agreement. There is no CLA. Contributions are
taken under the license of the directory they land in, and a contributor keeps their
copyright.

## Dependencies

Four third-party libraries, all installed rather than vendored:

| library | licence | used by | file |
| --- | --- | --- | --- |
| `cbor2` | MIT | `sdk/wire.py` — the CBOR wire format (Q5) | `requirements.txt` |
| `cryptography` | Apache-2.0 OR BSD-3-Clause | `sdk/erasure.py` only — sealing personal text so it can be erased by destroying a key (Q17) | `requirements.txt` |
| `protobuf` | BSD-3-Clause | `tools/q5_encoding.py` only — the measurement that sized Protocol Buffers against CBOR | `requirements-tools.txt` |
| `markdown-it-py` | MIT | `tools/pages.py` only — renders the project site | `requirements-tools.txt` |

All combine with Apache-2.0 and AGPL-3.0 without condition beyond keeping their notices.
Nothing in `sdk/`, `sim/` or `server/` needs protobuf or markdown-it-py.

## Inherited code

Some files in `sdk/` derive from `campus_twin`, by the same author, dual-licensed
`Apache-2.0 OR GPL-3.0-or-later` at its origin. They exercise the Apache-2.0 option.
See [sdk/PROVENANCE.md](sdk/PROVENANCE.md) for which files and what changed, and
[NOTICE](NOTICE).

<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Licensing

**Decided 2026-10-07** ([open-questions.md](docs/spec/open-questions.md) Q2). Three
licenses, because the three kinds of artifact here have three different jobs.

| What | License | File | Why this one |
| --- | --- | --- | --- |
| The specification and all prose in `docs/` | **CC-BY-4.0** | [LICENSE-CC-BY-4.0](LICENSE-CC-BY-4.0) | A contract nobody may implement is not a contract. Anyone — including a competitor — may implement this, with attribution. |
| `sdk/`, `sim/`, `tools/` — the SDK, the wire format and the conformance suite | **Apache-2.0** | [LICENSE-APACHE-2.0](LICENSE-APACHE-2.0) | A sensor manufacturer must be able to put this in firmware without consulting a lawyer, and the explicit patent grant matters in agriculture. This is the part we most want adopted, so it carries the fewest conditions. |
| `server/` — the reference implementation | **AGPL-3.0-or-later** | [LICENSE-AGPL-3.0](LICENSE-AGPL-3.0) | The project's premise is that the farmer owns the data. A hosting vendor running this as a closed service, with the farmer's data inside it, would defeat that premise specifically. The network clause is the only license term that reaches that case. |

Every file carries an `SPDX-License-Identifier` line. The file is authoritative; this
table explains it.

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
has no business depending on a server.

`-or-later` on the AGPL is deliberate. farmOS sits on Drupal, which is GPLv2-or-later;
the "or later" on both sides is what keeps a future combination possible at v3. Under
v0.1 §7.1 the question is moot today, because nothing links — the integration speaks
HTTP.

## Contributions

Decided **before** the first outside contribution, which was the point: relicensing
afterwards needs every contributor's agreement. There is no CLA. Contributions are
taken under the license of the directory they land in, and a contributor keeps their
copyright.

## Inherited code

Some files in `sdk/` derive from `campus_twin`, by the same author, dual-licensed
`Apache-2.0 OR GPL-3.0-or-later` at its origin. They exercise the Apache-2.0 option.
See [sdk/PROVENANCE.md](sdk/PROVENANCE.md) for which files and what changed, and
[NOTICE](NOTICE).

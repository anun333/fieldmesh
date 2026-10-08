<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `server/` — the reference implementation

A read-only SensorThings 1.1 HTTP service over derived state ([spec §10](../docs/spec/v0.1.md)).
**AGPL-3.0-or-later** — see [LICENSING.md](../LICENSING.md) for why this directory
carries a different license from `sdk/`.

```sh
make serve            # two simulated days, on :8080
DAYS=14 make serve
curl -s 'http://localhost:8080/v1.1/Datastreams?$top=2'
```

| file | what it is |
| --- | --- |
| [odata.py](odata.py) | the `$filter` parser and evaluator, plus the other query options. No HTTP. |
| [app.py](app.py) | routing and query application. Takes a method, a path and a query string; returns a status, headers and a body. No socket. |
| [serve.py](serve.py) | the socket. Standard library only. If this file grows logic, the logic belongs in one of the two above. |

## Three decisions worth knowing before reading the code

**An unsupported query option is an error, never silence.** A client that sends
`$filter=result gt 0.4` and receives every reading has been told something false — it
cannot distinguish "no filtering happened" from "nothing matched". Anything the
evaluator cannot handle is a 400 (malformed) or a 501 (valid OData we do not implement),
with the offending text quoted back in the error's `target`. `$top` beyond the cap is
refused rather than clamped, for the same reason.

**It is read-only on purpose, not pending.** §7.1 makes the append-only log the write
path, so a POST here would write to a projection and be discarded the next time state
was rebuilt. Mutating methods are 405 with `Allow: GET, HEAD` — the honest answer rather
than 501, which would imply it is coming.

**Every link it emits must resolve.** `test_app.py::TestEverySelfLinkResolves` walks
every entity set, collects every `@iot.selfLink` and `@iot.navigationLink`, and fetches
each one. A service that advertises a link it cannot answer is worse than one that
advertises none, because the client only finds out after following it. That test exists
because a real client found two such links; see
[notes/qgis-validation.md](../docs/notes/qgis-validation.md).

## What it does not do

`$metadata` (the CSDL document), `$apply`, lambda operators, geospatial filter
functions, arithmetic in `$filter`, MQTT, Locations and HistoricalLocations, and
anything that writes. Each refuses by name rather than by silence.

Not hardened for exposure to a network, and single-threaded by choice: a read-only
projection served to one GIS client at a time is the use case, and concurrency would
mean deciding what happens when state is rebuilt mid-request.

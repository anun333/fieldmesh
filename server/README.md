<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `server/` — the reference implementation

A read-only SensorThings 1.1 HTTP service over derived state ([spec §10](../docs/spec/v0.1.md)).
**AGPL-3.0-or-later** — see [LICENSING.md](../LICENSING.md) for why this directory
carries a different license from `sdk/`.

```sh
make serve            # two simulated days, on this machine's :8080, no token needed
DAYS=14 make serve
curl -s 'http://localhost:8080/v1.1/Datastreams?$top=2'

# A real farm's log, with tokens:
python3 server/access.py issue --log farm.jsonl --role viewer
python3 server/access.py issue --log farm.jsonl --grantee "state university soil lab"
python3 server/serve.py --log farm.jsonl                       # 127.0.0.1, behind a proxy
python3 server/serve.py --log farm.jsonl --host 0.0.0.0 --tls-cert c.pem --tls-key k.pem
curl -s -H "Authorization: Bearer $TOKEN" 'https://farm.example:8080/v1.1/Datastreams'
```

| file | what it is |
| --- | --- |
| [odata.py](odata.py) | the `$filter` parser and evaluator, plus the other query options. No HTTP. |
| [app.py](app.py) | routing and query application. Takes a method, a path and a query string; returns a status, headers and a body. No socket. |
| [access.py](access.py) | who may ask: tokens for farm users and grantees, issued and revoked as log records (only their hashes), and a rate limiter |
| [serve.py](serve.py) | the socket, and the decisions a socket brings: authentication, TLS, a thread per connection with a timeout, a cap on concurrent work, rate limits, an access log. Standard library only |

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

`$apply`, lambda operators, geospatial filter functions, arithmetic in `$filter`, `$ref`
association links, MQTT, and anything that writes. Each refuses by name rather than by
silence, and `serverSettings.conformance` at the service root claims only the nine
data-model requirements actually met. `$metadata` answers 501; it is an OData document
that SensorThings 1.1 does not require. HistoricalLocations is served and always empty:
Things here do not move, and devices that do are §4.1 Installations, which 1.1 has no
entity for.

## Who may ask, and what a client can do to the others

**Every request carries a bearer token** standing for a farm user (any §8.2 role reads
everything; the service writes nothing) or a sharing grantee (§7.6). A grantee is answered
from `sharing.view` — the granted series, the readings their grant covers, the quality
verdicts about those, and the names behind them — so no path, by id, by navigation link or
by `$filter`, reaches anything else; what is not shared is a 404, which does not say that it
exists. A revoked grant leaves the grantee's token working and their view empty; a revoked
or expired token is a 401. Tokens are log records holding only a hash, and the server
follows the log file, so one issued or revoked from another process counts within seconds.
`--open` serves without tokens, for the simulator and a GIS client on the same machine, and
only on loopback.

**Nothing leaves the machine in the clear**: binding anything but loopback needs a
certificate (TLS 1.2 or later), and behind a reverse proxy it binds loopback.

**One client cannot stall the others.** A thread per connection with a timeout, so a client
that never finishes its request is dropped after twenty seconds while sixteen others are
answered; TLS negotiated in that thread, not the accept loop; at most sixteen requests
worked at once, the rest told 503 with `Retry-After`; and each principal held to ten
requests a second with bursts of forty, then 429. Requests read the state under the lock
whatever folds new records into it holds, so nobody sees a half-folded state, and each
request carries its own language and view, so two at once never cross.

Every answer says `nosniff`, `no-store`, `no-referrer`, a deny-all content policy, and
`Server: fieldmesh/0` without the Python version. The access log is one line per request —
address, who, method, path, status, size — and never a token.

[deploy/systemd/fieldmesh-server.service](../deploy/systemd/fieldmesh-server.service) runs it
sandboxed. It has not faced the internet yet; tested on loopback with real sockets
([test_serve.py](test_serve.py)), not by anyone trying to break it.

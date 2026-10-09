<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Validated against FROST-Server

Run 2026-10-07 against `fraunhoferiosb/frost-server:latest` with
`postgis/postgis:16-3.4`. Companion to [sdk/sensorthings.py](../../sdk/sensorthings.py).

The completeness matrix in [VIRTUAL_FARM.md](../VIRTUAL_FARM.md) had this row as a
claim: a serializer exists, but "existing tools work on day one" is untested until
a real implementation has accepted its documents. FROST-Server is the right oracle
— it is the most widely deployed STA server, from the same institute as the 2.0
editor, so what it accepts is what the ecosystem accepts in practice.

## Method

Stand FROST up, deep-insert a Thing carrying a Datastream, ObservedProperty,
Sensor, Observation and FeatureOfInterest shaped exactly as the adapter emits
them, read them back, and diff key-by-key against the adapter's own output for
the same logical entity. FROST assigns its own ids and selfLinks, so those are
excluded from the diff; everything else is compared.

## What held

**The deep insert returned `201 Created`.** The document shapes are valid 1.1, not
merely plausible.

**`resultQuality` survived as a list of arbitrary objects**, nested `evidence`
included. §3.3's flag *set* therefore maps natively onto 1.1's `DQ_Element` with
multiplicity zero-to-many, exactly as [sensorthings-2.0.md](sensorthings-2.0.md)
predicted — and it is the capability the 2.0 draft drops, which is the concrete
argument for raising Q18.

**`parameters/librefarm` survived intact.** The namespacing decision — layer-zero
fields nested rather than posing as 1.1's "environmental conditions during
measurement" — costs nothing in the reference implementation.

**`resultTime: null` on an Observation was accepted** and returned as null, so the
honest encoding of "layer zero does not record when the result was generated" is
legal rather than a workaround.

`phenomenonTime` as an instant with `Z`, `unitOfMeasurement` as
`{name, symbol, definition}` with a UCUM definition, and a Datastream
`properties` object carrying `kind`, `derived_from`, `expected_interval_s`,
`thresholds` and `health` were all accepted and returned verbatim.

After the two fixes below, the Datastream and Observation documents are at **full
key parity** with FROST's.

## What the oracle caught

**`resultTime` on a Datastream.** 1.1 Table 10 makes it zero-to-one. The adapter
emitted it as `null`; FROST omits it. A bare null for an optional field layer zero
has nothing to say about is noise, so the adapter now omits it. Observation's
`resultTime` is "One (mandatory)" and nullable, so that one stays null — the two
fields look alike and are not.

## A defensible divergence, now a parameter

**`@iot.count` on an entity set.** FROST omits it unless `$count=true` is asked
for. 1.1's own Example 11 shows it in the response to a plain entity-set request
with no query options. Both read the spec reasonably, so this is not a bug in
either: `collection(..., count=...)` makes it switchable, defaults to including it
per Example 11, and an HTTP layer passes `$count` through.

## A finding about ids, not a defect

FROST with default configuration **rejects a client-supplied string id**:

```
400 Cannot deserialize value of type java.lang.Long from String "a-uuid-like-string"
```

Its ids are `Long`. §1 requires UUIDv7, and 1.1 does not constrain the id type, so
the adapter is within the standard; FROST is configurable in this respect
(`persistence_idGenerationMode` and friends). The practical consequence is worth
stating: **FROST cannot be used to round-trip our ids without reconfiguration**,
so it serves as an oracle for *document shape*, not as a store for layer-zero
data. Nothing in the spec needs to change.

## Since done

What was outstanding here — a GIS client reading these documents, which needed the HTTP
layer with `$filter`, `$expand`, `$top` and paging — has been done: QGIS 3.44 and
Fraunhofer's client read the service and found five defects no internal test could reach
([qgis-validation.md](qgis-validation.md)).

## Three more questions put to the oracle, 2026-10-07

Asked while validating the HTTP layer in [server/](../../server/) against two real
clients — see [qgis-validation.md](qgis-validation.md) for the full account.

| Question | FROST's answer | What it settled |
| --- | --- | --- |
| Does `$top=2` suppress `@iot.nextLink`? | **No.** Two rows *plus* `?$top=2&$skip=2`. With `$count=true`, the count is the unfiltered total and the nextLink carries `$count` forward | Our paging matches the reference implementation exactly. A change to suppress the nextLink on an explicit `$top` was drafted on a reading of OData and **not made**, because the oracle outranks the reading |
| Is `unitOfMeasurement` required when `observationType` is `OM_CountObservation`? | **Yes.** With a unit: 201. Without: **400** | Our count-with-a-unit document was a semantic defect, not a protocol violation — and a raw datastream declaring a null unit could not be mirrored into FROST, which constrains [Q21](../spec/open-questions.md) |
| Can a Thing be deep-inserted with Datastreams and Observations and no Location? | **No.** `No FeatureOfInterest provided, and none can be generated.` | FROST generates features of interest from Thing Locations; layer zero derives them from the datastream's declared feature (§3.1). A different and deliberate choice, but anyone mirroring into FROST will meet it |

## Reproducing

```sh
docker network create frostnet
docker run -d --name frost-db --network frostnet \
  -e POSTGRES_DB=sensorthings -e POSTGRES_USER=sensorthings \
  -e POSTGRES_PASSWORD=ChangeMe postgis/postgis:16-3.4
docker run -d --name frost --network frostnet -p 8080:8080 \
  -e persistence_db_driver=org.postgresql.Driver \
  -e persistence_db_url=jdbc:postgresql://frost-db:5432/sensorthings \
  -e persistence_db_username=sensorthings -e persistence_db_password=ChangeMe \
  -e persistence_autoUpdateDatabase=true \
  -e serviceRootUrl=http://localhost:8080/FROST-Server \
  fraunhoferiosb/frost-server:latest
curl -s http://localhost:8080/FROST-Server/v1.1/
```

The findings are pinned as tests in `sdk/test_sensorthings.py`
(`TestValidatedAgainstFrost`), so they survive without the container.

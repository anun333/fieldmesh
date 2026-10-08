<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Two real clients, pointed at the HTTP service

**2026-10-07.** [spec §10](../spec/v0.1.md), [VIRTUAL_FARM.md](../VIRTUAL_FARM.md) step 7's
cheap half. The HTTP layer in [server/](../../server/) was written, tested against 69 of
its own tests, and then handed to two clients nobody here wrote:

* **QGIS 3.44.15-Solothurn** (`qgis/qgis:ltr` in Docker, headless, `QT_QPA_PLATFORM=offscreen`)
  and its native SensorThings provider. Ubuntu 24.04 ships QGIS 3.34, which predates the
  provider, so the distribution package cannot be used for this.
* **`frost-sta-client` 1.1.53**, the Python client from Fraunhofer IOSB — the same group
  that writes FROST-Server, which this project already uses as a conformance oracle.

Both read the service. Between them they found **five defects**, four of them ours, and
one of our own tests turned out to be asserting the wrong thing. None of these was
reachable from inside: every one needed a consumer with its own opinions about what a
SensorThings document means.

## What worked immediately

QGIS loaded six entity sets from a simulated day of Harrow Bend:

| entity | features |
| --- | --- |
| Thing | 9 |
| Datastream | 56 |
| Observation | 5450 |
| Sensor | 28 |
| ObservedProperty | 6 |
| FeatureOfInterest | 10 |

Timestamps parsed into `QDateTime` without coaxing, `resultQuality` survived as a field,
the labels from `harrow_bend.labels()` showed as layer names, and paging worked — the
Fraunhofer client walked the whole collection by following `@iot.nextLink` on its own.

## The five findings

### 1. Every QGIS layer had no geometry

`geometryType()` came back `NullGeometry` for all of them, so the farm loaded as six
attribute tables and nothing could go on a map. §7.6 names a GIS client as the
acceptance test for the export story, and it was failing it silently.

Two causes, which is why it took a real client to see:

* **`FeatureOfInterest.feature` was `null` for every feature.** The serialiser already
  read geometry from the label side table; nothing ever put any there.
* **The QGIS provider needs the geometry type in its data-source URI.** With
  `url='...' entity='FeatureOfInterest'` alone it builds a geometryless layer; with
  `type=Point` added it builds a point layer. So even after the server was fixed, the
  first reading was still "no geometry" until the URI was right.

Fixed by giving Harrow Bend's features a layout — a row of six beds about 50 m long, with
the paddock, plot and hoop house offset — delivered through the same side table the names
use. **Geometry is deliberately not a log record**: a real farm's field boundaries are the
material [VIRTUAL_FARM.md](../VIRTUAL_FARM.md) keeps in a gitignored `.site/` directory,
and §3 has no record type for them. Harrow Bend is fictional and sits on the prime
meridian, so its geometry can live in the repository.

After the fix: **10 of 10 features with geometry**, layer extent
`-0.00060,-0.00040 : 0.00060,0.00030`.

### 2. Every observed property had a blank name

QGIS's legend showed six empty strings. The name fell back to "everything after the last
`/`", and the [Q4 vocabulary decision](../spec/open-questions.md) had just given every
URI a **trailing slash** — which both vocabulary servers want, because the slashless form
redirects and a redirect is a different identifier to a dumb client. Everything after the
last slash of `.../air_temperature/` is the empty string.

A defect introduced by a correct decision, invisible to every test we had, and the first
thing a human looking at a legend would notice. `humanise_term` now strips the trailing
slash and renders `volume_fraction_of_condensed_water_in_soil` as
"volume fraction of condensed water in soil" and `batteryVoltage` as "battery voltage" —
while leaving `pH` as `pH` rather than `p h`, which the first attempt got wrong and which
soil pH will certainly exercise.

### 3. The service emitted self links it answered 404 to

An observed property's identity **is** its vocabulary URI (§3.4), so its self link read
`ObservedProperties('http://vocab.nerc.ac.uk/standard_name/air_temperature/')`. The
unencoded slashes split the path into the wrong segments and our own router returned
`404 no such entity set: ObservedProperties('http:`.

The id is now percent-encoded, and the router decodes it **after** splitting the path,
not before — the ordering is the whole fix. `ObservedProperties` is also now exempt from
UUID parsing, since it is the one entity set whose key is not a UUID.

A second instance of the same class: `Thing` advertised a `Locations@iot.navigationLink`,
and we serve no Locations at all. Removed rather than implemented — geometry here belongs
to a feature of interest, not to the Thing that observes it, and 1.1 makes
`Thing.Locations` 0..\*.

Generalised into `test_app.py::TestEverySelfLinkResolves`, which walks every entity set,
collects every self and navigation link, and fetches each one. **A link you cannot answer
is worse than one you never offered**, because the client only learns after following it.

### 4. `ObservedProperty` had no `Datastreams` link at all

1.1 Table 9 gives it one. It was simply missing, and a client cannot work around it:
there is no other way to ask "which series measure this property?" than to list every
datastream and filter client-side. Added.

### 5. A raw series was typed as a *count*, with a unit

QGIS showed `observationType = OM_CountObservation` on a datastream whose
`unitOfMeasurement` was `cm3/cm3`. A count has no unit, so one document asserted two
incompatible things, and a consumer honouring `observationType` would be entitled to
refuse to average or interpolate a continuous measurement.

The cause was typing the datastream from the Python type of the first result it could
find — and a raw soil-moisture series carries scaled integers, `280` for 0.280. The type
now follows the **declaration**: a declared unit means a measured quantity, which is what
a unit is for. Only an undeclared unit lets the values decide, and then they decide
something real.

Two of our own tests asserted the old behaviour and were rewritten, because the behaviour
they pinned was wrong. The same scan was also walking every observation in the log for
every datastream on every `/Datastreams` request — the quadratic shape §7.2 forbids,
hiding in a serialiser rather than in the projection. It uses the index now.

**This fix only moved the real question**, which is what unit a raw datastream should
declare when it carries scaled integers. That is a data-model decision affecting the
canonical farm, so it is recorded as **Q21** rather than quietly chosen.

## What FROST settled, and one thing it did not

With the oracle running alongside, three behaviours were checked against it rather than
against a reading of the specification.

**`$top` and `@iot.nextLink` — we match FROST exactly.** FROST returns `$top=2` as two
rows *plus* a nextLink with `$skip=2`; so do we. This mattered because the Fraunhofer
client follows nextLink automatically, so asking for 3 rows yields the whole collection —
which looks exactly like `$top` being ignored. I had drafted a change to suppress the
nextLink whenever `$top` was explicit, on a reading of OData where `$top` bounds the
result set rather than the page. **FROST says otherwise, and FROST is the oracle this
project chose,** so the change was not made. Recorded because it is precisely the sort of
conformant behaviour a later reader would "fix" into non-conformance.

**FROST requires `unitOfMeasurement` even for a count.** Posting a Datastream with
`OM_CountObservation` and a unit: 201. The same without a unit: **400**. So our
count-with-a-unit document was never a protocol violation — it was a semantic one. This
also constrains Q21: a raw datastream declaring a null unit could not be mirrored into
the reference implementation.

**FROST requires a FeatureOfInterest, or a Location to generate one from.** A deep insert
of a Thing with Datastreams and Observations and no Location is rejected with
`No FeatureOfInterest provided, and none can be generated.` Our model derives features of
interest from the datastream's declared feature instead, which is a different and
deliberate choice (§3.1) — noted because anyone mirroring layer zero into FROST will meet
it.

## Reproducing

```sh
make serve                      # or: cd server && python3 serve.py --days 1 --port 8099
docker pull qgis/qgis:ltr
docker run --rm --network host -e QT_QPA_PLATFORM=offscreen \
  -v "$PWD/probe.py:/probe.py:ro" qgis/qgis:ltr python3 /probe.py
```

where `probe.py` builds layers with
`QgsVectorLayer("url='http://127.0.0.1:8099/v1.1' entity='FeatureOfInterest' type=Point", "foi", "sensorthings")`.
`QT_QPA_PLATFORM=offscreen` is required; without it the container cannot initialise Qt.

For the Fraunhofer client, `pip install frost-sta-client` into a virtual environment and
point `SensorThingsService` at the same base URL.

Every finding above is pinned as a test, so none of it depends on the containers:
`sdk/test_sensorthings.py` (`TestVocabularyUriPresentation`, `TestFeatureGeometry`,
`TestThingHasNoLocationsLink`, `TestUnitsAndTypes`), `server/test_app.py`
(`TestEverySelfLinkResolves`, `TestUriKeyedObservedProperties`), and
`sim/test_harrow_bend.py` (`TestLabelsAndGeometry`).

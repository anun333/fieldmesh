#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Observed-property URIs and unit codes (spec v0.1 §3.4, open-questions Q4).

**Decided 2026-10-07.** Units are UCUM. Observed properties are layered by what they
are for, rather than drawn from one vocabulary that would have to cover everything:

* **CF Standard Names** for physical measurands, as the de facto vocabulary for
  environmental measurement. Served as resolvable URIs by the NERC Vocabulary Server,
  which is what makes §3.4's "a URI, never free text" rule mean something.
* **ODM2 / CUAHSI** for the sensor-plumbing and water terms CF does not carry —
  battery voltage, signal strength — which is exactly the gap Q4 predicted.
* **AGROVOC** for the records side (crops, treatments, practices). Nothing here uses
  it yet; it belongs to layer 2, not to a datastream declaration.
* **A local term** only for a genuine gap in all of the above, declared in `LOCAL`
  below with the reason, so the gaps are countable and can be published upstream.

Every URI in this module was fetched and returned 200 on 2026-10-07. That is the
standard a vocabulary decision has to meet: a term nobody can resolve is free text
with extra syntax.

## The error this module exists to prevent

The placeholders these replaced said `cf/soil_moisture_content`. **`soil_moisture_content`
is not a CF standard name** — it does not appear in the table at any version. Worse, the
nearest real names are mass-based (`mass_content_of_water_in_soil`, kg m-2), so a reader
who assumed the obvious would get a measurand in the wrong dimension from a term that
looks authoritative. The volumetric quantity our probes actually report is
`volume_fraction_of_condensed_water_in_soil`, canonical units `1`, which is what
`cm3/cm3` is.

Checked against CF standard name table **version 95, 2026-09-16**.
"""
from __future__ import annotations

#: NERC Vocabulary Server, which serves the CF standard names as resolvable URIs.
CF = "http://vocab.nerc.ac.uk/standard_name/"
#: ODM2 controlled vocabularies (the CUAHSI lineage).
ODM2 = "http://vocabulary.odm2.org/variablename/"

#: Local terms. Does not resolve yet — the repository is private — and the durable
#: namespace is open as Q4c. One constant, so the move is a one-line change rather
#: than a migration.
LOCAL = "https://anun333.github.io/librefarm/vocab/"


# ------------------------------------------------------------------ measurands

#: Volumetric soil water content. CF canonical units `1`; we report `cm3/cm3`, which
#: is the same dimensionless ratio written so a human can see what was divided.
SOIL_WATER = CF + "volume_fraction_of_condensed_water_in_soil/"

#: Air temperature. CF canonical units are K; §3.4 does not require canonical units,
#: only a parsable UCUM code, and a farm reads `Cel`.
AIR_TEMPERATURE = CF + "air_temperature/"

#: Relative humidity. CF canonical units `1`; we report `%`.
RELATIVE_HUMIDITY = CF + "relative_humidity/"

#: Soil temperature, for when the probes report it. CF, units K, we use `Cel`.
SOIL_TEMPERATURE = CF + "soil_temperature/"

#: Field capacity and wilting point, as CF names rather than as bare numbers in a
#: config file. Both are volume fractions, so they are directly comparable with
#: SOIL_WATER — which is the property that makes a stress calculation checkable.
FIELD_CAPACITY = CF + "volume_fraction_of_condensed_water_in_soil_at_field_capacity/"
WILTING_POINT = CF + "volume_fraction_of_condensed_water_in_soil_at_wilting_point/"


#: A node's own GNSS fix. CF names, canonical units degree_north and degree_east;
#: UCUM writes both as `deg`. A node that keeps GPS time already has this fix and
#: used to discard it.
LATITUDE = CF + "latitude/"
LONGITUDE = CF + "longitude/"


# ------------------------------------------------- device health (§4.3), via ODM2

#: Battery voltage. Not a CF name and never will be: CF covers the environment, not
#: the instrument. ODM2 carries it because ODM2 was built for sensor deployments.
BATTERY_VOLTAGE = ODM2 + "batteryVoltage/"

#: Received signal strength. **The spelling is ODM2's, typo and all** — their term is
#: `receivedSignalStrenghtIndication`. It is their identifier, so it is not ours to
#: correct: a URI we "fixed" would resolve to nothing. Reported upstream is the right
#: response; silently diverging is not.
RSSI = ODM2 + "receivedSignalStrenghtIndication/"


# ------------------------------------------------------------------ local terms

#: Fraction of a vessel's capacity currently filled, 0..1.
#:
#: A genuine gap, and worth being precise about why, because the temptation is to
#: reach for ODM2 `waterLevel` and move on. `waterLevel` is a **height** — a length,
#: in metres. What a float-regulated stock trough usefully reports is how full it is,
#: which is dimensionless and bounded, and whose thresholds (§4.2: below 0.10 means
#: the stock cannot drink) are fractions. Declaring a fraction under a term defined as
#: a length is the same class of error as the `soil_moisture_content` placeholder:
#: a unit lie wearing a credible URI. CF has no vessel-fill term either.
#:
#: To be published upstream to ODM2 rather than kept private — that is the price of
#: adding a local term.
VESSEL_FILL_FRACTION = LOCAL + "vessel_fill_fraction/"


#: Every term this project declares, by URI, with the UCUM unit it is normally
#: reported in and where the term comes from. `make vocab` prints it; the point is
#: that the count of local terms is visible and therefore hard to grow quietly.
TERMS: dict[str, tuple[str, str]] = {
    SOIL_WATER: ("cm3/cm3", "CF"),
    AIR_TEMPERATURE: ("Cel", "CF"),
    RELATIVE_HUMIDITY: ("%", "CF"),
    SOIL_TEMPERATURE: ("Cel", "CF"),
    FIELD_CAPACITY: ("cm3/cm3", "CF"),
    WILTING_POINT: ("cm3/cm3", "CF"),
    LATITUDE: ("deg", "CF"),
    LONGITUDE: ("deg", "CF"),
    BATTERY_VOLTAGE: ("V", "ODM2"),
    RSSI: ("dB[mW]", "ODM2"),
    VESSEL_FILL_FRACTION: ("1", "local"),
}


def source_of(uri: str) -> str:
    """Which vocabulary a URI came from, or `"unknown"`.

    Deliberately prefix-based rather than a lookup in `TERMS`: the question "is this
    one of ours?" has to be answerable for a URI we have never seen, because that is
    the case where the answer matters.
    """
    for prefix, name in ((CF, "CF"), (ODM2, "ODM2"), (LOCAL, "local")):
        if uri.startswith(prefix):
            return name
    return "unknown"


def local_terms() -> list[str]:
    """The local terms, which are the ones owing a trip upstream."""
    return sorted(u for u in TERMS if source_of(u) == "local")


if __name__ == "__main__":
    width = max(len(u) for u in TERMS)
    for uri, (unit, src) in sorted(TERMS.items(), key=lambda kv: (kv[1][1], kv[0])):
        print(f"{src:<6} {uri:<{width}}  {unit}")
    print(f"\n{len(TERMS)} terms, {len(local_terms())} local "
          f"({len(local_terms()) / len(TERMS):.0%} owing a trip upstream)")

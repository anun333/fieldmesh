#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Builders for contract records, with sane defaults.

Not a test module (the name is deliberate — `unittest discover` only collects
`test_*`). These keep the tests about the rule under test instead of about
constructing five UUIDs, and they are the seed of what the virtual farm in
docs/VIRTUAL_FARM.md will need.

Soil moisture in cm3/cm3 is the running example because it is the measurand the
irrigation controller and the research logger both depend on.
"""
from __future__ import annotations

import datetime as _dt

import vocab as V
from ids import uuid7
from model import (Assertor, Calibration, ClockQuality, Datastream,
                   DatastreamKind, Observation, QualityAssertion, Threshold,
                   derive_usable)

UTC = _dt.timezone.utc

#: The CF standard name for volumetric water content. See vocab.py for why the
#: obvious-looking `soil_moisture_content` is not it.
SOIL_MOISTURE = V.SOIL_WATER
T0 = _dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def at(minutes: float = 0, *, base: _dt.datetime = T0) -> _dt.datetime:
    return base + _dt.timedelta(minutes=minutes)


def raw_datastream(*, thing=None, sensor=None, feature=None,
                   expected_interval=300.0, max_latency=3600.0,
                   unit: str | None = "cm3/cm3",
                   observed_property: str = SOIL_MOISTURE, **kw) -> Datastream:
    return Datastream(
        id=uuid7(),
        thing=thing or uuid7(),
        sensor=sensor or uuid7(),
        observed_property=observed_property,
        feature=feature or uuid7(),
        kind=DatastreamKind.RAW,
        unit=unit,
        expected_interval=expected_interval,
        max_latency=max_latency,
        **kw,
    )


def derived_datastream(raw: Datastream, **kw) -> Datastream:
    return Datastream(
        id=uuid7(),
        thing=raw.thing,
        sensor=raw.sensor,
        observed_property=raw.observed_property,
        feature=raw.feature,
        kind=DatastreamKind.DERIVED,
        derived_from=raw.id,
        unit=raw.unit,
        expected_interval=raw.expected_interval,
        max_latency=raw.max_latency,
        **kw,
    )


def observation(datastream: Datastream, *, result=0.23, measured_at=None,
                received_at=None, uncertainty=1.0,
                clock_quality=ClockQuality.GPS, node="!bed01", boot=1, seq=0,
                calibration=None, supersedes=None, **kw) -> Observation:
    measured = measured_at if measured_at is not None else T0
    return Observation(
        id=uuid7(),
        datastream=datastream.id,
        measured_at=measured,
        measured_at_uncertainty=uncertainty,
        received_at=received_at if received_at is not None else measured,
        result=result,
        clock_quality=clock_quality,
        node=node,
        boot=boot,
        seq=seq,
        calibration=calibration,
        supersedes=supersedes,
        **kw,
    )


def calibration(sensor, *, valid_from=None, valid_to=None, a=1.0, b=0.0,
                method="two-point") -> Calibration:
    return Calibration(
        id=uuid7(),
        sensor=sensor,
        method=method,
        valid_from=valid_from if valid_from is not None else at(-60 * 24 * 30),
        valid_to=valid_to,
        coefficients={"a": a, "b": b},
    )


def threshold(datastream: Datastream, **values) -> Threshold:
    return Threshold(id=uuid7(), datastream=datastream.id, values=values,
                     created_at=T0)


def assertion(observation_id, *, flags=(), check="flatline", check_version="1",
              threshold_version=None, asserted_at=None,
              assertor=Assertor.FOUNDATION, usable=None, supersedes=None,
              **kw) -> QualityAssertion:
    flags = frozenset(flags)
    return QualityAssertion(
        id=uuid7(),
        observation=observation_id,
        flags=flags,
        usable=usable if usable is not None else derive_usable(flags),
        check=check,
        check_version=check_version,
        threshold_version=threshold_version,
        asserted_at=asserted_at if asserted_at is not None else T0,
        assertor=assertor,
        supersedes=supersedes,
        **kw,
    )

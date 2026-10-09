#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Weather forecasts as input data (spec v0.1 §3.1 kind `forecast`, §3.2 `issued_at`; Q26).

A forecast is not a measurement, and filing it as one would break two promises at once.
It has **two times**: the hour it is valid for, and the run that produced it — O&M's
`phenomenonTime` and `resultTime`, the case that pair exists for. And it is **issued
again and again**: every run of the model predicts tomorrow afternoon anew, so a log
that keeps the runs holds several values for one valid time, which §3.2 forbids of a
measured series.

So a forecast datastream is its own kind, and each observation on it carries
`issued_at`. For each valid time the **live** value is the latest issue — no
`supersedes` pointer is written, because a newer run does not correct an older one, it
replaces it as the best guess, and a run that arrives late, after a newer one, must not
take over. Every run stays in the log, so a forecast can later be scored against what
the farm's own sensors measured — which is the only way to know how far to trust it here.

    report = ingest(log, state, datastream_id, issued_at, [(valid_at, value), ...],
                    uncertainty_s=1800, provenance={"source": "api.weather.gov", ...})

Re-ingesting a run is idempotent: a `(valid time, issued_at)` already in the log is
skipped and counted. Source adapters live in tools/forecast_sources.py; this module
knows nothing about any provider.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from uuid import UUID

import project as P
from ids import uuid7
from model import ClockQuality, DatastreamKind, Observation

UTC = _dt.timezone.utc


class ForecastError(ValueError):
    pass


@dataclass
class ForecastReport:
    written: int = 0
    already_present: int = 0
    #: Written, but an issue newer than this one already covers the hour, so it is
    #: history from the moment it lands — a run that arrived late.
    behind_newer: int = 0


def ingest(log, state: P.State, datastream_id: UUID, issued_at: _dt.datetime,
           values, *, uncertainty_s: float, received_at: _dt.datetime | None = None,
           clock_quality: ClockQuality = ClockQuality.NETWORK,
           provenance: dict | None = None) -> ForecastReport:
    """Append one forecast run's values to `log` and fold them into `state`."""
    ds = state.datastreams.get(datastream_id)
    if ds is None:
        raise ForecastError(f"no datastream {datastream_id} is declared")
    if ds.kind is not DatastreamKind.FORECAST:
        raise ForecastError(
            f"datastream {datastream_id} is {ds.kind.value}; a forecast lands on a "
            f"datastream of kind forecast, never among measurements (§3.1; Q26)")
    if issued_at.tzinfo is None or issued_at.utcoffset() != _dt.timedelta(0):
        raise ForecastError("issued_at must be timezone-aware UTC (§2)")
    received = received_at or _dt.datetime.now(tz=UTC)
    report = ForecastReport()
    for valid_at, value in values:
        if state.has_issue(datastream_id, valid_at, issued_at):
            report.already_present += 1
            continue
        current = state.forecast(datastream_id, valid_at, valid_at + _dt.timedelta(microseconds=1))
        obs = Observation(
            id=uuid7(), datastream=datastream_id, measured_at=valid_at,
            measured_at_uncertainty=uncertainty_s, received_at=received,
            result=value, clock_quality=clock_quality, issued_at=issued_at,
            provenance=dict(provenance or {}))
        obs.validate_against(ds)
        log.append_record(obs)
        state.add(obs)
        report.written += 1
        if current and current[0].issued_at > issued_at:
            report.behind_newer += 1
    return report


def verify(state: P.State, forecast_id: UUID, measured_id: UUID, *,
           within_s: float = 1800.0) -> dict:
    """Every stored issue of a forecast against what a sensor measured at its valid
    time, by lead time in whole hours: `{lead_h: [error, ...]}` (forecast − measured).

    Uses every run in the log, not only the live one — the point of keeping them."""
    out: dict[int, list] = {}
    for obs in state.observations_of(forecast_id):
        if obs.issued_at is None or not isinstance(obs.result, (int, float)):
            continue
        truth = state.nearest(measured_id, obs.measured_at, within_s)
        if truth is None or not isinstance(truth.result, (int, float)):
            continue
        lead = int((obs.measured_at - obs.issued_at).total_seconds() // 3600)
        out.setdefault(lead, []).append(obs.result - truth.result)
    return out

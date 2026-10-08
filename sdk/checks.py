#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Health checks (spec v0.1 §4.2).

Checks run in the foundation and write **assertions** (§3.3), never mutations.
Nothing here touches an observation; §3.2 says they are written once, and the
whole point of moving quality off the row was so a judgement could change without
history changing with it.

One assertion per assessment run, carrying the union of flags
---------------------------------------------------------------
§4.2 lists four checks that each produce one flag; §3.3 makes `flags` a set and
has precedence select exactly *one* live assertion. Those cannot both hold if each
check writes its own assertion: when flatline and range fire together, one wins on
precedence and the other's flag vanishes — the silent loss the model exists to
prevent. So an assessment runs the suite, unions what fired, and writes one
assertion naming the suite, with `evidence` recording which check contributed
what. That is the only reading under which §3.3's precedence rule is coherent, and
it is recorded in the spec rather than left as an implementation habit.

Re-running is safe and auditable
--------------------------------
`assess` never edits. Re-assessing an observation — after a threshold retune, a
check fix, or a backfill — produces a new assertion carrying `supersedes`, and the
old one stays readable with the threshold version that produced it (§3.3). That is
what makes a false alarm traceable to the threshold that caused it.

Thresholds
----------
Resolution order is the versioned `Threshold` record, then the datastream's own
`thresholds` dict, then `DEFAULTS` here — which is §4.2's "thresholds live on the
datastream with sensible defaults, so apps can tune them without code". Every
assertion stamps the `Threshold` id it used, so a retune cannot silently re-flag
history.

Staleness is deliberately absent. §4.2 makes it a datastream state, and
`project.datastream_health` is where it lives; flagging a reading would mean
mutating a record that was correct when written because a *later* one never
arrived.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from uuid import UUID

import project as P
from ids import uuid7
from model import (Assertor, Datastream, Observation, QualityAssertion,
                   QualityFlag, Threshold, derive_usable)

SUITE = "foundation"
SUITE_VERSION = "1"

#: §4.2's "sensible defaults". Deliberately loose: a default that fires often is
#: worse than one that fires rarely, because a farmer who stops trusting the
#: flags has lost the whole feature.
DEFAULTS = {
    # Flatline has two knobs on purpose. `flat_seconds` is the physical one —
    # §4.2 says "identical values for LONGER THAN physically plausible", which is
    # a duration, and how long a frozen reading is implausible is a property of
    # the measurand, not of how often you sample it. `flat_n` is a confidence
    # guard: two equal readings an hour apart prove very little.
    #
    # A count-only threshold is coupled to the sample rate, and that coupling is
    # a trap: `flat_n: 12` means twelve hours at hourly sampling and one hour at
    # five-minute sampling, so the "same" threshold means different physical
    # things on two farms. Set `flat_seconds` for anything that matters.
    "flat_seconds": None,    # duration of an identical run before `stuck`
    "flat_n": 12,            # minimum samples before a flat run is believed
    "min": None,             # no range check unless configured
    "max": None,
    "max_rate_per_s": None,  # no rate check unless configured
    "cross_tolerance": None,  # no cross-check unless configured
}


@dataclass(frozen=True, slots=True)
class Finding:
    """One check's verdict on one observation."""

    flag: QualityFlag
    check: str
    reason: str


def thresholds_for(datastream: Datastream,
                   threshold: Threshold | None = None) -> dict:
    """Merge DEFAULTS, the datastream's own values, then the versioned record."""
    values = dict(DEFAULTS)
    values.update(datastream.thresholds or {})
    if threshold is not None:
        values.update(threshold.values or {})
    return values


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ----------------------------------------------------------------- the checks

def check_range(obs: Observation, series, values, peers) -> Finding | None:
    """§4.2 Range → `out_of_range`. Soil moisture above saturation."""
    lo, hi = values.get("min"), values.get("max")
    if not _numeric(obs.result) or (lo is None and hi is None):
        return None
    if lo is not None and obs.result < lo:
        return Finding(QualityFlag.OUT_OF_RANGE, "range",
                       f"{obs.result} below min {lo}")
    if hi is not None and obs.result > hi:
        return Finding(QualityFlag.OUT_OF_RANGE, "range",
                       f"{obs.result} above max {hi}")
    return None


def check_flatline(obs: Observation, series, values, peers) -> Finding | None:
    """§4.2 Flatline → `stuck`. Identical values for longer than physically
    plausible.

    Walks back through the series measuring both how *long* the identical run has
    lasted and how many samples it contains. A probe reading exactly the same
    number for hours is either in a bucket or dead, and either way the value is
    not a measurement of the soil.

    `flat_seconds` is the real threshold because the spec's own wording is about
    duration; `flat_n` guards against calling two equal readings an hour apart a
    flatline. When both are set, both must be satisfied. When only `flat_n` is
    set the check still works, but its meaning moves with the sample rate — see
    DEFAULTS.
    """
    seconds_limit = values.get("flat_seconds")
    n_limit = values.get("flat_n")
    if obs.result is None or (seconds_limit is None and n_limit is None):
        return None

    earlier_rows = _upto(series, obs)
    run, oldest = 0, obs
    for earlier in earlier_rows:
        if earlier.result != obs.result:
            break
        run += 1
        oldest = earlier
    span = (obs.measured_at - oldest.measured_at).total_seconds()
    #: True when the run reached the start of the window we were given, so the span
    #: is a floor rather than the real duration.
    truncated = bool(earlier_rows) and run == len(earlier_rows)

    if n_limit is not None and run < n_limit:
        return None
    if seconds_limit is not None and span < seconds_limit:
        return None
    if seconds_limit is None and n_limit is None:
        return None

    at_least = "at least " if truncated else ""
    detail = (f"{run + 1} readings of {obs.result} unchanged over "
              f"{at_least}{span:.0f}s")
    if seconds_limit is not None:
        detail += f" (limit {seconds_limit:.0f}s)"
    else:
        detail += f" (limit {n_limit} samples; no flat_seconds set, so this "
        detail += "threshold moves with the sample rate)"
    return Finding(QualityFlag.STUCK, "flatline", detail)


def check_rate(obs: Observation, series, values, peers) -> Finding | None:
    """§4.2 Rate of change → `rate_exceeded`. A jump no real process could make.

    Measured against the previous reading in the series. A gap makes the allowed
    jump larger, which is correct: three hours of absence genuinely permits more
    change than three minutes.
    """
    limit = values.get("max_rate_per_s")
    if limit is None or not _numeric(obs.result):
        return None
    previous = _previous(series, obs)
    if previous is None or not _numeric(previous.result):
        return None
    seconds = (obs.measured_at - previous.measured_at).total_seconds()
    if seconds <= 0:
        return None
    rate = abs(obs.result - previous.result) / seconds
    if rate > limit:
        return Finding(QualityFlag.RATE_EXCEEDED, "rate",
                       f"{rate:.6g}/s over {seconds:.0f}s exceeds {limit:.6g}/s")
    return None


def check_cross(obs: Observation, series, values, peers) -> Finding | None:
    """§4.2 Cross-check → `suspect`. Disagreement with a redundant sensor on the
    same feature.

    Only `suspect`, never `bad`: when two probes disagree, this check cannot say
    which one is wrong. Calling either one bad would be a guess dressed as a
    measurement.
    """
    tolerance = values.get("cross_tolerance")
    if tolerance is None or not _numeric(obs.result) or not peers:
        return None
    for peer_obs in peers:
        if not _numeric(peer_obs.result):
            continue
        if abs(obs.result - peer_obs.result) > tolerance:
            return Finding(QualityFlag.SUSPECT, "cross",
                           f"differs from a redundant sensor by "
                           f"{abs(obs.result - peer_obs.result):.6g} "
                           f"(tolerance {tolerance:.6g})")
    return None


DEFAULT_CHECKS = (check_range, check_flatline, check_rate, check_cross)


# --------------------------------------------------------------- the assessor

def _lookback(datastream, values) -> int:
    """How many recent samples the checks can possibly need.

    Flatline is the only check that walks backwards, and it stops at the first value
    that differs, so it never needs more than its own threshold's worth of history.
    Rate needs one predecessor. Everything else needs none.
    """
    needed = 2
    seconds = values.get("flat_seconds")
    interval = datastream.expected_interval
    if seconds and interval:
        needed = max(needed, int(seconds / interval) + 2)
    count = values.get("flat_n")
    if count:
        needed = max(needed, int(count) + 2)
    # Generously, because the verdict needs only the threshold's worth but the
    # *evidence* should report how long the value has really been frozen — a
    # farmer wants "stuck for eight hours", not "stuck for the 75 minutes we
    # bothered to look at". Beyond this the finding says "at least".
    return max(32, needed * 8)


def _series(state: P.State, datastream_id: UUID,
            limit: int | None = None) -> list[Observation]:
    """The live rows of one series, in §2's order, optionally only the recent ones.

    Two bounds, both there because the first season-scale run was quadratic against
    §7.2's promise that years of readings never slow everyday work: the rows come
    from the state's per-datastream index rather than from filtering the whole live
    set, and `limit` keeps a check from re-sorting a season every time it looks at
    one reading. A backfilled row older than the window cannot change a flatline
    verdict, because the run stops at the first differing value anyway.
    """
    return P.order_observations(
        state.live_observations_of(datastream_id, tail=limit))


def _upto(series, obs):
    """The series before `obs`, nearest first.

    Located by `id`, not by value. `list.index` invokes the dataclass's generated
    `__eq__`, which compares every field of every candidate — including the
    provenance dict — and at season scale that was the single most expensive thing
    in ingest. An id comparison answers the same question.
    """
    target = obs.id
    for position, row in enumerate(series):
        if row.id == target:
            return series[position - 1::-1] if position else []
    return []


def _previous(series, obs):
    earlier = _upto(series, obs)
    return earlier[0] if earlier else None


def _peers(state: P.State, obs: Observation, window_s: float = 900.0):
    """Live observations comparable to this one: same observed property, same
    feature, same *kind* and unit, from a different sensor, close enough in time.

    **Kind and unit are not optional here.** A raw series is in whatever the node
    sent — a soil probe's `280` — and a derived series is in physical units,
    `0.280`. Comparing across them is a unit error that makes every pair of probes
    look like they violently disagree. Measured before this guard existed: a 99.8%
    false-alarm rate on a farm with nothing wrong with it, because each derived
    reading was being compared against its neighbour's raw one.
    """
    own = state.datastreams.get(obs.datastream)
    if own is None:
        return []
    # Find the comparable *datastreams* first — there are a handful of those, and
    # thousands of observations. Filtering every observation in the log for every
    # assessment is what made this quadratic.
    peer_streams = [ds for ds in state.datastreams.values()
                    if ds.id != own.id
                    and ds.sensor != own.sensor
                    and ds.observed_property == own.observed_property
                    and ds.kind is own.kind
                    and ds.unit == own.unit
                    and ds.feature == own.feature]
    if not peer_streams:
        return []
    mine = obs.effective_feature(own)
    out = []
    for ds in peer_streams:
        # Only the tail can be inside the window, and the window is minutes.
        for other in state.live_observations_of(ds.id, tail=64):
            if other.effective_feature(ds) != mine:
                continue
            if abs((other.measured_at - obs.measured_at).total_seconds()) > window_s:
                continue
            out.append(other)
    return out


def assess(state: P.State, obs: Observation, *,
           threshold: Threshold | None = None,
           checks=DEFAULT_CHECKS,
           asserted_at: _dt.datetime | None = None,
           supersedes: UUID | None = None) -> QualityAssertion:
    """Run the suite over one observation and return one assertion.

    Always returns an assertion, including a clean one. §3.3's empty flag set is a
    judgement — "checked, no objection" — and it is not the same as never having
    looked, which is the absence of any assertion at all.
    """
    datastream = state.datastreams[obs.datastream]
    values = thresholds_for(datastream, threshold)
    series = _series(state, obs.datastream, limit=_lookback(datastream, values))
    peers = _peers(state, obs)

    findings = [f for f in (c(obs, series, values, peers) for c in checks)
                if f is not None]
    flags = frozenset(f.flag for f in findings)
    evidence = {
        "checks_run": [c.__name__.removeprefix("check_") for c in checks],
        "fired": {f.check: f.reason for f in findings},
        "thresholds": {k: v for k, v in values.items() if v is not None},
    }
    return QualityAssertion(
        id=uuid7(),
        observation=obs.id,
        flags=flags,
        usable=derive_usable(flags),
        check=SUITE,
        check_version=SUITE_VERSION,
        threshold_version=threshold.id if threshold is not None else None,
        asserted_at=asserted_at or _dt.datetime.now(tz=_dt.timezone.utc),
        assertor=Assertor.FOUNDATION,
        supersedes=supersedes,
        note="; ".join(f"{f.check}: {f.reason}" for f in findings) or None,
        evidence=evidence,
    )


def assess_series(state: P.State, datastream_id: UUID, *,
                  threshold: Threshold | None = None,
                  checks=DEFAULT_CHECKS,
                  asserted_at: _dt.datetime | None = None,
                  reassess: bool = False) -> list[QualityAssertion]:
    """Assess every live observation in a datastream.

    With `reassess`, each new assertion supersedes the current live one for that
    observation — which is how a threshold retune or a check fix is applied
    without rewriting anything (§3.3). Without it, observations that already carry
    an assertion are skipped, so a routine pass is cheap and idempotent.
    """
    out = []
    for obs in _series(state, datastream_id):          # the whole series, by design
        existing = state.live_assertion_for(obs.id)
        if existing is not None and not reassess:
            continue
        if existing is not None and existing.assertor is Assertor.PERSON:
            # §3.3: a person outranks the foundation. Superseding their override
            # with a machine verdict would silently discard a human judgement.
            continue
        out.append(assess(state, obs, threshold=threshold, checks=checks,
                          asserted_at=asserted_at,
                          supersedes=existing.id if existing else None))
    return out

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
from dataclasses import dataclass, field
from uuid import UUID

import i18n
import project as P
import vocab
from ids import uuid7
from model import (Assertor, Datastream, DatastreamKind, Observation,
                   QualityAssertion, QualityFlag, Threshold, derive_usable)

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
    # The shape of a spike, for series where a rate cannot tell a fault from the
    # weather (Q23). `spike_step`: readings that leave their level by at least this,
    # stay out no longer than `spike_max_s`, and come back. Rain rises and holds; a
    # glitch comes back. Off unless configured.
    "spike_step": None,
    "spike_max_s": 1800.0,
    # Falls faster than this are `suspect`. Soil fills fast and empties slowly, so a
    # cap on falls can be tight where one on rises cannot. Off unless configured.
    "max_fall_per_s": None,
    # Neighbours further apart than this leave the shape and the fall undecided.
    "shape_max_gap_s": 3 * 3600.0,
    "cross_tolerance": None,  # no cross-check unless configured
    # A soil-moisture reading taken while the same probe's soil was below this is
    # `suspect`: capacitance and impedance probes sense liquid water only, so frozen
    # soil reads falsely dry. ISMN's D01 is the same rule. None switches it off.
    "frozen_below_c": 0.0,
}


@dataclass(frozen=True, slots=True)
class Finding:
    """One check's verdict on one observation.

    `key` and `params` are what the log keeps for any language to render later; `reason`
    is the English rendering, kept because a person reading a raw log deserves a
    sentence. Both come from the same template in `packs/en.json`, so they cannot
    drift apart.
    """

    flag: QualityFlag
    check: str
    reason: str
    key: str | None = None
    params: dict = field(default_factory=dict)


def _finding(flag: QualityFlag, check: str, key: str, **params) -> Finding:
    return Finding(flag, check, i18n.english(key, **params), key, params)


def _frozen(state: P.State, obs: Observation, datastream: Datastream,
            values: dict) -> tuple[bool, Finding | None]:
    """§4.2: moisture read while the probe's own soil was frozen.

    Needs the *same device's* soil temperature (§4.1: one TEROS-class body reports both),
    read within the larger of an hour and the temperature series' own interval. No
    temperature, no verdict — this never guesses that soil is frozen from the season.
    Only `suspect`: the reading is a true measurement of liquid water, just not of the
    water that matters for irrigation.

    Returns `(ran, finding)`. `ran` is false when the device has no temperature channel,
    so the evidence never lists a check as having run and stayed quiet when it could not
    run at all — a test caught the first version doing exactly that.
    """
    limit = values.get("frozen_below_c")
    if limit is None or datastream.observed_property != vocab.SOIL_WATER:
        return False, None
    for ds in state.datastreams_of_sensor(datastream.sensor):
        if (ds.kind is DatastreamKind.DERIVED
                and ds.observed_property == vocab.SOIL_TEMPERATURE):
            within = max(3600.0, ds.expected_interval or 0.0)
            reading = state.nearest(ds.id, obs.measured_at, within)
            if reading is not None and _numeric(reading.result) \
                    and reading.result < limit:
                return True, _finding(QualityFlag.SUSPECT, "frozen",
                                      "check.frozen.below",
                                      temperature=reading.result, limit=limit)
            return True, None
    return False, None


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
        return _finding(QualityFlag.OUT_OF_RANGE, "range", "check.range.below",
                        value=obs.result, min=lo)
    if hi is not None and obs.result > hi:
        return _finding(QualityFlag.OUT_OF_RANGE, "range", "check.range.above",
                        value=obs.result, max=hi)
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

    # Four keys rather than one sentence assembled from parts: "at least" and the
    # count-only caveat sit in different places in different languages, so a
    # translator needs whole sentences to work with.
    if seconds_limit is not None:
        key = "check.flatline.stuck_floor" if truncated else "check.flatline.stuck"
        limit = seconds_limit
    else:
        key = ("check.flatline.stuck_count_floor" if truncated
               else "check.flatline.stuck_count")
        limit = n_limit
    return _finding(QualityFlag.STUCK, "flatline", key, count=run + 1,
                    value=obs.result, span=span, limit=limit)


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
        return _finding(QualityFlag.RATE_EXCEEDED, "rate", "check.rate.exceeded",
                        rate=rate, seconds=seconds, limit=limit)
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
            return _finding(QualityFlag.SUSPECT, "cross", "check.cross.disagrees",
                            difference=abs(obs.result - peer_obs.result),
                            tolerance=tolerance)
    return None


#: How close to its starting level a spike must come back, as a share of how far it
#: went out. 0.3: most of the way, which a rain rise draining over days does not do.
SPIKE_RETURN_SHARE = 0.3
#: The longest run of readings a spike may span, whatever the sampling interval.
_SPIKE_MAX_READINGS = 12


def _spike_run(rows, end: int, values) -> list | None:
    """The run of readings that spiked and came back at `rows[end]`, or None.

    `rows` is a stretch of one series in display order, and `rows[end]` the reading
    that would be the return. Walks back over runs of one to `_SPIKE_MAX_READINGS`
    readings, shortest first: every reading in the run displaced from the level before
    it by at least `spike_step`, in one direction; the run lasting no longer than
    `spike_max_s`; no gap longer than `shape_max_gap_s`; and the return within
    `SPIKE_RETURN_SHARE` of the excursion of the starting level.
    """
    step = values.get("spike_step")
    if step is None or end < 2:
        return None
    max_gap = values.get("shape_max_gap_s") or float("inf")
    max_span = values.get("spike_max_s") or 0.0
    back = rows[end]
    if not _numeric(back.result):
        return None
    for length in range(1, min(_SPIKE_MAX_READINGS, end - 1) + 1):
        run = rows[end - length:end]
        base = rows[end - length - 1]
        if not all(_numeric(r.result) for r in run) or not _numeric(base.result):
            return None
        stretch = [base] + run + [back]
        if any((b.measured_at - a.measured_at).total_seconds() > max_gap
               for a, b in zip(stretch, stretch[1:])):
            return None
        if (run[-1].measured_at - run[0].measured_at).total_seconds() > max_span:
            return None
        offsets = [r.result - base.result for r in run]
        if not all(abs(o) >= step for o in offsets):
            continue
        if not (all(o > 0 for o in offsets) or all(o < 0 for o in offsets)):
            return None
        smallest = min(abs(o) for o in offsets)
        if abs(back.result - base.result) <= SPIKE_RETURN_SHARE * smallest:
            return run
    return None


def _spike_finding(run, base_value, values) -> Finding:
    peak = max(run, key=lambda r: abs(r.result - base_value))
    return _finding(QualityFlag.RATE_EXCEEDED, "spike", "check.spike.excursion",
                    out=peak.result - base_value, readings=len(run),
                    step=values.get("spike_step"))


def check_fall(obs: Observation, series, values, peers) -> Finding | None:
    """A fall faster than soil can drain → `suspect` (Q23).

    The allowance scales with the gap up to `shape_max_gap_s`, beyond which nothing is
    decided — drainage is a rate, so a longer gap genuinely allows more, but past a few
    hours the reading before says too little. The way back from a spike is not a fall:
    the spike check judges that excursion, and flagging its return as well would
    blame a good reading for a bad one."""
    limit = values.get("max_fall_per_s")
    if limit is None or not _numeric(obs.result):
        return None
    earlier = _upto(series, obs)
    if not earlier or not _numeric(earlier[0].result):
        return None
    previous = earlier[0]
    seconds = (obs.measured_at - previous.measured_at).total_seconds()
    if seconds <= 0 or seconds > (values.get("shape_max_gap_s") or float("inf")):
        return None
    fall = previous.result - obs.result
    if fall <= limit * seconds:
        return None
    window = list(reversed(earlier[:_SPIKE_MAX_READINGS + 1])) + [obs]
    if _spike_run(window, len(window) - 1, values) is not None:
        return None
    return _finding(QualityFlag.SUSPECT, "fall", "check.fall.fast",
                    fall=fall, hours=seconds / 3600.0, limit=limit * 3600.0)


DEFAULT_CHECKS = (check_range, check_flatline, check_rate, check_fall, check_cross)

#: A forecast gets the range check and nothing else (Q26). A value outside what the
#: variable can be — 80 °C air, negative rain — is a broken feed or a unit mixed up in
#: an adapter, and saying so is honest. The rest are sensor checks and would mislead:
#: a forecast holding one value for a day is not a stuck probe, a front is not a spike,
#: and a forecast has no redundant neighbour or frozen soil to consult.
FORECAST_CHECKS = (check_range,)


#: Checks whose finding is a step between two readings, which work done on the device in
#: between can explain (Q22). Flatline, range and cross-check judge the reading itself.
STEP_CHECKS = ("rate", "fall")


def maintenance_between(state: P.State, datastream: Datastream, start: _dt.datetime,
                        end: _dt.datetime):
    """The latest maintenance event on the datastream's own device in `(start, end]`, or
    None (Q22). Only the device the series comes from: a node's battery change explains
    a step in the node's battery voltage, not in the soil moisture of a probe it carries."""
    events = [e for e in state.maintenance_of(datastream.sensor) if start < e.at <= end]
    return events[-1] if events else None


def checks_for(datastream: Datastream) -> tuple:
    return FORECAST_CHECKS if datastream.kind is DatastreamKind.FORECAST else DEFAULT_CHECKS


def _spike_containing(state: P.State, obs: Observation, values) -> Finding | None:
    """Whether `obs` is inside a spike the series has already come back from — known
    when a reading is assessed after its successors arrived: a backfill, or a batch
    re-assessment."""
    if values.get("spike_step") is None:
        return None
    before = state.ordered_upto(obs.datastream, obs, _SPIKE_MAX_READINGS + 2)
    after = state.following(obs.datastream, obs, _SPIKE_MAX_READINGS + 1)
    rows = before + after
    here = len(before) - 1
    for end in range(here + 1, len(rows)):
        run = _spike_run(rows, end, values)
        if run is not None and any(r.id == obs.id for r in run):
            base = rows[end - len(run) - 1]
            datastream = state.datastreams[obs.datastream]
            if maintenance_between(state, datastream, base.measured_at, rows[end].measured_at):
                return None
            return _spike_finding(run, base.result, values)
    return None


def spike_assertions(state: P.State, obs: Observation, *,
                     threshold: Threshold | None = None,
                     asserted_at: _dt.datetime | None = None) -> list:
    """The late half of the spike check: assertions for readings that `obs` shows to
    have been a spike, now that the series has come back.

    A spike cannot be judged when it arrives — only the next reading says whether it
    was a change in the soil or a glitch — so it is judged **one reading late**, the
    same pattern the siting check uses to flag readings already in the log. The rules
    are the siting check's too, each for the same reason: the flag is added to the
    reading's live judgement rather than replacing it; a person's judgement is never
    superseded; and a reading already judged a spike is left alone, so running this on
    every arrival is safe.

    Pure: returns the assertions; the caller appends them.
    """
    datastream = state.datastreams.get(obs.datastream)
    if datastream is None:
        return []
    values = thresholds_for(datastream, threshold)
    if values.get("spike_step") is None:
        return []
    rows = state.ordered_upto(obs.datastream, obs, _SPIKE_MAX_READINGS + 2)
    run = _spike_run(rows, len(rows) - 1, values)
    if run is None:
        return []
    base = rows[len(rows) - len(run) - 2]
    if maintenance_between(state, datastream, base.measured_at, rows[-1].measured_at):
        return []          # a probe lifted out to clean and put back: explained (Q22)
    finding = _spike_finding(run, base.result, values)
    out = []
    for reading in run:
        current = state.live_assertion_for(reading.id)
        if current is not None and current.assertor is Assertor.PERSON:
            continue
        evidence = dict(current.evidence) if current is not None else {
            "checks_run": [], "fired": {}, "messages": {},
            "thresholds": {k: v for k, v in values.items() if v is not None}}
        if "spike" in evidence.get("fired", {}):
            continue
        evidence["checks_run"] = list(evidence.get("checks_run", [])) + ["spike"]
        evidence["fired"] = dict(evidence.get("fired", {}), spike=finding.reason)
        evidence["messages"] = dict(evidence.get("messages", {}),
                                    spike={"key": finding.key, "params": finding.params})
        flags = frozenset(current.flags if current is not None else ()) | {finding.flag}
        notes = [n for n in ((current.note if current is not None else None),
                             f"spike: {finding.reason}") if n]
        out.append(QualityAssertion(
            id=uuid7(), observation=reading.id, flags=flags,
            usable=derive_usable(flags), check=SUITE, check_version=SUITE_VERSION,
            threshold_version=threshold.id if threshold is not None else None,
            asserted_at=asserted_at or _dt.datetime.now(tz=_dt.timezone.utc),
            assertor=Assertor.FOUNDATION,
            supersedes=current.id if current is not None else None,
            note="; ".join(notes), evidence=evidence))
    return out


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

    The ids are compared **as integers**. `UUID.__eq__` is pure Python — an
    `isinstance` call, an attribute fetch, then an integer compare — and this scan
    runs it once per row per assessment. Together with the same pattern in
    `State.comparable_datastreams`, profiling one simulated week attributed **15
    million `UUID.__eq__` calls** and 3.4 s of 31 s to UUID equality alone. `.int` is
    the same comparison with none of the dispatch.
    """
    target = obs.id.int
    # The common case: `State.ordered_upto` hands over a window that *ends* at `obs`.
    if series and series[-1].id.int == target:
        return series[-2::-1]
    for position, row in enumerate(series):
        if row.id.int == target:
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
    # Ask the *datastreams* first — there are a handful of those, and thousands of
    # observations. Filtering every observation in the log for every assessment is
    # what made this quadratic. The predicate itself lives on the state, where it is
    # cached: recomputing it here meant scanning every datastream on the farm, with
    # several UUID comparisons each, once per reading.
    peer_streams = state.comparable_datastreams(own.id)
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
           checks=None,
           asserted_at: _dt.datetime | None = None,
           supersedes: UUID | None = None) -> QualityAssertion:
    """Run the suite over one observation and return one assertion.

    Always returns an assertion, including a clean one. §3.3's empty flag set is a
    judgement — "checked, no objection" — and it is not the same as never having
    looked, which is the absence of any assertion at all.
    """
    datastream = state.datastreams[obs.datastream]
    forecast = datastream.kind is DatastreamKind.FORECAST
    checks = checks if checks is not None else checks_for(datastream)
    values = thresholds_for(datastream, threshold)
    series = [] if forecast else state.ordered_upto(obs.datastream, obs, _lookback(datastream, values))
    peers = [] if forecast else _peers(state, obs)

    findings = [f for f in (c(obs, series, values, peers) for c in checks)
                if f is not None]
    # A step the maintenance log explains is not a fault (Q22): a new battery lifts the
    # voltage in one reading, a cleaned probe reads differently after. The finding is
    # kept in the evidence, as explained, so the judgement can still be audited.
    explained = {}
    previous = _previous(series, obs) if not forecast else None
    if previous is not None and any(f.check in STEP_CHECKS for f in findings):
        event = maintenance_between(state, datastream, previous.measured_at, obs.measured_at)
        if event is not None:
            for f in [f for f in findings if f.check in STEP_CHECKS]:
                findings.remove(f)
                explained[f.check] = {"key": "check.explained.maintenance",
                                      "params": {"action": event.action.value,
                                                 "at": event.at.isoformat(),
                                                 "finding": f.reason},
                                      "maintenance": str(event.id)}
    frozen_ran, frozen = (False, None) if forecast else _frozen(state, obs, datastream, values)
    if frozen is not None:
        findings.append(frozen)
    # Only decidable here when the readings after this one are already in: otherwise
    # `spike_assertions` decides it when they arrive, and the evidence must not claim
    # the check ran.
    spike_ran = (not forecast and values.get("spike_step") is not None
                 and bool(state.following(obs.datastream, obs, 1)))
    spike = _spike_containing(state, obs, values) if spike_ran else None
    if spike is not None:
        findings.append(spike)
    flags = frozenset(f.flag for f in findings)
    evidence = {
        "checks_run": [c.__name__.removeprefix("check_") for c in checks]
                      + (["frozen"] if frozen_ran else [])
                      + (["spike"] if spike_ran else []),
        "fired": {f.check: f.reason for f in findings},
        # What any language renders from, years later, from this same record.
        "messages": {f.check: {"key": f.key, "params": f.params}
                     for f in findings if f.key},
        "thresholds": {k: v for k, v in values.items() if v is not None},
    }
    if explained:
        evidence["explained"] = explained
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
                  checks=None,
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

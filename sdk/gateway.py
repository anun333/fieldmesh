#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Gateway ingest (spec v0.1 §5.1 step 4, §5.4, §8.1).

The whole of §5.1's step 4, in order:

    resolve ids through the registry
    compute times (§2)
    drop duplicates on (site, node, boot, seq) (§1)
    write the raw observation (§3.2)
    derive the calibrated one, by the calibration in force at measured_at (§3.2)
    run health checks (§4.2)

Everything it learns that is not a reading, it **records**. A frame that will not
parse, a device nobody approved, a hole in a sequence, a node that rebooted,
readings a node had to evict — each is an event in the log (§5.4), because the
alternative is a dataset with quiet holes in it and no way to tell a gap from a
reading that never existed.

Four behaviours worth stating because the easy implementation gets them wrong:

**An unregistered node is quarantined, not dropped.** §8.1: unregistered devices
are heard but not trusted. Their frames are logged with their payload so someone
can approve the device and replay them, and nothing of theirs reaches an
observation.

**A duplicate is a non-event.** Store-and-forward and cumulative acks both mean
re-delivery is normal, so `(site, node, boot, seq)` arriving twice is expected and
silent — but `dropped` and gaps are *not* re-counted for it.

**A sequence that goes backwards is usually a wrap, not a replay.** §1: `seq` is
uint16 and resets per boot, so the gateway tracks an unwrapped counter and treats a
decrease of more than half the range as a wrap. Getting this wrong discards a
node's whole next 32768 readings.

**An unparseable frame is a gap.** §5.4 forbids guessing, so a bad frame is logged
with the reason and the bytes, and the readings it carried are simply absent — which
the next frame's sequence number will reveal as a gap.

**Two readings may not land on one instant.** §3.2 allows exactly one live
observation per `(datastream, measured_at)`, because two at one `phenomenonTime`
break every SensorThings client. The wire format's ages are whole seconds, so a node
sampling one channel faster than 1 Hz cannot express distinct instants and would
produce exactly that collision. The gateway refuses the second reading and records
it, rather than writing a state that violates the invariant — and the event names
the real cause, which is a sample interval finer than the format can carry.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from uuid import UUID

import checks as C
import project as P
import wire
from ids import uuid7
from model import Observation
from registry import Registry

#: Event kinds this writes besides the records themselves.
REBOOT = "node_reboot"
GAP = "gap"
QUARANTINE = "quarantine"
UNDECODABLE = "undecodable_frame"
UNBOUND = "unbound_channel"
UNDERIVABLE = "underivable_reading"
COLLISION = "timestamp_collision"

SEQ_RANGE = 1 << 16
SEQ_WRAP_THRESHOLD = SEQ_RANGE // 2


@dataclass
class _SeqTracker:
    """Unwrapped sequence state for one `(node, boot)` (§1)."""

    wraps: int = 0
    last_raw: int | None = None
    highest: int = -1
    seen: set = field(default_factory=set)

    def absolute(self, seq: int) -> int:
        if self.last_raw is not None and seq < self.last_raw:
            # §1: a decrease of more than half the range inside one boot is a
            # wrap. A small decrease is a late or reordered frame, not a wrap.
            if self.last_raw - seq > SEQ_WRAP_THRESHOLD:
                self.wraps += 1
        self.last_raw = seq
        return self.wraps * SEQ_RANGE + seq


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What happened to one frame. Every field is something that was logged."""

    status: str                      # accepted | duplicate | quarantined | undecodable
    raw: tuple = ()                  # raw observations written
    derived: tuple = ()              # derived observations written
    assertions: tuple = ()           # quality assertions written
    gaps: tuple = ()                 # gap events written
    reboot: bool = False
    unbound: tuple = ()              # channels with no point binding
    reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"


class Gateway:
    """Expands wire frames into observations, and records everything else."""

    __slots__ = ("registry", "log", "state", "_trackers")

    def __init__(self, registry: Registry, log, state: P.State | None = None):
        self.registry = registry
        self.log = log
        self.state = state if state is not None else P.state_from_log(log)
        self._trackers: dict[tuple[UUID, int, int], _SeqTracker] = {}
        self._rebuild_trackers()

    def _rebuild_trackers(self) -> None:
        """Recover dedup state from the log, so a restart does not re-accept
        everything it already has."""
        for obs in self.state.observations:
            if obs.node is None or obs.boot is None or obs.seq is None:
                continue
            node = _as_int(obs.node)
            binding = self.registry.node_for(node)
            if binding is None:
                continue
            key = (binding.site, node, obs.boot)
            tracker = self._trackers.setdefault(key, _SeqTracker())
            absolute = tracker.absolute(obs.seq)
            tracker.seen.add(absolute)
            tracker.highest = max(tracker.highest, absolute)

    # ------------------------------------------------------------------ ingest

    def receive(self, payload: bytes, *, received_at: _dt.datetime) -> IngestResult:
        try:
            message = wire.decode(payload)
        except wire.WireError as exc:
            self.log.append(UNDECODABLE, {"reason": str(exc),
                                          "bytes": payload.hex(),
                                          "received_at": received_at})
            return IngestResult(status="undecodable", reason=str(exc))
        return self.accept(message, received_at=received_at)

    def accept(self, message: wire.Message, *,
               received_at: _dt.datetime) -> IngestResult:
        """Ingest an already-decoded frame (the sim's entry point)."""
        if message.node is None:
            return IngestResult(
                status="undecodable",
                reason="this frame carries no node id, so the link driver must "
                       "supply one before ingest (§5.2)")
        node = message.node
        binding = self.registry.node_for(node)
        if binding is None:
            self.log.append(QUARANTINE, {
                "node": node, "boot": message.boot, "seq": message.seq,
                "readings": len(message.readings), "received_at": received_at,
                "reason": "device is not registered; heard but not trusted (§8.1)"})
            return IngestResult(status="quarantined",
                               reason=f"node {node:#x} is not registered")

        key = (binding.site, node, message.boot)
        tracker = self._trackers.setdefault(key, _SeqTracker())
        absolute = tracker.absolute(message.seq)
        if absolute in tracker.seen:
            # Re-delivery is ordinary under store-and-forward; nothing to record.
            return IngestResult(status="duplicate")

        reboot = self._note_reboot(binding, node, message.boot)
        gaps = self._note_gaps(binding, node, message, tracker, absolute, received_at)
        tracker.seen.add(absolute)
        tracker.highest = max(tracker.highest, absolute)

        raw_written, derived_written, assertions, unbound = [], [], [], []
        for reading in message.readings:
            datastream_id = self.registry.datastream_for(node, reading.channel)
            if datastream_id is None:
                unbound.append(reading.channel)
                self.log.append(UNBOUND, {
                    "node": node, "channel": reading.channel,
                    "boot": message.boot, "seq": message.seq,
                    "value": reading.value, "received_at": received_at,
                    "reason": "no point binding; the reading is recorded here and "
                              "not in any datastream"})
                continue
            raw = self._write_raw(binding, message, reading, datastream_id,
                                  received_at)
            if raw is None:
                continue
            raw_written.append(raw)
            derived = self._write_derived(raw, datastream_id, binding)
            if derived is not None:
                derived_written.append(derived)
            assertion = self._assess(derived if derived is not None else raw)
            if assertion is not None:
                assertions.append(assertion)

        return IngestResult(status="accepted", raw=tuple(raw_written),
                            derived=tuple(derived_written),
                            assertions=tuple(assertions), gaps=tuple(gaps),
                            reboot=reboot, unbound=tuple(unbound))

    # -------------------------------------------------------------- internals

    def _note_reboot(self, binding, node: int, boot: int) -> bool:
        """§5.4: a boot increment is a reboot, not a gap, and is logged as such."""
        previous = [b for (site, n, b) in self._trackers
                    if site == binding.site and n == node and b != boot]
        if not previous or boot <= max(previous):
            return False
        self.log.append(REBOOT, {"node": node, "boot": boot,
                                 "previous_boot": max(previous),
                                 "site": binding.site})
        return True

    def _note_gaps(self, binding, node, message, tracker, absolute,
                   received_at) -> list:
        """§5.4: gaps are logged as gaps and never filled with guesses."""
        events = []
        if tracker.highest >= 0 and absolute > tracker.highest + 1:
            missing = absolute - tracker.highest - 1
            events.append(self.log.append(GAP, {
                "node": node, "boot": message.boot, "site": binding.site,
                "after_seq": tracker.highest % SEQ_RANGE,
                "before_seq": message.seq, "missing_messages": missing,
                "received_at": received_at,
                "reason": "sequence numbers absent; never filled with guesses"}))
        if message.dropped:
            # §5.3: a node that evicts MUST report the count, so the loss is a
            # recorded gap rather than readings that quietly never existed.
            events.append(self.log.append(GAP, {
                "node": node, "boot": message.boot, "site": binding.site,
                "at_seq": message.seq, "evicted_readings": message.dropped,
                "received_at": received_at,
                "reason": "node evicted readings from its buffer (§5.3)"}))
        return events

    def _write_raw(self, binding, message, reading, datastream_id,
                   received_at) -> Observation | None:
        age = message.age_of(reading)
        measured_at = received_at - _dt.timedelta(seconds=age)
        if self._occupied(datastream_id, measured_at):
            self.log.append(COLLISION, {
                "node": binding.node, "channel": reading.channel,
                "datastream": str(datastream_id), "boot": message.boot,
                "seq": message.seq, "value": reading.value,
                "measured_at": measured_at,
                "reason": "a live observation already exists at this instant; "
                          "§3.2 allows exactly one. Wire ages are whole seconds, "
                          "so this usually means a sample interval finer than the "
                          "format can express"})
            return None
        observation = Observation(
            id=uuid7(),
            datastream=datastream_id,
            measured_at=measured_at,
            measured_at_uncertainty=binding.uncertainty_s,
            received_at=received_at,
            result=reading.value,
            clock_quality=binding.clock_quality,
            node=f"{binding.node:#x}",
            boot=message.boot,
            seq=message.seq,
            provenance=binding.provenance(),
        )
        self._append(observation)
        return observation

    def _write_derived(self, raw: Observation, raw_datastream_id: UUID,
                       binding) -> Observation | None:
        derived_ds = self.state.derived_of(raw_datastream_id)
        if derived_ds is None:
            return None
        sensor = self.state.datastreams[raw_datastream_id].sensor
        # §3.2: by measured_at, never by ingest time. A reading that spent three
        # days in a buffer gets the coefficients that were in force when it was
        # taken.
        calibration = self.state.calibration_for(sensor, raw.measured_at)
        if calibration is None:
            return None
        try:
            result = P.apply_calibration(raw.result, calibration)
        except P.CalibrationError as exc:
            # One unusable calibration must not cost the whole frame. The raw
            # observation is already written and is the archival truth (§3.2), so
            # the honest outcome is a derived series with a hole in it and an event
            # saying why — not a lost batch, and not a guessed value.
            self.log.append(UNDERIVABLE, {
                "observation": str(raw.id), "datastream": str(derived_ds.id),
                "calibration": str(calibration.id), "reason": str(exc)})
            return None
        provenance = dict(raw.provenance)
        provenance["derived_from_observation"] = str(raw.id)
        observation = Observation(
            id=uuid7(),
            datastream=derived_ds.id,
            measured_at=raw.measured_at,
            measured_at_uncertainty=raw.measured_at_uncertainty,
            received_at=raw.received_at,
            result=result,
            clock_quality=raw.clock_quality,
            node=raw.node, boot=raw.boot, seq=raw.seq,
            calibration=calibration.id,
            provenance=provenance,
        )
        self._append(observation)
        return observation

    def _assess(self, observation: Observation):
        """§4.2. The derived observation is assessed where there is one, because
        thresholds are in physical units — `max: 0.55` is soil moisture, not the
        integer the probe reported."""
        datastream = self.state.datastreams.get(observation.datastream)
        if datastream is None:
            return None
        threshold = _latest_threshold(self.state, datastream.id)
        assertion = C.assess(self.state, observation, threshold=threshold)
        self._append(assertion)
        return assertion

    def _occupied(self, datastream_id: UUID, measured_at: _dt.datetime) -> bool:
        """Is there already a live observation on this series at this instant?"""
        for obs in self.state.observations:
            if obs.datastream == datastream_id and obs.measured_at == measured_at:
                return True
        return False

    def _append(self, record) -> None:
        self.log.append_record(record)
        self.state.add(record)


def _latest_threshold(state: P.State, datastream_id: UUID):
    candidates = [t for t in state.thresholds.values()
                  if t.datastream == datastream_id]
    live = P.live(candidates)
    return max(live, key=lambda t: t.id.int) if live else None


def _as_int(node) -> int:
    return int(node, 16) if isinstance(node, str) else int(node)


__all__ = ["Gateway", "IngestResult", "REBOOT", "GAP", "QUARANTINE",
           "UNDECODABLE", "UNBOUND", "UNDERIVABLE", "COLLISION"]

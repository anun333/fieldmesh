#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Gateway ingest (spec v0.1 §5.1 step 4, §5.4, §8.1, §3.2)."""
from __future__ import annotations

import datetime as _dt
import unittest

import fixtures as fx
import gateway as G
import log as L
import project as P
import wire
from ids import uuid7
from model import ClockQuality, QualityFlag, UTC
from registry import NodeBinding, Registry

NODE = 0x4F2A17B3
NOW = _dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _farm(*, derived=True, calibration=True, thresholds=None, uncertainty=12.0,
          clock=ClockQuality.RTC_UNSYNCED, channels=(1,)):
    """A registry, a log and a gateway with one bed probe wired up.

    `thresholds` go on the **derived** datastream, because a threshold is in the
    units of the series it bounds: `max: 0.55` is soil moisture, not the integer
    the probe reported (§4.2).
    """
    lg = L.Log()
    raw = fx.raw_datastream(expected_interval=3600.0)
    records = [raw]
    if derived:
        records.append(fx.derived_datastream(raw, thresholds=thresholds or {}))
    if calibration:
        records.append(fx.calibration(raw.sensor, a=0.001, b=0.0,
                                      valid_from=_dt.datetime(2026, 1, 1, tzinfo=UTC)))
    for r in records:
        lg.append_record(r)
    state = P.state_from_log(lg)
    reg = Registry()
    reg.register_node(NodeBinding(node=NODE, site=uuid7(), clock_quality=clock,
                                  uncertainty_s=uncertainty, firmware="0.3.1",
                                  driver="sdi12", driver_version="1.2"))
    for ch in channels:
        reg.bind_point(NODE, ch, raw.id)
    return G.Gateway(reg, lg, state), lg, raw


def _frame(**kw):
    """One frame. `base_age` defaults to a value derived from `seq` so successive
    frames land on distinct instants, which is what a real node produces and what
    §3.2 requires — one live observation per (datastream, measured_at)."""
    kw.setdefault("node", NODE)
    kw.setdefault("readings", [wire.Reading(1, 0, 231)])
    kw.setdefault("base_age", 100_000 - kw.get("seq", 0))
    return wire.encode(wire.Message(**kw))


class TestTheHappyPath(unittest.TestCase):
    def setUp(self):
        self.gw, self.log, self.raw = _farm()

    def test_a_frame_becomes_raw_and_derived_observations(self):
        r = self.gw.receive(_frame(boot=4, seq=10, base_age=60), received_at=NOW)
        self.assertTrue(r.accepted)
        self.assertEqual(len(r.raw), 1)
        self.assertEqual(r.raw[0].result, 231, "raw is exactly what the node sent")
        self.assertEqual(len(r.derived), 1)
        self.assertAlmostEqual(r.derived[0].result, 0.231)
        self.assertEqual(len(r.assertions), 1)

    def test_measured_at_is_received_at_minus_the_age(self):
        """§2: the gateway computes times; the node only reports ages."""
        r = self.gw.receive(_frame(boot=4, seq=10, base_age=60,
                                   readings=[wire.Reading(1, 0, 231),
                                             wire.Reading(1, 300, 238)]),
                            received_at=NOW)
        times = sorted(o.measured_at for o in r.raw)
        self.assertEqual(times[1], NOW - _dt.timedelta(seconds=60))
        self.assertEqual(times[0], NOW - _dt.timedelta(seconds=360))

    def test_uncertainty_and_clock_quality_come_from_the_registry(self):
        """§2 forbids a timestamp nobody can bound, and a node cannot be asked at
        ingest how good its clock is."""
        r = self.gw.receive(_frame(boot=4, seq=10), received_at=NOW)
        self.assertEqual(r.raw[0].measured_at_uncertainty, 12.0)
        self.assertEqual(r.raw[0].clock_quality, ClockQuality.RTC_UNSYNCED)

    def test_provenance_comes_from_the_manifest(self):
        r = self.gw.receive(_frame(boot=4, seq=10), received_at=NOW)
        self.assertEqual(r.raw[0].provenance["firmware"], "0.3.1")
        self.assertEqual(r.raw[0].provenance["driver_version"], "1.2")

    def test_the_derived_row_names_its_calibration_and_its_source(self):
        """§3.2: reproducible from raw value, calibration and driver version."""
        r = self.gw.receive(_frame(boot=4, seq=10), received_at=NOW)
        self.assertIsNotNone(r.derived[0].calibration)
        self.assertEqual(r.derived[0].provenance["derived_from_observation"],
                         str(r.raw[0].id))

    def test_the_resulting_state_validates(self):
        self.gw.receive(_frame(boot=4, seq=10), received_at=NOW)
        self.assertEqual(self.gw.state.validate(), [])

    def test_everything_is_in_the_log_and_replays(self):
        self.gw.receive(_frame(boot=4, seq=10), received_at=NOW)
        replayed = P.state_from_log(self.log)
        self.assertEqual(len(replayed.observations), 2)
        self.assertEqual(len(replayed.assertions), 1)


class TestDeduplication(unittest.TestCase):
    """§1: the key is (site, node, boot, seq)."""

    def setUp(self):
        self.gw, self.log, _ = _farm()

    def test_re_delivery_is_silent_and_writes_nothing(self):
        frame = _frame(boot=4, seq=10)
        self.gw.receive(frame, received_at=NOW)
        before = len(self.log)
        r = self.gw.receive(frame, received_at=NOW)
        self.assertEqual(r.status, "duplicate")
        self.assertEqual(len(self.log), before, "a duplicate is a non-event")

    def test_a_seq_reset_after_a_reboot_is_not_a_duplicate(self):
        """The v0 defect: dedup on (node, seq) alone silently discarded everything
        after a solar node's nightly brownout."""
        self.gw.receive(_frame(boot=4, seq=0), received_at=NOW)
        r = self.gw.receive(_frame(boot=5, seq=0, base_age=7), received_at=NOW)
        self.assertTrue(r.accepted, "boot is part of the key for exactly this")
        self.assertTrue(r.reboot)

    def test_dedup_survives_a_gateway_restart(self):
        frame = _frame(boot=4, seq=10)
        self.gw.receive(frame, received_at=NOW)
        reborn = G.Gateway(self.gw.registry, self.log,
                           P.state_from_log(self.log))
        self.assertEqual(reborn.receive(frame, received_at=NOW).status,
                         "duplicate")


class TestSequenceWrap(unittest.TestCase):
    """§1: a decrease of more than half the range inside one boot is a wrap."""

    def setUp(self):
        self.gw, self.log, _ = _farm()

    def test_a_wrap_is_accepted_not_treated_as_a_replay(self):
        self.gw.receive(_frame(boot=4, seq=0xFFFE), received_at=NOW)
        self.gw.receive(_frame(boot=4, seq=0xFFFF), received_at=NOW)
        r = self.gw.receive(_frame(boot=4, seq=0), received_at=NOW)
        self.assertTrue(r.accepted,
                        "mistaking a wrap for a replay discards the node's next "
                        "32768 readings")

    def test_a_small_decrease_is_a_late_frame_not_a_wrap(self):
        self.gw.receive(_frame(boot=4, seq=10), received_at=NOW)
        r = self.gw.receive(_frame(boot=4, seq=8), received_at=NOW)
        self.assertTrue(r.accepted)
        again = self.gw.receive(_frame(boot=4, seq=8), received_at=NOW)
        self.assertEqual(again.status, "duplicate",
                         "and it is still deduplicated on its own number")


class TestGapsAreRecorded(unittest.TestCase):
    """§5.4: logged as gaps, never filled with guesses."""

    def setUp(self):
        self.gw, self.log, _ = _farm()

    def test_missing_sequence_numbers_are_logged_with_a_count(self):
        self.gw.receive(_frame(boot=4, seq=10), received_at=NOW)
        r = self.gw.receive(_frame(boot=4, seq=14), received_at=NOW)
        self.assertEqual(len(r.gaps), 1)
        payload = r.gaps[0].payload
        self.assertEqual(payload["missing_messages"], 3)
        self.assertEqual(payload["after_seq"], 10)
        self.assertEqual(payload["before_seq"], 14)

    def test_an_evicted_backlog_is_logged_as_a_gap(self):
        """§5.3: a node that evicts MUST report the count, so the loss is recorded
        rather than being readings that quietly never existed."""
        r = self.gw.receive(_frame(boot=4, seq=1, base_age=0, dropped=96),
                            received_at=NOW)
        self.assertEqual(len(r.gaps), 1)
        self.assertEqual(r.gaps[0].payload["evicted_readings"], 96)

    def test_consecutive_frames_leave_no_gap(self):
        self.gw.receive(_frame(boot=4, seq=10), received_at=NOW)
        r = self.gw.receive(_frame(boot=4, seq=11), received_at=NOW)
        self.assertEqual(r.gaps, ())

    def test_a_reboot_is_a_reboot_not_a_gap(self):
        self.gw.receive(_frame(boot=4, seq=900), received_at=NOW)
        r = self.gw.receive(_frame(boot=5, seq=0, base_age=7), received_at=NOW)
        self.assertTrue(r.reboot)
        self.assertEqual(r.gaps, ())
        kinds = [e.kind for e in self.log]
        self.assertIn(G.REBOOT, kinds)


class TestUntrustedAndMalformed(unittest.TestCase):
    def setUp(self):
        self.gw, self.log, _ = _farm()

    def test_an_unregistered_node_is_quarantined_not_dropped(self):
        """§8.1: heard but not trusted."""
        r = self.gw.receive(_frame(boot=1, seq=1, base_age=0, node=0xDEAD),
                            received_at=NOW)
        self.assertEqual(r.status, "quarantined")
        self.assertEqual(len(list(self.log.records("observation"))), 0)
        quarantined = [e for e in self.log if e.kind == G.QUARANTINE]
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].payload["readings"], 1)

    def test_an_undecodable_frame_is_logged_with_its_bytes(self):
        r = self.gw.receive(b"\x87\x01", received_at=NOW)
        self.assertEqual(r.status, "undecodable")
        event = [e for e in self.log if e.kind == G.UNDECODABLE][0]
        self.assertEqual(event.payload["bytes"], "8701")
        self.assertIn("not CBOR", event.payload["reason"])

    def test_an_unbound_channel_is_logged_and_the_rest_still_lands(self):
        r = self.gw.receive(_frame(boot=4, seq=1, base_age=0,
                                   readings=[wire.Reading(1, 0, 231),
                                             wire.Reading(9, 0, 999)]),
                            received_at=NOW)
        self.assertTrue(r.accepted)
        self.assertEqual(r.unbound, (9,))
        self.assertEqual(len(r.raw), 1, "the bound channel still produced a reading")
        self.assertEqual([e.payload["value"] for e in self.log
                          if e.kind == G.UNBOUND], [999])

    def test_a_frame_with_no_node_id_is_refused_at_ingest(self):
        """§5.2 lets the field be null on a link that identifies the device, so the
        link driver must supply it before ingest."""
        r = self.gw.receive(_frame(boot=1, seq=1, base_age=0, node=None),
                            received_at=NOW)
        self.assertEqual(r.status, "undecodable")
        self.assertIn("link driver", r.reason)


class TestDerivation(unittest.TestCase):
    def test_calibration_is_chosen_by_measured_at_not_ingest(self):
        """§3.2, end to end: a reading that spent days in a buffer must get the
        coefficients that were in force when it was taken."""
        lg = L.Log()
        raw = fx.raw_datastream()
        derived = fx.derived_datastream(raw)
        spring = fx.calibration(raw.sensor, a=0.001,
                                valid_from=_dt.datetime(2026, 3, 1, tzinfo=UTC),
                                valid_to=_dt.datetime(2026, 6, 1, tzinfo=UTC))
        summer = fx.calibration(raw.sensor, a=0.002,
                                valid_from=_dt.datetime(2026, 6, 1, tzinfo=UTC))
        for r in (raw, derived, spring, summer):
            lg.append_record(r)
        reg = Registry()
        reg.register_node(NodeBinding(node=NODE, site=uuid7(),
                                      clock_quality=ClockQuality.GPS,
                                      uncertainty_s=1.0))
        reg.bind_point(NODE, 1, raw.id)
        gw = G.Gateway(reg, lg, P.state_from_log(lg))

        # Measured 30 May, delivered 2 June after a buffer drain.
        age = int((NOW + _dt.timedelta(days=1)
                   - _dt.datetime(2026, 5, 30, 9, 0, tzinfo=UTC)).total_seconds())
        r = gw.receive(_frame(boot=4, seq=1, base_age=age),
                       received_at=NOW + _dt.timedelta(days=1))
        self.assertEqual(r.derived[0].calibration, spring.id)
        self.assertAlmostEqual(r.derived[0].result, 0.231,
                               msg="ingest-time selection would have doubled it")

    def test_no_derived_datastream_means_raw_only(self):
        gw, _, _ = _farm(derived=False)
        r = gw.receive(_frame(boot=4, seq=1, base_age=0), received_at=NOW)
        self.assertEqual(len(r.raw), 1)
        self.assertEqual(r.derived, ())

    def test_no_calibration_in_force_means_raw_only(self):
        gw, _, _ = _farm(calibration=False)
        r = gw.receive(_frame(boot=4, seq=1, base_age=0), received_at=NOW)
        self.assertEqual(len(r.raw), 1)
        self.assertEqual(r.derived, ())

    def test_an_unusable_calibration_costs_the_derived_row_not_the_frame(self):
        """The raw observation is the archival truth (§3.2), so one bad calibration
        leaves a hole in the derived series and an event saying why — it does not
        lose the batch and it does not guess a value."""
        lg = L.Log()
        raw = fx.raw_datastream()
        derived = fx.derived_datastream(raw)
        broken = fx.calibration(raw.sensor, method="sorcery",
                                valid_from=_dt.datetime(2026, 1, 1, tzinfo=UTC))
        for r in (raw, derived, broken):
            lg.append_record(r)
        reg = Registry()
        reg.register_node(NodeBinding(node=NODE, site=uuid7(),
                                      clock_quality=ClockQuality.GPS,
                                      uncertainty_s=1.0))
        reg.bind_point(NODE, 1, raw.id)
        gw = G.Gateway(reg, lg, P.state_from_log(lg))
        r = gw.receive(_frame(boot=4, seq=1, base_age=0), received_at=NOW)
        self.assertTrue(r.accepted)
        self.assertEqual(len(r.raw), 1)
        self.assertEqual(r.derived, ())
        event = [e for e in lg if e.kind == G.UNDERIVABLE][0]
        self.assertIn("sorcery", event.payload["reason"])


class TestTimestampCollision(unittest.TestCase):
    """§3.2 allows exactly one live observation per (datastream, measured_at).

    Wire ages are whole seconds, so a node sampling one channel faster than 1 Hz
    cannot express distinct instants. The gateway must refuse the second reading
    rather than write a state that violates the invariant — and `State.validate`
    is what proves it did.
    """

    def setUp(self):
        self.gw, self.log, _ = _farm()

    def test_two_readings_on_one_channel_at_one_instant(self):
        r = self.gw.receive(_frame(boot=4, seq=1, base_age=60,
                                   readings=[wire.Reading(1, 0, 231),
                                             wire.Reading(1, 0, 999)]),
                            received_at=NOW)
        self.assertTrue(r.accepted)
        self.assertEqual(len(r.raw), 1, "the first reading lands")
        self.assertEqual(r.raw[0].result, 231)
        event = [e for e in self.log if e.kind == G.COLLISION][0]
        self.assertEqual(event.payload["value"], 999)
        self.assertIn("finer than the format", event.payload["reason"])

    def test_the_state_still_validates_afterwards(self):
        """The invariant holds, which is the whole point of refusing."""
        self.gw.receive(_frame(boot=4, seq=1, base_age=60,
                               readings=[wire.Reading(1, 0, 231),
                                         wire.Reading(1, 0, 999)]),
                        received_at=NOW)
        self.assertEqual(self.gw.state.validate(), [])

    def test_two_frames_that_round_to_the_same_second_collide_too(self):
        self.gw.receive(_frame(boot=4, seq=1, base_age=60), received_at=NOW)
        r = self.gw.receive(_frame(boot=4, seq=2, base_age=60), received_at=NOW)
        self.assertEqual(r.raw, ())
        self.assertEqual(self.gw.state.validate(), [])

    def test_distinct_instants_are_fine(self):
        r = self.gw.receive(_frame(boot=4, seq=1, base_age=60,
                                   readings=[wire.Reading(1, 0, 231),
                                             wire.Reading(1, 300, 238)]),
                            received_at=NOW)
        self.assertEqual(len(r.raw), 2)
        self.assertEqual(self.gw.state.validate(), [])

    def test_different_channels_at_one_instant_are_fine(self):
        """Two sensors sampled together are two datastreams, so two keys."""
        gw, log, raw = _farm(channels=(1,))
        second_raw = fx.raw_datastream()
        log.append_record(second_raw)
        gw.state.add(second_raw)
        gw.registry.bind_point(NODE, 2, second_raw.id)
        r = gw.receive(_frame(boot=4, seq=1, base_age=60,
                              readings=[wire.Reading(1, 0, 231),
                                        wire.Reading(2, 0, 180)]),
                       received_at=NOW)
        self.assertEqual(len(r.raw), 2)
        self.assertEqual(gw.state.validate(), [])


class TestAssessment(unittest.TestCase):
    def test_the_derived_reading_is_assessed_because_thresholds_are_physical(self):
        """`max: 0.55` is soil moisture, not the integer the probe reported."""
        gw, _, _ = _farm(thresholds={"max": 0.55})
        r = gw.receive(_frame(boot=4, seq=1, base_age=0,
                              readings=[wire.Reading(1, 0, 910)]),
                       received_at=NOW)
        self.assertEqual(r.assertions[0].observation, r.derived[0].id)
        self.assertIn(QualityFlag.OUT_OF_RANGE, r.assertions[0].flags)

    def test_a_clean_reading_still_gets_an_assertion(self):
        gw, _, _ = _farm(thresholds={"max": 0.55})
        r = gw.receive(_frame(boot=4, seq=1, base_age=0), received_at=NOW)
        self.assertEqual(r.assertions[0].flags, frozenset())

    def test_the_assertion_names_the_threshold_version_in_force(self):
        lg = L.Log()
        raw = fx.raw_datastream()
        derived = fx.derived_datastream(raw)
        cal = fx.calibration(raw.sensor, a=0.001,
                             valid_from=_dt.datetime(2026, 1, 1, tzinfo=UTC))
        th = fx.threshold(derived, max=0.55)
        for r in (raw, derived, cal, th):
            lg.append_record(r)
        reg = Registry()
        reg.register_node(NodeBinding(node=NODE, site=uuid7(),
                                      clock_quality=ClockQuality.GPS,
                                      uncertainty_s=1.0))
        reg.bind_point(NODE, 1, raw.id)
        gw = G.Gateway(reg, lg, P.state_from_log(lg))
        r = gw.receive(_frame(boot=4, seq=1, base_age=0), received_at=NOW)
        self.assertEqual(r.assertions[0].threshold_version, th.id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

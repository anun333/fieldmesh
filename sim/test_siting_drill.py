#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The siting drill as a regression test: scored, on the real farm, with the misses."""
from __future__ import annotations

import datetime as _dt
import unittest

import siting_drill as D


class TestSitingDrill(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.result = D.run(days=8.0, seed=1, disturbed=True)
        cls.events = cls.result["events"]

    def test_no_false_alarms_on_clean_probes(self):
        """The number that decides whether a farmer keeps trusting the flags."""
        clean = self.result["clean"]
        self.assertGreater(clean.assessed, 30)
        self.assertEqual(clean.flagged, 0)

    def test_an_unlogged_lift_is_caught_within_two_days(self):
        lift = self.events["bed4_shallow"]
        self.assertGreater(lift.flagged, 0)
        self.assertLessEqual(lift.first_flag_day, 2)

    def test_an_unlogged_push_is_caught_within_two_days(self):
        push = self.events["bed2_shallow"]
        self.assertGreater(push.flagged, 0)
        self.assertLessEqual(push.first_flag_day, 2)

    def test_a_lateral_move_at_the_same_depth_is_the_blind_spot(self):
        """Every bed shares the weather, so a move between beds at one depth leaves no
        thermal signature. Recall zero is the correct answer, and asserting it keeps
        anyone from later believing the check covers this."""
        self.assertEqual(self.events["bed3_deep"].flagged, 0)

    def test_a_logged_move_is_never_flagged(self):
        """The control. It also proves the simulator moves the probe with its record:
        before that fix, this exact move would have been flagged correctly."""
        self.assertEqual(self.events["bed6_shallow"].flagged, 0)

    def test_a_logged_move_is_not_flagged_by_the_lateral_check_either(self):
        """The false alarm the drill found: a window reaching back past a recorded move
        judged the new record by readings from the old bed. Both checks now clip to the
        current installation."""
        self.assertEqual(self.events["bed6_shallow"].lateral_flagged, 0)

    def test_the_lateral_check_catches_the_move_the_depth_check_cannot(self):
        """The blind spot, covered — by a different signal, which is the point."""
        swap = self.events["bed3_deep"]
        self.assertEqual(swap.flagged, 0, "the depth check is blind to it")
        self.assertGreater(swap.lateral_flagged, 0)
        self.assertLessEqual(swap.lateral_first_day, 2)

    def test_no_lateral_false_alarms_on_clean_probes(self):
        self.assertEqual(self.result["clean"].lateral_flagged, 0)


if __name__ == "__main__":
    unittest.main()


class TestNodePosition(unittest.TestCase):
    """The paddock node keeps GPS time; its fix now checks where it stands."""

    @classmethod
    def setUpClass(cls):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        os.pardir, "sdk"))
        import harrow_bend as hb
        import siting as S
        cls.hb, cls.S = hb, S
        cls.farm = hb.build()
        hb.season(cls.farm, days=2, events=False)
        cls.geo = hb.geometries(cls.farm)
        cls.node = cls.farm.node_devices["paddock"].id

    def test_nodes_are_devices_and_carry_their_own_battery(self):
        """§4.3: battery and signal are the node's, not two invented sensors."""
        state = self.farm.state
        props = {ds.observed_property for ds in state.datastreams_of_sensor(self.node)}
        import vocab as V
        self.assertTrue({V.BATTERY_VOLTAGE, V.RSSI, V.LATITUDE,
                         V.LONGITUDE} <= props)
        self.assertEqual(state.label_for(self.node).name, "paddock node")

    def test_only_the_gps_timed_node_reports_a_fix(self):
        import vocab as V
        for label, device in self.farm.node_devices.items():
            props = {ds.observed_property
                     for ds in self.farm.state.datastreams_of_sensor(device.id)}
            self.assertEqual(V.LATITUDE in props, label == "paddock", label)

    def test_in_place_it_is_consistent(self):
        finding = self.S.assess_position(self.farm.state, self.node,
                                         self.farm.world.when, self.geo)
        self.assertEqual(finding.verdict, self.S.CONSISTENT, finding.reason)

    def test_carried_to_another_bed_unlogged_it_is_displaced(self):
        farm = self.hb.build()
        self.hb.season(farm, days=1, events=False)
        self.hb.displace_node(farm, "paddock", feature="bed6")
        self.hb._run_segment(farm, self.hb.SeasonReport(days=1), 1.0)
        finding = self.S.assess_position(farm.state, farm.node_devices["paddock"].id,
                                         farm.world.when, self.hb.geometries(farm))
        self.assertEqual(finding.verdict, self.S.DISPLACED)
        self.assertGreater(finding.distance_m, 100)


class TestDisplacedProbeReadingsAreFlagged(unittest.TestCase):
    """End to end on the farm: an unlogged lift ends with the probe's moisture
    readings — the ones an irrigation decision would use — marked suspect."""

    def test_moisture_readings_from_a_lifted_probe_become_suspect(self):
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        os.pardir, "sdk"))
        import harrow_bend as hb
        import siting as S
        from model import QualityFlag
        farm = hb.build()
        hb.season(farm, days=3, events=False)
        hb.displace(farm, "bed4_shallow", depth_m=0.05)
        hb._run_segment(farm, hb.SeasonReport(days=3), 3.0)
        device = farm.series["bed4_shallow"].device.id
        finding = S.assess_siting(farm.state, device, farm.world.when)
        self.assertTrue(finding.displaced)
        flagging = S.suspect_assertions(farm.state, finding)
        for assertion in flagging.assertions:
            farm.log.append_record(assertion)
            farm.state.add(assertion)
        moisture = farm.series["bed4_shallow"].derived.id
        recent = [o for o in farm.state.live_observations_of(moisture)
                  if o.measured_at >= finding.at - _dt.timedelta(hours=24)]
        self.assertTrue(recent)
        for obs in recent:
            self.assertIn(QualityFlag.SUSPECT,
                          farm.state.live_assertion_for(obs.id).flags)
        self.assertEqual(farm.state.validate(), [])


class TestUnderMulch(unittest.TestCase):
    """A probe under mulch (sim/physics.SoilBed.mulch_m) is damped and delayed as a deeper
    one would be. Read against peers in bare beds it looks moved; with covers recorded,
    the depth check reads it only against peers under the same cover."""

    @classmethod
    def setUpClass(cls):
        import os
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sdk"))
        import physics as ph
        start = _dt.datetime(2026, 6, 10, tzinfo=_dt.timezone.utc)
        world = ph.World(start=start, climate=ph.Climate(seed=3),
                         beds=[ph.SoilBed(name="bare"), ph.SoilBed(name="mulched", mulch_m=0.05)])
        cls.probes = [("bare", 0.05), ("bare", 0.10), ("bare", 0.20),
                      ("mulched", 0.05), ("mulched", 0.10), ("mulched", 0.20)]
        cls.series = {p: [] for p in cls.probes}
        for n in range(4 * 24 * 12):
            tick = world.step()
            if n >= 24 * 12 and n % 12 == 0:
                for bed, z in cls.probes:
                    cls.series[(bed, z)].append((world.when, round(tick.soil_temp_at(bed, z), 1)))
        cls.at = world.when - _dt.timedelta(minutes=5)

    def farm(self, probes, *, covers: bool):
        """A log with these probes in it, each cover recorded or not."""
        import fixtures as fx
        import log as L
        import project as P
        import vocab as V
        from ids import uuid7
        from model import (Calibration, Datastream, DatastreamKind, Device, DeviceKind,
                           Installation)
        log, ids, site = L.Log(), {}, uuid7()
        beds = {"bare": uuid7(), "mulched": uuid7()}
        for bed, z in probes:
            device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=site)
            raw = Datastream(id=uuid7(), thing=uuid7(), sensor=device.id,
                             observed_property=V.SOIL_TEMPERATURE, feature=beds[bed],
                             kind=DatastreamKind.RAW, unit="Cel")
            derived = Datastream(id=uuid7(), thing=raw.thing, sensor=device.id,
                                 observed_property=V.SOIL_TEMPERATURE, feature=beds[bed],
                                 kind=DatastreamKind.DERIVED, derived_from=raw.id, unit="Cel")
            first = self.series[(bed, z)][0][0] - _dt.timedelta(days=2)
            cal = Calibration(id=uuid7(), sensor=device.id, datastream=raw.id,
                              method="identity", valid_from=first)
            surface = ("organic_mulch" if bed == "mulched" else "bare") if covers else None
            install = Installation(id=uuid7(), device=device.id, feature=beds[bed],
                                   installed_at=first, depth_m=z, surface=surface)
            for record in (device, raw, derived, cal, install):
                log.append_record(record)
            for when, value in self.series[(bed, z)]:
                log.append_record(fx.observation(derived, result=value, measured_at=when,
                                                 calibration=cal.id, node=None, boot=None, seq=None))
            ids[(bed, z)] = device.id
        return P.state_from_log(log), ids

    def assess(self, probes, *, covers, which=("mulched", 0.10)):
        import siting as S
        state, ids = self.farm(probes, covers=covers)
        return S.assess_siting(state, ids[which], self.at)

    def test_without_the_cover_recorded_a_mulched_probe_looks_moved(self):
        """The blind spot, shown: nothing moved, and bare peers say it is deeper."""
        found = self.assess([p for p in self.probes if p[0] == "bare"] + [("mulched", 0.10)],
                            covers=False)
        self.assertTrue(found.displaced, found.reason)
        self.assertGreater(found.evidence["implied_depth_m"], 0.15)

    def test_with_it_recorded_and_no_peer_under_mulch_it_cannot_tell(self):
        found = self.assess([p for p in self.probes if p[0] == "bare"] + [("mulched", 0.10)],
                            covers=True)
        self.assertFalse(found.displaced)
        self.assertEqual(found.key, "siting.too_few_peers_same_surface")
        self.assertEqual(found.params["others"], 3)

    def test_with_peers_under_the_same_mulch_it_reads_true(self):
        found = self.assess(self.probes, covers=True)
        self.assertEqual(found.verdict, "consistent", found.reason)
        self.assertEqual(found.evidence["surface"], "organic_mulch")
        self.assertEqual(found.evidence["peers_under_other_covers"], 3)
        # The bare probes are judged against bare peers, as before.
        self.assertEqual(self.assess(self.probes, covers=True, which=("bare", 0.10)).verdict,
                         "consistent")

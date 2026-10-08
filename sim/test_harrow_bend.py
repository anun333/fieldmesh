#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The completeness matrix, enforced (docs/VIRTUAL_FARM.md step 5).

One test per row of the matrix. A clause of the spec that nothing on the farm
exercises fails here rather than going quietly untested, which is the whole reason
the canonical farm exists.

**Rows that cannot pass yet skip with a reason naming what is missing**, rather than
being omitted. A row with no producer should be visible — campus_twin's doctrine is
that a placement without a producer is a lie, and the same applies to a matrix row
with nothing behind it.

The season is built once for the class; it is a few seconds of simulated farm.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import unittest

import harrow_bend as hb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sdk"))
import project as P  # noqa: E402
from model import Assertor, DatastreamKind, QualityFlag  # noqa: E402

DAYS = 12.0


class Matrix(unittest.TestCase):
    """Shared season. Every subclass reads the same farm."""

    farm = None
    report = None

    @classmethod
    def setUpClass(cls):
        if Matrix.farm is None:
            Matrix.farm = hb.build(seed=1)
            Matrix.report = hb.season(Matrix.farm, days=DAYS)
        cls.farm = Matrix.farm
        cls.report = Matrix.report
        cls.state = Matrix.farm.gateway.state
        cls.log = Matrix.farm.log

    def flagged(self):
        return [a for a in self.state.assertions if a.flags]

    def obs_of(self, series_name):
        return self.state.observations_of(
            self.farm.series[series_name].derived.id)


class TestTheFarmItself(Matrix):
    def test_it_assembled(self):
        self.assertEqual(len(self.farm.nodes), 5)
        self.assertGreaterEqual(len(self.farm.series), 28)
        self.assertGreaterEqual(len(self.state.datastreams), 56)

    def test_the_state_validates(self):
        """Every invariant the projection can check, over a whole season."""
        self.assertEqual(self.state.validate(), [])

    def test_it_is_anchored_where_nothing_real_is(self):
        self.assertEqual(hb.ANCHOR["coordinates"], [0.0, 0.0])

    def test_it_is_deterministic(self):
        farm = hb.build(seed=1)
        hb.season(farm, days=1.0)
        again = hb.build(seed=1)
        hb.season(again, days=1.0)
        self.assertEqual([o.result for o in farm.gateway.state.observations],
                         [o.result for o in again.gateway.state.observations])


class TestIdentity(Matrix):
    """§1."""

    def test_a_node_rebooted_and_reset_seq_with_nothing_deduplicated_away(self):
        reboots = [e for e in self.log if e.kind == "node_reboot"]
        self.assertEqual(len(reboots), 1, "logged once, not per frame")
        boot = reboots[0].payload["boot"]
        node = f"{reboots[0].payload['node']:#x}"
        after = [o for o in self.state.observations
                 if o.node == node and o.boot == boot]
        self.assertTrue(after, "readings after the reboot survived")
        self.assertIn(0, [o.seq for o in after], "and seq started again at zero")

    def test_id_order_differs_from_measured_at_order(self):
        """§1: ids are minted at ingest, so a backfilled reading sorts late."""
        rows = [o for o in self.state.observations if o.node]
        by_id = sorted(rows, key=lambda o: o.id.int)
        self.assertNotEqual([o.measured_at for o in by_id],
                            sorted(o.measured_at for o in by_id))


class TestTime(Matrix):
    """§2."""

    def test_all_five_clock_qualities_are_present(self):
        seen = {o.clock_quality.value for o in self.state.observations}
        self.assertEqual(seen, {"gps", "network", "rtc_synced", "rtc_unsynced",
                                "none"})

    def test_the_clockless_node_declares_an_honest_uncertainty(self):
        clockless = [o for o in self.state.observations
                     if o.clock_quality.value == "none"]
        self.assertTrue(clockless)
        for obs in clockless[:50]:
            self.assertGreaterEqual(obs.measured_at_uncertainty, 300.0,
                                    "at least its sample interval (§2)")

    def test_a_reading_buffered_for_days_kept_its_real_measured_at(self):
        """The three-day outage: readings arrive late, not backdated."""
        late = [o for o in self.state.observations
                if (o.received_at - o.measured_at) > _dt.timedelta(days=1)]
        self.assertTrue(late, "the outage should produce some")
        for obs in late[:50]:
            self.assertGreater(obs.received_at, obs.measured_at)


class TestDataModel(Matrix):
    """§3.1, §3.2."""

    def test_every_datastream_is_half_of_a_raw_calibrated_pair(self):
        raw = {ds.id for ds in self.state.datastreams.values()
               if ds.kind is DatastreamKind.RAW}
        derived_from = {ds.derived_from for ds in self.state.datastreams.values()
                        if ds.kind is DatastreamKind.DERIVED}
        self.assertEqual(raw, derived_from)

    def test_a_series_was_recalibrated_with_superseded_rows_still_present(self):
        superseded = [o for o in self.state.observations if o.supersedes]
        self.assertTrue(superseded, "the season recalibrates bed3_shallow")
        originals = {o.supersedes for o in superseded}
        present = {o.id for o in self.state.observations}
        self.assertTrue(originals <= present,
                        "every superseded row is still in the log")

    def test_exactly_one_live_row_per_timestamp_after_recalibration(self):
        live = self.state.live_observations(strict=True)
        self.assertGreater(len(live), 1000)

    def test_a_backfilled_reading_used_the_calibration_in_force_when_taken(self):
        series = self.farm.series["bed3_shallow"]
        cals = [c for c in self.state.calibrations.values()
                if c.sensor == series.raw.sensor]
        self.assertGreaterEqual(len(cals), 2, "recalibrated mid-season")
        live = {o.id for o in self.state.live_observations().values()}
        checked = 0
        for obs in self.obs_of("bed3_shallow"):
            if obs.calibration is None or obs.id not in live:
                # A *superseded* row keeps the calibration that produced it, whose
                # validity has since been closed. That is what "recalibration never
                # rewrites history" means: the old row remains a true statement
                # about what C1 computed, not a claim about today's calibrations.
                continue
            used = self.state.calibrations[obs.calibration]
            self.assertTrue(used.covers(obs.measured_at),
                            "by measured_at, never by ingest time (§3.2)")
            checked += 1
        self.assertGreater(checked, 100, "and it actually checked some")

    def test_a_handheld_reading_overrode_its_datastreams_feature(self):
        overrides = [o for o in self.state.observations if o.feature is not None]
        self.assertTrue(overrides)
        obs = overrides[0]
        datastream = self.state.datastreams[obs.datastream]
        self.assertNotEqual(obs.feature, datastream.feature)
        self.assertEqual(obs.effective_feature(datastream), obs.feature)


class TestQuality(Matrix):
    """§3.3."""

    def test_one_live_instance_of_each_flag(self):
        seen = {f.value for a in self.flagged() for f in a.flags}
        self.assertEqual(seen, {f.value for f in QualityFlag},
                         "every flag the spec defines must be produced")

    def test_a_reading_carrying_two_flags_at_once(self):
        """§3.3's reason for a set rather than one value."""
        multi = [a for a in self.flagged() if len(a.flags) > 1]
        self.assertTrue(multi)

    def test_a_persons_override_outranks_the_machine_and_the_original_survives(self):
        people = [a for a in self.state.assertions
                  if a.assertor is Assertor.PERSON]
        self.assertTrue(people)
        human = people[0]
        live = self.state.live_assertion_for(human.observation)
        self.assertEqual(live, human, "the person wins on precedence")
        machine = [a for a in self.state.assertions_about(human.observation)
                   if a.assertor is Assertor.FOUNDATION]
        self.assertTrue(machine, "and the machine's original is still there")

    def test_a_threshold_was_retuned_and_history_kept_its_old_version(self):
        retuned = [t for t in self.state.thresholds.values() if t.supersedes]
        self.assertTrue(retuned)
        fresh = retuned[0]
        old = fresh.supersedes
        historical = [a for a in self.state.assertions
                      if a.threshold_version == old]
        self.assertTrue(historical,
                        "assertions made under the old threshold still name it")


class TestDevices(Matrix):
    """§4.1, §4.2, §4.3."""

    def test_a_probe_drifting_across_the_season(self):
        drifting = [a for a in self.flagged()
                    if QualityFlag.SUSPECT in a.flags]
        self.assertTrue(drifting, "plot_probe_a drifts and its peer notices")

    def test_a_battery_declining(self):
        battery = self.obs_of("paddock_battery")
        self.assertTrue(battery)
        values = [o.result for o in sorted(battery, key=lambda o: o.measured_at)]
        self.assertLess(values[-1], values[0], "it declines over the season")

    def test_battery_and_signal_are_ordinary_datastreams_with_thresholds(self):
        """§4.3: not a side-channel warning bolted on."""
        for name in ("paddock_battery", "paddock_rssi", "beds_a_battery"):
            series = self.farm.series[name]
            self.assertIs(series.derived.kind, DatastreamKind.DERIVED)
            self.assertTrue(series.derived.thresholds)
            self.assertTrue(self.obs_of(name))

    def test_a_stale_datastream_whose_last_good_reading_is_not_flagged(self):
        """§4.2: staleness is a datastream state, never a reading flag."""
        self.assertNotIn("stale", {f.value for f in QualityFlag})
        series = self.farm.series["bed1_shallow"]
        rows = sorted(self.obs_of("bed1_shallow"), key=lambda o: o.measured_at)
        self.assertTrue(rows)
        health = P.datastream_health(series.derived, rows[-1].measured_at,
                                    rows[-1].measured_at + _dt.timedelta(days=2))
        self.assertIs(health, P.Health.STALE)
        last = self.state.live_assertion_for(rows[-1].id)
        if last is not None:
            self.assertNotIn("stale", {f.value for f in last.flags})

    def test_a_sensor_moved_and_reinstalled_with_dates(self):
        self.skipTest(
            "§4.1 describes a device record holding install location, depth and "
            "orientation with dates, a maintenance log and declared capabilities. "
            "There is no Device type in sdk/model.py, so there is nothing to move "
            "or reinstall. That is a spec-versus-code gap, not a farm gap.")


class TestTransport(Matrix):
    """§5.2, §5.3, §5.4."""

    def test_a_node_drained_a_three_day_outage_against_its_duty_cycle(self):
        late = [o for o in self.state.observations
                if (o.received_at - o.measured_at) > _dt.timedelta(days=1)]
        self.assertTrue(late)
        for node in self.farm.nodes.values():
            self.assertLess(node.duty.used(self.farm.world.when.timestamp()),
                            36.0, "and legally, inside the duty cycle")

    def test_two_nodes_with_opposite_drain_policies(self):
        orders = {n.policy.drain_order for n in self.farm.nodes.values()}
        self.assertEqual(orders, {"chronological", "fresh_first"})

    def test_an_evicted_reading_was_reported_as_a_count_and_logged_as_a_gap(self):
        evictions = [e for e in self.log
                     if e.kind == "gap" and "evicted_readings" in e.payload]
        self.assertTrue(evictions, "the outage overran the buffer")
        self.assertGreater(sum(e.payload["evicted_readings"] for e in evictions), 0)

    def test_gaps_in_the_sequence_were_logged_not_filled(self):
        gaps = [e for e in self.log
                if e.kind == "gap" and "missing_messages" in e.payload]
        self.assertTrue(gaps, "a lossy link should produce some")

    def test_a_batched_message_carried_several_readings_under_one_seq(self):
        batched = 0
        for node_label in self.farm.nodes:
            node = self.farm.nodes[node_label]
            per_seq = {}
            for obs in self.state.observations:
                if obs.node != f"{node.node_id:#x}" or obs.seq is None:
                    continue
                per_seq.setdefault((obs.boot, obs.seq), set()).add(obs.datastream)
            batched += sum(1 for streams in per_seq.values() if len(streams) > 1)
        self.assertGreater(batched, 0)

    def test_an_unconfirmed_link_was_released_by_cumulative_ack(self):
        unconfirmed = [label for label, link in self.farm.links.items()
                       if link.needs_cumulative_ack]
        self.assertTrue(unconfirmed)
        for label in unconfirmed:
            self.assertGreater(self.farm.links[label].stats.acks_sent, 0)
            self.assertEqual(self.farm.nodes[label].buffered, 0,
                             "nothing is left unsent at the end of the season")

    def test_an_undeliverable_frame_becomes_a_gap_rather_than_a_blockage(self):
        """A resend goes first by design, so a frame whose acknowledgement can never
        arrive would block every reading behind it. Bounded attempts turn it into a
        recorded gap (§5.4) — the node reported 316 readings stuck behind one such
        frame before `max_resends` existed."""
        for label, node in self.farm.nodes.items():
            self.assertEqual(node.buffered, 0, label)
            self.assertEqual(node.awaiting_resend, 0, label)
        evictions = [e for e in self.log
                     if e.kind == "gap" and "evicted_readings" in e.payload]
        self.assertTrue(evictions)

    def test_the_fleet_provably_fits_its_airtime_budget(self):
        for label, node in self.farm.nodes.items():
            self.assertTrue(node.feasible, f"{label}: {node.feasibility()}")


class TestStorage(Matrix):
    """§7.1, §7.3, §7.4, §7.5, §7.6."""

    def test_a_correction_as_a_compensating_event_with_the_original_readable(self):
        corrections = list(self.log.corrections())
        self.assertTrue(corrections)
        payload = corrections[0].payload
        self.assertIn("reason", payload)
        corrected = payload["corrects"]
        self.assertTrue(any(str(e.id) == corrected for e in self.log),
                        "the event it corrects is still in the log")

    def test_the_whole_season_replays_from_the_log_alone(self):
        """§7.1: current state is derived from the log."""
        replayed = P.state_from_log(self.log)
        self.assertEqual(len(replayed.observations),
                         len(self.state.observations))
        self.assertEqual(len(replayed.assertions), len(self.state.assertions))
        self.assertEqual(replayed.validate(), [])

    def test_an_offline_edit_conflict_resolved_by_hlc(self):
        self.skipTest(
            "§7.4's HLC exists in sdk/hlc.py and the log stamps every event with "
            "it, but there is no record type a second writer could edit "
            "concurrently and no conflict-event projection. Needs Q14 — which "
            "fields must never resolve silently — before it can be built.")

    def test_a_grant_issued_used_and_revoked(self):
        self.skipTest(
            "§7.6's sharing grants are not implemented. The scope and re-sharing "
            "semantics are Q16, and the erasure mechanism Q17.")

    def test_a_module_replayed_missed_events_from_its_cursor(self):
        self.skipTest(
            "§7.5's subscription API with a durable cursor is not implemented. "
            "Nothing structural blocks it; it is simply unbuilt.")


class TestInterop(Matrix):
    """§10, §7.6."""

    def test_sensorthings_serves_only_live_observations(self):
        import sensorthings as st
        service = st.Service(self.state, "https://harrow-bend.example")
        series = self.farm.series["bed3_shallow"]
        served = service.observations(series.derived.id)["value"]
        times = [o["phenomenonTime"] for o in served]
        self.assertEqual(len(times), len(set(times)),
                         "no duplicate phenomenonTime, even after recalibration")
        self.assertTrue(served)

    def test_sensorthings_was_validated_against_frost(self):
        """Done separately, with a container: docs/notes/frost-validation.md."""
        note = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "docs", "notes", "frost-validation.md")
        self.assertTrue(os.path.exists(note))
        with open(note) as handle:
            text = handle.read()
        self.assertIn("key parity", text)

    def test_a_full_export_round_trip_losing_nothing(self):
        self.skipTest(
            "§7.6's export in CSV, JSON and GeoJSON is not implemented. The codec "
            "round-trips every record exactly (sdk/test_project.py), so the "
            "encoding exists; the export surface does not.")


class TestCommandsAndApps(Matrix):
    def test_the_command_contract_exercised_in_sim(self):
        self.skipTest(
            "§6 is deferred from the first release by the scope cut in v0.1: "
            "observations only, with the command contract frozen after a season of "
            "field evidence. The matrix row stays so the omission is visible.")

    def test_all_three_acceptance_apps_run_against_the_farm(self):
        self.skipTest(
            "§15's three apps — irrigation controller, livestock water monitor, "
            "research logger — are not built. The farm has a home for each "
            "(beds with drip, the paddock troughs, the research plot's two "
            "probes), and the irrigation controller needs §6 first.")


class TestHistory(Matrix):
    def test_a_season_of_weather_drift_and_repairs_behind_the_trends(self):
        self.assertGreater(len(self.state.observations), 30_000)
        self.assertGreaterEqual(len(self.report.events), 8)
        self.assertGreater(len({o.measured_at.date()
                                for o in self.state.observations}), 10)

    def test_it_is_days_not_a_growing_season(self):
        """§9.2: reliability claims need a full growing season of FIELD data. This
        is twelve simulated days, and no amount of it converts into that."""
        self.assertLess(DAYS, 120.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestLabelsAndGeometry(unittest.TestCase):
    """The side table the SensorThings view is handed (§1 keeps names out of keys)."""

    @classmethod
    def setUpClass(cls):
        cls.farm = hb.build()
        hb.season(cls.farm, days=0.3)
        cls.labels = hb.labels(cls.farm)

    def test_every_series_is_named_on_both_its_datastreams(self):
        for name, series in self.farm.series.items():
            self.assertEqual(self.labels[series.derived.id]["name"], name)
            self.assertEqual(self.labels[series.raw.id]["name"], f"{name} (raw)")

    def test_raw_and_derived_are_never_given_the_same_label(self):
        """They are the pair whose confusion produced a 99.8% false-alarm rate, so a
        client showing them side by side must not be able to mistake one for the other.
        """
        for series in self.farm.series.values():
            self.assertNotEqual(self.labels[series.raw.id]["name"],
                                self.labels[series.derived.id]["name"])

    def test_every_feature_has_geometry(self):
        """A GIS client drops a row with no geometry silently, so a gap here is
        invisible rather than noisy."""
        for name, feature in self.farm.features.items():
            if feature.get("id") is None:
                continue
            geom = self.labels[feature["id"]].get("feature")
            self.assertIsNotNone(geom, name)
            self.assertEqual(geom["type"], "Point")
            self.assertEqual(len(geom["coordinates"]), 2)

    def test_no_two_features_share_a_point(self):
        """They all sat on null island until this test existed, which makes a map of
        six beds into one dot."""
        points = [tuple(v["feature"]["coordinates"])
                  for v in self.labels.values() if "feature" in v]
        self.assertEqual(len(points), len(set(points)))

    def test_the_farm_stays_on_the_prime_meridian(self):
        """The constellation's convention: nothing here may be mistaken for a real
        place, so the whole farm stays within a few hundred metres of 0,0."""
        for v in self.labels.values():
            if "feature" not in v:
                continue
            lon, lat = v["feature"]["coordinates"]
            self.assertLess(abs(lon), 0.01)
            self.assertLess(abs(lat), 0.01)

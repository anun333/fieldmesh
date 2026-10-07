#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The simulated link (spec v0.1 §5.2, §5.4)."""
from __future__ import annotations

import unittest

import link as lk


class TestProfile(unittest.TestCase):
    def test_probabilities_are_validated(self):
        for bad in ({"loss": 1.5}, {"duplicate": -0.1}, {"ack_loss": 2.0}):
            with self.assertRaises(ValueError):
                lk.LinkProfile(**bad)

    def test_delay_must_be_an_ordered_non_negative_range(self):
        with self.assertRaises(ValueError):
            lk.LinkProfile(delay_s=(5.0, 1.0))
        with self.assertRaises(ValueError):
            lk.LinkProfile(delay_s=(-1.0, 1.0))

    def test_an_unknown_confirmation_mode_is_refused(self):
        with self.assertRaises(ValueError):
            lk.LinkProfile(confirmation="hopeful")

    def test_only_a_frame_confirming_link_needs_no_cumulative_ack(self):
        """§5.2: Meshtastic and unconfirmed LoRaWAN return no receipt, so the
        gateway has to say what it holds."""
        self.assertTrue(lk.Link(lk.MESHTASTIC).needs_cumulative_ack)
        self.assertTrue(lk.Link(lk.LORAWAN_UNCONFIRMED).needs_cumulative_ack)
        self.assertFalse(lk.Link(lk.LORAWAN_CONFIRMED).needs_cumulative_ack)
        self.assertFalse(lk.Link(lk.WIRED).needs_cumulative_ack)


class TestIdealLink(unittest.TestCase):
    def test_everything_arrives_once_and_in_order(self):
        link = lk.Link(lk.WIRED)
        for i in range(20):
            link.send(bytes([i]), float(i))
        arrived = [d.payload[0] for d in link.deliver(100.0)]
        self.assertEqual(arrived, list(range(20)))
        self.assertEqual(link.loss_rate(), 0.0)

    def test_nothing_is_delivered_before_it_is_due(self):
        link = lk.Link(lk.LinkProfile(delay_s=(10.0, 10.0)))
        link.send(b"x", 0.0)
        self.assertEqual(link.deliver(5.0), [])
        self.assertEqual(len(link.deliver(10.0)), 1)


class TestImpairments(unittest.TestCase):
    def test_frames_are_lost_at_about_the_configured_rate(self):
        link = lk.Link(lk.LinkProfile(loss=0.2), seed=4)
        for i in range(1000):
            link.send(b"x", float(i))
        self.assertAlmostEqual(link.stats.lost / 1000, 0.2, delta=0.04)

    def test_frames_are_duplicated_and_the_copy_says_so(self):
        link = lk.Link(lk.LinkProfile(duplicate=1.0))
        link.send(b"x", 0.0)
        delivered = link.deliver(1.0)
        self.assertEqual(len(delivered), 2)
        self.assertIsNone(delivered[0].duplicate_of)
        self.assertIsNotNone(delivered[1].duplicate_of)

    def test_reordering_emerges_from_variable_delay(self):
        """No separate knob: give the delay a range and frames overtake, which is
        how reordering actually happens."""
        link = lk.Link(lk.LinkProfile(delay_s=(0.0, 30.0)), seed=3)
        for i in range(20):
            link.send(bytes([i]), float(i))
        arrived = [d.payload[0] for d in link.deliver(1000.0)]
        self.assertEqual(sorted(arrived), list(range(20)))
        self.assertNotEqual(arrived, sorted(arrived))

    def test_acknowledgements_can_be_lost(self):
        link = lk.Link(lk.LinkProfile(ack_loss=1.0))
        self.assertEqual(link.send_ack(5, 0.0), "lost")
        self.assertEqual(link.acks(100.0), [])
        self.assertEqual(link.stats.acks_lost, 1)

    def test_a_surviving_ack_arrives_after_its_delay(self):
        link = lk.Link(lk.LinkProfile(delay_s=(4.0, 4.0)))
        link.send_ack(7, 0.0)
        self.assertEqual(link.acks(2.0), [])
        self.assertEqual(link.acks(5.0), [7])


class TestOutage(unittest.TestCase):
    """Distinct from loss: nothing gets through and the node does not know."""

    def test_nothing_is_carried_during_an_outage(self):
        link = lk.Link(lk.WIRED)
        link.outage(10.0, 20.0)
        self.assertEqual(link.send(b"a", 5.0), "queued")
        self.assertEqual(link.send(b"b", 15.0), "outage")
        self.assertEqual(link.send(b"c", 25.0), "queued")
        self.assertEqual(link.stats.lost_to_outage, 1)

    def test_acks_do_not_get_through_either(self):
        link = lk.Link(lk.WIRED)
        link.outage(0.0, 10.0)
        self.assertEqual(link.send_ack(1, 5.0), "lost")

    def test_down_reports_the_window(self):
        link = lk.Link()
        link.outage(10.0, 20.0)
        self.assertFalse(link.down(9.9))
        self.assertTrue(link.down(10.0))
        self.assertTrue(link.down(19.9))
        self.assertFalse(link.down(20.0), "the window is half-open")

    def test_an_outage_cannot_end_before_it_starts(self):
        with self.assertRaises(ValueError):
            lk.Link().outage(20.0, 10.0)


class TestDeterminism(unittest.TestCase):
    def test_the_same_seed_impairs_identically(self):
        def run(seed):
            link = lk.Link(lk.MESHTASTIC, seed=seed)
            for i in range(200):
                link.send(bytes([i % 256]), float(i))
            return [d.payload[0] for d in link.deliver(10_000.0)]
        self.assertEqual(run(11), run(11))

    def test_a_different_seed_impairs_differently(self):
        def run(seed):
            link = lk.Link(lk.MESHTASTIC, seed=seed)
            for i in range(200):
                link.send(bytes([i % 256]), float(i))
            return [d.payload[0] for d in link.deliver(10_000.0)]
        self.assertNotEqual(run(11), run(12))


class TestPresets(unittest.TestCase):
    def test_every_preset_is_a_valid_profile(self):
        for name, profile in lk.PRESETS.items():
            with self.subTest(name):
                self.assertIsInstance(profile, lk.LinkProfile)
                lk.Link(profile)

    def test_meshtastic_is_the_harsher_case(self):
        """Which is why open-questions Q6 recommends building against it first."""
        self.assertGreater(lk.MESHTASTIC.loss, lk.LORAWAN_CONFIRMED.loss)
        self.assertGreater(lk.MESHTASTIC.ack_loss, lk.LORAWAN_CONFIRMED.ack_loss)
        self.assertGreater(lk.MESHTASTIC.delay_s[1], lk.LORAWAN_CONFIRMED.delay_s[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)

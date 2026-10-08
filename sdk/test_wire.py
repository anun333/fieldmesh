#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The wire message (spec v0.1 §5.2, §5.3, §2)."""
from __future__ import annotations

import unittest

import cbor2
import wire


def _readings(n, start=231):
    return [wire.Reading(i + 1, i * 300, start + i) for i in range(n)]


class TestRoundTrip(unittest.TestCase):
    def test_a_frame_survives_encoding(self):
        m = wire.Message(boot=4, seq=10, base_age=95, node=0x4F2A17B3,
                         readings=_readings(6), dropped=3)
        self.assertEqual(wire.decode(wire.encode(m)), m)

    def test_a_node_id_may_be_absent(self):
        """§5.2: on LoRaWAN the session identifies the device, so the bytes are
        waste. The slot stays, holding null, so decoding cannot misread a frame."""
        m = wire.Message(boot=1, seq=0, base_age=0, node=None,
                         readings=_readings(2))
        self.assertIsNone(wire.decode(wire.encode(m)).node)
        with_id = wire.Message(boot=1, seq=0, base_age=0, node=0x4F2A17B3,
                               readings=_readings(2))
        self.assertLess(len(wire.encode(m)), len(wire.encode(with_id)))

    def test_values_are_not_scaled_on_the_wire(self):
        """§5.1: the node applies nothing, so 231 arrives as 231."""
        m = wire.Message(boot=1, seq=0, base_age=0, readings=[wire.Reading(1, 0, 231)],
                         node=1)
        self.assertEqual(wire.decode(wire.encode(m)).readings[0].value, 231)

    def test_negative_values_survive(self):
        m = wire.Message(boot=1, seq=0, base_age=0, node=1,
                         readings=[wire.Reading(1, 0, -175)])
        self.assertEqual(wire.decode(wire.encode(m)).readings[0].value, -175)


class TestRefusals(unittest.TestCase):
    """§5.4 forbids guessing, so every malformed frame is a clean refusal."""

    def test_truncated_bytes_do_not_parse(self):
        """A half-written frame — the ordinary case after a radio cuts out."""
        with self.assertRaisesRegex(wire.WireError, "not CBOR"):
            wire.decode(b"\x87\x01")          # array of 7, one item present

    def test_a_lone_break_code_is_not_cbor_whatever_the_library_version(self):
        """`\xff` outside an indefinite-length item is not a data item (RFC 8949
        §3.2.1). This test used to claim it was "a valid CBOR break marker" that parsed
        and then failed the shape check — true of cbor2 5's leniency, false of the
        standard, and caught when CI installed cbor2 6."""
        with self.assertRaisesRegex(wire.WireError, "not CBOR"):
            wire.decode(b"\xff")

    def test_parseable_cbor_that_is_not_a_frame_is_refused_on_shape(self):
        """The other refusal path, with CBOR that really does parse. Neither guesses."""
        with self.assertRaisesRegex(wire.WireError, "expected 7 fields"):
            wire.decode(cbor2.dumps("not a frame"))

    def test_wrong_field_count(self):
        with self.assertRaisesRegex(wire.WireError, "expected 7 fields"):
            wire.decode(cbor2.dumps([1, None, 2, 3]))

    def test_not_an_array(self):
        with self.assertRaisesRegex(wire.WireError, "expected 7 fields"):
            wire.decode(cbor2.dumps({"v": 1}))

    def test_an_unknown_version_is_refused_not_misparsed(self):
        """§12 puts the version in every packet precisely for this."""
        blob = cbor2.dumps([99, 1, 2, 3, 4, 0, [1, 0, 5]])
        with self.assertRaisesRegex(wire.WireError, "unsupported wire version"):
            wire.decode(blob)

    def test_a_ragged_reading_list(self):
        blob = cbor2.dumps([wire.VERSION, 1, 2, 3, 4, 0, [1, 0, 5, 2]])
        with self.assertRaisesRegex(wire.WireError, "triple"):
            wire.decode(blob)

    def test_no_readings(self):
        blob = cbor2.dumps([wire.VERSION, 1, 2, 3, 4, 0, []])
        with self.assertRaises(wire.WireError):
            wire.decode(blob)

    def test_seq_is_uint16(self):
        with self.assertRaisesRegex(wire.WireError, "uint16"):
            wire.Message(boot=1, seq=0x10000, base_age=0, node=1,
                         readings=_readings(1))

    def test_channel_is_one_byte(self):
        with self.assertRaisesRegex(wire.WireError, "one byte"):
            wire.Reading(256, 0, 1)

    def test_age_delta_is_not_negative(self):
        with self.assertRaises(wire.WireError):
            wire.Reading(1, -1, 1)


class TestPacking(unittest.TestCase):
    """§5.2: batch size comes from the current payload budget, never build time."""

    def test_packs_what_fits_and_says_how_many(self):
        payload, count = wire.pack(_readings(12), boot=4, seq=10, base_age=95,
                                   max_payload=51, node=0x4F2A17B3)
        self.assertLessEqual(len(payload), 51)
        self.assertEqual(count, 6)
        self.assertEqual(len(wire.decode(payload).readings), 6)

    def test_a_larger_budget_takes_more(self):
        _, small = wire.pack(_readings(12), boot=4, seq=10, base_age=95,
                             max_payload=51, node=1)
        _, large = wire.pack(_readings(12), boot=4, seq=10, base_age=95,
                             max_payload=115, node=1)
        self.assertGreater(large, small)

    def test_a_shrinking_budget_costs_latency_not_data(self):
        """The caller keeps the remainder buffered (§5.3)."""
        readings = _readings(12)
        _, count = wire.pack(readings, boot=4, seq=10, base_age=95,
                             max_payload=30, node=1)
        self.assertGreater(count, 0)
        self.assertLess(count, 12)

    def test_a_budget_too_small_for_one_reading_is_a_configuration_error(self):
        with self.assertRaisesRegex(wire.WireError, "link-driver"):
            wire.pack(_readings(1), boot=4, seq=10, base_age=95,
                      max_payload=4, node=1)

    def test_packing_nothing_is_refused(self):
        with self.assertRaises(wire.WireError):
            wire.pack([], boot=1, seq=0, base_age=0, max_payload=51)


class TestRestamp(unittest.TestCase):
    """§2: ages are stamped at TRANSMIT, not at sample time.

    Stamping at sample time and then buffering for three days yields a
    `measured_at` wrong by the dwell time — the easiest way to corrupt a dataset
    silently, and the one a driver is most likely to get wrong.
    """

    def test_base_age_is_the_youngest_reading(self):
        base, out = wire.restamp(_readings(3), now_s=1000.0,
                                 sampled_at_s=[700.0, 800.0, 900.0])
        self.assertEqual(base, 100)
        self.assertEqual([r.age_delta for r in out], [200, 100, 0])

    def test_a_buffered_batch_restamps_larger_ages(self):
        samples = [700.0, 800.0, 900.0]
        fresh, _ = wire.restamp(_readings(3), now_s=1000.0, sampled_at_s=samples)
        later, _ = wire.restamp(_readings(3), now_s=1000.0 + 3 * 86400,
                                sampled_at_s=samples)
        self.assertEqual(fresh, 100)
        self.assertEqual(later, 100 + 3 * 86400,
                         "three days in a buffer must show up as three days of age")

    def test_values_and_channels_are_untouched(self):
        _, out = wire.restamp(_readings(3), now_s=1000.0,
                              sampled_at_s=[700.0, 800.0, 900.0])
        self.assertEqual([r.value for r in out], [231, 232, 233])
        self.assertEqual([r.channel for r in out], [1, 2, 3])

    def test_a_reading_cannot_be_sampled_in_the_future(self):
        with self.assertRaises(wire.WireError):
            wire.restamp(_readings(1), now_s=100.0, sampled_at_s=[200.0])

    def test_one_sample_time_per_reading(self):
        with self.assertRaises(wire.WireError):
            wire.restamp(_readings(3), now_s=100.0, sampled_at_s=[50.0])


class TestSchema(unittest.TestCase):
    def test_the_cddl_schema_travels_with_the_code(self):
        """Positional encoding makes the schema load-bearing, so it is not allowed
        to live only in the spec document."""
        for field_name in ("version", "node", "boot", "seq", "base-age",
                           "dropped", "readings"):
            self.assertIn(field_name, wire.CDDL)


if __name__ == "__main__":
    unittest.main(verbosity=2)

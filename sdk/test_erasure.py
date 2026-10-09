#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Erasure by key destruction (§7.3; Q17)."""
from __future__ import annotations

import copy
import os
import tempfile
import unittest

try:
    import erasure as E
    import cryptography  # noqa: F401
except ImportError:                       # pragma: no cover - the dependency is optional
    E = None

import fixtures as fx
import log as L
import project as P
from ids import uuid7
from model import MaintenanceAction, MaintenanceEvent


@unittest.skipIf(E is None, "needs the cryptography package")
class ErasureTest(unittest.TestCase):
    def setUp(self):
        self.ring = E.KeyRing.new()
        self.ana, self.ben = uuid7(), uuid7()

    def test_a_sealed_note_lives_in_the_log_and_reads_back(self):
        note = self.ring.seal(self.ana, "Ana Ruiz cleaned the probe; cable nicked")
        event = MaintenanceEvent(id=uuid7(), device=uuid7(), at=fx.at(0),
                                 action=MaintenanceAction.CLEANED, performed_by=self.ana,
                                 note=note)
        log = L.Log()
        log.append_record(event)
        stored = P.state_from_log(log).maintenance[0].note
        self.assertNotIn("Ana", stored)
        self.assertEqual(self.ring.reveal(stored), "Ana Ruiz cleaned the probe; cable nicked")

    def test_erasing_one_person_leaves_the_others(self):
        a, b = self.ring.seal(self.ana, "Ana"), self.ring.seal(self.ben, "Ben")
        log = L.Log()
        E.erase(log, self.ring, self.ana, reason="request under data protection law")
        self.assertEqual(self.ring.reveal(a), E.ERASED)
        self.assertEqual(self.ring.reveal(b), "Ben")
        self.assertEqual([e.kind for e in log.events], [E.ERASURE])
        self.assertNotIn("Ana", str(log.events[0].payload))

    def test_an_old_backup_of_the_ring_is_useless_once_the_old_farm_key_is_gone(self):
        sealed = self.ring.seal(self.ana, "Ana")
        backup = copy.deepcopy(self.ring.wrapped)          # backed up with the log
        old_key = self.ring.shred(self.ana)
        # The backup, opened with the farm key that exists now:
        restored = E.KeyRing(farm_key=self.ring.farm_key, wrapped=backup)
        with self.assertRaises(E.ErasureError):
            restored.reveal(sealed)
        # Which is why the old key must be destroyed: with it, the backup still reads.
        self.assertEqual(E.KeyRing(farm_key=old_key, wrapped=backup).reveal(sealed), "Ana")

    def test_a_value_cannot_be_moved_to_another_persons_name(self):
        sealed = self.ring.seal(self.ana, "Ana")
        self.ring.seal(self.ben, "Ben")
        forged = sealed.replace(str(self.ana), str(self.ben))
        with self.assertRaises(E.ErasureError):
            self.ring.reveal(forged)

    def test_the_recovery_code_restores_the_ring(self):
        sealed = self.ring.seal(self.ana, "Ana")
        code = self.ring.recovery_code()
        again = E.KeyRing.from_recovery_code(code, self.ring.wrapped)
        self.assertEqual(again.reveal(sealed), "Ana")

    def test_the_farm_key_is_saved_apart_and_private(self):
        with tempfile.TemporaryDirectory() as d:
            ring, key = os.path.join(d, "ring.json"), os.path.join(d, "farm.key")
            self.ring.seal(self.ana, "Ana")
            self.ring.save(ring, key)
            self.assertEqual(os.stat(key).st_mode & 0o777, 0o600)
            self.assertNotIn(self.ring.farm_key.hex(), open(ring).read())
            self.assertEqual(E.KeyRing.load(ring, key).wrapped, self.ring.wrapped)

    def test_plain_values_pass_through(self):
        self.assertEqual(self.ring.reveal("north bed"), "north bed")
        self.assertIsNone(self.ring.reveal(None))


if __name__ == "__main__":
    unittest.main()

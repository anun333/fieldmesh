#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The farm's records and their offline edits (spec v0.1 §7.4; Q7, Q14)."""
from __future__ import annotations

import datetime as _dt
import os
import tempfile
import unittest

import codec
import edits as E
from hlc import Hlc
from ids import uuid7
from log import Log
from project import state_from_log
from records import (Animal, AnimalGroup, AnimalTreatment, ConflictNotice, HarvestLot,
                     InputApplication, Land, LandKind, Quantity, RecordEdit)

UTC = _dt.timezone.utc
T0 = _dt.datetime(2026, 6, 1, 8, tzinfo=UTC)
SITE = uuid7()
HOUR = 3_600_000


def at(days=0.0, hours=0.0):
    return T0 + _dt.timedelta(days=days, hours=hours)


def square(lon=-86.59, lat=35.06, d=0.0005):
    return {"type": "Polygon", "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d],
                                                [lon, lat + d], [lon, lat]]]}


class Clock:
    def __init__(self, ms):
        self.ms = ms

    def __call__(self):
        return self.ms


class Phone:
    """A replica with its own clock, which may be wrong."""

    def __init__(self, ms=1_780_000_000_000):
        self.clock = Clock(ms)
        self.log = Log(hlc=Hlc(clock=self.clock))

    def tick(self, ms=1000):
        self.clock.ms += ms

    def state(self):
        return E.project(self.log)


def sync(*phones):
    """Every phone learns every event any of them has — the evening sync."""
    for a in phones:
        for b in phones:
            if a is not b:
                for ev in a.log.events:
                    b.log.receive(ev)


def lot(**kw):
    base = dict(id=uuid7(), site=SITE, harvested_at=at(), land=[uuid7()], crop="tomato",
                quantity=Quantity(120, "kg"), lot="HB-0601-1")
    base.update(kw)
    return HarvestLot(**base)


class TestRecords(unittest.TestCase):
    def test_a_boundary_is_geojson_longitude_first_and_closed(self):
        Land(uuid7(), SITE, LandKind.BED, boundary=square())
        open_ring = square()
        open_ring["coordinates"][0].pop()
        with self.assertRaisesRegex(ValueError, "close"):
            Land(uuid7(), SITE, "bed", boundary=open_ring)
        swapped = {"type": "Polygon", "coordinates": [[[35, -186], [35.1, -186], [35.1, -186.1],
                                                       [35, -186]]]}
        with self.assertRaisesRegex(ValueError, "longitude first"):
            Land(uuid7(), SITE, "bed", boundary=swapped)
        with self.assertRaisesRegex(ValueError, "Polygon"):
            Land(uuid7(), SITE, "bed", boundary={"type": "Point", "coordinates": [0, 0]})

    def test_quantities_have_a_ucum_unit_and_are_not_negative(self):
        with self.assertRaises(ValueError):
            Quantity(1, "kilograms per bed")
        with self.assertRaises(ValueError):
            Quantity(-1, "kg")
        with self.assertRaises(TypeError):
            Quantity(True, "kg")

    def test_withdrawal_is_for_a_known_commodity_in_whole_days(self):
        t = AnimalTreatment(uuid7(), SITE, at(), {uuid7()}, "oxytetracycline",
                            Quantity(10, "mL"), {"meat": 28, "milk": 4})
        self.assertEqual(t.withdrawal_until("milk"), at(4))
        self.assertIsNone(t.withdrawal_until("eggs"))
        with self.assertRaises(ValueError):
            AnimalTreatment(uuid7(), SITE, at(), set(), "x", Quantity(1, "mL"), {"wool": 3})
        with self.assertRaises(ValueError):
            AnimalTreatment(uuid7(), SITE, at(), set(), "x", Quantity(1, "mL"), {"meat": 2.5})

    def test_an_edit_never_touches_identity_and_never_replaces_a_set(self):
        h = lot()
        with self.assertRaisesRegex(ValueError, "identity"):
            RecordEdit(uuid7(), h.id, "HarvestLot", [h.id], at(), set={"site": uuid7()})
        with self.assertRaisesRegex(ValueError, "set-like"):
            RecordEdit(uuid7(), h.id, "HarvestLot", [h.id], at(), set={"tags": frozenset()})
        with self.assertRaisesRegex(ValueError, "seen"):
            RecordEdit(uuid7(), h.id, "HarvestLot", [], at(), set={"note": "x"})
        with self.assertRaisesRegex(ValueError, "changes something"):
            RecordEdit(uuid7(), h.id, "HarvestLot", [h.id], at(), add={"tags": []})
        with self.assertRaisesRegex(ValueError, "no field"):
            RecordEdit(uuid7(), h.id, "HarvestLot", [h.id], at(), set={"weight": 3})

    def test_every_record_round_trips_through_the_codec(self):
        land = Land(uuid7(), SITE, "bed", boundary=square(), parent=uuid7(), tags={"drip"})
        cow = Animal(uuid7(), SITE, "cattle", tag="114", born=at(-400), sex="female")
        herd = AnimalGroup(uuid7(), SITE, members={cow.id})
        spray = InputApplication(uuid7(), SITE, at(), [land.id], "spinosad",
                                 Quantity(0.4, "L/har"), area=Quantity(0.02, "har"),
                                 registration="62719-314", preharvest_interval_days=1,
                                 reentry_interval_h=4, applied_by=uuid7())
        dose = AnimalTreatment(uuid7(), SITE, at(), {cow.id}, "oxytetracycline",
                               Quantity(10, "mL"), {"meat": 28})
        h = lot(tags={"washed"})
        e = RecordEdit(uuid7(), h.id, "HarvestLot", [h.id], at(1),
                       set={"quantity": Quantity(112, "kg"), "harvested_at": at(0.1)},
                       add={"tags": {"organic"}}, remove={"tags": {"washed"}})
        n = ConflictNotice(uuid7(), h.id, "HarvestLot", "quantity", [uuid7(), uuid7()], at(1))
        for rec in (land, cow, herd, spray, dose, h, e, n):
            self.assertEqual(codec.load(codec.dump(rec)), rec, type(rec).__name__)


class TestEdits(unittest.TestCase):
    def test_a_later_edit_wins_though_its_phone_clock_is_hours_behind(self):
        """§7.4's reason for HLC. The second writer saw the first edit; its wall clock
        says it wrote six hours earlier; it still follows the first."""
        hub, fast, slow = Phone(), Phone(), Phone()
        fast.clock.ms += 6 * HOUR
        h = lot()
        E.create(hub.log, h)
        sync(hub, fast, slow)
        E.edit(fast.log, h.id, at=at(0, 6), set={"note": "two crates bruised"})
        sync(fast, hub, slow)
        E.edit(slow.log, h.id, at=at(0, 0.5), set={"note": "one crate bruised; recounted"})
        sync(hub, fast, slow)
        for phone in (hub, fast, slow):
            s = phone.state()
            self.assertEqual(s.get(h.id).note, "one crate bruised; recounted")
            self.assertEqual(s.conflicts(), [])
            self.assertEqual(s.edited_on_two_devices(h.id), frozenset())

    def test_concurrent_edits_to_a_protected_field_keep_both_and_ask(self):
        hub, a, b = Phone(), Phone(), Phone()
        h = lot()
        E.create(hub.log, h)
        sync(hub, a, b)
        E.edit(a.log, h.id, at=at(0, 1), set={"quantity": Quantity(118, "kg")})
        E.edit(b.log, h.id, at=at(0, 1), set={"quantity": Quantity(121, "kg")})
        sync(hub, a, b)
        s = hub.state()
        [c] = s.conflicts()
        self.assertEqual((c.field, c.noticed), ("quantity", False))
        self.assertEqual({v.value for _, v in c.candidates}, {118, 121})
        self.assertEqual({q.value for q in s.values(h.id, "quantity")}, {118, 121})
        self.assertEqual(s.conflicted_fields(h.id), frozenset({"quantity"}))

        written = E.notice_conflicts(hub.log, at=at(0, 2))
        self.assertEqual(len(written), 1)
        self.assertEqual(E.notice_conflicts(hub.log, at=at(0, 3)), [])
        self.assertTrue(hub.state().conflicts()[0].noticed)

        with self.assertRaisesRegex(ValueError, "why"):
            E.resolve(hub.log, h.id, "quantity", Quantity(121, "kg"), at=at(0, 4), reason=" ")
        E.resolve(hub.log, h.id, "quantity", Quantity(121, "kg"), at=at(0, 4),
                  reason="re-weighed the crates")
        sync(hub, a, b)
        for phone in (hub, a, b):
            s = phone.state()
            self.assertEqual(s.conflicts(), [])
            self.assertEqual(s.get(h.id).quantity, Quantity(121, "kg"))
        with self.assertRaisesRegex(ValueError, "not in conflict"):
            E.resolve(hub.log, h.id, "quantity", Quantity(1, "kg"), at=at(1), reason="x")

    def test_two_replicas_noticing_one_conflict_count_once(self):
        a, b = Phone(), Phone()
        h = lot()
        E.create(a.log, h)
        sync(a, b)
        E.edit(a.log, h.id, at=at(), set={"lot": "HB-0601-2"})
        E.edit(b.log, h.id, at=at(), set={"lot": "HB-0601-3"})
        sync(a, b)
        E.notice_conflicts(a.log, at=at(0, 1))
        E.notice_conflicts(b.log, at=at(0, 1))
        sync(a, b)
        s = a.state()
        self.assertEqual(len(s.notices), 1)
        self.assertEqual(len(s.conflicts()), 1)
        self.assertEqual(E.notice_conflicts(a.log, at=at(0, 2)), [])

    def test_agreeing_concurrent_edits_are_not_a_conflict(self):
        a, b = Phone(), Phone()
        h = lot()
        E.create(a.log, h)
        sync(a, b)
        E.edit(a.log, h.id, at=at(), set={"quantity": Quantity(110, "kg")})
        E.edit(b.log, h.id, at=at(), set={"quantity": Quantity(110.0, "kg")})
        sync(a, b)
        self.assertEqual(a.state().conflicts(), [])

    def test_an_unprotected_field_goes_to_hlc_order_and_is_marked(self):
        a, b = Phone(), Phone()
        b.clock.ms += 5_000
        h = lot()
        E.create(a.log, h)
        sync(a, b)
        E.edit(a.log, h.id, at=at(), set={"note": "from a"})
        E.edit(b.log, h.id, at=at(), set={"note": "from b"})
        sync(a, b)
        s = a.state()
        self.assertEqual(s.get(h.id).note, "from b")
        self.assertEqual(s.conflicts(), [])
        self.assertEqual(s.edited_on_two_devices(h.id), frozenset({"note"}))

    def test_sets_merge_by_union_and_a_concurrent_add_survives_a_remove(self):
        a, b = Phone(), Phone()
        cow, calf, heifer = uuid7(), uuid7(), uuid7()
        herd = AnimalGroup(uuid7(), SITE, members={cow, heifer})
        E.create(a.log, herd)
        sync(a, b)
        E.edit(a.log, herd.id, at=at(), add={"members": {calf}})
        E.edit(b.log, herd.id, at=at(), remove={"members": {heifer}})
        sync(a, b)
        self.assertEqual(a.state().get(herd.id).members, frozenset({cow, calf}))
        # One phone takes the calf out while the other, not having seen that, adds it
        # again: it stays.
        E.edit(a.log, herd.id, at=at(1), remove={"members": {calf}})
        E.edit(b.log, herd.id, at=at(1), add={"members": {calf}})
        sync(a, b)
        self.assertIn(calf, a.state().get(herd.id).members)
        # Taken out by a phone that has seen every addition: gone.
        E.edit(a.log, herd.id, at=at(2), remove={"members": {calf}})
        self.assertNotIn(calf, a.state().get(herd.id).members)

    def test_every_replica_projects_the_same_whatever_order_it_learned(self):
        a, b, c = Phone(), Phone(), Phone()
        h = lot()
        E.create(a.log, h)
        sync(a, b, c)
        E.edit(a.log, h.id, at=at(), set={"quantity": Quantity(100, "kg"), "note": "a"},
               add={"tags": {"x"}})
        E.edit(b.log, h.id, at=at(), set={"quantity": Quantity(101, "kg"), "note": "b"},
               remove={"tags": {"x"}})
        E.edit(c.log, h.id, at=at(), set={"crop": "pepper"})
        # c learns a then b; a learns c then b; b learns a then c.
        for src in (a, b):
            for ev in src.log.events:
                c.log.receive(ev)
        for src in (c, b):
            for ev in src.log.events:
                a.log.receive(ev)
        for src in (a, c):
            for ev in src.log.events:
                b.log.receive(ev)
        states = [p.state() for p in (a, b, c)]
        for s in states[1:]:
            self.assertEqual(s.get(h.id), states[0].get(h.id))
            self.assertEqual([x.key for x in s.conflicts()],
                             [x.key for x in states[0].conflicts()])
        self.assertEqual(states[0].get(h.id).crop, "pepper")

    def test_an_edit_that_arrives_before_its_record_waits_for_it(self):
        a, b = Phone(), Phone()
        h = lot()
        created = E.create(a.log, h)
        edit = E.edit(a.log, h.id, at=at(), set={"note": "late"})
        b.log.receive(edit)
        s = b.state()
        self.assertIsNone(s.get(h.id))
        self.assertTrue(any("does not have" in p for p in s.problems))
        b.log.receive(created)
        self.assertEqual(b.state().get(h.id).note, "late")
        self.assertEqual(b.state().problems, [])

    def test_an_invalid_edit_fails_before_the_log_is_touched(self):
        a = Phone()
        land = Land(uuid7(), SITE, "bed", boundary=square())
        E.create(a.log, land)
        before = len(a.log)
        with self.assertRaises(ValueError):
            E.edit(a.log, land.id, at=at(), set={"boundary": {"type": "Polygon",
                                                              "coordinates": [[[0, 0]]]}})
        with self.assertRaises(KeyError):
            E.edit(a.log, uuid7(), at=at(), set={"note": "x"})
        self.assertEqual(len(a.log), before)

    def test_a_replayed_file_log_projects_identically(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "farm.jsonl")
            lg = Log(path)
            h = lot()
            E.create(lg, h)
            E.edit(lg, h.id, at=at(), set={"quantity": Quantity(99, "kg")}, add={"tags": {"x"}})
            again = E.project(Log(path))
            self.assertEqual(again.get(h.id), E.project(lg).get(h.id))

    def test_the_sensing_state_ignores_records(self):
        a = Phone()
        E.create(a.log, lot())
        state_from_log(a.log)


class TestWhatTheRecordsAreFor(unittest.TestCase):
    def setUp(self):
        self.a, self.b = Phone(), Phone()
        self.cow, self.steer = uuid7(), uuid7()
        self.t = AnimalTreatment(uuid7(), SITE, at(), {self.cow}, "oxytetracycline",
                                 Quantity(10, "mL"), {"meat": 28, "milk": 4})
        E.create(self.a.log, self.t)
        sync(self.a, self.b)

    def test_a_withdrawal_disagreement_takes_the_longer(self):
        E.edit(self.a.log, self.t.id, at=at(), set={"withdrawal_days": {"meat": 21, "milk": 4}})
        E.edit(self.b.log, self.t.id, at=at(), set={"withdrawal_days": {"meat": 35, "milk": 4}})
        sync(self.a, self.b)
        s = self.a.state()
        self.assertEqual(s.withdrawal_until(self.cow, "meat"), at(35))
        self.assertTrue(s.under_withdrawal(self.cow, "meat", at(30)))
        self.assertFalse(s.under_withdrawal(self.cow, "milk", at(5)))
        self.assertIsNone(s.withdrawal_until(self.steer, "meat"))

    def test_a_void_in_conflict_is_not_a_void_yet(self):
        E.edit(self.a.log, self.t.id, at=at(), set={"void": True}, reason="entered twice")
        E.edit(self.b.log, self.t.id, at=at(), set={"dose": Quantity(12, "mL")})
        sync(self.a, self.b)
        s = self.a.state()
        [c] = s.conflicts(self.t.id)
        self.assertEqual(c.field, "void")
        self.assertEqual(s.withdrawal_until(self.cow, "meat"), at(28))
        E.resolve(self.a.log, self.t.id, "void", True, at=at(2), reason="duplicate entry")
        self.assertEqual(self.a.state().conflicts(), [])
        self.assertIsNone(self.a.state().withdrawal_until(self.cow, "meat"))

    def test_a_void_made_after_seeing_the_correction_is_just_a_void(self):
        E.edit(self.b.log, self.t.id, at=at(), set={"dose": Quantity(12, "mL")})
        sync(self.a, self.b)
        E.edit(self.a.log, self.t.id, at=at(1), set={"void": True}, reason="wrong cow")
        s = self.a.state()
        self.assertEqual(s.conflicts(), [])
        self.assertIsNone(s.withdrawal_until(self.cow, "meat"))

    def test_an_animal_added_to_a_treatment_is_under_its_withdrawal(self):
        E.edit(self.b.log, self.t.id, at=at(), add={"animals": {self.steer}})
        sync(self.a, self.b)
        self.assertEqual(self.a.state().withdrawal_until(self.steer, "meat"), at(28))

    def test_a_harvest_inside_a_preharvest_interval_is_found_and_traced(self):
        bed, other = uuid7(), uuid7()
        spray = InputApplication(uuid7(), SITE, at(), [bed], "spinosad",
                                 Quantity(0.4, "L/har"), preharvest_interval_days=3,
                                 reentry_interval_h=4)
        early = lot(land=[bed], harvested_at=at(0, 2))
        late = lot(land=[bed], harvested_at=at(5))
        elsewhere = lot(land=[other], harvested_at=at(0, 2))
        for rec in (spray, early, late, elsewhere):
            E.create(self.a.log, rec)
        s = self.a.state()
        breaches = {(b.lot, b.interval) for b in s.harvest_problems()}
        self.assertEqual(breaches, {(early.id, "preharvest"), (early.id, "reentry")})
        self.assertEqual(s.trace(late.id), [spray])
        self.assertEqual(s.trace(elsewhere.id), [])

    def test_a_disagreement_over_when_a_spray_went_on_cannot_hide_a_breach(self):
        bed = uuid7()
        spray = InputApplication(uuid7(), SITE, at(), [bed], "spinosad",
                                 Quantity(0.4, "L/har"), preharvest_interval_days=3)
        h = lot(land=[bed], harvested_at=at(4))
        E.create(self.a.log, spray)
        E.create(self.a.log, h)
        sync(self.a, self.b)
        self.assertEqual(self.a.state().harvest_problems(), [])
        E.edit(self.a.log, spray.id, at=at(), set={"applied_at": at(-1)})
        E.edit(self.b.log, spray.id, at=at(), set={"applied_at": at(2)})
        sync(self.a, self.b)
        [breach] = self.a.state().harvest_problems()
        self.assertEqual(breach.applied_at, at(2))


if __name__ == "__main__":
    unittest.main()

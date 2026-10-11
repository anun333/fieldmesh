#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Sharing grants (§7.6; Q16)."""
from __future__ import annotations

import datetime as _dt
import unittest

import codec
import fixtures as fx
import log as L
import project as P
import sharing as SH
from ids import uuid7
from model import Grant, GrantRevocation


def _grant(ds, issued_min, **kw):
    return Grant(id=uuid7(), grantee="state university soil lab", datastreams=(ds.id,),
                 purpose="drought study", issued_at=fx.at(issued_min), **kw)


class Q16Test(unittest.TestCase):
    def setUp(self):
        self.ds = fx.raw_datastream()
        self.before = fx.observation(self.ds, result=0.21, measured_at=fx.at(0), seq=0)
        self.after = fx.observation(self.ds, result=0.22, measured_at=fx.at(60), seq=1)
        # received_at drives it: the second reading arrives after the grant.
        self.before = type(self.before)(**{**_fields(self.before), "received_at": fx.at(5)})
        self.after = type(self.after)(**{**_fields(self.after), "received_at": fx.at(65)})

    def state(self, *records):
        log = L.Log()
        for r in (self.ds, self.before, self.after, *records):
            log.append_record(r)
        return P.state_from_log(log)

    def test_by_default_only_what_had_arrived(self):
        g = _grant(self.ds, 30)
        s = self.state(g)
        self.assertEqual(SH.shared(s, g.grantee, fx.at(120)), [self.before])

    def test_future_data_must_be_asked_for_and_must_end(self):
        with self.assertRaises(ValueError):
            _grant(self.ds, 30, includes_future=True)
        g = _grant(self.ds, 30, includes_future=True, until=fx.at(60 * 24 * 90))
        s = self.state(g)
        self.assertEqual(SH.shared(s, g.grantee, fx.at(120)), [self.before, self.after])
        self.assertEqual(SH.shared(s, g.grantee, fx.at(60 * 24 * 91)), [], "it ended")

    def test_revocation_stops_access_from_then_on(self):
        g = _grant(self.ds, 30)
        s = self.state(g, GrantRevocation(id=uuid7(), grant=g.id, at=fx.at(100)))
        self.assertTrue(SH.may_read(s, g.grantee, self.before, fx.at(90)))
        self.assertFalse(SH.may_read(s, g.grantee, self.before, fx.at(100)))

    def test_the_view_holds_what_the_grant_covers_and_nothing_else(self):
        """A service answers a grantee from this view, so what is not in it does not
        exist for them: the other series, the reading that arrived after the grant,
        and its quality verdict."""
        other = fx.raw_datastream()
        hidden = fx.observation(other, result=0.3, seq=9)
        g = _grant(self.ds, 30)
        verdict = fx.assertion(self.before.id, asserted_at=fx.at(10))
        late = fx.assertion(self.after.id, asserted_at=fx.at(70))
        s = self.state(g, other, hidden, verdict, late)
        v = SH.view(s, g.grantee, fx.at(120))
        self.assertEqual(list(v.datastreams), [self.ds.id])
        self.assertEqual(v.observations, [self.before])
        self.assertEqual(v.assertions, [verdict])
        self.assertEqual(SH.view(s, "a buyer", fx.at(120)).observations, [])
        self.assertEqual(list(SH.view(s, "a buyer", fx.at(120)).datastreams), [])

    def test_another_grantee_sees_nothing(self):
        s = self.state(_grant(self.ds, 30))
        self.assertEqual(SH.shared(s, "a buyer", fx.at(120)), [])

    def test_round_trips_and_validates(self):
        g = _grant(self.ds, 30, includes_future=True, until=fx.at(9000), reshare=True)
        self.assertEqual(codec.load(codec.dump(g)), g)
        s = self.state(g, GrantRevocation(id=uuid7(), grant=uuid7(), at=fx.at(100)))
        self.assertTrue(any("unknown grant" in p for p in s.validate()))

    def test_the_farmer_is_told_what_revoking_cannot_do(self):
        text = SH.describe(_grant(self.ds, 30))
        self.assertIn("and none after", text)
        self.assertIn("cannot take back", text)


def _fields(obs):
    return {f: getattr(obs, f) for f in obs.__slots__}


if __name__ == "__main__":
    unittest.main()

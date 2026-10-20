#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The probe watch: a probe that leaves the band its neighbours set is said to be off, once,
and said to be back when it returns. A stand-in model (`sdk/test_tsfm.py`): each probe is
forecast to move as its first neighbour does, a band 0.02 either side, so neither Timestral
nor NumPy is needed."""
from __future__ import annotations

import datetime as _dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))

try:
    import celpy  # noqa: F401
    HAVE_CEL = True
except ImportError:
    HAVE_CEL = False

import test_tsfm as T  # noqa: E402
from ids import uuid7  # noqa: E402
from log import Log  # noqa: E402
from model import Label  # noqa: E402
from project import State  # noqa: E402

import probewatch as PW  # noqa: E402

HOUR = _dt.timedelta(hours=1)
T0 = T.T0


def bed(drift=lambda h: 0.0, hours=120):
    """Three probes drying together, the deepest off by `drift(hour)`."""
    state, feature = State(), uuid7()
    state.add(Label(uuid7(), feature, "bed 3", T0, language="en"))
    state.add(Label(uuid7(), feature, "bancal 3", T0, language="es"))
    T.probe(state, feature, 0.05, [0.30 - 0.001 * h for h in range(hours)])
    T.probe(state, feature, 0.10, [0.28 - 0.001 * h for h in range(hours)])
    deep = T.probe(state, feature, 0.20, [0.26 - 0.001 * h + drift(h) for h in range(hours)])
    return state, PW.WatchBed(feature), deep


def wetter_from_40_to_60(h):
    return 0.003 * (h - 40) if 40 <= h <= 60 else 0.0


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestTheWatch(unittest.TestCase):
    def test_probes_that_agree_raise_nothing(self):
        state, b, _ = bed()
        self.assertEqual(PW.Watch(Log(), T.FakeModel()).check(state, [b], T0 + 60 * HOUR), [])

    def test_a_drifting_probe_is_said_to_be_off_once_with_its_receipt(self):
        state, b, deep = bed(wetter_from_40_to_60)
        log = Log()
        watch = PW.Watch(log, T.FakeModel())
        [event] = watch.check(state, [b], T0 + 60 * HOUR)
        d = event.payload
        self.assertEqual((d["rule"], d["alert"], d["subject"]), ("soil-probe-off", True, str(b.feature)))
        self.assertEqual(d["topic"], f"probewatch/{b.feature}/20")
        self.assertTrue(d["context"]["wetter"])
        self.assertGreaterEqual(d["context"]["longest_run_h"], PW.RUN_H)
        self.assertEqual(d["inputs"]["probe"], str(deep.id))
        self.assertEqual(d["inputs"]["receipt"]["model"], "stand-in")
        self.assertIn("probe at 5 cm", d["inputs"]["receipt"]["moved_by"])
        self.assertEqual(watch.check(state, [b], T0 + 61 * HOUR), [], "said once")
        self.assertEqual(PW.Watch(log, T.FakeModel()).check(state, [b], T0 + 61 * HOUR), [],
                         "and a watch started again reads that from the log")

    def test_said_in_the_readers_language_and_units(self):
        state, b, _ = bed(wetter_from_40_to_60)
        [event] = PW.Watch(Log(), T.FakeModel()).check(state, [b], T0 + 60 * HOUR)
        en = PW.render(event.payload, "en", state)
        self.assertTrue(en.startswith("For "), en)
        self.assertIn("For 13 of the last 24 hours, bed 3's probe at 20 cm read wetter", en)
        self.assertIn("bancal 3 a 20 cm leyó más húmeda", PW.render(event.payload, "es", state))
        self.assertIn("at 8 inches", PW.render(event.payload, "en", state, units="us"))

    def test_back_in_line_it_is_said_to_be_back(self):
        state, b, _ = bed(wetter_from_40_to_60)
        log = Log()
        watch = PW.Watch(log, T.FakeModel())
        watch.check(state, [b], T0 + 60 * HOUR)
        [back] = watch.check(state, [b], T0 + 100 * HOUR)
        self.assertEqual((back.payload["rule"], back.payload["alert"]), ("soil-probe-off", False))

    def test_drier_said_drier(self):
        state, b, _ = bed(lambda h: -wetter_from_40_to_60(h))
        [event] = PW.Watch(Log(), T.FakeModel()).check(state, [b], T0 + 60 * HOUR)
        self.assertFalse(event.payload["context"]["wetter"])
        self.assertIn("read drier", PW.render(event.payload, "en", state))

    def test_a_probe_alone_or_silent_is_not_judged(self):
        state, b, _ = bed(wetter_from_40_to_60, hours=61)
        model = T.FakeModel()
        self.assertEqual(PW.Watch(Log(), model).check(state, [b], T0 + 80 * HOUR), [],
                         "none reading within the last six hours")
        alone, feature = State(), uuid7()
        T.probe(alone, feature, 0.10, [0.3] * 61)
        self.assertEqual(PW.Watch(Log(), model).check(alone, [PW.WatchBed(feature)], T0 + 60 * HOUR), [])
        self.assertEqual(model.calls, [])


if __name__ == "__main__":
    unittest.main()

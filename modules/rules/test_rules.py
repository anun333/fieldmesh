# SPDX-License-Identifier: AGPL-3.0-or-later
"""The frost watch: a CEL condition, a decision event that says what it read, a backtest."""
import datetime as _dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
import fixtures as fx  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import ClockQuality, Datastream, DatastreamKind, Observation  # noqa: E402

try:
    import celpy  # noqa: F401
    import rules as R
except ImportError:                          # pragma: no cover - CI installs it
    R = None

UTC = _dt.timezone.utc
DUSK = _dt.datetime(2026, 4, 6, 22, 0, tzinfo=UTC)


def farm(night_lows_forecast, night_lows_measured):
    """A forecast issued each afternoon and a station, one night each."""
    log = L.Log()
    fc = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(), feature=uuid7(),
                    observed_property=V.AIR_TEMPERATURE, unit="Cel", kind=DatastreamKind.FORECAST,
                    expected_interval=3600.0, max_latency=3600.0)
    st = fx.raw_datastream(observed_property=V.AIR_TEMPERATURE, unit="Cel", expected_interval=3600.0)
    for r in (fc, st):
        log.append_record(r)
    for n, (f_low, m_low) in enumerate(zip(night_lows_forecast, night_lows_measured)):
        dusk = DUSK + _dt.timedelta(days=n)
        issued = dusk - _dt.timedelta(hours=4)
        for h in range(0, 20):
            t = dusk + _dt.timedelta(hours=h)
            dip = 1.0 if h in (8, 9, 10) else 0.0
            log.append_record(Observation(id=uuid7(), datastream=fc.id, measured_at=t,
                                          measured_at_uncertainty=1800.0, received_at=issued,
                                          result=f_low + 4.0 * (1 - dip), clock_quality=ClockQuality.NETWORK,
                                          issued_at=issued))
            log.append_record(fx.observation(st, result=m_low + 4.0 * (1 - dip), measured_at=t,
                                             seq=(n * 24 + h) % 65536))
    return log, P.state_from_log(log), fc, st


@unittest.skipIf(R is None, "needs cel-python (modules/rules/requirements.txt)")
class FrostWatchTest(unittest.TestCase):
    def test_a_cold_night_raises_an_advisory_decision_that_says_what_it_read(self):
        log, state, fc, st = farm([-1.0], [-3.0])
        event = R.decide(log, R.frost_watch(0.0), state, fc.id, DUSK)
        d = event.payload
        self.assertTrue(d["alert"])
        self.assertEqual((d["rule"], d["version"], d["trust"]), ("frost-watch", "1", "advisory"))
        self.assertEqual(d["condition"], "has_forecast && night_low_c <= warn_at_c")
        self.assertEqual(d["context"]["night_low_c"], -1.0)
        self.assertEqual(len(d["inputs"]["observations"]), 15, "the night's hours, 00 to 14 UTC")
        self.assertIn(R.DECISION, [e.kind for e in log.events])
        self.assertIn("−1.0 °C".replace("−", "-"), R.render(d))
        self.assertIn("Aviso de helada", R.render(d, "es"))

    def test_a_mild_night_decides_quietly_and_is_still_logged(self):
        log, state, fc, st = farm([3.0], [2.0])
        d = R.decide(log, R.frost_watch(0.0), state, fc.id, DUSK).payload
        self.assertFalse(d["alert"])
        self.assertIsNone(R.render(d))

    def test_no_forecast_is_no_alert_not_a_crash(self):
        log, state, fc, st = farm([], [])
        d = R.evaluate(R.frost_watch(0.0), state, fc.id, DUSK)
        self.assertFalse(d["alert"])
        self.assertFalse(d["context"]["has_forecast"])

    def test_the_backtest_counts_hits_misses_and_false_alerts(self):
        # Four nights: warned frost, missed frost, false alert, quiet.
        log, state, fc, st = farm([-1.0, 2.0, -0.5, 4.0], [-3.0, -2.5, 1.0, 3.0])
        s = R.backtest(R.frost_watch(0.0), state, fc.id, st.id)
        self.assertEqual(s, {"hits": 1, "misses": 1, "false": 1, "quiet": 1})


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(R is None, "needs cel-python (modules/rules/requirements.txt)")
class KeyParamsTest(unittest.TestCase):
    """A message can name something in the reader's language: the decision records which of
    its parameters are language-pack keys, and rendering says them (`Rule.key_params`; the
    sowing advisory's tests render crop names in English and Spanish)."""

    def test_the_decision_says_which_parameters_are_names(self):
        rule = R.Rule("named", "1", "warm", {}, alert_key="rules.frost.alert",
                      message_params={"crop": "crop_key", "low": "low", "warn": "low"},
                      key_params=("crop",))
        d = R.judge(rule, {"warm": True, "crop_key": "sowing.crop.bean", "low": 1.0}, {}, DUSK)
        self.assertEqual(d["message"]["key_params"], ["crop"])
        self.assertEqual(d["message"]["params"]["crop"], "sowing.crop.bean")
        plain = R.judge(R.Rule("plain", "1", "warm", {}, alert_key="rules.frost.alert"),
                        {"warm": True}, {}, DUSK)
        self.assertNotIn("key_params", plain["message"])

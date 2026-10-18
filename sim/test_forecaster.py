# SPDX-License-Identifier: Apache-2.0
"""Recorded weather in the virtual farm, a forecaster with a declared error, and the
drill that puts its runs through layer zero and scores them."""
import datetime as dt
import os
import statistics
import unittest

import forecast_drill as D
import forecaster as F
import physics as ph

UTC = dt.timezone.utc
HOUR = dt.timedelta(hours=1)


class RecordedClimateTest(unittest.TestCase):
    def setUp(self):
        self.rc = ph.RecordedClimate.from_csv(D.WEATHER)

    def test_the_day_s_extremes_at_five_and_five(self):
        v = self.rc.days[dt.date(2007, 4, 7)]
        at = lambda h: self.rc.step(dt.datetime(2007, 4, 7, h, tzinfo=UTC)).air_temp_c
        self.assertAlmostEqual(at(5), v["T2M_MIN"], places=2)
        self.assertAlmostEqual(at(17), v["T2M_MAX"], places=2)
        self.assertTrue(v["T2M_MIN"] < at(11) < v["T2M_MAX"])

    def test_no_step_at_midnight(self):
        before = self.rc.step(dt.datetime(2007, 4, 6, 23, 55, tzinfo=UTC)).air_temp_c
        after = self.rc.step(dt.datetime(2007, 4, 7, 0, 0, tzinfo=UTC)).air_temp_c
        self.assertLess(abs(after - before), 0.5)

    def test_each_day_s_rain_is_exact(self):
        world = ph.World(start=dt.datetime(2007, 3, 1, tzinfo=UTC), climate=self.rc)
        totals = {}
        for truth in world.run(days=20):
            totals[truth.when.date()] = totals.get(truth.when.date(), 0.0) + truth.weather.rain_mm
        for d, total in totals.items():
            self.assertAlmostEqual(total, self.rc.days[d]["PRECTOTCORR"], delta=0.01, msg=str(d))

    def test_outside_the_record_is_an_error_not_a_guess(self):
        with self.assertRaises(ValueError):
            self.rc.step(dt.datetime(2008, 1, 1, tzinfo=UTC))


class ForecasterTest(unittest.TestCase):
    def truth(self, hours=24 * 60):
        t0 = dt.datetime(2026, 1, 1, tzinfo=UTC)
        return [(t0 + i * HOUR, 10.0, 0.0) for i in range(hours)]

    def test_reproducible(self):
        f = F.Forecaster(self.truth(), seed=3)
        issued = dt.datetime(2026, 1, 2, 6, tzinfo=UTC)
        self.assertEqual(f.run(issued), F.Forecaster(self.truth(), seed=3).run(issued))
        a = dict(f.run(issued)["air_temperature"])
        b = dict(f.run(issued + 6 * HOUR)["air_temperature"])
        shared = sorted(set(a) & set(b))
        self.assertNotEqual([a[t] for t in shared], [b[t] for t in shared], "two issues differ")

    def test_whole_days_missed_and_spells_forecast_on_dry_days(self):
        """`event_miss`, `event_false_alarm`: each day's draw the same in every issue."""
        t0 = dt.datetime(2026, 1, 1, tzinfo=UTC)
        truth = [(t0 + i * HOUR, 10.0, 1.0 if (i // 24) % 2 == 0 else 0.0) for i in range(24 * 30)]
        always = F.Forecaster(truth, seed=3, skill=F.Skill(miss=0.0, false_alarm=0.0,
                                                           event_miss=1.0, event_false_alarm=1.0))
        rain = always.run(t0 + 6 * HOUR)["precipitation"]
        for t, mm in rain:
            day_wet = (int((t - t0) / HOUR) // 24) % 2 == 0
            if day_wet:
                self.assertEqual(mm, 0.0, "a rain day missed whole")
        dry_days = {t.date() for t, mm in rain if mm > 0}
        self.assertTrue(dry_days)
        self.assertTrue(all((int((dt.datetime.combine(d, dt.time(), tzinfo=UTC) - t0) / HOUR) // 24) % 2
                            for d in dry_days), "spells only on dry days")
        some = F.Skill(event_miss=0.3, event_false_alarm=0.1)
        f = F.Forecaster(truth, seed=3, skill=some)
        a, b = f.run(t0 + 6 * HOUR)["precipitation"], f.run(t0 + 12 * HOUR)["precipitation"]
        missed = lambda run: {t.date() for t, mm in run if mm == 0.0
                              and truth[int((t - t0) / HOUR)][2] > 0}
        both = {t.date() for t, _ in a} & {t.date() for t, _ in b}
        self.assertTrue(missed(b) & both)
        self.assertLessEqual(missed(b) & both, missed(a),
                             "a day missed nearer is missed further off: one draw a day")

    def test_the_spread_grows_as_declared(self):
        skill = F.Skill(sd0_c=1.0, sd_per_day_c=0.5)
        f = F.Forecaster(self.truth(), skill=skill, seed=1)
        by_day = {0: [], 3: [], 6: []}
        t0 = dt.datetime(2026, 1, 1, tzinfo=UTC)
        for k in range(150):
            issued = t0 + k * 6 * HOUR
            for t, v in f.run(issued)["air_temperature"]:
                day = int((t - issued).total_seconds() // 86400)
                if day in by_day:
                    by_day[day].append(v - 10.0)
        for day, errs in by_day.items():
            self.assertAlmostEqual(statistics.pstdev(errs), skill.sd(day * 24 + 12), delta=0.25 * skill.sd(day * 24 + 12))

    def test_an_ensemble_has_the_declared_spread_and_each_member_the_declared_skill(self):
        f = F.Forecaster(self.truth(), seed=5)
        t0 = dt.datetime(2026, 1, 1, tzinfo=UTC)
        member_err, run_err, spread = [], [], []
        for k in range(120):
            runs = f.ensemble(t0 + k * 6 * HOUR, 20, spread=0.7, horizon_h=48)
            values = [r[23][1] - 10.0 for r in runs]          # 24 hours ahead
            member_err += values
            run_err.append(statistics.mean(values))
            spread.append(statistics.pstdev(values))
        sd = F.Skill().sd(24)
        self.assertAlmostEqual(statistics.pstdev(member_err), sd, delta=0.15 * sd)
        self.assertAlmostEqual(statistics.mean(spread), 0.7 * sd / (1 + 0.7 ** 2) ** 0.5, delta=0.1)
        self.assertLess(statistics.pstdev(run_err), sd, "the members share an error, which is the run's")
        self.assertEqual(f.ensemble(t0, 3), F.Forecaster(self.truth(), seed=5).ensemble(t0, 3))

    def test_nothing_beyond_the_truth(self):
        f = F.Forecaster(self.truth(48))
        run = f.run(dt.datetime(2026, 1, 1, 12, tzinfo=UTC))
        self.assertEqual(len(run["air_temperature"]), 35)


class ScoreWatchTest(unittest.TestCase):
    """A frost night counts as warned when the alert standing 12 hours before it was on."""
    T0 = dt.datetime(2007, 3, 1, tzinfo=UTC)

    def issues(self, n=12):
        return [self.T0 + k * 6 * HOUR for k in range(n)]

    def test_the_standing_alert_counts_not_a_flicker(self):
        frost = [[self.T0 + 60 * HOUR, self.T0 + 63 * HOUR]]
        steady = [(i, None) for i in self.issues()[4:10]]                 # 24 h to 54 h, unbroken
        flicker = [(self.issues()[2], None)]                               # once at 12 h, withdrawn
        self.assertEqual(D.score_watch(steady, frost, 6, self.issues())["in_time"], 1)
        self.assertEqual(D.score_watch(steady, frost, 6, self.issues())["events"][0]["warned_h"], 36.0)
        self.assertEqual(D.score_watch(flicker, frost, 6, self.issues())["in_time"], 0)

    def test_alerts_are_counted_by_episode(self):
        warnings = [(i, None) for i in self.issues()[0:3]] + [(self.issues()[8], None)]
        r = D.score_watch(warnings, [], 6, self.issues())
        self.assertEqual((r["episodes"], r["false_episodes"]), (2, 2))


class DrillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = D.drill(start=dt.datetime(2007, 4, 1, tzinfo=UTC), days=12, skill=F.Skill())

    def test_the_log_is_sound_and_keeps_every_run(self):
        self.assertEqual(self.r["problems"], [])
        self.assertGreater(self.r["forecast_rows"], 5 * self.r["live_hours"])

    def test_verification_gives_the_declared_skill_back(self):
        for day, v in self.r["verification"].items():
            if v["n"] >= 300:
                declared = F.Skill().sd(day * 24 + 12)
                self.assertAlmostEqual(v["sd"], declared, delta=0.35 * declared, msg=f"day {day}")

    def test_the_easter_freeze_is_warned_in_time(self):
        easter = [e for e in self.r["events"] if e["start"].date() in (dt.date(2007, 4, 7), dt.date(2007, 4, 8))]
        self.assertEqual(len(easter), 2)
        self.assertTrue(all(e["warned_h"] >= D.ENOUGH_LEAD_H for e in easter))

    def test_health_follows_the_runs(self):
        self.assertEqual((self.r["health"], self.r["health_later"]), ("ok", "stale"))



class EnsembleDrillTest(unittest.TestCase):
    """The frost watch from an ensemble's chance, through layer zero (Q26)."""

    @classmethod
    def setUpClass(cls):
        cls.r = D.drill(start=dt.datetime(2007, 4, 3, tzinfo=UTC), days=8, skill=F.Skill(),
                        ensemble=10, chances=(0.1, 0.5))

    def test_every_member_run_is_in_the_log_and_the_log_is_sound(self):
        self.assertEqual(self.r["problems"], [])
        self.assertGreater(self.r["ensemble_rows"], 10 * 48 * 20)

    def test_the_easter_freeze_is_warned_by_the_chance_too(self):
        for c, w in self.r["ensemble_watch"].items():
            easter = [e for e in w["events"] if e["start"].date() in (dt.date(2007, 4, 7), dt.date(2007, 4, 8))]
            self.assertTrue(easter and all(e["warned_h"] >= D.ENOUGH_LEAD_H for e in easter), c)

    def test_a_chance_is_given_every_issue(self):
        self.assertTrue(self.r["chances"])
        self.assertTrue(all(0.0 <= p <= 1.0 for p, _, _ in self.r["chances"]))


if __name__ == "__main__":
    unittest.main()

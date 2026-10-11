#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Farm physics (docs/VIRTUAL_FARM.md step 2).

The sim is the producer half of the producer/detector doctrine, so these tests check
that it produces the right *shapes*: water that arrives and leaves for reasons, a
dry bed that dries more slowly than a wet one, and a stuck float that empties a
trough on a hot day.
"""
from __future__ import annotations

import datetime as _dt
import unittest

import physics as ph

JUNE = _dt.datetime(2026, 6, 1, 0, 0, tzinfo=ph.UTC)
JULY = _dt.datetime(2026, 7, 15, 0, 0, tzinfo=ph.UTC)
JANUARY = _dt.datetime(2026, 1, 15, 0, 0, tzinfo=ph.UTC)


def _dry_climate(**kw):
    """Weather with the rain switched off, so a test can isolate drying."""
    return ph.Climate(seed=1, p_rain_start=0.0, p_rain_continue=0.0, **kw)


class TestDeterminism(unittest.TestCase):
    """Seed plus start reproduces a season exactly, or a failing test is useless."""

    def test_the_same_seed_gives_the_same_season(self):
        a = [r.soil["bed3"] for r in ph.default_world(seed=7).run(days=3)]
        b = [r.soil["bed3"] for r in ph.default_world(seed=7).run(days=3)]
        self.assertEqual(a, b)

    def test_a_different_seed_gives_a_different_season(self):
        a = [r.soil["bed3"] for r in ph.default_world(seed=1).run(days=3)]
        b = [r.soil["bed3"] for r in ph.default_world(seed=2).run(days=3)]
        self.assertNotEqual(a, b)

    def test_weather_is_reproducible_too(self):
        a = [(r.weather.rain_mm, r.weather.air_temp_c)
             for r in ph.default_world(seed=3).run(days=2)]
        b = [(r.weather.rain_mm, r.weather.air_temp_c)
             for r in ph.default_world(seed=3).run(days=2)]
        self.assertEqual(a, b)


class TestClimate(unittest.TestCase):
    def test_july_is_warmer_than_january(self):
        july = ph.Climate(seed=1).step(JULY.replace(hour=12))
        january = ph.Climate(seed=1).step(JANUARY.replace(hour=12))
        self.assertGreater(july.air_temp_c, january.air_temp_c + 10)

    def test_afternoon_is_warmer_than_dawn(self):
        c = ph.Climate(seed=1, p_rain_start=0.0)
        dawn = c.step(JUNE.replace(hour=5))
        afternoon = c.step(JUNE.replace(hour=15))
        self.assertGreater(afternoon.air_temp_c, dawn.air_temp_c)

    def test_et0_is_a_summer_daytime_phenomenon(self):
        c = _dry_climate()
        self.assertGreater(c.step(JULY.replace(hour=13)).et0_mm,
                           c.step(JANUARY.replace(hour=13)).et0_mm)
        self.assertEqual(c.step(JULY.replace(hour=2)).et0_mm, 0.0,
                         "nothing evaporates much at 2 a.m.")

    def test_rain_arrives_in_spells_not_as_independent_drizzle(self):
        """A two-state process, because real wet weather clusters."""
        rows = list(ph.default_world(seed=5).run(days=30))
        wet = [r.weather.raining for r in rows]
        self.assertTrue(any(wet), "30 days should see some rain")
        runs = []
        current = 0
        for is_wet in wet:
            if is_wet:
                current += 1
            elif current:
                runs.append(current)
                current = 0
        if current:
            runs.append(current)
        self.assertGreater(max(runs), 3,
                           "rain should persist for more than one tick at a time")

    def test_rain_cools_and_humidifies(self):
        c = ph.Climate(seed=1, p_rain_start=1.0, p_rain_continue=1.0)
        wet = c.step(JUNE.replace(hour=12))
        dry = _dry_climate().step(JUNE.replace(hour=12))
        self.assertLess(wet.air_temp_c, dry.air_temp_c)
        self.assertGreater(wet.relative_humidity, dry.relative_humidity)
        self.assertLess(wet.et0_mm, dry.et0_mm)


class TestSoilBed(unittest.TestCase):
    def test_thresholds_must_be_ordered(self):
        with self.assertRaises(ValueError):
            ph.SoilBed(name="x", wilting_point=0.3, field_capacity=0.2)

    def test_water_above_field_capacity_drains_away(self):
        bed = ph.SoilBed(name="wet", theta=0.42)
        climate = _dry_climate()
        world = ph.World(start=JUNE, climate=climate, beds=[bed])
        list(world.run(days=1))
        self.assertLess(bed.theta, 0.42)
        self.assertLess(abs(bed.theta - bed.field_capacity), 0.03,
                        "free drainage should settle near field capacity in a day")

    def test_a_bed_at_field_capacity_dries_only_by_evapotranspiration(self):
        bed = ph.SoilBed(name="fc", theta=0.30)
        world = ph.World(start=JUNE, climate=_dry_climate(), beds=[bed])
        list(world.run(days=1))
        loss = 0.30 - bed.theta
        self.assertGreater(loss, 0.0)
        self.assertLess(loss, 0.03, "ET alone is a slow process")

    def test_a_dry_bed_dries_more_slowly_than_a_wet_one(self):
        """FAO-56's stress idea: a crop that cannot find water cannot transpire it,
        so drying is self-limiting. Without this a sim walks straight through the
        wilting point, and a rate-of-change check learns the wrong thing."""
        wet = ph.SoilBed(name="wet", theta=0.29)
        dry = ph.SoilBed(name="dry", theta=0.14)
        world = ph.World(start=JUNE, climate=_dry_climate(), beds=[wet, dry])
        before = (wet.theta, dry.theta)
        list(world.run(days=2))
        self.assertGreater(before[0] - wet.theta, before[1] - dry.theta)

    def test_stress_runs_from_zero_to_one_between_the_thresholds(self):
        bed = ph.SoilBed(name="b", theta=0.30)
        self.assertEqual(bed.stress, 0.0)
        bed.theta = 0.12
        self.assertEqual(bed.stress, 1.0)
        bed.theta = 0.21
        self.assertAlmostEqual(bed.stress, 0.5, places=2)

    def test_water_content_never_leaves_physical_bounds(self):
        bed = ph.SoilBed(name="b", theta=0.44)
        climate = ph.Climate(seed=1, p_rain_start=1.0, p_rain_continue=1.0,
                            rain_intensity_mm_h=40.0)
        world = ph.World(start=JUNE, climate=climate, beds=[bed])
        for truth in world.run(days=2):
            self.assertLessEqual(truth.soil["b"], bed.saturation)
            self.assertGreater(truth.soil["b"], 0.0)

    def test_rain_wets_the_soil(self):
        bed = ph.SoilBed(name="b", theta=0.20)
        climate = ph.Climate(seed=1, p_rain_start=1.0, p_rain_continue=1.0)
        world = ph.World(start=JUNE, climate=climate, beds=[bed])
        list(world.run(days=0.5))
        self.assertGreater(bed.theta, 0.20)


class TestIrrigation(unittest.TestCase):
    def test_millimetres_become_water_content_over_the_root_depth(self):
        bed = ph.SoilBed(name="b", theta=0.20, depth_mm=300.0)
        world = ph.World(start=JUNE, climate=_dry_climate(), beds=[bed])
        world.irrigate("b", 30.0)
        world.step()
        self.assertAlmostEqual(bed.theta, 0.20 + 30.0 / 300.0, places=2)

    def test_irrigation_applies_once_not_every_tick(self):
        """Midday, because at midnight ET0 is zero and nothing would change either
        way — the sim is right about that and the test has to account for it."""
        bed = ph.SoilBed(name="b", theta=0.20)
        world = ph.World(start=JUNE.replace(hour=12), climate=_dry_climate(),
                        beds=[bed])
        world.irrigate("b", 15.0)
        world.step()
        after_one = bed.theta
        world.step()
        self.assertLess(bed.theta, after_one, "the second tick only dries")

    def test_an_unknown_bed_is_refused(self):
        world = ph.World(start=JUNE, beds=[ph.SoilBed(name="b")])
        with self.assertRaises(KeyError):
            world.irrigate("nowhere", 10.0)

    def test_negative_irrigation_is_refused(self):
        world = ph.World(start=JUNE, beds=[ph.SoilBed(name="b")])
        with self.assertRaises(ValueError):
            world.irrigate("b", -5.0)


class TestTrough(unittest.TestCase):
    def test_a_working_float_holds_the_level(self):
        world = ph.default_world(start=JULY)
        levels = [r.trough_fraction["paddock"] for r in world.run(days=2)]
        self.assertGreater(min(levels), 0.85)

    def test_a_stuck_float_empties_the_trough_within_a_day(self):
        """The emergency this sim exists to produce. Hourly detection of this is an
        animal-welfare problem, which is why livestock water carries a tight
        max_latency (§5.3.1)."""
        world = ph.default_world(start=JULY)
        world.troughs["paddock"].float_stuck_shut = True
        rows = list(world.run(days=1))
        empty = [r for r in rows if r.trough_l["paddock"] <= 0.0]
        self.assertTrue(empty, "24 stock drinking 45 L/day empty 400 L inside a day")
        self.assertLess(empty[0].when.hour, 20,
                        "and it should run dry during the day, not overnight")

    def test_stock_drink_more_when_it_is_hot(self):
        """Measured as time-to-empty rather than volume drawn, because a trough
        that has bottomed out in both seasons shows no difference at all."""
        def hours_to_empty(start):
            world = ph.default_world(start=start)
            world.troughs["paddock"].float_stuck_shut = True
            for i, truth in enumerate(world.run(days=2)):
                if truth.trough_l["paddock"] <= 0.0:
                    return i * ph.STEP.total_seconds() / 3600.0
            return float("inf")
        self.assertLess(hours_to_empty(JULY), hours_to_empty(JANUARY))

    def test_stock_drink_in_the_daytime(self):
        world = ph.default_world(start=JULY)
        world.troughs["paddock"].float_stuck_shut = True
        rows = list(world.run(days=1))
        night = rows[0].trough_l["paddock"] - rows[36].trough_l["paddock"]
        day = rows[108].trough_l["paddock"] - rows[144].trough_l["paddock"]
        self.assertGreater(day, night)

    def test_a_level_never_goes_negative(self):
        world = ph.default_world(start=JULY)
        world.troughs["paddock"].float_stuck_shut = True
        for truth in world.run(days=2):
            self.assertGreaterEqual(truth.trough_l["paddock"], 0.0)


class TestWorld(unittest.TestCase):
    def test_start_must_be_utc(self):
        """§2: everything is stored in UTC."""
        with self.assertRaises(ValueError):
            ph.World(start=_dt.datetime(2026, 6, 1))
        with self.assertRaises(ValueError):
            ph.World(start=_dt.datetime(2026, 6, 1,
                                        tzinfo=_dt.timezone(_dt.timedelta(hours=3))))

    def test_time_advances_by_one_step_per_tick(self):
        world = ph.World(start=JUNE, beds=[ph.SoilBed(name="b")])
        first = world.step()
        second = world.step()
        self.assertEqual(second.when - first.when, ph.STEP)

    def test_run_yields_the_right_number_of_ticks(self):
        world = ph.default_world()
        self.assertEqual(len(list(world.run(days=1))), 288)

    def test_the_default_world_staggers_its_beds(self):
        """One run should show a wet bed draining, a comfortable one and a
        stressed one, so a single season exercises the whole range."""
        truth = ph.default_world().step()
        values = list(truth.soil.values())
        self.assertGreater(max(values), 0.35)
        self.assertLess(min(values), 0.16)
        self.assertEqual(len(truth.soil), 6)

    def test_truth_is_a_frozen_snapshot(self):
        truth = ph.default_world().step()
        with self.assertRaises(Exception):
            truth.when = JUNE



FILMS_COLD = {film: v["cold_night_gain_c"] for film, v in ph.FILMS.items()}


class SkyTest(unittest.TestCase):
    """The tunnel's nights when the weather knows its cloud (A7, Q28)."""

    def test_cloud_comes_back_from_the_sky_s_long_wave(self):
        sigma, t, rh = ph.SIGMA, 2.0, 80.0
        black = sigma * (t + 273.15) ** 4
        self.assertAlmostEqual(ph.cloud_from_longwave(t, rh, black), 1.0, places=6)
        self.assertEqual(ph.cloud_from_longwave(t, rh, 0.6 * black), 0.0)
        half = ph.cloud_from_longwave(t, rh, 0.85 * black)
        self.assertTrue(0.0 < half < 1.0)

    def night(self, film, cloud, outside=2.0, hours=10):
        tun = ph.Tunnel.of("hoop", film)
        w = ph.Weather(air_temp_c=outside, relative_humidity=85.0, rain_mm=0.0, et0_mm=0.0,
                       raining=False, cloud=cloud)
        inside = None
        for _ in range(hours * 12):
            inside = tun.step(w, 0.0)
        return inside - outside

    def test_a_clear_night_under_clear_film_is_colder_inside_than_out(self):
        self.assertLess(self.night("clear", 0.0), 0.0)
        self.assertGreater(self.night("clear", 1.0), 1.0, "under cloud the soil's heat holds")
        self.assertGreater(self.night("thermic", 0.0), 0.5, "IR film keeps it on a clear night")

    def test_without_cloud_the_tunnel_runs_as_it_always_has(self):
        for film in ("thermic", "clear"):
            tun = ph.Tunnel.of("hoop", film)
            self.assertEqual(tun.night_gain(2.0, False, None), tun.night_gain(2.0, False))
            self.assertEqual(tun.night_gain(-8.0, False, None), FILMS_COLD[film])


if __name__ == "__main__":
    unittest.main(verbosity=2)

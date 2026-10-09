#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Forecasts for the virtual farm, with an error that is known because it was put there.

A real forecast's skill at a farm is unknown until the farm's own sensors have scored
it for a season. Whatever acts on forecasts — a frost watch, an irrigation rule that
skips a watering when rain is coming — needs testing before that season exists, and
honestly: the producer/detector doctrine again (docs/VIRTUAL_FARM.md). So the
forecaster reads the world's own future and adds an error of a declared size:

* **temperature**: an error that wanders smoothly from hour to hour (AR(1), `rho`
  hour to hour) with a spread that grows with lead time, `sd0_c` at the start plus
  `sd_per_day_c` each day, around a fixed `bias_c`;
* **rain**: hours that rain are forecast dry with a probability that grows with lead
  time (`miss`), dry hours forecast wet likewise (`false_alarm`), and forecast
  amounts are the true ones scaled by a log-normal factor.

The defaults resemble published skill — around 1.5 °C of spread at a day, near 3.5 at a
week — without being calibrated to any one service; a test that needs a sharper or a
worse forecaster says so. Each run is seeded by the forecaster's seed and its issue
time, so a season of runs is reproducible and two runs differ the way two real
issues do.
"""
from __future__ import annotations

import datetime as _dt
import math
import random
from dataclasses import dataclass

HOUR = _dt.timedelta(hours=1)


@dataclass(frozen=True)
class Skill:
    sd0_c: float = 1.2
    sd_per_day_c: float = 0.35
    rho: float = 0.97
    bias_c: float = 0.0
    miss: float = 0.10              # at a day; doubles by a week
    false_alarm: float = 0.03
    amount_sd: float = 0.5          # of log(forecast / true)

    def sd(self, lead_h: float) -> float:
        return self.sd0_c + self.sd_per_day_c * lead_h / 24.0

    def growth(self, lead_h: float) -> float:
        return 1.0 + lead_h / 168.0


class Forecaster:
    """`truth`: hourly `(time, air temperature °C, rain mm in the hour)`, sorted."""

    def __init__(self, truth: list, *, skill: Skill = Skill(), seed: int = 1,
                 horizon_h: int = 168):
        self.truth = truth
        self.index = {t: i for i, (t, _, _) in enumerate(truth)}
        self.skill, self.seed, self.horizon_h = skill, seed, horizon_h

    def run(self, issued_at: _dt.datetime) -> dict:
        """One issue: `{"air_temperature": [(t, °C)], "precipitation": [(t, mm)]}` for
        the hours after `issued_at` that the truth covers, up to the horizon."""
        first = issued_at.replace(minute=0, second=0, microsecond=0) + HOUR
        start = self.index.get(first)
        if start is None:
            return {"air_temperature": [], "precipitation": []}
        rng = random.Random(self.seed * 7_919 + int(issued_at.timestamp()))
        s = self.skill
        temps, rain = [], []
        # Start at the full spread: an error that built up from zero would make the
        # first hours look sharper than the declared skill.
        prev_sd = s.sd((first - issued_at).total_seconds() / 3600.0)
        error = prev_sd * rng.gauss(0.0, 1.0)
        for k in range(self.horizon_h):
            i = start + k
            if i >= len(self.truth):
                break
            t, temp, mm = self.truth[i]
            lead = (t - issued_at).total_seconds() / 3600.0
            sd = s.sd(lead)
            error = s.rho * error * (sd / prev_sd) + math.sqrt(1.0 - s.rho ** 2) * sd * rng.gauss(0.0, 1.0)
            prev_sd = sd
            temps.append((t, round(temp + s.bias_c + error, 2)))
            g = s.growth(lead)
            if mm > 0.0:
                wet = rng.random() >= min(1.0, s.miss * g)
                rain.append((t, round(mm * math.exp(rng.gauss(0.0, s.amount_sd)), 2) if wet else 0.0))
            else:
                spurious = rng.random() < min(1.0, s.false_alarm * g)
                rain.append((t, round(rng.uniform(0.2, 2.0), 2) if spurious else 0.0))
        return {"air_temperature": temps, "precipitation": rain}

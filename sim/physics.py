#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Farm physics for the virtual farm (docs/VIRTUAL_FARM.md step 2).

Readings that move for a reason. Nothing above layer zero means anything if the
numbers it ingests are noise — a flatline check cannot be scored against a series
that was never going anywhere, and an irrigation rule cannot be backtested against
weather that did not happen.

**Ground truth lives here, and only here.** This module produces what is actually
true in the bed and the trough. Sensors, their noise, their quantisation and their
faults belong to the node simulator; the separation is the producer/detector doctrine
from docs/VIRTUAL_FARM.md — a detector is only honestly scored if the thing that
produced the fault and the thing that is supposed to notice it were written apart.

**Deterministic.** Seed plus start time reproduces a season exactly, so a fault that
appears on one run appears on every run and a failing test is actionable. Rain is the
only stochastic input — temperature and reference ET are pure functions of the
timestamp — so two seeds produce identical output over any window that happens to be
dry in both. That is a property, not a bug, and it means seed sensitivity has to be
tested over a window long enough for rain to occur.

**Fidelity, stated plainly.** This is plausible physics with the right *shape*, not a
validated agronomic model. The soil balance is a single-layer bucket with
FAO-56-flavoured stress and drainage; ET is a seasonal curve scaled by temperature,
not Penman-Monteith; rain is a seeded two-state process, not a weather generator.
That is enough to exercise every clause in the spec and to make a drift look like
drift. It is not enough to tell a farmer when to irrigate, and nothing here should be
used to claim otherwise.
"""
from __future__ import annotations

import datetime as _dt
import math
import random
from dataclasses import dataclass, field, replace

UTC = _dt.timezone.utc
STEP = _dt.timedelta(minutes=5)          # the base tick
HOURS_PER_STEP = STEP.total_seconds() / 3600.0


# --------------------------------------------------------------------- weather

@dataclass(frozen=True, slots=True)
class Weather:
    """What the sky is doing this tick."""

    air_temp_c: float
    relative_humidity: float
    rain_mm: float           # over this tick
    et0_mm: float            # reference evapotranspiration over this tick
    raining: bool


@dataclass
class Climate:
    """A seeded, seasonal, deterministic weather process.

    Northern-hemisphere temperate by default: coldest in January, hottest in July,
    a diurnal swing, and rain as a two-state process so wet spells cluster the way
    real ones do rather than arriving as independent drizzle.
    """

    seed: int = 1
    mean_temp_c: float = 11.0
    annual_swing_c: float = 9.0        # half the Jan-Jul difference
    diurnal_swing_c: float = 6.0
    #: probability a dry tick turns wet, and a wet tick stays wet. The asymmetry
    #: is what makes spells rather than noise.
    p_rain_start: float = 0.0012
    p_rain_continue: float = 0.92
    rain_intensity_mm_h: float = 2.2
    et0_peak_mm_day: float = 5.2
    et0_floor_mm_day: float = 0.4

    _rng: random.Random = field(init=False, repr=False, default=None)
    _raining: bool = field(init=False, repr=False, default=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._raining = False

    # The seasonal position of a moment, 0 at the coldest point of the year.
    @staticmethod
    def _year_phase(when: _dt.datetime) -> float:
        day = when.timetuple().tm_yday
        return 2 * math.pi * (day - 15) / 365.25

    def _seasonal_temp(self, when: _dt.datetime) -> float:
        return self.mean_temp_c - self.annual_swing_c * math.cos(self._year_phase(when))

    @staticmethod
    def _diurnal(when: _dt.datetime) -> float:
        """Coldest at 05:00, warmest at **17:00**.

        This said 15:00 until the soil heat model made the phase load-bearing.
        `-cos(2π(h - 5)/24)` is a pure sinusoid, so its maximum is twelve hours after
        its minimum. The code was what every measurement had been taken against, so it
        is the docstring that changed — a siting check that infers depth from *when*
        the daily peak arrives would have been calibrated two hours wrong.
        """
        hour = when.hour + when.minute / 60.0
        return -math.cos(2 * math.pi * (hour - 5) / 24.0)

    def step(self, when: _dt.datetime) -> Weather:
        seasonal = self._seasonal_temp(when)
        temp = seasonal + self.diurnal_swing_c * self._diurnal(when)

        # Two-state rain: starting is rare, continuing is likely.
        roll = self._rng.random()
        self._raining = (roll < self.p_rain_continue if self._raining
                         else roll < self.p_rain_start)
        rain = (self.rain_intensity_mm_h * HOURS_PER_STEP
                * (0.4 + 1.2 * self._rng.random())) if self._raining else 0.0
        temp -= 2.0 if self._raining else 0.0

        humidity = 92.0 if self._raining else max(
            35.0, 88.0 - 1.8 * max(0.0, temp - 5.0))

        # ET0 as a seasonal curve scaled by how warm it actually is, suppressed by
        # rain. Daylight only — nothing evaporates much at 3 a.m.
        season = 0.5 * (1 - math.cos(self._year_phase(when)))
        daylight = max(0.0, math.sin(math.pi * (when.hour + when.minute / 60.0 - 6) / 12))
        et0_day = self.et0_floor_mm_day + season * (
            self.et0_peak_mm_day - self.et0_floor_mm_day)
        warmth = max(0.2, min(1.6, (temp + 2.0) / 18.0))
        et0 = et0_day * warmth * daylight * (HOURS_PER_STEP / 12.0)
        if self._raining:
            et0 *= 0.15

        return Weather(air_temp_c=round(temp, 2),
                       relative_humidity=round(humidity, 1),
                       rain_mm=round(rain, 4),
                       et0_mm=round(max(0.0, et0), 5),
                       raining=self._raining)


# --------------------------------------------------------------- soil heat

#: Layer thickness and count for the soil heat model: 40 layers of 2.5 cm, to 1 m.
#: Chosen against the explicit scheme's stability limit, which needs
#: `kappa * dt / dz**2 <= 0.5`. At the wettest diffusivity below and a 5-minute
#: step that ratio is 0.34, so the scheme is stable without substepping.
HEAT_DZ = 0.025
HEAT_LAYERS = 41
DIURNAL_OMEGA = 2 * math.pi / 86400.0

#: How much warmer bare, sunlit soil runs than the air above it at solar noon.
SOLAR_SURFACE_GAIN_C = 4.0


def thermal_diffusivity(theta: float) -> float:
    """Soil thermal diffusivity in m2/s, from volumetric water content.

    Rises steeply as a dry soil wets — water bridges the air gaps between grains —
    and flattens past about 0.25. The range, roughly 2.5e-7 to 7e-7, is typical of a
    loam. **This is the confounder the siting check has to survive:** a dry bed damps
    the daily wave faster than a wet one, so a probe in a dry bed looks deeper than it
    is, and a check calibrated on one bed would misread every other.
    """
    return 2.5e-7 + 4.5e-7 * min(1.0, max(0.0, theta) / 0.25)


def damping_depth(kappa: float) -> float:
    """The depth at which the daily wave falls to 1/e, in metres.

    `sqrt(2 kappa / omega)`. Each damping depth down, the daily swing shrinks by a
    factor of e and the daily peak arrives 24/2π ≈ 3.8 hours later — the two
    signatures a probe's depth leaves in its own temperature record.
    """
    return math.sqrt(2.0 * kappa / DIURNAL_OMEGA)


# ------------------------------------------------------------------- soil beds

@dataclass
class SoilBed:
    """A single-layer water balance for one bed.

    Volumetric water content in cm3/cm3, which is what a capacitive probe reports
    and what §3.4's UCUM code `cm3/cm3` names. Water stored is `theta * depth_mm`.

    The three thresholds are the ones that matter agronomically and the ones the
    §4.2 range check wants: above `saturation` is physically impossible and means a
    broken sensor; below `wilting_point` the crop is in trouble; `field_capacity` is
    where free drainage stops.
    """

    name: str
    depth_mm: float = 300.0
    saturation: float = 0.45
    field_capacity: float = 0.30
    wilting_point: float = 0.12
    crop_coefficient: float = 1.0
    #: Fraction of the water above field capacity that drains away each hour.
    drainage_per_hour: float = 0.35
    theta: float = 0.28
    #: Soil temperature by layer, top down, `HEAT_DZ` apart. None until the first
    #: heat step, which seeds every layer at the deep boundary — so the daily wave
    #: needs roughly a day to establish itself at 20 cm, as it would after a real
    #: probe is pushed into undisturbed ground.
    temps: list = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.wilting_point < self.field_capacity < self.saturation:
            raise ValueError("thresholds must be wilting < field capacity < saturation")
        self.theta = self._clamp(self.theta)

    def _clamp(self, theta: float) -> float:
        return max(0.01, min(self.saturation, theta))

    @property
    def stored_mm(self) -> float:
        return self.theta * self.depth_mm

    @property
    def stress(self) -> float:
        """0 when the crop is comfortable, 1 when it cannot transpire at all.

        Linear between field capacity and wilting point — the FAO-56 idea without
        its depletion-fraction refinement.
        """
        span = self.field_capacity - self.wilting_point
        if self.theta >= self.field_capacity:
            return 0.0
        if self.theta <= self.wilting_point:
            return 1.0
        return 1.0 - (self.theta - self.wilting_point) / span

    def step(self, weather: Weather, *, irrigation_mm: float = 0.0) -> float:
        """Advance one tick. Returns the new water content."""
        water = self.stored_mm + weather.rain_mm + irrigation_mm

        # Actual ET falls off as the soil dries — a dry bed loses water slower.
        et = weather.et0_mm * self.crop_coefficient * (1.0 - self.stress)
        water -= et

        # Free drainage of anything above field capacity.
        capacity_mm = self.field_capacity * self.depth_mm
        if water > capacity_mm:
            excess = water - capacity_mm
            water -= excess * min(1.0, self.drainage_per_hour * HOURS_PER_STEP)

        self.theta = self._clamp(water / self.depth_mm)
        return self.theta

    def step_heat(self, surface_c: float, deep_c: float) -> None:
        """Advance the soil temperature profile one tick by explicit diffusion.

        The surface layer is forced to `surface_c` and the bottom held at `deep_c`;
        everything between follows the heat equation with this bed's own
        diffusivity. That is what makes the daily wave arrive later and weaker with
        depth, by the amounts `damping_depth` predicts — and differently in a wet bed
        than a dry one.
        """
        if self.temps is None:
            self.temps = [deep_c] * HEAT_LAYERS
        ratio = (thermal_diffusivity(self.theta) * STEP.total_seconds()
                 / (HEAT_DZ * HEAT_DZ))
        old = self.temps
        new = old[:]
        new[0] = surface_c
        for i in range(1, HEAT_LAYERS - 1):
            new[i] = old[i] + ratio * (old[i - 1] - 2.0 * old[i] + old[i + 1])
        new[-1] = deep_c
        self.temps = new

    def temp_at(self, depth_m: float) -> float:
        """Temperature at a depth, linearly between the two nearest layers."""
        if self.temps is None:
            raise ValueError("the heat model has not been stepped yet")
        if depth_m <= 0:
            return self.temps[0]
        position = depth_m / HEAT_DZ
        lower = int(position)
        if lower >= HEAT_LAYERS - 1:
            return self.temps[-1]
        frac = position - lower
        return self.temps[lower] * (1 - frac) + self.temps[lower + 1] * frac


# --------------------------------------------------------------------- troughs

@dataclass
class Trough:
    """A stock water trough with a float valve.

    The failure this exists to produce: a float valve that sticks shut. The trough
    then empties at whatever rate the animals drink, and on a hot day that is an
    emergency rather than a data-quality curiosity — which is why livestock water is
    the module recommended to ship first.
    """

    name: str
    capacity_l: float = 400.0
    level_l: float = 380.0
    stock_count: int = 24
    litres_per_head_per_day: float = 45.0
    #: Refill rate when the float is open and the level is below the setpoint.
    refill_l_per_min: float = 14.0
    float_setpoint: float = 0.92        # fraction of capacity the float holds
    float_stuck_shut: bool = False

    @property
    def level_fraction(self) -> float:
        return self.level_l / self.capacity_l

    def _draw_multiplier(self, when: _dt.datetime, weather: Weather) -> float:
        """Stock drink in the daytime, and more when it is hot."""
        hour = when.hour + when.minute / 60.0
        diurnal = max(0.05, math.sin(math.pi * max(0.0, hour - 5) / 15.0))
        heat = 1.0 + max(0.0, (weather.air_temp_c - 18.0)) * 0.045
        return diurnal * heat

    def step(self, when: _dt.datetime, weather: Weather) -> float:
        daily = self.stock_count * self.litres_per_head_per_day
        draw = daily * (HOURS_PER_STEP / 24.0) * self._draw_multiplier(when, weather)
        self.level_l = max(0.0, self.level_l - draw)

        if not self.float_stuck_shut and self.level_fraction < self.float_setpoint:
            room = self.capacity_l * self.float_setpoint - self.level_l
            refill = min(room, self.refill_l_per_min * HOURS_PER_STEP * 60.0)
            self.level_l += refill
        return self.level_l


# ------------------------------------------------------------------ irrigation

@dataclass(frozen=True, slots=True)
class IrrigationRule:
    """A drip timer: `millimetres` into `bed`, spread over `duration_h` from
    `start_hour` UTC, every `every_days` days starting on day `offset_days`.

    Spread rather than dumped, because the §4.2 rate threshold was derived from drip —
    25 mm across a 300 mm root zone over roughly a quarter of an hour — and a timer that
    delivered a whole event in one five-minute tick would be a physically impossible
    jump that the rate check is right to flag. A farm's own timers, not librefarm
    commands: §6 is deferred, and most farms irrigate on timers anyway.
    """

    bed: str
    millimetres: float
    start_hour: float
    duration_h: float = 1.0
    every_days: int = 2
    offset_days: int = 0

    def mm_this_step(self, when: _dt.datetime, start: _dt.datetime) -> float:
        day = (when.date() - start.date()).days
        if day < self.offset_days or (day - self.offset_days) % self.every_days:
            return 0.0
        hour = when.hour + when.minute / 60.0
        if not self.start_hour <= hour < self.start_hour + self.duration_h:
            return 0.0
        steps = self.duration_h * 3600.0 / STEP.total_seconds()
        return self.millimetres / steps


# ------------------------------------------------------------------- the world

@dataclass(frozen=True, slots=True)
class Truth:
    """Ground truth at one instant. What a perfect sensor would read."""

    when: _dt.datetime
    weather: Weather
    soil: dict                  # bed name -> volumetric water content
    soil_stress: dict           # bed name -> 0..1
    trough_l: dict              # trough name -> litres
    trough_fraction: dict       # trough name -> 0..1
    soil_temp: dict = None      # bed name -> layer temperatures, top down

    def soil_temp_at(self, bed: str, depth_m: float) -> float:
        """What a temperature sensor at `depth_m` in `bed` would read now."""
        profile = self.soil_temp[bed]
        if depth_m <= 0:
            return profile[0]
        position = depth_m / HEAT_DZ
        lower = int(position)
        if lower >= len(profile) - 1:
            return profile[-1]
        frac = position - lower
        return profile[lower] * (1 - frac) + profile[lower + 1] * frac


class World:
    """Beds, troughs and weather, stepped together and deterministically.

    `irrigate` is how anything above layer zero influences the world — the one hook
    an irrigation module would eventually drive. Nothing calls it yet; the first
    release ships observations only (§6 is deferred), so for now it exists to let a
    test produce the wet-then-drying curve that makes a rate-of-change check
    meaningful.
    """

    __slots__ = ("climate", "beds", "troughs", "when", "start", "_pending_mm",
                 "irrigation")

    def __init__(self, *, start: _dt.datetime, climate: Climate | None = None,
                 beds=(), troughs=()):
        if start.tzinfo is None or start.utcoffset() != _dt.timedelta(0):
            raise ValueError("start must be timezone-aware UTC (§2)")
        self.start = start
        self.when = start
        self.climate = climate or Climate()
        self.beds = {b.name: b for b in beds}
        self.troughs = {t.name: t for t in troughs}
        self._pending_mm: dict[str, float] = {}
        #: Drip timers. Empty by default, so a world built without them behaves
        #: exactly as before.
        self.irrigation: list[IrrigationRule] = []

    def irrigate(self, bed: str, millimetres: float) -> None:
        """Apply water to a bed on the next tick."""
        if bed not in self.beds:
            raise KeyError(bed)
        if millimetres < 0:
            raise ValueError("irrigation is not negative")
        self._pending_mm[bed] = self._pending_mm.get(bed, 0.0) + millimetres

    def step(self) -> Truth:
        weather = self.climate.step(self.when)
        # Sunlit soil runs warmer than the air at midday; rain removes the gain.
        hour = self.when.hour + self.when.minute / 60.0
        daylight = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0))
        gain = 0.0 if weather.raining else SOLAR_SURFACE_GAIN_C * daylight
        surface_c = weather.air_temp_c + gain
        deep_c = self.climate._seasonal_temp(self.when)
        for rule in self.irrigation:
            mm = rule.mm_this_step(self.when, self.start)
            if mm:
                self._pending_mm[rule.bed] = self._pending_mm.get(rule.bed, 0.0) + mm
        for name, bed in self.beds.items():
            bed.step(weather, irrigation_mm=self._pending_mm.pop(name, 0.0))
            bed.step_heat(surface_c, deep_c)
        for trough in self.troughs.values():
            trough.step(self.when, weather)
        truth = Truth(
            when=self.when,
            weather=weather,
            soil={n: round(b.theta, 5) for n, b in self.beds.items()},
            soil_stress={n: round(b.stress, 4) for n, b in self.beds.items()},
            trough_l={n: round(t.level_l, 2) for n, t in self.troughs.items()},
            trough_fraction={n: round(t.level_fraction, 4)
                             for n, t in self.troughs.items()},
            soil_temp={n: tuple(b.temps) for n, b in self.beds.items()},
        )
        self.when = self.when + STEP
        return truth

    def run(self, *, days: float = 1.0):
        """Yield ground truth for every tick over `days`."""
        ticks = int(days * 24 * 3600 / STEP.total_seconds())
        for _ in range(ticks):
            yield self.step()


def default_world(*, start: _dt.datetime | None = None, seed: int = 1) -> World:
    """Harrow Bend's physics: six beds and a paddock trough.

    The bed moistures are staggered so a single run exercises a wet bed draining,
    a comfortable one, and one already under stress.
    """
    start = start or _dt.datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    beds = [SoilBed(name=f"bed{i + 1}", theta=theta)
            for i, theta in enumerate((0.38, 0.32, 0.28, 0.24, 0.19, 0.14))]
    troughs = [Trough(name="paddock")]
    return World(start=start, climate=Climate(seed=seed), beds=beds,
                 troughs=troughs)


__all__ = ["Climate", "SoilBed", "Trough", "World", "Weather", "Truth",
           "default_world", "STEP", "UTC", "replace"]

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
    #: Cloud cover, 0 clear to 1 overcast, when the weather knows it (recorded hourly
    #: weather does, from the sky's long-wave: `cloud_from_longwave`). None leaves rain as
    #: the only sign of cloud, as the seeded climate has.
    cloud: float | None = None


SIGMA = 5.670374419e-8          # Stefan–Boltzmann, W m-2 K-4


def fao56_eto(tmin_c: float, tmax_c: float, rh_mean_pct: float, rs_mj_m2: float, day_of_year: int,
              lat_deg: float, elevation_m: float, wind_m_s: float = 2.0) -> float:
    """Daily reference evapotranspiration, mm, by FAO-56 Penman–Monteith (Allen et al.
    1998, eq. 6), from a day's extremes, mean humidity and sunshine. With no wind measured,
    FAO-56's own default of 2 m/s. This is what an irrigation controller's weather service
    computes from the day before; the virtual farm's own water use is its soil bucket."""
    def sat(t):
        return 0.6108 * math.exp(17.27 * t / (t + 237.3))
    tmean = (tmin_c + tmax_c) / 2.0
    pressure = 101.3 * ((293.0 - 0.0065 * elevation_m) / 293.0) ** 5.26
    gamma = 0.000665 * pressure
    delta = 4098.0 * sat(tmean) / (tmean + 237.3) ** 2
    es = (sat(tmax_c) + sat(tmin_c)) / 2.0
    ea = rh_mean_pct / 100.0 * es                                   # eq. 19
    phi = math.radians(lat_deg)
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * day_of_year / 365.0)
    dec = 0.409 * math.sin(2.0 * math.pi * day_of_year / 365.0 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(dec))))
    ra = 24.0 * 60.0 / math.pi * 0.0820 * dr * (ws * math.sin(phi) * math.sin(dec)
                                               + math.cos(phi) * math.cos(dec) * math.sin(ws))
    rso = (0.75 + 2e-5 * elevation_m) * ra
    rnl = (4.903e-9 * ((tmax_c + 273.16) ** 4 + (tmin_c + 273.16) ** 4) / 2.0
           * (0.34 - 0.14 * math.sqrt(max(ea, 0.0)))
           * (1.35 * min(rs_mj_m2 / rso, 1.0) - 0.35)) if rso > 0 else 0.0
    rn = (1.0 - 0.23) * rs_mj_m2 - rnl
    return max(0.0, (0.408 * delta * rn + gamma * 900.0 / (tmean + 273.0) * wind_m_s * (es - ea))
               / (delta + gamma * (1.0 + 0.34 * wind_m_s)))


def cloud_from_longwave(t_c: float, rh_pct: float, lw_w_m2: float) -> float:
    """Cloud cover from the long-wave the sky sends: how far it lies between what a clear
    sky would send (Brutsaert 1975) and what a black one would (Crawford and Duchon 1999,
    inverted)."""
    e_hpa = rh_pct / 100.0 * 6.1078 * math.exp(17.27 * t_c / (t_c + 237.3))   # Tetens, as the twin
    clear = 1.24 * (e_hpa / (t_c + 273.15)) ** (1.0 / 7.0)
    emitted = lw_w_m2 / (SIGMA * (t_c + 273.15) ** 4)
    return min(1.0, max(0.0, (emitted - clear) / (1.0 - clear)))


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


class RecordedClimate:
    """A real place's weather, replayed: daily records disaggregated to the 5-minute tick.

    The seeded `Climate` has the right shape and no history; this has history. Give it
    daily minimum and maximum air temperature, rain, mean humidity and sunshine — the
    NASA POWER fields `T2M_MIN`, `T2M_MAX`, `PRECTOTCORR`, `RH2M`, `ALLSKY_SFC_SW_DWN`
    — and the virtual farm lives through that season: McAllister Farm's spring of 2007,
    say, warm March, Easter freeze and all (sim/data/).

    * **Temperature** runs on half-cosines between the day's extremes, coldest at 05:00
      and warmest at 17:00 — the phase `Climate` uses, so every check calibrated
      against the synthetic world sees the same shape — and joins each evening's
      maximum to the next morning's minimum, so midnight has no step.
    * **Rain** falls in one spell a day, about 2.5 mm an hour, at an hour drawn from
      the seed and the date; the day's total is exact.
    * **Humidity** is the day's mean, lower in the warm afternoon, near saturation in
      rain.
    * **Reference ET** is Hargreaves' radiation formula, 0.0135 (T + 17.8) Rs, from the
      day's sunshine, spread over daylight and cut by rain as `Climate` cuts it.

    Like `Climate`, the hour of `when` is read as the site's local solar time — POWER's
    days are local solar days — so a world on recorded weather starts at a midnight.
    """

    def __init__(self, days, *, seed: int = 1):
        self.days = {d: dict(v) for d, v in days}
        if not self.days:
            raise ValueError("no days of weather")
        self.seed = seed
        self._seasonal: dict = {}

    @classmethod
    def from_csv(cls, path: str, *, seed: int = 1) -> "RecordedClimate":
        """`date,T2M_MIN,T2M_MAX,...` with `#` comment lines, as sim/data/ holds."""
        rows = []
        with open(path, encoding="utf-8") as h:
            lines = [line for line in h if not line.startswith("#")]
        names = lines[0].strip().split(",")
        for line in lines[1:]:
            if not line.strip():
                continue
            cells = line.strip().split(",")
            rows.append((_dt.date.fromisoformat(cells[0]),
                         {k: float(v) for k, v in zip(names[1:], cells[1:]) if v != ""}))
        return cls(rows, seed=seed)

    def _day(self, d: _dt.date) -> dict:
        v = self.days.get(d)
        if v is None:
            first, last = min(self.days), max(self.days)
            raise ValueError(f"{d} is outside the recorded weather ({first} to {last})")
        return v

    def _near(self, d: _dt.date) -> dict:
        """A day's record, or the nearest recorded neighbour at the record's edges."""
        return self.days.get(d) or self._day(min(self.days, key=lambda x: abs((x - d).days)))

    def _air(self, when: _dt.datetime) -> float:
        d, h = when.date(), when.hour + when.minute / 60.0
        today = self._day(d)
        if 5.0 <= h < 17.0:
            lo, hi, frac = today["T2M_MIN"], today["T2M_MAX"], (h - 5.0) / 12.0
            return lo + (hi - lo) * (1 - math.cos(math.pi * frac)) / 2.0
        if h >= 17.0:
            hi, lo, frac = today["T2M_MAX"], self._near(d + _dt.timedelta(days=1))["T2M_MIN"], (h - 17.0) / 12.0
        else:
            hi, lo, frac = self._near(d - _dt.timedelta(days=1))["T2M_MAX"], today["T2M_MIN"], (h + 7.0) / 12.0
        return hi + (lo - hi) * (1 - math.cos(math.pi * frac)) / 2.0

    def _rain_spell(self, d: _dt.date):
        total = self._day(d).get("PRECTOTCORR", 0.0)
        if total < 0.2:
            return None
        hours = min(18, max(1, math.ceil(total / 2.5)))
        start = random.Random(self.seed * 1_000_003 + d.toordinal()).randrange(0, 24 - hours + 1)
        return start, hours, total

    def step(self, when: _dt.datetime) -> "Weather":
        v = self._day(when.date())
        h = when.hour + when.minute / 60.0
        temp = self._air(when)
        spell = self._rain_spell(when.date())
        raining = spell is not None and spell[0] <= h < spell[0] + spell[1]
        rain = spell[2] / spell[1] * HOURS_PER_STEP if raining else 0.0
        mean = (v["T2M_MIN"] + v["T2M_MAX"]) / 2.0
        rh = v.get("RH2M", 70.0)
        humidity = max(92.0, rh) if raining else max(25.0, min(100.0, rh + 2.0 * (mean - temp)))
        daylight = max(0.0, math.sin(math.pi * (h - 6.0) / 12.0))
        et0_day = 0.0135 * (mean + 17.8) * v.get("ALLSKY_SFC_SW_DWN", 15.0) * 0.408
        et0 = max(0.0, et0_day) * daylight * HOURS_PER_STEP / (24.0 / math.pi)
        if raining:
            et0 *= 0.15
        return Weather(air_temp_c=round(temp, 2), relative_humidity=round(humidity, 1),
                       rain_mm=round(rain, 4), et0_mm=round(et0, 5), raining=raining)

    def _seasonal_temp(self, when: _dt.datetime) -> float:
        """The deep soil's driver: the mean air temperature of the month around."""
        d = when.date()
        if d not in self._seasonal:                 # per day: asked every tick
            near = [(x["T2M_MIN"] + x["T2M_MAX"]) / 2.0
                    for k in (d + _dt.timedelta(days=j) for j in range(-15, 16))
                    if (x := self.days.get(k)) is not None]
            self._seasonal[d] = sum(near) / len(near) if near else 10.0
        return self._seasonal[d]


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
    #: A layer of mulch over the soil, metres thick, with the low diffusivity of wood
    #: chips, bark or straw, mostly air. The day's heat reaches the soil through it, so the
    #: soil's daily wave is damped and delayed as if the soil were deeper: the confounder
    #: `sdk/siting.py`'s depth check must not read as a move. Depths stay measured from the
    #: soil's surface, as a probe's are.
    mulch_m: float = 0.0
    mulch_diffusivity: float = 2.0e-7         # dry wood chips: about 0.1 W m-1 K-1 over 0.5 MJ m-3 K-1
    #: Season totals, for anything that has to account for water: what drained below
    #: the root zone, what ran off a saturated bed, what the crop transpired.
    drained_mm: float = field(default=0.0, repr=False)
    runoff_mm: float = field(default=0.0, repr=False)
    et_mm: float = field(default=0.0, repr=False)

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
        self.et_mm += et

        # Free drainage of anything above field capacity.
        capacity_mm = self.field_capacity * self.depth_mm
        if water > capacity_mm:
            excess = water - capacity_mm
            drained = excess * min(1.0, self.drainage_per_hour * HOURS_PER_STEP)
            water -= drained
            self.drained_mm += drained

        full = self.saturation * self.depth_mm
        if water > full:
            self.runoff_mm += water - full
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
        mulch = self._mulch_layers()
        if self.temps is None:
            self.temps = [deep_c] * (HEAT_LAYERS + mulch)
        old = self.temps
        new = old[:]
        new[0] = surface_c
        if not mulch:
            ratio = (thermal_diffusivity(self.theta) * STEP.total_seconds()
                     / (HEAT_DZ * HEAT_DZ))
            for i in range(1, HEAT_LAYERS - 1):
                new[i] = old[i] + ratio * (old[i - 1] - 2.0 * old[i] + old[i + 1])
        else:
            # Under mulch the column has two materials; heat crosses each interface at
            # the harmonic mean of the two layers' diffusivities.
            soil = thermal_diffusivity(self.theta)
            k = [self.mulch_diffusivity if i < mulch else soil for i in range(len(old))]
            c = STEP.total_seconds() / (HEAT_DZ * HEAT_DZ)
            for i in range(1, len(old) - 1):
                up = 2.0 * k[i - 1] * k[i] / (k[i - 1] + k[i])
                down = 2.0 * k[i] * k[i + 1] / (k[i] + k[i + 1])
                new[i] = old[i] + c * (up * (old[i - 1] - old[i]) - down * (old[i] - old[i + 1]))
        new[-1] = deep_c
        self.temps = new

    def _mulch_layers(self) -> int:
        return int(round(self.mulch_m / HEAT_DZ))

    def temp_at(self, depth_m: float) -> float:
        """Temperature at a depth, linearly between the two nearest layers."""
        if self.temps is None:
            raise ValueError("the heat model has not been stepped yet")
        top = self._mulch_layers()                  # the soil's surface, under any mulch
        if depth_m <= 0:
            return self.temps[top]
        position = top + depth_m / HEAT_DZ
        lower = int(position)
        if lower >= len(self.temps) - 1:
            return self.temps[-1]
        frac = position - lower
        return self.temps[lower] * (1 - frac) + self.temps[lower + 1] * frac


@dataclass(frozen=True)
class Horizon:
    """One layer of soil in a `LayeredBed`, top down: how thick it is, its water limits
    as volume fractions, how fast it passes water when saturated, mm an hour, and the
    suction at a wetting front, mm, which draws water into a dry soil faster than that
    (Green and Ampt). With no suction, water soaks in only as fast as saturated soil
    passes it."""

    thickness_mm: float
    saturation: float
    field_capacity: float
    wilting_point: float
    ks_mm_per_h: float
    suction_mm: float = 0.0

    def __post_init__(self) -> None:
        if not 0 < self.wilting_point < self.field_capacity < self.saturation < 1:
            raise ValueError("0 < wilting point < field capacity < saturation < 1")
        if self.thickness_mm <= 0 or self.ks_mm_per_h <= 0 or self.suction_mm < 0:
            raise ValueError("a horizon has a thickness and passes some water")


#: A light topsoil and a compacted clay subsoil, the two a landscaped bed is often made
#: of: round values typical of a sandy loam and of a dense clay, assumed for the virtual
#: farm rather than taken from one soil survey. The clay's conductivity is a compacted
#: subsoil's, well below an undisturbed clay's.
SANDY_LOAM = {"saturation": 0.45, "field_capacity": 0.20, "wilting_point": 0.09,
              "ks_mm_per_h": 25.0, "suction_mm": 110.0}
COMPACTED_CLAY = {"saturation": 0.46, "field_capacity": 0.38, "wilting_point": 0.25,
                  "ks_mm_per_h": 1.0, "suction_mm": 300.0}


@dataclass
class LayeredBed(SoilBed):
    """A bed made of horizons: a few centimetres of brought-in topsoil over a subsoil the
    builders compacted, sod's own soil over the yard's, a raised bed's mix over the
    ground. A `SoilBed` is one bucket, so it cannot hold water perched over a layer that
    passes it slowly; this can.

    The soil is cut into layers `layer_mm` thick, each with its horizon's limits. Each
    five-minute tick:

    * **the crop takes water** from the root zone (`depth_mm`, here the roots' depth, not
      the soil's), from each layer in proportion to the water it can give;
    * **water drains down**, bottom layer first: a layer wetter than its field capacity
      passes the excess on as fast as its own conductivity at that wetness allows,
      `ks · ((θ − fc) / (sat − fc))³`, and no faster than the layer below takes water or
      has room for it; the bottom layer drains out of the soil;
    * **water soaks in** at the top as Green and Ampt have it: at the top horizon's
      saturated conductivity times `1 + suction · Δθ / F`, `Δθ` how much drier than
      saturation its top layer was when the water began to arrive and `F` what has soaked
      in since. A dry soil takes a shower fast at first, then more slowly. The water fills
      the top horizon from the top down, as a wetting front does, as far as it has room.
      Up to `surface_storage_mm` waits on the surface for the next tick, as in a lawn's
      hollows; the rest runs off.

    So a watering on topsoil over compacted clay fills the topsoil, stalls at the clay and
    perches there, and a long run puts more on than the bed can take. A probe reads its
    layer (`theta_at`); `theta` is the root zone's mean, which is what the crop and the
    heat model use. It starts at each layer's field capacity, a bed soaked and drained.
    """

    horizons: tuple = ()
    layer_mm: float = 25.0
    surface_storage_mm: float = 2.5
    ponded_mm: float = field(default=0.0, repr=False)
    #: What has soaked in since water began to arrive, and how dry the top was then.
    soaked_mm: float = field(default=0.0, repr=False)
    front_deficit: float = field(default=0.0, repr=False)
    #: Water that left the bottom of the soil, mm; `drained_mm` is what left the roots.
    deep_mm: float = field(default=0.0, repr=False)
    layers: list = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.horizons:
            raise ValueError("a layered bed has horizons")
        props = []
        for h in self.horizons:
            n = h.thickness_mm / self.layer_mm
            if abs(n - round(n)) > 1e-9:
                raise ValueError(f"a horizon is a whole number of {self.layer_mm} mm layers")
            props += [h] * int(round(n))
        roots = self.depth_mm / self.layer_mm
        if abs(roots - round(roots)) > 1e-9 or not 0 < round(roots) <= len(props):
            raise ValueError("the roots reach a whole number of layers, within the soil")
        self._props = props
        self._roots = int(round(roots))
        if self.layers is None:
            self.layers = [h.field_capacity for h in props]
        top = props[:self._roots]
        self.saturation = sum(h.saturation for h in top) / len(top)
        self.field_capacity = sum(h.field_capacity for h in top) / len(top)
        self.wilting_point = sum(h.wilting_point for h in top) / len(top)
        self._mean()

    def _mean(self) -> None:
        self.theta = sum(self.layers[:self._roots]) / self._roots

    def set_roots(self, depth_mm: float) -> None:
        """The roots reach `depth_mm` now, to the nearest whole layer (at least one, at most
        the soil): a crop growing through its season. The soil they reach holds whatever
        water it held; the limits of the root zone are its new layers'."""
        roots = max(1, min(len(self._props), int(round(depth_mm / self.layer_mm))))
        if roots == self._roots:
            return
        self._roots = roots
        self.depth_mm = roots * self.layer_mm
        top = self._props[:roots]
        self.saturation = sum(h.saturation for h in top) / len(top)
        self.field_capacity = sum(h.field_capacity for h in top) / len(top)
        self.wilting_point = sum(h.wilting_point for h in top) / len(top)
        self._mean()

    def theta_at(self, depth_m: float) -> float:
        """What a probe at `depth_m` reads: the water of the layer it sits in."""
        i = min(len(self.layers) - 1, max(0, int(depth_m * 1000.0 / self.layer_mm)))
        return self.layers[i]

    @property
    def stress(self) -> float:
        """The root zone's share of its available water that is gone, layer by layer."""
        gone = 0.0
        for theta, h in zip(self.layers[:self._roots], self._props):
            gone += 1.0 - max(0.0, min(1.0, (theta - h.wilting_point)
                                       / (h.field_capacity - h.wilting_point)))
        return gone / self._roots

    @property
    def stored_mm(self) -> float:
        return sum(self.layers) * self.layer_mm

    def step(self, weather: Weather, *, irrigation_mm: float = 0.0) -> float:
        dz, dt, n = self.layer_mm, HOURS_PER_STEP, len(self.layers)
        theta, props = self.layers, self._props

        et = weather.et0_mm * self.crop_coefficient * (1.0 - self.stress)
        can = [max(0.0, theta[i] - props[i].wilting_point) * dz for i in range(self._roots)]
        if et > 0 and sum(can) > 0:
            et = min(et, sum(can))
            total = sum(can)
            for i in range(self._roots):
                theta[i] -= et * can[i] / total / dz
            self.et_mm += et

        for i in reversed(range(n)):
            h = props[i]
            excess = theta[i] - h.field_capacity
            if excess <= 0:
                continue
            k = h.ks_mm_per_h * (excess / (h.saturation - h.field_capacity)) ** 3
            flux = min(k * dt, excess * dz)
            if i + 1 < n:
                below = props[i + 1]
                flux = min(flux, below.ks_mm_per_h * dt, (below.saturation - theta[i + 1]) * dz)
                theta[i + 1] += flux / dz
            else:
                self.deep_mm += flux
            theta[i] -= flux / dz
            if i == self._roots - 1:
                self.drained_mm += flux

        water = self.ponded_mm + weather.rain_mm + irrigation_mm
        top = props[0]
        if water <= 0:
            self.soaked_mm = 0.0                    # the surface is dry: the next is new
        elif self.soaked_mm == 0.0:
            self.front_deficit = max(0.0, top.saturation - theta[0])
        rate = top.ks_mm_per_h * (1.0 + top.suction_mm * self.front_deficit
                                  / max(self.soaked_mm, 1.0))
        soak = max(0.0, min(water, rate * dt))
        given = soak
        for i in range(n):                          # the wetting front, top down
            if props[i] is not top or given <= 0:
                break
            fill = min(given, (props[i].saturation - theta[i]) * dz)
            theta[i] += fill / dz
            given -= fill
        soak -= given
        self.soaked_mm += soak
        left = water - soak
        self.ponded_mm = min(left, self.surface_storage_mm)
        self.runoff_mm += left - self.ponded_mm
        for i in range(n):
            theta[i] = max(0.01, theta[i])
        self._mean()
        return self.theta


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
    jump that the rate check is right to flag. A farm's own timers, not fieldmesh
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


# ------------------------------------------------------------------ hoop house

@dataclass
class Tunnel:
    """An unheated single-poly tunnel: ground truth for the air inside it.

    The inside air is a small thermal mass, so it relaxes toward a target with a time
    constant of under an hour. The target is the outside air plus:

    * **by day**, the sun trapped under the plastic, scaled by daylight, cut by rain,
      and cut again by the share the sides let out when they are up;
    * **by night**, the heat the soil inside stored by day and gives back. Single poly
      passes long-wave radiation, so a clear sky draws much of that heat away, and
      clear nights can be the cold ones. When the weather knows its cloud
      (`Weather.cloud`, from the sky's long-wave), the gain runs from
      `clear_night_gain_c` under a clear sky to `cloudy_night_gain_c` under an overcast
      one, and a clear sky over plain polyethylene can pull the inside below the outside
      air. When rain is the only sign of cloud, as on the seeded farm, the gain shrinks
      from `night_gain_c` on a mild night to `cold_night_gain_c` at `cold_night_c` and
      below, standing in for a clear sky; under rain the full gain holds.

    The sides go up when the inside passes `vent_at_c` and down below `close_at_c`, as
    a grower would; `vent_at_c=None` is a tunnel nobody opens, which overheats.

    **The numbers are fitted to GreenLight** (open-questions Q28, modules/twin): its
    process model configured as an unheated single-poly tunnel, run on McAllister Farm's
    real spring and July weather. The first numbers here were plausible guesses — a 3 °C
    night gain, 18 °C of sun — and ran 1.6 °C too warm at night against it, which is a
    frost forecast for covered crops wrong in the dangerous direction. The defaults are an
    IR ("thermic") film, which most high-tunnel film now is; `FILMS["clear"]` is plain
    polyethylene, which on clear nights is no warmer than the open air. Neither the
    virtual tunnel nor GreenLight's has met a real one: these are what modules/advise/
    tunnel_gain.py must recover, and what a real tunnel's paired sensors will correct.
    """

    name: str
    night_gain_c: float = 1.0
    cold_night_gain_c: float = 1.0
    cold_night_c: float = -5.0
    solar_gain_c: float = 12.0
    #: The night gain under a clear and under an overcast sky, used when the weather says
    #: how cloudy it is (`Weather.cloud`) and in between in proportion; a negative clear-sky
    #: gain is an inversion. None keeps the cold-night rule above, which stands in for a
    #: clear sky where only rain is known, so a farm without cloud runs as it always has.
    clear_night_gain_c: float | None = 1.0
    cloudy_night_gain_c: float | None = 1.5
    vent_at_c: float | None = 27.0
    close_at_c: float = 20.0
    vent_cut: float = 0.75
    tau_h: float = 0.75
    inside_c: float | None = None
    sides_up: bool = False

    @classmethod
    def of(cls, name: str, film: str = "thermic", **kw) -> "Tunnel":
        """A tunnel covered in one of `FILMS`."""
        return cls(name=name, **{**FILMS[film], **kw})

    def night_gain(self, outside_c: float, overcast: bool, cloud: float | None = None) -> float:
        if cloud is not None and None not in (self.clear_night_gain_c, self.cloudy_night_gain_c):
            # The sky known: a clear one draws the soil's heat out through the film, and
            # under plain polyethylene can pull the inside below the outside air.
            return self.clear_night_gain_c + cloud * (self.cloudy_night_gain_c - self.clear_night_gain_c)
        if overcast:
            return self.night_gain_c
        share = min(1.0, max(0.0, (outside_c - self.cold_night_c) / 10.0))
        return self.cold_night_gain_c + share * (self.night_gain_c - self.cold_night_gain_c)

    def step(self, weather: Weather, daylight: float) -> float:
        outside = weather.air_temp_c
        solar = self.solar_gain_c * daylight * (0.25 if weather.raining else 1.0)
        if self.sides_up:
            solar *= 1.0 - self.vent_cut
        target = (outside + solar
                  + (1.0 - daylight) * self.night_gain(outside, weather.raining, weather.cloud))
        if self.inside_c is None:
            self.inside_c = target
        self.inside_c += (target - self.inside_c) * (1.0 - math.exp(-HOURS_PER_STEP / self.tau_h))
        if self.vent_at_c is not None:
            if self.inside_c > self.vent_at_c:
                self.sides_up = True
            elif self.inside_c < self.close_at_c:
                self.sides_up = False
        return self.inside_c


#: Fitted to GreenLight's tunnel per film (modules/twin, Q28): night-low error 0.87 °C
#: for IR film and 0.81 °C for clear, against 1.95 °C for the first guesses.
FILMS = {
    "thermic": {"night_gain_c": 1.0, "cold_night_gain_c": 1.0, "solar_gain_c": 12.0,
                "clear_night_gain_c": 1.0, "cloudy_night_gain_c": 1.5},
    "clear": {"night_gain_c": 0.0, "cold_night_gain_c": 0.0, "solar_gain_c": 10.0,
              "clear_night_gain_c": -0.5, "cloudy_night_gain_c": 1.5},
}


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
    tunnel_temp: dict = None    # tunnel name -> inside air temperature

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

    __slots__ = ("climate", "beds", "troughs", "tunnels", "when", "start",
                 "_pending_mm", "irrigation")

    def __init__(self, *, start: _dt.datetime, climate: Climate | None = None,
                 beds=(), troughs=(), tunnels=()):
        if start.tzinfo is None or start.utcoffset() != _dt.timedelta(0):
            raise ValueError("start must be timezone-aware UTC (§2)")
        self.start = start
        self.when = start
        self.climate = climate or Climate()
        self.beds = {b.name: b for b in beds}
        self.troughs = {t.name: t for t in troughs}
        self.tunnels = {t.name: t for t in tunnels}
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
        for tunnel in self.tunnels.values():
            tunnel.step(weather, daylight)
        truth = Truth(
            when=self.when,
            weather=weather,
            soil={n: round(b.theta, 5) for n, b in self.beds.items()},
            soil_stress={n: round(b.stress, 4) for n, b in self.beds.items()},
            trough_l={n: round(t.level_l, 2) for n, t in self.troughs.items()},
            trough_fraction={n: round(t.level_fraction, 4)
                             for n, t in self.troughs.items()},
            # From the soil's surface down: a sensor's depth is never into the mulch.
            soil_temp={n: tuple(b.temps[b._mulch_layers():]) for n, b in self.beds.items()},
            tunnel_temp={n: round(t.inside_c, 2) for n, t in self.tunnels.items()},
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

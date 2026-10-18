#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Soil-moisture advisory — layer 2 (spec v0.1 §11; open-questions Q12).

Each morning, for each bed: water today and how much, wait for the rain that is coming,
it will need water in a day or two, it is too wet, or it has enough — and when it cannot
say, why not. Read-only, so it ships without commands, and Q12's other reason for it: a
season of its advice, kept as decision events (§7.7), is the irrigation module's evidence
base before that module exists.

The arithmetic is FAO-56's root-zone water balance, read from the probes rather than
modelled:

* **total available water** `TAW = (field capacity − wilting point) × root depth`;
* **depletion** `Dr = (field capacity − θ) × root depth`, θ the root zone's water;
* water when `Dr ≥ p × TAW`, `p` the fraction a crop can lose before it is stressed
  (FAO-56 puts most vegetables between 0.3 and 0.5; the default is a third), back up to
  field capacity — `Dr` millimetres.

**The probes are found, not configured.** A bed's probes are the soil-moisture series
whose device was installed in that bed when it took the reading (§4.1), at the depth its
installation says. Each stands for the soil from halfway to the probe above it to
halfway to the one below, and only the part inside the root zone counts — so a probe
lifted out of one bed and pushed into another changes both beds' advice on the day it
moves, and a probe deeper than the roots counts for nothing.

**Quality decides what is read.** Only readings the health checks had passed by the time
of the advice count (`State.quality_as_of`), so a stuck or drifting probe does not water
a bed; a bed whose probes are all flagged gets "check the probes", not advice built on a
broken one. Rain coming is read from a forecast datastream in the log (Q26), so the
forecast a decision rested on is in the log beside it.

Every advice is a CEL rule judged through layer 1 (`modules/rules`), advisory, and one
decision event is written per bed per call: the morning's record, kept whether or not
it changes.

    advisor = Advisor(log)
    advisor.advise(state, beds, at=morning, forecast=rain_forecast_id)
"""
from __future__ import annotations

import datetime as _dt
import functools
import math
import os
import sys
from dataclasses import dataclass, field, replace
from uuid import UUID

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
import i18n  # noqa: E402
import rules as R  # noqa: E402
import vocab as V  # noqa: E402
from model import SURFACES, DatastreamKind, Usable  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "soilwater")

HOUR = _dt.timedelta(hours=1)
#: How far back the readings the drying rate is measured from reach: two whole days, and
#: the two hours either side of each day's ends (`_drying_mm_per_day`).
DRYING_WINDOW_H = 52.0
NO_ESTIMATE = 1e6
#: What grows in a bed, in a word.
PLANTINGS = ("vegetables", "flowers", "shrubs", "turf", "trees", "mixed")
#: Two probes in one bed whose learned field capacities differ by this much are in two
#: soils: several times the spread of one probe's drain-downs (about 0.02), and about a
#: texture class apart (a sandy loam holds roughly 0.20, a loam 0.27).
LAYER_GAP = 0.08


@dataclass(frozen=True)
class Bed:
    """One bed the advisory looks after: its land id (the feature its probes are
    installed in), its soil's water limits as volume fractions, and its crop's root
    depth and depletion fraction. The limits come from a soil test or SSURGO
    (`tools/soil_survey.py` reads both from the survey for a point).

    A bed whose soil changes with depth can say so: `layers` are `(bottom_m,
    field_capacity, wilting_point)`, top down, from a soil test of each layer or the
    survey's horizons; below the last, and for a bed with none, the bed's own two
    values stand."""

    feature: UUID
    field_capacity: float
    wilting_point: float
    root_depth_mm: float = 300.0
    depletion_fraction: float = 1 / 3
    #: The share of the available water whose loss leaves the crop short. The advice waters
    #: at `depletion_fraction`, and also when, drying as it has been, the bed would pass this
    #: before the next morning's look: a bed with little water to spare can go from short of
    #: its refill point to past half its water in one hot day. Half is FAO-56's depletion
    #: fraction for most field crops. Over thirty summers (README) it cut the shallow yard's
    #: short summers from 18 to 8, and its hours short from 407 to 141, for 5% more water,
    #: and left the deeper backtest bed as it was.
    #: Set to `depletion_fraction`, the advice looks ahead to the refill point itself: in a
    #: first run the shallow yard was short in 2 summers of 30, never more than 12 hours,
    #: and the deeper bed never, but the deeper one took 28% more water.
    short_fraction: float = 0.5
    #: The depletion fraction while any planting is in its initial stage, its few roots
    #: mostly in the soil the sun dries; None keeps `depletion_fraction` throughout. A
    #: seedbed is watered lightly and often (`young`). Among older plantings, it is the
    #: refill point of the young one's roots alone (`timing_depth_mm`); the older keep
    #: theirs. On the simulator of 2026-10-16, tomatoes' first month went short in 25
    #: summers of 30 without it, 9 with it, for 4% more water; held until the roots pass
    #: `YOUNG_ROOTS_MM`, tomatoes by probes went from 41 hours short to 1 and lettuce from
    #: 162 to none on one draw of the noise, from 112 to 68 and 366 to 43 on another.
    young_fraction: float | None = 0.2
    #: The share of the rain that reaches the bed: 0 under a tunnel or a roof, less under a
    #: canopy or plastic mulch. None: all of it, unless its probes show it is covered, where
    #: the farm has a rain gauge (`covered_by_its_probes`).
    rain_share: float | None = None
    #: With a tension sensor beside a probe, the tension field capacity is read at, kPa:
    #: a third of a bar, 33, for most soils; nearer 10 in a sand (`retention.py`).
    capacity_kpa: float = 33.0
    skip_rain_mm: float = 10.0
    wet_margin: float = 0.02
    soon_days: float = 2.0
    stale_after_h: float = 6.0
    #: The series of the valve that waters this bed, open or shut (`vocab.VALVE_OPEN`),
    #: when a controller reports it — an OpenSprinkler's station through the MQTT bridge.
    #: With it the watering check can tell a blocked line from a bed nobody watered.
    valve: UUID | None = None
    #: Learn the bed's field capacity from its own probes (`learned_capacity`), the
    #: configured value standing until there is enough to learn from.
    learn: bool = True
    #: What covers the soil (`model.SURFACES`: bare, organic or inorganic mulch, plastic,
    #: turf) and what grows in it (`PLANTINGS`). The bed's record, written into each
    #: decision, so a season's advice can be read against what the bed was: a mulched
    #: shrub bed dries slower than bare vegetables, and the probes see that, not this.
    surface: str | None = None
    planting: str | None = None
    layers: tuple = ()
    #: For a bed with no probe, advised from the farm's station (`weather_balance`): the
    #: crop's coefficient on reference ET (FAO-56's Kc; 1.0 a full canopy, 0.95 a
    #: cool-season lawn), and how fast its watering puts water down, mm an hour, so the
    #: valve's minutes become millimetres.
    crop_coefficient: float = 1.0
    application_mm_per_h: float | None = None
    #: The crop growing in it and the day it was sown, for a crop that grows through its
    #: season: its root depth and its crop coefficient then follow FAO-56's curve for the
    #: day (`crop_day`), in place of `root_depth_mm` and `crop_coefficient`. A crop from
    #: `CROPS`; an established lawn (`turf_cool`, `turf_warm`) needs no date.
    crop: str | None = None
    planted: _dt.date | None = None
    #: Plantings at different stages side by side, in place of `crop` and `planted`:
    #: `((crop, planted), ...)`, a succession sown a few weeks apart, a replant in a gap,
    #: lettuce under tomatoes. The bed's roots then span a range (`grown`): it is watered
    #: when its youngest roots have used their share, and refilled to its oldest roots'
    #: depth; its crop coefficient is the plantings' mean. A planting may name the probes
    #: set among it, `(crop, planted, (sensor id, ...))`: the youngest planting's own probes
    #: then time the watering, and the oldest's, with any no planting names, the refill.
    plantings: tuple = ()
    #: A correction to the balance's ET, from a probe's rate (`_corrected`): it scales the
    #: day's crop coefficient, whatever the crop's curve makes it.
    et_scale: float = 1.0
    #: The crop's water use against its curve's, where the farm has measured it: from its
    #: canopy's cover in a photo, or a satellite's ET (OpenET). It scales the weather
    #: balance's crop coefficient; the margin (`WEATHER_MARGIN`) stays on top of it.
    use_scale: float = 1.0
    #: How deep the soil lets roots go, mm: a hardpan, compacted subsoil, rock, the bottom
    #: of a raised bed. Roots stop there whatever the crop (`grown`), and a probe at that
    #: depth or below it reads soil they do not enter, so it is not counted.
    rooting_limit_mm: float | None = None
    #: Each planting's clock, `{(crop, planted): {day: growing days}}`
    #: (`thermal.growing_days`): how far through its curve a sown crop is on each day by the
    #: season's warmth, set by the advisor from the farm's station and its normal year.
    #: Without it, the calendar.
    clock: dict | None = field(default=None, compare=False, repr=False)
    #: The depth the watering is timed by, mm, where it is shallower than the root zone the
    #: refill is measured over: the youngest planting's roots (`grown`), or where the probes
    #: show the roots stop (`rooted`). None: the root zone's own depth.
    timing_depth_mm: float | None = None
    #: For a bed advised by the weather, the land of a bed nearby whose probes correct its
    #: balance (`reference_factor`): how fast that bed's root zone dries on dry days, against
    #: what the balance says for the same days. A bed of the same crop, on the same station.
    reference: UUID | None = None

    def __post_init__(self) -> None:
        if not 0 < self.wilting_point < self.field_capacity < 1:
            raise ValueError("0 < wilting point < field capacity < 1, as volume fractions")
        if self.root_depth_mm <= 0:
            raise ValueError("a root zone has a depth")
        if not 0 < self.depletion_fraction < 1:
            raise ValueError("the depletion fraction is between 0 and 1 (FAO-56's p)")
        if not self.depletion_fraction <= self.short_fraction < 1:
            raise ValueError("a crop is short at or past its refill point, before all its water is gone")
        if self.surface is not None and self.surface not in SURFACES:
            raise ValueError(f"a bed's surface is one of {SURFACES}")
        if self.planting is not None and self.planting not in PLANTINGS:
            raise ValueError(f"a bed's planting is one of {PLANTINGS}")
        if self.crop_coefficient <= 0 or (self.application_mm_per_h is not None
                                          and self.application_mm_per_h <= 0):
            raise ValueError("a crop coefficient and an application rate are positive")
        if self.crop is not None and self.plantings:
            raise ValueError("a bed has a crop or plantings, not both")
        if any(len(p) not in (2, 3) for p in self.plantings):
            raise ValueError("a planting is (crop, planted) or (crop, planted, probes)")
        for crop, planted in plantings_of(self):
            if crop not in CROPS:
                raise ValueError(f"unknown crop {crop!r}; known: {', '.join(sorted(CROPS))}")
            if planted is None and CROPS[crop]["season_days"] > 0:
                raise ValueError("a sown crop grows from the day it was sown: give planted")
        if self.rooting_limit_mm is not None and self.rooting_limit_mm <= 0:
            raise ValueError("a rooting limit is a depth, mm")
        if self.reference is not None and self.reference == self.feature:
            raise ValueError("a bed cannot be its own reference")
        bottoms = [layer[0] for layer in self.layers]
        if bottoms != sorted(set(bottoms)) or any(
                not (b > 0 and 0 < wp < fc < 1) for b, fc, wp in self.layers):
            raise ValueError("layers are (bottom_m, field capacity, wilting point), top down, "
                             "with 0 < wilting point < field capacity < 1")

    def limits_at(self, depth_m: float) -> tuple[float, float]:
        """The field capacity and wilting point of the soil at a depth."""
        for bottom, fc, wp in self.layers:
            if depth_m <= bottom:
                return fc, wp
        return self.field_capacity, self.wilting_point

    @property
    def taw_mm(self) -> float:
        return (self.field_capacity - self.wilting_point) * self.root_depth_mm

    @property
    def raw_mm(self) -> float:
        return self.depletion_fraction * self.taw_mm

    @property
    def timing_raw_mm(self) -> float:
        """The refill point of the zone the watering is timed by (`timing_depth_mm`)."""
        depth = self.timing_depth_mm if self.timing_depth_mm is not None else self.root_depth_mm
        return self.depletion_fraction * (self.field_capacity - self.wilting_point) * depth


def plantings_of(bed: Bed) -> tuple:
    """`((crop, planted), ...)`: the bed's plantings, or its one crop."""
    if bed.plantings:
        return tuple((p[0], p[1]) for p in bed.plantings)
    return ((bed.crop, bed.planted),) if bed.crop is not None else ()


def planting_probes(bed: Bed) -> dict:
    """`{(crop, planted): frozenset(sensor ids)}`: the probes set among each planting that
    names them (a planting's third item)."""
    return {(p[0], p[1]): frozenset(p[2]) for p in bed.plantings if len(p) > 2 and p[2]}


# ------------------------------------------------------------ the crop through its season

#: FAO-56's crops (`data/fao56-crops.csv`, `data/MANIFEST.csv`): each stage's days (Table 11),
#: the crop coefficient at sowing, mid-season and the end (Table 12), and the range of its
#: maximum root depth (Table 22).
CROP_DATA = os.path.join(HERE, "data", "fao56-crops.csv")
#: The 2025 revision (FAO-56 Rev.1, `data/fao56rev-crops.csv`): each crop's coefficients,
#: maximum root depth and depletion fraction, its base and upper temperatures, and for the
#: crops with field-observed degree-days, each stage's (Table 6.11).
CROP_DATA_REV = os.path.join(HERE, "data", "fao56rev-crops.csv")
#: The roots' depth at sowing: FAO-56 Annex 8 has 0.15 to 0.20 m for many annual crops, "the
#: depth of seed placement plus an additional depth of soil that may contribute water to the
#: seed"; the shallow end.
ROOT_AT_SOWING_MM = 150.0


def _load_crops(path: str = CROP_DATA, revised: str = CROP_DATA_REV) -> dict:
    """`{crop: ...}`: the 1998 edition's stage days for every crop, and for the sown crops
    the 2025 revision's coefficients, root depth, depletion fraction and temperatures, and
    its stages in degree-days where it gives them. A crop the revision gives two seasons for
    is also there as `crop:variant` (`tomato:processing`, `lettuce:long`); the plain name
    is its default, the first."""
    import csv
    out = {}
    with open(path, encoding="utf-8") as h:
        for r in csv.DictReader(h):
            stages = [float(r[k]) for k in ("initial_days", "development_days", "mid_days", "late_days")]
            out[r["crop"]] = {"stages": stages, "season_days": sum(stages),
                              "kc": (float(r["kc_initial"]), float(r["kc_mid"]), float(r["kc_end"])),
                              "root_mm": 1000.0 * float(r["root_max_shallow_m"]),
                              "p": float(r["depletion_fraction"]), "gdd_stages": None,
                              "thresholds": None, "edition": 1998}
    with open(revised, encoding="utf-8") as h:
        for r in csv.DictReader(h):
            # A crop the 1998 edition has no row for (the revision's mown lawn) is established:
            # no stages, its mid-season value all year, as the 1998 lawns are.
            base = out.get(r["crop"]) or {"stages": [0.0] * 4, "season_days": 0.0}
            gdd = ([float(r[k]) for k in ("gdd_ini", "gdd_dev", "gdd_mid", "gdd_late")]
                   if r["gdd_ini"] else None)
            entry = {**base,
                     "kc": (float(r["kc_ini"]), float(r["kc_mid"]), float(r["kc_end"])),
                     "root_mm": 1000.0 * float(r["root_shallow_m"]),
                     "p": float(r["depletion_fraction"]), "gdd_stages": gdd,
                     "thresholds": (float(r["tbase_c"]), float(r["tupper_c"])), "edition": 2025}
            if r["variant"]:
                out[f'{r["crop"]}:{r["variant"]}'] = entry
            if r["default"] == "1":
                out[r["crop"]] = entry
    return out


CROPS = _load_crops()


def crop_day(crop: str, days: float, gdd: float | None = None) -> tuple[float, float]:
    """FAO-56's crop coefficient and root depth (mm) for a crop `days` after sowing, or,
    for a crop whose stages the 2025 revision gives in degree-days (Table 6.11), when it has
    gathered `gdd` of them.

    The coefficient is its initial value through the initial stage, rises in a line to its
    mid-season value over the development stage, holds, and falls in a line to its end
    value over the late season (FAO-56 chapter 6; the revision's Table 6.1 and 6.2 values).
    The roots grow from `ROOT_AT_SOWING_MM` to the shallow end of the maximum depth's range
    over the development stage, reaching it as mid-season begins: the 1998 Annex 8's Eq. 8-1
    taken by time, as the revision's Example 8.3 still grows them, so a crop whose
    coefficient does not rise still roots. A garden bed is seldom deep, uniform soil, and a
    shallower root zone errs toward watering sooner."""
    c = CROPS[crop]
    k_ini, k_mid, k_end = c["kc"]
    deepest = c["root_mm"]
    if c["season_days"] == 0:
        return k_mid, deepest
    if gdd is not None and c["gdd_stages"] is not None:
        ini, dev, mid, late = c["gdd_stages"]
        t = max(0.0, gdd)
    else:
        ini, dev, mid, late = c["stages"]
        t = max(0.0, days)
    if t < ini:
        kc, grown = k_ini, 0.0
    elif t < ini + dev:
        grown = (t - ini) / dev
        kc = k_ini + grown * (k_mid - k_ini)
    elif t < ini + dev + mid:
        kc, grown = k_mid, 1.0
    elif t < ini + dev + mid + late:
        kc, grown = k_mid + (t - ini - dev - mid) / late * (k_end - k_mid), 1.0
    else:
        kc, grown = k_end, 1.0
    start = min(ROOT_AT_SOWING_MM, deepest)
    return kc, start + grown * (deepest - start)


#: FAO-56's basal crop coefficient at sowing, transpiration alone (Table 17: 0.15 for most
#: annual crops); later stages take the single coefficient less 0.05 (`basal_day`).
BASAL_AT_SOWING = 0.15


def basal_day(crop: str, days: float, gdd: float | None = None) -> float:
    """FAO-56's basal crop coefficient for the crop `days` after sowing (or `gdd`), its
    transpiration alone, for the simulator's dual coefficient: `BASAL_AT_SOWING` through
    the initial stage, rising in a line over development to the mid-season single
    coefficient less 0.05, holding, then falling to the end value less 0.05. An
    established crop (a lawn) holds its mid-season value less 0.05, as Table 17's
    cool-season turf, 0.90 against Table 12's 0.95."""
    c = CROPS[crop]
    k_ini, k_mid, k_end = c["kc"]
    b_mid = max(BASAL_AT_SOWING, k_mid - 0.05)
    b_end = max(BASAL_AT_SOWING, k_end - 0.05)
    if c["season_days"] == 0:
        return b_mid
    if gdd is not None and c["gdd_stages"] is not None:
        ini, dev, mid, late = c["gdd_stages"]
        t = max(0.0, gdd)
    else:
        ini, dev, mid, late = c["stages"]
        t = max(0.0, days)
    if t < ini:
        return BASAL_AT_SOWING
    if t < ini + dev:
        return BASAL_AT_SOWING + (t - ini) / dev * (b_mid - BASAL_AT_SOWING)
    if t < ini + dev + mid:
        return b_mid
    if t < ini + dev + mid + late:
        return b_mid + (t - ini - dev - mid) / late * (b_end - b_mid)
    return b_end


#: The advice's second look of the day, besides the morning's: a bed with little water
#: to spare can pass half of it by the afternoon (`backtest.py`). The module runs at both
#: hours (deploy/systemd/fieldmesh-module@soilwater.timer).
SECOND_CHECK_HOUR = 13


#: A planting stays young (`young`) while its roots are shallower than this, past its
#: initial stage if need be: the stage ends with the roots still the 15 cm they were sown
#: with and the crop beginning to use more, and on the simulator of 2026-10-16 the crops'
#: shortages by probes fell in the days after it. Every crop's roots pass it in their
#: development stage.
YOUNG_ROOTS_MM = 250.0


def young(bed: Bed, day: _dt.date) -> bool:
    """Whether any sown planting of the bed is young on `day`: in its crop's initial stage,
    or its roots still shallower than `YOUNG_ROOTS_MM`; its few roots in the top of the soil,
    its leaves not yet shading it."""
    for crop, planted in plantings_of(bed):
        if crop is None or planted is None or planted > day:
            continue
        c = CROPS.get(crop)
        if not (c and c["season_days"]):
            continue
        if 0 <= crop_days(bed, day, (crop, planted)) < c["stages"][0]:
            return True
        if crop_stage(bed, day, (crop, planted))[1] < YOUNG_ROOTS_MM:
            return True
    return False


def crop_days(bed: Bed, day: _dt.date, planting: tuple | None = None) -> float:
    """How far through its curve a planting of the bed (its crop by default) is on `day`,
    in days: by the season's warmth where the advisor has set its clock (`Bed.clock`) for a
    crop staged in days, else by the calendar."""
    crop, planted = planting if planting is not None else (bed.crop, bed.planted)
    if planted is None:
        return 0
    clock = (bed.clock or {}).get((crop, planted))
    if clock is not None and day in clock.get("days", {}):
        return clock["days"][day]
    return (day - planted).days


def crop_gdd(bed: Bed, day: _dt.date, planting: tuple | None = None) -> float | None:
    """The degree-days a planting has gathered by `day` since sowing, where its clock counts
    them (a crop the revision stages in degree-days); else None."""
    crop, planted = planting if planting is not None else (bed.crop, bed.planted)
    clock = (bed.clock or {}).get((crop, planted))
    if clock is None or day not in clock.get("gdd", {}):
        return None
    return clock["gdd"][day]


def crop_stage(bed: Bed, day: _dt.date, planting: tuple) -> tuple[float, float]:
    """`(crop coefficient, root depth mm)` of one of the bed's plantings on `day`."""
    return crop_day(planting[0], crop_days(bed, day, planting), crop_gdd(bed, day, planting))


def crop_p(bed: Bed, day: _dt.date) -> float:
    """The share of its available water the bed's crop uses freely before it uses less
    (FAO-56's `p`, its Table 22 and the revision's 8.1): the sown plantings' mean, or 0.5,
    FAO-56's figure for many crops, with none named. Not the advice's refill point
    (`Bed.depletion_fraction`), which waters sooner on purpose."""
    ps = [CROPS[c]["p"] for c, planted in plantings_of(bed)
          if c in CROPS and (planted is None or planted <= day)]
    return sum(ps) / len(ps) if ps else 0.5


def basal_of(bed: Bed, day: _dt.date) -> float | None:
    """The sown plantings' mean basal coefficient on `day` (`basal_day`), or None with no
    crop named."""
    found = [(c, planted) for c, planted in plantings_of(bed)
             if c in CROPS and planted is not None and planted <= day]
    if not found:
        return None
    return sum(basal_day(c, crop_days(bed, day, (c, planted)), crop_gdd(bed, day, (c, planted)))
               for c, planted in found) / len(found)


#: The weather balance's surface layer, for a bed's evaporation by FAO-56's dual
#: coefficient (`weather_balance`): its depth, its readily evaporable water, the most crop
#: and wet surface together lose (Eq. 72 at the standard wind and humidity), and the
#: crop's height for its canopy cover (Eq. 76).
EVAPORATION_LAYER_M = 0.10
REW_MM = 9.0
KC_MAX = 1.2
CROP_HEIGHT_M = 0.3


def grown(bed: Bed, day: _dt.date) -> Bed:
    """The bed as its crop is on `day`: its root depth and crop coefficient from the crop's
    curve, the roots no deeper than the soil lets them go (`rooting_limit_mm`). With
    plantings at different stages, the deepest planting's roots, the youngest's as the
    depth the watering is timed by (`timing_depth_mm`), and the plantings' mean crop
    coefficient. A bed with no crop named keeps its own root depth, to the same limit."""
    root_mm, kc, timing = bed.root_depth_mm, bed.crop_coefficient, None
    # A planting not yet sown has no roots to time the watering by.
    found = [(crop, planted) for crop, planted in plantings_of(bed)
             if planted is None or planted <= day]
    if found:
        stages = [crop_stage(bed, day, (crop, planted)) for crop, planted in found]
        kc = sum(k for k, _ in stages) / len(stages)
        root_mm, timing = max(r for _, r in stages), min(r for _, r in stages)
    if bed.rooting_limit_mm is not None:
        root_mm = min(root_mm, bed.rooting_limit_mm)
        timing = min(timing, bed.rooting_limit_mm) if timing is not None else None
    if timing is not None and timing >= root_mm:
        timing = None
    if (root_mm, kc, timing) == (bed.root_depth_mm, bed.crop_coefficient, bed.timing_depth_mm):
        return bed
    return replace(bed, root_depth_mm=root_mm, crop_coefficient=kc, timing_depth_mm=timing)


#: Roots seen by their probes, over the last `ROOT_SIGN_DAYS`. A probe's field capacity here
#: is the lower of the bed's and its own (learned or measured): one under steady drainage
#: from above learns it a little high. Its dry days are those that started no wetter than
#: that and were not wetted. Over `ROOT_SIGN_MIN_DAYS` of them or more, a probe whose soil
#: fell less than `ROOT_SIGN_RATE` a day is level: nothing draws on it. One that fell faster
#: and went `ROOT_SIGN_BELOW` under its field capacity has roots at it: a soil just past
#: field capacity still drains about that fast, but nothing but roots (and, near the
#: surface, the sun) takes it well below. Growers read the same thing off a probe as the
#: stair-step, falling by day and level at night, moving deeper as a crop grows
#: (docs/notes/root-depth.md).
ROOT_SIGN_DAYS = 14
ROOT_SIGN_MIN_DAYS = 3
ROOT_SIGN_RATE = 0.002
ROOT_SIGN_BELOW = 0.02
#: How far past a probe the crop's curve must say the roots are, mm, before a level probe
#: counts against it: the curve is a typical crop's, a week early or late, and roots near
#: their front draw little.
ROOT_SIGN_PAST_MM = 150.0
#: A stop seen at the same probe on `ROOT_HOLD_MORNINGS` of the last `ROOT_HOLD_DAYS`
#: mornings stands (`Advisor._held`), on mornings that cannot see it too: waterings leave
#: too few dry days to judge by, or roots right above draw a probe under the stop.
ROOT_HOLD_DAYS = 7
ROOT_HOLD_MORNINGS = 3


def _sign_days(at: _dt.datetime) -> list:
    """The last `ROOT_SIGN_DAYS` days, newest first, as `(begin, end)`: the 24 hours before
    `at`, and so on back."""
    return [(at - (k + 1) * 24 * HOUR, at - k * 24 * HOUR) for k in range(ROOT_SIGN_DAYS)]


def root_signs(state, bed: Bed, at: _dt.datetime, capacities: dict | None = None) -> list:
    """`[(depth_m, falling per day, roots there: True, False, or None)]` for each of the
    bed's probes, shallowest first: a falling probe has roots when it has gone
    `ROOT_SIGN_BELOW` under field capacity, and None until then. None too when its dry days
    are too few. `capacities`, `{datastream id: learned field capacity}`, keeps each probe's
    for the rest of the morning's look (`_bed_context`). (Reading roots by the day's fall
    against the night's, the stair-step, was an option until 2026-10-17: on the simulator it
    told a pan from none no better.)"""
    import bisect
    out = []
    windows = _sign_days(at)
    for ds, depth in probes_of(state, bed, at):
        inst = state.installation_of(ds.sensor, at)
        since = at - _dt.timedelta(days=ROOT_SIGN_DAYS + 1)
        every = sorted((o for o in state.live_observations_of(ds.id)
                        if o.received_at <= at and inst.installed_at <= o.measured_at <= at
                        and isinstance(o.result, (int, float))
                        and not isinstance(o.result, bool)), key=lambda o: o.measured_at)
        rows = [(o.measured_at, float(o.result)) for o in every if o.measured_at >= since
                and state.quality_as_of(o.id, at)[0] is Usable.GOOD]
        under, wilting = bed.limits_at(depth)
        own = _capacity(state, bed, ds, depth, wilting, every, at)
        if capacities is not None:
            capacities[ds.id] = own
        if own is not None:
            under = min(under, own["field_capacity"])
        stamps = [u for u, _ in rows]

        def near(t):
            lo = bisect.bisect_left(stamps, t - 2 * HOUR)
            values = [v for _, v in rows[lo:bisect.bisect_right(stamps, t + 2 * HOUR)]]
            return sum(values) / len(values) if len(values) >= 2 else None
        falls, low = [], under
        for begin, end in windows:
            a, b = near(begin), near(end)
            if a is None or b is None or a > under + 0.01:
                continue
            day = [v for _, v in
                   rows[bisect.bisect_right(stamps, begin):bisect.bisect_right(stamps, end)]]
            means = [sum(w) / 3.0 for w in zip(day, day[1:], day[2:])]
            if any(m > a + 0.02 for m in means):
                continue
            falls.append(a - b)
            low = min(low, b)
        if len(falls) < ROOT_SIGN_MIN_DAYS:
            out.append((depth, 0.0, None))
            continue
        rate = sum(falls) / len(falls)
        if rate < ROOT_SIGN_RATE:
            there = False
        else:
            there = True if low <= under - ROOT_SIGN_BELOW else None
        out.append((depth, round(rate, 4), there))
    return out


def rooted(curve_mm: float, signs: list,
           held: tuple | None = None) -> tuple[float, float, float | None]:
    """The depth the advice times its watering by, mm, from the crop's curve and what its
    probes show (`root_signs`): `(depth, deepest probe roots are seen at, probe they seem
    not to reach or None)`. A probe the curve says the roots passed `ROOT_SIGN_PAST_MM` ago
    that stays level, under a shallower one that has roots, is a sign they stop between the
    two: the advice then times its watering by half way. The refill is still measured to
    the curve's depth: below a real stop the probes read wet and add little to it, and
    roots that are there after all still get their water. So the probes only ever make
    the advice water sooner, never less: roots seen deeper than the curve may be the soil
    drying by other ways, and are not counted.

    `held` is `(seen, blocked)`, a stop seen on enough recent mornings to stand
    (`Advisor._held`) on mornings that cannot see it."""
    seen = max((d for d, _, there in signs if there), default=0.0)
    found = (curve_mm, seen, None)
    for d, _, there in signs:
        if there is False and seen > 0.0 and d > seen \
                and d * 1000.0 + ROOT_SIGN_PAST_MM <= curve_mm:
            found = (min(curve_mm, round(500.0 * (seen + d), 1)), seen, d)
            break
    if held is not None:
        was_seen, blocked = held
        depth = min(curve_mm, round(500.0 * (was_seen + blocked), 1))
        if blocked * 1000.0 + ROOT_SIGN_PAST_MM <= curve_mm and depth < found[0]:
            return depth, was_seen, blocked
    return found


#: A probe out of the soil reads the air, drier than any soil it could be in. Below the
#: surface only roots dry soil, and they stop at its wilting point; the sun dries its
#: evaporation layer further, and FAO-56 takes that layer, the top 0.10 to 0.15 m, to dry
#: to "halfway between oven dry (no water left) and wilting point" (Rev.1 Eq. 7.5, 1998's
#: Eq. 73). A reading more than `OUT_OF_SOIL_MARGIN` below that, a factory calibration's
#: usual error, is a probe out of the soil or in an air gap (`soil_floor`), and is not
#: read. In sand, whose wilting point is near the margin, a probe in the air cannot be
#: told this way from one in dry sand.
EVAPORATION_LAYER_M = 0.15
OUT_OF_SOIL_MARGIN = 0.03


def soil_floor(depth_m: float, wilting_point: float) -> float:
    """The driest a probe at `depth_m` can read in soil with this wilting point and be in
    it: half the wilting point within FAO-56's evaporation layer, the wilting point below,
    less `OUT_OF_SOIL_MARGIN`."""
    dried = 0.5 if depth_m <= EVAPORATION_LAYER_M + 1e-9 else 1.0
    return wilting_point * dried - OUT_OF_SOIL_MARGIN


#: A bed under cover, seen by its probes: through the last `COVER_STORMS` storms of
#: `COVER_STORM_MM` or more in the farm's rain gauge, while its valve stayed shut, no probe
#: in its root zone rose `COVER_RISE` (a mean of three readings, against the three hours
#: before) by `COVER_AFTER_H` after the rain's end. A storm that
#: size wets an open bed's soil down to its probes; a tunnel's probes do not see it. Only a
#: bed whose valve reports its waterings is judged: without it a watering could not be told
#: from the rain. Lighter rain may not reach a probe even in the open, and a share between
#: none and all is not learned: set `Bed.rain_share`.
COVER_STORM_MM = 15.0
COVER_STORMS = 3
COVER_RISE = 0.03
COVER_AFTER_H = 12.0
COVER_DAYS = 90
COVER_GAP_H = 6.0


def covered_by_its_probes(rain_rows: list, probe_rows: list, watered: list) -> tuple:
    """`(covered: True or None, storms judged)`. `rain_rows` `[(hour, mm)]` from the farm's
    gauge; `probe_rows` each in-zone probe's `[(time, θ)]`; `watered` `[(from, to)]` times
    the bed was watered."""
    spells = []
    for t, mm in sorted(rain_rows):
        if mm <= 0:
            continue
        if spells and (t - spells[-1][1]) / HOUR <= COVER_GAP_H:
            spells[-1] = (spells[-1][0], t, spells[-1][2] + mm)
        else:
            spells.append((t, t, mm))
    judged = []
    for start, end, mm in spells:
        if mm < COVER_STORM_MM:
            continue
        lo, hi = start - 3 * HOUR, end + COVER_AFTER_H * HOUR
        if any(a < hi and b > lo for a, b in watered):
            continue
        rose, seen = False, False
        for rows in probe_rows:
            before = [v for t, v in rows if start - 3 * HOUR <= t < start]
            after = [v for t, v in rows if start <= t <= end + COVER_AFTER_H * HOUR]
            means = [sum(w) / 3.0 for w in zip(after, after[1:], after[2:])]
            if before and means:
                seen = True
                rose = rose or max(means) - sum(before) / len(before) >= COVER_RISE
        if seen:
            judged.append(rose)
    last = judged[-COVER_STORMS:]
    if len(last) == COVER_STORMS and not any(last):
        return True, len(judged)
    return None, len(judged)


#: The advice, most urgent first; the first that holds is the morning's decision.
def rules_for(bed: Bed, timing_fraction: float | None = None) -> list:
    """The rules for `bed`; `timing_fraction`, the zone the watering is timed by its own
    depletion fraction, where it is not the bed's."""
    timing_p = timing_fraction or bed.depletion_fraction
    timing_raw = bed.timing_raw_mm * timing_p / bed.depletion_fraction
    p = {"raw_mm": round(bed.raw_mm, 2), "short_mm": round(bed.short_fraction * bed.taw_mm, 2),
         "timing_raw_mm": round(timing_raw, 2),
         "timing_short_mm": round(max(bed.short_fraction, timing_p) / timing_p * timing_raw, 2),
         "skip_rain_mm": bed.skip_rain_mm,
         "stale_after_h": bed.stale_after_h, "soon_days": bed.soon_days}
    usable = "has_probe && has_reading && usable && hours_since_reading <= stale_after_h"
    # Due today: past the refill point, or, drying as it is, short (`Bed.short_fraction` of
    # its water gone) before tomorrow's look. The advice comes once a morning, so a bed with
    # little water to spare that is short of its refill point today can be past half its
    # water by the next morning. Or the zone the watering is timed by, the youngest
    # planting's roots or the soil above where roots stop, is past its own refill point.
    timed = ("(timing_depletion_mm >= timing_raw_mm"
             " || timing_depletion_mm + timing_drying_mm_per_day >= timing_short_mm)")
    due = f"(depletion_mm >= raw_mm || {timed} || depletion_mm + drying_mm_per_day >= short_mm)"
    weather_due = f"(depletion_mm >= raw_mm || {timed})"
    weather = "by_weather"
    rules = [
        R.Rule("soil-weather-unseen", "1", f"{weather} && weather_missing_days >= 2", p,
               alert_key="soilwater.weather_unseen",
               message_params={"days": "weather_missing_days", "hours": "probe_silent_hours"},
               message_variants=(("anchored", "soilwater.weather_unseen_anchored"),)),
        R.Rule("soil-weather-rain-coming", "1",
               f"{weather} && {weather_due} && rain_reaching_mm >= skip_rain_mm", p,
               alert_key="soilwater.weather_rain_coming",
               message_params={"used": "used_percent", "rain": "rain_mm",
                               "hours": "probe_silent_hours", "et": "et_percent"},
               message_variants=(("anchored", "soilwater.weather_rain_coming_anchored"),
                                 ("corrected", "soilwater.weather_rain_coming_corrected"))),
        R.Rule("soil-weather-water-now", "1", f"{weather} && {weather_due}", p,
               alert_key="soilwater.weather_water_now",
               message_params={"used": "used_percent", "mm": "refill_mm",
                               "hours": "probe_silent_hours", "et": "et_percent",
                               "depth": "timing_depth_cm", "deep": "root_depth_cm",
                               "tused": "timing_used_percent"},
               message_variants=(("anchored", "soilwater.weather_water_now_anchored"),
                                 (f"timing_depth_mm < root_depth_mm && depletion_mm < raw_mm && {timed}",
                                  "soilwater.weather_water_now_young"),
                                 ("corrected && !watering_recorded",
                                  "soilwater.weather_water_now_unrecorded_corrected"),
                                 ("!watering_recorded",
                                  "soilwater.weather_water_now_unrecorded"),
                                 ("corrected", "soilwater.weather_water_now_corrected"))),
        R.Rule("soil-weather-enough", "1", weather, p, alert_key="soilwater.weather_enough",
               message_params={"left": "left_percent", "hours": "probe_silent_hours",
                               "et": "et_percent"},
               message_variants=(("anchored", "soilwater.weather_enough_anchored"),
                                 ("corrected", "soilwater.weather_enough_corrected"))),
        R.Rule("soil-no-probe", "1", "!has_probe", p, alert_key="soilwater.no_probe",
               message_params={"depth": "root_depth_cm"}),
        R.Rule("soil-unseen", "1", "!has_reading || hours_since_reading > stale_after_h", p,
               alert_key="soilwater.unseen", message_params={"hours": "hours_since_reading"},
               message_variants=((f"hours_since_reading >= {NO_ESTIMATE!r}",
                                  "soilwater.never_seen"),)),
        R.Rule("soil-untrusted", "1", "!usable", p, alert_key="soilwater.untrusted",
               message_params={"flags": "flags", "depth": "out_of_soil_cm",
                               "reading": "out_of_soil_percent", "floor": "soil_floor_percent"},
               message_variants=(("out_of_soil", "soilwater.untrusted_out_of_soil"),)),
        R.Rule("soil-too-wet", "1", f"{usable} && wetter_than_capacity", p,
               alert_key="soilwater.too_wet", message_params={}),
        R.Rule("soil-rain-coming", "1",
               f"{usable} && {due} && rain_reaching_mm >= skip_rain_mm", p,
               alert_key="soilwater.rain_coming",
               message_params={"used": "used_percent", "rain": "rain_mm"}),
        R.Rule("soil-water-now", "1", f"{usable} && {due}", p,
               alert_key="soilwater.water_now",
               message_params={"used": "used_percent", "mm": "refill_mm",
                               "drying": "drying_mm_per_day", "depth": "timing_depth_cm",
                               "deep": "root_depth_cm", "tused": "timing_used_percent"},
               message_variants=((f"timing_depth_mm < root_depth_mm && depletion_mm < raw_mm && {timed}",
                                  "soilwater.water_now_young"),
                                 ("depletion_mm < raw_mm", "soilwater.water_now_ahead"))),
        R.Rule("soil-water-soon", "1", f"{usable} && days_to_water <= soon_days", p,
               alert_key="soilwater.water_soon", message_params={"days": "days_to_water"}),
        R.Rule("soil-enough", "1", usable, p, alert_key="soilwater.enough",
               message_params={"left": "left_percent"}),
    ]
    units = {"mm": "mm", "rain": "mm", "drying": "mm/d", "depth": "cm", "deep": "cm"}
    return [replace(r, subject_param="bed", unit_params=units) for r in rules]


# ----------------------------------------------------------------- context

def probes_of(state, bed: Bed, at: _dt.datetime) -> list:
    """`(datastream, depth_m)` for each calibrated soil-moisture series whose device is
    installed in the bed at `at` (§4.1), shallowest first."""
    found = []
    for ds in state.datastreams.values():
        if ds.kind is not DatastreamKind.DERIVED or ds.observed_property != V.SOIL_WATER:
            continue
        inst = state.installation_of(ds.sensor, at)
        if inst is None or inst.feature != bed.feature or inst.depth_m is None:
            continue
        found.append((ds, inst.depth_m))
    return sorted(found, key=lambda p: (p[1], p[0].id.int))


def weights(depths_m: list, root_depth_m: float) -> list:
    """The share of the root zone each probe stands for: from halfway to the probe above
    (or the surface) to halfway to the one below (or the root zone's bottom). A probe at the
    bottom itself counts for nothing: it reads the soil the roots are only reaching, half
    of it below them. With tomatoes' roots at their deepest, 60 cm in the 2025 revision,
    a probe at 60 cm counted as a quarter of the root zone left them short in 13 summers
    of 30 (README)."""
    out = []
    for i, d in enumerate(depths_m):
        if d >= root_depth_m - 1e-9:
            out.append(0.0)      # below the roots: it says what drains, not what they use
            continue
        top = 0.0 if i == 0 else (depths_m[i - 1] + d) / 2
        bottom = (d + depths_m[i + 1]) / 2 if i + 1 < len(depths_m) else root_depth_m
        out.append(max(0.0, min(bottom, root_depth_m) - min(top, root_depth_m)))
    return out


def _drying_mm_per_day(rows, at, root_depth_mm, capacity: float | None = None) -> float:
    """How fast the root zone is drying: its loss over the last whole day, each end the
    mean of the readings within two hours of it. A crop draws by day and hardly at night, so
    any part of a day misstates the rate: a fit over the night since the soil left field
    capacity read a heat wave's 8 mm a day as 1.3, and the advice did not look ahead to it.
    A day with a wetting in it (a three-hour mean 0.02 over the day's start) says nothing,
    and the day before is used. With `capacity`, a day that started above field capacity
    starts there, so drainage does not count as the crop's."""
    def near(t):
        values = [v for u, v in rows if abs((u - t) / HOUR) <= 2.0]
        return sum(values) / len(values) if len(values) >= 2 else None

    for back in (0, 1):
        end = at - back * 24 * HOUR
        begin = end - 24 * HOUR
        a, b = near(begin), near(end)
        if a is None or b is None:
            continue
        day = [v for u, v in rows if begin < u <= end]
        means = [sum(w) / 3.0 for w in zip(day, day[1:], day[2:])]
        if any(m > a + 0.02 for m in means):
            continue
        if capacity is not None:
            a = min(a, capacity)
        return max(0.0, (a - b) * root_depth_mm)
    return 0.0


# ------------------------------------------------------------ learned soil

#: How far back a probe's field capacity is learned from, and the fewest drain-downs it
#: is learned from: until then the bed's configured value stands.
LEARN_DAYS = 60.0
LEARN_MIN_DRAINS = 3
#: A wetting: the probe's reading, smoothed, rising by this much within four hours.
WETTING_RISE = 0.04
#: A drain-down is followed this long at most, and counts only if it runs this long
#: before the next wetting.
DRAIN_MAX_H = 72
DRAIN_MIN_H = 16
#: A drain-down says nothing about capacity unless the probe was this much wetter than
#: the level it drained back to: a watering that only refilled the soil part way does not
#: drain at all.
DRAIN_MIN_EXCESS = 0.02
#: A drain-down slower than a quarter of its span counts only with this much excess: the
#: crop's daily rhythm and a probe's noise of 0.01 faked slow drainage of up to 0.05
#: (`drain_fit`). Water perched on clay drains slowly and carries more: 0.12 and 0.13 in
#: the layered yard's subsoil.
SLOW_DRAIN_MIN_EXCESS = 0.06
#: The drainage time constants tried, hours: only those at least the readings' interval
#: (`drain_fit`).
DRAIN_TAUS_H = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 36.0)


def _smoothed(values: list) -> list:
    """A running median of three: one noisy reading is not a wetting."""
    out = []
    for i in range(len(values)):
        window = sorted(values[max(0, i - 1):i + 2])
        out.append(window[len(window) // 2])
    return out


def _solve3(m: list, v: list):
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for c in range(3):
        p = max(range(c, 3), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-12:
            return None
        a[c], a[p] = a[p], a[c]
        for r in range(3):
            if r != c:
                f = a[r][c] / a[c][c]
                for k in range(c, 4):
                    a[r][k] -= f * a[c][k]
    return [a[i][3] / a[i][i] for i in range(3)]


def drain_fit(points: list):
    """Fit one drain-down, `[(hours since its peak, reading)]`, as water above field
    capacity draining away while the crop dries the soil steadily:

        θ(t) = fc + a·exp(−t / τ) − r·t

    For each τ in `DRAIN_TAUS_H`, `fc`, `a` and `r` are a linear least-squares fit; a
    drain-down cannot gain water, so `a` and `r` are not negative; the τ that fits best
    wins. Returns `{"field_capacity", "excess", "drying_per_day", "tau_h"}` or None.

    **A drain-down counts only if its drainage can be told from the crop's drying.** The τ
    tried are at least the interval between readings, so two or more readings see the
    excess leave. When the best τ is more than a quarter of the drain-down's span, so the
    excess would not be gone (to under 2%) before it ends, the drain-down counts only with
    an excess of `SLOW_DRAIN_MIN_EXCESS`. A crop draws less as the soil dries, and by day
    only, so the soil dries along a gentle curve. Over a 72-hour drain-down a slow, small
    "drainage" of τ 24 or 36 hours is that curve. It put field capacity below the level the
    bed was watered to, the next watering stopped there, and the learned value sank with
    each round: from 0.248 to 0.206 over the 2012 drought, on a probe whose true level was
    0.25. A τ of half an hour, on hourly readings, was one noisy reading."""
    if len(points) < 4:
        return None
    gaps = sorted(b[0] - a[0] for a, b in zip(points, points[1:]))
    step, span = gaps[len(gaps) // 2], points[-1][0] - points[0][0]
    best = None
    for tau in (t for t in DRAIN_TAUS_H if t >= step):
        rows = [(1.0, math.exp(-t / tau), -t) for t, _ in points]
        m = [[sum(x[i] * x[j] for x in rows) for j in range(3)] for i in range(3)]
        b = [sum(x[i] * y for x, (_, y) in zip(rows, points)) for i in range(3)]
        solved = _solve3(m, b)
        if solved is None or solved[1] < 0 or solved[2] < 0:
            continue
        fc, a, r = solved
        sse = sum((y - fc - a * x[1] - r * x[2]) ** 2 for x, (_, y) in zip(rows, points))
        if best is None or sse < best[0]:
            best = (sse, fc, a, r, tau)
    if best is None or (best[4] > span / 4.0 and best[2] < SLOW_DRAIN_MIN_EXCESS):
        return None
    _, fc, a, r, tau = best
    return {"field_capacity": fc, "excess": a, "drying_per_day": r * 24.0, "tau_h": tau}


@functools.lru_cache(maxsize=4096)
def _drain_fit_of(points: tuple):
    """`drain_fit`, remembered: each morning's learning refits the same drain-downs of the
    last `LEARN_DAYS`, and a drain-down's fit is its readings' alone."""
    return drain_fit(list(points))


def drain_downs(readings: list) -> list:
    """Every drain-down in a probe's hourly readings, `[(time, θ)]` oldest first: from the
    peak of each wetting until the next wetting, or `DRAIN_MAX_H`, when that is at least
    `DRAIN_MIN_H` of readings with no gap over three hours. Each is `drain_fit`'s result
    with its `peak_at`, and `half_drain_h`, the hours the probe took to lose half of what
    the wetting added."""
    if len(readings) < DRAIN_MIN_H:
        return []
    times = [t for t, _ in readings]
    smooth = _smoothed([v for _, v in readings])

    def rise_at(i: int, floor: int) -> bool:
        lo = min(smooth[max(floor, i - 4):i], default=smooth[i])
        return smooth[i] - lo >= WETTING_RISE

    out, i = [], 1
    while i < len(readings):
        if not rise_at(i, 0):
            i += 1
            continue
        peak = i
        while peak + 1 < len(readings) and smooth[peak + 1] >= smooth[peak] - 0.005 \
                and times[peak + 1] - times[peak] <= 3 * HOUR:
            peak += 1
        end = peak + 1
        while end < len(readings) and (times[end] - times[peak]) / HOUR <= DRAIN_MAX_H \
                and times[end] - times[end - 1] <= 3 * HOUR and not rise_at(end, peak):
            end += 1
        span = times[end - 1] - times[peak]
        if span / HOUR >= DRAIN_MIN_H:
            points = [((times[k] - times[peak]) / HOUR, readings[k][1]) for k in range(peak, end)]
            fit = _drain_fit_of(tuple(points))
            if fit is not None:
                fit = dict(fit)
                before = min(smooth[max(0, i - 12):i + 1])
                half = before + (smooth[peak] - before) / 2.0
                fit["half_drain_h"] = next(((times[k] - times[peak]) / HOUR
                                            for k in range(peak, end) if smooth[k] <= half), None)
                fit["peak_at"] = times[peak]
                out.append(fit)
        i = max(end, i + 1)
    return out


def learned_capacity(readings: list):
    """A probe's field capacity, learned from its own drain-downs: the upper quartile of the
    levels it drained back to, from those where it had been clearly wetter
    (`DRAIN_MIN_EXCESS`), when there are `LEARN_MIN_DRAINS` of them; else None. On a soil
    that goes on moving water after it has drained, a light watering over drier soil, and
    the sun on the top, leave a probe lower than its soil's field capacity, and their median
    read it low. (Until 2026-10-17 the median, and the median of the soakings alone, were
    options; on the simulator a lawn watered back to either was short in nearly every
    summer of 30.)
    `{"field_capacity", "drains", "half_drain_h"}`, the last the median hours to lose half
    a wetting, or None when none did within its drain-down."""
    import statistics
    kept = [d for d in drain_downs(readings) if d["excess"] >= DRAIN_MIN_EXCESS]
    if len(kept) < LEARN_MIN_DRAINS:
        return None
    halves = [d["half_drain_h"] for d in kept if d["half_drain_h"] is not None]
    levels = sorted(d["field_capacity"] for d in kept)
    level = levels[(3 * len(levels)) // 4]
    return {"field_capacity": round(level, 3),
            "drains": len(kept),
            "half_drain_h": statistics.median(halves) if halves else None}


#: How far back the weather balance runs. It starts full there unless a soaking since
#: (rain and recorded watering at least the root zone's available water) refilled it.
BALANCE_DAYS = 60
#: How long a bed whose probes have gone silent or untrusted is carried on the weather
#: from their last good reading: as long as the balance runs. Anchored, it is never worse
#: than a bed that never had a probe, which is advised on the weather alone; and every
#: advice it gives says to check the probes.
FALLBACK_DAYS = BALANCE_DAYS


def weather_balance(state, bed: Bed, station, at: _dt.datetime, *,
                    days: int = BALANCE_DAYS, assumed: dict | None = None,
                    anchor: tuple | None = None) -> dict:
    """The root zone's depletion from the farm's station alone, FAO-56's daily balance
    (chapter 8): each local day up to yesterday, the depletion falls by the day's rain and
    recorded watering, never below full, and rises by the crop's ET, `Ks · Kc · ETo`,
    never past the available water. `Ks` (eq. 84) slows the crop once it has used its own
    share `p` of the available water (`crop_p`). For a bed whose crop is named, the ET is
    FAO-56's dual coefficient instead (chapter 7), `(Ks Kcb + Ke) ETo`: the crop's basal
    coefficient (`basal_day`) and its wet surface's evaporation, which runs well above a
    young crop's single coefficient when the soil is wetted every day or two.

    * **Rain is the station's gauge**, all of it taken as reaching the roots; on a
      mulched or sloping bed it is less.
    * **Watering is the valve's recorded minutes** times `Bed.application_mm_per_h`.
      Without both, the advisory's own advice to water is taken as followed (`assumed`,
      `{local day: mm}`), and the advice says so: a balance that never sees the watering
      it asked for asks again every morning, and on the backtest bed called for 1,027 mm
      in 2013 where 157 was enough.
    * **A day the station did not cover** takes the mean ET of the week before it, and
      is counted; two of the last three missing and the advisory says it cannot tell.

    With `anchor`, `(local day, depletion_mm)`, the balance starts from a measured depletion,
    the probes' last good reading, and steps the whole days after that reading's day: up to
    a day's ET is left out, the price of a daily balance.

    Today's watering so far, recorded or assumed, comes off too, so a second look the same
    day does not ask for the morning's watering again.

    Returns `depletion_mm`, `eto_mm` (yesterday's), `days_since_full`, `missing_recent`,
    `watering_recorded` and the FAO-56 stand-ins the station needed (`estimated`)."""
    import eto as E
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(station.timezone)
    today = at.astimezone(tz).date()
    first, last = today - _dt.timedelta(days=days), today - _dt.timedelta(days=1)
    if anchor is not None:
        first = max(first, anchor[0] + _dt.timedelta(days=1))
    if first > last:
        first = last + _dt.timedelta(days=1)
    summaries = E.summaries(state, station, first, last, at) if first <= last else {}
    recorded = bed.valve is not None and bed.application_mm_per_h is not None
    taw = grown(bed, first).taw_mm
    dr, since_full, known, estimated, missing, eto_mm = 0.0, days, [], set(), [], 0.0
    top_fc, top_wp = bed.limits_at(EVAPORATION_LAYER_M / 2.0)
    tew, de = (top_fc - 0.5 * top_wp) * EVAPORATION_LAYER_M * 1000.0, 0.0
    if anchor is not None:
        dr, since_full = min(taw, max(0.0, anchor[1])), (today - anchor[0]).days
    day = first
    while day <= last:
        # The crop as it was that day: deeper roots reach soil the balance takes as at field
        # capacity, as FAO-56's daily balance does; the coefficient is the day's.
        crop = grown(bed, day)
        taw = crop.taw_mm
        got = E.eto_of(station, day, summaries[day])
        if got is None:
            eto_mm, rain = (sum(known[-7:]) / len(known[-7:]) if known else 0.0), 0.0
            missing.append(day)
        else:
            eto_mm, rain, used = got
            rain = rain or 0.0
            known.append(eto_mm)
            estimated.update(used)
        water = rain * (bed.rain_share if bed.rain_share is not None else 1.0)
        if recorded:
            lo = _dt.datetime.combine(day, _dt.time(), tzinfo=tz).astimezone(_dt.timezone.utc)
            seen, minutes = valve_minutes(state, bed.valve, lo, lo + 24 * HOUR)
            water += minutes / 60.0 * bed.application_mm_per_h if seen else 0.0
        else:
            water += (assumed or {}).get(day, 0.0)
        dr = max(0.0, dr - water)
        since_full = 0 if dr == 0.0 and water > 0 else since_full + 1
        # The crop uses its water freely until its own `p`, not the advice's refill point.
        p = crop_p(bed, day)
        ks = 1.0 if dr <= p * taw else max(0.0, (taw - dr) / ((1.0 - p) * taw))
        kcb = basal_of(bed, day)
        if kcb is None:
            dr = min(taw, dr + ks * crop.crop_coefficient * bed.use_scale * bed.et_scale * eto_mm)
        else:
            # FAO-56's dual coefficient, as pyfao56 computes it (Eqs. 69 to 79): the crop's
            # transpiration, `Ks Kcb ETo`, and the wet surface's evaporation, `Ke ETo`, from a
            # top layer that rain and watering refill and the sun dries in two stages.
            de = max(0.0, de - water)
            kc_max = max(KC_MAX, kcb + 0.05)
            cover = (min(0.99, ((kcb - BASAL_AT_SOWING) / (kc_max - BASAL_AT_SOWING))
                         ** (1.0 + 0.5 * CROP_HEIGHT_M)) if kcb > BASAL_AT_SOWING else 0.0)
            few = max(0.01, 1.0 - cover)
            kr = max(0.0, min(1.0, (tew - de) / (tew - min(REW_MM, tew))))
            evaporation = min(kr * (kc_max - kcb), few * kc_max) * eto_mm
            de = min(tew, de + evaporation / few)
            dr = min(taw, dr + (ks * kcb * bed.use_scale * bed.et_scale) * eto_mm + evaporation)
        day += _dt.timedelta(days=1)
    # Today's watering so far, which a later look the same day must see: without it the
    # afternoon's check finds the morning's deficit and asks for it again. Today's ET is
    # not counted, so by the weather the afternoon only waters what the morning did not.
    if recorded:
        lo = _dt.datetime.combine(today, _dt.time(), tzinfo=tz).astimezone(_dt.timezone.utc)
        seen, minutes = valve_minutes(state, bed.valve, lo, at)
        dr = max(0.0, dr - (minutes / 60.0 * bed.application_mm_per_h if seen else 0.0))
    else:
        dr = max(0.0, dr - (assumed or {}).get(today, 0.0))
    return {"depletion_mm": dr, "eto_mm": eto_mm, "days_since_full": since_full,
            "missing_recent": sum(1 for d in missing if d > last - _dt.timedelta(days=3)),
            "watering_recorded": recorded, "estimated": estimated}


#: A bed's probes correct the weather balance (`reference_factor`) from the dry days of the
#: last REFERENCE_DAYS: at least REFERENCE_MIN_DAYS of them, and REFERENCE_MIN_MM of the
#: balance's ET over them, or there is no correction.
REFERENCE_DAYS = 30
REFERENCE_MIN_DAYS = 5
REFERENCE_MIN_MM = 10.0
#: A correction outside these is not made: a probe or the station is more likely wrong
#: than FAO-56's balance is that far off.
REFERENCE_LIMITS = (0.5, 1.5)
#: How far toward a probe's slower rate the balance moves: half. Faster, it moves all the
#: way, since more water is the safe error. Over thirty recorded summers, moving all the way
#: saved a tenth of the water and left the bed short in five summers, up to 33 hours: the
#: rate a probe saw over a month does not hold through a hot spell, and the balance's own
#: excess was the bed's margin. Half saved a twentieth, and the bed was never short; since
#: learning stopped counting slow, small drainages (`drain_fit`), a fiftieth.
REFERENCE_SHARE = 0.5
#: Rain on the gauge that makes a day wet, and a rise in the probes' three-hour mean over
#: the day's start that says it was watered.
DRY_DAY_RAIN_MM = 1.0
DRY_DAY_RISE = 0.02


def _root_zone_hours(state, bed: Bed, at: _dt.datetime, since: _dt.datetime):
    """A bed's root-zone water hour by hour from `since` to `at`, from its probes' readings
    the checks had passed by `at`, each probe weighted by its slice, on the hours every probe
    has one; with the zone's field capacity (learned where there is enough), its wilting
    point, and whether every probe has learned its own. `({hour: theta}, capacity, wilting,
    learned)`, or None with no probe in the root zone."""
    bed = grown(bed, at.date())
    probes = probes_of(state, bed, at)
    ws = weights([d for _, d in probes], bed.root_depth_mm / 1000.0)
    in_zone = [(ds, d, w) for (ds, d), w in zip(probes, ws) if w > 0]
    if not in_zone:
        return None
    by_hour, capacity, wilting, total, learned_all = {}, 0.0, 0.0, 0.0, True
    for ds, depth, w in in_zone:
        inst = state.installation_of(ds.sensor, at)
        rows = sorted((o for o in state.live_observations_of(ds.id)
                       if o.received_at <= at and o.measured_at <= at
                       and o.measured_at >= inst.installed_at
                       and isinstance(o.result, (int, float)) and not isinstance(o.result, bool)),
                      key=lambda o: o.measured_at)
        fc, wp = bed.limits_at(depth)
        learned = _capacity(state, bed, ds, depth, wp, rows, at)
        learned_all = learned_all and learned is not None
        capacity += w * (learned["field_capacity"] if learned else fc)
        wilting += w * wp
        total += w
        for o in rows:
            if o.measured_at >= since and state.quality_as_of(o.id, at)[0] is Usable.GOOD:
                hour = o.measured_at.replace(minute=0, second=0, microsecond=0)
                by_hour.setdefault(hour, {})[ds.id] = (w, float(o.result))
    hours = {t: sum(w * v for w, v in vals.values()) / sum(w for w, _ in vals.values())
             for t, vals in by_hour.items() if len(vals) == len(in_zone)}
    return hours, capacity / total, wilting / total, learned_all


def reference_factor(state, bed: Bed, station, at: _dt.datetime, *,
                     days: int = REFERENCE_DAYS) -> dict | None:
    """How fast a bed's depletion actually grows, as its probes see it, against the weather
    balance's `Kc · ETo` on the same days: the factor that corrects the balance of a bed
    nearby that has no probe (`Bed.reference`), or of this bed's own once its probes fall
    silent.

    **It reads the probes' rate, not their level.** A probe is a point: the water where it
    sits need not be the zone's. How fast the zone's store runs down after a wetting is the
    crop, the soil and the weather, which the beds around it share.

    **Depletion, not water lost.** After rain the soil holds more than field capacity for a
    day or two, and the crop draws on water that would have drained anyway. The balance
    counts that day's ET as depletion; the probes show the store still full. So a day's
    measured depletion is the growth, from one midnight to the next, of the water missing
    below field capacity, each midnight the mean of the readings within two hours of it,
    when the crop is barely drawing. A local day counts when:

    * no rain reached the gauge, its valve (when it has one) did not open, and the probes
      did not rise (a watering);
    * it started with less than the readily available water gone, so the crop was not yet
      slowing (FAO-56's `Ks` is 1).

    The factor is the sum of the measured depletion over the sum of the balance's ET. Outside
    `REFERENCE_LIMITS` there is no correction: on the drought, a probe reading low learned
    a field capacity that sank through the season until the bed read wetter than it on
    most dry days, which would have halved the balance of the bed it corrected.

    **Only a probe whose level has been checked corrects anything**: every probe in the
    root zone must have learned its own field capacity from its drain-downs
    (`learned_capacity`). A probe reading high sees the first of each spell's depletion as
    water above field capacity, so it would slow the balance of every bed it corrects: on
    the 2012 drought, one reading 0.05 high took a bed advised by the weather from no
    stressed hours to 397. Such a probe is never watered enough to learn, and so never
    corrects. Returns `factor`, `days`, `measured_mm` and `predicted_mm`, or None: no probe,
    a probe that has not learned, too few dry days to say, or a factor out of bounds."""
    import eto as E
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(station.timezone)
    today = at.astimezone(tz).date()
    first, last = today - _dt.timedelta(days=days), today - _dt.timedelta(days=1)
    start = lambda day: _dt.datetime.combine(day, _dt.time(), tzinfo=tz).astimezone(_dt.timezone.utc)
    zone = _root_zone_hours(state, bed, at, start(first - _dt.timedelta(days=1)) - 2 * HOUR)
    if zone is None or not zone[3]:
        return None
    hours, capacity, wilting, _ = zone
    summaries = E.summaries(state, station, first - _dt.timedelta(days=1), last, at)

    def midnight(day):
        t0 = start(day)
        values = [hours[t] for t in (t0 + k * HOUR for k in range(-2, 3)) if t in hours]
        return sum(values) / len(values) if len(values) >= 3 else None

    def wet(day) -> bool:
        got = E.eto_of(station, day, summaries[day]) if day in summaries else None
        if got is not None and (got[1] or 0.0) >= DRY_DAY_RAIN_MM:
            return True
        begin = midnight(day)
        t0 = start(day)
        if bed.valve is not None and valve_minutes(state, bed.valve, t0, t0 + 24 * HOUR)[1] > 0:
            return True
        values = [hours.get(t0 + k * HOUR) for k in range(24)]
        means = [sum(v) / 3.0 for v in zip(values, values[1:], values[2:]) if None not in v]
        return begin is None or any(m > begin + DRY_DAY_RISE for m in means)

    measured = predicted = 0.0
    counted, day, ratios = 0, first, []
    while day <= last:
        a, b = midnight(day), midnight(day + _dt.timedelta(days=1))
        got = E.eto_of(station, day, summaries[day]) if day in summaries else None
        # A day that began wetter than field capacity is left out: what it lost above it
        # was partly drainage, and below it the crop's alone, so counting only the part
        # below would read a bed watered often as drying slower than it does.
        if (a is not None and b is not None and got is not None and a <= capacity
                and (capacity - a) * grown(bed, day).root_depth_mm
                < bed.depletion_fraction * (capacity - wilting) * grown(bed, day).root_depth_mm
                and not wet(day)):
            gained = ((max(0.0, capacity - b) - max(0.0, capacity - a))
                      * grown(bed, day).root_depth_mm)
            measured += gained
            kc = grown(bed, day).crop_coefficient * bed.use_scale * bed.et_scale
            predicted += kc * got[0]
            counted += 1
            if got[0] > 0:
                ratios.append(gained / (kc * got[0]))
        day += _dt.timedelta(days=1)
    if counted < REFERENCE_MIN_DAYS or predicted < REFERENCE_MIN_MM:
        return None
    lo, hi = REFERENCE_LIMITS
    ratio = measured / predicted
    if not lo <= ratio <= hi:
        return None
    import statistics
    spread = statistics.stdev(ratios) / math.sqrt(len(ratios)) if len(ratios) >= 2 else 1.0
    return {"factor": ratio, "days": counted, "measured_mm": round(measured, 1),
            "predicted_mm": round(predicted, 1), "standard_error": round(spread, 3)}


def _corrected(state, bed: Bed, station, at, base: dict, inputs: dict, source: Bed | None) -> Bed:
    """`bed` with its crop coefficient corrected by `source`'s probes (`reference_factor`):
    all the way to a faster rate, `REFERENCE_SHARE` of the way to a slower one. The
    correction is written into the context and inputs; `bed` is unchanged without one."""
    found = reference_factor(state, source, station, at) if source is not None else None
    if found is None:
        return bed
    factor = found["factor"]
    applied = factor if factor >= 1.0 else 1.0 - REFERENCE_SHARE * (1.0 - factor)
    base.update({"corrected": True, "et_percent": round(100.0 * applied),
                 "reference_days": found["days"]})
    inputs["reference"] = {"bed": str(source.feature), **found, "factor": round(factor, 3),
                           "applied": round(applied, 3)}
    return replace(bed, et_scale=bed.et_scale * applied)


#: A tension sensor pairs with a moisture probe whose installation is this close in depth.
PAIR_DEPTH_M = 0.02
#: A tension series' units, to kPa.
TO_KPA = {"kPa": 1.0, "cbar": 1.0, "hPa": 0.1, "MPa": 1000.0}


def _measured_capacity(state, bed: Bed, ds, depth_m: float, rows: list, at: _dt.datetime):
    """A probe's field capacity read off its soil's retention curve (`retention.py`), when a
    tension sensor is installed in the bed at its depth: the last `LEARN_DAYS` of hours
    both read, each passed by the checks. None without one, or without enough of a curve."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import retention as RT
    since = at - _dt.timedelta(days=LEARN_DAYS)
    tension = None
    for other in state.datastreams.values():
        if other.kind is not DatastreamKind.DERIVED or other.observed_property != V.SOIL_WATER_POTENTIAL:
            continue
        inst = state.installation_of(other.sensor, at)
        if (inst is not None and inst.feature == bed.feature and inst.depth_m is not None
                and abs(inst.depth_m - depth_m) <= PAIR_DEPTH_M and other.unit in TO_KPA):
            tension = other
            break
    if tension is None:
        return None

    def hourly(series, unit_scale):
        out = {}
        for o in series:
            if (o.measured_at >= since and o.received_at <= at and o.measured_at <= at
                    and isinstance(o.result, (int, float)) and not isinstance(o.result, bool)
                    and state.quality_as_of(o.id, at)[0] is Usable.GOOD):
                out[o.measured_at.replace(minute=0, second=0, microsecond=0)] = float(o.result) * unit_scale
        return out
    water = hourly(rows, 1.0)
    pull = hourly(state.live_observations_of(tension.id), TO_KPA[tension.unit])
    pairs = [(-pull[t], water[t]) for t in water if t in pull]
    found = RT.capacity_from_tension(pairs, bed.capacity_kpa)
    if found is None:
        return None
    return {"field_capacity": round(found["field_capacity"], 3), "drains": 0, "half_drain_h": None,
            "measured": True, "pairs": found["pairs"], "tension": tension.id}


def _capacity(state, bed: Bed, ds, depth_m: float, wilting: float, rows: list,
              at: _dt.datetime):
    """A probe's field capacity at `at`: measured off its soil's retention curve when a
    tension sensor is installed beside it (`_measured_capacity`), else learned from its
    readings of the last `LEARN_DAYS` that the health checks had passed by then; or None:
    not learning, not enough drain-downs yet, or a value its soil's wilting point says
    cannot be right."""
    if not bed.learn:
        return None
    measured = _measured_capacity(state, bed, ds, depth_m, rows, at)
    if measured is not None and measured["field_capacity"] > wilting + 0.03:
        return {**measured, "datastream": ds.id, "depth_m": depth_m}
    since = at - _dt.timedelta(days=LEARN_DAYS)
    readings = []
    for o in rows:
        if o.measured_at >= since and state.quality_as_of(o.id, at)[0] is Usable.GOOD:
            readings.append((o.measured_at, float(o.result)))
    found = learned_capacity(readings)
    if found is None or found["field_capacity"] <= wilting + 0.03:
        return None
    return {**found, "datastream": ds.id, "depth_m": depth_m}


#: By the weather with nothing measured, the balance counts the crop's water this share
#: above FAO-56's estimate (`_margined`). The estimate is not the bed: the station's reference
#: ET and the crop's coefficient are each a tenth or more out, and a balance that counts low
#: waters late and short, and its shortfall adds up until rain, since each watering refills
#: only what it counted. Counted high, it waters a little early and a little over, and the
#: excess drains. A probe that corrects the balance (`_corrected`) can raise the rate above
#: this, but not lower it below: a rate read truly does not make a balance stepped once a
#: day safe on its own. Through the 2012 drought a reference read its bed at 0.70 to 1.11
#: of FAO-56's estimate, and taken half way to that, the margin dropped, it left the bed
#: short 33 hours. On the backtest bed, whose crop uses
#: about a fifth more than the balance counts, thirty summers with none were short in 21
#: (1,945 hours) on 249 mm; with 0.1, in 6 (101) on 287; with 0.2, in none on 329. Watering
#: a fifth more each time, the balance unchanged, left 8 (118 hours) on 298 mm: it still
#: watered late. Where the balance was not low, 0.2 cost a lawn 27% more water, tomatoes
#: 21%, lettuce 14%, none of them short either way.
WEATHER_MARGIN = 0.2


def _margined(bed: Bed, base: dict, inputs: dict) -> Bed:
    """`bed` with its balance's crop coefficient raised by `WEATHER_MARGIN`, unless a probe
    has corrected it higher still. A correction lower than that is recorded and not used."""
    floor = 1.0 + WEATHER_MARGIN
    if not WEATHER_MARGIN or bed.et_scale >= floor:
        return bed
    if base.get("corrected"):
        base.update({"corrected": False, "et_percent": 100.0})
        inputs["reference"]["margin_held"] = True
    base["margin_percent"] = round(100.0 * WEATHER_MARGIN)
    return replace(bed, et_scale=floor)


def _by_weather(state, bed: Bed, station, at, forecast, base: dict, inputs: dict,
                balance: dict) -> None:
    """Fill a bed's context from the weather balance."""
    taw = bed.taw_mm
    base.update({
        "by_weather": True, "weather_missing_days": balance["missing_recent"],
        "watering_recorded": balance["watering_recorded"],
        "depletion_mm": round(balance["depletion_mm"], 1),
        "refill_mm": round(balance["depletion_mm"], 1),
        "used_percent": round(100.0 * min(1.0, balance["depletion_mm"] / taw), 0),
        "left_percent": round(100.0 * max(0.0, 1.0 - balance["depletion_mm"] / taw), 0),
        "eto_mm": round(balance["eto_mm"], 2),
        "days_since_full": balance["days_since_full"]})
    if forecast is not None:
        ahead = state.forecast(forecast, at, at + 24 * HOUR)
        base["rain_mm"] = round(sum(o.result for o in ahead
                                    if isinstance(o.result, (int, float))), 1)
        inputs["forecast"] = str(forecast)
    inputs["station"] = {k: str(v) for k, v in (
        ("air_temperature", station.air_temperature),
        ("relative_humidity", station.relative_humidity),
        ("solar_radiation", station.solar_radiation),
        ("wind_speed", station.wind_speed),
        ("precipitation", station.precipitation)) if v is not None}
    inputs["estimated"] = sorted(balance["estimated"])


#: A silent bed is carried from the mean of its probes' good readings over this many hours
#: up to the newest (`_last_good`), not from one: on the 2012 drought the last reading before
#: an outage read 0.027 over the soil, a third of the bed's water to spare, and the bed went
#: short 15 hours in the outage's first two days.
ANCHOR_HOURS = 3


def _last_good(state, rows: list, at: _dt.datetime, floor: float | None = None):
    """A probe's newest reading the checks had passed by `at`, within `FALLBACK_DAYS`, and
    not below `floor` (`soil_floor`): `(measured_at, value)`, the value the mean of its good
    readings over the `ANCHOR_HOURS` up to it; or None."""
    since = at - _dt.timedelta(days=FALLBACK_DAYS)
    newest, values = None, []
    for o in reversed(rows):
        if o.measured_at < since or (newest is not None
                                     and o.measured_at <= newest - ANCHOR_HOURS * HOUR):
            break
        if floor is not None and o.result < floor:
            continue
        if state.quality_as_of(o.id, at)[0] is Usable.GOOD:
            newest = newest or o.measured_at
            values.append(float(o.result))
    return (newest, sum(values) / len(values)) if values else None


def _anchored(state, bed: Bed, station, at, forecast, base: dict, inputs: dict,
              probes: list, assumed: dict | None, reference: Bed | None = None) -> None:
    """A bed whose probes have gone silent or untrusted, carried on the farm's weather from
    their last good readings: the root zone's depletion then, at each probe's soil's limits
    and learned field capacity, stepped forward by the weather balance."""
    from zoneinfo import ZoneInfo
    total = sum(w for w, *_ in probes)
    limits = [bed.limits_at(depth) for _, depth, *_ in probes]
    caps = [_capacity(state, bed, ds, depth, wp, rows, at)
            for (_, depth, ds, rows, _), (_, wp) in zip(probes, limits)]
    theta = sum(w * good[1] for (w, _, _, _, good) in probes) / total
    capacity = sum(w * (c["field_capacity"] if c else fc)
                   for (w, *_), c, (fc, _) in zip(probes, caps, limits)) / total
    wilting = sum(w * wp for (w, *_), (_, wp) in zip(probes, limits)) / total
    eff = replace(bed, field_capacity=capacity, wilting_point=wilting)
    # The bed's own probes, before they fell silent, say how fast it dries; failing that, its
    # reference's.
    corrected = _corrected(state, eff, station, at, base, inputs, bed)
    if corrected is eff and reference is not None:
        corrected = _corrected(state, eff, station, at, base, inputs, reference)
    eff = _margined(corrected, base, inputs)
    when = min(good[0] for *_, good in probes)
    dr0 = (capacity - theta) * bed.root_depth_mm
    balance = weather_balance(state, eff, station, at, assumed=assumed,
                              anchor=(when.astimezone(ZoneInfo(station.timezone)).date(), dr0))
    _by_weather(state, eff, station, at, forecast, base, inputs, balance)
    base.update({"anchored": True, "probe_silent_hours": round((at - when) / HOUR, 1),
                 "field_capacity": round(capacity, 3), "wilting_point": round(wilting, 3)})
    inputs["anchored_at"] = when.isoformat()


def _to_curve(base: dict, timing_mm: float) -> None:
    """Advice from the weather: its balance follows the crop's curve day by day (`grown`),
    so the depth the watering is timed by is the youngest planting's, and the probes' signs
    change nothing."""
    base.update({"timing_depth_mm": round(timing_mm, 1), "timing_depth_cm": round(timing_mm / 10.0),
                 "roots_blocked": False, "roots_blocked_cm": 0})


def _timed_by_balance(base: dict) -> None:
    """The weather's balance is one bucket: the zone the watering is timed by has lost the
    same millimetres, and holds fewer."""
    timing_mm = base["timing_depth_mm"]
    taw = max(1e-9, (base["field_capacity"] - base["wilting_point"]) * timing_mm)
    used = 100.0 * min(1.0, base["depletion_mm"] / taw)
    base.update({"timing_depletion_mm": base["depletion_mm"],
                 "timing_used_percent": round(used, 0),
                 "used_percent": max(base["used_percent"], round(used, 0)),
                 "left_percent": min(base["left_percent"], round(100.0 - used, 0))})


def bed_context(state, bed: Bed, at: _dt.datetime, *, forecast: UUID | None = None,
                station=None, assumed: dict | None = None, reference: Bed | None = None,
                held: tuple | None = None, rain_gauge: UUID | None = None):
    """What the advisory knew about a bed at `at`: `(context, inputs)` (`_bed_context`),
    with the forecast rain that would reach it (`Bed.rain_share`, or none where its probes
    show it covered: `covered_by_its_probes`, from `rain_gauge` or the station's)."""
    context, inputs = _bed_context(state, bed, at, forecast=forecast, station=station,
                                   assumed=assumed, reference=reference, held=held)
    share = bed.rain_share
    gauge = rain_gauge or (station.precipitation if station is not None else None)
    if share is None and gauge is not None and bed.valve is not None and context["has_reading"]:
        since = at - _dt.timedelta(days=COVER_DAYS)
        rain_rows = [(o.measured_at, float(o.result)) for o in state.live_observations_of(gauge)
                     if since <= o.measured_at <= at and o.received_at <= at
                     and isinstance(o.result, (int, float)) and not isinstance(o.result, bool)]
        probe_rows = []
        for ds, depth in probes_of(state, grown(bed, at.date()), at):
            if depth * 1000.0 > context["root_depth_mm"]:
                continue
            probe_rows.append([(o.measured_at, float(o.result))
                               for o in state.live_observations_of(ds.id)
                               if since <= o.measured_at <= at and o.received_at <= at
                               and isinstance(o.result, (int, float))
                               and not isinstance(o.result, bool)])
        covered, storms = covered_by_its_probes(rain_rows, probe_rows,
                                                _valve_windows(state, bed.valve, since, at))
        context["rain_share_spells"] = storms
        if covered:
            share = 0.0
            context["rain_share_learned"] = True
    share = 1.0 if share is None else share
    context["rain_share"] = share
    context["rain_reaching_mm"] = round(context["rain_mm"] * share, 1)
    return context, inputs


def _bed_context(state, bed: Bed, at: _dt.datetime, *, forecast: UUID | None = None,
                 station=None, assumed: dict | None = None, reference: Bed | None = None,
                 held: tuple | None = None):
    """What the advisory knew about a bed at `at`: `(context, inputs)`. A bed with no
    probe in its root zone is advised from the farm's `station` (`eto.Station`) when
    there is one (`weather_balance`), corrected by its `reference` bed's probes when they
    have seen enough dry days (`reference_factor`)."""
    known: dict = {}
    bed, base, inputs, found, in_zone, young_mm, timing_mm = _context_base(
        state, bed, at, held=held, capacities=known)
    if not in_zone:
        _to_curve(base, young_mm)
        if station is not None:
            bed = _margined(_corrected(state, bed, station, at, base, inputs, reference), base,
                            inputs)
            _by_weather(state, bed, station, at, forecast, base, inputs,
                        weather_balance(state, bed, station, at, assumed=assumed))
            _timed_by_balance(base)
        return base, inputs
    (latest, flagged, series, capacities, limits, fallback, out_of_soil, series_depths,
     series_sensors) = _probe_readings(state, bed, at, in_zone, known)
    if not latest:
        return base, inputs
    base["has_reading"] = True
    base["hours_since_reading"] = round((at - max(latest)) / HOUR, 2)
    base["flags"] = ",".join(sorted(flagged))
    if out_of_soil:
        depth, reading, floor = out_of_soil[0]
        base.update({"out_of_soil": True, "out_of_soil_cm": round(depth * 100.0),
                     "out_of_soil_percent": round(reading * 100.0, 1),
                     "soil_floor_percent": round(floor * 100.0, 1)})
    if not series:
        # The probes are silent or untrusted. With the farm's station, carry the bed on the
        # weather from their last good readings, for up to FALLBACK_DAYS.
        if (station is not None and len(fallback) == len(in_zone)
                and all(fb[4] is not None for fb in fallback)):
            _to_curve(base, young_mm)
            _anchored(state, bed, station, at, forecast, base, inputs, fallback, assumed,
                      reference)
            _timed_by_balance(base)
        return base, inputs

    _from_probes(state, bed, at, base, inputs, found, timing_mm, forecast, series, capacities,
                 limits, series_depths, series_sensors)
    return base, inputs


def _context_base(state, bed: Bed, at: _dt.datetime, *, held, capacities: dict):
    """The bed as its crop is on `at`, the depth its watering is timed by, its probes in the
    root zone, and the context and inputs every decision starts from: `(bed, context,
    inputs, plantings, probes in the zone, the youngest roots' depth, the timing depth)`."""
    bed = grown(bed, at.date())
    curve_mm, seen_m, blocked_m = bed.root_depth_mm, 0.0, None
    young_mm = bed.timing_depth_mm if bed.timing_depth_mm is not None else curve_mm
    timing_mm = young_mm
    found = plantings_of(bed)
    if found:
        signs = root_signs(state, bed, at, capacities)
        stop_mm, seen_m, blocked_m = rooted(curve_mm, signs, held)
        timing_mm = min(young_mm, stop_mm)
        bed = replace(bed, timing_depth_mm=timing_mm if timing_mm < curve_mm else None)
    root_m = bed.root_depth_mm / 1000.0
    probes = probes_of(state, bed, at)
    ws = weights([d for _, d in probes], root_m)
    if bed.rooting_limit_mm is not None:
        # A probe at the rooting limit, set into the hardpan, reads soil the roots do not enter.
        ws = [0.0 if d * 1000.0 >= bed.rooting_limit_mm else w for (_, d), w in zip(probes, ws)]
    in_zone = [(ds, d, w) for (ds, d), w in zip(probes, ws) if w > 0]
    first = found[0] if found else (None, None)
    base = {"root_depth_mm": round(bed.root_depth_mm, 1),
            "timing_depth_mm": round(timing_mm, 1), "timing_depth_cm": round(timing_mm / 10.0),
            "timing_depletion_mm": 0.0, "timing_drying_mm_per_day": 0.0,
            "timing_used_percent": 0.0,
            "plantings": len(found),
            "crop_days": round(crop_days(bed, at.date(), first), 1) if first[1] else 0.0,
            "crop_gdd": round(crop_gdd(bed, at.date(), first) or 0.0, 0) if first[1] else 0.0,
            "calendar_days": (at.date() - first[1]).days if first[1] else 0,
            "by_warmth": bed.clock is not None,
            "roots_expected_cm": round(curve_mm / 10.0), "roots_seen_cm": round(seen_m * 100.0),
            "roots_blocked": blocked_m is not None,
            "roots_blocked_cm": round((blocked_m or 0.0) * 100.0),
            "rooting_limit_set": bed.rooting_limit_mm is not None,
            "has_probe": bool(in_zone), "root_depth_cm": round(bed.root_depth_mm / 10.0),
            "has_reading": False, "usable": False, "flags": "",
            "out_of_soil": False, "out_of_soil_cm": 0, "out_of_soil_percent": 0.0,
            "soil_floor_percent": 0.0,
            "hours_since_reading": NO_ESTIMATE, "theta": 0.0,
            "wetter_than_capacity": False, "depletion_mm": 0.0, "refill_mm": 0.0,
            "used_percent": 0.0, "left_percent": 0.0, "rain_mm": 0.0,
            "rain_reaching_mm": 0.0,
            "rain_share": bed.rain_share if bed.rain_share is not None else 1.0,
            "rain_share_spells": 0, "rain_share_learned": False,
            "days_to_water": NO_ESTIMATE, "probes": len(in_zone),
            "field_capacity": bed.field_capacity, "wilting_point": bed.wilting_point,
            "learned_probes": 0, "measured_probes": 0, "layered": False, "layers_configured": bool(bed.layers),
            "by_weather": False, "weather_missing_days": 0, "watering_recorded": False,
            "anchored": False, "probe_silent_hours": 0.0, "drying_mm_per_day": 0.0,
            "corrected": False, "et_percent": 100.0, "reference_days": 0}
    inputs = {"bed": str(bed.feature), "observations": [], "forecast": None}
    inputs.update({k: getattr(bed, k) for k in ("surface", "planting") if getattr(bed, k)})
    if len(found) > 1:
        inputs["plantings"] = [
            {"crop": crop, "planted": planted.isoformat() if planted else None,
             "days": round(crop_days(bed, at.date(), (crop, planted)), 1),
             "gdd": crop_gdd(bed, at.date(), (crop, planted)),
             "root_cm": round(crop_stage(bed, at.date(), (crop, planted))[1] / 10.0)}
            for crop, planted in found]
    return bed, base, inputs, found, in_zone, young_mm, timing_mm


def _probe_readings(state, bed: Bed, at: _dt.datetime, in_zone: list, known: dict):
    """Each probe in the root zone's readings by `at`: the newest's time, the flags on the
    newest that failed, readings out of the soil, the last good reading to carry the bed
    from, and for each probe fresh enough to use, its good readings, depth, sensor, soil
    limits and learned field capacity, `known`'s where the root signs learned it already."""
    latest, flagged, series, capacities, limits, fallback = [], set(), [], [], [], []
    out_of_soil = []
    series_depths, series_sensors = [], []
    for ds, depth, w in in_zone:
        inst = state.installation_of(ds.sensor, at)
        rows = sorted((o for o in state.live_observations_of(ds.id)
                       if o.received_at <= at and o.measured_at <= at
                       and o.measured_at >= inst.installed_at
                       and isinstance(o.result, (int, float)) and not isinstance(o.result, bool)),
                      key=lambda o: o.measured_at)
        if not rows:
            continue
        floor = soil_floor(depth, bed.limits_at(depth)[1])
        good = []
        for o in rows[-int(DRYING_WINDOW_H * 4) - 8:]:
            usable, flags = state.quality_as_of(o.id, at)
            if usable is Usable.GOOD and o.result >= floor:
                good.append(o)
            elif o is rows[-1] and usable is Usable.GOOD:
                flagged.add("out_of_soil")
                out_of_soil.append((depth, o.result, floor))
            elif o is rows[-1]:
                flagged |= {f.value for f in flags} or {"questionable"}
        newest = rows[-1]
        latest.append(newest.measured_at)
        fallback.append((w, depth, ds, rows, _last_good(state, rows, at, floor)))
        fresh = (at - newest.measured_at) / HOUR <= bed.stale_after_h
        if fresh and good and good[-1] is newest:
            series.append((w, good))
            series_depths.append(depth)
            series_sensors.append(ds.sensor)
            limits.append(bed.limits_at(depth))
            capacities.append(known[ds.id] if ds.id in known
                              else _capacity(state, bed, ds, depth, limits[-1][1], rows, at))
    return (latest, flagged, series, capacities, limits, fallback, out_of_soil, series_depths,
            series_sensors)


def _from_probes(state, bed: Bed, at: _dt.datetime, base: dict, inputs: dict, found: tuple,
                 timing_mm: float, forecast, series: list, capacities: list, limits: list,
                 series_depths: list, series_sensors: list) -> None:
    """Fill a bed's context from its probes: the root zone's water and field capacity, the
    zone the watering is timed by, how fast each dries, and the forecast's rain."""
    root_m = bed.root_depth_mm / 1000.0
    # Probes named for plantings: the youngest's time the watering; the oldest's, and any
    # no planting names, measure the refill.
    timing_lists = None
    tied = planting_probes(bed)
    sown = [p for p in found if p[1] is None or p[1] <= at.date()]
    if tied and sown:
        reach = {p: crop_stage(bed, at.date(), p)[1] for p in sown}
        young, deep = min(reach, key=reach.get), max(reach, key=reach.get)
        named = frozenset().union(*tied.values())
        mine = [i for i, sensor in enumerate(series_sensors) if sensor in tied.get(young, ())]
        if mine:
            timing_lists = ([series[i] for i in mine], [capacities[i] for i in mine],
                            [limits[i] for i in mine], [series_depths[i] for i in mine])
        keep = [i for i, sensor in enumerate(series_sensors)
                if sensor in tied.get(deep, ()) or sensor not in named]
        if keep and len(keep) < len(series):
            kw = weights([series_depths[i] for i in keep], root_m)
            kept = [(i, w) for i, w in zip(keep, kw) if w > 0]
            if kept:
                series = [(w, series[i][1]) for i, w in kept]
                capacities = [capacities[i] for i, _ in kept]
                limits = [limits[i] for i, _ in kept]
                series_depths = [series_depths[i] for i, _ in kept]
                inputs["planting_probes"] = {"young": f"{young[0]} {young[1]}",
                                             "deep": f"{deep[0]} {deep[1]}"}
    total = sum(w for w, _ in series)
    theta = sum(w * good[-1].result for w, good in series) / total
    # Each probe's slice of the root zone at its own soil's limits, the field capacity
    # learned where there is enough to learn from.
    capacity = sum(w * (c["field_capacity"] if c else fc)
                   for (w, _), c, (fc, _) in zip(series, capacities, limits)) / total
    wilting = sum(w * wp for (w, _), (_, wp) in zip(series, limits)) / total
    learned = [{"datastream": str(c["datastream"]),
                "how": "measured" if c.get("measured") else "learned",
                **{k: c[k] for k in ("depth_m", "field_capacity", "drains", "half_drain_h")}}
               for c in capacities if c]
    bed = replace(bed, field_capacity=capacity, wilting_point=wilting)
    if len(learned) >= 2:
        top, bottom = learned[0], learned[-1]
        base.update({"layered": abs(bottom["field_capacity"] - top["field_capacity"]) >= LAYER_GAP,
                     "shallow_cm": round(top["depth_m"] * 100.0),
                     "deep_cm": round(bottom["depth_m"] * 100.0),
                     "shallow_fc_percent": round(top["field_capacity"] * 100.0),
                     "deep_fc_percent": round(bottom["field_capacity"] * 100.0)})
    # The root zone's water over time, on the hours every counted probe has a reading.
    by_time = {}
    for w, good in series:
        for o in good:
            key = o.measured_at.replace(minute=0, second=0, microsecond=0)
            by_time.setdefault(key, {})[id(good)] = (w, o.result)
    history = sorted((t, sum(w * v for w, v in vals.values()) / sum(w for w, _ in vals.values()))
                     for t, vals in by_time.items() if len(vals) == len(series))
    depletion = max(0.0, (bed.field_capacity - theta) * bed.root_depth_mm)
    drying = _drying_mm_per_day(history, at, bed.root_depth_mm, bed.field_capacity)
    # The zone the watering is timed by: the probes in it, or, where it is shallower than any,
    # the shallowest, the nearest there is to it; the youngest planting's own, where it names
    # them.
    t_series, t_caps, t_limits, t_depths = timing_lists or (series, capacities, limits,
                                                            series_depths)
    tw = weights(t_depths, timing_mm / 1000.0)
    if sum(tw) <= 0:
        top = t_depths.index(min(t_depths))
        tw = [1.0 if i == top else 0.0 for i in range(len(t_depths))]
    t_total = sum(tw)
    t_theta = sum(w * good[-1].result for w, (_, good) in zip(tw, t_series)) / t_total
    t_cap = sum(w * (c["field_capacity"] if c else fc)
                for w, c, (fc, _) in zip(tw, t_caps, t_limits)) / t_total
    t_wp = sum(w * wp for w, (_, wp) in zip(tw, t_limits)) / t_total
    timing_depletion = max(0.0, (t_cap - t_theta) * timing_mm)
    timing_taw = max(1e-9, (t_cap - t_wp) * timing_mm)
    # And how fast it dries, for the look-ahead: its own probes' water over time.
    counted = [(w, good) for w, (_, good) in zip(tw, t_series) if w > 0]
    t_by_time = {}
    for w, good in counted:
        for o in good:
            key = o.measured_at.replace(minute=0, second=0, microsecond=0)
            t_by_time.setdefault(key, {})[id(good)] = (w, o.result)
    t_history = sorted((t, sum(w * v for w, v in vals.values()) / sum(w for w, _ in vals.values()))
                       for t, vals in t_by_time.items() if len(vals) == len(counted))
    timing_drying = (_drying_mm_per_day(t_history, at, timing_mm, t_cap)
                     if timing_mm < bed.root_depth_mm else drying)
    timing_raw = bed.depletion_fraction * (bed.field_capacity - bed.wilting_point) * timing_mm
    ranged = timing_mm < bed.root_depth_mm
    if ranged:
        # Across a range of roots, each probe's own deficit: soil past field capacity under a
        # stop or below young roots is draining, and cannot fill the dry soil above it.
        depletion = sum(w * max(0.0, (c["field_capacity"] if c else fc) - good[-1].result)
                        for (w, good), c, (fc, _) in zip(series, capacities, limits)) \
            / total * bed.root_depth_mm
    to_go = min(bed.raw_mm - depletion, timing_raw - timing_depletion)
    days = to_go / drying if drying > 0.1 and to_go > 0 else (0.0 if to_go <= 0 else NO_ESTIMATE)
    rain = 0.0
    if forecast is not None:
        ahead = state.forecast(forecast, at, at + 24 * HOUR)
        rain = sum(o.result for o in ahead if isinstance(o.result, (int, float)))
        inputs["forecast"] = str(forecast)
    inputs["observations"] = [str(good[-1].id) for _, good in series]
    if learned:
        inputs["learned"] = learned
    base.update({
        "usable": True, "theta": round(theta, 3), "field_capacity": round(capacity, 3),
        "wilting_point": round(wilting, 3),
        "learned_probes": len(learned),
        "measured_probes": sum(1 for x in learned if x["how"] == "measured"),
        "wetter_than_capacity": (theta > bed.field_capacity + bed.wet_margin
                                 and (not ranged or t_theta > t_cap + bed.wet_margin)),
        "depletion_mm": round(depletion, 1),
        # With the young planting's own probes, its soil may have lost more than the old
        # planting's patch: the one valve gives the more.
        "refill_mm": round(max(depletion, timing_depletion) if timing_lists else depletion, 1),
        "timing_depletion_mm": round(timing_depletion, 1),
        "timing_drying_mm_per_day": round(timing_drying, 2),
        "timing_used_percent": round(100.0 * min(1.0, timing_depletion / timing_taw), 0),
        "used_percent": round(100.0 * min(1.0, max(depletion / bed.taw_mm,
                                                   timing_depletion / timing_taw)), 0),
        "left_percent": round(100.0 * max(0.0, 1.0 - max(depletion / bed.taw_mm,
                                                         timing_depletion / timing_taw)), 0),
        "rain_mm": round(rain, 1), "days_to_water": round(days, 1),
        "drying_mm_per_day": round(drying, 2)})


# ----------------------------------------------------------------- advisor

#: Without the farm's normal year to stand in for the days its station missed, a crop is
#: clocked by its station only when the station read this share of its days since sowing.
CLOCK_COVERAGE = 0.9


class Advisor:
    """Writes one decision per bed per call: the morning's advice, or why there is none."""

    def __init__(self, log, *, normal=None, rain_gauge: UUID | None = None,
                 clocks: bool = True) -> None:
        """`normal` is the farm's normal year (`thermal.Normal`): with it and a station, a
        sown crop's curve runs by the season's warmth (`clocked`). `rain_gauge` is the farm's
        rain gauge where it has no station's, for seeing a bed under cover
        (`covered_by_its_probes`). Without `clocks`, every crop keeps the calendar
        (`clocked`)."""
        self.log = log
        self.normal = normal
        self.rain_gauge = rain_gauge
        self.clocks = clocks
        self._temperatures: dict = {}

    def clocked(self, state, bed: Bed, station, at: _dt.datetime) -> Bed:
        """The bed with a clock for each of its sown plantings, from the station's daily
        temperatures since sowing: the degree-days gathered, for a crop the 2025 revision
        stages in degree-days (`thermal.cumulative_gdd`), else days by the farm's normal year
        (`thermal.growing_days`). The bed as it was without a station, or without the
        normal year for a crop staged in days."""
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import eto as E
        import thermal as T
        today = at.date()
        sown = [(crop, planted) for crop, planted in plantings_of(bed)
                if planted is not None and planted < today and crop in T.THRESHOLDS
                and (CROPS[crop]["gdd_stages"] is not None or self.normal is not None)]
        if not self.clocks or station is None or bed.clock is not None or not sown:
            return bed
        # Days two or more back are settled, and kept; the last is read again each morning.
        settled = today - _dt.timedelta(days=2)
        key = station.air_temperature
        known = self._temperatures.setdefault(key, {})
        first = min(planted for _, planted in sown)
        while first < today and first in known:
            first += _dt.timedelta(days=1)
        actual = dict(known)
        if first < today:
            read = E.daily_temperatures(state, station, first, today - _dt.timedelta(days=1), at)
            actual.update(read)
            known.update({d: t for d, t in read.items() if d <= settled})
        clock = {}
        for crop, planted in sown:
            span = (today - planted).days
            seen = sum(1 for n in range(span)
                       if actual.get(planted + _dt.timedelta(days=n)) is not None)
            if self.normal is None and seen < CLOCK_COVERAGE * span:
                continue            # too many days with nothing to stand in for them
            if CROPS[crop]["gdd_stages"] is not None:
                clock[(crop, planted)] = {"gdd": T.cumulative_gdd(crop, planted, today, actual,
                                                                  self.normal)}
            else:
                clock[(crop, planted)] = {"days": T.growing_days(crop, planted, today, actual,
                                                                 self.normal)}
        return replace(bed, clock=clock) if clock else bed

    def judge(self, state, bed: Bed, at: _dt.datetime, *, forecast: UUID | None = None,
              station=None, reference: Bed | None = None) -> dict:
        """The decision for one bed, without writing it; `reference` is the bed its
        `Bed.reference` names."""
        bed = grown(self.clocked(state, bed, station, at), at.date())
        if reference is not None:
            reference = self.clocked(state, reference, station, at)
        assumed = self._assumed(bed, station) if station is not None else None
        context, inputs = bed_context(state, bed, at, forecast=forecast, station=station,
                                      assumed=assumed, reference=reference,
                                      held=self._held(bed, at), rain_gauge=self.rain_gauge)
        timing = context["timing_depth_mm"]
        timing_p = None
        if bed.young_fraction is not None and young(bed, at.date()):
            p = min(bed.depletion_fraction, bed.young_fraction)
            if timing < context["root_depth_mm"]:
                # Among older plantings: the young roots' own zone; the older keep theirs.
                timing_p = context["timing_fraction"] = round(p, 3)
            else:
                bed = replace(bed, depletion_fraction=p, short_fraction=max(bed.short_fraction, p))
                context["depletion_fraction"] = round(p, 3)
        for rule in rules_for(replace(bed, root_depth_mm=context["root_depth_mm"],
                                      timing_depth_mm=(timing if timing < context["root_depth_mm"]
                                                       else None),
                                      field_capacity=context["field_capacity"],
                                      wilting_point=context["wilting_point"]),
                              timing_p):
            d = R.judge(rule, context, inputs, at)
            if d["alert"]:
                # One answer per bed per morning, whichever rule gave it (§7.7): the
                # morning's advice replaces yesterday's, and stands for a day.
                d["subject"] = str(bed.feature)
                d["topic"] = f"advice/{bed.feature}"
                d["valid_until"] = (at + _dt.timedelta(days=1)).isoformat()
                return d
        raise AssertionError("the last rule holds whenever none before it does")

    def _held(self, bed: Bed, at: _dt.datetime) -> tuple | None:
        """`(seen, blocked)`, metres: the shallowest stop this advisory found for the bed
        (`rooted`) on `ROOT_HOLD_MORNINGS` or more of its last `ROOT_HOLD_DAYS` mornings,
        or None. One morning's stop may be the probes' noise; three in a week is not."""
        since = at - _dt.timedelta(days=ROOT_HOLD_DAYS)
        counts: dict = {}
        for event in reversed(getattr(self.log, "events", ())):
            p = event.payload
            if (event.kind != R.DECISION or p.get("subject") != str(bed.feature)
                    or not str(p.get("topic", "")).startswith("advice/")):
                continue
            if _dt.datetime.fromisoformat(p["evaluated_at"]) < since:
                break
            c = p.get("context", {})
            if c.get("roots_blocked"):
                pair = (c["roots_seen_cm"] / 100.0, c["roots_blocked_cm"] / 100.0)
                day = _dt.datetime.fromisoformat(p["evaluated_at"]).date()
                counts.setdefault(pair, set()).add(day)          # days, not checks
        standing = [pair for pair, days in counts.items() if len(days) >= ROOT_HOLD_MORNINGS]
        return min(standing, key=sum) if standing else None

    def _assumed(self, bed: Bed, station) -> dict:
        """`{local day: mm}`: this advisory's own advice to water the bed by the weather,
        as it wrote it, taken as followed where no valve records the watering."""
        from zoneinfo import ZoneInfo
        tz, out = ZoneInfo(station.timezone), {}
        for event in getattr(self.log, "events", ()):
            p = event.payload
            if (event.kind == R.DECISION and p.get("rule") == "soil-weather-water-now"
                    and p.get("subject") == str(bed.feature)):
                day = _dt.datetime.fromisoformat(p["evaluated_at"]).astimezone(tz).date()
                out[day] = out.get(day, 0.0) + p["context"]["refill_mm"]   # a second check's too
        return out

    def advise(self, state, beds, at: _dt.datetime, *, forecast: UUID | None = None,
               station=None) -> list:
        """The morning's decision for each bed, and for a bed its probes show is
        layered, a note saying so (`layering`); for one whose roots seem stopped short of
        its crop's curve, another (`roots_note`); for one advised without a probe that reads
        drier than its soil can be, a third (`out_of_soil_note`). A bed's reference is found
        among `beds`."""
        out, by_land = [], {b.feature: b for b in beds}
        for bed in beds:
            decision = self.judge(state, bed, at, forecast=forecast, station=station,
                                  reference=by_land.get(bed.reference))
            out.append(self.log.append(R.DECISION, decision))
            for note in (self.layering(decision, bed, at), self.roots_note(decision, bed, at),
                         self.out_of_soil_note(decision, bed, at)):
                if note is not None:
                    out.append(self.log.append(R.DECISION, note))
        return out

    @staticmethod
    def roots_note(decision: dict, bed: Bed, at: _dt.datetime) -> dict | None:
        """When the crop's roots should have passed a probe that stays level, under a
        shallower one that has roots (`rooted`), and no rooting limit is set: a note that
        something may be stopping them. None otherwise."""
        context = decision["context"]
        if not context.get("roots_blocked") or context.get("rooting_limit_set"):
            return None
        names = ("roots_blocked", "rooting_limit_set", "roots_expected_cm", "roots_blocked_cm",
                 "roots_seen_cm", "timing_depth_cm")
        d = R.judge(roots_rule(), {k: context[k] for k in names}, decision["inputs"], at)
        d.update({"subject": str(bed.feature), "topic": f"roots/{bed.feature}",
                  "valid_until": (at + _dt.timedelta(days=1)).isoformat()})
        return d

    @staticmethod
    def out_of_soil_note(decision: dict, bed: Bed, at: _dt.datetime) -> dict | None:
        """When a probe reads drier than its soil can be (`soil_floor`) and the morning's
        advice came without it, from the bed's other probes or the weather: a note that it
        may be out of the soil. None otherwise, and when there was no advice at all, whose
        own words say so."""
        context = decision["context"]
        if not context.get("out_of_soil") or decision["rule"] == "soil-untrusted":
            return None
        names = ("out_of_soil", "out_of_soil_cm", "out_of_soil_percent", "soil_floor_percent")
        d = R.judge(out_of_soil_rule(), {k: context[k] for k in names}, decision["inputs"], at)
        d.update({"subject": str(bed.feature), "topic": f"probes/{bed.feature}",
                  "valid_until": (at + _dt.timedelta(days=1)).isoformat()})
        return d

    @staticmethod
    def layering(decision: dict, bed: Bed, at: _dt.datetime) -> dict | None:
        """When two of a bed's probes have learned field capacities `LAYER_GAP` or more
        apart and the bed was given one soil's values, a note that it is layered: one
        wilting point cannot describe two soils, and the advice can wait too long for
        the one that holds water the roots cannot take. None otherwise."""
        context = decision["context"]
        if not context.get("layered") or context.get("layers_configured"):
            return None
        names = ("layered", "layers_configured", "shallow_cm", "deep_cm",
                 "shallow_fc_percent", "deep_fc_percent")
        d = R.judge(layering_rule(), {k: context[k] for k in names}, decision["inputs"], at)
        d.update({"subject": str(bed.feature), "topic": f"layers/{bed.feature}",
                  "valid_until": (at + _dt.timedelta(days=1)).isoformat()})
        return d


def roots_rule() -> R.Rule:
    return R.Rule("soil-roots-blocked", "1", "roots_blocked && !rooting_limit_set", {},
                  alert_key="soilwater.roots_blocked",
                  message_params={"expected": "roots_expected_cm", "blocked": "roots_blocked_cm",
                                  "seen": "roots_seen_cm", "used": "timing_depth_cm"},
                  unit_params={k: "cm" for k in ("expected", "blocked", "seen", "used")},
                  subject_param="bed")


def out_of_soil_rule() -> R.Rule:
    return R.Rule("soil-probe-out-of-soil", "1", "out_of_soil", {},
                  alert_key="soilwater.out_of_soil", subject_param="bed",
                  message_params={"depth": "out_of_soil_cm", "reading": "out_of_soil_percent",
                                  "floor": "soil_floor_percent"},
                  unit_params={"depth": "cm"})


def layering_rule() -> R.Rule:
    return R.Rule("soil-layered", "1", "layered && !layers_configured", {},
                  alert_key="soilwater.layered", subject_param="bed",
                  message_params={"shallow": "shallow_cm", "deep": "deep_cm",
                                  "shallow_fc": "shallow_fc_percent",
                                  "deep_fc": "deep_fc_percent"})


# ---------------------------------------------------------------- regimen

#: The watering check's defaults (Q10): the watering an hour after the 04:00 advice, a
#: drip line's rate, three hours for the water to reach the probes, and the share of the
#: expected rise that counts as arrived. On the recorded summer (`backtest.py`), across 51
#: waterings, every bed that was watered rose by at least 0.74 of what its watering
#: should add and no blocked one by more than 0.27; half is the middle of that gap.
WATERING_CHECK = {"water_after_min": 60.0, "mm_per_hour": 12.0, "soak_min": 180.0,
                  "share": 0.5}


def watering_check(params=None):
    """The regimen that checks a watering arrived: `regimens/watering_check.star`."""
    import regimen as G
    return G.load(os.path.join(HERE, "regimens", "watering_check.star"),
                  params={**WATERING_CHECK, **(params or {})})


#: The soak test's settings (`regimens/soak_test.star`): how far past field capacity to wet
#: the root zone; how long to let it soak in; the share of the expected rise the probes must
#: show; the most water a mineral soil can hold; how long to watch it drain.
SOAK_TEST = {"excess": 0.05, "soak_min": 180.0, "share": 0.5, "saturation": 0.55,
             "drain_min": 2880.0}


def soak_test(params=None):
    """The regimen that soaks a bed to measure its field capacity on the day:
    `regimens/soak_test.star`."""
    import regimen as G
    return G.load(os.path.join(HERE, "regimens", "soak_test.star"),
                  params={**SOAK_TEST, **(params or {})})


def soak_start_context(state, bed: Bed, at: _dt.datetime) -> dict:
    """What the soak test plans from: the bed's root zone when it starts."""
    bed = grown(bed, at.date())
    ctx, _ = bed_context(state, bed, at)
    return {"bed": str(bed.feature), "has_reading": bool(ctx["usable"]), "theta": ctx["theta"],
            "capacity": ctx["field_capacity"], "root_depth_mm": bed.root_depth_mm}


def soak_context(state, bed: Bed, since: _dt.datetime, at: _dt.datetime) -> dict:
    """How the bed's root zone answered a soak begun at `since`: its rise to the peak, the
    peak, and the level it drained back to (`drain_fit`), from the depth-weighted readings
    the checks passed."""
    out = {"has_reading": False, "rise": 0.0, "rise_percent": 0.0, "peak": 0.0,
           "peak_percent": 0.0, "drained": False, "capacity_percent": 0.0}
    zone = _root_zone_hours(state, bed, at, since - 3 * HOUR)
    if zone is None:
        return out
    hours = sorted(zone[0].items())
    before = [v for t, v in hours if t <= since]
    after = [(t, v) for t, v in hours if t > since]
    if not before or not after:
        return out
    peak_t, peak = max(after, key=lambda tv: (tv[1], -tv[0].timestamp()))
    rise = peak - before[-1]
    out.update({"has_reading": True, "rise": round(rise, 4), "rise_percent": round(rise * 100.0, 1),
                "peak": round(peak, 4), "peak_percent": round(peak * 100.0, 1)})
    points = [((t - peak_t) / HOUR, v) for t, v in after if t >= peak_t]
    if points and points[-1][0] >= DRAIN_MIN_H:
        fit = drain_fit(points)
        if fit is not None and fit["excess"] >= DRAIN_MIN_EXCESS:
            out.update({"drained": True, "capacity_percent": round(fit["field_capacity"] * 100.0, 1)})
    return out


def watering_check_context(decision: dict, bed: Bed) -> dict:
    """What the regimen plans from: the morning's advice for the bed."""
    if plantings_of(bed) and decision.get("evaluated_at"):
        bed = grown(bed, _dt.datetime.fromisoformat(decision["evaluated_at"]).date())
    return {"advice": decision["rule"], "refill_mm": decision["context"]["refill_mm"],
            "root_depth_mm": bed.root_depth_mm, "bed": str(bed.feature)}


def response_context(state, bed: Bed, since: _dt.datetime, at: _dt.datetime) -> dict:
    """How much the root zone's water rose between `since` and `at`, as a fraction and
    in percentage points, from the same depth-weighted reading the advice uses; and,
    when the bed's valve reports, how long it stood open (`valve_open_min`) and whether
    that is known (`valve_known`)."""
    before, _ = bed_context(state, bed, since)
    after, _ = bed_context(state, bed, at)
    ok = before["usable"] and after["usable"]
    rise = after["theta"] - before["theta"] if ok else 0.0
    known, minutes = valve_minutes(state, bed.valve, since, at) if bed.valve else (False, 0.0)
    return {"has_reading": ok, "rise": round(rise, 4), "rise_percent": round(rise * 100.0, 1),
            "valve_known": known, "valve_open_min": round(minutes, 1)}


def _valve_windows(state, valve: UUID, since: _dt.datetime, at: _dt.datetime) -> list:
    """`[(opened, shut)]` the valve's reports show between `since` and `at`."""
    rows = sorted((o.measured_at, bool(o.result)) for o in state.live_observations_of(valve)
                  if since <= o.measured_at <= at and o.received_at <= at
                  and isinstance(o.result, bool))
    out, opened = [], None
    for t, is_open in rows:
        if is_open and opened is None:
            opened = t
        elif not is_open and opened is not None:
            out.append((opened, t))
            opened = None
    if opened is not None:
        out.append((opened, at))
    return out


def valve_minutes(state, valve: UUID, since: _dt.datetime, at: _dt.datetime) -> tuple[bool, float]:
    """How long a valve stood open between two times, from its open-and-shut series as
    received by `at`: `(known, minutes)`. Known needs its state at `since` — its last
    report before then — or a first report after it that opens it. A first report that
    shuts a valve never seen opening is a lost message, not a valve that stayed shut."""
    rows = sorted((o for o in state.live_observations_of(valve)
                   if o.received_at <= at and o.measured_at <= at and isinstance(o.result, bool)),
                  key=lambda o: o.measured_at)
    before = [o for o in rows if o.measured_at < since]
    inside = [o for o in rows if o.measured_at >= since]
    is_open = before[-1].result if before else None
    if is_open is None and inside and not inside[0].result:
        return False, 0.0
    if is_open is None and not inside:
        return False, 0.0
    minutes, opened = 0.0, since if is_open else None
    for o in inside:
        if o.result and opened is None:
            opened = o.measured_at
        elif not o.result and opened is not None:
            minutes += (o.measured_at - opened) / _dt.timedelta(minutes=1)
            opened = None
    if opened is not None:
        minutes += (at - opened) / _dt.timedelta(minutes=1)
    return True, minutes


def render(decision: dict, language: str = "en", state=None, units: str | None = None) -> str | None:
    """A decision's advice in `language`, naming the bed by its label there."""
    return R.render(decision, language, state, units)


# ---------------------------------------------------------------- backtest

#: A bed's fields the advisory sets for itself, not the farm's config: the balance's
#: correction from a probe's rate (`et_scale`), the crops' clock by the season's warmth
#: (`clock`), and the depth the youngest roots time the watering by (`timing_depth_mm`).
DERIVED = frozenset({"et_scale", "clock", "timing_depth_mm"})


def bed_from_config(b: dict) -> Bed:
    """A bed from its entry in the module's config, its ids and dates parsed. A field the
    advisory derives (`DERIVED`) is refused, as is any field `Bed` does not have."""
    derived = sorted(DERIVED & set(b))
    if derived:
        raise ValueError(f"a bed's config cannot set {', '.join(derived)}: "
                         "the advisory derives them")
    return Bed(**{**b, "feature": UUID(b["feature"]),
                  "planted": _dt.date.fromisoformat(b["planted"]) if b.get("planted") else None,
                  "plantings": tuple((p["crop"], _dt.date.fromisoformat(p["planted"])
                                      if p.get("planted") else None,
                                      tuple(UUID(x) for x in p.get("probes", ())))
                                     for p in b.get("plantings", ())),
                  "reference": UUID(b["reference"]) if b.get("reference") else None,
                  "layers": tuple(tuple(x) for x in b.get("layers", ()))})


def main(argv=None) -> int:
    """The advisory as its own process (§8.3; Q11): over the host's socket, holding only
    the token its grant gave it — a systemd credential, or `FIELDMESH_MODULE_TOKEN`."""
    import argparse
    import json
    import modhost as M

    ap = argparse.ArgumentParser(description="Soil-moisture advisory, as a module process")
    ap.add_argument("--socket", required=True)
    ap.add_argument("--config", required=True,
                    help="JSON: {\"beds\": [{\"feature\": id, \"field_capacity\": 0.3, "
                         "\"wilting_point\": 0.12, \"crop\": \"tomato\", \"planted\": \"2026-05-01\", "
                         "...}], \"forecast\": id or null, "
                         "\"station\": {\"lat\": 35.1, \"elevation_m\": 243, "
                         "\"timezone\": \"America/Chicago\", \"air_temperature\": id, ...} "
                         "or null, \"climate\": a daily record of past years, as "
                         "tools/weather_csv.py writes, for a sown crop's clock, or null}")
    ap.add_argument("--at", help="advise for this moment (ISO 8601); default now")
    ap.add_argument("--language", default="en")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as h:
        config = json.load(h)
    beds = [bed_from_config(b) for b in config["beds"]]
    forecast = UUID(config["forecast"]) if config.get("forecast") else None
    station = None
    if config.get("station"):
        import eto as E
        spec = dict(config["station"])
        for key in ("air_temperature", "relative_humidity", "solar_radiation",
                    "wind_speed", "precipitation"):
            if spec.get(key):
                spec[key] = UUID(spec[key])
        station = E.Station(**spec)
    rain_gauge = UUID(config["rain_gauge"]) if config.get("rain_gauge") else None
    normal = None
    if config.get("climate"):
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import thermal as T
        normal = T.Normal(T.read_climate(config["climate"]))
    at = (_dt.datetime.fromisoformat(args.at) if args.at
          else _dt.datetime.now(tz=_dt.timezone.utc))
    with M.ModuleClient(args.socket, M.token_from_environment()) as client:
        state = client.state(at)
        for event in Advisor(client.log(), normal=normal,
                             rain_gauge=rain_gauge).advise(state, beds, at, forecast=forecast,
                                                  station=station):
            print(json.dumps({"rule": event.payload["rule"],
                              "message": render(event.payload, args.language, state)},
                             ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

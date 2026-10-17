# SPDX-License-Identifier: AGPL-3.0-or-later
"""The soil-moisture advisory backtested on the virtual farm (`sim/physics.py`): a bed and
its crop simulated hour by hour, its probes read through the same checks a farm's are, and
the advice followed to the letter (`backtest`), or given from the farm's weather with no
probe (`weather_backtest`). Scored by the water given, what drained past the roots, and
the hours the bed was short.

Kept apart from the advisory itself (`soilwater.py`), which never imports the simulator:
this file does, and is not part of the module's process."""
from __future__ import annotations

import datetime as _dt
import math
import os
import random
import sys
from dataclasses import asdict, dataclass, replace

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from soilwater import (CROPS, HOUR, ROOT_AT_SOWING_MM, SECOND_CHECK_HOUR,  # noqa: E402
                       Advisor, Bed, basal_day, crop_day, response_context,
                       watering_check_context)
import vocab as V  # noqa: E402
from model import DatastreamKind  # noqa: E402

#: A plough pan: the silt loam pressed denser by years of tillage at one depth, holding
#: less air and passing water slowly (a round, typical value: measured pans pass 0.1 to
#: a few millimetres an hour), 5 cm thick. With `growing_bed(pan_mm=...)` water as well as
#: roots meets it; without, a pan only stops roots (`grow`'s `hardpan_mm`).
PAN = {"saturation": 0.36, "field_capacity": 0.30, "wilting_point": 0.13, "ks_mm_per_h": 0.5,
       "suction_mm": 170.0, "residual": 0.066, "pore_connectivity": 0.0}
PAN_MM = 50.0


@dataclass(frozen=True)
class VirtualFarm:
    """How the virtual farm departs from what the advice is told, for one backtest: its
    crop uses `use` times its curve's water, runs through its stages `stages` times as long
    and roots `roots` times as deep; its soil's field capacity and wilting point are
    `capacity` and `wilting` off (the growing bed's and the backtest bed's; a soil given in
    whole is as given); and each probe reads off by its own amount, drawn with a spread of
    `probe_sd`. The advice is told the crop's curve and the soil's values as they are
    written. `NOMINAL` departs from nothing, and a backtest on it is the one before
    2026-10-17, to the bit."""
    use: float = 1.0
    stages: float = 1.0
    roots: float = 1.0
    capacity: float = 0.0
    wilting: float = 0.0
    probe_sd: float = 0.0
    seed: int = 0

    @classmethod
    def drawn(cls, seed: int, *, use_sd: float = 0.12, stage_sd: float = 0.10,
              root_sd: float = 0.15, capacity_sd: float = 0.015, wilting_sd: float = 0.01,
              probe_sd: float = 0.015) -> "VirtualFarm":
        """A farm drawn from `seed`: its crop's use lognormal about the curve's, the rest
        normal and held within twice their spread. The spreads are a field's usual
        departures from a crop's published values and a soil's typical ones, and a factory
        calibration's error; assumed."""
        rng = random.Random(f"virtual farm {seed}")

        def held(mean, sd):
            return max(mean - 2 * sd, min(mean + 2 * sd, rng.gauss(mean, sd)))
        return cls(use=math.exp(held(0.0, use_sd)), stages=held(1.0, stage_sd),
                   roots=held(1.0, root_sd), capacity=held(0.0, capacity_sd),
                   wilting=held(0.0, wilting_sd), probe_sd=probe_sd, seed=seed)

    def offset(self, probe: str) -> float:
        """How far the probe named `probe` reads off."""
        if not self.probe_sd:
            return 0.0
        return random.Random(f"probe {self.seed} {probe}").gauss(0.0, self.probe_sd)


NOMINAL = VirtualFarm()


def _departed(bed, farm: VirtualFarm) -> None:
    """The backtest bed, one bucket, as `farm` has its soil and crop."""
    bed.field_capacity += farm.capacity
    bed.wilting_point += farm.wilting
    bed.theta = bed.field_capacity
    bed.crop_coefficient *= farm.use


def growing_bed(pan_mm: float | None = None, farm: VirtualFarm = NOMINAL):
    """The virtual bed for a crop that grows: the backtest bed's silt loam (field capacity
    0.30, wilting point 0.12) 1.5 m deep in layers, so roots can reach down through it,
    its water moving between layers below field capacity by Darcy's law; a number for
    (`physics.LayeredBed`). With `pan_mm`, a plough pan (`PAN`) lies at that depth, which
    water passes slowly too."""
    import physics as ph
    silt = dict(saturation=0.45, field_capacity=0.30 + farm.capacity,
                wilting_point=0.12 + farm.wilting, ks_mm_per_h=8.0,
                suction_mm=170.0, residual=0.065, pore_connectivity=0.19)   # Rosetta3: Dickson's texture
    if pan_mm is None:
        horizons = (ph.Horizon(1500.0, **silt),)
    else:
        horizons = (ph.Horizon(pan_mm, **silt), ph.Horizon(PAN_MM, **PAN),
                    ph.Horizon(1500.0 - pan_mm - PAN_MM, **silt))
    return ph.LayeredBed(name="field", depth_mm=ROOT_AT_SOWING_MM, horizons=horizons,
)


#: The ground an established crop (a lawn) covers, for the simulator's soil evaporation:
#: FAO-56's estimate from the basal coefficient (Eq. 76) leaves a mown lawn a third bare, and
#: a lawn watered every two or three days in July 2010 then used 1.20 of the reference ET,
#: where FAO-56's single coefficient for cool-season turf is 0.95 (Table 12) and its basal
#: one 0.90 (Table 17). At 0.95 cover it used 0.96.
ESTABLISHED_COVER = 0.95


def grow(soil, crop: str, days: float, hardpan_mm: float | None = None,
         gdd: float | None = None, farm: VirtualFarm = NOMINAL) -> None:
    """The virtual crop `days` after sowing, or `gdd` degree-days for a crop staged in them:
    its crop coefficient, and for a layered soil its basal one (`basal_day`) and, for an
    established crop, its ground cover (`ESTABLISHED_COVER`), its depletion fraction (the
    share of its water it uses freely), and its roots' depth, stopped at `hardpan_mm` when
    the soil has one; as `farm` has the crop."""
    days, gdd = days / farm.stages, (None if gdd is None else gdd / farm.stages)
    kc, root_mm = crop_day(crop, days, gdd)
    root_mm = root_mm * farm.roots
    soil.crop_coefficient = kc * farm.use
    soil.depletion_fraction = CROPS[crop]["p"]
    if hasattr(soil, "basal_coefficient"):
        soil.basal_coefficient = basal_day(crop, days, gdd) * farm.use
    if hasattr(soil, "ground_cover") and CROPS[crop]["season_days"] == 0:
        soil.ground_cover = ESTABLISHED_COVER
    soil.set_roots(root_mm if hardpan_mm is None else min(root_mm, hardpan_mm))


def forecasts(climate, start: _dt.datetime, days: float, seed: int):
    """The season's rain forecasts in a log, and the hourly truth they were made from
    (`irrigation_drill.forecasts`). Building them is a third of a backtest's time and the
    same for every backtest of one summer, draw and span, so with `FIELDMESH_FORECASTS`
    naming a directory each is built once and kept there, keyed by what it is made from."""
    import forecaster as FCS
    import irrigation_drill as D
    where = os.environ.get("FIELDMESH_FORECASTS")
    if not where:
        return D.forecasts(climate, start, days, FCS.Skill(), seed)
    import hashlib
    import pickle
    first, last = (start - _dt.timedelta(days=2)).date(), (start + _dt.timedelta(days=days + 2)).date()
    window = sorted((d.isoformat(), sorted(v.items())) for d, v in climate.days.items()
                    if first <= d <= last)
    key = hashlib.sha256(repr((type(climate).__name__, getattr(climate, "seed", None),
                               start.isoformat(), float(days), seed, FCS.Skill(),
                               window)).encode()).hexdigest()[:32]
    path = os.path.join(where, key + ".pickle")
    if os.path.exists(path):
        with open(path, "rb") as h:
            return pickle.load(h)
    made = D.forecasts(climate, start, days, FCS.Skill(), seed)
    os.makedirs(where, exist_ok=True)
    part = f"{path}.{os.getpid()}"
    with open(part, "wb") as h:
        pickle.dump(made, h, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(part, path)
    return made


#: Hours a root zone counts as short of air: less than a tenth of its volume holding air,
#: below which roots and soil life start to suffocate (Grable and Siemer 1968).
AIRLESS_SHARE = 0.10


class Score:
    """How a backtest bed fared, besides its hours short (half its available water gone):
    the hours its crop used less than its full demand, past its own `p`; the hours its
    root zone was short of air; and the transpiration its dryness cost it, mm, FAO-33's
    measure of lost yield (`physics.SoilBed.demand_mm`)."""

    def __init__(self):
        self.below_p_h = self.airless_h = 0.0

    def tick(self, bed) -> None:
        if bed.water_use < 1.0 - 1e-9:
            self.below_p_h += 1.0 / 12.0
        if bed.air_filled < AIRLESS_SHARE:
            self.airless_h += 1.0 / 12.0

    def result(self, bed, second=None) -> dict:
        out = {"below_p_h": self.below_p_h, "airless_h": self.airless_h,
               "transpiration_lost_mm": bed.demand_mm - bed.transpired_mm,
               "demand_mm": bed.demand_mm}
        if second is not None:
            out["second_transpiration_lost_mm"] = second.demand_mm - second.transpired_mm
        return out


def noise_streams(seed: int, names: list) -> list:
    """A random stream for each of a backtest's probes, by its name: each draws its noise
    from its own, so a probe added or taken away leaves the others' readings as they were,
    and two runs set side by side differ by that probe alone, not by noise that moved. The
    first keeps the seed's own stream, so a run with one probe is what it was when all of a
    run's probes drew from that one (before 2026-10-14)."""
    import random

    return [random.Random(seed if i == 0 else f"{seed} {name}") for i, name in enumerate(names)]


def backtest(climate, start: _dt.datetime, days: float, *, seed: int = 1,
             probe_noise: float = 0.01, check=None, blocked=frozenset(),
             forgotten=frozenset(), valve: bool = False, soil=None, depths=(0.20,),
             configured=None, learn: bool = True, layers=(), probe_bias: float = 0.0,
             crop: str | None = None, planted: _dt.date | None = None,
             knows_crop: bool = True, hardpan_mm: float | None = None,
             knows_hardpan: bool = False, second: tuple | None = None,
             knows_second: bool = True, in_second: tuple = (), second_depths: tuple = (),
             name_probes: bool = False, rain_share: float = 1.0,
             rain_gauge: bool = False, knows_cover: bool = False,
             virtual_crop: str | None = None, dense_pan: bool = False,
             second_check_hour: int | None = SECOND_CHECK_HOUR,
             farm: VirtualFarm = NOMINAL,
             depletion_fraction: float | None = None,
             young_fraction: float | None = 0.2) -> dict:
    """§11: the advisory on a recorded summer, watering when it says to and skipping when
    it says rain is coming, scored like `sim/irrigation_drill.py`'s policies — water
    applied, water drained past the roots, crop stress — so it can be set beside the
    drip timer most farms run. Hourly probe readings at 20 cm, the drill's forecasts in
    the log, the advice at 04:00 and the watering from 05:00.

    With `check`, a watering-check regimen (`watering_check()`) runs after each advice to
    water, and the days in `blocked` (counted from `start`) are waterings that never reach
    the bed, as through a blocked drip line: the person waters, the soil gets nothing.
    The days in `forgotten` are advice to water that nobody followed. With `valve`, the
    bed's valve reports opening and shutting, as an OpenSprinkler station does through the
    MQTT bridge: it runs on a blocked day and stays shut on a forgotten one. The result's
    `checks` says, per watering, whether the regimen said the water did not arrive, and in
    which words.

    `soil` is the virtual bed, the drill's (`irrigation_drill.bed`) by default; a
    `physics.LayeredBed` makes a bed of horizons, read by a probe at each of `depths`.
    `configured` is the field capacity and wilting point the bed is set up with, as
    `(fc, wp)`, the virtual bed's own by default: give it a soil survey's for the bed a
    survey does not describe, and `layers` each layer's (`Bed.layers`). `learn` lets the
    advisory learn the field capacity from the probes (`Bed.learn`). `probe_bias` is added
    to every reading, as an uncalibrated probe reads high or low. The result adds what ran off, the field capacity the last
    advice used, what each probe had learned by then, and whether it said the bed is
    layered.

    With `crop`, sown on `planted`, the virtual crop grows through its season as FAO-56's
    curve has it (`crop_day`): each day its crop coefficient and its roots' depth. The
    virtual bed is then the silt loam in layers (`growing_bed`). With `knows_crop`, the
    advice is told the crop and the day; without, it is set up as a bed with no crop
    named: 30 cm of roots and a coefficient of 1. With `hardpan_mm`, the virtual crop's
    roots stop there whatever its curve says; with `knows_hardpan`, the bed is set up with
    it as its rooting limit (`Bed.rooting_limit_mm`). The result's `roots` is each
    morning's `(day, curve's depth cm, depth the advice used cm, deepest probe roots
    were seen at cm, probe they seemed not to reach cm or None)`. With `dense_pan` the pan
    at `hardpan_mm` is a horizon that passes water slowly too (`PAN`), not only a depth the
    roots stop at.

    `second`, `(crop, planted)`, is a second planting in the same bed, its own patch of
    the same soil, watered whenever the bed is; the probes are in the first's. Until it is
    sown the patch is bare, drawing nothing, and its hours short count from that day (before
    2026-10-15 the patch grew as a seedling from the start, and its hours counted from then:
    lettuce sown on 15 June was "short" in May). With
    `knows_second` the bed is set up with both (`Bed.plantings`), without it with the
    first alone; the probes at the depths in `in_second` are in the second's patch, and
    `second_depths` adds probes there. With `name_probes` each planting names the probes in
    its patch (`Bed.plantings`). `rain_share` is the share of the rain that reaches the
    virtual bed (0 under a tunnel), while the forecasts are the open sky's; `rain_gauge`
    gives the farm a gauge in the open, and `knows_cover` sets the bed's `rain_share`.
    `virtual_crop` is what the virtual bed truly grows, where it differs from `crop`. The
    result's `second_stressed_h` is the second planting's hours short."""
    import statistics

    sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sim"))
    import forecaster as FCS
    import irrigation_drill as D
    import physics as ph
    from ids import uuid7
    from log import Log
    from model import ClockQuality, Datastream, Installation, Observation

    state, fc, truth = forecasts(climate, start, days, seed)
    b = soil if soil is not None else (growing_bed(hardpan_mm if dense_pan else None, farm)
                                       if crop else D.bed())
    if soil is None and not crop:
        _departed(b, farm)
    b.rain_share = rain_share
    b2 = None
    if second is not None:
        b2 = growing_bed(hardpan_mm if dense_pan else None, farm)
        b2.name = "second"
    world = ph.World(start=start, climate=climate, beds=[b] if b2 is None else [b, b2])
    land, probes = uuid7(), []
    placed = [(d, d in in_second) for d in depths] + [(d, True) for d in second_depths]
    for depth, in_patch in placed:
        sensor = uuid7()
        raw = Datastream(id=uuid7(), thing=uuid7(), sensor=sensor,
                         observed_property=V.SOIL_WATER, feature=land, kind=DatastreamKind.RAW,
                         unit="1", expected_interval=3600.0, max_latency=3600.0)
        probe = Datastream(id=uuid7(), thing=raw.thing, sensor=sensor,
                           observed_property=V.SOIL_WATER, feature=land,
                           kind=DatastreamKind.DERIVED, derived_from=raw.id, unit="cm3/cm3",
                           expected_interval=3600.0, max_latency=3600.0)
        for rec in (raw, probe, Installation(uuid7(), sensor, land, start - 24 * HOUR,
                                             depth_m=depth)):
            state.add(rec)
        probes.append((probe, depth, in_patch))
    cal = uuid7()
    valve_ds = None
    if valve:
        valve_ds = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(),
                              observed_property=V.VALVE_OPEN, feature=land,
                              kind=DatastreamKind.RAW, unit=None)
        state.add(valve_ds)
        state.add(Observation(uuid7(), valve_ds.id, start - HOUR, 1.0, start - HOUR, False,
                              ClockQuality.NETWORK, node="opensprinkler", boot=1, seq=0))

    def report(when, is_open, seq=[1]):
        seq[0] += 1
        state.add(Observation(uuid7(), valve_ds.id, when, 1.0, when, is_open,
                              ClockQuality.NETWORK, node="opensprinkler", boot=1, seq=seq[0] & 0xFFFF))
    capacity, wilting = configured or (b.field_capacity, b.wilting_point)
    bed = Bed(land, capacity, wilting, root_depth_mm=300.0 if crop else b.depth_mm,
              skip_rain_mm=D.SKIP_MM, valve=valve_ds.id if valve_ds else None, learn=learn,
              young_fraction=young_fraction,
              **({"depletion_fraction": depletion_fraction} if depletion_fraction else {}),
              layers=tuple(layers), crop=crop if knows_crop else None,
              planted=planted if crop and knows_crop else None,
              rooting_limit_mm=hardpan_mm if knows_hardpan else None,
              rain_share=rain_share if knows_cover else None)
    if second is not None and knows_second:
        if name_probes:
            first_sensors = tuple(pr.sensor for pr, _, there in probes if not there)
            second_sensors = tuple(pr.sensor for pr, _, there in probes if there)
            plantings = ((crop, planted, first_sensors), (*second, second_sensors))
        else:
            plantings = ((crop, planted), tuple(second))
        bed = replace(bed, crop=None, planted=None, plantings=plantings)
    gauge = None
    if rain_gauge:
        gauge = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(),
                           observed_property=V.PRECIPITATION_DEPTH, feature=uuid7(),
                           kind=DatastreamKind.RAW, unit="mm", expected_interval=3600.0,
                           max_latency=3600.0)
        state.add(gauge)
    advisor = Advisor(Log(), rain_gauge=gauge.id if gauge else None)
    noise = dict(zip((p.id for p, _, _ in probes),
                     noise_streams(seed, [f"{d} {patch}" for _, d, patch in probes])))
    offset = {p.id: farm.offset(f"{d} {patch}") for p, d, patch in probes}
    rain_hour = 0.0
    roots, second_h = [], 0.0
    applied, dose_now, stressed_h, stress, advice, last, last_at = 0.0, 0.0, 0.0, [], {}, None, None
    score = Score()
    decide_hours = (D.DECIDE_HOUR,) + ((second_check_hour,) if second_check_hour is not None else ())
    water_at = D.WATER_HOUR
    runner = None
    if check is not None:
        import regimen as G
        runner, checks = G.Runner(Log()), []

        def respond(subject, run):
            return response_context(state, bed, run.started_at, world.when)
    for n in range(int(days * 24 * 12)):
        when = world.when
        if crop and when.hour == 0 and when.minute == 0:
            grow(b, virtual_crop or crop,
                 (when.date() - planted).days if planted is not None else 0, hardpan_mm,
                 farm=farm)
            if b2 is not None:
                if when.date() < second[1]:
                    b2.crop_coefficient = 0.0          # bare, waiting to be sown
                else:
                    grow(b2, second[0], (when.date() - second[1]).days, hardpan_mm, farm=farm)
        if when.minute == 0:
            for probe, depth, in_patch in probes:
                patch = b2 if b2 is not None and in_patch else b
                truth = patch.theta_at(depth) if hasattr(patch, "theta_at") else patch.theta
                read = (truth + probe_bias + offset[probe.id]
                        + noise[probe.id].gauss(0.0, probe_noise))
                state.add(Observation(uuid7(), probe.id, when, 60.0, when, round(read, 3),
                                      ClockQuality.GPS, node="!soil", boot=1, seq=n & 0xFFFF,
                                      calibration=cal))
        if when.hour in decide_hours and when.minute == 0:
            # Through `advise`, as the module's own process runs, so each morning is in the
            # advisor's log for the next to read (`Advisor._held`).
            water_at = when.hour + 1
            d = next(e.payload for e in advisor.advise(state, [bed], when, forecast=fc.id)
                     if e.payload["topic"].startswith("advice/"))
            advice[d["rule"]] = advice.get(d["rule"], 0) + 1
            last, last_at = d, when
            c = d["context"]
            roots.append(((when - start).days, c["roots_expected_cm"], c["root_depth_cm"],
                          c["roots_seen_cm"], c["roots_blocked_cm"] if c["roots_blocked"] else None))
            want = d["context"]["refill_mm"] if d["rule"] == "soil-water-now" else 0.0
            dose_now = want / 12.0
            if runner is not None:
                runner.start(check, watering_check_context(d, bed), when, subject=bed.feature)
        day = (when - start).days
        if when.hour == water_at and dose_now and day not in forgotten:
            if valve_ds is not None and when.minute == 0:
                report(when, True)
            if day not in blocked:
                world.irrigate(b.name, dose_now)
                if b2 is not None:
                    world.irrigate(b2.name, dose_now)
            applied += dose_now
        if valve_ds is not None and when.hour == water_at + 1 and when.minute == 0 \
                and dose_now and day not in forgotten:
            report(when, False)
        if runner is not None and when.minute == 0:
            for e in runner.tick(when, respond):
                checks.append({"day": (_dt.datetime.fromisoformat(e.payload["due_at"]) - start).days,
                               "alert": e.payload["alert"],
                               "key": (e.payload["message"] or {}).get("key"),
                               "rise_percent": e.payload["context"].get("rise_percent"),
                               "expected_percent": round(e.payload["context"]["expected_percent"], 1)})
        if when.hour == water_at + 1 and when.minute == 0:
            dose_now = 0.0
        tick = world.step()
        if gauge is not None:
            rain_hour += tick.weather.rain_mm
            if (world.when.minute == 0):
                state.add(Observation(uuid7(), gauge.id, world.when, 60.0, world.when,
                                      round(rain_hour, 2), ClockQuality.NETWORK, node="gauge",
                                      boot=1, seq=n & 0xFFFF))
                rain_hour = 0.0
        s = tick.soil_stress[b.name]
        stress.append(s)
        if s >= 0.5:
            stressed_h += 1.0 / 12.0
        score.tick(b)
        if b2 is not None and when.date() >= second[1] and tick.soil_stress[b2.name] >= 0.5:
            second_h += 1.0 / 12.0
    return {"policy": "advisory", "applied_mm": applied, "drained_mm": b.drained_mm,
            "farm": asdict(farm),
            **score.result(b, b2),
            "second_stressed_h": second_h if b2 is not None else None,
            "runoff_mm": b.runoff_mm, "field_capacity": last["context"]["field_capacity"],
            "learned": [{k: v for k, v in x.items() if k != "datastream"}
                        for x in last["inputs"].get("learned", [])],
            "layered": Advisor.layering(last, bed, last_at) is not None,
            "mean_stress": statistics.mean(stress), "stressed_h": stressed_h,
            "advice": advice, "checks": checks if runner is not None else None, "roots": roots}


def weather_backtest(climate, start: _dt.datetime, days: float, *, seed: int = 1,
                     rate_mm_per_h: float = 12.0, record_valve: bool = True,
                     probe: bool = False, outage: tuple | None = None,
                     fallback: bool = True, probe_noise: float = 0.01,
                     reference: bool = False, reference_bias: float = 0.0,
                     crop: str | None = None, planted: _dt.date | None = None,
                     knows_crop: bool = True, warmth: bool = False,
                     clock: bool = False, second: tuple | None = None,
                     knows_second: bool = True, soil=None, virtual_crop: str | None = None,
                     hardpan_mm: float | None = None, knows_hardpan: bool = False,
                     second_check_hour: int | None = SECOND_CHECK_HOUR,
                     farm: VirtualFarm = NOMINAL, site: tuple | None = None) -> dict:
    """The advisory for the backtest bed with **no probe**, from a station on the farm:
    hourly air temperature, humidity, sunshine and rain, as the virtual farm's recorded
    weather gives them (`backtest` for the rest). Sunshine is each recorded day's total
    spread over the hours in the clear sky's shape (`sun.py`); there is no wind sensor,
    so FAO-56's 2 m/s stands in. Watering runs at `rate_mm_per_h` from 05:00 for as long
    as the advice's millimetres take, and with `record_valve` the valve reports it.

    Scored as `backtest` is. The balance's reference ET is FAO-56 Penman–Monteith; the
    virtual farm's own water loss is Hargreaves' formula on the same sunshine, so the
    balance runs on a model of the bed that is not the bed, as on a real farm.

    With `probe`, the bed has its probe at 20 cm as in `backtest`, and the station beside
    it. During `outage`, `(first day, last day)` counted from `start`, the probe sends
    nothing, as a node whose radio is down. With `fallback` the advisory carries the bed
    on the weather from the probe's last good reading; without it, the station is not
    given, and the bed has no advice while the probe is silent.

    With `reference`, a second bed of the same soil and crop beside it has a probe at 20 cm
    and a recorded valve, and is watered on its own advice; the bed scored names it as its
    reference (`Bed.reference`), so its balance is corrected by how fast that bed dries.
    `reference_mm` is what the second bed was given; `reference_bias` is added to every
    reading of its probe, as a probe that reads off.

    With `crop`, sown on `planted`, the virtual crop grows as in `backtest`; with
    `knows_crop` the balance follows its curve, without it holds a coefficient of 1 and
    30 cm of roots all season. With `warmth`, the virtual crop goes through its curve by
    the season's degree-days against the normal year of `climate`'s other years
    (`thermal.growing_days`), as a real crop runs early in a warm year; with `clock`, the
    advice is given that normal year, and times the curve the same way from the station's
    temperatures (`Advisor.clocked`). The result's `crop_days` is the last morning's
    `((growing days, degree-days) the advice used, the virtual crop's)`. `second` and `knows_second` are
    a second planting in the bed, as in `backtest`.

    `soil` is the virtual bed in place of the growing bed (a lawn's, say), `virtual_crop`
    what it truly grows when that differs from `crop`, the crop the advice is told (a lawn
    using the 1998 edition's water while the advice believes the revision's).
    `hardpan_mm` stops the virtual roots, and with `knows_hardpan` the bed's rooting limit
    is set to it."""
    import statistics

    sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sim"))
    import eto as E
    import forecaster as FCS
    import irrigation_drill as D
    import physics as ph
    import sun as SUN
    from ids import uuid7
    from log import Log
    from model import ClockQuality, Datastream, Installation, Observation

    state, fc, truth = forecasts(climate, start, days, seed)
    b = soil if soil is not None else (growing_bed(farm=farm) if crop else D.bed())
    rb = growing_bed(farm=farm) if crop else D.bed()
    if not crop:
        for bucket in ((b,) if soil is None else ()) + (rb,):
            _departed(bucket, farm)
    rb.name = "reference"
    grows = virtual_crop or crop
    b2 = None
    if second is not None:
        b2 = growing_bed(farm=farm)
        b2.name = "second"
    world = ph.World(start=start, climate=climate,
                     beds=[b] + ([rb] if reference else []) + ([b2] if b2 is not None else []))
    land, ref_land = uuid7(), uuid7()

    def series(prop, unit):
        ds = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(), observed_property=prop,
                        feature=uuid7(), kind=DatastreamKind.RAW, unit=unit,
                        expected_interval=3600.0, max_latency=3600.0)
        state.add(ds)
        return ds
    air, rh = series(V.AIR_TEMPERATURE, "Cel"), series(V.RELATIVE_HUMIDITY, "%")
    sunshine, rain = series(V.SOLAR_RADIATION, "W/m2"), series(V.PRECIPITATION_DEPTH, "mm")
    valve, ref_valve = series(V.VALVE_OPEN, None), series(V.VALVE_OPEN, None)
    cal = uuid7()

    def add_probe(where):
        sensor = uuid7()
        raw = Datastream(id=uuid7(), thing=uuid7(), sensor=sensor,
                         observed_property=V.SOIL_WATER, feature=where, kind=DatastreamKind.RAW,
                         unit="1", expected_interval=3600.0, max_latency=3600.0)
        ds = Datastream(id=uuid7(), thing=raw.thing, sensor=sensor,
                        observed_property=V.SOIL_WATER, feature=where,
                        kind=DatastreamKind.DERIVED, derived_from=raw.id,
                        unit="cm3/cm3", expected_interval=3600.0, max_latency=3600.0)
        for rec in (raw, ds, Installation(uuid7(), sensor, where, start - 24 * HOUR,
                                          depth_m=0.20)):
            state.add(rec)
        return ds
    probe_ds = add_probe(land) if probe else None
    ref_ds = add_probe(ref_land) if reference else None
    named = [(ds, name) for ds, name in ((probe_ds, "bed"), (ref_ds, "reference")) if ds]
    noise = dict(zip((ds.id for ds, _ in named), noise_streams(seed, [n for _, n in named])))
    offset = {ds.id: farm.offset(n) for ds, n in named}
    # The virtual farm's hours are local solar time, so its station's day is UTC's.
    lat, elevation = site if site is not None else (D.LAT, D.ELEVATION_M)
    station = E.Station(lat=lat, elevation_m=elevation, timezone="UTC",
                        air_temperature=air.id, relative_humidity=rh.id,
                        solar_radiation=sunshine.id, precipitation=rain.id)
    told = dict(crop=crop, planted=planted) if crop and knows_crop else {}
    if second is not None and knows_second:
        told = dict(plantings=((crop, planted), tuple(second)))
    bed = Bed(land, b.field_capacity, b.wilting_point, root_depth_mm=300.0 if crop else b.depth_mm,
              skip_rain_mm=D.SKIP_MM, valve=valve.id if record_valve else None,
              application_mm_per_h=rate_mm_per_h if record_valve else None,
              reference=ref_land if reference else None,
              rooting_limit_mm=hardpan_mm if knows_hardpan else None, **told)
    ref_bed = Bed(ref_land, rb.field_capacity, rb.wilting_point,
                  root_depth_mm=300.0 if crop else rb.depth_mm, skip_rain_mm=D.SKIP_MM,
                  valve=ref_valve.id, application_mm_per_h=rate_mm_per_h, **told)
    beds = [bed, ref_bed] if reference else [bed]
    sim_bed = {str(land): (b, valve, record_valve), str(ref_land): (rb, ref_valve, True)}
    seq = [0]

    def write(ds, when, value):
        seq[0] += 1
        state.add(Observation(uuid7(), ds.id, when, 60.0, when, value, ClockQuality.NETWORK,
                              node="station", boot=1, seq=seq[0] & 0xFFFF))

    def hourly_sun(day):
        """Each hour's mean W/m2 ending at hour h, the day's recorded total in the clear
        sky's shape."""
        total_mj = climate.days.get(day, {}).get("ALLSKY_SFC_SW_DWN", 0.0)
        ends = [_dt.datetime.combine(day, _dt.time(), tzinfo=_dt.timezone.utc)
                + _dt.timedelta(hours=h) for h in range(1, 25)]
        shape = [SUN.clear_sky_mean_w(lat, 0.0, elevation, e, 3600.0) for e in ends]
        scale = total_mj * 1e6 / (3600.0 * sum(shape)) if sum(shape) else 0.0
        return {e: w * scale for e, w in zip(ends, shape)}

    normal = truth = truth2 = None
    if crop and (warmth or clock):
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import thermal as T
        record = {d: (v["T2M_MIN"], v["T2M_MAX"]) for d, v in climate.days.items()
                  if "T2M_MIN" in v and "T2M_MAX" in v}
        normal = T.Normal(record, without=planted.year)
        if warmth:
            last = start.date() + _dt.timedelta(days=int(days) + 1)

            def clock_of(c, sown):
                if CROPS[c]["gdd_stages"] is not None:
                    return {d: (None, g) for d, g in
                            T.cumulative_gdd(c, sown, last, record, normal).items()}
                return {d: (g, None) for d, g in
                        T.growing_days(c, sown, last, record, normal).items()}
            truth = clock_of(crop, planted)
            if second is not None:
                truth2 = clock_of(second[0], second[1])
    advisor = Advisor(Log(), normal=normal if clock else None, clocks=clock)
    applied, stressed_h, stress, advice = {b.name: 0.0, rb.name: 0.0, "second": 0.0}, 0.0, [], {}
    score = Score()
    decide_hours = (D.DECIDE_HOUR,) + ((second_check_hour,) if second_check_hour is not None else ())
    rain_hour, sun_today, water_until, used_days, second_h = 0.0, {}, {}, None, 0.0
    for n in range(int(days * 24 * 12)):
        when = world.when
        if crop and when.hour == 0 and when.minute == 0:
            today = when.date()
            calendar = (today - planted).days if planted is not None else 0
            grown_days, grown_gdd = truth[today] if truth is not None else (calendar, None)
            for sb in (b, rb):
                grow(sb, grows, grown_days if grown_days is not None else calendar,
                     hardpan_mm=hardpan_mm, gdd=grown_gdd, farm=farm)
            if b2 is not None and today < second[1]:
                b2.crop_coefficient = 0.0              # bare, waiting to be sown
            elif b2 is not None:
                d2, g2 = (truth2.get(today, (0.0, 0.0)) if truth2 is not None
                          else ((today - second[1]).days, None))
                grow(b2, second[0], d2 if d2 is not None else (today - second[1]).days, gdd=g2,
                     farm=farm)
        if when.minute == 0:
            if when.hour == 0 or not sun_today:
                sun_today = hourly_sun(when.date())
                sun_today.update(hourly_sun(when.date() - _dt.timedelta(days=1)))
            if n:
                write(rain, when, round(rain_hour, 3))
                write(sunshine, when, round(sun_today.get(when, 0.0), 1))
            rain_hour = 0.0
        day_n = (when - start).days
        for ds, sb, silent, bias in ((probe_ds, b, outage and outage[0] <= day_n <= outage[1], 0.0),
                                     (ref_ds, rb, False, reference_bias)):
            if ds is not None and when.minute == 0 and not silent:
                read = sb.theta + bias + offset[ds.id] + noise[ds.id].gauss(0.0, probe_noise)
                state.add(Observation(uuid7(), ds.id, when, 60.0, when, round(read, 3),
                                      ClockQuality.GPS, node="!soil", boot=1, seq=n & 0xFFFF,
                                      calibration=cal))
        if when.hour in decide_hours and when.minute == 0:
            given = station if (probe_ds is None or fallback) else None
            for event in advisor.advise(state, beds, when, forecast=fc.id, station=given):
                d = event.payload
                if not d["topic"].startswith("advice/"):
                    continue
                sb, its_valve, recorded = sim_bed[d["subject"]]
                if sb is b:
                    advice[d["rule"]] = advice.get(d["rule"], 0) + 1
                    used_days = ((d["context"].get("crop_days"), d["context"].get("crop_gdd")),
                                 truth[when.date()] if truth is not None
                                 else (when.date() - planted).days if crop and planted else None)
                if d["rule"] in ("soil-weather-water-now", "soil-water-now"):
                    begin = when + HOUR
                    until = begin + _dt.timedelta(hours=d["context"]["refill_mm"] / rate_mm_per_h)
                    water_until[sb.name] = until
                    if sb is b and b2 is not None:
                        water_until[b2.name] = until
                    if recorded:
                        write(its_valve, begin, True)
                        write(its_valve, until, False)
        for name, until in list(water_until.items()):
            if when.hour < D.WATER_HOUR:
                continue
            step_end = when + ph.STEP
            minutes = max(0.0, (min(step_end, until) - when) / _dt.timedelta(minutes=1))
            if minutes > 0:
                mm = rate_mm_per_h * minutes / 60.0
                world.irrigate(name, mm)
                applied[name] += mm
            if step_end >= until:
                del water_until[name]
        tick = world.step()
        if when.minute == 0:
            write(air, when, tick.weather.air_temp_c)
            write(rh, when, tick.weather.relative_humidity)
        rain_hour += tick.weather.rain_mm
        s = tick.soil_stress[b.name]
        stress.append(s)
        if s >= 0.5:
            stressed_h += 1.0 / 12.0
        score.tick(b)
        if b2 is not None and when.date() >= second[1] and tick.soil_stress[b2.name] >= 0.5:
            second_h += 1.0 / 12.0
    return {"policy": "weather", "applied_mm": applied[b.name], "drained_mm": b.drained_mm,
            "farm": asdict(farm),
            **score.result(b, b2),
            "second_stressed_h": second_h if b2 is not None else None,
            "mean_stress": statistics.mean(stress), "stressed_h": stressed_h,
            "advice": advice, "reference_mm": applied[rb.name] if reference else None,
            "crop_days": used_days}


# ------------------------------------------------------------------ process

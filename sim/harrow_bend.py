#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Harrow Bend: the canonical farm (docs/VIRTUAL_FARM.md step 5).

One named, persistent, deterministic fictional farm, anchored on the prime meridian
so nothing can be mistaken for a real place. Not a per-demo throwaway: the thing the
completeness matrix is enforced against, so that a clause of the spec with nothing
exercising it fails the build rather than going quietly untested.

    python3 harrow_bend.py                 # assemble a season and report
    python3 harrow_bend.py --days 30
    python3 harrow_bend.py --link meshtastic

The farm, chosen so each acceptance-test app has a home and each hard clause has
something that exercises it:

| feature        | sensing                              | what it is there for          |
| -------------- | ------------------------------------ | ----------------------------- |
| bed1..bed6     | soil moisture at two depths          | the irrigation controller     |
| paddock        | two trough levels                    | the livestock water monitor   |
| research plot  | two probes on one feature            | the research logger, and the  |
|                |                                      | only way cross-check works    |
| hoop house     | air temperature and humidity         | the good-connectivity contrast|
| every node     | battery and signal                   | §4.3 device health as series  |

Five nodes carry them, deliberately unlike each other: different clock sources so all
five `clock_quality` values appear, opposite drain policies so §5.3's two correct
answers both appear, and one node far enough out that its link is bad.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import random
import sys
from dataclasses import dataclass, field

import faults as F
import harness
import link as lk
import node as nd
import physics as ph

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sdk"))
import gateway as G  # noqa: E402
import vocab as V  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
from ids import uuid7  # noqa: E402
from model import (Assertor, Calibration, ClockQuality,  # noqa: E402
                   Datastream, DatastreamKind, Device, DeviceKind,
                   Installation, Label, MaintenanceAction,
                   MaintenanceEvent, Observation, Threshold, Usable)
from registry import NodeBinding, Registry  # noqa: E402

START = _dt.datetime(2026, 6, 1, 0, 0, tzinfo=ph.UTC)

#: Null-island anchor, following the constellation's convention: longitude zero, so
#: nothing here can be mistaken for a real location.
ANCHOR = {"type": "Point", "coordinates": [0.0, 0.0]}

#: Real, resolvable vocabulary terms — see sdk/vocab.py, which records which
#: vocabulary each came from and why the one local term had to be local.
SOIL = V.SOIL_WATER
LEVEL = V.VESSEL_FILL_FRACTION
AIR_TEMP = V.AIR_TEMPERATURE
HUMIDITY = V.RELATIVE_HUMIDITY
BATTERY = V.BATTERY_VOLTAGE
RSSI = V.RSSI
SOIL_TEMP = V.SOIL_TEMPERATURE

#: Hardware a person would recognise, per measurand. Fictional, like the farm.
_MODELS = {
    V.SOIL_WATER: "TEROS-12",
    V.SOIL_TEMPERATURE: "TEROS-12",
    V.VESSEL_FILL_FRACTION: "float-level TL-1",
    V.AIR_TEMPERATURE: "SHT-35",
    V.RELATIVE_HUMIDITY: "SHT-35",
    V.BATTERY_VOLTAGE: "onboard ADC",
    V.RSSI: "onboard radio",
}

#: Install depth from the series' suffix (§4.1), positive downwards. A series with
#: no depth in its name is not in the ground, and gets None rather than a guess.
_DEPTHS = {"shallow": 0.20, "deep": 0.40}

#: Soil thresholds, each derived from something physical rather than picked.
#:
#: Spikes and falls are judged by shape, not by `max_rate_per_s` (Q23, decided
#: 2026-10-08). A rate allowance grows with the gap: the first value tried here,
#: 0.0004/s, permitted a jump of 0.36 per 15-minute interval, and the later 0.00015/s
#: still allows 0.54 at hourly sampling, where ISMN's record showed it catching
#: nothing. What tells a glitch from irrigation is that it comes back (`spike_step`);
#: what tells a fault from drainage is that soil empties slowly (`max_fall_per_s`,
#: 0.05 per hour, from 27.7 million healthy falls on SCAN). Rises get no cap: an
#: irrigation event and a fault rise alike.
#:
#: `flat_seconds` is 18 h because a probe at three decimals genuinely repeats for
#: about 8 h overnight when evapotranspiration is near zero (§4.2).
SOIL_THRESHOLDS = {"min": 0.02, "max": 0.46, "flat_seconds": 18 * 3600,
                   "flat_n": 4, "spike_step": 0.05, "max_fall_per_s": 0.05 / 3600,
                   "cross_tolerance": 0.04}
#: A float-regulated level is constant by design, so flatline is switched off and
#: range is what catches a stuck float (§4.2).
LEVEL_THRESHOLDS = {"min": 0.10, "max": 1.0, "flat_n": None,
                    "flat_seconds": None}
AIR_THRESHOLDS = {"min": -30.0, "max": 60.0, "flat_seconds": 6 * 3600,
                  "flat_n": 12}
BATTERY_THRESHOLDS = {"min": 3.2, "max": 4.3, "flat_n": None,
                      "flat_seconds": None}
#: Soil temperature. The flatline window is long because a deep probe's daily swing
#: at 0.1 C resolution can hold one value for many hours, and that is a correct
#: reading — the same quantisation-dwell lesson as moisture (§4.2).
SOIL_TEMP_THRESHOLDS = {"min": -15.0, "max": 55.0, "flat_seconds": 36 * 3600,
                        "flat_n": 6, "max_rate_per_s": 0.0012}


def _moisture(truth, siting) -> float:
    """What a moisture probe reads where it physically is.

    The bed's water content, plus a little more with depth — deeper soil holds more,
    and this reproduces the old fixed `+0.03` at 40 cm exactly while staying
    continuous for a probe moved to any other depth.
    """
    return truth.soil[siting.bed] + 0.15 * (siting.depth_m - 0.20)


@dataclass
class Spike(F.Fault):
    """A brief excursion to an impossible value, then back.

    §4.2's rate-of-change check is the only one that can see this, and nothing else
    on the farm produces it — a drift is too slow and a stuck probe does not move.
    """

    kind: str = "spike"
    until_s: float = 0.0
    value: float = 0.0

    def apply(self, value, at_s):
        if self.begins_at_s <= at_s < self.until_s:
            return self.value
        return value

    def describe(self) -> str:
        return (f"spikes to {self.value:g} for "
                f"{(self.until_s - self.begins_at_s) / 60:.0f} min")


@dataclass
class Siting:
    """Where a probe **physically** is — deliberately separate from where the log
    says it is.

    The `Installation` record is a claim a person made. This is the ground truth the
    simulator reads from, and the gap between the two is exactly what a siting check
    exists to find. Shared by every series a device feeds, so a TEROS-12 that is
    moved takes its moisture *and* its temperature readings with it.
    """

    bed: str
    depth_m: float


@dataclass
class Series:
    """One point: its raw and derived datastreams, its calibration, its sensor."""

    name: str
    raw: Datastream
    derived: Datastream
    calibration: Calibration
    threshold: Threshold
    sensor: F.Sensor
    channel: int
    device: object = None            # §4.1 Device
    installation: object = None      # §4.1 Installation, the open one
    siting: Siting | None = None     # where it physically is, which may disagree


@dataclass
class Farm:
    """Harrow Bend, assembled."""

    world: ph.World
    log: object
    state: P.State
    registry: Registry
    gateway: object
    nodes: dict = field(default_factory=dict)
    links: dict = field(default_factory=dict)
    series: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    site: object = None
    #: §4.1 devices for the nodes themselves, by label — what battery, signal and a
    #: GNSS fix are properties *of* (§4.3).
    node_devices: dict = field(default_factory=dict)
    #: Where each node physically stands, which may disagree with its record.
    node_sitings: dict = field(default_factory=dict)

    def series_for(self, name: str) -> Series:
        return self.series[name]


#: Where each feature sits, as GeoJSON, in metres-ish degrees off null island.
#:
#: These points are what the SensorThings view draws, handed to it as a side table the
#: way names once were. A field's *boundary* is a record — `records.Land`, in the farm's
#: own log, where Q14 protects it from a silent overwrite. What never belongs in a
#: public repository is a real farm's log: its boundaries, wells and contacts are the
#: farmer's, which is why docs/VIRTUAL_FARM.md keeps them in a gitignored `.site/`.
#:
#: Harrow Bend is fictional and anchored on the prime meridian, so its geometry *can*
#: live in the repository. That is the privilege of a farm that does not exist.
#:
#: The offsets exist because a GIS client loaded this farm as six layers stacked on one
#: point until they did. Roughly 11 m per 0.0001 degree, so the beds sit in a row about
#: 50 m long, which is a plausible market garden.
_LAYOUT = {
    "bed1": (0.0000, 0.0000), "bed2": (0.0001, 0.0000),
    "bed3": (0.0002, 0.0000), "bed4": (0.0003, 0.0000),
    "bed5": (0.0004, 0.0000), "bed6": (0.0005, 0.0000),
    "plot": (0.0002, 0.0003),
    "paddock": (-0.0006, -0.0004),
    "hoop": (0.0006, 0.0002),
    "bed4_sample": (0.0003, -0.0001),
}


def _geometry(name: str) -> dict:
    """A point for a named feature, or null island if the farm grew one we forgot.

    Returning the anchor rather than `None` for an unknown feature is deliberate: a
    missing geometry makes a GIS layer silently drop the row, and a row at 0,0 is
    visibly wrong instead. Being obviously wrong beats being quietly absent.
    """
    lon, lat = _LAYOUT.get(name, (0.0, 0.0))
    return {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}


def _boundary(name: str, half: float = 0.00004) -> dict:
    """A bed's edges: a square about 9 m across, centred on its point."""
    lon, lat = _LAYOUT.get(name, (0.0, 0.0))
    ring = [[lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half],
            [lon - half, lat + half], [lon - half, lat - half]]
    return {"type": "Polygon", "coordinates": [[[round(x, 7), round(y, 7)] for x, y in ring]]}


#: Spanish names for the features, because layer 4 must be bilingual (§11) and a
#: label registry that has only ever held English has never exercised its fallback.
_SPANISH = {
    "bed1": "cama 1", "bed2": "cama 2", "bed3": "cama 3", "bed4": "cama 4",
    "bed5": "cama 5", "bed6": "cama 6", "paddock": "potrero",
    "plot": "parcela de ensayo", "hoop": "invernadero",
    "bed4_sample": "muestra de la cama 4",
}


#: The series a Spanish-speaking farmer is told about by name: the troughs, in the
#: livestock water monitor's alerts.
_SPANISH_SERIES = {"trough_north": "bebedero norte", "trough_south": "bebedero sur"}


def _name(farm, entity, name: str, *, description: str | None = None,
          language: str = "en") -> None:
    label = Label(id=uuid7(), entity=entity, name=name, language=language,
                  description=description, set_at=farm.world.start)
    farm.log.append_record(label)
    farm.state.add(label)


def name_everything(farm) -> None:
    """Write a §1 `Label` for every entity the farm has, into the log.

    These were a simulator side table until the label registry existed; now they are
    ordinary records, exported, replayed and renameable like anything else.

    Raw and derived series are named distinctly on purpose. They are the pair whose
    confusion produced a 99.8% false-alarm rate (§4.2), so a client that shows them
    side by side should not be able to mistake one for the other either. A probe's
    device is named once even though it feeds four datastreams — moisture and
    temperature, raw and derived — because it is one thing in the ground.
    """
    named = set()
    for label, device in farm.node_devices.items():
        _name(farm, device.id, f"{label} node",
              description=f"the field node at {farm.node_sitings[label].feature}")
        named.add(device.id)
    for name, series in farm.series.items():
        _name(farm, series.raw.id, f"{name} (raw)",
              description=f"{name}, as the node reported it, before calibration")
        _name(farm, series.derived.id, name,
              description=f"{name}, calibrated to physical units")
        if name in _SPANISH_SERIES:
            _name(farm, series.derived.id, _SPANISH_SERIES[name], language="es")
        device = series.raw.sensor
        if device not in named:
            probe = name.removesuffix("_temp")
            _name(farm, device, f"{probe} probe" if series.siting else f"{name} sensor",
                  description=f"the sensor behind {probe}")
            named.add(device)
    for name, feature in farm.features.items():
        if feature.get("id") is not None:
            _name(farm, feature["id"], name, description=f"{name} at Harrow Bend")
            if name in _SPANISH:
                _name(farm, feature["id"], _SPANISH[name], language="es",
                      description=f"{_SPANISH[name]} en Harrow Bend")
        if feature.get("thing") is not None:
            _name(farm, feature["thing"], f"{name} station",
                  description=f"the monitoring station at {name}")
            if name in _SPANISH:
                _name(farm, feature["thing"], f"estación {_SPANISH[name]}",
                      language="es")


def rename(farm, entity, name: str, *, language: str = "en", by=None,
           at=None) -> Label:
    """Rename an entity (§1): a new label superseding the current one, never an edit."""
    current = farm.state.label_for(entity, language, fallback=())
    label = Label(id=uuid7(), entity=entity, name=name, language=language,
                  description=current.description if current else None,
                  set_at=at or farm.world.when, set_by=by,
                  supersedes=current.id if current else None)
    farm.log.append_record(label)
    farm.state.add(label)
    return label


def geometries(farm) -> dict:
    """GeoJSON points for every feature, for the SensorThings view and the GeoJSON
    export. A field's boundary is a `records.Land` in the farm's own log; these points
    are the side table the view is handed. Harrow Bend is fictional and sits on the
    prime meridian, so its geometry can live in the repository.
    """
    return {feature["id"]: _geometry(name)
            for name, feature in farm.features.items()
            if feature.get("id") is not None}



def _series(farm, *, name, feature, prop, unit, scale, decimals, thresholds,
            interval, latency, read, channel, sensor_id=None, faults=(),
            same_device_as: str | None = None, device=None):
    """One point. With `same_device_as`, a second datastream on an existing device —
    a TEROS-12 reports moisture and temperature from one body, so they share one
    `Device`, one `Installation` and one physical siting."""
    sibling = farm.series[same_device_as] if same_device_as else None
    sensor_id = (sibling.device.id if sibling else
                 device.id if device is not None else (sensor_id or uuid7()))
    thing = farm.features[feature]["thing"]
    # Q21: a node sending scaled integers sends numbers, not cm3/cm3; the scale is the
    # calibration's. A series sent in its own unit (scale 1) keeps that unit.
    raw = Datastream(id=uuid7(), thing=thing, sensor=sensor_id,
                     observed_property=prop, feature=farm.features[feature]["id"],
                     kind=DatastreamKind.RAW, unit=V.RAW_COUNT if scale != 1.0 else unit,
                     expected_interval=interval, max_latency=latency)
    derived = Datastream(id=uuid7(), thing=thing, sensor=sensor_id,
                         observed_property=prop,
                         feature=farm.features[feature]["id"],
                         kind=DatastreamKind.DERIVED, derived_from=raw.id,
                         unit=unit, expected_interval=interval,
                         max_latency=latency, thresholds=thresholds)
    cal = Calibration(id=uuid7(), sensor=sensor_id, datastream=raw.id,
                      method="linear",
                      valid_from=_dt.datetime(2026, 1, 1, tzinfo=ph.UTC),
                      coefficients={"a": 1.0 / scale, "b": 0.0,
                                    "decimals": decimals})
    th = Threshold(id=uuid7(), datastream=derived.id, values=thresholds)
    for record in (raw, derived, cal, th):
        farm.log.append_record(record)
        farm.state.add(record)
    # §4.1. The device record behind `Datastream.sensor`, which was a bare UUID with
    # nothing behind it until §4.1 was built — so a probe could be moved between beds
    # with nothing recording that it had happened. Installed where its feature is, at
    # the depth its name claims, from the day the season starts.
    if sibling is not None:
        device, install, siting = sibling.device, sibling.installation, sibling.siting
    elif device is not None:
        # A datastream of an already-registered device — a node's own battery.
        install = farm.state.installation_of(device.id, farm.world.start)
        siting = None
    else:
        device = Device(id=sensor_id, kind=DeviceKind.SENSOR, site=farm.site,
                        model=_MODELS.get(prop, "generic probe"),
                        serial=f"SN-{sensor_id.hex[:8]}",
                        manufacturer="Harrow Bend Instruments",
                        firmware="1.4.2", driver="fieldmesh.sim",
                        driver_version="0",
                        capabilities={"dedup_volatile": False,
                                      "confirms_delivery": True})
        depth = _DEPTHS.get(name.rsplit("_", 1)[-1])
        install = Installation(id=uuid7(), device=sensor_id,
                               feature=farm.features[feature]["id"],
                               installed_at=farm.world.start, depth_m=depth)
        siting = Siting(bed=feature, depth_m=depth) if depth is not None else None
        for record in (device, install):
            farm.log.append_record(record)
            farm.state.add(record)

    series = Series(name=name, raw=raw, derived=derived, calibration=cal,
                    threshold=th, channel=channel, device=device,
                    installation=install, siting=siting,
                    sensor=F.Sensor(read, scale=scale, faults=list(faults),
                                    name=name))
    farm.series[name] = series
    return series


def build(*, seed: int = 1, start: _dt.datetime = START,
          link_profile=None, dr: int = 3) -> Farm:
    """Assemble the farm. Deterministic from `seed` and `start`."""
    link_profile = link_profile if link_profile is not None else lk.WIRED

    beds = [ph.SoilBed(name=f"bed{i + 1}", theta=theta)
            for i, theta in enumerate((0.38, 0.33, 0.29, 0.26, 0.21, 0.16))]
    beds.append(ph.SoilBed(name="plot", theta=0.30))
    troughs = [ph.Trough(name="trough_north"),
               ph.Trough(name="trough_south", capacity_l=250.0, level_l=235.0,
                         stock_count=14)]
    # The hoop house is a tunnel with its own physics — sun trapped by day, the soil's
    # heat given back by night, less of it on a clear cold night, the sides rolled up
    # when it passes 27 °C — rather than a constant six degrees over the outside air.
    world = ph.World(start=start, climate=ph.Climate(seed=seed), beds=beds,
                     troughs=troughs, tunnels=[ph.Tunnel(name="hoop")])
    # Drip timers, one per bed, each starting at its own hour and alternating days.
    # Ordinary for a market garden; and the reason a probe's moisture record says which
    # bed it is in — shared rain wets every bed together, but each bed's own timer wets
    # only that bed, at a time no other bed shares. The plot is left on rain alone.
    world.irrigation = [
        ph.IrrigationRule(bed=f"bed{k}", millimetres=10.0, start_hour=4.0 + 2 * (k - 1),
                          every_days=2, offset_days=(k - 1) % 2)
        for k in range(1, 7)]

    log = L.Log()
    state = P.State()
    registry = Registry()
    site = uuid7()
    farm = Farm(world=world, log=log, state=state, registry=registry,
                gateway=None, site=site)

    for name in ("bed1", "bed2", "bed3", "bed4", "bed5", "bed6",
                 "paddock", "plot", "hoop"):
        farm.features[name] = {"id": uuid7(), "thing": uuid7(), "name": name}

    # --- soil, two depths per bed -------------------------------------------
    # Each probe reads through its *physical* siting rather than a bed name fixed at
    # build time. The first version bound the bed into the reader, so `relocate`
    # wrote records saying a probe had moved to bed2 while the simulated probe went
    # on reading bed6 — the records moved and the probe did not, which is precisely
    # the disagreement a siting check exists to catch, introduced by the simulator.
    holder: dict = {}
    for index, bed in enumerate(("bed1", "bed2", "bed3", "bed4", "bed5", "bed6")):
        for depth, channel in (("shallow", 1), ("deep", 2)):
            name = f"{bed}_{depth}"
            series = _series(
                farm, name=name, feature=bed, prop=SOIL, unit="cm3/cm3",
                scale=1000.0, decimals=3, thresholds=SOIL_THRESHOLDS,
                interval=900.0, latency=3600.0, channel=channel + 2 * (index % 3),
                read=(lambda n: lambda t: _moisture(t, holder[n]))(name))
            holder[name] = series.siting
            # The same TEROS-12 body reports soil temperature (§4.1: one device,
            # two datastreams). Hourly, because soil heat moves slowly and the daily
            # wave needs no finer sampling to be fitted — a quarter of the airtime
            # that matching the moisture interval would cost.
            _series(farm, name=f"{name}_temp", feature=bed, prop=SOIL_TEMP,
                    unit="Cel", scale=10.0, decimals=1,
                    thresholds=SOIL_TEMP_THRESHOLDS, interval=3600.0,
                    latency=3600.0, channel=20 + channel + 2 * (index % 3),
                    same_device_as=name,
                    read=(lambda n: lambda t: t.soil_temp_at(
                        holder[n].bed, holder[n].depth_m))(name))

    # --- troughs: the urgent series, tight latency ---------------------------
    for channel, trough in enumerate(("trough_north", "trough_south"), start=1):
        _series(farm, name=trough, feature="paddock", prop=LEVEL, unit="1",
                scale=1000.0, decimals=3, thresholds=LEVEL_THRESHOLDS,
                interval=300.0, latency=300.0, channel=channel,
                read=(lambda name: lambda t: t.trough_fraction[name])(trough))

    # --- research plot: two probes on one feature, same measurand -----------
    for channel, probe in enumerate(("plot_probe_a", "plot_probe_b"), start=1):
        _series(farm, name=probe, feature="plot", prop=SOIL, unit="cm3/cm3",
                scale=1000.0, decimals=3, thresholds=SOIL_THRESHOLDS,
                interval=900.0, latency=3600.0, channel=channel,
                read=lambda t: t.soil["plot"])

    # --- hoop house: the good-connectivity contrast -------------------------
    _series(farm, name="hoop_temp", feature="hoop", prop=AIR_TEMP, unit="Cel",
            scale=10.0, decimals=1, thresholds=AIR_THRESHOLDS, interval=300.0,
            latency=600.0, channel=1,
            read=lambda t: t.tunnel_temp["hoop"])
    _series(farm, name="hoop_humidity", feature="hoop", prop=HUMIDITY, unit="%",
            scale=10.0, decimals=1,
            thresholds={"min": 0.0, "max": 100.0, "flat_seconds": 6 * 3600,
                        "flat_n": 12},
            interval=300.0, latency=600.0, channel=2,
            read=lambda t: min(99.0, t.weather.relative_humidity + 8.0))

    # --- nodes, deliberately unlike each other ------------------------------
    plan = [
        ("beds_a", 0x4F2A1701, ClockQuality.RTC_UNSYNCED, 12.0, nd.CHRONOLOGICAL,
         ["bed1_shallow", "bed1_deep", "bed2_shallow", "bed2_deep",
          "bed3_shallow", "bed3_deep",
          "bed1_shallow_temp", "bed1_deep_temp", "bed2_shallow_temp",
          "bed2_deep_temp", "bed3_shallow_temp", "bed3_deep_temp"],
         lk.MESHTASTIC),
        ("beds_b", 0x4F2A1702, ClockQuality.RTC_SYNCED, 2.0, nd.CHRONOLOGICAL,
         ["bed4_shallow", "bed4_deep", "bed5_shallow", "bed5_deep",
          "bed6_shallow", "bed6_deep",
          "bed4_shallow_temp", "bed4_deep_temp", "bed5_shallow_temp",
          "bed5_deep_temp", "bed6_shallow_temp", "bed6_deep_temp"],
         lk.MESHTASTIC),
        ("paddock", 0x4F2A1703, ClockQuality.GPS, 0.5, nd.FRESH_FIRST,
         ["trough_north", "trough_south"], lk.LORAWAN_CONFIRMED),
        ("plot", 0x4F2A1704, ClockQuality.NETWORK, 1.5, nd.CHRONOLOGICAL,
         ["plot_probe_a", "plot_probe_b"], lk.WIRED),
        # No clock at all, and an honest uncertainty: the sample interval plus
        # transmit latency, as §2 requires.
        ("hoop", 0x4F2A1705, ClockQuality.NONE, 900.0, nd.CHRONOLOGICAL,
         ["hoop_temp", "hoop_humidity"], lk.WIRED),
    ]

    for label, node_id, clock, uncertainty, drain, names, profile in plan:
        registry.register_node(NodeBinding(
            node=node_id, site=site, clock_quality=clock,
            uncertainty_s=uncertainty, firmware="0.3.1", driver="sim",
            driver_version="0.1"))
        channels = []
        used = set()
        for name in names:
            series = farm.series[name]
            channel = series.channel
            while channel in used:
                channel += 1
            used.add(channel)
            series.channel = channel
            registry.bind_point(node_id, channel, series.raw.id)
            channels.append(nd.Channel(channel, series.raw.expected_interval,
                                       series.raw.max_latency, series.sensor,
                                       name=name))
        # §4.1/§4.3: the node is a device in its own right. Battery and signal are
        # properties *of the node*, and used to be modelled as two separate "sensor"
        # devices per node — a node's battery named as though it were a probe in the
        # ground.
        feature = (names[0].split("_")[0] if names[0].startswith("bed") else
                   "paddock" if label == "paddock" else
                   "plot" if label == "plot" else "hoop")
        node_device = Device(
            id=uuid7(), kind=DeviceKind.NODE, site=site,
            model="field node", serial=f"{node_id:#010x}",
            manufacturer="Harrow Bend Instruments", firmware="0.3.1",
            driver="sim", driver_version="0.1",
            capabilities={"dedup_volatile": False,
                          "confirms_delivery": profile is lk.LORAWAN_CONFIRMED})
        node_install = Installation(id=uuid7(), device=node_device.id,
                                    feature=farm.features[feature]["id"],
                                    installed_at=farm.world.start)
        for record in (node_device, node_install):
            farm.log.append_record(record)
            farm.state.add(record)
        farm.node_devices[label] = node_device
        farm.node_sitings[label] = NodeSiting(feature=feature)

        node_series = [
            (BATTERY, "V", 100.0, 2, BATTERY_THRESHOLDS,
             _battery_reader(label), "battery"),
            (RSSI, "dB[mW]", 1.0, 0,
             {"min": -140.0, "max": 0.0, "flat_n": None,
              "flat_seconds": None}, _rssi_reader(label), "rssi")]
        if clock is ClockQuality.GPS:
            # The fix a GPS-timed node already computes, no longer thrown away.
            for prop, axis in ((V.LATITUDE, 1), (V.LONGITUDE, 0)):
                node_series.append(
                    (prop, "deg", 1e6, 6, GPS_THRESHOLDS,
                     _gps_reader(farm, label, axis, seed=node_id),
                     "lat" if axis == 1 else "lon"))
        for prop, unit, scale, decimals, thresholds, reader, label_suffix in node_series:
            name = f"{label}_{label_suffix}"
            channel = max(used) + 1
            used.add(channel)
            series = _series(farm, name=name, feature=feature,
                             prop=prop, unit=unit, scale=scale,
                             decimals=decimals, thresholds=thresholds,
                             interval=3600.0, latency=21600.0, channel=channel,
                             read=reader, device=node_device)
            registry.bind_point(node_id, channel, series.raw.id)
            channels.append(nd.Channel(channel, 3600.0, 21600.0, series.sensor,
                                       name=name))

        node = nd.Node(node_id, channels, dr=dr, ack_timeout_s=1800.0,
                       policy=nd.BufferPolicy(buffer_max=800, drain_order=drain))
        farm.nodes[label] = node
        farm.links[label] = lk.Link(profile, seed=seed + node_id % 97)

    farm.gateway = G.Gateway(registry, log, state)
    name_everything(farm)
    return farm


#: Consumer GNSS, averaged over a fix: about 2.5 m one-sigma horizontally.
GPS_SIGMA_M = 2.5
METRES_PER_DEGREE = 111_320.0
GPS_THRESHOLDS = {"flat_n": None, "flat_seconds": None}


@dataclass
class NodeSiting:
    """Where a node physically stands: a feature, and an offset from its centre."""

    feature: str
    east_m: float = 0.0
    north_m: float = 0.0


def _gps_reader(farm, label: str, axis: int, *, seed: int):
    """A GNSS fix on one axis (0 longitude, 1 latitude), with realistic scatter.

    Seeded per node and axis, so a season is deterministic. Reads the node's
    *physical* siting, so a node moved without a record reports where it really is —
    which is the disagreement the position check exists for.
    """
    rng = random.Random(seed * 2 + axis)

    def read(truth):
        siting = farm.node_sitings[label]
        lon, lat = _LAYOUT.get(siting.feature, (0.0, 0.0))
        offset = siting.north_m if axis == 1 else siting.east_m
        base = (lat if axis == 1 else lon) + offset / METRES_PER_DEGREE
        return base + rng.gauss(0.0, GPS_SIGMA_M) / METRES_PER_DEGREE
    return read


def displace_node(farm: Farm, label: str, *, feature: str | None = None,
                  east_m: float = 0.0, north_m: float = 0.0) -> NodeSiting:
    """Move a node **without recording it** — the lateral move a temperature check
    cannot see, and a GNSS fix can."""
    siting = farm.node_sitings[label]
    if feature is not None:
        siting.feature = feature
    siting.east_m, siting.north_m = east_m, north_m
    return siting


def _battery_reader(label: str):
    """A battery that declines, and on the paddock node declines fast enough to
    matter — §4.3's point is that this is a datastream with a threshold, not a
    side-channel warning bolted on."""
    rate = 0.06 if label == "paddock" else 0.012      # volts per day
    def read(truth):
        days = (truth.when - START).total_seconds() / 86400.0
        return max(3.0, 4.15 - rate * days)
    return read


def _rssi_reader(label: str):
    marginal = -118.0 if label == "beds_a" else -92.0
    def read(truth):
        minute = truth.when.minute
        return marginal + (minute % 7) - 3
    return read


__all__ = ["build", "Farm", "Series", "START", "ANCHOR", "SOIL", "LEVEL",
           "AIR_TEMP", "HUMIDITY", "BATTERY", "RSSI"]


# --------------------------------------------------------------------- season

@dataclass
class SeasonReport:
    """What the season did, and which matrix rows it produced."""

    days: float = 0.0
    events: list = field(default_factory=list)
    frames: int = 0
    duplicates: int = 0
    note: dict = field(default_factory=dict)

    def record(self, when, what: str) -> None:
        self.events.append((when, what))


def recalibrate(farm: Farm, series_name: str, at: _dt.datetime, *,
                scale: float, decimals: int = 3) -> Calibration:
    """Recalibrate a sensor and re-derive its history (§3.2).

    Applied retroactively at the end of a season run, as a farmer recalibrating in
    June and re-deriving the spring would be. The originals keep the calibration
    that produced them — a superseded row stays a true statement about what the old
    coefficients computed, which is precisely what "recalibration never rewrites
    history" means, and why a superseded row's calibration need not cover its
    timestamp under today's calibration set.

    The old calibration gets an end, the new one takes over from `at`, and every
    derived observation from that point is recomputed as a *new* row carrying
    `supersedes`. The originals stay in the log forever, which is the clause that
    keeps the SensorThings promise alive past the first recalibration.
    """
    series = farm.series[series_name]
    old = series.calibration
    closed = Calibration(id=old.id, sensor=old.sensor, datastream=old.datastream,
                         method=old.method,
                         valid_from=old.valid_from, valid_to=at,
                         reference=old.reference, coefficients=old.coefficients,
                         performed_by=old.performed_by)
    fresh = Calibration(id=uuid7(), sensor=old.sensor, datastream=old.datastream,
                        method="linear",
                        valid_from=at,
                        coefficients={"a": 1.0 / scale, "b": 0.0,
                                      "decimals": decimals})
    for record in (closed, fresh):
        farm.log.append_record(record)
        farm.state.add(record)
    series.calibration = fresh

    # Both lookups go through the projection's indexes rather than scanning the log.
    # The version this replaces asked "has this row been superseded?" by scanning every
    # observation for every candidate row, which is quadratic in season length and was
    # the single largest cost in a simulated fortnight — 11 s of 34 s, 59 million UUID
    # comparisons, rebuilding a set `State` already maintains. A recalibration is
    # exactly when a season is longest, so this is the worst possible place for it.
    raw_by_time = {o.measured_at: o
                   for o in farm.state.observations_of(series.raw.id)}
    superseded = 0
    for old_obs in list(farm.state.observations_of(series.derived.id)):
        if old_obs.measured_at < at:
            continue
        if farm.state.is_superseded(old_obs.id):
            continue
        source = raw_by_time.get(old_obs.measured_at)
        if source is None:
            continue
        provenance = dict(old_obs.provenance)
        provenance["rederived_from_observation"] = str(source.id)
        replacement = Observation(
            id=uuid7(), datastream=series.derived.id,
            measured_at=old_obs.measured_at,
            measured_at_uncertainty=old_obs.measured_at_uncertainty,
            received_at=old_obs.received_at,
            result=P.apply_calibration(source.result, fresh),
            clock_quality=old_obs.clock_quality, node=old_obs.node,
            boot=old_obs.boot, seq=old_obs.seq, calibration=fresh.id,
            supersedes=old_obs.id, provenance=provenance)
        farm.log.append_record(replacement)
        farm.state.add(replacement)
        superseded += 1
    return fresh, superseded


def relocate(farm: Farm, series_name: str, *, to: str, at: _dt.datetime,
             depth_m: float | None = None, by=None):
    """Move a sensor to another feature, closing its old installation (§4.1).

    The two halves both matter. Appending the new installation is the easy part;
    **closing the old one** is what keeps "where was this probe in April" answerable,
    and forgetting it leaves two installations covering July, which `State.validate`
    reports as an overlap. A siting question with two answers is worse than one with
    none, because nothing looks wrong.

    Closing is a re-append of the same installation id with `removed_at` set — the
    same last-write-wins-by-id pattern recalibration uses for a closed calibration.
    """
    series = farm.series[series_name]
    old = series.installation
    closed = Installation(id=old.id, device=old.device, feature=old.feature,
                          installed_at=old.installed_at, removed_at=at,
                          depth_m=old.depth_m,
                          orientation_deg=old.orientation_deg,
                          installed_by=old.installed_by, note=old.note)
    fresh = Installation(id=uuid7(), device=old.device,
                         feature=farm.features[to]["id"], installed_at=at,
                         depth_m=depth_m if depth_m is not None else old.depth_m,
                         installed_by=by)
    moved = MaintenanceEvent(
        id=uuid7(), device=old.device, at=at, action=MaintenanceAction.MOVED,
        performed_by=by,
        note=f"{series_name} moved to {to}"
             + (f", depth {depth_m} m" if depth_m is not None else ""))
    for record in (closed, fresh, moved):
        farm.log.append_record(record)
        farm.state.add(record)
    # The probe physically moves too, and every datastream on the device with it.
    # Before this, only the records moved, and the simulated probe went on reading
    # its old bed — a logged move whose readings said otherwise.
    for other in _series_of_device(farm, old.device):
        other.installation = fresh
    if series.siting is not None:
        series.siting.bed = to
        if depth_m is not None:
            series.siting.depth_m = depth_m
    return fresh


def displace(farm: Farm, series_name: str, *, depth_m: float | None = None,
             bed: str | None = None) -> Siting:
    """Move a probe **without recording it** — the fault a siting check exists for.

    Frost heave, a cultivator catching the cable, someone pulling a probe to look at
    it and pushing it back in shallower. Nothing is appended to the log: the
    `Installation` still says where the probe was put, and only the physics knows
    where it is now. Ground truth for the drill is the disagreement between the two.
    """
    siting = farm.series[series_name].siting
    if siting is None:
        raise ValueError(f"{series_name} has no physical siting to disturb")
    if depth_m is not None:
        siting.depth_m = depth_m
    if bed is not None:
        siting.bed = bed
    return siting


def _series_of_device(farm: Farm, device_id):
    return [s for s in farm.series.values()
            if s.device is not None and s.device.id == device_id]


def service(farm: Farm, series_name: str, *, at: _dt.datetime,
            action: MaintenanceAction, by=None, note: str | None = None):
    """Log a maintenance action against a series' device (§4.1)."""
    series = farm.series[series_name]
    event = MaintenanceEvent(id=uuid7(), device=series.device.id, at=at,
                             action=action, performed_by=by, note=note)
    farm.log.append_record(event)
    farm.state.add(event)
    return event


def retune(farm: Farm, series_name: str, **values) -> Threshold:
    """Retune a threshold and re-assess under it (§3.3).

    The old assertions keep the old version, so a false alarm stays traceable to
    the threshold that caused it.
    """
    import checks as C
    series = farm.series[series_name]
    merged = dict(series.threshold.values)
    merged.update(values)
    fresh = Threshold(id=uuid7(), datastream=series.derived.id, values=merged,
                      supersedes=series.threshold.id)
    farm.log.append_record(fresh)
    farm.state.add(fresh)
    series.threshold = fresh
    produced = C.assess_series(farm.state, series.derived.id, threshold=fresh,
                               reassess=True)
    for assertion in produced:
        farm.log.append_record(assertion)
        farm.state.add(assertion)
    return fresh, len(produced)


def override(farm: Farm, series_name: str, *, by, note: str):
    """A person disagreeing with the machine (§3.3). The original stays visible."""
    series = farm.series[series_name]
    machine = None
    for obs in farm.state.observations_of(series.derived.id):
        found = farm.state.live_assertion_for(obs.id)
        if (found is not None and found.flags
                and found.assertor is Assertor.FOUNDATION):
            machine = found
            break
    if machine is None:
        return None
    human = type(machine)(
        id=uuid7(), observation=machine.observation, flags=machine.flags,
        usable=Usable.GOOD, check="manual-review", check_version="1",
        threshold_version=machine.threshold_version,
        asserted_at=machine.asserted_at + _dt.timedelta(hours=2),
        assertor=Assertor.PERSON, assertor_id=by, note=note,
        evidence={"reviewed": str(machine.id)})
    farm.log.append_record(human)
    farm.state.add(human)
    return human


def handheld(farm: Farm, series_name: str, *, at, value, sample_feature):
    """A handheld meter reading, overriding its datastream's feature (§3.1).

    The only case where a feature belongs on the observation: the datastream's
    feature is the bed, and this reading is of a sample taken from it.
    """
    series = farm.series[series_name]
    obs = Observation(
        id=uuid7(), datastream=series.derived.id, feature=sample_feature,
        measured_at=at, measured_at_uncertainty=60.0, received_at=at,
        result=value, clock_quality=ClockQuality.NETWORK,
        calibration=series.calibration.id,
        provenance={"driver": "handheld", "driver_version": "1.0",
                    "operator": "walked sample"})
    farm.log.append_record(obs)
    farm.state.add(obs)
    return obs


def season(farm: Farm, *, days: float = 21.0, events: bool = True,
           seed: int = 1) -> SeasonReport:
    """Run the farm, injecting the events the completeness matrix asks for."""
    report = SeasonReport(days=days)
    start = farm.world.start
    day = _dt.timedelta(days=1)

    if events:
        # A three-day outage on the far bed node (§5.3), and a stuck float on the
        # south trough from day 9 (§4.2 range).
        farm.links["beds_a"].outage((start + 5 * day).timestamp(),
                                    (start + 8 * day).timestamp())
        report.record(start + 5 * day, "beds_a radio out for three days")
        # Drift on one research probe: invisible to itself, visible to its peer.
        farm.series["plot_probe_a"].sensor.inject(
            F.Drifting(begins_at_s=(start + 4 * day).timestamp(), per_day=0.05))
        report.record(start + 4 * day, "plot_probe_a begins drifting 0.05/day")
        # A brief spike on bed5: a jump no real process could make, which is what
        # §4.2's rate-of-change check exists for and nothing else here produces.
        farm.series["bed5_deep"].sensor.inject(
            Spike(begins_at_s=(start + 3 * day).timestamp(),
                  until_s=(start + 3 * day + _dt.timedelta(minutes=30)).timestamp(),
                  value=0.45))
        report.record(start + 3 * day, "bed5_deep spikes for half an hour")

    segments = [(0.0, min(days, 9.0))]
    if days > 9.0:
        segments.append((9.0, days))

    for index, (from_day, to_day) in enumerate(segments):
        if events and index == 1:
            farm.world.troughs["trough_south"].float_stuck_shut = True
            report.record(start + 9 * day, "trough_south float sticks shut")
        for label, node in farm.nodes.items():
            run = harness.run(world=farm.world, node=node, gateway=farm.gateway,
                              link=farm.links[label], days=0.0)
            del run
        _run_segment(farm, report, to_day - from_day)
        if events and index == 0 and days > 9.0:
            # A reboot mid-season: seq resets and nothing is deduplicated away (§1).
            lost = farm.nodes["beds_b"].reboot()
            report.record(farm.world.when, f"beds_b reboots, {lost} buffered lost")

    if events:
        mid = start + _dt.timedelta(days=max(1.0, min(days * 0.55, 12.0)))
        fresh, superseded = recalibrate(farm, "bed3_shallow", mid, scale=1020.0)
        report.record(mid, f"bed3_shallow recalibrated, {superseded} rows superseded")
        _, reassessed = retune(farm, "bed1_shallow", flat_seconds=30 * 3600)
        report.record(mid, f"bed1_shallow threshold retuned, {reassessed} reassessed")
        human = override(farm, "trough_south", by=uuid7(),
                         note="trough was drained for cleaning")
        if human is not None:
            report.record(mid, "a person overrode a machine verdict on trough_south")
        sample = uuid7()
        farm.features["bed4_sample"] = {"id": sample, "thing": None,
                                        "name": "bed4 walked sample"}
        held = handheld(farm, "bed4_shallow", at=mid, value=0.244,
                        sample_feature=sample)
        report.record(mid, "a handheld reading overrode its datastream's feature")
        # §7.3: a correction is a compensating event. The original stays readable.
        target = next((e for e in reversed(farm.log.events)
                       if e.kind == "observation"
                       and e.payload.get("id") == str(held.id)), None)
        if target is not None:
            farm.log.correct(target.id,
                             "handheld reading was logged against the wrong bed",
                             replacement=handheld(farm, "bed5_shallow", at=mid,
                                                  value=0.244,
                                                  sample_feature=sample))
            report.record(mid, "a correction appended as a compensating event")

        # §4.1: a probe lifted out of bed6 and reinstalled deeper in bed2, and a
        # silted trough sensor cleaned. The move is the one event that makes the
        # siting history non-trivial — before it, every installation was open and
        # nothing exercised closing one.
        hands = uuid7()
        relocate(farm, "bed6_shallow", to="bed2", at=mid, depth_m=0.30, by=hands)
        report.record(mid, "bed6_shallow moved to bed2 and reinstalled at 0.30 m")
        service(farm, "trough_south", at=mid, action=MaintenanceAction.CLEANED,
                by=hands, note="silt on the float")
        report.record(mid, "trough_south cleaned")

    return report


def _run_segment(farm: Farm, report: SeasonReport, days: float) -> None:
    """All five nodes through their own links, tick for tick."""
    if days <= 0:
        return
    ticks = int(days * 24 * 3600 / ph.STEP.total_seconds())
    ack_every = 900.0
    last_ack = {label: None for label in farm.nodes}
    for _ in range(ticks):
        truth = farm.world.step()
        true_now = truth.when.timestamp()
        for label, node in farm.nodes.items():
            link = farm.links[label]
            node.sample(truth)
            node.expire_unacked(true_now + node.clock_offset_s)
            if node.due(true_now) or node.behind(true_now):
                for attempt in node.drain(true_now, max_messages=8):
                    link.send(attempt.payload, true_now)
                    report.frames += 1
            for delivery in link.deliver(true_now):
                received_at = _dt.datetime.fromtimestamp(delivery.at_s,
                                                         tz=_dt.timezone.utc)
                result = farm.gateway.receive(delivery.payload,
                                             received_at=received_at)
                if result.status == "duplicate":
                    report.duplicates += 1
                if not link.needs_cumulative_ack:
                    import wire
                    link.send_ack(wire.decode(delivery.payload).seq, true_now)
            if link.needs_cumulative_ack and (
                    last_ack[label] is None
                    or true_now - last_ack[label] >= ack_every):
                acked = farm.gateway.highest_contiguous(node.node_id, node.boot,
                                                        now_s=true_now)
                if acked is not None:
                    link.send_ack(acked, true_now)
                last_ack[label] = true_now
            for seq in link.acks(true_now):
                node.ack(seq, cumulative=link.needs_cumulative_ack)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=21.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--dr", type=int, default=3, choices=(0, 1, 2, 3, 4, 5))
    ap.add_argument("--no-events", action="store_true")
    args = ap.parse_args()

    farm = build(seed=args.seed, dr=args.dr)
    print(f"Harrow Bend  ·  {args.days:g} days from {START:%Y-%m-%d}  ·  "
          f"DR{args.dr}  ·  seed {args.seed}  ·  anchored at lon 0")
    print(f"{len(farm.features)} features, {len(farm.series)} series, "
          f"{len(farm.state.datastreams)} datastreams, {len(farm.nodes)} nodes\n")

    report = season(farm, days=args.days, events=not args.no_events,
                    seed=args.seed)
    state = farm.gateway.state

    print("season events")
    for when, what in sorted(report.events, key=lambda e: e[0]):
        print(f"  {when:%m-%d %H:%M}  {what}")
    print()
    print(f"{'frames sent':<28}{report.frames}")
    print(f"{'duplicates rejected':<28}{report.duplicates}")
    print(f"{'observations':<28}{len(state.observations)}")
    print(f"{'live observations':<28}{len(state.live_observations())}")
    print(f"{'quality assertions':<28}{len(state.assertions)}")
    flagged = [a for a in state.assertions if a.flags]
    print(f"{'  flagged':<28}{len(flagged)}")
    print(f"{'validate()':<28}{state.validate() or 'clean'}")
    kinds = {}
    for event in farm.log:
        kinds[event.kind] = kinds.get(event.kind, 0) + 1
    print()
    print("log events")
    for kind in sorted(kinds):
        print(f"  {kind:<26}{kinds[kind]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

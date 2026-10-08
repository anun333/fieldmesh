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
import log as L  # noqa: E402
import project as P  # noqa: E402
from ids import uuid7  # noqa: E402
from model import (Assertor, Calibration, ClockQuality,  # noqa: E402
                   Datastream, DatastreamKind, Observation, Threshold, Usable)
from registry import NodeBinding, Registry  # noqa: E402

START = _dt.datetime(2026, 6, 1, 0, 0, tzinfo=ph.UTC)

#: Null-island anchor, following the constellation's convention: longitude zero, so
#: nothing here can be mistaken for a real location.
ANCHOR = {"type": "Point", "coordinates": [0.0, 0.0]}

SOIL = "http://vocab.example.org/cf/soil_moisture_content"
LEVEL = "http://vocab.example.org/odm2/water_level_fraction"
AIR_TEMP = "http://vocab.example.org/cf/air_temperature"
HUMIDITY = "http://vocab.example.org/cf/relative_humidity"
BATTERY = "http://vocab.example.org/cf/battery_voltage"
RSSI = "http://vocab.example.org/local/radio_signal_strength"

#: Soil thresholds, each derived from something physical rather than picked.
#:
#: `max_rate_per_s` is the one worth explaining. At a 900 s sample interval, the
#: first value tried here was 0.0004/s — which permits a jump of 0.36 in one
#: interval, nearly the entire physical range of the measurand. The check could
#: never fire, and a threshold that cannot fire is worse than none because it looks
#: like protection. The real bound comes from the fastest *legitimate* process: 25 mm
#: of irrigation over a 300 mm root zone is 0.083, about 0.00009/s, so 0.00015/s
#: leaves headroom above irrigation and still catches a jump no process could make.
#:
#: `flat_seconds` is 18 h because a probe at three decimals genuinely repeats for
#: about 8 h overnight when evapotranspiration is near zero (§4.2).
SOIL_THRESHOLDS = {"min": 0.02, "max": 0.46, "flat_seconds": 18 * 3600,
                   "flat_n": 4, "max_rate_per_s": 0.00015,
                   "cross_tolerance": 0.04}
#: A float-regulated level is constant by design, so flatline is switched off and
#: range is what catches a stuck float (§4.2).
LEVEL_THRESHOLDS = {"min": 0.10, "max": 1.0, "flat_n": None,
                    "flat_seconds": None}
AIR_THRESHOLDS = {"min": -30.0, "max": 60.0, "flat_seconds": 6 * 3600,
                  "flat_n": 12}
BATTERY_THRESHOLDS = {"min": 3.2, "max": 4.3, "flat_n": None,
                      "flat_seconds": None}


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
class Series:
    """One point: its raw and derived datastreams, its calibration, its sensor."""

    name: str
    raw: Datastream
    derived: Datastream
    calibration: Calibration
    threshold: Threshold
    sensor: F.Sensor
    channel: int


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

    def series_for(self, name: str) -> Series:
        return self.series[name]


def _series(farm, *, name, feature, prop, unit, scale, decimals, thresholds,
            interval, latency, read, channel, sensor_id=None, faults=()):
    sensor_id = sensor_id or uuid7()
    thing = farm.features[feature]["thing"]
    raw = Datastream(id=uuid7(), thing=thing, sensor=sensor_id,
                     observed_property=prop, feature=farm.features[feature]["id"],
                     kind=DatastreamKind.RAW, unit=unit,
                     expected_interval=interval, max_latency=latency)
    derived = Datastream(id=uuid7(), thing=thing, sensor=sensor_id,
                         observed_property=prop,
                         feature=farm.features[feature]["id"],
                         kind=DatastreamKind.DERIVED, derived_from=raw.id,
                         unit=unit, expected_interval=interval,
                         max_latency=latency, thresholds=thresholds)
    cal = Calibration(id=uuid7(), sensor=sensor_id, method="linear",
                      valid_from=_dt.datetime(2026, 1, 1, tzinfo=ph.UTC),
                      coefficients={"a": 1.0 / scale, "b": 0.0,
                                    "decimals": decimals})
    th = Threshold(id=uuid7(), datastream=derived.id, values=thresholds)
    for record in (raw, derived, cal, th):
        farm.log.append_record(record)
        farm.state.add(record)
    series = Series(name=name, raw=raw, derived=derived, calibration=cal,
                    threshold=th, channel=channel,
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
    world = ph.World(start=start, climate=ph.Climate(seed=seed), beds=beds,
                     troughs=troughs)

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
    for index, bed in enumerate(("bed1", "bed2", "bed3", "bed4", "bed5", "bed6")):
        for depth, channel in (("shallow", 1), ("deep", 2)):
            offset = 0.0 if depth == "shallow" else 0.03   # deeper holds more
            _series(farm, name=f"{bed}_{depth}", feature=bed, prop=SOIL,
                    unit="cm3/cm3", scale=1000.0, decimals=3,
                    thresholds=SOIL_THRESHOLDS, interval=900.0, latency=3600.0,
                    channel=channel + 2 * (index % 3),
                    read=(lambda b, o: lambda t: t.soil[b] + o)(bed, offset))

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
            read=lambda t: t.weather.air_temp_c + 6.0)
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
          "bed3_shallow", "bed3_deep"], lk.MESHTASTIC),
        ("beds_b", 0x4F2A1702, ClockQuality.RTC_SYNCED, 2.0, nd.CHRONOLOGICAL,
         ["bed4_shallow", "bed4_deep", "bed5_shallow", "bed5_deep",
          "bed6_shallow", "bed6_deep"], lk.MESHTASTIC),
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
        # §4.3: battery and signal are ordinary datastreams on this node's thing.
        for prop, unit, scale, decimals, thresholds, reader, label_suffix in (
                (BATTERY, "V", 100.0, 2, BATTERY_THRESHOLDS,
                 _battery_reader(label), "battery"),
                (RSSI, "dB[mW]", 1.0, 0,
                 {"min": -140.0, "max": 0.0, "flat_n": None,
                  "flat_seconds": None}, _rssi_reader(label), "rssi")):
            name = f"{label}_{label_suffix}"
            channel = max(used) + 1
            used.add(channel)
            series = _series(farm, name=name, feature=names[0].split("_")[0]
                             if names[0].startswith("bed") else
                             ("paddock" if label == "paddock" else
                              "plot" if label == "plot" else "hoop"),
                             prop=prop, unit=unit, scale=scale,
                             decimals=decimals, thresholds=thresholds,
                             interval=3600.0, latency=21600.0, channel=channel,
                             read=reader)
            registry.bind_point(node_id, channel, series.raw.id)
            channels.append(nd.Channel(channel, 3600.0, 21600.0, series.sensor,
                                       name=name))

        node = nd.Node(node_id, channels, dr=dr, ack_timeout_s=1800.0,
                       policy=nd.BufferPolicy(buffer_max=800, drain_order=drain))
        farm.nodes[label] = node
        farm.links[label] = lk.Link(profile, seed=seed + node_id % 97)

    farm.gateway = G.Gateway(registry, log, state)
    return farm


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
    closed = Calibration(id=old.id, sensor=old.sensor, method=old.method,
                         valid_from=old.valid_from, valid_to=at,
                         reference=old.reference, coefficients=old.coefficients,
                         performed_by=old.performed_by)
    fresh = Calibration(id=uuid7(), sensor=old.sensor, method="linear",
                        valid_from=at,
                        coefficients={"a": 1.0 / scale, "b": 0.0,
                                      "decimals": decimals})
    for record in (closed, fresh):
        farm.log.append_record(record)
        farm.state.add(record)
    series.calibration = fresh

    raw_by_time = {o.measured_at: o for o in farm.state.observations
                   if o.datastream == series.raw.id}
    superseded = 0
    for old_obs in list(farm.state.observations):
        if old_obs.datastream != series.derived.id or old_obs.measured_at < at:
            continue
        if any(o.supersedes == old_obs.id for o in farm.state.observations):
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
                node.ack(seq)


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

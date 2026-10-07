#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The registry: short wire ids to full identities (spec v0.1 §1, §8.1, §9.1).

§1 keeps 16-byte UUIDs off the air. A node sends its native short id and a one-byte
channel index, and this is the table that turns `(node, channel)` into the
datastream those readings belong to. The mapping is part of the audit chain — "which
point did this reading land on" resolves through here — so it is data the farmer
owns, not a convention buried in a driver.

Per node it also holds what §9.1's manifest declares and §2 needs: the clock source,
and the **uncertainty budget** for timestamps from that clock. §2 makes
`measured_at_uncertainty` mandatory and non-zero, and this is where the honest
number comes from — a node cannot be asked at ingest time how good its clock is.

§8.1: an unregistered device is **heard but not trusted**. `node_for` returning None
is not an error to swallow; the gateway quarantines the data until someone approves
the device, so nothing unapproved reaches the observation record.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from model import ClockQuality


@dataclass(frozen=True, slots=True)
class NodeBinding:
    """One registered device.

    `uncertainty_s` is the half-width to stamp on every reading from this node
    (§2): sub-second for GPS, the sync error plus link latency for a network clock,
    the drift budget since last sync for an unsynced RTC, and at least the sample
    interval plus transmit latency for a node with no clock at all.
    """

    node: int
    site: UUID
    clock_quality: ClockQuality
    uncertainty_s: float
    firmware: str | None = None
    driver: str | None = None
    driver_version: str | None = None

    def __post_init__(self) -> None:
        if self.uncertainty_s <= 0:
            raise ValueError(
                "uncertainty_s must be positive — §2 forbids a timestamp nobody "
                "can bound, and a node's clock quality is known at registration, "
                "not at ingest")

    def provenance(self) -> dict:
        """What §3.2 wants stamped on a reading so a derivation is reproducible."""
        out = {}
        if self.firmware:
            out["firmware"] = self.firmware
        if self.driver:
            out["driver"] = self.driver
        if self.driver_version:
            out["driver_version"] = self.driver_version
        return out


@dataclass(frozen=True, slots=True)
class PointBinding:
    """One channel on one node, bound to the **raw** datastream it feeds."""

    node: int
    channel: int
    datastream: UUID

    def __post_init__(self) -> None:
        if not 0 <= self.channel <= 0xFF:
            raise ValueError("channel is one byte (§1)")


class Registry:
    """Node and point bindings. Not a store — build it from the log, or by hand."""

    __slots__ = ("_nodes", "_points")

    def __init__(self):
        self._nodes: dict[int, NodeBinding] = {}
        self._points: dict[tuple[int, int], PointBinding] = {}

    # ------------------------------------------------------------ registering

    def register_node(self, binding: NodeBinding) -> NodeBinding:
        self._nodes[binding.node] = binding
        return binding

    def bind_point(self, node: int, channel: int, datastream: UUID) -> PointBinding:
        if node not in self._nodes:
            raise KeyError(
                f"node {node:#x} is not registered; bind its channels after "
                f"registering it, so an unapproved device cannot acquire points")
        binding = PointBinding(node=node, channel=channel, datastream=datastream)
        self._points[(node, channel)] = binding
        return binding

    # --------------------------------------------------------------- lookups

    def node_for(self, node: int) -> NodeBinding | None:
        """The node, or None — which means quarantine, not discard (§8.1)."""
        return self._nodes.get(node)

    def datastream_for(self, node: int, channel: int) -> UUID | None:
        binding = self._points.get((node, channel))
        return binding.datastream if binding else None

    def channels_of(self, node: int) -> tuple[int, ...]:
        return tuple(sorted(ch for (n, ch) in self._points if n == node))

    @property
    def nodes(self) -> tuple[NodeBinding, ...]:
        return tuple(self._nodes.values())

    def __contains__(self, node: int) -> bool:
        return node in self._nodes

    def __len__(self) -> int:
        return len(self._points)

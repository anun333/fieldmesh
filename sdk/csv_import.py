#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bring existing records in from CSV (spec v0.1 §10: "nothing re-entered by hand").

A farm arrives with years of readings already in spreadsheets and logger exports, and a
research station with public datasets. This turns one into observations on declared
datastreams, so §9.2's replay of real field data and a farmer's own history land in the
same log as everything else.

Derived from campus_twin's `csv_replay.py` (see PROVENANCE.md). Two of its defaults were
reversed on the way, because each one is wrong for this spec in a way that produces no
error, only wrong data.

## Timestamps are local until proven otherwise

Upstream read every timestamp as UTC. A spreadsheet in Tennessee that says `14:00`
means Central time, so that default silently shifts every reading by five or six hours —
and the error is invisible, because the series still looks like a plausible day. Here
the mapping **must declare a timezone**, `UTC` or an IANA name like `America/Chicago`,
and an import without one is refused.

Daylight saving makes local time ambiguous twice a year. The autumn hour that occurs
twice cannot be placed without more information, and the spring hour that never existed
is a typing error; both are **reported and skipped**, never guessed at — guessing puts a
reading an hour from where it was taken with nothing to say so.

## Values arrive exactly as they were written

Upstream applied a scale and offset on the way in. Here that would be the silent
cleaning §3.2 forbids: the stored value would no longer be what the file said, and
nothing in the log would record the transform. So values land unaltered on a **raw**
datastream in the file's own unit, and any conversion is a `Calibration` producing a
derived series — versioned, visible, and reversible.

## And three smaller rules

* `uncertainty_s` is required. §2 makes `measured_at_uncertainty` mandatory and non-zero,
  a CSV has no column for it, and inventing one would be a claim nobody made. Half the
  logging interval is the usual honest answer.
* Re-importing is idempotent. A row whose `(datastream, measured_at)` is already in the
  log is skipped and counted, because farmers re-run imports.
* Every observation carries provenance: the file, its SHA-256, and the row number, so any
  reading can be traced to the line it came from.
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import os
from dataclasses import dataclass, field
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import project as P
from ids import uuid7
from model import ClockQuality, DatastreamKind, Observation

UTC = _dt.timezone.utc


class MappingError(ValueError):
    """The mapping cannot be used. Raised before a single row is written."""


@dataclass
class ImportReport:
    rows: int = 0
    written: int = 0
    already_present: int = 0
    blank: int = 0
    not_numeric: int = 0
    ambiguous_time: int = 0
    nonexistent_time: int = 0
    unparsable_time: int = 0
    problems: list = field(default_factory=list)

    @property
    def skipped(self) -> int:
        return (self.already_present + self.blank + self.not_numeric
                + self.ambiguous_time + self.nonexistent_time + self.unparsable_time)

    def note(self, problem: str) -> None:
        if len(self.problems) < 50:          # enough to act on, not a flood
            self.problems.append(problem)


def _zone(name):
    if not name:
        raise MappingError(
            "timestamp.timezone is required: 'UTC' or an IANA name such as "
            "'America/Chicago'. A spreadsheet's times are local until proven "
            "otherwise, and assuming UTC shifts every reading silently")
    if name.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise MappingError(f"unknown timezone {name!r}") from exc


def _local_to_utc(naive: _dt.datetime, zone):
    """`(utc, None)` or `(None, "ambiguous" | "nonexistent")`.

    zoneinfo resolves both cases without complaint — `fold` picks one of the two
    autumn hours, and a spring-gap time is pushed to the far side of the gap. Both
    would put a reading an hour from where it was taken. So round-trip and check.
    """
    if zone is UTC:
        return naive.replace(tzinfo=UTC), None
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() == second.utcoffset():
        return first.astimezone(UTC), None
    # The two folds disagree, which happens in *both* awkward cases — so the offset
    # alone cannot tell them apart, and the first version of this called the spring
    # gap "ambiguous". A time that really occurred survives a round trip through UTC
    # unchanged; one that never occurred comes back as a different wall-clock time.
    back = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    return None, ("ambiguous" if back == naive else "nonexistent")


def _parse_time(text: str, fmt: str, zone):
    text = (text or "").strip()
    if not text:
        raise ValueError("empty")
    if fmt in ("epoch", "epoch_s"):
        return _dt.datetime.fromtimestamp(float(text), tz=UTC), None
    if fmt == "epoch_ms":
        return _dt.datetime.fromtimestamp(float(text) / 1000.0, tz=UTC), None
    if fmt == "iso":
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    else:
        parsed = _dt.datetime.strptime(text, fmt)
    if parsed.tzinfo is not None:
        # The cell said its own offset, which beats anything the mapping assumed.
        return parsed.astimezone(UTC), None
    return _local_to_utc(parsed, zone)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_mapping(mapping: dict, state: P.State) -> dict:
    """Check a mapping against the declared datastreams. Returns column -> datastream."""
    stamp = mapping.get("timestamp") or {}
    if not stamp.get("column"):
        raise MappingError("timestamp.column is required")
    _zone(stamp.get("timezone"))
    uncertainty = mapping.get("uncertainty_s")
    if not isinstance(uncertainty, (int, float)) or uncertainty <= 0:
        raise MappingError(
            "uncertainty_s is required and positive (§2). A CSV has no column for it "
            "and inventing one would be a claim nobody made; half the logging "
            "interval is the usual honest answer")
    columns = mapping.get("columns") or {}
    if not columns:
        raise MappingError("columns maps at least one CSV column to a datastream")
    out = {}
    for column, spec in columns.items():
        try:
            ident = UUID(str(spec["datastream"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise MappingError(f"column {column!r}: datastream must be a UUID") from exc
        ds = state.datastreams.get(ident)
        if ds is None:
            raise MappingError(f"column {column!r}: no datastream {ident} is declared "
                               f"— declare it first, with its unit and property")
        if ds.kind is not DatastreamKind.RAW:
            raise MappingError(
                f"column {column!r}: datastream {ident} is derived. Imported values "
                f"land on a raw datastream as written (§3.2); a conversion is a "
                f"calibration producing the derived series, not a transform on import")
        if "scale" in spec or "offset" in spec:
            raise MappingError(
                f"column {column!r}: scale and offset are not applied on import — "
                f"that would store a value the file never contained, with no record "
                f"of the change. Declare the raw datastream in the file's own unit "
                f"and add a Calibration")
        out[column] = ds
    return out


def import_csv(log, state: P.State, path: str, mapping: dict, *,
               received_at: _dt.datetime | None = None,
               clock_quality: ClockQuality | None = None) -> ImportReport:
    """Append the CSV's readings to `log` (and fold them into `state`)."""
    bound = validate_mapping(mapping, state)
    stamp = mapping["timestamp"]
    zone = _zone(stamp["timezone"])
    fmt = stamp.get("format", "iso")
    uncertainty = float(mapping["uncertainty_s"])
    quality = clock_quality or ClockQuality(mapping.get("clock_quality", "none"))
    received = received_at or _dt.datetime.now(tz=UTC)
    source = {"source_file": os.path.basename(path), "source_sha256": _sha256(path)}
    report = ImportReport()

    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = [h.strip() for h in next(reader)]
        missing = [c for c in [stamp["column"], *bound] if c not in header]
        if missing:
            raise MappingError(f"columns not in the file: {missing}")
        for line, raw in enumerate(reader, start=2):
            row = dict(zip(header, raw))
            report.rows += 1
            try:
                measured, trouble = _parse_time(row.get(stamp["column"]), fmt, zone)
            except ValueError as exc:
                report.unparsable_time += 1
                report.note(f"line {line}: timestamp {row.get(stamp['column'])!r} "
                            f"({exc})")
                continue
            if trouble == "ambiguous":
                report.ambiguous_time += 1
                report.note(f"line {line}: {row[stamp['column']]!r} occurs twice in "
                            f"{stamp['timezone']} as clocks go back; not guessed")
                continue
            if trouble == "nonexistent":
                report.nonexistent_time += 1
                report.note(f"line {line}: {row[stamp['column']]!r} never happened in "
                            f"{stamp['timezone']} — clocks went forward; not guessed")
                continue
            for column, ds in bound.items():
                text = (row.get(column) or "").strip()
                if not text:
                    report.blank += 1
                    continue
                try:
                    value = float(text)
                except ValueError:
                    report.not_numeric += 1
                    continue
                if value != value or value in (float("inf"), float("-inf")):
                    report.not_numeric += 1
                    continue
                if state.has_observation_at(ds.id, measured):
                    report.already_present += 1
                    continue
                obs = Observation(
                    id=uuid7(), datastream=ds.id, measured_at=measured,
                    measured_at_uncertainty=uncertainty, received_at=received,
                    result=int(value) if value.is_integer() and "." not in text
                    else value,
                    clock_quality=quality,
                    provenance={**source, "source_line": line,
                                "source_column": column})
                log.append_record(obs)
                state.add(obs)
                report.written += 1
    return report

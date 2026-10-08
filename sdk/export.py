#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Export the log in open formats (spec v0.1 §7.6).

*Farmer-owned* is the project's premise, and the most load-bearing thing it can mean is
**being able to take your data and leave.** A stack with no export does not pass that
test however good its internals are, so this module is less a feature than the discharge
of a promise.

## Three formats, and only one of them is the archive

| file | what it is | lossless |
| --- | --- | --- |
| `log.jsonl` | every event, in log order — **the archive** | yes, by construction |
| `*.csv` | one file per record type, for a spreadsheet | measured per export, not assumed |
| `features.geojson` | a *view* for GIS clients | **no**, and says so |

The distinction is the point. An export that claims to lose nothing and quietly does is
worse than one that declares its losses, because the loss is discovered years later by
whoever needed the missing field.

`log.jsonl` is **the same format the log already writes** — `Log(path=...)` appends
exactly these lines. So an export is a replica rather than a conversion, and importing it
is a replay, which is the strongest guarantee available: there is no second encoder that
could disagree with the first.

## Events, not records

The unit exported is the **event**, not the record. §7.3's compensating events carry a
reason and no record at all, so an export built from `log.records()` would silently drop
every correction — the audit trail minus the part that says something was wrong. That is
precisely the silent cleaning §7.6 exists to prevent, and it is an easy mistake to make
because `records()` is the more convenient interface.

## The manifest

`MANIFEST.json` carries counts and a SHA-256 per file, and marks each file lossless or
not. That is what makes the directory an auditable copy rather than a pile of files:
`verify()` re-reads it and reports anything that does not match. A farmer handing this to
a certifier, or to a lawyer, can show it is complete.
"""
from __future__ import annotations

import csv
import datetime as _dt
import gzip
import hashlib
import json
import os
from dataclasses import dataclass, field

import codec
import project as P
from log import Log

#: Bumped when the layout changes in a way an importer must notice.
EXPORT_VERSION = 1

ARCHIVE = "log.jsonl"
MANIFEST = "MANIFEST.json"
GEOJSON = "features.geojson"

#: Column order for the types a person actually reads, so the useful fields are not
#: buried behind UUIDs. Anything unlisted follows, sorted, so a new field cannot be
#: dropped by forgetting to add it here.
_PREFERRED = {
    "Observation": ["id", "datastream", "measured_at", "result", "unit",
                    "measured_at_uncertainty", "received_at", "node", "boot", "seq"],
    "Datastream": ["id", "kind", "unit", "observed_property", "thing", "sensor",
                   "feature"],
    "QualityAssertion": ["id", "observation", "usable", "flags", "asserted_at",
                         "assertor", "check", "note"],
    "Calibration": ["id", "sensor", "method", "valid_from", "valid_to"],
    "Threshold": ["id", "datastream", "created_at"],
}


@dataclass(frozen=True, slots=True)
class ExportedFile:
    name: str
    kind: str
    rows: int
    sha256: str
    lossless: bool
    note: str | None = None

    def to_jsonable(self) -> dict:
        out = {"name": self.name, "kind": self.kind, "rows": self.rows,
               "sha256": self.sha256, "lossless": self.lossless}
        if self.note:
            out["note"] = self.note
        return out


@dataclass(frozen=True, slots=True)
class Manifest:
    exported_at: _dt.datetime
    events: int
    files: tuple[ExportedFile, ...] = field(default_factory=tuple)
    archive_name: str = ARCHIVE

    @property
    def archive(self) -> ExportedFile | None:
        return next((f for f in self.files if f.name == self.archive_name), None)

    def to_jsonable(self) -> dict:
        return {
            "export_version": EXPORT_VERSION,
            "spec": "v0.1 §7.6",
            "exported_at": self.exported_at.isoformat().replace("+00:00", "Z"),
            "events": self.events,
            "archive": self.archive_name,
            "files": [f.to_jsonable() for f in self.files],
        }


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------- archive

def _open(path: str, mode: str):
    """Open a path, transparently gzipped when it ends in `.gz`."""
    if path.endswith(".gz"):
        return gzip.open(path, mode + "t", encoding="utf-8")
    return open(path, mode, encoding="utf-8")


def write_archive(log: Log, path: str) -> int:
    """Every event, one JSON object per line, in log order. Gzipped if `path` says so.

    Deliberately `Event.to_jsonable` and nothing else — the same call `Log._commit`
    makes when it persists. A separate encoder here could drift from the one the log
    uses, and the divergence would appear only in exports, which is the worst place
    for a bug to live because nobody reads an export until they need it.

    **Uncompressed is the canonical form**, and the default, because that file is
    byte-compatible with what `Log(path=...)` writes and reads — an export is then a
    replica rather than a conversion, and `gzip` would break that property for the
    sake of disk. Compression is offered because the numbers are not small: a
    simulated week measured **35.1 MB, or 3.4 MB gzipped — 10.4x** — which puts a
    180-day season at roughly 900 MB against 87 MB. §7.6 promises the farmer can take
    the data, and 900 MB over a rural connection is a partial failure of that promise,
    so the option matters more than it looks.
    """
    count = 0
    with _open(path, "w") as handle:
        for event in log.events:
            handle.write(json.dumps(event.to_jsonable(), separators=(",", ":")) + "\n")
            count += 1
    return count


def read_archive(path: str, *, into: Log | None = None) -> Log:
    """Replay an archive into a log, preserving every event's identity and stamp.

    `receive` rather than `append`: `append` would issue **new** HLC stamps and new
    event ids, so the import would be a different history that happened to contain the
    same records. §7.4's causality and §7.1's "replay the log and get the same state"
    both depend on the stamps surviving, which makes `receive` the only correct choice
    and `append` a plausible-looking error.
    """
    from log import Event
    log = into if into is not None else Log()
    if not os.path.exists(path) and os.path.exists(path + ".gz"):
        path += ".gz"
    with _open(path, "r") as handle:
        for line in handle:
            line = line.strip()
            if line:
                log.receive(Event.from_jsonable(json.loads(line)))
    return log


# ------------------------------------------------------------------------- csv

def _encode(value) -> str:
    """One value as a CSV cell.

    A plain cell wherever a plain cell can be read back as the same value, and a
    JSON-quoted cell wherever it cannot. Two cases need the quotes, both of them
    strings that a reader would otherwise turn into something else:

    * **a numeric- or boolean-looking string**, like a `check_version` of `"1"`, which
      comes back as the integer `1` from a bare cell. Found by the round-trip test on
      the first run, and version strings are exactly where it bites;
    * **the empty string**, which a bare cell cannot tell from an absent value.

    So `1` writes as `1` and `"1"` writes as `"1"`, which is faintly odd to read in a
    spreadsheet and unambiguous on the way back — the right trade for a format whose
    job is to be both.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        if _uncell(value) != value:
            return json.dumps(value)
        return value
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _cell(value):
    """`(text, lossless)` — and losslessness is **verified, not predicted.**

    The cell is decoded straight back and compared with what went in. An earlier
    version reasoned about which values were safe and was wrong about one of them, so
    this asks the question instead of answering it: any value whose encoding does not
    survive its own decoder marks the file as lossy in the manifest, including cases
    nobody anticipated. A `float('nan')` would be caught this way without ever having
    been thought about.
    """
    text = _encode(value)
    return text, _uncell(text) == value


def _uncell(text: str):
    """A CSV cell back into a value. The inverse of `_cell` where one exists."""
    if text == "":
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if text and text[0] in "[{\"":
        try:
            return json.loads(text)
        except ValueError:
            return text
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _columns(kind: str, docs: list[dict]) -> list[str]:
    seen = {key for doc in docs for key in doc}
    seen.discard(codec.TYPE_KEY)
    ordered = [c for c in _PREFERRED.get(kind, []) if c in seen]
    return ordered + sorted(seen - set(ordered))


def write_csv(log: Log, directory: str) -> list[ExportedFile]:
    """One CSV per record type, plus `corrections.csv` if there are any.

    Corrections get their own file because they are events without records (§7.3) and
    would otherwise vanish — see the module docstring.
    """
    by_kind: dict[str, list[dict]] = {}
    corrections: list[dict] = []
    for event in log.events:
        doc = event.payload
        kind = doc.get(codec.TYPE_KEY)
        if kind is None:
            corrections.append({"event": str(event.id), "stamp": str(event.stamp),
                                "recorded_at": event.recorded_at.isoformat(),
                                **{k: v for k, v in doc.items()}})
            continue
        by_kind.setdefault(kind, []).append(doc)

    out: list[ExportedFile] = []
    for kind, docs in sorted(by_kind.items()):
        name = f"{kind.lower()}s.csv"
        path = os.path.join(directory, name)
        columns = _columns(kind, docs)
        lossless = True
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            for doc in docs:
                row = []
                for column in columns:
                    text, ok = _cell(doc.get(column))
                    lossless = lossless and ok
                    row.append(text)
                writer.writerow(row)
        out.append(ExportedFile(
            name=name, kind=kind, rows=len(docs), sha256=_sha256(path),
            lossless=lossless,
            note=None if lossless else
            "a field holds an empty string, which CSV cannot tell from absent; "
            f"use {ARCHIVE} as the authoritative copy"))

    if corrections:
        name = "corrections.csv"
        path = os.path.join(directory, name)
        columns = sorted({k for c in corrections for k in c})
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            for item in corrections:
                writer.writerow([_cell(item.get(c))[0] for c in columns])
        out.append(ExportedFile(name=name, kind="Correction", rows=len(corrections),
                                sha256=_sha256(path), lossless=True,
                                note="§7.3 compensating events, which carry a reason "
                                     "and no record"))
    return out


def read_csv_records(directory: str, kind: str) -> list:
    """Decode one type's CSV back into records, for the round-trip check."""
    path = os.path.join(directory, f"{kind.lower()}s.csv")
    out = []
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            doc = {codec.TYPE_KEY: kind}
            for column, text in row.items():
                value = _uncell(text)
                if value is not None:
                    doc[column] = value
            out.append(codec.load(doc))
    return out


# --------------------------------------------------------------------- geojson

def write_geojson(state: P.State, path: str, *, labels: dict | None = None) -> ExportedFile:
    """Features of interest as a GeoJSON FeatureCollection — **a view, not the archive.**

    Lossy on purpose and marked so in the manifest. One feature per feature of interest
    that has geometry, carrying a summary of the series observed there: unit, latest
    value and time, reading count, and staleness. That is what a GIS client needs to
    draw a map, and it is nothing like enough to reconstruct the log.

    A feature with no geometry is **counted and reported**, never silently dropped — a
    GIS client discards a geometryless feature without a word, which is how a missing
    bed becomes invisible rather than noticeable.
    """
    labels = labels or {}
    features = []
    skipped = 0
    by_feature: dict[object, list] = {}
    for ds in state.datastreams.values():
        if ds.feature is not None:
            by_feature.setdefault(ds.feature, []).append(ds)

    for ident, streams in sorted(by_feature.items(), key=lambda kv: str(kv[0])):
        label = labels.get(ident, {})
        geometry = label.get("feature")
        if geometry is None:
            skipped += 1
            continue
        series = []
        for ds in sorted(streams, key=lambda d: d.id.int):
            rows = state.live_observations_of(ds.id)
            last = rows[-1] if rows else None
            series.append({
                "datastream": str(ds.id),
                "name": labels.get(ds.id, {}).get("name", str(ds.id)),
                "kind": ds.kind.value,
                "unit": ds.unit,
                "observed_property": ds.observed_property,
                "readings": len(rows),
                "latest_result": last.result if last else None,
                "latest_measured_at": (last.measured_at.isoformat().replace(
                    "+00:00", "Z") if last else None),
                "health": state and P.datastream_health(
                    ds, last.measured_at, last.measured_at).value if last else "unknown",
            })
        features.append({
            "type": "Feature",
            "id": str(ident),
            "geometry": geometry,
            "properties": {
                "name": label.get("name", str(ident)),
                "description": label.get("description"),
                "datastreams": len(streams),
                "series": series,
            },
        })

    doc = {"type": "FeatureCollection", "features": features}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=1, sort_keys=False)
        handle.write("\n")
    note = ("a view for GIS clients: current values and summaries only, not the "
            f"history. {ARCHIVE} is the authoritative copy")
    if skipped:
        note += f". {skipped} feature(s) omitted for having no geometry"
    return ExportedFile(name=os.path.basename(path), kind="FeatureCollection",
                        rows=len(features), sha256=_sha256(path), lossless=False,
                        note=note)


# ------------------------------------------------------------------ the export

def export_log(log: Log, directory: str, *, state: P.State | None = None,
               labels: dict | None = None, geojson: bool = True,
               compress: bool = False) -> Manifest:
    """Write the whole export into `directory` and return its manifest."""
    os.makedirs(directory, exist_ok=True)
    name = ARCHIVE + ".gz" if compress else ARCHIVE
    archive_path = os.path.join(directory, name)
    events = write_archive(log, archive_path)
    files = [ExportedFile(name=name, kind="Event", rows=events,
                          sha256=_sha256(archive_path), lossless=True,
                          note="the authoritative copy; replays into an identical log")]
    files.extend(write_csv(log, directory))
    if geojson:
        if state is None:
            state = P.state_from_log(log)
        files.append(write_geojson(state, os.path.join(directory, GEOJSON),
                                   labels=labels))

    manifest = Manifest(
        exported_at=_dt.datetime.now(tz=_dt.timezone.utc),
        events=events, files=tuple(files), archive_name=name)
    with open(os.path.join(directory, MANIFEST), "w", encoding="utf-8") as handle:
        json.dump(manifest.to_jsonable(), handle, indent=1)
        handle.write("\n")
    return manifest


def import_log(directory: str) -> Log:
    """Replay an export directory's archive into a fresh log, gzipped or not."""
    return read_archive(os.path.join(directory, ARCHIVE))


def verify(directory: str) -> list[str]:
    """Check an export against its manifest. Empty list means intact.

    Checks the files are present, their checksums match, and the archive's line count
    equals the manifest's event count. This is the operation that makes the export
    *evidence* — without it the manifest is a claim about files rather than a check on
    them.
    """
    problems: list[str] = []
    manifest_path = os.path.join(directory, MANIFEST)
    if not os.path.exists(manifest_path):
        return [f"{MANIFEST} is missing"]
    with open(manifest_path, encoding="utf-8") as handle:
        doc = json.load(handle)
    if doc.get("export_version") != EXPORT_VERSION:
        problems.append(f"export_version {doc.get('export_version')} is not "
                        f"{EXPORT_VERSION}")
    for entry in doc.get("files", []):
        path = os.path.join(directory, entry["name"])
        if not os.path.exists(path):
            problems.append(f"{entry['name']} is missing")
            continue
        actual = _sha256(path)
        if actual != entry["sha256"]:
            problems.append(f"{entry['name']} checksum differs "
                            f"(manifest {entry['sha256'][:12]}, file {actual[:12]})")
    archive_name = doc.get("archive", ARCHIVE)
    archive_path = os.path.join(directory, archive_name)
    if os.path.exists(archive_path):
        with _open(archive_path, "r") as handle:
            lines = sum(1 for line in handle if line.strip())
        if lines != doc.get("events"):
            problems.append(f"{archive_name} has {lines} events, manifest says "
                            f"{doc.get('events')}")
    return problems


# -------------------------------------------------------------------- the CLI

def main(argv=None) -> int:
    """`export.py <log.jsonl> <directory>` — or `--verify <directory>`.

    Takes a log *file* rather than a farm, so this stays usable by anyone holding a
    log and keeps `sdk/` free of any dependency on the simulator.
    """
    import argparse
    ap = argparse.ArgumentParser(description="Export a log in open formats (§7.6).")
    ap.add_argument("source", help="a log.jsonl, or an export directory with --verify")
    ap.add_argument("directory", nargs="?", help="where to write the export")
    ap.add_argument("--verify", action="store_true",
                    help="check an existing export against its manifest")
    ap.add_argument("--compress", action="store_true",
                    help="gzip the archive (about 10x; uncompressed is canonical)")
    args = ap.parse_args(argv)

    if args.verify:
        problems = verify(args.source)
        for problem in problems:
            print(f"  {problem}")
        print("intact" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    if not args.directory:
        ap.error("a destination directory is required")
    manifest = export_log(read_archive(args.source), args.directory,
                          compress=args.compress)
    print(f"{manifest.events} events -> {args.directory}")
    width = max(len(f.name) for f in manifest.files)
    for entry in manifest.files:
        mark = "lossless" if entry.lossless else "a view"
        print(f"  {entry.name:<{width}}  {entry.rows:>7} rows  {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Erasure by key destruction (spec v0.1 §7.3; Q17).

An append-only log cannot delete a worker's name from a maintenance note, and a farm
must be able to when the worker has a right to it. So personal text never enters the log
in the clear: it is **sealed** under a key that belongs to that one person, and erasing
the person destroys their key. The events stay — the log is continuous and auditable —
and the content becomes unrecoverable.

## Where the keys live (Q17, decided 2026-10-09)

* **Each person has a data key.** A sealed value names its person and is AES-256-GCM
  under their key, with the person bound in as associated data, so a value cannot be
  moved to another person's name.
* **The data keys are wrapped by the farm key** and kept in a key ring beside the log.
  The ring holds nothing readable without the farm key, so it may be backed up with the
  log.
* **The farm key is kept apart**: on the gateway, never in a backup, plus one offline
  recovery copy (written down, or on a USB stick in a drawer), because a disk that dies
  with the only copy takes every person's data with it.
* **Erasing rotates the farm key.** The person's data key is dropped, every other data key
  is re-wrapped under a new farm key, and the old farm key is destroyed — including its
  recovery copy, which the new one replaces. That is what reaches the backups: an old
  backup still holds the person's wrapped key, but the only key that unwraps it is gone.
  The rule this rests on, stated as the spec states it: **a farm key is never backed up
  with the data, and a superseded recovery copy is destroyed.** Break it and erasure does
  not reach the backups.

Plan B, if this proves too much for a farm to run, is to keep personal data out of the
log altogether and log only a reference; erasure is then a delete in a side store.

Uses the `cryptography` package (Apache-2.0 or BSD-3-Clause), imported only here so the
rest of the SDK does not need it.
"""
from __future__ import annotations

import base64
import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from uuid import UUID

PREFIX = "sealed:1:"
ERASED = "[erased]"
ERASURE = "erasure"          # the log event that records an erasure


class ErasureError(Exception):
    pass


def _aead(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _wrap(farm_key: bytes, subject: str, data_key: bytes) -> str:
    nonce = os.urandom(12)
    return _b64(nonce + _aead(farm_key).encrypt(nonce, data_key, b"wrap:" + subject.encode()))


def _unwrap(farm_key: bytes, subject: str, wrapped: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    raw = _unb64(wrapped)
    try:
        return _aead(farm_key).decrypt(raw[:12], raw[12:], b"wrap:" + subject.encode())
    except InvalidTag as exc:
        raise ErasureError(f"the farm key does not open {subject}'s data key") from exc


@dataclass
class KeyRing:
    """The farm key and each person's wrapped data key. `farm_key` lives apart from the
    log and its backups; `wrapped` may travel with them (see `save`)."""

    farm_key: bytes
    wrapped: dict = field(default_factory=dict)
    generation: int = 1

    @classmethod
    def new(cls) -> "KeyRing":
        return cls(farm_key=os.urandom(32))

    def _data_key(self, subject: str, *, create: bool) -> bytes | None:
        if subject not in self.wrapped:
            if not create:
                return None
            key = os.urandom(32)
            self.wrapped[subject] = _wrap(self.farm_key, subject, key)
            return key
        return _unwrap(self.farm_key, subject, self.wrapped[subject])

    def seal(self, subject: UUID, text: str) -> str:
        """`text` sealed to `subject`, as a string any text field of a record can hold."""
        s = str(subject)
        key = self._data_key(s, create=True)
        nonce = os.urandom(12)
        body = _aead(key).encrypt(nonce, text.encode(), s.encode())
        return f"{PREFIX}{s}:{_b64(nonce + body)}"

    def reveal(self, value):
        """The plaintext of a sealed value, `ERASED` if its person was erased, and any
        other value unchanged."""
        if not isinstance(value, str) or not value.startswith(PREFIX):
            return value
        subject, _, body = value[len(PREFIX):].partition(":")
        key = self._data_key(subject, create=False)
        if key is None:
            return ERASED
        raw = _unb64(body)
        from cryptography.exceptions import InvalidTag
        try:
            return _aead(key).decrypt(raw[:12], raw[12:], subject.encode()).decode()
        except InvalidTag as exc:
            raise ErasureError("a sealed value failed its integrity check") from exc

    def shred(self, subject: UUID) -> bytes:
        """Destroy `subject`'s data key and rotate the farm key; returns the **old** farm
        key so the caller can confirm it is destroyed everywhere — the gateway's copy and
        the offline recovery copy, which the new one replaces."""
        s = str(subject)
        if s not in self.wrapped:
            raise ErasureError(f"no data key for {s}; nothing of theirs was sealed")
        new_key = os.urandom(32)
        rewrapped = {other: _wrap(new_key, other, _unwrap(self.farm_key, other, w))
                     for other, w in self.wrapped.items() if other != s}
        old, self.farm_key, self.wrapped = self.farm_key, new_key, rewrapped
        self.generation += 1
        return old

    def recovery_code(self) -> str:
        """The farm key for the offline copy, in groups a person can write down."""
        code = base64.b32encode(self.farm_key).decode().rstrip("=")
        return f"g{self.generation}-" + "-".join(code[i:i + 4] for i in range(0, len(code), 4))

    @staticmethod
    def from_recovery_code(code: str, wrapped: dict) -> "KeyRing":
        gen, _, groups = code.partition("-")
        raw = groups.replace("-", "")
        key = base64.b32decode(raw + "=" * (-len(raw) % 8))
        return KeyRing(farm_key=key, wrapped=dict(wrapped), generation=int(gen[1:]))

    def save(self, ring_path: str, farm_key_path: str) -> None:
        """Two files on purpose: the ring may be backed up with the log, the farm key
        must not be."""
        with open(ring_path, "w", encoding="utf-8") as h:
            json.dump({"generation": self.generation, "wrapped": self.wrapped}, h, indent=1)
        fd = os.open(farm_key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as h:
            h.write(self.farm_key)

    @classmethod
    def load(cls, ring_path: str, farm_key_path: str) -> "KeyRing":
        with open(ring_path, encoding="utf-8") as h:
            doc = json.load(h)
        with open(farm_key_path, "rb") as h:
            key = h.read()
        return cls(farm_key=key, wrapped=doc["wrapped"], generation=doc["generation"])


def erase(log, ring: KeyRing, subject: UUID, *, by: UUID | None = None,
          reason: str | None = None, at: _dt.datetime | None = None):
    """Erase a person: shred their key, and record that it happened — the event, not the
    content, so the log says an erasure took place without saying what was erased."""
    ring.shred(subject)
    return log.append(ERASURE, {
        "subject": str(subject), "by": str(by) if by else None, "reason": reason,
        "at": (at or _dt.datetime.now(tz=_dt.timezone.utc)).isoformat(),
        "farm_key_generation": ring.generation,
        "note": "the person's data key is destroyed and the farm key rotated; destroy the "
                "old farm key's recovery copy too, or backups still hold the person"})

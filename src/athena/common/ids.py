"""Stable identifier primitives for ATHENA."""

from __future__ import annotations

import secrets
import time
import uuid

_UUID_TIMESTAMP_MASK = (1 << 48) - 1


def new_uuid7() -> uuid.UUID:
    """Return an RFC 9562 UUID version 7.

    Python 3.12 does not provide ``uuid.uuid7()``, so ATHENA constructs the
    standardized layout directly: 48-bit Unix-millisecond timestamp, version
    7, RFC variant 10, and 74 pseudorandom bits.
    """
    timestamp_ms = (time.time_ns() // 1_000_000) & _UUID_TIMESTAMP_MASK
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)

    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    return uuid.UUID(int=value)


def uuid_to_blob(value: uuid.UUID) -> bytes:
    """Return the canonical 16-byte big-endian UUID representation."""
    return value.bytes


def uuid_from_blob(value: bytes) -> uuid.UUID:
    """Create a UUID from its 16-byte database representation."""
    if len(value) != 16:
        raise ValueError(f"ATHENA UUID blobs must contain 16 bytes, got {len(value)}.")
    return uuid.UUID(bytes=value)

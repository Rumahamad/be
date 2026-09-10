"""Lossless deterministic JSON for BNC recovery artifacts."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from uuid import UUID

SCHEMA_VERSION = 1


def money_minor(value: Decimal) -> int:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Money must be a finite Decimal")
    minor = value * 100
    if minor != minor.to_integral_value():
        raise ValueError("Money contains fractions smaller than one paisa")
    return int(minor)


def normalize(value):
    if isinstance(value, Enum):
        return normalize(value.value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise ValueError("Binary floats are not supported in recovery artifacts")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal")
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Recovery timestamps must have a timezone")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Recovery object keys must be strings")
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    raise ValueError(f"Unsupported recovery value: {type(value).__name__}")


def canonical_bytes(value) -> bytes:
    return json.dumps(
        normalize(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def digest(content: bytes) -> str:
    return sha256(content).hexdigest()

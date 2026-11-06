"""Opaque random tokens (stored only as SHA-256 hashes) and time helpers."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime


def now_utc() -> datetime:
    return datetime.now(UTC)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)

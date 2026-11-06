"""Rate limits.

Two layers share one store:
- `limiter` (slowapi decorator) for sign-in, sign-up, password reset and the public feed/share links, keyed by IP.
- `GeneralLimit`: a cap on every API request per IP.
- `AiLimit`, `UploadLimit`, `SqlLimit` (in app.api.deps): tighter caps on costly actions per signed-in user, so
  people behind one shared IP (an office, a proxy) do not use up each other's allowance, and opening more
  sessions does not buy more.

The store is in memory, which is correct for a single backend process. Running several processes or servers
needs a shared store: set RATE_LIMIT_STORAGE_URI (for example redis://host:6379/0).
"""
from __future__ import annotations

from fastapi import Depends, Request
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.core.errors import AppError

limiter = Limiter(key_func=get_remote_address, headers_enabled=False,
                  storage_uri=get_settings().rate_limit_storage_uri or "memory://")


def ip_key(request: Request) -> str:
    return "ip:" + (get_remote_address(request) or "unknown")


def hit(scope: str, setting: str, key: str) -> None:
    """Counts one request for `key` in `scope`; answers 429 once `settings.<setting>` is used up."""
    if not limiter.enabled:
        return
    if not limiter.limiter.hit(parse(getattr(get_settings(), setting)), scope, key):
        raise AppError(429, "rate_limited", "Too many requests. Please wait a minute and try again.")


async def _general(request: Request) -> None:
    hit("api", "api_rate_limit", ip_key(request))


GeneralLimit = Depends(_general)

"""Shared request dependencies: current user, cross-site request check, ObjectId parsing."""
from __future__ import annotations

from urllib.parse import urlsplit

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, Request

from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.core.ratelimit import hit
from app.security.sessions import user_for_request

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
REQUEST_HEADER = "X-Requested-With"  # sent by the app's own API client on every request


def unauthorized(message: str = "Please sign in to continue") -> AppError:
    return AppError(401, "unauthorized", message)


def _origin_allowed(origin: str, request: Request) -> bool:
    s = get_settings()
    allowed = {o.rstrip("/") for o in [*s.cors_origin_list, s.frontend_url]}
    if origin.rstrip("/") in allowed:
        return True
    host = request.headers.get("host", "")
    return bool(host) and urlsplit(origin).netloc == host


async def require_csrf(request: Request) -> None:
    """Blocks requests that another website makes on the user's behalf (CSRF), without a token cookie.

    1. State-changing requests must carry the X-Requested-With header. A page on another site cannot add a custom
       header to a cross-site request without a CORS preflight, which this API only grants to its own origins.
    2. When the browser says where the request comes from (Origin, Sec-Fetch-Site), it must be this app.
    The session cookie is also SameSite=Lax, so it is not sent on cross-site form posts at all.
    """
    if request.method in SAFE_METHODS:
        return
    if not request.headers.get(REQUEST_HEADER):
        raise AppError(403, "csrf_failed", "This request was blocked because it did not come from the app. Refresh the page and try again.")
    origin = request.headers.get("origin")
    if origin and origin != "null":
        if not _origin_allowed(origin, request):
            raise AppError(403, "csrf_failed", "Requests from other websites are not allowed.")
    elif origin == "null" or request.headers.get("sec-fetch-site") == "cross-site":
        raise AppError(403, "csrf_failed", "Requests from other websites are not allowed.")


async def get_current_user(request: Request) -> dict:
    user = await user_for_request(request)
    if not user:
        raise unauthorized()
    return user


CurrentUser = Depends(get_current_user)
Csrf = Depends(require_csrf)


def _user_limit(scope: str, setting: str):
    async def check(user: dict = CurrentUser) -> None:
        hit(scope, setting, f"u:{user['_id']}")
    return Depends(check)


# Per-user caps on costly actions (limits are set in .env; see app.core.ratelimit).
AiLimit = _user_limit("ai", "ai_rate_limit")
UploadLimit = _user_limit("upload", "upload_rate_limit")
SqlLimit = _user_limit("sql", "sql_rate_limit")


def parse_oid(value: str, what: str = "Resource") -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise not_found(what)

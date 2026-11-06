"""Server-side sessions behind a single opaque cookie.

The browser holds one HttpOnly cookie (`sid`) with a random value. It carries no user data and cannot be read
by page scripts. The server stores only its SHA-256 hash, with the user, an idle expiry (extended while the
session is used) and an absolute expiry. Logging out, changing or resetting the password, or deleting the
account ends sessions on the server immediately.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import Request, Response

from app.core.config import get_settings
from app.db.mongo import get_db
from app.security.tokens import now_utc, random_token, sha256_hex

SESSION_COOKIE = "sid"
TOUCH_EVERY = timedelta(minutes=10)  # how often the idle expiry is pushed forward while the session is used


def _cookie_args() -> dict:
    s = get_settings()
    return {"httponly": True, "secure": s.secure_cookies, "samesite": "lax", "path": "/"}


async def start_session(response: Response, user: dict, request: Request | None = None) -> None:
    """A fresh random session for this browser (a new ID at every sign-in prevents session fixation)."""
    s = get_settings()
    now = now_utc()
    raw = random_token(32)
    await get_db().sessions.insert_one({
        "token_hash": sha256_hex(raw), "user_id": user["_id"], "created_at": now, "last_seen_at": now,
        "expires_at": now + timedelta(days=s.session_idle_days),
        "absolute_expires_at": now + timedelta(days=s.session_max_days),
        "revoked_at": None,
        "user_agent": (request.headers.get("user-agent", "")[:200] if request else ""),
    })
    response.set_cookie(SESSION_COOKIE, raw, max_age=s.session_max_days * 86400, **_cookie_args())


async def user_for_request(request: Request) -> dict | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw or len(raw) > 200:
        return None
    db = get_db()
    now = now_utc()
    doc = await db.sessions.find_one({"token_hash": sha256_hex(raw), "revoked_at": None,
                                      "expires_at": {"$gt": now}, "absolute_expires_at": {"$gt": now}})
    if not doc:
        return None
    user = await db.users.find_one({"_id": doc["user_id"]})
    if not user:
        return None
    if now - doc["last_seen_at"] > TOUCH_EVERY:
        idle = now + timedelta(days=get_settings().session_idle_days)
        await db.sessions.update_one({"_id": doc["_id"]}, {"$set": {"last_seen_at": now, "expires_at": idle}})
    return user


async def end_session(request: Request, response: Response) -> None:
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        await get_db().sessions.update_one({"token_hash": sha256_hex(raw), "revoked_at": None}, {"$set": {"revoked_at": now_utc()}})
    clear_session_cookie(response)


async def end_all_sessions(user_id) -> None:
    await get_db().sessions.update_many({"user_id": user_id, "revoked_at": None}, {"$set": {"revoked_at": now_utc()}})


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, **_cookie_args())

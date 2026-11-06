"""Authentication: signup, signin, logout, password reset, account settings (server-side sessions)."""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Request, Response
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.api.deps import Csrf, CurrentUser
from app.core.config import get_settings
from app.core.errors import AppError, bad_request
from app.core.ratelimit import limiter
from app.db.mongo import get_db
from app.schemas.auth import (ChangePasswordIn, DeleteMeIn, ForgotIn, ResetIn, SigninIn, SignupIn, UpdateMeIn,
                              normalize_email, public_user)
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.sessions import clear_session_cookie, end_all_sessions, end_session, start_session
from app.security.tokens import now_utc, random_token, sha256_hex
from app.services.email import get_email_sender
from app.services.user_data import delete_user_everything

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("app.auth")

GENERIC_SIGNIN_ERROR = "Invalid email or password"
EMAIL_FAIL_WINDOW = timedelta(minutes=15)
EMAIL_FAIL_MAX = 5


def _signin_limit() -> str:
    return get_settings().signin_rate_limit


def _signup_limit() -> str:
    return get_settings().signup_rate_limit


@router.post("/signup", status_code=201, dependencies=[Csrf])
@limiter.limit(_signup_limit)
async def signup(request: Request, body: SignupIn, response: Response):
    email = normalize_email(body.email)
    # Hash first so new and existing emails take similar time.
    pw_hash = hash_password(body.password)
    user = {
        "full_name": body.full_name,
        "email": email,
        "password_hash": pw_hash,
        "email_verified": False,
        "ai_provider": None,
        "allow_ai_samples": False,
        "created_at": now_utc(),
    }
    try:
        res = await get_db().users.insert_one(user)
    except DuplicateKeyError:
        raise AppError(409, "email_taken", "This email is already registered. Sign in instead, or reset your password.")
    user["_id"] = res.inserted_id
    await start_session(response, user, request)
    return {"user": public_user(user)}


@router.post("/signin", dependencies=[Csrf])
@limiter.limit(_signin_limit)
async def signin(request: Request, body: SigninIn, response: Response):
    db = get_db()
    email = normalize_email(body.email)
    key = f"email:{sha256_hex(email)}"
    recent = await db.login_attempts.count_documents({"key": key, "created_at": {"$gt": now_utc() - EMAIL_FAIL_WINDOW}})
    if recent >= EMAIL_FAIL_MAX:
        raise AppError(429, "rate_limited", "Too many failed attempts. Please wait 15 minutes or reset your password.")
    user = await db.users.find_one({"email": email})
    ok = verify_password(user["password_hash"] if user else None, body.password)
    if not user or not ok:
        await db.login_attempts.insert_one({"key": key, "created_at": now_utc()})
        raise AppError(401, "invalid_credentials", GENERIC_SIGNIN_ERROR)
    await db.login_attempts.delete_many({"key": key})
    if needs_rehash(user["password_hash"]):
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_password(body.password)}})
    await start_session(response, user, request)
    return {"user": public_user(user)}


@router.post("/logout", dependencies=[Csrf])
async def logout(request: Request, response: Response):
    await end_session(request, response)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = CurrentUser):
    return {"user": public_user(user)}


@router.patch("/me", dependencies=[Csrf])
async def update_me(body: UpdateMeIn, user: dict = CurrentUser):
    update: dict = {}
    if body.full_name is not None:
        name = " ".join(body.full_name.split())
        if not name:
            raise bad_request("Name is required")
        update["full_name"] = name
    if body.clear_ai_provider:
        update["ai_provider"] = None
    elif body.ai_provider is not None:
        if body.ai_provider not in get_settings().configured_ai_providers():
            raise bad_request("That AI provider is not configured on this server", "provider_not_configured")
        update["ai_provider"] = body.ai_provider
    if body.allow_ai_samples is not None:
        update["allow_ai_samples"] = body.allow_ai_samples
    if update:
        user = await get_db().users.find_one_and_update({"_id": user["_id"]}, {"$set": update},
                                                        return_document=ReturnDocument.AFTER)
    return {"user": public_user(user)}


@router.post("/change-password", dependencies=[Csrf])
async def change_password(body: ChangePasswordIn, request: Request, response: Response, user: dict = CurrentUser):
    if not verify_password(user["password_hash"], body.current_password):
        raise AppError(400, "wrong_password", "Current password is incorrect")
    user = await get_db().users.find_one_and_update(
        {"_id": user["_id"]},
        {"$set": {"password_hash": hash_password(body.new_password)}},
        return_document=ReturnDocument.AFTER)
    await end_all_sessions(user["_id"])
    await start_session(response, user, request)  # keep this browser signed in; every other session ends
    return {"ok": True}


@router.delete("/me", dependencies=[Csrf])
async def delete_me(body: DeleteMeIn, response: Response, user: dict = CurrentUser):
    if not verify_password(user["password_hash"], body.password):
        raise AppError(400, "wrong_password", "Password is incorrect")
    await delete_user_everything(user["_id"])
    clear_session_cookie(response)
    return {"ok": True}


def forgot_response() -> dict:
    """Same answer whether or not the account exists. It does say whether this server can send email at all."""
    s = get_settings()
    if s.smtp_configured:
        return {"message": "If an account exists for that email, we've sent a link to reset the password.", "email": "smtp"}
    if s.app_env in ("development", "test"):
        return {"message": "Email is not set up on this server, so nothing was sent. In development the reset link is printed in the backend console.",
                "email": "console"}
    return {"message": "Email is not set up on this server, so no reset link can be sent. Ask the administrator to configure SMTP.", "email": "off"}


async def _send_reset(email: str, link: str) -> None:
    try:
        await get_email_sender().send(
            email, "Reset your AI Data Analyst password",
            f"Use this link to reset your password. It expires in {get_settings().password_reset_minutes} minutes "
            f"and can be used once.\n\n{link}\n\nIf you did not ask for this, you can ignore this email.")
    except Exception:  # noqa: BLE001 - never leak delivery errors to the client
        log.exception("Failed to send password reset email")


@router.post("/forgot-password", dependencies=[Csrf])
@limiter.limit(_signup_limit)
async def forgot_password(request: Request, body: ForgotIn, background: BackgroundTasks):
    s = get_settings()
    user = await get_db().users.find_one({"email": normalize_email(body.email)})
    if user:
        token = random_token(32)
        await get_db().password_resets.insert_one({
            "user_id": user["_id"], "token_hash": sha256_hex(token),
            "expires_at": now_utc() + timedelta(minutes=s.password_reset_minutes), "used_at": None,
            "created_at": now_utc()})
        background.add_task(_send_reset, user["email"], f"{s.frontend_url}/reset-password?token={token}")
    return forgot_response()


@router.post("/reset-password", dependencies=[Csrf])
@limiter.limit(_signup_limit)
async def reset_password(request: Request, body: ResetIn):
    db = get_db()
    now = now_utc()
    doc = await db.password_resets.find_one_and_update(
        {"token_hash": sha256_hex(body.token), "used_at": None, "expires_at": {"$gt": now}},
        {"$set": {"used_at": now}})
    if not doc:
        raise AppError(400, "invalid_token", "This reset link is invalid or has expired. Request a new one.")
    await db.users.update_one({"_id": doc["user_id"]},
                              {"$set": {"password_hash": hash_password(body.password)}})
    await end_all_sessions(doc["user_id"])
    return {"message": "Password updated. You can now sign in."}

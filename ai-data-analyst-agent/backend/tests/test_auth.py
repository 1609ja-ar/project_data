from datetime import timedelta

from app.security.tokens import now_utc, sha256_hex
from tests.conftest import PASSWORD, signup


async def test_signup_creates_user_with_argon2_hash_never_returned(client, db):
    r = await client.post("/api/auth/signup",
                          json={"full_name": "  Ana   Analyst ", "email": " Ana@Example.COM ", "password": PASSWORD})
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == "ana@example.com"
    assert body["user"]["full_name"] == "Ana Analyst"
    assert "password" not in r.text and "hash" not in r.text and "$argon2" not in r.text
    doc = await db.users.find_one({"email": "ana@example.com"})
    assert doc["password_hash"].startswith("$argon2id$")
    assert doc["email_verified"] is False
    assert doc["allow_ai_samples"] is False
    # Exactly one cookie: an opaque, HttpOnly session ID (no JWT, no CSRF token, no refresh token)
    cookies = r.headers.get_list("set-cookie")
    assert len(cookies) == 1 and cookies[0].startswith("sid=")
    assert "HttpOnly" in cookies[0] and "SameSite=lax" in cookies[0] and "Path=/" in cookies[0]
    sid = client.cookies.get("sid")
    assert sid and "." not in sid  # not a JWT: nothing to decode
    session = await db.sessions.find_one({})
    assert session["token_hash"] == sha256_hex(sid) and await db.sessions.find_one({"token_hash": sid}) is None


async def test_duplicate_email_rejected(client):
    await signup(client)
    r = await client.post("/api/auth/signup",
                          json={"full_name": "X", "email": "ANA@example.com", "password": PASSWORD})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


async def test_weak_password_rejected(client):
    r = await client.post("/api/auth/signup", json={"full_name": "X", "email": "x@example.com", "password": "short"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_signin_and_me(client):
    await signup(client)
    client.cookies.clear()
    r = await client.post("/api/auth/signin", json={"email": "ana@example.com", "password": PASSWORD})
    assert r.status_code == 200
    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "ana@example.com"


async def test_wrong_credentials_are_generic(client):
    await signup(client)
    r1 = await client.post("/api/auth/signin", json={"email": "ana@example.com", "password": "Wrong-pass-1"})
    r2 = await client.post("/api/auth/signin", json={"email": "nobody@example.com", "password": "Wrong-pass-1"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["error"]["message"] == r2.json()["error"]["message"] == "Invalid email or password"


async def test_per_email_lockout(client):
    await signup(client)
    for _ in range(5):
        await client.post("/api/auth/signin", json={"email": "ana@example.com", "password": "Wrong-pass-1"})
    r = await client.post("/api/auth/signin", json={"email": "ana@example.com", "password": PASSWORD})
    assert r.status_code == 429


async def test_protected_route_requires_cookie(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_cross_site_requests_are_blocked(client):
    await signup(client)
    ok = await client.patch("/api/auth/me", json={"full_name": "New"})
    assert ok.status_code == 200
    # Without the app's header (a plain cross-site form post would look like this)
    r = await client.patch("/api/auth/me", json={"full_name": "X"}, headers={"X-Requested-With": ""})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    # From another website
    r = await client.patch("/api/auth/me", json={"full_name": "X"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = await client.patch("/api/auth/me", json={"full_name": "X"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    # From the app's own origin (as the browser sends it through the dev proxy)
    r = await client.patch("/api/auth/me", json={"full_name": "Y"}, headers={"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200
    # Reading data is never blocked by this check
    assert (await client.get("/api/auth/me", headers={"X-Requested-With": ""})).status_code == 200


async def test_logout_ends_the_session_on_the_server(client, db):
    await signup(client)
    sid = client.cookies.get("sid")
    r = await client.post("/api/auth/logout")
    assert r.status_code == 200
    doc = await db.sessions.find_one({"token_hash": sha256_hex(sid)})
    assert doc["revoked_at"] is not None
    # Even if someone kept a copy of the cookie, it no longer works.
    client.cookies.set("sid", sid, domain="testserver.local")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_sessions_expire_when_idle_or_too_old(client, db):
    await signup(client)
    assert (await client.get("/api/auth/me")).status_code == 200
    await db.sessions.update_many({}, {"$set": {"expires_at": now_utc() - timedelta(seconds=1)}})
    assert (await client.get("/api/auth/me")).status_code == 401
    await db.sessions.update_many({}, {"$set": {"expires_at": now_utc() + timedelta(days=1), "absolute_expires_at": now_utc() - timedelta(seconds=1)}})
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_new_session_id_at_every_sign_in(client, db):
    await signup(client)
    first = client.cookies.get("sid")
    await client.post("/api/auth/signin", json={"email": "ana@example.com", "password": PASSWORD})
    assert client.cookies.get("sid") != first
    assert await db.sessions.count_documents({}) == 2


async def test_password_reset_single_use_and_expiry(client, db):
    from app.security.tokens import random_token
    user = await signup(client)
    r = await client.post("/api/auth/forgot-password", json={"email": "ana@example.com"})
    r_unknown = await client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert r.json() == r_unknown.json()
    assert r.json()["email"] == "console"  # no SMTP in the test setup: the answer must not claim an email was sent
    assert "not set up" in r.json()["message"] and "token" not in r.text
    assert await db.password_resets.count_documents({}) == 1

    # Plant a known token (the real one is only emailed/logged, never returned).
    from bson import ObjectId
    token = random_token(32)
    await db.password_resets.insert_one({"user_id": ObjectId(user["id"]), "token_hash": sha256_hex(token),
                                         "expires_at": now_utc() + timedelta(minutes=30), "used_at": None})
    r = await client.post("/api/auth/reset-password", json={"token": token, "password": "Brand-new-pw-9"})
    assert r.status_code == 200
    # Every session of the user ends
    assert await db.sessions.count_documents({"revoked_at": None}) == 0
    assert (await client.get("/api/auth/me")).status_code == 401
    # Single use
    r = await client.post("/api/auth/reset-password", json={"token": token, "password": "Another-pw-99"})
    assert r.status_code == 400
    # Expired
    expired = random_token(32)
    await db.password_resets.insert_one({"user_id": ObjectId(user["id"]), "token_hash": sha256_hex(expired),
                                         "expires_at": now_utc() - timedelta(minutes=1), "used_at": None})
    r = await client.post("/api/auth/reset-password", json={"token": expired, "password": "Another-pw-99"})
    assert r.status_code == 400
    # New password works
    r = await client.post("/api/auth/signin", json={"email": "ana@example.com", "password": "Brand-new-pw-9"})
    assert r.status_code == 200


async def test_update_me_rejects_unconfigured_provider(auth_client):
    r = await auth_client.patch("/api/auth/me", json={"full_name": "Ana B", "allow_ai_samples": True})
    assert r.status_code == 200
    assert r.json()["user"]["full_name"] == "Ana B" and r.json()["user"]["allow_ai_samples"] is True
    r = await auth_client.patch("/api/auth/me", json={"ai_provider": "groq"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "provider_not_configured"


async def test_change_password_ends_other_sessions(auth_client, other_client, db):
    r = await auth_client.post("/api/auth/change-password",
                               json={"current_password": "wrong-pw-1", "new_password": "Next-pass-123"})
    assert r.status_code == 400
    r = await auth_client.post("/api/auth/change-password",
                               json={"current_password": PASSWORD, "new_password": "Next-pass-123"})
    assert r.status_code == 200
    assert (await auth_client.get("/api/auth/me")).status_code == 200  # this browser stays signed in
    assert await db.sessions.count_documents({"revoked_at": None}) == 2  # this browser's new session + Bob's
    assert (await other_client.get("/api/auth/me")).status_code == 200  # another user is not affected


async def test_delete_account(auth_client, db):
    r = await auth_client.request("DELETE", "/api/auth/me", json={"password": "wrong-pw-1"})
    assert r.status_code == 400
    r = await auth_client.request("DELETE", "/api/auth/me", json={"password": PASSWORD})
    assert r.status_code == 200
    assert await db.users.count_documents({}) == 0
    assert await db.sessions.count_documents({}) == 0


async def test_old_token_cookies_are_removed(client):
    await signup(client)
    client.cookies.set("access_token", "old.jwt.value", domain="testserver.local")
    client.cookies.set("csrf_token", "old", domain="testserver.local")
    r = await client.get("/api/auth/me")
    assert r.status_code == 200  # the session cookie still works; the old ones are ignored
    deleted = [c.split("=")[0] for c in r.headers.get_list("set-cookie") if "Max-Age=0" in c or "expires=Thu, 01 Jan 1970" in c]
    assert {"access_token", "csrf_token"} <= set(deleted)

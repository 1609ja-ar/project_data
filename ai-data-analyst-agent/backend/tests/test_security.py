"""Rate limits, security headers, host checks and the production settings guard."""
import httpx
import pytest

from app.core.config import Settings, get_settings
from app.core.ratelimit import limiter
from app.main import create_app
from tests.conftest import APP_HEADERS

CSV = "region,amount\nNorth,10\nSouth,20\n"
SAFE_PROD = dict(
    _env_file=None, app_env="production", frontend_url="https://app.example.com", cors_origins="https://app.example.com",
    allowed_hosts="api.example.com", mongodb_uri="mongodb+srv://app_user:not-a-real-password@cluster0.example.net/",  # gitleaks:allow (fake test value)
)


@pytest.fixture
def limits(monkeypatch):
    """Lets a test lower one limit; counters are cleared before and after."""
    limiter.reset()
    s = get_settings()

    def set_limit(name, value):
        monkeypatch.setattr(s, name, value)

    yield set_limit
    limiter.reset()


async def _upload(c):
    return await c.post("/api/datasets/upload", files={"file": ("t.csv", CSV.encode(), "text/csv")})


async def test_security_headers_on_every_response(client):
    for r in (await client.get("/api/health"), await client.get("/api/auth/me"), await client.get("/api/nope")):
        h = r.headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["cache-control"] == "no-store"
        assert "server" not in h
        assert "strict-transport-security" not in h  # HTTPS-only header is for production


async def test_general_limit_per_ip(client, limits):
    limits("api_rate_limit", "3/minute")
    codes = [(await client.get("/api/health")).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert (await client.get("/api/health")).json()["error"]["code"] == "rate_limited"


async def test_upload_limit_is_per_user(auth_client, other_client, limits):
    limits("upload_rate_limit", "2/minute")
    assert [(await _upload(auth_client)).status_code for _ in range(3)] == [201, 201, 429]
    assert (await _upload(other_client)).status_code == 201  # a different user has their own allowance


async def test_upload_limit_not_reset_by_new_session(auth_client, limits):
    limits("upload_rate_limit", "1/minute")
    assert (await _upload(auth_client)).status_code == 201
    r = await auth_client.post("/api/auth/signin", json={"email": "ana@example.com", "password": "Sup3r-secret-pw"})
    assert r.status_code == 200
    assert (await _upload(auth_client)).status_code == 429


async def test_ai_limit(auth_client, limits):
    limits("ai_rate_limit", "2/minute")
    body = {"question": "total amount by region", "dataset_id": "0" * 24}
    codes = [(await auth_client.post("/api/ai/sql/generate", json=body)).status_code for _ in range(3)]
    assert codes[2] == 429 and 429 not in codes[:2]


async def test_costly_limit_needs_sign_in_first(client, limits):
    limits("upload_rate_limit", "1/minute")
    client.cookies.set("sid", "made-up")
    assert [(await _upload(client)).status_code for _ in range(3)] == [401, 401, 401]


async def test_reset_password_is_rate_limited(client, limits):
    limits("signup_rate_limit", "2/minute")
    body = {"token": "x" * 40, "password": "An0ther-long-pass"}
    codes = [(await client.post("/api/auth/reset-password", json=body)).status_code for _ in range(3)]
    assert codes[2] == 429 and 429 not in codes[:2]


def test_production_guard_accepts_safe_settings():
    assert Settings(**SAFE_PROD).production_problems() == []


@pytest.mark.parametrize("change, fragment", [
    ({"cors_origins": "*"}, "not '*'"),
    ({"cors_origins": "http://app.example.com"}, "https://"),
    ({"frontend_url": "http://app.example.com"}, "FRONTEND_URL"),
    ({"cookie_secure": False}, "COOKIE_SECURE"),
    ({"allowed_hosts": ""}, "ALLOWED_HOSTS"),
    ({"mongodb_uri": "mongodb+srv://cluster0.example.net/"}, "username/password"),
    ({"mongodb_uri": "mongodb://u:p@db.example.net:27017/"}, "TLS"),  # gitleaks:allow (fake test value)
])
def test_production_guard_rejects_unsafe_settings(change, fragment):
    problems = Settings(**{**SAFE_PROD, **change}).production_problems()
    assert any(fragment in p for p in problems), problems


def test_local_database_with_login_needs_no_tls():
    s = Settings(**{**SAFE_PROD, "mongodb_uri": "mongodb://app_user:pw@localhost:27017/"})  # gitleaks:allow (fake test value)
    assert s.production_problems() == []


def test_development_has_no_production_guard():
    assert Settings(_env_file=None, app_env="development", cors_origins="*").production_problems() == []


def test_server_refuses_to_start_with_unsafe_production_settings(monkeypatch):
    monkeypatch.setattr("app.main.get_settings", lambda: Settings(**{**SAFE_PROD, "cors_origins": "*"}))
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        create_app()


async def test_production_app_hides_docs_checks_host_and_sends_hsts(monkeypatch):
    monkeypatch.setattr("app.main.get_settings", lambda: Settings(**SAFE_PROD))
    prod = create_app()
    assert prod.openapi_url is None and prod.docs_url is None and prod.redoc_url is None
    transport = httpx.ASGITransport(app=prod)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.example.com", headers=APP_HEADERS) as c:
        r = await c.get("/api/openapi.json")
        assert r.status_code == 404
        assert r.headers["strict-transport-security"].startswith("max-age=31536000")
    async with httpx.AsyncClient(transport=transport, base_url="https://evil.example.org", headers=APP_HEADERS) as c:
        assert (await c.get("/api/health")).status_code == 400


async def test_excel_has_its_own_smaller_size_limit(auth_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_excel_mb", 1)
    big = b"x" * (1024 * 1024 + 1)
    r = await auth_client.post("/api/datasets/upload", files={"file": ("big.xlsx", big, "application/vnd.ms-excel")})
    assert r.status_code == 413 and "save it as CSV" in r.json()["error"]["message"]
    csv = b"region,amount\n" + b"North,10\n" * 120_000  # same size range as CSV: allowed
    assert len(csv) > 1024 * 1024
    assert (await auth_client.post("/api/datasets/upload", files={"file": ("big.csv", csv, "text/csv")})).status_code == 201


def test_default_limits_match_what_was_tested():
    s = Settings(_env_file=None)
    assert (s.max_upload_mb, s.max_excel_mb, s.max_rows) == (150, 40, 3_000_000)

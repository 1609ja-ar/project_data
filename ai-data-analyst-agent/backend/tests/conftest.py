import os
import tempfile

# Configure the app for tests before anything imports settings.
_TMP = tempfile.mkdtemp(prefix="ada-test-storage-")
os.environ.update({
    "APP_ENV": "test",
    "MONGODB_URI": os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017"),
    "MONGODB_DB": "ai_data_analyst_test",
    "STORAGE_DIR": _TMP,
    "SIGNIN_RATE_LIMIT": "1000/minute",
    "SIGNUP_RATE_LIMIT": "1000/minute",
    "FEED_RATE_LIMIT": "1000/minute",
    "API_RATE_LIMIT": "100000/minute",
    "AI_RATE_LIMIT": "1000/minute",
    "UPLOAD_RATE_LIMIT": "1000/minute",
    "SQL_RATE_LIMIT": "1000/minute",
    "GROQ_API_KEY": "",
    "XAI_API_KEY": "",
    "SMTP_HOST": "",
    "CLEANING_EXECUTOR": "thread",
})

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.db import mongo  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "Sup3r-secret-pw"


def pytest_collection_modifyitems(session, config, items):
    """Stops at once, with one clear message, when tests need MongoDB and it is not reachable.
    Without this every database test waits 5 s and fails with the same error (about 10 minutes in total)."""
    if not any("db" in getattr(item, "fixturenames", ()) for item in items):
        return
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    uri = os.environ["MONGODB_URI"]
    try:
        with MongoClient(uri, serverSelectionTimeoutMS=5000) as c:
            c.admin.command("ping")
    except PyMongoError as e:
        pytest.exit(f"MongoDB is not reachable at {uri.split('@')[-1]} ({type(e).__name__}). Start MongoDB, or set "
                    "MONGODB_URI to a running server, then run the tests again.", returncode=3)


@pytest_asyncio.fixture
async def db():
    database = await mongo.connect("ai_data_analyst_test")
    for name in await database.list_collection_names():
        await database[name].delete_many({})
    yield database
    await mongo.close()


APP_HEADERS = {"X-Requested-With": "fetch"}  # what the app's own API client sends


@pytest_asyncio.fixture
async def client(db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=APP_HEADERS) as c:
        yield c


async def signup(c: httpx.AsyncClient, email="ana@example.com", name="Ana Analyst", password=PASSWORD):
    r = await c.post("/api/auth/signup", json={"full_name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()["user"]


@pytest_asyncio.fixture
async def auth_client(client):
    await signup(client)
    return client


@pytest_asyncio.fixture
async def other_client(db):
    """A second, independent signed-in user."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=APP_HEADERS) as c:
        await signup(c, email="bob@example.com", name="Bob Other")
        yield c

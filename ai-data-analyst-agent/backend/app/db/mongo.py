"""MongoDB access via PyMongo's native async API (AsyncMongoClient)."""
from __future__ import annotations

import logging

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import get_settings

log = logging.getLogger("app.db")

_client: AsyncMongoClient | None = None
_db: AsyncDatabase | None = None


async def connect(db_name: str | None = None) -> AsyncDatabase:
    global _client, _db
    s = get_settings()
    _client = AsyncMongoClient(s.mongodb_uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    _db = _client[db_name or s.mongodb_db]
    await ensure_indexes(_db)
    return _db


async def close() -> None:
    global _client, _db
    if _client is not None:
        await _client.close()
    _client, _db = None, None


def get_db() -> AsyncDatabase:
    if _db is None:
        raise RuntimeError("Database not connected")
    return _db


async def ping() -> bool:
    try:
        await get_db().command("ping")
        return True
    except Exception:  # noqa: BLE001 - health check reports status only
        return False


async def ensure_indexes(db: AsyncDatabase) -> None:
    await db.users.create_index([("email", ASCENDING)], unique=True)
    await db.datasets.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.dataset_versions.create_index([("dataset_id", ASCENDING), ("version_number", ASCENDING)], unique=True)
    await db.analyses.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.analyses.create_index([("dataset_id", ASCENDING), ("version_id", ASCENDING), ("analysis_type", ASCENDING)])
    await db.reports.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.conversations.create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])
    await db.messages.create_index([("conversation_id", ASCENDING), ("created_at", ASCENDING)])
    await db.password_resets.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
    await db.password_resets.create_index([("token_hash", ASCENDING)], unique=True)
    await db.login_attempts.create_index([("created_at", ASCENDING)], expireAfterSeconds=3600)
    await db.login_attempts.create_index([("key", ASCENDING), ("created_at", DESCENDING)])
    await db.sessions.create_index([("token_hash", ASCENDING)], unique=True)
    await db.sessions.create_index([("user_id", ASCENDING)])
    await db.sessions.create_index([("absolute_expires_at", ASCENDING)], expireAfterSeconds=0)
    await db.saved_queries.create_index([("user_id", ASCENDING), ("dataset_id", ASCENDING)])
    await db.dashboards.create_index([("user_id", ASCENDING), ("dataset_id", ASCENDING)])
    await db.export_tokens.create_index([("token_hash", ASCENDING)], unique=True)
    await db.export_tokens.create_index([("user_id", ASCENDING)])
    await db.share_links.create_index([("token_hash", ASCENDING)], unique=True)
    await db.share_links.create_index([("user_id", ASCENDING), ("dataset_id", ASCENDING)])

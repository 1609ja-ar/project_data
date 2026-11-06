"""Deleting all data owned by a user (account deletion)."""
from __future__ import annotations

from bson import ObjectId

from app.db.mongo import get_db
from app.services.storage import get_storage

USER_COLLECTIONS = ("datasets", "dataset_versions", "analyses", "reports", "conversations", "messages",
                    "password_resets", "sessions", "refresh_tokens", "saved_queries", "dashboards", "export_tokens", "share_links")


async def delete_user_everything(user_id: ObjectId) -> None:
    db = get_db()
    for name in USER_COLLECTIONS:
        await db[name].delete_many({"user_id": user_id})
    get_storage().delete_user(str(user_id))
    await db.users.delete_one({"_id": user_id})

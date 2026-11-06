"""Read-only share links: a frozen snapshot of a dashboard view, reachable without signing in until it
expires or is revoked. Only the snapshot (aggregated figures and charts) is exposed, never rows."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.analytics import DashboardFilterIn, ISO_DATE, _context, _pinned
from app.api.deps import Csrf, CurrentUser, parse_oid
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.core.ratelimit import limiter
from app.db.mongo import get_db
from app.security.tokens import now_utc, random_token, sha256_hex
from app.services import datasets as svc
from app.services import jobs

router = APIRouter(tags=["share"])
MAX_LINKS = 20


class ShareIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    expires_in_days: int = Field(default=7, ge=1, le=30)
    date_from: str | None = Field(default=None, pattern=ISO_DATE)
    date_to: str | None = Field(default=None, pattern=ISO_DATE)
    filters: list[DashboardFilterIn] = Field(default_factory=list, max_length=6)


def _public(s: dict) -> dict:
    return {"id": str(s["_id"]), "title": s["title"], "token_prefix": s["token_prefix"], "created_at": s["created_at"].isoformat(),
            "expires_at": s["expires_at"].isoformat(), "views": s.get("views", 0), "filters": s.get("filters_text", []),
            "status": "revoked" if s.get("revoked_at") else "expired" if s["expires_at"] <= now_utc() else "active"}


def _strip(dash: dict) -> dict:
    """What a viewer gets: figures and charts, without internal query details."""
    def clean(t):
        t = {k: v for k, v in t.items() if k not in ("how_calculated", "plan")}
        return t
    return {"kpis": [{k: v for k, v in kp.items() if k != "how_calculated"} for kp in dash["kpis"]],
            "tiles": [clean(t) for t in dash["tiles"]], "custom_tiles": [clean(t) for t in dash.get("custom_tiles", [])],
            "dimensions": [{"key": x["key"], "label": x["label"], "values": x["values"][:20]} for x in dash["dimensions"]],
            "rows_in_view": dash["rows_in_view"], "row_count": dash["row_count"], "view_bounds": dash.get("view_bounds"),
            "dataset_version": dash["dataset_version"], "filters_applied": dash.get("filters_applied", [])}


@router.post("/analytics/{dataset_id}/share", status_code=201, dependencies=[Csrf])
async def create_share(dataset_id: str, body: ShareIn, user: dict = CurrentUser):
    d, v = await _context(user, dataset_id, None)
    db = get_db()
    if await db.share_links.count_documents({"user_id": user["_id"], "revoked_at": None, "expires_at": {"$gt": now_utc()}}) >= MAX_LINKS:
        raise AppError(400, "too_many", f"You can have up to {MAX_LINKS} active share links. Revoke one first.")
    opts = {"date_from": body.date_from, "date_to": body.date_to, "filters": [f.model_dump() for f in body.filters]}
    try:
        out = await jobs.run_limited("analytics", get_settings().query_timeout_seconds * 3, jobs.dashboard_job,
                                     str(svc.storage_path(v["storage_ref"])), v, d, opts, await _pinned(user, d))
    except jobs.JobTimeout:
        raise AppError(504, "timeout", "Building the snapshot took too long.")
    if "error" in out:
        raise AppError(422, "invalid_options", out["error"])
    token = "shr_" + random_token(24)
    doc = {"user_id": user["_id"], "dataset_id": d["_id"], "title": (body.title or "").strip() or d["filename"].rsplit(".", 1)[0],
           "dataset_name": d["filename"], "token_hash": sha256_hex(token), "token_prefix": token[:8],
           "snapshot": _strip(out["ok"]), "filters_text": out["ok"].get("filters_applied", []),
           "created_at": now_utc(), "expires_at": now_utc() + timedelta(days=body.expires_in_days), "revoked_at": None, "views": 0}
    doc["_id"] = (await db.share_links.insert_one(doc)).inserted_id
    return {**_public(doc), "path": f"/s/{token}"}


@router.get("/analytics/{dataset_id}/share")
async def list_shares(dataset_id: str, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    docs = await get_db().share_links.find({"user_id": user["_id"], "dataset_id": d["_id"]}, {"snapshot": 0}) \
        .sort("created_at", -1).to_list(50)
    return {"items": [_public(s) for s in docs]}


@router.delete("/share-links/{link_id}", dependencies=[Csrf])
async def revoke_share(link_id: str, user: dict = CurrentUser):
    res = await get_db().share_links.update_one({"_id": parse_oid(link_id, "Link"), "user_id": user["_id"], "revoked_at": None},
                                                {"$set": {"revoked_at": now_utc()}})
    if not res.matched_count:
        raise not_found("Share link")
    return {"ok": True}


def _share_limit() -> str:
    return get_settings().feed_rate_limit


@router.get("/public/share/{token}")
@limiter.limit(_share_limit)
async def view_share(request: Request, token: str):
    if not token.startswith("shr_") or len(token) > 80:
        raise not_found("Share link")
    db = get_db()
    s = await db.share_links.find_one({"token_hash": sha256_hex(token)})
    if not s or s.get("revoked_at") or s["expires_at"] <= now_utc():
        raise AppError(404, "not_found", "This link has expired or was revoked.")
    await db.share_links.update_one({"_id": s["_id"]}, {"$inc": {"views": 1}})
    return {"title": s["title"], "dataset_name": s["dataset_name"], "created_at": s["created_at"].isoformat(),
            "expires_at": s["expires_at"].isoformat(), "filters": s.get("filters_text", []), "snapshot": s["snapshot"]}

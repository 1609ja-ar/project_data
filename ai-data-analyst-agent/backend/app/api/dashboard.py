"""Overview page summary: real counts from the user's own data."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.db.mongo import get_db
from app.schemas.common import analysis_public, dataset_public

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def summary(user: dict = CurrentUser):
    db = get_db()
    uid = user["_id"]
    agg = await (await db.datasets.aggregate([
        {"$match": {"user_id": uid}},
        {"$group": {"_id": None, "n": {"$sum": 1}, "rows": {"$sum": {"$ifNull": ["$row_count", 0]}}}},
    ])).to_list(1)
    totals = agg[0] if agg else {"n": 0, "rows": 0}
    recent_ds = await db.datasets.find({"user_id": uid}).sort("created_at", -1).limit(5).to_list(5)
    recent_an = await db.analyses.find({"user_id": uid}).sort("created_at", -1).limit(5).to_list(5)

    findings: dict | None = None
    focus = next((d for d in recent_ds if d.get("active_version_id")), None)
    if focus:
        cached = await db.analyses.find_one(
            {"user_id": uid, "dataset_id": focus["_id"], "version_id": focus["active_version_id"],
             "analysis_type": "insights"}, sort=[("created_at", -1)])
        findings = {
            "dataset_id": str(focus["_id"]),
            "dataset_name": focus["filename"],
            "insights": (cached or {}).get("result_summary", {}).get("insights", [])[:3] if cached else None,
        }

    return {
        "total_datasets": totals["n"],
        "total_rows": totals["rows"],
        "completed_analyses": await db.analyses.count_documents({"user_id": uid}),
        "generated_reports": await db.reports.count_documents({"user_id": uid}),
        "recent_datasets": [dataset_public(d) for d in recent_ds],
        "recent_analyses": [analysis_public(a) for a in recent_an],
        "important_findings": findings,
    }

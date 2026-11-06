"""Data reports: generate (verified facts + AI or template narrative), list, read, delete."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.analytics import ISO_DATE, DashboardFilterIn
from app.api.deps import Csrf, CurrentUser, parse_oid
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.db.mongo import get_db
from app.security.tokens import now_utc
from app.services import datasets as svc
from app.services import jobs
from app.services import reports as rep

router = APIRouter(prefix="/reports", tags=["reports"])

Section = Literal["summary", "kpis", "charts", "insights", "quality", "columns"]


class ReportIn(BaseModel):
    dataset_id: str
    title: str | None = Field(default=None, max_length=200)
    use_ai: bool = True
    sections: list[Section] = Field(default_factory=lambda: list(rep.SECTIONS), min_length=1, max_length=6)
    date_from: str | None = Field(default=None, pattern=ISO_DATE)
    date_to: str | None = Field(default=None, pattern=ISO_DATE)
    filters: list[DashboardFilterIn] = Field(default_factory=list, max_length=6)


def _summary(r: dict) -> dict:
    return {"id": str(r["_id"]), "title": r["title"], "dataset_id": str(r["dataset_id"]), "dataset_name": r["dataset_name"],
            "version_number": r["version_number"], "source": r["source"], "provider": r.get("provider"),
            "sections": r["sections"], "created_at": r["created_at"].isoformat(),
            "headline": (r.get("narrative") or {}).get("executive_summary", "")[:220]}


def _public(r: dict) -> dict:
    return {**_summary(r), "narrative": r["narrative"], "facts": r["facts"], "unverified": r.get("unverified", []),
            "note": r.get("note"), "model": r.get("model"), "options": r.get("options")}


@router.post("", status_code=201, dependencies=[Csrf])
async def create_report(body: ReportIn, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(body.dataset_id, "Dataset"))
    v = await svc.get_version(d)
    options = {"date_from": body.date_from, "date_to": body.date_to, "filters": [f.model_dump() for f in body.filters]}
    try:
        out = await jobs.run_limited("analytics", get_settings().query_timeout_seconds * 4, jobs.report_job,
                                     str(svc.storage_path(v["storage_ref"])), v, d, options)
    except jobs.JobTimeout:
        raise AppError(504, "timeout", "Building the report took too long and was stopped. Narrow the date range.")
    if "error" in out:
        raise AppError(422, "invalid_options", out["error"])
    facts = rep.build_facts(d, v, out["ok"])
    written = await rep.write_narrative(user, facts, body.use_ai)
    title = (body.title or "").strip() or f"{d['filename'].rsplit('.', 1)[0]} report"
    doc = {"user_id": user["_id"], "dataset_id": d["_id"], "version_id": v["_id"], "dataset_name": d["filename"],
           "version_number": v["version_number"], "title": title, "sections": body.sections, "options": options,
           "facts": facts, "narrative": written["narrative"], "source": written["source"], "provider": written["provider"],
           "model": written["model"], "unverified": written["unverified"], "note": written["note"], "created_at": now_utc()}
    doc["_id"] = (await get_db().reports.insert_one(doc)).inserted_id
    return _public(doc)


@router.get("")
async def list_reports(dataset_id: str | None = None, limit: int = Query(50, ge=1, le=200), user: dict = CurrentUser):
    filt: dict = {"user_id": user["_id"]}
    if dataset_id:
        filt["dataset_id"] = parse_oid(dataset_id, "Dataset")
    docs = await get_db().reports.find(filt, {"facts": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": [_summary(r) for r in docs]}


@router.get("/{report_id}")
async def get_report(report_id: str, user: dict = CurrentUser):
    r = await get_db().reports.find_one({"_id": parse_oid(report_id, "Report"), "user_id": user["_id"]})
    if not r:
        raise not_found("Report")
    return _public(r)


@router.delete("/{report_id}", dependencies=[Csrf])
async def delete_report(report_id: str, user: dict = CurrentUser):
    res = await get_db().reports.delete_one({"_id": parse_oid(report_id, "Report"), "user_id": user["_id"]})
    if not res.deleted_count:
        raise not_found("Report")
    return {"ok": True}

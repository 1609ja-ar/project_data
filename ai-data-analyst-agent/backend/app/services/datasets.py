"""Dataset and version lifecycle: upload, background cleaning, versions, frames, deletion."""
from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from threading import Lock

import pandas as pd
from bson import ObjectId

from app.cleaning import frames
from app.cleaning.pipeline import CleaningOptions
from app.core.errors import AppError, not_found
from app.db.mongo import get_db
from app.security.tokens import now_utc
from app.services import jobs
from app.services.storage import get_storage

log = logging.getLogger("app.datasets")

FRIENDLY_FAILURE = "Cleaning failed for this file. Try re-running cleaning with different options (for example the header row)."


# ------------------------------------------------------------------ lookups (always scoped to the user)

async def get_dataset(user: dict, dataset_id: ObjectId) -> dict:
    d = await get_db().datasets.find_one({"_id": dataset_id, "user_id": user["_id"]})
    if not d:
        raise not_found("Dataset")
    return d


async def get_version(dataset: dict, version_id: ObjectId | None = None) -> dict:
    vid = version_id or dataset.get("active_version_id")
    if not vid:
        raise AppError(409, "not_ready", "This dataset has not finished cleaning yet.")
    v = await get_db().dataset_versions.find_one({"_id": vid, "dataset_id": dataset["_id"], "user_id": dataset["user_id"]})
    if not v:
        raise not_found("Version")
    return v


# ------------------------------------------------------------------ frame cache (versions are immutable)

_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
_cache_lock = Lock()
_CACHE_MAX = 6


def load_frame(version: dict) -> pd.DataFrame:
    ref = version["storage_ref"]
    with _cache_lock:
        if ref in _cache:
            _cache.move_to_end(ref)
            return _cache[ref]
    df = frames.read_parquet(get_storage().path(ref), version["schema"])
    with _cache_lock:
        _cache[ref] = df
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return df


def load_raw_grid(dataset: dict) -> pd.DataFrame:
    ref = dataset["raw_grid_ref"]
    with _cache_lock:
        if ref in _cache:
            return _cache[ref]
    df = pd.read_parquet(get_storage().path(ref))
    with _cache_lock:
        _cache[ref] = df
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return df


# ------------------------------------------------------------------ versions

async def _next_version_number(dataset_id: ObjectId) -> int:
    last = await get_db().dataset_versions.find_one({"dataset_id": dataset_id}, sort=[("version_number", -1)])
    return (last["version_number"] if last else 0) + 1


async def create_version(dataset: dict, *, kind: str, storage_ref: str, parent_id, schema: list[dict], row_count: int,
                         options: dict | None, report: dict, suggestions: list[dict]) -> dict:
    db = get_db()
    doc = {
        "dataset_id": dataset["_id"], "user_id": dataset["user_id"],
        "version_number": await _next_version_number(dataset["_id"]), "kind": kind, "storage_ref": storage_ref,
        "parent_version_id": parent_id, "row_count": int(row_count), "column_count": len(schema), "schema": schema,
        "cleaning_options": options, "cleaning_report": report,
        "quality_score_before": report.get("summary", {}).get("quality_score_before"),
        "quality_score_after": report.get("summary", {}).get("quality_score_after"),
        "suggestions": suggestions, "created_at": now_utc(),
    }
    doc["_id"] = (await db.dataset_versions.insert_one(doc)).inserted_id
    await db.datasets.update_one({"_id": dataset["_id"]}, {"$set": {
        "active_version_id": doc["_id"], "row_count": doc["row_count"], "column_count": doc["column_count"]}})
    return doc


# ------------------------------------------------------------------ automatic cleaning (background)

async def run_cleaning_task(dataset_id: ObjectId, options: dict) -> None:
    db = get_db()
    storage = get_storage()
    dataset = await db.datasets.find_one({"_id": dataset_id})
    if not dataset:
        return
    out_ref = storage.new_ref(str(dataset["user_id"]), ".parquet")
    try:
        await db.datasets.update_one({"_id": dataset_id}, {"$set": {"cleaning_status": "running", "cleaning_stage": "cleaning",
                                                                     "cleaning_error": None}})
        cleaned = await jobs.run_job(jobs.clean_job, str(storage.path(dataset["raw_grid_ref"])), dataset.get("merged", []),
                                     options, str(storage.path(out_ref)))
        await db.datasets.update_one({"_id": dataset_id}, {"$set": {"cleaning_stage": "profiling",
                                                                     "cleaning_counts": cleaned["report"]["summary"]}})
        prof = await jobs.run_job(jobs.profile_job, str(storage.path(out_ref)), cleaned["columns"], dataset.get("column_roles"))
        parent = dataset.get("active_version_id")
        await create_version(dataset, kind="auto_cleaned", storage_ref=out_ref, parent_id=parent, schema=prof["schema"],
                             row_count=cleaned["rows"], options=options, report=cleaned["report"], suggestions=prof["suggestions"])
        await db.datasets.update_one({"_id": dataset_id}, {"$set": {"cleaning_status": "done", "cleaning_stage": "done",
                                                                     "cleaning_options": options}})
    except Exception as e:  # noqa: BLE001 - background task must record failure, not crash
        log.exception("Cleaning failed dataset=%s", dataset_id)
        storage.delete(out_ref)
        message = str(e) if isinstance(e, ValueError) and len(str(e)) < 200 else FRIENDLY_FAILURE
        await db.datasets.update_one({"_id": dataset_id}, {"$set": {"cleaning_status": "failed", "cleaning_stage": "failed",
                                                                     "cleaning_error": message}})


async def recover_interrupted() -> None:
    """Datasets left running by a restart are marked failed so the user can re-run cleaning."""
    await get_db().datasets.update_many({"cleaning_status": {"$in": ["pending", "running"]}},
                                        {"$set": {"cleaning_status": "failed", "cleaning_stage": "failed",
                                                  "cleaning_error": "Cleaning was interrupted by a server restart. Re-run cleaning."}})


def options_from(body: dict | None, previous: dict | None = None) -> dict:
    base = CleaningOptions(**(previous or {})).to_dict()
    for k, v in (body or {}).items():
        if k in base:
            base[k] = v
    return CleaningOptions(**base).to_dict()


# ------------------------------------------------------------------ deletion

async def delete_dataset_everything(dataset: dict) -> None:
    db = get_db()
    storage = get_storage()
    did = dataset["_id"]
    for v in await db.dataset_versions.find({"dataset_id": did}).to_list(None):
        storage.delete(v["storage_ref"])
    for ref in (dataset.get("raw_storage_ref"), dataset.get("raw_grid_ref"), *(dataset.get("previous_raw_refs") or [])):
        if ref:
            storage.delete(ref)
    for r in await db.reports.find({"dataset_id": did}).to_list(None):
        if r.get("storage_ref"):
            storage.delete(r["storage_ref"])
    conv_ids = [c["_id"] for c in await db.conversations.find({"dataset_id": did}, {"_id": 1}).to_list(None)]
    if conv_ids:
        await db.messages.delete_many({"conversation_id": {"$in": conv_ids}})
    for coll in ("dataset_versions", "analyses", "conversations", "reports", "saved_queries", "dashboards", "export_tokens", "share_links"):
        await db[coll].delete_many({"dataset_id": did})
    await db.datasets.delete_one({"_id": did})
    with _cache_lock:
        _cache.clear()


def storage_path(ref: str) -> Path:
    return get_storage().path(ref)

"""SQL Workbench: read-only SQL on the user's own cleaned data, run in a separate killable worker process."""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.analytics import record_analysis
from app.api.deps import Csrf, CurrentUser, SqlLimit, parse_oid
from app.cleaning.structure import snake_key
from app.core.config import get_settings
from app.core.errors import AppError, bad_request, not_found
from app.db.mongo import get_db
from app.security.sql_guard import MAX_SQL_CHARS, validate_sql, wrap_with_limit
from app.security.tokens import now_utc
from app.services import datasets as svc
from app.services import jobs

router = APIRouter(prefix="/sql", tags=["sql"])
logging.getLogger("sqlglot").setLevel(logging.ERROR)

MAX_EXTRA_TABLES = 3
SQL_TYPES = {"string": "VARCHAR", "integer": "BIGINT", "float": "DOUBLE", "date": "DATE", "datetime": "TIMESTAMP", "boolean": "BOOLEAN"}


def _sql_type(c: dict) -> str:
    return f"DECIMAL(38,{c.get('scale', 2)})" if c["dtype"] == "decimal" else SQL_TYPES.get(c["dtype"], "VARCHAR")


async def _catalog(user: dict, primary: dict) -> dict[str, dict]:
    """Table name -> {dataset, version}. 'data' is the primary dataset; others are ds_<name> (owned by the user)."""
    db = get_db()
    out: dict[str, dict] = {}
    pv = await svc.get_version(primary)
    out["data"] = {"dataset": primary, "version": pv}
    others = await db.datasets.find({"user_id": user["_id"], "_id": {"$ne": primary["_id"]},
                                     "active_version_id": {"$ne": None}}).sort("created_at", -1).to_list(50)
    for d in others:
        base = "ds_" + (snake_key(re.sub(r"\.[^.]+$", "", d["filename"])) or "dataset")[:40]
        name, k = base, 2
        while name in out:
            name, k = f"{base}_{k}", k + 1
        out[name] = {"dataset": d, "version": None}
    return out


def _schema_entry(name: str, d: dict, v: dict | None) -> dict:
    return {"name": name, "dataset_id": str(d["_id"]), "dataset_name": d["filename"],
            "version_number": v["version_number"] if v else None,
            "columns": [{"name": c["key"], "label": c["display_name"], "type": _sql_type(c)} for c in v["schema"]] if v else None}


@router.get("/{dataset_id}/schema")
async def schema(dataset_id: str, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    cat = await _catalog(user, d)
    tables = []
    for name, entry in cat.items():
        v = entry["version"] or await svc.get_version(entry["dataset"])
        tables.append(_schema_entry(name, entry["dataset"], v))
    return {"tables": tables, "max_rows": get_settings().sql_max_rows, "max_chars": MAX_SQL_CHARS,
            "timeout_seconds": get_settings().sql_timeout_seconds}


class SqlIn(BaseModel):
    sql: str = Field(max_length=MAX_SQL_CHARS + 1000)


def _check(sql: str, catalog: dict):
    res = validate_sql(sql, set(catalog))
    if res.ok and len([t for t in res.tables if t != "data"]) > MAX_EXTRA_TABLES:
        res.ok, res.message = False, f"A query can join at most {MAX_EXTRA_TABLES} other datasets."
    return res


@router.post("/{dataset_id}/validate", dependencies=[Csrf])
async def validate(dataset_id: str, body: SqlIn, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    res = _check(body.sql, await _catalog(user, d))
    return {"valid": res.ok, "message": res.message, "line": res.line, "col": res.col, "tables": res.tables}


@router.post("/{dataset_id}/run", dependencies=[Csrf, SqlLimit])
async def run(dataset_id: str, body: SqlIn, user: dict = CurrentUser):
    s = get_settings()
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    catalog = await _catalog(user, d)
    res = _check(body.sql, catalog)
    if not res.ok:
        raise AppError(400, "invalid_sql", res.message, {"line": res.line, "col": res.col})
    tables, versions = {}, {}
    for name in res.tables:
        entry = catalog[name]
        v = entry["version"] or await svc.get_version(entry["dataset"])
        tables[name] = str(svc.storage_path(v["storage_ref"]))
        versions[name] = {"dataset": entry["dataset"]["filename"], "version_number": v["version_number"]}
    executed = wrap_with_limit(body.sql, s.sql_max_rows)
    try:
        out = await jobs.run_limited("sql", s.sql_timeout_seconds, jobs.sql_job, executed, tables, s.sql_max_rows,
                                     s.sql_memory_limit, force_process=True)
    except jobs.JobTimeout:
        raise AppError(504, "timeout", f"The query ran longer than {s.sql_timeout_seconds} seconds and was stopped.")
    if "error" in out:
        raise AppError(400, "sql_error", out["error"], {"detail": out.get("detail")})
    primary_v = catalog["data"]["version"]
    meta = {"executed_sql": executed, "dataset_version": primary_v["version_number"], "tables": versions,
            "row_count": out["row_count"], "truncated": out["truncated"], "max_rows": s.sql_max_rows, "duration_ms": out["duration_ms"],
            "engine": "duckdb"}
    details = {"dataset_version": primary_v["version_number"], "engine": "duckdb", "equivalent_sql": body.sql,
               "formula": "User SQL (read-only)", "filters_applied": ["As written in the SQL"],
               "rows_in": out["row_count"], "rows_used": out["row_count"], "rows_skipped": 0, "checks": [],
               "warnings": ([f"Result truncated to the first {s.sql_max_rows:,} rows."] if out["truncated"] else [])}
    aid = await record_analysis(user, d, primary_v, "sql", body.sql[:200], {"columns": out["columns"], "rows": out["rows"][:200]},
                                details, f"{out['row_count']} row(s)")
    return {**out, **meta, "calculation_details": details, "analysis_id": aid}


# ------------------------------------------------------------------ saved queries

class SavedIn(BaseModel):
    dataset_id: str
    name: str = Field(min_length=1, max_length=120)
    sql: str = Field(min_length=1, max_length=MAX_SQL_CHARS)


def _saved_public(q: dict) -> dict:
    return {"id": str(q["_id"]), "dataset_id": str(q["dataset_id"]), "name": q["name"], "sql": q["sql"],
            "created_at": q["created_at"].isoformat(), "updated_at": q["updated_at"].isoformat()}


@router.get("/saved")
async def list_saved(dataset_id: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                     user: dict = CurrentUser):
    filt: dict = {"user_id": user["_id"]}
    if dataset_id:
        filt["dataset_id"] = parse_oid(dataset_id, "Dataset")
    db = get_db()
    total = await db.saved_queries.count_documents(filt)
    items = await db.saved_queries.find(filt).sort("updated_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": [_saved_public(q) for q in items],
            "pagination": {"page": page, "page_size": page_size, "total": total, "pages": max(1, -(-total // page_size))}}


@router.post("/saved", status_code=201, dependencies=[Csrf])
async def create_saved(body: SavedIn, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(body.dataset_id, "Dataset"))
    if not validate_sql(body.sql, set(await _catalog(user, d))).ok:
        raise bad_request("Fix the query before saving it (it does not pass validation).", "invalid_sql")
    doc = {"user_id": user["_id"], "dataset_id": d["_id"], "name": body.name.strip(), "sql": body.sql,
           "created_at": now_utc(), "updated_at": now_utc()}
    doc["_id"] = (await get_db().saved_queries.insert_one(doc)).inserted_id
    return _saved_public(doc)


@router.delete("/saved/{query_id}", dependencies=[Csrf])
async def delete_saved(query_id: str, user: dict = CurrentUser):
    res = await get_db().saved_queries.delete_one({"_id": parse_oid(query_id, "Saved query"), "user_id": user["_id"]})
    if not res.deleted_count:
        raise not_found("Saved query")
    return {"ok": True}

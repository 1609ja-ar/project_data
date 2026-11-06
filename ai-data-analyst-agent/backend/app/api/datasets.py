"""Dataset upload, listing, preview, versions, cleaning and downloads. Every query is scoped to the user."""
from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Literal

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import Csrf, CurrentUser, UploadLimit, parse_oid
from app.cleaning import frames
from app.cleaning.parsing import canonical_text
from app.cleaning.structure import build_names, detect_header, normalize_text
from app.core.config import get_settings
from app.core.errors import AppError, bad_request
from app.db.mongo import get_db
from app.schemas.common import dataset_public, version_public
from app.security.tokens import now_utc
from app.services import clean_export
from app.services import fetch as remote
from app.services import datasets as svc
from app.services import jobs
from app.services.ingest import IngestError, file_type_from_name, read_grid, validate_content
from app.services.storage import get_storage

router = APIRouter(prefix="/datasets", tags=["datasets"])

MAX_PAGE_SIZE = 200


def _letters(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _safe_filename(name: str) -> str:
    name = (name or "dataset").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:200] or "dataset"


async def _read_upload(file: UploadFile, limit: int) -> bytes:
    chunks, size = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise AppError(413, "too_large", f"The file is larger than the {limit // (1024 * 1024)} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def _raw_preview(grid: pd.DataFrame, limit: int = 20) -> dict:
    head = grid.head(limit)
    return {
        "columns": [{"key": c, "label": _letters(i), "dtype": "string"} for i, c in enumerate(grid.columns)],
        "rows": [[None if pd.isna(v) else str(v) for v in row] for row in head.itertuples(index=False)],
        "row_numbers": [int(i) + 1 for i in head.index],
    }


def _detected_names(grid: pd.DataFrame) -> list[str]:
    try:
        top = grid.head(30).apply(normalize_text)
        header, n_rows, _ = detect_header(top, set(), None)
        return [n or _letters(i) for i, n in enumerate(build_names(top, header, n_rows))]
    except Exception:  # noqa: BLE001 - preview only
        return [_letters(i) for i in range(grid.shape[1])]


@router.post("/upload", status_code=201, dependencies=[Csrf, UploadLimit])
async def upload(background: BackgroundTasks, file: UploadFile = File(...), sheet: str | None = Form(default=None),
                 user: dict = CurrentUser):
    s = get_settings()
    filename = _safe_filename(file.filename or "")
    try:
        file_type = file_type_from_name(filename)
    except IngestError as e:
        raise AppError(400, e.code, e.message)
    data = await _read_upload(file, s.max_upload_bytes)
    return await _ingest(user, filename, file_type, data, sheet, background)


async def _ingest(user: dict, filename: str, file_type: str, data: bytes, sheet: str | None, background: BackgroundTasks,
                  source: dict | None = None) -> dict:
    """Store the raw file, read its grid and start cleaning. Shared by file upload and import from a link."""
    s = get_settings()
    if file_type != "csv" and len(data) > s.max_excel_bytes:
        raise AppError(413, "too_large", f"Excel files can be up to {s.max_excel_bytes // (1024 * 1024)} MB. "
                                         "For a larger table, save it as CSV (up to "
                                         f"{s.max_upload_bytes // (1024 * 1024)} MB).")
    try:
        validate_content(data, file_type)
        grid = await asyncio.to_thread(read_grid, data, file_type, sheet or None, s.max_rows, s.max_columns)
    except IngestError as e:
        raise AppError(400, e.code, e.message)

    storage = get_storage()
    uid = str(user["_id"])
    raw_ref = storage.new_ref(uid, f".{file_type}")
    sha = storage.write_bytes(raw_ref, data)
    grid_ref = storage.new_ref(uid, ".parquet")
    await asyncio.to_thread(grid.frame.to_parquet, storage.path(grid_ref), index=False)
    doc = {
        "user_id": user["_id"], "filename": filename, "file_type": file_type, "size_bytes": len(data),
        "raw_storage_ref": raw_ref, "raw_sha256": sha, "raw_grid_ref": grid_ref,
        "sheet": grid.sheet, "sheets": grid.sheets, "merged": [list(m) for m in grid.merged],
        "csv_encoding": grid.encoding, "csv_delimiter": grid.delimiter,
        "raw_row_count": int(grid.frame.shape[0]), "raw_column_count": int(grid.frame.shape[1]),
        "row_count": None, "column_count": None, "active_version_id": None, "column_roles": None,
        "cleaning_status": "pending", "cleaning_stage": "cleaning", "cleaning_error": None, "created_at": now_utc(),
        "source": source,
    }
    doc["_id"] = (await get_db().datasets.insert_one(doc)).inserted_id
    options = svc.options_from({"sheet": grid.sheet})
    background.add_task(svc.run_cleaning_task, doc["_id"], options)
    return {
        "dataset": dataset_public(doc),
        "raw_preview": _raw_preview(grid.frame),
        "column_names": _detected_names(grid.frame),
        "sheets": grid.sheets,
        "cleaning_status": "pending",
    }


class ImportUrlIn(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    sheet: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=150)


def _fetch_error(e: remote.FetchError) -> AppError:
    return AppError(400 if e.code in ("invalid_url", "blocked_address", "not_a_file", "unsupported_type", "too_large") else 502,
                    e.code, e.message)


@router.post("/import-url", status_code=201, dependencies=[Csrf, UploadLimit])
async def import_url(body: ImportUrlIn, background: BackgroundTasks, user: dict = CurrentUser):
    """Import a Google Sheet (shared as 'anyone with the link') or a public .csv/.xlsx/.xls link."""
    try:
        got = await remote.fetch(body.url, get_settings().max_upload_bytes)
    except remote.FetchError as e:
        raise _fetch_error(e)
    name = body.name.strip() if body.name and body.name.strip() else got.filename
    if not name.lower().endswith(f".{got.file_type}"):
        name = f"{name}.{got.file_type}"
    source = {"kind": "google_sheets" if "docs.google.com" in got.source_url else "url", "url": got.source_url,
              "fetched_at": now_utc()}
    return await _ingest(user, _safe_filename(name), got.file_type, got.data, body.sheet, background, source)


@router.post("/{dataset_id}/refresh", status_code=202, dependencies=[Csrf, UploadLimit])
async def refresh(dataset_id: str, background: BackgroundTasks, user: dict = CurrentUser):
    """Download the linked file again. If it changed, clean it into a new version with the same options."""
    s = get_settings()
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    src = d.get("source") or {}
    if not src.get("url"):
        raise bad_request("This dataset was uploaded as a file, so there is no link to refresh from. Upload the new file instead.")
    if d.get("cleaning_status") in ("pending", "running"):
        raise AppError(409, "busy", "Cleaning is already running for this dataset.")
    try:
        got = await remote.fetch(src["url"], s.max_upload_bytes)
    except remote.FetchError as e:
        raise _fetch_error(e)
    now = now_utc()
    storage = get_storage()
    sha = hashlib.sha256(got.data).hexdigest()
    if sha == d.get("raw_sha256"):
        await get_db().datasets.update_one({"_id": d["_id"]}, {"$set": {"source.fetched_at": now}})
        return {"changed": False, "cleaning_status": d.get("cleaning_status")}
    try:
        validate_content(got.data, got.file_type)
        grid = await asyncio.to_thread(read_grid, got.data, got.file_type, d.get("sheet"), s.max_rows, s.max_columns)
    except IngestError as e:
        raise AppError(400, e.code, e.message)
    uid = str(user["_id"])
    raw_ref = storage.new_ref(uid, f".{got.file_type}")
    storage.write_bytes(raw_ref, got.data)  # a new file; earlier raw files are never modified
    grid_ref = storage.new_ref(uid, ".parquet")
    await asyncio.to_thread(grid.frame.to_parquet, storage.path(grid_ref), index=False)
    await get_db().datasets.update_one({"_id": d["_id"]}, {"$set": {
        "raw_storage_ref": raw_ref, "raw_sha256": sha, "raw_grid_ref": grid_ref, "file_type": got.file_type,
        "size_bytes": len(got.data), "sheet": grid.sheet, "sheets": grid.sheets, "merged": [list(m) for m in grid.merged],
        "raw_row_count": int(grid.frame.shape[0]), "raw_column_count": int(grid.frame.shape[1]),
        "cleaning_status": "pending", "cleaning_stage": "cleaning", "cleaning_error": None,
        "source.fetched_at": now, "source.changed_at": now},
        "$push": {"previous_raw_refs": {"$each": [r for r in (d["raw_storage_ref"], d.get("raw_grid_ref")) if r]}}})
    background.add_task(svc.run_cleaning_task, d["_id"], svc.options_from({}, d.get("cleaning_options")))
    return {"changed": True, "cleaning_status": "pending"}


@router.get("")
async def list_datasets(q: str | None = Query(default=None, max_length=100), page: int = Query(1, ge=1),
                        page_size: int = Query(20, ge=1, le=100), user: dict = CurrentUser):
    filt: dict = {"user_id": user["_id"]}
    if q and q.strip():
        filt["filename"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    db = get_db()
    total = await db.datasets.count_documents(filt)
    docs = await db.datasets.find(filt).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": [dataset_public(d) for d in docs],
            "pagination": {"page": page, "page_size": page_size, "total": total, "pages": max(1, -(-total // page_size))}}


@router.get("/{dataset_id}")
async def get_one(dataset_id: str, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    out = dataset_public(d)
    out["cleaning_counts"] = d.get("cleaning_counts")
    out["column_roles"] = d.get("column_roles")
    out["cleaning_options"] = d.get("cleaning_options")
    if d.get("active_version_id"):
        v = await get_db().dataset_versions.find_one({"_id": d["active_version_id"]})
        out["active_version"] = version_public(v) if v else None
    return out


def _resolve_version_param(version: str | None):
    if version in (None, "", "cleaned", "active"):
        return None
    if version == "raw":
        return "raw"
    return parse_oid(version, "Version")


@router.get("/{dataset_id}/preview")
async def preview(dataset_id: str, version: str | None = None, page: int = Query(1, ge=1),
                  page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE), sort: str | None = Query(default=None, max_length=100),
                  dir: Literal["asc", "desc"] = "asc", highlight: bool = False, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    which = _resolve_version_param(version)
    if which == "raw" or (which is None and not d.get("active_version_id")):
        grid = await asyncio.to_thread(svc.load_raw_grid, d)
        if sort is not None and sort in grid.columns:
            grid = grid.sort_values(sort, ascending=dir == "asc", na_position="last", kind="stable")
        part = grid.iloc[(page - 1) * page_size: page * page_size]
        prev = _raw_preview(part, page_size)
        return {"version": "raw", "columns": prev["columns"], "rows": prev["rows"], "row_numbers": prev["row_numbers"],
                "pagination": {"page": page, "page_size": page_size, "total": int(len(grid))}}

    v = await svc.get_version(d, which)
    frame = await asyncio.to_thread(svc.load_frame, v)
    schema = v["schema"]
    if sort:
        if sort not in {c["key"] for c in schema}:
            raise bad_request("Unknown sort column")
        frame = frame.sort_values(sort, ascending=dir == "asc", na_position="last", kind="stable")
    part = frame.iloc[(page - 1) * page_size: page * page_size]
    changed = []
    if highlight:
        changed = await asyncio.to_thread(_changed_cells, d, part, schema)
    return {
        "version": str(v["_id"]), "version_number": v["version_number"],
        "columns": [{k: c.get(k) for k in ("key", "display_name", "dtype", "semantic_type", "currency", "scale")} for c in schema],
        "rows": frames.json_rows(part, schema),
        "row_numbers": [int(x) for x in part["_source_row"]],
        "changed": changed,
        "pagination": {"page": page, "page_size": page_size, "total": int(len(frame))},
    }


def _changed_cells(dataset: dict, part: pd.DataFrame, schema: list[dict]) -> list[list[int]]:
    grid = svc.load_raw_grid(dataset)
    idx = part["_source_row"].to_numpy() - 1
    out = []
    for ci, c in enumerate(schema):
        if c.get("source_col") is None or f"c{c['source_col']}" not in grid.columns:
            continue
        raw = grid[f"c{c['source_col']}"].iloc[idx].astype("string").reset_index(drop=True)
        canon = canonical_text(part[c["key"]], c["dtype"], c).reset_index(drop=True)
        same = (raw.isna() & canon.isna()) | (raw == canon).fillna(False)
        out.extend([[int(ri), ci] for ri in (~same).to_numpy().nonzero()[0]])
    return out


@router.get("/{dataset_id}/versions")
async def versions(dataset_id: str, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    vs = await get_db().dataset_versions.find({"dataset_id": d["_id"], "user_id": user["_id"]}).sort("version_number", -1).to_list(None)
    active = d.get("active_version_id")
    return {"items": [{**version_public(v), "is_active": v["_id"] == active,
                       "summary": (v.get("cleaning_report") or {}).get("summary")} for v in vs]}


class ActiveVersionIn(BaseModel):
    version_id: str


@router.put("/{dataset_id}/active-version", dependencies=[Csrf])
async def set_active(dataset_id: str, body: ActiveVersionIn, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    v = await svc.get_version(d, parse_oid(body.version_id, "Version"))
    await get_db().datasets.update_one({"_id": d["_id"]}, {"$set": {
        "active_version_id": v["_id"], "row_count": v["row_count"], "column_count": v["column_count"]}})
    return {"active_version_id": str(v["_id"]), "version_number": v["version_number"]}


@router.get("/{dataset_id}/cleaning-report")
async def cleaning_report(dataset_id: str, version: str | None = None, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    which = _resolve_version_param(version)
    if which == "raw":
        raise bad_request("The raw file has no cleaning report")
    v = await svc.get_version(d, which)
    return {"version": version_public(v, include_report=True)}


class CleanIn(BaseModel):
    sheet: str | None = None
    header_row: int | None = Field(default=None, ge=1, le=1000)
    date_order: Literal["DMY", "MDY"] | None = None
    decimal_separator: Literal[".", ","] | None = None
    null_tokens: list[str] | None = Field(default=None, max_length=100)
    id_columns: list[str] | None = Field(default=None, max_length=200)


@router.post("/{dataset_id}/clean", status_code=202, dependencies=[Csrf])
async def reclean(dataset_id: str, body: CleanIn, background: BackgroundTasks, user: dict = CurrentUser):
    s = get_settings()
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    if d.get("cleaning_status") in ("pending", "running"):
        raise AppError(409, "busy", "Cleaning is already running for this dataset.")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if body.decimal_separator is None and "decimal_separator" in body.model_fields_set:
        patch["decimal_separator"] = None
    if body.header_row is None and "header_row" in body.model_fields_set:
        patch["header_row"] = None
    options = svc.options_from(patch, d.get("cleaning_options"))
    update: dict = {"cleaning_status": "pending", "cleaning_stage": "cleaning", "cleaning_error": None}
    if body.sheet and d["file_type"] != "csv" and body.sheet != d.get("sheet"):
        if body.sheet not in (d.get("sheets") or []):
            raise bad_request(f"Sheet '{body.sheet}' was not found in the workbook.")
        data = get_storage().path(d["raw_storage_ref"]).read_bytes()
        try:
            grid = await asyncio.to_thread(read_grid, data, d["file_type"], body.sheet, s.max_rows, s.max_columns)
        except IngestError as e:
            raise AppError(400, e.code, e.message)
        storage = get_storage()
        new_grid_ref = storage.new_ref(str(user["_id"]), ".parquet")
        await asyncio.to_thread(grid.frame.to_parquet, storage.path(new_grid_ref), index=False)
        update.update({"raw_grid_ref": new_grid_ref, "sheet": grid.sheet, "merged": [list(m) for m in grid.merged],
                       "raw_row_count": int(grid.frame.shape[0]), "raw_column_count": int(grid.frame.shape[1])})
    await get_db().datasets.update_one({"_id": d["_id"]}, {"$set": update})
    background.add_task(svc.run_cleaning_task, d["_id"], options)
    return {"cleaning_status": "pending", "options": options}


@router.get("/{dataset_id}/cleaning-suggestions")
async def suggestions(dataset_id: str, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    v = await svc.get_version(d)
    return {"version_id": str(v["_id"]), "version_number": v["version_number"], "items": v.get("suggestions") or []}


class Selection(BaseModel):
    id: str = Field(max_length=200)
    option: str = Field(max_length=50)
    params: dict | None = None


class ApplyIn(BaseModel):
    selections: list[Selection] = Field(min_length=1, max_length=100)


@router.post("/{dataset_id}/cleaning-suggestions/apply", dependencies=[Csrf])
async def apply(dataset_id: str, body: ApplyIn, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    if d.get("cleaning_status") in ("pending", "running"):
        raise AppError(409, "busy", "Cleaning is running for this dataset. Try again when it finishes.")
    v = await svc.get_version(d)
    storage = get_storage()
    out_ref = storage.new_ref(str(user["_id"]), ".parquet")
    from app.cleaning.suggestions import SuggestionError
    try:
        result = await jobs.run_job(jobs.apply_job, str(storage.path(v["storage_ref"])), v["schema"], v.get("suggestions") or [],
                                    [s.model_dump() for s in body.selections], str(storage.path(out_ref)), d.get("column_roles"))
    except SuggestionError as e:
        storage.delete(out_ref)
        raise bad_request(str(e), "invalid_selection")
    db = get_db()
    if result.get("roles") is not None:
        await db.datasets.update_one({"_id": d["_id"]}, {"$set": {"column_roles": result["roles"]}})
    if not result["steps"]:
        storage.delete(out_ref)
        return {"created_version": None, "column_roles": result.get("roles")}
    prev_summary = (v.get("cleaning_report") or {}).get("summary", {})
    report = {
        "summary": {"rows_before": result["rows_before"], "rows_after": result["rows_after"],
                    "rows_removed": result["rows_before"] - result["rows_after"],
                    "columns_before": v["column_count"], "columns_after": len(result["schema"]),
                    "cells_changed": sum(s["rows_affected"] for s in result["steps"] if s["step"] not in ("unpivot",)),
                    "quality_score_before": prev_summary.get("quality_score_after"),
                    "quality_score_after": prev_summary.get("quality_score_after"), "applied_from_version": v["version_number"]},
        "steps": result["steps"],
    }
    if result["rows_before"] - report["summary"]["rows_removed"] != result["rows_after"]:
        storage.delete(out_ref)
        raise AppError(500, "check_failed", "Calculation check failed")
    d = await db.datasets.find_one({"_id": d["_id"]})
    nv = await svc.create_version(d, kind="user_cleaned", storage_ref=out_ref, parent_id=v["_id"], schema=result["schema"],
                                  row_count=result["rows_after"], options={"applied": [s.model_dump() for s in body.selections]},
                                  report=report, suggestions=result["suggestions"])
    return {"created_version": version_public(nv), "column_roles": result.get("roles")}


@router.get("/{dataset_id}/download")
async def download(dataset_id: str, version: str = "cleaned",
                   format: Literal["csv", "csv_excel", "xlsx", "json", "zip"] = "csv",
                   columns: str | None = Query(default=None, max_length=5000), user: dict = CurrentUser):
    """The original file (version=raw) or a cleaned version in a shareable format. columns: optional comma-separated
    keys to keep (e.g. leave out personal data before sharing)."""
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", d["filename"].rsplit(".", 1)[0])[:100]
    if version == "raw":
        data = get_storage().path(d["raw_storage_ref"]).read_bytes()
        media = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "xls": "application/vnd.ms-excel"}[d["file_type"]]
        return Response(data, media_type=media, headers=_attachment(f"{base}_original.{d['file_type']}"))
    if not d.get("active_version_id"):
        raise bad_request("This dataset has no cleaned version yet")
    v = await svc.get_version(d, _resolve_version_param(version))
    try:
        schema = clean_export.pick_columns(v["schema"], [k for k in (columns or "").split(",") if k])
    except ValueError as e:
        raise bad_request(str(e)) from None
    if not schema:
        raise bad_request("Choose at least one column")
    frame = await asyncio.to_thread(svc.load_frame, v)
    data = await asyncio.to_thread(clean_export.build, format, frame, schema, v, d, base, len(schema) == len(v["schema"]))
    headers = _attachment(f"{base}_clean_v{v['version_number']}.{clean_export.EXT[format]}")
    headers["X-Rows-Exported"] = str(len(frame))
    headers["X-Columns-Exported"] = str(len(schema))
    return Response(data, media_type=clean_export.MEDIA[format], headers=headers)


def _attachment(name: str) -> dict:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:150]
    return {"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"}


@router.delete("/{dataset_id}", dependencies=[Csrf])
async def delete(dataset_id: str, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    await svc.delete_dataset_everything(d)
    return {"ok": True}

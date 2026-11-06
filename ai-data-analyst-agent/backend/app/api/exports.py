"""Excel and Power BI exports, export tokens, and the token-protected refreshable feed."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import Csrf, CurrentUser, parse_oid
from app.cleaning import frames
from app.core.config import get_settings
from app.core.errors import AppError, bad_request, not_found
from app.core.ratelimit import limiter
from app.db.mongo import get_db
from app.security.sql_guard import validate_sql, wrap_with_limit
from app.security.tokens import now_utc, random_token, sha256_hex
from app.services import datasets as svc
from app.services import exports as ex
from app.services import jobs

router = APIRouter(tags=["exports"])
log = logging.getLogger("app.exports")
FEED_CHUNK_ROWS = 5000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _attachment(name: str) -> dict:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:150]
    return {"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"}


def _base(d: dict) -> str:
    return d["filename"].rsplit(".", 1)[0]


@router.get("/powerbi/{dataset_id}/package")
async def powerbi_package(dataset_id: str, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    v = await svc.get_version(d)
    frame = await asyncio.to_thread(svc.load_frame, v)
    data = await asyncio.to_thread(ex.powerbi_package, frame, v["schema"], svc.storage_path(v["storage_ref"]), v, d)
    return Response(data, media_type="application/zip", headers=_attachment(f"{_base(d)}_powerbi_v{v['version_number']}.zip"))


@router.get("/exports/{dataset_id}/excel")
async def excel(dataset_id: str, charts: str | None = Query(default=None, max_length=2000), user: dict = CurrentUser):
    """charts: comma-separated analysis ids of saved charts (analysis_type 'chart') for this dataset."""
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    v = await svc.get_version(d)
    chart_payloads = []
    if charts:
        ids = [parse_oid(x.strip(), "Chart") for x in charts.split(",") if x.strip()][:20]
        docs = await get_db().analyses.find({"_id": {"$in": ids}, "user_id": user["_id"], "dataset_id": d["_id"],
                                             "analysis_type": "chart"}).to_list(20)
        if len(docs) != len(ids):
            raise not_found("Chart")
        chart_payloads = [{"title": a["result_summary"]["chart"].get("title"), "chart": a["result_summary"]["chart"],
                           "columns": a["result_summary"]["columns"], "rows": a["result_summary"]["rows"]} for a in docs]
    frame = await asyncio.to_thread(svc.load_frame, v)
    data, skipped = await asyncio.to_thread(ex.excel_workbook, frame, v["schema"], v, d, chart_payloads)
    headers = _attachment(f"{_base(d)}_v{v['version_number']}.xlsx")
    if skipped:
        headers["X-Charts-Skipped"] = str(len(skipped))
    return Response(data, media_type=XLSX, headers=headers)


class ExportViewIn(BaseModel):
    """Columns and view filters for a tailored export (filters work exactly as on the dashboard)."""
    columns: list[str] | None = Field(default=None, max_length=500)
    date_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    filters: list[dict] = Field(default_factory=list, max_length=6)


class ExcelCustomIn(ExportViewIn):
    include_dashboard: bool = True
    include_dictionary: bool = True
    include_cleaning: bool = True
    title: str | None = Field(default=None, max_length=200)


def _export_view(frame, schema: list[dict], d: dict, body: ExportViewIn):
    """(filtered frame, chosen schema, filter descriptions)."""
    from app.analytics.dashboard import apply_view, date_column, view_filters
    from app.analytics.plan import describe_filters
    from app.analytics.profile import detect_roles

    for f in body.filters:
        if not isinstance(f, dict) or not isinstance(f.get("column"), str) or not isinstance(f.get("values"), list):
            raise ValueError("Each filter needs a column and a list of values")
    filters = view_filters(schema, date_column(schema, detect_roles(schema, d.get("column_roles"))),
                           body.date_from, body.date_to, body.filters)
    mask, probe = apply_view(frame, schema, filters)
    chosen = schema
    if body.columns:
        known = {c["key"]: c for c in schema}
        unknown = [c for c in body.columns if c not in known]
        if unknown:
            raise ValueError(f"Unknown column(s): {', '.join(unknown[:5])}")
        chosen = [known[k] for k in body.columns]
    return frame.loc[mask].reset_index(drop=True), chosen, describe_filters(probe, schema)


@router.post("/exports/{dataset_id}/preview", dependencies=[Csrf])
async def export_preview(dataset_id: str, body: ExportViewIn, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    v = await svc.get_version(d)
    frame = await asyncio.to_thread(svc.load_frame, v)
    try:
        view, chosen, ftext = await asyncio.to_thread(_export_view, frame, v["schema"], d, body)
    except ValueError as e:
        raise AppError(422, "invalid_options", str(e))
    cols = [{"key": c["key"], "label": c["display_name"], "dtype": c["dtype"], "semantic_type": c["semantic_type"],
             **({"currency": c.get("currency")} if c.get("currency") else {})} for c in chosen]
    return {"rows": int(len(view)), "total_rows": int(len(frame)), "columns": cols, "filters": ftext,
            "sample": frames.json_rows(view.head(12), chosen)}


@router.post("/exports/{dataset_id}/excel-custom", dependencies=[Csrf])
async def excel_custom(dataset_id: str, body: ExcelCustomIn, user: dict = CurrentUser):
    """A workbook of the chosen columns and rows, optionally with the dashboard's KPIs and native charts."""
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    v = await svc.get_version(d)
    frame = await asyncio.to_thread(svc.load_frame, v)
    try:
        view, chosen, ftext = await asyncio.to_thread(_export_view, frame, v["schema"], d, body)
    except ValueError as e:
        raise AppError(422, "invalid_options", str(e))
    if len(view) == 0:
        raise AppError(422, "empty", "No rows match these filters, so there is nothing to export.")
    charts, summary = [], None
    if body.include_dashboard:
        opts = {"date_from": body.date_from, "date_to": body.date_to, "filters": body.filters}
        try:
            out = await jobs.run_limited("analytics", get_settings().query_timeout_seconds * 3, jobs.dashboard_job,
                                         str(svc.storage_path(v["storage_ref"])), v, d, opts)
        except jobs.JobTimeout:
            raise AppError(504, "timeout", "Building the dashboard sheets took too long. Untick them or narrow the filters.")
        if "error" in out:
            raise AppError(422, "invalid_options", out["error"])
        dash = out["ok"]
        charts = [{"title": t["title"], "chart": t["chart"]["spec"], "columns": t["chart"]["columns"], "rows": t["chart"]["rows"]}
                  for t in dash["tiles"] + dash.get("custom_tiles", []) if t["kind"] != "table"]
        summary = {"title": body.title, "rows": len(view), "filters": ftext, "kpis": dash["kpis"]}
    include = {k for k, on in (("dictionary", body.include_dictionary), ("cleaning", body.include_cleaning)) if on}
    data, skipped = await asyncio.to_thread(ex.excel_workbook, view, chosen, v, d, charts, summary, include)
    headers = _attachment(f"{_base(d)}_v{v['version_number']}{'_filtered' if ftext else ''}.xlsx")
    headers["X-Rows-Exported"] = str(len(view))
    if skipped:
        headers["X-Charts-Skipped"] = str(len(skipped))
    return Response(data, media_type=XLSX, headers=headers)


@router.get("/powerbi/{dataset_id}/setup")
async def powerbi_setup(dataset_id: str, base_url: str = Query(max_length=200, pattern=r"^https?://[^\s\"]+$"),
                        user: dict = CurrentUser):
    """Everything needed to connect Power BI, shown in the app: column types, M scripts and DAX measures."""
    from app.analytics.profile import detect_roles

    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    v = await svc.get_version(d)
    schema = v["schema"]
    feed_url = f"{base_url.rstrip('/')}/api/feed/{dataset_id}.csv"
    return {"feed_url": feed_url, "version_number": v["version_number"],
            "columns": [{"name": c["display_name"], "type": c["dtype"], "powerbi_type": ex.powerbi_type(c)[1]} for c in schema],
            "m_web": ex.m_web_script(schema, feed_url), "m_file": ex.m_script(schema),
            "dax": ex.dax_measures(schema, detect_roles(schema, d.get("column_roles")))}


class SqlXlsxIn(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)


@router.post("/exports/{dataset_id}/sql-xlsx", dependencies=[Csrf])
async def sql_xlsx(dataset_id: str, body: SqlXlsxIn, user: dict = CurrentUser):
    """Re-runs the SQL server-side (never trusts client data) and returns the result as .xlsx."""
    from app.api.sql import _catalog

    s = get_settings()
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    catalog = await _catalog(user, d)
    chk = validate_sql(body.sql, set(catalog))
    if not chk.ok:
        raise AppError(400, "invalid_sql", chk.message, {"line": chk.line, "col": chk.col})
    tables = {}
    for name in chk.tables:
        vv = catalog[name]["version"] or await svc.get_version(catalog[name]["dataset"])
        tables[name] = str(svc.storage_path(vv["storage_ref"]))
    executed = wrap_with_limit(body.sql, s.sql_max_rows)
    try:
        out = await jobs.run_limited("sql", s.sql_timeout_seconds, jobs.sql_job, executed, tables, s.sql_max_rows,
                                     s.sql_memory_limit, force_process=True)
    except jobs.JobTimeout:
        raise AppError(504, "timeout", "The query took too long and was stopped.")
    if "error" in out:
        raise AppError(400, "sql_error", out["error"])
    data = await asyncio.to_thread(ex.sql_result_workbook, out["columns"], out["rows"], executed)
    return Response(data, media_type=XLSX, headers=_attachment("sql_result.xlsx"))


# ------------------------------------------------------------------ export tokens

class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dataset_id: str | None = None
    expires_in_days: int = Field(default=30, ge=1)


def _token_public(t: dict, datasets: dict) -> dict:
    return {"id": str(t["_id"]), "name": t["name"], "token_prefix": t["token_prefix"],
            "dataset_id": str(t["dataset_id"]) if t.get("dataset_id") else None,
            "dataset_name": datasets.get(t.get("dataset_id")) if t.get("dataset_id") else "All my datasets",
            "expires_at": t["expires_at"].isoformat(), "last_used_at": t["last_used_at"].isoformat() if t.get("last_used_at") else None,
            "revoked_at": t["revoked_at"].isoformat() if t.get("revoked_at") else None, "created_at": t["created_at"].isoformat(),
            "status": "revoked" if t.get("revoked_at") else "expired" if t["expires_at"] <= now_utc() else "active"}


@router.post("/export-tokens", status_code=201, dependencies=[Csrf])
async def create_token(body: TokenIn, user: dict = CurrentUser):
    s = get_settings()
    if body.expires_in_days > s.export_token_max_days:
        raise bad_request(f"Tokens can last at most {s.export_token_max_days} days.")
    did = None
    if body.dataset_id:
        did = (await svc.get_dataset(user, parse_oid(body.dataset_id, "Dataset")))["_id"]
    token = "pbi_" + random_token(32)
    doc = {"user_id": user["_id"], "dataset_id": did, "name": body.name.strip(), "token_hash": sha256_hex(token),
           "token_prefix": token[:8], "expires_at": now_utc() + timedelta(days=body.expires_in_days),
           "last_used_at": None, "revoked_at": None, "created_at": now_utc()}
    doc["_id"] = (await get_db().export_tokens.insert_one(doc)).inserted_id
    names = {did: (await svc.get_dataset(user, did))["filename"]} if did else {}
    return {**_token_public(doc, names), "token": token,
            "warning": "This token is shown only once. Anyone holding it can read the data it covers."}


@router.get("/export-tokens")
async def list_tokens(user: dict = CurrentUser):
    db = get_db()
    items = await db.export_tokens.find({"user_id": user["_id"]}).sort("created_at", -1).to_list(200)
    names = {d["_id"]: d["filename"] for d in await db.datasets.find({"user_id": user["_id"]}, {"filename": 1}).to_list(None)}
    return {"items": [_token_public(t, names) for t in items]}


@router.delete("/export-tokens/{token_id}", dependencies=[Csrf])
async def revoke_token(token_id: str, user: dict = CurrentUser):
    res = await get_db().export_tokens.update_one({"_id": parse_oid(token_id, "Token"), "user_id": user["_id"], "revoked_at": None},
                                                  {"$set": {"revoked_at": now_utc()}})
    if not res.matched_count:
        raise not_found("Token")
    return {"ok": True}


# ------------------------------------------------------------------ refreshable feed (export tokens only)

def _feed_key(request: Request) -> str:
    raw = _raw_token(request) or ""
    return "feed:" + sha256_hex(raw)[:16] if raw else (request.client.host if request.client else "anon")


def _raw_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if get_settings().export_token_in_url:
        return request.query_params.get("token")
    return None


def _feed_limit() -> str:
    return get_settings().feed_rate_limit


@router.get("/feed/{dataset_id}.{fmt}")
@limiter.limit(_feed_limit, key_func=_feed_key)
async def feed(request: Request, dataset_id: str, fmt: str, version: str | None = None,
               columns: str | None = Query(default=None, max_length=5000)):
    if fmt not in ("csv", "json"):
        raise not_found("Feed")
    if "token" in request.query_params and not get_settings().export_token_in_url:
        raise AppError(401, "unauthorized", "Tokens in the URL are disabled. Send it as the header Authorization: Bearer <token>.")
    raw = _raw_token(request)
    if not raw or not raw.startswith("pbi_"):
        raise AppError(401, "unauthorized", "An export token is required (Authorization: Bearer pbi_...).")
    db = get_db()
    tok = await db.export_tokens.find_one({"token_hash": sha256_hex(raw)})
    now = now_utc()
    if not tok or tok.get("revoked_at") or tok["expires_at"] <= now:
        raise AppError(401, "unauthorized", "This export token is invalid, expired or revoked.")
    did = parse_oid(dataset_id, "Dataset")
    if tok.get("dataset_id") and tok["dataset_id"] != did:
        raise not_found("Dataset")
    d = await db.datasets.find_one({"_id": did, "user_id": tok["user_id"]})
    if not d:
        raise not_found("Dataset")
    v = await svc.get_version(d, parse_oid(version, "Version") if version else None)
    await db.export_tokens.update_one({"_id": tok["_id"]}, {"$set": {"last_used_at": now}})
    schema = v["schema"]
    if columns:
        wanted = [c.strip() for c in columns.split(",") if c.strip()]
        known = {c["key"]: c for c in schema}
        unknown = [w for w in wanted if w not in known]
        if unknown:
            raise bad_request(f"Unknown column(s): {', '.join(unknown[:5])}")
        schema = [known[w] for w in wanted]
    frame = await asyncio.to_thread(svc.load_frame, v)
    headers = {"Cache-Control": "no-store", "X-Dataset-Version": str(v["version_number"]), "X-Content-Type-Options": "nosniff"}

    if fmt == "csv":
        def gen_csv():
            for start in range(0, max(1, len(frame)), FEED_CHUNK_ROWS):
                part = frames.export_text_frame(frame.iloc[start:start + FEED_CHUNK_ROWS], schema)
                yield part.to_csv(index=False, header=start == 0, lineterminator="\n").encode("utf-8")
        return StreamingResponse(gen_csv(), media_type="text/csv; charset=utf-8", headers=headers)

    keys = [c["key"] for c in schema]

    def gen_json():
        yield b'{"dataset_version": ' + str(v["version_number"]).encode() + b', "columns": ' + json.dumps(keys).encode() + b', "rows": ['
        first = True
        for start in range(0, len(frame), FEED_CHUNK_ROWS):
            rows = frames.json_rows(frame.iloc[start:start + FEED_CHUNK_ROWS], schema)
            for r in rows:
                yield (b"" if first else b",") + json.dumps(dict(zip(keys, r))).encode()
                first = False
        yield b"]}"
    return StreamingResponse(gen_json(), media_type="application/json", headers=headers)

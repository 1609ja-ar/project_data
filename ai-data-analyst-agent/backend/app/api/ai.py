"""AI endpoints. AI writes or explains text only; it never computes the numbers shown to users."""
from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.ai.base import AIError, ChatMessage
from app.ai.provider import get_provider
from app.api.deps import AiLimit, Csrf, CurrentUser, parse_oid
from app.cleaning import frames
from app.core.config import get_settings
from app.core.errors import AppError
from app.security.sql_guard import MAX_SQL_CHARS, validate_sql
from app.services import datasets as svc

router = APIRouter(prefix="/ai", tags=["ai"])
log = logging.getLogger("app.ai")

PROVIDER_LABELS = {"groq": "Groq", "xai": "xAI Grok"}
SAMPLE_ROWS = 5


@router.get("/providers")
async def providers(user: dict = CurrentUser):
    s = get_settings()
    configured = s.configured_ai_providers()
    active = user.get("ai_provider") if user.get("ai_provider") in configured else (
        s.ai_provider if s.ai_provider in configured else (configured[0] if configured else None))
    return {
        "providers": [{"id": p, "label": PROVIDER_LABELS[p], "configured": p in configured} for p in ("groq", "xai")],
        "active": active,
    }


def ai_http_error(e: AIError) -> AppError:
    status = 400 if e.code == "ai_not_configured" else 429 if e.code == "ai_rate_limited" else 502
    return AppError(status, e.code, e.message)


def _extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    sql = (m.group(1) if m else text).strip()
    return sql.rstrip(";").strip()


class GenerateIn(BaseModel):
    dataset_id: str
    question: str = Field(min_length=3, max_length=1000)


@router.post("/sql/generate", dependencies=[Csrf, AiLimit])
async def generate_sql(body: GenerateIn, user: dict = CurrentUser):
    from app.api.sql import _catalog, _sql_type

    try:
        provider = get_provider(user)
    except AIError as e:
        raise ai_http_error(e)
    d = await svc.get_dataset(user, parse_oid(body.dataset_id, "Dataset"))
    v = await svc.get_version(d)
    catalog = await _catalog(user, d)
    lines = [f'Table name: data (loaded from the file "{d["filename"]}"; always write FROM data, never the file name). Columns:']
    lines += [f"  {c['key']} {_sql_type(c)} -- {c['display_name']}" for c in v["schema"]]
    others = [n for n in catalog if n != "data"][:10]
    if others:
        lines.append("Other tables you may join (columns not listed): " + ", ".join(others))
    if user.get("allow_ai_samples"):
        frame = await asyncio.to_thread(svc.load_frame, v)
        sample = frames.json_rows(frame.head(SAMPLE_ROWS), v["schema"])
        lines.append(f"First {len(sample)} rows (the user allowed samples): {sample}")
    system = ("You write a single read-only DuckDB SELECT query for the user's question. Use only the tables given. "
              "Quote identifiers with double quotes when needed. Never use read_csv, read_parquet, files, URLs, PRAGMA, "
              "SET, ATTACH or any statement other than one SELECT (CTEs are fine). Reply with only the SQL in a ```sql block.")
    try:
        text = await provider.chat([ChatMessage("system", system), ChatMessage("user", "\n".join(lines) + f"\n\nQuestion: {body.question}")],
                                   temperature=0.0, max_tokens=1500)
    except AIError as e:
        raise ai_http_error(e)
    sql = _extract_sql(text)[:MAX_SQL_CHARS]
    check = validate_sql(sql, set(catalog))
    return {"sql": sql, "valid": check.ok, "message": check.message, "provider": provider.name, "model": provider.model,
            "sent_sample_rows": bool(user.get("allow_ai_samples"))}


class ExplainIn(BaseModel):
    sql: str = Field(min_length=1, max_length=MAX_SQL_CHARS)


@router.post("/sql/explain", dependencies=[Csrf, AiLimit])
async def explain_sql(body: ExplainIn, user: dict = CurrentUser):
    try:
        provider = get_provider(user)
        text = await provider.chat([
            ChatMessage("system", "Explain what this SQL query does in plain language for a non-technical reader, in at most "
                                  "6 short bullet points. You see only the query text, not the data, so do not guess results."),
            ChatMessage("user", body.sql)], temperature=0.2, max_tokens=1200)
    except AIError as e:
        raise ai_http_error(e)
    return {"explanation": text.strip(), "provider": provider.name, "model": provider.model, "sent_data": False}

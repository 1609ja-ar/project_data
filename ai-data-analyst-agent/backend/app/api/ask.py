"""Ask: plain-language questions about a dataset, answered with a verified chart and one sentence."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.analytics import _context, record_analysis
from app.api.deps import Csrf, CurrentUser
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.mongo import get_db
from app.services import datasets as svc
from app.services import jobs

router = APIRouter(prefix="/ask", tags=["ask"])
log = logging.getLogger("app.ask")


class AskIn(BaseModel):
    dataset_id: str
    question: str = Field(min_length=3, max_length=300)


async def _run(v: dict, d: dict, question: str, parsed: dict | None) -> dict:
    try:
        return await jobs.run_limited("analytics", get_settings().query_timeout_seconds, jobs.ask_job,
                                      str(svc.storage_path(v["storage_ref"])), v, d, question, parsed)
    except jobs.JobTimeout:
        raise AppError(504, "timeout", "This question took too long to answer. Try a narrower question.")


@router.post("", dependencies=[Csrf])
async def ask(body: AskIn, user: dict = CurrentUser):
    from app.ai.base import AIError, ChatMessage
    from app.ai.provider import get_provider
    from app.analytics import ask as ask_mod
    from app.analytics.dashboard import dimension_candidates

    d, v = await _context(user, body.dataset_id, None)
    question = " ".join(body.question.split())
    parsed, source, provider_name, ai_reason = None, "rules", None, None
    try:
        provider = get_provider(user)
        provider_name = provider.name
        text = await provider.chat([
            ChatMessage("system", "You convert business questions into query plans for a data table. JSON only."),
            ChatMessage("user", ask_mod.ai_prompt(question, v["schema"], dimension_candidates(v["schema"])))],
            temperature=0.0, max_tokens=1500)
        parsed = ask_mod.parse_ai_plan(text)
        source = "ai"
    except AIError as e:
        if e.code != "ai_not_configured":
            log.warning("Ask: AI unavailable (%s); using the rule parser", e.code)
    except (ask_mod.AskError, ValueError) as e:
        ai_reason = str(e)
    out = await _run(v, d, question, parsed)
    if "error" in out and parsed is not None:  # the AI plan did not fit; the rule parser may still answer
        rules = await _run(v, d, question, None)
        out, source = (rules, "rules") if "ok" in rules else (out, source)
    if "error" in out:
        raise AppError(422, "cannot_answer", out["error"] + (f" (AI: {ai_reason})" if ai_reason else ""))
    res = out["ok"]
    summary = {"answer": res["answer"], "interpretation": res["interpretation"], "chart_type": res["chart_type"],
               "plan": res["plan"], "tile": {k: res["tile"][k] for k in ("chart", "series_dimension", "dimension", "groups_total", "other")},
               "source": source}
    aid = await record_analysis(user, d, v, "ask", question, summary, res["tile"]["how_calculated"], res["answer"][:200])
    return {**res, "question": question, "source": source, "provider": provider_name if source == "ai" else None, "analysis_id": aid}


@router.get("/{dataset_id}/recent")
async def recent(dataset_id: str, user: dict = CurrentUser):
    d, _ = await _context(user, dataset_id, None)
    docs = await get_db().analyses.find({"user_id": user["_id"], "dataset_id": d["_id"], "analysis_type": "ask"},
                                        {"question": 1, "result_summary.answer": 1, "created_at": 1}) \
        .sort("created_at", -1).limit(12).to_list(12)
    seen, items = set(), []
    for a in docs:
        if a["question"].lower() not in seen:
            seen.add(a["question"].lower())
            items.append({"id": str(a["_id"]), "question": a["question"], "answer": (a.get("result_summary") or {}).get("answer"),
                          "created_at": a["created_at"].isoformat()})
    return {"items": items[:8]}


@router.get("/{dataset_id}/suggestions")
async def suggestions(dataset_id: str, user: dict = CurrentUser):
    """Questions that this dataset can answer, phrased from its columns."""
    from app.analytics.dashboard import date_column, default_aggregation, dimension_candidates, measure_candidates
    from app.analytics.profile import detect_roles

    d, v = await _context(user, dataset_id, None)
    schema = v["schema"]
    roles = detect_roles(schema, d.get("column_roles"))
    ms, dims, date = measure_candidates(schema), dimension_candidates(schema), date_column(schema, roles)
    m = ms[0] if ms else None
    word = (("total " if default_aggregation(m, roles) == "sum" else "average ") + m["display_name"].lower()) if m else "number of records"
    out = []
    if date:
        out.append(f"Monthly {word}")
    for dim in dims[:2]:
        name = dim["display_name"].lower()
        out.append(f"Top 5 {name if name.endswith('s') else name + 's'} by {word}")
    if dims and dims[0]["unique"] <= 6:
        out.append(f"Share of {word} by {dims[0]['display_name'].lower()}")
    if m and dims:
        out.append(f"Average {m['display_name'].lower()} by {dims[-1]['display_name'].lower()}")
    if len(ms) > 1 and date:
        out.append(f"{ms[1]['display_name']} over time")
    out.append(f"How many records" if not m else f"Total {m['display_name'].lower()}")
    return {"items": out[:6]}

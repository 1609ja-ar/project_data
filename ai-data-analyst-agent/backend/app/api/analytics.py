"""Analytics routes: dataset profile, query plans and chart data. All numbers come from app.analytics."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import AiLimit, Csrf, CurrentUser, parse_oid
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.mongo import get_db
from app.schemas.common import analysis_public
from app.security.tokens import now_utc
from app.services import datasets as svc
from app.services import jobs

router = APIRouter(tags=["analytics"])

CHART_TYPES = ("bar", "horizontal_bar", "grouped_bar", "stacked_bar", "stacked_100_bar", "line", "area", "pie", "kpi", "table")
MAX_STORED_ROWS = 200


async def record_analysis(user: dict, dataset: dict, version: dict, analysis_type: str, question: str | None,
                          result_summary: dict, calculation_details: dict | None, brief: str | None = None) -> str:
    doc = {"user_id": user["_id"], "dataset_id": dataset["_id"], "version_id": version["_id"],
           "dataset_name": dataset["filename"], "analysis_type": analysis_type, "question": question,
           "result_summary": result_summary, "result_summary_brief": brief, "calculation_details": calculation_details,
           "created_at": now_utc()}
    return str((await get_db().analyses.insert_one(doc)).inserted_id)


async def _run_plan(dataset: dict, version: dict, plan: dict) -> dict:
    path = str(svc.storage_path(version["storage_ref"]))
    try:
        out = await jobs.run_limited("analytics", get_settings().query_timeout_seconds, jobs.plan_job, path, version, plan)
    except jobs.JobTimeout:
        raise AppError(504, "timeout", "This calculation took too long and was stopped. Add filters or fewer groups.")
    if "error" in out:
        code, message, details = out["error"]
        raise AppError(422 if code == "invalid_plan" else 500, code, message, details)
    return out["ok"]


async def _context(user: dict, dataset_id: str, version_id: str | None):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    v = await svc.get_version(d, parse_oid(version_id, "Version") if version_id else None)
    return d, v


class ProfileIn(BaseModel):
    version_id: str | None = None
    refresh: bool = False


@router.post("/analytics/{dataset_id}/profile", dependencies=[Csrf])
async def profile(dataset_id: str, body: ProfileIn | None = None, user: dict = CurrentUser):
    body = body or ProfileIn()
    d, v = await _context(user, dataset_id, body.version_id)
    db = get_db()
    if not body.refresh:
        cached = await db.analyses.find_one({"user_id": user["_id"], "dataset_id": d["_id"], "version_id": v["_id"],
                                             "analysis_type": "profile"}, sort=[("created_at", -1)])
        if cached:
            return {"profile": cached["result_summary"], "analysis_id": str(cached["_id"]), "cached": True}
    try:
        prof = await jobs.run_limited("analytics", get_settings().query_timeout_seconds * 3, jobs.profile_dataset_job,
                                      str(svc.storage_path(v["storage_ref"])), v, d)
    except jobs.JobTimeout:
        raise AppError(504, "timeout", "Profiling took too long and was stopped.")
    aid = await record_analysis(user, d, v, "profile", "Dataset profile", prof, None,
                                f"{prof['shape']['rows']} rows × {prof['shape']['columns']} columns")
    return {"profile": prof, "analysis_id": aid, "cached": False}


class QueryIn(BaseModel):
    plan: dict
    version_id: str | None = None
    question: str | None = Field(default=None, max_length=500)


@router.post("/analytics/{dataset_id}/query", dependencies=[Csrf])
async def query(dataset_id: str, body: QueryIn, user: dict = CurrentUser):
    d, v = await _context(user, dataset_id, body.version_id)
    result = await _run_plan(d, v, body.plan)
    summary = {k: result[k] for k in ("columns", "metric_label") if k in result} | {"rows": result["rows"][:MAX_STORED_ROWS]}
    aid = await record_analysis(user, d, v, "query", body.question or result["metric_label"], summary, result["calculation_details"],
                                result["metric_label"])
    return {**result, "analysis_id": aid}


class ChartIn(QueryIn):
    chart_type: Literal[CHART_TYPES] | None = None  # type: ignore[valid-type]
    title: str | None = Field(default=None, max_length=200)


@router.post("/analytics/{dataset_id}/chart", dependencies=[Csrf])
async def chart(dataset_id: str, body: ChartIn, user: dict = CurrentUser):
    d, v = await _context(user, dataset_id, body.version_id)
    result = await _run_plan(d, v, body.plan)
    spec = dict(result.get("chart_suggestion") or {"type": "table"})
    if body.chart_type:
        if body.chart_type in ("grouped_bar", "stacked_bar", "stacked_100_bar") and "series" not in spec:
            raise AppError(422, "invalid_chart", "This chart type needs a second grouping column (series).")
        if body.chart_type in ("bar", "horizontal_bar", "pie") and "x" not in spec and spec.get("type") != "line":
            raise AppError(422, "invalid_chart", "This chart type needs a grouping column.")
        spec["type"] = body.chart_type
    spec["title"] = body.title or result["metric_label"]
    summary = {"columns": result["columns"], "rows": result["rows"][:MAX_STORED_ROWS], "chart": spec}
    aid = await record_analysis(user, d, v, "chart", spec["title"], summary, result["calculation_details"], spec["title"])
    return {**result, "chart": spec, "analysis_id": aid}



class PivotMeasure(BaseModel):
    column: str | None = Field(default=None, max_length=200)
    aggregation: Literal["sum", "mean", "count", "min", "max", "median", "nunique"] = "sum"


class PivotSort(BaseModel):
    by: Literal["auto", "label", "value"] = "auto"
    direction: Literal["asc", "desc"] | None = None
    measure: int = Field(default=0, ge=0, le=5)


class PivotIn(BaseModel):
    rows: list[str] = Field(min_length=1, max_length=3)
    columns: str | None = Field(default=None, max_length=200)
    measures: list[PivotMeasure] = Field(default_factory=lambda: [PivotMeasure(aggregation="count")], min_length=1, max_length=6)
    grain: Literal["day", "week", "month", "quarter", "year"] = "month"
    filters: list[dict] = Field(default_factory=list, max_length=20)
    sort: PivotSort = Field(default_factory=PivotSort)
    col_sort: Literal["label", "value"] = "label"
    top_n: int | None = Field(default=None, ge=1, le=1_000_000)
    version_id: str | None = None


async def _run_pivot(job, d: dict, v: dict, spec: dict, *args):
    path = str(svc.storage_path(v["storage_ref"]))
    try:
        out = await jobs.run_limited("analytics", max(60, get_settings().query_timeout_seconds * 4), job, path, v, spec, *args)
    except jobs.JobTimeout:
        raise AppError(504, "timeout", "This pivot took too long and was stopped. Add filters or choose fields with fewer values.")
    if "error" in out:
        code, message, details = out["error"]
        raise AppError(422 if code == "invalid_plan" else 500, code, message, details)
    return out["ok"]


def _pivot_spec(body: PivotIn) -> dict:
    return body.model_dump(exclude={"version_id"})


@router.post("/analytics/{dataset_id}/pivot", dependencies=[Csrf])
async def pivot(dataset_id: str, body: PivotIn, user: dict = CurrentUser):
    """Pivot table over every row of the dataset: nested rows, a column field, several values, subtotals."""
    d, v = await _context(user, dataset_id, body.version_id)
    spec = _pivot_spec(body)
    result = await _run_pivot(jobs.pivot_job, d, v, spec)
    names = " › ".join(f["label"] for f in result["row_fields"])
    title = f"{', '.join(m['label'] for m in result['measures'])} by {names}" + (f" and {result['column_field']['label']}" if result["column_field"] else "")
    await record_analysis(user, d, v, "pivot", title, {"spec": spec, "rows": len(result["rows"]), "columns": len(result["columns"])},
                          result["how_calculated"], title)
    return result


@router.post("/analytics/{dataset_id}/pivot/export", dependencies=[Csrf])
async def pivot_export(dataset_id: str, body: PivotIn, user: dict = CurrentUser):
    """The same pivot as an Excel workbook (values, subtotals and totals; numbers are real numbers, not text)."""
    from fastapi.responses import Response
    from app.services.pivot_export import safe_name
    d, v = await _context(user, dataset_id, body.version_id)
    data, rows = await _run_pivot(jobs.pivot_xlsx_job, d, v, _pivot_spec(body), d["filename"])
    headers = {"Content-Disposition": f'attachment; filename="{safe_name(d["filename"])}_pivot_v{v["version_number"]}.xlsx"',
               "X-Content-Type-Options": "nosniff", "X-Rows-Exported": str(rows)}
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)

@router.get("/analyses")
async def list_analyses(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                        analysis_type: str | None = Query(default=None, max_length=30), dataset_id: str | None = None,
                        user: dict = CurrentUser):
    filt: dict = {"user_id": user["_id"]}
    if analysis_type:
        filt["analysis_type"] = analysis_type
    if dataset_id:
        filt["dataset_id"] = parse_oid(dataset_id, "Dataset")
    db = get_db()
    total = await db.analyses.count_documents(filt)
    docs = await db.analyses.find(filt, {"result_summary": 0}).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": [analysis_public(a) for a in docs],
            "pagination": {"page": page, "page_size": page_size, "total": total, "pages": max(1, -(-total // page_size))}}


@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: str, user: dict = CurrentUser):
    a = await get_db().analyses.find_one({"_id": parse_oid(analysis_id, "Analysis"), "user_id": user["_id"]})
    if not a:
        raise AppError(404, "not_found", "Analysis not found")
    v = await get_db().dataset_versions.find_one({"_id": a["version_id"]}, {"version_number": 1})
    return {**analysis_public(a), "result_summary": a.get("result_summary"), "calculation_details": a.get("calculation_details"),
            "version_number": v["version_number"] if v else None}


# ------------------------------------------------------------------ automatic dashboard

ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"


class DashboardFilterIn(BaseModel):
    column: str = Field(max_length=200)
    values: list[str] = Field(min_length=1, max_length=200)


class DashboardIn(BaseModel):
    measure: str | None = Field(default=None, max_length=200)
    aggregation: Literal["sum", "mean"] | None = None
    date_from: str | None = Field(default=None, pattern=ISO_DATE)
    date_to: str | None = Field(default=None, pattern=ISO_DATE)
    grain: Literal["day", "week", "month", "quarter", "year"] | None = None
    filters: list[DashboardFilterIn] = Field(default_factory=list, max_length=6)
    refresh: bool = False


@router.post("/analytics/{dataset_id}/dashboard", dependencies=[Csrf])
async def dashboard(dataset_id: str, body: DashboardIn | None = None, user: dict = CurrentUser):
    from app.analytics.dashboard import DashboardOptions

    body = body or DashboardIn()
    d, v = await _context(user, dataset_id, None)
    opts = DashboardOptions(body.measure, body.aggregation, body.date_from, body.date_to, body.grain,
                            [f.model_dump() for f in body.filters])
    db = get_db()
    pinned = await _pinned(user, d)
    # The cache key covers the options and the pinned tiles, so pinning or removing a chart refreshes it.
    key = opts.key() + ":" + ",".join(p["id"] for p in pinned)
    # Only the default view is cached and kept in history; filtered views are computed on demand.
    cacheable = opts.is_default()
    if cacheable and not body.refresh:
        cached = await db.analyses.find_one({"user_id": user["_id"], "dataset_id": d["_id"], "version_id": v["_id"],
                                             "analysis_type": "dashboard", "options_key": key}, sort=[("created_at", -1)])
        if cached:
            return await _with_goals(user, d, {**cached["result_summary"], "analysis_id": str(cached["_id"]), "cached": True})
    try:
        out = await jobs.run_limited("analytics", get_settings().query_timeout_seconds * 3, jobs.dashboard_job,
                                     str(svc.storage_path(v["storage_ref"])), v, d, opts.__dict__, pinned)
    except jobs.JobTimeout:
        raise AppError(504, "timeout", "Building the dashboard took too long and was stopped. Narrow the date range or filters.")
    if "error" in out:
        raise AppError(422, "invalid_options", out["error"])
    res = out["ok"]
    aid = None
    if cacheable:
        aid = await record_analysis(user, d, v, "dashboard", "Dashboard", res, None,
                                    f"{len(res['kpis'])} KPIs, {len(res['tiles'])} charts")
        await db.analyses.update_one({"_id": __import__("bson").ObjectId(aid)}, {"$set": {"options_key": key}})
    return await _with_goals(user, d, {**res, "analysis_id": aid, "cached": False})


# ------------------------------------------------------------------ KPI targets

async def _goals(user: dict, d: dict) -> dict:
    docs = await get_db().dashboards.find({"user_id": user["_id"], "dataset_id": d["_id"], "kind": "goal"}).to_list(50)
    return {g["key"]: g for g in docs}


async def _with_goals(user: dict, d: dict, res: dict) -> dict:
    """Attaches each KPI's target and progress (value / target) for the current view."""
    goals = await _goals(user, d)
    for k in res.get("kpis", []):
        g = goals.get(k.get("key"))
        if g and isinstance(k.get("value"), (int, float)):
            k["goal"] = {"target": g["target"], "progress": k["value"] / g["target"], "gap": k["value"] - g["target"],
                         "direction": g.get("direction", "at_least")}
        else:
            k["goal"] = None
    return res


class GoalIn(BaseModel):
    key: str = Field(min_length=3, max_length=250, pattern=r"^[A-Za-z0-9_]+:(sum|mean|median|count|nunique|min|max)$")
    target: float = Field(gt=0, lt=1e15)
    direction: Literal["at_least", "at_most"] = "at_least"


@router.put("/analytics/{dataset_id}/goals", dependencies=[Csrf])
async def set_goal(dataset_id: str, body: GoalIn, user: dict = CurrentUser):
    d, v = await _context(user, dataset_id, None)
    col = body.key.split(":")[0]
    if col != "records" and col not in {c["key"] for c in v["schema"]}:
        raise AppError(422, "invalid_goal", "This measure is not in the dataset")
    await get_db().dashboards.update_one(
        {"user_id": user["_id"], "dataset_id": d["_id"], "kind": "goal", "key": body.key},
        {"$set": {"target": body.target, "direction": body.direction, "updated_at": now_utc()},
         "$setOnInsert": {"created_at": now_utc()}}, upsert=True)
    return {"ok": True}


@router.delete("/analytics/{dataset_id}/goals/{key}", dependencies=[Csrf])
async def delete_goal(dataset_id: str, key: str, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    await get_db().dashboards.delete_one({"user_id": user["_id"], "dataset_id": d["_id"], "kind": "goal", "key": key})
    return {"ok": True}


# ------------------------------------------------------------------ chart suggestions ("auto charts") and pinned tiles

MAX_PINNED = 12


async def _pinned(user: dict, d: dict) -> list[dict]:
    docs = await get_db().dashboards.find({"user_id": user["_id"], "dataset_id": d["_id"], "kind": "pinned_chart"}) \
        .sort("created_at", 1).to_list(MAX_PINNED)
    return [{"id": str(p["_id"]), "title": p["title"], "chart_type": p["chart_type"], "plan": p["plan"], "reason": p.get("reason")}
            for p in docs]


class ViewIn(BaseModel):
    date_from: str | None = Field(default=None, pattern=ISO_DATE)
    date_to: str | None = Field(default=None, pattern=ISO_DATE)
    grain: Literal["day", "week", "month", "quarter", "year"] | None = None
    filters: list[DashboardFilterIn] = Field(default_factory=list, max_length=6)


class SuggestIn(ViewIn):
    use_ai: bool = True


@router.post("/analytics/{dataset_id}/chart-suggestions", dependencies=[Csrf, AiLimit])
async def chart_suggestions(dataset_id: str, body: SuggestIn | None = None, user: dict = CurrentUser):
    """Suggested charts for this dataset. With AI, the model picks from the rule menu; without, rules pick."""
    from app.ai.base import AIError, ChatMessage
    from app.ai.provider import get_provider
    from app.analytics import recommend

    body = body or SuggestIn()
    d, v = await _context(user, dataset_id, None)
    menu = recommend.candidates(v["schema"], d)
    if not menu:
        return {"charts": [], "source": "rules", "note": "No numeric or category columns to chart.", "rows_in_view": 0}
    picks, source, note, provider_name = [], "rules", None, None
    if body.use_ai:
        try:
            provider = get_provider(user)
            provider_name = provider.name
            text = await provider.chat([
                ChatMessage("system", "You are an experienced BI developer choosing charts for a dashboard."),
                ChatMessage("user", recommend.ai_prompt(v["schema"], menu, d["filename"]))], temperature=0.1, max_tokens=2500)
            picks = recommend.parse_ai_pick(text, menu)
            source = "ai" if picks else "rules"
            if not picks:
                note = "The AI reply could not be used, so the charts were chosen by rules."
        except AIError as e:
            note = e.message if e.code == "ai_not_configured" else f"AI was not available ({e.message}); the charts were chosen by rules."
    if not picks:
        picks = recommend.rule_pick(menu)
    try:
        out = await jobs.run_limited("analytics", get_settings().query_timeout_seconds * 3, jobs.suggest_job,
                                     str(svc.storage_path(v["storage_ref"])), v, d, picks,
                                     body.model_dump(exclude={"use_ai"}))
    except jobs.JobTimeout:
        raise AppError(504, "timeout", "Building the suggested charts took too long and was stopped.")
    if "error" in out:
        raise AppError(422, "invalid_options", out["error"])
    pinned_ids = {(p["chart_type"], json.dumps(p["plan"], sort_keys=True)) for p in await _pinned(user, d)}
    for c in out["ok"]["charts"]:
        c["pinned"] = (c["chart_type"], json.dumps(c["plan"], sort_keys=True)) in pinned_ids
    return {**out["ok"], "source": source, "provider": provider_name if source == "ai" else None, "note": note}


class PinIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    chart_type: Literal["line", "area", "horizontal_bar", "bar", "donut", "stacked_bar", "stacked_100_bar", "grouped_bar"]
    plan: dict
    reason: str | None = Field(default=None, max_length=300)


@router.post("/analytics/{dataset_id}/dashboard/tiles", status_code=201, dependencies=[Csrf])
async def pin_tile(dataset_id: str, body: PinIn, user: dict = CurrentUser):
    from app.analytics.plan import PlanError, QueryPlan, validate_plan

    d, v = await _context(user, dataset_id, None)
    plan = {k: val for k, val in body.plan.items() if k != "filters"}
    try:
        check = dict(plan)
        if check.get("time_grain") == "auto":
            check["time_grain"] = "month"
        validate_plan(QueryPlan(**check), v["schema"])
    except (PlanError, ValueError) as e:
        raise AppError(422, "invalid_plan", f"This chart cannot be pinned: {e}")
    db = get_db()
    if await db.dashboards.count_documents({"user_id": user["_id"], "dataset_id": d["_id"], "kind": "pinned_chart"}) >= MAX_PINNED:
        raise AppError(400, "too_many", f"A dashboard can hold up to {MAX_PINNED} pinned charts. Remove one first.")
    doc = {"user_id": user["_id"], "dataset_id": d["_id"], "kind": "pinned_chart", "title": body.title.strip(),
           "chart_type": body.chart_type, "plan": plan, "reason": body.reason, "created_at": now_utc()}
    doc["_id"] = (await db.dashboards.insert_one(doc)).inserted_id
    return {"id": str(doc["_id"]), "title": doc["title"]}


@router.delete("/analytics/{dataset_id}/dashboard/tiles/{tile_id}", dependencies=[Csrf])
async def unpin_tile(dataset_id: str, tile_id: str, user: dict = CurrentUser):
    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    res = await get_db().dashboards.delete_one({"_id": parse_oid(tile_id, "Tile"), "user_id": user["_id"],
                                                "dataset_id": d["_id"], "kind": "pinned_chart"})
    if not res.deleted_count:
        raise AppError(404, "not_found", "Pinned chart not found")
    return {"ok": True}


# ------------------------------------------------------------------ insights (Phase 4d)

class InsightsIn(BaseModel):
    focus_measure: str | None = Field(default=None, max_length=200)
    date_from: str | None = Field(default=None, max_length=20)
    date_to: str | None = Field(default=None, max_length=20)
    max_insights: int = Field(default=10, ge=1, le=30)
    refresh: bool = False


@router.post("/analytics/{dataset_id}/insights", dependencies=[Csrf])
async def insights(dataset_id: str, body: InsightsIn | None = None, user: dict = CurrentUser):
    from app.analytics.insights import InsightOptions

    body = body or InsightsIn()
    d, v = await _context(user, dataset_id, None)
    opts = InsightOptions(body.focus_measure, body.date_from, body.date_to, body.max_insights)
    db = get_db()
    if not body.refresh:
        cached = await db.analyses.find_one({"user_id": user["_id"], "dataset_id": d["_id"], "version_id": v["_id"],
                                             "analysis_type": "insights", "options_key": opts.key()}, sort=[("created_at", -1)])
        if cached:
            return {**cached["result_summary"], "analysis_id": str(cached["_id"]), "cached": True}
    try:
        out = await jobs.run_limited("analytics", get_settings().query_timeout_seconds * 3, jobs.insights_job,
                                     str(svc.storage_path(v["storage_ref"])), v, d, opts.__dict__)
    except jobs.JobTimeout:
        raise AppError(504, "timeout", "Finding insights took too long and was stopped. Try a date range.")
    if "error" in out:
        raise AppError(422, "invalid_options", out["error"])
    res = out["ok"]
    top = res["insights"][0]["headline"] if res["insights"] else "No insights passed the thresholds"
    aid = await record_analysis(user, d, v, "insights", "Automated insights", res, None, top)
    await db.analyses.update_one({"_id": __import__("bson").ObjectId(aid)}, {"$set": {"options_key": opts.key()}})
    return {**res, "analysis_id": aid, "cached": False}


@router.get("/analytics/{dataset_id}/insights")
async def cached_insights(dataset_id: str, user: dict = CurrentUser):
    d, v = await _context(user, dataset_id, None)
    cached = await get_db().analyses.find_one({"user_id": user["_id"], "dataset_id": d["_id"], "version_id": v["_id"],
                                               "analysis_type": "insights"}, sort=[("created_at", -1)])
    if not cached:
        return {"insights": None, "dataset_version": v["version_number"]}
    return {**cached["result_summary"], "analysis_id": str(cached["_id"]), "cached": True}


class ExplainIn(BaseModel):
    analysis_id: str
    insight_ids: list[str] | None = Field(default=None, max_length=10)


def _numbers(obj) -> list[float]:
    out = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, dict):
        for v in obj.values():
            out += _numbers(v)
    if isinstance(obj, list):
        for v in obj:
            out += _numbers(v)
    return out


@router.post("/analytics/{dataset_id}/insights/explain", dependencies=[Csrf, AiLimit])
async def explain_insights(dataset_id: str, body: ExplainIn, user: dict = CurrentUser):
    import json as _json
    import logging as _logging

    from app.ai.base import AIError, ChatMessage
    from app.ai.provider import check_numbers, get_provider
    from app.api.ai import ai_http_error

    d = await svc.get_dataset(user, parse_oid(dataset_id, "Dataset"))
    a = await get_db().analyses.find_one({"_id": parse_oid(body.analysis_id, "Analysis"), "user_id": user["_id"],
                                          "dataset_id": d["_id"], "analysis_type": "insights"})
    if not a:
        raise AppError(404, "not_found", "Insights not found")
    items = [i for i in a["result_summary"]["insights"] if not body.insight_ids or i["id"] in body.insight_ids][:5]
    if not items:
        raise AppError(400, "bad_request", "There are no insights to explain")
    payload = [{"headline": i["headline"], "detail": i["detail"], "numbers": i["evidence"]["numbers"], "caveats": i["caveats"]} for i in items]
    try:
        provider = get_provider(user)
        text = await provider.chat([
            ChatMessage("system", "Rewrite these verified data insights in plain, friendly language for a non-technical reader. "
                                  "Use only numbers that appear in the input, copied exactly; do not calculate new numbers. "
                                  "Keep every caveat. Never claim causes. One short paragraph per insight."),
            ChatMessage("user", _json.dumps(payload, default=str))], temperature=0.2, max_tokens=2000)
    except AIError as e:
        raise ai_http_error(e)
    allowed = _numbers([i["evidence"]["numbers"] for i in items])
    # Numbers quoted in the templates (already verified) are allowed too.
    from app.ai.provider import extract_numbers
    for i in items:
        for tok in extract_numbers(i["headline"] + " " + i["detail"]):
            t = tok.replace(",", "").replace("−", "-").strip("$€£₹").rstrip("%")
            try:
                allowed.append(float(t) / (100 if tok.endswith("%") else 1))
                allowed.append(float(t))
            except ValueError:
                pass
    checked, bad = check_numbers(text, allowed)
    if bad:
        _logging.getLogger("app.ai").warning("AI explanation contained unverified numbers: %s (analysis=%s)", bad, body.analysis_id)
    return {"text": checked, "unverified": bad, "label": "AI-written, numbers verified" if not bad else
            "AI-written; numbers marked [unverified] did not match the results", "provider": provider.name}

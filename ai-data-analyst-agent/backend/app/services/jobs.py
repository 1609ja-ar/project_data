"""CPU-heavy work that runs outside the event loop (process pool by default).

Functions here are top-level and take/return plain data so they can run in worker processes.
Time-limited work goes through `run_limited`, which kills the worker processes on timeout.
"""
from __future__ import annotations

import asyncio
import concurrent.futures as cf
import logging
from pathlib import Path

import pandas as pd

from app.core.config import get_settings

log = logging.getLogger("app.jobs")
_executor: cf.Executor | None = None
_pools: dict[str, cf.Executor] = {}


class JobTimeout(Exception):
    pass


def get_executor() -> cf.Executor:
    global _executor
    if _executor is None:
        s = get_settings()
        if s.cleaning_executor == "process":
            _executor = cf.ProcessPoolExecutor(max_workers=s.cleaning_workers)
        else:
            _executor = cf.ThreadPoolExecutor(max_workers=s.cleaning_workers, thread_name_prefix="clean")
    return _executor


async def run_job(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(get_executor(), fn, *args)


def _pool(name: str, force_process: bool) -> cf.Executor:
    if name not in _pools:
        if force_process or get_settings().cleaning_executor == "process":
            _pools[name] = cf.ProcessPoolExecutor(max_workers=2)
        else:
            _pools[name] = cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix=name)
    return _pools[name]


def _kill_pool(name: str) -> None:
    pool = _pools.pop(name, None)
    if isinstance(pool, cf.ProcessPoolExecutor):
        # ProcessPoolExecutor has no public kill; terminate its workers so runaway work stops.
        for proc in list(getattr(pool, "_processes", {}).values()):
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


async def run_limited(name: str, timeout: float, fn, *args, force_process: bool = False):
    """Run fn in a named worker pool; on timeout the pool's processes are killed and recreated."""
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(_pool(name, force_process), fn, *args)
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        log.warning("Job in pool %s exceeded %ss; killing workers", name, timeout)
        _kill_pool(name)
        raise JobTimeout()
    except cf.process.BrokenProcessPool:
        _kill_pool(name)
        raise JobTimeout()


def shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
    for name in list(_pools):
        _kill_pool(name)


# ----------------------------------------------------------------------------- cleaning jobs

def clean_job(grid_path: str, merged: list, options: dict, out_path: str) -> dict:
    from app.cleaning import frames
    from app.cleaning.pipeline import CleaningOptions, run_cleaning

    grid = pd.read_parquet(grid_path)
    result = run_cleaning(grid, [tuple(m) for m in merged], CleaningOptions(**options))
    frames.write_parquet(result.frame, result.columns, Path(out_path))
    return {"columns": result.columns, "report": result.report, "rows": len(result.frame)}


def profile_job(parquet_path: str, columns: list[dict], roles: dict | None) -> dict:
    from app.cleaning import frames
    from app.cleaning.profile import build_schema
    from app.cleaning.suggestions import compute_suggestions

    frame = frames.read_parquet(Path(parquet_path), columns)
    schema = build_schema(frame, columns)
    return {"schema": schema, "suggestions": compute_suggestions(frame, schema, roles)}


def apply_job(parquet_path: str, schema: list[dict], suggestions: list[dict], selections: list[dict],
              out_path: str, roles: dict | None) -> dict:
    from app.cleaning import frames
    from app.cleaning.profile import build_schema
    from app.cleaning.suggestions import apply_suggestions, compute_suggestions

    frame = frames.read_parquet(Path(parquet_path), schema)
    rows_before = len(frame)
    new_frame, cols, steps, new_roles = apply_suggestions(frame, schema, suggestions, selections)
    if not steps:
        return {"steps": [], "roles": new_roles}
    new_schema = build_schema(new_frame, cols)
    frames.write_parquet(new_frame, new_schema, Path(out_path))
    return {"steps": steps, "roles": new_roles, "schema": new_schema, "rows_before": rows_before,
            "rows_after": len(new_frame), "suggestions": compute_suggestions(new_frame, new_schema, new_roles or roles)}


# ----------------------------------------------------------------------------- analytics jobs

def _load(parquet_path: str, schema: list[dict]):
    from app.cleaning import frames

    path = Path(parquet_path)
    return frames.read_parquet(path, schema), frames.read_arrow(path)


def plan_job(parquet_path: str, version: dict, plan: dict) -> dict:
    """Returns {"ok": result} or {"error": (code, message, details)} so worker exceptions stay friendly."""
    from app.analytics.engine import CalculationCheckFailed
    from app.analytics.plan import PlanError, QueryPlan
    from app.analytics.runner import run_verified

    try:
        p = QueryPlan.model_validate(plan)
        frame, table = _load(parquet_path, version["schema"])
        return {"ok": run_verified(frame, table, version["schema"], p, version)}
    except PlanError as e:
        return {"error": ("invalid_plan", str(e), {"field": e.field})}
    except CalculationCheckFailed as e:
        return {"error": ("check_failed", "Calculation check failed", {"reason": str(e)[:500]})}


def _pivot_errors(fn):
    from app.analytics.engine import CalculationCheckFailed
    from app.analytics.plan import PlanError

    try:
        return {"ok": fn()}
    except PlanError as e:
        return {"error": ("invalid_plan", str(e), {"field": e.field})}
    except CalculationCheckFailed as e:
        return {"error": ("check_failed", "Calculation check failed", {"reason": str(e)[:500]})}
    except ValueError as e:  # pydantic validation of filters
        return {"error": ("invalid_plan", str(e).splitlines()[0][:300], {})}


def pivot_job(parquet_path: str, version: dict, spec: dict) -> dict:
    from app.analytics.pivot import build_pivot

    def run():
        frame, table = _load(parquet_path, version["schema"])
        return build_pivot(frame, table, version["schema"], version, spec)
    return _pivot_errors(run)


def pivot_xlsx_job(parquet_path: str, version: dict, spec: dict, filename: str) -> dict:
    from app.analytics.pivot import build_pivot
    from app.services.pivot_export import pivot_workbook

    def run():
        frame, table = _load(parquet_path, version["schema"])
        result = build_pivot(frame, table, version["schema"], version, spec)
        return pivot_workbook(result, filename, version), len(result["rows"])
    return _pivot_errors(run)


def profile_dataset_job(parquet_path: str, version: dict, dataset: dict) -> dict:
    from app.analytics.profile import build_profile

    frame, table = _load(parquet_path, version["schema"])
    return build_profile(frame, table, version, dataset)


# ----------------------------------------------------------------------------- SQL Workbench job

def _sql_value(v):
    import datetime as dt
    import math
    from decimal import Decimal
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, int):
        return v if abs(v) < 2 ** 53 else str(v)
    if isinstance(v, dt.datetime):
        return v.isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (dt.time, dt.timedelta)):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    if isinstance(v, (list, tuple, dict)):
        import json
        return json.dumps(v, default=str)[:1000]
    return str(v)


def _sql_dtype(type_name: str) -> str:
    t = type_name.upper()
    if t.startswith("DECIMAL"):
        return "decimal"
    if t in ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT"):
        return "integer"
    if t in ("FLOAT", "DOUBLE", "REAL"):
        return "float"
    if t == "DATE":
        return "date"
    if t.startswith("TIMESTAMP"):
        return "datetime"
    if t == "BOOLEAN":
        return "boolean"
    return "string"


def sql_job(executed_sql: str, tables: dict[str, str], max_rows: int, memory_limit: str) -> dict:
    """Runs validated SQL on a fresh, locked, in-memory DuckDB with only the given Parquet files registered.

    The Parquet files are read here with pyarrow; DuckDB itself has no file access.
    """
    import time

    import duckdb
    import pyarrow.parquet as pq

    from app.analytics.verify import connect_locked

    arrow = {}
    for name, path in tables.items():
        cols = [c for c in pq.read_schema(path).names if c != "_source_row"]
        arrow[name] = pq.read_table(path, columns=cols)
    con = connect_locked(memory_limit=memory_limit, threads=2)
    try:
        for name, table in arrow.items():
            con.register(name, table)
        t0 = time.perf_counter()
        try:
            cur = con.execute(executed_sql)
            rows = cur.fetchall()
            desc = cur.description or []
        except duckdb.Error as e:
            msg = str(e).strip()
            return {"error": msg.split("\n")[0][:500], "detail": msg[:1500]}
        duration_ms = round((time.perf_counter() - t0) * 1000, 1)
    finally:
        con.close()
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    names, seen = [], {}
    for d in desc:
        n = str(d[0])
        seen[n] = seen.get(n, 0) + 1
        names.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    columns = [{"key": n, "label": str(d[0]), "sql_type": str(d[1]), "dtype": _sql_dtype(str(d[1])), "semantic_type": "numeric"
                if _sql_dtype(str(d[1])) in ("integer", "float", "decimal") else "text"} for n, d in zip(names, desc)]
    return {"columns": columns, "rows": [[_sql_value(v) for v in r] for r in rows], "row_count": len(rows),
            "truncated": truncated, "duration_ms": duration_ms}


# ----------------------------------------------------------------------------- insights job

def insights_job(parquet_path: str, version: dict, dataset: dict, options: dict) -> dict:
    from app.analytics.insights import InsightOptions, generate_insights

    frame, table = _load(parquet_path, version["schema"])
    try:
        return {"ok": generate_insights(frame, table, version, dataset, InsightOptions(**options))}
    except ValueError as e:
        return {"error": str(e)}


# ----------------------------------------------------------------------------- dashboard job

def dashboard_job(parquet_path: str, version: dict, dataset: dict, options: dict, pinned: list | None = None) -> dict:
    from app.analytics.dashboard import DashboardOptions, build_dashboard

    frame, table = _load(parquet_path, version["schema"])
    try:
        return {"ok": build_dashboard(frame, table, version, dataset, DashboardOptions(**options), pinned)}
    except ValueError as e:  # includes PlanError
        return {"error": str(e)}


def _view_runner(frame, table, version, dataset, options: dict):
    """Runner + grain for a filtered view (date range and category filters, as on the dashboard)."""
    from app.analytics.dashboard import _Runner, apply_view, auto_grain, date_column, view_filters
    from app.analytics.profile import detect_roles

    schema = version["schema"]
    date = date_column(schema, detect_roles(schema, dataset.get("column_roles")))
    filters = view_filters(schema, date, options.get("date_from"), options.get("date_to"), options.get("filters") or [])
    mask, probe = apply_view(frame, schema, filters)
    grain = options.get("grain") or (auto_grain(frame.loc[mask, date["key"]]) if date else "month")
    return _Runner(frame, table, schema, version, filters), grain, int(mask.sum()), probe


def suggest_job(parquet_path: str, version: dict, dataset: dict, picks: list[dict], options: dict) -> dict:
    """Computes suggested charts (already chosen from the rule menu) under the current view."""
    from app.analytics.dashboard import describe_filters, run_chart

    frame, table = _load(parquet_path, version["schema"])
    try:
        run, grain, rows, probe = _view_runner(frame, table, version, dataset, options)
    except ValueError as e:
        return {"error": str(e)}
    charts = []
    for p in picks:
        t = run_chart(run, p["plan"], p["chart_type"], p["title"], grain, tid=p["id"], reason=p.get("why"))
        if t:
            t.update({"source": p.get("source"), "family": p.get("family"), "chart_type": p["chart_type"], "plan": p["plan"]})
            charts.append(t)
    return {"ok": {"charts": charts, "skipped": run.skipped, "rows_in_view": rows, "grain": grain,
                   "filters_applied": describe_filters(probe, version["schema"])}}


def ask_job(parquet_path: str, version: dict, dataset: dict, question: str, ai_parsed: dict | None) -> dict:
    """Plain-language question -> plan (AI-filled template or the rule parser) -> verified result + answer."""
    from app.analytics import ask
    from app.analytics.dashboard import _Runner, _tile, apply_view, auto_grain, chart_spec, date_column
    from app.analytics.engine import CalculationCheckFailed
    from app.analytics.plan import PlanError, describe_filters
    from app.analytics.profile import detect_roles
    from app.services.reports import _fmt

    schema = version["schema"]
    by_key = {c["key"]: c for c in schema}
    frame, table = _load(parquet_path, schema)
    try:
        parsed = ai_parsed or ask.parse_question(question, frame, schema, dataset)
        filters = [dict(f) for f in parsed["filters"]]
        ask.check_filter_values(frame, by_key, filters)
        mask, probe = apply_view(frame, schema, filters)
        plan = dict(parsed["plan"])
        date = date_column(schema, detect_roles(schema, dataset.get("column_roles")))
        if plan["operation"] == "trend":
            plan.setdefault("date_column", date["key"] if date else None)
            if plan.get("time_grain") in (None, "auto"):
                plan["time_grain"] = auto_grain(frame.loc[mask, plan["date_column"]]) if plan.get("date_column") in by_key else "month"
        run = _Runner(frame, table, schema, version, filters)
        title = ask.describe(plan, by_key, [])
        r = run(title, **plan)
        if r is None:
            return {"error": "The calculation check failed, so no answer is shown."}
    except ask.AskError as e:
        return {"error": str(e)}
    except (PlanError, ValueError) as e:
        return {"error": f"That question does not fit this dataset: {e}"}
    except CalculationCheckFailed:
        return {"error": "The calculation check failed, so no answer is shown."}
    chart_type = parsed.get("chart_type") or ("kpi" if not plan.get("group_by") and plan["operation"] != "trend" else "horizontal_bar")
    if chart_type == "kpi" and (plan.get("group_by") or plan["operation"] == "trend"):
        chart_type = "line" if plan["operation"] == "trend" else "horizontal_bar"
    if chart_type != "kpi" and not plan.get("group_by") and plan["operation"] != "trend":
        chart_type = "kpi"
    spec = {"type": "kpi"} if chart_type == "kpi" else chart_spec(plan, chart_type)
    groups = plan.get("group_by") or []
    tile = _tile("ask", "custom", title, "", r, spec, groups[0] if groups and plan["operation"] != "trend" else None)
    tile["series_dimension"] = spec.get("series")
    return {"ok": {"answer": ask.answer_text(r, plan, _fmt), "interpretation": ask.describe(plan, by_key, describe_filters(probe, schema)),
                   "plan": plan, "filters": filters, "chart_type": chart_type, "tile": tile, "rows_in_view": int(mask.sum()),
                   "ignored": parsed.get("ignored", [])}}


def report_job(parquet_path: str, version: dict, dataset: dict, options: dict) -> dict:
    """Every number a report needs, computed and verified here: dashboard KPIs and charts plus insights."""
    from app.analytics.dashboard import DashboardOptions, build_dashboard
    from app.analytics.insights import InsightOptions, generate_insights

    frame, table = _load(parquet_path, version["schema"])
    try:
        dash = build_dashboard(frame, table, version, dataset, DashboardOptions(
            date_from=options.get("date_from"), date_to=options.get("date_to"), filters=options.get("filters") or []))
        ins = generate_insights(frame, table, version, dataset, InsightOptions(
            date_from=options.get("date_from"), date_to=options.get("date_to"), max_insights=8))
    except ValueError as e:
        return {"error": str(e)}
    return {"ok": {"dashboard": dash, "insights": ins}}

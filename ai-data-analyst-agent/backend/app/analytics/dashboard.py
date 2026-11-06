"""Automatic dashboard: KPI tiles, trend, breakdowns and a summary table for any cleaned dataset.

This module only decides which query plans to run and how to lay the results out. Every number shown
comes from `run_verified` (Pandas result checked by DuckDB); nothing here calculates a reported value.
Choice rules are documented in docs/METRICS.md ("Dashboard").
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

import pandas as pd
import pyarrow as pa

from app.analytics.engine import CalculationCheckFailed, filter_mask
from app.analytics.plan import NUMERIC, QueryPlan, describe_filters, validate_plan
from app.analytics.profile import detect_roles

GRAINS = ("day", "week", "month", "quarter", "year")
MAX_BREAKDOWNS = 3
TOP_N = 8
TABLE_ROWS = 15
MAX_SHARE_GROUPS = 6
MAX_STACK_GROUPS = 6
MAX_STACK_PERIODS = 36
MAX_CATEGORY_GROUPS = 200
MAX_FILTER_VALUES = 100
SPARK_POINTS = 60

# Columns whose values are rates or positions: adding them up is meaningless, so they default to average.
AVERAGE_NAMES = re.compile(r"(^|_)(price|rate|ratio|score|rating|age|temp|temperature|avg|average|mean|margin|"
                           r"lat|latitude|lon|lng|longitude)(_|$)")
# Numeric columns that are labels, not measures (a "year" column summed is nonsense).
NOT_MEASURES = re.compile(r"(^|_)(id|year|month|week|day|quarter|zip|postal|postcode|code|phone|number|no)(_|$)")


@dataclass
class DashboardOptions:
    measure: str | None = None
    aggregation: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    grain: str | None = None
    filters: list[dict] = field(default_factory=list)  # [{"column": key, "values": [...]}]

    def key(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, default=str).encode()).hexdigest()[:16]

    def is_default(self) -> bool:
        return self == DashboardOptions()


def measure_candidates(schema: list[dict]) -> list[dict]:
    return [c for c in schema if c["dtype"] in NUMERIC and c["semantic_type"] not in ("id", "percent")
            and not NOT_MEASURES.search(c["key"])]


def default_aggregation(col: dict, roles: dict) -> str:
    if roles.get("price") == col["key"] or AVERAGE_NAMES.search(col["key"]):
        return "mean"
    return "sum"


def dimension_candidates(schema: list[dict]) -> list[dict]:
    """Category columns, low-cardinality ones first (they make readable charts), then schema order."""
    cands = [(i, c) for i, c in enumerate(schema) if c["dtype"] == "string" and c["semantic_type"] == "category"
             and 2 <= (c.get("unique") or 0) <= MAX_CATEGORY_GROUPS]
    cands.sort(key=lambda t: (t[1]["unique"] > 30, t[0]))
    return [c for _, c in cands]


def auto_grain(dates: pd.Series) -> str:
    """Grain that gives a readable number of points for the visible date span."""
    s = dates.dropna()
    if s.empty:
        return "month"
    days = (s.max() - s.min()).days
    if days <= 62:
        return "day"
    if days <= 26 * 7:
        return "week"
    if days <= 4 * 366:
        return "month"
    if days <= 12 * 366:
        return "quarter"
    return "year"


def _iso(ts) -> str | None:
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d")


class _Runner:
    def __init__(self, frame, table, schema, version, filters):
        self.frame, self.table, self.schema, self.version, self.filters = frame, table, schema, version, filters
        self.skipped: list[dict] = []

    def __call__(self, title: str, **plan) -> dict | None:
        from app.analytics.runner import run_verified

        try:
            return run_verified(self.frame, self.table, self.schema,
                                QueryPlan(filters=[dict(f) for f in self.filters], **plan), self.version)
        except CalculationCheckFailed:
            self.skipped.append({"tile": title, "reason": "The calculation check failed, so this tile is hidden."})
            return None


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _label(col: dict | None, agg: str) -> str:
    if col is None:
        return "Records"
    return {"sum": "Total", "mean": "Average", "nunique": "Distinct"}.get(agg, agg.capitalize()) + " " + col["display_name"]


def _metric(col: dict | None, agg: str) -> dict:
    return {"aggregation": agg, **({"metric_column": col["key"]} if col else {})}


def _kpi(run: _Runner, kid: str, label: str, col: dict | None, agg: str, date: dict | None, grain: str):
    r = run(label, operation="aggregate", **_metric(col, agg))
    if not r:
        return None, None
    d = r["calculation_details"]
    kpi = {"id": kid, "key": f"{col['key'] if col else 'records'}:{agg}", "label": label, "value": r["rows"][0][0],
           "column": r["columns"][0], "rows_used": d["rows_used"], "how_calculated": d, "change": None, "spark": []}
    trend = None
    if date:
        trend = run(f"{label} over time", operation="trend", date_column=date["key"], time_grain=grain, **_metric(col, agg))
        rows = trend["rows"] if trend else []
        if rows:
            # Trend rows: [period, period_start, value, growth, partial]
            kpi["spark"] = [{"period": row[0], "value": row[2], "partial": row[4]} for row in rows[-SPARK_POINTS:]]
            complete = [row for row in rows if not row[4]]
            # The engine fills growth only when the previous period is complete and non-zero.
            if len(complete) >= 2 and complete[-1][3] is not None:
                kpi["change"] = {"pct": complete[-1][3], "current": complete[-1][2], "previous": complete[-2][2],
                                 "period": complete[-1][0], "previous_period": complete[-2][0], "grain": grain}
    return kpi, trend


def _tile(tid, kind, title, subtitle, result, spec, dimension=None, extra=None) -> dict:
    d = result["calculation_details"]
    return {"id": tid, "kind": kind, "title": title, "subtitle": subtitle, "dimension": dimension,
            "chart": {"spec": spec, "columns": result["columns"], "rows": result["rows"]},
            "other": result.get("other"), "groups_total": result.get("groups_total"),
            "rows_used": d["rows_used"], "warnings": d.get("warnings", []), "how_calculated": d, **(extra or {})}


CHART_TYPES = ("line", "area", "horizontal_bar", "bar", "donut", "stacked_bar", "stacked_100_bar", "grouped_bar")


def chart_spec(plan: dict, chart_type: str) -> dict:
    """x/y/series for a chart of a plan's result (columns are named by the engine)."""
    groups = plan.get("group_by") or []
    if plan["operation"] == "trend":
        return {"type": chart_type, "x": "period", "y": "value", **({"series": groups[0]} if groups else {})}
    return {"type": chart_type, "x": groups[0], "y": "value", **({"series": groups[1]} if len(groups) > 1 else {})}


def run_chart(run: _Runner, plan: dict, chart_type: str, title: str, grain: str, tid: str, reason: str | None = None) -> dict | None:
    """Runs a stored or suggested chart plan under the current view. Plans carry no filters of their own;
    a trend plan with time_grain "auto" uses the view's grain. Returns None (with a skip note) if the plan
    no longer fits the dataset, e.g. after re-cleaning renamed a column."""
    from app.analytics.plan import PlanError

    p = {k: v for k, v in plan.items() if k != "filters"}
    if p.get("time_grain") in (None, "auto"):
        p["time_grain"] = grain
    try:
        r = run(title, **p)
    except (PlanError, ValueError) as e:
        run.skipped.append({"tile": title, "reason": f"No longer fits this dataset: {e}"})
        return None
    if not r or not r["rows"]:
        return None
    groups = r.get("groups_total")
    sub = (f"Top {len(r['rows'])} of {groups}" if groups and groups > len(r["rows"]) else
           _count(groups, "value") if groups else f"by {p['time_grain']}" if p["operation"] == "trend" else "")
    spec = chart_spec(p, chart_type)
    # Click-to-filter works on the x category; a trend's x is a period, so it has no filter dimension.
    t = _tile(tid, "custom", title, sub, r, spec, None if p["operation"] == "trend" else spec["x"])
    t["series_dimension"] = spec.get("series")
    t["reason"] = reason
    t["plan"] = p
    return t


def _summary_table(run: _Runner, dim: dict, measure: dict | None, agg: str, second: dict | None, second_agg: str):
    """Group table: primary value, share, records, average (when the primary is a total), second measure.
    Each column is its own verified result, joined on the group key."""
    title = f"{dim['display_name']} summary"
    main = run(title, operation="top_n", group_by=[dim["key"]], limit=TABLE_ROWS, **_metric(measure, agg))
    if not main or not main["rows"]:
        return None
    ci = {c["key"]: i for i, c in enumerate(main["columns"])}
    columns = [main["columns"][0], {**main["columns"][ci["value"]], "key": "value", "label": _label(measure, agg)}]
    if "share" in ci:
        columns.append(main["columns"][ci["share"]])
    # Records = rows counted in each group; rows with an empty measure are skipped, and the label says so.
    records_label = "Records with a value" if main["calculation_details"]["rows_skipped"] else "Records"
    with_records = measure is not None  # without a measure the value already is the record count
    if with_records:
        columns.append({"key": "records", "label": records_label, "dtype": "integer", "semantic_type": "numeric"})
    extra_cols = []
    if measure is not None and agg == "sum":
        extra_cols.append(("average", _label(measure, "mean"), measure, "mean"))
    if second is not None:
        extra_cols.append(("second", _label(second, second_agg), second, second_agg))
    lookups = []
    for key, label, col, a in extra_cols:
        r = run(f"{title}: {label}", operation="aggregate", group_by=[dim["key"]], limit=1000, **_metric(col, a))
        if not r:
            continue
        vi = next(i for i, c in enumerate(r["columns"]) if c["key"] == "value")
        lookups.append({row[0]: row[vi] for row in r["rows"]})
        columns.append({**r["columns"][vi], "key": key, "label": label})
    rows = []
    for row in main["rows"]:
        out = [row[0], row[ci["value"]]]
        if "share" in ci:
            out.append(row[ci["share"]])
        if with_records:
            out.append(row[ci["rows"]])
        out += [lk.get(row[0]) for lk in lookups]
        rows.append(out)
    groups = main.get("groups_total") or len(rows)
    subtitle = (f"Top {len(rows)} of {groups} by {_label(measure, agg).lower()}" if groups > len(rows)
                else f"{_count(groups, 'value')}, sorted by {_label(measure, agg).lower()}")
    t = _tile("table", "table", title, subtitle, main, {"type": "table"}, dim["key"])
    t["chart"] = {"spec": {"type": "table"}, "columns": columns, "rows": rows}
    return t


def date_column(schema: list[dict], roles: dict) -> dict | None:
    by_key = {c["key"]: c for c in schema}
    return by_key.get(roles.get("date")) or next((c for c in schema if c["dtype"] in ("date", "datetime")), None)


def view_filters(schema: list[dict], date: dict | None, date_from: str | None, date_to: str | None,
                 category_filters: list[dict]) -> list[dict]:
    """Plan filters for a dashboard-style view: date range plus `in` filters on category columns.
    Shared by the dashboard, chart suggestions, reports and filtered exports so they always agree."""
    dim_keys = {c["key"] for c in dimension_candidates(schema)}
    if (date_from or date_to) and not date:
        raise ValueError("This dataset has no date column to filter on")
    filters: list[dict] = []
    if date_from:
        filters.append({"column": date["key"], "op": "gte", "value": date_from})
    if date_to:
        if date["dtype"] == "datetime":  # include the whole end day
            nxt = (pd.Timestamp(date_to) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            filters.append({"column": date["key"], "op": "lt", "value": nxt})
        else:
            filters.append({"column": date["key"], "op": "lte", "value": date_to})
    for f in category_filters or []:
        if f.get("column") not in dim_keys:
            raise ValueError(f"'{f.get('column')}' cannot be used as a filter")
        vals = [str(v) for v in (f.get("values") or []) if v is not None]
        if vals:
            filters.append({"column": f["column"], "op": "in", "value": vals})
    return filters


def apply_view(frame: pd.DataFrame, schema: list[dict], filters: list[dict]):
    """(mask, validated probe plan). Raises PlanError (a ValueError) for bad filter values."""
    probe = QueryPlan(operation="filter_count", filters=[dict(f) for f in filters])
    validate_plan(probe, schema)
    return filter_mask(frame, probe, {c["key"]: c for c in schema}), probe


def build_dashboard(frame: pd.DataFrame, table: pa.Table, version: dict, dataset: dict, opts: DashboardOptions,
                    pinned: list[dict] | None = None) -> dict:
    schema = version["schema"]
    by_key = {c["key"]: c for c in schema}
    roles = detect_roles(schema, dataset.get("column_roles"))
    measures = measure_candidates(schema)
    dims = dimension_candidates(schema)
    date = date_column(schema, roles)

    # ---- options
    if opts.measure:
        if opts.measure not in {m["key"] for m in measures}:
            raise ValueError("The measure must be one of this dataset's numeric measure columns")
        measure = by_key[opts.measure]
    else:
        preferred = roles.get("revenue") or roles.get("quantity")
        measure = by_key[preferred] if preferred in {m["key"] for m in measures} else (measures[0] if measures else None)
    agg = opts.aggregation or (default_aggregation(measure, roles) if measure else "count")
    if measure is None:
        agg = "count"
    if opts.grain and opts.grain not in GRAINS:
        raise ValueError("Unknown time grain")
    filters = view_filters(schema, date, opts.date_from, opts.date_to, opts.filters)
    mask, probe = apply_view(frame, schema, filters)
    view = frame.loc[mask]
    grain = opts.grain or (auto_grain(view[date["key"]]) if date else "month")

    out = {
        "dataset_version": version["version_number"], "row_count": int(len(frame)), "rows_in_view": int(mask.sum()),
        "measure": {"key": measure["key"], "label": measure["display_name"]} if measure else None,
        "aggregation": agg,
        "measures": [{"key": m["key"], "label": m["display_name"], "default_aggregation": default_aggregation(m, roles)}
                     for m in measures],
        "date_column": {"key": date["key"], "label": date["display_name"], "dtype": date["dtype"]} if date else None,
        "date_bounds": {"min": _iso(frame[date["key"]].min()), "max": _iso(frame[date["key"]].max())} if date else None,
        "view_bounds": {"min": _iso(view[date["key"]].min()), "max": _iso(view[date["key"]].max())} if date else None,
        "grain": grain, "grain_auto": opts.grain is None,
        "dimensions": [{"key": c["key"], "label": c["display_name"], "unique": c["unique"],
                        "values": [str(v) for v in frame[c["key"]].dropna().value_counts().index[:MAX_FILTER_VALUES]]}
                       for c in dims[:6]],
        "options": asdict(opts),
        "filters_applied": describe_filters(probe, schema),
        "kpis": [], "tiles": [], "skipped": [],
    }
    if not out["rows_in_view"]:
        return out

    run = _Runner(frame, table, schema, version, filters)
    second = next((m for m in measures if measure is None or m["key"] != measure["key"]), None)
    second_agg = default_aggregation(second, roles) if second else "sum"

    # ---- KPIs (each with its own verified trend for the sparkline and period change)
    main_kpi, main_trend = _kpi(run, "primary", _label(measure, agg), measure, agg, date, grain)
    kpi_specs = [("records", "Records", None, "count")] if measure is not None else []
    if measure is not None and agg == "sum":
        kpi_specs.append(("average", f"Average {measure['display_name']} per record", measure, "mean"))
    if second is not None:
        kpi_specs.append(("second", _label(second, second_agg), second, second_agg))
    if measure is None and dims:
        kpi_specs.append(("distinct", f"Distinct {dims[0]['display_name']}", dims[0], "nunique"))
    out["kpis"] = [k for k in [main_kpi] + [_kpi(run, *spec, date, grain)[0] for spec in kpi_specs[:3]] if k]

    label = _label(measure, agg)
    tiles = []
    # ---- trend
    if main_trend and main_trend["rows"]:
        n = len(main_trend["rows"])
        span = f"{main_trend['rows'][0][0]} to {main_trend['rows'][-1][0]}"
        tiles.append(_tile("trend", "trend", f"{label} by {grain}", f"{_count(n, grain)} · {span}", main_trend,
                           {"type": "area" if n > 24 else "line", "x": "period", "y": "value"}))
        if agg in ("sum", "count", "mean"):
            from app.analytics.forecast import linear_forecast
            tiles[-1]["forecast"] = linear_forecast(main_trend["rows"], grain)

    # ---- breakdowns: one part-to-whole donut (few groups, additive), the rest ranked bars
    donut_used = False
    for dim in dims[:MAX_BREAKDOWNS]:
        r = run(f"{label} by {dim['display_name']}", operation="top_n", group_by=[dim["key"]], limit=TOP_N, **_metric(measure, agg))
        if not r or not r["rows"]:
            continue
        has_share = any(c["key"] == "share" for c in r["columns"])
        groups = r.get("groups_total") or len(r["rows"])
        if has_share and groups <= MAX_SHARE_GROUPS and not donut_used:
            donut_used = True
            tiles.append(_tile(f"share_{dim['key']}", "share", f"Share of {label.lower()} by {dim['display_name']}",
                               _count(groups, "value"), r, {"type": "donut", "x": dim["key"], "y": "value"}, dim["key"]))
            continue
        sub = f"Top {len(r['rows'])} of {groups}" if groups > len(r["rows"]) else _count(groups, "value")
        tiles.append(_tile(f"by_{dim['key']}", "breakdown", f"{label} by {dim['display_name']}", sub, r,
                           {"type": "horizontal_bar", "x": dim["key"], "y": "value"}, dim["key"]))

    # ---- trend split by a small category (stacked when additive)
    stack_dim = next((c for c in dims if c["unique"] <= MAX_STACK_GROUPS), None)
    if date and stack_dim and main_trend and main_trend["rows"]:
        r = run(f"{label} by {grain} and {stack_dim['display_name']}", operation="trend", date_column=date["key"],
                time_grain=grain, group_by=[stack_dim["key"]], **_metric(measure, agg))
        if r and r["rows"]:
            periods = len({row[0] for row in r["rows"]})
            stacked = agg in ("sum", "count") and periods <= MAX_STACK_PERIODS
            tiles.append(_tile(f"split_{stack_dim['key']}", "split", f"{label} by {grain} and {stack_dim['display_name']}",
                               _count(periods, grain),
                               r, {"type": "stacked_bar" if stacked else "line", "x": "period", "y": "value",
                                   "series": stack_dim["key"]}, stack_dim["key"]))

    # ---- summary table
    if dims:
        t = _summary_table(run, dims[0], measure, agg, second, second_agg)
        if t:
            tiles.append(t)

    out["tiles"] = tiles
    # ---- tiles the user pinned (from chart suggestions); they follow the same view filters
    out["custom_tiles"] = []
    for p in pinned or []:
        t = run_chart(run, p["plan"], p["chart_type"], p["title"], grain, tid=p["id"], reason=p.get("reason"))
        if t:
            out["custom_tiles"].append(t)
    out["skipped"] = run.skipped
    if not date:
        out["skipped"].append({"tile": "Trend", "reason": "No date column, so there is no trend or period change."})
    if not dims:
        out["skipped"].append({"tile": "Breakdowns", "reason": "No category column with 2-200 distinct values."})
    return out

"""Executes validated query plans with Pandas on the active cleaned version.

Accuracy rules applied here (see docs/METRICS.md):
- nulls are skipped and counted (rows_in = rows_used + rows_skipped);
- money is summed as exact integer minor units; means/medians are exact Decimals;
- comparisons never match empty values (same semantics as SQL);
- reconciliation checks run before a result is returned, then the DuckDB engine re-computes the
  headline numbers independently (app.analytics.verify).
"""
from __future__ import annotations

import math
from decimal import Decimal, localcontext

import numpy as np
import pandas as pd

from app.analytics.plan import NUMERIC, QueryPlan, describe_filters, validate_plan

EMPTY_LABEL = None  # group key for empty values (shown as "(empty)" by the UI)
MIN_TREND_POINTS = 8
AGG_LABEL = {"sum": "Sum", "mean": "Average", "count": "Count", "min": "Minimum", "max": "Maximum",
             "median": "Median", "nunique": "Distinct count"}


class CalculationCheckFailed(Exception):
    pass


# ------------------------------------------------------------------ helpers

def dec(minor: int, scale: int) -> Decimal:
    return Decimal(int(minor)).scaleb(-scale)


def money_div(total_minor: int, n: int, scale: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 34
        return (Decimal(int(total_minor)) / Decimal(n)).scaleb(-scale)


def to_json_number(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, (pd.Timestamp,)):
        return v.strftime("%Y-%m-%d") if v == v.normalize() else v.isoformat()
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def key_value(v, col: dict | None):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return EMPTY_LABEL
    if col and col["dtype"] in ("date", "datetime"):
        ts = pd.Timestamp(v)
        return ts.strftime("%Y-%m-%d") if ts == ts.normalize() else ts.isoformat()
    if col and col["dtype"] == "boolean":
        return bool(v)
    if col and col["dtype"] == "integer":
        return int(v)
    return str(v)


def filter_mask(frame: pd.DataFrame, plan: QueryPlan, by_key: dict) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for f in plan.filters:
        c = by_key[f.column]
        s = frame[f.column]
        val = f.value

        def conv(x):
            if c["dtype"] == "decimal":
                return float(Decimal(str(x)) * (10 ** c.get("scale", 2)))
            return x

        present = s.notna()
        if f.op == "is_null":
            m = ~present
        elif f.op == "not_null":
            m = present
        elif f.op == "eq":
            m = present & (s == conv(val))
        elif f.op == "ne":
            m = present & (s != conv(val))
        elif f.op == "gt":
            m = present & (s > conv(val))
        elif f.op == "gte":
            m = present & (s >= conv(val))
        elif f.op == "lt":
            m = present & (s < conv(val))
        elif f.op == "lte":
            m = present & (s <= conv(val))
        elif f.op == "between":
            lo, hi = conv(val[0]), conv(val[1])
            m = present & (s >= lo) & (s <= hi)
        elif f.op == "in":
            m = present & s.isin([conv(v) for v in val])
        elif f.op == "not_in":
            m = present & ~s.isin([conv(v) for v in val])
        elif f.op == "contains":
            m = present & s.astype("string").str.lower().str.contains(str(val).lower(), regex=False)
        else:  # pragma: no cover - validated earlier
            raise ValueError(f.op)
        mask &= m.fillna(False).astype(bool)
    return mask


def aggregate_series(s: pd.Series, col: dict | None, agg: str):
    """Exact aggregate of one series (nulls skipped). Money returns Decimal."""
    present = s.dropna()
    n = len(present)
    if agg == "count":
        return n
    if agg == "nunique":
        return int(present.nunique())
    if n == 0:
        return None
    dtype = col["dtype"] if col else None
    if dtype == "decimal":
        scale = col.get("scale", 2)
        ints = present.astype("int64")
        if agg == "sum":
            return dec(int(ints.sum()), scale)
        if agg == "mean":
            return money_div(int(ints.sum()), n, scale)
        if agg == "min":
            return dec(int(ints.min()), scale)
        if agg == "max":
            return dec(int(ints.max()), scale)
        if agg == "median":
            srt = np.sort(ints.to_numpy())
            mid = n // 2
            m2 = Decimal(int(srt[mid])) if n % 2 else (Decimal(int(srt[mid - 1])) + Decimal(int(srt[mid]))) / 2
            return m2.scaleb(-scale)
    if dtype in ("date", "datetime"):
        return present.min() if agg == "min" else present.max()
    if dtype == "integer":
        ints = present.astype("int64")
        if agg == "sum":
            return int(ints.sum())
        if agg in ("min", "max"):
            return int(getattr(ints, agg)())
        if agg == "mean":
            return float(Decimal(int(ints.sum())) / Decimal(n))
        return float(ints.median())
    vals = present.astype("float64")
    return float(getattr(vals, agg)())


def grain_start(s: pd.Series, grain: str) -> pd.Series:
    d = s.dt.normalize()
    if grain == "day":
        return d
    if grain == "week":
        return d - pd.to_timedelta(d.dt.day_of_week, unit="D")  # ISO weeks start Monday
    return d.dt.to_period({"month": "M", "quarter": "Q", "year": "Y"}[grain]).dt.start_time


def grain_end(start: pd.Timestamp, grain: str) -> pd.Timestamp:
    return {"day": start, "week": start + pd.Timedelta(days=6),
            "month": start + pd.offsets.MonthEnd(0), "quarter": start + pd.offsets.QuarterEnd(0),
            "year": start + pd.offsets.YearEnd(0)}[grain]


def next_start(start: pd.Timestamp, grain: str) -> pd.Timestamp:
    return {"day": start + pd.Timedelta(days=1), "week": start + pd.Timedelta(days=7),
            "month": start + pd.offsets.MonthBegin(1), "quarter": start + pd.offsets.QuarterBegin(1, startingMonth=1),
            "year": start + pd.offsets.YearBegin(1)}[grain]


def period_label(start: pd.Timestamp, grain: str) -> str:
    if grain == "day":
        return start.strftime("%Y-%m-%d")
    if grain == "week":
        iso = start.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if grain == "month":
        return start.strftime("%Y-%m")
    if grain == "quarter":
        return f"{start.year}-Q{(start.month - 1) // 3 + 1}"
    return str(start.year)


def _close(a, b, rel=1e-9) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a == b
    a, b = float(a), float(b)
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


# ------------------------------------------------------------------ main entry

def execute(frame: pd.DataFrame, schema: list[dict], plan: QueryPlan, version: dict) -> dict:
    by_key = {c["key"]: c for c in schema}
    validate_plan(plan, schema)
    rows_total = len(frame)
    mask = filter_mask(frame, plan, by_key)
    data = frame.loc[mask]
    rows_in = len(data)
    metric = by_key.get(plan.metric_column) if plan.metric_column else None
    checks: list[dict] = []
    warnings: list[str] = []

    op = plan.operation
    if op == "filter_count":
        result = _filter_count(data, rows_total)
        used, skipped = rows_in, 0
    elif op == "describe":
        result = _describe(data, metric)
        used = int(data[metric["key"]].notna().sum())
        skipped = rows_in - used
    else:
        need = pd.Series(True, index=data.index)
        if metric is not None:
            need &= data[metric["key"]].notna()
        if op == "trend":
            need &= data[plan.date_column].notna()
        work = data.loc[need]
        used, skipped = len(work), rows_in - len(work)
        if op == "trend":
            result = _trend(work, plan, by_key, metric, warnings, checks)
        else:
            result = _grouped(work, plan, by_key, metric, checks)

    checks.append({"name": "rows_in = rows_used + rows_skipped", "passed": rows_in == used + skipped,
                   "detail": f"{rows_in} = {used} + {skipped}"})
    failed = [c for c in checks if not c["passed"]]
    if failed:
        raise CalculationCheckFailed("; ".join(c["name"] for c in failed))

    metric_label = (f"{AGG_LABEL[plan.aggregation]} of {metric['display_name']}" if metric
                    else "Row count")
    details = {
        "dataset_version": version.get("version_number"), "version_id": str(version.get("_id", "")),
        "engine": "pandas", "plan": plan.model_dump(mode="json"),
        "filters_applied": describe_filters(plan, schema) or ["None"],
        "formula": _formula(plan, by_key, metric_label),
        "rows_total": rows_total, "rows_in": rows_in, "rows_used": used, "rows_skipped": skipped,
        "null_policy": "Empty values are skipped (never treated as 0). Comparison filters never match empty values.",
        "checks": checks, "warnings": warnings,
    }
    result["calculation_details"] = details
    result["metric_label"] = metric_label
    return result


def _formula(plan: QueryPlan, by_key: dict, metric_label: str) -> str:
    names = [by_key[g]["display_name"] for g in plan.group_by]
    if plan.operation == "filter_count":
        return "Count of rows matching the filters; share = matching rows ÷ all rows"
    if plan.operation == "describe":
        return f"Summary statistics of {by_key[plan.metric_column]['display_name']} over non-empty values"
    base = metric_label
    if plan.operation == "trend":
        return (f"{base} per {plan.time_grain} of {by_key[plan.date_column]['display_name']}"
                + (f", split by {names[0]}" if names else "")
                + "; growth % = (current − previous) ÷ |previous|, complete periods only")
    if names:
        base += " grouped by " + ", ".join(names)
    if plan.operation in ("top_n", "compare") or (plan.operation == "aggregate" and len(names) == 1):
        base += "; share = group value ÷ total of all groups (shown when every group value is ≥ 0)"
    return base


def _out_col(metric: dict | None, plan: QueryPlan, label: str) -> dict:
    if metric is None or plan.aggregation in ("count", "nunique"):
        return {"key": "value", "label": label, "dtype": "integer", "semantic_type": "numeric"}
    if metric["dtype"] in ("date", "datetime"):
        return {"key": "value", "label": label, "dtype": metric["dtype"], "semantic_type": "date"}
    out = {"key": "value", "label": label, "dtype": "float" if plan.aggregation in ("mean", "median") and metric["dtype"] == "integer" else metric["dtype"],
           "semantic_type": metric["semantic_type"]}
    if metric["dtype"] == "decimal":
        out.update({"currency": metric.get("currency"), "scale": metric.get("scale")})
    return out


def _grouped(work: pd.DataFrame, plan: QueryPlan, by_key: dict, metric: dict | None, checks: list) -> dict:
    agg = plan.aggregation
    mkey = metric["key"] if metric else None
    label = f"{AGG_LABEL[agg]} of {metric['display_name']}" if metric else "Row count"
    grand = aggregate_series(work[mkey], metric, agg) if mkey else len(work)
    gcols = [{"key": g, "label": by_key[g]["display_name"], "dtype": by_key[g]["dtype"],
              "semantic_type": by_key[g]["semantic_type"]} for g in plan.group_by]
    columns = gcols + [_out_col(metric, plan, label), {"key": "rows", "label": "Rows used", "dtype": "integer", "semantic_type": "numeric"}]

    if not plan.group_by:
        return {"columns": columns, "rows": [[to_json_number(grand), len(work)]], "total": to_json_number(grand),
                "chart_suggestion": {"type": "kpi", "value": "value"}, "_groups": {(): (grand, len(work))}}

    groups = []
    for keys, part in work.groupby(plan.group_by, dropna=False, sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        val = aggregate_series(part[mkey], metric, agg) if mkey else len(part)
        groups.append(([key_value(k, by_key[g]) for k, g in zip(keys, plan.group_by)], val, len(part)))

    # Reconciliation: additive aggregates must add up to the independently computed grand total.
    if agg in ("sum", "count") and groups:
        total_groups = sum((g[1] for g in groups if g[1] is not None), Decimal(0) if isinstance(grand, Decimal) else 0)
        checks.append({"name": "group totals add up to the grand total", "passed": _close(total_groups, grand),
                       "detail": f"{total_groups} vs {grand}"})
    checks.append({"name": "group row counts add up", "passed": sum(g[2] for g in groups) == len(work),
                   "detail": f"{sum(g[2] for g in groups)} vs {len(work)}"})

    def sort_key(g):
        v = g[1]
        if v is None:
            return (1, 0)
        num = float(v) if not isinstance(v, pd.Timestamp) else v.value
        return (0, -num if plan.order == "desc" else num)

    if plan.operation in ("top_n", "compare") or len(plan.group_by) == 1:
        groups.sort(key=sort_key)
    else:
        groups.sort(key=lambda g: [("" if k is None else str(k)) for k in g[0]])

    with_share = (len(plan.group_by) == 1 and agg in ("sum", "count") and grand not in (None, 0)
                  and all(g[1] is not None and g[1] >= 0 for g in groups))
    if with_share:
        columns.insert(len(gcols) + 1, {"key": "share", "label": "Share of total", "dtype": "float", "semantic_type": "percent"})
        shares = [float(Decimal(g[1]) / Decimal(grand)) if isinstance(grand, Decimal) else g[1] / grand for g in groups]
        checks.append({"name": "shares add up to 100%", "passed": abs(sum(shares) - 1.0) <= 1e-9, "detail": f"{sum(shares)!r}"})
    other = None
    shown = groups
    if plan.operation == "top_n" or len(groups) > plan.limit:
        shown = groups[: plan.limit]
        rest = groups[plan.limit:]
        if rest and agg in ("sum", "count"):
            other_val = sum((g[1] for g in rest if g[1] is not None), Decimal(0) if isinstance(grand, Decimal) else 0)
            other = {"groups": len(rest), "value": to_json_number(other_val), "rows": sum(g[2] for g in rest)}

    rows = []
    for i, g in enumerate(shown):
        row = [*g[0], to_json_number(g[1])]
        if with_share:
            row.append(shares[i])  # groups is sorted and `shown` is its prefix
        row.append(g[2])
        rows.append(row)
    if plan.operation == "compare" and agg not in ("count", "nunique") and grand is not None and metric and metric["dtype"] in NUMERIC:
        columns.append({"key": "vs_overall", "label": f"Difference from overall ({to_json_number(grand)})", "dtype": "float", "semantic_type": metric["semantic_type"],
                        **({"currency": metric.get("currency")} if metric.get("currency") else {})})
        for row, g in zip(rows, shown):
            row.append(None if g[1] is None else to_json_number(Decimal(str(g[1])) - Decimal(str(grand))))

    chart = {"type": "bar", "x": plan.group_by[0], "y": "value"}
    if len(plan.group_by) == 2:
        chart = {"type": "grouped_bar", "x": plan.group_by[0], "series": plan.group_by[1], "y": "value"}
    elif max((len(str(g[0][0])) for g in shown), default=0) > 14 or len(shown) > 12:
        chart["type"] = "horizontal_bar"
    return {"columns": columns, "rows": rows, "total": to_json_number(grand), "groups_total": len(groups),
            "other": other, "chart_suggestion": chart, "_groups": {tuple(g[0]): (g[1], g[2]) for g in groups}}


def _trend(work: pd.DataFrame, plan: QueryPlan, by_key: dict, metric: dict | None, warnings: list, checks: list) -> dict:
    agg, grain = plan.aggregation, plan.time_grain
    dkey = plan.date_column
    mkey = metric["key"] if metric else None
    label = f"{AGG_LABEL[agg]} of {metric['display_name']}" if metric else "Row count"
    split = plan.group_by[0] if plan.group_by else None
    if work.empty:
        return {"columns": [], "rows": [], "chart_suggestion": None, "periods": 0, "_groups": {}}
    starts = grain_start(work[dkey], grain)
    first, last = starts.min(), starts.max()
    periods = []
    p = first
    while p <= last and len(periods) < 5000:
        periods.append(p)
        p = next_start(p, grain)
    min_d, max_d = work[dkey].min().normalize(), work[dkey].max().normalize()
    partial = {first: grain != "day" and min_d > first, last: grain != "day" and max_d < grain_end(last, grain).normalize()}
    additive = agg in ("sum", "count")

    def series_for(sub: pd.DataFrame, sub_starts: pd.Series):
        vals, counts = {}, {}
        for st, part in sub.groupby(sub_starts, sort=True):
            vals[st] = aggregate_series(part[mkey], metric, agg) if mkey else len(part)
            counts[st] = len(part)
        return vals, counts

    columns = [{"key": "period", "label": f"{grain.capitalize()} ({by_key[dkey]['display_name']})", "dtype": "string", "semantic_type": "period"},
               {"key": "period_start", "label": "Period start", "dtype": "date", "semantic_type": "date"}]
    if split:
        columns.append({"key": split, "label": by_key[split]["display_name"], "dtype": by_key[split]["dtype"], "semantic_type": by_key[split]["semantic_type"]})
    columns += [_out_col(metric, plan, label), {"key": "growth", "label": "Growth vs previous period", "dtype": "float", "semantic_type": "percent"},
                {"key": "partial", "label": "Partial period", "dtype": "boolean", "semantic_type": "boolean"}]

    rows = []
    verify_groups = {}
    groups = [(None, work, starts)] if not split else [
        (key_value(k, by_key[split]), part, starts.loc[part.index]) for k, part in work.groupby(split, dropna=False, sort=True)]
    for gkey, sub, sub_starts in groups:
        vals, counts = series_for(sub, sub_starts)
        prev = None
        for p in periods:
            v = vals.get(p, (Decimal(0) if metric and metric["dtype"] == "decimal" else 0) if additive else None)
            verify_groups[(p.strftime("%Y-%m-%d"), *([gkey] if split else []))] = (v, counts.get(p, 0))
            is_partial = bool(partial.get(p, False))
            growth = None
            if prev is not None and not prev[1] and not is_partial and v is not None and prev[0] not in (None, 0):
                growth = float((Decimal(str(v)) - Decimal(str(prev[0]))) / abs(Decimal(str(prev[0]))))
            row = [period_label(p, grain), p.strftime("%Y-%m-%d")]
            if split:
                row.append(gkey)
            row += [to_json_number(v), growth, is_partial]
            rows.append(row)
            prev = (v, is_partial)
    if additive:
        vi = len(columns) - 3
        tot = sum((Decimal(str(r[vi])) for r in rows if r[vi] is not None), Decimal(0))
        grand = aggregate_series(work[mkey], metric, agg) if mkey else len(work)
        checks.append({"name": "period totals add up to the grand total", "passed": _close(float(tot), float(grand)),
                       "detail": f"{tot} vs {grand}"})
    complete = [p for p in periods if not partial.get(p, False)]
    if len(complete) < MIN_TREND_POINTS:
        warnings.append(f"Only {len(complete)} complete {grain}(s): too few points (fewer than {MIN_TREND_POINTS}) to judge a trend.")
    if any(partial.values()):
        warnings.append("Partial periods (marked) are excluded from growth comparisons.")
    return {"columns": columns, "rows": rows, "periods": len(periods), "_groups": verify_groups,
            "chart_suggestion": {"type": "line", "x": "period", "y": "value", **({"series": split} if split else {})}}


def _filter_count(data: pd.DataFrame, rows_total: int) -> dict:
    share = len(data) / rows_total if rows_total else None
    return {"columns": [{"key": "rows", "label": "Matching rows", "dtype": "integer", "semantic_type": "numeric"},
                        {"key": "share", "label": "Share of all rows", "dtype": "float", "semantic_type": "percent"}],
            "rows": [[len(data), share]], "total": len(data), "chart_suggestion": {"type": "kpi", "value": "rows"}}


def _describe(data: pd.DataFrame, col: dict) -> dict:
    s = data[col["key"]]
    present = s.dropna()
    stats: list[tuple[str, object]] = [("Values", len(present)), ("Empty", int(s.isna().sum())), ("Distinct", int(present.nunique()))]
    if col["dtype"] in NUMERIC and len(present):
        for name, agg in (("Mean", "mean"), ("Median", "median"), ("Minimum", "min"), ("Maximum", "max"), ("Sum", "sum")):
            stats.append((name, aggregate_series(s, col, agg)))
        vals = present.astype("float64") / (10 ** col.get("scale", 2) if col["dtype"] == "decimal" else 1)
        stats += [("Standard deviation", float(vals.std()) if len(vals) > 1 else None),
                  ("Lower quartile (Q1)", float(vals.quantile(0.25))), ("Upper quartile (Q3)", float(vals.quantile(0.75)))]
    elif col["dtype"] in ("date", "datetime") and len(present):
        stats += [("Earliest", present.min()), ("Latest", present.max())]
    elif len(present):
        vc = present.value_counts().head(5)
        stats += [(f"Top value #{i + 1}: {k}", int(v)) for i, (k, v) in enumerate(vc.items())]
    return {"columns": [{"key": "statistic", "label": "Statistic", "dtype": "string", "semantic_type": "text"},
                        {"key": "value", "label": col["display_name"], "dtype": "string", "semantic_type": "text"}],
            "rows": [[k, to_json_number(v) if not isinstance(v, Decimal) else str(v)] for k, v in stats],
            "chart_suggestion": None}

"""Dataset profile (Phase 4): shape, types, stats, duplicates, outlier screening, correlations, trends,
quality issues and optional business metrics. Domain-agnostic: uses column types, never column names,
except for the business helpers, which state the columns they used and are skipped when absent."""
from __future__ import annotations

import re
from decimal import Decimal

import numpy as np
import pandas as pd
import pyarrow as pa

from app.analytics.engine import CalculationCheckFailed, money_div
from app.analytics.plan import NUMERIC, QueryPlan
from app.analytics.runner import run_verified
from app.cleaning.suggestions import ROLE_PATTERNS

MAX_CORR_COLUMNS = 20


def numeric_values(frame: pd.DataFrame, col: dict) -> pd.Series:
    s = frame[col["key"]]
    if col["dtype"] == "decimal":
        return s.astype("float64") / (10 ** col.get("scale", 2))
    return s.astype("float64")


def detect_roles(schema: list[dict], saved: dict | None) -> dict:
    by_key = {c["key"]: c for c in schema}
    if saved:
        return {r: k for r, k in saved.items() if k in by_key}
    roles = {}
    for role, pat in ROLE_PATTERNS.items():
        for c in schema:
            if re.search(pat, c["key"]) and c["key"] not in roles.values():
                if role in ("revenue", "price") and c["dtype"] not in NUMERIC:
                    continue
                if role == "quantity" and c["dtype"] not in ("integer", "float"):
                    continue
                roles[role] = c["key"]
                break
    if "revenue" not in roles:
        money = [c for c in schema if c["semantic_type"] == "currency"]
        if len(money) == 1:
            roles["revenue"] = money[0]["key"]
    dates = [c["key"] for c in schema if c["dtype"] in ("date", "datetime")]
    if dates:
        roles.setdefault("date", dates[0])
    return roles


def outlier_screening(frame: pd.DataFrame, schema: list[dict]) -> list[dict]:
    out = []
    for c in schema:
        if c["dtype"] not in NUMERIC or c["semantic_type"] in ("id", "percent"):
            continue
        v = numeric_values(frame, c).dropna()
        if len(v) < 8:
            continue
        q1, q3 = v.quantile(0.25), v.quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        n = int(((v < lo) | (v > hi)).sum())
        if n:
            out.append({"column": c["key"], "label": c["display_name"], "count": n, "share": n / len(v),
                        "lower": float(lo), "upper": float(hi), "method": "IQR 1.5× (screening, not proof of error)"})
    return out


def correlations(frame: pd.DataFrame, schema: list[dict]) -> dict | None:
    cols = [c for c in schema if c["dtype"] in NUMERIC and c["semantic_type"] != "id"][:MAX_CORR_COLUMNS]
    if len(cols) < 2:
        return None
    data = pd.DataFrame({c["key"]: numeric_values(frame, c) for c in cols})
    matrix = data.corr(method="pearson", min_periods=3)
    counts = data.notna().astype(int).T.dot(data.notna().astype(int))
    return {
        "columns": [{"key": c["key"], "label": c["display_name"]} for c in cols],
        "pearson": [[None if pd.isna(x) else float(x) for x in row] for row in matrix.to_numpy()],
        "n": counts.to_numpy().tolist(),
        "note": "Pearson correlation over rows where both values exist. Correlation is association, not causation.",
    }


def build_profile(frame: pd.DataFrame, table: pa.Table, version: dict, dataset: dict) -> dict:
    schema = version["schema"]
    data_cols = [c["key"] for c in schema]
    dup = int(frame[data_cols].duplicated().sum()) if len(frame) else 0
    issues = []
    for c in schema:
        if len(frame) and c["missing"] / len(frame) > 0.2:
            issues.append({"severity": "warning", "column": c["display_name"],
                           "message": f"{c['missing'] / len(frame):.0%} of values are empty"})
        if c.get("flagged"):
            issues.append({"severity": "warning", "column": c["display_name"],
                           "message": "Kept as text because values were ambiguous or mixed; review the cleaning report"})
    for step in (version.get("cleaning_report") or {}).get("steps", []):
        if step["step"] == "total_rows_kept":
            issues.append({"severity": "warning", "column": step.get("column"),
                           "message": f"{step['rows_affected']} row(s) labelled 'Total' did not add up and are still included in "
                                      f"totals ({', '.join(step['examples'][:3])}). Exclude them with a filter or fix the file."})
    outl = outlier_screening(frame, schema)
    for o in outl:
        issues.append({"severity": "info", "column": o["label"], "message": f"{o['count']} possible outlier(s) (screening)"})
    unresolved = [s for s in (version.get("suggestions") or []) if s["type"] != "column_roles"]
    if unresolved:
        issues.append({"severity": "info", "column": None,
                       "message": f"{len(unresolved)} cleaning suggestion(s) not applied; they could change results"})
    if dup:
        issues.append({"severity": "info", "column": None, "message": f"{dup} identical row(s) remain"})

    trend = None
    dates = [c for c in schema if c["dtype"] in ("date", "datetime")]
    if dates:
        d = dates[0]
        measure = next((c for c in schema if c["semantic_type"] == "currency"), None) or next(
            (c for c in schema if c["dtype"] in NUMERIC and c["semantic_type"] not in ("id", "percent")), None)
        span = (frame[d["key"]].max() - frame[d["key"]].min()) if frame[d["key"]].notna().any() else pd.Timedelta(0)
        grain = "year" if span.days > 3 * 366 else "month" if span.days > 62 else "week" if span.days > 14 else "day"
        plan = QueryPlan(operation="trend", date_column=d["key"], time_grain=grain,
                         metric_column=measure["key"] if measure else None, aggregation="sum" if measure else "count")
        try:
            trend = run_verified(frame, table, schema, plan, version)
        except CalculationCheckFailed:
            trend = {"error": "Calculation check failed"}

    return {
        "dataset_version": version["version_number"], "version_id": str(version["_id"]),
        "shape": {"rows": len(frame), "columns": len(schema)},
        "columns": [{k: c.get(k) for k in ("key", "display_name", "dtype", "semantic_type", "missing", "unique", "currency")}
                    | {"stats": (c.get("profile") or {}).get("stats"), "top": (c.get("profile") or {}).get("dist") if c["dtype"] == "string" else None}
                    for c in schema],
        "duplicates": dup,
        "outliers": outl,
        "correlation": correlations(frame, schema),
        "trend": trend,
        "quality": {"score_before": version.get("quality_score_before"), "score_after": version.get("quality_score_after"),
                    "issues": issues},
        "business": business_metrics(frame, table, schema, version, dataset),
    }


def business_metrics(frame: pd.DataFrame, table: pa.Table, schema: list[dict], version: dict, dataset: dict) -> dict | None:
    roles = detect_roles(schema, dataset.get("column_roles"))
    rev_key = roles.get("revenue")
    if not rev_key:
        return None
    by_key = {c["key"]: c for c in schema}
    rev = by_key[rev_key]
    try:
        total = run_verified(frame, table, schema, QueryPlan(operation="aggregate", metric_column=rev_key, aggregation="sum"), version)
        out = {"roles": {r: {"key": k, "label": by_key[k]["display_name"]} for r, k in roles.items()},
               "revenue": {"column": rev["display_name"], "value": total["total"], "currency": rev.get("currency"),
                           "calculation_details": total["calculation_details"]}}
        order_key = roles.get("order_id")
        if order_key:
            orders = run_verified(frame, table, schema, QueryPlan(operation="aggregate", metric_column=order_key, aggregation="nunique",
                                                                  filters=[{"column": rev_key, "op": "not_null"}]), version)
            n_orders, basis = orders["total"], f"distinct {by_key[order_key]['display_name']}"
        else:
            n_orders, basis = total["calculation_details"]["rows_used"], "rows (no order ID column, so this is per row)"
        if n_orders:
            if rev["dtype"] == "decimal":
                minor = int(frame[rev_key].dropna().astype("int64").sum())  # exact; equals the verified total
                aov = float(money_div(minor, n_orders, rev.get("scale", 2)))
            else:
                aov = float(total["total"]) / n_orders
            out["average_order_value"] = {"value": aov, "orders": n_orders, "basis": basis,
                                          "formula": f"total {rev['display_name']} ÷ {basis}",
                                          "label": "Average order value" if order_key else "Average per row"}
        for role in ("product", "region", "category", "customer"):
            if role in roles:
                top = run_verified(frame, table, schema, QueryPlan(operation="top_n", metric_column=rev_key, aggregation="sum",
                                                                   group_by=[roles[role]], limit=5), version)
                out[f"top_{role}"] = {"column": by_key[roles[role]]["display_name"], "columns": top["columns"], "rows": top["rows"]}
        return out
    except CalculationCheckFailed:
        return {"error": "Calculation check failed"}

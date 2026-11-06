"""Query plans: validated JSON descriptions of a calculation. Never code, never free-text expressions."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

NUMERIC = ("integer", "float", "decimal")
MAX_LIMIT = 1000
MAX_GROUP_BY = 3
MAX_FILTERS = 20
MAX_IN_VALUES = 200

Operation = Literal["aggregate", "top_n", "trend", "compare", "describe", "filter_count"]
Aggregation = Literal["sum", "mean", "count", "min", "max", "median", "nunique"]
FilterOp = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "is_null", "not_null", "between"]
Grain = Literal["day", "week", "month", "quarter", "year"]


class PlanError(ValueError):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=200)
    op: FilterOp
    value: Any = None


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Operation
    metric_column: str | None = Field(default=None, max_length=200)
    aggregation: Aggregation = "sum"
    group_by: list[str] = Field(default_factory=list, max_length=MAX_GROUP_BY)
    filters: list[Filter] = Field(default_factory=list, max_length=MAX_FILTERS)
    date_column: str | None = Field(default=None, max_length=200)
    time_grain: Grain = "month"
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)


def _coerce_value(v, col: dict, op: str):
    dtype = col["dtype"]
    if v is None or isinstance(v, (dict, list)) and op not in ("in", "not_in", "between"):
        raise PlanError(f"A value is required for '{col['display_name']}'", "filters")
    try:
        if dtype in ("integer", "decimal", "float"):
            if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                raise ValueError
            return float(v) if dtype == "float" else (int(v) if dtype == "integer" and float(v).is_integer() else float(v))
        if dtype in ("date", "datetime"):
            if not isinstance(v, str) or len(v) > 40:
                raise ValueError
            ts = pd.Timestamp(v)
            if pd.isna(ts):
                raise ValueError
            return ts
        if dtype == "boolean":
            if isinstance(v, bool):
                return v
            if isinstance(v, str) and v.lower() in ("true", "false"):
                return v.lower() == "true"
            raise ValueError
        if not isinstance(v, (str, int, float)) or isinstance(v, bool):
            raise ValueError
        s = str(v)
        if len(s) > 500:
            raise ValueError
        return s
    except (ValueError, TypeError, OverflowError):
        raise PlanError(f"'{v}' is not a valid {dtype} value for '{col['display_name']}'", "filters")


def validate_plan(plan: QueryPlan, schema: list[dict]) -> dict:
    """Check the plan against the dataset schema. Returns {key: column} for columns used.

    Raises PlanError with a friendly message for unknown columns, wrong types or unsupported combinations.
    """
    by_key = {c["key"]: c for c in schema}

    def need(key: str | None, field: str, label: str) -> dict:
        if not key:
            raise PlanError(f"Choose a {label}", field)
        if key not in by_key:
            raise PlanError(f"Column '{key}' does not exist in this dataset", field)
        return by_key[key]

    used: dict[str, dict] = {}
    op, agg = plan.operation, plan.aggregation
    if op in ("aggregate", "top_n", "trend", "compare"):
        if agg != "count" or plan.metric_column:
            m = need(plan.metric_column, "metric_column", "column to measure")
            if agg in ("sum", "mean", "median") and m["dtype"] not in NUMERIC:
                raise PlanError(f"'{m['display_name']}' is not numeric, so {agg} is not possible. Use count or nunique.", "aggregation")
            if agg in ("min", "max") and m["dtype"] not in (*NUMERIC, "date", "datetime"):
                raise PlanError(f"{agg} needs a numeric or date column", "aggregation")
            used[m["key"]] = m
    if op == "describe":
        m = need(plan.metric_column, "metric_column", "column to describe")
        used[m["key"]] = m
    if op in ("top_n", "compare") and len(plan.group_by) != 1:
        raise PlanError("Choose exactly one column to group by", "group_by")
    if len(set(plan.group_by)) != len(plan.group_by):
        raise PlanError("Each group-by column can be used once", "group_by")
    for g in plan.group_by:
        c = need(g, "group_by", "group-by column")
        if c["dtype"] in ("float", "decimal"):
            raise PlanError(f"'{c['display_name']}' has continuous numbers; group by a category, date or ID instead", "group_by")
        used[g] = c
    if op == "trend":
        d = need(plan.date_column, "date_column", "date column")
        if d["dtype"] not in ("date", "datetime"):
            raise PlanError(f"'{d['display_name']}' is not a date column", "date_column")
        if len(plan.group_by) > 1:
            raise PlanError("A trend can be split by at most one column", "group_by")
        used[d["key"]] = d
    for f in plan.filters:
        c = need(f.column, "filters", "filter column")
        used[c["key"]] = c
        if f.op in ("is_null", "not_null"):
            f.value = None
        elif f.op in ("in", "not_in"):
            if not isinstance(f.value, list) or not f.value or len(f.value) > MAX_IN_VALUES:
                raise PlanError(f"'{f.op}' needs a list of 1-{MAX_IN_VALUES} values", "filters")
            f.value = [_coerce_value(v, c, "eq") for v in f.value]
        elif f.op == "between":
            if not isinstance(f.value, list) or len(f.value) != 2:
                raise PlanError("'between' needs [low, high]", "filters")
            f.value = [_coerce_value(v, c, "eq") for v in f.value]
            if c["dtype"] not in (*NUMERIC, "date", "datetime"):
                raise PlanError("'between' works on numbers and dates", "filters")
        elif f.op == "contains":
            if c["dtype"] != "string":
                raise PlanError("'contains' works on text columns", "filters")
            f.value = _coerce_value(f.value, c, f.op)
        else:
            if f.op in ("gt", "gte", "lt", "lte") and c["dtype"] not in (*NUMERIC, "date", "datetime"):
                raise PlanError(f"'{f.op}' works on numbers and dates", "filters")
            f.value = _coerce_value(f.value, c, f.op)
    return used


def describe_filters(plan: QueryPlan, schema: list[dict]) -> list[str]:
    names = {c["key"]: c["display_name"] for c in schema}
    sym = {"eq": "=", "ne": "≠", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "in": "in", "not_in": "not in",
           "contains": "contains", "between": "between", "is_null": "is empty", "not_null": "is not empty"}

    def fmt(v):
        if isinstance(v, pd.Timestamp):
            return v.strftime("%Y-%m-%d") if v == v.normalize() else v.isoformat()
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return str(v)

    out = []
    for f in plan.filters:
        if f.op in ("is_null", "not_null"):
            out.append(f"{names[f.column]} {sym[f.op]}")
        elif isinstance(f.value, list):
            out.append(f"{names[f.column]} {sym[f.op]} {', '.join(fmt(v) for v in f.value)}")
        else:
            out.append(f"{names[f.column]} {sym[f.op]} {fmt(f.value)}")
    return out

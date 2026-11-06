"""Dual-engine verification: recompute a plan's headline numbers with DuckDB and compare to Pandas.

DuckDB reads the same cleaned Parquet (money is DECIMAL, so sums are exact) and applies the plan's
filters itself, so the two engines share no calculation code. Only SQL generated here (never user SQL)
runs in this connection, and external access is disabled and locked anyway.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import duckdb
import pandas as pd
import pyarrow as pa

from app.analytics.plan import QueryPlan

SQL_AGG = {"sum": "SUM({m})", "mean": "AVG({m})", "count": "COUNT({m})", "min": "MIN({m})", "max": "MAX({m})",
           "median": "MEDIAN({m})", "nunique": "COUNT(DISTINCT {m})"}
OPS = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


class VerificationFailed(Exception):
    pass


def q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _sql_type(col: dict) -> str:
    return {"decimal": f"DECIMAL(38,{col.get('scale', 2)})", "integer": "BIGINT", "float": "DOUBLE", "date": "TIMESTAMP",
            "datetime": "TIMESTAMP", "boolean": "BOOLEAN"}.get(col["dtype"], "VARCHAR")


def _literal(v, col: dict) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, pd.Timestamp):
        return f"TIMESTAMP '{v.isoformat(sep=' ')}'"
    if col["dtype"] in ("integer", "float", "decimal"):
        return f"CAST('{Decimal(str(v))}' AS {_sql_type(col)})"
    return "'" + str(v).replace("'", "''") + "'"


def where_sql(plan: QueryPlan, schema: list[dict], literal: bool = False) -> tuple[list[str], list]:
    """The plan's filters as SQL conditions (and bound parameters when literal is False)."""
    by_key = {c["key"]: c for c in schema}
    params: list = []

    def val(v, col):
        if literal:
            return _literal(v, col)
        params.append(v.to_pydatetime() if isinstance(v, pd.Timestamp) else (str(v) if col["dtype"] == "decimal" else v))
        return f"CAST(? AS {_sql_type(col)})" if col["dtype"] in ("decimal", "date", "datetime") else "?"

    where = []
    for f in plan.filters:
        col = by_key[f.column]
        c = q(f.column)
        if f.op == "is_null":
            where.append(f"{c} IS NULL")
        elif f.op == "not_null":
            where.append(f"{c} IS NOT NULL")
        elif f.op in OPS:
            where.append(f"{c} {OPS[f.op]} {val(f.value, col)}")
        elif f.op == "between":
            where.append(f"{c} BETWEEN {val(f.value[0], col)} AND {val(f.value[1], col)}")
        elif f.op in ("in", "not_in"):
            items = ", ".join(val(v, col) for v in f.value)
            where.append(f"{c} {'NOT IN' if f.op == 'not_in' else 'IN'} ({items})")
        elif f.op == "contains":
            where.append(f"contains(lower({c}), lower({val(f.value, col)}))")
    return where, params


def build_sql(plan: QueryPlan, schema: list[dict], literal: bool = False, table: str = "data") -> tuple[str, list]:
    """SQL equivalent of the plan. literal=True inlines escaped values (for display / SQL Workbench)."""
    where, params = where_sql(plan, schema, literal)

    op = plan.operation
    if op == "filter_count":
        sql = f"SELECT COUNT(*) AS rows FROM {table}" + (f" WHERE {' AND '.join(where)}" if where else "")
        return sql, params
    m = q(plan.metric_column) if plan.metric_column else None
    if op == "describe":
        sql = (f"SELECT COUNT({m}) AS values_count, COUNT(DISTINCT {m}) AS distinct_count FROM {table}"
               + (f" WHERE {' AND '.join(where)}" if where else ""))
        return sql, params
    if m:
        where.append(f"{m} IS NOT NULL")
    select, group = [], []
    if op == "trend":
        where.append(f"{q(plan.date_column)} IS NOT NULL")
        expr = f"date_trunc('{plan.time_grain}', CAST({q(plan.date_column)} AS TIMESTAMP))"
        select.append(f"{expr} AS period_start")
        group.append(expr)
    for g in plan.group_by:
        select.append(q(g))
        group.append(q(g))
    agg = SQL_AGG[plan.aggregation].format(m=m) if m else "COUNT(*)"
    select += [f"{agg} AS value", "COUNT(*) AS rows_used"]
    sql = f"SELECT {', '.join(select)} FROM {table}"
    if where:
        sql += f" WHERE {' AND '.join(where)}"
    if group:
        sql += f" GROUP BY {', '.join(group)} ORDER BY {', '.join(group)}"
    return sql, params


def connect_locked(memory_limit: str = "512MB", threads: int = 2) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    for stmt in ("SET enable_external_access=false", "SET autoload_known_extensions=false",
                 "SET autoinstall_known_extensions=false", "SET allow_community_extensions=false",
                 f"SET memory_limit='{memory_limit}'", f"SET threads={int(threads)}",
                 "SET max_temp_directory_size='0KB'",  # never spill to disk
                 "SET lock_configuration=true"):
        con.execute(stmt)
    return con


def _norm_key(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d") if (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0) else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bool,)):
        return v
    if isinstance(v, int):
        return v
    return str(v)


def _same(a, b, exact: bool) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if exact:
        return Decimal(str(a)) == Decimal(str(b))
    a, b = float(a), float(b)
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def verify(table: pa.Table, plan: QueryPlan, schema: list[dict], expected: dict) -> list[dict]:
    """expected: {"groups": {key_tuple: (value, rows)}, "rows_used": int, "rows_in": int}. Returns check records."""
    by_key = {c["key"]: c for c in schema}
    metric = by_key.get(plan.metric_column) if plan.metric_column else None
    exact = metric is None or plan.aggregation in ("count", "nunique") or (
        metric["dtype"] in ("decimal", "integer") and plan.aggregation in ("sum", "min", "max"))
    con = connect_locked()
    try:
        con.register("data", table)
        sql, params = build_sql(plan, schema)
        res = con.execute(sql, params).fetchall()
    finally:
        con.close()
    checks = []
    if plan.operation == "filter_count":
        ok = res[0][0] == expected["rows_in"]
        checks.append({"name": "DuckDB matching row count", "passed": ok, "detail": f"{res[0][0]} vs {expected['rows_in']}"})
        return checks
    if plan.operation == "describe":
        ok = res[0][0] == expected["rows_used"]
        checks.append({"name": "DuckDB non-empty value count", "passed": ok, "detail": f"{res[0][0]} vs {expected['rows_used']}"})
        return checks
    duck = {}
    for row in res:
        *keys, value, n = row
        duck[tuple(_norm_key(k) for k in keys)] = (value, n)
    mine = expected["groups"]
    rows_ok = sum(n for _, n in duck.values()) == expected["rows_used"]
    checks.append({"name": "DuckDB rows used", "passed": rows_ok, "detail": f"{sum(n for _, n in duck.values())} vs {expected['rows_used']}"})
    mismatches = []
    for k, (v, n) in mine.items():
        d = duck.get(k)
        if d is None:
            if n:  # an empty filled-in period has no SQL row
                mismatches.append(f"{k}: missing in DuckDB")
            continue
        if d[1] != n or not _same(v, d[0], exact):
            mismatches.append(f"{k}: pandas {v} ({n} rows) vs duckdb {d[0]} ({d[1]} rows)")
    extra = [k for k in duck if k not in mine]
    checks.append({"name": "DuckDB group values match" + (" exactly" if exact else " (relative 1e-9)"),
                   "passed": not mismatches and not extra,
                   "detail": "; ".join(mismatches[:3] + [f"{k}: only in DuckDB" for k in extra[:3]]) or f"{len(mine)} group(s) compared"})
    return checks

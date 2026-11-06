"""Pivot tables: nested row fields, a column field, several measures, subtotals and a grand total.

How the numbers stay right
- Every level (cells, subtotals, row totals, column totals, grand total) is its own group-by over the filtered
  rows, never a sum of other cells, so averages, medians and distinct counts are correct at every level.
- Money is added as exact integer minor units; counts and integer sums are exact integers.
- Each group-by is recomputed by DuckDB (a second engine on the same Parquet data) and every group is compared:
  exact for money/integers/counts, relative 1e-9 for averages and medians.
- For sums and counts the cells must also add up to the grand total.

Size: there is no row limit; the pivot covers every row of the dataset. Only the *output* is bounded (500 columns,
600,000 cells) so the browser can show it; totals always include everything.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analytics import verify
from app.analytics.engine import (AGG_LABEL, CalculationCheckFailed, filter_mask, grain_end, grain_start,
                                  period_label)
from app.analytics.plan import NUMERIC, PlanError, QueryPlan, describe_filters, validate_plan

EMPTY = "(empty)"
MAX_ROW_FIELDS = 3
MAX_MEASURES = 6
MAX_COLUMNS = 500
MAX_CELLS = 600_000
EXACT_AGGS = ("sum", "min", "max")
VALUE_AGGS = ("sum", "mean", "median", "min", "max")


@dataclass
class _Field:
    idx: int
    key: str
    col: dict
    date: bool

    @property
    def name(self) -> str:
        return f"__k{self.idx}"


@dataclass
class _Measure:
    idx: int
    key: str | None
    col: dict | None
    agg: str
    label: str

    @property
    def scale(self) -> int:
        return int(self.col.get("scale", 2)) if self.col and self.col["dtype"] == "decimal" else 0

    @property
    def exact(self) -> bool:
        """Results are integers (money in minor units), so engines must agree exactly."""
        return self.agg in ("count", "nunique") or bool(
            self.col and self.col["dtype"] in ("decimal", "integer") and self.agg in EXACT_AGGS)

    def out_column(self) -> dict:
        c = self.col
        if c is None or self.agg in ("count", "nunique"):
            return {"key": "value", "label": self.label, "dtype": "integer", "semantic_type": "numeric"}
        dtype = c["dtype"]
        if dtype == "integer" and self.agg in ("mean", "median"):
            dtype = "float"
        out = {"key": "value", "label": self.label, "dtype": dtype, "semantic_type": c["semantic_type"]}
        if c["dtype"] == "decimal":
            out.update({"currency": c.get("currency"), "scale": c.get("scale")})
        return out


# ------------------------------------------------------------------ specification

def _parse(spec: dict, by_key: dict) -> tuple[list[_Field], _Field | None, list[_Measure]]:
    rows = [k for k in (spec.get("rows") or []) if k]
    col = spec.get("columns") or None
    if not rows:
        raise PlanError("Choose at least one column for Rows", "rows")
    if len(rows) > MAX_ROW_FIELDS:
        raise PlanError(f"Rows can have at most {MAX_ROW_FIELDS} fields", "rows")
    keys = rows + ([col] if col else [])
    if len(set(keys)) != len(keys):
        raise PlanError("Each column can be used only once across Rows and Columns", "columns")
    fields = []
    for i, k in enumerate(keys):
        c = by_key.get(k)
        if c is None:
            raise PlanError(f"Column '{k}' does not exist in this dataset", "rows" if i < len(rows) else "columns")
        if c["dtype"] in ("float", "decimal"):
            raise PlanError(f"'{c['display_name']}' has continuous numbers; group by a category, date or ID instead",
                            "rows" if i < len(rows) else "columns")
        fields.append(_Field(i, k, c, c["dtype"] in ("date", "datetime")))
    measures: list[_Measure] = []
    wanted = spec.get("measures") or [{"column": None, "aggregation": "count"}]
    if len(wanted) > MAX_MEASURES:
        raise PlanError(f"A pivot can show at most {MAX_MEASURES} values", "measures")
    for i, w in enumerate(wanted):
        agg, mkey = w.get("aggregation", "sum"), w.get("column") or None
        if mkey is None:
            if agg not in ("count", "sum"):
                raise PlanError(f"Choose a column to apply {AGG_LABEL.get(agg, agg)} to", "measures")
            agg, label, mcol = "count", "Row count", None
        else:
            mcol = by_key.get(mkey)
            if mcol is None:
                raise PlanError(f"Column '{mkey}' does not exist in this dataset", "measures")
            if agg in VALUE_AGGS and mcol["dtype"] not in NUMERIC:
                raise PlanError(f"'{mcol['display_name']}' is not numeric, so {AGG_LABEL[agg].lower()} is not possible. "
                                "Use Count or Distinct count.", "measures")
            label = f"{AGG_LABEL[agg]} of {mcol['display_name']}"
        if any(m.label == label for m in measures):
            raise PlanError(f"'{label}' is already in Values", "measures")
        measures.append(_Measure(i, mkey, mcol, agg, label))
    return fields[:len(rows)], (fields[len(rows)] if col else None), measures


# ------------------------------------------------------------------ labels

def _date_labels(values: pd.Series, grain: str) -> tuple[pd.Series, dict]:
    uniq = pd.Series(values.dropna().unique())
    mapping = {pd.Timestamp(u): period_label(pd.Timestamp(u), grain) for u in uniq}
    out = pd.Series(values.map(mapping), index=values.index).astype("string").fillna(EMPTY)
    return out, {label: ts for ts, label in mapping.items()}


def _plain_labels(values: pd.Series, col: dict) -> pd.Series:
    if col["dtype"] == "boolean":
        return values.map({True: "true", False: "false"}).astype("string").fillna(EMPTY)
    return values.astype("string").fillna(EMPTY)


def _ord(label: str, f: _Field, starts: dict):
    """Sort key: empty last, dates chronologically, integers numerically, text case-insensitively."""
    if label == EMPTY:
        return (1, 0)
    if f.date:
        return (0, starts.get(label, pd.Timestamp.max).value)
    if f.col["dtype"] == "integer":
        try:
            return (0, int(label))
        except ValueError:
            pass
    return (0, label.casefold())


# ------------------------------------------------------------------ calculation

def _group(work: pd.DataFrame, keycols: list[str], vals: pd.Series, m: _Measure) -> pd.DataFrame:
    """One group-by: key columns, value ('v') and rows used ('n'). Rows with an empty measure are already removed."""
    df = work[keycols].copy() if keycols else pd.DataFrame(index=work.index)
    if not keycols:
        df["__all"] = 0
        keycols = ["__all"]
    df["__v"] = vals.to_numpy() if not isinstance(vals.dtype, pd.StringDtype) else vals
    g = df.groupby(keycols, dropna=False, sort=False)
    n = g.size()
    if m.agg == "count":
        v = n
    elif m.agg == "nunique":
        v = g["__v"].nunique()
    elif m.agg == "mean":
        v = g["__v"].sum() / n
    else:
        v = getattr(g["__v"], m.agg)()
    keys = n.index.to_frame(index=False)
    if list(keys.columns) != keycols:
        keys.columns = keycols
    keys["v"] = v.to_numpy()
    keys["n"] = n.to_numpy()
    return keys


def _to_dict(frame: pd.DataFrame, keycols: list[str], labelers: dict) -> dict:
    cols = [labelers[c](frame[c]) for c in keycols if c in labelers]
    labels = list(zip(*[c.tolist() for c in cols])) if cols else [()] * len(frame)
    vs = frame["v"].tolist()
    ns = frame["n"].tolist()
    return {k: ((None if (isinstance(v, float) and math.isnan(v)) else v), n) for k, v, n in zip(labels, vs, ns)}


def _agg_sql(m: _Measure, check: bool) -> str:
    c = verify.q(m.key) if m.key else None
    if m.agg == "count":
        return "COUNT(*)" if c is None else f"COUNT({c})"
    if m.agg == "nunique":
        return f"COUNT(DISTINCT {c})"
    fn = {"sum": "SUM", "mean": "AVG", "median": "MEDIAN", "min": "MIN", "max": "MAX"}[m.agg]
    expr = f"{fn}({c})"
    if not check:
        return expr
    if m.col["dtype"] == "decimal" and m.agg in EXACT_AGGS:
        return f"CAST({expr} * {10 ** m.scale} AS BIGINT)"
    if m.col["dtype"] == "integer" and m.agg in EXACT_AGGS:
        return f"CAST({expr} AS BIGINT)"
    return f"CAST({expr} AS DOUBLE)"


def _sql(fields: list[_Field], m: _Measure, where: list[str], grain: str, check: bool) -> str:
    exprs, sel = [], []
    for i, f in enumerate(fields):
        e = (f"date_trunc('{grain}', CAST({verify.q(f.key)} AS TIMESTAMP))" if f.date else
             f"CAST({verify.q(f.key)} AS VARCHAR)" if check else verify.q(f.key))
        exprs.append(e)
        sel.append(f"{e} AS k{i}" if check else e)
    conds = list(where) + ([f"{verify.q(m.key)} IS NOT NULL"] if m.key else [])
    sql = f"SELECT {', '.join(sel + [f'{_agg_sql(m, check)} AS value'] + (['COUNT(*) AS n'] if check else []))} FROM data"
    if conds:
        sql += f" WHERE {' AND '.join(conds)}"
    if exprs:
        sql += f" GROUP BY {', '.join(exprs)}"
        if not check:
            sql += f" ORDER BY {', '.join(exprs)}"
    return sql


def _duck_dict(con, sql: str, params: list, fields: list[_Field], grain: str) -> dict:
    tbl = con.sql(sql, params=params or None).to_arrow_table()
    n_keys = len(fields)
    cols = []
    for i, f in enumerate(fields):
        s = tbl.column(i).to_pandas()
        cols.append(_date_labels(s, grain)[0] if f.date else s.astype("string").fillna(EMPTY))
    values = tbl.column(n_keys).to_pylist()
    counts = tbl.column(n_keys + 1).to_pylist()
    labels = list(zip(*[c.tolist() for c in cols])) if cols else [()] * len(values)
    return {k: (v, n) for k, v, n in zip(labels, values, counts)}


def _same(m: _Measure, mine, theirs) -> bool:
    if mine is None or theirs is None:
        return mine is None and theirs is None
    if m.exact:
        return int(mine) == int(theirs)
    a = float(mine) / (10 ** m.scale)
    b = float(theirs)
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _display(v, m: _Measure):
    if v is None:
        return None
    if m.scale:
        return float(v) / (10 ** m.scale)
    return int(v) if m.exact else float(v)


def build_pivot(frame: pd.DataFrame, table, schema: list[dict], version: dict, spec: dict) -> dict:
    by_key = {c["key"]: c for c in schema}
    rows_f, col_f, measures = _parse(spec, by_key)
    fields = rows_f + ([col_f] if col_f else [])
    R, C = len(rows_f), 1 if col_f else 0
    grain = spec.get("grain") or "month"
    sort = spec.get("sort") or {}
    sort_m = int(sort.get("measure", 0))
    if sort_m >= len(measures):
        sort_m = 0
    top_n = spec.get("top_n")

    plan = QueryPlan.model_validate({"operation": "filter_count", "filters": spec.get("filters") or []})
    validate_plan(plan, schema)
    data = frame.loc[filter_mask(frame, plan, by_key)]
    rows_in = len(data)
    filters_text = describe_filters(plan, schema)
    if rows_in == 0:
        return _empty(rows_f, col_f, measures, filters_text, len(frame), version)

    # key columns (dates are cut to the start of their period)
    work = pd.DataFrame(index=data.index)
    starts: dict[int, dict] = {}
    partial: dict[int, set] = {}
    for f in fields:
        work[f.name] = grain_start(data[f.key], grain) if f.date else data[f.key]
        if f.date:
            d = data[f.key].dropna()
            partial[f.idx] = set()
            if not d.empty and grain != "day":
                st = grain_start(d, grain)
                first, last = st.min(), st.max()
                if d.min().normalize() > first:
                    partial[f.idx].add(period_label(first, grain))
                if d.max().normalize() < grain_end(last, grain).normalize():
                    partial[f.idx].add(period_label(last, grain))

    def labeler(f: _Field):
        def run(s: pd.Series) -> pd.Series:
            if f.date:
                out, mp = _date_labels(s, grain)
                starts.setdefault(f.idx, {}).update(mp)
                return out
            return _plain_labels(s, f.col)
        return run

    labelers = {f.name: labeler(f) for f in fields}

    # ---- every level, every measure: pandas result (mine) checked against DuckDB (theirs)
    levels = [(k, j) for k in range(R + 1) for j in range(C + 1)]
    where, params = verify.where_sql(plan, schema)
    checks: list[dict] = []
    mine: dict[tuple, dict] = {}
    con = verify.connect_locked(memory_limit="1GB")
    try:
        con.register("data", table)
        rows_dbl = con.execute("SELECT COUNT(*) FROM data" + (f" WHERE {' AND '.join(where)}" if where else ""), params).fetchall()[0][0]
        checks.append({"name": "DuckDB matching row count", "passed": rows_dbl == rows_in, "detail": f"{rows_dbl} vs {rows_in}"})
        for m in measures:
            if m.key is None:
                vals, valid = pd.Series(np.zeros(len(data), dtype="int8"), index=data.index), pd.Series(True, index=data.index)
            else:
                s = data[m.key]
                valid = s.notna()
                if m.col["dtype"] in ("decimal", "integer"):
                    vals = s[valid].astype("int64")
                elif m.col["dtype"] == "float":
                    vals = s[valid].astype("float64")
                else:
                    vals = s[valid]
            w = work.loc[valid]
            for k, j in levels:
                kf = fields[:k] + (fields[R:R + 1] if j else [])
                keycols = [f.name for f in kf]
                res = _to_dict(_group(w, keycols, vals, m), keycols, labelers)
                mine[(m.idx, k, j)] = res
                sql = _sql(kf, m, where, grain, check=True)
                theirs = _duck_dict(con, sql, params, kf, grain)
                bad = []
                for key, (v, n) in res.items():
                    t = theirs.get(key)
                    if t is None:
                        bad.append(f"{key}: missing in DuckDB")
                    elif t[1] != n or not _same(m, v, t[0]):
                        bad.append(f"{key}: {_display(v, m)} ({n} rows) vs DuckDB {t[0]} ({t[1]} rows)")
                bad += [f"{key}: only in DuckDB" for key in theirs if key not in res]
                name = (f"{m.label}: " + ("grand total" if (k, j) == (0, 0) else "column totals" if k == 0 else
                                         "row totals" if j == 0 and k == R else "subtotals" if j == 0 else
                                         "subtotals by column" if k < R else "cells") + " match DuckDB")
                checks.append({"name": name, "passed": not bad,
                               "detail": "; ".join(bad[:3]) or f"{len(res):,} group(s) compared" + (" exactly" if m.exact else " (relative 1e-9)")})
            if m.agg in ("sum", "count"):
                grand = mine[(m.idx, 0, 0)].get((), (None, 0))[0]
                for k, j in ((R, 0), (R, C)):
                    total = sum(v for v, _ in mine[(m.idx, k, j)].values() if v is not None)
                    ok = (grand is None and total == 0) or (grand is not None and (int(total) == int(grand) if m.exact else abs(total - grand) <= 1e-9 * max(1.0, abs(grand))))
                    checks.append({"name": f"{m.label}: {'cells' if j else 'rows'} add up to the grand total", "passed": ok,
                                   "detail": f"{_display(total, m)} vs {_display(grand, m)}"})
        eq_sql = _sql(fields, measures[0], verify.where_sql(plan, schema, literal=True)[0], grain, check=False)
    finally:
        con.close()
    failed = [c for c in checks if not c["passed"]]
    if failed:
        raise CalculationCheckFailed("; ".join(f"{c['name']}: {c['detail']}" for c in failed)[:500])

    # ---- layout: sorted tree of row paths, sorted columns
    def paths_at(k: int) -> set:
        return {p for m in measures for p in mine[(m.idx, k, 0)]}

    def total_of(mi: int, k: int, path: tuple):
        v = mine[(mi, k, 0)].get(path)
        return None if v is None else v[0]

    children: dict[tuple, list] = {}
    for k in range(1, R + 1):
        for p in paths_at(k):
            children.setdefault(p[:-1], []).append(p)
    leaf_count = len(paths_at(R))

    def order(parent: tuple, level: int) -> list:
        f = rows_f[level]
        kids = children.get(parent, [])
        by = sort.get("by", "auto")
        by = ("label" if f.date else "value") if by == "auto" else by
        direction = sort.get("direction") or ("asc" if by == "label" else "desc")
        if by == "label":
            return sorted(kids, key=lambda p: _ord(p[-1], f, starts.get(f.idx, {})), reverse=direction == "desc")
        def val(p):
            v = total_of(sort_m, level + 1, p)
            return (v is None, -(v or 0) if direction == "desc" else (v or 0))
        return sorted(kids, key=val)

    if top_n:
        ranked = sorted(children.get((), []), key=lambda p: (total_of(sort_m, 1, p) is None, -(total_of(sort_m, 1, p) or 0)))
        children[()] = ranked[: int(top_n)]
    ordered_rows: list[tuple] = []

    def walk(parent: tuple, level: int):
        for p in order(parent, level):
            ordered_rows.append(p)
            if level + 1 < R:
                walk(p, level + 1)

    walk((), 0)

    cols_labels: list[str] = []
    if col_f:
        cols_labels = list({p[0] for m in measures for p in mine[(m.idx, 0, 1)]})
        if len(cols_labels) > MAX_COLUMNS:
            raise PlanError(f"'{col_f.col['display_name']}' has {len(cols_labels):,} different values; a pivot can show at most "
                            f"{MAX_COLUMNS} columns. Put it in Rows or add a filter.", "columns")
        if spec.get("col_sort") == "value":
            def cval(c):
                v = mine[(sort_m, 0, 1)].get((c,))
                return (v is None or v[0] is None, -(v[0] if v and v[0] is not None else 0))
            cols_labels.sort(key=cval)
        else:
            cols_labels.sort(key=lambda c: _ord(c, col_f, starts.get(col_f.idx, {})))
    nm, nc = len(measures), len(cols_labels)
    if len(ordered_rows) * max(1, nc) * nm > MAX_CELLS:
        raise PlanError(f"This pivot has {len(ordered_rows):,} rows × {max(1, nc)} columns × {nm} value(s), more than the "
                        f"{MAX_CELLS:,} cells that can be shown at once. Add a filter, use Top N, or choose fewer fields.", "rows")

    def pick(mi: int, k: int, j: int, key: tuple):
        v = mine[(mi, k, j)].get(key)
        return None if v is None else _display(v[0], measures[mi])

    out_rows = []
    for p in ordered_rows:
        k = len(p)
        partial_row = any(p[f.idx] in partial.get(f.idx, ()) for f in rows_f[:k] if f.date)
        out_rows.append({
            "path": list(p), "level": k - 1, "subtotal": k < R, "partial": partial_row,
            "totals": [pick(m.idx, k, 0, p) for m in measures],
            "cells": [pick(m.idx, k, 1, p + (c,)) for c in cols_labels for m in measures] if col_f else [],
        })
    col_partial = [bool(col_f and col_f.date and c in partial.get(col_f.idx, ())) for c in cols_labels]
    grand_n = [mine[(m.idx, 0, 0)].get((), (None, 0))[1] for m in measures]
    rows_used = max(grand_n)
    row_names = [f.col["display_name"] for f in rows_f]
    formula = (f"Pivot of {', '.join(m.label for m in measures)} by {' › '.join(row_names)}"
               + (f" and {col_f.col['display_name']}" if col_f else "")
               + (f" (dates grouped by {grain})" if any(f.date for f in fields) else "")
               + ". Each cell, subtotal and total is calculated from the underlying rows.")
    details = {
        "dataset_version": version.get("version_number"), "version_id": str(version.get("_id", "")), "engine": "pandas",
        "verified_by": "duckdb", "plan": {k: v for k, v in spec.items() if k != "filters"},
        "filters_applied": filters_text or ["None"], "formula": formula,
        "rows_total": len(frame), "rows_in": rows_in, "rows_used": rows_used, "rows_skipped": rows_in - rows_used,
        "null_policy": "Rows where a value's column is empty are skipped for that value only (never treated as 0). "
                       "Empty labels in Rows or Columns are shown as (empty).",
        "checks": checks, "warnings": [], "equivalent_sql": eq_sql,
    }
    return {
        "row_fields": [{"key": f.key, "label": f.col["display_name"], "is_date": f.date} for f in rows_f],
        "column_field": {"key": col_f.key, "label": col_f.col["display_name"], "is_date": col_f.date} if col_f else None,
        "grain": grain if any(f.date for f in fields) else None,
        "measures": [{"label": m.label, "aggregation": m.agg, "column": m.out_column(), "additive": m.agg in ("sum", "count"),
                      "rows_used": grand_n[m.idx]} for m in measures],
        "columns": cols_labels, "columns_partial": col_partial,
        "rows": out_rows,
        "column_totals": [pick(m.idx, 0, 1, (c,)) for c in cols_labels for m in measures] if col_f else [],
        "grand_total": [pick(m.idx, 0, 0, ()) for m in measures],
        "rows_total_count": leaf_count, "rows_shown_count": sum(1 for p in ordered_rows if len(p) == R), "top_n": top_n,
        "rows_in": rows_in, "rows_used": rows_used, "filters": filters_text,
        "verification": {"checks": len(checks), "passed": len(checks) - len(failed), "engines": ["pandas", "duckdb"]},
        "how_calculated": details, "empty": False,
    }


def _empty(rows_f, col_f, measures, filters_text, rows_total, version) -> dict:
    return {
        "row_fields": [{"key": f.key, "label": f.col["display_name"], "is_date": f.date} for f in rows_f],
        "column_field": {"key": col_f.key, "label": col_f.col["display_name"], "is_date": col_f.date} if col_f else None,
        "grain": None, "measures": [{"label": m.label, "aggregation": m.agg, "column": m.out_column(),
                                    "additive": m.agg in ("sum", "count"), "rows_used": 0} for m in measures],
        "columns": [], "columns_partial": [], "rows": [], "column_totals": [], "grand_total": [None] * len(measures),
        "rows_total_count": 0, "rows_shown_count": 0, "top_n": None, "rows_in": 0, "rows_used": 0, "filters": filters_text,
        "verification": {"checks": 0, "passed": 0, "engines": ["pandas", "duckdb"]},
        "how_calculated": {"dataset_version": version.get("version_number"), "engine": "pandas", "filters_applied": filters_text or ["None"],
                           "rows_total": rows_total, "rows_in": 0, "rows_used": 0, "rows_skipped": 0, "checks": []},
        "empty": True,
    }

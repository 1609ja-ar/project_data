"""Runs a plan with Pandas, verifies it with DuckDB, and returns a result only if both agree."""
from __future__ import annotations

import pandas as pd
import pyarrow as pa

from app.analytics import engine, verify
from app.analytics.plan import QueryPlan


def run_verified(frame: pd.DataFrame, table: pa.Table, schema: list[dict], plan: QueryPlan, version: dict) -> dict:
    result = engine.execute(frame, schema, plan, version)
    details = result["calculation_details"]
    expected = {"groups": result.pop("_groups", {}), "rows_used": details["rows_used"], "rows_in": details["rows_in"]}
    checks = verify.verify(table, plan, schema, expected)
    details["checks"] += checks
    details["verified_by"] = "duckdb"
    details["equivalent_sql"] = verify.build_sql(plan, schema, literal=True)[0]
    if not all(c["passed"] for c in checks):
        raise engine.CalculationCheckFailed("; ".join(c["detail"] for c in checks if not c["passed"]))
    return result

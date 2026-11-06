"""Analytics engine (Phase 4). Expected values are computed by hand in the comments."""
from decimal import Decimal

import pytest

from app.analytics import engine, verify
from app.analytics.plan import PlanError, QueryPlan
from app.analytics.profile import build_profile
from app.analytics.runner import run_verified
from app.cleaning import frames
from app.cleaning.pipeline import run_cleaning
from app.cleaning.profile import build_schema
from app.services.ingest import read_csv_grid

GOLDEN = """Order ID,Order Date,Region,Product,Amount,Qty
A1,2024-01-03,North,Pen,$10.10,1
A2,2024-01-15,South,Ink,$20.20,2
A3,2024-02-01,North,Pen,$30.30,3
A4,2024-02-20,East,Pad,,1
A5,2024-03-05,South,Ink,$40.40,4
A6,2024-03-28,North,Pad,$0.01,5
"""
FULL_MONTHS = """Day,Units
2024-01-01,5
2024-02-10,7
2024-03-31,11
"""
NO_NUMBERS = """Name,Team,Joined
Ann,Red,2023-01-01
Bo,Blue,2023-02-01
Cy,Red,2023-03-01
"""


def load(text, tmp_path, name="v.parquet"):
    r = run_cleaning(read_csv_grid(text.encode(), 1000, 50).frame)
    schema = build_schema(r.frame, r.columns)
    p = tmp_path / name
    frames.write_parquet(r.frame, schema, p)
    frame = frames.read_parquet(p, schema)
    version = {"_id": "v1", "version_number": 1, "schema": schema, "suggestions": [], "quality_score_before": 50, "quality_score_after": 90}
    return frame, frames.read_arrow(p), schema, version


def run(text, tmp_path, **plan):
    frame, table, schema, version = load(text, tmp_path)
    return run_verified(frame, table, schema, QueryPlan(**plan), version)


def test_money_aggregates_exact(tmp_path):
    s = run(GOLDEN, tmp_path, operation="aggregate", metric_column="amount", aggregation="sum")
    assert s["total"] == 101.01                    # 10.10+20.20+30.30+40.40+0.01
    d = s["calculation_details"]
    assert (d["rows_in"], d["rows_used"], d["rows_skipped"]) == (6, 5, 1)   # A4 has no amount
    assert d["verified_by"] == "duckdb" and all(c["passed"] for c in d["checks"])
    assert run(GOLDEN, tmp_path, operation="aggregate", metric_column="amount", aggregation="mean")["total"] == 20.202  # 101.01/5
    assert run(GOLDEN, tmp_path, operation="aggregate", metric_column="amount", aggregation="median")["total"] == 20.20
    assert run(GOLDEN, tmp_path, operation="aggregate", metric_column="amount", aggregation="min")["total"] == 0.01
    assert run(GOLDEN, tmp_path, operation="aggregate", aggregation="count")["total"] == 6
    assert run(GOLDEN, tmp_path, operation="aggregate", metric_column="region", aggregation="nunique")["total"] == 3


def test_exact_decimal_mean_not_rounded():
    import pandas as pd
    col = {"dtype": "decimal", "scale": 2}
    s = pd.Series([100, 100, 101], dtype="Int64")  # 1.00, 1.00, 1.01
    from fractions import Fraction
    mean = engine.aggregate_series(s, col, "mean")
    assert abs(Fraction(mean) - Fraction(301, 300)) < Fraction(1, 10 ** 30)   # 3.01 / 3, not rounded to cents
    assert engine.aggregate_series(s, col, "sum") == Decimal("3.01")


def test_group_shares_and_reconciliation(tmp_path):
    r = run(GOLDEN, tmp_path, operation="aggregate", metric_column="amount", aggregation="sum", group_by=["region"])
    rows = {row[0]: row for row in r["rows"]}
    assert set(rows) == {"North", "South"}                       # East's only amount is empty
    assert rows["North"][1] == 40.41 and rows["South"][1] == 60.60
    assert rows["North"][2] == pytest.approx(40.41 / 101.01, abs=1e-12)
    assert sum(row[2] for row in r["rows"]) == pytest.approx(1.0, abs=1e-9)
    names = [c["name"] for c in r["calculation_details"]["checks"]]
    assert "group totals add up to the grand total" in names and "shares add up to 100%" in names


def test_top_n_with_other(tmp_path):
    r = run(GOLDEN, tmp_path, operation="top_n", metric_column="amount", aggregation="sum", group_by=["product"], limit=1)
    assert r["rows"][0][0] == "Ink" and r["rows"][0][1] == 60.60        # Ink 20.20+40.40
    assert r["other"] == {"groups": 2, "value": 40.41, "rows": 3}        # Pen 40.40 + Pad 0.01


def test_trend_partial_periods_and_growth(tmp_path):
    r = run(GOLDEN, tmp_path, operation="trend", metric_column="amount", aggregation="sum", date_column="order_date", time_grain="month")
    by = {row[0]: row for row in r["rows"]}
    assert [by[m][2] for m in ("2024-01", "2024-02", "2024-03")] == [30.30, 30.30, 40.41]
    assert by["2024-01"][4] is True and by["2024-03"][4] is True     # data starts 3 Jan, ends 28 Mar
    assert all(row[3] is None for row in r["rows"])                  # growth excludes partial periods
    assert any("too few points" in w for w in r["calculation_details"]["warnings"])

    full = run(FULL_MONTHS, tmp_path, operation="trend", metric_column="units", aggregation="sum", date_column="day", time_grain="month")
    g = {row[0]: row[3] for row in full["rows"]}
    assert g["2024-01"] is None and g["2024-02"] == pytest.approx(0.4) and g["2024-03"] == pytest.approx(4 / 7)


def test_iso_weeks_start_monday(tmp_path):
    text = "When,N\n2024-01-01,1\n2024-01-07,2\n2024-01-08,4\n2024-01-14,8\n"   # Mon, Sun, Mon, Sun
    r = run(text, tmp_path, operation="trend", metric_column="n", aggregation="sum", date_column="when", time_grain="week")
    assert [(row[0], row[2]) for row in r["rows"]] == [("2024-W01", 3), ("2024-W02", 12)]


def test_growth_na_when_previous_zero(tmp_path):
    text = "Day,V\n2024-01-01,0\n2024-01-31,0\n2024-02-01,5\n2024-02-29,0\n"
    r = run(text, tmp_path, operation="trend", metric_column="v", aggregation="sum", date_column="day", time_grain="month")
    assert r["rows"][1][3] is None   # previous period total is 0 -> n/a


def test_filters(tmp_path):
    r = run(GOLDEN, tmp_path, operation="aggregate", metric_column="amount", aggregation="sum",
            filters=[{"column": "amount", "op": "gte", "value": "20.20"}, {"column": "region", "op": "in", "value": ["South", "North"]}])
    assert r["total"] == 90.90                                       # 20.20+30.30+40.40
    r = run(GOLDEN, tmp_path, operation="filter_count",
            filters=[{"column": "order_date", "op": "between", "value": ["2024-02-01", "2024-03-05"]}])
    assert r["rows"][0][0] == 3 and r["rows"][0][1] == 0.5           # A3, A4, A5 of 6
    r = run(GOLDEN, tmp_path, operation="filter_count", filters=[{"column": "amount", "op": "ne", "value": 10.10}])
    assert r["rows"][0][0] == 4                                      # empty amount never matches
    r = run(GOLDEN, tmp_path, operation="filter_count", filters=[{"column": "product", "op": "contains", "value": "pE"}])
    assert r["rows"][0][0] == 2


def test_shuffle_invariance(tmp_path):
    lines = GOLDEN.strip().splitlines()
    shuffled = "\n".join([lines[0]] + lines[1:][::-1]) + "\n"
    a = run(GOLDEN, tmp_path, operation="aggregate", metric_column="amount", aggregation="sum", group_by=["region"])
    b = run(shuffled, tmp_path, operation="aggregate", metric_column="amount", aggregation="sum", group_by=["region"])
    assert sorted(a["rows"]) == sorted(b["rows"]) and a["total"] == b["total"]


@pytest.mark.parametrize("plan,msg", [
    ({"operation": "aggregate", "metric_column": "nope", "aggregation": "sum"}, "does not exist"),
    ({"operation": "aggregate", "metric_column": "region", "aggregation": "sum"}, "not numeric"),
    ({"operation": "trend", "metric_column": "amount", "date_column": "region"}, "not a date"),
    ({"operation": "top_n", "metric_column": "amount", "group_by": []}, "exactly one"),
    ({"operation": "aggregate", "metric_column": "amount", "filters": [{"column": "amount", "op": "gt", "value": "abc"}]}, "not a valid"),
    ({"operation": "aggregate", "metric_column": "amount", "filters": [{"column": "region", "op": "gt", "value": "x"}]}, "works on numbers"),
    ({"operation": "aggregate", "metric_column": "amount; DROP TABLE data", "aggregation": "sum"}, "does not exist"),
])
def test_invalid_plans_rejected(tmp_path, plan, msg):
    frame, table, schema, version = load(GOLDEN, tmp_path)
    with pytest.raises(PlanError, match=msg):
        engine.execute(frame, schema, QueryPlan(**plan), version)


@pytest.mark.parametrize("bad", [
    {"operation": "aggregate", "expression": "__import__('os')"},          # unknown field
    {"operation": "eval", "metric_column": "amount"},                      # operation not allowed
    {"operation": "aggregate", "aggregation": "std"},                      # aggregation not allowed
    {"operation": "aggregate", "limit": 100000},                           # limit capped
    {"operation": "aggregate", "filters": [{"column": "a", "op": "regex", "value": ".*"}]},
])
def test_malicious_plan_values_rejected(bad):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        QueryPlan(**bad)


def test_no_numeric_or_date_columns_handled(tmp_path):
    frame, table, schema, version = load(NO_NUMBERS, tmp_path)
    r = run_verified(frame, table, schema, QueryPlan(operation="aggregate", aggregation="count", group_by=["team"]), version)
    assert {row[0]: row[1] for row in r["rows"]} == {"Red": 2, "Blue": 1}
    d = run_verified(frame, table, schema, QueryPlan(operation="describe", metric_column="team"), version)
    assert d["rows"][0] == ["Values", 3]
    prof = build_profile(frame, table, version, {})
    assert prof["correlation"] is None and prof["business"] is None and prof["outliers"] == []
    assert prof["trend"]["rows"]  # Joined is a date column, so a row-count trend exists


def test_verification_detects_mismatch(tmp_path):
    frame, table, schema, version = load(GOLDEN, tmp_path)
    plan = QueryPlan(operation="aggregate", metric_column="amount", aggregation="sum", group_by=["region"])
    wrong = {"groups": {("North",): (Decimal("40.42"), 3), ("South",): (Decimal("60.60"), 2)}, "rows_used": 5, "rows_in": 6}
    checks = verify.verify(table, plan, schema, wrong)
    assert not all(c["passed"] for c in checks)


def test_dual_engine_on_golden_datasets(tmp_path):
    from tests import fixtures as fx
    for text in (GOLDEN, fx.SALES_CSV, fx.WEATHER_CSV.decode("latin-1"), FULL_MONTHS):
        frame, table, schema, version = load(text, tmp_path)
        for c in schema:
            if c["dtype"] in ("integer", "float", "decimal"):
                for agg in ("sum", "mean", "min", "max", "median", "count"):
                    run_verified(frame, table, schema, QueryPlan(operation="aggregate", metric_column=c["key"], aggregation=agg), version)
                cat = next((x for x in schema if x["dtype"] == "string"), None)
                if cat:
                    run_verified(frame, table, schema, QueryPlan(operation="aggregate", metric_column=c["key"], aggregation="sum", group_by=[cat["key"]], limit=1000), version)


def test_business_metrics_aov(tmp_path):
    frame, table, schema, version = load(GOLDEN, tmp_path)
    b = build_profile(frame, table, version, {})["business"]
    assert b["revenue"]["value"] == 101.01 and b["revenue"]["column"] == "Amount"
    assert b["average_order_value"]["orders"] == 5                  # distinct order IDs with an amount
    assert b["average_order_value"]["value"] == pytest.approx(20.202)
    no_orders = GOLDEN.replace("Order ID", "Ref")
    frame, table, schema, version = load(no_orders, tmp_path, "w.parquet")
    b2 = build_profile(frame, table, version, {})["business"]
    assert b2["average_order_value"]["label"] == "Average per row"


# ------------------------------------------------------------------ API

async def _ds(client, text=GOLDEN):
    r = await client.post("/api/datasets/upload", files={"file": ("golden.csv", text.encode(), "text/csv")})
    assert r.status_code == 201
    return r.json()["dataset"]["id"]


async def test_query_api_records_analysis(auth_client, db):
    ds = await _ds(auth_client)
    r = await auth_client.post(f"/api/analytics/{ds}/query", json={"plan": {"operation": "aggregate", "metric_column": "amount", "aggregation": "sum"}})
    assert r.status_code == 200, r.text
    body = r.json()
    d = body["calculation_details"]
    assert body["total"] == 101.01 and d["dataset_version"] == 1 and d["rows_skipped"] == 1
    assert 'SUM("amount")' in d["equivalent_sql"]
    a = await db.analyses.find_one({"analysis_type": "query"})
    assert a and str(a["version_id"]) == d["version_id"]
    hist = (await auth_client.get("/api/analyses")).json()
    assert hist["pagination"]["total"] == 1


async def test_query_api_invalid_plan_is_422(auth_client):
    ds = await _ds(auth_client)
    r = await auth_client.post(f"/api/analytics/{ds}/query", json={"plan": {"operation": "aggregate", "metric_column": "zzz"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_plan"


async def test_chart_api(auth_client):
    ds = await _ds(auth_client)
    r = await auth_client.post(f"/api/analytics/{ds}/chart", json={"plan": {"operation": "aggregate", "metric_column": "amount",
                                                                            "aggregation": "sum", "group_by": ["region"]}})
    assert r.status_code == 200 and r.json()["chart"]["type"] == "bar"
    r = await auth_client.post(f"/api/analytics/{ds}/chart", json={"plan": {"operation": "aggregate", "metric_column": "amount",
                                                                            "aggregation": "sum", "group_by": ["region"]}, "chart_type": "stacked_bar"})
    assert r.status_code == 422


async def test_profile_cached_and_scoped(auth_client, other_client):
    ds = await _ds(auth_client)
    p1 = (await auth_client.post(f"/api/analytics/{ds}/profile", json={})).json()
    assert p1["cached"] is False and p1["profile"]["shape"]["rows"] == 6
    p2 = (await auth_client.post(f"/api/analytics/{ds}/profile", json={})).json()
    assert p2["cached"] is True
    assert (await other_client.post(f"/api/analytics/{ds}/profile", json={})).status_code == 404
    assert (await other_client.post(f"/api/analytics/{ds}/query", json={"plan": {"operation": "filter_count"}})).status_code == 404


def test_profile_warns_about_kept_total_rows(tmp_path):
    from tests import fixtures as fx
    r = run_cleaning(read_csv_grid(fx.SALES_CSV.encode(), 1000, 50).frame)
    schema = build_schema(r.frame, r.columns)
    p = tmp_path / "s.parquet"
    frames.write_parquet(r.frame, schema, p)
    version = {"_id": "v", "version_number": 1, "schema": schema, "cleaning_report": r.report, "suggestions": []}
    prof = build_profile(frames.read_parquet(p, schema), frames.read_arrow(p), version, {})
    assert any("did not add up" in i["message"] for i in prof["quality"]["issues"])

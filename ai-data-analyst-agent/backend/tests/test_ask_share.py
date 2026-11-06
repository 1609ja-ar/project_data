"""Ask (rule parser and AI plans), forecast, KPI targets and share links."""
import json

import pytest

from app.analytics import ask
from app.analytics.forecast import linear_forecast
from tests.test_analytics import load
from tests.test_auto_dashboard import sales_csv, sales_rows
from tests.test_reports_suggestions import clear_ai, mock_ai  # noqa: F401  (fixture + helper)


@pytest.fixture
def sales(tmp_path):
    return load(sales_csv(), tmp_path)


@pytest.mark.parametrize("q, op, group, agg, chart", [
    ("total revenue by region", "top_n", ["region"], "sum", "horizontal_bar"),
    ("Top 3 products by revenue", "top_n", ["product"], "sum", "horizontal_bar"),
    ("monthly units", "trend", [], "sum", "area"),
    ("revenue over time by region", "trend", ["region"], "sum", "stacked_bar"),
    ("average revenue by product", "top_n", ["product"], "mean", "horizontal_bar"),
    ("how many orders", "aggregate", [], "count", "kpi"),
    ("share of revenue by region", "top_n", ["region"], "sum", "donut"),
])
def test_rule_parser(sales, q, op, group, agg, chart):
    frame, _, schema, _ = sales
    p = ask.parse_question(q, frame, schema, {})
    assert p["plan"]["operation"] == op and p["plan"].get("group_by", []) == group
    assert p["plan"]["aggregation"] == agg and p["chart_type"] == chart


def test_rule_parser_filters_limits_and_years(sales):
    frame, _, schema, _ = sales
    p = ask.parse_question("top 2 products by revenue in north for 2023", frame, schema, {})
    assert p["plan"]["limit"] == 2
    assert {"column": "region", "op": "in", "value": ["North"]} in p["filters"]
    assert {"column": "order_date", "op": "gte", "value": "2023-01-01"} in p["filters"]
    assert ask.parse_question("lowest region by revenue", frame, schema, {})["plan"]["order"] == "asc"
    with pytest.raises(ask.AskError):
        ask.parse_question("hello there", frame, schema, {})


def test_check_filter_values_maps_spelling(sales):
    frame, _, schema, _ = sales
    by_key = {c["key"]: c for c in schema}
    f = [{"column": "region", "op": "eq", "value": "north"}]
    ask.check_filter_values(frame, by_key, f)
    assert f == [{"column": "region", "op": "in", "value": ["North"]}]
    with pytest.raises(ask.AskError):
        ask.check_filter_values(frame, by_key, [{"column": "region", "op": "in", "value": ["Nrth"]}])


def test_forecast_follows_an_exact_line():
    rows = [[f"2024-{m:02d}", f"2024-{m:02d}-01", 100.0 + 10 * (m - 1), None, False] for m in range(1, 10)]
    f = linear_forecast(rows, "month")
    assert [p["period"] for p in f["points"]] == ["2024-10", "2024-11", "2024-12"]
    assert [round(p["value"], 9) for p in f["points"]] == [190.0, 200.0, 210.0]
    assert f["r2"] == pytest.approx(1.0) and all(p["low"] == pytest.approx(p["value"]) for p in f["points"])
    rows[-1][4] = True                                                   # a trailing partial period is forecast in full
    assert linear_forecast(rows, "month")["points"][0]["period"] == "2024-09"
    assert linear_forecast(rows[:4], "month") is None


async def upload(client):
    r = await client.post("/api/datasets/upload", files={"file": ("s.csv", sales_csv().encode(), "text/csv")})
    return r.json()["dataset"]["id"]


async def test_ask_api_rules(auth_client):
    ds = await upload(auth_client)
    r = await auth_client.post("/api/ask", json={"dataset_id": ds, "question": "Total revenue by region in 2023"})
    assert r.status_code == 200
    a = r.json()
    north = sum(row[3] for row in sales_rows() if row[1] == "North")
    total = sum(row[3] for row in sales_rows())
    assert a["source"] == "rules" and a["answer"].startswith(f"North has the highest total revenue: ${north:,.2f}")
    assert f"{float(north / total):.1%} of the total" in a["answer"]
    assert a["tile"]["how_calculated"]["verified_by"] == "duckdb"
    assert "Order Date" in a["interpretation"]
    kpi = (await auth_client.post("/api/ask", json={"dataset_id": ds, "question": "how many records"})).json()
    assert kpi["chart_type"] == "kpi" and kpi["answer"] == f"Number of records: {len(sales_rows()):,}."
    odd = (await auth_client.post("/api/ask", json={"dataset_id": ds, "question": "revenue in Atlantis"})).json()
    assert odd["ignored"] == ["atlantis"]                              # unknown words are reported, not silently dropped
    bad = await auth_client.post("/api/ask", json={"dataset_id": ds, "question": "hello there"})
    assert bad.status_code == 422
    recent = (await auth_client.get(f"/api/ask/{ds}/recent")).json()["items"]
    assert [x["question"] for x in recent[:2]] == ["revenue in Atlantis", "how many records"]
    assert (await auth_client.get(f"/api/ask/{ds}/suggestions")).json()["items"]


async def test_ask_api_ai_plan_and_fallback(auth_client, monkeypatch, clear_ai):  # noqa: F811
    ds = await upload(auth_client)
    sent = mock_ai(monkeypatch, json.dumps({"plan": {"operation": "top_n", "metric_column": "units", "aggregation": "sum",
                                                     "group_by": ["product"], "limit": 1, "filters": [{"column": "region", "op": "in", "value": ["east"]}]},
                                            "chart": "horizontal_bar"}))
    a = (await auth_client.post("/api/ask", json={"dataset_id": ds, "question": "best selling product in the east"})).json()
    east_units = {}
    for _, region, product, _, units in sales_rows():
        if region == "East":
            east_units[product] = east_units.get(product, 0) + units
    best = max(east_units, key=east_units.get)
    assert a["source"] == "ai" and a["answer"].startswith(f"{best} has the highest total units: {east_units[best]:,}")
    assert "Region in East" in a["interpretation"]
    assert "2023-03-31" not in json.dumps(sent[0])                    # no rows go to the model

    mock_ai(monkeypatch, json.dumps({"plan": {"operation": "top_n", "metric_column": "nope", "group_by": ["region"]}}))
    a = (await auth_client.post("/api/ask", json={"dataset_id": ds, "question": "total revenue by region"})).json()
    assert a["source"] == "rules" and a["answer"].startswith("North")    # invalid AI plan -> rule parser


async def test_goals_attach_progress(auth_client):
    ds = await upload(auth_client)
    total = float(sum(row[3] for row in sales_rows()))
    assert (await auth_client.put(f"/api/analytics/{ds}/goals", json={"key": "revenue:sum", "target": total * 2})).status_code == 200
    dash = (await auth_client.post(f"/api/analytics/{ds}/dashboard", json={})).json()
    g = next(k for k in dash["kpis"] if k["key"] == "revenue:sum")["goal"]
    assert g["progress"] == pytest.approx(0.5) and g["gap"] == pytest.approx(-total)
    assert next(k for k in dash["kpis"] if k["key"] == "records:count")["goal"] is None
    bad = await auth_client.put(f"/api/analytics/{ds}/goals", json={"key": "nope:sum", "target": 1})
    assert bad.status_code == 422
    await auth_client.delete(f"/api/analytics/{ds}/goals/revenue:sum")
    dash = (await auth_client.post(f"/api/analytics/{ds}/dashboard", json={})).json()
    assert all(k["goal"] is None for k in dash["kpis"])


async def test_share_link_snapshot_and_revoke(auth_client, db):
    import httpx
    from app.main import app

    ds = await upload(auth_client)
    r = await auth_client.post(f"/api/analytics/{ds}/share", json={"title": "For the team", "expires_in_days": 3,
                                                                   "filters": [{"column": "region", "values": ["South"]}]})
    assert r.status_code == 201
    link = r.json()
    token = link["path"].split("/s/")[1]
    anon = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")  # signed-out viewer
    view = await anon.get(f"/api/public/share/{token}")
    assert view.status_code == 200
    snap = view.json()["snapshot"]
    assert view.json()["title"] == "For the team" and snap["rows_in_view"] == sum(1 for row in sales_rows() if row[1] == "South")
    assert all("how_calculated" not in k for k in snap["kpis"]) and all("plan" not in t for t in snap["tiles"])
    assert (await auth_client.get(f"/api/analytics/{ds}/share")).json()["items"][0]["views"] == 1
    assert (await auth_client.delete(f"/api/share-links/{link['id']}")).status_code == 200
    assert (await anon.get(f"/api/public/share/{token}")).status_code == 404
    assert (await anon.get("/api/public/share/shr_doesnotexist")).status_code == 404
    await anon.aclose()


def test_period_words_and_trend_answer():
    assert [ask.period_words(p) for p in ("2024-03", "2024-Q1", "2024-W09", "2024-03-05", "2024")] == \
        ["Mar 2024", "Q1 2024", "week 9 of 2024", "5 Mar 2024", "2024"]
    result = {"metric_label": "Sum of Units", "columns": [{"key": "period"}, {"key": "period_start"}, {"key": "value", "label": "Sum of Units"},
                                                          {"key": "growth"}, {"key": "partial"}],
              "rows": [["2024-01", "2024-01-01", 40, None, False], ["2024-02", "2024-02-01", 50, 0.25, False]]}
    text = ask.answer_text(result, {"operation": "trend"}, lambda v, c: f"{v:,}")
    assert text == "Total units went from 40 in Jan 2024 to 50 in Feb 2024 (+25.0%)."

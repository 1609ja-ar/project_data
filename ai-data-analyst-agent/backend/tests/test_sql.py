"""SQL Workbench (Phase 4b) and AI SQL helpers."""
import json
import time

import httpx
import pytest

from app.ai import provider as ai_provider
from app.analytics.verify import connect_locked
from app.core.config import get_settings
from app.security.sql_guard import validate_sql
from tests.test_analytics import GOLDEN

OTHER = "Region,Manager\nNorth,Nia\nSouth,Sam\n"


async def _upload(c, name, text):
    r = await c.post("/api/datasets/upload", files={"file": (name, text.encode(), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()["dataset"]["id"]


async def _run(c, ds, sql):
    return await c.post(f"/api/sql/{ds}/run", json={"sql": sql})


async def test_select_join_cte_window_and_matches_pandas(auth_client):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    await _upload(auth_client, "managers.csv", OTHER)
    schema = (await auth_client.get(f"/api/sql/{ds}/schema")).json()
    names = [t["name"] for t in schema["tables"]]
    assert names[0] == "data" and "ds_managers" in names
    sql = """WITH r AS (SELECT region, SUM(amount) AS total FROM data GROUP BY region)
             SELECT r.region, r.total, m.manager, RANK() OVER (ORDER BY r.total DESC) AS rnk
             FROM r JOIN ds_managers m ON m.region = r.region ORDER BY rnk"""
    r = await _run(auth_client, ds, sql)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == [["South", 60.6, "Sam", 1], ["North", 40.41, "Nia", 2]]
    assert body["columns"][1]["sql_type"].startswith("DECIMAL")
    assert body["executed_sql"].endswith(f"LIMIT {get_settings().sql_max_rows + 1}") and sql.strip() in body["executed_sql"]
    assert body["dataset_version"] == 1 and body["truncated"] is False
    # Same numbers as the Pandas query-plan engine
    plan = {"operation": "aggregate", "metric_column": "amount", "aggregation": "sum", "group_by": ["region"]}
    q = (await auth_client.post(f"/api/analytics/{ds}/query", json={"plan": plan})).json()
    assert {row[0]: row[1] for row in q["rows"]} == {"South": 60.6, "North": 40.41}


async def test_decimal_sum_exact(auth_client):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    r = (await _run(auth_client, ds, "SELECT SUM(amount) AS s, CAST(SUM(amount) AS VARCHAR) AS exact FROM data")).json()
    assert r["rows"] == [[101.01, "101.01"]]


@pytest.mark.parametrize("sql", [
    "DROP TABLE data", "INSERT INTO data VALUES (1)", "ATTACH 'x.db'", "COPY data TO 'out.csv'", "PRAGMA version",
    "INSTALL httpfs", "SET threads = 8", "SELECT 1; SELECT 2", "SELECT * FROM read_csv('requirements.txt')",
    "SELECT * FROM read_parquet('x.parquet')", "SELECT * FROM 'requirements.txt'", "SELECT 1 /* ; */; DROP TABLE data",
    "SELECT * FROM duckdb_settings()", "SELECT * FROM information_schema.tables", "SELECT * FROM pragma_database_list()",
    "SELECT current_setting('enable_external_access')", "SELECT * FROM query('SELECT 1')", "SELECT * FROM main.data",
])
async def test_rejected_statements(auth_client, sql):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    r = await _run(auth_client, ds, sql)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_sql", (sql, r.text)
    v = (await auth_client.post(f"/api/sql/{ds}/validate", json={"sql": sql})).json()
    assert v["valid"] is False


async def test_parser_error_has_position(auth_client):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    v = (await auth_client.post(f"/api/sql/{ds}/validate", json={"sql": "SELECT region\nFROM data WHERE"})).json()
    assert v["valid"] is False and v["line"] == 2


async def test_cannot_reach_other_users_data(auth_client, other_client):
    mine = await _upload(auth_client, "golden.csv", GOLDEN)
    theirs = await _upload(other_client, "secret.csv", "Secret\n42\n")
    assert (await _run(auth_client, theirs, "SELECT * FROM data")).status_code == 404
    r = await _run(auth_client, mine, "SELECT * FROM ds_secret")
    assert r.status_code == 400 and "Unknown table" in r.json()["error"]["message"]
    tables = [t["name"] for t in (await auth_client.get(f"/api/sql/{mine}/schema")).json()["tables"]]
    assert tables == ["data"]


def test_locked_settings_cannot_change():
    con = connect_locked()
    for stmt in ("SET enable_external_access=true", "SET lock_configuration=false", "SET threads=16", "SET memory_limit='10GB'"):
        with pytest.raises(Exception, match="(?i)configuration"):
            con.execute(stmt)
    with pytest.raises(Exception, match="(?i)disabled|permission"):
        con.execute("SELECT * FROM read_csv('requirements.txt')")


async def test_row_cap_and_truncated_flag(auth_client, monkeypatch):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    monkeypatch.setattr(get_settings(), "sql_max_rows", 2)
    r = (await _run(auth_client, ds, "SELECT order_id FROM data ORDER BY order_id")).json()
    assert r["row_count"] == 2 and r["truncated"] is True and r["rows"] == [["A1"], ["A2"]]


async def test_runaway_query_killed_by_timeout(auth_client, monkeypatch):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    assert (await _run(auth_client, ds, "SELECT 1 AS warm FROM data LIMIT 1")).status_code == 200  # start the worker
    monkeypatch.setattr(get_settings(), "sql_timeout_seconds", 3)
    joins = ", ".join(f"data t{i}" for i in range(14))  # 6^14 rows
    t0 = time.perf_counter()
    r = await _run(auth_client, ds, f"SELECT COUNT(*) FROM {joins}")
    elapsed = time.perf_counter() - t0
    assert r.status_code == 504 and r.json()["error"]["code"] == "timeout"
    assert elapsed < 8
    monkeypatch.setattr(get_settings(), "sql_timeout_seconds", 30)
    assert (await _run(auth_client, ds, "SELECT COUNT(*) AS n FROM data")).json()["rows"] == [[6]]  # pool recreated


async def test_sql_runtime_error_is_friendly(auth_client):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    r = await _run(auth_client, ds, "SELECT no_such_column FROM data")
    assert r.status_code == 400 and r.json()["error"]["code"] == "sql_error" and "no_such_column" in r.json()["error"]["message"]


async def test_run_recorded_as_analysis(auth_client, db):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    await _run(auth_client, ds, "SELECT COUNT(*) FROM data")
    assert await db.analyses.count_documents({"analysis_type": "sql"}) == 1


async def test_saved_queries(auth_client, other_client):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    r = await auth_client.post("/api/sql/saved", json={"dataset_id": ds, "name": "Totals", "sql": "SELECT SUM(amount) FROM data"})
    assert r.status_code == 201
    qid = r.json()["id"]
    assert (await auth_client.post("/api/sql/saved", json={"dataset_id": ds, "name": "Bad", "sql": "DROP TABLE data"})).status_code == 400
    items = (await auth_client.get("/api/sql/saved", params={"dataset_id": ds})).json()["items"]
    assert [i["name"] for i in items] == ["Totals"]
    assert (await other_client.delete(f"/api/sql/saved/{qid}")).status_code == 404
    assert (await auth_client.delete(f"/api/sql/saved/{qid}")).status_code == 200


# ------------------------------------------------------------------ AI helpers (mocked provider)

async def test_ai_not_configured(auth_client):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    r = await auth_client.post("/api/ai/sql/generate", json={"dataset_id": ds, "question": "total by region"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "ai_not_configured"


@pytest.fixture
def mock_groq(monkeypatch):
    sent = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        sent.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": body})
        if "Explain" in body["messages"][0]["content"]:
            content = "- Adds up amount per region."
        else:
            content = "```sql\nSELECT region, SUM(amount) AS total FROM data GROUP BY region\n```"
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})

    monkeypatch.setattr(get_settings(), "groq_api_key", "gsk_test_placeholder")
    ai_provider.set_test_transport(httpx.MockTransport(handler))
    yield sent
    ai_provider.set_test_transport(None)


async def test_ai_generate_and_explain_send_no_rows_by_default(auth_client, mock_groq):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    r = await auth_client.post("/api/ai/sql/generate", json={"dataset_id": ds, "question": "total by region"})
    assert r.status_code == 200, r.text
    assert r.json()["valid"] is True and r.json()["sql"].startswith("SELECT region")
    req = mock_groq[0]
    assert req["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert req["auth"] == "Bearer gsk_test_placeholder"
    prompt = json.dumps(req["body"])
    assert "amount" in prompt and "A1" not in prompt and "10.1" not in prompt   # schema only, no row values
    e = await auth_client.post("/api/ai/sql/explain", json={"sql": "SELECT 1"})
    assert e.status_code == 200 and e.json()["sent_data"] is False


async def test_ai_sends_samples_only_when_allowed(auth_client, mock_groq):
    ds = await _upload(auth_client, "golden.csv", GOLDEN)
    await auth_client.patch("/api/auth/me", json={"allow_ai_samples": True})
    await auth_client.post("/api/ai/sql/generate", json={"dataset_id": ds, "question": "total by region"})
    assert "A1" in json.dumps(mock_groq[-1]["body"])


def test_number_check_marks_unverified():
    text, bad = ai_provider.check_numbers("Revenue was $101.01, up 40% from 72.5 in the top 3 regions in 2024.", [101.01, 0.4])
    assert bad == ["72.5"] and "72.5 [unverified]" in text and "$101.01 [" not in text and "40% [" not in text

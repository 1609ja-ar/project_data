"""Chart suggestions (rules and AI pick), pinned tiles, reports and tailored exports."""
import io
import json

import httpx
import pytest
from openpyxl import load_workbook

from app.analytics import recommend
from tests.test_analytics import load
from tests.test_auto_dashboard import REGIONS, sales_csv, sales_rows


def schema_of(tmp_path):
    return load(sales_csv(), tmp_path)[2]


def test_rule_menu_covers_different_questions(tmp_path):
    menu = recommend.candidates(schema_of(tmp_path), {})
    families = {c["family"] for c in menu}
    assert {"trend", "ranking", "share", "composition", "average", "mix"} <= families
    assert len({c["id"] for c in menu}) == len(menu)
    picked = recommend.rule_pick(menu)
    assert 1 <= len(picked) <= recommend.MAX_SUGGESTIONS
    assert max(sum(1 for p in picked if p["family"] == f) for f in families) <= 2
    assert picked[0]["family"] == "trend" and picked[0]["plan"]["metric_column"] == "revenue"


def test_ai_pick_only_accepts_menu_ids(tmp_path):
    menu = recommend.candidates(schema_of(tmp_path), {})
    a, b = menu[3]["id"], menu[0]["id"]
    text = 'Sure! {"charts": [{"id": "%s", "why": "Shows mix."}, {"id": "invented123", "why": "x"}, {"id": "%s"}, {"id": "%s"}]}' % (a, b, a)
    picked = recommend.parse_ai_pick(text, menu)
    assert [p["id"] for p in picked] == [a, b]                       # order kept, unknown and duplicate ids dropped
    assert picked[0]["why"] == "Shows mix." and picked[0]["source"] == "ai"
    assert picked[1]["why"] == menu[0]["reason"]                     # missing reason falls back to the rule's
    assert recommend.parse_ai_pick("no json here", menu) == []
    # A reply cut off by the token limit still yields its complete items.
    cut = '{"charts": [{"id": "%s", "why": "Trend first."}, {"id": "%s", "why": "Ranks"}, {"id": "%s", "wh' % (b, a, menu[5]["id"])
    assert [p["id"] for p in recommend.parse_ai_pick(cut, menu)] == [b, a, menu[5]["id"]]
    assert recommend.parse_ai_pick(cut, menu)[0]["why"] == "Trend first."


@pytest.fixture
async def sales_ds(auth_client):
    r = await auth_client.post("/api/datasets/upload", files={"file": ("s.csv", sales_csv().encode(), "text/csv")})
    return r.json()["dataset"]["id"]


def mock_ai(monkeypatch, reply):
    from app.ai import provider as ai_provider
    from app.core.config import get_settings

    sent = []

    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": reply(sent[-1]) if callable(reply) else reply}}]})
    monkeypatch.setattr(get_settings(), "xai_api_key", "xai-test-placeholder")
    ai_provider.set_test_transport(httpx.MockTransport(handler))
    return sent


@pytest.fixture
def clear_ai():
    yield
    from app.ai import provider as ai_provider
    ai_provider.set_test_transport(None)


async def test_suggestions_without_ai_use_rules_and_verified_numbers(auth_client, sales_ds):
    r = (await auth_client.post(f"/api/analytics/{sales_ds}/chart-suggestions", json={})).json()
    assert r["source"] == "rules" and 1 <= len(r["charts"]) <= 6
    for c in r["charts"]:
        assert c["how_calculated"]["verified_by"] == "duckdb" and all(k["passed"] for k in c["how_calculated"]["checks"])
        assert c["why"] if "why" in c else c["reason"]
    trend = r["charts"][0]
    assert trend["chart"]["spec"]["x"] == "period" and trend["plan"]["time_grain"] == "auto"
    total = sum(row[3] for row in sales_rows())
    vi = [c["key"] for c in trend["chart"]["columns"]].index("value")
    assert sum(row[vi] for row in trend["chart"]["rows"]) == pytest.approx(float(total))


async def test_suggestions_with_ai_follow_the_model_choice(auth_client, sales_ds, monkeypatch, clear_ai):
    from app.analytics import recommend as rec
    from app.services import datasets as svc

    def reply(body):
        # Pick the "mix" and "share" options from the menu the server sent.
        options = json.loads(body["messages"][1]["content"].split("Chart options: ")[1].split("\n\n")[0])
        mix = next(o["id"] for o in options if "mix within" in o["title"])
        share = next(o["id"] for o in options if o["title"].startswith("Share of"))
        return json.dumps({"charts": [{"id": mix, "why": "Mix differs by region."}, {"id": "bogus"}, {"id": share, "why": "Few regions."}]})
    sent = mock_ai(monkeypatch, reply)
    r = (await auth_client.post(f"/api/analytics/{sales_ds}/chart-suggestions", json={})).json()
    assert r["source"] == "ai" and r["provider"]
    assert [c["chart"]["spec"]["type"] for c in r["charts"]] == ["stacked_100_bar", "donut"]
    assert r["charts"][0]["reason"] == "Mix differs by region."
    assert "2023-01-01" not in json.dumps(sent[0])                   # no rows are sent, only column metadata

    mock_ai(monkeypatch, "I cannot help with that.")
    r = (await auth_client.post(f"/api/analytics/{sales_ds}/chart-suggestions", json={})).json()
    assert r["source"] == "rules" and r["note"] and r["charts"]


async def test_pin_suggestion_to_dashboard_and_filter_it(auth_client, sales_ds):
    sug = (await auth_client.post(f"/api/analytics/{sales_ds}/chart-suggestions", json={"use_ai": False})).json()
    pick = next(c for c in sug["charts"] if c["chart_type"] == "horizontal_bar")
    p = await auth_client.post(f"/api/analytics/{sales_ds}/dashboard/tiles",
                               json={"title": pick["title"], "chart_type": pick["chart_type"], "plan": pick["plan"], "reason": pick["reason"]})
    assert p.status_code == 201
    tid = p.json()["id"]
    dash = (await auth_client.post(f"/api/analytics/{sales_ds}/dashboard", json={})).json()
    assert [t["id"] for t in dash["custom_tiles"]] == [tid] and dash["cached"] is False
    again = (await auth_client.post(f"/api/analytics/{sales_ds}/chart-suggestions", json={"use_ai": False})).json()
    assert next(c for c in again["charts"] if c["id"] == pick["id"])["pinned"] is True

    filt = (await auth_client.post(f"/api/analytics/{sales_ds}/dashboard", json={"filters": [{"column": "region", "values": ["East"]}]})).json()
    tile = filt["custom_tiles"][0]
    assert {row[0] for row in tile["chart"]["rows"]} == {"East"}       # pinned charts follow the dashboard filters

    bad = await auth_client.post(f"/api/analytics/{sales_ds}/dashboard/tiles",
                                 json={"title": "x", "chart_type": "bar", "plan": {"operation": "top_n", "group_by": ["nope"]}})
    assert bad.status_code == 422
    assert (await auth_client.delete(f"/api/analytics/{sales_ds}/dashboard/tiles/{tid}")).status_code == 200
    assert (await auth_client.post(f"/api/analytics/{sales_ds}/dashboard", json={})).json()["custom_tiles"] == []


async def test_report_without_ai_uses_templates_over_verified_facts(auth_client, sales_ds):
    r = await auth_client.post("/api/reports", json={"dataset_id": sales_ds, "use_ai": True, "title": "Q report"})
    assert r.status_code == 201
    rep = r.json()
    assert rep["source"] == "template" and rep["title"] == "Q report"
    assert rep["note"] is None or "AI" in rep["note"]
    total = sum(row[3] for row in sales_rows())
    kpi = rep["facts"]["kpis"][0]
    assert kpi["value"] == pytest.approx(float(total)) and kpi["how_calculated"]["verified_by"] == "duckdb"
    assert f"{len(sales_rows()):,} records" in rep["narrative"]["executive_summary"]
    assert rep["facts"]["charts"] and rep["facts"]["columns"] and rep["facts"]["insights"]
    lst = (await auth_client.get("/api/reports")).json()["items"]
    assert [x["id"] for x in lst] == [rep["id"]] and "facts" not in lst[0]
    assert (await auth_client.get(f"/api/reports/{rep['id']}")).json()["narrative"] == rep["narrative"]
    assert (await auth_client.delete(f"/api/reports/{rep['id']}")).status_code == 200
    assert (await auth_client.get(f"/api/reports/{rep['id']}")).status_code == 404


async def test_report_with_ai_marks_invented_numbers(auth_client, sales_ds, monkeypatch, clear_ai):
    total = sum(row[3] for row in sales_rows())
    reply = json.dumps({"executive_summary": f"Revenue totals ${total:,.2f} across {len(REGIONS)} regions, about 999,999 more than planned.",
                        "key_findings": ["North leads."], "recommendations": ["Review East."], "chart_notes": {"bogus": "x"}})
    sent = mock_ai(monkeypatch, reply)
    rep = (await auth_client.post("/api/reports", json={"dataset_id": sales_ds})).json()
    assert rep["source"] == "ai" and rep["unverified"] == ["999,999"]
    assert "999,999 [unverified]" in rep["narrative"]["executive_summary"]
    assert f"${total:,.2f} [unverified]" not in rep["narrative"]["executive_summary"]
    assert rep["narrative"]["chart_notes"] == {}                      # notes for unknown charts are dropped
    assert "2023-03-31" not in json.dumps(sent[0])                   # aggregates only: no individual row dates

    mock_ai(monkeypatch, "not json")
    rep = (await auth_client.post("/api/reports", json={"dataset_id": sales_ds})).json()
    assert rep["source"] == "template" and "templates" in rep["note"]


async def test_tailored_excel_export(auth_client, sales_ds):
    view = {"columns": ["order_date", "region", "revenue"], "filters": [{"column": "region", "values": ["North"]}],
            "date_from": "2023-01-01", "date_to": "2023-06-30"}
    keep = [r for r in sales_rows() if r[1] == "North" and r[0] <= "2023-06-30"]
    pre = (await auth_client.post(f"/api/exports/{sales_ds}/preview", json=view)).json()
    assert pre["rows"] == len(keep) and [c["key"] for c in pre["columns"]] == view["columns"] and len(pre["sample"]) == 12

    r = await auth_client.post(f"/api/exports/{sales_ds}/excel-custom", json={**view, "include_cleaning": False})
    assert r.status_code == 200 and r.headers["x-rows-exported"] == str(len(keep))
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "Data", "Data dictionary", "Aggregates", "Charts"]
    data = wb["Data"]
    assert [c.value for c in data[1]] == ["Order Date", "Region", "Revenue"] and data.max_row == len(keep) + 1
    summary = {row[0].value: row[1].value for row in wb["Summary"].iter_rows() if row[0].value}
    assert float(summary["Total Revenue"]) == pytest.approx(float(sum(r[3] for r in keep)))
    assert len(wb["Charts"]._charts) >= 3

    empty = await auth_client.post(f"/api/exports/{sales_ds}/excel-custom", json={"date_from": "2030-01-01"})
    assert empty.status_code == 422


async def test_powerbi_setup_scripts(auth_client, sales_ds):
    r = (await auth_client.get(f"/api/powerbi/{sales_ds}/setup", params={"base_url": "http://localhost:5173"})).json()
    assert r["feed_url"] == f"http://localhost:5173/api/feed/{sales_ds}.csv"
    assert 'Web.Contents(FeedUrl, [Headers = [Authorization = "Bearer " & Token]])' in r["m_web"]
    assert "PASTE_TOKEN_HERE" in r["m_web"] and "Revenue" in r["dax"]
    assert (await auth_client.get(f"/api/powerbi/{sales_ds}/setup", params={"base_url": "javascript:alert(1)"})).status_code == 422

"""Power BI package, Excel export, export tokens and the refreshable feed (Phase 4c)."""
import csv
import io
import json
import re
import zipfile
from datetime import timedelta
from decimal import Decimal

import openpyxl
import pytest

from app.core.config import get_settings
from app.core.logging import redact
from app.security.tokens import now_utc, sha256_hex

TRICKY = (
    'Order ID,Customer Name,"Unit ""Price"" [USD]",Order Date,Note\n'
    'O-1,Ana,$12.50,2024-01-05,=SUM(A1)\n'
    'O-2,Ben,($3.25),2024-02-10,+cmd\n'
    'O-3,Cy,$100.00,2024-03-15,ok\n'
)
EXPECTED_PRICE_SUM = Decimal("12.50") + Decimal("-3.25") + Decimal("100.00")   # 109.25


async def _ds(c, text=TRICKY, name="tricky.csv"):
    r = await c.post("/api/datasets/upload", files={"file": (name, text.encode(), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()["dataset"]["id"]


async def test_powerbi_package_contents_and_escaping(auth_client):
    ds = await _ds(auth_client)
    r = await auth_client.get(f"/api/powerbi/{ds}/package")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(z.namelist()) == {"data.csv", "data.parquet", "data_dictionary.csv", "Load.pq", "measures.dax", "README_PowerBI.md"}
    m = z.read("Load.pq").decode()
    assert '{"Unit ""Price"" [USD]", Currency.Type}' in m
    assert '{"Order Date", type date}' in m and '{"Customer Name", type text}' in m
    assert 'FilePath = "C:\\Users\\you\\Downloads\\data.csv"' in m
    # M references only existing columns
    header = next(csv.reader(io.StringIO(z.read("data.csv").decode())))
    referenced = [s.replace('""', '"') for s in re.findall(r'\{"((?:[^"]|"")*)", ', m)]
    assert sorted(referenced) == sorted(header)
    dax = z.read("measures.dax").decode()
    assert "Total Revenue = SUM('data'[Unit \"Price\" [USD]]])" in dax       # ] doubled inside brackets
    assert "Order Count = DISTINCTCOUNT('data'[Order ID])" in dax
    assert "DIVIDE([Total Revenue], [Order Count])" in dax and "SAMEPERIODLASTYEAR" in dax and "DateTable = " in dax
    for col in re.findall(r"'data'\[((?:[^\]]|\]\])*)\]", dax):
        assert col.replace("]]", "]") in header
    dd = list(csv.DictReader(io.StringIO(z.read("data_dictionary.csv").decode())))
    assert {r["display_name"] for r in dd} == set(header)


async def test_dax_skips_revenue_measures_without_revenue_column(auth_client):
    ds = await _ds(auth_client, "Student,Score\nAna,90\nBo,75\n", "marks.csv")
    z = zipfile.ZipFile(io.BytesIO((await auth_client.get(f"/api/powerbi/{ds}/package")).content))
    dax = z.read("measures.dax").decode()
    assert "Total Revenue" not in dax and "Total Score = SUM('data'[Score])" in dax


async def test_token_shown_once_stored_hashed(auth_client, db):
    ds = await _ds(auth_client)
    r = await auth_client.post("/api/export-tokens", json={"name": "PBI", "dataset_id": ds, "expires_in_days": 7})
    assert r.status_code == 201
    token = r.json()["token"]
    assert token.startswith("pbi_") and r.json()["token_prefix"] == token[:8]
    doc = await db.export_tokens.find_one({})
    assert doc["token_hash"] == sha256_hex(token) and token not in json.dumps(doc, default=str)
    listed = (await auth_client.get("/api/export-tokens")).json()["items"]
    assert "token" not in listed[0] and listed[0]["status"] == "active"
    too_long = await auth_client.post("/api/export-tokens", json={"name": "x", "expires_in_days": get_settings().export_token_max_days + 1})
    assert too_long.status_code == 400


async def _token(c, ds=None, days=7):
    body = {"name": "t", "expires_in_days": days, **({"dataset_id": ds} if ds else {})}
    return (await c.post("/api/export-tokens", json=body)).json()


async def test_feed_csv_matches_cleaned_data(auth_client):
    ds = await _ds(auth_client)
    tok = (await _token(auth_client, ds))["token"]
    import httpx
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as anon:
        r = await anon.get(f"/api/feed/{ds}.csv", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200 and r.headers["x-dataset-version"] == "1"
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert len(rows) == 3
        assert sum(Decimal(row['Unit "Price" [USD]']) for row in rows) == EXPECTED_PRICE_SUM
        assert rows[1]['Unit "Price" [USD]'] == "-3.25"                         # negative intact
        assert rows[0]["Note"] == "'=SUM(A1)"                                   # text escaped only
        j = await anon.get(f"/api/feed/{ds}.json", params={"columns": "order_id,unit_price_usd"}, headers={"Authorization": f"Bearer {tok}"})
        body = j.json()
        assert body["columns"] == ["order_id", "unit_price_usd"] and body["rows"][1] == {"order_id": "O-2", "unit_price_usd": -3.25}


async def test_token_rejections(auth_client, db):
    ds = await _ds(auth_client)
    other_ds = await _ds(auth_client, "A\n1\n", "other.csv")
    t = await _token(auth_client, ds)
    import httpx
    from app.main import app
    hdr = {"Authorization": f"Bearer {t['token']}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as anon:
        # never accepted on other routes
        assert (await anon.get("/api/datasets", headers=hdr)).status_code == 401
        assert (await anon.get(f"/api/datasets/{ds}/download", headers=hdr)).status_code == 401
        assert (await anon.get(f"/api/powerbi/{ds}/package", headers=hdr)).status_code == 401
        # another dataset
        assert (await anon.get(f"/api/feed/{other_ds}.csv", headers=hdr)).status_code == 404
        # no / wrong token
        assert (await anon.get(f"/api/feed/{ds}.csv")).status_code == 401
        assert (await anon.get(f"/api/feed/{ds}.csv", headers={"Authorization": "Bearer pbi_wrong"})).status_code == 401
        # expired
        await db.export_tokens.update_one({"_id": __import__("bson").ObjectId(t["id"])}, {"$set": {"expires_at": now_utc() - timedelta(seconds=1)}})
        assert (await anon.get(f"/api/feed/{ds}.csv", headers=hdr)).status_code == 401
        # revoked
        t2 = await _token(auth_client, ds)
        assert (await anon.get(f"/api/feed/{ds}.csv", headers={"Authorization": f"Bearer {t2['token']}"})).status_code == 200
        assert (await auth_client.delete(f"/api/export-tokens/{t2['id']}")).status_code == 200
        assert (await anon.get(f"/api/feed/{ds}.csv", headers={"Authorization": f"Bearer {t2['token']}"})).status_code == 401
    last = await db.export_tokens.find_one({"_id": __import__("bson").ObjectId(t2["id"])})
    assert last["last_used_at"] is not None


async def test_token_cannot_read_other_users_dataset(auth_client, other_client):
    mine = await _ds(auth_client)
    t = await _token(other_client)  # all of *their* datasets
    import httpx
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as anon:
        assert (await anon.get(f"/api/feed/{mine}.csv", headers={"Authorization": f"Bearer {t['token']}"})).status_code == 404


async def test_token_in_url_refused_by_default_and_redacted(auth_client, monkeypatch):
    ds = await _ds(auth_client)
    tok = (await _token(auth_client, ds))["token"]
    import httpx
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as anon:
        r = await anon.get(f"/api/feed/{ds}.csv", params={"token": tok})
        assert r.status_code == 401 and "disabled" in r.json()["error"]["message"]
        monkeypatch.setattr(get_settings(), "export_token_in_url", True)
        assert (await anon.get(f"/api/feed/{ds}.csv", params={"token": tok})).status_code == 200
    assert redact(f"GET /api/feed/x.csv?version=1&token={tok}") == "GET /api/feed/x.csv?version=1&token=[REDACTED]"


async def test_excel_export_roundtrip(auth_client):
    ds = await _ds(auth_client)
    chart = (await auth_client.post(f"/api/analytics/{ds}/chart", json={"plan": {
        "operation": "aggregate", "metric_column": "unit_price_usd", "aggregation": "sum", "group_by": ["customer_name"]}})).json()
    r = await auth_client.get(f"/api/exports/{ds}/excel", params={"charts": chart["analysis_id"]})
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Data", "Data dictionary", "Cleaning report", "Aggregates", "Charts"]
    data = wb["Data"]
    header = [c.value for c in data[1]]
    pc = header.index('Unit "Price" [USD]') + 1
    values = [data.cell(row=i, column=pc).value for i in range(2, data.max_row + 1)]
    assert sum(Decimal(str(v)) for v in values) == EXPECTED_PRICE_SUM
    assert data.cell(row=3, column=pc).value == -3.25 and "$" in data.cell(row=3, column=pc).number_format
    note = data.cell(row=2, column=header.index("Note") + 1)
    assert note.value == "=SUM(A1)" and note.data_type == "s"                 # text, not a formula
    assert data.freeze_panes == "A2" and data.auto_filter.ref
    date_cell = data.cell(row=2, column=header.index("Order Date") + 1)
    assert date_cell.is_date
    charts = wb["Charts"]._charts
    assert len(charts) == 1
    agg = wb["Aggregates"]
    for ref in re.findall(r"'?Aggregates'?!\$([A-Z]+)\$(\d+)(?::\$([A-Z]+)\$(\d+))?", charts[0].series[0].val.numRef.f):
        assert int(ref[1]) <= agg.max_row
    assert agg.cell(row=3, column=2).value is not None


async def test_sql_result_xlsx(auth_client):
    ds = await _ds(auth_client)
    r = await auth_client.post(f"/api/exports/{ds}/sql-xlsx", json={"sql": "SELECT order_id, unit_price_usd FROM data ORDER BY order_id"})
    assert r.status_code == 200
    ws = openpyxl.load_workbook(io.BytesIO(r.content))["Result"]
    assert [c.value for c in ws[1]] == ["order_id", "unit_price_usd"] and ws.cell(row=3, column=2).value == -3.25
    assert (await auth_client.post(f"/api/exports/{ds}/sql-xlsx", json={"sql": "DROP TABLE data"})).status_code == 400

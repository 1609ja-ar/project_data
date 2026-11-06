"""Pivot tables (verified at every level, no row limit) and importing spreadsheets from a link."""
import io
import time
from collections import defaultdict
from decimal import Decimal

import pytest

from app.analytics import pivot as pv
from app.analytics.engine import CalculationCheckFailed
from app.analytics.pivot import build_pivot
from app.analytics.plan import PlanError
from app.services import fetch as remote
from tests.test_analytics import load
from tests.test_ask_share import upload
from tests.test_auto_dashboard import sales_csv, sales_rows

SUM_REV = {"column": "revenue", "aggregation": "sum"}


def load_large(text, tmp_path):
    from app.cleaning import frames
    from app.cleaning.pipeline import run_cleaning
    from app.cleaning.profile import build_schema
    from app.services.ingest import read_csv_grid
    r = run_cleaning(read_csv_grid(text.encode(), 1_000_000, 50).frame)
    schema = build_schema(r.frame, r.columns)
    path = tmp_path / "big.parquet"
    frames.write_parquet(r.frame, schema, path)
    return frames.read_parquet(path, schema), frames.read_arrow(path), schema, {"_id": "v1", "version_number": 1, "schema": schema}


@pytest.fixture
def sales(tmp_path):
    return load(sales_csv(), tmp_path)


def pivot(sales, **spec):
    frame, table, schema, version = sales
    return build_pivot(frame, table, schema, version, spec)


def by_path(out):
    return {tuple(r["path"]): r for r in out["rows"]}


def test_nested_rows_subtotals_and_columns_match_plain_python(sales):
    out = pivot(sales, rows=["region", "product"], columns="order_date", grain="year", measures=[SUM_REV])
    expect = defaultdict(Decimal)
    for _, region, product, value, _ in sales_rows():
        expect[(region, product)] += value
    rows = by_path(out)
    for (region, product), want in expect.items():
        leaf = rows[(region, product)]
        assert Decimal(str(leaf["totals"][0])) == want and not leaf["subtotal"]
    for region in {k[0] for k in expect}:
        sub = rows[(region,)]
        assert sub["subtotal"] and Decimal(str(sub["totals"][0])) == sum(v for (r, _), v in expect.items() if r == region)
    assert Decimal(str(out["grand_total"][0])) == sum(expect.values())
    assert out["columns"] == ["2023"] and out["column_totals"][0] == out["grand_total"][0]
    # tree order: a subtotal comes right before its children
    order = [tuple(r["path"]) for r in out["rows"]]
    assert order.index(("North",)) + 1 == order.index(next(p for p in order if len(p) == 2 and p[0] == "North"))
    assert out["verification"]["passed"] == out["verification"]["checks"] >= 9


def test_every_aggregation_matches_pandas_at_every_level(sales):
    import pandas as pd
    ref = pd.DataFrame(sales_rows(), columns=["d", "region", "product", "revenue", "units"])
    ref["revenue"] = ref["revenue"].astype(float)
    for agg in ("sum", "mean", "median", "min", "max"):
        out = pivot(sales, rows=["region", "product"], columns=None,
                    measures=[{"column": "revenue", "aggregation": agg}, {"column": "units", "aggregation": agg}])
        rows = by_path(out)
        for path, r in rows.items():
            part = ref[ref["region"] == path[0]] if len(path) == 1 else ref[(ref["region"] == path[0]) & (ref["product"] == path[1])]
            for i, col in enumerate(("revenue", "units")):
                assert r["totals"][i] == pytest.approx(float(getattr(part[col], agg)()), rel=1e-9), (agg, path, col)
        for i, col in enumerate(("revenue", "units")):
            assert out["grand_total"][i] == pytest.approx(float(getattr(ref[col], agg)()), rel=1e-9)


def test_subtotals_of_averages_are_true_averages_not_averages_of_cells(tmp_path):
    # North: Desk has 1 order of 100, Chair has 3 orders of 10. True average 32.5; the average of the two cell averages would be 55.
    rows = ["Region,Product,Amount"] + ["North,Desk,100"] + ["North,Chair,10"] * 3 + ["South,Desk,40", "South,Chair,60"]
    small = load("\n".join(rows) + "\n", tmp_path)
    out = pivot(small, rows=["region", "product"], measures=[{"column": "amount", "aggregation": "mean"}])
    got = by_path(out)
    assert got[("North", "Desk")]["totals"][0] == 100 and got[("North", "Chair")]["totals"][0] == 10
    assert got[("North",)]["totals"][0] == pytest.approx(32.5)
    assert out["grand_total"][0] == pytest.approx(230 / 6)


def test_periods_columns_sorting_and_top_n(sales):
    out = pivot(sales, rows=["order_date"], columns="region", grain="quarter", measures=[SUM_REV, {"column": None, "aggregation": "count"}])
    assert [r["path"][0] for r in out["rows"]] == ["2023-Q1", "2023-Q2", "2023-Q3", "2023-Q4"]
    assert out["columns"] == sorted(out["columns"]) and len(out["rows"][0]["cells"]) == len(out["columns"]) * 2
    q1_rows = sum(1 for d, *_ in sales_rows() if d < "2023-04")
    assert out["rows"][0]["totals"][1] == q1_rows
    desc = pivot(sales, rows=["order_date"], grain="quarter", measures=[SUM_REV], sort={"by": "label", "direction": "desc"})
    assert [r["path"][0] for r in desc["rows"]][0] == "2023-Q4"
    top = pivot(sales, rows=["product"], measures=[SUM_REV], top_n=2)
    allp = pivot(sales, rows=["product"], measures=[SUM_REV])
    assert [r["path"] for r in top["rows"]] == [r["path"] for r in allp["rows"][:2]]
    assert top["rows_total_count"] == len(allp["rows"]) and top["grand_total"] == allp["grand_total"]  # totals keep everything
    by_label = pivot(sales, rows=["region"], measures=[SUM_REV], sort={"by": "label", "direction": "asc"})
    assert [r["path"][0] for r in by_label["rows"]] == sorted(r["path"][0] for r in by_label["rows"])
    assert by_label["rows"][0]["totals"] != [None]


def test_filters_empty_result_and_invalid_specs(sales):
    f = {"column": "region", "op": "in", "value": ["North"]}
    out = pivot(sales, rows=["product"], measures=[SUM_REV], filters=[f])
    assert out["rows_in"] == sum(1 for _, r, *_ in sales_rows() if r == "North") and out["filters"]
    none = pivot(sales, rows=["product"], measures=[SUM_REV], filters=[{"column": "region", "op": "eq", "value": "Atlantis"}])
    assert none["empty"] and none["rows"] == []
    for bad in ({"rows": []}, {"rows": ["region"], "columns": "region"}, {"rows": ["nope"]}, {"rows": ["revenue"]},
                {"rows": ["region", "product", "order_date", "units"]},
                {"rows": ["region"], "measures": [{"column": "region", "aggregation": "sum"}]},
                {"rows": ["region"], "measures": [SUM_REV, SUM_REV]}):
        with pytest.raises(PlanError):
            pivot(sales, **bad)


def test_engine_disagreement_is_caught(sales, monkeypatch):
    monkeypatch.setattr(pv, "_same", lambda m, a, b: False)
    with pytest.raises(CalculationCheckFailed):
        pivot(sales, rows=["region"], measures=[SUM_REV])


def test_output_limits_are_clear_errors(sales, monkeypatch):
    monkeypatch.setattr(pv, "MAX_COLUMNS", 2)
    with pytest.raises(PlanError, match="at most 2 columns"):
        pivot(sales, rows=["product"], columns="region", measures=[SUM_REV])
    monkeypatch.setattr(pv, "MAX_CELLS", 3)
    with pytest.raises(PlanError, match="cells that can be shown"):
        pivot(sales, rows=["region", "product"], measures=[SUM_REV])


def test_no_row_limit_on_large_data(tmp_path):
    n, groups = 60_000, 25_000
    lines = ["Code,Region,Amount,Qty"] + [f"K{i % groups:05d},{('North', 'South', 'East', 'West')[i % 4]},{(i % 97) + 0.25:.2f},{i % 7}" for i in range(n)]
    big = load_large("\n".join(lines) + "\n", tmp_path)
    t = time.time()
    out = pivot(big, rows=["code"], columns="region", measures=[{"column": "amount", "aggregation": "sum"}, {"column": "qty", "aggregation": "mean"}])
    assert len(out["rows"]) == out["rows_total_count"] == groups  # every group, nothing cut at 200 or 1,000
    assert out["rows_used"] == n and out["verification"]["passed"] == out["verification"]["checks"]
    assert sum(r["totals"][0] for r in out["rows"]) == pytest.approx(out["grand_total"][0], rel=1e-9)
    assert time.time() - t < 60


async def test_pivot_api_and_excel_export(auth_client):
    from openpyxl import load_workbook
    ds = await upload(auth_client)
    body = {"rows": ["region", "product"], "columns": "order_date", "grain": "year", "measures": [SUM_REV, {"column": None, "aggregation": "count"}],
            "filters": [{"column": "region", "op": "in", "value": ["North", "South"]}]}
    r = await auth_client.post(f"/api/analytics/{ds}/pivot", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert {x["path"][0] for x in out["rows"]} == {"North", "South"} and out["filters"]
    x = await auth_client.post(f"/api/analytics/{ds}/pivot/export", json=body)
    assert x.status_code == 200 and x.headers["content-disposition"].endswith('.xlsx"')
    wb = load_workbook(io.BytesIO(x.content), read_only=True)
    assert wb.sheetnames == ["Pivot", "About"]
    rows = list(wb["Pivot"].iter_rows(values_only=True))
    assert rows[0][:2] == ("Region", "Product") and rows[-1][0] == "Grand total"
    grand = out["grand_total"]
    assert rows[-1][-2:] == (pytest.approx(grand[0]), grand[1])  # real numbers, not text
    bad = await auth_client.post(f"/api/analytics/{ds}/pivot", json={"rows": ["revenue"], "measures": [SUM_REV]})
    assert bad.status_code == 422
    none = await auth_client.post(f"/api/analytics/{ds}/pivot", json={"rows": []})
    assert none.status_code == 422


# ---------------------------------------------------------------- import from a link

def test_google_sheet_links_become_csv_exports():
    src, dl, name = remote.normalize("https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit#gid=42")
    assert dl == "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/export?format=csv&gid=42"
    assert src == dl and name == "google_sheet.csv"


@pytest.mark.parametrize("url, code", [
    ("http://example.com/a.csv", "invalid_url"),
    ("https://user:pw@example.com/a.csv", "invalid_url"),
    ("https://docs.google.com/document/d/abc/edit", "invalid_url"),
])
def test_bad_links_rejected(url, code):
    with pytest.raises(remote.FetchError) as e:
        remote.normalize(url)
    assert e.value.code == code


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "localhost"])
def test_private_addresses_blocked(host):
    with pytest.raises(remote.FetchError) as e:
        remote._check_host(host)
    assert e.value.code == "blocked_address"


def test_html_pages_are_not_files():
    with pytest.raises(remote.FetchError) as e:
        remote._file_type("view", "text/html; charset=utf-8", b"<!DOCTYPE html><html>")
    assert e.value.code == "not_a_file"
    assert remote._file_type("export", "text/csv", b"a,b\n1,2\n") == "csv"


async def test_import_url_and_refresh(auth_client, monkeypatch):
    calls = {"n": 0}
    first = sales_csv().encode()
    second = sales_csv(sales_rows()[:-4]).encode()

    async def fake_fetch(url, max_bytes):
        calls["n"] += 1
        data = first if calls["n"] <= 2 else second
        return remote.Fetched(data, "csv", "orders.csv", url, url)

    monkeypatch.setattr(remote, "fetch", fake_fetch)
    r = await auth_client.post("/api/datasets/import-url", json={"url": "https://example.com/orders.csv", "name": "Orders"})
    assert r.status_code == 201, r.text
    ds = r.json()["dataset"]
    assert ds["filename"] == "Orders.csv" and ds["source"]["kind"] == "url"
    d = (await auth_client.get(f"/api/datasets/{ds['id']}")).json()
    assert d["cleaning_status"] == "done" and d["active_version"]["version_number"] == 1

    same = await auth_client.post(f"/api/datasets/{ds['id']}/refresh")
    assert same.status_code == 202 and same.json()["changed"] is False

    changed = await auth_client.post(f"/api/datasets/{ds['id']}/refresh")
    assert changed.json()["changed"] is True
    d = (await auth_client.get(f"/api/datasets/{ds['id']}")).json()
    assert d["active_version"]["version_number"] == 2 and d["row_count"] == len(sales_rows()) - 4

    uploaded = await upload(auth_client)
    r = await auth_client.post(f"/api/datasets/{uploaded}/refresh")
    assert r.status_code == 400

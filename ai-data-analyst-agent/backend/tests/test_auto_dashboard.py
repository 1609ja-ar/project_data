"""Automatic dashboard: tile choice, filters and numbers, checked against plain-Python oracles."""
import calendar
from decimal import Decimal

import pandas as pd
import pytest

from app.analytics.dashboard import DashboardOptions, auto_grain, build_dashboard
from tests.test_analytics import load

REGIONS = {"North": 300, "South": 120, "East": 45}
PRODUCTS = {"Desk": Decimal("2.5"), "Chair": Decimal("1")}


def sales_rows():
    """One row per month x region x product on the 1st and the last day (so every month is complete)."""
    rows = []
    for m in range(1, 13):
        last = calendar.monthrange(2023, m)[1]
        for region, base in REGIONS.items():
            for product, mult in PRODUCTS.items():
                for day in (1, last):
                    rows.append((f"2023-{m:02d}-{day:02d}", region, product, (Decimal(base + 10 * m) * mult).quantize(Decimal("0.01")), m))
    return rows


def sales_csv(rows=None):
    rows = rows or sales_rows()
    return "Order Date,Region,Product,Revenue,Units\n" + "".join(f"{d},{r},{p},${v},{u}\n" for d, r, p, v, u in rows)


def build(text, tmp_path, **opts):
    frame, table, schema, version = load(text, tmp_path)
    return build_dashboard(frame, table, version, {}, DashboardOptions(**opts))


def tile(res, kind):
    return [t for t in res["tiles"] if t["kind"] == kind]


def test_default_dashboard_layout_and_numbers(tmp_path):
    rows = sales_rows()
    res = build(sales_csv(rows), tmp_path)
    total = sum(r[3] for r in rows)
    assert res["measure"]["key"] == "revenue" and res["aggregation"] == "sum" and res["grain"] == "month"
    kpis = {k["id"]: k for k in res["kpis"]}
    assert kpis["primary"]["value"] == pytest.approx(float(total), abs=1e-9)
    assert kpis["records"]["value"] == len(rows)
    assert kpis["average"]["value"] == pytest.approx(float(total / len(rows)), rel=1e-12)
    assert kpis["second"]["label"] == "Total Units" and kpis["second"]["value"] == sum(r[4] for r in rows)

    # Period change: December vs November, both complete.
    by_month = {}
    for d, _, _, v, _ in rows:
        by_month[d[:7]] = by_month.get(d[:7], 0) + v
    ch = kpis["primary"]["change"]
    assert (ch["period"], ch["previous_period"]) == ("2023-12", "2023-11")
    assert ch["pct"] == pytest.approx(float((by_month["2023-12"] - by_month["2023-11"]) / by_month["2023-11"]), rel=1e-12)
    assert len(kpis["primary"]["spark"]) == 12

    kinds = [t["kind"] for t in res["tiles"]]
    assert kinds == ["trend", "share", "breakdown", "split", "table"]
    share = tile(res, "share")[0]
    vi = [c["key"] for c in share["chart"]["columns"]].index("share")
    region_tot = {k: sum(r[3] for r in rows if r[1] == k) for k in REGIONS}
    for row in share["chart"]["rows"]:
        assert row[vi] == pytest.approx(float(region_tot[row[0]] / total), rel=1e-12)
    assert sum(r[vi] for r in share["chart"]["rows"]) == pytest.approx(1.0, abs=1e-12)

    table = tile(res, "table")[0]
    keys = [c["key"] for c in table["chart"]["columns"]]
    assert keys == ["region", "value", "share", "records", "average", "second"]
    north = next(r for r in table["chart"]["rows"] if r[0] == "North")
    n_rows = [r for r in rows if r[1] == "North"]
    assert north[1] == pytest.approx(float(region_tot["North"]))
    assert north[3] == len(n_rows) and north[4] == pytest.approx(float(region_tot["North"] / len(n_rows)), rel=1e-12)
    assert north[5] == sum(r[4] for r in n_rows)

    split = tile(res, "split")[0]
    assert split["chart"]["spec"]["type"] == "stacked_bar" and len(split["chart"]["rows"]) == 12 * len(REGIONS)


def test_every_number_is_dual_engine_verified(tmp_path):
    res = build(sales_csv(), tmp_path)
    details = [k["how_calculated"] for k in res["kpis"]] + [t["how_calculated"] for t in res["tiles"]]
    assert details and res["skipped"] == []
    for d in details:
        assert d["verified_by"] == "duckdb" and all(c["passed"] for c in d["checks"])


def test_filters_and_date_range(tmp_path):
    rows = sales_rows()
    res = build(sales_csv(rows), tmp_path, date_from="2023-03-01", date_to="2023-05-31",
                filters=[{"column": "region", "values": ["North", "East"]}])
    keep = [r for r in rows if "2023-03-01" <= r[0] <= "2023-05-31" and r[1] in ("North", "East")]
    assert res["rows_in_view"] == len(keep)
    assert res["kpis"][0]["value"] == pytest.approx(float(sum(r[3] for r in keep)))
    assert res["filters_applied"] == ["Order Date ≥ 2023-03-01", "Order Date ≤ 2023-05-31", "Region in North, East"]
    assert res["grain"] == "week"                                            # three months -> weekly points
    share = tile(res, "share")[0]
    assert {r[0] for r in share["chart"]["rows"]} == {"North", "East"}
    assert res["date_bounds"] == {"min": "2023-01-01", "max": "2023-12-31"}     # bounds ignore filters
    assert res["view_bounds"] == {"min": "2023-03-01", "max": "2023-05-31"}


def test_datetime_end_date_includes_whole_day(tmp_path):
    text = "Stamp,Amount\n2024-01-01 09:00,1\n2024-01-02 18:30,2\n2024-01-03 08:00,4\n"
    res = build(text, tmp_path, date_to="2024-01-02")
    assert res["rows_in_view"] == 2 and res["kpis"][0]["value"] == 3


def test_empty_view_returns_no_tiles(tmp_path):
    res = build(sales_csv(), tmp_path, date_from="2030-01-01")
    assert res["rows_in_view"] == 0 and res["kpis"] == [] and res["tiles"] == []


def test_without_date_or_measure(tmp_path):
    res = build("Team,Score\nRed,10\nRed,12\nBlue,9\nBlue,15\nGreen,11\n", tmp_path)
    assert res["aggregation"] == "mean"                                      # a score is averaged, not added
    assert res["kpis"][0]["value"] == pytest.approx(57 / 5) and res["kpis"][0]["change"] is None
    assert not tile(res, "trend") and any(s["tile"] == "Trend" for s in res["skipped"])

    res = build("City,Status\nParis,Open\nRome,Closed\nParis,Open\nOslo,Open\n", tmp_path)
    assert res["measure"] is None and [k["label"] for k in res["kpis"]] == ["Records", "Distinct City"]
    assert [k["value"] for k in res["kpis"]] == [4, 3]
    table = tile(res, "table")[0]
    assert [c["key"] for c in table["chart"]["columns"]] == ["city", "value", "share"]    # no duplicate count column


def test_measure_choice_and_invalid_options(tmp_path):
    res = build(sales_csv(), tmp_path, measure="units", aggregation="mean")
    assert res["kpis"][0]["label"] == "Average Units"
    assert {m["key"] for m in res["measures"]} == {"revenue", "units"}
    with pytest.raises(ValueError):
        build(sales_csv(), tmp_path, measure="region")
    with pytest.raises(ValueError):
        build(sales_csv(), tmp_path, filters=[{"column": "revenue", "values": ["1"]}])
    with pytest.raises(ValueError):
        build("Team,Score\nRed,1\nBlue,2\n", tmp_path, date_from="2024-01-01")


def test_auto_grain_thresholds():
    def span(days):
        return pd.Series(pd.Timestamp("2024-01-01") + pd.to_timedelta([0, days], unit="D"))
    assert [auto_grain(span(d)) for d in (30, 120, 700, 2000, 6000)] == ["day", "week", "month", "quarter", "year"]


# ------------------------------------------------------------------ API

async def test_dashboard_api_cache_and_filters(auth_client, db):
    r = await auth_client.post("/api/datasets/upload", files={"file": ("s.csv", sales_csv().encode(), "text/csv")})
    ds = r.json()["dataset"]["id"]
    first = (await auth_client.post(f"/api/analytics/{ds}/dashboard", json={})).json()
    assert first["cached"] is False and first["kpis"][0]["id"] == "primary"
    second = (await auth_client.post(f"/api/analytics/{ds}/dashboard", json={})).json()
    assert second["cached"] is True and second["analysis_id"] == first["analysis_id"]

    filt = await auth_client.post(f"/api/analytics/{ds}/dashboard", json={"filters": [{"column": "region", "values": ["South"]}]})
    assert filt.status_code == 200 and filt.json()["analysis_id"] is None and filt.json()["rows_in_view"] == 48
    assert await db.analyses.count_documents({"analysis_type": "dashboard"}) == 1   # filtered views are not stored

    bad = await auth_client.post(f"/api/analytics/{ds}/dashboard", json={"date_from": "03/01/2023"})
    assert bad.status_code == 422
    bad = await auth_client.post(f"/api/analytics/{ds}/dashboard", json={"filters": [{"column": "revenue", "values": ["1"]}]})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_options"

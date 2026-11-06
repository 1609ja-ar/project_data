"""Automated insights (Phase 4d): planted patterns with hand-computed expectations."""
import calendar
import math
import random

import pytest

from app.analytics.insights import InsightOptions, generate_insights
from tests.test_analytics import load

MONTHS = [f"2023-{m:02d}" for m in range(1, 13)]


def trend_csv(boost_month=None):
    """Monthly sum = 1000 + 100*i (two rows per month, on the 1st and last day so every month is complete)."""
    lines = ["Day,Sales"]
    for i, m in enumerate(MONTHS):
        v = (500 + 50 * i) * (5 if i == boost_month else 1)
        last = calendar.monthrange(2023, i + 1)[1]
        lines += [f"{m}-01,{v}", f"{m}-{last},{v}"]
    return "\n".join(lines) + "\n"


def run_insights(text, tmp_path, **opts):
    frame, table, schema, version = load(text, tmp_path)
    return generate_insights(frame, table, version, {}, InsightOptions(**opts))


def by_type(res, t):
    return [i for i in res["insights"] if i["type"] == t]


def test_planted_trend(tmp_path):
    res = run_insights(trend_csv(), tmp_path)
    t = by_type(res, "trend")
    assert len(t) == 1
    n = t[0]["evidence"]["numbers"]
    assert n["slope"] == pytest.approx(100.0)                        # +100 per month by construction
    assert n["periods"] == 12
    assert n["mean"] == pytest.approx(1550.0)                         # mean of 1000..2100
    assert n["relative_change"] == pytest.approx(100 * 11 / 1550)
    assert t[0]["severity"] == "important" and "upward" in t[0]["headline"]
    assert not by_type(res, "anomaly")


def test_planted_anomaly(tmp_path):
    res = run_insights(trend_csv(boost_month=6), tmp_path)
    a = by_type(res, "anomaly")
    assert len(a) == 1
    assert a[0]["evidence"]["numbers"]["period_value"] == 8000.0      # (500+50*6) * 5 * 2 rows
    assert "2023-07" in a[0]["detail"] and "screening" in a[0]["headline"]


def test_planted_top_contributor(tmp_path):
    rows = ["Region,Amount"] + ["North,$100.00"] * 7 + ["South,$100.00"] * 2 + ["East,$100.00"]
    res = run_insights("\n".join(rows) + "\n", tmp_path)
    top = by_type(res, "top_contributor")[0]
    n = top["evidence"]["numbers"]
    assert n["top_share"] == pytest.approx(0.7, abs=1e-12) and n["total"] == 1000.0 and n["groups"] == 3
    assert top["severity"] == "important" and top["headline"].startswith("North contributes 70.0%")


def _pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))


def test_planted_correlation(tmp_path):
    xs = list(range(1, 41))
    ys = [2 * x + ((x % 3) - 1) for x in xs]
    text = "Hours,Output\n" + "\n".join(f"{x},{y}" for x, y in zip(xs, ys)) + "\n"
    rel = by_type(run_insights(text, tmp_path), "relationship")
    assert len(rel) == 1
    assert rel[0]["evidence"]["numbers"]["pearson_r"] == pytest.approx(_pearson(xs, ys), abs=1e-12)
    assert rel[0]["evidence"]["numbers"]["n"] == 40
    assert "not causation" in rel[0]["headline"]


def test_planted_segment_difference(tmp_path):
    rows = ["Team,Score"] + [f"Red,{v}" for v in range(10, 40)] + [f"Blue,{v}" for v in range(30, 60)]
    seg = by_type(run_insights("\n".join(rows) + "\n", tmp_path), "segment_difference")
    assert len(seg) == 1
    n = seg[0]["evidence"]["numbers"]
    assert {round(n["mean_a"], 9), round(n["mean_b"], 9)} == {24.5, 44.5}     # (10+39)/2 and (30+59)/2
    assert n["n_a"] == n["n_b"] == 30 and "Welch" in seg[0]["detail"]


def test_random_data_has_no_important_insights(tmp_path):
    rng = random.Random(42)
    lines = ["Day,Group,Value,Other"]
    for _ in range(400):
        lines.append(f"2023-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d},{rng.choice('ABCD')},{rng.gauss(100, 15):.2f},{rng.gauss(50, 5):.2f}")
    res = run_insights("\n".join(lines) + "\n", tmp_path)
    assert [i for i in res["insights"] if i["severity"] == "important"] == []
    assert res["tests_run"] <= 20


def test_small_sample_no_trend_or_tests(tmp_path):
    text = "Day,Sales\n" + "\n".join(f"2023-{m:02d}-15,{100 + m}" for m in range(1, 6)) + "\n"
    res = run_insights(text, tmp_path)
    assert not by_type(res, "trend") and not by_type(res, "relationship") and not by_type(res, "segment_difference")
    assert any("Not enough data to call a trend" in s["reason"] for s in res["skipped"])


def test_insight_numbers_pass_dual_engine(tmp_path):
    rows = ["Region,Day,Amount"]
    for i, m in enumerate(MONTHS):
        rows += [f"North,{m}-01,${(300 + 40 * i):.2f}", f"South,{m}-15,$100.00", f"East,{m}-28,$50.25"]
    res = run_insights("\n".join(rows) + "\n", tmp_path)
    verified = [i for i in res["insights"] if i["how_calculated"]]
    assert verified
    for ins in verified:
        assert ins["how_calculated"]["verified_by"] == "duckdb"
        assert all(c["passed"] for c in ins["how_calculated"]["checks"])
        for key in ("id", "type", "severity", "score", "headline", "detail", "evidence", "how_calculated",
                    "suggested_chart_spec", "caveats", "possible_next_checks"):
            assert key in ins


def test_date_range_and_focus_options(tmp_path):
    res = run_insights(trend_csv(), tmp_path, date_from="2023-01-01", date_to="2023-03-31")
    assert res["filters"] == ["Day between 2023-01-01 and 2023-03-31"] and not by_type(res, "trend")
    with pytest.raises(ValueError):
        run_insights(trend_csv(), tmp_path, focus_measure="day")


# ------------------------------------------------------------------ API

async def test_insights_api_cache_and_overview(auth_client, db):
    r = await auth_client.post("/api/datasets/upload", files={"file": ("t.csv", trend_csv().encode(), "text/csv")})
    ds = r.json()["dataset"]["id"]
    assert (await auth_client.get(f"/api/analytics/{ds}/insights")).json()["insights"] is None
    first = (await auth_client.post(f"/api/analytics/{ds}/insights", json={})).json()
    assert first["cached"] is False and first["insights"][0]["type"] == "trend"
    second = (await auth_client.post(f"/api/analytics/{ds}/insights", json={})).json()
    assert second["cached"] is True and second["analysis_id"] == first["analysis_id"]
    summary = (await auth_client.get("/api/dashboard/summary")).json()
    assert summary["important_findings"]["insights"][0]["headline"] == first["insights"][0]["headline"]
    assert await db.analyses.count_documents({"analysis_type": "insights"}) == 1


async def test_explain_requires_provider_and_checks_numbers(auth_client, monkeypatch):
    import json
    import httpx
    from app.ai import provider as ai_provider
    from app.core.config import get_settings
    r = await auth_client.post("/api/datasets/upload", files={"file": ("t.csv", trend_csv().encode(), "text/csv")})
    ds = r.json()["dataset"]["id"]
    ins = (await auth_client.post(f"/api/analytics/{ds}/insights", json={})).json()
    e = await auth_client.post(f"/api/analytics/{ds}/insights/explain", json={"analysis_id": ins["analysis_id"]})
    assert e.status_code == 400 and e.json()["error"]["code"] == "ai_not_configured"

    sent = []

    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Sales grow by about 100 each month, not 250."}}]})
    monkeypatch.setattr(get_settings(), "xai_api_key", "xai-test-placeholder")
    ai_provider.set_test_transport(httpx.MockTransport(handler))
    try:
        e = (await auth_client.post(f"/api/analytics/{ds}/insights/explain", json={"analysis_id": ins["analysis_id"]})).json()
    finally:
        ai_provider.set_test_transport(None)
    assert e["unverified"] == ["250"] and "250 [unverified]" in e["text"] and "100 [unverified]" not in e["text"]
    assert "2023-01-01" not in json.dumps(sent[0])   # only verified insight payloads are sent, no rows

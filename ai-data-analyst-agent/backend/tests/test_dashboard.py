async def test_summary_empty_state(auth_client):
    r = await auth_client.get("/api/dashboard/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total_datasets"] == 0
    assert body["total_rows"] == 0
    assert body["completed_analyses"] == 0
    assert body["generated_reports"] == 0
    assert body["recent_datasets"] == [] and body["recent_analyses"] == []
    assert body["important_findings"] is None


async def test_summary_requires_auth(client):
    assert (await client.get("/api/dashboard/summary")).status_code == 401


async def test_providers_none_configured(auth_client):
    r = await auth_client.get("/api/ai/providers")
    assert r.status_code == 200
    assert r.json()["active"] is None
    assert all(p["configured"] is False for p in r.json()["providers"])

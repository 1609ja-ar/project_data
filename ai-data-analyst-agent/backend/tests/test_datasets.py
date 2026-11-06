"""Upload, storage and dataset API (Phase 3) plus cleaning versions/suggestions routes (Phase 3b)."""
import hashlib
import io

import pytest
import xlwt

from app.core.config import get_settings
from app.services.storage import get_storage
from tests import fixtures as fx


async def upload(c, name, data, sheet=None):
    files = {"file": (name, data, "application/octet-stream")}
    r = await c.post("/api/datasets/upload", files=files, data={"sheet": sheet} if sheet else None)
    return r


async def upload_ok(c, name, data):
    r = await upload(c, name, data)
    assert r.status_code == 201, r.text
    ds_id = r.json()["dataset"]["id"]
    d = (await c.get(f"/api/datasets/{ds_id}")).json()
    assert d["cleaning_status"] == "done", d
    return r.json(), d


def xls_bytes():
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Shipments")
    for j, h in enumerate(["Shipment", "Weight kg", "Shipped"]):
        ws.write(0, j, h)
    for i, (a, b, s) in enumerate([("S-01", 12.5, "yes"), ("S-02", 7.25, "no"), ("S-03", 3.0, "yes")], start=1):
        ws.write(i, 0, a)
        ws.write(i, 1, b)
        ws.write(i, 2, s)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


THEMED = [
    ("sales.csv", fx.SALES_CSV.encode("utf-8"), 7),
    ("weather.csv", fx.WEATHER_CSV, 5),
    ("students.xlsx", fx.student_marks_xlsx(), 4),
    ("shipments.xls", xls_bytes(), 3),
]


@pytest.mark.parametrize("name,data,rows", THEMED, ids=[t[0] for t in THEMED])
async def test_themed_uploads_clean_and_preview(auth_client, name, data, rows):
    up, d = await upload_ok(auth_client, name, data)
    assert up["raw_preview"]["rows"] and up["column_names"]
    assert d["row_count"] == rows and d["active_version"]["version_number"] == 1
    assert d["active_version"]["kind"] == "auto_cleaned"
    p = (await auth_client.get(f"/api/datasets/{d['id']}/preview", params={"page_size": 2, "highlight": True})).json()
    assert p["pagination"]["total"] == rows and len(p["rows"]) == min(2, rows)
    raw = (await auth_client.get(f"/api/datasets/{d['id']}/preview", params={"version": "raw"})).json()
    assert raw["version"] == "raw"


async def test_upload_response_and_raw_file_immutable(auth_client, db):
    data = fx.SALES_CSV.encode("utf-8")
    up, d = await upload_ok(auth_client, "sales.csv", data)
    assert up["cleaning_status"] == "pending"
    doc = await db.datasets.find_one({})
    assert doc["raw_sha256"] == hashlib.sha256(data).hexdigest()
    on_disk = get_storage().path(doc["raw_storage_ref"]).read_bytes()
    assert hashlib.sha256(on_disk).hexdigest() == doc["raw_sha256"]  # untouched after cleaning
    # stored under a generated name, not the client filename
    assert "sales" not in doc["raw_storage_ref"]
    raw_dl = await auth_client.get(f"/api/datasets/{d['id']}/download", params={"version": "raw"})
    assert raw_dl.content == data


async def test_excel_sheets_listed_and_first_nonempty_chosen(auth_client):
    up, d = await upload_ok(auth_client, "two.xlsx", fx.xlsx_with_two_sheets())
    assert up["sheets"] == ["Blank", "Data"] and d["sheet"] == "Data"


async def test_invalid_type_rejected(auth_client):
    r = await upload(auth_client, "data.json", b'{"a": 1}')
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_type"
    r = await upload(auth_client, "fake.xlsx", b"just,some,text\n1,2,3\n")
    assert r.status_code == 400 and "not a valid .xlsx" in r.json()["error"]["message"]
    r = await upload(auth_client, "fake.xls", b"hello")
    assert r.status_code == 400


async def test_macro_workbook_rejected(auth_client):
    import zipfile
    buf = io.BytesIO(fx.student_marks_xlsx())
    out = io.BytesIO()
    with zipfile.ZipFile(buf) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr("xl/vbaProject.bin", b"\x00" * 10)
    r = await upload(auth_client, "macro.xlsx", out.getvalue())
    assert r.status_code == 400 and r.json()["error"]["code"] == "macro_enabled"


async def test_oversize_rejected(auth_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    r = await upload(auth_client, "big.csv", b"a,b\n" + b"1,2\n" * 300_000)
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


async def test_row_cap(auth_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_rows", 10)
    r = await upload(auth_client, "rows.csv", b"a,b\n" + b"1,2\n" * 100)
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many_rows"


async def test_missing_values_and_duplicates_surface(auth_client):
    _, d = await upload_ok(auth_client, "dupes.csv", fx.NO_KEY_DUPES_CSV.encode())
    sugs = (await auth_client.get(f"/api/datasets/{d['id']}/cleaning-suggestions")).json()["items"]
    assert any(s["type"] == "duplicate_rows" for s in sugs)
    _, d2 = await upload_ok(auth_client, "sales.csv", fx.SALES_CSV.encode())
    sugs2 = (await auth_client.get(f"/api/datasets/{d2['id']}/cleaning-suggestions")).json()["items"]
    assert any(s["id"] == "missing:discount" for s in sugs2)
    report = (await auth_client.get(f"/api/datasets/{d2['id']}/cleaning-report")).json()["version"]["cleaning_report"]
    assert report["summary"]["rows_before"] - report["summary"]["rows_removed"] == report["summary"]["rows_after"]


async def test_apply_suggestion_creates_version_and_undo(auth_client):
    _, d = await upload_ok(auth_client, "dupes.csv", fx.NO_KEY_DUPES_CSV.encode())
    r = await auth_client.post(f"/api/datasets/{d['id']}/cleaning-suggestions/apply",
                               json={"selections": [{"id": "duplicates", "option": "remove"}]})
    assert r.status_code == 200, r.text
    v2 = r.json()["created_version"]
    assert v2["version_number"] == 2 and v2["kind"] == "user_cleaned" and v2["row_count"] == 2
    vs = (await auth_client.get(f"/api/datasets/{d['id']}/versions")).json()["items"]
    assert [v["version_number"] for v in vs] == [2, 1] and vs[0]["is_active"]
    v1 = vs[1]["id"]
    r = await auth_client.put(f"/api/datasets/{d['id']}/active-version", json={"version_id": v1})
    assert r.status_code == 200
    again = (await auth_client.get(f"/api/datasets/{d['id']}")).json()
    assert again["row_count"] == 3 and again["active_version"]["version_number"] == 1


async def test_invalid_suggestion_rejected(auth_client):
    _, d = await upload_ok(auth_client, "dupes.csv", fx.NO_KEY_DUPES_CSV.encode())
    r = await auth_client.post(f"/api/datasets/{d['id']}/cleaning-suggestions/apply",
                               json={"selections": [{"id": "nope", "option": "x"}]})
    assert r.status_code == 400


async def test_reclean_with_options(auth_client):
    _, d = await upload_ok(auth_client, "dates.csv", fx.AMBIGUOUS_DATES_CSV.encode())
    first = (await auth_client.get(f"/api/datasets/{d['id']}/preview")).json()["rows"][0][1]
    assert first == "2024-02-01"
    r = await auth_client.post(f"/api/datasets/{d['id']}/clean", json={"date_order": "MDY"})
    assert r.status_code == 202
    p = (await auth_client.get(f"/api/datasets/{d['id']}/preview")).json()
    assert p["version_number"] == 2 and p["rows"][0][1] == "2024-01-02"


async def test_download_cleaned_keeps_negatives(auth_client):
    _, d = await upload_ok(auth_client, "sales.csv", fx.SALES_CSV.encode())
    r = await auth_client.get(f"/api/datasets/{d['id']}/download")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    text = r.text
    assert ",-200.00," in text and ",-45.10," in text and "_source_row" not in text


async def test_list_and_search(auth_client):
    await upload_ok(auth_client, "alpha sales.csv", fx.NO_KEY_DUPES_CSV.encode())
    await upload_ok(auth_client, "beta.csv", fx.NO_KEY_DUPES_CSV.encode())
    r = (await auth_client.get("/api/datasets", params={"q": "ALPHA"})).json()
    assert [i["filename"] for i in r["items"]] == ["alpha sales.csv"]
    assert r["pagination"]["total"] == 1
    r = (await auth_client.get("/api/datasets", params={"q": ".*"})).json()  # regex characters are escaped
    assert r["pagination"]["total"] == 0


async def test_other_users_dataset_is_404(auth_client, other_client):
    _, d = await upload_ok(auth_client, "sales.csv", fx.SALES_CSV.encode())
    for path in ("", "/preview", "/versions", "/cleaning-report", "/cleaning-suggestions", "/download"):
        r = await other_client.get(f"/api/datasets/{d['id']}{path}")
        assert r.status_code == 404, path
    assert (await other_client.delete(f"/api/datasets/{d['id']}")).status_code == 404
    assert (await other_client.post(f"/api/datasets/{d['id']}/clean", json={})).status_code == 404
    assert (await other_client.get("/api/datasets")).json()["pagination"]["total"] == 0
    assert (await auth_client.get(f"/api/datasets/{d['id']}")).status_code == 200


async def test_delete_removes_files_and_records(auth_client, db):
    _, d = await upload_ok(auth_client, "sales.csv", fx.SALES_CSV.encode())
    doc = await db.datasets.find_one({})
    v = await db.dataset_versions.find_one({})
    paths = [get_storage().path(doc["raw_storage_ref"]), get_storage().path(doc["raw_grid_ref"]), get_storage().path(v["storage_ref"])]
    assert all(p.exists() for p in paths)
    r = await auth_client.delete(f"/api/datasets/{d['id']}")
    assert r.status_code == 200
    assert not any(p.exists() for p in paths)
    assert await db.datasets.count_documents({}) == 0 and await db.dataset_versions.count_documents({}) == 0


async def test_summary_counts_real_rows(auth_client):
    await upload_ok(auth_client, "sales.csv", fx.SALES_CSV.encode())
    await upload_ok(auth_client, "weather.csv", fx.WEATHER_CSV)
    s = (await auth_client.get("/api/dashboard/summary")).json()
    assert s["total_datasets"] == 2 and s["total_rows"] == 12
    assert s["important_findings"]["insights"] is None


async def test_clean_download_formats_match(auth_client):
    import json
    import zipfile

    from openpyxl import load_workbook
    _, d = await upload_ok(auth_client, "sales.csv", fx.SALES_CSV.encode())
    url = f"/api/datasets/{d['id']}/download"
    csv = await auth_client.get(url)
    rows = int(csv.headers["x-rows-exported"])
    assert csv.text.count("\n") == rows + 1

    excel_csv = await auth_client.get(url, params={"format": "csv_excel"})
    assert excel_csv.content.startswith(b"\xef\xbb\xbf") and excel_csv.content[3:] == csv.content

    data = json.loads((await auth_client.get(url, params={"format": "json"})).content)
    assert len(data) == rows
    amounts = sorted(r["Amount"] for r in data)
    assert -200.0 in amounts and 1234.5 in amounts and all(isinstance(a, float) for a in amounts)
    assert data[0]["Order Date"] == "2024-01-05" and isinstance(data[0]["Shipped"], bool)

    x = await auth_client.get(url, params={"format": "xlsx"})
    assert x.headers["content-disposition"].endswith('.xlsx"')
    wb = load_workbook(io.BytesIO(x.content), read_only=True)
    assert {"Data", "Data dictionary", "Cleaning report"} <= set(wb.sheetnames)
    assert sum(1 for _ in wb["Data"].iter_rows()) == rows + 1

    z = await auth_client.get(url, params={"format": "zip"})
    with zipfile.ZipFile(io.BytesIO(z.content)) as pack:
        names = set(pack.namelist())
        assert {"sales_clean.csv", "data_dictionary.csv", "cleaning_report.csv", "README.txt"} == names
        assert pack.read("sales_clean.csv") == csv.content
        readme = pack.read("README.txt").decode()
        assert hashlib.sha256(csv.content).hexdigest() in readme and f"Rows: {rows}" in readme


async def test_clean_download_column_selection(auth_client):
    _, d = await upload_ok(auth_client, "sales.csv", fx.SALES_CSV.encode())
    url = f"/api/datasets/{d['id']}/download"
    cols = (await auth_client.get(url.replace("/download", "/preview"))).json()["columns"]
    keep = [c["key"] for c in cols[:2]]
    r = await auth_client.get(url, params={"columns": ",".join(keep)})
    assert r.status_code == 200 and r.headers["x-columns-exported"] == "2"
    assert r.text.splitlines()[0].count(",") == 1
    assert (await auth_client.get(url, params={"columns": "nope"})).status_code == 400
    assert (await auth_client.get(url, params={"format": "pdf"})).status_code == 422

import io

from openpyxl import Workbook

from tests.conftest import H, KNOWN_CSV, metric_id, new_workspace, upload_csv, use


def test_auth_required_and_csrf(client):
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401
    W = new_workspace(client, "csrf@example.com")
    r = client.post("/api/workspaces", json={"name": "No header"})  # missing X-CM-Client
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
    client.cookies.set("cm_session", "forged-token")
    assert client.get(f"{W}").status_code == 401


def test_login_logout_and_password_rules(client):
    client.cookies.clear()
    r = client.post("/api/auth/signup", json={"full_name": "Weak", "email": "weak@example.com", "password": "short"}, headers=H)
    assert r.status_code == 422
    new_workspace(client, "login@example.com")
    assert client.post("/api/auth/logout", headers=H).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    bad = client.post("/api/auth/login", json={"email": "login@example.com", "password": "wrong-pass-123"}, headers=H)
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"email": "login@example.com", "password": "correct-horse-1"}, headers=H)
    assert ok.status_code == 200 and client.get("/api/auth/me").status_code == 200


def test_password_reset_flow(client):
    new_workspace(client, "reset@example.com")
    r = client.post("/api/auth/forgot-password", json={"email": "reset@example.com"}, headers=H).json()
    assert r["email_delivery"] == "not_configured"
    # unknown accounts get the same response (no enumeration)
    assert client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"}, headers=H).status_code == 200


def test_workspace_isolation(client):
    A = new_workspace(client, "alice@example.com")
    ds = upload_csv(client, A, KNOWN_CSV)
    a_cookies = dict(client.cookies)
    rep = client.post(f"{A}/reports", json={"title": "Private", "dataset_id": ds["id"]}, headers=H).json()["report"]
    B = new_workspace(client, "bob@example.com")
    # Bob cannot reach Alice's workspace, dataset, preview or report — via his own workspace either
    assert client.get(A).status_code == 404
    assert client.get(f"{A}/datasets/{ds['id']}").status_code == 404
    assert client.get(f"{B}/datasets/{ds['id']}").status_code == 404
    assert client.post(f"{B}/datasets/{ds['id']}/preview", json={}, headers=H).status_code == 404
    assert client.get(f"{B}/reports/{rep['id']}").status_code == 404
    assert client.get(f"{A}/reports/{rep['id']}/export?format=pdf").status_code == 404
    r = client.post(f"{B}/analysis/run", json={"plan": {"intent": "aggregate", "dataset_id": ds["id"], "measures": [{"kind": "count_rows"}]}}, headers=H)
    assert r.status_code == 404
    for k, v in a_cookies.items():
        client.cookies.set(k, v)


def test_viewer_cannot_modify(client):
    A = new_workspace(client, "owner2@example.com")
    owner_cookies = dict(client.cookies)
    new_workspace(client, "viewer@example.com")
    viewer_cookies = dict(client.cookies)
    use(client, {"cookies": owner_cookies})
    assert client.post(f"{A}/invitations", json={"email": "viewer@example.com", "role": "viewer"}, headers=H).status_code == 201
    use(client, {"cookies": viewer_cookies})
    inv = client.get("/api/auth/me").json()["invitations"][0]
    assert client.post(f"/api/invitations/{inv['id']}/accept", headers=H).status_code == 200
    assert client.get(A).status_code == 200
    r = client.post(f"{A}/datasets/upload", files={"file": ("x.csv", KNOWN_CSV.encode(), "text/csv")}, headers=H)
    assert r.status_code == 403


def test_sql_injection_attempts_are_inert(client):
    W = new_workspace(client, "sqli@example.com")
    ds = upload_csv(client, W, KNOWN_CSV)
    base = {"intent": "aggregate", "dataset_id": ds["id"], "measures": [{"kind": "count_rows"}]}
    # value injection: bound as a parameter, matches nothing
    r = client.post(f"{W}/analysis/run", json={"plan": {**base, "filters": [{"column": "region", "op": "eq", "value": "x' OR '1'='1"}]}}, headers=H)
    assert r.status_code == 200 and r.json()["run"]["result"]["kpis"][0]["value"] == 0
    # identifier injection: rejected by schema validation
    r = client.post(f"{W}/analysis/run", json={"plan": {**base, "intent": "breakdown", "group_by": ['region"; DROP TABLE data; --']}}, headers=H)
    assert r.status_code == 422
    # extra fields (e.g. raw SQL) are forbidden by the strict plan schema
    r = client.post(f"{W}/analysis/run", json={"plan": {**base, "sql": "SELECT * FROM read_csv('/etc/passwd')"}}, headers=H)
    assert r.status_code == 422
    # preview search and sort cannot inject
    r = client.post(f"{W}/datasets/{ds['id']}/preview", json={"search": "%' OR 1=1 --", "sort": "region"}, headers=H)
    assert r.status_code == 200 and r.json()["total"] == 0
    assert client.post(f"{W}/datasets/{ds['id']}/preview", json={"sort": "region; DROP"}, headers=H).status_code == 422


def test_metric_formula_cannot_execute_code(client):
    W = new_workspace(client, "formula@example.com")
    ds = upload_csv(client, W, KNOWN_CSV)
    for f in ["SUM(net_revenue); DROP TABLE data", "__import__('os').system('ls')", "SUM(read_csv('/etc/passwd'))",
              "SUM(net_revenue) + net_revenue", "SUM(region)", "SUM(unknown_col)"]:
        r = client.post(f"{W}/metrics", json={"dataset_id": ds["id"], "name": "Bad", "formula": f}, headers=H)
        assert r.status_code == 422, f
    ok = client.post(f"{W}/metrics", json={"dataset_id": ds["id"], "name": "North revenue", "formula": "SUM_IF(net_revenue, region = 'North')",
                                           "unit": "currency"}, headers=H)
    assert ok.status_code == 201


def test_unsafe_plan_requests(client):
    W = new_workspace(client, "unsafe@example.com")
    ds = upload_csv(client, W, KNOWN_CSV)
    r = client.post(f"{W}/analysis/run", json={"plan": {"intent": "rank", "dataset_id": ds["id"], "measures": [{"kind": "count_rows"}],
                                                        "group_by": ["region"], "limit": 100000}}, headers=H)
    assert r.status_code == 422
    r = client.post(f"{W}/analysis/run", json={"plan": {"intent": "aggregate", "dataset_id": ds["id"],
                                                        "measures": [{"kind": "column", "column": "region", "aggregation": "sum"}]}}, headers=H)
    assert r.status_code == 422


def test_upload_validation(client):
    W = new_workspace(client, "upload@example.com")
    bad_ext = client.post(f"{W}/datasets/upload", files={"file": ("evil.exe", b"MZ....", "application/octet-stream")}, headers=H)
    assert bad_ext.status_code == 400 and bad_ext.json()["error"]["code"] == "unsupported_format"
    fake_xlsx = client.post(f"{W}/datasets/upload", files={"file": ("fake.xlsx", b"not a zip at all", "application/vnd.ms-excel")}, headers=H)
    assert fake_xlsx.status_code == 400
    binary_csv = client.post(f"{W}/datasets/upload", files={"file": ("bin.csv", b"\x00\x01\x02" * 100, "text/csv")}, headers=H)
    assert binary_csv.status_code == 400
    empty = client.post(f"{W}/datasets/upload", files={"file": ("e.csv", b"", "text/csv")}, headers=H)
    assert empty.status_code == 400
    # Path traversal in the filename is only metadata; storage uses generated keys
    ds = upload_csv(client, W, KNOWN_CSV, name="../../../../etc/passwd.csv")
    assert ds["original_filename"].endswith("passwd.csv") and ds["status"] == "ready"
    from app.services.dataset import storage
    import pytest
    with pytest.raises(ValueError):
        storage.original_path("../../etc/passwd")


def test_oversized_upload(client, monkeypatch):
    from app.core.config import get_settings
    W = new_workspace(client, "big@example.com")
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    r = client.post(f"{W}/datasets/upload", files={"file": ("big.csv", b"a,b\n1,2\n" * 100, "text/csv")}, headers=H)
    assert r.status_code == 413


def test_macro_workbook_rejected(client):
    import zipfile
    W = new_workspace(client, "macro@example.com")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/vbaProject.bin", b"\x00")
    r = client.post(f"{W}/datasets/upload", files={"file": ("m.xlsx", buf.getvalue(), "application/octet-stream")}, headers=H)
    assert r.status_code == 400 and r.json()["error"]["code"] == "macros_not_allowed"


def test_formula_injection_in_exports(client):
    W = new_workspace(client, "inject@example.com")
    csv_text = "name,amount\n=HYPERLINK(\"http://evil\"),10\n@SUM(1+1),20\nplain,30\n"
    ds = upload_csv(client, W, csv_text)
    r = client.post(f"{W}/datasets/{ds['id']}/export", json={"format": "csv"}, headers=H)
    body = r.text
    assert "'=HYPERLINK" in body and "'@SUM" in body
    x = client.post(f"{W}/datasets/{ds['id']}/export", json={"format": "xlsx"}, headers=H)
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(x.content))
    vals = [c.value for c in wb.active["A"]]
    assert vals[1].startswith("'=")


def test_delete_dataset_removes_files(client):
    W = new_workspace(client, "delete@example.com")
    ds = upload_csv(client, W, KNOWN_CSV)
    from app.core.config import get_settings
    from app.database import SessionLocal
    from app.models import Dataset, DatasetVersion
    db = SessionLocal()
    d = db.get(Dataset, ds["id"])
    pk = db.get(DatasetVersion, d.current_version_id).parquet_key
    orig = d.original_key
    db.close()
    s = get_settings()
    assert (s.storage_dir / "parquet" / pk).exists()
    assert client.delete(f"{W}/datasets/{ds['id']}", headers=H).status_code == 200
    assert not (s.storage_dir / "parquet" / pk).exists() and not (s.storage_dir / "originals" / orig).exists()
    assert client.get(f"{W}/datasets/{ds['id']}").status_code == 404

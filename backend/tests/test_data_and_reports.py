import io

from openpyxl import Workbook

from tests.conftest import H, KNOWN_CSV, metric_id, new_workspace, upload_csv, use


def test_csv_dialects_and_types(client):
    W = new_workspace(client, "dialects@example.com")
    text = 'Date;Store;Sales Amount;Units\n03/01/2026;"Main; North";"1.234,00";5\n04/01/2026;Side;300;N/A\n05/01/2026;Side;bad;2\n'
    # semicolon delimiter, quoted delimiter inside value, missing tokens
    ds = upload_csv(client, W, text.replace("1.234,00", "1234.00"))
    cols = {c["original_name"]: c for c in client.get(f"{W}/datasets/{ds['id']}/columns").json()["columns"]}
    assert ds["import_report"]["delimiter"] == ";"
    assert cols["Date"]["dtype"] == "date"
    assert cols["Units"]["null_count"] == 1
    assert cols["Sales Amount"]["dtype"] == "string" or cols["Sales Amount"]["invalid_count"] == 1
    latin = "name,city\nJosé,Málaga\n".encode("latin-1")
    r = client.post(f"{W}/datasets/upload", files={"file": ("l.csv", latin, "text/csv")}, headers=H)
    assert r.status_code == 201 and r.json()["dataset"]["import_report"]["encoding"] in ("cp1252", "latin-1")


def test_inconsistent_records_skipped(client):
    W = new_workspace(client, "ragged@example.com")
    ds = upload_csv(client, W, "a,b\n1,2\n3,4,5,6\n7,8\n")
    assert ds["row_count"] == 2 and ds["import_report"]["skipped_lines"] >= 1
    q = client.get(f"{W}/datasets/{ds['id']}/quality").json()["quality"]
    assert any(i["type"] == "malformed_records" for i in q["issues"])


def test_xlsx_multiple_sheets(client):
    W = new_workspace(client, "excel@example.com")
    wb = Workbook()
    ws = wb.active
    ws.title = "Notes"
    ws.append(["readme"])
    ws.append(["this sheet is notes"])
    s2 = wb.create_sheet("Orders")
    s2.append(["Order", "Amount", "When"])
    import datetime
    s2.append(["A", 10.5, datetime.date(2026, 1, 1)])
    s2.append(["B", 20, datetime.date(2026, 1, 2)])
    wb.create_sheet("Empty")
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"{W}/datasets/upload", files={"file": ("book.xlsx", buf.getvalue(), "application/octet-stream")}, headers=H)
    ds = r.json()["dataset"]
    assert ds["status"] == "needs_sheet" and {s["name"] for s in ds["sheets"]} == {"Notes", "Orders", "Empty"}
    assert next(s for s in ds["sheets"] if s["name"] == "Empty")["empty"]
    r = client.post(f"{W}/datasets/{ds['id']}/import", json={"sheet": "Orders"}, headers=H)
    d = r.json()["dataset"]
    assert d["status"] == "ready" and d["row_count"] == 2
    cols = {c["original_name"]: c["dtype"] for c in client.get(f"{W}/datasets/{ds['id']}/columns").json()["columns"]}
    assert cols == {"Order": "string", "Amount": "float", "When": "date"}


def test_profile_quality_and_preview(client, demo):
    use(client, demo)
    W, ds = demo["W"], demo["ds"]["id"]
    q = client.get(f"{W}/datasets/{ds}/quality").json()["quality"]
    assert q["totals"]["duplicate_rows"] == 3 and 0 < q["score"] <= 100 and "completeness" in q["methodology"]
    p = client.post(f"{W}/datasets/{ds}/preview", json={"page": 2, "page_size": 25, "sort": "net_revenue", "direction": "desc",
                                                         "filters": [{"column": "region", "op": "eq", "value": "West"}]}, headers=H).json()
    assert len(p["rows"]) == 25 and p["page"] == 2 and p["total"] < 1464
    vals = [r[p["columns"].index("net_revenue")] for r in p["rows"]]
    assert vals == sorted(vals, reverse=True)


def test_transformations_versions_and_restore(client):
    W = new_workspace(client, "prep@example.com")
    ds = upload_csv(client, W, KNOWN_CSV + "O10,2026-03-30,E,Vase,Home,South,1,5000,2000,3000\n")
    d0 = client.get(f"{W}/datasets/{ds['id']}").json()["dataset"]
    assert d0["row_count"] == 11
    prev = client.post(f"{W}/datasets/{ds['id']}/transformations/preview", json={"kind": "remove_duplicates", "params": {}}, headers=H).json()
    assert prev["rows_after"] == 10 and prev["affected"] == 1
    assert client.get(f"{W}/datasets/{ds['id']}").json()["dataset"]["row_count"] == 11  # preview does not persist
    r = client.post(f"{W}/datasets/{ds['id']}/transformations", json={"kind": "remove_duplicates", "params": {}}, headers=H).json()
    assert r["dataset"]["row_count"] == 10 and r["dataset"]["current_version"]["version_number"] == 2
    client.post(f"{W}/datasets/{ds['id']}/transformations", json={"kind": "calculated_field",
                                                                  "params": {"name": "Margin pct", "expression": "profit / net_revenue * 100"}}, headers=H)
    cols = client.get(f"{W}/datasets/{ds['id']}/columns").json()["columns"]
    assert any(c["name"] == "margin_pct" for c in cols)
    bad = client.post(f"{W}/datasets/{ds['id']}/transformations/preview", json={"kind": "calculated_field",
                                                                                "params": {"name": "x", "expression": "open('/etc/passwd')"}}, headers=H)
    assert bad.status_code == 422
    versions = client.get(f"{W}/datasets/{ds['id']}/versions").json()["versions"]
    v1 = next(v for v in versions if v["version_number"] == 1)
    r = client.post(f"{W}/datasets/{ds['id']}/versions/{v1['id']}/restore", headers=H).json()
    assert r["dataset"]["row_count"] == 11 and r["dataset"]["current_version"]["version_number"] == 4


def test_metric_versioning_preserves_history(client):
    W = new_workspace(client, "versions@example.com")
    ds = upload_csv(client, W, KNOWN_CSV)
    m = client.post(f"{W}/metrics", json={"dataset_id": ds["id"], "name": "Revenue", "formula": "SUM(net_revenue)", "unit": "currency"},
                    headers=H).json()["metric"]
    client.post(f"{W}/metrics/{m['id']}/verify", headers=H)
    plan = {"intent": "aggregate", "dataset_id": ds["id"], "measures": [{"kind": "metric", "metric_id": m["id"]}]}
    run1 = client.post(f"{W}/analysis/run", json={"plan": plan}, headers=H).json()["run"]
    assert run1["result"]["kpis"][0]["value"] == 6700
    upd = client.patch(f"{W}/metrics/{m['id']}", json={"formula": "SUM(net_revenue) - SUM(cost)", "change_note": "net of cost"}, headers=H).json()["metric"]
    assert upd["version"] == 2 and upd["verified"] is False  # changed calculations need re-verification
    run2 = client.post(f"{W}/analysis/run", json={"plan": plan}, headers=H).json()["run"]
    assert run2["result"]["kpis"][0]["value"] == 6700 - 3050
    again = client.post(f"{W}/analysis/runs/{run1['id']}/reproduce", headers=H).json()
    assert again["identical"] is True  # the old run still reproduces with metric v1
    detail = client.get(f"{W}/metrics/{m['id']}").json()["metric"]
    assert len(detail["versions"]) == 2 and detail["usage"]["analysis_runs"] >= 2


def test_reports_pdf_csv_and_snapshots(client, demo):
    use(client, demo)
    W, ds = demo["W"], demo["ds"]["id"]
    ins = client.post(f"{W}/insights/generate", json={"dataset_id": ds}, headers=H).json()["insights"]
    assert ins and all(i["method"] for i in ins)
    cats = {i["category"] for i in ins}
    assert {"regional_performance", "unusual_records"} <= cats
    rep = client.post(f"{W}/reports", json={"title": "Exec", "dataset_id": ds, "template": "executive",
                                            "from_insight_ids": [ins[0]["id"]]}, headers=H).json()["report"]
    summary = rep["sections"][0]["snapshot"]
    assert summary["kpis"] and summary["limitations"] and summary["reporting_period"]["current"]
    nr = next(k for k in summary["kpis"] if k["metric"] == "Net Revenue")
    plan = {"intent": "aggregate", "dataset_id": ds, "measures": [{"kind": "metric", "metric_id": metric_id(client, W, "Net Revenue")}],
            "time": {"column": "order_date", "start": summary["reporting_period"]["start"], "end": summary["reporting_period"]["end"]}}
    direct = client.post(f"{W}/analysis/run", json={"plan": plan}, headers=H).json()["run"]["result"]["kpis"][0]["value"]
    assert nr["current"] == direct  # executive summary numbers come from the engine
    pdf = client.get(f"{W}/reports/{rep['id']}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and len(pdf.content) > 5000
    csv = client.get(f"{W}/reports/{rep['id']}/export?format=csv")
    assert csv.status_code == 200 and "Net Revenue" in csv.text
    secs = rep["sections"]
    order = [s["id"] for s in reversed(secs)]
    r = client.post(f"{W}/reports/{rep['id']}/order", json={"section_ids": order}, headers=H).json()["report"]
    assert [s["id"] for s in r["sections"]] == order


def test_relationship_validation_and_join(client):
    W = new_workspace(client, "joins@example.com")
    orders = upload_csv(client, W, "order_id,customer,amount\nO1,A,10\nO2,B,20\nO3,Z,5\n", "orders.csv")
    custs = upload_csv(client, W, "customer,segment\nA,Retail\nB,Wholesale\nC,Retail\n", "customers.csv")
    body = {"left_dataset_id": orders["id"], "right_dataset_id": custs["id"], "left_column": "customer", "right_column": "customer", "join_type": "left"}
    v = client.post(f"{W}/relationships/validate", json=body, headers=H).json()
    assert v["cardinality"] == "many_to_one" or v["cardinality"] == "one_to_one"
    assert v["matched_left_rows"] == 2 and v["unmatched_left_rows"] == 1 and v["unmatched_left_sample"] == ["Z"]
    rel = client.post(f"{W}/relationships", json=body, headers=H).json()["relationship"]
    ds = client.post(f"{W}/relationships/{rel['id']}/materialize", json={"name": "Orders with segment"}, headers=H).json()["dataset"]
    assert ds["row_count"] == 3 and ds["source_type"] == "join"
    cols = {c["name"] for c in client.get(f"{W}/datasets/{ds['id']}/columns").json()["columns"]}
    assert {"order_id", "customer", "amount", "segment"} <= cols
    # one-to-many joins duplicate rows and require explicit confirmation
    dup = upload_csv(client, W, "customer,note\nA,x\nA,y\n", "notes.csv")
    body2 = {**body, "right_dataset_id": dup["id"]}
    assert client.post(f"{W}/relationships/validate", json=body2, headers=H).json()["warnings"]
    rel2 = client.post(f"{W}/relationships", json=body2, headers=H).json()["relationship"]
    assert client.post(f"{W}/relationships/{rel2['id']}/materialize", json={"name": "x"}, headers=H).status_code == 422

import os
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="cmtest-")
os.environ["CM_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["CM_STORAGE_DIR"] = f"{_TMP}/storage"
os.environ["CM_ENVIRONMENT"] = "test"
os.environ["CM_AI_PROVIDER"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

H = {"X-CM-Client": "web"}

# A small dataset with hand-verifiable answers (see test_accuracy.py)
KNOWN_CSV = """order_id,order_date,customer,product,category,region,quantity,net_revenue,cost,profit
O1,2026-01-05,A,Widget,Tools,North,2,100,60,40
O2,2026-01-10,B,Gadget,Tools,South,1,50,20,30
O3,2026-01-20,A,Widget,Tools,North,1,50,30,20
O4,2026-02-03,C,Lamp,Home,North,3,300,150,150
O5,2026-02-14,B,Gadget,Tools,South,2,100,40,60
O6,2026-02-20,D,Chair,Home,East,1,400,300,100
O7,2026-03-02,A,Widget,Tools,East,4,200,120,80
O8,2026-03-15,C,Lamp,Home,South,1,100,50,50
O9,2026-03-28,E,Chair,Home,North,1,400,280,120
O10,2026-03-30,E,Vase,Home,South,1,5000,2000,3000
"""


@pytest.fixture(scope="session", autouse=True)
def _cleanup():
    yield
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def signup(client, email, name="Test User"):
    client.cookies.clear()
    r = client.post("/api/auth/signup", json={"full_name": name, "email": email, "password": "correct-horse-1"}, headers=H)
    assert r.status_code == 201, r.text
    return r


def new_workspace(client, email, currency="USD"):
    signup(client, email)
    w = client.post("/api/workspaces", json={"name": f"WS {email}", "currency": currency}, headers=H).json()["workspace"]
    return f"/api/workspaces/{w['id']}"


def upload_csv(client, W, text, name="data.csv"):
    r = client.post(f"{W}/datasets/upload", files={"file": (name, text.encode(), "text/csv")}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["dataset"]


def confirm_terms(client, W, ds_id, mapping=None):
    terms = client.get(f"{W}/datasets/{ds_id}/terms").json()["terms"]
    m = mapping or {t["key"]: t["suggested"] for t in terms}
    r = client.post(f"{W}/datasets/{ds_id}/terms", json={"mapping": m}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def metric_id(client, W, name):
    ms = client.get(f"{W}/metrics").json()["metrics"]
    return next(m["id"] for m in ms if m["name"] == name)


def run_plan(client, W, plan):
    r = client.post(f"{W}/analysis/run", json={"plan": plan}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["run"]["result"]


@pytest.fixture(scope="session")
def known(client):
    """Workspace with the known-answer dataset and confirmed metrics."""
    W = new_workspace(client, "known@example.com")
    ds = upload_csv(client, W, KNOWN_CSV, "known.csv")
    confirm_terms(client, W, ds["id"], {"net_revenue": "net_revenue", "profit": "profit", "cost": "cost", "quantity": "quantity",
                                         "order_id": "order_id", "customer_id": None, "order_date": "order_date", "gross_revenue": None})
    return {"W": W, "ds": ds, "cookies": dict(client.cookies)}


@pytest.fixture(scope="session")
def demo(client):
    W = new_workspace(client, "demo@example.com", "USD")
    ds = client.post(f"{W}/datasets/demo", headers=H).json()["dataset"]
    confirm_terms(client, W, ds["id"])
    return {"W": W, "ds": ds, "cookies": dict(client.cookies)}


def use(client, ws):
    client.cookies.clear()
    for k, v in ws["cookies"].items():
        client.cookies.set(k, v)

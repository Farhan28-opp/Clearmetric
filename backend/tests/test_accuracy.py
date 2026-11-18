"""Analytical accuracy against hand-computed answers for KNOWN_CSV (conftest.py). Values, not HTTP codes."""
import pytest

from tests.conftest import H, metric_id, run_plan, use

pytestmark = pytest.mark.usefixtures("known")


@pytest.fixture
def k(client, known):
    use(client, known)
    W, ds = known["W"], known["ds"]["id"]
    return W, ds, lambda name: {"kind": "metric", "metric_id": metric_id(client, W, name)}


def test_total_revenue(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "aggregate", "dataset_id": ds, "measures": [m("Net Revenue")]})
    assert r["kpis"][0]["value"] == pytest.approx(6700.0)
    assert r["provenance"]["records_in_scope"] == 10


def test_average_order_value(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "aggregate", "dataset_id": ds, "measures": [m("Average Order Value")]})
    assert r["kpis"][0]["value"] == pytest.approx(670.0)  # 6700 / 10 distinct orders


def test_profit_margin(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "aggregate", "dataset_id": ds, "measures": [m("Profit Margin")]})
    assert r["kpis"][0]["value"] == pytest.approx(3650 / 6700)


def test_top_products(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "rank", "dataset_id": ds, "measures": [m("Net Revenue")], "group_by": ["product"], "limit": 3})
    assert [(x["product"], x["m0"]) for x in r["rows"]] == [("Vase", 5000), ("Chair", 800), ("Lamp", 400)]
    assert r["rows"][0]["share_pct"] == pytest.approx(5000 / 6700 * 100)
    assert r["total_groups"] == 5


def test_group_by_region(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "breakdown", "dataset_id": ds, "measures": [m("Net Revenue")], "group_by": ["region"]})
    assert {x["region"]: x["m0"] for x in r["rows"]} == {"South": 5250, "North": 850, "East": 600}


def test_monthly_totals(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "trend", "dataset_id": ds, "measures": [m("Net Revenue")],
                             "time": {"column": "order_date", "grain": "month"}})
    assert [(x["period"][:7], x["m0"]) for x in r["rows"]] == [("2026-01", 200), ("2026-02", 800), ("2026-03", 5700)]
    assert r["rows"][1]["change_pct"] == pytest.approx(300.0)


def test_compare_two_date_ranges(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "compare_periods", "dataset_id": ds, "measures": [m("Total Profit")],
                             "time": {"column": "order_date"},
                             "comparison": {"mode": "custom", "current": {"start": "2026-02-01", "end": "2026-02-28"},
                                            "baseline": {"start": "2026-01-01", "end": "2026-01-31"}}})
    kp = {x["key"]: x["value"] for x in r["kpis"]}
    assert kp["current"] == 310 and kp["baseline"] == 90 and kp["change"] == 220
    assert kp["change_pct"] == pytest.approx(220 / 90 * 100)


def test_decomposition_contributions_sum_to_100(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "decompose_change", "dataset_id": ds, "measures": [m("Net Revenue")], "group_by": ["region"],
                             "time": {"column": "order_date"},
                             "comparison": {"mode": "custom", "current": {"start": "2026-03-01", "end": "2026-03-31"},
                                            "baseline": {"start": "2026-02-01", "end": "2026-02-28"}}})
    assert r["totals"]["change"] == 4900
    assert sum(x["contribution_pct"] for x in r["rows"]) == pytest.approx(100.0)
    assert r["rows"][0]["region"] == "South"  # +5000 vs +100 → South drives the increase


def test_outliers_iqr(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "outliers", "dataset_id": ds, "measures": [m("Net Revenue")],
                             "options": {"outlier_method": "iqr", "outlier_threshold": 1.5}})
    # values sorted: 50,50,100,100,100,200,300,400,400,5000 → Q1=100, Q3=375, IQR=275, upper=787.5
    assert r["bounds"]["high"] == pytest.approx(787.5)
    assert [x["v"] for x in r["rows"]] == [5000]


def test_category_contribution(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "contribution", "dataset_id": ds, "measures": [m("Net Revenue")], "group_by": ["category"]})
    shares = {x["category"]: x["share_pct"] for x in r["rows"]}
    assert shares["Home"] == pytest.approx(6200 / 6700 * 100)
    assert shares["Tools"] == pytest.approx(500 / 6700 * 100)


def test_filters_are_applied(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "aggregate", "dataset_id": ds, "measures": [m("Net Revenue")],
                             "filters": [{"column": "region", "op": "eq", "value": "north"}, {"column": "quantity", "op": "gte", "value": 2}]})
    assert r["kpis"][0]["value"] == 400  # O1 (100) + O4 (300)


def test_empty_result(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "breakdown", "dataset_id": ds, "measures": [m("Net Revenue")], "group_by": ["region"],
                             "filters": [{"column": "region", "op": "eq", "value": "Atlantis"}]})
    assert r["rows"] == [] and r.get("empty") is True


def test_division_by_zero_is_null(client, k):
    W, ds, m = k
    r = run_plan(client, W, {"intent": "aggregate", "dataset_id": ds, "measures": [m("Profit Margin")],
                             "filters": [{"column": "region", "op": "eq", "value": "Nowhere"}]})
    assert r["kpis"][0]["value"] is None


def test_metric_consistency_across_modules(client, k):
    """The same saved metric yields the same number via Explore and via the Analyst."""
    W, ds, m = k
    explore = run_plan(client, W, {"intent": "aggregate", "dataset_id": ds, "measures": [m("Total Profit")]})["kpis"][0]["value"]
    conv = client.post(f"{W}/conversations", json={"dataset_id": ds}, headers=H).json()["conversation"]
    msg = client.post(f"{W}/conversations/{conv['id']}/ask", json={"question": "What is my total profit?"}, headers=H).json()["messages"][-1]
    assert msg["run"]["result"]["kpis"][0]["value"] == explore == 3650


def test_unknown_column_rejected(client, k):
    W, ds, m = k
    r = client.post(f"{W}/analysis/run", json={"plan": {"intent": "breakdown", "dataset_id": ds, "measures": [m("Net Revenue")],
                                                        "group_by": ["salary"]}}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_plan"


def test_unsupported_operation_rejected(client, k):
    W, ds, m = k
    r = client.post(f"{W}/analysis/run", json={"plan": {"intent": "forecast", "dataset_id": ds, "measures": [m("Net Revenue")]}}, headers=H)
    assert r.status_code == 422
    r = client.post(f"{W}/analysis/run", json={"plan": {"intent": "contribution", "dataset_id": ds, "measures": [m("Profit Margin")],
                                                        "group_by": ["region"]}}, headers=H)
    assert r.status_code == 422 and "additive" in r.json()["error"]["message"]


def test_query_timeout():
    from app.core.errors import AppError
    from app.services.execution import engine as e
    import pyarrow as pa
    e._CACHE["00000000000000000000000000000000.parquet"] = pa.table({"x": list(range(3000))})
    with pytest.raises(AppError) as exc:
        e.run_sql("00000000000000000000000000000000.parquet",
                  "SELECT COUNT(*) FROM data a, data b, data c WHERE a.x + b.x + c.x = -1", timeout=0.3)
    assert exc.value.code == "query_timeout"

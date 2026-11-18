"""Natural-language evaluation suite (local deterministic interpreter) on the synthetic demo dataset.

Each case states the expected status, intent, measure, grouping and (for follow-ups) context use.
Metrics are reported per dimension; analytical correctness of executed plans is checked independently of
wording in test_accuracy.py."""
import pytest

from tests.conftest import H, use

# (question, expected): keys status/intent/measure/group_by/focus/filters/clarify_kind. measure = metric name or column:agg
CASES = [
    ("What is my total net revenue?", {"status": "answer", "intent": "aggregate", "measure": "Net Revenue"}),
    ("How many orders are present?", {"status": "answer", "intent": "aggregate", "measure": "Total Orders"}),
    ("What is the average transaction value?", {"status": "answer", "intent": "aggregate", "measure": "Average Order Value"}),
    ("What is my total profit?", {"status": "answer", "intent": "aggregate", "measure": "Total Profit"}),
    ("How many customers do we have?", {"status": "answer", "intent": "aggregate", "measure": "Customer Count"}),
    ("Which five products generated the highest net revenue?", {"status": "answer", "intent": "rank", "measure": "Net Revenue", "group_by": ["product"], "limit": 5}),
    ("Which regions generated the highest profit?", {"status": "answer", "intent": "rank", "measure": "Total Profit", "group_by": ["region"]}),
    ("Which customers purchased the most?", {"status": "answer", "intent": "rank", "measure": "Net Revenue", "group_by": ["customer_id"]}),
    ("What are the bottom 3 products by profit?", {"status": "answer", "intent": "rank", "measure": "Total Profit", "group_by": ["product"], "limit": 3, "direction": "asc"}),
    ("Compare net revenue across different regions", {"status": "answer", "intent": "compare_segments", "measure": "Net Revenue", "group_by": ["region"]}),
    ("Which category has the highest profit margin?", {"status": "answer", "intent": "rank", "measure": "Profit Margin", "group_by": ["category"]}),
    ("Show monthly net revenue", {"status": "answer", "intent": "trend", "measure": "Net Revenue", "grain": "month"}),
    ("How has profit changed over time?", {"status": "answer", "intent": "trend", "measure": "Total Profit"}),
    ("Which month performed best?", {"status": "answer", "intent": "trend", "measure": "Net Revenue"}),
    ("Show quarterly units sold", {"status": "answer", "intent": "trend", "measure": "Units Sold", "grain": "quarter"}),
    ("Compare net revenue this month with the previous month", {"status": "answer", "intent": "compare_periods", "measure": "Net Revenue"}),
    ("Compare profit year over year", {"status": "answer", "intent": "compare_periods", "measure": "Total Profit"}),
    ("How is net revenue distributed across product categories?", {"status": "answer", "intent": "distribution", "measure": "Net Revenue", "group_by": ["category"]}),
    ("Which customers contribute the most to net revenue?", {"status": "answer", "intent": "contribution", "measure": "Net Revenue", "group_by": ["customer_id"]}),
    ("Which region contributed most to the decrease in profit?", {"status": "answer", "intent": "decompose_change", "measure": "Total Profit", "group_by": ["region"]}),
    ("What drove the change in net revenue by category?", {"status": "answer", "intent": "decompose_change", "measure": "Net Revenue", "group_by": ["category"]}),
    ("Are there unusual transactions?", {"status": "answer", "intent": "outliers", "measure": "Net Revenue"}),
    ("Are there abnormal changes in daily net revenue?", {"status": "answer", "intent": "outliers", "measure": "Net Revenue", "grain": "day"}),
    ("Net revenue in the West region by product", {"status": "answer", "intent": "breakdown", "measure": "Net Revenue", "group_by": ["product"], "filters": {"region": "West"}}),
    ("Total profit for Electronics in 2025", {"status": "answer", "intent": "aggregate", "measure": "Total Profit", "filters": {"category": "Electronics"}, "time_start": "2025-01-01"}),
    # Ambiguity → clarification
    ("What is my revenue?", {"status": "clarification", "clarify_kind": "measure"}),
    ("Show monthly sales", {"status": "clarification", "clarify_kind": "measure"}),
    ("Why did profit decline?", {"status": "clarification", "clarify_kind": "dimension"}),
    # Unknown / unsupported / out of scope
    ("What is my churn rate?", {"status": "unsupported"}),
    ("How many website visits did we get?", {"status": "unsupported"}),
    ("What's the weather in Paris?", {"status": "unsupported"}),
    ("Write me a poem about spring", {"status": "unsupported"}),
    # Dataset questions
    ("What columns are present?", {"status": "answer", "describe": True}),
    ("Which important business metrics are unavailable?", {"status": "answer", "describe": True}),
    ("What can I analyse with this dataset?", {"status": "answer", "describe": True}),
]

FOLLOW_UPS = [  # (first question, follow-up, expectations for the follow-up)
    ("Which five products generated the highest net revenue?", "How much did their revenue contribute to total revenue?",
     {"intent": "contribution", "measure": "Net Revenue", "focus_n": 5}),
    ("Which regions generated the highest net revenue?", "Compare its profit margin with the second-highest region.",
     {"intent": "compare_segments", "measure": "Profit Margin", "focus_n": 2}),
    ("Show monthly net revenue", "What about West?", {"intent": "trend", "measure": "Net Revenue", "filters": {"region": "West"}}),
    ("Which three categories have the highest net revenue?", "Show monthly revenue for them", {"intent": "trend", "measure": "Net Revenue", "focus_n": 3}),
]


def _ask(client, W, cid, q):
    r = client.post(f"{W}/conversations/{cid}/ask", json={"question": q}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["messages"][-1]


def _metric_name(client, W, mid):
    return client.get(f"{W}/metrics/{mid}").json()["metric"]["name"]


def _check(client, W, msg, exp, scores):
    status = "answer" if msg["kind"] == "answer" else msg["kind"]
    ok_status = status == exp["status"]
    scores["status"].append(ok_status)
    if exp["status"] == "clarification":
        scores["clarification"].append(ok_status and msg["payload"]["clarification"]["kind"] == exp["clarify_kind"])
        return ok_status
    if exp["status"] == "unsupported":
        scores["unsupported"].append(ok_status)
        return ok_status
    if exp.get("describe"):
        return ok_status and "describe" in msg["payload"]
    if not ok_status or not msg["run"]:
        scores["intent"].append(False)
        return False
    plan = msg["run"]["plan"]
    checks = []
    checks.append(("intent", plan["intent"] == exp["intent"]))
    if "measure" in exp:
        mm = plan["measures"][0]
        name = _metric_name(client, W, mm["metric_id"]) if mm["kind"] == "metric" else f"{mm['column']}:{mm['aggregation']}"
        checks.append(("measure", name == exp["measure"]))
    if "group_by" in exp:
        checks.append(("columns", plan["group_by"] == exp["group_by"]))
    if "limit" in exp:
        checks.append(("columns", plan["limit"] == exp["limit"]))
    if "direction" in exp:
        checks.append(("intent", plan["sort"]["direction"] == exp["direction"]))
    if "grain" in exp:
        checks.append(("columns", (plan.get("time") or {}).get("grain") == exp["grain"]))
    if "filters" in exp:
        got = {f["column"]: f["value"] for f in plan["filters"]}
        checks.append(("columns", all(got.get(c) == v for c, v in exp["filters"].items())))
    if "time_start" in exp:
        checks.append(("columns", (plan.get("time") or {}).get("start") == exp["time_start"]))
    if "focus_n" in exp:
        checks.append(("context", bool(plan.get("focus")) and len(plan["focus"]["values"]) == exp["focus_n"]))
    for key, ok in checks:
        scores[key].append(ok)
    scores["plan_valid"].append(msg["run"]["status"] == "succeeded")
    return all(ok for _, ok in checks)


def test_nl_evaluation_suite(client, demo):
    use(client, demo)
    W, ds = demo["W"], demo["ds"]["id"]
    scores = {k: [] for k in ("status", "intent", "measure", "columns", "context", "clarification", "unsupported", "plan_valid")}
    failures = []
    for q, exp in CASES:
        cid = client.post(f"{W}/conversations", json={"dataset_id": ds}, headers=H).json()["conversation"]["id"]
        msg = _ask(client, W, cid, q)
        if not _check(client, W, msg, exp, scores):
            failures.append((q, msg["kind"], msg["content"][:120], (msg.get("run") or {}).get("plan")))
    for first, follow, exp in FOLLOW_UPS:
        cid = client.post(f"{W}/conversations", json={"dataset_id": ds}, headers=H).json()["conversation"]["id"]
        _ask(client, W, cid, first)
        msg = _ask(client, W, cid, follow)
        if not _check(client, W, msg, {"status": "answer", **exp}, scores):
            failures.append((follow, msg["kind"], msg["content"][:120], (msg.get("run") or {}).get("plan")))
    report = {k: f"{sum(v)}/{len(v)}" for k, v in scores.items() if v}
    print("\nNL evaluation:", report, f"| total questions: {len(CASES) + len(FOLLOW_UPS) * 2}")
    for f in failures:
        print("  FAIL:", f)
    assert len(CASES) + len(FOLLOW_UPS) >= 30
    assert not failures, failures


def test_clarification_then_answer(client, demo):
    use(client, demo)
    W, ds = demo["W"], demo["ds"]["id"]
    cid = client.post(f"{W}/conversations", json={"dataset_id": ds}, headers=H).json()["conversation"]["id"]
    msg = _ask(client, W, cid, "Which region generated the highest revenue?")
    assert msg["kind"] == "clarification"
    labels = [o["label"] for o in msg["payload"]["clarification"]["options"]]
    r = client.post(f"{W}/conversations/{cid}/clarify", json={"message_id": msg["id"], "option_index": labels.index("Net Revenue")}, headers=H)
    ans = r.json()["messages"][-1]
    assert ans["kind"] == "answer" and ans["run"]["plan"]["group_by"] == ["region"]
    # The choice is remembered for the rest of the investigation
    nxt = _ask(client, W, cid, "Show monthly revenue")
    assert nxt["kind"] == "answer" and nxt["run"]["plan"]["intent"] == "trend"


def test_saved_investigation_persists(client, demo):
    use(client, demo)
    W, ds = demo["W"], demo["ds"]["id"]
    cid = client.post(f"{W}/conversations", json={"dataset_id": ds}, headers=H).json()["conversation"]["id"]
    _ask(client, W, cid, "Which five products generated the highest net revenue?")
    client.patch(f"{W}/conversations/{cid}", json={"saved": True, "title": "Top products"}, headers=H)
    conv = client.get(f"{W}/conversations/{cid}").json()["conversation"]
    assert conv["saved"] and conv["title"] == "Top products"
    assert conv["messages"][1]["run"]["result"]["rows"][0]["product"]
    assert client.get(f"{W}/conversations?saved=true").json()["conversations"][0]["id"] == cid
    md = client.get(f"{W}/conversations/{cid}/export?format=md")
    assert md.status_code == 200 and "Top products" in md.text

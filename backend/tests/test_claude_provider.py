"""Claude provider behaviour with a mocked SDK client (no network, no key needed)."""
import json
from types import SimpleNamespace

from app.core.config import get_settings
from app.services.ai import anthropic_provider
from tests.conftest import H, metric_id, use


class FakeMessages:
    def __init__(self, payloads):
        self.payloads, self.calls = list(payloads), []

    def create(self, **kw):
        self.calls.append(kw)
        p = self.payloads.pop(0)
        if isinstance(p, Exception):
            raise p
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=p if isinstance(p, str) else json.dumps(p))])


def _plan(**over):
    base = {"status": "plan", "message": "", "clarification_options": [], "intent": "rank", "measure_kind": "metric", "metric_id": "",
            "measure_column": "", "aggregation": "sum", "group_by": ["region"], "filters": [], "time_column": "", "grain": "none",
            "start_date": "", "end_date": "", "comparison_mode": "previous_period", "focus_column": "", "focus_values": [],
            "sort_direction": "desc", "limit": 3, "expected_direction": "any", "notes": ["mock"]}
    return {**base, **over}


def _enable(client, demo, monkeypatch, fake):
    use(client, demo)
    s = get_settings()
    monkeypatch.setattr(s, "ai_provider", "anthropic")
    monkeypatch.setattr(s, "anthropic_api_key", "test-key")
    monkeypatch.setattr(anthropic_provider, "_client", lambda: SimpleNamespace(messages=fake))
    client.patch(demo["W"], json={"external_ai_enabled": True}, headers=H)


def test_claude_plan_is_validated_and_executed(client, demo, monkeypatch):
    W, ds = demo["W"], demo["ds"]["id"]
    use(client, demo)
    nr = metric_id(client, W, "Net Revenue")
    fake = FakeMessages([_plan(metric_id=nr), "Revenue is led by one region."])
    _enable(client, demo, monkeypatch, fake)
    try:
        cid = client.post(f"{W}/conversations", json={"dataset_id": ds}, headers=H).json()["conversation"]["id"]
        msg = client.post(f"{W}/conversations/{cid}/ask", json={"question": "Top regions by net revenue"}, headers=H).json()["messages"][-1]
        assert msg["kind"] == "answer" and msg["payload"]["mode"] == "anthropic"
        assert msg["run"]["interpreter"].startswith("anthropic:")
        sent = fake.calls[0]
        assert sent["output_config"]["format"]["type"] == "json_schema"
        content = json.dumps(sent["messages"])
        # schema and metadata only: no record values (order IDs, customer IDs, dimension values)
        assert "SO-1" not in content and "C10" not in content and "Air Fryer" not in content
        assert msg["payload"]["ai_explanation"] is None or isinstance(msg["payload"]["ai_explanation"], str)
    finally:
        client.patch(W, json={"external_ai_enabled": False}, headers=H)


def test_invalid_claude_plan_gets_one_correction_then_reports(client, demo, monkeypatch):
    W, ds = demo["W"], demo["ds"]["id"]
    fake = FakeMessages([_plan(measure_kind="column", measure_column="salary"), _plan(measure_kind="column", measure_column="salary")])
    _enable(client, demo, monkeypatch, fake)
    try:
        cid = client.post(f"{W}/conversations", json={"dataset_id": ds}, headers=H).json()["conversation"]["id"]
        msg = client.post(f"{W}/conversations/{cid}/ask", json={"question": "Top regions by salary"}, headers=H).json()["messages"][-1]
        assert msg["kind"] == "error" and len(fake.calls) == 2
        assert "Your previous plan was rejected" in fake.calls[1]["messages"][0]["content"]
    finally:
        client.patch(W, json={"external_ai_enabled": False}, headers=H)


def test_provider_failure_falls_back_to_local(client, demo, monkeypatch):
    W, ds = demo["W"], demo["ds"]["id"]
    fake = FakeMessages([TimeoutError("timed out"), "{not json"])
    _enable(client, demo, monkeypatch, fake)
    try:
        cid = client.post(f"{W}/conversations", json={"dataset_id": ds}, headers=H).json()["conversation"]["id"]
        msg = client.post(f"{W}/conversations/{cid}/ask", json={"question": "Which five products generated the highest net revenue?"},
                          headers=H).json()["messages"][-1]
        assert msg["kind"] == "answer" and msg["payload"]["mode"] == "local"
        assert "Claude was unavailable" in msg["payload"]["notes"][0]
    finally:
        client.patch(W, json={"external_ai_enabled": False}, headers=H)


def test_grounding_check_rejects_invented_numbers():
    data = {"rows": [{"region": "West", "m0": 78213.4}], "kpis": [{"value": 25.4}]}
    assert anthropic_provider.grounded("West leads with 78,213.40 (25.4% of total).", data)
    assert anthropic_provider.grounded("West leads with 78.2K.", data)
    assert not anthropic_provider.grounded("West leads with 91,000 in sales.", data)

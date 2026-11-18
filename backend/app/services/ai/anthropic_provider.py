"""Optional Claude provider. Used only when CM_AI_PROVIDER=anthropic, an API key is configured on the
server, AND a workspace owner/admin has enabled external AI for the workspace.

Claude receives schema/semantic metadata and the previous plan — never raw rows or dimension value
lists — and must answer with a JSON object constrained by a strict schema (structured outputs). The
object is converted to an AnalysisPlan and validated server-side like any other plan. Any provider
error, timeout or malformed response falls back to the deterministic local interpreter."""
import json
import logging
import re

from app.core.config import get_settings
from app.services.ai.context import InterpretContext, schema_summary
from app.services.ai.local_interpreter import Interpretation

log = logging.getLogger("clearmetric.ai")

INTENTS = ["aggregate", "rank", "breakdown", "contribution", "trend", "compare_periods", "compare_segments",
           "decompose_change", "distribution", "outliers", "describe_dataset"]
OPS = ["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "between", "contains", "is_null", "not_null"]

PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["plan", "clarify", "unsupported", "describe"]},
        "message": {"type": "string", "description": "Clarifying question or explanation when status is not plan; otherwise empty."},
        "clarification_options": {"type": "array", "items": {"type": "string"}},
        "intent": {"type": "string", "enum": INTENTS},
        "measure_kind": {"type": "string", "enum": ["metric", "column", "count_rows"]},
        "metric_id": {"type": "string", "description": "id of a saved metric, or empty"},
        "measure_column": {"type": "string", "description": "numeric column name when measure_kind is column, or empty"},
        "aggregation": {"type": "string", "enum": ["sum", "avg", "min", "max", "count", "count_distinct", "median"]},
        "group_by": {"type": "array", "items": {"type": "string"}},
        "filters": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                               "properties": {"column": {"type": "string"}, "op": {"type": "string", "enum": OPS},
                                                              "values": {"type": "array", "items": {"type": "string"}}},
                                               "required": ["column", "op", "values"]}},
        "time_column": {"type": "string"},
        "grain": {"type": "string", "enum": ["none", "day", "week", "month", "quarter", "year"]},
        "start_date": {"type": "string", "description": "YYYY-MM-DD or empty"},
        "end_date": {"type": "string", "description": "YYYY-MM-DD or empty (inclusive)"},
        "comparison_mode": {"type": "string", "enum": ["previous_period", "previous_year"]},
        "focus_column": {"type": "string"},
        "focus_values": {"type": "array", "items": {"type": "string"}},
        "sort_direction": {"type": "string", "enum": ["asc", "desc"]},
        "limit": {"type": "integer"},
        "expected_direction": {"type": "string", "enum": ["decrease", "increase", "any"]},
        "notes": {"type": "array", "items": {"type": "string"}, "description": "How ambiguous words were interpreted"},
    },
    "required": ["status", "message", "clarification_options", "intent", "measure_kind", "metric_id", "measure_column",
                 "aggregation", "group_by", "filters", "time_column", "grain", "start_date", "end_date", "comparison_mode",
                 "focus_column", "focus_values", "sort_direction", "limit", "expected_direction", "notes"],
}

SYSTEM = """You translate business questions into a structured analysis plan for ClearMetric. You never calculate
numbers yourself: a separate deterministic engine executes the plan.
Rules:
- Use only column names and metric ids that appear in the provided context. Prefer verified saved metrics.
- If a business term maps to more than one plausible metric (e.g. "revenue" with both gross and net revenue
  metrics and no earlier choice in the conversation), set status "clarify" and ask a short question.
- Follow-up references ("their", "its", "second-highest") refer to previous_analysis.result_order; put the
  referenced values in focus_values with focus_column = previous_analysis.result_dimension.
- Relative dates are anchored to dataset.latest_date.
- Use status "unsupported" when the dataset cannot answer the question, explaining what is missing.
- Use status "describe" for questions about what the dataset contains.
- Fill unused string fields with "" and unused arrays with []."""


class ProviderError(Exception):
    pass


def _client():
    import anthropic
    s = get_settings()
    return anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.anthropic_timeout_seconds, max_retries=1)


def _to_plan(obj: dict, ctx: InterpretContext) -> dict:
    measure: dict
    if obj["measure_kind"] == "metric" and obj["metric_id"]:
        measure = {"kind": "metric", "metric_id": obj["metric_id"]}
    elif obj["measure_kind"] == "column" and obj["measure_column"]:
        measure = {"kind": "column", "column": obj["measure_column"], "aggregation": obj["aggregation"]}
    else:
        measure = {"kind": "count_rows"}
    filters = []
    for f in obj["filters"]:
        col = ctx.cols.get(f["column"])
        if not col:
            raise ProviderError(f"unknown filter column {f['column']}")
        vals = f["values"]
        if col["dtype"] in ("integer", "float"):
            vals = [float(v) for v in vals]
        value = vals if f["op"] in ("in", "not_in", "between") else (vals[0] if vals else None)
        filters.append({"column": f["column"], "op": f["op"], "value": value})
    plan = {"intent": obj["intent"], "dataset_id": ctx.dataset.id, "measures": [measure], "group_by": obj["group_by"][:2],
            "filters": filters, "limit": max(1, min(int(obj["limit"] or 10), 500)), "visualization": "auto",
            "sort": {"by": "value", "direction": obj["sort_direction"]},
            "options": {"expected_direction": obj["expected_direction"]}}
    if obj["time_column"]:
        t = {"column": obj["time_column"]}
        if obj["grain"] != "none":
            t["grain"] = obj["grain"]
        if obj["start_date"]:
            t["start"] = obj["start_date"]
        if obj["end_date"]:
            t["end"] = obj["end_date"]
        plan["time"] = t
    if obj["intent"] in ("compare_periods", "decompose_change"):
        plan["comparison"] = {"mode": obj["comparison_mode"], "grain": obj["grain"] if obj["grain"] != "none" else "month"}
    if obj["focus_column"] and obj["focus_values"]:
        plan["focus"] = {"column": obj["focus_column"], "values": obj["focus_values"][:50]}
    return plan


def interpret(question: str, ctx: InterpretContext, correction: str | None = None) -> Interpretation:
    s = get_settings()
    content = f"Context:\n{json.dumps(schema_summary(ctx), default=str)}\n\nQuestion: {question}"
    if correction:
        content += f"\n\nYour previous plan was rejected by the validator: {correction}\nReturn a corrected plan."
    try:
        resp = _client().messages.create(
            model=s.anthropic_model, max_tokens=1500, system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": PLAN_SCHEMA}})
        text = next(b.text for b in resp.content if b.type == "text")
        obj = json.loads(text)
    except StopIteration:
        raise ProviderError("empty response")
    except json.JSONDecodeError:
        raise ProviderError("malformed JSON")
    except Exception as e:  # SDK errors: timeouts, rate limits, auth, overload
        raise ProviderError(type(e).__name__ + ": " + str(e)[:200])
    label = f"anthropic:{s.anthropic_model}"
    if obj.get("status") == "clarify":
        return Interpretation("clarify", message=obj["message"], interpreter=label, notes=obj.get("notes", []),
                              clarification={"question": obj["message"], "kind": "text",
                                             "options": [{"label": o, "rephrase": o} for o in obj.get("clarification_options", [])[:6]]})
    if obj.get("status") in ("unsupported", "describe"):
        return Interpretation(obj["status"], message=obj["message"] or "describe", interpreter=label)
    try:
        plan = _to_plan(obj, ctx)
    except (KeyError, ValueError, TypeError) as e:
        raise ProviderError(f"unusable plan: {e}")
    return Interpretation("plan", plan=plan, notes=obj.get("notes", []), interpreter=label)


EXPLAIN_SYSTEM = """You explain an analysis result to a business owner in 2-4 sentences. Use ONLY numbers that
appear in the provided result. Do not speculate about causes; say what the data shows and one sensible next
step. No markdown headings."""


def explain(question: str, result: dict) -> str | None:
    """Optional AI-written interpretation of computed values. Discarded if it contains numbers not in the result."""
    s = get_settings()
    compact = {"columns": result.get("columns"), "rows": (result.get("rows") or [])[:30], "kpis": result.get("kpis"),
               "notes": result.get("notes"), "periods": result.get("periods")}
    try:
        resp = _client().messages.create(model=s.anthropic_model, max_tokens=400, system=EXPLAIN_SYSTEM,
                                         messages=[{"role": "user", "content": f"Question: {question}\nResult: {json.dumps(compact, default=str)}"}])
        text = next(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("Claude explanation failed: %s", e)
        return None
    return text if grounded(text, compact) else None


def grounded(text: str, data: dict) -> bool:
    """Every number of 2+ significant digits in the text must match a number in the data within rounding."""
    nums = []

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            nums.append(float(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data)
    for tok in re.findall(r"-?\d[\d,]*\.?\d*", text):
        t = tok.replace(",", "")
        try:
            v = float(t)
        except ValueError:
            continue
        if abs(v) < 10 or (1900 <= v <= 2100 and "." not in t):
            continue
        scales = [1, 1e3, 1e6, 1e9]
        if not any(abs(abs(n) - abs(v) * sc) <= max(0.051 * sc, abs(n) * 0.006) for n in nums for sc in scales):
            return False
    return True

"""Conversation manager: context → interpretation → validation → deterministic execution → narration."""
import logging

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import WorkspaceCtx
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import AnalysisRun, Conversation, Dataset, Message
from app.services import activity
from app.services.ai import anthropic_provider, context as ctxmod
from app.services.ai.local_interpreter import Interpretation, LocalInterpreter
from app.services.ai.narrator import Narrator
from app.services.analytics import engine
from app.services.analytics.plan import AnalysisPlan
from app.services.dataset.service import get_dataset
from app.services.semantic.metrics import create_metric
from app.services.semantic.terms import STANDARD

log = logging.getLogger("clearmetric.analyst")


def _next_seq(db: DbSession, conv: Conversation) -> int:
    return (db.scalar(select(func.max(Message.seq)).where(Message.conversation_id == conv.id)) or 0) + 1


def add_message(db, conv, role, content, kind="text", run_id=None, payload=None) -> Message:
    m = Message(conversation_id=conv.id, seq=_next_seq(db, conv), role=role, content=content, kind=kind, run_id=run_id,
                payload=payload or {})
    db.add(m)
    db.flush()
    return m


def previous_turn(db: DbSession, conv: Conversation, ds: Dataset) -> tuple[ctxmod.PreviousTurn | None, bool]:
    msg = db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.role == "assistant",
                                          Message.kind == "answer", Message.run_id.is_not(None)).order_by(Message.seq.desc()))
    if not msg:
        return None, False
    run = db.get(AnalysisRun, msg.run_id)
    if not run or run.dataset_id != ds.id:
        return None, False
    plan, res = run.plan, run.result
    dim = (plan.get("group_by") or [None])[0] or (plan.get("focus") or {}).get("column")
    ordered = []
    if dim:
        for r in res.get("rows", []):
            v = r.get(dim)
            if v is not None and str(v) not in ordered and v != "All other":
                ordered.append(str(v))
    label = (res.get("provenance", {}).get("measures") or [{}])[0].get("label", "")
    q = db.scalar(select(Message.content).where(Message.conversation_id == conv.id, Message.role == "user", Message.seq < msg.seq)
                  .order_by(Message.seq.desc())) or ""
    used = []
    for rid in db.scalars(select(Message.run_id).where(Message.conversation_id == conv.id, Message.run_id.is_not(None))
                          .order_by(Message.seq.desc())).all():
        r = db.get(AnalysisRun, rid)
        for mm in (r.plan.get("measures") or []) if r else []:
            if mm.get("metric_id") and mm["metric_id"] not in used:
                used.append(mm["metric_id"])
    return ctxmod.PreviousTurn(q, plan, dim, ordered, label, used), run.dataset_version_id != ds.current_version_id


def _use_claude(ctx: WorkspaceCtx) -> bool:
    return get_settings().external_ai_available and ctx.workspace.external_ai_enabled


def interpret(db: DbSession, ctx: WorkspaceCtx, ds: Dataset, conv: Conversation | None, question: str,
              overrides: dict | None = None) -> tuple[Interpretation, ctxmod.InterpretContext]:
    prev, changed = previous_turn(db, conv, ds) if conv else (None, False)
    ictx = ctxmod.build(db, ds, prev)
    ictx.previous_dataset_changed = changed
    if _use_claude(ctx) and not overrides:
        try:
            return anthropic_provider.interpret(question, ictx), ictx
        except anthropic_provider.ProviderError as e:
            log.warning("Claude interpretation failed, falling back to local: %s", e)
            interp = _local(ictx, question, overrides)
            interp.notes.insert(0, f"Claude was unavailable ({str(e)[:80]}); the local interpreter answered instead.")
            return interp, ictx
    return _local(ictx, question, overrides), ictx


def _local(ictx, question, overrides) -> Interpretation:
    li = LocalInterpreter(ictx)
    if overrides:
        return _with_overrides(li, question, overrides)
    return li.interpret(question)


def _with_overrides(li: LocalInterpreter, question: str, ov: dict) -> Interpretation:
    """Re-interpret after the user answered a clarification, injecting their choice."""
    if "measure" in ov:
        orig = li._measure
        li._measure = lambda q, prev: (ov["measure"], None)  # type: ignore[method-assign]
        li._default_measure = lambda q, intent: (ov["measure"], None)  # type: ignore[method-assign]
        res = li.interpret(question)
        li._measure = orig  # type: ignore[method-assign]
        return res
    if "group_by" in ov:
        orig_dims = li._dimensions
        li._dimensions = lambda q, f: [ov["group_by"]] + [d for d in orig_dims(q, f) if d != ov["group_by"]]  # type: ignore[method-assign]
        return li.interpret(question)
    if "time_column" in ov:
        li._date_column = lambda measure: ov["time_column"]  # type: ignore[method-assign]
        return li.interpret(question)
    return li.interpret(question)


def describe(ictx: ctxmod.InterpretContext) -> tuple[str, dict]:
    cols = ictx.cols.values()
    by_role: dict[str, list[str]] = {}
    for c in cols:
        by_role.setdefault(c["semantic_type"], []).append(c["display_name"])
    have = {m.name for m in ictx.metrics}
    meanings = {c["business_meaning"] for c in cols if c["business_meaning"]}
    unavailable = []
    for name, tmpl, unit, cat, req, syn, desc in STANDARD:
        if name in have:
            continue
        missing = [r for r in req if r not in meanings and r.replace("_id", "") not in meanings]
        unavailable.append({"metric": name, "reason": ("needs " + ", ".join(m.replace("_", " ") for m in missing)) if missing
                            else "columns exist but the metric is not defined yet (confirm business terms)"})
    dr = ""
    if ictx.anchor_date:
        dc = next((c for c in cols if c["dtype"] in ("date", "datetime")), None)
        if dc and dc.get("stats", {}).get("min"):
            dr = f" from {dc['stats']['min'][:10]} to {dc['stats']['max'][:10]}"
    text = (f"“{ictx.dataset.name}” has {ictx.version.row_count:,} rows and {len(ictx.cols)} columns{dr}. "
            f"Measures: {', '.join(by_role.get('currency', []) + by_role.get('measure', [])) or 'none'}. "
            f"Dimensions: {', '.join(by_role.get('dimension', [])) or 'none'}. "
            f"Dates: {', '.join(by_role.get('date', [])) or 'none'}. Identifiers: {', '.join(by_role.get('identifier', [])) or 'none'}.")
    payload = {"answer": text,
               "observations": [f"Saved metrics: {', '.join(sorted(have)) or 'none yet'}."] +
                               ([f"Not available: {', '.join(u['metric'] + ' (' + u['reason'] + ')' for u in unavailable)}."] if unavailable else []),
               "describe": {"columns": [{"name": c["display_name"], "type": c["dtype"], "role": c["semantic_type"], "meaning": c["business_meaning"]} for c in cols],
                            "metrics": sorted(have), "unavailable": unavailable},
               "follow_ups": suggested_questions(ictx)[:3]}
    return text, payload


def suggested_questions(ictx: ctxmod.InterpretContext) -> list[str]:
    names = {m.name.lower(): m for m in ictx.metrics}
    rev = next((n for n in ("net revenue", "gross revenue") if n in names), None) or \
        next((c["display_name"].lower() for c in ictx.cols.values() if c["semantic_type"] == "currency"), None)
    dims = {c["business_meaning"] or n: c["display_name"].lower() for n, c in ictx.cols.items() if c["semantic_type"] == "dimension"}
    product, region, category = dims.get("product"), dims.get("region"), dims.get("category")
    qs = []
    if rev:
        qs.append(f"What is my total {rev}?")
        if product:
            qs.append(f"Which five {product}s generated the highest {rev}?")
        if region:
            qs.append(f"Compare monthly {rev} across all {region}s")
        if ictx.anchor_date:
            qs.append(f"Show monthly {rev}")
    if "total profit" in names and region:
        qs.append(f"Which {region} contributed most to the decrease in profit?")
    if "profit margin" in names and category:
        qs.append(f"Which {category} has the highest profit margin?")
    if category and rev:
        qs.append(f"How are sales distributed across {category} categories?".replace("category categories", "categories"))
    qs.append("Are there unusual transactions?")
    qs.append("What can I analyse with this dataset?")
    return qs[:8]


def ask(db: DbSession, ctx: WorkspaceCtx, conv: Conversation, question: str, overrides: dict | None = None,
        record_question: bool = True) -> list[Message]:
    if not conv.dataset_id:
        raise AppError(422, "no_dataset", "Select a dataset for this investigation first")
    ds = get_dataset(db, ctx.id, conv.dataset_id)
    out = []
    if record_question:
        out.append(add_message(db, conv, "user", question))
        if conv.title == "New analysis":
            conv.title = question[:80]
    interp, ictx = interpret(db, ctx, ds, conv, question, overrides)
    mode = {"mode": "anthropic" if interp.interpreter.startswith("anthropic") else "local", "interpreter": interp.interpreter}
    if interp.status == "describe":
        text, payload = describe(ictx)
        out.append(add_message(db, conv, "assistant", text, "answer", payload={**payload, **mode, "notes": interp.notes}))
    elif interp.status == "unsupported":
        out.append(add_message(db, conv, "assistant", interp.message, "unsupported",
                               payload={**mode, "suggestions": suggested_questions(ictx)[:4], "notes": interp.notes}))
    elif interp.status == "clarify":
        out.append(add_message(db, conv, "assistant", interp.message, "clarification",
                               payload={**mode, "question": question, "clarification": interp.clarification, "notes": interp.notes}))
    else:
        out.append(_execute(db, ctx, conv, ds, question, interp, ictx, mode))
    activity.record(db, ctx.id, ctx.user.id, "question_asked", f"Asked: {question[:140]}", "conversation", conv.id)
    db.flush()
    return out


def _execute(db, ctx, conv, ds, question, interp: Interpretation, ictx, mode) -> Message:
    attempts = 0
    while True:
        try:
            plan = AnalysisPlan(**interp.plan)
            run = engine.execute(db, ctx.id, ctx.user.id, plan, "analyst", question, interp.interpreter, interp.notes)
            break
        except (ValidationError, engine.PlanInvalid) as e:
            problems = e.problems if isinstance(e, engine.PlanInvalid) else [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]
            if interp.interpreter.startswith("anthropic") and attempts == 0:
                attempts += 1
                try:  # one correction round with the validator's feedback
                    interp = anthropic_provider.interpret(question, ictx, correction="; ".join(problems))
                    if interp.status == "plan":
                        continue
                except anthropic_provider.ProviderError:
                    pass
            return add_message(db, conv, "assistant", "I couldn't build a valid analysis for that question: " + "; ".join(problems),
                               "error", payload={**mode, "problems": problems, "plan": interp.plan, "notes": interp.notes,
                                                 "suggestions": suggested_questions(ictx)[:4]})
        except AppError as e:
            return add_message(db, conv, "assistant", e.message, "error", payload={**mode, "plan": interp.plan, "notes": interp.notes})
    narr = Narrator(ctx.workspace.currency).narrate(run.plan, run.result)
    ai_text = None
    if mode["mode"] == "anthropic":
        ai_text = anthropic_provider.explain(question, run.result)
    payload = {**mode, **narr, "notes": interp.notes, "ai_explanation": ai_text,
               "dataset_version_id": run.dataset_version_id, "dataset_version": run.result["provenance"]["dataset"]["version_number"]}
    activity.record(db, ctx.id, ctx.user.id, "analysis_executed", f"Ran {run.plan['intent'].replace('_', ' ')} analysis on {ds.name}",
                    "conversation", conv.id)
    return add_message(db, conv, "assistant", narr["answer"], "answer", run_id=run.id, payload=payload)


def answer_clarification(db: DbSession, ctx: WorkspaceCtx, conv: Conversation, msg: Message, option_index: int) -> list[Message]:
    clar = (msg.payload or {}).get("clarification") or {}
    opts = clar.get("options") or []
    if not (0 <= option_index < len(opts)):
        raise AppError(422, "invalid_option", "Unknown option")
    opt = opts[option_index]
    question = msg.payload.get("question", "")
    out = [add_message(db, conv, "user", f"{opt['label']}", payload={"clarification_answer": True})]
    if "create_metric" in opt:
        spec = opt["create_metric"]
        ds = get_dataset(db, ctx.id, conv.dataset_id)
        ctx.require("analyst")
        try:
            m = create_metric(db, ctx.id, ctx.user.id, dataset_id=ds.id, name=spec["name"], formula=spec["formula"], unit=spec["unit"],
                              category=spec.get("category", "General"), decimals=1, synonyms=["profit margin", "margin"], verified=True,
                              description=f"Created from the AI Analyst after you chose: {opt['label']}.")
        except AppError as e:
            if e.code != "metric_exists":
                raise
        else:
            activity.record(db, ctx.id, ctx.user.id, "metric_created", f"Created metric '{spec['name']}' = {spec['formula']} from a clarification", "metric", m.id)
        return out + ask(db, ctx, conv, question, record_question=False)
    if "rephrase" in opt:
        return out + ask(db, ctx, conv, f"{question} ({opt['rephrase']})", record_question=False)
    ov = {k: opt[k] for k in ("measure", "group_by", "time_column") if k in opt}
    return out + ask(db, ctx, conv, question, overrides=ov, record_question=False)

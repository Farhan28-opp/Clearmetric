from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import WorkspaceCtx, editor_ctx, workspace_ctx
from app.api.routes.datasets import _file_response
from app.core.errors import not_found
from app.database import get_db
from app.models import AnalysisRun, SavedVisualization
from app.services import activity
from app.services.ai import conversation as conv_svc
from app.services.ai.narrator import Narrator
from app.services.analytics import engine
from app.services.analytics.plan import AnalysisPlan
from app.services.dataset.service import get_dataset

router = APIRouter(prefix="/workspaces/{workspace_id}/analysis", tags=["analysis"])


class RunIn(BaseModel):
    plan: AnalysisPlan
    source: Literal["explore", "insight", "report", "api"] = "explore"
    question: str = Field(default="", max_length=1000)


class InterpretIn(BaseModel):
    dataset_id: str
    question: str = Field(min_length=1, max_length=1000)


class VizIn(BaseModel):
    run_id: str
    title: str = Field(min_length=1, max_length=200)
    chart_type: str = Field(max_length=20)
    note: str = Field(default="", max_length=5000)
    conversation_id: str | None = None


def _run(db, ctx, rid) -> AnalysisRun:
    r = db.get(AnalysisRun, rid)
    if not r or r.workspace_id != ctx.id:
        raise not_found("Analysis")
    return r


@router.post("/validate")
def validate(body: RunIn, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    c = engine.validate_plan(db, ctx.id, body.plan)
    return {"valid": True, "measures": [{"label": m.label, "definition": m.definition, "unit": m.unit} for m in c.measures],
            "time_column": c.time_col}


@router.post("/interpret")
def interpret(body: InterpretIn, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    """Natural language → plan without executing (Explore switches between NL and the visual builder)."""
    ds = get_dataset(db, ctx.id, body.dataset_id)
    interp, _ = conv_svc.interpret(db, ctx, ds, None, body.question)
    return {"status": interp.status, "plan": interp.plan, "notes": interp.notes, "message": interp.message,
            "clarification": interp.clarification, "interpreter": interp.interpreter}


@router.post("/run")
def run(body: RunIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    r = engine.execute(db, ctx.id, ctx.user.id, body.plan, body.source, body.question, "visual-builder" if not body.question else "")
    narr = Narrator(ctx.workspace.currency).narrate(r.plan, r.result)
    activity.record(db, ctx.id, ctx.user.id, "analysis_executed", f"Ran {r.plan['intent'].replace('_', ' ')} analysis in Explore", "analysis", r.id)
    db.commit()
    return {"run": engine.run_out(r), "narrative": narr}


@router.get("/runs/{rid}")
def get_run(rid: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    r = _run(db, ctx, rid)
    return {"run": engine.run_out(r), "narrative": Narrator(ctx.workspace.currency).narrate(r.plan, r.result)}


@router.post("/runs/{rid}/reproduce")
def reproduce(rid: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    """Re-executes the stored plan against the exact dataset version and metric versions it used."""
    r = _run(db, ctx, rid)
    from app.models import MetricVersion
    pins = {}
    for vid in r.metric_version_ids or []:
        mv = db.get(MetricVersion, vid)
        if mv:
            pins[mv.metric_id] = mv.id
    _, result = engine.compute(db, ctx.id, AnalysisPlan(**r.plan), pin_version_id=r.dataset_version_id, pin_metrics=pins)
    same = result.get("rows") == r.result.get("rows") and result.get("kpis") == r.result.get("kpis")
    return {"identical": same, "dataset_version_id": r.dataset_version_id, "rows": result.get("rows", [])[:20]}


@router.get("/runs/{rid}/export")
def export_run(rid: str, format: Literal["csv", "xlsx"] = "csv", ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    r = _run(db, ctx, rid)
    cols = r.result.get("columns", [])
    rows = [[row.get(c["key"]) for c in cols] for row in r.result.get("rows", [])]
    activity.record(db, ctx.id, ctx.user.id, "result_exported", f"Exported analysis result as {format.upper()}", "analysis", r.id)
    db.commit()
    return _file_response([c["label"] for c in cols], rows, format, f"clearmetric_{r.plan['intent']}_{r.id[:8]}.{format}")


@router.get("/visualizations")
def list_viz(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    vs = db.scalars(select(SavedVisualization).where(SavedVisualization.workspace_id == ctx.id).order_by(SavedVisualization.created_at.desc())).all()
    out = []
    for v in vs:
        r = db.get(AnalysisRun, v.run_id)
        out.append({"id": v.id, "title": v.title, "chart_type": v.chart_type, "note": v.note, "created_at": v.created_at.isoformat(),
                    "conversation_id": v.conversation_id, "run": engine.run_out(r) if r else None})
    return {"visualizations": out}


@router.post("/visualizations", status_code=201)
def save_viz(body: VizIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    _run(db, ctx, body.run_id)
    v = SavedVisualization(workspace_id=ctx.id, run_id=body.run_id, title=body.title, chart_type=body.chart_type, note=body.note,
                           conversation_id=body.conversation_id, created_by=ctx.user.id)
    db.add(v)
    activity.record(db, ctx.id, ctx.user.id, "visualization_saved", f"Saved visualization '{body.title}'", "analysis", body.run_id)
    db.commit()
    return {"id": v.id}


@router.delete("/visualizations/{vid}")
def delete_viz(vid: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    v = db.get(SavedVisualization, vid)
    if not v or v.workspace_id != ctx.id:
        raise not_found("Visualization")
    db.delete(v)
    db.commit()
    return {"ok": True}


class ComputeIn(BaseModel):
    plan: AnalysisPlan


@router.post("/compute")
def compute_preview(body: ComputeIn, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    """Computes a plan without storing a provenance record (dashboard tiles, previews). Read-only."""
    _, result = engine.compute(db, ctx.id, body.plan)
    return {"result": result, "narrative": Narrator(ctx.workspace.currency).narrate(body.plan.model_dump(mode="json"), result)}


@router.get("/overview")
def overview(dataset_id: str, period: Literal["latest_month", "last_3_months", "ytd", "all"] = "latest_month",
             ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    """Business Pulse: verified metrics for the selected period vs the preceding equal-length period."""
    from datetime import date, timedelta

    from app.models import MetricDefinition, MetricVersion
    from app.services.ai.context import anchor
    from app.services.dataset.service import column_map, get_version
    ds = get_dataset(db, ctx.id, dataset_id)
    if ds.status != "ready":
        return {"ready": False}
    version = get_version(db, ds)
    cols = column_map(version)
    metrics = [(m, db.get(MetricVersion, m.current_version_id)) for m in db.scalars(select(MetricDefinition).where(
        MetricDefinition.dataset_id == ds.id, MetricDefinition.status == "active", MetricDefinition.verified.is_(True))).all()]
    order = ["net revenue", "gross revenue", "total profit", "profit margin", "total orders", "average order value", "customer count", "units sold"]
    metrics.sort(key=lambda mv: order.index(mv[1].name.lower()) if mv[1].name.lower() in order else 99)
    date_col = next((v.default_date_column for _, v in metrics if v.default_date_column in cols), None) or \
        next((c for c, m in cols.items() if m["dtype"] in ("date", "datetime")), None)
    latest = anchor(version, cols, []) if date_col else None
    cur = base = None
    if latest and period != "all":
        if period == "latest_month":
            s = latest.replace(day=1)
            e = (s.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            be = s - timedelta(days=1)
            cur, base = (s, e), (be.replace(day=1), be)
        elif period == "last_3_months":
            e = (latest.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            m = latest.month - 2
            s = date(latest.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
            be = s - timedelta(days=1)
            m2 = be.month - 2
            cur, base = (s, e), (date(be.year + (m2 - 1) // 12, (m2 - 1) % 12 + 1, 1), be)
        else:
            cur = (date(latest.year, 1, 1), latest)
            try:
                prev_end = latest.replace(year=latest.year - 1)
            except ValueError:  # 29 Feb
                prev_end = date(latest.year - 1, 2, 28)
            base = (date(latest.year - 1, 1, 1), prev_end)
    kpis = []
    for m, v in metrics[:8]:
        ref = {"kind": "metric", "metric_id": m.id}
        if cur:
            plan = AnalysisPlan(intent="compare_periods", dataset_id=ds.id, measures=[ref], time={"column": date_col},
                                comparison={"mode": "custom", "current": {"start": cur[0], "end": cur[1]}, "baseline": {"start": base[0], "end": base[1]}})
            _, r = engine.compute(db, ctx.id, plan)
            k = {x["key"]: x["value"] for x in r["kpis"]}
            kpis.append({"metric_id": m.id, "name": v.name, "formula": v.formula, "unit": v.unit, "version": v.version,
                         "current": k["current"], "baseline": k["baseline"], "change_pct": k["change_pct"], "change": k["change"]})
        else:
            _, r = engine.compute(db, ctx.id, AnalysisPlan(intent="aggregate", dataset_id=ds.id, measures=[ref]))
            kpis.append({"metric_id": m.id, "name": v.name, "formula": v.formula, "unit": v.unit, "version": v.version,
                         "current": r["kpis"][0]["value"], "baseline": None, "change_pct": None, "change": None})
    trend = None
    primary = next(((m, v) for m, v in metrics if v.unit == "currency" and v.aggregation_type == "additive"), None)
    if primary and date_col:
        _, t = engine.compute(db, ctx.id, AnalysisPlan(intent="trend", dataset_id=ds.id, measures=[{"kind": "metric", "metric_id": primary[0].id}],
                                                       time={"column": date_col, "grain": "month"}, limit=500))
        trend = {"metric": primary[1].name, "rows": t["rows"][-18:], "notes": t["notes"]}
    from app.services.analytics.format import range_label
    return {"ready": True, "dataset": {"id": ds.id, "name": ds.name, "is_demo": ds.is_demo, "version": version.version_number,
                                       "rows": version.row_count, "quality": (version.profile or {}).get("quality", {}).get("score")},
            "period": {"key": period, "current": range_label(*cur) if cur else "All dates", "baseline": range_label(*base) if base else None,
                       "latest_date": latest.isoformat() if latest else None, "date_column": cols.get(date_col, {}).get("display_name") if date_col else None},
            "kpis": kpis, "trend": trend, "unverified_metrics": db.scalar(select(func.count()).select_from(MetricDefinition).where(
                MetricDefinition.dataset_id == ds.id, MetricDefinition.status == "active", MetricDefinition.verified.is_(False)))}

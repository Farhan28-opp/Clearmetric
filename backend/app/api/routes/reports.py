from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import WorkspaceCtx, editor_ctx, workspace_ctx
from app.api.routes.datasets import _file_response
from app.core.errors import AppError, not_found
from app.database import get_db
from app.models import AnalysisRun, Conversation, Dataset, DatasetVersion, Insight, Message, Report, ReportSection
from app.services import activity
from app.services.ai.narrator import Narrator
from app.services.analytics import engine
from app.services.analytics.format import range_label
from app.services.analytics.plan import AnalysisPlan
from app.services.dataset.service import get_dataset
from app.services.insights.detector import insight_out
from app.services.reports import pdf
from app.services.reports.summary import build_summary

router = APIRouter(prefix="/workspaces/{workspace_id}/reports", tags=["reports"])
KINDS = ("text", "kpis", "chart", "table", "insight", "summary", "recommendations")


class ReportIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=300)
    dataset_id: str | None = None
    period_start: str = Field(default="", max_length=10)
    period_end: str = Field(default="", max_length=10)
    from_conversation_id: str | None = None
    from_insight_ids: list[str] = Field(default_factory=list, max_length=30)
    template: Literal["blank", "executive"] = "blank"


class ReportPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=300)
    period_start: str | None = Field(default=None, max_length=10)
    period_end: str | None = Field(default=None, max_length=10)
    status: Literal["draft", "final"] | None = None
    dataset_id: str | None = None


class SectionIn(BaseModel):
    kind: Literal["text", "kpis", "chart", "table", "insight", "summary", "recommendations"]
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=20000)
    plan: AnalysisPlan | None = None
    run_id: str | None = None
    insight_id: str | None = None
    metric_ids: list[str] = Field(default_factory=list, max_length=8)
    position: int | None = None


class SectionPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=20000)


class OrderIn(BaseModel):
    section_ids: list[str]


def _get(db, ctx, rid) -> Report:
    r = db.get(Report, rid)
    if not r or r.workspace_id != ctx.id:
        raise not_found("Report")
    return r


def _period_label(r: Report) -> str:
    return range_label(r.period_start, r.period_end) if r.period_start and r.period_end else ""


def report_out(db, r: Report, detail=False) -> dict:
    ds = db.get(Dataset, r.dataset_id) if r.dataset_id else None
    v = db.get(DatasetVersion, ds.current_version_id) if ds and ds.current_version_id else None
    out = {"id": r.id, "title": r.title, "subtitle": r.subtitle, "dataset_id": r.dataset_id, "dataset_name": ds.name if ds else None,
           "is_demo": ds.is_demo if ds else False, "dataset_version": v.version_number if v else None,
           "period_start": r.period_start, "period_end": r.period_end, "period_label": _period_label(r), "status": r.status,
           "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(), "section_count": len(r.sections)}
    if detail:
        out["sections"] = [{"id": s.id, "position": s.position, "kind": s.kind, "title": s.title, "body": s.body, "plan": s.plan,
                            "snapshot": s.snapshot, "source_ref": s.source_ref, "created_at": s.created_at.isoformat()} for s in r.sections]
    return out


def _snapshot_from_run(run: AnalysisRun, currency: str) -> dict:
    narr = Narrator(currency).narrate(run.plan, run.result)
    return {**run.result, "narrative": narr["answer"], "observations": narr.get("observations", []), "run_id": run.id}


def _with_period(plan: dict, r: Report, ds_id: str) -> dict:
    p = dict(plan)
    if r.period_start and r.period_end and p.get("intent") not in ("compare_periods", "decompose_change"):
        if p.get("time"):
            p["time"] = {**p["time"], "start": r.period_start, "end": r.period_end}
    return p


def _make_section(db, ctx: WorkspaceCtx, r: Report, body: SectionIn) -> ReportSection:
    sec = ReportSection(report_id=r.id, kind=body.kind, title=body.title, body=body.body, position=0)
    if body.kind in ("chart", "table"):
        if body.run_id:
            run = db.get(AnalysisRun, body.run_id)
            if not run or run.workspace_id != ctx.id:
                raise not_found("Analysis")
        elif body.plan:
            run = engine.execute(db, ctx.id, ctx.user.id, body.plan, "report", body.title, "report-builder")
        else:
            raise AppError(422, "missing_plan", "A chart or table section needs an analysis")
        sec.plan, sec.snapshot, sec.source_ref = run.plan, _snapshot_from_run(run, ctx.workspace.currency), run.id
        sec.title = sec.title or run.question or run.plan["intent"].replace("_", " ").title()
    elif body.kind == "kpis":
        if not r.dataset_id:
            raise AppError(422, "no_dataset", "Select a dataset for the report first")
        plan = {"intent": "aggregate", "dataset_id": r.dataset_id, "measures": [{"kind": "metric", "metric_id": m} for m in body.metric_ids[:4]]}
        if not body.metric_ids:
            raise AppError(422, "missing_metrics", "Choose at least one metric")
        from app.models import MetricVersion
        from app.services.semantic.metrics import get_metric
        date_col = next((db.get(MetricVersion, get_metric(db, ctx.id, m).current_version_id).default_date_column for m in body.metric_ids), "")
        if r.period_start and r.period_end and date_col:
            plan["time"] = {"column": date_col, "start": r.period_start, "end": r.period_end}
        run = engine.execute(db, ctx.id, ctx.user.id, AnalysisPlan(**plan), "report", "Key metrics", "report-builder")
        sec.plan, sec.snapshot, sec.source_ref = run.plan, _snapshot_from_run(run, ctx.workspace.currency), run.id
        sec.title = sec.title or "Key metrics"
    elif body.kind == "insight":
        i = db.get(Insight, body.insight_id or "")
        if not i or i.workspace_id != ctx.id:
            raise not_found("Insight")
        sec.snapshot = insight_out(i)
        sec.source_ref = i.id
        sec.title = sec.title or i.title
    elif body.kind == "summary":
        if not r.dataset_id:
            raise AppError(422, "no_dataset", "Select a dataset for the report first")
        sec.snapshot = build_summary(db, ctx.workspace, get_dataset(db, ctx.id, r.dataset_id), r)
        sec.title = sec.title or "Executive summary"
    elif body.kind == "recommendations":
        sec.title = sec.title or "Recommendations"
    return sec


def _insert(r: Report, sec: ReportSection, position: int | None):
    secs = list(r.sections)
    pos = len(secs) if position is None else max(0, min(position, len(secs)))
    secs.insert(pos, sec)
    for i, s in enumerate(secs):
        s.position = i
    r.sections = secs


@router.get("")
def list_reports(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db), q: str | None = None):
    stmt = select(Report).where(Report.workspace_id == ctx.id)
    if q:
        stmt = stmt.where(Report.title.ilike(f"%{q[:100]}%"))
    return {"reports": [report_out(db, r) for r in db.scalars(stmt.order_by(Report.updated_at.desc())).all()]}


@router.post("", status_code=201)
def create(body: ReportIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    ds_id = body.dataset_id
    conv = None
    if body.from_conversation_id:
        conv = db.get(Conversation, body.from_conversation_id)
        if not conv or conv.workspace_id != ctx.id:
            raise not_found("Investigation")
        ds_id = ds_id or conv.dataset_id
    if ds_id:
        get_dataset(db, ctx.id, ds_id)
    r = Report(workspace_id=ctx.id, dataset_id=ds_id, title=body.title, subtitle=body.subtitle, period_start=body.period_start,
               period_end=body.period_end, created_by=ctx.user.id)
    db.add(r)
    db.flush()
    if body.template == "executive" and ds_id:
        _insert(r, _make_section(db, ctx, r, SectionIn(kind="summary")), None)
    if conv:
        for m in conv.messages:
            if m.role == "assistant" and m.run_id and (m.pinned or not any(x.pinned for x in conv.messages)):
                q = db.scalar(select(Message.content).where(Message.conversation_id == conv.id, Message.seq < m.seq, Message.role == "user")
                              .order_by(Message.seq.desc()))
                _insert(r, _make_section(db, ctx, r, SectionIn(kind="chart", run_id=m.run_id, title=q or "", body=m.note or "")), None)
        if conv.findings:
            _insert(r, ReportSection(report_id=r.id, kind="text", title="Findings", body="\n".join(f"- {f}" for f in conv.findings), position=0), None)
    for iid in body.from_insight_ids:
        _insert(r, _make_section(db, ctx, r, SectionIn(kind="insight", insight_id=iid)), None)
    activity.record(db, ctx.id, ctx.user.id, "report_created", f"Created report '{r.title}'", "report", r.id)
    db.commit()
    return {"report": report_out(db, r, detail=True)}


@router.get("/{rid}")
def get(rid: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    return {"report": report_out(db, _get(db, ctx, rid), detail=True)}


@router.patch("/{rid}")
def update(rid: str, body: ReportPatch, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    r = _get(db, ctx, rid)
    data = body.model_dump(exclude_unset=True)
    if data.get("dataset_id"):
        get_dataset(db, ctx.id, data["dataset_id"])
    for k, v in data.items():
        setattr(r, k, v)
    db.commit()
    return {"report": report_out(db, r, detail=True)}


@router.delete("/{rid}")
def delete(rid: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    r = _get(db, ctx, rid)
    title = r.title
    db.delete(r)
    activity.record(db, ctx.id, ctx.user.id, "report_deleted", f"Deleted report '{title}'", "report", rid)
    db.commit()
    return {"ok": True}


@router.post("/{rid}/duplicate", status_code=201)
def duplicate(rid: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    r = _get(db, ctx, rid)
    new = Report(workspace_id=ctx.id, dataset_id=r.dataset_id, title=f"{r.title} (copy)", subtitle=r.subtitle,
                 period_start=r.period_start, period_end=r.period_end, created_by=ctx.user.id)
    new.sections = [ReportSection(kind=s.kind, title=s.title, body=s.body, plan=s.plan, snapshot=s.snapshot, source_ref=s.source_ref,
                                  position=s.position) for s in r.sections]
    db.add(new)
    db.commit()
    return {"report": report_out(db, new)}


@router.post("/{rid}/sections", status_code=201)
def add_section(rid: str, body: SectionIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    r = _get(db, ctx, rid)
    _insert(r, _make_section(db, ctx, r, body), body.position)
    db.commit()
    return {"report": report_out(db, r, detail=True)}


@router.patch("/{rid}/sections/{sid}")
def update_section(rid: str, sid: str, body: SectionPatch, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    r = _get(db, ctx, rid)
    s = next((x for x in r.sections if x.id == sid), None)
    if not s:
        raise not_found("Section")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    return {"report": report_out(db, r, detail=True)}


@router.delete("/{rid}/sections/{sid}")
def delete_section(rid: str, sid: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    r = _get(db, ctx, rid)
    r.sections = [s for s in r.sections if s.id != sid]
    for i, s in enumerate(r.sections):
        s.position = i
    db.commit()
    return {"report": report_out(db, r, detail=True)}


@router.post("/{rid}/order")
def reorder(rid: str, body: OrderIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    r = _get(db, ctx, rid)
    by_id = {s.id: s for s in r.sections}
    if set(body.section_ids) != set(by_id):
        raise AppError(422, "invalid_order", "The order must list every section exactly once")
    for i, sid in enumerate(body.section_ids):
        by_id[sid].position = i
    db.commit()
    db.refresh(r)
    return {"report": report_out(db, r, detail=True)}


@router.post("/{rid}/sections/{sid}/refresh")
def refresh_section(rid: str, sid: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    """Explicitly recompute a section with current data and metric definitions (snapshots never change silently)."""
    r = _get(db, ctx, rid)
    s = next((x for x in r.sections if x.id == sid), None)
    if not s:
        raise not_found("Section")
    if s.kind == "summary":
        s.snapshot = build_summary(db, ctx.workspace, get_dataset(db, ctx.id, r.dataset_id), r)
    elif s.plan:
        run = engine.execute(db, ctx.id, ctx.user.id, AnalysisPlan(**_with_period(s.plan, r, r.dataset_id)), "report", s.title, "report-builder")
        s.plan, s.snapshot, s.source_ref = run.plan, _snapshot_from_run(run, ctx.workspace.currency), run.id
    elif s.kind == "insight":
        i = db.get(Insight, s.source_ref)
        if i:
            s.snapshot = insight_out(i)
    db.commit()
    return {"report": report_out(db, r, detail=True)}


@router.get("/{rid}/export")
def export(rid: str, format: Literal["pdf", "csv", "xlsx"] = "pdf", ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    r = _get(db, ctx, rid)
    data = report_out(db, r, detail=True)
    safe = "".join(ch for ch in r.title[:60] if ch.isalnum() or ch in " -_").strip().replace(" ", "_") or "report"
    activity.record(db, ctx.id, ctx.user.id, "report_exported", f"Exported report '{r.title}' as {format.upper()}", "report", r.id)
    db.commit()
    if format == "pdf":
        content = pdf.render(data, {"name": ctx.workspace.name, "currency": ctx.workspace.currency})
        return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'})
    headers, rows = ["Section", "Item", "Value", "Detail"], []
    for s in data["sections"]:
        snap = s["snapshot"] or {}
        if s["kind"] == "summary":
            for k in snap.get("kpis", []):
                rows.append([s["title"], k["metric"], k["current"], f"baseline {k['baseline']}; change {k['change_pct']}%"])
        for k in snap.get("kpis", []) if s["kind"] != "summary" else []:
            rows.append([s["title"], k.get("label"), k.get("value"), k.get("text", "")])
        cols = snap.get("columns") or []
        for row in snap.get("rows", []) if s["kind"] in ("chart", "table") else []:
            rows.append([s["title"], str(row.get(cols[0]["key"])) if cols else "", row.get(cols[1]["key"]) if len(cols) > 1 else None,
                         "; ".join(f"{c['label']}={row.get(c['key'])}" for c in cols[2:])])
    return _file_response(headers, rows, format, f"{safe}.{format}")

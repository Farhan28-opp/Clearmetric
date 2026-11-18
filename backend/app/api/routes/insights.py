from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import WorkspaceCtx, editor_ctx, workspace_ctx
from app.core.errors import not_found
from app.database import get_db
from app.models import Insight
from app.services import activity
from app.services.analytics import engine
from app.services.analytics.plan import AnalysisPlan
from app.services.dataset.service import get_dataset
from app.services.insights.detector import CATEGORIES, generate, insight_out

router = APIRouter(prefix="/workspaces/{workspace_id}/insights", tags=["insights"])


class GenerateIn(BaseModel):
    dataset_id: str


class InsightPatch(BaseModel):
    status: Literal["new", "saved", "dismissed"] | None = None
    note: str | None = Field(default=None, max_length=5000)


def _get(db, ctx, iid) -> Insight:
    i = db.get(Insight, iid)
    if not i or i.workspace_id != ctx.id:
        raise not_found("Insight")
    return i


@router.get("")
def list_insights(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db), dataset_id: str | None = None,
                  category: str | None = None, status: str | None = None, severity: str | None = None):
    stmt = select(Insight).where(Insight.workspace_id == ctx.id, Insight.is_current.is_(True))
    if dataset_id:
        stmt = stmt.where(Insight.dataset_id == dataset_id)
    if category:
        stmt = stmt.where(Insight.category == category)
    if severity:
        stmt = stmt.where(Insight.severity == severity)
    if status == "active":
        stmt = stmt.where(Insight.status != "dismissed")
    elif status:
        stmt = stmt.where(Insight.status == status)
    items = sorted(db.scalars(stmt).all(), key=lambda i: -i.score)
    return {"insights": [insight_out(i) for i in items], "categories": CATEGORIES}


@router.post("/generate")
def run_generation(body: GenerateIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    ds = get_dataset(db, ctx.id, body.dataset_id)
    found = generate(db, ctx.workspace, ds)
    activity.record(db, ctx.id, ctx.user.id, "insights_generated", f"Scanned '{ds.name}' and found {len(found)} insights", "dataset", ds.id)
    db.commit()
    return {"insights": [insight_out(i) for i in sorted(found, key=lambda i: -i.score)]}


@router.get("/{iid}")
def get_insight(iid: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    return {"insight": insight_out(_get(db, ctx, iid))}


@router.patch("/{iid}")
def update(iid: str, body: InsightPatch, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    i = _get(db, ctx, iid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(i, k, v)
    if body.status == "saved":
        activity.record(db, ctx.id, ctx.user.id, "insight_saved", f"Saved insight: {i.title}", "insight", i.id)
    db.commit()
    return {"insight": insight_out(i)}


@router.post("/{iid}/evidence")
def evidence(iid: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    """Re-runs the insight's supporting calculation through the validated engine and records provenance."""
    i = _get(db, ctx, iid)
    if not i.evidence_plan:
        return {"run": None, "calculations": i.calculations}
    run = engine.execute(db, ctx.id, ctx.user.id, AnalysisPlan(**i.evidence_plan), "insight", i.title, "insight-detector")
    db.commit()
    return {"run": engine.run_out(run), "calculations": i.calculations}

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import WorkspaceCtx, editor_ctx, workspace_ctx
from app.database import get_db
from app.models import MetricDefinition, MetricVersion
from app.services import activity
from app.services.semantic import metrics as svc

router = APIRouter(prefix="/workspaces/{workspace_id}/metrics", tags=["metrics"])


class MetricIn(BaseModel):
    dataset_id: str
    name: str = Field(min_length=1, max_length=120)
    formula: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="General", max_length=40)
    unit: Literal["currency", "count", "percent", "number"] = "number"
    decimals: int = Field(default=2, ge=0, le=6)
    default_date_column: str = ""
    dimensions: list[str] = Field(default_factory=list, max_length=50)
    synonyms: list[str] = Field(default_factory=list, max_length=20)


class MetricPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    formula: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=40)
    unit: Literal["currency", "count", "percent", "number"] | None = None
    decimals: int | None = Field(default=None, ge=0, le=6)
    default_date_column: str | None = None
    dimensions: list[str] | None = None
    synonyms: list[str] | None = None
    change_note: str = Field(default="", max_length=500)


class FormulaCheck(BaseModel):
    dataset_id: str
    formula: str = Field(max_length=1000)


@router.get("")
def list_metrics(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db), q: str | None = None,
                 category: str | None = None, dataset_id: str | None = None, status: str = "active", verified: bool | None = None):
    stmt = select(MetricDefinition).where(MetricDefinition.workspace_id == ctx.id)
    if status != "all":
        stmt = stmt.where(MetricDefinition.status == status)
    if category:
        stmt = stmt.where(MetricDefinition.category == category)
    if dataset_id:
        stmt = stmt.where(MetricDefinition.dataset_id == dataset_id)
    if verified is not None:
        stmt = stmt.where(MetricDefinition.verified.is_(verified))
    items = [svc.metric_out(db, m) for m in db.scalars(stmt.order_by(MetricDefinition.category, MetricDefinition.created_at)).all()]
    if q:
        ql = q.lower()
        items = [m for m in items if ql in m["name"].lower() or ql in m["description"].lower() or any(ql in s for s in m["synonyms"])]
    cats = sorted({m.category for m in db.scalars(select(MetricDefinition).where(MetricDefinition.workspace_id == ctx.id)).all()})
    return {"metrics": items, "categories": cats}


@router.post("/check")
def check(body: FormulaCheck, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    return svc.check_formula(db, ctx.id, body.dataset_id, body.formula)


@router.post("", status_code=201)
def create(body: MetricIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    m = svc.create_metric(db, ctx.id, ctx.user.id, **body.model_dump())
    activity.record(db, ctx.id, ctx.user.id, "metric_created", f"Created metric '{body.name}' = {body.formula}", "metric", m.id)
    db.commit()
    return {"metric": svc.metric_out(db, m, detail=True)}


@router.get("/{metric_id}")
def get(metric_id: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    return {"metric": svc.metric_out(db, svc.get_metric(db, ctx.id, metric_id), detail=True)}


@router.patch("/{metric_id}")
def update(metric_id: str, body: MetricPatch, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    m = svc.get_metric(db, ctx.id, metric_id)
    v = svc.update_metric(db, m, ctx.user.id, **body.model_dump(exclude_unset=True))
    activity.record(db, ctx.id, ctx.user.id, "metric_updated", f"Updated metric '{v.name}' to version {v.version}"
                    + (" (verification reset: formula changed)" if not m.verified and body.formula else ""), "metric", m.id)
    db.commit()
    return {"metric": svc.metric_out(db, m, detail=True)}


@router.post("/{metric_id}/verify")
def verify(metric_id: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    m = svc.get_metric(db, ctx.id, metric_id)
    svc.compile_for_dataset(db, m)  # only valid definitions can be verified
    m.verified, m.verified_by, m.verified_at = True, ctx.user.id, datetime.now(timezone.utc)
    v = db.get(MetricVersion, m.current_version_id)
    activity.record(db, ctx.id, ctx.user.id, "metric_verified", f"Verified metric '{v.name}' (v{v.version})", "metric", m.id)
    db.commit()
    return {"metric": svc.metric_out(db, m, detail=True)}


@router.post("/{metric_id}/unverify")
def unverify(metric_id: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    m = svc.get_metric(db, ctx.id, metric_id)
    m.verified, m.verified_by, m.verified_at = False, None, None
    db.commit()
    return {"metric": svc.metric_out(db, m, detail=True)}


@router.post("/{metric_id}/duplicate", status_code=201)
def duplicate(metric_id: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    m = svc.get_metric(db, ctx.id, metric_id)
    v = db.get(MetricVersion, m.current_version_id)
    base, n = f"{v.name} (copy)", 2
    name = base
    while db.scalar(select(MetricDefinition).where(MetricDefinition.workspace_id == ctx.id, MetricDefinition.dataset_id == m.dataset_id,
                                                   MetricDefinition.key == svc.slugify(name), MetricDefinition.status == "active")):
        name, n = f"{v.name} (copy {n})", n + 1
    new = svc.create_metric(db, ctx.id, ctx.user.id, dataset_id=m.dataset_id, name=name, formula=v.formula,
                            description=v.description, category=m.category, unit=v.unit, decimals=v.decimals,
                            default_date_column=v.default_date_column, dimensions=v.dimensions, synonyms=[])
    activity.record(db, ctx.id, ctx.user.id, "metric_created", f"Duplicated metric '{v.name}' as '{name}'", "metric", new.id)
    db.commit()
    return {"metric": svc.metric_out(db, new, detail=True)}


@router.post("/{metric_id}/archive")
def archive(metric_id: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    m = svc.get_metric(db, ctx.id, metric_id)
    m.status = "archived" if m.status == "active" else "active"
    v = db.get(MetricVersion, m.current_version_id)
    activity.record(db, ctx.id, ctx.user.id, "metric_archived", f"{'Archived' if m.status == 'archived' else 'Restored'} metric '{v.name}'", "metric", m.id)
    db.commit()
    return {"metric": svc.metric_out(db, m, detail=True)}

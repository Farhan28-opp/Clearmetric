from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import WorkspaceCtx, admin_ctx, current_user, workspace_ctx
from app.core.config import get_settings
from app.core.errors import AppError, bad_request, forbidden, not_found
from app.core.security import verify_password
from app.database import get_db
from app.models import (ActivityEvent, Conversation, Dataset, DatasetVersion, Insight, MetricDefinition, MetricVersion,
                        Report, User, Workspace, WorkspaceInvitation, WorkspaceMembership)
from app.services import activity
from app.services.dataset import storage

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
CURRENCIES = ["USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "SGD", "AED", "ZAR"]


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    industry: str = Field(default="", max_length=80)
    business_type: str = Field(default="", max_length=80)
    currency: Literal["USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "SGD", "AED", "ZAR"] = "USD"
    timezone: str = Field(default="UTC", max_length=64)
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    industry: str | None = Field(default=None, max_length=80)
    business_type: str | None = Field(default=None, max_length=80)
    currency: Literal["USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "SGD", "AED", "ZAR"] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    date_format: Literal["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY", "DD MMM YYYY"] | None = None
    external_ai_enabled: bool | None = None
    insight_settings: dict | None = None


class OnboardingIn(BaseModel):
    step: int = Field(ge=1, le=6)
    completed: bool = False
    dataset_id: str | None = None


class InviteIn(BaseModel):
    email: EmailStr
    role: Literal["admin", "analyst", "viewer"] = "analyst"


class RoleIn(BaseModel):
    role: Literal["admin", "analyst", "viewer"]


class DeleteAccountIn(BaseModel):
    password: str


def ws_out(w: Workspace, role: str) -> dict:
    s = get_settings()
    return {"id": w.id, "name": w.name, "industry": w.industry, "business_type": w.business_type, "currency": w.currency,
            "timezone": w.timezone, "fiscal_year_start_month": w.fiscal_year_start_month, "date_format": w.date_format,
            "external_ai_enabled": w.external_ai_enabled, "insight_settings": w.insight_settings or {},
            "onboarding": w.onboarding or {}, "role": role, "created_at": w.created_at.isoformat(),
            "ai": {"provider_configured": s.external_ai_available, "provider": "anthropic" if s.external_ai_available else "local",
                   "model": s.anthropic_model if s.external_ai_available else None,
                   "active_mode": "anthropic" if (s.external_ai_available and w.external_ai_enabled) else "local"}}


@router.post("", status_code=201)
def create_workspace(body: WorkspaceIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    w = Workspace(**body.model_dump(), created_by=user.id, onboarding={"step": 2, "completed": False},
                  insight_settings={"change_threshold_pct": 10, "concentration_threshold_pct": 40, "outlier_iqr_k": 3.0})
    db.add(w)
    db.flush()
    db.add(WorkspaceMembership(workspace_id=w.id, user_id=user.id, role="owner"))
    user.last_workspace_id = w.id
    activity.record(db, w.id, user.id, "workspace_created", f"Created workspace '{w.name}'", "workspace", w.id)
    db.commit()
    return {"workspace": ws_out(w, "owner")}


@router.get("/{workspace_id}")
def get_workspace(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ctx.user.last_workspace_id = ctx.id
    db.commit()
    return {"workspace": ws_out(ctx.workspace, ctx.role)}


@router.patch("/{workspace_id}")
def update_workspace(body: WorkspacePatch, ctx: WorkspaceCtx = Depends(admin_ctx), db: DbSession = Depends(get_db)):
    w = ctx.workspace
    changes = body.model_dump(exclude_unset=True)
    if "insight_settings" in changes:
        allowed = {"change_threshold_pct": (1, 100), "concentration_threshold_pct": (10, 95), "outlier_iqr_k": (1.0, 6.0)}
        clean = dict(w.insight_settings or {})
        for k, v in (changes.pop("insight_settings") or {}).items():
            if k in allowed:
                lo, hi = allowed[k]
                clean[k] = min(max(float(v), lo), hi)
        w.insight_settings = clean
    for k, v in changes.items():
        setattr(w, k, v)
    activity.record(db, ctx.id, ctx.user.id, "workspace_updated", f"Updated workspace settings ({', '.join(body.model_dump(exclude_unset=True))})", "workspace", w.id)
    db.commit()
    return {"workspace": ws_out(w, ctx.role)}


@router.post("/{workspace_id}/onboarding")
def onboarding(body: OnboardingIn, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    w = ctx.workspace
    w.onboarding = {**(w.onboarding or {}), "step": body.step, "completed": body.completed,
                    **({"dataset_id": body.dataset_id} if body.dataset_id else {})}
    db.commit()
    return {"onboarding": w.onboarding}


@router.delete("/{workspace_id}")
def delete_workspace(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    if ctx.role != "owner":
        raise forbidden("Only the owner can delete a workspace")
    _delete_workspace_files(db, ctx.id)
    db.delete(ctx.workspace)
    db.commit()
    return {"ok": True}


def _delete_workspace_files(db: DbSession, workspace_id: str) -> None:
    for ds in db.scalars(select(Dataset).where(Dataset.workspace_id == workspace_id)).all():
        for v in db.scalars(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id)).all():
            storage.delete_quietly("parquet", v.parquet_key)
        if ds.original_key:
            storage.delete_quietly("originals", ds.original_key)


# ----------------------------------------------------------------------------- members
@router.get("/{workspace_id}/members")
def members(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ms = db.scalars(select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == ctx.id)).all()
    inv = db.scalars(select(WorkspaceInvitation).where(WorkspaceInvitation.workspace_id == ctx.id, WorkspaceInvitation.status == "pending")).all()
    return {"members": [{"id": m.id, "user_id": m.user_id, "name": m.user.full_name, "email": m.user.email, "role": m.role,
                         "joined_at": m.created_at.isoformat()} for m in ms],
            "invitations": [{"id": i.id, "email": i.email, "role": i.role, "created_at": i.created_at.isoformat()} for i in inv]}


@router.post("/{workspace_id}/invitations", status_code=201)
def invite(body: InviteIn, ctx: WorkspaceCtx = Depends(admin_ctx), db: DbSession = Depends(get_db)):
    email = body.email.lower()
    existing_user = db.scalar(select(User).where(User.email == email))
    if existing_user and db.scalar(select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == ctx.id,
                                                                      WorkspaceMembership.user_id == existing_user.id)):
        raise AppError(409, "already_member", "This person is already a member")
    if db.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.workspace_id == ctx.id, WorkspaceInvitation.email == email,
                                                   WorkspaceInvitation.status == "pending")):
        raise AppError(409, "already_invited", "An invitation is already pending for this email")
    inv = WorkspaceInvitation(workspace_id=ctx.id, email=email, role=body.role, invited_by=ctx.user.id)
    db.add(inv)
    activity.record(db, ctx.id, ctx.user.id, "member_invited", f"Invited {email} as {body.role}", "workspace", ctx.id)
    db.commit()
    return {"invitation": {"id": inv.id, "email": email, "role": body.role},
            "delivery": "Email delivery is not configured. The invitee sees this invitation after signing in with this email address."}


@router.delete("/{workspace_id}/invitations/{inv_id}")
def revoke_invite(inv_id: str, ctx: WorkspaceCtx = Depends(admin_ctx), db: DbSession = Depends(get_db)):
    inv = db.get(WorkspaceInvitation, inv_id)
    if not inv or inv.workspace_id != ctx.id:
        raise not_found("Invitation")
    inv.status = "revoked"
    db.commit()
    return {"ok": True}


@router.patch("/{workspace_id}/members/{member_id}")
def change_role(member_id: str, body: RoleIn, ctx: WorkspaceCtx = Depends(admin_ctx), db: DbSession = Depends(get_db)):
    m = db.get(WorkspaceMembership, member_id)
    if not m or m.workspace_id != ctx.id:
        raise not_found("Member")
    if m.role == "owner":
        raise forbidden("The owner's role cannot be changed")
    if body.role == "admin" and ctx.role != "owner":
        raise forbidden("Only the owner can grant admin")
    m.role = body.role
    activity.record(db, ctx.id, ctx.user.id, "member_role_changed", f"Changed {m.user.email} to {body.role}", "workspace", ctx.id)
    db.commit()
    return {"ok": True}


@router.delete("/{workspace_id}/members/{member_id}")
def remove_member(member_id: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    m = db.get(WorkspaceMembership, member_id)
    if not m or m.workspace_id != ctx.id:
        raise not_found("Member")
    if m.role == "owner":
        raise forbidden("The owner cannot be removed")
    if m.user_id != ctx.user.id:
        ctx.require("admin")
    db.delete(m)
    db.commit()
    return {"ok": True}


invite_router = APIRouter(prefix="/invitations", tags=["workspaces"])


@invite_router.post("/{inv_id}/accept")
def accept(inv_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    inv = db.get(WorkspaceInvitation, inv_id)
    if not inv or inv.status != "pending" or inv.email != user.email:
        raise not_found("Invitation")
    db.add(WorkspaceMembership(workspace_id=inv.workspace_id, user_id=user.id, role=inv.role))
    inv.status = "accepted"
    activity.record(db, inv.workspace_id, user.id, "member_joined", f"{user.full_name} joined as {inv.role}", "workspace", inv.workspace_id)
    db.commit()
    return {"workspace_id": inv.workspace_id}


@invite_router.post("/{inv_id}/decline")
def decline(inv_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    inv = db.get(WorkspaceInvitation, inv_id)
    if not inv or inv.status != "pending" or inv.email != user.email:
        raise not_found("Invitation")
    inv.status = "declined"
    db.commit()
    return {"ok": True}


account_router = APIRouter(prefix="/account", tags=["auth"])


@account_router.post("/delete")
def delete_account(body: DeleteAccountIn, response: Response, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Deletes the user, every workspace they own (with stored files) and their other memberships."""
    if not verify_password(body.password, user.password_hash):
        raise bad_request("Password is incorrect", "invalid_password")
    owned = db.scalars(select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id, WorkspaceMembership.role == "owner")).all()
    for m in owned:
        _delete_workspace_files(db, m.workspace_id)
        db.delete(db.get(Workspace, m.workspace_id))
    db.flush()
    for m in db.scalars(select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id)).all():
        db.delete(m)
    db.delete(user)
    db.commit()
    response.delete_cookie(get_settings().session_cookie, path="/")
    return {"ok": True}


# ----------------------------------------------------------------------------- activity, notifications, search
@router.get("/{workspace_id}/activity")
def activity_feed(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db), type: str | None = None,
                  resource_type: str | None = None, page: int = 1, page_size: int = 50):
    stmt = select(ActivityEvent).where(ActivityEvent.workspace_id == ctx.id)
    if type:
        stmt = stmt.where(ActivityEvent.event_type == type)
    if resource_type:
        stmt = stmt.where(ActivityEvent.resource_type == resource_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ActivityEvent.created_at.desc()).offset((page - 1) * min(page_size, 100)).limit(min(page_size, 100))).all()
    users = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({r.user_id for r in rows if r.user_id}))).all()}
    types = [t for (t,) in db.execute(select(ActivityEvent.event_type).where(ActivityEvent.workspace_id == ctx.id).distinct()).all()]
    return {"events": [{"id": e.id, "type": e.event_type, "summary": e.summary, "resource_type": e.resource_type,
                        "resource_id": e.resource_id, "user": users.get(e.user_id, "System"), "created_at": e.created_at.isoformat(),
                        "details": e.details} for e in rows], "total": total, "types": sorted(types)}


@router.get("/{workspace_id}/notifications")
def notifications(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    events = db.scalars(select(ActivityEvent).where(ActivityEvent.workspace_id == ctx.id, ActivityEvent.user_id != ctx.user.id)
                        .order_by(ActivityEvent.created_at.desc()).limit(20)).all()
    unread = [e for e in events if ctx.user.id not in (e.read_by or [])]
    new_high = db.scalar(select(func.count()).select_from(Insight).where(
        Insight.workspace_id == ctx.id, Insight.is_current.is_(True), Insight.status == "new", Insight.severity == "high"))
    items = [{"id": e.id, "kind": "activity", "summary": e.summary, "created_at": e.created_at.isoformat(), "unread": e in unread,
              "resource_type": e.resource_type, "resource_id": e.resource_id} for e in events]
    if new_high:
        items.insert(0, {"id": "insights", "kind": "insights", "summary": f"{new_high} high-importance insight{'s' if new_high > 1 else ''} to review",
                         "created_at": None, "unread": True, "resource_type": "insight", "resource_id": ""})
    return {"items": items, "unread": len(unread) + (1 if new_high else 0)}


@router.post("/{workspace_id}/notifications/read")
def mark_read(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    for e in db.scalars(select(ActivityEvent).where(ActivityEvent.workspace_id == ctx.id).order_by(ActivityEvent.created_at.desc()).limit(50)).all():
        if ctx.user.id not in (e.read_by or []):
            e.read_by = [*(e.read_by or []), ctx.user.id]
    db.commit()
    return {"ok": True}


@router.get("/{workspace_id}/search")
def search(q: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    q = q.strip()[:100]
    if len(q) < 2:
        return {"results": []}
    like = f"%{q}%"
    out = []
    for d in db.scalars(select(Dataset).where(Dataset.workspace_id == ctx.id, or_(Dataset.name.ilike(like), Dataset.original_filename.ilike(like))).limit(5)):
        out.append({"type": "dataset", "id": d.id, "title": d.name, "subtitle": d.original_filename, "href": f"/app/data/{d.id}"})
    for m in db.scalars(select(MetricDefinition).where(MetricDefinition.workspace_id == ctx.id, MetricDefinition.status == "active")):
        v = db.get(MetricVersion, m.current_version_id)
        if q.lower() in v.name.lower() or q.lower() in v.formula.lower():
            out.append({"type": "metric", "id": m.id, "title": v.name, "subtitle": v.formula, "href": f"/app/metrics?metric={m.id}"})
    for c in db.scalars(select(Conversation).where(Conversation.workspace_id == ctx.id, Conversation.title.ilike(like)).limit(5)):
        out.append({"type": "investigation", "id": c.id, "title": c.title, "subtitle": "Investigation", "href": f"/app/analyst?c={c.id}"})
    for r in db.scalars(select(Report).where(Report.workspace_id == ctx.id, Report.title.ilike(like)).limit(5)):
        out.append({"type": "report", "id": r.id, "title": r.title, "subtitle": "Report", "href": f"/app/reports/{r.id}"})
    for i in db.scalars(select(Insight).where(Insight.workspace_id == ctx.id, Insight.is_current.is_(True), Insight.title.ilike(like)).limit(5)):
        out.append({"type": "insight", "id": i.id, "title": i.title, "subtitle": i.category.replace("_", " "), "href": f"/app/insights?i={i.id}"})
    return {"results": out[:20]}

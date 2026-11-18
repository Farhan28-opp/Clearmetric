import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.errors import AppError, bad_request
from app.core.security import hash_password, hash_token, new_token, verify_password
from app.database import get_db
from app.models import (PasswordReset, Session, User, Workspace, WorkspaceInvitation, WorkspaceMembership)

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("clearmetric.auth")


def _strong(pw: str) -> str:
    if len(pw) < 10 or not any(c.isdigit() for c in pw) or not any(c.isalpha() for c in pw):
        raise ValueError("Password must be at least 10 characters and include letters and numbers")
    return pw


class SignupIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(max_length=128)
    _pw = field_validator("password")(_strong)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(max_length=128)
    _pw = field_validator("password")(_strong)


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    preferences: dict | None = None


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(max_length=128)
    _pw = field_validator("new_password")(_strong)


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "preferences": u.preferences or {},
            "last_workspace_id": u.last_workspace_id, "created_at": u.created_at.isoformat()}


def _start_session(db: DbSession, user: User, request: Request, response: Response) -> None:
    s = get_settings()
    token = new_token()
    db.add(Session(user_id=user.id, token_hash=hash_token(token),
                   expires_at=datetime.now(timezone.utc) + timedelta(days=s.session_days),
                   user_agent=(request.headers.get("user-agent") or "")[:300]))
    db.commit()
    response.set_cookie(s.session_cookie, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                        max_age=s.session_days * 86400, path="/")


@router.post("/signup", status_code=201)
def signup(body: SignupIn, request: Request, response: Response, db: DbSession = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise AppError(409, "email_taken", "An account with this email already exists")
    user = User(email=email, full_name=body.full_name.strip(), password_hash=hash_password(body.password),
                preferences={"number_format": "compact", "default_chart": "auto"})
    db.add(user)
    db.flush()
    _start_session(db, user, request, response)
    return {"user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: DbSession = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash) or not user.is_active:
        raise AppError(401, "invalid_credentials", "Email or password is incorrect")
    _start_session(db, user, request, response)
    return {"user": user_out(user)}


@router.post("/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)):
    s = get_settings()
    token = request.cookies.get(s.session_cookie)
    if token:
        db.execute(update(Session).where(Session.token_hash == hash_token(token)).values(revoked=True))
        db.commit()
    response.delete_cookie(s.session_cookie, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    rows = db.execute(select(WorkspaceMembership, Workspace).join(Workspace).where(
        WorkspaceMembership.user_id == user.id).order_by(Workspace.created_at)).all()
    invites = db.scalars(select(WorkspaceInvitation).where(
        WorkspaceInvitation.email == user.email, WorkspaceInvitation.status == "pending")).all()
    inv_out = []
    for i in invites:
        ws = db.get(Workspace, i.workspace_id)
        inv_out.append({"id": i.id, "workspace_name": ws.name if ws else "", "role": i.role})
    return {"user": user_out(user),
            "workspaces": [{"id": w.id, "name": w.name, "role": m.role, "currency": w.currency,
                            "onboarding": w.onboarding or {}} for m, w in rows],
            "invitations": inv_out}


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    user.full_name = body.full_name.strip()
    if body.preferences is not None:
        allowed = {"number_format", "default_chart", "show_sql", "reduced_motion"}
        user.preferences = {**(user.preferences or {}), **{k: v for k, v in body.preferences.items() if k in allowed}}
    db.commit()
    return {"user": user_out(user)}


@router.post("/password")
def change_password(body: PasswordChangeIn, request: Request, user: User = Depends(current_user),
                    db: DbSession = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise bad_request("Current password is incorrect", "invalid_password")
    user.password_hash = hash_password(body.new_password)
    # Revoke every other session after a password change
    db.execute(update(Session).where(Session.user_id == user.id, Session.id != request.state.session_id)
               .values(revoked=True))
    db.commit()
    return {"ok": True}


@router.get("/sessions")
def list_sessions(request: Request, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(Session).where(Session.user_id == user.id, Session.revoked.is_(False))
                      .order_by(Session.created_at.desc())).all()
    out = []
    for s in rows:
        exp = s.expires_at if s.expires_at.tzinfo else s.expires_at.replace(tzinfo=timezone.utc)
        if exp > now:
            out.append({"id": s.id, "created_at": s.created_at.isoformat(), "user_agent": s.user_agent,
                        "current": s.id == request.state.session_id})
    return {"sessions": out}


@router.post("/sessions/revoke-others")
def revoke_others(request: Request, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    n = db.execute(update(Session).where(Session.user_id == user.id, Session.id != request.state.session_id,
                                         Session.revoked.is_(False)).values(revoked=True)).rowcount
    db.commit()
    return {"revoked": n}


@router.post("/forgot-password")
def forgot_password(body: ForgotIn, db: DbSession = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    delivery = "not_configured"
    dev_link = None
    if user:
        token = new_token()
        db.add(PasswordReset(user_id=user.id, token_hash=hash_token(token),
                             expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        db.commit()
        link = f"{get_settings().frontend_url}/reset-password?token={token}"
        # No email provider is configured: the link is written to the server log for the operator.
        log.warning("Password reset requested for %s. Reset link (valid 1h): %s", user.email, link)
        if get_settings().environment == "development":
            dev_link = link
    # Same response whether or not the account exists (no account enumeration) — except the dev-only link.
    return {"ok": True, "email_delivery": delivery, "dev_reset_link": dev_link}


@router.post("/reset-password")
def reset_password(body: ResetIn, db: DbSession = Depends(get_db)):
    pr = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(body.token),
                                               PasswordReset.used.is_(False)))
    if not pr:
        raise bad_request("This reset link is invalid or has already been used", "invalid_token")
    exp = pr.expires_at if pr.expires_at.tzinfo else pr.expires_at.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        raise bad_request("This reset link has expired", "expired_token")
    user = db.get(User, pr.user_id)
    user.password_hash = hash_password(body.password)
    pr.used = True
    db.execute(update(Session).where(Session.user_id == user.id).values(revoked=True))
    db.commit()
    return {"ok": True}

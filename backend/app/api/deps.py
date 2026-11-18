"""Request dependencies: authentication, CSRF guard and workspace authorisation."""
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.core.errors import AppError, forbidden, not_found
from app.core.security import hash_token
from app.database import get_db
from app.models import ROLE_RANK, Session, User, Workspace, WorkspaceMembership

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csrf_guard(request: Request) -> None:
    """State-changing requests must carry a custom header that cross-site forms cannot set.
    Combined with SameSite=Lax session cookies this blocks CSRF."""
    if request.method not in SAFE_METHODS and request.headers.get("x-cm-client") != "web":
        raise AppError(403, "csrf", "Missing client header")


def current_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    token = request.cookies.get(get_settings().session_cookie)
    if not token:
        raise AppError(401, "unauthenticated", "Please sign in")
    sess = db.scalar(select(Session).where(Session.token_hash == hash_token(token), Session.revoked.is_(False)))
    if not sess:
        raise AppError(401, "unauthenticated", "Your session is invalid. Please sign in again")
    expires = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc) or not sess.user.is_active:
        raise AppError(401, "session_expired", "Your session has expired. Please sign in again")
    request.state.session_id = sess.id
    return sess.user


@dataclass
class WorkspaceCtx:
    workspace: Workspace
    user: User
    role: str

    @property
    def id(self) -> str:
        return self.workspace.id

    def require(self, min_role: str) -> None:
        if ROLE_RANK[self.role] < ROLE_RANK[min_role]:
            raise forbidden(f"This action requires the {min_role} role or higher")


def workspace_ctx(workspace_id: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> WorkspaceCtx:
    m = db.scalar(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user.id))
    if not m:
        # Do not reveal whether the workspace exists
        raise not_found("Workspace")
    return WorkspaceCtx(workspace=m.workspace, user=user, role=m.role)


def editor_ctx(ctx: WorkspaceCtx = Depends(workspace_ctx)) -> WorkspaceCtx:
    ctx.require("analyst")
    return ctx


def admin_ctx(ctx: WorkspaceCtx = Depends(workspace_ctx)) -> WorkspaceCtx:
    ctx.require("admin")
    return ctx

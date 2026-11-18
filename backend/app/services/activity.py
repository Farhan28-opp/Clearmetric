from sqlalchemy.orm import Session as DbSession

from app.models import ActivityEvent


def record(db: DbSession, workspace_id: str, user_id: str | None, event_type: str, summary: str,
           resource_type: str = "", resource_id: str = "", **details) -> ActivityEvent:
    ev = ActivityEvent(workspace_id=workspace_id, user_id=user_id, event_type=event_type, summary=summary,
                       resource_type=resource_type, resource_id=resource_id, details=details,
                       read_by=[user_id] if user_id else [])
    db.add(ev)
    return ev

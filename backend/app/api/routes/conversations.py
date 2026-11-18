import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import WorkspaceCtx, editor_ctx, workspace_ctx
from app.core.errors import not_found
from app.database import get_db
from app.models import AnalysisRun, Conversation, Dataset, Message
from app.services import activity
from app.services.ai import context as ctxmod, conversation as svc
from app.services.analytics.engine import run_out
from app.services.dataset.service import get_dataset

router = APIRouter(prefix="/workspaces/{workspace_id}/conversations", tags=["analyst"])


class ConversationIn(BaseModel):
    dataset_id: str
    title: str = Field(default="New analysis", max_length=200)


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    saved: bool | None = None
    notes: str | None = Field(default=None, max_length=20000)
    findings: list[str] | None = Field(default=None, max_length=50)
    dataset_id: str | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class ClarifyIn(BaseModel):
    message_id: str
    option_index: int = Field(ge=0, le=20)


class MessagePatch(BaseModel):
    pinned: bool | None = None
    note: str | None = Field(default=None, max_length=5000)


def _get(db, ctx, cid) -> Conversation:
    c = db.get(Conversation, cid)
    if not c or c.workspace_id != ctx.id:
        raise not_found("Investigation")
    return c


def msg_out(db: DbSession, m: Message) -> dict:
    run = db.get(AnalysisRun, m.run_id) if m.run_id else None
    return {"id": m.id, "seq": m.seq, "role": m.role, "content": m.content, "kind": m.kind, "payload": m.payload,
            "pinned": m.pinned, "note": m.note, "created_at": m.created_at.isoformat(), "run": run_out(run) if run else None}


def conv_out(db: DbSession, c: Conversation, detail=False) -> dict:
    ds = db.get(Dataset, c.dataset_id) if c.dataset_id else None
    out = {"id": c.id, "title": c.title, "saved": c.saved, "dataset_id": c.dataset_id, "dataset_name": ds.name if ds else None,
           "notes": c.notes, "findings": c.findings, "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
           "message_count": len(c.messages), "pinned_count": sum(1 for m in c.messages if m.pinned)}
    if detail:
        out["messages"] = [msg_out(db, m) for m in c.messages]
        out["dataset_current_version_id"] = ds.current_version_id if ds else None
    return out


@router.get("")
def list_conversations(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db), q: str | None = None,
                       saved: bool | None = None, dataset_id: str | None = None):
    stmt = select(Conversation).where(Conversation.workspace_id == ctx.id)
    if saved is not None:
        stmt = stmt.where(Conversation.saved.is_(saved))
    if dataset_id:
        stmt = stmt.where(Conversation.dataset_id == dataset_id)
    if q:
        like = f"%{q[:100]}%"
        ids = select(Message.conversation_id).where(Message.content.ilike(like))
        stmt = stmt.where(or_(Conversation.title.ilike(like), Conversation.id.in_(ids)))
    return {"conversations": [conv_out(db, c) for c in db.scalars(stmt.order_by(Conversation.updated_at.desc()).limit(200)).all()]}


@router.post("", status_code=201)
def create(body: ConversationIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    ds = get_dataset(db, ctx.id, body.dataset_id)
    c = Conversation(workspace_id=ctx.id, dataset_id=ds.id, title=body.title, created_by=ctx.user.id)
    db.add(c)
    db.commit()
    return {"conversation": conv_out(db, c, detail=True)}


@router.get("/suggestions")
def suggestions(dataset_id: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ds = get_dataset(db, ctx.id, dataset_id)
    if ds.status != "ready":
        return {"questions": []}
    return {"questions": svc.suggested_questions(ctxmod.build(db, ds))}


@router.get("/{cid}")
def get(cid: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    return {"conversation": conv_out(db, _get(db, ctx, cid), detail=True)}


@router.patch("/{cid}")
def update(cid: str, body: ConversationPatch, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    c = _get(db, ctx, cid)
    data = body.model_dump(exclude_unset=True)
    if "dataset_id" in data and data["dataset_id"]:
        get_dataset(db, ctx.id, data["dataset_id"])
    for k, v in data.items():
        setattr(c, k, v)
    if body.saved:
        activity.record(db, ctx.id, ctx.user.id, "investigation_saved", f"Saved investigation '{c.title}'", "conversation", c.id)
    db.commit()
    return {"conversation": conv_out(db, c)}


@router.delete("/{cid}")
def delete(cid: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    c = _get(db, ctx, cid)
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/{cid}/duplicate", status_code=201)
def duplicate(cid: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    c = _get(db, ctx, cid)
    new = Conversation(workspace_id=ctx.id, dataset_id=c.dataset_id, title=f"{c.title} (copy)", notes=c.notes,
                       findings=list(c.findings or []), created_by=ctx.user.id)
    db.add(new)
    db.flush()
    for m in c.messages:
        db.add(Message(conversation_id=new.id, seq=m.seq, role=m.role, content=m.content, kind=m.kind, run_id=m.run_id,
                       payload=m.payload, pinned=m.pinned, note=m.note))
    db.commit()
    return {"conversation": conv_out(db, new)}


@router.post("/{cid}/ask")
def ask(cid: str, body: AskIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    c = _get(db, ctx, cid)
    msgs = svc.ask(db, ctx, c, body.question.strip())
    db.commit()
    return {"messages": [msg_out(db, m) for m in msgs], "conversation": conv_out(db, c)}


@router.post("/{cid}/clarify")
def clarify(cid: str, body: ClarifyIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    c = _get(db, ctx, cid)
    m = db.get(Message, body.message_id)
    if not m or m.conversation_id != c.id or m.kind != "clarification":
        raise not_found("Clarification")
    msgs = svc.answer_clarification(db, ctx, c, m, body.option_index)
    m.payload = {**m.payload, "answered": body.option_index}
    db.commit()
    return {"messages": [msg_out(db, x) for x in msgs], "conversation": conv_out(db, c)}


@router.patch("/{cid}/messages/{mid}")
def update_message(cid: str, mid: str, body: MessagePatch, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    c = _get(db, ctx, cid)
    m = db.get(Message, mid)
    if not m or m.conversation_id != c.id:
        raise not_found("Message")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    db.commit()
    return {"message": msg_out(db, m)}


@router.get("/{cid}/export")
def export(cid: str, format: str = "md", ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    c = _get(db, ctx, cid)
    data = conv_out(db, c, detail=True)
    safe = "".join(ch for ch in c.title[:50] if ch.isalnum() or ch in " -_").strip().replace(" ", "_") or "investigation"
    if format == "json":
        return Response(json.dumps(data, indent=2, default=str), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{safe}.json"'})
    lines = [f"# {c.title}", "", f"Dataset: {data['dataset_name']}", f"Exported from ClearMetric", ""]
    if c.notes:
        lines += ["## Notes", c.notes, ""]
    if c.findings:
        lines += ["## Findings"] + [f"- {f}" for f in c.findings] + [""]
    for m in data["messages"]:
        if m["role"] == "user":
            lines += [f"### Q: {m['content']}", ""]
            continue
        lines += [m["content"], ""]
        for o in (m["payload"] or {}).get("observations", []):
            lines.append(f"- {o}")
        run = m.get("run")
        if run:
            prov = run["result"].get("provenance", {})
            lines += ["", f"*Method:* {prov.get('methodology', '')}",
                      f"*Data:* {prov.get('dataset', {}).get('name')} v{prov.get('dataset', {}).get('version_number')} · "
                      f"{prov.get('records_in_scope', 0):,} records · {prov.get('date_range', '')}"]
            cols = run["result"].get("columns", [])
            rows = run["result"].get("rows", [])[:20]
            if cols and rows:
                lines += ["", "| " + " | ".join(col["label"] for col in cols) + " |", "|" + "---|" * len(cols)]
                for r in rows:
                    lines.append("| " + " | ".join(_cell(r.get(col["key"])) for col in cols) + " |")
        if m["note"]:
            lines += ["", f"> Note: {m['note']}"]
        lines.append("")
    return Response("\n".join(lines), media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.md"'})


def _cell(v):
    if isinstance(v, float):
        return f"{v:,.2f}"
    return "" if v is None else str(v).replace("|", "/")

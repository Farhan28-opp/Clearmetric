import csv
import io
import json
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import WorkspaceCtx, editor_ctx, workspace_ctx
from app.core.config import get_settings
from app.core.errors import AppError, bad_request, not_found
from app.core.security import safe_cell
from app.database import get_db
from app.models import (AnalysisRun, Conversation, DataRelationship, Dataset, DatasetTransformation, DatasetVersion,
                        Insight, MetricDefinition, Report)
from app.services import activity
from app.services.analytics.filters import Filter, compile_filters
from app.services.dataset import demo, ingestion, relationships, service, storage, transform
from app.services.execution.engine import quote_ident, run_sql
from app.services.semantic import terms

router = APIRouter(prefix="/workspaces/{workspace_id}/datasets", tags=["datasets"])


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class SheetIn(BaseModel):
    sheet: str = Field(min_length=1, max_length=120)


class PreviewIn(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    sort: str | None = None
    direction: Literal["asc", "desc"] = "asc"
    search: str | None = Field(default=None, max_length=100)
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    columns: list[str] | None = None
    version_id: str | None = None


class TransformIn(BaseModel):
    kind: str
    params: dict = Field(default_factory=dict)


class TermsIn(BaseModel):
    mapping: dict[str, str | None]
    create_metrics: bool = True


class ExportIn(BaseModel):
    format: Literal["csv", "xlsx"] = "csv"
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    search: str | None = None
    columns: list[str] | None = None
    sort: str | None = None
    direction: Literal["asc", "desc"] = "asc"


class RelationshipIn(BaseModel):
    left_dataset_id: str
    right_dataset_id: str
    left_column: str
    right_column: str
    join_type: Literal["inner", "left"] = "left"


class MaterializeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    allow_row_multiplication: bool = False


def _read_limited(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_bytes
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise AppError(413, "file_too_large", f"Files are limited to {get_settings().max_upload_mb} MB")
    if not data:
        raise bad_request("The file is empty", "empty_file")
    return data


@router.get("")
def list_datasets(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db),
                  q: str | None = None, status: str | None = None, sort: str = "created_desc"):
    stmt = select(Dataset).where(Dataset.workspace_id == ctx.id)
    if q:
        stmt = stmt.where(or_(Dataset.name.ilike(f"%{q[:100]}%"), Dataset.original_filename.ilike(f"%{q[:100]}%")))
    if status:
        stmt = stmt.where(Dataset.status == status)
    order = {"created_desc": Dataset.created_at.desc(), "created_asc": Dataset.created_at.asc(), "name": Dataset.name.asc()}
    stmt = stmt.order_by(order.get(sort, Dataset.created_at.desc()))
    items = [service.dataset_out(db, d) for d in db.scalars(stmt).all()]
    if sort == "rows":
        items.sort(key=lambda d: -(d["row_count"] or 0))
    return {"datasets": items}


@router.post("/upload", status_code=201)
def upload(file: UploadFile = File(...), name: str | None = Form(default=None),
           ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    data = _read_limited(file)
    filename = (file.filename or "upload")[-255:]
    kind = ingestion.detect_format(filename, data[:8192])
    if kind == "xlsx":
        ingestion.verify_xlsx(data)
    key = storage.new_key(kind)
    storage.original_path(key).write_bytes(data)
    ds = Dataset(workspace_id=ctx.id, name=(name or filename.rsplit(".", 1)[0])[:200], original_filename=filename,
                 source_type=kind, status="processing", original_key=key, file_size=len(data), created_by=ctx.user.id)
    db.add(ds)
    db.flush()
    try:
        if kind in ("xlsx", "xls"):
            ds.sheets = ingestion.list_sheets(data, kind)
            non_empty = [s for s in ds.sheets if not s["empty"]]
            if not non_empty:
                raise bad_request("The workbook has no sheets with data", "empty_file")
            if len(non_empty) > 1:
                ds.status = "needs_sheet"
                ds.status_message = "Choose which sheet to import"
                activity.record(db, ctx.id, ctx.user.id, "dataset_uploaded", f"Uploaded workbook {filename}", "dataset", ds.id)
                db.commit()
                return {"dataset": service.dataset_out(db, ds, detail=True)}
            ds.sheet_name = non_empty[0]["name"]
        service.import_upload(db, ds, data, kind, ctx.user.id, ds.sheet_name or None)
    except AppError as e:
        db.rollback()
        storage.delete_quietly("originals", key)
        raise e
    activity.record(db, ctx.id, ctx.user.id, "dataset_imported", f"Imported {filename} ({ds.import_report.get('rows_read', 0):,} rows)",
                    "dataset", ds.id)
    db.commit()
    return {"dataset": service.dataset_out(db, ds, detail=True)}


@router.post("/demo", status_code=201)
def load_demo(ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    data = demo.generate_csv()
    key = storage.new_key("csv")
    storage.original_path(key).write_bytes(data)
    ds = Dataset(workspace_id=ctx.id, name="Demo Retail Orders (synthetic)", original_filename="clearmetric-demo-retail.csv",
                 description="Synthetic demonstration data generated by ClearMetric with a fixed random seed. Not real business data.",
                 source_type="csv", is_demo=True, status="processing", original_key=key, file_size=len(data), created_by=ctx.user.id)
    db.add(ds)
    db.flush()
    service.import_upload(db, ds, data, "csv", ctx.user.id, None)
    activity.record(db, ctx.id, ctx.user.id, "dataset_imported", "Imported synthetic demo retail dataset", "dataset", ds.id)
    db.commit()
    return {"dataset": service.dataset_out(db, ds, detail=True)}


@router.post("/{dataset_id}/import")
def import_sheet(dataset_id: str, body: SheetIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    if ds.source_type not in ("xlsx", "xls") or ds.current_version_id:
        raise bad_request("This dataset is not waiting for a sheet selection")
    data = storage.original_path(ds.original_key).read_bytes()
    ds.sheet_name = body.sheet
    try:
        service.import_upload(db, ds, data, ds.source_type, ctx.user.id, body.sheet)
    except AppError as e:
        db.rollback()
        raise e
    activity.record(db, ctx.id, ctx.user.id, "dataset_imported", f"Imported sheet '{body.sheet}' of {ds.original_filename}", "dataset", ds.id)
    db.commit()
    return {"dataset": service.dataset_out(db, ds, detail=True)}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    return {"dataset": service.dataset_out(db, ds, detail=True)}


@router.patch("/{dataset_id}")
def rename(dataset_id: str, body: RenameIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    old = ds.name
    ds.name = body.name.strip()
    if body.description is not None:
        ds.description = body.description
    activity.record(db, ctx.id, ctx.user.id, "dataset_renamed", f"Renamed dataset '{old}' to '{ds.name}'", "dataset", ds.id)
    db.commit()
    return {"dataset": service.dataset_out(db, ds)}


@router.delete("/{dataset_id}")
def delete(dataset_id: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    versions = db.scalars(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id)).all()
    keys = {v.parquet_key for v in versions}
    original = ds.original_key
    name = ds.name
    db.delete(ds)
    activity.record(db, ctx.id, ctx.user.id, "dataset_deleted", f"Deleted dataset '{name}' and its stored files", "dataset", dataset_id)
    db.commit()
    for k in keys:
        storage.delete_quietly("parquet", k)
    if original:
        storage.delete_quietly("originals", original)
    return {"ok": True}


@router.get("/{dataset_id}/columns")
def columns(dataset_id: str, version_id: str | None = None, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    v = service.get_version(db, ds, version_id)
    return {"version": service.version_out(v), "columns": [service.column_out(c) for c in v.columns]}


@router.get("/{dataset_id}/quality")
def quality(dataset_id: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    v = service.get_version(db, ds)
    return {"quality": v.profile.get("quality"), "readiness": v.profile.get("readiness"), "import_report": ds.import_report}


@router.post("/{dataset_id}/preview")
def preview(dataset_id: str, body: PreviewIn, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    v = service.get_version(db, ds, body.version_id)
    return service.preview(v, body.page, body.page_size, body.sort, body.direction, body.search, body.filters, body.columns)


@router.get("/{dataset_id}/columns/{column}/values")
def column_values(dataset_id: str, column: str, q: str | None = None, ctx: WorkspaceCtx = Depends(workspace_ctx),
                  db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    v = service.get_version(db, ds)
    cmap = service.column_map(v, include_excluded=True)
    if column not in cmap:
        raise not_found("Column")
    qc = quote_ident(column)
    where, params = (f" WHERE CAST({qc} AS VARCHAR) ILIKE ?", ["%" + q.replace("%", "")[:50] + "%"]) if q else ("", [])
    r = run_sql(v.parquet_key, f"SELECT CAST({qc} AS VARCHAR) AS v, COUNT(*) AS n FROM data{where} GROUP BY 1 ORDER BY n DESC LIMIT 100", params)
    return {"values": [{"value": a, "count": b} for a, b in r.rows]}


@router.post("/{dataset_id}/export")
def export(dataset_id: str, body: ExportIn, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    v = service.get_version(db, ds)
    cmap = service.column_map(v, include_excluded=True)
    cols = [c for c in (body.columns or list(cmap)) if c in cmap]
    where, params = compile_filters(body.filters, cmap)
    clauses = [where] if where else []
    if body.search:
        text_cols = [c for c, m in cmap.items() if m["dtype"] == "string"] or list(cmap)
        clauses.append("(" + " OR ".join(f"CAST({quote_ident(c)} AS VARCHAR) ILIKE ?" for c in text_cols) + ")")
        params += ["%" + body.search.replace("%", "")[:100] + "%"] * len(text_cols)
    order = f" ORDER BY {quote_ident(body.sort)} {body.direction.upper()}" if body.sort in cmap else ""
    sql = f"SELECT {', '.join(quote_ident(c) for c in cols)} FROM data{' WHERE ' + ' AND '.join(clauses) if clauses else ''}{order}"
    res = run_sql(v.parquet_key, sql, params)
    headers = [cmap[c]["display_name"] for c in cols]
    activity.record(db, ctx.id, ctx.user.id, "dataset_exported", f"Exported {len(res.rows):,} rows of '{ds.name}' as {body.format.upper()}", "dataset", ds.id)
    db.commit()
    fname = f"{ds.name[:60].replace(' ', '_')}_v{v.version_number}.{body.format}"
    return _file_response(headers, res.rows, body.format, fname)


def _file_response(headers: list[str], rows: list, fmt: str, filename: str):
    safe_name = "".join(ch for ch in filename if ch.isalnum() or ch in "._-") or "export"
    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Data")
        ws.append(headers)
        for r in rows:
            ws.append([safe_cell(x.isoformat() if hasattr(x, "isoformat") and not isinstance(x, (int, float)) else x) for x in r])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([safe_cell(h) for h in headers])
    for r in rows:
        w.writerow([safe_cell(x.isoformat() if hasattr(x, "isoformat") else x) for x in r])
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})


# ----------------------------------------------------------------------------- versions & transformations
@router.get("/{dataset_id}/versions")
def versions(dataset_id: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    vs = db.scalars(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id).order_by(DatasetVersion.version_number.desc())).all()
    tr = {t.to_version_id: t for t in db.scalars(select(DatasetTransformation).where(DatasetTransformation.dataset_id == ds.id)).all()}
    return {"current_version_id": ds.current_version_id,
            "versions": [service.version_out(v) | ({"transformation": {"kind": tr[v.id].kind, "params": tr[v.id].params}} if v.id in tr else {})
                         for v in vs]}


@router.post("/{dataset_id}/transformations/preview")
def preview_transform(dataset_id: str, body: TransformIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    v = service.get_version(db, ds)
    return transform.preview(service.load_frame(v), service.meta_from_version(v), body.kind, body.params)


@router.post("/{dataset_id}/transformations")
def apply_transform(dataset_id: str, body: TransformIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    v = service.get_version(db, ds)
    df, meta, summary, affected = transform.apply(service.load_frame(v), service.meta_from_version(v), body.kind, body.params)
    new_v = service.create_version(db, ds, df, meta, ctx.user.id, note=summary, parent=v,
                                   parquet_key=v.parquet_key if body.kind in transform.METADATA_ONLY else None)
    db.add(DatasetTransformation(dataset_id=ds.id, from_version_id=v.id, to_version_id=new_v.id, kind=body.kind,
                                 params=body.params, summary=summary, created_by=ctx.user.id))
    activity.record(db, ctx.id, ctx.user.id, "dataset_transformed", f"{ds.name}: {summary} (v{new_v.version_number})", "dataset", ds.id)
    db.commit()
    return {"dataset": service.dataset_out(db, ds, detail=True), "summary": summary, "affected": affected}


@router.post("/{dataset_id}/versions/{version_id}/restore")
def restore(dataset_id: str, version_id: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    target = service.get_version(db, ds, version_id)
    new_v = service.restore_version(db, ds, target, ctx.user.id)
    activity.record(db, ctx.id, ctx.user.id, "dataset_restored", f"{ds.name}: restored version {target.version_number} as v{new_v.version_number}", "dataset", ds.id)
    db.commit()
    return {"dataset": service.dataset_out(db, ds, detail=True)}


# ----------------------------------------------------------------------------- business terms
@router.get("/{dataset_id}/terms")
def get_terms(dataset_id: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    return {"terms": terms.suggestions(service.get_version(db, ds))}


@router.post("/{dataset_id}/terms")
def confirm_terms(dataset_id: str, body: TermsIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    result = terms.confirm(db, ds, ctx.user.id, body.mapping, body.create_metrics)
    activity.record(db, ctx.id, ctx.user.id, "terms_confirmed",
                    f"Confirmed business terminology for '{ds.name}' and created {len(result['metrics_created'])} verified metrics",
                    "dataset", ds.id)
    db.commit()
    return result


@router.get("/{dataset_id}/related")
def related(dataset_id: str, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    ds = service.get_dataset(db, ctx.id, dataset_id)
    convs = db.scalars(select(Conversation).where(Conversation.dataset_id == ds.id).order_by(Conversation.updated_at.desc()).limit(20)).all()
    reps = db.scalars(select(Report).where(Report.dataset_id == ds.id).order_by(Report.updated_at.desc()).limit(20)).all()
    mets = db.scalars(select(MetricDefinition).where(MetricDefinition.dataset_id == ds.id, MetricDefinition.status == "active")).all()
    n_runs = db.scalar(select(func.count()).select_from(AnalysisRun).where(AnalysisRun.dataset_id == ds.id))
    n_ins = db.scalar(select(func.count()).select_from(Insight).where(Insight.dataset_id == ds.id, Insight.is_current.is_(True)))
    from app.services.semantic.metrics import metric_out
    return {"conversations": [{"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat(), "saved": c.saved} for c in convs],
            "reports": [{"id": r.id, "title": r.title, "updated_at": r.updated_at.isoformat()} for r in reps],
            "metrics": [metric_out(db, m) for m in mets], "analysis_runs": n_runs, "insights": n_ins}


# ----------------------------------------------------------------------------- relationships
rel_router = APIRouter(prefix="/workspaces/{workspace_id}/relationships", tags=["relationships"])


@rel_router.get("")
def list_relationships(ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    rels = db.scalars(select(DataRelationship).where(DataRelationship.workspace_id == ctx.id).order_by(DataRelationship.created_at.desc())).all()
    return {"relationships": [relationships.rel_out(db, r) for r in rels]}


@rel_router.post("/validate")
def validate_relationship(body: RelationshipIn, ctx: WorkspaceCtx = Depends(workspace_ctx), db: DbSession = Depends(get_db)):
    return relationships.validate(db, ctx.id, body.left_dataset_id, body.right_dataset_id, body.left_column, body.right_column, body.join_type)


@rel_router.post("", status_code=201)
def create_relationship(body: RelationshipIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    report = relationships.validate(db, ctx.id, body.left_dataset_id, body.right_dataset_id, body.left_column, body.right_column, body.join_type)
    r = DataRelationship(workspace_id=ctx.id, left_dataset_id=body.left_dataset_id, right_dataset_id=body.right_dataset_id,
                         left_column=body.left_column, right_column=body.right_column, join_type=body.join_type,
                         cardinality=report["cardinality"], validation=report, created_by=ctx.user.id)
    db.add(r)
    activity.record(db, ctx.id, ctx.user.id, "relationship_created", f"Defined a {report['cardinality'].replace('_', '-')} relationship", "relationship", r.id)
    db.commit()
    return {"relationship": relationships.rel_out(db, r)}


@rel_router.post("/{rel_id}/materialize", status_code=201)
def materialize(rel_id: str, body: MaterializeIn, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    r = db.get(DataRelationship, rel_id)
    if not r or r.workspace_id != ctx.id:
        raise not_found("Relationship")
    ds = relationships.materialize(db, ctx.id, ctx.user.id, r, body.name, body.allow_row_multiplication)
    activity.record(db, ctx.id, ctx.user.id, "dataset_imported", f"Created joined dataset '{ds.name}'", "dataset", ds.id)
    db.commit()
    return {"dataset": service.dataset_out(db, ds, detail=True)}


@rel_router.delete("/{rel_id}")
def delete_relationship(rel_id: str, ctx: WorkspaceCtx = Depends(editor_ctx), db: DbSession = Depends(get_db)):
    r = db.get(DataRelationship, rel_id)
    if not r or r.workspace_id != ctx.id:
        raise not_found("Relationship")
    db.delete(r)
    db.commit()
    return {"ok": True}

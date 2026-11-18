"""Dataset lifecycle: import, immutable versions, column metadata, preview and version restore."""
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.models import Dataset, DatasetColumn, DatasetVersion
from app.services.analytics.filters import Filter, compile_filters
from app.services.dataset import ingestion, profiling, storage
from app.services.execution.engine import load_table, quote_ident, run_sql

COLUMN_FIELDS = ("position", "name", "original_name", "display_name", "dtype", "semantic_type", "semantic_confirmed",
                 "business_meaning", "meaning_confidence", "excluded", "null_count", "unique_count", "invalid_count",
                 "examples", "stats")


def get_dataset(db: DbSession, workspace_id: str, dataset_id: str) -> Dataset:
    ds = db.get(Dataset, dataset_id)
    if not ds or ds.workspace_id != workspace_id:
        raise not_found("Dataset")
    return ds


def get_version(db: DbSession, ds: Dataset, version_id: str | None = None) -> DatasetVersion:
    vid = version_id or ds.current_version_id
    v = db.get(DatasetVersion, vid) if vid else None
    if not v or v.dataset_id != ds.id:
        raise AppError(409, "dataset_not_ready", "This dataset has no processed version yet")
    return v


def column_map(version: DatasetVersion, include_excluded: bool = False) -> dict[str, dict]:
    return {c.name: {f: getattr(c, f) for f in COLUMN_FIELDS}
            for c in version.columns if include_excluded or not c.excluded}


def column_out(c: DatasetColumn) -> dict:
    return {f: getattr(c, f) for f in COLUMN_FIELDS} | {"id": c.id}


def version_out(v: DatasetVersion) -> dict:
    return {"id": v.id, "version_number": v.version_number, "row_count": v.row_count, "column_count": v.column_count,
            "note": v.note, "created_at": v.created_at.isoformat(), "parent_version_id": v.parent_version_id,
            "quality_score": (v.profile or {}).get("quality", {}).get("score")}


def dataset_out(db: DbSession, ds: Dataset, detail: bool = False) -> dict:
    v = db.get(DatasetVersion, ds.current_version_id) if ds.current_version_id else None
    out = {"id": ds.id, "name": ds.name, "description": ds.description, "original_filename": ds.original_filename,
           "source_type": ds.source_type, "is_demo": ds.is_demo, "status": ds.status, "status_message": ds.status_message,
           "file_size": ds.file_size, "created_at": ds.created_at.isoformat(), "sheets": ds.sheets, "sheet_name": ds.sheet_name,
           "current_version": version_out(v) if v else None,
           "row_count": v.row_count if v else None, "column_count": v.column_count if v else None,
           "quality_score": (v.profile or {}).get("quality", {}).get("score") if v else None}
    if detail and v:
        out["import_report"] = ds.import_report
        out["readiness"] = (v.profile or {}).get("readiness")
        out["version_count"] = db.scalar(select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == ds.id))
    return out


def create_version(db: DbSession, ds: Dataset, df: pd.DataFrame, meta: list[dict], user_id: str, note: str,
                   parent: DatasetVersion | None = None, parquet_key: str | None = None) -> DatasetVersion:
    """Persist a new immutable version. When parquet_key is given the data is unchanged (metadata-only change)."""
    s = get_settings()
    if len(df) > s.max_rows:
        raise AppError(400, "too_many_rows", f"Datasets are limited to {s.max_rows:,} rows in this deployment")
    if df.shape[1] > s.max_columns:
        raise AppError(400, "too_many_columns", f"Datasets are limited to {s.max_columns} columns")
    if parquet_key is None:
        parquet_key = storage.new_key("parquet")
        df.to_parquet(storage.parquet_path(parquet_key), index=False)
    cols = profiling.profile_columns(df, meta)
    quality = profiling.quality_report(df, cols, ds.import_report)
    number = (db.scalar(select(func.max(DatasetVersion.version_number)).where(DatasetVersion.dataset_id == ds.id)) or 0) + 1
    v = DatasetVersion(dataset_id=ds.id, version_number=number, parent_version_id=parent.id if parent else None,
                       parquet_key=parquet_key, row_count=len(df), column_count=df.shape[1], note=note, created_by=user_id,
                       profile={"quality": quality, "readiness": profiling.readiness(cols)})
    v.columns = [DatasetColumn(**{k: c.get(k) for k in COLUMN_FIELDS if k in c}) for c in cols]
    for dc, c in zip(v.columns, cols):
        dc.excluded = bool(c.get("excluded", False))
        dc.semantic_confirmed = bool(c.get("semantic_confirmed", False))
        dc.invalid_count = int(c.get("invalid_count") or 0)
    db.add(v)
    db.flush()
    ds.current_version_id = v.id
    ds.status, ds.status_message = "ready", ""
    return v


def load_frame(version: DatasetVersion) -> pd.DataFrame:
    return load_table(version.parquet_key).to_pandas()


def meta_from_version(version: DatasetVersion) -> list[dict]:
    return [column_out(c) for c in version.columns]


def import_upload(db: DbSession, ds: Dataset, data: bytes, kind: str, user_id: str, sheet: str | None) -> DatasetVersion:
    if kind == "csv":
        raw = ingestion.read_csv(data)
    else:
        raw = ingestion.read_excel(data, kind, sheet or "")
    df, meta = ingestion.type_frame(raw.frame)
    ds.import_report = raw.report | {"rows_read": len(df), "columns_read": df.shape[1]}
    return create_version(db, ds, df, meta, user_id, note="Initial import")


# ----------------------------------------------------------------------------- preview
def preview(version: DatasetVersion, page: int, page_size: int, sort: str | None, direction: str,
            search: str | None, filters: list[Filter], columns: list[str] | None) -> dict:
    s = get_settings()
    page_size = max(1, min(page_size, s.preview_max_page_size))
    cmap = column_map(version, include_excluded=True)
    selected = [c for c in (columns or list(cmap)) if c in cmap] or list(cmap)
    where, params = compile_filters(filters, cmap)
    clauses = [where] if where else []
    if search:
        text_cols = [c for c, m in cmap.items() if m["dtype"] in ("string",)] or list(cmap)
        clauses.append("(" + " OR ".join(f"CAST({quote_ident(c)} AS VARCHAR) ILIKE ?" for c in text_cols) + ")")
        params += ["%" + search.replace("%", "").replace("_", "\\_")[:100] + "%"] * len(text_cols)
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    order_sql = ""
    if sort:
        if sort not in cmap:
            raise AppError(422, "unknown_column", f"Unknown sort column '{sort}'")
        order_sql = f" ORDER BY {quote_ident(sort)} {'DESC' if direction == 'desc' else 'ASC'} NULLS LAST"
    cols_sql = ", ".join(quote_ident(c) for c in selected)
    total = run_sql(version.parquet_key, f"SELECT COUNT(*) FROM data{where_sql}", params).rows[0][0]
    res = run_sql(version.parquet_key, f"SELECT {cols_sql} FROM data{where_sql}{order_sql} LIMIT ? OFFSET ?",
                  params + [page_size, (page - 1) * page_size])
    return {"columns": selected, "rows": [[_cell(v) for v in r] for r in res.rows], "total": int(total), "page": page,
            "page_size": page_size, "pages": max(1, -(-int(total) // page_size))}


def _cell(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, float) and (v != v):
        return None
    return v if isinstance(v, (int, float, str, bool)) else str(v)


def restore_version(db: DbSession, ds: Dataset, target: DatasetVersion, user_id: str) -> DatasetVersion:
    current = get_version(db, ds)
    df = load_frame(target)
    return create_version(db, ds, df, meta_from_version(target), user_id,
                          note=f"Restored version {target.version_number}", parent=current, parquet_key=target.parquet_key)

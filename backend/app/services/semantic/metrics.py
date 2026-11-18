"""Metric Library: versioned, verifiable business metric definitions."""
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.errors import AppError, not_found
from app.models import AnalysisRun, MetricDefinition, MetricVersion, ReportSection
from app.services.dataset.service import column_map, get_dataset, get_version
from app.services.semantic.formula import Compiled, humanize, parse, validate_and_compile

UNITS = ("currency", "count", "percent", "number")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60] or "metric"


def compile_for_dataset(db: DbSession, metric: MetricDefinition, version: MetricVersion | None = None) -> tuple[Compiled, dict]:
    mv = version or db.get(MetricVersion, metric.current_version_id)
    ds = get_dataset(db, metric.workspace_id, metric.dataset_id)
    cols = column_map(get_version(db, ds))
    compiled = validate_and_compile(parse(mv.formula), cols)
    if compiled.kind == "row":
        raise AppError(422, "invalid_formula", "A metric must aggregate rows, e.g. SUM(net_revenue)")
    return compiled, cols


def check_formula(db: DbSession, workspace_id: str, dataset_id: str, formula: str) -> dict:
    ds = get_dataset(db, workspace_id, dataset_id)
    cols = column_map(get_version(db, ds))
    compiled = validate_and_compile(parse(formula), cols)
    if compiled.kind == "row":
        raise AppError(422, "invalid_formula", "A metric must aggregate rows, e.g. SUM(net_revenue)")
    return {"valid": True, "aggregation_type": compiled.kind, "columns_used": compiled.columns,
            "readable": humanize(formula, cols)}


def create_metric(db: DbSession, workspace_id: str, user_id: str, *, dataset_id: str, name: str, formula: str,
                  description: str = "", category: str = "General", unit: str = "number", decimals: int = 2,
                  default_date_column: str = "", dimensions: list | None = None, synonyms: list | None = None,
                  verified: bool = False) -> MetricDefinition:
    info = check_formula(db, workspace_id, dataset_id, formula)
    if unit not in UNITS:
        raise AppError(422, "invalid_unit", f"Unit must be one of {', '.join(UNITS)}")
    key = slugify(name)
    clash = db.scalar(select(MetricDefinition).where(MetricDefinition.workspace_id == workspace_id,
                                                     MetricDefinition.dataset_id == dataset_id,
                                                     MetricDefinition.key == key, MetricDefinition.status == "active"))
    if clash:
        raise AppError(409, "metric_exists", f"A metric named '{name}' already exists for this dataset")
    _check_date_and_dims(db, workspace_id, dataset_id, default_date_column, dimensions or [])
    m = MetricDefinition(workspace_id=workspace_id, dataset_id=dataset_id, key=key, category=category,
                         owner_id=user_id, synonyms=[s.strip().lower() for s in (synonyms or []) if s.strip()][:20])
    if verified:
        m.verified, m.verified_by, m.verified_at = True, user_id, datetime.now(timezone.utc)
    db.add(m)
    db.flush()
    v = MetricVersion(metric_id=m.id, version=1, name=name.strip(), description=description, formula=formula.strip(),
                      aggregation_type=info["aggregation_type"], unit=unit, decimals=decimals,
                      default_date_column=default_date_column, dimensions=dimensions or [],
                      columns_used=info["columns_used"], created_by=user_id, change_note="Created")
    db.add(v)
    db.flush()
    m.current_version_id = v.id
    return m


def _check_date_and_dims(db, workspace_id, dataset_id, date_col, dims):
    cols = column_map(get_version(db, get_dataset(db, workspace_id, dataset_id)))
    if date_col and (date_col not in cols or cols[date_col]["dtype"] not in ("date", "datetime")):
        raise AppError(422, "invalid_date_column", f"'{date_col}' is not a date column in this dataset")
    for d in dims:
        if d not in cols:
            raise AppError(422, "unknown_column", f"Unknown dimension '{d}'")


def update_metric(db: DbSession, m: MetricDefinition, user_id: str, **changes) -> MetricVersion:
    """Definition changes create a new version; earlier runs keep pointing at the version they used."""
    cur = db.get(MetricVersion, m.current_version_id)
    formula = changes.get("formula") or cur.formula
    info = check_formula(db, m.workspace_id, m.dataset_id, formula)
    date_col = changes.get("default_date_column", cur.default_date_column) or ""
    dims = changes.get("dimensions", cur.dimensions) or []
    _check_date_and_dims(db, m.workspace_id, m.dataset_id, date_col, dims)
    v = MetricVersion(metric_id=m.id, version=cur.version + 1, name=(changes.get("name") or cur.name).strip(),
                      description=changes.get("description", cur.description) or "", formula=formula.strip(),
                      aggregation_type=info["aggregation_type"], unit=changes.get("unit") or cur.unit,
                      decimals=changes.get("decimals", cur.decimals), default_date_column=date_col, dimensions=dims,
                      columns_used=info["columns_used"], created_by=user_id,
                      change_note=changes.get("change_note") or "Definition updated")
    if v.unit not in UNITS:
        raise AppError(422, "invalid_unit", f"Unit must be one of {', '.join(UNITS)}")
    db.add(v)
    db.flush()
    m.current_version_id = v.id
    if formula.strip() != cur.formula and m.verified:
        # A changed calculation must be re-verified by a person
        m.verified, m.verified_by, m.verified_at = False, None, None
    if "category" in changes and changes["category"]:
        m.category = changes["category"]
    if "synonyms" in changes and changes["synonyms"] is not None:
        m.synonyms = [s.strip().lower() for s in changes["synonyms"] if s.strip()][:20]
    if changes.get("name"):
        m.key = slugify(changes["name"])
    return v


def get_metric(db: DbSession, workspace_id: str, metric_id: str) -> MetricDefinition:
    m = db.get(MetricDefinition, metric_id)
    if not m or m.workspace_id != workspace_id:
        raise not_found("Metric")
    return m


def metric_out(db: DbSession, m: MetricDefinition, detail: bool = False) -> dict:
    v = db.get(MetricVersion, m.current_version_id)
    out = {"id": m.id, "key": m.key, "name": v.name, "description": v.description, "formula": v.formula,
           "category": m.category, "status": m.status, "verified": m.verified,
           "verified_at": m.verified_at.isoformat() if m.verified_at else None, "dataset_id": m.dataset_id,
           "unit": v.unit, "decimals": v.decimals, "aggregation_type": v.aggregation_type,
           "default_date_column": v.default_date_column, "dimensions": v.dimensions, "columns_used": v.columns_used,
           "synonyms": m.synonyms, "version": v.version, "version_id": v.id, "owner_id": m.owner_id,
           "created_at": m.created_at.isoformat()}
    if detail:
        out["versions"] = [{"id": x.id, "version": x.version, "name": x.name, "formula": x.formula, "unit": x.unit,
                            "change_note": x.change_note, "created_at": x.created_at.isoformat()} for x in m.versions]
        vids = [x.id for x in m.versions]
        runs = db.scalars(select(AnalysisRun).where(AnalysisRun.workspace_id == m.workspace_id)
                          .order_by(AnalysisRun.created_at.desc()).limit(500)).all()
        used = [r for r in runs if set(r.metric_version_ids or []) & set(vids)]
        out["usage"] = {"analysis_runs": len(used),
                        "recent": [{"id": r.id, "question": r.question or r.plan.get("intent"), "source": r.source,
                                    "created_at": r.created_at.isoformat(),
                                    "metric_version": next((x.version for x in m.versions if x.id in r.metric_version_ids), None)}
                                   for r in used[:10]]}
        try:
            cols = column_map(get_version(db, get_dataset(db, m.workspace_id, m.dataset_id)))
            out["readable_formula"] = humanize(v.formula, cols)
            out["valid"] = True
            compile_for_dataset(db, m)
        except AppError as e:
            out["valid"], out["validation_error"] = False, e.message
    return out


def report_sections_using(db: DbSession, workspace_id: str, version_ids: list[str]) -> int:
    secs = db.scalars(select(ReportSection)).all()
    return sum(1 for s in secs if s.plan and any(
        mm.get("metric_version_id") in version_ids for mm in (s.snapshot or {}).get("provenance", {}).get("metrics", [])))

"""Context construction for interpreters: schema, semantic metadata, metrics, statistics and conversation
state. Raw rows are never included; dimension value lists are only used by the local interpreter."""
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import Dataset, DatasetVersion, MetricDefinition, MetricVersion
from app.services.dataset.service import column_map, get_version
from app.services.execution.engine import quote_ident, run_sql

_VALUES_CACHE: dict[str, dict[str, list[str]]] = {}


@dataclass
class MetricInfo:
    id: str
    name: str
    key: str
    synonyms: list[str]
    unit: str
    kind: str
    verified: bool
    columns: list[str]
    date_column: str
    formula: str
    category: str


@dataclass
class PreviousTurn:
    question: str
    plan: dict
    dimension: str | None = None
    ordered_values: list[str] = field(default_factory=list)
    measure_label: str = ""
    used_metric_ids: list[str] = field(default_factory=list)  # most recent first, across the investigation


@dataclass
class InterpretContext:
    dataset: Dataset
    version: DatasetVersion
    cols: dict
    metrics: list[MetricInfo]
    values: dict[str, list[str]]
    anchor_date: date | None
    previous: PreviousTurn | None = None
    previous_dataset_changed: bool = False


def dimension_values(version: DatasetVersion, cols: dict) -> dict[str, list[str]]:
    if version.id in _VALUES_CACHE:
        return _VALUES_CACHE[version.id]
    out = {}
    for name, c in cols.items():
        if c["dtype"] == "string" and c["semantic_type"] in ("dimension",) and 0 < c["unique_count"] <= 300:
            r = run_sql(version.parquet_key, f"SELECT DISTINCT CAST({quote_ident(name)} AS VARCHAR) FROM data WHERE {quote_ident(name)} IS NOT NULL LIMIT 300")
            out[name] = [row[0] for row in r.rows if row[0]]
    _VALUES_CACHE[version.id] = out
    if len(_VALUES_CACHE) > 50:
        _VALUES_CACHE.pop(next(iter(_VALUES_CACHE)))
    return out


def anchor(version: DatasetVersion, cols: dict, metrics: list[MetricInfo]) -> date | None:
    date_cols = [c for c, m in cols.items() if m["dtype"] in ("date", "datetime")]
    preferred = next((m.date_column for m in metrics if m.date_column in date_cols), None) or (date_cols[0] if date_cols else None)
    if not preferred:
        return None
    v = run_sql(version.parquet_key, f"SELECT MAX({quote_ident(preferred)}) FROM data").rows[0][0]
    return v.date() if isinstance(v, datetime) else v


def build(db: DbSession, ds: Dataset, previous: PreviousTurn | None = None) -> InterpretContext:
    version = get_version(db, ds)
    cols = column_map(version)
    metrics = []
    for m in db.scalars(select(MetricDefinition).where(MetricDefinition.dataset_id == ds.id, MetricDefinition.status == "active")).all():
        v = db.get(MetricVersion, m.current_version_id)
        metrics.append(MetricInfo(m.id, v.name, m.key, m.synonyms or [], v.unit, v.aggregation_type, m.verified,
                                  v.columns_used, v.default_date_column, v.formula, m.category))
    metrics.sort(key=lambda m: (not m.verified, m.name))
    return InterpretContext(ds, version, cols, metrics, dimension_values(version, cols), anchor(version, cols, metrics), previous)


def schema_summary(ctx: InterpretContext) -> dict:
    """What an external model may see: schema and semantic metadata only (no rows, no value lists)."""
    return {
        "dataset": {"id": ctx.dataset.id, "name": ctx.dataset.name, "rows": ctx.version.row_count,
                    "version": ctx.version.version_number, "latest_date": ctx.anchor_date.isoformat() if ctx.anchor_date else None},
        "columns": [{"name": n, "display_name": c["display_name"], "type": c["dtype"], "role": c["semantic_type"],
                     "meaning": c["business_meaning"], "distinct_values": c["unique_count"]} for n, c in ctx.cols.items()],
        "metrics": [{"id": m.id, "name": m.name, "formula": m.formula, "unit": m.unit, "verified": m.verified,
                     "synonyms": m.synonyms, "default_date_column": m.date_column} for m in ctx.metrics],
        "previous_analysis": ({"question": ctx.previous.question, "plan": ctx.previous.plan,
                               "result_dimension": ctx.previous.dimension, "result_order": ctx.previous.ordered_values[:20]}
                              if ctx.previous else None),
    }

"""Type-safe filter compilation shared by data preview, analysis plans and transformations."""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError
from app.services.execution.engine import quote_ident

FilterOp = Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "between", "contains", "is_null", "not_null"]
_SQL_OPS = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
OP_LABEL = {"eq": "is", "neq": "is not", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "in": "is one of",
            "not_in": "is not one of", "between": "is between", "contains": "contains", "is_null": "is empty",
            "not_null": "is not empty"}


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=64)
    op: FilterOp
    value: Any = None


def _coerce(value, dtype: str, column: str):
    try:
        if dtype == "integer":
            f = float(value)
            return int(f) if f.is_integer() else f
        if dtype == "float":
            return float(value)
        if dtype in ("date", "datetime"):
            if isinstance(value, (date, datetime)):
                return value
            s = str(value)[:19]
            return datetime.fromisoformat(s) if dtype == "datetime" or len(s) > 10 else date.fromisoformat(s)
        if dtype == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes")
        if value is None:
            raise ValueError
        return str(value)[:500]
    except (TypeError, ValueError):
        raise AppError(422, "invalid_filter", f"'{value}' is not a valid value for column {column} ({dtype})")


def compile_filters(filters: list[Filter], columns: dict[str, dict]) -> tuple[str, list]:
    """columns: internal name → {dtype, ...}. Returns ('cond AND cond', params)."""
    parts, params = [], []
    for f in filters:
        col = columns.get(f.column)
        if not col:
            raise AppError(422, "unknown_column", f"Unknown column '{f.column}'")
        q, dtype = quote_ident(f.column), col["dtype"]
        if f.op in _SQL_OPS:
            if dtype == "string" and f.op in ("eq", "neq"):
                parts.append(f"lower({q}) {_SQL_OPS[f.op]} lower(?)")
            else:
                parts.append(f"{q} {_SQL_OPS[f.op]} ?")
            params.append(_coerce(f.value, dtype, f.column))
        elif f.op in ("in", "not_in"):
            vals = f.value if isinstance(f.value, list) else [f.value]
            if not vals or len(vals) > 200:
                raise AppError(422, "invalid_filter", "A list filter needs between 1 and 200 values")
            ph = ", ".join("?" for _ in vals)
            parts.append(f"{q} {'IN' if f.op == 'in' else 'NOT IN'} ({ph})")
            params.extend(_coerce(v, dtype, f.column) for v in vals)
        elif f.op == "between":
            if not isinstance(f.value, list) or len(f.value) != 2:
                raise AppError(422, "invalid_filter", "A between filter needs [low, high]")
            parts.append(f"{q} BETWEEN ? AND ?")
            params.extend(_coerce(v, dtype, f.column) for v in f.value)
        elif f.op == "contains":
            parts.append(f"CAST({q} AS VARCHAR) ILIKE ?")
            params.append("%" + str(f.value).replace("\\", "").replace("%", "").replace("_", "\\_")[:200] + "%")
        elif f.op == "is_null":
            parts.append(f"{q} IS NULL")
        elif f.op == "not_null":
            parts.append(f"{q} IS NOT NULL")
    return " AND ".join(parts), params


def describe_filter(f: Filter, columns: dict[str, dict]) -> str:
    label = columns.get(f.column, {}).get("display_name", f.column)
    if f.op in ("is_null", "not_null"):
        return f"{label} {OP_LABEL[f.op]}"
    val = ", ".join(map(str, f.value)) if isinstance(f.value, list) else str(f.value)
    return f"{label} {OP_LABEL[f.op]} {val}"

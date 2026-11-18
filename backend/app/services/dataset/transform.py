"""Controlled, previewable, reproducible data preparation steps. No user-supplied code is executed:
calculated fields use the restricted formula language and are evaluated over the parsed AST."""
import numpy as np
import pandas as pd

from app.core.errors import AppError
from app.services.analytics.filters import Filter
from app.services.dataset.ingestion import _to_datetime, _to_number, safe_identifier
from app.services.dataset.relationships import json_rows
from app.services.semantic.formula import parse, validate_and_compile

KINDS = {"rename_column", "set_role", "exclude_column", "parse_dates", "convert_numeric", "fill_missing",
         "drop_missing_rows", "remove_duplicates", "filter_rows", "calculated_field"}
METADATA_ONLY = {"rename_column", "set_role", "exclude_column"}
SEMANTIC_TYPES = {"measure", "currency", "dimension", "date", "identifier", "text", "boolean"}


def _col(meta: list[dict], name: str) -> dict:
    for m in meta:
        if m["name"] == name:
            return m
    raise AppError(422, "unknown_column", f"Unknown column '{name}'")


def _mask(df: pd.DataFrame, meta: list[dict], f: Filter) -> pd.Series:
    m = _col(meta, f.column)
    s = df[f.column]
    v = f.value
    if m["dtype"] in ("integer", "float") and f.op in ("eq", "neq", "gt", "gte", "lt", "lte"):
        v = float(v)
    if m["dtype"] in ("date", "datetime") and f.op in ("eq", "neq", "gt", "gte", "lt", "lte"):
        v = pd.Timestamp(v)
    ops = {"eq": lambda: s == v, "neq": lambda: s != v, "gt": lambda: s > v, "gte": lambda: s >= v, "lt": lambda: s < v,
           "lte": lambda: s <= v, "is_null": lambda: s.isna(), "not_null": lambda: s.notna(),
           "contains": lambda: s.astype(str).str.contains(str(v), case=False, regex=False),
           "in": lambda: s.astype(str).isin([str(x) for x in (v if isinstance(v, list) else [v])]),
           "not_in": lambda: ~s.astype(str).isin([str(x) for x in (v if isinstance(v, list) else [v])])}
    if f.op not in ops:
        raise AppError(422, "invalid_filter", f"Operator '{f.op}' is not supported for row filtering")
    return ops[f.op]().fillna(False).astype(bool)


def _eval_row(ast: dict, df: pd.DataFrame) -> pd.Series:
    t = ast["t"]
    if t == "num":
        return pd.Series(ast["v"], index=df.index, dtype="float64")
    if t == "col":
        return df[ast["name"]].astype("float64")
    if t == "neg":
        return -_eval_row(ast["e"], df)
    l, r = _eval_row(ast["l"], df), _eval_row(ast["r"], df)
    if ast["op"] == "/":
        return l / r.replace(0, np.nan)
    return {"+": l + r, "-": l - r, "*": l * r}[ast["op"]]


def apply(df: pd.DataFrame, meta: list[dict], kind: str, params: dict) -> tuple[pd.DataFrame, list[dict], str, int]:
    """Returns (new frame, new column metadata, human summary, affected row/cell count)."""
    if kind not in KINDS:
        raise AppError(422, "unsupported_transformation", f"Unsupported transformation '{kind}'")
    meta = [dict(m) for m in meta]
    df = df.copy()
    p = params or {}
    if kind == "rename_column":
        m = _col(meta, p.get("column", ""))
        new = str(p.get("display_name", "")).strip()[:120]
        if not new:
            raise AppError(422, "invalid_name", "A display name is required")
        old, m["display_name"] = m["display_name"], new
        return df, meta, f"Renamed '{old}' to '{new}'", 0
    if kind == "set_role":
        m = _col(meta, p.get("column", ""))
        st = p.get("semantic_type") or m["semantic_type"]
        if st not in SEMANTIC_TYPES:
            raise AppError(422, "invalid_role", "Unknown semantic role")
        if st in ("measure", "currency") and m["dtype"] not in ("integer", "float"):
            raise AppError(422, "invalid_role", "Only numeric columns can be measures")
        if st == "date" and m["dtype"] not in ("date", "datetime"):
            raise AppError(422, "invalid_role", "Convert the column to a date first")
        m["semantic_type"], m["semantic_confirmed"] = st, True
        if "business_meaning" in p:
            m["business_meaning"], m["meaning_confidence"] = str(p["business_meaning"] or "")[:40], 1.0
        return df, meta, f"Set role of '{m['display_name']}' to {st}", 0
    if kind == "exclude_column":
        m = _col(meta, p.get("column", ""))
        m["excluded"] = bool(p.get("excluded", True))
        return df, meta, f"{'Excluded' if m['excluded'] else 'Included'} '{m['display_name']}' {'from' if m['excluded'] else 'in'} analysis", 0
    if kind in ("parse_dates", "convert_numeric"):
        m = _col(meta, p.get("column", ""))
        if m["dtype"] != "string":
            raise AppError(422, "invalid_transformation", f"'{m['display_name']}' is already {m['dtype']}")
        s = df[m["name"]]
        present = s.notna()
        if kind == "parse_dates":
            parsed = pd.to_datetime(s.astype(str), errors="coerce", format="mixed", dayfirst=bool(p.get("dayfirst"))) \
                if p.get("dayfirst") is not None else _to_datetime(s)
            df[m["name"]] = pd.to_datetime(parsed).dt.normalize().astype("datetime64[us]")
            m["dtype"], m["semantic_type"] = "date", "date"
        else:
            df[m["name"]] = _to_number(s).astype("float64")
            m["dtype"], m["semantic_type"] = "float", "measure"
        failed = int((present & df[m["name"]].isna()).sum())
        m["invalid_count"] = failed
        return df, meta, f"Converted '{m['display_name']}' to {m['dtype']} ({failed:,} values could not be converted)", int(present.sum())
    if kind == "fill_missing":
        m = _col(meta, p.get("column", ""))
        s = df[m["name"]]
        n = int(s.isna().sum())
        strat = p.get("strategy", "value")
        if strat in ("mean", "median", "zero") and m["dtype"] not in ("integer", "float"):
            raise AppError(422, "invalid_transformation", f"'{strat}' only applies to numeric columns")
        fill = {"zero": lambda: 0, "mean": lambda: s.mean(), "median": lambda: s.median(),
                "mode": lambda: s.mode().iloc[0] if not s.mode().empty else None, "value": lambda: p.get("value")}.get(strat)
        if not fill:
            raise AppError(422, "invalid_transformation", "Unknown fill strategy")
        val = fill()
        if val is None:
            raise AppError(422, "invalid_transformation", "A fill value is required")
        if m["dtype"] in ("integer", "float"):
            val = float(val)
            if m["dtype"] == "integer" and not float(val).is_integer():
                df[m["name"]] = s.astype("float64")
                m["dtype"] = "float"
        df[m["name"]] = df[m["name"]].fillna(val)
        return df, meta, f"Filled {n:,} missing values in '{m['display_name']}' using {strat}{'' if strat != 'value' else f' ({val})'}", n
    if kind == "drop_missing_rows":
        m = _col(meta, p.get("column", ""))
        mask = df[m["name"]].isna()
        return df[~mask].reset_index(drop=True), meta, f"Removed {int(mask.sum()):,} rows with missing '{m['display_name']}'", int(mask.sum())
    if kind == "remove_duplicates":
        subset = p.get("columns") or None
        for c in subset or []:
            _col(meta, c)
        mask = df.astype(str).duplicated(subset=subset, keep="first") if subset else df.astype(str).duplicated(keep="first")
        label = "exact duplicate rows" if not subset else f"rows duplicated on {', '.join(subset)}"
        return df[~mask].reset_index(drop=True), meta, f"Removed {int(mask.sum()):,} {label}", int(mask.sum())
    if kind == "filter_rows":
        filters = [Filter(**f) for f in (p.get("filters") or [])]
        if not filters:
            raise AppError(422, "invalid_transformation", "At least one condition is required")
        mask = pd.Series(True, index=df.index)
        for f in filters:
            mask &= _mask(df, meta, f)
        action = p.get("action", "remove")
        keep = ~mask if action == "remove" else mask
        removed = int((~keep).sum())
        return df[keep].reset_index(drop=True), meta, f"{'Removed' if action == 'remove' else 'Kept only'} rows matching the condition ({removed:,} rows removed)", removed
    # calculated_field
    name = str(p.get("name", "")).strip()[:80]
    if not name:
        raise AppError(422, "invalid_name", "A field name is required")
    expr = str(p.get("expression", ""))
    cols = {m["name"]: m for m in meta}
    ast = parse(expr, mode="row")
    compiled = validate_and_compile(ast, cols)
    if compiled.kind != "row":
        raise AppError(422, "invalid_formula", "Calculated fields are row-level; aggregations are defined as metrics")
    ident = safe_identifier(name, set(cols))
    df[ident] = _eval_row(ast, df).replace([np.inf, -np.inf], np.nan)
    unit = p.get("unit", "number")
    meta.append({"position": len(meta), "name": ident, "original_name": name, "display_name": name, "dtype": "float",
                 "semantic_type": "currency" if unit == "currency" else "measure", "semantic_confirmed": True,
                 "business_meaning": "", "meaning_confidence": 1.0, "excluded": False, "invalid_count": 0,
                 "stats": {"expression": expr}})
    return df, meta, f"Added calculated field '{name}' = {expr}", len(df)


def preview(df: pd.DataFrame, meta: list[dict], kind: str, params: dict) -> dict:
    new_df, new_meta, summary, affected = apply(df, meta, kind, params)
    show = [m["name"] for m in new_meta][:12]
    return {"summary": summary, "affected": affected, "rows_before": len(df), "rows_after": len(new_df),
            "columns_before": len(meta), "columns_after": len(new_meta), "metadata_only": kind in METADATA_ONLY,
            "sample_columns": [{"name": m["name"], "display_name": m["display_name"], "dtype": m["dtype"]} for m in new_meta if m["name"] in show],
            "sample_after": json_rows(new_df[show].head(10))}

"""Column statistics, semantic-type inference, business-meaning suggestions and the Data Quality Score."""
import re

import numpy as np
import pandas as pd

# Business meanings: (meaning, regex on normalised column name, confidence). Generic terms get low
# confidence so onboarding asks the user to confirm instead of silently assuming.
MEANING_RULES: list[tuple[str, str, float]] = [
    ("net_revenue", r"net_?(revenue|sales|amount)", 0.9),
    ("gross_revenue", r"gross_?(revenue|sales|amount)", 0.9),
    ("revenue", r"^(revenue|sales|total_?sales|sales_?amount|amount|total|total_?amount|turnover|order_?value)$", 0.5),
    ("profit", r"(gross_?|net_?)?profit", 0.85),
    ("cost", r"^(cost|cogs|total_?cost|unit_?cost|cost_?of_?goods)", 0.8),
    ("discount", r"discount", 0.8),
    ("unit_price", r"(unit_?price|^price$|list_?price)", 0.8),
    ("quantity", r"(quantity|^qty$|units?_?sold|^units$)", 0.85),
    ("order_id", r"(order|invoice|transaction|txn|receipt)_?(id|no|num|number)", 0.9),
    ("customer_id", r"(customer|client|cust)_?(id|no|code)", 0.9),
    ("customer", r"^(customer|client)(_?name)?$", 0.7),
    ("order_date", r"(order|transaction|sale|invoice|purchase)_?date|^date$", 0.85),
    ("product", r"^(product|item|sku)(_?name)?$", 0.85),
    ("category", r"(category|product_?type|department)", 0.8),
    ("region", r"(region|territory|area|zone)", 0.85),
    ("country", r"country", 0.85),
    ("city", r"city", 0.85),
    ("channel", r"(channel|sales_?channel)", 0.85),
    ("segment", r"segment", 0.8),
]
MONEY_HINT = re.compile(r"revenue|sales|amount|price|cost|profit|total|value|spend|income|fee|cogs|payment", re.I)
ID_HINT = re.compile(r"(^|_)(id|code|key|no|num|number|zip|postal|phone|sku)$", re.I)


def suggest_meaning(name: str, dtype: str) -> tuple[str, float]:
    n = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    numeric_meanings = {"net_revenue", "gross_revenue", "revenue", "profit", "cost", "discount", "unit_price", "quantity"}
    for meaning, pattern, conf in MEANING_RULES:
        if re.search(pattern, n):
            if meaning in numeric_meanings and dtype not in ("integer", "float"):
                continue
            if meaning == "order_date" and dtype not in ("date", "datetime"):
                continue
            return meaning, conf
    return "", 0.0


def semantic_type(name: str, dtype: str, unique: int, rows: int) -> str:
    ratio = unique / rows if rows else 0
    if dtype in ("date", "datetime"):
        return "date"
    if dtype == "boolean":
        return "boolean"
    if dtype in ("integer", "float"):
        if ID_HINT.search(name) and ratio > 0.5:
            return "identifier"
        return "currency" if MONEY_HINT.search(name) else "measure"
    if ID_HINT.search(name) and (ratio > 0.3 or unique > 30):
        return "identifier"
    if unique <= 1000 and (ratio <= 0.5 or unique <= 30):
        return "dimension"
    return "text"


def _jsonable(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v if isinstance(v, (int, float, str, bool)) else str(v)


def profile_columns(df: pd.DataFrame, meta: list[dict]) -> list[dict]:
    rows = len(df)
    out = []
    for m in meta:
        s = df[m["name"]]
        nn = s.dropna()
        unique = int(nn.nunique())
        stats: dict = {}
        if m["dtype"] in ("integer", "float") and len(nn):
            v = nn.astype("float64")
            q1, q3 = float(v.quantile(0.25)), float(v.quantile(0.75))
            iqr = q3 - q1
            stats = {"min": float(v.min()), "max": float(v.max()), "mean": float(v.mean()), "median": float(v.median()),
                     "std": float(v.std()) if len(v) > 1 else 0.0, "sum": float(v.sum()), "q1": q1, "q3": q3,
                     "skew": float(v.skew()) if len(v) > 2 else 0.0,
                     "outliers_iqr": int(((v < q1 - 1.5 * iqr) | (v > q3 + 1.5 * iqr)).sum()) if iqr > 0 else 0,
                     "negatives": int((v < 0).sum()), "zeros": int((v == 0).sum())}
            counts, edges = np.histogram(v, bins=min(20, max(5, unique))) if unique > 1 else ([len(v)], [v.min(), v.max()])
            stats["histogram"] = {"counts": [int(c) for c in counts], "edges": [float(e) for e in edges]}
        elif m["dtype"] in ("date", "datetime") and len(nn):
            stats = {"min": nn.min().isoformat(), "max": nn.max().isoformat(), "distinct_days": int(nn.dt.normalize().nunique())}
        elif len(nn):
            top = nn.astype(str).value_counts().head(10)
            stats = {"top_values": [{"value": str(k), "count": int(c)} for k, c in top.items()],
                     "avg_length": float(nn.astype(str).str.len().mean())}
        examples = [_jsonable(x) for x in nn.drop_duplicates().head(5).tolist()]
        if m.get("semantic_confirmed"):  # user-confirmed metadata is never overwritten by inference
            sem, meaning, conf = m["semantic_type"], m.get("business_meaning", ""), m.get("meaning_confidence", 1.0)
        else:
            sem = m.get("semantic_type") or semantic_type(m["name"], m["dtype"], unique, rows)
            meaning, conf = suggest_meaning(m["original_name"], m["dtype"])
        out.append({**m, "null_count": int(s.isna().sum()), "unique_count": unique, "examples": examples, "stats": stats,
                    "semantic_type": sem, "business_meaning": meaning, "meaning_confidence": conf})
    return out


def quality_report(df: pd.DataFrame, columns: list[dict], import_report: dict | None = None) -> dict:
    """Data Quality Score (0-100) = 40·completeness + 20·uniqueness + 25·validity + 15·consistency.
    Each component is a ratio in [0, 1]; the methodology is returned with the score."""
    rows, ncols = len(df), max(len(columns), 1)
    total_cells = max(rows * ncols, 1)
    issues: list[dict] = []
    missing = sum(c["null_count"] for c in columns)
    try:
        dup_rows = int(df.duplicated().sum())
    except TypeError:
        dup_rows = int(df.astype(str).duplicated().sum())
    invalid = sum(c.get("invalid_count", 0) for c in columns)
    constant = [c for c in columns if c["unique_count"] <= 1 and rows > 1]
    misclassified = [c for c in columns if c["dtype"] == "string" and (c.get("numeric_like_ratio") or 0) >= 0.6]

    for c in columns:
        if c["null_count"]:
            pct = c["null_count"] / rows * 100 if rows else 0
            issues.append({"type": "missing_values", "column": c["name"], "severity": "high" if pct > 20 else "medium" if pct > 5 else "low",
                           "count": c["null_count"], "message": f"{c['display_name']}: {c['null_count']:,} missing values ({pct:.1f}%)"})
        if c.get("invalid_count"):
            kind = "invalid_dates" if c["dtype"] in ("date", "datetime") else "invalid_numbers" if c["dtype"] in ("integer", "float") else "type_inconsistency"
            issues.append({"type": kind, "column": c["name"], "severity": "medium", "count": c["invalid_count"],
                           "message": f"{c['display_name']}: {c['invalid_count']:,} values could not be read as {c['dtype']} and were set to empty"})
        st = c.get("stats") or {}
        if c["dtype"] in ("integer", "float") and st.get("outliers_iqr"):
            issues.append({"type": "outlier_candidates", "column": c["name"], "severity": "info", "count": st["outliers_iqr"],
                           "message": f"{c['display_name']}: {st['outliers_iqr']:,} values outside 1.5×IQR (candidates to review, not necessarily errors)"})
        if c["dtype"] in ("integer", "float") and abs(st.get("skew", 0)) > 3:
            issues.append({"type": "unusual_distribution", "column": c["name"], "severity": "info", "count": 0,
                           "message": f"{c['display_name']}: highly skewed distribution (skewness {st['skew']:.1f}); medians may describe it better than averages"})
        if c["semantic_type"] in ("measure", "currency") and st.get("negatives") and c.get("business_meaning") in ("quantity", "unit_price"):
            issues.append({"type": "invalid_numbers", "column": c["name"], "severity": "medium", "count": st["negatives"],
                           "message": f"{c['display_name']}: {st['negatives']:,} negative values in a field that is usually positive"})
    for c in constant:
        issues.append({"type": "constant_column", "column": c["name"], "severity": "low", "count": rows,
                       "message": f"{c['display_name']} has a single value for every row and carries no analytical information"})
    for c in misclassified:
        issues.append({"type": "possibly_misclassified", "column": c["name"], "severity": "medium", "count": 0,
                       "message": f"{c['display_name']} is stored as text but {c['numeric_like_ratio'] * 100:.0f}% of values look numeric"})
    if dup_rows:
        issues.append({"type": "duplicate_rows", "column": None, "severity": "high" if dup_rows / max(rows, 1) > 0.02 else "medium",
                       "count": dup_rows, "message": f"{dup_rows:,} rows are exact duplicates of another row"})
    if import_report and import_report.get("skipped_lines"):
        issues.append({"type": "malformed_records", "column": None, "severity": "medium", "count": import_report["skipped_lines"],
                       "message": f"{import_report['skipped_lines']:,} malformed lines were skipped during import"})

    typed_cells = sum(rows for c in columns if c["dtype"] != "string") or 1
    comp = {
        "completeness": 1 - missing / total_cells,
        "uniqueness": 1 - dup_rows / max(rows, 1),
        "validity": 1 - invalid / typed_cells,
        "consistency": 1 - (len(constant) + len(misclassified)) / ncols,
    }
    weights = {"completeness": 40, "uniqueness": 20, "validity": 25, "consistency": 15}
    score = round(sum(max(0.0, comp[k]) * w for k, w in weights.items()), 1)
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    issues.sort(key=lambda i: order[i["severity"]])
    return {
        "score": score,
        "grade": "Good" if score >= 90 else "Fair" if score >= 75 else "Needs attention",
        "components": {k: {"ratio": round(v, 4), "weight": weights[k], "points": round(max(0, v) * weights[k], 1)} for k, v in comp.items()},
        "methodology": ("Score = 40×completeness (non-missing cells / all cells) + 20×uniqueness (non-duplicate rows / rows) "
                        "+ 25×validity (parsable typed values / typed cells) + 15×consistency (columns that are neither constant "
                        "nor likely misclassified / columns). Outlier and distribution notes are informational and do not reduce the score."),
        "totals": {"rows": rows, "columns": ncols, "missing_cells": int(missing), "duplicate_rows": dup_rows,
                   "invalid_values": int(invalid), "constant_columns": len(constant)},
        "issues": issues,
    }


def readiness(columns: list[dict]) -> dict:
    measures = [c for c in columns if c["semantic_type"] in ("measure", "currency") and not c.get("excluded")]
    dims = [c for c in columns if c["semantic_type"] == "dimension" and not c.get("excluded")]
    dates = [c for c in columns if c["semantic_type"] == "date" and not c.get("excluded")]
    checks = [
        {"label": "At least one numeric measure", "ok": bool(measures)},
        {"label": "At least one categorical dimension", "ok": bool(dims)},
        {"label": "A date column for trends", "ok": bool(dates)},
    ]
    return {"ready": bool(measures), "checks": checks, "measures": len(measures), "dimensions": len(dims), "dates": len(dates)}

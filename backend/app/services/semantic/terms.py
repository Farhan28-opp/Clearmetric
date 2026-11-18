"""Business terminology confirmation: the user confirms which columns mean what, and ClearMetric
creates verified standard metrics from those confirmations (never from column names alone)."""
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import Dataset, MetricDefinition
from app.services.dataset.service import create_version, get_version, load_frame, meta_from_version
from app.services.semantic.metrics import create_metric

TERMS = [  # key, question, allowed dtypes
    ("net_revenue", "Which column represents your net revenue (after discounts)?", ("integer", "float")),
    ("gross_revenue", "Which column represents gross revenue (before discounts)?", ("integer", "float")),
    ("profit", "Which column represents profit?", ("integer", "float")),
    ("cost", "Which column represents cost?", ("integer", "float")),
    ("quantity", "Which column holds units / quantity sold?", ("integer", "float")),
    ("order_id", "Which column identifies an order or transaction?", ("string", "integer")),
    ("customer_id", "Which column identifies a customer?", ("string", "integer")),
    ("order_date", "Which date column should be used for trends by default?", ("date", "datetime")),
]


def suggestions(version) -> list[dict]:
    cols = [c for c in version.columns if not c.excluded]
    out = []
    for key, question, dtypes in TERMS:
        cands = []
        for c in cols:
            if c.dtype not in dtypes:
                continue
            conf = c.meaning_confidence if c.business_meaning == key else 0.0
            if key in ("net_revenue", "gross_revenue") and c.business_meaning == "revenue":
                conf = 0.45  # generic 'sales'/'amount': plausible, needs confirmation
            if conf or (key == "order_date" and c.dtype in ("date", "datetime")):
                cands.append({"column": c.name, "display_name": c.display_name, "confidence": round(conf or 0.3, 2)})
        cands.sort(key=lambda x: -x["confidence"])
        confirmed = next((c.name for c in cols if c.business_meaning == key and c.semantic_confirmed), None)
        out.append({"key": key, "question": question, "candidates": cands, "suggested": cands[0]["column"] if cands else None,
                    "needs_confirmation": not cands or cands[0]["confidence"] < 0.8 or (len(cands) > 1 and cands[1]["confidence"] >= 0.6),
                    "confirmed": confirmed,
                    "options": [{"column": c.name, "display_name": c.display_name} for c in cols if c.dtype in dtypes]})
    return out


STANDARD = [  # name, formula template, unit, category, requires, synonyms, description
    ("Net Revenue", "SUM({net_revenue})", "currency", "Revenue", ["net_revenue"], ["net revenue", "net sales"], "Revenue after discounts."),
    ("Gross Revenue", "SUM({gross_revenue})", "currency", "Revenue", ["gross_revenue"], ["gross revenue", "gross sales"], "Revenue before discounts."),
    ("Total Profit", "SUM({profit})", "currency", "Profitability", ["profit"], ["profit", "total profit", "earnings"], "Sum of profit."),
    ("Profit Margin", "SUM({profit}) / SUM({net_revenue})", "percent", "Profitability", ["profit", "net_revenue"], ["profit margin", "margin"], "Total profit as a share of net revenue."),
    ("Total Cost", "SUM({cost})", "currency", "Profitability", ["cost"], ["cost", "total cost", "costs"], "Sum of cost."),
    ("Total Orders", "COUNT_DISTINCT({order_id})", "count", "Volume", ["order_id"], ["orders", "order count", "number of orders", "transactions"], "Number of distinct orders."),
    ("Average Order Value", "SUM({net_revenue}) / COUNT_DISTINCT({order_id})", "currency", "Revenue", ["net_revenue", "order_id"], ["average order value", "aov", "average transaction value", "average order"], "Net revenue per distinct order."),
    ("Customer Count", "COUNT_DISTINCT({customer_id})", "count", "Customers", ["customer_id"], ["customers", "customer count", "number of customers"], "Number of distinct customers (missing IDs are not counted)."),
    ("Units Sold", "SUM({quantity})", "count", "Volume", ["quantity"], ["units", "units sold", "quantity", "items sold"], "Total quantity sold."),
]


def confirm(db: DbSession, ds: Dataset, user_id: str, mapping: dict[str, str | None], create_metrics: bool) -> dict:
    version = get_version(db, ds)
    meta = meta_from_version(version)
    by_name = {m["name"]: m for m in meta}
    valid = {k: v for k, v in mapping.items() if v and v in by_name and k in {t[0] for t in TERMS}}
    for m in meta:  # clear previous confirmations of these meanings, then apply new ones
        if m.get("business_meaning") in valid and m["name"] != valid[m["business_meaning"]]:
            m["business_meaning"], m["semantic_confirmed"] = "", False
    for key, col in valid.items():
        by_name[col]["business_meaning"], by_name[col]["meaning_confidence"], by_name[col]["semantic_confirmed"] = key, 1.0, True
        if key in ("net_revenue", "gross_revenue", "profit", "cost"):
            by_name[col]["semantic_type"] = "currency"
        elif key == "order_date":
            by_name[col]["semantic_type"] = "date"
        elif key in ("order_id", "customer_id"):
            by_name[col]["semantic_type"] = "identifier"
    create_version(db, ds, load_frame(version), meta, user_id, note="Confirmed business terminology",
                   parent=version, parquet_key=version.parquet_key)
    created, skipped = [], []
    if create_metrics:
        existing = {m.key for m in db.scalars(select(MetricDefinition).where(
            MetricDefinition.dataset_id == ds.id, MetricDefinition.status == "active")).all()}
        for name, tmpl, unit, cat, req, syn, desc in STANDARD:
            if not all(valid.get(r) for r in req):
                skipped.append({"name": name, "reason": "requires " + ", ".join(r.replace("_", " ") for r in req if not valid.get(r))})
                continue
            key = name.lower().replace(" ", "_")
            if key in existing:
                skipped.append({"name": name, "reason": "already exists"})
                continue
            formula = tmpl.format(**valid)
            m = create_metric(db, ds.workspace_id, user_id, dataset_id=ds.id, name=name, formula=formula, description=desc,
                              category=cat, unit=unit, decimals=1 if unit == "percent" else 2,
                              default_date_column=valid.get("order_date") or "", synonyms=syn, verified=True)
            created.append({"id": m.id, "name": name, "formula": formula})
    return {"confirmed": valid, "metrics_created": created, "metrics_skipped": skipped}

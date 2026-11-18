from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.database import get_db
from app.models import ContactMessage

router = APIRouter(tags=["public"])


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    company: str = Field(default="", max_length=200)
    topic: Literal["sales", "support", "partnership", "privacy", "other"]
    message: str = Field(min_length=10, max_length=5000)
    website: str = Field(default="", max_length=200)  # honeypot: must stay empty


@router.post("/contact", status_code=201)
def contact(body: ContactIn, db: DbSession = Depends(get_db)):
    s = get_settings()
    if body.website:
        return {"stored": False, "delivered": False}
    db.add(ContactMessage(name=body.name, email=body.email, company=body.company, topic=body.topic, message=body.message,
                          delivered=False))
    db.commit()
    # No email provider is configured in this deployment; the message is stored for the team to review.
    return {"stored": True, "delivered": False, "email_configured": s.smtp_configured}


@router.get("/system/status")
def status():
    s = get_settings()
    return {"app": s.app_name, "environment": s.environment,
            "ai": {"external_provider_configured": s.external_ai_available, "default_mode": "local"},
            "limits": {"max_upload_mb": s.max_upload_mb, "max_rows": s.max_rows, "query_timeout_seconds": s.query_timeout_seconds},
            "database": "sqlite" if s.database_url.startswith("sqlite") else "postgresql"}


_PREVIEW: dict | None = None


@router.get("/public/demo-preview")
def demo_preview():
    """Landing-page preview, computed live from the synthetic demo dataset (no account data involved)."""
    global _PREVIEW
    if _PREVIEW is None:
        import pandas as pd

        from app.services.dataset import demo
        df = pd.DataFrame(demo.generate_rows(), columns=demo.HEADER)
        df["month"] = df["Order Date"].str[:7]
        total = float(df["Net Revenue"].sum())
        top = df.groupby("Product")["Net Revenue"].sum().sort_values(ascending=False).head(5)
        monthly = df.groupby("month")[["Net Revenue", "Profit"]].sum().tail(12)
        last, prev = monthly.index[-1], monthly.index[-2]
        reg = (df[df.month == last].groupby("Region")["Profit"].sum() - df[df.month == prev].groupby("Region")["Profit"].sum()).sort_values()
        change = float(reg.sum())
        _PREVIEW = {
            "dataset": {"name": "Demo Retail Orders (synthetic)", "rows": len(df), "seed": 47},
            "questions": [
                {"question": "Which five products generated the highest net revenue?", "intent": "rank",
                 "rows": [{"label": k, "value": round(float(v), 2), "share": round(float(v) / total * 100, 1)} for k, v in top.items()],
                 "plan": {"intent": "rank", "metric": "Net Revenue = SUM(net_revenue)", "group_by": "Product", "sort": "desc", "limit": 5},
                 "trail": [f"Metric: Net Revenue (verified) = SUM(Net Revenue)", "Grouped by Product, sorted descending, top 5",
                           f"{len(df):,} records in scope · all dates", "Executed in an isolated DuckDB connection"]},
                {"question": "Show monthly net revenue", "intent": "trend",
                 "rows": [{"label": pd.Period(k).strftime("%b %y"), "value": round(float(v), 2)} for k, v in monthly["Net Revenue"].items()],
                 "plan": {"intent": "trend", "metric": "Net Revenue", "time": "Order Date by month"},
                 "trail": ["Metric: Net Revenue (verified)", "Aggregated per calendar month of Order Date", "Last 12 months shown"]},
                {"question": "Which region contributed most to the decrease in profit?", "intent": "decompose_change",
                 "rows": [{"label": k, "value": round(float(v), 2), "share": round(float(v) / change * 100, 1) if change else None} for k, v in reg.items()],
                 "plan": {"intent": "decompose_change", "metric": "Total Profit", "group_by": "Region",
                          "periods": f"{pd.Period(last).strftime('%b %Y')} vs {pd.Period(prev).strftime('%b %Y')}"},
                 "trail": [f"Total Profit changed by {change:,.2f} ({pd.Period(last).strftime('%b %Y')} vs {pd.Period(prev).strftime('%b %Y')})",
                           "Segment change ÷ total change, by Region", "Shows where the change happened, not why"]},
            ],
        }
    return _PREVIEW

"""Executive summary generator. All numbers come from engine computations; the interpretation paragraph is
generated from those numbers and labelled separately from computed observations."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.errors import AppError
from app.models import Dataset, Insight, MetricDefinition, MetricVersion, Report, Workspace
from app.services.analytics import engine
from app.services.analytics.format import fmt_pct, fmt_value
from app.services.analytics.plan import AnalysisPlan
from app.services.dataset.service import column_map, get_version
from app.services.insights.detector import CATEGORIES

KPI_ORDER = ["net revenue", "gross revenue", "total profit", "profit margin", "total orders", "average order value", "customer count", "units sold"]


def periods_for(report: Report, latest: date | None) -> tuple[dict, dict]:
    if report.period_start and report.period_end:
        s, e = date.fromisoformat(report.period_start), date.fromisoformat(report.period_end)
        length = (e - s).days + 1
        bs, be = s - timedelta(days=length), s - timedelta(days=1)
    else:
        if not latest:
            raise AppError(422, "no_dates", "Choose a reporting period: the dataset has no date column")
        s = latest.replace(day=1)
        e = (s.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        be = s - timedelta(days=1)
        bs = be.replace(day=1)
    return {"start": s, "end": e}, {"start": bs, "end": be}


def build_summary(db: DbSession, ws: Workspace, ds: Dataset, report: Report) -> dict:
    version = get_version(db, ds)
    cols = column_map(version)
    date_col = next((c for c, m in cols.items() if m["business_meaning"] == "order_date"), None) or \
        next((c for c, m in cols.items() if m["dtype"] in ("date", "datetime")), None)
    from app.services.ai.context import anchor
    latest = anchor(version, cols, [])
    cur, base = periods_for(report, latest)
    metrics = []
    for m in db.scalars(select(MetricDefinition).where(MetricDefinition.dataset_id == ds.id, MetricDefinition.status == "active",
                                                       MetricDefinition.verified.is_(True))).all():
        metrics.append((m, db.get(MetricVersion, m.current_version_id)))
    metrics.sort(key=lambda mv: KPI_ORDER.index(mv[1].name.lower()) if mv[1].name.lower() in KPI_ORDER else 99)
    kpis, changes, plans = [], [], []
    money = lambda v, u="currency": fmt_value(v, u, ws.currency, 2)  # noqa: E731
    for m, v in metrics[:6]:
        if not date_col:
            break
        plan = {"intent": "compare_periods", "dataset_id": ds.id, "measures": [{"kind": "metric", "metric_id": m.id}],
                "time": {"column": date_col}, "comparison": {"mode": "custom", "grain": "month",
                                                              "current": {"start": cur["start"].isoformat(), "end": cur["end"].isoformat()},
                                                              "baseline": {"start": base["start"].isoformat(), "end": base["end"].isoformat()}}}
        _, r = engine.compute(db, ws.id, AnalysisPlan(**plan))
        k = {x["key"]: x for x in r["kpis"]}
        kpis.append({"metric": v.name, "metric_version": v.version, "formula": v.formula, "unit": v.unit,
                     "current": k["current"]["value"], "baseline": k["baseline"]["value"], "change_pct": k["change_pct"]["value"],
                     "change": k["change"]["value"]})
        plans.append(plan)
    period_label = r["periods"]["current"]["label"] if kpis else f"{cur['start']} – {cur['end']}"
    base_label = r["periods"]["baseline"]["label"] if kpis else f"{base['start']} – {base['end']}"
    for k in kpis:
        if k["change_pct"] is not None:
            if k["unit"] == "percent":
                changes.append(f"{k['metric']} moved from {k['baseline'] * 100:.1f}% to {k['current'] * 100:.1f}% "
                               f"({(k['current'] - k['baseline']) * 100:+.1f} pp).")
            else:
                changes.append(f"{k['metric']}: {money(k['current'], k['unit'])} vs {money(k['baseline'], k['unit'])} ({fmt_pct(k['change_pct'])}).")
    contributors = []
    primary = next(((m, v) for m, v in metrics if v.name.lower() in ("net revenue", "gross revenue")), None)
    profit = next(((m, v) for m, v in metrics if v.name.lower() == "total profit"), None)
    dims = [c for c, mm in cols.items() if mm["business_meaning"] in ("region", "category") and mm["semantic_type"] == "dimension"]
    for target in [x for x in (profit, primary) if x]:
        for dim in dims[:2]:
            plan = {"intent": "decompose_change", "dataset_id": ds.id, "measures": [{"kind": "metric", "metric_id": target[0].id}],
                    "group_by": [dim], "time": {"column": date_col},
                    "comparison": {"mode": "custom", "grain": "month", "current": {"start": cur["start"].isoformat(), "end": cur["end"].isoformat()},
                                   "baseline": {"start": base["start"].isoformat(), "end": base["end"].isoformat()}}}
            try:
                _, r2 = engine.compute(db, ws.id, AnalysisPlan(**plan))
            except AppError:
                continue
            if r2["rows"] and r2["totals"]["change"]:
                t = r2["rows"][0]
                share = f" ({t['contribution_pct']:.0f}% of the change)" if t.get("contribution_pct") is not None else ""
                contributors.append(f"{target[1].name} by {cols[dim]['display_name'].lower()}: largest {'decline' if r2['totals']['change'] < 0 else 'increase'} "
                                    f"in {t[dim]}, {money(t['change'])}{share}.")
                plans.append(plan)
    insights = db.scalars(select(Insight).where(Insight.dataset_id == ds.id, Insight.is_current.is_(True),
                                                Insight.status != "dismissed")).all()
    insights = sorted(insights, key=lambda i: -i.score)
    findings = [{"title": i.title, "finding": i.finding, "category": CATEGORIES.get(i.category, i.category), "severity": i.severity}
                for i in insights if i.category not in ("data_quality",)][:5]
    anomalies = [i.finding for i in insights if i.category == "unusual_records"][:2]
    q = version.profile.get("quality", {})
    limitations = [f"Data Quality Score {q.get('score')} / 100 ({q.get('grade')}). {len([x for x in q.get('issues', []) if x['severity'] in ('high', 'medium')])} issues need attention."]
    if ds.is_demo:
        limitations.insert(0, "This report uses synthetic demonstration data, not real business data.")
    if latest and cur["end"] > latest:
        limitations.append(f"The reporting period extends beyond the latest data ({latest.isoformat()}); the current period may be incomplete.")
    limitations.append("Contributions show where changes occurred, not their causes. Correlations do not establish causation.")
    if not insights:
        limitations.append("No insight scan has been run for this dataset yet; run one in the Insights Center to include findings.")
    next_steps = [i.suggested_question for i in insights if i.suggested_question][:4]
    # Interpretation: generated from the computed values above (template), labelled as interpretation
    interp = []
    lead = next((k for k in kpis if k["metric"].lower() in ("net revenue", "gross revenue")), kpis[0] if kpis else None)
    prof = next((k for k in kpis if k["metric"].lower() == "total profit"), None)
    if lead and lead["change_pct"] is not None:
        interp.append(f"{lead['metric']} {'grew' if lead['change_pct'] > 0 else 'declined'} {abs(lead['change_pct']):.1f}% in {period_label} compared with {base_label}.")
    if prof and lead and prof["change_pct"] is not None and lead["change_pct"] is not None and (prof["change_pct"] - lead["change_pct"]) < -5:
        interp.append("Profit fell faster than revenue, which points to pressure on margins (for example from discounts or product mix) worth investigating.")
    if contributors:
        interp.append("The change was concentrated in specific segments listed under contributors; these are the first places to look.")
    return {"business_context": {"workspace": ws.name, "industry": ws.industry, "currency": ws.currency, "dataset": ds.name,
                                 "dataset_version": version.version_number, "rows": version.row_count, "is_demo": ds.is_demo},
            "reporting_period": {"current": period_label, "baseline": base_label, "start": cur["start"].isoformat(), "end": cur["end"].isoformat()},
            "kpis": kpis, "main_changes": changes, "contributors": contributors, "findings": findings, "anomalies": anomalies,
            "limitations": limitations, "next_investigations": next_steps,
            "interpretation": {"text": " ".join(interp), "source": "Generated by ClearMetric's template engine from the computed values above"},
            "provenance": {"plans": plans, "metric_versions": [{"metric": v.name, "version": v.version, "formula": v.formula} for _, v in metrics[:6]]}}

"""Proactive insight detection. Every candidate finding is computed by the deterministic analytical engine
(or a documented statistic); text is generated from those computed values. Thresholds are configurable
per workspace. Severity methodology is documented per detector and returned with each insight."""
import hashlib
import math

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.errors import AppError
from app.models import Dataset, Insight, MetricDefinition, MetricVersion, Workspace
from app.services.analytics import engine
from app.services.analytics.format import fmt_pct, fmt_value
from app.services.analytics.plan import AnalysisPlan
from app.services.dataset.service import column_map, get_version
from app.services.execution.engine import quote_ident, run_sql

CATEGORIES = {
    "performance_changes": "Performance changes", "growth_decline": "Growth and decline", "product_performance": "Product performance",
    "regional_performance": "Regional performance", "customer_contribution": "Customer contribution",
    "revenue_profit": "Revenue and profit patterns", "trends_seasonality": "Trends and seasonality", "unusual_records": "Unusual records",
    "concentration_risk": "Concentration risks", "data_quality": "Data-quality concerns",
}
SEVERITY_SCORE = {"high": 3, "medium": 2, "low": 1}


class Detector:
    def __init__(self, db: DbSession, ws: Workspace, ds: Dataset):
        self.db, self.ws, self.ds = db, ws, ds
        self.version = get_version(db, ds)
        self.cols = column_map(self.version)
        st = ws.insight_settings or {}
        self.thr = float(st.get("change_threshold_pct", 10))
        self.conc = float(st.get("concentration_threshold_pct", 40))
        self.k = float(st.get("outlier_iqr_k", 3.0))
        self.found: list[dict] = []
        self.metrics = {}
        for m in db.scalars(select(MetricDefinition).where(MetricDefinition.dataset_id == ds.id, MetricDefinition.status == "active")).all():
            v = db.get(MetricVersion, m.current_version_id)
            self.metrics[v.name.lower()] = (m, v)
        self.primary = self._pick_measure(["net revenue", "revenue", "gross revenue", "total sales"], ("net_revenue", "revenue", "gross_revenue"))
        self.profit = self._pick_measure(["total profit", "profit"], ("profit",))
        self.margin = self.metrics.get("profit margin")
        self.date_col = next((c for c, m in self.cols.items() if m["business_meaning"] == "order_date"), None) or \
            next((c for c, m in self.cols.items() if m["dtype"] in ("date", "datetime")), None)
        dims = [c for c, m in self.cols.items() if m["semantic_type"] == "dimension" and 2 <= m["unique_count"] <= 60]
        order = {"region": 0, "category": 1, "product": 2, "channel": 3}
        self.dims = sorted(dims, key=lambda c: order.get(self.cols[c]["business_meaning"], 9))[:4]
        self.customer = next((c for c, m in self.cols.items() if m["business_meaning"] in ("customer_id", "customer")), None)

    def _pick_measure(self, names, meanings):
        for n in names:
            if n in self.metrics and self.metrics[n][0].verified and self.metrics[n][1].aggregation_type == "additive":
                m, v = self.metrics[n]
                return {"ref": {"kind": "metric", "metric_id": m.id}, "label": v.name, "unit": v.unit, "verified": True}
        col = next((c for c, m in self.cols.items() if m["business_meaning"] in meanings and m["dtype"] in ("integer", "float")), None)
        if col:
            return {"ref": {"kind": "column", "column": col, "aggregation": "sum"}, "label": f"Total {self.cols[col]['display_name']}",
                    "unit": "currency", "verified": False}
        return None

    def compute(self, plan: dict):
        plan = {"dataset_id": self.ds.id, **plan}
        _, result = engine.compute(self.db, self.ws.id, AnalysisPlan(**plan))
        return plan, result

    def money(self, v, unit="currency"):
        return fmt_value(v, unit, self.ws.currency, 2)

    def add(self, key: str, category: str, severity: str, title: str, finding: str, method: str, *, metric="", baseline="",
            date_range="", calculations=None, plan=None, question="", limitations="", score=0.0):
        fp = hashlib.sha256(f"{self.ds.id}|{key}".encode()).hexdigest()[:40]
        self.found.append(dict(fingerprint=fp, category=category, severity=severity, title=title, finding=finding, method=method,
                               metric_label=metric, baseline=baseline, date_range=date_range, calculations=calculations or {},
                               evidence_plan=plan, suggested_question=question, limitations=limitations,
                               score=score or SEVERITY_SCORE[severity]))

    # ----------------------------------------------------------------- detectors
    def period_changes(self):
        if not self.date_col:
            return
        for meas in [m for m in (self.primary, self.profit) if m]:
            plan, r = self.compute({"intent": "compare_periods", "measures": [meas["ref"]], "time": {"column": self.date_col},
                                    "comparison": {"mode": "previous_period", "grain": "month"}})
            k = {x["key"]: x for x in r["kpis"]}
            pct = k["change_pct"]["value"]
            if pct is None or abs(pct) < self.thr:
                continue
            sev = "high" if abs(pct) >= 2.5 * self.thr else "medium"
            up = pct > 0
            p = r["periods"]
            self.add(f"mom|{meas['label']}", "performance_changes", sev,
                     f"{meas['label']} {'rose' if up else 'fell'} {abs(pct):.1f}% in {p['current']['label']}",
                     f"{meas['label']} was {self.money(k['current']['value'], meas['unit'])} in {p['current']['label']}, compared with "
                     f"{self.money(k['baseline']['value'], meas['unit'])} in {p['baseline']['label']} ({fmt_pct(pct)}).",
                     f"Month-over-month comparison of the latest month with the previous month. Reported when |change| ≥ {self.thr:.0f}%; "
                     f"high importance when ≥ {2.5 * self.thr:.0f}%.",
                     metric=meas["label"], baseline=p["baseline"]["label"], date_range=p["current"]["label"],
                     calculations={"current": k["current"]["value"], "baseline": k["baseline"]["value"], "change": k["change"]["value"],
                                   "change_pct": pct, "notes": r["notes"],
                                   "affected_filters": [{"column": self.date_col, "op": "between", "value": [p["current"]["start"], p["current"]["end"]]}]},
                     plan=plan, question=f"Which region contributed most to the change in {meas['label'].lower()}?",
                     limitations="A single month can be affected by timing and seasonality; compare with the same month last year as well.",
                     score=SEVERITY_SCORE[sev] + min(abs(pct) / 100, 1))
            # Year-over-year when there is enough history
            plan, r = self.compute({"intent": "compare_periods", "measures": [meas["ref"]], "time": {"column": self.date_col},
                                    "comparison": {"mode": "previous_year", "grain": "month"}})
            k = {x["key"]: x for x in r["kpis"]}
            pct = k["change_pct"]["value"]
            if pct is not None and k["baseline"]["value"] and abs(pct) >= self.thr:
                p = r["periods"]
                sev = "high" if abs(pct) >= 2.5 * self.thr else "medium"
                self.add(f"yoy|{meas['label']}", "growth_decline", sev,
                         f"{meas['label']} is {'up' if pct > 0 else 'down'} {abs(pct):.1f}% year over year",
                         f"{p['current']['label']}: {self.money(k['current']['value'], meas['unit'])} vs {p['baseline']['label']}: "
                         f"{self.money(k['baseline']['value'], meas['unit'])} ({fmt_pct(pct)}).",
                         "Same month one year earlier. Thresholds as for month-over-month changes.", metric=meas["label"],
                         baseline=p["baseline"]["label"], date_range=p["current"]["label"],
                         calculations={"current": k["current"]["value"], "baseline": k["baseline"]["value"], "change_pct": pct},
                         plan=plan, question=f"Show monthly {meas['label'].lower()}", score=SEVERITY_SCORE[sev] + min(abs(pct) / 100, 1))

    def segment_changes(self):
        if not (self.date_col and self.primary):
            return
        for meas in [m for m in (self.profit, self.primary) if m]:
            for dim in self.dims[:3]:
                plan, r = self.compute({"intent": "decompose_change", "measures": [meas["ref"]], "group_by": [dim],
                                        "time": {"column": self.date_col}, "comparison": {"mode": "previous_period", "grain": "month"}})
                total = r["totals"]["change"]
                if not total or not r["rows"] or not r["totals"]["baseline"]:
                    continue
                if abs(total) / abs(r["totals"]["baseline"]) * 100 < self.thr:
                    continue
                top = r["rows"][0]
                share = top.get("contribution_pct")
                if share is None or share < 40 or (top["change_pct"] is not None and abs(top["change_pct"]) < self.thr):
                    continue
                label = self.cols[dim]["display_name"]
                cat = {"region": "regional_performance", "country": "regional_performance", "city": "regional_performance",
                       "product": "product_performance", "category": "product_performance"}.get(self.cols[dim]["business_meaning"], "growth_decline")
                p = r["periods"]
                sev = "high" if share >= 50 and abs(total) / abs(r["totals"]["baseline"]) * 100 >= 2 * self.thr else "medium"
                word = "decrease" if total < 0 else "increase"
                self.add(f"seg|{meas['label']}|{dim}|{top[dim]}", cat, sev,
                         f"{top[dim]} accounts for {share:.0f}% of the {word} in {meas['label'].lower()}",
                         f"{meas['label']} changed by {self.money(total, meas['unit'])} between {p['baseline']['label']} and {p['current']['label']}. "
                         f"{label} {top[dim]} changed by {self.money(top['change'], meas['unit'])} ({fmt_pct(top['change_pct'])}), "
                         f"{share:.0f}% of the total change.",
                         "Change decomposition: segment change ÷ total change for an additive metric, latest month vs previous month. "
                         "Reported when one segment explains ≥ 40% of a change of at least the change threshold.",
                         metric=meas["label"], baseline=p["baseline"]["label"], date_range=p["current"]["label"],
                         calculations={"segment": top[dim], "segment_change": top["change"], "segment_change_pct": top["change_pct"],
                                       "total_change": total, "share_of_change_pct": share,
                                       "segments": [{"segment": x[dim], "change": x["change"], "share": x.get("contribution_pct")} for x in r["rows"][:8]],
                                       "affected_filters": [{"column": dim, "op": "eq", "value": top[dim]},
                                                            {"column": self.date_col, "op": "between", "value": [p["current"]["start"], p["current"]["end"]]}]},
                         plan=plan, question=f"Compare {meas['label'].lower()} for {top[dim]} this month with the previous month",
                         limitations="Shows where the change occurred, not why. Discounts, prices and volumes may all play a role.",
                         score=SEVERITY_SCORE[sev] + share / 100)

    def concentration(self):
        if not self.primary:
            return
        for dim in self.dims:
            plan, r = self.compute({"intent": "contribution", "measures": [self.primary["ref"]], "group_by": [dim], "limit": 10})
            n = r.get("total_groups") or 0
            if n < 3 or not r["rows"]:
                continue
            top = r["rows"][0]
            equal = 100 / n
            share = top["share_pct"] or 0
            if share < max(1.5 * equal, min(self.conc, 30)) and share < self.conc:
                continue
            sev = "high" if share >= self.conc and share >= 2 * equal else "medium" if share >= 1.5 * equal else "low"
            label = self.cols[dim]["display_name"]
            cat = "concentration_risk" if share >= self.conc else ("product_performance" if self.cols[dim]["business_meaning"] in ("product", "category") else "revenue_profit")
            self.add(f"conc|{dim}|{top[dim]}", cat, sev, f"{top[dim]} generates {share:.1f}% of {self.primary['label'].lower()}",
                     f"{label} {top[dim]} contributes {self.money(top[r['columns'][1]['key']], self.primary['unit'])} of "
                     f"{self.money(r['totals'][r['columns'][1]['key']], self.primary['unit'])} ({share:.1f}%), versus {equal:.1f}% if the "
                     f"{n} {label.lower()} values contributed equally.",
                     f"Share of total. Reported when the largest segment exceeds 1.5× an equal share; concentration risk when ≥ {self.conc:.0f}%.",
                     metric=self.primary["label"], baseline=f"Equal share {equal:.1f}%", date_range="All dates",
                     calculations={"segment": top[dim], "share_pct": share, "equal_share_pct": equal, "segments": n,
                                   "affected_filters": [{"column": dim, "op": "eq", "value": top[dim]}]},
                     plan=plan, question=f"Show monthly {self.primary['label'].lower()} by {label.lower()}", score=SEVERITY_SCORE[sev] + share / 200)
        if self.customer:
            plan, r = self.compute({"intent": "contribution", "measures": [self.primary["ref"]], "group_by": [self.customer], "limit": 20})
            n = r.get("total_groups") or 0
            if n >= 10:
                top_n = max(1, round(n * 0.1))
                rows = sorted([x for x in r["rows"] if x.get("rank")], key=lambda x: x["rank"])
                cum = r["rows"][min(top_n, len(rows)) - 1]["cumulative_pct"] if rows and top_n <= len(rows) else None
                if cum is None:
                    plan2, r2 = self.compute({"intent": "contribution", "measures": [self.primary["ref"]], "group_by": [self.customer], "limit": min(top_n, 500)})
                    cum = sum(x["share_pct"] or 0 for x in r2["rows"] if x.get("rank"))
                if cum >= 30:
                    sev = "high" if cum >= 60 else "medium" if cum >= 40 else "low"
                    self.add(f"cust|{self.customer}", "customer_contribution", sev,
                             f"The top 10% of customers generate {cum:.0f}% of {self.primary['label'].lower()}",
                             f"{top_n} of {n} customers (10%) account for {cum:.1f}% of {self.primary['label'].lower()}. The largest single customer, "
                             f"{r['rows'][0][self.customer]}, contributes {r['rows'][0]['share_pct']:.1f}%.",
                             "Cumulative share of the top decile of customers ranked by the metric. Records with a missing customer ID are excluded from the ranking but included in the total.",
                             metric=self.primary["label"], baseline="Equal contribution would be 10%", date_range="All dates",
                             calculations={"top_customers": top_n, "customers": n, "share_pct": cum},
                             plan=plan, question="Which customers purchased the most?", score=SEVERITY_SCORE[sev] + cum / 200)

    def variability(self):
        prod = next((d for d in self.dims if self.cols[d]["business_meaning"] == "product"), None)
        if not (prod and self.date_col and self.primary):
            return
        plan, r = self.compute({"intent": "trend", "measures": [self.primary["ref"]], "group_by": [prod],
                                "time": {"column": self.date_col, "grain": "month"}, "options": {"max_series": 12}, "limit": 500})
        mk = self.primary_key(r)
        series: dict = {}
        months = sorted({x["period"] for x in r["rows"]})
        for x in r["rows"]:
            series.setdefault(x[prod], {})[x["period"]] = x[mk] or 0
        cvs = {}
        for k, vals in series.items():
            arr = np.array([vals.get(m, 0.0) for m in months])
            if len(arr) >= 6 and arr.mean() > 0:
                cvs[k] = float(arr.std(ddof=1) / arr.mean())
        if len(cvs) < 3:
            return
        med = float(np.median(list(cvs.values())))
        k, cv = max(cvs.items(), key=lambda kv: kv[1])
        if cv >= 0.6 and cv >= 1.5 * med:
            arr = [series[k].get(m, 0.0) for m in months]
            self.add(f"cv|{prod}|{k}", "product_performance", "medium" if cv < 1 else "high",
                     f"{k} has unusually variable monthly {self.primary['label'].lower()}",
                     f"Monthly {self.primary['label'].lower()} for {k} has a coefficient of variation of {cv:.2f}, versus a median of {med:.2f} "
                     f"across the {len(cvs)} largest products. Monthly values ranged from {self.money(min(arr))} to {self.money(max(arr))}.",
                     "Coefficient of variation (standard deviation ÷ mean) of monthly totals, months with no sales counted as zero. "
                     "Reported when ≥ 0.6 and ≥ 1.5× the median across products.",
                     metric=self.primary["label"], baseline=f"Median CV {med:.2f}", date_range=f"{len(months)} months",
                     calculations={"product": k, "cv": cv, "median_cv": med, "monthly": dict(zip(months, arr)),
                                   "affected_filters": [{"column": prod, "op": "eq", "value": k}]},
                     plan={**plan, "focus": {"column": prod, "values": [k]}, "group_by": []},
                     question=f"Show monthly {self.primary['label'].lower()} for {k}",
                     limitations="Variability may reflect promotions, stock availability or seasonality rather than demand.", score=2 + min(cv, 2) / 2)

    def primary_key(self, r):
        return next(c["key"] for c in r["columns"] if c["role"] == "measure")

    def outliers(self):
        if not self.primary:
            return
        plan, r = self.compute({"intent": "outliers", "measures": [self.primary["ref"]],
                                "options": {"outlier_method": "iqr", "outlier_threshold": self.k}, "limit": 25})
        k = {x["key"]: x for x in r["kpis"]}
        n = k["count"]["value"]
        if not n:
            return
        total_v = sum(x["v"] for x in r["rows"])
        ids = [c["key"] for c in r["columns"] if c["role"] == "dimension"]
        idc = next((c for c in ids if self.cols.get(c, {}).get("business_meaning") == "order_id"), ids[0] if ids else None)
        sev = "medium" if n / max(self.version.row_count, 1) > 0.01 else "low"
        self.add("outliers|records", "unusual_records", sev, f"{n} transactions have unusually large or small values",
                 f"{n} records ({k['share']['value']:.1f}%) fall outside the {self.k:g}×IQR range for "
                 f"{self.primary['label'].lower()} (typical value {self.money(k['median']['value'])}). "
                 f"The largest is {self.money(r['rows'][0]['v'])}" + (f" ({r['rows'][0][idc]})" if idc else "") + ".",
                 r["method"] + " Outlier candidates are not necessarily errors or fraud.", metric=self.primary["label"],
                 baseline=f"Median {self.money(k['median']['value'])}", date_range="All dates",
                 calculations={"count": n, "bounds": r["bounds"], "listed_value_total": total_v,
                               "affected_filters": [{"column": self.primary_column(), "op": "gt", "value": r["bounds"]["high"]}] if self.primary_column() else []},
                 plan=plan, question="Are there unusual transactions?",
                 limitations="Large wholesale or bulk orders are legitimately larger than typical orders.", score=SEVERITY_SCORE[sev] + 0.3)

    def primary_column(self):
        ref = self.primary["ref"]
        if ref["kind"] == "column":
            return ref["column"]
        m = next((mv for (md, mv) in self.metrics.values() if md.id == ref["metric_id"]), None)
        return m.columns_used[0] if m and len(m.columns_used) == 1 else None

    def trend(self):
        if not (self.primary and self.date_col):
            return
        plan, r = self.compute({"intent": "trend", "measures": [self.primary["ref"]], "time": {"column": self.date_col, "grain": "month"}, "limit": 500})
        mk = self.primary_key(r)
        vals = [x[mk] or 0 for x in r["rows"]]
        if any("may be incomplete" in n for n in r["notes"]) and len(vals) > 1:
            vals = vals[:-1]
        if len(vals) < 6:
            return
        x = np.arange(len(vals))
        slope, intercept = np.polyfit(x, vals, 1)
        pred = slope * x + intercept
        ss_res = float(((np.array(vals) - pred) ** 2).sum())
        ss_tot = float(((np.array(vals) - np.mean(vals)) ** 2).sum()) or 1
        r2 = 1 - ss_res / ss_tot
        pct_month = slope / np.mean(vals) * 100 if np.mean(vals) else 0
        if r2 >= 0.3 and abs(pct_month) >= 0.5:
            self.add(f"trend|{self.primary['label']}", "trends_seasonality", "medium" if r2 >= 0.5 else "low",
                     f"{self.primary['label']} shows a {'rising' if slope > 0 else 'declining'} trend of about {abs(pct_month):.1f}% per month",
                     f"A linear fit to {len(vals)} complete months gives a slope of {self.money(slope)} per month "
                     f"({fmt_pct(pct_month)} of the monthly average) with R² = {r2:.2f}.",
                     "Ordinary least-squares line over monthly totals (incomplete latest month excluded). Reported when R² ≥ 0.3. "
                     "This describes the past; it is not a forecast.", metric=self.primary["label"], date_range=f"{len(vals)} months",
                     calculations={"slope_per_month": float(slope), "r2": r2, "pct_per_month": float(pct_month), "months": len(vals)},
                     plan=plan, question=f"Show monthly {self.primary['label'].lower()}", score=1.5 + r2)
        if len(r["rows"]) >= 24:
            by_m: dict[int, list] = {}
            for row in r["rows"]:
                by_m.setdefault(int(row["period"][5:7]), []).append(row[mk] or 0)
            avg = {m: float(np.mean(v)) for m, v in by_m.items() if len(v) >= 2}
            if len(avg) >= 12:
                overall = float(np.mean(list(avg.values())))
                peak = max(avg, key=avg.get)
                idx = avg[peak] / overall if overall else 1
                if idx >= 1.2:
                    import calendar
                    top2 = sorted(avg, key=avg.get, reverse=True)[:2]
                    self.add(f"season|{self.primary['label']}", "trends_seasonality", "low",
                             f"{calendar.month_name[peak]} is seasonally the strongest month",
                             f"Averaged across years, {calendar.month_name[peak]} {self.primary['label'].lower()} is {(idx - 1) * 100:.0f}% above the "
                             f"average month; the two strongest months are {calendar.month_name[top2[0]]} and {calendar.month_name[top2[1]]}.",
                             "Seasonal index = average for a calendar month ÷ average of all calendar months, using months seen in at least two years.",
                             metric=self.primary["label"], date_range=f"{len(r['rows'])} months",
                             calculations={"index": {calendar.month_abbr[m]: round(v / overall, 3) for m, v in sorted(avg.items())}},
                             plan=plan, question=f"Compare {self.primary['label'].lower()} year over year",
                             limitations="Based on only two years of data; seasonal estimates are rough.", score=1.4)

    def margins(self):
        if not self.margin:
            return
        m, v = self.margin
        cat = next((d for d in self.dims if self.cols[d]["business_meaning"] == "category"), self.dims[0] if self.dims else None)
        if not cat:
            return
        plan, r = self.compute({"intent": "breakdown", "measures": [{"kind": "metric", "metric_id": m.id}], "group_by": [cat],
                                "sort": {"by": "value", "direction": "asc"}})
        _, overall = self.compute({"intent": "aggregate", "measures": [{"kind": "metric", "metric_id": m.id}]})
        ov = overall["kpis"][0]["value"]
        if not r["rows"] or ov is None:
            return
        low = r["rows"][0]
        gap = (ov - low["m0"]) * 100
        if gap >= 5:
            self.add(f"margin|{cat}|{low[cat]}", "revenue_profit", "medium" if gap >= 8 else "low",
                     f"{low[cat]} has the lowest profit margin ({low['m0'] * 100:.1f}%)",
                     f"{self.cols[cat]['display_name']} {low[cat]} has a profit margin of {low['m0'] * 100:.1f}%, {gap:.1f} percentage points "
                     f"below the overall {ov * 100:.1f}%.", f"Verified metric {v.name} = {v.formula}, by {self.cols[cat]['display_name']}. "
                     "Reported when a segment is ≥ 5 pp below the overall margin.", metric=v.name, baseline=f"Overall {ov * 100:.1f}%",
                     date_range="All dates", calculations={"segment_margin": low["m0"], "overall_margin": ov, "gap_pp": gap,
                                                           "affected_filters": [{"column": cat, "op": "eq", "value": low[cat]}]},
                     plan=plan, question=f"Which products have the lowest profit margin in {low[cat]}?", score=1.5 + gap / 20)

    def correlation(self):
        disc = next((c for c, m in self.cols.items() if m["business_meaning"] == "discount"), None)
        prof = next((c for c, m in self.cols.items() if m["business_meaning"] == "profit"), None)
        rev = next((c for c, m in self.cols.items() if m["business_meaning"] in ("net_revenue", "revenue")), None)
        if not (disc and prof and rev):
            return
        d, p, rv = quote_ident(disc), quote_ident(prof), quote_ident(rev)
        sql = f"SELECT corr({d}, {p} / NULLIF({rv}, 0)), COUNT(*) FROM data WHERE {d} IS NOT NULL AND {rv} <> 0"
        corr, n = run_sql(self.version.parquet_key, sql).rows[0]
        if corr is None or math.isnan(corr) or abs(corr) < 0.3 or n < 30:
            return
        self.add(f"corr|{disc}|margin", "revenue_profit", "medium" if abs(corr) >= 0.5 else "low",
                 f"Higher discounts go with {'lower' if corr < 0 else 'higher'} order margins (r = {corr:.2f})",
                 f"Across {n:,} records, the Pearson correlation between {self.cols[disc]['display_name']} and per-record margin "
                 f"({self.cols[prof]['display_name']} ÷ {self.cols[rev]['display_name']}) is {corr:.2f}.",
                 "Pearson correlation coefficient at record level. Reported when |r| ≥ 0.3 with at least 30 records.",
                 metric="Record margin", date_range="All dates", calculations={"r": corr, "n": n, "sql": sql},
                 question=f"How are {self.cols[disc]['display_name'].lower()} values distributed?",
                 limitations="Correlation is not causation. Discounts may be applied to products that already have thin margins.", score=1.6 + abs(corr))

    def data_quality(self):
        q = self.version.profile.get("quality", {})
        for issue in [i for i in q.get("issues", []) if i["severity"] in ("high", "medium")][:5]:
            self.add(f"dq|{issue['type']}|{issue.get('column')}", "data_quality", "medium" if issue["severity"] == "high" else "low",
                     issue["message"], issue["message"] + f". Data Quality Score: {q.get('score')} / 100.", q.get("methodology", ""),
                     date_range="Current dataset version", calculations={"issue": issue, "score": q.get("score")},
                     question="", limitations="Resolve in Data Hub → Prepare (all changes are versioned and reversible).", score=0.8)

    def run(self) -> list[dict]:
        for fn in (self.period_changes, self.segment_changes, self.concentration, self.variability, self.outliers, self.trend,
                   self.margins, self.correlation, self.data_quality):
            try:
                fn()
            except AppError:
                continue  # a detector that cannot apply to this dataset is skipped, never faked
        return self.found


def generate(db: DbSession, ws: Workspace, ds: Dataset) -> list[Insight]:
    if ds.status != "ready":
        raise AppError(409, "dataset_not_ready", "The dataset is not ready")
    found = Detector(db, ws, ds).run()
    prior = {i.fingerprint: i for i in db.scalars(select(Insight).where(Insight.dataset_id == ds.id)).all()}
    for i in prior.values():
        i.is_current = False
    out = []
    for f in found:
        old = prior.get(f["fingerprint"])
        ins = Insight(workspace_id=ws.id, dataset_id=ds.id, dataset_version_id=ds.current_version_id, **f)
        if old:
            ins.status, ins.note = old.status, old.note
            db.delete(old)
        db.add(ins)
        out.append(ins)
    db.flush()
    return out


def insight_out(i: Insight) -> dict:
    return {"id": i.id, "dataset_id": i.dataset_id, "dataset_version_id": i.dataset_version_id, "category": i.category,
            "category_label": CATEGORIES.get(i.category, i.category), "severity": i.severity, "score": round(i.score, 3),
            "title": i.title, "finding": i.finding, "metric": i.metric_label, "baseline": i.baseline, "date_range": i.date_range,
            "method": i.method, "limitations": i.limitations, "calculations": i.calculations, "evidence_plan": i.evidence_plan,
            "suggested_question": i.suggested_question, "status": i.status, "note": i.note, "created_at": i.created_at.isoformat()}

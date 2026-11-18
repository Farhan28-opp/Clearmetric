"""Plan validation, restricted SQL compilation and deterministic execution.

Pipeline: AnalysisPlan → validate_plan (workspace ownership, version, columns, metrics, types, limits)
→ intent compiler (allow-listed SQL shapes, quoted identifiers, bound parameters) → isolated DuckDB
→ result validation (finite numbers, empty results) → structured result + provenance."""
import hashlib
import json
import math
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import duckdb
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import AnalysisRun, Dataset, DatasetVersion, MetricDefinition, MetricVersion
from app.services.analytics.filters import Filter, compile_filters, describe_filter
from app.services.analytics.format import period_label, range_label
from app.services.analytics.plan import INTENT_LABELS, AnalysisPlan, MeasureRef
from app.services.dataset.service import column_map, get_dataset, get_version
from app.services.execution.engine import quote_ident, run_sql
from app.services.semantic.formula import humanize, parse, validate_and_compile

NUMERIC = ("integer", "float")
AGG_LABEL = {"sum": "Total", "avg": "Average", "min": "Minimum", "max": "Maximum", "count": "Count of",
             "count_distinct": "Distinct count of", "median": "Median"}
_RESULT_CACHE: "OrderedDict[str, dict]" = OrderedDict()


class PlanInvalid(AppError):
    def __init__(self, problems: list[str]):
        super().__init__(422, "invalid_plan", "The analysis plan failed validation: " + "; ".join(problems), problems)
        self.problems = problems


@dataclass
class Measure:
    alias: str
    label: str
    sql: str
    params: list
    unit: str
    decimals: int
    kind: str  # additive|ratio|distinct|average|extreme
    definition: str
    columns: list[str]
    date_column: str = ""
    metric: dict | None = None


@dataclass
class Ctx:
    db: DbSession
    plan: AnalysisPlan
    dataset: Dataset
    version: DatasetVersion
    cols: dict
    measures: list[Measure]
    time_col: str | None
    queries: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    total_ms: int = 0

    def label(self, col: str) -> str:
        return self.cols[col]["display_name"] if col in self.cols else col

    def q(self, purpose: str, sql: str, params: list, max_rows: int | None = None):
        res = run_sql(self.version.parquet_key, sql, params, max_rows=max_rows)
        self.total_ms += res.duration_ms
        self.queries.append({"purpose": purpose, "sql": sql, "params": [_param_out(p) for p in params],
                             "duration_ms": res.duration_ms})
        return res


def _param_out(p):
    return p.isoformat() if hasattr(p, "isoformat") else p


# ----------------------------------------------------------------------------- validation
def _resolve_measure(db, workspace_id: str, ds: Dataset, cols: dict, m: MeasureRef, i: int, problems: list,
                     pinned: dict | None = None) -> Measure | None:
    alias = f"m{i}"
    if m.kind == "count_rows":
        return Measure(alias, "Number of records", "CAST(COUNT(*) AS DOUBLE)", [], "count", 0, "additive", "COUNT(*)", [])
    if m.kind == "column":
        c = cols.get(m.column or "")
        if not c:
            problems.append(f"Unknown or excluded column '{m.column}'")
            return None
        agg = m.aggregation or ("sum" if c["dtype"] in NUMERIC else "count_distinct")
        if agg in ("sum", "avg", "median") and c["dtype"] not in NUMERIC:
            problems.append(f"Cannot calculate {agg} of non-numeric column '{c['display_name']}'")
            return None
        if agg in ("min", "max") and c["dtype"] not in NUMERIC:
            problems.append(f"Min/max is supported for numeric columns only ('{c['display_name']}')")
            return None
        q = quote_ident(c["name"])
        sql = {"sum": f"SUM({q})", "avg": f"AVG({q})", "min": f"MIN({q})", "max": f"MAX({q})", "count": f"COUNT({q})",
               "count_distinct": f"COUNT(DISTINCT {q})", "median": f"MEDIAN({q})"}[agg]
        unit = "count" if agg in ("count", "count_distinct") else ("currency" if c["semantic_type"] == "currency" else "number")
        kind = {"sum": "additive", "count": "additive", "count_distinct": "distinct", "avg": "average",
                "median": "average", "min": "extreme", "max": "extreme"}[agg]
        label = f"{AGG_LABEL[agg]} {c['display_name']}".strip()
        return Measure(alias, label, f"CAST({sql} AS DOUBLE)", [], unit, 2, kind,
                       f"{agg.upper()}({c['display_name']}) — column-based, not a saved metric", [c["name"]])
    metric = db.get(MetricDefinition, m.metric_id or "")
    if not metric or metric.workspace_id != workspace_id:
        problems.append(f"Unknown metric '{m.metric_id}'")
        return None
    if metric.status != "active" and not pinned:
        problems.append("Metric is archived")
        return None
    if metric.dataset_id != ds.id:
        problems.append("The selected metric belongs to a different dataset")
        return None
    mv = db.get(MetricVersion, (pinned or {}).get(metric.id) or metric.current_version_id)
    if not mv or mv.metric_id != metric.id:
        problems.append("Pinned metric version not found")
        return None
    try:
        compiled = validate_and_compile(parse(mv.formula), cols)
    except AppError as e:
        problems.append(f"Metric '{mv.name}' is not valid for the current dataset version: {e.message}")
        return None
    return Measure(alias, mv.name, compiled.sql, compiled.params, mv.unit, mv.decimals, compiled.kind,
                   humanize(mv.formula, cols), compiled.columns, mv.default_date_column,
                   {"metric_id": metric.id, "metric_version_id": mv.id, "version": mv.version, "name": mv.name,
                    "formula": mv.formula, "readable": humanize(mv.formula, cols), "verified": metric.verified,
                    "aggregation_type": compiled.kind, "unit": mv.unit})


def validate_plan(db: DbSession, workspace_id: str, plan: AnalysisPlan, pin_version_id: str | None = None,
                  pin_metrics: dict | None = None) -> Ctx:
    """pin_version_id / pin_metrics reproduce a past run against the exact data and metric versions it used."""
    s = get_settings()
    ds = get_dataset(db, workspace_id, plan.dataset_id)  # enforces workspace ownership
    if ds.status != "ready":
        raise AppError(409, "dataset_not_ready", "This dataset is still processing or failed to import")
    version = get_version(db, ds, pin_version_id)  # verifies the version belongs to this dataset
    cols = column_map(version)
    problems: list[str] = []
    measures = [m for i, ref in enumerate(plan.measures)
                if (m := _resolve_measure(db, workspace_id, ds, cols, ref, i, problems, pin_metrics))]
    for g in plan.group_by:
        if g not in cols:
            problems.append(f"Unknown or excluded grouping column '{g}'")
        elif cols[g]["dtype"] == "float":
            problems.append(f"Cannot group by continuous numeric column '{cols[g]['display_name']}'")
    for f in plan.filters:
        if f.column not in cols:
            problems.append(f"Unknown or excluded filter column '{f.column}'")
    if plan.focus and plan.focus.column not in cols:
        problems.append(f"Unknown focus column '{plan.focus.column}'")
    time_col = None
    if plan.time:
        if plan.time.column not in cols or cols[plan.time.column]["dtype"] not in ("date", "datetime"):
            problems.append(f"'{plan.time.column}' is not a date column")
        else:
            time_col = plan.time.column
        if plan.time.start and plan.time.end and plan.time.start > plan.time.end:
            problems.append("The date range starts after it ends")
    needs_time = plan.intent in ("trend", "compare_periods", "decompose_change")
    if needs_time and not time_col:
        date_cols = [c for c, m in cols.items() if m["dtype"] in ("date", "datetime")]
        preferred = next((m.date_column for m in measures if m.date_column in date_cols), None)
        if preferred:
            time_col = preferred
        elif len(date_cols) == 1:
            time_col = date_cols[0]
        elif not date_cols:
            problems.append("This analysis needs a date column, but the dataset has none")
        else:
            problems.append("Several date columns exist; specify which one to use")
    if plan.intent != "describe_dataset" and not measures and not problems:
        problems.append("At least one measure or metric is required")
    if plan.intent in ("rank", "breakdown", "contribution", "decompose_change") and not plan.group_by:
        problems.append(f"A {INTENT_LABELS[plan.intent].lower()} needs a dimension to group by")
    if plan.intent == "compare_segments" and not (plan.group_by and (plan.focus or plan.filters)) and not plan.group_by:
        problems.append("A segment comparison needs a dimension")
    if plan.intent == "contribution" and measures and measures[0].kind != "additive":
        problems.append(f"Contribution shares require an additive metric (SUM or COUNT); '{measures[0].label}' is a {measures[0].kind} calculation")
    if plan.intent == "outliers" and measures and measures[0].kind not in ("additive", "average") :
        problems.append("Outlier detection needs a summable numeric measure")
    if plan.limit > s.max_result_rows:
        problems.append(f"Result limit exceeds the maximum of {s.max_result_rows}")
    if problems:
        raise PlanInvalid(problems)
    return Ctx(db, plan, ds, version, cols, measures, time_col)


# ----------------------------------------------------------------------------- SQL helpers
def _scope(ctx: Ctx, include_focus: bool = True, extra: list[Filter] | None = None, time_range: bool = True) -> tuple[str, list]:
    filters = list(ctx.plan.filters) + list(extra or [])
    if include_focus and ctx.plan.focus:
        filters.append(Filter(column=ctx.plan.focus.column, op="in", value=ctx.plan.focus.values))
    where, params = compile_filters(filters, ctx.cols)
    clauses = [where] if where else []
    if time_range and ctx.plan.time and ctx.time_col:
        tq = quote_ident(ctx.time_col)
        if ctx.plan.time.start:
            clauses.append(f"{tq} >= ?")
            params.append(ctx.plan.time.start)
        if ctx.plan.time.end:
            clauses.append(f"{tq} < ?")
            params.append(ctx.plan.time.end + timedelta(days=1))
    return f"WITH scope AS (SELECT * FROM data{' WHERE ' + ' AND '.join(clauses) if clauses else ''})", params


def _measures_sql(ctx: Ctx, alias_prefix: str = "") -> tuple[str, list]:
    parts, params = [], []
    for m in ctx.measures:
        parts.append(f"{m.sql} AS {alias_prefix}{m.alias}")
        params += m.params
    return ", ".join(parts), params


def _trunc(grain: str, col: str) -> str:
    assert grain in ("day", "week", "month", "quarter", "year")
    return f"CAST(date_trunc('{grain}', {quote_ident(col)}) AS DATE)"


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v):
            return None
        if math.isinf(v):
            raise AppError(422, "invalid_result", "The calculation produced an infinite value")
        return round(v, 10)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (int, str, bool)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def _dim_cols(ctx: Ctx) -> list[dict]:
    return [{"key": g, "label": ctx.label(g), "role": "dimension"} for g in ctx.plan.group_by]


def _measure_cols(ctx: Ctx) -> list[dict]:
    return [{"key": m.alias, "label": m.label, "role": "measure", "unit": m.unit, "decimals": m.decimals} for m in ctx.measures]


def _pct(a, b):
    if a is None or b in (None, 0):
        return None
    return (a - b) / abs(b) * 100


# ----------------------------------------------------------------------------- intents
def _aggregate(ctx: Ctx) -> dict:
    scope, sp = _scope(ctx)
    msql, mp = _measures_sql(ctx)
    r = ctx.q("Calculate the requested values", f"{scope} SELECT {msql}, COUNT(*) AS _rows FROM scope", sp + mp)
    row = dict(zip(r.columns, [_clean(v) for v in r.rows[0]]))
    kpis = [{"key": m.alias, "label": m.label, "value": row[m.alias], "unit": m.unit, "decimals": m.decimals} for m in ctx.measures]
    return {"columns": _measure_cols(ctx), "rows": [{k: row[k] for k in row if k != "_rows"}], "kpis": kpis,
            "chart": {"type": "kpi"}, "rows_in_scope": row["_rows"]}


def _grouped(ctx: Ctx) -> dict:
    p = ctx.plan
    scope, sp = _scope(ctx)
    msql, mp = _measures_sql(ctx)
    gsql = ", ".join(quote_ident(g) for g in p.group_by)
    m0 = ctx.measures[0].alias
    order = f"{m0} {p.sort.direction.upper()} NULLS LAST" if p.sort.by == "value" else f"{quote_ident(p.group_by[0])} {p.sort.direction.upper()}"
    r = ctx.q(f"Aggregate by {', '.join(ctx.label(g) for g in p.group_by)}",
              f"{scope} SELECT {gsql}, {msql} FROM scope GROUP BY {gsql} ORDER BY {order}, {gsql} LIMIT ?",
              sp + mp + [p.limit])
    rows = [dict(zip(r.columns, [_clean(v) for v in row])) for row in r.rows]
    n_groups = ctx.q("Count groups", f"{scope} SELECT COUNT(*) FROM (SELECT {gsql} FROM scope GROUP BY {gsql})", sp).rows[0][0]
    cols = _dim_cols(ctx) + _measure_cols(ctx)
    out = {"columns": cols, "rows": rows, "total_groups": int(n_groups), "truncated": int(n_groups) > len(rows)}
    if ctx.measures[0].kind == "additive":
        tsql, tp = ctx.measures[0].sql, ctx.measures[0].params
        total = _clean(ctx.q("Overall total for share-of-total", f"{scope} SELECT {tsql} FROM scope", sp + tp).rows[0][0])
        for row in rows:
            row["share_pct"] = (row[m0] / total * 100) if total and row[m0] is not None else None
        out["columns"].append({"key": "share_pct", "label": "Share of total", "role": "percent"})
        out["totals"] = {m0: total}
    if p.intent == "compare_segments" and len(rows) >= 2:
        a, b = rows[0], rows[1]
        out["kpis"] = [{"key": "difference", "label": f"{a[p.group_by[0]]} vs {b[p.group_by[0]]}",
                        "value": (a[m0] - b[m0]) if a[m0] is not None and b[m0] is not None else None,
                        "unit": "percent_points" if ctx.measures[0].unit == "percent" else ctx.measures[0].unit,
                        "decimals": ctx.measures[0].decimals}]
    out["chart"] = {"type": "stacked_bar" if len(p.group_by) == 2 else "hbar" if p.intent == "rank" else "bar",
                    "x": p.group_by[0], "y": [m.alias for m in ctx.measures], "series": p.group_by[1] if len(p.group_by) == 2 else None}
    return out


def _contribution(ctx: Ctx) -> dict:
    p = ctx.plan
    scope, sp = _scope(ctx, include_focus=False)
    m = ctx.measures[0]
    g = quote_ident(p.group_by[0])
    r = ctx.q(f"Aggregate by {ctx.label(p.group_by[0])}",
              f"{scope} SELECT {g}, {m.sql} AS {m.alias} FROM scope GROUP BY {g} ORDER BY {m.alias} DESC NULLS LAST LIMIT 5000",
              sp + m.params)
    total = _clean(ctx.q("Overall total", f"{scope} SELECT {m.sql} FROM scope", sp + m.params).rows[0][0]) or 0
    all_rows = [{p.group_by[0]: _clean(a), m.alias: _clean(b)} for a, b in r.rows]
    cum = 0.0
    for i, row in enumerate(all_rows):
        row["rank"] = i + 1
        row["share_pct"] = (row[m.alias] or 0) / total * 100 if total else None
        cum += row["share_pct"] or 0
        row["cumulative_pct"] = cum
    kpis = [{"key": "total", "label": f"Total {m.label}", "value": total, "unit": m.unit, "decimals": m.decimals}]
    if p.focus:
        wanted = {str(v).lower() for v in p.focus.values}
        rows = [r_ for r_ in all_rows if str(r_[p.group_by[0]]).lower() in wanted]
        missing = wanted - {str(r_[p.group_by[0]]).lower() for r_ in rows}
        if missing:
            ctx.notes.append(f"No data for: {', '.join(sorted(missing))}")
        combined = sum(r_[m.alias] or 0 for r_ in rows)
        rest = total - combined
        kpis += [{"key": "combined", "label": f"Combined {m.label} of selected", "value": combined, "unit": m.unit, "decimals": m.decimals},
                 {"key": "combined_share", "label": "Combined share of total", "value": combined / total * 100 if total else None, "unit": "pct"}]
        rows = rows + [{p.group_by[0]: "All other", m.alias: rest, "share_pct": rest / total * 100 if total else None, "rank": None, "cumulative_pct": None}]
    else:
        top = all_rows[: p.limit]
        rest = total - sum(r_[m.alias] or 0 for r_ in top)
        rows = top + ([{p.group_by[0]: "All other", m.alias: rest, "share_pct": rest / total * 100 if total else None,
                        "rank": None, "cumulative_pct": 100.0}] if len(all_rows) > len(top) else [])
        n80 = next((r_["rank"] for r_ in all_rows if r_["cumulative_pct"] >= 80), None)
        kpis.append({"key": "top_share", "label": f"Share of top {min(len(all_rows), 5)}", "unit": "pct",
                     "value": sum(r_["share_pct"] or 0 for r_ in all_rows[:5])})
        if n80:
            kpis.append({"key": "n80", "label": "Segments making up 80% of total", "value": n80, "unit": "count"})
    cols = _dim_cols(ctx)[:1] + [{"key": m.alias, "label": m.label, "role": "measure", "unit": m.unit, "decimals": m.decimals},
                                 {"key": "share_pct", "label": "Share of total", "role": "percent"},
                                 {"key": "cumulative_pct", "label": "Cumulative share", "role": "percent"}]
    return {"columns": cols, "rows": rows, "kpis": kpis, "totals": {m.alias: total}, "total_groups": len(all_rows),
            "chart": {"type": "donut" if len(rows) <= 8 else "hbar", "x": p.group_by[0], "y": [m.alias]}}


def _trend(ctx: Ctx) -> dict:
    p = ctx.plan
    grain = (p.time.grain if p.time and p.time.grain else "month")
    scope, sp = _scope(ctx)
    msql, mp = _measures_sql(ctx)
    per = _trunc(grain, ctx.time_col)
    g = p.group_by[0] if p.group_by else None
    gsel = f", {quote_ident(g)}" if g else ""
    r = ctx.q(f"Aggregate by {grain}", f"{scope} SELECT {per} AS period{gsel}, {msql} FROM scope "
              f"WHERE {quote_ident(ctx.time_col)} IS NOT NULL GROUP BY ALL ORDER BY period LIMIT 20000", sp + mp)
    rows = [dict(zip(r.columns, [_clean(v) for v in row])) for row in r.rows]
    m0 = ctx.measures[0].alias
    maxd = ctx.q("Latest date in scope", f"{scope} SELECT MAX({quote_ident(ctx.time_col)}) FROM scope", sp).rows[0][0]
    for row in rows:
        row["period_label"] = period_label(row["period"], grain)
    cols = [{"key": "period_label", "label": grain.capitalize(), "role": "period"}] + (_dim_cols(ctx)[:1]) + _measure_cols(ctx)
    out = {"columns": cols, "grain": grain}
    if g:
        totals: dict = {}
        for row in rows:
            totals[row[g]] = totals.get(row[g], 0) + (row[m0] or 0)
        keep = [k for k, _ in sorted(totals.items(), key=lambda kv: -kv[1])[: p.options.max_series]]
        if len(totals) > len(keep):
            ctx.notes.append(f"Showing the {len(keep)} largest of {len(totals)} {ctx.label(g)} series.")
        rows = [row for row in rows if row[g] in keep]
        out["series"] = [str(k) for k in keep]
        out["chart"] = {"type": "line", "x": "period_label", "y": [m0], "series": g}
    else:
        prev = None
        for row in rows:
            row["change_pct"] = _pct(row[m0], prev) if prev is not None else None
            prev = row[m0]
        out["columns"].append({"key": "change_pct", "label": f"Change vs previous {grain}", "role": "percent"})
        valid = [r_ for r_ in rows if r_[m0] is not None]
        if valid:
            best, worst = max(valid, key=lambda r_: r_[m0]), min(valid, key=lambda r_: r_[m0])
            m = ctx.measures[0]
            out["kpis"] = [
                {"key": "latest", "label": f"Latest {grain} ({valid[-1]['period_label']})", "value": valid[-1][m0], "unit": m.unit, "decimals": m.decimals},
                {"key": "latest_change", "label": f"Change vs previous {grain}", "value": valid[-1].get("change_pct"), "unit": "pct"},
                {"key": "best", "label": f"Best {grain}: {best['period_label']}", "value": best[m0], "unit": m.unit, "decimals": m.decimals},
                {"key": "worst", "label": f"Lowest {grain}: {worst['period_label']}", "value": worst[m0], "unit": m.unit, "decimals": m.decimals},
            ]
        out["chart"] = {"type": "line", "x": "period_label", "y": [m.alias for m in ctx.measures]}
    if maxd and rows:
        last_start = date.fromisoformat(rows[-1]["period"][:10])
        end = _period_end(last_start, grain)
        maxdate = maxd.date() if isinstance(maxd, datetime) else maxd
        if maxdate < end:
            ctx.notes.append(f"The latest {grain} ({period_label(last_start, grain)}) only has data up to "
                             f"{maxdate.strftime('%d %b %Y')} and may be incomplete.")
    out["rows"] = rows
    return out


def _period_end(start: date, grain: str) -> date:
    if grain == "day":
        return start
    if grain == "week":
        return start + timedelta(days=6)
    months = {"month": 1, "quarter": 3, "year": 12}[grain]
    y, mth = divmod(start.month - 1 + months, 12)
    return date(start.year + y, mth + 1, 1) - timedelta(days=1)


def _period_start(d: date, grain: str) -> date:
    if grain == "day":
        return d
    if grain == "week":
        return d - timedelta(days=d.weekday())
    if grain == "month":
        return d.replace(day=1)
    if grain == "quarter":
        return date(d.year, (d.month - 1) // 3 * 3 + 1, 1)
    return date(d.year, 1, 1)


def resolve_periods(ctx: Ctx) -> tuple[tuple[date, date], tuple[date, date], str]:
    comp = ctx.plan.comparison
    grain = comp.grain if comp else "month"
    if comp and comp.current and comp.baseline:
        return (comp.current.start, comp.current.end), (comp.baseline.start, comp.baseline.end), grain
    scope, sp = _scope(ctx, time_range=False)
    maxd = ctx.q("Latest date in scope", f"{scope} SELECT MAX({quote_ident(ctx.time_col)}) FROM scope", sp).rows[0][0]
    if maxd is None:
        raise AppError(422, "no_data", "There is no dated data in the selected scope")
    maxd = maxd.date() if isinstance(maxd, datetime) else maxd
    if comp and comp.current:
        cur = (comp.current.start, comp.current.end)
    else:
        start = _period_start(maxd, grain)
        cur = (start, _period_end(start, grain))
    if comp and comp.mode == "previous_year":
        base = (cur[0].replace(year=cur[0].year - 1), cur[1].replace(year=cur[1].year - 1) if not (cur[1].month == 2 and cur[1].day == 29) else date(cur[1].year - 1, 2, 28))
    else:
        bstart = _period_start(cur[0] - timedelta(days=1), grain) if grain != "day" else cur[0] - timedelta(days=1)
        base = (bstart, _period_end(bstart, grain))
    if maxd < cur[1]:
        ctx.notes.append(f"The current period has data only up to {maxd.strftime('%d %b %Y')}; it may be incomplete, "
                         f"so it is compared with a full baseline period.")
    return cur, base, grain


def _compare(ctx: Ctx, decompose: bool) -> dict:
    p = ctx.plan
    cur, base, grain = resolve_periods(ctx)
    scope, sp = _scope(ctx, time_range=False)
    tq = quote_ident(ctx.time_col)
    case = f"CASE WHEN {tq} >= ? AND {tq} < ? THEN 'current' WHEN {tq} >= ? AND {tq} < ? THEN 'baseline' END"
    cp = [cur[0], cur[1] + timedelta(days=1), base[0], base[1] + timedelta(days=1)]
    msql, mp = _measures_sql(ctx)
    m = ctx.measures[0]
    total_r = ctx.q("Measure both periods", f"{scope}, p AS (SELECT *, {case} AS _period FROM scope) "
                    f"SELECT _period, {msql}, COUNT(*) AS _rows FROM p WHERE _period IS NOT NULL GROUP BY _period", sp + cp + mp)
    tot = {row[0]: dict(zip(total_r.columns, [_clean(v) for v in row])) for row in total_r.rows}
    tc, tb = tot.get("current", {}).get(m.alias), tot.get("baseline", {}).get(m.alias)
    total_change = (tc or 0) - (tb or 0) if tc is not None or tb is not None else None
    def _lbl(r):
        return period_label(r[0], grain) if r[0] == _period_start(r[0], grain) and r[1] == _period_end(r[0], grain) else range_label(*r)
    cur_label, base_label = _lbl(cur), _lbl(base)
    kpis = [{"key": "current", "label": f"Current ({cur_label})", "value": tc, "unit": m.unit, "decimals": m.decimals},
            {"key": "baseline", "label": f"Baseline ({base_label})", "value": tb, "unit": m.unit, "decimals": m.decimals},
            {"key": "change", "label": "Change", "value": total_change, "unit": "percent_points" if m.unit == "percent" else m.unit, "decimals": m.decimals},
            {"key": "change_pct", "label": "Change %", "value": _pct(tc, tb), "unit": "pct"}]
    out = {"periods": {"current": {"start": cur[0].isoformat(), "end": cur[1].isoformat(), "label": cur_label},
                       "baseline": {"start": base[0].isoformat(), "end": base[1].isoformat(), "label": base_label},
                       "grain": grain},
           "kpis": kpis, "totals": {"current": tc, "baseline": tb, "change": total_change}}
    if not p.group_by:
        out["columns"] = [{"key": "period", "label": "Period", "role": "dimension"}] + _measure_cols(ctx)
        out["rows"] = [{"period": f"Current ({cur_label})", **{k: v for k, v in tot.get("current", {}).items() if k.startswith("m")}},
                       {"period": f"Baseline ({base_label})", **{k: v for k, v in tot.get("baseline", {}).items() if k.startswith("m")}}]
        out["chart"] = {"type": "bar", "x": "period", "y": [m.alias]}
        return out
    g = p.group_by[0]
    gq = quote_ident(g)
    r = ctx.q(f"Measure both periods by {ctx.label(g)}", f"{scope}, p AS (SELECT *, {case} AS _period FROM scope) "
              f"SELECT {gq}, _period, {m.sql} AS v FROM p WHERE _period IS NOT NULL GROUP BY ALL LIMIT 20000",
              sp + cp + m.params)
    seg: dict = {}
    for key, period, v in r.rows:
        seg.setdefault(_clean(key), {})[period] = _clean(v)
    rows = []
    additive = m.kind == "additive"
    for key, vals in seg.items():
        c, b = vals.get("current"), vals.get("baseline")
        change = (c or 0) - (b or 0) if (additive or (c is not None and b is not None)) else None
        row = {g: key, "current": c, "baseline": b, "change": change, "change_pct": _pct(c, b)}
        if decompose and additive and total_change:
            row["contribution_pct"] = change / total_change * 100 if change is not None else None
        rows.append(row)
    decreasing = (total_change or 0) < 0 or p.options.expected_direction == "decrease"
    rows.sort(key=lambda r_: (r_["change"] is None, r_["change"] if decreasing else -(r_["change"] or 0)))
    rows = rows[: p.limit]
    cols = [{"key": g, "label": ctx.label(g), "role": "dimension"},
            {"key": "baseline", "label": f"Baseline ({base_label})", "role": "measure", "unit": m.unit, "decimals": m.decimals},
            {"key": "current", "label": f"Current ({cur_label})", "role": "measure", "unit": m.unit, "decimals": m.decimals},
            {"key": "change", "label": "Change", "role": "measure", "unit": "percent_points" if m.unit == "percent" else m.unit, "decimals": m.decimals},
            {"key": "change_pct", "label": "Change %", "role": "percent"}]
    if decompose:
        if additive and total_change:
            cols.append({"key": "contribution_pct", "label": "Share of total change", "role": "percent"})
            ctx.notes.append("Share of total change = segment change ÷ total change. Shares can exceed 100% or be negative "
                             "when segments moved in opposite directions.")
        elif not additive:
            ctx.notes.append(f"'{m.label}' is a {m.kind} measure, so segment changes are not additive and cannot be "
                             "expressed as shares of the total change.")
        if p.options.expected_direction == "decrease" and (total_change or 0) > 0:
            ctx.notes.append(f"{m.label} did not decrease overall between these periods (it rose); the table lists the "
                             "segments that declined first.")
        if p.options.expected_direction == "increase" and (total_change or 0) < 0:
            ctx.notes.append(f"{m.label} did not increase overall between these periods (it fell).")
        ctx.notes.append("This decomposition shows where the change occurred. It identifies the segments associated "
                         "with the change, not the underlying causes.")
        if rows:
            topc = rows[0]
            kpis.append({"key": "top_contributor", "label": f"Largest {'decline' if decreasing else 'increase'}: {topc[g]}",
                         "value": topc["change"], "unit": m.unit, "decimals": m.decimals})
    out.update({"columns": cols, "rows": rows,
                "chart": {"type": "waterfall" if decompose else "bar", "x": g, "y": ["change"] if decompose else ["baseline", "current"]}})
    return out


def _single_column(ctx: Ctx) -> str | None:
    m = ctx.measures[0]
    return m.columns[0] if len(m.columns) == 1 and ctx.cols[m.columns[0]]["dtype"] in NUMERIC else None


def _distribution(ctx: Ctx) -> dict:
    if ctx.plan.group_by:
        if ctx.measures[0].kind == "additive":
            return _contribution(ctx)
        return _grouped(ctx)
    col = _single_column(ctx)
    if not col:
        raise AppError(422, "unsupported", "A distribution needs a single numeric column or a dimension to break down by")
    q = quote_ident(col)
    scope, sp = _scope(ctx)
    st = ctx.q("Distribution statistics", f"{scope} SELECT MIN({q}), MAX({q}), AVG({q}), MEDIAN({q}), "
               f"quantile_cont({q}, 0.25), quantile_cont({q}, 0.75), STDDEV_SAMP({q}), COUNT({q}) FROM scope", sp)
    mn, mx, avg, med, q1, q3, sd, n = [_clean(v) for v in st.rows[0]]
    if not n:
        raise AppError(422, "no_data", "No values in scope")
    bins = ctx.plan.options.bins
    width = (mx - mn) / bins if mx != mn else 1.0
    h = ctx.q("Histogram bins", f"{scope} SELECT LEAST(CAST(FLOOR(({q} - ?) / ?) AS INTEGER), ?) AS b, COUNT(*) AS n "
              f"FROM scope WHERE {q} IS NOT NULL GROUP BY b ORDER BY b", sp + [mn, width, bins - 1])
    counts = {int(b): int(c) for b, c in h.rows}
    unit = "currency" if ctx.cols[col]["semantic_type"] == "currency" else "number"
    rows = [{"bin": f"{mn + i * width:,.2f} – {mn + (i + 1) * width:,.2f}", "low": mn + i * width, "high": mn + (i + 1) * width,
             "count": counts.get(i, 0), "share_pct": counts.get(i, 0) / n * 100} for i in range(bins if mx != mn else 1)]
    label = ctx.label(col)
    return {"columns": [{"key": "bin", "label": f"{label} range", "role": "dimension"},
                        {"key": "count", "label": "Records", "role": "measure", "unit": "count", "decimals": 0},
                        {"key": "share_pct", "label": "Share of records", "role": "percent"}],
            "rows": rows, "chart": {"type": "histogram", "x": "bin", "y": ["count"]},
            "kpis": [{"key": "median", "label": f"Median {label}", "value": med, "unit": unit, "decimals": 2},
                     {"key": "mean", "label": f"Average {label}", "value": avg, "unit": unit, "decimals": 2},
                     {"key": "iqr", "label": "Middle 50% range", "value": None, "text": f"{q1:,.2f} – {q3:,.2f}"},
                     {"key": "n", "label": "Values", "value": n, "unit": "count"}],
            "stats": {"min": mn, "max": mx, "mean": avg, "median": med, "q1": q1, "q3": q3, "std": sd, "count": n},
            "method": f"Equal-width histogram with {bins} bins over [{mn:,.2f}, {mx:,.2f}]."}


def _outliers(ctx: Ctx) -> dict:
    p = ctx.plan
    opt = p.options
    method = opt.outlier_method
    k = opt.outlier_threshold if not (method == "zscore" and opt.outlier_threshold == 1.5) else 3.0
    scope, sp = _scope(ctx)
    m = ctx.measures[0]
    grain = p.time.grain if p.time and p.time.grain else None
    if grain and ctx.time_col:
        base = f"SELECT {_trunc(grain, ctx.time_col)} AS unit_key, {m.sql} AS v FROM scope GROUP BY 1"
        bp, level, unit_label = list(m.params), f"{grain} totals", grain.capitalize()
        id_cols: list[str] = []
    elif p.group_by:
        gq = quote_ident(p.group_by[0])
        base = f"SELECT {gq} AS unit_key, {m.sql} AS v FROM scope GROUP BY 1"
        bp, level, unit_label = list(m.params), f"{ctx.label(p.group_by[0])} totals", ctx.label(p.group_by[0])
        id_cols = []
    else:
        col = _single_column(ctx)
        if not col:
            raise AppError(422, "unsupported", "Record-level outlier detection needs a metric based on one numeric column")
        id_cols = [c for c, meta in ctx.cols.items() if meta["semantic_type"] in ("identifier", "date", "dimension")][:6]
        sel = ", ".join(quote_ident(c) for c in id_cols)
        base = f"SELECT {sel + ', ' if sel else ''}{quote_ident(col)} AS v FROM scope WHERE {quote_ident(col)} IS NOT NULL"
        bp, level, unit_label = [], "individual records", "Record"
    if method == "iqr":
        stats_sql = "SELECT quantile_cont(v, 0.25) AS q1, quantile_cont(v, 0.75) AS q3, MEDIAN(v) AS med, COUNT(v) AS n FROM b"
        st = ctx.q("Quartiles", f"{scope}, b AS ({base}) {stats_sql}", sp + bp).rows[0]
        q1, q3, med, n = [_clean(x) for x in st]
        iqr = (q3 or 0) - (q1 or 0)
        lo, hi = q1 - k * iqr, q3 + k * iqr
        method_text = f"Interquartile range rule: values below Q1 − {k}×IQR ({lo:,.2f}) or above Q3 + {k}×IQR ({hi:,.2f})."
        score_sql = "ABS(v - ?) / NULLIF(?, 0)"
        score_p = [med, iqr]
    else:
        st = ctx.q("Mean and standard deviation", f"{scope}, b AS ({base}) SELECT AVG(v), STDDEV_SAMP(v), MEDIAN(v), COUNT(v) FROM b", sp + bp).rows[0]
        mean, sd, med, n = [_clean(x) for x in st]
        lo, hi = mean - k * (sd or 0), mean + k * (sd or 0)
        method_text = f"Z-score rule: |value − mean| > {k} standard deviations (mean {mean:,.2f}, sd {sd or 0:,.2f}). Assumes a roughly symmetric distribution."
        score_sql = "ABS(v - ?) / NULLIF(?, 0)"
        score_p = [mean, sd]
    cnt = ctx.q("Count outlier candidates", f"{scope}, b AS ({base}) SELECT COUNT(*), COUNT(*) FILTER (WHERE v > ?) FROM b WHERE v < ? OR v > ?",
                sp + bp + [hi, lo, hi]).rows[0]
    r = ctx.q("List outlier candidates", f"{scope}, b AS ({base}) SELECT *, {score_sql} AS deviation FROM b WHERE v < ? OR v > ? "
              f"ORDER BY deviation DESC NULLS LAST LIMIT ?", sp + bp + score_p + [lo, hi, p.limit])
    rows = [dict(zip(r.columns, [_clean(v) for v in row])) for row in r.rows]
    for row in rows:
        row["direction"] = "high" if row["v"] > hi else "low"
    vcol = {"key": "v", "label": m.label if level != "individual records" else ctx.label(_single_column(ctx)),
            "role": "measure", "unit": m.unit, "decimals": m.decimals}
    cols = ([{"key": "unit_key", "label": unit_label, "role": "dimension"}] if not id_cols and level != "individual records" else
            [{"key": c, "label": ctx.label(c), "role": "dimension"} for c in id_cols]) + [vcol,
            {"key": "direction", "label": "Direction", "role": "text"}, {"key": "deviation", "label": "Deviation score", "role": "number"}]
    ctx.notes.append("Outlier candidates are statistically unusual values. They are not necessarily errors, fraud or problems — review them in context.")
    return {"columns": cols, "rows": rows, "level": level, "method": method_text, "bounds": {"low": lo, "high": hi, "median": med},
            "kpis": [{"key": "count", "label": "Outlier candidates", "value": cnt[0], "unit": "count"},
                     {"key": "share", "label": f"Share of {level}", "value": cnt[0] / n * 100 if n else None, "unit": "pct"},
                     {"key": "high", "label": "Unusually high", "value": cnt[1], "unit": "count"},
                     {"key": "median", "label": "Typical (median) value", "value": med, "unit": m.unit, "decimals": m.decimals}],
            "chart": {"type": "scatter" if level == "individual records" else "bar", "x": cols[0]["key"], "y": ["v"]},
            "truncated": cnt[0] > len(rows)}


def _describe(ctx: Ctx) -> dict:
    rows = [{"column": c["display_name"], "name": c["name"], "type": c["dtype"], "semantic_type": c["semantic_type"],
             "meaning": c["business_meaning"], "missing": c["null_count"], "distinct": c["unique_count"]}
            for c in ctx.cols.values()]
    return {"columns": [{"key": "column", "label": "Column", "role": "dimension"}, {"key": "type", "label": "Type", "role": "text"},
                        {"key": "semantic_type", "label": "Role", "role": "text"}, {"key": "meaning", "label": "Business meaning", "role": "text"},
                        {"key": "missing", "label": "Missing", "role": "number"}, {"key": "distinct", "label": "Distinct values", "role": "number"}],
            "rows": rows, "chart": {"type": "table"},
            "kpis": [{"key": "rows", "label": "Rows", "value": ctx.version.row_count, "unit": "count"},
                     {"key": "cols", "label": "Columns", "value": len(rows), "unit": "count"}]}


INTENT_FN = {"aggregate": _aggregate, "rank": _grouped, "breakdown": _grouped, "compare_segments": _grouped,
             "contribution": _contribution, "trend": _trend, "compare_periods": lambda c: _compare(c, False),
             "decompose_change": lambda c: _compare(c, True), "distribution": _distribution, "outliers": _outliers,
             "describe_dataset": _describe}


# ----------------------------------------------------------------------------- execution + provenance
def _methodology(ctx: Ctx, result: dict) -> str:
    p = ctx.plan
    m = ctx.measures[0] if ctx.measures else None
    parts = [INTENT_LABELS[p.intent] + "."]
    if m:
        parts.append(f"Measure: {m.label} = {m.definition}.")
    if p.group_by:
        parts.append(f"Grouped by {', '.join(ctx.label(g) for g in p.group_by)}.")
    if p.intent in ("compare_periods", "decompose_change") and result.get("periods"):
        pr = result["periods"]
        parts.append(f"Current period {pr['current']['label']} compared with {pr['baseline']['label']} using {ctx.label(ctx.time_col)}.")
    if p.intent == "trend":
        parts.append(f"Values aggregated per {result.get('grain')} of {ctx.label(ctx.time_col)}.")
    if result.get("method"):
        parts.append(result["method"])
    if p.intent in ("rank", "breakdown") and "share_pct" in [c["key"] for c in result.get("columns", [])]:
        parts.append("Share of total = segment value ÷ total for all records in scope.")
    return " ".join(parts)


def _cache_key(ctx: Ctx) -> str:
    raw = json.dumps({"plan": ctx.plan.model_dump(mode="json"), "v": ctx.version.id,
                      "m": [m.metric["metric_version_id"] for m in ctx.measures if m.metric]}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def compute(db: DbSession, workspace_id: str, plan: AnalysisPlan, pin_version_id: str | None = None,
            pin_metrics: dict | None = None) -> tuple[Ctx, dict]:
    ctx = validate_plan(db, workspace_id, plan, pin_version_id, pin_metrics)
    key = _cache_key(ctx)
    if key in _RESULT_CACHE:
        _RESULT_CACHE.move_to_end(key)
        cached = json.loads(json.dumps(_RESULT_CACHE[key]))
        cached["provenance"]["cache_hit"] = True
        return ctx, cached
    result = INTENT_FN[plan.intent](ctx)
    if plan.intent != "describe_dataset":
        scope, sp = _scope(ctx, include_focus=plan.intent != "contribution",
                           time_range=plan.intent not in ("compare_periods", "decompose_change"))
        in_scope = result.get("rows_in_scope")
        if in_scope is None:
            in_scope = ctx.q("Count records in scope", f"{scope} SELECT COUNT(*) FROM scope", sp).rows[0][0]
    else:
        in_scope = ctx.version.row_count
    result.pop("rows_in_scope", None)
    if not result.get("rows") and plan.intent != "aggregate":
        result["empty"] = True
        ctx.notes.append("No records matched this analysis. Check the filters and date range.")
    if p_t := plan.time:
        tr = f"{p_t.start or 'start of data'} to {p_t.end or 'end of data'}" if (p_t.start or p_t.end) else "All dates"
    else:
        tr = "All dates" if plan.intent not in ("compare_periods", "decompose_change") else result.get("periods", {}).get("current", {}).get("label", "")
    result["notes"] = ctx.notes
    result["intent"] = plan.intent
    result["provenance"] = {
        "dataset": {"id": ctx.dataset.id, "name": ctx.dataset.name, "version_id": ctx.version.id,
                    "version_number": ctx.version.version_number, "total_rows": ctx.version.row_count,
                    "is_demo": ctx.dataset.is_demo},
        "records_in_scope": int(in_scope),
        "filters": [describe_filter(f, ctx.cols) for f in plan.filters] +
                   ([f"{ctx.label(plan.focus.column)} is one of {', '.join(plan.focus.values)}"] if plan.focus and plan.intent != "contribution" else []),
        "time_column": ctx.label(ctx.time_col) if ctx.time_col else None,
        "date_range": tr,
        "grouping": [ctx.label(g) for g in plan.group_by],
        "measures": [{"label": m.label, "definition": m.definition, "unit": m.unit, "aggregation_type": m.kind,
                      "source": "metric" if m.metric else "column"} for m in ctx.measures],
        "metrics": [m.metric for m in ctx.measures if m.metric],
        "methodology": _methodology(ctx, result),
        "queries": ctx.queries,
        "engine": f"DuckDB {duckdb.__version__} · isolated in-memory connection · external access disabled",
        "duration_ms": ctx.total_ms,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "cache_hit": False,
    }
    _RESULT_CACHE[key] = json.loads(json.dumps(result, default=str))
    while len(_RESULT_CACHE) > 200:
        _RESULT_CACHE.popitem(last=False)
    return ctx, result


def execute(db: DbSession, workspace_id: str, user_id: str, plan: AnalysisPlan, source: str, question: str = "",
            interpreter: str = "", plan_notes: list[str] | None = None, pin_version_id: str | None = None,
            pin_metrics: dict | None = None) -> AnalysisRun:
    """Validate, compute and persist a provenance record. Validation errors propagate (nothing is stored)."""
    ctx, result = compute(db, workspace_id, plan, pin_version_id, pin_metrics)
    run = AnalysisRun(workspace_id=workspace_id, user_id=user_id, dataset_id=ctx.dataset.id,
                      dataset_version_id=ctx.version.id,
                      metric_version_ids=[m.metric["metric_version_id"] for m in ctx.measures if m.metric],
                      source=source, question=question[:2000], interpreter=interpreter, plan=plan.model_dump(mode="json"),
                      plan_notes=plan_notes or [], status="succeeded", sql=";\n\n".join(q["sql"] for q in ctx.queries),
                      params=[q["params"] for q in ctx.queries], duration_ms=ctx.total_ms,
                      rows_scanned=result["provenance"]["records_in_scope"], result=json.loads(json.dumps(result, default=str)))
    db.add(run)
    db.flush()
    return run


def run_out(run: AnalysisRun) -> dict:
    return {"id": run.id, "dataset_id": run.dataset_id, "dataset_version_id": run.dataset_version_id, "plan": run.plan,
            "plan_notes": run.plan_notes, "interpreter": run.interpreter, "question": run.question, "status": run.status,
            "result": run.result, "created_at": run.created_at.isoformat(), "source": run.source}

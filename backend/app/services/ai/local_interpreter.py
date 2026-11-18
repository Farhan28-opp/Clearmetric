"""Deterministic local interpreter: natural-language question → structured AnalysisPlan.

This is rule-based language understanding (vocabulary matching against the dataset's schema, saved
metric names/synonyms and dimension values, plus intent patterns). It is NOT a generative model and
is labelled as such in the UI. It supports common business question patterns and asks for clarification
instead of guessing when a business definition is ambiguous."""
import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.services.ai.context import InterpretContext, MetricInfo

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}
ORDINALS = {"second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4,
            "first": 0, "top": 0, "highest": 0, "1st": 0}
ANALYTIC_WORDS = r"\b(revenue|sales|profit|margin|cost|orders?|customers?|products?|units|quantity|discount|price|total|average|count|data|dataset|columns?|metric|kpi|growth|trend|transactions?|records?|rows?|month|months|quarter|year|week|day|period|performed|performance|perform|sold|bought|purchased|spent|spend|earned|made)\b"
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
GRAINS = [(r"\b(daily|per day|by day|each day|day[- ]by[- ]day)\b", "day"), (r"\b(weekly|per week|by week|each week)\b", "week"),
          (r"\b(monthly|per month|by month|each month|month[- ]by[- ]month|every month)\b", "month"),
          (r"\b(quarterly|per quarter|by quarter|each quarter)\b", "quarter"),
          (r"\b(yearly|annual(ly)?|per year|by year|each year|year[- ]by[- ]year)\b", "year")]
MEANING_ALIASES = {
    "customer_id": ["customer", "customers", "client", "clients", "buyer", "buyers"], "customer": ["customer", "customers"],
    "product": ["product", "products", "item", "items"], "category": ["category", "categories", "product category", "product categories"],
    "region": ["region", "regions", "territory", "territories"], "channel": ["channel", "channels", "sales channel", "sales channels"],
    "order_id": ["order", "orders", "transaction", "transactions"], "segment": ["segment", "segments"],
    "country": ["country", "countries"], "city": ["city", "cities"],
}
GENERIC_REVENUE = {"revenue", "sales", "turnover", "income"}
UNKNOWN_CONCEPTS = ["churn", "retention", "conversion", "inventory", "stock level", "returns", "refund", "headcount",
                    "employee", "salary", "ad spend", "marketing spend", "website traffic", "visits", "sessions", "nps", "rating"]


@dataclass
class Interpretation:
    status: str  # plan | clarify | unsupported | describe
    plan: dict | None = None
    notes: list[str] = field(default_factory=list)
    message: str = ""
    clarification: dict | None = None
    interpreter: str = "local-deterministic"


def _singular(w: str) -> str:
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith("ses"):
        return w[:-2]
    return w[:-1] if w.endswith("s") and not w.endswith("ss") else w


def _phrase_in(phrase: str, text: str) -> int:
    """Position of whole-phrase match, or -1."""
    m = re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text)
    return m.start() if m else -1


class LocalInterpreter:
    def __init__(self, ctx: InterpretContext):
        self.ctx = ctx
        self.notes: list[str] = []

    # ------------------------------------------------------------------ vocabulary
    def _metric_phrases(self) -> list[tuple[str, MetricInfo]]:
        out = []
        for m in self.ctx.metrics:
            for p in {m.name.lower(), *m.synonyms}:
                out.append((p, m))
        return sorted(out, key=lambda x: -len(x[0]))

    def _column_aliases(self, col: str) -> list[str]:
        c = self.ctx.cols[col]
        names = {c["display_name"].lower(), c["original_name"].lower(), col.replace("_", " ")}
        names |= {_singular(n) for n in names} | {n + "s" for n in names if not n.endswith("s")}
        names |= set(MEANING_ALIASES.get(c["business_meaning"], []))
        if col.endswith("_id"):
            names.add(col[:-3].replace("_", " "))
        return sorted({n for n in names if len(n) > 1}, key=len, reverse=True)

    def _dimension_columns(self) -> list[str]:
        return [n for n, c in self.ctx.cols.items() if c["semantic_type"] in ("dimension", "identifier", "boolean")
                or (c["dtype"] == "string" and c["unique_count"] <= 1000)]

    def _measure_columns(self) -> list[str]:
        return [n for n, c in self.ctx.cols.items() if c["dtype"] in ("integer", "float") and c["semantic_type"] in ("measure", "currency")]

    def _date_columns(self) -> list[str]:
        return [n for n, c in self.ctx.cols.items() if c["dtype"] in ("date", "datetime")]

    # ------------------------------------------------------------------ main
    def interpret(self, question: str) -> Interpretation:
        q = " " + re.sub(r"[?!.,;:]+(\s|$)", " ", question.lower()).replace("’", "'") + " "
        q = re.sub(r"\s+", " ", q)
        prev = self.ctx.previous

        if self._is_describe(q):
            return Interpretation("describe", message="describe")

        filters, consumed = self._value_filters(q)
        q_wo_values = q
        for span in consumed:
            q_wo_values = q_wo_values.replace(span, " ")
        time_spec, grain = self._time(q)
        refs = self._references(q)
        self.measure_phrase = ""
        measure, clar = self._measure(q_wo_values, prev)
        if clar:
            return clar
        q_dims = q_wo_values.replace(self.measure_phrase, " ") if self.measure_phrase else q_wo_values
        dims = self._dimensions(q_dims, filters)
        intent = self._intent(q, dims, grain, refs)
        if measure is None and not dims and not filters and not time_spec and not grain and not refs \
                and not re.search(ANALYTIC_WORDS, q):
            unknown = next((u for u in UNKNOWN_CONCEPTS if u in q), None)
            return self._unknown_concept(unknown) if unknown else Interpretation("unsupported", message=self._out_of_scope())

        if intent is None:
            if prev and (filters or time_spec or grain or refs or len(q.split()) <= 7) and self._looks_like_followup(q):
                return self._modify_previous(q, prev, filters, time_spec, grain, measure, dims)
            unknown = next((u for u in UNKNOWN_CONCEPTS if u in q), None)
            if unknown:
                return self._unknown_concept(unknown)
            if measure is None and not dims:
                return Interpretation("unsupported", message=self._out_of_scope())
            intent = "rank" if dims and self._has_superlative(q) else "breakdown" if dims else "aggregate"

        if intent == "outliers" and measure and measure.get("kind") == "metric" and \
                self.measure_phrase in ("transactions", "orders", "order count", "records", "number of orders"):
            measure = None  # "unusual transactions" = unusual transaction values, not a count of transactions
        unknown = next((u for u in UNKNOWN_CONCEPTS if u in q), None)
        if unknown and measure is None:
            return self._unknown_concept(unknown)

        # Measures: explicit > carried over from previous turn > workspace primary
        if measure is None:
            if prev and prev.plan.get("measures") and (refs or self._looks_like_followup(q)):
                measure = prev.plan["measures"][0]
                self.notes.append(f"Using {prev.measure_label or 'the same measure'} from the previous question.")
            else:
                measure, clar = self._default_measure(q, intent)
                if clar:
                    return clar
        if measure is None and intent != "describe_dataset":
            return self._ask_measure()

        # Dimensions from references or previous turn
        focus = None
        if refs and prev and prev.dimension and prev.ordered_values:
            vals = self._resolve_refs(refs, prev)
            if vals:
                focus = {"column": prev.dimension, "values": vals}
                if not dims:
                    dims = [prev.dimension]
                label = self.ctx.cols.get(prev.dimension, {}).get("display_name", prev.dimension)
                self.notes.append(f"Resolved the reference to {label}: {', '.join(vals)} (from the previous result).")
        elif refs and not prev:
            return Interpretation("clarify", message="I'm not sure what “" + refs[0]["word"] + "” refers to. Could you name the items you mean?",
                                  clarification={"question": "Which items do you mean?", "options": []})

        group_by = dims[:2]
        plan: dict = {"intent": intent, "dataset_id": self.ctx.dataset.id, "measures": [measure], "group_by": [],
                      "filters": filters, "limit": 50, "visualization": "auto", "options": {}}
        date_col = self._date_column(measure)
        if isinstance(date_col, Interpretation):
            if intent in ("trend", "compare_periods", "decompose_change") or time_spec or grain:
                return date_col
            date_col = None

        if intent in ("rank", "breakdown", "contribution", "compare_segments", "decompose_change", "distribution") and not group_by:
            if intent == "distribution":
                pass  # histogram of a single numeric measure
            elif intent == "decompose_change":
                return self._ask_dimension(question, "Which dimension should I break the change down by?")
            elif prev and prev.dimension and intent in ("contribution", "compare_segments"):
                group_by = [prev.dimension]
            else:
                return self._ask_dimension(question, "Which dimension should I use?")

        if intent == "trend":
            plan["time"] = {"column": date_col, "grain": grain or "month"}
            plan["group_by"] = group_by[:1]
            plan["visualization"] = "line"
            plan["limit"] = 500
        elif intent in ("compare_periods", "decompose_change"):
            plan["comparison"] = self._comparison(q, grain)
            plan["time"] = {"column": date_col}
            plan["group_by"] = group_by[:1]
            plan["visualization"] = "waterfall" if intent == "decompose_change" else "bar"
            direction = "decrease" if re.search(r"\b(decline|decrease|drop|fall|fell|lower|loss|down|shrink)", q) else \
                "increase" if re.search(r"\b(increase|growth|grow|rise|rose|gain|up)\b", q) else "any"
            plan["options"]["expected_direction"] = direction
            plan["limit"] = 50
        elif intent == "outliers":
            group_by = [g for g in group_by if self.ctx.cols[g]["semantic_type"] != "identifier"]
            plan["group_by"] = group_by[:1] if not grain else []
            if grain:
                plan["time"] = {"column": date_col, "grain": grain}
            plan["options"]["outlier_method"] = "zscore" if re.search(r"z[- ]?score|standard deviation", q) else "iqr"
            plan["options"]["outlier_threshold"] = 3.0 if plan["options"]["outlier_method"] == "zscore" or not grain else 1.5
            plan["limit"] = 25
        elif intent == "distribution":
            plan["group_by"] = group_by[:1]
            plan["visualization"] = "donut" if group_by else "histogram"
        else:
            plan["group_by"] = group_by
            if intent == "rank":
                plan["limit"] = self._number(q) or 10
                plan["sort"] = {"by": "value", "direction": "asc" if self._ascending(q) else "desc"}
                plan["visualization"] = "hbar"
            elif intent == "contribution":
                plan["limit"] = self._number(q) or 10
                plan["visualization"] = "donut"
            elif intent == "compare_segments":
                plan["limit"] = 50
                plan["visualization"] = "bar"
            else:
                plan["limit"] = self._number(q) or 50
                plan["visualization"] = "bar"
        if focus and intent != "trend":
            plan["focus"] = focus
            if intent == "rank":
                plan["intent"] = "compare_segments"
        elif focus and intent == "trend":
            plan["focus"] = focus
        if time_spec and intent not in ("compare_periods", "decompose_change"):
            plan.setdefault("time", {"column": date_col})
            plan["time"].update(time_spec)
        elif time_spec and intent in ("compare_periods", "decompose_change") and "current" in time_spec:
            plan["comparison"].update({"current": time_spec["current"]})
        if self.ctx.previous_dataset_changed:
            self.notes.append("The dataset has a newer version than earlier answers in this conversation; this answer uses the current version.")
        return Interpretation("plan", plan=plan, notes=self.notes)

    # ------------------------------------------------------------------ pieces
    def _is_describe(self, q: str) -> bool:
        return bool(re.search(r"what (columns|fields)|which (columns|fields)|list (the |all )?(columns|fields)|what (type|kind)s? of (information|data)"
                              r"|what (information|data) (is|does)|what can i (analy[sz]e|ask)|describe (the|this|my) (data|dataset)"
                              r"|(metrics|measures) (are|is) (unavailable|missing|not available)|what('s| is) in (this|the|my) (data|dataset)"
                              r"|which (important )?(business )?metrics (are )?(unavailable|missing)", q))

    def _value_filters(self, q: str) -> tuple[list[dict], list[str]]:
        found: dict[str, list[str]] = {}
        consumed = []
        pairs = sorted(((v, col) for col, vals in self.ctx.values.items() for v in vals if len(v) >= 2), key=lambda x: -len(x[0]))
        taken = q
        for value, col in pairs:
            vl = value.lower()
            if vl in ("other", "all", "none", "total", "others", "yes", "no"):
                continue
            pos = _phrase_in(vl, taken)
            if pos >= 0:
                found.setdefault(col, []).append(value)
                consumed.append(vl)
                taken = taken[:pos] + " " * len(vl) + taken[pos + len(vl):]
        filters = [{"column": c, "op": "eq" if len(v) == 1 else "in", "value": v[0] if len(v) == 1 else v} for c, v in found.items()]
        # numeric conditions: "<measure> over 500"
        for col in self._measure_columns():
            for alias in self._column_aliases(col):
                m = re.search(re.escape(alias) + r"\s+(?:is\s+|of\s+)?(over|above|greater than|more than|at least|under|below|less than|at most|>=|<=|>|<)\s+\$?([\d,]+(?:\.\d+)?)", q)
                if m:
                    op = {"over": "gt", "above": "gt", "greater than": "gt", "more than": "gt", ">": "gt", "at least": "gte", ">=": "gte",
                          "under": "lt", "below": "lt", "less than": "lt", "<": "lt", "at most": "lte", "<=": "lte"}[m.group(1)]
                    filters.append({"column": col, "op": op, "value": float(m.group(2).replace(",", ""))})
                    consumed.append(m.group(0))
                    break
        if filters:
            self.notes.append("Filters detected: " + "; ".join(
                f"{self.ctx.cols[f['column']]['display_name']} {'=' if f['op'] == 'eq' else f['op']} {f['value']}" for f in filters))
        return filters, consumed

    def _time(self, q: str) -> tuple[dict | None, str | None]:
        grain = next((g for pat, g in GRAINS if re.search(pat, q)), None)
        a = self.ctx.anchor_date
        spec = None
        if a:
            def month_range(y, m):
                return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
            if re.search(r"\b(this|current) month\b", q):
                s, e = month_range(a.year, a.month)
                spec = {"start": s, "end": e}
            elif re.search(r"\b(last|previous|prior) month\b", q) and not re.search(r"(compare|vs|versus|than|with)", q):
                pm = a.replace(day=1) - timedelta(days=1)
                s, e = month_range(pm.year, pm.month)
                spec = {"start": s, "end": e}
            elif m := re.search(r"\b(last|past|previous) (\d+|" + "|".join(NUM_WORDS) + r") (days|weeks|months)\b", q):
                n = int(m.group(2)) if m.group(2).isdigit() else NUM_WORDS[m.group(2)]
                days = n * {"days": 1, "weeks": 7, "months": 30.4}[m.group(3)]
                spec = {"start": a - timedelta(days=int(days) - 1), "end": a}
            elif re.search(r"\b(this year|year to date|ytd)\b", q):
                spec = {"start": date(a.year, 1, 1), "end": a}
            elif re.search(r"\blast year\b", q) and not re.search(r"(compare|vs|versus|than|year over year)", q):
                spec = {"start": date(a.year - 1, 1, 1), "end": date(a.year - 1, 12, 31)}
            if spec:
                self.notes.append(f"Relative dates are anchored to the latest date in the data ({a.strftime('%d %b %Y')}).")
        if not spec:
            m = re.search(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\s+(20\d\d)\b", q)
            qm = re.search(r"\bq([1-4])\s*(20\d\d)\b", q)
            ym = re.search(r"\b(in|during|for|of)\s+(20\d\d)\b", q)
            between = re.search(r"between (\d{4}-\d{2}-\d{2}) and (\d{4}-\d{2}-\d{2})", q)
            if between:
                spec = {"start": date.fromisoformat(between.group(1)), "end": date.fromisoformat(between.group(2))}
            elif m:
                y, mo = int(m.group(2)), MONTHS[m.group(1)]
                spec = {"start": date(y, mo, 1), "end": date(y, mo, calendar.monthrange(y, mo)[1])}
            elif qm:
                y, qn = int(qm.group(2)), int(qm.group(1))
                sm = (qn - 1) * 3 + 1
                spec = {"start": date(y, sm, 1), "end": date(y, sm + 2, calendar.monthrange(y, sm + 2)[1])}
            elif ym:
                y = int(ym.group(2))
                spec = {"start": date(y, 1, 1), "end": date(y, 12, 31)}
        if spec:
            spec = {k: v.isoformat() for k, v in spec.items()}
        return spec, grain

    def _references(self, q: str) -> list[dict]:
        refs = []
        for m in re.finditer(r"\b(its|it|that|this one|their|they|them|these|those|the (second|third|fourth|fifth|2nd|3rd|4th|5th)[- ](highest|largest|best|biggest|top|ranked|place|one)?|"
                             r"(second|third|2nd|3rd)[- ](highest|largest|best|biggest|ranked)|the (top|highest|best|first|leading) one|the (lowest|last|bottom|worst) one|the (top|first) (\d+|"
                             + "|".join(NUM_WORDS) + r"))\b", q):
            w = m.group(0)
            if w in ("it", "that", "this one") and not re.search(r"\b(compare|contribut|share|what about|how about|and|its)\b", q):
                continue
            refs.append({"word": w, "pos": m.start()})
        return refs

    def _resolve_refs(self, refs: list[dict], prev) -> list[str]:
        vals: list[str] = []
        ordered = [v for v in prev.ordered_values if v not in ("All other", None)]
        for r in refs:
            w = r["word"]
            if w in ("their", "they", "them", "these", "those"):
                for v in ordered[: (prev.plan.get("limit") or len(ordered))]:
                    if v not in vals:
                        vals.append(v)
                continue
            m = re.search(r"(top|first) (\d+|" + "|".join(NUM_WORDS) + ")", w)
            if m:
                n = int(m.group(2)) if m.group(2).isdigit() else NUM_WORDS[m.group(2)]
                vals += [v for v in ordered[:n] if v not in vals]
                continue
            idx = 0
            for word, i in ORDINALS.items():
                if re.search(r"\b" + word + r"\b", w):
                    idx = i
                    break
            if re.search(r"lowest|last|bottom|worst", w):
                idx = len(ordered) - 1
            if 0 <= idx < len(ordered) and ordered[idx] not in vals:
                vals.append(ordered[idx])
        return vals

    def _dimensions(self, q: str, filters: list[dict]) -> list[str]:
        hits = []
        filtered = {f["column"] for f in filters}
        for col in self._dimension_columns():
            for alias in self._column_aliases(col):
                pos = _phrase_in(alias, q)
                if pos >= 0:
                    # "how many orders" / "number of customers" is a count, not a grouping
                    before = q[max(0, pos - 22):pos]
                    if re.search(r"(how many|number of|count of|count|distinct)\s+(unique\s+|distinct\s+)?$", before):
                        break
                    if col in filtered and not re.search(r"(by|per|each|across|which|every|all|compare)\s+(the\s+)?$", q[max(0, pos - 12):pos]):
                        break
                    hits.append((pos, col))
                    break
        # A dimension is named by a measure alias too ("customers" vs Customer Count): prefer grouping words
        hits.sort()
        return [c for _, c in hits]

    def _measure(self, q: str, prev) -> tuple[dict | None, Interpretation | None]:
        agg = "avg" if re.search(r"\b(average|avg|mean)\b", q) else "median" if "median" in q else None
        # 1. saved metrics by name / synonym (longest phrase first)
        hits: list[tuple[int, MetricInfo, str]] = []
        for phrase, m in self._metric_phrases():
            pos = _phrase_in(phrase, q)
            if pos >= 0 and not any(phrase in h[2] for h in hits):
                before = q[max(0, pos - 12):pos]
                if m.unit == "count" and re.search(r"(which|by|per|each|across|top|the)\s+$", before) and phrase in ("customers", "orders", "transactions"):
                    continue
                hits.append((pos, m, phrase))
        hits.sort(key=lambda h: (h[0], not h[1].verified))
        if hits:
            m = hits[0][1]
            self.measure_phrase = hits[0][2]
            if agg and m.unit == "currency" and m.kind == "additive" and m.columns and len(m.columns) == 1:
                aov = next((x for x in self.ctx.metrics if "average order" in x.name.lower()), None)
                if aov and re.search(r"\b(order|transaction) value\b", q):
                    return {"kind": "metric", "metric_id": aov.id}, None
                self.notes.append(f"Averaging {self.ctx.cols[m.columns[0]]['display_name']} per record.")
                return {"kind": "column", "column": m.columns[0], "aggregation": agg}, None
            if not m.verified:
                self.notes.append(f"'{m.name}' is not yet verified in the Metric Library.")
            return {"kind": "metric", "metric_id": m.id}, None
        # 2. generic revenue terms → ambiguity handling
        generic = next((g for g in GENERIC_REVENUE if _phrase_in(g, q) >= 0), None)
        if generic:
            rev_metrics = [m for m in self.ctx.metrics if "revenue" in m.name.lower() and m.unit == "currency" and "average" not in m.name.lower()]
            verified = [m for m in rev_metrics if m.verified]
            pool = verified or rev_metrics
            if len(pool) == 1:
                self.notes.append(f"Interpreted “{generic}” as the verified metric {pool[0].name}.")
                return {"kind": "metric", "metric_id": pool[0].id}, None
            if len(pool) > 1:
                if prev and prev.used_metric_ids:
                    match = next((m for mid in prev.used_metric_ids for m in pool if m.id == mid), None)
                    if match:
                        self.notes.append(f"Interpreted “{generic}” as {match.name}, the revenue definition already used in this investigation.")
                        return {"kind": "metric", "metric_id": match.id}, None
                names = " or ".join(m.name.lower() for m in pool[:3])
                return None, Interpretation("clarify", message=f"Do you mean {names}?", clarification={
                    "question": f"Do you mean {names}?", "kind": "measure",
                    "options": [{"label": m.name, "measure": {"kind": "metric", "metric_id": m.id}, "description": m.formula} for m in pool]})
            cols = [c for c in self._measure_columns() if self.ctx.cols[c]["business_meaning"] in ("net_revenue", "gross_revenue", "revenue")]
            if len(cols) == 1:
                self.notes.append(f"No revenue metric is defined; using the column {self.ctx.cols[cols[0]]['display_name']}.")
                return {"kind": "column", "column": cols[0], "aggregation": agg or "sum"}, None
            if len(cols) > 1:
                return None, Interpretation("clarify", message="Which column represents the revenue you mean?", clarification={
                    "question": "Which column represents the revenue you mean?", "kind": "measure",
                    "options": [{"label": self.ctx.cols[c]["display_name"], "measure": {"kind": "column", "column": c, "aggregation": "sum"}} for c in cols]})
        # 3. margin without a margin metric
        if re.search(r"\b(profit )?margin\b", q):
            return None, self._margin_clarification()
        # 4. numeric columns by name
        for col in self._measure_columns():
            for alias in self._column_aliases(col):
                if _phrase_in(alias, q) >= 0:
                    a = agg or ("max" if re.search(r"\b(maximum|max|largest single|biggest single)\b", q) else
                                "min" if re.search(r"\b(minimum|min|smallest single)\b", q) else "sum")
                    return {"kind": "column", "column": col, "aggregation": a}, None
        # 5. counts
        if re.search(r"\b(how many|number of|count of|count)\b", q):
            for col in self._dimension_columns():
                for alias in self._column_aliases(col):
                    if re.search(r"(how many|number of|count of|count)\s+(unique\s+|distinct\s+)?" + re.escape(alias) + r"\b", q):
                        return {"kind": "column", "column": col, "aggregation": "count_distinct"}, None
            if re.search(r"\b(rows|records|lines|entries)\b", q):
                return {"kind": "count_rows"}, None
        return None, None

    def _default_measure(self, q: str, intent: str) -> tuple[dict | None, Interpretation | None]:
        if intent == "describe_dataset":
            return None, None
        if re.search(r"\b(units|quantity|sold the most units)\b", q):
            m = next((x for x in self.ctx.metrics if x.name.lower() == "units sold"), None)
            if m:
                return {"kind": "metric", "metric_id": m.id}, None
        if re.search(r"\b(purchased|bought|spent|spend|sold|sales|performed|generated|contribute|brought)\b", q) or intent in (
                "rank", "breakdown", "contribution", "trend", "compare_periods", "decompose_change", "outliers", "distribution", "compare_segments"):
            rev = [m for m in self.ctx.metrics if m.verified and "revenue" in m.name.lower() and "average" not in m.name.lower()]
            net = next((m for m in rev if "net" in m.name.lower()), None)
            if len(rev) == 1 or net:
                chosen = net or rev[0]
                self.notes.append(f"No measure was named; using the verified metric {chosen.name}.")
                return {"kind": "metric", "metric_id": chosen.id}, None
            if len(rev) > 1:
                return None, Interpretation("clarify", message="Which measure should I use?", clarification={
                    "question": "Which measure should I use?", "kind": "measure",
                    "options": [{"label": m.name, "measure": {"kind": "metric", "metric_id": m.id}} for m in rev]})
        return None, None

    def _intent(self, q: str, dims: list[str], grain: str | None, refs: list[dict]) -> str | None:
        if re.search(r"\b(unusual|outliers?|anomal\w*|abnormal|differ\w* (substantially|significantly)|suspicious|irregular|strange|spikes?)\b", q):
            return "outliers"
        if re.search(r"\b(contribut\w*|drove|driv\w*|explain\w*|caus\w*|responsible|account\w* for|behind|why did)\b", q) and \
                re.search(r"\b(decline|decrease|drop|fall|fell|increase|growth|rise|rose|change|gain|loss|dip)\b", q):
            return "decompose_change"
        if re.search(r"\b(month[- ]over[- ]month|mom|year[- ]over[- ]year|yoy|quarter[- ]over[- ]quarter|qoq|week[- ]over[- ]week)\b", q) or \
                re.search(r"\b(compare|compared|vs|versus|against)\b.*\b(previous|last|prior|this|same) (month|quarter|year|week|period)\b", q) or \
                re.search(r"\b(this|current) (month|quarter|year|week)\b.*\b(previous|last|prior) (month|quarter|year|week)\b", q):
            return "compare_periods"
        if re.search(r"\b(contribut\w*|share of|percentage of|percent of|proportion|portion|% of)\b", q):
            return "contribution"
        if re.search(r"\b(distribut\w*|histogram|spread|range of values)\b", q):
            return "distribution"
        if grain or re.search(r"\b(over time|trend\w*|time series|changed over|how has .* changed|how did .* change|which (month|quarter|year|week|day) (performed|was|had)|(best|worst|highest|lowest) (month|quarter|year|week|day))\b", q):
            return "trend"
        if re.search(r"\b(compare|comparison|versus|vs)\b", q) and (dims or refs):
            return "compare_segments" if refs or not self._has_superlative(q) else "rank"
        if dims and self._has_superlative(q):
            return "rank"
        if dims and re.search(r"\b(by|per|across|for each|each|breakdown|break down|split|among|every)\b", q):
            return "breakdown"
        if re.search(r"\b(what is|what's|what was|how much|how many|total|calculate|show me|give me|tell me)\b", q):
            return "aggregate" if not dims else "breakdown"
        return None

    def _has_superlative(self, q: str) -> bool:
        return bool(re.search(r"\b(top|bottom|highest|lowest|best|worst|most|least|largest|smallest|biggest|leading|rank\w*|which)\b", q))

    def _ascending(self, q: str) -> bool:
        return bool(re.search(r"\b(bottom|lowest|worst|least|smallest|weakest|fewest)\b", q))

    def _number(self, q: str) -> int | None:
        m = re.search(r"\b(top|bottom|first|best|worst|largest|highest|lowest|biggest|smallest|leading)\s+(\d+|" + "|".join(NUM_WORDS) + r")\b", q) or \
            re.search(r"\b(\d+|" + "|".join(NUM_WORDS) + r")\s+(\w+\s+)?(products|customers|regions|categories|items|channels|countries|cities|segments|stores)\b", q)
        if not m:
            return None
        tok = m.group(2) if m.re.pattern.startswith(r"\b(top") else m.group(1)
        n = int(tok) if tok.isdigit() else NUM_WORDS.get(tok)
        return max(1, min(n, 100)) if n else None

    def _date_column(self, measure: dict | None):
        dates = self._date_columns()
        if measure and measure.get("kind") == "metric":
            m = next((x for x in self.ctx.metrics if x.id == measure["metric_id"]), None)
            if m and m.date_column in dates:
                return m.date_column
        confirmed = [d for d in dates if self.ctx.cols[d]["business_meaning"] == "order_date"]
        if len(dates) == 1:
            return dates[0]
        if len(confirmed) == 1:
            return confirmed[0]
        if not dates:
            return Interpretation("unsupported", message="This dataset has no date column, so time-based analysis is not possible.")
        return Interpretation("clarify", message="Which date column should I use?", clarification={
            "question": "Which date column should I use?", "kind": "date_column",
            "options": [{"label": self.ctx.cols[d]["display_name"], "time_column": d} for d in dates]})

    def _comparison(self, q: str, grain: str | None) -> dict:
        g = "year" if re.search(r"\b(year[- ]over[- ]year|yoy|last year|previous year|annual)\b", q) and not re.search(r"\bsame (month|quarter) last year\b", q) else \
            "quarter" if re.search(r"\b(quarter|qoq)\b", q) else "week" if re.search(r"\bweek", q) else grain if grain in ("day",) else "month"
        mode = "previous_year" if re.search(r"\bsame (month|quarter|week) last year\b", q) else "previous_period"
        return {"mode": mode, "grain": g}

    def _looks_like_followup(self, q: str) -> bool:
        return bool(re.search(r"^\s*(and|what about|how about|now|same|also|only|just|for|in|but|then|break|split|instead|filter)\b", q))

    def _modify_previous(self, q, prev, filters, time_spec, grain, measure, dims) -> Interpretation:
        plan = {k: v for k, v in prev.plan.items()}
        plan["filters"] = [f for f in plan.get("filters", []) if f["column"] not in {x["column"] for x in filters}] + filters
        if measure:
            plan["measures"] = [measure]
        if dims and plan.get("intent") not in ("trend",):
            plan["group_by"] = dims[:1]
        if grain and plan.get("time"):
            plan["time"] = {**plan["time"], "grain": grain}
        if time_spec and plan.get("intent") not in ("compare_periods", "decompose_change"):
            dc = self._date_column(measure or plan["measures"][0])
            if isinstance(dc, Interpretation):
                return dc
            plan["time"] = {**(plan.get("time") or {"column": dc}), **time_spec}
        plan.pop("focus", None)
        self.notes.append("Treated this as a follow-up: reused the previous analysis and applied the new conditions.")
        return Interpretation("plan", plan=plan, notes=self.notes)

    def _margin_clarification(self) -> Interpretation:
        profit = next((c for c in self._measure_columns() if self.ctx.cols[c]["business_meaning"] == "profit"), None)
        revs = [c for c in self._measure_columns() if self.ctx.cols[c]["business_meaning"] in ("net_revenue", "gross_revenue", "revenue")]
        if not profit or not revs:
            return Interpretation("unsupported", message="Profit margin needs confirmed profit and revenue columns. Confirm them in "
                                  "Data Hub → Business terms, or define a Profit Margin metric in the Metric Library.")
        return Interpretation("clarify", message="There is no Profit Margin metric yet. Should I calculate profit margin using net revenue or gross revenue?",
                              clarification={"question": "Should I calculate profit margin using net revenue or gross revenue?", "kind": "create_metric",
                                             "options": [{"label": f"Profit ÷ {self.ctx.cols[r]['display_name']}",
                                                          "create_metric": {"name": "Profit Margin", "formula": f"SUM({profit}) / SUM({r})",
                                                                            "unit": "percent", "category": "Profitability"}} for r in revs]})

    def _ask_dimension(self, question: str, prompt: str) -> Interpretation:
        dims = [d for d in self._dimension_columns() if self.ctx.cols[d]["semantic_type"] == "dimension"][:6]
        return Interpretation("clarify", message=prompt, clarification={
            "question": prompt, "kind": "dimension",
            "options": [{"label": self.ctx.cols[d]["display_name"], "group_by": d} for d in dims]})

    def _ask_measure(self) -> Interpretation:
        opts = [{"label": m.name, "measure": {"kind": "metric", "metric_id": m.id}} for m in self.ctx.metrics[:6]]
        opts += [{"label": self.ctx.cols[c]["display_name"], "measure": {"kind": "column", "column": c, "aggregation": "sum"}}
                 for c in self._measure_columns()[: max(0, 6 - len(opts))]]
        return Interpretation("clarify", message="Which measure should I use?", clarification={"question": "Which measure should I use?",
                                                                                              "kind": "measure", "options": opts})

    def _unknown_concept(self, concept: str) -> Interpretation:
        available = [m.name for m in self.ctx.metrics][:8] or [self.ctx.cols[c]["display_name"] for c in self._measure_columns()][:8]
        return Interpretation("unsupported", message=f"This dataset doesn't contain information about {concept}. "
                              f"Measures available here include: {', '.join(available)}.")

    def _out_of_scope(self) -> str:
        return (f"I can only answer questions about the data in “{self.ctx.dataset.name}”. Try asking about totals, rankings, "
                "trends over time, comparisons between periods or segments, contributions, distributions or unusual records.")

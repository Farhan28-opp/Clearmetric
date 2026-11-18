"""Template-based explanation of computed results. Every number in the text is read from the result
object; nothing is estimated. Observations are labelled as computed; suggestions are labelled as such."""
from app.services.analytics.format import fmt_pct, fmt_value


def plural(label: str) -> str:
    l = label.lower()
    if l.endswith("s"):
        return l
    if l.endswith("y") and not l.endswith(("ay", "ey", "oy")):
        return l[:-1] + "ies"
    return l + "s"


class Narrator:
    def __init__(self, currency: str):
        self.cur = currency

    def v(self, value, unit="number", decimals=2) -> str:
        if unit == "pct":
            return "—" if value is None else f"{value:.1f}%"
        if unit == "percent_points":
            return "—" if value is None else f"{value * 100:+.1f} pp"
        return fmt_value(value, unit, self.cur, decimals)

    def narrate(self, plan: dict, result: dict) -> dict:
        intent = result.get("intent") or plan["intent"]
        if result.get("empty"):
            return {"answer": "No records matched this analysis, so there is nothing to calculate. Try widening the filters or date range.",
                    "observations": [], "follow_ups": []}
        fn = getattr(self, f"_{intent}", None)
        out = fn(plan, result) if fn else {"answer": "The analysis completed.", "observations": []}
        out.setdefault("follow_ups", self._follow_ups(plan, result))
        return out

    def _mcol(self, result, key="m0"):
        return next((c for c in result["columns"] if c["key"] == key), {"label": "Value", "unit": "number", "decimals": 2})

    def _dim(self, result):
        return next((c for c in result["columns"] if c["role"] == "dimension"), None)

    def _aggregate(self, plan, result):
        parts = [f"{k['label']}: {self.v(k['value'], k['unit'], k.get('decimals', 2))}" for k in result.get("kpis", [])]
        recs = result["provenance"]["records_in_scope"]
        if len(parts) == 1:
            k = result["kpis"][0]
            return {"answer": f"{k['label']} is {self.v(k['value'], k['unit'], k.get('decimals', 2))}.",
                    "observations": [f"Calculated over {recs:,} records ({result['provenance']['date_range'].lower() if result['provenance']['date_range'] == 'All dates' else result['provenance']['date_range']})."]}
        return {"answer": "; ".join(parts) + ".", "observations": [f"Calculated over {recs:,} records."]}

    def _ranked_text(self, rows, dim, m, n=5):
        return ", ".join(f"{r[dim['key']]} ({self.v(r[m['key']], m.get('unit'), m.get('decimals', 2))})" for r in rows[:n])

    def _rank(self, plan, result):
        rows, dim, m = result["rows"], self._dim(result), self._mcol(result)
        if not rows:
            return {"answer": "No results.", "observations": []}
        asc = plan.get("sort", {}).get("direction") == "asc"
        top = rows[0]
        word = "lowest" if asc else "highest"
        share = f" ({top['share_pct']:.1f}% of the total)" if top.get("share_pct") is not None else ""
        n = len(rows)
        if n == 1 or plan.get("limit", 10) == 1:
            answer = f"{top[dim['key']]} has the {word} {m['label']}: {self.v(top[m['key']], m.get('unit'), m.get('decimals', 2))}{share}."
        else:
            answer = (f"The {'bottom' if asc else 'top'} {n} {plural(dim['label'])} by {m['label']} are "
                      f"{self._ranked_text(rows, dim, m, n)}. {top[dim['key']]} ranks first{share}.")
        obs = []
        if len(rows) >= 2 and rows[1][m["key"]]:
            gap = (top[m["key"]] - rows[1][m["key"]]) / abs(rows[1][m["key"]]) * 100
            obs.append(f"{top[dim['key']]} is {abs(gap):.1f}% {'below' if gap < 0 else 'above'} the next {dim['label'].lower()}, {rows[1][dim['key']]}.")
        if rows[0].get("share_pct") is not None:
            comb = sum(r.get("share_pct") or 0 for r in rows)
            obs.append(f"Together these {n} account for {comb:.1f}% of total {m['label']} (out of {result.get('total_groups', n)} {plural(dim['label'])}).")
        return {"answer": answer, "observations": obs}

    def _breakdown(self, plan, result):
        rows, dim, m = result["rows"], self._dim(result), self._mcol(result)
        if not rows:
            return {"answer": "No results.", "observations": []}
        hi, lo = rows[0], min(rows, key=lambda r: r[m["key"]] if r[m["key"]] is not None else float("inf"))
        answer = (f"{m['label']} by {dim['label'].lower()}: {self._ranked_text(rows, dim, m, 8)}"
                  f"{' and others' if len(rows) > 8 else ''}.")
        obs = [f"Highest: {hi[dim['key']]} ({self.v(hi[m['key']], m.get('unit'), m.get('decimals', 2))}); lowest: {lo[dim['key']]} ({self.v(lo[m['key']], m.get('unit'), m.get('decimals', 2))})."]
        if hi.get("share_pct") is not None:
            obs.append(f"{hi[dim['key']]} represents {hi['share_pct']:.1f}% of the total.")
        if result.get("truncated"):
            obs.append(f"Showing {len(rows)} of {result['total_groups']} groups.")
        return {"answer": answer, "observations": obs}

    def _compare_segments(self, plan, result):
        rows, dim, m = result["rows"], self._dim(result), self._mcol(result)
        if len(rows) < 2:
            return self._breakdown(plan, result)
        a, b = rows[0], rows[1]
        if plan.get("focus"):
            order = [v.lower() for v in plan["focus"]["values"]]
            rows = sorted(rows, key=lambda r: order.index(str(r[dim["key"]]).lower()) if str(r[dim["key"]]).lower() in order else 99)
            a, b = rows[0], rows[1]
        va, vb = a[m["key"]], b[m["key"]]
        diff = (va - vb) if va is not None and vb is not None else None
        unit = m.get("unit")
        diff_txt = self.v(abs(diff) if diff is not None else None, "percent_points").lstrip("+") if unit == "percent" else self.v(abs(diff) if diff is not None else None, unit, m.get("decimals", 2))
        rel = f" ({abs(diff / vb * 100):.1f}% {'higher' if diff > 0 else 'lower'})" if diff is not None and vb and unit != "percent" else ""
        answer = (f"{a[dim['key']]}: {m['label']} {self.v(va, unit, m.get('decimals', 2))} vs {b[dim['key']]}: "
                  f"{self.v(vb, unit, m.get('decimals', 2))}. {a[dim['key']]} is {'higher' if (diff or 0) > 0 else 'lower'} by {diff_txt}{rel}.")
        obs = [f"{r[dim['key']]}: {self.v(r[m['key']], unit, m.get('decimals', 2))}" for r in rows[2:6]]
        return {"answer": answer, "observations": obs}

    def _contribution(self, plan, result):
        rows, dim, m = result["rows"], self._dim(result), self._mcol(result)
        kp = {k["key"]: k for k in result.get("kpis", [])}
        total = kp["total"]["value"]
        if plan.get("focus"):
            members = [r for r in rows if r[dim["key"]] != "All other"]
            names = ", ".join(str(r[dim["key"]]) for r in members)
            answer = (f"Together, {names} generated {self.v(kp['combined']['value'], m.get('unit'), m.get('decimals', 2))}, "
                      f"which is {kp['combined_share']['value']:.1f}% of total {m['label']} ({self.v(total, m.get('unit'), m.get('decimals', 2))}).")
            obs = [f"{r[dim['key']]}: {r['share_pct']:.1f}% of total" for r in members]
            return {"answer": answer, "observations": obs}
        top = rows[0]
        answer = (f"{top[dim['key']]} contributes the largest share of {m['label']}: {top['share_pct']:.1f}% "
                  f"({self.v(top[m['key']], m.get('unit'), m.get('decimals', 2))} of {self.v(total, m.get('unit'), m.get('decimals', 2))}).")
        obs = []
        if "top_share" in kp:
            obs.append(f"The top {min(5, result.get('total_groups', 5))} account for {kp['top_share']['value']:.1f}% of the total.")
        if "n80" in kp:
            obs.append(f"{kp['n80']['value']} of {result.get('total_groups')} {dim['label'].lower()} values make up 80% of the total.")
        return {"answer": answer, "observations": obs}

    def _trend(self, plan, result):
        rows = result["rows"]
        m = self._mcol(result)
        grain = result.get("grain", "month")
        if not rows:
            return {"answer": "No dated records in scope.", "observations": []}
        if result.get("series"):
            dim = next(c for c in result["columns"] if c["role"] == "dimension")
            totals = {}
            for r in rows:
                totals[r[dim["key"]]] = totals.get(r[dim["key"]], 0) + (r[m["key"]] or 0)
            lead = max(totals, key=totals.get)
            last_p = rows[-1]["period_label"]
            last = {r[dim["key"]]: r[m["key"]] for r in rows if r["period_label"] == last_p}
            lead_last = max(last, key=lambda k: last[k] or 0)
            answer = (f"Across {len({r['period_label'] for r in rows})} {grain}s, {lead} has the highest cumulative {m['label']} "
                      f"({self.v(totals[lead], m.get('unit'), m.get('decimals', 2))}). In {last_p}, {lead_last} led with "
                      f"{self.v(last[lead_last], m.get('unit'), m.get('decimals', 2))}.")
            obs = [f"{k}: {self.v(v, m.get('unit'), m.get('decimals', 2))} total" for k, v in sorted(totals.items(), key=lambda kv: -kv[1])]
            return {"answer": answer, "observations": obs}
        kp = {k["key"]: k for k in result.get("kpis", [])}
        valid = [r for r in rows if r[m["key"]] is not None]
        first, last = valid[0], valid[-1]
        change = (last[m["key"]] - first[m["key"]]) / abs(first[m["key"]]) * 100 if first[m["key"]] else None
        answer = (f"{m['label']} per {grain} ranged from {self.v(kp['worst']['value'], m.get('unit'), m.get('decimals', 2))} "
                  f"({kp['worst']['label'].split(': ')[-1]}) to {self.v(kp['best']['value'], m.get('unit'), m.get('decimals', 2))} "
                  f"({kp['best']['label'].split(': ')[-1]}). The best {grain} was {kp['best']['label'].split(': ')[-1]}.")
        obs = [f"Latest {grain} ({last['period_label']}): {self.v(last[m['key']], m.get('unit'), m.get('decimals', 2))}"
               + (f", {fmt_pct(last.get('change_pct'))} vs the previous {grain}." if last.get("change_pct") is not None else ".")]
        if change is not None and len(valid) > 2:
            obs.append(f"From {first['period_label']} to {last['period_label']}, {m['label']} changed by {fmt_pct(change)}.")
        return {"answer": answer, "observations": obs}

    def _compare_periods(self, plan, result):
        kp = {k["key"]: k for k in result["kpis"]}
        m = self._mcol(result) if not plan.get("group_by") else next(c for c in result["columns"] if c["key"] == "current")
        unit, dec = kp["current"]["unit"], kp["current"].get("decimals", 2)
        p = result["periods"]
        ch, pct = kp["change"]["value"], kp["change_pct"]["value"]
        direction = "up" if (ch or 0) > 0 else "down" if (ch or 0) < 0 else "flat"
        label = result["provenance"]["measures"][0]["label"]
        answer = (f"{label} was {self.v(kp['current']['value'], unit, dec)} in {p['current']['label']} vs "
                  f"{self.v(kp['baseline']['value'], unit, dec)} in {p['baseline']['label']}: {direction} "
                  f"{self.v(abs(ch) if ch is not None and unit != 'percent' else ch, 'percent_points' if unit == 'percent' else unit, dec)}"
                  f"{f' ({fmt_pct(pct)})' if pct is not None else ''}.")
        obs = []
        if plan.get("group_by") and result["rows"]:
            dim = self._dim(result)
            ups = sorted([r for r in result["rows"] if r["change"] is not None], key=lambda r: -r["change"])
            if ups:
                obs.append(f"Largest increase: {ups[0][dim['key']]} ({self.v(ups[0]['change'], unit, dec)}).")
                obs.append(f"Largest decrease: {ups[-1][dim['key']]} ({self.v(ups[-1]['change'], unit, dec)}).")
        return {"answer": answer, "observations": obs}

    def _decompose_change(self, plan, result):
        base = self._compare_periods(plan, result)
        rows = result["rows"]
        dim = self._dim(result)
        kp = {k["key"]: k for k in result["kpis"]}
        unit, dec = kp["current"]["unit"], kp["current"].get("decimals", 2)
        total = kp["change"]["value"] or 0
        label = result["provenance"]["measures"][0]["label"]
        if not rows:
            return base
        top = rows[0]
        expected = plan.get("options", {}).get("expected_direction", "any")
        if expected == "decrease" and total >= 0:
            answer = (base["answer"] + f" {label} did not decrease overall in this comparison, so no segment 'caused' a decline. "
                      f"The weakest {dim['label'].lower()} was {top[dim['key']]} ({self.v(top['change'], unit, dec)}).")
        else:
            contrib = f", or {top['contribution_pct']:.0f}% of the total change" if top.get("contribution_pct") is not None else ""
            answer = (base["answer"] + f" {top[dim['key']]} contributed most to the {'decrease' if total < 0 else 'increase'}: "
                      f"{self.v(top['change'], unit, dec)}{contrib}.")
        obs = [f"{r[dim['key']]}: {self.v(r['change'], unit, dec)}" + (f" ({r['contribution_pct']:.0f}% of change)" if r.get("contribution_pct") is not None else "")
               for r in rows[1:5]]
        obs.append("This shows where the change happened, not why. Investigate drivers such as discounts, volumes or prices for the leading segment.")
        return {"answer": answer, "observations": obs}

    def _distribution(self, plan, result):
        if plan.get("group_by"):
            return self._contribution(plan, result) if result.get("kpis") and any(k["key"] == "total" for k in result["kpis"]) else self._breakdown(plan, result)
        st = result["stats"]
        rows = result["rows"]
        mode = max(rows, key=lambda r: r["count"])
        answer = (f"The median is {st['median']:,.2f} and the middle 50% of values fall between {st['q1']:,.2f} and {st['q3']:,.2f} "
                  f"(n = {st['count']:,}). The most common range is {mode['bin']} with {mode['count']:,} records ({mode['share_pct']:.1f}%).")
        obs = [f"Range: {st['min']:,.2f} to {st['max']:,.2f}; mean {st['mean']:,.2f}."]
        if st["mean"] and st["median"] and st["mean"] > st["median"] * 1.3:
            obs.append("The mean is well above the median, so a few large values pull the average up (right-skewed).")
        return {"answer": answer, "observations": obs}

    def _outliers(self, plan, result):
        kp = {k["key"]: k for k in result["kpis"]}
        n = kp["count"]["value"]
        level = result["level"]
        if not n:
            return {"answer": f"No outlier candidates were found among {level} using the rule: {result['method']}", "observations": []}
        rows = result["rows"]
        vcol = self._mcol(result, "v")
        top = rows[0]
        ident = next((c for c in result["columns"] if c["role"] == "dimension"), None)
        who = f"{top[ident['key']]}" if ident else "the most extreme value"
        answer = (f"Found {n:,} outlier candidate{'s' if n != 1 else ''} among {level} ({kp['share']['value']:.1f}%). "
                  f"The most extreme is {who} at {self.v(top['v'], vcol.get('unit'), vcol.get('decimals', 2))}, versus a typical "
                  f"(median) value of {self.v(kp['median']['value'], vcol.get('unit'), vcol.get('decimals', 2))}.")
        obs = [result["method"], f"{kp['high']['value']:,} are unusually high and {n - kp['high']['value']:,} unusually low.",
               "Unusual does not mean wrong: review these records before drawing conclusions."]
        return {"answer": answer, "observations": obs}

    def _describe_dataset(self, plan, result):
        return {"answer": "", "observations": []}

    def _follow_ups(self, plan, result) -> list[str]:
        intent = plan["intent"]
        dim = self._dim(result)
        label = result["provenance"]["measures"][0]["label"] if result.get("provenance", {}).get("measures") else "revenue"
        s = []
        if intent in ("rank", "breakdown") and dim:
            s += [f"How much did their {label.lower()} contribute to the total?", f"Show monthly {label.lower()} by {dim['label'].lower()}",
                  f"Compare the top two {dim['label'].lower()} values"]
        elif intent == "trend":
            s += [f"Which region contributed most to the change in {label.lower()} last month?", f"Are there abnormal changes in daily {label.lower()}?",
                  f"Compare {label.lower()} this month with the previous month"]
        elif intent in ("compare_periods", "decompose_change"):
            s += [f"Show monthly {label.lower()}", f"Which products contributed most to the change in {label.lower()}?"]
        elif intent == "contribution":
            s += [f"Show monthly {label.lower()} for these", "Which customers contribute the most to revenue?"]
        elif intent == "outliers":
            s += [f"How are {label.lower()} values distributed?", f"Show monthly {label.lower()}"]
        else:
            s += [f"Show monthly {label.lower()}", f"Which five products generated the highest {label.lower()}?"]
        return s[:3]

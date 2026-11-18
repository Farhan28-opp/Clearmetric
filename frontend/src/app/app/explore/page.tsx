"use client";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Play, Plus, Trash2, Wand2, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { ResultView } from "@/components/analysis/result";
import { DatasetSelect, useActiveDataset, useColumns, useMetrics } from "@/components/datasets";
import { Badge, Button, cx, Empty, ErrorNote, Field, Input, PageHeader, Panel, Select, Skeleton, Tabs, Textarea, useToast } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { del, errorMessage, post } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { Column, Filter, MeasureRef, Plan, Run } from "@/lib/types";

const INTENTS = [
  ["aggregate", "Total value"], ["breakdown", "Breakdown by dimension"], ["rank", "Ranking (top / bottom)"], ["trend", "Trend over time"],
  ["compare_periods", "Compare periods"], ["compare_segments", "Compare segments"], ["contribution", "Contribution to total"],
  ["decompose_change", "What drove a change"], ["distribution", "Distribution"], ["outliers", "Unusual values"],
];
const OPS = [["eq", "is"], ["neq", "is not"], ["in", "is one of"], ["gt", ">"], ["gte", "≥"], ["lt", "<"], ["lte", "≤"], ["contains", "contains"], ["is_null", "is empty"], ["not_null", "is not empty"]];
const AGGS = [["sum", "Sum"], ["avg", "Average"], ["median", "Median"], ["min", "Minimum"], ["max", "Maximum"], ["count", "Count"], ["count_distinct", "Distinct count"]];

type Builder = {
  intent: string; measure: string; agg: string; dim: string; dim2: string; filters: Filter[]; start: string; end: string; grain: string;
  cmpMode: string; cmpGrain: string; curStart: string; curEnd: string; baseStart: string; baseEnd: string; segments: string;
  limit: number; direction: string; outlierMethod: string; threshold: number; timeCol: string;
};
const EMPTY: Builder = { intent: "breakdown", measure: "", agg: "sum", dim: "", dim2: "", filters: [], start: "", end: "", grain: "month", cmpMode: "previous_period", cmpGrain: "month",
  curStart: "", curEnd: "", baseStart: "", baseEnd: "", segments: "", limit: 20, direction: "desc", outlierMethod: "iqr", threshold: 1.5, timeCol: "" };

function toPlan(b: Builder, datasetId: string): Plan {
  const measure: MeasureRef = b.measure.startsWith("metric:") ? { kind: "metric", metric_id: b.measure.slice(7) }
    : b.measure === "count_rows" ? { kind: "count_rows" } : { kind: "column", column: b.measure.slice(4), aggregation: b.agg };
  const p: Plan = { intent: b.intent, dataset_id: datasetId, measures: [measure], group_by: [], filters: b.filters, limit: b.limit, sort: { by: "value", direction: b.direction }, visualization: "auto", options: {} };
  if (["breakdown", "rank", "contribution", "compare_segments", "decompose_change", "distribution"].includes(b.intent) && b.dim) p.group_by = [b.dim, ...(b.intent === "breakdown" && b.dim2 ? [b.dim2] : [])];
  if (b.intent === "trend" && b.dim) p.group_by = [b.dim];
  if (b.intent === "outliers" && b.dim && b.grain === "none") p.group_by = [b.dim];
  if (b.timeCol && (b.start || b.end || b.intent === "trend" || (b.intent === "outliers" && b.grain !== "none")))
    p.time = { column: b.timeCol, grain: b.intent === "trend" || (b.intent === "outliers" && b.grain !== "none") ? b.grain : null, start: b.start || null, end: b.end || null };
  if (b.intent === "compare_periods" || b.intent === "decompose_change") {
    p.time = { column: b.timeCol };
    p.comparison = b.cmpMode === "custom" ? { mode: "custom", grain: b.cmpGrain, current: { start: b.curStart, end: b.curEnd }, baseline: { start: b.baseStart, end: b.baseEnd } } : { mode: b.cmpMode, grain: b.cmpGrain };
  }
  if (b.intent === "compare_segments" && b.dim && b.segments.trim()) p.focus = { column: b.dim, values: b.segments.split(",").map((s) => s.trim()).filter(Boolean) };
  if (b.intent === "outliers") p.options = { outlier_method: b.outlierMethod, outlier_threshold: b.threshold };
  if (b.intent === "trend") p.limit = 500;
  return p;
}

function fromPlan(p: Plan, prev: Builder): Builder {
  const m = p.measures[0];
  return { ...prev, intent: p.intent, measure: m?.kind === "metric" ? `metric:${m.metric_id}` : m?.kind === "column" ? `col:${m.column}` : "count_rows", agg: m?.aggregation ?? "sum",
    dim: p.group_by?.[0] ?? p.focus?.column ?? "", dim2: p.group_by?.[1] ?? "", filters: p.filters ?? [], start: p.time?.start ?? "", end: p.time?.end ?? "", grain: p.time?.grain ?? prev.grain,
    timeCol: p.time?.column ?? prev.timeCol, cmpMode: p.comparison?.mode ?? prev.cmpMode, cmpGrain: p.comparison?.grain ?? prev.cmpGrain, segments: p.focus?.values?.join(", ") ?? "",
    limit: p.limit ?? prev.limit, direction: p.sort?.direction ?? "desc" };
}

type Card = { id: string; run: Run; title: string; note: string; drill: string[] };

function Canvas() {
  const params = useSearchParams();
  const { base, wid, can } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const { id: dsId, choose, datasets } = useActiveDataset(params.get("dataset"));
  const cols = useColumns(dsId);
  const metrics = useMetrics(dsId);
  const [mode, setMode] = useState<"visual" | "nl" | "saved">("visual");
  const [b, setB] = useState<Builder>(EMPTY);
  const [nl, setNl] = useState("");
  const [nlInfo, setNlInfo] = useState<{ status: string; notes: string[]; message: string; interpreter: string } | null>(null);
  const [cards, setCards] = useState<Card[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [draft, setDraft] = useState<Filter>({ column: "", op: "eq", value: "" });
  const saved = useWsQuery<{ visualizations: { id: string; title: string; chart_type: string; note: string; created_at: string; run: Run | null }[] }>(["visualizations"], "/analysis/visualizations", { enabled: mode === "saved" });

  const c = cols.data?.columns.filter((x) => !x.excluded) ?? [];
  const dims = c.filter((x) => ["dimension", "identifier", "boolean"].includes(x.semantic_type) || (x.dtype === "string" && x.unique_count <= 1000));
  const nums = c.filter((x) => x.dtype === "integer" || x.dtype === "float");
  const dates = c.filter((x) => x.dtype === "date" || x.dtype === "datetime");
  const byName = useMemo(() => Object.fromEntries(c.map((x) => [x.name, x])), [c]);

  useEffect(() => {
    if (!cols.data || !metrics.data) return;
    const ms = metrics.data.metrics;
    const mParam = params.get("metric");
    const preferred = ms.find((m) => m.id === mParam) ?? ms.find((m) => m.verified && /net revenue/i.test(m.name))
      ?? ms.find((m) => m.verified && m.unit === "currency" && m.aggregation_type === "additive") ?? ms.find((m) => m.verified) ?? ms[0];
    const names = new Set(cols.data.columns.filter((x) => !x.excluded).map((x) => x.name));
    setB((prev) => {
      const valid = prev.measure === "count_rows" || (prev.measure.startsWith("metric:") && ms.some((m) => `metric:${m.id}` === prev.measure))
        || (prev.measure.startsWith("col:") && names.has(prev.measure.slice(4)));
      return {
        ...prev,
        measure: valid ? prev.measure : preferred ? `metric:${preferred.id}` : nums[0] ? `col:${nums[0].name}` : "count_rows",
        dim: prev.dim && names.has(prev.dim) ? prev.dim : dims.find((d) => d.semantic_type === "dimension")?.name ?? "",
        timeCol: prev.timeCol && names.has(prev.timeCol) ? prev.timeCol : dates[0]?.name ?? "",
      };
    });
    setDraft((d) => ({ ...d, column: d.column || dims[0]?.name || "" }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cols.data, metrics.data, dsId]);

  const run = async (plan: Plan, title: string, drill: string[] = [], question = "") => {
    setBusy(true); setErr("");
    try {
      const r = await post<{ run: Run }>(`${base}/analysis/run`, { plan, source: "explore", question });
      setCards((cs) => [{ id: r.run.id, run: r.run, title, note: "", drill }, ...cs]);
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  };
  const titleFor = (p: Plan) => {
    const m = p.measures[0];
    const mName = m.kind === "metric" ? metrics.data?.metrics.find((x) => x.id === m.metric_id)?.name : m.kind === "column" ? `${m.aggregation} of ${byName[m.column ?? ""]?.display_name}` : "Records";
    const intent = INTENTS.find((i) => i[0] === p.intent)?.[1];
    return `${mName}: ${intent}${p.group_by.length ? ` by ${p.group_by.map((g) => byName[g]?.display_name ?? g).join(" and ")}` : ""}`;
  };
  const drillFrom = (card: Card, value: string) => {
    const p = card.run.plan;
    const dim = p.group_by[0];
    if (!dim) return;
    const order = ["region", "category", "channel", "segment", "product", "customer_id", "customer"];
    const used = new Set([...p.group_by, ...p.filters.map((f) => f.column)]);
    const next = [...dims].sort((a, b2) => (order.indexOf(a.business_meaning) + 99) % 99 - (order.indexOf(b2.business_meaning) + 99) % 99)
      .find((d) => !used.has(d.name) && d.semantic_type === "dimension");
    if (!next) return toast("No further dimension to drill into", "error");
    const plan: Plan = { ...p, intent: p.intent === "trend" ? "breakdown" : p.intent === "compare_segments" ? "rank" : p.intent, group_by: [next.name], focus: null,
      filters: [...p.filters, { column: dim, op: "eq", value }] };
    run(plan, `${titleFor(plan)} in ${value}`, [...card.drill, `${byName[dim]?.display_name}: ${value}`]);
  };
  const interpret = async () => {
    if (!nl.trim() || !dsId) return;
    setBusy(true); setErr(""); setNlInfo(null);
    try {
      const r = await post<{ status: string; plan: Plan | null; notes: string[]; message: string; interpreter: string }>(`${base}/analysis/interpret`, { dataset_id: dsId, question: nl });
      setNlInfo(r);
      if (r.status === "plan" && r.plan) { setB((prev) => fromPlan(r.plan!, prev)); await run(r.plan, titleFor(r.plan), [], nl); }
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  };
  const set = (k: keyof Builder, v: unknown) => setB((prev) => ({ ...prev, [k]: v }));
  const needsDim = ["breakdown", "rank", "contribution", "compare_segments", "decompose_change"].includes(b.intent);

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader title="Explore" description="Build an analysis by choosing what to measure and how to slice it, or describe it in words. Both produce the same validated plan."
        actions={<DatasetSelect value={dsId} onChange={(v) => { choose(v); setCards([]); }} datasets={datasets} />} />
      <Tabs value={mode} onChange={setMode} className="mb-5" items={[{ value: "visual", label: "Configure visually" }, { value: "nl", label: "Ask in natural language" }, { value: "saved", label: "Saved visualisations" }]} />
      {!dsId && <Empty title="No dataset selected">Add a dataset in the Data Hub to start exploring.</Empty>}
      {dsId && mode !== "saved" && (
        <div className="grid gap-6 lg:grid-cols-[21rem_1fr]">
          <div className="space-y-4">
            {mode === "nl" && (
              <Panel title="Describe the analysis"><div className="space-y-3 p-4">
                <Textarea aria-label="Question" rows={3} value={nl} onChange={(e) => setNl(e.target.value)} placeholder="e.g. Compare monthly net revenue across regions" />
                <Button variant="primary" onClick={interpret} loading={busy} disabled={!can("analyst")}><Wand2 className="size-4" />Interpret and run</Button>
                {nlInfo && <div className="space-y-1 text-sm">
                  {nlInfo.status !== "plan" && <p className="text-brass">{nlInfo.message}</p>}
                  {nlInfo.notes.map((n) => <p key={n} className="text-xs text-muted">{n}</p>)}
                  {nlInfo.status === "plan" && <p className="text-xs text-muted">The plan below was filled in from your question. Adjust anything and run again.</p>}
                </div>}
              </div></Panel>
            )}
            <Panel title="Analysis builder"><div className="space-y-3 p-4">
              <Field label="Analysis type" htmlFor="it"><Select id="it" value={b.intent} onChange={(e) => set("intent", e.target.value)}>{INTENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
              <Field label="Measure" htmlFor="ms"><Select id="ms" value={b.measure} onChange={(e) => set("measure", e.target.value)}>
                {!!metrics.data?.metrics.length && <optgroup label="Saved metrics">{metrics.data.metrics.map((m) => <option key={m.id} value={`metric:${m.id}`}>{m.name}{m.verified ? "" : " (unverified)"}</option>)}</optgroup>}
                <optgroup label="Columns">{nums.map((n) => <option key={n.name} value={`col:${n.name}`}>{n.display_name}</option>)}<option value="count_rows">Number of records</option></optgroup>
              </Select></Field>
              {b.measure.startsWith("col:") && <Field label="Aggregation" htmlFor="ag"><Select id="ag" value={b.agg} onChange={(e) => set("agg", e.target.value)}>{AGGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>}
              {(needsDim || b.intent === "trend" || b.intent === "distribution" || b.intent === "outliers") && (
                <Field label={b.intent === "trend" ? "Split lines by (optional)" : needsDim ? "Dimension" : "Group by (optional)"} htmlFor="dm">
                  <Select id="dm" value={b.dim} onChange={(e) => set("dim", e.target.value)}>{!needsDim && <option value="">None</option>}{dims.map((d) => <option key={d.name} value={d.name}>{d.display_name}</option>)}</Select>
                </Field>)}
              {b.intent === "breakdown" && <Field label="Second dimension (stacked)" htmlFor="dm2"><Select id="dm2" value={b.dim2} onChange={(e) => set("dim2", e.target.value)}><option value="">None</option>{dims.filter((d) => d.name !== b.dim).map((d) => <option key={d.name} value={d.name}>{d.display_name}</option>)}</Select></Field>}
              {b.intent === "compare_segments" && <SegmentPicker datasetId={dsId} column={b.dim} value={b.segments} onChange={(v) => set("segments", v)} />}
              {(b.intent === "trend" || b.intent === "outliers") && (
                <Field label={b.intent === "outliers" ? "Check values at the level of" : "Time grain"} htmlFor="gr"><Select id="gr" value={b.grain} onChange={(e) => set("grain", e.target.value)}>
                  {b.intent === "outliers" && <option value="none">Individual records / groups</option>}{["day", "week", "month", "quarter", "year"].map((g) => <option key={g} value={g}>{g === "day" ? "Daily totals" : g === "week" ? "Weekly totals" : `${g[0].toUpperCase() + g.slice(1)}ly totals`}</option>)}</Select></Field>)}
              {(b.intent === "compare_periods" || b.intent === "decompose_change") && (
                <div className="space-y-2 rounded-md border border-line p-3">
                  <Field label="Compare" htmlFor="cm"><Select id="cm" value={b.cmpMode} onChange={(e) => set("cmpMode", e.target.value)}><option value="previous_period">Latest period vs previous</option><option value="previous_year">Latest period vs same period last year</option><option value="custom">Custom date ranges</option></Select></Field>
                  {b.cmpMode !== "custom" ? <Field label="Period length" htmlFor="cg"><Select id="cg" value={b.cmpGrain} onChange={(e) => set("cmpGrain", e.target.value)}>{["week", "month", "quarter", "year"].map((g) => <option key={g} value={g}>{g}</option>)}</Select></Field> : (
                    <div className="grid grid-cols-2 gap-2">
                      <Field label="Current from" htmlFor="cs"><Input id="cs" type="date" value={b.curStart} onChange={(e) => set("curStart", e.target.value)} /></Field>
                      <Field label="to" htmlFor="ce"><Input id="ce" type="date" value={b.curEnd} onChange={(e) => set("curEnd", e.target.value)} /></Field>
                      <Field label="Baseline from" htmlFor="bs"><Input id="bs" type="date" value={b.baseStart} onChange={(e) => set("baseStart", e.target.value)} /></Field>
                      <Field label="to" htmlFor="be"><Input id="be" type="date" value={b.baseEnd} onChange={(e) => set("baseEnd", e.target.value)} /></Field>
                    </div>)}
                </div>)}
              {dates.length > 0 && b.intent !== "compare_periods" && b.intent !== "decompose_change" && (
                <div className="grid grid-cols-2 gap-2">
                  <Field label="From" htmlFor="ds"><Input id="ds" type="date" value={b.start} onChange={(e) => set("start", e.target.value)} /></Field>
                  <Field label="To" htmlFor="de"><Input id="de" type="date" value={b.end} onChange={(e) => set("end", e.target.value)} /></Field>
                </div>)}
              {dates.length > 1 && <Field label="Date column" htmlFor="tc"><Select id="tc" value={b.timeCol} onChange={(e) => set("timeCol", e.target.value)}>{dates.map((d) => <option key={d.name} value={d.name}>{d.display_name}</option>)}</Select></Field>}
              <div>
                <p className="text-[13px] font-medium text-ink-2">Filters</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">{b.filters.map((f, i) => (
                  <span key={i} className="inline-flex items-center gap-1 rounded-full border border-line-2 px-2 py-0.5 text-xs">{byName[f.column]?.display_name} {OPS.find((o) => o[0] === f.op)?.[1]} {Array.isArray(f.value) ? f.value.join(", ") : String(f.value ?? "")}
                    <button aria-label="Remove filter" onClick={() => set("filters", b.filters.filter((_, j) => j !== i))}><X className="size-3" /></button></span>))}</div>
                <div className="mt-2 grid grid-cols-[1fr_5.5rem] gap-1.5">
                  <Select aria-label="Filter column" value={draft.column} onChange={(e) => setDraft({ ...draft, column: e.target.value })} className="h-8 text-xs">{c.map((x) => <option key={x.name} value={x.name}>{x.display_name}</option>)}</Select>
                  <Select aria-label="Operator" value={draft.op} onChange={(e) => setDraft({ ...draft, op: e.target.value })} className="h-8 text-xs">{OPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
                  {!["is_null", "not_null"].includes(draft.op) && <Input aria-label="Filter value" className="h-8 text-xs" value={String(draft.value ?? "")} onChange={(e) => setDraft({ ...draft, value: e.target.value })} placeholder={draft.op === "in" ? "comma separated" : "value"} list="filter-values" />}
                  <Button size="sm" onClick={() => { set("filters", [...b.filters, { ...draft, value: draft.op === "in" ? String(draft.value).split(",").map((s) => s.trim()) : draft.value }]); setDraft({ ...draft, value: "" }); }}><Plus className="size-3.5" />Add</Button>
                </div>
                <ValueHints datasetId={dsId} column={draft.column} col={byName[draft.column]} />
              </div>
              {["rank", "breakdown", "contribution", "outliers"].includes(b.intent) && (
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Show at most" htmlFor="lm"><Input id="lm" type="number" min={1} max={500} value={b.limit} onChange={(e) => set("limit", Number(e.target.value))} /></Field>
                  {b.intent !== "outliers" && <Field label="Sort" htmlFor="sd"><Select id="sd" value={b.direction} onChange={(e) => set("direction", e.target.value)}><option value="desc">Highest first</option><option value="asc">Lowest first</option></Select></Field>}
                </div>)}
              {b.intent === "outliers" && <div className="grid grid-cols-2 gap-2">
                <Field label="Method" htmlFor="om"><Select id="om" value={b.outlierMethod} onChange={(e) => { const v = e.target.value; setB((prev) => ({ ...prev, outlierMethod: v, threshold: v === "zscore" ? 3 : 1.5 })); }}><option value="iqr">IQR rule</option><option value="zscore">Z-score</option></Select></Field>
                <Field label={b.outlierMethod === "iqr" ? "IQR multiplier" : "Std. deviations"} htmlFor="th"><Input id="th" type="number" step={0.5} min={0.5} max={10} value={b.threshold} onChange={(e) => set("threshold", Number(e.target.value))} /></Field></div>}
              {err && <ErrorNote>{err}</ErrorNote>}
              <Button variant="primary" className="w-full" loading={busy} disabled={!can("analyst") || (needsDim && !b.dim)} onClick={() => { const p = toPlan(b, dsId); run(p, titleFor(p)); }}><Play className="size-4" />Run analysis</Button>
              <details className="text-xs"><summary className="cursor-pointer text-muted">View the plan this builds</summary><pre className="mt-2 overflow-x-auto rounded bg-paper p-2">{JSON.stringify(toPlan(b, dsId), null, 2)}</pre></details>
            </div></Panel>
          </div>
          <div className="min-w-0 space-y-5">
            {!cards.length && <Empty title="Your analysis canvas" icon={<Play className="size-6" />}>Run an analysis to add it here. Each result keeps its own chart, table, notes and calculation, and you can click bars to drill into the next level.</Empty>}
            {cards.map((card) => (
              <Panel key={card.id} title={<div className="min-w-0"><h2 className="truncate text-sm font-semibold">{card.title}</h2>
                {card.drill.length > 0 && <p className="flex flex-wrap items-center gap-1 text-xs text-muted">Drill path {card.drill.map((d) => <span key={d} className="flex items-center gap-1"><ChevronRight className="size-3" />{d}</span>)}</p>}
                <p className="text-xs text-muted">{card.run.result.provenance.records_in_scope.toLocaleString()} records · {card.run.result.provenance.date_range} · {timeAgo(card.run.created_at)}</p></div>}
                actions={<button aria-label="Remove from canvas" onClick={() => setCards(cards.filter((x) => x.id !== card.id))} className="rounded p-1 text-muted hover:bg-paper-2"><X className="size-4" /></button>}>
                <div className="space-y-3 p-4">
                  <ResultView run={card.run} title={card.title} onDrill={card.run.plan.group_by.length === 1 && !["outliers", "distribution"].includes(card.run.plan.intent) ? (v) => drillFrom(card, v) : undefined} />
                  <Textarea aria-label="Notes for this result" rows={2} placeholder="Notes and findings for this result" value={card.note} onChange={(e) => setCards(cards.map((x) => x.id === card.id ? { ...x, note: e.target.value } : x))} className="text-sm" />
                </div>
              </Panel>))}
          </div>
        </div>
      )}
      {mode === "saved" && (
        <div className="grid gap-5 lg:grid-cols-2">
          {saved.isLoading && <Skeleton className="h-64" />}
          {saved.data && !saved.data.visualizations.length && <Empty title="No saved visualisations">Use “Save visualisation” under any result in Explore or the AI Analyst.</Empty>}
          {saved.data?.visualizations.map((v) => v.run && (
            <Panel key={v.id} title={<div><h2 className="text-sm font-semibold">{v.title}</h2><p className="text-xs text-muted">{v.run.result.provenance.dataset.name} v{v.run.result.provenance.dataset.version_number} · saved {timeAgo(v.created_at)}</p></div>}
              actions={can("analyst") && <button aria-label="Delete saved visualisation" onClick={async () => { await del(`${base}/analysis/visualizations/${v.id}`); qc.invalidateQueries({ queryKey: [wid, "visualizations"] }); }} className="rounded p-1 text-muted hover:text-rust"><Trash2 className="size-4" /></button>}>
              <div className="space-y-2 p-4">{v.note && <p className="text-sm text-ink-2">{v.note}</p>}<ResultView run={v.run} title={v.title} compact /></div>
            </Panel>))}
        </div>
      )}
    </div>
  );
}

function ValueHints({ datasetId, column, col }: { datasetId: string; column: string; col?: Column }) {
  const q = useWsQuery<{ values: { value: string; count: number }[] }>(["values", datasetId, column], col && col.dtype === "string" && col.unique_count <= 1000 ? `/datasets/${datasetId}/columns/${column}/values` : null);
  return <datalist id="filter-values">{q.data?.values.map((v) => <option key={v.value} value={v.value} />)}</datalist>;
}

function SegmentPicker({ datasetId, column, value, onChange }: { datasetId: string; column: string; value: string; onChange: (v: string) => void }) {
  const q = useWsQuery<{ values: { value: string; count: number }[] }>(["values", datasetId, column], column ? `/datasets/${datasetId}/columns/${column}/values` : null);
  const chosen = value.split(",").map((s) => s.trim()).filter(Boolean);
  return (
    <div>
      <p className="text-[13px] font-medium text-ink-2">Segments to compare <span className="font-normal text-muted">(leave empty for all)</span></p>
      <div className="mt-1.5 flex max-h-28 flex-wrap gap-1 overflow-y-auto">{q.data?.values.slice(0, 40).map((v) => (
        <button key={v.value} type="button" onClick={() => onChange((chosen.includes(v.value) ? chosen.filter((c) => c !== v.value) : [...chosen, v.value]).join(", "))}
          className={cx("rounded-full border px-2 py-0.5 text-xs", chosen.includes(v.value) ? "border-forest bg-forest-wash text-forest-2" : "border-line-2")}>{v.value}</button>))}</div>
      {chosen.length > 0 && <Badge className="mt-1.5">{chosen.length} selected</Badge>}
    </div>
  );
}

export default function ExplorePage() {
  return <Suspense fallback={<Skeleton className="h-96" />}><Canvas /></Suspense>;
}

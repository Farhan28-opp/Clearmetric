"use client";
import { ArrowDownUp, Check, Download, FileImage, FilePlus2, Info, Repeat, Save, Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { allowedChartTypes, defaultChartType, exportPng, ResultChart } from "@/components/analysis/chart";
import { Badge, Button, cx, Dialog, Field, Input, Select, Textarea, useToast } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { download, errorMessage, post } from "@/lib/api";
import { cellText, fmtDate, fmtValue } from "@/lib/format";
import type { AnalysisResult, Kpi, Report, Run } from "@/lib/types";

const CHART_LABEL: Record<string, string> = { bar: "Bar", hbar: "Horizontal bar", line: "Line", area: "Area", stacked_bar: "Stacked", donut: "Donut", histogram: "Histogram", scatter: "Scatter", waterfall: "Waterfall", table: "Table" };

export function KpiRow({ kpis, currency }: { kpis: Kpi[]; currency: string }) {
  if (!kpis?.length) return null;
  return (
    <dl className={cx("grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line", kpis.length === 3 ? "sm:grid-cols-3" : kpis.length >= 4 ? "sm:grid-cols-4" : "sm:grid-cols-2")}>
      {kpis.map((k) => (
        <div key={k.key} className="bg-surface px-3.5 py-3">
          <dt className="line-clamp-2 text-xs leading-snug text-muted" title={k.label}>{k.label}</dt>
          <dd className={cx("tnum mt-1 text-xl font-semibold", k.unit === "pct" && k.value !== null && k.value < 0 && "text-rust")}>
            {k.text ?? (k.unit === "pct" && k.value !== null ? `${k.value > 0 ? "+" : ""}${k.value.toFixed(1)}%` : fmtValue(k.value, k.unit ?? "number", currency, k.decimals ?? 2))}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function ResultTable({ result, currency, maxRows = 200, selectable }: { result: AnalysisResult; currency: string; maxRows?: number; selectable?: boolean }) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const rows = useMemo(() => {
    const r = [...result.rows];
    if (sort) r.sort((a, b) => ((a[sort.key] ?? -Infinity) > (b[sort.key] ?? -Infinity) ? 1 : -1) * sort.dir);
    return r.slice(0, maxRows);
  }, [result.rows, sort, maxRows]);
  if (!result.columns.length) return null;
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="w-full text-sm">
        <caption className="sr-only">Result table with {result.rows.length} rows</caption>
        <thead className="bg-paper/70">
          <tr>
            {selectable && <th className="w-8" />}
            {result.columns.map((c) => (
              <th key={c.key} scope="col" className={cx("whitespace-nowrap px-3 py-2 text-left font-medium text-ink-2", c.role !== "dimension" && c.role !== "period" && c.role !== "text" && "text-right")}>
                <button className="inline-flex items-center gap-1 hover:text-ink" onClick={() => setSort((s) => ({ key: c.key, dir: s?.key === c.key && s.dir === -1 ? 1 : -1 }))}
                  aria-label={`Sort by ${c.label}`}>
                  {c.label}<ArrowDownUp className="size-3 text-muted" aria-hidden />
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-paper/50">
              {result.columns.map((c) => (
                <td key={c.key} className={cx("whitespace-nowrap px-3 py-1.5", c.role !== "dimension" && c.role !== "period" && c.role !== "text" ? "tnum text-right" : "")}>
                  <span className={cx(typeof r[c.key] === "number" && r[c.key] < 0 && (c.key.includes("change") || c.key === "contribution_pct") && "text-rust")}>{cellText(r[c.key], c, currency)}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {result.rows.length > maxRows && <p className="border-t border-line px-3 py-2 text-xs text-muted">Showing {maxRows} of {result.rows.length} rows. Export for the full result.</p>}
    </div>
  );
}

export function Inspector({ run, onClose }: { run: Run; onClose?: () => void }) {
  const { base, me } = useWorkspace();
  const p = run.result.provenance;
  const [showSql, setShowSql] = useState(Boolean(me.user.preferences?.show_sql));
  const [repro, setRepro] = useState<null | { identical: boolean }>(null);
  const [busy, setBusy] = useState(false);
  const rows: [string, React.ReactNode][] = [
    ["Dataset", <span key="ds">{p.dataset.name} <Badge>v{p.dataset.version_number}</Badge>{p.dataset.is_demo && <Badge tone="brass" className="ml-1">synthetic</Badge>}</span>],
    ["Records included", <span key="rec">{p.records_in_scope.toLocaleString()} of {p.dataset.total_rows.toLocaleString()}</span>],
    ["Filters", p.filters.length ? p.filters.join("; ") : "None"],
    ["Date range", p.date_range || "All dates"],
    ...(p.time_column ? [["Date column", p.time_column] as [string, string]] : []),
    ["Grouping", p.grouping.length ? p.grouping.join(", ") : "None"],
    ...p.measures.map((m, i) => [i === 0 ? "Measure" : `Measure ${i + 1}`, <span key={i}><span className="font-medium">{m.label}</span> = {m.definition} <span className="text-muted">({m.aggregation_type})</span></span>] as [string, React.ReactNode]),
    ...p.metrics.map((m) => ["Metric version", <span key={m.metric_version_id}>{m.name} v{m.version} {m.verified ? <Badge tone="forest">verified</Badge> : <Badge tone="brass">unverified</Badge>}</span>] as [string, React.ReactNode]),
    ["Methodology", p.methodology],
    ["Interpreter", run.interpreter === "local-deterministic" ? "Local deterministic interpreter (rule-based, not a generative model)" : run.interpreter.startsWith("anthropic") ? `Claude (${run.interpreter.split(":")[1]}), plan validated server-side` : run.interpreter || "Visual builder"],
    ["Execution", <span key="e">Succeeded in {p.duration_ms} ms{p.cache_hit ? " (cached result)" : ""} at {fmtDate(p.executed_at, true)}</span>],
    ["Engine", p.engine],
  ];
  return (
    <div className="space-y-4 text-sm">
      {run.plan_notes?.length > 0 && (
        <div className="rounded-md border border-line bg-paper/60 p-3">
          <p className="mb-1 text-xs font-medium text-ink-2">How the question was interpreted</p>
          <ul className="list-disc space-y-0.5 pl-4 text-ink-2">{run.plan_notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </div>
      )}
      <dl className="grid grid-cols-[8.5rem_1fr] gap-x-3 gap-y-2">
        {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="min-w-0 break-words">{v}</dd></div>)}
      </dl>
      <details className="rounded-md border border-line">
        <summary className="cursor-pointer px-3 py-2 text-ink-2">Analysis plan (validated)</summary>
        <pre className="overflow-x-auto border-t border-line bg-paper/60 p-3 text-xs leading-relaxed">{JSON.stringify(run.plan, null, 2)}</pre>
      </details>
      <div className="rounded-md border border-line">
        <button className="flex w-full items-center justify-between px-3 py-2 text-left text-ink-2" onClick={() => setShowSql(!showSql)} aria-expanded={showSql}>
          Generated query (read-only) <span className="text-xs text-muted">{p.queries.length} statement{p.queries.length === 1 ? "" : "s"}</span>
        </button>
        {showSql && p.queries.map((q, i) => (
          <div key={i} className="border-t border-line p-3">
            <p className="mb-1 text-xs text-muted">{q.purpose} · {q.duration_ms} ms</p>
            <pre className="overflow-x-auto rounded bg-ink p-2.5 text-xs leading-relaxed text-[#cde5d9]">{q.sql}</pre>
            {q.params.length > 0 && <p className="mt-1 break-words text-xs text-muted">Bound parameters: {JSON.stringify(q.params)}</p>}
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" loading={busy} onClick={async () => { setBusy(true); try { setRepro(await post(`${base}/analysis/runs/${run.id}/reproduce`)); } finally { setBusy(false); } }}>
          <Repeat className="size-3.5" /> Reproduce from saved plan
        </Button>
        {repro && <span role="status" className={cx("text-sm", repro.identical ? "text-forest" : "text-brass")}>{repro.identical ? <><Check className="mr-1 inline size-4" />Identical result from dataset v{p.dataset.version_number}</> : "Result differs from the stored one"}</span>}
        {onClose && <Button size="sm" variant="ghost" onClick={onClose} className="ml-auto">Close</Button>}
      </div>
    </div>
  );
}

export function AddToReport({ run, open, onClose, title }: { run: Run; open: boolean; onClose: () => void; title: string }) {
  const { base } = useWorkspace();
  const toast = useToast();
  const reports = useWsQuery<{ reports: Report[] }>(["reports"], "/reports", { enabled: open });
  const [target, setTarget] = useState("new");
  const [name, setName] = useState("New report");
  const [secTitle, setSecTitle] = useState(title);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} title="Add to report"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={async () => {
        setBusy(true);
        try {
          let rid = target;
          if (target === "new") rid = (await post<{ report: Report }>(`${base}/reports`, { title: name, dataset_id: run.dataset_id })).report.id;
          await post(`${base}/reports/${rid}/sections`, { kind: "chart", run_id: run.id, title: secTitle });
          toast("Added to report");
          onClose();
        } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
      }}>Add section</Button></>}>
      <div className="space-y-3">
        <Field label="Report" htmlFor="rep">
          <Select id="rep" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="new">Create a new report</option>
            {reports.data?.reports.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}
          </Select>
        </Field>
        {target === "new" && <Field label="New report title" htmlFor="rn"><Input id="rn" value={name} onChange={(e) => setName(e.target.value)} /></Field>}
        <Field label="Section title" htmlFor="st"><Input id="st" value={secTitle} onChange={(e) => setSecTitle(e.target.value)} /></Field>
        <p className="text-xs text-muted">The section stores a snapshot of this result with its provenance.</p>
      </div>
    </Dialog>
  );
}

export function ResultView({ run, title, onDrill, compact, conversationId, showActions = true, onInspect }: {
  run: Run; title?: string; onDrill?: (value: string) => void; compact?: boolean; conversationId?: string; showActions?: boolean; onInspect?: () => void;
}) {
  const { ws, base, can } = useWorkspace();
  const toast = useToast();
  const r = run.result;
  const types = allowedChartTypes(r);
  const [type, setType] = useState(defaultChartType(r) === "kpi" ? "table" : types.includes(defaultChartType(r)) ? defaultChartType(r) : types[0]);
  const [inspect, setInspect] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [vizNote, setVizNote] = useState("");
  const [vizTitle, setVizTitle] = useState(title || run.question || "Saved analysis");
  const chartRef = useRef<HTMLDivElement>(null);
  const currency = ws?.currency ?? "USD";
  const hasChart = r.chart?.type && r.chart.type !== "kpi" && r.chart.type !== "table" && r.rows.length > 0;
  const chartTitle = title || run.question || "analysis";
  return (
    <div className="space-y-3">
      {r.kpis && r.kpis.length > 0 && <KpiRow kpis={r.kpis} currency={currency} />}
      {hasChart && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div role="radiogroup" aria-label="Visualisation" className="flex flex-wrap gap-1">
            {types.map((t) => (
              <button key={t} role="radio" aria-checked={type === t} onClick={() => setType(t)}
                className={cx("rounded px-2 py-1 text-xs", type === t ? "bg-ink text-white" : "text-ink-2 hover:bg-paper-2")}>{CHART_LABEL[t]}</button>
            ))}
          </div>
          {onDrill && type !== "table" && <p className="text-xs text-muted">Click a bar to drill down</p>}
        </div>
      )}
      {hasChart && type !== "table" ? (
        <figure ref={chartRef} className="rounded-md border border-line bg-surface p-2">
          <ResultChart result={r} type={type} currency={currency} height={compact ? 240 : 300} onSelect={onDrill} />
          <figcaption className="sr-only">{chartTitle}. The same values are available in the table view.</figcaption>
        </figure>
      ) : r.columns.length > 0 && r.rows.length > 0 ? <ResultTable result={r} currency={currency} /> : null}
      {hasChart && type !== "table" && !compact && (
        <details className="rounded-md border border-line bg-surface">
          <summary className="cursor-pointer px-3 py-2 text-sm text-ink-2">Data table ({r.rows.length} rows)</summary>
          <div className="p-2"><ResultTable result={r} currency={currency} /></div>
        </details>
      )}
      {r.notes?.length > 0 && (
        <ul className="space-y-1 text-[13px] text-muted">{r.notes.map((n) => <li key={n} className="flex gap-1.5"><Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />{n}</li>)}</ul>
      )}
      {showActions && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          <Button size="sm" variant={inspect ? "primary" : "secondary"} onClick={() => (onInspect ? onInspect() : setInspect(!inspect))} aria-expanded={onInspect ? undefined : inspect}><Search className="size-3.5" /> Show calculation</Button>
          <Button size="sm" variant="ghost" onClick={() => download(`${base}/analysis/runs/${run.id}/export?format=csv`).catch((e) => toast(errorMessage(e), "error"))}><Download className="size-3.5" /> CSV</Button>
          <Button size="sm" variant="ghost" onClick={() => download(`${base}/analysis/runs/${run.id}/export?format=xlsx`).catch((e) => toast(errorMessage(e), "error"))}><Download className="size-3.5" /> XLSX</Button>
          {hasChart && type !== "table" && <Button size="sm" variant="ghost" onClick={() => exportPng(chartRef.current, chartTitle)}><FileImage className="size-3.5" /> PNG</Button>}
          {can("analyst") && <Button size="sm" variant="ghost" onClick={() => setSaveOpen(true)}><Save className="size-3.5" /> Save visualisation</Button>}
          {can("analyst") && <Button size="sm" variant="ghost" onClick={() => setAddOpen(true)}><FilePlus2 className="size-3.5" /> Add to report</Button>}
        </div>
      )}
      {inspect && <div className="rounded-md border border-line bg-surface p-4"><Inspector run={run} onClose={() => setInspect(false)} /></div>}
      <AddToReport run={run} open={addOpen} onClose={() => setAddOpen(false)} title={chartTitle} />
      <Dialog open={saveOpen} onClose={() => setSaveOpen(false)} title="Save visualisation"
        footer={<><Button variant="ghost" onClick={() => setSaveOpen(false)}>Cancel</Button><Button variant="primary" onClick={async () => {
          try {
            await post(`${base}/analysis/visualizations`, { run_id: run.id, title: vizTitle, chart_type: type, note: vizNote, conversation_id: conversationId });
            toast("Visualisation saved to Explore");
            setSaveOpen(false);
          } catch (e) { toast(errorMessage(e), "error"); }
        }}>Save</Button></>}>
        <div className="space-y-3">
          <Field label="Title" htmlFor="vt"><Input id="vt" value={vizTitle} onChange={(e) => setVizTitle(e.target.value)} /></Field>
          <Field label="Note (optional)" htmlFor="vn"><Textarea id="vn" value={vizNote} onChange={(e) => setVizNote(e.target.value)} /></Field>
        </div>
      </Dialog>
    </div>
  );
}

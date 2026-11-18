"use client";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Copy, Download, Eye, Pencil, Plus, Printer, RefreshCw, Trash2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ResultChart } from "@/components/analysis/chart";
import { KpiRow, ResultTable } from "@/components/analysis/result";
import { useColumns, useMetrics } from "@/components/datasets";
import { Badge, Button, Confirm, cx, Dialog, ErrorNote, Field, Input, PageHeader, Select, Skeleton, Textarea, useToast } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { del, download, errorMessage, patch, post } from "@/lib/api";
import { fmtDate, fmtPct, fmtValue } from "@/lib/format";
import type { AnalysisResult, Insight, Plan, Report, ReportSection } from "@/lib/types";

const KIND_LABEL: Record<string, string> = { summary: "Executive summary", kpis: "Key metrics", chart: "Chart", table: "Table", insight: "Insight", text: "Text", recommendations: "Recommendations" };

function SummaryBlock({ s, currency }: { s: Record<string, any>; currency: string }) {
  const list = (title: string, items?: string[]) => items?.length ? <div className="mt-4"><h4 className="text-[13px] font-semibold text-forest">{title}</h4><ul className="mt-1 space-y-1 font-serif text-[15.5px] leading-relaxed">{items.map((x) => <li key={x} className="flex gap-2"><span aria-hidden>–</span>{x}</li>)}</ul></div> : null;
  return (
    <div>
      <p className="text-[13px] text-muted">{s.business_context?.workspace} · {s.business_context?.dataset} (v{s.business_context?.dataset_version}, {s.business_context?.rows?.toLocaleString()} rows) · {s.reporting_period?.current} compared with {s.reporting_period?.baseline}</p>
      {s.business_context?.is_demo && <Badge tone="brass" className="mt-1">synthetic demonstration data</Badge>}
      {s.kpis?.length > 0 && (
        <dl className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line sm:grid-cols-3">
          {s.kpis.map((k: any) => <div key={k.metric} className="bg-surface p-3"><dt className="text-xs text-muted">{k.metric}</dt><dd className="tnum mt-0.5 text-xl font-semibold">{fmtValue(k.current, k.unit, currency)}</dd>
            <dd className="text-xs text-muted"><span className={cx("tnum", (k.change_pct ?? 0) < 0 ? "text-rust" : "text-forest")}>{k.unit === "percent" ? fmtValue((k.current ?? 0) - (k.baseline ?? 0), "percent_points") : fmtPct(k.change_pct)}</span> vs {fmtValue(k.baseline, k.unit, currency)}</dd></div>)}
        </dl>)}
      {list("Main performance changes", s.main_changes)}
      {list("Product and regional contributors", s.contributors)}
      {s.findings?.length > 0 && list("Significant findings", s.findings.map((f: any) => `${f.title}. ${f.finding}`))}
      {list("Anomaly observations", s.anomalies)}
      {s.interpretation?.text && <div className="mt-4 rounded-md border border-line bg-paper/60 p-3"><h4 className="text-[13px] font-semibold">Interpretation</h4><p className="mt-1 font-serif text-[15.5px] leading-relaxed">{s.interpretation.text}</p><p className="mt-1 text-xs text-muted">{s.interpretation.source}. The sections above are exact calculations.</p></div>}
      {list("Important limitations", s.limitations)}
      {list("Suggested next investigations", s.next_investigations)}
    </div>
  );
}

function SectionBody({ sec, currency }: { sec: ReportSection; currency: string }) {
  const snap = sec.snapshot as AnalysisResult & Record<string, any>;
  if (sec.kind === "summary") return <SummaryBlock s={sec.snapshot} currency={currency} />;
  if (sec.kind === "text" || sec.kind === "recommendations")
    return <div className="doc-prose font-serif text-[16px] leading-relaxed">{(sec.body || "Empty section. Use Edit to write it.").split("\n").map((l, i) => l.trim().startsWith("-") ? <p key={i} className="pl-4">– {l.trim().slice(1).trim()}</p> : <p key={i}>{l}</p>)}</div>;
  if (sec.kind === "insight") return (
    <div className="space-y-2"><div className="flex gap-1.5"><Badge tone={snap.severity === "high" ? "rust" : snap.severity === "medium" ? "brass" : "neutral"}>{snap.severity}</Badge><Badge>{snap.category_label}</Badge></div>
      <p className="font-serif text-[16px] leading-relaxed">{snap.finding}</p><p className="text-xs text-muted">Method: {snap.method}</p>{snap.limitations && <p className="text-xs text-muted">Limitations: {snap.limitations}</p>}</div>);
  const hasChart = sec.kind === "chart" && snap.chart && !["kpi", "table"].includes(snap.chart.type ?? "") && snap.rows?.length;
  return (
    <div className="space-y-3">
      {sec.body && <p className="font-serif text-[16px] leading-relaxed">{sec.body}</p>}
      {snap.narrative && <p className="font-serif text-[16px] leading-relaxed">{snap.narrative}</p>}
      {snap.kpis && <KpiRow kpis={snap.kpis} currency={currency} />}
      {hasChart ? <div className="rounded-md border border-line p-2"><ResultChart result={snap} type={snap.chart!.type} currency={currency} height={260} /></div> : null}
      {(sec.kind === "table" || hasChart) && snap.columns?.length > 0 && <ResultTable result={snap} currency={currency} maxRows={sec.kind === "table" ? 50 : 12} />}
      {snap.notes?.map((n: string) => <p key={n} className="text-xs text-muted">{n}</p>)}
      {snap.provenance && <p className="text-xs text-muted">Source: {snap.provenance.dataset.name} v{snap.provenance.dataset.version_number} · {snap.provenance.records_in_scope.toLocaleString()} records · {snap.provenance.date_range} · computed {fmtDate(snap.provenance.executed_at, true)}. {snap.provenance.methodology}</p>}
    </div>
  );
}

function AddSection({ report, open, onClose }: { report: Report; open: boolean; onClose: () => void }) {
  const { base, wid } = useWorkspace();
  const qc = useQueryClient();
  const [kind, setKind] = useState("chart");
  const metrics = useMetrics(report.dataset_id);
  const cols = useColumns(report.dataset_id);
  const viz = useWsQuery<{ visualizations: { id: string; title: string; run: { id: string } | null }[] }>(["visualizations"], "/analysis/visualizations", { enabled: open });
  const ins = useWsQuery<{ insights: Insight[] }>(["insights", report.dataset_id, "active"], report.dataset_id ? `/insights?dataset_id=${report.dataset_id}&status=active` : null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [source, setSource] = useState("build");
  const [vizId, setVizId] = useState("");
  const [insId, setInsId] = useState("");
  const [metricIds, setMetricIds] = useState<string[]>([]);
  const [b, setB] = useState({ intent: "breakdown", metric: "", dim: "", grain: "month" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const dims = cols.data?.columns.filter((c) => c.semantic_type === "dimension" && !c.excluded) ?? [];
  const dateCol = cols.data?.columns.find((c) => c.business_meaning === "order_date")?.name ?? cols.data?.columns.find((c) => c.dtype === "date")?.name;
  const submit = async () => {
    setBusy(true); setErr("");
    try {
      const payload: Record<string, unknown> = { kind, title, body };
      if (kind === "chart" || kind === "table") {
        if (source === "saved") payload.run_id = viz.data?.visualizations.find((v) => v.id === vizId)?.run?.id;
        else {
          const metric = b.metric || metrics.data?.metrics[0]?.id;
          const plan: Plan = { intent: b.intent, dataset_id: report.dataset_id!, measures: [{ kind: "metric", metric_id: metric }], group_by: b.intent === "trend" ? [] : [b.dim || dims[0]?.name].filter(Boolean) as string[], filters: [], limit: b.intent === "trend" ? 500 : 15 };
          if (b.intent === "trend") plan.time = { column: dateCol!, grain: b.grain, start: report.period_start || null, end: report.period_end || null };
          if (b.intent === "decompose_change") { plan.time = { column: dateCol! }; plan.comparison = { mode: "previous_period", grain: "month" }; }
          payload.plan = plan;
        }
      }
      if (kind === "insight") payload.insight_id = insId;
      if (kind === "kpis") payload.metric_ids = metricIds;
      await post(`${base}/reports/${report.id}/sections`, payload);
      qc.invalidateQueries({ queryKey: [wid, "report", report.id] });
      onClose(); setTitle(""); setBody("");
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={onClose} wide title="Add a section" footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Add section</Button></>}>
      <div className="space-y-4">
        {err && <ErrorNote>{err}</ErrorNote>}
        <div role="radiogroup" aria-label="Section type" className="flex flex-wrap gap-1.5">
          {["summary", "kpis", "chart", "table", "insight", "text", "recommendations"].map((k) => <button key={k} role="radio" aria-checked={kind === k} onClick={() => setKind(k)} className={cx("rounded-md border px-2.5 py-1.5 text-sm", kind === k ? "border-forest bg-forest-wash" : "border-line-2")}>{KIND_LABEL[k]}</button>)}
        </div>
        {kind !== "summary" && <Field label="Section title" htmlFor="stl"><Input id="stl" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>}
        {kind === "summary" && <p className="text-sm text-muted">Computes KPIs for the reporting period against the previous period, contributors, current insights, anomalies, limitations and suggested next steps.</p>}
        {kind === "kpis" && <fieldset className="grid grid-cols-2 gap-1"><legend className="mb-1 text-[13px] font-medium text-ink-2">Metrics (up to 4)</legend>{metrics.data?.metrics.map((m) => <label key={m.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={metricIds.includes(m.id)} disabled={!metricIds.includes(m.id) && metricIds.length >= 4} onChange={(e) => setMetricIds(e.target.checked ? [...metricIds, m.id] : metricIds.filter((x) => x !== m.id))} />{m.name}</label>)}</fieldset>}
        {(kind === "chart" || kind === "table") && (
          <>
            <Select aria-label="Source" value={source} onChange={(e) => setSource(e.target.value)}><option value="build">Build a new analysis</option><option value="saved">Use a saved visualisation</option></Select>
            {source === "saved" ? (
              <Select aria-label="Saved visualisation" value={vizId} onChange={(e) => setVizId(e.target.value)}><option value="">Choose</option>{viz.data?.visualizations.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}</Select>
            ) : (
              <div className="grid gap-2 sm:grid-cols-3">
                <Select aria-label="Analysis" value={b.intent} onChange={(e) => setB({ ...b, intent: e.target.value })}><option value="breakdown">Breakdown</option><option value="rank">Ranking</option><option value="trend">Monthly trend</option><option value="contribution">Contribution</option><option value="decompose_change">Change vs previous month</option></Select>
                <Select aria-label="Metric" value={b.metric} onChange={(e) => setB({ ...b, metric: e.target.value })}>{metrics.data?.metrics.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select>
                {b.intent !== "trend" && <Select aria-label="Dimension" value={b.dim} onChange={(e) => setB({ ...b, dim: e.target.value })}>{dims.map((d) => <option key={d.name} value={d.name}>{d.display_name}</option>)}</Select>}
              </div>
            )}
            <Field label="Commentary (optional)" htmlFor="cm"><Textarea id="cm" rows={2} value={body} onChange={(e) => setBody(e.target.value)} /></Field>
          </>
        )}
        {kind === "insight" && <Select aria-label="Insight" value={insId} onChange={(e) => setInsId(e.target.value)}><option value="">Choose an insight</option>{ins.data?.insights.map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}</Select>}
        {(kind === "text" || kind === "recommendations") && <Field label="Text" htmlFor="tx" hint="Start lines with “-” for bullet points."><Textarea id="tx" rows={6} value={body} onChange={(e) => setBody(e.target.value)} /></Field>}
      </div>
    </Dialog>
  );
}

export default function ReportStudio() {
  const { reportId } = useParams<{ reportId: string }>();
  const { base, wid, ws, can } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const router = useRouter();
  const q = useWsQuery<{ report: Report }>(["report", reportId], `/reports/${reportId}`);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<ReportSection | null>(null);
  const [edit, setEdit] = useState({ title: "", body: "" });
  const [meta, setMeta] = useState<null | { title: string; subtitle: string; period_start: string; period_end: string }>(null);
  const [remove, setRemove] = useState(false);
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: [wid, "report", reportId] });
  const r = q.data?.report;
  if (q.error) return <ErrorNote>{errorMessage(q.error)}</ErrorNote>;
  if (!r) return <Skeleton className="h-96" />;
  const secs = r.sections ?? [];
  const currency = ws?.currency ?? "USD";
  const move = async (i: number, d: number) => {
    const ids = secs.map((s) => s.id);
    [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
    await post(`${base}/reports/${reportId}/order`, { section_ids: ids }); refresh();
  };
  const exp = async (fmt: string) => { setBusy(fmt); try { await download(`${base}/reports/${reportId}/export?format=${fmt}`); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); } };
  return (
    <div className="mx-auto max-w-7xl">
      <div className="print:hidden">
        <PageHeader crumbs={[{ href: "/app/reports", label: "Reports" }, { label: r.title }]} title={r.title}
          description={<>{r.dataset_name ?? "No dataset"} · reporting period {r.period_label || "latest month in the data"} · <Badge tone={r.status === "final" ? "forest" : "neutral"}>{r.status}</Badge></>}
          actions={<>
            <Button size="sm" variant={preview ? "primary" : "secondary"} onClick={() => setPreview(!preview)}><Eye className="size-3.5" />{preview ? "Back to editing" : "Preview"}</Button>
            <Button size="sm" variant="primary" loading={busy === "pdf"} onClick={() => exp("pdf")}><Download className="size-3.5" />PDF</Button>
            <Button size="sm" loading={busy === "csv"} onClick={() => exp("csv")}>CSV</Button>
            <Button size="sm" loading={busy === "xlsx"} onClick={() => exp("xlsx")}>XLSX</Button>
            <Button size="sm" variant="ghost" onClick={() => window.print()}><Printer className="size-3.5" />Print</Button>
          </>} />
      </div>
      <div className={cx("grid gap-6", !preview && "lg:grid-cols-[17rem_1fr]")}>
        {!preview && (
          <aside className="space-y-3 print:hidden" aria-label="Report outline">
            {can("analyst") && <Button variant="primary" className="w-full" onClick={() => setAdding(true)}><Plus className="size-4" />Add section</Button>}
            <ol className="space-y-1">{secs.map((s, i) => (
              <li key={s.id} className="flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1.5 text-sm">
                <a href={`#sec-${s.id}`} className="min-w-0 flex-1 truncate hover:text-forest"><span className="text-xs text-muted">{KIND_LABEL[s.kind]}</span><span className="block truncate">{s.title || "Untitled"}</span></a>
                {can("analyst") && <><button aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)} className="rounded p-0.5 text-muted hover:bg-paper-2 disabled:opacity-30"><ArrowUp className="size-3.5" /></button>
                  <button aria-label="Move down" disabled={i === secs.length - 1} onClick={() => move(i, 1)} className="rounded p-0.5 text-muted hover:bg-paper-2 disabled:opacity-30"><ArrowDown className="size-3.5" /></button></>}
              </li>))}</ol>
            {can("analyst") && <div className="space-y-1.5 border-t border-line pt-3">
              <Button size="sm" className="w-full" onClick={() => setMeta({ title: r.title, subtitle: r.subtitle, period_start: r.period_start, period_end: r.period_end })}><Pencil className="size-3.5" />Title and period</Button>
              <Button size="sm" className="w-full" onClick={async () => { await patch(`${base}/reports/${reportId}`, { status: r.status === "final" ? "draft" : "final" }); refresh(); }}>{r.status === "final" ? "Mark as draft" : "Mark as final"}</Button>
              <Button size="sm" variant="ghost" className="w-full" onClick={async () => { const d = await post<{ report: Report }>(`${base}/reports/${reportId}/duplicate`); router.push(`/app/reports/${d.report.id}`); }}><Copy className="size-3.5" />Duplicate</Button>
              <Button size="sm" variant="danger" className="w-full" onClick={() => setRemove(true)}><Trash2 className="size-3.5" />Delete report</Button>
            </div>}
          </aside>
        )}
        <article className={cx("mx-auto w-full rounded-sm border border-line bg-surface px-8 py-10 shadow-lift print:border-0 print:shadow-none sm:px-14", preview ? "max-w-[52rem]" : "max-w-[60rem]")} aria-label="Report document">
          <header className="border-b border-ink pb-5">
            <p className="text-xs text-muted">{ws?.name} · ClearMetric report</p>
            <h1 className="mt-2 font-serif text-[34px] leading-tight">{r.title}</h1>
            {r.subtitle && <p className="mt-1 font-serif text-lg text-ink-2">{r.subtitle}</p>}
            <p className="mt-3 text-[13px] text-muted">Data: {r.dataset_name ?? "—"}{r.dataset_version ? ` (version ${r.dataset_version})` : ""} · Period: {r.period_label || "latest month in the data"} · Updated {fmtDate(r.updated_at, true)}</p>
            {r.is_demo && <Badge tone="brass" className="mt-2">Synthetic demonstration data, not real business records</Badge>}
          </header>
          {!secs.length && <p className="py-10 text-center text-muted">This report is empty. Add an executive summary, KPIs, charts, insights or text.</p>}
          {secs.map((s) => (
            <section key={s.id} id={`sec-${s.id}`} className="group relative border-b border-line py-7 last:border-0">
              <div className="mb-3 flex items-start justify-between gap-3">
                <h2 className="text-xl font-semibold">{s.title || KIND_LABEL[s.kind]}</h2>
                {!preview && can("analyst") && (
                  <div className="flex gap-0.5 print:hidden">
                    {(s.kind === "text" || s.kind === "recommendations" || s.kind === "chart" || s.kind === "table") && <Button size="sm" variant="ghost" onClick={() => { setEditing(s); setEdit({ title: s.title, body: s.body }); }} aria-label="Edit section"><Pencil className="size-3.5" /></Button>}
                    {["summary", "chart", "table", "kpis", "insight"].includes(s.kind) && <Button size="sm" variant="ghost" title="Recompute with current data and metric definitions" aria-label="Refresh section" loading={busy === s.id}
                      onClick={async () => { setBusy(s.id); try { await post(`${base}/reports/${reportId}/sections/${s.id}/refresh`); toast("Section recomputed"); refresh(); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); } }}><RefreshCw className="size-3.5" /></Button>}
                    <Button size="sm" variant="ghost" aria-label="Delete section" onClick={async () => { await del(`${base}/reports/${reportId}/sections/${s.id}`); refresh(); }}><Trash2 className="size-3.5" /></Button>
                  </div>)}
              </div>
              <SectionBody sec={s} currency={currency} />
            </section>))}
          <footer className="mt-6 border-t border-line pt-4 text-xs text-muted">All figures were computed by ClearMetric’s deterministic engine from validated analysis plans. Each section stores a snapshot, so this report changes only when a section is refreshed.</footer>
        </article>
      </div>
      <AddSection report={r} open={adding} onClose={() => setAdding(false)} />
      <Dialog open={!!editing} onClose={() => setEditing(null)} title="Edit section" footer={<><Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
        <Button variant="primary" onClick={async () => { await patch(`${base}/reports/${reportId}/sections/${editing!.id}`, edit); setEditing(null); refresh(); }}>Save section</Button></>}>
        <div className="space-y-3"><Field label="Title" htmlFor="et"><Input id="et" value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></Field>
          <Field label={editing?.kind === "chart" || editing?.kind === "table" ? "Commentary" : "Text"} htmlFor="eb"><Textarea id="eb" rows={8} value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} /></Field></div>
      </Dialog>
      <Dialog open={!!meta} onClose={() => setMeta(null)} title="Report details" footer={<><Button variant="ghost" onClick={() => setMeta(null)}>Cancel</Button>
        <Button variant="primary" onClick={async () => { await patch(`${base}/reports/${reportId}`, meta); setMeta(null); refresh(); toast("Saved. Refresh the summary to apply a new period."); }}>Save</Button></>}>
        {meta && <div className="space-y-3">
          <Field label="Title" htmlFor="mt"><Input id="mt" value={meta.title} onChange={(e) => setMeta({ ...meta, title: e.target.value })} /></Field>
          <Field label="Subtitle" htmlFor="ms"><Input id="ms" value={meta.subtitle} onChange={(e) => setMeta({ ...meta, subtitle: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-2"><Field label="Period from" htmlFor="mp1"><Input id="mp1" type="date" value={meta.period_start} onChange={(e) => setMeta({ ...meta, period_start: e.target.value })} /></Field>
            <Field label="to" htmlFor="mp2"><Input id="mp2" type="date" value={meta.period_end} onChange={(e) => setMeta({ ...meta, period_end: e.target.value })} /></Field></div>
        </div>}
      </Dialog>
      <Confirm open={remove} onClose={() => setRemove(false)} danger title="Delete report" confirmLabel="Delete report" onConfirm={async () => { await del(`${base}/reports/${reportId}`); qc.invalidateQueries({ queryKey: [wid, "reports"] }); router.push("/app/reports"); }}>
        “{r.title}” and its {secs.length} sections will be deleted.
      </Confirm>
    </div>
  );
}

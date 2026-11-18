"use client";
import { useQueryClient } from "@tanstack/react-query";
import { Bookmark, BookmarkCheck, EyeOff, FilePlus2, Lightbulb, MessageSquareText, RefreshCw, Rows3, Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ResultView } from "@/components/analysis/result";
import { DatasetSelect, useActiveDataset } from "@/components/datasets";
import { Badge, Button, cx, Dialog, Empty, ErrorNote, Field, PageHeader, Select, Skeleton, Textarea, useToast } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { errorMessage, patch, post } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Insight, Report, Run } from "@/lib/types";

const SEV = { high: "rust", medium: "brass", low: "neutral" } as const;

function Calculations({ c }: { c: Record<string, any> }) {
  const simple = Object.entries(c).filter(([k, v]) => !["affected_filters", "segments", "monthly", "index", "issue", "sql", "notes", "bounds"].includes(k) && (typeof v !== "object" || v === null));
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {simple.map(([k, v]) => <div key={k} className="rounded-md border border-line px-2.5 py-1.5"><dt className="text-[11.5px] text-muted">{k.replace(/_/g, " ")}</dt><dd className="tnum text-sm font-medium">{typeof v === "number" ? v.toLocaleString("en-US", { maximumFractionDigits: 3 }) : String(v)}</dd></div>)}
      </dl>
      {Array.isArray(c.segments) && (
        <table className="w-full text-[13px]"><caption className="mb-1 text-left text-xs text-muted">Change by segment</caption>
          <thead className="text-left text-ink-2"><tr><th className="py-1 font-medium">Segment</th><th className="py-1 text-right font-medium">Change</th><th className="py-1 text-right font-medium">Share of change</th></tr></thead>
          <tbody className="divide-y divide-line">{c.segments.map((s: any) => <tr key={s.segment}><td className="py-1">{s.segment}</td><td className={cx("tnum py-1 text-right", s.change < 0 && "text-rust")}>{s.change?.toLocaleString("en-US", { maximumFractionDigits: 2 })}</td><td className="tnum py-1 text-right">{s.share === null ? "—" : `${s.share.toFixed(1)}%`}</td></tr>)}</tbody></table>)}
      {c.monthly && <p className="text-xs text-muted">Monthly values: {Object.entries(c.monthly).map(([m, v]) => `${m.slice(0, 7)}: ${Number(v).toFixed(0)}`).join(", ")}</p>}
      {c.index && <p className="text-xs text-muted">Seasonal index: {Object.entries(c.index).map(([m, v]) => `${m} ${v}`).join(", ")}</p>}
      {c.bounds && <p className="text-xs text-muted">Bounds: below {c.bounds.low?.toFixed(2)} or above {c.bounds.high?.toFixed(2)} (median {c.bounds.median?.toFixed(2)})</p>}
      {c.sql && <pre className="overflow-x-auto rounded bg-ink p-2 text-xs text-[#cde5d9]">{c.sql}</pre>}
    </div>
  );
}

function Detail({ ins, onChanged }: { ins: Insight; onChanged: () => void }) {
  const { base, can, wid } = useWorkspace();
  const toast = useToast();
  const router = useRouter();
  const [evidence, setEvidence] = useState<Run | null>(null);
  const [evBusy, setEvBusy] = useState(false);
  const [records, setRecords] = useState<null | { columns: string[]; rows: unknown[][]; total: number }>(null);
  const [note, setNote] = useState(ins.note);
  const [addOpen, setAddOpen] = useState(false);
  const reports = useWsQuery<{ reports: Report[] }>(["reports"], "/reports", { enabled: addOpen });
  const [target, setTarget] = useState("new");
  useEffect(() => { setEvidence(null); setRecords(null); setNote(ins.note); }, [ins.id, ins.note]);
  const setStatus = async (status: string) => { await patch(`${base}/insights/${ins.id}`, { status }); toast(status === "saved" ? "Insight saved" : status === "dismissed" ? "Insight dismissed" : "Insight restored"); onChanged(); };
  const affected = ins.calculations?.affected_filters as { column: string; op: string; value: unknown }[] | undefined;
  return (
    <article className="rounded-lg border border-line bg-surface" aria-label="Insight detail">
      <header className="border-b border-line p-5">
        <div className="flex flex-wrap items-center gap-1.5"><Badge tone={SEV[ins.severity]}>{ins.severity} importance</Badge><Badge>{ins.category_label}</Badge>{ins.status !== "new" && <Badge tone="forest">{ins.status}</Badge>}</div>
        <h2 className="mt-2 text-xl font-semibold leading-snug">{ins.title}</h2>
        <p className="mt-2 leading-relaxed text-ink-2">{ins.finding}</p>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
          {[["Metric", ins.metric || "—"], ["Period", ins.date_range || "—"], ["Baseline", ins.baseline || "—"], ["Detected", fmtDate(ins.created_at)]].map(([k, v]) => <div key={k}><dt className="text-xs text-muted">{k}</dt><dd>{v}</dd></div>)}
        </dl>
      </header>
      <div className="space-y-5 p-5">
        <section><h3 className="text-sm font-semibold">Supporting calculations</h3><div className="mt-2"><Calculations c={ins.calculations} /></div></section>
        <section><h3 className="text-sm font-semibold">Method</h3><p className="mt-1 text-sm text-ink-2">{ins.method}</p>
          <p className="mt-2 text-xs text-muted">Importance: high when the effect is large relative to the configured threshold (see method); medium when it passes the threshold; low for informational patterns.</p></section>
        {ins.limitations && <section><h3 className="text-sm font-semibold">Limitations</h3><p className="mt-1 text-sm text-ink-2">{ins.limitations}</p></section>}
        <div className="flex flex-wrap gap-2">
          {ins.evidence_plan && <Button size="sm" loading={evBusy} onClick={async () => { setEvBusy(true); try { setEvidence((await post<{ run: Run }>(`${base}/insights/${ins.id}/evidence`)).run); } catch (e) { toast(errorMessage(e), "error"); } finally { setEvBusy(false); } }}><Search className="size-3.5" />Inspect supporting calculation</Button>}
          {affected?.length ? <Button size="sm" onClick={async () => {
            try { setRecords(await post(`${base}/datasets/${ins.dataset_id}/preview`, { page: 1, page_size: 50, filters: affected.map((f) => (f.op === "between" ? { ...f } : f)) })); } catch (e) { toast(errorMessage(e), "error"); }
          }}><Rows3 className="size-3.5" />View affected records</Button> : null}
          {ins.suggested_question && <Button size="sm" onClick={() => router.push(`/app/analyst?new=1&dataset=${ins.dataset_id}&q=${encodeURIComponent(ins.suggested_question)}`)}><MessageSquareText className="size-3.5" />Ask a follow-up</Button>}
          {can("analyst") && (ins.status === "saved" ? <Button size="sm" variant="ghost" onClick={() => setStatus("new")}><BookmarkCheck className="size-3.5" />Saved</Button> : <Button size="sm" variant="ghost" onClick={() => setStatus("saved")}><Bookmark className="size-3.5" />Save</Button>)}
          {can("analyst") && (ins.status === "dismissed" ? <Button size="sm" variant="ghost" onClick={() => setStatus("new")}>Restore</Button> : <Button size="sm" variant="ghost" onClick={() => setStatus("dismissed")}><EyeOff className="size-3.5" />Dismiss</Button>)}
          {can("analyst") && <Button size="sm" variant="ghost" onClick={() => setAddOpen(true)}><FilePlus2 className="size-3.5" />Add to report</Button>}
        </div>
        {can("analyst") && <div className="flex items-end gap-2"><Field label="Note" htmlFor="in"><Textarea id="in" rows={2} value={note} onChange={(e) => setNote(e.target.value)} className="min-w-72" /></Field>
          <Button size="sm" onClick={async () => { await patch(`${base}/insights/${ins.id}`, { note }); toast("Note saved"); onChanged(); }}>Save note</Button></div>}
        {evidence && <section className="rounded-md border border-line p-3"><h3 className="mb-2 text-sm font-semibold">Supporting calculation (recomputed now)</h3><ResultView run={evidence} title={ins.title} compact /></section>}
        {records && <section className="rounded-md border border-line"><h3 className="border-b border-line px-3 py-2 text-sm font-semibold">Affected records ({records.total.toLocaleString()}{records.total > 50 ? ", first 50 shown" : ""})</h3>
          <div className="max-h-80 overflow-auto"><table className="w-full text-xs"><thead className="sticky top-0 bg-paper"><tr>{records.columns.map((c) => <th key={c} className="whitespace-nowrap px-2 py-1.5 text-left font-medium">{c}</th>)}</tr></thead>
            <tbody className="divide-y divide-line">{records.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className="whitespace-nowrap px-2 py-1">{v === null ? "—" : String(v).replace("T00:00:00", "")}</td>)}</tr>)}</tbody></table></div></section>}
      </div>
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="Add insight to report" footer={<><Button variant="ghost" onClick={() => setAddOpen(false)}>Cancel</Button>
        <Button variant="primary" onClick={async () => {
          try {
            if (target === "new") { const r = await post<{ report: Report }>(`${base}/reports`, { title: "Insights brief", dataset_id: ins.dataset_id, from_insight_ids: [ins.id] }); router.push(`/app/reports/${r.report.id}`); }
            else { await post(`${base}/reports/${target}/sections`, { kind: "insight", insight_id: ins.id }); toast("Added to report"); setAddOpen(false); }
          } catch (e) { toast(errorMessage(e), "error"); }
        }}>Add</Button></>}>
        <Field label="Report" htmlFor="ar"><Select id="ar" value={target} onChange={(e) => setTarget(e.target.value)}><option value="new">Create a new report</option>{reports.data?.reports.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</Select></Field>
      </Dialog>
    </article>
  );
}

function Feed() {
  const params = useSearchParams();
  const router = useRouter();
  const { base, wid, can } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const { id: dsId, choose, datasets } = useActiveDataset();
  const [cat, setCat] = useState("");
  const [sev, setSev] = useState("");
  const [status, setStatus] = useState("active");
  const list = useWsQuery<{ insights: Insight[]; categories: Record<string, string> }>(["insights", dsId, cat, sev, status], dsId ? `/insights?dataset_id=${dsId}&status=${status}${cat ? `&category=${cat}` : ""}${sev ? `&severity=${sev}` : ""}` : null);
  const [scanning, setScanning] = useState(false);
  const [err, setErr] = useState("");
  const sel = params.get("i") ?? list.data?.insights[0]?.id;
  const selected = list.data?.insights.find((i) => i.id === sel) ?? list.data?.insights[0];
  const scan = async () => {
    setScanning(true); setErr("");
    try { const r = await post<{ insights: Insight[] }>(`${base}/insights/generate`, { dataset_id: dsId }); toast(`Scan complete: ${r.insights.length} findings`); qc.invalidateQueries({ queryKey: [wid, "insights"] }); }
    catch (e) { setErr(errorMessage(e)); } finally { setScanning(false); }
  };
  const ws = useWorkspace().ws;
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Insights Center" description="Findings detected by statistical checks on your data. Each one shows how it was calculated and what it can’t tell you."
        actions={<><DatasetSelect value={dsId} onChange={choose} datasets={datasets} />{can("analyst") && <Button variant="primary" loading={scanning} onClick={scan} disabled={!dsId}><RefreshCw className="size-4" />Scan dataset</Button>}</>} />
      {err && <div className="mb-4"><ErrorNote>{err}</ErrorNote></div>}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select aria-label="Category" value={cat} onChange={(e) => setCat(e.target.value)} className="h-8.5 w-auto text-[13px]"><option value="">All categories</option>{Object.entries(list.data?.categories ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
        <Select aria-label="Importance" value={sev} onChange={(e) => setSev(e.target.value)} className="h-8.5 w-auto text-[13px]"><option value="">Any importance</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></Select>
        <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-8.5 w-auto text-[13px]"><option value="active">New and saved</option><option value="saved">Saved</option><option value="dismissed">Dismissed</option><option value="">All</option></Select>
        <span className="ml-auto text-xs text-muted">Thresholds: change ≥ {ws?.insight_settings?.change_threshold_pct ?? 10}%, concentration ≥ {ws?.insight_settings?.concentration_threshold_pct ?? 40}%, outliers beyond {ws?.insight_settings?.outlier_iqr_k ?? 3}×IQR. Change them in Settings.</span>
      </div>
      {list.isLoading && <Skeleton className="h-96" />}
      {list.data && !list.data.insights.length && (
        <Empty icon={<Lightbulb className="size-6" />} title={status === "active" && !cat && !sev ? "No insights yet for this dataset" : "Nothing matches these filters"}
          action={can("analyst") && status === "active" && <Button variant="primary" onClick={scan} loading={scanning}>Scan dataset</Button>}>
          A scan checks recent changes, the segments behind them, concentration, variability, unusual records, trends, margins, correlations and data quality.
        </Empty>
      )}
      {!!list.data?.insights.length && (
        <div className="grid gap-6 lg:grid-cols-[24rem_1fr]">
          <ol className="space-y-2" aria-label="Insight feed">
            {list.data.insights.map((i) => (
              <li key={i.id}>
                <button onClick={() => router.replace(`/app/insights?i=${i.id}`, { scroll: false })} aria-current={selected?.id === i.id}
                  className={cx("w-full rounded-lg border bg-surface p-3.5 text-left transition-colors", selected?.id === i.id ? "border-forest" : "border-line hover:border-line-2", i.status === "dismissed" && "opacity-60")}>
                  <span className="flex items-center gap-1.5 text-[11.5px] text-muted"><span className={cx("size-2 rounded-full", i.severity === "high" ? "bg-rust" : i.severity === "medium" ? "bg-brass" : "bg-line-2")} aria-hidden />{i.category_label}{i.status === "saved" && <BookmarkCheck className="size-3 text-forest" />}</span>
                  <span className="mt-1 block text-[14.5px] font-medium leading-snug">{i.title}</span>
                  <span className="mt-1 line-clamp-2 block text-[13px] text-muted">{i.finding}</span>
                </button>
              </li>))}
          </ol>
          {selected && <Detail ins={selected} onChanged={() => qc.invalidateQueries({ queryKey: [wid, "insights"] })} />}
        </div>
      )}
    </div>
  );
}

export default function InsightsPage() {
  return <Suspense fallback={<Skeleton className="h-96" />}><Feed /></Suspense>;
}

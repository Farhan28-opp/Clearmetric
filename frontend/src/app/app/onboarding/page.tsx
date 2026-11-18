"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Database, FileSpreadsheet, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Logo } from "@/components/brand";
import { TermsForm, TermsResult } from "@/components/terms";
import { Badge, Button, ButtonLink, cx, ErrorNote, Field, Input, Select, Skeleton } from "@/components/ui";
import { Uploader } from "@/components/upload";
import { useWorkspace } from "@/components/workspace";
import { errorMessage, get, post } from "@/lib/api";
import type { Column, Dataset, Insight } from "@/lib/types";

const STEPS = ["Workspace", "Starting data", "Understand", "Business terms", "First overview"];
const CURRENCIES = ["USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "SGD", "AED", "ZAR"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function CreateWorkspace() {
  const [f, setF] = useState({ name: "", industry: "Retail", business_type: "Small business", currency: "USD", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", fiscal_year_start_month: 1 });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  return (
    <form className="space-y-4" onSubmit={async (e) => {
      e.preventDefault();
      if (!f.name.trim()) return setErr("Give your workspace a name");
      setBusy(true); setErr("");
      try {
        const r = await post<{ workspace: { id: string } }>("/workspaces", f);
        try { localStorage.setItem("cm_workspace", r.workspace.id); } catch { /* ignore */ }
        window.location.href = "/app/onboarding";
      } catch (x) { setErr(errorMessage(x)); setBusy(false); }
    }}>
      {err && <ErrorNote>{err}</ErrorNote>}
      <Field label="Business or workspace name" htmlFor="n"><Input id="n" autoFocus value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Asha Home Goods" /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Industry" htmlFor="i"><Select id="i" value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })}>
          {["Retail", "E-commerce", "Wholesale and distribution", "Food and hospitality", "Professional services", "Manufacturing", "Other"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Field label="Business type" htmlFor="b"><Select id="b" value={f.business_type} onChange={(e) => setF({ ...f, business_type: e.target.value })}>
          {["Small business", "Multi-location business", "Online store", "Agency or consultancy", "Enterprise team"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Field label="Default currency" htmlFor="c" hint="Used to format money in answers and reports."><Select id="c" value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}>
          {CURRENCIES.map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Field label="Time zone" htmlFor="tz"><Input id="tz" value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} /></Field>
        <Field label="Fiscal year starts in" htmlFor="fy"><Select id="fy" value={f.fiscal_year_start_month} onChange={(e) => setF({ ...f, fiscal_year_start_month: Number(e.target.value) })}>
          {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</Select></Field>
      </div>
      <Button type="submit" variant="primary" loading={busy}>Create workspace</Button>
    </form>
  );
}

function Wizard() {
  const { ws, base, wid, refresh } = useWorkspace();
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const creating = params.get("new") === "1" || !ws;
  const saved = ws?.onboarding ?? {};
  const [step, setStep] = useState<number>(creating ? 1 : Math.max(2, saved.step ?? 2));
  const [datasetId, setDatasetId] = useState<string | undefined>(saved.dataset_id);
  const [demoBusy, setDemoBusy] = useState(false);
  const [err, setErr] = useState("");
  const [terms, setTerms] = useState<TermsResult | null>(null);

  const go = async (n: number, extra: { dataset_id?: string; completed?: boolean } = {}) => {
    setStep(n);
    if (wid) await post(`${base}/onboarding`, { step: n, completed: !!extra.completed, dataset_id: extra.dataset_id ?? datasetId });
  };
  const ds = useQuery({ queryKey: [wid, "dataset", datasetId], queryFn: () => get<{ dataset: Dataset }>(`${base}/datasets/${datasetId}`), enabled: !!datasetId && step >= 3 });
  const cols = useQuery({ queryKey: [wid, "columns", datasetId], queryFn: () => get<{ columns: Column[] }>(`${base}/datasets/${datasetId}/columns`), enabled: !!datasetId && step === 3 });
  const quality = useQuery({ queryKey: [wid, "quality", datasetId], queryFn: () => get<{ quality: { score: number; grade: string; issues: { message: string; severity: string }[] } }>(`${base}/datasets/${datasetId}/quality`), enabled: !!datasetId && step >= 3 });
  const insights = useQuery({
    queryKey: [wid, "onboarding-insights", datasetId], enabled: !!datasetId && step === 5,
    queryFn: () => post<{ insights: Insight[] }>(`${base}/insights/generate`, { dataset_id: datasetId }),
  });
  const sugg = useQuery({ queryKey: [wid, "suggestions", datasetId], queryFn: () => get<{ questions: string[] }>(`${base}/conversations/suggestions?dataset_id=${datasetId}`), enabled: !!datasetId && step === 5 });

  const picked = async (d: Dataset) => { setDatasetId(d.id); qc.invalidateQueries({ queryKey: [wid, "datasets"] }); await go(3, { dataset_id: d.id }); };

  useEffect(() => { if (creating) setStep(1); }, [creating]);

  return (
    <div className="mx-auto max-w-3xl px-5 py-8">
      <div className="flex items-center justify-between"><Logo href="/app/overview" />{ws && !creating && <Link href="/app/overview" onClick={() => go(step)} className="text-sm text-muted hover:text-ink">Finish later</Link>}</div>
      <ol className="mt-8 flex gap-2" aria-label="Setup progress">
        {STEPS.map((s, i) => (
          <li key={s} className="flex-1">
            <div className={cx("h-1 rounded-full", i + 1 <= step ? "bg-forest" : "bg-line")} />
            <p className={cx("mt-1.5 text-xs", i + 1 === step ? "font-medium text-ink" : "text-muted")} aria-current={i + 1 === step ? "step" : undefined}>{i + 1}. {s}</p>
          </li>
        ))}
      </ol>
      <div className="mt-10">
        {step === 1 && (<><h1 className="text-3xl font-semibold tracking-[-0.015em]">Set up your business workspace</h1><p className="mb-6 mt-2 text-muted">These settings shape how numbers, dates and reports are formatted.</p><CreateWorkspace /></>)}
        {step === 2 && (
          <>
            <h1 className="text-3xl font-semibold tracking-[-0.015em]">Choose some data to start with</h1>
            <p className="mb-6 mt-2 text-muted">Upload your own sales or customer file, or explore a synthetic retail dataset first.</p>
            {err && <div className="mb-4"><ErrorNote>{err}</ErrorNote></div>}
            <div className="grid gap-4 md:grid-cols-[1.4fr_1fr]">
              <div><h2 className="mb-2 flex items-center gap-2 text-sm font-medium"><FileSpreadsheet className="size-4 text-forest" />Upload a CSV or Excel workbook</h2><Uploader onUploaded={picked} /></div>
              <div className="flex flex-col rounded-lg border border-line bg-surface p-5">
                <h2 className="flex items-center gap-2 text-sm font-medium"><Database className="size-4 text-forest" />Explore demonstration data</h2>
                <p className="mt-2 flex-1 text-sm text-muted">About 1,500 synthetic retail orders across 24 months, five regions and seventeen products. Generated with a fixed seed and imported through the same pipeline as your files. It is clearly labelled as synthetic everywhere.</p>
                <Button className="mt-4" variant="primary" loading={demoBusy} onClick={async () => {
                  setDemoBusy(true); setErr("");
                  try { await picked((await post<{ dataset: Dataset }>(`${base}/datasets/demo`)).dataset); } catch (e) { setErr(errorMessage(e)); } finally { setDemoBusy(false); }
                }}>Load demo data</Button>
              </div>
            </div>
          </>
        )}
        {step === 3 && (
          <>
            <h1 className="text-3xl font-semibold tracking-[-0.015em]">Here’s what we found in your data</h1>
            <p className="mb-6 mt-2 text-muted">{ds.data ? `${ds.data.dataset.name}: ${ds.data.dataset.row_count?.toLocaleString()} rows, ${ds.data.dataset.column_count} columns.` : "Reading the dataset…"}</p>
            {quality.data && (
              <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface p-4">
                <span className="tnum text-3xl font-semibold">{quality.data.quality.score}</span>
                <span className="text-sm"><span className="font-medium">Data Quality Score</span><br /><span className="text-muted">{quality.data.quality.grade}. {quality.data.quality.issues.filter((i) => i.severity !== "info").length} issues to review in the Data Hub.</span></span>
              </div>
            )}
            {cols.isLoading ? <Skeleton className="h-64" /> : (
              <div className="overflow-x-auto rounded-lg border border-line bg-surface">
                <table className="w-full text-sm">
                  <caption className="sr-only">Detected columns</caption>
                  <thead className="bg-paper/70 text-left text-ink-2"><tr><th className="px-3 py-2 font-medium">Column</th><th className="px-3 py-2 font-medium">Type</th><th className="px-3 py-2 font-medium">Role</th><th className="px-3 py-2 font-medium">Missing</th><th className="px-3 py-2 font-medium">Examples</th></tr></thead>
                  <tbody className="divide-y divide-line">
                    {cols.data?.columns.map((c) => (
                      <tr key={c.id}><td className="px-3 py-2 font-medium">{c.display_name}</td><td className="px-3 py-2">{c.dtype}</td>
                        <td className="px-3 py-2"><Badge tone={c.semantic_type === "currency" || c.semantic_type === "measure" ? "forest" : c.semantic_type === "date" ? "slate" : "neutral"}>{c.semantic_type === "measure" || c.semantic_type === "currency" ? "potential measure" : c.semantic_type === "dimension" ? "likely dimension" : c.semantic_type}</Badge></td>
                        <td className="tnum px-3 py-2">{c.null_count ? c.null_count.toLocaleString() : "—"}</td>
                        <td className="max-w-56 truncate px-3 py-2 text-muted">{c.examples.slice(0, 3).map(String).join(", ")}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="mt-6 flex gap-2"><Button variant="primary" onClick={() => go(4)}>Continue to business terms</Button><Button variant="ghost" onClick={() => go(2)}>Choose different data</Button></div>
          </>
        )}
        {step === 4 && datasetId && (
          <>
            <h1 className="text-3xl font-semibold tracking-[-0.015em]">Confirm your business terms</h1>
            <p className="mb-6 mt-2 text-muted">Columns called sales, amount or total can mean different things. Tell us which column means what, so every answer uses the same definitions.</p>
            {terms ? (
              <div className="space-y-4">
                <div role="status" className="rounded-lg border border-forest/30 bg-surface p-4">
                  <p className="font-medium"><Check className="mr-1 inline size-4 text-forest" />Created {terms.metrics_created.length} verified metrics</p>
                  <ul className="mt-2 grid gap-1 text-sm sm:grid-cols-2">{terms.metrics_created.map((m) => <li key={m.id}><span className="font-medium">{m.name}</span> <span className="text-muted">= {m.formula}</span></li>)}</ul>
                  {terms.metrics_skipped.length > 0 && <p className="mt-2 text-xs text-muted">Skipped: {terms.metrics_skipped.map((s) => `${s.name} (${s.reason})`).join("; ")}</p>}
                </div>
                <Button variant="primary" onClick={() => go(5)}>See your first overview</Button>
              </div>
            ) : <TermsForm datasetId={datasetId} onDone={(r) => { setTerms(r); qc.invalidateQueries({ queryKey: [wid, "metrics"] }); }} />}
          </>
        )}
        {step === 5 && (
          <>
            <h1 className="text-3xl font-semibold tracking-[-0.015em]">Your first business overview</h1>
            <p className="mb-6 mt-2 text-muted">A first scan of {ds.data?.dataset.name ?? "your data"}. Everything below was computed from the data, not written in advance.</p>
            <div className="grid gap-4 md:grid-cols-2">
              <section className="rounded-lg border border-line bg-surface p-4">
                <h2 className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="size-4 text-forest" />Interesting patterns</h2>
                {insights.isLoading && <div className="mt-3 space-y-2"><Skeleton className="h-10" /><Skeleton className="h-10" /><Skeleton className="h-10" /></div>}
                {insights.error && <p className="mt-2 text-sm text-rust">{errorMessage(insights.error)}</p>}
                <ul className="mt-3 space-y-3">
                  {insights.data?.insights.slice(0, 4).map((i) => (
                    <li key={i.id} className="text-sm"><Badge tone={i.severity === "high" ? "rust" : i.severity === "medium" ? "brass" : "neutral"}>{i.severity}</Badge> <span className="font-medium">{i.title}</span></li>
                  ))}
                  {insights.data && insights.data.insights.length === 0 && <li className="text-sm text-muted">No notable patterns at the default thresholds.</li>}
                </ul>
              </section>
              <section className="rounded-lg border border-line bg-surface p-4">
                <h2 className="text-sm font-semibold">Suggested questions</h2>
                <ul className="mt-3 space-y-1.5">
                  {sugg.data?.questions.slice(0, 6).map((q) => <li key={q}><Link className="text-sm text-forest hover:underline" href={`/app/analyst?new=1&q=${encodeURIComponent(q)}`}>{q}</Link></li>)}
                </ul>
              </section>
              <section className="rounded-lg border border-line bg-surface p-4 md:col-span-2">
                <h2 className="text-sm font-semibold">Recommended starting analyses</h2>
                <div className="mt-3 flex flex-wrap gap-2">
                  <ButtonLink href="/app/metrics">Review your metrics</ButtonLink>
                  <ButtonLink href={`/app/data/${datasetId}?tab=quality`}>Check data quality ({quality.data?.quality.score ?? "—"})</ButtonLink>
                  <ButtonLink href="/app/insights">Open the Insights Center</ButtonLink>
                  <ButtonLink href="/app/explore">Build a chart in Explore</ButtonLink>
                </div>
              </section>
            </div>
            <Button className="mt-6" variant="primary" onClick={async () => { await go(5, { completed: true }); await refresh(); router.push("/app/overview"); }}>Finish setup</Button>
          </>
        )}
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  return <Suspense fallback={null}><Wizard /></Suspense>;
}

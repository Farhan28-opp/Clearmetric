"use client";
import { FileText, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useDatasets } from "@/components/datasets";
import { Badge, Button, Dialog, Empty, ErrorNote, Field, Input, PageHeader, Select, Skeleton } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { errorMessage, post } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { Conversation, Insight, Report } from "@/lib/types";

function NewReport({ open, onClose, initialTemplate }: { open: boolean; onClose: () => void; initialTemplate: string }) {
  const { base } = useWorkspace();
  const router = useRouter();
  const ds = useDatasets();
  const ready = ds.data?.datasets.filter((d) => d.status === "ready") ?? [];
  const [f, setF] = useState({ title: "Executive brief", subtitle: "", dataset_id: "", period_start: "", period_end: "", template: initialTemplate, from_conversation_id: "", from_insight_ids: [] as string[] });
  const convs = useWsQuery<{ conversations: Conversation[] }>(["conversations", "for-report"], "/conversations", { enabled: open });
  const ins = useWsQuery<{ insights: Insight[] }>(["insights", f.dataset_id, "for-report"], f.dataset_id ? `/insights?dataset_id=${f.dataset_id}&status=active` : null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { if (!f.dataset_id && ready[0]) setF((x) => ({ ...x, dataset_id: ready[0].id })); }, [ready, f.dataset_id]);
  return (
    <Dialog open={open} onClose={onClose} wide title="Create a report" footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" loading={busy} onClick={async () => {
        setBusy(true); setErr("");
        try { const r = await post<{ report: Report }>(`${base}/reports`, { ...f, from_conversation_id: f.from_conversation_id || null, dataset_id: f.dataset_id || null }); router.push(`/app/reports/${r.report.id}`); }
        catch (e) { setErr(errorMessage(e)); setBusy(false); }
      }}>Create report</Button></>}>
      <div className="space-y-4">
        {err && <ErrorNote>{err}</ErrorNote>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Title" htmlFor="rt"><Input id="rt" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="Subtitle (optional)" htmlFor="rs"><Input id="rs" value={f.subtitle} onChange={(e) => setF({ ...f, subtitle: e.target.value })} /></Field>
          <Field label="Dataset" htmlFor="rd"><Select id="rd" value={f.dataset_id} onChange={(e) => setF({ ...f, dataset_id: e.target.value, from_insight_ids: [] })}>{ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
          <Field label="Start from" htmlFor="rtp"><Select id="rtp" value={f.template} onChange={(e) => setF({ ...f, template: e.target.value })}><option value="executive">Executive summary</option><option value="blank">Blank report</option></Select></Field>
          <Field label="Reporting period from" htmlFor="ps" hint="Leave empty to use the latest month in the data."><Input id="ps" type="date" value={f.period_start} onChange={(e) => setF({ ...f, period_start: e.target.value })} /></Field>
          <Field label="to" htmlFor="pe"><Input id="pe" type="date" value={f.period_end} onChange={(e) => setF({ ...f, period_end: e.target.value })} /></Field>
        </div>
        <Field label="Include answers from an investigation (optional)" htmlFor="rc" hint="Pinned answers are used when there are any; otherwise every answer.">
          <Select id="rc" value={f.from_conversation_id} onChange={(e) => setF({ ...f, from_conversation_id: e.target.value })}><option value="">None</option>{convs.data?.conversations.map((c) => <option key={c.id} value={c.id}>{c.title}{c.saved ? " (saved)" : ""}</option>)}</Select>
        </Field>
        {!!ins.data?.insights.length && (
          <fieldset><legend className="text-[13px] font-medium text-ink-2">Include insights</legend>
            <div className="mt-1.5 max-h-40 space-y-1 overflow-y-auto rounded-md border border-line p-2">{ins.data.insights.map((i) => (
              <label key={i.id} className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={f.from_insight_ids.includes(i.id)} onChange={(e) => setF({ ...f, from_insight_ids: e.target.checked ? [...f.from_insight_ids, i.id] : f.from_insight_ids.filter((x) => x !== i.id) })} />{i.title}</label>))}</div>
          </fieldset>)}
      </div>
    </Dialog>
  );
}

function List() {
  const params = useSearchParams();
  const { can } = useWorkspace();
  const [q, setQ] = useState("");
  const list = useWsQuery<{ reports: Report[] }>(["reports", q], `/reports${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  const [open, setOpen] = useState(params.get("new") !== null);
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Reports" description="Executive briefs and analysis reports built from computed results. Each section keeps a snapshot of its numbers and their source."
        actions={can("analyst") && <Button variant="primary" onClick={() => setOpen(true)}><Plus className="size-4" />New report</Button>} />
      <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search reports" aria-label="Search reports" className="mb-4 max-w-sm" />
      {list.isLoading && <Skeleton className="h-48" />}
      {list.data && !list.data.reports.length && <Empty icon={<FileText className="size-6" />} title="No reports yet" action={can("analyst") && <Button variant="primary" onClick={() => setOpen(true)}>Create an executive brief</Button>}>Start from an executive summary, a saved investigation or selected insights.</Empty>}
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {list.data?.reports.map((r) => (
          <li key={r.id}>
            <Link href={`/app/reports/${r.id}`} className="group block h-full rounded-lg border border-line bg-surface p-5 hover:border-forest">
              <div className="mb-8 h-20 rounded border border-line bg-paper/70 p-2.5" aria-hidden><div className="h-2 w-2/3 rounded bg-ink/70" /><div className="mt-2 h-1.5 w-1/2 rounded bg-line-2" /><div className="mt-3 flex gap-1">{[1, 2, 3].map((i) => <div key={i} className="h-5 flex-1 rounded bg-forest-wash" />)}</div></div>
              <h2 className="font-semibold group-hover:text-forest">{r.title}</h2>
              <p className="mt-1 text-sm text-muted">{r.dataset_name ?? "No dataset"} · {r.section_count} sections</p>
              <p className="mt-2 flex items-center gap-2 text-xs text-muted"><Badge tone={r.status === "final" ? "forest" : "neutral"}>{r.status}</Badge>{r.period_label || "Latest month"} · updated {timeAgo(r.updated_at)}</p>
            </Link>
          </li>))}
      </ul>
      <NewReport open={open} onClose={() => setOpen(false)} initialTemplate={params.get("new") === "blank" ? "blank" : "executive"} />
    </div>
  );
}

export default function ReportsPage() {
  return <Suspense fallback={<Skeleton className="h-96" />}><List /></Suspense>;
}

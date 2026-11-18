"use client";
import { useQueryClient } from "@tanstack/react-query";
import { Archive, BadgeCheck, BookMarked, Copy, Pencil, Plus, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useColumns, useDatasets } from "@/components/datasets";
import { Badge, Button, cx, Dialog, Empty, ErrorNote, Field, Input, PageHeader, Panel, Select, Skeleton, Textarea, useToast } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { errorMessage, patch, post } from "@/lib/api";
import { fmtDate, fmtValue, timeAgo } from "@/lib/format";
import type { Metric } from "@/lib/types";

const FUNCS = ["SUM( )", "AVG( )", "COUNT(*)", "COUNT_DISTINCT( )", "MIN( )", "MAX( )", "SUM_IF( , region = 'North')", "COUNT_IF(status = 'Paid')"];

function MetricEditor({ metric, onClose }: { metric: Metric | "new"; onClose: () => void }) {
  const { base, wid } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const ds = useDatasets();
  const isNew = metric === "new";
  const m = isNew ? null : metric;
  const [f, setF] = useState({
    dataset_id: m?.dataset_id ?? ds.data?.datasets.find((d) => d.status === "ready")?.id ?? "", name: m?.name ?? "", formula: m?.formula ?? "",
    description: m?.description ?? "", category: m?.category ?? "Revenue", unit: m?.unit ?? "currency", decimals: m?.decimals ?? 2,
    default_date_column: m?.default_date_column ?? "", synonyms: (m?.synonyms ?? []).join(", "), change_note: "",
  });
  const cols = useColumns(f.dataset_id || null);
  const [check, setCheck] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!f.formula.trim() || !f.dataset_id) { setCheck(null); return; }
    const t = setTimeout(() => {
      post<{ aggregation_type: string; readable: string }>(`${base}/metrics/check`, { dataset_id: f.dataset_id, formula: f.formula })
        .then((r) => setCheck({ ok: true, text: `Valid ${r.aggregation_type} calculation: ${r.readable}` }))
        .catch((e) => setCheck({ ok: false, text: errorMessage(e) }));
    }, 350);
    return () => clearTimeout(t);
  }, [f.formula, f.dataset_id, base]);
  const insert = (s: string) => setF({ ...f, formula: (f.formula + " " + s).trim() });
  return (
    <Dialog open onClose={onClose} wide title={isNew ? "Define a metric" : `Edit ${m!.name}`} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" loading={busy} disabled={!check?.ok || !f.name.trim()} onClick={async () => {
        setBusy(true); setErr("");
        const body = { ...f, synonyms: f.synonyms.split(",").map((s) => s.trim()).filter(Boolean), decimals: Number(f.decimals) };
        try {
          if (isNew) { const { change_note: _c, ...rest } = body; void _c; await post(`${base}/metrics`, rest); toast("Metric created (unverified until someone verifies it)"); }
          else { const { dataset_id: _d, ...rest } = body; void _d; await patch(`${base}/metrics/${m!.id}`, rest); toast("Saved as a new version"); }
          qc.invalidateQueries({ queryKey: [wid] }); onClose();
        } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
      }}>{isNew ? "Create metric" : "Save new version"}</Button></>}>
      <div className="space-y-4">
        {err && <ErrorNote>{err}</ErrorNote>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Dataset" htmlFor="md"><Select id="md" disabled={!isNew} value={f.dataset_id} onChange={(e) => setF({ ...f, dataset_id: e.target.value })}>{ds.data?.datasets.filter((d) => d.status === "ready").map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
          <Field label="Display name" htmlFor="mn"><Input id="mn" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Net Revenue" /></Field>
        </div>
        <Field label="Formula" htmlFor="mf" hint="Aggregate columns with the functions below. Text values go in single quotes. Division by zero returns an empty value.">
          <Textarea id="mf" rows={2} className="font-mono text-[13px]" value={f.formula} onChange={(e) => setF({ ...f, formula: e.target.value })} placeholder="SUM(profit) / SUM(net_revenue)" />
        </Field>
        <div className="flex flex-wrap gap-1">{FUNCS.map((s) => <button key={s} type="button" onClick={() => insert(s)} className="rounded border border-line px-1.5 py-0.5 font-mono text-[11.5px] hover:border-forest">{s}</button>)}</div>
        <div className="flex max-h-24 flex-wrap gap-1 overflow-y-auto">{cols.data?.columns.filter((c) => !c.excluded).map((c) => <button key={c.name} type="button" onClick={() => insert(c.name)} title={`${c.display_name} (${c.dtype})`} className={cx("rounded px-1.5 py-0.5 font-mono text-[11.5px]", c.dtype === "integer" || c.dtype === "float" ? "bg-forest-wash text-forest-2" : "bg-paper-2 text-ink-2")}>{c.name}</button>)}</div>
        {check && <p role="status" className={cx("text-sm", check.ok ? "text-forest" : "text-rust")}>{check.text}</p>}
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Unit" htmlFor="mu"><Select id="mu" value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })}><option value="currency">Currency</option><option value="count">Count</option><option value="percent">Percent (ratio)</option><option value="number">Number</option></Select></Field>
          <Field label="Decimals" htmlFor="mdec"><Input id="mdec" type="number" min={0} max={6} value={f.decimals} onChange={(e) => setF({ ...f, decimals: Number(e.target.value) })} /></Field>
          <Field label="Category" htmlFor="mc"><Input id="mc" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} /></Field>
          <Field label="Default date" htmlFor="mdd"><Select id="mdd" value={f.default_date_column} onChange={(e) => setF({ ...f, default_date_column: e.target.value })}><option value="">None</option>{cols.data?.columns.filter((c) => c.dtype === "date" || c.dtype === "datetime").map((c) => <option key={c.name} value={c.name}>{c.display_name}</option>)}</Select></Field>
        </div>
        <Field label="Other names people use (comma separated)" htmlFor="ms" hint="Helps the AI Analyst recognise the metric, e.g. “margin, gross margin”."><Input id="ms" value={f.synonyms} onChange={(e) => setF({ ...f, synonyms: e.target.value })} /></Field>
        <Field label="Description" htmlFor="mdesc"><Textarea id="mdesc" rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        {!isNew && <Field label="What changed (stored with the version)" htmlFor="mcn"><Input id="mcn" value={f.change_note} onChange={(e) => setF({ ...f, change_note: e.target.value })} /></Field>}
        {!isNew && f.formula !== m!.formula && <p className="text-sm text-brass">Changing the formula creates version {m!.version + 1} and removes its verified status until someone verifies it again. Earlier analyses keep using version {m!.version}.</p>}
      </div>
    </Dialog>
  );
}

function MetricDetail({ id }: { id: string }) {
  const { base, wid, ws, can } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useWsQuery<{ metric: Metric }>(["metric", id], `/metrics/${id}`);
  const [edit, setEdit] = useState(false);
  const [value, setValue] = useState<string | null>(null);
  const act = async (path: string, msg: string) => { try { await post(`${base}/metrics/${id}/${path}`); toast(msg); qc.invalidateQueries({ queryKey: [wid] }); } catch (e) { toast(errorMessage(e), "error"); } };
  useEffect(() => setValue(null), [id]);
  if (!q.data) return <Skeleton className="h-96" />;
  const m = q.data.metric;
  return (
    <Panel>
      <div className="border-b border-line p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs text-muted">{m.category} · {m.key}</p>
            <h2 className="mt-0.5 text-2xl font-semibold">{m.name}</h2>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {m.verified ? <Badge tone="forest"><BadgeCheck className="size-3" />Verified {m.verified_at && fmtDate(m.verified_at)}</Badge> : <Badge tone="brass">Not verified</Badge>}
              <Badge>v{m.version}</Badge><Badge>{m.aggregation_type}</Badge><Badge>{m.unit}</Badge>{m.status === "archived" && <Badge tone="rust">archived</Badge>}
              {m.valid === false && <Badge tone="rust">invalid for current data</Badge>}
            </div>
          </div>
          {can("analyst") && <div className="flex flex-wrap gap-1.5">
            {!m.verified && m.valid !== false && <Button size="sm" variant="primary" onClick={() => act("verify", "Metric verified")}><ShieldCheck className="size-3.5" />Mark verified</Button>}
            {m.verified && <Button size="sm" variant="ghost" onClick={() => act("unverify", "Verification removed")}>Remove verification</Button>}
            <Button size="sm" onClick={() => setEdit(true)}><Pencil className="size-3.5" />Edit</Button>
            <Button size="sm" variant="ghost" onClick={() => act("duplicate", "Duplicated")}><Copy className="size-3.5" />Duplicate</Button>
            <Button size="sm" variant="ghost" onClick={() => act("archive", m.status === "active" ? "Archived" : "Restored")}><Archive className="size-3.5" />{m.status === "active" ? "Archive" : "Restore"}</Button>
          </div>}
        </div>
        {m.description && <p className="mt-3 text-sm text-ink-2">{m.description}</p>}
      </div>
      <div className="grid gap-6 p-5 md:grid-cols-2">
        <div className="space-y-4">
          <div>
            <h3 className="text-xs font-medium text-muted">Formula</h3>
            <pre className="mt-1 overflow-x-auto rounded-md bg-ink p-3 font-mono text-[13px] text-[#cde5d9]">{m.formula}</pre>
            {m.readable_formula && <p className="mt-1.5 text-sm text-ink-2">{m.readable_formula}</p>}
            {m.validation_error && <p className="mt-1.5 text-sm text-rust">{m.validation_error}</p>}
          </div>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            {[["Columns used", m.columns_used.join(", ")], ["Default date", m.default_date_column || "—"], ["Formatting", m.unit === "count" ? "count, whole numbers" : `${m.unit}, ${m.decimals} decimals`], ["Created", fmtDate(m.created_at)],
              ["Also known as", m.synonyms.join(", ") || "—"], ["Applies to", m.dimensions.length ? m.dimensions.join(", ") : "All dimensions"]].map(([k, v]) => <div key={k}><dt className="text-xs text-muted">{k}</dt><dd>{v}</dd></div>)}
          </dl>
          <div className="flex items-center gap-3">
            <Button size="sm" onClick={async () => {
              try {
                const r = await post<{ result: { kpis: { value: number }[] } }>(`${base}/analysis/compute`, { plan: { intent: "aggregate", dataset_id: m.dataset_id, measures: [{ kind: "metric", metric_id: m.id }] } });
                setValue(fmtValue(r.result.kpis[0].value, m.unit, ws?.currency, m.decimals, false));
              } catch (e) { setValue(errorMessage(e)); }
            }}>Calculate on all data</Button>
            {value && <span role="status" className="tnum text-lg font-semibold">{value}</span>}
            <Link href={`/app/explore?metric=${m.id}&dataset=${m.dataset_id}`} className="text-sm text-forest hover:underline">Explore this metric</Link>
          </div>
        </div>
        <div className="space-y-5">
          <div>
            <h3 className="text-xs font-medium text-muted">Version history</h3>
            <ol className="mt-2 space-y-2">{[...(m.versions ?? [])].reverse().map((v) => (
              <li key={v.id} className="rounded-md border border-line px-3 py-2 text-sm"><div className="flex justify-between"><span className="font-medium">v{v.version}{v.id === m.version_id && " (current)"}</span><span className="text-xs text-muted">{fmtDate(v.created_at, true)}</span></div>
                <code className="mt-1 block text-xs text-ink-2">{v.formula}</code>{v.change_note && <p className="mt-0.5 text-xs text-muted">{v.change_note}</p>}</li>))}</ol>
          </div>
          <div>
            <h3 className="text-xs font-medium text-muted">Used in {m.usage?.analysis_runs ?? 0} analyses</h3>
            <ul className="mt-2 space-y-1 text-sm">{m.usage?.recent.map((u) => <li key={u.id} className="flex justify-between gap-3"><span className="truncate">{u.question}</span><span className="shrink-0 text-xs text-muted">{u.source}, v{u.metric_version}, {timeAgo(u.created_at)}</span></li>)}</ul>
          </div>
        </div>
      </div>
      {edit && <MetricEditor metric={m} onClose={() => setEdit(false)} />}
    </Panel>
  );
}

function Library() {
  const params = useSearchParams();
  const router = useRouter();
  const { can } = useWorkspace();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [status, setStatus] = useState("active");
  const [ver, setVer] = useState("");
  const list = useWsQuery<{ metrics: Metric[]; categories: string[] }>(["metrics", "list", q, cat, status, ver], `/metrics?status=${status}${q ? `&q=${encodeURIComponent(q)}` : ""}${cat ? `&category=${encodeURIComponent(cat)}` : ""}${ver ? `&verified=${ver}` : ""}`);
  const ds = useDatasets();
  const [creating, setCreating] = useState(false);
  const sel = params.get("metric") ?? list.data?.metrics[0]?.id ?? null;
  const grouped = useMemo(() => {
    const g: Record<string, Metric[]> = {};
    for (const m of list.data?.metrics ?? []) (g[m.category] ??= []).push(m);
    return g;
  }, [list.data]);
  const dsName = (id: string) => ds.data?.datasets.find((d) => d.id === id)?.name ?? "";
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Metric Library" description="The agreed definitions behind every number. Verified metrics are used by the Analyst, Explore, Insights and Reports alike."
        actions={can("analyst") && <Button variant="primary" onClick={() => setCreating(true)}><Plus className="size-4" />Define metric</Button>} />
      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <div className="space-y-3">
          <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search metrics" aria-label="Search metrics" />
          <div className="grid grid-cols-2 gap-2">
            <Select aria-label="Category" value={cat} onChange={(e) => setCat(e.target.value)} className="col-span-2 h-8.5 text-[13px]"><option value="">All categories</option>{list.data?.categories.map((c) => <option key={c}>{c}</option>)}</Select>
            <Select aria-label="Verification" value={ver} onChange={(e) => setVer(e.target.value)} className="h-8.5 text-[13px]"><option value="">Any status</option><option value="true">Verified</option><option value="false">Not verified</option></Select>
            <Select aria-label="Archive status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-8.5 text-[13px]"><option value="active">Active</option><option value="archived">Archived</option><option value="all">All</option></Select>
          </div>
          {list.isLoading && <Skeleton className="h-64" />}
          {list.data && !list.data.metrics.length && <Empty icon={<BookMarked className="size-6" />} title="No metrics here">Confirm business terms for a dataset to create standard verified metrics, or define your own.</Empty>}
          <nav aria-label="Metrics" className="space-y-4">
            {Object.entries(grouped).map(([c, ms]) => (
              <div key={c}>
                <h2 className="mb-1 px-1 text-xs font-medium text-muted">{c}</h2>
                <ul className="overflow-hidden rounded-md border border-line bg-surface">
                  {ms.map((m) => (
                    <li key={m.id} className="border-b border-line last:border-0">
                      <button onClick={() => router.replace(`/app/metrics?metric=${m.id}`, { scroll: false })} aria-current={sel === m.id}
                        className={cx("block w-full px-3 py-2.5 text-left hover:bg-paper", sel === m.id && "bg-forest-wash/60")}>
                        <span className="flex items-center gap-1.5 text-sm font-medium">{m.name}{m.verified && <BadgeCheck className="size-3.5 text-forest" aria-label="verified" />}</span>
                        <code className="block truncate text-xs text-muted">{m.formula}</code>
                        <span className="text-[11px] text-muted">{dsName(m.dataset_id)} · v{m.version}</span>
                      </button>
                    </li>))}
                </ul>
              </div>))}
          </nav>
        </div>
        <div>{sel ? <MetricDetail id={sel} /> : null}</div>
      </div>
      {creating && <MetricEditor metric="new" onClose={() => setCreating(false)} />}
    </div>
  );
}

export default function MetricsPage() {
  return <Suspense fallback={<Skeleton className="h-96" />}><Library /></Suspense>;
}

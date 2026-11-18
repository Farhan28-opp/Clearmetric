"use client";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Columns3, Download, History, Plus, RotateCcw, Wand2, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { TermsForm } from "@/components/terms";
import { Badge, Button, ButtonLink, Confirm, cx, Dialog, ErrorNote, Field, Input, PageHeader, Panel, Select, Skeleton, Tabs, useToast } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { download, errorMessage, post } from "@/lib/api";
import { bytes, fmtDate, timeAgo } from "@/lib/format";
import type { Column, Dataset, DatasetVersion, Filter } from "@/lib/types";

type Tab = "overview" | "preview" | "schema" | "quality" | "statistics" | "prepare" | "terms" | "versions" | "related";
const OPS = [["eq", "is"], ["neq", "is not"], ["gt", ">"], ["gte", "≥"], ["lt", "<"], ["lte", "≤"], ["contains", "contains"], ["is_null", "is empty"], ["not_null", "is not empty"]];
const ROLES = ["measure", "currency", "dimension", "date", "identifier", "text", "boolean"];

/* ------------------------------------------------------------------ transformation preview + apply */
function TransformDialog({ dsId, kind, params, onClose, title }: { dsId: string; kind: string; params: Record<string, unknown>; onClose: () => void; title: string }) {
  const { base, wid } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const [prev, setPrev] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setPrev(null); setErr("");
    post(`${base}/datasets/${dsId}/transformations/preview`, { kind, params }).then(setPrev).catch((e) => setErr(errorMessage(e)));
  }, [base, dsId, kind, params]);
  return (
    <Dialog open onClose={onClose} title={title} wide footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" disabled={!prev} loading={busy} onClick={async () => {
        setBusy(true);
        try { const r = await post<{ summary: string; dataset: Dataset }>(`${base}/datasets/${dsId}/transformations`, { kind, params }); toast(`${r.summary}. Saved as v${r.dataset.current_version?.version_number}.`); qc.invalidateQueries({ queryKey: [wid] }); onClose(); }
        catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
      }}>Apply as new version</Button></>}>
      {err && <ErrorNote>{err}</ErrorNote>}
      {!prev && !err && <Skeleton className="h-32" />}
      {prev && (
        <div className="space-y-3 text-sm">
          <p className="font-medium">{prev.summary}</p>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[["Rows before", prev.rows_before], ["Rows after", prev.rows_after], ["Columns", `${prev.columns_before} → ${prev.columns_after}`], ["Affected", prev.affected]].map(([k, v]) => (
              <div key={k as string} className="rounded-md border border-line p-2"><dt className="text-xs text-muted">{k}</dt><dd className="tnum font-semibold">{typeof v === "number" ? v.toLocaleString() : v}</dd></div>))}
          </dl>
          <p className="text-xs text-muted">{prev.metadata_only ? "Metadata change only: the data values are unchanged." : "Applying writes a new version. The current version stays available to restore."}</p>
          <div className="overflow-x-auto rounded-md border border-line"><table className="text-xs">
            <thead className="bg-paper/70"><tr>{prev.sample_columns.map((c: any) => <th key={c.name} className="whitespace-nowrap px-2 py-1.5 text-left font-medium">{c.display_name}<span className="ml-1 text-muted">{c.dtype}</span></th>)}</tr></thead>
            <tbody className="divide-y divide-line">{prev.sample_after.map((r: unknown[], i: number) => <tr key={i}>{r.map((v, j) => <td key={j} className="whitespace-nowrap px-2 py-1">{v === null ? <span className="text-muted">—</span> : String(v)}</td>)}</tr>)}</tbody>
          </table></div>
        </div>
      )}
    </Dialog>
  );
}

/* ------------------------------------------------------------------ preview tab */
function PreviewTab({ ds, cols }: { ds: Dataset; cols: Column[] }) {
  const { base, wid } = useWorkspace();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(50);
  const [sort, setSort] = useState<{ col: string; dir: "asc" | "desc" } | null>(null);
  const [search, setSearch] = useState("");
  const [deb, setDeb] = useState("");
  const [filters, setFilters] = useState<Filter[]>([]);
  const [hidden, setHidden] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [colsOpen, setColsOpen] = useState(false);
  const [draft, setDraft] = useState<Filter>({ column: cols[0]?.name ?? "", op: "eq", value: "" });
  useEffect(() => { const t = setTimeout(() => { setDeb(search); setPage(1); }, 300); return () => clearTimeout(t); }, [search]);
  const visible = cols.filter((c) => !hidden.includes(c.name)).map((c) => c.name);
  const body = { page, page_size: size, sort: sort?.col, direction: sort?.dir ?? "asc", search: deb || null, filters, columns: visible };
  type PreviewData = { columns: string[]; rows: unknown[][]; total: number; pages: number };
  const [data, setData] = useState<PreviewData>();
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const bodyKey = JSON.stringify(body);
  useEffect(() => {
    setLoading(true); setErr("");
    post<PreviewData>(`${base}/datasets/${ds.id}/preview`, JSON.parse(bodyKey)).then((d) => { setData(d); setSelected(new Set()); }).catch((e) => setErr(errorMessage(e))).finally(() => setLoading(false));
  }, [base, ds.id, bodyKey, wid, ds.current_version?.id]);
  const byName = Object.fromEntries(cols.map((c) => [c.name, c]));
  const exportSelected = () => {
    if (!data) return;
    const esc = (v: unknown) => { let s = v === null || v === undefined ? "" : String(v); if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const lines = [data.columns.map((c) => esc(byName[c]?.display_name ?? c)).join(","), ...[...selected].map((i) => data.rows[i].map(esc).join(","))];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    a.download = `${ds.name.replace(/\W+/g, "_")}_selected_rows.csv`;
    a.click();
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <Input type="search" placeholder="Search text columns" value={search} onChange={(e) => setSearch(e.target.value)} className="h-8.5 w-56 text-[13px]" aria-label="Search rows" />
        <div className="flex flex-wrap items-end gap-1.5 rounded-md border border-line bg-surface p-1.5">
          <Select aria-label="Filter column" value={draft.column} onChange={(e) => setDraft({ ...draft, column: e.target.value })} className="h-7.5 w-36 text-xs">{cols.map((c) => <option key={c.name} value={c.name}>{c.display_name}</option>)}</Select>
          <Select aria-label="Operator" value={draft.op} onChange={(e) => setDraft({ ...draft, op: e.target.value })} className="h-7.5 w-28 text-xs">{OPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
          {!["is_null", "not_null"].includes(draft.op) && <Input aria-label="Value" value={String(draft.value ?? "")} onChange={(e) => setDraft({ ...draft, value: e.target.value })} className="h-7.5 w-32 text-xs" />}
          <Button size="sm" onClick={() => { setFilters([...filters, draft]); setPage(1); }}><Plus className="size-3.5" />Filter</Button>
        </div>
        <div className="relative">
          <Button size="sm" variant="ghost" onClick={() => setColsOpen(!colsOpen)} aria-expanded={colsOpen}><Columns3 className="size-3.5" />Columns ({visible.length}/{cols.length})</Button>
          {colsOpen && (
            <div className="absolute left-0 top-full z-20 mt-1 max-h-72 w-56 overflow-y-auto rounded-md border border-line bg-surface p-2 shadow-lift">
              {cols.map((c) => <label key={c.name} className="flex items-center gap-2 px-1 py-1 text-sm"><input type="checkbox" checked={!hidden.includes(c.name)} onChange={(e) => setHidden(e.target.checked ? hidden.filter((h) => h !== c.name) : [...hidden, c.name])} />{c.display_name}</label>)}
            </div>
          )}
        </div>
        <div className="ml-auto flex gap-1.5">
          {selected.size > 0 && <Button size="sm" onClick={exportSelected}><Download className="size-3.5" />Export {selected.size} selected</Button>}
          <Button size="sm" variant="ghost" onClick={() => download(`${base}/datasets/${ds.id}/export`, { method: "POST", json: { format: "csv", filters, search: deb || null, columns: visible, sort: sort?.col, direction: sort?.dir ?? "asc" } }).catch((e) => toast(errorMessage(e), "error"))}><Download className="size-3.5" />CSV</Button>
          <Button size="sm" variant="ghost" onClick={() => download(`${base}/datasets/${ds.id}/export`, { method: "POST", json: { format: "xlsx", filters, search: deb || null, columns: visible } }).catch((e) => toast(errorMessage(e), "error"))}><Download className="size-3.5" />XLSX</Button>
        </div>
      </div>
      {filters.length > 0 && (
        <div className="flex flex-wrap gap-1.5">{filters.map((f, i) => (
          <span key={i} className="inline-flex items-center gap-1 rounded-full border border-line-2 bg-surface px-2.5 py-1 text-xs">
            {byName[f.column]?.display_name} {OPS.find((o) => o[0] === f.op)?.[1]} {f.value !== undefined && !["is_null", "not_null"].includes(f.op) ? String(f.value) : ""}
            <button aria-label="Remove filter" onClick={() => { setFilters(filters.filter((_, j) => j !== i)); setPage(1); }}><X className="size-3" /></button>
          </span>))}
        </div>
      )}
      {err && <ErrorNote>{err}</ErrorNote>}
      <div className={cx("overflow-x-auto rounded-md border border-line bg-surface", loading && "opacity-60")}>
        <table className="w-full text-[13px]">
          <caption className="sr-only">Data preview, page {page}</caption>
          <thead className="sticky top-0 bg-paper/90"><tr>
            <th className="w-8 px-2"><input type="checkbox" aria-label="Select all rows on this page" checked={!!data?.rows.length && selected.size === data.rows.length} onChange={(e) => setSelected(e.target.checked ? new Set(data?.rows.map((_, i) => i)) : new Set())} /></th>
            {data?.columns.map((c) => (
              <th key={c} scope="col" aria-sort={sort?.col === c ? (sort.dir === "asc" ? "ascending" : "descending") : "none"} className="whitespace-nowrap px-3 py-2 text-left font-medium">
                <button onClick={() => { setSort(sort?.col === c && sort.dir === "asc" ? { col: c, dir: "desc" } : { col: c, dir: "asc" }); setPage(1); }} className="hover:text-forest">
                  {byName[c]?.display_name ?? c}{sort?.col === c ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
                </button>
              </th>))}
          </tr></thead>
          <tbody className="divide-y divide-line">
            {data?.rows.map((r, i) => (
              <tr key={i} className={cx(selected.has(i) && "bg-forest-wash/50")}>
                <td className="px-2"><input type="checkbox" aria-label={`Select row ${i + 1}`} checked={selected.has(i)} onChange={(e) => { const s = new Set(selected); if (e.target.checked) s.add(i); else s.delete(i); setSelected(s); }} /></td>
                {r.map((v, j) => <td key={j} className={cx("whitespace-nowrap px-3 py-1.5", typeof v === "number" && "tnum text-right")}>{v === null ? <span className="text-muted">—</span> : typeof v === "string" && /T00:00:00/.test(v) ? v.slice(0, 10) : String(v)}</td>)}
              </tr>))}
          </tbody>
        </table>
        {data && !data.rows.length && <p className="p-4 text-sm text-muted">No rows match the current filters.</p>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="tnum text-muted">{data ? `${data.total.toLocaleString()} matching rows · page ${page} of ${data.pages}` : ""}</span>
        <div className="flex items-center gap-2">
          <Select aria-label="Rows per page" value={size} onChange={(e) => { setSize(Number(e.target.value)); setPage(1); }} className="h-8 w-auto text-xs">{[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n} per page</option>)}</Select>
          <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <Button size="sm" disabled={!data || page >= data.pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ schema tab */
function SchemaTab({ ds, cols, onTransform }: { ds: Dataset; cols: Column[]; onTransform: (k: string, p: Record<string, unknown>, t: string) => void }) {
  const { can } = useWorkspace();
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"position" | "name" | "nulls" | "unique">("position");
  const [edit, setEdit] = useState<Column | null>(null);
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const shown = useMemo(() => {
    const r = cols.filter((c) => !q || `${c.display_name} ${c.original_name} ${c.business_meaning}`.toLowerCase().includes(q.toLowerCase()));
    return [...r].sort((a, b) => sort === "name" ? a.display_name.localeCompare(b.display_name) : sort === "nulls" ? b.null_count - a.null_count : sort === "unique" ? b.unique_count - a.unique_count : a.position - b.position);
  }, [cols, q, sort]);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search columns" className="h-8.5 w-56 text-[13px]" aria-label="Search columns" />
        <Select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className="h-8.5 w-auto text-[13px]" aria-label="Sort columns"><option value="position">File order</option><option value="name">Name</option><option value="nulls">Most missing</option><option value="unique">Most distinct</option></Select>
      </div>
      <div className="overflow-x-auto rounded-md border border-line bg-surface">
        <table className="w-full text-[13px]">
          <caption className="sr-only">Schema of {ds.name}</caption>
          <thead className="bg-paper/70 text-left text-ink-2"><tr>{["Display name", "Original name", "Type", "Role", "Business meaning", "Missing", "Distinct", "Examples", ""].map((h) => <th key={h} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}</tr></thead>
          <tbody className="divide-y divide-line">
            {shown.map((c) => (
              <tr key={c.id} className={cx(c.excluded && "opacity-55")}>
                <td className="px-3 py-2 font-medium">{c.display_name}{c.excluded && <Badge className="ml-1.5">excluded</Badge>}</td>
                <td className="px-3 py-2 text-muted">{c.original_name}</td>
                <td className="px-3 py-2">{c.dtype}{c.invalid_count > 0 && <Badge tone="brass" className="ml-1">{c.invalid_count} invalid</Badge>}</td>
                <td className="px-3 py-2"><Badge tone={c.semantic_type === "currency" || c.semantic_type === "measure" ? "forest" : c.semantic_type === "date" ? "slate" : "neutral"}>{c.semantic_type}</Badge>{c.semantic_confirmed && <CheckCircle2 className="ml-1 inline size-3.5 text-forest" aria-label="confirmed" />}</td>
                <td className="px-3 py-2">{c.business_meaning ? <span>{c.business_meaning.replace(/_/g, " ")} {!c.semantic_confirmed && <span className="text-xs text-muted">(suggested, {Math.round(c.meaning_confidence * 100)}%)</span>}</span> : <span className="text-muted">—</span>}</td>
                <td className="tnum px-3 py-2">{c.null_count.toLocaleString()}</td>
                <td className="tnum px-3 py-2">{c.unique_count.toLocaleString()}</td>
                <td className="max-w-48 truncate px-3 py-2 text-muted" title={c.examples.map(String).join(", ")}>{c.examples.slice(0, 3).map(String).join(", ")}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right">{can("analyst") && <Button size="sm" variant="ghost" onClick={() => { setEdit(c); setName(c.display_name); setRole(c.semantic_type); }}>Edit</Button>}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={`Column: ${edit?.original_name}`}>
        {edit && (
          <div className="space-y-4">
            <div className="flex items-end gap-2"><Field label="Display name" htmlFor="cn"><Input id="cn" value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <Button disabled={name === edit.display_name || !name.trim()} onClick={() => { onTransform("rename_column", { column: edit.name, display_name: name }, "Rename column"); setEdit(null); }}>Preview</Button></div>
            <div className="flex items-end gap-2"><Field label="Analytical role" htmlFor="cr"><Select id="cr" value={role} onChange={(e) => setRole(e.target.value)}>{ROLES.map((r) => <option key={r}>{r}</option>)}</Select></Field>
              <Button disabled={role === edit.semantic_type && edit.semantic_confirmed} onClick={() => { onTransform("set_role", { column: edit.name, semantic_type: role }, "Change role"); setEdit(null); }}>Preview</Button></div>
            <div className="flex flex-wrap gap-2 border-t border-line pt-4">
              <Button onClick={() => { onTransform("exclude_column", { column: edit.name, excluded: !edit.excluded }, edit.excluded ? "Include column" : "Exclude column"); setEdit(null); }}>{edit.excluded ? "Include in analysis" : "Exclude from analysis"}</Button>
              {edit.dtype === "string" && <Button onClick={() => { onTransform("parse_dates", { column: edit.name }, "Convert to date"); setEdit(null); }}>Convert to date</Button>}
              {edit.dtype === "string" && <Button onClick={() => { onTransform("convert_numeric", { column: edit.name }, "Convert to number"); setEdit(null); }}>Convert to number</Button>}
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}

/* ------------------------------------------------------------------ quality tab */
function QualityTab({ dsId, onTransform }: { dsId: string; onTransform: (k: string, p: Record<string, unknown>, t: string) => void }) {
  const { can } = useWorkspace();
  const q = useWsQuery<{ quality: any; readiness: any; import_report: any }>(["quality", dsId], `/datasets/${dsId}/quality`);
  if (!q.data) return <Skeleton className="h-64" />;
  const { quality: Q, readiness: R, import_report: I } = q.data;
  const fix = (i: any): [string, Record<string, unknown>, string] | null => {
    if (i.type === "duplicate_rows") return ["remove_duplicates", {}, "Remove duplicate rows"];
    if (i.type === "missing_values") return ["drop_missing_rows", { column: i.column }, "Remove rows with missing values"];
    if (i.type === "possibly_misclassified") return ["convert_numeric", { column: i.column }, "Convert to number"];
    if (i.type === "constant_column") return ["exclude_column", { column: i.column, excluded: true }, "Exclude constant column"];
    return null;
  };
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1.6fr]">
      <div className="space-y-4">
        <Panel title="Data Quality Score">
          <div className="p-4">
            <p className="tnum text-5xl font-semibold">{Q.score}<span className="text-lg text-muted"> / 100</span></p>
            <p className="mt-1 text-sm">{Q.grade}</p>
            <dl className="mt-4 space-y-2.5">
              {Object.entries(Q.components).map(([k, v]: [string, any]) => (
                <div key={k}>
                  <dt className="flex justify-between text-[13px]"><span className="capitalize">{k}</span><span className="tnum text-muted">{v.points} / {v.weight}</span></dt>
                  <dd className="mt-1 h-1.5 overflow-hidden rounded-full bg-paper-2"><div className="h-full rounded-full bg-forest" style={{ width: `${v.ratio * 100}%` }} /></dd>
                </div>))}
            </dl>
            <p className="mt-4 text-xs leading-relaxed text-muted">{Q.methodology}</p>
          </div>
        </Panel>
        <Panel title="Analysis readiness">
          <ul className="space-y-1.5 p-4 text-sm">{R?.checks.map((c: any) => <li key={c.label} className="flex items-center gap-2">{c.ok ? <CheckCircle2 className="size-4 text-forest" /> : <X className="size-4 text-rust" />}{c.label}</li>)}</ul>
        </Panel>
        {I && <Panel title="Import details"><dl className="grid grid-cols-2 gap-2 p-4 text-sm">
          {[["Format", I.source], ["Encoding", I.encoding ?? "—"], ["Delimiter", I.delimiter ?? "—"], ["Sheet", I.sheet ?? "—"], ["Rows read", I.rows_read?.toLocaleString()], ["Malformed lines skipped", I.skipped_lines ?? 0]].map(([k, v]) => <div key={k}><dt className="text-xs text-muted">{k}</dt><dd>{String(v)}</dd></div>)}
          {I.header_notes?.map((n: string) => <p key={n} className="col-span-2 text-xs text-muted">{n}</p>)}
        </dl></Panel>}
      </div>
      <Panel title={`Issues found (${Q.issues.length})`}>
        <ul className="divide-y divide-line">
          {Q.issues.map((i: any, k: number) => {
            const f = fix(i);
            return (
              <li key={k} className="flex items-start gap-3 px-4 py-3 text-sm">
                <Badge tone={i.severity === "high" ? "rust" : i.severity === "medium" ? "brass" : "neutral"}>{i.severity}</Badge>
                <span className="flex-1">{i.message}</span>
                {f && can("analyst") && <Button size="sm" onClick={() => onTransform(...f)}><Wand2 className="size-3.5" />Fix</Button>}
              </li>);
          })}
          {!Q.issues.length && <li className="px-4 py-6 text-sm text-muted">No issues found.</li>}
        </ul>
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ statistics tab */
function StatsTab({ cols }: { cols: Column[] }) {
  const nums = cols.filter((c) => (c.dtype === "integer" || c.dtype === "float") && c.stats?.mean !== undefined);
  const dims = cols.filter((c) => c.stats?.top_values);
  const dates = cols.filter((c) => c.dtype === "date" || c.dtype === "datetime");
  return (
    <div className="space-y-6">
      {nums.length > 0 && <Panel title="Numeric columns"><div className="overflow-x-auto"><table className="w-full text-[13px]">
        <thead className="text-left text-ink-2"><tr className="border-b border-line">{["Column", "Min", "Median", "Mean", "Max", "Std. dev.", "Sum", "Outliers (1.5×IQR)", "Distribution"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">{nums.map((c) => {
          const h = c.stats.histogram?.counts ?? [];
          const mx = Math.max(...h, 1);
          return (<tr key={c.id}><td className="px-3 py-2 font-medium">{c.display_name}</td>
            {["min", "median", "mean", "max", "std", "sum"].map((k) => <td key={k} className="tnum px-3 py-2 text-right">{Number(c.stats[k]).toLocaleString("en-US", { maximumFractionDigits: 2 })}</td>)}
            <td className="tnum px-3 py-2 text-right">{c.stats.outliers_iqr}</td>
            <td className="px-3 py-2"><svg width="100" height="22" role="img" aria-label={`Histogram of ${c.display_name}`}>{h.map((n: number, i: number) => <rect key={i} x={i * (100 / h.length)} y={22 - (n / mx) * 22} width={100 / h.length - 1} height={(n / mx) * 22} fill="#1f6b52" />)}</svg></td></tr>);
        })}</tbody></table></div></Panel>}
      {dates.length > 0 && <Panel title="Date columns"><ul className="divide-y divide-line">{dates.map((c) => <li key={c.id} className="px-4 py-2.5 text-sm"><span className="font-medium">{c.display_name}</span>: {String(c.stats.min ?? "").slice(0, 10)} to {String(c.stats.max ?? "").slice(0, 10)} ({c.stats.distinct_days} distinct days)</li>)}</ul></Panel>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {dims.slice(0, 9).map((c) => {
          const top = c.stats.top_values as { value: string; count: number }[];
          const mx = Math.max(...top.map((t) => t.count), 1);
          return (<Panel key={c.id} title={`${c.display_name} (${c.unique_count.toLocaleString()} distinct)`}>
            <ul className="space-y-1.5 p-4">{top.slice(0, 8).map((t) => (
              <li key={t.value} className="text-[13px]"><div className="flex justify-between gap-2"><span className="truncate">{t.value}</span><span className="tnum text-muted">{t.count.toLocaleString()}</span></div>
                <div className="mt-0.5 h-1 rounded-full bg-paper-2"><div className="h-full rounded-full bg-forest/70" style={{ width: `${(t.count / mx) * 100}%` }} /></div></li>))}</ul>
          </Panel>);
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ prepare tab */
function PrepareTab({ cols, onTransform }: { cols: Column[]; onTransform: (k: string, p: Record<string, unknown>, t: string) => void }) {
  const [fill, setFill] = useState({ column: cols.find((c) => c.null_count)?.name ?? cols[0]?.name, strategy: "zero", value: "" });
  const [filt, setFilt] = useState<Filter & { action: string }>({ column: cols[0]?.name ?? "", op: "lt", value: "0", action: "remove" });
  const [calc, setCalc] = useState({ name: "", expression: "", unit: "number" });
  const [dup, setDup] = useState<string[]>([]);
  const numeric = cols.filter((c) => c.dtype === "integer" || c.dtype === "float");
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="Handle missing values"><div className="space-y-3 p-4">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Column" htmlFor="fc"><Select id="fc" value={fill.column} onChange={(e) => setFill({ ...fill, column: e.target.value })}>{cols.map((c) => <option key={c.name} value={c.name}>{c.display_name} ({c.null_count} missing)</option>)}</Select></Field>
          <Field label="Replace with" htmlFor="fs"><Select id="fs" value={fill.strategy} onChange={(e) => setFill({ ...fill, strategy: e.target.value })}><option value="zero">Zero</option><option value="mean">Mean</option><option value="median">Median</option><option value="mode">Most common value</option><option value="value">A specific value</option></Select></Field>
        </div>
        {fill.strategy === "value" && <Field label="Value" htmlFor="fv"><Input id="fv" value={fill.value} onChange={(e) => setFill({ ...fill, value: e.target.value })} /></Field>}
        <div className="flex gap-2"><Button onClick={() => onTransform("fill_missing", fill, "Fill missing values")}>Preview fill</Button><Button variant="ghost" onClick={() => onTransform("drop_missing_rows", { column: fill.column }, "Remove rows with missing values")}>Remove those rows instead</Button></div>
      </div></Panel>
      <Panel title="Remove duplicate records"><div className="space-y-3 p-4">
        <p className="text-sm text-muted">Exact duplicates by default, or rows that repeat the selected columns.</p>
        <div className="flex max-h-28 flex-wrap gap-x-4 gap-y-1 overflow-y-auto">{cols.map((c) => <label key={c.name} className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={dup.includes(c.name)} onChange={(e) => setDup(e.target.checked ? [...dup, c.name] : dup.filter((d) => d !== c.name))} />{c.display_name}</label>)}</div>
        <Button onClick={() => onTransform("remove_duplicates", dup.length ? { columns: dup } : {}, "Remove duplicates")}>Preview removal</Button>
      </div></Panel>
      <Panel title="Filter invalid rows"><div className="space-y-3 p-4">
        <div className="grid grid-cols-3 gap-2">
          <Select aria-label="Column" value={filt.column} onChange={(e) => setFilt({ ...filt, column: e.target.value })}>{cols.map((c) => <option key={c.name} value={c.name}>{c.display_name}</option>)}</Select>
          <Select aria-label="Condition" value={filt.op} onChange={(e) => setFilt({ ...filt, op: e.target.value })}>{OPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
          <Input aria-label="Value" value={String(filt.value ?? "")} onChange={(e) => setFilt({ ...filt, value: e.target.value })} disabled={["is_null", "not_null"].includes(filt.op)} />
        </div>
        <Select aria-label="Action" value={filt.action} onChange={(e) => setFilt({ ...filt, action: e.target.value })}><option value="remove">Remove matching rows</option><option value="keep">Keep only matching rows</option></Select>
        <Button onClick={() => onTransform("filter_rows", { filters: [{ column: filt.column, op: filt.op, value: filt.value }], action: filt.action }, "Filter rows")}>Preview filter</Button>
      </div></Panel>
      <Panel title="Add a calculated field"><div className="space-y-3 p-4">
        <Field label="Field name" htmlFor="cfn"><Input id="cfn" value={calc.name} onChange={(e) => setCalc({ ...calc, name: e.target.value })} placeholder="e.g. Margin per unit" /></Field>
        <Field label="Expression" htmlFor="cfe" hint={`Use column names with + − × ÷ and numbers, e.g. ${numeric[0]?.name ?? "profit"} / ${numeric[1]?.name ?? "quantity"}. Division by zero gives an empty value.`}>
          <Input id="cfe" value={calc.expression} onChange={(e) => setCalc({ ...calc, expression: e.target.value })} className="font-mono text-[13px]" placeholder="profit / quantity" /></Field>
        <p className="text-xs text-muted">Numeric columns: {numeric.map((c) => c.name).join(", ")}</p>
        <Button disabled={!calc.name || !calc.expression} onClick={() => onTransform("calculated_field", calc, "Add calculated field")}>Preview field</Button>
      </div></Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ versions + related */
function VersionsTab({ ds }: { ds: Dataset }) {
  const { base, wid, can } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const v = useWsQuery<{ current_version_id: string; versions: DatasetVersion[] }>(["versions", ds.id, ds.current_version?.id], `/datasets/${ds.id}/versions`);
  const [restore, setRestore] = useState<DatasetVersion | null>(null);
  return (
    <Panel title="Version history">
      <ol className="divide-y divide-line">
        {v.data?.versions.map((x) => (
          <li key={x.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
            <span className="tnum w-10 font-semibold">v{x.version_number}</span>
            <span className="min-w-0 flex-1"><span className="block">{x.note}</span><span className="text-xs text-muted">{fmtDate(x.created_at, true)} · {x.row_count.toLocaleString()} rows · {x.column_count} columns · quality {x.quality_score}</span></span>
            {x.id === v.data.current_version_id ? <Badge tone="forest">current</Badge> : can("analyst") && <Button size="sm" onClick={() => setRestore(x)}><RotateCcw className="size-3.5" />Restore</Button>}
          </li>))}
      </ol>
      <Confirm open={!!restore} onClose={() => setRestore(null)} title={`Restore version ${restore?.version_number}?`} confirmLabel="Restore as new version"
        onConfirm={async () => { try { await post(`${base}/datasets/${ds.id}/versions/${restore!.id}/restore`); toast("Version restored"); setRestore(null); qc.invalidateQueries({ queryKey: [wid] }); } catch (e) { toast(errorMessage(e), "error"); } }}>
        This creates a new version with the data and column settings of v{restore?.version_number}. Nothing is deleted, and earlier analyses keep pointing at the versions they used.
      </Confirm>
    </Panel>
  );
}

function RelatedTab({ dsId }: { dsId: string }) {
  const r = useWsQuery<any>(["related", dsId], `/datasets/${dsId}/related`);
  if (!r.data) return <Skeleton className="h-40" />;
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Panel title={`Metrics (${r.data.metrics.length})`}><ul className="divide-y divide-line">{r.data.metrics.map((m: any) => <li key={m.id} className="px-4 py-2 text-sm"><Link href={`/app/metrics?metric=${m.id}`} className="hover:text-forest">{m.name}</Link> {m.verified && <Badge tone="forest">verified</Badge>}</li>)}</ul></Panel>
      <Panel title={`Investigations (${r.data.conversations.length})`}><ul className="divide-y divide-line">{r.data.conversations.map((c: any) => <li key={c.id} className="px-4 py-2 text-sm"><Link href={`/app/analyst?c=${c.id}`} className="hover:text-forest">{c.title}</Link><span className="block text-xs text-muted">{timeAgo(c.updated_at)}</span></li>)}</ul></Panel>
      <Panel title={`Reports (${r.data.reports.length})`}><ul className="divide-y divide-line">{r.data.reports.map((c: any) => <li key={c.id} className="px-4 py-2 text-sm"><Link href={`/app/reports/${c.id}`} className="hover:text-forest">{c.title}</Link></li>)}</ul></Panel>
      <p className="text-sm text-muted md:col-span-3">{r.data.analysis_runs} analyses have been computed on this dataset, and {r.data.insights} current insights reference it.</p>
    </div>
  );
}

function DatasetPage() {
  const { datasetId } = useParams<{ datasetId: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const { wid } = useWorkspace();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "overview");
  const ds = useWsQuery<{ dataset: Dataset }>(["dataset", datasetId], `/datasets/${datasetId}`);
  const cols = useWsQuery<{ columns: Column[] }>(["columns", datasetId, ds.data?.dataset.current_version?.id], ds.data?.dataset.current_version ? `/datasets/${datasetId}/columns` : null);
  const [tf, setTf] = useState<null | { kind: string; params: Record<string, unknown>; title: string }>(null);
  const onTransform = (kind: string, p: Record<string, unknown>, title: string) => setTf({ kind, params: p, title });
  if (ds.error) return <ErrorNote>{errorMessage(ds.error)}</ErrorNote>;
  if (!ds.data) return <Skeleton className="h-96" />;
  const d = ds.data.dataset;
  const c = cols.data?.columns ?? [];
  const change = (t: Tab) => { setTab(t); router.replace(`/app/data/${datasetId}?tab=${t}`, { scroll: false }); };
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader crumbs={[{ href: "/app/data", label: "Data Hub" }, { label: d.name }]} title={d.name}
        description={<>{d.original_filename} · {d.current_version ? `version ${d.current_version.version_number}` : "not imported"} {d.is_demo && <Badge tone="brass" className="ml-1">synthetic demonstration data</Badge>}</>}
        actions={d.status === "ready" && <><ButtonLink href={`/app/analyst?new=1&dataset=${d.id}`} variant="primary">Ask about this data</ButtonLink><ButtonLink href={`/app/explore?dataset=${d.id}`}>Explore</ButtonLink></>} />
      {d.status !== "ready" ? <ErrorNote>This dataset is {d.status.replace("_", " ")}. {d.status === "needs_sheet" ? "Return to the Data Hub and choose a sheet to import." : d.status_message}</ErrorNote> : (
        <>
          <Tabs value={tab} onChange={change} className="mb-5" items={[
            { value: "overview", label: "Overview" }, { value: "preview", label: "Data preview" }, { value: "schema", label: "Schema", count: c.length },
            { value: "quality", label: "Data quality" }, { value: "statistics", label: "Statistics" }, { value: "prepare", label: "Prepare" },
            { value: "terms", label: "Business terms" }, { value: "versions", label: "Versions", count: d.version_count }, { value: "related", label: "Related analyses" }]} />
          {tab === "overview" && (
            <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
              <Panel title="Dataset overview"><dl className="grid grid-cols-2 gap-x-6 gap-y-4 p-5 sm:grid-cols-3">
                {[["Dataset name", d.name], ["Original file", d.original_filename], ["Imported", fmtDate(d.created_at, true)], ["Rows", d.row_count?.toLocaleString()], ["Columns", d.column_count],
                  ["File size", bytes(d.file_size)], ["Status", "Ready for analysis"], ["Current version", `v${d.current_version?.version_number} (${d.version_count} total)`], ["Data Quality Score", `${d.quality_score} / 100`]].map(([k, v]) => (
                  <div key={k as string}><dt className="text-xs text-muted">{k}</dt><dd className="mt-0.5 break-words text-sm font-medium">{String(v ?? "—")}</dd></div>))}
              </dl>{d.description && <p className="border-t border-line px-5 py-3 text-sm text-muted">{d.description}</p>}</Panel>
              <Panel title="Analysis readiness"><div className="space-y-2 p-5 text-sm">
                {d.readiness?.checks.map((x) => <p key={x.label} className="flex items-center gap-2">{x.ok ? <CheckCircle2 className="size-4 text-forest" /> : <X className="size-4 text-rust" />}{x.label}</p>)}
                <p className="pt-2 text-muted">{d.readiness?.measures} measures, {d.readiness?.dimensions} dimensions, {d.readiness?.dates} date columns.</p>
                <div className="flex flex-wrap gap-2 pt-2"><Button size="sm" onClick={() => change("terms")}>Confirm business terms</Button><Button size="sm" variant="ghost" onClick={() => change("quality")}>Review quality</Button><Button size="sm" variant="ghost" onClick={() => change("versions")}><History className="size-3.5" />History</Button></div>
              </div></Panel>
            </div>
          )}
          {tab === "preview" && c.length > 0 && <PreviewTab ds={d} cols={c} />}
          {tab === "schema" && <SchemaTab ds={d} cols={c} onTransform={onTransform} />}
          {tab === "quality" && <QualityTab dsId={d.id} onTransform={onTransform} />}
          {tab === "statistics" && <StatsTab cols={c} />}
          {tab === "prepare" && c.length > 0 && <PrepareTab cols={c} onTransform={onTransform} />}
          {tab === "terms" && <div className="max-w-3xl"><TermsForm datasetId={d.id} submitLabel="Save terms and create missing metrics" onDone={(r) => { qc.invalidateQueries({ queryKey: [wid] }); toast(`Business terms saved. ${r.metrics_created.length} new verified metric${r.metrics_created.length === 1 ? "" : "s"} created.`); }} /></div>}
          {tab === "versions" && <VersionsTab ds={d} />}
          {tab === "related" && <RelatedTab dsId={d.id} />}
        </>
      )}
      {tf && <TransformDialog dsId={d.id} kind={tf.kind} params={tf.params} title={tf.title} onClose={() => setTf(null)} />}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<Skeleton className="h-96" />}><DatasetPage /></Suspense>;
}

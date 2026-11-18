"use client";
import { useQueryClient } from "@tanstack/react-query";
import { Database, Link2, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Badge, Button, Confirm, cx, Dialog, Empty, ErrorNote, Field, Input, PageHeader, Panel, Select, Skeleton, useToast } from "@/components/ui";
import { Uploader } from "@/components/upload";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { del, errorMessage, patch, post } from "@/lib/api";
import { bytes, fmtDate } from "@/lib/format";
import type { Column, Dataset } from "@/lib/types";

const STATUS: Record<string, { label: string; tone: "forest" | "brass" | "rust" | "neutral" }> = {
  ready: { label: "Ready", tone: "forest" }, needs_sheet: { label: "Choose sheet", tone: "brass" }, processing: { label: "Processing", tone: "neutral" },
  uploaded: { label: "Uploaded", tone: "neutral" }, failed: { label: "Failed", tone: "rust" },
};

function Relationships({ datasets }: { datasets: Dataset[] }) {
  const { base, wid, can } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const rels = useWsQuery<{ relationships: any[] }>(["relationships"], "/relationships");
  const ready = datasets.filter((d) => d.status === "ready");
  const [f, setF] = useState({ left_dataset_id: "", right_dataset_id: "", left_column: "", right_column: "", join_type: "left" });
  const lc = useWsQuery<{ columns: Column[] }>(["columns", f.left_dataset_id], f.left_dataset_id ? `/datasets/${f.left_dataset_id}/columns` : null);
  const rc = useWsQuery<{ columns: Column[] }>(["columns", f.right_dataset_id], f.right_dataset_id ? `/datasets/${f.right_dataset_id}/columns` : null);
  const [report, setReport] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [mat, setMat] = useState<any>(null);
  const [matName, setMatName] = useState("");
  const [allowMult, setAllowMult] = useState(false);
  if (ready.length < 2) return null;
  const valid = f.left_dataset_id && f.right_dataset_id && f.left_column && f.right_column;
  return (
    <Panel title={<h2 className="flex items-center gap-2 text-sm font-semibold"><Link2 className="size-4 text-forest" />Dataset relationships</h2>} className="mt-6">
      <div className="space-y-4 p-4">
        <p className="text-sm text-muted">Connect two datasets on a shared key, check how well they match, then create a joined dataset for analysis. Joins are never created automatically.</p>
        {can("analyst") && (
          <div className="grid gap-3 md:grid-cols-5">
            <Field label="Left dataset" htmlFor="ld"><Select id="ld" value={f.left_dataset_id} onChange={(e) => setF({ ...f, left_dataset_id: e.target.value, left_column: "" })}><option value="">Choose</option>{ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
            <Field label="Left column" htmlFor="lcol"><Select id="lcol" value={f.left_column} onChange={(e) => setF({ ...f, left_column: e.target.value })}><option value="">Choose</option>{lc.data?.columns.map((c) => <option key={c.name} value={c.name}>{c.display_name}</option>)}</Select></Field>
            <Field label="Right dataset" htmlFor="rd"><Select id="rd" value={f.right_dataset_id} onChange={(e) => setF({ ...f, right_dataset_id: e.target.value, right_column: "" })}><option value="">Choose</option>{ready.filter((d) => d.id !== f.left_dataset_id).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
            <Field label="Right column" htmlFor="rcol"><Select id="rcol" value={f.right_column} onChange={(e) => setF({ ...f, right_column: e.target.value })}><option value="">Choose</option>{rc.data?.columns.map((c) => <option key={c.name} value={c.name}>{c.display_name}</option>)}</Select></Field>
            <Field label="Join type" htmlFor="jt"><Select id="jt" value={f.join_type} onChange={(e) => setF({ ...f, join_type: e.target.value })}><option value="left">Keep all left rows</option><option value="inner">Only matching rows</option></Select></Field>
          </div>
        )}
        {err && <ErrorNote>{err}</ErrorNote>}
        {can("analyst") && <div className="flex gap-2">
          <Button disabled={!valid} loading={busy} onClick={async () => { setBusy(true); setErr(""); try { setReport(await post(`${base}/relationships/validate`, f)); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); } }}>Preview match</Button>
          {report && <Button variant="primary" onClick={async () => { try { await post(`${base}/relationships`, f); toast("Relationship saved"); setReport(null); qc.invalidateQueries({ queryKey: [wid, "relationships"] }); } catch (e) { setErr(errorMessage(e)); } }}>Save relationship</Button>}
        </div>}
        {report && (
          <div className="rounded-md border border-line p-3 text-sm">
            <p><span className="font-medium">{report.cardinality.replace(/_/g, "-")}</span>: {report.match_rate}% of left rows match ({report.matched_left_rows.toLocaleString()} matched, {report.unmatched_left_rows.toLocaleString()} unmatched left, {report.unmatched_right_rows.toLocaleString()} unmatched right). Result: {report.result_rows.toLocaleString()} rows.</p>
            {report.warnings.map((w: string) => <p key={w} className="mt-1 text-brass">{w}</p>)}
            {report.unmatched_left_sample.length > 0 && <p className="mt-1 text-muted">Unmatched left keys: {report.unmatched_left_sample.join(", ")}</p>}
            <div className="mt-2 overflow-x-auto"><table className="text-xs"><thead><tr>{report.preview.columns.map((c: string) => <th key={c} className="px-2 py-1 text-left font-medium">{c}</th>)}</tr></thead>
              <tbody>{report.preview.rows.slice(0, 5).map((r: unknown[], i: number) => <tr key={i}>{r.map((v, j) => <td key={j} className="px-2 py-1">{String(v ?? "—")}</td>)}</tr>)}</tbody></table></div>
          </div>
        )}
        {rels.data?.relationships.length ? (
          <ul className="divide-y divide-line rounded-md border border-line">
            {rels.data.relationships.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
                <span>{r.left_dataset.name}.{r.left_column} = {r.right_dataset.name}.{r.right_column}</span>
                <Badge>{r.cardinality.replace(/_/g, "-")}</Badge><Badge>{r.join_type}</Badge>
                <span className="text-xs text-muted">{r.validation.match_rate}% match</span>
                <span className="ml-auto flex gap-2">
                  {r.materialized_dataset_id ? <Link href={`/app/data/${r.materialized_dataset_id}`} className="text-forest hover:underline">Open joined dataset</Link>
                    : can("analyst") && <Button size="sm" onClick={() => { setMat(r); setMatName(`${r.left_dataset.name} + ${r.right_dataset.name}`); setAllowMult(false); }}>Create joined dataset</Button>}
                  {can("analyst") && <Button size="sm" variant="ghost" aria-label="Delete relationship" onClick={async () => { await del(`${base}/relationships/${r.id}`); qc.invalidateQueries({ queryKey: [wid, "relationships"] }); }}><Trash2 className="size-3.5" /></Button>}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <Dialog open={!!mat} onClose={() => setMat(null)} title="Create joined dataset" footer={<><Button variant="ghost" onClick={() => setMat(null)}>Cancel</Button>
        <Button variant="primary" disabled={(mat?.cardinality === "one_to_many" || mat?.cardinality === "many_to_many") && !allowMult} onClick={async () => {
          try { await post(`${base}/relationships/${mat.id}/materialize`, { name: matName, allow_row_multiplication: allowMult }); toast("Joined dataset created"); setMat(null); qc.invalidateQueries({ queryKey: [wid] }); } catch (e) { toast(errorMessage(e), "error"); }
        }}>Create dataset</Button></>}>
        <div className="space-y-3">
          <Field label="Name" htmlFor="mn"><Input id="mn" value={matName} onChange={(e) => setMatName(e.target.value)} /></Field>
          {(mat?.cardinality === "one_to_many" || mat?.cardinality === "many_to_many") && (
            <label className="flex gap-2 text-sm"><input type="checkbox" checked={allowMult} onChange={(e) => setAllowMult(e.target.checked)} />I understand left rows will be repeated, which inflates totals of left-side measures.</label>
          )}
        </div>
      </Dialog>
    </Panel>
  );
}

export default function DataHubPage() {
  const { base, wid, can } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("created_desc");
  const list = useWsQuery<{ datasets: Dataset[] }>(["datasets", q, status, sort], `/datasets?sort=${sort}${q ? `&q=${encodeURIComponent(q)}` : ""}${status ? `&status=${status}` : ""}`);
  const all = useWsQuery<{ datasets: Dataset[] }>(["datasets"], "/datasets");
  const [rename, setRename] = useState<Dataset | null>(null);
  const [newName, setNewName] = useState("");
  const [remove, setRemove] = useState<Dataset | null>(null);
  const [menu, setMenu] = useState<string | null>(null);
  const [demoBusy, setDemoBusy] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: [wid] });
  const totals = useMemo(() => ({ rows: list.data?.datasets.reduce((s, d) => s + (d.row_count ?? 0), 0) ?? 0 }), [list.data]);

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Data Hub" description="Every dataset in this workspace, its versions and its quality. Originals are kept unchanged; preparation creates new versions."
        actions={can("analyst") && <Button loading={demoBusy} onClick={async () => { setDemoBusy(true); try { const r = await post<{ dataset: Dataset }>(`${base}/datasets/demo`); refresh(); router.push(`/app/data/${r.dataset.id}`); } catch (e) { toast(errorMessage(e), "error"); } finally { setDemoBusy(false); } }}><Database className="size-4" />Add synthetic demo data</Button>} />
      <div className="mb-6"><Uploader compact onUploaded={(d) => { refresh(); toast(`Imported ${d.name}`); router.push(`/app/data/${d.id}`); }} /></div>
      <Panel title={<div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold">Datasets</h2><span className="text-xs text-muted tnum">{list.data?.datasets.length ?? 0} datasets, {totals.rows.toLocaleString()} rows</span></div>}
        actions={<>
          <Input type="search" placeholder="Search by name or file" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 w-52 text-[13px]" aria-label="Search datasets" />
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 w-auto text-[13px]" aria-label="Filter by status"><option value="">All statuses</option><option value="ready">Ready</option><option value="needs_sheet">Needs sheet</option></Select>
          <Select value={sort} onChange={(e) => setSort(e.target.value)} className="h-8 w-auto text-[13px]" aria-label="Sort"><option value="created_desc">Newest</option><option value="created_asc">Oldest</option><option value="name">Name</option><option value="rows">Most rows</option></Select>
        </>}>
        {list.isLoading ? <div className="space-y-2 p-4">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-10" />)}</div> : !list.data?.datasets.length ? (
          <div className="p-6"><Empty icon={<Database className="size-6" />} title={q || status ? "No datasets match" : "No datasets yet"}>{q || status ? "Try a different search or filter." : "Upload a file above or add the synthetic demo data."}</Empty></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Datasets</caption>
              <thead className="text-left text-ink-2"><tr className="border-b border-line">
                {["Name", "Source", "Rows", "Columns", "Quality", "Version", "Status", "Imported", ""].map((h) => <th key={h} scope="col" className="px-4 py-2 font-medium">{h}</th>)}
              </tr></thead>
              <tbody className="divide-y divide-line">
                {list.data.datasets.map((d) => (
                  <tr key={d.id} className="hover:bg-paper/50">
                    <td className="px-4 py-2.5"><Link href={`/app/data/${d.id}`} className="font-medium hover:text-forest">{d.name}</Link>{d.is_demo && <Badge tone="brass" className="ml-2">synthetic</Badge>}<p className="text-xs text-muted">{d.original_filename}</p></td>
                    <td className="px-4 py-2.5 uppercase text-xs text-muted">{d.source_type}{d.sheet_name ? ` · ${d.sheet_name}` : ""}<p className="normal-case">{bytes(d.file_size)}</p></td>
                    <td className="tnum px-4 py-2.5">{d.row_count?.toLocaleString() ?? "—"}</td>
                    <td className="tnum px-4 py-2.5">{d.column_count ?? "—"}</td>
                    <td className="tnum px-4 py-2.5">{d.quality_score ?? "—"}</td>
                    <td className="tnum px-4 py-2.5">{d.current_version ? `v${d.current_version.version_number}` : "—"}</td>
                    <td className="px-4 py-2.5"><Badge tone={STATUS[d.status]?.tone}>{STATUS[d.status]?.label ?? d.status}</Badge></td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-muted">{fmtDate(d.created_at)}</td>
                    <td className="relative px-4 py-2.5 text-right">
                      {can("analyst") && <button aria-label={`Actions for ${d.name}`} aria-expanded={menu === d.id} onClick={() => setMenu(menu === d.id ? null : d.id)} className="rounded p-1 hover:bg-paper-2"><MoreHorizontal className="size-4" /></button>}
                      {menu === d.id && (
                        <div role="menu" className="absolute right-4 top-9 z-20 w-40 rounded-md border border-line bg-surface p-1 text-left shadow-lift">
                          <button role="menuitem" className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 hover:bg-paper" onClick={() => { setMenu(null); setRename(d); setNewName(d.name); }}><Pencil className="size-3.5" />Rename</button>
                          <button role="menuitem" className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-rust hover:bg-rust-wash" onClick={() => { setMenu(null); setRemove(d); }}><Trash2 className="size-3.5" />Delete</button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Relationships datasets={all.data?.datasets ?? []} />
      <Dialog open={!!rename} onClose={() => setRename(null)} title="Rename dataset" footer={<><Button variant="ghost" onClick={() => setRename(null)}>Cancel</Button>
        <Button variant="primary" onClick={async () => { try { await patch(`${base}/datasets/${rename!.id}`, { name: newName }); toast("Renamed"); setRename(null); refresh(); } catch (e) { toast(errorMessage(e), "error"); } }}>Save name</Button></>}>
        <Field label="Name" htmlFor="dn"><Input id="dn" value={newName} onChange={(e) => setNewName(e.target.value)} /></Field>
      </Dialog>
      <Confirm open={!!remove} onClose={() => setRemove(null)} danger title="Delete dataset" confirmLabel="Delete dataset"
        onConfirm={async () => { try { await del(`${base}/datasets/${remove!.id}`); toast("Dataset deleted"); setRemove(null); refresh(); } catch (e) { toast(errorMessage(e), "error"); } }}>
        This permanently deletes <strong>{remove?.name}</strong>, all of its versions, its stored files and its metrics. Saved reports keep their snapshots.
      </Confirm>
      <p className={cx("mt-6 text-xs text-muted")}>Limits in this deployment: files up to 50 MB and 1,000,000 rows.</p>
    </div>
  );
}

"use client";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Badge, Button, ErrorNote, Select, Skeleton } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { errorMessage, get, post } from "@/lib/api";

type Term = { key: string; question: string; candidates: { column: string; display_name: string; confidence: number }[]; suggested: string | null;
  needs_confirmation: boolean; confirmed: string | null; options: { column: string; display_name: string }[] };
export type TermsResult = { confirmed: Record<string, string>; metrics_created: { id: string; name: string; formula: string }[]; metrics_skipped: { name: string; reason: string }[] };

/** "Confirm business terminology": the user maps business meanings to columns; verified metrics follow. */
export function TermsForm({ datasetId, onDone, submitLabel = "Confirm and create metrics" }: { datasetId: string; onDone: (r: TermsResult) => void; submitLabel?: string }) {
  const { base, wid, can } = useWorkspace();
  const q = useQuery({ queryKey: [wid, "terms", datasetId], queryFn: () => get<{ terms: Term[] }>(`${base}/datasets/${datasetId}/terms`) });
  const [map, setMap] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (q.data) setMap(Object.fromEntries(q.data.terms.map((t) => [t.key, t.confirmed ?? t.suggested ?? ""])));
  }, [q.data]);
  if (q.isLoading) return <div className="space-y-2">{[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-12" />)}</div>;
  if (q.error) return <ErrorNote>{errorMessage(q.error)}</ErrorNote>;
  return (
    <form className="space-y-4" onSubmit={async (e) => {
      e.preventDefault(); setBusy(true); setErr("");
      try { onDone(await post<TermsResult>(`${base}/datasets/${datasetId}/terms`, { mapping: Object.fromEntries(Object.entries(map).map(([k, v]) => [k, v || null])), create_metrics: true })); }
      catch (x) { setErr(errorMessage(x)); } finally { setBusy(false); }
    }}>
      {err && <ErrorNote>{err}</ErrorNote>}
      <div className="divide-y divide-line rounded-lg border border-line bg-surface">
        {q.data?.terms.map((t) => {
          const chosen = map[t.key] ?? "";
          const cand = t.candidates.find((c) => c.column === chosen);
          return (
            <div key={t.key} className="grid items-center gap-3 px-4 py-3 sm:grid-cols-[1fr_15rem]">
              <div>
                <label htmlFor={`t-${t.key}`} className="text-sm font-medium">{t.question}</label>
                <p className="mt-0.5 text-xs text-muted">
                  {t.confirmed ? <Badge tone="forest">confirmed</Badge> : t.needs_confirmation ? <Badge tone="brass">please check</Badge> : cand ? <Badge>suggested from the column name</Badge> : <span>Choose “Not in this data” if it doesn’t apply.</span>}
                </p>
              </div>
              <Select id={`t-${t.key}`} value={chosen} onChange={(e) => setMap({ ...map, [t.key]: e.target.value })}>
                <option value="">Not in this data</option>
                {t.options.map((o) => <option key={o.column} value={o.column}>{o.display_name}</option>)}
              </Select>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-muted">ClearMetric creates verified metrics only for the meanings you confirm here, for example Net Revenue = SUM of the column you chose. You can edit them later in the Metric Library.</p>
      {can("analyst") && <Button type="submit" variant="primary" loading={busy}>{submitLabel}</Button>}
    </form>
  );
}

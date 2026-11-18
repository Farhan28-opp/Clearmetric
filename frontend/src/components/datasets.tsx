"use client";
import { useEffect, useState } from "react";
import { Badge, Select } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import type { Column, Dataset, Metric } from "@/lib/types";

export function useDatasets() {
  return useWsQuery<{ datasets: Dataset[] }>(["datasets"], "/datasets");
}

/** Remembers the dataset in use per workspace (a UI preference; data itself lives on the server). */
export function useActiveDataset(initial?: string | null) {
  const { wid, ws } = useWorkspace();
  const q = useDatasets();
  const key = `cm_ds_${wid}`;
  const [id, setId] = useState<string | null>(initial ?? null);
  useEffect(() => {
    if (!q.data) return;
    const ready = q.data.datasets.filter((d) => d.status === "ready");
    if (id && ready.some((d) => d.id === id)) return;
    let stored: string | null = null;
    try { stored = localStorage.getItem(key); } catch { /* ignore */ }
    const pick = [initial, stored, ws?.onboarding?.dataset_id, ready[0]?.id].find((x) => x && ready.some((d) => d.id === x)) ?? null;
    setId(pick);
  }, [q.data, id, key, initial, ws?.onboarding?.dataset_id]);
  const choose = (v: string) => { setId(v); try { localStorage.setItem(key, v); } catch { /* ignore */ } };
  const dataset = q.data?.datasets.find((d) => d.id === id) ?? null;
  return { id, dataset, choose, datasets: q.data?.datasets ?? [], loading: q.isLoading };
}

export function DatasetSelect({ value, onChange, datasets, label = "Dataset" }: { value: string | null; onChange: (v: string) => void; datasets: Dataset[]; label?: string }) {
  const compact = label === "";
  const ready = datasets.filter((d) => d.status === "ready");
  const current = ready.find((d) => d.id === value);
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="ds-select" className={compact ? "sr-only" : "text-sm text-muted"}>{label || "Dataset"}</label>
      <Select id="ds-select" value={value ?? ""} onChange={(e) => onChange(e.target.value)} className={compact ? "h-8.5 w-full text-[13px]" : "h-8.5 w-auto min-w-48 max-w-72 text-[13px]"}>
        {!ready.length && <option value="">No datasets yet</option>}
        {ready.map((d) => <option key={d.id} value={d.id}>{d.name} (v{d.current_version?.version_number})</option>)}
      </Select>
      {current?.is_demo && !compact && <Badge tone="brass">synthetic data</Badge>}
    </div>
  );
}

export function useColumns(datasetId: string | null) {
  return useWsQuery<{ columns: Column[] }>(["columns", datasetId], datasetId ? `/datasets/${datasetId}/columns` : null);
}

export function useMetrics(datasetId?: string | null) {
  return useWsQuery<{ metrics: Metric[]; categories: string[] }>(["metrics", datasetId ?? "all"], `/metrics${datasetId ? `?dataset_id=${datasetId}` : ""}`);
}

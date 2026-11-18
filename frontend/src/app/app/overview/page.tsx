"use client";
import { AlertTriangle, BookMarked, FileText, Lightbulb, MessageSquareText, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { DatasetSelect, useActiveDataset } from "@/components/datasets";
import { Badge, ButtonLink, cx, Empty, PageHeader, Panel, Select, Skeleton } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { compact, fmtPct, fmtValue, timeAgo } from "@/lib/format";
import type { Conversation, Insight, Report } from "@/lib/types";

type Overview = {
  ready: boolean; dataset: { id: string; name: string; is_demo: boolean; version: number; rows: number; quality: number };
  period: { current: string; baseline: string | null; latest_date: string | null; date_column: string | null };
  kpis: { metric_id: string; name: string; formula: string; unit: string; version: number; current: number | null; baseline: number | null; change_pct: number | null }[];
  trend: { metric: string; rows: Record<string, any>[]; notes: string[] } | null; unverified_metrics: number;
};

export default function OverviewPage() {
  const { ws, me } = useWorkspace();
  const { id, choose, datasets, loading } = useActiveDataset();
  const [period, setPeriod] = useState("latest_month");
  const ov = useWsQuery<Overview>(["overview", id, period], id ? `/analysis/overview?dataset_id=${id}&period=${period}` : null);
  const ins = useWsQuery<{ insights: Insight[] }>(["insights", id, "active"], id ? `/insights?dataset_id=${id}&status=active` : null);
  const convs = useWsQuery<{ conversations: Conversation[] }>(["conversations", "saved"], "/conversations?saved=true");
  const reps = useWsQuery<{ reports: Report[] }>(["reports"], "/reports");
  const sugg = useWsQuery<{ questions: string[] }>(["suggestions", id], id ? `/conversations/suggestions?dataset_id=${id}` : null);
  const cur = ws?.currency ?? "USD";
  const attention = ins.data?.insights.filter((i) => i.severity === "high" && ["performance_changes", "regional_performance", "product_performance", "growth_decline"].includes(i.category)).slice(0, 3) ?? [];
  const lowQuality = datasets.filter((d) => d.status === "ready" && (d.quality_score ?? 100) < 95);

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title={`${ws?.name ?? ""}: business pulse`} description={`Good to see you, ${me.user.full_name.split(" ")[0]}. Figures below use verified metrics only.`}
        actions={<>
          <DatasetSelect value={id} onChange={choose} datasets={datasets} />
          <label className="sr-only" htmlFor="period">Period</label>
          <Select id="period" value={period} onChange={(e) => setPeriod(e.target.value)} className="h-8.5 w-auto text-[13px]">
            <option value="latest_month">Latest month vs previous</option><option value="last_3_months">Last 3 months vs previous 3</option>
            <option value="ytd">Year to date vs last year</option><option value="all">All dates</option>
          </Select>
        </>} />

      {!loading && !datasets.length && (
        <Empty icon={<Upload className="size-6" />} title="No data in this workspace yet" action={<ButtonLink href="/app/onboarding" variant="primary">Add data</ButtonLink>}>
          Upload a CSV or Excel file, or load the synthetic demo dataset, to see your business pulse.
        </Empty>
      )}

      {id && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted">
            {ov.data?.ready && <>
              <span>Period: <span className="text-ink">{ov.data.period.current}</span>{ov.data.period.baseline && <> compared with {ov.data.period.baseline}</>}</span>
              {ov.data.period.date_column && <span>Dated by {ov.data.period.date_column}, latest record {ov.data.period.latest_date}</span>}
              <span>{ov.data.dataset.name} v{ov.data.dataset.version}, {ov.data.dataset.rows.toLocaleString()} rows</span>
              {ov.data.dataset.is_demo && <Badge tone="brass">synthetic demonstration data</Badge>}
            </>}
          </div>
          {ov.isLoading ? <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-24" />)}</div> : ov.data?.kpis.length ? (
            <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-4">
              {ov.data.kpis.map((k) => (
                <div key={k.metric_id} className="bg-surface p-4">
                  <dt className="flex items-center justify-between text-[13px] text-muted"><span>{k.name}</span><span title={`${k.formula} (v${k.version})`} className="text-[11px]">v{k.version}</span></dt>
                  <dd className="tnum mt-1.5 text-[26px] font-semibold leading-none">{fmtValue(k.current, k.unit, cur)}</dd>
                  {k.baseline !== null && (
                    <dd className="mt-2 text-xs text-muted">
                      <span className={cx("tnum font-medium", (k.change_pct ?? 0) < 0 ? "text-rust" : "text-forest")}>{k.unit === "percent" ? fmtValue((k.current ?? 0) - (k.baseline ?? 0), "percent_points") : fmtPct(k.change_pct)}</span> vs {fmtValue(k.baseline, k.unit, cur)}
                    </dd>
                  )}
                </div>
              ))}
            </dl>
          ) : ov.data && (
            <Empty icon={<BookMarked className="size-6" />} title="No verified metrics for this dataset" action={<ButtonLink href={`/app/data/${id}?tab=terms`} variant="primary">Confirm business terms</ButtonLink>}>
              Overview tiles only show verified metrics, so that every number has an agreed definition.{ov.data.unverified_metrics ? ` ${ov.data.unverified_metrics} metric(s) are waiting for verification in the Metric Library.` : ""}
            </Empty>
          )}

          <div className="mt-6 grid gap-6 lg:grid-cols-[1.7fr_1fr]">
            <Panel title={ov.data?.trend ? `${ov.data.trend.metric} by month` : "Recent performance"} actions={<Link href="/app/explore" className="text-sm text-forest hover:underline">Explore</Link>}>
              <div className="h-72 p-3">
                {ov.data?.trend?.rows.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={ov.data.trend.rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                      <CartesianGrid stroke="#e4e7de" vertical={false} />
                      <XAxis dataKey="period_label" tick={{ fontSize: 11.5, fill: "#66726b" }} tickLine={false} minTickGap={20} />
                      <YAxis tickFormatter={(v) => compact(v, 0)} tick={{ fontSize: 11.5, fill: "#66726b" }} tickLine={false} axisLine={false} width={50} />
                      <Tooltip formatter={(v) => fmtValue(Number(v), "currency", cur)} contentStyle={{ borderRadius: 6, fontSize: 13 }} />
                      <Line dataKey="m0" name={ov.data.trend.metric} stroke="#1f6b52" strokeWidth={2.2} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : <p className="p-4 text-sm text-muted">{ov.isLoading ? "Loading…" : "A monthly trend appears once a verified revenue metric and a date column are available."}</p>}
              </div>
              {ov.data?.trend?.notes.map((n) => <p key={n} className="border-t border-line px-4 py-2 text-xs text-muted">{n}</p>)}
            </Panel>
            <Panel title="Changes that deserve attention" actions={<Link href="/app/insights" className="text-sm text-forest hover:underline">All insights</Link>}>
              <ul className="divide-y divide-line">
                {attention.map((i) => (
                  <li key={i.id} className="px-4 py-3"><Link href={`/app/insights?i=${i.id}`} className="block hover:text-forest"><span className="text-sm font-medium">{i.title}</span><span className="mt-0.5 block text-xs text-muted">{i.date_range} vs {i.baseline}</span></Link></li>
                ))}
                {!attention.length && <li className="px-4 py-4 text-sm text-muted">{ins.data ? (ins.data.insights.length ? "No high-importance changes right now." : "Run an insight scan to check for notable changes.") : "Loading…"}</li>}
              </ul>
            </Panel>
          </div>

          <div className="mt-6 grid gap-6 md:grid-cols-2 xl:grid-cols-4">
            <Panel title="Important insights">
              <ul className="divide-y divide-line">{ins.data?.insights.slice(0, 4).map((i) => (
                <li key={i.id} className="flex gap-2 px-4 py-2.5 text-sm"><Lightbulb className="mt-0.5 size-4 shrink-0 text-forest" /><Link href={`/app/insights?i=${i.id}`} className="hover:text-forest">{i.title}</Link></li>))}
                {ins.data && !ins.data.insights.length && <li className="px-4 py-3 text-sm text-muted"><Link href="/app/insights" className="text-forest">Scan this dataset</Link> to find insights.</li>}
              </ul>
            </Panel>
            <Panel title="Saved investigations">
              <ul className="divide-y divide-line">{convs.data?.conversations.slice(0, 5).map((c) => (
                <li key={c.id} className="px-4 py-2.5 text-sm"><Link href={`/app/analyst?c=${c.id}`} className="block truncate hover:text-forest">{c.title}</Link><span className="text-xs text-muted">{timeAgo(c.updated_at)}</span></li>))}
                {convs.data && !convs.data.conversations.length && <li className="px-4 py-3 text-sm text-muted">Save an investigation in the AI Analyst to find it here.</li>}
              </ul>
            </Panel>
            <Panel title="Recent reports">
              <ul className="divide-y divide-line">{reps.data?.reports.slice(0, 5).map((r) => (
                <li key={r.id} className="px-4 py-2.5 text-sm"><Link href={`/app/reports/${r.id}`} className="flex items-center gap-2 truncate hover:text-forest"><FileText className="size-4 shrink-0 text-muted" />{r.title}</Link></li>))}
                {reps.data && !reps.data.reports.length && <li className="px-4 py-3 text-sm text-muted">No reports yet.</li>}
              </ul>
            </Panel>
            <Panel title="Data-quality warnings">
              <ul className="divide-y divide-line">{lowQuality.map((d) => (
                <li key={d.id} className="flex items-center gap-2 px-4 py-2.5 text-sm"><AlertTriangle className="size-4 text-brass" /><Link href={`/app/data/${d.id}?tab=quality`} className="truncate hover:text-forest">{d.name}</Link><span className="tnum ml-auto text-xs text-muted">{d.quality_score}</span></li>))}
                {!lowQuality.length && <li className="px-4 py-3 text-sm text-muted">All ready datasets score 95 or above. Small issues may still be listed per dataset.</li>}
              </ul>
            </Panel>
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-[1.7fr_1fr]">
            <Panel title="Suggested investigations">
              <ul className="grid gap-2 p-4 sm:grid-cols-2">
                {sugg.data?.questions.map((q) => (
                  <li key={q}><Link href={`/app/analyst?new=1&q=${encodeURIComponent(q)}`} className="flex h-full items-start gap-2 rounded-md border border-line px-3 py-2 text-sm hover:border-forest"><MessageSquareText className="mt-0.5 size-4 shrink-0 text-forest" />{q}</Link></li>
                ))}
              </ul>
            </Panel>
            <Panel title="Quick actions">
              <div className="grid gap-2 p-4">
                <ButtonLink href="/app/analyst?new=1" variant="primary">Ask a business question</ButtonLink>
                <ButtonLink href="/app/data">Upload data</ButtonLink>
                <ButtonLink href="/app/metrics">Explore a metric</ButtonLink>
                <ButtonLink href="/app/insights">Review insights</ButtonLink>
                <ButtonLink href="/app/reports?new=executive">Generate an executive report</ButtonLink>
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

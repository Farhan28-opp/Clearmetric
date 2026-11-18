"use client";
import { Activity as Icon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button, Empty, PageHeader, Select, Skeleton } from "@/components/ui";
import { useWsQuery } from "@/components/workspace";
import { fmtDate } from "@/lib/format";

type Ev = { id: string; type: string; summary: string; resource_type: string; resource_id: string; user: string; created_at: string };

const href = (e: Ev) => ({ dataset: `/app/data/${e.resource_id}`, metric: `/app/metrics?metric=${e.resource_id}`, conversation: `/app/analyst?c=${e.resource_id}`,
  report: `/app/reports/${e.resource_id}`, insight: `/app/insights?i=${e.resource_id}`, workspace: "/app/settings?tab=workspace", relationship: "/app/data" } as Record<string, string>)[e.resource_type];

export default function ActivityPage() {
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const q = useWsQuery<{ events: Ev[]; total: number; types: string[] }>(["activity", type, page], `/activity?page=${page}&page_size=40${type ? `&type=${type}` : ""}`);
  let lastDay = "";
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Activity" description="A record of imports, data changes, metric definitions, questions, analyses, insights and reports in this workspace."
        actions={<Select aria-label="Event type" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} className="h-8.5 w-auto text-[13px]"><option value="">All activity</option>{q.data?.types.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}</Select>} />
      {q.isLoading && <Skeleton className="h-96" />}
      {q.data && !q.data.events.length && <Empty icon={<Icon className="size-6" />} title="No activity yet">Activity appears as you and your teammates work.</Empty>}
      <ol className="relative space-y-0 border-l border-line pl-6">
        {q.data?.events.map((e) => {
          const day = fmtDate(e.created_at);
          const header = day !== lastDay ? (lastDay = day) : null;
          const link = href(e);
          return (
            <li key={e.id} className="pb-4">
              {header && <p className="-ml-6 mb-2 mt-2 bg-paper pl-0 text-xs font-medium text-muted">{header}</p>}
              <span aria-hidden className="absolute -left-[5px] mt-1.5 size-2.5 rounded-full border-2 border-paper bg-forest" />
              <p className="text-sm">{link ? <Link href={link} className="hover:text-forest">{e.summary}</Link> : e.summary}</p>
              <p className="text-xs text-muted">{e.user} · {new Date(e.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {e.type.replace(/_/g, " ")}</p>
            </li>);
        })}
      </ol>
      {q.data && q.data.total > 40 && (
        <div className="mt-4 flex items-center justify-between text-sm"><span className="text-muted">Page {page} of {Math.ceil(q.data.total / 40)}</span>
          <div className="flex gap-2"><Button size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>Newer</Button><Button size="sm" disabled={page * 40 >= q.data.total} onClick={() => setPage(page + 1)}>Older</Button></div></div>)}
    </div>
  );
}

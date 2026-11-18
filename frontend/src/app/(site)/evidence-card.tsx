"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Bar, BarChart, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { cx, Skeleton } from "@/components/ui";
import { compact } from "@/lib/format";

type Q = { question: string; intent: string; rows: { label: string; value: number; share?: number | null }[]; plan: Record<string, string | number>; trail: string[] };

export function EvidenceCard() {
  const { data, isError } = useQuery({
    queryKey: ["demo-preview"],
    queryFn: async () => {
      const r = await fetch("/api/public/demo-preview");
      if (!r.ok) throw new Error("unavailable");
      return r.json() as Promise<{ dataset: { name: string; rows: number }; questions: Q[] }>;
    },
    staleTime: Infinity,
  });
  const [i, setI] = useState(0);
  const q = data?.questions[i];
  return (
    <div className="rounded-xl border border-line-2 bg-surface shadow-lift">
      <div className="flex gap-1 overflow-x-auto border-b border-line p-2" role="tablist" aria-label="Example questions">
        {(data?.questions ?? [{ question: "Top products" }, { question: "Monthly revenue" }, { question: "Profit decline" }]).map((x, k) => (
          <button key={k} role="tab" aria-selected={k === i} onClick={() => setI(k)}
            className={cx("whitespace-nowrap rounded-md px-2.5 py-1.5 text-[13px]", k === i ? "bg-ink text-white" : "text-ink-2 hover:bg-paper-2")}>
            {["Top products", "Monthly trend", "Why profit fell"][k]}
          </button>
        ))}
      </div>
      <div className="p-5">
        {isError && <p className="text-sm text-muted">The live preview needs the ClearMetric backend running. Start it and refresh this page.</p>}
        {!data && !isError && <div className="space-y-3"><Skeleton className="h-6 w-3/4" /><Skeleton className="h-40" /><Skeleton className="h-16" /></div>}
        {q && (
          <div key={i} className="reveal space-y-4">
            <p className="flex gap-2 text-[15px] font-medium"><span className="text-muted">You asked</span>{q.question}</p>
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                {q.intent === "trend" ? (
                  <LineChart data={q.rows} margin={{ left: 0, right: 8, top: 6, bottom: 0 }}>
                    <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#66726b" }} tickLine={false} axisLine={{ stroke: "#d6dbd0" }} interval={1} />
                    <YAxis tickFormatter={(v) => compact(v, 0)} tick={{ fontSize: 11, fill: "#66726b" }} tickLine={false} axisLine={false} width={42} />
                    <Tooltip formatter={(v) => compact(Number(v))} />
                    <Line dataKey="value" stroke="#1f6b52" strokeWidth={2.2} dot={false} isAnimationActive={false} />
                  </LineChart>
                ) : (
                  <BarChart data={q.rows} layout="vertical" margin={{ left: 0, right: 12, top: 0, bottom: 0 }}>
                    <XAxis type="number" hide domain={q.intent === "decompose_change" ? ["dataMin", 0] : [0, "dataMax"]} />
                    <YAxis type="category" dataKey="label" width={112} tick={{ fontSize: 12, fill: "#3d4a43" }} tickLine={false} axisLine={false} />
                    <Tooltip formatter={(v) => compact(Number(v))} cursor={{ fill: "#eef0e9" }} />
                    <Bar dataKey="value" radius={2} isAnimationActive={false} barSize={14}>
                      {q.rows.map((r, k) => <Cell key={k} fill={r.value < 0 ? (k === 0 ? "#b4533c" : "#d9a493") : k === 0 ? "#1f6b52" : "#8fc2ab"} />)}
                    </Bar>
                  </BarChart>
                )}
              </ResponsiveContainer>
            </div>
            <p className="text-sm leading-relaxed text-ink-2">
              {q.intent === "rank" && <>{q.rows[0].label} leads with {compact(q.rows[0].value)} in net revenue, {q.rows[0].share}% of the total.</>}
              {q.intent === "trend" && <>Monthly net revenue over the last 12 months, from {compact(Math.min(...q.rows.map((r) => r.value)))} to {compact(Math.max(...q.rows.map((r) => r.value)))}.</>}
              {q.intent === "decompose_change" && <>{q.rows[0].label} accounts for {q.rows[0].share}% of the profit decline ({compact(q.rows[0].value)}).</>}
            </p>
            <div className="rounded-md border border-line bg-paper/70 p-3">
              <p className="mb-2 text-xs font-medium text-ink-2">How this was calculated</p>
              <ol className="space-y-1 text-[13px] text-ink-2">
                {q.trail.map((t, k) => <li key={k} className="flex gap-2"><span className="tnum text-muted">{k + 1}.</span>{t}</li>)}
              </ol>
            </div>
          </div>
        )}
      </div>
      <p className="border-t border-line px-5 py-2.5 text-xs text-muted">
        Computed live from {data ? `${data.dataset.rows.toLocaleString()} rows of ` : ""}synthetic demonstration data. Not real business data.
      </p>
    </div>
  );
}

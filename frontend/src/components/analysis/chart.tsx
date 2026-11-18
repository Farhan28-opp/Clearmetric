"use client";
import { useMemo } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import { compact, fmtValue } from "@/lib/format";
import type { AnalysisResult } from "@/lib/types";

export const PALETTE = ["#1f6b52", "#a7791f", "#3f6fa8", "#7d4e8c", "#2e8c86", "#b4533c", "#6b7a3a", "#5b665f", "#c07a9a", "#4d5fa0", "#8a6d3b", "#3a7f5f"];
export const CHART_TYPES = ["bar", "hbar", "line", "area", "stacked_bar", "donut", "histogram", "scatter", "waterfall", "table"] as const;
const AX = { fontSize: 11.5, fill: "#66726b" };

export function defaultChartType(r: AnalysisResult): string {
  return r.chart?.type ?? "table";
}

export function allowedChartTypes(r: AnalysisResult): string[] {
  const t = r.chart?.type;
  if (!t || t === "kpi" || t === "table") return ["table"];
  if (t === "line") return r.series ? ["line", "area", "table"] : ["line", "area", "bar", "table"];
  if (t === "histogram") return ["histogram", "table"];
  if (t === "scatter") return ["scatter", "table"];
  if (t === "waterfall") return ["waterfall", "hbar", "table"];
  if (t === "stacked_bar") return ["stacked_bar", "table"];
  return ["bar", "hbar", "donut", "table"].filter((x) => x !== "donut" || (r.rows.length <= 10 && r.rows.every((row) => (row[r.chart?.y?.[0] ?? ""] ?? 0) >= 0)));
}

function useSeriesData(r: AnalysisResult) {
  return useMemo(() => {
    const x = r.chart?.x ?? "period_label";
    const s = r.chart?.series;
    const y = r.chart?.y?.[0] ?? "m0";
    if (!s) return { data: r.rows, keys: r.chart?.y ?? [y] };
    const byX = new Map<string, Record<string, unknown>>();
    const keys: string[] = [];
    for (const row of r.rows) {
      const k = String(row[x]);
      const sk = String(row[s]);
      if (!keys.includes(sk)) keys.push(sk);
      const o = byX.get(k) ?? { [x]: k };
      o[sk] = row[y];
      byX.set(k, o);
    }
    return { data: [...byX.values()], keys };
  }, [r]);
}

export function ResultChart({ result, type, currency, height = 300, onSelect }: {
  result: AnalysisResult; type: string; currency: string; height?: number; onSelect?: (value: string) => void;
}) {
  const { data, keys } = useSeriesData(result);
  const x = result.chart?.x ?? "period_label";
  const ycol = result.columns.find((c) => c.key === (result.chart?.y?.[0] ?? "m0"));
  const unit = ycol?.role === "percent" ? "pct" : ycol?.unit ?? "number";
  const fmt = (v: unknown) => (typeof v === "number" ? fmtValue(v, unit, currency, 2) : String(v));
  const axisFmt = (v: number) => (unit === "percent" ? `${(v * 100).toFixed(0)}%` : unit === "pct" ? `${v.toFixed(0)}%` : compact(v, 0));
  const labelOf = (k: string) => result.columns.find((c) => c.key === k)?.label ?? k;
  const click = (d: { payload?: Record<string, unknown> } | undefined) => { const v = d?.payload?.[x]; if (onSelect && v !== undefined && v !== "All other") onSelect(String(v)); };
  const tip = <Tooltip formatter={(v, n) => [fmt(v), labelOf(String(n))]} cursor={{ fill: "#eef0e9" }} contentStyle={{ borderRadius: 6, borderColor: "#d6dbd0", fontSize: 13 }} />;
  const grid = <CartesianGrid stroke="#e4e7de" vertical={false} />;

  if (type === "line" || type === "area") {
    const C = type === "line" ? LineChart : AreaChart;
    return (
      <ResponsiveContainer width="100%" height={height}>
        <C data={data} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
          {grid}
          <XAxis dataKey={x} tick={AX} tickLine={false} axisLine={{ stroke: "#d6dbd0" }} minTickGap={16} />
          <YAxis tick={AX} tickFormatter={axisFmt} tickLine={false} axisLine={false} width={56} />
          {tip}
          {keys.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v) => labelOf(String(v))} />}
          {keys.map((k, i) => type === "line"
            ? <Line key={k} dataKey={k} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2} dot={data.length < 30 ? { r: 2.5 } : false} isAnimationActive={false} />
            : <Area key={k} dataKey={k} stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.14} strokeWidth={2} stackId={keys.length > 1 ? "a" : undefined} isAnimationActive={false} />)}
        </C>
      </ResponsiveContainer>
    );
  }
  if (type === "donut") {
    const y = result.chart?.y?.[0] ?? "m0";
    const rows = result.rows.filter((r) => typeof r[y] === "number" && r[y] > 0);
    return (
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie data={rows} dataKey={y} nameKey={x} innerRadius="55%" outerRadius="85%" paddingAngle={1} isAnimationActive={false} onClick={(d) => click({ payload: (d as unknown as { payload?: Record<string, unknown> }).payload })}>
            {rows.map((row, i) => <Cell key={i} fill={row[x] === "All other" ? "#c3cabd" : PALETTE[i % PALETTE.length]} stroke="#fbfbf8" />)}
          </Pie>
          <Tooltip formatter={(v) => fmt(v)} contentStyle={{ borderRadius: 6, fontSize: 13 }} />
          <Legend layout="vertical" align="right" verticalAlign="middle" wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    );
  }
  if (type === "scatter") {
    const pts = result.rows.map((r, i) => ({ ...r, i: i + 1 }));
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
          {grid}
          <XAxis dataKey="i" name="Rank by deviation" tick={AX} tickLine={false} />
          <YAxis dataKey="v" tick={AX} tickFormatter={axisFmt} width={56} tickLine={false} axisLine={false} />
          {result.bounds && <ReferenceLine y={result.bounds.high} stroke="#a7791f" strokeDasharray="4 3" label={{ value: "upper bound", fontSize: 11, fill: "#a7791f", position: "insideTopRight" }} />}
          {result.bounds && <ReferenceLine y={result.bounds.median} stroke="#66726b" strokeDasharray="2 3" label={{ value: "median", fontSize: 11, fill: "#66726b", position: "insideBottomRight" }} />}
          <Tooltip formatter={(v) => fmt(v)} contentStyle={{ borderRadius: 6, fontSize: 13 }} />
          <Scatter data={pts} fill="#b4533c" isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }
  const horizontal = type === "hbar" || (type === "waterfall" && data.length > 8);
  const stacked = type === "stacked_bar";
  const bars = type === "waterfall" ? ["change"] : keys;
  const h = horizontal ? Math.max(height, data.length * 28 + 40) : height;
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
        <CartesianGrid stroke="#e4e7de" horizontal={!horizontal} vertical={horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" tick={AX} tickFormatter={axisFmt} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey={x} tick={{ ...AX, fill: "#3d4a43" }} width={130} tickLine={false} axisLine={false} interval={0} />
          </>
        ) : (
          <>
            <XAxis dataKey={x} tick={AX} tickLine={false} axisLine={{ stroke: "#d6dbd0" }} interval={data.length > 14 ? "preserveStartEnd" : 0} angle={data.length > 8 ? -25 : 0} textAnchor={data.length > 8 ? "end" : "middle"} height={data.length > 8 ? 60 : 30} />
            <YAxis tick={AX} tickFormatter={axisFmt} tickLine={false} axisLine={false} width={56} />
          </>
        )}
        {tip}
        {(bars.length > 1 || stacked) && <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v) => labelOf(String(v))} />}
        {type === "waterfall" && <ReferenceLine {...(horizontal ? { x: 0 } : { y: 0 })} stroke="#3d4a43" />}
        {bars.map((k, i) => (
          <Bar key={k} dataKey={k} stackId={stacked ? "s" : undefined} fill={PALETTE[i % PALETTE.length]} radius={stacked ? 0 : 2} maxBarSize={44}
            onClick={(d) => click(d as { payload?: Record<string, unknown> })} className={onSelect ? "cursor-pointer" : undefined} isAnimationActive={false}>
            {(type === "waterfall" || (!stacked && bars.length === 1)) && data.map((row, j) => {
              const v = Number((row as Record<string, unknown>)[k] ?? 0);
              const fill = type === "waterfall" ? (v < 0 ? "#b4533c" : "#1f6b52") : row[x as keyof typeof row] === "All other" ? "#c3cabd" : PALETTE[0];
              return <Cell key={j} fill={fill} />;
            })}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Export the rendered SVG chart inside `container` as a PNG file. */
export function exportPng(container: HTMLElement | null, name: string) {
  const svg = container?.querySelector("svg.recharts-surface");
  if (!svg) return;
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const { width, height } = svg.getBoundingClientRect();
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const src = new XMLSerializer().serializeToString(clone);
  const img = new Image();
  img.onload = () => {
    const c = document.createElement("canvas");
    const scale = 2;
    c.width = width * scale;
    c.height = height * scale;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "#fbfbf8";
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    const a = document.createElement("a");
    a.download = `${name.replace(/[^a-z0-9-_]+/gi, "_").slice(0, 60) || "chart"}.png`;
    a.href = c.toDataURL("image/png");
    a.click();
  };
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(src);
}

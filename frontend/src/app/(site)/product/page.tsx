import type { Metadata } from "next";
import { ButtonLink } from "@/components/ui";

export const metadata: Metadata = { title: "Product" };

const PARTS = [
  { id: "data", title: "Data understanding", body: "Upload a CSV or Excel workbook. ClearMetric detects delimiters, encodings, headers and sheets; infers integer, decimal, date, text and yes/no columns; and classifies each as a measure, dimension, date or identifier. A Data Quality Score with a published formula tells you how complete, unique, valid and consistent the data is, and lists every issue it found.", points: ["Immutable original upload, analytical copy stored as Parquet", "Versioned preparation steps with preview and restore", "Explicit dataset relationships with match rates and cardinality checks"] },
  { id: "metrics", title: "Metric Library", body: "A metric is a named, versioned formula such as Net Revenue = SUM(net_revenue) or Profit Margin = SUM(profit) / SUM(net_revenue). You confirm which columns mean what; ClearMetric never infers a business definition from a column name alone. Verified metrics are what the Analyst, Explore, Insights and Reports all use.", points: ["Restricted formula language: SUM, AVG, COUNT, COUNT_DISTINCT, MIN, MAX, conditional aggregates, ratios", "Division by zero returns empty, never infinity", "Editing a formula creates a new version and resets verification"] },
  { id: "analyst", title: "AI Analyst", body: "Questions become structured analysis plans: intent, metric, dimensions, filters, time range, comparison and chart. The server validates each plan against your workspace and compiles it to parameterised SQL for DuckDB. Follow-up questions resolve references like “their” or “the second-highest region” from the previous result and run a new calculation.", points: ["Clarifies ambiguous terms instead of guessing", "Inspect panel with records, filters, formula and query", "Save, pin, annotate, duplicate and export investigations"] },
  { id: "explore", title: "Data exploration", body: "The visual builder produces the same analysis plan as a typed question, so you can move between asking and configuring. Choose a metric, a dimension, filters and dates; pick a chart type suited to the question; click a bar to drill into the next dimension.", points: ["Bar, line, area, stacked, donut, histogram, scatter and waterfall views", "Table view and CSV, XLSX and PNG exports", "Saved visualisations stay linked to their calculation"] },
  { id: "insights", title: "Insights Center", body: "A scan runs documented statistical checks: month-over-month and year-over-year changes, segment contributions to a change, concentration, coefficient of variation, IQR outlier candidates, trend and seasonality, margin gaps and correlations. Each finding lists its method, baseline and limitations.", points: ["Configurable thresholds per workspace", "Inspect supporting calculations and affected records", "Save, dismiss, annotate or add to a report"] },
  { id: "reports", title: "Reports and executive briefs", body: "Build a report from a blank page, an investigation or selected insights. The executive summary computes KPIs for the reporting period against the previous period, lists contributors, findings, anomalies and limitations, and keeps computed facts separate from interpretation.", points: ["Sections store a snapshot, so reports don’t change silently", "PDF with methodology and data source; CSV and XLSX data", "Reorder, retitle, refresh and duplicate"] },
];

export default function ProductPage() {
  return (
    <div className="mx-auto max-w-6xl px-5 py-14">
      <header className="max-w-3xl">
        <h1 className="text-4xl font-semibold tracking-[-0.02em]">How ClearMetric is put together</h1>
        <p className="mt-4 text-lg text-ink-2">Information moves in one direction: data is understood, business terms are defined, questions become validated plans, the engine computes, and the results feed insights and reports.</p>
      </header>
      <figure className="mt-10 overflow-x-auto rounded-lg border border-line bg-surface p-6" aria-label="Information flow">
        <ol className="flex min-w-[760px] items-stretch gap-2 text-sm">
          {["Upload and profile", "Confirm business terms", "Verified metrics", "Question or visual builder", "Validated analysis plan", "DuckDB computation", "Answer, insight or report"].map((s, i, a) => (
            <li key={s} className="flex flex-1 items-center gap-2">
              <span className={`flex h-full flex-1 items-center rounded-md border px-3 py-3 ${i === 4 ? "border-forest bg-forest-wash font-medium text-forest-2" : "border-line-2"}`}>{s}</span>
              {i < a.length - 1 && <span aria-hidden className="text-muted">›</span>}
            </li>
          ))}
        </ol>
        <figcaption className="mt-3 text-xs text-muted">The analysis plan is the only path from language to computation. Nothing executes without passing validation.</figcaption>
      </figure>
      <div className="mt-14 space-y-14">
        {PARTS.map((p) => (
          <section key={p.id} id={p.id} aria-labelledby={`${p.id}-h`} className="grid gap-6 border-t border-line pt-8 md:grid-cols-[1fr_1.6fr]">
            <h2 id={`${p.id}-h`} className="text-2xl font-semibold">{p.title}</h2>
            <div>
              <p className="leading-relaxed text-ink-2">{p.body}</p>
              <ul className="mt-4 space-y-1.5 text-sm">{p.points.map((x) => <li key={x} className="flex gap-2"><span className="text-forest" aria-hidden>✓</span>{x}</li>)}</ul>
            </div>
          </section>
        ))}
      </div>
      <div className="mt-16 flex gap-3"><ButtonLink href="/signup" variant="primary">Try it with demo data</ButtonLink><ButtonLink href="/how-it-works">See the workflow</ButtonLink></div>
    </div>
  );
}

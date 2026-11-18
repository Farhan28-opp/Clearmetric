import type { Metadata } from "next";
import { ButtonLink } from "@/components/ui";

export const metadata: Metadata = { title: "How it works" };

const STEPS = [
  ["Import data", "Upload a CSV or Excel file, or load the synthetic retail dataset. The original file is kept unchanged; an analytical copy is stored as Parquet.", "Accepted: .csv, .xlsx, .xls up to 50 MB in the default setup."],
  ["Understand the dataset", "ClearMetric profiles every column: type, role, missing and distinct values, examples, statistics, and a Data Quality Score with the formula behind it.", "Issues such as duplicates or unreadable dates are listed, not hidden."],
  ["Define business metrics", "Confirm which columns hold net revenue, profit, order IDs and dates. Verified metrics are created from your answers, and you can write your own formulas.", "“Which column represents your net revenue?”"],
  ["Ask analytical questions", "Ask in plain language or use the visual builder. Both produce the same structured plan, validated before anything runs.", "“Which five products generated the highest net revenue?”"],
  ["Inspect evidence", "Open the Inspect panel to see the dataset version, records included, filters, metric formula, method and the read-only query.", "Re-run any saved answer against the exact versions it used."],
  ["Discover patterns", "Run an insight scan to find period changes, the segments behind them, concentration, variability and unusual records.", "Each finding states its method and limitations."],
  ["Generate reports", "Combine an executive summary, KPIs, charts and findings into a report, then download it as a PDF with its methodology.", "Sections keep a snapshot so reports don’t change silently."],
];

export default function HowItWorks() {
  return (
    <div className="mx-auto max-w-4xl px-5 py-14">
      <h1 className="text-4xl font-semibold tracking-[-0.02em]">How it works</h1>
      <p className="mt-3 text-lg text-ink-2">Seven steps from a spreadsheet to a decision-ready brief.</p>
      <ol className="mt-12 space-y-0">
        {STEPS.map(([t, d, ex], i) => (
          <li key={t} className="relative grid grid-cols-[3rem_1fr] gap-4 pb-10">
            {i < STEPS.length - 1 && <span aria-hidden className="absolute left-[1.15rem] top-10 h-[calc(100%-2.5rem)] w-px bg-line-2" />}
            <span className="tnum flex size-9 items-center justify-center rounded-full border border-forest bg-surface text-sm font-semibold text-forest">{i + 1}</span>
            <div>
              <h2 className="text-xl font-semibold">{t}</h2>
              <p className="mt-1.5 leading-relaxed text-ink-2">{d}</p>
              <p className="mt-2 text-sm text-muted">{ex}</p>
            </div>
          </li>
        ))}
      </ol>
      <ButtonLink href="/signup" variant="primary">Start with step one</ButtonLink>
    </div>
  );
}

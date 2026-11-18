import type { Metadata } from "next";

export const metadata: Metadata = { title: "Features" };

const GROUPS: [string, string[]][] = [
  ["Import and data quality", ["CSV, XLSX and XLS upload with drag and drop and progress", "Delimiter, encoding and header detection", "Sheet selection for multi-sheet workbooks", "Type and role inference per column", "Data Quality Score with component breakdown", "Missing values, duplicates, invalid dates and numbers, constant and misclassified columns, skew and outlier notes", "Server-side paginated preview with sort, filter, search, column visibility and export"]],
  ["Preparation and versions", ["Rename columns and set business roles", "Exclude columns from analysis", "Convert text to dates or numbers", "Fill or drop missing values", "Remove duplicate rows", "Filter out invalid rows", "Calculated fields from a safe expression language", "Preview before applying; restore any earlier version"]],
  ["Semantic metrics", ["Confirm business terminology after import", "Standard verified metrics created from your confirmations", "Custom formulas with validation and readable explanations", "Versions, verification, duplication and archiving", "See which analyses used each metric version"]],
  ["Analysis", ["Totals, rankings, breakdowns and segment comparisons", "Trends by day, week, month, quarter or year", "Period comparisons: previous period, year over year or custom ranges", "Contribution and change decomposition", "Histograms and IQR or z-score outlier detection", "Multi-turn follow-ups with reference resolution", "Clarifying questions for ambiguous terms"]],
  ["Evidence", ["Inspect panel on every answer", "Dataset version, records in scope, filters and date range", "Metric formula and version, aggregation and grouping", "Methodology and read-only query text", "Reproduce any run against its original data and metric versions"]],
  ["Insights and reporting", ["Ten insight categories from statistical detectors", "Severity defined per detector", "Save, dismiss, annotate and follow up", "Report sections for text, KPIs, charts, tables, insights and summaries", "Executive summary with limitations and next investigations", "PDF, CSV and XLSX exports"]],
  ["Workspace", ["Owner, admin, analyst and viewer roles", "Invitations accepted by the invitee after sign-in", "Activity history with links to each resource", "Global search, notifications, currency and date settings", "Optional Claude provider with explicit opt-in"]],
];

export default function FeaturesPage() {
  return (
    <div className="mx-auto max-w-6xl px-5 py-14">
      <h1 className="text-4xl font-semibold tracking-[-0.02em]">Features</h1>
      <p className="mt-3 max-w-2xl text-lg text-ink-2">Everything listed here works in the current release. Planned work is not listed.</p>
      <div className="mt-12 columns-1 gap-10 md:columns-2">
        {GROUPS.map(([title, items]) => (
          <section key={title} className="mb-10 break-inside-avoid">
            <h2 className="border-b border-line pb-2 text-lg font-semibold">{title}</h2>
            <ul className="mt-3 space-y-2 text-sm text-ink-2">{items.map((x) => <li key={x} className="flex gap-2"><span className="text-forest" aria-hidden>✓</span>{x}</li>)}</ul>
          </section>
        ))}
      </div>
    </div>
  );
}

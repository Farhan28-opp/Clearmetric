import { BookOpenCheck, Database, FileText, Library, Lightbulb, MessageSquareText, ScanSearch } from "lucide-react";
import Link from "next/link";
import { ButtonLink } from "@/components/ui";
import { EvidenceCard } from "./evidence-card";

const FLOW = [
  ["Ask", "Type a question the way you'd ask a colleague."],
  ["Analyse", "ClearMetric turns it into a structured plan and runs it against your data."],
  ["Verify", "Every answer shows its metric, filters, records and the exact query."],
  ["Discover", "A scan of your data surfaces changes, concentrations and unusual records."],
  ["Decide", "Turn findings into an executive brief you can download and share."],
];

const CAPS = [
  { icon: Database, title: "Data Hub", text: "Upload CSV or Excel. ClearMetric reads the structure, detects types, scores data quality and keeps every change as a version you can restore." },
  { icon: Library, title: "Metric Library", text: "Define revenue, margin or order value once. Every question, chart and report uses the same verified definition." },
  { icon: MessageSquareText, title: "AI Analyst", text: "Ask follow-ups like “how much did their revenue contribute?” and get a new calculation, not a paraphrase of the last answer." },
  { icon: ScanSearch, title: "Explore", text: "Build an analysis without writing anything: choose a metric, dimension, filters and dates, then drill into any bar." },
  { icon: Lightbulb, title: "Insights Center", text: "Statistical checks find period changes, segment drivers, concentration risks, variability and outlier candidates." },
  { icon: FileText, title: "Report Studio", text: "Assemble KPIs, charts, findings and an executive summary into a PDF with its methodology and data source." },
];

const CASES = [
  ["Retail", "Which stores or regions are slipping this month, and which products moved the numbers?"],
  ["E-commerce", "How concentrated is revenue across customers and channels? Which orders look unusual?"],
  ["Sales operations", "How does this quarter compare with last quarter by rep, region or segment?"],
  ["Small businesses", "What did we sell, what did we earn, and what changed since last month?"],
];

const QUESTIONS = [
  "What is my total net revenue?", "Which five products generated the highest net revenue?", "Compare monthly revenue across all regions",
  "Which region contributed most to the decrease in profit?", "Which category has the highest profit margin?", "Are there unusual transactions?",
  "How are sales distributed across product categories?", "Which customers purchased the most?",
];

const FAQ = [
  ["Do I need an AI API key?", "No. The built-in analyst is a deterministic interpreter that runs entirely on the ClearMetric server and handles common business questions. An administrator can optionally connect Claude for broader language understanding; it is off unless a workspace owner turns it on."],
  ["Is my data sent to an AI provider?", "Not by default. With the local analyst nothing leaves the server. If Claude is enabled, it receives your column names, metric definitions and the previous question’s plan to interpret wording, plus aggregated results to write an explanation. Raw rows are never sent."],
  ["How do I know an answer is right?", "Each answer has an Inspect panel showing the dataset version, the number of records included, filters, the metric formula, the methodology and the read-only query that produced it. Any saved answer can be re-run against the exact data version it used."],
  ["What files can I upload?", "CSV, XLSX and XLS files up to 50 MB and one million rows in the default configuration. Workbooks with several sheets let you choose the sheet; macro-enabled workbooks are rejected."],
  ["Can it predict next month?", "Not yet. ClearMetric describes what happened and where changes came from. It does not produce forecasts, because a forecast needs a validated method and enough history to be trustworthy."],
];

export default function Home() {
  return (
    <>
      <section className="mx-auto grid max-w-6xl items-center gap-12 px-5 pb-16 pt-14 lg:grid-cols-[1fr_1.05fr] lg:pt-20">
        <div>
          <h1 className="text-[44px] font-semibold leading-[1.04] tracking-[-0.025em] sm:text-[56px]">
            Your business data has answers. Just ask.
          </h1>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-2">
            Turn complex business data into clear answers, meaningful insights and smarter decisions. ClearMetric shows the calculation behind every number, so you can trust what you act on.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <ButtonLink href="/signup" variant="primary" className="h-11 px-5 text-[15px]">Start free with demo data</ButtonLink>
            <ButtonLink href="/product" className="h-11 px-5 text-[15px]">Take the product tour</ButtonLink>
          </div>
          <p className="mt-5 text-sm text-muted">No AI key required. Your rows stay on the server.</p>
        </div>
        <EvidenceCard />
      </section>

      <section aria-labelledby="flow" className="border-y border-line bg-surface">
        <div className="mx-auto max-w-6xl px-5 py-12">
          <h2 id="flow" className="text-2xl font-semibold tracking-[-0.01em]">From question to decision, with the working shown</h2>
          <ol className="mt-8 grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-5">
            {FLOW.map(([t, d], i) => (
              <li key={t} className="bg-surface p-5">
                <span className="tnum text-sm text-forest">{i + 1}</span>
                <h3 className="mt-2 text-lg font-semibold">{t}</h3>
                <p className="mt-1 text-sm text-muted">{d}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section aria-labelledby="caps" className="mx-auto max-w-6xl px-5 py-16">
        <div className="max-w-2xl">
          <h2 id="caps" className="text-3xl font-semibold tracking-[-0.015em]">One workspace for the whole analysis</h2>
          <p className="mt-3 text-ink-2">Six connected parts share the same data, the same metric definitions and the same history.</p>
        </div>
        <div className="mt-10 grid gap-x-12 gap-y-8 md:grid-cols-2">
          {CAPS.map(({ icon: I, title, text }) => (
            <div key={title} className="flex gap-4 border-t border-line pt-6">
              <I className="mt-0.5 size-5 shrink-0 text-forest" aria-hidden />
              <div><h3 className="font-semibold">{title}</h3><p className="mt-1 text-sm leading-relaxed text-ink-2">{text}</p></div>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="evidence" className="bg-ink text-white">
        <div className="mx-auto grid max-w-6xl gap-12 px-5 py-16 lg:grid-cols-2">
          <div>
            <h2 id="evidence" className="text-3xl font-semibold tracking-[-0.015em]">An analyst that shows its working</h2>
            <p className="mt-4 leading-relaxed text-white/75">
              Language models are good at understanding questions and bad at arithmetic you can audit. ClearMetric splits the job: wording becomes a strict, validated analysis plan, and a deterministic engine computes the numbers. The model never invents a figure.
            </p>
            <ul className="mt-6 space-y-3 text-sm text-white/85">
              {["Plans use only columns and metrics that exist in your workspace", "Values are bound as parameters; generated SQL or Python is never executed",
                "Ambiguous terms like “revenue” trigger a question instead of a guess", "Saved answers re-run against the exact data and metric versions they used"].map((t) => (
                <li key={t} className="flex gap-3"><BookOpenCheck className="size-4 shrink-0 text-[#8fc2ab]" aria-hidden />{t}</li>
              ))}
            </ul>
          </div>
          <figure className="rounded-lg border border-white/15 bg-white/5 p-5 font-[450]">
            <figcaption className="text-sm text-white/60">Inspect analysis</figcaption>
            <dl className="mt-3 grid grid-cols-[9rem_1fr] gap-y-2.5 text-sm">
              {[["Question", "Which region contributed most to the decrease in profit?"], ["Metric", "Total Profit (verified, v1) = SUM(Profit)"],
                ["Comparison", "Oct 2026 vs Sep 2026 on Order Date"], ["Grouping", "Region"], ["Records", "Every order dated in either month"],
                ["Method", "Segment change ÷ total change"], ["Limitation", "Shows where the change happened, not why"]].map(([k, v]) => (
                <div key={k} className="contents"><dt className="text-white/55">{k}</dt><dd>{v}</dd></div>
              ))}
            </dl>
            <pre className="mt-4 overflow-x-auto rounded-md bg-black/30 p-3 text-xs leading-relaxed text-[#bfe0d0]">{`WITH scope AS (SELECT * FROM data),
p AS (SELECT *, CASE WHEN "order_date" >= ? ...
SELECT "region", _period, CAST(SUM("profit") AS DOUBLE) AS v
FROM p WHERE _period IS NOT NULL GROUP BY ALL`}</pre>
            <p className="mt-2 text-xs text-white/50">Illustration of the read-only query view in the Analyst.</p>
          </figure>
        </div>
      </section>

      <section aria-labelledby="cases" className="mx-auto max-w-6xl px-5 py-16">
        <h2 id="cases" className="text-3xl font-semibold tracking-[-0.015em]">Built for the questions businesses actually ask</h2>
        <div className="mt-8 grid gap-6 md:grid-cols-4">
          {CASES.map(([t, q]) => (
            <div key={t}>
              <h3 className="font-semibold">{t}</h3>
              <p className="mt-2 font-serif text-[17px] leading-snug text-ink-2">“{q}”</p>
            </div>
          ))}
        </div>
        <div className="mt-12 rounded-lg border border-line bg-surface p-6">
          <h3 className="font-semibold">Questions you can ask on day one</h3>
          <ul className="mt-4 flex flex-wrap gap-2">
            {QUESTIONS.map((q) => <li key={q} className="rounded-full border border-line-2 px-3 py-1.5 text-sm text-ink-2">{q}</li>)}
          </ul>
        </div>
      </section>

      <section aria-labelledby="trust" className="border-y border-line bg-surface">
        <div className="mx-auto grid max-w-6xl gap-10 px-5 py-14 md:grid-cols-[1fr_2fr]">
          <div>
            <h2 id="trust" className="text-2xl font-semibold">Your data, under your control</h2>
            <Link href="/trust" className="mt-3 inline-block text-sm text-forest underline underline-offset-4">Read how data is stored and processed</Link>
          </div>
          <dl className="grid gap-6 sm:grid-cols-2">
            {[["Stored on your server", "Uploads are converted to Parquet files outside any public folder and referenced by generated keys."],
              ["Private by workspace", "Every request checks workspace membership and role. Other workspaces cannot see your datasets."],
              ["External AI is opt-in", "Off by default. When enabled, only schema and aggregates are shared, never raw rows."],
              ["Delete means delete", "Deleting a dataset removes its stored files. Deleting your account removes the workspaces you own."]].map(([k, v]) => (
              <div key={k}><dt className="font-medium">{k}</dt><dd className="mt-1 text-sm text-muted">{v}</dd></div>
            ))}
          </dl>
        </div>
      </section>

      <section aria-labelledby="faq" className="mx-auto max-w-3xl px-5 py-16">
        <h2 id="faq" className="text-3xl font-semibold tracking-[-0.015em]">Questions</h2>
        <div className="mt-6 divide-y divide-line border-y border-line">
          {FAQ.map(([q, a]) => (
            <details key={q} className="group py-4">
              <summary className="cursor-pointer list-none font-medium marker:hidden">
                <span className="flex items-center justify-between gap-4">{q}<span className="text-muted transition-transform group-open:rotate-45" aria-hidden>+</span></span>
              </summary>
              <p className="mt-2 text-sm leading-relaxed text-ink-2">{a}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="mx-auto mb-16 max-w-6xl px-5">
        <div className="flex flex-col items-start justify-between gap-6 rounded-xl bg-forest px-8 py-10 text-white md:flex-row md:items-center">
          <div>
            <h2 className="text-2xl font-semibold">See it on real-looking data in two minutes</h2>
            <p className="mt-1 text-white/80">Create an account, load the synthetic retail dataset and ask your first question.</p>
          </div>
          <ButtonLink href="/signup" className="h-11 border-white bg-white px-5 text-forest hover:bg-forest-wash">Create your workspace</ButtonLink>
        </div>
      </section>
    </>
  );
}

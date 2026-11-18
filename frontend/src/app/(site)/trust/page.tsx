import type { Metadata } from "next";

export const metadata: Metadata = { title: "Trust and privacy" };

const SECTIONS: [string, string[]][] = [
  ["Where uploaded data is stored", [
    "Your original file is saved on the ClearMetric server under a randomly generated name, outside any publicly served folder. The name you uploaded is kept only as a label.",
    "An analytical copy is stored as a Parquet file per dataset version. Workspace, dataset, metric and report records live in the application database (SQLite for local installations, PostgreSQL for multi-user deployments).",
  ]],
  ["How data is processed", [
    "Calculations run in DuckDB inside the ClearMetric server. Each query uses a fresh in-memory connection that can see only the one dataset being analysed, with file access disabled and a time limit.",
    "Queries are built by ClearMetric from validated analysis plans. Filter values are passed as parameters. Generated SQL or Python from a language model, and code typed by users, is never executed.",
    "Spreadsheet macros are never run; macro-enabled workbooks are rejected. Exported spreadsheets neutralise cells that could be interpreted as formulas.",
  ]],
  ["Whether external AI is enabled", [
    "By default, no. The built-in analyst runs entirely on the server and makes no external requests.",
    "An administrator can configure Anthropic’s Claude on the server. Even then, it is used only in workspaces where an owner or admin has switched on External AI in Settings. The active mode is shown in the Analyst.",
  ]],
  ["What is sent to third-party providers", [
    "When External AI is on: the question, column names and types, column roles, distinct-value counts, metric names and formulas, the latest date in the data, and the previous question’s plan. After a calculation, the aggregated result table (at most 30 rows) may be sent to write a plain-language explanation.",
    "Raw records and lists of values from your columns are never sent. An explanation is discarded if it contains a number that is not in the computed result.",
    "The contact form stores messages in the database. No email provider is configured in this release, so nothing is emailed.",
  ]],
  ["How you delete your information", [
    "Deleting a dataset removes its versions, its stored Parquet files and the original upload.",
    "Deleting a workspace (owner only) removes all of its datasets, files, metrics, investigations, insights and reports.",
    "Deleting your account (Settings, Security) removes your user record and every workspace you own, and removes you from workspaces owned by others.",
  ]],
  ["Authentication and access control", [
    "Passwords are hashed with bcrypt. Sessions use a random token in an HttpOnly, SameSite cookie; only a hash of the token is stored. Changing your password signs out your other sessions.",
    "State-changing requests require a custom header that other websites cannot send, which blocks cross-site request forgery.",
    "Every workspace request checks membership. Roles: owners and admins manage settings and members; analysts can upload, analyse and report; viewers can read.",
  ]],
];

export default function TrustPage() {
  return (
    <div className="mx-auto max-w-3xl px-5 py-14">
      <h1 className="text-4xl font-semibold tracking-[-0.02em]">Trust and privacy</h1>
      <p className="mt-3 text-lg text-ink-2">What this release of ClearMetric actually does with your data. If a control isn’t described here, don’t assume it exists.</p>
      <div className="mt-10 space-y-10">
        {SECTIONS.map(([h, ps]) => (
          <section key={h} aria-label={h}>
            <h2 className="text-xl font-semibold">{h}</h2>
            <div className="mt-3 space-y-3 font-serif text-[17px] leading-relaxed text-ink-2">{ps.map((p) => <p key={p}>{p}</p>)}</div>
          </section>
        ))}
      </div>
    </div>
  );
}

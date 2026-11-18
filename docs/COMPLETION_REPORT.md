# ClearMetric 2.0: completion report

Status as of 18 Nov 2026. Everything below was run in the build environment: Python 3.13, Node 22, Chrome. Results marked "verified" were executed, not inferred.

## 1. Final architecture

```
Browser ── Next.js 16 (App Router, client components, TanStack Query)
             │  /api/* rewrite (same origin, HttpOnly session cookie)
             ▼
FastAPI ── deps: session auth · CSRF header guard · workspace membership/role
   │
   ├─ Ingestion ─► type inference ─► profiling + Data Quality Score ─► Parquet version (immutable)
   ├─ Semantic layer: business-term confirmation ─► MetricDefinition / MetricVersion (restricted formula AST)
   ├─ Interpreters (local deterministic | optional Claude, structured outputs) ─► AnalysisPlan (strict schema)
   ├─ Plan validator ─► intent compilers ─► parameterised SQL ─► DuckDB (isolated, read-only, timeout)
   ├─ Result validation ─► provenance ─► AnalysisRun (stored)  ─► narrator (template; Claude explanation optional, grounding-checked)
   ├─ Insight detectors (use the same engine) ─► Insight
   └─ Report Studio: sections store snapshots ─► PDF (ReportLab) / CSV / XLSX
SQLAlchemy ─► SQLite (default) or PostgreSQL · files in storage/ (originals, parquet)
```

No component executes model output or user text as code. The `AnalysisPlan` is the only contract between language and computation.

## 2. Pages and routes

Public: `/`, `/product`, `/features`, `/solutions`, `/how-it-works`, `/trust`, `/contact`, `/login`, `/signup`, `/forgot-password`, `/reset-password`, plus a 404 page.

Workspace: `/app` (redirect), `/app/onboarding`, `/app/overview`, `/app/data`, `/app/data/[datasetId]` (tabs: overview, preview, schema, quality, statistics, prepare, business terms, versions, related), `/app/metrics`, `/app/analyst`, `/app/explore` (builder, natural language, saved visualisations), `/app/insights`, `/app/reports`, `/app/reports/[reportId]`, `/app/activity`, `/app/settings` (profile, workspace, business and formats, members, security, data privacy).

API: 103 operations under `/api` (OpenAPI at `/api/docs`). The areas are auth, account, workspaces, members and invitations, datasets, upload, preview, export, transformations, versions, business terms, relationships, metrics, analysis (validate/compute/run/interpret/reproduce/export), overview, conversations and messages, visualisations, insights, reports and sections, activity, notifications, search, contact and system status.

## 3. Important backend modules

| Module | Responsibility |
|---|---|
| `services/dataset/ingestion.py` | Extension allow-list and signature checks, zip-bomb and macro guards, CSV dialect/encoding/header detection, sheet listing, type inference |
| `services/dataset/profiling.py` | Column statistics, semantic roles, business-meaning suggestions, Data Quality Score |
| `services/dataset/service.py`, `transform.py`, `relationships.py` | Versions, server-side preview, previewable transformations, restore, explicit joins |
| `services/semantic/formula.py`, `metrics.py`, `terms.py` | Formula grammar and compiler, metric versioning and verification, term confirmation |
| `services/analytics/plan.py`, `filters.py`, `engine.py` | Plan schema, type-safe filters, validation, 11 intent compilers, provenance, result cache |
| `services/execution/engine.py` | Isolated DuckDB execution |
| `services/ai/*` | Context builder, local interpreter, Claude provider, narrator, conversation manager |
| `services/insights/detector.py` | Nine detectors plus data-quality findings |
| `services/reports/summary.py`, `pdf.py` | Executive summary and PDF rendering |

## 4. Database schema

`users`, `sessions` (hashed tokens), `password_resets`, `workspaces` (currency, timezone, fiscal year start, date format, external-AI opt-in, insight thresholds, onboarding state), `workspace_memberships` (owner/admin/analyst/viewer), `workspace_invitations`, `activity_events`, `contact_messages`, `datasets`, `dataset_versions` (Parquet key, profile JSON), `dataset_columns` (type, role, meaning, confirmation, exclusion, stats), `dataset_transformations`, `data_relationships`, `metric_definitions`, `metric_versions`, `conversations`, `messages`, `analysis_runs` (plan, SQL, params, dataset version, metric versions, result, timing), `saved_visualizations`, `insights`, `reports`, `report_sections` (plan + snapshot).

Every analytical result is linked to its user, workspace, dataset, dataset version, metric versions, plan and execution timestamp.

## 5. Analytical engine

Intents: aggregate, rank, breakdown, compare segments, contribution (with focus members and an "All other" group), trend (day to year, series capped with a note), period comparison (previous period, previous year or custom; partial periods flagged), change decomposition (share of total change for additive metrics, with an explanation when a metric is not additive), distribution (equal-width histogram or shares), outliers (IQR or z-score at record, group or time-grain level) and dataset description.

Safeguards:
- Identifiers come only from validated metadata.
- All values are bound parameters.
- Division uses `NULLIF`.
- Infinite results are rejected.
- Results are capped at 500 rows.
- Each query has a 15 s timeout.
- An LRU result cache keys on plan, dataset version and metric versions.

## 6. AI provider integration status

The Claude provider is implemented in `services/ai/anthropic_provider.py`:
- It uses `messages.create` with `output_config.format = json_schema`, a strict schema with `additionalProperties: false`, as in the current structured-outputs documentation.
- It runs only when a server key is configured and a workspace admin has opted in.
- It gets one correction round when the validator rejects a plan, and falls back to the local interpreter on any error or timeout.
- It records provider and model on each run.
- Its explanations are discarded if they contain numbers that are not in the result.

**It has been tested only with a mocked SDK client (4 tests). No live API call was made, because no key was available.**

## 7. Local fallback capabilities

The deterministic interpreter works without any key. It handles:
- totals, counts and averages
- top and bottom N
- breakdowns, including stacked breakdowns
- segment comparisons
- shares and contributions
- trends at any grain
- period comparisons: month over month, year over year and relative phrases anchored to the latest date
- change drivers
- distributions
- unusual records or days
- value filters ("in West", "for Electronics", "in 2025", "Q3 2025", "last 90 days")
- numeric conditions
- follow-up references ("their", "its", "the second-highest", "what about West?")
- clarification of ambiguous revenue, margin, dimension or date terms
- unknown concepts ("churn") and out-of-scope questions

It is labelled in the UI as a rule-based interpreter.

## 8. Implemented product features

All features listed in `/features` are implemented and connected to the backend, including:
- onboarding with persistent progress
- dataset management, preview, quality, statistics, preparation and versions
- relationships with match validation and materialised joins
- the Metric Library with versions, verification and usage
- AI Analyst investigations: save, rename, duplicate, delete, search, export, pin and notes
- the inspector with reproduce
- the Explore builder with natural-language mode, drill-down, chart switching, PNG/CSV/XLSX export and saved visualisations
- the Insights Center with evidence, affected records, follow-up, save, dismiss, note and add-to-report
- the Report Studio: create, edit, reorder, refresh, duplicate, delete, PDF/CSV/XLSX and print
- Activity, notifications, global search, roles and invitations, and security and privacy settings

## 9. Test results (executed)

- **Backend (pytest): 45 passed.**
  - 17 known-answer accuracy tests on a hand-computable dataset: totals, AOV, margin, top N, grouping, monthly totals, date-range comparison, decomposition summing to 100%, IQR bounds, contribution, filters, empty result, division by zero, cross-module metric consistency, invalid column, unsupported operation and query timeout.
  - The NL evaluation suite with 43 questions (35 single questions and 4 follow-up pairs). Status 39/39, intent 30/30, measure 29/29, columns 20/20, context 3/3, clarification 3/3, unsupported 4/4, plans valid 29/29.
  - 13 security tests: auth, CSRF, workspace isolation, viewer role, SQL injection, formula code injection, unsafe plans, upload validation, oversized upload, macro workbook, export formula injection and file deletion.
  - Ingestion, transformation, versioning, relationships and reports/PDF tests.
  - 4 Claude-provider tests with a mocked client.
- **Frontend unit tests (Vitest): 6 passed.** TypeScript: no errors. ESLint: 0 errors and 47 warnings (`no-explicit-any` on schemaless result JSON, and `set-state-in-effect` where forms sync from loaded data).
- **End-to-end (`e2e/jury_demo.py`, Playwright with Chrome): 13 of 13 steps passed.**
  - The public site and the contact form.
  - Signup, workspace creation in INR, demo data, profiling and term confirmation.
  - The four jury questions with chart, inspector and generated query.
  - A saved investigation reopened after navigation.
  - The Insights Center with evidence and affected records, and Explore drill-down.
  - The executive report with the PDF downloaded and checked.
  - Settings, activity and mobile navigation.
- **Production build:** `next build` succeeds for all 25 routes.

## 10. Known limitations

**Partially implemented**
- The fiscal-year start and date-format settings are stored and editable but not yet applied. Quarters and years are calendar-based, and dates display in a fixed format.
- Explore canvas cards and their notes last only for the browser session. Saved visualisations, investigations and reports persist.
- Relationships create a materialised joined dataset. Plans cannot query across two datasets directly.
- XLS (legacy Excel) import is implemented via xlrd but was not tested with a real .xls file. XLSX is tested.
- PostgreSQL works through SQLAlchemy but tests run on SQLite. The schema is created with `create_all`; there are no migrations (Alembic) yet.

**Not implemented**
- Email delivery: contact messages are stored, invitations appear in-app and reset links go to the server log.
- Forecasting, by design.
- Heatmap charts.
- Background processing for very large uploads: imports run within the request.
- SSO.
- A formal automated accessibility audit. Keyboard operation, labels, focus styles, live regions, skip links and table alternatives for charts are implemented and were spot-checked.

**Other limits**
- The local interpreter covers common phrasings, not open-ended language. Unsupported questions get an explicit message and suggestions.
- Insight thresholds use simple heuristics, documented per detector.

## 11. Security measures

- bcrypt password hashing and password-strength rules.
- Random session tokens; only their SHA-256 hash is stored. Cookies are HttpOnly and SameSite=Lax, with Secure configurable. Sessions expire and can be revoked, and other sessions are revoked on a password change.
- A CSRF header guard on every state-changing request.
- Workspace membership checks on every resource, returning 404 for other workspaces, plus role enforcement.
- Uploads: extension allow-list, signature checks, size and row limits, zip-bomb and macro rejection, generated storage keys with a path-traversal guard, and cleanup of stored files on delete.
- Strict plan schema (extra fields forbidden), validated identifiers, bound parameters, a restricted formula grammar with no `eval`, and isolated DuckDB with external access disabled, configuration locked and a timeout.
- Formula-injection neutralisation in CSV/XLSX exports.
- No API keys in the frontend, opt-in external AI that never sends raw rows, and a grounding check on AI text.
- Security headers: `X-Content-Type-Options`, `X-Frame-Options` and `Referrer-Policy`.

## 12–15. Startup, database and environment

See `README.md`. In short: `uvicorn app.main:app --port 8000` in `backend/`, then `npm run dev` (or `npm run build && npm start`) in `frontend/`. SQLite is created automatically, or set `CM_DATABASE_URL` for PostgreSQL. All settings are documented in `backend/.env.example`.

## 16. Reproducing the jury demonstration

Follow "Jury demonstration" in `README.md`, or run `python e2e/jury_demo.py http://localhost:3000` against running servers. It performs every step and saves screenshots and the downloaded PDF.

Synthetic data facts the demo relies on (seed 47, 1,464 rows):
- Net Revenue $307.9K in total.
- The top product is Air Fryer, at 12.2% of the total.
- The top 5 products make up 54.4% of net revenue.
- Total Profit fell from 8,915.30 in Sep 2026 to 5,959.00 in Oct 2026 (−33.2%). West accounts for −1,806.25 of that, or 61% of the decline.

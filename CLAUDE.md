# ClearMetric: working notes

## Commands
- Backend: `cd backend && uvicorn app.main:app --port 8000` · tests: `python -m pytest` (run from `backend/`, `pytest.ini` sets `pythonpath=.`)
- Frontend: `cd frontend && npm run dev` · build: `npm run build` · unit tests: `npm test` · types: `npm run typecheck` · lint: `npx eslint src`
- E2E: `python e2e/jury_demo.py http://localhost:3000 [--chrome /usr/bin/google-chrome]` with both servers running
- Regenerate sample CSV: `cd backend && PYTHONPATH=. python -c "from app.services.dataset.demo import generate_csv; open('sample_data/clearmetric_demo_retail.csv','wb').write(generate_csv())"`

## Architecture rules (do not break)
- Language never reaches the database. Interpreters (local or Claude) and the visual builder only produce an `AnalysisPlan` (`services/analytics/plan.py`, `extra="forbid"`). `engine.validate_plan` checks workspace ownership, dataset version, columns, metrics, types and limits before compiling.
- SQL is generated only in `engine.py`, `filters.py`, `formula.py` and a few fixed preview/export queries. Identifiers come from validated metadata and go through `quote_ident`; every value is a bound `?` parameter.
- DuckDB runs in `services/execution/engine.py`: a fresh in-memory connection per query that sees one registered Arrow table named `data`, with external access disabled, configuration locked and a timer interrupt.
- Metric formulas use the restricted grammar in `formula.py`. Never `eval`/`exec` user or model text. Calculated fields evaluate the parsed AST with pandas.
- Datasets are immutable versions. Transformations create new `DatasetVersion`s, and metadata-only changes reuse the Parquet key. Restore creates a new version.
- Metric edits create a new `MetricVersion`. A formula change resets verification. Runs store `metric_version_ids` and `dataset_version_id`; `/analysis/runs/{id}/reproduce` pins both.
- Report sections store snapshots and change only via explicit refresh.
- Narratives are template-generated from computed results (`services/ai/narrator.py`). A Claude explanation is discarded if `anthropic_provider.grounded()` finds a number that is not in the result.
- Insights come from detectors in `services/insights/detector.py` that run engine plans. A detector that cannot apply is skipped, never faked.

## Conventions
- API: `/api/workspaces/{workspace_id}/…`, with `workspace_ctx` / `editor_ctx` / `admin_ctx` dependencies for role checks. Errors use `{"error": {code, message, details}}`.
- State-changing requests need the header `X-CM-Client: web` (CSRF guard). The frontend `lib/api.ts` adds it.
- Frontend data fetching: `useWsQuery([...key], "/path")` scopes keys and paths to the current workspace. Invalidate with `qc.invalidateQueries({ queryKey: [wid, ...] })`.
- Next.js 16: pages that read `useSearchParams` are wrapped in `<Suspense>`. There is no middleware/proxy; `/api` is proxied via `rewrites` in `next.config.ts`.
- Design tokens live in `frontend/src/app/globals.css` (`@theme`): paper/ink/forest, with rust only for negative values and brass for warnings. Use `cx()` from `components/ui.tsx` (clsx + tailwind-merge).
- Copy: sentence case, plain verbs, no all-caps labels. Never claim delivery (email) or capability that is not configured.

## Decisions
- Relative dates ("this month") are anchored to the latest date in the dataset, and the answer says so.
- "revenue"/"sales" is ambiguous when several revenue metrics exist. The analyst asks, then remembers the choice for the rest of that investigation.
- Demo data: `services/dataset/demo.py`, seed 47. It has a West-driven profit decline in Oct 2026, a variable Smart Watch, wholesale outliers and small data-quality defects.

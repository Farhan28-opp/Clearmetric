# ClearMetric: your AI business analyst

ClearMetric lets a small business upload CSV or Excel data, ask questions in plain language, and get answers it can verify: each answer shows the metric, filters, records and the query behind it. A question becomes a strict analysis plan. The plan is validated against the workspace and compiled to parameterised SQL, then executed by DuckDB in an isolated connection. No number comes from a language model.

```
frontend/   Next.js 16 (App Router) · TypeScript · Tailwind CSS v4 · TanStack Query · React Hook Form + Zod · Recharts
backend/    FastAPI · Pydantic v2 · SQLAlchemy 2 · DuckDB · pandas · PyArrow/Parquet · openpyxl/xlrd · ReportLab
e2e/        Playwright walk-through of the full jury demonstration
docs/       Completion report and screenshots
```

## Quick start

Requirements: Python 3.11+ (tested on 3.13), Node.js 20+ (tested on 22).

```bash
# 1. Backend (http://127.0.0.1:8000, API docs at /api/docs)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. Frontend (http://localhost:3000), in a second terminal
cd frontend
npm install
npm run dev            # or: npm run build && npm start
```

The frontend proxies `/api/*` to the backend (`BACKEND_URL`, default `http://127.0.0.1:8000`), so the browser only ever talks to one origin. This keeps the HttpOnly session cookie first-party, and no secret ever reaches the client.

### Database

SQLite is created automatically at `backend/storage/clearmetric.db` on first start. Uploaded files and Parquet versions are stored in `backend/storage/originals` and `backend/storage/parquet`.

For a multi-user deployment, point `CM_DATABASE_URL` at PostgreSQL (the `psycopg` driver is in `requirements.txt`). Tables are created at startup:

```bash
export CM_DATABASE_URL="postgresql+psycopg://clearmetric:secret@localhost:5432/clearmetric"
```

### Environment variables

All backend settings use the `CM_` prefix and can live in `backend/.env` (see `backend/.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `CM_DATABASE_URL` | SQLite in `backend/storage` | SQLAlchemy URL |
| `CM_STORAGE_DIR` | `backend/storage` | Uploaded originals, Parquet versions |
| `CM_ENVIRONMENT` | `development` | In development the password-reset link is also returned to the UI |
| `CM_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `CM_MAX_UPLOAD_MB` / `CM_MAX_ROWS` | `50` / `1000000` | Upload limits |
| `CM_QUERY_TIMEOUT_SECONDS` | `15` | DuckDB wall-clock limit per query |
| `CM_AI_PROVIDER` | `local` | `anthropic` enables the optional Claude provider |
| `CM_ANTHROPIC_API_KEY` | – | Server-side only |
| `CM_ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Any current Claude model id |
| `BACKEND_URL` (frontend) | `http://127.0.0.1:8000` | Where Next.js proxies `/api` |

Claude is used only when the provider and key are configured **and** a workspace owner or admin turns on External AI in Settings → Data privacy. Without it, the deterministic local interpreter answers. The UI always shows which mode is active.

## Tests

```bash
cd backend && python -m pytest                 # 44 tests: accuracy, NL evaluation, security, ingestion, reports
cd frontend && npm test                         # Vitest unit tests
cd frontend && npm run typecheck && npx eslint src
# End-to-end (both servers running):
pip install playwright && playwright install chromium     # or pass --chrome /path/to/chrome
python e2e/jury_demo.py http://localhost:3000 --shots e2e/screenshots
```

## Jury demonstration

1. Open http://localhost:3000. Browse Product, Features, Solutions, How it works and Trust. The hero card is computed live from the synthetic dataset.
2. **Start free with demo data**: create an account, then a workspace. Choose INR or another currency.
3. Choose **Load demo data**. The 1,464-row synthetic retail file is generated, then imported through the normal ingestion pipeline. Review the detected columns and the Data Quality Score.
4. Confirm the business terms (net revenue, profit and so on). Nine verified metrics are created. The first overview runs an insight scan.
5. In **AI Analyst**, ask:
   - *Which five products generated the highest net revenue?* Then open **Show calculation** to see the plan, records and query.
   - *How much did their revenue contribute to total revenue?* "Their" resolves to the five products.
   - *Compare monthly revenue across all regions.*
   - *Which region contributed most to the decrease in profit?* The answer is West, with about 61% of the October decline, plus the stated limitation that this shows where, not why.
6. Choose **Save**, navigate away, and reopen the investigation from Overview → Saved investigations.
7. Open the **Insights Center**: regional and product drivers, concentration, variable products, outlier transactions, trend, seasonality, margins, correlation and data quality, each with its method and the records it affects.
8. Open **Reports → New report → Executive summary** and include the investigation. Choose **PDF**.

## Repository map

- `backend/app/services/analytics/engine.py`: plan validation, intent compilers, provenance
- `backend/app/services/analytics/plan.py`: the strict `AnalysisPlan` schema
- `backend/app/services/semantic/formula.py`: restricted metric formula language
- `backend/app/services/ai/`: context builder, local interpreter, Claude provider, narrator, conversation manager
- `backend/app/services/insights/detector.py`: statistical insight detectors
- `backend/app/services/reports/`: executive summary and PDF rendering
- `frontend/src/app/(site)`: public site; `(auth)`: sign-in flows; `app/`: authenticated workspace
- `frontend/src/components/analysis/`: chart renderer, result view, inspector

See `docs/COMPLETION_REPORT.md` for the architecture, data model, test results and known limitations.

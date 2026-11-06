# AI Data Analyst Agent — Specification (condensed)

Source: the build prompt dated 2026-10-23. NOTE: the prompt arrived truncated at Phase 5
("Charts"). Everything from Phase 5 onward (chart catalog details, Phases 6-8, the
"Environment variables" section) was not received and is not specified here.

## Stack
- Frontend: React 19, Vite, JS, React Router, Axios, Recharts, Lucide, Framer Motion,
  three + R3F + drei (lazy, optional, `VITE_ENABLE_3D`), CodeMirror SQL editor, sql-formatter,
  Vitest + RTL, plain CSS with tokens (no Tailwind), self-hosted Inter (@fontsource).
- Backend: Python 3.11+ (dev on 3.14), FastAPI, Uvicorn, Pydantic v2 + pydantic-settings,
  Pandas, NumPy, SciPy, pyarrow, DuckDB (read-only SQL, worker process), sqlglot, openpyxl,
  xlrd, httpx, argon2-cffi, slowapi, pytest.
- DB: MongoDB via PyMongo `AsyncMongoClient` (not Motor). Local or Atlas via `MONGODB_URI`.
- AI: Groq and xAI Grok, both OpenAI-compatible chat APIs, called only from the backend with httpx.
- Ports: backend 8000, frontend 5173; Vite proxies `/api` → `http://localhost:8000`.
  CORS allow-list from env for production.

## Security rules
- Argon2id password hashes, never returned.
- Sessions (changed 2026-10-25 from access JWT + refresh token + CSRF cookie): one HttpOnly SameSite=Lax
  cookie `sid` (Secure in production) holding a random ID; SHA-256 hash stored in `sessions` with idle
  (7 days, extended while used) and absolute (30 days) expiry; new ID at every sign-in; ended on logout,
  password change (other sessions) and password reset (all sessions).
- Cross-site request protection without a token: `X-Requested-With` header required on state-changing
  requests, and `Origin` / `Sec-Fetch-Site` must match the app when present.
- Rate limits on signin (per IP and per email) and signup. Generic "Invalid email or password".
- Every resource query filters by `user_id`; foreign resources return 404.
- Password reset: 32-byte token, SHA-256 stored, 30 min, single use, ends all sessions.
  Dev without SMTP logs link to console only.
- Uploads: only .csv/.xlsx/.xls, extension + content validated, size cap, row/col caps,
  UUID storage names, no pickle, raw file immutable (SHA-256 recorded).
- SQL: sqlglot single SELECT, table allow-list, function deny-list, DuckDB locked settings,
  separate worker process with timeout, row cap.
- Export tokens `pbi_...`: shown once, SHA-256 stored, feed endpoint only.
- One error shape: `{"error": {"code", "message", "details"}}`; request ID in logs.

## Routes (Phases 0-4d)
- `GET /api/health`
- Auth: `POST /api/auth/{signup,signin,logout,forgot-password,reset-password,change-password}`,
  `GET|PATCH|DELETE /api/auth/me`
- `GET /api/dashboard/summary`, `GET /api/ai/providers`
- Datasets: `POST /api/datasets/upload`, `GET /api/datasets?q=`, `GET|DELETE /api/datasets/{id}`,
  `GET /api/datasets/{id}/preview`, `/versions`, `PUT /active-version`, `/cleaning-report`,
  `POST /clean`, `GET /cleaning-suggestions`, `POST /cleaning-suggestions/apply`, `GET /download`
- Analytics: `POST /api/analytics/{id}/{profile,query,chart,insights}`, `GET /api/analytics/{id}/insights`
- SQL: `GET /api/sql/{id}/schema`, `POST /api/sql/{id}/{validate,run}`, `GET|POST /api/sql/saved`,
  `DELETE /api/sql/saved/{id}`
- Power BI / Excel: `GET /api/powerbi/{id}/package`, `GET /api/exports/{id}/excel`,
  `POST|GET /api/export-tokens`, `DELETE /api/export-tokens/{id}`, `GET /api/feed/{id}.csv|.json`
- History: `GET /api/analyses`

## Routes added after Phase 4d
- Dashboard and charts: `POST /api/analytics/{id}/{dashboard,chart-suggestions,pivot,pivot/export}`,
  `PUT|DELETE /api/analytics/{id}/goals`, `POST|DELETE /api/analytics/{id}/dashboard/tiles`
- Ask and reports: `POST /api/ask`, `POST|GET|DELETE /api/reports`
- Sharing: `POST|GET /api/analytics/{id}/share`, `DELETE /api/share-links/{id}`, `GET /api/public/share/{token}`
- Datasets: `POST /api/datasets/import-url`, `POST /api/datasets/{id}/refresh`;
  `GET /api/datasets/{id}/download?version=&format=zip|xlsx|csv|csv_excel|json&columns=`

## Collections
users, datasets, dataset_versions, analyses, reports, conversations, messages,
password_resets (TTL), login_attempts (TTL), sessions (TTL on absolute expiry), saved_queries, dashboards,
export_tokens (unique token_hash). Indexes as listed in the prompt; created at startup in
`app/db/mongo.py`.

## Accuracy principles (summary)
Backend computes every number from the active version; nulls skipped and counted; currency
summed as Decimal and stored as Parquet DECIMAL; reconciliation checks before returning;
dual-engine (Pandas vs DuckDB) cross-check of headline metrics; every result carries
dataset version, filters, formula, rows used/skipped, engine. AI text is number-checked.

## Patterns adopted from reference products
| Pattern | Source | Where |
|---|---|---|
| Data profiling strip (valid/error/empty bar + mini distribution + column profile panel) | Power Query data profiling | `frontend/src/components/ProfilingStrip.jsx`, `ColumnProfilePanel.jsx`, the dataset page (the separate Data Explorer page was removed later) |
| Near-duplicate category clustering | OpenRefine | `backend/app/cleaning/suggestions.py` (Tier 2 near-duplicate mapping) |
| Show the code (query plan / SQL behind every result) | Julius, Powerdrill | `CalcDrawer` component on analytics results and insights |
| SQL Lab separation (SQL runs in its own worker) | Apache Superset | `backend/app/services/jobs.py` (`sql_job`) and `backend/app/api/sql.py` |
| Automated insights flagging drivers and anomalies | Powerdrill, ThoughtSpot | `backend/app/analytics/insights/` |
| Saved queries with charts | Redash | SQL Workbench saved queries |
| Auto dashboard | Metabase X-ray, Polymer | Built outside the original phases: `backend/app/analytics/dashboard.py`, `frontend/src/pages/app/Dashboard.jsx` |
| Pivot table with subtotals and show-values-as | Excel PivotTable | `backend/app/analytics/pivot.py`, `frontend/src/pages/app/Pivot.jsx` |

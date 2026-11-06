# AI Data Analyst Agent

A full-stack web app that uploads CSV/Excel files about any subject, cleans them transparently into
versioned datasets, and analyzes them with tested, verifiable calculations: profiles, no-code query
plans, pivot tables, a read-only SQL Workbench and automated insights. Every upload (a file, or a
Google Sheets / public file link that can be refreshed) opens as an automatic, filterable dashboard (KPIs with
period change and targets, trend with forecast, breakdowns, summary table). Ask questions in plain words,
get suggested charts, write reports, share read-only links, download the cleaned data (share pack, Excel, CSV,
JSON) and export tailored Excel workbooks or a refreshable Power BI feed. AI (Groq or xAI Grok) is optional:
it helps read a question and writes or explains text; it never produces the numbers.

> Portfolio project. Not affiliated with any of the products mentioned below.

## Status

See [docs/PROGRESS.md](docs/PROGRESS.md) for what is built and verified. The build prompt arrived
truncated at Phase 5 (charts). The dashboard, auto charts, reports and export builder were added on
request afterwards; Chart Studio and AI chat are **not built**. Reports print to PDF from the browser.

## Stack

- **Frontend:** React 19, Vite, React Router, Axios, Recharts, three.js + React Three Fiber
  (lazy, data-driven 3D views with static fallbacks), Framer Motion (dialogs, toasts and the sign-in page), CodeMirror, Vitest. Plain CSS with design tokens (light, dark, system).
- **Backend:** Python 3.11+ (developed on 3.14), FastAPI, Pydantic v2, Pandas, NumPy, SciPy, pyarrow,
  DuckDB, sqlglot, openpyxl/xlrd, PyMongo async (`AsyncMongoClient`), argon2-cffi, slowapi.
- **Database:** MongoDB (local or Atlas via `MONGODB_URI`).

## Run locally (Windows, macOS, Linux)

Prerequisites: Python 3.11+, Node.js 20+, MongoDB running locally (or an Atlas URI).

```bash
# Backend (port 8000)
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # then add your MongoDB URI (and an AI key if you want AI features)
uvicorn app.main:app --port 8000

# Frontend (port 5173, proxies /api to the backend)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Every environment variable is documented in `backend/.env.example` and
`frontend/.env.example`. Only `.env.example` files are committed.

### Tests

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest     # needs MongoDB on localhost
cd frontend && npm test
```

Backend tests use a separate database (`ai_data_analyst_test`) and a temporary storage folder.

## Accuracy

All numbers are computed by the backend from the active cleaned dataset version. Money is stored as
exact `DECIMAL` and summed in integer minor units; results report rows used and skipped, pass
reconciliation checks, and are cross-checked by a second engine (DuckDB) before they are returned.
Forecasts and statistical tests are model estimates, labelled as such, and are not part of that check.
Definitions and thresholds: [docs/METRICS.md](docs/METRICS.md).

## Pivot tables, link import and downloads

- **Pivot** (`/app/pivot`): one to three nested row fields with subtotals, a column field, up to six values
  (sum, average, median, minimum, maximum, count, distinct count), date grouping, filters, sorting, Top N and
  an Excel export. It covers every row of the dataset. Each level (cells, subtotals, totals) is a separate
  group-by recomputed in DuckDB, so totals are right for averages too. Only the *output* is bounded (500
  columns, 600,000 cells).
- **Import from a link**: a Google Sheet shared as "anyone with the link" (the open tab, exported as CSV) or a
  public `.csv` / `.xlsx` / `.xls` URL. Only https; every hop, including redirects, must resolve to a public IP
  address. The address is looked up once to check it and again when downloading, so a hostile DNS server could in
  principle still point the download somewhere private (DNS rebinding). Close that gap (pin the checked
  address) before exposing the app publicly. *Refresh* re-downloads the link and cleans changed data into a new version.
- **Clean data downloads** (`/app/downloads`): share pack (zip with clean CSV, data dictionary, cleaning report
  and a README with a SHA-256 checksum), Excel workbook, CSV, Excel-friendly CSV (UTF-8 BOM) and JSON, with
  optional column selection. Columns whose names look like personal data are flagged; the check looks at names only.

## Power BI and Excel (scope)

Power BI Desktop and the Power BI service are separate Microsoft products. This app **does not embed
Power BI and cannot create `.pbix` files**. It prepares data for Power BI:

- a downloadable package (`data.csv`, `data.parquet`, data dictionary, a Power Query M script that
  applies the column types, suggested DAX measures for the columns that exist, and instructions);
- a refreshable CSV/JSON feed protected by read-only export tokens (`pbi_...`, shown once, stored as
  SHA-256, revocable, expiring). Power BI Desktop's Web connector sends the token as an
  `Authorization: Bearer` header under *Advanced* options. Tokens in the URL are off by default
  (`EXPORT_TOKEN_IN_URL=false`) and are redacted from logs when enabled.

**Not tested in Power BI.** The package and feed were verified by automated tests and HTTP requests,
not inside Power BI Desktop. Power BI Desktop can refresh from `http://localhost:8000`; scheduled
refresh in the Power BI service needs a publicly reachable HTTPS URL (and possibly a gateway), which
was not tested.

The Excel export (`openpyxl`) writes typed cells (numbers, dates, currency formats), a data
dictionary, the cleaning report and, optionally, native Excel charts whose series point at an
`Aggregates` sheet holding the backend-computed values. Text cells starting with `=`, `+`, `-` or
`@` are written as text, never as formulas; numeric and date cells are never altered.

## Security

Deployment checklist, rate limits, security headers and the automated checks: see [docs/SECURITY.md](docs/SECURITY.md).
In production the backend refuses to start with unsafe settings (wildcard CORS, non-HTTPS URLs, no `ALLOWED_HOSTS`,
a database without a login or, when remote, without TLS) and lists what to fix.

- **Accounts:** Argon2id password hashes. Signing in sets exactly one cookie, `sid`: a random 32-byte
  session ID (no user data, not a JWT), HttpOnly, SameSite=Lax, Secure in production. The server stores
  only its SHA-256 hash in the `sessions` collection, with an idle expiry (7 days, extended while in use)
  and an absolute expiry (30 days). Every sign-in creates a new ID; logout ends the session on the server;
  a password change or reset ends every session of that user (the browser that changed it gets a new one).
  No token is ever returned in a response body, stored in browser storage or put in a URL.
- **Cross-site requests:** state-changing requests must carry the `X-Requested-With` header that the
  app's API client always sends (another site cannot add it without a CORS preflight, which only the
  configured origins pass), and `Origin` / `Sec-Fetch-Site`, when the browser sends them, must point to
  this app. There is no CSRF token cookie. Rate limits on sign-in
  (per IP and per email) and sign-up. Password reset tokens are random, stored hashed, single-use and
  expire after 30 minutes. Reset emails are only sent when SMTP is configured; without it, the reset page
  says so and, in development, the link is printed in the backend console.
- **Email verification:** the `email_verified` field is stored (default false) but no verification
  flow is built.
- **Isolation:** every query filters by the signed-in user's ID; another user's resource returns 404.
- **Uploads:** only `.csv`, `.xlsx`, `.xls`; extension and content are both checked; macro-enabled and
  password-protected workbooks are refused; size, row, column and zip-expansion limits apply. Files
  are stored under generated names outside any static route, and the original is never modified.
- **SQL Workbench — read this.** Executing user-supplied SQL is a code-execution risk. This app
  reduces it with several layers, but they do **not** remove it:
  1. `sqlglot` parsing: exactly one statement whose root is a `SELECT`; DDL/DML, `ATTACH`, `COPY`,
     `PRAGMA`, `SET`, `INSTALL`, `LOAD`, multiple statements and unparsable input are rejected.
  2. A table allow-list (`data` and the user's own `ds_*` tables only) and a function deny-list
     (file/URL readers, `glob`, `query()`, `duckdb_*`, `pragma_*`, `getenv`, settings access).
  3. DuckDB settings applied and then locked: `enable_external_access=false`, no extension
     autoload/autoinstall, no community extensions, `memory_limit`, `threads=2`,
     `max_temp_directory_size=0`, `lock_configuration=true`. Data is registered as in-memory Arrow
     tables, so DuckDB itself never opens a file.
  4. A row cap (`SQL_MAX_ROWS`) with a `truncated` flag, and a 20,000-character query limit.
  5. Each query runs in a separate worker process that the API kills after `SQL_TIMEOUT_SECONDS`.

  DuckDB's own documentation states that untrusted SQL needs sandboxing beyond these settings. For
  production, run the backend in a container with **no outbound network access** and a **read-only
  filesystem** (with a writable volume only for `STORAGE_DIR`), as a non-root user.
- **AI:** providers are called only from the backend. By default only table/column names, types and
  computed results are sent; sample rows are sent only if the user turns that on in Settings.
  "Explain this SQL" sends only the query text. The xAI integration uses the OpenAI-compatible
  `/v1/chat/completions` endpoint, which xAI currently labels as *legacy* (their primary API is
  Responses). The automated tests use a mocked provider. During development the chart suggestions, Ask
  and report generation were also run by hand against live Groq; xAI Grok and the other AI features
  (SQL generation, insight explanations) were not run against a live key.

## Reference products

Patterns were learned from public descriptions of Julius AI, Powerdrill, Polymer, Tableau, Power BI,
ThoughtSpot, Akkio, Metabase, Apache Superset, Redash, OpenRefine and Power Query. No code, text,
logos or layouts were copied. Which pattern was adopted where is listed in
[docs/SPEC.md](docs/SPEC.md).

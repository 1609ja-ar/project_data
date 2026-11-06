# Progress

Tick a phase only after its checks have actually run and passed.

- [x] Phase 0 - Scaffolding
- [x] Phase 1 - MongoDB + Authentication
- [x] Phase 2 - Landing page + app shell
- [x] Phase 3 - Dataset upload and storage
- [x] Phase 3b - Automatic data cleaning pipeline
- [x] Phase 4 - Analytics engine (query plans)
- [x] Phase 4b - SQL Workbench
- [x] Phase 4c - Power BI + Excel export
- [x] Phase 4d - Automated insights engine
- [x] Automatic dashboard + visual redesign (requested 2026-10-23, outside the original phases)
- [x] Auto charts, pinned tiles, AI reports, practical Insights / Excel / Power BI / Home, 3D views (2026-10-24)
- [x] Ask, forecast, targets, share links; Explorer and History removed; area colours; richer 3D (2026-10-24)
- [x] Five 3D click moments (KPI change, forecast ribbon, share card flip, insight ranking, cleaning replay); SQL moved
  out of the main menu (still reachable from Datasets, dataset pages and "Verify in SQL") (2026-10-24)
- [x] Clean data downloads (share pack, Excel, CSV, JSON, column choice) (2026-10-25)
- [x] Stronger automatic cleaning (encoding repair, units, scientific notation, dates, emails, phones, capitalisation) (2026-10-25)
- [x] Pivot tables (nested rows, subtotals, several values, no row limit) and import from Google Sheets / a link with refresh (2026-10-25)
- [x] Content audit: landing page, in-app text and docs checked against the code and corrected (2026-10-25)
- [x] Sign-in uses one opaque HttpOnly session cookie (server-side sessions); JWT, refresh and CSRF cookies removed (2026-10-25)
- [ ] Phase 5+ - NOT RECEIVED (prompt truncated at Phase 5 "Charts")

## Verification at the Phase 4d boundary (2026-10-23)
- Backend: `python -m pytest` -> 141 passed (local MongoDB, Python 3.14.3).
- Frontend: `npm test` -> 28 passed; `npm run build` passes.
- Manual end-to-end in headless Chrome against the real stack (process-pool workers, Vite proxy):
  sign-in, upload of messy CSV, cleaning report and suggestions, Data Explorer, profile, SQL run and
  chart, export page, live feed via bearer token, insights and Overview findings.

## Automatic dashboard + redesign (2026-10-23)
- `POST /api/analytics/{id}/dashboard` (`app/analytics/dashboard.py`): KPIs with change vs the previous
  complete period and sparklines, trend, donut share, ranked bars, stacked trend by a small category and a
  summary table. Filters: date range, category values (also click-to-filter), measure, total/average,
  time grain. Every figure comes from `run_verified`; default views are cached in `analyses`.
- Uploads open the dashboard as soon as cleaning finishes (multi-sheet workbooks stay on the upload page).
- Redesign: neutral tokens, single blue accent, compact density; 3D scenes, tilt cards and page
  transitions removed at the time (three.js was uninstalled here and reinstated on 2026-10-24, see below).
  Chart palette re-validated for the new surfaces.
- Checks: backend 152 passed; frontend 29 passed; build passes; screenshots of dashboard (light, dark,
  filtered by clicking a bar, 390px mobile), Home and landing in headless Chrome.

## Auto charts, reports, exports, 3D (2026-10-24)
- `POST /api/analytics/{id}/chart-suggestions`: rule menu of valid plans (`app/analytics/recommend.py`); the AI
  provider may only pick and explain menu ids (unknown ids ignored, truncated replies salvaged); rules otherwise.
  Charts are computed with `run_verified` under the dashboard filters. Pin/unpin: `/dashboard/tiles` (stored in
  `dashboards`), pinned tiles follow the dashboard filters and are part of the cache key.
- Reports: `POST/GET/DELETE /api/reports` (`app/services/reports.py`): verified facts (KPIs, charts, insights,
  quality, columns) + narrative by AI (numbers checked, unmatched marked "[unverified]") or templates. Viewer
  prints to PDF and downloads Markdown.
- Exports: `POST /exports/{id}/preview`, `POST /exports/{id}/excel-custom` (columns, dashboard filters, Summary
  sheet with KPIs, native charts), `GET /powerbi/{id}/setup` (web-feed M query, file M query, DAX, types).
- Frontend: Auto charts panel, findings strip, KPI accents, chart/table/3D tile views, Reports + ReportView,
  new Insights (summary, list + detail, actions), Excel builder + Power BI guided setup with connection test,
  new Home, landing 3D hero. 3D: `three/DataBars3D.jsx` (data-driven, DOM labels), `three/HeroScene.jsx`
  (sample data, labelled), both lazy with reduced-motion and no-WebGL fallbacks.
- AI calls use larger token budgets: the configured Groq model (openai/gpt-oss-120b) spends tokens on reasoning.
- Checks: backend 161 passed; frontend 34 passed; build passes; headless-Chrome run against real Groq: AI chart
  picks, AI report (spot-checked numbers, none unverified), insights, Excel preview, Power BI token + feed test,
  Home, 3D tile, landing light/dark, 390px mobile.

## Practical features (2026-10-24, second pass)
- Ask (`POST /api/ask`, `app/analytics/ask.py`): rule parser for common phrasings (measures, "by", top N, lowest,
  average, monthly/weekly, share, category values and years as filters); with AI, the model fills a fixed plan
  template that is validated before running; invalid AI plans fall back to the parser. Answers are written from
  the verified result; words that had no effect are reported ("Not understood"). Recent questions and
  suggestions per dataset. Topbar Ask bar (Ctrl+K).
- Forecast (`app/analytics/forecast.py`): OLS over complete periods, 3 periods ahead, 80% prediction interval;
  shown on the trend tile as a dashed line and band, labelled as an estimate.
- Targets: `PUT/DELETE /api/analytics/{id}/goals`; progress (value / target) is attached to KPIs by the backend.
- Share links: `POST /api/analytics/{id}/share` stores a snapshot (figures and charts, no rows, no query
  details); `GET /api/public/share/{token}` (rate limited) until expiry or revocation; `/s/:token` page.
- Removed: Explorer and History pages (Ask and Home cover them); statistics and explanatory captions moved
  out of the main views into "How calculated"; AI-styled gradients and sparkle icons.
- Design: one colour per area (`--m-*` tokens) for sidebar icons, page headers and active state.
- 3D: shared Stage (in-browser studio environment, contact shadows), City3D (period x category), physical
  materials and hover lift on bars, new landing city scene.
- Checks: backend 176 passed; frontend 39 passed; build passes; browser run with real Groq: Ask (AI plan and
  rule fallback), targets, forecast, share link opened signed-out, 3D city, Home, Insights, landing light/dark.

## Latest additions (2026-10-24 and 2026-10-25)
- 3D moments (`three/moments/`, `components/Moment3D.jsx`): opened from an icon, lazy-loaded, driven by the user's
  own figures; reduced motion shows the final frame.
- Clean data downloads (`services/clean_export.py`, `GET /datasets/{id}/download?format=zip|xlsx|csv|csv_excel|json&columns=`).
- Cleaning (`cleaning/standardize.py`, `parsing.py`): see docs/METRICS.md. Regression file: `tests/messy_customers.csv`.
- Pivot (`analytics/pivot.py`, `POST /analytics/{id}/pivot` and `/pivot/export`): vectorised group-by per level, each
  recomputed in DuckDB; 25,000 row groups computed and verified in about 3 seconds in the tests.
- Link import (`services/fetch.py`, `POST /datasets/import-url`, `POST /datasets/{id}/refresh`).
- Password reset reports honestly whether email can be sent; unused `reportlab` and `matplotlib` removed from requirements.
- Checks: backend 208 passed; frontend 52 passed; build passes; real-stack checks in headless Chrome for the
  moments, downloads, pivot and a real public CSV import (245 rows). The pivot was also compared with plain
  Pandas on the 948-row sample for sum, average, median, minimum, maximum, count and distinct count: no differences.

## Not verified
- Python 3.11-3.13 (developed and tested on 3.14 only).
- MongoDB Atlas (only a local MongoDB service was used).
- xAI Grok: never called. Groq was used by hand for chart suggestions, Ask and reports during
  development (see the checks above); SQL generation and insight explanations were not run against a live key.
  The automated tests use a mocked HTTP provider.
- Power BI Desktop / Power BI service: the package and feed were tested by automated tests and HTTP
  requests only, not inside Power BI.
- SMTP email delivery (development console fallback only).

## Built against the received phases but intentionally left out (depend on unreceived phases)
- Sidebar items AI Data Analyst (chat) and Visualizations (Chart Studio), and the "Open in Chart Studio",
  "Ask AI about this" and "Add to report" actions. (Pinning charts to the dashboard exists, via Ask and Suggested charts.)

## Resume point
Paste the rest of the build prompt (from Phase 5 "Charts" onward, plus the "Environment variables"
section). Next: Phase 5 Chart Studio. Reuse `frontend/src/components/ResultChart.jsx` (bar, horizontal,
grouped, stacked, 100% stacked, line, area already render from backend rows) and
`POST /api/analytics/{id}/chart` (results are stored as `analyses` with `analysis_type: "chart"`,
which the Excel export already turns into native charts).

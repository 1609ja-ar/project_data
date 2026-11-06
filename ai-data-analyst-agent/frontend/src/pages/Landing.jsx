import { lazy, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight, BarChart3, Box, Briefcase, Calculator, Code2, Download, FileSpreadsheet, FileText, Grid3x3, KeyRound, LayoutGrid, Link2, Lock,
  MessageSquare, ShieldCheck, Target, Trash2, Upload,
} from 'lucide-react';
import Logo from '../components/Logo.jsx';
import ThemeSwitcher from '../components/ThemeSwitcher.jsx';
import { Badge } from '../components/ui/index.js';
import {
  AskMini, AskMock, City, CleaningMock, ColumnsToTiles, DashboardMock, DropzoneMini, ExcelPowerBI, ForecastMock, MiniChart,
  ReportMock, ShareMock, StepperMini, TrustPanel,
} from '../components/landing/Mocks.jsx';
import { useCases } from '../components/landing/sample.js';
import usePageTitle from '../hooks/usePageTitle.js';
import Lazy3D from '../three/Lazy3D.jsx';
import '../styles/landing.css';

const HeroScene = lazy(() => import('../three/HeroScene.jsx'));

const TOUR = [
  { id: 'dashboard', label: 'Dashboard', icon: BarChart3, module: 'dashboard', caption: 'KPIs with change and targets, trend with forecast, breakdowns and a 3D view, built from your columns.', view: DashboardMock },
  { id: 'ask', label: 'Ask', icon: MessageSquare, module: 'ask', caption: 'Type a question, get the answer in one sentence and the chart behind it. Try the questions below.', view: AskMock },
  { id: 'forecast', label: 'Forecast & targets', icon: Target, module: 'insights', caption: 'See where the trend is heading for the next three periods (months, for a monthly trend) and how each KPI tracks against its target.', view: ForecastMock },
  { id: 'reports', label: 'Reports', icon: FileText, module: 'reports', caption: 'A one-click report with summary, key figures and findings, ready to print as PDF.', view: ReportMock },
  { id: 'share', label: 'Share', icon: Link2, module: 'datasets', caption: 'Send a read-only link. It shows the figures and charts you chose, not your rows, and expires on its own.', view: ShareMock },
];

const FEATURES = [
  { id: 'auto', module: 'dashboard', kicker: 'Automatic dashboards', title: 'No templates. No column mapping.',
    text: 'The app reads the type and role of every column: dates become trends, categories become breakdowns, money and quantities become KPIs. You get a dashboard the moment cleaning finishes.',
    points: ['Date range presets and category filters', 'Click any bar to filter the whole page', 'Pin suggested charts or your own questions'], visual: ColumnsToTiles },
  { id: 'clean', module: 'upload', kicker: 'Cleaning you can audit', title: 'Messy exports, fixed and explained.',
    text: 'Currency symbols, brackets for negatives, mixed date formats, units such as kg or 12k, garbled characters, stray spaces, inconsistent capitals, duplicates and “Total” rows are handled for you. The original file is never changed, and every change is listed.',
    points: ['A total row is removed only if it really adds up', 'Money is kept as exact decimals', 'Switch back to any earlier version'], visual: CleaningMock },
  { id: '3d', module: 'reports', kicker: '3D views', title: 'See months and categories at once.',
    text: 'Any breakdown can switch to an interactive 3D view. Months × regions become a city of columns you can rotate, so the biggest movers stand out at a glance.',
    points: ['Drag to rotate, hover for the exact figure', 'Same verified numbers as the chart and table', 'Falls back to a normal chart on older devices'], visual: City },
  { id: 'export', module: 'exports', kicker: 'Excel and Power BI', title: 'Take it into the tools your team already uses.',
    text: 'Download exactly the rows and columns you need as an Excel workbook with native charts, or connect Power BI to a feed that loads the latest cleaned version each time you refresh.',
    points: ['Pick columns and filters, see a live preview', 'Summary sheet with KPIs and charts', 'Ready-to-paste Power Query and DAX'], visual: ExcelPowerBI },
];

const ROLES = [
  { icon: Briefcase, module: 'dashboard', title: 'Managers and founders', text: 'Ask questions, track targets and share a link with the team without waiting for an analyst.' },
  { icon: Calculator, module: 'datasets', title: 'Finance and operations', text: 'Exact decimal money, period-over-period change and a record of how each figure was calculated.' },
  { icon: Code2, module: 'sql', title: 'Analysts', text: 'Read-only SQL on your cleaned data, the equivalent SQL behind every tile, and exports to Excel or Power BI.' },
];

const CAPABILITIES = [[Upload, 'Upload & clean'], [BarChart3, 'Auto dashboards'], [MessageSquare, 'Ask'], [Target, 'Forecast & targets'], [LayoutGrid, 'Suggested charts'],
  [Grid3x3, 'Pivot tables'], [Box, '3D views'], [FileText, 'Reports'], [Link2, 'Share links'], [Download, 'Clean data download'], [FileSpreadsheet, 'Excel & Power BI'],
  [Code2, 'SQL editor']];

const FAQ = [
  ['Which files work?', 'CSV up to 150 MB and 30 lakh rows, XLSX and XLS up to 40 MB, or a Google Sheet shared as “anyone with the link” (one tab at a time). Workbooks with several sheets let you pick the sheet. Password-protected and macro-enabled files are rejected.'],
  ['What does the cleaning actually change?', 'It standardises currency, numbers, dates, units and text; repairs garbled characters; tidies emails, phone numbers, names and capitalisation; removes exact duplicate rows when the file has an ID column (otherwise it flags them); and removes a “Total” row only when it adds up to the rows above it. Each step is listed with examples, and the original file stays unchanged. Values that cannot be read are left empty in the cleaned version and listed in the report.'],
  ['Can I trust the numbers?', 'Totals, averages, counts and other aggregates in dashboards, answers, pivot tables and insights are calculated with Pandas and recalculated independently with DuckDB. If the two do not agree, the figure is not shown. Forecasts and statistical tests are model estimates and are labelled as such. Every tile has a “How calculated” panel with the formula, filters, rows used and the equivalent SQL.'],
  ['Does the AI calculate anything?', 'No. AI only turns a question into a structured query, picks charts from a list of valid ones and writes report text and explanations. Numbers it writes are checked against the results and marked if they do not match.'],
  ['Do I need an AI key?', 'No. Dashboards, questions, pivot tables, forecasts, targets, reports and exports all work without one. With a key, questions understand looser wording, reports get a written summary and insights can be explained.'],
  ['How is the forecast made?', 'A straight-line trend over the complete periods (at least six), projected three periods ahead with an 80% range. It is labelled as an estimate and never mixed with recorded figures.'],
  ['Can I download the cleaned data?', 'Yes. From “Clean data” you can download a share pack (clean CSV, data dictionary, cleaning report and a checksum), an Excel workbook, a CSV, an Excel-friendly CSV or JSON, and leave out columns, such as ones that look like personal data, before you share it.'],
  ['Who can see a shared link?', 'Anyone with the link, until it expires or you revoke it. It shows the figures and charts of the view you chose, not the dataset’s rows. Labels used in a chart, such as product or customer names, are visible.'],
  ['Does it replace Power BI?', 'No. It gets data clean and answered quickly, then hands it to Excel or Power BI when you need them. It does not create .pbix files.'],
];

function Tour() {
  const [tab, setTab] = useState(0);
  const refs = useRef([]);
  const T = TOUR[tab];
  const View = T.view;
  const onKey = (e) => {
    const n = e.key === 'ArrowRight' ? (tab + 1) % TOUR.length : e.key === 'ArrowLeft' ? (tab - 1 + TOUR.length) % TOUR.length : null;
    if (n !== null) { setTab(n); refs.current[n]?.focus(); }
  };
  return (
    <div className="lp-tour">
      <div className="lp-tabs" role="tablist" aria-label="Product tour" onKeyDown={onKey}>
        {TOUR.map((t, i) => (
          <button key={t.id} ref={(el) => { refs.current[i] = el; }} type="button" role="tab" aria-selected={i === tab} tabIndex={i === tab ? 0 : -1}
            id={`tour-${t.id}`} aria-controls="tour-panel" className="lp-tab" style={{ '--mc': `var(--m-${t.module})` }} onClick={() => setTab(i)}>
            <span className="nav-icon"><t.icon size={15} aria-hidden="true" /></span>{t.label}
          </button>
        ))}
      </div>
      <p className="lp-tour-caption">{T.caption} <Badge tone="warning">Sample data</Badge></p>
      <div id="tour-panel" role="tabpanel" aria-labelledby={`tour-${T.id}`} className="lp-tour-panel"><View /></div>
    </div>
  );
}

export default function Landing() {
  usePageTitle('');
  return (
    <div className="landing lp">
      <header className="l-header">
        <div className="l-header-inner">
          <Logo />
          <nav className="l-nav" aria-label="Main">
            <a href="#product">Product</a>
            <a href="#use-cases">Use cases</a>
            <a href="#features">Features</a>
            <a href="#trust">Trust</a>
            <a href="#faq">FAQ</a>
          </nav>
          <div className="row" style={{ marginLeft: 'auto' }}>
            <span className="hide-mobile"><ThemeSwitcher /></span>
            <Link to="/signin" className="btn btn-ghost">Sign in</Link>
            <Link to="/signup" className="btn btn-primary">Get started</Link>
          </div>
        </div>
      </header>

      <main id="top">
        <section className="lp-hero">
          <div className="lp-wrap lp-hero-grid">
            <div>
              <a href="#product" className="lp-eyebrow"><span className="lp-eyebrow-tag">New</span> Ask your data in plain words <ArrowRight size={14} aria-hidden="true" /></a>
              <h1>Your spreadsheets, turned into answers.</h1>
              <p className="lp-lead">
                Upload a CSV or Excel export, or paste a Google Sheets link. It is cleaned, charted and ready to question as soon as
                cleaning finishes: dashboards that build themselves, plain-language answers, pivot tables, forecasts, targets and reports you
                can share. Totals, averages and counts are recalculated by a second engine.
              </p>
              <div className="row-wrap" style={{ marginTop: 28, gap: 10 }}>
                <Link to="/signup" className="btn btn-primary btn-lg">Start with your own file <ArrowRight size={16} aria-hidden="true" /></Link>
                <a href="#product" className="btn btn-secondary btn-lg">Take the tour</a>
              </div>
              <p className="lp-small">Free to use · no credit card · works without an AI key</p>
            </div>
            <div className="lp-hero-visual">
              <span className="demo-label"><Badge tone="warning">Sample data</Badge></span>
              <Lazy3D scene={HeroScene} height={420} label="3D chart of sample monthly revenue by region" fallback={<div style={{ height: 420 }} />} />
            </div>
          </div>
          <div className="lp-wrap">
            <dl className="lp-facts">
              <div><dt>2 engines</dt><dd>calculate each total and must agree</dd></div>
              <div><dt>3 formats</dt><dd>CSV up to 150 MB, XLSX and XLS up to 40 MB</dd></div>
              <div><dt>0 setup</dt><dd>no templates, no column mapping</dd></div>
              <div><dt>Read-only</dt><dd>shared links show figures, not your rows</dd></div>
            </dl>
          </div>
        </section>

        <section className="lp-section" id="product">
          <div className="lp-wrap">
            <div className="lp-head">
              <span className="lp-kicker" style={{ '--mc': 'var(--m-dashboard)' }}>Product tour</span>
              <h2>Everything between “here's a spreadsheet” and “here's what it means”.</h2>
            </div>
            <Tour />
          </div>
        </section>

        <section className="lp-section lp-alt" id="how">
          <div className="lp-wrap">
            <div className="lp-head">
              <span className="lp-kicker" style={{ '--mc': 'var(--m-upload)' }}>How it works</span>
              <h2>From file to answer in three steps.</h2>
            </div>
            <ol className="lp-how">
              <li><span className="lp-num">1</span><h3>Upload</h3><p>Drop in an export from your CRM, shop, ERP, bank or survey tool.</p><DropzoneMini /></li>
              <li><span className="lp-num">2</span><h3>It cleans and builds</h3><p>Fixes the data, keeps the original, and opens a dashboard built for it.</p><StepperMini /></li>
              <li><span className="lp-num">3</span><h3>Ask and share</h3><p>Ask questions, set targets, then send a link or a report.</p><AskMini /></li>
            </ol>
          </div>
        </section>

        <section className="lp-section" id="use-cases">
          <div className="lp-wrap">
            <div className="lp-head">
              <span className="lp-kicker" style={{ '--mc': 'var(--m-insights)' }}>Use cases</span>
              <h2>Works with any table, whatever it is about.</h2>
              <p>No column mapping is needed: the app works out dates, categories and money from the values and the column names. The cards below use made-up numbers to show the kind of question each team asks. <Badge tone="warning">Sample data</Badge></p>
            </div>
            <div className="lp-cases">
              {useCases.map((u) => (
                <article key={u.title} className="lp-case" style={{ '--mc': `var(--m-${u.module})` }}>
                  <div className="row between"><span className="lp-case-title">{u.title}</span><span className="lp-case-kpi"><strong>{u.kpi}</strong> <span className="xs muted">{u.label}</span></span></div>
                  <MiniChart kind={u.kind} data={u.data} module={u.module} />
                  <p className="lp-case-q"><MessageSquare size={13} aria-hidden="true" /> “{u.question}”</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-section lp-alt" id="features">
          <div className="lp-wrap lp-features">
            {FEATURES.map((f, i) => (
              <div key={f.id} className="lp-feature" data-flip={i % 2 === 1}>
                <div className="lp-feature-text" style={{ '--mc': `var(--m-${f.module})` }}>
                  <span className="lp-kicker">{f.kicker}</span>
                  <h2>{f.title}</h2>
                  <p>{f.text}</p>
                  <ul className="lp-ticks">{f.points.map((p) => <li key={p}>{p}</li>)}</ul>
                </div>
                <div className="lp-feature-visual"><f.visual /></div>
              </div>
            ))}
          </div>
        </section>

        <section className="lp-section" id="trust">
          <div className="lp-wrap">
            <div className="lp-head">
              <span className="lp-kicker" style={{ '--mc': 'var(--m-exports)' }}>Trust</span>
              <h2>Every number can be checked.</h2>
              <p>AI is useful for understanding a question. It is not allowed to make up the answer.</p>
            </div>
            <TrustPanel />
            <div className="lp-trust-grid">
              <div><ShieldCheck size={18} aria-hidden="true" /><h3>AI never calculates</h3><p>It fills in a fixed query template that is validated before it runs, and any number it writes is checked.</p></div>
              <div><Lock size={18} aria-hidden="true" /><h3>Security built in</h3><p>Argon2id passwords, one HttpOnly session cookie holding only a random ID, sessions that end on logout or a password change, and cross-site request blocking.</p></div>
              <div><KeyRound size={18} aria-hidden="true" /><h3>Read-only access</h3><p>SQL runs read-only in a separate, time-limited process. Shared links and feeds are revocable.</p></div>
              <div><Trash2 size={18} aria-hidden="true" /><h3>Your data, your call</h3><p>Original files are kept unchanged. Delete a dataset, or your whole account, at any time.</p></div>
            </div>
          </div>
        </section>

        <section className="lp-section lp-alt">
          <div className="lp-wrap">
            <div className="lp-head">
              <span className="lp-kicker" style={{ '--mc': 'var(--m-ask)' }}>Built for every role</span>
              <h2>One upload, three ways to use it.</h2>
            </div>
            <div className="lp-roles">
              {ROLES.map((r) => (
                <div key={r.title} className="lp-role" style={{ '--mc': `var(--m-${r.module})` }}>
                  <span className="page-icon" aria-hidden="true"><r.icon size={18} /></span>
                  <h3>{r.title}</h3><p>{r.text}</p>
                </div>
              ))}
            </div>
            <div className="lp-capabilities">
              {CAPABILITIES.map(([I, l]) => <span key={l} className="lp-cap"><I size={14} aria-hidden="true" /> {l}</span>)}
            </div>
          </div>
        </section>

        <section className="lp-section" id="faq">
          <div className="lp-wrap lp-faq">
            <div className="lp-head lp-head-left">
              <span className="lp-kicker" style={{ '--mc': 'var(--m-home)' }}>FAQ</span>
              <h2>Questions people ask first.</h2>
              <p>Something else? Sign up and try it with your own file: it takes a minute.</p>
            </div>
            <div>
              {FAQ.map(([q, a]) => (
                <details key={q} className="faq-item">
                  <summary>{q}<span aria-hidden="true" className="muted">+</span></summary>
                  <p>{a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-cta">
          <div className="lp-wrap lp-cta-inner">
            <div>
              <h2>Bring a spreadsheet. Leave with answers.</h2>
              <p>Create an account and upload your first file. Your dashboard is ready when cleaning finishes.</p>
            </div>
            <div className="row-wrap" style={{ gap: 10 }}>
              <Link to="/signup" className="btn btn-primary btn-lg">Get started <ArrowRight size={16} aria-hidden="true" /></Link>
              <Link to="/signin" className="btn btn-secondary btn-lg">Sign in</Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-wrap lp-footer-grid">
          <div>
            <Logo />
            <p className="small muted" style={{ marginTop: 10, maxWidth: 300 }}>Upload a spreadsheet, get a verified dashboard, answers, forecasts and reports.</p>
          </div>
          <div><h4>Product</h4><a href="#product">Tour</a><a href="#features">Features</a><a href="#use-cases">Use cases</a><a href="#trust">Trust</a></div>
          <div><h4>Account</h4><Link to="/signup">Create account</Link><Link to="/signin">Sign in</Link><Link to="/forgot-password">Reset password</Link></div>
          <div><h4>About</h4><span className="small muted">A portfolio project. Not affiliated with Microsoft, Power BI or any product it exports to.</span></div>
        </div>
        <div className="lp-wrap lp-footer-base small muted">© {new Date().getFullYear()} AI Data Analyst Agent</div>
      </footer>
    </div>
  );
}

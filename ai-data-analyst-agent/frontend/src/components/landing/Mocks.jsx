import { lazy, useMemo, useState } from 'react';
import { Area, AreaChart, Bar, BarChart, Line, LineChart, ResponsiveContainer } from 'recharts';
import { ArrowRight, Check, CheckCircle2, Link2, Search } from 'lucide-react';
import KpiCard from '../dashboard/KpiCard.jsx';
import Tile from '../dashboard/Tile.jsx';
import { Stepper } from '../CleaningProgress.jsx';
import { Badge } from '../ui/index.js';
import Lazy3D from '../../three/Lazy3D.jsx';
import useThemeColors from '../../hooks/useThemeColors.js';
import { cssVar } from '../../context/ThemeContext.jsx';
import { MODULES } from '../../layouts/nav.js';
import { formatCurrency, formatInteger, formatPercent, formatPeriod } from '../../utils/format.js';
import * as S from './sample.js';

const City3D = lazy(() => import('../../three/City3D.jsx'));
const SEED_ACCENTS = [0, 6, 2, 1];

/* ------------------------------------------------------------------ frames */

export function BrowserFrame({ url, children, className = '' }) {
  return (
    <div className={`lp-frame ${className}`}>
      <div className="lp-frame-bar" aria-hidden="true">
        <span className="lp-dots"><i /><i /><i /></span>
        <span className="lp-url">{url}</span>
        <span style={{ width: 44 }} />
      </div>
      <div className="lp-frame-body">{children}</div>
    </div>
  );
}

const RAIL = ['home', 'dashboard', 'ask', 'insights', 'reports', 'datasets', 'upload', 'sql', 'exports'];

function Rail({ active }) {
  return (
    <div className="lp-rail" aria-hidden="true">
      <span className="lp-rail-logo" />
      {RAIL.map((m) => {
        const Icon = MODULES[m].icon;
        return <span key={m} className="lp-rail-item" data-active={m === active} style={{ '--mc': `var(--m-${m})` }}><Icon size={15} /></span>;
      })}
    </div>
  );
}

export function AppWindow({ module, url, title, meta, children }) {
  const M = MODULES[module];
  return (
    <BrowserFrame url={url}>
      <div className="lp-app">
        <Rail active={module} />
        <div className="lp-app-main">
          <div className="lp-app-head" style={{ '--mc': `var(--m-${module})` }}>
            <span className="page-icon" aria-hidden="true"><M.icon size={18} /></span>
            <div style={{ minWidth: 0 }}><h3>{title}</h3>{meta && <p>{meta}</p>}</div>
          </div>
          {children}
        </div>
      </div>
    </BrowserFrame>
  );
}

/* ------------------------------------------------------------------ tiles from sample data */

const tile = (id, kind, title, subtitle, spec, data, extra = {}) => ({ id, kind, title, subtitle, how_calculated: null, chart: { spec, ...data }, ...extra });
const trendTile = () => tile('trend', 'trend', 'Total Revenue by month', '12 months · 2024-01 to 2024-12', { type: 'line', x: 'period', y: 'value' }, S.trend, { forecast: S.demoForecast() });
const shareTile = () => tile('share', 'share', 'Share of total revenue by Region', '4 values', { type: 'donut', x: 'region', y: 'value' }, S.byRegion, { dimension: 'region' });
const productTile = () => tile('product', 'breakdown', 'Total Revenue by Product', '4 values', { type: 'horizontal_bar', x: 'product', y: 'value' }, S.byProduct);
const splitTile = () => tile('split', 'split', 'Total Revenue by month and Region', '12 months', { type: 'stacked_bar', x: 'period', y: 'value', series: 'region' }, S.split, { dimension: 'region', series_dimension: 'region' });

const TOP_INSIGHTS = [
  ['danger', 'Important · Trend', 'Revenue shows an upward trend over 12 complete months'],
  ['danger', 'Important · Top contributor', `North contributes ${formatPercent(S.byRegion.rows[0][2])} of total Revenue`],
  ['warning', 'Notable · Segment difference', 'Revenue differs between Product Desk and Chair'],
];

/* ------------------------------------------------------------------ showcase panels */

export function DashboardMock() {
  return (
    <AppWindow module="dashboard" url="app/dashboard" title="harbor_sales_2024.xlsx" meta={`${formatInteger(S.orders)} orders · 2024-01-01 – 2024-12-31 · v1`}>
      <div className="dash-kpis">{S.kpis.map((k, i) => <KpiCard key={k.id} kpi={k} accent={SEED_ACCENTS[i]} />)}</div>
      <div className="istrip">
        {TOP_INSIGHTS.map(([tone, kicker, text]) => (
          <span key={text} className="istrip-card" data-tone={tone}><span className="xs muted">{kicker}</span><span className="small" style={{ fontWeight: 550 }}>{text}</span></span>
        ))}
        <span className="istrip-more small">All insights <ArrowRight size={14} aria-hidden="true" /></span>
      </div>
      <div className="dash-grid">
        <Tile className="span-8" tile={trendTile()} />
        <Tile className="span-4" tile={shareTile()} seriesOrder={S.seriesOrder} />
        <Tile className="span-5" tile={productTile()} />
        <Tile className="span-7" tile={splitTile()} seriesOrder={S.seriesOrder} />
      </div>
    </AppWindow>
  );
}

const fmt = (v) => formatCurrency(v);
const top = S.byRegion.rows[0];
const first = S.monthTotals[0];
const lastV = S.monthTotals[S.monthTotals.length - 1];
const ASKS = [
  { q: 'Top products by revenue', title: 'Total Revenue by Product (top 4)', sub: 'All dates',
    text: `${S.byProduct.rows[0][0]} has the highest total revenue: ${fmt(S.byProduct.rows[0][1])} (${formatPercent(S.byProduct.rows[0][1] / S.total)} of the total), across 4 Product values.`,
    tile: () => tile('a1', 'answer', 'Total Revenue by Product (top 4)', 'All dates', { type: 'horizontal_bar', x: 'product', y: 'value' }, S.byProduct) },
  { q: 'Monthly revenue in 2024', title: 'Total Revenue by month', sub: 'Order Date in 2024',
    text: `Total revenue went from ${fmt(first)} in Jan 2024 to ${fmt(lastV)} in Dec 2024 (${((lastV - first) / first >= 0 ? '+' : '') + formatPercent((lastV - first) / first, 1)}).`,
    tile: () => tile('a2', 'answer', 'Total Revenue by month', 'Order Date in 2024', { type: 'area', x: 'period', y: 'value' }, S.trend) },
  { q: 'Share of revenue by region', title: 'Total Revenue by Region', sub: '4 values',
    text: `${top[0]} has the highest total revenue: ${fmt(top[1])} (${formatPercent(top[2])} of the total), across 4 Region values.`,
    tile: () => tile('a3', 'answer', 'Total Revenue by Region', '4 values', { type: 'donut', x: 'region', y: 'value' }, S.byRegion, { dimension: 'region' }) },
];

export function AskMock() {
  const [i, setI] = useState(0);
  const a = ASKS[i];
  return (
    <AppWindow module="ask" url="app/ask" title="Ask" meta="harbor_sales_2024.xlsx">
      <div className="lp-ask">
        <div className="ask-box lp-ask-box" aria-hidden="true">
          <span className="lp-typed">{a.q}</span>
          <span className="btn btn-primary btn-icon" style={{ background: 'var(--m-ask)' }}><ArrowRight size={16} style={{ transform: 'rotate(-90deg)' }} /></span>
        </div>
        <div className="chips" role="group" aria-label="Try a question">
          {ASKS.map((x, k) => (
            <button key={x.q} type="button" className="suggest-chip" aria-pressed={k === i} data-on={k === i} onClick={() => setI(k)}>{x.q}</button>
          ))}
        </div>
        <article className="answer" key={i}>
          <div className="answer-q">{a.q.toLowerCase()}</div>
          <p className="answer-text">{a.text}</p>
          <Tile tile={a.tile()} seriesOrder={S.seriesOrder} />
        </article>
      </div>
    </AppWindow>
  );
}

export function ForecastMock() {
  const targets = [
    ['Total Revenue', S.total, 650000, fmt],
    ['Orders', S.orders, 5000, formatInteger],
    ['Average order', S.total / S.orders, 130, fmt],
  ];
  return (
    <AppWindow module="dashboard" url="app/dashboard" title="Forecast and targets" meta="Projection from 12 complete months">
      <div className="home-row">
        <Tile tile={trendTile()} defaultForecast />
        <div className="card">
          <div className="card-header"><h2>Targets</h2></div>
          <ul className="targets">
            {targets.map(([label, value, target, f]) => {
              const progress = value / target;
              const met = progress >= 1;
              return (
                <li key={label}>
                  <div className="row between"><span className="small" style={{ fontWeight: 550 }}>{label}</span><Badge tone={met ? 'success' : 'warning'}>{met ? 'On target' : 'Behind'}</Badge></div>
                  <div className="goal" data-met={met}><div className="goal-bar"><span style={{ width: `${Math.min(100, progress * 100)}%` }} /></div></div>
                  <span className="xs muted num">{f(value)} of {f(target)} · {formatPercent(progress, 0)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </AppWindow>
  );
}

export function ReportMock() {
  const k = S.kpis[0];
  const regionShare = formatPercent(top[2]);
  const findings = [
    `${top[0]} contributes ${regionShare} of total revenue, ${fmt(top[1])} of ${fmt(S.total)}.`,
    `${S.byProduct.rows[0][0]} is the largest product at ${formatPercent(S.byProduct.rows[0][1] / S.total)} of revenue.`,
    `Monthly revenue rose from ${fmt(first)} in January to ${fmt(lastV)} in December.`,
  ];
  return (
    <AppWindow module="reports" url="app/reports/harbor-sales-2024" title="Reports" meta="Saved report">
      <article className="report-doc lp-report">
        <header className="report-cover">
          <span className="report-kicker">Data report</span>
          <h1>Harbor sales 2024 review</h1>
          <p className="report-meta">harbor_sales_2024.xlsx · version 1 · {formatInteger(S.orders)} records · 2024-01-01 to 2024-12-31</p>
        </header>
        <section className="report-section">
          <h2>Executive summary</h2>
          <p className="report-lead">
            Total revenue for 2024 was {fmt(S.total)} across {formatInteger(S.orders)} orders. In {formatPeriod(k.change.period)} it {k.change.pct < 0 ? 'fell' : 'rose'} {formatPercent(Math.abs(k.change.pct))} compared
            with {formatPeriod(k.change.previous_period)}. {top[0]} is the largest region, and revenue trended upward through the year with small dips in some months.
          </p>
          <h3>Key findings</h3>
          <ol className="report-findings">{findings.map((f) => <li key={f}>{f}</li>)}</ol>
        </section>
        <section className="report-section" style={{ marginBottom: 0 }}>
          <div className="report-kpis">
            {S.kpis.slice(0, 3).map((x) => (
              <div className="rk" key={x.id}><span className="xs muted">{x.label}</span><span className="rk-value num">{x.column.semantic_type === 'currency' ? fmt(x.value) : formatInteger(x.value)}</span></div>
            ))}
          </div>
        </section>
      </article>
    </AppWindow>
  );
}

export function ShareMock() {
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  return (
    <AppWindow module="dashboard" url="app/dashboard" title="Share dashboard" meta="Read-only snapshot of this view">
      <div className="lp-share">
        <div className="card lp-share-card">
          <div className="grid-2">
            <div className="field"><span className="label">Title</span><div className="input lp-fake">Harbor sales 2024 - team view</div></div>
            <div className="field"><span className="label">Expires after</span><div className="input lp-fake">7 days</div></div>
          </div>
          <div className="share-created" style={{ marginTop: 12 }}>
            <Link2 size={16} aria-hidden="true" />
            <code className="token-box grow">{origin}/s/shr_a8Kd2Qm9xW4t</code>
            <span className="btn btn-secondary btn-sm">Copy</span>
          </div>
          <ul className="share-list">
            <li><span className="grow"><span className="small" style={{ fontWeight: 550 }}>Harbor sales 2024 - team view</span><span className="xs muted"> · 14 views · created 2 hours ago</span></span><Badge tone="success">active</Badge></li>
            <li><span className="grow"><span className="small" style={{ fontWeight: 550 }}>North region only</span><span className="xs muted"> · 3 views · Region in North</span></span><Badge tone="success">active</Badge></li>
            <li><span className="grow"><span className="small" style={{ fontWeight: 550 }}>Q3 board pack</span><span className="xs muted"> · 41 views</span></span><Badge>expired</Badge></li>
          </ul>
        </div>
        <ul className="lp-points">
          <li><CheckCircle2 size={16} /> Figures and charts only: no rows, no query details</li>
          <li><CheckCircle2 size={16} /> Choose the date range and filters that viewers see</li>
          <li><CheckCircle2 size={16} /> Expires on its own, or revoke it in one click</li>
          <li><CheckCircle2 size={16} /> Viewers need no account</li>
        </ul>
      </div>
    </AppWindow>
  );
}

/* ------------------------------------------------------------------ feature visuals */

const COLS = [['Order Date', 'date', 'trend'], ['Region', 'category', 'breakdown'], ['Product', 'category', 'breakdown'], ['Revenue', 'currency', 'measure'], ['Units', 'number', 'measure']];
const TILES = [['Total Revenue', 'KPI with change vs last month', 'dashboard'], ['Revenue by month', 'Trend with forecast', 'dashboard'], ['Revenue by Region', 'Ranked bars and a share donut', 'ask'],
  ['Region over time', 'Stacked trend, 3D view', 'reports'], ['Region summary', 'Table with share and averages', 'datasets']];

export function ColumnsToTiles() {
  return (
    <div className="lp-card lp-map">
      <div>
        <span className="lp-label">Columns found in your file</span>
        <ul className="lp-collist">{COLS.map(([n, t]) => <li key={n}><strong>{n}</strong><Badge>{t}</Badge></li>)}</ul>
      </div>
      <ArrowRight size={20} className="lp-map-arrow" aria-hidden="true" />
      <div>
        <span className="lp-label">What gets built</span>
        <ul className="lp-tilelist">{TILES.map(([n, d, m]) => <li key={n} style={{ '--mc': `var(--m-${m})` }}><i /><span><strong>{n}</strong><br /><span className="xs muted">{d}</span></span></li>)}</ul>
      </div>
    </div>
  );
}

function MiniTable({ data, changed = [], dim = false }) {
  const isChanged = (r, c) => changed.some(([rr, cc]) => rr === r && cc === c);
  return (
    <div className="table-wrap lp-mini" data-dim={dim}>
      <table className="table">
        <thead><tr>{data.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{data.rows.map((row, r) => (
          <tr key={r} className={row[0] === 'Total' ? 'lp-bad' : r === 2 && dim ? 'lp-bad' : ''}>{row.map((cell, c) => <td key={c} className={isChanged(r, c) ? 'changed' : ''}>{cell || ' '}</td>)}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function CleaningMock() {
  const steps = [['Currency values standardised', '4'], ['Dates converted to one format', '3'], ['Text trimmed and case unified', '4'], ['Duplicate row removed', '1'], ['Total row removed (verified: it adds up)', '1']];
  return (
    <div className="lp-card lp-clean">
      <div className="lp-clean-tables">
        <div><span className="lp-label">Your file</span><MiniTable data={S.messy} dim /></div>
        <ArrowRight size={18} className="lp-map-arrow" aria-hidden="true" />
        <div><span className="lp-label">Cleaned version</span><MiniTable data={S.cleaned} changed={S.cleaned.changed} /></div>
      </div>
      <ul className="lp-steps">{steps.map(([t, n]) => <li key={t}><Check size={14} /> <span className="grow">{t}</span><span className="num muted">{n}</span></li>)}</ul>
    </div>
  );
}

export function City() {
  return (
    <div className="lp-card lp-3d">
      <Badge tone="warning" style={{ position: 'absolute', top: 12, right: 12, zIndex: 2 }}>Sample data</Badge>
      <Lazy3D scene={City3D} height={360} label="3D view of monthly revenue by region (sample data)"
        sceneProps={{ columns: S.split.columns, rows: S.split.rows, spec: { type: 'stacked_bar', x: 'period', y: 'value', series: 'region' }, seriesOrder: S.seriesOrder }}
        fallback={<div style={{ height: 360 }} />} />
      <span className="lp-hint">Drag to rotate · hover a column for its value</span>
    </div>
  );
}

const SHEET = [['2024-01-05', 'North', 'Desk', '₹1,234.50', '3'], ['2024-01-07', 'West', 'Chair', '₹412.00', '4'], ['2024-01-09', 'South', 'Shelf', '₹318.90', '2'],
  ['2024-01-12', 'North', 'Lamp', '₹96.00', '5'], ['2024-01-14', 'East', 'Desk', '₹1,180.00', '2'], ['2024-01-15', 'West', 'Desk', '₹1,225.40', '3']];

export function ExcelPowerBI() {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'https://your-app';
  return (
    <div className="lp-card lp-export">
      <div className="lp-sheet" aria-label="Excel workbook preview">
        <div className="lp-sheet-top"><span>harbor_sales_2024.xlsx</span></div>
        <table>
          <thead><tr><th /><th>A</th><th>B</th><th>C</th><th>D</th><th>E</th></tr>
            <tr className="lp-sheet-head"><th>1</th><td>Order Date</td><td>Region</td><td>Product</td><td>Revenue</td><td>Units</td></tr></thead>
          <tbody>{SHEET.map((r, i) => <tr key={i}><th>{i + 2}</th>{r.map((c, j) => <td key={j} className={j >= 3 ? 'num' : ''}>{c}</td>)}</tr>)}</tbody>
        </table>
        <div className="lp-sheet-tabs"><span>Summary</span><span data-on="true">Data</span><span>Data dictionary</span><span>Cleaning report</span><span>Charts</span></div>
      </div>
      <pre className="lp-code" aria-label="Power Query script">{`let
    FeedUrl = "${origin}/api/feed/…csv",
    Token = "PASTE_TOKEN_HERE",
    Source = Csv.Document(Web.Contents(FeedUrl,
        [Headers = [Authorization = "Bearer " & Token]]),
        [Delimiter = ",", Columns = 5, Encoding = 65001]),
    Typed = Table.TransformColumnTypes(
        Table.PromoteHeaders(Source),
        {{"Order Date", type date}, {"Revenue", Currency.Type}, …})
in
    Typed`}</pre>
    </div>
  );
}

export function TrustPanel() {
  const checks = ['Group totals add up to the grand total', 'Shares add up to 100%', 'Rows in = rows used + rows skipped', 'DuckDB result equals Pandas result'];
  return (
    <div className="lp-card lp-trust">
      <ol className="lp-pipe" aria-label="How a figure is checked">
        <li><span>1</span><strong>Your data</strong><span className="xs muted">cleaned version</span></li>
        <li><span>2</span><strong>Pandas</strong><span className="xs muted">calculates the figure</span></li>
        <li><span>3</span><strong>DuckDB</strong><span className="xs muted">recalculates it with SQL</span></li>
        <li data-end="true"><span>4</span><strong>They agree?</strong><span className="xs muted">shown · otherwise hidden</span></li>
      </ol>
      <div className="lp-calc">
        <div className="lp-calc-head">How this was calculated <Badge tone="success">verified by duckdb</Badge></div>
        <dl>
          <dt>Formula</dt><dd>Sum of Revenue grouped by Region</dd>
          <dt>Filters</dt><dd>Order Date between 2024-01-01 and 2024-12-31</dd>
          <dt>Rows</dt><dd className="num">{formatInteger(S.orders)} in · {formatInteger(S.orders)} used · 0 skipped</dd>
        </dl>
        <ul className="lp-checks">{checks.map((c) => <li key={c}><CheckCircle2 size={14} /> {c}</li>)}</ul>
        <pre>{`SELECT "region", SUM("revenue") AS value
FROM data
WHERE "order_date" BETWEEN '2024-01-01' AND '2024-12-31'
GROUP BY "region" ORDER BY value DESC`}</pre>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ small pieces */

export function MiniChart({ kind, data, module }) {
  useThemeColors(); // re-render when the theme changes, so the area colour below is re-read
  const color = cssVar(`--m-${module}`) || '#2563eb';
  const rows = data.map((v, i) => ({ i, v }));
  const common = { data: rows, margin: { top: 4, right: 2, bottom: 0, left: 2 } };
  return (
    <div className="lp-mini-chart" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        {kind === 'bars' ? (
          <BarChart {...common} barCategoryGap="22%"><Bar dataKey="v" fill={color} radius={[3, 3, 0, 0]} isAnimationActive={false} /></BarChart>
        ) : kind === 'area' ? (
          <AreaChart {...common}><Area dataKey="v" type="monotone" stroke={color} strokeWidth={2} fill={color} fillOpacity={0.14} isAnimationActive={false} dot={false} /></AreaChart>
        ) : (
          <LineChart {...common}><Line dataKey="v" type="monotone" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

export function DropzoneMini() {
  return (
    <div className="lp-step-visual lp-drop" aria-hidden="true">
      <span className="lp-file"><b>XLSX</b> harbor_sales_2024.xlsx <span className="muted">· 612 KB</span></span>
      <span className="xs muted">or drop a file here</span>
    </div>
  );
}
export function StepperMini() {
  return <div className="lp-step-visual" aria-hidden="true"><Stepper stage="done" /></div>;
}
export function AskMini() {
  return (
    <div className="lp-step-visual" aria-hidden="true">
      <span className="askbar lp-askbar"><Search size={14} className="askbar-icon" /><span className="lp-typed">top 5 products by revenue in 2024</span></span>
      <span className="answer-text" style={{ fontSize: 14 }}>Desk has the highest total revenue: {fmt(S.byProduct.rows[0][1])}</span>
    </div>
  );
}

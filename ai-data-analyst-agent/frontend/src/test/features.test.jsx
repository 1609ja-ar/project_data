import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import { ThemeProvider } from '../context/ThemeContext.jsx';
import { ToastProvider } from '../components/ui/index.js';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock('../services/api.js', () => ({ default: apiMock, setAuthLostHandler: vi.fn() }));

const { default: Ask } = await import('../pages/app/Ask.jsx');
const { default: SharedDashboard } = await import('../pages/SharedDashboard.jsx');
const { default: KpiCard } = await import('../components/dashboard/KpiCard.jsx');
const { default: Tile } = await import('../components/dashboard/Tile.jsx');

const MONEY = { dtype: 'decimal', semantic_type: 'currency', currency: 'USD' };
const DATASETS = { items: [{ id: 'd1', filename: 'sales.csv', active_version_id: 'v1' }] };
const BAR_TILE = {
  id: 'ask', kind: 'custom', title: 'Total Revenue by Region', subtitle: '', dimension: 'region', how_calculated: null,
  chart: { spec: { type: 'horizontal_bar', x: 'region', y: 'value' }, columns: [{ key: 'region', label: 'Region', dtype: 'string' }, { key: 'value', label: 'Sum of Revenue', ...MONEY }], rows: [['North', 900], ['South', 300]] },
};

function wrap(ui, path, route = '/x') {
  return render(<MemoryRouter initialEntries={[path]}><ThemeProvider><ToastProvider><Routes><Route path={route} element={ui} /></Routes></ToastProvider></ThemeProvider></MemoryRouter>);
}

beforeEach(() => { Object.values(apiMock).forEach((f) => f.mockReset()); });

test('ask answers a question from the topbar and can pin the chart to the dashboard', async () => {
  const user = userEvent.setup();
  apiMock.get.mockImplementation((url) => Promise.resolve({ data: url === '/datasets' ? DATASETS : url.endsWith('/suggestions') ? { items: ['Monthly total revenue'] } : { items: [] } }));
  apiMock.post.mockImplementation((url) => Promise.resolve({ data: url === '/ask'
    ? { analysis_id: 'a1', question: 'revenue by region', answer: 'North has the highest total revenue: $900.00 (75.0% of the total).',
      interpretation: 'Total Revenue by Region (top 15)', chart_type: 'horizontal_bar', plan: { operation: 'top_n', group_by: ['region'] }, tile: BAR_TILE, ignored: ['atlantis'], source: 'rules' }
    : { id: 'p1' } }));
  wrap(<Ask />, '/app/ask?dataset=d1&q=revenue%20by%20region', '/app/ask');
  expect(await screen.findByText('North has the highest total revenue: $900.00 (75.0% of the total).')).toBeInTheDocument();
  expect(apiMock.post).toHaveBeenCalledWith('/ask', { dataset_id: 'd1', question: 'revenue by region' });
  expect(screen.getByText('Not understood: atlantis')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Pin to dashboard' }));
  await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/analytics/d1/dashboard/tiles',
    { title: 'Total Revenue by Region (top 15)', chart_type: 'horizontal_bar', plan: { operation: 'top_n', group_by: ['region'] } }));
  expect(await screen.findByRole('button', { name: 'On dashboard' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Monthly total revenue' })).toBeInTheDocument();
});

test('a KPI with a target shows the backend progress, and the target can be set', async () => {
  const user = userEvent.setup();
  const onGoal = vi.fn();
  const kpi = { id: 'primary', key: 'revenue:sum', label: 'Total Revenue', value: 150, column: { key: 'value', ...MONEY }, change: null, spark: [], how_calculated: null,
    goal: { target: 200, progress: 0.75, gap: -50, direction: 'at_least' } };
  wrap(<KpiCard kpi={kpi} onGoal={onGoal} />, '/x');
  expect(screen.getByText('75%')).toBeInTheDocument();
  expect(screen.getByText(/of \$200\.00 target/)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Set a target for Total Revenue' }));
  const input = screen.getByLabelText('Target for Total Revenue');
  await user.clear(input);
  await user.type(input, '250');
  await user.click(screen.getByRole('button', { name: 'Save' }));
  expect(onGoal).toHaveBeenCalledWith('revenue:sum', 250);
});

test('the trend tile offers a forecast view when the backend sends one', async () => {
  const user = userEvent.setup();
  const tile = {
    id: 'trend', kind: 'trend', title: 'Total Revenue by month', subtitle: '6 months', how_calculated: null,
    chart: { spec: { type: 'line', x: 'period', y: 'value' },
      columns: [{ key: 'period', label: 'Month', dtype: 'string', semantic_type: 'period' }, { key: 'period_start', label: 'Start', dtype: 'date' }, { key: 'value', label: 'Revenue', ...MONEY }, { key: 'growth', label: 'Growth', dtype: 'float' }, { key: 'partial', label: 'Partial', dtype: 'boolean' }],
      rows: [1, 2, 3, 4, 5, 6].map((m) => [`2024-0${m}`, `2024-0${m}-01`, 100 * m, null, false]) },
    forecast: { method: 'Linear trend', level: 0.8, basis: 6, grain: 'month', r2: 1, points: [{ period: '2024-07', value: 700, low: 690, high: 710 }] },
  };
  wrap(<Tile tile={tile} />, '/x');
  await user.click(screen.getByRole('button', { name: 'Forecast' }));
  expect(screen.getByRole('img', { name: /1-period forecast/ })).toBeInTheDocument();
  expect(screen.getByText(/Projection from 6 complete months/)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'View Total Revenue by month forecast in 3D' }));
  expect(within(await screen.findByRole('dialog')).getAllByText(/Recorded 6 complete months, then the projection to/).length).toBeGreaterThan(0);
});

test('a shared link shows the snapshot read-only, without calculation details', async () => {
  apiMock.get.mockResolvedValue({ data: {
    title: 'For the team', dataset_name: 'sales.csv', created_at: '2026-10-24T10:00:00Z', expires_at: '2026-10-31T10:00:00Z', filters: ['Region in South'],
    snapshot: { kpis: [{ id: 'primary', key: 'revenue:sum', label: 'Total Revenue', value: 1234.5, column: { key: 'value', ...MONEY }, change: null, spark: [] }],
      tiles: [{ ...BAR_TILE, kind: 'breakdown' }], custom_tiles: [], dimensions: [], rows_in_view: 10, row_count: 40, view_bounds: null, dataset_version: 1 },
  } });
  wrap(<SharedDashboard />, '/s/shr_abc', '/s/:token');
  expect(await screen.findByRole('heading', { name: 'For the team' })).toBeInTheDocument();
  expect(apiMock.get).toHaveBeenCalledWith('/public/share/shr_abc');
  expect(screen.getByText('$1,234.50')).toBeInTheDocument();
  expect(screen.getByText('Region in South')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /How .* calculated/ })).not.toBeInTheDocument();
  expect(within(screen.getByText('Total Revenue').closest('.kpi')).queryByRole('button', { name: /Set a target/ })).not.toBeInTheDocument();
});

test('clicking a KPI icon opens the 3D change moment with the real figures', async () => {
  const user = userEvent.setup();
  const kpi = { id: 'primary', key: 'revenue:sum', label: 'Total Revenue', value: 150, column: { key: 'value', ...MONEY }, how_calculated: null, spark: [],
    change: { pct: 0.25, current: 125, previous: 100, period: '2024-06', previous_period: '2024-05', grain: 'month' } };
  wrap(<KpiCard kpi={kpi} />, '/x');
  await user.click(screen.getByRole('button', { name: 'Show Total Revenue change in 3D' }));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getAllByText(/\$125\.00 in .*, up 25(\.0)?% from \$100\.00/).length).toBeGreaterThan(0);
  expect(within(dialog).getByRole('button', { name: 'Replay' })).toBeInTheDocument();
});

test('a KPI without a previous period has no 3D button', () => {
  const kpi = { id: 'primary', key: 'revenue:sum', label: 'Total Revenue', value: 150, column: { key: 'value', ...MONEY }, how_calculated: null, spark: [], change: null };
  wrap(<KpiCard kpi={kpi} />, '/x');
  expect(screen.queryByRole('button', { name: /in 3D/ })).not.toBeInTheDocument();
});

test('cleaning replay opens with the dataset counts', async () => {
  const user = userEvent.setup();
  const { default: CleaningReplay } = await import('../components/CleaningReplay.jsx');
  wrap(<CleaningReplay counts={{ rows_before: 1200, rows_removed: 30, cells_changed: 85 }} />, '/x');
  await user.click(screen.getByRole('button', { name: 'Replay cleaning in 3D' }));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getAllByText(/1,200 rows read, 30 removed, 85 values fixed. Blocks are scaled/).length).toBeGreaterThan(0);
});

test('SQL is no longer in the main menu but its page stays reachable', async () => {
  const { NAV, MODULES } = await import('../layouts/nav.js');
  expect(NAV.some((i) => i.to === '/app/sql')).toBe(false);
  expect(MODULES.sql).toBeDefined();
});

test('download clean data: format choice, personal columns left out, real request', async () => {
  const user = userEvent.setup();
  const { CleanDownloadDialog } = await import('../components/CleanDownload.jsx');
  const schema = [
    { key: 'order_id', display_name: 'Order ID', dtype: 'string', semantic_type: 'id' },
    { key: 'customer_email', display_name: 'Customer Email', dtype: 'string', semantic_type: 'text' },
    { key: 'revenue', display_name: 'Revenue', dtype: 'decimal', semantic_type: 'currency' },
  ];
  apiMock.get.mockImplementation((url) => (url === '/datasets/d1'
    ? Promise.resolve({ data: { id: 'd1', filename: 'sales.csv', cleaning_counts: { rows_before: 10, rows_removed: 1, cells_changed: 4 },
      active_version: { version_number: 2, row_count: 9, schema, quality_score_before: 80, quality_score_after: 100 } } })
    : Promise.resolve({ data: new Blob(['x']), headers: { 'content-disposition': 'attachment; filename="sales_clean_v2.xlsx"', 'x-rows-exported': '9', 'x-columns-exported': '2' } })));
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:x');
  globalThis.URL.revokeObjectURL = vi.fn();
  wrap(<CleanDownloadDialog open datasetId="d1" onClose={() => {}} />, '/x');
  expect(await screen.findByText(/10 rows read, 1 removed, 4 values fixed/)).toBeInTheDocument();
  expect(screen.getByText(/“Customer Email” may hold personal data/)).toBeInTheDocument();
  await user.click(screen.getByRole('radio', { name: /Excel workbook/ }));
  await user.click(screen.getByRole('button', { name: 'Leave out personal' }));
  await user.click(screen.getByRole('button', { name: 'Download .xlsx' }));
  await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/datasets/d1/download',
    { params: { format: 'xlsx', columns: 'order_id,revenue' }, responseType: 'blob', timeout: 0 }));
  expect(await screen.findByText('Downloaded 9 rows × 2 columns')).toBeInTheDocument();
});

test('the Clean data page is in the menu', async () => {
  const { NAV } = await import('../layouts/nav.js');
  expect(NAV.find((i) => i.to === '/app/downloads')?.label).toBe('Clean data');
});

const PIVOT_SCHEMA = [
  { key: 'region', display_name: 'Region', dtype: 'string', semantic_type: 'category' },
  { key: 'product', display_name: 'Product', dtype: 'string', semantic_type: 'category' },
  { key: 'revenue', display_name: 'Revenue', dtype: 'decimal', semantic_type: 'currency', currency: 'USD', scale: 2 },
];
const USD = { key: 'value', label: 'Sum of Revenue', dtype: 'decimal', semantic_type: 'currency', currency: 'USD' };
const PIVOT = {
  row_fields: [{ key: 'region', label: 'Region', is_date: false }, { key: 'product', label: 'Product', is_date: false }],
  column_field: null, grain: null, empty: false,
  measures: [{ label: 'Sum of Revenue', aggregation: 'sum', column: USD, additive: true, rows_used: 40 }],
  columns: [], columns_partial: [], column_totals: [], grand_total: [1000],
  rows: [
    { path: ['North'], level: 0, subtotal: true, partial: false, totals: [600], cells: [] },
    { path: ['North', 'Desk'], level: 1, subtotal: false, partial: false, totals: [500], cells: [] },
    { path: ['North', 'Chair'], level: 1, subtotal: false, partial: false, totals: [100], cells: [] },
    { path: ['South'], level: 0, subtotal: true, partial: false, totals: [400], cells: [] },
    { path: ['South', 'Desk'], level: 1, subtotal: false, partial: false, totals: [400], cells: [] },
  ],
  rows_total_count: 3, rows_shown_count: 3, top_n: null, rows_in: 40, rows_used: 40, filters: [],
  verification: { checks: 9, passed: 9, engines: ['pandas', 'duckdb'] },
  how_calculated: { rows_total: 40, checks: [] },
};

test('pivot page: nested rows with subtotals, collapse, percentages and checks', async () => {
  const user = userEvent.setup();
  const { default: Pivot } = await import('../pages/app/Pivot.jsx');
  apiMock.get.mockImplementation((url) => Promise.resolve({ data: url === '/datasets/d1'
    ? { id: 'd1', filename: 'sales.csv', cleaning_status: 'done', active_version_id: 'v1', active_version: { schema: PIVOT_SCHEMA } }
    : url === '/datasets' ? DATASETS : {} }));
  apiMock.post.mockImplementation((url) => Promise.resolve({ data: url.endsWith('/pivot') ? PIVOT : { dimensions: [] } }));
  wrap(<Pivot />, '/app/pivot?dataset=d1', '/app/pivot');
  const table = await screen.findByRole('table', { name: /Sum of Revenue by Region, Product/ });
  await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/analytics/d1/pivot', expect.objectContaining({
    rows: ['region'], columns: 'product', measures: [{ column: 'revenue', aggregation: 'sum' }], filters: [],
  }), { timeout: 0 }));
  expect(within(table).getByText('$600.00')).toBeInTheDocument();
  expect(within(table).getAllByText('$1,000.00').length).toBeGreaterThan(0);
  expect(screen.getByText(/9 of 9 checks passed/)).toBeInTheDocument();
  // a subtotal row collapses its children
  expect(within(table).getByText('Chair')).toBeInTheDocument();
  await user.click(within(table).getByRole('button', { name: 'Collapse North' }));
  expect(within(table).queryByText('Chair')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Expand all' }));
  expect(within(table).getByText('Chair')).toBeInTheDocument();
  await user.click(screen.getByRole('radio', { name: '% of total' }));
  expect(within(table).getByText('60.0%')).toBeInTheDocument();
  expect(within(table).getByText('10.0%')).toBeInTheDocument();
  await user.click(screen.getByRole('radio', { name: '% of parent' }));
  expect(within(table).getByText('83.3%')).toBeInTheDocument(); // North / Desk = 500 of 600
});

test('pivot page: only the rows in view are drawn when there are thousands of rows', async () => {
  const { default: Pivot } = await import('../pages/app/Pivot.jsx');
  const many = { ...PIVOT, row_fields: [{ key: 'region', label: 'Region', is_date: false }],
    rows: Array.from({ length: 20000 }, (_, i) => ({ path: [`Row ${i}`], level: 0, subtotal: false, partial: false, totals: [i], cells: [] })),
    rows_total_count: 20000, rows_shown_count: 20000, grand_total: [199990000] };
  apiMock.get.mockImplementation((url) => Promise.resolve({ data: url === '/datasets/d1'
    ? { id: 'd1', filename: 'sales.csv', cleaning_status: 'done', active_version_id: 'v1', active_version: { schema: PIVOT_SCHEMA } }
    : url === '/datasets' ? DATASETS : {} }));
  apiMock.post.mockImplementation((url) => Promise.resolve({ data: url.endsWith('/pivot') ? many : { dimensions: [] } }));
  wrap(<Pivot />, '/app/pivot?dataset=d1', '/app/pivot');
  const table = await screen.findByRole('table');
  expect(within(table).getByText('Row 0')).toBeInTheDocument();
  expect(screen.getByText(/20,000 region groups/)).toBeInTheDocument();
  expect(table.querySelectorAll('tbody tr').length).toBeLessThan(80); // not 20,000
});

test('import from a Google Sheets link', async () => {
  const user = userEvent.setup();
  const { default: Upload } = await import('../pages/app/Upload.jsx');
  apiMock.post.mockResolvedValue({ data: { dataset: { id: 'd9', filename: 'Sales.csv', size_bytes: 1200, raw_row_count: 3, raw_column_count: 2 },
    raw_preview: { columns: [], rows: [] }, column_names: ['a', 'b'], sheets: null, cleaning_status: 'pending' } });
  apiMock.get.mockResolvedValue({ data: { id: 'd9', filename: 'Sales.csv', cleaning_status: 'running', cleaning_stage: 'cleaning' } });
  wrap(<Upload />, '/x');
  await user.click(screen.getByRole('radio', { name: 'Google Sheets or link' }));
  const url = 'https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit#gid=0';
  await user.type(screen.getByLabelText('Link'), url);
  expect(screen.getByText(/The tab open in the link/)).toBeInTheDocument();
  await user.type(screen.getByLabelText('Name (optional)'), 'Sales');
  await user.click(screen.getByRole('button', { name: 'Import' }));
  await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/datasets/import-url', { url, name: 'Sales' }, { timeout: 0 }));
  expect(await screen.findByText('Sales.csv')).toBeInTheDocument();
});

test('linked datasets can be refreshed from their source', async () => {
  const user = userEvent.setup();
  const { default: SourceLink } = await import('../components/SourceLink.jsx');
  const onRefreshed = vi.fn();
  apiMock.post.mockResolvedValue({ data: { changed: false } });
  wrap(<SourceLink dataset={{ id: 'd9', source: { kind: 'google_sheets', url: 'https://docs.google.com/x', fetched_at: '2026-10-25T10:00:00Z' } }} onRefreshed={onRefreshed} />, '/x');
  expect(screen.getByRole('link', { name: 'Google Sheets' })).toHaveAttribute('href', 'https://docs.google.com/x');
  await user.click(screen.getByRole('button', { name: 'Refresh' }));
  expect(apiMock.post).toHaveBeenCalledWith('/datasets/d9/refresh', null, { timeout: 0 });
  expect(await screen.findByText('No changes since the last import.')).toBeInTheDocument();
  expect(onRefreshed).toHaveBeenCalled();
});

test('password reset says plainly when the server cannot send email', async () => {
  const user = userEvent.setup();
  const { default: ForgotPassword } = await import('../pages/ForgotPassword.jsx');
  apiMock.post.mockResolvedValue({ data: { message: 'Email is not set up on this server, so nothing was sent. In development the reset link is printed in the backend console.', email: 'console' } });
  wrap(<ForgotPassword />, '/x');
  await user.type(screen.getByLabelText(/Email/), 'ana@example.com');
  await user.click(screen.getByRole('button', { name: 'Send reset link' }));
  expect(await screen.findByText(/Email is not set up on this server, so nothing was sent/)).toBeInTheDocument();
});

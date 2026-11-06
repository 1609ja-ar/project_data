import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import { ThemeProvider } from '../context/ThemeContext.jsx';
import { ToastProvider } from '../components/ui/index.js';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock('../services/api.js', () => ({ default: apiMock, setAuthLostHandler: vi.fn() }));

const { default: Reports } = await import('../pages/app/Reports.jsx');
const { default: ReportView } = await import('../pages/app/ReportView.jsx');
const { default: Insights } = await import('../pages/app/Insights.jsx');
const { default: Exports } = await import('../pages/app/Exports.jsx');

const MONEY = { dtype: 'decimal', semantic_type: 'currency', currency: 'USD' };

function wrap(path, routes) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider><ToastProvider><Routes>{routes}</Routes></ToastProvider></ThemeProvider>
    </MemoryRouter>,
  );
}

const DATASETS = { items: [{ id: 'd1', filename: 'sales.csv', active_version_id: 'v1' }] };
const REPORT = {
  id: 'r1', title: 'Q3 review', dataset_id: 'd1', dataset_name: 'sales.csv', version_number: 2, source: 'ai', provider: 'Groq', model: 'm',
  sections: ['summary', 'kpis', 'insights', 'quality'], created_at: '2026-10-23T10:00:00Z', unverified: ['999'], note: null,
  narrative: { executive_summary: 'Revenue reached $1,234.50, about 999 [unverified] above plan.', key_findings: ['North leads.'], recommendations: ['Review East.'], chart_notes: {} },
  facts: {
    dataset: { name: 'sales.csv', version: 2, rows: 10, rows_in_view: 10, columns: 3, view_bounds: { min: '2024-01-01', max: '2024-03-31' }, filters: [] },
    kpis: [{ id: 'primary', label: 'Total Revenue', value: 1234.5, column: { key: 'value', ...MONEY }, change: null }],
    charts: [], table: null,
    insights: [{ id: 'i1', type: 'trend', severity: 'important', headline: 'Revenue is rising', detail: 'Slope 10 per month.', caveats: [], next_checks: [], numbers: {} }],
    quality: { score_before: 60, score_after: 95, rows_before: 12, rows_after: 10, rows_removed: 2, cells_changed: 7, steps: [] },
    columns: [],
  },
};

beforeEach(() => {
  apiMock.get.mockReset();
  apiMock.post.mockReset();
});

test('report builder sends the chosen options and opens the saved report', async () => {
  const user = userEvent.setup();
  apiMock.get.mockImplementation((url) => Promise.resolve({ data: url === '/datasets' ? DATASETS : url === '/ai/providers' ? { active: 'groq' } : { items: [] } }));
  apiMock.post.mockResolvedValue({ data: REPORT });
  wrap('/app/reports?new=1&dataset=d1', <>
    <Route path="/app/reports" element={<Reports />} />
    <Route path="/app/reports/:id" element={<p>opened report</p>} />
  </>);
  await user.click(await screen.findByRole('checkbox', { name: /Column dictionary/ }));
  await user.type(screen.getByLabelText('Title (optional)'), 'Q3 review');
  await user.click(screen.getByRole('button', { name: 'Generate report' }));
  expect(await screen.findByText('opened report')).toBeInTheDocument();
  expect(apiMock.post).toHaveBeenCalledWith('/reports', expect.objectContaining({
    dataset_id: 'd1', title: 'Q3 review', use_ai: true, sections: ['summary', 'kpis', 'charts', 'insights', 'quality'],
  }), { timeout: 0 });
});

test('report view highlights numbers the AI could not verify', async () => {
  apiMock.get.mockResolvedValue({ data: REPORT });
  wrap('/app/reports/r1', <Route path="/app/reports/:id" element={<ReportView />} />);
  expect(await screen.findByRole('heading', { name: 'Q3 review' })).toBeInTheDocument();
  expect(screen.getByText('unverified', { selector: 'mark' })).toBeInTheDocument();
  expect(screen.getByText(/1 number in the AI text did not match/)).toBeInTheDocument();
  expect(screen.getByText('$1,234.50', { selector: '.rk-value' })).toBeInTheDocument();
  expect(screen.getByText('60 → 95')).toBeInTheDocument();
});

test('insights page summarises severities and shows the selected insight in detail', async () => {
  const user = userEvent.setup();
  const insights = {
    analysis_id: 'a1', dataset_version: 1, tests_run: 5, filters: ['None'], note: 'n', skipped: [],
    insights: [
      { id: 'i1', type: 'trend', severity: 'important', headline: 'Revenue is rising', detail: 'd1', evidence: { numbers: { slope: 10, r_squared: 0.9 }, columns: ['revenue', 'order_date'], filters: ['None'], rows_used: 10, rows_skipped: 0 }, how_calculated: null, suggested_chart_spec: null, caveats: [], possible_next_checks: ['Check seasonality.'] },
      { id: 'i2', type: 'top_contributor', severity: 'notable', headline: 'North contributes 61%', detail: 'd2', evidence: { numbers: { top_share: 0.61 }, columns: ['revenue', 'region'], filters: ['None'], rows_used: 10, rows_skipped: 0 }, how_calculated: null, suggested_chart_spec: null, caveats: ['Descriptive only.'], possible_next_checks: [] },
    ],
  };
  apiMock.get.mockImplementation((url) => Promise.resolve({ data: url.endsWith('/insights') ? insights : url === '/datasets' ? DATASETS : { id: 'd1', active_version: { schema: [] } } }));
  wrap('/app/insights?dataset=d1', <Route path="/app/insights" element={<Insights />} />);
  const detail = await screen.findByRole('heading', { level: 2, name: 'Revenue is rising' });
  expect(detail).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /North contributes 61%/ }));
  expect(screen.getByRole('heading', { level: 2, name: 'North contributes 61%' })).toBeInTheDocument();
  expect(screen.getByText('Descriptive only.')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Ask: total revenue by region/ })).toHaveAttribute('href', '/app/ask?dataset=d1&q=total%20revenue%20by%20region');
  await user.click(screen.getByRole('button', { name: /1 Act on/ }));     // severity card filters the list
  expect(screen.queryByRole('button', { name: /North contributes 61%/ })).not.toBeInTheDocument();
});

test('excel builder previews the chosen columns and rows', async () => {
  const user = userEvent.setup();
  const cols = [{ key: 'region', label: 'Region', dtype: 'string', semantic_type: 'category' }, { key: 'amount', label: 'Amount', ...MONEY }];
  apiMock.get.mockImplementation((url) => Promise.resolve({ data: url === '/datasets' ? DATASETS : { items: [] } }));
  apiMock.post.mockImplementation((url, body) => Promise.resolve({
    data: url.endsWith('/dashboard')
      ? { dimensions: [{ key: 'region', label: 'Region', values: ['North', 'South'] }], date_column: null }
      : { rows: 2, total_rows: 4, filters: [], columns: body.columns ? cols.filter((c) => body.columns.includes(c.key)) : cols,
        sample: [['North', 10.5], ['North', 20]].map((r) => (body.columns?.length === 1 ? [r[0]] : r)) },
  }));
  wrap('/app/exports?dataset=d1', <Route path="/app/exports" element={<Exports />} />);
  const preview = await screen.findByRole('table', { name: 'Export preview' });
  expect(within(preview).getByText('$10.50')).toBeInTheDocument();
  expect(screen.getByText('2 of 4 rows · 2 columns')).toBeInTheDocument();
  await user.click(screen.getByRole('checkbox', { name: /Amount/ }));
  await waitFor(() => expect(apiMock.post).toHaveBeenLastCalledWith('/exports/d1/preview', expect.objectContaining({ columns: ['region'] })));
  expect(screen.getByText('Summary')).toBeInTheDocument();                 // dashboard sheets are listed in the preview
});

test('a new token is filled into the Token line of the Power BI query, not the comment', async () => {
  const user = userEvent.setup();
  const mWeb = '// Replace PASTE_TOKEN_HERE with your export token (pbi_...).\nlet\n    Token = "PASTE_TOKEN_HERE",\n    Source = 1\nin\n    Source\n';
  apiMock.get.mockImplementation((url) => Promise.resolve({ data: url === '/datasets' ? DATASETS : url.startsWith('/powerbi/')
    ? { feed_url: 'http://localhost/api/feed/d1.csv', version_number: 1, columns: [], m_web: mWeb, m_file: '', dax: '' } : { items: [] } }));
  apiMock.post.mockResolvedValue({ data: { id: 't1', token: 'pbi_secretvalue', dataset_id: 'd1', token_prefix: 'pbi_secr' } });
  wrap('/app/exports?dataset=d1&tab=powerbi', <Route path="/app/exports" element={<Exports />} />);
  await user.click(await screen.findByRole('button', { name: 'Create token' }));
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Create token' }));
  const code = await screen.findByText(/Token = "pbi_secretvalue"/);
  expect(code.textContent).toContain('// Replace PASTE_TOKEN_HERE');             // the comment is left as written
  expect(code.textContent).not.toContain('Token = "PASTE_TOKEN_HERE"');
});

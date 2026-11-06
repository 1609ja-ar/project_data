import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import { ThemeProvider } from '../context/ThemeContext.jsx';
import { ToastProvider } from '../components/ui/index.js';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../services/api.js', () => ({ default: apiMock, setAuthLostHandler: vi.fn() }));

const { default: Dashboard } = await import('../pages/app/Dashboard.jsx');
const { default: Landing } = await import('../pages/Landing.jsx');

const MONEY = { dtype: 'decimal', semantic_type: 'currency', currency: 'USD' };
const details = { formula: 'Sum of Revenue', filters_applied: ['None'], rows_in: 4, rows_used: 4, rows_skipped: 0, engine: 'pandas', verified_by: 'duckdb', checks: [] };
const DASH = {
  dataset_version: 1, row_count: 4, rows_in_view: 4, measure: { key: 'revenue', label: 'Revenue' }, aggregation: 'sum',
  measures: [{ key: 'revenue', label: 'Revenue', default_aggregation: 'sum' }],
  date_column: { key: 'day', label: 'Day', dtype: 'date' }, date_bounds: { min: '2024-01-01', max: '2024-02-29' },
  view_bounds: { min: '2024-01-01', max: '2024-02-29' }, grain: 'month', grain_auto: true,
  dimensions: [{ key: 'region', label: 'Region', unique: 2, values: ['North', 'South'] }],
  filters_applied: [], skipped: [],
  kpis: [{
    id: 'primary', label: 'Total Revenue', value: 1234.5, column: { key: 'value', label: 'Sum of Revenue', ...MONEY }, rows_used: 4,
    how_calculated: details, spark: [{ period: '2024-01', value: 500, partial: false }, { period: '2024-02', value: 734.5, partial: false }],
    change: { pct: 0.469, current: 734.5, previous: 500, period: '2024-02', previous_period: '2024-01', grain: 'month' },
  }],
  tiles: [{
    id: 'by_region', kind: 'breakdown', title: 'Total Revenue by Region', subtitle: '2 values', dimension: 'region', rows_used: 4, warnings: [],
    how_calculated: details, other: null, groups_total: 2,
    chart: {
      spec: { type: 'horizontal_bar', x: 'region', y: 'value' },
      columns: [{ key: 'region', label: 'Region', dtype: 'string' }, { key: 'value', label: 'Sum of Revenue', ...MONEY }, { key: 'rows', label: 'Rows used', dtype: 'integer' }],
      rows: [['North', 900.25, 2], ['South', 334.25, 2]],
    },
  }],
};

function wrap(ui, path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider><ToastProvider>
        <Routes><Route path="/app/dashboard" element={ui} /><Route path="/" element={ui} /></Routes>
      </ToastProvider></ThemeProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiMock.get.mockReset();
  apiMock.post.mockReset();
  apiMock.get.mockImplementation((url) => Promise.resolve(url === '/datasets'
    ? { data: { items: [{ id: 'd1', filename: 'sales.csv', active_version_id: 'v1' }] } }
    : { data: { id: 'd1', filename: 'sales.csv', cleaning_status: 'done', active_version_id: 'v1' } }));
  apiMock.post.mockResolvedValue({ data: DASH });
});

test('dashboard shows backend KPI values, period change and tiles', async () => {
  wrap(<Dashboard />, '/app/dashboard?dataset=d1');
  expect(await screen.findByText('$1,234.50')).toBeInTheDocument();
  expect(screen.getByText('46.9%')).toBeInTheDocument();
  expect(screen.getByText('Feb 2024 vs Jan 2024')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Total Revenue by Region' })).toBeInTheDocument();
  expect(apiMock.post).toHaveBeenCalledWith('/analytics/d1/dashboard', expect.objectContaining({ filters: [], date_from: null }));
});

test('table view of a tile lists the same backend values', async () => {
  const user = userEvent.setup();
  wrap(<Dashboard />, '/app/dashboard?dataset=d1');
  await user.click(await screen.findByRole('radio', { name: 'Table' }));
  expect(screen.getByRole('radio', { name: '3D' })).toBeInTheDocument();     // a bar-per-value chart offers a 3D view
  const table = screen.getByRole('table', { name: 'Total Revenue by Region' });
  expect(within(table).getByText('$900.25')).toBeInTheDocument();
  expect(within(table).getByText('$334.25')).toBeInTheDocument();
});

test('a category filter is sent to the backend and shown as a removable chip', async () => {
  const user = userEvent.setup();
  wrap(<Dashboard />, '/app/dashboard?dataset=d1');
  await user.click(await screen.findByRole('button', { name: /Region/ }));
  await user.click(screen.getByRole('checkbox', { name: 'North' }));
  await user.click(screen.getByRole('button', { name: 'Apply' }));
  await waitFor(() => expect(apiMock.post).toHaveBeenLastCalledWith('/analytics/d1/dashboard',
    expect.objectContaining({ filters: [{ column: 'region', values: ['North'] }] })));
  expect(screen.getByRole('button', { name: 'Remove Region filter' })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Remove Region filter' }));
  await waitFor(() => expect(apiMock.post).toHaveBeenLastCalledWith('/analytics/d1/dashboard', expect.objectContaining({ filters: [] })));
});

test('date preset is relative to the newest date in the data', async () => {
  const user = userEvent.setup();
  wrap(<Dashboard />, '/app/dashboard?dataset=d1');
  await user.selectOptions(await screen.findByRole('combobox', { name: 'Date range' }), '30d');
  await waitFor(() => expect(apiMock.post).toHaveBeenLastCalledWith('/analytics/d1/dashboard',
    expect.objectContaining({ date_from: '2024-01-31', date_to: '2024-02-29' })));
});

test('landing page labels its product visuals as sample data, with a static fallback when WebGL is missing', () => {
  wrap(<Landing />, '/');
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Your spreadsheets, turned into answers.');
  expect(screen.getAllByText('Sample data').length).toBeGreaterThanOrEqual(3);      // hero, tour, 3D feature
  expect(document.querySelector('canvas')).toBeNull();
  // The tour's dashboard uses the real KPI cards with the sample figures (regions sum to ₹6,21,500).
  expect(screen.getAllByText('₹6.2L').length).toBeGreaterThan(0);
});

test('the product tour switches views, and the Ask demo answers the chosen question', async () => {
  const user = userEvent.setup();
  wrap(<Landing />, '/');
  await user.click(screen.getByRole('tab', { name: /Ask/ }));
  expect(screen.getByRole('tab', { name: /Ask/ })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByText(/Desk has the highest total revenue: ₹2,36,170\.00 \(38\.0% of the total\)/)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Share of revenue by region' }));
  expect(screen.getByText(/North has the highest total revenue: ₹2,58,000\.00 \(41\.5% of the total\)/)).toBeInTheDocument();
  await user.keyboard('{ArrowRight}');
  await user.click(screen.getByRole('tab', { name: /Reports/ }));
  expect(screen.getByRole('heading', { name: 'Harbor sales 2024 review' })).toBeInTheDocument();
});

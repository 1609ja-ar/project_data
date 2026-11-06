import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider } from '../context/ThemeContext.jsx';
import { ToastProvider } from '../components/ui/index.js';
import ResultChart from '../components/ResultChart.jsx';
import ResultView from '../components/ResultView.jsx';

const columns = [
  { key: 'region', label: 'Region', dtype: 'string', semantic_type: 'category' },
  { key: 'year', label: 'Year', dtype: 'string', semantic_type: 'category' },
  { key: 'value', label: 'Sum of Amount', dtype: 'decimal', semantic_type: 'currency', currency: 'USD' },
];
const rows = [['North', '2023', 40.41], ['North', '2024', 10], ['South', '2023', 60.6], ['South', '2024', 5]];
const TYPES = ['bar', 'horizontal_bar', 'grouped_bar', 'stacked_bar', 'stacked_100_bar', 'line', 'area'];

function wrap(ui) {
  return render(<MemoryRouter><ThemeProvider><ToastProvider>{ui}</ToastProvider></ThemeProvider></MemoryRouter>);
}

describe.each(['light', 'dark'])('%s theme', (theme) => {
  beforeEach(() => localStorage.setItem('theme', theme));
  test.each(TYPES)('%s renders', (type) => {
    const spec = { type, x: 'region', y: 'value', ...(type.includes('grouped') || type.includes('stacked') ? { series: 'year' } : {}) };
    wrap(<ResultChart spec={spec} columns={columns} rows={rows} />);
    expect(document.documentElement.getAttribute('data-theme')).toBe(theme);
    expect(screen.getByRole('img', { name: new RegExp(type.replace(/_/g, ' ')) })).toBeInTheDocument();
  });
});

test('table view shows the same backend values as the chart', async () => {
  const user = userEvent.setup();
  wrap(<ResultView result={{ columns, rows, chart_suggestion: { type: 'grouped_bar', x: 'region', series: 'year', y: 'value' } }} />);
  await user.click(screen.getByRole('radio', { name: 'Table' }));
  expect(screen.getByText('$40.41')).toBeInTheDocument();
  expect(screen.getByText('$60.60')).toBeInTheDocument();
});

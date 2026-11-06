import { formatPeriod } from '../utils/format.js';
import { formatCell, formatCurrency, formatInteger, formatPercent, formatPercentFlexible } from '../utils/format.js';

test('currency keeps cents and sign', () => {
  expect(formatCurrency(-200, 'USD')).toMatch(/200\.00/);
  expect(formatCurrency(-200, 'USD')).toMatch(/-|−|\(/);
  expect(formatCurrency(1234.5, 'USD')).toMatch(/1,234\.50/);
});

test('percent formatting of backend ratios', () => {
  expect(formatPercent(0.125, 1)).toMatch(/12\.5\s?%/);
  expect(formatPercent(null)).toBe('n/a');
  expect(formatPercentFlexible(0.1)).toMatch(/^10\s?%$/);
  expect(formatPercentFlexible(0.125)).toMatch(/12\.5\s?%/);
});

test('formatCell uses semantic types and shows nulls as null', () => {
  expect(formatCell(null, { dtype: 'integer' })).toBeNull();
  expect(formatCell(0.05, { dtype: 'float', semantic_type: 'percent' })).toMatch(/^5\s?%$/);
  expect(formatCell('2024-01-05', { dtype: 'date' })).toBe('2024-01-05');
  expect(formatCell(false, { dtype: 'boolean' })).toBe('false');
  expect(formatInteger(1234567)).toBe('12,34,567'); // Indian grouping
});

test('period labels from the backend are shown as readable text', () => {
  expect(formatPeriod('2024-03')).toBe('Mar 2024');
  expect(formatPeriod('2024-Q2')).toBe('Q2 2024');
  expect(formatPeriod('2024-W09')).toBe('W9 2024');
  expect(formatPeriod('2024-03-05')).toBe('Mar 5, 2024');
  expect(formatPeriod('2024')).toBe('2024');
});

test('insight sentences drop test statistics but keep the practical figures', async () => {
  const { plainDetail, followUp } = await import('../pages/app/Insights.jsx');
  expect(plainDetail('A straight-line fit changes by $993.58 per month (69.9% of the average over the period; p = 2.15e-06, R² = 0.90).'))
    .toBe('A straight-line fit changes by $993.58 per month (69.9% of the average over the period).');
  expect(plainDetail('Average $339.24 for Desk vs $128.97 for Chair (Welch t-test, p = 4.7e-48; Cohen\'s d = 1.62; n = 239 and 237).'))
    .toBe('Average $339.24 for Desk vs $128.97 for Chair.');
  expect(followUp({ type: 'trend', evidence: { columns: ['order_date', 'revenue'] } })).toBe('revenue over time');
  expect(followUp({ type: 'top_contributor', evidence: { columns: ['revenue', 'region'] } })).toBe('total revenue by region');
  expect(followUp({ type: 'relationship', evidence: { columns: ['revenue', 'units'] } })).toBeNull();
});

test('money is shown in rupees with Indian grouping unless the column says otherwise', async () => {
  const { formatKpi, formatCompactValue, DEFAULT_CURRENCY } = await import('../utils/format.js');
  expect(DEFAULT_CURRENCY).toBe('INR');
  expect(formatCurrency(1234567.5)).toBe('₹12,34,567.50');
  expect(formatCurrency(-200)).toBe('-₹200.00');
  expect(formatCurrency(-0.001)).toBe('₹0.00'); // no minus sign on a value that rounds to zero
  const money = { dtype: 'decimal', semantic_type: 'currency' }; // no currency recorded -> rupees
  expect(formatCell(2500.5, money)).toBe('₹2,500.50');
  expect(formatKpi(99999, money)).toBe('₹99,999.00');
  expect(formatKpi(250000, money)).toBe('₹2.5L');
  expect(formatCompactValue(12345678, money)).toBe('₹1.2Cr');
  expect(formatCell(10, { ...money, currency: 'USD' })).toBe('$10.00'); // dollar data stays in dollars
});

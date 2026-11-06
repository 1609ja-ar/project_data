// Sample data for the landing page's product visuals. Everything here is derived from the same monthly
// figures, so totals, shares and changes agree with each other. It is demonstration data (the page says so);
// the real app gets these numbers from the verified backend.
const MONEY = { dtype: 'decimal', semantic_type: 'currency', currency: 'INR' };

export const MONTHS = ['2024-01', '2024-02', '2024-03', '2024-04', '2024-05', '2024-06', '2024-07', '2024-08', '2024-09', '2024-10', '2024-11', '2024-12'];

export const REGIONS = {
  North: [17200, 18100, 19400, 18800, 20300, 21900, 21200, 22800, 24100, 23600, 25900, 24700],
  West: [10100, 10800, 11300, 11000, 12200, 12900, 12600, 13700, 14400, 14100, 15600, 14900],
  South: [8200, 8500, 9100, 8800, 9400, 10100, 9800, 10600, 11200, 10900, 12100, 11700],
  East: [5900, 6300, 6700, 6400, 7000, 7500, 7300, 7900, 8400, 8200, 9100, 8800],
};
const ORDERS = [352, 371, 398, 384, 417, 446, 433, 468, 491, 482, 523, 504];

export const REGION_ORDER = Object.keys(REGIONS);
export const monthTotals = MONTHS.map((_, i) => REGION_ORDER.reduce((s, r) => s + REGIONS[r][i], 0));
export const total = monthTotals.reduce((s, v) => s + v, 0);
export const orders = ORDERS.reduce((s, v) => s + v, 0);
const regionTotals = REGION_ORDER.map((r) => REGIONS[r].reduce((s, v) => s + v, 0));

const moneyCol = (label) => ({ key: 'value', label, ...MONEY });
const pct = (a, b) => (a - b) / Math.abs(b);
const last = monthTotals.length - 1;

export const trend = {
  columns: [
    { key: 'period', label: 'Month', dtype: 'string', semantic_type: 'period' }, { key: 'period_start', label: 'Start', dtype: 'date' },
    moneyCol('Revenue'), { key: 'growth', label: 'Growth', dtype: 'float' }, { key: 'partial', label: 'Partial', dtype: 'boolean' },
  ],
  rows: MONTHS.map((m, i) => [m, `${m}-01`, monthTotals[i], i ? pct(monthTotals[i], monthTotals[i - 1]) : null, false]),
};

export const byRegion = {
  columns: [{ key: 'region', label: 'Region', dtype: 'string' }, moneyCol('Revenue'), { key: 'share', label: 'Share', dtype: 'float', semantic_type: 'percent' }],
  rows: REGION_ORDER.map((r, i) => [r, regionTotals[i], regionTotals[i] / total]).sort((a, b) => b[1] - a[1]),
};

// Products split each region's revenue by fixed shares; the last product takes the remainder so totals match.
const PRODUCT_SHARE = { Desk: 0.38, Chair: 0.29, Shelf: 0.21 };
const productValues = {};
let allocated = 0;
Object.entries(PRODUCT_SHARE).forEach(([p, s]) => { productValues[p] = Math.round(total * s); allocated += productValues[p]; });
productValues.Lamp = total - allocated;
export const byProduct = {
  columns: [{ key: 'product', label: 'Product', dtype: 'string' }, moneyCol('Revenue')],
  rows: Object.entries(productValues).sort((a, b) => b[1] - a[1]),
};

export const split = {
  columns: [{ key: 'period', label: 'Month', dtype: 'string', semantic_type: 'period' }, { key: 'region', label: 'Region', dtype: 'string' }, moneyCol('Revenue')],
  rows: MONTHS.flatMap((m, i) => REGION_ORDER.map((r) => [m, r, REGIONS[r][i]])),
};

const kpiBase = (id, key, label, value, col, series) => ({
  id, key, label, value, column: col, how_calculated: null, goal: null,
  change: { pct: pct(series[last], series[last - 1]), current: series[last], previous: series[last - 1], period: MONTHS[last], previous_period: MONTHS[last - 1], grain: 'month' },
  spark: series.map((v, i) => ({ period: MONTHS[i], value: v, partial: false })),
});
const avgSeries = monthTotals.map((v, i) => v / ORDERS[i]);

export const kpis = [
  { ...kpiBase('primary', 'revenue:sum', 'Total Revenue', total, moneyCol('Revenue'), monthTotals), goal: { target: 650000, progress: total / 650000, gap: total - 650000, direction: 'at_least' } },
  kpiBase('records', 'records:count', 'Orders', orders, { key: 'value', label: 'Orders', dtype: 'integer' }, ORDERS),
  kpiBase('average', 'revenue:mean', 'Average order', total / orders, { ...moneyCol('Average order') }, avgSeries),
  kpiBase('second', 'units:sum', 'Units sold', Math.round(orders * 2.4), { key: 'value', label: 'Units', dtype: 'integer' }, ORDERS.map((o) => Math.round(o * 2.4))),
];

// Least-squares line over the 12 months, 3 periods ahead with an 80% range: only for this demo chart.
export function demoForecast() {
  const n = monthTotals.length;
  const xs = monthTotals.map((_, i) => i);
  const xb = (n - 1) / 2;
  const yb = total / n;
  const sxx = xs.reduce((s, x) => s + (x - xb) ** 2, 0);
  const slope = xs.reduce((s, x, i) => s + (x - xb) * (monthTotals[i] - yb), 0) / sxx;
  const icpt = yb - slope * xb;
  const sse = xs.reduce((s, x, i) => s + (monthTotals[i] - (icpt + slope * x)) ** 2, 0);
  const sd = Math.sqrt(sse / (n - 2));
  const t80 = 1.372; // t(0.9, 10)
  return {
    method: 'Linear trend', level: 0.8, basis: n, grain: 'month', r2: 0.97,
    points: [1, 2, 3].map((h) => {
      const x0 = n - 1 + h;
      const y = icpt + slope * x0;
      const half = t80 * sd * Math.sqrt(1 + 1 / n + (x0 - xb) ** 2 / sxx);
      return { period: `2025-0${h}`, value: y, low: y - half, high: y + half };
    }),
  };
}

export const seriesOrder = REGION_ORDER;
export const MONEY_COL = moneyCol;

// A tiny file before and after cleaning. The cleaned table is the real output of the app's cleaning pipeline for
// this exact file (tests/test_cleaning.py keeps the same file honest); `changed` marks the cells that differ.
export const messy = {
  columns: ['Order ID', 'Region', 'Order Date', 'Amount'],
  rows: [['00101', ' north', '05/01/2024', '₹1,234.50'], ['00102', 'NORTH', '13/02/2024', '(200.00)'], ['00102', 'NORTH', '13/02/2024', '(200.00)'],
    ['00104', 'South ', '2024-03-01', '1,000.00'], ['00105', 'south', '15/03/2024', 'Rs 250.00'], ['Total', '', '', '₹2,084.50']],
};
export const cleaned = {
  columns: ['Order ID', 'Region', 'Order Date', 'Amount'],
  rows: [['00101', 'North', '2024-01-05', '₹1,234.50'], ['00102', 'North', '2024-02-13', '-₹200.00'], ['00104', 'South', '2024-03-01', '₹1,000.00'],
    ['00105', 'South', '2024-03-15', '₹250.00']],
  changed: [[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3], [2, 1], [2, 3], [3, 1], [3, 2], [3, 3]],
};

// Use-case cards: made-up numbers, each shown figure derived from its own series, with the question that produces it.
export const useCases = [
  { module: 'dashboard', title: 'Sales', question: 'Top 4 products by revenue in 2024', kpi: '₹6.2L', label: 'Revenue', kind: 'bars', data: [38, 29, 21, 12] },
  { module: 'datasets', title: 'Finance', question: 'Monthly expenses this year', kpi: '-11.5%', label: 'Dec vs Jan', kind: 'area', data: [52, 49, 55, 53, 51, 50, 54, 52, 49, 48, 47, 46] },
  { module: 'upload', title: 'Operations', question: 'On-time delivery by month', kpi: '94%', label: 'latest month', kind: 'line', data: [88, 90, 89, 92, 91, 93, 92, 94, 93, 95, 94, 94] },
  { module: 'reports', title: 'Marketing', question: 'Share of leads by channel', kpi: '41%', label: 'top channel', kind: 'bars', data: [41, 27, 19, 13] },
  { module: 'insights', title: 'HR', question: 'Headcount by department', kpi: '312', label: 'people', kind: 'bars', data: [96, 74, 61, 48, 33] },
  { module: 'exports', title: 'Education', question: 'Average score by class', kpi: '77.1', label: 'avg score', kind: 'line', data: [71, 74, 73, 76, 78, 77, 80, 79, 82, 81] },
];

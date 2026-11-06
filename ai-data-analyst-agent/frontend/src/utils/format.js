// The single number/date formatter for the whole app. Formats only — never recalculates.
// Indian numbering everywhere (12,34,567.50; ₹1.2Cr; ₹2.5L), whatever the browser's language.
const LOCALE = 'en-IN';
// Money columns without a known currency are shown in rupees (the backend applies the same default).
export const DEFAULT_CURRENCY = 'INR';
const cache = new Map();

function nf(key, opts) {
  if (!cache.has(key)) cache.set(key, new Intl.NumberFormat(LOCALE, opts));
  return cache.get(key);
}

export function isNullish(v) {
  return v === null || v === undefined || (typeof v === 'number' && Number.isNaN(v));
}

function toNumber(v) {
  if (typeof v === 'number') return v;
  if (typeof v === 'string' && v.trim() !== '' && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

export function formatNumber(v, { maxDecimals = 2 } = {}) {
  const n = toNumber(v);
  if (n === null) return isNullish(v) ? '—' : String(v);
  return nf(`n${maxDecimals}`, { maximumFractionDigits: maxDecimals }).format(n);
}

export function formatInteger(v) {
  const n = toNumber(v);
  if (n === null) return isNullish(v) ? '—' : String(v);
  return nf('int', { maximumFractionDigits: 0 }).format(n);
}

export function formatCurrency(v, currency = DEFAULT_CURRENCY) {
  const n = toNumber(v);
  if (n === null) return isNullish(v) ? '—' : String(v);
  try {
    return nf(`c${currency}`, { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'negative' }).format(n);
  } catch {
    return `${nf('n2f', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)} ${currency}`;
  }
}

// Expects a ratio already computed by the backend (0.25 -> 25%).
export function formatPercent(ratio, decimals = 1) {
  const n = toNumber(ratio);
  if (n === null) return 'n/a';
  return nf(`p${decimals}`, { style: 'percent', minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(n);
}

// Ratio -> percent with only the decimals the value needs (0.125 -> 12.5%, 0.1 -> 10%).
export function formatPercentFlexible(ratio) {
  const n = toNumber(ratio);
  if (n === null) return 'n/a';
  return nf('pflex', { style: 'percent', minimumFractionDigits: 0, maximumFractionDigits: 4 }).format(n);
}

export function formatCompact(v) {
  const n = toNumber(v);
  if (n === null) return isNullish(v) ? '—' : String(v);
  return nf('compact', { notation: 'compact', maximumFractionDigits: 1 }).format(n);
}

// Short axis/KPI label that keeps the unit: ₹1.2Cr / ₹2.5L for money, 1.2Cr otherwise, 25% for ratios.
export function formatCompactValue(v, col = {}) {
  const n = toNumber(v);
  if (n === null) return isNullish(v) ? '—' : String(v);
  if (col.semantic_type === 'percent') return formatPercent(n, 0);
  if (col.semantic_type === 'currency') {
    try {
      return nf(`cc${col.currency || DEFAULT_CURRENCY}`, { style: 'currency', currency: col.currency || DEFAULT_CURRENCY, notation: 'compact', maximumFractionDigits: 1 }).format(n);
    } catch {
      return formatCompact(n);
    }
  }
  return formatCompact(n);
}

// KPI headline: exact below 1 lakh (so it matches tables), compact above.
export function formatKpi(v, col = {}) {
  const n = toNumber(v);
  if (n === null) return isNullish(v) ? '—' : String(v);
  if (Math.abs(n) >= 100000) return formatCompactValue(n, col);
  if (col.semantic_type === 'currency') return formatCurrency(n, col.currency || DEFAULT_CURRENCY);
  if (col.semantic_type === 'percent') return formatPercent(n);
  if (col.dtype === 'integer') return formatInteger(n);
  return formatNumber(n, { maxDecimals: 2 });
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// Backend period labels (2024-03, 2024-Q1, 2024-W09, 2024-03-05, 2024) -> readable text. Display only.
export function formatPeriod(p) {
  if (typeof p !== 'string') return p;
  let m = p.match(/^(\d{4})-(\d{2})$/);
  if (m) return `${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
  m = p.match(/^(\d{4})-Q([1-4])$/);
  if (m) return `Q${m[2]} ${m[1]}`;
  m = p.match(/^(\d{4})-W(\d{2})$/);
  if (m) return `W${Number(m[2])} ${m[1]}`;
  m = p.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
  return p;
}

export function formatBytes(bytes) {
  const n = toNumber(bytes);
  if (n === null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${formatNumber(n / 1024, { maxDecimals: 1 })} KB`;
  return `${formatNumber(n / (1024 * 1024), { maxDecimals: 1 })} MB`;
}

export function formatDate(v) {
  if (isNullish(v)) return '—';
  const d = v instanceof Date ? v : new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toISOString().slice(0, 10);
}

export function formatDateTime(v) {
  if (isNullish(v)) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return new Intl.DateTimeFormat(LOCALE, { dateStyle: 'medium', timeStyle: 'short' }).format(d);
}

export function formatRelative(v) {
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return '';
  const diff = (Date.now() - d.getTime()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto' });
  if (diff < 60) return rtf.format(-Math.round(diff), 'second');
  if (diff < 3600) return rtf.format(-Math.round(diff / 60), 'minute');
  if (diff < 86400) return rtf.format(-Math.round(diff / 3600), 'hour');
  return rtf.format(-Math.round(diff / 86400), 'day');
}

/**
 * Format a value using a column's semantic type from the backend schema.
 * dtype: integer|float|decimal|string|date|datetime|boolean ; semantic: currency|percent|id|...
 */
export function formatCell(v, col = {}) {
  if (isNullish(v)) return null;
  if (col.semantic_type === 'currency') return formatCurrency(v, col.currency || DEFAULT_CURRENCY);
  if (col.semantic_type === 'percent') return col.decimals != null ? formatPercent(v, col.decimals) : formatPercentFlexible(v);
  if (col.semantic_type === 'period') return formatPeriod(v);
  if (col.dtype === 'boolean') return v ? 'true' : 'false';
  if (col.dtype === 'date') return formatDate(v);
  if (col.dtype === 'datetime') return String(v).replace('T', ' ').slice(0, 19);
  if (col.dtype === 'integer') return formatInteger(v);
  if (col.dtype === 'float' || col.dtype === 'decimal') return formatNumber(v, { maxDecimals: 4 });
  return String(v);
}

export function isNumericCol(col = {}) {
  return ['integer', 'float', 'decimal'].includes(col.dtype);
}

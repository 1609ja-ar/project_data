import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from 'recharts';
import { Badge, Drawer, Segmented } from './ui/index.js';
import useThemeColors from '../hooks/useThemeColors.js';
import { DEFAULT_CURRENCY, formatCurrency, formatInteger, formatNumber, formatPercent } from '../utils/format.js';

const STAT_LABELS = {
  sum: 'Sum', mean: 'Mean (average)', median: 'Median (middle value)', min: 'Minimum', max: 'Maximum', std: 'Standard deviation',
  q1: 'Lower quartile (Q1)', q3: 'Upper quartile (Q3)', min_length: 'Shortest text', max_length: 'Longest text',
};

function fmtStat(key, v, col) {
  if (v === null || v === undefined) return '—';
  if (key.endsWith('length')) return `${formatInteger(v)} characters`;
  if (col.dtype === 'date' || col.dtype === 'datetime') return String(v).replace('T00:00:00', '').replace('T', ' ');
  if (col.semantic_type === 'currency') return formatCurrency(v, col.currency || DEFAULT_CURRENCY);
  if (col.semantic_type === 'percent' && key !== 'std') return formatPercent(v, 2);
  return formatNumber(v, { maxDecimals: 4 });
}

function distRows(dist, col) {
  if (!dist) return [];
  if (dist.kind === 'histogram') {
    return dist.counts.map((c, i) => ({ label: `${formatNumber(dist.edges[i], { maxDecimals: 2 })} – ${formatNumber(dist.edges[i + 1], { maxDecimals: 2 })}`, count: c }));
  }
  const rows = dist.labels.map((l, i) => ({ label: l, count: dist.counts[i] }));
  if (dist.other) rows.push({ label: 'Other values', count: dist.other });
  return rows;
}

export default function ColumnProfilePanel({ column, onClose }) {
  const c = useThemeColors();
  const [view, setView] = useState('chart');
  const p = column?.profile;
  const rows = distRows(p?.dist, column || {});
  return (
    <Drawer open={Boolean(column)} onClose={onClose} title={column ? column.display_name : ''}>
      {column && p && (
        <>
          <div className="row-wrap">
            <Badge tone="primary">{column.dtype}</Badge>
            <Badge>{column.semantic_type}</Badge>
            {column.currency && <Badge>{column.currency}</Badge>}
            <code className="xs muted">{column.key}</code>
          </div>
          <dl className="grid-2" style={{ margin: 0, gap: 12 }}>
            <div><dt className="xs muted">Values</dt><dd style={{ margin: 0, fontWeight: 600 }} className="num">{formatInteger(p.count)}</dd></div>
            <div><dt className="xs muted">Empty</dt><dd style={{ margin: 0, fontWeight: 600 }} className="num">{formatInteger(p.missing)}</dd></div>
            <div><dt className="xs muted">Unique</dt><dd style={{ margin: 0, fontWeight: 600 }} className="num">{formatInteger(p.unique)}</dd></div>
            <div><dt className="xs muted">Conversion errors (set to empty)</dt><dd style={{ margin: 0, fontWeight: 600 }} className="num">{formatInteger(column.invalid || 0)}</dd></div>
            {Object.entries(p.stats || {}).map(([k, v]) => (
              <div key={k}><dt className="xs muted">{STAT_LABELS[k] || k}</dt><dd style={{ margin: 0, fontWeight: 600 }} className="num">{fmtStat(k, v, column)}</dd></div>
            ))}
          </dl>
          <p className="xs muted">Statistics skip empty values. Mean and median are shown separately because skewed data can make them differ.</p>
          {rows.length > 0 && (
            <div className="stack-sm">
              <div className="row between">
                <h3 style={{ fontSize: 'var(--fs-md)' }}>Value distribution</h3>
                <Segmented label="Distribution view" value={view} onChange={setView} options={[{ value: 'chart', label: 'Chart' }, { value: 'table', label: 'Table' }]} />
              </div>
              {view === 'chart' ? (
                <div style={{ height: 220 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={rows} layout={p.dist.kind === 'histogram' ? 'horizontal' : 'vertical'} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                      <CartesianGrid stroke={c.grid} horizontal={p.dist.kind === 'histogram'} vertical={p.dist.kind !== 'histogram'} />
                      {p.dist.kind === 'histogram' ? (
                        <>
                          <XAxis dataKey="label" hide />
                          <YAxis tick={{ fill: c.axis, fontSize: 11 }} allowDecimals={false} width={36} />
                        </>
                      ) : (
                        <>
                          <XAxis type="number" tick={{ fill: c.axis, fontSize: 11 }} allowDecimals={false} />
                          <YAxis type="category" dataKey="label" tick={{ fill: c.axis, fontSize: 11 }} width={110} />
                        </>
                      )}
                      <RTooltip cursor={{ fill: c.grid, opacity: 0.4 }} contentStyle={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 8, color: c.text }} formatter={(v) => [formatInteger(v), 'Rows']} />
                      <Bar dataKey="count" fill={c.series[0]} radius={p.dist.kind === 'histogram' ? [4, 4, 0, 0] : [0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <table className="table" aria-label={`Distribution of ${column.display_name}`}>
                  <thead><tr><th>{p.dist.kind === 'histogram' ? 'Range' : 'Value'}</th><th className="num">Rows</th></tr></thead>
                  <tbody>{rows.map((r) => <tr key={r.label}><td>{r.label}</td><td className="num">{formatInteger(r.count)}</td></tr>)}</tbody>
                </table>
              )}
            </div>
          )}
          {p.examples?.length > 0 && (
            <div className="stack-sm">
              <h3 style={{ fontSize: 'var(--fs-md)' }}>Example values</h3>
              <div className="row-wrap">{p.examples.map((e) => <Badge key={e}>{e}</Badge>)}</div>
            </div>
          )}
        </>
      )}
    </Drawer>
  );
}

import { memo, useMemo } from 'react';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import useThemeColors from '../hooks/useThemeColors.js';
import { formatCell, formatCompactValue, formatPeriod } from '../utils/format.js';

const EMPTY = '(empty)';
const label = (v) => (v === null || v === undefined ? EMPTY : String(v));

/**
 * Draws backend result rows. It only reshapes rows (long -> wide for series); it never computes values.
 * spec: { type, x, y, series }  columns: result column specs  rows: arrays aligned with columns
 * onSelect(value): optional; clicking a bar reports its category (used for cross-filtering).
 * selected: optional list of category labels to emphasise; the others are dimmed.
 * seriesOrder: optional fixed order of series labels, so a value keeps its colour across charts.
 */
function ResultChart({ spec, columns, rows, height = 300, onSelect, selected, seriesOrder }) {
  const c = useThemeColors();
  const idx = useMemo(() => Object.fromEntries(columns.map((col, i) => [col.key, i])), [columns]);
  const yCol = columns[idx[spec?.y]];
  const xIsPeriod = columns[idx[spec?.x]]?.semantic_type === 'period';

  const { data, series } = useMemo(() => {
    if (!spec || idx[spec.x] === undefined || idx[spec.y] === undefined) return { data: [], series: [] };
    const xi = idx[spec.x];
    const yi = idx[spec.y];
    const pi = idx.partial;
    const xLabel = (v) => (xIsPeriod ? formatPeriod(label(v)) : label(v));
    if (spec.series && idx[spec.series] !== undefined) {
      const si = idx[spec.series];
      const order = [];
      const byX = new Map();
      rows.forEach((r) => {
        const s = label(r[si]);
        if (!order.includes(s)) order.push(s);
        const x = xLabel(r[xi]);
        if (!byX.has(x)) byX.set(x, { __x: x, __raw: r[xi], __partial: pi !== undefined ? r[pi] : false });
        byX.get(x)[s] = r[yi];
      });
      return { data: [...byX.values()], series: order };
    }
    return { data: rows.map((r) => ({ __x: xLabel(r[xi]), __raw: r[xi], value: r[yi], __partial: pi !== undefined ? r[pi] : false })), series: ['value'] };
  }, [spec, rows, idx, xIsPeriod]);

  if (!data.length) return null;
  // Colour follows the entity: a fixed seriesOrder (or first-seen order) picks the slot; a 9th+ series is neutral grey.
  const slot = (s, i) => {
    if (!seriesOrder) return i;
    const k = seriesOrder.indexOf(s);
    return k >= 0 ? k : seriesOrder.length + i;
  };
  const color = (i, s) => {
    const k = s === undefined ? i : slot(s, i);
    return k < c.series.length ? c.series[k] : c.axis;
  };
  const fmt = (v) => formatCell(v, yCol || {}) ?? '—';
  const tick = (v) => formatCompactValue(v, yCol || {});
  const clickable = Boolean(onSelect);
  const isDim = (d) => selected?.length > 0 && !selected.includes(d.__x);
  const tooltip = (
    <Tooltip
      cursor={{ fill: c.grid, opacity: 0.6 }}
      contentStyle={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 6, color: c.text, fontSize: 12, boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}
      labelStyle={{ color: c.muted, marginBottom: 2 }}
      itemStyle={{ color: c.text, padding: 0 }}
      formatter={(v, name) => [fmt(v), name === 'value' ? (yCol?.label || 'Value') : name]}
      labelFormatter={(l, payload) => (payload?.[0]?.payload?.__partial ? `${l} (partial period)` : l)}
    />
  );
  const maxLabel = Math.max(...data.map((d) => d.__x.length));
  const axes = (horizontal) => (
    <>
      <CartesianGrid stroke={c.grid} vertical={horizontal} horizontal={!horizontal} />
      {horizontal ? (
        <>
          <XAxis type="number" tick={{ fill: c.axis, fontSize: 11 }} tickFormatter={tick} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="__x" tick={{ fill: c.text, fontSize: 12 }} width={Math.min(160, Math.max(56, maxLabel * 7 + 8))}
            axisLine={false} tickLine={false} interval={0} />
        </>
      ) : (
        <>
          <XAxis dataKey="__x" tick={{ fill: c.axis, fontSize: 11 }} axisLine={{ stroke: c.grid }} tickLine={false} minTickGap={16} />
          <YAxis tick={{ fill: c.axis, fontSize: 11 }} tickFormatter={spec.type === 'stacked_100_bar' ? (v) => `${Math.round(v * 100)}%` : tick}
            axisLine={false} tickLine={false} width={56} domain={spec.type === 'stacked_100_bar' ? [0, 1] : [0, 'auto']} />
        </>
      )}
    </>
  );
  // Legend text stays in the text colour; the swatch carries the identity.
  const legend = series.length > 1
    ? <Legend wrapperStyle={{ fontSize: 12, paddingTop: 4 }} iconType="square" iconSize={10} formatter={(v) => <span style={{ color: c.muted }}>{v}</span>} />
    : null;
  const name = (s) => (s === 'value' ? yCol?.label || 'Value' : s);
  const t = spec.type;

  let chart;
  if (t === 'line' || t === 'area') {
    const Chart = t === 'area' ? AreaChart : LineChart;
    chart = (
      <Chart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        {axes(false)}
        {tooltip}
        {legend}
        {series.map((s, i) =>
          t === 'area' ? (
            <Area key={s} type="linear" dataKey={s} name={name(s)} stroke={color(i, s)} fill={color(i, s)} fillOpacity={0.12} strokeWidth={2} dot={false} isAnimationActive={false} />
          ) : (
            <Line key={s} type="linear" dataKey={s} name={name(s)} stroke={color(i, s)} strokeWidth={2} dot={data.length <= 24 ? { r: 3, strokeWidth: 2, fill: c.surface } : false}
              activeDot={{ r: 5, strokeWidth: 2, stroke: c.surface }} connectNulls={false} isAnimationActive={false} />
          ),
        )}
      </Chart>
    );
  } else {
    const horizontal = t === 'horizontal_bar';
    const stacked = t === 'stacked_bar' || t === 'stacked_100_bar';
    // Direct value labels on a short ranked list; longer lists rely on the tooltip and table view.
    const labelled = horizontal && series.length === 1 && data.length <= 12;
    chart = (
      <BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'} stackOffset={t === 'stacked_100_bar' ? 'expand' : undefined}
        margin={{ top: 8, right: labelled ? 64 : 12, bottom: 0, left: 0 }} barCategoryGap={horizontal ? '28%' : '22%'} barGap={2}>
        {axes(horizontal)}
        {tooltip}
        {legend}
        {series.map((s, i) => (
          <Bar key={s} dataKey={s} name={name(s)} fill={color(i, series.length > 1 ? s : undefined)} stackId={stacked ? 'a' : undefined} maxBarSize={horizontal ? 22 : 40}
            radius={stacked ? 0 : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} stroke={stacked ? c.surface : undefined} strokeWidth={stacked ? 1 : 0} isAnimationActive={false}
            onClick={clickable ? (entry) => entry?.payload && onSelect(entry.payload.__raw) : undefined} style={clickable ? { cursor: 'pointer' } : undefined}>
            {!stacked && series.length === 1 && data.map((d) => <Cell key={d.__x} fillOpacity={isDim(d) ? 0.3 : 1} />)}
            {labelled && <LabelList dataKey={s} position="right" offset={6} formatter={tick} style={{ fill: c.muted, fontSize: 11, fontVariantNumeric: 'tabular-nums' }} />}
          </Bar>
        ))}
      </BarChart>
    );
  }
  return (
    <div style={{ width: '100%', height }} role="img" aria-label={`${t.replace(/_/g, ' ')} chart of ${yCol?.label || 'values'}. A table view is available.`}>
      <ResponsiveContainer width="100%" height="100%">{chart}</ResponsiveContainer>
    </div>
  );
}

export default memo(ResultChart);

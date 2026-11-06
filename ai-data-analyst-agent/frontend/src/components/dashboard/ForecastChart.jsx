import { memo, useMemo } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import useThemeColors from '../../hooks/useThemeColors.js';
import { formatCell, formatCompactValue, formatPeriod } from '../../utils/format.js';

/** Actual trend (solid) followed by the backend's projection (dashed) and its 80% range (band). */
function ForecastChart({ columns, rows, forecast, height = 260 }) {
  const c = useThemeColors();
  const ix = Object.fromEntries(columns.map((col, i) => [col.key, i]));
  const vcol = columns[ix.value];
  const data = useMemo(() => {
    const actual = rows.map((r) => ({ x: formatPeriod(r[ix.period]), actual: r[ix.value], partial: r[ix.partial] }));
    const lastComplete = [...actual].reverse().find((p) => !p.partial);
    // The dashed line starts at the last complete actual value so the two lines connect.
    if (lastComplete) lastComplete.forecast = lastComplete.actual;
    const future = forecast.points.map((p) => ({ x: formatPeriod(p.period), forecast: p.value, band: [p.low, p.high] }));
    // A trailing partial period is replaced by its forecast.
    const kept = actual.filter((p) => !(p.partial && future.some((f) => f.x === p.x)));
    return [...kept, ...future.filter((f) => !kept.some((k) => k.x === f.x))];
  }, [rows, forecast, ix.period, ix.value, ix.partial]);
  const fmt = (v) => (Array.isArray(v) ? `${formatCell(v[0], vcol)} – ${formatCell(v[1], vcol)}` : formatCell(v, vcol) ?? '—');
  return (
    <div style={{ width: '100%', height }} role="img" aria-label={`Trend of ${vcol?.label} with a ${forecast.points.length}-period forecast`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={c.grid} vertical={false} />
          <XAxis dataKey="x" tick={{ fill: c.axis, fontSize: 11 }} axisLine={{ stroke: c.grid }} tickLine={false} minTickGap={16} />
          <YAxis tick={{ fill: c.axis, fontSize: 11 }} tickFormatter={(v) => formatCompactValue(v, vcol || {})} axisLine={false} tickLine={false} width={56} domain={[0, 'auto']} />
          <Tooltip contentStyle={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 6, fontSize: 12 }} itemStyle={{ color: c.text, padding: 0 }}
            formatter={(v, name) => [fmt(v), name === 'band' ? '80% range' : name === 'forecast' ? 'Forecast' : vcol?.label]} />
          <Area dataKey="band" stroke="none" fill={c.series[0]} fillOpacity={0.12} isAnimationActive={false} />
          <Line dataKey="actual" stroke={c.series[0]} strokeWidth={2} dot={data.length <= 30 ? { r: 3, fill: c.surface, strokeWidth: 2 } : false} isAnimationActive={false} connectNulls={false} />
          <Line dataKey="forecast" stroke={c.series[0]} strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3, fill: c.surface, strokeWidth: 2 }} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export default memo(ForecastChart);

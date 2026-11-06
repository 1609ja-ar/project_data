import { memo } from 'react';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import useThemeColors from '../../hooks/useThemeColors.js';
import { formatCell, formatPercent } from '../../utils/format.js';

/** Part-to-whole for a handful of groups. Shares come from the backend; this only draws them. */
function DonutChart({ columns, rows, height = 220, onSelect, selected, seriesOrder }) {
  const c = useThemeColors();
  // Colour follows the value (same slot as in every other chart of this dimension), not its rank here.
  const colorOf = (name, i) => {
    const k = seriesOrder ? seriesOrder.indexOf(String(name)) : i;
    const slot = k >= 0 ? k : (seriesOrder?.length || 0) + i;
    return c.series[slot] || c.axis;
  };
  const ix = Object.fromEntries(columns.map((col, i) => [col.key, i]));
  const dimKey = columns[0].key;
  const valueCol = columns[ix.value];
  const data = rows.map((r) => ({ name: r[ix[dimKey]] ?? '(empty)', raw: r[ix[dimKey]], value: r[ix.value], share: r[ix.share] }));
  const dim = (d) => selected?.length > 0 && !selected.includes(String(d.name));
  return (
    <div className="donut-wrap">
      <div style={{ height }} role="img" aria-label={`Donut chart of ${valueCol?.label} by ${columns[0].label}. A table view is available.`}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip
              contentStyle={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 6, color: c.text, fontSize: 12 }}
              formatter={(v, n, p) => [`${formatCell(v, valueCol) ?? '—'} (${formatPercent(p.payload.share)})`, n]}
            />
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="92%" paddingAngle={1} stroke={c.surface} strokeWidth={2}
              isAnimationActive={false} onClick={onSelect ? (d) => d?.payload?.raw != null && onSelect(d.payload.raw) : undefined}
              style={onSelect ? { cursor: 'pointer' } : undefined}>
              {data.map((d, i) => <Cell key={String(d.name)} fill={colorOf(d.name, i)} fillOpacity={dim(d) ? 0.3 : 1} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="donut-list">
        {data.map((d, i) => (
          <li key={String(d.name)} onClick={onSelect && d.raw != null ? () => onSelect(d.raw) : undefined} style={{ opacity: dim(d) ? 0.5 : 1 }}>
            <i style={{ background: colorOf(d.name, i) }} aria-hidden="true" />
            <span className="name" title={String(d.name)}>{String(d.name)}</span>
            <span className="pct">{formatPercent(d.share)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default memo(DonutChart);

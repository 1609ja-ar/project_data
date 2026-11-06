import { memo, useEffect, useRef, useState } from 'react';
import { ArrowDownRight, ArrowRight, ArrowUpRight, Calculator, Coins, Hash, Layers, Rows3, Sigma, Target } from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, YAxis } from 'recharts';
import CalcDrawer from '../CalcDrawer.jsx';
import { Moment3D } from '../Moment3D.jsx';
import { KpiRise3D } from '../../three/moments/index.js';
import { Card } from '../ui/index.js';
import useThemeColors from '../../hooks/useThemeColors.js';
import { formatCell, formatKpi, formatPercent, formatPeriod } from '../../utils/format.js';

function Spark({ points, column, accent }) {
  const c = useThemeColors();
  const color = c.series[accent % c.series.length];
  const gid = `spark-${accent}`;
  if (points.length < 2) return <div className="spark" aria-hidden="true" />;
  return (
    <div className="spark" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <YAxis hide domain={['dataMin', 'dataMax']} />
          <Tooltip
            cursor={{ stroke: c.grid }}
            contentStyle={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 6, fontSize: 11, padding: '2px 8px' }}
            labelFormatter={(_, p) => formatPeriod(p?.[0]?.payload?.period)}
            formatter={(v) => [formatCell(v, column) ?? '—', '']}
            separator=""
          />
          <defs><linearGradient id={gid} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.28} /><stop offset="100%" stopColor={color} stopOpacity={0} /></linearGradient></defs>
          <Area type="monotone" dataKey="value" stroke={color} strokeWidth={1.75} fill={`url(#${gid})`} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

const ICONS = { primary: Coins, records: Rows3, average: Calculator, second: Layers, distinct: Hash };

function GoalEditor({ kpi, onSave, onRemove, onClose }) {
  const [value, setValue] = useState(kpi.goal ? String(kpi.goal.target) : '');
  const ref = useRef(null);
  useEffect(() => {
    const onDoc = (e) => !ref.current?.contains(e.target) && onClose();
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [onClose]);
  const n = Number(value);
  return (
    <form ref={ref} className="goal-pop" onSubmit={(e) => { e.preventDefault(); if (n > 0) onSave(n); }}>
      <label className="label" htmlFor={`goal-${kpi.key}`}>Target for {kpi.label}</label>
      <input id={`goal-${kpi.key}`} className="input" type="number" min="0" step="any" value={value} autoFocus onChange={(e) => setValue(e.target.value)} />
      <div className="row between">
        {kpi.goal ? <button type="button" className="btn btn-ghost btn-sm" onClick={onRemove}>Remove</button> : <span />}
        <button type="submit" className="btn btn-primary btn-sm" disabled={!(n > 0)}>Save</button>
      </div>
    </form>
  );
}

/** One KPI: value from a verified backend aggregate, change vs the previous complete period, sparkline,
 *  and an optional target with progress (progress is computed by the backend). */
function KpiCard({ kpi, datasetId, accent = 0, onGoal }) {
  const [editing, setEditing] = useState(false);
  const [rise, setRise] = useState(false);
  const c = useThemeColors();
  const ch = kpi.change;
  const dir = !ch ? null : ch.pct > 0.0005 ? 'up' : ch.pct < -0.0005 ? 'down' : 'flat';
  const Arrow = dir === 'up' ? ArrowUpRight : dir === 'down' ? ArrowDownRight : ArrowRight;
  const Icon = kpi.id === 'primary' && kpi.column?.semantic_type !== 'currency' ? Sigma : ICONS[kpi.id] || Sigma;
  const g = kpi.goal;
  const met = g && (g.direction === 'at_most' ? g.progress <= 1 : g.progress >= 1);
  return (
    <Card className="kpi kpi-accent" style={{ '--accent': `var(--chart-${(accent % 8) + 1})` }}>
      <div className="kpi-label">
        <span className="row" style={{ gap: 8, minWidth: 0 }}>
          {ch ? (
            <button type="button" className="kpi-icon kpi-icon-btn" onClick={() => setRise(true)} aria-label={`Show ${kpi.label} change in 3D`} title="Show the change in 3D">
              <Icon size={15} aria-hidden="true" />
            </button>
          ) : <span className="kpi-icon" aria-hidden="true"><Icon size={15} /></span>}
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={kpi.label}>{kpi.label}</span>
        </span>
        <span className="row" style={{ gap: 0, position: 'relative' }}>
          {onGoal && kpi.key && (
            <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={() => setEditing((e) => !e)} aria-label={`Set a target for ${kpi.label}`} title="Set target">
              <Target size={15} aria-hidden="true" />
            </button>
          )}
          <CalcDrawer details={kpi.how_calculated} datasetId={datasetId} iconOnly label={`How ${kpi.label} was calculated`} />
          {editing && (
            <GoalEditor kpi={kpi} onClose={() => setEditing(false)}
              onSave={(t) => { setEditing(false); onGoal(kpi.key, t); }} onRemove={() => { setEditing(false); onGoal(kpi.key, null); }} />
          )}
        </span>
      </div>
      <div className="kpi-value" title={formatCell(kpi.value, kpi.column) ?? ''}>{formatKpi(kpi.value, kpi.column)}</div>
      <div className="kpi-foot">
        {ch ? (
          <>
            <span className="delta" data-dir={dir}><Arrow size={13} aria-hidden="true" />{formatPercent(Math.abs(ch.pct))}</span>
            <span>{formatPeriod(ch.period)} vs {formatPeriod(ch.previous_period)}</span>
          </>
        ) : <span>&nbsp;</span>}
      </div>
      {g ? (
        <div className="goal" data-met={met}>
          <div className="goal-bar"><span style={{ width: `${Math.min(100, Math.max(0, g.progress * 100))}%` }} /></div>
          <span className="xs"><strong>{formatPercent(g.progress, 0)}</strong> of {formatKpi(g.target, kpi.column)} target</span>
        </div>
      ) : <Spark points={kpi.spark} column={kpi.column} accent={accent} />}
      {ch && (
        <Moment3D open={rise} onClose={() => setRise(false)} title={`${kpi.label}: ${formatPeriod(ch.period)} vs ${formatPeriod(ch.previous_period)}`}
          caption={`${formatKpi(ch.current, kpi.column)} in ${formatPeriod(ch.period)}, ${dir === 'down' ? 'down' : 'up'} ${formatPercent(Math.abs(ch.pct))} from ${formatKpi(ch.previous, kpi.column)} in ${formatPeriod(ch.previous_period)}.`}
          scene={KpiRise3D}
          sceneProps={{ previous: ch.previous, current: ch.current, prevLabel: formatPeriod(ch.previous_period), curLabel: formatPeriod(ch.period),
            valueText: formatKpi(ch.current, kpi.column), prevText: formatKpi(ch.previous, kpi.column), changeText: formatPercent(Math.abs(ch.pct)), dir,
            color: c.series[accent % c.series.length] }} />
      )}
    </Card>
  );
}

export default memo(KpiCard);

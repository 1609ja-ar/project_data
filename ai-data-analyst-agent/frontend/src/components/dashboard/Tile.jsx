import { lazy, memo, useMemo, useState } from 'react';
import { BarChart3, Box, Orbit, PinOff, Table2, TrendingUp } from 'lucide-react';
import CalcDrawer from '../CalcDrawer.jsx';
import ResultChart from '../ResultChart.jsx';
import DonutChart from './DonutChart.jsx';
import ForecastChart from './ForecastChart.jsx';
import { Badge, Button, Card, DataTable, Segmented } from '../ui/index.js';
import Lazy3D from '../../three/Lazy3D.jsx';
import { Moment3D } from '../Moment3D.jsx';
import { ForecastRibbon3D } from '../../three/moments/index.js';
import useThemeColors from '../../hooks/useThemeColors.js';
import { formatCell, formatCompactValue, formatPeriod } from '../../utils/format.js';

const DataBars3D = lazy(() => import('../../three/DataBars3D.jsx'));
const City3D = lazy(() => import('../../three/City3D.jsx'));
const HEIGHT = { trend: 260, split: 280, breakdown: 260, share: 220, custom: 260 };

/** A dashboard tile: chart / table / 3D view, optional forecast, "how calculated" and click-to-filter. */
function Tile({ tile, datasetId, onSelect, selected, seriesOrder, onUnpin, defaultForecast = false, className = '' }) {
  const c = useThemeColors();
  const { spec, columns, rows } = tile.chart;
  const [view, setView] = useState(tile.kind === 'table' ? 'table' : 'chart');
  const [showForecast, setShowForecast] = useState(defaultForecast);
  const [ribbon, setRibbon] = useState(false);
  const filterable = Boolean(tile.dimension && onSelect && tile.kind !== 'split');
  const select = filterable ? (v) => onSelect(tile.dimension, v) : undefined;
  const valueCol = columns.find((col) => col.key === 'value');
  // 3D: one bar per value for category charts; a period x category "city" for split trends.
  const isCity = Boolean(spec.series && spec.x === 'period' && rows.length <= 400);
  const can3D = tile.kind !== 'table' && (isCity || (!spec.series && spec.x !== 'period' && rows.length > 1 && rows.length <= 12));
  // Table view shows exactly the backend columns, minus internal ones; shares read better at one decimal.
  const kept = columns.filter((col) => col.key !== 'period_start' && col.key !== 'partial');
  const tableCols = kept.map((col) => (col.semantic_type === 'percent' ? { ...col, decimals: 1 } : col));
  const tableRows = rows.map((r) => kept.map((col) => r[columns.indexOf(col)]));
  const height = HEIGHT[tile.kind] || 260;

  const items3D = useMemo(() => {
    if (!can3D || isCity) return [];
    const xi = columns.findIndex((col) => col.key === spec.x);
    const yi = columns.findIndex((col) => col.key === 'value');
    return rows.map((r, i) => {
      const label = r[xi] == null ? '(empty)' : String(r[xi]);
      const slot = seriesOrder ? seriesOrder.indexOf(label) : -1;
      return {
        label, raw: r[xi], value: Number(r[yi]) || 0, text: formatCell(r[yi], valueCol) ?? '—',
        color: c.series[slot >= 0 ? slot % c.series.length : i % c.series.length],
        dim: selected?.length > 0 && !selected.includes(label),
      };
    });
  }, [can3D, isCity, columns, rows, spec.x, seriesOrder, valueCol, c.series, selected]);

  let body;
  if (view === 'table') {
    body = <DataTable columns={tableCols} rows={tableRows} pageSize={tile.kind === 'table' ? 15 : 10} maxHeight={tile.kind === 'table' ? 560 : height} caption={tile.title} />;
  } else if (view === '3d') {
    body = isCity ? (
      <Lazy3D scene={City3D} height={height + 60} label={`3D view of ${tile.title}`} sceneProps={{ columns, rows, spec, seriesOrder }}
        fallback={<ResultChart spec={spec} columns={columns} rows={rows} height={height} seriesOrder={seriesOrder} />} />
    ) : (
      <Lazy3D scene={DataBars3D} height={height + 30} label={`3D bar chart of ${tile.title}`} sceneProps={{ items: items3D, onSelect: select }}
        fallback={<ResultChart spec={{ ...spec, type: 'horizontal_bar' }} columns={columns} rows={rows} height={height} onSelect={select} selected={selected} />} />
    );
  } else if (showForecast && tile.forecast) {
    body = <ForecastChart columns={columns} rows={rows} forecast={tile.forecast} height={height} />;
  } else if (spec.type === 'donut') {
    body = <DonutChart columns={columns} rows={rows} height={HEIGHT.share} onSelect={select} selected={selected} seriesOrder={seriesOrder} />;
  } else {
    body = <ResultChart spec={spec} columns={columns} rows={rows} height={height} onSelect={select} selected={selected} seriesOrder={seriesOrder} />;
  }

  const views = [{ value: 'chart', label: 'Chart', icon: BarChart3, showLabel: false }, { value: 'table', label: 'Table', icon: Table2, showLabel: false }];
  if (can3D) views.push({ value: '3d', label: '3D', icon: Box, showLabel: false });
  const f = tile.forecast;
  // Recorded complete periods + the backend projection, for the 3D forecast moment.
  const ribbonProps = useMemo(() => {
    if (!f) return null;
    const ix = Object.fromEntries(columns.map((col, i) => [col.key, i]));
    const actual = rows.filter((r) => !r[ix.partial]).map((r) => ({ label: formatPeriod(r[ix.period]), value: r[ix.value] })).slice(-18);
    if (actual.length < 2) return null;
    const end = f.points[f.points.length - 1];
    return {
      actual, forecast: f.points.map((p) => ({ label: formatPeriod(p.period), value: p.value, low: p.low, high: p.high })),
      firstLabel: actual[0].label, lastLabel: actual[actual.length - 1].label,
      lastText: formatCompactValue(actual[actual.length - 1].value, valueCol),
      forecastText: `${formatPeriod(end.period)}: ${formatCompactValue(end.value, valueCol)}`,
      caption: `Recorded ${actual.length} complete ${f.grain}s, then the projection to ${formatPeriod(end.period)} (${formatCompactValue(end.value, valueCol)}, 80% range ${formatCompactValue(end.low, valueCol)}–${formatCompactValue(end.high, valueCol)}). Projections are estimates, not recorded values.`,
    };
  }, [f, columns, rows, valueCol]);

  return (
    <Card className={`tile ${tile.kind === 'custom' ? 'tile-custom' : ''} ${className}`}>
      <div className="tile-head">
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 6 }}>
            <h3>{tile.title}</h3>
            {tile.kind === 'custom' && <Badge>Pinned</Badge>}
          </div>
          {tile.subtitle && <p>{tile.subtitle}{showForecast && f && view === 'chart' ? ` · forecast to ${formatPeriod(f.points[f.points.length - 1].period)}` : ''}</p>}
        </div>
        <div className="tile-actions">
          {f && view === 'chart' && (
            <Button variant={showForecast ? 'secondary' : 'ghost'} size="sm" icon={TrendingUp} aria-pressed={showForecast}
              onClick={() => setShowForecast((s) => !s)} title="Linear trend projection with an 80% range">Forecast</Button>
          )}
          {showForecast && ribbonProps && view === 'chart' && (
            <Button variant="ghost" size="sm" icon={Orbit} onClick={() => setRibbon(true)} aria-label={`View ${tile.title} forecast in 3D`} title="View forecast in 3D" />
          )}
          {tile.kind !== 'table' && <Segmented options={views} value={view} onChange={setView} label={`${tile.title} view`} />}
          <CalcDrawer details={tile.how_calculated} datasetId={datasetId} iconOnly label="How this was calculated" />
          {onUnpin && <Button variant="ghost" size="sm" icon={PinOff} onClick={onUnpin} aria-label={`Remove ${tile.title} from dashboard`} title="Remove from dashboard" />}
        </div>
      </div>
      <div className="tile-body">{body}</div>
      {showForecast && f && view === 'chart' && (
        <p className="tile-foot">Projection from {f.basis} complete {f.grain}s; dashed line and band are estimates, not recorded values{f.r2 != null && f.r2 < 0.3 ? ' (weak trend: wide uncertainty)' : ''}.</p>
      )}
      {tile.other && view === 'chart' && (
        <p className="tile-foot">+{tile.other.groups} more · {formatCell(tile.other.value, valueCol) ?? formatCompactValue(tile.other.value, valueCol)}</p>
      )}
      {ribbonProps && (
        <Moment3D open={ribbon} onClose={() => setRibbon(false)} title={`${tile.title}: forecast`} caption={ribbonProps.caption}
          scene={ForecastRibbon3D} sceneProps={ribbonProps} />
      )}
    </Card>
  );
}

export default memo(Tile);

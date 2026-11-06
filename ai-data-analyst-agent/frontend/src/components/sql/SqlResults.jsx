import { useEffect, useMemo, useState } from 'react';
import { BarChart3, Copy, Download, Table2 } from 'lucide-react';
import ResultChart from '../ResultChart.jsx';
import CalcDrawer from '../CalcDrawer.jsx';
import { Alert, Badge, Button, DataTable, Segmented, Select, useToast } from '../ui/index.js';
import { formatCell, formatInteger, formatNumber } from '../../utils/format.js';

const CHART_TYPES = [
  { value: 'bar', label: 'Vertical bar' }, { value: 'horizontal_bar', label: 'Horizontal bar' },
  { value: 'grouped_bar', label: 'Grouped bar' }, { value: 'stacked_bar', label: 'Stacked bar' },
  { value: 'stacked_100_bar', label: '100% stacked bar' }, { value: 'line', label: 'Line' }, { value: 'area', label: 'Area' },
];
const NEEDS_SERIES = new Set(['grouped_bar', 'stacked_bar', 'stacked_100_bar']);
const isNum = (c) => ['integer', 'float', 'decimal'].includes(c.dtype);

function csvOf(columns, rows) {
  const cell = (v, col) => {
    if (v === null || v === undefined) return '';
    let s = String(v);
    if (!isNum(col) && /^[=+\-@\t\r]/.test(s)) s = `'${s}`; // formula-injection escaping for text only
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map((c) => cell(c.label, {})).join(',')].concat(rows.map((r) => r.map((v, i) => cell(v, columns[i])).join(','))).join('\n');
}

export default function SqlResults({ result, datasetId }) {
  const toast = useToast();
  const [view, setView] = useState('table');
  const cols = result.columns;
  const numeric = cols.filter(isNum);
  const others = cols.filter((c) => !isNum(c));
  const [chart, setChart] = useState({});
  useEffect(() => {
    setChart({ type: 'bar', x: (others[0] || cols[0])?.key, y: numeric[0]?.key, series: '' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);
  const spec = useMemo(() => ({ type: chart.type, x: chart.x, y: chart.y, ...(chart.series ? { series: chart.series } : {}) }), [chart]);
  const chartProblem = !numeric.length ? 'Charts need at least one numeric column in the result.'
    : NEEDS_SERIES.has(chart.type) && !chart.series ? 'Choose a series column for this chart type.' : null;

  const columns = cols.map((c) => ({ ...c, display_name: c.label }));
  const copy = async () => {
    try {
      await navigator.clipboard.writeText([cols.map((c) => c.label).join('\t')].concat(result.rows.map((r) => r.map((v, i) => formatCell(v, cols[i]) ?? '').join('\t'))).join('\n'));
      toast.success('Result copied');
    } catch {
      toast.error('Copy failed');
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([csvOf(cols, result.rows)], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'sql_result.csv';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="stack-sm">
      <div className="row between" style={{ flexWrap: 'wrap' }}>
        <div className="row-wrap">
          <Badge tone="success">{formatInteger(result.row_count)} row(s)</Badge>
          <Badge>{formatNumber(result.duration_ms, { maxDecimals: 1 })} ms</Badge>
          <Badge>Dataset version {result.dataset_version}</Badge>
          {result.truncated && <Badge tone="warning">Truncated to {formatInteger(result.max_rows)}</Badge>}
        </div>
        <div className="row-wrap">
          <Segmented label="Results or chart" value={view} onChange={setView}
            options={[{ value: 'table', label: 'Results', icon: Table2 }, { value: 'chart', label: 'Chart', icon: BarChart3 }]} />
          <Button variant="ghost" size="sm" icon={Copy} onClick={copy}>Copy</Button>
          <Button variant="ghost" size="sm" icon={Download} onClick={download}>CSV</Button>
          <CalcDrawer details={{ ...result.calculation_details, equivalent_sql: result.executed_sql }} label="Details" />
        </div>
      </div>
      {result.truncated && <Alert tone="warning">Only the first {formatInteger(result.max_rows)} rows are shown. Add a WHERE clause or aggregate to see everything.</Alert>}
      {view === 'table' ? (
        <DataTable columns={columns} rows={result.rows} pageSize={50} maxHeight={420} caption="SQL result" />
      ) : (
        <div className="stack-sm">
          <div className="grid-4">
            <Select label="Chart type" value={chart.type} onChange={(e) => setChart((c) => ({ ...c, type: e.target.value }))} options={CHART_TYPES} />
            <Select label="X axis" value={chart.x || ''} onChange={(e) => setChart((c) => ({ ...c, x: e.target.value }))} options={cols.map((c) => ({ value: c.key, label: c.label }))} />
            <Select label="Y value" value={chart.y || ''} onChange={(e) => setChart((c) => ({ ...c, y: e.target.value }))} options={numeric.map((c) => ({ value: c.key, label: c.label }))} />
            <Select label="Series (optional)" value={chart.series || ''} onChange={(e) => setChart((c) => ({ ...c, series: e.target.value }))}
              options={[{ value: '', label: 'None' }, ...others.filter((c) => c.key !== chart.x).map((c) => ({ value: c.key, label: c.label }))]} />
          </div>
          {chartProblem ? <Alert tone="info">{chartProblem}</Alert> : <ResultChart spec={spec} columns={cols} rows={result.rows} height={320} />}
          <p className="xs muted">The chart uses exactly the rows in the result table; nothing is recalculated.</p>
        </div>
      )}
    </div>
  );
}

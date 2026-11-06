import { useState } from 'react';
import { BarChart3, Copy, Table2 } from 'lucide-react';
import ResultChart from './ResultChart.jsx';
import CalcDrawer from './CalcDrawer.jsx';
import { Alert, Button, DataTable, Segmented, useToast } from './ui/index.js';
import { formatCell } from '../utils/format.js';

/** Backend result: chart + table toggle (same rows for both), copy button, calculation drawer. */
export default function ResultView({ result, datasetId, chartSpec, height = 300, defaultView = 'chart' }) {
  const toast = useToast();
  const spec = chartSpec || result.chart || result.chart_suggestion;
  const chartable = spec && !['kpi', 'table'].includes(spec.type);
  const [view, setView] = useState(chartable ? defaultView : 'table');
  const columns = result.columns.map((c) => ({ ...c, display_name: c.label }));
  const { rows } = result;

  const copy = async () => {
    const text = [columns.map((c) => c.label).join('\t')]
      .concat(result.rows.map((r) => r.map((v, i) => formatCell(v, columns[i]) ?? '').join('\t')))
      .join('\n');
    try {
      await navigator.clipboard.writeText(text);
      toast.success('Result copied');
    } catch {
      toast.error('Copy failed');
    }
  };

  return (
    <div className="stack-sm">
      {result.calculation_details?.warnings?.map((w) => <Alert key={w} tone="warning">{w}</Alert>)}
      <div className="row between" style={{ flexWrap: 'wrap' }}>
        {chartable ? (
          <Segmented label="Chart or table" value={view} onChange={setView}
            options={[{ value: 'chart', label: 'Chart', icon: BarChart3 }, { value: 'table', label: 'Table', icon: Table2 }]} />
        ) : <span />}
        <div className="row">
          <Button variant="ghost" size="sm" icon={Copy} onClick={copy}>Copy</Button>
          <CalcDrawer details={result.calculation_details} datasetId={datasetId} />
        </div>
      </div>
      {view === 'chart' && chartable ? (
        <ResultChart spec={spec} columns={result.columns} rows={result.rows} height={height} />
      ) : (
        <DataTable columns={columns} rows={rows} pageSize={25} maxHeight={height + 120} caption="Result table" />
      )}
      {result.other && (
        <p className="xs muted">Plus {result.other.groups} more group(s) totalling {formatCell(result.other.value, result.columns.find((c) => c.key === 'value'))} ({result.other.rows} rows).</p>
      )}
    </div>
  );
}

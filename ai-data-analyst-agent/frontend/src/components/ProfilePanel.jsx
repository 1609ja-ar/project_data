import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Info, RefreshCw } from 'lucide-react';
import ResultView from './ResultView.jsx';
import CalcDrawer from './CalcDrawer.jsx';
import { Alert, Badge, Button, Card, CardHeader, EmptyState, ErrorState, Skeleton } from './ui/index.js';
import api from '../services/api.js';
import { errorMessage } from '../services/errors.js';
import { formatCurrency, formatInteger, formatNumber, formatPercent } from '../utils/format.js';

function Correlation({ corr }) {
  if (!corr) return <p className="small muted">Correlation needs at least two numeric columns.</p>;
  return (
    <div className="stack-sm">
      <Alert tone="info" icon={Info}>{corr.note}</Alert>
      <div className="table-wrap">
        <table className="table" aria-label="Pearson correlation matrix">
          <thead><tr><th>Column</th>{corr.columns.map((c) => <th key={c.key} className="num">{c.label}</th>)}</tr></thead>
          <tbody>
            {corr.columns.map((row, i) => (
              <tr key={row.key}>
                <th scope="row" style={{ position: 'static' }}>{row.label}</th>
                {corr.pearson[i].map((v, j) => (
                  <td key={j} className="num" title={`n = ${corr.n[i][j]}`} style={{ fontWeight: v !== null && i !== j && Math.abs(v) >= 0.5 ? 700 : 400 }}>
                    {v === null ? '—' : formatNumber(v, { maxDecimals: 3 })}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="xs muted">Bold: |r| ≥ 0.5. Hover a cell for the number of rows used.</p>
    </div>
  );
}

function Business({ b, datasetId }) {
  if (!b) return null;
  if (b.error) return <Alert tone="danger">Business metrics: {b.error}</Alert>;
  const cur = b.revenue.currency;
  const money = (v) => (cur ? formatCurrency(v, cur) : formatNumber(v));
  return (
    <Card>
      <CardHeader title="Business metrics" subtitle={`Based on detected column roles: ${Object.entries(b.roles).map(([r, c]) => `${r} = ${c.label}`).join(', ')}`} />
      <div className="card-body stack">
        <div className="grid-3">
          <div><p className="xs muted">Total {b.revenue.column}</p><p className="num" style={{ fontSize: 'var(--fs-xl)', fontWeight: 700 }}>{money(b.revenue.value)}</p>
            <CalcDrawer details={b.revenue.calculation_details} datasetId={datasetId} label="How calculated" /></div>
          {b.average_order_value && (
            <div><p className="xs muted">{b.average_order_value.label}</p><p className="num" style={{ fontSize: 'var(--fs-xl)', fontWeight: 700 }}>{money(b.average_order_value.value)}</p>
              <p className="xs muted">{b.average_order_value.formula} ({formatInteger(b.average_order_value.orders)})</p></div>
          )}
        </div>
        {['product', 'region', 'category', 'customer'].filter((r) => b[`top_${r}`]).map((r) => (
          <div key={r} className="stack-sm">
            <h3 style={{ fontSize: 'var(--fs-md)' }}>Top {b[`top_${r}`].column} by {b.revenue.column}</h3>
            <ResultView result={{ columns: b[`top_${r}`].columns, rows: b[`top_${r}`].rows, chart_suggestion: { type: 'horizontal_bar', x: b.roles[r].key, y: 'value' } }} height={200} />
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function ProfilePanel({ datasetId, versionId }) {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const load = useCallback(async (refresh = false) => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const { data } = await api.post(`/analytics/${datasetId}/profile`, { version_id: versionId, refresh });
      setState({ data, loading: false, error: null });
    } catch (err) {
      setState({ data: null, loading: false, error: errorMessage(err) });
    }
  }, [datasetId, versionId]);
  useEffect(() => { load(false); }, [load]);

  const { data, loading, error } = state;
  if (error) return <ErrorState message={error} onRetry={() => load(false)} />;
  if (!data) return <div className="stack"><Skeleton height={80} /><Skeleton height={260} /></div>;
  const p = data.profile;
  return (
    <div className="stack" aria-busy={loading}>
      <div className="row between">
        <p className="small muted">Version {p.dataset_version} · {formatInteger(p.shape.rows)} rows × {formatInteger(p.shape.columns)} columns · {formatInteger(p.duplicates)} identical rows {data.cached && '· cached'}</p>
        <Button variant="secondary" size="sm" icon={RefreshCw} loading={loading} onClick={() => load(true)}>Recalculate</Button>
      </div>
      <Card>
        <CardHeader title="Data quality" subtitle={`Score ${p.quality.score_before ?? '—'} before cleaning → ${p.quality.score_after ?? '—'} after (out of 100)`} />
        <div className="card-body">
          {p.quality.issues.length === 0 ? <p className="small muted">No remaining issues found.</p> : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }} className="stack-sm">
              {p.quality.issues.map((i, k) => (
                <li key={k} className="row small">
                  {i.severity === 'warning' ? <AlertTriangle size={15} color="var(--warning)" aria-label="Warning" /> : <Info size={15} color="var(--info)" aria-label="Info" />}
                  {i.column && <Badge>{i.column}</Badge>}<span>{i.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
      <Business b={p.business} datasetId={datasetId} />
      {p.trend && (
        <Card>
          <CardHeader title="Over time" subtitle={p.trend.metric_label} />
          <div className="card-body">{p.trend.error ? <Alert tone="danger">{p.trend.error}</Alert> : <ResultView result={p.trend} datasetId={datasetId} />}</div>
        </Card>
      )}
      <div className="grid-2" style={{ alignItems: 'start' }}>
        <Card>
          <CardHeader title="Outlier screening" subtitle="1.5 × IQR rule. A screening, not proof of an error." />
          <div className="card-body">
            {p.outliers.length === 0 ? <EmptyState title="No outliers flagged" message="No numeric column has values outside the screening bounds." /> : (
              <table className="table" aria-label="Outlier screening">
                <thead><tr><th>Column</th><th className="num">Flagged</th><th className="num">Share</th><th className="num">Bounds</th></tr></thead>
                <tbody>{p.outliers.map((o) => (
                  <tr key={o.column}><td>{o.label}</td><td className="num">{formatInteger(o.count)}</td><td className="num">{formatPercent(o.share)}</td>
                    <td className="num">{formatNumber(o.lower)} to {formatNumber(o.upper)}</td></tr>))}</tbody>
              </table>
            )}
          </div>
        </Card>
        <Card>
          <CardHeader title="Correlation" />
          <div className="card-body"><Correlation corr={p.correlation} /></div>
        </Card>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Pin, RefreshCw, X } from 'lucide-react';
import ResultChart from '../ResultChart.jsx';
import DonutChart from './DonutChart.jsx';
import CalcDrawer from '../CalcDrawer.jsx';
import { Button, Card, Skeleton, Switch, useToast } from '../ui/index.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';

/**
 * Suggested charts: the server builds a menu of valid charts from the column types; an AI provider (if
 * configured) picks the best ones, otherwise rules do. Every chart is computed and verified on the
 * server. Users pin the ones they want onto the dashboard.
 */
export default function AutoCharts({ datasetId, view, aiReady, seriesOrderFor, onClose, onPinned }) {
  const toast = useToast();
  const [useAi, setUseAi] = useState(aiReady);
  // The provider list may arrive after this panel opens; switch AI on once it is known to be configured.
  useEffect(() => { if (aiReady) setUseAi(true); }, [aiReady]);
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const [busy, setBusy] = useState('');
  const req = useRef(0);
  const viewKey = JSON.stringify(view);

  const load = useCallback(async () => {
    const id = ++req.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const { data } = await api.post(`/analytics/${datasetId}/chart-suggestions`, { ...JSON.parse(viewKey), use_ai: useAi });
      if (id === req.current) setState({ data, loading: false, error: null });
    } catch (err) {
      if (id === req.current) setState((s) => ({ ...s, loading: false, error: errorMessage(err) }));
    }
  }, [datasetId, viewKey, useAi]);

  useEffect(() => { load(); }, [load]);

  const pin = async (c) => {
    setBusy(c.id);
    try {
      await api.post(`/analytics/${datasetId}/dashboard/tiles`, { title: c.title, chart_type: c.chart_type, plan: c.plan, reason: c.reason });
      toast.success('Added to the dashboard');
      setState((s) => ({ ...s, data: { ...s.data, charts: s.data.charts.map((x) => (x.id === c.id ? { ...x, pinned: true } : x)) } }));
      onPinned();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy('');
    }
  };

  const data = state.data;
  return (
    <Card className="autocharts">
      <div className="autocharts-head">
        <div>
          <h2 style={{ fontSize: 'var(--fs-md)' }}>Suggested charts</h2>
          <p className="xs muted">{data?.source === 'ai' ? `Picked by ${data.provider} for this dataset` : 'Picked for this dataset'}</p>
        </div>
        <div className="row-wrap">
          {aiReady && <Switch checked={useAi} onChange={setUseAi} label="Use AI" />}
          <Button variant="ghost" size="sm" icon={RefreshCw} onClick={load} loading={state.loading && Boolean(data)} aria-label="Suggest again" title="Suggest again" />
          <Button variant="ghost" size="sm" icon={X} onClick={onClose} aria-label="Close suggested charts" />
        </div>
      </div>
      {state.error && <p className="small" style={{ color: 'var(--danger)', padding: '0 16px 12px' }}>{state.error}</p>}
      <div className="autocharts-grid">
        {!data && state.loading && [0, 1, 2].map((i) => <div key={i} className="suggestion"><Skeleton height={220} /></div>)}
        {data?.charts.map((c) => (
          <div key={c.id} className="suggestion" title={c.reason}>
            <div className="row between" style={{ alignItems: 'flex-start', gap: 8 }}>
              <h3 style={{ fontSize: 'var(--fs-sm)' }}>{c.title}</h3>
              <CalcDrawer details={c.how_calculated} datasetId={datasetId} iconOnly label="How this was calculated" />
            </div>
            {c.chart.spec.type === 'donut'
              ? <DonutChart columns={c.chart.columns} rows={c.chart.rows} height={170} seriesOrder={seriesOrderFor(c.chart.spec.x)} />
              : <ResultChart spec={c.chart.spec} columns={c.chart.columns} rows={c.chart.rows} height={190} seriesOrder={seriesOrderFor(c.chart.spec.series || c.chart.spec.x)} />}
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              {c.pinned
                ? <Button variant="ghost" size="sm" icon={Check} disabled>On dashboard</Button>
                : <Button variant="secondary" size="sm" icon={Pin} loading={busy === c.id} onClick={() => pin(c)}>Add to dashboard</Button>}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

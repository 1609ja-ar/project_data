import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowUp, Check, Database, Pin } from 'lucide-react';
import PageHeader from '../../components/PageHeader.jsx';
import DatasetPicker from '../../components/DatasetPicker.jsx';
import CalcDrawer from '../../components/CalcDrawer.jsx';
import Tile from '../../components/dashboard/Tile.jsx';
import { Badge, Button, Card, EmptyState, Skeleton, useToast } from '../../components/ui/index.js';
import useApi from '../../hooks/useApi.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatKpi, formatRelative } from '../../utils/format.js';

function Answer({ a, datasetId }) {
  const toast = useToast();
  const [pinned, setPinned] = useState(false);
  const [busy, setBusy] = useState(false);
  const kpi = a.chart_type === 'kpi';
  const valueCol = a.tile.chart.columns.find((c) => c.key === 'value');

  const pin = async () => {
    setBusy(true);
    try {
      await api.post(`/analytics/${datasetId}/dashboard/tiles`, { title: a.interpretation.split(' · ')[0], chart_type: a.chart_type, plan: a.plan });
      setPinned(true);
      toast.success('Added to the dashboard');
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="answer">
      <div className="answer-q">{a.question}</div>
      <p className="answer-text">{a.answer}</p>
      {kpi ? (
        <Card className="answer-kpi">
          <span className="xs muted">{a.interpretation}</span>
          <strong className="num">{formatKpi(a.tile.chart.rows[0]?.[0], valueCol)}</strong>
          <div className="row" style={{ gap: 4 }}><CalcDrawer details={a.tile.how_calculated} datasetId={datasetId} label="How calculated" /></div>
        </Card>
      ) : (
        <Tile tile={{ ...a.tile, kind: 'answer', title: a.interpretation.split(' · ')[0], subtitle: a.interpretation.split(' · ').slice(1).join(' · ') }}
          datasetId={datasetId} />
      )}
      <div className="answer-foot">
        {a.ignored?.length > 0 && <span className="xs" style={{ color: 'var(--warning)' }}>Not understood: {a.ignored.join(', ')}</span>}
        {a.source === 'ai' && <Badge>AI</Badge>}
        <span className="grow" />
        {!kpi && (pinned
          ? <Button variant="ghost" size="sm" icon={Check} disabled>On dashboard</Button>
          : <Button variant="secondary" size="sm" icon={Pin} loading={busy} onClick={pin}>Pin to dashboard</Button>)}
        <Link to={`/app/dashboard?dataset=${datasetId}`} className="btn btn-ghost btn-sm">Open dashboard</Link>
      </div>
    </article>
  );
}

export default function Ask() {
  usePageTitle('Ask');
  const [params, setParams] = useSearchParams();
  const datasetId = params.get('dataset');
  const setDataset = useCallback((v) => setParams((p) => { const n = new URLSearchParams(p); n.set('dataset', v); return n; }, { replace: true }), [setParams]);
  const suggestions = useApi(datasetId ? `/ask/${datasetId}/suggestions` : null);
  const recent = useApi(datasetId ? `/ask/${datasetId}/recent` : null);
  const [q, setQ] = useState('');
  const [answers, setAnswers] = useState([]);
  const [state, setState] = useState({ busy: false, error: null });
  const inputRef = useRef(null);

  useEffect(() => { setAnswers([]); setState({ busy: false, error: null }); }, [datasetId]);

  const ask = useCallback(async (question) => {
    const text = question.trim();
    if (text.length < 3 || !datasetId) return;
    setState({ busy: true, error: null });
    try {
      const { data } = await api.post('/ask', { dataset_id: datasetId, question: text });
      setAnswers((list) => [data, ...list].slice(0, 10));
      setQ('');
      recent.reload();
    } catch (err) {
      setState({ busy: false, error: errorMessage(err) });
      return;
    }
    setState({ busy: false, error: null });
  }, [datasetId, recent]);

  // A question passed from the topbar (?q=) is asked once the dataset is known, and only once
  // (effects can run twice in development; the ref makes the request idempotent).
  const incoming = params.get('q');
  const handled = useRef('');
  useEffect(() => {
    if (incoming && datasetId && handled.current !== `${datasetId}|${incoming}`) {
      handled.current = `${datasetId}|${incoming}`;
      ask(incoming);
      setParams((p) => { const n = new URLSearchParams(p); n.delete('q'); return n; }, { replace: true });
    }
  }, [incoming, datasetId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="stack">
      <PageHeader module="ask" title="Ask" actions={<DatasetPicker value={datasetId} onChange={setDataset} label="" />} />
      {!datasetId ? (
        <Card><EmptyState icon={Database} title="No datasets yet" message="Upload a file to ask questions about it."
          action={<Link to="/app/upload" className="btn btn-primary">Upload file</Link>} /></Card>
      ) : (
        <div className="ask-layout">
          <div className="stack">
            <form className="ask-box" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
              <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} maxLength={300} autoFocus
                placeholder="Ask a question, e.g. monthly revenue in North" aria-label="Your question" />
              <Button type="submit" icon={ArrowUp} loading={state.busy} disabled={q.trim().length < 3} aria-label="Ask" />
            </form>
            <div className="chips">
              {(suggestions.data?.items || []).map((s) => (
                <button key={s} type="button" className="suggest-chip" onClick={() => ask(s)} disabled={state.busy}>{s}</button>
              ))}
            </div>
            {state.error && <div className="ask-error" role="alert">{state.error}</div>}
            {state.busy && <Card pad><Skeleton height={22} width="60%" /><Skeleton height={220} style={{ marginTop: 12 }} /></Card>}
            {answers.map((a) => <Answer key={a.analysis_id} a={a} datasetId={datasetId} />)}
            {!answers.length && !state.busy && !state.error && (
              <div className="ask-empty">
                <p className="small muted">Try “top 5 products by revenue”, “average order value by region”, “monthly units in 2024” or “how many orders”.</p>
              </div>
            )}
          </div>
          <Card className="ask-recent">
            <div className="card-header"><h2>Recent questions</h2></div>
            {recent.loading && !recent.data ? <div className="card-body"><Skeleton height={80} /></div> : !recent.data?.items?.length ? (
              <p className="small muted" style={{ padding: 16 }}>Questions you ask appear here.</p>
            ) : (
              <ul className="home-list">
                {recent.data.items.map((r) => (
                  <li key={r.id}>
                    <button type="button" className="recent-q" onClick={() => ask(r.question)} disabled={state.busy}>
                      <span className="small" style={{ fontWeight: 550 }}>{r.question}</span>
                      <span className="xs muted">{r.answer}</span>
                      <span className="xs faint">{formatRelative(r.created_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

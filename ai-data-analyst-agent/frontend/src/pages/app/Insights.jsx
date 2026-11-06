import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import {
  Activity, AlertTriangle, BarChart3, CalendarDays, CircleAlert, Crown, Database, FileText, GitCompare, Info,
  Layers, Lightbulb, MessageSquare, Orbit, PenLine, PieChart, RefreshCw, ShieldCheck, SlidersHorizontal, TrendingUp,
} from 'lucide-react';
import { Moment3D } from '../../components/Moment3D.jsx';
import { InsightRace3D } from '../../three/moments/index.js';
import DatasetPicker from '../../components/DatasetPicker.jsx';
import ResultChart from '../../components/ResultChart.jsx';
import CalcDrawer from '../../components/CalcDrawer.jsx';
import {
  Badge, Button, Card, Drawer, EmptyState, ErrorState, Input, Select, Skeleton, useToast,
} from '../../components/ui/index.js';
import useApi from '../../hooks/useApi.js';
import useDataset from '../../hooks/useDataset.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatInteger } from '../../utils/format.js';

const SEVERITY_TONE = { important: 'danger', notable: 'warning', info: 'info' };
const SEVERITIES = [['important', 'Act on', CircleAlert], ['notable', 'Worth a look', AlertTriangle], ['info', 'Good to know', Info]];
const TYPE = {
  top_contributor: ['Top contributor', Crown, 'One group accounts for a large part of the total. Results depend heavily on it.'],
  concentration: ['Concentration', PieChart, 'A few groups hold most of the total (Pareto pattern). Risk and opportunity sit with them.'],
  trend: ['Trend', TrendingUp, 'The measure moves steadily in one direction over complete periods, not just noise.'],
  period_change: ['Period change', Activity, 'The latest complete period differs clearly from the one before it.'],
  weekday_pattern: ['Weekday pattern', CalendarDays, 'Some days of the week are consistently stronger or weaker than others.'],
  anomaly: ['Anomaly (screening)', AlertTriangle, 'A period stands out from the usual range. Check whether it is real or a data issue.'],
  relationship: ['Relationship', GitCompare, 'Two measures move together. That is correlation, not proof that one causes the other.'],
  segment_difference: ['Segment difference', Layers, 'Two groups differ more than chance would explain. Worth understanding why.'],
  distribution: ['Distribution', BarChart3, 'The values are skewed or have a long tail, so averages can mislead; medians help.'],
  data_quality: ['Data quality', ShieldCheck, 'Something in the data itself needs attention before relying on related figures.'],
};


const TIME_TYPES = new Set(['trend', 'anomaly', 'period_change', 'weekday_pattern']);
const BY_GROUP_TYPES = new Set(['top_contributor', 'concentration', 'segment_difference']);

/** A follow-up question for the Ask page, from the insight type and the columns it is about. */
export function followUp(insight) {
  const cols = (insight.evidence.columns || []).map((k) => k.replace(/_/g, ' '));
  const measure = cols.find((c) => !/\b(date|time|day|month|year|week)\b/.test(c));
  if (TIME_TYPES.has(insight.type) && measure) return `${measure} over time`;
  if (BY_GROUP_TYPES.has(insight.type) && cols.length >= 2) return `total ${cols[0]} by ${cols[1]}`;
  return null;
}

/** The insight sentence without test statistics (p, R², r, Cohen's d, n); those stay in "How calculated". */
export function plainDetail(text) {
  return text
    .replace(/Welch t-test,?\s*/g, '')
    .replace(/[;,]?\s*(p|R²|r|Cohen's d|n)\s*=\s*[^;),]+(\s+and\s+[^;),]+)?/g, '')
    .replace(/\(\s*[;,]?\s*\)/g, '')
    .replace(/\(\s*[;,]\s*/g, '(')
    .replace(/\s+([.,)])/g, '$1');
}

function EvidenceDrawer({ insight }) {
  const [open, setOpen] = useState(false);
  const e = insight.evidence;
  return (
    <>
      <Button variant="ghost" size="sm" icon={Info} onClick={() => setOpen(true)}>How calculated</Button>
      <Drawer open={open} onClose={() => setOpen(false)} title="How this insight was calculated">
        <p className="small">{insight.detail}</p>
        <dl className="stack-sm" style={{ margin: 0 }}>
          <dt className="xs muted">Filters</dt><dd style={{ margin: 0 }}>{e.filters.join(' · ')}</dd>
          <dt className="xs muted">Rows</dt><dd style={{ margin: 0 }} className="num">{formatInteger(e.rows_used)} used · {formatInteger(e.rows_skipped)} skipped</dd>
          <dt className="xs muted">Engine</dt><dd style={{ margin: 0 }}>Pandas + SciPy statistics on the cleaned data.</dd>
        </dl>
      </Drawer>
    </>
  );
}

function InsightRow({ insight, active, onClick }) {
  const [label, Icon] = TYPE[insight.type] || [insight.type, Lightbulb];
  return (
    <button type="button" className="ins-row" data-active={active} data-tone={SEVERITY_TONE[insight.severity]} onClick={onClick}>
      <span className="ins-icon" aria-hidden="true"><Icon size={16} /></span>
      <span className="grow" style={{ minWidth: 0 }}>
        <span className="xs muted">{label}</span>
        <span className="ins-headline">{insight.headline}</span>
      </span>
      <Badge tone={SEVERITY_TONE[insight.severity]}>{insight.severity}</Badge>
    </button>
  );
}

function Detail({ insight, datasetId, aiReady, analysisId }) {
  const toast = useToast();
  const [explain, setExplain] = useState(null);
  useEffect(() => setExplain(null), [insight.id]);
  const [label, Icon] = TYPE[insight.type] || [insight.type, Lightbulb];
  const chart = insight.suggested_chart_spec;
  const question = followUp(insight);

  const doExplain = async () => {
    setExplain({ loading: true });
    try {
      const { data } = await api.post(`/analytics/${datasetId}/insights/explain`, { analysis_id: analysisId, insight_ids: [insight.id] });
      setExplain(data);
    } catch (err) {
      setExplain(null);
      toast.error(errorMessage(err));
    }
  };

  return (
    <Card className="ins-detail" data-tone={SEVERITY_TONE[insight.severity]}>
      <div className="ins-detail-head">
        <span className="ins-icon lg" aria-hidden="true"><Icon size={20} /></span>
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 6 }}><Badge tone={SEVERITY_TONE[insight.severity]}>{insight.severity}</Badge><span className="xs muted">{label}</span></div>
          <h2 style={{ marginTop: 6 }}>{insight.headline}</h2>
        </div>
      </div>
      <div className="ins-detail-body">
        {chart && <div className="ins-chart"><ResultChart spec={chart.spec} columns={chart.columns} rows={chart.rows} height={230} /></div>}
        <p className="small">{plainDetail(insight.detail)}</p>
        {insight.caveats.length > 0 && <p className="xs muted">{insight.caveats[0]}</p>}
        {explain && (
          <div className="ins-ai">
            <div className="row" style={{ gap: 6, marginBottom: 6 }}><PenLine size={15} aria-hidden="true" /><strong className="small">In plain words</strong>
              {!explain.loading && <Badge tone={explain.unverified?.length ? 'warning' : 'success'}>{explain.label}</Badge>}</div>
            {explain.loading ? <Skeleton height={60} /> : <p className="small" style={{ whiteSpace: 'pre-wrap' }}>{explain.text}</p>}
          </div>
        )}
        <div className="row-wrap ins-actions">
          {question && <Link to={`/app/ask?dataset=${datasetId}&q=${encodeURIComponent(question)}`} className="btn btn-primary btn-sm"><MessageSquare size={14} /> Ask: {question}</Link>}
          <Link to={`/app/dashboard?dataset=${datasetId}`} className="btn btn-secondary btn-sm"><BarChart3 size={14} /> Dashboard</Link>
          <Link to={`/app/reports?dataset=${datasetId}&new=1`} className="btn btn-secondary btn-sm"><FileText size={14} /> Add to a report</Link>
          {aiReady && <Button variant="ghost" size="sm" icon={PenLine} onClick={doExplain} loading={explain?.loading}>Explain</Button>}
          {insight.how_calculated ? <CalcDrawer details={insight.how_calculated} datasetId={datasetId} label="How calculated" /> : <EvidenceDrawer insight={insight} />}
        </div>
      </div>
    </Card>
  );
}

export default function Insights() {
  usePageTitle('Insights');
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const datasetId = params.get('dataset');
  const setDataset = useCallback((v) => setParams({ dataset: v }, { replace: true }), [setParams]);
  const { dataset } = useDataset(datasetId);
  const providers = useApi('/ai/providers');
  const [opts, setOpts] = useState({ focus_measure: '', date_from: '', date_to: '', max_insights: '15' });
  const [showOpts, setShowOpts] = useState(false);
  const [state, setState] = useState({ data: null, loading: false, error: null });
  const [severity, setSeverity] = useState('');
  const [selected, setSelected] = useState(null);
  const [ranking, setRanking] = useState(false);

  const numericCols = useMemo(() => (dataset?.active_version?.schema || []).filter((c) => ['integer', 'float', 'decimal'].includes(c.dtype) && c.semantic_type !== 'id'), [dataset]);
  const hasDate = (dataset?.active_version?.schema || []).some((c) => c.dtype === 'date' || c.dtype === 'datetime');

  useEffect(() => {
    if (!datasetId) return;
    setState({ data: null, loading: true, error: null });
    api.get(`/analytics/${datasetId}/insights`)
      .then(({ data }) => setState({ data: data.insights ? data : null, loading: false, error: null }))
      .catch((err) => setState({ data: null, loading: false, error: errorMessage(err) }));
  }, [datasetId]);

  const generate = async (refresh) => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const { data } = await api.post(`/analytics/${datasetId}/insights`, {
        focus_measure: opts.focus_measure || null, date_from: opts.date_from || null, date_to: opts.date_to || null,
        max_insights: Number(opts.max_insights), refresh,
      });
      setState({ data, loading: false, error: null });
    } catch (err) {
      setState((s) => ({ ...s, loading: false, error: errorMessage(err) }));
    }
  };

  const data = state.data;
  const all = useMemo(() => data?.insights || [], [data]);
  const counts = Object.fromEntries(SEVERITIES.map(([k]) => [k, all.filter((i) => i.severity === k).length]));
  const shown = all.filter((i) => !severity || i.severity === severity);
  const hash = location.hash.slice(1);
  useEffect(() => {
    if (!all.length) return;
    setSelected((cur) => (all.some((i) => i.id === cur) ? cur : (all.find((i) => i.id === hash) || all[0]).id));
  }, [all, hash]);
  const current = shown.find((i) => i.id === selected) || shown[0];
  const aiReady = Boolean(providers.data?.active);

  return (
    <div className="stack">
      <div className="dash-head" style={{ marginBottom: 0 }}>
        <div>
          <div className="dash-title" style={{ '--mc': 'var(--m-insights)' }}><span className="page-icon"><Lightbulb size={18} /></span><h1>Insights</h1></div>
        </div>
        <div className="row-wrap" style={{ alignItems: 'flex-end' }}>
          <DatasetPicker value={datasetId} onChange={setDataset} />
          {data?.insights?.length > 1 && <Button variant="secondary" icon={Orbit} onClick={() => setRanking(true)}>3D ranking</Button>}
          {datasetId && <Button variant="secondary" icon={SlidersHorizontal} onClick={() => setShowOpts((s) => !s)} aria-pressed={showOpts}>Options</Button>}
          {datasetId && <Button icon={data ? RefreshCw : Lightbulb} loading={state.loading} onClick={() => generate(Boolean(data))}>{data ? 'Re-run' : 'Find insights'}</Button>}
        </div>
      </div>
      {!datasetId ? (
        <Card><EmptyState icon={Database} title="No cleaned datasets yet" message="Upload a dataset to find insights." action={<Link to="/app/upload" className="btn btn-primary">Upload file</Link>} /></Card>
      ) : (
        <>
          {showOpts && (
            <Card pad>
              <div className="grid-4" style={{ alignItems: 'end' }}>
                <Select label="Focus measure" value={opts.focus_measure} onChange={(e) => setOpts((o) => ({ ...o, focus_measure: e.target.value }))}
                  options={[{ value: '', label: 'Automatic' }, ...numericCols.map((c) => ({ value: c.key, label: c.display_name }))]} />
                <Input label="From date" type="date" value={opts.date_from} disabled={!hasDate} onChange={(e) => setOpts((o) => ({ ...o, date_from: e.target.value }))} />
                <Input label="To date" type="date" value={opts.date_to} disabled={!hasDate} onChange={(e) => setOpts((o) => ({ ...o, date_to: e.target.value }))} />
                <Button onClick={() => generate(true)} loading={state.loading}>Apply and re-run</Button>
              </div>
            </Card>
          )}
          {state.error && <ErrorState message={state.error} onRetry={() => generate(false)} />}
          {state.loading && !data && <div className="ins-layout"><Card pad><Skeleton height={320} /></Card><Card pad><Skeleton height={320} /></Card></div>}
          {!state.loading && !state.error && !data && (
            <Card><EmptyState icon={Lightbulb} title="No insights yet" message="Find top contributors, trends, anomalies, segment differences and data-quality issues in one run."
              action={<Button icon={Lightbulb} onClick={() => generate(false)}>Find insights</Button>} /></Card>
          )}
          {data && (
            <>
              <div className="ins-summary">
                {SEVERITIES.map(([k, l, Icon]) => (
                  <button key={k} type="button" className="ins-stat" data-tone={SEVERITY_TONE[k]} aria-pressed={severity === k}
                    onClick={() => setSeverity((s) => (s === k ? '' : k))}>
                    <span className="ins-stat-icon" aria-hidden="true"><Icon size={18} /></span>
                    <span><strong className="num">{counts[k]}</strong> <span className="small">{l}</span></span>
                  </button>
                ))}
              </div>
              {shown.length === 0 ? (
                <Card><EmptyState icon={Lightbulb} title="Nothing to show" message={all.length ? 'No insight has this severity.' : 'No pattern passed the evidence thresholds. That is a valid result, not an error.'} /></Card>
              ) : (
                <div className="ins-layout">
                  <Card className="ins-list" aria-label="Insights">
                    {shown.map((i) => <InsightRow key={i.id} insight={i} active={current?.id === i.id} onClick={() => setSelected(i.id)} />)}
                  </Card>
                  {current && <Detail insight={current} datasetId={datasetId} aiReady={aiReady} analysisId={data.analysis_id} />}
                </div>
              )}
              {data.skipped?.length > 0 && (
                <details className="small muted"><summary>Checks that were not run ({data.skipped.length})</summary>
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{data.skipped.map((s, k) => <li key={k}>{s.detector}: {s.reason}</li>)}</ul>
                </details>
              )}
            </>
          )}
        </>
      )}
      {data?.insights?.length > 1 && (
        <Moment3D open={ranking} onClose={() => setRanking(false)} title="Insights ranked"
          caption="Findings are ranked by severity first (red: act on, amber: worth a look, blue: good to know), then by score. Height shows that score (effect size × share of the data × strength of evidence), so heights are only comparable within a colour. Click a column to open that insight."
          scene={InsightRace3D}
          sceneProps={{ items: data.insights.map((i) => ({ id: i.id, headline: i.headline, score: i.score, severity: i.severity })),
            onPick: (id) => { setSeverity(''); setSelected(id); setRanking(false); } }} />
      )}
    </div>
  );
}

import { lazy, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, ArrowUp, BarChart3, Database, FileText, Target } from 'lucide-react';
import KpiCard from '../../components/dashboard/KpiCard.jsx';
import ResultChart from '../../components/ResultChart.jsx';
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Skeleton, useToast } from '../../components/ui/index.js';
import useApi from '../../hooks/useApi.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import useThemeColors from '../../hooks/useThemeColors.js';
import { STATUS_LABEL, STATUS_TONE } from '../../hooks/useDataset.js';
import { MODULES } from '../../layouts/nav.js';
import Lazy3D from '../../three/Lazy3D.jsx';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { useAuth } from '../../context/AuthContext.jsx';
import { formatCell, formatInteger, formatKpi, formatPercent, formatRelative } from '../../utils/format.js';

const DataBars3D = lazy(() => import('../../three/DataBars3D.jsx'));
const City3D = lazy(() => import('../../three/City3D.jsx'));
const ANALYSIS_LABELS = { profile: 'Profile', query: 'Query', sql: 'SQL', insights: 'Insights', chart: 'Chart', dashboard: 'Dashboard', ask: 'Ask' };
const SEVERITY_TONE = { important: 'danger', notable: 'warning', info: 'info' };

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

function HeroVisual({ dash, latest }) {
  const c = useThemeColors();
  // The latest dataset in 3D: a period x category city when there is a split trend, else ranked bars.
  const split = dash?.tiles.find((t) => t.kind === 'split');
  const bars = dash?.tiles.find((t) => t.kind === 'share' || t.kind === 'breakdown');
  const items = useMemo(() => {
    if (!bars) return [];
    const xi = bars.chart.columns.findIndex((col) => col.key === bars.chart.spec.x);
    const yi = bars.chart.columns.findIndex((col) => col.key === 'value');
    return bars.chart.rows.slice(0, 8).map((r, i) => ({ label: r[xi] == null ? '(empty)' : String(r[xi]), raw: r[xi], value: Number(r[yi]) || 0, text: formatCell(r[yi], bars.chart.columns[yi]), color: c.series[i % c.series.length] }));
  }, [bars, c.series]);
  if (split) {
    const order = dash.dimensions.find((d) => d.key === split.chart.spec.series)?.values;
    return (
      <>
        <Lazy3D scene={City3D} height={250} label={`3D view: ${split.title}`} sceneProps={{ columns: split.chart.columns, rows: split.chart.rows, spec: split.chart.spec, seriesOrder: order }}
          fallback={<ResultChart spec={split.chart.spec} columns={split.chart.columns} rows={split.chart.rows} height={230} seriesOrder={order} />} />
        <span className="hero-caption">{split.title} · {latest.filename}</span>
      </>
    );
  }
  if (items.length > 1) {
    return (
      <>
        <Lazy3D scene={DataBars3D} height={240} label={`3D chart: ${bars.title}`} sceneProps={{ items }}
          fallback={<ResultChart spec={{ type: 'horizontal_bar', x: bars.chart.spec.x, y: 'value' }} columns={bars.chart.columns} rows={bars.chart.rows} height={220} />} />
        <span className="hero-caption">{bars.title} · {latest.filename}</span>
      </>
    );
  }
  return <div className="hero-placeholder"><BarChart3 size={40} /><span className="small muted">Upload a file to see it here.</span></div>;
}

const ACTIONS = [
  { module: 'upload', to: '/app/upload' },
  { module: 'dashboard', to: '/app/dashboard', latest: true },
  { module: 'ask', to: '/app/ask', latest: true },
  { module: 'insights', to: '/app/insights', latest: true },
  { module: 'reports', to: '/app/reports?new=1', latest: true, label: 'New report' },
  { module: 'exports', to: '/app/exports', latest: true },
];

function Findings({ findings, onGenerated }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!findings) return <EmptyState icon={BarChart3} title="No findings yet" message="Findings for your latest dataset appear here." />;
  const generate = async () => {
    setBusy(true);
    try {
      await api.post(`/analytics/${findings.dataset_id}/insights`, {});
      onGenerated();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  if (findings.insights === null) {
    return <EmptyState icon={BarChart3} title="Not analysed yet" message={findings.dataset_name} action={<Button variant="secondary" loading={busy} onClick={generate}>Find insights</Button>} />;
  }
  if (!findings.insights.length) return <EmptyState icon={BarChart3} title="Nothing stands out" message={findings.dataset_name} />;
  return (
    <ul className="home-list">
      {findings.insights.map((i) => (
        <li key={i.id}>
          <Link to={`/app/insights?dataset=${findings.dataset_id}#${i.id}`} className="home-finding" data-tone={SEVERITY_TONE[i.severity]}>
            <span className="small" style={{ fontWeight: 550 }}>{i.headline}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Targets({ kpis, datasetId }) {
  const withGoal = kpis.filter((k) => k.goal);
  if (!withGoal.length) {
    return (
      <div className="targets-empty">
        <Target size={18} aria-hidden="true" />
        <span className="small muted">No targets yet. Use the target button on a dashboard KPI.</span>
        <Link to={`/app/dashboard?dataset=${datasetId}`} className="btn btn-secondary btn-sm">Set a target</Link>
      </div>
    );
  }
  return (
    <ul className="targets">
      {withGoal.map((k) => {
        const met = k.goal.direction === 'at_most' ? k.goal.progress <= 1 : k.goal.progress >= 1;
        return (
          <li key={k.key}>
            <div className="row between"><span className="small" style={{ fontWeight: 550 }}>{k.label}</span><Badge tone={met ? 'success' : 'warning'}>{met ? 'On target' : 'Behind'}</Badge></div>
            <div className="goal" data-met={met}><div className="goal-bar"><span style={{ width: `${Math.min(100, k.goal.progress * 100)}%` }} /></div></div>
            <span className="xs muted num">{formatKpi(k.value, k.column)} of {formatKpi(k.goal.target, k.column)} · {formatPercent(k.goal.progress, 0)}</span>
          </li>
        );
      })}
    </ul>
  );
}

export default function Overview() {
  usePageTitle('Home');
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data, loading, error, reload } = useApi('/dashboard/summary');
  const latest = data?.recent_datasets.find((d) => d.active_version_id);
  const dash = useApi(latest ? `/analytics/${latest.id}/dashboard` : null, { method: 'post' });
  const reports = useApi('/reports', { params: { limit: 4 } });
  const [q, setQ] = useState('');

  if (loading && !data) return <div className="stack"><Skeleton height={260} radius="var(--r-xl)" /><Card pad><Skeleton height={200} /></Card></div>;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  const trend = dash.data?.tiles.find((t) => t.kind === 'trend');
  const ask = (e) => {
    e.preventDefault();
    if (q.trim().length >= 3 && latest) navigate(`/app/ask?dataset=${latest.id}&q=${encodeURIComponent(q.trim())}`);
  };

  return (
    <div className="stack">
      <section className="home-hero">
        <div className="home-hero-text">
          <h1>{greeting()}, {user.full_name.split(' ')[0]}</h1>
          {latest ? (
            <>
              <form className="ask-box hero-ask" onSubmit={ask}>
                <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={300} placeholder={`Ask about ${latest.filename}`} aria-label={`Ask about ${latest.filename}`} />
                <Button type="submit" icon={ArrowUp} disabled={q.trim().length < 3} aria-label="Ask" />
              </form>
              <div className="row-wrap" style={{ marginTop: 12 }}>
                <Link to={`/app/dashboard?dataset=${latest.id}`} className="btn btn-primary"><BarChart3 size={15} /> Open dashboard</Link>
                <Link to="/app/upload" className="btn btn-secondary">Upload file</Link>
              </div>
            </>
          ) : (
            <div className="row-wrap" style={{ marginTop: 16 }}><Link to="/app/upload" className="btn btn-primary">Upload your first file</Link></div>
          )}
        </div>
        <div className="home-hero-visual">{latest ? <HeroVisual dash={dash.data} latest={latest} /> : <HeroVisual />}</div>
      </section>

      <div className="home-actions">
        {ACTIONS.map((a) => {
          const m = MODULES[a.module];
          const to = a.latest && latest ? `${a.to}${a.to.includes('?') ? '&' : '?'}dataset=${latest.id}` : a.to;
          return (
            <Link key={a.module} to={to} className="home-action" style={{ '--mc': `var(--m-${a.module})` }}>
              <span className="page-icon sm" aria-hidden="true"><m.icon size={16} /></span>
              <strong className="small">{a.label || m.label}</strong>
              <ArrowRight size={14} className="home-action-arrow" aria-hidden="true" />
            </Link>
          );
        })}
      </div>

      {latest && (
        <section>
          <div className="row between" style={{ marginBottom: 8 }}>
            <div className="section-label" style={{ margin: 0 }}>{latest.filename}</div>
            <Link to={`/app/dashboard?dataset=${latest.id}`} className="small">Dashboard <ArrowRight size={13} /></Link>
          </div>
          {dash.loading && !dash.data ? <div className="dash-kpis">{[0, 1, 2, 3].map((i) => <Card key={i} pad><Skeleton height={90} /></Card>)}</div> : dash.data && (
            <>
              <div className="dash-kpis">{dash.data.kpis.map((k, i) => <KpiCard key={k.id} kpi={k} datasetId={latest.id} accent={[0, 6, 2, 1][i] ?? i} />)}</div>
              <div className="home-row">
                {trend && (
                  <Card className="tile">
                    <div className="tile-head"><div><h3>{trend.title}</h3><p>{trend.subtitle}</p></div></div>
                    <div className="tile-body"><ResultChart spec={{ ...trend.chart.spec, type: 'area' }} columns={trend.chart.columns} rows={trend.chart.rows} height={210} /></div>
                  </Card>
                )}
                <Card>
                  <CardHeader title="Targets" />
                  <Targets kpis={dash.data.kpis} datasetId={latest.id} />
                </Card>
              </div>
            </>
          )}
        </section>
      )}

      <div className="home-grid">
        <Card className="home-datasets">
          <CardHeader title="Datasets" actions={data.recent_datasets.length > 0 && <Link to="/app/datasets" className="small">All</Link>} />
          {data.recent_datasets.length === 0 ? (
            <EmptyState icon={Database} title="No datasets yet" action={<Link to="/app/upload" className="btn btn-primary">Upload file</Link>} />
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="table">
                <thead><tr><th>Name</th><th className="num">Rows</th><th>Status</th><th>Uploaded</th><th aria-label="Actions" /></tr></thead>
                <tbody>
                  {data.recent_datasets.map((d) => (
                    <tr key={d.id}>
                      <td><Link to={`/app/datasets/${d.id}`} style={{ fontWeight: 550 }}>{d.filename}</Link></td>
                      <td className="num">{formatInteger(d.row_count)}</td>
                      <td><Badge tone={STATUS_TONE[d.cleaning_status]}>{STATUS_LABEL[d.cleaning_status] || d.cleaning_status}</Badge></td>
                      <td className="muted">{formatRelative(d.created_at)}</td>
                      <td style={{ textAlign: 'right' }}>{d.active_version_id && <Link to={`/app/dashboard?dataset=${d.id}`} className="btn btn-secondary btn-sm"><BarChart3 size={14} /> Dashboard</Link>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card style={{ '--mc': 'var(--m-insights)' }}>
          <CardHeader title="Findings" actions={data.important_findings && <Link to={`/app/insights?dataset=${data.important_findings.dataset_id}`} className="small">All</Link>} />
          <Findings findings={data.important_findings} onGenerated={reload} />
        </Card>
        <Card>
          <CardHeader title="Reports" actions={<Link to="/app/reports?new=1" className="small">New</Link>} />
          {!reports.data?.items?.length ? <EmptyState icon={FileText} title="No reports yet" /> : (
            <ul className="home-list">
              {reports.data.items.map((r) => (
                <li key={r.id}><Link to={`/app/reports/${r.id}`} className="home-report">
                  <FileText size={15} aria-hidden="true" /><span className="grow" style={{ minWidth: 0 }}><span className="small" style={{ fontWeight: 550 }}>{r.title}</span><br />
                    <span className="xs muted">{r.dataset_name} · {formatRelative(r.created_at)}</span></span>
                </Link></li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <CardHeader title="Activity" />
          {data.recent_analyses.length === 0 ? <EmptyState icon={BarChart3} title="No activity yet" /> : (
            <ul className="home-list">
              {data.recent_analyses.map((a) => (
                <li key={a.id} className="row between" style={{ padding: '9px 16px', gap: 12 }}>
                  <span className="row grow" style={{ minWidth: 0 }}>
                    <Badge>{ANALYSIS_LABELS[a.analysis_type] || a.analysis_type}</Badge>
                    <span className="small" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.analysis_type === 'dashboard' ? a.dataset_name : a.question || a.dataset_name}</span>
                  </span>
                  <span className="xs muted" style={{ whiteSpace: 'nowrap' }}>{formatRelative(a.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

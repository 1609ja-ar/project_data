import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { BarChart3, CheckCircle2, Database, Download, FileSpreadsheet, FileText, LayoutGrid, Link2, RefreshCw, Upload, X } from 'lucide-react';
import AutoCharts from '../../components/dashboard/AutoCharts.jsx';
import InsightsStrip from '../../components/dashboard/InsightsStrip.jsx';
import KpiCard from '../../components/dashboard/KpiCard.jsx';
import ShareDialog from '../../components/dashboard/ShareDialog.jsx';
import MultiSelect from '../../components/dashboard/MultiSelect.jsx';
import Tile from '../../components/dashboard/Tile.jsx';
import { Button, Card, EmptyState, ErrorState, Skeleton, useToast } from '../../components/ui/index.js';
import useApi from '../../hooks/useApi.js';
import useDataset from '../../hooks/useDataset.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatInteger, formatKpi } from '../../utils/format.js';
import CleaningReplay from '../../components/CleaningReplay.jsx';
import { CleanDownloadButton } from '../../components/CleanDownload.jsx';

const GRAINS = [['', 'Auto'], ['day', 'Day'], ['week', 'Week'], ['month', 'Month'], ['quarter', 'Quarter'], ['year', 'Year']];
const PRESETS = [['all', 'All dates'], ['30d', 'Last 30 days'], ['90d', 'Last 90 days'], ['12m', 'Last 12 months'], ['ytd', 'Year to date']];
// Grid spans for whatever tiles the backend chose: trend + donut share a row, bars pair up, a lone bar is full width.
function spans(tiles) {
  const hasTrend = tiles.some((t) => t.kind === 'trend');
  const hasShare = tiles.some((t) => t.kind === 'share');
  const bars = tiles.filter((t) => t.kind === 'breakdown');
  const offset = !hasTrend && hasShare ? 1 : 0; // without a trend the donut pairs with the first bar chart
  return tiles.map((t) => {
    if (t.kind === 'trend') return hasShare ? 'span-8' : 'span-12';
    if (t.kind === 'share') return hasTrend ? 'span-4' : bars.length ? 'span-6' : 'span-12';
    if (t.kind === 'breakdown') {
      const n = bars.length + offset;
      return n % 2 === 1 && bars.indexOf(t) + offset === n - 1 ? 'span-12' : 'span-6';
    }
    return 'span-12';
  });
}

// ---- URL <-> options. Filters live in the URL so a view survives refresh and can be bookmarked.
function readOptions(params) {
  const filters = {};
  params.getAll('f').forEach((f) => {
    const i = f.indexOf(':');
    if (i > 0) (filters[f.slice(0, i)] ||= []).push(f.slice(i + 1));
  });
  return {
    measure: params.get('m') || '', aggregation: params.get('agg') || '', grain: params.get('grain') || '',
    from: params.get('from') || '', to: params.get('to') || '', filters,
  };
}

function writeParams(datasetId, o) {
  const p = new URLSearchParams();
  if (datasetId) p.set('dataset', datasetId);
  if (o.measure) p.set('m', o.measure);
  if (o.aggregation) p.set('agg', o.aggregation);
  if (o.grain) p.set('grain', o.grain);
  if (o.from) p.set('from', o.from);
  if (o.to) p.set('to', o.to);
  Object.entries(o.filters).forEach(([k, vals]) => vals.forEach((v) => p.append('f', `${k}:${v}`)));
  return p;
}

function iso(d) {
  return d.toISOString().slice(0, 10);
}

// Presets are relative to the newest date in the data, not today: uploaded files are often historical.
function presetRange(key, maxDate) {
  if (key === 'all' || !maxDate) return { from: '', to: '' };
  const end = new Date(`${maxDate}T00:00:00Z`);
  const start = new Date(end);
  if (key === '30d') start.setUTCDate(start.getUTCDate() - 29);
  if (key === '90d') start.setUTCDate(start.getUTCDate() - 89);
  if (key === '12m') { start.setUTCFullYear(start.getUTCFullYear() - 1); start.setUTCDate(start.getUTCDate() + 1); }
  if (key === 'ytd') { start.setUTCMonth(0); start.setUTCDate(1); }
  return { from: iso(start), to: maxDate };
}

function DatasetSwitcher({ value, onChange }) {
  const [items, setItems] = useState(null);
  useEffect(() => {
    api.get('/datasets', { params: { page_size: 100 } })
      .then(({ data }) => setItems(data.items.filter((d) => d.active_version_id)))
      .catch(() => setItems([]));
  }, []);
  useEffect(() => { if (items?.length && !value) onChange(items[0].id); }, [items, value, onChange]);
  if (!items) return <Skeleton height={30} width={200} />;
  if (!items.length) return null;
  return (
    <select className="fselect" aria-label="Dataset" value={value || ''} onChange={(e) => onChange(e.target.value)} style={{ maxWidth: 260 }}>
      {items.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
    </select>
  );
}

function DashboardSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading dashboard">
      <div className="dash-kpis">{[0, 1, 2, 3].map((i) => <Card key={i} pad><Skeleton width={120} /><Skeleton height={30} width={140} style={{ marginTop: 10 }} /><Skeleton height={36} style={{ marginTop: 10 }} /></Card>)}</div>
      <div className="dash-grid">
        <Card pad className="span-8"><Skeleton height={280} /></Card>
        <Card pad className="span-4"><Skeleton height={280} /></Card>
      </div>
    </div>
  );
}

export default function Dashboard() {
  usePageTitle('Dashboard');
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const datasetId = params.get('dataset');
  const opts = useMemo(() => readOptions(params), [params]);
  const { dataset } = useDataset(datasetId);
  const [state, setState] = useState({ data: null, loading: false, error: null });
  const [notice, setNotice] = useState(Boolean(location.state?.uploaded));
  const [auto, setAuto] = useState(Boolean(location.state?.uploaded) || params.get('auto') === '1');
  const [sharing, setSharing] = useState(false);
  const providers = useApi('/ai/providers');
  const toast = useToast();
  const req = useRef(0);
  const ready = dataset?.cleaning_status === 'done' && dataset?.active_version_id;

  const update = useCallback((patch) => setParams(writeParams(datasetId, { ...opts, ...patch })), [datasetId, opts, setParams]);
  const setDataset = useCallback((id) => setParams(writeParams(id, { measure: '', aggregation: '', grain: '', from: '', to: '', filters: {} }), { replace: !datasetId }), [setParams, datasetId]);

  const load = useCallback(async (refresh = false) => {
    if (!datasetId || !ready) return;
    const id = ++req.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    const body = {
      measure: opts.measure || null, aggregation: opts.aggregation || null, grain: opts.grain || null,
      date_from: opts.from || null, date_to: opts.to || null, refresh,
      filters: Object.entries(opts.filters).filter(([, v]) => v.length).map(([column, values]) => ({ column, values })),
    };
    try {
      const { data } = await api.post(`/analytics/${datasetId}/dashboard`, body);
      if (id === req.current) setState({ data, loading: false, error: null });
    } catch (err) {
      if (id === req.current) setState((s) => ({ ...s, loading: false, error: errorMessage(err) }));
    }
  }, [datasetId, ready, opts]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setState({ data: null, loading: false, error: null }); }, [datasetId]);

  const data = state.data;
  const toggleValue = useCallback((dim, value) => {
    const cur = opts.filters[dim] || [];
    const v = String(value);
    const next = cur.length === 1 && cur[0] === v ? [] : [v];
    update({ filters: { ...opts.filters, [dim]: next } });
  }, [opts.filters, update]);

  const preset = useMemo(() => {
    if (!opts.from && !opts.to) return 'all';
    const hit = PRESETS.find(([k]) => k !== 'all' && (() => { const r = presetRange(k, data?.date_bounds?.max); return r.from === opts.from && r.to === opts.to; })());
    return hit ? hit[0] : 'custom';
  }, [opts.from, opts.to, data?.date_bounds?.max]);

  const activeFilters = Object.entries(opts.filters).filter(([, v]) => v.length);
  const dimLabel = (k) => data?.dimensions.find((d) => d.key === k)?.label || k;
  const hasFilters = activeFilters.length > 0 || opts.from || opts.to;
  const tileSpans = useMemo(() => spans(data?.tiles || []), [data]);
  const sharePreview = useMemo(() => data && {
    kpis: data.kpis.slice(0, 3).map((k) => ({ label: k.label, text: formatKpi(k.value, k.column) })),
    bars: (data.kpis[0]?.spark || []).map((p) => p.value).filter((v) => typeof v === 'number' && v >= 0),
  }, [data]);
  const seriesOrderFor = useCallback((key) => data?.dimensions.find((d) => d.key === key)?.values, [data]);
  const viewBody = useMemo(() => ({
    date_from: opts.from || null, date_to: opts.to || null, grain: opts.grain || null,
    filters: Object.entries(opts.filters).filter(([, v]) => v.length).map(([column, values]) => ({ column, values })),
  }), [opts]);
  const setGoal = async (key, target) => {
    try {
      if (target == null) await api.delete(`/analytics/${datasetId}/goals/${encodeURIComponent(key)}`);
      else await api.put(`/analytics/${datasetId}/goals`, { key, target });
      toast.success(target == null ? 'Target removed' : 'Target saved');
      load();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };
  const unpin = async (tileId) => {
    try {
      await api.delete(`/analytics/${datasetId}/dashboard/tiles/${tileId}`);
      toast.success('Removed from the dashboard');
      load();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  if (!datasetId) {
    return (
      <div className="stack">
        <div className="dash-head"><div className="dash-title" style={{ '--mc': 'var(--m-dashboard)' }}><span className="page-icon"><BarChart3 size={18} /></span><h1>Dashboard</h1></div><DatasetSwitcher value={datasetId} onChange={setDataset} /></div>
        <Card>
          <EmptyState icon={Database} title="No datasets yet" message="Upload a CSV or Excel file. A dashboard is built for it automatically as soon as cleaning finishes."
            action={<Link to="/app/upload" className="btn btn-primary"><Upload size={15} aria-hidden="true" /> Upload a file</Link>} />
        </Card>
      </div>
    );
  }

  return (
    <div>
      <div className="dash-head">
        <div style={{ minWidth: 0 }}>
          <div className="dash-title" style={{ '--mc': 'var(--m-dashboard)' }}><span className="page-icon" aria-hidden="true"><BarChart3 size={18} /></span><h1 title={dataset?.filename}>{dataset?.filename || 'Dashboard'}</h1></div>
          {data && (
            <div className="dash-meta">
              <span className="num">{formatInteger(data.rows_in_view)}{data.rows_in_view !== data.row_count && ` of ${formatInteger(data.row_count)}`} records</span>
              {data.view_bounds?.min && <><span className="sep">|</span><span className="num">{data.view_bounds.min} – {data.view_bounds.max}</span></>}
              <span className="sep">|</span><span>v{data.dataset_version}</span>
            </div>
          )}
        </div>
        <div className="row-wrap">
          <DatasetSwitcher value={datasetId} onChange={setDataset} />
          <Button variant="secondary" size="sm" icon={RefreshCw} loading={state.loading && Boolean(data)} onClick={() => load(true)} aria-label="Recalculate" title="Recalculate" />
          <Link to={`/app/datasets/${datasetId}`} className="btn btn-secondary btn-sm"><FileSpreadsheet size={15} aria-hidden="true" /> Data</Link>
          <Link to={`/app/exports?dataset=${datasetId}`} className="btn btn-secondary btn-sm"><Download size={15} aria-hidden="true" /> Export</Link>
          <Link to={`/app/reports?dataset=${datasetId}&new=1`} className="btn btn-secondary btn-sm"><FileText size={15} aria-hidden="true" /> Report</Link>
          {ready && <Button variant="secondary" size="sm" icon={LayoutGrid} onClick={() => setAuto((a) => !a)} aria-pressed={auto}>Suggested charts</Button>}
          {ready && <Button size="sm" icon={Link2} onClick={() => setSharing(true)} disabled={!data}>Share</Button>}
        </div>
      </div>

      {notice && dataset?.cleaning_counts && (
        <div className="notice" role="status">
          <CheckCircle2 size={16} color="var(--success)" aria-hidden="true" />
          <span className="grow">
            <strong>{dataset.filename}</strong> is ready: {formatInteger(dataset.cleaning_counts.rows_before)} rows read, {formatInteger(dataset.cleaning_counts.rows_removed)} removed, {formatInteger(dataset.cleaning_counts.cells_changed)} values fixed.
          </span>
          <CleaningReplay counts={dataset.cleaning_counts} columns={dataset.active_version?.column_count} />
          <CleanDownloadButton datasetId={datasetId} size="sm" />
          <Link to={`/app/datasets/${datasetId}`} className="small">Review cleaning</Link>
          <Button variant="ghost" size="sm" icon={X} aria-label="Dismiss" onClick={() => { setNotice(false); navigate(`${location.pathname}${location.search}`, { replace: true, state: null }); }} />
        </div>
      )}

      {dataset && !ready ? (
        <Card>
          {dataset.cleaning_status === 'failed'
            ? <ErrorState title="Cleaning failed" message={dataset.cleaning_error} />
            : <EmptyState icon={RefreshCw} title="Cleaning in progress" message="The dashboard appears as soon as cleaning finishes." />}
        </Card>
      ) : (
        <>
          {data && (
            <div className="filterbar" role="toolbar" aria-label="Dashboard filters">
              {data.date_column && (
                <>
                  <select className="fselect" aria-label="Date range" value={preset}
                    onChange={(e) => e.target.value !== 'custom' && update(presetRange(e.target.value, data.date_bounds?.max))}>
                    {PRESETS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    {preset === 'custom' && <option value="custom">Custom range</option>}
                  </select>
                  <input type="date" className="fdate" aria-label="From date" value={opts.from} min={data.date_bounds?.min} max={data.date_bounds?.max} onChange={(e) => update({ from: e.target.value })} />
                  <span className="xs muted">to</span>
                  <input type="date" className="fdate" aria-label="To date" value={opts.to} min={data.date_bounds?.min} max={data.date_bounds?.max} onChange={(e) => update({ to: e.target.value })} />
                  <span className="divider" aria-hidden="true" />
                </>
              )}
              {data.dimensions.map((d) => (
                <MultiSelect key={d.key} label={d.label} options={d.values} value={opts.filters[d.key] || []}
                  onChange={(vals) => update({ filters: { ...opts.filters, [d.key]: vals } })} />
              ))}
              <span className="grow" />
              {data.measures.length > 0 && (
                <select className="fselect" aria-label="Measure" value={data.measure?.key || ''} onChange={(e) => update({ measure: e.target.value, aggregation: '' })}>
                  {data.measures.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                </select>
              )}
              {data.measure && (
                <select className="fselect" aria-label="Aggregation" value={data.aggregation} onChange={(e) => update({ aggregation: e.target.value })}>
                  <option value="sum">Total</option>
                  <option value="mean">Average</option>
                </select>
              )}
              {data.date_column && (
                <select className="fselect" aria-label="Time grain" value={opts.grain} onChange={(e) => update({ grain: e.target.value })}>
                  {GRAINS.map(([k, l]) => <option key={k} value={k}>{k ? `By ${l.toLowerCase()}` : `Auto (${data.grain})`}</option>)}
                </select>
              )}
            </div>
          )}

          {data && hasFilters && (
            <div className="chips" aria-label="Active filters">
              {(opts.from || opts.to) && (
                <span className="chip">{data.date_column?.label}: {opts.from || 'start'} – {opts.to || 'end'}
                  <button type="button" aria-label="Remove date filter" onClick={() => update({ from: '', to: '' })}><X size={12} /></button>
                </span>
              )}
              {activeFilters.map(([k, vals]) => (
                <span key={k} className="chip">{dimLabel(k)}: {vals.join(', ')}
                  <button type="button" aria-label={`Remove ${dimLabel(k)} filter`} onClick={() => update({ filters: { ...opts.filters, [k]: [] } })}><X size={12} /></button>
                </span>
              ))}
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => update({ from: '', to: '', filters: {} })}>Clear all</button>
            </div>
          )}

          {state.error && <Card><ErrorState message={state.error} onRetry={() => load()} /></Card>}
          {!data && !state.error && <DashboardSkeleton />}
          {data && data.rows_in_view === 0 && (
            <Card><EmptyState icon={Database} title="No records match these filters" message="Widen the date range or remove a filter." action={<Button variant="secondary" onClick={() => update({ from: '', to: '', filters: {} })}>Clear filters</Button>} /></Card>
          )}
          {data && data.rows_in_view > 0 && (
            <div style={{ opacity: state.loading ? 0.6 : 1, transition: 'opacity 120ms' }} aria-busy={state.loading}>
              {auto && !providers.loading && (
                <AutoCharts datasetId={datasetId} view={viewBody} aiReady={Boolean(providers.data?.active)} seriesOrderFor={seriesOrderFor}
                  onClose={() => setAuto(false)} onPinned={() => load()} />
              )}
              <div className="dash-kpis">
                {data.kpis.map((k, i) => <KpiCard key={k.id} kpi={k} datasetId={datasetId} accent={[0, 6, 2, 1][i] ?? i} onGoal={setGoal} />)}
              </div>
              <InsightsStrip datasetId={datasetId} />
              <div className="dash-grid">
                {data.tiles.map((t, i) => (
                  <Tile key={`${t.id}-${i}`} tile={t} datasetId={datasetId} className={tileSpans[i]}
                    onSelect={toggleValue} selected={t.dimension ? opts.filters[t.dimension] : undefined}
                    seriesOrder={seriesOrderFor(t.dimension)} />
                ))}
              </div>
              {data.custom_tiles?.length > 0 && (
                <>
                  <div className="section-label">Pinned charts</div>
                  <div className="dash-grid">
                    {data.custom_tiles.map((t) => (
                      <Tile key={t.id} tile={t} datasetId={datasetId} className={t.chart.spec.type === 'donut' ? 'span-4' : 'span-6'}
                        onSelect={toggleValue} selected={t.dimension ? opts.filters[t.dimension] : undefined}
                        seriesOrder={seriesOrderFor(t.series_dimension || t.dimension)} onUnpin={() => unpin(t.id)} />
                    ))}
                  </div>
                </>
              )}
              {!auto && (
                <button type="button" className="add-tile" onClick={() => setAuto(true)}>
                  <LayoutGrid size={16} aria-hidden="true" /> Add a chart
                </button>
              )}
              {data.skipped.length > 0 && (
                <p className="xs muted" style={{ marginTop: 12 }}>Not shown: {data.skipped.map((s) => `${s.tile} (${s.reason})`).join(' · ')}</p>
              )}
            </div>
          )}
        </>
      )}
      {data && <ShareDialog open={sharing} onClose={() => setSharing(false)} datasetId={datasetId} view={viewBody} defaultTitle={dataset?.filename?.replace(/\.\w+$/, '') || 'Dashboard'} preview={sharePreview} />}
    </div>
  );
}

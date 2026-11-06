import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle2, FileText, Loader2, PenLine, Plus, Trash2 } from 'lucide-react';
import PageHeader from '../../components/PageHeader.jsx';
import {
  Alert, Badge, Button, Card, CardHeader, ConfirmDialog, EmptyState, Input, Select, Skeleton, Switch, useToast,
} from '../../components/ui/index.js';
import useApi from '../../hooks/useApi.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatRelative } from '../../utils/format.js';

const SECTIONS = [
  ['summary', 'Executive summary', 'Overview, key findings and recommendations'],
  ['kpis', 'Key figures', 'Headline measures with period change'],
  ['charts', 'Charts', 'Trend, breakdowns and composition'],
  ['insights', 'Insights', 'Statistically screened findings with caveats'],
  ['quality', 'Data quality', 'Cleaning steps and quality score'],
  ['columns', 'Column dictionary', 'Every column, its type and completeness'],
];
const STEPS = ['Calculating key figures', 'Building charts', 'Screening for insights', 'Writing the narrative'];

function Builder({ datasets, initialDataset, aiReady, onCreated }) {
  const toast = useToast();
  const [form, setForm] = useState({ dataset_id: initialDataset || '', title: '', date_from: '', date_to: '', use_ai: aiReady });
  const [sections, setSections] = useState(SECTIONS.map(([k]) => k));
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0);
  useEffect(() => { if (!form.dataset_id && datasets.length) setForm((f) => ({ ...f, dataset_id: datasets[0].id })); }, [datasets, form.dataset_id]);
  useEffect(() => setForm((f) => ({ ...f, use_ai: aiReady })), [aiReady]);
  useEffect(() => {
    if (!busy) return undefined;
    setStep(0);
    const t = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 1400);
    return () => clearInterval(t);
  }, [busy]);

  const generate = async () => {
    setBusy(true);
    try {
      const { data } = await api.post('/reports', {
        dataset_id: form.dataset_id, title: form.title || null, use_ai: form.use_ai, sections,
        date_from: form.date_from || null, date_to: form.date_to || null,
      }, { timeout: 0 });
      if (data.note) toast.info(data.note);
      onCreated(data);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="report-builder">
      <CardHeader title="New report" />
      <div className="card-body">
        <div className="builder-grid">
          <div className="stack">
            <Select label="Dataset" value={form.dataset_id} onChange={(e) => setForm({ ...form, dataset_id: e.target.value })}
              options={datasets.map((d) => ({ value: d.id, label: d.filename }))} />
            <Input label="Title (optional)" placeholder="For example: Q3 sales review" value={form.title} maxLength={200} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <div className="grid-2">
              <Input label="From date (optional)" type="date" value={form.date_from} onChange={(e) => setForm({ ...form, date_from: e.target.value })} />
              <Input label="To date (optional)" type="date" value={form.date_to} onChange={(e) => setForm({ ...form, date_to: e.target.value })} />
            </div>
            <div className="ai-toggle">
              <span className="ai-chip" aria-hidden="true"><PenLine size={16} /></span>
              <div className="grow">
                <p className="small" style={{ fontWeight: 600 }}>AI-written summary</p>
                <p className="xs muted">{aiReady ? 'Numbers are checked against the results.' : 'No AI provider configured: written from templates.'}</p>
              </div>
              <Switch checked={form.use_ai && aiReady} disabled={!aiReady} onChange={(v) => setForm({ ...form, use_ai: v })} label="" />
            </div>
          </div>
          <div>
            <span className="label">Sections</span>
            <div className="section-picks">
              {SECTIONS.map(([k, label, hint]) => (
                <label key={k} className="section-pick" data-on={sections.includes(k)}>
                  <input type="checkbox" checked={sections.includes(k)}
                    onChange={(e) => setSections((s) => (e.target.checked ? [...s, k] : s.filter((x) => x !== k)))} />
                  <span><strong className="small">{label}</strong><br /><span className="xs muted">{hint}</span></span>
                </label>
              ))}
            </div>
          </div>
        </div>
        <div className="row between" style={{ marginTop: 16, flexWrap: 'wrap', gap: 12 }}>
          {busy ? (
            <ol className="gen-steps" aria-live="polite">
              {STEPS.map((s, i) => (
                <li key={s} data-state={i < step ? 'done' : i === step ? 'active' : 'todo'}>
                  {i < step ? <CheckCircle2 size={14} /> : i === step ? <Loader2 size={14} className="spin" /> : <span className="dot" />} {s}
                </li>
              ))}
            </ol>
          ) : <span className="xs muted">Takes a few seconds. The report is saved so you can reopen, print or download it later.</span>}
          <Button icon={FileText} onClick={generate} loading={busy} disabled={!form.dataset_id || !sections.length}>Generate report</Button>
        </div>
      </div>
    </Card>
  );
}

export default function Reports() {
  usePageTitle('Reports');
  const toast = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const datasets = useApi('/datasets', { params: { page_size: 100 } });
  const providers = useApi('/ai/providers');
  const list = useApi('/reports');
  const [showBuilder, setShowBuilder] = useState(params.get('new') === '1');
  const [remove, setRemove] = useState(null);
  const ready = useMemo(() => (datasets.data?.items || []).filter((d) => d.active_version_id), [datasets.data]);

  const doRemove = async () => {
    const r = remove;
    setRemove(null);
    try {
      await api.delete(`/reports/${r.id}`);
      toast.success('Report deleted');
      list.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const items = list.data?.items || [];
  return (
    <div className="stack">
      <PageHeader module="reports" title="Reports"
        actions={!showBuilder && ready.length > 0 && <Button icon={Plus} onClick={() => setShowBuilder(true)}>New report</Button>} />
      {datasets.loading && !datasets.data ? <Card pad><Skeleton height={160} /></Card> : ready.length === 0 ? (
        <Card><EmptyState icon={FileText} title="No datasets to report on" message="Upload a dataset first; reports are built from its cleaned version."
          action={<Link to="/app/upload" className="btn btn-primary">Upload file</Link>} /></Card>
      ) : showBuilder && (
        <Builder datasets={ready} initialDataset={params.get('dataset')} aiReady={Boolean(providers.data?.active)}
          onCreated={(r) => { setParams({}); navigate(`/app/reports/${r.id}`); }} />
      )}
      <Card>
        <CardHeader title="Saved reports" subtitle={items.length ? `${items.length} report${items.length === 1 ? '' : 's'}` : undefined} />
        {list.loading && !list.data ? <div className="card-body"><Skeleton height={80} /></div> : items.length === 0 ? (
          <EmptyState icon={FileText} title="No reports yet" message="Generate one above. It is saved here with the dataset version it used." />
        ) : (
          <ul className="report-list">
            {items.map((r) => (
              <li key={r.id}>
                <Link to={`/app/reports/${r.id}`} className="report-item">
                  <span className="report-icon" aria-hidden="true"><FileText size={18} /></span>
                  <span className="grow" style={{ minWidth: 0 }}>
                    <span className="row" style={{ gap: 8 }}>
                      <strong className="small">{r.title}</strong>
                      <Badge tone={r.source === 'ai' ? 'primary' : 'neutral'}>{r.source === 'ai' ? `AI · ${r.provider}` : 'Template'}</Badge>
                    </span>
                    <span className="xs muted">{r.dataset_name} · version {r.version_number} · {formatRelative(r.created_at)}</span>
                    {r.headline && <span className="xs muted report-headline">{r.headline}</span>}
                  </span>
                </Link>
                <Button variant="ghost" size="sm" icon={Trash2} aria-label={`Delete ${r.title}`} onClick={() => setRemove(r)} />
              </li>
            ))}
          </ul>
        )}
      </Card>
      <ConfirmDialog open={Boolean(remove)} title="Delete report?" danger confirmLabel="Delete" message={remove ? `“${remove.title}” will be deleted.` : ''}
        onConfirm={doRemove} onCancel={() => setRemove(null)} />
    </div>
  );
}

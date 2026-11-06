import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { BarChart3, Download, MessageSquare, RefreshCw, Terminal, Trash2 } from 'lucide-react';
import PageHeader from '../../components/PageHeader.jsx';
import CleaningReplay from '../../components/CleaningReplay.jsx';
import SourceLink from '../../components/SourceLink.jsx';
import { CleanDownloadButton } from '../../components/CleanDownload.jsx';
import CleaningProgress from '../../components/CleaningProgress.jsx';
import DataPreview from '../../components/DataPreview.jsx';
import ColumnProfilePanel from '../../components/ColumnProfilePanel.jsx';
import SuggestionsPanel from '../../components/cleaning/SuggestionsPanel.jsx';
import ProfilePanel from '../../components/ProfilePanel.jsx';
import { ReportDownloads, ReportSteps, ReportSummary } from '../../components/cleaning/CleaningReport.jsx';
import {
  Alert, Badge, Button, Card, CardHeader, ConfirmDialog, ErrorState, Input, Modal, Segmented, Select, Skeleton, Tabs, useToast,
} from '../../components/ui/index.js';
import useDataset, { STATUS_LABEL, STATUS_TONE } from '../../hooks/useDataset.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatInteger, formatRelative } from '../../utils/format.js';

function CleanOptionsModal({ open, onClose, dataset, onStarted }) {
  const toast = useToast();
  const prev = dataset.cleaning_options || {};
  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setForm({
        sheet: dataset.sheet || '',
        header_row: prev.header_row ?? '',
        date_order: prev.date_order || 'DMY',
        decimal_separator: prev.decimal_separator || '',
        null_tokens: (prev.null_tokens || []).join(', '),
        id_columns: (prev.id_columns || []).join(', '),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = async () => {
    setBusy(true);
    const list = (s) => s.split(',').map((x) => x.trim()).filter(Boolean);
    try {
      await api.post(`/datasets/${dataset.id}/clean`, {
        sheet: form.sheet || undefined,
        header_row: form.header_row === '' ? null : Number(form.header_row),
        date_order: form.date_order,
        decimal_separator: form.decimal_separator || null,
        null_tokens: form.null_tokens.trim() ? list(form.null_tokens) : null,
        id_columns: list(form.id_columns),
      });
      toast.info('Cleaning started');
      onStarted();
      onClose();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Re-run cleaning with options" width={560}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={submit} loading={busy}>Re-run cleaning</Button></>}>
      <div className="stack">
        <p className="small muted">Creates a new version from the original file. Earlier versions are kept.</p>
        {dataset.sheets?.length > 1 && <Select label="Sheet" value={form.sheet} onChange={set('sheet')} options={dataset.sheets.map((s) => ({ value: s, label: s }))} />}
        <Input label="Header row number" type="number" min={1} value={form.header_row} onChange={set('header_row')} hint="Leave empty to detect automatically. Counted from the first row of the file." />
        <div className="grid-2">
          <Select label="Date order for ambiguous dates" value={form.date_order} onChange={set('date_order')} options={[{ value: 'DMY', label: 'Day first (31/12/2024)' }, { value: 'MDY', label: 'Month first (12/31/2024)' }]} />
          <Select label="Decimal separator" value={form.decimal_separator} onChange={set('decimal_separator')} options={[{ value: '', label: 'Detect automatically' }, { value: '.', label: 'Dot (1,234.56)' }, { value: ',', label: 'Comma (1.234,56)' }]} />
        </div>
        <Input label="Null markers" value={form.null_tokens} onChange={set('null_tokens')} placeholder="N/A, null, -, ?" hint="Comma-separated. Leave empty for the default list." />
        <Input label="Identifier columns" value={form.id_columns} onChange={set('id_columns')} placeholder="order_id, sku" hint="Comma-separated column names to keep as text (never converted to numbers)." />
      </div>
    </Modal>
  );
}

function VersionsTab({ dataset, onChanged }) {
  const toast = useToast();
  const [items, setItems] = useState(null);
  const load = () => api.get(`/datasets/${dataset.id}/versions`).then(({ data }) => setItems(data.items));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [dataset.id, dataset.active_version_id]);
  const activate = async (v) => {
    try {
      await api.put(`/datasets/${dataset.id}/active-version`, { version_id: v.id });
      toast.success(`Version ${v.version_number} is now active`);
      onChanged();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };
  if (!items) return <Skeleton height={120} />;
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Dataset versions</caption>
        <thead><tr><th>Version</th><th>Kind</th><th className="num">Rows</th><th className="num">Columns</th><th className="num">Quality</th><th>Created</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {items.map((v) => (
            <tr key={v.id}>
              <td style={{ fontWeight: 600 }}>v{v.version_number} {v.is_active && <Badge tone="success">Active</Badge>}</td>
              <td>{v.kind === 'auto_cleaned' ? 'Automatic cleaning' : 'Your changes'}</td>
              <td className="num">{formatInteger(v.row_count)}</td>
              <td className="num">{formatInteger(v.column_count)}</td>
              <td className="num">{v.quality_score_after ?? '—'}</td>
              <td className="muted">{formatRelative(v.created_at)}</td>
              <td style={{ textAlign: 'right' }}>
                <div className="row" style={{ justifyContent: 'flex-end' }}>
                  <a className="btn btn-ghost btn-sm" href={`/api/datasets/${dataset.id}/download?version=${v.id}`} aria-label={`Download version ${v.version_number} as CSV`}><Download size={15} /></a>
                  {!v.is_active && <Button size="sm" variant="secondary" onClick={() => activate(v)}>Make active</Button>}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DictionaryTab({ schema, onOpen }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Data dictionary</caption>
        <thead><tr><th>Column</th><th>Key</th><th>Type</th><th>Meaning</th><th className="num">Empty</th><th className="num">Unique</th><th>Examples</th></tr></thead>
        <tbody>
          {schema.map((c) => (
            <tr key={c.key}>
              <td><button type="button" className="th-btn" style={{ color: 'var(--primary)', fontWeight: 600 }} onClick={() => onOpen(c)}>{c.display_name}</button></td>
              <td><code className="xs">{c.key}</code></td>
              <td>{c.dtype}{c.scale ? ` (${c.scale} dp)` : ''}</td>
              <td>{c.semantic_type}{c.currency ? ` · ${c.currency}` : ''}{c.flagged && <> <Badge tone="warning">check</Badge></>}</td>
              <td className="num">{formatInteger(c.missing)}</td>
              <td className="num">{formatInteger(c.unique)}</td>
              <td className="muted" title={(c.profile?.examples || []).join(', ')}>{(c.profile?.examples || []).slice(0, 5).join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CleaningTab({ dataset }) {
  const version = dataset.active_version;
  const [view, setView] = useState('cleaned');
  const [report, setReport] = useState(null);
  useEffect(() => {
    setReport(null);
    api.get(`/datasets/${dataset.id}/cleaning-report`, { params: { version: version.id } }).then(({ data }) => setReport(data.version.cleaning_report));
  }, [dataset.id, version.id]);
  const base = dataset.filename.replace(/\.[^.]+$/, '');
  return (
    <div className="stack">
      {report ? <ReportSummary summary={report.summary} /> : <Skeleton height={90} />}
      <Card>
        <CardHeader
          title="Data"
          subtitle={view === 'cleaned' ? 'Highlighted cells differ from the original file.' : 'The original file, exactly as uploaded (no conversion).'}
          actions={<Segmented label="Raw or cleaned" value={view} onChange={setView} options={[{ value: 'raw', label: 'Raw' }, { value: 'cleaned', label: 'Cleaned' }]} />}
        />
        <div className="card-body">
          <DataPreview datasetId={dataset.id} version={view === 'raw' ? 'raw' : version.id} highlight={view === 'cleaned'} pageSize={25} />
        </div>
      </Card>
      <Card>
        <CardHeader title="Cleaning steps" subtitle="Every automatic change, with examples." actions={report && <ReportDownloads report={report} base={base} />} />
        <div className="card-body">{report ? <ReportSteps report={report} /> : <Skeleton height={120} />}</div>
      </Card>
    </div>
  );
}

export default function DatasetDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { dataset, error, loading, reload, busy } = useDataset(id);
  usePageTitle(dataset?.filename || 'Dataset');
  const [tab, setTab] = useState('cleaning');
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [column, setColumn] = useState(null);

  if (error) return <ErrorState title="Dataset unavailable" message={error} onRetry={reload} />;
  if (loading || !dataset) return <div className="stack"><Skeleton height={32} width={300} /><Skeleton height={300} /></div>;

  const version = dataset.active_version;
  const del = async () => {
    setDeleting(true);
    try {
      await api.delete(`/datasets/${dataset.id}`);
      toast.success('Dataset deleted');
      navigate('/app/datasets');
    } catch (err) {
      toast.error(errorMessage(err));
      setDeleting(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        module="datasets"
        title={dataset.filename}
        description={
          <span className="row-wrap">
            <Badge tone={STATUS_TONE[dataset.cleaning_status]}>{STATUS_LABEL[dataset.cleaning_status]}</Badge>
            {version && <span>Active version {version.version_number} · {formatInteger(version.row_count)} rows · {formatInteger(version.column_count)} columns</span>}
            {dataset.sheet && <span>· Sheet “{dataset.sheet}”</span>}
            <SourceLink dataset={dataset} onRefreshed={() => reload()} disabled={busy} />
          </span>
        }
        actions={
          <>
            {version && <Link to={`/app/dashboard?dataset=${dataset.id}`} className="btn btn-primary"><BarChart3 size={15} aria-hidden="true" /> Dashboard</Link>}
            {version && <Link to={`/app/ask?dataset=${dataset.id}`} className="btn btn-secondary"><MessageSquare size={15} aria-hidden="true" /> Ask</Link>}
            {version && <Link to={`/app/sql?dataset=${dataset.id}`} className="btn btn-secondary"><Terminal size={15} aria-hidden="true" /> Query with SQL</Link>}
            {version && <CleanDownloadButton datasetId={dataset.id} />}
            <a className="btn btn-ghost" href={`/api/datasets/${dataset.id}/download?version=raw`}>Original file</a>
            {version && !busy && <CleaningReplay counts={dataset.cleaning_counts} columns={version.column_count} />}
            <Button variant="secondary" icon={RefreshCw} onClick={() => setOptionsOpen(true)} disabled={busy}>Re-run cleaning</Button>
            <Button variant="ghost" icon={Trash2} onClick={() => setConfirm(true)} aria-label="Delete dataset" />
          </>
        }
      />
      {busy && (
        <Card pad><CleaningProgress stage={dataset.cleaning_stage || 'cleaning'} counts={dataset.cleaning_counts} /></Card>
      )}
      {dataset.cleaning_status === 'failed' && (
        <Alert tone="danger">{dataset.cleaning_error} <button type="button" className="th-btn" style={{ textDecoration: 'underline' }} onClick={() => setOptionsOpen(true)}>Re-run with options</button></Alert>
      )}
      {version && (
        <>
          <Tabs label="Dataset sections" value={tab} onChange={setTab} tabs={[
            { value: 'cleaning', label: 'Data cleaning' },
            { value: 'profile', label: 'Profile' },
            { value: 'suggestions', label: 'Suggestions' },
            { value: 'dictionary', label: 'Data dictionary' },
            { value: 'versions', label: 'Versions' },
          ]} />
          {tab === 'cleaning' && <CleaningTab dataset={dataset} />}
          {tab === 'profile' && <ProfilePanel datasetId={dataset.id} versionId={version.id} />}
          {tab === 'suggestions' && <SuggestionsPanel datasetId={dataset.id} columns={version.schema} onApplied={reload} />}
          {tab === 'dictionary' && <DictionaryTab schema={version.schema} onOpen={setColumn} />}
          {tab === 'versions' && <VersionsTab dataset={dataset} onChanged={reload} />}
        </>
      )}
      <CleanOptionsModal open={optionsOpen} onClose={() => setOptionsOpen(false)} dataset={dataset} onStarted={reload} />
      <ColumnProfilePanel column={column} onClose={() => setColumn(null)} />
      <ConfirmDialog open={confirm} title="Delete dataset?" danger confirmLabel="Delete" loading={deleting}
        message="The original file, every version, and all analyses, queries and reports made from this dataset will be deleted. This cannot be undone."
        onConfirm={del} onCancel={() => setConfirm(false)} />
    </div>
  );
}

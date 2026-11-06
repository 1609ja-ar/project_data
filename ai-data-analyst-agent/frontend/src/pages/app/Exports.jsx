import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle, CheckCircle2, Copy, Database, Download, FileSpreadsheet, KeyRound, Package, PlugZap, Search, Sheet, Trash2, XCircle,
} from 'lucide-react';
import DatasetPicker from '../../components/DatasetPicker.jsx';
import MultiSelect from '../../components/dashboard/MultiSelect.jsx';
import {
  Alert, Badge, Button, Card, CardHeader, ConfirmDialog, DataTable, EmptyState, Input, Modal, Select, Skeleton, Tabs, useToast,
} from '../../components/ui/index.js';
import useApi from '../../hooks/useApi.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatDateTime, formatInteger, formatRelative } from '../../utils/format.js';
import { blobError, saveBlob } from '../../utils/download.js';

function useCopy() {
  const toast = useToast();
  return async (text, what = 'Copied') => {
    try { await navigator.clipboard.writeText(text); toast.success(what); } catch { toast.error('Copy failed. Select the text and copy it manually.'); }
  };
}

function CodeBlock({ title, code, note }) {
  const copy = useCopy();
  return (
    <div className="codeblock">
      <div className="codeblock-head"><span className="small" style={{ fontWeight: 600 }}>{title}</span>
        <Button variant="ghost" size="sm" icon={Copy} onClick={() => copy(code, `${title} copied`)}>Copy</Button></div>
      <pre>{code}</pre>
      {note && <p className="xs muted" style={{ padding: '6px 12px' }}>{note}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ Excel builder

function ExcelBuilder({ datasetId }) {
  const toast = useToast();
  const meta = useApi(`/analytics/${datasetId}/dashboard`, { method: 'post' });
  const [cols, setCols] = useState(null);
  const [schemaCols, setSchemaCols] = useState([]);
  const [q, setQ] = useState('');
  const [view, setView] = useState({ from: '', to: '', filters: {} });
  const [inc, setInc] = useState({ include_dashboard: true, include_dictionary: true, include_cleaning: true });
  const [preview, setPreview] = useState({ data: null, loading: false, error: null });
  const [busy, setBusy] = useState(false);

  const body = useMemo(() => ({
    columns: cols, date_from: view.from || null, date_to: view.to || null,
    filters: Object.entries(view.filters).filter(([, v]) => v.length).map(([column, values]) => ({ column, values })),
  }), [cols, view]);
  const bodyKey = JSON.stringify(body);

  useEffect(() => {
    let live = true;
    setPreview((p) => ({ ...p, loading: true, error: null }));
    const t = setTimeout(() => {
      api.post(`/exports/${datasetId}/preview`, JSON.parse(bodyKey))
        .then(({ data }) => {
          if (!live) return;
          setPreview({ data, loading: false, error: null });
          // The first preview (no column choice yet) lists every column: that is the pick list.
          setSchemaCols((s) => (s.length ? s : data.columns));
          setCols((c) => c ?? data.columns.map((x) => x.key));
        })
        .catch((err) => live && setPreview((p) => ({ ...p, loading: false, error: errorMessage(err) })));
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [datasetId, bodyKey]);

  const dims = meta.data?.dimensions || [];
  // Same order as the workbook: Summary first, then Data, dictionary, cleaning, then the chart sheets.
  const sheets = [...(inc.include_dashboard ? ['Summary'] : []), 'Data', ...(inc.include_dictionary ? ['Data dictionary'] : []), ...(inc.include_cleaning ? ['Cleaning report'] : []), ...(inc.include_dashboard ? ['Aggregates', 'Charts'] : [])];
  const shownCols = schemaCols.filter((c) => c.label.toLowerCase().includes(q.toLowerCase()));
  const chosen = cols || [];

  const download = async () => {
    setBusy(true);
    try {
      const res = await api.post(`/exports/${datasetId}/excel-custom`, { ...body, ...inc }, { responseType: 'blob', timeout: 0 });
      saveBlob(res, 'export.xlsx');
      toast.success(`Workbook downloaded (${formatInteger(res.headers['x-rows-exported'])} rows)`);
      if (res.headers['x-charts-skipped']) toast.info(`${res.headers['x-charts-skipped']} chart(s) have no native Excel equivalent and were skipped.`);
    } catch (err) {
      toast.error(await blobError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="xl-layout">
      <div className="stack">
        <Card>
          <CardHeader title="1. Rows" subtitle="Same filters as the dashboard." />
          <div className="card-body stack-sm">
            {meta.data?.date_column && (
              <div className="row-wrap">
                <span className="xs muted" style={{ width: 70 }}>{meta.data.date_column.label}</span>
                <input type="date" className="fdate" aria-label="From date" value={view.from} min={meta.data.date_bounds?.min} max={meta.data.date_bounds?.max} onChange={(e) => setView((v) => ({ ...v, from: e.target.value }))} />
                <span className="xs muted">to</span>
                <input type="date" className="fdate" aria-label="To date" value={view.to} min={meta.data.date_bounds?.min} max={meta.data.date_bounds?.max} onChange={(e) => setView((v) => ({ ...v, to: e.target.value }))} />
              </div>
            )}
            <div className="row-wrap">
              {dims.map((d) => <MultiSelect key={d.key} label={d.label} options={d.values} value={view.filters[d.key] || []} onChange={(vals) => setView((v) => ({ ...v, filters: { ...v.filters, [d.key]: vals } }))} />)}
              {meta.loading && <Skeleton width={160} height={30} />}
            </div>
          </div>
        </Card>
        <Card>
          <CardHeader title="2. Columns" subtitle={`${chosen.length} of ${schemaCols.length} selected`}
            actions={<><Button variant="ghost" size="sm" onClick={() => setCols(schemaCols.map((c) => c.key))}>All</Button><Button variant="ghost" size="sm" onClick={() => setCols([])}>None</Button></>} />
          <div className="card-body stack-sm">
            {schemaCols.length > 8 && <Input lead={Search} placeholder="Search columns" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search columns" />}
            <div className="col-picks">
              {shownCols.map((c) => (
                <label key={c.key} className="option">
                  <input type="checkbox" checked={chosen.includes(c.key)}
                    onChange={(e) => setCols((cur) => {
                      const base = cur || [];
                      const next = e.target.checked ? [...base, c.key] : base.filter((k) => k !== c.key);
                      return schemaCols.map((s) => s.key).filter((k) => next.includes(k)); // keep the dataset's column order
                    })} />
                  <span className="grow">{c.label}</span>
                  <Badge>{c.semantic_type === 'currency' ? 'money' : c.dtype}</Badge>
                </label>
              ))}
            </div>
          </div>
        </Card>
        <Card>
          <CardHeader title="3. Extra sheets" />
          <div className="card-body stack-sm">
            {[['include_dashboard', 'Dashboard summary', 'KPIs with period change and native Excel charts of the trend and breakdowns'],
              ['include_dictionary', 'Data dictionary', 'Each column with its type, empty and distinct counts'],
              ['include_cleaning', 'Cleaning report', 'Every change made to the original file']].map(([k, l, h]) => (
              <label key={k} className="section-pick" data-on={inc[k]}>
                <input type="checkbox" checked={inc[k]} onChange={(e) => setInc((s) => ({ ...s, [k]: e.target.checked }))} />
                <span><strong className="small">{l}</strong><br /><span className="xs muted">{h}</span></span>
              </label>
            ))}
          </div>
        </Card>
      </div>
      <Card className="xl-preview">
        <CardHeader title="Preview" subtitle={preview.data ? `${formatInteger(preview.data.rows)} of ${formatInteger(preview.data.total_rows)} rows · ${chosen.length} columns` : 'Loading…'} />
        <div className="card-body stack">
          <div className="sheet-tabs" aria-label="Sheets in the workbook">
            {sheets.map((s) => <span key={s} className="sheet-tab"><Sheet size={13} aria-hidden="true" /> {s}</span>)}
          </div>
          {preview.error && <Alert tone="danger">{preview.error}</Alert>}
          {preview.data && chosen.length > 0 ? (
            <div style={{ opacity: preview.loading ? 0.5 : 1 }}>
              <DataTable columns={preview.data.columns} rows={preview.data.sample} pageSize={12} maxHeight={380} caption="Export preview" />
              <p className="xs muted" style={{ marginTop: 6 }}>First {preview.data.sample.length} rows shown. Filters: {preview.data.filters.length ? preview.data.filters.join('; ') : 'none'}.</p>
            </div>
          ) : !preview.error && (chosen.length === 0 ? <p className="small muted">Select at least one column.</p> : <Skeleton height={220} />)}
          <div className="row between" style={{ flexWrap: 'wrap', gap: 8 }}>
            <span className="xs muted">Typed cells, frozen header and filters on the Data sheet. Values match the app exactly.</span>
            <Button icon={Download} loading={busy} disabled={!chosen.length || !preview.data?.rows} onClick={download}>Download .xlsx</Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ Power BI

function TokenModal({ open, onClose, datasetId, onCreated }) {
  const toast = useToast();
  const [name, setName] = useState('Power BI Desktop');
  const [scope, setScope] = useState('dataset');
  const [days, setDays] = useState('30');
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      const { data } = await api.post('/export-tokens', { name, dataset_id: scope === 'dataset' ? datasetId : undefined, expires_in_days: Number(days) });
      onCreated(data);
      onClose();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Create an access token" width={520}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={create} loading={busy}>Create token</Button></>}>
      <div className="stack">
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} hint="To recognise the token later." />
        <Select label="Access" value={scope} onChange={(e) => setScope(e.target.value)} options={[{ value: 'dataset', label: 'This dataset only (recommended)' }, { value: 'all', label: 'All my datasets' }]} />
        <Select label="Expires after" value={days} onChange={(e) => setDays(e.target.value)} options={['7', '30', '90'].map((d) => ({ value: d, label: `${d} days` }))} />
        <Alert tone="info">Tokens are read-only, work only on the data feed, and can be revoked at any time.</Alert>
      </div>
    </Modal>
  );
}

function PowerBI({ datasetId, token, onNewToken }) {
  const toast = useToast();
  const copy = useCopy();
  const setup = useApi(`/powerbi/${datasetId}/setup`, { params: { base_url: window.location.origin } });
  const [test, setTest] = useState(null);
  const [busy, setBusy] = useState(false);
  const usable = token && (!token.dataset_id || token.dataset_id === datasetId) ? token : null;
  const mWeb = setup.data ? (usable ? setup.data.m_web.replace('Token = "PASTE_TOKEN_HERE"', `Token = "${usable.token}"`) : setup.data.m_web) : '';

  const testFeed = async () => {
    setTest({ loading: true });
    try {
      const res = await fetch(setup.data.feed_url.replace(window.location.origin, ''), { headers: { Authorization: `Bearer ${usable.token}` } });
      if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.error?.message || `HTTP ${res.status}`);
      const reader = res.body.getReader();
      const { value } = await reader.read();
      reader.cancel();
      const header = new TextDecoder().decode(value || new Uint8Array()).split('\n')[0];
      setTest({ ok: true, version: res.headers.get('x-dataset-version'), header });
    } catch (err) {
      setTest({ ok: false, message: err.message });
    }
  };
  const pkg = async () => {
    setBusy(true);
    try {
      saveBlob(await api.get(`/powerbi/${datasetId}/package`, { responseType: 'blob', timeout: 0 }), 'powerbi.zip');
      toast.success('Package downloaded');
    } catch (err) {
      toast.error(await blobError(err));
    } finally {
      setBusy(false);
    }
  };

  if (setup.loading && !setup.data) return <Card pad><Skeleton height={300} /></Card>;
  if (setup.error) return <Alert tone="danger">{setup.error}</Alert>;
  const s = setup.data;
  return (
    <div className="pbi-layout">
      <Card className="pbi-main">
        <CardHeader title="Live connection (refreshable)" subtitle="Power BI pulls the latest cleaned version every time you press Refresh." actions={<Badge tone="success">Recommended</Badge>} />
        <div className="card-body">
          <ol className="pbi-steps">
            <li data-done={Boolean(usable)}>
              <div className="pbi-step-head"><span className="pbi-num">{usable ? <CheckCircle2 size={16} /> : 1}</span><strong>Create an access token</strong></div>
              {usable ? (
                <div className="stack-sm">
                  <Alert tone="warning" icon={AlertTriangle}>Copy it now: this token is shown only once. It has been filled into the query below.</Alert>
                  <div className="row"><code className="token-box grow">{usable.token}</code><Button variant="secondary" size="sm" icon={Copy} onClick={() => copy(usable.token, 'Token copied')}>Copy</Button></div>
                </div>
              ) : (
                <div className="row-wrap"><Button icon={KeyRound} onClick={onNewToken}>Create token</Button><span className="xs muted">Or paste an existing token into the query.</span></div>
              )}
            </li>
            <li>
              <div className="pbi-step-head"><span className="pbi-num">2</span><strong>Paste the query into Power BI Desktop</strong></div>
              <p className="small muted">Home → Get data → Blank query → Advanced editor, paste, Done. Name the query <code>data</code>, then Close &amp; Apply.</p>
              <CodeBlock title="Power Query (M)" code={mWeb} note={usable ? 'Contains your token: keep the .pbix private or move the token to a parameter.' : 'Replace PASTE_TOKEN_HERE with your token.'} />
            </li>
            <li>
              <div className="pbi-step-head"><span className="pbi-num">3</span><strong>Check the connection</strong></div>
              <div className="row-wrap">
                <Button variant="secondary" icon={PlugZap} disabled={!usable} onClick={testFeed} loading={test?.loading}>Test connection</Button>
                {!usable && <span className="xs muted">Create a token first.</span>}
                {test && !test.loading && (test.ok
                  ? <span className="small" style={{ color: 'var(--success)' }}><CheckCircle2 size={14} /> Feed works · version {test.version} · columns: {test.header.slice(0, 120)}</span>
                  : <span className="small" style={{ color: 'var(--danger)' }}><XCircle size={14} /> {test.message}</span>)}
              </div>
              <div className="row" style={{ marginTop: 8 }}><code className="token-box grow">{s.feed_url}</code><Button variant="ghost" size="sm" icon={Copy} onClick={() => copy(s.feed_url, 'Feed URL copied')} aria-label="Copy feed URL" /></div>
              <p className="xs muted" style={{ marginTop: 6 }}>Scheduled refresh in the Power BI service needs this app on a public HTTPS address (and possibly a gateway); that setup was not tested.</p>
            </li>
          </ol>
        </div>
      </Card>
      <div className="stack">
        <Card>
          <CardHeader title="Column types" subtitle={`Version ${s.version_number} · applied by the query`} />
          <div style={{ maxHeight: 260, overflow: 'auto' }}>
            <table className="table"><thead><tr><th>Column</th><th>Power BI type</th></tr></thead>
              <tbody>{s.columns.map((c) => <tr key={c.name}><td>{c.name}</td><td className="muted">{c.powerbi_type}</td></tr>)}</tbody></table>
          </div>
        </Card>
        <CodeBlock title="Suggested DAX measures" code={s.dax} note="Modeling → New measure, paste one measure at a time." />
        <Card>
          <CardHeader title="Offline file package" subtitle="CSV + Parquet, data dictionary, M script and DAX in one zip." />
          <div className="card-body"><Button variant="secondary" icon={Package} loading={busy} onClick={pkg}>Download package</Button></div>
        </Card>
      </div>
    </div>
  );
}

function Tokens({ tokens }) {
  const toast = useToast();
  const [revoke, setRevoke] = useState(null);
  const doRevoke = async () => {
    const t = revoke;
    setRevoke(null);
    try {
      await api.delete(`/export-tokens/${t.id}`);
      toast.success('Token revoked');
      tokens.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };
  return (
    <Card>
      <CardHeader title="Access tokens" subtitle="Anyone holding an active token can read the data it covers. Revoke tokens you no longer use." />
      {tokens.loading && !tokens.data ? <div className="card-body"><Skeleton height={80} /></div> : !tokens.data?.items?.length ? (
        <EmptyState icon={KeyRound} title="No tokens yet" message="Create one on the Power BI tab to connect a live feed." />
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="table">
            <caption className="sr-only">Access tokens</caption>
            <thead><tr><th>Name</th><th>Token</th><th>Access</th><th>Status</th><th>Expires</th><th>Last used</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {tokens.data.items.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td><code>{t.token_prefix}…</code></td>
                  <td>{t.dataset_name || 'Deleted dataset'}</td>
                  <td><Badge tone={t.status === 'active' ? 'success' : t.status === 'revoked' ? 'danger' : 'warning'}>{t.status}</Badge></td>
                  <td>{formatDateTime(t.expires_at)}</td>
                  <td className="muted">{t.last_used_at ? formatRelative(t.last_used_at) : 'Never'}</td>
                  <td style={{ textAlign: 'right' }}>{t.status === 'active' && <Button variant="ghost" size="sm" icon={Trash2} onClick={() => setRevoke(t)}>Revoke</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ConfirmDialog open={Boolean(revoke)} title="Revoke token?" danger confirmLabel="Revoke"
        message={revoke ? `“${revoke.name}” will stop working immediately. Power BI refreshes using it will fail.` : ''}
        onConfirm={doRevoke} onCancel={() => setRevoke(null)} />
    </Card>
  );
}

export default function Exports() {
  usePageTitle('Excel and Power BI');
  const [params, setParams] = useSearchParams();
  const datasetId = params.get('dataset');
  const tab = params.get('tab') || 'excel';
  const setDataset = useCallback((v) => setParams({ dataset: v, tab }, { replace: true }), [setParams, tab]);
  const setTab = (t) => setParams({ ...(datasetId ? { dataset: datasetId } : {}), tab: t }, { replace: true });
  const tokens = useApi('/export-tokens');
  const [tokenOpen, setTokenOpen] = useState(false);
  const [fresh, setFresh] = useState(null);

  return (
    <div className="stack">
      <div className="dash-head" style={{ marginBottom: 0 }}>
        <div>
          <div className="dash-title" style={{ '--mc': 'var(--m-exports)' }}><span className="page-icon"><FileSpreadsheet size={18} /></span><h1>Excel &amp; Power BI</h1></div>
        </div>
        <DatasetPicker value={datasetId} onChange={setDataset} />
      </div>
      <Tabs label="Export type" value={tab} onChange={setTab}
        tabs={[{ value: 'excel', label: 'Excel workbook' }, { value: 'powerbi', label: 'Power BI' }, { value: 'tokens', label: `Access tokens${tokens.data?.items?.length ? ` (${tokens.data.items.filter((t) => t.status === 'active').length})` : ''}` }]} />
      {!datasetId && tab !== 'tokens' ? (
        <Card><EmptyState icon={Database} title="No cleaned datasets yet" message="Upload a dataset to export it." action={<Link to="/app/upload" className="btn btn-primary">Upload file</Link>} /></Card>
      ) : tab === 'excel' ? <ExcelBuilder key={datasetId} datasetId={datasetId} />
        : tab === 'powerbi' ? <PowerBI key={datasetId} datasetId={datasetId} token={fresh} onNewToken={() => setTokenOpen(true)} />
          : <Tokens tokens={tokens} />}
      <TokenModal open={tokenOpen} onClose={() => setTokenOpen(false)} datasetId={datasetId} onCreated={(t) => { setFresh(t); tokens.reload(); }} />
    </div>
  );
}

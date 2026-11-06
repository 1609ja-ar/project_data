import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { AlignLeft, BookmarkPlus, Database, HelpCircle, History as HistoryIcon, Play, MessageSquareText, Table2, Trash2 } from 'lucide-react';
import { format as formatSql } from 'sql-formatter';
import PageHeader from '../../components/PageHeader.jsx';
import DatasetPicker from '../../components/DatasetPicker.jsx';
import SqlResults from '../../components/sql/SqlResults.jsx';
import {
  Accordion, Alert, Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, Modal, Skeleton, Tabs, useToast,
} from '../../components/ui/index.js';
import { useTheme } from '../../context/ThemeContext.jsx';
import useApi, { useDebounced } from '../../hooks/useApi.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage, getErrorInfo } from '../../services/errors.js';
import { formatRelative } from '../../utils/format.js';

const SqlEditor = lazy(() => import('../../components/sql/SqlEditor.jsx'));
const q = (name) => (/^[a-z_][a-z0-9_]*$/.test(name) ? name : `"${name.replace(/"/g, '""')}"`);

function examples(table) {
  if (!table?.columns) return [];
  const cols = table.columns;
  const num = cols.find((c) => /DECIMAL|BIGINT|DOUBLE/.test(c.type));
  const text = cols.find((c) => c.type === 'VARCHAR');
  const date = cols.find((c) => c.type === 'DATE' || c.type === 'TIMESTAMP');
  const out = [{ title: 'Count rows', sql: 'SELECT COUNT(*) AS row_count\nFROM data' }];
  if (text && num) out.push({ title: `Total ${num.label} by ${text.label}`, sql: `SELECT ${q(text.name)}, SUM(${q(num.name)}) AS total\nFROM data\nGROUP BY ${q(text.name)}\nORDER BY total DESC\nLIMIT 10` });
  if (num) out.push({ title: `Top 10 rows by ${num.label}`, sql: `SELECT *\nFROM data\nORDER BY ${q(num.name)} DESC NULLS LAST\nLIMIT 10` });
  if (date && num) out.push({ title: `${num.label} per month`, sql: `SELECT date_trunc('month', ${q(date.name)}) AS month, SUM(${q(num.name)}) AS total\nFROM data\nWHERE ${q(date.name)} IS NOT NULL\nGROUP BY month\nORDER BY month` });
  if (text) out.push({ title: `Distinct ${text.label} values`, sql: `SELECT ${q(text.name)}, COUNT(*) AS rows\nFROM data\nGROUP BY ${q(text.name)}\nORDER BY rows DESC` });
  return out;
}

function AiModal({ open, onClose, datasetId, onSql }) {
  const toast = useToast();
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  useEffect(() => { if (open) setRes(null); }, [open]);
  const ask = async () => {
    setBusy(true);
    try {
      const { data } = await api.post('/ai/sql/generate', { dataset_id: datasetId, question });
      setRes(data);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Ask AI to write SQL" width={620}
      footer={<><Button variant="secondary" onClick={onClose}>Close</Button>{res?.sql && <Button onClick={() => { onSql(res.sql); onClose(); }}>Use this SQL</Button>}</>}>
      <div className="stack">
        <p className="small muted">The AI sees table and column names and types{' '}<strong>but not your rows</strong>, unless you allowed sample rows in Settings. It only writes the query; results are always computed by DuckDB.</p>
        <Input label="Question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Total amount per region, highest first" onKeyDown={(e) => e.key === 'Enter' && question.trim().length > 2 && ask()} />
        <div><Button icon={MessageSquareText} onClick={ask} loading={busy} disabled={question.trim().length < 3}>Write SQL</Button></div>
        {res && (
          <div className="stack-sm">
            <pre>{res.sql}</pre>
            <Alert tone={res.valid ? 'success' : 'warning'}>{res.valid ? 'This query passed the read-only validation.' : `Validation: ${res.message}`}</Alert>
            <p className="xs muted">{res.provider} · {res.model}{res.sent_sample_rows ? ' · sample rows were sent' : ' · no rows were sent'}</p>
          </div>
        )}
      </div>
    </Modal>
  );
}

export default function SqlWorkbench() {
  usePageTitle('SQL Workbench');
  const toast = useToast();
  const { resolved } = useTheme();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const datasetId = params.get('dataset');
  const setDataset = useCallback((v) => setParams({ dataset: v }, { replace: true }), [setParams]);
  const [sql, setSql] = useState(location.state?.sql || 'SELECT *\nFROM data\nLIMIT 100');
  const [result, setResult] = useState(null);
  const [runError, setRunError] = useState(null);
  const [running, setRunning] = useState(false);
  const [validation, setValidation] = useState(null);
  const [side, setSide] = useState('schema');
  const [aiOpen, setAiOpen] = useState(false);
  const [explain, setExplain] = useState(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState('');
  const editorRef = useRef(null);

  const schemaReq = useApi(datasetId ? `/sql/${datasetId}/schema` : null);
  const saved = useApi(datasetId ? '/sql/saved' : null, { params: { dataset_id: datasetId } });
  const history = useApi(datasetId ? '/analyses' : null, { params: { analysis_type: 'sql', dataset_id: datasetId, page_size: 15 }, deps: [result] });
  const tables = schemaReq.data?.tables || [];
  const cmSchema = useMemo(() => Object.fromEntries(tables.map((t) => [t.name, (t.columns || []).map((c) => c.name)])), [tables]);
  const debouncedSql = useDebounced(sql, 500);

  useEffect(() => {
    if (!datasetId || !debouncedSql.trim()) return;
    api.post(`/sql/${datasetId}/validate`, { sql: debouncedSql }).then(({ data }) => setValidation(data)).catch(() => setValidation(null));
  }, [datasetId, debouncedSql]);

  const run = useCallback(async () => {
    if (!datasetId || running) return;
    setRunning(true);
    setRunError(null);
    try {
      const { data } = await api.post(`/sql/${datasetId}/run`, { sql });
      setResult(data);
    } catch (err) {
      const info = getErrorInfo(err);
      setRunError(info);
      setResult(null);
    } finally {
      setRunning(false);
    }
  }, [datasetId, sql, running]);

  const format = () => {
    try {
      setSql(formatSql(sql, { language: 'duckdb', keywordCase: 'upper' }));
    } catch {
      toast.error('Could not format this SQL. Fix the syntax first.');
    }
  };
  const insert = (text) => editorRef.current?.insert(text) ?? setSql((s) => `${s}${text}`);
  const doExplain = async () => {
    setExplain({ loading: true });
    try {
      const { data } = await api.post('/ai/sql/explain', { sql });
      setExplain(data);
    } catch (err) {
      setExplain(null);
      toast.error(errorMessage(err));
    }
  };
  const save = async () => {
    try {
      await api.post('/sql/saved', { dataset_id: datasetId, name: saveName.trim(), sql });
      toast.success('Query saved');
      setSaveOpen(false);
      setSaveName('');
      saved.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };
  const removeSaved = async (item) => {
    saved.setData((d) => ({ ...d, items: d.items.filter((x) => x.id !== item.id) }));
    try {
      await api.delete(`/sql/saved/${item.id}`);
    } catch (err) {
      toast.error(errorMessage(err));
      saved.reload();
    }
  };
  const loadHistory = async (id) => {
    try {
      const { data } = await api.get(`/analyses/${id}`);
      setSql(data.calculation_details?.equivalent_sql || data.question || '');
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  return (
    <div className="stack">
      <PageHeader
        module="sql"
        title="SQL Workbench"
        description="Read-only SQL on your cleaned data. Your active dataset is the table data; other datasets are ds_ tables."
        actions={<DatasetPicker value={datasetId} onChange={setDataset} />}
      />
      {!datasetId ? (
        <Card><EmptyState icon={Database} title="No cleaned datasets yet" message="Upload a dataset to query it with SQL." action={<Link to="/app/upload" className="btn btn-primary">Upload dataset</Link>} /></Card>
      ) : schemaReq.error ? (
        <ErrorState message={schemaReq.error} onRetry={schemaReq.reload} />
      ) : (
        <div className="sql-layout">
          <Card className="sql-side">
            <Tabs label="Workbench panels" value={side} onChange={setSide} tabs={[
              { value: 'schema', label: 'Schema' }, { value: 'examples', label: 'Examples' }, { value: 'saved', label: 'Saved' }, { value: 'history', label: 'History' },
            ]} />
            <div className="card-body stack-sm" style={{ maxHeight: 560, overflow: 'auto' }}>
              {side === 'schema' && (schemaReq.loading ? <Skeleton height={200} /> : tables.map((t, i) => (
                <Accordion key={t.name} defaultOpen={i === 0}
                  title={<span className="row" style={{ gap: 6 }}><Table2 size={14} aria-hidden="true" /><code>{t.name}</code></span>}
                  right={<span className="xs muted" title={t.dataset_name}>{t.dataset_name.slice(0, 18)}</span>}>
                  <button type="button" className="th-btn small" style={{ color: 'var(--primary)' }} onClick={() => insert(t.name)}>Insert table name</button>
                  <ul style={{ listStyle: 'none', padding: 0, margin: '6px 0 0' }}>
                    {(t.columns || []).map((c) => (
                      <li key={c.name}>
                        <button type="button" className="menu-item" style={{ minHeight: 30 }} onClick={() => insert(q(c.name))} title={`${c.label} — click to insert`}>
                          <code className="grow" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.name}</code>
                          <span className="xs muted">{c.type}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </Accordion>
              )))}
              {side === 'examples' && examples(tables[0]).map((ex) => (
                <button key={ex.title} type="button" className="menu-item" onClick={() => setSql(ex.sql)}>{ex.title}</button>
              ))}
              {side === 'saved' && (saved.data?.items?.length ? saved.data.items.map((s) => (
                <div key={s.id} className="row">
                  <button type="button" className="menu-item grow" onClick={() => setSql(s.sql)}>{s.name}</button>
                  <Button variant="ghost" size="sm" icon={Trash2} aria-label={`Delete saved query ${s.name}`} onClick={() => removeSaved(s)} />
                </div>
              )) : <p className="small muted">No saved queries for this dataset.</p>)}
              {side === 'history' && (history.data?.items?.length ? history.data.items.map((h) => (
                <button key={h.id} type="button" className="menu-item" onClick={() => loadHistory(h.id)} title={h.question}>
                  <HistoryIcon size={14} aria-hidden="true" />
                  <span className="grow mono xs" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.question}</span>
                  <span className="xs muted">{formatRelative(h.created_at)}</span>
                </button>
              )) : <p className="small muted">Queries you run appear here.</p>)}
            </div>
          </Card>
          <div className="stack" style={{ minWidth: 0 }}>
            <Card>
              <div className="card-body stack-sm">
                <div className="row-wrap between">
                  <div className="row-wrap">
                    <Button icon={Play} onClick={run} loading={running} disabled={validation && !validation.valid}>Run</Button>
                    <span className="xs muted hide-mobile">Ctrl+Enter</span>
                    <Button variant="secondary" size="sm" icon={AlignLeft} onClick={format}>Format</Button>
                    <Button variant="secondary" size="sm" icon={BookmarkPlus} onClick={() => setSaveOpen(true)} disabled={validation && !validation.valid}>Save</Button>
                  </div>
                  <div className="row-wrap">
                    <Button variant="ghost" size="sm" icon={MessageSquareText} onClick={() => setAiOpen(true)}>Write SQL from a question</Button>
                    <Button variant="ghost" size="sm" icon={HelpCircle} onClick={doExplain}>Explain this SQL</Button>
                  </div>
                </div>
                <Suspense fallback={<Skeleton height={220} />}>
                  <SqlEditor ref={editorRef} value={sql} onChange={setSql} onRun={run} schema={cmSchema} dark={resolved === 'dark'} />
                </Suspense>
                {validation && (
                  <p className="small" role="status" style={{ color: validation.valid ? 'var(--success)' : 'var(--danger)' }}>
                    {validation.valid ? '✓ ' : ''}{validation.message}{validation.line ? ` (line ${validation.line}, column ${validation.col})` : ''}
                  </p>
                )}
                {explain && (
                  <Alert tone="info" icon={HelpCircle}>
                    {explain.loading ? 'Explaining…' : (<><div style={{ whiteSpace: 'pre-wrap' }}>{explain.explanation}</div><p className="xs" style={{ marginTop: 6 }}>AI-written from the query text only (no data was sent) · {explain.provider}</p></>)}
                  </Alert>
                )}
              </div>
            </Card>
            <Card>
              <CardHeader title="Results" subtitle={result ? undefined : 'Run a query to see results here.'} />
              <div className="card-body">
                {running ? <Skeleton height={240} /> : runError ? (
                  <Alert tone="danger">{runError.message}{runError.details?.line ? ` (line ${runError.details.line}, column ${runError.details.col})` : ''}</Alert>
                ) : result ? <SqlResults result={result} datasetId={datasetId} /> : <EmptyState icon={Play} title="No results yet" message="Write a SELECT query and press Run." />}
              </div>
            </Card>
          </div>
        </div>
      )}
      <AiModal open={aiOpen} onClose={() => setAiOpen(false)} datasetId={datasetId} onSql={setSql} />
      <Modal open={saveOpen} onClose={() => setSaveOpen(false)} title="Save query"
        footer={<><Button variant="secondary" onClick={() => setSaveOpen(false)}>Cancel</Button><Button onClick={save} disabled={!saveName.trim()}>Save</Button></>}>
        <Input label="Name" value={saveName} onChange={(e) => setSaveName(e.target.value)} maxLength={120} autoFocus />
      </Modal>
      {schemaReq.data && <p className="xs muted">Limits: {schemaReq.data.max_rows.toLocaleString('en-IN')} rows per result · {schemaReq.data.timeout_seconds} s per query · one SELECT statement.{' '}<Badge>read-only</Badge></p>}
    </div>
  );
}

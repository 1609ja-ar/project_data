import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { BarChart3, CheckCircle2, FileSpreadsheet, Link2, RotateCcw, UploadCloud } from 'lucide-react';
import PageHeader from '../../components/PageHeader.jsx';
import CleaningProgress from '../../components/CleaningProgress.jsx';
import { CleanDownloadButton } from '../../components/CleanDownload.jsx';
import { Alert, Badge, Button, Card, CardHeader, DataTable, Input, Segmented, Select, useToast } from '../../components/ui/index.js';
import useDataset from '../../hooks/useDataset.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatBytes, formatInteger } from '../../utils/format.js';

const ACCEPT = ['.csv', '.xlsx', '.xls'];

export default function Upload() {
  usePageTitle('Upload dataset');
  const toast = useToast();
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [drag, setDrag] = useState(false);
  const [file, setFile] = useState(null);
  const [phase, setPhase] = useState('idle'); // idle | uploading | reading | processing | error
  const [pct, setPct] = useState(0);
  const [error, setError] = useState('');
  const [upload, setUpload] = useState(null);
  const [source, setSource] = useState('file'); // file | link
  const [link, setLink] = useState({ url: '', name: '' });
  const { dataset, reload } = useDataset(upload?.dataset.id);

  const reset = () => {
    setFile(null); setPhase('idle'); setPct(0); setError(''); setUpload(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const start = useCallback(async (f) => {
    if (!f) return;
    const ext = `.${f.name.split('.').pop().toLowerCase()}`;
    if (!ACCEPT.includes(ext)) {
      setError('Only .csv, .xlsx and .xls files are supported.');
      setPhase('error');
      return;
    }
    setFile(f); setError(''); setPhase('uploading'); setPct(0);
    const form = new FormData();
    form.append('file', f);
    try {
      const { data } = await api.post('/datasets/upload', form, {
        timeout: 0,
        onUploadProgress: (e) => {
          const p = e.total ? (e.loaded / e.total) * 100 : 0;
          setPct(p);
          if (p >= 100) setPhase('reading');
        },
      });
      setUpload(data);
      setPhase('processing');
    } catch (err) {
      setError(errorMessage(err));
      setPhase('error');
    }
  }, []);

  const importLink = async (e) => {
    e.preventDefault();
    setError(''); setPhase('reading'); setPct(100);
    try {
      const { data } = await api.post('/datasets/import-url', { url: link.url.trim(), name: link.name.trim() || null }, { timeout: 0 });
      setFile({ name: data.dataset.filename, size: data.dataset.size_bytes });
      setUpload(data);
      setPhase('processing');
    } catch (err) {
      setError(errorMessage(err));
      setPhase('error');
    }
  };
  const isSheet = /docs\.google\.com\/spreadsheets/.test(link.url);

  const changeSheet = async (sheet) => {
    try {
      await api.post(`/datasets/${upload.dataset.id}/clean`, { sheet });
      toast.info(`Cleaning sheet “${sheet}”`);
      reload();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const stage = phase === 'uploading' ? 'uploading' : phase === 'reading' ? 'reading'
    : dataset?.cleaning_status === 'done' ? 'done' : dataset?.cleaning_stage || 'cleaning';
  const failed = dataset?.cleaning_status === 'failed';
  const done = dataset?.cleaning_status === 'done';
  const multiSheet = upload?.sheets?.length > 1;

  // Straight to the dashboard once cleaning succeeds (workbooks stay here so another sheet can be picked).
  useEffect(() => {
    if (done && dataset?.active_version_id && !multiSheet) {
      navigate(`/app/dashboard?dataset=${dataset.id}`, { state: { uploaded: true } });
    }
  }, [done, dataset, multiSheet, navigate]);

  return (
    <div className="stack">
      <PageHeader module="upload" title="Upload" />

      {phase === 'idle' || phase === 'error' ? (
        <Card pad>
          <div style={{ marginBottom: 16 }}>
            <Segmented label="Where is the data?" value={source} onChange={(v) => { setSource(v); setError(''); setPhase('idle'); }}
              options={[{ value: 'file', label: 'File', icon: UploadCloud }, { value: 'link', label: 'Google Sheets or link', icon: Link2 }]} />
          </div>
          {source === 'link' ? (
            <form className="link-import" onSubmit={importLink}>
              <Input label="Link" type="url" required placeholder="https://docs.google.com/spreadsheets/d/…" value={link.url}
                onChange={(e) => setLink((l) => ({ ...l, url: e.target.value }))}
                hint={isSheet ? 'The tab open in the link (gid) is imported.' : 'A Google Sheet, or a public link to a .csv, .xlsx or .xls file (OneDrive, Dropbox, a website).'} />
              <Input label="Name (optional)" placeholder="e.g. Monthly sales" maxLength={150} value={link.name}
                onChange={(e) => setLink((l) => ({ ...l, name: e.target.value }))} />
              <div className="row-wrap">
                <Button type="submit" icon={Link2} disabled={!/^https:\/\//.test(link.url.trim())}>Import</Button>
                <span className="xs muted">For Google Sheets: Share → General access → <strong>Anyone with the link</strong> (Viewer). The sheet stays linked, so you can refresh it later.</span>
              </div>
            </form>
          ) : (
          <div
            className="dropzone"
            data-active={drag}
            role="button"
            tabIndex={0}
            aria-label="Choose a file to upload, or drop it here"
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); start(e.dataTransfer.files?.[0]); }}
          >
            <UploadCloud size={28} aria-hidden="true" style={{ color: 'var(--text-faint)', marginBottom: 8 }} />
            <h2 style={{ fontSize: 'var(--fs-md)' }}>Drop a file here, or <span style={{ color: 'var(--primary)' }}>browse</span></h2>
            <p className="small muted" style={{ marginTop: 4 }}>.csv up to 150 MB and 30 lakh rows · .xlsx or .xls up to 40 MB · password-protected and macro files are rejected</p>
            <input ref={inputRef} type="file" accept={ACCEPT.join(',')} hidden onChange={(e) => start(e.target.files?.[0])} />
          </div>
          )}
          {phase === 'error' && <div style={{ marginTop: 16 }}><Alert tone="danger">{error}</Alert></div>}
        </Card>
      ) : (
        <div className="grid-2" style={{ alignItems: 'start' }}>
          <Card>
            <CardHeader
              title={file?.name}
              subtitle={file ? formatBytes(file.size) : ''}
              actions={done ? <Badge tone="success"><CheckCircle2 size={12} /> Cleaned</Badge> : failed ? <Badge tone="danger">Failed</Badge> : <Badge tone="info">Processing</Badge>}
            />
            <div className="card-body stack">
              <CleaningProgress stage={stage} uploadPct={pct} counts={dataset?.cleaning_counts} failed={failed} />
              {failed && <Alert tone="danger">{dataset.cleaning_error}</Alert>}
              {upload?.sheets?.length > 1 && (
                <Select
                  label="Sheet"
                  value={dataset?.sheet || upload.dataset.sheet}
                  disabled={!done && !failed}
                  onChange={(e) => changeSheet(e.target.value)}
                  options={upload.sheets.map((s) => ({ value: s, label: s }))}
                  hint="Workbooks with several sheets: choose which sheet to analyze."
                />
              )}
              <div className="row-wrap">
                {done && <Link to={`/app/dashboard?dataset=${upload.dataset.id}`} className="btn btn-primary"><BarChart3 size={15} aria-hidden="true" /> Open dashboard</Link>}
                {done && <CleanDownloadButton datasetId={upload.dataset.id} />}
                {(done || failed) && <Link to={`/app/datasets/${upload.dataset.id}`} className={`btn ${failed ? 'btn-primary' : 'btn-secondary'}`}>{failed ? 'Open dataset to retry' : 'Review cleaning'}</Link>}
                {(done || failed) && <Button variant="ghost" icon={RotateCcw} onClick={reset}>Upload another</Button>}
              </div>
            </div>
          </Card>
          {upload && (
            <Card>
              <CardHeader
                title="Raw preview (as uploaded)"
                subtitle={`${formatInteger(upload.dataset.raw_row_count)} rows × ${formatInteger(upload.dataset.raw_column_count)} columns, no type conversion`}
              />
              <div className="card-body stack">
                <div className="row-wrap">
                  <FileSpreadsheet size={16} aria-hidden="true" className="muted" />
                  <span className="small muted">Detected columns:</span>
                  {upload.column_names.slice(0, 12).map((n, i) => <Badge key={i}>{n}</Badge>)}
                  {upload.column_names.length > 12 && <span className="xs muted">+{upload.column_names.length - 12} more</span>}
                </div>
                <DataTable columns={upload.raw_preview.columns} rows={upload.raw_preview.rows} pageSize={20} maxHeight={360} caption="Raw file preview" />
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

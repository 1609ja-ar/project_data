import { useEffect, useState } from 'react';
import { Braces, Download, FileArchive, FileSpreadsheet, FileText, Search, Sheet } from 'lucide-react';
import { Alert, Badge, Button, Input, Modal, Skeleton, useToast } from './ui/index.js';
import useApi from '../hooks/useApi.js';
import api from '../services/api.js';
import { blobError, saveBlob } from '../utils/download.js';
import { formatInteger } from '../utils/format.js';

// What each format is for, in the order people usually need them.
export const FORMATS = [
  { id: 'zip', label: 'Share pack', ext: '.zip', icon: FileArchive, best: true,
    help: 'Clean CSV + data dictionary + cleaning report + README with a checksum. Best for sending to someone.' },
  { id: 'xlsx', label: 'Excel workbook', ext: '.xlsx', icon: FileSpreadsheet,
    help: 'Numbers and dates as real Excel values, a frozen header row with filters, plus Data dictionary and Cleaning report sheets.' },
  { id: 'csv_excel', label: 'CSV for Excel', ext: '.csv', icon: Sheet,
    help: 'Opens correctly when double-clicked in Excel (keeps ₹, €, accents).' },
  { id: 'csv', label: 'CSV', ext: '.csv', icon: FileText,
    help: 'Plain UTF-8 for Python, R, SQL, Power BI or Google Sheets.' },
  { id: 'json', label: 'JSON', ext: '.json', icon: Braces,
    help: 'One record per row with numbers, true/false and dates as YYYY-MM-DD text. For developers and APIs.' },
];

// Column names that often hold personal data; flagged so people can leave them out before sharing.
const PERSONAL = /(e-?mail|phone|mobile|contact|address|customer.?name|full.?name|first.?name|last.?name|surname|birth|dob\b|ssn|aadhaa?r|passport|pan.?(no|number)|account.?(no|number)|ip.?address)/i;
export const looksPersonal = (name) => PERSONAL.test(name);

/** Downloads a cleaned version. Returns the toast text; throws the API's message on failure. */
export async function downloadClean(datasetId, format, columns) {
  const params = { format, ...(columns ? { columns: columns.join(',') } : {}) };
  const res = await api.get(`/datasets/${datasetId}/download`, { params, responseType: 'blob', timeout: 0 });
  saveBlob(res, `clean_data${FORMATS.find((f) => f.id === format)?.ext || ''}`);
  return `Downloaded ${formatInteger(Number(res.headers['x-rows-exported']))} rows × ${res.headers['x-columns-exported']} columns`;
}

/** "Download clean data": pick a format and (optionally) leave out columns before sharing. */
export function CleanDownloadDialog({ open, onClose, datasetId }) {
  const toast = useToast();
  const ds = useApi(open && datasetId ? `/datasets/${datasetId}` : null);
  const [format, setFormat] = useState('zip');
  const [cols, setCols] = useState(null);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const v = ds.data?.active_version;
  const schema = v?.schema || [];
  const counts = ds.data?.cleaning_counts;

  useEffect(() => { if (open) { setCols(null); setQ(''); } }, [open, datasetId]);

  const chosen = cols ?? schema.map((c) => c.key);
  const all = chosen.length === schema.length;
  const personal = schema.filter((c) => looksPersonal(c.display_name));
  const shown = schema.filter((c) => c.display_name.toLowerCase().includes(q.toLowerCase()));
  const toggle = (key, on) => setCols(() => {
    const next = on ? [...chosen, key] : chosen.filter((k) => k !== key);
    return schema.map((c) => c.key).filter((k) => next.includes(k)); // keep the dataset's column order
  });

  const run = async () => {
    setBusy(true);
    try {
      toast.success(await downloadClean(datasetId, format, all ? null : chosen));
    } catch (err) {
      toast.error(await blobError(err));
    } finally {
      setBusy(false);
    }
  };

  const f = FORMATS.find((x) => x.id === format);
  return (
    <Modal open={open} onClose={onClose} title="Download clean data" width={720}
      footer={<>
        <span className="xs muted grow">{v ? `${formatInteger(v.row_count)} rows × ${chosen.length} columns · version ${v.version_number}` : ''}</span>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button icon={Download} onClick={run} loading={busy} disabled={!v || chosen.length === 0}>Download {f.ext}</Button>
      </>}>
      {ds.error ? <Alert tone="danger">{ds.error}</Alert> : !ds.data ? <Skeleton height={320} /> : !v ? (
        <Alert tone="info">This dataset has no cleaned version yet. Wait for cleaning to finish, then download it here.</Alert>
      ) : (
        <div className="stack">
          <div className="cd-summary">
            <strong className="small">{ds.data.filename}</strong>
            {counts && (
              <span className="xs muted">
                Cleaned: {formatInteger(counts.rows_before)} rows read, {formatInteger(counts.rows_removed)} removed, {formatInteger(counts.cells_changed)} values fixed
                {v.quality_score_after != null && <> · quality {v.quality_score_before} → {v.quality_score_after}</>}
              </span>
            )}
          </div>

          <fieldset className="cd-formats">
            <legend className="label">Format</legend>
            {FORMATS.map((x) => (
              <label key={x.id} className="cd-format" data-on={format === x.id}>
                <input type="radio" name="clean-format" value={x.id} checked={format === x.id} onChange={() => setFormat(x.id)} />
                <span className="cd-format-icon" aria-hidden="true"><x.icon size={18} /></span>
                <span className="grow">
                  <span className="row" style={{ gap: 6 }}>
                    <strong className="small">{x.label}</strong><span className="xs muted">{x.ext}</span>
                    {x.best && <Badge tone="success">Best for sharing</Badge>}
                  </span>
                  <span className="xs muted">{x.help}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div>
            <div className="row between" style={{ marginBottom: 6 }}>
              <span className="label" style={{ margin: 0 }}>Columns · {chosen.length} of {schema.length}</span>
              <span className="row" style={{ gap: 0 }}>
                <Button variant="ghost" size="sm" onClick={() => setCols(null)}>All</Button>
                {personal.length > 0 && (
                  <Button variant="ghost" size="sm" onClick={() => setCols(schema.filter((c) => !looksPersonal(c.display_name)).map((c) => c.key))}>Leave out personal</Button>
                )}
              </span>
            </div>
            {personal.length > 0 && all && (
              <p className="xs muted" style={{ marginBottom: 6 }}>
                {personal.length === 1 ? `“${personal[0].display_name}” may hold` : `${personal.length} columns may hold`} personal data. Consider leaving {personal.length === 1 ? 'it' : 'them'} out before sharing.
              </p>
            )}
            {schema.length > 8 && <Input lead={Search} placeholder="Search columns" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search columns" />}
            <div className="col-picks cd-cols">
              {shown.map((c) => (
                <label key={c.key} className="option">
                  <input type="checkbox" checked={chosen.includes(c.key)} onChange={(e) => toggle(c.key, e.target.checked)} />
                  <span className="grow">{c.display_name}</span>
                  {looksPersonal(c.display_name) && <Badge tone="warning">personal?</Badge>}
                  <Badge>{c.semantic_type === 'currency' ? 'money' : c.dtype}</Badge>
                </label>
              ))}
            </div>
            {chosen.length === 0 && <p className="xs" style={{ color: 'var(--danger)', marginTop: 6 }}>Select at least one column.</p>}
          </div>
        </div>
      )}
    </Modal>
  );
}

/** Button that opens the dialog. */
export function CleanDownloadButton({ datasetId, variant = 'secondary', size, label = 'Download clean data', iconOnly = false }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant={variant} size={size} icon={Download} onClick={() => setOpen(true)} aria-label={label} title={label}>{iconOnly ? null : label}</Button>
      <CleanDownloadDialog open={open} onClose={() => setOpen(false)} datasetId={datasetId} />
    </>
  );
}

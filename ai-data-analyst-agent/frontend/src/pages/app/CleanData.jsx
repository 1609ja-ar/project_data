import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Database, Download, Search, SlidersHorizontal, Upload } from 'lucide-react';
import PageHeader from '../../components/PageHeader.jsx';
import { CleanDownloadDialog, FORMATS, downloadClean } from '../../components/CleanDownload.jsx';
import { Badge, Button, Card, EmptyState, ErrorState, Input, Skeleton, useToast } from '../../components/ui/index.js';
import useApi, { useDebounced } from '../../hooks/useApi.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import { STATUS_LABEL, STATUS_TONE } from '../../hooks/useDataset.js';
import { blobError } from '../../utils/download.js';
import { formatInteger, formatRelative } from '../../utils/format.js';

const QUICK = ['zip', 'xlsx', 'csv'];

/** One place to download the cleaned version of any dataset, ready to share. */
export default function CleanData() {
  usePageTitle('Clean data');
  const toast = useToast();
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const debounced = useDebounced(q);
  const { data, loading, error, reload } = useApi('/datasets', { params: { q: debounced || undefined, page, page_size: 20 } });
  const [busy, setBusy] = useState(null);
  const [options, setOptions] = useState(null);

  const quick = async (d, format) => {
    setBusy(`${d.id}:${format}`);
    try {
      toast.success(await downloadClean(d.id, format));
    } catch (err) {
      toast.error(await blobError(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="stack">
      <PageHeader module="downloads" title="Clean data"
        description="Download the cleaned version of a file to share it. The original upload is never changed."
        actions={<Link to="/app/upload" className="btn btn-primary"><Upload size={15} aria-hidden="true" /> Upload file</Link>} />

      <div className="cd-guide">
        {FORMATS.map((f) => (
          <div key={f.id} className="cd-guide-item">
            <span className="cd-format-icon" aria-hidden="true"><f.icon size={16} /></span>
            <span><strong className="small">{f.label}</strong> <span className="xs muted">{f.ext}</span><br /><span className="xs muted">{f.help}</span></span>
          </div>
        ))}
      </div>

      <div style={{ maxWidth: 360 }}>
        <Input lead={Search} placeholder="Search by file name" aria-label="Search datasets by file name" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      </div>
      {error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : loading && !data ? (
        <div className="stack-sm">{[0, 1, 2].map((i) => <Card key={i} pad><Skeleton height={18} width="40%" /></Card>)}</div>
      ) : data.items.length === 0 ? (
        <Card>
          <EmptyState icon={Database} title={debounced ? 'No matching datasets' : 'Nothing to download yet'}
            message={debounced ? `Nothing matches “${debounced}”.` : 'Upload a CSV or Excel file. Once it is cleaned, it appears here ready to download.'}
            action={!debounced && <Link to="/app/upload" className="btn btn-primary">Upload file</Link>} />
        </Card>
      ) : (
        <Card>
          <div className="table-wrap" style={{ border: 'none' }}>
            <table className="table">
              <caption className="sr-only">Cleaned datasets you can download</caption>
              <thead>
                <tr><th>File</th><th>Status</th><th className="num">Rows</th><th className="num">Columns</th><th>Uploaded</th><th><span className="sr-only">Downloads</span></th></tr>
              </thead>
              <tbody>
                {data.items.map((d) => {
                  const ready = Boolean(d.active_version_id);
                  return (
                    <tr key={d.id}>
                      <td><Link to={`/app/datasets/${d.id}`} style={{ fontWeight: 600 }}>{d.filename}</Link>{d.sheet && <span className="xs muted"> · {d.sheet}</span>}</td>
                      <td><Badge tone={STATUS_TONE[d.cleaning_status]}>{STATUS_LABEL[d.cleaning_status]}</Badge></td>
                      <td className="num">{formatInteger(d.row_count)}</td>
                      <td className="num">{formatInteger(d.column_count)}</td>
                      <td className="muted">{formatRelative(d.created_at)}</td>
                      <td style={{ textAlign: 'right' }}>
                        {ready ? (
                          <span className="row" style={{ justifyContent: 'flex-end', gap: 4, flexWrap: 'wrap' }}>
                            {QUICK.map((id) => {
                              const f = FORMATS.find((x) => x.id === id);
                              return (
                                <Button key={id} variant={id === 'zip' ? 'primary' : 'secondary'} size="sm" icon={id === 'zip' ? Download : f.icon}
                                  loading={busy === `${d.id}:${id}`} disabled={Boolean(busy)} onClick={() => quick(d, id)}
                                  aria-label={`Download ${d.filename} as ${f.label}`} title={f.help}>
                                  {id === 'zip' ? 'Share pack' : f.label.replace(' workbook', '')}
                                </Button>
                              );
                            })}
                            <Button variant="ghost" size="sm" icon={SlidersHorizontal} onClick={() => setOptions(d.id)} aria-label={`More download options for ${d.filename}`} title="Choose columns or another format" />
                          </span>
                        ) : <span className="xs muted">Available when cleaning finishes</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {data.pagination.pages > 1 && (
            <div className="pager" style={{ padding: '12px 20px' }}>
              <span className="small muted">Page {page} of {data.pagination.pages}</span>
              <div className="row">
                <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button size="sm" variant="secondary" disabled={page >= data.pagination.pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </Card>
      )}
      <CleanDownloadDialog open={Boolean(options)} onClose={() => setOptions(null)} datasetId={options} />
    </div>
  );
}

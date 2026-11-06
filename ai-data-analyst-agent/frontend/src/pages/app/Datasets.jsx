import { useState } from 'react';
import { Link } from 'react-router-dom';
import { BarChart3, Database, Search, Terminal, Trash2, Upload } from 'lucide-react';
import PageHeader from '../../components/PageHeader.jsx';
import { CleanDownloadButton } from '../../components/CleanDownload.jsx';
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Input, Skeleton, useToast } from '../../components/ui/index.js';
import useApi, { useDebounced } from '../../hooks/useApi.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import { STATUS_LABEL, STATUS_TONE } from '../../hooks/useDataset.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatBytes, formatInteger, formatRelative } from '../../utils/format.js';

export default function Datasets() {
  usePageTitle('Datasets');
  const toast = useToast();
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const debounced = useDebounced(q);
  const { data, loading, error, reload, setData } = useApi('/datasets', { params: { q: debounced || undefined, page, page_size: 20 } });
  const [confirm, setConfirm] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const remove = async () => {
    const target = confirm;
    setDeleting(true);
    const before = data;
    setData((d) => ({ ...d, items: d.items.filter((x) => x.id !== target.id), pagination: { ...d.pagination, total: d.pagination.total - 1 } }));
    setConfirm(null);
    try {
      await api.delete(`/datasets/${target.id}`);
      toast.success(`Deleted “${target.filename}”`);
    } catch (err) {
      setData(before);
      toast.error(errorMessage(err));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        module="datasets"
        title="Datasets"
        actions={<><Link to="/app/sql" className="btn btn-secondary"><Terminal size={15} aria-hidden="true" /> SQL</Link><Link to="/app/upload" className="btn btn-primary"><Upload size={15} aria-hidden="true" /> Upload file</Link></>}
      />
      <div style={{ maxWidth: 360 }}>
        <Input lead={Search} placeholder="Search by file name" aria-label="Search datasets by file name" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      </div>
      {error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : loading && !data ? (
        <div className="stack-sm">{[0, 1, 2].map((i) => <Card key={i} pad><Skeleton height={18} width="40%" /><Skeleton height={14} width="25%" style={{ marginTop: 8 }} /></Card>)}</div>
      ) : data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={Database}
            title={debounced ? 'No matching datasets' : 'No datasets yet'}
            message={debounced ? `Nothing matches “${debounced}”.` : 'Upload a CSV or Excel file to get started.'}
            action={!debounced && <Link to="/app/upload" className="btn btn-primary">Upload dataset</Link>}
          />
        </Card>
      ) : (
        <Card>
          <div className="table-wrap" style={{ border: 'none' }}>
            <table className="table">
              <caption className="sr-only">Your datasets</caption>
              <thead>
                <tr><th>Name</th><th>Status</th><th className="num">Rows</th><th className="num">Columns</th><th className="num">Size</th><th>Uploaded</th><th><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>
                {data.items.map((d) => (
                  <tr key={d.id}>
                    <td><Link to={`/app/datasets/${d.id}`} style={{ fontWeight: 600 }}>{d.filename}</Link>{d.sheet && <span className="xs muted"> · {d.sheet}</span>}</td>
                    <td><Badge tone={STATUS_TONE[d.cleaning_status]}>{STATUS_LABEL[d.cleaning_status]}</Badge></td>
                    <td className="num">{formatInteger(d.row_count)}</td>
                    <td className="num">{formatInteger(d.column_count)}</td>
                    <td className="num">{formatBytes(d.size_bytes)}</td>
                    <td className="muted">{formatRelative(d.created_at)}</td>
                    <td style={{ textAlign: 'right' }}>
                      <span className="row" style={{ justifyContent: 'flex-end', gap: 4 }}>
                        {d.active_version_id && <Link to={`/app/dashboard?dataset=${d.id}`} className="btn btn-secondary btn-sm"><BarChart3 size={14} aria-hidden="true" /> Dashboard</Link>}
                        {d.active_version_id && <CleanDownloadButton datasetId={d.id} variant="ghost" size="sm" iconOnly label={`Download clean ${d.filename}`} />}
                        <Button variant="ghost" size="sm" icon={Trash2} aria-label={`Delete ${d.filename}`} onClick={() => setConfirm(d)} />
                      </span>
                    </td>
                  </tr>
                ))}
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
      <ConfirmDialog
        open={Boolean(confirm)}
        title="Delete dataset?"
        message={confirm ? `“${confirm.filename}”, its original file, all cleaned versions and every analysis, query and report made from it will be deleted. This cannot be undone.` : ''}
        confirmLabel="Delete"
        danger
        loading={deleting}
        onConfirm={remove}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

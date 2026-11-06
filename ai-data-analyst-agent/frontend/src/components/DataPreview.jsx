import { useEffect, useMemo, useState } from 'react';
import { DataTable, ErrorState, Skeleton } from './ui/index.js';
import ProfilingStrip from './ProfilingStrip.jsx';
import api from '../services/api.js';
import { errorMessage } from '../services/errors.js';

/** Server-paged, server-sorted preview of a dataset version (or the raw grid). */
export default function DataPreview({ datasetId, version, highlight = false, schema, onOpenColumn, pageSize = 50, onMeta }) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState(null);
  const [state, setState] = useState({ data: null, loading: true, error: null });

  useEffect(() => { setPage(1); setSort(null); }, [datasetId, version]);

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    api.get(`/datasets/${datasetId}/preview`, {
      params: { version, page, page_size: pageSize, sort: sort?.key, dir: sort?.dir, highlight: highlight || undefined },
    })
      .then(({ data }) => { if (!cancelled) { setState({ data, loading: false, error: null }); onMeta?.(data); } })
      .catch((err) => { if (!cancelled) setState({ data: null, loading: false, error: errorMessage(err) }); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, version, page, sort, highlight, pageSize]);

  const changed = useMemo(() => {
    const set = new Set();
    (state.data?.changed || []).forEach(([r, c]) => set.add(`${r}:${c}`));
    return set;
  }, [state.data]);

  const bySchema = useMemo(() => Object.fromEntries((schema || []).map((c) => [c.key, c])), [schema]);
  const { data, loading, error } = state;
  if (error) return <ErrorState message={error} />;
  if (!data) return <Skeleton height={320} />;

  const columns = data.columns.map((c) => ({ ...c, label: c.label || c.display_name, ...(bySchema[c.key] ? { profile: bySchema[c.key].profile, invalid: bySchema[c.key].invalid } : {}) }));
  const colIndex = Object.fromEntries(columns.map((c, i) => [c.key, i]));
  const offset = (page - 1) * pageSize;
  return (
    <div aria-busy={loading} style={{ opacity: loading ? 0.6 : 1, transition: 'opacity 150ms' }}>
      <DataTable
        columns={columns}
        rows={data.rows}
        page={page}
        pageSize={pageSize}
        total={data.pagination.total}
        onPageChange={setPage}
        sort={sort}
        onSort={(s) => { setSort(s); setPage(1); }}
        headerExtra={schema ? (c) => <ProfilingStrip column={c} onOpen={onOpenColumn} /> : undefined}
        isChanged={highlight ? (ri, key) => changed.has(`${ri - offset}:${colIndex[key]}`) : undefined}
        caption={`Dataset preview, page ${page}`}
      />
    </div>
  );
}

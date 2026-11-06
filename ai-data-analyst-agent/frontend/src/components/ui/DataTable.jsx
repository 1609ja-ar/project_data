import { memo, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight } from 'lucide-react';
import Button from './Button.jsx';
import { formatCell, formatInteger, isNumericCol } from '../../utils/format.js';

/**
 * Generic table.
 * columns: [{ key, label, dtype, semantic_type }]
 * rows: array of arrays (aligned with columns) or objects keyed by column key.
 * Pagination: pass page/pageSize/total/onPageChange for server-side paging, otherwise client-side.
 * Sorting: pass sort/onSort for server-side sorting, otherwise client-side within the loaded rows.
 */
function DataTable({
  columns,
  rows,
  page: extPage,
  pageSize = 25,
  total,
  onPageChange,
  sort: extSort,
  onSort,
  headerExtra,
  isChanged,
  caption,
  maxHeight = 520,
}) {
  const [localPage, setLocalPage] = useState(1);
  const [localSort, setLocalSort] = useState(null);
  const serverPaged = typeof onPageChange === 'function';
  const sort = onSort ? extSort : localSort;
  const page = serverPaged ? extPage : localPage;

  const getVal = (row, col, i) => (Array.isArray(row) ? row[i] : row[col.key]);

  const sorted = useMemo(() => {
    if (onSort || !localSort) return rows;
    const i = columns.findIndex((c) => c.key === localSort.key);
    if (i < 0) return rows;
    const col = columns[i];
    const dir = localSort.dir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => {
      const va = getVal(a, col, i);
      const vb = getVal(b, col, i);
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (isNumericCol(col)) return (Number(va) - Number(vb)) * dir;
      return String(va).localeCompare(String(vb)) * dir;
    });
  }, [rows, columns, localSort, onSort]);

  const totalRows = serverPaged ? total ?? rows.length : sorted.length;
  const pages = Math.max(1, Math.ceil(totalRows / pageSize));
  const visible = serverPaged ? sorted : sorted.slice((page - 1) * pageSize, page * pageSize);
  const offset = (page - 1) * pageSize;

  const toggleSort = (key) => {
    const next = !sort || sort.key !== key ? { key, dir: 'asc' } : sort.dir === 'asc' ? { key, dir: 'desc' } : null;
    if (onSort) onSort(next);
    else setLocalSort(next);
  };
  const goto = (p) => (serverPaged ? onPageChange(p) : setLocalPage(p));

  return (
    <div>
      <div className="table-wrap" style={{ maxHeight }}>
        <table className="table">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead>
            <tr>
              {columns.map((c) => {
                const active = sort?.key === c.key;
                const Icon = active ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown;
                return (
                  <th key={c.key} className={isNumericCol(c) ? 'num' : ''} aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'} scope="col">
                    <button type="button" className="th-btn" onClick={() => toggleSort(c.key)} title={c.label}>
                      {c.label}
                      <Icon size={12} aria-hidden="true" style={{ opacity: active ? 1 : 0.4 }} />
                    </button>
                    {headerExtra && <div style={{ marginTop: 6, fontWeight: 400 }}>{headerExtra(c)}</div>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, ri) => (
              <tr key={ri}>
                {columns.map((c, ci) => {
                  const v = getVal(row, c, ci);
                  const txt = formatCell(v, c);
                  const changed = isChanged?.(offset + ri, c.key);
                  return (
                    <td key={c.key} className={[isNumericCol(c) && 'num', changed && 'changed'].filter(Boolean).join(' ')} title={txt ?? 'null'}>
                      {txt === null ? <span className="null">null</span> : txt}
                    </td>
                  );
                })}
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="muted" style={{ textAlign: 'center', padding: 24 }}>No rows</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <nav className="pager" aria-label="Table pagination">
          <span className="small muted num">
            Rows {formatInteger(offset + 1)}–{formatInteger(Math.min(offset + pageSize, totalRows))} of {formatInteger(totalRows)}
          </span>
          <div className="row">
            <Button variant="secondary" size="sm" icon={ChevronLeft} onClick={() => goto(page - 1)} disabled={page <= 1} aria-label="Previous page" />
            <span className="small num">Page {page} / {pages}</span>
            <Button variant="secondary" size="sm" icon={ChevronRight} onClick={() => goto(page + 1)} disabled={page >= pages} aria-label="Next page" />
          </div>
        </nav>
      )}
    </div>
  );
}

export default memo(DataTable);

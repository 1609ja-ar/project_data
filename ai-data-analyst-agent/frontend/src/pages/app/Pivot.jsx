import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronDown, ChevronRight, Database, Download, FileSpreadsheet, Plus, ShieldCheck, X } from 'lucide-react';
import PageHeader from '../../components/PageHeader.jsx';
import DatasetPicker from '../../components/DatasetPicker.jsx';
import CalcDrawer from '../../components/CalcDrawer.jsx';
import MultiSelect from '../../components/dashboard/MultiSelect.jsx';
import { Alert, Button, Card, EmptyState, Input, Segmented, Select, Skeleton, Switch, useToast } from '../../components/ui/index.js';
import useApi from '../../hooks/useApi.js';
import useDataset from '../../hooks/useDataset.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { blobError, saveBlob } from '../../utils/download.js';
import { formatCell, formatInteger, formatPercent, formatPeriod } from '../../utils/format.js';

const NUMERIC = ['integer', 'float', 'decimal'];
const AGGS = [
  { value: 'sum', label: 'Sum', numeric: true }, { value: 'mean', label: 'Average', numeric: true },
  { value: 'median', label: 'Median', numeric: true }, { value: 'min', label: 'Minimum', numeric: true },
  { value: 'max', label: 'Maximum', numeric: true }, { value: 'count', label: 'Count' }, { value: 'nunique', label: 'Distinct count' },
];
const GRAINS = ['day', 'week', 'month', 'quarter', 'year'].map((g) => ({ value: g, label: g[0].toUpperCase() + g.slice(1) }));
const ROW_H = 34;
const VIEW_H = 560;
const OVERSCAN = 8;
const SHOW_AS = [
  { value: 'values', label: 'Values' }, { value: 'grand', label: '% of total' }, { value: 'row', label: '% of row' },
  { value: 'column', label: '% of column' }, { value: 'parent', label: '% of parent' },
];

function csvCell(v) {
  const s = v === null || v === undefined ? '' : String(v);
  const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}
const pathKey = (p) => p.join('\u0001');
const ratio = (a, b) => (typeof a === 'number' && typeof b === 'number' && b !== 0 ? a / b : null);

/** Pivot table over every row of the dataset. All numbers come from the backend, where each level is calculated
 *  from the underlying rows and re-checked by a second engine. This page only arranges them. */
export default function Pivot() {
  usePageTitle('Pivot');
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const datasetId = params.get('dataset');
  const setDataset = useCallback((v) => setParams({ dataset: v }, { replace: true }), [setParams]);
  const { dataset } = useDataset(datasetId);
  const meta = useApi(datasetId ? `/analytics/${datasetId}/dashboard` : null, { method: 'post' });
  const schema = useMemo(() => dataset?.active_version?.schema || [], [dataset]);

  const groupable = useMemo(() => schema.filter((c) => !['float', 'decimal'].includes(c.dtype) && c.semantic_type !== 'email'), [schema]);
  const measureCols = useMemo(() => schema.filter((c) => NUMERIC.includes(c.dtype) && c.semantic_type !== 'id'), [schema]);
  const [spec, setSpec] = useState(null);
  const [filters, setFilters] = useState({});
  const [show, setShow] = useState('values');
  const [heat, setHeat] = useState(true);
  const [totals, setTotals] = useState({ rows: true, columns: true });
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState({ data: null, loading: false, error: null });
  const [scroll, setScroll] = useState(0);

  // A sensible first pivot: the first category by the first money/number column, split by a second category.
  useEffect(() => {
    if (!schema.length) return;
    const cats = groupable.filter((c) => c.semantic_type === 'category');
    const date = schema.find((c) => c.dtype === 'date' || c.dtype === 'datetime');
    const m = measureCols.find((c) => c.semantic_type === 'currency') || measureCols[0];
    setSpec({
      rows: [(cats[0] || date || groupable[0])?.key].filter(Boolean), columns: cats[1]?.key || '',
      measures: [m ? { column: m.key, aggregation: 'sum' } : { column: '', aggregation: 'count' }],
      grain: 'month', sortBy: 'auto', sortDir: '', sortMeasure: 0, colSort: 'label', topN: '',
    });
    setFilters({});
    setCollapsed(new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema]);

  const hasDate = spec && [...spec.rows, spec.columns].some((k) => ['date', 'datetime'].includes(schema.find((c) => c.key === k)?.dtype));
  const body = useMemo(() => spec && spec.rows.length > 0 && {
    rows: spec.rows, columns: spec.columns || null,
    measures: spec.measures.map((m) => ({ column: m.column || null, aggregation: m.column ? m.aggregation : 'count' })),
    grain: spec.grain, sort: { by: spec.sortBy, direction: spec.sortDir || null, measure: Math.min(spec.sortMeasure, spec.measures.length - 1) },
    col_sort: spec.colSort, top_n: spec.topN ? Number(spec.topN) : null,
    filters: Object.entries(filters).filter(([, v]) => v.length).map(([column, value]) => ({ column, op: 'in', value })),
  }, [spec, filters]);
  const bodyKey = JSON.stringify(body);

  useEffect(() => {
    if (!datasetId || !body) return undefined;
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    const t = setTimeout(() => {
      api.post(`/analytics/${datasetId}/pivot`, JSON.parse(bodyKey), { timeout: 0 })
        .then(({ data }) => { if (live) { setState({ data, loading: false, error: null }); setCollapsed(new Set()); } })
        .catch((err) => live && setState((s) => ({ ...s, loading: false, error: errorMessage(err) })));
    }, 300);
    return () => { live = false; clearTimeout(t); };
  }, [datasetId, bodyKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const patch = (p) => setSpec((s) => ({ ...s, ...p }));
  const setRow = (i, key) => setSpec((s) => {
    const rows = s.rows.map((r, j) => (j === i ? key : r));
    return { ...s, rows, columns: rows.includes(s.columns) ? '' : s.columns };
  });
  const setMeasure = (i, p) => setSpec((s) => ({
    ...s,
    measures: s.measures.map((m, j) => {
      if (j !== i) return m;
      const next = { ...m, ...p };
      const col = schema.find((c) => c.key === next.column);
      if (!next.column) return { column: '', aggregation: 'count' };
      if (!NUMERIC.includes(col?.dtype) && AGGS.find((a) => a.value === next.aggregation)?.numeric) next.aggregation = 'count';
      if (p.column && !m.column) next.aggregation = NUMERIC.includes(col?.dtype) ? 'sum' : 'count';
      return next;
    }),
  }));

  const d = state.data;
  const nm = d?.measures.length || 0;
  const hasCols = Boolean(d?.column_field);
  const grain = d?.grain;
  const showOptions = d ? SHOW_AS.filter((o) => o.value === 'values' || (d.measures.some((m) => m.additive)
    && (hasCols || (o.value !== 'row' && o.value !== 'column')) && (o.value !== 'parent' || d.row_fields.length > 1 || hasCols))) : SHOW_AS;
  const mode = showOptions.some((o) => o.value === show) ? show : 'values';
  const additive = (mi) => d.measures[mi].additive;

  // Rows hidden by a collapsed ancestor are skipped; the table below only renders what is scrolled into view.
  const rowByPath = useMemo(() => {
    const map = new Map();
    d?.rows.forEach((r) => map.set(pathKey(r.path), r));
    return map;
  }, [d]);
  const visible = useMemo(() => {
    if (!d) return [];
    return d.rows.filter((r) => {
      for (let i = 1; i < r.path.length; i += 1) if (collapsed.has(pathKey(r.path.slice(0, i)))) return false;
      return true;
    });
  }, [d, collapsed]);
  const subtotalKeys = useMemo(() => (d ? d.rows.filter((r) => r.subtotal).map((r) => pathKey(r.path)) : []), [d]);

  const shown = (value, mi, base) => {
    if (value === null || value === undefined) return null;
    if (mode === 'values' || !additive(mi)) return { text: formatCell(value, d.measures[mi].column) ?? String(value), n: value };
    const p = ratio(value, base);
    return p === null ? null : { text: formatPercent(p), n: p };
  };
  const cell = (row, c, mi) => {
    const idx = c * nm + mi;
    const v = row.cells[idx];
    let base = d.grand_total[mi];
    if (mode === 'row') base = row.totals[mi];
    else if (mode === 'column') base = d.column_totals[idx];
    else if (mode === 'parent') {
      const parent = rowByPath.get(pathKey(row.path.slice(0, -1)));
      base = parent ? parent.cells[idx] : d.column_totals[idx];
    }
    return shown(v, mi, base);
  };
  const totalCell = (row, mi) => {
    let base = d.grand_total[mi];
    if (mode === 'row') base = row.totals[mi];
    else if (mode === 'parent') {
      const parent = rowByPath.get(pathKey(row.path.slice(0, -1)));
      base = parent ? parent.totals[mi] : d.grand_total[mi];
    }
    return shown(row.totals[mi], mi, base);
  };
  const colTotalCell = (c, mi) => {
    const idx = c * nm + mi;
    return shown(d.column_totals[idx], mi, mode === 'column' || mode === 'parent' ? d.column_totals[idx] : d.grand_total[mi]);
  };
  const grandCell = (mi) => shown(d.grand_total[mi], mi, d.grand_total[mi]);

  // Heatmap scale: per value and per level, so a subtotal is compared with other subtotals, not with detail rows.
  const heatMax = useMemo(() => {
    if (!d || !heat) return {};
    const out = {};
    d.rows.forEach((r) => {
      const cells = hasCols ? r.cells : r.totals;
      cells.forEach((v, i) => {
        const mi = i % nm;
        if (typeof v !== 'number') return;
        let n = v;
        if (mode !== 'values' && d.measures[mi].additive) {
          const parent = rowByPath.get(pathKey(r.path.slice(0, -1)));
          const base = mode === 'row' ? r.totals[mi] : mode === 'column' ? d.column_totals[i] : mode === 'parent' ? (parent ? parent.cells[i] : d.column_totals[i]) : d.grand_total[mi];
          n = ratio(v, base) ?? 0;
        }
        const key = `${r.level}|${mi}`;
        out[key] = Math.max(out[key] || 0, Math.abs(n));
      });
    });
    return out;
  }, [d, heat, mode, nm, hasCols, rowByPath]);
  const shade = (cellInfo, mi, level) => {
    const top = heatMax[`${level}|${mi}`];
    return heat && cellInfo && top > 0 ? { '--heat': `${Math.round((Math.abs(cellInfo.n) / top) * 100)}%` } : undefined;
  };

  const labelOf = (row) => {
    const i = row.path.length - 1;
    const text = row.path[i];
    return d.row_fields[i]?.is_date && text !== '(empty)' ? formatPeriod(text) : text;
  };
  const colLabel = (c) => (d.column_field?.is_date && c !== '(empty)' ? formatPeriod(c) : c);

  const first = Math.max(0, Math.floor(scroll / ROW_H) - OVERSCAN);
  const last = Math.min(visible.length, Math.ceil((scroll + VIEW_H) / ROW_H) + OVERSCAN);
  const slice = visible.slice(first, last);
  const colsN = hasCols ? d.columns.length * nm + (totals.rows ? nm : 0) : nm;

  const toggle = (row) => setCollapsed((cur) => {
    const next = new Set(cur);
    const k = pathKey(row.path);
    if (next.has(k)) next.delete(k); else next.add(k);
    return next;
  });
  const nested = d && d.row_fields.length > 1;

  const exportCsv = () => {
    const head = [...d.row_fields.map((f) => f.label), '',
      ...(hasCols ? d.columns.flatMap((c) => d.measures.map((m) => (nm > 1 ? `${c} | ${m.label}` : c))) : []),
      ...d.measures.map((m) => (hasCols ? (nm > 1 ? `Total | ${m.label}` : 'Total') : m.label))];
    const raw = (v) => (v === null || v === undefined ? '' : v);
    const pad = d.row_fields.length;
    const lines = [head.map(csvCell).join(',')];
    d.rows.forEach((r) => {
      lines.push([...r.path, ...Array(pad - r.path.length).fill(''), r.subtotal ? 'Total' : '', ...(hasCols ? r.cells.map(raw) : []), ...r.totals.map(raw)].map(csvCell).join(','));
    });
    lines.push(['Grand total', ...Array(pad).fill(''), ...(hasCols ? d.column_totals.map(raw) : []), ...d.grand_total.map(raw)].map(csvCell).join(','));
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'pivot.csv';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const exportExcel = async () => {
    setBusy(true);
    try {
      const res = await api.post(`/analytics/${datasetId}/pivot/export`, body, { responseType: 'blob', timeout: 0 });
      saveBlob(res, 'pivot.xlsx');
      toast.success(`Excel file downloaded (${formatInteger(Number(res.headers['x-rows-exported']))} rows)`);
    } catch (err) {
      toast.error(await blobError(err));
    } finally {
      setBusy(false);
    }
  };

  const dims = meta.data?.dimensions || [];
  const rowOptions = (i) => groupable.filter((c) => c.key === spec.rows[i] || (!spec.rows.includes(c.key) && c.key !== spec.columns)).map((c) => ({ value: c.key, label: c.display_name }));
  const colOptions = [{ value: '', label: 'None' }, ...groupable.filter((c) => !spec?.rows.includes(c.key)).map((c) => ({ value: c.key, label: c.display_name }))];
  const valueOptions = [{ value: '', label: 'Number of rows' }, ...measureCols.map((c) => ({ value: c.key, label: c.display_name })),
    ...groupable.filter((c) => !NUMERIC.includes(c.dtype)).map((c) => ({ value: c.key, label: `${c.display_name} (text)` }))];
  const aggOptions = (key) => AGGS.filter((a) => !a.numeric || NUMERIC.includes(schema.find((c) => c.key === key)?.dtype));

  return (
    <div className="stack">
      <PageHeader module="pivot" title="Pivot"
        description="Summarise any measure by one to three fields and a column field, like an Excel PivotTable. It covers every row of the file, and every number is calculated and double-checked."
        actions={<DatasetPicker value={datasetId} onChange={setDataset} />} />
      {!datasetId ? (
        <Card><EmptyState icon={Database} title="No cleaned datasets yet" message="Upload a dataset to build a pivot." action={<Link to="/app/upload" className="btn btn-primary">Upload file</Link>} /></Card>
      ) : !spec ? <Skeleton height={320} /> : (
        <>
          <Card pad>
            <div className="pv-setup">
              <section aria-label="Rows">
                <h3 className="pv-h">Rows</h3>
                {spec.rows.map((r, i) => (
                  <div key={i} className="pv-line">
                    <Select aria-label={`Row field ${i + 1}`} value={r} onChange={(e) => setRow(i, e.target.value)} options={rowOptions(i)} />
                    {spec.rows.length > 1 && <Button variant="ghost" size="sm" icon={X} aria-label={`Remove row field ${i + 1}`} onClick={() => setSpec((s) => ({ ...s, rows: s.rows.filter((_, j) => j !== i) }))} />}
                  </div>
                ))}
                {spec.rows.length < 3 && (
                  <Button variant="ghost" size="sm" icon={Plus} onClick={() => setSpec((s) => ({ ...s, rows: [...s.rows, groupable.find((c) => !s.rows.includes(c.key) && c.key !== s.columns)?.key].filter(Boolean) }))}>Add row field</Button>
                )}
              </section>
              <section aria-label="Columns">
                <h3 className="pv-h">Columns</h3>
                <Select aria-label="Column field" value={spec.columns} onChange={(e) => patch({ columns: e.target.value })} options={colOptions} />
              </section>
              <section aria-label="Values">
                <h3 className="pv-h">Values</h3>
                {spec.measures.map((m, i) => (
                  <div key={i} className="pv-line">
                    <Select aria-label={`Value ${i + 1} column`} value={m.column} onChange={(e) => setMeasure(i, { column: e.target.value })} options={valueOptions} />
                    {m.column && <Select aria-label={`Value ${i + 1} summarised by`} value={m.aggregation} onChange={(e) => setMeasure(i, { aggregation: e.target.value })} options={aggOptions(m.column)} />}
                    {spec.measures.length > 1 && <Button variant="ghost" size="sm" icon={X} aria-label={`Remove value ${i + 1}`} onClick={() => setSpec((s) => ({ ...s, measures: s.measures.filter((_, j) => j !== i), sortMeasure: 0 }))} />}
                  </div>
                ))}
                {spec.measures.length < 6 && (
                  <Button variant="ghost" size="sm" icon={Plus} onClick={() => setSpec((s) => ({ ...s, measures: [...s.measures, { column: measureCols.find((c) => !s.measures.some((m) => m.column === c.key))?.key || '', aggregation: 'sum' }] }))}>Add value</Button>
                )}
              </section>
              <section aria-label="Sort and limit">
                <h3 className="pv-h">Arrange</h3>
                <div className="pv-line pv-line-wrap">
                  <Select aria-label="Sort rows by" value={spec.sortBy} onChange={(e) => patch({ sortBy: e.target.value })}
                    options={[{ value: 'auto', label: 'Sort: automatic' }, { value: 'label', label: 'Sort: by name' }, { value: 'value', label: 'Sort: by value' }]} />
                  <Select aria-label="Sort direction" value={spec.sortDir} onChange={(e) => patch({ sortDir: e.target.value })}
                    options={[{ value: '', label: 'Default' }, { value: 'asc', label: 'A→Z / low→high' }, { value: 'desc', label: 'Z→A / high→low' }]} />
                </div>
                {spec.measures.length > 1 && (
                  <Select aria-label="Value used for sorting and Top N" value={String(spec.sortMeasure)} onChange={(e) => patch({ sortMeasure: Number(e.target.value) })}
                    options={spec.measures.map((m, i) => ({ value: String(i), label: `Rank by: ${d?.measures[i]?.label || (m.column ? schema.find((c) => c.key === m.column)?.display_name : 'Number of rows')}` }))} />
                )}
                <div className="pv-line pv-line-wrap">
                  <Input aria-label="Top N first-level rows" type="number" min="1" placeholder="Top N rows (all)" value={spec.topN} onChange={(e) => patch({ topN: e.target.value })} />
                  {spec.columns && (
                    <Select aria-label="Sort columns by" value={spec.colSort} onChange={(e) => patch({ colSort: e.target.value })}
                      options={[{ value: 'label', label: 'Columns: by name' }, { value: 'value', label: 'Columns: by value' }]} />
                  )}
                  {hasDate && <Select aria-label="Group dates by" value={spec.grain} onChange={(e) => patch({ grain: e.target.value })} options={GRAINS} />}
                </div>
              </section>
            </div>
            {dims.length > 0 && (
              <div className="row-wrap" style={{ marginTop: 12 }}>
                <span className="xs muted">Filters</span>
                {dims.map((x) => <MultiSelect key={x.key} label={x.label} options={x.values} value={filters[x.key] || []} onChange={(vals) => setFilters((f) => ({ ...f, [x.key]: vals }))} />)}
              </div>
            )}
          </Card>

          {state.error && <Alert tone="danger">{state.error}</Alert>}
          {!d && state.loading && <Card pad><Skeleton height={300} /></Card>}
          {d?.empty && <Card><EmptyState icon={Database} title="No rows match these filters" message="Clear a filter to see the pivot." /></Card>}
          {d && !d.empty && (
            <Card className="pv-card" style={{ opacity: state.loading ? 0.6 : 1 }} aria-busy={state.loading}>
              <div className="pv-bar">
                <div style={{ minWidth: 0 }}>
                  <h2 className="pv-title">{d.measures.map((m) => m.label).join(', ')} by {d.row_fields.map((f) => f.label).join(' › ')}{hasCols ? ` and ${d.column_field.label}` : ''}</h2>
                  <p className="xs muted">
                    {formatInteger(d.rows_used)} of {formatInteger(d.how_calculated.rows_total)} rows · {formatInteger(d.rows_total_count)} {d.row_fields[d.row_fields.length - 1].label.toLowerCase()} {d.rows_total_count === 1 ? 'group' : 'groups'}
                    {d.top_n && d.rows_total_count > d.rows_shown_count && ` · top ${formatInteger(d.top_n)} of ${formatInteger(d.rows_total_count)} first-level rows listed (totals include all)`}
                    {d.filters.length > 0 && ` · ${d.filters.join('; ')}`}
                    {grain && ` · dates by ${grain}`}
                  </p>
                </div>
                <div className="row-wrap">
                  <Segmented label="Show values as" value={mode} onChange={setShow} options={showOptions} />
                  <Switch label="Heatmap" checked={heat} onChange={setHeat} />
                  {nested && (
                    <>
                      <Button variant="ghost" size="sm" onClick={() => setCollapsed(new Set(subtotalKeys))}>Collapse all</Button>
                      <Button variant="ghost" size="sm" onClick={() => setCollapsed(new Set())}>Expand all</Button>
                    </>
                  )}
                  <Button variant="secondary" size="sm" icon={Download} onClick={exportCsv}>CSV</Button>
                  <Button variant="secondary" size="sm" icon={FileSpreadsheet} loading={busy} onClick={exportExcel}>Excel</Button>
                  <CalcDrawer details={d.how_calculated} datasetId={datasetId} iconOnly label="How this pivot was calculated" />
                </div>
              </div>
              {mode !== 'values' && d.measures.some((m) => !m.additive) && (
                <p className="xs muted" style={{ padding: '0 20px 8px' }}>Percentages are shown for sums and counts. Averages, medians, minimums, maximums and distinct counts stay as values.</p>
              )}
              <div className="pv-wrap" style={{ maxHeight: VIEW_H }} onScroll={(e) => setScroll(e.currentTarget.scrollTop)}>
                <table className="pv-table">
                  <caption className="sr-only">{d.measures.map((m) => m.label).join(', ')} by {d.row_fields.map((f) => f.label).join(', ')}</caption>
                  <thead>
                    <tr>
                      <th scope="col" className="pv-corner" rowSpan={hasCols && nm > 1 ? 2 : 1}>{d.row_fields.map((f) => f.label).join(' › ')}{hasCols && <span className="xs muted"> / {d.column_field.label}</span>}</th>
                      {hasCols ? d.columns.map((c, ci) => <th key={c} scope="colgroup" colSpan={nm} className="num">{colLabel(c)}{d.columns_partial[ci] && <span className="xs muted"> (partial)</span>}</th>)
                        : d.measures.map((m) => <th key={m.label} scope="col" className="num">{m.label}</th>)}
                      {hasCols && totals.rows && <th scope="colgroup" colSpan={nm} className="num pv-total">Total</th>}
                    </tr>
                    {hasCols && nm > 1 && (
                      <tr>
                        {[...d.columns, ...(totals.rows ? ['Total'] : [])].flatMap((c) => d.measures.map((m) => <th key={`${c}|${m.label}`} scope="col" className="num pv-sub">{m.label}</th>))}
                      </tr>
                    )}
                  </thead>
                  <tbody>
                    {first > 0 && <tr aria-hidden="true" style={{ height: first * ROW_H }}><td colSpan={colsN + 1} /></tr>}
                    {slice.map((r) => {
                      const open = r.subtotal && !collapsed.has(pathKey(r.path));
                      return (
                        <tr key={pathKey(r.path)} className={r.subtotal ? 'pv-sub-row' : undefined} style={{ height: ROW_H }}>
                          <th scope="row" style={{ paddingLeft: 14 + r.level * 18 }}>
                            {r.subtotal ? (
                              <button type="button" className="pv-toggle" aria-expanded={open} onClick={() => toggle(r)} aria-label={`${open ? 'Collapse' : 'Expand'} ${labelOf(r)}`}>
                                {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}{labelOf(r)}
                              </button>
                            ) : <>{labelOf(r)}</>}
                            {r.partial && <span className="xs muted"> (partial)</span>}
                          </th>
                          {hasCols ? d.columns.flatMap((c, ci) => d.measures.map((m, mi) => {
                            const x = cell(r, ci, mi);
                            return <td key={`${c}|${mi}`} className="num pv-cell" style={shade(x, mi, r.level)}>{x ? x.text : ''}</td>;
                          })) : d.measures.map((m, mi) => {
                            const x = totalCell(r, mi);
                            return <td key={mi} className="num pv-cell" style={shade(x, mi, r.level)}>{x ? x.text : ''}</td>;
                          })}
                          {hasCols && totals.rows && d.measures.map((m, mi) => <td key={`t${mi}`} className="num pv-total">{totalCell(r, mi)?.text ?? ''}</td>)}
                        </tr>
                      );
                    })}
                    {last < visible.length && <tr aria-hidden="true" style={{ height: (visible.length - last) * ROW_H }}><td colSpan={colsN + 1} /></tr>}
                  </tbody>
                  {totals.columns && (
                    <tfoot>
                      <tr>
                        <th scope="row">Grand total</th>
                        {hasCols ? d.columns.flatMap((c, ci) => d.measures.map((m, mi) => <td key={`${c}|${mi}`} className="num">{colTotalCell(ci, mi)?.text ?? ''}</td>))
                          : d.measures.map((m, mi) => <td key={mi} className="num">{grandCell(mi)?.text ?? ''}</td>)}
                        {hasCols && totals.rows && d.measures.map((m, mi) => <td key={`g${mi}`} className="num pv-total">{grandCell(mi)?.text ?? ''}</td>)}
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
              <div className="pv-foot xs muted">
                <span className="row" style={{ gap: 6 }}>
                  <ShieldCheck size={13} aria-hidden="true" /> {d.verification.passed} of {d.verification.checks} checks passed (calculated with Pandas, each group re-checked with DuckDB). Subtotals and totals come from the rows, not from adding the cells shown.
                </span>
                <span className="row" style={{ gap: 12 }}>
                  <Switch label="Total column" checked={totals.rows} onChange={(v) => setTotals((t) => ({ ...t, rows: v }))} />
                  <Switch label="Grand total row" checked={totals.columns} onChange={(v) => setTotals((t) => ({ ...t, columns: v }))} />
                </span>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Copy, Database, Info, XCircle } from 'lucide-react';
import { Badge, Button, Drawer, useToast } from './ui/index.js';
import { formatInteger } from '../utils/format.js';

/** "How this was calculated": formula, filters, version, rows used/skipped, engines, checks, SQL. */
export default function CalcDrawer({ details, datasetId, label = 'How this was calculated', size = 'sm', iconOnly = false }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const toast = useToast();
  if (!details) return null;
  const sql = details.equivalent_sql;
  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success('Copied');
    } catch {
      toast.error('Copy failed. Select the text and copy it manually.');
    }
  };
  return (
    <>
      {iconOnly
        ? <Button variant="ghost" size={size} icon={Info} onClick={() => setOpen(true)} aria-label={label} title={label} />
        : <Button variant="ghost" size={size} icon={Info} onClick={() => setOpen(true)}>{label}</Button>}
      <Drawer open={open} onClose={() => setOpen(false)} title="How this was calculated">
        <dl className="stack-sm" style={{ margin: 0 }}>
          {details.formula && (<><dt className="xs muted">Formula</dt><dd style={{ margin: 0 }}>{details.formula}</dd></>)}
          <dt className="xs muted">Filters</dt>
          <dd style={{ margin: 0 }}>{(details.filters_applied || ['None']).join(' · ')}</dd>
          <dt className="xs muted">Dataset version</dt>
          <dd style={{ margin: 0 }}>Version {details.dataset_version ?? '—'}</dd>
          <dt className="xs muted">Rows</dt>
          <dd style={{ margin: 0 }} className="num">
            {formatInteger(details.rows_in)} in · {formatInteger(details.rows_used)} used · {formatInteger(details.rows_skipped)} skipped
            {details.rows_total !== undefined && details.rows_total !== details.rows_in && <> · {formatInteger(details.rows_total)} before filters</>}
          </dd>
          {details.null_policy && (<><dt className="xs muted">Empty values</dt><dd style={{ margin: 0 }} className="small">{details.null_policy}</dd></>)}
          <dt className="xs muted">Engines</dt>
          <dd style={{ margin: 0 }} className="row-wrap">
            <Badge tone="primary">{details.engine}</Badge>
            {details.verified_by && <Badge tone="success">verified by {details.verified_by}</Badge>}
          </dd>
        </dl>
        {details.warnings?.length > 0 && (
          <div className="stack-sm">
            <h3 style={{ fontSize: 'var(--fs-md)' }}>Notes</h3>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{details.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          </div>
        )}
        {details.checks?.length > 0 && (
          <div className="stack-sm">
            <h3 style={{ fontSize: 'var(--fs-md)' }}>Checks</h3>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }} className="stack-sm">
              {details.checks.map((c, i) => (
                <li key={i} className="row small" style={{ alignItems: 'flex-start' }}>
                  {c.passed ? <CheckCircle2 size={15} color="var(--success)" aria-label="Passed" /> : <XCircle size={15} color="var(--danger)" aria-label="Failed" />}
                  <span className="grow">{c.name}<br /><span className="xs muted">{c.detail}</span></span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {sql && (
          <div className="stack-sm">
            <h3 style={{ fontSize: 'var(--fs-md)' }}>Equivalent SQL</h3>
            <pre>{sql}</pre>
            <div className="row-wrap">
              <Button variant="secondary" size="sm" icon={Copy} onClick={() => copy(sql)}>Copy SQL</Button>
              {datasetId && (
                <Button size="sm" icon={Database} onClick={() => navigate(`/app/sql?dataset=${datasetId}`, { state: { sql } })}>Verify in SQL</Button>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </>
  );
}

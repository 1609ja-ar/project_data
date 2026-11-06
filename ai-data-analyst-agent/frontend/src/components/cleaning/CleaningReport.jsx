import { AlertTriangle, Download, Info } from 'lucide-react';
import { Accordion, Badge, Button } from '../ui/index.js';
import { formatInteger } from '../../utils/format.js';

function downloadBlob(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const csvCell = (v) => {
  const s = v === null || v === undefined ? '' : String(v);
  const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
};

export function downloadReport(report, base, format) {
  if (format === 'json') {
    downloadBlob(`${base}_cleaning_report.json`, JSON.stringify(report, null, 2), 'application/json');
    return;
  }
  const head = ['step', 'column', 'rows_affected', 'severity', 'description', 'examples'];
  const lines = [head.join(',')].concat(
    report.steps.map((s) => [s.step, s.column, s.rows_affected, s.severity, s.description, (s.examples || []).join(' | ')].map(csvCell).join(',')),
  );
  downloadBlob(`${base}_cleaning_report.csv`, lines.join('\n'), 'text/csv');
}

function Stat({ label, value, sub }) {
  return (
    <div className="card" style={{ padding: 'var(--s-4)' }}>
      <p className="xs muted" style={{ fontWeight: 600 }}>{label}</p>
      <p style={{ fontSize: 'var(--fs-xl)', fontWeight: 700 }} className="num">{value}</p>
      {sub && <p className="xs muted">{sub}</p>}
    </div>
  );
}

export function ReportSummary({ summary }) {
  if (!summary) return null;
  return (
    <div className="grid-4">
      <Stat label="Rows" value={`${formatInteger(summary.rows_before)} → ${formatInteger(summary.rows_after)}`} sub={`${formatInteger(summary.rows_removed)} removed`} />
      <Stat label="Columns" value={`${formatInteger(summary.columns_before)} → ${formatInteger(summary.columns_after)}`} />
      <Stat label="Cells changed" value={formatInteger(summary.cells_changed)} sub={summary.nulls_before !== undefined ? `Empty cells ${formatInteger(summary.nulls_before)} → ${formatInteger(summary.nulls_after)}` : undefined} />
      <Stat label="Quality score" value={`${summary.quality_score_before ?? '—'} → ${summary.quality_score_after ?? '—'}`} sub="Out of 100 (see METRICS.md)" />
    </div>
  );
}

export function ReportSteps({ report }) {
  if (!report?.steps?.length) return <p className="small muted">No changes were needed.</p>;
  return (
    <div>
      {report.steps.map((s, i) => (
        <Accordion
          key={i}
          title={
            <span className="row" style={{ gap: 8 }}>
              {s.severity === 'warning' ? <AlertTriangle size={15} color="var(--warning)" aria-label="Warning" /> : <Info size={15} color="var(--info)" aria-label="Info" />}
              <span style={{ fontWeight: 600 }}>{s.description}</span>
            </span>
          }
          right={
            <span className="row" style={{ gap: 6 }}>
              {s.column && <Badge>{s.column}</Badge>}
              {s.rows_affected > 0 && <Badge tone="primary">{formatInteger(s.rows_affected)}</Badge>}
            </span>
          }
        >
          <div className="stack-sm">
            <p className="xs muted">Step <code>{s.step}</code>{s.column ? <> on <strong>{s.column}</strong></> : null} · {formatInteger(s.rows_affected)} affected</p>
            {s.examples?.length > 0 && <div className="row-wrap">{s.examples.map((e, j) => <Badge key={j}>{e}</Badge>)}</div>}
          </div>
        </Accordion>
      ))}
    </div>
  );
}

export function ReportDownloads({ report, base }) {
  return (
    <div className="row-wrap">
      <Button variant="secondary" size="sm" icon={Download} onClick={() => downloadReport(report, base, 'json')}>Report JSON</Button>
      <Button variant="secondary" size="sm" icon={Download} onClick={() => downloadReport(report, base, 'csv')}>Report CSV</Button>
    </div>
  );
}

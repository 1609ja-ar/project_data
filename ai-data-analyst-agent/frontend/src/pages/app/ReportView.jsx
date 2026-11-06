import { Fragment, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowDownRight, ArrowLeft, ArrowUpRight, Download, PenLine, Printer, ShieldCheck, Trash2 } from 'lucide-react';
import ResultChart from '../../components/ResultChart.jsx';
import DonutChart from '../../components/dashboard/DonutChart.jsx';
import { Badge, Button, Card, ConfirmDialog, DataTable, ErrorState, Skeleton, useToast } from '../../components/ui/index.js';
import useApi from '../../hooks/useApi.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatCell, formatDateTime, formatInteger, formatKpi, formatPercent, formatPeriod } from '../../utils/format.js';

const SEVERITY_TONE = { important: 'danger', notable: 'warning', info: 'info' };

/** Renders AI text with "[unverified]" markers highlighted, so readers see which numbers did not match. */
function Checked({ text }) {
  const parts = String(text || '').split(' [unverified]');
  return (
    <>
      {parts.map((p, i) => (
        <Fragment key={i}>
          {p}
          {i < parts.length - 1 && <mark className="unverified" title="This number did not match the verified results">unverified</mark>}
        </Fragment>
      ))}
    </>
  );
}

function toMarkdown(r) {
  const f = r.facts;
  const n = r.narrative;
  const lines = [`# ${r.title}`, '', `${f.dataset.name} · version ${f.dataset.version} · ${f.dataset.rows_in_view.toLocaleString('en-IN')} records`
    + (f.dataset.view_bounds?.min ? ` · ${f.dataset.view_bounds.min} to ${f.dataset.view_bounds.max}` : ''), ''];
  if (r.sections.includes('summary')) {
    lines.push('## Executive summary', '', n.executive_summary, '');
    if (n.key_findings?.length) lines.push('### Key findings', '', ...n.key_findings.map((x) => `- ${x}`), '');
  }
  if (r.sections.includes('kpis')) {
    lines.push('## Key figures', '', '| Measure | Value | Change |', '| --- | --- | --- |',
      ...f.kpis.map((k) => `| ${k.label} | ${formatCell(k.value, k.column)} | ${k.change ? `${formatPercent(k.change.pct)} (${k.change.period} vs ${k.change.previous_period})` : '—'} |`), '');
  }
  if (r.sections.includes('insights') && f.insights.length) {
    lines.push('## Insights', '', ...f.insights.map((i) => `- **${i.headline}** (${i.severity}). ${i.detail}`), '');
  }
  if (r.sections.includes('summary') && n.recommendations?.length) lines.push('## Recommendations', '', ...n.recommendations.map((x) => `1. ${x}`), '');
  if (r.sections.includes('quality')) {
    const q = f.quality;
    lines.push('## Data quality', '', `Quality score ${q.score_before ?? '—'} → ${q.score_after ?? '—'}; ${q.rows_removed ?? 0} rows removed; ${q.cells_changed ?? 0} values standardised.`, '');
  }
  lines.push('---', `Generated ${new Date(r.created_at).toISOString().slice(0, 16).replace('T', ' ')} UTC. Figures computed with Pandas and verified with DuckDB. `
    + (r.source === 'ai' ? `Narrative written by ${r.provider}; numbers checked against the results.` : 'Narrative written from templates.'));
  return lines.join('\n');
}

function KpiFigure({ k }) {
  const ch = k.change;
  const up = ch && ch.pct > 0;
  return (
    <div className="rk">
      <span className="xs muted">{k.label}</span>
      <span className="rk-value num">{formatKpi(k.value, k.column)}</span>
      {ch ? (
        <span className="xs" style={{ color: up ? 'var(--up)' : 'var(--down)' }}>
          {up ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />} {formatPercent(Math.abs(ch.pct))} <span className="muted">{formatPeriod(ch.period)} vs {formatPeriod(ch.previous_period)}</span>
        </span>
      ) : <span className="xs muted">—</span>}
    </div>
  );
}

export default function ReportView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { data: r, loading, error, reload } = useApi(`/reports/${id}`);
  const [confirm, setConfirm] = useState(false);
  usePageTitle(r?.title || 'Report');

  if (loading && !r) return <Card pad><Skeleton height={420} /></Card>;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  const f = r.facts;
  const n = r.narrative;
  const has = (s) => r.sections.includes(s);
  const dimOrder = (key) => f.charts.find((t) => t.dimension === key)?.chart.rows.map((row) => String(row[0]));

  const downloadMd = () => {
    const blob = new Blob([toMarkdown(r)], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${r.title.replace(/[^\w-]+/g, '_')}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };
  const remove = async () => {
    try {
      await api.delete(`/reports/${id}`);
      toast.success('Report deleted');
      navigate('/app/reports');
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  return (
    <div>
      <div className="report-toolbar no-print">
        <Link to="/app/reports" className="btn btn-ghost btn-sm"><ArrowLeft size={15} /> Reports</Link>
        <span className="grow" />
        <Button variant="secondary" size="sm" icon={Download} onClick={downloadMd}>Markdown</Button>
        <Button size="sm" icon={Printer} onClick={() => window.print()}>Print / Save as PDF</Button>
        <Button variant="ghost" size="sm" icon={Trash2} aria-label="Delete report" onClick={() => setConfirm(true)} />
      </div>

      <article className="report-doc">
        <header className="report-cover">
          <span className="report-kicker">Data report</span>
          <h1>{r.title}</h1>
          <p className="report-meta">
            {f.dataset.name} · version {f.dataset.version} · {formatInteger(f.dataset.rows_in_view)} records
            {f.dataset.view_bounds?.min && <> · {f.dataset.view_bounds.min} to {f.dataset.view_bounds.max}</>}
            {f.dataset.filters?.length > 0 && <> · {f.dataset.filters.join('; ')}</>}
          </p>
          <div className="report-badges">
            <Badge tone="success"><ShieldCheck size={12} /> Figures verified by two engines</Badge>
            {r.source === 'ai'
              ? <Badge tone="primary"><PenLine size={12} /> Written by {r.provider}{r.model ? ` (${r.model})` : ''}</Badge>
              : <Badge>Narrative from templates</Badge>}
            <span className="xs muted">Generated {formatDateTime(r.created_at)}</span>
          </div>
          {r.unverified?.length > 0 && (
            <p className="report-warn"><AlertTriangle size={14} /> {r.unverified.length} number{r.unverified.length === 1 ? '' : 's'} in the AI text did not match the results and {r.unverified.length === 1 ? 'is' : 'are'} marked “unverified”.</p>
          )}
        </header>

        {has('summary') && (
          <section className="report-section">
            <h2>Executive summary</h2>
            <p className="report-lead"><Checked text={n.executive_summary} /></p>
            {n.key_findings?.length > 0 && (
              <>
                <h3>Key findings</h3>
                <ol className="report-findings">{n.key_findings.map((x, i) => <li key={i}><Checked text={x} /></li>)}</ol>
              </>
            )}
          </section>
        )}

        {has('kpis') && f.kpis.length > 0 && (
          <section className="report-section">
            <h2>Key figures</h2>
            <div className="report-kpis">{f.kpis.map((k) => <KpiFigure key={k.id} k={k} />)}</div>
          </section>
        )}

        {has('charts') && f.charts.length > 0 && (
          <section className="report-section">
            <h2>Charts</h2>
            <div className="report-charts">
              {f.charts.map((t) => (
                <figure key={t.id} className={`report-figure ${t.kind === 'split' || t.kind === 'trend' ? 'wide' : ''}`}>
                  <figcaption><strong>{t.title}</strong><span className="xs muted"> · {t.subtitle}</span></figcaption>
                  {t.chart.spec.type === 'donut'
                    ? <DonutChart columns={t.chart.columns} rows={t.chart.rows} height={200} seriesOrder={dimOrder(t.dimension)} />
                    : <ResultChart spec={t.chart.spec} columns={t.chart.columns} rows={t.chart.rows} height={t.kind === 'split' ? 260 : 230} seriesOrder={dimOrder(t.chart.spec.series)} />}
                  {n.chart_notes?.[t.id] && <p className="small muted"><Checked text={n.chart_notes[t.id]} /></p>}
                </figure>
              ))}
            </div>
            {f.table && (
              <figure className="report-figure wide">
                <figcaption><strong>{f.table.title}</strong><span className="xs muted"> · {f.table.subtitle}</span></figcaption>
                <DataTable columns={f.table.chart.columns.map((c) => (c.semantic_type === 'percent' ? { ...c, decimals: 1 } : c))}
                  rows={f.table.chart.rows} pageSize={50} maxHeight={2000} caption={f.table.title} />
              </figure>
            )}
          </section>
        )}

        {has('insights') && (
          <section className="report-section">
            <h2>Insights</h2>
            {f.insights_note && <p className="xs muted">{f.insights_note}</p>}
            {f.insights.length === 0 ? <p className="small muted">No pattern passed the evidence thresholds.</p> : (
              <div className="report-insights">
                {f.insights.map((i) => (
                  <div key={i.id} className="report-insight" data-tone={SEVERITY_TONE[i.severity]}>
                    <div className="row" style={{ gap: 6 }}><Badge tone={SEVERITY_TONE[i.severity]}>{i.severity}</Badge><span className="xs muted">{i.type.replace(/_/g, ' ')}</span></div>
                    <p className="small" style={{ fontWeight: 600, marginTop: 4 }}>{i.headline}</p>
                    <p className="xs muted">{i.detail}</p>
                    {i.caveats.length > 0 && <p className="xs" style={{ marginTop: 4 }}>Caveat: {i.caveats.join(' ')}</p>}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {has('summary') && n.recommendations?.length > 0 && (
          <section className="report-section">
            <h2>Recommendations</h2>
            <ol className="report-recs">{n.recommendations.map((x, i) => <li key={i}><Checked text={x} /></li>)}</ol>
          </section>
        )}

        {has('quality') && (
          <section className="report-section">
            <h2>Data quality</h2>
            <div className="report-kpis">
              <div className="rk"><span className="xs muted">Quality score</span><span className="rk-value num">{f.quality.score_before ?? '—'} → {f.quality.score_after ?? '—'}</span><span className="xs muted">before → after cleaning</span></div>
              <div className="rk"><span className="xs muted">Rows</span><span className="rk-value num">{formatInteger(f.quality.rows_after)}</span><span className="xs muted">{formatInteger(f.quality.rows_removed)} removed of {formatInteger(f.quality.rows_before)}</span></div>
              <div className="rk"><span className="xs muted">Values standardised</span><span className="rk-value num">{formatInteger(f.quality.cells_changed)}</span><span className="xs muted">currency, dates, text</span></div>
            </div>
            {f.quality.steps.length > 0 && (
              <DataTable caption="Cleaning steps" pageSize={20} maxHeight={2000}
                columns={[{ key: 'step', label: 'Step', dtype: 'string' }, { key: 'column', label: 'Column', dtype: 'string' }, { key: 'rows', label: 'Rows affected', dtype: 'integer' }, { key: 'd', label: 'What changed', dtype: 'string' }]}
                rows={f.quality.steps.map((s) => [s.step, s.column || '—', s.rows_affected, s.description])} />
            )}
          </section>
        )}

        {has('columns') && (
          <section className="report-section">
            <h2>Column dictionary</h2>
            <DataTable caption="Columns" pageSize={100} maxHeight={3000}
              columns={[{ key: 'n', label: 'Column', dtype: 'string' }, { key: 't', label: 'Type', dtype: 'string' }, { key: 'm', label: 'Meaning', dtype: 'string' }, { key: 'e', label: 'Empty', dtype: 'integer' }, { key: 'd', label: 'Distinct', dtype: 'integer' }]}
              rows={f.columns.map((c) => [c.name, c.type, c.meaning, c.empty, c.distinct])} />
          </section>
        )}

        <footer className="report-foot">
          Method: every figure was computed with Pandas from the cleaned dataset and recomputed independently with DuckDB; both had to agree.
          {r.source === 'ai' ? ' The narrative was written by an AI model from those results only (no individual rows were sent); numbers it wrote were checked against the results.' : ' The narrative was written from fixed templates.'}
          {r.note && <> {r.note}</>}
        </footer>
      </article>
      <ConfirmDialog open={confirm} title="Delete report?" danger confirmLabel="Delete" message={`“${r.title}” will be deleted.`} onConfirm={remove} onCancel={() => setConfirm(false)} />
    </div>
  );
}

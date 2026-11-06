import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Lightbulb, X } from 'lucide-react';
import { Alert, Badge, Button, Card, EmptyState, Input, Select, useToast } from '../ui/index.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatInteger, formatNumber } from '../../utils/format.js';

const IMPACT_LABELS = { rows: 'Rows with values', total: 'Total', mean: 'Mean', rows_dropped: 'Rows dropped', rows_changed: 'Rows changed' };

function ImpactTable({ impact, options }) {
  const keys = Object.keys(impact || {});
  if (!keys.length) return null;
  const metrics = [...new Set(keys.flatMap((k) => Object.keys(impact[k])))];
  const label = (v) => options.find((o) => o.value === v)?.label || v;
  return (
    <div className="table-wrap">
      <table className="table" aria-label="Effect of each option">
        <thead><tr><th>Option</th>{metrics.map((m) => <th key={m} className="num">{IMPACT_LABELS[m] || m}</th>)}</tr></thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}><td>{label(k)}</td>{metrics.map((m) => <td key={m} className="num">{impact[k][m] === undefined || impact[k][m] === null ? '—' : formatNumber(impact[k][m], { maxDecimals: 4 })}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MappingEditor({ mapping, onChange, columns, roles }) {
  const entries = Object.entries(mapping || {});
  if (roles) {
    return (
      <div className="grid-2">
        {entries.map(([role, key]) => (
          <Select
            key={role}
            label={role.replace('_', ' ')}
            value={key}
            onChange={(e) => onChange({ ...mapping, [role]: e.target.value })}
            options={columns.map((c) => ({ value: c.key, label: c.display_name }))}
          />
        ))}
      </div>
    );
  }
  return (
    <div className="stack-sm">
      {entries.map(([from, to]) => (
        <div key={from} className="row">
          <Badge>{from}</Badge>
          <span aria-hidden="true">→</span>
          <div className="grow"><Input aria-label={`Replacement for ${from}`} value={to} onChange={(e) => onChange({ ...mapping, [from]: e.target.value })} /></div>
          <Button variant="ghost" size="sm" icon={X} aria-label={`Remove ${from} from mapping`} onClick={() => { const m = { ...mapping }; delete m[from]; onChange(m); }} />
        </div>
      ))}
    </div>
  );
}

function SuggestionCard({ s, choice, onChoice, columns }) {
  const opt = s.options.find((o) => o.value === choice.option);
  const selected = choice.option !== s.default;
  return (
    <Card pad style={{ borderColor: selected ? 'var(--primary)' : undefined }}>
      <div className="stack-sm">
        <div className="row between" style={{ alignItems: 'flex-start' }}>
          <div className="grow">
            <div className="row-wrap">
              <Badge tone={s.severity === 'warning' ? 'warning' : 'info'}>{s.type.replace(/_/g, ' ')}</Badge>
              <span style={{ fontWeight: 600 }}>{s.title}</span>
            </div>
            <p className="small muted" style={{ marginTop: 4 }}>{s.description}</p>
          </div>
          {selected && <Badge tone="primary"><CheckCircle2 size={12} /> Selected</Badge>}
        </div>
        <div style={{ maxWidth: 360 }}>
          <Select label="Action" value={choice.option} onChange={(e) => onChoice({ ...choice, option: e.target.value })} options={s.options.map((o) => ({ value: o.value, label: o.label }))} />
        </div>
        {opt?.needs === 'constant' && (
          <div style={{ maxWidth: 360 }}>
            <Input label="Value to fill with" value={choice.params?.constant ?? ''} onChange={(e) => onChoice({ ...choice, params: { ...choice.params, constant: e.target.value } })} />
          </div>
        )}
        {(s.type === 'near_duplicates' || s.type === 'column_roles') && (
          <MappingEditor mapping={choice.params?.mapping ?? s.params.mapping} roles={s.type === 'column_roles'} columns={columns}
            onChange={(m) => onChoice({ ...choice, params: { ...choice.params, mapping: m } })} />
        )}
        <ImpactTable impact={s.impact} options={s.options} />
        {s.preview && (
          <div className="table-wrap">
            <table className="table" aria-label="Preview of the result">
              <thead><tr>{s.preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{s.preview.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v ?? <span className="null">null</span>}</td>)}</tr>)}</tbody>
            </table>
          </div>
        )}
        {s.examples?.length > 0 && <div className="row-wrap"><span className="xs muted">Examples:</span>{s.examples.map((e) => <Badge key={e}>{e}</Badge>)}</div>}
      </div>
    </Card>
  );
}

export default function SuggestionsPanel({ datasetId, columns, onApplied }) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [choices, setChoices] = useState({});
  const [busy, setBusy] = useState(false);

  const load = () => api.get(`/datasets/${datasetId}/cleaning-suggestions`)
    .then(({ data: d }) => { setData(d); setChoices(Object.fromEntries(d.items.map((s) => [s.id, { option: s.default, params: {} }]))); })
    .catch((err) => setError(errorMessage(err)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [datasetId]);

  const selected = useMemo(() => (data?.items || []).filter((s) => choices[s.id] && choices[s.id].option !== s.default), [data, choices]);

  const apply = async () => {
    setBusy(true);
    try {
      const { data: res } = await api.post(`/datasets/${datasetId}/cleaning-suggestions/apply`, {
        selections: selected.map((s) => ({ id: s.id, option: choices[s.id].option, params: choices[s.id].params })),
      });
      toast.success(res.created_version ? `Created version ${res.created_version.version_number}` : 'Column roles saved');
      onApplied?.();
      load();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (error) return <Alert tone="danger">{error}</Alert>;
  if (!data) return <p className="small muted">Loading suggestions…</p>;
  if (!data.items.length) return <EmptyState icon={Lightbulb} title="No suggestions" message="Nothing needs a judgment call in this version." />;
  return (
    <div className="stack">
      <Alert tone="info" icon={Lightbulb}>
        These changes can affect results, so none are applied automatically. Applying creates version {data.version_number + 1}; earlier versions stay available.
      </Alert>
      {data.items.map((s) => (
        <SuggestionCard key={s.id} s={s} columns={columns} choice={choices[s.id] || { option: s.default }} onChoice={(c) => setChoices((x) => ({ ...x, [s.id]: c }))} />
      ))}
      <div className="row" style={{ position: 'sticky', bottom: 0, padding: '12px 0', background: 'var(--bg)' }}>
        <Button onClick={apply} loading={busy} disabled={!selected.length}>Apply selected ({formatInteger(selected.length)})</Button>
      </div>
    </div>
  );
}

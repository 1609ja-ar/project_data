import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Search } from 'lucide-react';

/** Filter button with a searchable checkbox list ("Region: All"). Calls onChange(values[]) on Apply. */
export default function MultiSelect({ label, options, value = [], onChange }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [draft, setDraft] = useState(value);
  const ref = useRef(null);

  useEffect(() => { if (open) { setDraft(value); setQ(''); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => !ref.current?.contains(e.target) && setOpen(false);
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open]);

  const shown = useMemo(() => options.filter((o) => o.toLowerCase().includes(q.toLowerCase())).slice(0, 100), [options, q]);
  const summary = value.length === 0 ? 'All' : value.length === 1 ? value[0] : `${value.length} selected`;
  const toggle = (o) => setDraft((d) => (d.includes(o) ? d.filter((x) => x !== o) : [...d, o]));

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button type="button" className="fbtn" data-active={value.length > 0} aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="k">{label}</span><span className="v">{summary}</span><ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label={`Filter ${label}`}>
          {options.length > 8 && (
            <div className="popover-search">
              <div className="input-wrap">
                <Search size={14} className="input-lead" aria-hidden="true" />
                <input className="input has-lead" style={{ minHeight: 30 }} placeholder={`Search ${label.toLowerCase()}`} value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
              </div>
            </div>
          )}
          <div className="popover-list" role="listbox" aria-multiselectable="true">
            {shown.map((o) => (
              <label key={o} className="option" role="option" aria-selected={draft.includes(o)}>
                <input type="checkbox" checked={draft.includes(o)} onChange={() => toggle(o)} />
                <span title={o}>{o}</span>
              </label>
            ))}
            {shown.length === 0 && <p className="xs muted" style={{ padding: 8 }}>No matches</p>}
          </div>
          <div className="popover-foot">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDraft([])} disabled={!draft.length}>Clear</button>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => { onChange(draft); setOpen(false); }}>Apply</button>
          </div>
        </div>
      )}
    </div>
  );
}

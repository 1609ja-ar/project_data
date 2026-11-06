import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Database, Search } from 'lucide-react';
import api from '../services/api.js';
import { useDebounced } from '../hooks/useApi.js';
import { formatInteger } from '../utils/format.js';

export default function DatasetSearch() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const debounced = useDebounced(q, 250);
  const ref = useRef(null);

  useEffect(() => {
    let cancelled = false;
    if (!debounced.trim()) {
      setItems([]);
      return undefined;
    }
    api.get('/datasets', { params: { q: debounced, page_size: 8 } })
      .then(({ data }) => { if (!cancelled) { setItems(data.items); setActive(0); } })
      .catch(() => { if (!cancelled) setItems([]); });
    return () => { cancelled = true; };
  }, [debounced]);

  useEffect(() => {
    const onDoc = (e) => !ref.current?.contains(e.target) && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const go = (d) => {
    setOpen(false);
    setQ('');
    navigate(`/app/datasets/${d.id}`);
  };

  return (
    <div className="search-box" ref={ref}>
      <div className="input-wrap">
        <Search size={16} className="input-lead" aria-hidden="true" />
        <input
          className="input has-lead"
          type="search"
          placeholder="Search datasets"
          aria-label="Search datasets"
          role="combobox"
          aria-expanded={open && items.length > 0}
          aria-controls="dataset-search-results"
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
            if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            if (e.key === 'Enter' && items[active]) go(items[active]);
            if (e.key === 'Escape') setOpen(false);
          }}
        />
      </div>
      {open && q.trim() && (
        <div className="menu" id="dataset-search-results" role="listbox" style={{ left: 0, right: 'auto', width: '100%' }}>
          {items.length === 0 ? (
            <p className="small muted" style={{ padding: '8px 12px' }}>No datasets match “{q}”.</p>
          ) : (
            items.map((d, i) => (
              <button key={d.id} type="button" role="option" aria-selected={i === active} className="menu-item" data-active={i === active} onMouseEnter={() => setActive(i)} onClick={() => go(d)}>
                <Database size={15} aria-hidden="true" />
                <span className="grow" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.filename}</span>
                <span className="xs muted num">{d.row_count != null ? `${formatInteger(d.row_count)} rows` : d.cleaning_status}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

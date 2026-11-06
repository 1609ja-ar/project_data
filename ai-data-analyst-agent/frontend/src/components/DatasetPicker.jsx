import { useEffect, useState } from 'react';
import api from '../services/api.js';
import { Select, Skeleton } from './ui/index.js';

/** Picks one of the user's cleaned datasets. Calls onChange(id) and auto-selects the newest when empty. */
export default function DatasetPicker({ value, onChange, label = 'Dataset', onlyReady = true }) {
  const [items, setItems] = useState(null);
  useEffect(() => {
    api.get('/datasets', { params: { page_size: 100 } })
      .then(({ data }) => setItems(onlyReady ? data.items.filter((d) => d.active_version_id) : data.items))
      .catch(() => setItems([]));
  }, [onlyReady]);
  useEffect(() => {
    if (items && items.length && !value) onChange(items[0].id);
  }, [items, value, onChange]);
  if (!items) return <Skeleton height={40} width={260} />;
  if (!items.length) return null;
  return (
    <div style={{ minWidth: 240, maxWidth: 360 }}>
      <Select label={label} value={value || ''} onChange={(e) => onChange(e.target.value)} options={items.map((d) => ({ value: d.id, label: d.filename }))} />
    </div>
  );
}

import { useState } from 'react';
import { Link2, RefreshCw } from 'lucide-react';
import { Button, useToast } from './ui/index.js';
import api from '../services/api.js';
import { errorMessage } from '../services/errors.js';
import { formatRelative } from '../utils/format.js';

/** "Linked to Google Sheets · checked 5 min ago · Refresh" for datasets imported from a link. */
export default function SourceLink({ dataset, onRefreshed, disabled }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const src = dataset.source;
  if (!src?.url) return null;
  let where = 'a link';
  try { where = src.kind === 'google_sheets' ? 'Google Sheets' : new URL(src.url).hostname.replace(/^www\./, ''); } catch { /* keep generic */ }

  const refresh = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/datasets/${dataset.id}/refresh`, null, { timeout: 0 });
      if (data.changed) toast.success('New data found. Cleaning it into a new version…');
      else toast.info('No changes since the last import.');
      onRefreshed?.(data);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="source-link">
      <Link2 size={13} aria-hidden="true" />
      <span>Linked to <a href={src.url} target="_blank" rel="noreferrer noopener">{where}</a>{src.fetched_at && <> · checked {formatRelative(src.fetched_at)}</>}</span>
      <Button variant="ghost" size="sm" icon={RefreshCw} loading={busy} disabled={disabled} onClick={refresh} title="Download the latest data from the link">Refresh</Button>
    </span>
  );
}

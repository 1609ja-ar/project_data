import { useState } from 'react';
import { Copy, ExternalLink, Link2, Trash2 } from 'lucide-react';
import { Badge, Button, Input, Modal, Select, useToast } from '../ui/index.js';
import useApi from '../../hooks/useApi.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';
import { formatRelative } from '../../utils/format.js';
import Lazy3D from '../../three/Lazy3D.jsx';
import { ShareFlip3D } from '../../three/moments/index.js';

/** Creates read-only snapshot links of the current dashboard view and lists / revokes existing ones. */
/** preview: { kpis: [{ label, text }], bars: [numbers] } for the card that flips over when a link is created. */
export default function ShareDialog({ open, onClose, datasetId, view, defaultTitle, preview }) {
  const toast = useToast();
  const links = useApi(open ? `/analytics/${datasetId}/share` : null);
  const [title, setTitle] = useState('');
  const [days, setDays] = useState('7');
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState(null);
  const url = (path) => `${window.location.origin}${path}`;

  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text); toast.success('Link copied'); } catch { toast.error('Copy failed'); }
  };
  const create = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/analytics/${datasetId}/share`, { ...view, title: title || defaultTitle, expires_in_days: Number(days) });
      setCreated(data);
      copy(url(data.path));
      links.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (id) => {
    try {
      await api.delete(`/share-links/${id}`);
      links.reload();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  return (
    <Modal open={open} onClose={() => { setCreated(null); onClose(); }} title="Share dashboard" width={560}>
      <div className="stack">
        <p className="small muted">Anyone with the link sees a read-only snapshot of this view (figures and charts, no rows). Revoke it at any time.</p>
        <div className="grid-2">
          <Input label="Title" placeholder={defaultTitle} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
          <Select label="Expires after" value={days} onChange={(e) => setDays(e.target.value)} options={['1', '7', '14', '30'].map((d) => ({ value: d, label: `${d} day${d === '1' ? '' : 's'}` }))} />
        </div>
        {created && preview && (
          <Lazy3D scene={ShareFlip3D} height={260} label="Shared dashboard card flipping to show the link is ready"
            sceneProps={{ title: created.title || title || defaultTitle, kpis: preview.kpis, bars: preview.bars, link: url(created.path).replace(/^https?:\/\//, '') }}
            fallback={null} />
        )}
        {created ? (
          <div className="share-created">
            <Link2 size={16} aria-hidden="true" />
            <code className="token-box grow">{url(created.path)}</code>
            <Button variant="secondary" size="sm" icon={Copy} onClick={() => copy(url(created.path))}>Copy</Button>
            <a className="btn btn-ghost btn-sm" href={created.path} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open</a>
          </div>
        ) : (
          <div><Button icon={Link2} onClick={create} loading={busy}>Create link</Button></div>
        )}
        {links.data?.items?.length > 0 && (
          <div>
            <span className="label">Links for this dataset</span>
            <ul className="share-list">
              {links.data.items.map((l) => (
                <li key={l.id}>
                  <span className="grow" style={{ minWidth: 0 }}>
                    <span className="small" style={{ fontWeight: 550 }}>{l.title}</span>
                    <span className="xs muted"> · {l.views} view{l.views === 1 ? '' : 's'} · created {formatRelative(l.created_at)}{l.filters.length ? ` · ${l.filters.join('; ')}` : ''}</span>
                  </span>
                  <Badge tone={l.status === 'active' ? 'success' : 'neutral'}>{l.status}</Badge>
                  {l.status === 'active' && <Button variant="ghost" size="sm" icon={Trash2} aria-label={`Revoke ${l.title}`} onClick={() => revoke(l.id)} />}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Modal>
  );
}

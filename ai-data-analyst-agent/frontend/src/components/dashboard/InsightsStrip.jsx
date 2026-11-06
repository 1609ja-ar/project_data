import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Lightbulb } from 'lucide-react';
import { Button, useToast } from '../ui/index.js';
import api from '../../services/api.js';
import { errorMessage } from '../../services/errors.js';

const TONE = { important: 'danger', notable: 'warning', info: 'info' };

/** The top findings for this dataset (from the cached insights run), shown above the charts. */
export default function InsightsStrip({ datasetId }) {
  const toast = useToast();
  const [items, setItems] = useState(undefined);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    setItems(undefined);
    api.get(`/analytics/${datasetId}/insights`)
      .then(({ data }) => live && setItems(data.insights))
      .catch(() => live && setItems(null));
    return () => { live = false; };
  }, [datasetId]);

  const generate = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/analytics/${datasetId}/insights`, {});
      setItems(data.insights);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (items === undefined) return null;
  if (!items) {
    return (
      <div className="istrip-empty">
        <Lightbulb size={16} aria-hidden="true" />
        <span className="grow small">Find trends, top contributors and outliers in this dataset.</span>
        <Button size="sm" variant="secondary" loading={busy} onClick={generate}>Find insights</Button>
      </div>
    );
  }
  if (!items.length) return null;
  return (
    <div className="istrip" aria-label="Top findings">
      {items.slice(0, 3).map((i) => (
        <Link key={i.id} to={`/app/insights?dataset=${datasetId}#${i.id}`} className="istrip-card" data-tone={TONE[i.severity]}>
          <span className="xs muted" style={{ textTransform: 'capitalize' }}>{i.severity} · {i.type.replace(/_/g, ' ')}</span>
          <span className="small" style={{ fontWeight: 550, color: 'var(--text)' }}>{i.headline}</span>
        </Link>
      ))}
      <Link to={`/app/insights?dataset=${datasetId}`} className="istrip-more small">All insights <ArrowRight size={14} aria-hidden="true" /></Link>
    </div>
  );
}

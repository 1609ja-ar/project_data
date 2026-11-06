import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Link2Off } from 'lucide-react';
import Logo from '../components/Logo.jsx';
import ThemeSwitcher from '../components/ThemeSwitcher.jsx';
import KpiCard from '../components/dashboard/KpiCard.jsx';
import Tile from '../components/dashboard/Tile.jsx';
import { Card, EmptyState, Skeleton } from '../components/ui/index.js';
import usePageTitle from '../hooks/usePageTitle.js';
import api from '../services/api.js';
import { errorMessage } from '../services/errors.js';
import { formatDateTime, formatInteger } from '../utils/format.js';

/** Public, read-only view of a shared dashboard snapshot. */
export default function SharedDashboard() {
  const { token } = useParams();
  const [state, setState] = useState({ data: null, error: null });
  usePageTitle(state.data?.title || 'Shared dashboard');

  useEffect(() => {
    api.get(`/public/share/${token}`)
      .then(({ data }) => setState({ data, error: null }))
      .catch((err) => setState({ data: null, error: errorMessage(err) }));
  }, [token]);

  const s = state.data?.snapshot;
  const orderFor = useMemo(() => (key) => s?.dimensions.find((d) => d.key === key)?.values, [s]);
  const tiles = [...(s?.tiles || []), ...(s?.custom_tiles || [])];

  return (
    <div className="shared">
      <header className="shared-top">
        <Logo to="/" />
        <span className="grow" />
        <ThemeSwitcher />
      </header>
      <main className="shared-main">
        {state.error ? (
          <Card><EmptyState icon={Link2Off} title="This link is not available" message={state.error} /></Card>
        ) : !s ? <Card pad><Skeleton height={320} /></Card> : (
          <>
            <div className="dash-head">
              <div>
                <h1>{state.data.title}</h1>
                <div className="dash-meta">
                  <span>{state.data.dataset_name}</span><span className="sep">|</span>
                  <span className="num">{formatInteger(s.rows_in_view)} records</span>
                  {s.view_bounds?.min && <><span className="sep">|</span><span className="num">{s.view_bounds.min} – {s.view_bounds.max}</span></>}
                  {state.data.filters.length > 0 && <><span className="sep">|</span><span>{state.data.filters.join('; ')}</span></>}
                </div>
              </div>
              <span className="xs muted">Snapshot of {formatDateTime(state.data.created_at)} · read-only</span>
            </div>
            <div className="dash-kpis">{s.kpis.map((k, i) => <KpiCard key={k.id} kpi={k} accent={[0, 6, 2, 1][i] ?? i} />)}</div>
            <div className="dash-grid">
              {tiles.map((t, i) => (
                <Tile key={`${t.id}-${i}`} tile={t} className={t.kind === 'trend' || t.kind === 'split' || t.kind === 'table' ? 'span-12' : 'span-6'}
                  seriesOrder={orderFor(t.series_dimension || t.dimension)} />
              ))}
            </div>
            <p className="xs muted" style={{ marginTop: 16 }}>Shared from Data Analyst · link expires {formatDateTime(state.data.expires_at)}</p>
          </>
        )}
      </main>
    </div>
  );
}

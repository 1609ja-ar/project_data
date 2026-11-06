import { memo } from 'react';
import { PanelRightOpen } from 'lucide-react';
import { Tooltip } from './ui/index.js';
import { formatPercent } from '../utils/format.js';

/** Column quality bar (valid / error / empty) and mini distribution. All shares come from the backend profile. */
function ProfilingStrip({ column, onOpen }) {
  const p = column.profile;
  if (!p) return null;
  const q = p.quality;
  const counts = p.dist?.counts || [];
  const max = Math.max(1, ...counts);
  const tip = `Valid ${formatPercent(q.valid)} · Error ${formatPercent(q.error)} · Empty ${formatPercent(q.empty)} · ${p.unique} unique`;
  return (
    <div style={{ minWidth: 110 }}>
      <Tooltip content={tip}>
        <div className="qbar" role="img" aria-label={tip} tabIndex={0}>
          <span className="v" style={{ width: `${q.valid * 100}%` }} />
          <span className="e" style={{ width: `${q.error * 100}%` }} />
          <span className="n" style={{ width: `${q.empty * 100}%` }} />
        </div>
      </Tooltip>
      <div className="row" style={{ gap: 4, alignItems: 'flex-end' }}>
        <div className="minidist grow" aria-hidden="true">
          {counts.slice(0, 12).map((c, i) => <span key={i} style={{ height: `${(c / max) * 100}%` }} />)}
        </div>
        {onOpen && (
          <button type="button" className="th-btn" onClick={() => onOpen(column)} aria-label={`Open profile of ${column.display_name}`} title="Column profile">
            <PanelRightOpen size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

export default memo(ProfilingStrip);

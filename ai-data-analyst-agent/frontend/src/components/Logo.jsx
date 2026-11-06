import { Link } from 'react-router-dom';

export default function Logo({ to = '/' }) {
  return (
    <Link to={to} className="logo" aria-label="AI Data Analyst home">
      <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
        <rect width="22" height="22" rx="5" fill="var(--text)" />
        <rect x="5" y="12" width="3" height="5" rx="0.5" fill="var(--bg-elev)" />
        <rect x="9.5" y="8" width="3" height="9" rx="0.5" fill="var(--bg-elev)" />
        <rect x="14" y="5" width="3" height="12" rx="0.5" fill="var(--bg-elev)" />
      </svg>
      <span>Data Analyst</span>
    </Link>
  );
}

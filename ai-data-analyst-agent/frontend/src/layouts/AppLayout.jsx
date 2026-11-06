import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { LogOut, Menu, Settings as SettingsIcon, X } from 'lucide-react';
import Logo from '../components/Logo.jsx';
import ThemeSwitcher from '../components/ThemeSwitcher.jsx';
import AskBar from '../components/AskBar.jsx';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
import { Button } from '../components/ui/index.js';
import { useAuth } from '../context/AuthContext.jsx';
import { NAV } from './nav.js';

function initials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join('') || '?';
}

function ProfileMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => !ref.current?.contains(e.target) && setOpen(false);
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open]);
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button type="button" className="profile-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="avatar" aria-hidden="true">{initials(user?.full_name)}</span>
        <span className="small hide-mobile" style={{ fontWeight: 600 }}>{user?.full_name}</span>
      </button>
      {open && (
        <div className="menu" role="menu">
          <div style={{ padding: '8px 12px' }}>
            <p style={{ fontWeight: 600 }}>{user?.full_name}</p>
            <p className="xs muted">{user?.email}</p>
          </div>
          <button type="button" role="menuitem" className="menu-item" onClick={() => { setOpen(false); navigate('/app/settings'); }}>
            <SettingsIcon size={16} aria-hidden="true" /> Settings
          </button>
          <button type="button" role="menuitem" className="menu-item" onClick={async () => { await logout(); navigate('/signin'); }}>
            <LogOut size={16} aria-hidden="true" /> Log out
          </button>
        </div>
      )}
    </div>
  );
}

export default function AppLayout() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [drawer, setDrawer] = useState(false);

  useEffect(() => setDrawer(false), [location.pathname]);

  return (
    <div className="shell">
      {drawer && <div className="sidebar-scrim" onClick={() => setDrawer(false)} aria-hidden="true" />}
      <aside className="sidebar" data-open={drawer} aria-label="Main navigation">
        <div className="row between">
          <Logo to="/app" />
          {drawer && <Button variant="ghost" icon={X} onClick={() => setDrawer(false)} aria-label="Close menu" />}
        </div>
        <nav className="stack-sm" style={{ gap: 1 }}>
          {NAV.map((item) =>
            item.section ? (
              <div key={item.section} className="nav-section">{item.section}</div>
            ) : (
              <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                style={{ '--mc': `var(--m-${item.module})` }}>
                <span className="nav-icon"><item.icon size={15} aria-hidden="true" /></span> {item.label}
              </NavLink>
            ),
          )}
        </nav>
        <div className="sidebar-foot stack-sm" style={{ gap: 1 }}>
          <NavLink to="/app/settings" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} style={{ '--mc': 'var(--m-settings)' }}>
            <span className="nav-icon"><SettingsIcon size={15} aria-hidden="true" /></span> Settings
          </NavLink>
          <button type="button" className="nav-link" style={{ '--mc': 'var(--m-settings)' }} onClick={async () => { await logout(); navigate('/signin'); }}>
            <span className="nav-icon"><LogOut size={15} aria-hidden="true" /></span> Log out
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <Button variant="ghost" icon={Menu} className="menu-btn" onClick={() => setDrawer(true)} aria-label="Open menu" />
          <AskBar />
          <div className="row" style={{ marginLeft: 'auto' }}>
            <span className="hide-mobile"><ThemeSwitcher /></span>
            <ProfileMenu />
          </div>
        </header>
        <main className="content" id="main">
          <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

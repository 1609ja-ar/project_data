import { motion } from 'framer-motion';
import Logo from '../components/Logo.jsx';
import ThemeSwitcher from '../components/ThemeSwitcher.jsx';

export default function AuthLayout({ title, subtitle, children, footer }) {
  return (
    <div className="auth-page">
      <header className="auth-top">
        <Logo />
        <ThemeSwitcher />
      </header>
      <main className="auth-main">
        <motion.div
          className="card auth-card"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.22, ease: 'easeOut' }}
        >
          <div className="stack-sm" style={{ marginBottom: 'var(--s-6)' }}>
            <h1>{title}</h1>
            {subtitle && <p className="muted">{subtitle}</p>}
          </div>
          {children}
        </motion.div>
        {footer && <p className="small muted" style={{ marginTop: 'var(--s-5)', textAlign: 'center' }}>{footer}</p>}
      </main>
    </div>
  );
}

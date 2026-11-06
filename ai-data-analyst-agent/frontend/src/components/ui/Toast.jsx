import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle2, Info, X, XCircle } from 'lucide-react';

const ToastContext = createContext(null);
const ICONS = { success: CheckCircle2, error: XCircle, info: Info };

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (kind, message, timeout = 4500) => {
      const id = ++idRef.current;
      setToasts((t) => [...t.slice(-3), { id, kind, message }]);
      if (timeout) setTimeout(() => dismiss(id), timeout);
      return id;
    },
    [dismiss],
  );
  const api = useMemo(
    () => ({
      success: (m) => push('success', m),
      error: (m) => push('error', m, 7000),
      info: (m) => push('info', m),
      dismiss,
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" aria-live="polite" aria-relevant="additions">
        <AnimatePresence initial={false}>
          {toasts.map((t) => {
            const Icon = ICONS[t.kind] || Info;
            return (
              <motion.div
                key={t.id}
                className="toast"
                data-kind={t.kind}
                role={t.kind === 'error' ? 'alert' : 'status'}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: 20 }}
                transition={{ duration: 0.18 }}
              >
                <Icon size={18} aria-hidden="true" style={{ flexShrink: 0, color: `var(--${t.kind === 'error' ? 'danger' : t.kind === 'success' ? 'success' : 'primary'})` }} />
                <span className="grow">{t.message}</span>
                <button type="button" className="btn btn-ghost btn-sm" style={{ minHeight: 24, padding: 2 }} onClick={() => dismiss(t.id)} aria-label="Dismiss notification">
                  <X size={14} />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside ToastProvider');
  return ctx;
}

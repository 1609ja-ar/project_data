import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import Button from './Button.jsx';

function useEscape(open, onClose) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && onClose?.();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);
}

function useFocusTrap(open, ref) {
  useEffect(() => {
    if (!open || !ref.current) return undefined;
    const prev = document.activeElement;
    const el = ref.current;
    const focusables = () => el.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    (focusables()[0] || el).focus();
    const onKey = (e) => {
      if (e.key !== 'Tab') return;
      const f = Array.from(focusables()).filter((n) => !n.disabled);
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    el.addEventListener('keydown', onKey);
    return () => { el.removeEventListener('keydown', onKey); prev?.focus?.(); };
  }, [open, ref]);
}

export function Modal({ open, onClose, title, children, footer, width }) {
  const ref = useRef(null);
  useEscape(open, onClose);
  useFocusTrap(open, ref);
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div className="overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
          <motion.div
            ref={ref}
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            style={width ? { width: `min(${width}px, 100%)` } : undefined}
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            <div className="modal-head">
              <h2 style={{ fontSize: 'var(--fs-lg)' }}>{title}</h2>
              <Button variant="ghost" icon={X} onClick={onClose} aria-label="Close" />
            </div>
            <div className="modal-body">{children}</div>
            {footer && <div className="modal-foot">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

export function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', danger = false, loading, onConfirm, onCancel, children }) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} loading={loading}>{confirmLabel}</Button>
        </>
      }
    >
      <div className="stack">
        {message && <p className="muted">{message}</p>}
        {children}
      </div>
    </Modal>
  );
}

export function Drawer({ open, onClose, title, children }) {
  const ref = useRef(null);
  useEscape(open, onClose);
  useFocusTrap(open, ref);
  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="drawer-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside
            ref={ref}
            className="drawer"
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            initial={{ x: 40, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 40, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
          >
            <div className="drawer-head">
              <h2 style={{ fontSize: 'var(--fs-lg)' }}>{title}</h2>
              <Button variant="ghost" icon={X} onClick={onClose} aria-label="Close" />
            </div>
            <div className="drawer-body">{children}</div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>,
    document.body,
  );
}

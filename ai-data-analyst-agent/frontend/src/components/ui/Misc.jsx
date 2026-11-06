import { useId, useState } from 'react';
import { AlertTriangle, ChevronDown, Inbox, RefreshCw } from 'lucide-react';
import Button from './Button.jsx';

export function Badge({ tone = 'neutral', children, ...rest }) {
  return <span className={`badge ${tone !== 'neutral' ? `badge-${tone}` : ''}`} {...rest}>{children}</span>;
}

export function Tooltip({ content, children }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!content) return children;
  return (
    <span
      className="tip"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      aria-describedby={open ? id : undefined}
    >
      {children}
      {open && <span role="tooltip" id={id} className="tip-bubble">{content}</span>}
    </span>
  );
}

export function Skeleton({ width = '100%', height = 14, radius, style, className = '' }) {
  return <span aria-hidden="true" className={`skeleton ${className}`} style={{ display: 'block', width, height, borderRadius: radius, ...style }} />;
}

export function ProgressBar({ value, label }) {
  const pct = Math.max(0, Math.min(100, value ?? 0));
  return (
    <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-label={label}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function EmptyState({ icon: Icon = Inbox, title, message, action, illustration }) {
  return (
    <div className="state">
      {illustration || <div className="state-icon"><Icon size={26} aria-hidden="true" /></div>}
      <h3>{title}</h3>
      {message && <p>{message}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ title = 'Something went wrong', message, onRetry }) {
  return (
    <div className="state error" role="alert">
      <div className="state-icon"><AlertTriangle size={26} aria-hidden="true" /></div>
      <h3>{title}</h3>
      {message && <p>{message}</p>}
      {onRetry && <Button variant="secondary" icon={RefreshCw} onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export function Alert({ tone = 'info', icon: Icon, children }) {
  return (
    <div className={`alert alert-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      {Icon && <Icon size={17} aria-hidden="true" style={{ flexShrink: 0, marginTop: 1 }} />}
      <div className="grow">{children}</div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange, label }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button
          key={t.value}
          role="tab"
          type="button"
          className="tab"
          aria-selected={value === t.value}
          tabIndex={value === t.value ? 0 : -1}
          onClick={() => onChange(t.value)}
          onKeyDown={(e) => {
            const i = tabs.findIndex((x) => x.value === value);
            if (e.key === 'ArrowRight') onChange(tabs[(i + 1) % tabs.length].value);
            if (e.key === 'ArrowLeft') onChange(tabs[(i - 1 + tabs.length) % tabs.length].value);
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Segmented({ options, value, onChange, label }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          title={o.label}
          aria-label={o.label}
        >
          {o.icon && <o.icon size={15} aria-hidden="true" />}
          {o.showLabel !== false && o.label}
        </button>
      ))}
    </div>
  );
}

export function Accordion({ title, right, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className="acc-item">
      <button type="button" className="acc-head" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <span className="grow">{title}</span>
        {right}
        <ChevronDown size={16} style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 150ms' }} aria-hidden="true" />
      </button>
      {open && <div className="acc-body" id={id}>{children}</div>}
    </div>
  );
}

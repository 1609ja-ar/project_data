export function Card({ className = '', pad = false, children, ...rest }) {
  return (
    <div className={['card', pad && 'card-pad', className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, actions, as: H = 'h2' }) {
  return (
    <div className="card-header">
      <div className="grow">
        <H style={{ fontSize: 'var(--fs-lg)' }}>{title}</H>
        {subtitle && <p className="small muted">{subtitle}</p>}
      </div>
      {actions && <div className="row-wrap">{actions}</div>}
    </div>
  );
}

export function CardBody({ children, className = '' }) {
  return <div className={`card-body ${className}`}>{children}</div>;
}

import { MODULES } from '../layouts/nav.js';

/** Page title with the area's colour and icon (module = key of MODULES), an optional one-liner and actions. */
export default function PageHeader({ title, description, actions, module }) {
  const m = module ? MODULES[module] : null;
  return (
    <div className="page-head" style={m ? { '--mc': `var(--m-${module})` } : undefined}>
      <div className="row" style={{ gap: 12, alignItems: 'center', minWidth: 0 }}>
        {m && <span className="page-icon" aria-hidden="true"><m.icon size={18} /></span>}
        <div style={{ minWidth: 0 }}>
          <h1>{title}</h1>
          {description && <p>{description}</p>}
        </div>
      </div>
      {actions && <div className="row-wrap">{actions}</div>}
    </div>
  );
}

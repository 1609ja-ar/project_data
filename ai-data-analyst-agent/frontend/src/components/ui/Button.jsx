import { forwardRef } from 'react';

const Button = forwardRef(function Button(
  { variant = 'primary', size, icon: Icon, loading = false, block = false, className = '', children, type = 'button', ...rest },
  ref,
) {
  const cls = ['btn', `btn-${variant}`, size && `btn-${size}`, block && 'btn-block', !children && Icon && 'btn-icon', className]
    .filter(Boolean)
    .join(' ');
  return (
    <button ref={ref} type={type} className={cls} disabled={loading || rest.disabled} aria-busy={loading || undefined} {...rest}>
      {loading ? <span className="spinner" aria-hidden="true" /> : Icon ? <Icon size={size === 'sm' ? 15 : 17} aria-hidden="true" /> : null}
      {children}
    </button>
  );
});

export default Button;

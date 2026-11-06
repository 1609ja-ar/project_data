import { forwardRef, useId, useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';

export const Field = ({ label, hint, error, id, children }) => (
  <div className="field">
    {label && <label htmlFor={id}>{label}</label>}
    {children}
    {error ? (
      <span className="err" id={`${id}-err`} role="alert">{error}</span>
    ) : hint ? (
      <span className="hint" id={`${id}-hint`}>{hint}</span>
    ) : null}
  </div>
);

export const Input = forwardRef(function Input({ label, hint, error, id, className = '', lead: Lead, ...rest }, ref) {
  const autoId = useId();
  const fid = id || autoId;
  return (
    <Field label={label} hint={hint} error={error} id={fid}>
      <div className="input-wrap">
        {Lead && <Lead size={16} className="input-lead" aria-hidden="true" />}
        <input
          ref={ref}
          id={fid}
          className={`input ${Lead ? 'has-lead' : ''} ${className}`}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${fid}-err` : hint ? `${fid}-hint` : undefined}
          {...rest}
        />
      </div>
    </Field>
  );
});

export const PasswordInput = forwardRef(function PasswordInput({ label, hint, error, id, ...rest }, ref) {
  const autoId = useId();
  const fid = id || autoId;
  const [show, setShow] = useState(false);
  return (
    <Field label={label} hint={hint} error={error} id={fid}>
      <div className="input-wrap">
        <input
          ref={ref}
          id={fid}
          type={show ? 'text' : 'password'}
          className="input"
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${fid}-err` : hint ? `${fid}-hint` : undefined}
          {...rest}
        />
        <button
          type="button"
          className="btn btn-ghost btn-icon input-icon-btn"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? 'Hide password' : 'Show password'}
          aria-pressed={show}
        >
          {show ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </div>
    </Field>
  );
});

export function Select({ label, hint, error, id, options = [], className = '', ...rest }) {
  const autoId = useId();
  const fid = id || autoId;
  return (
    <Field label={label} hint={hint} error={error} id={fid}>
      <select id={fid} className={`select ${className}`} aria-invalid={error ? 'true' : undefined} {...rest}>
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function Switch({ checked, onChange, label, id, disabled }) {
  const autoId = useId();
  const fid = id || autoId;
  return (
    <div className="row">
      <button
        id={fid}
        type="button"
        role="switch"
        className="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      />
      {label && <label htmlFor={fid} className="small">{label}</label>}
    </div>
  );
}

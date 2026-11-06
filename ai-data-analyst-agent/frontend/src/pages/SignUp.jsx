import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, User } from 'lucide-react';
import AuthLayout from '../layouts/AuthLayout.jsx';
import { Alert, Button, Input, PasswordInput } from '../components/ui/index.js';
import { useAuth } from '../context/AuthContext.jsx';
import { errorMessage, fieldErrors, getErrorInfo } from '../services/errors.js';
import { EMAIL_RE, passwordProblems, passwordStrength } from '../utils/password.js';
import usePageTitle from '../hooks/usePageTitle.js';

export default function SignUp() {
  usePageTitle('Create account');
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: '', email: '', password: '', confirm: '' });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [loading, setLoading] = useState(false);
  const strength = passwordStrength(form.password);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const validate = () => {
    const e = {};
    if (!form.full_name.trim()) e.full_name = 'Enter your name';
    if (!EMAIL_RE.test(form.email.trim())) e.email = 'Enter a valid email address';
    const probs = passwordProblems(form.password);
    if (probs.length) e.password = `Password needs ${probs.join(', ')}`;
    if (form.confirm !== form.password) e.confirm = 'Passwords do not match';
    return e;
  };

  const onSubmit = async (ev) => {
    ev.preventDefault();
    setFormError('');
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length) return;
    setLoading(true);
    try {
      await signup(form.full_name.trim(), form.email.trim(), form.password);
      navigate('/app', { replace: true });
    } catch (err) {
      const info = getErrorInfo(err);
      if (info.code === 'email_taken') setErrors({ email: info.message });
      else if (info.code === 'validation_error') setErrors(fieldErrors(err));
      else setFormError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Start analyzing your data in minutes."
      footer={<>Already have an account? <Link to="/signin">Sign in</Link></>}
    >
      <form className="stack" onSubmit={onSubmit} noValidate>
        {formError && <Alert tone="danger">{formError}</Alert>}
        <Input label="Full name" lead={User} value={form.full_name} onChange={set('full_name')} error={errors.full_name} autoComplete="name" required />
        <Input label="Email" type="email" lead={Mail} value={form.email} onChange={set('email')} error={errors.email} autoComplete="email" required />
        <div className="stack-sm">
          <PasswordInput label="Password" value={form.password} onChange={set('password')} error={errors.password} hint="At least 8 characters with letters and numbers" autoComplete="new-password" required />
          {form.password && (
            <div className="row" aria-live="polite">
              <div className="strength grow" data-level={strength.level} aria-hidden="true">
                <span /><span /><span /><span />
              </div>
              <span className="xs muted" style={{ minWidth: 48 }}>{strength.label}</span>
            </div>
          )}
        </div>
        <PasswordInput label="Confirm password" value={form.confirm} onChange={set('confirm')} error={errors.confirm} autoComplete="new-password" required />
        <Button type="submit" block size="lg" loading={loading}>Create account</Button>
      </form>
    </AuthLayout>
  );
}

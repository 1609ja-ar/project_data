import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CheckCircle2 } from 'lucide-react';
import AuthLayout from '../layouts/AuthLayout.jsx';
import { Alert, Button, PasswordInput } from '../components/ui/index.js';
import api from '../services/api.js';
import { errorMessage } from '../services/errors.js';
import { passwordProblems } from '../utils/password.js';
import usePageTitle from '../hooks/usePageTitle.js';

export default function ResetPassword() {
  usePageTitle('Choose a new password');
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (ev) => {
    ev.preventDefault();
    setFormError('');
    const e = {};
    const probs = passwordProblems(password);
    if (probs.length) e.password = `Password needs ${probs.join(', ')}`;
    if (confirm !== password) e.confirm = 'Passwords do not match';
    setErrors(e);
    if (Object.keys(e).length) return;
    setLoading(true);
    try {
      await api.post('/auth/reset-password', { token, password });
      setDone(true);
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout title="Choose a new password" footer={<Link to="/signin">Back to sign in</Link>}>
      {!token ? (
        <Alert tone="danger">This reset link is incomplete. Request a new one from <Link to="/forgot-password">Forgot password</Link>.</Alert>
      ) : done ? (
        <div className="stack">
          <Alert tone="success" icon={CheckCircle2}>Password updated. All other sessions were signed out.</Alert>
          <Link to="/signin" className="btn btn-primary btn-lg btn-block">Sign in</Link>
        </div>
      ) : (
        <form className="stack" onSubmit={onSubmit} noValidate>
          {formError && <Alert tone="danger">{formError}</Alert>}
          <PasswordInput label="New password" value={password} onChange={(e) => setPassword(e.target.value)} error={errors.password} autoComplete="new-password" />
          <PasswordInput label="Confirm new password" value={confirm} onChange={(e) => setConfirm(e.target.value)} error={errors.confirm} autoComplete="new-password" />
          <Button type="submit" block size="lg" loading={loading}>Update password</Button>
        </form>
      )}
    </AuthLayout>
  );
}

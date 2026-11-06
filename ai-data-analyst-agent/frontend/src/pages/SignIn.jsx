import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Mail } from 'lucide-react';
import AuthLayout from '../layouts/AuthLayout.jsx';
import { Alert, Button, Input, PasswordInput } from '../components/ui/index.js';
import { useAuth } from '../context/AuthContext.jsx';
import { errorMessage } from '../services/errors.js';
import { EMAIL_RE } from '../utils/password.js';
import usePageTitle from '../hooks/usePageTitle.js';

export default function SignIn() {
  usePageTitle('Sign in');
  const { signin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [loading, setLoading] = useState(false);

  const onSubmit = async (ev) => {
    ev.preventDefault();
    setFormError('');
    const e = {};
    if (!EMAIL_RE.test(email.trim())) e.email = 'Enter a valid email address';
    if (!password) e.password = 'Enter your password';
    setErrors(e);
    if (Object.keys(e).length) return;
    setLoading(true);
    try {
      await signin(email.trim(), password);
      const from = location.state?.from;
      navigate(from && from.startsWith('/app') ? from : '/app', { replace: true });
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to your workspace."
      footer={<>New here? <Link to="/signup">Create an account</Link></>}
    >
      <form className="stack" onSubmit={onSubmit} noValidate>
        {formError && <Alert tone="danger">{formError}</Alert>}
        <Input label="Email" type="email" lead={Mail} value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} autoComplete="email" required />
        <PasswordInput label="Password" value={password} onChange={(e) => setPassword(e.target.value)} error={errors.password} autoComplete="current-password" required />
        <div className="row between">
          <span />
          <Link to="/forgot-password" className="small">Forgot password?</Link>
        </div>
        <Button type="submit" block size="lg" loading={loading}>Sign in</Button>
      </form>
    </AuthLayout>
  );
}

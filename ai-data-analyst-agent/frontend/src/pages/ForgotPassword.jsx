import { useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, Mail } from 'lucide-react';
import AuthLayout from '../layouts/AuthLayout.jsx';
import { Alert, Button, Input } from '../components/ui/index.js';
import api from '../services/api.js';
import { errorMessage } from '../services/errors.js';
import { EMAIL_RE } from '../utils/password.js';
import usePageTitle from '../hooks/usePageTitle.js';

export default function ForgotPassword() {
  usePageTitle('Forgot password');
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [sent, setSent] = useState(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (ev) => {
    ev.preventDefault();
    setError('');
    if (!EMAIL_RE.test(email.trim())) {
      setError('Enter a valid email address');
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.post('/auth/forgot-password', { email: email.trim() });
      setSent({ message: data.message, email: data.email });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="Enter your account email to get a link to choose a new password."
      footer={<Link to="/signin">Back to sign in</Link>}
    >
      {sent ? (
        <Alert tone={sent.email === 'smtp' ? 'success' : 'warning'} icon={CheckCircle2}>{sent.message}</Alert>
      ) : (
        <form className="stack" onSubmit={onSubmit} noValidate>
          <Input label="Email" type="email" lead={Mail} value={email} onChange={(e) => setEmail(e.target.value)} error={error} autoComplete="email" required />
          <Button type="submit" block size="lg" loading={loading}>Send reset link</Button>
        </form>
      )}
    </AuthLayout>
  );
}

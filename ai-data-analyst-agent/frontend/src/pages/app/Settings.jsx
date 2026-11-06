import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Info } from 'lucide-react';
import PageHeader from '../../components/PageHeader.jsx';
import ThemeSwitcher from '../../components/ThemeSwitcher.jsx';
import {
  Alert, Button, Card, CardHeader, ConfirmDialog, Input, PasswordInput, Select, Skeleton, Switch, useToast,
} from '../../components/ui/index.js';
import { useAuth } from '../../context/AuthContext.jsx';
import useApi from '../../hooks/useApi.js';
import usePageTitle from '../../hooks/usePageTitle.js';
import api from '../../services/api.js';
import { errorMessage, getErrorInfo } from '../../services/errors.js';
import { passwordProblems } from '../../utils/password.js';

function ProfileSection() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const [name, setName] = useState(user.full_name);
  const [busy, setBusy] = useState(false);
  const save = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const { data } = await api.patch('/auth/me', { full_name: name.trim() });
      setUser(data.user);
      toast.success('Name updated');
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader title="Profile" subtitle={user.email} />
      <form className="card-body stack" onSubmit={save}>
        <Input label="Display name" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} error={!name.trim() ? 'Name is required' : undefined} />
        <div><Button type="submit" loading={busy} disabled={name.trim() === user.full_name}>Save name</Button></div>
      </form>
    </Card>
  );
}

function AppearanceSection() {
  return (
    <Card>
      <CardHeader title="Appearance" subtitle="System follows your operating system setting." />
      <div className="card-body"><ThemeSwitcher showLabels /></div>
    </Card>
  );
}

function AiSection() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const { data, loading, reload } = useApi('/ai/providers');
  const [saving, setSaving] = useState(false);

  const patch = async (body, msg) => {
    setSaving(true);
    try {
      const { data: d } = await api.patch('/auth/me', body);
      setUser(d.user);
      toast.success(msg);
      reload();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const configured = data?.providers.filter((p) => p.configured) || [];
  return (
    <Card>
      <CardHeader title="AI assistant" subtitle="AI helps read your question and writes explanations. All numbers come from tested backend calculations." />
      <div className="card-body stack">
        {loading ? (
          <Skeleton height={40} />
        ) : configured.length === 0 ? (
          <Alert tone="info" icon={Info}>
            No AI provider is configured on this server. Add a <code>GROQ_API_KEY</code> or <code>XAI_API_KEY</code> to the backend <code>.env</code> to enable AI explanations. Everything else works without AI.
          </Alert>
        ) : (
          <Select
            label="AI provider"
            value={user.ai_provider || data.active || ''}
            disabled={saving}
            onChange={(e) => patch({ ai_provider: e.target.value }, 'AI provider updated')}
            options={data.providers.map((p) => ({ value: p.id, label: p.configured ? p.label : `${p.label} (not configured)`, disabled: !p.configured }))}
          />
        )}
        <div className="stack-sm">
          <Switch
            label="Allow sample rows in AI requests"
            checked={user.allow_ai_samples}
            disabled={saving}
            onChange={(v) => patch({ allow_ai_samples: v }, v ? 'Sample rows allowed' : 'Sample rows disabled')}
          />
          <p className="xs muted">Off by default. When off, AI requests include column names, types, the file name and computed results (such as totals by category), never your rows.</p>
        </div>
      </div>
    </Card>
  );
}

function PasswordSection() {
  const toast = useToast();
  const [form, setForm] = useState({ current: '', next: '', confirm: '' });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    const er = {};
    if (!form.current) er.current = 'Enter your current password';
    const p = passwordProblems(form.next);
    if (p.length) er.next = `Password needs ${p.join(', ')}`;
    if (form.confirm !== form.next) er.confirm = 'Passwords do not match';
    setErrors(er);
    if (Object.keys(er).length) return;
    setBusy(true);
    try {
      await api.post('/auth/change-password', { current_password: form.current, new_password: form.next });
      setForm({ current: '', next: '', confirm: '' });
      toast.success('Password changed. Other sessions were signed out.');
    } catch (err) {
      const info = getErrorInfo(err);
      if (info.code === 'wrong_password') setErrors({ current: info.message });
      else toast.error(info.message);
    } finally {
      setBusy(false);
    }
  };
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <Card>
      <CardHeader title="Change password" />
      <form className="card-body stack" onSubmit={submit} noValidate>
        <PasswordInput label="Current password" value={form.current} onChange={set('current')} error={errors.current} autoComplete="current-password" />
        <PasswordInput label="New password" value={form.next} onChange={set('next')} error={errors.next} autoComplete="new-password" />
        <PasswordInput label="Confirm new password" value={form.confirm} onChange={set('confirm')} error={errors.confirm} autoComplete="new-password" />
        <div><Button type="submit" loading={busy}>Change password</Button></div>
      </form>
    </Card>
  );
}

function DangerSection() {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!open) { setPassword(''); setError(''); } }, [open]);
  const del = async () => {
    if (!password) { setError('Enter your password to confirm'); return; }
    setBusy(true);
    try {
      await api.delete('/auth/me', { data: { password } });
      setUser(null);
      navigate('/', { replace: true });
      window.location.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader title="Delete account" subtitle="Permanently deletes your account, datasets, files, analyses and reports." />
      <div className="card-body">
        <Button variant="danger" icon={AlertTriangle} onClick={() => setOpen(true)}>Delete account</Button>
      </div>
      <ConfirmDialog
        open={open}
        title="Delete your account?"
        message="This cannot be undone. All your datasets, files, analyses, saved queries and reports will be deleted."
        confirmLabel="Delete everything"
        danger
        loading={busy}
        onConfirm={del}
        onCancel={() => setOpen(false)}
      >
        <PasswordInput label="Password" value={password} onChange={(e) => setPassword(e.target.value)} error={error} autoComplete="current-password" />
      </ConfirmDialog>
    </Card>
  );
}

export default function Settings() {
  usePageTitle('Settings');
  return (
    <div className="stack" style={{ maxWidth: 760 }}>
      <PageHeader title="Settings" description="Manage your profile, appearance, AI preferences and security." />
      <ProfileSection />
      <AppearanceSection />
      <AiSection />
      <PasswordSection />
      <DangerSection />
    </div>
  );
}

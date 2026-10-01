import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { errorMessage } from '../api/client';
import AuthLayout from '../components/AuthLayout';
import Field from '../components/Field';
import { useAuth } from '../hooks/authContext';

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (new TextEncoder().encode(form.password).length > 72) {
      setError('Password must be at most 72 bytes.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await register(form);
      navigate('/chat', { replace: true });
    } catch (err) {
      setError(errorMessage(err, 'Registration failed. Please try again.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Create your workspace"
      subtitle="Upload documents, ask questions, get cited answers."
      footer={
        <>
          Already have an account? <Link to="/login">Sign in</Link>
        </>
      }
    >
      <form onSubmit={submit} className="auth-form">
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <Field label="Full name" autoComplete="name" required maxLength={100} value={form.full_name}
          onChange={(e) => setForm({ ...form, full_name: e.target.value })} placeholder="Ada Lovelace" />
        <Field label="Email" type="email" autoComplete="email" required maxLength={254} value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="you@company.com" />
        <Field label="Password" type="password" autoComplete="new-password" required minLength={8} maxLength={72}
          hint="At least 8 characters." value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="Create a password" />
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? <span className="spinner" aria-hidden="true" /> : null}
          {busy ? 'Creating account…' : 'Create account'}
        </button>
      </form>
    </AuthLayout>
  );
}

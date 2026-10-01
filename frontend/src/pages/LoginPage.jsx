import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { errorMessage } from '../api/client';
import AuthLayout from '../components/AuthLayout';
import Field from '../components/Field';
import { useAuth } from '../hooks/authContext';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const expired = location.state?.expired;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await login(form);
      navigate(location.state?.from || '/chat', { replace: true });
    } catch (err) {
      setError(errorMessage(err, 'Sign-in failed. Please try again.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to your document workspace."
      footer={
        <>
          New to DocuMind? <Link to="/register">Create an account</Link>
        </>
      }
    >
      <form onSubmit={submit} className="auth-form" noValidate={false}>
        {expired && !error && <p className="notice">Your session ended. Please sign in again.</p>}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <Field label="Email" type="email" autoComplete="email" required value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="you@company.com" />
        <Field label="Password" type="password" autoComplete="current-password" required value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="Your password" />
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? <span className="spinner" aria-hidden="true" /> : null}
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </AuthLayout>
  );
}

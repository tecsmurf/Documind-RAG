import { lazy, Suspense, useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import Logo from './components/Logo';
import { AUTH_EXPIRED_EVENT } from './api/client';
import { AuthProvider } from './hooks/AuthProvider';
import { useAuth } from './hooks/authContext';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';

// The workspace (markdown renderer, chat) loads separately so the sign-in screen stays light.
const ChatPage = lazy(() => import('./pages/ChatPage'));

function Splash() {
  return (
    <div className="splash" role="status" aria-live="polite">
      <Logo size="lg" />
      <span className="visually-hidden">Loading</span>
    </div>
  );
}

/** UX only: the API rejects unauthenticated requests regardless of what the router shows. */
function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Splash />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Suspense fallback={<Splash />}>{children}</Suspense>;
}

function PublicOnlyRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <Splash />;
  return user ? <Navigate to="/chat" replace /> : children;
}

function SessionWatcher() {
  const navigate = useNavigate();
  useEffect(() => {
    const onExpired = () => navigate('/login', { replace: true, state: { expired: true } });
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, [navigate]);
  return null;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <SessionWatcher />
        <Routes>
          <Route path="/login" element={<PublicOnlyRoute><LoginPage /></PublicOnlyRoute>} />
          <Route path="/register" element={<PublicOnlyRoute><RegisterPage /></PublicOnlyRoute>} />
          <Route path="/chat" element={<ProtectedRoute><ChatPage /></ProtectedRoute>} />
          <Route path="/chat/:conversationId" element={<ProtectedRoute><ChatPage /></ProtectedRoute>} />
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

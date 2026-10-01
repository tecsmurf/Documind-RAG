import { useCallback, useEffect, useMemo, useState } from 'react';
import { AUTH_EXPIRED_EVENT, authAPI, tokenStore } from '../api/client';
import { AuthContext } from './authContext';

/**
 * Session state. The token is a short-lived bearer JWT; the server is the only
 * authority (every API call re-checks it), so this context is UX, not security.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState(() => (tokenStore.get() ? 'checking' : 'signed-out'));

  useEffect(() => {
    if (status !== 'checking') return undefined;
    let active = true;
    authAPI
      .me()
      .then((res) => {
        if (!active) return;
        setUser(res.data);
        setStatus('signed-in');
      })
      .catch(() => {
        if (!active) return;
        tokenStore.clear();
        setUser(null);
        setStatus('signed-out');
      });
    return () => {
      active = false;
    };
  }, [status]);

  useEffect(() => {
    const onExpired = () => {
      setUser(null);
      setStatus('signed-out');
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, []);

  const startSession = useCallback(async (token) => {
    tokenStore.set(token);
    const me = await authAPI.me();
    setUser(me.data);
    setStatus('signed-in');
  }, []);

  const login = useCallback(
    async (credentials) => {
      const res = await authAPI.login(credentials);
      await startSession(res.data.access_token);
    },
    [startSession],
  );

  const register = useCallback(
    async (data) => {
      const res = await authAPI.register(data);
      await startSession(res.data.access_token);
    },
    [startSession],
  );

  const logout = useCallback(async () => {
    try {
      await authAPI.logout(); // revokes the token server-side
    } catch {
      /* already invalid: nothing to revoke */
    }
    tokenStore.clear();
    setUser(null);
    setStatus('signed-out');
  }, []);

  const value = useMemo(
    () => ({ user, loading: status === 'checking', login, register, logout }),
    [user, status, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

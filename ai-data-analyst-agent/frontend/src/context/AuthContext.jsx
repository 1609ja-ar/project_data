import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import api, { setAuthLostHandler } from '../services/api.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | authenticated | anonymous

  const loadMe = useCallback(async () => {
    try {
      const { data } = await api.get('/auth/me', { skipAuthRedirect: true });
      setUser(data.user);
      setStatus('authenticated');
    } catch {
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  useEffect(() => {
    loadMe();
    setAuthLostHandler(() => {
      setUser(null);
      setStatus('anonymous');
    });
  }, [loadMe]);

  const signin = useCallback(async (email, password) => {
    const { data } = await api.post('/auth/signin', { email, password });
    setUser(data.user);
    setStatus('authenticated');
    return data.user;
  }, []);

  const signup = useCallback(async (full_name, email, password) => {
    const { data } = await api.post('/auth/signup', { full_name, email, password });
    setUser(data.user);
    setStatus('authenticated');
    return data.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } finally {
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  const value = useMemo(
    () => ({ user, status, setUser, signin, signup, logout, reload: loadMe }),
    [user, status, signin, signup, logout, loadMe],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

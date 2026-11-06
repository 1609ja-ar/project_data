import axios from 'axios';

// Sign-in state lives in one HttpOnly session cookie that page scripts cannot read; the browser sends it with
// every request. The X-Requested-With header tells the API the request comes from this app (it rejects
// state-changing requests without it, which blocks cross-site request forgery).
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  withCredentials: true,
  timeout: 120000,
  headers: { 'X-Requested-With': 'fetch' },
});

let onAuthLost = () => {};
export function setAuthLostHandler(fn) {
  onAuthLost = fn;
}

const AUTH_PAGES = ['/auth/signin', '/auth/signup', '/auth/logout', '/auth/forgot-password', '/auth/reset-password'];

// A 401 means the session ended (signed out elsewhere, password changed, or expired): show the sign-in page.
api.interceptors.response.use(
  (r) => r,
  (error) => {
    const { config, response } = error;
    if (response?.status === 401 && config && !config.skipAuthRedirect && !AUTH_PAGES.some((p) => config.url?.endsWith(p))) {
      onAuthLost();
    }
    throw error;
  },
);

export default api;

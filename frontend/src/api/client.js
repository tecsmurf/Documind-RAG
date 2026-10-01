/**
 * API client. The only place that knows the backend URL and the token.
 *
 * - VITE_API_URL is baked in at build time (Vercel must redeploy after changing it).
 * - The Gemini key never exists here: all AI calls happen on the server.
 * - Errors are normalised to safe, human messages; raw server details are never shown.
 */
import axios from 'axios';

const configured = (import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '').replace(/\/api$/, '');
export const API_URL = configured || (import.meta.env.DEV ? 'http://localhost:8000' : '');

if (!configured && import.meta.env.PROD) {
  // A missing VITE_API_URL in production used to make every request hit the Vercel host itself.
  console.error('VITE_API_URL is not set for this build; API requests will fail. Set it in Vercel and redeploy.');
}

const TOKEN_KEY = 'documind.token';

export const tokenStore = {
  get() {
    try {
      return localStorage.getItem(TOKEN_KEY) || localStorage.getItem('token');
    } catch {
      return null;
    }
  },
  set(token) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.removeItem('token'); // legacy key from the old frontend
    } catch {
      /* storage unavailable (private mode): session lasts until reload */
    }
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem('token');
    } catch {
      /* ignore */
    }
  },
};

export const AUTH_EXPIRED_EVENT = 'documind:auth-expired';

const api = axios.create({ baseURL: `${API_URL}/api`, timeout: 60000 });

api.interceptors.request.use((config) => {
  const token = tokenStore.get();
  if (token && !config.skipAuth) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    // Only an authenticated request that is rejected means the session ended.
    // A failed login/registration is a normal error shown on the form.
    if (err.response?.status === 401 && !err.config?.skipAuth) {
      tokenStore.clear();
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
    return Promise.reject(err);
  },
);

const STATUS_MESSAGES = {
  400: 'The request could not be processed.',
  401: 'Your session has ended. Please sign in again.',
  403: 'You do not have access to this item.',
  404: 'This item no longer exists.',
  409: 'This already exists.',
  413: 'This file is too large.',
  415: 'This file type is not supported.',
  422: 'Please check the highlighted fields.',
  429: 'Too many requests. Please wait a moment and try again.',
};

/** Turn any error into a short message that is safe to display. */
export function errorMessage(err, fallback = 'Something went wrong. Please try again.') {
  if (!err) return fallback;
  if (err.code === 'ERR_CANCELED') return '';
  const status = err.response?.status ?? err.status;
  const detail = err.response?.data?.detail ?? err.detail;
  if (!status) {
    return err.code === 'ECONNABORTED'
      ? 'The server took too long to respond. Please try again.'
      : 'Could not reach the server. Check your connection and try again.';
  }
  if (status >= 500) return fallback;
  if (status === 422 && Array.isArray(err.response?.data?.errors)) {
    const first = err.response.data.errors[0];
    if (first?.field && first?.message) return `${humanField(first.field)}: ${first.message.replace(/^Value error, /, '')}`;
  }
  // Backend `detail` strings are written to be user-safe; still bound their length.
  if (typeof detail === 'string' && detail.length < 300) return detail;
  return STATUS_MESSAGES[status] || fallback;
}

function humanField(field) {
  const last = field.split('.').pop();
  return { email: 'Email', password: 'Password', full_name: 'Name', question: 'Question' }[last] || 'Input';
}

export const authAPI = {
  register: (data) => api.post('/auth/register', data, { skipAuth: true }),
  login: ({ email, password }) => {
    const form = new URLSearchParams();
    form.append('username', email);
    form.append('password', password);
    return api.post('/auth/login', form, {
      skipAuth: true,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
  },
  me: () => api.get('/auth/me'),
  logout: () => api.post('/auth/logout'),
};

export const docsAPI = {
  list: () => api.get('/documents'),
  get: (id) => api.get(`/documents/${encodeURIComponent(id)}`),
  chunk: (docId, chunkId) => api.get(`/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}`),
  upload: (file, onUploadProgress) => {
    const form = new FormData();
    form.append('file', file);
    return api.post('/documents/upload', form, { onUploadProgress, timeout: 120000 });
  },
  remove: (id) => api.delete(`/documents/${encodeURIComponent(id)}`),
};

export const chatAPI = {
  list: () => api.get('/chat/conversations'),
  create: (title = 'New Conversation') => api.post('/chat/conversations', { title }),
  messages: (id) => api.get(`/chat/conversations/${encodeURIComponent(id)}/messages`),
  remove: (id) => api.delete(`/chat/conversations/${encodeURIComponent(id)}`),
};

export default api;

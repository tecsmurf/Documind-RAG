import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

export const authAPI = {
  register: (data) => api.post('/auth/register', data),
  login: (data) => {
    const form = new URLSearchParams();
    form.append('username', data.email);
    form.append('password', data.password);
    return api.post('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
  },
  getMe: () => api.get('/auth/me'),
};

export const docsAPI = {
  upload: (file) => {
    const form = new FormData();
    form.append('file', file);
    return api.post('/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  list: () => api.get('/documents'),
  delete: (id) => api.delete(`/documents/${id}`),
};

export const chatAPI = {
  createConversation: (title) => api.post('/chat/conversations', { title }),
  listConversations: () => api.get('/chat/conversations'),
  getMessages: (convId) => api.get(`/chat/conversations/${convId}/messages`),
  ask: (convId, question, documentIds) =>
    api.post(`/chat/conversations/${convId}/ask`, { question, document_ids: documentIds }),
  streamUrl: (convId) => `${API_URL}/api/chat/conversations/${convId}/stream`,
};

export default api;

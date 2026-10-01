import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../api/client', async (orig) => {
  const actual = await orig();
  return {
    ...actual,
    authAPI: { me: vi.fn(), login: vi.fn(), register: vi.fn(), logout: vi.fn() },
    tokenStore: { get: vi.fn(() => null), set: vi.fn(), clear: vi.fn() },
  };
});

import App from '../App';
import { authAPI, tokenStore } from '../api/client';

describe('routing guards', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  });

  it('redirects unauthenticated users from /chat to /login', async () => {
    window.history.pushState({}, '', '/chat/5');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/login');
  });

  it('unknown routes fall back to /chat then /login when signed out', async () => {
    window.history.pushState({}, '', '/does/not/exist');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
  });

  it('a stored but rejected token ends on the login page', async () => {
    tokenStore.get.mockReturnValue('stale');
    authAPI.me.mockRejectedValue({ response: { status: 401 } });
    window.history.pushState({}, '', '/chat');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
    expect(tokenStore.clear).toHaveBeenCalled();
  });

  it('signed-in users visiting /login are sent to /chat', async () => {
    tokenStore.get.mockReturnValue('good');
    authAPI.me.mockResolvedValue({ data: { id: 1, email: 'a@b.c', full_name: 'A' } });
    window.history.pushState({}, '', '/login');
    render(<App />);
    await vi.waitFor(() => expect(window.location.pathname).toBe('/chat'));
  });
});

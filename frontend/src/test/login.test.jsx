import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { AuthContext } from '../hooks/authContext';
import LoginPage from '../pages/LoginPage';

window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));

describe('login form', () => {
  it('shows the generic credential error instead of reloading the page', async () => {
    const login = vi.fn().mockRejectedValue({ response: { status: 401, data: { detail: 'Invalid email or password.' } } });
    render(
      <AuthContext.Provider value={{ login }}>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </AuthContext.Provider>,
    );
    await userEvent.type(screen.getByLabelText('Email'), 'a@b.co');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong-pass');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.');
    expect(login).toHaveBeenCalledWith({ email: 'a@b.co', password: 'wrong-pass' });
  });

  it('decorative 3D scene is hidden from assistive tech', () => {
    const { container } = render(
      <AuthContext.Provider value={{ login: vi.fn() }}>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </AuthContext.Provider>,
    );
    const scene = container.querySelector('.scene');
    expect(scene).toHaveAttribute('aria-hidden', 'true');
  });
});

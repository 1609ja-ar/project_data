import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import { ThemeProvider } from '../context/ThemeContext.jsx';
import { ToastProvider } from '../components/ui/index.js';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../services/api.js', () => ({ default: apiMock, setAuthLostHandler: vi.fn() }));

const { AuthProvider } = await import('../context/AuthContext.jsx');
const { default: SignUp } = await import('../pages/SignUp.jsx');
const { default: ProtectedRoute } = await import('../components/ProtectedRoute.jsx');

function wrap(ui, path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>{ui}</AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiMock.get.mockReset();
  apiMock.post.mockReset();
  apiMock.get.mockRejectedValue({ response: { status: 401 } });
});

test('protected route redirects anonymous users to sign in', async () => {
  wrap(
    <Routes>
      <Route path="/app" element={<ProtectedRoute><p>secret</p></ProtectedRoute>} />
      <Route path="/signin" element={<p>sign in page</p>} />
    </Routes>,
    '/app',
  );
  expect(await screen.findByText('sign in page')).toBeInTheDocument();
  expect(screen.queryByText('secret')).not.toBeInTheDocument();
});

test('sign up validates fields and shows duplicate email error from the API', async () => {
  const user = userEvent.setup();
  apiMock.post.mockRejectedValue({
    response: { status: 409, data: { error: { code: 'email_taken', message: 'This email is already registered.' } } },
  });
  wrap(<SignUp />);
  await user.click(await screen.findByRole('button', { name: 'Create account' }));
  expect(screen.getByText('Enter your name')).toBeInTheDocument();
  expect(apiMock.post).not.toHaveBeenCalled();

  await user.type(screen.getByLabelText('Full name'), 'Ana');
  await user.type(screen.getByLabelText('Email'), 'ana@example.com');
  await user.type(screen.getByLabelText('Password'), 'abc12345');
  await user.type(screen.getByLabelText('Confirm password'), 'abc12345');
  await user.click(screen.getByRole('button', { name: 'Create account' }));
  await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/auth/signup', { full_name: 'Ana', email: 'ana@example.com', password: 'abc12345' }));
  expect(await screen.findByText('This email is already registered.')).toBeInTheDocument();
});

test('password visibility toggle', async () => {
  const user = userEvent.setup();
  wrap(<SignUp />);
  const pw = await screen.findByLabelText('Password');
  expect(pw).toHaveAttribute('type', 'password');
  await user.click(screen.getAllByRole('button', { name: 'Show password' })[0]);
  expect(pw).toHaveAttribute('type', 'text');
});

import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider, useTheme } from '../context/ThemeContext.jsx';
import ThemeSwitcher from '../components/ThemeSwitcher.jsx';

function mockMatchMedia(dark) {
  const listeners = new Set();
  const mq = {
    matches: dark,
    media: '(prefers-color-scheme: dark)',
    addEventListener: (_, fn) => listeners.add(fn),
    removeEventListener: (_, fn) => listeners.delete(fn),
  };
  window.matchMedia = () => mq;
  return {
    set(next) {
      mq.matches = next;
      listeners.forEach((fn) => fn({ matches: next }));
    },
  };
}

function Probe() {
  const { mode, resolved } = useTheme();
  return <p>{`${mode}:${resolved}`}</p>;
}

beforeEach(() => localStorage.clear());

test('choice persists across reloads', async () => {
  mockMatchMedia(false);
  const user = userEvent.setup();
  const { unmount } = render(<ThemeProvider><ThemeSwitcher /><Probe /></ThemeProvider>);
  await user.click(screen.getByRole('radio', { name: 'Dark' }));
  expect(screen.getByText('dark:dark')).toBeInTheDocument();
  expect(localStorage.getItem('theme')).toBe('dark');
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  unmount();
  render(<ThemeProvider><Probe /></ThemeProvider>); // simulated reload
  expect(screen.getByText('dark:dark')).toBeInTheDocument();
});

test('system mode follows the OS setting live', () => {
  const mm = mockMatchMedia(false);
  render(<ThemeProvider><Probe /></ThemeProvider>);
  expect(screen.getByText('system:light')).toBeInTheDocument();
  act(() => mm.set(true));
  expect(screen.getByText('system:dark')).toBeInTheDocument();
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
});

test('components that read CSS variables while rendering see the new theme immediately', async () => {
  mockMatchMedia(false);
  const { cssVar } = await import('../context/ThemeContext.jsx');
  const style = document.createElement('style');
  style.textContent = ":root[data-theme='light'] { --probe: light-value; } :root[data-theme='dark'] { --probe: dark-value; }";
  document.head.appendChild(style);
  function ReadsVar() {
    useTheme(); // re-renders on theme change, like useThemeColors
    return <p>{`var:${cssVar('--probe')}`}</p>;
  }
  const user = userEvent.setup();
  render(<ThemeProvider><ThemeSwitcher /><ReadsVar /></ThemeProvider>);
  await user.click(screen.getByRole('radio', { name: 'Light' }));
  expect(screen.getByText('var:light-value')).toBeInTheDocument();
  await user.click(screen.getByRole('radio', { name: 'Dark' }));
  expect(screen.getByText('var:dark-value')).toBeInTheDocument();   // before the fix this still said light-value
  style.remove();
});

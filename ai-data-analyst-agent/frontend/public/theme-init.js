// Apply the saved theme before first paint to avoid a flash of the wrong theme.
// A file rather than an inline <script>, so the Content-Security-Policy can forbid inline scripts.
(function () {
  var mode = 'system';
  try { mode = localStorage.getItem('theme') || 'system'; } catch (e) {}
  var dark = mode === 'dark' || (mode === 'system' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme-mode', mode);
})();

// Security headers for the web app. Used by `vite preview` and written to dist/_headers at build time
// (Netlify and Cloudflare Pages read that file; for nginx or another server, copy these values; see docs/SECURITY.md).
//
// If the API is on a different origin (VITE_API_BASE=https://api.example.com/api), that origin is added to connect-src.

export function contentSecurityPolicy(apiBase = '/api') {
  let api = '';
  try { api = /^https?:\/\//.test(apiBase) ? new URL(apiBase).origin : ''; } catch { api = ''; }
  return [
    "default-src 'self'",
    "script-src 'self'",
    // Inline styles: React style props and CodeMirror's injected editor styles. Scripts stay strict.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self'${api ? ' ' + api : ''}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join('; ');
}

export function securityHeaders(apiBase, { https = false } = {}) {
  const h = {
    'Content-Security-Policy': contentSecurityPolicy(apiBase),
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  };
  if (https) h['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains';
  return h;
}

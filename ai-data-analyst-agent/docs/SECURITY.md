# Security

What protects the app, and the steps to take before putting it online.

## What is built in

| Area | How |
|---|---|
| Sign-in | One HttpOnly, SameSite=Lax session cookie (`sid`, Secure in production) holding a random ID. The server stores only its SHA-256 hash. Sessions end on logout, after 7 idle days, after 30 days, and on password change/reset. |
| Passwords | Argon2id (`argon2-cffi`, RFC 9106 parameters). Old hashes are upgraded at the next sign-in. Sign-in takes the same time whether or not the email exists, and an email is locked out briefly after repeated failures. |
| Cross-site requests | Every write needs the `X-Requested-With` header the app sends, and its `Origin` must be an allowed origin. |
| CORS | Only the origins in `CORS_ORIGINS`, with credentials. A `*` origin is refused in production. |
| Rate limits | Every API request per IP (`API_RATE_LIMIT`). Sign-in, sign-up, forgot/reset password, the Power BI feed and share links per IP. AI calls, uploads/URL imports/refreshes and SQL runs per user. Over the limit = HTTP 429. |
| Endpoints | All routes need a signed-in user except: health, sign-in/up, forgot/reset password, the token-protected Power BI feed and share links. Every dataset lookup is scoped to its owner. Tested in `backend/tests`. |
| API headers | `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `Permissions-Policy`, HSTS in production. No `Server` header. |
| Web app headers | Strict CSP (scripts only from the app itself, no inline scripts), the same framing/sniffing/referrer protections. Defined in `frontend/security-headers.js`. |
| Errors | Production never returns stack traces; unexpected errors are logged with a request ID and the user sees a generic message. API docs and the OpenAPI schema are off in production. Secrets in URLs are redacted from logs. |
| SQL Workbench | Read-only statements only, parsed and checked before running, with time, memory and row limits. |
| Secrets | Only `.env.example` files are in Git. `.env`, keys and certificates are ignored. |

## Before going live

1. **backend/.env** (never commit it):
   - `APP_ENV=production`
   - `FRONTEND_URL=https://your-app-domain`, `CORS_ORIGINS=https://your-app-domain`
   - `ALLOWED_HOSTS=your-api-host`
   - `MONGODB_URI` with a username/password, over TLS (see below)

   The server will not start until these are safe and prints which ones are not.
2. **MongoDB**
   - Turn on access control. Create a user with only the `readWrite` role on the app database (not `root`, not `dbAdmin`).
   - Use TLS (`mongodb+srv://…` on Atlas, or `tls=true`).
   - Do not expose port 27017 to the internet; on Atlas, allow only your server's IP address.
3. **Run the backend** without auto-reload and without the server banner, behind HTTPS:

   ```
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-server-header --proxy-headers --forwarded-allow-ips=127.0.0.1
   ```

   `--proxy-headers` with only your proxy's address lets rate limits see real client IPs without trusting forged ones. For more than one worker or server, set `RATE_LIMIT_STORAGE_URI=redis://…` and `pip install redis`, so limits are shared.
4. **Serve the web app with its headers.** `npm run build` writes `dist/_headers`, which Netlify and Cloudflare Pages apply automatically. With nginx, add the same values, for example:

   ```
   add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'" always;
   add_header X-Content-Type-Options nosniff always;
   add_header X-Frame-Options DENY always;
   add_header Referrer-Policy strict-origin-when-cross-origin always;
   add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
   ```

   If the API is on a different origin, add it to `connect-src` (the build does this from `VITE_API_BASE`).
5. **Never serve `backend/storage/`** as static files.
6. Run the checks below and fix anything they report.

## Checks

```
cd backend && pip-audit -r requirements.txt && pytest -q
cd frontend && npm audit && npm test && npm run build
```

On GitHub, `.github/workflows/security.yml` runs these, plus a full-history secret scan (gitleaks), on every push and every Monday. `.github/dependabot.yml` opens weekly pull requests for dependency updates and security fixes.

**If a key is ever committed:** revoke it at the provider first (deleting the commit is not enough, because forks and caches keep it), then remove it from history.

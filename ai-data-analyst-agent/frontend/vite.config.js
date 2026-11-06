import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { securityHeaders } from './security-headers.js';

// Writes dist/_headers so static hosts that read it (Netlify, Cloudflare Pages) send the security headers.
function headersFile(apiBase) {
  return {
    name: 'security-headers-file',
    apply: 'build',
    writeBundle(options) {
      const lines = Object.entries(securityHeaders(apiBase, { https: true })).map(([k, v]) => `  ${k}: ${v}`);
      writeFileSync(resolve(options.dir || 'dist', '_headers'), `/*\n${lines.join('\n')}\n`);
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const apiBase = env.VITE_API_BASE || '/api';
  const devHeaders = { ...securityHeaders(apiBase) };
  delete devHeaders['Content-Security-Policy']; // the dev server injects inline scripts for hot reload
  return {
    plugins: [react(), headersFile(apiBase)],
    server: {
      port: 5173,
      headers: devHeaders,
      // API_TARGET lets a second dev setup run against another backend port.
      proxy: { '/api': { target: process.env.API_TARGET || 'http://127.0.0.1:8000', changeOrigin: false } },
    },
    preview: {
      headers: securityHeaders(apiBase),
      proxy: { '/api': { target: process.env.API_TARGET || 'http://127.0.0.1:8000', changeOrigin: false } },
    },
    build: {
      chunkSizeWarningLimit: 900,
      sourcemap: false, // do not publish the original source code
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: './src/test/setup.js',
      css: false,
    },
  };
});

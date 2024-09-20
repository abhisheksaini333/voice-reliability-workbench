import { defineConfig } from 'vitest/config';
export default defineConfig({
  server: { proxy: {
    '/api': { target: 'http://127.0.0.1:8096', ws: true },
    '/health': 'http://127.0.0.1:8096',
  } },
  test: { environment: 'jsdom', include: ['tests/**/*.test.tsx'], threads: false },
});

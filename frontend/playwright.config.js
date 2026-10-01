import { defineConfig, devices } from '@playwright/test';

/**
 * Browser E2E against the real backend running with a fake Gemini
 * (backend/tests/e2e_server.py) and a production build of the frontend.
 *   E2E_API_URL  backend base URL (default http://localhost:8010)
 *   E2E_BASE_URL frontend URL     (default http://localhost:4173)
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:4173',
    trace: 'off',
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } }, grepInvert: /@mobile/ },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, grep: /@mobile/ },
  ],
});

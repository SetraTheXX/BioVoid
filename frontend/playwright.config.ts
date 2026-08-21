import { defineConfig } from '@playwright/test';

const python = process.env.BIOVOID_PYTHON ?? 'python';
const port = process.env.BIOVOID_E2E_PORT ?? '18080';
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL,
    headless: true,
  },
  webServer: {
    command: `"${python}" ../scripts/run_phase6_api.py --host 127.0.0.1 --port ${port}`,
    url: `${baseURL}/health`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});

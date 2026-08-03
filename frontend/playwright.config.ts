import { defineConfig } from '@playwright/test';

const python = process.env.BIOVOID_PYTHON ?? 'python';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:8000',
    headless: true,
  },
  webServer: {
    command: `${python} ../scripts/run_phase6_api.py --host 127.0.0.1 --port 8000`,
    url: 'http://127.0.0.1:8000/health',
    reuseExistingServer: false,
    timeout: 120_000,
  },
});

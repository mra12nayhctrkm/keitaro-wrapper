import { defineConfig, devices } from '@playwright/test'

const PORT = 8899

// The real backend (API + the built UI from dist/) against an in-memory fake Keitaro.
// Run `npm run build` first; `npm run e2e` does both.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'uv run python -m tests.e2e_server',
    cwd: '../backend',
    url: `http://127.0.0.1:${PORT}/api/health`,
    env: { E2E_PORT: String(PORT) },
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})

/**
 * Playwright configuration for the end-to-end specs in e2e/, run against a running stack
 * (`docker compose up --build --wait` locally and in CI). The specs read WEB_BASE_URL and
 * API_BASE_URL; both default to the compose ports.
 */
import { defineConfig, devices } from '@playwright/test';

process.env.WEB_BASE_URL ??= 'http://localhost:3000';
process.env.API_BASE_URL ??= 'http://localhost:3001';

export default defineConfig({
    testDir: 'e2e',
    forbidOnly: Boolean(process.env.CI),
    retries: process.env.CI ? 1 : 0,
    reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
    use: {
        baseURL: process.env.WEB_BASE_URL,
        trace: 'retain-on-failure',
    },
    projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});

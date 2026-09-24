/**
 * Playwright configuration for the smoke suite (`pnpm smoke`; spec B-28, amended 2026-09-24):
 * a few requests proving every service started and answers, run in CI against the compose stack
 * built from the production images, and by a fork after its first deploy against the live URLs.
 * The base URLs default to the compose ports. Against a deployment whose worker has no public
 * address, run it with `--grep-invert worker`.
 */
import { defineConfig, devices } from '@playwright/test';

process.env.SMOKE_WEB_URL ??= 'http://localhost:3000';
process.env.SMOKE_API_URL ??= 'http://localhost:3001';
process.env.SMOKE_WORKER_URL ??= 'http://localhost:3002';

export default defineConfig({
    expect: { timeout: 10_000 },
    forbidOnly: true,
    projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
    reporter: 'list',
    retries: process.env.CI ? 1 : 0,
    testDir: 'e2e/smoke',
    testMatch: '*.smoke.ts',
    timeout: 30_000,
    use: {
        baseURL: process.env.SMOKE_WEB_URL,
        trace: 'retain-on-failure',
    },
    workers: 1,
});

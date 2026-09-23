/**
 * Playwright configuration for the `visual-regression` project (spec: B-39).
 *
 * It starts Storybook, reads the story index, and snapshots every story. A rendering change
 * without an updated baseline fails the run. Baselines are Linux renders, generated inside the
 * Playwright container (`pnpm test:visual:update`), because font rasterisation differs by OS and a
 * macOS baseline would fail on every CI run.
 */
import { defineConfig, devices } from '@playwright/test';

const STORYBOOK_PORT = 6006;

process.env.STORYBOOK_URL ??= `http://localhost:${STORYBOOK_PORT}`;

export default defineConfig({
    testDir: 'e2e/visual',
    testMatch: '**/*.visual.ts',
    forbidOnly: Boolean(process.env.CI),
    reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
    snapshotPathTemplate: '{testDir}/__snapshots__/{arg}{ext}',
    expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.01, animations: 'disabled' } },
    use: { baseURL: process.env.STORYBOOK_URL },
    projects: [{ name: 'visual-regression', use: { ...devices['Desktop Chrome'] } }],
    webServer: {
        command: `pnpm --filter @repo/web exec storybook dev --ci --no-open --port ${STORYBOOK_PORT}`,
        url: `${process.env.STORYBOOK_URL}/index.json`,
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
    },
});

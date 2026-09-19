/**
 * End-to-end checks of the landing page and the web server health route against a running Nuxt app.
 * Stories US-LANDING-001 (spec B-49) and US-INFRA-003; the base URL comes from WEB_BASE_URL.
 * /login and /register answer 404 until slice 03, so the link tests assert only the navigation.
 */
import { test, expect } from '@playwright/test';

const webBaseUrl = process.env.WEB_BASE_URL ?? '';
const productName = 'template-fastapi-nuxt';

test.describe('landing page', () => {
    test('US-LANDING-001: / renders one heading naming the product (B-49)', async ({ page }) => {
        await page.goto(`${webBaseUrl}/`);

        await expect(page.locator('[data-test-id="landing-page"]')).toBeVisible();
        await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
        await expect(page.getByRole('heading', { level: 1 })).toContainText(productName);
    });

    test('US-LANDING-001: the "Log in" link navigates to /login (B-49)', async ({ page }) => {
        await page.goto(`${webBaseUrl}/`);

        await page.getByRole('link', { name: 'Log in' }).click();

        await expect(page).toHaveURL(/\/login$/);
    });

    test('US-LANDING-001: the "Register" link navigates to /register (B-49)', async ({ page }) => {
        await page.goto(`${webBaseUrl}/`);

        await page.getByRole('link', { name: 'Register' }).click();

        await expect(page).toHaveURL(/\/register$/);
    });
});

test.describe('web server health route', () => {
    test('US-INFRA-003: GET /api/health answers 200 with status ok', async ({ request }) => {
        const response = await request.get(`${webBaseUrl}/api/health`);

        expect(response.status()).toBe(200);
        expect(await response.json()).toEqual({ status: 'ok' });
    });
});

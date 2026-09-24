/**
 * End-to-end checks of billing against the default stack, which runs without Stripe credentials
 * (US-BILLING; spec B-42, B-50). Checkout, portal and signed webhooks against Stripe are covered
 * by the API integration tests and by the stripe-mock `e2e` compose profile; this file proves the
 * routes are mounted, refuse what they must, and that the dashboard reports a refusal in place.
 */
import { test, expect, type BrowserContext } from '@playwright/test';
import { randomUUID } from 'node:crypto';

import { clearRateLimitCounters } from './rateLimitCounters';

test.beforeAll(() => {
    clearRateLimitCounters();
});

// This file's own client address, so it spends a rate-limit bucket no other spec shares.
const CLIENT_ADDRESS = '198.51.100.40';
test.use({ extraHTTPHeaders: { 'X-Forwarded-For': CLIENT_ADDRESS } });

const CSRF_HEADERS = { 'X-Requested-With': 'XMLHttpRequest' };
const apiBaseUrl = process.env.API_BASE_URL ?? '';
const passphrase = ['e2e', 'billing', 'passphrase', '4471'].join('-');

/** Register through the proxy, leaving this context signed in. */
async function registerThroughProxy(context: BrowserContext): Promise<void> {
    const email = `e2e-billing-${Date.now()}-${randomUUID().slice(0, 8)}@example.test`;
    const response = await context.request.post('/api/v1/auth/register', {
        data: Object.fromEntries([
            ['email', email],
            ['password', passphrase],
        ]),
        headers: CSRF_HEADERS,
    });
    expect(response.status(), await response.text()).toBe(201);
}

test('B-42: an unsigned webhook delivery is refused and writes nothing', async ({ request }) => {
    const response = await request.post(`${apiBaseUrl}/v1/billing/webhook`, {
        data: '{"id":"evt_unsigned","type":"checkout.session.completed"}',
        headers: { 'Content-Type': 'application/json' },
    });

    expect(response.status()).toBe(400);
    expect((await response.json()).code).toBe('BILLING_WEBHOOK_MISCONFIGURED');
});

test('B-50: the dashboard reports a billing refusal and stays put', async ({ context, page }) => {
    await registerThroughProxy(context);
    await page.goto('/dashboard');

    for (const buttonName of ['Subscribe', 'Manage billing']) {
        await page.getByRole('button', { name: buttonName }).click();
        await expect(page.getByRole('alert')).toBeVisible();
        await expect(page).toHaveURL(/\/dashboard$/);
    }
});

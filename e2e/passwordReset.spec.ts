/**
 * End-to-end checks of the password-recovery pages against the running stack (spec: B-14, B-15,
 * B-36). The full reset with a real token is covered by the API integration tests, which read the
 * token the job emails; a browser run has no inbox to read it from. This file spends two requests
 * of the shared auth rate-limit bucket.
 */
import { test, expect, type Page } from '@playwright/test';

import { clearRateLimitCounters } from './rateLimitCounters';

const passphrase = ['e2e', 'reset', 'passphrase', '3381'].join('-');
const otherPassphrase = ['e2e', 'reset', 'mismatch', '7720'].join('-');

/** Fill a labelled field. */
async function fillField(page: Page, label: string, value: string): Promise<void> {
    await page.getByLabel(label, { exact: true }).fill(value);
}

test.beforeAll(() => {
    clearRateLimitCounters();
});

// This file's own client address, so its requests count in a rate-limit bucket no other spec
// shares. Nitro takes the last X-Forwarded-For entry as the client, which in compose, with no
// edge in front, is whatever the browser sends (documentation range, RFC 5737).
const CLIENT_ADDRESS = '198.51.100.20';
test.use({ extraHTTPHeaders: { 'X-Forwarded-For': CLIENT_ADDRESS } });

test('B-14, B-36: a signed-out visitor requests a reset and sees the submitted state', async ({
    page,
}) => {
    await page.goto('/login');
    await page.getByRole('link', { name: 'Forgot your password?' }).click();
    await expect(page).toHaveURL(/\/forgot-password$/);

    await fillField(page, 'Email', 'nobody-in-particular@example.test');
    await page.getByRole('button', { name: 'Send reset link' }).click();

    await expect(page.getByRole('status')).toContainText('Check your email');
});

test('B-36: the reset page refuses mismatched passwords before sending anything', async ({
    page,
}) => {
    await page.goto('/reset-password?token=not-a-real-token');

    await fillField(page, 'New password', passphrase);
    await fillField(page, 'Confirm new password', otherPassphrase);
    await page.getByRole('button', { name: 'Reset password' }).click();

    await expect(page.getByRole('alert')).toContainText('do not match');
});

test('B-15: an unknown token is refused on the page', async ({ page }) => {
    await page.goto('/reset-password?token=not-a-real-token');

    await fillField(page, 'New password', passphrase);
    await fillField(page, 'Confirm new password', passphrase);
    await page.getByRole('button', { name: 'Reset password' }).click();

    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page).toHaveURL(/\/reset-password/);
});

test('B-36: /login?reset=true shows the reset-success banner', async ({ page }) => {
    await page.goto('/login?reset=true');

    await expect(page.getByRole('status')).toContainText('Your password has been reset');
});

/**
 * End-to-end checks of the admin page against the running stack (spec: B-19, US-ADMIN-001).
 *
 * An admin is made by promoting a registered account in the compose Postgres, because no route
 * grants the role; the promotion is the operator action the template expects.
 */
import { test, expect, type BrowserContext } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';

import { clearRateLimitCounters } from './rateLimitCounters';

test.beforeAll(() => {
    clearRateLimitCounters();
});

// This file's own client address, so it spends a rate-limit bucket no other spec shares.
const CLIENT_ADDRESS = '198.51.100.30';
test.use({ extraHTTPHeaders: { 'X-Forwarded-For': CLIENT_ADDRESS } });

const CSRF_HEADERS = { 'X-Requested-With': 'XMLHttpRequest' };
const passphrase = ['e2e', 'admin', 'passphrase', '5163'].join('-');

/** Return an address no earlier run registered. */
function buildUniqueEmailAddress(label: string): string {
    return `e2e-admin-${label}-${Date.now()}-${randomUUID().slice(0, 8)}@example.test`;
}

/** Register through the proxy, leaving this context signed in. */
async function registerThroughProxy(context: BrowserContext, email: string): Promise<void> {
    const response = await context.request.post('/api/v1/auth/register', {
        headers: CSRF_HEADERS,
        data: Object.fromEntries([
            ['email', email],
            ['password', passphrase],
        ]),
    });
    expect(response.status(), await response.text()).toBe(201);
}

/** Promote an account to admin in the compose Postgres. */
function promoteToAdmin(email: string): void {
    execFileSync('docker', [
        'compose',
        'exec',
        '-T',
        'postgres',
        'psql',
        '-U',
        'app',
        '-d',
        'app',
        '-c',
        `UPDATE users SET role = 'admin' WHERE email = '${email}'`,
    ]);
}

test('B-19: a member opening /admin lands on the dashboard', async ({ context, page }) => {
    await registerThroughProxy(context, buildUniqueEmailAddress('member'));

    await page.goto('/admin');

    await expect(page).toHaveURL(/\/dashboard$/);
});

test('B-19: an admin sees the user list', async ({ context, page }) => {
    const email = buildUniqueEmailAddress('admin');
    await registerThroughProxy(context, email);
    promoteToAdmin(email);

    await page.goto('/admin');

    await expect(page.getByRole('heading', { level: 1, name: 'Users' })).toBeVisible();
    await expect(page.getByRole('cell', { name: email })).toBeVisible();
});

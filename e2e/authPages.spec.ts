/**
 * End-to-end checks of the auth pages in a real browser against the running stack
 * (US-AUTH-003, US-AUTH-004; spec B-12, B-38, B-45, B-50, B-52).
 *
 * Accounts are created through the Nitro proxy with the browser context's own request client, so
 * the session cookie lands in that context's jar exactly as a form submission would put it there.
 * The auth rate-limit bucket allows ten requests per fifteen minutes per client; this file spends
 * three on its shared address and one on each of B-52's own addresses, and clears the counters
 * before it runs.
 */
import { test, expect, type BrowserContext, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';

import { clearRateLimitCounters } from './rateLimitCounters';

// Nitro's fixed compose address. Its own rate-limit bucket must never move (B-52).
const NITRO_ADDRESS = '172.28.0.10';
const CSRF_HEADERS = { 'X-Requested-With': 'XMLHttpRequest' };
const SESSION_COOKIE_NAME = 'sid';
const GLOBAL_BUCKET_PREFIX = 'ratelimit:global';
const SESSION_REQUEST_PATH = '/api/v1/auth/me';
// The backend requests one full load of /dashboard makes: the server render's session read.
const REQUESTS_PER_DASHBOARD_RENDER = 1;
// How long a page is watched for a request that should not come, after it has rendered.
const QUIET_PERIOD_MILLISECONDS = 750;
const passphrase = ['e2e', 'pages', 'passphrase', '6190'].join('-');
const replacementPassphrase = ['e2e', 'pages', 'replacement', '2754'].join('-');

/** Return an address no earlier run registered. */
function buildUniqueEmailAddress(label: string): string {
    return `e2e-pages-${label}-${Date.now()}-${randomUUID().slice(0, 8)}@example.test`;
}

/** Register through the proxy with this context's cookie jar, leaving the context signed in. */
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

/**
 * Log out through the proxy, then put the session cookie back into the jar.
 *
 * Logging out deletes the session row and answers with a `Set-Cookie` that expires the cookie, so
 * the browser would otherwise hold no cookie at all. Restoring it leaves exactly the case B-12
 * names: a cookie that is present and well formed but whose session the backend has revoked.
 */
async function revokeSessionKeepingCookie(context: BrowserContext): Promise<void> {
    const sessionCookies = (await context.cookies()).filter(
        (cookie) => cookie.name === SESSION_COOKIE_NAME,
    );
    expect(sessionCookies).toHaveLength(1);
    const response = await context.request.post('/api/v1/auth/logout', { headers: CSRF_HEADERS });
    expect(response.status(), await response.text()).toBe(204);
    await context.addCookies(sessionCookies);
    const restoredCookies = (await context.cookies()).filter(
        (cookie) => cookie.name === SESSION_COOKIE_NAME,
    );
    expect(restoredCookies.map((cookie) => cookie.value)).toEqual([sessionCookies[0]!.value]);
}

/** Run a redis-cli command in the compose Redis and return its trimmed output. */
function runRedisCommand(...args: string[]): string {
    const output = execFileSync('docker', ['compose', 'exec', '-T', 'redis', 'redis-cli', ...args]);
    return output.toString().trim();
}

/** Return whether the compose Redis holds a key. */
function hasRedisKey(key: string): boolean {
    return runRedisCommand('EXISTS', key) === '1';
}

/** Return a rate-limit counter's value, zero when the bucket has not been opened. */
function readBucketCount(key: string): number {
    return Number(runRedisCommand('GET', key)) || 0;
}

/** Navigate with the application's own router, without a document load. */
async function navigateClientSide(page: Page, path: string): Promise<void> {
    await page.evaluate(async (targetPath) => {
        const appRoot = document.querySelector('#__nuxt') as unknown as {
            __vue_app__: {
                config: { globalProperties: { $router: { push(to: string): Promise<unknown> } } };
            };
        };
        await appRoot.__vue_app__.config.globalProperties.$router.push(targetPath);
    }, path);
}

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
const CLIENT_ADDRESS = '198.51.100.10';
test.use({ extraHTTPHeaders: { 'X-Forwarded-For': CLIENT_ADDRESS } });

test.describe('the auth gate', () => {
    test('B-12: a signed-out browser loading /dashboard lands on /login', async ({ page }) => {
        await page.goto('/dashboard');

        await expect(page).toHaveURL(/\/login$/);
        await expect(page.getByRole('heading', { level: 1, name: 'Log in' })).toBeVisible();
    });

    test('B-45, B-50, B-12: one signed-in journey through the gate and the profile form', async ({
        context,
        page,
    }) => {
        // One account for all three, because each registration spends the shared auth bucket.
        await registerThroughProxy(context, buildUniqueEmailAddress('journey'));

        for (const signedOutPath of ['/login', '/register']) {
            await page.goto(signedOutPath);
            await expect(page).toHaveURL(/\/dashboard$/);
        }

        await fillField(page, 'Current password', passphrase);
        await fillField(page, 'New password', replacementPassphrase);
        await page.getByRole('button', { name: 'Change password' }).click();
        await expect(page.getByRole('status')).toContainText('Password changed');

        // Revoke the session on the backend but keep its cookie in the jar, then leave and return
        // through the client-side router. The cookie is still present, so only the route
        // middleware asking the backend (not the Nitro gate's presence check, and not a missing
        // cookie) can notice that the session behind it is gone.
        await revokeSessionKeepingCookie(context);
        await navigateClientSide(page, '/');
        await navigateClientSide(page, '/dashboard');
        await expect(page).toHaveURL(/\/login$/);
    });

    test('B-12, IAN-335: the browser asks for the session never on a full load of /dashboard and once per client-side navigation', async ({
        context,
        page,
    }) => {
        await registerThroughProxy(context, buildUniqueEmailAddress('count'));
        const sessionRequestUrls: string[] = [];
        page.on('request', (request) => {
            if (new URL(request.url()).pathname === SESSION_REQUEST_PATH) {
                sessionRequestUrls.push(request.url());
            }
        });

        const documentResponse = await page.goto('/dashboard');
        await expect(page.getByTestId('dashboard-email')).toBeVisible();
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(QUIET_PERIOD_MILLISECONDS);

        expect(documentResponse?.headers()['cache-control']).toBe('no-store');
        expect(sessionRequestUrls).toEqual([]);

        await navigateClientSide(page, '/');
        sessionRequestUrls.length = 0;
        await navigateClientSide(page, '/dashboard');
        await expect(page.getByTestId('dashboard-email')).toBeVisible();
        await page.waitForTimeout(QUIET_PERIOD_MILLISECONDS);

        expect(sessionRequestUrls).toHaveLength(1);
    });
});

test.describe('the auth forms', () => {
    test('B-38: an invalid email shows the field error beside the email input', async ({
        page,
    }) => {
        await page.goto('/register');

        await fillField(page, 'Email', 'no-at-sign');
        await fillField(page, 'Password', passphrase);
        await page.getByRole('button', { name: 'Create account' }).click();

        const emailInput = page.getByLabel('Email', { exact: true });
        await expect(emailInput).toHaveAttribute('aria-invalid', 'true');
        const describedById = await emailInput.getAttribute('aria-describedby');
        await expect(page.locator(`[id="${describedById}"]`)).toBeVisible();
        await expect(page).toHaveURL(/\/register$/);
    });
});

test('B-52: two overlapping server renders each reach FastAPI as their own user and address', async ({
    browser,
}) => {
    // Each user browses from a distinct address, so each one's global bucket is separately
    // observable and a render counted against the other user, or against Nitro, would show.
    const users = [
        { email: buildUniqueEmailAddress('first'), clientAddress: '198.51.100.21' },
        { email: buildUniqueEmailAddress('second'), clientAddress: '198.51.100.22' },
    ];
    const contexts = await Promise.all(
        users.map(({ clientAddress }) =>
            browser.newContext({ extraHTTPHeaders: { 'X-Forwarded-For': clientAddress } }),
        ),
    );
    await Promise.all(
        contexts.map((context, index) => registerThroughProxy(context, users[index]!.email)),
    );
    const pages = await Promise.all(contexts.map((context) => context.newPage()));
    const countsBeforeRender = users.map(({ clientAddress }) =>
        readBucketCount(`${GLOBAL_BUCKET_PREFIX}:${clientAddress}`),
    );

    // A barrier on the document requests: neither is released to Nitro until both have been
    // sent, so the two server renders are in flight together rather than one after the other.
    const releaseBarrier = openRequestBarrier(pages.length);
    await Promise.all(
        pages.map((page) =>
            page.route('**/dashboard', async (route) => {
                await releaseBarrier();
                await route.continue();
            }),
        ),
    );
    await Promise.all(pages.map((page) => page.goto('/dashboard')));

    for (const [index, page] of pages.entries()) {
        await expect(page.getByTestId('dashboard-email')).toContainText(users[index]!.email);
        await page.waitForLoadState('networkidle');
    }
    // Exactly one each: the server render's own session read. The browser hydrates from that
    // render and sends no API request of its own, so a larger count is a request the dedupe
    // should have spared, and a smaller one is a render counted somewhere else.
    for (const [index, { clientAddress }] of users.entries()) {
        expect(
            readBucketCount(`${GLOBAL_BUCKET_PREFIX}:${clientAddress}`),
            `the render for ${clientAddress} is counted once in its own bucket`,
        ).toBe(countsBeforeRender[index]! + REQUESTS_PER_DASHBOARD_RENDER);
    }
    expect(hasRedisKey(`${GLOBAL_BUCKET_PREFIX}:${NITRO_ADDRESS}`)).toBe(false);
    await Promise.all(contexts.map((context) => context.close()));
});

/** Return a wait that resolves for every caller once the given number of callers have arrived. */
function openRequestBarrier(expectedArrivals: number): () => Promise<void> {
    let arrivals = 0;
    let releaseAll: () => void = () => {};
    const released = new Promise<void>((resolve) => {
        releaseAll = resolve;
    });
    return async () => {
        arrivals += 1;
        if (arrivals === expectedArrivals) {
            releaseAll();
        }
        await released;
    };
}

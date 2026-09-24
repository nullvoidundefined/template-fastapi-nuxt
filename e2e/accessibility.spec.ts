/**
 * Accessibility checks of all seven pages against the running stack (spec B-27, B-48; slice 08).
 *
 * B-27: Lighthouse's accessibility category scores 100 on the landing, log-in, register,
 * forgot-password, reset-password (with a token in the link), dashboard, and admin pages. The
 * last two need a signed-in admin, and Lighthouse cannot sign in, so it is pointed at a Chromium
 * this file launches with a persistent profile and a debugging port: Lighthouse opens its tab in
 * that profile's one browser context, which already holds the session cookie the registration
 * set, and `disableStorageReset` keeps Lighthouse from clearing it.
 *
 * B-48: every page is fully operable by keyboard with a visible focus indicator, and with
 * `prefers-reduced-motion: reduce` nothing animates. Tabbing must reach every focusable control
 * on the page, each one must paint an outline or a shadow while focused, and a form must submit
 * from the keyboard alone.
 */
import { chromium, expect, test, type BrowserContext, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import lighthouse from 'lighthouse';

import { clearRateLimitCounters } from './rateLimitCounters';

test.beforeAll(() => {
    clearRateLimitCounters();
});

// This file's own client address, so it spends a rate-limit bucket no other spec shares.
const CLIENT_ADDRESS = '198.51.100.40';
test.use({ extraHTTPHeaders: { 'X-Forwarded-For': CLIENT_ADDRESS } });

type AuditResult = { failedAuditIds: string[]; score: number };

const webBaseUrl = process.env.WEB_BASE_URL ?? '';
const CSRF_HEADERS = { 'X-Requested-With': 'XMLHttpRequest' };
const passphrase = ['e2e', 'a11y', 'passphrase', '4827'].join('-');
const LIGHTHOUSE_TIMEOUT_MS = 240_000;
const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
].join(', ');
const TAB_STOP_ATTRIBUTE = 'data-e2e-tab-stop';

/** Return a reset-link query naming a token, built at run time; the page then shows its form. */
function buildResetLinkQuery(): string {
    return new URLSearchParams([['token', randomUUID()]]).toString();
}

const signedOutPaths = [
    '/',
    '/login',
    '/register',
    '/forgot-password',
    `/reset-password?${buildResetLinkQuery()}`,
];
const signedInPaths = ['/dashboard', '/admin'];

/** Return an address no earlier run registered. */
function buildUniqueEmailAddress(label: string): string {
    return `e2e-a11y-${label}-${Date.now()}-${randomUUID().slice(0, 8)}@example.test`;
}

/** Register through the proxy with this context's cookie jar, leaving the context signed in. */
async function registerThroughProxy(context: BrowserContext, email: string): Promise<void> {
    const response = await context.request.post(`${webBaseUrl}/api/v1/auth/register`, {
        headers: { ...CSRF_HEADERS, 'X-Forwarded-For': CLIENT_ADDRESS },
        data: Object.fromEntries([
            ['email', email],
            ['password', passphrase],
        ]),
    });
    expect(response.status(), await response.text()).toBe(201);
}

/** Promote an account to admin in the compose Postgres, the operator action no route offers. */
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

/** Register an account, promote it, and leave the context signed in as that admin. */
async function signInAsAdmin(context: BrowserContext): Promise<void> {
    const email = buildUniqueEmailAddress('admin');
    await registerThroughProxy(context, email);
    promoteToAdmin(email);
}

/** Return a local port nothing is listening on, for Chromium's debugging endpoint. */
async function findFreePort(): Promise<number> {
    return new Promise((resolvePort, rejectPort) => {
        const probeServer = createServer();
        probeServer.once('error', rejectPort);
        probeServer.listen(0, '127.0.0.1', () => {
            const address = probeServer.address();
            const port = typeof address === 'object' && address ? address.port : 0;
            probeServer.close(() => resolvePort(port));
        });
    });
}

/** Run Lighthouse's accessibility category on one page; return its score and failed audits. */
async function auditAccessibility(debuggingPort: number, path: string): Promise<AuditResult> {
    const runnerResult = await lighthouse(`${webBaseUrl}${path}`, {
        disableStorageReset: true,
        extraHeaders: { 'X-Forwarded-For': CLIENT_ADDRESS },
        logLevel: 'error',
        onlyCategories: ['accessibility'],
        port: debuggingPort,
    });
    expect(runnerResult, `Lighthouse returned no result for ${path}`).toBeDefined();
    const { audits, categories } = runnerResult!.lhr;
    const failedAuditIds = Object.values(audits)
        .filter((audit) => audit.scoreDisplayMode === 'binary' && audit.score === 0)
        .map((audit) => audit.id);
    return { failedAuditIds, score: Math.round((categories.accessibility?.score ?? 0) * 100) };
}

/** Audit each path in turn, keyed by path, so a failure names the page and its audits. */
async function auditPaths(
    debuggingPort: number,
    paths: string[],
): Promise<Record<string, AuditResult>> {
    const resultsByPath: Record<string, AuditResult> = {};
    for (const path of paths) {
        resultsByPath[path] = await auditAccessibility(debuggingPort, path);
    }
    return resultsByPath;
}

/** Return the perfect result for each path, the shape `auditPaths` must equal. */
function buildPerfectResults(paths: string[]): Record<string, AuditResult> {
    return Object.fromEntries(paths.map((path) => [path, { failedAuditIds: [], score: 100 }]));
}

/** Number each visible focusable control on the page; return how many there are. */
async function markTabStops(page: Page): Promise<number> {
    return page.evaluate(
        ({ attribute, selector }) => {
            const controls = [...document.querySelectorAll<HTMLElement>(selector)].filter(
                (control) => control.getClientRects().length > 0,
            );
            controls.forEach((control, index) => control.setAttribute(attribute, String(index)));
            return controls.length;
        },
        { attribute: TAB_STOP_ATTRIBUTE, selector: FOCUSABLE_SELECTOR },
    );
}

/** Describe the focused control: its tab-stop number and whether it paints a focus indicator. */
async function readFocusedControl(
    page: Page,
): Promise<{ hasFocusIndicator: boolean; tabStop: string | null }> {
    return page.evaluate((attribute) => {
        const focused = document.activeElement as HTMLElement | null;
        if (!focused || focused === document.body) {
            return { hasFocusIndicator: false, tabStop: null };
        }
        const { boxShadow, outlineStyle, outlineWidth } = getComputedStyle(focused);
        const hasOutline = outlineStyle !== 'none' && parseFloat(outlineWidth) > 0;
        return {
            hasFocusIndicator: hasOutline || boxShadow !== 'none',
            tabStop: focused.getAttribute(attribute),
        };
    }, TAB_STOP_ATTRIBUTE);
}

/** Tab through the page once; return how many stops were reached and those with no indicator. */
async function tabThroughPage(
    page: Page,
): Promise<{ reachedCount: number; stopsWithoutIndicator: string[]; totalCount: number }> {
    const totalCount = await markTabStops(page);
    const reachedStops = new Set<string>();
    const stopsWithoutIndicator: string[] = [];
    for (let pressCount = 0; pressCount < totalCount; pressCount += 1) {
        await page.keyboard.press('Tab');
        const { hasFocusIndicator, tabStop } = await readFocusedControl(page);
        if (tabStop === null) {
            continue;
        }
        reachedStops.add(tabStop);
        if (!hasFocusIndicator) {
            stopsWithoutIndicator.push(tabStop);
        }
    }
    return { reachedCount: reachedStops.size, stopsWithoutIndicator, totalCount };
}

/** Load a page and tab through it, asserting every control is reached and shows its focus. */
async function expectKeyboardOperable(page: Page, path: string): Promise<void> {
    await page.goto(path);
    await page.waitForLoadState('networkidle');

    const { reachedCount, stopsWithoutIndicator, totalCount } = await tabThroughPage(page);

    expect(totalCount, `${path} has no focusable control`).toBeGreaterThan(0);
    expect(reachedCount, `${path}: controls reached by Tab`).toBe(totalCount);
    expect(stopsWithoutIndicator, `${path}: controls with no focus indicator`).toEqual([]);
}

/** Return the animations and transitions running on the page right now. */
async function listRunningAnimations(page: Page): Promise<string[]> {
    return page.evaluate(() =>
        document
            .getAnimations()
            .filter((animation) => animation.playState === 'running')
            .map((animation) => {
                const target = (animation.effect as KeyframeEffect | null)?.target;
                return `${animation.constructor.name} on ${target?.nodeName ?? 'unknown'}`;
            }),
    );
}

/** Load a page, hover and focus every control, and assert nothing animates at any point. */
async function expectNoMotion(page: Page, path: string): Promise<void> {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    const totalCount = await markTabStops(page);
    for (let stopIndex = 0; stopIndex < totalCount; stopIndex += 1) {
        const control = page.locator(`[${TAB_STOP_ATTRIBUTE}="${stopIndex}"]`);
        await control.hover();
        await control.focus();
        expect(await listRunningAnimations(page), `${path}: stop ${stopIndex}`).toEqual([]);
    }
    expect(await listRunningAnimations(page), path).toEqual([]);
}

test.describe('B-27: Lighthouse accessibility', () => {
    test('every page scores 100, signed out and then as a signed-in admin', async () => {
        test.setTimeout(LIGHTHOUSE_TIMEOUT_MS);
        const profileDirectory = mkdtempSync(join(tmpdir(), 'e2e-lighthouse-'));
        const debuggingPort = await findFreePort();
        const context = await chromium.launchPersistentContext(profileDirectory, {
            args: [`--remote-debugging-port=${debuggingPort}`],
        });
        try {
            expect(await auditPaths(debuggingPort, signedOutPaths)).toEqual(
                buildPerfectResults(signedOutPaths),
            );

            await signInAsAdmin(context);

            expect(await auditPaths(debuggingPort, signedInPaths)).toEqual(
                buildPerfectResults(signedInPaths),
            );
        } finally {
            await context.close();
            rmSync(profileDirectory, { force: true, recursive: true });
        }
    });
});

test.describe('B-48: keyboard operability', () => {
    test('Tab reaches every control on the signed-out pages, each with a visible focus', async ({
        page,
    }) => {
        for (const path of signedOutPaths) {
            await expectKeyboardOperable(page, path);
        }
    });

    test('Tab reaches every control on the signed-in pages, each with a visible focus', async ({
        context,
        page,
    }) => {
        await signInAsAdmin(context);

        for (const path of signedInPaths) {
            await expectKeyboardOperable(page, path);
        }
    });

    test('the forgot-password form submits from the keyboard alone', async ({ page }) => {
        await page.goto('/forgot-password');
        await page.waitForLoadState('networkidle');

        await page.getByLabel('Email', { exact: true }).focus();
        await page.keyboard.type('keyboard-only-visitor@example.test');
        await page.keyboard.press('Enter');

        await expect(page.getByRole('status')).toContainText('Check your email');
    });
});

test.describe('B-48: reduced motion', () => {
    test.use({ reducedMotion: 'reduce' });

    test('no element animates on any page when the visitor prefers reduced motion', async ({
        context,
        page,
    }) => {
        for (const path of signedOutPaths) {
            await expectNoMotion(page, path);
        }

        await signInAsAdmin(context);

        for (const path of signedInPaths) {
            await expectNoMotion(page, path);
        }
    });
});

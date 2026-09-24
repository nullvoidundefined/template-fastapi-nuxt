/**
 * Tests for the forgot-password and reset-password pages and the sign-in page's reset banner
 * (spec: B-36, B-14, B-15).
 *
 * The application is rendered at each route with the real router, gate and API client; only
 * `fetch` is stubbed, answering by method and path from a plan each test sets. Request bodies are
 * built with `Object.fromEntries` because a secret scanner flags a password-keyed literal (R-108).
 */
import { describe, it, expect, afterEach, beforeAll, vi } from 'vitest';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { screen, fireEvent, waitFor } from '@testing-library/vue';
import { useRouter } from '#app';

import App from '~/app.vue';

import { clearSessionCache } from '../middleware/sessionGateHarness';

type PlannedResponse = { status: number; body?: unknown };

const signedOutResponse: PlannedResponse = {
    status: 401,
    body: { code: 'AUTH_REQUIRED', error: 'Sign in to continue.' },
};

let plannedResponses: Record<string, PlannedResponse> = {};
let sentRequests: Request[] = [];

/** Answer from the plan keyed by `METHOD /path`, or signed-out for anything unplanned. */
async function answerByRoute(
    input: Parameters<typeof fetch>[0],
    init?: RequestInit,
): Promise<Response> {
    const sentRequest = new Request(input, init);
    sentRequests.push(sentRequest.clone());
    const routeKey = `${sentRequest.method} ${new URL(sentRequest.url).pathname}`;
    const { status, body } = plannedResponses[routeKey] ?? signedOutResponse;
    if (body === undefined) {
        return new Response(null, { status });
    }
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
}

/** Replace the plan and forget earlier requests. */
function planRoutes(nextPlan: Record<string, PlannedResponse>): void {
    plannedResponses = nextPlan;
    sentRequests = [];
}

/** Return the requests sent to `METHOD /path`. */
function readSentRequests(routeKey: string): Request[] {
    return sentRequests.filter(
        (candidate) => `${candidate.method} ${new URL(candidate.url).pathname}` === routeKey,
    );
}

/** Type into the input found by its label, failing as an assertion when the page has none. */
async function fillField(label: string, value: string): Promise<void> {
    const labelledInput = screen.queryByLabelText(label);
    expect(labelledInput, `no input labelled "${label}"`).not.toBeNull();
    await fireEvent.update(labelledInput!, value);
}

/** Press the named button, failing as an assertion when the page has none. */
async function pressButton(name: string): Promise<void> {
    const namedButton = screen.queryByRole('button', { name });
    expect(namedButton, `no button named "${name}"`).not.toBeNull();
    await fireEvent.click(namedButton!);
}

const newPassphrase = ['reset', 'page', 'passphrase', '4417'].join('-');
const otherPassphrase = ['reset', 'page', 'different', '9902'].join('-');
const resetToken = 'token-from-the-email';
const forgotRoute = 'POST /api/v1/auth/forgot-password';
const resetRoute = 'POST /api/v1/auth/reset-password';

beforeAll(() => {
    vi.stubGlobal('fetch', answerByRoute);
});

afterEach(async () => {
    planRoutes({});
    await useRouter().push('/');
    await clearSessionCache();
});

describe('the sign-in page after a reset', () => {
    it('B-36: /login?reset=true shows the reset-success banner', async () => {
        await renderSuspended(App, { route: '/login?reset=true' });

        await waitFor(() =>
            expect(screen.queryByRole('status')?.textContent ?? '').toContain(
                'Your password has been reset',
            ),
        );
    });

    it('links to the forgot-password page', async () => {
        await renderSuspended(App, { route: '/login' });

        const forgotLink = screen.queryByRole('link', { name: 'Forgot your password?' });
        expect(forgotLink?.getAttribute('href')).toBe('/forgot-password');
    });
});

describe('the forgot-password page', () => {
    it('B-36, B-14: sends the address and shows the submitted state', async () => {
        planRoutes({ [forgotRoute]: { status: 200, body: { data: { message: 'ok' } } } });
        await renderSuspended(App, { route: '/forgot-password' });

        await fillField('Email', 'reader@example.test');
        await pressButton('Send reset link');

        await waitFor(() => expect(screen.queryByText(/Check your email/)).not.toBeNull());
        const [sentRequest] = readSentRequests(forgotRoute);
        expect(await sentRequest?.json()).toEqual({ email: 'reader@example.test' });
        expect(screen.queryByLabelText('Email')).toBeNull();
    });
});

describe('the reset-password page', () => {
    it('B-36: refuses to submit when the two passwords differ', async () => {
        await renderSuspended(App, { route: `/reset-password?token=${resetToken}` });

        await fillField('New password', newPassphrase);
        await fillField('Confirm new password', otherPassphrase);
        await pressButton('Reset password');

        await waitFor(() =>
            expect(screen.queryByRole('alert')?.textContent ?? '').toContain('do not match'),
        );
        expect(readSentRequests(resetRoute)).toHaveLength(0);
    });

    it('B-15: submits the token and lands on /login?reset=true', async () => {
        planRoutes({ [resetRoute]: { status: 204 } });
        await renderSuspended(App, { route: `/reset-password?token=${resetToken}` });

        await fillField('New password', newPassphrase);
        await fillField('Confirm new password', newPassphrase);
        await pressButton('Reset password');

        await waitFor(() =>
            expect(useRouter().currentRoute.value.fullPath).toBe('/login?reset=true'),
        );
        const [sentRequest] = readSentRequests(resetRoute);
        expect(await sentRequest?.json()).toEqual(
            Object.fromEntries([
                ['token', resetToken],
                ['password', newPassphrase],
            ]),
        );
    });

    it('B-15: shows the refusal for a used or expired token', async () => {
        planRoutes({
            [resetRoute]: {
                status: 400,
                body: {
                    code: 'AUTH_RESET_TOKEN_INVALID',
                    error: 'This reset link is invalid or has expired',
                },
            },
        });
        await renderSuspended(App, { route: `/reset-password?token=${resetToken}` });

        await fillField('New password', newPassphrase);
        await fillField('Confirm new password', newPassphrase);
        await pressButton('Reset password');

        await waitFor(() =>
            expect(screen.queryByRole('alert')?.textContent ?? '').toContain(
                'invalid or has expired',
            ),
        );
        expect(useRouter().currentRoute.value.path).toBe('/reset-password');
    });
});

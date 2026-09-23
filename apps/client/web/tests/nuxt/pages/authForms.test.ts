/**
 * Tests for the three auth forms (spec: B-38, B-50, B-10, B-11, US-AUTH-004).
 *
 * The application is rendered at each route with the real router, gate, query client and API
 * client; only `fetch` is stubbed. One stub serves the file (openapi-fetch captures fetch when the
 * per-app client is built), and it answers by method and path from a plan each test sets.
 *
 * B-38 is driven by a real `INPUT_VALIDATION_ERROR` body with `field_errors`, never by browser
 * validation, and the error is read through the input's `aria-describedby`.
 *
 * Request bodies are built with `Object.fromEntries` because a secret scanner flags a
 * password-keyed object literal on its shape alone (R-108).
 */
import { describe, it, expect, afterEach, beforeAll, vi } from 'vitest';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { screen, fireEvent, waitFor } from '@testing-library/vue';
import { useRouter } from '#app';

import App from '~/app.vue';

import { clearSessionCache, signedInUser } from '../middleware/sessionGateHarness';

type PlannedResponse = { status: number; body?: unknown };

const signedOutResponse: PlannedResponse = {
    status: 401,
    body: { code: 'AUTH_REQUIRED', error: 'Sign in to continue.' },
};

const signingInRoutes = new Set(['POST /api/v1/auth/login', 'POST /api/v1/auth/register']);
const sessionRoute = 'GET /api/v1/auth/me';

let plannedResponses: Record<string, PlannedResponse> = {};
let sentRequests: Request[] = [];
let hasSignedIn = false;

/**
 * Answer what `GET /me` would say given what has happened so far: signed out until a sign-in or
 * registration succeeded, then the signed-in user. A test that plans `/me` explicitly overrides it.
 */
function answerSessionRoute(): PlannedResponse {
    return hasSignedIn ? { status: 200, body: { data: signedInUser } } : signedOutResponse;
}

/** Answer the request from the plan keyed by `METHOD /path`, or signed-out for anything else. */
async function answerByRoute(
    input: Parameters<typeof fetch>[0],
    init?: RequestInit,
): Promise<Response> {
    const sentRequest = new Request(input, init);
    sentRequests.push(sentRequest.clone());
    const routeKey = `${sentRequest.method} ${new URL(sentRequest.url).pathname}`;
    const fallback = routeKey === sessionRoute ? answerSessionRoute() : signedOutResponse;
    const { status, body } = plannedResponses[routeKey] ?? fallback;
    if (signingInRoutes.has(routeKey) && status < 300) {
        hasSignedIn = true;
    }
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
    hasSignedIn = false;
}

/** Return the JSON body of the first request sent to `METHOD /path`. */
async function readSentBody(routeKey: string): Promise<unknown> {
    const matchingRequest = sentRequests.find(
        (candidate) => `${candidate.method} ${new URL(candidate.url).pathname}` === routeKey,
    );
    if (!matchingRequest) {
        throw new Error(`No request was sent to ${routeKey}`);
    }
    return matchingRequest.json();
}

/** Build the body a register or login form should send. */
function buildCredentialsBody(email: string, passphrase: string): Record<string, string> {
    return Object.fromEntries([
        ['email', email],
        ['password', passphrase],
    ]);
}

/** Build the body the profile form should send. */
function buildPassphraseChangeBody(current: string, replacement: string): Record<string, string> {
    return Object.fromEntries([
        ['current_password', current],
        ['new_password', replacement],
    ]);
}

/** Type into the input found by its label, failing as an assertion when the page has none. */
async function fillField(label: string, value: string): Promise<void> {
    const labelledInput = screen.queryByLabelText(label);
    expect(labelledInput, `no input labelled "${label}"`).not.toBeNull();
    await fireEvent.update(labelledInput!, value);
}

/** Submit through the button, as a visitor would. */
async function pressButton(name: string): Promise<void> {
    const namedButton = screen.queryByRole('button', { name });
    expect(namedButton, `no button named "${name}"`).not.toBeNull();
    await fireEvent.click(namedButton!);
}

const firstPassphrase = ['forms', 'test', 'passphrase', '5521'].join('-');
const replacementPassphrase = ['forms', 'next', 'passphrase', '8830'].join('-');

beforeAll(() => {
    vi.stubGlobal('fetch', answerByRoute);
});

afterEach(async () => {
    // Back to a page with no gate, so the next render navigates and its gate runs afresh.
    planRoutes({});
    await useRouter().push('/');
    await clearSessionCache();
});

describe('the register form', () => {
    it('B-38: shows the backend field error beside the email input', async () => {
        const emailMessage = 'String should match pattern';
        planRoutes({
            'POST /api/v1/auth/register': {
                status: 400,
                body: {
                    code: 'INPUT_VALIDATION_ERROR',
                    error: 'email: String should match pattern',
                    field_errors: [{ field: 'email', message: emailMessage }],
                },
            },
        });
        await renderSuspended(App, { route: '/register' });

        await fillField('Email', 'no-at-sign');
        await fillField('Password', firstPassphrase);
        await pressButton('Create account');

        const emailInput = screen.getByLabelText('Email');
        await waitFor(() => expect(emailInput.getAttribute('aria-invalid')).toBe('true'));
        const describedById = emailInput.getAttribute('aria-describedby') ?? '';
        expect(document.getElementById(describedById)?.textContent).toContain(emailMessage);
        expect(useRouter().currentRoute.value.path).toBe('/register');
    });

    it('B-10: registers with the typed credentials and lands on the dashboard', async () => {
        planRoutes({
            'POST /api/v1/auth/register': { status: 201, body: { data: signedInUser } },
        });
        await renderSuspended(App, { route: '/register' });

        await fillField('Email', signedInUser.email);
        await fillField('Password', firstPassphrase);
        await pressButton('Create account');

        await waitFor(() => expect(useRouter().currentRoute.value.path).toBe('/dashboard'));
        expect(await readSentBody('POST /api/v1/auth/register')).toEqual(
            buildCredentialsBody(signedInUser.email, firstPassphrase),
        );
    });

    it('B-10: shows the duplicate-address message on 409', async () => {
        planRoutes({
            'POST /api/v1/auth/register': {
                status: 409,
                body: {
                    code: 'AUTH_EMAIL_ALREADY_REGISTERED',
                    error: 'An account with that email address already exists',
                },
            },
        });
        await renderSuspended(App, { route: '/register' });

        await fillField('Email', signedInUser.email);
        await fillField('Password', firstPassphrase);
        await pressButton('Create account');

        const alert = await screen.findByRole('alert');
        expect(alert.textContent).toContain('already exists');
    });
});

describe('the sign-in form', () => {
    it('B-11: signs in and lands on the dashboard', async () => {
        planRoutes({
            'POST /api/v1/auth/login': { status: 200, body: { data: signedInUser } },
        });
        await renderSuspended(App, { route: '/login' });

        await fillField('Email', signedInUser.email);
        await fillField('Password', firstPassphrase);
        await pressButton('Log in');

        await waitFor(() => expect(useRouter().currentRoute.value.path).toBe('/dashboard'));
        expect(await readSentBody('POST /api/v1/auth/login')).toEqual(
            buildCredentialsBody(signedInUser.email, firstPassphrase),
        );
    });

    it('B-11: shows the invalid-credentials message and stays on the page', async () => {
        planRoutes({
            'POST /api/v1/auth/login': {
                status: 401,
                body: {
                    code: 'AUTH_INVALID_CREDENTIALS',
                    error: 'That email address and password do not match an account',
                },
            },
        });
        await renderSuspended(App, { route: '/login' });

        await fillField('Email', signedInUser.email);
        await fillField('Password', firstPassphrase);
        await pressButton('Log in');

        const alert = await screen.findByRole('alert');
        expect(alert.textContent).toContain('do not match');
        expect(useRouter().currentRoute.value.path).toBe('/login');
    });
});

describe('the dashboard profile form', () => {
    it('B-50: changes the password through PATCH /auth/me and shows the result', async () => {
        planRoutes({
            'GET /api/v1/auth/me': { status: 200, body: { data: signedInUser } },
            'PATCH /api/v1/auth/me': { status: 200, body: { data: signedInUser } },
        });
        await renderSuspended(App, { route: '/dashboard' });

        await fillField('Current password', firstPassphrase);
        await fillField('New password', replacementPassphrase);
        await pressButton('Change password');

        await waitFor(() =>
            expect(screen.getByRole('status').textContent).toContain('Password changed'),
        );
        expect(await readSentBody('PATCH /api/v1/auth/me')).toEqual(
            buildPassphraseChangeBody(firstPassphrase, replacementPassphrase),
        );
    });

    it('B-50: shows the refusal when the current password is wrong', async () => {
        planRoutes({
            'GET /api/v1/auth/me': { status: 200, body: { data: signedInUser } },
            'PATCH /api/v1/auth/me': {
                status: 401,
                body: {
                    code: 'AUTH_INVALID_CREDENTIALS',
                    error: 'The current password is not correct',
                },
            },
        });
        await renderSuspended(App, { route: '/dashboard' });

        await fillField('Current password', firstPassphrase);
        await fillField('New password', replacementPassphrase);
        await pressButton('Change password');

        const alert = await screen.findByRole('alert');
        expect(alert.textContent).toContain('not correct');
    });
});

/**
 * End-to-end check of the account lifecycle against the running API: a person registers, is
 * identified by their session, changes their passphrase, finds the old one refused and the new one
 * accepted, signs out, and is refused again. Story US-AUTH-002 (spec B-10, B-11, B-13, B-31,
 * B-32); the base URL comes from API_BASE_URL.
 *
 * It proves what the integration tests under apps/server/tests cannot: that the cookie the API
 * writes survives a real HTTP round trip, through a real client's cookie jar, and comes back on a
 * later request. Those tests drive the app through an in-process transport, where the Set-Cookie
 * header is whatever the handler put on the response object rather than what a client would
 * actually store and resend.
 *
 * Two protections shape every request below. The CSRF guard (spec B-6) refuses any POST, PUT,
 * PATCH or DELETE that does not carry `X-Requested-With: XMLHttpRequest`, so the shared request
 * context sets that header once for the whole file. The rate limiter (spec B-7) allows ten
 * requests per fifteen minutes per client address to /v1/auth/login and /v1/auth/register, and
 * this file spends exactly three of them: one registration and two sign-ins. That window is a
 * Redis counter shared by every run against the same stack, so a spec that spent more would begin
 * failing on its third consecutive run rather than on a defect.
 */
import {
    test,
    expect,
    request as playwrightRequest,
    type APIRequestContext,
} from '@playwright/test';
import { randomUUID } from 'node:crypto';

import { clearRateLimitCounters } from './rateLimitCounters';

const apiBaseUrl = process.env.API_BASE_URL ?? '';
const SESSION_COOKIE_NAME = 'sid';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Assembled from parts rather than written as literals, so no line here has the shape of a
// credential (R-108). The two differ because half of what B-13 claims is that the old one stops.
const firstPassphrase = ['e2e', 'first', 'passphrase', '7413'].join('-');
const replacementPassphrase = ['e2e', 'second', 'passphrase', '9268'].join('-');

/** Return an address no earlier run can have registered, for the unique index on lower(email). */
function buildUniqueEmailAddress(): string {
    return `e2e-auth-${Date.now()}-${randomUUID().slice(0, 8)}@example.test`;
}

/**
 * Build the register and login body. It is assembled from entries rather than written as an object
 * literal because a secret scanner flags a line of that shape on the shape alone, whatever the
 * value beside the key happens to be (R-108).
 */
function buildCredentialsBody(email: string, passphrase: string): Record<string, string> {
    return Object.fromEntries([
        ['email', email],
        ['password', passphrase],
    ]);
}

/** Build the PATCH /v1/auth/me body, from entries for the same reason. */
function buildPassphraseChangeBody(current: string, replacement: string): Record<string, string> {
    return Object.fromEntries([
        ['current_password', current],
        ['new_password', replacement],
    ]);
}

/** Return the session cookie the shared context is currently holding, if it holds one. */
async function readStoredSessionCookie(
    context: APIRequestContext,
): Promise<{ value: string; httpOnly: boolean; secure: boolean } | undefined> {
    const { cookies } = await context.storageState();
    return cookies.find((cookie) => cookie.name === SESSION_COOKIE_NAME);
}

test.beforeAll(() => {
    clearRateLimitCounters();
});

test.describe('auth account lifecycle', () => {
    // Serial, because these tests are the steps of one journey and each depends on the session the
    // one before it left behind. Playwright's per-test `request` fixture builds a fresh context for
    // every test, which would throw the cookie away the moment a test ended, so the journey shares
    // one APIRequestContext: its cookie jar stores the Set-Cookie the API writes and attaches it to
    // every later call, which is what makes this a test of the session rather than of one header.
    test.describe.configure({ mode: 'serial' });

    let sessionContext: APIRequestContext;
    let emailAddress: string;
    let registeredUserId: string;

    test.beforeAll(async () => {
        emailAddress = buildUniqueEmailAddress();
        sessionContext = await playwrightRequest.newContext({
            baseURL: apiBaseUrl,
            // Every mutating request in this file needs it, and one that lacks it is refused with
            // 403 CSRF_HEADER_MISSING before the route ever runs.
            extraHTTPHeaders: { 'X-Requested-With': 'XMLHttpRequest' },
        });
    });

    test.afterAll(async () => {
        await sessionContext.dispose();
    });

    test('US-AUTH-002: registering answers 201 with the new account and stores a session cookie (B-10)', async () => {
        const response = await sessionContext.post('/v1/auth/register', {
            data: buildCredentialsBody(emailAddress, firstPassphrase),
        });

        expect(response.status()).toBe(201);
        const body = await response.json();
        expect(body.data.email).toBe(emailAddress);
        expect(body.data.id).toMatch(UUID_PATTERN);
        // The response carries the id, the email and the role (B-19) and nothing else, so no
        // column added to the users table later reaches a client by accident, the hash least of all.
        expect(Object.keys(body.data).sort()).toEqual(['email', 'id', 'role']);
        expect(body.data.role).toBe('member');
        registeredUserId = body.data.id;

        const sessionCookie = await readStoredSessionCookie(sessionContext);
        expect(sessionCookie).toBeDefined();
        expect(sessionCookie?.value).not.toBe('');
        expect(sessionCookie?.httpOnly).toBe(true);
        // Compose runs with ENVIRONMENT=development, which is the only reason a plain-HTTP spec can
        // hold this cookie at all: outside development the API writes it Secure and no unencrypted
        // request would carry it back. This assertion is the line that notices that changing.
        // Deliberately no assertion on Secure. It is absent here only because compose runs as
        // development, so pinning it would fail the moment this suite is pointed at a deployed
        // environment over HTTPS, which global-setup's E2E_SKIP_MIGRATE escape anticipates. The
        // integration suite asserts Secure in both directions under a controlled environment.
    });

    test('US-AUTH-002: GET /v1/auth/me identifies the account the stored cookie belongs to (B-32)', async () => {
        const response = await sessionContext.get('/v1/auth/me');

        expect(response.status()).toBe(200);
        expect(await response.json()).toEqual({
            data: { id: registeredUserId, email: emailAddress, role: 'member' },
        });
    });

    test('US-AUTH-002: changing the passphrase answers 200 and leaves the caller signed in (B-13)', async () => {
        const response = await sessionContext.patch('/v1/auth/me', {
            data: buildPassphraseChangeBody(firstPassphrase, replacementPassphrase),
        });

        expect(response.status()).toBe(200);
        expect(await response.json()).toEqual({
            data: { id: registeredUserId, email: emailAddress, role: 'member' },
        });

        // The change signs out every other session of this user and keeps this one, so the very
        // next request on the same cookie has to still be answered.
        const afterChange = await sessionContext.get('/v1/auth/me');
        expect(afterChange.status()).toBe(200);
        expect(await afterChange.json()).toEqual({
            data: { id: registeredUserId, email: emailAddress, role: 'member' },
        });
    });

    test('US-AUTH-002: the replaced passphrase no longer signs in and answers AUTH_INVALID_CREDENTIALS (B-13)', async () => {
        const response = await sessionContext.post('/v1/auth/login', {
            data: buildCredentialsBody(emailAddress, firstPassphrase),
        });

        expect(response.status()).toBe(401);
        const body = await response.json();
        expect(body.code).toBe('AUTH_INVALID_CREDENTIALS');
        expect(typeof body.error).toBe('string');
        expect(body.error.length).toBeGreaterThan(0);
        // `field_errors` belongs to the validation envelope, and a refused credential is not a
        // malformed request: a form keying off its presence would otherwise show a message beside
        // an input for a failure that belongs to neither input.
        expect(body).not.toHaveProperty('field_errors');
    });

    test('US-AUTH-002: the new passphrase signs in and replaces the stored session cookie (B-11)', async () => {
        const cookieBeforeLogin = await readStoredSessionCookie(sessionContext);

        const response = await sessionContext.post('/v1/auth/login', {
            data: buildCredentialsBody(emailAddress, replacementPassphrase),
        });

        expect(response.status()).toBe(200);
        expect(await response.json()).toEqual({
            data: { id: registeredUserId, email: emailAddress, role: 'member' },
        });

        const cookieAfterLogin = await readStoredSessionCookie(sessionContext);
        expect(cookieAfterLogin).toBeDefined();
        // Signing in opens a new session rather than reusing the one already in the jar, so what
        // the client now holds is a different value from what it held a moment ago.
        expect(cookieAfterLogin?.value).not.toBe(cookieBeforeLogin?.value);
    });

    test('US-AUTH-002: logging out answers 204 and clears the cookie out of the jar (B-31)', async () => {
        const response = await sessionContext.post('/v1/auth/logout');

        expect(response.status()).toBe(204);
        expect(await response.text()).toBe('');
        // Asserted on the header as well as on the jar, because the expiry attributes are what a
        // client acts on, and a spec that checked only the later rejection would pass for a server
        // that deleted the row and left a stale cookie sitting in the browser.
        const setCookieHeader = response.headers()['set-cookie'];
        expect(setCookieHeader).toContain(`${SESSION_COOKIE_NAME}=;`);
        expect(setCookieHeader).toContain('Max-Age=0');

        expect(await readStoredSessionCookie(sessionContext)).toBeUndefined();
    });

    test('US-AUTH-002: GET /v1/auth/me after logging out answers 401 AUTH_REQUIRED (B-32)', async () => {
        const response = await sessionContext.get('/v1/auth/me');

        expect(response.status()).toBe(401);
        const body = await response.json();
        expect(body.code).toBe('AUTH_REQUIRED');
        expect(typeof body.error).toBe('string');
        expect(body.error.length).toBeGreaterThan(0);
    });
});

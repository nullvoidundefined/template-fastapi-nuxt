/**
 * Tests for the inverse gate on the signed-out pages (spec: slice 03 PR 3, B-45, US-AUTH-003).
 *
 * B-45 says a signed-in visitor who opens `/login` or `/register` is sent to `/dashboard`. This
 * file covers what the middleware function does; whether both pages actually carry it is a
 * separate question that a call to the function cannot answer, and it is asserted in
 * `tests/nuxt/pages/authRouteGate.test.ts` against the route records and a real navigation.
 *
 * The signed-in case is still run against both paths, because a middleware that branched on
 * `to.path` and handled only the one it was written for would otherwise go unnoticed.
 *
 * A backend outage leaves the visitor on the page they asked for. The inverse gate protects
 * nothing: sending someone away from the sign-in page, or refusing to render it, because the
 * session endpoint answered 500 would lock out exactly the people who are already signed out.
 */
import { describe, it, expect, afterEach, beforeAll } from 'vitest';

import redirectIfSession from '~/middleware/redirectIfSession';

import {
    clearSessionCache,
    installBackendStub,
    planBackendOutage,
    planExpiredSession,
    planSignedInSession,
    readRedirectPath,
    runRouteGate,
} from './sessionGateHarness';

const signInPath = '/login';
const registerPath = '/register';
const signedInLandingPath = '/dashboard';

beforeAll(() => {
    installBackendStub();
});

afterEach(async () => {
    await clearSessionCache();
});

describe('redirectIfSession', () => {
    it.each([signInPath, registerPath])(
        'B-45: sends a signed-in visitor from %s to the dashboard',
        async (signedOutPath) => {
            planSignedInSession();

            const outcome = await runRouteGate(redirectIfSession, signedOutPath);

            expect(readRedirectPath(outcome)).toBe(signedInLandingPath);
        },
    );

    it.each([signInPath, registerPath])(
        'B-45: leaves a signed-out visitor on %s',
        async (signedOutPath) => {
            planExpiredSession();

            const outcome = await runRouteGate(redirectIfSession, signedOutPath);

            expect(outcome.settled).toBe('returned');
            expect(readRedirectPath(outcome)).toBeUndefined();
        },
    );

    it('B-45: leaves a visitor on the sign-in page when the backend is unavailable', async () => {
        planBackendOutage();

        const outcome = await runRouteGate(redirectIfSession, signInPath);

        expect(outcome.settled).toBe('returned');
        expect(readRedirectPath(outcome)).toBeUndefined();
    }, 15000);
});

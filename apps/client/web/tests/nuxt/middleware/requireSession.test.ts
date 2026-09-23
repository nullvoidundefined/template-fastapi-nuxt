/**
 * Tests for the protected-route gate (spec: slice 03 PR 3, B-12, story US-AUTH-003).
 *
 * The middleware is invoked the way Nuxt's router plugin invokes it, through the harness: marked
 * as processing middleware and run inside the Nuxt context. That matters for the assertions,
 * because `navigateTo` only returns its target instead of performing the navigation while a
 * middleware pass is in progress, and because the middleware resolves its query client and its API
 * client from the Nuxt app rather than from a component.
 *
 * Four behaviours, and the last one is the reason this file exists rather than an end-to-end spec
 * alone. A gate that reads whatever the cache already holds passes the first three tests and fails
 * the fourth, which is exactly the defect the slice plan names: an expired session would navigate
 * the whole protected area freely until the cache entry went stale on its own.
 *
 * The 500 case is the second reason. Treating any failed session read as "signed out" turns a
 * backend outage into a mass sign-out, which nobody notices until it happens in production. The
 * status is what separates the two, so the gate redirects only on 401 and aborts the navigation
 * with a server error otherwise: it neither signs the visitor out nor lets an unverified visitor
 * into a protected page.
 */
import { describe, it, expect, afterEach, beforeAll } from 'vitest';
import { isNuxtError } from '#app';

import requireSession from '~/middleware/requireSession';
import { sessionQueryKey } from '~/composables/useSessionQuery';

import {
    clearSessionCache,
    installBackendStub,
    planBackendOutage,
    planExpiredSession,
    planSignedInSession,
    readAppQueryClient,
    readRedirectPath,
    readSentRequests,
    runRouteGate,
    seedCachedSession,
    signedInUser,
} from './sessionGateHarness';

const protectedPath = '/dashboard';
const signInPath = '/login';
const firstServerErrorStatus = 500;

beforeAll(() => {
    installBackendStub();
});

afterEach(async () => {
    await clearSessionCache();
});

describe('requireSession', () => {
    it('B-12: sends a visitor whose session the backend rejects to the sign-in page', async () => {
        planExpiredSession();

        const outcome = await runRouteGate(requireSession, protectedPath);

        expect(readRedirectPath(outcome)).toBe(signInPath);
    });

    it('B-12: aborts with a server error on a backend outage rather than signing the visitor out', async () => {
        planBackendOutage();

        const outcome = await runRouteGate(requireSession, protectedPath);

        expect(readRedirectPath(outcome)).toBeUndefined();
        expect(outcome.settled).toBe('threw');
        const abortError = outcome.settled === 'threw' ? outcome.error : undefined;
        expect(isNuxtError(abortError)).toBe(true);
        expect((abortError as { statusCode?: number }).statusCode).toBeGreaterThanOrEqual(
            firstServerErrorStatus,
        );
    }, 15000);

    it('B-12: lets a signed-in visitor through and leaves the session under the shared key', async () => {
        planSignedInSession();

        const outcome = await runRouteGate(requireSession, protectedPath);

        expect(outcome.settled).toBe('returned');
        expect(readRedirectPath(outcome)).toBeUndefined();
        const queryClient = await readAppQueryClient();
        expect(queryClient.getQueryData(sessionQueryKey)).toEqual(signedInUser);
    });

    it('B-12: revalidates a cached session, so an expired one is redirected rather than trusted', async () => {
        await seedCachedSession(signedInUser);
        planExpiredSession();

        const outcome = await runRouteGate(requireSession, protectedPath);

        expect(readSentRequests()).not.toHaveLength(0);
        expect(new URL(readSentRequests()[0]!.url).pathname).toBe('/api/v1/auth/me');
        expect(readRedirectPath(outcome)).toBe(signInPath);
    });
});

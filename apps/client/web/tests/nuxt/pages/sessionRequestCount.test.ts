/**
 * Counts the `GET /v1/auth/me` requests one navigation sends (IAN-335, spec: B-12, B-32).
 *
 * The gate revalidates the session on every navigation, and the protected layout and the dashboard
 * page both read it through `useSessionQuery`. Each of those is correct on its own, and together
 * they asked the backend two or three times per page load: once from the middleware, once more
 * when the components mounted, and on a full page load once more from the middleware re-running
 * during hydration after the server had already asked. Every one of those requests draws on the
 * global rate-limit bucket, so the count is the behavior under test, read from the requests the
 * backend stub actually received.
 *
 * The client-side case renders the real application at `/dashboard`, so the router runs the real
 * middleware and the real layout and page mount. The hydration cases run the gate the way Nuxt
 * runs it on the browser's first pass over a page, with a session already in the cache: fresh
 * from the server, old enough that only a replayed render could carry it, or on a page the server
 * never rendered. Only the first may skip the request.
 */
import { describe, it, expect, afterEach, beforeAll, beforeEach, vi } from 'vitest';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { flushPromises } from '@vue/test-utils';
import { useNuxtApp, useRouter } from '#app';

import App from '~/app.vue';
import redirectIfSession from '~/middleware/redirectIfSession';
import requireSession from '~/middleware/requireSession';
import { sessionQueryKey } from '~/composables/useSessionQuery';

import {
    clearSessionCache,
    installBackendStub,
    planExpiredSession,
    planSignedInSession,
    readAppQueryClient,
    readRedirectPath,
    readSentRequests,
    runRouteGate,
    seedCachedSession,
    signedInUser,
} from '../middleware/sessionGateHarness';

const dashboardPath = '/dashboard';
const signInPath = '/login';
const sessionPath = '/v1/auth/me';
// Ten minutes: far older than any render a browser hydrates as it arrives.
const staleRenderAgeMilliseconds = 10 * 60 * 1000;

/** Return how many of the requests the backend received asked for the session. */
function countSessionRequests(): number {
    return readSentRequests().filter((request) =>
        new URL(request.url).pathname.endsWith(sessionPath),
    ).length;
}

/** Wait until no query is in flight, so a refetch a mount started has been counted. */
async function waitForQueriesToSettle(): Promise<void> {
    const queryClient = await readAppQueryClient();
    await flushPromises();
    await vi.waitFor(() => {
        expect(queryClient.isFetching()).toBe(0);
    });
    await flushPromises();
}

/**
 * Run the callback while the Nuxt app reports a first pass over a page, server-rendered unless
 * the caller says otherwise (a client-only page hydrates with `serverRendered` false).
 */
async function runWhileHydratingServerRender<T>(
    callback: () => Promise<T>,
    isServerRendered = true,
): Promise<T> {
    const nuxtApp = useNuxtApp();
    const { isHydrating: wasHydrating } = nuxtApp;
    const { serverRendered: wasServerRendered } = nuxtApp.payload;
    nuxtApp.isHydrating = true;
    nuxtApp.payload.serverRendered = isServerRendered;
    try {
        return await callback();
    } finally {
        nuxtApp.isHydrating = wasHydrating;
        nuxtApp.payload.serverRendered = wasServerRendered;
    }
}

beforeAll(() => {
    installBackendStub();
});

beforeEach(async () => {
    planExpiredSession();
    await useRouter().push('/');
});

afterEach(async () => {
    await clearSessionCache();
});

describe('the session requests one navigation sends', () => {
    it('B-12, B-32: a client-side navigation to the dashboard asks for the session once, not once per reader', async () => {
        planSignedInSession();

        await renderSuspended(App, { route: dashboardPath });
        await waitForQueriesToSettle();

        expect(useRouter().currentRoute.value.path).toBe(dashboardPath);
        expect(countSessionRequests()).toBe(1);
    });

    it('B-12: hydrating a server-rendered dashboard reuses the session the server fetched instead of asking again', async () => {
        await seedCachedSession(signedInUser);
        planSignedInSession();

        const outcome = await runWhileHydratingServerRender(() =>
            runRouteGate(requireSession, dashboardPath),
        );

        expect(readRedirectPath(outcome)).toBeUndefined();
        expect(countSessionRequests()).toBe(0);
    });

    it('B-12, IAN-335: hydrating an old render replayed from the HTTP cache revalidates the stale session and redirects', async () => {
        const queryClient = await readAppQueryClient();
        queryClient.setQueryData(sessionQueryKey, signedInUser, {
            updatedAt: Date.now() - staleRenderAgeMilliseconds,
        });
        planExpiredSession();

        const outcome = await runWhileHydratingServerRender(() =>
            runRouteGate(requireSession, dashboardPath),
        );

        expect(readRedirectPath(outcome)).toBe(signInPath);
        expect(countSessionRequests()).toBe(1);
    });

    it('B-12, IAN-335: a session dated after the browser clock is not recent, so a replay under a lagging clock still revalidates', async () => {
        const queryClient = await readAppQueryClient();
        // A server clock ahead of the browser's makes an old render look younger than zero.
        queryClient.setQueryData(sessionQueryKey, signedInUser, {
            updatedAt: Date.now() + staleRenderAgeMilliseconds,
        });
        planExpiredSession();

        const outcome = await runWhileHydratingServerRender(() =>
            runRouteGate(requireSession, dashboardPath),
        );

        expect(readRedirectPath(outcome)).toBe(signInPath);
        expect(countSessionRequests()).toBe(1);
    });

    it('B-12: hydrating a page the server did not render still asks, so an expired session redirects', async () => {
        await seedCachedSession(signedInUser);
        planExpiredSession();

        const outcome = await runWhileHydratingServerRender(
            () => runRouteGate(requireSession, dashboardPath),
            false,
        );

        expect(readRedirectPath(outcome)).toBe(signInPath);
        expect(countSessionRequests()).toBe(1);
    });

    it('B-45: hydrating a server-rendered sign-in page does not ask for the session again', async () => {
        planExpiredSession();

        const outcome = await runWhileHydratingServerRender(() =>
            runRouteGate(redirectIfSession, signInPath),
        );

        expect(readRedirectPath(outcome)).toBeUndefined();
        expect(countSessionRequests()).toBe(0);
    });
});

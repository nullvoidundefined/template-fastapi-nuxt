/**
 * Tests for the session query composable (spec: slice 03 PR 3, B-12 and B-32).
 *
 * The composable owns the query key: components and the sign-out mutation refer to the session
 * through the exported key rather than rebuilding it, so the assertions below are made on the query
 * cache the mounted component actually used. The cache is read through the client the component
 * resolves in setup rather than through a client the test holds, because the Nuxt test environment
 * runs the app's own plugins and a component resolves whichever client the app provides.
 *
 * The second test is the one the gate depends on. `requireSession` redirects when the backend
 * answers 401, so the composable has to leave the query in an error state carrying an
 * `ApiRequestError` with the status, rather than resolving with an error-shaped value: openapi-fetch
 * does not throw on an HTTP error, so a query function that returned its result unexamined would
 * make a rejected session look like a signed-in one.
 *
 * One fetch stub serves the whole file and is installed before the first mount, which is a
 * constraint of what the client captures and when. openapi-fetch reads `globalThis.fetch` once,
 * when `createApiClient` builds the client, and `useApiClient()` memoizes one client per Nuxt app
 * instance, which `mountSuspended` shares across every test in a file. The first mount in the file
 * therefore decides which fetch every later call goes through: a second `vi.stubGlobal` in the
 * second test would never be consulted, and that test would silently assert against the first
 * test's response. Only the response the stub is told to answer with changes between tests, so the
 * memoization under review in the client itself is exercised rather than worked around.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import {
    QueryClient,
    VueQueryPlugin,
    useQueryClient,
    type VueQueryPluginOptions,
} from '@tanstack/vue-query';
import { mountSuspended } from '@nuxt/test-utils/runtime';

import { buildQueryClientOptions } from '~/config/queryClient';
import { sessionQueryKey, useSessionQuery } from '~/composables/useSessionQuery';
import { ApiRequestError } from '~/services/apiClient/apiRequestError';

type PlannedResponse = {
    status: number;
    body: unknown;
};

const signedInUser = { id: '8f4a2f6e-0d5c-4a9b-9a4d-3d6f5e2c1b0a', email: 'reader@example.test' };

let plannedResponse: PlannedResponse = { status: 200, body: { data: signedInUser } };
let sentRequests: Request[] = [];
let observedQueryClient: QueryClient | undefined;

const SessionProbe = defineComponent({
    name: 'SessionProbe',
    setup() {
        observedQueryClient = useQueryClient();
        useSessionQuery();
        return () => h('div', { 'data-test-id': 'session-probe' });
    },
});

/** Record the request and answer whatever the running test planned. */
async function answerPlannedResponse(
    input: Parameters<typeof fetch>[0],
    init?: RequestInit,
): Promise<Response> {
    sentRequests.push(new Request(input, init));
    const { status, body } = plannedResponse;
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
}

/** Set what the backend answers next, and start a fresh record of what it was sent. */
function planBackendResponse(planned: PlannedResponse): void {
    plannedResponse = planned;
    sentRequests = [];
}

/** Mount the probe with a query client configured the way the application configures one. */
async function mountSessionProbe(): Promise<void> {
    const vueQueryInstall: [typeof VueQueryPlugin, VueQueryPluginOptions] = [
        VueQueryPlugin,
        { queryClient: new QueryClient(buildQueryClientOptions()) },
    ];
    await mountSuspended(SessionProbe, { global: { plugins: [vueQueryInstall] } });
}

/** Return the query client the mounted component resolved, failing loudly when it had none. */
function readObservedQueryClient(): QueryClient {
    if (!observedQueryClient) {
        throw new Error('The session probe was never mounted, so no query client was resolved');
    }
    return observedQueryClient;
}

beforeEach(() => {
    vi.stubGlobal('fetch', answerPlannedResponse);
});

afterEach(() => {
    observedQueryClient?.clear();
    observedQueryClient = undefined;
    vi.unstubAllGlobals();
});

describe('useSessionQuery', () => {
    it('B-32: caches the signed-in user under the key the composable exports', async () => {
        planBackendResponse({ status: 200, body: { data: signedInUser } });

        await mountSessionProbe();

        const queryClient = readObservedQueryClient();
        await vi.waitFor(() => {
            expect(queryClient.getQueryData(sessionQueryKey)).toEqual(signedInUser);
        });
        expect(sentRequests).toHaveLength(1);
        expect(new URL(sentRequests[0]!.url).pathname).toBe('/api/v1/auth/me');
        expect(
            queryClient
                .getQueryCache()
                .getAll()
                .map((cachedQuery) => cachedQuery.queryKey),
        ).toEqual([sessionQueryKey]);
    });

    it('B-12: leaves the query in error with the 401 the gate reads, rather than resolving', async () => {
        planBackendResponse({
            status: 401,
            body: { code: 'AUTH_SESSION_EXPIRED', error: 'Your session has expired.' },
        });

        await mountSessionProbe();

        const queryClient = readObservedQueryClient();
        await vi.waitFor(
            () => {
                expect(queryClient.getQueryState(sessionQueryKey)?.status).toBe('error');
            },
            { timeout: 2000 },
        );
        const queryError = queryClient.getQueryState(sessionQueryKey)?.error;
        expect(queryError).toBeInstanceOf(ApiRequestError);
        expect((queryError as ApiRequestError).status).toBe(401);
        expect((queryError as ApiRequestError).code).toBe('AUTH_SESSION_EXPIRED');
        expect(queryClient.getQueryData(sessionQueryKey)).toBeUndefined();
    });
});

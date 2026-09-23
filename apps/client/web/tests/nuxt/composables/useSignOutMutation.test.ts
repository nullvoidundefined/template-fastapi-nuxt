/**
 * Tests for the sign-out mutation (spec: slice 03 PR 3, B-31, and the Nuxt track's auth gating,
 * which requires that the mutation's `onSuccess` removes the session query from the cache).
 *
 * The session lives in the query cache rather than in a store, so removing that entry is what signs
 * the interface out: a protected layout renders against the session query, and leaving a resolved
 * session in the cache after a successful sign-out leaves the signed-out visitor looking at their
 * own name. The assertions are therefore made on the contents of the cache the mounted component
 * used, not on whether a removal function was called, and they check that the entry is gone from
 * the cache rather than merely holding undefined, since a query reset to undefined would refetch
 * and repopulate on the next mount.
 *
 * The failure case pins `onSuccess` rather than `onSettled`: a sign-out the backend refused has not
 * ended the session, so the cached session has to survive it.
 *
 * One fetch stub serves the whole file and is installed before the first mount, which is a
 * constraint of what the client captures and when. openapi-fetch reads `globalThis.fetch` once,
 * when `createApiClient` builds the client, and `useApiClient()` memoizes one client per Nuxt app
 * instance, which `mountSuspended` shares across every test in a file. The first mount in the file
 * therefore decides which fetch every later call goes through: a stub installed per test would be
 * ignored by the client the first test built, and a mount before any stub would hand Node's own
 * fetch a happy-dom `Request` it cannot parse. Only the response the stub is told to answer with
 * changes between tests.
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
import { sessionQueryKey } from '~/composables/useSessionQuery';
import { useSignOutMutation } from '~/composables/useSignOutMutation';
import { ApiRequestError } from '~/services/apiClient/apiRequestError';

type PlannedResponse = {
    status: number;
    body?: unknown;
};

const signedInUser = { id: '8f4a2f6e-0d5c-4a9b-9a4d-3d6f5e2c1b0a', email: 'reader@example.test' };
const unrelatedQueryKey = ['dashboard', 'summary'];
const unrelatedQueryData = { openInvoices: 2 };

let plannedResponse: PlannedResponse = { status: 204 };
let sentRequests: Request[] = [];
let observedQueryClient: QueryClient | undefined;
let observedSignOutMutation: ReturnType<typeof useSignOutMutation> | undefined;

const SignOutProbe = defineComponent({
    name: 'SignOutProbe',
    setup() {
        observedQueryClient = useQueryClient();
        observedSignOutMutation = useSignOutMutation();
        return () => h('button', { type: 'button', 'data-test-id': 'sign-out' }, 'Sign out');
    },
});

/** Record the request and answer whatever the running test planned. */
async function answerPlannedResponse(
    input: Parameters<typeof fetch>[0],
    init?: RequestInit,
): Promise<Response> {
    sentRequests.push(new Request(input, init));
    const { status, body } = plannedResponse;
    if (body === undefined) {
        return new Response(null, { status });
    }
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
async function mountSignOutProbe(): Promise<void> {
    const vueQueryInstall: [typeof VueQueryPlugin, VueQueryPluginOptions] = [
        VueQueryPlugin,
        { queryClient: new QueryClient(buildQueryClientOptions()) },
    ];
    await mountSuspended(SignOutProbe, { global: { plugins: [vueQueryInstall] } });
}

/** Return the query client the mounted component resolved, failing loudly when it had none. */
function readObservedQueryClient(): QueryClient {
    if (!observedQueryClient) {
        throw new Error('The sign-out probe was never mounted, so no query client was resolved');
    }
    return observedQueryClient;
}

/** Return the mutation the mounted component created, failing loudly when it has none. */
function readObservedSignOutMutation(): ReturnType<typeof useSignOutMutation> {
    if (!observedSignOutMutation) {
        throw new Error('The sign-out probe was never mounted, so no mutation was created');
    }
    return observedSignOutMutation;
}

/** Fill the cache the way a signed-in page would have filled it. */
function cacheSignedInSession(queryClient: QueryClient): void {
    queryClient.setQueryData(sessionQueryKey, signedInUser);
    queryClient.setQueryData(unrelatedQueryKey, unrelatedQueryData);
}

/** Await the call and return whatever it rejected with, or undefined when it resolved. */
async function captureRejection(runCall: () => Promise<unknown>): Promise<unknown> {
    try {
        await runCall();
        return undefined;
    } catch (rejection) {
        return rejection;
    }
}

beforeEach(() => {
    vi.stubGlobal('fetch', answerPlannedResponse);
});

afterEach(() => {
    observedQueryClient?.clear();
    observedQueryClient = undefined;
    observedSignOutMutation = undefined;
    vi.unstubAllGlobals();
});

describe('useSignOutMutation', () => {
    it('B-31: posts the sign-out and removes the session query from the cache', async () => {
        planBackendResponse({ status: 204 });
        await mountSignOutProbe();
        const queryClient = readObservedQueryClient();
        cacheSignedInSession(queryClient);

        await readObservedSignOutMutation().mutateAsync();

        expect(sentRequests).toHaveLength(1);
        expect(new URL(sentRequests[0]!.url).pathname).toBe('/api/v1/auth/logout');
        expect(sentRequests[0]!.method).toBe('POST');
        expect(queryClient.getQueryData(sessionQueryKey)).toBeUndefined();
        expect(queryClient.getQueryCache().find({ queryKey: sessionQueryKey })).toBeUndefined();
        expect(queryClient.getQueryData(unrelatedQueryKey)).toEqual(unrelatedQueryData);
    });

    it('B-31: keeps the cached session when the backend refuses the sign-out', async () => {
        planBackendResponse({
            status: 500,
            body: { code: 'SERVER_INTERNAL_ERROR', error: 'Something went wrong.' },
        });
        await mountSignOutProbe();
        const queryClient = readObservedQueryClient();
        cacheSignedInSession(queryClient);

        const rejection = await captureRejection(() => readObservedSignOutMutation().mutateAsync());

        expect(rejection).toBeInstanceOf(ApiRequestError);
        expect((rejection as ApiRequestError).status).toBe(500);
        expect(queryClient.getQueryData(sessionQueryKey)).toEqual(signedInUser);
        expect(queryClient.getQueryCache().find({ queryKey: sessionQueryKey })).toBeDefined();
    });
});

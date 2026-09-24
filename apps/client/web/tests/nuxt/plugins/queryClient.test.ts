/**
 * Tests for the query client plugin as it runs in the browser (spec: slice 03 PR 3, review focus:
 * "no client or QueryClient is constructed at module scope").
 *
 * The first test is the one that matters. On the server a Nuxt app instance is a request, so a
 * `QueryClient` built at module scope outlives the request that filled it and the next
 * server-rendered page starts with the previous visitor's session in its cache. The test runs one
 * import of the plugin against two Nuxt app instances, exactly as two concurrent renders would, and
 * asserts both that the installed clients are different objects and that data written into one is
 * absent from the other. Importing the module once is deliberate: re-importing it per run would
 * reset module-level state and let a module-scope client pass.
 *
 * The second test covers the browser half of the server-to-client handover, driving the plugin
 * against a payload that has been through `JSON` the way Nuxt's payload goes over the wire, and
 * proving the hydrated entry then answers a read without a network request. The server half lives
 * in `queryClient.server.test.ts`, because the two halves need different `import.meta` values and
 * those are fixed when a module is evaluated.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { QueryClient, dehydrate } from '@tanstack/vue-query';
import { useNuxtApp, useState } from '#app';

import queryClientPlugin from '~/plugins/queryClient';

import {
    createStubNuxtApp,
    readInstalledQueryClient,
    runQueryClientPlugin,
} from './queryClientPluginHarness';

const signedInUser = { id: '8f4a2f6e-0d5c-4a9b-9a4d-3d6f5e2c1b0a', email: 'reader@example.test' };
const otherSignedInUser = {
    id: '1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f',
    email: 'other@example.test',
};
const cachedSessionKey = ['plugin-probe', 'session'];
const dehydratedStateKey = 'vue-query';

/** Stub fetch to record every request and answer with the other user, returning the record. */
function stubFetchRespondingWithOtherUser(): Request[] {
    const sentRequests: Request[] = [];
    vi.stubGlobal('fetch', async (input: Parameters<typeof fetch>[0], init?: RequestInit) => {
        sentRequests.push(new Request(input, init));
        return new Response(JSON.stringify({ data: otherSignedInUser }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
        });
    });
    return sentRequests;
}

/** Write the payload a server render would have left for the browser. */
async function seedServerRenderedPayload(dehydratedState: unknown): Promise<void> {
    await useNuxtApp().runWithContext(() => {
        useState<unknown>(dehydratedStateKey, () => null).value = dehydratedState;
    });
}

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('the query client plugin', () => {
    it('installs one QueryClient per Nuxt app instance, never one shared by every request', async () => {
        const firstRequest = createStubNuxtApp();
        const secondRequest = createStubNuxtApp();

        await runQueryClientPlugin(queryClientPlugin, firstRequest);
        await runQueryClientPlugin(queryClientPlugin, secondRequest);

        const firstRequestClient = readInstalledQueryClient(firstRequest.vueApp);
        const secondRequestClient = readInstalledQueryClient(secondRequest.vueApp);
        expect(firstRequestClient).toBeInstanceOf(QueryClient);
        expect(secondRequestClient).not.toBe(firstRequestClient);

        firstRequestClient.setQueryData(cachedSessionKey, signedInUser);

        expect(firstRequestClient.getQueryData(cachedSessionKey)).toEqual(signedInUser);
        expect(secondRequestClient.getQueryData(cachedSessionKey)).toBeUndefined();
    });

    it('IAN-335: hydrates the payload during plugin setup, before app:created starts the initial navigation and its gate', async () => {
        const serverRenderedClient = new QueryClient();
        serverRenderedClient.setQueryData(cachedSessionKey, signedInUser);
        const transferredPayload: unknown = JSON.parse(
            JSON.stringify(dehydrate(serverRenderedClient)),
        );
        await seedServerRenderedPayload(transferredPayload);
        const browserRequest = createStubNuxtApp();

        // Nuxt's router plugin runs the initial navigation, route middleware included, from its
        // own app:created hook, which is registered before this plugin's; so the hook is not fired.
        await runQueryClientPlugin(queryClientPlugin, browserRequest);

        const hydratedClient = readInstalledQueryClient(browserRequest.vueApp);
        expect(hydratedClient.getQueryData(cachedSessionKey)).toEqual(signedInUser);
    });

    it('hydrates the server-rendered payload into the cache instead of refetching it', async () => {
        const serverRenderedClient = new QueryClient();
        serverRenderedClient.setQueryData(cachedSessionKey, signedInUser);
        const transferredPayload: unknown = JSON.parse(
            JSON.stringify(dehydrate(serverRenderedClient)),
        );
        await seedServerRenderedPayload(transferredPayload);
        const browserRequest = createStubNuxtApp();

        await runQueryClientPlugin(queryClientPlugin, browserRequest);
        await browserRequest.callHook('app:created');

        const hydratedClient = readInstalledQueryClient(browserRequest.vueApp);
        expect(hydratedClient.getQueryData(cachedSessionKey)).toEqual(signedInUser);

        const sentRequests = stubFetchRespondingWithOtherUser();
        const sessionFromCache = await hydratedClient.ensureQueryData({
            queryKey: cachedSessionKey,
            queryFn: async () => (await fetch('/api/v1/auth/me')).json(),
            staleTime: 60_000,
        });

        expect(sessionFromCache).toEqual(signedInUser);
        expect(sentRequests).toHaveLength(0);
    });
});

/**
 * Tests for the query client plugin as it runs during server-side rendering (spec: slice 03 PR 3).
 *
 * The server branch runs because the file sets Vitest's `import.meta` defines to the server values
 * before the plugin module is imported, the technique `tests/nuxt/composables/useApiClient.server.test.ts`
 * uses. The defines are fixed when a module is evaluated rather than read at call time, so the
 * plugin is imported inside the test, after the defines are set, and the browser half of the
 * handover lives in its own file rather than here.
 *
 * What this asserts is the server end of the handover: once the page has rendered, the request's
 * cache is written into the `vue-query` payload state, and that payload survives the JSON
 * serialization Nuxt puts it through and rehydrates into a fresh client carrying the same user.
 * A page rendered with the session already fetched therefore reaches the browser with the session,
 * rather than with an empty cache that fetches it a second time.
 *
 * The gap this file does not close: there is no real server-to-browser handover here. Nitro is not
 * running, the server render is a plugin invocation with `import.meta.server` simulated, and the
 * payload is read back in the same process. The end-to-end proof that a server-rendered page does
 * not refetch belongs to the Playwright specs, which count the requests the backend actually
 * receives.
 */
import { describe, it, expect, afterAll, beforeAll } from 'vitest';
import { QueryClient, hydrate } from '@tanstack/vue-query';
import { useNuxtApp, useState } from '#app';

import {
    createStubNuxtApp,
    readInstalledQueryClient,
    runQueryClientPlugin,
} from './queryClientPluginHarness';

type VitestWorkerState = { metaDefines?: Record<string, unknown> };

const signedInUser = { id: '8f4a2f6e-0d5c-4a9b-9a4d-3d6f5e2c1b0a', email: 'reader@example.test' };
const cachedSessionKey = ['plugin-probe', 'session'];
const dehydratedStateKey = 'vue-query';

/** Return Vitest's per-module `import.meta` defines, failing loudly if the internal moved. */
function readMetaDefines(): Record<string, unknown> {
    const workerState = (globalThis as { __vitest_worker__?: VitestWorkerState }).__vitest_worker__;
    if (!workerState) {
        throw new Error('Vitest worker state is missing; cannot run the server branch');
    }
    workerState.metaDefines ??= {};
    return workerState.metaDefines;
}

/** Read the payload state a server render leaves behind for the browser. */
async function readServerRenderedPayload(): Promise<unknown> {
    return useNuxtApp().runWithContext(
        () => useState<unknown>(dehydratedStateKey, () => null).value,
    );
}

const originalMetaDefines: Record<string, unknown> = {};

beforeAll(() => {
    const metaDefines = readMetaDefines();
    Object.assign(originalMetaDefines, { server: metaDefines.server, client: metaDefines.client });
    Object.assign(metaDefines, { server: true, client: false });
});

afterAll(() => {
    Object.assign(readMetaDefines(), originalMetaDefines);
});

describe('the query client plugin on the server', () => {
    it('dehydrates the request cache into the payload once the page has rendered', async () => {
        const { default: queryClientPlugin } = await import('~/plugins/queryClient');
        const serverRequest = createStubNuxtApp();
        await runQueryClientPlugin(queryClientPlugin, serverRequest);
        const requestClient = readInstalledQueryClient(serverRequest.vueApp);
        requestClient.setQueryData(cachedSessionKey, signedInUser);

        await serverRequest.callHook('app:rendered');

        const serverRenderedPayload = await readServerRenderedPayload();
        expect(serverRenderedPayload).not.toBeNull();

        const browserClient = new QueryClient();
        hydrate(browserClient, JSON.parse(JSON.stringify(serverRenderedPayload)));
        expect(browserClient.getQueryData(cachedSessionKey)).toEqual(signedInUser);
    });
});

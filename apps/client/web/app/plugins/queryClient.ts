/**
 * Installs one query client per request and carries its cache to the browser (slice 03 PR 3).
 *
 * The client is built inside the plugin, never at module scope. A Nuxt app instance is one request
 * on the server, so a module-scope client would outlive the request that filled it and the next
 * server-rendered page would start holding the previous visitor's session. This is the review
 * focus the slice plan names, and the plugin test drives two app instances to prove it.
 *
 * The handover is the other half: the server writes the request's cache into the payload once the
 * page has rendered, and the browser seeds its own client from that payload before anything
 * mounts, so a server-rendered page shows what the server already fetched rather than fetching it
 * a second time.
 */
import { QueryClient, VueQueryPlugin, dehydrate, hydrate } from '@tanstack/vue-query';
import type { DehydratedState } from '@tanstack/vue-query';
import { defineNuxtPlugin, useState } from '#app';

import { buildQueryClientOptions } from '~/config/queryClient';

const DEHYDRATED_STATE_KEY = 'vue-query';

export default defineNuxtPlugin((nuxtApp) => {
    const queryClient = new QueryClient(buildQueryClientOptions());
    const dehydratedState = useState<DehydratedState | null>(DEHYDRATED_STATE_KEY, () => null);
    nuxtApp.vueApp.use(VueQueryPlugin, { queryClient });
    // Neither hook is guarded by `import.meta`, because each one already runs on exactly one
    // side: `app:rendered` fires only during a server render, and on the server the payload is
    // still null when `app:created` fires, so hydrating from it there is a no-op rather than a
    // branch to maintain.
    nuxtApp.hooks.hook('app:created', () => {
        if (dehydratedState.value) {
            hydrate(queryClient, dehydratedState.value);
        }
    });
    nuxtApp.hooks.hook('app:rendered', () => {
        dehydratedState.value = dehydrate(queryClient);
    });
});

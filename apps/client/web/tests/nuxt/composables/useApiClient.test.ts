/**
 * Nuxt runtime tests for the browser client (spec: Architecture, "Request path").
 * Calls run in the Nuxt app context, as they do during component setup. Fetch is stubbed
 * before client creation so the real typed client exposes its URL and outgoing headers.
 * runWithContext is typed to return the callback's value or a promise of it, so each call is
 * awaited; awaiting a non-promise yields the same object, which keeps the identity check exact.
 * useNuxtApp is wrapped in a spy that keeps the real implementation, so one test can hand the
 * composable two distinct app objects and tell per-app memoization from a module-level client.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { mockNuxtImport } from '@nuxt/test-utils/runtime';
import { type NuxtApp, useNuxtApp } from '#app';

mockNuxtImport('useNuxtApp', (originalUseNuxtApp) => vi.fn(originalUseNuxtApp));

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('useApiClient', () => {
    it('Request path: browser requests use /api/health without forwarded headers', async () => {
        const sentRequests: Request[] = [];
        vi.stubGlobal('fetch', async (input: Parameters<typeof fetch>[0], init?: RequestInit) => {
            sentRequests.push(new Request(input, init));
            return new Response(JSON.stringify({ status: 'ok' }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        });
        const { useApiClient } = await import('~/composables/useApiClient');
        const apiClient = await useNuxtApp().runWithContext(() => useApiClient());

        await apiClient.GET('/health');

        expect(sentRequests).toHaveLength(1);
        expect(new URL(sentRequests[0]!.url).pathname).toMatch(/^\/api\/health/);
        expect(sentRequests[0]?.headers.get('cookie')).toBeNull();
        expect(sentRequests[0]?.headers.get('X-Forwarded-For')).toBeNull();
    });

    it('Request path: memoizes the identical client within one Nuxt app instance', async () => {
        const { useApiClient } = await import('~/composables/useApiClient');
        const nuxtApp = useNuxtApp();

        const firstClient = await nuxtApp.runWithContext(() => useApiClient());
        const secondClient = await nuxtApp.runWithContext(() => useApiClient());

        expect(firstClient).toBeDefined();
        expect(secondClient).toBe(firstClient);
    });

    it('Request path: memoizes one client per Nuxt app instance, never one shared by every instance', async () => {
        const { useApiClient } = await import('~/composables/useApiClient');
        const firstNuxtApp = {} as NuxtApp;
        const secondNuxtApp = {} as NuxtApp;
        vi.mocked(useNuxtApp)
            .mockReturnValueOnce(firstNuxtApp)
            .mockReturnValueOnce(firstNuxtApp)
            .mockReturnValueOnce(secondNuxtApp)
            .mockReturnValueOnce(secondNuxtApp);

        const firstAppClient = useApiClient();
        const firstAppRepeatClient = useApiClient();
        const secondAppClient = useApiClient();
        const secondAppRepeatClient = useApiClient();

        expect(firstAppRepeatClient).toBe(firstAppClient);
        expect(secondAppRepeatClient).toBe(secondAppClient);
        expect(secondAppClient).not.toBe(firstAppClient);
    });
});

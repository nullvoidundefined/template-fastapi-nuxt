/**
 * Nuxt runtime tests for the browser client (spec: Architecture, "Request path").
 * Calls run in the Nuxt app context, as they do during component setup. Fetch is stubbed
 * before client creation so the real typed client exposes its URL and outgoing headers.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { useNuxtApp } from '#app';

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
        const apiClient = useNuxtApp().runWithContext(() => useApiClient());

        await apiClient.GET('/health');

        expect(sentRequests).toHaveLength(1);
        expect(new URL(sentRequests[0]!.url).pathname).toMatch(/^\/api\/health/);
        expect(sentRequests[0]?.headers.get('cookie')).toBeNull();
        expect(sentRequests[0]?.headers.get('X-Forwarded-For')).toBeNull();
    });

    it('Request path: memoizes the identical client within one Nuxt app instance', async () => {
        const { useApiClient } = await import('~/composables/useApiClient');
        const nuxtApp = useNuxtApp();

        const firstClient = nuxtApp.runWithContext(() => useApiClient());
        const secondClient = nuxtApp.runWithContext(() => useApiClient());

        expect(firstClient).toBeDefined();
        expect(secondClient).toBe(firstClient);
    });
});

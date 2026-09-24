/**
 * Tests that the typed API client tags the browser's Sentry scope with the backend's request ID
 * (spec: the Frontend feature map's Observability row, the Nuxt track's Sentry section, R-341).
 *
 * Every backend response echoes `X-Request-Id`, and a browser error reported after a call should
 * carry that ID so the report joins the backend's log lines for the same request. `@sentry/nuxt`
 * is replaced at its module boundary and each assertion reads the tag it was handed after a real
 * openapi-fetch call against a stubbed backend.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';

const sentryTags = vi.hoisted(() => [] as Array<[string, unknown]>);

vi.mock('@sentry/nuxt', () => ({
    setTag: (name: string, value: unknown) => {
        sentryTags.push([name, value]);
    },
}));

const backendRequestId = 'req-01J8Z1.backend_7';

/** Answer every request with the given headers and an empty body. */
function stubBackend(responseHeaders: Record<string, string>): void {
    vi.stubGlobal(
        'fetch',
        async () =>
            new Response(JSON.stringify({ data: { status: 'ok' } }), {
                status: 200,
                headers: { 'Content-Type': 'application/json', ...responseHeaders },
            }),
    );
}

beforeEach(() => {
    sentryTags.length = 0;
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('the request ID tag on API responses', () => {
    it('R-341: a response carrying X-Request-Id tags the Sentry scope with it', async () => {
        stubBackend({ 'X-Request-Id': backendRequestId });
        const { createApiClient } = await import('~/api/apiClient');

        await createApiClient({ baseUrl: 'http://api.test' }).GET('/health');

        expect(sentryTags).toEqual([['request_id', backendRequestId]]);
    });

    it('R-341: each response retags the scope, so the latest request ID wins', async () => {
        const plannedRequestIds = ['req-first', undefined, 'req-third'];
        vi.stubGlobal('fetch', async () => {
            const requestId = plannedRequestIds.shift();
            return new Response('{}', {
                status: 200,
                headers: requestId ? { 'X-Request-Id': requestId } : {},
            });
        });
        const { createApiClient } = await import('~/api/apiClient');
        const apiClient = createApiClient({ baseUrl: 'http://api.test' });
        await apiClient.GET('/health');
        await apiClient.GET('/health');

        await apiClient.GET('/health');

        expect(sentryTags).toEqual([
            ['request_id', 'req-first'],
            ['request_id', 'req-third'],
        ]);
    });
});

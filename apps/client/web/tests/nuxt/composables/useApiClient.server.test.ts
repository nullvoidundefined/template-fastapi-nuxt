// @vitest-environment node
/**
 * Tests for the server-side client (spec: Architecture, "Request path" and "Client IP trust
 * chain"). They run in the node environment, because mocking useNuxtApp would break the Nuxt
 * environment's own setup. The composable's server branch runs because Vitest copies its
 * `import.meta.*` defines onto each module's `import.meta` when the module is evaluated, so the
 * file sets `server` true before importing the composable, which no other import here loads. The Nuxt
 * composables the client reads are mocked, the page request is a fixture that also carries
 * headers the client must never forward, and fetch is stubbed before each client is created, so
 * the real typed client exposes its URL and the exact outgoing headers.
 */
import { describe, it, expect, afterAll, afterEach, beforeAll, vi } from 'vitest';
import { mockNuxtImport } from '@nuxt/test-utils/runtime';

type PageRequestHeaders = Record<string, string>;
type VitestWorkerState = { metaDefines?: Record<string, unknown> };

const pageRequestFixture = vi.hoisted(() => ({
    headers: {} as Record<string, string>,
}));

const pageRequestHeadersWithForwardedFor: PageRequestHeaders = {
    cookie: 'session=abc',
    'x-request-id': 'req-page-001',
    'x-forwarded-for': '1.1.1.1, 203.0.113.7',
    authorization: 'untrusted',
    host: 'page.test',
};

mockNuxtImport('useNuxtApp', () => () => ({}));
mockNuxtImport('useRuntimeConfig', () => () => ({ apiBaseUrl: 'http://api.test' }));
mockNuxtImport('useRequestHeaders', () => (headerNames?: string[]) => {
    const pageHeaders = pageRequestFixture.headers;
    if (!headerNames) {
        return { ...pageHeaders };
    }
    return Object.fromEntries(
        headerNames
            .filter((headerName) => headerName in pageHeaders)
            .map((headerName) => [headerName, pageHeaders[headerName]]),
    );
});
mockNuxtImport('useRequestEvent', () => () => ({
    node: { req: { socket: { remoteAddress: '192.0.2.9' } } },
}));

/** Return Vitest's per-module `import.meta` defines, failing loudly if the internal moved. */
function readMetaDefines(): Record<string, unknown> {
    const workerState = (globalThis as { __vitest_worker__?: VitestWorkerState }).__vitest_worker__;
    if (!workerState) {
        throw new Error('Vitest worker state is missing; cannot run the server branch');
    }
    workerState.metaDefines ??= {};
    return workerState.metaDefines;
}

/** Stub fetch to record every request and answer 200, returning the recorded list. */
function recordSentRequests(): Request[] {
    const sentRequests: Request[] = [];
    vi.stubGlobal('fetch', async (input: Parameters<typeof fetch>[0], init?: RequestInit) => {
        sentRequests.push(new Request(input, init));
        return new Response(JSON.stringify({ status: 'ok' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
        });
    });
    return sentRequests;
}

/** Return every header on the request as a plain object with lowercased names. */
function readHeaderEntries(sentRequest: Request): Record<string, string> {
    return Object.fromEntries(sentRequest.headers.entries());
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

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('useApiClient on the server', () => {
    it('Request path: calls apiBaseUrl directly and forwards only the cookie, request ID, and edge address', async () => {
        pageRequestFixture.headers = { ...pageRequestHeadersWithForwardedFor };
        const sentRequests = recordSentRequests();
        const { useApiClient } = await import('~/composables/useApiClient');

        await useApiClient().GET('/health');

        expect(sentRequests).toHaveLength(1);
        expect(sentRequests[0]!.url).toBe('http://api.test/health');
        expect(readHeaderEntries(sentRequests[0]!)).toEqual({
            cookie: 'session=abc',
            'x-request-id': 'req-page-001',
            'x-forwarded-for': '203.0.113.7',
            'x-requested-with': 'XMLHttpRequest',
        });
        expect(sentRequests[0]!.headers.get('authorization')).toBeNull();
        expect(sentRequests[0]!.headers.get('host')).toBeNull();
    });

    it('Client IP trust chain: forwards the socket address when the page request has no X-Forwarded-For', async () => {
        const { 'x-forwarded-for': _omittedForwardedFor, ...headersWithoutForwardedFor } =
            pageRequestHeadersWithForwardedFor;
        pageRequestFixture.headers = headersWithoutForwardedFor;
        const sentRequests = recordSentRequests();
        const { useApiClient } = await import('~/composables/useApiClient');

        await useApiClient().GET('/health');

        expect(sentRequests).toHaveLength(1);
        expect(sentRequests[0]!.url).toBe('http://api.test/health');
        expect(readHeaderEntries(sentRequests[0]!)).toEqual({
            cookie: 'session=abc',
            'x-request-id': 'req-page-001',
            'x-forwarded-for': '192.0.2.9',
            'x-requested-with': 'XMLHttpRequest',
        });
    });
});

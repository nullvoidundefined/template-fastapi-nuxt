// @vitest-environment node
/**
 * Tests for the PostHog ingestion proxy `server/api/ingest/[...path].ts` (spec: B-24, the Nuxt
 * track's Proxies section, slice 07).
 *
 * The browser's PostHog SDK sends to its own origin under `/api/ingest`, so ad blockers that drop
 * requests to PostHog's domain let it through, and this route forwards each request to
 * `runtimeConfig.posthogHost` with its path, query string, and body. It never forwards the
 * session cookie: PostHog has no use for it, and a proxy that passed it would hand a third party
 * the credential of every signed-in visitor.
 *
 * The harness is the one `apiProxy.test.ts` documents: a real h3 app with the route table Nitro
 * builds from `server/api/`, the Nitro auto-imports stubbed as globals, `useRuntimeConfig`
 * replaced through `mockNuxtImport` because the app auto-import transform rewrites it, and only
 * the upstream replaced, through the global fetch `proxyRequest` resolves at call time.
 */
import {
    createApp,
    createError,
    createRouter,
    defineEventHandler,
    eventHandler,
    getHeader,
    getMethod,
    getProxyRequestHeaders,
    getQuery,
    getRequestHeader,
    getRequestHeaders,
    getRequestIP,
    getRequestPath,
    getRequestURL,
    getRouterParam,
    getRouterParams,
    proxyRequest,
    readBody,
    readRawBody,
    sendProxy,
    setResponseHeader,
    setResponseStatus,
    toWebHandler,
    type EventHandler,
} from 'h3';
import { describe, it, expect, afterAll, beforeEach, vi } from 'vitest';
import { mockNuxtImport } from '@nuxt/test-utils/runtime';

type UpstreamRequest = {
    url: string;
    method: string;
    headers: Headers;
    body: string | undefined;
};

// Hoisted, because the mockNuxtImport factory below is lifted above these declarations.
const backendBaseUrl = vi.hoisted(() => 'http://api.test');
const posthogHost = vi.hoisted(() => 'https://posthog.test');
// Built from parts so no credential-shaped literal is written down (R-108).
const sessionCookie = ['sid=', ['issued', 'by', 'the', 'backend'].join('-')].join('');

mockNuxtImport('useRuntimeConfig', () => () => ({ apiBaseUrl: backendBaseUrl, posthogHost }));

const upstreamRequests: UpstreamRequest[] = [];

/** Read the forwarded request body, which h3 hands to fetch as a buffer. */
function readOutgoingBody(body: RequestInit['body']): string | undefined {
    if (body === undefined || body === null) {
        return undefined;
    }
    if (typeof body === 'string') {
        return body;
    }
    return Buffer.from(body as Uint8Array).toString('utf8');
}

/** Record every outgoing request and answer 200, standing in for PostHog and FastAPI alike. */
function stubUpstream(): void {
    vi.stubGlobal(
        'fetch',
        async (target: string | URL | Request, options?: RequestInit): Promise<Response> => {
            upstreamRequests.push({
                url: String(target),
                method: options?.method ?? 'GET',
                headers: new Headers((options?.headers ?? {}) as HeadersInit),
                body: readOutgoingBody(options?.body),
            });
            return new Response('{}', {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        },
    );
}

/** Put the Nitro auto-imports on globalThis, since Vitest runs no auto-import transform. */
function stubNitroAutoImports(): void {
    const nitroAutoImports: Record<string, unknown> = {
        createError,
        defineEventHandler,
        eventHandler,
        getHeader,
        getMethod,
        getProxyRequestHeaders,
        getQuery,
        getRequestHeader,
        getRequestHeaders,
        getRequestIP,
        getRequestPath,
        getRequestURL,
        getRouterParam,
        getRouterParams,
        proxyRequest,
        readBody,
        readRawBody,
        sendProxy,
        setResponseHeader,
        setResponseStatus,
    };
    for (const [importName, importValue] of Object.entries(nitroAutoImports)) {
        vi.stubGlobal(importName, importValue);
    }
}

/**
 * Build the web handler for the route table Nitro compiles from `server/api/`: the specific
 * `/api/ingest/**` route beside the backend catch-all, as Nitro's router ranks them.
 */
async function createNitroRouteTable(): Promise<(request: Request) => Promise<Response>> {
    const ingestRouteModule = await import('../../../../server/api/ingest/[...path]');
    const proxyRouteModule = await import('../../../../server/api/[...path]');
    const router = createRouter();
    router.use('/api/ingest/**:path', ingestRouteModule.default as EventHandler);
    router.use('/api/**:path', proxyRouteModule.default as EventHandler);
    const app = createApp();
    app.use(router);
    return toWebHandler(app);
}

afterAll(() => {
    vi.unstubAllGlobals();
});

beforeEach(() => {
    upstreamRequests.length = 0;
    stubNitroAutoImports();
    stubUpstream();
});

describe('the PostHog ingestion proxy at /api/ingest/**', () => {
    it('B-24: forwards an event batch to the PostHog host with its path, query, and body', async () => {
        const handleRequest = await createNitroRouteTable();

        await handleRequest(
            new Request('http://web.test/api/ingest/e/?ip=0&ver=1', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: '{"event":"$pageview"}',
            }),
        );

        expect(upstreamRequests).toHaveLength(1);
        const [ingestRequest] = upstreamRequests;
        expect(ingestRequest!.url).toBe('https://posthog.test/e/?ip=0&ver=1');
        expect(ingestRequest!.method).toBe('POST');
        expect(ingestRequest!.body).toBe('{"event":"$pageview"}');
    });

    it('B-24: never forwards the session cookie to PostHog', async () => {
        const handleRequest = await createNitroRouteTable();

        await handleRequest(
            new Request('http://web.test/api/ingest/flags/?v=2', {
                method: 'POST',
                headers: { cookie: sessionCookie, 'Content-Type': 'application/json' },
                body: '{}',
            }),
        );

        expect(upstreamRequests).toHaveLength(1);
        expect(upstreamRequests[0]!.url).toBe('https://posthog.test/flags/?v=2');
        expect(upstreamRequests[0]!.headers.get('cookie')).toBeNull();
    });

    it.each([
        '/api/ingest/%2e%2e/%2e%2e/api/ingest@169.254.169.254/latest/',
        '/api/ingest/@169.254.169.254/latest/',
        '/api/ingest/api/projects/',
    ])(
        'refuses %s rather than fetching anything but a PostHog ingest endpoint',
        async (hostilePath) => {
            const handleRequest = await createNitroRouteTable();

            const response = await handleRequest(new Request(`http://web.test${hostilePath}`));

            const strayRequests = upstreamRequests.filter(
                (upstreamRequest) => !upstreamRequest.url.startsWith(`${posthogHost}/`),
            );
            expect(strayRequests).toEqual([]);
            expect(
                upstreamRequests.filter((upstreamRequest) =>
                    upstreamRequest.url.startsWith(posthogHost),
                ),
            ).toEqual([]);
            expect(response.status).toBe(404);
        },
    );

    it('forwards no credential or forwarding header from the visitor to PostHog', async () => {
        const handleRequest = await createNitroRouteTable();

        await handleRequest(
            new Request('http://web.test/api/ingest/e/', {
                method: 'POST',
                headers: {
                    authorization: ['Bearer', 'visitor-held-value'].join(' '),
                    'content-type': 'application/json',
                    'x-forwarded-for': '203.0.113.9',
                    'x-request-id': 'req-ingest-0001',
                },
                body: '{}',
            }),
        );

        expect(upstreamRequests).toHaveLength(1);
        const [ingestRequest] = upstreamRequests;
        expect(ingestRequest!.headers.get('authorization')).toBeNull();
        expect(ingestRequest!.headers.get('x-forwarded-for')).toBeNull();
        expect(ingestRequest!.headers.get('content-type')).toBe('application/json');
    });

    it('B-24: leaves every other /api path to the backend proxy', async () => {
        const handleRequest = await createNitroRouteTable();

        await handleRequest(new Request('http://web.test/api/v1/auth/me'));

        expect(upstreamRequests).toHaveLength(1);
        expect(upstreamRequests[0]!.url).toBe('http://api.test/v1/auth/me');
    });
});

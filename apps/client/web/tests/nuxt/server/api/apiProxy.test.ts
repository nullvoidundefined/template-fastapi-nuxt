// @vitest-environment node
/**
 * Tests for the Nitro catch-all proxy `server/api/[...path].ts` (slice 03 PR 3, US-AUTH-003).
 *
 * The route is driven through a real h3 app whose route table reproduces the one Nitro builds
 * from the `server/api/` file names: the specific `/api/health` route and the `/api/**:path`
 * catch-all, registered in that order, so route precedence, the router parameter, and h3's own
 * `proxyRequest` all behave as they do in the built server. Only the backend is stubbed, by
 * replacing the global fetch that `proxyRequest` resolves at call time, so every assertion reads
 * the request the backend would actually have received or the response the browser would
 * actually have received. The node environment is used because these are server modules and h3
 * needs the platform Request, Response, and stream implementations rather than happy-dom's.
 *
 * The route modules are imported after the Nitro auto-imports are stubbed as globals, the same
 * way `health.test.ts` does it, because Vitest does not run Nitro's auto-import transform.
 *
 * `useRuntimeConfig` is the one exception, and the trap for the next Nitro test written here.
 * Vitest's Nuxt environment applies Nuxt's *app* auto-import transform to every file in the
 * project, `server/` included, and `useRuntimeConfig` is a name in both the app and the Nitro
 * auto-import sets. So the route's bare `useRuntimeConfig(event)` is rewritten to an import of the
 * app implementation from `#app/nuxt`, which needs a Nuxt app instance and throws `NUXT_E1001`
 * under a bare h3 event; the global stub is never consulted. `mockNuxtImport` replaces the module
 * the transform actually imports, which is the only interception point that works. Nitro-only
 * names such as `getRequestHeader` and `proxyRequest` have no app-side namesake, are left alone by
 * the transform, and are still served by the globals below.
 */
import {
    appendResponseHeader,
    createApp,
    createError,
    createRouter,
    defineEventHandler,
    eventHandler,
    getCookie,
    getHeader,
    getHeaders,
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
    parseCookies,
    proxyRequest,
    readBody,
    readRawBody,
    sendProxy,
    sendRedirect,
    setHeader,
    setHeaders,
    setResponseHeader,
    setResponseHeaders,
    setResponseStatus,
    splitCookiesString,
    toWebHandler,
    type EventHandler,
} from 'h3';
import { describe, it, expect, afterAll, beforeEach, vi } from 'vitest';
import { mockNuxtImport } from '@nuxt/test-utils/runtime';

type BackendRequest = {
    url: string;
    method: string;
    headers: Headers;
    body: string | undefined;
};

type BackendResponseSpec = {
    status: number;
    headers: Record<string, string>;
    body: string;
};

// Hoisted, because the mockNuxtImport factory below is lifted above these declarations.
const backendBaseUrl = vi.hoisted(() => 'http://api.test');
const csrfHeaderValue = 'XMLHttpRequest';
// Built from parts so no credential-shaped literal is written down (R-108).
const sessionCookie = ['session=', ['issued', 'by', 'the', 'backend'].join('-')].join('');
const setCookieHeaderValue = [sessionCookie, 'Path=/', 'HttpOnly', 'SameSite=Lax', 'Secure'].join(
    '; ',
);
// The first entry is client-supplied and forgeable; the last is the one the edge appended.
const forgedForwardedForEntry = '203.0.113.9';
const edgeAppendedForwardedForEntry = '198.51.100.4';
const forwardedForChain = [forgedForwardedForEntry, edgeAppendedForwardedForEntry].join(', ');

// The route reads its base URL through `useRuntimeConfig`, which the app auto-import transform
// rewrites into an import; see the file docstring for why a global stub cannot reach it.
mockNuxtImport('useRuntimeConfig', () => () => ({ apiBaseUrl: backendBaseUrl }));

const backendRequests: BackendRequest[] = [];

/** Record the outgoing request and answer with the given response, standing in for FastAPI. */
function stubBackend({ status, headers, body }: BackendResponseSpec): void {
    vi.stubGlobal(
        'fetch',
        async (target: string | URL | Request, options?: RequestInit): Promise<Response> => {
            backendRequests.push({
                url: String(target),
                method: options?.method ?? 'GET',
                headers: new Headers((options?.headers ?? {}) as HeadersInit),
                body: readOutgoingBody(options?.body),
            });
            return new Response(body, { status, headers });
        },
    );
}

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

/**
 * Build the web handler for the route table Nitro compiles from `server/api/`.
 *
 * The route modules are imported here rather than in a `beforeAll` so that a module that does not
 * exist yet fails each test rather than skipping the file.
 */
async function createNitroRouteTable(): Promise<(request: Request) => Promise<Response>> {
    const proxyRouteModule = await import('../../../../server/api/[...path]');
    const healthRouteModule = await import('../../../../server/api/health.get');
    const router = createRouter();
    router.get('/api/health', healthRouteModule.default as EventHandler);
    router.use('/api/**:path', proxyRouteModule.default as EventHandler);
    const app = createApp();
    app.use(router);
    return toWebHandler(app);
}

/** Put the Nitro auto-imports on globalThis, since Vitest runs no auto-import transform. */
function stubNitroAutoImports(): void {
    const nitroAutoImports: Record<string, unknown> = {
        appendResponseHeader,
        createError,
        defineEventHandler,
        eventHandler,
        getCookie,
        getHeader,
        getHeaders,
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
        parseCookies,
        proxyRequest,
        readBody,
        readRawBody,
        sendProxy,
        sendRedirect,
        setHeader,
        setHeaders,
        setResponseHeader,
        setResponseHeaders,
        setResponseStatus,
        splitCookiesString,
    };
    for (const [importName, importValue] of Object.entries(nitroAutoImports)) {
        vi.stubGlobal(importName, importValue);
    }
}

afterAll(() => {
    vi.unstubAllGlobals();
});

beforeEach(() => {
    backendRequests.length = 0;
    stubNitroAutoImports();
    stubBackend({ status: 200, headers: { 'Content-Type': 'application/json' }, body: '{}' });
});

describe('the Nitro catch-all proxy at /api/**', () => {
    it('US-AUTH-003: forwards the query string with the path, so /api/v1/trips?page=2 reaches /v1/trips?page=2', async () => {
        const handleRequest = await createNitroRouteTable();

        await handleRequest(new Request('http://web.test/api/v1/trips?page=2&sort=name'));

        expect(backendRequests).toHaveLength(1);
        expect(backendRequests[0]!.url).toBe('http://api.test/v1/trips?page=2&sort=name');
    });

    it('US-AUTH-003: propagates the backend Set-Cookie header and status to the browser', async () => {
        stubBackend({
            status: 201,
            headers: { 'Content-Type': 'application/json', 'Set-Cookie': setCookieHeaderValue },
            body: '{"data":{"id":1}}',
        });
        const handleRequest = await createNitroRouteTable();

        const proxyResponse = await handleRequest(
            new Request('http://web.test/api/v1/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: '{"email":"person@example.test"}',
            }),
        );

        expect(proxyResponse.status).toBe(201);
        expect(proxyResponse.headers.get('set-cookie')).toBe(setCookieHeaderValue);
    });

    it('US-AUTH-003: passes the session cookie, the CSRF header, and the body through to the backend', async () => {
        const handleRequest = await createNitroRouteTable();

        await handleRequest(
            new Request('http://web.test/api/v1/auth/logout', {
                method: 'POST',
                headers: {
                    cookie: sessionCookie,
                    'X-Requested-With': csrfHeaderValue,
                    'Content-Type': 'application/json',
                },
                body: '{"email":"person@example.test"}',
            }),
        );

        expect(backendRequests).toHaveLength(1);
        const [backendRequest] = backendRequests;
        expect(backendRequest!.url).toBe('http://api.test/v1/auth/logout');
        expect(backendRequest!.method).toBe('POST');
        expect(backendRequest!.headers.get('cookie')).toBe(sessionCookie);
        expect(backendRequest!.headers.get('x-requested-with')).toBe(csrfHeaderValue);
        expect(backendRequest!.body).toBe('{"email":"person@example.test"}');
    });

    it('US-AUTH-003: replaces the X-Forwarded-For chain with the edge-appended address, so a forged entry cannot rotate the rate-limit bucket', async () => {
        const handleRequest = await createNitroRouteTable();

        await handleRequest(
            new Request('http://web.test/api/v1/auth/login', {
                method: 'POST',
                headers: {
                    'X-Forwarded-For': forwardedForChain,
                    'Content-Type': 'application/json',
                },
                body: '{"email":"person@example.test"}',
            }),
        );

        expect(backendRequests).toHaveLength(1);
        expect(backendRequests[0]!.headers.get('x-forwarded-for')).toBe(
            edgeAppendedForwardedForEntry,
        );
    });

    it('US-AUTH-003: answers /api/health from the Nuxt server itself, never through the proxy', async () => {
        const handleRequest = await createNitroRouteTable();

        const healthResponse = await handleRequest(new Request('http://web.test/api/health'));

        expect(healthResponse.status).toBe(200);
        await expect(healthResponse.json()).resolves.toEqual({ status: 'ok' });
        expect(backendRequests).toEqual([]);
    });

    it.each([
        '/api/v1/%2e%2e/openapi.json',
        '/api/v1/%2E%2e/%2e%2E/docs',
        '/api/v1/./../health/ready',
    ])(
        'refuses %s, whose dot segments would climb out of /v1 once fetch resolves them',
        async (climbingPath) => {
            const handleRequest = await createNitroRouteTable();

            const response = await handleRequest(new Request(`http://web.test${climbingPath}`));

            expect(backendRequests).toEqual([]);
            expect(response.status).toBe(404);
        },
    );
});

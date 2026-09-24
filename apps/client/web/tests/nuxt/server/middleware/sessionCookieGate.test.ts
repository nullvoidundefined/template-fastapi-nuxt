// @vitest-environment node
/**
 * Tests for the Nitro session-cookie gate `server/middleware/sessionCookieGate.ts` (B-12, slice
 * 03 PR 3, US-AUTH-003).
 *
 * The gate is the cheap half of the three-part auth gate (`CLAUDE-FRONTEND-NUXT.md`, Auth
 * gating): on a full page request with no session cookie it redirects to `/login`, and that is
 * all it does. It never calls the backend, never parses the cookie, and never decides whether a
 * session is still valid, because it runs in the Node process on every single request; the real
 * verification happens once per navigation in `app/middleware/requireSession.ts`. So the test for
 * a present cookie deliberately sends a junk value: a gate that tried to validate it would fail
 * that test, and failing it is the point.
 *
 * The gate is driven through a real h3 app arranged the way Nitro arranges one: the middleware
 * first for every request, then a route table holding the pages, the asset paths, and the real
 * `/api/**` proxy, so the API case reaches the proxy and comes back with the backend's own status
 * rather than with an HTML redirect. Only the backend is stubbed, by replacing global fetch.
 *
 * Path policy under test: the gate is closed by default. Every page path is protected unless it
 * is one of the handful of public ones, so a page added later without touching the gate is gated
 * rather than exposed, which is the direction this mistake should fail in. `/api/**` and asset
 * paths are skipped before that decision is reached.
 *
 * `useRuntimeConfig` is mocked through `mockNuxtImport` rather than stubbed as a global for the
 * reason recorded in `tests/nuxt/server/api/apiProxy.test.ts`: Vitest's Nuxt environment rewrites
 * that one name in `server/` code to an import of Nuxt's app implementation, so a global stub is
 * never consulted. The proxy route imported here reads its base URL that way.
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

type BackendResponseSpec = {
    status: number;
    headers: Record<string, string>;
    body: string;
};

// Hoisted, because the mockNuxtImport factory below is lifted above these declarations.
const backendBaseUrl = vi.hoisted(() => 'http://api.test');
const loginPath = '/login';
const landingPath = '/';
const protectedPagePath = '/dashboard';
// A page nobody has told the gate about, standing in for the `/settings` added next month.
const unregisteredPagePath = '/settings';
const nuxtAssetPath = '/_nuxt/entry.CJd8Xb1p.js';
const faviconPath = '/favicon.ico';
const apiPath = '/api/v1/auth/me';
const pageRequestHeaders = { accept: 'text/html,application/xhtml+xml' };
// Confirmed against apps/server/app/constants/session.py; the value is built from parts so no
// credential-shaped literal is written down (R-108).
const sessionCookieName = 'sid';
const junkSessionCookie = [sessionCookieName, ['expired', 'or', 'outright', 'junk'].join('-')].join(
    '=',
);
const backendUnauthorizedBody = '{"error":"Authentication required","code":"AUTH_REQUIRED"}';

const backendRequests: string[] = [];

// The route reads its base URL through `useRuntimeConfig`, which the app auto-import transform
// rewrites into an import; see the file docstring for why a global stub cannot reach it.
mockNuxtImport('useRuntimeConfig', () => () => ({ apiBaseUrl: backendBaseUrl }));

/** Record the outgoing request and answer with the given response, standing in for FastAPI. */
function stubBackend({ status, headers, body }: BackendResponseSpec): void {
    vi.stubGlobal('fetch', async (target: string | URL | Request): Promise<Response> => {
        backendRequests.push(String(target));
        return new Response(body, { status, headers });
    });
}

/** Answer as a rendered page or asset would, so the test can tell what served the request. */
function createBodyHandler(responseBody: string): EventHandler {
    return defineEventHandler(() => responseBody);
}

/**
 * Build the web handler for Nitro's order: server middleware first, then the route table.
 *
 * The gate is imported here rather than in a `beforeAll` so that a module that does not exist yet
 * fails each test rather than skipping the file. `/settings` is deliberately absent from the
 * table: when the gate lets it through the router answers 404, which is distinguishable from the
 * 302 a closed gate produces.
 */
async function createNitroRequestPipeline(): Promise<(request: Request) => Promise<Response>> {
    const sessionCookieGateModule = await import('../../../../server/middleware/sessionCookieGate');
    const proxyRouteModule = await import('../../../../server/api/[...path]');
    const router = createRouter();
    router.get(landingPath, createBodyHandler('landing page'));
    router.get(loginPath, createBodyHandler('login page'));
    router.get('/forgot-password', createBodyHandler('forgot page'));
    router.get('/reset-password', createBodyHandler('reset page'));
    router.get(protectedPagePath, createBodyHandler('dashboard page'));
    router.get('/_nuxt/**:assetPath', createBodyHandler('built asset'));
    router.get(faviconPath, createBodyHandler('favicon'));
    router.use('/api/**:path', proxyRouteModule.default as EventHandler);
    const app = createApp();
    app.use(sessionCookieGateModule.default as EventHandler);
    app.use(router);
    return toWebHandler(app);
}

/** Send one request through the pipeline with the given headers. */
async function sendRequest(path: string, headers: Record<string, string> = {}): Promise<Response> {
    const handleRequest = await createNitroRequestPipeline();
    return handleRequest(new Request(`http://web.test${path}`, { headers }));
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

describe('the Nitro session-cookie gate', () => {
    it('B-12: redirects a signed-out page request for a protected path to /login with 302, without asking the backend', async () => {
        const gateResponse = await sendRequest(protectedPagePath, pageRequestHeaders);

        expect(gateResponse.status).toBe(302);
        expect(gateResponse.headers.get('location')).toBe(loginPath);
        expect(backendRequests).toEqual([]);
    });

    it('B-12: gates a page path the gate was never told about, so a page added later is protected rather than exposed', async () => {
        const gateResponse = await sendRequest(unregisteredPagePath, pageRequestHeaders);

        expect(gateResponse.status).toBe(302);
        expect(gateResponse.headers.get('location')).toBe(loginPath);
    });

    it('B-12: lets a page request carrying any session cookie through, because validity is the app-side middleware', async () => {
        const pageResponse = await sendRequest(protectedPagePath, {
            ...pageRequestHeaders,
            cookie: junkSessionCookie,
        });

        expect(pageResponse.status).toBe(200);
        await expect(pageResponse.text()).resolves.toBe('dashboard page');
        expect(pageResponse.headers.get('location')).toBeNull();
    });

    it('B-12: leaves /api/** alone, so a signed-out API call gets the backend 401 rather than a redirect to HTML', async () => {
        stubBackend({
            status: 401,
            headers: { 'Content-Type': 'application/json' },
            body: backendUnauthorizedBody,
        });

        const apiResponse = await sendRequest(apiPath, { accept: 'application/json' });

        expect(apiResponse.status).toBe(401);
        expect(apiResponse.headers.get('location')).toBeNull();
        await expect(apiResponse.text()).resolves.toBe(backendUnauthorizedBody);
        expect(backendRequests).toEqual(['http://api.test/v1/auth/me']);
    });

    it('B-12: leaves asset paths alone, so a signed-out visitor still gets the scripts and icons', async () => {
        const assetResponse = await sendRequest(nuxtAssetPath);
        const faviconResponse = await sendRequest(faviconPath);

        expect(assetResponse.status).toBe(200);
        await expect(assetResponse.text()).resolves.toBe('built asset');
        expect(faviconResponse.status).toBe(200);
        await expect(faviconResponse.text()).resolves.toBe('favicon');
    });

    it('B-12: does not gate the public pages, so /login never redirects to itself', async () => {
        const landingResponse = await sendRequest(landingPath, pageRequestHeaders);
        const loginResponse = await sendRequest(loginPath, pageRequestHeaders);

        expect(landingResponse.status).toBe(200);
        await expect(landingResponse.text()).resolves.toBe('landing page');
        expect(loginResponse.status).toBe(200);
        await expect(loginResponse.text()).resolves.toBe('login page');
    });

    it.each(['/forgot-password', '/reset-password'])(
        'B-36: does not gate %s, which a signed-out visitor must reach to recover the account',
        async (recoveryPath) => {
            const recoveryResponse = await sendRequest(
                `${recoveryPath}?token=abc`,
                pageRequestHeaders,
            );

            expect(recoveryResponse.status).toBe(200);
        },
    );
});

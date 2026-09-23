// @vitest-environment node
/**
 * Tests for the Nitro request-ID middleware `server/middleware/requestId.ts` (R-341, slice 03
 * PR 3, US-AUTH-003).
 *
 * The middleware is driven through a real h3 app arranged the way Nitro arranges a page request:
 * the middleware runs first for every request, then a page handler stands in for server-side
 * rendering by building the real server-side API client exactly as `useApiClient` does, through
 * `buildServerApiClientOptions`, and calling FastAPI once. The page handler reads its forwarded
 * headers the way Nuxt's `useRequestHeaders(include)` reads them, through h3's
 * `getRequestHeaders(event)` filtered to the same three names, so a middleware that sets only the
 * response header is invisible to the client and fails these tests, which is the point: FastAPI
 * would then mint its own ID and the page would correlate to nothing.
 *
 * Only the backend is stubbed, by replacing global fetch, so each assertion reads the request
 * FastAPI would actually have received and the response the browser would actually have received.
 * The node environment is used because these are server modules needing the platform Request,
 * Response, and stream implementations rather than happy-dom's.
 *
 * The backend accepts 1 to 64 characters of [A-Za-z0-9._-] as an inbound ID and mints a fresh one
 * otherwise (`CLAUDE-PYTHON.md`, Observability); Nitro applies the same rule so a rejected value
 * never leaves the edge. The unsafe fixtures are built at run time: a carriage return cannot be
 * put on a Request at all (undici refuses the header), so the whitespace case uses a tab, which is
 * a legal header value and equally outside the safe set.
 */
import {
    appendResponseHeader,
    createApp,
    createError,
    defineEventHandler,
    eventHandler,
    getCookie,
    getHeader,
    getHeaders,
    getMethod,
    getRequestHeader,
    getRequestHeaders,
    getRequestIP,
    getRequestPath,
    getRequestURL,
    parseCookies,
    sendRedirect,
    setHeader,
    setHeaders,
    setResponseHeader,
    setResponseHeaders,
    setResponseStatus,
    toWebHandler,
    type EventHandler,
    type H3Event,
} from 'h3';
import { describe, it, expect, afterAll, beforeEach, vi } from 'vitest';

import { createApiClient } from '~/api/apiClient';
import { buildServerApiClientOptions } from '~/services/apiClient/buildServerApiClientOptions';

const backendBaseUrl = 'http://api.test';
const pagePath = '/dashboard';
// The only page-request headers the server-side client forwards (spec: Request path).
const forwardedRequestHeaderNames = ['cookie', 'x-request-id', 'x-forwarded-for'];
const safeRequestIdPattern = /^[A-Za-z0-9._-]{1,64}$/;
const validInboundRequestId = 'req-01HZX9.trace_7';
const overLongInboundRequestId = 'a'.repeat(65);
const headerInjectionInboundRequestId = ['req', String.fromCharCode(9), 'x-injected:1'].join('');
const pageRequestHeaders: Record<string, string> = {
    cookie: ['session=', ['sent', 'by', 'the', 'browser'].join('-')].join(''),
    'x-forwarded-for': '198.51.100.4',
};

const backendRequests: Request[] = [];

/** Record the outgoing request and answer 200, standing in for FastAPI. */
function stubBackend(): void {
    vi.stubGlobal(
        'fetch',
        async (target: Request | string | URL, options?: RequestInit): Promise<Response> => {
            backendRequests.push(new Request(target as RequestInfo, options));
            return new Response(JSON.stringify({ status: 'ok' }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
        },
    );
}

/** Read the forwarded headers the way Nuxt's `useRequestHeaders(include)` reads them. */
function readForwardedRequestHeaders(event: H3Event): Record<string, string | undefined> {
    const requestHeaders = getRequestHeaders(event);
    return Object.fromEntries(
        forwardedRequestHeaderNames
            .filter((headerName) => requestHeaders[headerName])
            .map((headerName) => [headerName, requestHeaders[headerName]]),
    );
}

// Stands in for server-side rendering: one page, one server-side API call to FastAPI.
const pageHandler = defineEventHandler(async (event) => {
    const apiClient = createApiClient(
        buildServerApiClientOptions({
            apiBaseUrl: backendBaseUrl,
            requestHeaders: readForwardedRequestHeaders(event),
            socketAddress: event.node.req.socket.remoteAddress,
        }),
    );
    await apiClient.GET('/health');
    return '<!DOCTYPE html><html lang="en"><body>dashboard</body></html>';
});

/**
 * Build the web handler for Nitro's order: server middleware first, then the page.
 *
 * The middleware is imported here rather than in a `beforeAll` so that a module that does not
 * exist yet fails each test rather than skipping the file.
 */
async function createNitroRequestPipeline(): Promise<(request: Request) => Promise<Response>> {
    const requestIdModule = await import('../../../../server/middleware/requestId');
    const app = createApp();
    app.use(requestIdModule.default as EventHandler);
    app.use(pagePath, pageHandler);
    return toWebHandler(app);
}

/** Send one full page request with the given extra headers and return the page response. */
async function requestPage(extraHeaders: Record<string, string> = {}): Promise<Response> {
    const handleRequest = await createNitroRequestPipeline();
    return handleRequest(
        new Request(`http://web.test${pagePath}`, {
            headers: { ...pageRequestHeaders, ...extraHeaders },
        }),
    );
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
        getRequestHeader,
        getRequestHeaders,
        getRequestIP,
        getRequestPath,
        getRequestURL,
        parseCookies,
        sendRedirect,
        setHeader,
        setHeaders,
        setResponseHeader,
        setResponseHeaders,
        setResponseStatus,
        useRuntimeConfig: () => ({ apiBaseUrl: backendBaseUrl }),
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
    stubBackend();
});

describe('the Nitro request-ID middleware', () => {
    it('R-341: mints an ID for a page request carrying none and sends that same ID to both the browser and FastAPI', async () => {
        const pageResponse = await requestPage();

        const mintedRequestId = pageResponse.headers.get('x-request-id');
        expect(mintedRequestId).toMatch(safeRequestIdPattern);
        expect(backendRequests).toHaveLength(1);
        expect(backendRequests[0]!.headers.get('x-request-id')).toBe(mintedRequestId);
    });

    it('R-341: mints a different ID for each page request', async () => {
        const firstPageResponse = await requestPage();
        const secondPageResponse = await requestPage();

        const firstRequestId = firstPageResponse.headers.get('x-request-id');
        const secondRequestId = secondPageResponse.headers.get('x-request-id');
        expect(firstRequestId).toMatch(safeRequestIdPattern);
        expect(secondRequestId).not.toBe(firstRequestId);
    });

    it('R-341: honors a safe inbound X-Request-Id on both the page response and the FastAPI call', async () => {
        const pageResponse = await requestPage({ 'X-Request-Id': validInboundRequestId });

        expect(pageResponse.headers.get('x-request-id')).toBe(validInboundRequestId);
        expect(backendRequests).toHaveLength(1);
        expect(backendRequests[0]!.headers.get('x-request-id')).toBe(validInboundRequestId);
    });

    it('R-341: replaces an inbound X-Request-Id longer than 64 characters rather than passing it on', async () => {
        const pageResponse = await requestPage({ 'X-Request-Id': overLongInboundRequestId });

        const mintedRequestId = pageResponse.headers.get('x-request-id');
        expect(mintedRequestId).not.toBe(overLongInboundRequestId);
        expect(mintedRequestId).toMatch(safeRequestIdPattern);
        expect(backendRequests).toHaveLength(1);
        expect(backendRequests[0]!.headers.get('x-request-id')).toBe(mintedRequestId);
    });

    it('R-341: replaces an inbound X-Request-Id carrying characters outside the safe set rather than passing it on', async () => {
        const pageResponse = await requestPage({ 'X-Request-Id': headerInjectionInboundRequestId });

        const mintedRequestId = pageResponse.headers.get('x-request-id');
        expect(mintedRequestId).not.toBe(headerInjectionInboundRequestId);
        expect(mintedRequestId).toMatch(safeRequestIdPattern);
        expect(backendRequests).toHaveLength(1);
        expect(backendRequests[0]!.headers.get('x-request-id')).toBe(mintedRequestId);
    });
});

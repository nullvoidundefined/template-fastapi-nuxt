// @vitest-environment node
/**
 * Tests that the Nitro request-ID middleware binds its ID to the server-side Sentry scope
 * (spec: the Nuxt track's Sentry section, R-341, slice 07).
 *
 * The middleware already resolves one ID per page request and forwards it to FastAPI; an error
 * Nitro reports while rendering that page should carry the same ID, so the report, the page's
 * logs, and the backend's logs all join on it. `@sentry/nuxt` is replaced at its module boundary
 * with a recording isolation scope, and the middleware runs in a real h3 app as `requestId.test.ts`
 * drives it, so the assertion compares the tag with the ID the response actually carried.
 */
import {
    createApp,
    defineEventHandler,
    eventHandler,
    getRequestHeader,
    setResponseHeader,
    toWebHandler,
    type EventHandler,
} from 'h3';
import { describe, it, expect, afterAll, beforeEach, vi } from 'vitest';

const isolationScopeTags = vi.hoisted(() => [] as Array<[string, unknown]>);

vi.mock('@sentry/nuxt', () => ({
    getIsolationScope: () => ({
        setTag: (name: string, value: unknown) => {
            isolationScopeTags.push([name, value]);
        },
    }),
}));

const validInboundRequestId = 'req-01HZX9.trace_7';

/** Build the pipeline: the middleware, then a page that answers 200. */
async function createNitroRequestPipeline(): Promise<(request: Request) => Promise<Response>> {
    const requestIdModule = await import('../../../../server/middleware/requestId');
    const app = createApp();
    app.use(requestIdModule.default as EventHandler);
    app.use(
        '/dashboard',
        defineEventHandler(() => 'dashboard'),
    );
    return toWebHandler(app);
}

afterAll(() => {
    vi.unstubAllGlobals();
});

beforeEach(() => {
    isolationScopeTags.length = 0;
    for (const [importName, importValue] of Object.entries({
        defineEventHandler,
        eventHandler,
        getRequestHeader,
        setResponseHeader,
    })) {
        vi.stubGlobal(importName, importValue);
    }
});

describe('the request ID on the Nitro Sentry scope', () => {
    it('R-341: an honored inbound ID is set as the request_id tag', async () => {
        const handleRequest = await createNitroRequestPipeline();

        await handleRequest(
            new Request('http://web.test/dashboard', {
                headers: { 'x-request-id': validInboundRequestId },
            }),
        );

        expect(isolationScopeTags).toEqual([['request_id', validInboundRequestId]]);
    });

    it('R-341: a minted ID is the one tagged, matching the response header', async () => {
        const handleRequest = await createNitroRequestPipeline();

        const pageResponse = await handleRequest(new Request('http://web.test/dashboard'));

        expect(isolationScopeTags).toEqual([
            ['request_id', pageResponse.headers.get('x-request-id')],
        ]);
    });
});

/**
 * Unit tests for the typed API client (spec B-4, "Type flow" and "Request path").
 * createApiClient() returns one openapi-fetch client typed by the generated `paths` from
 * @repo/api-types, so every backend call is checked against the committed OpenAPI document.
 * The global fetch is stubbed before each client is created, so the tests observe the exact
 * request the client sends and the way it surfaces a 2xx body in `data` and a non-2xx body in
 * `error`. The header test uses X-Request-Id rather than a cookie because happy-dom's Request
 * drops forbidden headers such as Cookie, which would hide the client's behavior. A never-run
 * branch holds a @ts-expect-error call on an undefined path, so `vue-tsc` in the typecheck script
 * fails if the client stops rejecting routes the document does not define.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { createApiClient } from '~/api/apiClient';

const apiBaseUrl = 'http://api.test';

type FetchInput = Parameters<typeof fetch>[0];

function createJsonResponse(responseBody: unknown, responseStatus: number): Response {
    return new Response(JSON.stringify(responseBody), {
        status: responseStatus,
        headers: { 'Content-Type': 'application/json' },
    });
}

function stubFetchResponding(responseBody: unknown, responseStatus: number): Request[] {
    const sentRequests: Request[] = [];
    vi.stubGlobal('fetch', async (input: FetchInput, init?: RequestInit) => {
        sentRequests.push(new Request(input, init));
        return createJsonResponse(responseBody, responseStatus);
    });
    return sentRequests;
}

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('createApiClient', () => {
    it('B-4: GET /health requests `${baseUrl}/health` with GET and resolves data', async () => {
        const sentRequests = stubFetchResponding({ status: 'ok' }, 200);
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        const { data, error } = await apiClient.GET('/health');

        expect(sentRequests).toHaveLength(1);
        expect(sentRequests[0]?.url).toBe(`${apiBaseUrl}/health`);
        expect(sentRequests[0]?.method).toBe('GET');
        expect(data).toEqual({ status: 'ok' });
        expect(error).toBeUndefined();
    });

    it('B-4: sends the headers passed to createApiClient on every request', async () => {
        const sentRequests = stubFetchResponding({ status: 'ok' }, 200);
        const apiClient = createApiClient({
            baseUrl: apiBaseUrl,
            headers: { 'X-Request-Id': 'req-apiclient-001' },
        });

        await apiClient.GET('/health');

        expect(sentRequests[0]?.headers.get('X-Request-Id')).toBe('req-apiclient-001');
    });

    it('B-4: a 503 from /health/ready resolves with the status and the body in error', async () => {
        const degradedBody = { status: 'degraded', db: 'disconnected' };
        stubFetchResponding(degradedBody, 503);
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        const { data, error, response } = await apiClient.GET('/health/ready');

        expect(response.status).toBe(503);
        expect(error).toEqual(degradedBody);
        expect(data).toBeUndefined();
    });

    it('B-4: rejects a path the OpenAPI document does not define at compile time', () => {
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        if (false as boolean) {
            // @ts-expect-error '/not-a-route' is not a key of the generated paths type.
            void apiClient.GET('/not-a-route');
        }

        expect(typeof apiClient.GET).toBe('function');
    });
});

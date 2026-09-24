// @vitest-environment node
/**
 * Tests for the `GET /v1/auth/me` wrapper (spec: slice 03 PR 3, B-32).
 *
 * The wrapper takes the typed client as its first parameter, makes one call on it, and returns the
 * signed-in user. These tests drive the real openapi-fetch client with a stubbed global fetch, the
 * way `tests/nuxt/api/apiClient.test.ts` does, rather than a fake client: openapi-fetch resolves
 * rather than throwing on an HTTP error, and a fake client that rejected would hide the one
 * behavior that matters here, which is that the wrapper turns a 401 into a thrown
 * `ApiRequestError` carrying the status and the registry code.
 *
 * The status is asserted rather than only the fact of a rejection, because `requireSession` has to
 * tell an expired session (401, redirect to the sign-in page) from a backend outage (5xx, show an
 * error), and both arrive here as a failed query. The file runs in the node environment because the
 * wrapper needs no Nuxt runtime: the caller obtains the client in setup and passes it in.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';

import { createApiClient } from '~/api/apiClient';
import { fetchCurrentUser } from '~/api/fetchCurrentUser';
import { ApiRequestError } from '~/services/apiClient/apiRequestError';

const apiBaseUrl = 'http://api.test';
const signedInUser = { id: '8f4a2f6e-0d5c-4a9b-9a4d-3d6f5e2c1b0a', email: 'reader@example.test' };

type FetchInput = Parameters<typeof fetch>[0];

/** Stub fetch to record every request and answer with the given JSON body, returning the record. */
function stubFetchResponding(responseBody: unknown, responseStatus: number): Request[] {
    const sentRequests: Request[] = [];
    vi.stubGlobal('fetch', async (input: FetchInput, init?: RequestInit) => {
        sentRequests.push(new Request(input, init));
        return new Response(JSON.stringify(responseBody), {
            status: responseStatus,
            headers: { 'Content-Type': 'application/json' },
        });
    });
    return sentRequests;
}

/** Stub fetch to answer with a body the backend never sends, such as a proxy's HTML error page. */
function stubFetchRespondingWithHtml(responseStatus: number): void {
    vi.stubGlobal('fetch', async () => {
        return new Response('<html><body>502 Bad Gateway</body></html>', {
            status: responseStatus,
            headers: { 'Content-Type': 'text/html' },
        });
    });
}

/** Await the call and return whatever it rejected with, or undefined when it resolved. */
async function captureRejection(runCall: () => Promise<unknown>): Promise<unknown> {
    try {
        await runCall();
        return undefined;
    } catch (rejection) {
        return rejection;
    }
}

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('fetchCurrentUser', () => {
    it('B-32: requests GET /v1/auth/me and returns the user out of the data envelope', async () => {
        const sentRequests = stubFetchResponding({ data: signedInUser }, 200);
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        const currentUser = await fetchCurrentUser(apiClient);

        expect(sentRequests).toHaveLength(1);
        expect(sentRequests[0]?.url).toBe(`${apiBaseUrl}/v1/auth/me`);
        expect(sentRequests[0]?.method).toBe('GET');
        expect(currentUser).toEqual(signedInUser);
        expect(currentUser).not.toHaveProperty('data');
    });

    it('B-32: rejects a 401 with an ApiRequestError carrying the status and the registry code', async () => {
        stubFetchResponding({ code: 'AUTH_REQUIRED', error: 'Sign in to continue.' }, 401);
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        const rejection = await captureRejection(() => fetchCurrentUser(apiClient));

        expect(rejection).toBeInstanceOf(ApiRequestError);
        const apiRequestError = rejection as ApiRequestError;
        expect(apiRequestError.status).toBe(401);
        expect(apiRequestError.code).toBe('AUTH_REQUIRED');
        expect(apiRequestError.message).toContain('Sign in to continue.');
    });

    it('B-32: an expired session rejects with AUTH_SESSION_EXPIRED rather than a bare Error', async () => {
        stubFetchResponding(
            { code: 'AUTH_SESSION_EXPIRED', error: 'Your session has expired.' },
            401,
        );
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        const rejection = await captureRejection(() => fetchCurrentUser(apiClient));

        expect(rejection).toBeInstanceOf(ApiRequestError);
        expect((rejection as ApiRequestError).code).toBe('AUTH_SESSION_EXPIRED');
    });

    it('B-32: rejects with the status and no code when the failure body is not the error envelope', async () => {
        stubFetchRespondingWithHtml(502);
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        const rejection = await captureRejection(() => fetchCurrentUser(apiClient));

        expect(rejection).toBeInstanceOf(ApiRequestError);
        const apiRequestError = rejection as ApiRequestError;
        expect(apiRequestError.status).toBe(502);
        expect(apiRequestError.code).toBeUndefined();
    });
});

// @vitest-environment node
/**
 * Tests for the `POST /v1/auth/logout` wrapper (spec: slice 03 PR 3, B-31).
 *
 * Logout answers 204 with no body, which is the case that decides how the shared unwrap helper has
 * to be written: openapi-fetch returns `{ data: undefined, response }` for a 204, so a helper that
 * threw whenever `data` was absent would make every successful sign-out look like a failure, and
 * the mutation's `onSuccess` would never clear the session from the cache. The first test therefore
 * asserts the call resolves, and the negative case asserts that a failure with an empty body still
 * carries the status, which is the other half of the same trap: openapi-fetch hands back
 * `{ error: undefined, response }` when a non-2xx response has nothing to parse.
 *
 * The real client runs against a stubbed global fetch in the node environment, as in
 * `tests/nuxt/api/apiClient.test.ts`.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';

import { createApiClient } from '~/api/apiClient';
import { signOutUser } from '~/api/signOutUser';
import { ApiRequestError } from '~/services/apiClient/apiRequestError';

const apiBaseUrl = 'http://api.test';

type FetchInput = Parameters<typeof fetch>[0];

/** Stub fetch to record every request and answer with an empty body, returning the record. */
function stubFetchRespondingWithoutBody(responseStatus: number): Request[] {
    const sentRequests: Request[] = [];
    vi.stubGlobal('fetch', async (input: FetchInput, init?: RequestInit) => {
        sentRequests.push(new Request(input, init));
        return new Response(null, { status: responseStatus });
    });
    return sentRequests;
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

describe('signOutUser', () => {
    it('B-31: posts to /v1/auth/logout and resolves on the bodyless 204', async () => {
        const sentRequests = stubFetchRespondingWithoutBody(204);
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        const signOutResult = await signOutUser(apiClient);

        expect(sentRequests).toHaveLength(1);
        expect(sentRequests[0]?.url).toBe(`${apiBaseUrl}/v1/auth/logout`);
        expect(sentRequests[0]?.method).toBe('POST');
        expect(signOutResult).toBeUndefined();
    });

    it('B-31: sends the CSRF header the backend requires of a state-changing request', async () => {
        const sentRequests = stubFetchRespondingWithoutBody(204);
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        await signOutUser(apiClient);

        expect(sentRequests[0]?.headers.get('X-Requested-With')).toBe('XMLHttpRequest');
    });

    it('B-31: rejects with an ApiRequestError carrying the status when the response has no body', async () => {
        stubFetchRespondingWithoutBody(401);
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        const rejection = await captureRejection(() => signOutUser(apiClient));

        expect(rejection).toBeInstanceOf(ApiRequestError);
        const apiRequestError = rejection as ApiRequestError;
        expect(apiRequestError.status).toBe(401);
        expect(apiRequestError.code).toBeUndefined();
    });
});

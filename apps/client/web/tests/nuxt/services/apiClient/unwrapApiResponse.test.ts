// @vitest-environment node
/**
 * Unit tests for the helper that turns openapi-fetch's return into a value or a throw
 * (spec: slice 03 PR 3, "the query layer").
 *
 * openapi-fetch never throws on an HTTP error. It resolves with `{ data, error, response }`, and a
 * query whose function resolves is a successful query, so without this helper a 401 would reach a
 * component as data. The helper therefore returns `data` when the response succeeded and throws an
 * `ApiRequestError` carrying the status and the registry code when it did not.
 *
 * The cases below are the three shapes openapi-fetch actually produces, and they are the reason the
 * decision has to be made on `response.ok` rather than on the presence of `error` or of `data`.
 * A 204 succeeds with no body at all, so `data` is undefined on a success; and openapi-fetch reads
 * the body by content type, so a failure whose body is not JSON arrives as a bare string rather than
 * as the backend's `{ code, error }` envelope. The file runs in the node environment, like
 * `tests/nuxt/api/apiClient.test.ts`, because nothing here needs the Nuxt runtime.
 */
import { describe, it, expect } from 'vitest';

import { ApiRequestError } from '~/services/apiClient/apiRequestError';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';

const signedInUser = { id: '8f4a2f6e-0d5c-4a9b-9a4d-3d6f5e2c1b0a', email: 'reader@example.test' };

/** Return an empty response carrying only the status the backend answered with. */
function createResponseWithStatus(responseStatus: number): Response {
    return new Response(null, { status: responseStatus });
}

/** Run the helper and return whatever it threw, or undefined when it returned instead. */
function captureThrown(runHelper: () => unknown): unknown {
    try {
        runHelper();
        return undefined;
    } catch (thrown) {
        return thrown;
    }
}

describe('unwrapApiResponse', () => {
    it('returns the data of a successful response', () => {
        const unwrapped = unwrapApiResponse({
            data: signedInUser,
            response: createResponseWithStatus(200),
        });

        expect(unwrapped).toEqual(signedInUser);
    });

    it('returns undefined for a 204, where a success carries no body', () => {
        const unwrapped = unwrapApiResponse({
            data: undefined,
            response: createResponseWithStatus(204),
        });

        expect(unwrapped).toBeUndefined();
    });

    it('throws an ApiRequestError carrying the status, the code, and the message of the envelope', () => {
        const thrown = captureThrown(() =>
            unwrapApiResponse({
                error: { code: 'AUTH_REQUIRED', error: 'Sign in to continue.' },
                response: createResponseWithStatus(401),
            }),
        );

        expect(thrown).toBeInstanceOf(ApiRequestError);
        const apiRequestError = thrown as ApiRequestError;
        expect(apiRequestError.status).toBe(401);
        expect(apiRequestError.code).toBe('AUTH_REQUIRED');
        expect(apiRequestError.message).toContain('Sign in to continue.');
    });

    it('throws with the status and no code when the failure body is not the error envelope', () => {
        const thrown = captureThrown(() =>
            unwrapApiResponse({
                error: '<html><body>502 Bad Gateway</body></html>',
                response: createResponseWithStatus(502),
            }),
        );

        expect(thrown).toBeInstanceOf(ApiRequestError);
        const apiRequestError = thrown as ApiRequestError;
        expect(apiRequestError.status).toBe(502);
        expect(apiRequestError.code).toBeUndefined();
    });

    it('throws with the status when a failed response carries no body for openapi-fetch to parse', () => {
        const thrown = captureThrown(() =>
            unwrapApiResponse({
                error: undefined,
                response: createResponseWithStatus(401),
            }),
        );

        expect(thrown).toBeInstanceOf(ApiRequestError);
        const apiRequestError = thrown as ApiRequestError;
        expect(apiRequestError.status).toBe(401);
        expect(apiRequestError.code).toBeUndefined();
    });
});

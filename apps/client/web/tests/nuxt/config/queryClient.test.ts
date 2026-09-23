// @vitest-environment node
/**
 * Tests for the query client's shared configuration (spec: slice 03 PR 3, "the query layer").
 *
 * The options are built by a function rather than held in a module-level object because every
 * request gets its own `QueryClient` built from them, and the test below drives a real client
 * constructed from the returned options rather than reading the object's shape, since two different
 * shapes (`retry: false` and a retry predicate that excludes 4xx) satisfy the same requirement.
 *
 * The requirement is that an authentication failure fails the query at once. `requireSession`
 * redirects to the sign-in page when the session query answers 401, so retrying a 401 delays the
 * redirect by the whole backoff schedule and leaves a signed-out visitor looking at a loading state
 * for several seconds. A server error is a different case and this file does not constrain it.
 */
import { describe, it, expect } from 'vitest';
import { QueryClient } from '@tanstack/vue-query';

import { buildQueryClientOptions } from '~/config/queryClient';
import { ApiRequestError } from '~/services/apiClient/apiRequestError';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';

/** Await the call and return whatever it rejected with, or undefined when it resolved. */
async function captureRejection(runCall: () => Promise<unknown>): Promise<unknown> {
    try {
        await runCall();
        return undefined;
    } catch (rejection) {
        return rejection;
    }
}

describe('buildQueryClientOptions', () => {
    it('fails a query on a 401 at the first attempt rather than retrying the session away', async () => {
        const queryClient = new QueryClient(buildQueryClientOptions());
        let attemptCount = 0;
        const readExpiredSession = async (): Promise<unknown> => {
            attemptCount += 1;
            return unwrapApiResponse({
                error: { code: 'AUTH_SESSION_EXPIRED', error: 'Your session has expired.' },
                response: new Response(null, { status: 401 }),
            });
        };

        const rejection = await captureRejection(() =>
            queryClient.fetchQuery({
                queryKey: ['config-probe-session'],
                queryFn: readExpiredSession,
            }),
        );

        expect(rejection).toBeInstanceOf(ApiRequestError);
        expect((rejection as ApiRequestError).status).toBe(401);
        expect(attemptCount).toBe(1);
    }, 3000);
});

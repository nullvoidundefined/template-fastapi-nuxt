/**
 * The options every request's query client is built from (spec: slice 03 PR 3).
 *
 * A function rather than a shared object, because each request builds its own client and a shared
 * object would hand every one of them the same mutable defaults.
 *
 * The retry rule is the part that matters. `requireSession` redirects to the sign-in page when the
 * session query answers 401, so retrying a 401 through the whole backoff schedule leaves a
 * signed-out visitor watching a loading state for several seconds before the redirect they should
 * have had at once. A refusal the client caused will not change on a second attempt; a server
 * error might, so that one is still retried.
 */
import type { QueryClientConfig } from '@tanstack/vue-query';

import { ApiRequestError } from '~/services/apiClient/apiRequestError';

const MAX_QUERY_ATTEMPTS = 2;
const FIRST_SERVER_ERROR_STATUS = 500;

/** Return the defaults a `QueryClient` for one request is constructed with. */
export function buildQueryClientOptions(): QueryClientConfig {
    return {
        defaultOptions: {
            queries: { retry: shouldRetryFailedQuery },
            mutations: { retry: false },
        },
    };
}

/** Retry a server error a bounded number of times, and never a refusal the client caused. */
function shouldRetryFailedQuery(failureCount: number, error: Error): boolean {
    if (error instanceof ApiRequestError && error.status < FIRST_SERVER_ERROR_STATUS) {
        return false;
    }
    return failureCount < MAX_QUERY_ATTEMPTS - 1;
}

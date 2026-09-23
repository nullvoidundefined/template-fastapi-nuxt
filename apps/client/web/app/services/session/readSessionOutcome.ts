/**
 * Asks the backend who is signed in and classifies the answer (spec: B-12, B-45).
 *
 * Both route middlewares need the same three-way answer and must not disagree about it, so the
 * classification lives here rather than twice. The distinction that matters is between a visitor
 * the backend does not recognize and a backend that cannot answer: sending someone to the sign-in
 * page because the API is down signs them out for a reason that has nothing to do with them, and
 * it is the kind of fault nobody notices until it happens in production.
 *
 * It fetches rather than reading the cache. A session that expired while a tab sat open would
 * otherwise let the visitor navigate the whole protected area until the entry went stale on its
 * own, which is the opposite of what a gate is for.
 */
import type { QueryClient } from '@tanstack/vue-query';

import type { ApiClient } from '~/api/apiClient';
import { type CurrentUser, fetchCurrentUser } from '~/api/fetchCurrentUser';
import { sessionQueryKey } from '~/composables/useSessionQuery';
import { ApiRequestError } from '~/services/apiClient/apiRequestError';

const FIRST_SERVER_ERROR_STATUS = 500;
const SESSION_UNAVAILABLE_STATUS = 503;

export type SessionOutcome =
    | { state: 'signedIn'; user: CurrentUser }
    | { state: 'signedOut' }
    | { state: 'unavailable'; status: number };

/** Return who is signed in, that nobody is, or that the backend could not say. */
export async function readSessionOutcome(
    queryClient: QueryClient,
    apiClient: ApiClient,
): Promise<SessionOutcome> {
    try {
        const user = await queryClient.fetchQuery({
            queryKey: sessionQueryKey,
            queryFn: () => fetchCurrentUser(apiClient),
        });
        return { state: 'signedIn', user };
    } catch (err) {
        return classifySessionFailure(err);
    }
}

/** Read a rejected session request as either a signed-out visitor or an unreachable backend. */
function classifySessionFailure(err: unknown): SessionOutcome {
    if (err instanceof ApiRequestError && err.status < FIRST_SERVER_ERROR_STATUS) {
        return { state: 'signedOut' };
    }
    const status = err instanceof ApiRequestError ? err.status : SESSION_UNAVAILABLE_STATUS;
    return { state: 'unavailable', status };
}

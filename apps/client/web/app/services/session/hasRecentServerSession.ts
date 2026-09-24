/**
 * Tells the protected-route gate whether the session in the cache is recent enough to have come
 * from the server render being hydrated right now (IAN-335, spec: B-12).
 *
 * A render the browser hydrates as it arrives carries a session the server fetched moments ago.
 * A render replayed from the HTTP cache, by Back after signing out, carries one fetched long ago
 * that may since have been revoked. Page responses are sent `no-store` so the replay should never
 * happen, and this check is the second line: a session older than the window is revalidated
 * rather than trusted. The window is generous for a slow page load and tiny next to a session's
 * lifetime; a client clock far ahead of the server's only costs one extra request.
 */
import type { QueryClient } from '@tanstack/vue-query';

import { sessionQueryKey } from '~/composables/useSessionQuery';

const RECENT_SESSION_WINDOW_MILLISECONDS = 30 * 1000;

/** Return true when the cache holds a session fetched within the recent-render window. */
export function hasRecentServerSession(queryClient: QueryClient): boolean {
    const sessionState = queryClient.getQueryState(sessionQueryKey);
    if (!sessionState || sessionState.data === undefined) {
        return false;
    }
    return Date.now() - sessionState.dataUpdatedAt < RECENT_SESSION_WINDOW_MILLISECONDS;
}

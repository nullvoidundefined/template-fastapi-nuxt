/**
 * Tells the protected-route gate whether the session in the cache is recent enough to have come
 * from the server render being hydrated right now (IAN-335, spec: B-12).
 *
 * This governs only what happens after hydration: whether the gate asks the backend again or
 * trusts the render. It cannot stop a stale page from being seen, because server-rendered HTML
 * paints before any script runs. The control that prevents a revoked session's page from being
 * shown at all is the `Cache-Control: no-store` that `server/middleware/sessionCookieGate.ts`
 * sets on every page response, so that header must never be weakened on the strength of this
 * check.
 *
 * A render the browser hydrates as it arrives carries a session the server fetched moments ago;
 * a replayed render carries one fetched long ago. A session older than the window, or dated after
 * the browser's clock, is revalidated rather than trusted. The window compares the server's clock
 * with the browser's, so skew in either direction only ever costs one extra request: a browser
 * clock ahead of the server's ages a fresh session past the window, and one behind the server's
 * dates it in the future, which is refused rather than read as brand new.
 */
import type { QueryClient } from '@tanstack/vue-query';

import { sessionQueryKey } from '~/composables/useSessionQuery';

// Thirty seconds.
const RECENT_SESSION_WINDOW_MILLISECONDS = 30_000;

/** Return true when the cache holds a session fetched within the recent-render window. */
export function hasRecentServerSession(queryClient: QueryClient): boolean {
    const sessionState = queryClient.getQueryState(sessionQueryKey);
    if (!sessionState) {
        return false;
    }
    const { data: cachedSession, dataUpdatedAt } = sessionState;
    const sessionAgeMilliseconds = Date.now() - dataUpdatedAt;
    return (
        cachedSession !== undefined &&
        sessionAgeMilliseconds >= 0 &&
        sessionAgeMilliseconds < RECENT_SESSION_WINDOW_MILLISECONDS
    );
}
